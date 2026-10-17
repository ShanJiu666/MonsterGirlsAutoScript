# -*- coding: utf-8 -*-
"""★ 回归：`_confirm()` 不许漏确认框、且只点一次（2026-10-11）

⛔ 两个真 bug（都在真机帧/实测上抓到）：
  ① **`cy > 800` 过严 ⇒ 漏掉一整类确认框** ✗
     真机铁证 `_verify/finish_confirm_dialog_20261002.png`
     （「提示 / 还有未拾取的战利品 / 是否结束冒险?」+ 取消/确定）
     ⇒ 「确定」在 **(516, 742)** ⇒ `cy>800` **判不到** ✗✗
     （另一真机帧 `pcrun_10.png` 在 `(379,876)` ⇒ 那种才命中 ✓ ⇒ **两类 y 不同**）
  ② **同一坐标被点两下** ✗
     `for _ in range(2)` + `_items()` **同帧缓存** ⇒ 第二轮读到的还是点之前那帧
     ⇒ 实测 `taps=[(516,742),(516,742)]` ⇒ 第二下点空 ✗
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


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


class B:
    def __init__(self):
        self.taps = []

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))


_orig = BP._items

print('=' * 92)
print('`_confirm()` 确认框（2026-10-11）')
print('=' * 92)

print()
print('【1】⭐ 低位确认框（真机 `finish_confirm_dialog_20261002.png` 的坐标）')
_dlg = [{'text': '提示', 'cx': 360, 'cy': 520, 'conf': 1.0},
        {'text': '取消', 'cx': 204, 'cy': 742, 'conf': 1.0},
        {'text': '确定', 'cx': 516, 'cy': 742, 'conf': 1.0}]
BP._items = lambda bot, reuse=True: _dlg
_b = B()
_l = []
_r = BP._confirm(_b, _l, 'test')
print('     返回=%s taps=%s' % (_r, _b.taps))
ck('① ⭐ 点到了 (516,742)（修前 `cy>800` **漏掉** ✗）',
   (516, 742) in _b.taps, str(_b.taps))
ck('② ⭐ **只点一次**（修前同帧点两下 ✗）', len(_b.taps) == 1, str(_b.taps))
ck('③ ⚠ **绝不点「取消」**（点错会浪费钱/道具 ✗）',
   (204, 742) not in _b.taps, str(_b.taps))
ck('④ 如实记了 `buy_confirm_paired`（说明走的是新判据 ✓）',
   any(isinstance(e, dict) and 'buy_confirm_paired' in e for e in _l))

print()
print('【2】⚠ 反向：**结果框**（只有「确定」、无「取消」）低位 ⇒ 不许误点')
_res = [{'text': '确定', 'cx': 360, 'cy': 770, 'conf': 1.0}]
BP._items = lambda bot, reuse=True: _res
_b2 = B()
_r2 = BP._confirm(_b2, [], 't2')
ck('⑤ ⚠ 结果框低位「确定」⇒ **不点**（没有「取消」= 不是确认框 ✓）',
   not _b2.taps, str(_b2.taps))

print()
print('【3】旧判据（高位「确定」，真机 `pcrun_10.png` 在 (379,876)）仍要能点到')
_hi = [{'text': '确定', 'cx': 379, 'cy': 876, 'conf': 1.0}]
BP._items = lambda bot, reuse=True: _hi
_b3 = B()
_r3 = BP._confirm(_b3, [], 't3')
ck('⑥ ⭐ 高位「确定」(379,876) ⇒ **点到**（没把旧判据改坏 ✓）',
   (379, 876) in _b3.taps, str(_b3.taps))

BP._items = _orig

print()
print('【4】真机帧复算（`_verify/` 里的真帧 + 真 OCR）')
_P = os.path.join('_verify', 'finish_confirm_dialog_20261002.png')
if not os.path.exists(_P):
    ck('⑦ 有真机确认框帧', False, _P)
else:
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    _img = cv2.imdecode(np.fromfile(_P, dtype=np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite(r'runs\_vc_tmp.png', _img)
    _res2, _ = RapidOCR()(r'runs\_vc_tmp.png')
    _its = [{'text': str(t).strip(),
             'cx': int(sum(q[0] for q in b) / 4),
             'cy': int(sum(q[1] for q in b) / 4),
             'conf': float(c)} for b, t, c in (_res2 or [])]
    _oks = [i for i in _its if i['text'] == '确定']
    _cancels = [i for i in _its if i['text'] == '取消']
    print('     真实 OCR：「确定」%s ｜「取消」%s'
          % ([(i['cx'], i['cy']) for i in _oks],
             [(i['cx'], i['cy']) for i in _cancels]))
    ck('⑦ ⭐ 这帧的真实「确定」在 **cy<=800**（旧判据必漏 ✓ 这就是那个 bug）',
       bool(_oks) and _oks[0]['cy'] <= 800,
       str([(i['cx'], i['cy']) for i in _oks]))
    BP._items = lambda bot, reuse=True: _its
    _b4 = B()
    BP._confirm(_b4, [], 'real')
    ck('⑧ ⭐ 修后**在真帧上点到了**', bool(_b4.taps), str(_b4.taps))
    ck('⑨ ⚠ 真帧上**没点「取消」**',
       all(t != (i['cx'], i['cy']) for t in _b4.taps for i in _cancels))
    BP._items = _orig

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
