# -*- coding: utf-8 -*-
"""★ 用**真机面板帧**验证：`popups()` 现在走对预言石板那支

帧：`runs/acc1/fst_opened.png`（真机点开后的一帧，OCR 读到「预言石板」conf=0.99 ✓）
断言：`is_reward_panel` 必须 False、`popups()` 必须**不点返回**、而是调 `foretell_flow`
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
from rapidocr_onnxruntime import RapidOCR
import cv2
import numpy as np
import explore_loop as EL
import buypanels as BP

OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


P = r'runs\acc1\fst_opened.png'
img = cv2.imdecode(np.fromfile(P, dtype=np.uint8), cv2.IMREAD_COLOR)
cv2.imwrite(r'runs\acc1\_v_tmp.png', img)
eng = RapidOCR()
res, _ = eng(r'runs\acc1\_v_tmp.png')
items = []
for box, txt, conf in (res or []):
    xs = [q[0] for q in box]
    ys = [q[1] for q in box]
    items.append({'text': str(txt), 'conf': float(conf),
                  'cx': int(sum(xs) / 4), 'cy': int(sum(ys) / 4)})

print('=' * 88)
print('真机面板帧验证：预言石板（%s，%d 条 OCR）' % (os.path.basename(P), len(items)))
print('=' * 88)
print('  面板标题 =', [t['text'] for t in items if '预言' in t['text']])
print()

print('【1】`is_reward_panel` 必须 **False**（这是元凶判据）')
# ⚠ 断言必须查 **return 语句本身**，不能查整个函数体 ——
#   函数体里必然有解释"为什么不要 prophecy"的**留档注释** ⇒ 字符串 grep 会假红 ✗
#   （本项目第四次踩这个坑：v1.62c / v1.67 / v1.68 都是"注释里必然逐字引用旧判据"）
import re as _re

_src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
_seg = _src.split('def is_reward_panel')[1].split('\ndef ')[0]
# ⛔⛔ 2026-10-15 **修这条断言自己的过时正则**（它 10-12 起就**恒判假**了 ✗）
#   ---- 病 ----
#     旧正则写死了 `return bool(fb(items, *L['lime'])...)`，
#     而 10-12 把莱姆判据改成了 `_lime_popup_title(items) is not None`（治"子串被骗"✓）
#     ⇒ 正则**再也匹配不上** ⇒ `bool(_m)` 为假 ⇒ `_props_ok` 恒假 ⇒ **这条恒红** ✗
#     ⚠ 我 10-15 修预言石碑时才发现它（当时以为是自己改坏的 ✗）
#   ---- 修法：**抓"那个 return 语句本身"，不写死它内部用的函数名** ----
#     判据意图**一个字不变**：`is_reward_panel` 的 return 里**不许出现 `prophecy`** ✓
#     ⚠ 仍然**只看 return 行**（不看整个函数体）—— 函数体里必然有
#       "为什么不要 prophecy"的留档注释 ⇒ 查全文会**假红** ✗
#       （本项目已踩过 N 次：v1.62c / v1.67 / v1.68 都是"注释里逐字引用旧判据"✓）
_ret_lines = [l.strip() for l in _seg.splitlines()
              if l.strip().startswith('return ')]
# 取"那个 return bool(...)"（可能跨行 ⇒ 拼到下一行以 `)` 收尾为止 ✓）
_ret_txt = ''
for _i, _l in enumerate(_seg.splitlines()):
    if _l.strip().startswith('return bool('):
        _buf = [_l.strip()]
        _j = _i
        while not _buf[-1].rstrip().endswith(')') and _j + 1 < len(_seg.splitlines()):
            _j += 1
            _buf.append(_seg.splitlines()[_j].strip())
        _ret_txt += ' '.join(_buf)
_props_ok = bool(_ret_txt) and 'prophecy' not in _ret_txt
ck('① `is_reward_panel(items)` 为 False',
   EL.is_reward_panel(items=items) is False,
   '实际 %s' % EL.is_reward_panel(items=items))
ck('② ⚠ `is_reward_panel` 的 **return 语句**里不含 `prophecy`',
   _props_ok, '抓到的 return = %s' % (_ret_txt[:80] or '（没抓到 ✗）'))


class FakeBot:
    dev = '127.0.0.1:16384'

    def __init__(self):
        self.taps = []

    def snap(self, *a, **k):
        return P

    def img(self):
        return img

    def img_dlg(self):
        return img

    def ocr(self, *a, **k):
        return items

    def tap(self, x, y, wait=0.0):
        self.taps.append((x, y))

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))


print()
print('【2】⭐ 真调 `popups()`：必须走 foretell_flow，**不许点返回**')
b = FakeBot()
log = []
_called = {'n': 0}
_orig = BP.foretell_flow


def _spy(*a, **kw):
    _called['n'] += 1
    return {'acts': None, 'stop': None, 'picked': []}   # 空 ⇒ 不真点，只验路径


BP.foretell_flow = _spy
try:
    act = EL.popups(b, items, log,
                    ctx={'flags': {'mapname': '夏日海滩'}, 'marks': {},
                         'tapped': (456, 716)})
finally:
    BP.foretell_flow = _orig

print('     `popups()` 返回 = %r' % (act,))
print('     `foretell_flow` 命中 = %d' % _called['n'])
print('     点过的坐标 = %s' % (b.taps[:6],))
print('     日志 = %s' % [str(e)[:80] for e in log][:4])
ck('③ ⭐ `foretell_flow` **被调用了**（10-07 起从没发生过 ✓）',
   _called['n'] >= 1, '命中 %d' % _called['n'])
ck('④ ⚠ **没有**盲点 (360,835)（"获得新装备"那个返回位）',
   (360, 835) not in b.taps, str(b.taps[:6]))
ck('⑤ 日志里**没有** `newequip_back`',
   not any('newequip' in str(e) for e in log))

print()
print('=' * 88)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
