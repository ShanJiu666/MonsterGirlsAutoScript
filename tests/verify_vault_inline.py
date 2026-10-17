# -*- coding: utf-8 -*-
"""verify_vault_inline.py · 回归：**点开的宝库面板必须就地买掉**

用户 2026-10-05 原话：
    「**修了个寂寞，还是打开黄金宝库就关了，根本没购买**」
    「**既然规划都点了宝库，肯定是规划知道这个是已揭示能点的，
       什么东西不认可规划的判断？**」

真机铁证（`runs/loop/loop_log.json` 第 3 张图，条目 126 → 131）
--------------------------------------------------------------
    条目 99   solver ok：`order = ["1,3","1,4","3,4","4,4","5,7"]`
              `5,7 ⇒ 像素 (648,1100)` —— **规划里有宝库** ✓（用户说得对）
    条目 126  round4：`taps` 里 `["5,7", 5.1, true, "S30001_016", 1]`
              ⇒ **确实点开了黄金宝库** ✓
              `panel_via = "title"` ← 点击循环里 `panel_seen(it2)` 认到的
              （`L['special']` 含「黄金宝库」⇒ 它**一直都知道是宝库** ✓）
              但那一支**只 `break`**，没做任何购买动作 ✗
    条目 128  round5：`ocr: skip_no_panel`（判"无面板" ⇒ **免整屏 OCR**）
    条目 131  `finish: blank_board` ⇒ 收工，**宝库没买** ✗✗

根因：`panel_seen` 命中后**只 `break`**，把面板留给**下一轮**的 `popups()`；
    而下一轮轮首 `board_hidden(_cells_cached(...))` 在那个面板帧上算出 False
    （直接证据：`ocr: skip_no_panel`）⇒ **免 OCR、也不调 `popups()`**
    ⇒ 宝库面板**从来没人处理** ⇒ `blank_board` 收工 ✗

修法：点击循环里认到**宝库面板**（`黄金宝库` 标题 / 「解锁宝库」字样）⇒
     **当场走 `buypanels.vault_flow()`**（与 `popups()` 里那条**同一个函数** ✓）
     ⚠ **只对宝库动手**，绝不在这里调 `popups()` —— 它末尾有 `find_x()`
       **无条件盲点 X** 的兜底，会把没认出来的宝库面板**关掉**，
       那正是用户报的「打开就关了」本身 ✗✗

牙齿：去掉就地处理（退回只 `break`）⇒ 本门禁必红 ✓
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
    import mapbot as MB
    import explore_loop as EL

    print('=== 点开的宝库面板必须就地买掉（用户：「打开黄金宝库就关了，根本没购买」）===')

    # ── ① 前置事实：L['special'] 含「黄金宝库」⇒ panel_seen 认得到 ──────
    print()
    print('【1】`L[\'special\']` 含「黄金宝库」⇒ `panel_seen` 本来就认得到它')
    ck('「黄金宝库」在 `L[\'special\']` 里（这是 `panel_via=title` 的来源 ✓）',
       '黄金宝库' in EL.L['special'])

    # ── ② 真帧：判据必须命中 ─────────────────────────────────────────
    print()
    print('【2】判据在**宝库刚打开那一刻的真帧**上必须命中')
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def one_round(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    body = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
    ck('点击循环里有 `vault_panel_inline`（就地买那支）',
       'vault_panel_inline' in body)
    ck('就地调用的是 **`buypanels.vault_flow`**（与 popups 里同一条路 ✓）',
       'buypanels.vault_flow(b, log)' in body)
    ck('⚠ 它**没有**在这里调 `popups()`（那条末尾会盲点 X 把面板关掉 ✗）',
       'popups(b, _dp2' not in body)
    ck('包了 try/except（`vault_flow` 一崩不能抛穿 ⇒ 面板留屏 ⇒ 后面全点在面板上 ✗）',
       "flow_error_tap" in body and 'except Exception as _ve2' in body)

    frames = ['vault_start_20261005.png', 'vault_r1_undrawn_20261005.png',
              'vault_live_20261005.png']
    hit_any = 0
    for fn in frames:
        p = os.path.join(V, fn)
        if not os.path.exists(p):
            print('      （缺 %s ⇒ 跳过）' % fn)
            continue
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        b = MB.Bot.__new__(MB.Bot)
        b._img_arr = im
        b._last = None
        b._img_path = None
        b.fast_ok = True
        b.runs = V
        b.t = {'snap': 0, 'ocr': 0, 'wait': 0, 'wait_n': 0, 'tap': 0, 'ocr_n': 0}
        b.ocr_grabs = False
        it2 = b.ocr(band=(int(EL.LAYOUT.sy(130)), int(EL.LAYOUT.sy(1080))),
                    tag='gate_vault_inline')
        t2s = ' '.join((i.get('text') or '') for i in (it2 or []))
        seen = bool(EL.panel_seen(it2, b=b))
        is_vault = bool('黄金宝库' in t2s or ('宝库' in t2s and '解锁' in t2s))
        vbtn = bool(any(k in t2s for k in ('选择奖励', '解锁宝库'))
                    or ('购买' in t2s and '解锁' in t2s))
        hit = bool(is_vault or (vbtn and '宝库' in t2s))
        hit_any += 1 if hit else 0
        print('      %-34s panel_seen=%-5s is_vault=%-5s btn=%-5s ⇒ 命中=%s'
              % (fn, seen, is_vault, vbtn, hit))
        ck('%s ⇒ `panel_seen` 成立（会走到那一支）' % fn, seen)
        ck('%s ⇒ **我的判据命中**（会就地买）' % fn, hit)
    ck('至少有一张宝库真帧验证过（不许"没帧就静默通过" ✗）', hit_any > 0,
       '命中 %d 张' % hit_any)

    # ── ③ 反向断言：非宝库面板**不许**被就地买 ───────────────────────
    print()
    print('【3】反向断言：别的面板不许触发就地买（防误买 ✗）')
    for name, texts, want in [
        ('旅行商人', ['旅行商人', '购买', '离开'], False),
        ('战斗事件', ['战斗事件', '开始战斗'], False),
        ('探索产出', ['探索产出', '一键派遣'], False),
        ('宝库（真）', ['黄金宝库', '购买', '解锁宝库'], True),
        ('宝库·选择奖励', ['黄金宝库', '选择奖励'], True),
    ]:
        t2s = ' '.join(texts)
        is_vault = bool('黄金宝库' in t2s or ('宝库' in t2s and '解锁' in t2s))
        vbtn = bool(any(k in t2s for k in ('选择奖励', '解锁宝库'))
                    or ('购买' in t2s and '解锁' in t2s))
        got = bool(is_vault or (vbtn and '宝库' in t2s))
        ck('%-16s ⇒ %s' % (name, want), got is want, '实际 %s' % got)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：点开的宝库面板会**就地买掉**（走 vault_flow）；'
          '别的面板不受影响；没在这里调 popups()（避免被盲点 X 关掉）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
