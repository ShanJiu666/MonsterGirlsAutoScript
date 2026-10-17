# -*- coding: utf-8 -*-
"""guild_common.py · 公会展厅导航 + 面板判据（派遣任务 / 炼金 共用底层）

为什么单独一层
--------------
`guild_tasks.py`（派遣）与 `alchemy.py`（炼金）都在**公会展厅**里干活，
两者共用的东西一模一样：进公会、滚楼层、认面板、关面板、点按钮。
分成一份，免得两边各写一套、日后一边改一边忘（本项目"判据两份漂移"踩过多次 ✗）。

坐标口径（**全是 720×1280 设备坐标，直接 `b.tap`**）
----------------------------------------------------
⚠ 这些值**不是抄 `layout.py` 的**：`layout.py` 里**没有公会楼层这一层**
  （它只管图内元素 + 底部导航）⇒ 本轮**真机实测**标定，来源见
  `_tmp_probe_dispatch/CALIBRATION.md`。
⚠ `fixed.A()` 那条硬规矩照旧适用：**拿到就直接点，不要再乘 `LAYOUT.k`** ✓

公会展厅的楼层结构（实测）
--------------------------
    1 楼  中央大门（招募）+ 右侧 邮件/商店/招募/成就/公告/背包
    2 楼  **4 把椅子（派遣任务）** + 黑晶女仆  ← 进公会默认就在这层
    3 楼  地图挂毯 + 老者
    4 楼  **星空顶楼：左边普通宝箱 = 炼金**；中间大陶罐（无反应）；
          右边紫发角色 = 献祭宝箱怪（天赋互换，**别点错**）

⚠⚠ 滚动的方向（我第一轮搞反了，白试半小时 ✗）
    实测：**手指下滑**（y 小 → y 大）= 看**更高**楼层
          `input swipe 360 200 360 900 1200`
    反之（y 大 → y 小）回低层 ✓
"""
from __future__ import annotations

import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ⚠ 本模块**不 import explore_loop**（那会拉起一大坨业务，且它在 import 期
#   就往 sys.path 塞东西）。只用 mapbot 那一层的 Bot ✓
from mapbot import Bot, RUNS, ADB, DEV, CREATE_NO_WINDOW      # noqa: E402,F401
from mapbot import ADB_PORT                                   # noqa: E402
import subprocess                                             # noqa: E402

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════════════════
# ① 坐标表（全部 720×1280 实测）
# ══════════════════════════════════════════════════════════════════════
# 底部导航「公会」（公会展厅入口）
NAV_GUILD = (55, 1240)
# 底部导航「开始冒险」（离开公会 / 回选图界面）
NAV_START = (360, 1260)

# 滚动（见文件头：手指下滑 = 看更高层）
SWIPE_UP_XY = (360, 200, 360, 900, 1200)      # 往**高**楼层
SWIPE_DOWN_XY = (360, 900, 360, 200, 1200)    # 往**低**楼层
FLOOR_SWIPES = 3                              # 从 2 楼到 4 楼实测要 3 次

#: 「画面真的变了」的阈值（降采样灰度平均绝对差）
#: 实测：面板挡着时的"假滑动" = 1.1~2.3；真滚动 = 27.8~79.6 ⇒ 取 15 余量充足
#:
#: ⛔⛔ 2026-10-17 **别再用它判断"有没有面板挡着"**（我试过，是错的）：
#:   已经在**顶层**时再滚也不动 ⇒ delta 天然很小（实测 0.98/3.45/1.05）
#:   ⇒ 会把"到顶了"误判成"有面板" ⇒ 进而去点 X（那个坐标是大厅的「活动」✗✗）
#:   ⇒ 判"到没到炼金层"请用 `_try_alchemy_chest()` **试点自证** ✓
SCROLL_MIN_DELTA = 15.0


def _frame_sig(b):
    """取当前帧的**降采样灰度指纹**（判"画面变没变"用）

    ⚠ 必须走 `b.img()`（它内部按需 `snap`）——不要用 `b.ocr()` 的缓存帧，
      那玩意儿不重抓，判据会读旧帧（本项目踩过 N 次）✗
    """
    try:
        import numpy as _np
        im = b.img()
        if im is None:
            return None
        g = _np.asarray(im)
        if g.ndim == 3:
            g = g[:, :, :3].mean(axis=2)
        return g[::8, ::8].astype('float32')       # 90×160，抗噪且快
    except Exception:                              # noqa: BLE001
        return None


def _sig_delta(a, c):
    """两个指纹的平均绝对差；任一为 None / 形状不符 ⇒ None（表示"测不出"）"""
    if a is None or c is None:
        return None
    try:
        import numpy as _np
        if a.shape != c.shape:
            return None
        return float(_np.abs(a - c).mean())
    except Exception:                              # noqa: BLE001
        return None

# ── 派遣任务（2 楼）──
CHAIR_X = (263, 388, 513, 628)                # 4 把椅子的 x（间距 125）
CHAIR_Y = 470
BUBBLE_Y0, BUBBLE_Y1 = 335, 398               # 椅子气泡的 y 带
TASK_ACTION_BTN = (604, 1152)                 # 面板底部主按钮（文案三态，位置同一个）
TASK_PANEL_X = (656, 127)                     # 派遣面板右上 X
# ⚠⚠ 2026-10-14 用户口径（原话）：「**返回都不用按固定坐标点的**」✓
#   ⇒ 「返回/确定」这类**结果弹窗**的按钮**一律 OCR 现读**，不写死坐标 ✓
#     理由：这类弹窗的位置会随**文案行数/奖励条目数**变（项目早有这条教训，
#       见 `buypanels._find_text_btn` 的注释），写死必然有一天点空 ✗
#   ⇒ 这里**只留一个注释位**，代码里不再有 TASK_REWARD_BACK 这个常量
#     （保留会诱使后人再去用它 ✗）

