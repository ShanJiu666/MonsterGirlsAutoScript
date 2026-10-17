# -*- coding: utf-8 -*-
"""★ 回归：预言石碑「要停的卡」必须在**选卡之前**就停（2026-10-13 用户报）

用户原话：`🛑🛑 抽到【元素·紫色】⇒ **立即停止**（不退图，留着你自己处理）`
          ＋「**说是立即停止，结果已经选择完预言了，我要在预言选择界面停止**」

⛔ 病（代码顺序反了）——`buypanels.foretell_flow` 原顺序：
     ① `for c in pick: tap_dlg(c['x'], c['y'])`   ← **先点卡**（已经选完）✗
     ② `for c in pick: if '元素' …`                ← 之后才判要不要停
     ③ `tap_dlg(确定)`                            ← 再点确定
   ⇒ 用户看到"已经选择完预言"才停 ✗

⭐ 修法：判停**提到点卡之前** ⇒ 要停 ⇒ **一张都不点、连确定也不点** ⇒ 面板原样留着 ✓

⚠⚠ 本回归我第一版有两个**探针自己的 bug**（被测代码没错），记下来：
   · `_find_text_btn(b, ('确定',)` 在文件里**有两处**（勇者之墓 ~2274 / 预言 ~2621）
     第一版取到了**前面那个** ⇒ 行序判据假红 ✗
   · "判停块"用 `lines[stop : pick]` 切片 ⇒ **块尾正好是点卡行** ⇒
     `tap_dlg` 出现在切片里 ⇒ 假红 ✗
   ⇒ 现在：**限定在 `foretell_flow` 函数体内**取值 + 切片**不含**点卡行 ✓
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import buypanels


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


_S = io.open(os.path.join(CORE, 'buypanels.py'), encoding='utf-8').read()
_LS = _S.splitlines()


def _fn_span(name):
    """`def name(...)` 的行号区间（1-based，含）—— 用缩进判断函数体结束 ✓"""
    i0 = None
    for i, l in enumerate(_LS, 1):
        if l.startswith('def %s(' % name):
            i0 = i
            break
    if i0 is None:
        return None, None
    i1 = len(_LS)
    for j in range(i0, len(_LS)):
        l = _LS[j]
        if l.strip() and not l.startswith((' ', '\t')) and j + 1 > i0 + 1:
            i1 = j          # 下一个顶层定义 ⇒ 函数体到此为止
            break
    return i0, i1


_F0, _F1 = _fn_span('foretell_flow')
print('=' * 94)
print('预言石碑：要停 ⇒ 必须在选卡之前停（2026-10-13）')
print('=' * 94)
print('  `foretell_flow` 行区间 = %s ~ %s' % (_F0, _F1))


def _line_in_fn(pred):
    for i in range(_F0 or 1, (_F1 or len(_LS)) + 1):
        if pred(_LS[i - 1]):
            return i
    return None


print()
print('【1】⭐ 行序：判停 < 点卡 < 点确定（全在 `foretell_flow` 内 ✓）')
_L_STOP = _line_in_fn(lambda l: l.strip() == 'if _stop_why:')
_L_PICK = _line_in_fn(lambda l: "tap_dlg(c['x'], c['y'], wait=1.4)" in l)
_L_OK = _line_in_fn(lambda l: "_find_text_btn(b, ('确定',)" in l)
print('     判停=%s ｜ 点卡=%s ｜ 点确定=%s' % (_L_STOP, _L_PICK, _L_OK))
ck('① 判停行在 `foretell_flow` 内', _L_STOP is not None)
ck('② 点卡行在 `foretell_flow` 内', _L_PICK is not None)
ck('③ ⭐⭐ **判停 < 点卡**（本 bug 的正题 ✓）',
   None not in (_L_STOP, _L_PICK) and _L_STOP < _L_PICK,
   '%s < %s' % (_L_STOP, _L_PICK))
ck('④ ⭐ 点卡 < 点确定（顺序合理 ✓）',
   None not in (_L_PICK, _L_OK) and _L_PICK < _L_OK,
   '%s < %s' % (_L_PICK, _L_OK))

print()
print('【2】⭐ 判停那块里**必须 `return`**（不点卡、不点确定 ✓）')
# ⚠ 切片**不含**点卡行（`_L_PICK - 1`）—— 第一版含了 ⇒ 假红 ✗
_seg = '\n'.join(_LS[(_L_STOP or 1) - 1:(_L_PICK or len(_LS)) - 1])
print('     判停块 %d 行（不含点卡行 ✓）' % len(_seg.splitlines()))
ck('⑤ ⭐ 块内有 `return out`（直接返回 ✓）', 'return out' in _seg)
ck('⑥ ⚠ 块内**没有** `tap_dlg`（一张卡都没点 ✓）',
   'tap_dlg' not in _seg,
   str([l.strip()[:60] for l in _seg.splitlines() if 'tap_dlg' in l]))
ck('⑦ ⭐ `out[\'picked\'] = []`（如实记账 ✓）', "out['picked'] = []" in _seg)
ck('⑧ ⭐ `out[\'acts\'] = [\'stop_before_pick\']` ✓',
   "out['acts'] = ['stop_before_pick']" in _seg)
ck('⑨ 落了 `stop_before_pick` 日志', 'stop_before_pick' in _seg)

print()
print('【3】⚠ 反向守门：旧的"点卡之后再判停"**不许回来**')
_OLD = [i for i, l in enumerate(_LS, 1)
        if ("out['stop'] = '元素·橙色'" in l or "out['stop'] = '元素·紫色'" in l
            or "out['stop'] = '幸运'" in l or "out['stop'] = '和平·金属宝箱怪'" in l)]
print('     旧式直接赋值行 = %s' % (_OLD or '无 ✓'))
ck('⑩ ⚠ 已无"点卡后直接赋值 `out[\'stop\']`"的旧写法', not _OLD, str(_OLD))
ck('⑪ ⚠ 旧块位置留了"已删"说明（留档 ✓）', '旧判停块已删' in _S)

print()
print('【4】⭐⭐ 行为级：真跑 `foretell_flow`，断言**一次 tap 都没有**')
_CALLS = []


class _FakeBot:
    dev = '127.0.0.1:16448'

    def tap_dlg(self, x, y, wait=0.0, **kw):
        _CALLS.append((x, y))
        return True

    def tap(self, x, y, **kw):
        _CALLS.append((x, y))
        return True

    def ocr(self, *a, **kw):
        return []

    def snap(self, *a, **kw):
        return None


_OLD_READ = buypanels._foretell_read_cards
_OLD_ITEMS = buypanels._items
_OLD_HAS = buypanels._has
try:
    buypanels._items = lambda b: [{'text': '预言石板', 'x': 1, 'y': 1,
                                   'cx': 1, 'cy': 1}]
    buypanels._has = lambda it, s: True

    # ── 场景 A：**元素·紫色** ⇒ 必须一张都不点 ──
    _CALLS.clear()
    buypanels._foretell_read_cards = lambda b, log=None: (
        [{'name': '元素', 'eff': '地图中至少出现1只莱姆，且所有莱姆至少是紫色位阶',
          'tier': 3, 'x': 100, 'y': 500},
         {'name': '丰收', 'eff': '+200%', 'tier': 3, 'x': 300, 'y': 500}], 1)
    _out = buypanels.foretell_flow(
        _FakeBot(), [], flags={'stop_elem_purple': True, 'stop_elem_orange': True,
                               'stop_peace_metal': True})
    print('     A 返回 = %s' % {k: _out[k] for k in ('stop', 'picked', 'acts')})
    print('     A 实际 tap = %s' % (_CALLS or '**一次都没有** ✓'))
    ck('⑫ ⭐⭐ `stop` = 元素·紫色', _out.get('stop') == '元素·紫色',
       str(_out.get('stop')))
    ck('⑬ ⭐⭐⭐ **一次 tap 都没有**（卡没选、确定也没点 ✓）', not _CALLS,
       str(_CALLS))
    ck('⑭ ⭐ `picked` 为空（如实 ✓）', _out.get('picked') == [],
       str(_out.get('picked')))

    # ── 场景 B（对照）：**元素·蓝色** ⇒ 不停 ⇒ 必须照常点 ──
    _CALLS.clear()
    buypanels._foretell_read_cards = lambda b, log=None: (
        [{'name': '元素', 'eff': '地图中至少出现1只莱姆，且所有莱姆至少是蓝色位阶',
          'tier': 2, 'x': 100, 'y': 500}], 1)
    _out2 = buypanels.foretell_flow(
        _FakeBot(), [], flags={'stop_elem_purple': True, 'stop_elem_orange': True})
    print('     B（蓝档）返回 = %s ｜ tap = %s'
          % ({k: _out2[k] for k in ('stop', 'picked')}, _CALLS))
    ck('⑮ ⚠ 对照：**蓝档不停**（`stop` 空 ✓）', not _out2.get('stop'),
       str(_out2.get('stop')))
    ck('⑯ ⚠ 对照：蓝档**照常点卡 + 点确定**（证明不是"永不点" ✓）',
       len(_CALLS) >= 2, str(_CALLS))

    # ── 场景 C（对照）：**幸运** ⇒ 也要在选卡前停 ──
    _CALLS.clear()
    buypanels._foretell_read_cards = lambda b, log=None: (
        [{'name': '幸运', 'eff': '幸运值提升', 'tier': 5, 'x': 100, 'y': 500}], 1)
    _out3 = buypanels.foretell_flow(_FakeBot(), [], flags={'stop_lucky': True})
    print('     C（幸运）返回 = %s ｜ tap = %s'
          % ({k: _out3[k] for k in ('stop', 'picked')}, _CALLS))
    ck('⑰ ⭐ 幸运也在**选卡前**停（同类口径一致 ✓）',
       _out3.get('stop') == '幸运' and not _CALLS,
       '%s / tap=%s' % (_out3.get('stop'), _CALLS))
finally:
    buypanels._foretell_read_cards = _OLD_READ
    buypanels._items = _OLD_ITEMS
    buypanels._has = _OLD_HAS

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
