# -*- coding: utf-8 -*-
"""make_tiles.py · 地块模板图鉴（一张图看完所有方块长什么样 + 名字 + 占格）

给手工核对用：把 `templates/unit/<code>/<sid>/*.png` 的**真实贴图**（含 alpha 轮廓）
按「名字 / sid / 占格」排版导出，落到桌面。

用法：
    python make_tiles.py [地图代码] [输出目录]     # 默认 S00003 → 桌面
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

import spots as spots_mod                           # noqa: E402


DESK = os.path.join(os.path.expanduser('~'), 'Desktop')
_FONT = r'C:\Windows\Fonts\msyh.ttc'
UNIT = spots_mod.UNIT

# 贴图单位网格：32px = 1 格（缩到屏幕上按比例放大，方便看清）
DESIGN = 32
CELL = 96            # 输出时每格画多少像素
COLS = 5             # 每行几个地块


def _f(sz):
    try:
        return ImageFont.truetype(_FONT, sz)
    except Exception:                                   # noqa: BLE001
        return ImageFont.load_default()


def load_tile(code, sid):
    """该 sid 的首帧贴图（PIL RGBA）"""
    for p in sorted(glob.glob(os.path.join(UNIT, code, sid, '*.png'))):
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        if im.shape[2] == 4:
            im = im[:, :, [2, 1, 0, 3]]               # BGR→RGB，保 alpha
        else:
            im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
            im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
        return Image.fromarray(im), p
    return None, None


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else 'S00003'
    outdir = sys.argv[2] if len(sys.argv) > 2 else DESK
    rows_tbl = spots_mod.spot_rows()
    B = spots_mod.Board(code)

    items = []
    for sid, r in sorted(rows_tbl.items()):
        if not sid.startswith(code):
            continue
        tile, path = load_tile(code, sid)
        if tile is None:
            continue
        fp = B.footprint(sid)
        cw, ch = B._tpl_size(sid)
        items.append((sid, str(r.get('Name') or '?'), r, tile, fp, cw, ch))
    if not items:
        print('没找到 %s 的贴图（目录 %s）' % (code, UNIT))
        return 1

    # 每个地块一块画布，尺寸按它最大占格
    f_t, f_s = _f(17), _f(13)
    pad = 8
    boxes = []
    for sid, nm, r, tile, fp, cw, ch in items:
        tw = max(1, cw) * CELL + pad * 2
        th = max(1, ch) * CELL + pad * 2 + 64
        boxes.append((tw, th))
    n = len(items)
    rowsn = (n + COLS - 1) // COLS
    colw = [max(boxes[i][0] for i in range(c, n, COLS)) for c in range(COLS)]
    rowh = [max(boxes[i][1] for i in range(r0, min(r0 + COLS, n)))
            for r0 in range(0, n, COLS)]
    W = sum(colw) + 20
    H = sum(rowh) + 86

    pil = Image.new('RGB', (W, H), (26, 22, 18))
    dr = ImageDraw.Draw(pil)
    dr.text((10, 8), '地块模板图鉴 · %s · 共 %d 种'
            % (str((rows_tbl.get('S00003_000') or {}).get('Name') and code), n),
            font=_f(20), fill=(240, 230, 200))
    dr.text((10, 34), '每格 %dpx 网格；绿框 = 该地块真实占格（footprint）；'
                      '右上角数字 = sid 末段' % CELL, font=f_s,
            fill=(190, 180, 160))

    y = 60
    for r0 in range(0, n, COLS):
        x = 10
        for c in range(COLS):
            i = r0 + c
            if i >= n:
                break
            sid, nm, row, tile, fp, cw, ch = items[i]
            bw, bh = boxes[i]
            dr.rectangle([x, y, x + bw - 4, y + bh - 4], outline=(70, 62, 52))
            # 贴图画在「最大外框」左上角，锚格 = (0,0)
            tw, th = tile.size
            sc = CELL / float(DESIGN)
            t2 = tile.resize((max(1, int(tw * sc)), max(1, int(th * sc))),
                             Image.LANCZOS)
            # alpha 区域衬一层棋盘底，方便看清轮廓
            bb = Image.new('RGB', t2.size, (52, 46, 40))
            a = t2.split()[3]
            bb.paste(t2.convert('RGB'), (0, 0), a)
            pil.paste(bb, (x + pad, y + pad))
            dr.rectangle([x + pad, y + pad, x + pad + t2.size[0] - 1,
                          y + pad + t2.size[1] - 1], outline=(120, 110, 96))
            # 网格
            for k in range(1, cw):
                gx = x + pad + k * CELL
                dr.line([gx, y + pad, gx, y + pad + ch * CELL], fill=(90, 80, 68))
            for k in range(1, ch):
                gy = y + pad + k * CELL
                dr.line([x + pad, gy, x + pad + cw * CELL, gy], fill=(90, 80, 68))
            # 真实占格 = 绿框
            fr = set(fp)
            for dr0 in range(ch):
                for dc in range(cw):
                    if (dr0, dc) in fr:
                        dr.rectangle([x + pad + dc * CELL, y + pad + dr0 * CELL,
                                      x + pad + (dc + 1) * CELL - 1,
                                      y + pad + (dr0 + 1) * CELL - 1],
                                     outline=(0, 235, 90), width=3)
            # 文字
            ty = y + pad + max(1, ch) * CELL + 4
            dr.text((x + pad, ty), nm, font=f_t, fill=(255, 230, 150))
            dr.text((x + pad, ty + 20), '%s   占%d格  SpotSize=%s'
                    % (sid.split('_')[-1], len(fp), row.get('SpotSize')),
                    font=f_s, fill=(190, 200, 215))
            dr.text((x + pad, ty + 36), '外框%d×%d  Special=%s'
                    % (cw, ch, row.get('SpecialSpot')), font=f_s,
                    fill=(150, 160, 175))
            x += colw[c]
        y += rowh[r0 // COLS]

    out = os.path.join(outdir, '%s_地块图鉴.png' % code)
    pil.save(out)
    print('已生成：%s  (%dx%d, %d bytes)' % (out, W, H, os.path.getsize(out)))

    # 顺带出一份纯文字清单
    L = ['■ %s 地块清单（占格 = footprint，绿框）' % code, '']
    for sid, nm, row, tile, fp, cw, ch in items:
        L.append('  %-14s %-8s 占%d格 %-28s 外框%d×%d SpotSize=%s Special=%s'
                 % (sid, nm, len(fp), str(fp), cw, ch,
                    row.get('SpotSize'), row.get('SpecialSpot')))
    p = os.path.join(outdir, '%s_地块清单.txt' % code)
    io.open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    print('已生成：%s' % p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
