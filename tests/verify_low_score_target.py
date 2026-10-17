# -*- coding: utf-8 -*-
"""★ 回归：**低分名字不许当目标**（2026-10-12「先打巨大沙堡」✗）

用户原话：「**为什么先点巨大沙堡再点 4,6 / 1,6？难道不是直接 4,6、1,6 就完事了吗**」
            ＋「**所以最本质的问题不应该是识别错了吗**」

⛔ 根因（真机铁证 `runs/loop/loop_log.json` 第 12 张 + 帧 `runs/r_133026_0.png`）：
    `5,6` 被认成 `S00003_014 限时礼包`，**score 只有 0.441**
      （候选挤在一起：`0.441 / 0.392 / 0.38` ⇒ **分类器自己都不确定** ✗）
    而 `限时礼包` 在配置里是**勾选**的 ⇒ 旧 `is_target(name, sid, marks)`
      **不看 score** ⇒ 判 True ⇒ 求解器**专门去拿它** ⇒ 点它 ⇒
      实际打的是**整座巨大沙堡**（`S00003_211`，`SpotSize=4 / EventNum=4-4`
      ⇒ **4 场战斗**）✗✗

⭐ 修法：`is_target(..., score=)` —— **靠名字当目标**时必须 `score >= 0.85`
   （`NAME_SCORE_MIN`）✓
   ⚠ 与既有设计同源：`mapsim.CONTENT_SCORE_MIN = 0.85` 早就有这条原则
     （原话注释：「**雾里名字本来就不可信**」✓）

⚠⚠ 本轮差点改错（记下来）：
   我第一版想给 `is_target` **全体**加门槛 ⇒ 一量数据发现**会废掉探索格** ✗
   实测（`_tmpman/chk_score_dist.py`）：目标格 152 个、低分 43 个，
   **43 个几乎全是探索格**，而探索格 score 本来就 **0.39~0.73**
   （靠 **sid 后缀** 221/321/331 判定，**不靠名字** ✓）
   ⇒ 门槛**只能**加在"名字"那一支 ✓ 本回归第【3】组专门钉住这一点 ✓
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
import targets_cfg as TC


OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料 / 无本机配置）⇒ **响亮地跳过**（不算通过、也不算失败）。"""
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


_SRC = io.open('targets_cfg.py', encoding='utf-8').read()
_EL = io.open('explore_loop.py', encoding='utf-8').read()
_ELC = '\n'.join(l for l in _EL.splitlines() if not l.lstrip().startswith('#'))
# ⚠⚠ 本组必须用**确定的**配置，不能读本机 `runs/target_types.json`。
#   原因：那份配置是**用户现场**（各人勾选不同、且 runs/ 不入仓）。
#   原写法 `TC.load()` 读不到文件时，`限时礼包` 会落到"未勾选=False"
#   ⇒ ⑤⑦⑧ 三条断言（都以「限时礼包**已勾选**」为前提）**必然假红** ✗
#   ⇒ 这里显式构造一份最小配置（只把限时礼包打开），把被测判据与用户现场解耦 ✓
cfg = {'version': 1, 'types': {}}
for _k in TC.DEFAULT_ON:
    cfg['types'][_k] = True
cfg['types']['限时礼包'] = True

print('=' * 94)
print('低分名字不许当目标（2026-10-12）')
print('=' * 94)

print()
print('【1】结构级')
ck('① `targets_cfg` 有 `NAME_SCORE_MIN`', hasattr(TC, 'NAME_SCORE_MIN'),
   str(getattr(TC, 'NAME_SCORE_MIN', None)))
ck('② 它 = 0.85（与 `mapsim.CONTENT_SCORE_MIN` 同值 ✓）',
   float(getattr(TC, 'NAME_SCORE_MIN', 0)) == 0.85)
ck('③ `is_target` 有 `score` 形参',
   'score=None' in _SRC and 'def is_target(name, sid, marks=None, cfg=None, score=None)'
   in _SRC)
# ⭐ 生产调用点**只有一个** ⇒ 必须传 score（否则改了等于没改 ✗）
ck('④ ⭐ 生产调用点传了 `score=`',
   "score=_vv.get('score')" in _ELC,
   str([l.strip()[:70] for l in _ELC.splitlines() if 'is_target(' in l][:2]))

print()
print('【2】⭐⭐ 行为级：真机那格的判据翻转')
_SID, _NM = 'S00003_014', '限时礼包'
_o = TC.is_target(_NM, _SID, cfg=cfg)
_n = TC.is_target(_NM, _SID, cfg=cfg, score=0.441)
print('     5,6 限时礼包 score=0.441 ⇒ 旧=%s 新=%s' % (_o, _n))
ck('⑤ ⭐⭐ 旧判据判 True（这就是那个 bug ✓）', _o is True)
ck('⑥ ⭐⭐ 新判据判 **False**（不再专门去拿 ✓）', _n is False)
ck('⑦ ⭐ 高置信（score=0.95）**照旧** True（功能没坏 ✓）',
   TC.is_target(_NM, _SID, cfg=cfg, score=0.95) is True)
ck('⑧ ⚠ **不传 score** ⇒ 行为与修前**完全一致**（fail-open ✓）',
   TC.is_target(_NM, _SID, cfg=cfg) is True)

