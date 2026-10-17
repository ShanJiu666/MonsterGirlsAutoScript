# -*- coding: utf-8 -*-
"""★ 回归：实时棋盘的**三条 UI 改动**（2026-10-13 用户要求）

用户原话（一次说三条）：
  「**实时棋盘那边的第3张图，体力金币幸运草那行去掉，下面的计划/进度也删掉，
    棋盘稍微放大一点**」

① 画布内标题行（`第N张图 · 体力 x · 金币 y · 幸运草 z · 消耗 c`）—— **去掉**
② 棋盘卡下方那行说明小字（`计划/进度＝实时 ✓ ｜ 格名/雾格＝进图 ~1s 快照`）—— **删掉**
③ 棋盘**放大**（`BOARD_CELL` 48 → 54）

---- 空间账（关键：**日志区没被牺牲** ✓）----
    删标题行 ⇒ 画布内 -24px（`_BHEADER` 24 → 0）
    删说明行 ⇒ 卡内   -25px
    格子 48→54 ⇒ 画布内 +30px（5 行 × 6px）
    ────────────────────────────
    净效果   ⇒ 日志区 **+19px**（用户最在意的那个区 ✓）

⚠ 本回归**只测这三条**；"锁机制已删"在 `verify_lock_kind.py`、
  "配置按设备绑定"在 `verify_prefs_per_device.py`（各管各的 ✓）
"""
import io
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import tkinter as tk

import bot_gui
import bot_gui_ui.theme as TH
import bot_gui_ui.widgets as W


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('实时棋盘三条 UI 改动（2026-10-13）')
print('=' * 94)

print()
print('【1】结构级')
ck('① `BoardCanvas` **没有** `_draw_header`（标题行已去 ✓）',
   not hasattr(W.BoardCanvas, '_draw_header'))
ck('② `_round_text` / `_cost_text` 已删（它们只服务标题行 ✓）',
   not hasattr(W, '_round_text') and not hasattr(W, '_cost_text'))
ck('③ `_BHEADER` = 0（标题行不留高度 ✓）', W._BHEADER == 0, str(W._BHEADER))
ck('④ `BOARD_CELL` = 54（放大 ✓）', TH.BOARD_CELL == 54, str(TH.BOARD_CELL))

print()
print('【2】⭐⭐ 行为级：真建窗量尺寸')
root = tk.Tk()
app = bot_gui.App(root)
root.update()
bd = app.board

_got_w = bd._px_w()
_got_h = bd._px_h()
print('     cell=%d ｜ 画布 = %dx%d' % (bd.cell, _got_w, _got_h))
ck('⑤ ⭐ 格子 = 54（比原来 48 大 ✓）', bd.cell == 54, '%d' % bd.cell)
ck('⑥ ⭐ `_px_h` **不再含** `_BHEADER`（= 5*cell + 2*_BPAD ✓）',
   _got_h == bd.ROWS * bd.cell + 2 * W._BPAD, '%d' % _got_h)
ck('⑦ ⭐ 画布高 = 5*54+16 = **286**（原 280 ✓）', _got_h == 286, '%d' % _got_h)
_avail = TH.LEFT_CARD_W - 2 * TH.PAD_CARD
ck('⑧ ⚠ 画布宽 %d **不超过**卡内可用宽 %d（不会撑破卡 ✓）' % (_got_w, _avail),
   _got_w <= _avail, '%d <= %d' % (_got_w, _avail))

# ① 画布内**不再**有"体力/金币/幸运草/第N张图"
#    ⚠ 必须**先喂一份带 hud 的数据**再查 —— 否则"没画"可能只是因为没数据 ✗（防假绿）
try:
    bd.update_board(board={}, marks={}, order=[], cost=13,
                    hud={'round': 2, 'stamina': 214, 'gold': 4304959,
                         'clover': 673})
    root.update()
    _fed = True
except Exception as _e:     # noqa: BLE001
    _fed = False
    ck('⑨ 喂 `hud` 不抛', False, repr(_e)[:100])
if _fed:
    _txts = []
    for _it in bd.find_all():
        try:
            _t = bd.itemcget(_it, 'text')
            if _t:
                _txts.append(_t)
        except Exception:       # noqa: BLE001
            pass
    _all_txt = ' '.join(_txts)
    print('     喂 hud 后画布内文字 = %r' % (_all_txt[:160],))
    ck('⑨ ⭐⭐ 画布内**没有**「体力/金币/幸运草/第 N 张图」（标题行已去 ✓）',
       not any(k in _all_txt for k in ('体力', '金币', '幸运草', '张图')))

# ② 卡内那行说明小字没了
def _all_text(w, out=None):
    if out is None:
        out = []
    for _a in ('text', 'textvariable'):
        try:
            out.append(str(w.cget(_a)))
        except Exception:       # noqa: BLE001
            pass
    for _c in w.winfo_children():
        _all_text(_c, out)
    return out


_t = _all_text(root)
_hit = [x for x in _t if '计划/进度' in x]
print('     窗口里含「计划/进度」的控件 = %s' % (_hit or '无 ✓'))
ck('⑩ ⭐ 那行说明小字**已删**', not _hit, str(_hit[:2]))

print()
print('【3】⚠⚠ 反向：**只删该删的**（别删过头 ✗）')
ck('⑪ ⚠ `plan_var`（计划行）**仍在** —— 用户只让删"那行小字" ✓',
   hasattr(app, 'plan_var'),
   str(getattr(app, 'plan_var', None) and app.plan_var.get())[:50])
ck('⑫ ⚠ `prog_var`（进度行）**仍在** ✓', hasattr(app, 'prog_var'))
ck('⑬ ⚠ `hud_var`（右卡那行体力/金币）**仍在** —— 用户指的是棋盘里那行 ✓',
   hasattr(app, 'hud_var'), str(getattr(app, 'hud_var', None)
                                and app.hud_var.get())[:60])
ck('⑭ ⚠ 棋盘**仍画得出图元**（没被删空 ✓）', len(bd.find_all()) > 0,
   '%d 个' % len(bd.find_all()))
# ⚠ 反向：`_Tip` 悬浮提示还在（说明文字删了，但鼠标悬停仍能看到 ✓）
_tip_src = io.open('bot_gui.py', encoding='utf-8').read()
ck('⑮ ⚠ 棋盘的 `_Tip` 悬浮提示**保留**（删的是常驻小字 ✓）',
   '_Tip(self.board' in _tip_src)
root.destroy()

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
