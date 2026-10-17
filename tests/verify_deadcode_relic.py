# -*- coding: utf-8 -*-
"""★★ 用**正确的方法**验证：面板识别 → `act_on` → 走哪一支

⛔ 我 10-07 的错误测法：直接调 `buypanels.relic_flow()` ⇒ 绕过 `popups()`
   ⇒ 函数跑通了但**生产路径进不去** ✗
✓ 正确测法：**从 `popups()` 入口进**，喂"面板已打开"的 OCR 条目，看它走哪条分支
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
import explore_loop as EL


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 92)
print('勇者之墓 死代码 bug 修复验证（2026-10-10）')
print('=' * 92)

print()
print('【1】`L["act_on"]` 必须含那三个（否则 flow 是死代码）')
for nm in ('勇者之墓', '限时礼包', '预言石碑'):
    ck('① `act_on` 含「%s」' % nm, nm in EL.L['act_on'], str(EL.L['act_on']))
ck('② 商人/宝库**仍在**（没改坏）',
   '旅行商人' in EL.L['act_on'] and '黄金宝库' in EL.L['act_on'])

print()
print('【2】结构级：`act_on` 必须**先于**「无视」分支判定')
_src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
_i_act = _src.find("'act_on':")
_i_use = _src.find("if t not in L['act_on']:")
ck('③ `if t not in L[act_on]` 那句还在（防我误删）', _i_use > 0)
ck('④ 三个名字在 `act_on` 里 ⇒ 不会走「无视」那支', _i_act > 0, '定义在 %d' % _i_act)

print()
print('【3】那三个 `elif` 分支**仍然在**（没被谁删掉）')
# ⚠ 2026-10-10：判据从 `elif t == 'X'` 改成 **`elif 'X' in t`**（按语义分派 ✓）——
#   因为方块名 ≠ 面板名（`限时礼包` vs `限时超值礼包`）⇒ 精确等于会**掉进 else**
#   ⇒ 真机日志实测：**拿旅行商人流程去点预言面板**（买了 4 次！）✗✗
#   ⇒ 断言跟着改成 `in t`，并**反向守住**不许退回精确等于 ✓
for nm in ('勇者之墓', '限时礼包', '预言石碑'):
    ck('⑤ `elif \'%s\' in t:` 在（按语义分派 ✓）' % nm,
       ("elif '%s' in t:" % nm) in _src)
# ⚠⚠ 反向断言**必须先剥掉注释**再查 ——
#   `elif t == 'X':` 这个旧写法在**留档注释里必然逐字出现**（我在解释为什么改它 ✗）
#   ⇒ 直接 grep 会**假红**（本项目第 4 次踩这个坑：v1.62c / v1.67 / v1.68 / 本次 ✓）
_CODE = '\n'.join(ln for ln in _src.splitlines()
                  if not ln.lstrip().startswith('#'))
for nm in ('勇者之墓', '限时礼包', '预言石碑'):
    ck('⑤b ⚠ **代码里**没有退回精确等于 `elif t == \'%s\':`（注释不算）' % nm,
       ("elif t == '%s':" % nm) not in _CODE)
ck('⑥ 三支各自调了对应 flow',
   all(k in _src for k in ('buypanels.relic_flow(', 'buypanels.gift_flow(',
                           'buypanels.foretell_flow(')))

print()
print('【4】⭐ 真跑一遍 `popups()`：喂「英灵使者」面板的 OCR 条目')
# ⛔⛔ 2026-10-10 **修本脚本的假绿**（我自己审计时抓到的 ✗）：
#   原来这里手写了 `{'text': '勇者之墓', ...}` —— 可**真实面板上根本没这三个字** ✗
#   真机取证帧（`runs/spec_dev/relic_panel.png`）实测 OCR 只有 **「英灵使者」** ✓
#   ⇒ 我手写的那条**替被测代码把活干了** ⇒ 测试"通过"而生产路径照样进不去 ✗
#   ⇒ 现在**只留真实面板上确实有的文字**（「英灵使者」+ 按钮），
#     并且**额外加一条反向断言**：只喂「勇者之墓」时**必须走不到** flow
#     （证明"方块名 ≠ 面板名"这个前提是**真的**，不是我编的 ✓）
#   ⚠ 更彻底的做法见 `verify_panel_alias.py`（它用**真实帧 + 真实 OCR** ✓）
PANEL = [
    {'text': '英灵使者', 'cx': 461, 'cy': 302, 'conf': 1.0},
    {'text': '确定', 'cx': 458, 'cy': 960, 'conf': 1.0},
]


class FB:
    """假 bot：只记调用，不真点"""
    dev = '127.0.0.1:16384'

    def __init__(self):
        self.calls = []

    def snap(self, *a, **k):
        self.calls.append(('snap', a[:1]))
        return 'x.png'

    def img(self):
        import numpy as np
        return np.zeros((1280, 720, 3), np.uint8)

    def img_dlg(self):
        return self.img()

    def ocr(self, *a, **k):
        return PANEL

    def tap(self, x, y, wait=0.0):
        self.calls.append(('tap', x, y))

    def tap_dlg(self, x, y, wait=0.0):
        self.calls.append(('tap_dlg', x, y))


b = FB()
log = []
hit_flow = {'relic': 0, 'gift': 0, 'foretell': 0}
_orig = {}
for nm, key in (('relic_flow', 'relic'), ('gift_flow', 'gift'),
                ('foretell_flow', 'foretell')):
    _orig[nm] = getattr(EL.buypanels, nm)

    def _mk(k):
        def _f(*a, **kw):
            hit_flow[k] += 1
            return {} if k != 'relic' else []
        return _f
    setattr(EL.buypanels, nm, _mk(key))
try:
    act = EL.popups(b, PANEL, log, ctx={'flags': {'mapname': '夏日海滩'},
                                        'marks': {}, 'tapped': None})
finally:
    for nm in _orig:
        setattr(EL.buypanels, nm, _orig[nm])

print('     `popups()` 返回 = %r' % (act,))
print('     flow 命中 = %r' % (hit_flow,))
ck('⑦ ⭐ **`relic_flow` 真的被调用了**（这就是 10-07 从没发生的事 ✓）',
   hit_flow['relic'] >= 1, '命中 %d 次' % hit_flow['relic'])
ck('⑧ 没有走「无视 + 盲点 X」那支',
   not any(c[0] == 'tap' and c[1] == 655 for c in b.calls),
   str([c for c in b.calls if c[0] == 'tap'][:4]))

print()
print('=' * 92)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
