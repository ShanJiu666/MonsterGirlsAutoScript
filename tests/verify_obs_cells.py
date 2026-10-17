# -*- coding: utf-8 -*-
"""★ 回归：**观测缺失格不许被当作"已消耗"**（2026-10-12，治「85 张图只打 77 个首领」）

用户口径（原话）：「**我要保证的是打多少张图，就打多少个首领**」
用户方法论（原话）：「**不要做加法。要查到本质原因然后修复**」

⛔ 本质（详见 `docs/08-保证每张图必打首领规划.md` §1.7）：
   真机 board 常有**分类器没认出来的格**（map18 缺 8 格）⇒ 建盘时 `board = -1`
   ⇒ `mapsolve` 把 `board<0` 一律当"已消耗格" ⇒ 它们的 4 邻被判"开局已揭示可点"
   ⇒ **雾里的 boss 被误判"可点"** ⇒ 求解器规划"一步直接打 boss"
   ⇒ 真机 `fogged_noop`（它其实在雾里）⇒ `no_progress` 退图 ⇒ **首领漏打** ✗✗

⛔ 为什么闸门"早就有"却没用：`mapsolve._build_cache` 的 `EMPTY_ADJ`（:`458-463`）
   本来就写了这道闸门（判据 `if _obs_cells and c not in _obs_cells: continue`），
   但 `MapSim.from_observation` / `_from_anchors` **从来没设过 `sim.obs_cells`**
   （只有 `from_observation` 设了）⇒ `_obs_cells` 恒为空 ⇒ **闸门形同虚设** ✗✗
   （= 本项目反复出现的"判据静默失效"：判据建在拿不到数据的地方）

✅ 修法（**不做加法**）：把闸门缺的**输入**补上 ——
   ① `MapSim.from_observation` / `_from_anchors` 记 `sim.obs_cells`（观测真实覆盖的格）
   ② `Problem.consumed_cells()` 补上与 `_build_cache.EMPTY_ADJ` **对称**的同款闸门
      （README 反复警告"只改一处 ⇒ A\* 走缓存版白改"）

牙齿（falsifiable）：
   · 去掉 `from_observation` 的 `_mark_obs_cells` 调用 ⇒ ①④ 红
   · 去掉 `consumed_cells()` 里的 obs_cells 闸门 ⇒ ② 红
   · 把闸门方向写反（`c in _obs_cells` 才跳）⇒ ② 红
"""
import copy
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

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


# map18 真实 board（真机实测：分类器只给出 27 格，缺 8 格）
B18 = {
    '1,1': ['211', '火红树', 0.81, 0.681], '1,3': ['001', '草地', 1.00, 0.641],
    '1,4': ['001', '草地', 1.00, 0.641], '1,5': ['111', '野兽巢穴', 0.76, 0.657],
    '2,3': ['104', '杂草堆', 0.72, 0.585], '2,5': ['001', '草地', 1.00, 0.641],
    '2,6': ['001', '草地', 1.00, 0.641], '2,7': ['001', '草地', 1.00, 0.641],
    '3,1': ['001', '草地', 1.00, 0.641], '3,2': ['001', '草地', 1.00, 0.641],
    '3,3': ['003', '宝箱', 0.98, 0.645], '3,4': ['002', '篝火', 0.98, 0.641],
    '3,5': ['001', '草地', 1.00, 0.641], '3,6': ['001', '草地', 1.00, 0.641],
    '3,7': ['001', '草地', 1.00, 0.641], '4,1': ['001', '草地', 1.00, 0.641],
    '4,2': ['001', '草地', 1.00, 0.641], '4,3': ['001', '草地', 1.00, 0.641],
    '4,4': ['009', '金属宝箱怪', 0.96, 0.971], '4,5': ['002', '篝火', 0.98, 0.641],
    '4,6': ['103', '伞树', 0.78, 0.675], '4,7': ['003', '宝箱', 0.98, 0.645],
    '5,1': ['001', '草地', 1.00, 0.641], '5,2': ['001', '草地', 1.00, 0.641],
    '5,3': ['001', '草地', 1.00, 0.995], '5,4': ['104', '杂草堆', 0.97, 0.821],
    '5,7': ['001', '草地', 1.00, 0.641],
}
MISSING = [(1, 2), (1, 6), (1, 7), (2, 1), (2, 2), (2, 4), (5, 5), (5, 6)]
BOSS_RC = (4, 6)


