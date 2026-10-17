# -*- coding: utf-8 -*-
"""vault_test.py · 黄金宝库「买完」逐步实测（每步重新截图 + 打印面板文字 + 金币对账）

流程（用户口述 2026-09-25）：选择奖励 → 右下角「购买」→ 中间「返回」，循环 3 次。

用法:
    python vault_test.py             # 面板没开就先点宝库格打开
    python vault_test.py --cell 5,4  # 指定宝库格（行,列）
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
import buypanels as BP
import explore_loop as EL
import spots as SP
from mapbot import Bot



def panel_texts(items):
    out = []
    for it in items:
        if 330 < it['cy'] < 1560 and len(it['text']) <= 12:
            out.append('%s@(%d,%d)' % (it['text'], it['cx'], it['cy']))
    return out


def gold(items):
    for it in items:
        t = it['text'].replace(',', '').replace('+', '')
        if it['cy'] < 70 and t.isdigit() and len(t) >= 5:
            return int(t)
    return None


def see(b, tag='vs'):
    """⚠ 先 snap 再 OCR：Bot.ocr() 读的是上一次截图（缓存旧图）"""
    b.snap(tag)
    return b.ocr(min_conf=0.3)


def open_panel(b):
    it = see(b, 'vs_open0')
    if any(('黄金宝库' in t['text'] or '黄全宝库' in t['text']) for t in it):
        return it
    r, c = [int(v) for v in CELL.split(',')]
    x = int(SP.GRID['x0'] + (c - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
    y = int(SP.GRID['y0'] + (r - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
    print('点宝库格 (%d,%d) @(%d,%d)' % (r, c, x, y))
    b.tap(x, y, wait=3.0)
    return see(b, 'vs_open1')


CELL = '5,4'


def main():
    global CELL
    ap = argparse.ArgumentParser()
    ap.add_argument('--cell', default='5,4')
    a = ap.parse_args()
    CELL = a.cell
    b = Bot(log_prefix='vs')
    log = []
    if not EL.ensure_in_map(b, log):
        print('进图失败')
        return 1
    b.snap('vs0')
    g0 = gold(see(b, 'vs_g0'))
    it = open_panel(b)
    print('面板文字:', panel_texts(it))
    print('起始金币:', g0)

    picks = [(BP.VAULT['gx0'], BP.VAULT['gy0']),
             (BP.VAULT['gx0'] + BP.VAULT['pitch'], BP.VAULT['gy0'] + BP.VAULT['pitch']),
             (BP.VAULT['gx0'] + 2 * BP.VAULT['pitch'], BP.VAULT['gy0'] + 2 * BP.VAULT['pitch'])]
    bought = 0
    for step in range(14):
        it = see(b, 'vs_s%d' % step)
        txt = [t['text'] for t in it]
        print('  第%d步 面板:' % step, [t for t in panel_texts(it)][:8])
        if any('返回' in t for t in txt):
            print('    -> 点「返回」(539,1212)')
            b.tap(*BP.VAULT['back'], wait=2.4)
            continue
        if not any('购买' in t for t in txt):
            print('    -> 没有「购买」了，收工')
            break
        pick = picks[min(bought, 2)]
        print('    -> 选择奖励 (%d,%d) → 购买 (895,1444)' % pick)
        b.tap(pick[0], pick[1], wait=1.8)
        b.tap(*BP.VAULT['buy'], wait=3.0)
        bought += 1
    it = see(b, 'vs_end0')
    if any('返回' in t['text'] for t in it):
        print('    -> 补点「返回」')
        b.tap(*BP.VAULT['back'], wait=2.4)
        it = see(b, 'vs_end1')
    if any(('黄金宝库' in t['text'] or '黄全宝库' in t['text']) for t in it):
        print('    -> 关 X (983,384)')
        b.tap(*BP.VAULT['x'], wait=2.2)
    it = see(b, 'vs_end2')
    g1 = gold(it)
    print('购买次数:', bought, ' 金币:', g0, '->', g1,
          ' 差额:', (g0 - g1) if (g0 and g1) else '?')
    print('结束面板:', panel_texts(it)[:8])
    return 0


if __name__ == '__main__':
    sys.exit(main())
