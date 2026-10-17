# -*- coding: utf-8 -*-
"""find_buy.py · 进新图 → 逐格分类 → 报出旅行商人/黄金宝库（可选直接点开验证）

用法:
    python find_buy.py                 # 当前图（若在图里就沿用）
    python find_buy.py --enter         # 先结束当前图，进新图再认
    python find_buy.py --click         # 认出后点它，打印面板文字（当真值验证）
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
import explore_loop as EL
import spots as SP
from mapbot import Bot



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', dest='mapname', default='夏日海滩')
    ap.add_argument('--code')
    ap.add_argument('--enter', action='store_true')
    ap.add_argument('--click', action='store_true')
    ap.add_argument('--thr', type=float, default=0.80)
    a = ap.parse_args()
    code = a.code or SP.code_of(a.mapname)
    rows = SP.spot_rows()
    b = Bot(log_prefix='fb')
    log = []
    items = b.ocr()
    img = b.img()
    if a.enter and EL.in_map(b, img, items):
        EL.finish_map(b, log)
    if not EL.in_map(b, b.img(), b.ocr()):
        if not EL.ensure_in_map(b, log):
            print('进图失败:', log)
            return 1
    p = b.snap('find_buy')
    img = b.img()
    board = SP.Board(code)
    sc = board.scores(img)
    objs = board.objects(sc, thr=a.thr)
    print('截图 %s  图 %s → %s' % (p, a.mapname, code))
    print('=== 棋盘（每格 = 分类名/分数） ===')
    for r in range(1, 6):
        line = []
        for c in range(1, 8):
            lst = sc.get((r, c))
            if not lst:
                line.append('%-14s' % '-')
                continue
            v, sid, _f, _o = lst[0]
            nm = (rows.get(sid) or {}).get('Name') or '?'
            line.append('%-8s%.2f ' % (nm[:8], v))
        print('  r%d %s' % (r, ' | '.join(line)))
    print('=== 物件（≥%.2f） ===' % a.thr)
    done = set()
    for (r, c), o in sorted(objs.items()):
        if o['anchor'] in done:
            continue
        done.add(o['anchor'])
        nm = (rows.get(o['sid']) or {}).get('Name') or '?'
        print('  锚点%-8s %-12s %-8s %.3f  占格 %s'
              % (o['anchor'], o['sid'], nm, o['score'], o['cells']))
    want = {sid for sid, r in rows.items()
            if sid.startswith(code) and (r.get('Name') in SP.BUY_OUT_NAMES)}
    hits = [(r, c) for (r, c), lst in sc.items() if lst[0][1] in want and lst[0][0] >= a.thr]
    print('=== 旅行商人/黄金宝库 ===')
    for (r, c) in sorted(hits):
        v, sid, _f, _o = sc[(r, c)][0]
        print('  格(%d,%d) %s %s %.3f' % (r, c, sid, rows[sid]['Name'], v))
    if not hits:
        print('  本图未认出（可能没有，或阈值过高）')
    if a.click and hits:
        r, c = sorted(hits)[0]
        cx = int(SP.GRID['x0'] + (c - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        cy = int(SP.GRID['y0'] + (r - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        print('点 格(%d,%d) @(%d,%d)' % (r, c, cx, cy))
        b.tap(cx, cy, wait=2.5)
        b.snap('find_buy_click')
        it2 = b.ocr()
        for it in it2:
            if it['cy'] > 300 and it['cy'] < 1400:
                print('    %-28s %4d,%4d' % (it['text'], it['cx'], it['cy']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
