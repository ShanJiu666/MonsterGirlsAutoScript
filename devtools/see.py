# -*- coding: utf-8 -*-
"""see.py · 把截图变成可读文本（OCR 全量 + 区域配色分析）

用途：无图形环境下诊断界面（本工具是 mapbot 的「眼睛」）。
品质色真值取自游戏源码 GeneralHelper.GetStepColorCode / PresetColor：
  S=orange(255,191,102)  SS=red(255,138,115)  A=purple(221,153,255)
  B=blue(145,210,242)    C=green(170,242,145) yellow=(255,243,115) red=(255,138,115)

用法:
    python see.py                       # 实时抓屏 + OCR
    python see.py runs/m0_r001.png      # 分析已有截图（不碰设备）
    python see.py runs/x.png --box 700 190 920 265   # 额外输出该区域的主色/前景色
    python see.py runs/x.png --box 700 190 920 265 --box 700 560 920 720
"""
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


PALETTE = {
    'red(SS)': (255, 138, 115),
    'orange(S)': (255, 191, 102),
    'purple(A)': (221, 153, 255),
    'blue(B)': (145, 210, 242),
    'green(C)': (170, 242, 145),
    'yellow': (255, 243, 115),
    'white': (255, 255, 255),
    'gray': (150, 150, 150),
    'dark': (60, 60, 60),
}


def nearest_palette(rgb):
    r, g, b = [float(v) for v in rgb]
    best, bd = None, 1e18
    for k, (pr, pg, pb) in PALETTE.items():
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < bd:
            bd, best = d, k
    return best, int(bd ** 0.5)


def dominant(win, topn=6):
    q = (win // 24) * 24
    flat = q.reshape(-1, 3)
    uniq, cnt = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-cnt)[:topn]
    out = []
    for i in order:
        c = uniq[i]
        pct = cnt[i] / max(1, len(flat)) * 100
        out.append(('#%02x%02x%02x' % (int(c[2]), int(c[1]), int(c[0])),
                    round(float(pct), 1), nearest_palette((int(c[2]), int(c[1]), int(c[0])))[0]))
    return out


def foreground(win):
    """去掉浅色底/深色底，取饱和前景（文字）均色 -> 品质色判定用"""
    b, g, r = cv2.split(win.astype(int))
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn
    fg = (sat > 60) & (mx > 110)
    if int(fg.sum()) < 20:
        return None, int(fg.sum())
    rgb = (int(r[fg].mean()), int(g[fg].mean()), int(b[fg].mean()))
    return rgb, int(fg.sum())


