# -*- coding: utf-8 -*-
"""bot_gui_ui/ctk_widgets.py · customtkinter 版小组件（T6 · 2026-10-12）

为什么单独一个文件
------------------
T6 把整窗迁到 **customtkinter 6.0**（工单 `06-PC端UI执行工单.md` §T6）。但有三样东西
**必须保留 tk/tkinter**（门禁字符串钉着 + ctk 没有等价物）：

| 保留 tk 的东西 | 为什么 |
|---|---|
| 日志 `ScrolledText` | `verify_lock_kind.py` 真跑 `show_red_lock()` 并调 `self.txt.get('1.0','end')` ⇒ `CTkTextbox` 的 API 不同 ✗ |
| 存图勾选 `tk.Checkbutton(bar2, …)` | `verify_hotupdate.py` T16f 按**字面量** `'tk.Checkbutton(bar2'` 钉着它 |
| 棋盘 `BoardCanvas`（tk.Canvas） | ctk 没有等价的自绘棋盘（工单 §0 已定稿"保留 tk/ctk 混排"） |

⇒ 本文件只放**能安全 ctk 化**的小组件：目前是 `CtkCard`（仪表盘小卡）。
   ⚠ 所有色值**只从 `ctk_theme.palette()` 取**（组件里不许出现硬编码色值 —— 与 `theme.py` 同一条纪律 ✓）。
"""
import customtkinter as ctk

from . import ctk_theme as C


class CtkCard(ctk.CTkFrame):
    """仪表盘小卡（customtkinter 版）：标题 + 大数值 + 副标题

    · **圆角 12**（工单 §0 定稿「卡片：圆角 12」✓）
    · 三行文字：标题（小、灰）、数值（大、主色粗体）、副标题（小、灰）
    · 接口与旧的 ttk `StatCard` **保持一致**：`set(value=None, sub=None, title=None)`
      ⇒ 上层的 `_update_dashboard` 一行都不用改 ✓（`None` = 不改）
    · **任何坏数据都不抛**（GUI 跑在 pythonw 无控制台 ⇒ 抛了用户看不见 ✓）

    ⭐⭐ 2026-10-12 **T6 §7② 治本**：色值一律用 `ctk_theme.palette()` 的
      **双色元组** `(浅色, 深色)` ⇒ `ctk.set_appearance_mode()` 一切全换，
      **不再需要** `restyle()` 手动重设（那正是 §7② 点名的病根：显式单值 = 切换不变 ✗）✓
      ⚠ 字号走 `ctk_theme.FS_*` 阶梯（§8 表 1），组件里**不许写裸数字** ✓
    """

    def __init__(self, master, title='', value='—', sub='', mode=None, big=False):
        """`big=True` ⇒ 数值用**大一档**字号（`FS_NUM_BIG`；给"进图体力"那张 8 字符卡 ✓）

        ⭐ 2026-10-12 用户：「**进图体力显示稍微大一点的，现在两个四位数最后一位数
          可能显示不全**」⇒ `big` 只加字号、不改配色；配合 `bot_gui` 里第 0 列的
          **双份列宽** ⇒ `1234→1234` 实测有余量 ✓
        ⛔ 一度还按"汉字黑体 / 数字 Times New Roman"分族，用户已要求**换回**原字体
          ⇒ 现在全窗单一族（`FS_*` 的 `_FONT = 'Microsoft YaHei UI'`）✓
        """
        _p = C.palette()            # ⚠ **不给 mode** ⇒ 双色元组（ctk 自动跟随主题 ✓）
        # ⭐⭐ 2026-10-18 方案 A「视觉层次精修」：卡片**加 1px 描边**
        #   实测病：卡底 `#FFFFFF` 与窗口底 `#F0F1F3` 对比度只有 **1.13:1**
        #     （深色 `#2B2D31` vs `#1E1F22` = 1.195:1）⇒ 卡片边界全靠圆角形状去猜 ✗
        #   ⇒ `border_width` 0 → **1**，色走 `palette()['border']`（双色元组 ⇒ 切主题自动跟 ✓）
        #   ⚠ 不占布局高度：ctk 的 border 画在圆角框内，`DASH_H`(78) 不变 ✓
        super().__init__(master, corner_radius=12, fg_color=_p['card'],
                         border_width=1, border_color=_p['border'])
        self._big = bool(big)
        self._num_spec = C.FS_NUM_BIG if self._big else C.FS_NUM
        # ⭐⭐ 2026-10-13 「手绘效果图 1:1 复刻」（docs/09）：**三行高度必须显式给**
        #   ⛔ 病：`ctk.CTkLabel` 的默认高**恒为 28px**（连 9pt 的字也是 28 ✗）⇒
        #     卡片自然高 = 8 + 28 + 28 + 28 + 8 = **102px**，而效果图是 **78px** ✗
        #   ⇒ 标题/副标题（`FS_HINT` 9pt；`linespace` 实测 17）给 **T.LBL_H = 17**；
        #     数值给 **28**（`FS_NUM_BIG` 16pt 的 `linespace` 实测就是 28 ⇒ 一格不裁 ✓）
        #   ⇒ 8 + 17 + 28 + 17 + 8 = **78 = `theme.DASH_H`**（探针会逐卡拉尺复核 ✓）
        self._title = ctk.CTkLabel(
            self, text=str(title or ''), text_color=_p['dim'],
            font=C.font(C.FS_HINT), anchor='w', height=17)
        self.value = ctk.CTkLabel(
            self, text=str(value or '—'), text_color=_p['primary'],
            font=C.font(self._num_spec), anchor='w', height=28)
        self._sub = ctk.CTkLabel(
            self, text=str(sub or ''), text_color=_p['dim'],
            font=C.font(C.FS_HINT), anchor='w', height=17)
        self._title.pack(anchor='w', padx=10, pady=(8, 0))
        self.value.pack(anchor='w', padx=10, pady=(0, 0))
        self._sub.pack(anchor='w', padx=10, pady=(0, 8))

    def set(self, value=None, sub=None, title=None):
        """改显示内容；**None = 不改**（三个参数都可为 None）⚠ 坏数据不抛"""
        try:
            if title is not None:
                self._title.configure(text=str(title))
            if value is not None:
                self.value.configure(text=str(value))
            if sub is not None:
                self._sub.configure(text=str(sub))
        except Exception:           # noqa: BLE001
            pass

    def restyle(self, mode=None):
        """**保留但已不需要**（§7② 治本后元组会自己跟随主题 ✓）

        ⚠ 留着是因为主窗口可能还调它一次（幂等、无害）；**新代码不要依赖它** ——
          「显式单值 + 切换时手动重设」正是 §7② 要消灭的那套做法 ✗
        """
        try:
            _p = C.palette()
            self.configure(fg_color=_p['card'])
            self._title.configure(text_color=_p['dim'])
            self.value.configure(text_color=_p['primary'])
            self._sub.configure(text_color=_p['dim'])
        except Exception:           # noqa: BLE001
            pass


