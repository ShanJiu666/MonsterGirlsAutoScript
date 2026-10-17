# -*- coding: utf-8 -*-
"""★ 验证 `_vault_tap` 安全区守卫 + 所有宝库常量是否都在安全区内。

要验：
  ① 语法/import 正常
  ② 安全矩形 `VAULT['safe']` 与真机实测面板 bbox 一致
  ③ 每个常量点**是否在安全区内**（不在的会被夹回来 —— 打印出来看是谁）
  ④ `_vault_tap` 对越界点**真的夹回**、对界内点**一字不动**
  ⑤ `blank`/`back` 不再是同一个值的隐患（拆成两个键，但都改对了）
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
import buypanels as BP


FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


print('=' * 78)
print('【①】安全矩形与真机实测面板 bbox')
print('=' * 78)
sx0, sx1, sy0, sy1 = BP.VAULT['safe']
print('  VAULT["safe"] = x[%d,%d] y[%d,%d]' % (sx0, sx1, sy0, sy1))
print('  真机实测面板   = x[39,680]  y[228,1048]   （88 张帧一致）')
ck('安全矩形在面板内（左右各留 ≥10px）',
   sx0 > 39 and sx1 < 680 and sy0 > 228 and sy1 < 1048,
   'x[%d,%d] y[%d,%d]' % (sx0, sx1, sy0, sy1))
ck('安全矩形下边 < 面板底边 1048（★本 bug 的核心：旧 blank 越过了它）',
   sy1 < 1048, 'sy1=%d' % sy1)

print()
print('=' * 78)
print('【②】各常量点是否在安全区内')
print('=' * 78)
PTS = [('VAULT["buy"]', BP.VAULT['buy']),
       ('VAULT["back"]', BP.VAULT['back']),
       ('VAULT["blank"]', BP.VAULT['blank']),
       ('VAULT["x"]', BP.VAULT['x']),
       ('VAULT_RET', BP.VAULT_RET)]
for nm, (x, y) in PTS:
    inside = (sx0 <= x <= sx1) and (sy0 <= y <= sy1)
    ck('%-16s (%4d,%4d) 在安全区内' % (nm, x, y), inside,
       '' if inside else '★越界 ⇒ 会被夹回')
ck('blank 与 back 是**独立键**（不再是同一个表达式）',
   'blank' in BP.VAULT and 'back' in BP.VAULT)
ck('blank 不再是旧的越界值 (440,1060)',
   tuple(BP.VAULT['blank']) != (440, 1060), '现在 = %s' % (BP.VAULT['blank'],))

print()
print('=' * 78)
print('【③】`_vault_tap` 行为：越界夹回 / 界内不动')
print('=' * 78)


class FakeBot:
    def __init__(self):
        self.taps = []

    def tap_dlg(self, x, y, wait=0):
        self.taps.append((int(round(x)), int(round(y))))


b = FakeBot()
log = []
BP._vault_tap(b, 440, 1060, log=log, what='old_blank')
ck('越界点 (440,1060) ⇒ 被夹进安全区', b.taps[-1] != (440, 1060),
   '实际点到 %s' % (b.taps[-1],))
ck('夹回后落在安全区内',
   sx0 <= b.taps[-1][0] <= sx1 and sy0 <= b.taps[-1][1] <= sy1)
ck('记了 `tap_clamped` 日志',
   any(e.get('vault') == 'tap_clamped' for e in log),
   '%s' % ([e.get('vault') for e in log],))

b2 = FakeBot()
log2 = []
for nm, (x, y) in PTS:
    BP._vault_tap(b2, x, y, log=log2, what=nm)
ck('界内的点**一字不动**（5 个常量原样点到）',
   b2.taps == [tuple(p[1]) for p in PTS], '%s' % (b2.taps,))
ck('界内点**不记** tap_clamped（不刷屏 ✓）',
   not any(e.get('vault') == 'tap_clamped' for e in log2))

b3 = FakeBot()
BP._vault_tap(b3, 'abc', None, log=None, what='bad')
ck('非法坐标不崩（退回 blank）', len(b3.taps) == 1, '%s' % (b3.taps,))

print()
print('=' * 78)
print('【④】宝库流程里的 `tap_dlg` 是否都收口到守卫')
print('=' * 78)
src = io.open(os.path.join(CORE, 'buypanels.py'), encoding='utf-8').read()
lines = src.splitlines()
s = next((i for i, l in enumerate(lines) if l.startswith('def vault_flow(')), None)
e = next((i for i, l in enumerate(lines) if i > s and l.startswith('def ')), None)
body = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
n_guard = body.count('_vault_tap(')
n_raw = body.count('bot.tap_dlg(')
print('  vault_flow 里：守卫调用 %d 次 ／ 裸 tap_dlg %d 次' % (n_guard, n_raw))
ck('vault_flow 的宝库点击都走守卫（裸 tap_dlg 应为 0 —— 只剩被守卫内部调用的不算 ✗）',
   n_raw == 0, '裸调用 %d 次' % n_raw)
ck('守卫调用 ≥ 8 处（buy/leave/pick/blank/claim/back/x 都接上了）',
   n_guard >= 8, '%d 处' % n_guard)

print()
print('=' * 78)
if FAILS:
    print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
    raise SystemExit(1)
print('✅ 全部通过：宝库点击一律先夹进面板安全区 ⇒ 物理上点不出面板')
print('   （旧 `blank`(440,1060) 在面板外 12px ⇒ 已修成 (475,391)，且加了结构性守卫 ✓）')
