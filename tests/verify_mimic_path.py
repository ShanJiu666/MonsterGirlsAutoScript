# -*- coding: utf-8 -*-
"""★ 审计 6：`mimic_flow` 接线后的执行级验证（真实宝箱怪面板帧）

⚠ 又一次要小心**不要手写夹具** ✗（面板标题必须来自真实帧 OCR ✓）
"""
import glob
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
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
import explore_loop as EL
import buypanels as BP


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


# 找真实宝箱怪面板帧
CANDS = (glob.glob('runs/spec_dev/mimic*.png') + glob.glob('runs/sptest/*mimic*.png')
         + glob.glob('runs/**/*mimic*.png', recursive=True)
         + glob.glob('runs/**/mim_opened*.png', recursive=True))
CANDS = [p for p in dict.fromkeys(CANDS) if os.path.exists(p)]
print('=' * 92)
print('宝箱怪接线验证（真实面板帧）')
print('=' * 92)
print('  候选帧 %d 个：%s' % (len(CANDS), [os.path.basename(p) for p in CANDS[:6]]))
print()

if not CANDS:
    print('  ⚠ 没有宝箱怪取证帧 ⇒ **如实报告跳过**（不假装通过 ✗）')
    ck('① 有真实宝箱怪面板帧可测', False)

P = None
for p in CANDS:
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    tmp = r'runs\_a6.png'
    cv2.imwrite(tmp, img)
    res, _ = RapidOCR()(tmp)
    items = [{'text': str(t), 'conf': 0.9, 'cx': 0, 'cy': 0} for _b, t, _c in (res or [])]
    if EL.fb(items, '金属宝箱怪') or EL.fb(items, '机巧宝箱怪'):
        P = p
        break

if P:
    print('  用帧 = %s' % P)
    img = cv2.imdecode(np.fromfile(P, dtype=np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite(r'runs\_a6.png', img)
    res, _ = RapidOCR()(r'runs\_a6.png')
    items = [{'text': str(t), 'conf': float(c),
              'cx': int(sum(q[0] for q in b) / 4), 'cy': int(sum(q[1] for q in b) / 4)}
             for b, t, c in (res or [])]
    print('  OCR = %s' % [i['text'][:14] for i in items][:10])

    class FB:
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

    b = FB()
    log = []
    called = {'n': 0}
    _orig = BP.mimic_flow

    def _spy(*a, **kw):
        called['n'] += 1
        return {'acts': [], 'bought': [], 'skip': 'test'}
    BP.mimic_flow = _spy
    try:
        act = EL.popups(b, items, log,
                        ctx={'flags': {'mapname': '夏日海滩'}, 'marks': {},
                             'tapped': (72, 716)})
    finally:
        BP.mimic_flow = _orig
    print('  `popups()` = %r ｜ mimic_flow 命中 = %d ｜ 点过 = %s'
          % (act, called['n'], b.taps[:3]))
    print('  日志 = %s' % [str(e)[:70] for e in log][:3])
    ck('② ⭐ `mimic_flow` **被调用了**（接线生效 ✓）', called['n'] >= 1)
    ck('③ ⚠ 没有走"无视 + 盲点 X"', not any(t[0] in (655, 329, 683) for t in b.taps))
else:
    print('  ⚠ 没找到含「金属宝箱怪/机巧宝箱怪」的真实面板帧')

print()
print('【结构级】`act_on` 含两个宝箱怪 + `popups` 有对应分支')
_src = io.open('explore_loop.py', encoding='utf-8').read()
ck('④ `act_on` 含金属/机巧宝箱怪',
   '金属宝箱怪' in EL.L['act_on'] and '机巧宝箱怪' in EL.L['act_on'],
   str(EL.L['act_on']))
ck('⑤ `popups()` 里有 `elif \'宝箱怪\' in t:` 分支并调用 `mimic_flow`',
   "elif '宝箱怪' in t:" in _src and 'buypanels.mimic_flow(' in _src)
ck('⑥ ⚠ 用**语义**判（`in t`）而不是精确等于（别名/全称都接得住 ✓）',
   "elif t == '宝箱怪'" not in _src)

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
