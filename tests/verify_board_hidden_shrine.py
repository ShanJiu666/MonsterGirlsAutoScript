# -*- coding: utf-8 -*-
"""★ 回归：`board_hidden()` 必须认出**传承祭坛面板**（2026-10-11「无法正确点击传承祭坛」）

⛔ 病：阈值 `n >= 15` 太高 ⇒ 祭坛面板帧算出 `n = 14` ⇒ **差 1** ✗
   ⇒ `board_hidden` 返回 False ⇒ `_need_ocr = False` ⇒ `ocr: skip_no_panel`
   ⇒ **整轮免 OCR + 连 `popups()` 都不调** ⇒ `shrine_flow` **永远没机会跑** ✗✗

真机铁证 `runs/acc3/gui_20261011_164317_acc3.log`：
    · 点 (72,716) → 弹面板        ← 面板**真的弹出来了**
    · 无面板 ⇒ 本轮免 OCR          ← 下一轮却判"没面板"⇒ 跳过 ✗

⚠ 这是**同一 bug 家族的第四次**：代码 `:11479` 早记着**宝库版**的同一现象，
  而当时的修法是"只给宝库开捷径"（治标）⇒ 祭坛又栽在同一个地方 ✓
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
import explore_loop as EL


OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料）⇒ **响亮地跳过**（不算通过、也不算失败）。

    ⚠ 公开发布版**不含**开发者的真机录屏语料（本地私有数据）。
    """
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


def bh(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    if im is None or im.shape[:2] != (1280, 720):
        return None
    return EL.board_hidden(EL.cells_of(im, '废弃矿洞'))


def ndim(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    c = EL.cells_of(im, '废弃矿洞')
    _st = c.get('st') or {}
    rs = [float((v or {}).get('ratio') or 0) for v in _st.values()]
    mx = max(rs) if rs else 0.0
    thr = min(0.55, 0.55 * mx) if mx > 0 else 0.55
    return len([r for r in rs if r < thr])


print('=' * 94)
print('`board_hidden()` 认出传承祭坛面板（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
_src = io.open('explore_loop.py', encoding='utf-8').read()
_code = '\n'.join(l for l in _src.splitlines() if not l.lstrip().startswith('#'))
ck('① 阈值不再是写死的 15', 'n >= 15' not in _code)
ck('② 用了 `_DIM_N_MIN` 常量', '_DIM_N_MIN' in _code)
ck('③ 阈值 ≤ 10（必须低于祭坛实测的 14 ✓）',
   '_DIM_N_MIN = 6' in _code, '_DIM_N_MIN = 6')

print()
print('【2】⭐⭐ 行为级：真机帧（生产口径）')
_P = r'_verify\shrine_panel.png'
if not os.path.exists(_P):
    ck('④ 有祭坛面板帧', False, _P)
else:
    _n = ndim(_P)
    _b = bh(_P)
    print('     祭坛面板帧：n = %d ｜ board_hidden = %s' % (_n, _b))
    ck('④ ⭐⭐ 祭坛面板帧 **n <= 14**（修前卡在阈值 15 之下 ✗）', _n <= 14, str(_n))
    ck('⑤ ⭐⭐ `board_hidden` = **True**（修前 False ⇒ 跳过 OCR ✗）',
       _b is True, str(_b))

print()
print('【3】⭐ 其它面板也要认得出（同一判据一起受益 ✓）')
# ⚠ 用**绝对路径**：相对路径在门禁不同 cwd 下会找不到 ✗（我第一版就假红了一次 ✓）
_HERE = ROOT          # ⚠ 迁到子目录后：相对资源以仓根为基准
for _p, _nm in ((os.path.join(_HERE, '_verify', 'finish_confirm_dialog_20261002.png'),
                 '结束冒险确认框'),
                (os.path.join(_HERE, 'runs', 'acc3', 'shrine_panel_r-1.png'),
                 '祭坛面板(原始)'),
                (os.path.join(_HERE, '_verify', 'shrine_confirm_synth.png'),
                 '合成确认框')):
    if not os.path.exists(_p):
        # ⚠ 缺的是**私有真机语料**时 ⇒ 响亮跳过；缺仓内 fixture 才算失败
        _inrepo = os.path.join(_HERE, '_verify')
        if os.path.commonpath([os.path.abspath(_p), os.path.abspath(_HERE)]) \
                and _p.startswith(os.path.join(_HERE, 'runs')):
            skip('⑥ %s' % _nm,
                 '缺真机语料 %s（发布版不带私有录屏）⇒ 未真正验证'
                 % os.path.relpath(_p, _HERE))
        else:
            ck('⑥ %s' % _nm, False, '缺文件 %s' % _p)
        continue
    _b = bh(_p)
    print('     %-22s n=%-3d ⇒ board_hidden=%s' % (_nm, ndim(_p), _b))
    ck('⑥ %s ⇒ True（会 OCR ✓）' % _nm, _b is True, str(_b))

print()
print('【4】⚠⚠ 反向：**干净棋盘不许误报**（否则每轮都白跑一次 OCR ✗）')
_cs = sorted(glob.glob('runs/acc1/r_1*.png'))[:40]
_tr = 0
_n = 0
for _p in _cs:
    _v = bh(_p)
    if _v is None:
        continue
    _n += 1
    _tr += 1 if _v else 0
print('     %d 个干净帧：判"被挡" %d 个' % (_n, _tr))
if _n == 0:
    skip('⑦⑧ 干净棋盘不误报（反向守门）',
         '缺真机语料 runs/acc1/r_1*.png（发布版不带私有录屏）⇒ 未真正验证')
else:
    ck('⑦ ⚠ 干净棋盘 **一个都不许误报**', _tr == 0, '%d/%d' % (_tr, _n))
    ck('⑧ 样本量足够（≥20 帧 ✓）', _n >= 20, str(_n))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
for x in BAD:
    print('   ✗ ' + x)
if SKIP:
    print('   ⚠ 以下 %d 项**没真正验证**（缺真机语料，非代码问题）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.stdout.flush()
os._exit(1 if BAD else 0)
