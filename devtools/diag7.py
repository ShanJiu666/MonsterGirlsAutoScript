# -*- coding: utf-8 -*-
"""诊断7: 灰石板格揭格交互实验 - tap/lp300/lp1200/偏移点 哪种有效"""
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
import time

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np
from mapbot import Bot
from explore_loop import lp, diff_at, classify_cells, enter_map, exact_btn


b = Bot(log_prefix='diag7')

# 先确保在地图里
b.snap('d7_pre')
items = b.ocr()
if not exact_btn(items, '结束冒险'):
    if not enter_map(b, []):
        print('ENTER FAILED')
        sys.exit(1)
    time.sleep(3)

b.snap('d7_in_map')
img0 = b.img()
cells = classify_cells(img0, bot=b)
print('gray=%d light=%d' % (len(cells['gray']), len(cells['light'])))
print('gray cells:', [(c[0], c[1]) for c in cells['gray']][:10])
print('light cells:', [(c[0], c[1], c[2]) for c in cells['light']])

# 取一个灰格做交互实验 (选一个没有大物件剪影的: 遍历前几个)
target = cells['gray'][0] if cells['gray'] else None
if not target:
    print('NO GRAY CELL')
    sys.exit(0)
cx, cy = target[0], target[1]
print('>>> 实验格:', cx, cy)

# 1) 中心 tap
b.tap(cx, cy, wait=2.0)
b.snap('d7_a_tap')
d = diff_at(img0, b.img(), cx, cy)
print('tap center: diff=%.3f' % d)

# 2) 中心 lp 300ms
b.snap('d7_b_pre')
img0b = b.img()
b.tap(cx, cy, wait=1.0)  # 无效化
lp(cx, cy, 300)
b.snap('d7_b_lp300')
print('lp300: diff=%.3f' % diff_at(img0b, b.img(), cx, cy))

# 3) lp 1200ms
img0c = b.img()
lp(cx, cy, 1200)
b.snap('d7_c_lp1200')
print('lp1200: diff=%.3f' % diff_at(img0c, b.img(), cx, cy))

# 4) 偏移点 (左下角, 避开中心物件)
for dx, dy, tag in [(-55, 45, 'bl'), (55, -45, 'tr'), (0, 60, 'bc'), (-55, -45, 'tl')]:
    img0d = b.img()
    x, y = cx + dx, cy + dy
    b.tap(x, y, wait=1.5)
    b.snap('d7_d_%s' % tag)
    print('tap offset %s(%+d,%+d): diff=%.3f' % (tag, dx, dy, diff_at(img0d, b.img(), cx, cy)))
    lp(x, y, 600)
    b.snap('d7_e_%s' % tag)
    print('  +lp600: diff=%.3f' % diff_at(img0d, b.img(), cx, cy))

# 最终棋盘状态
b.snap('d7_final')
cells2 = classify_cells(b.img(), bot=b)
print('after: gray=%d light=%d' % (len(cells2['gray']), len(cells2['light'])))
