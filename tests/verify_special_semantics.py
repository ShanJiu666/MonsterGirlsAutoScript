# -*- coding: utf-8 -*-
"""★ 特殊方块**两类语义**回归（2026-10-09 用户口径）

用户原话（三条）：
  ① 「**把窗口的其他特殊方块解锁吧，现在勾选是设定为会当成目标去拿，
      不勾选就不专门去拿，但是如果挡了最优的路，也会去点
      （不同于之前的不勾选拉黑了）**」
  ② （我问"要不要也用在商人/宝库上"）「**只对那 6 个生效**」
  ③ 「**俩宝箱怪和祭坛也和商人宝库一样吧**」
  ④ 「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个**低于50w金币和10幸运草**就是」
  ⑤ 「**特殊方块的描述改成个感叹号，点了可以看描述**」

⇒ 本回归钉住这五条 ✓
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

os.chdir(ROOT)
sys.path.insert(0, ROOT)
import targets_cfg as TC       # noqa: E402
import spots as SP             # noqa: E402
import explore_loop as EL      # noqa: E402


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 76)
print('特殊方块两类语义回归（2026-10-09）')
print('=' * 76)
print()

# ── ① 分类正确 ───────────────────────────────────────────
print('【1】两类划分（口径 ①③）')
ck('① 拉黑类 = 商人/宝库 + **两个宝箱怪 + 传承祭坛**（口径③ ✓）',
   set(TC.BLOCK_NAMES) == {'旅行商人', '黄金宝库', '金属宝箱怪',
                           '机巧宝箱怪', '传承祭坛'},
   str(sorted(TC.BLOCK_NAMES)))
ck('② 可点类 = 勇者之墓/限时礼包/预言石碑（3 个）',
   set(TC.PICK_IF_BLOCKING) == {'勇者之墓', '限时礼包', '预言石碑'},
   str(sorted(TC.PICK_IF_BLOCKING)))
ck('③ 两类**不重不漏**（并集 = 8 个特殊方块）',
   set(TC.BLOCK_NAMES) | set(TC.PICK_IF_BLOCKING) == set(TC.SPECIAL_NAMES)
   and not (set(TC.BLOCK_NAMES) & set(TC.PICK_IF_BLOCKING)))
# ⭐ 划分依据：**要花资源的 = 拉黑类**（自洽性守门）
FREE = {'勇者之墓', '限时礼包', '预言石碑'}       # 实测零成本 / 免费档 / 只做选择
ck('④ 可点类**恰好就是**那三个免费的（划分依据自洽 ✓）',
   set(TC.PICK_IF_BLOCKING) == FREE)

# ── ② 不勾时的语义 ───────────────────────────────────────
print()
print('【2】不勾时的行为（口径 ①③）')
_cfg = {'types': {}}
for _n in sorted(TC.BLOCK_NAMES):
    ck('⑤ 不勾「%s」⇒ **拉黑**（is_blocked=True）' % _n,
       TC.is_blocked(_n, _cfg) is True)
for _n in sorted(TC.PICK_IF_BLOCKING):
    ck('⑥ 不勾「%s」⇒ **不是拉黑**（可点但不拿）' % _n,
       TC.is_blocked(_n, _cfg) is False)
ck('⑦ 不勾时**两类都不是目标**（is_target=False）',
   all(not TC.is_target(n, 'S00003_011', cfg=_cfg) for n in TC.SPECIAL_NAMES))
# ── ③ 勾上就是目标 ───────────────────────────────────────
print()
print('【3】勾上 ⇒ 主动去拿（口径 ①）')
for _n, _sid in (('金属宝箱怪', 'S00003_009'), ('传承祭坛', 'S00003_012'),
                 ('勇者之墓', 'S00003_011'), ('预言石碑', 'S00003_013'),
                 ('旅行商人', 'S00003_008')):
    _c2 = {'types': {_n: True}}
    ck('⑧ 勾上「%s」⇒ is_target=True' % _n,
       TC.is_target(_n, _sid, cfg=_c2) is True)

# ── ④ 自动拉黑（口径 ④）───────────────────────────────────
print()
print('【4】自动拉黑两条（口径 ④）')
ck('⑨ `GOLD_MIN_BUY == 500000`（金币 < 50w ⇒ 商人/宝库拉黑）',
   int(EL.GOLD_MIN_BUY) == 500000, '实际 %s' % EL.GOLD_MIN_BUY)
ck('⑩ `MIMIC_CLOVER_MIN == 10`（幸运草 < 10 ⇒ 宝箱怪拉黑）',
   int(EL.MIMIC_CLOVER_MIN) == 10, '实际 %s' % EL.MIMIC_CLOVER_MIN)
ck('⑪ ⭐ 两条**现在同为 10**（用户 2026-10-09：「幸运草阈值都改成10」✓）',
   int(EL.CLOVER_MIN_REROLL) == int(EL.MIMIC_CLOVER_MIN) == 10,
   '摇色子=%s 宝箱怪=%s' % (EL.CLOVER_MIN_REROLL, EL.MIMIC_CLOVER_MIN))
ck('⑪b ⚠ 但仍是**两个独立常量**（语义不同：摇色子 vs 买装备 ⇒ 明天可只改一个 ✓）',
   'CLOVER_MIN_REROLL' in io.open('explore_loop.py', encoding='utf-8').read()
   and 'MIMIC_CLOVER_MIN' in io.open('explore_loop.py', encoding='utf-8').read())
ck('⑫ 金币闸门管**只有**商人/宝库（不含宝箱怪 ✓ 它们花草不花金币）',
   tuple(SP.BUY_OUT_NAMES) == ('旅行商人', '黄金宝库')
   and not any(n in SP.BUY_OUT_NAMES for n in SP.MIMIC_NAMES))
ck('⑬ 宝箱怪名单独立（`MIMIC_NAMES`，SP=2 那两个）',
   tuple(SP.MIMIC_NAMES) == ('金属宝箱怪', '机巧宝箱怪'))
# 判据函数
_ck = EL.clover_enough_for_mimic
ck('⑭ 草 9 ⇒ 宝箱怪**不够**（< 10）', _ck({'clover_locked': 9}) is False)
ck('⑮ 草 10 ⇒ 宝箱怪**够**（边界 ✓）', _ck({'clover_locked': 10}) is True)
ck('⑯ 草读不到(None) ⇒ **不拉黑**（fail-open ✓）',
   _ck({'clover_locked': None}) is True and _ck({}) is True)
# ⚠ 互不干扰（关键：两条闸门不能串味 ✗）
ck('⑰ 金币少 + 草多 ⇒ **商人拉黑、宝箱怪不拉黑**（两闸门独立 ✓）',
   EL.gold_enough_locked({'gold_locked': 400000}) is False
   and _ck({'clover_locked': 20}) is True)
ck('⑱ 金币多 + 草少 ⇒ **宝箱怪拉黑、商人不拉黑**（同上 ✓）',
   EL.gold_enough_locked({'gold_locked': 600000}) is True
   and _ck({'clover_locked': 5}) is False)

# ── ⑤ 说明文字（口径 ⑤）───────────────────────────────────
print()
print('【5】❗说明按钮（口径 ⑤）')
ck('⑲ 8 个特殊方块**每个都有** `describe()` 说明',
   all(TC.describe(n).strip() for n in TC.SPECIAL_NAMES))
ck('⑳ 未知名字也有**兜底**说明（不返回空）',
   bool(TC.describe('某个没配过的名字').strip()))
_src = io.open('bot_gui.py', encoding='utf-8').read()
ck('㉑ GUI 里有「❗」按钮 + `_show_special_help`',
   "'❗'" in _src and '_show_special_help' in _src)
ck('㉒ GUI 里 8 个勾选框**全部可勾**（不再 `disabled`）',
   "state=('normal' if _can else 'disabled')" not in _src
   and "'（不勾 = 拉黑；其余特殊方块暂时锁定 ✓）'" not in _src)

print()
print('=' * 76)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for b in BAD:
    print('   ✗ ' + b)
raise SystemExit(1 if BAD else 0)
