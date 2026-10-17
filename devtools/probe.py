# -*- coding: utf-8 -*-
"""probe.py · 拿一张截图跑一遍 mapbot 的识别逻辑，把结果写成 UTF-8 JSON

用途：不碰设备即可回归「识别层」——红X弹窗检测 / 棋盘分类 / 面板品质采样。
    python probe.py runs/see_now.png out.json
"""
import json
import os
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
# ⚠ 业务模块已移进 `core/`（2026-10-17 目录整理）⇒ 也要能 import 到
CORE = _os.path.join(ROOT, "core")          # _MGAS_CORE_ADDED
if CORE not in _sys.path:
    _sys.path.insert(0, CORE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np

from mapbot import Bot
from explore_loop import (GRID, classify_cells, close_red_x_panels,
                          _title_quality, _action_btn, exact_btn, find_btn,
                          pick_btn)



def red_x_blobs(img, y0=180, y1=300, band_only=True):
    """与 close_red_x_panels 同一套阈值，但把命中的块全部列出来（含被尺寸过滤掉的）

    band_only=False 时全屏扫描（y0/y1 忽略）——用于评估「放宽扫描区」的误报率
    """
    b_, g_, r_ = cv2.split(img.astype(int))
    red = ((r_ > 150) & (r_ - g_ > 70) & (r_ - b_ > 60))
    m = red.astype(np.uint8) * 255
    if band_only:
        band = np.zeros_like(red)
        band[y0:y1, :] = True
        m = (red & band).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        keep = 1500 < a < 8000 and 40 < w < 110 and 40 < h < 110
        out.append({'cx': int(cents[i][0]), 'cy': int(cents[i][1]), 'x': int(x),
                    'y': int(y), 'w': int(w), 'h': int(h), 'area': int(a),
                    'pass_filter': bool(keep)})
    return out


def cell_grid(img):
    """35 格逐格的 gray/light 占比（排查「明明有石板格却没被认出来」）"""
    out = []
    for rr in range(GRID['rows']):
        row = []
        for cc in range(GRID['cols']):
            cx = int(GRID['x0'] + (cc + 0.5) * GRID['cx'])
            cy = int(GRID['y0'] + (rr + 0.5) * GRID['cy'])
            win = img[cy-35:cy+35, cx-45:cx+45]
            b, g, r = cv2.split(win)
            ri, gi, bi = r.astype(int), g.astype(int), b.astype(int)
            gray = ((r >= 125) & (r <= 175) & (abs(ri - gi) < 16) & (abs(gi - bi) < 16))
            light = ((r >= 235) & (g >= 185) & (bi >= 105) & (bi <= 220))
            row.append({'cx': cx, 'cy': cy,
                        'fg': round(float(gray.mean()), 2),
                        'fl': round(float(light.mean()), 2),
                        'rgb': [int(v) for v in (r.mean(), g.mean(), b.mean())]})
        out.append(row)
    return out


def main():
    png = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(png)[0] + '_probe.json'
    img = cv2.imdecode(np.fromfile(png, dtype=np.uint8), cv2.IMREAD_COLOR)

    b = Bot.__new__(Bot)          # 不连设备
    b.log_prefix = 'probe'
    cells = classify_cells(img, bot=b)
    from mapbot import _ocr
    tmp = os.path.join(os.path.dirname(png) or '.', '_probe_ocr.png')
    cv2.imencode('.png', img)[1].tofile(tmp)
    res, _ = _ocr()(tmp)
    items = []
    for it in (res or []):
        box, txt, conf = it[0], it[1], it[2]
        if conf < 0.35:
            continue
        xs = [q[0] for q in box]
        ys = [q[1] for q in box]
        items.append({'text': txt.strip(), 'cx': int(sum(xs) / 4), 'cy': int(sum(ys) / 4),
                      'x0': int(min(xs)), 'y0': int(min(ys)),
                      'x1': int(max(xs)), 'y1': int(max(ys)), 'conf': round(float(conf), 3)})
    items.sort(key=lambda d: (d['cy'], d['cx']))

    q_fight, info_fight = _title_quality(img, items, '战斗事件')
    q_expl, info_expl = _title_quality(img, items, '探索产出')
    rep = {
        'png': png,
        'red_x_blobs': red_x_blobs(img),
        'red_x_full': red_x_blobs(img, band_only=False),
        'cells': {
            'gray': [[c[0], c[1], c[2]] for c in cells['gray']],
            'light': [[c[0], c[1], c[2]] for c in cells['light']],
        },
        'cell_grid': cell_grid(img),
        'panel': {
            'has_战斗事件': bool(find_btn(items, '战斗事件')),
            'has_探索产出': bool(find_btn(items, '探索产出')),
            'action_战斗': _action_btn(items, '战斗', exclude='战斗事件'),
            'action_探索': _action_btn(items, '探索', exclude='探索产出'),
            'exact_结束冒险': exact_btn(items, '结束冒险'),
            'exact_确定': exact_btn(items, '确定'),
            'exact_取消': exact_btn(items, '取消'),
            'quality_战斗事件': q_fight, 'info_战斗事件': info_fight,
            'quality_探索产出': q_expl, 'info_探索产出': info_expl,
        },
        'ocr': items,
    }
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print('PROBE:', out)


if __name__ == '__main__':
    main()