print()
print('【3】⚠⚠ 关键反向：**探索格不许被误伤**（低分是正常的 ✓）')
# 实测：探索格 score 本来就是 0.39~0.73（靠 sid 后缀判，不靠名字）
for _sid, _sc in (('S00003_221', 0.52), ('S00003_321', 0.71),
                  ('S00003_331', 0.394)):
    _r = TC.is_target('荧光蘑菇', _sid, cfg=cfg, score=_sc)
    print('     %s score=%.3f ⇒ %s' % (_sid, _sc, _r))
    ck('⑨ ⭐ 探索格 %s（score=%.2f）**仍是目标**' % (_sid, _sc), _r is True)
ck('⑩ ⚠ `is_explore_tile` 判据**没被改动**',
   'def is_explore_tile' in _SRC and 'EXPLORE_SUFFIX' in _SRC)

print()
print('【4】⚠ 反向：`marks` 那一支也不受影响')
ck('⑪ ⭐ 带 `boss` 标记、score 极低 ⇒ **仍是目标**',
   TC.is_target('未知', 'S00003_001', ['boss'], cfg=cfg, score=0.3) is True)
ck('⑫ 带 `recommend` 标记、score 极低 ⇒ 仍是目标',
   TC.is_target('未知', 'S00003_001', ['recommend'], cfg=cfg, score=0.2) is True)

print()
print('【5】⭐ 真机帧复算（`runs/r_133026_0.png`，那条 bug 的现场）')
_P = os.path.join('runs', 'r_133026_0.png')
if not os.path.exists(_P):
    # ⚠ 真机帧属开发者私有录屏（runs/ 不入仓）⇒ 响亮跳过，不算失败
    skip('⑬⑭⑭b⑮ 真机帧复算（runs/r_133026_0.png）',
         '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
else:
    img = cv2.imdecode(np.fromfile(_P, dtype=np.uint8), cv2.IMREAD_COLOR)
    c = EL.cells_of(img, '夏日海滩')
    st = c.get('st') or {}
    _f = []
    for k, v in st.items():
        if not isinstance(v, dict):
            continue
        _old = TC.is_target(v.get('name'), v.get('sid'), None, cfg=cfg)
        _new = TC.is_target(v.get('name'), v.get('sid'), None, cfg=cfg,
                            score=v.get('score'))
        if _old != _new:
            _f.append(('%d,%d' % k, v.get('name'), round(float(v.get('score')), 3)))
    print('     该帧 target 翻转的格 = %s' % (_f or '无'))
    # ⚠⚠ 2026-10-14 **本节按新行为改写**（原断言已过时 ✗）
    #   ---- 为什么过时 ----
    #     原文假设 `5,6` 的 `name` 恒为「限时礼包」。
    #     可 10-14 修「沙堡没识别」时（形状判据 + 门槛 0.28 + E7 保护），
    #     `(4,5)(5,5)(5,6)(5,7)` 被**正确地**归成「巨大沙堡」块 ✓
    #     ⇒ `5,6` 的 `name` 变成「巨大沙堡」（`score` 仍是那格自己的 0.441）✗
    #   ---- 人眼核对（`runs/r_133026_0.png`，见 `runs/_low56.png`）----
    #     `4,5` = **巨大沙堡本体**（旗子+塔身）／`5,5`/`5,6`/`5,7` = 它的延伸装饰带
    #     ⇒ **它们本来就是同一片沙堡美术** ⇒ 归成块是**对的** ✓
    #     ⇒ 原先"`5,6` 是限时礼包"才是**误判**（正是用户最初报的那个 bug ✓）
    #   ---- 本节的**核心意图没变** ----
    #     「低分名字不许当目标」——`score 0.441` 低于 `NAME_SCORE_MIN 0.85`
    #     ⇒ 无论它叫「限时礼包」还是「巨大沙堡」，**都不该当目标** ✓
    _v56 = st.get((5, 6)) or {}
    _n56 = str(_v56.get('name') or '')
    ck('⑭ ⭐ `5,6` 的 **score = 0.441**（分类器对它不确定 ✓）',
       abs(float(_v56.get('score') or 0) - 0.441) < 0.01,
       '%s %s' % (_n56, _v56.get('score')))
    ck('⑭b ⭐ 它现在归入**沙堡块**（`anchor` 不是自己 ⇒ 被块接管 ✓）',
       tuple(_v56.get('anchor') or ()) != (5, 6),
       'anchor=%s name=%s' % (_v56.get('anchor'), _n56))
    ck('⑬ ⭐⭐ 该帧低分格**一律不当目标**（`5,6` 与它同块的那些都在内 ✓）',
       all(not TC.is_target((st.get(k) or {}).get('name'),
                            (st.get(k) or {}).get('sid'), None, cfg=cfg,
                            score=(st.get(k) or {}).get('score'))
           for k in ((4, 5), (5, 5), (5, 6), (5, 7))
           if (st.get(k) or {}).get('score') is not None),
       str([('%d,%d' % k, (st.get(k) or {}).get('name'),
             (st.get(k) or {}).get('score')) for k in ((4, 5), (5, 5), (5, 6), (5, 7))]))
    # ⚠ 同帧的高分格**不许**被翻转（否则杀过头 ✗）
    _hi = [k for k, v in st.items()
           if isinstance(v, dict) and float(v.get('score') or 0) >= 0.85
           and TC.is_target(v.get('name'), v.get('sid'), None, cfg=cfg)
           and not TC.is_target(v.get('name'), v.get('sid'), None, cfg=cfg,
                                score=v.get('score'))]
    ck('⑮ ⚠ 高分格（≥0.85）**一个都没被翻转**（没杀过头 ✓）',
       not _hi, str(_hi[:4]))

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
