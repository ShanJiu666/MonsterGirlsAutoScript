# -*- coding: utf-8 -*-
"""diag_dice.py · 采样「大拇指（推荐）战斗」打完后的摇色子界面

流程：进图 -> 扫标记 -> 找 recommend 格 -> 沿路揭格解锁 -> 点开 -> 打 ->
      打完**不停手**，每 1.5s 抓一帧（截图 + OCR 全量）共 ~24s，
      把摇色子/重摇/确定这类按钮的位置量出来。
产出：runs/diag_dice.json + runs/dice_XX.png
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
from mapbot import Bot, RUNS
from explore_loop import (classify_cells, enter_map, find_btn, in_map,
                          find_fight_btn, start_fight)


OUT = os.path.join(RUNS, 'diag_dice.json')


def texts(b, mc=0.35):
    return [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy'], 'conf': i['conf']}
            for i in b.ocr(min_conf=mc)]


def main():
    b = Bot(log_prefix='dd')
    log = []
    b.snap('dd0')
    items = b.ocr()
    if not in_map(b, b.img(), items):
        if not enter_map(b, log):
            print('ENTER FAILED')
            return
    time.sleep(3)

    fought = False
    for rnd in range(24):
        b.snap('dd_r%02d' % rnd)
        img = b.img()
        it = b.ocr()
        mk = marks_mod.scan_board(img)
        log.append({'round': rnd, 'marks': {'%d,%d' % k: v['marks'] for k, v in mk.items()}})
        rec = [k for k, v in mk.items() if 'recommend' in v['marks']]
        if find_btn(it, '【正面】', '【负面】'):
            # 战斗结算（可能是摇色子前的界面）-> 停手，连续采样
            log.append({'stage': 'result_or_dice', 'texts': texts(b)})
            for j in range(16):
                time.sleep(1.5)
                b.snap('dd_dice%02d' % j)
                cv2.imencode('.png', b.img())[1].tofile(
                    os.path.join(RUNS, 'dice_%02d.png' % j))
                log.append({'dice_frame': j, 'texts': texts(b)})
            break
        if find_btn(it, '战斗事件'):
            f = find_fight_btn(it) or {'cx': 541, 'cy': 735}
            log.append({'fight': 'try', 'at': (f['cx'], f['cy']),
                        'marks': mk.get(next((k for k in mk), (0, 0)), {})})
            if start_fight(b, log, f):
                fought = True
            continue
        if rec:
            cell = sorted(rec)[0]
            cx, cy = marks_mod.cell_center(*cell)
            cells = classify_cells(img, bot=b)
            light = {(c[0], c[1]) for c in cells['light']}
            if (cx, cy) in light or rnd > 8:
                b.tap(cx, cy, wait=3)
                log.append({'tap_recommend': cell, 'at': [cx, cy]})
                continue
        cells = classify_cells(img, bot=b)
        nones = [(c[0], c[1]) for c in cells['light'] if c[2] == 'none']
        if rec and nones:
            tgt = [marks_mod.cell_center(*k) for k in rec]
            nones.sort(key=lambda p: min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in tgt))
            b.tap(nones[0][0], nones[0][1], wait=2.5)
            log.append({'reveal': nones[0]})
            continue
        log.append({'idle': True, 'gray': len(cells['gray']), 'light': len(cells['light'])})
        break

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print('DIAG:', OUT, 'fought=', fought)


if __name__ == '__main__':
    main()