class ThemeSwitch(ctk.CTkFrame):
    """浅色/深色两段开关 —— ⭐ 2026-10-13 复刻手绘效果图（docs/09）

    为什么要自己写（而不是用 `ctk.CTkSegmentedButton`）：
      · ctk 那个分段按钮**宽度压不住**（构造给 `width=118`，实测只有 **68px**），
        且**选中段底色与未选中段文字共用一个 `text_color`** ⇒ 做不出效果图那样的
        「白胶囊 + 靛蓝字 ｜ 未选中：透明底 + 灰字」✗
      · 效果图里的控件是：**118×26 圆角容器（`card2` 底 + 1px `border`）**，
        左半「浅色」= **白胶囊（`card`）+ 主色字**，右半「深色」= 透明底 + 灰字 ✓

    接口：`set(label)`（与 `CTkSegmentedButton` 同名 ⇒ `_on_theme_pick` 一行都不用改 ✓）
    颜色全部走 `palette()` 双色元组 ⇒ 切主题自己跟 ✓（构件里无硬编码色值 ✓）
    """

    def __init__(self, master, values=('浅色', '深色'), command=None,
                 width=118, height=26, **kw):
        _p = C.palette()
        # ⚠ `width/height` 必须**显式收在这里**：否则调用方传的同名实参会与
        #   下面 `super().__init__(width=…)` 撞成
        #   `TypeError: got multiple values for keyword argument 'width'` ✗（本轮踩到）
        super().__init__(master, width=width, height=height, corner_radius=6,
                         fg_color=_p['card2'], border_width=1,
                         border_color=_p['border'], **kw)
        self._command = command
        self._vals = list(values)
        self._seg = {}
        _half = max(40, (int(width) - 4) // 2)      # 每半宽（118 ⇒ 57）✓
        for _i, _v in enumerate(self._vals):
            _lbl = ctk.CTkLabel(self, text=_v, width=_half - 2, height=int(height) - 4,
                                corner_radius=5, font=C.font(C.FS_SUB))
            _lbl.place(x=2 + _i * _half, y=2)
            _lbl.bind('<Button-1>', lambda _e, vv=_v: self._pick(vv))
            _lbl.bind('<Enter>', lambda _e, vv=_v: self._hover(vv))
            self._seg[_v] = _lbl
        self._cur = self._vals[0] if self._vals else ''
        self._paint()

    # ---- 外观 ----
    def _paint(self, hover=None):
        _p = C.palette()
        for _v, _lbl in self._seg.items():
            try:
                if _v == self._cur:
                    _lbl.configure(fg_color=_p['card'], text_color=_p['primary'])
                elif _v == hover:
                    _lbl.configure(fg_color=_p['card2'], text_color=_p['text'])
                else:
                    _lbl.configure(fg_color='transparent', text_color=_p['dim'])
            except Exception:       # noqa: BLE001
                pass

    def _hover(self, v):
        self._paint(hover=v)

    def _pick(self, v):
        self.set(v)
        if callable(self._command):
            try:
                self._command(v)
            except Exception:       # noqa: BLE001
                pass

    # ---- 接口（与 CTkSegmentedButton 同名 ⇒ 调用方不用改 ✓）----
    def set(self, label=None, **kw):
        try:
            if label in self._seg:
                self._cur = label
                self._paint()
        except Exception:           # noqa: BLE001
            pass

    def get(self):
        return self._cur
