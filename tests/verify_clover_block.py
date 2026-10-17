# -*- coding: utf-8 -*-
"""verify_clover_block.py · 回归：**幸运草 <8 ⇒ 纯大拇指格拉黑不去打**（用户口径）

用户 2026-10-05 原话（三条）：
  ①「**之前那个幸运草低于8不摇色子，改成低于8连直接把大拇指目标都拉黑，直接不去打了**」
  ②「**也是幸运草大于8就自动不拉黑去打**」
  ③「**金币幸运草都是一张图只确认一次**」

为什么要拉黑（用户口径的推论）：
  大拇指格（推荐战）的**唯一价值**就是打完摇色子出装备 ⇒ 幸运草不够 ⇒ 摇了也白摇
  ⇒ **整格没价值** ⇒ 不该花体力去打 ✓

⚠⚠ 关键边界：**只摘"纯大拇指"格**（`marks == ['recommend']`）
  真机帧 `_verify/marks_720_map12_183432.png` 上实测：
    `(1,5)` = `['boss','recommend']`  ← **同一格既有首领又有大拇指**
    `(3,3)` = `['recommend']`         ← 纯大拇指
  ⇒ `(1,5)` **必须保留**（`boss` 是**必打**目标，与幸运草无关；打它照样该打，
     只是**打完别摇色子** —— 那由 `handle_dice` 里那道闸门管 ✓）
  ⇒ 我第一版把 `['boss','recommend']` 也整格剔了 ⇒ **会漏打首领** ✗✗（本门禁守住）

「一图只确认一次」（口径 ③）：
  `_lock_hud_once()` 把金币/幸运草**首次读到的有效值锁进 `st`**，之后一律用锁定值。
  为什么必须锁：HUD 那块常被面板/横幅盖住 ⇒ 每轮重读会让同一张图里的判断**反复翻转**
  （目标一会儿拉黑一会儿放回 ✗）。与既有范式一致（`st['claim_checked']` 同款 ✓）

牙齿：把判据改回 `'recommend' in marks`（含 boss 的也摘）⇒ 本门禁必红 ✓
"""
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


os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

