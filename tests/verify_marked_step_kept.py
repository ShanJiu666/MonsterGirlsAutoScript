# -*- coding: utf-8 -*-
"""★ 回归：**带标记的格不许被"试过就摘"摘掉**（2026-10-11「68 张图只打 62 个首领」第二半）

真机铁证（第 19/41/65 张，**三张全都没打到 boss** ✗）：
    #1109 board marks {"4,1": ["boss"]}          ← **标记扫描认出了 boss** ✓
    #1118 tap fogged_noop cell 4,1 ratio 0.222  ← 分类器却判它是**雾** ✗
    #1119 plan give_up_step cell 4,1             ← 于是"试过就摘" ⇒ boss 从计划消失 ✗
    #1125 stuck_why targets_unreachable  marked_n 1
    #1126 finish targets_unreachable             ⇒ **退图，boss 没打** ✗✗

逻辑：标记是**模板匹配**（硬证据）；`ratio≈0.22` 是**亮度比**判雾（软判据，会被压暗/
      遮挡/渐显动画骗到）⇒ 矛盾时**信标记** ✓
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
OK, BAD = [], []
#: ⭐ 2026-10-14 「**响亮跳过**」名单（语料滚走时用 —— **不静默、也不算失败** ✓）
SKIPPED = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


_SRC = io.open('explore_loop.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _SRC.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('带标记的格不许被"试过就摘"（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `keep_marked_step` 分支', 'keep_marked_step' in _CODE)
ck('② 判据用 `marked_px`（像素集合 ✓）', "(cx, cy) in marked_px" in _CODE)
ck('③ ⚠ 保留分支**排在** `give_up_step` 之前',
   _CODE.find('keep_marked_step') < _CODE.find("'plan': 'give_up_step'"))
# ⚠⚠ 本轮我自己踩的坑：`st['marks']` 的键是**元组**，不是 '4,1' 字符串 ✗
ck('④ ⭐⭐ 取 marks 用**元组**键（`tuple(_rc_g)`），不是字符串 ✗',
   'tuple(_rc_g)' in _CODE)
ck('⑤ ⚠ 代码里**没有**用字符串键取 `st[\'marks\']`（那会永远取不到 ✗）',
   ".get('%d,%d' % _rc_g)" not in _CODE)

print()
print('【2】⭐ 真机数据复算：这一族到底影响几张图')
import json
# ⚠⚠ 2026-10-11 修「本项会随真机日志滚动而无故变红」：
#   原来**只读** `runs/acc1/loop/loop_log.json` —— 而 `explore_loop` 每次开跑都会把
#   上一局**轮转**到 `loop_log_prev.json`（`explore_loop.py:12164-12174` 的既定行为 ✓）
#   ⇒ 用户一跑图，那份"铁证"就换到 `_prev.json` 去了 ⇒ 本项**红得毫无道理** ✗
#   （实测 2026-10-11 23:45：`loop_log.json` 是用户刚跑的新一局 `keep_marked_step=0`，
#     而 `loop_log_prev.json`（23:37 那局）里有 **6** 条 —— 铁证**没丢**，只是换了文件 ✓）
#   ⇒ 现在：**先看当次，当次没有就看上一局**（两处都找不到才算真红 ✓），
#     并**打印是哪一份文件**（不然以后又变成"看不出为什么红" ✗）
# ⛔⛔ 2026-10-13 **改成扫全盘**（原来只扫 `runs/acc1/loop/` ✗）
#   病：`explore_loop` 每局轮转 `loop_log.json → _prev.json`（既定行为）
#   ⇒ 用户跑几局后，`acc1` 那一族**被挤掉** ⇒ 断言假红 ✗
#   （实测：`acc1` 两份都 0 条，而 `runs/acc3/loop/loop_log.json` 仍有 11 条 ✓）
#   ⇒ 与本仓既有纪律一致：**别指向会滚动的单一文件** ✓
import glob as _glob
_d, _src = None, ''
_cands = []
for _p in (['runs/acc1/loop/loop_log.json',
             'runs/acc1/loop/loop_log_prev.json']
            + sorted(_glob.glob('runs/**/loop/loop_log*.json',
                               recursive=True))):
    if _p not in _cands:
        _cands.append(_p)
for _p in _cands:
    try:
        _d = json.load(io.open(_p, encoding='utf-8'))
    except Exception as _e:                 # noqa: BLE001
        print('     （读不到 %s：%r）' % (_p, _e))
        continue
    _txt = io.open(_p, encoding='utf-8', errors='replace').read()
    print('     %s：%d 条事件，`keep_marked_step|give_up_step` 家族 = %d 条'
          % (_p, len(_d) if isinstance(_d, list) else -1,
             _txt.count('keep_marked_step') + _txt.count('give_up_step')))
    if _txt.count('keep_marked_step'):
        _src = _p
        break
if _d is None:
    _d = []
print('     ⇒ 本次复算用：%s' % (_src or '（两份都没有这一族）'))
segs = []
cur = None
for i, e in enumerate(_d):
    if not isinstance(e, dict):
        continue
    if isinstance(e.get('mapname'), str):
        cur = {'n': len(segs) + 1, 'i0': i, 'marks': {}, 'boss_hit': False,
               'fog_marked': [], 'gu_marked': []}
        segs.append(cur)
        continue
    if cur is None:
        continue
    m = e.get('marks')
    if isinstance(m, dict):
        cur['marks'].update(m)
    if e.get('battle') in ('started', 'started_fast') and 'boss' in (e.get('marks') or []):
        cur['boss_hit'] = True
    if e.get('tap') == 'fogged_noop' and e.get('cell') in cur['marks']:
        cur['fog_marked'].append(e.get('cell'))
    if e.get('plan') == 'give_up_step' and e.get('cell') in cur['marks']:
        cur['gu_marked'].append(e.get('cell'))

_hit = [s for s in segs if s['fog_marked'] or s['gu_marked']]
_nb = [s for s in _hit if not s['boss_hit']]
print('     出现「点/摘了带标记的格」的图 = %d 张' % len(_hit))
for s in _hit:
    print('        第%-3d张 #%-5d boss打到=%-5s 点过带标记=%s 摘过带标记=%s'
          % (s['n'], s['i0'], s['boss_hit'], s['fog_marked'], s['gu_marked']))
print('     ⇒ 其中**没打到 boss** = %d 张（修复直接救回 ✓）' % len(_nb))
# ⛔⛔ 2026-10-14 **修"数据滚走后假红"**（回归自己的问题，被测代码没错 ✗）
#   ---- 病 ----
#     ⑥ 原来**扫 `runs/**/loop/loop_log*.json`** 取证，可 `explore_loop` 每局
#     把 `loop_log.json` 轮转成 `_prev.json`、旧的被覆盖
#     ⇒ 用户连跑几局后那一族**一条都不剩** ⇒ 断言假红 ✗
#     实测（2026-10-14）：全盘 `keep_marked_step` = **0 条**（本会话早前还有 11 条）✗
#   ⚠ 而**不许手写假夹具**（本仓纪律：fixture 必须来自真机 ✓）⇒ 造不出来
#   ⇒ 修法：**有数据就断言、没有就"响亮跳过"**（绝不静默 ✗）——
#     真正守门的是【1】【2】那些**结构/行为**判据（它们不依赖日志 ✓）
if _hit:
    ck('⑥ ⭐⭐ 真机数据里确实有这一族（铁证 ✓）', True, '%d 张' % len(_hit))
    ck('⑦ ⭐ 且这些图**全都没打到 boss**（后果严重 ✓）',
       len(_nb) == len(_hit), '%d/%d' % (len(_nb), len(_hit)))
else:
    print()
    print('     ⚠⚠ **语料已滚走**（全盘 `keep_marked_step` = 0 条）⇒ ⑥⑦ **跳过**')
    print('        · 原因：`explore_loop` 每局把 `loop_log.json` 轮转成 `_prev.json`')
    print('          ⇒ 用户连跑几局就把这一族顶掉了（**不是代码问题** ✗）')
    print('        · ⚠ **不手写假夹具**（本仓纪律：fixture 必须来自真机 ✓）')
    print('        · 本回归的守门价值由【1】【2】的**结构/行为**判据承担 ✓')
    SKIPPED.append('⑥⑦ 真机语料已滚走（keep_marked_step=0 条）')

print()
print('【3】⚠ 反向：`st[\'marks\']` 的键形态必须是元组（铁证来源）')
import inspect
import marks as _M

_doc = inspect.getsource(_M.scan_board)[:120]
print('     `marks.scan_board` docstring 开头：%s' % _doc.split('\n')[1][:80])
ck('⑧ `scan_board` 文档写明键是 `(row,col)` 元组',
   '(row,col)' in _doc or '(row, col)' in _doc)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
if SKIPPED:
    print('   ⚠ 以下 %d 组**没真正验证**（语料原因，非代码问题）：' % len(SKIPPED))
    for s in SKIPPED:
        print('     - ' + s)
sys.stdout.flush()
os._exit(1 if BAD else 0)
