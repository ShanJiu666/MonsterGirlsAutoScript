# -*- coding: utf-8 -*-
"""mapsolve.py · **最优策略搜索（按体力最省）**（地图/探索层）

⭐ 目标函数 = **消耗体力最少**（用户 2026-09-25：「要按消耗体力最少的方案走」），不是点击次数。

体力公式（源码 82956-82992 MapBlock）：
    singleEnergyConsume  = SpotSize        # 点普通格/空地
    fightEnergyConsume   = SpotSize * 2    # 战斗格
    exploreEnergyConsume = SpotSize * 2    # 探索产出格
    （传送门块 = 0；进图另收 mapExploreEnergyCost = 25，与地图内策略无关）
    实测印证：我们统计里"进图体力 −25"就是这么来的 ✓

为什么能求最优：点击结果是确定性的（空地→连通整片消耗；内容格→消耗该块），
状态只由「已消耗的地块集合」决定 ⇒ 用 **Dijkstra（按体力边权）** 求到目标态的最小体力 ✓

状态：
    state = frozenset(已消耗 block idx)
    可见 = 营地 ∪ 与已消耗格 4 邻接的块；目标 = 带标记 ∪ 商人/宝库（未消耗）
    动作 = 点一个可见未消耗块；代价 = 该块（或整片空地）的体力
    目标态 = 所有目标块都被消耗

用法：
    python mapsolve.py --bench 200 --map 夏日海滩 --difficulty 100
        → 同 200 张盘上对比「基线策略」vs「体力最优」的体力与点击数
"""
import argparse
import heapq
import io
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROWS, COLS = 5, 7
NCELL = ROWS * COLS
# ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**战斗格的体力需要是格数×2，拦路那个消耗 6 体啊**」
#   ⇒ 补进 `拦路`：拦路格**定义上就是战斗**（真机日志：「开打 · 拦路格（标记 ['拦路']）」✓）
#   真机事故（acc1 `gui_20261003_140308` 第 2 张图）：计划里的 `2,6`（S00003_111，格数 3）
#     被定价成 **3**（掉到"内容格·探索"那档 ✗），而它实际是**拦路战斗** ⇒ 应为 **3×2=6** ✓
#     ⇒ 求解器把"要打的架"少算一半 ⇒ 挑出"看起来便宜、实际更贵"的路 ✗
FIGHT_X2 = {'boss', 'redEquip', 'recommend', 'battle', '拦路'}      # 战斗格：体力 ×2


def rc_of(idx):
    """cell 索引 -> 1 基 (r, c)（与 `mapsim.rc_of` 同口径）"""
    return idx // COLS + 1, idx % COLS + 1


