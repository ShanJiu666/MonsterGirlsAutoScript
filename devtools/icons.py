# -*- coding: utf-8 -*-
"""icons.py · 从历史截图里无监督捞出「地块标记图标」并聚类

原理：4 个标记（首领/大拇指/幸运草/红装）都是画在地块上的高饱和小贴图，
      和沙地/石板/物件美术的色块分布不同 —— 逐格找高饱和小色块，裁出来聚类，
      反复出现的就是图标（每个图标在不同地图/不同格子上长得一模一样）。

用法:
    python icons.py collect "runs/*.png" runs/icons          # 抽色块 + 存缩略图
    python icons.py cluster runs/icons --min 3               # 聚类 + 拼对照图
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


GRID = dict(x0=21.0, y0=941.0, cx=148.3, cy=154.3, cols=7, rows=5)


def load(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def save(p, img):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cv2.imencode('.png', img)[1].tofile(p)


def blobs_in(img, x0, y0, x1, y1):
    """返回该区域里的高饱和小色块 [(x,y,w,h,rgb)]"""
    win = img[y0:y1, x0:x1].astype(int)
    b, g, r = cv2.split(win)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn
    mask = ((sat > 90) & (mx > 150)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 60 <= area <= 3000 and 8 <= w <= 90 and 8 <= h <= 90:
            sub = win[y:y + h, x:x + w]
            bb, gg, rr = [int(v.mean()) for v in cv2.split(sub)]
            out.append((int(x), int(y), int(w), int(h), (rr, gg, bb)))
    return out


def cmd_collect(pattern, outdir):
    files = sorted(glob.glob(pattern))
    os.makedirs(outdir, exist_ok=True)
    meta = []
    for f in files:
        img = load(f)
        if img is None or img.shape[0] < 1700:
            continue
        base = os.path.splitext(os.path.basename(f))[0]
        for rr in range(GRID['rows']):
            for cc in range(GRID['cols']):
                x0 = int(GRID['x0'] + cc * GRID['cx'])
                y0 = int(GRID['y0'] + rr * GRID['cy'])
                x1 = int(x0 + GRID['cx'])
                y1 = int(y0 + GRID['cy'])
                for k, (x, y, w, h, rgb) in enumerate(blobs_in(img, x0, y0, x1, y1)):
                    crop = img[y0 + y:y0 + y + h, x0 + x:x0 + x + w]
                    thumb = cv2.resize(crop, (16, 16), interpolation=cv2.INTER_AREA)
                    name = '%s_r%dc%d_%d.png' % (base, rr + 1, cc + 1, k)
                    save(os.path.join(outdir, 'thumbs', name), thumb)
                    meta.append({'file': os.path.basename(f), 'r': rr + 1, 'c': cc + 1,
                                 'x': x, 'y': y, 'w': w, 'h': h, 'rgb': list(rgb),
                                 'thumb': name})
    with open(os.path.join(outdir, 'blobs.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print('COLLECT %d 张图 -> %d 个色块' % (len(files), len(meta)))


def cmd_cluster(outdir, min_n=3):
    meta = json.load(open(os.path.join(outdir, 'blobs.json'), encoding='utf-8'))
    thumbs = {}
    for m in meta:
        t = load(os.path.join(outdir, 'thumbs', m['thumb']))
        if t is not None:
            thumbs[m['thumb']] = t.astype(np.float32)
    clusters = []          # [{'rep':name,'items':[names]}]
    for m in meta:
        t = thumbs.get(m['thumb'])
        if t is None:
            continue
        best, bd = None, 1e18
        for cl in clusters:
            d = float(np.abs(thumbs[cl['rep']] - t).mean())
            if d < bd:
                bd, best = d, cl
        if best is not None and bd < 22:
            best['items'].append(m['thumb'])
        else:
            clusters.append({'rep': m['thumb'], 'items': [m['thumb']], 'meta': m})
    clusters.sort(key=lambda c: -len(c['items']))
    big = [c for c in clusters if len(c['items']) >= min_n]
    # 拼对照图：每个簇一行，第一张是代表
    rows = []
    for c in big[:24]:
        ims = [load(os.path.join(outdir, 'thumbs', n)) for n in c['items'][:12]]
        ims = [i for i in ims if i is not None]
        if not ims:
            continue
        row = np.hstack(ims)
        pad = np.zeros((16, max(0, 12 * 16 - row.shape[1]), 3), np.uint8)
        rows.append(np.hstack([row, pad]))
    if rows:
        sheet = np.vstack(rows)
        sheet = cv2.resize(sheet, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        save(os.path.join(outdir, '_clusters.png'), sheet)
    rep = [{'n': len(c['items']), 'rep': c['rep'],
            'rgb': c['meta']['rgb'], 'w': c['meta']['w'], 'h': c['meta']['h'],
            'files': sorted({i.split('_r')[0] for i in c['items']})[:6]}
           for c in big]
    with open(os.path.join(outdir, 'clusters.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print('CLUSTER %d 簇(>=%d 次)，对照图 %s' % (len(big), min_n,
                                          os.path.join(outdir, '_clusters.png')))
    for r in rep[:20]:
        print('  n=%-4d %dx%d rgb=%s 例:%s' % (r['n'], r['w'], r['h'], r['rgb'], r['rep']))


def main():
    cmd = sys.argv[1]
    if cmd == 'collect':
        cmd_collect(sys.argv[2], sys.argv[3])
    elif cmd == 'cluster':
        mn = 3
        if '--min' in sys.argv:
            mn = int(sys.argv[sys.argv.index('--min') + 1])
        cmd_cluster(sys.argv[2], mn)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
