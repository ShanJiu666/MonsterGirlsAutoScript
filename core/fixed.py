# -*- coding: utf-8 -*-
"""fixed.py · ⭐ PC 端「固定锚点 + 模板快查」层（2026-10-01，为速度而生）

为什么有这个
------------
PC 端已**锁定 720×1280**（不再追全分辨率）⇒ 游戏 UI 是**固定竖屏布局**，
所有"永远在同一个位置"的元素都可以**直接写死坐标**，根本不需要 OCR。

实测代价（720×1280，PC venv，warm 后）：
    全屏 OCR 1.2~1.6s ／ 条带 OCR 0.8~2.9s ／ 首次含引擎初始化 4.5s
    模板匹配（同区域）**< 5ms** ⇒ **快 200~300 倍**
⇒ 凡是"位置固定 + 长得固定"的，一律走这里；只有**内容会变**的东西才 OCR。

三类 API
--------
① **纯坐标**（`nav_bar()` / `btn_start_adv()` …）
   固定 UI 直接给 720×1280 像素坐标，连匹配都不用。
② **模板快查**（`find(FRAME, 'nav_battle')`）
   固定图标/按钮的**存在性判断**（"现在到底在不在这张图上"），
   比 OCR 快两个数量级，且不受字号/清晰度影响。
③ **必须 OCR 的**（不在本模块）
   读**会变的文字**：体力数字、倒计时、图名、道具名、价格……

坐标口径
--------
⚠ 本模块**只服务 PC 端 720×1280**。`layout.py` 那套 1080×1920 参考系是
**手机端**（RefMapper 归一化）在用的 —— 两端已平行独立开发（README §0），
所以这里**不复用** LAYOUT，直接按 720×1280 写死，避免"以为能复用其实会错"。

    参考系 1080×1920 → 720×1280 的换算：k = 720/1080 = 0.6667
      参考 (x, y) 里的棋盘锚点 y=1002 ⇒ 设备 y = 668
      ⇒ 与 `layout.py` 的 `sy()` 一致（720p 是纯等比缩放，无偏移 ✓）
"""
from __future__ import annotations

import os

import cv2
import numpy as np

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `templates/` `runs/` `data/` 这些资源都相对**仓根** ⇒ 必须多上一级。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TPL_DIR = os.path.join(_MGAS_ROOT, 'templates', 'fixed')

# ── 屏幕规格（PC 端锁定，别改）─────────────────────────────────────────
PC_W, PC_H = 720, 1280
REF_W, REF_H = 1080, 1920
K = PC_W / float(REF_W)          # 0.6667（720p 是 1080p 的纯等比缩放）

# 匹配阈值：模板都是固定 UI，同分辨率下分数很高；0.62 留足余量
MATCH_MIN = 0.62
# 未命中时返回 None（调用方决定要不要回退 OCR）
_cache: dict = {}


def _r(x, y):
    """参考系 1080×1920 → 720×1280 设备坐标"""
    return int(round(x * K)), int(round(y * K))


