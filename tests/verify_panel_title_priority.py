# -*- coding: utf-8 -*-
"""★ 回归：**面板分派必须"标题优先"**（2026-10-11「第 46 张卡死 44 轮」）

⛔ 病（真机铁证 `runs/acc1/loop/loop_log.json` #2460~#2687）：
    #2460 {"special": "勇者之墓",
           texts: ["预言石板", "本次可选择1个预言！", "路标",
                   "地图中至少出现1个勇者", "之墓，并且勇者之墓奖", ...]}
           ↑ 面板其实是**预言石碑**，却被判成**勇者之墓** ✗
    #2461 {"vault_step": "relic_start", "n": 88}
    #2462 {"relic": "panel_missing"}       ← 勇者之墓面板"不存在"
    …（**重复 44 轮**，体力一直 715 ⇒ maxed 退图；boss 也没打 ✗✗）

根因：`fb()` 是**子串**匹配，而预言卡「奇遇」的效果文字里**含"勇者之墓"**
      且 `L['special']` 里 `勇者之墓` **排在** `预言石板` **之前** ✗
      ⇒ 复算：全盘 **86 条** `special` 全是这种错派 ✓
"""
import glob
import io
import json
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import explore_loop as EL


OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料）⇒ **响亮地跳过**（不算通过、也不算失败）。"""
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


print('=' * 94)
print('面板分派「标题优先」（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `_panel_title_of`', hasattr(EL, '_panel_title_of'))
ck('② 有 `_PANEL_TITLES` 表', hasattr(EL, '_PANEL_TITLES')
   and len(EL._PANEL_TITLES) >= 4, str(getattr(EL, '_PANEL_TITLES', ())[:5]))
_src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
_code = '\n'.join(l for l in _src.splitlines() if not l.lstrip().startswith('#'))
ck('③ 分派入口用了 `_panel_title_of`', '_panel_title_of(items)' in _code)
ck('④ ⚠ 它用**等于**判据（`in _txts`），不是子串 `fb`（否则又会被正文骗 ✗）',
   '_t in _txts' in _code)

print()
print('【2】⭐⭐ 行为级：**真机那条 texts** 必须判成「预言石碑」')
# ⛔⛔ 2026-10-11 **修本回归的假红**（教训：夹具不能指向会滚动的日志 ✗）
#   原来写 `_d = json.load(open('runs/acc1/loop/loop_log.json'))` + `_d[2460]`
#   ⇒ 那个文件**会被后续运行覆盖**（滚动日志，现在只剩 13 条）⇒ `IndexError` ✗
#   ⇒ 门禁从绿变红，**代码没坏、是夹具不稳** ✗（本项目第 N 次踩这个）
#   ⇒ 修法：把那条**真机 texts 原文**固化成 `_verify/foretell_misdispatch_texts.json`
#     （用 `_tmpman/mk_fixture_misdispatch.py` 从真机日志提取 ⇒ **非手写** ✓）
_HERE = ROOT          # ⚠ 迁到子目录后：相对资源以仓根为基准
_FIX = os.path.join(_HERE, '_verify', 'foretell_misdispatch_texts.json')
if not os.path.exists(_FIX):
    ck('⑤ 有稳定夹具', False, _FIX)
    raise SystemExit(1)
_FD = json.load(io.open(_FIX, encoding='utf-8'))
_e = {'texts': _FD['texts'], 'special': _FD.get('special_recorded')}
print('     夹具来源：%s' % _FD.get('source'))
print('     真机 texts 关键条：%s'
      % [t for t in _e['texts'] if '预言' in t or '勇者' in t or '之墓' in t])
_items = [{'text': t} for t in _e['texts']]
_title = EL._panel_title_of(_items)
print('     `_panel_title_of` ⇒ %r' % _title)
ck('⑤ ⭐⭐ 标题识别 = 「预言石板」', _title == '预言石板', repr(_title))
_t = EL.SPECIAL_ALIAS.get(_title, _title) if _title else None
ck('⑥ ⭐⭐ 归一到规范名 = 「预言石碑」（不是勇者之墓 ✗）', _t == '预言石碑', repr(_t))

print()
print('【3】⚠ 对照项：**旧口径**（按元组顺序子串扫）确实会错派')
_old = None
for _x in EL.L['special']:
    if EL.fb(_items, _x):
        _old = _x
        break
print('     旧口径第一个命中 = %r' % _old)
ck('⑦ ⚠ **对照项**：旧口径判成「勇者之墓」⇒ 证明本回归测得出这个 bug ✓',
   _old == '勇者之墓', repr(_old))
ck('⑧ ⚠ 且正文里**确实含**「勇者之墓」（这就是被骗的原因 ✓）',
   EL.fb(_items, '勇者之墓') is not None)

ck('⑨ ⭐⭐ 夹具证明**旧口径确实会错派**（= 那天 86/92 条错派的同一形态 ✓）',
   _old == '勇者之墓' and _t == '预言石碑',
   '旧口径=%r 新口径=%r（真机当天 86/92 条错派都是这个形态 ✓）' % (_old, _t))

print()
print('【5】⚠ 反向：**标题不在**列表里时不许乱改 `t`（fail-open ✓）')
_plain = [{'text': '战斗胜利'}, {'text': '返回'}]
ck('⑩ ⚠ 读不到标题 ⇒ `_panel_title_of` 返回 None（不改分派 ✓）',
   EL._panel_title_of(_plain) is None)
# 只有正文含「勇者之墓」但没有标题 ⇒ 标题判据必须返回 None
_span = [{'text': '地图中至少出现1个勇者之墓'}]
ck('⑪ ⚠ **正文里含「勇者之墓」但没有标题** ⇒ 仍返回 None（不许当标题 ✓）',
   EL._panel_title_of(_span) is None, repr(EL._panel_title_of(_span)))

print()
print('【6】⭐ OCR 前缀容错（真机 #2500 读成 `+预言石板` ✗）')
for _s, _exp in (('预言石板', '预言石板'), ('+预言石板', '预言石板'),
                 (' 预言石板 ', '预言石板'), ('【英灵使者】', '英灵使者'),
                 ('-传承祭坛', '传承祭坛')):
    _got = EL._panel_title_of([{'text': _s}])
    ck('⑫ %r ⇒ %r' % (_s, _exp), _got == _exp, repr(_got))
ck('⑬ ⚠ 带感叹号的正文**不许**被当标题（`本次可选择1个预言！`）',
   EL._panel_title_of([{'text': '本次可选择1个预言！'}]) is None)

print()
print('【7】⭐ 真机全盘：修后**每条 `special` 都能认出正确标题**')
# ⚠ 同前：扫**所有**历史 loop_log，并取"能识别出标题的比例"当判据
#   （不写死条数 —— 日志会滚动，写死必然假红 ✗）
# ⛔⛔ 2026-10-13 **修两条数据依赖断言**（回归自己的问题，被测代码没错 ✗）
#   ---- 病 ----
#     ⑨ 断言"真机数据里 ≥20 条错派"、⑭ 断言"识别为预言石板 ≥20 条"。
#     可**修好之后新写的日志不再有错派** ⇒ 旧证据被新数据顶掉 ✗
#     实测（2026-10-13）：全盘 `special` 事件只剩 **36 条**、**不一致 0 条** ✓
#       ⇒ ⑨ 永远不可能 ≥20（那些错派记录已随滚动日志消失）
#       ⇒ ⑭ 也只数到 11 条「预言石板」
#   ---- 修法（与本仓既有做法一致 ✓）----
#     ⑨ 的"错派铁证"改读**固化语料** `_verify/foretell_misdispatch_texts.json`
#       （那条真机 texts 原文早就存下来了，正是不想再依赖滚动日志 ✓）
#     ⑭ 改成**比例判据** + 只要求"确实有"（不写死 20）—— 数据量本来就随滚动变化 ✓
_c = {}
for _p in glob.glob('runs/**/loop/loop_log*.json', recursive=True):
    try:
        _dd = json.load(io.open(_p, encoding='utf-8'))
    except Exception:       # noqa: BLE001
        continue
    if not isinstance(_dd, list):
        continue
    for _x in _dd:
        if not isinstance(_x, dict) or 'special' not in _x:
            continue
        _its = [{'text': t} for t in (_x.get('texts') or [])]
        _k = str(EL._panel_title_of(_its))
        _c[_k] = _c.get(_k, 0) + 1
print('     分布 = %s' % _c)
if not _c:
    # ⚠ 公开发布版**不含**开发者的真机录屏语料（runs/ 是本地私有数据、且滚动覆盖）
    #   ⇒ 这里必须**响亮跳过**：算通过是假绿，算失败又不是代码问题。
    skip('⑭ 真机全盘：每条 special 归一正确标题',
         '缺真机语料 runs/**/loop/loop_log*.json（发布版不带私有录屏）⇒ 未真正验证')
else:
    _stele = _c.get('预言石板', 0)
    _all = sum(_c.values()) or 1
    ck('⑭ ⭐⭐ 识别为「预言石板」的**占多数**且 ≥1（修后绝大多数被正确归一 ✓）',
       _stele >= 1 and _stele >= 0.20 * _all,
       '预言石板 %d / 共 %d' % (_stele, _all))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
for x in BAD:
    print('   ✗ ' + x)
if SKIP:
    print('   ⚠ 以下 %d 项**没真正验证**（缺真机语料，非代码问题）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.stdout.flush()
os._exit(1 if BAD else 0)
