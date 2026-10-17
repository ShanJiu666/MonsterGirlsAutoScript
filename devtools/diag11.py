# -*- coding: utf-8 -*-
"""诊断11: 取消退出弹窗, 查看棋盘真实状态"""
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
from explore_loop import classify_cells


b = Bot(log_prefix='diag11')

b.snap('d11_0')
items = b.ocr()
cancel = [it for it in items if it['text'] == '取消']
confirm = [it for it in items if it['text'] == '确定']
print('取消:', [(c['cx'], c['cy']) for c in cancel])
print('确定:', [(c['cx'], c['cy']) for c in confirm])
if cancel:
    b.tap(cancel[0]['cx'], cancel[0]['cy'], wait=2)
    print('>>> 已点取消')

b.snap('d11_1_after_cancel')
items = b.ocr()
# 确认没有退出弹窗了
assert not any('退出游戏' in it['text'] for it in items), '弹窗还在!'

# 当前界面 dump
print('=== current ===')
for it in items:
    if it['cy'] < 950:
        print("  %-22s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))

cells = classify_cells(b.img(), bot=b)
print('gray=%d light=%d' % (len(cells['gray']), len(cells['light'])))
print('light:', [(c[0], c[1], c[2]) for c in cells['light']])