# ══════════════════════════════════════════════════════════════════════
# ① 纯坐标锚点（720×1280）—— 能写死的就写死，零开销
# ══════════════════════════════════════════════════════════════════════
# ⚠ 全部由 `layout.REF` 的参考值 ×0.6667 换算而来，改动请连参考值一起改。
# ⚠⚠ **底部导航条**是唯一一处「参考值」极容易搞错的地方：
#    实测 720p **设备系**导航条文字在 y≈1260（贴底），换回参考系是 1260/0.6667 = **1890**，
#    **不是 1260** ⚠（本文件第一版把设备实测值 1260 当参考值写进来，算出 840、离真实位置
#    差 400px，自检时才发现）。`layout.REF` 里没有这一组（它只管图内元素），
#    所以这里按实测反推并标注来源。
_ANCHORS_REF = {
    # 底部导航条（5 个 tab，永远在这一行）
    # 来源：720p 真帧 OCR 实测设备系 (x, 1260~1261) ⇒ 参考系 = 设备/0.6667
    'nav_guild': (81, 1890),      # 公会     设备(54, 1260)
    'nav_role': (204, 1890),      # 角色     设备(136,1260)
    'nav_start': (360, 1890),     # 开始冒险 设备(240,1260) ★ 中心 tab
    'nav_arena': (518, 1890),     # 斗技场   设备(345,1260)
    'nav_dex': (642, 1890),       # 图鉴     设备(428,1260)

    # 地图内（来自 layout.REF ✓ 已逐条与 LAYOUT.for_screen(720,1280) 对拍过）
    'end_adv': (539, 772),        # 结束冒险（面板内）    → 设备(359, 515)
    'start_adv_icon': (540, 1828),  # 开始冒险**图标**    → 设备(360,1219)
    #   ⚠ 点**图标**不是文字：文字 cy=1890，点 1889 会点空、1828 才生效（2026-09-28 修）
    'enter_map': (904, 1618),     # 选图界面「进入地图」  → 设备(603,1079)

    # 通用
    # ⚠ `close_x_right`(1024) 与 `close_bag`(984,191) 是**两个不同元素**：
    #     前者是通用面板右上角 X，后者是**背包**右上角关闭。抄表时别混（本文件第一版就混了）。
    'close_right': (1024, 191),   # 通用面板右上角 X     → 设备(683, 127)
    'close_bag': (984, 191),      # 背包右上角关闭        → 设备(656, 127)
    'close_left': (493, 225),     # 左上角 X              → 设备(329, 150)
    'back_btn': (539, 1212),      # 面板「返回」          → 设备(359, 808)
    # ⚠⚠ 2026-10-02 新增：**奖励类弹窗**的「返回」按钮。
    #   触发场景（用户 2026-09-25 / 09-26 定）：揭格出莱姆、打大拇指出装备、
    #   **退图前最后一次补点**（最常卡住的就是这个 —— 用户 2026-10-02 实测
    #   「模拟器卡在获得莱姆界面」，且日志显示盖住棋盘 ⇒ 认不到「结束冒险」
    #   ⇒ 走万能位盲点 ⇒ **跳到「图鉴」大页面** ✗✗）
    #   ⭐ **为什么要写死**（PC 端 §1b 提速约定）：
    #     写死坐标 **0ms**，OCR 一条带 **3.3~3.6s**；这两个弹窗在退图收尾必遇，
    #     每次都 OCR 一次纯属浪费 ⇒ 判据改成**模板/结构**，**不再靠 OCR 读「返回」二字**。
    #   ⚠ 坐标来源：用户 2026-09-25/26 实测（1080×1920 参考系）
    #       莱姆「返回」(539,1309)、新装备「返回」(540,1252)
    #     → 720×1280 设备系 (359,873) / (360,835)，两处都在屏内 ✓
    #   ⚠ 与 `back_btn`(539,1212) 是**不同的按钮**（y 差 ~100），
    #     抄表时别混 —— 这两个弹窗的返回比普通面板返回更靠下。
    'lime_back': (539, 1309),     # 「发现莱姆！」返回    → 设备(359, 873)
    'equip_back': (540, 1252),    # 「获得新装备！」返回  → 设备(360, 835)
    'bottom_close': (578, 1440),  # 结算面板底部「关闭」  → 设备(385, 960)
    'universal_close': (541, 1890),  # 万能兜底位          → 设备(361,1260)
    #   ⚠ 与 nav 行同一 y 带：它是「中间最下面」，在导航条**上方**，点它不切图
    #     （用户 2026-09-26 实测：那边点了非常安全、关完还在图里）

    # 战斗/派遣按钮
    'fight_normal': (806, 735),   # 普通格开打（右列）    → 设备(537, 490)
    'fight_boss': (541, 735),     # 首领格开打（居中）    → 设备(361, 490)
    'explore_btn': (275, 736),    # 探索                  → 设备(183, 491)
    'dispatch_btn': (891, 1507),  # 派遣                  → 设备(594,1005)

    # ── ⭐⭐⭐ 2026-10-02 摇色子「命运之骰」——**全部写死，删掉 OCR** ──────────
    #   起因：用户「固定坐标不就行了」。原实现用 OCR 找含
    #   「骰/重投/命运/重掷/掷」字样的按钮（`handle_dice` 的 `_dice_keys`），
    #   但**结算面板上根本没有这些文字** ⇒ 永远 `dice: no_btn`
    #   ⇒ 大拇指格打完了从不摇色子 ✗✗
    #   真机实测（720×1280；runs/dice_now.png → after_tap.png）：
    #     · 摇的入口 = 奖励行左下角那个**绿色四叶草 + 数字**
    #       （数字 = 还能摇几次；每摇一次消耗 1，用户 2026-10-02 确认）
    #     · 点它弹确认框：「命运之骰 — 每次重掷必定高于当前点数，最高20点」
    #     · 框上只有「取消 / 确定」，**没有任何"骰子"字样** ⇒ OCR 永远找不到 ✓
    #   ⇒ 一律固定坐标（§1b：写死 0ms ／ 模板 6.8ms ／ OCR 3.3~3.6s）✓
    'dice_reroll': (60, 967),       # 参考 1080p：奖励行左下角·四叶草 → 设备(40, 645)
    'dice_yes': (780, 1113),        # 命运之骰「确定」    → 设备(520, 742)
    'dice_no': (450, 1113),         # 命运之骰「取消」    → 设备(300, 742)
    'dice_dlg_title': (540, 756),   # 确认框标题「命运之骰」→ 设备(360, 504)
    # 奖励行四个格子中心（摇完扫有没有大拇指装备）
    'reward_slot_1': (312, 923),    # → 设备(208, 615)
    'reward_slot_2': (420, 923),    # → 设备(280, 615)
    'reward_slot_3': (528, 923),    # → 设备(352, 615)
    'reward_slot_4': (636, 923),    # → 设备(424, 615)

    # 探索槽位行（三个格子；参考 y=899 → 设备 599）
    'slot_1': (240, 899), 'slot_2': (356, 899), 'slot_3': (473, 899),

    # 结算面板底部三键（v1.19 实证：两机参考系坐标一致）
    'settle_close': (578, 1440),
    'settle_replay': (577, 1223),
    'settle_skip': (576, 1563),
}

