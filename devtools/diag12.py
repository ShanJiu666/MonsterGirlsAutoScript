# -*- coding: utf-8 -*-
"""诊断12: 进图后详细盘点棋盘 - 每格颜色采样 + 找 boss/紫色地块 + 领奖线索"""
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
from mapbot import Bot
from explore_loop import (classify_cells, exact_btn, enter_map, GRID,
                          _quality_from_rgb)


b = Bot(log_prefix='diag12')

b.snap('d12_pre')
items = b.ocr()
if not exact_btn(items, '结束冒险'):
    if not enter_map(b, []):
        print('ENTER FAILED')
        sys.exit(1)
    time.sleep(4)

b.snap('d12_in_map')
img = b.img()
print('=== 界面 OCR (cy<950) ===')
for it in b.ocr():
    if it['cy'] < 950:
        print("  %-22s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))

cells = classify_cells(img, bot=b)
print('gray=%d light=%d' % (len(cells['gray']), len(cells['light'])))

print('=== 35 格逐格采样 (均值RGB + 品质) ===')
for rr in range(GRID['rows']):
    line = []
    for cc in range(GRID['cols']):
        cx = int(GRID['x0'] + (cc + 0.5) * GRID['cx'])
        cy = int(GRID['y0'] + (rr + 0.5) * GRID['cy'])
        win = img[cy-35:cy+35, cx-45:cx+45]
        bb, gg, rr_ = cv2.split(win.astype(int))
        r, g, bl = int(rr_.mean()), int(gg.mean()), int(bb.mean())
        q = _quality_from_rgb(r, g, bl)
        # 找该格内最"紫"的像素(用于识别紫色地块图标)
        purple_px = int(((rr_ > 120) & (rr_ < 210) & (bb > 170) &
                         (bb - gg > 40) & (rr_ - gg > 20)).mean() * 100)
        line.append('r%dc%d(%3d,%3d,%3d)%s%s' % (
            rr, cc, r, g, bl, ('/' + q[:2]) if q != 'unknown' else '/--',
            ('P%d' % purple_px) if purple_px > 3 else ''))
    print('  ' + ' | '.join(line))
