# -*- coding: utf-8 -*-
"""verify_plan_fog.py · 回归：**规划不许去点雾格**（真机帧离线复盘，真值手工核对过）

用户 2026-10-05 连报（原话）：
  ①「**这个规划不对**」（海滩 map23）—— 计划 `['2,7','4,6']`：首步是雾格，23 秒 stuck
  ②「**实例B模拟器这俩图规划也不对**」（矿洞 ×2）
  ③「**为什么在废弃矿洞的规划错得离谱，在夏日海滩的就是对的**」
  ④「**可能不是求解器的问题？是识别的问题？**」⇒ **是识别** ✓（求解器只是忠实执行）

真根因：**`ratio` 判不了"亮没亮"**
----------------------------------
`spots.cells()`：`ratio = 该格**中心 60×60** 平均亮度 ÷ 该格被判成的**地块模板**亮度`
  · **分子**：游戏**会在雾格上叠标记图标**（boss/幸运草/大拇指…）⇒ 中心被抬起
  · **分母**：是**模板**⇒ 同一亮度在不同地图/地块上算出不同 ratio ⇒ **判据不可跨图**
真机铁证（`runs/acc2/r_145056_0.png`，废弃矿洞 14:50）：
  格子 `(2,1)` 上画着 **boss 标记**，`ratio = 1.019` ⇒ 被判"已揭示"
  ⇒ 求解器拿它当**第一步**去点 ⇒ 真机 `give_up_step`（点不动）
  ⇒ 整条计划 `2,1 → 3,3 → 3,4 → 5,1` 建立在假前提上 ⇒ **4 次点击全废、18.4 秒白跑** ✗✗
  而按**四角实测**它明明是雾：四角 `[176, 65, 65, 65]`、四边 `上65 下104 左117 右65`
  —— 只有**图标压着的那一角/一边**亮，格子本身 65 = **本帧纯雾基准**（真已揭示格 83~98）✓
为什么"海滩对、矿洞错"：海滩草地模板亮 ⇒ 雾 0.65 / 已揭示 1.0~1.3 间隔干净；
矿洞岩石模板暗 + 图标亮 ⇒ 雾格冲到 **0.85~1.02** ⇒ 一片误判 ✗

本轮修法（识别层，两处）
------------------------
1. `spots._floor_luma()`：新增**"地板"亮度** = 该格**四角**中位数里**最暗**的那个
   （图标最多压住一角/一边 ⇒ 总有一个角是纯地板）⇒ 连同本帧 25 分位的基准一起存进
   每格（`floor` / `floor_lit`）✓
2. `explore_loop._cells_for_model()`：**带标记的格子 ⇒ 由地板说了算**（`ratio` 不算数）
   —— 游戏会在雾格上叠图标（本仓 737 行那段教训已写明），所以"有标记"恰恰是
   `ratio` 最不可信的情形；反方向同理（`runs/r_155829_0.png`：格子真亮 + boss/大拇指
   两个图标 ⇒ ratio 0.708 被判雾 ⇒ 计划打不开首领）⇒ 地板法两边都救 ✓
   ⚠ **没有标记的格子一条都不动**（仍走 `REVEAL_RATIO_MIN` 口径）⇒ 不动那 1068 格的标定 ✓

⚠ 本文件里每张帧的"真值"都是**逐格看图核对过**的常量（不是用被测代码算出来的）
  ⇒ 门禁**不自证清白** ✓

本门禁（离线，不需要模拟器、不联网）
"""
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

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import explore_loop as EL                   # noqa: E402


V = os.path.join(HERE, '_verify')
FAILS = []

