# -*- coding: utf-8 -*-
"""diag_prophecy.py · 定位「预言石板」面板的正确操作（选卡 -> 确定）

当前游戏应停在预言石板面板上。脚本：
  1) OCR 现状
  2) 依次点三张卡的中心 -> 每次对比卡片区域像素变化（判断有没有选中）
  3) 点「确定」-> 判断面板是否消失
把每步结果写成 JSON（UTF-8），不依赖控制台中文。
"""
import json
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
import cv2
import numpy as np
from mapbot import Bot
from explore_loop import diff_at, exact_btn, find_btn


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs', 'diag_prophecy.json')

CARDS = [(211, 880), (540, 880), (869, 880)]
CARDS_ICON = [(211, 760), (540, 760), (869, 760)]


def texts(b):
    return [i['text'] for i in b.ocr()]


def main():
    b = Bot(log_prefix='dp')
    rep = {'steps': []}

    b.snap('dp0')
    img0 = b.img()
    t0 = texts(b)
    rep['steps'].append({'step': 'init', 'texts': t0,
                         'has_panel': bool(find_btn(t0 and b.ocr(), '预言石板'))})

    def note(tag, extra):
        rep['steps'].append(dict({'step': tag}, **extra))

    # 1) 点卡面中心
    for i, (cx, cy) in enumerate(CARDS):
        b.tap(cx, cy, wait=1.0)
        b.snap('dp_card%d' % i)
        img = b.img()
        d = diff_at(img0, img, cx, cy, r=140)
        note('tap_card_body', {'idx': i, 'at': (cx, cy), 'diff': round(d, 4)})

    b.snap('dp_after_cards')
    t1 = texts(b)
    note('after_card_bodies', {'texts': t1})

    # 2) 点确定
    ok = exact_btn(b.ocr(), '确定')
    if ok:
        b.tap(ok['cx'], ok['cy'], wait=2.5)
        b.snap('dp_ok1')
        t2 = texts(b)
        note('tap_ok', {'at': (ok['cx'], ok['cy']), 'texts': t2,
                        'panel_gone': not any('预言石板' in x for x in t2)})
    else:
        note('tap_ok', {'found': False})

    # 3) 若还在面板上，试「点图标区 -> 确定」
    t3 = texts(b)
    if any('预言石板' in x for x in t3):
        for i, (cx, cy) in enumerate(CARDS_ICON):
            b.tap(cx, cy, wait=1.0)
            note('tap_card_icon', {'idx': i, 'at': (cx, cy)})
        ok = exact_btn(b.ocr(), '确定')
        if ok:
            b.tap(ok['cx'], ok['cy'], wait=2.5)
        b.snap('dp_ok2')
        t4 = texts(b)
        note('after_icon_flow', {'texts': t4,
                                 'panel_gone': not any('预言石板' in x for x in t4)})

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print('DIAG:', OUT)


if __name__ == '__main__':
    main()
