# -*- coding: utf-8 -*-
"""verify_blocked_score.py · ⭐ 拉黑**置信度门槛**门禁（2026-10-02 真机事故）

事故
----
真机帧 `runs/r_122222_0.png`（夏日海滩）**修复前**实测：

    5,4 = {'sid': 'S00003_009', 'name': '金属宝箱怪', 'score': 0.397}

那一格其实是**躺椅类大地块 + 大拇指(boss)标记**，但分类器**几乎没认出来**
（score 0.397，真识别是 0.994）⇒ 只是**蒙对了个轮廓**，蒙出来的偏偏是
黑名单里的名字 ⇒ 老口径 `is_blocked('金属宝箱怪') = True`
⇒ **boss 格被当「用户拉黑」永久剔除** ⇒ 规划里根本没有它
⇒ 14 点体力的首领不打了（同帧 5,1/5,2/5,5 也全是 0.30~0.32 的乱猜）。

⏰ **2026-10-02 更新**：本事故的**根因已在上游修掉** ——
`spots._region()` 的 `pad` 公式只对单格成立，多格模板取图起点反向偏移 45~285px
⇒ 现在 `5,4` 正确识别为 `S00003_103 游乐设施`（用户手工核对确认）。
所以下面【A】组那条「名字被蒙成宝箱怪类」**现在应当为 False** ——
它留着是当**哨兵**：万一哪天 pad 又坏了、当场报出来，而不是让事故静默复发 ✓

本门禁钉住两件事
--------------
  ① **低置信度不许拉黑**（0.3 分的猜测不能替用户做决定）—— 这道防线**独立于** pad 修复，
     别的机型/别的图上低分乱猜照样会发生（`realme` 雾格只有 0.487，见 AGENTS.md §3）
  ② **真拉黑不能坏**（认得准的宝箱怪仍然被拉黑、仍然不进点序）

⚠ 判据**用真机帧现算**（`spots.Board.state()` 跑那张 PNG），
  不是把那张图的期望值抄在这儿 —— 否则有人把门槛改回去，
  门禁会跟着一起绿，等于没测（同 `verify_finish_exit.py` 的思路 ✓）

用法：python verify_blocked_score.py
退出码 0 = 全过。
"""
from __future__ import annotations

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

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []


def check(name, cond, detail=''):
    if cond:
        OK.append(name)
        print('  [ok  ] %s%s' % (name, ('  ' + detail) if detail else ''))
    else:
        BAD.append(name)
        print('  [FAIL] %s%s' % (name, ('  ' + detail) if detail else ''))


import cv2                                                       # noqa: E402
import numpy as np                                               # noqa: E402
import spots                                                     # noqa: E402
import targets_cfg as tcfg                                       # noqa: E402


FRAME = os.path.join(HERE, 'runs', 'r_122222_0.png')

print()
print('【A】真机帧现算（不是抄期望值）')
if not os.path.exists(FRAME):
    check('真机帧存在（%s）' % os.path.basename(FRAME), False, '找不到，跳过全部真机判据')
    st = {}
else:
    img = cv2.imdecode(np.fromfile(FRAME, dtype=np.uint8), cv2.IMREAD_COLOR)
    st = spots.Board('S00003').state(img)
    check('真机帧现算成功（%d 格）' % len(st), len(st) >= 30)

# ⭐ 事故格：boss + 大拇指那一格（真机日志 runs/loop/loop_log.json 记的）
BOSS_RC = (5, 4)
boss = st.get(BOSS_RC) or {}
# ⏰ 事故的**根因已修**（spots._region 的 pad 对多格模板算成负数，见 verify_region_pad.py）
#   ⇒ 现在这一格**应该**被正确认成 103 游乐设施、名字不再落在黑名单上。
#   ⚠ 下面两条是**哨兵**：它们现在期望「不复现」，一旦 pad 又坏 ⇒ 立刻红。
check('A0 哨兵：事故格 5,4 **不再**被蒙成宝箱怪类（pad 修复仍生效）',
      '宝箱怪' not in str(boss.get('name') or ''),
      'name=%s score=%s ← 若又变回宝箱怪，说明 spots._region 的 pad 回归了'
      % (boss.get('name'), boss.get('score')))
check('A0 哨兵：事故格 5,4 置信度已回到可用区间（≥0.45）',
      float(boss.get('score') or 0) >= 0.45,
      'score=%s（修复前 0.397 ⇒ boss 格被误拉黑）' % boss.get('score'))

print()
print('【B】低置信度不许拉黑（本次修复的核心，独立于 pad 修复）')
# ⚠ 不能再用真机帧的 5,4 当「低分」样本了 —— 它现在分高了（pad 修好了）。
#   改用**构造的低分格**：这才是这道防线真正要防的场景
#   （别的机型/别的图上分类器照样可能给 0.3 分的乱猜，AGENTS.md §3 记了 realme 雾格 0.487）。
_low = {'name': '金属宝箱怪', 'score': 0.397}
check('BOSS_1 低分乱猜**不**判拉黑（老口径只判名字会 True）',
      tcfg.is_blocked_cell(_low) is False,
      'is_blocked(名字)=%s ← 老口径；is_blocked_cell=%s ← 新口径'
      % (tcfg.is_blocked(_low['name']), tcfg.is_blocked_cell(_low)))
check('BOSS_2 门槛 0.70 落在「乱猜」与「真识别」之间（不是瞎拍的）',
      0.397 < tcfg.BLOCKED_SCORE_MIN < 0.90,
      '乱猜 0.397 < %s < 真识别 0.994 ✓' % tcfg.BLOCKED_SCORE_MIN)
