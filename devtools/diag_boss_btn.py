# -*- coding: utf-8 -*-
"""diag_boss_btn.py · 交互式探针：boss 面板的「战斗」到底怎么点得动

备选动作依次试（每次试完看面板有没有消失）：
    1) 单击按钮中心 (535,755)
    2) 长按按钮中心
    3) 单击按钮下沿 (535,800) / 上沿 (535,700)
    4) 长按按钮下沿
    5) 单击「战斗」文字 OCR 位置
每步都 dump OCR（抓「能量不足 / 需要相邻队伍」这类提示）。
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
import marks as marks_mod
from mapbot import Bot, RUNS, ADB, DEV
from explore_loop import (classify_cells, enter_map, find_btn, in_map, lp)


OUT = os.path.join(RUNS, 'diag_boss_btn.json')


def texts(b):
    return [i['text'] for i in b.ocr()]


def main():
    b = Bot(log_prefix='dbb')
    log = []
    b.snap('dbb0')
    items = b.ocr()
    if not in_map(b, b.img(), items):
        if not enter_map(b, log):
            print('ENTER FAILED')
            return
    time.sleep(3)

    # 找 boss 格并点开面板
    panel_open = False
    for rnd in range(20):
        b.snap('dbb_r%02d' % rnd)
        img = b.img()
        it = b.ocr()
        if find_btn(it, '战斗事件'):
            panel_open = True
            break
        mk = marks_mod.scan_board(img)
        if mk:
            cell = sorted(mk.keys())[0]
            cx, cy = marks_mod.cell_center(*cell)
            log.append({'try_open': cell, 'marks': mk[cell]['marks'], 'at': [cx, cy]})
            b.tap(cx, cy, wait=3)
            it2 = texts(b)
            if '战斗事件' in it2:
                panel_open = True
                break
        cells = classify_cells(img, bot=b)
        nones = [(c[0], c[1]) for c in cells['light'] if c[2] == 'none']
        if not nones:
            log.append({'reveal': 'none_left'})
            break
        b.tap(nones[0][0], nones[0][1], wait=2.5)
        log.append({'reveal': nones[0]})

    if not panel_open:
        log.append({'result': 'no_panel'})
        open(OUT, 'w', encoding='utf-8').write(json.dumps(log, ensure_ascii=False, indent=1))
        print('NO PANEL:', OUT)
        return

    cv2.imencode('.png', b.img())[1].tofile(os.path.join(RUNS, 'dbb_panel.png'))
    log.append({'panel': 'opened', 'texts': texts(b)[:40]})

    acts = [
        ('tap', 535, 755), ('hold', 535, 755),
        ('tap', 535, 800), ('tap', 535, 700),
        ('hold', 535, 800), ('hold', 535, 700),
        ('tap', 470, 755), ('tap', 600, 755),
    ]
    for i, (kind, x, y) in enumerate(acts):
        if kind == 'tap':
            b.tap(x, y, wait=2.5)
        else:
            lp(x, y, ms=900)
        t = texts(b)
        gone = '战斗事件' not in t
        log.append({'act': kind, 'at': [x, y], 'i': i, 'panel_gone': gone,
                    'texts': t[:30]})
        cv2.imencode('.png', b.img())[1].tofile(
            os.path.join(RUNS, 'dbb_after_%d_%s.png' % (i, kind)))
        if gone:
            log.append({'result': 'SUCCESS', 'act': kind, 'at': [x, y]})
            break
    else:
        log.append({'result': 'all_failed'})

    open(OUT, 'w', encoding='utf-8').write(json.dumps(log, ensure_ascii=False, indent=1))
    print('DIAG:', OUT)


if __name__ == '__main__':
    main()
