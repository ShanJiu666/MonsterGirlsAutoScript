# -*- coding: utf-8 -*-
"""bot_gui_ui/datasource.py · UI 数据层（UI 重设计 Step 2，2026-10-11）

口径出处：`docs/05-PC端UI重设计方案与开发规划.md` §6 Step 2 / §4.4 / 附录 C / 附录 E.1·E.2·E.6。

    「数据层**纯只读**；全部用 `root.after` 轮询驱动，**不许自起线程直接碰 UI**」
    —— 这是现 UI 痛点 P3（后台线程直接改 tk 组件 ⇒ 偶发闪退）的修法 ✓

四个只读封装
------------
| 类 | 数据源 | 刷新方式 |
|---|---|---|
| `SummaryWatcher` | `runs/[tag/]last_summary.json` | **mtime 感知**：没变就一个字节都不解析 |
| `LoopLogTail` | `runs/[tag/]loop/loop_log.json` | 同上；取事件数组尾部（最新 board / HUD / plan） |
| `LockState` | `.loop_<port>.lock`、`red_equip_<port>.lock.json`、`<tag\\|default>/.gui.lock` | 按需读 |
| `HotState` | `hot/state.json` | **只读封装** `hotupdate.load_state()/status_line()`，不重写它的逻辑 |

⚠⚠ 两条铁律（本仓历史上反复踩的坑都在这两条上）
--------------------------------------------
1. **绝不写盘 / 绝不改配置 / 绝不起线程 / 绝不 import GUI 组件** —— 本模块只 `open(..., 'r')`。
   连"顺手 `os.makedirs` 一下"都不许（`hotupdate._log_path()` 那种会自动建目录，**别抄** ✗）。
2. **一切 IO 容错不抛**：GUI 跑在 `pythonw`（无控制台）⇒ 抛了用户**什么都看不见**。
   文件不存在 / 空 / 半截 JSON / 顶层类型不对 / 路径是目录 / 权限错
   ⇒ 返回 `None` 或**上次的值**，原因记进 `last_error`，**绝不上抛** ✓

   ⭐ 为什么必须"保留上次的好值"：`explore_loop.dump_summary()` 落盘用的是
      `open(SUMMARY_PATH, 'w') + json.dump(...)`（**不是原子替换** ✗，见 `explore_loop.py:371`，
      而 `hotupdate.write_json()` 才是 `os.replace` 原子替换）⇒ UI 若正好在写的中间读，
      就会读到半截 ⇒ 这时**绝不能把面板清空**（旧 UI 的"读数一闪变空"就是这么来的 ✓）。

用法（主窗口侧，**全部在主线程 `after` 里**）
------------------------------------------
    sw   = SummaryWatcher(os.path.join(runs, 'last_summary.json'))
    tail = LoopLogTail(os.path.join(runs, 'loop', 'loop_log.json'))
    lk   = LockState(runs, device='127.0.0.1:16384', tag='')
    hs   = HotState()                     # 默认 = 本包目录的上一级（mapbot_pc/）

    def tick():
        if sw.poll():                     # ⭐ True 才重画（没变就不重解析）
            cards.update(sw.stats)
        tail.poll()
        board.update_board(tail.last_board, tail.last_marks,
                           tail.plan['order'], tail.plan['cost'])
        root.after(1000, tick)

⚠ 已知限制（**如实写在契约里**，不装看不见）
------------------------------------------
- `loop_log.json` 是**整体覆写**（explore_loop 只在 flush 时落盘）⇒ **图内低频刷新**：
  棋盘/HUD 的"实时"精度 = 子进程的 flush 频率，不是 1s（见规划文档附录 E.2 ✓）。
- `poll()` 只在「**指纹变了 且 解析成功**」时返回 True；坏文件返回 False + `last_error`
  ⇒ UI 保持上一帧，不闪断 ✓。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))        # …/mapbot_pc/bot_gui_ui/
PKG_DIR = os.path.dirname(HERE)                          # …/mapbot_pc/（被热更的包目录）

# ⚠ 仓内既有惯例：业务模块在 import 期把自己所在目录挂到 `sys.path`（`explore_loop.py:18` /
#   `mapbot.py:25` / `marks.py:21` …）。本模块**只**为 `import hotupdate`（同目录兄弟模块）这么做，
#   **纯内存操作**：不写盘、不改配置、不起线程 ✓（`mapbot_pc/` 下没有与标准库同名的 .py，无遮蔽风险）
if PKG_DIR and PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

# `stats` 里与"本次会话"无关的字段（UI 想显示"可累加键"时可用；只做参考，不参与逻辑）
STATS_ACC_KEYS = ('maps', 'shots', 'boss_fights', 'boss_wins', 'recommend_fights',
                  'recommend_wins', 'dice_got', 'merchants', 'vaults', 'battles',
                  'battle_wins', 'blind_maps', 'stuck_maps', 'recover_n', 'gifts',
                  'bag_upgrades', 'clovers')
# 仪表盘/HUD 用到的键（缺了不出现，UI 自己画"—"）
HUD_KEYS = ('round', 'stamina', 'gold', 'clover', 'slots_free')


# ───────────────────────── 小工具（全部容错不抛） ─────────────────────────

def _stamp_of(path):
    """文件指纹 `(mtime_ns, size, mtime_float)`；拿不到 ⇒ None。

    ⭐ 为什么不是只比 mtime：子进程 flush 很快，**同一时钟刻度内**覆写会漏
      ⇒ 用 `st_mtime_ns`（NTFS 100ns 精度）+ `size` 双保险 ✓
    """
    try:
        st = os.stat(path)
        ns = getattr(st, 'st_mtime_ns', None)
        if ns is None:                                  # 极老平台兜底
            ns = int(float(st.st_mtime) * 1e9)
        return (int(ns), int(st.st_size), float(st.st_mtime))
    except Exception:                                   # noqa: BLE001  不存在/权限/坏链接…
        return None


def _read_json_file(path):
    """容错读 JSON → `(ok, obj, err)`。**绝不抛**。

    | 情况 | 返回 |
    |---|---|
    | 不存在 | `(False, None, '文件不存在…')` |
    | 路径是目录 | `(False, None, '路径是目录…')` |
    | 空文件 / 半截 JSON / 编码错 / 权限错 | `(False, None, '读取或解析失败：…')` |
    | 正常 | `(True, obj, '')`（**obj 可能是 list/str/None**，由调用方判形状 ✓） |

    ⚠ 用 `utf-8-sig` 读：写方是无 BOM 的 utf-8（`json.dump(..., ensure_ascii=False)`），
      但万一被别的工具加了 BOM，`utf-8` 会在第一个字符上炸 ⇒ `utf-8-sig` 两种都吃得下 ✓
    """
    try:
        if not os.path.exists(path):
            return False, None, '文件不存在：%s' % path
        if os.path.isdir(path):
            return False, None, '路径是目录：%s' % path
        with open(path, encoding='utf-8-sig') as f:
            return True, json.load(f), ''
    except Exception as e:                              # noqa: BLE001  （半截 JSON 也走这里）
        return False, None, '读取或解析失败：%r' % (e,)


def _first_num(v):
    """从 `order_cost[cell]` 里取**第一个数字**；取不到 ⇒ None。**绝不抛**。

    ⚠ 契约要求"值是 list/tuple/dict 都能取"（`explore_loop` 各版本形状不同）：
      · 真机现状：`{"1,7": [1, "S10001_001"]}`  → 1 ✓
      · 见过的变体：`{"3,4": {"cost": 4, "sid": "…"}}` → 先认 `cost`/`n` 键，再按插入序取 ✓
      · 字符串数字（`"6"`）也算数；**纯文本**（`"S10001_001"`）不算，会继续往后找 ✓
    """
    if isinstance(v, bool):                             # ⚠ bool 是 int 的子类，必须先挡
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (list, tuple)):
        for x in v:
            n = _first_num(x)
            if n is not None:
                return n
        return None
    if isinstance(v, dict):
        for k in ('cost', 'n'):                         # 语义键优先（顺序不同也能取对）
            if k in v:
                n = _first_num(v[k])
                if n is not None:
                    return n
        for x in v.values():                            # 再按插入序
            n = _first_num(x)
            if n is not None:
                return n
        return None
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except Exception:                               # noqa: BLE001
            try:
                return float(s)
            except Exception:                           # noqa: BLE001
                return None
    return None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _key_shape_ok(k):
    """棋盘键形状 `"行,列"`（1 基，5 行 × 7 列 ⇒ 附录 E.2）"""
    try:
        a, b = str(k).split(',')
        return int(a) >= 0 and int(b) >= 0
    except Exception:                                   # noqa: BLE001
        return False


# ───────────────────────── 仪表盘：last_summary.json ─────────────────────────

class SummaryWatcher:
    """轮询 `runs/[tag/]last_summary.json`（**mtime 感知**：没变就不重解析）。

    数据形状（`explore_loop.dump_summary()` 逐字，见附录 C/E.1）::

        {"stats": {...24 张图一局的全部计数...},
         "text": "════════ 本次统计 ════════\\n…",
         "tag": "", "device": "127.0.0.1:16384"}

    ⭐ `poll()` 返回 True 才算"有新数据"，主窗口只在那时重画 ✓
    """

    def __init__(self, path):
        self._path = str(path)
        self._stamp = None          # 上次**成功解析**的指纹
        self._d = {}                # 上次成功解析的 dict（坏文件时**原样保留** ✓）
        self._mtime = None
        self._last_error = ''
        self._poll_n = 0            # 轮询次数（排查用；UI 不依赖）
        self._read_n = 0            # 真正落盘解析的次数（mtime 命中时不涨 ✓）

    # ---- 轮询 ----
    def poll(self):
        """→ True=文件**变过且已重新解析成功**；False=没变 / 读失败（`last_error` 里有原因）。

        ⚠ 坏文件也记指纹 ⇒ 同一份坏文件不会每轮重复解析（大文件才不白烧 CPU ✓）；
          写方下次落盘 mtime 又变 ⇒ 照样能读到 ✓
        """
        self._poll_n += 1
        st = _stamp_of(self._path)
        if st is None:
            self._last_error = '文件不存在或不可访问：%s' % self._path
            return False
        if self._stamp is not None and st == self._stamp:
            return False                                # ⭐ mtime/size 没变 ⇒ 一个字节都不解析
        ok, obj, err = _read_json_file(self._path)
        self._stamp = st                                # 无论好坏都记指纹（见上面 ⚠）
        if not ok:
            self._last_error = err
            return False                                # ⚠ **保留上次的 stats**
        if not isinstance(obj, dict):
            self._last_error = '顶层不是 dict（实际 %s）⇒ 不采用' % type(obj).__name__
            return False                                # ⚠ 同上：不清空旧值
        self._d = obj
        self._mtime = st[2]
        self._last_error = ''
        self._read_n += 1
        return True

    # ---- 只读属性 ----
    @property
    def stats(self):
        """`d['stats']`；没有或是坏类型 ⇒ `{}`（**绝不是 None**，UI 免判空）"""
        s = self._d.get('stats')
        return s if isinstance(s, dict) else {}

    @property
    def text(self):
        """`d['text']`；没有 ⇒ `''`"""
        t = self._d.get('text')
        return t if isinstance(t, str) else ''

    @property
    def tag(self):
        """`d['tag']`；没有 ⇒ `''`"""
        t = self._d.get('tag')
        return t if isinstance(t, str) else ''

    @property
    def device(self):
        """`d['device']`；没有 ⇒ `''`"""
        t = self._d.get('device')
        return t if isinstance(t, str) else ''

    @property
    def running(self):
        """是否正在跑。

        ⚠ 真实数据里 `running` 在 **`stats` 里**（`explore_loop.STATS['running']`，`:146`）；
          这里**先认顶层**（万一将来提到顶层）再回落 `stats` ⇒ 两种形状都对 ✓ 读不到 ⇒ False
        """
        if 'running' in self._d:
            return bool(self._d.get('running'))
        return bool(self.stats.get('running', False))

    @property
    def mtime(self):
        """**上次成功解析**那版的 mtime（float）；从没成功过 ⇒ None"""
        return self._mtime

    @property
    def last_error(self):
        """最近一次 poll 的出错原因；`''` = 没出错"""
        return self._last_error

    @property
    def path(self):
        return self._path

    @property
    def has_data(self):
        """是否**成功解析过至少一次**（用来区分"从没数据"和"读失败但有旧值"）"""
        return bool(self._d)

    @property
    def poll_n(self):
        return self._poll_n

    @property
    def read_n(self):
        return self._read_n

    # ---- 取值 ----
    def stats_of(self, keys, default=0):
        """从 `stats` 里挑几个键出来 → dict（键不存在给 `default`）。

        ⚠ `keys` 传字符串也吃（当成一个键），免得调用方写 `stats_of('maps')` 时
          被逐字符迭代（那是**静默取错值**，比抛异常更难查 ✗）
        """
        if isinstance(keys, str):
            keys = [keys]
        try:
            ks = list(keys)
        except Exception:                               # noqa: BLE001
            return {}
        s = self.stats
        out = {}
        for k in ks:
            out[k] = s.get(k, default)
        return out


# ───────────────────────── 实时棋盘：loop/loop_log.json ─────────────────────────

class LoopLogTail:
    """读 `runs/[tag/]loop/loop_log.json`（**事件数组**，取尾部 `max_events` 条）。

    事件序列（一图约 40~50 条，附录 E.2）::

        pre → stamina → pre_gate → enter → fog_wait → shot → mapname → hud_lock
        → obs_merge → solver(ok: cost+steps+order) → plan → round(含 board/marks/taps)
        → round_end → popup → battle → collect → map(end_reason) → finish → map(finished…)

    ⚠ **整体覆写**：文件是 `flush` 才落盘（不是逐行 append）⇒ **图内低频刷新**
      是**已知限制**，不是本模块能修的（契约里已写明 ✓）。
    """

    def __init__(self, path, max_events=500):
        self._path = str(path)
        try:
            self._max = max(1, int(max_events))
        except Exception:                               # noqa: BLE001
            self._max = 500
        self._stamp = None
        self._events = []           # 上次成功解析的**尾部**事件（坏文件时原样保留 ✓）
        self._mtime = None
        self._last_error = ''
        self._total = 0             # 文件里的事件总数（截尾前；排查用）
        self._poll_n = 0
        self._read_n = 0

    # ---- 轮询 ----
    def poll(self):
        """→ True=文件变过且已重新解析；False=没变 / 读失败（`last_error` 里有原因）"""
        self._poll_n += 1
        st = _stamp_of(self._path)
        if st is None:
            self._last_error = '文件不存在或不可访问：%s' % self._path
            return False
        if self._stamp is not None and st == self._stamp:
            return False                                # ⭐ mtime/size 没变 ⇒ 不重解析
        ok, obj, err = _read_json_file(self._path)
        self._stamp = st
        if not ok:
            # ⭐⭐⭐ 2026-10-19 **解析失败就隔 50ms 重试一次**
            #   ---- 真机事故 ----
            #     `explore_loop.flush()` 原来用 `open('w')` **截断后写**（~200KB/几十 ms），
            #     而本函数用 **mtime/size 指纹**判"变了没" ⇒ 截断瞬间 size 变小 ⇒
            #     立刻来解析 ⇒ 读到半截 ⇒ `JSONDecodeError('Expecting property name…')`
            #     （gui_console_20261019.log 16:21:52 有这条原文 ✓）
            #     ⇒ 失败时**保留上次 events** ⇒ 棋盘停在上一张图 ✗✗
            #   ---- 两道修 ----
            #     写侧已改**原子替换**（`.tmp` + `os.replace`）⇒ 理论上不会再有半截
            #     这里再加**一次重试**：万一别处非原子写 / Windows 上被杀软占用 ✓
            #   ⚠ 只重试一次（50ms）—— 别把 2 秒一拍的 tick 拖长 ✗
            #   ⚠ 实测（Windows 并发压力）：**失败全是 PermissionError、内容不残缺**
            #     ⇒ 不是"读到半截"，是 `os.replace` 换名瞬间 `open()` 被短暂拒绝
            #     ⇒ 重试就够。量化：3 次×50ms ⇒ 失败 4 → **0**（1 次会有残余）
            for _try_r in range(3):
                try:
                    import time as _t_r
                    _t_r.sleep(0.05)
                    ok2, obj2, err2 = _read_json_file(self._path)
                except Exception:               # noqa: BLE001
                    continue
                if ok2:
                    ok, obj, err = ok2, obj2, ''
                    break
        if not ok:
            self._last_error = err
            return False                                # ⚠ 保留上次的 events / board
        if not isinstance(obj, list):
            self._last_error = '顶层不是 list（实际 %s）⇒ 不采用' % type(obj).__name__
            return False
        evs = [e for e in obj if isinstance(e, dict)]
        drop = len(obj) - len(evs)
        self._events = evs[-self._max:]
        self._total = len(evs)
        self._mtime = st[2]
        self._last_error = ('有 %d 条非 dict 事件已忽略' % drop) if drop else ''
        self._read_n += 1
        return True

    # ---- 基础只读属性 ----
    @property
    def events(self):
        """尾部 `max_events` 条事件（**副本**，改它不会污染内部状态 ✓）"""
        return list(self._events)

    @property
    def last_event(self):
        """尾部最后一条事件（dict）| None"""
        return self._events[-1] if self._events else None

    def _last_with(self, key):
        for e in reversed(self._events):
            if key in e:
                return e
        return None

    @property
    def board_snapshot(self):
        """尾部最后一条 **`board_snapshot` 事件**（dict）| None

        ⭐⭐ 2026-10-12 新增。为什么需要它（**这是"实时棋盘一直在变 / 越改越差"的根因**）：
          `loop_log` 里同一张图有**两种** board 事件，格数差很多（真机实测）：
            · `board_snapshot` —— `explore_loop` 在**进图首轮**追加一次，是**整盘**
              （实测 **26~29 格**；含进图那一刻扫到的全部格名 + 标记）
            · 每轮的 `round` 事件 —— 只带**本轮观测到的那一小片**（实测 **9~12 格**）
          ⇒ `last_board` 的优先级是 `round > board_snapshot` ⇒ 拿到的是**稀疏板**，
            而且**一轮一个样**（一会儿 9 格一会 28 格）⇒ 棋盘看着一直在变 ✗
          ⇒ 本属性把"**进图首帧的整盘**"单独给出来，供"每图冻一版"的调用方取用 ✓
        ⚠ 只读、返回**内部那条 dict 本身**（不做深拷贝；调用方要改请自己拷）
        """
        return self._last_with('board_snapshot')

    @property
    def last_round(self):
        """尾部最后一条**含 `round` 键**的事件。

        ⚠ `round_end` / `round` 是两个不同的键（`round_end` 不含 `round`）⇒ 不会串 ✓
        """
        return self._last_with('round')

    @property
    def last_solver(self):
        """尾部最后一条**含 `solver` 键**的事件（**原样返回，不猜结构** —— 各版本字段不同）"""
        return self._last_with('solver')

    # ---- 棋盘 ----
    def _board_ev(self):
        """给出 board 的那条事件：`round` > **`board_snapshot`** > 旧 board 事件

        ⭐⭐ 2026-10-12（工单 06 T3 / 规划 05 §4.5c）：`explore_loop` 在**进图首轮**
        追加了一条 `{'board_snapshot': True, 'board': …}` 并**只 flush 这一次**
        ⇒ 棋盘能在**进图 ~1 秒、真机开始点之前**就画出格名/雾格 ✓
        优先级：`round` 更新鲜（每轮都可能有新观测），snapshot 只补"进图那一刻" ✓
        ⚠ 它是**新字段名**（不复用 `round`）⇒ 不会被当成"真打了一轮" ✓
        """
        lr = self.last_round
        if lr is not None and isinstance(lr.get('board'), dict):
            return lr
        snap = self._last_with('board_snapshot')
        if snap is not None and isinstance(snap.get('board'), dict):
            return snap
        for e in reversed(self._events):
            if isinstance(e.get('board'), dict):
                return e
        return None

    @property
    def last_board(self):
        """`{"行,列": [sid后缀, 地块名, score, ratio]}`（附录 E.2）| None

        ⚠ **原样返回**（不做清洗）：契约是"board 是 dict ⇒ 返回它"。
          个别格子的值形状奇怪（`"abc"`）也照样返回 ⇒ 由 `BoardCanvas` 自己兜底，
          本层**不许**因为一格坏就把整盘丢掉（那会让棋盘无故变空 ✗）。
        """
        e = self._board_ev()
        return e.get('board') if e is not None else None

    @property
    def board_round(self):
        """给出那条 board 的 `round` 号；没有 / 不是 int ⇒ None"""
        e = self._board_ev()
        if e is None:
            return None
        r = e.get('round')
        return int(r) if isinstance(r, int) and not isinstance(r, bool) else None

    @property
    def last_marks(self):
        """`last_round['marks']`（**是 dict 才用**）；否则 `{}`（`{"3,1": ["boss"]}`）

        ⭐ 2026-10-12 T3：没有 round 事件时**回落到给出 board 的那条事件**的 marks
        —— `board_snapshot` 自带 marks（进图那一刻扫到的标记）⇒ 开局就能画角标 ✓
        ⚠ 优先级不变：**round 有就听 round** ✓
        """
        lr = self.last_round
        m = lr.get('marks') if lr is not None else None
        if not isinstance(m, dict):
            e = self._board_ev()
            m = e.get('marks') if isinstance(e, dict) else None
        return m if isinstance(m, dict) else {}

    # ---- HUD / 计划 ----
    @property
    def hud(self):
        """`{'round','stamina','gold','clover','slots_free'}` —— **缺的键不出现**。

        ⚠ 值为 `null` 的键也**不出现**：真机日志见过 `"clover": null`（读不出幸运草，
          见手机端 v1.71 那一族坑）⇒ 若原样给 UI，会被画成字符串 `"None"` ✗
          ⇒ 这里当"没读到"，让 UI 走自己的"—"兜底 ✓
        """
        lr = self.last_round
        out = {}
        if lr is None:
            return out
        for k in HUD_KEYS:
            v = lr.get(k)
            if v is not None:
                out[k] = v
        return out

    @property
    def plan(self):
        """`{'order': [...], 'steps': int, 'cost': int|None}`（**四个字段以外的键不返回**）。

        构造规则（**逐条容错，不许抛**）::

            order = last_round['solver_order']  （**list/tuple 才用**；str/None ⇒ []）
            steps = len(order)
            cost  = sum( order_cost[cell] 的第一个数字 for cell in order )

        ⚠ `cost` 何时是 None：
          · `order` 为空（没计划 ⇒ 无从求和，UI 画"—"）
          · `order_cost` 不是 dict / 缺某个 cell / 该 cell 取不到数字
          ⇒ **宁可画"—"，也不给一个"少加了一半"的错数**（那会静默误导 ✗）
        """
        lr = self.last_round
        order = []
        oc = None
        if lr is not None:
            o = lr.get('solver_order')
            if isinstance(o, (list, tuple)):            # ⚠ 是 str 就丢（"1,7" 会被逐字符迭代 ✗）
                order = list(o)
            oc = lr.get('order_cost')
        cost = None
        if order and isinstance(oc, dict):
            nums = []
            for c in order:
                n = _first_num(oc.get(c))
                if n is None:
                    nums = None
                    break
                nums.append(n)
            if nums is not None:
                cost = sum(nums)
        return {'order': order, 'steps': len(order), 'cost': cost}

    @property
    def plan_full(self):
        """⭐ **完整**计划 `{'order': [...], 'steps': int, 'cost': int|None, 'src': str}`

        ⛔ 为什么需要它（2026-10-11 用户真机反馈：「**规划了 5 步只显示了 4 步**」）
        ------------------------------------------------------------------
        `plan` 取的是 round 事件的 `solver_order`，而 `explore_loop` 写这个字段时是
        **"本轮真正要点的前几步"**（`_picked`，硬上限 **4** 步 —— 见 `explore_loop.py`
        `for _p in _plan: … if len(_picked) >= 4: break`）⇒ **它天然看不到第 5 步** ✗
        而**完整计划**在 `solver` 事件里（`{'solver':'ok','cost':…,'steps':…,'order':[…]}`，
        `max_steps=10` 的那一份，含出生点已被隐去后的全序 ✓）。

        ⇒ 本属性**优先 `solver` 事件**；它没有可用 `order` 时**退回 `plan`**（round 口径）✓
        ⚠ `plan` 的语义**不动**（另有只测它的回归），这里只是**多给一个更全的口径**。
        """
        ls = self.last_solver
        if isinstance(ls, dict) and ls.get('solver') == 'ok':
            o = ls.get('order')
            if isinstance(o, (list, tuple)) and o:
                cost = _first_num(ls.get('cost'))
                steps = ls.get('steps')
                try:
                    steps = int(steps) if steps is not None else len(o)
                except (TypeError, ValueError):
                    steps = len(o)
                return {'order': [str(x) for x in o], 'steps': steps,
                        'cost': cost, 'src': 'solver'}
        p = self.plan
        p = dict(p or {})
        p['src'] = 'round' if p.get('order') else ''
        return p

    @property
    def mapname(self):
        """当前这张图的**图名**（尾部最后一条 `mapname` 事件里的值）；没有 ⇒ `''`

        用途：主窗口拿它 `spots.code_of(mapname)` 反解出 `Sxxxxx` 图码，
        再用 `spots.Board(code).footprint(sid)` 还原**多格地块的占格** ✓
        （`loop_log` 的 `board` 只给锚点格 ⇒ 不还原的话 2×2 地块只显示 1 格 ✗）
        """
        e = self._last_with('mapname')
        if e is None:
            return ''
        v = e.get('mapname')
        return str(v) if isinstance(v, str) else ''

    # ---- 排查用 ----
    @property
    def last_error(self):
        """最近一次 poll 的出错原因；`''` = 没出错"""
        return self._last_error

    @property
    def mtime(self):
        return self._mtime

    @property
    def path(self):
        return self._path

    @property
    def max_events(self):
        return self._max

    @property
    def total_events(self):
        """文件里的事件总数（截尾前）—— 排查"是不是被截了"用"""
        return self._total

    @property
    def poll_n(self):
        """`poll()` 被调次数（排查用）"""
        return self._poll_n

    @property
    def read_n(self):
        """**真正落盘解析**的次数（mtime/size 命中的轮次不涨 ⇒ 这就是"mtime 感知"的证据 ✓）"""
        return self._read_n

    def by_key(self, key, limit=20):
        """尾部**含某键**的事件（排查用）→ list（按时间正序，最多 `limit` 条）"""
        try:
            n = max(0, int(limit))
        except Exception:                               # noqa: BLE001
            n = 20
        if n <= 0:
            return []
        return [e for e in self._events if key in e][-n:]


# ───────────────────────── 三种锁（只读） ─────────────────────────

class LockState:
    """三种锁的只读封装（路径与现 `bot_gui.py` / `explore_loop.py` **逐字一致**）：

    | 锁 | 路径 | 谁写 |
    |---|---|---|
    | 循环锁（占用判定） | `<runs>/.loop_<port>.lock` | `explore_loop.device_lock_path()` / `loopguard` |
    | 停脚本保现场锁 | `<runs>/red_equip_<port>.lock.json` | `explore_loop.red_lock_path()`（`kind` 分派） |
    | 本窗口单例锁 | `<runs>/<tag or 'default'>/.gui.lock` | `bot_gui.py`（纯 PID 文本） |

    ⚠ 三个路径**不同目录**：前两个在 `runs/` 根，`.gui.lock` 在 `runs/<tag|default>/`
      —— 现 UI 为这个差异**修过一次路径 bug**（`bot_gui.py:421`），别改回去 ✗

    ⚠ `red_equip_<port>.lock.json` 是**多种锁共用**一个文件，靠 `kind` 区分
      （`red_equip` / 旧版 `shrine` / `mimic2`）；读不到 `kind` ⇒ 一律按 `'red_equip'` ✓
    """

    def __init__(self, runs_dir, device='127.0.0.1:16384', tag=''):
        self._runs = str(runs_dir)
        self.device = str(device or '')
        self.tag = str(tag or '')
        self._last_error = ''

    # ---- 路径（拼接方式与既有代码逐字一致） ----
    def port(self):
        """设备端口（`'127.0.0.1:16416'` → 16416）；拿不到 ⇒ 0（与现 UI 同口径）"""
        try:
            return int(str(self.device).split(':')[-1])
        except Exception:                               # noqa: BLE001
            return 0

    def loop_lock_path(self):
        return os.path.join(self._runs, '.loop_%d.lock' % self.port())

    def red_lock_path(self):
        return os.path.join(self._runs, 'red_equip_%d.lock.json' % self.port())

    def gui_lock_path(self):
        return os.path.join(self._runs, self.tag or 'default', '.gui.lock')

    # ---- 读 ----
    def _lock_dict(self, path, what):
        """→ None=文件不存在（没锁）；{}=文件在但坏（**按"锁着"处理**，见 `loop_lock` 注释）"""
        if not os.path.exists(path):
            return None
        ok, obj, err = _read_json_file(path)
        if not ok:
            self._last_error = '%s：%s' % (what, err)
            return {}
        self._last_error = ''
        return obj if isinstance(obj, dict) else {}

    def loop_lock(self):
        """→ dict | None。

        ⚠ 坏文件返回 `{}`（**不是 None**）⇒ `is_running()` 会判"占用中"：
          这个文件**在**就说明有人写过循环锁；宁可显示"运行中/待确认"，
          也别让 UI 放行第二次启动（那会**两个进程抢同一个模拟器** ✗）——
          与 `loopguard` 的保守口径一致 ✓
        """
        return self._lock_dict(self.loop_lock_path(), '循环锁')

    def red_lock(self):
        """→ dict | None（**文件在但坏 ⇒ `{}`**，UI 照样提示"待处理·解锁" ✓）"""
        return self._lock_dict(self.red_lock_path(), '停脚本锁')

    def red_lock_kind(self):
        """`{device,kind,map,cell,round,at,shot}` 里的 `kind`；读不到 ⇒ `'red_equip'`"""
        d = self.red_lock()
        if not isinstance(d, dict):
            return 'red_equip'
        return str(d.get('kind') or 'red_equip')

    def gui_lock_pid(self):
        """`<tag|default>/.gui.lock` 里的 PID → int | None（文件不在/不是数字 ⇒ None）"""
        p = self.gui_lock_path()
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding='utf-8-sig') as f:
                txt = f.read().strip()
        except Exception as e:                          # noqa: BLE001  权限/是目录…
            self._last_error = '单例锁读取失败：%r' % (e,)
            return None
        if not txt:
            self._last_error = '单例锁是空文件'
            return None
        try:
            return int(txt)
        except Exception:                               # noqa: BLE001
            self._last_error = '单例锁不是纯 PID：%r' % (txt[:32],)
            return None

    def is_running(self):
        """循环锁文件在 ⇒ True（引擎正在跑 / 至少有人写过锁）"""
        return self.loop_lock() is not None

    @property
    def last_error(self):
        return self._last_error


# ───────────────────────── 热更状态（只读封装，不重写） ─────────────────────────

class HotState:
    """`hot/state.json` 只读封装 —— **只做委托与兜底，绝不重写 `hotupdate` 的逻辑** ✓

    `hotupdate` 里的**真实** API（2026-10-11 逐字核实）::

        load_state()    -> read_json(state_path())            # dict | {} | None（缺失/坏文件）
        status_line()   -> '包 v1.0 · 补丁=…（已确认/待确认） · 包目录=…'（自带 try，失败给文案）
        pkg_dir()       -> os.environ.get('MGAS_PC_PKG_DIR') or HERE   # HERE = mapbot_pc/
        state_path()    -> <pkg_dir>/hot/state.json

    ⚠ `load_state()` 可能返回 **None**（`read_json` 的默认值）⇒ 本层统一成 `{}` ✓
    ⚠ 热更不存在（`hot/` 目录都没有）⇒ 出厂版：`status_line()` = '出厂版·从未热更'，
      `title_suffix()` = '· 出厂版' ✓
    """

    def __init__(self, pkg_dir=None):
        self._pkg = os.path.abspath(str(pkg_dir)) if pkg_dir else PKG_DIR
        self._delegate = (os.path.abspath(self._pkg) == os.path.abspath(PKG_DIR))
        self._last_error = ''

    # ---- 内部 ----
    def _mod(self):
        """惰性 import `hotupdate`（同目录兄弟模块）；失败 ⇒ None（**不许抛**）"""
        try:
            import hotupdate
            return hotupdate
        except Exception as e:                          # noqa: BLE001
            self._last_error = 'import hotupdate 失败：%r' % (e,)
            return None

    def _read_local(self):
        """`<pkg>/hot/state.json` 的容错读（只在 `pkg_dir` 被显式指到别处时用）"""
        ok, obj, err = _read_json_file(os.path.join(self._pkg, 'hot', 'state.json'))
        if not ok:
            self._last_error = err
            return {}
        if isinstance(obj, dict):
            self._last_error = ''
            return obj
        self._last_error = 'state.json 顶层不是 dict（实际 %s）' % type(obj).__name__
        return {}

    # ---- 契约 ----
    def load(self):
        """→ dict。委托 `hotupdate.load_state()`；import 失败/异常/返回 None ⇒ `{}`（**不抛**）。

        ⚠ `pkg_dir` 被显式指到**别的目录**时不能盲委托（`hotupdate` 的路径由
          `MGAS_PC_PKG_DIR`/`HERE` 决定，会读到**真包**去）⇒ 这时本层自己容错读那份
          `hot/state.json`（只读，不碰 `hotupdate`）✓
        """
        m = self._mod()
        if m is None or not self._delegate:
            return self._read_local()
        try:
            st = m.load_state()
        except Exception as e:                          # noqa: BLE001
            self._last_error = 'hotupdate.load_state() 异常：%r' % (e,)
            return self._read_local()
        if isinstance(st, dict):
            self._last_error = ''
            return st
        self._last_error = 'hotupdate.load_state() 返回 %s（按空处理）' % type(st).__name__
        return {}

    def status_line(self):
        """→ 一句话状态。**委托** `hotupdate.status_line()`；失败 ⇒ `'出厂版·从未热更'`"""
        m = self._mod()
        if m is None:
            return '出厂版·从未热更'
        try:
            s = m.status_line()
        except Exception as e:                          # noqa: BLE001
            self._last_error = 'hotupdate.status_line() 异常：%r' % (e,)
            return '出厂版·从未热更'
        return s if isinstance(s, str) and s.strip() else '出厂版·从未热更'

    def applied(self):
        """当前生效的补丁 id（`hot-pc-<版本>-<sha8>`）；没有 ⇒ `''`"""
        v = self.load().get('applied')
        return v.strip() if isinstance(v, str) else ''

    def title_suffix(self):
        """窗口标题后缀（契约，**只读**）::

            ''                            # 没有补丁（绝大多数用户就是这个）
            '· 补丁 <id后缀>'              # 已确认
            '· 补丁 <id后缀>（待确认）'      # 覆盖了但界面还没跑到确认点

        ⚠ 为什么"没补丁"时返回**空串**（而不是以前的 `'· 出厂版'`）：
          这个后缀原本是给**开发者自己做热更排查**用的。
          普通用户从没热更过、也永远不会关心这个字段
          ⇒ 窗口标题挂「出厂版」只会让人误以为"我这版是不是残缺的" ✗
          真有补丁时仍会显示 `· 补丁 xxx`（排查能力不变 ✓）

        ⚠ 「id后缀」= `hot-pc-1.0-boot0001` 的最后一段 `boot0001`
          （id 由 `tools/release_pc.py:335` 拼成 `'hot-pc-%s-%s' % (ver, sha[:8])` ✓）
        """
        st = self.load()
        v = st.get('applied')
        hid = v.strip() if isinstance(v, str) else ''
        if not hid:
            return ''
        sfx = hid.rsplit('-', 1)[-1] if '-' in hid else hid
        return '· 补丁 %s%s' % (sfx, '' if st.get('confirmed') else '（待确认）')

    @property
    def pkg_dir(self):
        return self._pkg

    @property
    def last_error(self):
        return self._last_error
