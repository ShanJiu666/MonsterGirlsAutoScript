# -*- coding: utf-8 -*-
"""probe_hit.py · 试点击：对每个候选坐标 抓图→点→抓图→比对，看哪个真的有反应

用法:
    python probe_hit.py 539,1033 896,1466 251,746
    python probe_hit.py 539,1033 --wait 2 --box 120,600,980,1460
"""
import argparse
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
from mapbot import Bot, RUNS



def snap_img(b, tag):
    b.snap(tag)
    return b.img()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('points', nargs='+')
    ap.add_argument('--wait', type=float, default=1.6)
    ap.add_argument('--box', default='0,0,1080,1920')
    a = ap.parse_args()
    x0, y0, x1, y1 = [int(v) for v in a.box.split(',')]
    b = Bot(log_prefix='ph')
    base = snap_img(b, 'ph_base')
    print('基准截图 ph_base.png  %s' % (base.shape,))
    for i, pt in enumerate(a.points):
        x, y = [int(v) for v in pt.split(',')]
        b.tap(x, y, wait=a.wait)
        cur = snap_img(b, 'ph_%d' % i)
        d = np.abs(cur.astype(int) - base.astype(int)).sum(axis=2)
        sub = d[y0:y1, x0:x1]
        n_all = int((d > 40).sum())
        n_box = int((sub > 40).sum())
        ys, xs = np.where(sub > 40)
        where = ''
        if len(ys):
            where = ' 变化区 x%d..%d y%d..%d' % (xs.min() + x0, xs.max() + x0,
                                                 ys.min() + y0, ys.max() + y0)
        print('点 (%4d,%4d): 全屏变化 %7d  框内 %6d%s' % (x, y, n_all, n_box, where))
        items = b.ocr(min_conf=0.5)
        ttl = [it['text'] for it in items if 320 < it['cy'] < 620]
        print('        标题带文字:', ttl[:6])
        base = cur
    return 0


if __name__ == '__main__':
    sys.exit(main())
