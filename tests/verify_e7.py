# -*- coding: utf-8 -*-
"""★ E7 回归（掩膜虚高 ⇒ 同名局部替换）—— 独立可跑，退出码 0/1

背景（用户报「综合连派 3 支探索队」，2026-10-08）：
  `S00003_103 游乐设施`(2格, 非紫金) 被认成 `S00003_221 游乐设施`(5格, **紫金**)
  ⇒ 走「探索+派遣」⇒ 派小队去打本该打的格 ✗
根因：`221` 走**掩膜通道**（alpha 不满 ⇒ 只比 70.1% 像素）⇒ 分数虚高，
      与 `103` 的**矩形分不是一个量纲** ⇒ 0.747 压过 0.606

真值（**用户人眼确认**，3 格）：
  r_151015_0.png 格 3,2 = 103
  r_152100_0.png 格 2,1 = 103
  r_151634_0.png 格 4,5 = **202**（这一格是"不许动"的反例 ✓）

本回归：
  ① 三张真机帧上，`state()` 必须给出真值
  ② E7 关掉 ⇒ **必须复现旧行为**（证明不是恒绿）
  ③ E7 只动那 2 帧（影响面）—— 拿语料算，超阈值就红

⭐⭐ 性能（2026-10-08 用户问「为什么这么慢？不能多并发快点跑吗」）：
  · `Board()` 每次重载 79 个模板 PNG = **0.11s** ⇒ **按地图码缓存** ✓
  · `state()` = 0.55s，其中 `scores()` = 0.27s（**与 E7 开关无关**）
    ⇒ 一帧跑两遍（开/关）时 `scores` **只算一次** ✓
  · 180 帧 **多进程并发**（`ProcessPoolExecutor`，默认 min(8, CPU)）✓
  ⇒ 实测 4 分钟 → **约 15 秒**
"""
from __future__ import annotations

import glob
import json
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
import time
from concurrent.futures import ProcessPoolExecutor

os.chdir(ROOT)
sys.path.insert(0, ROOT)
# ⚠ Windows 默认控制台是 GBK，本文件的输出含 ⇒ / ✓ 等字符 ⇒ 会 UnicodeEncodeError 崩掉
#   （门禁父进程会设 PYTHONIOENCODING=utf-8，但**单跑**时没人设 ⇒ 必须自己兜住）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:               # noqa: BLE001
    pass

import cv2                      # noqa: E402
import numpy as np              # noqa: E402
import spots as SP              # noqa: E402


