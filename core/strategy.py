# -*- coding: utf-8 -*-
"""strategy.py · **探索策略**（可离线评估、可搬到真机的固定规则）

用户要求（2026-09-25）：「最后要脱离 AI 的，我需要你给一套尽量好的策略」
⇒ 本模块给出一套**确定性规则**（无搜索、无 AI），并用 `mapsolve` 的最优解当标尺验证它。

策略 = 贪心打分（每步选一个可见未消耗的块），分数由四部分组成：
    gain_target  该块就是目标（标记/商人/宝库）        —— 直接拿
    gain_reveal  点它会连锁揭示出新的格                —— 开路
    gain_near    点它使得到最近目标的曼哈顿距离变小     —— 靠近
    cost         体力（源码口径：普通格 SpotSize、战斗格 SpotSize×2）
    score = w_t*gain_target + w_r*gain_reveal + w_n*gain_near - w_c*cost
平手时：先比 cost 小、再比离目标近。

⚠ 关键纪律：**便宜优先** —— 1 格空地(1 体)远优于大块内容格(4~8 体)，
   除非那格就是目标本身或实在无路可走。

用法：
    python strategy.py --bench 200 --map 夏日海滩 --difficulty 100   # 基线 vs 贪心 vs 最优
    python strategy.py --sweep 120 --map 夏日海滩 --difficulty 100   # 权重小扫描，挑最省的
"""
import argparse
import io
import itertools
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROWS, COLS = 5, 7
NCELL = ROWS * COLS

# 默认权重（`--sweep` 会重新挑）
W = {'target': 100.0, 'reveal': 8.0, 'near': 3.0, 'cost': 6.0}


