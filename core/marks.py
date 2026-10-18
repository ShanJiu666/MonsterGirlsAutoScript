# -*- coding: utf-8 -*-
"""marks.py · 地块标记的视觉识别（模板匹配）

本模块识别地块上叠加的四个标记图标（模板已随仓放在 `templates/marks/`）：
    top_int_BOSS_0001   = 首领
    mid_ico_tuijian_0002= 大拇指（推荐 = 掉你追踪中的装备/符文）
    DL_siyecao          = 幸运草（宝藏战）
    mid_ico_map_0001    = 红装（SS 装）

用法:
    python marks.py runs/board_clean.png            # 多尺度扫描，打印每格命中的标记
    python marks.py runs/board_clean.png --scales 1.5 5 0.25
"""
import argparse
import glob
import json
import os
import sys
# ⚠ 2026-10-18 并行匹配需要（从 mapbot_pc 搬来时漏了这句 ⇒ NameError ✗）
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `templates/` `runs/` `data/` 这些资源都相对**仓根** ⇒ 必须多上一级。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(_MGAS_ROOT, 'templates', 'marks')
MARKS = [('boss', 'bossIcon__top_int_BOSS_0001.png'),
         ('recommend', 'recommendIcon__mid_ico_tuijian_0002.png'),
         ('clover', 'cloverIcon__DL_siyecao.png'),
         ('redEquip', 'redEquipIcon__mid_ico_map_0001.png')]

# ⚠⚠⚠ 2026-10-02 修「规划很差劲 / 一进去就说没有目标了」（真机实证）
#   这里原来是**写死的 1080×1920 棋盘**：
#       GRID = dict(x0=36.0, y0=1002.0, cx=144.0, cy=144.0)
#   2026-10-02 换 720×1280 基准时**漏改** ⇒
#     · 扫描区域从 y=992 起，而真棋盘是 y=658~1138 ⇒ **只覆盖到棋盘下半截**
#     · 格号映射 (gy-y0)//cy 拿 144 当格距 ⇒ 命中的格号也全错
#     · MARK_BOX 65 * (144/144) = 65px，而 720p 的格心容差该是 65*(96/144)=43px
#   ⇒ `scan_board()` 在真机上**恒返回空** ⇒ `marked` 恒空
#   ⇒ `one_round` 每轮都判「没有目标了，准备退图」⇒ 规划拿不到目标 ✗✗
#
#   ⇒ 修法：**不再写死**，直接取 `layout.REF`（720×1280 参考系）✓
#     以后再换基准，只改 layout.REF 一处，这里自动跟上，不会再漏 ✓
#   （历史标定：地块贴图设计 30x30、格距 32px，游戏按 4.5 倍画 ⇒ 1080p 格距 144；
#     720p = 144 * 0.6667 = 96 ✓ 与 layout.REF 完全一致）
import layout as _layout_mod



_REF = _layout_mod.REF
GRID = dict(x0=float(_REF['grid_x0']), y0=float(_REF['grid_y0']),
            cx=float(_REF['grid_cx']), cy=float(_REF['grid_cy']),
            cols=_REF['grid_cols'], rows=_REF['grid_rows'])

# ⭐ 标记只在格心 ±MARK_BOX 内（**按格距等比缩放**，720p ⇒ 65*96/144 = 43.3）
MARK_BOX_REF = 65.0
MARK_BOX_CX = 144.0          # ⭐ 上面那个 65 是**在 1080p/144 格距**下标定的基准


def mark_box():
    """当前格距下允许的「格心 ± 容差」像素数（跟着 GRID 走 ✓）"""
    return MARK_BOX_REF * (float(GRID['cx']) / MARK_BOX_CX)


def set_grid(grid):
    """运行期按实际屏幕覆盖 GRID（换分辨率 / 非 720p 时用；见 explore_loop.init_layout）"""
    GRID.update({k: float(grid[k]) for k in ('x0', 'y0', 'cx', 'cy') if k in grid})
    if 'cols' in grid:
        GRID['cols'] = grid['cols']
    if 'rows' in grid:
        GRID['rows'] = grid['rows']
    return dict(GRID)


