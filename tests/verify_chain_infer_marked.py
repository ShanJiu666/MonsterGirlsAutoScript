# -*- coding: utf-8 -*-
"""★ 回归：连锁消耗反推**不许剔带标记的格**（2026-10-11「68 张图只打 62 个首领」）

用**真机那次的确切情形**复现：`2,2` 带 boss 标记、亮着、无人能揭示
  · 修前 ⇒ 被判"已消耗" ⇒ 剔出模型 ⇒ 计划里没它 ⇒ `targets_unreachable` ⇒ 退图 ✗
  · 修后 ⇒ **跳过**它 ⇒ 它仍在模型里 ⇒ boss 会被打 ✓
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
import explore_loop as EL

OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('连锁消耗反推 vs 标记格（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
import inspect
_sig = inspect.signature(EL._infer_chain_consumed)
print('     签名 = %s' % _sig)
ck('① 新增 `marked_rc` 参数', 'marked_rc' in _sig.parameters)
_src = io.open('explore_loop.py', encoding='utf-8').read()
_code = '\n'.join(l for l in _src.splitlines() if not l.lstrip().startswith('#'))
ck('② 反推循环里有"跳过带标记格"的分支',
   'chain_infer_skip_marked' in _code)
ck('③ 调用点传了 `marked_rc`', 'marked_rc=_marked_rc' in _code)

print()
print('【2】⭐ 行为级：复现真机那张图（`2,2` 带 boss 标记）')
# 造一个最小局面：
#   营地 (3,3)，其 4 邻被解释 ⇒ 覆盖
#   `2,2` 亮着、是草地、**没人能揭示它** ⇒ 修前必被判"已消耗" ✗
CELLS = {}
for _r in range(1, 6):
    for _c in range(1, 8):
        CELLS[(_r, _c)] = {'name': '草地', 'revealed': False, 'score': 0.99}
# 营地亮着
CELLS[(3, 3)] = {'name': '营地', 'revealed': True, 'score': 0.98}
# `2,2` 亮着 + 是草地（分类器把它当草地 → 正是被误剔的原因 ✓）
CELLS[(2, 2)] = {'name': '草地', 'revealed': True, 'score': 0.99}
# 让 (2,2) 无人能揭示：把它的 4 邻都设成**未亮**
for _n in ((1, 2), (3, 2), (2, 1), (2, 3)):
    CELLS[_n] = {'name': '草地', 'revealed': False, 'score': 0.99}

# ① 修前口径（不传 marked_rc）
_l1 = []
_r1 = EL._infer_chain_consumed(dict(CELLS), (3, 3), seed_rc=set(), log=_l1,
                               tag='solver')
print('     不传 marked_rc ⇒ consumed 含 (2,2) 吗 = %s' % ((2, 2) in _r1))
ck('④ ⚠ **对照项**：不传 `marked_rc` ⇒ (2,2) **仍被误剔**（证明本回归测得出 ✓）',
   (2, 2) in _r1, str(sorted(_r1))[:80])

# ② 修后口径（传 marked_rc）
_l2 = []
_r2 = EL._infer_chain_consumed(dict(CELLS), (3, 3), seed_rc=set(), log=_l2,
                               tag='solver', marked_rc={(2, 2)})
print('     传 marked_rc={(2,2)} ⇒ consumed 含 (2,2) 吗 = %s' % ((2, 2) in _r2))
ck('⑤ ⭐ 传了 `marked_rc` ⇒ (2,2) **不再被剔**（boss 会留在模型里 ✓）',
   (2, 2) not in _r2, str(sorted(_r2))[:80])
ck('⑥ ⭐ 如实落了 `chain_infer_skip_marked`（不静默 ✓）',
   any(isinstance(e, dict) and e.get('solver') == 'chain_infer_skip_marked'
       for e in _l2), str(_l2)[:120])

print()
print('【3】⚠ fail-open：**别把原来该剔的空地也放过了**')
# 加一个**没标记**的亮格 (5,5)，4 邻全暗 ⇒ 它**应该照旧被剔** ✓
CELLS[(5, 5)] = {'name': '草地', 'revealed': True, 'score': 0.99}
for _n in ((4, 5), (5, 4), (5, 6)):
    CELLS[_n] = {'name': '草地', 'revealed': False, 'score': 0.99}
_l3 = []
_r3 = EL._infer_chain_consumed(dict(CELLS), (3, 3), seed_rc=set(), log=_l3,
                               tag='solver', marked_rc={(2, 2)})
print('     consumed = %s' % sorted(_r3))
ck('⑦ ⚠ **无标记**的亮格 (5,5) **照旧被剔**（原效用没被破坏 ✓）',
   (5, 5) in _r3, str(sorted(_r3)))
ck('⑧ ⭐ 同时 (2,2) 仍被保住', (2, 2) not in _r3)

print()
print('【4】⭐ 用**真机那张图的真实数据**复算')
import json

try:
    # ⛔⛔ 2026-10-11 **修本回归的假红**（和第 N 次一样：指向了**会滚动的日志** ✗）
    #   原来只读 `runs/acc1/loop/loop_log.json` 一个文件
    #   ⇒ 那个文件**会被后续运行覆盖**（滚动日志，现在里面已经没有那条记录了）
    #   ⇒ `chain_consumed_inferred` 0 条 ⇒ 断言"确实有重叠"失败 ✗
    #     （**代码没坏，是数据源被冲掉了** ✗）
    #   ⇒ 修法：扫**所有**历史 loop_log（含 `_prev` 等），只要有**任一**实例即可 ✓
    #     ⚠ 判据从"必须 ≥1 条"改成"**扫到的总条数里必须有重叠**"，
    #       但**允许历史被清空时跳过**（否则日志一轮换门禁就红 ✗）
    import glob as _g
    _FILES = sorted(_g.glob('runs/**/loop/loop_log*.json', recursive=True))
    _d = []
    for _p in _FILES:
        try:
            _one = json.load(io.open(_p, encoding='utf-8'))
        except Exception:       # noqa: BLE001
            continue
        if isinstance(_one, list):
            # 标记来源（让下面的切段逻辑能分清不同文件）—— 直接拼起来即可
            _d += _one
    print('     扫了 %d 个 loop_log，共 %d 条' % (len(_FILES), len(_d)))
    # ⚠⚠ 三个坑（前两版都踩了 ⇒ 假红 ✗）：
    #   ① 必须扫**全部**实例（只看第一条 ⇒ 拿到别的图 ⇒ 假红）
    #   ② `marks` 字段有**两种形态**（真机实测：91 条 dict / 76 条 list ✗）
    #      ⇒ 不能无脑 `dict(...)` ⇒ 会 `ValueError` ✗
    #   ③ ⭐⭐ 同一张图里 `chain_consumed_inferred` 出现在**前**、
    #      `board.marks` 出现在**后**（真机：#267 剔 2,2 ／ #277 才报 marks）
    #      ⇒ 不能用"之前最后一次 marks"⇒ **必须按整张图收集 marks** ✓
    def _marks_of(e):
        m = e.get('marks')
        if isinstance(m, dict):
            return dict(m)
        return {}

    # 先按地图切段
    _segs = []
    _cur = None
    for _i, _e in enumerate(_d):
        if not isinstance(_e, dict):
            continue
        if isinstance(_e.get('mapname'), str):
            _cur = {'map': _e['mapname'], 'i0': _i, 'ev': [], 'marks': {}}
            _segs.append(_cur)
            continue
        if _cur is None:
            continue
        _m = _marks_of(_e)
        if _m:
            _cur['marks'].update(_m)          # ⭐ 整图并集（先后都算 ✓）
        if _e.get('solver') == 'chain_consumed_inferred':
            _cur['ev'].append((_i, _e.get('cells') or []))

    _all = []
    for _s in _segs:
        for _i, _cl in _s['ev']:
            _ov = [c for c in _cl if c in _s['marks']]
            _all.append((_i, _s['map'], _cl, dict(_s['marks']), _ov))
    print('     真机全盘 %d 条 `chain_consumed_inferred`' % len(_all))
    for _i, _mp, _cl, _mk, _ov in _all:
        print('        #%-5d %-8s 剔=%-10s 整图标记=%-20s ⇒ 重叠=%s'
              % (_i, str(_mp), str(_cl), str(list(_mk.keys())[:4]), _ov))
    _with = [x for x in _all if x[4]]
    print('     ⭐ 其中**剔掉了带标记格**的：%d 条' % len(_with))
    ck('⑨ ⭐⭐ 真机数据里确实**剔掉了带标记的格**（这就是那个 bug 的铁证 ✓）',
       bool(_with), '%d 条重叠' % len(_with))
except Exception as _e:     # noqa: BLE001
    ck('⑨ 真机复算', False, repr(_e)[:100])

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