def main():
    args = sys.argv[1:]
    boxes = []
    maps = []
    rest = []
    crop = None
    scale = 1.0
    json_out = None
    i = 0
    while i < len(args):
        if args[i] == '--box':
            boxes.append(tuple(int(v) for v in args[i + 1:i + 5]))
            i += 5
        elif args[i] == '--crop':
            crop = tuple(int(v) for v in args[i + 1:i + 5])
            i += 5
        elif args[i] == '--scale':
            scale = float(args[i + 1])
            i += 2
        elif args[i] == '--json':
            json_out = args[i + 1]
            i += 2
        elif args[i] == '--map':
            v = [int(t) for t in args[i + 1:i + 5]]
            maps.append((v[0], v[1], v[2], v[3], int(args[i + 5]) if len(args) > i + 5 and args[i + 5].isdigit() else 24))
            i += 6 if len(args) > i + 5 and args[i + 5].isdigit() else 5
        else:
            rest.append(args[i])
            i += 1

    if rest:
        p = rest[0]
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        print('IMG:', p, img.shape)
        items = None
        # 复用 Bot 的 OCR（不连设备）
        from mapbot import _ocr
        tmp = os.path.join(os.path.dirname(p) or '.', '_see_ocr.png')
        if crop:
            x0, y0, x1, y1 = crop
            sub = img[y0:y1, x0:x1]
            if scale != 1:
                sub = cv2.resize(sub, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_CUBIC)
            print('CROP: x%d-%d y%d-%d scale=%s' % (x0, x1, y0, y1, scale))
            cv2.imencode('.png', sub)[1].tofile(tmp)
        else:
            sub = img
            cv2.imencode('.png', img)[1].tofile(tmp)
        res, _ = _ocr()(tmp)
        items = []
        for it in (res or []):
            box, txt, conf = it[0], it[1], it[2]
            if conf < 0.35:
                continue
            xs = [q[0] for q in box]
            ys = [q[1] for q in box]
            items.append({'text': txt.strip(), 'cx': int(sum(xs) / 4 / scale) + (crop[0] if crop else 0),
                          'cy': int(sum(ys) / 4 / scale) + (crop[1] if crop else 0),
                          'x0': int(min(xs) / scale) + (crop[0] if crop else 0),
                          'y0': int(min(ys) / scale) + (crop[1] if crop else 0),
                          'x1': int(max(xs) / scale) + (crop[0] if crop else 0),
                          'y1': int(max(ys) / scale) + (crop[1] if crop else 0),
                          'conf': round(float(conf), 3)})
        items.sort(key=lambda d: (d['cy'], d['cx']))
    else:
        from mapbot import Bot
        b = Bot(log_prefix='see')
        p = b.snap('see_now')
        img = b.img()
        items = b.ocr(min_conf=0.35)
        print('IMG:', p, img.shape)

    print('=== OCR (%d items, conf>=0.35) ===' % len(items))
    if json_out:
        import json as _json
        with open(json_out, 'w', encoding='utf-8') as f:
            _json.dump({'img': rest[0] if rest else None, 'items': items,
                        'boxes': [{'box': list(b), 'fg': foreground(img[b[1]:b[3], b[0]:b[2]])[0],
                                   'dominant': dominant(img[b[1]:b[3], b[0]:b[2]], 6)}
                                  for b in boxes]},
                       f, ensure_ascii=False, indent=1)
        print('JSON:', json_out)
    for it in items:
        print('  %-26s cx=%4d cy=%4d conf=%.2f  [%d,%d-%d,%d]' %
              (it['text'], it['cx'], it['cy'], it['conf'],
               it['x0'], it['y0'], it['x1'], it['y1']))
    for spec in maps:
        x0, y0, x1, y1, cell = spec
        print('=== 色块图 x%d-%d y%d-%d cell=%d ===' % (x0, x1, y0, y1, cell))
        letters = {'red(SS)': 'R', 'orange(S)': 'O', 'purple(A)': 'P', 'blue(B)': 'B',
                   'green(C)': 'G', 'yellow': 'Y', 'white': 'w', 'gray': '.', 'dark': '#'}
        hdr = '     ' + ''.join(str((x0 + c * cell) // 100 % 10) for c in range((x1 - x0) // cell))
        print(hdr)
        for yy in range(y0, y1 - cell + 1, cell):
            row = ''
            for xx in range(x0, x1 - cell + 1, cell):
                w = img[yy:yy + cell, xx:xx + cell]
                b_, g_, r_ = [int(v.mean()) for v in cv2.split(w)]
                nm, _ = nearest_palette((r_, g_, b_))
                row += letters.get(nm, '?')
            print('%4d %s' % (yy, row))
    for (x0, y0, x1, y1) in boxes:
        win = img[y0:y1, x0:x1]
        if win.size == 0:
            print('BOX(%d,%d,%d,%d): 空' % (x0, y0, x1, y1))
            continue
        rgb, n = foreground(win)
        print('BOX(%d,%d,%d,%d): 前景像素=%d 前景均色=%s -> %s' %
              (x0, y0, x1, y1, n, rgb, nearest_palette(rgb) if rgb else 'n/a'))
        print('    主色:', dominant(win, 5))


if __name__ == '__main__':
    main()
