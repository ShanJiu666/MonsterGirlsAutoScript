# -*- coding: utf-8 -*-
"""verify_layout_scale.py · 分辨率缩放的自检（2026-10-02）

背景：这个坑让 720p 完全跑不了
--------------------------------
`explore_loop.py` 里有二十几处判据是 **1080×1920 参考系**的常数，靠 `LAYOUT.sy()`
缩放。`ADAPTIVE_LAYOUT=False` 时 `apply_layout()` 直接 return ⇒ **`k` 恒为 1.0**。

720p 下「进入地图」实测 `cy=1078`，而门槛是 `it['cy'] > LAYOUT.sy(1400)`：
- `k=1.0` ⇒ 门槛 1400 ⇒ **1078 过不去** ⇒ 永远不点 ⇒ 每次「进图失败」
- `k=0.6667` ⇒ 门槛 933 ⇒ **1078 过得去** ✓

日志里那行 `屏幕 720x1280 ⇒ 缩放 k=1.0000` 就是自相矛盾的信号：
**屏幕不是参考分辨率，k 却等于 1.0**。

为什么要单独一个门禁
--------------------
`verify_gate` 全绿时这个 bug 照样发生 —— 它只在**真机 720p** 下才暴露。
而门禁是纯计算的，能提前抓住「k 没跟着屏幕变」这件事 ⇒ 不必等真机。

⚠ 这里不碰任何真机、不连 adb、不开窗口。
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


os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


# 720×1280 下「进入地图」的真实 OCR 坐标（2026-10-02 真机实测）
REAL_ENTER_CY_720P = 1078
REAL_ENTER_CX_720P = 603


def main():
    import layout
    import fixed as F

    print('=== 分辨率缩放自检（不碰真机）===\n')

    print('【1】ADAPTIVE_LAYOUT 必须开着（否则 k 恒 1.0，720p 全废）')
    src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    import re
    m = re.search(r'^ADAPTIVE_LAYOUT\s*=\s*(True|False)', src, re.M)
    ck('能找到 ADAPTIVE_LAYOUT 开关', bool(m))
    if m:
        ck('ADAPTIVE_LAYOUT = True', m.group(1) == 'True', '现在是 %s' % m.group(1))

    print()
    print('【2】k 必须跟着屏幕走（720p 是基准 ⇒ k 恒为 1.0）')
    ck('参考基准就是 720×1280', (layout.REF_W, layout.REF_H) == (720, 1280),
       'REF=%dx%d' % (layout.REF_W, layout.REF_H))
    L = layout.Layout(720, 1280)
    ck('720p 的 k = 1.0（基准即屏幕，不该再缩放）', abs(L.k - 1.0) < 1e-9,
       'k=%.4f' % L.k)
    ck('720p 无黑边偏移（9:16 等比）', L.ox == 0 and L.oy == 0,
       'ox=%.1f oy=%.1f' % (L.ox, L.oy))
    L1080 = layout.Layout(1080, 1920)
    ck('1080p 会等比放大 1.5（仍按 720 基准缩放）',
       abs(L1080.k - 1.5) < 1e-6, 'k=%.4f' % L1080.k)

    print()
    print('【3】「进入地图」门槛在 720p 下必须能过（本次事故的真凶）')
    thr = L.sy(933)
    ck('720p 门槛 = sy(933) = 933', thr == 933, '实际 %d' % thr)
    ck('实测 cy=%d 过得了门槛' % REAL_ENTER_CY_720P,
       REAL_ENTER_CY_720P > thr, '%d > %d ? %s' % (REAL_ENTER_CY_720P, thr,
                                                   REAL_ENTER_CY_720P > thr))
    # 反证：旧的 1080 系参数（1400）过不去 —— 把"参数必须一起换算"钉住
    ck('（反证）旧 1080 系参数 1400 **过不去** ⇒ 参数必须一起换算',
       not (REAL_ENTER_CY_720P > 1400), '1078 > 1400 ? False')

    print()
    print('【4】layout（720 基准） 与 fixed.py 的 720p 锚点必须吻合')
    ck('REF[enter_map] == fixed.A(enter_map)',
       tuple(L.pt(*layout.REF['enter_map'])) == tuple(F.A('enter_map')),
       '%s vs %s' % (L.pt(*layout.REF['enter_map']), F.A('enter_map')))
    ck('REF[start_adv] == fixed.A(start_adv_icon)',
       tuple(L.pt(*layout.REF['start_adv'])) == tuple(F.A('start_adv_icon')),
       '%s vs %s' % (L.pt(*layout.REF['start_adv']), F.A('start_adv_icon')))
    ck('与真机实测 cx=%d 一致' % REAL_ENTER_CX_720P,
       F.A('enter_map')[0] == REAL_ENTER_CX_720P)
    # ⚠ 锚点 1079 与 OCR 文字中心 1078 差 1px **是正常的**：
    #   前者是**按钮中心**（点它），后者是**文字框中心**（判存在性），
    #   本来就不该完全相等 ⇒ 断言留 4px 容差，只查"同一位置附近"。
    ck('与真机实测 cy=%d 相差 ≤4px（同一按钮）' % REAL_ENTER_CY_720P,
       abs(L.pt(*layout.REF['enter_map'])[1] - REAL_ENTER_CY_720P) <= 4,
       'REF.y=%d' % L.pt(*layout.REF['enter_map'])[1])

    print()
    print('【5】720p 下所有判据阈值必须落在屏内（防缩放后越界）')
    bad = []
    for y in (400, 533, 600, 667, 733, 933, 1067, 1133, 1167):
        v = L.sy(y)
        if v >= 1280:
            bad.append('sy(%d)=%d' % (y, v))
    ck('全部阈值 < 1280', not bad, '; '.join(bad))

    print()
    print('【6】apply_layout 在 720p 下真的把常量刷新了（端到端）')
    import explore_loop as E
    E.apply_layout(720, 1280)
    ck('LAYOUT.k == 1.0（基准即 720p 屏幕）', abs(E.LAYOUT.k - 1.0) < 1e-9,
       'k=%.4f' % E.LAYOUT.k)
    ck('ENTER_MAP == fixed.A(enter_map)', tuple(E.ENTER_MAP) == tuple(F.A('enter_map')),
       '%s vs %s' % (E.ENTER_MAP, F.A('enter_map')))
    ck('START_ADV == fixed.A(start_adv_icon)',
       tuple(E.START_ADV) == tuple(F.A('start_adv_icon')),
       '%s vs %s' % (E.START_ADV, F.A('start_adv_icon')))
    for nm, v in (('FIGHT_Y', E.FIGHT_Y), ('SLOTS_Y', E.SLOTS_Y)):
        ck('%s 落在 720p 屏内' % nm, 0 < v < 1280, '%s' % v)
    ck('GRID 已按 720p 缩放（y0≈668）',
       abs(E.GRID['y0'] - 668) < 2, "y0=%s" % E.GRID.get('y0'))

    print()
    print('【7】⭐ 调用点参数必须已换算成 720 系（不留 1080 系越界值）')
    # 换基准只改 layout.REF 是不够的 —— `LAYOUT.sy(1400)` 这类**调用参数**
    # 也要一起 ×0.6667，否则 k=1.0 下门槛反而更高、按钮更点不到。
    # 这条断言就是防"只换一半"。
    lines = io.open(os.path.join(CORE, 'explore_loop.py'),
                    encoding='utf-8').read().splitlines()
    pat = re.compile(r'LAYOUT\.(sy|sx)\(([^()]*)\)')
    over = []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('#'):
            continue                      # 注释里举例子没关系
        for m in pat.finditer(line):
            nums = [int(x) for x in re.findall(r'\d+', m.group(2))]
            if not nums:
                continue
            lim = 1280 if m.group(1) == 'sy' else 720
            if max(nums) > lim:
                over.append('L%d %s' % (i, m.group(0)))
    ck('无 1080 系残留参数（全部 ≤ 720/1280）', not over,
       '残留 %d 处: %s' % (len(over), '; '.join(over[:5])) if over else '')
    # 抽查几处已换算的关键调用
    for want in ('LAYOUT.sy(933)', 'LAYOUT.sy(1133)', 'LAYOUT.sx(683)'):
        ck('已换算：%s' % want,
           any(want in l for l in lines), '')

    print()
    print('【8】⭐ 静态常量不能残留 1080 系（换基准最易漏的地方）')
    # 2026-10-02 踩坑：`spots.GRID` 静态定义漏改（仍 36/1002/144），
    # 而 `Board.state()` 的阈值公式又把 144 写死 ⇒ 720p 下每格 NCC 只有
    # 0.07~0.26、**全在瞎猜**（同一格两轮认成不同地块，0 个战斗格）。
    # ⚠ 这类问题**门禁当时全绿**（因为 apply_layout() 运行时覆盖了 GRID），
    #    所以必须**直接扫静态源码**，不能只看运行时对象。
    import spots
    g = spots.GRID
    ck('spots.GRID 已是 720p（cx=96）', abs(g['cx'] - 96) < 1, 'cx=%s' % g['cx'])
    ck('spots.GRID y0 已是 720p（≈668）', abs(g['y0'] - 668) < 2, 'y0=%s' % g['y0'])
    ck('spots.GRID 与 layout.REF 一致（单一数据源）',
       g['x0'] == layout.REF['grid_x0'] and g['cx'] == layout.REF['grid_cx'],
       'spots=%s/%s ref=%s/%s' % (g['x0'], g['cx'],
                                   layout.REF['grid_x0'], layout.REF['grid_cx']))
    ck('spots.BASE_PX 与 GRID.cx 一致（阈值分母不是写死的 144）',
       abs(spots.BASE_PX - g['cx']) < 1e-6, 'BASE_PX=%s cx=%s' % (spots.BASE_PX, g['cx']))
    ck('格子数仍是 7×5（没被当成坐标缩放过）',
       g['cols'] == 7 and g['rows'] == 5, '%sx%s' % (g['cols'], g['rows']))
    # ⚠ `SCALE` 在 spots.py 里只用于默认参数与日志，**不参与计算**
    #   （格距一律走 `self.px` ← `GRID['cx']`）⇒ 换基准后它**不该被 apply_layout 改写**
    import explore_loop as _E0
    _E0.apply_layout(720, 1280)
    ck('apply_layout 不会改写 spots.SCALE（含义不漂移）',
       abs(spots.SCALE - 4.5) < 1e-9, 'SCALE=%s（被改写说明 520 行那种重算又回来了）' % spots.SCALE)
    # 720p 下算出来的 NCC 门槛必须在合理区间
    _b = spots.Board('夏日海滩', grid={'cx': g['cx'], 'cy': g['cy'],
                                      'x0': g['x0'], 'y0': g['y0'],
                                      'pitch': g['pitch']})
    _thr = 0.80 * (g['cx'] / spots.BASE_PX)
    _thr = max(0.12, min(0.80, _thr))
    ck('720p 的 NCC 门槛在 [0.30,0.80]', 0.30 <= _thr <= 0.80, 'thr=%.3f' % _thr)

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：720p 下缩放正常，「进入地图」门槛过得去')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
