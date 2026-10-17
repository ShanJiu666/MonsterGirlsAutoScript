# -*- coding: utf-8 -*-
"""diag_boss.py · 采样「首领地块」的战斗面板（定位它的「开始战斗」按钮）

用户口径（2026-09-24）：boss 格的开始战斗位置和普通格不一样。
做法：进图 -> 扫标记 -> 点标记格 -> 若弹出「战斗事件」面板就**不点任何按钮**，
      把整块面板 OCR 全量 + 字符化色块图落盘，用来量按钮坐标。
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
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）
import time

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np
import marks as marks_mod
from mapbot import Bot, RUNS
from explore_loop import (classify_cells, enter_map, find_btn, in_map,
                          _action_btn, cell_of)


OUT = os.path.join(RUNS, 'diag_boss.json')
PAL = {'R': (200, 80, 80), 'O': (240, 170, 90), 'Y': (250, 240, 120),
       'G': (140, 220, 140), 'B': (120, 160, 230), 'W': (240, 240, 240)}


def color_map(img, x0, y0, x1, y1, cell=20):
    lines = []
    for yy in range(y0, y1 - cell + 1, cell):
        row = ''
        for xx in range(x0, x1 - cell + 1, cell):
            w = img[yy:yy + cell, xx:xx + cell].astype(int)
            b, g, r = [int(v.mean()) for v in cv2.split(w)]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 70:
                row += '#'
            elif mx - mn < 40:
                row += 'w' if mx > 180 else '.'
            else:
                best, bd = '.', 1e9
                for k, (pr, pg, pb) in PAL.items():
                    d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                    if d < bd:
                        bd, best = d, k
                row += best if bd < 9000 else '.'
        lines.append('%4d %s' % (yy, row))
    return lines


def main():
    b = Bot(log_prefix='db')
    log = []
    b.snap('db0')
    items = b.ocr()
    if not in_map(b, b.img(), items):
        if not enter_map(b, log):
            print('ENTER FAILED')
            return
    time.sleep(3)

    for rnd in range(18):
        b.snap('db_r%02d' % rnd)
        img = b.img()
        items = b.ocr()
        mk = marks_mod.scan_board(img)
        log.append({'round': rnd, 'marks': {'%d,%d' % k: v['marks'] for k, v in mk.items()}})
        if find_btn(items, '战斗事件'):
            # 面板已开：全量落盘，立即停手
            pitems = b.ocr(min_conf=0.3)
            cv2.imencode('.png', img)[1].tofile(os.path.join(RUNS, 'db_panel.png'))
            log.append({'panel_ocr': [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy'],
                                       'conf': i['conf']} for i in pitems]})
            # 左右两列面板都给色块图（找橙色艺术字按钮）
            log.append({'colormap_left': color_map(img, 20, 180, 530, 820, 20)})
            log.append({'colormap_right': color_map(img, 550, 180, 1060, 820, 20)})
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(log, f, ensure_ascii=False, indent=1)
            print('DIAG:', OUT, '（面板已保存 runs/db_panel.png）')
            return
        if mk:
            cell = sorted(mk.keys())[0]
            cx, cy = marks_mod.cell_center(*cell)
            log.append({'tap_marked': cell, 'marks': mk[cell]['marks'], 'at': [cx, cy]})
            b.tap(cx, cy, wait=3)
            b.snap('db_after_mark')
            if find_btn(b.ocr(), '战斗事件'):
                continue
            log.append({'tap_marked': 'no_panel -> 需要先解锁'})
        cells = classify_cells(img, bot=b)
        nones = [(c[0], c[1]) for c in cells['light'] if c[2] == 'none']
        if mk and nones:
            tgt = [marks_mod.cell_center(*k) for k in mk]
            nones.sort(key=lambda p: min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in tgt))
        if nones:
            b.tap(nones[0][0], nones[0][1], wait=2.5)
            log.append({'reveal': nones[0]})
        else:
            log.append({'reveal': 'none_left', 'gray': len(cells['gray'])})
            break

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print('DIAG(未遇到面板):', OUT)


if __name__ == '__main__':
    main()
