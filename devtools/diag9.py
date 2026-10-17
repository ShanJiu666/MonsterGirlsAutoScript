# -*- coding: utf-8 -*-
"""诊断9: 新图全灰点不动的排查 - 配队/tab1/点击light格 逐步试"""
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
from mapbot import Bot
from explore_loop import classify_cells, diff_at, exact_btn


b = Bot(log_prefix='diag9')


def dump(tag):
    b.snap(tag)
    items = b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        if it['cy'] < 950:
            print("  %-22s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))
    return items


dump('d9_0_state')
cells = classify_cells(b.img(), bot=b)
print('gray=%d light=%d light:%s' % (len(cells['gray']), len(cells['light']),
                                     [(c[0], c[1], c[2]) for c in cells['light']]))

# 1) 点一个 light gold 格试试
if cells['light']:
    lx, ly = cells['light'][0][0], cells['light'][0][1]
    img0 = b.img()
    b.tap(lx, ly, wait=2)
    b.snap('d9_1_light_tap')
    print('light tap (%d,%d) diff=%.3f' % (lx, ly, diff_at(img0, b.img(), lx, ly)))
    dump('d9_1_after')
    # 关闭可能弹出的面板
    from explore_loop import close_red_x_panels
    close_red_x_panels(b)

# 2) 点 tab1 (队伍1)
b.tap(75, 940, wait=2)
dump('d9_2_tab1')

# 3) 点「配队」按钮 (976,767)
b.tap(976, 767, wait=2.5)
dump('d9_3_team_btn')

# 4) 若出现新界面, 找「出战/上阵/出发」类按钮
items = b.ocr()
for kw in ('出战', '上阵', '出发', '开始探索', '确认'):
    hit = [it for it in items if kw in it['text']]
    if hit:
        print('>>> found %s: %s' % (kw, [(h['cx'], h['cy']) for h in hit]))