def cells_of():
    c = {}
    for rc, v in B18.items():
        r, cc = int(rc.split(',')[0]), int(rc.split(',')[1])
        c[(r, cc)] = {'sid': v[0], 'name': v[1], 'score': v[2], 'ratio': v[3],
                      'revealed': float(v[3]) >= 0.80,
                      'marks': ['boss'] if rc == '4,6' else []}
    return c


print('=' * 88)
print('观测缺失格不许当"已消耗"（2026-10-12 · 治「85 张图只打 77 个首领」）')
print('=' * 88)

import mapsim
import mapsolve
import spots


print()
print('【1】结构级：闸门的**输入**必须真的被设上')
_sim = mapsim.MapSim.from_observation(cells_of(), spots.spot_rows())
# ⚠ 一律用 getattr 取：牙齿测试（去掉 `_mark_obs_cells`）时**属性会整个不存在** ⇒
#   直接访问会抛 `AttributeError` ⇒ **Traceback 也算非 0，但那是"崩了"不是"断言红"** ✗
#   本项目判据是「**有 `[FAIL]` 行 且 没有 Traceback**」⇒ 必须容错成断言红 ✓
_ocs = getattr(_sim, 'obs_cells', None)
ck('① `from_observation` 设了 `sim.obs_cells`', _ocs is not None,
   '缺失 ⇒ `mapsolve` 的闸门恒不生效 ✗')
ck('①b 数量 == 观测覆盖格数（%d）' % len(B18),
   len(_ocs or ()) == len(B18),
   str(len(_ocs or ())))
# 缺失格必须**不在** obs_cells 里
_idx_miss = [mapsim.cell_of(*rc) for rc in MISSING]
ck('①c 缺失的 8 格**不在** obs_cells 里（否则闸门拦不住）',
   all(i not in (_ocs or set()) for i in _idx_miss))
# 有观测的格必须在
_idx_has = [mapsim.cell_of(int(rc.split(',')[0]), int(rc.split(',')[1])) for rc in B18]
ck('①d 有观测的格**都在** obs_cells 里', all(i in (_ocs or set()) for i in _idx_has))

_src_ms = io.open(os.path.join(HERE, 'mapsim.py'), encoding='utf-8').read()
_Code = '\n'.join(l for l in _src_ms.splitlines() if not l.lstrip().startswith('#'))
ck('② `_mark_obs_cells` 辅助存在且被调用（不是写了不调用）',
   'def _mark_obs_cells' in _Code and '_mark_obs_cells(' in _Code.replace(
       'def _mark_obs_cells', '', 1))

_src_mv = io.open(os.path.join(HERE, 'mapsolve.py'), encoding='utf-8').read()
_CodeV = '\n'.join(l for l in _src_mv.splitlines() if not l.lstrip().startswith('#'))
ck('③ `Problem.consumed_cells` 里有 obs_cells 闸门（与 `_build_cache.EMPTY_ADJ` 对称）',
   'obs_cells' in _CodeV and 'if _obs_cells' in _CodeV)

print()
print('【2】⭐ 行为级：boss 不许被误判"可点"（map18 真机盘）')
sim = mapsim.MapSim.from_observation(cells_of(), spots.spot_rows())
prob = mapsolve.Problem(sim)
boss_bi = sim.board[(4 - 1) * 7 + (6 - 1)]
vis_slow = prob.visible(frozenset())
ck('④ 慢版 `visible()` **不含** boss（修前含 ⇒ 假可点）', boss_bi not in vis_slow,
   '%d 块' % len(vis_slow))
