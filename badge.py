# -*- coding: utf-8 -*-
"""badge.py · 认「大拇目标记」（推荐徽章 = 绿边 + 绿拇指，`mid_ico_tuijian_0002`）

为什么不用纯形状分：奖励行里的小图标只有 14~60px，纯形状的**噪声地板就有 0.83**
（面板底色、图标品质边框都能凑上去），上一版按 0.80 早停 → 「没刷到大拇指装备就退了」
（用户 2026-09-25 报）。改成**形状 + 三通道配色**双判，实测：

    正样本（地图上已知的大拇目标记，scale 4.4）: 形状 0.807  配色 0.771
    负样本（摇色子奖励区的假命中）            : 形状 0.51/0.54/0.28  配色 0.51/0.52/0.22

⇒ 判据 `形状 >= 0.70 且 配色 >= 0.65`（留足两边余量）。

用法:
    python badge.py runs/m0_r006.png                 # 整图扫，打印命中
    python badge.py runs/dice_ok_0.png --box 40 820 920 1120
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'templates', 'marks', 'recommendIcon__mid_ico_tuijian_0002.png')
# ⭐ 奖励行的「推荐」标记**不是**地图上那个 14x14 徽章，而是 `mid_ico_tuijian_0001`
#   （33x33 = **绿色方框 + 右上角一个小绿拇指**，游戏把它按 ~4.4 倍画在整格上 ⇒ 148px）。
#   2026-09-25 实机标定（用户指认「奖励行 4 格，大拇指在第 3 格」）：
#     第1格 形状0.113 / 第2格 0.315 / **第3格 0.745** / 第4格 0.289
#   ⇒ 噪声地板 ≤0.32、真标记 0.74，阈值 0.55 分得很开。
REWARD_TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'templates', 'marks', 'tj_mid_ico_tuijian_0001.png')
# ⚠ 2026-09-25 二次标定（把 6 张真实摇色子截图全打分）：
#   真标记恒为 **缩放 4.5、形状/配色 0.92~0.95**（dice_2 / dice_ok_*）；
#   而缩放 3.8 处会凑出 **0.55/0.55** 的噪声（dice_0/dice_1）——正好卡在旧阈值 0.55 上。
#   ⇒ 尺度收窄到 4.1~4.9、阈值提到 0.70（真 0.92+ / 噪声 ≤0.55，两边余量都够）
SCALE_K = 1.0        # ⭐ 分辨率系数（1080×1920 = 1.0 ✓ 由 apply_layout 设置 ✓）
REWARD_SCALES = [round(4.1 + 0.1 * i, 2) for i in range(9)]
REWARD_SHAPE_MIN = 0.70
REWARD_COLOR_MIN = 0.70
SHAPE_MIN = 0.70
COLOR_MIN = 0.65
GREEN_MIN = 0.25        # 绿像素 IoU 下限（红按钮=0，真标记 0.4+）


def load_tpl(path=TPL):
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def _ncc(a, b):
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    a = a - a.mean()
    b = b - b.mean()
    sa, sb = a.std(), b.std()
    if sa < 1e-6 or sb < 1e-6:
        return 0.0
    return float((a / sa * (b / sb)).mean())


def score_at(img, tpl, cx, cy, scale):
    """在 (cx,cy) 放一个 scale 倍的模板 -> (形状分, 配色分)"""
    th, tw = tpl.shape[:2]
    w, h = int(round(tw * scale)), int(round(th * scale))
    if w < 8 or h < 8:
        return 0.0, 0.0
    t = cv2.resize(tpl[:, :, :3].astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
    m = cv2.resize(tpl[:, :, 3], (w, h), interpolation=cv2.INTER_NEAREST) > 128
    if int(m.sum()) < 40:
        return 0.0, 0.0
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - h / 2.0))
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.shape[0] != h or sub.shape[1] != w:
        return 0.0, 0.0
    shape = _ncc(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)[m],
                 cv2.cvtColor(t.astype(np.uint8), cv2.COLOR_BGR2GRAY)[m])
    color = float(np.mean([_ncc(sub[:, :, i][m], t[:, :, i][m]) for i in range(3)]))
    return shape, color


def green_iou(img, tpl, cx, cy, scale):
    """绿像素掩码的 IoU —— 大拇目标记特有的「**绿框 + 绿拇指**」空间布局

    ⚠ 2026-09-25 加：光靠形状+配色，纯红圆角按钮（回放/自动跳过）也能凑到
      形状 0.83 / 配色 0.79 → 误判。红按钮**一个绿像素都没有**，IoU=0，直接排除。
    """
    th, tw = tpl.shape[:2]
    w, h = int(round(tw * scale)), int(round(th * scale))
    if w < 8 or h < 8:
        return 0.0
    t = cv2.resize(tpl[:, :, :3].astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
    m = cv2.resize(tpl[:, :, 3], (w, h), interpolation=cv2.INTER_NEAREST) > 128
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - h / 2.0))
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.shape[0] != h or sub.shape[1] != w:
        return 0.0

    def green_mask(a):
        b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        return (g >= r + 8) & (g >= b + 8)

    gm_t = green_mask(t) & m
    gm_s = green_mask(sub.astype(np.float32)) & m
    if int(gm_t.sum()) < 20:
        return 0.0
    inter = int((gm_t & gm_s).sum())
    union = int((gm_t | gm_s).sum())
    return inter / union if union else 0.0


def find_reward_mark(img, box=(40, 840, 1020, 1140), scales=None,
                     shape_min=REWARD_SHAPE_MIN, color_min=REWARD_COLOR_MIN, top=4):
    """找「奖励行里带小绿拇指的那一格」—— 摇色子「刷到大拇指装备就停」用这个

    模板 = `mid_ico_tuijian_0001`（绿框 + 右上角小绿拇指，~4.4 倍画在整格上）。
    返回 [(shape, color, cx, cy, scale)]，空列表 = 这一行没有推荐标记。
    ⚠ 别拿地图上那个 14x14 徽章（`mid_ico_tuijian_0002`）来认奖励行 —— 渲染不同，认不出来。
    """
    if not os.path.exists(REWARD_TPL):
        return []
    tpl = cv2.imdecode(np.fromfile(REWARD_TPL, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if tpl is None or tpl.ndim < 3:
        return []
    if scales is None:
        scales = [round(s * SCALE_K, 3) for s in REWARD_SCALES]
    box = tuple(int(round(v * SCALE_K)) for v in box)
    x0, y0, x1, y1 = box
    sub = img[y0:y1, x0:x1]
    cands = []
    for s in scales:
        th, tw = tpl.shape[:2]
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 20 or h < 20 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        # ⚠ 粗筛必须用**掩码 SQDIFF**（只比绿框那条线）：
        #   TM_CCOEFF_NORMED 会被框内的装备美术带偏（真位置只有 0.28，压根进不了候选）
        t = cv2.resize(tpl[:, :, :3].astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
        m = cv2.resize(tpl[:, :, 3], (w, h), interpolation=cv2.INTER_NEAREST)
        m = np.where(m > 128, 255, 0).astype(np.uint8)
        if int((m > 0).sum()) < 40:
            continue
        res = cv2.matchTemplate(sub.astype(np.float32), t, cv2.TM_SQDIFF, mask=m)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        r = res.copy()
        for _ in range(3):
            mn, _mx, loc, _ml = cv2.minMaxLoc(r)
            if mn > 1e11:
                break
            cands.append((1e6 - float(mn) / ((m > 0).sum() * 255.0 * 255.0), s,
                          loc[0] + w / 2.0 + x0, loc[1] + h / 2.0 + y0))
            ry, rx = max(0, loc[1] - h // 2), max(0, loc[0] - w // 2)
            r[ry:loc[1] + h // 2, rx:loc[0] + w // 2] = 1e12
    hits, seen = [], []
    for _pre, s, cx, cy in sorted(cands, reverse=True)[:30]:
        if any(abs(cx - a) < 60 * SCALE_K and abs(cy - b) < 60 * SCALE_K
                           for a, b in seen):
            continue
        best = (0.0, 0.0)
        for dx in (-6, -4, -2, 0, 2, 4, 6):
            for dy in (-6, -4, -2, 0, 2, 4, 6):
                sh, co = score_at(img, tpl, int(cx) + dx, int(cy) + dy, s)
                if sh + co > best[0] + best[1]:
                    best = (sh, co)
        seen.append((cx, cy))
        if best[0] >= shape_min and best[1] >= color_min:
            hits.append((best[0], best[1], int(cx), int(cy), s))
    hits.sort(key=lambda t: -(t[0] + t[1]))
    return hits[:top]


def find_badge(img, box=None, scales=None, shape_min=SHAPE_MIN, color_min=COLOR_MIN,
               green_min=GREEN_MIN, top=6):
    """-> [(shape, color, cx, cy, scale)]（三重判据都过才返回）"""
    if box:
        x0, y0, x1, y1 = box
        sub = img[y0:y1, x0:x1]
        ox, oy = x0, y0
    else:
        sub = img
        ox, oy = 0, 0
    tpl = load_tpl()
    scales = scales or [round(1.0 + 0.2 * i, 2) for i in range(21)]      # 1.0 ~ 5.0
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
    cands = []
    for s in scales:
        th, tw = tpl.shape[:2]
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 8 or h < 8 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(cv2.cvtColor(tpl[:, :, :3], cv2.COLOR_BGR2GRAY), (w, h),
                       interpolation=cv2.INTER_AREA).astype(np.float32)
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1, posinf=-1, neginf=-1)
        # 每个尺度取前几个局部峰做候选（粗筛，再算掩码三重判）
        r = res.copy()
        for _ in range(4):
            _mn, mx, _ml, loc = cv2.minMaxLoc(r)
            if mx < 0.35:
                break
            cands.append((float(mx), s, loc[0] + w / 2.0 + ox, loc[1] + h / 2.0 + oy))
            ry, rx = max(0, loc[1] - h // 2), max(0, loc[0] - w // 2)
            r[ry:loc[1] + h // 2, rx:loc[0] + w // 2] = -1
    hits = []
    seen = []
    for _pre, s, cx, cy in sorted(cands, reverse=True)[:60]:
        if any(abs(cx - a) < 20 and abs(cy - b) < 20 and abs(s - c) < 0.3 for a, b, c in seen):
            continue
        best = (0.0, 0.0, 0.0)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                sh, co = score_at(img, tpl, int(cx) + dx, int(cy) + dy, s)
                gi = green_iou(img, tpl, int(cx) + dx, int(cy) + dy, s)
                if sh + co + gi > best[0] + best[1] + best[2]:
                    best = (sh, co, gi)
        seen.append((cx, cy, s))
        if best[0] >= shape_min and best[1] >= color_min and best[2] >= green_min:
            hits.append((best[0], best[1], best[2], int(cx), int(cy), s))
    hits.sort(key=lambda t: -(t[0] + t[1] + t[2]))
    return hits[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--box', nargs=4, type=int)
    a = ap.parse_args()
    img = cv2.imdecode(np.fromfile(a.img, dtype=np.uint8), cv2.IMREAD_COLOR)
    hits = find_badge(img, box=a.box)
    print('%s：三重判命中 %d 个（形状>=%.2f 且 配色>=%.2f 且 绿IoU>=%.2f）'
          % (a.img, len(hits), SHAPE_MIN, COLOR_MIN, GREEN_MIN))
    for sh, co, gi, cx, cy, s in hits:
        print('   形状 %.3f 配色 %.3f 绿IoU %.3f  位置 (%d,%d) 缩放 %.2f'
              % (sh, co, gi, cx, cy, s))


if __name__ == '__main__':
    main()
