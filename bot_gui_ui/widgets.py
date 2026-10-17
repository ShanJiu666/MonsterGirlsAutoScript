# -*- coding: utf-8 -*-
"""bot_gui_ui.widgets · 组件层（状态灯 / 仪表盘小卡 / 迷你曲线 / 柱状图 / 实时棋盘）

出处：UI 重设计方案
    · **§4.4 核心组件清单** —— 状态灯、仪表盘四卡、体力曲线 sparkline、
      每图耗时柱状、**实时棋盘 5×7 Canvas**（现 UI 完全没有、数据现成的最大增值点）；
    · **§4.5 视觉风格规范** —— 棋盘配色 / 状态灯 6 态 / 卡片间距；
    · **附录 E.2 实时棋盘** —— 数据格式与几何（`GRID_X0=24, GRID_Y0=668,
      GRID_CX=GRID_CY=96, COLS=7, ROWS=5`，720×1280 基准，`mapbot.py`）。

⭐⭐ 两条硬纪律：
    ① **本文件不许出现任何硬编码色值/字体** —— 一律 `theme.C_XXX` / `theme.FONT_XXX`
      （这正是痛点 P2「样式散落」的修法 ✓）；
    ② 一切公开方法对**坏数据容错不抛** —— GUI 跑在 pythonw（无控制台），
      抛了用户看不见 ✗ ⇒ 解析函数（`_rc` / `_floats` / `_norm_*`）对任何输入
      只返回"空"，**不抛也不猜**；绘制方法整体 `try/except` 兜底 ✓。

⭐ 棋盘数据口径（**逐字照附录 E.2**，全部 **1 基**、键是 `"行,列"` 字符串）::

    board = {"1,1": ["221", "阴暗古墓", 0.723, 0.651],   # [sid后缀, 地块名, score, ratio]
             "2,7": ["000", "营地", 0.978, 0.988], ...}
    marks = {"3,1": ["boss"], ...}                       # 格右上角角标
    order = ["1,7", "3,5", "3,4", "3,1"]                 # 格中央 1,2,3… + 箭头连线
    hud   = {"round": 0, "stamina": 214, "gold": 4304959, "clover": 673}

    ⚠ **必须容忍**：`None` / `{}` / 值不是 list / list 短于 4 / 值是 str /
      键不合法（`"0,0"` / `"9,9"` / 非 `r,c` / 元组以外的怪东西）⇒ 一律**跳过该格**，
      **不许抛** ✓（`selftest()` 就是拿这些畸形数据轰一遍）。

⭐ 多格地块（**2026-10-11 新增 `spans`**，用户：「实时棋盘还不能正常显示多格地块」）::

    spans = [((2, 2), [(2, 2), (2, 3), (3, 2), (3, 3)]), …]   # ① 元组形态
    spans = [{'anchor': (2, 2), 'cells': [(2, 2), (2, 3)]}]   # ② dict 形态
    spans = {'2,2': [(2, 2), (2, 3)], …}                      # ③ 锚点 → 成员格

    ⛔ 病根：`explore_loop` 落盘的 `board` 每个地块**只给锚点格**
      （`spots.Board.state()` 里 `if v['anchor'] == k` 过滤掉了成员格）
      ⇒ 2×2 的「巨大沙堡」在棋盘上只显示左上角 1 格、另外 3 格看着是雾 ✗
    ⭐ 修法**纯 UI 侧**（不动 `explore_loop`）：主窗口用 `spots.Board(code).cells_of()`
      算出真实占格当 `spans` 传进来 ⇒ 本组件把整块**当一整块**画 ✓
    ⚠ 只有 `len(cells) > 1` 才算多格；成员格越界剔除、**锚点必须并在里面**；
      坏项跳过、**绝不抛**；`spans=None` ⇒ 与改造前**逐像素同构** ✓
"""
import math
import tkinter as tk
from tkinter import ttk

from . import theme as T

__all__ = ['StatusDot', 'StatCard', 'Sparkline', 'BarChart', 'BoardCanvas']

# ── 模块级常量（棋盘几何口径；⚠ 与 `BoardCanvas.ROWS/COLS` **必须一致**：
#    解析函数 `_rc()` 在类定义之前就要用，所以这里存一份，值取 §4.3/附录 E.2）──
_ROWS, _COLS = 5, 7
_PLAIN_WORDS = ('草地', '沙地', '雪地', '岩地', '海底')   # 空地名字（§4.3 已揭示空地）
_PLAIN_SUFFIX = '001'                                   # 空地 sid 后缀（`S10001_001` 岩地）
_CAMP_WORD = '营地'                                      # 名字含它 ⇒ 也当营地（契约明确要求）
_MAX_BADGES = 3                                         # 一格最多画 3 个角标（再多就挤了）
_BPAD = 8                                               # 棋盘画布留白
# ⛔ 2026-10-13 用户要求去掉画布内标题行 ⇒ 本常量已无消费者；置 **0** 只为兼容
_BHEADER = 0
                                                        # ⚠ 22→24：标题字按 §7 顺带修升到
                                                        #   `FONT_BODY`(11)（约 16px）+
                                                        #   顶边留 2px ⇒ 22 会把下一行挤到贴边 ✓
_CELL_MIN, _CELL_MAX = 24, 160                          # 每格像素边长夹取范围


# ══════════════════════════════════════════════════════════════════════
# 零、容错小工具（**全部不抛**；这是本文件的地基）
# ══════════════════════════════════════════════════════════════════════
def _s(v, default=''):
    """任何东西 → str；None → default；连 `__str__` 坏了也不抛"""
    if v is None:
        return default
    try:
        return str(v)
    except Exception:               # noqa: BLE001
        return default


def _clip(s, n=40):
    """字符串截断（长就加省略号）—— 标题行放不下太多字"""
    try:
        return s if len(s) <= n else s[:max(1, n - 1)] + '…'
    except Exception:               # noqa: BLE001
        return ''


def _num(v):
    """数字容忍：能转 float 且有限 ⇒ float；否则 None（bool 不算数字 ⚠）"""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:               # noqa: BLE001
        return None
    return f if math.isfinite(f) else None


def _is_kind(v):
    """`v` 是不是合法的 kind 名（`'ok'`/`'run'`/`'lock'`/`'warn'`/`'danger'`/`'off'`）

    ⚠ 必须包 `try`：`v in dict` 对**不可哈希**的值（`{}` / `[None]`）会抛
      `TypeError: unhashable type` ✗ —— 直接写 `v in KIND_COLORS` 的话，
      `StatusDot(kind={})` 会在**构造期**就炸（那时还没有兜底 except）✗✗。
    """
    try:
        return v in T.KIND_COLORS
    except Exception:               # noqa: BLE001
        return False


def _px(v, default):
    """像素尺寸容忍：能转 int 且 ≥1 ⇒ int；否则 `default`（**构造期也不许抛** ✓）

    ⚠ 为什么连"构造参数"也要容错：组件多半由上层按数据算尺寸（比如按格数放大画布），
      算错一次就在**建窗时**炸 —— 而建窗期没有本文件的兜底 except，
      直接就是"窗口起不来"✗ ⇒ 这里统一夹一道 ✓。
    """
    if isinstance(v, bool):
        return default
    try:
        n = int(v)
    except Exception:               # noqa: BLE001
        return default
    return n if n >= 1 else default


def _floats(obj):
    """任意可迭代 → [float]（坏项跳过；不可迭代 ⇒ []）

    ⚠ 用 `list(obj)` 先物化：生成器等一次性对象也能用；`obj` 是数字/字符串时
      `list()` 抛 TypeError ⇒ 直接空表（数字**不当**曲线上的一个点，
      因为"点集"和"单值"是两种语义，不猜 ✓）。
    """
    out = []
    try:
        items = list(obj)
    except Exception:               # noqa: BLE001
        return out
    for v in items:
        f = _num(v)
        if f is not None:
            out.append(f)
    return out


def _rc(key):
    """`"3,1"` → `(3, 1)`；非法/越界 ⇒ **None**（1 基，"行,列"，附录 E.2）

    容忍：元组/列表键；前后空格；`int()` 能认的字符串。
    拒绝：`"0,0"` / `"9,9"` / `"abc"` / `"1"` / `"1,2,3"` / `None` / 数字 …
    """
    try:
        if isinstance(key, (tuple, list)):
            if len(key) < 2:
                return None
            r, c = int(key[0]), int(key[1])
        else:
            parts = _s(key).strip().split(',')
            if len(parts) != 2:
                return None
            r, c = int(parts[0].strip()), int(parts[1].strip())
    except Exception:               # noqa: BLE001
        return None
    if 1 <= r <= _ROWS and 1 <= c <= _COLS:
        return (r, c)
    return None


