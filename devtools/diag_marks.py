# -*- coding: utf-8 -*-
"""diag_marks.py · 实机采样：进图 -> 扫 4 个标记 -> 点开命中格 -> dump 面板

目的（2026-09-24 新策略）：
  1) 验证 marks.scan_board 在实机跑得动、不误报
  2) 拿到「boss 关弹窗」的真实版面 —— 它的「战斗」按钮位置与普通格不同（用户口径）
  3) 拿到商人格/宝库面板的按钮文字，供「买完」流程用

产出：runs/diag_marks.json（每轮标记 + 面板 OCR 全量）+ runs/dm_*.png 截图
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
from explore_loop import (classify_cells, enter_map, exact_btn, find_btn,
                          in_map, pick_btn)


OUT = os.path.join(RUNS, 'diag_marks.json')


def dump_items(items):
    return [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy']} for i in items]


def main():
    b = Bot(log_prefix='dm')
    log = []

    b.snap('dm0')
    items = b.ocr()
    if not in_map(b, b.img(), items):
        if not enter_map(b, log):
            print('ENTER FAILED')
            return
    time.sleep(3)

    opened = False
    for rnd in range(14):
        b.snap('dm_r%02d' % rnd)
        img = b.img()
        items = b.ocr()
        mk = marks_mod.scan_board(img)
        log.append({'round': rnd,
                    'marks': {'%d,%d' % k: v['marks'] for k, v in mk.items()},
                    'score': {'%d,%d' % k: v['score'] for k, v in mk.items()}})

        # 先处理已知弹窗（用简单规则，避免干扰采样）
        if find_btn(items, '探索产出'):
            act = None
            for it in items:
                if '探索' in it['text'] and it['cy'] > 620 and '探索产出' not in it['text']:
                    act = it
                    break
            if act:
                b.tap(act['cx'], act['cy'], wait=3)
                log.append({'act': 'explore', 'at': (act['cx'], act['cy'])})
                continue

        if mk and not opened:
            cell = sorted(mk.keys())[0]
            cx, cy = marks_mod.cell_center(*cell)
            log.append({'tap_marked_cell': cell, 'marks': mk[cell]['marks'],
                        'at': (cx, cy)})
            b.tap(cx, cy, wait=3)
            b.snap('dm_panel')
            pimg = b.img()
            pitems = b.ocr(min_conf=0.35)
            log.append({'panel': dump_items(pitems)})
            cv2.imencode('.png', pimg)[1].tofile(
                os.path.join(RUNS, 'dm_panel_%d%d.png' % cell))
            # 面板里所有按钮候选位置
            log.append({'panel_buttons': [
                {'t': i['text'], 'cx': i['cx'], 'cy': i['cy']}
                for i in pitems if i['cy'] > 600 and len(i['text']) <= 6]})
            opened = True
            break

        # 没有标记就揭格推进
        cells = classify_cells(pimg if False else img, bot=b)
        cand = [(c[0], c[1]) for c in cells['light'] if c[2] == 'none']
        cand += [(c[0], c[1]) for c in cells['gray'][:2]]
        if not cand:
            log.append({'act': 'no_cand', 'gray': len(cells['gray']),
                        'light': len(cells['light'])})
            break
        b.tap(cand[0][0], cand[0][1], wait=2.5)
        log.append({'act': 'reveal', 'at': cand[0]})

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print('DIAG:', OUT)


if __name__ == '__main__':
    main()
