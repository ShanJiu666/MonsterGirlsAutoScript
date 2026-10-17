# -*- coding: utf-8 -*-
"""verify_region_pad.py · 防「模板内缩量算成负数」回归（2026-10-02）

事故
----
上一轮把分辨率基准从 1080×1920 换成 720×1280 时，`spots._region()` 的**内缩量**
漏改了：

    pad = (px - DESIGN_TILE * self.scale) / 2.0
        = (96 - 30 × 4.5) / 2
        = **−19.5**   ← 负数

`self.scale` 固定是 `SCALE=4.5`（1080p 系的旧值），而 `px` 已经是 720p 的 96。
⇒ 每格取图起点整体左移/上移 19.5px ⇒ 模板与画面错位 ⇒
  NCC 分数全线 **0.10~0.30**（门槛 0.80）⇒ 认不出任何地块
  ⇒ objects()/explore_blocks() 聚不出物件 → `anchor` 全 None
  ⇒ `explore_loop` 记的 `board` 恒空
  ⇒ solver 无输入 → `no_plan / exhausted / expanded=1` → **没有规划**
  ⇒ 上游表现为「开局就退 / 棋盘被挡 / 目标全丢」，全是它的下游症状 ✗✗

修法：`pad` 与模板缩放用**同一公式**（`dw/DESIGN_PITCH*px`），
      **不再引用 `self.scale`**（它已不参与几何计算）。

本脚本断言
----------
① `pad` 在 720p 下**必须为正**（不是负数）
② 多个分辨率下 `pad` 都为正
③ 真机帧的 NCC 分数**达到门槛**（≥0.80 的格数 > 0）
④ `anchor` 不再全为 None（board 能记进去 ⇒ 规划有输入）
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  [%s] %s%s' % ('ok  ' if cond else 'FAIL', name,
                           ('  ' + detail) if detail else ''))


FRAMES = ['runs/r_033057_0.png', 'runs/r_032640_0.png', 'runs/r_032228_0.png',
          'runs/r_031230_0.png', 'runs/r_030757_0.png', 'runs/r_025613_0.png']


def main():
    print('=' * 78)
    print('防回归：模板内缩量不许算成负数（否则识别全线失效）  零设备、零体力')
    print('=' * 78)

    try:
        import cv2
        import inspect
        import numpy as np
        import spots as SP
        import explore_loop as EL
    except Exception as e:                       # noqa: BLE001
        check('能 import 分类模块', False, repr(e))
        return 1

    print()
    print('【1】pad 在各分辨率/各模板宽下必须非负（调**真实代码**算，不复算公式）')
    print('   %-8s %-10s %-8s %s' % ('px', '模板宽dw', 'pad', '判定'))
    print('   ' + '-' * 44)
    # ⚠⚠ 2026-10-02：本组原先**复算旧公式** `(px-w)/2` 来验，等于把「多格 pad 为负」
    #   这个**真 bug** 当成了期望值 ⇒ 门禁一直绿着，而多格模板（战斗格/大建筑）
    #   取图起点一直被反向偏移 45~285 像素（用户报「战斗格几乎全错」）。
    #   ⇒ 现在改成**直接调 `Board._region()` 反推真实 pad**（源码怎么写就怎么测），
    #     并把**多格宽度**一并覆盖（单格 dw=30 只是最小 case）。
    _B = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0})
    import re as _re
    _src = io.open(os.path.join(CORE, 'spots.py'), encoding='utf-8').read()
    _i = _src.index('    def _region(')
    _body = _src[_i:_src.index('\n    def ', _i + 10)]
    # ⚠⚠ **只取代码行，跳过文档字符串** —— 那一大段注释里也写着
    #   `pad = (px − dw/DESIGN_PITCH*px) / 2 = (96 − 90) / 2` 这样的**推导**，
    #   用正则扫全文会匹配到注释，把结论带歪（2026-10-02 踩过）✗
    _code = _body
    _m = _re.search(r'"""(.*?)"""', _body, _re.S)
    if _m:                        # 把 docstring 整段挖掉再匹配
        _code = _body[:_m.start()] + _body[_m.end():]
    _pm = _re.search(r'^\s*pad\s*=\s*(.+?)\s*$', _code, _re.M)
    _pad_expr = ' '.join(_pm.group(1).split()) if _pm else '(px - w) / 2.0'
    print('   源码里的 pad 表达式：%s' % _pad_expr)
    n_pad_ok = n_pad = 0
    for px in (96.0, 144.0, 108.0, 72.0):
        for dw in (30, 62, 94, 126, 158, 222):       # 单格 + 各档多格
            w = int(round(dw / SP.DESIGN_PITCH * px))
            try:
                pad = eval(_pad_expr, {'px': px, 'w': w, 'DESIGN_PITCH': SP.DESIGN_PITCH})
            except Exception:                          # noqa: BLE001
                continue
            n_pad += 1
            ok = pad >= 0
            n_pad_ok += ok
            check('   px=%-5.0f dw=%-5d w=%-5d pad=%+7.1f' % (px, dw, w, pad), ok,
                  '' if ok else '  ⛔ 负数 ⇒ 取图起点反向偏移 ⇒ 模板与画面错位')
    check('① pad 全部非负（单格居中 / 多格以 anchor 为原点）',
          n_pad and n_pad_ok == n_pad, '%d/%d 项' % (n_pad_ok, n_pad))
    # ⭐ 真实取图：多格模板在**左边缘**必须取得到
    #   （pad 为负时 x0 会跑到画面左侧外 ⇒ `_region` 返回 None ⇒ 正确模板被丢弃；
    #     这正是修复前 `5,1` 认不出来的原因：x0 算成 −69）
    #   ⚠ 只查**左边缘**：右边缘越界是**正常裁剪**（7 列盘放不下 4 格宽模板贴右边），
    #     那不是 bug，别把判据写宽了误报。
    _img = cv2.imdecode(np.fromfile(os.path.join(HERE, FRAMES[0]), np.uint8),
                        cv2.IMREAD_COLOR) if FRAMES and os.path.exists(
                            os.path.join(HERE, FRAMES[0])) else None
    if _img is not None:
        _b2 = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0})
        _miss = []
        for _dw, _cols in ((62, (1, 2, 5)), (94, (1, 2, 4)), (126, (1, 2))):
            for _c in _cols:                # 都放得下的列，只测左边缘
                if _b2._region(_img, 3, _c, _dw, 62) is None:
                    _miss.append('dw=%d @列%d' % (_dw, _c))
        check('① 多格模板在左边缘也取得到图（pad 负数会被判越界而丢弃）',
              not _miss, '、'.join(_miss[:4]))

    print()
    print('【2】真机帧：NCC 分数必须达到门槛（0.80）')
    print('   %-16s %7s %9s %8s %8s' % ('帧', 'Board', 'score中位', '>=0.80', 'anchor非None'))
    print('   ' + '-' * 60)
    n_strong_ok = 0
    n_anchor_ok = 0
    n = 0
    for p in FRAMES:
        fp = os.path.join(HERE, p)
        if not os.path.exists(fp):
            continue
        img = cv2.imdecode(np.fromfile(fp, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        n += 1
        b = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0,
                                     'cx': 96.0, 'cy': 96.0})
        st = b.state(img)
        if not st:
            check('帧 %s 能分类' % os.path.basename(p), False)
            continue
        sc = sorted(float((v or {}).get('score') or 0) for v in st.values())
        strong = sum(1 for v in st.values()
                     if float((v or {}).get('score') or 0) >= 0.80)
        n_anchor = sum(1 for v in st.values() if v.get('anchor') is not None)
        n_strong_ok += 1 if strong > 0 else 0
        n_anchor_ok += 1 if n_anchor > 0 else 0
        print('   %-16s %7d %9.3f %8d %8d' % (os.path.basename(p)[:16], len(st),
                                              sc[len(sc) // 2], strong, n_anchor))

    print()
    print('【3】结论')
    check('① 多数帧有格达到 0.80 门槛（识别真的在工作）',
          n and n_strong_ok >= max(1, n - 1), '%d/%d 帧' % (n_strong_ok, n))
    check('② 多数帧 anchor 非 None（board 能记 ⇒ 规划有输入）',
          n and n_anchor_ok >= max(1, n - 1), '%d/%d 帧' % (n_anchor_ok, n))

    print()
    print('【4】源码里 _region 确实用 px 公式（防注释在、代码没了）')
    try:
        src = io.open(os.path.join(CORE, 'spots.py'), encoding='utf-8').read()
    except OSError as e:                          # noqa: BLE001
        check('读得到 spots.py', False, repr(e))
        src = ''
    body = src
    if 'def _region' in body:
        body = body[body.index('def _region'):]
        body = body[:body.index('\n    def ') if '\n    def ' in body else len(body)]
    check('③ _region 里不再用 DESIGN_TILE * self.scale 算 pad',
          'DESIGN_TILE * self.scale' not in body)
    # ⚠ ④ 原判据是逐字匹配 `pad = (px - w) / 2.0`，但那个公式**只对单格成立**
    #   （多格 w>px ⇒ pad 为负 ⇒ 取图起点反向偏移 45~285px ⇒ 战斗格全错）。
    #   逐字匹配挡不住「单格对、多格错」⇒ 改成验**多格被显式处理**这一事实。
    check('④ 多格模板（w>px）被显式处理，不与单格共用居中公式',
          ('w <= px' in body or 'w>px' in body or 'max(0.0' in body)
          and 'pad = (px - w) / 2.0' not in body,
          'body 里 pad 相关：%s'
          % [ln.strip() for ln in body.splitlines() if 'pad =' in ln][:2])

    # ⭐⭐ ⑤ 真正的行为判据：**用户 2026-10-02 手工核对的真值**不许再错
    #   （真机帧 runs/r_122222_0.png，他逐格告诉我的）：
    #     1,3 = 221 游乐设施（五格紫）  3,4 = 103 游乐设施（两格绿）
    #     5,4 = 103 游乐设施（两格绿）  5,1 = 102 海边游客（鸭子，两格）
    #   ⚠ 这几条**修复前全是错的**（认成 巨大沙堡/黄金宝库/金属宝箱怪/传承祭坛），
    #     分数只有 0.04~0.40 ⇒ 这是「战斗格几乎全错」的直接证据。
    _tf = os.path.join(HERE, 'runs', 'r_122222_0.png')
    if os.path.exists(_tf):
        _im = cv2.imdecode(np.fromfile(_tf, np.uint8), cv2.IMREAD_COLOR)
        _bb = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0, 'cx': 96.0,
                                       'cy': 96.0, 'pitch': 96.0})
        _st = _bb.state(_im)
        _truth = {(1, 3): 'S00003_221', (3, 4): 'S00003_103',
                  (5, 4): 'S00003_103', (5, 1): 'S00003_102'}
        for _k, _want in sorted(_truth.items()):
            _v = _st.get(_k) or {}
            _got = str(_v.get('sid') or '?')
            _sc = float(_v.get('score') or 0)
            check('⑤ %d,%d = %s（用户手工核对真值，置信度≥0.45）'
                  % (_k[0], _k[1], _want.split('_')[-1]),
                  _got == _want and _sc >= 0.45,
                  '实际 %s %.3f' % (_got, _sc))
    else:
        check('⑤ 真机帧 runs/r_122222_0.png 存在', False, '缺 ⇒ 跳真值核对')

    # ── ⭐⭐ ⑥ 多格块**归属修正**（2026-10-02 用户手工核对后加）──
    #   真机帧 `runs/r_132022_0.png`，用户逐格告诉我的真值：
    #     · 3,3 4,3 4,5          = 三格 海边杂物(104)      —— 其中 4,5~4,7 是一整块
    #     · 3,2 4,2 4,3 4,4      = 四格 巨大沙堡(211)
    #     · 1,3 2,3              = 两格 椰树(101)
    #   ⚠ 修复前 `4,3` 认成 **014 限时礼包 0.435**（只比 211 的 0.425 高 0.01）
    #     ⇒ 因为 `explore_blocks` 只认 `EXPLORE_SUFFIX`(221/321/331)，
    #       **战斗格全漏网** ⇒ 成员格各用各的 top1 ⇒ 被单格模板抢走。
    #   ⇒ 现在按**数据驱动**（地块表 SpotSize>1 ∪ 紫橙）纳入全部多格块。
    #   判据 = **整块**（anchor + 全部成员格 sid 一致），不是逐格单看。
    _mf = os.path.join(HERE, 'runs', 'r_132022_0.png')
    if os.path.exists(_mf):
        _im2 = cv2.imdecode(np.fromfile(_mf, np.uint8), cv2.IMREAD_COLOR)
        _b3 = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0, 'cx': 96.0,
                                       'cy': 96.0, 'pitch': 96.0})
        _st2 = _b3.state(_im2)
        _want = {(1, 3): 'S00003_101', (2, 3): 'S00003_101',          # 椰树 2 格
                 (3, 2): 'S00003_211', (4, 2): 'S00003_211',          # 巨大沙堡 4 格
                 (4, 3): 'S00003_211', (4, 4): 'S00003_211',
                 (3, 3): 'S00003_104', (3, 4): 'S00003_104',          # 海边杂物 3 格
                 (3, 5): 'S00003_104',
                 (4, 5): 'S00003_104', (4, 6): 'S00003_104',
                 (4, 7): 'S00003_104'}
        _bad = []
        for _k, _w in sorted(_want.items()):
            _g = str((_st2.get(_k) or {}).get('sid') or '?')
            if _g != _w:
                _bad.append('%d,%d 应%s 实%s' % (_k[0], _k[1],
                                                 _w.split('_')[-1], _g.split('_')[-1]))
        check('⑥ 多格块成员格全部归属正确（含曾被单格模板抢走的 4,3）',
              not _bad, '、'.join(_bad[:4]))
        # 整块性：同一块的 anchor 相同、成员格数正确
        for _a, _n in (((1, 3), 2), ((3, 2), 4), ((3, 3), 3), ((4, 5), 3)):
            _anc = tuple((_st2.get(_a) or {}).get('anchor') or _a)
            _mem = [_k for _k in _want
                    if tuple((_st2.get(_k) or {}).get('anchor') or _k) == _anc]
            check('⑥ 整块 %s 成员 %d 格（用户核对值）'
                  % (_n, _n), len(_mem) == _n, '实际 %d：%s' % (len(_mem), sorted(_mem)))
    else:
        check('⑥ 真机帧 runs/r_132022_0.png 存在', False, '缺 ⇒ 跳归属核对')

    # ── ⑦ 门槛 0.35 不许回涨（2026-10-02 用户核对时发现 1,1+1,2 没合并）──
    #   真机帧 `runs/r_133328_0.png`：`1,1`+`1,2` 是 **102 海边游客**（用户核对），
    #   但 102 在那两格的分数只有 **0.370** ⇒ 被 `MULTI_BLOCK_MIN=0.40` 差 0.03 滤掉
    #   ⇒ 两格没合并（用户原话：「11，12也是，但是没有用绿色框框起来」）✗
    #   ⇒ 门槛降到 0.35 修好。⚠ 仍高于纯噪声（实测最低多格候选 0.157）。
    _mf2 = os.path.join(HERE, 'runs', 'r_133328_0.png')
    if os.path.exists(_mf2):
        _im3 = cv2.imdecode(np.fromfile(_mf2, np.uint8), cv2.IMREAD_COLOR)
        _b4 = SP.Board('S00003', grid={'x0': 24.0, 'y0': 668.0, 'cx': 96.0,
                                       'cy': 96.0, 'pitch': 96.0})
        _st3 = _b4.state(_im3)
        _w2 = {(1, 1): 'S00003_102', (1, 2): 'S00003_102',     # 海边游客（0.370！）
               (3, 4): 'S00003_102', (3, 5): 'S00003_102',     # 海边游客（0.536）
               (1, 4): 'S00003_302', (1, 5): 'S00003_302',     # 海边小屋 6 格
               (1, 6): 'S00003_302', (2, 4): 'S00003_302',
               (2, 5): 'S00003_302', (2, 6): 'S00003_302',
               (4, 1): 'S00003_211', (5, 1): 'S00003_211',     # 巨大沙堡 4 格
               (5, 2): 'S00003_211', (5, 3): 'S00003_211'}
        _bad2 = []
        for _k, _v in sorted(_w2.items()):
            _g2 = str((_st3.get(_k) or {}).get('sid') or '?')
            if _g2 != _v:
                _bad2.append('%d,%d 应%s 实%s' % (_k[0], _k[1],
                                                 _v.split('_')[-1], _g2.split('_')[-1]))
        check('⑦ 低分多格块也能合并（1,1+1,2 的 102 只有 0.370）',
              not _bad2, '、'.join(_bad2[:4]))
        _a11 = tuple((_st3.get((1, 1)) or {}).get('anchor') or (1, 1))
        _a12 = tuple((_st3.get((1, 2)) or {}).get('anchor') or (1, 2))
        check('⑦ 1,1 与 1,2 同属一块（绿框该框住它们）',
              _a11 == _a12, 'anchor %s vs %s' % (_a11, _a12))
    else:
        check('⑦ 真机帧 runs/r_133328_0.png 存在', False, '缺 ⇒ 跳低分合并核对')

    print()
    print('=' * 78)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
    for b in BAD:
        print('   ✗ ' + b)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
