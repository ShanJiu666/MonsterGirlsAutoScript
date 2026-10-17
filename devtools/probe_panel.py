# -*- coding: utf-8 -*-
"""probe_panel.py · 通用面板探测：点一个坐标 → 抓图 + 全量 OCR（写进 runs/）

用法:
    python probe_panel.py 896 1444              # 点一下并 dump
    python probe_panel.py 896 1444 --wait 3     # 点后等 3 秒
    python probe_panel.py --none                # 只 dump，不点
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
from mapbot import Bot



def dump(b, tag):
    p = b.snap(tag)
    items = b.ocr(min_conf=0.35)
    print('IMG:', p, '(%d items)' % len(items))
    for it in items:
        if it['cy'] < 140 or it['cy'] > 1860:
            continue
        print('  %-30s %4d,%4d conf=%.2f' % (it['text'], it['cx'], it['cy'], it['conf']))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('x', nargs='?', type=int)
    ap.add_argument('y', nargs='?', type=int)
    ap.add_argument('--wait', type=float, default=2.5)
    ap.add_argument('--none', action='store_true')
    ap.add_argument('--tag', default='panel')
    a = ap.parse_args()
    b = Bot(log_prefix='pp')
    if not a.none and a.x is not None:
        print('tap (%d,%d)' % (a.x, a.y))
        b.tap(a.x, a.y, wait=a.wait)
    dump(b, a.tag)
    return 0


if __name__ == '__main__':
    sys.exit(main())
