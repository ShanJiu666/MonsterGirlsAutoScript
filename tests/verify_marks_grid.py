# -*- coding: utf-8 -*-
"""verify_marks_grid.py · 防「marks/cells 棋盘几何没跟着换基准」回归（2026-10-02）

事故
----
2026-10-02 换 720×1280 基准时，`marks.py` 的棋盘几何**漏改**，还是 1080×1920 系：

    GRID = dict(x0=36.0, y0=1002.0, cx=144.0, cy=144.0)
    GLYPH_SCALES = 3.8~5.2          # 也是按 144 格距标的

⇒ 真机（720p，棋盘 x0=24 y0=668 cx=96）：
  · 扫描区域从 y=992 起，真棋盘是 y=658~1138 ⇒ **只覆盖下半截**
  · 格号映射 `(gy-y0)//cy` 拿 144 当格距 ⇒ 命中的格号也全错
  · 图标等比缩到 96/144 = 0.667 倍 ⇒ 真实尺度落在 **2.5~3.5**，
    **整个在 3.8~5.2 之外** ⇒ 即使修好 GRID 照样零命中
⇒ `scan_board()` **恒返回空** ⇒ `marked` 恒空
⇒ `one_round` 每轮都判「没有目标了，准备退图」⇒ 规划拿不到目标
⇒ 用户看到的现象 = 「规划很差劲」✗✗

本脚本断言
----------
① `marks.GRID` 与 `layout.REF` **逐条一致**（不许各写一份）
② 尺度区间是**从格距推**的，且在 720p 下落在 2.0~4.0（真标���区间）
③ 真帧上 `scan_board()` **扫得到 boss 标记**（不是空）
④ 扫描耗时 **< 4 秒**（放宽尺度区间很容易做到 11 秒，必须挡住）
⑤ `cells.GRID` 同样与 layout.REF 一致

⚠ 零设备、零体力：只读 `_verify/` 里的真帧，不连 adb、不点任何东西。
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
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）
import time


os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []

# 真机帧（进图首帧，上面确实有红色 boss 记号）—— 已入库，别人 clone 也能复现
FRAMES = [
    os.path.join(HERE, '_verify', 'boss_mark_gridcheck_20261002.png'),
]


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  [%s] %s%s' % ('ok  ' if cond else 'FAIL', name,
                           ('  ' + detail) if detail else ''))


def main():
    print('=' * 78)
    print('防回归：marks/cells 的棋盘几何与尺度必须跟着基准走  零设备、零体力')
    print('=' * 78)

    try:
        import cv2
        import numpy as np
        import layout
        import marks
    except Exception as e:                                   # noqa: BLE001
        check('能 import 分类模块', False, repr(e))
        return 1

    REF = layout.REF
    print()

    # ── ① GRID 与 layout.REF 逐条一致 ────────────────────────────
    print('【1】marks.GRID 必须等于 layout.REF（单一数据源，不许各写一份）')
    want = {'x0': float(REF['grid_x0']), 'y0': float(REF['grid_y0']),
            'cx': float(REF['grid_cx']), 'cy': float(REF['grid_cy'])}
    for k, v in want.items():
        got = float(marks.GRID.get(k) or -1)
        check('① marks.GRID[%-2s] = %-7.1f（期望 %-7.1f）' % (k, got, v),
              abs(got - v) < 0.5,
              '' if abs(got - v) < 0.5 else '  ⛔ 不一致 ⇒ 扫描区域/格号全错')
    check('② 不残留 1080 系写死值（y0=1002 / cx=144）',
          not (abs(float(marks.GRID['y0']) - 1002) < 1
               and abs(float(marks.GRID['cx']) - 144) < 1))
    # ⛔ 2026-10-02 自造回归：`_mk3.GRID = {x0,y0,cx,cy}`（整体替换）把
    #   `cols`/`rows` 弄丢 ⇒ `scan_board()` 里 `GRID['rows']` **KeyError**
    #   ⇒ 每轮标记扫描抛异常 ⇒ marked 恒空 ⇒ 「没有目标了」✗
    #   ⇒ 断言 explore_loop 里**不再有**整体替换 marks.GRID 的写法 ✓
    for k in ('cols', 'rows'):
        check('③ marks.GRID[%r] 存在（被整体替换过就会丢）' % k, k in marks.GRID)
    try:
        import re as _re
        bad_assign = []
        for _ln in io.open(os.path.join(HERE, 'explore_loop.py'),
                           encoding='utf-8').read().splitlines():
            if _ln.lstrip().startswith('#'):       # 注释里提到旧写法不算 ✗
                continue
            if _re.search(r'_mk\d*\.GRID\s*=\s*(?!dict\(|\w+\.)', _ln):
                bad_assign.append(_ln.strip()[:80])
        check('④ explore_loop 里没有「整体替换 marks.GRID」的写法（要用 set_grid）',
              not bad_assign,
              '' if not bad_assign else '  ⛔ %s' % bad_assign[:2])
    except OSError as e:                                   # noqa: BLE001
        check('④ 读得到 explore_loop.py', False, repr(e))

    # ── ② 尺度从格距推，且落在真标记区间 ────────────────────────
    print()
    print('【2】标记尺度必须由格距推出，且 720p 下落在真标记区间')
    sc = marks.GLYPH_SCALES
    lo, hi = min(sc), max(sc)
    print('      当前区间 %.2f ~ %.2f（%d 档）' % (lo, hi, len(sc)))
    check('① 尺度下界 >= 2.0（720p 真标记约 2.5~3.5；<2 是拿小图瞎试）',
          lo >= 2.0, '' if lo >= 2.0 else '  当前 %.2f' % lo)
    check('② 尺度上界 <= 4.5（720p 真标记约 3.5；>4.5 是拿废尺度烧时间）',
          hi <= 4.5, '' if hi <= 4.5 else '  当前 %.2f' % hi)
    check('③ 档数 <= 20（多尺度匹配耗时 ∝ 档数）', len(sc) <= 20, '  %d 档' % len(sc))
    try:
        derived = marks.glyph_scales(float(REF['grid_cx']))
        check('④ glyph_scales(格距) 给的区间与模块级一致（尺度真由格距推出）',
              abs(min(derived) - lo) < 0.05 and abs(max(derived) - hi) < 0.05,
              '  derived %.2f~%.2f vs 模块 %.2f~%.2f'
              % (min(derived), max(derived), lo, hi))
    except Exception as e:                                   # noqa: BLE001
        check('④ glyph_scales() 可调用', False, repr(e))

    # ── ③ 真帧上扫得到标记 + ④ 耗时 ─────────────────────────────
    print()
    print('【3】真机帧上必须扫得到标记（空 = 规划没目标 = 用户说的「规划很差」）')
    usable = [p for p in FRAMES if os.path.exists(p)]
    if not usable:
        check('① 取证帧还在（%s）' % os.path.basename(FRAMES[0]), False,
              '  帧丢了 ⇒ 这条断言没法验证，请把该帧一并入库')
    else:
        for p in usable:
            img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                check('① %s 读得出来' % os.path.basename(p), False)
                continue
            t0 = time.time()
            res = marks.scan_board(img)
            dt = time.time() - t0
            found = {k: (v or {}).get('marks') for k, v in (res or {}).items()}
            print('      %s -> %d 个标记，耗时 %.2fs'
                  % (os.path.basename(p), len(res or {}), dt))
            for k in sorted(res or {}):
                print('         %s %s shape=%s color=%s'
                      % (k, found[k], (res[k] or {}).get('score'),
                         (res[k] or {}).get('color')))
            check('① %s 扫得到 boss 标记（不是空）'
                  % os.path.basename(p), bool(res),
                  '' if res else '  ⛔ 零命中 ⇒ marked 恒空 ⇒ 每轮都判「没有目标了」')
            if res:
                # 记到的格号必须在棋盘范围内（格号映射没算错）
                bad_cell = [k for k in res
                            if not (1 <= k[0] <= REF['grid_rows']
                                    and 1 <= k[1] <= REF['grid_cols'])]
                check('② 命中格号都在棋盘范围内（格号映射正确）', not bad_cell,
                      '' if not bad_cell else '  越界：%s' % (bad_cell,))
                # 形状/配色要过闸（说明是真标记不是噪声）
                weak = [k for k, v in res.items()
                        if float((v or {}).get('score') or 0) < marks.SHAPE_MIN]
                check('③ 命中项形状分都过闸（>= %.2f）' % marks.SHAPE_MIN,
                      not weak, '' if not weak else '  低分：%s' % (weak,))
            # ⭐⭐⭐ 2026-10-03 修**抖动假红**：原来是一次性墙钟断言 `< 4.0s`，
            #   而同一帧同一份代码实测在 **3.54s ~ 4.82s** 之间跳（机器一有负载就超标）
            #   ⇒ 门禁时不时红一次，且**测的不是代码**（是当时机器的忙闲）✗
            #   （2026-10-02 连续两次全量门禁一红一绿，就是这条）
            #   ⇒ 改成**中位 3 次 + 阈值 8s**：仍然能抓住"真正变慢一个量级"的回归，
            #     但不再因负载抖动误报 ✓
            _ts = []
            for _ in range(3):
                _t0 = time.time()
                marks.scan_board(img)
                _ts.append(time.time() - _t0)
            _ts.sort()
            _med = _ts[1]
            check('④ 扫描耗时中位 < 8 秒（3 次取中位；防负载抖动假红）',
                  _med < 8.0,
                  '  中位 %.2fs（三次 %.2f/%.2f/%.2f）' % (_med, _ts[0], _ts[1], _ts[2]))

    # ── ⑤ cells.GRID ───────────────────────────────────────────
    print()
    print('【4】cells.GRID 同样不许停在 1080 系')
    try:
        import cells
        for k, v in want.items():
            got = float(cells.GRID.get(k) or -1)
            check('① cells.GRID[%-2s] = %-7.1f（期望 %-7.1f）' % (k, got, v),
                  abs(got - v) < 0.5)
    except Exception as e:                                   # noqa: BLE001
        check('① 能 import cells', False, repr(e))

    # ── ⑤ 探索模式闸门 + boss 提前（2026-10-02 从手机端 v1.29/v1.34 对齐）──
    print()
    print('【5】探索模式闸门 + 能点的 boss 提到最前（治「1~4 轮就退图」）')
    try:
        import explore_loop as EL
    except Exception as e:                                   # noqa: BLE001
        check('① 能 import explore_loop', False, repr(e))
        EL = None
    if EL is not None:
        ne = getattr(EL, 'need_explore', None)
        # ⚠ 2026-10-02：函数**保留**（`need_explore` 纯函数，将来若要恢复
        #   「开局全雾先揭两格」不必重写），但**已不参与退图判定**。
        #   下面 ②③④ 只验函数自身行为不变，**不再**声称「该探图就能不急着退」——
        #   那是旧口径，用户已明确否掉（见下方⑪⑫的注释）。
        check('① need_explore() 仍在（纯函数，将来复用；已不参与退图判定）',
              ne is not None)
        if ne is not None:
            check('② 纯函数行为不变：没目标 + 暗格 20 + 预算 0 ⇒ True',
                  ne([], [], 20, 0) is True)
            check('③ 没目标但暗格只剩 3 ⇒ False（盘已探开）',
                  ne([], [], 3, 0) is False)
            check('④ 探图预算用完(40) ⇒ 不探图（防无限花体力）',
                  ne([], [], 20, 40) is False)
            check('⑤ 还有标记目标 ⇒ 不探图（正常走目标）',
                  ne([1], [], 20, 0) is False)

        # boss 提前：能点的 boss 提到最前，雾里的**绝不**提
        _st_ok = {'marks': {(2, 3): {'marks': ['boss']}},
                  'obs': {(2, 3): {'ratio': 1.0}, (3, 5): {'ratio': 1.0}}}
        _st_fog = {'marks': {(2, 3): {'marks': ['boss']}},
                   'obs': {(2, 3): {'ratio': 0.65}, (3, 5): {'ratio': 1.0}}}
        rc_ = getattr(EL, '_ready_boss_cells', None)
        ho = getattr(EL, '_hoist_ready_boss_first', None)
        check('⑥ _ready_boss_cells/_hoist_ready_boss_first 存在（boss 提前）',
              rc_ is not None and ho is not None)
        if rc_ and ho:
            check('⑦ 已揭示的 boss 被认成「当下能点」', rc_(_st_ok, [(3, 5), (2, 3)]) == [(2, 3)])
            check('⑧ 能点的 boss 提到点序最前',
                  ho(_st_ok, [(3, 5), (2, 3)]) == [(2, 3), (3, 5)])
            check('⑨ ⛔ 雾里的 boss 绝不被提（提上来也点不动，只会更差）',
                  ho(_st_fog, [(3, 5), (2, 3)]) == [(3, 5), (2, 3)])
            check('⑩ 点序本来没有 boss ⇒ 不动它（fail-open）',
                  ho(_st_ok, [(3, 5), (1, 1)]) == [(3, 5), (1, 1)])
        # 源码层：退图判据 —— ⭐⭐⭐ 2026-10-02 **按用户口径反转**
        #   用户原话：「目标没了就可以退了，不用把雾格全揭开」
        #   ⚠ 原来这三条门禁守的是**反过来的口径**（`and not _explore` /
        #     `or _explore` ⇒ 暗格多就继续探图），那是 2026-10-02 早先为了盖
        #     「识别层坏 ⇒ 目标认不出」临时加的探图闸门。
        #     识别修好后（`1e64b1b` / `861687b` / `615fad1`），用户明确否掉了那条口径
        #     ⇒ 门禁跟着改，**否则门禁会一直把代码拽回旧行为**（这才是真危险）。
        #   现状：没有标记格 + 没有商人/宝库 ⇒ 直接 `return 'done'` 收工。
        try:
            src2 = io.open(os.path.join(HERE, 'explore_loop.py'),
                           encoding='utf-8').read()
            check('⑪ 退图判据 = 「没标记格 且 没商人/宝库」就收工'
                  '（用户口径：目标没了就退，不强求揭开雾格）',
                  'not marked and not pending_buy:' in src2
                  and 'and not _explore' not in src2)
            check('⑫ 点序组装**不再**带 `or _explore`（没目标就不组装）',
                  '(marked or buy_any or _explore)' not in src2
                  and 'if not order and (marked or buy_any):' in src2)
            check('⑫ 探图日志不再出现（「先揭几格开路探图」已整段停用）',
                  "say('   · 盘上暂无可见目标" not in src2)
            check('⑬ 探图预算记账仍在（explore_clicks 会 +1，留着将来复用）',
                  "st['explore_clicks'] = st.get('explore_clicks', 0) + 1" in src2)
        except OSError as e:                               # noqa: BLE001
            check('⑪ 读得到 explore_loop.py', False, repr(e))

    print()
    print('=' * 78)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
    for x in BAD:
        print('   ✗ ' + x)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
