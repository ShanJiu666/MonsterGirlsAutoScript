# -*- coding: utf-8 -*-
"""诊断14: 采样战斗结算面板 - 打一场战斗, 停在结算界面 dump UI 结构"""
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
from mapbot import Bot
from explore_loop import (classify_cells, exact_btn, enter_map, find_btn,
                          pick_btn, _action_btn, close_red_x_panels, diff_at)


b = Bot(log_prefix='diag14')
RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')


def dump(tag, img=None):
    b.snap(tag) if img is None else None
    items = b.ocr(img=img) if img is not None else b.ocr()
    print('=== %s ===' % tag)
    for it in items:
        print("  %-24s cy=%4d cx=%4d conf=%.2f" %
              (it['text'], it['cy'], it['cx'], it.get('conf', 0)))
    return items


# 1) 进图
img = b.fast_snap() if hasattr(b, 'fast_snap') else b.img()
items = b.ocr()
if not exact_btn(items, '结束冒险'):
    if not enter_map(b, []):
        print('ENTER FAILED')
        sys.exit(1)
time.sleep(4)

# 2) 扫格: 找战斗事件面板
found_fight = False
for rnd in range(50):
    b.snap('s%03d' % rnd)
    img = b.img()
    items = b.ocr()
    if find_btn(items, '战斗事件'):
        print('>>> 找到战斗事件面板!')
        dump('s_fight_panel')
        fight = _action_btn(items, '战斗', exclude='战斗事件')
        if fight is None:
            # OCR 兜底: 战斗按钮艺术字常被误识(「卡彈」), 用固定位置
            anchor = find_btn(items, '战斗事件')
            px = 806 if anchor['cx'] > 540 else 275
            fight = {'cx': px, 'cy': 735}
            print('>>> OCR 未识别战斗按钮, 用位置兜底', px, 735)
        b.tap(fight['cx'], fight['cy'], wait=2)
        found_fight = True
        break
    if find_btn(items, '探索产出'):
        act = _action_btn(items, '探索', exclude='探索产出')
        if act:
            b.tap(act['cx'], act['cy'], wait=2)
        else:
            close_red_x_panels(b, img)
        continue
    ok = exact_btn(items, '确定')
    if ok and ok['cy'] > 900 and exact_btn(items, '取消') is None:
        b.tap(ok['cx'], ok['cy'], wait=2)
        continue
    # 点一个浅色格推进
    cells = classify_cells(img, bot=b)
    cands = ([(c[0], c[1]) for c in cells['light'] if c[2] == 'none'] +
             [(c[0], c[1]) for c in cells['light'] if c[2] != 'none'] +
             [(c[0], c[1]) for c in cells['gray'][:3]])
    cands = [c for c in cands]
    if not cands:
        print('>>> 没有可点格了 (没遇到战斗)')
        break
    cx, cy = cands[0]
    b.tap(cx, cy, wait=2)

if not found_fight:
    print('!!! 本轮没遇到战斗事件, 结束')
    sys.exit(0)

# 3) 等战斗结束 -> 结算面板
print('>>> 等待战斗结算...')
time.sleep(6)
for i in range(40):
    b.snap('res%02d' % i)
    img = b.img()
    items = b.ocr()
    if find_btn(items, '战斗胜利', '战斗失败') or \
            (find_btn(items, '关闭') and find_btn(items, '战斗')):
        break
    close = find_btn(items, '关闭')
    if close and i > 6:
        break
    time.sleep(2)

# 4) 停在结算界面: 详细 dump + 保存高清截图
b.snap('RESULT_PANEL')
img = b.img()
cv2.imwrite(os.path.join(RUNS, 'battle_result_sample.png'), img)
print('=== 结算面板 OCR 全量 ===')
items = b.ocr(min_conf=0.35)
for it in items:
    print("  %-24s cy=%4d cx=%4d" % (it['text'], it['cy'], it['cx']))
print('>>> 截图已存 runs/battle_result_sample.png, 脚本停止(界面保留)')
