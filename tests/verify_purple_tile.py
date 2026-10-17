# -*- coding: utf-8 -*-
"""verify_purple_tile.py · 回归：**紫/橙探索格别漏**（用户 2026-10-05 报）

用户原话：「**为什么漏了一个紫探索的战斗**」
（`runs/acc1/r_160935_0.png`，第 5 张图：`event_tiles=['3,1']` 已判定为紫/橙探索格，
 计划里也有它，但点开面板后**被当普通面板关掉** ⇒ 那一格探索战斗没打 ✗）

真根因：**两条判据用了不同的 sid**
  · "发现紫/橙探索地块"那条（`entry['event_tiles']`）用 **top-N 候选的后缀** ⇒ 判对 ✓
  · 而点开面板后的探索分支只认**顶层 sid**；真机那格顶层是
    `S30001_104 废弃矿车`、**score 只有 0.192（垃圾）**、ratio **1.709**
    （= 雾里那团**紫光**，紫/橙格在雾里就是靠这团光被认出来的 ✓）
    ⇒ 后缀 104 ∉ {221,321,331} ⇒ `_is_purple=False` ⇒ **探索/派遣分支被整个跳过** ✗✗

修：把判据抽成纯函数 `explore_loop._is_purple_cell()`（可离线测 ✓）——
    ① 顶层后缀 ∈ `EXPLORE_SUFFIX` ✓ 或 ② **本轮 `ev_tiles` 里确有这一格** ✓

牙齿：旧实现（只认顶层后缀）在本门禁第 1、5 例上必红 ✓
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

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import explore_loop as EL
    print('=== 紫/橙探索格判据（用户报「漏了一个紫探索的战斗」）===')
    cases = [
        # (顶层 sid, ev_tiles, 点击坐标, 期望, 说明)
        ('S30001_104', ['3,1'], (72, 908), True,
         '真机那把：顶层是垃圾猜测(score 0.19) ⇒ 必须靠 ev_tiles 认出来'),
        ('S30001_221', [], (72, 908), True, '常规：顶层后缀就是 221'),
        ('S30001_321', [], (72, 908), True, '常规：321'),
        ('S30001_331', [], (72, 908), True, '常规：331'),
        ('', ['3,1'], (72, 908), True, '顶层读不到、ev_tiles 有它'),
        ('S30001_104', ['5,5'], (72, 908), False,
         'ev_tiles 里**没有**这一格 ⇒ 不许乱认（防把宝箱/石碑当探索格 ✗）'),
        ('S30001_013', [], (72, 908), False, '预言石碑 ⇒ 非紫格'),
        ('S30001_003', [], (72, 908), False, '宝箱 ⇒ 非紫格'),
    ]
    for sid, ev, tap, want, name in cases:
        got = EL._is_purple_cell(sid, ev, tap)
        ck('%-56s ⇒ %s' % (name, want), got is want, '实际 %s' % got)
    # 纯函数存在性（防有人把判据写回内联、门禁又变成测不到 ✗）
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    ck('判据是**可离线测的纯函数** `_is_purple_cell()`，且探索分支在调它',
       'def _is_purple_cell(' in src and '_is_purple = _is_purple_cell(' in src)
    print()
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：紫/橙探索格既能按顶层后缀认、也能按本轮 ev_tiles 认；'
          '不在 ev_tiles 里的格绝不乱认')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