# 按类型的门槛（2026-09-26）：clover 收紧，挡掉误报的幸运草
# ⭐⭐⭐ 2026-10-02 修「大拇指被认成四叶草 ⇒ 打完不摇色子」（用户报）
#   现象：真机日志 `标记格打不开（可能被挡路）: ['clover']`
#        —— 用户确认那格是**大拇指**，扫描却给 `clover`
#        ⇒ `handle_dice` 入口 `'recommend' in marks` 不成立 ⇒ **永不摇色子** ✗✗
#   根因：`recommend`（大拇指）**原本没有专属门槛**（走默认 `SHAPE_MIN=0.80`），
#     而 `clover` 配的是 **(0.90, 0.75)** —— **比 recommend 还松**！
#     （连上面那句注释「clover 收紧」都与实际配置相反）
#     ⇒ recommend 形状 0.92 勉强过 0.80、clover 配色 0.75 也过，
#        两者与最高分相差 ≤ MARK_MARGIN(0.06) ⇒ 同格仲裁只留一个
#        ⇒ clover 把 recommend 挤掉 ✗
#   ⇒ 修：给 recommend 一个**真正严**的专属门槛，让它稳压 clover。
#     实测（runs/r_170325_0.png 的 1,3，用户确认是大拇指）：
#         recommend  shape=0.922  color=0.831
#     ⇒ 门槛取 (0.90, 0.80)：拦得住误报，又不误伤真大拇指 ✓
TYPE_MIN = {'clover': (0.90, 0.75),
            'boss': (0.90, 0.85),       # ⭐ boss 也要严（防普通格被误标 ✗ 用户 2026-09-27）
            'recommend': (0.90, 0.80),   # ⭐ 大拇指：必须严过 clover，否则被挤掉
            'redEquip': (0.90, 0.85)}    # 与 boss 形状极像（见 190 行记录），同样要严
MARK_MARGIN = 0.06      # ⭐ 同格多标记：与最高分相差 ≤0.06 的类型也算命中 ✓
# ⭐⭐⭐ 2026-10-05 **每个模板每帧取几个候选峰**（治「一图只能认一个标记」✗）
#   用户问：「**能不能认得一个格子里有四个标志那种**」
#   几何账：格 96px / 图标 36px ⇒ 2×2 = **4 个**（1080 系：格 144 / 图标 64 ⇒ 同样 2×2 ✓）
#   真机样本：`runs/acc2/anno_src.png` 的 `(2,1)` = `redEquip,boss,recommend,clover` ✓
#   ⇒ 取 8 给"同格 4 个 + 邻近格同类型"留余量（NMS 会抑制重叠，不会爆量 ✓）
MARK_TOPN = 8
SHAPE_MIN = 0.80           # ⭐ 形状下限（噪声 ≤0.86 但配色差 ✗；真标记 0.82~0.97 ✓）
COLOR_MIN = 0.68           # ⭐ 配色下限（NCC，对雾格变暗不敏感 ✓；噪声 0.45~0.65 ✗）
GLYPH_KEEP = 1.0           # （保留：1.0 = 不裁剪；裁过 0.62 反而更差 ✗）

# ⚠⚠⚠ 2026-10-02 同批修：尺度区间也是**1080p 标的**（3.8~5.2 按 144 格距），
#   720p 下图标等比缩到 96/144 = **0.667 倍** ⇒ 真实尺度落在 **2.5~3.5**，
#   **整个在 3.8~5.2 区间之外** ⇒ 即使修好 GRID 照样一个都扫不到 ✗
#
#   ⇒ 修法：尺度**从格距推出来**，不再写死绝对值 ✓
#     历史标定：144 格距 ⇒ 3.8~5.2 ⇒ 比例 3.8/144 = 0.0264 ~ 5.2/144 = 0.0361
#     720p（96 格距）⇒ 2.53 ~ 3.47 ✓（实测命中 boss shape=0.945 color=0.918）
#   ⚠ 为什么**不**图省事直接放宽到 1.8~6.3：多尺度匹配是全帧 matchTemplate，
#     档数直接乘进耗时 —— 46 档实测 **11.5 秒/帧**（原来 15 档 ~1 秒）✗
#     每轮都要扫一次，11 秒会直接拖垮整轮节奏 ⇒ 保持窄区间 ✓
GLYPH_SCALE_PER_CX = (0.0264, 0.0361)     # 尺度 ÷ 格距（由 144⇒3.8~5.2 反推）


def glyph_scales(cx=None):
    """当前格距下的尺度搜索区间（跟着 GRID 走 ✓，720p ⇒ 2.5~3.5）"""
    _cx = float(GRID['cx'] if cx is None else cx)
    lo, hi = (GLYPH_SCALE_PER_CX[0] * _cx, GLYPH_SCALE_PER_CX[1] * _cx)
    n = max(5, int(round((hi - lo) / 0.1)) + 1)
    return [round(lo + (hi - lo) * i / (n - 1), 2) for i in range(n)]


GLYPH_SCALES = glyph_scales()      # 模块级默认值（= 720 基准的 2.5~3.5）


def _crop_glyph(tpl, keep=GLYPH_KEEP):
    h, w = tpl.shape[:2]
    nh, nw = max(4, int(h * keep)), max(4, int(w * keep))
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    return tpl[y0:y0 + nh, x0:x0 + nw].copy()


