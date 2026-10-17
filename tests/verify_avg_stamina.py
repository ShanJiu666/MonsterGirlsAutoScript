# -*- coding: utf-8 -*-
"""⭐ 回归：GUI「均耗」**不许低于 25**（2026-10-16 用户报「acc1 均耗 20.2」）。

用户原话：「**acc1 最近一波为什么均耗能到 20.2？进图不就消耗 25 了**」

⭐ 算术事实：**进图固定扣 25 点** ⇒ 每图消耗**不可能 < 25** ✓
   所以"20.2"一定是**算错**，不是游戏行为 ✗

⭐ 病根（真机铁证 `runs/acc1/last_summary.json`）：
   GUI 原来用 **(首 − 末) / 图数**，它假设「整局中间没人补过体力」✗
   实测该局的 `stamina_entries`：
       ...146, 99, 66, 35, | **544, 545**, | 513, 484, ...
                           ↑ 补给回升 **+509**
   总回升 **514** 点 ÷ 70 图 = **低估 7.3**
   ⇒ 真值 **32.7** 被算成 **24.8**（用户看到 20.2 的那次回升更多）✗

⭐ 修法：**逐段相减 + 按「30 秒回 1 点」补偿**（与 `explore_loop.stamina_line()`
   **同一套公式**，单一口径 ✓），每段夹 ≥0（中途大额补充不冲抵别的段 ✓）

⚠ 本门禁钉三件事：
   ① 源码里**不再**用 `(first - last) / maps` 当均耗
   ② 新公式在**真机数据**上给出 **≥ 25** 的值（= 32.7 ✓）
   ③ **对照项**：老公式在同一份数据上**确实 < 25**（证明本门禁不是恒绿 ✓）

用法：python verify_avg_stamina.py
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
import ast
import re
import json


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
N = [0]
FAILS = []


def ck(name, cond, detail=''):
    if cond:
        N[0] += 1
    else:
        FAILS.append(name)
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))


SRC = io.open(os.path.join(CORE, 'bot_gui.py'), encoding='utf-8').read()
# ⚠ 必须**剥掉注释/docstring**再查（本项目已踩过 4 次：
#   留档注释里会**逐字引用**旧写法 ⇒ 直接 grep 会假红 ✗）
_tree = ast.parse(SRC)


def _strip_comments(s):
    """把 `#` 整行注释与三引号串去掉（保留代码结构）✓"""
    s = re.sub(r'""".*?"""', '""', s, flags=re.S)
    s = re.sub(r"'''.*?'''", "''", s, flags=re.S)
    out = []
    for ln in s.splitlines():
        i = ln.find('#')
        out.append(ln[:i] if i >= 0 else ln)
    return '\n'.join(out)


CODE = _strip_comments(SRC)

print('=' * 84)
print('GUI「均耗」回归（不许 < 25）')
print('=' * 84)
print()

print('【1】源码级：均耗**不再**用「首末相减 / maps」')
# 找 _update_dashboard 里 card_avg.set 那一段
_seg = ''
for _n in ast.walk(_tree):
    if isinstance(_n, ast.FunctionDef) and _n.name == '_update_dashboard':
        _seg = ast.get_source_segment(SRC, _n) or ''
        break
_seg_code = _strip_comments(_seg)
ck('① `_update_dashboard` 里**没有** `(first - last) / maps` 这种均耗写法'
   '（⛔ 它会被补给污染 ✗）',
   not re.search(r'first\s*-\s*last\s*\)\s*/\s*maps', _seg_code)
   and not re.search(r'first\s*-\s*last\)\s*/\s*maps', _seg_code),
   '（已剥注释后再查 ✓）')
ck('② ⭐ 分母 = **`len(_parts)`**（**有效**段数 ✓）'
   '—— ⛔ 不是 `len(ent) - 1`（那是**原始**段数，异常段被剔后会对不上 ✗）',
   'len(_parts)' in _seg_code and 'len(ent) - 1' not in _seg_code,
   '（我用过 `len(ent)-1` ⇒ 夹具上算成 17.9，**又错了** ✗ 分子分母必须同源 ✓）')
ck('②b ⭐⭐ 有**单段上限** `_SEG_MAX`（剔掉"不是两次进图之间"的异常段 ✓）',
   # ⚠ 查**类级**定义 + **在 `_stamina_spent` 里真的用了** `self._SEG_MAX`
   #   （我第一版只查 `_seg_code`（= `_update_dashboard` 那段）⇒ 假红 ✗：
   #    定义在 `_update_dashboard` 里、用的是 `self._SEG_MAX`，**类属性**作用域 ✓）
   'self._SEG_MAX' in CODE and '_SEG_MAX = 60.0' in CODE,
   '（实测夹具 `735→34=701` 会把均耗算成 252 ✗）')
ck('②c ⭐ 分母**绝不可能是 0** 时才算（`and _nseg` 守着 ✓）',
   'and _nseg' in _seg_code or 'if spent is not None and _nseg' in _seg_code)
ck('③ 有 **30 秒回 1 点**的补偿（与 `stamina_line` 同源 ✓）',
   '/ 30.0' in CODE or '/30.0' in CODE,
   '（不补回来的话会把"游戏自己回的"当成"没花的"⇒ 低估 ✗）')
ck('④ 每段**夹 ≥0**（`max(0.0, ...)`）⇒ 中途大额补充不冲抵别的段 ✓',
   'max(0.0, (s0 - s1)' in CODE)
ck('⑤ 新 Helper `_stamina_spent` 存在（口径集中一处，不再两处各算 ✗）',
   '_stamina_spent' in CODE,
   '（本项目老毛病："同一件事两处各算一遍" ⇒ 必然分叉 ✗）')

print()
print('【2】数值级：拿**真机数据**跑，新公式必须 ≥ 25')
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs', 'acc1', 'last_summary.json')
if os.path.exists(P):
    j = json.load(io.open(P, encoding='utf-8', errors='replace'))
    st = (j.get('stats') or {})
    ent = st.get('stamina_entries') or []
    maps = int(st.get('maps') or 0)
    vals = [x[0] for x in ent if isinstance(x, (list, tuple))]
    ck('⑥ 语料可用（acc1 的 stamina_entries 有 %d 段 / maps=%d）'
       % (max(0, len(vals) - 1), maps),
       len(vals) >= 2 and maps > 0)
    if len(vals) >= 2:
        # 新公式（与代码逐字同源，**含 `_SEG_MAX` 过滤** ✓）
        total, nseg = 0.0, 0
        for i in range(len(ent) - 1):
            s0, t0 = float(ent[i][0]), float(ent[i][1])
            s1, t1 = float(ent[i + 1][0]), float(ent[i + 1][1])
            regen = max(0.0, t1 - t0) / 30.0
            sp = max(0.0, (s0 - s1) + regen)
            if sp > 60.0:                       # `_SEG_MAX` ✓
                continue
            total += sp
            nseg += 1
        new_avg = total / nseg if nseg else None
        old_avg = (vals[0] - vals[-1]) / maps
        ck('⑦ ⭐ 新口径 = **%.1f** 点/张 ⇒ **≥ 25** ✓'
           '（进图 25 + 图内 %.1f；有效段 %d）' % (new_avg, new_avg - 25, nseg),
           new_avg is not None and new_avg >= 25.0,
           'new=%.2f' % (new_avg or 0))
        ck('⑧ ⚠ **对照项**：老口径在同一份数据上 = **%.1f** ⇒ **< 25** ✗'
           '（证明本门禁不是恒绿 ✓）' % old_avg,
           old_avg < 25.0,
           'old=%.2f（**算术上不可能** ⇒ 这就是用户看到的病 ✓）' % old_avg)
        ck('⑨ 两者**确实不同**（若相同说明新公式没生效 ✗）',
           abs((new_avg or 0) - old_avg) > 1.0,
           'new-old = %.1f' % ((new_avg or 0) - old_avg))
        # 补给回升确实存在（否则本语料测不出这个 bug）
        ups = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)
               if vals[i + 1] > vals[i]]
        ck('⑩ 该语料**确实含补给回升**（%d 次 / 共 +%d 点）'
           '⇒ 能真正测出这个 bug ✓' % (len(ups), sum(ups)),
           len(ups) > 0, 'ups=%s' % (ups[:5],))
else:
    print('   ⚠ 缺 %s ⇒ ⑥~⑩ 未验证' % P)

print()
print('【2b】⭐ 异常段过滤（`_SEG_MAX`）—— **夹具抓出来的真 bug**')
# 场景：`[785, 760, 735, 34]` —— 末条 34 是"停止时的体力"（**不是进图读数**）
#   ⇒ `735→34 = 701` 会被当成"一张图的消耗" ⇒ 均耗算成 252（荒谬 ✗）
#   ⇒ 修法：单段 > `_SEG_MAX(60)` ⇒ 跳过 ✓
# ⛔⛔ **必须调真函数**（我第一版在这里**自己重写了一遍公式** ⇒
#   "牙齿 A（撤掉过滤）"居然还是全绿 ⇒ **假牙** ✗✗
#   ⇒ 教训：门禁**不许复述被测逻辑** —— 复述出来的东西撤掉真代码也不会红 ✓）
_bad = [[785, 1000.0], [760, 1033.0], [735, 1066.0], [34, 1099.0]]
try:
    import tkinter as _tk                                        # noqa: F401
    import bot_gui as _bg

    class _F(object):
        """只带 `_SEG_MAX` 的假 self（`_stamina_spent` 只用到它 ✓）"""
        _SEG_MAX = _bg.App._SEG_MAX

    _spent, _how, _parts = _bg.App._stamina_spent(_F(), _bad)
    _n_yes = len(_parts)
    _yes = (_spent / _n_yes) if _n_yes else None
    ck('㉗ ⭐ 真函数过滤后 ⇒ 均耗 = **%.1f** ⇒ 落在合理区间（25~60 ✓）'
       % (_yes or 0), _yes is not None and 25.0 <= _yes <= 60.0,
       'filtered=%.1f（有效段 %d，how=%s）' % (_yes or 0, _n_yes, _how))
    ck('㉘ ⭐ 剔掉了那个 701 的异常段（有效段 = %d，'
       '**原始段数 = %d** ⇒ 少了 1 ✓）' % (_n_yes, len(_bad) - 1),
       _n_yes == len(_bad) - 2, 'yes=%d want=%d' % (_n_yes, len(_bad) - 2))
    ck('㉙ ⭐ `how` 里**如实写明剔了几段**（不静默 ✗）',
       '剔除' in str(_how), 'how=%s' % _how)
    ck('㉚ 过滤**只剔异常段**、不整条丢掉（有效段 > 0 ✓）', _n_yes > 0)
    # ⚠ 对照项：**不过滤**会长什么样（同一个真函数，把上限调巨大 ⇒ 病态）
    class _F2(object):
        _SEG_MAX = 1e9
    _s2, _h2, _p2 = _bg.App._stamina_spent(_F2(), _bad)
    _badavg = (_s2 / len(_p2)) if _p2 else None
    ck('㉛ ⚠ **对照项**：把上限调巨大（= 不过滤）⇒ 均耗 = **%.1f** '
       '（> 60 ✗ 荒谬 ⇒ 证明过滤**真在起作用** ✓）' % (_badavg or 0),
       _badavg is not None and _badavg > 60.0, 'no-filter=%.1f' % (_badavg or 0))
except Exception as _e:
    ck('㉗~㉛ 调真函数 `_stamina_spent`（无 tkinter 环境会失败）', False,
       repr(_e)[:120])

print()
print('【3】与 `explore_loop.stamina_line()` 同源（单一口径 ✓）')
_el = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
ck('⑪ `explore_loop.stamina_line()` 仍用**逐段 + 30 秒补偿**'
   '（GUI 复用的是这套 ✓ 别再改歪 ✗）',
   'regen = dt / 30.0' in _el and 'max(0.0, (s0 - s1) + regen)' in _el)
ck('⑫ 两处的公式**逐字一致**（GUI 的 `s0 - s1` / `/ 30.0` / `max(0.0,` ✓）',
   'max(0.0, (s0 - s1) + regen)' in CODE
   and '/ 30.0' in CODE)

print()
print('=' * 84)
if FAILS:
    print('通过 %d 项，失败 %d 项' % (N[0], len(FAILS)))
    for f in FAILS:
        print('   ✗ %s' % f)
    raise SystemExit(1)
print('通过 %d 项，失败 0 项' % N[0])
