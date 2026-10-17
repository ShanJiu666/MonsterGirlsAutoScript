# -*- coding: utf-8 -*-
"""verify_mark_multi.py · 回归：**一格多标记 + 一帧多格**（用户问「能不能认一格四个标志」）

用户 2026-10-05 原话：
    「**我看看现在模板多大，能不能认得一个格子里有四个标志那种**」

历史记录（`mapbot_pc/交接文档.md` §5，09-26）：
    「**同格可多标记** ✓（实测一格 4 个：`redEquip,boss,recommend,clover`）
      ⇒ 按**位置相距 ≥18px** 保留 ✓」
    `runs/acc2/anno_src.png` → 格(2,1) = `redEquip,boss,recommend,clover`
    `runs/acc2/where_rec.png` → 格(2,3) = `boss,clover`

真根因（两处，都在**上游只给一个点**/尺度错位上）
------------------------------------------------
① **`match_at_scales` 每帧每模板只返回 1 个点**（`cv2.minMaxLoc`）
   ⇒ `(1,5)` 的 0.925 抢走唯一名额 ⇒ `(3,3)` 的 0.873 **连候选都不是** ✗
   （`scan_board` 下方"按位置 ≥18px 保留多标记"的聚合逻辑**本来是给四标记写的**，
     却因为上游只给 1 个点而**从来没派上用场** ✗）
② **尺度用了模块级 `GLYPH_SCALES`（720 的快照）**
   ⇒ 拿 720 的 2.53~3.47 去扫 1080 帧（格距 144 ⇒ 正确是 3.8~5.2）
   ⇒ **尺度少一整档** ⇒ 四个标记分数只有 0.74~0.83（门槛 0.90）⇒ 全认不出 ✗

修法
----
① `match_at_scales(..., topn=N, min_score=)`：NMS 取前 N 个峰（**默认 topn=1 = 老行为** ✓）
② `scan_board`：`scales` 默认改调 **`glyph_scales()`**（跟着当前 `GRID` 走），
   并给 `match_at_scales` 传 `topn=MARK_TOPN(8)` ✓

牙齿：把 `topn` 改回 1 / 把尺度改回 `GLYPH_SCALES` ⇒ 本门禁必红 ✓
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


sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

V = os.path.join(HERE, '_verify')
FAILS = []

# ⚠ 基准帧**必须放在 `_verify/`**（`runs/` 是 gitignore 的 ⇒ 新克隆下来门禁会静默跳过 = 没牙齿 ✗）
#   `_verify` 里没有时才回落到 `runs/`（本机开发时两边都在 ✓）
FIXTURES = {
    'anno_src.png': ('mark4_1080_anno_src.png', 'runs/acc2/anno_src.png'),
    'where_rec.png': ('mark2_1080_where_rec.png', 'runs/acc2/where_rec.png'),
    'r_183432_0.png': ('marks_720_map12_183432.png', 'runs/acc2/r_183432_0.png'),
}


def _fx(name):
    """取基准帧路径（先 `_verify/`，再 `runs/`）"""
    v, r = FIXTURES[name]
    p1 = os.path.join(V, v)
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(HERE, r)
    return p2 if os.path.exists(p2) else None

# 1080 系与 720 系的 GRID（真机帧上实测的）
GRID_1080 = {'x0': 36.0, 'y0': 1002.0, 'cx': 144.0, 'cy': 144.0, 'cols': 7, 'rows': 5}
GRID_720 = {'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0, 'cols': 7, 'rows': 5}


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import cv2
    import numpy as np
    import marks as M

    print('=== 一格多标记 / 一帧多格（用户：「能不能认得一个格子里有四个标志那种」）===')

    # ── ① 能力：`topn` 存在，且默认仍是 1（不破坏别的调用方）─────────
    print()
    print('【1】`match_at_scales` 支持多点（`topn`），默认保持老行为')
    import inspect
    sig = inspect.signature(M.match_at_scales)
    ck('有 `topn` 参数', 'topn' in sig.parameters)
    ck('`topn` 默认 = 1（**老行为逐位不变** ⇒ 不影响没传参的调用方 ✓）',
       int(sig.parameters['topn'].default) == 1,
       '实际 %s' % sig.parameters['topn'].default)
    ck('有 `min_score`（只用于提前停止，不改判据语义）',
       'min_score' in sig.parameters)
    ck('`MARK_TOPN` 存在且 ≥ 4（一格最多 4 个标记 ✓）',
       int(getattr(M, 'MARK_TOPN', 0)) >= 4, '实际 %s' % getattr(M, 'MARK_TOPN', None))

    # ── ② 尺度必须跟着帧的格距走 ────────────────────────────────────
    print()
    print('【2】尺度跟着帧的格距走（原来固定用 720 的快照 ⇒ 1080 帧少一整档 ✗）')
    s1080 = M.glyph_scales(144)
    s720 = M.glyph_scales(96)
    print('      1080(cx=144) ⇒ %s' % ([s1080[0], s1080[-1]],))
    print('       720(cx= 96) ⇒ %s' % ([s720[0], s720[-1]],))
    ck('144 的尺度区间 ≈ 3.8~5.2', abs(s1080[0] - 3.8) < 0.15 and abs(s1080[-1] - 5.2) < 0.15)
    ck('96 的尺度区间 ≈ 2.53~3.47', abs(s720[0] - 2.53) < 0.15 and abs(s720[-1] - 3.47) < 0.15)
    src = open(os.path.join(HERE, 'marks.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def scan_board(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    body = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
    ck('`scan_board` 默认调 **`glyph_scales()`**（而不是模块级 `GLYPH_SCALES`）',
       'scales or glyph_scales()' in body)
    ck('`scan_board` 给 `match_at_scales` 传了 `topn`',
       'topn=MARK_TOPN' in body)

    # ── ③ 三个真机用例（含四标记格）────────────────────────────────
    print()
    print('【3】真机用例（含**一格四标记**那张）')
    cases = [
        ('anno_src.png', GRID_1080, (2, 1),
         {'redEquip', 'boss', 'recommend', 'clover'},
         '**一格四标记**（09-26 用户确认过的样本 ✓）'),
        ('where_rec.png', GRID_1080, (2, 3), {'boss', 'clover'}, '一格两标记'),
        ('r_183432_0.png', GRID_720, (1, 5), {'boss', 'recommend'}, '第 12 张图（原本就认到）'),
        ('r_183432_0.png', GRID_720, (3, 3), {'recommend'},
         '★ **修复前被漏掉的那个**（同模板只回 1 点 ⇒ 被 (1,5) 抢走名额 ✗）'),
    ]
    for fn, grid, rc, want, why in cases:
        p = _fx(fn)
        if not p:
            print('      （缺 %s ⇒ 跳过）' % fn)
            continue
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        old = M.GRID
        try:
            M.GRID = dict(grid)
            got = M.scan_board(im)
        finally:
            M.GRID = old
        marks = set((got.get(rc) or {}).get('marks') or [])
        ck('%-16s 格 %-5s ⇒ %-40s（%s）' % (fn, '%d,%d' % rc, sorted(marks), why),
           marks == want, '期望 %s ｜ 实际 %s' % (sorted(want), sorted(marks)))

    # ── ④ 四标记格必须是"四个"，不能多也不能少 ──────────────────────
    print()
    print('【4】四标记格：**恰好 4 个**（多一个=误报；少一个=漏）')
    p = _fx('anno_src.png')
    if p:
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        old = M.GRID
        try:
            M.GRID = dict(GRID_1080)
            got = M.scan_board(im)
        finally:
            M.GRID = old
        mk = (got.get((2, 1)) or {}).get('marks') or []
        ck('(2,1) 恰好 4 个标记', len(mk) == 4, '实际 %d 个：%s' % (len(mk), mk))
        ck('四类齐全（redEquip/boss/recommend/clover）',
           set(mk) == {'redEquip', 'boss', 'recommend', 'clover'}, str(sorted(mk)))

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：一格四标记能认全（几何 2×2）；一帧多个格也能认；'
          '尺度跟着帧的格距走；`topn` 默认=1 不破坏别的调用方')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
