# -*- coding: utf-8 -*-
"""★★ 真机面板帧回归：**三个特殊面板都必须走到自己的 flow**（2026-10-10）

用户报：「**刚刚那场没能正确点击勇者之墓，导致卡死**」
        「**图上有预言石碑，试一试**」
        ＋ 我审计时又抓到「限时礼包」有同一个病 ✗

⛔ 病（同一族，**三个全中**）：面板标题与方块名不同，
   而 `for t in L['special']` 只列了**方块名** ⇒ `fb()` 匹配不上 ⇒
   面板被「无视」支 `close_x_panels` + 盲点 X 关掉 ⇒ **对应 flow 永远跑不到** ✗

| 方块名（数据表） | 面板标题（真机 OCR） | 修法 |
|---|---|---|
| 预言石碑 | 预言石板 | 加进 `special` + `SPECIAL_ALIAS` |
| 勇者之墓 | **英灵使者** | 同上 |
| 限时礼包 | **限时超值礼包** | 同上 |

⚠⚠⚠ **本回归的口径（我前几轮栽过两次，这次必须守住）**：
   ① 条目**必须来自真实面板帧 + 真实 OCR** —— 不许手写 ✗
      （我 `verify_deadcode_relic.py` 手写了「勇者之墓」，可真实面板上没这三个字
        ⇒ **假绿** ✗）
   ② 必须**从 `popups()` 入口进** —— 不许直接调 flow ✗
      （绕过 `popups()` 就测不到"生产路径进不进得去" ✓）
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


def real_items(path):
    """**真实面板帧**的 OCR 条目（生产同引擎 ✓）—— 绝不手写 ✗"""
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    tmp = r'runs\_vtmp.png'
    cv2.imwrite(tmp, img)
    res, _ = RapidOCR()(tmp)
    return [{'text': str(t), 'conf': float(c),
             'cx': int(sum(q[0] for q in b) / 4), 'cy': int(sum(q[1] for q in b) / 4)}
            for b, t, c in (res or [])], img


class FakeBot:
    dev = '127.0.0.1:16384'

    def __init__(self, img):
        self._img = img
        self.taps = []

    def snap(self, *a, **k):
        return 'x.png'

    def img(self):
        return self._img

    def img_dlg(self):
        return self._img

    def ocr(self, *a, **k):
        return []

    def tap(self, x, y, wait=0.0):
        self.taps.append((x, y))

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))


print('=' * 92)
print('真机面板帧回归：三个特殊面板都要走自己的 flow')
print('=' * 92)

# ⭐ 三个面板的**真实取证帧**（缺了就如实报 ✗，不假装过）
CASES = [
    ('预言石碑', 'runs/acc1/fst_opened.png', 'foretell_flow', 'foretell'),
    ('勇者之墓', 'runs/spec_dev/relic_panel.png', 'relic_flow', 'relic'),
    ('限时礼包', 'runs/spec_dev/gift_free1.png', 'gift_flow', 'gift'),
]

print()
print('【1】⭐ 真实帧上：方块名 `/` 面板名 各读不读得到')
for label, path, flow, key in CASES:
    if not os.path.exists(path):
        ck('① 「%s」有真实取证帧' % label, False, path)
        continue
    items, img = real_items(path)
    txts = [i['text'] for i in items]
    print('     ── %s  %s ──' % (label, os.path.basename(path)))
    print('        OCR: %s' % [t[:12] for t in txts[:8]])
    # 面板名必须命中
    _alias = [k for k, v in EL.SPECIAL_ALIAS.items() if v == label]
    _panel_hit = any(EL.fb(items, a) for a in _alias)
    ck('② 「%s」的面板名 %s 在真实帧上**读得到**' % (label, _alias),
       _panel_hit)

print()
print('【2】⭐⭐ 从 `popups()` 入口进 ⇒ 对应 flow **必须被调用**')
for label, path, flow, key in CASES:
    if not os.path.exists(path):
        continue
    items, img = real_items(path)
    b = FakeBot(img)
    log = []
    called = {'n': 0}
    _orig = getattr(BP, flow)

    def _mk(orig_f):
        def _f(*a, **kw):
            called['n'] += 1
            return {} if key != 'relic' else []
        return _f
    setattr(BP, flow, _mk(_orig))
    try:
        act = EL.popups(b, items, log,
                        ctx={'flags': {'mapname': '夏日海滩'}, 'marks': {},
                             'tapped': (456, 716)})
    finally:
        setattr(BP, flow, _orig)
    print('     ── %s ⇒ popups=%r  flow 命中=%d  点过=%s ──'
          % (label, act, called['n'], b.taps[:3]))
    print('        日志: %s' % [str(e)[:70] for e in log][:3])
    ck('③ ⭐ 「%s」的 `%s` **被调用了**' % (label, flow), called['n'] >= 1)
    ck('④ ⚠ 「%s」**没有**走"无视 + 盲点 X"' % label,
       not any(t[0] in (655, 329, 683) for t in b.taps))

print()
print('【3】`SPECIAL_ALIAS` 三个别名都在（治本表 ✓）')
for _p, _c in (('预言石板', '预言石碑'), ('英灵使者', '勇者之墓'),
               ('限时超值礼包', '限时礼包')):
    ck('⑤ `%s` → `%s`' % (_p, _c), EL.SPECIAL_ALIAS.get(_p) == _c)
ck('⑥ 三个面板名都在 `L[\'special\']` 里（否则 `fb` 扫不到）',
   all(a in EL.L['special'] for a in EL.SPECIAL_ALIAS))

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
