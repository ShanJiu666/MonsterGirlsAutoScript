# -*- coding: utf-8 -*-
"""★ 回归：探索槽「已完成」→ 领取，**必须重新取帧**（2026-10-10）

用户报：「**看一下全分辨率测试模拟器的脚本窗口日志，为什么无法正常领取已完成探索**」

⛔ 病：`b.tap(_sd…)` 点了「已完成」后，**没 `b.snap()` 就直接 `b.ocr(band=(700,800))`** ✗
   ⇒ `b.ocr()` 读的是 **`b.img()` = 上一次 snap 的缓存帧**，而 `b.tap()` **不抓帧**
     （实测 `mapbot.Bot.tap` 源码里 `snap` 出现 **0 次** ✓）
   ⇒ 读到的还是**点击之前那张纯棋盘** ⇒ 里面根本没有「领取」按钮 ⇒ 必然读不到 ✗✗

⭐ 铁证（可复算）：`runs/bagdbg/back_miss_175259.png` = 失败时 `b.img()` 落盘的那帧，
   上面「领取」在 **(582,758)**；用**生产口径** `band=(700,800)` 离线跑同一帧
   ⇒ **`(582,758) 领取 conf=1.00`** ✓
   ⇒ **判据/坐标/帧都没问题，唯一的问题是"当时读的不是那一帧"** ✓
"""
import io
import os
import re
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
OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


SRC = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()

print('=' * 90)
print('探索槽领取：必须重新取帧（2026-10-10）')
print('=' * 90)
print()

# ── ① 结构级：`claim_btn` 那次 ocr 之前**必须有 snap** ──────────────
print('【1】结构级：`b.ocr(band=(700,800), tag=\'claim_btn\')` 之前必须有 `b.snap(`')
i = SRC.find("b.ocr(band=(700, 800), tag='claim_btn')")
ck('① 那句 `claim_btn` OCR 还在（没被误删）', i > 0)
head = SRC[max(0, i - 2600):i]
ck('② ⭐ 它**之前**出现了 `b.snap(`（这就是修的那处）',
   'b.snap(' in head,
   '最近 2600 字符内 snap 次数 = %d' % head.count('b.snap('))
# ⚠ 必须确认那个 snap 在**tap 之后**（否则修错位置 ✗）
j_tap = SRC.rfind('b.tap(_sd[0], _sd[1]', 0, i)
j_snap = SRC.rfind('b.snap(', 0, i)
ck('③ 那个 `snap` 在 `tap(_sd…)` **之后**（顺序对 ✓）',
   j_tap > 0 and j_snap > j_tap,
   'tap@%d  snap@%d' % (j_tap, j_snap))

# ── ② 反向：确认 `Bot.tap` 真的不抓帧（这是根因的前提） ────────────
print()
print('【2】前提核实：`mapbot.Bot.tap` **不抓帧**（所以漏 snap 才致命）')
import inspect
import mapbot

_tsrc = inspect.getsource(mapbot.Bot.tap)
ck('④ `Bot.tap` 源码里 `snap` 出现 **0 次**（它不会自己重抓 ✓）',
   _tsrc.count('snap') == 0, '出现 %d 次' % _tsrc.count('snap'))
_isrc = inspect.getsource(mapbot.Bot.img)
ck('⑤ `Bot.img` 是**内存优先**（返回缓存帧 ✓）',
   '_img_arr' in _isrc and 'return self._img_arr' in _isrc)

# ── ③ ⭐ 执行级：拿真机帧验证「判据本身没问题」 ─────────────────────
print()
print('【3】⭐ 执行级：拿失败时那帧验证判据（证明病在"读错帧"不在"判据"）')
P = r'runs\bagdbg\back_miss_175259.png'
if not os.path.exists(P):
    print('     ⚠ 缺取证帧 %s ⇒ 跳过本段（不假装通过 ✗）' % P)
    ck('⑥ 取证帧在（可复算）', False, P)
else:
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    img = cv2.imdecode(np.fromfile(P, dtype=np.uint8), cv2.IMREAD_COLOR)
    band = img[700:800]
    tmp = r'runs\_v_claim_band.png'
    cv2.imwrite(tmp, band)
    res, _ = RapidOCR()(tmp)
    got = [(int(sum(q[0] for q in bx) / 4), int(sum(q[1] for q in bx) / 4),
            str(tx), float(cf)) for bx, tx, cf in (res or [])]
    hit = [g for g in got if '领取' in g[2]]
    print('     `band=(700,800)` 在这帧上的 OCR = %s'
          % [(g[0], g[1], g[2]) for g in got][:5])
    ck('⑥ ⭐ 这帧上**读得到**「领取」（conf≥0.9）⇒ 判据没问题、是读错了帧',
       bool(hit) and hit[0][3] >= 0.9,
       str(hit[:1]))
    ck('⑦ 「领取」的 x 在按钮区（≥500）', bool(hit) and hit[0][0] >= 500,
       str(hit[:1]))

# ── ④ 同类坑计数（本项目第 4 例） ─────────────────────────────────
print()
print('【4】同一个坑的其它三处**都有 snap**（这处是漏网的第 4 例）')
for name, anchor in (('claim_back_poll', 'def claim_back_poll'),
                     ('_tap_verified', 'def _tap_verified')):
    k = SRC.find(anchor)
    if k < 0:
        ck('⑧ `%s` 存在' % name, False)
        continue
    seg = SRC[k:k + 6000]
    ck('⑧ `%s` 里有 `b.snap(`（前 3 例已修 ✓）' % name, 'b.snap(' in seg)

print()
print('=' * 90)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for b in BAD:
    print('   ✗ ' + b)
raise SystemExit(1 if BAD else 0)