class Problem:
    """把一张盘编译成"搜索用"的纯数据（不依赖 MapSim 的可变状态）"""

    def __init__(self, sim):
        self.board = list(sim.board)                       # cell -> block idx
        self.blocks = {b.idx: b for b in sim.blocks.values()}
        self.cells_of = {i: [] for i in self.blocks}
        for c, bi in enumerate(self.board):
            if bi >= 0:
                self.cells_of[bi].append(c)
        self.camp = None
        # ⭐⭐⭐ 2026-10-02：**观测里就空的格**（`board<0`）单独留一份 ——
        #   用于区分「观测时就已经消耗」和「搜索推演过程中才消耗」：
        #   · 前者（观测消耗）揭示过的块，**观测里本应看得见** ⇒ 若观测说是雾，
        #     说明"它被消耗"是模型自己的推断（幻影）⇒ 不许据此判"可点" ✓
        #   · 后者（推演消耗）是**多步揭示链**的正常推演 ⇒ 必须放行，
        #     否则目标一旦藏在雾里就永远不可达 ⇒ `exhausted`（无解、整图干等）✗✗
        #   （这两条是 2026-10-02 用真机帧 A/B 出来的：只做前者 ⇒ 无解；只做后者 ⇒ 点雾格）✓
        self.obs_consumed = {c for c in range(NCELL) if self.board[c] < 0}
        # ⭐ 2026-10-02：**观测里真的有哪几格**（`MapSim.from_observation` 记的）——
        #   `_build_cache` 的 `EMPTY_ADJ` 用它做闸门：观测里没有的格不许当"已消耗"✓
        self.obs_cells = set(getattr(sim, 'obs_cells', None) or ())
        for b in self.blocks.values():
            if '营地' in (b.name or ''):
                self.camp = b.idx
        # ⭐⭐⭐ 2026-10-02 兜底：按块名找不到营地时，用观测里**明确标了 camp** 的块
        #   （用户口径：「营地应该最好认吧，稳定是揭示状态的，**先固定下来营地**？」
        #     —— 营地恒已揭示、sid 后缀 000、score≈0.998，是最稳的锚点 ✓）
        #   为什么必须有这条：营地格常被多格块吞掉 ⇒ 块名不是"营地" ⇒ 原来的
        #   `camp=None` ⇒ 揭示规则「与营地/已消耗格 4 邻」**没有起点** ⇒ 求解器
        #   `exhausted` 无解 ⇒ 整张图干等退图（真机 23:30 那把铁证）✗✗
        if self.camp is None:
            for b in self.blocks.values():
                if getattr(b, 'camp', False):
                    self.camp = b.idx
                    break
        # ⭐⭐⭐ 2026-10-02 **营地的揭示源 = 营地那一格**（不是整个多格块）——
        #   离线铁证：营地 (2,1) 属于 4 格块 `巨大沙堡` ⇒ 拿整块当揭示源时，
        #   boss(1,2)（与 (1,1)/(2,2) 相邻）会被判"可点" ⇒ 又排进计划、真机是雾格 ✗✗
        #   ⇒ 优先用 Block.camp_cells（真正带 camp 标记的格）；没有就退回整块（单格营地情形 ✓）
        self.camp_cells = set()
        if self.camp is not None:
            _cb2 = self.blocks.get(self.camp)
            self.camp_cells = (set(getattr(_cb2, 'camp_cells', None) or ())
                               or set(self.cells_of.get(self.camp, ())))
        self.targets = set()
        for b in self.blocks.values():
            # ⭐⭐⭐ 2026-09-28 用户要求（「勾选某一种方块，后续就专门去拿；不勾就不规划」）：
            #   `Block.want` 由调用方（explore_loop + `targets_cfg` 白名单）明确给出 ⇒ **以它为准** ✓
            #     want=True  ⇒ 进目标（哪怕没标记：宝箱/海螺/多格建筑… ✓）
            #     want=False ⇒ **不进目标**（哪怕挂着 boss 标记、是商人 ⇒ 用户就是不要 ✓）
            #   want=None（老调用：mapevolve 等）⇒ 退回老口径 `mark or is_buy` ✓ 向后兼容
            want = getattr(b, 'want', None)
            hit = (bool(want) if want is not None else bool(b.mark or b.is_buy))
            if hit:
                self.targets.add(b.idx)

    # ---------- 状态派生 ----------
    def consumed_cells(self, state):
        """「已消耗的格」= 观测里**本来就是空的格**（`board < 0`）+ 本状态吃掉的格

        ⭐⭐ 2026-09-30 修（保真度核心，离线对拍抓到）：
            旧实现只算 `state` ⇒ 从**空集**起步 ⇒ 模型以为"一步都没走过"，
            于是 `visible()` 只剩「营地四邻」⇒ 已经走出去的地图完全看不见 ✗✗
            —— 真机表现就是「每轮都从营地重新起步、走法明显不是最优」。
            而"哪一格已经空了"**观测里本来就有**（消耗掉的格没有地块美术 ⇒
            `MapSim.from_observation` 建盘时 board = -1 ✓）
            ⇒ 必须并进来 ✓
        """
        out = {c for c in range(NCELL) if self.board[c] < 0}
        # ⭐⭐⭐⭐ 2026-10-12 **补上与 `_build_cache.EMPTY_ADJ` 对称的 `obs_cells` 闸门**
        #   （治「85 张图只打 77 个首领」✗；与 `mapsim.from_observation` 那处修复配套）
        #   ---- 病 ----
        #     `board<0` 有两种来源：① 真已消耗（观测里没有它，正常）／
        #     ② **分类器没认出来的格**（观测里也没有它，但它**不是空的**）。
        #     旧实现把两者一律当"已消耗" ⇒ ② 的 4 邻被判"开局已揭示可点"
        #     ⇒ **雾里的 boss 被误判可点** ⇒ 求解器规划"一步直接打 boss" ⇒
        #       真机 `fogged_noop` ⇒ `no_progress` 退图 ⇒ **首领漏打** ✗✗
        #     （map18 铁证：缺 8 格 ⇒ 慢版 visible 17 块且含 boss；补闸门后 = 3 块 ✓）
        #   ---- 为什么这里必须也改（不是只改 `_build_cache` 就够）----
        #     README 反复警告"**只改一处 ⇒ A\* 走缓存版白改**"：本函数是**慢版**路径
        #     （`Problem.visible()` / `step()` 用它），`_build_cache.EMPTY_ADJ` 是快版；
        #     两处口径必须一致，否则两条路径给出**不同计划** ✗（`_build_cache` 的注释
        #     自己写着"两处必须一致"）。
        #   ⚠ 方向安全 / fail-open：`obs_cells` 为空（老调用 / 全知盘 / 记账失败）⇒
        #     本闸门**不启用**，行为与修前**一字不变** ✓
        _obs_cells = set(getattr(self, 'obs_cells', None) or ())
        if _obs_cells:
            out = {c for c in out if c in _obs_cells}
        for bi in state:
            out.update(self.cells_of.get(bi, ()))
        return out

    def block_revealed(self, bi, consumed):
        """块 bi 在「已消耗格集合 = consumed」下**是否已揭示**（能点）

        ⭐ 2026-09-30 新增。揭示规则（真机 + `mapsim._reveal_neighbours` 同口径）：
            块已揭示 ⟺ 块内某格与「营地的任一格」或「任一已消耗格的任一格」4 邻接
          （营地开局自带揭示 ✓）
        """
        if bi < 0:
            return False
        if self.camp is not None and bi == self.camp:
            return True
        # ⭐⭐⭐ 2026-10-02（用户报「**规划错了**」）**观测闸门** —— 治"计划去点雾格"
        #   原来这条判据**纯邻接推演**（只与营地/已消耗格 4 邻接），**完全不看观测**：
        #   只要模型相信"某个格已被消耗"（哪怕它其实还是雾），它**旁边的雾格**就会被判
        #   "已揭示/可点" ⇒ 计划里出现点不动的格 ⇒ 真机 `fogged_noop` 空转 ⇒
        #   整条计划错位、漏目标 ✗✗
        #   真机铁证（gui_20261002_232950 / loop_log）：
        #     #11 done_cells_dropped: 4 格 (1,1 2,1 2,2 2,3)   ← 被推断成"已消耗"并删出模型
        #     #12 solver ok: order ["1,2","2,4"]
        #     #13/#14 tap: fogged_noop (1,2) ratio 0.665 / (2,4) ratio 0.717  ← 真机是雾 ✗
        #   这与 `explore_loop.py:895` 记的 v0.99 事故**是同一类**（那里注释第一条就写着
        #   "相邻的雾格被判已揭示/可点 ⇒ 计划里出现点不动的格"）。
        #   ⇒ 加闸门：块内必须**在观测里就有一格是已揭示的**（`Block.observed`，
        #     由建块时的观测值固定，`_infer_revealed()` 推演出来的不算）才允许判"可点" ✓
        #   ⚠ 方向安全：观测说"已亮"但实际点不动（如被面板挡）仍会在计划里 —— 那是
        #     `tap` 的 nochange/拉黑逻辑管的（这里只管"观测说它是雾"的那一类）✓
        _bb = self.blocks.get(bi)
        _obs = bool(getattr(_bb, 'observed', False)) if _bb is not None else True
        camp_cells = self.camp_cells or ()      # ⭐ 只认"营地那一格"（见 __init__ 说明）✓
        for c in self.cells_of.get(bi, ()):
            r, cc = c // COLS, c % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if not (0 <= rr < ROWS and 0 <= ccc < COLS):
                    continue
                n = rr * COLS + ccc
                if n in camp_cells:
                    return True
                # ⚠⚠⚠ 2026-10-01 修**格索引 / 块索引 空间混用**（实测 1556 块里 382 个假阳性）：
                #   `n` 已经是**格索引**、`consumed` 也是**格索引**集合 ⇒ 判据就该是 `n in consumed`
                #   （该邻格本身已被消耗 ⇒ 本块紧邻消耗格 ⇒ 会被揭示 ✓ 语义正确，
                #     也与 explore_loop._infer_chain_consumed 的反推律同口径）
                #   旧写法取 `nb = self.board[n]`（**块 id**）再 `nb in consumed`（**格 id** 集）——
                #   两个索引空间数值范围都是 0..34，肉眼无法区分 ⇒ 只要「邻格所属块的编号」
                #   数值上撞上「某个已消耗格的编号」就误判已揭示 ⇒ 求解器以为点得动，
                #   真机上其实是雾格 ⇒ `fogged_noop` 空转、整条计划错位、漏目标。
                #   另：`board[n] < 0` 的情形已被上面的 `consumed_cells` 全量收集（board<0 ⇔ n∈consumed），
                #   不需要在这里再单独判一次。
                if n in consumed:
                    # ⭐⭐⭐ 2026-10-02 **观测闸门**（只对"观测时就已经消耗"的邻格生效）：
                    #   观测里就空的邻格 ⇒ 它对本块的揭示**在观测里本该看得见**；
                    #   若观测说本块是雾，那"该邻格已消耗"就是模型的推断（幻影）⇒ 不许放行 ✗
                    #   （真机 23:30 那把：4 格被推断成已消耗并删出模型 ⇒ 相邻雾格被判可点）
                    #   反之：`n` 是**搜索推演中**才消耗的 ⇒ 放行（多步揭示链必须能推演）✓
                    if n in self.obs_consumed and not _obs:
                        continue
                    return True
        return False

    def cells_for_plan(self, acts):
        """把搜索出来的 `[(block_idx, 体力)…]` 翻成**每一步真的能点的格**

        ⭐⭐ 2026-09-30 修（离线对拍抓到的核心 bug）：
            `Problem.visible()` 会把**一整片连通空地**去重成"片内最小 idx 的代表块"
            （`REP`）—— 规划语义上是对的（点片里任意一格都连锁消掉整片 ✓），
            但**代表块本身不一定是"已经揭示"的那一块** ✗
            ⇒ 真机点它 = `fogged_noop`；而且点不动 ⇒ 这片空地在下一帧里边界不变、
              揭示集不变 ⇒ **后面整条计划全部错位**（空转 + 漏目标）✗✗
            实测（`_bench_online.py` 60 张盘）：不修时 30/60 张真的清不完目标。
            ⇒ 修法：**逐步推演模型状态**，每一步在目标块（片）里挑一个
              "当下已揭示"的格；片里必有一个已揭示格（否则它进不了 visible ✓）

        返回 [((r, c), block_idx, 体力)…]（1 基行列，与 visible()/rc_of 同坐标系 ✓）
        """
        consumed = set(self.consumed_cells(frozenset()))   # ⭐ 含观测里本来就是空的格 ✓
        out = []
        for bi, w in acts:
            b = self.blocks.get(bi)
            if b is None:
                continue
            # ⭐ 空地：候选格 = **整片**的所有格（bi 只是"片内最小 idx 的代表块"，
            #   它自己很可能还没揭示 ⇒ 必须从整片里挑一个已揭示的格 ✓）
            if b.plain:
                cells = []
                for gb in self.plain_group(bi):
                    cells.extend(self.cells_of.get(gb, ()))
            else:
                cells = list(self.cells_of.get(bi, ()))
            if not cells:
                continue
            # ⭐⭐⭐⭐ 2026-10-05 挑格**必须优先挑"观测里就亮"的那一格**（用户报「规划不对」）
            #   真机铁证（`runs/r_133641_0.png`，营地 (2,5)，boss 目标 (4,6)）：
            #     首步块 4 的 plain 片 = `[(1,6),(2,6),(2,7),(3,5),(3,6)]`，
            #     其中 `(2,6) (3,5)` ratio=1.302 **真亮**，`(2,7) (3,6)` ratio=0.851 **是雾**。
            #     旧代码在这个**无序集合**上跑 `for c in cells: if block_revealed(...)` ——
            #     谁的块先过判据就选谁 ⇒ 这次挑中了**雾格 (2,7)** ✗
            #     ⇒ 真机点它 = 画面无变化（雾格点不动）⇒ `give_up_step` 摘掉 ⇒
            #       后面整条计划错位（模型还以为连锁吃掉了 (3,6) ⇒ 以为 boss 够得着）✗✗
            #   ⇒ 规则：**片里有"观测已亮"的格，就只从那里面挑**（那才是真能点的）；
            #     一个都没有（本该不会发生）才退回原来的邻接判据 ✓
            pick = None
            for c in cells:
                _blk = self.blocks.get(self.board[c])
                if _blk is not None and getattr(_blk, 'observed', False):
                    pick = c
                    break
            if pick is None:
                for c in cells:
                    if self.block_revealed(self.board[c], consumed):
                        pick = c
                        break
            if pick is None:                  # 兜底：整片都没揭示（不该发生）
                pick = cells[0]
            out.append((rc_of(pick), bi, w))
            # ⚠⚠ 2026-10-01 修：原来 `consumed |= (self.plain_group(bi) if b.plain else {bi})`
            #   —— `plain_group` 返回的是**块 id**、`{bi}` 也是**块 id**，
            #   而 `consumed` 全程是**格索引**（`block_revealed` 按格判）⇒ 又一处空间混用 ✗
            #   ⇒ 本步真正被占用的**格**是 `cells`（候选格全部在片内、空地片已全部连锁消耗 ✓）
            #   改用 `cells` 后语义自洽，也顺带覆盖"多格块只点了一格、其余成员仍算已揭示"的漏洞。
            consumed |= set(cells)
        return out

    def visible(self, state):
        """可点格 ✓

        ⭐ 2026-09-27 修正（用户三次口径都指向这件事）：
            「最开始就是只有**营地挨着的四个格子**可以点」
            「规划步数去掉点击出生点那格」
            ⇒ **营地本身不可点** ✗（它只是出生点标记 ✓）
            ⇒ 开局可点 = **营地的四个邻居** ✓（地图生成时就是亮的 ✓）
        可点 = ① 与已消耗格 4 邻接的（连锁揭示 ✓）
               ∪ ② 营地的 4 邻接格（开局起手 ✓）
               ∪ ③ ⭐ 观测里**本来就亮**的格（2026-10-05 新增，见下）
        """
        vis = set()

        def _add_nb(cell):
            r, cc = cell // COLS, cell % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if 0 <= rr < ROWS and 0 <= ccc < COLS:
                    bi = self.board[rr * COLS + ccc]
                    # ⭐ 2026-09-28：**营地永久排除**（它不可点，点了只弹个无用面板、
                    #   不消耗不揭示 —— explore_loop 也把它直接当"已完成"排除 ✓）
                    #   否则 solver 可能安排"点营地"当跳板 ⇒ 真机空转一步 ✗
                    if bi >= 0 and bi not in state and bi != self.camp:
                        vis.add(bi)

        # ① 与已消耗格相邻（连锁揭示出来的 ✓）
        for c in self.consumed_cells(state):
            _add_nb(c)
        # ② 营地的四个邻居（开局起手 ✓）—— 营地自己**不加** ✗
        if self.camp is not None:
            for cc2 in self.cells_of.get(self.camp, ()):
                _add_nb(cc2)
        # ⭐⭐⭐⭐ 2026-10-05 ③ **观测里就亮的格，本来就能点**（用户报「这俩图规划也不对」）
        #   真机铁证（acc2 13:53 第 6 张，`runs/acc2/r_135303_0.png`）：
        #     营地 (1,7)，boss 目标 `(1,1)` 在观测里 ratio=**1.019（明明亮着）**，
        #     但它**不挨着营地、也不挨着任何已消耗格** ⇒ 旧 `visible()` **不含它** ✗
        #     ⇒ 求解器以为"够不着"，规划出一条 **6 步 / 11 体力** 的绕路
        #       `['1,6','1,5','1,4','1,3','1,2','1,1']`（横穿 4 个雾格）
        #     ⇒ 真机连点 4 格才走到 boss，白扔体力；用户原话「这俩图规划也不对」✗✗
        #   ⇒ 观测说"这格是亮的" ⇒ 它就是能点的（游戏里点亮=可交互）⇒ 直接进候选 ✓
        #     （这条**只增不减**：原有的邻接推演一条不动 ⇒ 不会让计划变差，
        #       只会让"明明亮着却要绕路"那类计划消失 ✓）
        #   ⚠ 用 `Block.observed`（建块时**从观测读到**的 revealed，永不被推演改写 ✓）
        #     而不是 `revealed`（会被 `_infer_revealed()` 邻接推演改 ⇒ 会引入幻影可点格 ✗）
        for _bi, _b in self.blocks.items():
            if _bi == self.camp or _bi in state:
                continue
            if getattr(_b, 'observed', False):
                vis.add(_bi)
        return vis

    def plain_group(self, bi):
        """该空地所在的连通空地整片（源码 GetConnectedPlainBlocks）"""
        if not self.blocks[bi].plain:
            return {bi}
        got, seen, q = {bi}, set(), deque([bi])
        while q:
            cur = q.popleft()
            for c in self.cells_of.get(cur, ()):
                r, cc = c // COLS, c % COLS
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    rr, ccc = r + dr, cc + dc
                    if not (0 <= rr < ROWS and 0 <= ccc < COLS):
                        continue
                    nb = self.board[rr * COLS + ccc]
                    if nb < 0 or nb in got or nb in seen:
                        continue
                    # ⭐⭐⭐ 2026-09-28 用户口径修正（真机已证）：连锁**能穿过雾**，
                    #   但**只穿草地**（`plain` 已把营地/宝箱/海螺/岩石等排除 ✓）。
                    #   证据：用户报「点 (1,5) 只揭开 (1,5)(1,6)(1,7) 三格，被宝箱、
                    #   海螺和出生地挡住」+「(2,4)→(5,4) 两步就完事」；真机体力 7 点
                    #   （1+6），而不是本模型旧版算的 8 点（1+1+6）✗。
                    #   ⚠ 09-27 那条「只穿已揭示」是**误诊**：当时"走不通"的真因是
                    #     起点/可点集合把未揭示格也算进去了（`Problem.visible` 管），
                    #     不是连锁范围 ⇒ 用"截断连锁"去治，压住了症状但让片普遍偏小 ✗
                    _nb_b = self.blocks[nb]
                    if _nb_b.plain:
                        seen.add(nb)
                        got.add(nb)
                        q.append(nb)
        return got

    def step(self, state, bi):
        """点一块 → 新状态（空地整片消耗；其他只消耗自己）"""
        if self.blocks[bi].plain:
            return frozenset(state | self.plain_group(bi))
        return frozenset(state | {bi})

    # ---------- 体力代价 ----------
    @staticmethod
    def block_cost(b):
        """体力（按**数据表口径** ✓ 2026-09-27 第二次修）

        数据表 `Area_Spot`：`SpotSize` = 格数（椰树 2 / 游乐设施 4 / 草地 1）
                            `SpecialSpot` = 0 纯地块（连锁）/ 1~4 特殊（弹面板）
        规则：
          空地（连锁）⇒ **固定 1 点** ✓（用户：「空白格都是 1 点，不管连锁多少」✓）
          内容格 · **探索** ⇒ **SpotSize 点** ✓
          内容格 · **战斗** ⇒ **SpotSize × 2 点** ✓
        ⚠ 上一版"非空地一律 2×Size"✗ ⇒ 内容格费用虚高一倍 ⇒ 规划偏保守 ✗（本次修 ✓）
        """
        size = int(getattr(b, 'size', 1) or 1)
        if getattr(b, 'plain', False):          # 空地：连锁 ⇒ 固定 1 点 ✓
            return 1
        # ⭐⭐⭐ 2026-10-03 用户口径：「战斗格 = **格数×2**」⇒ **按地块类型**判定 ✓
        #   原来只看 `b.mark`（boss/红装/大拇指/战斗/拦路）✗ —— 而 `拦路` 是**规划完之后**
        #   才贴的标记（循环发现"计划路径穿过非空地"时才标 ✓）⇒ 规划那一刻它没有标记
        #   ⇒ 要打的架被按"内容格·探索"计价（3 而非 6 ✗）⇒ 平局时选了要打的那条 ✗
        #   真机事故：acc1 gui_20261003_140308 第 2 张图（详见 spots.is_fight_spot 注释 ✓）
        #   ⇒ 现在先问数据表（`EventNum` > 1-1 即战斗型 ✓），表里查不到才退回标记判据 ✓
        try:
            import spots as _sp                 # ⚠ 本模块**故意不 import spots**（数据靠参数传 ✓）
            if _sp.is_fight_spot(getattr(b, 'sid', None)):   # 局部导入：首次后走缓存，零开销 ✓
                return size * 2
        except Exception:                       # noqa: BLE001
            pass
        if b.mark in FIGHT_X2:                  # 明确要打的（boss/红装/大拇指/战斗标记）✓
            return size * 2
        return size                             # 内容格：探索 = SpotSize ✓

    def step_cost(self, state, bi):
        """点这一下要花的体力 ✓

        ⭐ 2026-09-27 用户口径：**空地固定 1 点**，连锁吃掉多少格都一样 ✓
           （旧版对空地整片求 ΣSpotSize ✗ ⇒ 4 格游乐设施算 4~8 点 ✗ 与游戏不符 ✗）
        """
        if self.blocks[bi].plain:
            return 1
        return self.block_cost(self.blocks[bi])

    def done(self, state):
        return not (self.targets - set(state))


