# -*- coding: utf-8 -*-
"""vault_run.py · 直接对当前宝库面板跑一遍 buypanels.vault_flow（逐步打印）

用法:
    python vault_run.py            # 面板没开就先点 (4,5) 的宝库格
    python vault_run.py --cell 4,5
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
import buypanels as BP
import explore_loop as EL
import spots as SP
from mapbot import Bot



def see(b, tag):
    b.snap(tag)
    return b.ocr(min_conf=0.3)


def gold(it):
    for t in it:
        v = t['text'].replace(',', '').replace('+', '')
        if t['cy'] < 70 and v.isdigit() and len(v) >= 6:
            return int(v)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cell', default='4,5')
    a = ap.parse_args()
    b = Bot(log_prefix='vr')
    log = []
    if not EL.ensure_in_map(b, log):
        print('进图失败')
        return 1
    it = see(b, 'vr0')
    if not any('黄金宝库' in t['text'] or '黄全宝库' in t['text'] for t in it):
        r, c = [int(v) for v in a.cell.split(',')]
        x = int(SP.GRID['x0'] + (c - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        y = int(SP.GRID['y0'] + (r - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        print('点宝库格 (%d,%d) @(%d,%d)' % (r, c, x, y))
        b.tap(x, y, wait=3.0)
        it = see(b, 'vr1')
    print('开面板前金币:', gold(it) or '(被面板挡住)')
    print('面板:', [t['text'] for t in it if 330 < t['cy'] < 1560][:8])
    n = BP.vault_flow(b, log)
    for e in log:
        print('  ', e)
    it = see(b, 'vr_end')
    print('买了几层:', n, ' 结束金币:', gold(it))
    print('结束面板:', [t['text'] for t in it if 330 < t['cy'] < 1560][:8])
    return 0


if __name__ == '__main__':
    sys.exit(main())
