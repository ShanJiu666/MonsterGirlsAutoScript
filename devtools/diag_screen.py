# -*- coding: utf-8 -*-
"""诊断: 实时抓屏 + OCR 全量 dump(带坐标), 定位「结束冒险」按钮"""
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


b = Bot(log_prefix='diag')
b.snap('diag_now')
items = b.ocr()
print('=== OCR items (%d) ===' % len(items))
for it in items:
    print("%-28s cx=%4d cy=%4d conf=%.2f" % (it['text'], it['cx'], it['cy'], it.get('conf', 0)))
print('=== done ===')
