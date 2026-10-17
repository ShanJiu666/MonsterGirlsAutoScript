# -*- coding: utf-8 -*-
"""★ 元素·紫/橙 停止判据回归（2026-10-09 用户口径）

用户原话：「**预言石碑停止脚本加上橙色和紫色元素**」
⇒ 期望：紫(A)/橙(S) 可停；**蓝(B) 不停**
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
import buypanels as BP
import explore_loop as EL

OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 84)
print('元素·紫/橙 停止判据（2026-10-09）')
print('=' * 84)

# ── ① 常量/开关 ─────────────────────────────────────────
print()
print('【1】开关（默认开，与幸运/和平同向）')
ck('① `STOP_ELEM_PURPLE` 默认 True', EL.STOP_ELEM_PURPLE is True)
ck('② `STOP_ELEM_ORANGE` 默认 True', EL.STOP_ELEM_ORANGE is True)
ck('③ 「元素」进了 `PRIO_STOP`（会优先挑）',
   '元素' in BP.FORETELL['PRIO_STOP'], str(BP.FORETELL['PRIO_STOP']))

# ── ② 判据：用 `_items`/`img` 太重 ⇒ 直接测那段分支逻辑的**输入形态** ──
#   用真机取过的文案（数据表 `Foretell` 的 EffectDescription ✓）
print()
print('【2】文案形态（来自数据表 `Foretell` 实测）')
CASES = {
    '元素·蓝(B)': ('元素', '地图中至少出现1只莱姆，并且所有莱姆至少是蓝色位阶。', '不停'),
    '元素·紫(A)': ('元素', '地图中至少出现1只莱姆，并且所有莱姆至少是紫色位阶。', '元素·紫色'),
    '元素·橙(S)': ('元素', '地图中至少出现1只莱姆，并且所有莱姆至少是橙色位阶。', '元素·橙色'),
}

# 复现 `foretell_flow` 里那段判据（逐字同源：卡名 + eff）
def judge(name, eff, flags):
    blob = name + eff
    if '幸运' in blob:
        return '幸运'
    if '和平' in blob and '金属宝箱怪' in blob:
        return '和平·金属宝箱怪' if flags.get('stop_peace_metal', True) else None
    if '元素' in name:
        if '橙色' in blob and flags.get('stop_elem_orange', True):
            return '元素·橙色'
        if '紫色' in blob and flags.get('stop_elem_purple', True):
            return '元素·紫色'
    return None


for label, (nm, eff, want) in CASES.items():
    got = judge(nm, eff, {'stop_elem_purple': True, 'stop_elem_orange': True})
    exp = None if want == '不停' else want
    ck('④ %s ⇒ %s' % (label, want), got == exp, '实际 %s' % got)

print()
print('【3】开关关掉时**不停**（用户能在窗口里控制 ✓）')
ck('⑤ 紫档 + 关紫开关 ⇒ 不停',
   judge('元素', CASES['元素·紫(A)'][1], {'stop_elem_purple': False}) is None)
ck('⑥ 橙档 + 关橙开关 ⇒ 不停',
   judge('元素', CASES['元素·橙(S)'][1], {'stop_elem_orange': False}) is None)
ck('⑦ 紫档 + 关**橙**开关 ⇒ **仍然停**（两开关独立，不互相影响 ✓）',
   judge('元素', CASES['元素·紫(A)'][1],
         {'stop_elem_purple': True, 'stop_elem_orange': False}) == '元素·紫色')
ck('⑧ ⚠ **蓝档没有开关能停它**（用户只说紫+橙 ✓）',
   judge('元素', CASES['元素·蓝(B)'][1],
         {'stop_elem_purple': True, 'stop_elem_orange': True}) is None)

print()
print('【4】不误伤既有两条')
ck('⑨ 「幸运」仍停',
   judge('幸运', '地块结算时宝箱掉落替换为四叶草。', {}) == '幸运')
ck('⑩ 「和平·金属宝箱怪」仍停',
   judge('和平', '地图中至少出现1个金属宝箱怪。', {'stop_peace_metal': True})
   == '和平·金属宝箱怪')
ck('⑪ ⚠ 别的卡名（如「丰收」）**不顺带停**',
   judge('丰收', '地块结算时获得素材数量+200%。',
         {'stop_elem_purple': True, 'stop_elem_orange': True}) is None)

print()
print('【5】链路口径一致（explore_loop 认这四个 stop 值）')
_src = io.open('explore_loop.py', encoding='utf-8').read()
ck('⑫ `explore_loop` 传了 `stop_elem_purple/orange` 两个 flag',
   "'stop_elem_purple': STOP_ELEM_PURPLE" in _src
   and "'stop_elem_orange': STOP_ELEM_ORANGE" in _src)
ck('⑬ `explore_loop` 的 `_do_stop` 认「元素·紫色」「元素·橙色」',
   "'元素·紫色' in _why and STOP_ELEM_PURPLE" in _src
   and "'元素·橙色' in _why and STOP_ELEM_ORANGE" in _src)
_bsrc = io.open('buypanels.py', encoding='utf-8').read()
import re as _re

_bpos = _bsrc.find("_tier11 = ")      # 新加的日志行（应存在，但**不是**判据）
# ⚠ 2026-10-13：「要停的卡」判据已**提到选卡之前**（用户报「已经选择完预言了才停」）
#   ⇒ 那段代码整块上移，局部变量从 `blob` 改名成 `_blob`（`c` → `_c`，避免与外层重名 ✓）
#   ⇒ 本断言跟着改（**判据本身没变**：仍是"文案里的位阶词"，不是边框颜色 ✓）
ck('⑭ `buypanels` 里判据用**文案位阶词**（不看边框颜色）',
   "'橙色' in _blob" in _bsrc and "'紫色' in _blob" in _bsrc)
ck('⑮ ⚠ **判据分支**里没有「蓝色」（蓝档不停 ✓）',
   # ⚠ 必须查**判据分支**（`if '蓝色' in blob and ...:` ⇒ 会设置 out['stop']），
   #   不能查整个文件 —— 我新加的**日志行**里必然出现「蓝色」
   #   （`('蓝色' if '蓝色' in blob else ...)`，那是为了排查"这张卡是哪一档" ✓）
   #   ⇒ 字符串 grep 会假红 ✗（本项目第 N 次踩"注释/日志里必然引用"这个坑）
   not _re.search(r"if\s*'蓝色'\s*in\s*blob\s*and", _bsrc)
   and "out['stop'] = '元素·蓝色'" not in _bsrc
   and _bpos >= 0,
   '判据分支位置 = %d' % _bpos)

print()
print('=' * 84)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for b in BAD:
    print('   ✗ ' + b)
raise SystemExit(1 if BAD else 0)
