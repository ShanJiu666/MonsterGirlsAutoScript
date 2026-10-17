# -*- coding: utf-8 -*-
"""⭐ 回归：**「顶部自洽」补充判据**（2026-10-16 用户报「旅行商人没识别到」）。

用户原话：「`r_001804_0.png` / `r_001906_0.png` 没识别到旅行商人？」

⭐ 根因（真机铁证，用户在图上指出商人在 `1,7` / `4,7`）：
    · 分类器**认对了** —— `top1/2/3` 全是 `S10003_008 旅行商人`
    · 但分数 **0.727 / 0.689** < `BUY_SCORE_MIN(0.85)` ⇒ **被门槛挡掉** ✗
    · 而 0.85 当年的依据样本**只覆盖黄金宝库**（它确实 0.999）；
      **旅行商人天生低**：雾里 0.689~0.727、**已亮也才 0.847** ✗
      （⚠ 不是亮度/饱和度问题：两者雾里饱和 14.1 vs 13.8、模板也都彩色 140 vs 145 ✓）

⭐ 修法（**用户选定**：「不改绝对门槛，改用顶部自洽」）：
    `strong = (score >= 0.85) or _buy_top_self(v)`
    `_buy_top_self` = `top[0]` 与"第一个不同 sid"的**分数差 >= 0.30**

⭐ 0.30 的标定（600 张真机帧 + 人眼核对拼图）：
    真目标 gap = **0.343 / 0.353 / 0.477 / 0.656** ✓
    误报   gap = **0.054 / 0.255**（图上是**模糊的树/石头**）✗

⚠⚠ 撤回守门：**不许**把判据写成"top 里连续同 sid 的个数 k >= 3" ——
   实测 793 个格的 `k` **全是 3**（每类有多个动画帧）⇒ **恒真、毫无区分度** ✗
   （我第一版就是这么写的 ⇒ 本门禁专门钉住这一点 ✓）

用法：python verify_buy_topself.py
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
import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402
import explore_loop as EL                                       # noqa: E402
import spots                                                    # noqa: E402


N_PASS = [0]
FAILS = []


def ck(name, cond, detail=''):
    if cond:
        N_PASS[0] += 1
    else:
        FAILS.append(name)
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))


def gap_of(v):
    """`top[0]` 与"第一个不同 sid"的分数差 ⇒ float / None"""
    try:
        top = (v or {}).get('top') or []
        if len(top) < 2:
            return None
        sid0 = top[0][1]
        for t in top[1:]:
            if t[1] != sid0:
                return float(top[0][0]) - float(t[0])
        return None
    except Exception:                                           # noqa: BLE001
        return None


NAME = {k: (v.get('Name') or '?') for k, v in spots.spot_rows().items()}
G = spots.GRID
X0, Y0, CX, CY = G['x0'], G['y0'], G['cx'], G['cy']


def centre(r, c):
    return (int(X0 + (c - 1) * CX + CX / 2), int(Y0 + (r - 1) * CY + CY / 2))


def cells_of(fn):
    p = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs', 'acc3'), fn)
    if not os.path.exists(p):
        return None
    im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    return EL.cells_of(im, mapname='铁血高地')


def in_buy(cells, cell):
    cc = centre(*cell)
    return (cc in [tuple(x) for x in (cells.get('buy') or [])]
            or cc in [tuple(x) for x in (cells.get('buy_hidden') or [])])


print('=' * 84)
print('「顶部自洽」判据回归（旅行商人被 BUY_SCORE_MIN 误挡）')
print('=' * 84)
print()

print('【1】结构级')
ck('① `BUY_SCORE_MIN` **保持 0.85**（没被降 ✗ 那是当年的卡死防范）',
   abs(float(EL.BUY_SCORE_MIN) - 0.85) < 1e-9,
   'BUY_SCORE_MIN=%s' % EL.BUY_SCORE_MIN)
ck('② `BUY_TOP_GAP_MIN` = 0.30（离线标定值 ✓）',
   abs(float(getattr(EL, 'BUY_TOP_GAP_MIN', -1)) - 0.30) < 1e-9,
   'BUY_TOP_GAP_MIN=%s' % getattr(EL, 'BUY_TOP_GAP_MIN', '（没有）'))
_src = io.open('explore_loop.py', encoding='utf-8').read()
_seg = _src.split('def cells_of')[1].split('\ndef ')[0]
_strong = [l.strip() for l in _seg.splitlines() if l.strip().startswith('strong =')]
ck('③ `cells_of` 里 `strong` = **老判据 `or` 顶部自洽**（两条都要在 ✓）',
   bool(_strong) and 'BUY_SCORE_MIN' in _strong[0]
   and '_buy_top_self' in _strong[0],
   _strong[0] if _strong else '（没找到 ✗）')
_fun = _src.split('def _buy_top_self')[1].split('\ndef ')[0]
ck('④ ⛔ 撤回守门：`_buy_top_self` **不许**用"连续同 sid 的个数 k"当判据'
   '（实测 k 恒为 3 ⇒ 毫无区分度 ✗）',
   'kmin' not in _fun and 'k >= ' not in _fun,
   '（判据必须是 top[0] 与第一个不同 sid 的**分数差** ✓）')

print()
print('【2】行为级：**用户报的那两格必须被收进来**')
OK_CASES = [
    ('r_001804_0.png', (1, 7), '旅行商人', '用户报的第 1 张（雾里）'),
    ('r_001906_0.png', (4, 7), '旅行商人', '用户报的第 2 张（雾里）'),
    ('r_142856_0.png', (5, 5), '旅行商人', '已亮商人（老门槛差 0.003 也被挡 ✗）'),
]
_missing = []
for fn, cell, want, note in OK_CASES:
    cells = cells_of(fn)
    if cells is None:
        _missing.append(fn)
        continue
    v = (cells.get('st') or {}).get(cell) or {}
    nm = NAME.get(v.get('sid'))
    sc = float(v.get('score') or 0)
    hit = in_buy(cells, cell)
    ck('⑤ %-18s %-6s %-8s %.3f ⇒ **收进 buy/buy_hidden** ✓（%s）'
       % (fn, '%d,%d' % cell, nm or '?', sc, note),
       nm == want and hit,
       'name=%s score=%.3f topself=%s hit=%s'
       % (nm, sc, EL._buy_top_self(v), hit))

print()
print('【3】⚠ 对照项：**误报必须仍然被挡**（否则判据太松 ✗）')
for fn, cell in (('r_144530_0.png', (2, 7)), ('r_150205_0.png', (3, 1))):
    cells = cells_of(fn)
    if cells is None:
        _missing.append(fn)
        continue
    v = (cells.get('st') or {}).get(cell) or {}
    hit = in_buy(cells, cell)
    ck('⑥ %-18s %-6s %.3f（低分误报）⇒ **仍被挡** ✓'
       % (fn, '%d,%d' % cell, float(v.get('score') or 0)),
       (not EL._buy_top_self(v)) and (not hit),
       'topself=%s hit=%s gap=%s' % (EL._buy_top_self(v), hit, gap_of(v)))

print()
print('【4】判据的数值边界（拿真帧的 top 直接算）')
_c = cells_of('r_001804_0.png')
if _c:
    _v = (_c.get('st') or {}).get((1, 7)) or {}
    _g = gap_of(_v)
    ck('⑦ 用户那格的 gap = %s ⇒ **>= 0.30**（判据该收它 ✓）'
       % ('%.3f' % _g if _g is not None else 'None'),
       bool(_g is not None and _g >= EL.BUY_TOP_GAP_MIN),
       'gap=%s 门槛=%s' % (_g, EL.BUY_TOP_GAP_MIN))
_c2 = cells_of('r_144530_0.png')
if _c2:
    _v2 = (_c2.get('st') or {}).get((2, 7)) or {}
    _g2 = gap_of(_v2)
    ck('⑧ 误报那格的 gap = %s ⇒ **< 0.30**（判据该挡它 ✓）'
       % ('%.3f' % _g2 if _g2 is not None else 'None'),
       bool(_g2 is not None and _g2 < EL.BUY_TOP_GAP_MIN),
       'gap=%s 门槛=%s' % (_g2, EL.BUY_TOP_GAP_MIN))

print()
if _missing:
    print('   ⚠ 缺帧（**未验证**，非代码问题）：%s' % sorted(set(_missing)))
print('=' * 84)
if FAILS:
    print('通过 %d 项，失败 %d 项' % (N_PASS[0], len(FAILS)))
    for f in FAILS:
        print('   ✗ %s' % f)
    raise SystemExit(1)
print('通过 %d 项，失败 0 项' % N_PASS[0])
