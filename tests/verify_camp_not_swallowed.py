# -*- coding: utf-8 -*-
"""★ 回归：**本格有确定身份 ⇒ 不许被误判的多格块覆盖**（2026-10-12）

用户原话：「**又出现把营地框进去成战斗格子的了**」
            ＋（上一轮）「**把营地和附近两格合体成多格了，营地不可能是战斗格啊**」

⛔ 病（真机铁证 `runs/r_194934_0.png`，夏日海滩）：
   假块 `sid=S00003_211 巨大沙堡`、**块分只有 0.361**、`anchor=(1,2)`、
   `cells=[(1,2),(2,2),(2,3),(2,4)]`；
   而成员格**自己的 top1**：`1,2`=**0.998 草地**、`2,2`=**1.000 营地**、
   `2,3`=**0.998 草地**、`2,4`=**0.994 草地**
   ⇒ 旧代码 `if blk: eff = blk['sid']` **无条件覆盖** ✗
   ⇒ **营地（Size=1 / SP=1 / 非战斗）被改判成「巨大沙堡」（Size=4 / 4-4 / 战斗）** ✗✗
   ⇒ 下游把它那一圈画成一整块、还按战斗格计价 ✓

⭐ 判据（全量 60 帧 221 块实测，`_tmpman/chk_gap.py`）：
     `gap = min(成员 top1) - 块分`
       **真块 gap == 0.000**（成员 top1 恰等于块分）⇒ 216/221
       **假块 gap = +0.63/+0.63/+0.63/+0.41/+0.37** ⇒ 5 个（2.3%）
     ⚠ 0.00 → 0.37 之间**一片空白**（双峰）⇒ 阈值不敏感 ✓
   规则：任一成员格满足 `top1 >= 0.85` **且** `top1 - 块分 > 0.20` ⇒ 整块不采纳 ✓
"""
import importlib
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
import spots


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


