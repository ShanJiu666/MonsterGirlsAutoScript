# -*- coding: utf-8 -*-
"""mapgen.py · **地图生成器**（按游戏数据表 + 客户端源码规则，生成探索开局盘）

只做地图/事件，不碰战斗数值（那是 headless_battle）。

规则来源：
  · 布局参数：`Difficulty_Spec.MidBlockNum / BigBlockNum / HugeBlockNum`（中/大/巨型块数量）
              + `Area_Spot.SpotSize / SpotShape / MaxNum / Weight / AreaName`
  · 地块抽取：`ExploreSceneManager.GetAnAreaspot`（47413）= `WeightedRandom(areaSpotWeightList)`
  · 事件抽取：`GenerateBlockBattleEvent`(47801)
        minStep = max(该图 BossMinStep, 地块 MinBattleStep) → 按 Type/Step 从 Battle_Event 抽
  · **红装**：`GenerateRedEquip`(47001) —— 只有 step>=3 的事件才可能出；
        A档(3) 1/10000、S档(4) 1/1000；中了随机一件 SS 装备塞给某个敌人
  · 事件每格数量：`GeneralHelper.RangeRandom(block.data.EventNum)`（46146）

⚠ 诚实说明：**布局的"服务端算法"看不到**（棋盘由服务端下发，见 50945 `startExploreReply.ExploreMap`），
   本文件是按「表里的参数」+「真盘统计」重建的**近似生成器**。

⭐⭐⭐ 2026-09-28：**摆放层已定案**（n=94 真盘反推 + 2-fold 交叉验证选模）
   · **摆放顺序 = blockList 下标顺序**：94/94 张「营地恒为最后一个块」、
     档序 huge(≥6) → big(4~5) → mid(2~3) → 1格填缝 → 营地 **零例外**；
     各档计数精确对上 Difficulty_Spec（big 112 ≈ 1.2×94、mid 300 ≈ 3.2×94）
   · **位置 = 随机起点 + 行优先回绕线性探测 first-fit**（见 `_place_linear`）：
     CV held-out logL −1016.78，比均匀模型 **+170.78**，且是 **0 参数模型**；
     对比：可分解权重 +36.0、clamp-回0 +49.5、35 自由权重 **−148.7（过拟合）**
   · ⭐ 真盘的「偏左上」**不是位置偏好**，而是**线性探测回绕时的边界堆积效应**：
     模型预测第一个块落 (0,0) = **25.7%**，真盘实测 **27.7%**；均匀模型只给 4.2%
   · 起点是在**全部 35 格**上取（不是空格列表：Fempty 变体 logL 差 20）
   · 1 格填缝块的顺序与格子位置无关（Spearman ρ = −0.012）⇒ 填缝用随机顺序
   用途：离线大量产盘，跑策略搜索与回归（**不需要真机**）。

用法：
    python mapgen.py --maps 5 --map 夏日海滩 --difficulty 100     # 生成并打印 5 张
    python mapgen.py --bench 100 --map 夏日海滩 --difficulty 100  # 生成 100 张 + 跑基线策略统计
"""
import argparse
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROWS, COLS = 5, 7
NCELL = ROWS * COLS
import repo_paths as RP                                          # noqa: E402
# mapgen 只读 Area_Spot / Battle_Event / Difficulty_Spec 三张表，
# 主数据表里这三张与历史基准版逐字节一致 ⇒ 直接用主表（省一份 4MB 重复副本）。
DATATABLE = RP.require(RP.DATATABLE, '游戏数据表')
STEP_INT = {'C': 1, 'B': 2, 'A': 3, 'S': 4, '': 0}


def _rows(tbl):
    return list(tbl.values()) if isinstance(tbl, dict) else list(tbl)


def _range_random(spec):
    """GeneralHelper.RangeRandom("a-b" / "n" / "") —— 事件数那种字段"""
    s = str(spec or '').strip()
    if not s:
        return 0
    if '-' in s:
        a, b = s.split('-', 1)
        try:
            return random.randint(int(a), int(b))
        except Exception:       # noqa: BLE001
            return 0
    try:
        return int(s)
    except Exception:           # noqa: BLE001
        return 0