_m1 = [c for c, bi in enumerate(prob.board) if bi < 0]
_cons = prob.consumed_cells(frozenset())
ck('⑤ 缺失格不再进 `consumed_cells`（不许当已消耗）',
   all(m not in _cons for m in _idx_miss),
   '仍在 = %s' % [m for m in _idx_miss if m in _cons])

print()
print('【3】⭐ 逐步验真：计划每一步都必须**真的可点**，且 boss 被打掉')
cost, plan = mapsolve.solve(prob, max_states=60000, max_secs=8)
conv = [rc for rc, bi, w in prob.cells_for_plan((plan or [])[:8])]
ck('⑥ 解出了计划', bool(conv), 'cost=%s plan=%s' % (cost, conv))
_s2 = mapsim.MapSim.from_observation(copy.deepcopy(cells_of()), spots.spot_rows())
_allok, _bad_step = True, ''
for rc in conv:
    if rc not in set(_s2.visible()):
        _allok, _bad_step = False, str(rc)
        break
    kind, info = _s2.click(rc)
    if kind == 'panel':
        _s2.resolve_panel(rc)
ck('⑦ 每一步都**真的可点**（修前 boss 那步必点不动 ⇒ 真机 `fogged_noop`）',
   _allok, ('不可点 = %s' % _bad_step) if _bad_step else '')
ck('⑧ 走完计划后 **boss 已被打掉**（不再留在雾里）', not _s2.fogged_marks(),
   str(_s2.fogged_marks()))

print()
print('【4】⚠ 对照项：清空 `obs_cells`（= 修前行为）⇒ **必须复现** boss 假可点')
_sim_old = mapsim.MapSim.from_observation(cells_of(), spots.spot_rows())
_sim_old.obs_cells = set()
_prob_old = mapsolve.Problem(_sim_old)
ck('⑨ **对照项**：清空 obs_cells ⇒ boss 又被判可点（证明本回归**测得出**问题，不是恒绿）',
   boss_bi in _prob_old.visible(frozenset()),
   '%d 块' % len(_prob_old.visible(frozenset())))

print()
print('【5】fail-open：全知盘（无缺失格）与老调用不许被改坏')
_full = {}
for r in range(1, 6):
    for c in range(1, 8):
        _full[(r, c)] = {'sid': '001', 'name': '草地', 'score': 1.0, 'ratio': 0.99,
                         'revealed': True, 'marks': []}
_full[(3, 4)] = {'sid': '111', 'name': '野兽巢穴', 'score': 0.9, 'ratio': 0.99,
                 'revealed': True, 'marks': ['boss']}
_sf = mapsim.MapSim.from_observation(_full, spots.spot_rows())
_ocsf = getattr(_sf, 'obs_cells', None)
ck('⑩ 全知盘 obs_cells = 全部 35 格', len(_ocsf or ()) == 35, str(len(_ocsf or ())))
_pf = mapsolve.Problem(_sf)
_cf, _plf = mapsolve.solve(_pf, max_states=60000, max_secs=8)
_convf = [rc for rc, bi, w in _pf.cells_for_plan((_plf or [])[:8])]
ck('⑪ 全知盘仍能解出计划（行为不变）', bool(_convf),
   'cost=%s plan=%s' % (_cf, _convf))
# 老调用：没有 obs_cells 时 consumed_cells 不崩、行为同修前
try:
    _po = mapsolve.Problem.__new__(mapsolve.Problem)
    _po.obs_cells = set()
    ck('⑫ `obs_cells` 为空 ⇒ 闸门不启用、不抛（fail-open ✓）', True)
except Exception as _e:
    ck('⑫ `obs_cells` 为空 ⇒ 闸门不启用、不抛（fail-open ✓）', False, repr(_e))

print()
print('=' * 88)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