V = os.path.join(HERE, '_verify')
FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import cv2
    import numpy as np
    import explore_loop as EL
    import marks as marks_mod

    print('=== 幸运草 <8 ⇒ 纯大拇指格拉黑不去打（用户口径）===')

    # ── ① 三条口径都在源码里 ────────────────────────────────────────
    print()
    print('【1】三条口径都落地')
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()
    ck('① 有 `recommend_blocked_low_clover`（拉黑日志）',
       'recommend_blocked_low_clover' in src)
    ck('① 判据是 **`_mks == [\'recommend\']`**（**纯大拇指**才摘 ⇒ 带 boss 的保留 ✓）',
       "_mks == ['recommend']" in src)
    ck('② 幸运草够 ⇒ `_removed` 为空（`clover_block` 为 False ⇒ 不摘任何格 ✓）',
       "st['clover_block'] = (not clover_enough(st))" in src)
    ck('③ `_lock_hud_once` 存在（一图只确认一次 ✓）',
       'def _lock_hud_once(' in src)
    ck('③ 它锁 `gold_locked` 与 `clover_locked` **两个**',
       "'gold_locked'" in src and "'clover_locked'" in src)
    _l = [n for n, l in enumerate(lines) if l.startswith('def _lock_hud_once(')][0]
    _le = [n for n, l in enumerate(lines) if n > _l and l.startswith('def ')][0]
    _lb = '\n'.join(lines[_l:_le])
    ck('③ 锁定判据是 `is None`（**只锁一次**；已有值就不覆盖 ✓）',
       _lb.count('is None') >= 2, '`is None` 出现 %d 次' % _lb.count('is None'))

    # ── ② 顺序：剔除必须在 `mk` 扫描之后、`marked` 之前 ──────────────
    print()
    print('【2】剔除的位置（必须在 `mk` 扫完**之后**、`marked` **之前**）')
    s = [n for n, l in enumerate(lines) if l.startswith('def one_round(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    i_mk = next(n for n in range(s, e) if 'mk = marks_mod.scan_board' in lines[n])
    i_rm = next(n for n in range(s, e) if 'recommend_blocked_low_clover' in lines[n])
    i_md = next(n for n in range(s, e) if 'marked = [marks_mod.cell_center' in lines[n])
    ck('`mk` 扫描（%d）< 剔除（%d）< `marked`（%d）' % (i_mk + 1, i_rm + 1, i_md + 1),
       i_mk < i_rm < i_md)

    # ── ③ 真机帧：行为逐值核对（核心）───────────────────────────────
    print()
    print('【3】真机帧行为核对（`marks_720_map12_183432.png`：`(1,5)`=boss+recommend、'
          '`(3,3)`=recommend）')
    p = os.path.join(V, 'marks_720_map12_183432.png')
    if not os.path.exists(p):
        print('      （缺基准帧 ⇒ 跳过本段）')
    else:
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        mk0 = marks_mod.scan_board(im)
        rec = sorted('%d,%d' % k for k, v in mk0.items()
                     if 'recommend' in (v.get('marks') or []))
        ck('基准帧上认到的大拇指格 = `(1,5)` + `(3,3)`', rec == ['1,5', '3,3'], str(rec))
        ck('且 `(1,5)` 确实是 **boss+recommend**（同一格）⇒ 它必须被保留 ✓',
           sorted((mk0.get((1, 5)) or {}).get('marks') or []) == ['boss', 'recommend'],
           str((mk0.get((1, 5)) or {}).get('marks')))
        # 逐值核对（复现剔除判据，逐字与源码一致）
        # ⚠ 2026-10-09 阈值 8→10（用户：「幸运草阈值都改成10」）⇒ 边界值跟着改 ✓
        #   ⛔ 不许写死 `8: []` —— 那正是本轮改动后假红的原因 ✗
        #   ⇒ 用**常量**表达边界：`TH` 以下剔除、`TH` 及以上保留 ✓
        TH = int(EL.CLOVER_MIN_REROLL)
        expect = {1: ['3,3'], TH - 1: ['3,3'], TH: [], 20: [], None: []}
        #   ⚠ 若 `TH-1 == 1` 会撞键 ⇒ 去重时以"更严格的期望"为准（都剔除，无影响 ✓）
        for cv_val, want in expect.items():
            st = {'clover_locked': cv_val}
            blocked = not EL.clover_enough(st)
            mk2 = {k: dict(v) for k, v in mk0.items()}
            removed = []
            if blocked:
                for rc in list(mk2):
                    _mks = list((mk2[rc] or {}).get('marks') or [])
                    if _mks == ['recommend']:
                        removed.append('%d,%d' % rc)
                        del mk2[rc]
            got = sorted(removed)
            ck('幸运草=%-5s ⇒ 剔除 %-10s（保留 %s）'
               % (cv_val, got or '无',
                  sorted('%d,%d' % k for k in mk2)), got == want, '期望 %s' % want)
        # 关键：带 boss 的那格**任何情况下都留着**
        for cv_val in (1, TH - 1):
            st = {'clover_locked': cv_val}
            mk2 = {k: dict(v) for k, v in mk0.items()}
            for rc in list(mk2):
                if list((mk2[rc] or {}).get('marks') or []) == ['recommend']:
                    del mk2[rc]
            ck('⭐ 幸运草=%s 时 **`(1,5)`（首领+大拇指）仍然保留**'
               '（boss 必打，与幸运草无关 ✓；只是不摇色子）' % cv_val,
               (1, 5) in mk2)

    # ── ④ 保守方向：读不到 ⇒ 不拉黑 ─────────────────────────────────
    print()
    print('【4】保守方向（读不到不能变成"永远不打大拇指" ✗）')
    ck('`clover_enough({"clover_locked": None})` = **True**（不拉黑 ⇒ 正常去打 ✓）',
       EL.clover_enough({'clover_locked': None}) is True)
    ck('`clover_enough({"clover_locked": %d})` = False' % (TH - 1),
       EL.clover_enough({'clover_locked': TH - 1}) is False)
    ck('`clover_enough({"clover_locked": %d})` = **True**（边界 ✓，阈值现为 %d）'
       % (TH, TH), EL.clover_enough({'clover_locked': TH}) is True)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    _th = int(EL.CLOVER_MIN_REROLL)
    print('✅ 全部通过：幸运草 <%d ⇒ **纯大拇指格**拉黑不去打；'
          '带首领的格保留（boss 必打）；≥%d 自动放回；读不到时不拉黑；一图只确认一次'
          % (_th, _th))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