# 基准帧：文件名 / 图名 / 标记 / 营地像素 / **肉眼核对过的"真已揭示"集合**
#          ＋ 可选的 `(步数上限, 体力上限)` 期望（用户口径「**不是最优步数**」）
#
# (2,1) 那一格是本轮的主角：boss 图标压在雾格上、ratio=1.019、**真机点不动** ⇒ 真值里没有它 ✓
#
# ⭐ 步数上限的来历（真机 `runs/acc2/r_150954_0.png`，用户原话「不是最优步数」）：
#   `岩地`（矿洞的空地）自带的雾底岩石纹理 `fog_sil` 恒 =0.126 > 老阈值 0.04
#   ⇒ 每格空地都被判"雾下有东西" ⇒ **连锁全断** ⇒ 规划只能一格一格点 ✗✗
#   改成"按本帧众数取阈值"后：矿洞 15:09 **9 步/28 → 4 步/23**、13:53 **6/12 → 3/9**、
#   13:36 **6/11 → 2/7**；海滩不变（**2 步/5**）✓
CASES = [
    ('A 海滩 map23（片内选格）',
     'badplan_map23_20261005.png', '夏日海滩',
     {(4, 6): {'marks': ['boss']}}, (456, 812),
     [(1, 5), (2, 4), (2, 5), (2, 6), (3, 5)], (2, 5)),
    ('B 矿洞 13:53（boss 在雾里）',
     'badplan_map7_20261005.png', '废弃矿洞',
     {(5, 1): {'marks': ['boss']}}, (552, 716),
     [(1, 5), (1, 6), (1, 7), (2, 6)], (3, 9)),
    ('C 矿洞 14:50（**带标记的雾格**）',
     'markfog_mine_145056_20261005.png', '废弃矿洞',
     {(2, 1): {'marks': ['boss']}, (3, 4): {'marks': ['clover']}}, (648, 716),
     [(1, 7), (2, 6), (2, 7), (3, 6), (3, 7)], (4, 23)),
    # ⚠ D 这张是**我上一轮误判过的帧**：当时我按"帧中心最亮"以为 boss `(1,1)` 是亮的、
    #   把"一步直打 boss"当成了正确计划 ✗ —— 逐格看图后确认：`(1,1)` 是**雾格 + boss 图标**
    #   （四角 [176(图标),65,65,65]），真机 round0 也确实点不动它，是**沿第一行揭格**那条
    #   链跑通的（真机 `done`，32 秒）✓ ⇒ 这里把**正确真值**钉住，防止再被"中心亮度"骗回去。
    ('D 矿洞 13:36（我上轮误判的那张）',
     'markfog_mine_135303_20261005.png', '废弃矿洞',
     {(1, 1): {'marks': ['boss']}}, (648, 716),
     [(1, 6), (1, 7), (2, 7)], (2, 7)),
    # ⭐ E＝用户 15:09 报「不是最优步数」「有两下无意义点击」的那张
    #   ⚠ 2026-10-05 二次修正：我先前记的「4 步/23」是**基于过宽的连锁模型**
    #     （让连锁穿过 `荧光蘑菇/首领块`）⇒ 修好"高置信内容地块拦连锁"后是 **6 步/25** ✓
    ('E 矿洞 15:09（用户报"不是最优步数"的那张）',
     'steps_mine_150954_20261005.png', '废弃矿洞',
     {(2, 1): {'marks': ['boss']}, (3, 4): {'marks': ['clover']},
      (5, 1): {'marks': ['explore_full_fight']}}, (648, 716),
     [(1, 7), (2, 6), (2, 7), (3, 6), (3, 7)], (6, 25)),
    # ⭐ G＝用户 15:30 报「**这张图没认出宝箱吗，中间有宝箱拦住连锁了**」的那张
    #   铁证：`(4,1)` = `宝箱`、分类 **score 1.0**，但 `fog_sil` 只有 **0.04**
    #   （宝箱美术是**亮**的，剪影法只抓"比雾底暗"的东西 ⇒ 整个漏掉 ✗✗）
    #   ⇒ 旧模型判它"平坦=空地" ⇒ 连锁穿过宝箱 ⇒ 计划 `['1,6','2,1','3,1','5,4']`（4 步）✗
    #   ⇒ 修后：宝箱/矿箱/地穴（score 0.999~1.0）一律**拦连锁** ⇒ 计划 6 步、绕开它 ✓
    ('G 矿洞 15:30（用户报"有宝箱拦住连锁"的那张）',
     'chest_mine_153038_20261005.png', '废弃矿洞',
     {(5, 4): {'marks': ['boss']}}, (648, 716),
     [(1, 6), (1, 7), (2, 6), (2, 7)], (6, 23),
     # ⭐ 用户报的那一格：`宝箱` 必须**拦连锁**（旧模型因"剪影法抓不到亮色物体"漏了它 ✗）
     [(4, 1), (3, 5), (1, 5)]),
    # ⭐ H＝用户 15:52 报「**夏日沙滩这把出问题了**」的那张（acc1 第 2 张）
    #   真机：计划 `['1,1']` ⇒ 点它 `点不动` ⇒ `[r1] 标记格 1（含点不动的 1）` ⇒ 计划清空 ⇒ stuck 19 秒
    #   根因：`(1,1)` = `椰树`**雾格**（ratio 0.678），而"地板"基准当时用的是**25 分位**
    #     ⇒ 被大件美术的低值（椰树四角 [196,153,147,153] ⇒ min 147）拖到 136 ⇒ 阈值 143
    #     ⇒ 连**纯雾草地(153)** 和椰树(147) 都判成"已揭示" ✗✗
    #   ⇒ 修：地板取**四角中位数**＋基准取**众数**（纯雾值）× 1.35 ✓
    ('H 海滩 15:52（用户报"夏日沙滩这把出问题了"的那张）',
     'fogmark_beach_155257_20261005.png', '夏日沙滩',
     {(1, 1): {'marks': ['boss']}}, (648, 908),
     [(2, 7), (3, 6), (3, 7), (4, 6), (4, 7)], (4, 7),
     [(1, 1)]),
]


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def replay(png, mapname, marks, camp_px):
    p = os.path.join(V, png)
    if not os.path.exists(p):
        return None
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert im is not None and im.shape[:2] == (1280, 720), p
    c = EL.cells_of(im, mapname=mapname)
    st = {'marks': marks, 'spawn': camp_px, 'camp': camp_px}
    log = []
    cells = EL._cells_for_model(st, c, log=log, tag='solver', mark_revealed=False)
    out = {}
    plan = EL.solver_order(st, c, log=[], max_steps=6, out=out)
    return c, cells, plan, out, log


