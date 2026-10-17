# -*- coding: utf-8 -*-
"""make_crop.py · 把若干格裁出来**放大**放到「地图核对」，供手工核对

用法：
    python make_crop.py <图片> <输出名> [格号...]      # 不给格号则自动裁所有「有标记」和「低分」的格
"""
from __future__ import annotations

import glob
import io
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

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import marks                                        # noqa: E402
import spots as spots_mod                           # noqa: E402
import targets_cfg as tcfg                          # noqa: E402


DESK = os.path.join(os.path.expanduser('~'), 'Desktop')
_FONT = r'C:\Windows\Fonts\msyh.ttc'
GRID = {'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0}
ZOOM = 3                       # 放大倍数（96 → 288，肉眼能看清图标）
PAD = 10


def _f(sz):
    try:
        return ImageFont.truetype(_FONT, sz)
    except Exception:                                   # noqa: BLE001
        return ImageFont.load_default()


def cell_rc(r, c):
    x0 = int(GRID['x0'] + (c - 1) * GRID['cx'])
    y0 = int(GRID['y0'] + (r - 1) * GRID['cx'])
    return x0, y0, x0 + int(GRID['cx']), y0 + int(GRID['cy'])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(
        os.path.basename(src))[0]
    img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print('读不到图：%s' % src)
        return 1
    g = {'x0': GRID['x0'], 'y0': GRID['y0'], 'cx': GRID['cx'],
         'cy': GRID['cx'], 'pitch': GRID['cx'], 'cols': 7, 'rows': 5}
    st = spots_mod.Board('S00003', grid=g).state(img)
    mk = marks.scan_board(img) or {}

    want = sys.argv[3:] or None
    if want:
        cells = []
        for t in want:
            r, c = t.split(',')
            cells.append((int(r), int(c)))
    else:
        # 自动挑：所有有标记的 + 雾格里分数低的（最容易误判的）
        cells = []
        for k, v in sorted(mk.items()):
            cells.append(tuple(k))
        for k, v in sorted(st.items()):
            if k in cells:
                continue
            if float(v.get('score') or 0) < tcfg.BLOCKED_SCORE_MIN:
                cells.append(k)
    if not cells:
        print('没有要裁的格')
        return 1

    # 连成一张大图：上下两行（原图上下文 + 放大裁切）
    big = int(GRID['cx']) * ZOOM
    W = PAD + len(cells) * (big + PAD)
    hdr, ctx_h = 54, int(GRID['cx']) + PAD
    H = PAD + ctx_h + big + 56
    pil = Image.new('RGB', (W, H), (24, 20, 16))
    dr = ImageDraw.Draw(pil)
    dr.text((PAD, 8), '%s · 放大 %d× 的格（黄框=有标记 红框=低分）'
            % (os.path.basename(src), ZOOM), font=_f(19), fill=(240, 230, 200))
    dr.text((PAD, 32), '每格上排=原尺寸上下文，下排=放大 %d 倍' % ZOOM,
            font=_f(13), fill=(180, 170, 150))

    for i, (r, c) in enumerate(cells):
        x = PAD + i * (big + PAD)
        x0, y0, x1, y1 = cell_rc(r, c)
        # 上：原尺寸
        ctx = img[y0:y1, x0:x1]
        pil.paste(Image.fromarray(cv2.cvtColor(ctx, cv2.COLOR_BGR2RGB)), (x, PAD + 20))
        dr.rectangle([x, PAD + 20, x + ctx.shape[1] - 1, PAD + 20 + ctx.shape[0] - 1],
                     outline=(110, 100, 86))
        # 下：放大
        y2 = PAD + ctx_h + 20
        up = cv2.resize(ctx, (big, big), interpolation=cv2.INTER_NEAREST)
        pil.paste(Image.fromarray(cv2.cvtColor(up, cv2.COLOR_BGR2RGB)), (x, y2))
        m = mk.get((r, c))
        v = st.get((r, c)) or {}
        dr.rectangle([x, y2, x + big - 1, y2 + big - 1],
                     outline=(255, 220, 0) if m else (120, 110, 96), width=3)
        ty = y2 + big + 4
        dr.text((x, ty), '%d,%d' % (r, c), font=_f(17), fill=(255, 235, 160))
        marks_s = ','.join((m or {}).get('marks') or []) or '无标记'
        col = (255, 90, 90) if m else ((255, 150, 90)
                                       if float(v.get('score') or 0)
                                       < tcfg.BLOCKED_SCORE_MIN else (190, 200, 210))
        dr.text((x, ty + 20), '标记:%s' % marks_s, font=_f(13), fill=col)
        if m:
            dr.text((x, ty + 37), '形状%.3f 配色%.3f' % (m.get('score') or 0,
                                                        m.get('color') or 0),
                    font=_f(12), fill=(230, 230, 230))
        dr.text((x, ty + (54 if m else 37)),
                '%s %.2f r%.2f' % (str(v.get('name') or '?')[:5],
                                  float(v.get('score') or 0),
                                  float(v.get('ratio') or 0)),
                font=_f(12), fill=(170, 178, 190))

    out = os.path.join(DESK, '%s_放大对照.png' % base)
    pil.save(out)
    print('已生成：%s  (%dx%d, %d bytes)' % (out, W, H, os.path.getsize(out)))

    L = ['■ %s 逐格明细（裁切同源数据）' % os.path.basename(src), '']
    for r, c in cells:
        v = st.get((r, c)) or {}
        m = mk.get((r, c)) or {}
        L.append('  %d,%-2d %-8s %.3f r%.2f   标记[%s] 形状%.3f 配色%.3f'
                 % (r, c, str(v.get('name') or '?'), float(v.get('score') or 0),
                    float(v.get('ratio') or 0),
                    ','.join(m.get('marks') or []) or '—',
                    float(m.get('score') or 0), float(m.get('color') or 0)))
    p = os.path.join(DESK, '%s_放大明细.txt' % base)
    io.open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    print('已生成：%s' % p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