# 真机帧：现在所有「名字落在黑名单上」的格，分数都该够高（识别修好了）⇒ 真拉黑生效
_scores = []
for _k, _v in sorted(st.items()):
    if tcfg.is_blocked(_v.get('name')):
        _scores.append((float(_v.get('score') or 0), _k, _v.get('name'), True))
print('     真机帧里黑名单格：%s'
      % ([('%s=%.2f' % ('%d,%d' % k, s)) for s, k, _n, _b in _scores] or '无'))
check('BOSS_3 修好 pad 后，真机帧里**认准的**黑名单格照常被拉黑',
      all(s >= tcfg.BLOCKED_SCORE_MIN for s, _k, _n, _b in _scores) if _scores
      else True,
      '门槛 %.2f；实际分数 %s'
      % (tcfg.BLOCKED_SCORE_MIN, [round(s, 2) for s, _k, _n, _b in _scores]))

print()
print('【C】真拉黑不能坏（别把修复做成「拉黑整个失效」）')
# ⚠⚠ 2026-10-09 **必须显式传 cfg**（不能吃真实配置文件 ✗）
#   根因（我本轮踩的）：原来这几条调 `is_blocked_cell(cell)` 不传 cfg ⇒ 回落到
#     `current()` ⇒ 读 **`runs/target_types.json`（用户真实勾选）** ✗
#   ⇒ 用户一解锁那 6 个方块（本轮的正当操作！）⇒ 这几条就**假红** ✗✗
#   ⇒ 门禁要测的是**判据逻辑**，不是"用户当前勾了什么" ⇒ 显式给两份固定 cfg ✓
_cfg_all_off = {'types': {}}                     # 全不勾（测"不勾会怎样"）
_cfg_all_on = {'types': {k: True for k in tcfg.SPECIAL_NAMES}}   # 全勾（测"勾了就放行"）

# ⭐⭐⭐⭐⭐ 2026-10-09 **语义变更后重写**（用户口径，原话）：
#   「把窗口的其他特殊方块解锁吧，现在勾选是设定为会当成目标去拿，不勾选就不专门去拿，
#     但是如果挡了最优的路，也会去点（**不同于之前的不勾选拉黑了**）」
#   ＋「**俩宝箱怪和祭坛也和商人宝库一样吧**」✓
# ⇒ 现在分两类（见 `targets_cfg.BLOCK_NAMES` / `PICK_IF_BLOCKING`）：
#     · **拉黑类** = 商人/宝库 + 两个宝箱怪 + 传承祭坛 ⇒ 有些名字**不再**被拉黑 ✗
#     · **可点类** = 勇者之墓/限时礼包/预言石碑 ⇒ 不勾**不是拉黑** ✓
#   ⚠ 本组旧断言钉的是"**所有**特殊方块不勾都拉黑" ⇒ 语义变了，**旧断言就是错的**
#     ⇒ 按下述重写（**不是放宽阈值，是前提变了** ✓）
check('BLK_1 认得准的宝箱怪（**拉黑类**）仍然被拉黑',
      tcfg.is_blocked_cell({'name': '金属宝箱怪', 'score': 0.99}, _cfg_all_off) is True)
check('BLK_2 **拉黑类**全部照常拉黑（两宝箱怪/祭坛）',
      all(tcfg.is_blocked_cell({'name': n, 'score': 0.95}, _cfg_all_off)
          for n in ('金属宝箱怪', '机巧宝箱怪', '传承祭坛')))
check('BLK_2b ⭐ **可点类不勾**⇒ 不再是拉黑（勇者之墓/限时礼包/预言石碑）',
      not any(tcfg.is_blocked_cell({'name': n, 'score': 0.95}, _cfg_all_off)
              for n in ('勇者之墓', '限时礼包', '预言石碑')))
check('BLK_2c ⭐ 两类名单不重不漏（并集 = 8 个特殊方块）',
      set(tcfg.BLOCK_NAMES) | set(tcfg.PICK_IF_BLOCKING) == set(tcfg.SPECIAL_NAMES)
      and not (set(tcfg.BLOCK_NAMES) & set(tcfg.PICK_IF_BLOCKING)))
check('BLK_3 用户**勾选**后 ⇒ 不再算拉黑（拉黑与勾选是同一件事的两面）',
      tcfg.is_blocked_cell({'name': '旅行商人', 'score': 0.99}, _cfg_all_on) is False)
check('BLK_4 非黑名单名字（草地/宝箱）永远不拉黑',
      not tcfg.is_blocked_cell({'name': '草地', 'score': 0.99}, _cfg_all_off)
      and not tcfg.is_blocked_cell({'name': '宝箱', 'score': 0.99}, _cfg_all_off))
check('BLK_5 score 缺失/是 None ⇒ **不拉黑**（fail-open，宁多点不漏 boss）',
      not tcfg.is_blocked_cell({'name': '金属宝箱怪'}, _cfg_all_off)
      and not tcfg.is_blocked_cell({'name': '金属宝箱怪', 'score': None}, _cfg_all_off))

print()
print('【D】explore_loop 两处调用点都已切到新口径（不许漏改一处）')
_src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
check('DRV_1 _blocked_px 走 is_blocked_cell',
      'is_blocked_cell(_v)' in _src)
check('DRV_2 _cells_for_model 的拉黑标记也走新口径',
      'is_blocked_cell(_v2)' in _src)
check('DRV_3 没有残留的老口径调用（`_v.get(\'name\')` 形式）',
      "is_blocked(_v.get('name'))" not in _src
      and "is_blocked(_v2.get('name'))" not in _src)

print()
print('=' * 74)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
