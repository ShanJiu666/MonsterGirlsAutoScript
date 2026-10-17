# -*- coding: utf-8 -*-
"""★ 回归：**预言石碑**在**所有**路径上都必须走 `foretell_flow`（不许被关掉）

用户报（两次）：
  ① 10-10 早：「**图上有预言石碑，试一试**」→ 我改了 `popups()` 那一处
  ② 10-10 晚：「**刚刚综合模拟器那把点开预言窗口就直接关了**」
     ⇒ 真机铁证 `runs/acc1/gui_20261010_203354_acc1.log:85`
        `· 点 (456,1100) 弹出「预言石板」→ 关掉并拉黑这格` ✗
     ⇒ **我只改了 `popups()`，漏了另外 4 处** ✗✗

⚠ 这正是 README 早记过的教训（手机端 v1.63）：
   「**我前几轮一直在修 `popups()` 那条链，而真正吃掉这一格的是
     `final_collect()` 这条完全独立的路径**」
  ⇒ **同一个错又犯了一次** ⇒ 本回归用**AST/静态扫全部调用点**来防它 ✓
"""
import ast
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


SRC = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
LINES = SRC.splitlines()

print('=' * 94)
print('预言石碑：所有路径都必须领掉（2026-10-10）')
print('=' * 94)

# ── ① 共用判据存在 ────────────────────────────────────────────
print()
print('【1】共用判据（治"改了这处漏那处"）')
ck('① 有模块级 `_is_foretell_panel`',
   hasattr(EL, '_is_foretell_panel'))
ck('② 它同时认**方块名**与**面板名**（`预言石碑`/`预言石板`）',
   EL._is_foretell_panel([{'text': '预言石碑'}]) is True
   and EL._is_foretell_panel([{'text': '预言石板'}]) is True)
ck('③ ⚠ **不认**单独的「预言」（`L[\'hud\']` 里有它 ⇒ 会误伤 ✗）',
   EL._is_foretell_panel([{'text': '预言'}]) is False)
ck('④ ⚠ **不认**别的占卜类（`占卜` ⇒ 那些没 flow，仍该关掉 ✓）',
   EL._is_foretell_panel([{'text': '占卜'}]) is False)

# ── ② ⭐ 静态扫：所有 `fb(..., *L['prophecy'])` 判据都必须带守卫 ──
print()
print('【2】⭐ 静态扫：**每一处** `fb(..., *L[\'prophecy\'])` 判据都要带守卫')
# 用 AST 更准：找出所有 `fb(x, *L['prophecy'])` 作为 `if` 条件的表达式
tree = ast.parse(SRC)
bad_sites = []
guarded_sites = []
for node in ast.walk(tree):
    if not isinstance(node, ast.If):
        continue
    for cond in (node.test,):
        txt = ast.get_source_segment(SRC, cond) or ''
        if "L['prophecy']" not in txt:
            continue
        ln = cond.lineno
        # ⭐ 守卫可以出现在条件里（`and not _is_foretell_panel(...)`）
        #   或**在紧邻的上一行**（有人拆成两行写）
        _near = '\n'.join(LINES[max(0, ln - 3):ln + 1])
        has = ('_is_foretell_panel' in txt or '_is_stele' in txt
               or '_is_foretell_panel' in _near or '_is_stele' in _near)
        (guarded_sites if has else bad_sites).append((ln, txt.strip()[:78]))
        break

print('  带守卫的判据 %d 处：' % len(guarded_sites))
for ln, t in guarded_sites:
    print('     ✓ 行%-6d %s' % (ln, t))
print('  ⚠ 无守卫的判据 %d 处：' % len(bad_sites))
for ln, t in bad_sites:
    print('     ✗ 行%-6d %s' % (ln, t))
ck('⑤ ⭐ **全部** `prophecy` 判据都带守卫（`_is_foretell_panel`/`_is_stele` ✓）',
   not bad_sites, '无守卫 %d 处' % len(bad_sites))
ck('⑥ 共找到 **≥4** 处（那 4~5 条独立路径都要覆盖 ✓）',
   len(guarded_sites) >= 4, '实际 %d 处' % len(guarded_sites))

# ── ③ 每条路径都要**领掉**（调 `foretell_flow`），不只是"不关掉" ──
print()
print('【3】那几处旁边必须有 `foretell_flow` 调用（否则只是"不关"，也没领 ✗）')
_n = SRC.count('buypanels.foretell_flow(')
print('     全仓 `buypanels.foretell_flow(` 出现 %d 次' % _n)
ck('⑦ ≥4 处调用（`popups()` / 点击循环 / `finish_map` / `final_collect`×2 ✓）',
   _n >= 4, '%d 次' % _n)

# ── ④ 行为级：拿真机面板帧喂 `popups()` ─────────────────────────
print()
print('【4】⭐ 行为级：真机面板帧 ⇒ `popups()` 必须调 `foretell_flow`（不关掉）')
P = 'runs/acc1/fst_opened.png'
if not os.path.exists(P):
    ck('⑧ 有真机面板帧', False, P)
else:
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    import buypanels as BP
    img = cv2.imdecode(np.fromfile(P, dtype=np.uint8), cv2.IMREAD_COLOR)
    cv2.imwrite(r'runs\_vo_tmp.png', img)
    res, _ = RapidOCR()(r'runs\_vo_tmp.png')
    items = [{'text': str(t), 'conf': float(c),
              'cx': int(sum(q[0] for q in b) / 4),
              'cy': int(sum(q[1] for q in b) / 4)}
             for b, t, c in (res or [])]
    ck('⑧ `_is_foretell_panel` 在这帧上 = True', EL._is_foretell_panel(items) is True)

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
    _called = {'n': 0}
    _orig = BP.foretell_flow

    def _spy(*a, **kw):
        _called['n'] += 1
        return {'acts': None, 'stop': None, 'picked': []}
    BP.foretell_flow = _spy
    try:
        EL.popups(b, items, log, ctx={'flags': {'mapname': '夏日海滩'},
                                      'marks': {}, 'tapped': (456, 716)})
    finally:
        BP.foretell_flow = _orig
    print('     foretell_flow 命中 = %d ｜ 点过 = %s' % (_called['n'], b.taps[:3]))
    ck('⑨ ⭐ `foretell_flow` 被调用（不是 `universal_close` ✓）', _called['n'] >= 1)
    ck('⑩ ⚠ **没有**去点 `universal_close` 那块（360,1260 附近）',
       not any(abs(t[0] - 360) < 30 and t[1] > 1150 for t in b.taps),
       str(b.taps[:4]))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