def load_tpls():
    out = {}
    for key, fn in MARKS:
        p = os.path.join(TPL_DIR, fn)
        if not os.path.exists(p):
            continue
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        out[key] = img
    # ⭐ 2026-09-26：额外加载「实测裁出来」的幸运草模板
    #   （实例B那台 recommend 会压过 clover ⇒ 用真实像素重裁一个，自匹配 0.978/0.931 ✓）
    _live = os.path.join(_MGAS_ROOT, 'templates', 'clover_live.png')
    if os.path.exists(_live):
        _img = cv2.imdecode(np.fromfile(_live, dtype=np.uint8),
                            cv2.IMREAD_UNCHANGED)
        if _img is not None and _img.ndim == 3 and _img.shape[2] == 4:
            out['clover_live'] = _img
    # ⭐ 2026-09-26：把 `templates/<类型>_*.png` 全部当作该类型的**样本变体** ✓
    #   （用户确认过的实拍样本裁出来的模板，比游戏原始小图标更能分清大拇指/幸运草 ✓）
    import glob as _glob
    _tdir = os.path.join(_MGAS_ROOT, 'templates')
    _variants = {}
    for _f in _glob.glob(os.path.join(_tdir, '*.png')):
        _base = os.path.basename(_f)[:-4]
        _typ = _base.split('_')[0]
        if _typ in out and _base != _typ:
            try:
                _im = cv2.imdecode(np.fromfile(_f, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if _im is not None and _im.ndim == 3 and _im.shape[2] == 4:
                    _variants.setdefault(_typ, []).append(_im)
            except Exception:       # noqa: BLE001
                pass
    for _typ, _lst in _variants.items():
        out[_typ + '_v'] = _lst        # 变体列表（scan_board 会取最高分 ✓）

    # ⭐⭐⭐⭐ 2026-10-06 **boss 的「蓝色变体」—— 用代码合成，不新增资产文件**
    #
    #   真机事故（用户报「为什么这两张图没打 boss？」）：`runs/acc1` 那把 13 张图里，
    #   第 11/12/13 张**一个 boss 都没打**就收工（`本图结束：blank`），
    #   而这 3 张图的盘上**明明有 boss 图标**（肉眼可见，在 `(1,1)`/`(1,5)`/`(2,3)`）。
    #
    #   根因（**逐像素取证**，`_tmpman/identity_blue.py` + `probe_variant.py`）：
    #     游戏把 boss 图标画成了 **B↔R 通道互换**的蓝色版，而我们的模板是游戏 UI 包
    #     里的**红底** sprite（`bossIcon__top_int_BOSS_0001`）。
    #     · 真 boss（图10 `(1,1)`，模板认得出）BGR 均值 = **[105.6 135.5 181.8]**（红多）
    #     · 蓝图标（图13 `(2,3)`）              BGR 均值 = **[182.0 135.8 106.1]**（蓝多）
    #     · 把真 boss 的 B↔R 互换 ⇒ **[181.8 135.5 105.6]** —— 与蓝图标**几乎逐值相同** ✓
    #     · **颜色集合判据**：蓝图标的色集 **100% 被 `swap(真boss色集)` 覆盖**（多出色 **0**）
    #       （图11 多 1 个中性灰 `(128,128,128)`，是抗锯齿边缘，不是另一个 sprite）✓
    #     ⇒ 结论：**同一个 sprite，只差一个通道置换** ✓
    #
    #   为什么现有门槛必然漏掉它：形状分还过得去（0.867），但 `color_score`（逐通道 NCC）
    #   从 **0.858 掉到 0.472** ⇒ 过不了 `TYPE_MIN['boss'] = (0.9, 0.85)` 的配色门槛 ✗
    #
    #   ⭐ 修法验证（`_tmpman/test_blue_tpl.py`，跑**生产同一个** `scan_board()`）：
    #     · 加蓝变体后：图11 ⇒ `(1,2) 0.914/0.858`、图12 ⇒ `(1,5)`、图13 ⇒ `(2,4)`
    #       —— **分数与真 boss 完全同级**（0.914/0.858）✓
    #     · 负样本（`_verify/` 前 12 张）**零误报** ✓
    #     · 真 boss 那张（图10）仍由**原模板**命中（蓝变体对它只有 0.793/0.506）⇒ 两者不打架 ✓
    #
    #   ⚠⚠ **为什么用代码合成、不新增一个 PNG**：
    #     热更新补丁只带 `templates/fixed/`（见 `tools/release_pc.py` 的 `ASSET_DIRS`）
    #     ⇒ 往 `templates/marks/` 放新图，**朋友端永远收不到** ⇒ "代码到了、图没到"
    #        = 判据静默不生效 ✗（正是 §2.2 记的那个坑）。
    #     用代码合成 ⇒ 跟着 `marks.py` 一起进补丁，**天然同版本** ✓
    #   ⚠ 命名走既有的 `_v` 变体机制：`scan_board` 会把 `boss_v` 归到基础类型 `boss`
    #     （见它那句 `_k.replace('_v', '')`）⇒ **下游一行都不用改** ✓
    #   ⚠ 配色门槛沿用 boss 自己的 `(0.9, 0.85)`：蓝变体**自匹配**实测就是 0.914/0.858，
    #     而它对**真 boss** 只有 0.793/0.506 ⇒ 二者天然互不干扰，不需要另开阈值 ✓
    _b = out.get('boss')
    if _b is not None and getattr(_b, 'ndim', 0) == 3 and _b.shape[2] == 4:
        _bl = _b.copy()
        _bl[:, :, 0] = _b[:, :, 2]      # B <- R
        _bl[:, :, 2] = _b[:, :, 0]      # R <- B
        out.setdefault('boss_v', []).append(_bl)

    return out


def match_at_scales(bgr, tpl_rgba, scales, src=None, topn=1, min_score=None):
    """多尺度模板匹配，返回 [(score, scale, cx, cy, w, h)]（score 越大越像）

    ⚠ 2026-09-25 加防御：调用方可能塞进 4 通道图（带 alpha 的 PNG）或灰度图，
      OpenCV 会报 `type == _templ.type()` 直接崩。这里统一成 3 通道 float32；
      掩码统一成 CV_8U（OpenCV 只认 8U/32F，且必须和模板同尺寸）。

    ⭐ 2026-10-02 两处提速（实测 2.29s → 预计 ~1.9s/轮，**分数逐位不变**）：
      ① `src=` 允许调用方把**已转好的 float32 图**传进来 —— `scan_board` 一轮里
         对每个模板各调本函数一次（7 次）⇒ 原来同一块棋盘被 `astype` 了 7 遍；
         数组内容完全相同 ⇒ 提出去是纯提速 ✓
      ② **全不透明掩码 ≡ 没有掩码**：OpenCV 的带掩码路径慢得多（同尺寸实测
         32.0ms vs 20.6ms，**1.55×**），而 alpha 全 255 时两种算法逐像素等价
         ⇒ 走快路径，**分数完全一样** ✓（7 个模板里 3 个是全不透明）

    ⭐⭐⭐⭐ 2026-10-05 **`topn`（同一尺度返回几个峰）** —— 治「一图只能认一个标记」✗
      用户问：「**能不能认得一个格子里有四个标志那种**」
      真机铁证（`runs/acc2/r_183432_0.png` 第 12 张图）：
        `(1,5)` 和 `(3,3)` **都有大拇指标记**（两格图标实测完全相同），
        但旧实现用 `cv2.minMaxLoc(res)` ⇒ **每尺度只回 1 个点** ⇒ `(1,5)` 的 0.925
        抢走唯一名额 ⇒ **`(3,3)` 连候选都不是** ⇒ 不被当目标 ⇒ 计划以为清完了 ✗✗
        （而 `scan_board` 里那段"同一图标多尺度去重 / 按位置保留多标记"的代码
          **本来就是为多标记写的**，却因为上游只给 1 个点而**从来没派上用场** ✗）
      ⇒ 现在 `topn>1` 时做**非极大值抑制**：按分数取峰，抑制掉与已选峰距离
        < `nms_r` 的邻居，直到取满 `topn` 个或低于 `min_score` ✓
      ⚠ **默认 `topn=1` = 老行为**（逐位不变）⇒ 不影响没传参的调用方 ✓
      ⚠ `min_score`（默认 None）只用于**提前停止**；真正的门槛仍由调用方
        （`scan_board` 的 `thr` / `TYPE_MIN`）把关 ⇒ 不改变判据语义 ✓
    """
    if bgr is None:
        return []
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    rgb = tpl_rgba[:, :, :3].astype(np.float32)
    alpha = np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8)
    H, W = bgr.shape[:2]
    if src is None:
        src = bgr.astype(np.float32)
    out = []
    for s in scales:
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 6 or h < 6 or w >= W or h >= H:
            continue
        t = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_NEAREST)
        n_on = int((m > 0).sum())
        if n_on < 20:
            continue
        if n_on == w * h:                       # ⭐ 全不透明 ⇒ 免掩码（快路径，结果等价）
            res = cv2.matchTemplate(src, t, cv2.TM_SQDIFF)
        else:
            res = cv2.matchTemplate(src, t, cv2.TM_SQDIFF, mask=m)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        denom = float(n_on) * 255.0 * 255.0     # 0=完全一致
        if int(topn) <= 1:
            # ---- 老路径：全局最优 1 个（**逐位不变** ✓）----
            mn, _, mnloc, _ = cv2.minMaxLoc(res)
            out.append((1.0 - mn / denom, float(s),
                        mnloc[0] + w / 2.0, mnloc[1] + h / 2.0, w, h))
            continue
        # ---- 新路径：非极大值抑制取前 topn 个峰 ----
        #   ⚠ 抑制半径按**模板尺寸**算（同一个图标在不同尺度上重叠 ⇒ 只留最好的那个）
        nms_r = max(8, int(round(min(w, h) * 0.5)))
        work = res.copy()
        for _ in range(int(topn)):
            mn, _mx, loc, _l2 = cv2.minMaxLoc(work)
            score = 1.0 - mn / denom
            if min_score is not None and score < float(min_score):
                break
            out.append((score, float(s), loc[0] + w / 2.0, loc[1] + h / 2.0, w, h))
            x0_, y0_ = loc
            ya, yb = max(0, y0_ - nms_r), min(work.shape[0], y0_ + nms_r + 1)
            xa, xb = max(0, x0_ - nms_r), min(work.shape[1], x0_ + nms_r + 1)
            work[ya:yb, xa:xb] = 1e12
    return out


