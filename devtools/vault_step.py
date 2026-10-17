# -*- coding: utf-8 -*-
"""vault_step.py · 宝库面板「单步」操作器（每步都重新截图，逐步看效果）

用法:
    python vault_step.py state          # 只打印当前面板状态
    python vault_step.py open           # 在棋盘上点开宝库面板（默认格 5,4）
    python vault_step.py pick 0 0       # 点第 0 行第 0 列的宝物（选择奖励）
    python vault_step.py buy            # 点右下角「购买」
    python vault_step.py back           # 点中间「返回」
    python vault_step.py x              # 点右上角 X 关闭
    python vault_step.py gold           # 关掉面板读金币（读不到就只报当前值）
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


VAULT = {'buy': (895, 1444), 'back': (539, 1212), 'x': (983, 384),
         'gx0': 251, 'gy0': 746, 'pitch': 144}


def see(b, tag='step'):
    b.snap(tag)
    return b.ocr(min_conf=0.3)


def report(it):
    txt = [t['text'] for t in it if 330 < t['cy'] < 1560 and len(t['text']) <= 14]
    gold = None
    for t in it:
        v = t['text'].replace(',', '').replace('+', '')
        if t['cy'] < 70 and v.isdigit() and len(v) >= 6:
            gold = int(v)
    print('  面板:', txt[:10])
    print('  金币:', gold)
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('a', nargs='?', type=int)
    ap.add_argument('b', nargs='?', type=int)
    ap.add_argument('--cell', default='5,4')
    ap.add_argument('--wait', type=float, default=2.6)
    a = ap.parse_args()
    bot = Bot(log_prefix='vst')
    log = []
    if not EL.ensure_in_map(bot, log):
        print('进图失败:', log)
        return 1
    if a.cmd == 'state':
        report(see(bot))
    elif a.cmd == 'open':
        r, c = [int(v) for v in a.cell.split(',')]
        x = int(SP.GRID['x0'] + (c - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        y = int(SP.GRID['y0'] + (r - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        print('点格 (%d,%d) @(%d,%d)' % (r, c, x, y))
        bot.tap(x, y, wait=a.wait)
        report(see(bot))
    elif a.cmd == 'pick':
        x = int(VAULT['gx0'] + a.b * VAULT['pitch'])
        y = int(VAULT['gy0'] + a.a * VAULT['pitch'])
        print('点宝物 (%d,%d) @(%d,%d)' % (a.a, a.b, x, y))
        bot.tap(x, y, wait=a.wait)
        report(see(bot))
    elif a.cmd in ('buy', 'back', 'x'):
        pos = VAULT[a.cmd]
        print('点 %s %s' % (a.cmd, pos))
        bot.tap(pos[0], pos[1], wait=a.wait)
        report(see(bot))
    elif a.cmd == 'gold':
        report(see(bot))
    else:
        print(__doc__)
    for e in log[-3:]:
        print(e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