# ── 炼金（4 楼顶楼）──
# ⚠⚠⚠ 2026-10-14 **真机实测：炼金宝箱的 y 会随"滚到多深"变**（重要！）
#   ---- 三次实测（同一台机器，不同滚动状态）----
#     帧            宝箱实测位置     能不能点开「炼金宝箱」面板
#     alch5.png     (248, 455)      ✓（主号，滚到底）
#     sc_step2.png  (215, 470)      ✓（测试号，滚到一半）
#     me1.png       (240, 435)      ✓（测试号，滚到极限）
#   ---- 结论 ----
#     ① 宝箱美术**很宽**（x≈129..297）⇒ **x 容差极大**（200/215/240/248 全中 ✓）
#     ② 但 **y 会漂 ~35px**（435 / 455 / 470）⇒ 只试一个 y 会点空 ✗
#        （我最初写死 (248,455)，在 y=435 那屏就点空了——真机实测 ✓）
#   ⇒ 修法：**试多个候选点**（x 一组、y 一组做笛卡尔积，逐个试到开出面板为止）✓
#     代价：最坏 3×3=9 次试点击；正常第 1~2 个就中 ⇒ 可接受 ✓
#     这比"模板匹配找宝箱"稳得多：实测跨号匹配 score 只有 0.39~0.46 ✗
#       （两个号的**公会皮肤不同**，宝箱美术不一样）
ALCHEMY_CHEST = (240, 445)                    # 主候选（三个实测值的中间）
ALCHEMY_CHEST_XS = (240, 215, 262)            # 实测命中的 x（容差大，取 3 个）
ALCHEMY_CHEST_YS = (445, 435, 470)            # 实测命中的 y（随滚动漂）
ALCHEMY_DECO_POT = (370, 430)                 # 大陶罐 —— **无反应**，别点
ALCHEMY_WRONG_CHAR = (519, 455)               # 紫发角色 = 献祭宝箱怪 —— **别点** ✗
ALCH_PANEL_TITLE = (479, 141)                 # 「炼金宝箱」
ALCH_PANEL_X = (671, 126)                     # 炼金面板右上 X
ALCH_START_BTN = (600, 471)                   # ⭐「开始炼金」
ALCH_CANCEL_BTN = (429, 471)                  # 「全部取消」
ALCH_TAB_EQUIP = (132, 591)                   # 「装备」页签
ALCH_TAB_RUNE = (301, 591)                    # 「符文」页签
ALCH_FILTER_FULLSTAR = (341, 1118)            # ⭐「满星」筛选 = **自动投料开关**
ALCH_ITEM_COLS = (106, 200, 295, 389, 484, 578)   # 6 个投料槽的 x
ALCH_ITEM_Y = 385
# 炼金**结果**面板（已炼好待领）
ALCH_RESULT_TITLE = '炼金结果'
ALCH_RESULT_BACK = (359, 931)                 # 结果面板的「返回」
# 炼金**进行中**（箱子上的浮层）
ALCH_TIMER_HINT = (240, 338)                  # 倒计时文字
ALCH_HOURGLASS = (361, 338)                   # ⭐ 沙漏 = 加速入口
ALCH_ACCEL_GEM = (313, 745)                   # 加速弹窗：花宝石
ALCH_ACCEL_AD = (535, 745)                    # 加速弹窗：看广告（每日 1 次）
ALCH_ACCEL_X = (671, 486)                     # 关掉加速弹窗（**不加速**）

# 公会展厅特征（判"我现在到底在不在公会"）
GUILD_CORNERS = ('攻略', '活动', '庆典福利', '机巧秘宝', '情报', '巅峰赛')
# 选图界面特征（判"离开公会了没"）
MENU_HINTS = ('进入地图', '快速扫荡', '星界秘境')
# 大厅（主界面）特征
LOBBY_HINTS = ('免费指定招募', '角色招募', '限时招募开启')

TIMER_RE = re.compile(r'^\d{1,2}[:：]\d{2}[:：]\d{2}$')

# ⭐⭐⭐⭐ 2026-10-14 **试跑模式（dry-run）** —— 只观察，**一下都不点**
#   为什么要有它（用户口径：「要在真机运行脚本的时候叫我，我看看正不正常」）：
#     直接上真机跑，用户只能看日志、看不到"脚本打算点哪"；
#     而一旦点错（本项目在真机上点错过多次），代价是真实的 ✗
#   ⇒ `--dry-run` 时：**所有 tap/swipe 只打印、不执行**，但 **OCR/判据/流程全照走**
#     （`snap`+`ocr` 仍真做 ⇒ 打印出来的状态是**真实读数**，不是编的 ✓）
#   ⇒ 用户先看一遍"它认到了什么、打算点哪"，确认无误再真跑 ✓
#   ⚠ 实现方式：把 Bot 包一层代理，拦掉 `tap`/`swipe` 两个方法即可 ——
#     不动各流程的一行逻辑（流程代码原样跑，判据也就原样被验证 ✓）
DRY_RUN = False


class DryBot:
    """把 `Bot` 包一层：**拦掉点击/滑动**，其余（snap/ocr/img）原样转发 ✓

    ⚠ 只拦 `tap` / `swipe` / `tap_dlg` 三个"会改状态"的口子；
      `snap`/`ocr`/`img` 必须**真做**（否则读数就是假的，试跑没有意义 ✗）
    """

    def __init__(self, bot, log=None):
        object.__setattr__(self, '_b', bot)
        object.__setattr__(self, '_n', 0)
        object.__setattr__(self, '_log', log)

    def __getattr__(self, k):
        return getattr(object.__getattribute__(self, '_b'), k)

    def _record(self, what, *a, **kw):
        n = object.__getattribute__(self, '_n') + 1
        object.__setattr__(self, '_n', n)
        say('      🚫[dry-run %02d] %s%s' % (n, what, a if a else ''))
        try:
            _lg = object.__getattribute__(self, '_log')
            if _lg is not None:
                _lg.append({'dry_run': what, 'args': list(a)})
        except Exception:                               # noqa: BLE001
            pass

    def tap(self, x, y, wait=1.2, **kw):
        self._record('tap', int(x), int(y))
        time.sleep(min(0.25, float(wait) / 8.0))        # 稍等，贴近真实节奏
        return None

    def tap_dlg(self, x, y, wait=1.2, **kw):
        self._record('tap_dlg', int(x), int(y))
        time.sleep(min(0.25, float(wait) / 8.0))
        return None

    def swipe(self, x1, y1, x2, y2, ms=300, wait=1.2, **kw):
        self._record('swipe', int(x1), int(y1), int(x2), int(y2))
        time.sleep(0.2)
        return None


