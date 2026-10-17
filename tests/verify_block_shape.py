# -*- coding: utf-8 -*-
"""★ 回归：**按"空出来的形状"判多格块真假**（2026-10-14 用户口径）

用户原话（两次）：
  ① 10-12：「**把营地和附近两格合体成多格了，营地不可能是战斗格啊**」
  ② 10-14：「**第二张图的巨大沙堡没识别出来？**」
     ＋（我问怎么修）「**为什么这么低？能不能按空出来的方块形状猜测空出来的这是什么？**」

⛔ 我 10-12 那版判据（**相对量**）分不开这两帧 ✗：
     `top1 >= 0.85` **且** `top1 - 块分 > 0.20` ⇒ 弃块
   而两帧的那个 `211` 块**逐项相同**：
     · `runs/r_194934_0.png`（10-12，**人眼核对：真没沙堡**）
     · `runs/acc1/r_143410_0.png`（10-14，**人眼核对：`2,1` 真有沙堡**）
   块分都 `0.361`、cells 都 `(1,2)(2,2)(2,3)(2,4)` ⇒ 相对量必然同判 ✗

⭐⭐ 用户的判据（**绝对量**，实测完美区分 ✓）：
   看块覆盖的每一格**自己的 top1 分**：
     · **全部偏低** ⇒ 它们是**同一块大美术的碎片** ⇒ **采纳** ✓
     · **有任一格 ≥0.85**（自成一体：营地/草地/宝箱…）⇒ 块**吞了它** ⇒ **弃块** ✗

⭐ 同时把 `MULTI_BLOCK_MIN` **0.35 → 0.28**（两条**一起才成立**）：
   · 只降门槛：40 帧采纳数 97→143（+47%），且真沙堡仍被吞 ✗
   · 只加形状判据：0.35 下真沙堡**根本没进候选** ⇒ 认不出 ✗
   · **两条一起**：118 块，且今天认回 ✓ / 昨天正确拒绝 ✓

⚠ 为什么真沙堡的分只有 0.29 而"水洼"能到 0.36：
   模板 `211` 是**整块 L 形大图**（94×62）⇒ 逐格只截到**局部**
   ⇒ **正确摆放的单格分天生偏低**，而"碰巧像"的地方反而高
   ⇒ 门槛卡在两者之间**必然错** ⇒ 必须靠形状判据兜 ✓
"""
import importlib
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
import cv2
import numpy as np
import explore_loop as EL
import spots


OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料）⇒ **响亮地跳过**（不算通过、也不算失败）。

    ⚠ 公开发布版**不含**开发者的真机录屏语料（本地私有数据）。
    """
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


_S = io.open('spots.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _S.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('按"空出来的形状"判多格块真假（2026-10-14）')
print('=' * 94)

print()
print('【1】结构级')
ck('① ⭐ `MULTI_BLOCK_MIN` = **0.28**（原 0.35 ✓）',
   float(spots.MULTI_BLOCK_MIN) == 0.28, str(spots.MULTI_BLOCK_MIN))
ck('② ⭐ 形状判据用**绝对量**（`>= 0.85`，不再减块分 ✓）',
   'float(_l0[0][0]) >= 0.85' in _CODE)
ck('③ ⚠ 旧的相对量判据（`_s0 - _bs`）**已撤换**', '_s0 - _bs' not in _CODE)
ck('④ 撤换理由留档（注释里写明两帧分不开 ✓）', '分不开这两帧' in _S)

print()
print('【2】⭐⭐⭐ 行为级：两帧各判对（核心）')
_A = os.path.join('runs', 'r_194934_0.png')          # 真没沙堡
_B = os.path.join('runs', 'acc1', 'r_143410_0.png')  # 2,1 真有沙堡


def _castle_and_camp(p):
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    st = (EL.cells_of(img, '夏日海滩') or {}).get('st') or {}
    _castle, _camp = {}, {}
    for k, v in st.items():
        if not isinstance(v, dict):
            continue
        sid, nm = str(v.get('sid') or ''), str(v.get('name') or '')
        if sid.endswith('_211') or '沙堡' in nm:
            _castle['%d,%d' % k] = (nm, v.get('score'), tuple(v.get('anchor') or ()),
                                    tuple(map(tuple, v.get('cells') or [])))
        if '营地' in nm:
            _camp['%d,%d' % k] = (v.get('score'), tuple(v.get('anchor') or ()))
    return _castle, _camp


_HAVE_A = os.path.exists(_A)
_HAVE_B = os.path.exists(_B)
if not (_HAVE_A and _HAVE_B):
    skip('⑤~⑪ 两帧行为级 + 对照项',
         '缺真机语料（发布版不带私有录屏：%s）⇒ 未真正验证'
         % ', '.join(n for n, ok in (('r_194934_0.png', _HAVE_A),
                                     ('acc1/r_143410_0.png', _HAVE_B)) if not ok))

for _p, _tag in ((_B, '今天 B（**2,1 真有沙堡**）'), (_A, '昨天 A（**真没沙堡**）')):
    if not os.path.exists(_p):
        print('     ⚠ 缺语料帧 %s ⇒ 跳过该帧' % os.path.basename(_p))
        continue
    _c, _cp = _castle_and_camp(_p)
    print('     %s ⇒ 沙堡=%s ｜ 营地=%s' % (_tag, _c or '无', _cp))
    if _p == _B:
        ck('⑤ ⭐⭐⭐ **真有沙堡的帧认回来了**（anchor=(2,1) ✓）',
           bool(_c) and all(v[2] == (2, 1) for v in _c.values()),
           str({k: v[2] for k, v in _c.items()}))
        ck('⑥ ⭐ 覆盖格 = [(2,1),(3,1),(3,2),(3,3)]（**正确摆放** ✓）',
           bool(_c) and any(
               v[3] == ((2, 1), (3, 1), (3, 2), (3, 3)) for v in _c.values()),
           str([v[3] for v in _c.values()][:1]))
        ck('⑦ ⭐⭐ 营地**没被吞**（anchor=自己 ✓）',
           bool(_cp) and all(v[1] == (2, 2) for v in _cp.values()),
           str(_cp))
    else:
        ck('⑧ ⭐⭐⭐ **真没沙堡的帧正确拒绝**（不误认 ✓）', not _c, str(_c))
        ck('⑨ ⭐⭐ 营地仍**独立**（anchor=自己 ✓）',
           bool(_cp) and all(v[1] == (2, 2) for v in _cp.values()), str(_cp))

print()
print('【3】⚠⚠ 对照项：**回退任一半就会坏**（证明两条缺一不可 ✓）')
_BAK = io.open('spots.py', encoding='utf-8', newline='').read()
try:
    if not _HAVE_B:
        # ⚠ 对照项本身就要拿那两帧算 ⇒ 没有语料时**不能假装跑过**
        skip('⑩⑪⑫ 对照项（回退任一半就坏）',
             '缺真机语料 runs/acc1/r_143410_0.png ⇒ 未真正验证')
    else:
        # 半①：只把门槛退回去（保留形状判据）
        _m1 = _BAK.replace('MULTI_BLOCK_MIN = 0.28', 'MULTI_BLOCK_MIN = 0.35')
        io.open('spots.py', 'w', encoding='utf-8', newline='').write(_m1)
        importlib.reload(spots)
        importlib.reload(EL)
        _c1, _ = _castle_and_camp(_B) if os.path.exists(_B) else ({}, {})
        print('     只回退门槛（0.35 + 形状判据）⇒ 真有沙堡那帧 = %s' % (_c1 or '**认不出** ✗'))
        ck('⑩ ⚠ **只降门槛不够**：退回 0.35 ⇒ 真沙堡**又认不出** ✓',
           not _c1, str(_c1))
        # 半②：只把形状判据退成"永远采纳"
        _m2 = _BAK.replace('if float(_l0[0][0]) >= 0.85:',
                           'if False:      # 对照：形状判据关掉')
        io.open('spots.py', 'w', encoding='utf-8', newline='').write(_m2)
        importlib.reload(spots)
        importlib.reload(EL)
        _c2, _cp2 = _castle_and_camp(_B) if os.path.exists(_B) else ({}, {})
        # ⚠⚠ 判据要按 **anchor**（不按 `name`）—— 营地被吞时它的 `name` 会变成
        #    「巨大沙堡」⇒ 按名字找**找不到** ⇒ 我第一版因此假红 ✗（探针自己的错）
        _swallowed = bool(_c2) and any(v[2] == (1, 2) for v in _c2.values())
        print('     （关掉形状判据）沙堡块 anchor 集合 = %s'
              % sorted(set(v[2] for v in _c2.values())))
        print('     ⇒ 营地所在 `1,2` 摆放**被采纳了吗** = %s' % _swallowed)
        ck('⑪ ⚠ **只加门槛不够**：关掉形状判据 ⇒ 含营地的 `1,2` 摆放被采纳（营地被吞 ✓）',
           _swallowed, str(sorted(set(v[2] for v in _c2.values()))))
finally:
    io.open('spots.py', 'w', encoding='utf-8', newline='').write(_BAK)
    importlib.reload(spots)
    importlib.reload(EL)
_after = io.open('spots.py', encoding='utf-8', newline='').read()
ck('⑫ 还原**逐字节一致** ✓', _after == _BAK)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
for x in BAD:
    print('   ✗ ' + x)
if SKIP:
    print('   ⚠ 以下 %d 项**没真正验证**（缺真机语料，非代码问题）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.stdout.flush()
os._exit(1 if BAD else 0)