def _build_cache(prob):
    """⭐ 2026-09-29 深夜优化：把 Problem 编译成**位掩码 + 预计算表**（缓存在 prob 上）

    三个性能杠杆（语义与旧版逐点等价，最优体力值不变）：
      1. 状态 frozenset → **int 位掩码**（块 ≤35 个）：哈希/比较/并集 O(n)→O(1)
      2. **A\* 启发** h(state) = Σ 未消耗目标的体力。可采纳且一致：
         目标全是非空地块（空地连锁不吃内容块）⇒ 每个未消耗目标必须被单独点掉、
         各花 block_cost(t) ⇒ 真优解花费 ≥ g + h；且点目标这条边 w=cost(t)=h 下降量。
      3. **空地等价组去重**：同一整片空地的成员块 step 结果相同 ⇒ 只展开代表块
         （片内最小 idx），分支数不再随片大小膨胀。
    """
    blocks = prob.blocks
    idxs = sorted(blocks)
    bit = {bi: 1 << k for k, bi in enumerate(idxs)}
    # 每块的格子位掩码（cell 位）
    cell_bit = {i: 1 << i for i in range(NCELL)}
    block_cells_mask = {bi: 0 for bi in idxs}
    for c, bi in enumerate(prob.board):
        if bi >= 0:
            block_cells_mask[bi] |= cell_bit[c]
    # 块级邻接：NB_MASK[bi] = 与 bi 任一格 4 邻接的其他块位掩码（含雾块 ✓）
    NB_MASK = {bi: 0 for bi in idxs}
    for bi in idxs:
        for c in prob.cells_of.get(bi, ()):
            r, cc = c // COLS, c % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if 0 <= rr < ROWS and 0 <= ccc < COLS:
                    nb = prob.board[rr * COLS + ccc]
                    if nb >= 0 and nb != bi:
                        NB_MASK[bi] |= bit[nb]
    # 整片空地组（按块并集，含穿雾穿草地口径 —— 直接复用旧逻辑预计算一次 ✓）
    PLAIN_GROUP_MASK = {}
    for bi in idxs:
        grp = prob.plain_group(bi)
        m = 0
        for x in grp:
            m |= bit[x]
        PLAIN_GROUP_MASK[bi] = m
    # 等价代表：同片空地取最小 idx；非空地 = 自己
    REP = {}
    for bi in idxs:
        if prob.blocks[bi].plain:
            REP[bi] = min(x for x in (prob.plain_group(bi)))
        else:
            REP[bi] = bi
    cost = {bi: prob.step_cost(frozenset(), bi) for bi in idxs}
    camp = prob.camp
    camp_mask = bit[camp] if camp is not None else 0
    # ⭐⭐⭐ 2026-10-02 **营地的"开局已揭示"只能来自营地那一格的 4 邻**（不是整块的 4 邻）
    #   离线铁证（r_233023_0.png，用户报「规划错了」那把）：
    #     营地格 (2,1) 被 4 格块 `巨大沙堡` (1,1)(2,1)(2,2)(2,3) 吞掉 ⇒
    #     用**整块**算邻接 ⇒ boss(1,2)、紫金格(2,4) 都进了 `camp_nb` ⇒ 开局就被当成
    #     "已揭示/可点" ⇒ 计划 = `[(1,2),(2,4)]`（真机两格 ratio 0.665/0.717 **都是雾**）
    #     ⇒ `fogged_noop` 空转、整条计划错位 ✗✗
    #   ⇒ 用 `prob.camp_cells`（真正带 camp 标记的格）算邻接；
    #     没有该信息（单格营地的常规情形）才退回整块口径 ⇒ 对老盘行为不变 ✓
    camp_nb = 0
    _ccells = set(getattr(prob, 'camp_cells', None) or ())
    if camp is not None and _ccells:
        for _c0 in _ccells:
            _r0, _q0 = _c0 // COLS, _c0 % COLS
            for _dr, _dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                _rr, _qq = _r0 + _dr, _q0 + _dc
                if 0 <= _rr < ROWS and 0 <= _qq < COLS:
                    _nb = prob.board[_rr * COLS + _qq]
                    if _nb >= 0 and _nb != camp:
                        camp_nb |= bit[_nb]
    elif camp is not None:
        camp_nb = NB_MASK[camp] & ~camp_mask
    # ⭐⭐ 2026-09-30：「观测里本来就是空的格」（已消耗）⇒ 它的邻居块**现在就已经揭示**。
    #   全知盘（新生成的盘）没有任何 -1 ⇒ EMPTY_ADJ = 0，行为一字不变 ✓
    #   观测盘（真机 / 在线推演）则有 -1 ⇒ 模型终于知道"已经走到哪了" ✓
    EMPTY_ADJ = 0
    _obs_cells = set(getattr(prob, 'obs_cells', None) or ())
    for c, bi in enumerate(prob.board):
        if bi >= 0:
            continue
        # ⭐⭐⭐ 2026-10-02 闸门：**观测里根本没有这一格 ⇒ 不许拿它当"已消耗"去揭示邻居**
        #   （真机 23:30 那把：4 格被 `_infer_chain_consumed` 推断成已消耗并**删出观测**
        #     ⇒ 这里 board<0 ⇒ `EMPTY_ADJ` 把它们的邻居判成"开局已揭示" ⇒ 计划点雾格 ✗）
        #   ⚠ 只有拿到观测格集合时才启用（老调用/全知盘没有 ⇒ 行为一字不变 ✓）
        if _obs_cells and c not in _obs_cells:
            continue
        r, cc = c // COLS, c % COLS
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, ccc = r + dr, cc + dc
            if 0 <= rr < ROWS and 0 <= ccc < COLS:
                nb = prob.board[rr * COLS + ccc]
                if nb >= 0:
                    EMPTY_ADJ |= bit[nb]
    EMPTY_ADJ &= ~camp_mask
    # ⭐⭐⭐⭐ 2026-10-05 **观测里就亮的块 = 开局就能点**
    #   （与 `Problem.visible()` ③ 同一条口径；两处**必须一致**，否则 A* 与
    #     慢速版会给出不同计划 ✗）
    #   真机铁证（acc2 13:53 第 6 张，`runs/acc2/r_135303_0.png`）：
    #     营地 (1,7)，boss 目标 `(1,1)` 观测 ratio=**1.019（明明亮着）**，
    #     但它既不挨营地、也不挨任何已消耗格 ⇒ 旧 `visible()` 不含它 ⇒
    #     求解器规划出 **6 步 / 11 体力**的绕路 `['1,6','1,5','1,4','1,3','1,2','1,1']`
    #     （横穿 4 个雾格）⇒ 用户原话「这俩图规划也不对」✗✗
    #   ⚠ 用 `Block.observed`（建块时的观测值，永不被推演改写）✓
    OBS_LIT = 0
    for bi in idxs:
        if getattr(prob.blocks[bi], 'observed', False):
            OBS_LIT |= bit[bi]
    OBS_LIT &= ~camp_mask
    targets_mask = 0
    for t in prob.targets:
        targets_mask |= bit[t]
    tcost = {bit[t]: cost[t] for t in prob.targets}     # ⭐ 键 = 单 bit（与 h() 一致）
    # ⭐⭐⭐ 2026-10-03 用户口径：「**最新一张图的规划里把拉黑的方块规划进去了，
    #   能不能一开始就不规划这个拉黑的？**」✓
    #   ⇒ 拉黑块（`Block.blocked` ✓）**既不是候选动作、也不借它走路** ✓
    #     （清单里没勾选的宝箱怪/勇者之墓/… ✓；勾选过的商人/宝库不是 blocked ✓）
    blocked_mask = 0
    for bi in idxs:
        if getattr(prob.blocks[bi], 'blocked', False):
            blocked_mask |= bit[bi]
    return {'bit': bit, 'bits': [bit[bi] for bi in idxs],
            'blocked_mask': blocked_mask,
            'NB_MASK': {bit[k]: v for k, v in NB_MASK.items()},   # ⭐ 键 = 单 bit
            'PLAIN_GROUP_MASK': PLAIN_GROUP_MASK, 'REP': REP,
            'cost': cost, 'camp_mask': camp_mask, 'camp_nb': camp_nb,
            'empty_adj': EMPTY_ADJ, 'obs_lit': OBS_LIT,
            'targets_mask': targets_mask, 'tcost': tcost,
            'idx_of_bit': {v: k for k, v in bit.items()}, 'bit_keyed': True}