def load_tables(path=DATATABLE):
    # ⚠ v1.20：用 with 显式关闭。原来 `json.load(open(path))` 靠 GC 回收 ⇒ 端上每次
    #   回收都打一条 `ResourceWarning: unclosed file server_datatable.json`（日志噪音，
    #   还会淹没真正的异常堆栈）。
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    return {'spot': _rows(d['Area_Spot']),
            'event': _rows(d['Battle_Event']),
            'diff': _rows(d['Difficulty_Spec'])}


def _map_key(name):
    """表里的 AreaName 值（如 '夏日海滩' / '不限'）"""
    return (name or '').strip()


class MapGen:
    def __init__(self, tables, map_name='夏日海滩', difficulty=100):
        self.T = tables
        self.map_name = _map_key(map_name)
        self.difficulty = difficulty
        self.spec = self._pick_spec(difficulty)
        # ⚠ 别按 Weight>0 筛池：**boss 大块 / 营地 / 宝库这些特殊格 Weight=0**（服务端按规则摆，
        #   不参与权重抽取）⇒ 分成两个池：可以按权重填的 + 必须按 MaxNum 摆的特殊格
        allp = [s for s in self.T['spot'] if s.get('AreaName') in (self.map_name, '不限')]
        self.allp = allp
        self.specials = [s for s in allp
                         if int(s.get('SpecialSpot') or 0) > 0 or int(s.get('Weight') or 0) == 0]
        self.pool = [s for s in allp if int(s.get('Weight') or 0) > 0]
        # ⭐ 2026-09-27（analyze_spot_sampling.py 实测标定，n=137 张真盘）：
        #   · 1 格层 = **整个 SpotSize==1 池（特殊格也在里面）按 Weight 抽 + 每图 MaxNum 截断**
        #     实测 不截断模型 χ²=48.5/df10 p=8.1e-7（拒绝）vs 截断模型 χ²=6.2/df10 p=0.80（成立）
        #   · 多格层按尺寸分三档（与 Difficulty_Spec 的 mid/big/huge 一一对应，均值精确）：
        #       mid  = SpotSize 2~3   → MidBlockNum  (难度100: 3.2)  实测 3.233 ✓
        #       big  = SpotSize **4~5** → BigBlockNum (难度100: 1.2)  实测 1.197 ✓
        #       huge = SpotSize **≥6**  → HugeBlockNum(难度100: 0.1)  实测 0.073
        #   ⚠⚠ 2026-09-27 修正：big/huge 的边界是 **4~5 / ≥6**，不是 4 / ≥5！
        #     原按 4 / ≥5 分档时，5 格块（S00003_221）会落到 huge 档，而实测它占
        #     "huge 档" 56.5%（W 份额仅 12%）⇒ 曾被误判成"huge 档档内不按 Weight"。
        #     真因是分档边界错。铁证（_test_size_grouping.py；**n=137 → 2026-09-28 复核 n=664，
        #     三条判据全部加强**）：
        #       ① 每图 (n4,n5) 联合分布里 **n4=0 时 n5 必为 1（11/11 张）**；若两尺寸分属
        #          不同档则应互相独立 ⇒ 11 张全中的概率 ≈1e-11 ⇒ 同档无疑
        #       ② big=4~5 的每图总数分布 = 1:110 / 2:27，与 floor(1.2)+Bernoulli(0.2)
        #          预测的 1:109.6 / 2:27.4 完全吻合；而 big=4 会出现 11 张 0，与表不符
        #       ③ 修正后档内按 Weight 完全成立：big χ²=2.68/df4 p=0.61、huge χ²=4.81/df4 p=0.31
        #       ④ ⭐ n=664 复核：big 总数分布 **1:527 / 2:137** ⇒ 137/664 = **0.206** ≈ Bernoulli(0.2)，
        #          均值 1.206 ≈ BigBlockNum 1.2；huge=≥6 均值 **0.107** ≈ 0.1
        #          （若用 ≥5 边界则均值 0.184、不对应任何常数 ⇒ **反证边界就是 ≥6**）；
        #          同类相关：4格vs5格 r=**−0.529**（同档应负）、2格vs3格 r=**−0.857**（对照，极稳定）✓
        #
        #     ⚠⚠ 位置层（anchor 放哪）**仍未破，别信"同分布/已可用"**：
        #       `_check_layout_fidelity.py` 曾有**统计口径 bug**（"全部多格块"一段漏了 `sz>=2`
        #       过滤，把 13722 个 1 格填缝块也并进来 ⇒ 16718 = 旧输出的 n，把多格块真实偏置
        #       稀释成"看起来和生成器一致"）已修。修正后多格块：左列 32.0% vs 生成 19.4%、
        #       顶行 31.6% vs 25.0%、**(1,1) 12.3% vs 5.6%（2.2×）**、χ²=96.4/df=29（p≈1e-8）；
        #       偏置随尺寸单调增强（(1,1)：2格 5.7% → 4格 22.9% → 6格 30.6%）。
        #       本生成器现在用**均匀随机试位**（gen() 里的 rnd.randrange）⇒ **已知与真盘有差距**，
        #       要定案只能靠「候选算法对拍」（见 地图生成算法.md §14.7）。
        #     ⚠ 「每图总数」和「档内 sid 选择」都在**服务端**，客户端只负责渲染
        #      服务端下发的 blockList（`SandTable.FreshSandTable`），
        #      所以只能靠这类反推，服务端取样代码不在客户端里。
        self.one_pool = [s for s in allp
                         if int(s.get('SpotSize') or 1) == 1 and int(s.get('Weight') or 0) > 0]
        self.mid_pool = [s for s in self.pool if int(s.get('SpotSize') or 1) in (2, 3)]
        self.big_pool = [s for s in self.pool if int(s.get('SpotSize') or 1) in (4, 5)]
        self.huge_pool = [s for s in self.pool if int(s.get('SpotSize') or 1) >= 6]
        # 填充格：SpecialSpot==0 且 MaxNum 最大的那个（夏日海滩=草地，MaxNum=35 ⇒ 永不触顶）
        # ⚠ 它吸收所有被 MaxNum 夹掉的余量 —— 这就是实测里"草地比 Weight 比例多 1.4%"的成因
        plains = [s for s in self.one_pool if int(s.get('SpecialSpot') or 0) == 0]
        self.filler = max(plains, key=lambda s: int(s.get('MaxNum') or 1)) if plains else None
        self.events = self.T['event']

    # ---------- 表查询 ----------
    def _pick_spec(self, diff):
        rows = sorted(self.T['diff'], key=lambda r: int(r.get('Difficulty') or 0))
        best = rows[0]
        for r in rows:
            if int(r.get('Difficulty') or 0) <= diff:
                best = r
        return best

    def _size_mix(self):
        """中/大/巨型块数量（小数按概率取整；跟服务端同参数）"""
        def pick(v):
            f = float(v or 0)
            n = int(f)
            return n + (1 if random.random() < (f - n) else 0)
        return {'mid': pick(self.spec.get('MidBlockNum')),
                'big': pick(self.spec.get('BigBlockNum')),
                'huge': pick(self.spec.get('HugeBlockNum'))}

    def _shape_cells(self, spot):
        """地块 footprint —— ⭐ 2026-09-27 改为**直接解析 SpotShape**（表驱动，不再猜近似）

        实测标定（115 张真盘、516 个多格块）：**516/516 与 SpotShape 原样一致，0 个需要旋转**
        ⇒ `SpotShape` 就是摆放形状本身，且本作**不做旋转** ✓
            "1"               → 1 格
            "1,1"             → 竖排 2 格        "11"        → 横排 2 格
            "111"             → 横排 3 格        "10,11"     → 2×3 的 3 格 L
            "100,111"         → 2×3 的 4 格 L    "11,11"     → 2×2
            "110,111"         → 5 格             "1111111,..." ×5 → 满盘 35 格
        旧实现是「size<=1→1格；4→2x2；否则 1×size 直线」的近似 ⇒ **8/9 格永远摆不下**
        （保真度自检里 5 格实测 8 张、生成 0 张就是这个原因）。
        """
        sh = (spot.get('SpotShape') or '').strip()
        if sh:
            rows = [r for r in sh.split(',') if r]
            if rows and any('1' in r for r in rows):
                return [(i, j) for i, r in enumerate(rows)
                        for j, ch in enumerate(r) if ch == '1']
        size = int(spot.get('SpotSize') or 1)
        if size <= 1:
            return [(0, 0)]
        return [(0, i) for i in range(size)]

    def _can_place(self, board, r, c, cells):
        for dr, dc in cells:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ROWS and 0 <= cc < COLS):
                return False
            if board[rr * COLS + cc] >= 0:
                return False
        return True

    def _place_linear(self, board, cells, rnd):
        """⭐ 2026-09-28 定案：**随机起点 + 行优先回绕线性探测 first-fit**

        证据（n=94 真盘，423 个多格块摆放样本，2-fold 交叉验证）：
            logL    −1016.78（均匀模型 −1187.56，Δ=+170.78）
            0 参数  ⇒ 不会过拟合（35 自由权重模型 held-out Δ=−148.7，确认过拟合）
        变体对照（全量 logL）：
            起点在空格列表上取      −1036.97 ✗（起点是在**全部 35 格**上取）
            不回绕                  −1081.06 ✗
            列优先 / 逆序           −1225 ~ −1364 ✗（方向必须是行优先正向）
            最多探测 1 步           −1187.56（退化为均匀，符合预期 ✓）
        ⚠ 真盘的「偏左上」由本规则的**回绕边界堆积**自然产生，不要再去加"位置权重"。
        """
        s = rnd.randrange(NCELL)
        for k in range(NCELL):
            p = (s + k) % NCELL
            r, c = divmod(p, COLS)
            if self._can_place(board, r, c, cells):
                return r, c
        return None

    # ---------- 生成 ----------
    def gen(self, seed=None):
        """-> MapSim（真实地块结构 + 事件标记，可直接跑策略）"""
        rnd = random.Random(seed)
        random.seed(seed)
        import mapsim

        board = [-1] * NCELL
        placed = []          # (spot, cells)
        used_num = {}

        def stamp(spot, cells):
            """cells = [(r, c), ...] 绝对坐标；返回 placed 下标"""
            idx = len(placed)
            placed.append({'spot': spot, 'cells': list(cells)})
            for (r, c) in cells:
                board[r * COLS + c] = idx
            return idx

        # ① 营地 —— ⚠ 2026-09-28 定案：**营地是最后一个摆的块**
        #    真盘 94/94 张「营地 idx == 总块数-1」，差值分布 {0: 94} ⇒ 它不参与开场摆放，
        #    而是在 1 格填缝阶段**从剩余空格里随机拿一个**（见 ④）。
        #    （旧实现把营地放在第一步随机位，会让营地出现在多格块本可占用的格上 ✗）
        camp = next((s for s in self.specials + self.pool if s.get('Name') == '营地'), None)

        # ② Weight==0 的特殊多格块（boss 大块等，营地不在此列）：按尺寸降序，线性探测摆放
        #    ⚠ 2026-09-27 修：原先这里把**所有 SpecialSpot>0 的格**都按 50% 硬币摆，
        #      与实测不符 —— 实测特殊格（海螺/宝箱/岩石/勇者之墓/黄金宝库…）**也是从权重池里抽**，
        #      只是每图有 MaxNum 截断（见 analyze_spot_sampling.py）。旧写法会让
        #      黄金宝库 0.5 张/图（实测 0.041，虚高 12 倍）、岩石 0.5（实测 0.321）。
        # ⚠ 2026-09-28 补：必须剔除 **SpotSize>=10 的整图型占位块**（夏日海滩的
        #    「异界之门」SpotSize=35 / W=0 / MaxNum=1）。真盘多格块尺寸只在 **2~9**，
        #    它属于别的玩法入口，探索图不生成。旧代码没剔是因为营地先在 ① 占掉 1 格，
        #    35 格块"恰好摆不下"才没出事；营地改到最后摆之后就会**占满全盘** ✗
        specials = [s for s in self.specials
                    if int(s.get('Weight') or 0) == 0
                    and s.get('Name') != '营地'
                    and 2 <= int(s.get('SpotSize') or 1) <= 9]
        # boss 大块优先（SpotSize 大的先摆，否则会被小块占满摆不下）
        for s in sorted(specials, key=lambda x: (-int(x.get('SpotSize') or 1),
                                                 -int(x.get('Weight') or 0))):
            cap = int(s.get('MaxNum') or 1)
            for _ in range(cap):
                cells = self._shape_cells(s)
                rc = self._place_linear(board, cells, rnd)
                if rc is None:
                    continue
                r, c = rc
                stamp(s, [(r + dr, c + dc) for dr, dc in cells])

        # ③ 多格块 huge(≥6) → big(4~5) → mid(2~3)：
        #    ⭐ 档序由真盘 blockList 下标**零例外**验证（huge 晚于 big/mid：0/94；big 晚于 mid：0/94）
        #    档内按 Weight 抽、每图 MaxNum 截断；位置一律走 `_place_linear`
        mix = self._size_mix()
        for pool_k, n in ((self.huge_pool, mix['huge']),
                          (self.big_pool, mix['big']),
                          (self.mid_pool, mix['mid'])):
            if not pool_k:
                continue
            wl = [max(1, int(s.get('Weight') or 0)) for s in pool_k]
            cnt2 = {}
            for _ in range(n):
                s = None
                for _try2 in range(60):
                    cand = rnd.choices(pool_k, weights=wl, k=1)[0]
                    key = cand.get('IDs')
                    if cnt2.get(key, 0) < int(cand.get('MaxNum') or 1):
                        s = cand
                        cnt2[key] = cnt2.get(key, 0) + 1
                        break
                if s is None:
                    s = pool_k[0]
                cells = self._shape_cells(s)
                rc = self._place_linear(board, cells, rnd)
                if rc is None:
                    continue
                r, c = rc
                stamp(s, [(r + dr, c + dc) for dr, dc in cells])

        # ④ 1 格填缝（**随机顺序**，真盘填缝 idx 与格子位置无关 Spearman ρ=−0.012）
        #    + 营地收尾：从剩余空格里随机拿一个 ⇒ 营地 idx 恒为最后 ✓
        one = self.one_pool
        weights = [max(1, int(s.get('Weight') or 0)) for s in one] or [1]
        cnt1 = {}
        empties = [i for i in range(NCELL) if board[i] < 0]
        rnd.shuffle(empties)
        camp_cell = empties.pop() if empties else None
        for i in empties:
            s = None
            for _try2 in range(200):
                cand = rnd.choices(one, weights=weights, k=1)[0] if one else None
                if cand is None:
                    break
                key = cand.get('IDs')
                if cnt1.get(key, 0) < int(cand.get('MaxNum') or 1):
                    s = cand
                    cnt1[key] = cnt1.get(key, 0) + 1
                    break
            if s is None:
                s = self.filler or {'IDs': 'X', 'Name': '草地', 'SpecialSpot': 0,
                                    'SpotSize': 1, 'MaxNum': 99}
            stamp(s, [divmod(i, COLS)])
        if camp is not None and camp_cell is not None:
            stamp(camp, [divmod(camp_cell, COLS)])

        # ⑤ 事件与标记（按客户端规则）
        # ⑤ 事件与标记（按客户端规则）
        #    ⭐ 每张图**必有一个 boss**（游戏里就是那个最大的战斗块）⇒ 先选出 boss 块
        fight_blocks = [i for i, p in enumerate(placed)
                        if int(p['spot'].get('SpotSize') or 1) >= 2
                        and p['spot'].get('Name') != '营地']
        boss_idx = None
        if fight_blocks:
            boss_idx = max(fight_blocks,
                           key=lambda i: int(placed[i]['spot'].get('SpotSize') or 1))
        blocks = []
        for i, p in enumerate(placed):
            s = p['spot']
            row = dict(s)
            row['sid'] = s.get('IDs')
            row['name'] = s.get('Name') or s.get('IDs') or '空地'    # ⚠ Block 读的是 name（小写）
            b = mapsim.Block(i, row, revealed=False)
            # ⭐ 事件按客户端规则生成（GenerateBlockEvents 46131）：
            #   事件数 = RangeRandom(spot.EventNum)；每件事的**种类**按
            #   WeightedRandom([IngredientWeight, RoleWeight, ChestWeight, ItemWeight])
            #   （0=材料 1=战斗 2=宝箱 3=道具 4=装备）—— RoleWeight 抽中就是战斗格
            evs = self._gen_events(s, is_boss=(i == boss_idx))
            # ⭐ 2026-09-28 修：**多格块的 RoleWeight 全是 0**（夏日海滩 15 个多格块无一例外，
            #   表 IngredientWeight=6200 / RoleWeight=0 / ChestWeight=3000）
            #   ⇒ `_gen_events` 永远抽不到 kind==1(战斗) ⇒ `evs` 非空但**没有战斗事件**
            #   ⇒ boss 块拿不到 mark ⇒ **生成的盘 40 张里 38 张零目标**，策略无从评估。
            #   旧代码只在 `evs` 为空时才补 ⇒ 正好补不上。
            #   真盘铁证（n=96）：每图 `isBossFight` 块数 = **{1: 95, 0: 1}** ⇒ 每图恰好 1 个 boss。
            if i == boss_idx and not any(e.get('type') == '战斗' for e in evs):
                evs.append(self._gen_event(s, is_boss=True))
            if evs:
                b.save = {'battleEvent': next((e for e in evs if e.get('type') == '战斗'), {})}
                if any(e.get('redEquip') for e in evs):
                    b.mark = 'redEquip'
                elif any(e.get('isBossFight') for e in evs):
                    b.mark = 'boss'
            blocks.append(b)

        sim = mapsim.MapSim(board, blocks)
        # 开局揭示：营地 + **与营地 4 邻接的块**（真机口径：最先只有营地挨着的格子能点）
        # ⚠⚠ 2026-09-30 修（离线保真度 bug，影响面很大）：
        #   原实现把 `placed[...]['cells']`（`stamp()` 存的是 **0 基 (r,c)**，见 224-229 行）
        #   直接当成 (r,c) 去和 `mapsim.rc_of()` 算出来的 **1 基**坐标比 ⇒ 集合整体错位 (−1,−1)
        #   ⇒ 开局揭示集不是"营地四邻"，而是"**营地左上那一格**的四邻" ✗
        #   实测铁证（seed 5000，营地 1 基 (3,3)）：revealed 竟是
        #       (1,1)(1,2)(2,1)(2,3)(3,2) = (2,2) 的四邻 ✗
        #   ⇒ 后果：所有离线评估（`mapsolve --bench` 的最优值、`strategy` 的权重扫描、
        #     `地图生成算法.md §16` 那套 11.02/11.68）都建立在**开局态与真机不一致**的盘上；
        #     且「真盘 vs 生成器」对拍时会与 `mapsim/mapsolve` 的"营地四邻"口径互相打架 ✗
        #   ⇒ 修法：统一走 `rc_of(r * COLS + c)` 把 0 基 (r,c) 换成 1 基，再比 ✓
        camp_idx = next((i for i, p in enumerate(placed)
                         if p['spot'].get('Name') == '营地'), None)
        if camp_idx is not None:
            camp_r = {mapsim.rc_of(r * COLS + c)
                      for (r, c) in placed[camp_idx]['cells']}
            for blk in sim.blocks.values():
                rc = [mapsim.rc_of(ci) for ci in (blk.cells or [])]
                if blk.idx == camp_idx or any(
                        abs(r - cr) + abs(c - cc) == 1
                        for (r, c) in rc for (cr, cc) in camp_r):
                    blk.revealed = True
        return sim

    def _gen_events(self, spot, is_boss=False):
        """GenerateBlockEvents(46131) 的等价实现：事件数 + 种类权重 → 战斗事件按需生成"""
        cnt = _range_random(spot.get('EventNum'))
        if cnt <= 0:
            return []
        wl = [int(float(spot.get(k) or 0)) for k in
              ('IngredientWeight', 'RoleWeight', 'ChestWeight', 'ItemWeight')]
        if sum(wl) <= 0:
            wl = [1, 1, 1, 1]
        out = []
        for _ in range(cnt):
            kind = random.choices([0, 1, 2, 3], weights=[max(0, w) for w in wl], k=1)[0]
            if kind == 1:                     # 战斗 → GenerateBlockBattleEvent(47801)
                out.append(self._gen_event(spot, is_boss=is_boss))
            else:
                out.append({'type': ['材料', '战斗', '宝箱', '道具'][kind]})
        return out

    def _gen_event(self, spot, is_boss=False):
        """GenerateBlockBattleEvent + GenerateRedEquip 的等价实现"""
        min_step = max(0, int(STEP_INT.get(self.spec.get('BossMinStep') or '', 0)),
                       int(STEP_INT.get(spot.get('MinBattleStep') or '', 0)))
        typ = '首领' if is_boss else '常规'
        cand = [e for e in self.events
                if e.get('AreaName') in (self.map_name, '不限')
                and int(STEP_INT.get(e.get('Step') or '', 0)) >= min_step
                and (e.get('Type') or '') == typ]
        if not cand:
            cand = [e for e in self.events if (e.get('Type') or '') == typ] or self.events
        w = [max(1, int(e.get('Weight') or 0)) for e in cand]
        e = random.choices(cand, weights=w, k=1)[0]
        step = int(STEP_INT.get(e.get('Step') or '', 0))
        # ⭐ 红装（源码 47001）：step>=3 才有；A 档 1/10000、S 档 1/1000
        red = False
        if step >= 3 and random.randrange(10000 if step == 3 else 1000) == 0:
            red = True
        return {'iDs': e.get('IDs'), 'type': '战斗', 'step': e.get('Step'),
                'isBossFight': bool(is_boss), 'redEquip': red}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', default='夏日海滩')
    ap.add_argument('--difficulty', type=int, default=100)
    ap.add_argument('--maps', type=int, default=0, help='生成并打印几张')
    ap.add_argument('--bench', type=int, default=0, help='生成 N 张并跑基线策略统计')
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    T = load_tables()
    g = MapGen(T, a.map, a.difficulty)
    print('表：地块池 %d 个（%s，权重>0）、事件池 %d 个；难度 %d 档位表=%s（中/大/巨=%s/%s/%s）'
          % (len(g.pool), a.map, len(g.events), a.difficulty, g.spec.get('Difficulty'),
             g.spec.get('MidBlockNum'), g.spec.get('BigBlockNum'), g.spec.get('HugeBlockNum')))
    if a.maps:
        for k in range(a.maps):
            sim = g.gen(seed=a.seed + k)
            print('\n--- 生成盘 #%d（seed %d）目标=%s ---' % (k + 1, a.seed + k, sim.targets()))
            print(sim.render())
    if a.bench:
        import mapsim
        import statistics
        rows = []
        for k in range(a.bench):
            sim = g.gen(seed=a.seed + k)
            t0 = sim.targets()
            st = mapsim.BaselinePolicy().run(sim)
            rows.append((len(t0), st['clicks'], st['left_targets']))
        clicks = [r[1] for r in rows]
        tgt = [r[0] for r in rows]
        left = [r[2] for r in rows]
        print('\n生成 %d 张盘 + 基线策略：' % len(rows))
        print('  平均目标数 %.1f（最多 %d）；平均点击 %.1f（中位 %.1f，最多 %d）'
              % (statistics.mean(tgt), max(tgt), statistics.mean(clicks),
                 statistics.median(clicks), max(clicks)))
        print('  未清完目标的局面 %d/%d（%.0f%%）'
              % (sum(1 for x in left if x > 0), len(rows),
                 100.0 * sum(1 for x in left if x > 0) / max(1, len(rows))))


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
