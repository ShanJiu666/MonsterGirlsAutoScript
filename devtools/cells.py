# -*- coding: utf-8 -*-
"""cells.py · 把棋盘 35 格逐格切出来 + 做「带标记 vs 不带标记」差分找图标

用法:
    # 1) 切图：把一张棋盘截图切成 35 张（r{行}c{列}.png），并存一张拼接大图便于人眼核对
    python cells.py cut runs/xxx.png runs/cells_out

    # 2) 差分：给两张同类型地块的截图区域，找差异块（= 图标位置）
    python cells.py diff a.png b.png out_prefix [--box x0 y0 x1 y1]

    # 3) 扫描：在一堆截图里找出「某个子区域反复出现的稀有图案」（无监督找图标）
    python cells.py scan runs/*.png --cell 2,3 --sub 0 0 48 48
"""
import glob
import json
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

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np


# ⭐ 2026-10-02 换基准：与 `spots.py` / `marks.py` 一样，**改为从 layout.REF 取**。
#   原来写死 1080×1920 系（x0=36 y0=1002 cx=144），720p 下整体错位。
try:
    from layout import REF as _REF
    GRID = dict(x0=float(_REF['grid_x0']), y0=float(_REF['grid_y0']),
                cx=float(_REF['grid_cx']), cy=float(_REF['grid_cy']),
                cols=_REF['grid_cols'], rows=_REF['grid_rows'])
except Exception:       # noqa: BLE001  layout 不可用时退回 720p 标定值（勿改回 1080 系）
    GRID = dict(x0=24.0, y0=668.0, cx=96.0, cy=96.0, cols=7, rows=5)


def cell_boxes():
    out = []
    for r in range(GRID['rows']):
        for c in range(GRID['cols']):
            x0 = int(GRID['x0'] + c * GRID['cx'])
            y0 = int(GRID['y0'] + r * GRID['cy'])
            out.append((r + 1, c + 1, x0, y0,
                        int(x0 + GRID['cx']), int(y0 + GRID['cy'])))
    return out


def load(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def save(p, img):
    cv2.imencode('.png', img)[1].tofile(p)


def cmd_cut(src, outdir):
    os.makedirs(outdir, exist_ok=True)
    img = load(src)
    tiles = []
    for (r, c, x0, y0, x1, y1) in cell_boxes():
        t = img[y0:y1, x0:x1]
        save(os.path.join(outdir, 'r%dc%d.png' % (r, c)), t)
        t2 = cv2.resize(t, (150, 154))
        cv2.putText(t2, '%d,%d' % (r, c), (4, 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 255), 1)
        tiles.append(t2)
    rows = []
    for r in range(GRID['rows']):
        rows.append(np.hstack(tiles[r * GRID['cols']:(r + 1) * GRID['cols']]))
    sheet = np.vstack(rows)
    save(os.path.join(outdir, '_sheet.png'), sheet)
    print('CUT:', outdir, 'sheet=_sheet.png', sheet.shape)


def cmd_diff(a, b, prefix, box=None):
    ia, ib = load(a), load(b)
    if box:
        x0, y0, x1, y1 = box
        ia, ib = ia[y0:y1, x0:x1], ib[y0:y1, x0:x1]
    if ia.shape != ib.shape:
        print('尺寸不同', ia.shape, ib.shape)
        return
    d = np.abs(ia.astype(int) - ib.astype(int)).max(axis=2).astype(np.uint8)
    m = (d > 40).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(m, 8)
    blobs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= 40:
            blobs.append({'cx': int(cents[i][0]), 'cy': int(cents[i][1]),
                          'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
                          'area': int(area)})
    blobs.sort(key=lambda b: -b['area'])
    save(prefix + '_mask.png', m)
    save(prefix + '_diff.png', cv2.applyColorMap(d * 3, cv2.COLORMAP_JET))
    with open(prefix + '_blobs.json', 'w', encoding='utf-8') as f:
        json.dump(blobs, f, ensure_ascii=False, indent=1)
    print('DIFF blobs:', len(blobs))
    for b in blobs[:12]:
        print('   cx=%4d cy=%4d %dx%d area=%d' % (b['cx'], b['cy'], b['w'], b['h'], b['area']))


def cmd_scan(pattern, cell, sub):
    """在多个截图的同一格同一子区域里找「稀有图案」：按 8x8 缩略图哈希分组"""
    files = sorted(glob.glob(pattern))
    r, c = [int(v) for v in cell.split(',')]
    x0, y0, x1, y1 = sub
    groups = {}
    for f in files:
        img = load(f)
        if img is None:
            continue
        cx0 = int(GRID['x0'] + (c - 1) * GRID['cx']) + x0
        cy0 = int(GRID['y0'] + (r - 1) * GRID['cy']) + y0
        win = img[cy0:cy0 + (y1 - y0), cx0:cx0 + (x1 - x0)]
        if win.size == 0:
            continue
        small = cv2.resize(win, (8, 8))
        key = tuple((small // 32).flatten().tolist())
        groups.setdefault(key, []).append(os.path.basename(f))
    print('SCAN %d 张 -> %d 组' % (len(files), len(groups)))
    for k, v in sorted(groups.items(), key=lambda x: len(x[1])):
        print('   n=%-4d 例: %s' % (len(v), v[0]))


def cmd_blobs(src, out):
    """逐格找「高饱和小色块」= 可能的标记图标，按格输出相对坐标"""
    img = load(src)
    lines = []
    for (r, c, x0, y0, x1, y1) in cell_boxes():
        win = img[y0:y1, x0:x1].astype(int)
        b, g, rr = cv2.split(win)
        mx = np.maximum(np.maximum(rr, g), b)
        mn = np.minimum(np.minimum(rr, g), b)
        sat = mx - mn
        mask = ((sat > 90) & (mx > 150)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        blobs = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if 40 <= area <= 3000 and w <= 90 and h <= 90:
                sub = win[y:y + h, x:x + w]
                bb, gg, rrr = [int(v.mean()) for v in cv2.split(sub)]
                blobs.append('(%3d,%3d %2dx%2d a=%4d rgb=%3d,%3d,%3d)'
                             % (x, y, w, h, area, rrr, gg, bb))
        if blobs:
            lines.append('r%dc%d: %s' % (r, c, ' '.join(blobs[:4])))
    txt = '\n'.join(lines)
    if out:
        open(out, 'w', encoding='utf-8').write(txt)
        print('BLOBS:', out, len(lines), '格有色块')
    else:
        print(txt)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == 'cut':
        cmd_cut(sys.argv[2], sys.argv[3])
    elif cmd == 'diff':
        box = None
        if '--box' in sys.argv:
            i = sys.argv.index('--box')
            box = tuple(int(v) for v in sys.argv[i + 1:i + 5])
        cmd_diff(sys.argv[2], sys.argv[3], sys.argv[4], box)
    elif cmd == 'scan':
        i = sys.argv.index('--cell')
        j = sys.argv.index('--sub')
        cmd_scan(sys.argv[2], sys.argv[i + 1], tuple(int(v) for v in sys.argv[j + 1:j + 5]))
    elif cmd == 'blobs':
        cmd_blobs(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
