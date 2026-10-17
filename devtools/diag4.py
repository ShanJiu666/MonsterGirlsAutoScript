# -*- coding: utf-8 -*-
"""诊断4: 从主界面点「进入地图」-> 逐步 dump, 摸清进图弹窗链路"""
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
import time

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
from mapbot import Bot


b = Bot(log_prefix='diag4')


def dump(tag):
    b.snap(tag)
    items = b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        print("  %-22s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))
    return items


dump('d4_0_menu')
ent = [it for it in b.ocr() if '进入地图' in it['text']]
print('>>> 进入地图:', [(c['cx'], c['cy']) for c in ent])
if ent:
    e = ent[0]
    b.tap(e['cx'], e['cy'], wait=3)
    dump('d4_1_after_enter')
    time.sleep(3)
    dump('d4_2_wait3')
