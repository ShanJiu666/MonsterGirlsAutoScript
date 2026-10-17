# -*- coding: utf-8 -*-
"""★ 回归：**传承祭坛**必须进 `act_on`（否则面板被盲点 X 关掉 ⇒ 采不到 ✗）

用户口径（2026-10-11）：「**我开了**」
  = 在窗口里勾上了「传承祭坛」/「机巧宝箱怪」，要采这两个最后的地块面板
⛔ 病：`传承祭坛` 在 `L['special']` 里、**但不在 `L['act_on']`**
  ⇒ `t not in act_on` ⇒ 走"无视"支 `close_x_panels` + 盲点 X **关掉面板** ✗✗
  ⇒ 而且它**从来没有 handler** ⇒ 采不到坐标 ✓
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


SRC = io.open('explore_loop.py', encoding='utf-8').read()
_CODE = '\n'.join(ln for ln in SRC.splitlines() if not ln.lstrip().startswith('#'))

print('=' * 94)
print('传承祭坛接线（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
ck('① `传承祭坛` 在 `L[\'special\']` 里', '传承祭坛' in EL.L['special'])
ck('② ⭐ `传承祭坛` **在 `L[\'act_on\']` 里**（否则面板被盲点 X 关掉 ✗）',
   '传承祭坛' in EL.L['act_on'], str(EL.L['act_on']))
ck('③ `popups()` 里有 `elif \'传承祭坛\' in t:` 分支',
   "elif '传承祭坛' in t:" in _CODE)
ck('④ 该分支留了取证帧（`shrine_panel_r%02d` ✓）',
   "shrine_panel_r%02d" in _CODE and "'shrine': 'panel_seen'" in _CODE)
# ⛔⛔ 2026-10-11 **本组按新行为改写**（[临时]采集停止已按用户要求删除 ✓）
#   用户原话：「**把窗口那个临时用的采集停止去掉吧**」
#   ⇒ 原来那 4 条断言的全是**已删掉的停止机制** ⇒ 现在断言"**它不存在**"＋
#     "**直接走 shrine_flow**"（这才是面板采到之后的正确行为 ✓）
ck('⑤ ⭐ `STOP_SHRINE`（[临时]停止开关）**已删除**',
   not hasattr(EL, 'STOP_SHRINE'))
ck('⑥ ⭐ `shrine_stop` 这个返回值**没有任何产生者**（停止路径已删 ✓）',
   "return 'shrine_stop'" not in _CODE)
ck('⑦ ⭐ 传承祭坛**直接走 `shrine_flow`**（不再停脚本 ✓）',
   'buypanels.shrine_flow(' in _CODE)
ck('⑧ ⭐ `shrine_flow` 调用在 `elif \'传承祭坛\' in t:` 分支**之内**',
   _CODE.find("elif '传承祭坛' in t:") < _CODE.find('buypanels.shrine_flow('))

print()
print('【2】⭐ 关键：`act_on` 里**每个有 handler 的名字**都要在里面')
#   交叉表：special 里哪些名字在 act_on
_missing = [n for n in ('传承祭坛', '机巧宝箱怪', '金属宝箱怪', '勇者之墓',
                        '限时礼包', '预言石碑', '黄金宝库', '旅行商人')
            if n not in EL.L['act_on']]
ck('⑨ 8 个"已处理"的名字**全在** `act_on`（无遗漏 ✓）',
   not _missing, '缺 = %s' % _missing)
ck('⑩ ⚠ 反向：`献祭宝箱怪` **不在** `act_on`（`MaxNum=0` 游戏不生成 ⇒ 无需 handler ✓）',
   '献祭宝箱怪' not in EL.L['act_on'])

print()
print('【3】⚠ `act_on` 里不许有"没有实现"的名字（会静默变成 handled ✗）')
#   有没有 handler：看 popups() 里有没有对应 elif
_impl = {
    '旅行商人': True,   # else 分支
    '黄金宝库': "if '黄金宝库' in t:" in _CODE,
    '勇者之墓': "elif '勇者之墓' in t:" in _CODE,
    '限时礼包': "elif '限时礼包' in t:" in _CODE,
    '预言石碑': "elif '预言石碑' in t:" in _CODE,
    '金属宝箱怪': "elif '宝箱怪' in t:" in _CODE,
    '机巧宝箱怪': "elif '宝箱怪' in t:" in _CODE,
    '传承祭坛': "elif '传承祭坛' in t:" in _CODE,
}
_bad = [k for k, v in _impl.items() if not v]
print('     逐个核对：%s' % _impl)
ck('⑪ `act_on` 里每个名字都有对应分支（否则会静默 handled ✗）',
   not _bad, '缺分支 = %s' % _bad)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
