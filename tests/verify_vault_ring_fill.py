# -*- coding: utf-8 -*-
"""★ 回归：宝库某一圈**检测漏格**时要按本圈理论格补齐（2026-10-14 用户报）

用户原话：「**这张图的宝库第二层，没选到4个四叶草那个奖励**」

⛔ 病（真机铁证 `runs/acc1/loop/loop_log.json` #198~#211）：
    `#198 tiles_detected n=7`（第 2 层）
    `#199 ring_filter all=7 **ring=6**` ⇐ **本圈应有 8 格、少了 2 格** ✗
    缺的正是 `(263,689)` 与 `(359,785)`（= `vault_ring(2)` 里那两格）
    ⇒ 那两格**永远进不了候选** ⇒ 就算其中一格是「4 四叶草」（`tier 3.0`）
      **也轮不到它** ✗✗
    实测该层最终 `#211 claim 天赋果实×0`（`qty=null` ⇒ `tier 0.0` —— 最低档）
    ⇒ 用户看到的"没选到 4 四叶草" ✓

⛔ 根因：`vault_tiles` 靠**彩色底**检测（高饱和块），而有些奖励格底色**不够饱和**
   ⇒ 检测漏格。这是**召回**问题（不是"点错格"）⇒ 补格安全 ✓

⭐ 修法：**只补不删** —— 本圈理论格 `vault_ring(level)` 里凡**没被任何检出格覆盖**的
   （按 5×5 行列判，容差半格 ⇒ 免疫面板整体位移 ✓）补进来当**额外候选** ✓
   ⚠ 检出格坐标更准，**优先保留**；不删任何检出格 ✓
   ⚠ 只对第 1/2 层补（第 3 层就 1 格，`center_only` 已处理 ✓）
"""
import io
import os
import re
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
import buypanels as BP


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


_S = io.open('buypanels.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _S.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('宝库某圈检测漏格 ⇒ 按理论格补齐（2026-10-14）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `ring_fill` 补齐逻辑', 'ring_fill' in _CODE)
ck('② ⭐ **只补不删**（`cells = cells + _real` ✓）',
   'cells + _real' in _CODE)
ck('③ ⚠ 只对第 1/2 层补（第 3 层就 1 格 ✓）',
   'level in (1, 2)' in _CODE)
ck('④ 去重按 **5×5 行列**（免疫面板整体位移 ✓）',
   '_vault_rc(_t[0], _t[1]) not in _have' in _CODE)

print()
print('【2】⭐⭐⭐ 行为级：**用真机那 7 格复算**（核心）')
# 真机 `#198 tiles_detected` 的原始数据（**非手写**，逐字抄自 loop_log ✓）
DET_REAL = [(456, 592), (264, 593), (360, 593), (360, 689), (458, 689),
            (456, 785), (261, 788)]
LEVEL = 2


def _fill(det, level):
    """复刻生产逻辑：ring_filter 后按理论格补齐 ✓"""
    ring = [p for p in det if BP.tile_ring(p[0], p[1]) == level]
    have = set()
    for _p in ring:
        have.add(BP._vault_rc(_p[0], _p[1]))
    add = [t for t in BP.vault_ring(level) if BP._vault_rc(t[0], t[1]) not in have]
    real = [t for t in add
            if not any(abs(t[0] - p[0]) <= 48 and abs(t[1] - p[1]) <= 48 for p in ring)]
    return ring, real, ring + real


_ring, _add, _all = _fill(DET_REAL, LEVEL)
print('     真机检出 7 格 ⇒ ring_filter 后 = %d 格' % len(_ring))
print('     理论上缺的 = %s' % _add)
print('     补齐后候选 = %d 格' % len(_all))
ck('⑤ ⭐⭐ 检出 7 格时 `ring_filter` = **6 格**（复现真机 ✓）', len(_ring) == 6,
   '%d' % len(_ring))
ck('⑥ ⭐⭐⭐ 补齐后 = **8 格**（本圈理论格数 ✓）', len(_all) == 8, '%d' % len(_all))
ck('⑦ ⭐⭐ 补的正是缺的那 2 格 `(263,689)` / `(359,785)` ✓',
   sorted(_add) == [(263, 689), (359, 785)], str(sorted(_add)))
ck('⑧ ⚠ **一个检出格都没丢**（只补不删 ✓）',
   all(p in _all for p in _ring), str([p for p in _ring if p not in _all]))
ck('⑨ ⚠ 补的格**不在检出里**（没重复 ✓）',
   not any(t in _ring for t in _add))

print()
print('【3】⭐ 为什么"补上"能救回 4 四叶草（档位算得对 ✓）')
_t4 = BP.vault_tier_of('四叶草', 4)
_t0 = BP.vault_tier_of('天赋果实', None)
print('     `4 四叶草` ⇒ tier=%s ｜ 当时唯一候选 `天赋果实 qty=null` ⇒ tier=%s'
      % (_t4, _t0))
ck('⑩ ⭐ `4 四叶草` 档位 = **3.0**（高于那个 `tier 0.0` ✓）', _t4[0] == 3.0,
   str(_t4))
ck('⑪ ⚠ 数量读不到 ⇒ `tier 0.0`（**保守、不冒充高档** ✓）', _t0[0] == 0.0,
   str(_t0))
ck('⑫ ⭐⭐ 若那格真是 4 四叶草 ⇒ **补齐后就能选到它**（档位更高 ✓）',
   _t4 > _t0)

print()
print('【4】⚠⚠ 反向：**不许把别的圈补进来**（补过头会点错格 ✗）')
_ring1, _add1, _all1 = _fill(DET_REAL, 1)
print('     同样 7 格、按第 1 层算 ⇒ 补齐后 = %d 格' % len(_all1))
ck('⑬ ⚠ 补的格全都 `tile_ring == level`（不越圈 ✓）',
   all(BP.tile_ring(t[0], t[1]) == LEVEL for t in _add), str(_add))
ck('⑭ ⚠ 第 1 层补齐后也**只含第 1 圈的格** ✓',
   all(BP.tile_ring(t[0], t[1]) == 1 for t in _all1) or not _all1,
   '%d 格' % len(_all1))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
