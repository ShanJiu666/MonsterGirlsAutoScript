# -*- coding: utf-8 -*-
"""诊断13: 实测临时背包界面 - 找「全部领取」按钮"""
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
from mapbot import Bot
from explore_loop import exact_btn


b = Bot(log_prefix='diag13')


def dump(tag):
    b.snap(tag)
    items = b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        print("  %-22s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))
    return items


dump('d13_0_state')
items = b.ocr()
bag = [it for it in items if '背包' in it['text']]
print('>>> 背包按钮:', [(c['cx'], c['cy']) for c in bag])
if bag:
    b.tap(bag[0]['cx'], bag[0]['cy'], wait=2.5)
    dump('d13_1_bag_open')
