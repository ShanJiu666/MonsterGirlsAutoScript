# -*- coding: utf-8 -*-
"""★ 回归：**「停脚本·保现场锁」机制已彻底删除**（2026-10-12 用户要求）

用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」

⛔ 原来是什么：发现红装 / 抽到要停的预言 ⇒ 写一个锁文件
   （`runs/red_equip_<port>.lock.json`）⇒ **下次启动被 `red_locked()` 拦住**，
   要人去窗口点「红装已处理·解锁」才放行 ✗
⛔ 为什么删：用户要的只是"**遇到就停**"这个动作；锁是**多余的一层**，
   而且**真卡过人**三次：
     · `kind=shrine` 被报成"发现了红装"（用户：「不勾选还是自动停了」✗）
     · `kind=foretell` 显示"未知类型"、无解锁指引（用户：「怎么解除锁定」✗）
     · 最终用户明确：「**我不需要这个锁定**」✓

⭐ 本回归**同时反向守住"停脚本"这个动作**（别把该留的也删了 ✗）：
   红装标记 ⇒ `return 'red_equip'` ⇒ `run_maps` 里 `break` ✓
   抽到要停的预言 ⇒ `return 'foretell_stop'` ⇒ `run_maps` 里 `break` ✓
"""
import ast
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
OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def _code(f):
    """只取**代码行**（剥掉纯注释 —— 留档注释里必然引用旧名字 ✗ 会假红）"""
    return [(i, l) for i, l in enumerate(
        io.open(f, encoding='utf-8').read().splitlines(), 1)
        if not l.lstrip().startswith('#')]


_EL = io.open('explore_loop.py', encoding='utf-8').read()
_GUI = io.open('bot_gui.py', encoding='utf-8').read()
_ELc = '\n'.join(l for l in _EL.splitlines() if not l.lstrip().startswith('#'))
_GUIc = '\n'.join(l for l in _GUI.splitlines() if not l.lstrip().startswith('#'))

print('=' * 92)
print('「停脚本·保现场锁」已彻底删除（2026-10-12）')
print('=' * 92)

print()
print('【1】⬛ 撤回守门：**代码里**不许再有锁的实现/调用')
GONE_EL = ('def red_lock_path', 'def red_locked', '_KIND_TXT',
           'red_lock_path(', 'red_locked(')
GONE_GUI = ('_KIND_TXT', 'def red_lock_file', 'def _read_red_lock',
            'def show_red_lock', 'def _refresh_lock_card', 'def unlock_red',
            '_refresh_lock_card(', 'show_red_lock(')
for _nm in GONE_EL:
    _h = [(i, l.strip()[:80]) for i, l in _code('explore_loop.py') if _nm in l]
    ck('`explore_loop.py` 里没有 %r' % _nm, not _h, str(_h[:2]))
for _nm in GONE_GUI:
    _h = [(i, l.strip()[:80]) for i, l in _code('bot_gui.py') if _nm in l]
    ck('`bot_gui.py` 里没有 %r' % _nm, not _h, str(_h[:2]))

print()
print('【2】⬛ 也不许再**写锁文件**（`red_equip_*.lock.json`）')
ck('① 脚本里没有 `red_equip_%d.lock.json` 的写入',
   'red_equip_%d.lock.json' not in _ELc)
ck('② GUI 里没有 `red_equip_%d.lock.json`',
   'red_equip_%d.lock.json' not in _GUIc)
# 用 AST 找"写 lock.json"的 open(..., 'w')
_ast_el = ast.parse(_EL)
_w = []
for _n in ast.walk(_ast_el):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name) \
            and _n.func.id == 'open':
        _src = ast.get_source_segment(_EL, _n) or ''
        if 'lock' in _src.lower() and "'w'" in _src:
            _w.append((_n.lineno, _src[:70]))
print('     脚本里"写锁文件"的 open(...,\'w\') = %s' % (_w or '无 ✓'))
ck('③ ⭐ 脚本里**没有**写锁文件的 open 调用', not _w, str(_w[:2]))

print()
print('【3】⚠⚠ 反向：**停脚本这个动作必须还在**（别删过头 ✗）')
ck('④ 红装 ⇒ `return \'red_equip\'`（停脚本主判据 ✓）',
   "return 'red_equip'" in _ELc)
ck('⑤ 预言 ⇒ `return \'foretell_stop\'` ✓',
   "return 'foretell_stop'" in _ELc)
ck('⑥ `run_maps` 里 `red_equip` 分支 **break**（停局 ✓）',
   "if why == 'red_equip':" in _ELc)
ck('⑦ `run_maps` 里 `foretell_stop` 分支 **break**（停局 ✓）',
   "if why == 'foretell_stop':" in _ELc)
ck('⑧ 设备锁（防"同机开两个脚本"）**保留** ✓',
   'def device_lock_path' in _ELc and 'def acquire_device_lock' in _ELc)

print()
print('【4】⭐ 行为级：GUI 能建窗，且**锁相关的属性/方法/控件都没了**')
try:
    import tkinter as tk
    import bot_gui
    _root = tk.Tk()
    _app = bot_gui.App(_root)
    _root.update()
    for _nm in ('red_lock_file', '_read_red_lock', 'show_red_lock',
                '_refresh_lock_card', 'unlock_red', '_locked'):
        ck('⑨ `%s` 已删' % _nm, not hasattr(_app, _nm))
    ck('⑩ `_KIND_TXT` 类属性已删', not hasattr(bot_gui.App, '_KIND_TXT'))

    def _all_text(w):
        out = []
        try:
            out.append(str(w.cget('text')))
        except Exception:       # noqa: BLE001
            pass
        for c in w.winfo_children():
            out += _all_text(c)
        return out

    _t = _all_text(_root)
    _bad = [x for x in _t if '解锁' in x or '锁' in x and '锁定' in x]
    print('     窗口里含「解锁/锁定」的控件 = %s' % (_bad or '无 ✓'))
    ck('⑪ ⭐ 窗口里**没有**解锁按钮/锁卡片', not _bad, str(_bad[:3]))
    _root.destroy()
except Exception as _e:     # noqa: BLE001
    ck('⑨ GUI 行为级', False, repr(_e)[:140])

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