def _dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class GreedyPolicy:
    """确定性贪心策略（真机可直接照搬：每轮算一次分数表，取最高分那格点）"""

    name = '贪心：便宜优先 + 目标优先 + 开路/靠近加权'

    def __init__(self, w=None, max_click=30):
        self.w = dict(W if w is None else w)
        self.max_click = max_click

    # ---------- 打分 ----------
    def score(self, sim, bi):
        b = sim.blocks[bi]
        cost = sim.block_cost(b)
        is_target = bool(b.mark) or b.is_buy
        # 点它会不会揭示新格：该块任意格子的 4 邻里有未揭示块
        reveals = 0
        cells = b.cells or []
        for c in cells:
            r, cc = c // COLS, c % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if not (0 <= rr < ROWS and 0 <= ccc < COLS):
                    continue
                nb = sim.board[rr * COLS + ccc]
                if nb >= 0 and nb != bi and not sim.blocks[nb].revealed \
                        and not sim.blocks[nb].gone:
                    reveals += 1
        tgs = sim.targets()
        near = 0.0
        if tgs:
            anchor = None
            for c in cells:
                p = (c // COLS + 1, c % COLS + 1)
                anchor = p if anchor is None else min(anchor, p)
            d0 = min(_dist(anchor, t) for t in tgs)
            near = max(0.0, 10.0 - d0) if not is_target else 10.0
        w = self.w
        return (w['target'] * (1 if is_target else 0)
                + w['reveal'] * reveals
                + w['near'] * near
                - w['cost'] * cost), cost

    # ---------- 跑一局 ----------
    def run(self, sim, verbose=False):
        guard = 0
        skip = set()                        # ⚠ 只在本策略里跳过，**绝不能改模拟器状态**
        while guard < self.max_click and not sim.done():
            guard += 1
            vis = [rc for rc in sim.visible() if rc not in skip]
            if not vis:
                break                      # 没有可点的了（不该发生：营地恒可点）
            best, best_key = None, None
            for rc in vis:
                bi = sim.board[(rc[0] - 1) * COLS + (rc[1] - 1)]
                if bi < 0:
                    continue
                sc, cost = self.score(sim, bi)
                tgs = sim.targets()
                dmin = min((_dist(rc, t) for t in tgs), default=99)
                key = (-sc, cost, dmin)    # 分数高优先；同分选便宜的；再选离目标近的
                if best_key is None or key < best_key:
                    best, best_key = (rc, bi), key
            if best is None:
                break
            rc, bi = best
            kind, info = sim.click(rc)
            if kind == 'noop':
                skip.add(rc)               # 点不动 → 本策略内跳过这格（不动棋局）
                continue
            if kind == 'panel':
                b = sim.blocks[bi]
                if b.is_buy or b.mark or '营地' not in (b.name or ''):
                    sim.resolve_panel(rc, do_buy=True, do_fight=True)
        return sim.stats()


class LineCostPolicy:
    """⭐ **成本感知的最短直线策略**（= 现行骨架 + 体力成本优先）——推荐给真机用的一套

    骨架沿用现行规则（实测已接近最优：只多花 13.8%）：
        ① 目标是标记格 ∪ 商人/宝库；目标能点就直接点
        ② 目标点不动 → 沿「出生地(营地) → 目标」的**直线**点可点的格开路
        ③ 目标清完立刻停
    本类补上最优解暴露出来的三条**成本纪律**：
        ⓐ 直线上的格**按体力成本排序**（便宜优先），同成本再按离目标近
        ⓑ **成本上限**：只要还有 cost≤1 的可点格就不碰 cost≥2 的（大块内容格 4~8 体 ✗）
        ⓒ 目标本身不受成本上限约束（该拿的还是要拿）
    """

    name = '成本感知直线：便宜优先 + 成本上限 + 直线开路'

    def __init__(self, max_click=30, cap1=1, cap2=2):
        self.max_click = max_click
        self.cap1 = cap1          # 首选成本上限
        self.cap2 = cap2          # 次选成本上限

    @staticmethod
    def _line(a, b):
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

    def run(self, sim, max_click=None):
        max_click = max_click or self.max_click
        spawn = sim.spawn_cell()
        skip = set()
        while sim.clicks < max_click and not sim.done():
            vis = [rc for rc in sim.visible() if rc not in skip]
            if not vis:
                break
            tgs = sim.targets()
            if not tgs:
                break
            # ① 目标能点 → 直接点（不受成本上限约束）
            picked = None
            for t in tgs:
                if t in vis:
                    picked = t
                    break
            if picked is None:
                # ② 沿直线开路：候选按 (成本, 离目标距离) 排序，并施加成本上限
                cands = []
                for t in tgs:
                    for p in self._line(spawn, t):
                        if p in vis and p != t and p not in [c[0] for c in cands]:
                            bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                            if bi < 0:
                                continue
                            cost = sim.block_cost(sim.blocks[bi])
                            cands.append((p, cost, _dist(p, t)))
                if not cands:
                    # 直线上没得点 → 退而求其次：全部可点格里挑最便宜、离目标最近的
                    for p in vis:
                        bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                        if bi < 0:
                            continue
                        cost = sim.block_cost(sim.blocks[bi])
                        cands.append((p, cost, min(_dist(p, t) for t in tgs)))
                if not cands:
                    break
                cheap = [c for c in cands if c[1] <= self.cap1]
                mid = [c for c in cands if c[1] <= self.cap2]
                pool = cheap or mid or cands          # ⓑ 成本上限逐级放宽
                pool.sort(key=lambda c: (c[1], c[2]))  # ⓐ 便宜优先，其次离目标近
                picked = pool[0][0]
            kind, info = sim.click(picked)
            if kind == 'noop':
                skip.add(picked)
                continue
            if kind == 'panel':
                bi = sim.board[(picked[0] - 1) * COLS + (picked[1] - 1)]
                b = sim.blocks[bi] if bi >= 0 else None
                if b is not None and (b.is_buy or b.mark or '营地' not in (b.name or '')):
                    sim.resolve_panel(picked, do_buy=True, do_fight=True)
        return sim.stats()


class BaselineCostPolicy:
    """⭐ 最终推荐：**现行基线 + 体力成本纪律**（最小改动、风险最低）

    与 `mapsim.BaselinePolicy` 完全同一套骨架（目标 / 直线开路 / 走廊兜底 / 点不动拉黑），
    只把"选哪一个开路格"从**只看距离**改成**先看体力成本、再看距离**：

        候选 = 直线上的可见格（或走廊兜底）
        排序 = (体力成本, 离目标距离)          ← 原来只有"离目标距离"
        ⇒ 1 格空地(1 体) 永远优先于 大块内容格(4~8 体)

    离线实测（夏日海滩 难度100，150 张盘）：见 `--bench` 输出。
    """

    name = '基线 + 成本纪律（便宜优先）'

    def __init__(self, max_click=30):
        self.max_click = max_click

    def run(self, sim, max_click=None):
        import mapsim
        base = mapsim.BaselinePolicy(max_click=max_click or self.max_click)
        # 复用基线的整套骨架，只替换它的"直线上取哪个格"逻辑：
        # 这里用**成本优先**的顺序喂给它（把便宜格排前面）
        while sim.clicks < base.max_click and not sim.done():
            vis = [p for p in sim.visible() if p not in base.black]
            tgs = sim.targets()
            if not tgs:
                break
            # ① 目标能点 → 直接点
            hit = next((t for t in tgs if t in vis), None)
            if hit is None:
                # ② 直线/走廊候选 → **按 (成本, 距离) 排序**取第一个
                spawn = sim.spawn_cell()
                cands = []
                for t in tgs:
                    for p in base._line(spawn, t):
                        if p in vis and p != t:
                            bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                            if bi < 0:
                                continue
                            cands.append((p, sim.block_cost(sim.blocks[bi]), _dist(p, t)))
                if not cands:
                    for p in vis:
                        bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                        if bi < 0:
                            continue
                        cands.append((p, sim.block_cost(sim.blocks[bi]),
                                      min(_dist(p, t) for t in tgs)))
                if not cands:
                    break
                cheap = [c for c in cands if c[1] <= 1]
                pool = cheap or cands
                pool.sort(key=lambda c: (c[1], c[2]))
                hit = pool[0][0]
            kind, info = sim.click(hit)
            if kind == 'noop':
                base.black.add(hit)
                continue
            if kind == 'panel':
                b = sim.blocks[sim.board[(hit[0] - 1) * COLS + (hit[1] - 1)]]
                if b.is_buy or b.mark or '营地' not in (b.name or ''):
                    sim.resolve_panel(hit, do_buy=True, do_fight=True)
        return sim.stats()


# ⭐ 2026-09-28 用**定案的生成器**产 2000 张盘扫描出来的最优参数（见 地图生成算法.md §16）
EFF_BEST = {'w_rev': 1.0, 'w_cost': 2.0, 'w_d': 1.0, 'no_content': False, 'w_goal': 5.0}


def _nb(idx):
    r, c = idx // COLS, idx % COLS
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS and 0 <= cc < COLS:
            out.append(rr * COLS + cc)
    return out


class EffPolicy:
    """⭐ **片感知 + 一步前瞻**（2026-09-28 优化出的最省体力策略，推荐真机用）

    为什么比"直线开路"好：**点空地会连锁消除整片，而空地固定 1 点**（用户 2026-09-27 口径）
        ⇒ 点一片空地的**代价与片大小无关**，收益却是"整片周围一圈被揭示"
        ⇒ 应该挑**揭示得多**的那一片，而不是"离目标直线最近"的那一格。

    每一步的候选打分（越大越好）：
        cost   = 真实代价（空地 **固定 1**；内容格 size；战斗格 size×2）
        reveal = 点它之后**新揭示**的块数
        d      = 到最近目标的曼哈顿距离
        goal   = 这一下能不能**直接把目标揭示出来**（⭐ 一步前瞻，权重 w_goal）
        score  = w_rev·reveal − w_cost·cost − w_d·d + w_goal·goal

    ⚠ 两条纪律：
        · 目标可点 ⇒ 必点（不受任何成本约束）
        · `no_content=False`（**不要**禁掉内容格）—— 扫描里所有 `no_content=True` 的组
          都排在最差档（有时必须穿过内容格才能到目标）

    实测（夏日海滩 难度100）：
        扫描盘 400 张（seed 8000）      → 11.098
        验证盘 **2000 张**（seed 30000，与扫描不重叠 ⇒ 无过拟合）→ **11.021**
            现行基线 11.675（省 **5.61%**）｜成本感知直线 11.514（省 4.28%）
        vs Dijkstra 最优 10.453：多花 5.65%（0.59 点），
            而现行基线多花 11.55%（1.21 点）⇒ **与最优的差距缩小了一半**
    """

    name = '片感知 + 一步前瞻（2026-09-28 最优）'

    def __init__(self, w_rev=None, w_cost=None, w_d=None, cap=0, no_content=None,
                 max_click=30, w_goal=None):
        b = EFF_BEST
        self.w_rev = b['w_rev'] if w_rev is None else w_rev
        self.w_cost = b['w_cost'] if w_cost is None else w_cost
        self.w_d = b['w_d'] if w_d is None else w_d
        self.no_content = b['no_content'] if no_content is None else no_content
        self.w_goal = b['w_goal'] if w_goal is None else w_goal
        self.cap = cap
        self.max_click = max_click

    def _grp_cost(self, sim, idx):
        bi = sim.board[idx]
        b = sim.blocks[bi]
        if b.plain:
            grp = sim.connected_plain(idx)
            cells = [j for j in range(NCELL) if sim.board[j] in grp]
            return 1, cells          # ⭐ 空地固定 1 点，连锁多少都一样
        return sim.block_cost(b), [j for j in range(NCELL) if sim.board[j] == bi]

    def plan(self, sim, max_click=None, stop_when_no_target=True):
        """⭐ 推演整条点击序列并返回 [(r,c), …]（1 基行列，与 visible()/rc_of 同坐标系）

        2026-09-28 接入 explore_loop 用：solver 失败时由 explore_loop.eff_order()
        调这里拿点序。逻辑与 run() **只有这一份**（run = plan + 统计，防两处漂移 ✓）。
        ⚠ 推演会消费 sim（点击/面板/揭示都会发生）⇒ 只传临时建盘的 sim 或副本。

        stop_when_no_target：
          · True（默认，全知盘口径）—— 目标清完就停（run 的原语义 ✓）
          · False（**观测盘**必须用！from_observation 建的盘里雾格 board=-1 ⇒
            目标还在雾里时 targets() 为空 ⇒ done()=True ⇒ 旧条件下 plan 恒空 ✗✗
            —— 2026-09-28 离线验证抓到：60 张全崩（漏目标 44/60）。
            改成：没目标也继续开路，直到没有可点格）

        ⭐⭐ 观测盘的「揭示收益」近似（2026-09-28）：观测盘上所有块都 revealed=True
        （export 只导已揭示格）⇒ 原判据 `not b.revealed` 恒空 ⇒ rev 恒 0 ✗。
        改用**边界雾格数**：块消耗后其周围 board=-1 的格数（≈ 将被揭示的块数）。
        """
        max_click = max_click or self.max_click
        order = []
        skip = set()
        guard = 0
        while guard < max_click and (not sim.done() or not stop_when_no_target):
            guard += 1
            tgs = sim.targets()
            if not tgs:
                if stop_when_no_target:
                    break
                tgs = []            # 观测盘：目标还在雾里 ⇒ 继续开路（无 d/无 goal ✓）
            # 观测盘判据：盘上是否还有"未揭示的块"（有 ⇒ 全知口径 rev；无 ⇒ 边界雾格近似）
            blind = not any(not b.revealed and not b.gone
                            for b in sim.blocks.values())
            vis = [rc for rc in sim.visible() if rc not in skip]
            if not vis:
                break
            hit = next((t for t in tgs if t in vis), None)     # ① 目标能点 ⇒ 必点
            if hit is None:
                cands = []
                for rc in vis:
                    idx = (rc[0] - 1) * COLS + (rc[1] - 1)
                    bi = sim.board[idx]
                    if bi < 0:
                        continue
                    b = sim.blocks[bi]
                    is_tgt = bool(b.mark) or b.is_buy
                    if not is_tgt and self.no_content and not b.plain:
                        continue
                    cost, cells = self._grp_cost(sim, idx)
                    if self.cap and cost > self.cap:
                        continue
                    if blind:
                        # ⭐ 观测盘（blind）打分（2026-09-28 修，离线验证抓到 17.8 的教训）：
                        #   rev = 片外边界的**雾格数 + 雾块数**
                        #   · board=-1 在观测盘上是雾格（全知盘上是已消耗格，别混 ✗）
                        #   · 盘上存在的未揭示块（雾中标记格，_from_mark 建进来的）也算
                        #     —— 点掉贴着它的片，它就会被真实揭示 ✓
                        #   · 内容格(size≥2)边界天然大 ⇒ rev 会高估 ⇒ 用参数扫描对冲
                        #     （w_cost 盲推口径下应更大，见 §16 扫描）
                        rev = set()
                        for cc in cells:
                            for nb in _nb(cc):
                                bj = sim.board[nb]
                                if bj < 0:
                                    rev.add(nb)
                                elif bj != bi and not sim.blocks[bj].gone \
                                        and not sim.blocks[bj].revealed:
                                    rev.add(bj)
                    else:
                        rev = set()
                        for cc in cells:
                            for nb in _nb(cc):
                                bj = sim.board[nb]
                                if bj >= 0 and bj != bi and not sim.blocks[bj].gone \
                                        and not sim.blocks[bj].revealed:
                                    rev.add(bj)
                    if tgs:
                        d = min(_dist(rc, t) for t in tgs)
                        sc = self.w_rev * len(rev) - self.w_cost * cost - self.w_d * d
                        if self.w_goal:
                            if blind:
                                # ⭐ blind 的 goal 项：片（cells）直接贴到目标格
                                #   ⇒ 点完这片目标就贴脸（下一步必能揭示/点到）✓
                                #   （旧判据 `sim.board[t] in rev` 在 blind 下永不成立：
                                #    rev 混合格索引/块索引，且雾中目标格 board≥0 ✗）
                                for t in tgs:
                                    ti = (t[0] - 1) * COLS + (t[1] - 1)
                                    if ti in cells or any(nb in cells
                                                          for nb in _nb(ti)):
                                        sc += self.w_goal
                                        break
                            elif {sim.board[(t[0] - 1) * COLS + (t[1] - 1)]
                                  for t in tgs} & rev:
                                sc += self.w_goal
                    else:
                        sc = self.w_rev * len(rev) - self.w_cost * cost
                    cands.append((-sc, cost, d if tgs else 0, rc))
                if not cands:                       # 全被过滤 ⇒ 放宽重来
                    for rc in vis:
                        idx = (rc[0] - 1) * COLS + (rc[1] - 1)
                        bi = sim.board[idx]
                        if bi < 0:
                            continue
                        cost, cells = self._grp_cost(sim, idx)
                        d = min(_dist(rc, t) for t in tgs) if tgs else 0
                        cands.append((self.w_cost * cost + self.w_d * d, cost, d, rc))
                if not cands:
                    break
                cands.sort()
                hit = cands[0][3]
            kind, info = sim.click(hit)
            if kind == 'noop':
                skip.add(hit)
                continue
            order.append(hit)          # ⭐ 真正会点/会开面板的步才进点序（noop 不记 ✓）
            if kind == 'panel':
                bi = sim.board[(hit[0] - 1) * COLS + (hit[1] - 1)]
                b = sim.blocks[bi] if bi >= 0 else None
                if b is not None and (b.is_buy or b.mark or '营地' not in (b.name or '')):
                    sim.resolve_panel(hit, do_buy=True, do_fight=True)
                else:
                    skip.add(hit)
        return order

    def run(self, sim, max_click=None):
        self.plan(sim, max_click)
        return sim.stats()


def compare(n=200, map_name='夏日海滩', difficulty=100, seed=5000, w=None, show=0,
            policy='line'):
    import mapgen
    import mapsim
    import mapsolve
    T = mapgen.load_tables()
    g = mapgen.MapGen(T, map_name, difficulty)
    rows = []
    for k in range(n):
        if policy == 'greedy':
            sim_g = g.gen(seed=seed + k)
            st_g = GreedyPolicy(w).run(sim_g)
        elif policy == 'cost':
            sim_g = g.gen(seed=seed + k)
            st_g = BaselineCostPolicy().run(sim_g)
        elif policy == 'eff':
            sim_g = g.gen(seed=seed + k)
            st_g = EffPolicy().run(sim_g)
        else:
            sim_g = g.gen(seed=seed + k)
            st_g = LineCostPolicy().run(sim_g)
        sim_b = g.gen(seed=seed + k)
        st_b = mapsim.BaselinePolicy().run(sim_b)
        sim_o = g.gen(seed=seed + k)
        prob = mapsolve.Problem(sim_o)
        opt, _acts = mapsolve.solve(prob)
        rows.append({'greedy': st_g['stamina'], 'base': st_b['stamina'], 'opt': opt,
                     'g_left': st_g['left_targets'], 'b_left': st_b['left_targets'],
                     'gclk': st_g['clicks'], 'bclk': st_b['clicks']})
        if k < show:
            print('--- seed %d ｜ 贪心 %d ｜ 基线 %d ｜ 最优 %s'
                  % (seed + k, st_g['stamina'], st_b['stamina'], opt))
    gs = [r['greedy'] for r in rows]
    bs = [r['base'] for r in rows]
    os_ = [r['opt'] for r in rows if r['opt'] is not None]
    print()
    print('对比 %d 张盘（%s 难度 %d）—— 指标=体力（越小越好）' % (n, map_name, difficulty))
    print('  最优(Dijkstra)：平均 %.2f（中位 %d）'
          % (statistics.mean(os_), statistics.median(os_)) if os_ else '  最优：算不出')
    print('  基线(现行规则)：平均 %.2f（中位 %d）；点击 %.2f；漏目标 %d'
          % (statistics.mean(bs), statistics.median(bs),
             statistics.mean([r['bclk'] for r in rows]),
             sum(1 for r in rows if r['b_left'] > 0)))
    print('  **贪心(新策略)**：平均 %.2f（中位 %d）；点击 %.2f；漏目标 %d'
          % (statistics.mean(gs), statistics.median(gs),
             statistics.mean([r['gclk'] for r in rows]),
             sum(1 for r in rows if r['g_left'] > 0)))
    if os_:
        print('  贪心 vs 最优：多花 %.2f%%；完全一样 %d/%d'
              % (100.0 * (statistics.mean(gs) - statistics.mean(os_)) / statistics.mean(os_),
                 sum(1 for r in rows if r['opt'] is not None and r['greedy'] == r['opt']), len(os_)))
        print('  基线 vs 最优：多花 %.2f%%'
              % (100.0 * (statistics.mean(bs) - statistics.mean(os_)) / statistics.mean(os_)))
    return {'greedy': statistics.mean(gs),
            'base': statistics.mean(bs),
            'opt': statistics.mean(os_) if os_ else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', type=int, default=0)
    ap.add_argument('--sweep', type=int, default=0)
    ap.add_argument('--map', default='夏日海滩')
    ap.add_argument('--difficulty', type=int, default=100)
    ap.add_argument('--seed', type=int, default=5000)
    ap.add_argument('--show', type=int, default=0)
    ap.add_argument('--policy', default='eff',
                    choices=('cost', 'line', 'greedy', 'eff'))
    a = ap.parse_args()
    if a.sweep:
        best = None
        for wt, wr, wn, wc in itertools.product((80, 150), (0, 2, 6), (0, 4, 10),
                                                (6, 12, 24)):
            w = {'target': wt, 'reveal': wr, 'near': wn, 'cost': wc}
            r = compare(a.sweep, a.map, a.difficulty, a.seed, w)
            tag = '目标%s 开路%s 靠近%s 体力%s' % (wt, wr, wn, wc)
            print('  %-30s 贪心 %.2f（基线 %.2f 最优 %.2f）'
                  % (tag, r['greedy'], r['base'], r['opt'] or -1))
            if best is None or r['greedy'] < best[0]:
                best = (r['greedy'], w)
        print()
        print('★ 最省的一组权重：贪心平均 %.2f 点体力' % best[0])
        print('   W =', best[1])
        return
    if a.bench:
        compare(a.bench, a.map, a.difficulty, a.seed, show=a.show, policy=a.policy)


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