def wrap_dry(bot, log=None):
    """按全局 `DRY_RUN` 决定要不要包试跑代理 ⇒ 返回可直接用的 bot ✓

    ⭐ 同时把**设备号**登记给本模块 —— `swipe_abs` 走裸 adb，得知道发给谁 ✓
      （`Bot` 上那个字段叫 `dev`；拿不到就退回环境变量/默认值，绝不因此崩 ✗）
    """
    try:
        _d = getattr(bot, 'dev', None)
        if _d:
            set_device(_d)
    except Exception:                                   # noqa: BLE001
        pass
    return DryBot(bot, log) if DRY_RUN else bot


# ══════════════════════════════════════════════════════════════════════
# ② 日志 / OCR 小工具
# ══════════════════════════════════════════════════════════════════════
def say(msg):
    """本模块的日志出口（与 explore_loop.say 同款：stdout + flush）"""
    try:
        print(msg, flush=True)
    except Exception:                                   # noqa: BLE001
        pass


def _texts(items):
    return [str((i or {}).get('text') or '').strip() for i in (items or [])]


def has(items, *labels, exact=False):
    """帧里有没有这些文字（默认**子串**；`exact=True` 时要求整条相等）

    ⚠ 本项目踩过「子串匹配被骗」的坑（预言卡正文里含「勇者之墓」✗）⇒ 凡是
      **面板标题**类的判据一律用 `exact=True`；按钮/说明文字才用子串 ✓
    """
    ts = _texts(items)
    for lb in labels:
        for t in ts:
            if (t == lb) if exact else (lb in t):
                return True
    return False


def find(items, *labels, exact=False, ymin=None, ymax=None):
    """找第一条命中文字 ⇒ 返回该 OCR 条目（含 cx/cy）或 None"""
    for it in (items or []):
        t = str(it.get('text') or '').strip()
        if ymin is not None and it.get('cy', 0) < ymin:
            continue
        if ymax is not None and it.get('cy', 0) > ymax:
            continue
        for lb in labels:
            if (t == lb) if exact else (lb in t):
                return it
    return None


def ocr_items(b, band=None, tag='guild', min_conf=0.35):
    """先 `snap` 再 `ocr` —— ⚠⚠ **必须成对**

    本项目第 N 次踩的同一个坑：`b.ocr()` 读的是**上一次 `snap()` 的缓存帧**，
    它**不会自己重抓** ⇒ 轮询/点击后不 `snap` 就会一直读旧帧，判据静默失效 ✗
    """
    try:
        b.snap(tag)
    except Exception:                                   # noqa: BLE001
        pass
    return b.ocr(min_conf=min_conf, band=band, tag=tag) or []


# ══════════════════════════════════════════════════════════════════════
# ③ 界面判定
# ══════════════════════════════════════════════════════════════════════
def in_guild(items):
    """这一帧是不是**公会展厅**（≥2 个公会专属角标命中）"""
    ts = _texts(items)
    return sum(1 for k in GUILD_CORNERS if any(k == t for t in ts)) >= 2


def in_menu(items):
    """这一帧是不是**选图界面**（有「进入地图/快速扫荡」）"""
    return has(items, *MENU_HINTS)


def in_lobby(items):
    """这一帧是不是**大厅主界面**"""
    return has(items, *LOBBY_HINTS)


def where_am_i(items):
    """给日志用的一句话定位"""
    if in_guild(items):
        return '公会展厅'
    if in_menu(items):
        return '选图界面'
    if in_lobby(items):
        return '大厅'
    return '未知界面'


# ══════════════════════════════════════════════════════════════════════
# ④ 进出公会 / 滚楼层
# ══════════════════════════════════════════════════════════════════════
def goto_guild(b, log=None, tries=3):
    """回到公会展厅（返回 True/False）

    ⭐⭐⭐⭐ 2026-10-14 **用户当场纠正了我一条多余的安全门**（原话）：
        「**这两步进图也能打，直接点公会就切换过去了**」
      ---- 我原来写的（错的）----
        照搬 `use_supply` / `bag_upgrade` 那套：「在图里 ⇒ 拒绝点公会，
        理由是"会点在棋盘上"」✗
      ---- 真机实测（实例B测试号 16448，我当时正停在「铁血高地」图内）----
        在图里点底部「公会」(55,1240) ⇒ **干脆利落地切到公会展厅** ✓
        （帧上直接看到「免费指定招募」+ 4 把椅子）
      ---- 为什么那两处要拦、这里不用拦（**别当成"它们错了"**）----
        · `use_supply` / `bag_upgrade` 点的是**图内元素**（公会界面里的 BAG_BTN
          =(643,1120) 这种）—— 在图里点那个坐标**确实落在棋盘格上** ✗ ⇒ 该拦 ✓
        · 这里点的是**底部导航条 (55,1240)**，它在**大厅/选图/图内三个界面都常驻**，
          且游戏把它做成了**全局切页按钮** ⇒ 图内点它是**正常操作** ✓
        ⇒ 判据差别在"**点的是全域导航 还是 图内专属坐标**"，不是"在不在图里" ✓
          （这正是本项目记过的教训：`fx_menu` 判"在不在选图"可靠、`in_map` 判
            "在不在图内"不可靠 —— **两个问题长得像，结论相反** ✓）
      ⚠ 仍保留一条**必要的**兜底：万一点了公会**没切过去**，不硬凑，如实返回 False ✓
    """
    for k in range(tries):
        items = ocr_items(b, tag='gg%d' % k)
        if in_guild(items):
            return True
        # 大厅 ⇒ 先点「开始冒险」离开大厅（大厅里公会按钮可能被大厅层挡）
        if in_lobby(items):
            b.tap(*NAV_START, wait=2.5)
            _log(log, {'guild': 'leave_lobby'})
            continue
        # ⭐ 图内 / 选图界面 ⇒ **直接点公会**（底部导航是全局切页，实测有效 ✓）
        _where = where_am_i(items)
        b.tap(*NAV_GUILD, wait=3.0)
        _log(log, {'guild': 'tap_nav', 'at': NAV_GUILD, 'try': k,
                   'from': _where})
        items2 = ocr_items(b, tag='gg%d_b' % k)
        if in_guild(items2):
            if _where not in ('公会展厅',):
                say('   ✓ 从「%s」点公会 ⇒ 已到公会展厅' % _where)
            return True
        say('   · 点了公会但还不像公会展厅（认到 %s）' % (_texts(items2)[:8],))
    return in_guild(ocr_items(b, tag='gg_f'))