def _clip_seg(x0, y0, x1, y1, rx0, ry0, rx1, ry1):
    """Liang–Barsky：把线段裁进矩形 → `(x0,y0,x1,y1)`；整段在外 ⇒ None

    ⚠ 为什么非要自己裁：tkinter Canvas **没有裁剪区**（没有 clip 概念）——
      斜线纹若直接画整格对角线，会**溢到邻格**上 ✗ ⇒ 必须算交点 ✓。
    """
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - rx0), (dx, rx1 - x0), (-dy, y0 - ry0), (dy, ry1 - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return (x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy)


def _short_name(name, cell):
    """按格宽把地块名再截一刀（⚠ canvas 的 `width=` 其实是**换行**、不是省略 ✗）

    ⇒ 双保险：先按"中文字 ≈ 7px @9pt"粗估能放几个字，超了截断 + `…`；
      再交给 `create_text(width=...)` 兜住长英文串（它会换行，不会跑出格）。
    """
    try:
        n = max(2, int((float(cell) - 10) / 7.0))
        return name if len(name) <= n else name[:max(1, n - 1)] + '…'
    except Exception:               # noqa: BLE001
        return ''


def _unit_hint(label):
    """从 `label` 里取一个**短单位提示**（`'每图耗时（秒）'` → `'秒'`；取不到 ⇒ `''`）

    ⭐ 2026-10-11 用户：「上面那两个线图和柱状图不知道是显示啥的」⇒ 顶部右侧那个
      "最后一个值"要在**前面**带个单位提示；而单位就藏在 `label` 里
      （主窗口给的是 `'体力曲线（进图时的体力，点）'` / `'每图耗时（秒）'`）✓

    ⚠ 刻意**只认**最后一对括号里、再用 `，`/`,`/`/` 切出来的**最后一个 ≤4 字**的词：
      括号里长句子是"说明"不是"单位"，取它会把数字挤花 ✗ ⇒ **取不到就什么都不画**
      （保持"最后一个值"原样、也**绝不自己编文案** ✓）——不做任何单位推断 ✓。
    """
    try:
        s = _s(label)
        i, j = s.rfind('（'), s.rfind('）')
        if i < 0 or j <= i:
            i, j = s.rfind('('), s.rfind(')')
        if i < 0 or j <= i:
            return ''
        unit = s[i + 1:j].strip()
        for sep in ('，', ',', '/'):
            if sep in unit:
                unit = unit.split(sep)[-1].strip()
        return unit if 0 < len(unit) <= 4 else ''
    except Exception:               # noqa: BLE001
        return ''


class StatusDot(tk.Frame):
    """状态灯：● 圆点 + 文字。kind: 'ok'绿|'run'蓝|'lock'红|'warn'橙|'danger'红|'off'灰

    ⭐ 出处 §4.5「状态灯：● 绿=就绪 / 蓝=运行中 / 红=锁定待处理 / 灰=设备未连」。
    ⚠ 兼容 tk 老接口：`configure(text=…)` / `configure(fg=…)` **在 tk.Frame 上会
      `TclError: unknown option "-text"`** ✗ —— 旧 `bot_gui.py` 里 `self.state` 是
      `tk.Label`，上层代码习惯这么调 ⇒ 本类**吃掉** `text/fg/kind/state` 并转发
      `set()`，其余关键字照旧转给 `tk.Frame.configure` ✓（换组件不用改调用方）。
    公开属性：`self.text`（当前文字）/ `self.kind`（当前状态）/ `self.fg`（当前色值）。
    """

    def __init__(self, master, text='就绪', kind='ok', **kw):
        bg = kw.pop('bg', T.C_BG)
        tk.Frame.__init__(self, master, bg=bg, **kw)
        self._bg = bg
        self.text = _s(text, '就绪')
        self.kind = kind if _is_kind(kind) else 'ok'
        self.fg = T.KIND_COLORS.get(self.kind, T.C_OFF)
        # ● 圆点 + 文字：两者同色（旧 GUI 那个绿字的观感就是这个 ✓）——
        #   ⚠ 色值一律来自 `theme.KIND_COLORS`，这里**不写任何字面量** ✓
        self._dot = tk.Label(self, text='●', bg=bg, fg=self.fg, font=T.FONT_BODY)
        self._lab = tk.Label(self, text=self.text, bg=bg, fg=self.fg, font=T.FONT_BTN)
        self._dot.pack(side='left')
        self._lab.pack(side='left', padx=(4, 0))

    # ---- 公开接口（签名逐字固定，上层照这个写）------------------------
    def set(self, text=None, kind=None, fg=None):
        """改文字/状态色。三个参数**都可为 None**（= 不改）；给 `fg` 就按色值反推 kind

        ⚠ 坏数据一律**不抛**：`fg` 认不出 ⇒ 'off'；`text` 不是字符串 ⇒ `str()`
          （连 `__str__` 坏了也保住原值）；`kind` 不认识 ⇒ 'off'。
        """
        try:
            if kind is not None:
                self.kind = kind if _is_kind(kind) else 'off'
            if fg is not None:                      # fg 优先于 kind（调用方给了明确色值）
                self.kind = T.kind_of_color(fg)
            if text is not None:
                self.text = _s(text, self.text)
            self.fg = T.KIND_COLORS.get(self.kind, T.C_OFF)
            self._dot.configure(fg=self.fg)
            self._lab.configure(text=self.text, fg=self.fg)
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001
            pass

    def setbg(self, bg):
        """⭐ 2026-10-12 新增：重设自己的底色（**tk 控件没有主题机制 ⇒ 切换时手动调**）

        ⚠ 为什么不靠 `configure(bg=…)`：本类的 `configure` 吃掉了 `text/fg/kind/state`
          再转发，**底色的重设要连 `_dot`/`_lab` 一起**（否则圆点/文字仍留旧底色 ✗）
          ⇒ 单开一个方法，一次改三处 ✓
        """
        try:
            self._bg = bg
            tk.Frame.configure(self, bg=bg)
            self._dot.configure(bg=bg)
            self._lab.configure(bg=bg)
        except Exception:       # noqa: BLE001
            pass

    def configure(self, **kw):                      # noqa: D401  （老接口兼容）
        """⚠ 兼容 tk 老接口：吃掉 `text=` / `fg=` / `kind=` / `state=`，转发 `set()`

        `state=` 只是**为了不炸**（tk.Label 的 state 对状态灯没有意义，
        旧代码 `configure(state='normal')` 在这里等价于"什么都不做"）；
        其余关键字转 `tk.Frame.configure`，**它自己不抛**（失败吞掉 ✓）。
        """
        text = kw.pop('text', None)
        fg = kw.pop('fg', None)
        kind = kw.pop('kind', None)
        kw.pop('state', None)                       # 吃掉：无效但**绝不能炸**
        if text is not None or fg is not None or kind is not None:
            self.set(text=text, kind=kind, fg=fg)
        if kw:
            try:
                tk.Frame.configure(self, **kw)
            except tk.TclError:
                pass
            except Exception:                       # noqa: BLE001
                pass

    config = configure                              # tk 的老别名（一个都不能少 ✓）

    def cget(self, key):
        """`key == 'text'` ⇒ 当前文字；其余转 `tk.Frame.cget`（取不到 ⇒ `''`，不抛）"""
        if key == 'text':
            return self.text
        try:
            return tk.Frame.cget(self, key)
        except tk.TclError:
            return ''
        except Exception:                           # noqa: BLE001
            return ''


# ══════════════════════════════════════════════════════════════════════
# 二、StatCard · 仪表盘小卡（标题 + 大数值 + 副标题）
# ══════════════════════════════════════════════════════════════════════
class StatCard(ttk.Frame):
    """仪表盘小卡：标题（9pt 灰）+ 大数值（16pt bold 靛蓝）+ 副标题（9pt 灰）

    出处 §4.3「仪表盘（4 个小卡）：体力 785→34 / 本次 24张·852s / 胜率 28/28 /
    均耗 32.8点/张」。⚠ 只显示，**不做任何计算**（统计口径在业务层 ✓）。
    """

    def __init__(self, master, title='', value='—', sub='', **kw):
        kw.setdefault('style', 'Card.TFrame')
        kw.setdefault('padding', T.PAD_CARD)
        ttk.Frame.__init__(self, master, **kw)
        self._title = ttk.Label(self, text=_s(title), style='CardTitle.TLabel')
        self.value = ttk.Label(self, text=_s(value, '—'), style='Num.TLabel')
        self._sub = ttk.Label(self, text=_s(sub), style='Sub.TLabel')
        self._title.pack(anchor='w')
        self.value.pack(anchor='w', pady=(2, 0))
        self._sub.pack(anchor='w')

    def set(self, value=None, sub=None, title=None):
        """改显示内容；**None = 不改**（三个参数都可为 None）⚠ 坏数据不抛"""
        try:
            if title is not None:
                self._title.configure(text=_s(title))
            if value is not None:
                self.value.configure(text=_s(value, '—'))
            if sub is not None:
                self._sub.configure(text=_s(sub))
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001
            pass


# ══════════════════════════════════════════════════════════════════════
# 三、Sparkline · 体力迷你曲线
# ══════════════════════════════════════════════════════════════════════
class Sparkline(tk.Canvas):
    """体力迷你曲线（点数少就退化成折线/点，空数据画「—」）

    数据源：`last_summary.json` 的 `stats.stamina_entries = [[体力, epoch], …]`
    （附录 E.1）。`invert=True`（默认）= **大值画在上面**（画布 y 向下增长 ⇒
    这里把它翻过来），体力从高到低的下降曲线因此一眼可见 ✓。

    ⭐ 2026-10-11（用户：「不知道是显示啥的」）⇒ 图里**写明是什么 + 单位 + 平均值**：
      · `label` 画**左上**（"是什么 + 单位"）；`note` 画**左下**（"平均值"）✓
      · 右上"最后一个值"保持原样（`%g`），只在它**前面**补一个 `label` 里的短单位 ✓
    """

    def __init__(self, master, width=260, height=56, **kw):
        kw.setdefault('bg', T.C_BG)
        kw.setdefault('highlightthickness', 0)      # 去掉 tk 画布默认的聚焦黑框
        kw.setdefault('bd', 0)
        tk.Canvas.__init__(self, master, width=_px(width, 260), height=_px(height, 56), **kw)
        self._pts = []
        self._label = ''
        self._note = ''                             # 左下"平均值"一行（空 ⇒ 不画 ✓）
        self._invert = True
        self._render()

    # ---- 公开接口 ----------------------------------------------------
    def set(self, points, invert=True, label='', note=''):
        """`points: list[float]`；**坏数据 ⇒ 画「—」**（不抛 ✓）

        `label` 左上（是什么/单位）；`note` 左下（平均值，**新增**；空 ⇒ 不画）✓
        容忍：`None` / 数字 / 字符串 / `[None]` / `['abc']` / `[1, None, 3]`
        （坏项跳过，好的照画）/ NaN / inf（跳过）。
        """
        try:
            self._invert = bool(invert)
        except Exception:                           # noqa: BLE001
            self._invert = True
        self._label = _clip(_s(label), 16)
        self._note = _clip(_s(note), 24)
        self._pts = _floats(points)
        self._render()

    def set_entries(self, entries):
        """`[[体力, epoch], …]` ⇒ **取 `[0]`** 再 `set()`（附录 E.1 的原格式）

        坏行跳过（短行 / 不是序列 / 第一项不是数字 ⇒ 跳过该行，**不抛** ✓）。
        """
        vals = []
        try:
            rows = list(entries)
        except Exception:                           # noqa: BLE001
            rows = []
        for row in rows:
            try:
                vals.append(row[0])
            except Exception:                       # noqa: BLE001
                continue
        self.set(vals)

    # ---- 内部绘制 ----------------------------------------------------
    def _wh(self):
        try:
            return (float(self.winfo_reqwidth() or 260),
                    float(self.winfo_reqheight() or 56))
        except Exception:                           # noqa: BLE001
            return (260.0, 56.0)

    def _render(self):
        try:
            self.delete('all')
        except tk.TclError:
            return
        except Exception:                           # noqa: BLE001
            return
        try:
            w, h = self._wh()
            top = 15.0 if self._label else 5.0
            bot = 15.0 if self._note else 5.0        # 左下要放 note ⇒ 让出底带 ✓
            left, right = 4.0, 4.0
            if self._label:
                self.create_text(3, 2, anchor='nw', text=self._label,
                                 font=T.FONT_HINT, fill=T.C_TEXT_DIM)
            if self._note:                          # ⭐ 新增：左下"平均 x"（空 ⇒ 一个字都不画 ✓）
                self.create_text(3, h - 2, anchor='sw', text=self._note,
                                 font=T.FONT_HINT, fill=T.C_TEXT_DIM)
            vals = self._pts
            if not vals:
                # ⭐ 优雅降级：没有可用的点 ⇒ 画一个「—」，**不画坐标系也不抛** ✓
                self.create_text(w / 2.0, h / 2.0, text='—',
                                 font=T.FONT_SUB, fill=T.C_TEXT_DIM)
                return
            # 末值贴右上角（配合 label 用；两者都在顶带，互不遮挡）——
            # ⭐ 数值**后面**跟一个从 `label` 括注里取出的**短单位**（`340 点`）；
            #   取不到单位就照旧只画数字 ✓
            #   ⚠ 2026-10-11 订正：第一版写成前置（`点340`）—— 实测读起来像乱码 ✗，
            #     单位就该跟在数字后面 ✓
            _u = _unit_hint(self._label)
            self.create_text(w - 3, 2, anchor='ne',
                             text=('%g %s' % (vals[-1], _u)) if _u else ('%g' % vals[-1]),
                             font=T.FONT_HINT, fill=T.C_TEXT)
            if len(vals) == 1:                      # 只有一个点 ⇒ 退化成"点" ✓
                cy = (top + h - bot) / 2.0
                self.create_oval(w / 2.0 - 2.5, cy - 2.5, w / 2.0 + 2.5, cy + 2.5,
                                 fill=T.C_RUN, outline=T.C_RUN)
                return
            lo, hi = min(vals), max(vals)
            if hi - lo < 1e-9:                      # 全平 ⇒ 居中一条直线（别除 0 ✗）
                lo, hi = lo - 1.0, hi + 1.0
            span = max(1, int(w))                   # 点比像素多就抽稀（省重绘时间）
            step = max(1, len(vals) // span)
            pts = vals[::step]
            if len(pts) < 2:
                pts = vals[:2]
            x0, x1 = left, max(left + 1.0, w - right)
            y_hi, y_lo = top, max(top + 1.0, h - bot)
            seq = []
            for i, v in enumerate(pts):
                x = x0 + (x1 - x0) * (i / float(len(pts) - 1))
                k = (v - lo) / (hi - lo)
                y = (y_hi + (1.0 - k) * (y_lo - y_hi)) if self._invert \
                    else (y_lo - (1.0 - k) * (y_lo - y_hi))
                seq.append((x, y))
            self.create_line(*[c for p in seq for c in p], fill=T.C_RUN, width=2,
                             capstyle='round', joinstyle='round')
            self.create_oval(seq[-1][0] - 2.5, seq[-1][1] - 2.5,
                             seq[-1][0] + 2.5, seq[-1][1] + 2.5,
                             fill=T.C_PRIMARY, outline=T.C_PRIMARY)
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001
            pass


# ══════════════════════════════════════════════════════════════════════
# 四、BarChart · 每图耗时柱状图
# ══════════════════════════════════════════════════════════════════════
class BarChart(tk.Canvas):
    """每图耗时柱状图（数据源 `stats.map_secs`，附录 E.1）

    `values: list[float]`，坏数据 ⇒ 画「—」（不抛 ✓）。

    ⭐ 2026-10-11（用户：「不知道是显示啥的」）⇒ 图里**写明是什么 + 单位 + 平均值**：
      · `label` 画**左上**（"是什么 + 单位"）；`note` 画**左下**（"平均值"）✓
      · 最大值仍在右上角 ✓
      · 柱数多于画布宽度时**照旧**（上层 `bot_gui.py` 自己只喂尾部 `[-30:]`）
        —— 本组件**不做截断**、**也不自己编任何文案**（`note` 空 ⇒ 保持沉默 ✓）
    """

    def __init__(self, master, width=260, height=56, **kw):
        kw.setdefault('bg', T.C_BG)
        kw.setdefault('highlightthickness', 0)
        kw.setdefault('bd', 0)
        tk.Canvas.__init__(self, master, width=_px(width, 260), height=_px(height, 56), **kw)
        self._vals = []
        self._label = ''
        self._note = ''                             # 左下"平均值"一行（空 ⇒ 不画 ✓）
        self._render()

    def set_values(self, values, label='', note=''):
        """`values: list[float]`；**坏数据 ⇒ 画「—」**（不抛 ✓）

        `label` 左上（是什么/单位）；`note` 左下（平均值，**新增**；空 ⇒ 不画）✓
        容忍：`None` / 数字 / 字符串 / `[None]` / `['abc']` / 负数（画零轴下方）/
        NaN / inf（跳过）。
        """
        self._label = _clip(_s(label), 16)
        self._note = _clip(_s(note), 24)
        self._vals = _floats(values)
        self._render()

    def _wh(self):
        try:
            return (float(self.winfo_reqwidth() or 260),
                    float(self.winfo_reqheight() or 56))
        except Exception:                           # noqa: BLE001
            return (260.0, 56.0)

    def _render(self):
        try:
            self.delete('all')
        except Exception:                           # noqa: BLE001
            return
        try:
            w, h = self._wh()
            top = 15.0 if self._label else 4.0
            bot = 15.0 if self._note else 4.0        # 左下要放 note ⇒ 让出底带 ✓
            left, right = 4.0, 4.0
            if self._label:
                self.create_text(3, 2, anchor='nw', text=self._label,
                                 font=T.FONT_HINT, fill=T.C_TEXT_DIM)
            if self._note:                          # ⭐ 新增：左下"平均 x"（空 ⇒ 一个字都不画 ✓）
                self.create_text(3, h - 2, anchor='sw', text=self._note,
                                 font=T.FONT_HINT, fill=T.C_TEXT_DIM)
            vals = self._vals
            if not vals:
                self.create_text(w / 2.0, h / 2.0, text='—',
                                 font=T.FONT_SUB, fill=T.C_TEXT_DIM)
                return
            if len(vals) > 1:
                self.create_text(w - 3, 2, anchor='ne', text='%g' % max(vals),
                                 font=T.FONT_HINT, fill=T.C_TEXT)
            lo = min(0.0, min(vals))
            hi = max(vals)
            if hi - lo < 1e-9:
                hi = lo + 1.0
            y_hi, y_lo = top, max(top + 1.0, h - bot)
            band = max(1.0, (w - left - right) / float(len(vals)))
            bw = max(1.0, band - 1.0)               # 留 1px 缝，柱子不糊在一起
            y_of = lambda v: y_lo - (v - lo) / (hi - lo) * (y_lo - y_hi)   # noqa: E731
            y_base = y_of(0.0)
            vmax = max(vals)
            for i, v in enumerate(vals):
                x0 = left + i * band
                x1 = min(w - right, x0 + bw)
                yv = y_of(v)
                # ⚠ 负值柱是**图形填充**（不是文字）⇒ 用 `C_WARN_BG`（05 §4.5a v2 清单
                #   第 2 项把警告色拆成"文字 `C_WARN` / 图形 `C_WARN_BG`"，此处属图形侧）
                col = T.C_WARN_BG if v < 0 else (T.C_PRIMARY if v == vmax else T.C_RUN)
                self.create_rectangle(x0, min(yv, y_base), x1, max(yv, y_base),
                                      fill=col, outline=col)
            self.create_line(left, y_base, w - right, y_base,
                             fill=T.C_BORDER, width=1)
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001
            pass


# ══════════════════════════════════════════════════════════════════════
# 五、BoardCanvas · 5×7 实时棋盘
# ══════════════════════════════════════════════════════════════════════
class BoardCanvas(tk.Canvas):
    """5×7 实时棋盘（格名 / 标记角标 / 计划点序 / 营地 / 拉黑斜线纹）

    ⭐ 构造期 `show_sid=False` ⇒ **不画**左上角的 sid 后缀小字（默认 `True` = 逐像素同构）。

    ⚠ 几何类常量照 `mapbot.py` 的 **720×1280 基准**逐字给出（§4.3 / 附录 E.2）：
      它们是**屏幕坐标基准**，本组件只把它们当"口径常量"暴露出来
      （实际绘制用 `cell` 每格像素边长重算）—— 这样上层想反算/对齐时不用再抄一遍 ✓。
    """

    ROWS = 5
    COLS = 7
    GRID_X0 = 24
    GRID_Y0 = 668
    GRID_CX = 96
    GRID_CY = 96

    def __init__(self, master, cell=64, show_sid=True, **kw):
        try:
            cell = int(cell)
        except Exception:                           # noqa: BLE001
            cell = 64
        self.cell = max(_CELL_MIN, min(_CELL_MAX, cell))
        # ⭐ `show_sid`（构造期参数，**不进 `update_board` 签名**）：是否画左上角 sid 后缀小字。
        #   ⚠ 默认 `True` ⇒ 与改造前**逐像素同构**（`_demo.py` / `_selftest_*` 零影响 ✓）。
        #   ⚠ 容错：**只认真 bool 与 0/1**；其余（`None` / `{}` / `''` / 乱码 / 怪 `__bool__`）
        #     一律**当 True**（= 回落默认行为，宁多画一行小字也绝不抛 —— 构造期没有兜底
        #     `except`，这里抛了就是"窗口起不来" ✗）。
        if isinstance(show_sid, bool):
            self.show_sid = show_sid
        elif isinstance(show_sid, int) and show_sid in (0, 1):
            self.show_sid = bool(show_sid)
        else:
            self.show_sid = True
        # 默认底色/尺寸：⚠ 只 setdefault ⇒ 调用方显式给了就听调用方的 ✓
        kw.setdefault('bg', T.BOARD_BG)
        kw.setdefault('highlightthickness', 0)
        kw.setdefault('bd', 0)
        kw.setdefault('width', self._px_w())
        kw.setdefault('height', self._px_h())
        tk.Canvas.__init__(self, master, **kw)
        # ⭐ 每个"格名"的 canvas item id（`(r,c) -> item`）—— 序号圆要靠它定位到**名字右边** ✓
        #   ⚠ 每次 `update_board` 开头 `delete('all')` ⇒ item 全失效 ⇒ 必须**清空重建** ✗
        self._name_items = {}
        # ⭐ 多格块的名字 item（`块下标 -> item`，见 `_draw_span_label`）✓
        self._span_name_items = {}
        self.clear('无数据')

    # ---- 尺寸/坐标 ---------------------------------------------------
    # ⚠⚠ 名字**绝不能叫 `_w` / `_h`**：`tkinter.Misc.__init__` 会往实例上塞
    #   `self._w`（= Tcl 路径名，如 `.!boardcanvas`）⇒ **实例属性盖掉同名方法** ✗✗
    #   实测后果：`__init__` 里（那时 `self._w` 还没被赋值）能调通、尺寸算对，
    #   但**建完之后**再调 `self._w()` 就 `TypeError: 'str' object is not callable`
    #   ⇒ 被本文件的 `except Exception` 兜底**静默吃掉** ⇒ `clear()` 变成空转、
    #     连"无数据"提示都画不出来，而 selftest 依然全绿 ✗（这就是本项目最怕的
    #     "判据静默失效"）⇒ 一律用 `_px_*` 前缀，永远不碰 tkinter 的下划线内部名 ✓
    def _px_w(self):
        return self.COLS * self.cell + 2 * _BPAD

    def _px_h(self):
        return self.ROWS * self.cell + 2 * _BPAD      # ⛔ 2026-10-13 去掉 `_BHEADER`（标题行已删 ⇒ 画布高全给棋盘 ✓）

    def _cell_rect(self, r, c):
        """(行,列) 1 基 → 该格像素矩形 `(x0, y0, x1, y1)`"""
        x0 = _BPAD + (int(c) - 1) * self.cell
        y0 = _BPAD + (int(r) - 1) * self.cell            # ⛔ 同上：不再让标题行 ✓
        return (float(x0), float(y0), float(x0 + self.cell), float(y0 + self.cell))

    # ---- 数据解析（全部容错，坏数据 ⇒ 跳过，不抛也不猜）--------------
    def _norm_board(self, board):
        """`{键: [sid后缀, 名字, score, ratio]}` → `{(r,c): {...}}`

        ⚠ 逐条容忍（契约明确要求）：非 dict ⇒ 空；键不合法 ⇒ 跳过；
          值不是 list/tuple ⇒ 跳过；**list 短于 4 ⇒ 跳过**；score/ratio 非数字 ⇒ None。
        """
        out = {}
        if not isinstance(board, dict):
            return out
        for k, v in board.items():
            rc = _rc(k)
            if rc is None:
                continue
            if not isinstance(v, (list, tuple)) or len(v) < 4:
                continue
            out[rc] = {'sid': _s(v[0]).strip(), 'name': _s(v[1]).strip(),
                       'score': _num(v[2]), 'ratio': _num(v[3])}
        return out

    def _norm_marks(self, marks):
        """`{"3,1": ["boss"]}` → `{(r,c): [标记名, …]}`

        ⚠ 额外容忍 `{"3,1": {"marks": ["boss"]}}`：`loop_log` 的 `marks` 与
          `marks.py` 的 `mk[格]` **两种形态都出现过**（后者是 dict！）——
          只认 list 的话会**静默读不到标记** ✗（本项目踩过同族的坑）。
        """
        out = {}
        if not isinstance(marks, dict):
            return out
        for k, v in marks.items():
            rc = _rc(k)
            if rc is None:
                continue
            if isinstance(v, dict):
                v = v.get('marks') or []
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, (list, tuple, set)):
                continue
            names, seen = [], set()
            for m in v:
                nm = _s(m).strip()
                if nm and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
            if names:
                out[rc] = names
        return out

    def _norm_order(self, order):
        """`["1,7","3,5",…]` → `[(r,c), …]`（去重保序；坏项跳过）

        ⚠ 去重是必要的：同格出现两次会互相盖掉序号（留在后面那个赢），
          看起来像"少了一步"✗ ⇒ 取**首次**出现的位置 ✓。
        """
        out, seen = [], set()
        try:
            items = list(order)
        except Exception:                           # noqa: BLE001
            return out
        for k in items:
            rc = _rc(k)
            if rc is None or rc in seen:
                continue
            seen.add(rc)
            out.append(rc)
        return out

    def _norm_cells(self, it):
        """`["5,5", …]`（或单个 `"5,5"`）→ `set[(r,c)]`；坏项跳过"""
        out = set()
        if it is None or isinstance(it, (int, float, bool)):
            return out
        if isinstance(it, str):                     # 单个 "5,5" 也接受（不然会按字符拆 ✗）
            rc = _rc(it)
            if rc is not None:
                out.add(rc)
            return out
        if isinstance(it, dict):
            it = list(it.keys())                    # dict ⇒ 当键集合（`{格: …}` 很常见）
        try:
            items = list(it)
        except Exception:                           # noqa: BLE001
            return out
        for k in items:
            rc = _rc(k)
            if rc is not None:
                out.add(rc)
        return out

    def _norm_spans(self, spans):
        """`spans` → `(blocks, member)`：**多格地块**的真实占格（坏项跳过、**绝不抛**）✓

        ⭐ 病根（2026-10-11 用户：「实时棋盘还不能正常显示多格地块」）：`explore_loop`
          落盘的 `board` 里 `if v['anchor'] == k` 只留**锚点格** ⇒ 一个 2×2 的
          「巨大沙堡」在棋盘上只填 1 格、另外 3 格看着是雾 ✗。主窗口用
          `spots.Board.footprint/cells_of` 把占格算好、当**新参数 `spans`** 传进来 ✓

        **三种形态都要容忍**：
          ① `[(anchor, cells), …]`（`anchor` 是 `(r,c)` 或 `"r,c"`；`cells` 是
             `[(r,c),…]` 或 `["r,c",…]`）
          ② `[{'anchor': …, 'cells': …}, …]`
          ③ `{'r,c': [(r,c),…], …}`（锚点 → 成员格）
        **规则**：只有 `len(cells) > 1` 才算多格；成员格必须落进 5×7 界内（越界剔除，
        由 `_rc` 负责）；**必须包含锚点自身**（缺就并进去 —— 否则那块会缺角 ✗）；
        同一格只归**第一个**块（重复/重叠 ⇒ 后来的让位）✓

        返回 `([{'anchor': (r,c), 'cells': set}, …], {(r,c): 块下标})`，
        且**两个返回值永远同下标对齐**（`blocks[i]` ↔ `member[rc] == i`）✓
        """
        blocks, member = [], {}
        try:
            if isinstance(spans, dict):
                raw = list(spans.items())
            elif isinstance(spans, (list, tuple)):
                raw = list(spans)
            else:
                return blocks, member
        except Exception:                           # noqa: BLE001
            return [], {}
        for item in raw:
            try:
                if isinstance(item, dict):          # 形态②
                    anchor, cells = item.get('anchor'), item.get('cells')
                elif isinstance(item, (list, tuple)) and len(item) >= 2:   # 形态①
                    anchor, cells = item[0], item[1]
                else:
                    continue
                a = _rc(anchor)                     # 锚点非法/越界 ⇒ 整项跳过 ✓
                if a is None:
                    continue
                cs = self._norm_cells(cells)        # 复用容错口径（坏项自动跳过 ✓）
                cs.add(a)                           # ⚠ 必须含锚点自身，否则那块缺角 ✗
                free = set(rc for rc in cs if rc not in member)
                if a not in free or len(free) <= 1:  # 只有 >1 格才算"多格"✓
                    continue
                idx = len(blocks)
                for rc in free:
                    member[rc] = idx
                blocks.append({'anchor': a, 'cells': free})
            except Exception:                       # noqa: BLE001
                continue
        return blocks, member

    # ---- 底色判据 ----------------------------------------------------
    def _fill_of(self, rec, is_camp):
        """§4.3 棋盘配色（**顺序即优先级**，逐条对应用户口径）

        ① 营地（显式 `camp` 参数 ∪ 名字含「营地」）⇒ 蓝底 —— **优先于雾判据**：
           名字含「营地」是契约里"额外当营地"的硬要求，被 ratio 规则冲掉就违背契约 ✗
        ② 无数据 / 无名 / 名字是「未知」/ ratio 缺失或 < 0.5 ⇒ 雾灰
        ③ 空地（名字含 草地/沙地/雪地/岩地/海底 之一，或 sid 后缀 `001`）⇒ 浅绿
        ④ 其余有名字 ⇒ 内容格橙
        ⚠ 全程 `_num` 已把坏值归一成 None ⇒ 这里**不会再抛** ✓
        """
        if is_camp:
            return T.BOARD_CAMP
        if rec is None:
            return T.BOARD_FOG
        name, ratio = rec['name'], rec['ratio']
        if not name or name == '未知':
            return T.BOARD_FOG
        if ratio is None or ratio < 0.5:
            return T.BOARD_FOG
        if rec['sid'].endswith(_PLAIN_SUFFIX):
            return T.BOARD_PLAIN
        for wd in _PLAIN_WORDS:
            if wd in name:
                return T.BOARD_PLAIN
        return T.BOARD_CONTENT

    # ---- 公开接口（签名逐字固定，上层照这个写）------------------------
    def update_board(self, board=None, marks=None, order=None, cost=None,
                     camp=None, blocked=None, target_cells=None, hud=None,
                     spans=None):
        """整盘重绘（**先 `delete('all')`**）。**任何坏数据都不抛** ✓

        `board`  `{ "行,列": [sid后缀, 地块名, score, ratio] }`（附录 E.2）
        `marks`  `{ "行,列": ["boss", …] }` ⇒ 右上角角标（色/字查 theme.MARK_COLORS）
        `order`  `["1,7", …]` ⇒ 格中央 1,2,3… + 相邻序号箭头连线
        `cost`   数字 / `[a,b]` / dict ⇒ **只进标题行文字，不做算术** ⚠
        `camp`   `"2,7"` 或 None（**另外**：board 里名字含「营地」的格也算）
        `blocked`/`target_cells`  可迭代 `"r,c"` ⇒ 斜线纹 / 靛蓝 2px 描边
                 （**照旧按格画，不合并** —— 多格块的成员格也照旧画在那一格上 ✓）
                 ⛔ 2026-10-12：`target_cells` 的**描边已停用**（用户：「去掉实时棋盘
                   目标格子的那个蓝色框」）—— 参数**照旧收下**（签名不动、上层照传 ✓），
                   只是内部不再消费它；`blocked` 的斜线纹**不受影响** ✓
        `hud`    dict ⇒ 标题行 `第N张图`/体力/金币/幸运草（键 `round`/`stamina`/
                 `gold`/`clover`；**缺键就不显示**）
        `spans`  ⭐ **多格地块的真实占格**（2026-10-11 新增；三种形态都容忍，见
                 `_norm_spans`）—— `board` 只给锚点格，`spans` 把整块补全：
                 **每个成员格都按锚点那条记录的底色填满**（不再露雾灰）、
                 **名字只画一次**（块 bbox 中下部）、sid 只画在锚点格左上角、
                 **整块只画一圈外框**（内部不留格线）、角标挪到块 bbox 右上角、
                 计划序号圆心取块 bbox 中心 ✓
                 ⚠ **`spans=None`（或单格/坏数据）⇒ 与改造前逐像素同构** ✓
        ⭐ `show_sid` 是**构造期**参数（`BoardCanvas(..., show_sid=False)`），**不进本签名**
           —— 为假时**两处**左上角 sid 后缀小字（单格 `_draw_cell` / 多格块
           `_draw_span_label`）都不画；**只影响"画不画这行小字"**，底色/格名/🏕/角标/
           序号一律照旧 ✓（`_fill_of` 里那条按 sid 后缀判**底色**的规则**不受影响** ✓）
        """
        try:
            self.delete('all')
        except tk.TclError:
            return
        except Exception:                           # noqa: BLE001
            return
        # ⚠ `delete('all')` 之后**所有 item id 都失效** ⇒ 名字索引必须重建
        #   （否则序号会去 `bbox()` 一个**不存在的 item** ⇒ 定位到空气 / 抛异常 ✗）
        self._name_items = {}
        self._span_name_items = {}
        try:
            recs = self._norm_board(board)
            mks = self._norm_marks(marks)
            seq = self._norm_order(order)
            blk = self._norm_cells(blocked)
            tgt = self._norm_cells(target_cells)
            camp_rc = _rc(camp)
            hud_d = hud if isinstance(hud, dict) else {}
            # ★ 多格地块：`_norm_spans` 出"块表 + 成员表"（两者下标对齐 ✓），
            #   这里再给每块补上"锚点记录 / 是不是营地 / bbox"（绘制要用）
            raw_blocks, member = self._norm_spans(spans)
            blks = []
            for b in raw_blocks:
                rec = recs.get(b['anchor'])
                is_camp = (b['anchor'] == camp_rc) or \
                    (_CAMP_WORD in (rec['name'] if rec else ''))
                rects = [self._cell_rect(*rc) for rc in b['cells']]
                bbox = (min(t[0] for t in rects), min(t[1] for t in rects),
                        max(t[2] for t in rects), max(t[3] for t in rects))
                blks.append({'anchor': b['anchor'], 'cells': b['cells'],
                             'rec': rec, 'camp': bool(is_camp), 'bbox': bbox})
            # ① 底色 + 格名 + sid + 🏕（最底层）
            #    ⚠ 多格块的成员格只画"按锚点记录填满的底色"，名字/sid/🏕 归
            #      `_draw_span_label()` **各画一次**（不然一块里画 4 遍名字 = 糊 ✗）
            #    ⚠ `member` 为空时，本循环与改造前**逐字相同**（多格那几段全是空转）✓
            for r in range(1, self.ROWS + 1):
                for c in range(1, self.COLS + 1):
                    bi = member.get((r, c))
                    if bi is None:
                        rec = recs.get((r, c))
                        is_camp = ((r, c) == camp_rc) or \
                            (_CAMP_WORD in (rec['name'] if rec else ''))
                        self._draw_cell(r, c, rec, is_camp)
                    else:
                        self._draw_span_fill((r, c), blks[bi])
            # ①b 多格块：外框（一圈，内部无格线）+ 名字/sid/🏕（各一次）
            for b in blks:
                self._draw_span_frame(b)
            for b in blks:
                self._draw_span_label(b)
            # ② 拉黑斜线纹 + 目标描边（压在底色上、序号下）——照旧**按格**画 ✓
            for rc in sorted(blk):
                self._draw_blocked(*self._cell_rect(*rc))
            # ⛔ 2026-10-12 用户口径（原话）：「**去掉实时棋盘目标格子的那个蓝色框**」
            #   ⇒ 目标格的**靛蓝 2px 描边不再画** ✓
            #   ⚠ 只去掉"描边"这一件事，别的一律不动：
            #     · 目标格的**底色**照旧（`_fill_of`，与是否目标无关 ✓）
            #     · 计划序号 / 角标 / 名字 / 🏕 / 拉黑斜线纹 **全部保留** ✓
            #     · `target_cells` **参数与签名一个字都不动**（上层照旧传 ✓）
            #       —— 只是这里不再消费它 ⇒ 以后想恢复：把下面两行注释放开即可 ✓
            #     · `_draw_target()` 函数**保留**（不删）⇒ 可逆、且不影响别的调用方 ✓
            #   ⚠ 为什么不是删函数/删参数：那会动到**签名**（上层 `bot_gui.py` 按名传
            #     `target_cells=`）⇒ 一删就得连带改上层，风险大且没必要 ✗
            # for rc in sorted(tgt):
            #     self._draw_target(*self._cell_rect(*rc))
            # ③ 标记角标（多格块的成员 ⇒ 挪到**块 bbox 左上角**，免得落进块内部 ✗）
            #    ⚠ 左上角也是用户口径「标志要靠左上」⇒ 整块的标志同样贴块左上 ✓
            #    ⚠ 非成员格与改造前**逐字相同**；每块仍最多 `_MAX_BADGES` 个 ✓
            moved = {}
            for rc in sorted(mks):
                bi = member.get(rc)
                if bi is None:
                    self._draw_marks(*self._cell_rect(*rc), mks[rc])
                    continue
                got = moved.setdefault(bi, [])
                for nm in mks[rc]:
                    if len(got) >= _MAX_BADGES:
                        break
                    got.append(nm)
            for bi in sorted(moved):
                # ⛔⛔ 2026-10-12 用户：「**三格的右上角都不是本格了，到其他格子了**」
                #   ── 同一个根因：**bbox 的角 ≠ 本块的格子** ──
                #     L 形三格（如「蘑菇丛」=(1,1)/(2,1)/(2,2)）的 bbox 是 2×2，
                #     bbox 左上角 = 格 (1,1)（是成员，凑巧对）；但如果成员是 (1,2)/(2,1)/(2,2)，
                #     bbox 左上角 (1,1) **就不是成员** ⇒ 角标画到**别人的格子**上 ✗✗
                #   ⇒ 修法：**取本块成员格里最左列 + 最上行那一格**当角标锚格
                #     ⇒ 角标一定落在**本块自己的格子**里 ✓（与序号圆取"最右列+最上行"对称 ✓）
                _cs = sorted(blks[bi].get('cells') or [])
                if _cs:
                    _c = min(c for _r, c in _cs)                 # 最左列
                    _r = min(r for r, cc in _cs if cc == _c)     # 该列最上行
                    bx0, by0, _, _ = self._cell_rect(_r, _c)
                else:                                            # 兜底（无 cells）
                    bx0, by0 = blks[bi]['bbox'][0], blks[bi]['bbox'][1]
                # ⚠ 用"格大小"的伪矩形贴到**那个真格**的左上角 ⇒ 角标大小与单格一致 ✓
                self._draw_marks(bx0, by0, bx0 + self.cell, by0 + self.cell, moved[bi])
            # ④ 计划点序 + 箭头（**最上层** —— 否则会被角标/斜线盖住 ✗）
            self._draw_order(seq, member, blks)
            # ⛔⛔ 2026-10-13 用户口径（原话）：
            #   「**实时棋盘那边的第3张图，体力金币幸运草那行去掉**」✓
            #   ⇒ 不再画标题行（`_draw_header` 已删）
            #   ⚠ 连带 `_BHEADER` 也没用了（见 `_px_h`）⇒ 画布高度全给棋盘 ✓
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001  （兜底：绝不抛到回调里）
            try:
                self.delete('all')
                self.create_text(self._px_w() / 2.0, self._px_h() / 2.0, text='数据异常',
                                 font=T.FONT_SUB, fill=T.C_DANGER)
            except Exception:                       # noqa: BLE001
                pass

    def clear(self, msg='无数据'):
        """清空并只显示一句提示（`msg` 是坏数据也不抛 ✓）

        ⭐ T6 §7 顺带修：占位字由 `FONT_SUB`(9) 提到 **`T.FONT_BODY`(11)**
          —— 真实截图里那个「无数据」**偏小**、几乎看不见 ✗（工单原话）
        """
        try:
            self.delete('all')
            self.create_text(self._px_w() / 2.0, self._px_h() / 2.0, text=_s(msg, '无数据'),
                             font=T.FONT_BODY, fill=T.C_TEXT_DIM)
        except tk.TclError:
            pass
        except Exception:                           # noqa: BLE001
            pass

    def _draw_cell(self, r, c, rec, is_camp):
        """一格：底色 + 格名（**居中**）+ sid 后缀（左上小字）+ 🏕（顶中）

        ⭐ 2026-10-12 用户口径：「**实时棋盘地块字体要居中**」
          ⇒ 格名从"底中"改成**格子正中央**（`anchor='center'`）✓
          ⇒ 因为名字占了中心，**计划序号圆改画到左上角**（原来也占中心 ⇒ 会糊在名字上 ✗）
        """
        x0, y0, x1, y1 = self._cell_rect(r, c)
        fill = self._fill_of(rec, is_camp)
        self.create_rectangle(x0, y0, x1, y1, fill=fill, outline=T.BOARD_EDGE, width=1)
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        if rec is not None:
            # ⚠ 雾格（`BOARD_FOG`）是**灰底** ⇒ 灰字实测仅 1.32:1（严重不可读）⇒ 换白字
            #   `C_ON_FOG`（05 §4.5a v2 清单第 3 项）；空地/内容/营地格上的灰字**达标**
            #   ⇒ **照旧 `C_TEXT_DIM`** —— 这是"按格选字色"，不是全局换色 ✓
            #   ⚠ 判据直接用上面**已经算好**的 `fill`（不再多调一次 `_fill_of` ⇒ 零额外开销）✓
            # ⭐ `show_sid=False` ⇒ 这一处 sid 小字**不画**（底色/格名/🏕/角标/序号全照旧 ✓）；
            #   ⚠ `_fill_of` 里那条 `rec['sid'].endswith(_PLAIN_SUFFIX)` 判**底色**的**绝不改** ✓
            if rec['sid'] and self.show_sid:
                sid_fg = T.C_ON_FOG if fill == T.BOARD_FOG else T.C_TEXT_DIM
                self.create_text(x0 + 3, y0 + 2, anchor='nw', text=rec['sid'][:4],
                                 font=T.FONT_TINY, fill=sid_fg)
            if rec['name']:
                f_name = T.FONT_MONO if self.cell >= 56 else T.FONT_TINY
                # ⭐⭐ 2026-10-12 用户：「**步数的那个 123 号标记位置改成紧挨着字体右边吧**」
                #   ⇒ 记下这个名字的 canvas item id ⇒ 画序号时用它的 `bbox()` 定位到**右边** ✓
                #     （`create_text` 返回 item id；存进 `self._name_items[rc]` ✓）
                _it = self.create_text(cx, cy, anchor='center',
                                       text=_short_name(rec['name'], self.cell),
                                       font=f_name, fill=T.C_TEXT,
                                       width=max(8, self.cell - 8))   # width 兜住长串换行
                try:
                    self._name_items[(r, c)] = _it
                except Exception:       # noqa: BLE001
                    pass
        if is_camp:
            self.create_text(cx, y0 + 1, anchor='n', text='🏕',
                             font=T.FONT_TINY_UI, fill=T.C_TEXT)

    def _draw_blocked(self, x0, y0, x1, y1):
        """拉黑格：`BOARD_BLOCKED` 底 + 斜线纹（⚠ 线段自己裁进格内，别溢到邻格）

        `BOARD_BLOCKED` 底**在 `_fill_of` 之后叠**（拉黑格可能是内容格/雾格，
        底色按原判据走、再盖一层红底 + 斜纹 ⇒ 一眼能认出"这格被封了" ✓）。
        ⚠ 斜纹色走 `C_BLOCKED_HATCH`（= `C_DANGER` 危险红）—— 05 §4.5a v2 清单第 5 项：
          原 `C_TEXT_DIM` 灰纹在浅红底上仅 1.65:1 ⇒ 深红纹 4.92:1 ✅（**只换色，画法/步长不改**）
        """
        self.create_rectangle(x0, y0, x1, y1, fill=T.BOARD_BLOCKED,
                              outline=T.BOARD_EDGE, width=1)
        side = x1 - x0
        step = max(6.0, side / 6.0)
        k = -side
        while k <= 2.0 * side:
            seg = _clip_seg(x0 + k, y0, x0 + k + side, y1, x0, y0, x1, y1)
            if seg:
                self.create_line(seg[0], seg[1], seg[2], seg[3],
                                 fill=T.C_BLOCKED_HATCH, width=1)
            k += step

    def _draw_target(self, x0, y0, x1, y1):
        """目标格：靛蓝 2px 描边（§4.5）

        ⛔ 2026-10-12 **本函数已停用**（用户口径：「**去掉实时棋盘目标格子的那个蓝色框**」）——
           调用点在 `update_board` 里**已注释**。函数本身**保留**（不删）：
           · 可逆：想恢复只需放开调用点那两行 ✓
           · 不影响任何别的调用方（本函数只被 `update_board` 调过 ✓）
        """
        self.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1,
                              outline=T.C_PRIMARY, width=2, fill='')

    def _draw_marks(self, x0, y0, x1, y1, names):
        """**左上角**角标：色/字查 `theme.MARK_COLORS` / `theme.MARK_TEXT`；未知 ⇒ 灰点

        ⭐⭐ 2026-10-12 用户口径（原话）：「**实时棋盘里的标志要靠左上**」
          ⇒ 角标从**右上**挪到**左上**（`cx` 从 `x1 - …` 改成 `x0 + …`）✓
          ⚠ 与**计划序号圆**的位置**互换**（序号圆让到右上，见 `_plan_center`）——
            两者都在左上会叠在一起 ✗（序号圆原本就在左上 ✓）
        ⚠ `fill=''` 在 tkinter 里表示"不填充"—— 这里用 `create_oval(fill=col)`
          是实心圆点；未知标记就是**灰实心点**（契约要求"未知标记画灰点" ✓）。
        ⭐ 角标内**文字色**查 `theme.MARK_FG`（05 §4.5a v2 清单第 6 项：只有黄底的
          幸运草需要深字 `C_ON_CLOVER`）⇒ 组件侧**没有 `if nm == 'clover'` 分支、
          也不写死字面色**；查不到 ⇒ `.get(nm, BOARD_BG)` 回落白字（与 v1 一致 ✓）
        """
        side = x1 - x0
        rad = max(5.0, side * 0.11)
        gap = 2.0
        for i, nm in enumerate(names[:_MAX_BADGES]):
            col = T.MARK_COLORS.get(nm, T.C_TEXT_DIM)       # 未知标记 ⇒ 灰
            ch = T.MARK_TEXT.get(nm, '')
            # ⭐ 靠**左上**：从 `x0` 往右排（多标记时依次向右）✓
            cx = x0 + rad + 2.0 + i * (2.0 * rad + gap)
            cy = y0 + rad + 2.0
            if cx + rad > x1:
                break                                       # 挤不下就不画了（不硬塞）
            self.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                             fill=col, outline=T.BOARD_BG, width=1)
            if ch:
                self.create_text(cx, cy, text=ch, font=T.FONT_TINY_UI,
                                 fill=T.MARK_FG.get(nm, T.BOARD_BG))

    def _draw_span_fill(self, rc, blk):
        """多格块的一个成员格：按**锚点那条记录**的底色填满（⚠ 不留格线）

        ⭐ 契约：成员格**不许**再显示成雾灰（「另外 3 格看起来是雾」就是本条要修的）✓
        ⚠ `outline=''` 是**故意**的：格子轮流画 1px `BOARD_EDGE` 的话，块内部会留下
          格线 ⇒ 又看起来像几格 ✗（外圈另由 `_draw_span_frame()` 画 ✓）。
        """
        x0, y0, x1, y1 = self._cell_rect(*rc)
        self.create_rectangle(x0, y0, x1, y1,
                              fill=self._fill_of(blk['rec'], blk['camp']),
                              outline='')

    def _draw_span_frame(self, blk):
        """整块**一圈外框**（`C_TEXT_DIM`，width=2）：只画"邻居不在本块内"的那些边

        ⇒ 2×2 恰好 **8 条**；块**内部一条都不画**（内部线会让它又看起来是几格 ✗）✓
        """
        cells = blk['cells']
        for (r, c) in sorted(cells):
            x0, y0, x1, y1 = self._cell_rect(r, c)
            for nb, seg in (((r - 1, c), (x0, y0, x1, y0)),      # 上
                            ((r + 1, c), (x0, y1, x1, y1)),      # 下
                            ((r, c - 1), (x0, y0, x0, y1)),      # 左
                            ((r, c + 1), (x1, y0, x1, y1))):     # 右
                if nb in cells:
                    continue                                     # 内部边 ⇒ 不画 ✓
                self.create_line(seg[0], seg[1], seg[2], seg[3],
                                 fill=T.C_TEXT_DIM, width=2)

    def _draw_span_label(self, blk):
        """整块的"文字层"：**一个名字**（**bbox 正中**，`width=` 兜住换行）+ sid + 🏕

        · **名字只画一次**：画在整块 bbox 的**正中央**（与单格一致的"居中"口径 ✓），
          `width=` 用 **bbox 宽度**兜住换行（在成员格上各画一遍会糊 ✗）；
        · **sid 后缀小字只在锚点格左上角**（1 处）；
        · **营地**（名字含「营地」或它就是 `camp`）⇒ 底色已蓝，🏕 画在 **bbox 顶部中间**
          （各成员格都画一遍会一串帐篷 ✗）。
        ⚠ 锚点那条记录缺失（`rec is None`）⇒ 只留底色（雾灰），**不编名字也不抛** ✓
        """
        rec = blk['rec']
        bx0, by0, bx1, by1 = blk['bbox']
        bw = bx1 - bx0
        # ⛔⛔ 2026-10-12 用户：「**实时棋盘的文字居中不对，因为有 3 格的，文字直接出框了**」
        #   ── 根因：**用 bbox 正中心当锚点，对 L 形块是错的** ──
        #     真机多格块里有 **L 形三格**（如「蘑菇丛」= (1,1)/(2,1)/(2,2)）——
        #     它的 bbox 是 2×2 的正方形，**bbox 正中心落在右下那格 (2,2) 的对角交点附近**，
        #     而 (2,2) 恰好是成员 ⇒ 看着还行；但换成「矿箱堆」(1,3)/(2,3)/(2,4) 这类
        #     **中心可能落进不属于本块的那一格**（bbox 覆盖 4 格、本块只占 3 格）
        #     ⇒ 文字画到**别人的格子上**、宽度按 bbox 算 ⇒ **视觉出框** ✗✗
        #   ⇒ 修法：**锚点 = 本块成员格的几何质心**（不是 bbox 中心 ✗），
        #     并把 `width=` 收紧到"质心所在那一格的宽度"（宁可换行也别出块 ✓）
        _cs = sorted(blk.get('cells') or [])
        if _cs:
            _mx = sum((self._cell_rect(r, c)[0] + self._cell_rect(r, c)[2]) / 2.0
                      for r, c in _cs) / len(_cs)
            _my = sum((self._cell_rect(r, c)[1] + self._cell_rect(r, c)[3]) / 2.0
                      for r, c in _cs) / len(_cs)
        else:                                   # 兜底：没有 cells 就退回 bbox 中心（老行为 ✓）
            _mx, _my = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
        cx, cy = _mx, _my
        # ⚠ 名字宽度：取"质心落在哪一格"的宽度 - 余量 ⇒ **保证不出本格**（L 形块尤其重要 ✓）
        _wr = min(blk['cells'], key=lambda rc: abs(
            (self._cell_rect(*rc)[0] + self._cell_rect(*rc)[2]) / 2.0 - cx)
            + abs((self._cell_rect(*rc)[1] + self._cell_rect(*rc)[3]) / 2.0 - cy)) \
            if _cs else None
        _cell_w = (self._cell_rect(*_wr)[2] - self._cell_rect(*_wr)[0]) if _wr else bw
        if rec is not None:
            # ⚠ 与 `_draw_cell` **同一类**"左上角 sid 后缀小字" ⇒ 同样听 `show_sid`
            #   （另一半在 `_draw_cell` 里）—— 只加这一道闸，**底色判据与画法一字未动** ✓
            if rec['sid'] and self.show_sid:
                ax0, ay0, _, _ = self._cell_rect(*blk['anchor'])
                self.create_text(ax0 + 3, ay0 + 2, anchor='nw', text=rec['sid'][:4],
                                 font=T.FONT_TINY, fill=T.C_TEXT_DIM)
            if rec['name']:
                f_name = T.FONT_MONO if self.cell >= 56 else T.FONT_TINY
                # ⭐ 记下 item ⇒ 序号圆要贴在这个名字右边（用户口径 ✓）
                _it2 = self.create_text(cx, cy, anchor='center',
                                        text=_short_name(rec['name'], _cell_w),
                                        font=f_name, fill=T.C_TEXT,
                                        width=max(8, _cell_w - 8))  # 按**单格**宽 ⇒ 不出框 ✓
                try:
                    # ⚠ 用 `anchor` 当键（`blks` 里**没有** `idx` 字段 —— 第一版我写了
                    #   `blk['idx']` ⇒ KeyError，本轮自查抓到）；`anchor` 在块内唯一 ✓
                    self._span_name_items[blk['anchor']] = _it2
                except Exception:       # noqa: BLE001
                    pass
        if blk['camp']:
            self.create_text(cx, by0 + 1, anchor='n', text='🏕',
                             font=T.FONT_TINY_UI, fill=T.C_TEXT)

    def _plan_center(self, rc, member, blks):
        """计划步的**锚点**：⭐ **格名文字的正上方**（用户 2026-10-12 口径）

        ⭐⭐ 用户原话（先后两次，以**最后一次**为准）：
          · 先：「步数的那个 123 号标记位置改成**紧挨着字体右边**吧」
          · 后：「**步数的圆图标位置改为紧挨字体正上面**」← **本次采用这条** ✓
          ⇒ 返回 `(文字水平中心, 文字顶边)` ⇒ 由 `_draw_order` 把圆画在**正上方** ✓
          ⚠ 用**名字 item 的 `bbox()`** 实测（名字长短不同、还会换行 ⇒ 只有实测才贴得准 ✓）
          ⚠ 取不到名字 item（该格没名字 / `delete('all')` 后的旧 id）
            ⇒ **退回兜底**（格/块的真·右上角）⇒ 永不抛、也不画到空气里 ✓
        """
        try:
            # ① 该步所在格**自己**的名字 item（单格直接命中；多格块取块的名字 ✓）
            _it = (self._name_items or {}).get(rc)
            if _it is None and member and blks:
                _bi = (member or {}).get(rc)
                if _bi is not None:
                    # ⚠⚠ 键是**块的 `anchor`（`(r,c)` 元组）**，不是块下标 ✗
                    #   —— 第一版写成 `.get(_bi)`（整数）⇒ 永远取不到 ⇒ 多格块静默退回
                    #      老行为、而单格正常 ⇒ **看着"只对三格没生效"** ✓
                    _anc = (blks[_bi] or {}).get('anchor')
                    _it = (self._span_name_items or {}).get(_anc)
            if _it is not None:
                _bb = self.bbox(_it)            # (x0,y0,x1,y1)；取不到 ⇒ None
                if _bb:
                    # ⭐ **文字水平中心 + 文字顶边** ⇒ 圆画在**正上方** ✓
                    return ((_bb[0] + _bb[2]) / 2.0, _bb[1])
        except Exception:                           # noqa: BLE001
            pass
        # ② 兜底（没有名字 / bbox 取不到）⇒ 本格（或本块真·右上角格）的顶边中点
        #   ⚠ 与"正上方"语义一致：取**该格顶边中点**（不是右上角）✓
        try:
            bi = (member or {}).get(rc)
            if bi is not None and blks:
                _cs = sorted(blks[bi].get('cells') or [])
                if _cs:
                    # 取"质心所在那一格"的顶边中点 ⇒ 一定在本块内 ✓
                    _mx = sum((self._cell_rect(*q)[0] + self._cell_rect(*q)[2]) / 2.0
                              for q in _cs) / len(_cs)
                    _wr = min(_cs, key=lambda q: abs(
                        (self._cell_rect(*q)[0] + self._cell_rect(*q)[2]) / 2.0 - _mx))
                    x0, y0, x1, _y1 = self._cell_rect(*_wr)
                    return ((x0 + x1) / 2.0, y0)
                bx0, by0, bx1, by1 = blks[bi]['bbox']            # 兜底（无 cells）
                return ((bx0 + bx1) / 2.0, by0)
        except Exception:                           # noqa: BLE001
            pass
        x0, y0, x1, y1 = self._cell_rect(*rc)
        return ((x0 + x1) / 2.0, y0)                # 格顶边中点（单格）

    def _draw_order(self, seq, member=None, blks=None):
        """计划点序：相邻序号之间箭头连线 + **格名正上方**的序号圆（1,2,3…）

        ⚠ 箭头**先画**、序号圆**后画** ⇒ 圆压住线头，看着像"从圆连到圆" ✓
          （反过来的话线会盖在数字上，字看不清 ✗）。
        ⭐ 锚点走 `_plan_center()`：**文字的水平中心 + 文字顶边** ⇒ 圆画在**正上方** ✓
          ⚠ 但若把圆心**正好**放在顶边上，圆会**压住字头** ⇒ 再往**上抬 `rad + 1`**
            （`cxx` 不变、`cyy = 顶边 - rad - 1`）⇒ 圆**紧贴文字上方、又不压字** ✓
        """
        if not seq:
            return
        rad = max(8.0, self.cell * 0.15)
        pts = []
        for i, rc in enumerate(seq):
            cx, cy = self._plan_center(rc, member, blks)
            # ⭐ 圆心 = **文字水平中心**，纵向 = **文字顶边再往上 `rad + 1`** ⇒ 正上方紧贴 ✓
            cxx, cyy = cx, cy - rad - 1.0
            # ⚠⚠ 夹取的口径（**本轮实测踩过坑，写清楚**）：
            #   · **横向**：只夹到**画布内**（不夹进格内 —— 长名字比格子宽时，
            #     圆心跟着文字中心走才对；夹进格内会与文字**错位** ✗）
            #   · **纵向**：⚠⚠ **绝不能把圆心"往下推"到文字上** ——
            #     第一版拿"块的真·右上角格"当夹取范围，而 **L 形块**那个格的顶边
            #     （88）可能**低于**文字顶边（90）⇒ 夹取把圆压回文字上（实测重叠 14.8px ✗✗）
            #   ⇒ 口径改成：**以上方为优先** —— 只要 `文字顶边 - rad - 1` 在画布内就**原样用**；
            #     只有**探出画布上沿**时才往下让（且让到"不压文字"为止）✓
            try:
                _pad = 8.0                                   # = `_BPAD`（画布留白）
                # 横向：夹到画布内 ✓
                cxx = min(max(cxx, _pad + rad), self._px_w() - _pad - rad)
                # 纵向：默认信任"正上方"；仅当探出画布上沿 ⇒ 下移到画布内 ✓
                _top_lim = _pad + rad                        # 画布内最高的圆心
                if cyy < _top_lim:
                    cyy = _top_lim
                # 且**绝不**低到压住文字（文字顶边 - rad - 1 就是"紧贴上方"的位置）
                cyy = min(cyy, cy - rad - 1.0)
                # 最后兜一道：别探出画布下沿 ✓
                cyy = min(cyy, self._px_h() - _pad - rad)
            except Exception:                   # noqa: BLE001
                pass
            pts.append((cxx, cyy, i + 1))
        # ⛔⛔ 2026-10-12 用户：「**步数线条的箭头看不见了**」
        #   ── 根因（几何级）──
        #     箭头 `arrow='last'` 画在**终点 = 下一个圆的圆心**上，
        #     而**后画的圆**（同色 `C_PRIMARY`）正好把它**盖住** ⇒ 箭头整个藏进圆里 ✗✗
        #     `width=2` 的线也很细，圆外边那一小截几乎看不出是箭头 ✓
        #   ⇒ 修法：**两端各缩进 `rad + 2`** ⇒ 线**从圆的边缘出发、箭头落在目标圆的边缘上**
        #     ⇒ 箭头露在圆外、一眼可见 ✓（圆仍是后画 ⇒ 压住线头 ⇒ 接口干净 ✓）
        #     ⚠ 两点重合（同一格连点两次）⇒ 方向向量为 0，**跳过**别除零 ✓
        _gap = rad + 2.0                                    # 圆半径 + 2px 余量
        # ⭐⭐ 2026-10-12 用户：「**步数线条如果是斜着的还不是很直**」
        #   ── 根因（**平台限制**，不是画错坐标）──
        #     Tk **8.6** 的 Canvas **完全没有抗锯齿**（已实测：`-antialiasing` 不是
        #     合法 item 选项 ✗）⇒ 2px 斜线只能是**阶梯状**像素 ⇒ 看着"不直" ✗
        #   ── 修法：**多条平行细线做伪抗锯齿**（非 AA 画布上的通行做法 ✓）──
        #     沿**法线方向**在正式线两侧各铺若干条 `width=1` 的**中间调**细线，
        #     越靠外越接近底色 ⇒ 阶梯的硬边被"渐变"糊掉 ⇒ 远看线条平滑 ✓
        #     ⚠ 只 1 条晕**不够**（第一版只画 1 条 width=5 ⇒ 截图对比几乎没变化 ✗
        #        —— 因为那条晕自己也是硬边的）⇒ 必须**逐级过渡**才有效 ✓
        #     ⚠ 顺序：**由外向内**画（外圈先、正式线最后）⇒ 中心的实线最完整 ✓
        #     ⚠ 色值一律走 `T.blend()`（组件里不许出现硬编码色值 —— 本仓纪律 ✓）
        _segs = []
        for a, b in zip(pts, pts[1:]):
            _dx, _dy = b[0] - a[0], b[1] - a[1]
            _d = (_dx * _dx + _dy * _dy) ** 0.5
            if _d <= 1e-6:
                continue                                    # 同点 ⇒ 没有方向，不画 ✓
            _ux, _uy = _dx / _d, _dy / _d
            # ⚠ 太短的连线（两圆几乎贴住）⇒ 缩进后反了 ⇒ 保底留 1px，别画反 ✓
            _sh = min(_gap, max(0.0, (_d - 1.0) / 2.0))
            # 法线（用于向两侧铺过渡线）✓
            _nx, _ny = -_uy, _ux
            _segs.append((a[0] + _ux * _sh, a[1] + _uy * _sh,
                          b[0] - _ux * _sh, b[1] - _uy * _sh, _nx, _ny))
        # ① 两侧的过渡细线：偏移越远 ⇒ 越接近底色（`t` 越大）✓
        #    偏移 1.0px ⇒ t=0.45（较实）；偏移 2.0px ⇒ t=0.75（很淡）✓
        for _off, _t in ((2.0, 0.78), (1.0, 0.45)):
            try:
                _col = T.blend(T.C_PRIMARY, T.BOARD_BG, _t)
            except Exception:               # noqa: BLE001
                break
            for _x0, _y0, _x1, _y1, _nx, _ny in _segs:
                for _sgn in (1.0, -1.0):
                    try:
                        self.create_line(_x0 + _nx * _off * _sgn,
                                         _y0 + _ny * _off * _sgn,
                                         _x1 + _nx * _off * _sgn,
                                         _y1 + _ny * _off * _sgn,
                                         fill=_col, width=1, capstyle='round')
                    except Exception:       # noqa: BLE001
                        break
        # ② 正式线（带箭头；箭头露在圆外 ✓）
        for _x0, _y0, _x1, _y1, _nx, _ny in _segs:
            self.create_line(_x0, _y0, _x1, _y1, fill=T.C_PRIMARY, width=2,
                             arrow='last', capstyle='round')
        for cxx, cyy, n in pts:
            self.create_oval(cxx - rad, cyy - rad, cxx + rad, cyy + rad,
                             fill=T.C_PRIMARY, outline=T.BOARD_BG, width=2)
            self.create_text(cxx, cyy, text=_s(n), font=T.FONT_TINY_UI, fill=T.BOARD_BG)
