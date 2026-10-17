# -*- coding: utf-8 -*-
"""ascii_img.py · 把截图区域转成文字图（我看不了图片，靠这个"看"）

用法:
    python ascii_img.py runs/x.png --box 300 600 800 1400 --cols 60 --rows 30
    python ascii_img.py runs/x.png --box 0 0 1080 1920 --cols 80 --rows 40 --mode edge
    python ascii_img.py runs/x.png --box ... --mode color
模式：luma（默认，亮度）| edge（边缘，看网格线）| color（主色字母）
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

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np
from spots import imread


LUMA = ' .:-=+*#%@'


def render_luma(g):
    lo, hi = float(g.min()), float(g.max())
    rng = max(1e-6, hi - lo)
    out = []
    for row in g:
        out.append(''.join(LUMA[min(9, int((v - lo) / rng * 10))] for v in row))
    return out


def render_edge(g):
    g = g.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    hi = float(np.percentile(mag, 99)) or 1.0
    out = []
    for row in mag:
        out.append(''.join('#' if v > hi * 0.35 else ('+' if v > hi * 0.15 else
                                                      ('.' if v > hi * 0.05 else ' ')) for v in row))
    return out


PALETTE = [('沙黄', (255, 236, 179), 'a'), ('棕', (150, 100, 60), 'n'),
           ('金', (240, 200, 80), 'Y'), ('白', (245, 245, 245), 'W'),
           ('红', (200, 70, 60), 'R'), ('绿', (90, 180, 90), 'G'),
           ('蓝', (80, 140, 220), 'B'), ('紫', (160, 100, 200), 'P'),
           ('深灰', (70, 70, 70), ':'), ('中灰', (130, 130, 130), '-'),
           ('浅灰', (200, 200, 200), '+')]


def render_color(img):
    out = []
    for row in img:
        line = ''
        for px in row:
            b, g, r = [float(v) for v in px]
            best, bd = '?', 1e18
            for _nm, (pr, pg, pb), ch in PALETTE:
                d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if d < bd:
                    bd, best = d, ch
            line += best
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--box', nargs=4, type=int, required=True)
    ap.add_argument('--cols', type=int, default=60)
    ap.add_argument('--rows', type=int, default=30)
    ap.add_argument('--mode', default='luma', choices=['luma', 'edge', 'color'])
    a = ap.parse_args()
    img = imread(a.img, cv2.IMREAD_COLOR)
    if img is None:
        print('读不到图', a.img)
        return 1
    x0, y0, x1, y1 = a.box
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        print('空区域')
        return 1
    small = cv2.resize(sub, (a.cols, a.rows), interpolation=cv2.INTER_AREA)
    print('%s  box=%s  %dx%d -> %dx%d  模式=%s'
          % (os.path.basename(a.img), a.box, x1 - x0, y1 - y0, a.cols, a.rows, a.mode))
    step_x = (x1 - x0) / float(a.cols)
    step_y = (y1 - y0) / float(a.rows)
    print('      x: 每字符 %.1fpx    y: 每行 %.1fpx' % (step_x, step_y))
    if a.mode == 'luma':
        lines = render_luma(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(float))
    elif a.mode == 'edge':
        lines = render_edge(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(float))
    else:
        lines = render_color(small)
    for i, ln in enumerate(lines):
        print('%5d %s' % (y0 + i * step_y, ln))
    return 0


if __name__ == '__main__':
    sys.exit(main())
