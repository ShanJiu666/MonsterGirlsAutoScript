# -*- coding: utf-8 -*-
"""诊断8: 对全部灰格逐个 tap, 记录哪些能揭开 -> 找可揭格的分布规律"""
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
from mapbot import Bot
from explore_loop import classify_cells, diff_at, exact_btn, GRID


b = Bot(log_prefix='diag8')

b.snap('d8_pre')
items = b.ocr()
if not exact_btn(items, '结束冒险'):
    print('NOT IN MAP - 请先手动进图')
    sys.exit(1)

b.snap('d8_start')
img0 = b.img()
cells = classify_cells(img0, bot=b)
grays = [(c[0], c[1]) for c in cells['gray']]
print('start gray=%d light=%d' % (len(cells['gray']), len(cells['light'])))

results = []
for i, (cx, cy) in enumerate(grays):
    b.tap(cx, cy, wait=1.6)
    b.snap()
    d = diff_at(img0, b.img(), cx, cy)
    ok = d > 0.3
    # 网格坐标
    col = round((cx - GRID['x0']) / GRID['cx'] - 0.5)
    row = round((cy - GRID['y0']) / GRID['cy'] - 0.5)
    results.append((row, col, cx, cy, round(d, 3), ok))
    print('r%d c%d (%4d,%4d) diff=%.3f %s' % (row, col, cx, cy, d, 'HIT' if ok else ''))
    img0 = b.img()   # 用最新图做下次基线
    cells = classify_cells(img0, bot=b)
    if not cells['gray']:
        print('all gray cleared at i=%d' % i)
        break

b.snap('d8_end')
cells2 = classify_cells(b.img(), bot=b)
print('end gray=%d light=%d' % (len(cells2['gray']), len(cells2['light'])))
hits = [r for r in results if r[5]]
print('HIT rows:', sorted(set(r[0] for r in hits)))
print('HIT cols:', sorted(set(r[1] for r in hits)))