_T0 = time.perf_counter()
OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料）⇒ **响亮地跳过**，绝不记成 [ok]。

    ⚠ 本仓是公开发布版，**不含**开发者的真机录屏语料（那是本地私有数据）。
      没有语料时这里必须**明确报出来**，而不是把断言悄悄放过，
      也不能把它算成失败 —— 那不是代码问题。
    """
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


TRUTH = [
    ('runs/acc1/r_151015_0.png', 'S00003', (3, 2), '103'),
    ('runs/acc1/r_152100_0.png', 'S00003', (2, 1), '103'),
    ('runs/acc3/r_151634_0.png', 'S20003', (4, 5), '202'),
]
MAP2CODE = {'夏日海滩': 'S00003', '枯木丛林': 'S20003', '废弃矿洞': 'S30001',
            '铁血高地': 'S40001'}

# ⭐ 按地图码缓存 Board（只读模板 ⇒ 可安全复用 ✓）
_BOARDS = {}
_ORIG_SCORES = {}       # id(bd) -> 原始绑定方法（防无限递归 ✗ 踩过两次）


def _board(code):
    if code not in _BOARDS:
        _BOARDS[code] = SP.Board(code)
    return _BOARDS[code]


def _one_frame(path, code):
    """跑一帧的 E7 开/关两遍，-> (是否真的改了, 改了几格)

    ⛔⛔ **不许用 `id(img)` 当缓存键** —— ndarray 回收后 id 会**复用**，
       可能把别的帧的分数当本帧的 ⇒ **静默错判** ✗✗
       （第一版就这么写：180 帧只命中 48 条 = id 被复用的铁证，结果碰巧对纯属运气）
    ⇒ 用**闭包持一份**：本帧算一次，两遍共用，出函数即丢 ✓
    """
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return (False, 0)
    bd = _board(code)
    orig = _ORIG_SCORES.setdefault(id(bd), bd.scores)
    sc = orig(img, topn=SP.STATE_TOPN)          # ← 本帧只算这一次 ✓
    _before = bd.scores
    bd.scores = lambda *_a, **_k: sc
    try:
        SP._E7_ON = False
        s0 = bd.state(img)
        SP._E7_ON = True
        s1 = bd.state(img)
    finally:
        bd.scores = _before
    nd = 0
    for cell in set(s0) | set(s1):
        a = str((s0.get(cell) or {}).get('sid') or '')
        b = str((s1.get(cell) or {}).get('sid') or '')
        if a != b:
            nd += 1
    return (nd > 0, nd)


def _worker(args):
    """多进程工作单元（**模块级** ⇒ 可 pickle ✓）"""
    path, code = args
    try:
        changed, nd = _one_frame(path, code)
        return (os.path.basename(path), changed, nd, '')
    except Exception as e:      # noqa: BLE001
        return (os.path.basename(path), False, 0, repr(e)[:80])


def _st(path, code, on):
    """单帧（给真值检查用；Board 复用 ✓）"""
    SP._E7_ON = bool(on)
    p = os.path.join(HERE, path.replace('/', os.sep))
    if not os.path.exists(p):
        return None
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    bd = _board(code)
    orig = _ORIG_SCORES.setdefault(id(bd), bd.scores)
    sc = orig(img, topn=SP.STATE_TOPN)
    _before = bd.scores
    bd.scores = lambda *_a, **_k: sc
    try:
        return bd.state(img)
    finally:
        bd.scores = _before


def _corpus():
    """收集语料（含 3 张显式补的坏帧）"""
    LOGS = sorted(glob.glob(os.path.join(HERE, 'runs', '*', 'loop', 'loop_log.json'))
                  + glob.glob(os.path.join(HERE, 'runs', 'loop', 'loop_log.json')))
    recs = []
    for lg in LOGS:
        try:
            d = json.load(open(lg, encoding='utf-8'))
        except Exception:       # noqa: BLE001
            continue
        if not isinstance(d, list):
            continue
        cm, pend = None, None
        for e in d:
            if not isinstance(e, dict):
                continue
            if e.get('note') == '进图首帧锁定图名 ✓':
                cm = e.get('mapname')
            if 'file' in e and str(e['file']).endswith('_0.png'):
                pend = e['file']
            if 'board' in e and e.get('round') == 0 and pend:
                p = os.path.normpath(os.path.join(os.path.dirname(lg), '..', pend))
                if os.path.exists(p) and cm:
                    recs.append((p, cm))
                pend = None
    # ⚠⚠ `loop_log.json` 那份语料**不含**出问题的那两张帧（它们来自 gui 日志另一轮）
    #   ⇒ 必须**显式补进来** ✓ 否则 ⑧⑨ 会"看着通过"（影响 0 帧 ⊂ ≤3 帧），
    #     **实际没测到改动** ✗ ← 我第一版就是这样（补了 ⑪ 反向守门才堵住）
    for _p, _mp in ((r'runs\acc1\r_151015_0.png', '夏日海滩'),
                    (r'runs\acc1\r_152100_0.png', '夏日海滩'),
                    (r'runs\acc3\r_151634_0.png', '枯木丛林')):
        _full = os.path.join(HERE, _p)
        if os.path.exists(_full):
            recs.append((_full, _mp))
    seen, uniq = set(), []
    for p, mp in recs:
        if p in seen:
            continue
        seen.add(p)
        uniq.append((p, mp))
    return uniq


def main():
    print('=' * 74)
    print('E7 回归：掩膜虚高 ⇒ 同名局部替换')
    print('=' * 74)
    print()

    # ── ① 开关与常量在位 ──────────────────────────────────
    ck('① `spots._E7_ON` 存在且**默认开**', getattr(SP, '_E7_ON', None) is True)
    ck('② `spots._E7_GAP` 存在且 = 0.20',
       abs(float(getattr(SP, '_E7_GAP', 0)) - 0.20) < 1e-9,
       'GAP=%s' % getattr(SP, '_E7_GAP', None))
    ck('③ `Board._e7_fix_same_name` 在', hasattr(SP.Board, '_e7_fix_same_name'))
    ck('④ `Board._is_mask_sid` 在', hasattr(SP.Board, '_is_mask_sid'))

    # ── ② 真值：E7 开 ⇒ 全对 ─────────────────────────────
    print()
    # ⚠ 公开发布版**不含**真机录屏语料 ⇒ 缺帧时**响亮跳过**（不是失败、也不是假绿）
    _have = [t for t in TRUTH
             if os.path.exists(os.path.join(HERE, t[0].replace('/', os.sep)))]
    if not _have:
        skip('⑤⑥⑦ 真值三格核对（E7 开/关对照）',
             '缺真机语料 runs/acc1|acc3/*.png（发布版不带私有录屏）⇒ 未真正验证')
        n_ok = n_bad = 0
    else:
        n_ok = n_bad = 0
        for path, code, cell, tr in TRUTH:
            s = _st(path, code, True)
            if s is None:
                ck('⑤ 帧可读 %s' % os.path.basename(path), False, '文件缺失')
                continue
            got = str((s.get(cell) or {}).get('sid') or '').split('_')[-1]
            good = (got == tr)
            n_ok += good
            n_bad += (not good)
            ck('⑤ 真值 %s 格 %d,%d = %s（实际 %s）'
               % (os.path.basename(path), cell[0], cell[1], tr, got or '?'), good)
        ck('⑥ **三格真值全对**（E7 开）', n_bad == 0 and n_ok == 3,
           '✓%d ✗%d' % (n_ok, n_bad))

    # ── ③ E7 关 ⇒ 复现旧行为（不是恒绿）────────────────────
    print()
    if not _have:
        skip('⑦ E7 关掉后必须复现旧行为', '同上：缺语料 ⇒ 未真正验证')
    else:
        old_wrong = 0
        for path, code, cell, tr in TRUTH:
            s = _st(path, code, False)
            if s is None:
                continue
            got = str((s.get(cell) or {}).get('sid') or '').split('_')[-1]
            if got != tr:
                old_wrong += 1
        ck('⑦ E7 **关**时至少 2 格判错（证明开关真的在起作用，不是恒绿）',
           old_wrong >= 2, '关掉后仍错 %d 格' % old_wrong)

    # ── ④ 影响面（**多进程并发**）──────────────────────────
    print()
    recs = _corpus()
    jobs = []
    for p, mp in recs:
        code = MAP2CODE.get(mp)
        if code:
            jobs.append((p, code))
    NW = max(1, min(8, (os.cpu_count() or 4)))
    print('  语料 %d 帧 ⇒ 并发 %d 进程跑…' % (len(jobs), NW))
    t1 = time.perf_counter()
    touched, ndiff, errs = set(), 0, []
    if jobs:
        with ProcessPoolExecutor(max_workers=NW) as ex:
            for nm, changed, nd, err in ex.map(_worker, jobs, chunksize=4):
                if err:
                    errs.append((nm, err))
                if changed:
                    touched.add(nm)
                ndiff += nd
    print('  并发跑完 %.1f 秒' % (time.perf_counter() - t1))
    print()
    print('  语料 %d 帧（含 3 张显式补的坏帧）｜ E7 影响 %d 帧 ｜ 改判 %d 格'
          % (len(jobs), len(touched), ndiff))
    # ⚠ 公开发布版不含私有录屏语料 ⇒ 影响面统计**无法复现** ⇒ 响亮跳过
    if len(jobs) < 3:
        skip('⑧⑨⑪⑫⑬ E7 影响面统计（≤3 帧 / ≤14 格）',
             '缺真机语料（发布版不带私有录屏，实测 %d 帧）⇒ 未真正验证' % len(jobs))
    else:
        ck('⑧ E7 影响面**极少**（≤ 3 帧，实测 2）', len(touched) <= 3,
           '影响：%s' % sorted(touched))
        ck('⑨ E7 改判格数**很少**（≤ 14，实测 10）', ndiff <= 14, '%d 格' % ndiff)
        # ⭐ 反向守门：必须**真的动了**那 2 张坏帧（否则 ⑧⑨ 是空的假绿 ✗）
        ck('⑪ E7 确实改动了那 2 张坏帧（**防假绿**）',
           'r_151015_0.png' in touched and 'r_152100_0.png' in touched,
           'touched=%s' % sorted(touched))
        # ⚠⚠ 2026-10-09 **阈值从 150 降到 60**（不是放宽断言，是原来的**前提就是错的**）
        #   根因：语料里的大头 `runs/loop/loop_log.json`（约 178 条）是**滚动覆盖**的
        #     —— 它**只保留当前那一局**，跑完就被下次覆盖/占住 ✗
        #   ⇒ 断言「≥150 帧」实际上在断言"**今天跑了够多局**" ⇒ **脆的** ✗
        #     （实测：一次掉到 142 就假红，而代码一行没改 ✓）
        #   ⇒ 门禁要保的是"**有足够多样的语料能验证影响面**"，60 条已远超需要 ✓
        #     （E7 的实际影响面只 2 帧 / 10 格 —— 语料再多也只是加强结论，不影响判定 ✓）
        ck('⑫ 语料规模**够跑**（≥ 60 帧，滚动日志不保证更多）',
           len(jobs) >= 60, '%d 帧' % len(jobs))
        # ⭐ ⑬ 不许有静默失败（本项目反复栽在 `except: pass` 上 ⇒ 必须可观测 ✓）
        ck('⑬ 全语料**零异常**（不是一个无声的兜底）', not errs,
           'errs=%s' % errs[:2])
    ck('⑭ E7 自身的错误计数为 0（`spots._E7_ERR`）',
       int(getattr(SP, '_E7_ERR', 0) or 0) == 0,
       '_E7_ERR=%s last=%s' % (getattr(SP, '_E7_ERR', None),
                               getattr(SP, '_E7_ERR_LAST', '')))

    SP._E7_ON = True
    print()
    print('  总耗时 %.1f 秒（Board 缓存 %d 个地图码，并发 %d）'
          % (time.perf_counter() - _T0, len(_BOARDS), NW))
    print('=' * 74)
    print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
    for b in BAD:
        print('   ✗ ' + b)
    if SKIP:
        print('   ⚠ 以下 %d 项**没真正验证**（缺真机语料，非代码问题）：' % len(SKIP))
        for s in SKIP:
            print('     - ' + s)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
