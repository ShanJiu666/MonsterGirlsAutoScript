# -*- coding: utf-8 -*-
"""do_vault.py · 一键处理当前的宝库：面板开着就直接买完，没开就先点开宝库格

走的就是主循环 `explore_loop.popups()` 的同一条路（`buypanels.vault_flow`），
所以这个脚本跑通 = 主循环跑通。

用法:
    python do_vault.py              # 当前状态自动判断
    python do_vault.py --cell 4,7   # 指定宝库格（行,列）
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
from mapbot import Bot



def see(b, tag):
    b.snap(tag)
    return b.ocr(min_conf=0.3)


def show(it, tag):
    print('--- %s ---' % tag)
    for t in it:
        if 330 < t['cy'] < 1600:
            print('   %-30s %4d,%4d' % (t['text'][:30], t['cx'], t['cy']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cell')
    a = ap.parse_args()
    b = Bot(log_prefix='dv')
    log = []
    it = see(b, 'dv0')
    panel = any(('黄金宝库' in t['text'] or '黄全宝库' in t['text'] or '旅行商人' in t['text'])
                for t in it)
    print('面板已开:', panel)
    if panel:
        show(it, '当前面板')
        EL.popups(b, it, log, ctx={'marks': {}, 'tapped': None})
    else:
        if not EL.ensure_in_map(b, log):
            print('进图失败', log[-3:])
            return 1
        it = see(b, 'dv1')
        c = EL.cells_of(b.img(), mapname=EL.map_name(it))
        tgt = None
        for k, v in sorted(c['st'].items()):
            if v['anchor'] == k and v['name'] in ('黄金宝库', '旅行商人') and v['revealed']:
                tgt = (k, v)
                break
        if not tgt:
            print('本图没认出宝库/商人（或都未揭示）')
            return 1
        (r, cc), v = tgt
        x, y = EL.cell_center(r, cc)
        print('点 %s (%d,%d) @(%d,%d) 分数%.2f' % (v['name'], r, cc, x, y, v['score']))
        b.tap(x, y, wait=3.0)
        it = see(b, 'dv2')
        show(it, '点开后')
        EL.popups(b, it, log, ctx={'marks': {}, 'tapped': (x, y)})
    print('=== 动作日志 ===')
    for e in log:
        print('  ', e)
    it = see(b, 'dv_end')
    print('=== 结束面板 ===')
    for t in it:
        if 330 < t['cy'] < 1600:
            print('   %-30s %4d,%4d' % (t['text'][:30], t['cx'], t['cy']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