_S = io.open('spots.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _S.splitlines() if not l.lstrip().startswith('#'))
rows = spots.spot_rows() or {}

print('=' * 94)
print('本格有确定身份 ⇒ 不许被误判多格块覆盖（2026-10-12）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `_blk_ok` 闸门', '_blk_ok' in _CODE)
# ⚠ 2026-10-14：判据从**相对量**（`>=0.85` 且 `- 块分 > 0.20`）换成
#   **绝对量**（只看本格 top1 `>=0.85`）—— 用户口径：
#   「**能不能按空出来的方块形状猜测**」⇒ 详见 `verify_block_shape.py` ✓
ck('② 形状判据用**绝对量** `>= 0.85`（本格自成一体 ⇒ 弃块 ✓）',
   'float(_l0[0][0]) >= 0.85' in _CODE)
ck('③ ⚠ `owner[k] = b` 在 `if _blk_ok:` 里（**不再无条件**）',
   'if _blk_ok:' in _CODE and _CODE.count('owner[k] = b') == 1,
   '出现 %d 次' % _CODE.count('owner[k] = b'))
ck('④ 商人/宝库那条守卫**还在**（没被误删 ✓）',
   '_is_strong_buy' in _CODE)

print()
print('【2】⭐⭐ 执行级：真机那帧的营地')
_P = os.path.join('runs', 'r_194934_0.png')
_in_repo_frame = os.path.exists(_P)
if not _in_repo_frame:
    # ⚠ 公开发布版**不含**开发者私有录屏语料（runs/ 不入仓）
    #   ⇒ 这几条**响亮跳过**：算通过是假绿，算失败又不是代码问题 ✓
    skip('⑤~⑧ 真机帧执行级（runs/r_194934_0.png 的 2,2 营地）',
         '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
else:
    import explore_loop as EL
    img = cv2.imdecode(np.fromfile(_P, dtype=np.uint8), cv2.IMREAD_COLOR)
    st = EL.cells_of(img, '夏日海滩').get('st') or {}
    v = st.get((2, 2)) or {}
    print('     2,2 ⇒ sid=%s name=%s score=%s anchor=%s cells=%s'
          % (v.get('sid'), v.get('name'), v.get('score'), v.get('anchor'),
             v.get('cells')))
    ck('⑤ ⭐⭐ `2,2` 判回 **营地**（不是巨大沙堡 ✓）',
       v.get('name') == '营地', str(v.get('name')))
    ck('⑥ ⭐ 它是**独立格**（anchor=自己 ✓）',
       tuple(v.get('anchor') or ()) == (2, 2), str(v.get('anchor')))
    ck('⑦ ⭐ 它**不是战斗格**（营地 Size=1 / SP=1 ✓）',
       not spots.is_fight_spot(str(v.get('sid'))))
    ck('⑧ ⭐ score = 1.0（**本格自己的高分**被采纳了 ✓）',
       abs(float(v.get('score') or 0) - 1.0) < 0.01, str(v.get('score')))

print()
print('【3】⚠ 反向：**真块不许被误杀**（gap==0 的那一大批 ✓）')
# ⛔⛔ 2026-10-13 **修"静默跳过"**（第一版写成"文件不在就整块不跑" ✗）
#   ---- 病 ----
#     ⑨/⑩ 原来读 `runs/_live_now.png` —— 那是排查时的临时图，
#     后来被删 ⇒ 这两项**一声不响地不跑了** ✗（实测本该 12 项只跑出 10 项，而门禁全绿）
#   ---- 修法 ----
#     ① 改用稳定语料（`runs/acc1/loop_0001.png`：生产命名的进图首帧）
#     ② 找不到时**响亮跳过**（不是判红、也不是静默不跑）✓
#   ⚠ 发布版不含 runs/ ⇒ 找不到是**预期**，走 ② 那条。
_LIVE_CANDS = ('runs/acc1/loop_0001.png', 'runs/acc1/r_151015_0.png',
               'runs/acc1/loop_0007.png')
_LIVE = next((p for p in _LIVE_CANDS if os.path.exists(p)), None)
print('     用稳定语料：%s' % (_LIVE or '（发布版不含 runs/ ⇒ 跳过本组）'))
if _LIVE is None:
    skip('⑨⑩ 反向守门：真块一个都不许被误杀',
         '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
else:
    ck('⑨a ⚠ 有稳定语料帧可用（**不许静默跳过** ✗）', True, str(_LIVE))
img = None
if _LIVE:
    img = cv2.imdecode(np.fromfile(_LIVE, dtype=np.uint8), cv2.IMREAD_COLOR)
    ck('⑨b 语料帧尺寸 = 720×1280 ✓',
       img is not None and img.shape[:2] == (1280, 720),
       str(None if img is None else img.shape))
if img is not None and img.shape[:2] == (1280, 720):
    # ⚠ 图名不知道 ⇒ 逐图码试，取**块最多**的那个（稳、且能证明闸门没杀光 ✓）
    _best = None
    for _code in ('S00003', 'S30001', 'S20003', 'S10001'):
        try:
            _bb = spots.Board(_code)
            _sc = _bb.scores(img, topn=spots.STATE_TOPN)
            _bl = _bb.explore_blocks(_sc)
        except Exception:       # noqa: BLE001
            continue
        if _bl and (_best is None or len(_bl) > len(_best[2])):
            _best = (_code, _sc, _bl)
    if _best is None:
        ck('⑨c 语料帧上**能聚出多格块**（否则本项无效 ✗）', False, '没有任何图码出块')
    else:
        _code, _sc, _blks = _best
        _nm = [((rows.get(x['sid']) or {}).get('Name'), round(float(x['score']), 3))
               for x in _blks]
        print('     图码 %s 的块 = %s' % (_code, _nm))
        ck('⑨ ⭐ 真块**仍然在**（闸门没把它们全杀掉 ✓）', len(_blks) >= 1,
           '%d 个' % len(_blks))
        # 真块：成员格 top1 == 块分 ⇒ 不该被拦（gap ≤ 0.20）
        _bad = []
        for x in _blks:
            _tops = [float((_sc.get(k) or [[0]])[0][0]) for k in x['cells']]
            if _tops and min(_tops) - float(x['score']) > 0.20:
                _bad.append((x['sid'], round(min(_tops), 3), round(float(x['score']), 3)))
        ck('⑩ ⚠ 这些块的 gap 都 ≤0.20（不会误触发闸门 ✓）', not _bad, str(_bad))

print()
print('【4】⚠⚠ 对照项：**把闸门关掉，必须复现旧症状**（证明不是恒绿 ✓）')
if not _in_repo_frame:
    # ⚠ 对照项本身就要拿那帧来算 ⇒ 没有语料时**不能假装跑过**
    skip('⑪ 对照项：关掉闸门复现旧症状',
         '缺真机语料 runs/r_194934_0.png（发布版不带私有录屏）⇒ 未真正验证')
else:
    # 临时把阈值改到不可能触发，看营地会不会又被吞
    _SRC_BAK = io.open('spots.py', encoding='utf-8', newline='').read()
    _crlf = '\r\n' in _SRC_BAK
    NL = '\r\n' if _crlf else '\n'
    try:
        # ⚠ 2026-10-14：判据实现换成绝对量后，这里**替换的目标字符串也要跟着换** ✓
        #   （原来替换 `if _s0 >= 0.85 and (_s0 - _bs) > 0.20:` ⇒ 找不到 ⇒ 替换无效 ⇒ 假红 ✗）
        _mut = _SRC_BAK.replace('if float(_l0[0][0]) >= 0.85:',
                                'if False:      # ⚠ 对照：闸门关掉')
        if _mut == _SRC_BAK:
            ck('⑪-prep 对照项能改到代码（替换目标存在 ✓）', False,
               '替换没生效 ⇒ 后续对照无意义 ✗')
        io.open('spots.py', 'w', encoding='utf-8', newline='').write(_mut)
        importlib.reload(spots)
        import explore_loop as _EL2
        importlib.reload(_EL2)
        img2 = cv2.imdecode(np.fromfile(_P, dtype=np.uint8), cv2.IMREAD_COLOR)
        st2 = _EL2.cells_of(img2, '夏日海滩').get('st') or {}
        v2 = st2.get((2, 2)) or {}
        print('     闸门关掉后 2,2 ⇒ sid=%s name=%s anchor=%s'
              % (v2.get('sid'), v2.get('name'), v2.get('anchor')))
        ck('⑪ ⭐⭐ 关掉闸门 ⇒ **营地又被吞**（复现旧症状 ✓）',
           tuple(v2.get('anchor') or ()) == (1, 2),
           'anchor=%s name=%s' % (v2.get('anchor'), v2.get('name')))
    finally:
        io.open('spots.py', 'w', encoding='utf-8', newline='').write(_SRC_BAK)
        importlib.reload(spots)

    # 复查还原干净
    _after = io.open('spots.py', encoding='utf-8', newline='').read()
    ck('⑫ 还原**逐字节一致**', _after == _SRC_BAK)

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
