# -*- coding: utf-8 -*-
"""live_board.py · 进图 → 抓一张棋盘截图（离线分析用）

用法:
    python live_board.py                 # 只在不在图里时进图，然后抓 runs/live_board.png
    python live_board.py --enter         # 强制先结束当前图再进新图
    python live_board.py --rounds 3      # 抓完 r1 后按主循环点 3 轮，每轮各抓一张
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
import time

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import explore_loop as EL
from mapbot import Bot, RUNS



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rounds', type=int, default=0)
    ap.add_argument('--enter', action='store_true')
    ap.add_argument('--tag', default='live_board')
    a = ap.parse_args()

    b = Bot(log_prefix='lb')
    log = []
    b.snap(a.tag + '_pre')
    items = b.ocr()
    if a.enter and EL.in_map(b, b.img(), items):
        EL.finish_map(b, log)
    if not EL.in_map(b, b.img(), b.ocr()):
        if not EL.ensure_in_map(b, log):
            print('进图失败')
            for e in log:
                print(e)
            return 1
    p = b.snap(a.tag)
    print('截图:', p)
    items = b.ocr()
    img = b.img()
    c = EL.cells_of(img)
    print('cells_of: gray=%d light=%d' % (len(c['gray']), len(c['light'])))
    mk = __import__('marks').scan_board(img)
    print('marks:', {'%d,%d' % k: v['marks'] for k, v in mk.items()})
    print('stamina:', EL.stamina(items))
    for r in range(a.rounds):
        try:
            why = EL.one_round(b, log, 900 + r, '', {'cold': {}, 'done': set(), 'last': None,
                                                     'err': 0, 'stuck': 0, 'marks': mk,
                                                     'clear': False, 'clear_fights': 0,
                                                     'stall': 0, 'sig': None, 'blank': 0})
        except Exception as e:      # noqa: BLE001
            print('round err', repr(e))
            why = None
        p = b.snap('%s_after%d' % (a.tag, r))
        print('round %d -> %s  截图 %s' % (r, why, p))
        if why:
            break
    for e in log[-12:]:
        print(e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
