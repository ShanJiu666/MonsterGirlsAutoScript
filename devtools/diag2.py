# -*- coding: utf-8 -*-
"""诊断2: 验证 结束冒险 -> 确认弹窗 -> 回主界面 全链路, 并 dump 每步 OCR"""
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


b = Bot(log_prefix='diag2')


def dump(tag):
    b.snap(tag)
    items = b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        print("  %-20s cx=%4d cy=%4d" % (it['text'], it['cx'], it['cy']))
    return items


# step1: 当前是确认框, 先点「取消」回到地图界面, 看真实「结束冒险」按钮在哪
dump('d2_0_before_cancel')
b.tap(305, 1113, wait=3)
dump('d2_1_after_cancel')

# step2: 在地图界面上找「结束冒险」按钮(排除问句文本)
items = dump('d2_2_map')
cand = [it for it in items if '结束冒险' in it['text']]
print('>>> 结束冒险候选:', [(c['text'], c['cx'], c['cy']) for c in cand])
