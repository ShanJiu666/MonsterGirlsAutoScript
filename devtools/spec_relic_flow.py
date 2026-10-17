# -*- coding: utf-8 -*-
"""★ 勇者之墓（英灵使者）完整流程 —— 按真机实测的坐标与判据走一遍

这是**将来要搬进 `buypanels.py` 的原型**，所以：
  · 坐标全部来自实测（两次面板逐像素一致 ⇒ 可写死）
  · 唯一**不能**写死的是「结果框的确定」⇒ 必须 OCR 找（用户 2026-10-07 指出）
  · 每一步都截图留证 + 打印，便于人眼核对

实测坐标（720×1280）：
  格子点开后：  面板三行 / 必定成功(261,960) / 确定(458,960) / X(655,302)
  行1 点 (284,544)   行2 点 (286,674)   行3 点 (285,804)
  结果框：      「确定」必须 OCR 找（实测本次是 (360,770)，但会变）
"""
from __future__ import annotations

import io
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import cv2
import numpy as np
import spec_dev as D


REL = {                       # 面板元素（实测，720×1280）
    'row1': (284, 544),
    'row2': (286, 674),
    'row3': (285, 804),
    'ok': (458, 960),
    'x': (655, 302),
}
SHOT = r'runs\spec_dev\flow'


def say(*a):
    print(*a, flush=True)


def _ocr_items(img):
    """对**内存里的帧**做 OCR（用 rapidocr，最快那条路）"""
    from rapidocr_onnxruntime import RapidOCR
    global _ENG
    try:
        _ENG
    except NameError:
        _ENG = RapidOCR()
    h, w = img.shape[:2]
    # rapidocr 吃 ndarray（BGR）也行；为稳先落一个临时文件
    tmp = os.path.join(SHOT, '_ocr.png')
    cv2.imwrite(tmp, img)
    res, _ = _ENG(tmp)
    out = []
    for box, txt, conf in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append((txt, float(conf), int(sum(xs) / 4), int(sum(ys) / 4)))
    return out


def find_ok(img):
    """在结果框里找「确定」的坐标（**不能写死** ⇒ 每帧 OCR）"""
    for txt, conf, cx, cy in _ocr_items(img):
        if txt.strip() == '确定' and conf >= 0.5:
            return cx, cy
    return None


