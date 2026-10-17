# -*- coding: utf-8 -*-
"""★ 回归：特殊方块勾选框的**顺序必须固定**（2026-10-10 用户报「位置一直在变」）

⛔ 病：`_order = list(TC.BLOCK_NAMES) + ...` —— `BLOCK_NAMES` 是 **set**
   ⇒ `list(set)` 顺序不保证；Python 字符串哈希**每进程随机**（PEP 456）
   ⇒ 实测连开 8 个进程 = **7~8 种不同顺序** ✗
   ⇒ 用户记不住位置 ⇒ 极易点错框（「金属宝箱怪」vs「机巧宝箱怪」只差两字）
   ⇒ 这是「**勾了宝箱怪却没买**」的合理来源之一 ✓

本回归用**跨进程**验证（同进程内 set 顺序是稳定的 ⇒ 在同进程里测**测不出来** ✗）
"""
import io
import os
import subprocess
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
import targets_cfg as TC


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


PY = sys.executable
BASE = ("import sys, io;"
        "sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8');"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)));"
        "import targets_cfg as TC;")


def cross(expr, n=6):
    seen = []
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    for _ in range(n):
        r = subprocess.run([PY, '-c', BASE + "print(%s)" % expr],
                           capture_output=True, timeout=90,
                           creationflags=0x08000000, env=env)
        seen.append((r.stdout or b'').decode('utf-8', 'replace').strip())
    return seen


print('=' * 92)
print('特殊方块勾选框顺序固定（2026-10-10）')
print('=' * 92)

print()
print('【1】结构级')
ck('① `targets_cfg` 有 `DISPLAY_ORDER`（显式有序元组 ✓）',
   hasattr(TC, 'DISPLAY_ORDER') and isinstance(TC.DISPLAY_ORDER, tuple),
   str(getattr(TC, 'DISPLAY_ORDER', None))[:70])
ck('② 它**覆盖**全部特殊方块（一个不漏 ✓）',
   set(TC.DISPLAY_ORDER) == set(TC.SPECIAL_NAMES),
   '漏 = %s' % sorted(set(TC.SPECIAL_NAMES) - set(getattr(TC, 'DISPLAY_ORDER', ()))))
ck('③ 无重复',
   len(TC.DISPLAY_ORDER) == len(set(TC.DISPLAY_ORDER)))
ck('④ GUI 用的是 `DISPLAY_ORDER`（不再 `list(set)` ✗）',
   'TC.DISPLAY_ORDER' in io.open('bot_gui.py', encoding='utf-8').read())
_src = io.open('bot_gui.py', encoding='utf-8', newline='').read()
_CODE = '\n'.join(ln for ln in _src.splitlines()
                  if not ln.lstrip().startswith('#'))
ck('⑤ ⚠ **代码里**没有 `list(TC.BLOCK_NAMES)`（注释里提到不算 ✓）',
   'list(TC.BLOCK_NAMES)' not in _CODE)

print()
print('【2】⭐ 跨进程实测（同进程测不出来 ⇒ 必须跨进程 ✓）')
_gui = cross("'|'.join(list(TC.DISPLAY_ORDER) + [x for x in sorted(TC.SPECIAL_NAMES)"
             " if x not in TC.DISPLAY_ORDER])")
for i, s in enumerate(_gui, 1):
    print('     第%d次：%s' % (i, s))
ck('⑥ ⭐ GUI 的 `_order` **跨进程完全一致**（6 次 = 1 种 ✓）',
   len(set(_gui)) == 1, '%d 种' % len(set(_gui)))

print()
print('【3】⚠ 对照项：旧口径（`list(set)`）**必须仍然不稳定**')
_old = cross("'|'.join(list(TC.BLOCK_NAMES))")
print('     旧口径 6 次 = %d 种顺序' % len(set(_old)))
ck('⑦ **对照项**：旧口径确实不稳定 ⇒ 证明本回归**测得出**这个问题'
   '（不是恒绿 ✓）', len(set(_old)) > 1, '%d 种' % len(set(_old)))

print()
print('【4】顺序口径（拉黑类在前 ✓）')
_first5 = list(TC.DISPLAY_ORDER[:5])
ck('⑧ 前 5 个都是**拉黑类**（花资源的，用户最常改 ✓）',
   set(_first5) == set(TC.BLOCK_NAMES), str(_first5))
ck('⑨ 后 3 个都是**可点类**（免费的 ✓）',
   set(TC.DISPLAY_ORDER[5:]) == set(TC.PICK_IF_BLOCKING), str(list(TC.DISPLAY_ORDER[5:])))

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
