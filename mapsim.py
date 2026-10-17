# -*- coding: utf-8 -*-
"""mapsim.py · **地图模拟器**（探索棋盘：揭格 / 连锁消除 / 目标与点序）

⚠ 这不是 `headless_battle`（战斗数值模拟器），本文件只模拟**探索地图**这一层：
   棋盘布局、可见性（雾）、点击规则、连通消除、标记/商人/宝库目标、以及"点哪一格"的策略。

规则来源（与游戏客户端行为一致，逐条核对过）：
  · 点击地块（行 45185）：
        if (data.SpecialSpot == 0)  -> GetConnectedPlainBlocks(...)  # 整片连通空地一起消耗
        else                        -> FinishBlock(...)              # 开面板（战斗/商人/宝库…）
  · 连通空地（行 45205 GetConnectedPlainBlocks）：BFS，5 行 7 列，4 邻域，
        只吃 `SpotSize <= 1 && SpecialSpot == 0 && saga == null` 的块；同块的所有格子一起入队
  · 消耗地块（行 47708 RemoveBlock）→ SetBlockVisible()（行 47743）重算可用性
  · 地块属性（行 82943 起）：`AreaSpotDataItem.SpecialSpot / SpotSize / PrefixNum / MinBattleStep…`
        ⇒ 本模拟器**直接用真实地块表**（`spots.spot_rows()`），不手抄常量

可见性（雾）：源码里 `isVisible` 由服务端状态驱动，客户端只负责渲染压暗（`disableColor`）。
    我们的视觉管线实测口径：
        · 已揭示格 亮度比 ≥0.85；未揭示 = 同一张美术 ×0.65（可识别但**点不动**）
        · 标记（首领/红装/点赞/幸运草）**即使在未揭示格上也画出来**（所以"点不动的 boss"存在）
    ⇒ 模拟器就用这套口径（与探索循环看到的完全一致）。

用法：
    python mapsim.py --sample runs/m1_r006.png      # 用一张真实截图建盘，跑一遍当前策略
    python mapsim.py --bench 40                     # 从 runs/ 采样建盘，跑 N 局统计
    python mapsim.py --selftest                     # 规则自检（连通消除/可见性）
"""
import argparse
import glob
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROWS, COLS = 5, 7
NCELL = ROWS * COLS


def cell_of(r, c):
    return (r - 1) * COLS + (c - 1)          # 内部 0 基；对外 r/c 用 1 基（跟 explore_loop 一致）


def rc_of(idx):
    return idx // COLS + 1, idx % COLS + 1


def _neighbours(idx):
    """4 邻格的 cell 索引（越界的不返回）"""
    r, c = idx // COLS, idx % COLS
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS and 0 <= cc < COLS:
            out.append(rr * COLS + cc)
    return out


# 小助手 app 官方分类：普通地块（绿）后缀列表 —— 这些是空地（连锁消除，只花 SpotSize）
# 空地后缀（点它**连锁消除** ⇒ 只花 1 点 ✓）
# ⚠ 002（海螺）**不是空地** ✗ —— 它是内容格（点它弹面板 ⇒ 战斗 ×2 ✓）
#   2026-09-27 用户报「非要去点 24 的战斗格子」= 我把 002 当空地 ⇒ 单价 1 点 ⇒ 求解器无所谓 ✗
PLAIN_SUFFIX = {'000', '001'}
# ⭐ v1.06：雾格「剪影占比」阈值 —— 与 `spots.FOG_SIL_MIN` **同值**（真机实测：雾下有物体
#   0.064~0.292 / 平坦 0.014~0.016，4 倍空档 ⇒ 0.04 稳 ✓）。这里**故意复制常量**而不是
#   import spots（`spots` 会在 import 时读数据表，而 mapsim 要保持"纯逻辑模块"可在无表环境跑 ✓）
FOG_SIL_MIN = 0.04
# ⭐⭐⭐ 2026-10-05 「分类器**有把握**认出内容地块」的分界（见 `Block.plain`）：
#   真机实测（`runs/acc2/r_153038_0.png`）：宝箱/矿箱/地穴 = **0.999~1.0**（必须拦连锁 ✓）
#   而雾里的低分猜测：矿箱堆 0.638 / 荧光蘑菇 0.528 / 翻倒矿箱 0.473（**不许拦** ✓）
#   ⇒ 0.85 落在两簇中间（用户口径："只有类似宝箱海螺那种非空地才拦连锁"）
CONTENT_SCORE_MIN = 0.85

# ⭐ 运行时学习（跨图共享 ✓）：点下去**连锁**的 = 空地 ✓；**弹面板**的 = 内容格 ✓
PLAIN_SEEN = {}     # suffix -> True
PANEL_SEEN = {}     # suffix -> True


def learn_tile(sid, plain):
    """循环点完一格后回报"是连锁还是面板" ⇒ 越跑越准 ✓"""
    suf = str(sid or '').split('_')[-1]
    if not suf:
        return
    if plain:
        PLAIN_SEEN[suf] = True
        PANEL_SEEN.pop(suf, None)
    else:
        PANEL_SEEN[suf] = True
        PLAIN_SEEN.pop(suf, None)