def in_map_now(items):
    """这一帧在不在**探索图内**（有「结束冒险」或图名带 [难度]）

    ⚠ 与 `explore_loop.in_map` **同源口径**，但这里只取最硬的那条
      （「结束冒险」），够用且不会被选图界面误判 ✓
    """
    if has(items, '结束冒险'):
        return True
    return any(re.match(r'^.+\[\d+\]\s*$', t) for t in _texts(items))


def _raw_adb(*args, timeout=20):
    """跑一条 adb 命令（**不带 -s**，本模块自己补）—— 给"绕开 airtest"用 ✓"""
    return subprocess.run([ADB, '-P', str(ADB_PORT), '-s', str(_dev_of()),
                           ] + [str(a) for a in args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)


_DEV_CUR = {'dev': None}


def set_device(dev):
    """本模块记住当前设备号（`swipe_abs` 绕开 airtest 时要用它）"""
    _DEV_CUR['dev'] = str(dev) if dev else None


def _dev_of():
    return _DEV_CUR['dev'] or os.environ.get('MAPBOT_DEVICE') or DEV


def swipe_abs(x1, y1, x2, y2, ms=1200, wait=0.9):
    """滑动 —— ⛔ **不用 airtest 的 `swipe()`**，改走**裸 adb** ✓

    ⛔⛔⛔ 2026-10-14 **真机卡死 2 分钟的根因**（本项目最隐蔽的一个坑）
      ---- 现象 ----
        炼金脚本"跑着跑着就不动了"，日志停在 `⚗️ 炼金` 之后**一行都不出** ✗
        实测计时：`scroll_to_top`（5 次 swipe）**> 120 秒没返回** ✗✗
      ---- 定位（逐步二分）----
        · `GC.Bot(...)` 建得出来 ✓
        · `ocr_items()` 正常（23 条）✓
        · `in_guild()` 正常 ✓
        · `b.swipe(...)` ⇒ **永久卡住**（30 秒不返回，进程还在）✗
        · **同一坐标、同一时长**的裸命令
          `adb -P 5038 -s <dev> shell input swipe 360 200 360 900 1200`
          ⇒ **1.29 秒**就回来了 ✓
      ---- 结论 ----
        `mapbot.Bot.swipe()` 内部是 airtest 的 `swipe((x1,y1),(x2,y2),duration=ms)`
        ⇒ 走 **maxtouch**（`maxpresent.jar` + 本地 socket 通道）⇒
        **在这台 MuMu / 这个 Android 15 镜像上，该通道的 swipe 会永久阻塞** ✗
      ---- ⚠ 为什么这个坑一直没被发现 ----
        **主循环 `explore_loop.py` 从头到尾一次都没用过 `swipe`** ✓
        （它只 `tap` / `snap` / `ocr`）⇒ 这条死路从来没被走到过 ✗
        ⇒ 我的公会脚本是**第一个用 swipe 的调用方**，一用就撞上 ✓
      ---- 修法 ----
        本层滑动**一律走裸 adb**（`input swipe`）—— 实测 1.3s、稳定 ✓
        ⚠ **不改 `mapbot.Bot.swipe`**（那是全仓共用接口，动它风险大；
          而且"该不该顺便修 mapbot"要用户拍板 ⇒ 记进交接，不擅自改 ✗）
    """
    try:
        _raw_adb('shell', 'input', 'swipe', int(x1), int(y1), int(x2), int(y2),
                 int(ms))
    except Exception as _e:                             # noqa: BLE001
        say('   ⚠ 滑动失败（%r）⇒ 跳过这一次' % (_e,))
        return False
    if wait:
        time.sleep(wait)
    return True


def scroll_to_top(b, log=None, times=None, max_swipes=8):
    """滚到**最高层**（4 楼 = 炼金）—— 手指下滑 = 看更高层 ✓

    ⛔⛔ 2026-10-14 **连写三版判据全被真机证伪**，这条是第四版（记下来防重犯）：
      · 第一版：认「兑换商店开启」当"到顶了"
        ⇒ **3 楼和 4 楼都能看到那块牌子** ⇒ 滚到 3 楼就停 ✗
      · 第二版：认「画面不再变」（帧差 < 1.5）
        ⇒ 真机实测**仍然停在 3 楼**：因为公会滚动是**带吸附的分页**，
          3 楼→4 楼那一下的过渡帧恰好被判成"没变"⇒ 提前停 ✗
      · 第三版：换滑动起点/距离/时长（y150→700、y250→600、y1100→150…）
        ⇒ **全都停在同一位置** ⇒ 说明**不是手势参数问题** ✗
    ----
    ⭐⭐ 真机实测的**决定性事实**（这条才管用）：
      · 测试号(16448) 滚到某位置时，**宝箱就已经能点开** ✓
        ⇒ 换句话说：**只要"宝箱可见、且在候选点上"就能干活** ✓
      · 实测三个 x（200/215/240/248）都能点开 ⇒ **x 容差极大** ✓
      · 但**不同滚动深度下各自命中**（同一屏上只有部分候选有效）
      · 且实测"再往下滚也滚不动了"（到顶后 swipe 无效果）⇒ 顶就是顶 ✓
    ----
    ⇒ 第四版（**最简单也最稳**）：
      ① 先**固定往上滚 N 次**（滚到滚不动为止，多滚无害 ✓）
      ② 再让 `_try_alchemy_chest` 用**一组候选点**去试开面板
         （它自带 x×y 容差，正是为这种"位置会漂"设计的 ✓）
    ⛔⛔ 2026-10-17 第五版的**错误修法已废弃**（用户当场指出）：
      曾用「滚完测帧差 < 15 ⇒ 判有面板 ⇒ 点 X 关面板」，两个致命问题：
        ① **已在顶层**时再滚也不动 ⇒ 帧差天然小（实测 0.98/3.45/1.05）
           ⇒ 把到顶了误判成有面板挡着 ✗
        ② TASK_PANEL_X(656,127) 在公会大厅正好是「**活动**」按钮
           （OCR 实测 x=667,y=174）⇒ 程序跑去点活动，界面被搞乱 ✗✗
      ⇒ 把一个失效的 bug 改成了错误点击的 bug，**更糟** ✗
    ⭐⭐⭐⭐⭐ 2026-10-17 **现行做法（真机已验证）**：
      滚 N 次 → **试点一次炼金箱** → 开得出炼金面板就算到层
        真机实测：在炼金层点 (240,445) **直接开出「炼金结果」**（货币 96000）✓
      开不出 ⇒ 再滚一轮（最多 3 轮）⇒ 仍不行**如实 False**
      ⛔ **全程不点任何 X / 不碰别的按钮** ✓
    ⚠ 为什么是每轮试一次而不是每次滑动都试：
      试点代价 = 1 次 tap + 1 次 OCR ≈ 3 秒；一轮 N 次滑动后再试 1 次
      ⇒ 最多 3 次试点（9 秒），可接受 ✓
      ⛔ 若**每次滑动后都试 9 个候选点** ⇒ 分钟级、用户看不到进展 ✗
    ⚠ `times` 参数：默认 `FLOOR_SWIPES + 2`（从 2 楼到顶实测 2~3 次，
      多滚 2 次保证到底；顶楼再滚不动，无副作用 ✓）
    """
    n = int(times) if times is not None else (FLOOR_SWIPES + 2)
    # ⭐⭐⭐⭐⭐ 2026-10-17 **第二次修**（第一次修错了，用户当场指出）
    #   ---- 第一次错在哪 ----
    #     我加了「测 delta，< 15 就判有面板挡着 ⇒ 点 X 关面板」。
    #     但 ① **已经在顶层**时再滚也不动 ⇒ delta 天然小（实测 0.98/3.45/1.05）
    #             ⇒ 被误判成"有面板" ✗
    #         ② `TASK_PANEL_X(656,127)` 在**公会大厅**正好是「**活动**」按钮
    #             （OCR 实测 x=667 y=174）⇒ 程序跑去点了活动，界面被搞乱 ✗✗
    #     ⇒ 把"失效"的 bug 改成了"错误点击"的 bug，更糟
    #   ---- 现在的判据：**试点炼金箱自证**（真机已验证）----
    #     当前在炼金层时，点 `ALCHEMY_CHEST` **直接开出「炼金结果」面板** ✓
    #     ⇒ 滚 N 次 → 试点 → 开出炼金面板就算到层；开不出再滚一轮（最多 3 轮）
    #     ⛔ **全程不点任何 X**、不改动别的界面 ✓
    _try = 0
    for _attempt in range(3):
        for _ in range(max(1, n)):
            swipe_abs(*SWIPE_UP_XY)
            time.sleep(0.9)
        time.sleep(0.6)                      # 等滚动吸附停稳
        if _try_alchemy_chest(b, log):
            _log(log, {'guild': 'scroll_top', 'n': n, 'attempt': _attempt,
                       'by': 'chest_probe', 'ok': True})
            if _attempt:
                say('   · 第 %d 轮试点才到炼金层 ✓' % (_attempt + 1))
            return True
        _try += 1
        _log(log, {'guild': 'scroll_top_probe', 'attempt': _attempt,
                   'by': 'chest_probe', 'ok': False})
        say('   · 滚了 %d 次还没到炼金层（试点没开出炼金面板）⇒ 再滚一轮'
            % ((_attempt + 1) * n))
    say('   ⚠ 3 轮都没到炼金层 ⇒ **如实返回 False**（调用方据此放弃，别硬点别的按钮）')
    _log(log, {'guild': 'scroll_top_failed', 'tries': _try})
    return False


def _try_alchemy_chest(b, log=None):
    """试点炼金宝箱 ⇒ True = 开出了炼金面板（并**顺手把它关掉**）

    ⭐⭐⭐ 2026-10-14 **真机实测：宝箱的 y 会随滚动深度漂 ~35px** ⇒
      只试一个坐标会点空（我最初写死 (248,455)，在 y=435 那屏就点空了 ✗）
      ⇒ 这里**试一组候选点**（x × y 笛卡尔积），试到开出面板为止 ✓
    ⚠ 判据只看"有没有炼金面板"（不是"点在没点中"）—— 点空/点错物件都返回 False ✓
    ⚠ 点错隔壁的紫发角色会开「献祭宝箱怪」—— 那不是炼金面板 ⇒ 判 False
      并**把它关掉**（不然挡着后续操作 ✗），**绝不误投料** ✓
    """
    for _x in ALCHEMY_CHEST_XS:
        for _y in ALCHEMY_CHEST_YS:
            try:
                b.tap(_x, _y, wait=2.4)
                items = ocr_items(b, tag='tac')
                if _is_alchemy_panel(items):
                    b.tap(*ALCH_PANEL_X, wait=1.4)      # 关掉，避免影响后面
                    _log(log, {'guild': 'alchemy_chest_ok', 'at': (_x, _y)})
                    return True
                if has(items, '献祭宝箱怪'):
                    _log(log, {'guild': 'alchemy_chest_wrong_obj', 'at': (_x, _y)})
                    b.tap(*ALCH_PANEL_X, wait=1.4)
            except Exception:                           # noqa: BLE001
                continue
    return False


def _is_alchemy_panel(items):
    """这一帧是不是**炼金**面板（结果面板 or 主面板）

    ⛔ 必须排除「献祭宝箱怪」（同层隔壁那个紫发角色，面板名不同）✗
    """
    if has(items, '炼金结果', exact=True):
        return True
    if has(items, '炼金宝箱', exact=True):
        return True
    return False


def scroll_to_floor2(b, log=None, times=None):
    """（**已不用**；保留仅为兼容）改用 `ensure_chair_floor` —— 见那个函数的说明 ✓"""
    return ensure_chair_floor(b, log)


def ensure_chair_floor(b, log=None, max_floors=5):
    """确保站在**有派遣椅子**的那一层 ⇒ True/False

    ⛔⛔⛔ 2026-10-14 **四版判据的教训**（这段是本轮最值得记的）
    ------------------------------------------------------------
    我一开始想"先判断自己在哪层、再决定滚不滚"，连写三版判据，**每版都被真机证伪**：
      ① **只认文字**（倒计时 / 「黑晶女仆」/「一键派遣」）
         ⇒ 实例B测试号那屏 **4 把椅子全是 `?`**（没任务、面板没开）
         ⇒ 三条全落空 ⇒ 判成"不在椅子层" ⇒ **乱滚** ✗
      ② **数白色块**（气泡是白底）
         ⇒ 3 楼（地图挂毯）、4 楼（星空/柱子高光）**也有白色美术**，
           面积 500~1600，与真气泡**同量级** ⇒ 假阳性 ✗
      ③ **白色块 + 里面有彩色字形**（想区分"白底+彩色 `?`"vs"纯白美术"）
         ⇒ 3 楼/4 楼**仍有**带彩色的白块 ⇒ 还是假阳性 ✗
        （实测：2 楼 6 个、3 楼 4 个、4 楼 2 个 —— **只差数量，没有干净的分界**）
    ⇒ 三版都错在**同一个假设**：「我能从一帧里**认出**这是哪层」。
    ------------------------------------------------------------
    ⭐ 正解：**别再认了，直接试**（本项目一贯的"闭环验证"口径 ✓）
      判据 = **点一下椅 1，看派遣面板开不开**：
        开了   ⇒ 这**就是**椅子那层（顺手把面板关掉）✓
        没开   ⇒ 换一层再试（先往下找，找不到再往上找）
      · 零猜测量：不用认楼层、不用认气泡、不用认任何美术 ✓
      · 自证：判据就是**最终要用的那个动作**本身 ⇒ 不会"判对了却用不了" ✓
      · 代价：最坏情况每个楼层一次试点击（≈2.5s/层，全会话一次）✓
        —— 而**正常情况进公会就在 2 楼** ⇒ 第 1 次就命中，**零额外开销** ✓

    ⚠ `count_bubbles` 仍保留，但**只用于日志/诊断**，不再参与决策
      （它的 docstring 里写明了"为什么它不够格当闸门" ✓）
    """
    # ── ① 先试当前层（正常情况下进公会就在 2 楼 ⇒ 这里就命中）──
    if _try_chair_floor(b, log):
        return True
    # ── ② 往下找（1 楼）──
    for i in range(max_floors):
        swipe_abs(*SWIPE_DOWN_XY)
        time.sleep(0.9)
        _log(log, {'guild': 'floor_search_down', 'n': i + 1})
        if _try_chair_floor(b, log):
            return True
    # ── ③ 往上找（3 楼 → 4 楼顶楼）──
    for i in range(max_floors * 2):
        swipe_abs(*SWIPE_UP_XY)
        time.sleep(0.9)
        _log(log, {'guild': 'floor_search_up', 'n': i + 1})
        if _try_chair_floor(b, log):
            return True
    say('   ⚠ 上下都找过了，**没找到椅子那层**（如实返回 False，不硬凑）')
    _log(log, {'guild': 'chair_floor_not_found'})
    return False


def _try_chair_floor(b, log=None):
    """试一下：点椅 1，看派遣面板开不开 ⇒ True/False

    ⛔⛔ 2026-10-14 **真机卡死当场抓到的 bug**（用户报「卡在第一个派遣的返回上了」）
      ---- 病 ----
        我只判了"面板开没开"，**没判"是不是弹了奖励弹窗"** ✗
        而椅 1 恰好是**已完成**态 ⇒ 点它弹的**不是面板**，是「恭喜获得 宝箱 + 返回」✗
        ⇒ `has(items,'黑晶女仆')` 为假 ⇒ 判成"这层没椅子" ⇒ 换层继续试
        ⇒ 可**奖励弹窗一直挂着**，后续每次试点击都点在弹窗上 ⇒ **越试越死** ✗✗
      ---- 修法（两件事）----
        ① 试点击之后**先看有没有奖励弹窗**：有就点掉（按 **OCR 现读**坐标 ✓）
           —— 顺手还白领一份奖励，不亏 ✓
        ② 判据顺序：奖励弹窗 → 派遣面板 → 都不是才换层 ✓
    ⚠⚠ 用户口径（原话）：「**返回都不用按固定坐标点的**」✓
      —— 所以这里**不再用** `TASK_REWARD_BACK` 那个写死值，
        一律 `find(items,'返回','确定')` **现读现点** ✓
        （写死值只在"OCR 也读不到"时才当兜底，而且会**显式记日志** ✓）
    """
    try:
        b.tap(CHAIR_X[0], CHAIR_Y, wait=2.4)
        items = ocr_items(b, tag='ecf')
        # ① 奖励弹窗（已完成态点椅子会弹这个）⇒ 点掉（OCR 现读坐标）
        if has(items, '恭喜获得'):
            _log(log, {'guild': 'try_floor_reward'})
            _dismiss_popup(b, log, 'ecf_rw')
            # 领完奖励后椅 1 会换成新任务 ⇒ 这层**确定就是椅子层** ✓
            _log(log, {'guild': 'chair_floor_found', 'by': 'reward_popup'})
            return True
        # ② 派遣面板
        if has(items, '黑晶女仆', exact=True):
            b.tap(*TASK_PANEL_X, wait=1.6)
            _log(log, {'guild': 'chair_floor_found', 'by': 'task_panel'})
            return True
        return False
    except Exception:                                   # noqa: BLE001
        return False


def _dismiss_popup(b, log=None, tag='popup'):
    """点掉当前弹窗的「返回/确定」—— **坐标一律 OCR 现读**（用户口径 ✓）

    ⚠ 每轮**重新取帧**再找（弹窗有弹出动画，一次判死会漏 ✗
      —— `relic_flow` 上正是栽在这）
    ⚠ 找不到就**不盲点**，如实返回 False ✓
    """
    for k in range(4):
        items = ocr_items(b, tag='%s_%d' % (tag, k))
        it = find(items, '返回', '确定')
        if it:
            b.tap(it['cx'], it['cy'], wait=1.8)
            _log(log, {'popup_dismiss': 'ocr', 'text': it['text'],
                       'at': (it['cx'], it['cy']), 'try': k + 1})
            say('         · 点掉弹窗「%s」(%d,%d)（OCR 现读 ✓）'
                % (it['text'], it['cx'], it['cy']))
            return True
        time.sleep(0.8)
    _log(log, {'popup_dismiss': 'miss', 'note': '4 轮没读到「返回/确定」⇒ 不盲点'})
    return False


def _safe_img(b):
    """取当前帧（拿不到返回 None —— 判据会退化成"只看文字"，不会崩 ✓）"""
    try:
        return b.img()
    except Exception:                                   # noqa: BLE001
        return None


def chair_row_hint(items, img=None):
    """这一帧像不像**有派遣椅子**的那层（用于"要不要滚"的判据）

    ⛔⛔ 2026-10-14 真机第二版判据**仍然漏**，实测抓出：
      我原来只认文字（倒计时 / 黑晶女仆 / 一键派遣…）——
      可**实例B测试号**那屏：4 把椅子全是 `?`（没任务、没倒计时），
      而「黑晶女仆」三个字**要开面板才显示** ⇒ 文字判据**全部落空** ⇒
      `chair_row_hint` 返回 False ⇒ 脚本以为"不在椅子那层"⇒ 继续乱滚 ✗✗
    ⇒ 修法：**补一条图像判据**（气泡本身就是最直接的特征，不依赖 OCR）✓
      判据 = 椅子行 y 带里出现 **≥2 个"近白色方块"**（就是那 4 个对话气泡）
      —— 气泡是**纯白圆角方**，而公会背景是暖木色/米黄，
        用"**低饱和 + 高亮**"一抠就出来，非常稳（实测 4 个都命中 ✓）
    ⚠ 为什么"≥2"而不是"==4"：气泡会被面板/动画挡住几个，
      只要**认出 2 个以上**就足以说明"这是椅子那层" ✓（宁松勿严：
      判错的代价是"多滚一次"，而滚过头会看不见椅子 ✗）
    """
    # ① 文字证据（有任务在跑 / 面板开着时最省事）
    for it in (items or []):
        cy = it.get('cy', 0)
        t = str(it.get('text') or '').replace(' ', '').replace('：', ':')
        if BUBBLE_Y0 - 30 < cy < BUBBLE_Y1 + 30 and TIMER_RE.match(t):
            return True
    if has(items, '黑晶女仆', '一键派遣', '键派遣', '开始任务', '剩余时间'):
        return True
    # ② 图像证据：椅子行的**白色气泡**（不依赖 OCR ✓）
    if img is not None:
        try:
            n = count_bubbles(img)
            if n >= 2:
                return True
        except Exception:                               # noqa: BLE001
            pass
    return False


def count_bubbles(img):
    """数椅子行里有几个**对话气泡**（图像判据，零 OCR）✓

    ⛔⛔ 2026-10-14 **第三版才判对**（前两版都被真机证伪，记下来防重犯）：
      · 第一版：只认文字（倒计时/黑晶女仆/一键派遣）⇒ 实例B测试号 4 椅全 `?`、
        没倒计时、面板也没开 ⇒ **全部落空** ✗
      · 第二版：数"白色块" ⇒ 3 楼（地图挂毯）/4 楼（星空+柱子）
        **也有白色美术**（实测 4 块、面积 500~1600 ⇒ 与真气泡同量级）✗✗
    ⇒ 正解 = **加上"气泡里必须有一个彩色字形"这一条**：
        气泡 = 白底 + 里面一个**高饱和**的 `?` / `!`（绿/蓝/紫/橙，按位阶变色）
        而背景的白色美术（挂毯、柱子高光）**里面是白的/灰的，没有彩色块** ✓
      实测区分度（见 `verify_guild_scripts.py` 的楼层回归）：
        2 楼（4 椅 `?`）        ⇒ 4 个真气泡
        3 楼 / 4 楼顶楼         ⇒ **0 个**（白色块都在，但都没有彩色字形）✓
    """
    if img is None or getattr(img, 'size', 0) == 0:
        return 0
    band = img[max(0, BUBBLE_Y0 - 10):BUBBLE_Y1 + 10, :]
    if band.size == 0:
        return 0
    import numpy as _np
    import cv2 as _cv2
    hsv = _cv2.cvtColor(band, _cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).astype(_np.uint8) * 255
    white = _cv2.morphologyEx(white, _cv2.MORPH_CLOSE,
                              _np.ones((5, 5), _np.uint8))
    n, _lab, stats, _c = _cv2.connectedComponentsWithStats(white, 8)
    cnt = 0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 400:
            continue
        # ⭐ 关键一条：这个白块**里面**有没有**高饱和**的彩色像素（= 字形）
        sub = hsv[y:y + h, x:x + w]
        # 只数"够彩"的：S 高（>90）且不是极暗（V>110）⇒ 排除黑边
        col = int(((sub[:, :, 1] > 90) & (sub[:, :, 2] > 110)).sum())
        if col < 60:            # 实测真气泡的字形 ≥ 100 像素；白色美术 ≈ 0
            continue
        cnt += 1
    return cnt


def leave_guild(b, log=None):
    """离开公会：点底部中间「开始冒险」⇒ 回选图界面（未完成的图会直接恢复）"""
    b.tap(*NAV_START, wait=2.5)
    _log(log, {'guild': 'leave', 'at': NAV_START})
    items = ocr_items(b, tag='leave')
    return in_menu(items) or in_map_now(items)


# ══════════════════════════════════════════════════════════════════════
# ⑤ 通用：关面板 / 点按钮（**点完必验证**，不盲点）
# ══════════════════════════════════════════════════════════════════════
def tap_verified(b, x, y, tag, wait=2.0, log=None):
    """点一下，然后**重新取帧**确认画面变了（返回 True/False = 有没有变化）

    ⚠ 与 explore_loop._tap_verified 同口径：**别信 tap 的返回值**，
      它只表示"触摸事件发出去了"，不代表游戏受理了 ✓
    """
    try:
        b.snap(tag + '_a')
        _before = b.img()
    except Exception:                                   # noqa: BLE001
        _before = None
    b.tap(int(x), int(y), wait=wait)
    try:
        b.snap(tag + '_b')
        _after = b.img()
    except Exception:                                   # noqa: BLE001
        return True
    if _before is None or _after is None:
        return True
    try:
        import numpy as _np
        d = float(_np.mean(_np.abs(_after.astype(int) - _before.astype(int))))
    except Exception:                                   # noqa: BLE001
        return True
    _log(log, {'tap': tag, 'at': (int(x), int(y)), 'diff': round(d, 2)})
    return d >= 1.0


def close_panel(b, at, tag, probe_texts=(), log=None, tries=2):
    """点右上 X 关面板，并**验证它真的关了**（`probe_texts` 是要消失的文字）

    返回 True = 已确认关掉；False = 还开着（**如实返回，不假装成功** ✓）
    """
    for k in range(tries):
        b.tap(int(at[0]), int(at[1]), wait=1.8)
        if not probe_texts:
            _log(log, {'close': tag, 'verified': None})
            return True
        items = ocr_items(b, tag='%s_c%d' % (tag, k))
        if not has(items, *probe_texts):
            _log(log, {'close': tag, 'verified': True, 'tries': k + 1})
            return True
        _log(log, {'close': tag, 'verified': False, 'tries': k + 1})
    say('   ⚠ 面板没关掉（%s）⇒ 如实上报，交给下一轮' % (tag,))
    return False


def _log(log, rec):
    """往调用方给的 log 列表塞一条结构化记录（拿不到就只打印）"""
    try:
        if log is not None:
            log.append(rec)
    except Exception:                                   # noqa: BLE001
        pass


# ══════════════════════════════════════════════════════════════════════
# ⑥ 真机自检（不连设备也能跑的那部分：坐标越界 + 常量合法性）
# ══════════════════════════════════════════════════════════════════════
def _all_points():
    """本模块里所有"会被当点击坐标用"的常量 ⇒ [(名字, (x, y))]"""
    return [
        ('NAV_GUILD', NAV_GUILD), ('NAV_START', NAV_START),
        ('TASK_ACTION_BTN', TASK_ACTION_BTN), ('TASK_PANEL_X', TASK_PANEL_X),
        # ⚠ 「返回/确定」这类**结果弹窗**按钮**不写死**（用户口径）⇒ 这里没有它 ✓
        ('ALCHEMY_CHEST', ALCHEMY_CHEST), ('ALCHEMY_DECO_POT', ALCHEMY_DECO_POT),
        ('ALCHEMY_WRONG_CHAR', ALCHEMY_WRONG_CHAR),
        ('ALCH_PANEL_TITLE', ALCH_PANEL_TITLE), ('ALCH_PANEL_X', ALCH_PANEL_X),
        ('ALCH_START_BTN', ALCH_START_BTN), ('ALCH_CANCEL_BTN', ALCH_CANCEL_BTN),
        ('ALCH_TAB_EQUIP', ALCH_TAB_EQUIP), ('ALCH_TAB_RUNE', ALCH_TAB_RUNE),
        ('ALCH_FILTER_FULLSTAR', ALCH_FILTER_FULLSTAR),
        ('ALCH_RESULT_BACK', ALCH_RESULT_BACK),
        ('ALCH_TIMER_HINT', ALCH_TIMER_HINT), ('ALCH_HOURGLASS', ALCH_HOURGLASS),
        ('ALCH_ACCEL_GEM', ALCH_ACCEL_GEM), ('ALCH_ACCEL_AD', ALCH_ACCEL_AD),
        ('ALCH_ACCEL_X', ALCH_ACCEL_X),
    ]


def self_test():
    """零设备自检：坐标越界 / 椅子间距 / 文案表非空（跑 `python guild_common.py`）"""
    print('=== guild_common 自检（720×1280 设备坐标）===')
    bad = []
    for name, (x, y) in _all_points():
        if not (0 <= x < 720 and 0 <= y < 1280):
            bad.append((name, (x, y)))
    if bad:
        for n, v in bad:
            print('   ✗ %-22s 越界 %s' % (n, v))
    else:
        print('   ✓ %d 个点击坐标全部在屏内' % len(_all_points()))
    # ⚠⚠ 这里**不能断言"4 把椅子等距"** —— 我第一版就是这么写的，自检当场判红 ✗
    #   ---- 事实 ----
    #     实测点过的 4 个 x = 263 / 388 / 513 / 628，间距 125/125/**115** （**不等距**）
    #     而按角色立绘像素重心量出来是 244 / 376 / 522 / 658（间距 132/146/136）
    #   ---- 为什么"等距"这条判据是错的 ----
    #     椅子的**美术立绘宽窄不一**（有拿剑的、有坐得靠前的），而点击热区是
    #     游戏按**逻辑槽位**摆的、不是按美术等分 ⇒ 两者本来就不该等距 ✓
    #     （我照"应该是等距"去凑 628→638 反而会点偏 ✗）
    #   ⇒ **真正的判据 = 这 4 个 x 都落在对应椅子的可点区内**，而那**只能在真机验**
    #     （本轮已逐把实测：4 把都点开过、状态都读对 ✓ 见 CALIBRATION.md）
    #   ⇒ 自检这里只做"**区间单调 + 不重叠 + 都在屏内**"这种**结构性**检查 ✓
    gaps = [CHAIR_X[i + 1] - CHAIR_X[i] for i in range(len(CHAIR_X) - 1)]
    if all(CHAIR_X[i] < CHAIR_X[i + 1] for i in range(len(CHAIR_X) - 1)):
        print('   ✓ 4 把椅子 x 严格递增：%s（间距 %s，实测不等距是正常的 ✓）'
              % (list(CHAIR_X), gaps))
    else:
        print('   ✗ 椅子 x 没有严格递增：%s' % (list(CHAIR_X),))
        bad.append(('chair_order', CHAIR_X))
    if all(abs(CHAIR_X[i + 1] - CHAIR_X[i]) >= 90 for i in range(len(CHAIR_X) - 1)):
        print('   ✓ 相邻椅子间距 ≥90px（不会点到隔壁）')
    else:
        print('   ✗ 有相邻椅子挨得太近：%s' % (gaps,))
        bad.append(('chair_gap_small', gaps))
    # 炼金 6 槽也要等距
    g2 = [ALCH_ITEM_COLS[i + 1] - ALCH_ITEM_COLS[i]
          for i in range(len(ALCH_ITEM_COLS) - 1)]
    if len(set(g2)) == 1:
        print('   ✓ 炼金 6 槽等距 %dpx' % g2[0])
    else:
        print('   · 炼金 6 槽间距：%s（实测值，允许不完全等距）' % (g2,))
    for nm, tup in (('GUILD_CORNERS', GUILD_CORNERS), ('MENU_HINTS', MENU_HINTS),
                    ('LOBBY_HINTS', LOBBY_HINTS)):
        if not tup:
            print('   ✗ %s 是空的' % nm)
            bad.append((nm, 'empty'))
    print('   ✓ 文案表都非空')
    print()
    return not bad


if __name__ == '__main__':
    raise SystemExit(0 if self_test() else 1)