ANCHORS = {k: _r(*v) for k, v in _ANCHORS_REF.items()}


def A(name):
    """取锚点（720×1280 像素坐标）"""
    v = ANCHORS.get(name)
    if v is None:
        raise KeyError('未知锚点 %r（可用：%s）' % (name, sorted(ANCHORS)))
    return v


# ══════════════════════════════════════════════════════════════════════
# ② 模板快查（<5ms，替代 OCR 的"存在性判断"）
# ══════════════════════════════════════════════════════════════════════
def _load(name):
    p = os.path.join(TPL_DIR, name + '.png')
    if name in _cache:
        return _cache[name]
    if not os.path.exists(p):
        _cache[name] = None
        return None
    t = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    _cache[name] = t
    return t


def find(img, name, box=None, min_conf=MATCH_MIN):
    """在 `img` 里找固定模板 `name`。

    返回 (cx, cy, score) —— 命中；否则 None。
    `box`=(x0,y0,x1,y1) 限定搜索区（**强烈建议给**：能再快一个数量级）。

    ⚠ 模板必须在 **720×1280** 截取（见 `make_templates.py`），
       放到别的分辨率会因尺寸不符直接返回 None。
    """
    t = _load(name)
    if t is None or img is None:
        return None
    th, tw = t.shape[:2]
    sub = img
    ox = oy = 0
    if box:
        x0, y0, x1, y1 = box
        sub = img[max(0, y0):y1, max(0, x0):x1]
        ox, oy = max(0, x0), max(0, y0)
    if sub is None or sub.shape[0] < th or sub.shape[1] < tw:
        # ⚠ 不是"没找到"，是**box 装不下模板**（多半是 band 写错了）——
        #    这种必须看得见，否则会静默永远不命中（第一版 BANDS['nav'] 就是这么废掉的）。
        if os.environ.get('FIXED_STRICT'):
            raise ValueError(
                '模板 %r(%dx%d) 装不进 box %s（可用区域 %dx%d）—— 检查 band 定义'
                % (name, tw, th, box, sub.shape[1] if sub is not None else 0,
                   sub.shape[0] if sub is not None else 0))
        return None
    if t.ndim == 3 and t.shape[2] == 4:          # 带 alpha 的模板：只比 RGB
        t = t[:, :, :3]
    r = cv2.matchTemplate(sub.astype(np.float32),
                          t.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    _mn, mx, _ml, loc = cv2.minMaxLoc(r)
    if mx < min_conf:
        return None
    return (int(loc[0] + tw / 2 + ox), int(loc[1] + th / 2 + oy), round(float(mx), 3))


def has(img, name, box=None, min_conf=MATCH_MIN):
    """只要"在不在"，不要坐标（省一次元组解包）"""
    return find(img, name, box=box, min_conf=min_conf) is not None


# 常用搜索区 (x0, y0, x1, y1) —— 限定区域能把匹配再快一个数量级
# ⚠⚠ 全部是 **720×1280 设备坐标**，不要再乘 K（K 已含在 ANCHORS 里了）。
#    第一版这里写了 `int(1225 * K * 2)` 这种鬼表达式，算出 y0=1633 > y1=1280
#    ⇒ 切片为空 ⇒ 模板**永远 0 命中**，而且不报错（静默失效，最难查）。
#    写完务必跑 `verify_fastpath.py`：它会拿正样本要求"必须命中"来兜住这类错误。
_BAND_TOL = 70          # 锚点上下留余量
BANDS = {
    # 底部导航条：5 个 tab 中心都在 y=1260，模板高 30 ⇒ 1230~1290，取 1180~1280
    'nav': (0, 1180, PC_W, PC_H),
    # 顶部 HUD（体力/倒计时/图名那一带）
    'hud': (0, 0, PC_W, 200),
    # 图内面板按钮带（开打/探索/派遣 中心 y≈490~1005）
    'panel_btn': (0, 400, PC_W, 1060),
    # 结算面板底部三键（关闭/回放/跳过 设备 y 815~1042）
    'settle': (0, 780, PC_W, 1080),
    # ⭐ 2026-10-02 新增：**选图界面**的「进入地图/快速扫荡」两颗按钮那一行
    #   （真机帧实测：`进入地图` 文字 bbox=(564,1066)-(641,1091)、中心 (603,1079)
    #     —— 与 `layout.REF['enter_map']` **完全一致** ✓）
    #   模板 `enter_map_btn.png`（150×110，中心 (603,1079)）就是从这里裁的。
    #   用途：判「现在是不是在**选图界面**」—— 模板 6.8ms，比一次 OCR(0.78s) 快 115 倍 ✓
    'enter_btn': (480, 1010, PC_W, 1150),
}


CHECK_PAIRS = []       # cross_check_layout() 运行时填真实锚点名（给自检打印用）


def _check_bands():
    """自检：band 必须 y0<y1 且在屏内（第一版的 1633>1280 就是这么漏过去的）"""
    bad = []
    for name, (x0, y0, x1, y1) in BANDS.items():
        if not (0 <= x0 < x1 <= PC_W and 0 <= y0 < y1 <= PC_H):
            bad.append((name, (x0, y0, x1, y1)))
    return bad


def nav_bar(img):
    """底部导航条是否在（→ 说明我们在**大厅/选图**而不是图内）"""
    return has(img, 'nav_dex', box=BANDS['nav'])


def cross_check_layout():
    """⭐ 与 `layout.LAYOUT`（权威口径）逐条对拍 —— 防止"手抄坐标抄错系"这类事故

    本模块的锚点若与 `layout.for_screen(720,1280)` 不一致，说明有人把
    **设备系**数值当**参考系**写进来了（第一版导航条就栽在这：840 vs 1260，差 400px）。
    ⇒ 这个对拍是必须的，不是可选的。
    """
    import layout as LY
    L = LY.for_screen(PC_W, PC_H)
    pairs = [
        ('explore_btn', L.explore_btn),
        ('dispatch_btn', L.dispatch_btn),
        ('start_adv_icon', L.start_adv),
        ('enter_map', L.enter_map),
        ('end_adv', L.end_adv),
        ('back_btn', L.back_btn),
        ('bottom_close', L.bottom_close),
        ('close_bag', L.close_bag),
        ('fight_normal', L.fight_btn('normal')),
        ('fight_boss', L.fight_btn('boss')),
        ('slot_1', L.slots[0]), ('slot_2', L.slots[1]), ('slot_3', L.slots[2]),
    ]
    CHECK_PAIRS[:] = [p[0] for p in pairs]        # 供自检打印真实条数
    bad = []
    for name, want in pairs:
        got = ANCHORS.get(name)
        if got is None:
            bad.append((name, want, '缺失'))
            continue
        # 允许 ±1px（两个模块的取整方式可能差 1）
        if abs(got[0] - want[0]) > 1 or abs(got[1] - want[1]) > 1:
            bad.append((name, want, got))
    return bad


def self_test():
    print('=== fixed.py 自检（PC 端 720×1280）===')
    print('屏幕 %dx%d  k=%.4f（参考 %dx%d 的纯等比缩放）'
          % (PC_W, PC_H, K, REF_W, REF_H))
    print()
    print('锚点 %d 个（全部 720×1280 像素坐标）：' % len(ANCHORS))
    for k2 in sorted(ANCHORS):
        print('   %-16s 参考%-12s → 设备 %s' % (k2, _ANCHORS_REF[k2], ANCHORS[k2]))
    print()
    ok = True
    bbad = _check_bands()
    if bbad:
        for name, bd in bbad:
            print('   ✗ band %-12s %s（y0 必须 < y1 且都在屏内）' % (name, bd))
        ok = False
    else:
        print('   ✓ %d 个 band 全部合法（y0<y1 且在屏内）' % len(BANDS))
    oob = [(k2, dev) for k2, dev in ANCHORS.items()
           if not (0 <= dev[0] < PC_W and 0 <= dev[1] < PC_H)]
    if oob:
        for k2, dev in oob:
            print('   ✗ %-16s 越界 %s' % (k2, dev))
        ok = False
    else:
        print('   ✓ 全部锚点都在屏内')
    print()
    print('--- 与 layout.LAYOUT(720×1280) 对拍（权威口径校验）---')
    try:
        bad = cross_check_layout()
    except ImportError:
        print('   (找不到 layout.py，跳过对拍)')
        bad = []
    if bad:
        for name, want, got in bad:
            print('   ✗ %-16s LAYOUT=%s  本表=%s' % (name, want, got))
        ok = False
    else:
        print('   ✓ %d 个可对拍锚点与 LAYOUT 完全一致（±1px）' % len(CHECK_PAIRS))
    tpls = []
    if os.path.isdir(TPL_DIR):
        tpls = [f[:-4] for f in os.listdir(TPL_DIR) if f.endswith('.png')]
    print()
    print('   模板 %d 个：%s' % (len(tpls), tpls or '（还没生成，跑 make_templates.py）'))
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if self_test() else 1)
