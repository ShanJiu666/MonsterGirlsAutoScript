# -*- coding: utf-8 -*-
"""bench: 量化各步骤耗时, 找瓶颈(目标 1 分钟/图)"""
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
from explore_loop import classify_cells, diff_at


b = Bot(log_prefix='bench')

N = 6


def bench(name, fn):
    ts = []
    for _ in range(N):
        t0 = time.time()
        fn()
        ts.append(time.time() - t0)
    ts.sort()
    print('%-28s  min=%.3fs  med=%.3fs  max=%.3fs' %
          (name, ts[0], ts[len(ts) // 2], ts[-1]))
    return ts[len(ts) // 2]


t_snap = bench('snapshot(airtest)', lambda: b.snap())
t_img = bench('img() 读盘+解码', lambda: b.img())
t_ocr_full = bench('OCR 全屏', lambda: b.ocr())
b.snap()
img = b.img()
h, w = img.shape[:2]
top = img[180:320, :]
bot = img[880:1080, :]
t_ocr_top = bench('OCR 裁剪(标题栏 y180-320)', lambda: b.ocr(img=top))
t_ocr_bot = bench('OCR 裁剪(按钮区 y880-1080)', lambda: b.ocr(img=bot))
t_cls = bench('classify_cells(35格)', lambda: classify_cells(img, bot=b))
t_tap = bench('tap(wait=0.5)', lambda: b.tap(540, 300, wait=0.5))
t_adb_tap = bench('tap(wait=0)', lambda: b.tap(540, 1300, wait=0))
t_diff = bench('diff_at(局部)', lambda: diff_at(img, img, 540, 1300))

print()
print('--- 单张图估算 ---')
n_cells = 35
n_popup = 15
per_cell = t_tap + t_snap + 0.02
per_popup = t_snap + t_ocr_top + t_ocr_bot + t_tap + t_adb_tap + 0.3
print('每格点击(含截图): %.2fs x %d = %.0fs' % (per_cell, n_cells, per_cell * n_cells))
print('每个弹窗:        %.2fs x %d = %.0fs' % (per_popup, n_popup, per_popup * n_popup))
print('合计:            %.0fs' % (per_cell * n_cells + per_popup * n_popup))
