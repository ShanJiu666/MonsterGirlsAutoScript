# -*- coding: utf-8 -*-
"""诊断10: 验证「点已揭开沙地格 -> 连通消除推进」机制"""
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
from explore_loop import (classify_cells, diff_at, exact_btn,
                          close_red_x_panels, pick_btn)


b = Bot(log_prefix='diag10')

# 0) 关闭可能开着的「配置队伍」面板: 先试红X, 再试返回
b.snap('d10_0')
items = b.ocr()
if any('配置队伍' in it['text'] for it in items):
    # 配置队伍面板: 点左上角返回(X) - 一般在 (60,310) 附近或屏幕左上
    for pos in [(63, 314), (1000, 314), (63, 250)]:
        b.tap(*pos, wait=2)
        items = b.ocr()
        if not any('配置队伍' in it['text'] for it in items):
            print('closed team panel at', pos)
            break
    else:
        # 用系统返回键
        from airtest.core.api import keyevent
        keyevent('BACK')
        time.sleep(2)
        print('pressed BACK')
close_red_x_panels(b)
b.snap('d10_1_clean')
print('gray=%d light=%d' % (len(classify_cells(b.img(), bot=b)['gray']),
                            len(classify_cells(b.img(), bot=b)['light'])))

# 1) 逐个点 light 格, 观察 gray 是否减少
for rnd in range(6):
    b.snap()
    img = b.img()
    cells = classify_cells(img, bot=b)
    print('--- round %d: gray=%d light=%d' % (rnd, len(cells['gray']), len(cells['light'])))
    print('    light:', [(c[0], c[1], c[2]) for c in cells['light']])
    if not cells['light']:
        print('no light left')
        break
    # 优先点 'none'(空沙地), 再 gold
    cands = [c for c in cells['light'] if c[2] == 'none'] or cells['light']
    cx, cy, q = cands[0]
    b.tap(cx, cy, wait=2.2)
    b.snap('d10_tap_%d' % rnd)
    img2 = b.img()
    print('    tap(%d,%d,%s) diff=%.3f' % (cx, cy, q, diff_at(img, img2, cx, cy)))
    items2 = b.ocr()
    popup = [it for it in items2 if it['text'] in ('探索产出', '战斗事件') or '产出' in it['text']]
    if popup:
        print('    POPUP:', popup[0]['text'])
        close_red_x_panels(b)
    time.sleep(1)

b.snap('d10_final')
cells_f = classify_cells(b.img(), bot=b)
print('final gray=%d light=%d' % (len(cells_f['gray']), len(cells_f['light'])))
