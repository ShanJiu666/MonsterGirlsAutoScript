# -*- coding: utf-8 -*-
"""grid_detect.py · 从截图**自动检测**棋盘几何（x0, y0, cx, cy）—— 分辨率无关的关键 ✓

原理
----
地图由 5×7 个地块拼成，地块之间有明显边界（美术/描边差异 ✓）
⇒ 对棋盘区域求**梯度投影**（沿 x 投影得到竖边、沿 y 投影得到横边 ✓）
⇒ 投影上会出现**等间距的峰** ⇒ 峰间距 = 格距 ✓、峰相位 = 原点 ✓

用法
----
    from grid_detect import detect_grid
    g = detect_grid(img)                 # 全自动 ✓
    g = detect_grid(img, hint={'x0':24,'y0':668,'cx':96,'cy':96})   # 给个先验更快更稳 ✓（720p 基准）
返回 {'x0','y0','cx','cy','conf','src'} ✓（conf 低时调用方应保留先验值 ✓）
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except Exception:       # noqa: BLE001
    cv2 = None


def _profile(roi_gray, axis):
    """梯度投影：axis=0 → 沿列求和（得到竖边的 x 位置 ✓）；axis=1 → 横边 ✓"""
    g = roi_gray.astype(np.float32)
    if cv2 is not None:
        if axis == 0:
            gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
            prof = np.abs(gx).sum(axis=0)
        else:
            gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
            prof = np.abs(gy).sum(axis=1)
    else:                                   # 退化实现（无 cv2 时 ✓）
        d = np.abs(np.diff(g, axis=1)).sum(axis=0) if axis == 0 else \
            np.abs(np.diff(g, axis=0)).sum(axis=1)
        prof = np.concatenate([d, d[-1:]])
    # 去掉直流 + 平滑
    prof = prof - prof.mean()
    k = max(3, int(len(prof) * 0.004) | 1)
    ker = np.ones(k, np.float32) / k
    prof = np.convolve(prof, ker, mode='same')
    return prof


def _best_period(prof, lo, hi, step=0.25):
    """梳状滤波评分：score = 格线处均值 − 中点处均值 ✓（只有真周期才高 ✓）"""
    n = len(prof)
    best = (None, -1e9)
    p = lo
    while p <= hi + 1e-9:
        m = int(np.floor((n - 1) / p))
        if m < 4:
            p += step
            continue
        base = np.arange(m) * p
        line_best, mid_best = -1e9, 1e9
        for ph in range(0, max(1, int(round(p)))):
            li = (base + ph).astype(np.int32)
            li = li[li < n]
            if len(li) < 4:
                continue
            mi = (base + ph + p / 2.0).astype(np.int32)
            mi = mi[mi < n]
            if len(mi) < 3:
                continue
            lv = float(prof[li].mean())
            mv = float(prof[mi].mean())
            if lv > line_best:
                line_best = lv
                mid_best = mv
        sc = line_best - mid_best          # 梳状对比 ✓
        if sc > best[1]:
            best = (p, sc)
        p += step
    return best


def detect_grid(img, hint=None, verbose=False):
    """返回 {'x0','y0','cx','cy','conf','src'} ✓"""
    if img is None:
        return None
    h, w = img.shape[:2]
    gray = img[:, :, :3] if (img.ndim == 3 and img.shape[2] >= 3) else img
    if gray.ndim == 3 and cv2 is not None:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    # ① 棋盘大致区域：优先用先验 ✓，否则按屏幕比例猜（竖屏地图在屏幕中下部 ✓）
    if hint:
        cx0 = float(hint.get('cx', w * 0.13333))
        cy0 = float(hint.get('cy', h * 0.075))
        x0 = float(hint.get('x0', cx0 / 4))
        y0 = float(hint.get('y0', h * 0.52))
        rx0 = int(max(0, x0 - cx0))
        rx1 = int(min(w, x0 + 7 * cx0 + cx0))
        ry0 = int(max(0, y0 - cy0))
        ry1 = int(min(h, y0 + 5 * cy0 + cy0))
        guess = (cx0, cy0)
    else:
        rx0, rx1 = int(w * 0.02), int(w * 0.98)
        ry0, ry1 = int(h * 0.30), int(h * 0.95)
        guess = (w * 0.13333, h * 0.075)      # 参考布局实测比例 ✓

    roi = gray[ry0:ry1, rx0:rx1]
    if roi.size < 1000:
        return None

    # ② 找周期（在猜测值 ±35% 范围内 ✓）
    px = _profile(roi, 0)
    py = _profile(roi, 1)
    bx, sx = _best_period(px, guess[0] * 0.88, guess[0] * 1.12)
    by, sy = _best_period(py, guess[1] * 0.88, guess[1] * 1.12)
    if not bx or not by:
        return None

    # ③ 定相位（原点 ✓）：让格线落在投影的峰上
    def phase(prof, period, first_hint):
        n = len(prof)
        m = int(np.floor((n - 1) / period))
        best, bv = 0, -1e9
        for ph in range(0, max(1, int(round(period)))):
            ii = (np.arange(m) * period).astype(np.int32) + ph
            ii = ii[ii < n]
            if len(ii) < 3:
                continue
            v = float(prof[ii].mean())
            if v > bv:
                bv, best = v, ph
        return best

    phx = phase(px, bx, None)
    phy = phase(py, by, None)
    x0 = rx0 + phx + bx          # 第一条**内部**格线 ≈ x0 + cx ⇒ 原点 = 格线 - 格距 ✓
    y0 = ry0 + phy + by
    # 归一化到"第 1 格左上角"（参考布局里 x0=36 就是左上角 ✓）
    x0 -= bx
    y0 -= by

    # ④ 置信度：格线上的投影均值 / 全体的标准差
    def conf(prof, period, ph):
        n = len(prof)
        m = int(np.floor((n - 1) / period))
        ii = (np.arange(m) * period).astype(np.int32) + ph
        ii = ii[ii < n]
        if len(ii) < 3:
            return 0.0
        s = prof.std() + 1e-6
        return float(prof[ii].mean() / s)

    cxf, cyf = conf(px, bx, phx), conf(py, by, phy)
    res = {'x0': int(round(x0)), 'y0': int(round(y0)),
           'cx': float(round(bx, 2)), 'cy': float(round(by, 2)),
           'conf': float(round(min(cxf, cyf), 3)), 'src': 'detect'}
    if verbose:
        print('检测: x0=%d y0=%d cx=%.2f cy=%.2f conf=%.3f'
              % (res['x0'], res['y0'], res['cx'], res['cy'], res['conf']))
    return res


def verify_on_frames(paths, hint=None, tol=6):
    """在一批**已知 720×1280** 的帧上验证检测结果（应接近 (24,668,96,96) ✓）"""
    import os

    import numpy as np

    try:
        from spots import imread
    except Exception:       # noqa: BLE001
        def imread(p):
            return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

    # ⚠ 2026-10-02 换基准：默认先验改为 **720p 基准** (24,668,96,96)
    #   并从 `spots.GRID` 取（单一数据源，避免两处漂移）
    if hint is None:
        try:
            from spots import GRID as _G
            hint = {'x0': _G['x0'], 'y0': _G['y0'],
                    'cx': _G.get('cx') or _G.get('pitch'),
                    'cy': _G.get('cy') or _G.get('pitch')}
        except Exception:       # noqa: BLE001
            hint = {'x0': 24, 'y0': 668, 'cx': 96, 'cy': 96}
    ok = 0
    print('%-28s %-34s %s' % ('帧', '检测结果', '与真值误差'))
    for p in paths:
        if not os.path.exists(p):
            continue
        img = imread(p)
        if img is None:
            continue
        r = detect_grid(img, hint=hint)
        if not r:
            print('%-28s 检测失败 ✗' % os.path.basename(p))
            continue
        dx = abs(r['x0'] - hint['x0'])
        dy = abs(r['y0'] - hint['y0'])
        dcx = abs(r['cx'] - hint['cx'])
        dcy = abs(r['cy'] - hint['cy'])
        good = (dcx <= tol and dcy <= tol)
        ok += 1 if good else 0
        print('%-28s x0=%-5d y0=%-5d cx=%-7.2f cy=%-7.2f conf=%.2f   Δx0=%-3d Δy0=%-3d Δcx=%-5.2f Δcy=%-5.2f %s'
              % (os.path.basename(p), r['x0'], r['y0'], r['cx'], r['cy'], r['conf'],
                 dx, dy, dcx, dcy, '✓' if good else '✗'))
    print('格距误差 ≤%dpx 的帧: %d 个 ✓' % (tol, ok))
    return ok


if __name__ == '__main__':
    import glob
    import os
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    paths = sys.argv[1:] or (
        glob.glob(os.path.join(HERE, 'runs', 'acc2', '*.png'))[:3] +
        glob.glob(os.path.join(HERE, 'runs', 'm*_r00*.png'))[:3] +
        [os.path.join(HERE, 'runs', 'findA3.png')])
    verify_on_frames(paths)

def calibrate(img, code='S00003', hint=None, verbose=False):
    """用**分类器分数**标定棋盘原点 (x0,y0) ✓（格距用投影检测的 cx/cy ✓）

    返回 {'x0','y0','cx','cy','conf','score','src':'calibrate'} ✓
    """
    import spots as SP
    det = detect_grid(img, hint=hint)
    if not det:
        return None
    cx, cy = det['cx'], det['cy']
    hx = (hint or {}).get('x0', det['x0'])
    hy = (hint or {}).get('y0', det['y0'])

    def score(x0, y0):
        try:
            g = {'x0': int(round(x0)), 'y0': int(round(y0)), 'cx': cx, 'cy': cy,
                 'cols': 7, 'rows': 5}
            st = SP.Board(code, grid=g).state(img)
            vals = sorted((v.get('score') or 0) for v in (st or {}).values())
            top = vals[-10:] if len(vals) >= 10 else vals
            return sum(top) / max(1, len(top))
        except Exception:       # noqa: BLE001
            return 0.0

    cands = []
    for dx in (-int(cx / 3), 0, int(cx / 3)):
        for dy in (-int(cy / 3), 0, int(cy / 3)):
            cands.append((hx + dx, hy + dy))
    best = max(cands, key=lambda c: score(*c))
    # 二轮细化：±cx/6 内再试一轮 ✓
    fine = []
    for dx in (-int(cx / 6), 0, int(cx / 6)):
        for dy in (-int(cy / 6), 0, int(cy / 6)):
            fine.append((best[0] + dx, best[1] + dy))
    best2 = max([best] + fine, key=lambda c: score(*c))
    sc = score(*best2)
    # ⭐ 一致性闸（2026-09-27）：标定结果必须与先验"同一套格子" ✓
    #   实测 720p 曾把 x0 从 24 挪到 -27（Δ51px > 半格 48px ✗）⇒ 之后点格子整体偏移 ✗
    hx0 = hx
    hy0 = hy
    # ⚠ 1/3 格（实测 1/2 格时 51 vs 51.5 擦边漏过 ✗）
    if abs(best2[0] - hx0) > cx / 3.0 or abs(best2[1] - hy0) > cy / 3.0:
        if verbose:
            print('标定被拒（偏差 %.0f/%.0f px 超过半格 %.0f/%.0f）'
                  % (abs(best2[0] - hx0), abs(best2[1] - hy0), cx * 0.5, cy * 0.5))
        return {'x0': int(hx0), 'y0': int(hy0), 'cx': cx, 'cy': cy,
                'conf': det['conf'], 'score': None, 'src': 'rejected_shift'}
    out = {'x0': int(best2[0]), 'y0': int(best2[1]), 'cx': cx, 'cy': cy,
           'conf': det['conf'], 'score': round(float(sc), 4), 'src': 'calibrate'}
    if verbose:
        print('标定: x0=%d y0=%d cx=%.2f cy=%.2f 识别均分=%.4f（投影初值 x0=%d y0=%d）'
              % (out['x0'], out['y0'], cx, cy, sc, det['x0'], det['y0']))
    return out
