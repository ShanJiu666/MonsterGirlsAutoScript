# -*- coding: utf-8 -*-
"""诊断3: 点 结束冒险(540,773) -> 确认框 -> 确定 -> 看是否回主界面"""
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


b = Bot(log_prefix='diag3')


def dump(tag):
    b.snap(tag)
    items = b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        print("  %-20s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))
    return items


b.tap(540, 773, wait=3)
dump('d3_1_after_end_click')

# 确认框: 确定在 (774,1113)
items = b.ocr()
cand = [it for it in items if it['text'] == '确定']
print('>>> 确定候选:', [(c['cx'], c['cy']) for c in cand])
if cand:
    c = max(cand, key=lambda z: z['cy'])
    b.tap(c['cx'], c['cy'], wait=5)
    dump('d3_2_after_confirm')
    b.snap('d3_3_wait5')
    time.sleep(4)
    dump('d3_4_final')