class Block:
    """一个地块（可能占多格，但探索图里绝大多数是 1 格）"""

    def __init__(self, idx, spot, revealed=False, mark=None, gone=False):
        self.idx = idx
        self.sid = spot.get('sid') if isinstance(spot, dict) else str(spot)
        self.name = spot.get('name') if isinstance(spot, dict) else str(spot)
        self.special = int(spot.get('SpecialSpot') or 0) if isinstance(spot, dict) else 0
        # ⭐⭐⭐ 2026-10-05 分类器**置信度**与数据表**权重**（判"是不是内容地块"用，见 `plain`）
        try:
            self.score = float(spot.get('score') or spot.get('block_score') or 0.0)
        except Exception:               # noqa: BLE001
            self.score = 0.0
        try:
            self.weight = int(spot.get('Weight') or 0)
        except Exception:               # noqa: BLE001
            self.weight = 0
        self.size = int(spot.get('SpotSize') or 1) if isinstance(spot, dict) else 1
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**16 为什么是 18 体？两块不应该是 4 体吗**」✓
        #   ⇒ 块的大小不能只看数据表 `SpotSize`（海边小屋模板写 9 ✓），还要受
        #     **这一块实际占了几格**约束：数据表 9 + 实际 2 格 ⇒ 应按 **2 格**计价
        #     （战斗 ⇒ 2×2 = **4 体** ✓；原来按 9 算 ⇒ 18 体 ✗）
        #   ⚠ 与"按分数降级"不同（那条已被用户否掉 ✗「别随意降门槛」）——
        #     这里**不碰分数**，只用"块实际占几格"这个**几何事实** ✓
        #   （回归影响：单格内容格 ⇒ min(表值,1)=1 ✓；真 4 格游乐设施 ⇒ min(5,4)=4 ✓
        #     即"按实际格数"，正是用户口径 ✓）
        if isinstance(spot, dict):
            _obs_cells = spot.get('cells')
            if isinstance(_obs_cells, (list, tuple)) and len(_obs_cells) > 0:
                self.size = max(1, min(self.size, len(_obs_cells)))
        self.revealed = revealed          # 已揭示（不压暗、可点）
        # ⭐⭐⭐ 2026-10-02 **观测值**（建块时从观测读到的 revealed，此后**永不改动**）
        #   为什么要单独存一份：`_infer_revealed()` / `reveal_neighbours()` 会用
        #   **邻接推演**把某些块的 `revealed` 改成 True（"邻格是空地 ⇒ 该块被揭示"）——
        #   可一旦模型对"哪些格已消耗"的判断有偏差（真机 23:30 那把就是这样：
        #   4 格被推断成已消耗并被删出模型 ⇒ board<0 ⇒ 求解器当成空地），
        #   它**旁边的雾格**就会被推演成"已揭示/可点" ⇒ 计划里出现点不动的格 ✗✗
        #   ⇒ `mapsolve.Problem.block_revealed` 用这个 `observed` 做**观测闸门**，
        #     推演出来的 revealed 不再有资格让一个块"变成可点" ✓
        self.observed = bool(revealed)
        # ⭐⭐⭐ 2026-10-02 **营地标记**（用户口径：「营地应该最好认吧，稳定是揭示状态的，
        #   先固定下来营地？」）
        #   为什么必须喂给模型：`mapsolve.Problem` 原来**只按块名含"营地"**找营地，
        #   而营地格经常被多格块吞掉（真机 `spawn_fallback: 2,1`「营地没被认成单格块」）
        #   ⇒ `Problem.camp = None` ⇒ 揭示规则「与**营地**或已消耗格 4 邻接」**没有起点**
        #   ⇒ 求解器 `exhausted`（无解）⇒ 整张图干等/退图（真机 23:30 那把铁证）✗✗
        #   ⇒ 循环侧用 `find_camp_cell()`（老判据 + sid 后缀 000 兜底）认出来后，
        #     在观测里给那一格打 `camp=True`，这里接住它 ✓
        self.camp = bool(spot.get('camp')) if isinstance(spot, dict) else False
        # ⭐⭐⭐ 2026-10-03 用户口径：「**能不能一开始就不规划这个拉黑的**」✓
        #   拉黑块（特殊方块清单里没勾选的：宝箱怪/勇者之墓/… ✓）
        #   ⇒ 求解器**既不点它、也不借它走路** ✓（计划从生成起就不含它 ✓）
        self.blocked = bool(spot.get('blocked')) if isinstance(spot, dict) else False
        # ⭐⭐⭐ 2026-10-02 **营地到底是哪一格**（可多格块）——
        #   离线铁证（r_233023_0.png）：营地格 (2,1) 属于 4 格块 `巨大沙堡`
        #   (1,1)(2,1)(2,2)(2,3) ⇒ 若拿**整块**当"揭示源"，boss(1,2) 与 (1,1)/(2,2)
        #   相邻 ⇒ 被捷径判"可点" ⇒ 又排进计划（真机就是雾格）✗✗
        #   ⇒ 只记带 camp 标记的那一格 ✓
        self.camp_cells = ([int(x) for x in (spot.get('camp_cells') or [])]
                           if isinstance(spot, dict) else [])
        self.mark = mark                  # 'boss' | 'redEquip' | 'recommend' | 'clover' | None
        self.gone = gone                  # 已消耗
        self.cells = []                   # 占用的格子（0 基 cell 索引）
        # ⭐⭐ 2026-09-28：**「这一块是不是当前配置下的目标」**（来自 targets_cfg 白名单 ✓）
        #   True/False = 调用方明确给了结论（explore_loop 走这条 ✓）
        #   None       = 没给（老调用如 mapevolve）⇒ 退回 `mark or is_buy` 老口径 ✓
        self.want = (spot.get('want') if isinstance(spot, dict) and 'want' in spot else None)
        # ⭐ v1.06：留着原始 spot dict —— `fog_sil`（雾格剪影占比）等字段要用它判定 ✓
        self.spot = dict(spot) if isinstance(spot, dict) else {'sid': str(spot)}
        # ⭐ v1.03/v1.05：**雾下剪影**（按格实测，不是一刀切 ✓）
        self.fog_object = bool(spot.get('fog_object')) if isinstance(spot, dict) else False
        self.fog_flat = bool(spot.get('fog_flat')) if isinstance(spot, dict) else False

    @property
    def plain(self):
        """空地（点它触发**连锁消除**，固定 1 点体力）

        ⭐⭐⭐ 2026-09-28 用户口径（**真机已证，决定性**）：
            「只连锁草地，不连锁其他的」＋「(1,5) 只揭开 3 格 (1,5)(1,6)(1,7)，
              被宝箱、海螺和出生地挡住了」

        两条硬修正：
          ① **营地（出生地）不是空地** —— 不可点，而且**阻断连锁** ✗
             旧版 `PLAIN_SUFFIX` 含 '000'（营地）⇒ 营地被当成空地
             ⇒ 把 (1,5)、(2,4)、(3,5) 三个各自独立的草地片**通过营地粘成一片** ✗
             ⇒ solver 以为"点哪个都一样"，挑了片最小的 (1,5)（它只连 3 格）
             ⇒ 够不到 boss ⇒ 被迫多插一步 (4,5)（真机上那格已被连带消掉、点了零反应）✗✗
          ② **删掉旧兜底 `special==0 and size<=1 ⇒ True`** —— 它把 1 格的内容格
             （宝箱/海螺/岩石…）也当成了空地 ✗；改成只认**草地**（名字含「草」）
        实测（`_why_15c.py`，C 口径）：点 (1,5) ⇒ 片恰为 3 格 ✓ 与用户描述逐字吻合
        """
        # ⛔⛔ 2026-10-03 用户口径（原话）：「**模型都认出这是海边小屋了，怎么还会认为是空地**」✗
        #   真机铁证（`runs/r_200646_0.png` 第 3 张图）：
        #     计划第1步 `(4,2)` = `S00003_301`「海边小屋」score 0.757、ratio **1.19（已揭示✓）**
        #     数据表 `SpotSize=6 / EventNum=6-6` ⇒ **战斗地块** ⇒ 正确定价 **6×2 = 12 体** ✓
        #     且**不连锁** ✗ —— 可模型给出 `plain=True` ✗ ⇒ `block_cost = 1` ✗
        #     ⇒ 还被算进"草地连锁"⇒ 计划第一步的代价与后续推演**全错** ✗✗
        #   根因：下面"雾格剪影"那一支**提前 return、完全不看名字/类型** ✗
        #     （本意是"雾里名字不可信 ⇒ 改看剪影平坦度"，但它**排在战斗保护之前** ✗）
        #   ⇒ **战斗保护提到最前**：任何分支都不许把战斗型地块判成空地 ✓
        try:
            import spots as _sp0
            if _sp0.is_fight_spot(self.sid):
                return False
        except Exception:       # noqa: BLE001
            pass
        if '营地' in (self.name or ''):
            return False                     # 出生地：不可点 + 阻断连锁 ✓
        # ⭐⭐⭐⭐ 2026-10-05 用户口径（原话）：
        #     「**只有类似那种宝箱海螺的非空地才会拦截连锁**」
        #   ⇒ **分类器有把握地认出这是"内容地块"（且不是本图地面填充块）⇒ 非空地** ✓
        #   真机铁证（`runs/acc2/r_153038_0.png`，用户原话「**这张图没认出宝箱吗，
        #   中间有宝箱拦住连锁了**」）：
        #     `(4,1)` = `宝箱`、**score = 1.0**，但 `fog_sil` 只有 **0.04** ——
        #     因为**剪影法只抓"比雾底暗"的东西，而宝箱美术是亮的** ⇒ 它整个漏掉 ✗✗
        #     ⇒ 旧路径判它"平坦=空地" ⇒ 模型让连锁**穿过宝箱** ⇒ 计划错 ✗
        #   ⚠ 只认**高置信**（score ≥ `CONTENT_SCORE_MIN`）：宝箱/矿箱/地穴都是 0.999~1.0 ✓；
        #     而矿箱堆 0.638 / 荧光蘑菇 0.528 / 翻倒矿箱 0.473 这类**低分猜测不拦** ✓
        #     （雾里名字本来就不可信，挡得太狠会把真空地也拦掉 ⇒ 那正是上一轮修的坑 ✗）
        try:
            import targets_cfg as _tc2
            _is_ground = ((self.name or '') in set(_tc2.PLAIN_NAMES or ())) or self.weight >= 40000
            if (not _is_ground) and self.score >= CONTENT_SCORE_MIN:
                return False
        except Exception:       # noqa: BLE001
            pass
        # ⭐⭐⭐ 2026-10-01 v1.03【雾格剪影一票否决】——用户口径「优化识别模型，认出雾格里那块
        #   不能穿过」：雾格剪影占比 ≥ `spots.FOG_SIL_MIN`(0.04) ⇒ 底下**有东西** ⇒ 不是空地
        #   （真机同帧实测：有物体 0.064~0.292 / 平坦 0.014~0.016，4 倍空档 ✓）
        #   ⚠ 只对**雾格**生效（`state()` 只在 ratio<0.78 时打这个标）；揭开后按真实分类建模 ✓
        if getattr(self, 'fog_object', False):
            return False          # 雾下有物体 ⇒ 非空地（挡连锁 ✓）
        # ⭐⭐⭐ v1.06【雾格平坦 ⇒ 当空地】：对**雾格**来说"名字"很不可信（真机这盘整套模板
        #   中位分只有 0.276，平坦格被猜成「岩石/巨大木桩」✗）⇒ 雾格的 plain 只认剪影实测：
        #     有物体（fog_object）⇒ 非空地 ｜ 平坦（fog_flat）⇒ 空地
        #   ⚠ 仅当该格**有剪影值**（= 它是雾格）时接管；揭开后走下面按名字/后缀的老逻辑 ✓
        #   ⚠⚠ 2026-10-03 **这一支只看真雾格**（观测时未揭示 ✓）——
        #     已揭示的格**必须**按名字/类型判断 ✓
        #     真机反例（`r_200646_0.png`）：(4,2) ratio=**1.19（已揭示）** 却带着剪影值
        #       ⇒ 旧写法（只看 `fog_sil is not None`）会**绕过一切判断** ⇒ plain=True ✗✗
        if (not getattr(self, 'observed', False)) and self.spot.get('fog_sil') is not None:
            return bool(getattr(self, 'fog_flat', False))
        suf = str(self.sid or '').split('_')[-1]
        # ⚠ v1.05：og_flat（雾格平坦⇒当空地）**暂不启用** —— 集成路径里剪影值与独立原型
        #   不一致（疑似 state() 内部对帧做过缩放/几何换算），修好再开 ✓ 先把值记进日志备查 ✓
        suf = str(self.sid or '').split('_')[-1]
        # ⭐⭐⭐ 2026-10-03 用户口径：「**为什么还是要去打战斗格子？这样不是会贵吗**」
        #   真机根因（acc1 gui_20261003_140308 第 2 张图，离线逐格对账实证）：
        #     `A* 计划（格）= [('2,6', cost=1), ('2,5', cost=1), ('3,1', cost=6)]`
        #     ⇒ 那个**要打的战斗格 (2,6) 被算成 1 体** ✗（应按 格数×2 = 6 ✓）
        #     ⇒ 于是 A* 总价 8，而真正的绕路要 12 ⇒ 模型当然选"打架那条" ✗✗
        #   原因就在下面这条**"运行时学到"**的捷径：只要有一次把 `_111` 误学成空地，
        #     该类型**全部**格子都变成 1 体 ✗（与 `block_cost` 的类型定价互相矛盾 ✗）
        #   ⇒ 战斗型地块**永远不许**当空地（数据表 `EventNum` 说了算 ✓）
        try:
            import spots as _sp
            if _sp.is_fight_spot(self.sid):
                return False
        except Exception:       # noqa: BLE001
            pass
        # ⭐ 运行时学到的优先（点过、知道是连锁还是弹面板 ✓）
        if suf in PLAIN_SEEN:
            return True
        if suf in PANEL_SEEN:
            return False
        # ⭐⭐⭐⭐ 2026-10-05 用户口径（原话）：
        #     「**空地有好多种，其实本质都一样**」
        #     「**只有类似那种宝箱海螺的非空地才会拦截连锁**」
        #   ⇒ 空地的判据**不该看名字、也不该看号段**，只看数据表里
        #     "这是不是本图的**地面填充块**"。全表实测（`spots.spot_rows()`）：
        #       地面：雪地/草地/岩地/海底/沙地 —— **Weight = 40000、MaxNum = 35、
        #             SpecialSpot = 0**（5 种，本质一样 ✓）
        #       内容：矿箱堆(10000~15000)/岩石柱/翻倒矿箱/废弃矿车/魔晶矿(20000)/
        #             蘑菇丛/水晶矿/荧光蘑菇(3000)/空间水晶(200)… —— **一律 ≤ 20000** ✓
        #   ⚠ 旧写法两处都不对（只是**碰巧**在 `_001` 的地图上行得通）：
        #     · `suffix == '001'`：号段是会变的（`地穴` 就是 `_005`）⇒ 靠号段＝靠巧合 ✗
        #     · `'草' in name`：只认「草地」⇒ **岩地/沙地/雪地/海底 全被判成"非空地"** ✗
        #       （与本仓 `targets_cfg.PLAIN_NAMES` 那张清单**自相矛盾** ✗）
        #   ⇒ 现在：数据表口径（**填充块 Weight ⇒ 空地**）＋ 共享清单 `PLAIN_NAMES` 兜底 ✓
        try:
            _w = int(self.spot.get('Weight') or 0)
            _sp = int(self.spot.get('SpecialSpot') or 0)
        except Exception:       # noqa: BLE001
            _w, _sp = 0, 0
        if _w >= 40000 and not _sp:
            return True                      # 本图地面填充块 ⇒ 空地（连锁 ✓）
        try:
            import targets_cfg as _tc
            if (self.name or '') in set(_tc.PLAIN_NAMES or ()):
                return True                  # 共享清单兜底（与 targets_cfg 同源 ✓）
        except Exception:       # noqa: BLE001
            pass
        return False

    @property
    def is_merchant(self):
        return self.name in ('旅行商人',)

    @property
    def is_vault(self):
        return self.name in ('黄金宝库',)

    @property
    def is_buy(self):
        return self.is_merchant or self.is_vault

    def __repr__(self):
        return '<B%d %s%s%s>' % (self.idx, self.name,
                                 '/mark=%s' % self.mark if self.mark else '',
                                 '/gone' if self.gone else
                                 ('' if self.revealed else '/fog'))


