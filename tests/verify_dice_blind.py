# -*- coding: utf-8 -*-
"""verify_dice_blind.py · 回归：摇色子的两个「棋盘内盲点」必须带判据

用户 2026-10-05 原话：
    「**还有摇完大拇指后有个点中间的盲点**」

硬事实（`FX.A()` 坐标 + `cell_of()` 落格，**可复算，不是猜**）
----------------------------------------------------------
    锚点            坐标          ⇒ 落在
    `dice_reroll`  (40, 645)      **棋盘外**（左上角 ✓ 安全）
    `dice_yes`     **(520, 742)** 格 **(1,6)**   ⚠⚠ **棋盘内**
    `dice_no`      **(300, 742)** 格 **(1,3)**   ⚠⚠ **棋盘内 ← 用户说的"点中间"**
    （棋盘 y 范围 ≈ 668~1148 ⇒ 742 在**第 1 行**；x 300 ⇒ 第 3 列）

原来这两处**都没有判据**：
  · `dice_yes` 每圈**无条件点** ⇒ 四叶草没弹框时（幸运草不够 / 面板变了 / 点空）
    这一下就落在**棋盘 (1,6)** 上 ✗
  · `dice_no` 收尾**无条件点** ⇒ 框不在时落在**棋盘 (1,3)** 上 ✗
    （原作者注释写「框不在时这一下落在**面板空白处**」—— **假设是错的** ✗）

修法：判据用**棋盘压暗**（模态确认框弹出 ⇒ 棋盘被遮罩压暗）—— **零成本**，
不付 OCR（合用户口径「这种不应该都是固定坐标点击吗」）。
方向安全：**没判定出框就不点**（这一圈作废，但**绝不误点棋盘** ✓）

牙齿：把这两道判据去掉，本门禁必红 ✓
"""
import os
import re
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


sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import explore_loop as EL
    import fixed as FX
    import layout as lay
    print('=== 摇色子：两个"棋盘内盲点"必须带判据 ===')
    y0 = int(lay.REF['grid_y0'])
    y1 = y0 + 5 * int(lay.REF['grid_cy'])

    # ── ① 先固定"落格"这个硬事实 ─────────────────────────────────────
    print()
    print('【1】三个锚点各自落在哪（硬事实）')
    geo = {}
    for a in ('dice_reroll', 'dice_yes', 'dice_no'):
        p = FX.A(a)
        ck('锚点 `%s` 存在' % a, bool(p), str(p))
        if not p:
            continue
        rc = EL.cell_of(p[0], p[1])
        ingrid = (y0 <= p[1] <= y1) and (1 <= rc[1] <= 7)
        geo[a] = (p, rc, ingrid)
        print('      %-13s %-12s ⇒ 格 %-6s 棋盘内=%s'
              % (a, str(p), '%d,%d' % rc, ingrid))
    ck('`dice_reroll` **在棋盘外**（所以它可以无条件点 ✓）',
       geo.get('dice_reroll') and not geo['dice_reroll'][2])
    ck('`dice_yes` **在棋盘内**（(520,742) ⇒ 格 (1,6)）⇒ **必须带判据**',
       geo.get('dice_yes') and geo['dice_yes'][2],
       str(geo.get('dice_yes')))
    ck('`dice_no` **在棋盘内**（(300,742) ⇒ 格 (1,3)）⇒ **必须带判据**'
       '（用户说的"点中间"就是它）',
       geo.get('dice_no') and geo['dice_no'][2], str(geo.get('dice_no')))

    # ── ② 两个棋盘内的点都必须被判据包着 ─────────────────────────────
    print()
    print('【2】源码：两个棋盘内的点都被"棋盘压暗"判据包着')
    lines = open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read().splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def handle_dice(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    code = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))

    taps = {}
    for n in range(s, e):
        m = re.search(r'b\.tap\(_(\w+)\[0\]', lines[n])
        if m:
            guard = None
            # ⚠ 查找窗口要**够近**：太宽会跨到上一个分支去（我第一版窗口 32 行，
            #   把 `dice_reroll` 的判据误报成循环外的 `if _h0:` ✗）
            for k in range(n - 1, max(s, n - 12), -1):
                st = lines[k].strip()
                if st.startswith('if ') or st.startswith('elif '):
                    guard = st
                    break
                if st.startswith('for ') or st.startswith('def '):
                    break                   # 撞到循环/函数头 ⇒ 说明这段没有判据
            taps[m.group(1)] = (n + 1, guard)
    print('      点击 → 判据：%s' % taps)
    ck('`dice_yes` 有点击，且判据是 `_dlg_dim`（棋盘压暗）',
       'yp' in taps and taps['yp'][1] and '_dlg_dim' in taps['yp'][1],
       str(taps.get('yp')))
    ck('`dice_no` 有点击，且判据是 `_tail_dim`（棋盘压暗）',
       'no_p' in taps and taps['no_p'][1] and '_tail_dim' in taps['no_p'][1],
       str(taps.get('no_p')))
    ck('判据阈值为 `>= 0.85`（没压暗 ⇒ **跳过**，不点棋盘 ✓）',
       '_dlg_dim >= 0.85' in code and '_tail_dim < 0.85' in code)
    ck('`dice_reroll` **不需要**判据（它在棋盘外 ✓）',
       'btn' in taps and not (taps['btn'][1] and '_dim' in taps['btn'][1]),
       str(taps.get('btn')))
    ck('跳过时**记日志**（`no_dlg_skip` / `tail_skip`），便于事后对账',
       'no_dlg_skip' in code and 'tail_skip' in code)

    # ── ③ 方向安全：跳过后不许"接着乱点" ────────────────────────────
    print()
    print('【3】方向安全：没判定出框 ⇒ 这一圈作废（而不是继续乱点）')
    ck('`no_dlg_skip` 之后**立刻 break**（不再进下一圈）',
       bool(re.search(r"no_dlg_skip[\s\S]{0,400}?break", code)))
    ck('两处都**不依赖 OCR**（用户口径：能用固定坐标/免费判据就别 OCR ✓）',
       'b.ocr(' not in code)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：摇色子的两个"棋盘内盲点"都带上了"棋盘压暗"判据；'
          '棋盘外那个保持零判断；跳过后不再乱点')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