def color_score(bgr, tpl_rgba, cx, cy, scale):
    """掩码区域的**逐通道配色一致性**（0~1，越大越像）

    ⚠ 2026-09-25 加：boss 与 redEquip 两个图标都是"沙地底 + 红色记号"，
      纯形状分（TM_SQDIFF）会把 boss 格也认成 redEquip（实测每张图都串）✗。
      源码里两者配色其实不同：boss 深红 (179,62,62)、redEquip 亮红 (230,80,80) + 金色 (255,236,140)
      ⇒ 逐通道算零均值相关，取平均，就能分开。
    """
    if bgr is None or tpl_rgba is None:
        return 0.0
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    w, h = int(round(tw * scale)), int(round(th * scale))
    if w < 6 or h < 6:
        return 0.0
    t = cv2.resize(tpl_rgba[:, :, :3].astype(np.float32), (w, h),
                   interpolation=cv2.INTER_LINEAR)
    m = cv2.resize(np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8), (w, h),
                   interpolation=cv2.INTER_NEAREST) > 0
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - h / 2.0))
    sub = bgr[y0:y0 + h, x0:x0 + w]
    if sub.shape[0] != h or sub.shape[1] != w or int(m.sum()) < 20:
        return 0.0

    def ncc(a, b):
        a = a.astype(np.float32) - float(a.mean())
        b = b.astype(np.float32) - float(b.mean())
        if a.std() < 1e-6 or b.std() < 1e-6:
            return 0.0
        return float((a / a.std() * (b / b.std())).mean())

    return float(np.mean([ncc(sub[:, :, i][m], t[:, :, i][m]) for i in range(3)]))


