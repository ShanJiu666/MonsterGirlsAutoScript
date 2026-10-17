# -*- coding: utf-8 -*-
"""hunt_vault.py · 连刷地图直到遇到「黄金宝库 / 旅行商人」，跑买完流程并打印结果

用法:
    python hunt_vault.py --maps 6          # 最多刷 6 张图
    python hunt_vault.py --maps 3 --kind 旅行商人
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
import buypanels as BP
import explore_loop as EL
from mapbot import Bot



def classify(b, log):
    b.snap('hv')
    it = b.ocr()
    mn = EL.map_name(it)
    c = EL.cells_of(b.img(), mapname=mn)
    return mn, it, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--maps', type=int, default=5)
    ap.add_argument('--kind', default='黄金宝库')
    ap.add_argument('--deadline', type=int, default=300)
    a = ap.parse_args()
    b = Bot(log_prefix='hv')
    log = []
    for i in range(a.maps):
        if not EL.ensure_in_map(b, log):
            print('第%d张：进图失败' % i, log[-3:])
            break
        mn, it, c = classify(b, log)
        names = []
        for k, v in sorted(c['st'].items()):
            if v['anchor'] == k and v['name'] in ('黄金宝库', '旅行商人'):
                names.append((k, v['name'], v['revealed'], v['score']))
        print('第%d张 %s：买完目标 %s' % (i, mn, names))
        if not any(n[1] == a.kind for n in names):
            EL.finish_map(b, log)
            continue
        # 点开目标格
        for (k, nm, rev, sc) in names:
            if nm != a.kind:
                continue
            cx, cy = EL.cell_center(k[0], k[1])
            print('  点 %s (%d,%d) @(%d,%d) 已揭示=%s' % (nm, k[0], k[1], cx, cy, rev))
            b.tap(cx, cy, wait=3.0)
            b.snap('hv_open')
            it2 = b.ocr(min_conf=0.3)
            print('  面板:', [t['text'] for t in it2 if 330 < t['cy'] < 1560][:8])
            if a.kind == '黄金宝库':
                n = BP.vault_flow(b, log)
            else:
                n = BP.merchant_flow(b, log)
            print('  完成，动作数 %s' % n)
            for e in log[-14:]:
                print('    ', e)
        b.snap('hv_after')
        it3 = b.ocr(min_conf=0.3)
        print('  收尾面板:', [t['text'] for t in it3 if 330 < t['cy'] < 1560][:6])
        EL.finish_map(b, log)
        break
    return 0


if __name__ == '__main__':
    sys.exit(main())