class MapSim:
    """探索地图模拟器（只做揭格/消耗/目标判定；战斗与掉落不在这一层）"""

    def __init__(self, board=None, blocks=None):
        self.board = list(board or [-1] * NCELL)      # cell -> block idx
        self.blocks = {b.idx: b for b in (blocks or [])}
        for b in self.blocks.values():
            b.cells = [i for i, v in enumerate(self.board) if v == b.idx]
        self.clicks = 0
        self.stamina = 0            # ⭐ 累计体力（源码口径，见 charge()）
        self.log = []

    # ---------- 体力（源码 82956-82992） ----------
    @staticmethod
    def block_cost(b):
        """普通格 = SpotSize；战斗格 = SpotSize*2（战斗/探索产出都是 ×2）

        ⭐⭐ 2026-09-27 用户明确口径（与 `mapsolve` 同口径，2026-09-28 补同步）：
            「空白格都是 1 点，且不管连锁多少其他挨着的空白格」
            ⇒ **空地固定 1 点**（不是 Σ SpotSize ✗）
            「最小的战斗格子都要花 4 点（1 乘 2 的）」⇒ 战斗格 = SpotSize × 2
        ⚠ 2026-09-28 才发现：`_fix_blank_cost_1.py` 当年**只改了 mapsolve.py、
          漏了 mapsim.py** ⇒ 模拟器按"整片 Σ"、求解器按"固定 1 点"
          ⇒ 策略评估与最优解**不可比**（苹果比橘子，"基线多花 16%"是虚的）。
        """
        if getattr(b, 'plain', False):
            return 1
        size = int(getattr(b, 'size', 1) or 1)
        # ⭐ 2026-10-03 与 `mapsolve` 同口径：**先按地块类型**判是不是战斗型
        #   （`EventNum` > 1-1 ⇒ 战斗 ⇒ size×2 ✓；临时标记 `拦路` 在规划时还没有 ✗）
        try:
            import spots as _sp                 # ⚠ 本模块**故意不 import spots**（数据靠参数传 ✓）
            if _sp.is_fight_spot(getattr(b, 'sid', None)):   # 局部导入：首次后走缓存，零开销 ✓
                return size * 2
        except Exception:       # noqa: BLE001
            pass
        if getattr(b, 'mark', None) in ('boss', 'redEquip', 'recommend', 'battle',
                                        '拦路'):
            return size * 2
        return size

    def charge(self, cost):
        self.stamina += int(cost)
        return cost

    # ---------- 构造 ----------
    @classmethod
    def from_observation(cls, cells, spot_table, group=True):
        """从「一次真实观测」建盘

        cells: {(r, c): {'sid':..., 'name':..., 'revealed':bool, 'marks':[...]}}
               （探索循环 `cells_of()` / `spots.Board.state()` 的输出）
        spot_table: spots.spot_rows() —— 真实地块表（拿 SpecialSpot/SpotSize）
        group: 把**相邻且同 sid** 的格子归成一个块（游戏里 2×2 大地块就是这样 ✓）
               —— 不归组的话，一个 4 格地块会被拆成 4 个块，体力/揭示都会算错 ✗

        ⭐⭐⭐ 2026-09-28 新增（用户真机报 `r_224535_0`「(1,1) 前面应该有个 (3,1) 宝箱」）：
            **只要格子带 `anchor` 字段 ⇒ 一律按它归组**（`_from_anchors`），不再用
            「相邻 + 同 sid」猜 ✗。原因（真机像素铁证 `runs/_zoom_1535_corner.png`）：
              左上角是**两棵独立的竖排椰树** 椰树#1=(1,1)+(2,1) / 椰树#2=(1,2)+(2,2)，
              旧规则把它们**并成一块** ⇒ ① boss 只算一次点击（4 点，实际要 8 点：
              真机连打两场战斗 ✓）② 被并后的块直接挨着已消草地 (1,3) ⇒ 规划以为
              「不用 (3,1) 就能点 boss」⇒ 真机 `tap: fogged_noop at (1,1)` 点不动 ✗✗
              按 anchor 归组后：椰树#1 的格 = (1,1)+(2,1)，与草地 (1,3) **不邻接**
              ⇒ boss 只能靠 (3,1) 宝箱（1 点，邻 (2,1)）或椰树#2 解锁 ⇒ solver 选出
              `(2,4)→(3,1)宝箱→(3,5)→(4,5)商人→(1,1)boss` = 8 点 / 5 步 ✓
              （与用户「(1,1) 前面应该有个 (3,1)」逐字吻合 ✓）。
            `anchor` 由 `spots.Board.state()`（alpha 真实占格 + 掩膜 NCC）给出 —— 是
            比"相邻同 sid"可靠得多的**真机占格**结论 ✓
        """
        # ⭐⭐⭐⭐ 2026-10-12 **记下「观测里真的有哪几格」**（治「85 张图只打 77 个首领」✗）
        #   ---- 病（详见 docs/08-保证每张图必打首领规划.md §1.7）----
        #     真机 board 常有**分类器没认出来的格**（map18 缺 8 格）⇒ 建盘时 `board = -1`
        #     ⇒ `mapsolve` 把 `board<0` 当"已消耗格"⇒ 它们的 4 邻被判"开局已揭示可点"
        #     ⇒ **雾里的 boss 被误判"可点"** ⇒ 求解器给出"一步直接打 boss" ⇒
        #       真机 `fogged_noop`（它其实在雾里）⇒ `no_progress` 退图 ⇒ **首领漏打** ✗✗
        #   ---- 闸门早已存在，但输入缺失 ----
        #     `mapsolve._build_cache` 的 `EMPTY_ADJ`（`:458-463`）**本来就写了**这道闸门：
        #       「观测里根本没有这一格 ⇒ 不许拿它当已消耗去揭示邻居」，
        #       判据 = `if _obs_cells and c not in _obs_cells: continue`
        #     ⚠ 但 `from_observation` / `_from_anchors` **从来没设过 `sim.obs_cells`**
        #       ⇒ `_obs_cells` 恒为空
        #       ⇒ `if _obs_cells and …` **恒不成立** ⇒ **闸门形同虚设** ✗✗
        #       （= 本项目反复出现的"判据静默失效"：判据建在拿不到数据的地方）
        #   ⇒ 修法：**把闸门缺的那个输入补上**（不改闸门本身、不加新判据 ✓）
        _sim = (cls._from_anchors(cells, spot_table)
                if any(isinstance(v, dict) and v.get('anchor') for v in cells.values())
                else None)
        if _sim is not None:
            cls._mark_obs_cells(_sim, cells)
            return _sim
        board = [-1] * NCELL
        idx_of = {}
        blocks = []
        for (r, c) in sorted(cells):
            sid = cells[(r, c)].get('sid') or cells[(r, c)].get('name')
            # ⚠ 只有 **SpotSize>1 的大地块**才跨格；1 格地块（草地/海螺…）各自独立 ✗
            #   （否则相邻同 sid 的草地会被并成一大块，块数/体力/揭示全算错）
            size = int((spot_table.get(sid) or {}).get('SpotSize') or 1)
            if group and size > 1:
                for (dr, dc) in ((-1, 0), (0, -1)):
                    nb = (r + dr, c + dc)
                    if nb in idx_of and (cells.get(nb, {}).get('sid') or
                                         cells.get(nb, {}).get('name')) == sid:
                        bi = idx_of[nb]
                        board[cell_of(r, c)] = bi
                        blocks[bi].cells.append(cell_of(r, c))
                        idx_of[(r, c)] = bi
                        if cells[(r, c)].get('marks'):
                            blocks[bi].mark = (cells[(r, c)]['marks'] or [None])[0]
                        # ⭐ 2026-10-02：合并进来的成员带着营地标记 ⇒ 标到整块上 ✓
                        #   （营地被多格块吞掉时**走的就是这条路**，必须在 merge 分支里也接住）
                        if cells[(r, c)].get('camp'):
                            blocks[bi].camp = True
                            # ⭐ 只记这一格当"揭示源"（多格块不许整块当营地）✓
                            if cell_of(r, c) not in blocks[bi].camp_cells:
                                blocks[bi].camp_cells.append(cell_of(r, c))
                        break
                else:
                    size = 1        # 合并失败 → 当作独立块
                if board[cell_of(r, c)] >= 0:
                    continue
            row = dict(spot_table.get(sid) or spot_table.get(cells[(r, c)].get('name')) or {})
            if not row:
                # ⚠ 认不出地块时：**带标记的格绝不能当空地**（否则会被当成连锁揭示的一部分白白消耗）
                has_mark = bool(cells[(r, c)].get('marks'))
                row = {'SpecialSpot': 1 if has_mark else 0, 'SpotSize': 1}
            row = dict(row)
            row['sid'] = sid
            row['name'] = cells[(r, c)].get('name') or sid
            # ⭐⭐⭐ 2026-10-03 **观测里的 `SpotSize` 优先**（用户口径：16 和 17 是同一块、
            #   0.340 分的"9 格海边小屋"是幻觉 ✗）
            #   背景：`explore_loop._cells_for_model` 会把"大块但分数 < 0.55"的格子降级成
            #     单格并写 `SpotSize = 1` ✓，但**这里 `row` 是单独从地块表构造的** ⇒
            #     降级到不了模型 ⇒ 仍按 9 格 ×2 = **18 体** 计价（两格 36 体、总价 40 ✗✗）
            #   （与 368 行营地那条是**同一类坑**——那次就是"表构造的 row 收不到单格路的字段"✗）
            _sz_obs = cells[(r, c)].get('SpotSize')
            if _sz_obs:
                try:
                    row['SpotSize'] = int(_sz_obs)
                except Exception:       # noqa: BLE001
                    pass
            # ⭐ 同上：单格路上也把"实际占几格"告诉 Block（这里恒为 1 格 ✓）
            row['cells'] = [(r, c)]
            if 'target' in cells[(r, c)]:              # ⭐ 目标白名单（targets_cfg）✓
                row['want'] = bool(cells[(r, c)].get('target'))
            # ⭐ 2026-10-03 拉黑标（同 `_from_anchors` ✓）：求解器据此不点、也不借它走 ✓
            if 'blocked' in cells[(r, c)]:
                row['blocked'] = bool(cells[(r, c)].get('blocked'))
            if cells[(r, c)].get('camp'):              # ⭐ 2026-10-02：营地标记 ✓
                row['camp'] = True
                row['camp_cells'] = [cell_of(r, c)]
            b = Block(len(blocks), row, revealed=bool(cells[(r, c)].get('revealed')),
                      mark=((cells[(r, c)].get('marks') or [None])[0]))
            board[cell_of(r, c)] = b.idx
            b.cells = [cell_of(r, c)]
            idx_of[(r, c)] = b.idx
            blocks.append(b)
        _sim = cls(board, blocks)
        cls._mark_obs_cells(_sim, cells)
        return _sim

    @staticmethod
    def _mark_obs_cells(sim, cells):
        """记下「观测里真的有哪几格」⇒ 供 `mapsolve` 的 `EMPTY_ADJ` / `consumed_cells` 闸门用 ✓

        ⭐⭐⭐⭐ 2026-10-12 新增（治「85 张图只打 77 个首领」✗，见 `from_observation` 顶部注释）：
          语义 = **观测真实覆盖的格集合**（`cells` 的键）。
          ⚠ 为什么必须是"观测覆盖"而不是"建出来的块"：
            `board<0` 有两种来源 ——
              ① **真已消耗**（玩家点过 / 连锁吃掉）⇒ 观测里**没有这一格**（游戏里它已空）
              ② **分类器没认出来**（雾太厚/被面板挡）⇒ 观测里**也没有这一格**，但它**不是空的**！
            而 `mapsolve` 现在把两者**一律当"已消耗"** ⇒ ② 的邻居被误判"可点" ✗✗
            闸门要拦的正是 ②：**观测里没有这一格 ⇒ 不许拿它当已消耗**。
          ⚠ 与 `from_observation` 那条路**同一口径**，两处必须一致 ✓
          ⚠ 容错：任何异常 ⇒ `obs_cells = set()`（= 闸门不启用，行为与修前完全一致 ✓
            —— fail-open，绝不因为一个记账失败把整张图改坏）
        """
        try:
            sim.obs_cells = {cell_of(r, c) for (r, c) in cells}
        except Exception:                   # noqa: BLE001
            sim.obs_cells = set()

    @classmethod
    def _from_anchors(cls, cells, spot_table):
        """⭐ 按 `anchor` 字段归组建盘（真机占格；见 `from_observation` 的说明）

        · 每个 **anchor 值** = 一个地块；`cells` = 所有 anchor 指向它的格（含成员格 ✓）
        · 块尺寸/SpecialSpot 一律**查地块表**（成员格只是占格信息，不参与算尺寸）
        · 标记：锚点优先，成员格兜底（boss 图标可能画在成员格上）
        """
        grp = {}
        for k, v in cells.items():
            a = tuple(v.get('anchor') or k)
            # ⭐⭐⭐ 2026-10-03 根因修复（用户口径：「**只有相连的空地才能连锁**」✓）
            #   真机实证（`runs/r_184822_0.png`）：同一 anchor 里混了 **001 草地** 与
            #   **211 巨大沙堡** ⇒ 块 sid 取 head 的 `_001` ⇒ `plain=True` ⇒
            #   `plain_group` 连锁穿过它 ✗ ⇒ 模型"草地片"=18 格、**10 格非草地**
            #   （含 boss (1,4) 椰树、宝箱 (4,3) 0.999 …）⇒ 模型以为"点 (4,1) 一步
            #   连锁吃整片（含 boss）"⇒ 计划直接点雾里的 boss ⇒ **漏打 boss** ✗✗
            #   ⇒ **分组键改成 `(anchor, sid)`**：同 anchor 内不同 sid ⇒ 各建一块 ✓
            #     （不动函数体、不重新缩进 ⇒ 出错面最小 ✓；每组仍按原路径完成
            #      row → Block() → board[] → blocks.append 的全套记账 ✓）
            _sid_k = str(v.get('sid') or '')
            grp.setdefault((a, _sid_k), []).append(k)
        board = [-1] * NCELL
        blocks = []
        for _key in sorted(grp):
            a = _key[0]                          # ⭐ 键 = (anchor, sid) ✓
            members = sorted(grp[_key])
            head = dict(cells.get(a) or cells[members[0]] or {})
            sid = (_key[1] or head.get('sid') or head.get('name'))     # ⭐ 用本组的 sid ✓
            row = dict(spot_table.get(sid) or {})
            marks = list(head.get('marks') or [])
            for m in members:
                for mk in (cells[m].get('marks') or []):
                    if mk not in marks:
                        marks.append(mk)
            if not row:
                # ⚠ 认不出地块时：**带标记的格绝不能当空地**（同 from_observation ✓）
                has_mark = bool(marks)
                row = {'SpecialSpot': 1 if has_mark else 0, 'SpotSize': 1}
            row = dict(row)
            # ⭐ 2026-10-03 同上（这条 `_from_anchors` 路）：**观测里的 `SpotSize` 优先** ✓
            #   （低分大块被 `_cells_for_model` 降级成单格 ⇒ 这里要接住 `SpotSize=1` ✓
            #    否则仍按 9 格 ×2 = 18 体计价 ✗）
            _sz_obs = head.get('SpotSize')
            if _sz_obs:
                try:
                    row['SpotSize'] = int(_sz_obs)
                except Exception:       # noqa: BLE001
                    pass
            # ⭐⭐⭐ 2026-10-03 用户口径：「**两块不应该是 4 体吗**」✓
            #   ⇒ 把"这一块**实际占了几格**"塞进 row（`Block.__init__` 会取
            #     `min(SpotSize, len(cells))` ⇒ 9 格模板 + 实际 2 格 ⇒ 按 2 格计价 ✓
            #     战斗 ⇒ 2×2 = **4 体** ✓；不这么做 `row` 里没有 cells ⇒ 仍按 9 算 18 体 ✗）
            try:
                row['cells'] = [tuple(x) for x in members]
            except Exception:           # noqa: BLE001
                pass
            #   真机铁证（离线复算 r_233023_0.png）：营地格 (2,1) 属于多格块
            #   `巨大沙堡`（anchor=(1,1)）⇒ **走的就是 `_from_anchors` 这条路**，
            #   而这里 `row` 是**单独从地块表构造**的 ⇒ 我在 `from_observation` 单格路上
            #   加的 `row['camp']` **到不了这里** ⇒ `Block.camp=False` ⇒
            #   `Problem.camp=None` ⇒ 揭示链没有起点 ⇒ 求解器 `exhausted`（整图干等）✗
            #   ⇒ 锚点或任一成员格带 camp 标记，就标到整块上 ✓
            if head.get('camp') or any((cells.get(m) or {}).get('camp') for m in members):
                row['camp'] = True
                # ⭐ 只把**真正带 camp 标记的格子**记成"揭示源"（不是整块）✓
                row['camp_cells'] = [cell_of(*m) for m in members
                                     if (cells.get(m) or {}).get('camp')]
            grew = head.get('revealed')
            if grew is None:
                grew = any(cells[m].get('revealed') for m in members)
            # ⭐⭐⭐ v1.06 修**多格块丢剪影**（真机 A/B 抓出来的真根因）：
            #   块的代表格（anchor）**常常是平坦的那一格**，而成员的剪影各不相同 ——
            #   真机铁血高地实证：`(5,3)` 属于 6 格块 anchor=(3,2)，anchor 剪影 0.016（平坦）
            #   但 `(5,3)` 自己 0.271（下面是大木桩！）⇒ 旧代码只读 anchor ⇒
            #   整块被当成空地 ⇒ **连锁穿过大木桩** ✗✗（= 用户最初报的那个现象）
            #   ⇒ 取**成员里剪影最大的那个**（只要有任一成员看出有东西，整块就非空地 ✓）
            _sils = [float(cells[m].get('fog_sil')) for m in members
                     if cells[m].get('fog_sil') is not None]
            # ⭐ 2026-10-05 把**分类器置信度**也搬进块（`Block.plain` 判"是不是内容地块"要用 ✓）
            _scs = [float((cells.get(m) or {}).get('score') or 0.0) for m in members]
            if _scs:
                row['score'] = max(_scs)
            if _sils:
                row['fog_sil'] = max(_sils)
                # ⭐⭐⭐ 2026-10-05 **优先用观测里已经判好的 `fog_object`**（用户报「不是最优步数」）
                #   `spots.cells()` 现在按**本帧众数**算阈值（`max(0.04, 众数×1.6)`）——
                #   因为不同地图的空地底纹不一样：铁血高地 草地 0.014~0.016（老阈值 0.04 合适），
                #   而废弃矿洞 **岩地自带岩石底纹 0.126** ⇒ 老阈值把每格空地都判成"有东西"
                #   ⇒ `plain=False` ⇒ **连锁全断** ⇒ 规划被迫一格一格点（9 步/28 体力 ✗✗）
                #   ⇒ 这里**沿用观测的结论**，别再用模块常量重算一遍（否则前面的修正白做 ✗）
                _fobj_obs = [bool((cells.get(m) or {}).get('fog_object')) for m in members
                             if (cells.get(m) or {}).get('fog_object') is not None]
                if _fobj_obs:
                    row['fog_object'] = any(_fobj_obs)     # 任一成员有东西 ⇒ 整块非空地 ✓
                else:
                    row['fog_object'] = bool(row['fog_sil'] >= FOG_SIL_MIN)
                row['fog_flat'] = not row['fog_object']
            row['sid'] = sid
            row['name'] = head.get('name') or sid
            if 'target' in head:                       # ⭐ 目标白名单（targets_cfg）✓
                row['want'] = bool(head.get('target'))
            # ⭐ 2026-10-03 拉黑标（用户口径："一开始就不规划拉黑的" ✓）
            #   块级 row 是从数据表构造的 ⇒ 观测字段必须显式搬过来 ✓（否则到不了模型 ✗）
            if 'blocked' in head:
                row['blocked'] = bool(head.get('blocked'))
            b = Block(len(blocks), row, revealed=bool(grew),
                      mark=(marks[0] if marks else None))
            b.cells = [cell_of(*m) for m in members
                       if 0 <= m[0] - 1 < ROWS and 0 <= m[1] - 1 < COLS]
            for c in b.cells:
                board[c] = b.idx
            blocks.append(b)
        return cls(board, blocks)

    def _infer_revealed(self):
        """按游戏连锁规则反推可见性：与空格（已消耗）4 邻接的格 = 已揭示"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if b.revealed or b.gone:
                continue
            r, c = i // COLS, i % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                if self.board[rr * COLS + cc] < 0:
                    b.revealed = True
                    break

    # ---------- 观测 ----------
    def visible(self):
        """当前"能点"的格子 = 未消耗且已揭示"""
        return [rc_of(i) for i in range(NCELL)
                if self.board[i] >= 0 and not self.blocks[self.board[i]].gone
                and self.blocks[self.board[i]].revealed]

    def fogged(self):
        return [rc_of(i) for i in range(NCELL)
                if self.board[i] >= 0 and not self.blocks[self.board[i]].gone
                and not self.blocks[self.board[i]].revealed]

    def fogged_marks(self):
        """未揭示但带标记的格（boss 常常这样：看得到标记、点不动）"""
        out = []
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if not b.gone and not b.revealed and b.mark:
                out.append((rc_of(i), b.mark))
        return out

    def targets(self, want=('mark', 'buy')):
        """目标集合（跟探索循环一致：标记格 ∪ 商人/宝库）

        ⚠ 按**地块**去重：多格大块（blockSize>1，例如 2×2 的 boss 块）只算一个目标，
          锚点取该块最左上的格子（跟真机里"一格代表整块"一致）
        """
        out = []
        seen = set()
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0 or bi in seen:
                continue
            b = self.blocks[bi]
            if b.gone:
                continue
            hit = ('mark' in want and b.mark) or ('buy' in want and b.is_buy)
            if hit:
                seen.add(bi)
                out.append(rc_of(b.cells[0] if b.cells else i))
        return sorted(set(out))

    def done(self):
        """目标都清完了吗（商人/宝库要看是否已消耗）"""
        return not self.targets()

    # ---------- 规则（1:1 移植） ----------
    def connected_plain(self, start_cell):
        """源码 GetConnectedPlainBlocks：BFS 4 邻域，整片连通空地一起返回（块索引集合）"""
        bi = self.board[start_cell]
        if bi < 0:
            return set()
        b = self.blocks[bi]
        if not b.plain:
            return set()
        got, seen_cells, q = {bi}, set(), []

        def enqueue_block(idx):
            for j in range(NCELL):
                if self.board[j] == idx and j not in seen_cells:
                    seen_cells.add(j)
                    q.append(j)

        enqueue_block(bi)
        while q:
            cur = q.pop(0)
            r, c = cur // COLS, cur % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                nidx = rr * COLS + cc
                if nidx in seen_cells:
                    continue
                nb = self.board[nidx]
                if nb < 0:
                    continue
                blk = self.blocks[nb]
                if blk.gone:
                    continue
                # ⭐⭐ 2026-09-28 用户口径：连锁**能穿过雾**（不再要求 revealed）——
                #   真机证据：(1,5) 一次揭开 (1,5)(1,6)(1,7)，而 (1,6)/(1,7) 当时
                #   还是雾格 ⇒ 旧判据 `blk.revealed` 把片截断成 1 格 ✗
                #   （穿透仍只限 `plain`=草地 ⇒ 宝箱/海螺/岩石/营地照旧阻断 ✓）
                if blk.plain:
                    if nb not in got:
                        got.add(nb)
                        enqueue_block(nb)
                    seen_cells.add(nidx)
                    q.append(nidx)
        return got

    def click(self, rc):
        """点一格（1 基行列）。返回 ('plain', 消耗的块数) / ('panel', 块) / ('noop', 原因)"""
        r, c = rc
        idx = cell_of(r, c)
        if not (1 <= r <= ROWS and 1 <= c <= COLS):
            return ('noop', 'out_of_board')
        bi = self.board[idx]
        if bi < 0:
            return ('noop', 'empty')
        b = self.blocks[bi]
        if b.gone:
            return ('noop', 'gone')
        if '营地' in (b.name or ''):
            # ⭐ 2026-09-28：出生地**不可点**（点了只弹一个无用面板，不消耗、不揭示；
            #   explore_loop 已把它当"已完成"直接排除 ✓）
            return ('noop', 'camp')
        if not b.revealed:
            return ('noop', 'fogged')          # 未揭示 = 点不动（实测）
        self.clicks += 1
        if b.plain:
            grp = self.connected_plain(idx)
            # ⭐ 2026-09-28 修：空地**固定 1 点**（连锁吃掉多少格都一样，用户 2026-09-27 口径）。
            #   旧代码 `charge(Σ block_cost)` 与 mapsolve.step_cost 的"固定 1 点"不一致 ✗
            self.charge(1)
            for k in grp:
                self.blocks[k].gone = True
                for j in range(NCELL):
                    if self.board[j] == k:
                        self.board[j] = -1
            self._reveal_neighbours()
            self.log.append(('plain', rc, len(grp), len(self.visible())))
            return ('plain', len(grp))
        # 非空地：开面板。这里只把"面板结果"告诉策略层（战斗/购买由外层决定）
        self.charge(self.block_cost(b))
        self.log.append(('panel', rc, b.name, b.mark))
        return ('panel', b)

    def resolve_panel(self, rc, do_buy=True, do_fight=True):
        """面板处理结果（模拟外层策略）：商人/宝库买完 → 消耗；战斗格打完 → 消耗"""
        r, c = rc
        bi = self.board[cell_of(r, c)]
        if bi < 0:
            return None
        b = self.blocks[bi]
        if b.is_buy:
            if not do_buy:
                return None
            b.gone = True
        elif do_fight:
            b.gone = True                  # 打完这一格就消耗掉（实测：战斗格打完会消失/变新遭遇）
        if b.gone:
            for j in range(NCELL):
                if self.board[j] == bi:
                    self.board[j] = -1
            self._reveal_neighbours()
        return b

    def _reveal_neighbours(self):
        """消耗地块后：相邻格解锁为「已揭示」（实测：RemoveBlock → SetBlockVisible 连锁揭示）"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if b.gone or b.revealed:
                continue
            r, c = i // COLS, i % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                if self.board[rr * COLS + cc] < 0:       # 邻居是空格（刚被消耗）⇒ 解锁
                    b.revealed = True
                    break

    # ---------- 指标 ----------
    def stats(self):
        return {'clicks': self.clicks,
                'stamina': self.stamina,
                'left_targets': len(self.targets()),
                'left_cells': sum(1 for i in range(NCELL) if self.board[i] >= 0),
                'visible': len(self.visible())}

    def render(self):
        """文字棋盘：已揭示=大写首字，未揭示=小写，空格='.'，标记加 *"""
        lines = []
        for r in range(1, ROWS + 1):
            row = []
            for c in range(1, COLS + 1):
                i = cell_of(r, c)
                bi = self.board[i]
                if bi < 0:
                    row.append(' .')
                    continue
                b = self.blocks[bi]
                ch = (b.name or '?')[0]
                if not b.revealed:
                    ch = ch.lower()
                if b.mark:
                    ch = ch.upper() if b.revealed else ch
                row.append(('%s%s' % ('*' if b.mark else '', ch))[-2:])
            lines.append(' '.join(row))
        return '\n'.join(lines)


    def spawn_cell(self):
        """出生地 = 「营地」那一格（跟真机一样从地块名认；认不出就退回第一个已揭示格）"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if not b.gone and '营地' in (b.name or ''):
                return rc_of(i)
        vis = self.visible()
        return vis[0] if vis else (1, 1)


# ---------------- 策略层（把 explore_loop 的规则搬进来，作为基线） ----------------
class BaselinePolicy:
    """探索循环当前策略的等价实现（用于离线评估）"""

    name = 'baseline：目标=标记∪商人宝库 / 直线开路 / 严格交替'

    def __init__(self, max_click=60):
        self.max_click = max_click
        self.black = set()

    @staticmethod
    def _line(a, b):
        """Bresenham 直线取格（跟 explore_loop.line_cells 同一套）"""
        (r0, c0), (r1, c1) = a, b
        dr, dc = abs(r1 - r0), abs(c1 - c0)
        sr = 1 if r1 >= r0 else -1
        sc = 1 if c1 >= c0 else -1
        err = dr - dc
        r, c = r0, c0
        out = []
        for _ in range(dr + dc + 3):
            out.append((r, c))
            if (r, c) == (r1, c1):
                break
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc
        return out

    def run(self, sim, spawn=None, verbose=False, cost_first=False):
        """cost_first=True：直线上的开路格**按体力成本排序**（便宜优先），同成本按离目标近

        ⭐ 2026-09-25 用离线最优解当标尺验证：基线只比理论最优多花 ~13-32% 体力，
          而两次"重写"（纯贪心 / 直线成本重写）都明显更差 ✗ ⇒ 骨架保留，只加这一条纪律。
        """
        spawn = spawn or sim.spawn_cell()
        while sim.clicks < self.max_click and not sim.done():
            vis = [p for p in sim.visible() if p not in self.black]
            tgs = sim.targets()
            if not tgs:
                break
            # ① 目标自己能点 → 直接点（商人/宝库顺手买掉；战斗格打完消耗）
            for t in tgs:
                if t in vis:
                    kind, info = sim.click(t)
                    if kind == 'panel':
                        sim.resolve_panel(t, do_buy=True, do_fight=True)
                    break
            else:
                # ② 目标点不动（未揭示）→ 沿「出生地→目标」直线开路
                road = []
                for t in tgs:
                    for p in self._line(spawn, t):
                        if p in vis and p not in road and p != t:
                            road.append(p)
                # ③ 走廊兜底（|d(出生地,格)+d(格,目标)-d(出生地,目标)| ≤ 2，跟真机一致）
                if not road:
                    for t in tgs:
                        d_st = abs(spawn[0] - t[0]) + abs(spawn[1] - t[1])
                        near = sorted(
                            (p for p in vis if p not in road),
                            key=lambda p: (abs(abs(p[0] - spawn[0]) + abs(p[1] - spawn[1])
                                               + abs(p[0] - t[0]) + abs(p[1] - t[1]) - d_st) > 2,
                                           abs(p[0] - t[0]) + abs(p[1] - t[1])))
                        if near:
                            road.append(near[0])
                pick = road[0] if road else (vis[0] if vis else None)
                if cost_first and road:
                    # ⭐ 便宜优先：1 格空地(1 体) 永远排在大块内容格(4~8 体) 前面
                    def _cost(p):
                        bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                        return sim.block_cost(sim.blocks[bi]) if bi >= 0 else 99
                    road = sorted(road, key=_cost)
                    pick = road[0]
                if pick is None:
                    break
                kind, info = sim.click(pick)
                if kind == 'noop':
                    self.black.add(pick)          # 点不动（雾/空）→ 本地拉黑，别再选它
                elif kind == 'panel':
                    # ⚠ 非目标面板：
                    #   · 商人/宝库 → 买掉并消耗 ✓
                    #   · 带战斗标记 → 打完消耗 ✓
                    #   · **其他内容格（宝箱/海螺/巨大沙堡/椰树…）→ 点了会消耗掉、并连锁揭示** ✓
                    #     （真机就是这么开路的；只有「营地」点了不消耗 ⇒ 必须拉黑，否则死循环）
                    b = info
                    if b.is_buy:
                        sim.resolve_panel(pick, do_buy=True, do_fight=False)
                    elif b.mark:
                        sim.resolve_panel(pick, do_buy=False, do_fight=True)
                    elif '营地' in (b.name or ''):
                        self.black.add(pick)
                    else:
                        sim.resolve_panel(pick, do_buy=False, do_fight=True)
        return sim.stats()


# ---------------- 从真实截图采样建盘 ----------------
def sim_from_shot(path, spots_mod, limits=None):
    """用我们的分类器把一张真实截图变成模拟器棋盘（真实布局 ✓）"""
    from spots import imread
    img = imread(path)
    if img is None:
        return None
    st = None
    for code in ('S00003', 'S00002', 'S00001'):
        try:
            st = spots_mod.Board(code).state(img)
            if st:
                break
        except Exception:       # noqa: BLE001
            st = None
    if not st:
        return None
    cells = {}
    for (r, c), v in st.items():
        if v.get('anchor') != (r, c):
            continue
        cells[(r, c)] = {'sid': v.get('sid'), 'name': v.get('name'),
                         'revealed': bool(v.get('revealed')),
                         'marks': list(v.get('marks') or [])}
    # ⭐ 标记（首领/红装/点赞/幸运草）是**另一个模板匹配器**扫出来的，不在分类器输出里 —— 必须合并
    try:
        import marks as marks_mod
        for (r, c), mv in (marks_mod.scan_board(img, thr=0.85) or {}).items():
            if (r, c) in cells:
                got = list(cells[(r, c)].get('marks') or [])
                for m in (mv.get('marks') or []):
                    if m not in got:
                        got.append(m)
                cells[(r, c)]['marks'] = got
    except Exception:       # noqa: BLE001
        pass
    if len(cells) < 12:
        return None
    return MapSim.from_observation(cells, spots_mod.spot_rows())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', help='用这张截图建盘并跑一遍基线策略')
    ap.add_argument('--bench', type=int, default=0, help='从 runs/ 采样 N 张建盘跑基线策略')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    import spots as spots_mod

    if a.selftest:
        # 自检：一块空地点击 → 只吃连通的那一片；未揭示格点不动
        spots = {'草地': {'SpecialSpot': 0, 'SpotSize': 1, 'sid': 'P'},
                 '宝箱': {'SpecialSpot': 3, 'SpotSize': 1, 'sid': 'C'},
                 '首领': {'SpecialSpot': 5, 'SpotSize': 1, 'sid': 'B'}}
        cells = {}
        for r in range(1, ROWS + 1):
            for c in range(1, COLS + 1):
                if (r, c) == (1, 1):
                    cells[(r, c)] = {'sid': 'P', 'name': '草地', 'revealed': True}
                elif (r, c) == (1, 2):
                    cells[(r, c)] = {'sid': 'C', 'name': '宝箱', 'revealed': True}
                elif (r, c) == (3, 3):
                    cells[(r, c)] = {'sid': 'B', 'name': '营地', 'revealed': True,
                                     'marks': ['boss']}
                else:
                    cells[(r, c)] = {'sid': 'P', 'name': '草地', 'revealed': False}
        sim = MapSim.from_observation(cells, spots)
        print('自检棋盘：')
        print(sim.render())
        print('可点格:', sim.visible())
        print('未揭示但带标记:', sim.fogged_marks())
        kind, info = sim.click((1, 1))
        print('点(1,1) →', kind, info, '（应当只吃连通空地）')
        kind, info = sim.click((5, 7))
        print('点未揭示的(5,7) →', kind, info, '（应当是 fogged 点不动）')
        print('点完可点格:', sim.visible())
        return

    if a.sample:
        sim = sim_from_shot(a.sample, spots_mod)
        if sim is None:
            print('建盘失败（截图里可用格子太少）')
            return
        print('=== 从 %s 建盘 ===' % os.path.basename(a.sample))
        print(sim.render())
        print('目标:', sim.targets())
        print('点不动的标记:', sim.fogged_marks())
        pol = BaselinePolicy()
        st = pol.run(sim)
        print('基线策略跑完:', st)
        return

    if a.bench:
        base = os.path.dirname(os.path.abspath(__file__))
        # ⚠ 要用「开局那几轮」的截图（棋盘还满着）；中途的截图大量格已被消耗，统计没意义
        files = []
        for pat in ('runs/**/m*_r000.png', 'runs/**/m*_r001.png', 'runs/**/m*_r002.png'):
            files += glob.glob(os.path.join(base, pat), recursive=True)
        random.seed(7)
        random.shuffle(files)
        rows, ok = [], 0
        for f in files:
            if ok >= a.bench:
                break
            sim = sim_from_shot(f, spots_mod)
            if sim is None:
                continue
            ok += 1
            before = sim.stats()
            st = BaselinePolicy().run(sim)
            rel = os.path.relpath(f, base).replace('\\', '/')
            rows.append((rel, before['left_cells'], before['left_targets'],
                         st['clicks'], st['left_targets']))
        if not rows:
            print('没采到可用棋盘')
            return
        import statistics
        print('采样 %d 局（基线策略）：' % len(rows))
        print('  %-30s %6s %6s %7s %8s' % ('截图', '剩余格', '目标数', '点击数', '剩余目标'))
        for r in rows[:20]:
            print('  %-30s %6d %6d %7d %8d' % r)
        clicks = [r[3] for r in rows]
        left = [r[4] for r in rows]
        tgt = [r[2] for r in rows]
        witht = [r for r in rows if r[2] > 0]
        print('  总样本 %d；其中「有目标」的 %d 局' % (len(rows), len(witht)))
        if witht:
            print('  有目标局：平均点击 %.1f（中位 %.1f，最多 %d）；未清完 %d/%d'
                  % (statistics.mean([r[3] for r in witht]),
                     statistics.median([r[3] for r in witht]),
                     max(r[3] for r in witht),
                     sum(1 for r in witht if r[4] > 0), len(witht)))
        print('  全部局：平均点击 %.1f；平均目标数 %.1f；未清完目标的局数 %d/%d'
              % (statistics.mean(clicks), statistics.mean(tgt),
                 sum(1 for x in left if x > 0), len(rows)))


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