def solve(prob, max_states=400000, report=None, max_secs=None):
    """A\*（按体力边权 + Σ剩余目标体力启发）求**最省体力**地清完所有目标

    -> (最小体力, [(block_idx, 体力)…])；无解返回 (None, None)
    语义与旧 Dijkstra 完全一致（最优体力值唯一），只是**快一个数量级以上**：
      2026-09-29 深夜优化：frozenset→int 位掩码 / A\* 启发 / 空地等价组去重（见 _build_cache）
    report / max_states / max_secs 语义不变（fail-open 口径不变 ✓）
    """
    import time as _time
    if report is None:
        report = {}
    report.update({'pushed': 0, 'expanded': 0, 'max_states': max_states,
                   'reason': 'exhausted', 'cost': None, 'n_targets': len(prob.targets)})
    _t0 = _time.time() if max_secs else None
    ch = getattr(prob, '_cache', None)
    if ch is None:
        ch = _build_cache(prob)
        prob._cache = ch
    bit, NB, PGM, REP, cost = ch['bit'], ch['NB_MASK'], ch['PLAIN_GROUP_MASK'], ch['REP'], ch['cost']
    # NB_MASK 的键统一成「单 bit」：把块键表换成 bit 键
    if 'bit_keyed' not in ch:
        ch['NB_MASK'] = {ch['bit'][k]: v for k, v in NB.items()}
        ch['bit_keyed'] = True
    NB = ch['NB_MASK']
    idx_of_bit = ch['idx_of_bit']
    targets_mask = ch['targets_mask']
    tcost = ch['tcost']
    camp_mask = ch['camp_mask']
    camp_nb = ch['camp_nb']
    empty_adj = ch.get('empty_adj', 0)

    def visible(m):
        # ⭐ 起手可见 = 营地四邻 ∪ **观测里已经空掉的格的邻块**（= 已经走出去的地图 ✓）
        #            ∪ **观测里就亮的块**（2026-10-05，见 `OBS_LIT` 注释 ✓）
        out = camp_nb | empty_adj | ch.get('obs_lit', 0)
        mm = m
        while mm:
            low = mm & -mm
            out |= NB.get(low, 0)
            mm ^= low
        out &= ~m & ~camp_mask
        # ⭐⭐⭐ 2026-10-03：**拉黑块一律不是候选**（用户口径"一开始就不规划它" ✓）
        out &= ~ch.get('blocked_mask', 0)
        ded = 0
        while out:
            low = out & -out
            bi = idx_of_bit[low]
            ded |= bit[REP[bi]]
            out ^= low
        return ded

    def h(m):
        s = 0
        t = targets_mask & ~m
        while t:
            low = t & -t
            s += tcost[low] if low in tcost else tcost[idx_of_bit[low]]
            t ^= low
        return s

    start = 0
    if not (targets_mask & ~start):
        report.update({'reason': 'ok', 'cost': 0})
        return 0, []
    h0 = h(start)
    dist = {start: 0}
    prev = {start: None}                 # mask -> (prev_mask, block_idx, cost)
    # ⭐⭐⭐⭐ 2026-10-05 **同等体力下取"最少步数"**（用户原话：「**不是最优步数**」／
    #   「**有两下无意义点击**」）
    #   原来 A* 只最小化**体力**，`pq` 里同 `f` 的节点**按插入顺序**出队 ⇒ 体力一样时
    #   可能给出**步数更多**的计划。真机代价很实在：每多一步 = 一次点击（1.4~2.6 秒）
    #   ＋ 一次"画面变没变"的判定，白点还容易被 `give_up_step` 摘掉、看着像卡住 ✗
    #   ⇒ 优先级键从 `(f, cnt)` 改成 **`(f, steps, cnt)`**：体力是**主目标**（不变 ✓），
    #     步数是**次序目标**（只在体力相同时才起作用）✓
    #   ⚠ 正确性：`f` 仍是主键 ⇒ 第一个弹出的目标仍是**最小体力**的；同体力时步数少的先出 ✓
    #     松弛时"同代价但步数更少"也要更新 `prev`（否则计划链还停在旧的那条 ✗）
    steps_of = {start: 0}
    pq = [(h0, 0, 0, start)]             # (f=g+h, 步数, 计数器, mask)
    cnt = 1
    n = 0
    best_goal = None
    while pq:
        f, _sn, _c, st = heapq.heappop(pq)
        g = dist.get(st)
        if g is not None and f - h(st) > g:      # 过期条目（A* 惰性删除）
            continue
        if steps_of.get(st) != _sn:              # 过期条目（步数键变了 ⇒ 旧的那条 ✗）
            continue
        report['expanded'] += 1
        if not (targets_mask & ~st):
            best_goal = st
            report['reason'] = 'ok'
            break
        vm = visible(st)
        while vm:
            low = vm & -vm
            vm ^= low
            bi = idx_of_bit[low]
            ns = st | PGM[bi]
            if ns == st:
                continue
            w = cost[bi]
            nd = g + w
            nst = steps_of[st] + 1
            old = dist.get(ns)
            # ⭐ 同体力时：**步数更少**也算改善（本轮的"最优步数"就是这条 ✓）
            if old is None or nd < old or (nd == old and nst < steps_of.get(ns, 1 << 30)):
                dist[ns] = nd
                steps_of[ns] = nst
                prev[ns] = (st, bi, w)
                heapq.heappush(pq, (nd + h(ns), nst, cnt, ns))
                cnt += 1
                n += 1
                report['pushed'] = n
                if n > max_states:
                    report['reason'] = 'max_states'
                    return None, None
        if max_secs and (report['expanded'] & 2047) == 0 \
                and _time.time() - _t0 > max_secs:
            report['reason'] = 'max_secs'
            return None, None
    if best_goal is None:
        report['reason'] = 'exhausted'
        return None, None
    report['cost'] = dist[best_goal]
    acts, cur = [], best_goal
    while prev[cur] is not None:
        p, act, w = prev[cur]
        acts.append((act, w))
        cur = p
    acts.reverse()
    return dist[best_goal], acts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', type=int, default=0)
    ap.add_argument('--map', default='夏日海滩')
    ap.add_argument('--difficulty', type=int, default=100)
    ap.add_argument('--seed', type=int, default=5000)
    ap.add_argument('--show', type=int, default=0, help='打印前 N 张盘的对比细节')
    a = ap.parse_args()
    import mapgen
    import mapsim
    import statistics

    T = mapgen.load_tables()
    g = mapgen.MapGen(T, a.map, a.difficulty)
    n = max(a.bench, a.show, 1)
    rows = []
    for k in range(n):
        sim = g.gen(seed=a.seed + k)
        prob = Problem(sim)
        opt, acts = solve(prob)
        # 基线策略（同一张盘）
        sim2 = g.gen(seed=a.seed + k)
        st = mapsim.BaselinePolicy().run(sim2)
        rows.append({'targets': len(prob.targets), 'opt': opt,
                     'base': st['clicks'], 'base_st': st['stamina'],
                     'base_left': st['left_targets'], 'acts': acts})
        if k < a.show:
            print('--- seed %d 目标=%d ｜ 最优体力=%s ｜ 基线体力=%d（点击 %d，剩目标 %d）'
                  % (a.seed + k, len(prob.targets), opt, st['stamina'], st['clicks'],
                     st['left_targets']))
            print(sim.render())
            if acts:
                names = ['%s(%d体)' % (prob.blocks[bi].name, w) for bi, w in acts]
                print('   体力最优点序:', ' → '.join(names))
    if a.bench:
        opts = [r['opt'] for r in rows if r['opt'] is not None]
        base = [r['base_st'] for r in rows]
        bclk = [r['base'] for r in rows]
        print()
        print('对比 %d 张盘（%s 难度 %d）：**目标函数 = 体力**' % (len(rows), a.map, a.difficulty))
        if opts:
            print('  体力最优：平均 %.2f 点（中位 %d，最多 %d）；算不出的 %d'
                  % (statistics.mean(opts), statistics.median(opts), max(opts),
                     sum(1 for r in rows if r['opt'] is None)))
        print('  基线策略：平均 %.2f 点体力（中位 %d，最多 %d）；点击 %.2f 次；漏目标 %d/%d'
              % (statistics.mean(base), statistics.median(base), max(base),
                 statistics.mean(bclk),
                 sum(1 for r in rows if r['base_left'] > 0), len(rows)))
        if opts:
            gap = [b - o for b, o in zip(base, opts) if o is not None]
            print('  基线比最优多花体力：平均 %.2f 点（最多 %d）；完全一样的 %d/%d'
                  % (statistics.mean(gap), max(gap), sum(1 for x in gap if x == 0), len(gap)))


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