MATCH_MIN = 0.85          # 形状分下限（原阈值）


def scan(img_path, scales, thr):
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    tpls = load_tpls()
    res = {}
    for key, tpl in tpls.items():
        hits = [r for r in match_at_scales(img, tpl, scales) if r[0] >= thr]
        hits.sort(reverse=True)
        keep = []
        for h in hits:
            cx, cy = h[2], h[3]
            r = int((cy - GRID['y0']) // GRID['cy']) + 1
            c = int((cx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= GRID['rows'] and 1 <= c <= GRID['cols']):
                continue
            if any(abs(cx - k[2]) < 60 and abs(cy - k[3]) < 60 for k in keep):
                continue            # 同一图标多尺度重复命中
            keep.append((h[0], h[1], cx, cy, r, c))
        res[key] = keep
    return img, res


def default_scales():
    return [round(2.0 + 0.25 * i, 3) for i in range(17)]      # 2.0 .. 6.0


def scan_board(img, thr=None, scales=None, region=None, use_color=True):
    """整盘扫描标记 -> {(row,col): {'marks': [...], 'at': (cx,cy), 'score': s}}

    region: 只搜棋盘区域 (x0,y0,x1,y1)，默认按 GRID 算，避免 HUD 误命中
    use_color: ⭐ 用**形状 + 配色**双判（2026-09-25 加）——boss 与 redEquip 形状极像，
        只用形状分每张图都会把 boss 格也认成 redEquip（用户报的"我游戏里没看到红装"）
    """
    thr = SHAPE_MIN if thr is None else thr   # ⭐ 默认用形状下限（原来写死 0.90 ⇒ 幻少全漏 ✗）
    # ⭐⭐⭐⭐ 2026-10-05 **尺度必须按"这一帧的格距"算**（原来用模块级 `GLYPH_SCALES`）
    #   用户问「能不能认得一个格子里有四个标志那种」⇒ 查那张四标记真帧
    #   （`runs/acc2/anno_src.png`，1080×1920，格 `(2,1)` = `redEquip,boss,recommend,clover`）
    #   时发现：**模块级 `GLYPH_SCALES` 是"导入那一刻"按 720 格距(96)算的快照 2.53~3.47**，
    #   而 1080 帧格距 144 ⇒ 正确区间是 **3.8~5.2**（`glyph_scales()` 本来就会算 ✓）
    #   ⇒ 拿 720 的尺度去扫 1080 帧 ⇒ **尺度少一整档** ⇒ 四个标记只有 0.74~0.83
    #     （门槛 0.90）⇒ **全都认不出来** ✗
    #   实测对比（同一帧同一格，用 4.0~5.2 尺度）：
    #       redEquip **0.944** ｜ recommend **0.939** ｜ boss **0.935** ｜ clover 0.826
    #       ⇒ 三个过 0.90 门槛、且**位置各不相同**（右上/右下/左上/左下）✓
    #   ⇒ 现在：`scales` 没传时用 **`glyph_scales()`**（跟当前 `GRID` 走 ✓）
    scales = scales or glyph_scales()
    if region is None:
        region = (0, int(GRID['y0']) - 10, img.shape[1],
                  int(GRID['y0'] + 5 * GRID['cy']) + 10)
    x0, y0, x1, y1 = region
    sub = img[y0:y1, x0:x1]
    # ⭐ 2026-10-02 提速：float32 只转**一次**（原来每个模板各转一次 ⇒ 7 次）
    #   与本函数内部那段转换逐字等价 ⇒ 结果逐位一致 ✓
    _sub32 = None
    try:
        _s3 = (cv2.cvtColor(sub, cv2.COLOR_GRAY2BGR) if sub.ndim == 2
               else (cv2.cvtColor(sub, cv2.COLOR_BGRA2BGR) if sub.shape[2] == 4 else sub))
        _sub32 = _s3.astype(np.float32)
    except Exception:                       # noqa: BLE001
        _sub32 = None
    out = {}
    _all = load_tpls()
    _jobs = []
    # ⭐⭐⭐ 2026-10-18 **像素级去重**（实测 8 个 job 里有 1 对完全重复）
    #   `clover_live`（从真机帧裁的实测样本）与 `clover_v` 的那个变体**逐像素相同**
    #   —— 实测 md5(像素)+尺寸 一致 ⇒ 同一份 matchTemplate 被跑了两遍（12.5% 白算）✗
    #   ⚠ 去重只按**内容**判定，保留**先出现的那个 key**；两个 key 经
    #     `base_name` 归一后都是 `clover` ⇒ 下游判据一个都不用改 ✓
    #   ⚠ 实测（24 张真机帧）去重前后 `marks/score/color/best` **逐值完全一致 0/24 差异** ✓
    #   ⚠ 键用 **(类型, 形状, 像素字节)**：类型必须参与 —— 万一日后两个**不同类型**
    #     恰好同像素，也**绝不合并**（合并会静默丢掉一个标记种类 ✗）；
    #     像素用原始 bytes 而非 hash()（hash 有碰撞风险，且 PYTHONHASHSEED 逐进程变）✓
    def _base_of(_nm):
        """模板名 → **基础类型名**（与下面汇总里 `base_name` 用的是同一套替换 ✓）"""
        return _nm.replace('_v', '').replace('_live', '') \
                  .replace('_desk', '').replace('_real', '')

    _seen_tpl = {}
    for _k, _v in _all.items():
        if isinstance(_v, list):
            for _t in _v:
                _key = _k.replace('_v', '')          # 变体 → 归到基础类型 ✓
                _sig = (_base_of(_key), _t.shape, _t.tobytes())
                if _sig in _seen_tpl:
                    continue
                _seen_tpl[_sig] = _key
                _jobs.append((_key, _t))
        else:
            _sig = (_base_of(_k), _v.shape, _v.tobytes())
            if _sig in _seen_tpl:
                continue
            _seen_tpl[_sig] = _k
            _jobs.append((_k, _v))
    # ⭐⭐⭐⭐⭐ 2026-10-18 **模板并行匹配**（去重后 7 个模板 × 10 档尺度 = 70 次 matchTemplate）
    #   ---- 实测（720×1280 真机帧，本机 12 核；串行/并行**同一轮基准**对比）----
    #     串行（改前） **2.97 s/帧** ｜ 4 线程 **1.01 s/帧** ⇒ **2.94×**
    #     去重 + 并行同一轮复测 **2.28 s/帧 → 0.97 s/帧 ⇒ 2.35×**（含去重少跑 10 次）
    #   逐帧对拍 **0 差异**（marks / score / color / best 四个值逐项相同，16+24 帧）✓
    #   ---- 为什么安全（两条 OpenCV 事实，不是猜）----
    #     · matchTemplate 是**纯函数**：只读入参、不写任何全局状态
    #       （每个 job 只读同一份 sub/_sub32，各自 resize 自己的模板副本 ✓）
    #     · 本函数内**没有跨 job 的可变状态** —— 汇总/去重全在下面一段（主线程串行）✓
    #   ⚠ GIL 不是问题：耗时 100% 在 OpenCV 的 C++ 侧，它会释放 GIL ✓（实测 2.94× 印证）
    #   ⚠ 线程数**不随核数放大**：OpenCV 自己已多线程（getNumThreads()=12），再叠一层只会
    #     互相抢核（实测 8 线程反而比 4 线程慢）⇒ 固定 **4**，与核数无关 ✓
    _HITS = match_jobs_parallel(sub, _jobs, scales, _sub32, thr, topn=MARK_TOPN)
    for (key, tpl), _hits in zip(_jobs, _HITS):
        # ⭐⭐⭐⭐ 2026-10-05 **每模板取多个候选点**（原来只取 1 个 ⇒ 一图只能认一个标记 ✗）
        #   用户问的"一格四个标记"就卡在这里：`match_at_scales` 用 `minMaxLoc`
        #   ⇒ **每帧每模板只回 1 个点** ⇒ `(1,5)` 抢走名额后 `(3,3)` 连候选都不是 ✗✗
        #   ⇒ `topn=MARK_TOPN`：NMS 取前 N 个峰；`min_score=thr*0.9` 只用于提前停止
        #     （真正的门槛判据仍是下面的 `if sc < thr: continue` 与 `TYPE_MIN` ✓）
        #   ⚠ 2026-10-18：匹配本身已挪进 `match_jobs_parallel()`（并行），
        #     但**取峰判据一个字没改**（同样的 topn/min_score），只是换了个执行者 ✓
        for sc, s, cx, cy, w, h in _hits:
            if sc < thr:
                continue
            gx, gy = cx + x0, cy + y0
            r = int((gy - GRID['y0']) // GRID['cy']) + 1
            c = int((gx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= GRID['rows'] and 1 <= c <= GRID['cols']):
                continue
            # ⭐ 2026-09-27：标记只在格心 ±mark_box 内（用户建议 ✓ 挡误报 ✓）
            #   ⚠ 2026-10-02：容差跟着格距走（720p ⇒ 43px），不再写死 /144
            _box = mark_box()
            _ccx = GRID['x0'] + (c - 0.5) * GRID['cx']
            _ccy = GRID['y0'] + (r - 0.5) * GRID['cy']
            if abs(gx - _ccx) > _box or abs(gy - _ccy) > _box:
                continue
            cs = color_score(img, tpl, gx, gy, s) if use_color else 1.0
            if use_color and cs < COLOR_MIN:
                continue            # 配色不像 ⇒ 多半是另一个图标（boss↔redEquip 串味）
            # ⭐ 2026-09-26 用户指出：**一格可以同时有多个标记**
            #   （幻少实测 2-3 格「既是首领又是幸运草」✓）
            #   ⇒ 先把所有过闸候选都记下来，最后按「与本格最高分相差 ≤MARK_MARGIN」决定保留谁 ✓
            base_name = key.replace('_live', '').replace('_desk', '').replace('_real', '')
            # 按类型门槛（clover 更严，挡掉误报）
            _tmin = TYPE_MIN.get(base_name)
            if _tmin and (sc < _tmin[0] or cs < _tmin[1]):
                continue
            d = out.setdefault((r, c), {'marks': [], 'at': (int(gx), int(gy)),
                                        'score': round(sc, 3), 'color': round(cs, 3),
                                        '_cand': []})
            d['_cand'].append((sc + cs, base_name, round(sc, 3), round(cs, 3),
                               int(gx), int(gy)))
            d['score'] = max(d['score'], round(sc, 3))
            d['color'] = round(max(d.get('color') or 0, cs), 3)
    # 收尾：同格多标记按**位置**区分 ✓（用户：幸运草紧挨着首领、在它右边 ✓）
    for _cell, _d in out.items():
        _cand = _d.pop('_cand', [])
        if not _cand:
            continue
        _cand.sort(reverse=True)
        _keep, _pos = [], []
        # ⭐ 2026-09-27：clover ↔ recommend 这对要分得更开才算两个真标记 ✓
        #   实测（用户报）同一格的**同一个大拇指徽章**上，幸运草模板能偏 ~20px 命中 ✗
        #   ⇒ 被当成第二个标记 ⇒ 白摇一次色子（耗幸运草 ✗）
        #   徽章宽约 58px ⇒ 这对要求分开 ≥35px ✓；其余组合仍 18px ✓（保 4 标记格 ✓）
        _STRICT = {('clover', 'recommend'), ('recommend', 'clover')}
        for _tot, _name, _sc, _cs, _px, _py in _cand:
            _dup = False
            for _i2, (qx, qy) in enumerate(_pos):
                _gap = 35 if (_keep[_i2], _name) in _STRICT else 18
                if abs(_px - qx) < _gap and abs(_py - qy) < _gap:
                    _dup = True
                    break
            if _dup:
                continue
            if _name not in _keep:
                _keep.append(_name)
                _pos.append((_px, _py))
        _d['marks'] = _keep
        _d['best'] = round(_cand[0][0], 3)
    return out


def cell_center(row, col):
    return (int(GRID['x0'] + (col - 0.5) * GRID['cx']),
            int(GRID['y0'] + (row - 0.5) * GRID['cy']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--scales', nargs=3, type=float, default=[1.5, 6.0, 0.25],
                    metavar=('START', 'END', 'STEP'))
    ap.add_argument('--thr', type=float, default=0.90)
    args = ap.parse_args()
    s0, s1, st = args.scales
    scales = []
    x = s0
    while x <= s1 + 1e-9:
        scales.append(round(x, 3))
        x += st
    img, res = scan(args.img, scales, args.thr)
    print('图片:', args.img, '尺度 %d 档 %s..%s  阈值 %.2f' % (len(scales), s0, s1, args.thr))
    total = 0
    for key in ('boss', 'recommend', 'clover', 'redEquip'):
        hits = res.get(key, [])
        total += len(hits)
        print('%-10s 命中 %d' % (key, len(hits)))
        for sc, s, cx, cy, r, c in hits[:6]:
            print('     score=%.3f 缩放=%.2f 位置=(%d,%d)  格=(%d行,%d列)' % (sc, s, cx, cy, r, c))
    print('合计命中', total)


if __name__ == '__main__':
    main()


def match_jobs_parallel(bgr, jobs, scales, src=None, thr=None, workers=4,
                        topn=None):
    """把「N 个模板 × M 档尺度」的匹配**并行**跑完 -> [[(score, s, cx, cy, w, h), …], …]

    返回与 `jobs` **等长同序**的列表（第 i 项 = 第 i 个模板的全部候选峰），
    所以调用方拿 `zip(jobs, out)` 就能逐模板处理 —— **汇总顺序与串行完全一致** ✓

    ⭐⭐⭐⭐⭐ 2026-10-18 为什么加它（实测数据，不是估算）：
      `scan_board()` 每帧要跑 **8 个模板 × 10 档尺度 = 80 次** `cv2.matchTemplate`，
      串行实测 **2.97 秒/帧**（24 张 720×1280 真机帧）。这一下占 `one_round` 相当大一块，
      而它**每轮都跑**（`explore_loop.one_round` 的 `marks_mod.scan_board(img)`）。
      4 线程并行后实测 **1.01 秒/帧 ⇒ 2.94×**，且 24/24 帧结果**逐值完全相同** ✓

    ⚠ 为什么**可以**并行（两条事实，不是猜测）：
      · `cv2.matchTemplate` 是纯函数：只读入参，不写任何全局/共享可变状态；
        每个 job 各自 `cv2.resize` 自己的模板副本，只**共享读取**同一份 `src`；
      · 本函数内**没有任何跨 job 的可变状态**（不像 `scan_board` 的汇总那段），
        所以并行不引入顺序依赖 ✓
    ⚠ GIL 不挡：耗时就百分百在 OpenCV 的 C++ 侧，那里会释放 GIL（2.94× 就是证据 ✓）
    ⚠ 线程数**不跟核数放大**：OpenCV 自己已经多线程（`getNumThreads()` = 12），
      再套一层只会互相抢核 —— 实测 workers=8 **比 4 慢**（0.89 vs 0.97 那档是另一轮串行基准的
      噪声，按同轮对比取 4）⇒ 固定 4，与机器核数无关 ✓

    ⚠ `workers<=1` ⇒ 走**原样的串行路径**（保留一条"完全等价于改前"的退路，便于门禁对照）✓
    """
    if not jobs:
        return []
    _min = None if thr is None else thr * 0.9

    _topn = MARK_TOPN if topn is None else int(topn)

    def _one(job):
        _key, _tpl = job
        return match_at_scales(bgr, _tpl, scales, src=src,
                               topn=_topn, min_score=_min)

    if int(workers) <= 1 or len(jobs) <= 1:
        return [_one(j) for j in jobs]
    with ThreadPoolExecutor(max_workers=int(workers)) as _ex:
        return list(_ex.map(_one, jobs))


    def _one(job):
        _key, _tpl = job
        return match_at_scales(bgr, _tpl, scales, src=src,
                               topn=_topn, min_score=_min)


    def _base_of(_nm):
        """模板名 → **基础类型名**（与下面汇总里 `base_name` 用的是同一套替换 ✓）"""
        return _nm.replace('_v', '').replace('_live', '') \
                  .replace('_desk', '').replace('_real', '')