def main():
    os.makedirs(SHOT, exist_ok=True)
    ok, st = D.adb_ok()
    say('设备 %s ⇒ %s' % (D.DEV, st))
    if not ok:
        return 1

    # ── 第 0 步：先扫一遍，找到勇者之墓 ──────────────────────
    say()
    say('=' * 78)
    say('第 0 步：扫棋盘，找勇者之墓（SP=3）')
    say('=' * 78)
    img = D.shot('flow_f0_board', save=True)
    import spots as SP
    bd = SP.Board('S20003')
    board = bd.state(img)
    rows = SP.spot_rows() or {}
    px, x0, y0 = float(SP.GRID['cx']), float(SP.GRID['x0']), float(SP.GRID['y0'])
    target = None
    for (r, c), v in sorted(board.items()):
        sid = str(v.get('sid') or '')
        sp = int(((rows.get(sid) or {}).get('SpecialSpot')) or 0)
        if sp == 3:
            target = {
                'cell': (r, c), 'sid': sid, 'name': v.get('name'),
                'score': round(float(v.get('score') or 0), 3),
                'tap': (int(x0 + (c - 1) * px + px / 2),
                        int(y0 + (r - 1) * px + px / 2)),
                'revealed': bool(v.get('revealed')),
            }
            break
    if not target:
        say('  ✗ 没找到勇者之墓 ⇒ 退出（不猜）')
        return 2
    say('  ✓ 找到 %d,%d  %s  分=%s  已揭示=%s  点击=%s'
        % (target['cell'][0], target['cell'][1], target['name'],
           target['score'], target['revealed'], target['tap']))

    # ── 第 1 步：点开面板 ──────────────────────────────────
    say()
    say('=' * 78)
    say('第 1 步：点格子 %s ⇒ 开面板' % (target['tap'],))
    say('=' * 78)
    img = D.tap(target['tap'][0], target['tap'][1], 'flow_f1_panel')
    items = _ocr_items(img)
    has = any('英灵使者' in t for t, _c, _x, _y in items)
    say('  面板标题「英灵使者」认得吗？ %s' % ('✓' if has else '✗'))
    if not has:
        say('  ✗ 没开成面板 ⇒ 退出')
        return 3
    # 读三行的成功率（判据：取成功率最高的行）
    succ = [(t, cy, cx) for t, _c, cx, cy in items if '成功率' in t]
    say('  读到 %d 个"成功率"：%s' % (len(succ), [s[0] for s in succ]))

    # ── 第 2 步：选一行（优先 100%）────────────────────────
    say()
    say('=' * 78)
    say('第 2 步：选一行 —— 优先成功率 100% 的')
    say('=' * 78)
    # 三行固定坐标；「成功率100%」对应 y=593/722/851 ⇒ 行1/2/3
    any100 = any('100%' in s[0] for s in succ)
    pick_row = 1 if any100 else 1          # 简化：默认行1（若 100% 不在行1 再调）
    # 更严谨：按 y 找"100%"那行
    y2row = {593: 1, 722: 2, 851: 3}
    best = None
    for t, cy, cx in succ:
        if '100%' not in t:
            continue
        # cy 是"成功率"文字的 y；映射到行
        r = None
        for yy, rr in y2row.items():
            if abs(cy - yy) <= 12:
                r = rr
        if r:
            best = r
            break
    pick_row = best or 1
    say('  选中行 %d（成功率 100%% 的那行 %s）' % (pick_row, '(找到)' if best else '(没找到 ⇒ 默认行1)'))
    tap_xy = REL['row%d' % pick_row]
    img = D.tap(tap_xy[0], tap_xy[1], 'flow_f2_pick%d' % pick_row)
    say('  点了 (%d,%d)' % tap_xy)

    # ── 第 3 步：点「确定」─────────────────────────────────
    say()
    say('=' * 78)
    say('第 3 步：点「确定」%s' % (REL['ok'],))
    say('=' * 78)
    img = D.tap(REL['ok'][0], REL['ok'][1], 'flow_f3_ok')
    items = _ocr_items(img)
    got = [t for t, _c, _x, _y in items]
    say('  屏幕认到：%s' % got[:8])
    is_ok = any('事件成功' in t for t in got)
    is_fail = any('没能获得' in t for t in got)
    say('  ⇒ %s' % ('★ 事件成功 ✓' if is_ok else ('✗ 失败' if is_fail else '？未知')))
    reward = [t for t in got if '获得' in t]
    if reward:
        say('  奖励：%s' % reward)

    # ── 第 4 步：关结果框（**OCR 找确定，不能写死**）──────────
    say()
    say('=' * 78)
    say('第 4 步：关结果框 —— **OCR 找「确定」**（不能写死坐标）')
    say('=' * 78)
    p = find_ok(img)
    if not p:
        say('  ✗ 没 OCR 到「确定」⇒ 不盲点（退出，交人处理）')
        return 4
    say('  OCR 找到「确定」@ %s' % (p,))
    img = D.tap(p[0], p[1], 'flow_f4_result_ok')
    items = _ocr_items(img)
    gone = not any('事件成功' in t for t, _c, _x, _y in items)
    say('  结果框关掉了吗？ %s' % ('✓' if gone else '✗ 还在'))

    # ── 第 5 步：复扫，确认格子已消耗 ───────────────────────
    say()
    say('=' * 78)
    say('第 5 步：复扫棋盘，确认那一格结算了')
    say('=' * 78)
    board2 = bd.state(img)
    r, c = target['cell']
    v2 = board2.get((r, c)) or {}
    say('  %d,%d 现在 = %s %s 分=%s ratio=%s'
        % (r, c, v2.get('sid'), v2.get('name'),
           round(float(v2.get('score') or 0), 3),
           round(float(v2.get('ratio') or 0), 3)))
    still = int(((rows.get(str(v2.get('sid') or '')) or {}).get('SpecialSpot')) or 0) == 3
    say('  还是勇者之墓吗？ %s' % ('✗ 已变（= 结算成功 ✓）' if not still else '★ 还是（= 没结算 ✗）'))
    say()
    say('★ 流程走完。取证帧在 %s\\flow_*.png' % SHOT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