def main():
    print('=== 规划不许去点雾格（真机帧离线复盘；真值逐格看图核对过）===')
    for case in CASES:
        label, png, mapname, marks, camp, truth, want = case[:7]
        content_cells = case[7] if len(case) > 7 else None
        got = replay(png, mapname, marks, camp)
        if got is None:
            print('   （缺基准帧 %s ⇒ 跳过）' % png)
            continue
        c, cells, plan, out, log = got
        rev = sorted(k for k, v in cells.items() if v.get('revealed'))
        truth_s = sorted(truth)
        print()
        print('【%s】' % label)
        print('      模型"已揭示"= %s' % rev)
        print('      看图真值    = %s' % truth_s)
        print('      计划 = %s  cost=%s' % (plan, out.get('cost')))
        ck('%s：模型"已揭示"与看图真值**完全一致**' % label[:1], rev == truth_s,
           '多: %s ｜ 少: %s' % (sorted(set(rev) - set(truth_s)),
                                 sorted(set(truth_s) - set(rev))))
        # ⓪ ⭐ **步数/体力上限**（用户口径「不是最优步数」——空地的连锁不许断 ✗）
        if want:
            _wsteps, _wcost = want
            ck('%s：步数 ≤ %d 且体力 ≤ %d（旧代码空地被判"有东西"⇒ 连锁断 ⇒ 步数翻倍 ✗）'
               % (label[:1], _wsteps, _wcost),
               len(plan) <= _wsteps and (out.get('cost') or 0) <= _wcost,
               '实际 %d 步 / %s 体力' % (len(plan), out.get('cost')))
        # ① 首步必须落在"真的亮着"的格上（否则真机点了没反应）
        ck('%s：计划首步是**真已揭示**的格' % label[:1],
           bool(plan) and plan[0] in truth,
           '首步 %s' % ((plan[0] if plan else None),))
        # ② 不许把"带标记的雾格"当第一步（本轮真根因）
        marked_fog = [k for k in marks if k not in truth]
        ck('%s：**带标记的雾格**没被当成"已揭示"' % label[:1],
           not [k for k in marked_fog if k in rev],
           '带标记的雾格: %s ｜ 被判亮的: %s'
           % (marked_fog, [k for k in marked_fog if k in rev]))
        if marked_fog:
            ck('%s：计划**没有**从带标记的雾格起步（旧代码正是这样 ✗）' % label[:1],
               not plan or plan[0] not in marked_fog,
               '首步 %s' % ((plan[0] if plan else None),))
        # ③ 诊断日志：veto 发生时要说清楚
        #   ⚠ 日志形状是 `{tag: '事件名', ...}`（键是 tag）⇒ 要查**值**，不是 `e.get('事件名')` ✗
        veto = [e for e in log
                if isinstance(e, dict) and 'mark_floor_veto' in e.values()]
        if marked_fog:
            print('      mark_floor_veto: %s'
                  % ([e.get('flips') for e in veto] or '（本轮没有翻转）'))
        # ④ 不许有"被反推成已消耗的**雾格**"（幻影前沿：真机 map7 那把 9 格 ⇒ boss 变可点 ✗）
        # ⑤ 指定的"内容地块"必须**拦连锁**（`plain=False`）—— 用户报的宝箱就靠这条钉住 ✓
        if content_cells:
            import mapsim as _ms2
            import spots as _sp2
            _sim = _ms2.MapSim.from_observation(cells, _sp2.spot_rows())
            _bad = []
            for _rc in content_cells:
                _ci = (_rc[0] - 1) * 7 + (_rc[1] - 1)
                _bi = _sim.board[_ci] if _ci < len(_sim.board) else -1
                _b = _sim.blocks.get(_bi) if _bi >= 0 else None
                if _b is None or getattr(_b, 'plain', True):
                    _bad.append('%d,%d(%s)' % (_rc[0], _rc[1],
                                               getattr(_b, 'name', '?')))
            ck('%s：内容地块 %s **都拦了连锁**（plain=False）'
               % (label[:1], ['%d,%d' % k for k in content_cells]),
               not _bad, '仍被当空地: %s' % (_bad,))
        dropped = []
        for e in log:
            if isinstance(e, dict) and 'done_cells_dropped' in e.values():
                dropped = [tuple(int(x) for x in s.split(','))
                           for s in (e.get('cells') or [])]
        fog_dropped = [k for k in dropped if k not in truth]
        ck('%s：没有"被反推成已消耗的**雾格**"（幻影前沿）' % label[:1],
           not fog_dropped, '雾格被误剔: %s' % (fog_dropped,))

    print()
    print('=' * 74)
    # ── F. 空地口径（用户原话：「**空地有好多种，其实本质都一样**」／
    #      「**只有类似那种宝箱海螺的非空地才会拦截连锁**」）
    #   数据表口径：地面填充块 = `Weight 40000 / MaxNum 35 / SpecialSpot 0`
    #   （全表 15 个：雪地×1 岩地×3 草地×8 海底×1 沙地×2 —— **本质一样** ✓）
    #   ⚠ 旧代码靠 `号段 == '001'` ＋ `'草' in 名字` ⇒ 岩地/沙地/雪地/海底 全被判"非空地" ✗
    print()
    print('【F】空地口径：多种地面一视同仁；内容块才拦连锁')
    import spots as _sp
    import mapsim as _ms
    _rows = _sp.spot_rows()
    _ground, _content, _bad_g, _bad_c = [], [], [], []
    for _sid, _r in _rows.items():
        _nm = _r.get('Name')
        _r2 = dict(_r)
        _r2['sid'] = _sid
        _b = _ms.Block(0, _r2, revealed=True)
        try:
            _fill = int(_r.get('Weight') or 0) >= 40000 and not int(_r.get('SpecialSpot') or 0)
        except Exception:                       # noqa: BLE001
            _fill = False
        if _fill:
            _ground.append(_sid)
            if not _b.plain:
                _bad_g.append(_sid)
        elif _nm != '营地':
            _content.append(_sid)
            if _b.plain:
                _bad_c.append(_sid)
    print('      地面填充块 %d 个 ⇒ 判空地 %d 个（漏判 %s）'
          % (len(_ground), len(_ground) - len(_bad_g), _bad_g))
    print('      内容块 %d 个 ⇒ 判非空地 %d 个（误判成空地的 %s）'
          % (len(_content), len(_content) - len(_bad_c), _bad_c))
    ck('F：**所有地面填充块**（雪地/岩地/草地/海底/沙地…）都算空地',
       not _bad_g, '漏判: %s' % (_bad_g,))
    ck('F：**内容块一个都不许当空地**（否则连锁穿过宝箱/海螺 ✗）',
       not _bad_c, '误判: %s' % (_bad_c,))
    ck('F：判据**不看号段、不看名字子串**（旧代码 `号段001`＋`名字含草` ✗）',
       'PLAIN_SUFFIX and suf' not in open(os.path.join(HERE, 'mapsim.py'),
                                          encoding='utf-8').read())

    print()
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：三张真机帧的"已揭示"与看图真值一致；'
          '带标记的雾格不再被当成可点；计划首步都落在真亮的格上')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
