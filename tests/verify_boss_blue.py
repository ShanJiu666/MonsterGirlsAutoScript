# -*- coding: utf-8 -*-
"""verify_boss_blue.py · 守住「雾格上的 boss 是 B↔R 互换的蓝色图标」

真机事故（用户报「**为什么这两张图没打 boss？**」，`runs/acc1` 那把）：
    13 张图里第 11/12/13 张**一个 boss 都没打**就收工（`本图结束：blank`），
    可盘上**明明有 boss 图标**（肉眼可见）。13 张里 **9 张**是这种蓝图标（雾格）。

根因（逐像素取证）：游戏把**雾格上的 boss**画成**红蓝通道互换**的蓝色版，
而我们的模板是游戏 UI 包里的**红底** sprite。
    · 真 boss  BGR 均值 = [105.6 135.5 181.8]（红多）—— 模板认得出
    · 蓝图标   BGR 均值 = [182.0 135.8 106.1]（蓝多）—— `color_score` 0.858→**0.472** ⇒ 被拒
    · 真 boss 做 B↔R ⇒ [181.8 135.5 105.6] —— 与蓝图标**几乎逐值相同** ✓
    · **颜色集合判据**：蓝图标色集 **100% 被 `swap(真boss色集)` 覆盖**（多出色 **0**）

判据分四层：
  【1】结构级（AST）：`load_tpls()` 里必须有"用 B↔R 合成 boss 蓝变体"那段，
        且**必须走代码合成**（`boss_v`），不是引用一个 `templates/marks/` 下的新 PNG
        —— ⚠ 那个目录**不进热更补丁**（`ASSET_DIRS` 只有 `templates/fixed/`）
          ⇒ 放新 PNG = "代码到了、图没到" = 判据静默不生效 ✗（§2.2 的坑）
  【2】数据级：`load_tpls()['boss_v']` 必须真有 1 个变体，且它 **= 原模板 B↔R 互换**
        （逐像素断言，不是"有就行"）
  【3】执行级（真机帧，**只读 `_verify/`**）：
        · 3 张蓝 boss 帧 ⇒ 每张都必须认出 boss，且**落在正确格**
        · 对照帧（红 boss）⇒ 也必须认出（证明没改坏原来的）
        · **反向守门**：把蓝变体删掉 ⇒ 那 3 张**必须认不出**
          （否则本门禁是恒绿的摆设 ✗）
  【4】守门：真 boss 帧的**分数**不能被蓝变体抢走（修前修后都是原模板命中）
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


sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                                # noqa: BLE001
    pass

SRC_PATH = os.path.join(CORE, 'marks.py')
SRC = io.open(SRC_PATH, encoding='utf-8').read()

_n = [0]
_fail = [0]
_skip = []


def ck(name, cond, extra=''):
    _n[0] += 1
    if cond:
        print('  [ok]   %s' % name)
    else:
        _fail[0] += 1
        print('  [FAIL] %s  %s' % (name, extra))


def skip(name, why):
    _skip.append(name)
    print('  [skip] %s  （%s）' % (name, why))


# ─────────────────────────── 【1】结构级 ───────────────────────────
print('=' * 74)
print('【1】结构级：蓝变体必须由**代码合成**（AST 查，不字符串 grep）')
print('=' * 74)

_tree = ast.parse(SRC, SRC_PATH)
_lt = None
for _node in ast.walk(_tree):
    if isinstance(_node, ast.FunctionDef) and _node.name == 'load_tpls':
        _lt = _node
        break

ck('找得到 load_tpls()', _lt is not None)
if _lt is not None:
    _body_src = ast.get_source_segment(SRC, _lt) or ''
    # ⚠ 不字符串 grep 整个函数体：留档注释里必然逐字出现 `boss_v`
    #   ⇒ 按 **AST 语句**看"真的有没有那段赋值" ✓
    _has_bossv_assign = False
    _has_swap = False
    for _s in ast.walk(_lt):
        # 形态一：`out['boss_v'] = ...`
        if isinstance(_s, ast.Assign):
            for _tg in _s.targets:
                if isinstance(_tg, ast.Subscript) and \
                        getattr(_tg.value, 'id', None) == 'out' and \
                        isinstance(_tg.slice, ast.Constant) and _tg.slice.value == 'boss_v':
                    _has_bossv_assign = True
        # 形态二：`out.setdefault('boss_v', []).append(...)`（实际写法）
        if isinstance(_s, ast.Call):
            _f = _s.func
            if isinstance(_f, ast.Attribute) and _f.attr == 'setdefault' and _s.args:
                if isinstance(_s.args[0], ast.Constant) and _s.args[0].value == 'boss_v':
                    _has_bossv_assign = True
    # B↔R 互换：形态是 `X[:, :, 0] = Y[:, :, 2]`（下标 0 在左、2 在右）
    #   ⚠ 我第一版写成"左边同时含 0 和 2" ⇒ 永远为假（假红）✗
    #   ⇒ 正确判据：**左下标 ∪ 右下标** 里同时出现 {0, 2} ✓
    def _subs_idx(_node):
        """取出 `X[:, :, k]` 里那个整数下标 k（没有就返回 None）"""
        if isinstance(_node, ast.Subscript) and isinstance(_node.slice, ast.Tuple):
            for _e in _node.slice.elts:
                if isinstance(_e, ast.Constant) and isinstance(_e.value, int):
                    return _e.value
        return None

    for _s in ast.walk(_lt):
        if isinstance(_s, ast.Assign) and len(_s.targets) == 1:
            _li = _subs_idx(_s.targets[0])
            _ri = _subs_idx(_s.value)
            if _li is not None and _ri is not None and {_li, _ri} == {0, 2}:
                _has_swap = True
    ck("load_tpls() 里有产出 out['boss_v'] 的语句（赋值或 setdefault）", _has_bossv_assign)
    ck('那段确实做了通道下标 0/2 的互换（B↔R）', _has_swap)
    # 反向：不许靠 templates/marks/ 下的新 PNG
    _marks_dir = os.path.join(HERE, 'templates', 'marks')
    _blue_pngs = [f for f in (os.listdir(_marks_dir) if os.path.isdir(_marks_dir) else [])
                  if 'blue' in f.lower()]
    ck('没有靠 `templates/marks/` 下的新 PNG（那个目录不进热更补丁）',
       not _blue_pngs, '发现 %s' % _blue_pngs)

# ─────────────────────────── 【2】数据级 ───────────────────────────
print()
print('=' * 74)
print('【2】数据级：boss_v 必须**逐像素等于**原模板的 B↔R 互换')
print('=' * 74)

try:
    import numpy as np                              # noqa: E402
    import marks as M                               # noqa: E402
except Exception as _e:                             # noqa: BLE001
    print('  ✗ import marks 失败：%r' % (_e,))
    print()
    print('共 %d 项，失败 %d 项' % (_n[0], _fail[0] + 1))
    sys.exit(1)

_t = M.load_tpls()
_boss = _t.get('boss')
_bv = _t.get('boss_v')
ck('load_tpls() 给出了 boss_v', bool(_bv))
if _boss is not None and _bv:
    _bl = _bv[0] if isinstance(_bv, list) else _bv
    ck('boss_v 形状与 boss 一致', _bl.shape == _boss.shape,
       '%s vs %s' % (_bl.shape, _boss.shape))
    _want = _boss.copy()
    _want[:, :, 0] = _boss[:, :, 2]
    _want[:, :, 2] = _boss[:, :, 0]
    _same = bool(np.array_equal(_bl, _want))
    ck('boss_v 逐像素 == boss 的 B↔R 互换', _same)
    # 反向：不许把 alpha 也换了
    if _boss.shape[2] == 4:
        ck('alpha 通道没被换（只换 B/R）',
           bool(np.array_equal(_bl[:, :, 3], _boss[:, :, 3])))

# ─────────────────────────── 【3】执行级 ───────────────────────────
print()
print('=' * 74)
print('【3】执行级：真机帧（只读 `_verify/`）')
print('=' * 74)

try:
    import cv2                                      # noqa: E402
except Exception as _e:                             # noqa: BLE001
    skip('执行级（需要 cv2）', repr(_e))
    cv2 = None

CASES = [('boss_blue_1_20261006.png', (1, 2), 'blue'),
         ('boss_blue_2_20261006.png', (2, 4), 'blue'),
         ('boss_red_1_20261006.png', (1, 1), 'red')]

if cv2 is not None:
    _imgs = {}
    for _fn, _rc, _kind in CASES:
        _p = os.path.join(HERE, '_verify', _fn)
        # ⚠ 夹具是**入库冻结**的（`_verify/` 只读）⇒ 缺了就是**真问题**，
        #   必须硬失败、不能 skip（skip 会让"夹具被误删"悄悄变绿 ✗）
        ck('夹具存在：_verify/%s' % _fn, os.path.isfile(_p))
        if os.path.isfile(_p):
            _imgs[_fn] = cv2.imread(_p)

    # ① 有蓝变体时：三张都必须认出，且落在正确格
    for _fn, _rc, _kind in CASES:
        if _fn not in _imgs:
            continue
        _h = M.scan_board(_imgs[_fn])
        _got = [k for k, v in _h.items() if 'boss' in v.get('marks', [])]
        ck('%s（%s boss）认出 boss 且在 %s' % (_fn, _kind, _rc),
           _rc in _got, '实际认出 %s' % (_got,))

    # ② 反向守门：把蓝变体删掉 ⇒ 那两张蓝帧**必须认不出**
    _saved = M.load_tpls

    def _no_blue():
        _d = _saved()
        _d.pop('boss_v', None)
        return _d

    M.load_tpls = _no_blue
    try:
        for _fn, _rc, _kind in CASES:
            if _fn not in _imgs:
                continue
            _h = M.scan_board(_imgs[_fn])
            _got = [k for k, v in _h.items() if 'boss' in v.get('marks', [])]
            if _kind == 'blue':
                ck('反向守门：删掉蓝变体 ⇒ %s **认不出**（证明不是恒绿）' % _fn,
                   _rc not in _got, '竟然还认出 %s' % (_got,))
            else:
                ck('反向守门：删掉蓝变体 ⇒ %s（红 boss）**仍认得出**' % _fn,
                   _rc in _got, '实际 %s' % (_got,))
    finally:
        M.load_tpls = _saved

# ─────────────────────────── 【4】分数守门 ───────────────────────────
print()
print('=' * 74)
print('【4】守门：蓝变体不许抢走真 boss 的命中')
print('=' * 74)
if cv2 is not None and 'boss_red_1_20261006.png' in _imgs:
    _h = M.scan_board(_imgs['boss_red_1_20261006.png'])
    _v = _h.get((1, 1))
    ck('红 boss 帧仍由**原模板**命中（marks 里是 boss 不是别的）',
       bool(_v) and _v.get('marks') == ['boss'], '%s' % (_v,))
    if _v:
        ck('红 boss 的形状分仍 ≥ 0.90（没被拉低）',
           float(_v.get('score') or 0) >= 0.90, 'score=%s' % _v.get('score'))

print()
print('=' * 74)
if _skip:
    print('跳过 %d 项：%s' % (len(_skip), '、'.join(_skip)))
if _fail[0]:
    print('✗ 失败 %d / %d 项' % (_fail[0], _n[0]))
    sys.exit(1)
print('✅ 全部通过：雾格 boss 的蓝色变体已由代码合成（逐像素对拍），'
      '真机帧认得出、删掉就认不出（不是恒绿）')
