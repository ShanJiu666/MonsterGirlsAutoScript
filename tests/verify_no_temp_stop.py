# -*- coding: utf-8 -*-
"""★ 回归：「[临时]采集停止」已彻底删除（2026-10-11 用户要求）

用户原话：「**把窗口那个临时用的采集停止去掉吧**」

⛔ 它原来是什么：2026-10-08 为采"最后两个特殊地块"的面板而加的临时工具
   ⇒ 勾选 = 图上认出 `机巧宝箱怪` / `传承祭坛` 就**停脚本、保现场**
⛔ 为什么现在删：两个面板**都已采到、流程都已写好**（`mimic_flow`/`shrine_flow`）
   ⇒ 留着只会**误停脚本** ✗

本回归钉住「**删干净**」这件事（不留死代码/不留残控件 ✓），
并**反向守住不该删的**（红装锁、预言石碑四个开关等 ✓）。
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
OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def code_lines(f):
    """只取**代码行**（剥掉纯注释行 —— 留档注释里必然引用旧名字 ✗ 会假红）"""
    return [(i, l) for i, l in enumerate(
        io.open(f, encoding='utf-8').read().splitlines(), 1)
        if not l.lstrip().startswith('#')]


EL = code_lines('explore_loop.py')
GUI = code_lines('bot_gui.py')
_EL_S = io.open('explore_loop.py', encoding='utf-8').read()
_GUI_S = io.open('bot_gui.py', encoding='utf-8').read()

print('=' * 92)
print('「[临时]采集停止」已彻底删除（2026-10-11）')
print('=' * 92)

print()
print('【1】⬛ 撤回守门：**代码里**不许再有这些名字')
GONE = ('STOP_MIMIC2', 'STOP_SHRINE', 'COLLECT_STOP_NAMES',
        'stop_mimic2_var', 'stop_shrine_var',
        '_load_collect_stop_prefs', 'toggle_stop_mimic2', 'toggle_stop_shrine',
        '_save_collect_stop_pref',
        'MAPBOT_STOP_MIMIC2', 'MAPBOT_STOP_SHRINE')
for _f, _L in (('explore_loop.py', EL), ('bot_gui.py', GUI)):
    for _nm in GONE:
        _h = [(i, l.strip()[:80]) for i, l in _L if _nm in l]
        ck('%s 里没有 %s' % (_f, _nm), not _h, str(_h[:2]))

print()
print('【2】⬛ 两个 `why` 也不许再有**产生者**（返回值本身可以留档在注释里）')
for _w in ('collect_stop', 'shrine_stop'):
    _h = [(i, l.strip()[:80]) for i, l in EL
          if ("return '%s'" % _w) in l or ('"%s"' % _w) in l]
    ck('`%s` 没有产生者' % _w, not _h, str(_h[:2]))

print()
print('【3】⚠ 反向：**不该删的**必须还在（否则我删过头了 ✗）')
ck('① ⭐ 红装"停脚本"动作**还在**（`return \'red_equip\'`）',
   "return 'red_equip'" in _EL_S)
ck('② 红装早退还在（`return \'red_equip\'`）', "return 'red_equip'" in _EL_S)
ck('③ 预言石碑早退还在（`foretell_stop`）', "return 'foretell_stop'" in _EL_S)
ck('④ 用户点停止还在（`why == \'stopped\'`）', "why == 'stopped'" in _EL_S)
ck('⑤ `shrine_flow` 调用还在（走正常流程 ✓）',
   'buypanels.shrine_flow(' in _EL_S)
ck('⑥ `mimic_flow` 调用还在', 'buypanels.mimic_flow(' in _EL_S)

print()
print('【4】⭐ 行为级：GUI 能建窗、且控件/属性都对')
try:
    import tkinter as tk
    import bot_gui
    _root = tk.Tk()
    _app = bot_gui.App(_root)
    _root.update()
    for _nm in ('stop_mimic2_var', 'stop_shrine_var'):
        ck('⑦ `%s` 属性已删' % _nm, not hasattr(_app, _nm))
    for _nm in ('_load_collect_stop_prefs', 'toggle_stop_mimic2',
                'toggle_stop_shrine', '_save_collect_stop_pref'):
        ck('⑦ `%s` 方法已删' % _nm, not hasattr(_app, _nm))
    # 反向：长期那几个必须在
    for _nm in ('stop_lucky_var', 'stop_peace_var', 'stop_elem_purple_var',
                'stop_elem_orange_var'):
        ck('⑧ `%s` **还在**（没被连带删 ✗）' % _nm, hasattr(_app, _nm))

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
    ck('⑨ 窗口里没有「临时…停止」那排',
       not [x for x in _t if '临时' in x and '停止' in x])
    ck('⑩ 「机巧宝箱怪…停止」字样已消失',
       not any('机巧宝箱怪' in x and '停止' in x for x in _t))
    ck('⑪ 「传承祭坛…停止」字样已消失',
       not any('传承祭坛' in x and '停止' in x for x in _t))
    # ⭐ 日志框高度（10-08 踩过"权重挂错排 ⇒ 塌成 0"的坑 ✗）
    _root.update_idletasks()
    _h = _app.txt.winfo_height()
    print('     日志框高度 = %dpx' % _h)
    ck('⑫ ⭐ 日志框高度 > 100px（没塌 ✓）', _h > 100, '%dpx' % _h)
    _root.destroy()
except Exception as _e:     # noqa: BLE001
    ck('④ GUI 行为级', False, repr(_e)[:140])

print()
print('【5】⚠ 磁盘上遗留的旧开关文件（已无读取方 ⇒ 无害，但报一下）')
for _w in ('mimic2', 'shrine'):
    _p = os.path.join('runs', '.stop_%s' % _w)
    print('     %-28s %s' % ('runs/.stop_%s' % _w,
                             '存在（已无读取方 ✓）' if os.path.exists(_p) else '不存在'))
# ⚠ 判据要**精确**（本仓已被"子串匹配"坑了六次 ✗）：
#   前两版假红的来源：
#     ① `.stop_mimic2` ⇒ 匹配到通用拼接 `'.stop_%s' % which` ✗
#     ② `'shrine'`     ⇒ 匹配到**日志标签** `{'shrine': 'panel_seen'}` ✗
#        （那是 `log.append({'shrine': ...})` 的**日志分类名**，与"锁类型"无关 ✓）
#   ⇒ 这次只查**锁类型那两处**（`_KIND_TXT`），因为那才是"废弃的死分支" ✓
# ⛔⛔ 2026-10-12 **整套锁定机制已按用户要求删除**（原话：
#   「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
#   ⇒ `_KIND_TXT` **整张表都没了** ⇒ 下面两条断言**按新行为改写** ✓
_LITERAL = []
for _i, l in (EL + GUI):
    _s = l.strip()
    # 锁类型字典里还留着 shrine/mimic2 当**正常类型**（不是"已废弃"兜底）⇒ 才算残留
    if ("'mimic2':" in _s or "'shrine':" in _s) and '锁定' in _s:
        _LITERAL.append(_s[:90])
    if ("'mimic2':" in _s or "'shrine':" in _s) and '（' in _s and '不' not in _s:
        _LITERAL.append(_s[:90])
print('     锁类型表里仍当正常类型用的 = %s' % (_LITERAL or '无 ✓'))
ck('⑬ 锁类型表里**没有** shrine/mimic2 当正常锁类型',
   not _LITERAL, str(_LITERAL[:3]))
# 直接断言：`_KIND_TXT` **整张表都已删**（不是"只剩 red_equip" ✓）
import ast as _ast

for _f in ('explore_loop.py', 'bot_gui.py'):
    _src = io.open(_f, encoding='utf-8').read()
    _tree = _ast.parse(_src)
    _found = []
    for _n in _ast.walk(_tree):
        if isinstance(_n, _ast.Assign) and any(
                isinstance(_t, _ast.Name) and _t.id == '_KIND_TXT'
                for _t in _n.targets):
            if isinstance(_n.value, _ast.Dict):
                _found += [k.value for k in _n.value.keys
                           if isinstance(k, _ast.Constant)]
    print('     %s 的 `_KIND_TXT` 键 = %s' % (_f, _found or '（表已删 ✓）'))
    ck('⑯ %s 的 `_KIND_TXT` **已删**（锁定机制整体移除 ✓）' % _f, not _found,
       str(_found))
# ⭐ 反向：**旧锁文件必须仍能被读出**（不许崩、不许误导）
ck('⑮ ⭐ 锁机制**已删**（`red_locked` 不再存在 ✓）',
   'def red_locked' not in _EL_S)
# 反向：长期那两个键必须还在（lucky/peace/elem_* 仍走同一机制 ✓）
ck('⑭ ⚠ 反向：`lucky`/`peace`/`elem_*` 仍正常传（没被连带删 ✗）',
   "'lucky'" in _GUI_S and "'peace'" in _GUI_S
   and "'elem_purple'" in _GUI_S and "'elem_orange'" in _GUI_S)

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
