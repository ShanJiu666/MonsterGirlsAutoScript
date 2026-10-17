# -*- coding: utf-8 -*-
"""verify_gold_gate.py · 回归：**金币 < 50 万 ⇒ 商人和宝库不买、也不规划**（用户口径）

用户 2026-10-05 原话：
    「**扫体力顺便把金币数量也扫了吧，加个金币低于50万就自动不去购买商人和宝库
      （也不规划，就相当于拉黑了），高于50w就还是正常买**」

读数位置（14 张真机帧、**两个账号**实测）
--------------------------------------------------
    (435, 26) '441031'    ← acc1/acc2 的金币（6 位）
    (429, 26) '2300302'   ← 另一账号（7 位 ⇒ 中心左移 6px，窗口留裕量 ✓）
    ⚠ 与幸运草（y≈59）**只差一行 y** ⇒ 判据**必须用 y 分开**（x 区间有重叠 ✗）
    ⚠ 与钻石/宝石（x≈581~587、y≈26）用 **x 区间**分开 ✓

真机读数（人眼核对，全部正确）
--------------------------------------------------
    clover_1  金币 357731  幸运草 3    ⇒ **不足**（<50 万）
    clover_2  金币 441031  幸运草 7    ⇒ **不足**
    clover_3  金币 441031  幸运草 5    ⇒ **不足**
    clover_4  金币 441031  幸运草 2    ⇒ **不足**
    clover_5  金币 441031  幸运草 1    ⇒ **不足**
    clover_6  金币 441031  幸运草 1    ⇒ **不足**
    r_225702  金币 4014282              ⇒ 够
    r_225757  金币 2300302              ⇒ 够
    ⇒ acc1 那批**只有 35.7~44.1 万** ⇒ 按用户口径**本来就不该买** ✓

修法（三处，缺一不可）
--------------------------------------------------
  ① `gold_count(items)` —— 从**体力那一行的同一次 OCR** 里读（**零额外开销** ✓）
  ② `popups()` 的 special 分支：金币不足 ⇒ **只关面板不买**（`ensure_closed`）
  ③ `pending_buy` **统一清空**（本帧 `buy`/`buy_hidden` ＋ 跨轮 `sticky` ＋ `buy_seen`
     记忆 **三条来源都要挡**）—— 只过滤第一处不够，那样它仍会被规划 ✗
  ④ 点击循环里认到宝库面板时**同样先查金币**（否则那条"就地买"会绕过闸门 ✗）
  ⚠ 读不到金币（None）⇒ `gold_enough` 返回 **True** = 照常买（保守：
    一次 OCR 失败不该把整局的商人/宝库全丢掉 ✗）

牙齿：去掉任一处闸门 / 把阈值改错 ⇒ 本门禁必红 ✓
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


os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import explore_loop as EL

    print('=== 金币 < 50 万 ⇒ 商人和宝库不买、也不规划（用户口径）===')

    # ── ① 阈值与窗口 ────────────────────────────────────────────────
    print()
    print('【1】阈值 = 50 万；读数窗口靠 **y 行**与幸运草分开')
    ck('`GOLD_MIN_BUY == 500000`', int(EL.GOLD_MIN_BUY) == 500000,
       '实际 %s' % EL.GOLD_MIN_BUY)
    gy = EL.GOLD_HUD_Y
    cy = EL.CLOVER_HUD_Y
    ck('金币窗口（y %s）与幸运草（y %s）**不重叠**（x 有重叠 ⇒ 只能靠 y ✗）'
       % (gy, cy), gy[1] < cy[0], 'gold_y_max=%s clover_y_min=%s' % (gy[1], cy[0]))

    # ── ② 读数判据：不误取别的数字 ──────────────────────────────────
    print()
    print('【2】`gold_count` 判据（不会误取幸运草/钻石/体力/PID）')
    cases = [
        ([{'text': '441031', 'cx': 435, 'cy': 26},
          {'text': '8365', 'cx': 587, 'cy': 26},
          {'text': '1', 'cx': 463, 'cy': 59}], 441031, '真机 acc1 ⇒ 441031'),
        ([{'text': '2300302', 'cx': 429, 'cy': 26},
          {'text': '296', 'cx': 451, 'cy': 59}], 2300302, '另一账号 7 位数 ⇒ 2300302'),
        ([{'text': '1', 'cx': 463, 'cy': 59}], None,
         '只有幸运草（y=59）⇒ **读不到金币**（不能被当金币 ✗）'),
        ([{'text': '8365', 'cx': 587, 'cy': 26}], None,
         '钻石/宝石（x=587 区间外）⇒ 不误取 ✓'),
        ([{'text': '1949/2100', 'cx': 224, 'cy': 62}], None, '体力带 `/` ⇒ 不是纯数字 ✓'),
        ([{'text': 'PID:162332', 'cx': 152, 'cy': 25}], None, 'PID 含冒号 ⇒ 不误取 ✓'),
        ([{'text': '4,410,31', 'cx': 435, 'cy': 26}], 441031,
         'OCR 带千分位逗号 ⇒ 去掉逗号仍读对 ✓'),
        ([], None, '没读到 ⇒ None（**不猜** ✓）'),
        # ⭐⭐⭐⭐ 2026-10-08 修：**图标被 OCR 粘在数字上**（与幸运草同一个病）
        #   真机取证 `runs/spec_dev/acc3_all/clover_hud.png`：草 `4 Φ`/`12 ±`/`287Φ`
        #   金币那边同理（批量 24 帧实测：修前只命中 **10/24** ✗）
        ([{'text': '441031Φ', 'cx': 435, 'cy': 26}], 441031,
         '**尾随图标**粘上 ⇒ 仍读 441031 ✓'),
        ([{'text': '3023719 ±', 'cx': 440, 'cy': 25}], 3023719,
         '尾随杂字 ⇒ 仍读 3023719 ✓'),
    ]
    for items, want, name in cases:
        got = EL.gold_count(items)
        ck('%-48s ⇒ %s' % (name, want), got == want, '实际 %s' % got)

    # ── ③ 门槛的**保守方向**：读不到 ⇒ 照常买 ────────────────────────
    print()
    print('【3】门槛方向（读不到不能变成"永远不买" ✗）')
    ck('`gold_enough(None)` = **True**（照常买 —— 一次 OCR 失败不该丢整局的商人/宝库 ✓）',
       EL.gold_enough(None) is True)
    ck('`gold_enough(499999)` = False', EL.gold_enough(499999) is False)
    ck('`gold_enough(500000)` = **True**（边界：够 ✓）', EL.gold_enough(500000) is True)
    ck('`gold_enough(500001)` = True', EL.gold_enough(500001) is True)

    # ── ④ 三处闸门都要在（缺一处 ⇒ 能被绕过 ✗）──────────────────────
    print()
    print('【4】闸门必须覆盖**四条路径**（缺一就能绕过）')
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()

    def body_of(fn):
        s = [n for n, l in enumerate(lines) if l.startswith('def %s(' % fn)]
        if not s:
            return ''
        s = s[0]
        e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
        return '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))

    pop = body_of('popups')
    ck('① `popups()` special 分支：金币不足 ⇒ `buy_skip_low_gold`（只关不买 ✓）',
       'buy_skip_low_gold' in pop)
    ck('① 且真的调了 `ensure_closed`（把已经开着的面板关掉，不买 ✓）',
       'ensure_closed' in pop[pop.find('buy_skip_low_gold') - 900:
                              pop.find('buy_skip_low_gold') + 200]
       if 'buy_skip_low_gold' in pop else False)
    ck('② `pending_buy` **统一清空**（`buy_pending_cleared_low_gold`）'
       '—— 本帧+跨轮 sticky+记忆三条来源都要挡 ✓',
       'buy_pending_cleared_low_gold' in src)
    ck('② 同时清了 `buy_sticky`（否则跨轮粘性集会把它重新塞回 pending ✗）',
       "setdefault('buy_sticky', {}).clear()" in src
       or "buy_sticky'].clear()" in src)
    ck('③ 本帧 `buy`/`buy_hidden` 也剔了（`buy_blocked_low_gold` ⇒ 不进 buy_px ⇒ 等于拉黑 ✓）',
       'buy_blocked_low_gold' in src)

    # ── ⑤ ⭐⭐⭐ 2026-10-06 **第 5 条路：求解器的目标集合**（用户报的真漏口）─────────
    #   用户 2026-10-06 原话：「**还有为什么这个号金币明明低于50万了，却还是去买宝库了**」
    #   ⛔ 真根因：上面 ①~④ 挡的全是「**待买清单**」（`buy`/`buy_hidden`/`sticky`/`buy_seen`），
    #     可商人/宝库进计划**根本不看那张清单** —— 求解器看 `Block.want`，
    #     而 `want` 由 `_cells_for_model` 里 `is_target(name, sid, marks)` **单独算**，
    #     「黄金宝库」在 `targets_cfg.DEFAULT_ON` 里是**默认勾选** ⇒ 恒 True ⇒ 绕过全部闸门 ✗✗
    #   真机铁证（acc3 `runs/acc3/loop/loop_log.json` 第 7 张图）：
    #     #282 hud_lock gold v=95531 enough=false → #284 buy_blocked_low_gold ["1,5"]
    #     → #286 buy_pending_cleared_low_gold ["1,5"]
    #     → #292 solver ok order=["5,6","1,1","**1,5**","4,7"]   ← ✗✗ 还在计划里！
    print()
    print('【5】第 5 条路：金币不足 ⇒ 商人/宝库**彻底拉黑**（连借道都不许）')
    ck('⑤ `_cells_for_model` 里按了 `target`（`buy_target_off_low_gold`）',
       'buy_target_off_low_gold' in src)
    _cfm = body_of('_cells_for_model')
    ck('⑤ 判据用的是**锁定值** `gold_enough_locked(st)`（一图只确认一次 ✓，不是每轮重读 ✗）',
       'gold_enough_locked(st)' in _cfm)
    ck('⑤ 只对 `spots_mod.BUY_OUT_NAMES`（旅行商人/黄金宝库）生效 —— 不许误伤别的目标 ✗',
       'BUY_OUT_NAMES' in _cfm)
    ck('⑤ 读不到金币 ⇒ 判据为 True ⇒ **不动 target**（fail-open：照常买 ✓）',
       'not gold_enough_locked' in _cfm)
    # ⭐⭐⭐⭐⭐ 2026-10-06 口径升级（用户原话：「**改成彻底拉黑**」）：
    #   旧口径只按 `target` ⇒ 宝库会以**垫脚石（借道）**身份进计划 ⇒
    #   真机点它就弹面板（用户报：「说了不进规划目标，为什么计划里还有 3,2」✗）
    #   ⇒ 新口径必须**同时写 `blocked=True`**（求解器既不点、也不借道 ✓）
    print()
    print('【5b】★ 金币不足 ⇒ **连 `blocked` 一起写**（否则会以"垫脚石"身份进计划 ✗）')
    ck('⑤b 金币那支里**同时**写了 `blocked`（不是只按 target ✗）',
       "['blocked'] = True" in _cfm or '"blocked"' in _cfm and 'True' in _cfm)
    ck('⑤b 下面那条通用 `blocked` 赋值是**只增不减**（`or`，不是直接赋值 ✗✗）',
       "_vv['blocked'] = bool(_vv.get('blocked')) or" in _cfm)
    ck('⑤b 日志条目带 `blocked: True`（措辞如实，不再只说"不进规划目标" ✗）',
       "'blocked': True" in src)
    ck('⑤b 日志/终端措辞写明"彻底拉黑"或"不借道"',
       '彻底拉黑' in src or '不借道' in src)

    # 行为级：真建一份模型，验"金币不足 ⇒ 宝库不在 Problem.targets 里"（不是查字符串 ✓）
    print()
    print('【6】**行为级**：同一张盘，金币够 / 不够 ⇒ 目标集合必须不同')
    try:
        import mapsim as _ms
        import mapsolve as _mv

        def _prob_with(gold):
            """真建一份**求解器用的** Problem（不是 MapSim.targets() ——
            那个是**老口径** `mark or is_buy`，求解器根本不看它 ✗）。"""
            _obs = {
                (1, 5): {'sid': 'S30001_016', 'name': '黄金宝库', 'score': 0.999,
                         'ratio': 1.0, 'anchor': (1, 5), 'marks': []},
                (1, 1): {'sid': 'S30001_001', 'name': '空地', 'score': 0.99,
                         'ratio': 1.0, 'anchor': (1, 1), 'marks': []},
            }
            _st = {'gold_locked': gold, 'marks': {}, 'obs': _obs}
            _c = {'st': _obs, 'gray': [], 'light': []}
            _cells = EL._cells_for_model(_st, _c, log=None, tag='gate')
            _sim = _ms.MapSim.from_observation(_cells, EL.spots_mod.spot_rows())
            return _cells, _mv.Problem(_sim)

        _cells_rich, _prob_rich = _prob_with(EL.GOLD_MIN_BUY)
        _cells_poor, _prob_poor = _prob_with(EL.GOLD_MIN_BUY - 1)
        _v_rich = [k for k, v in _cells_rich.items() if v.get('target')]
        _v_poor = [k for k, v in _cells_poor.items() if v.get('target')]
        ck('金币够 ⇒ 宝库格 `target=True`（进目标集合 ✓）',
           bool(_v_rich), 'target 格 %s' % (_v_rich,))
        ck('金币不足 ⇒ 宝库格 `target=False`（**不进目标集合** ✓）',
           not _v_poor, 'target 格 %s' % (_v_poor,))
        # ⭐⭐⭐ 2026-10-06 **口径升级**（用户原话：「**改成彻底拉黑**」）：
        #   旧断言写的是「金币不足 ⇒ **不写 blocked**（走路仍可借它）」，理由是
        #   「写 blocked 会连走路都不许 ✗」—— **那条理由现在被用户否掉了**：
        #   真机上"借道"= "点它"= **一定弹面板** ⇒ 借道这个假设在内容格上根本不成立 ✗
        #   真机铁证（`runs/acc2/r_231259_0.png` 废弃矿洞）：
        #     日志「不进规划目标（3,2）✓」→ 计划 `['3,1','3,2','3,3','2,3']`
        #     → 点 (168,908) → **黄金宝库面板**（只关不买，但白点一下）✗
        #   实测账（独立 Dijkstra 交叉验证）：只按 target ⇒ cost 7（白点面板）；
        #     连 blocked 一起写 ⇒ cost 11（绕打 1,1 矿箱堆）但**完全不碰它** ✓
        #   ⇒ 用户拍板：**宁可多花体力，也不要白点面板** ✓
        #   ⚠ 下面这条**必须留着**（它是"打脸守门"）：写 blocked 时**不能把
        #     本来该买的宝库也封了** —— 所以只查"金币不足"这一支 ✓
        #   ⚠ 判据要钉**宝库那一格**（`(1,5)`），不是"所有格都 blocked" ✗ ——
        #     空地格本来就没有 `blocked` 键（它是 `is_blocked` 那条路的事）✓
        #     （我第一版写成 `all(...)` 遍历全部格 ⇒ **假红**，被本门禁自己抓出 ✓）
        _blk_poor = [k for k, v in _cells_poor.items() if v.get('blocked')]
        ck('★ 金币不足 ⇒ 宝库格 `blocked=True`（**本图彻底不碰它**：不点也不借道 ✓）',
           (1, 5) in _blk_poor, 'blocked 格 = %s' % (_blk_poor,))
        ck('★ 金币不足 ⇒ **只有**宝库那格被 blocked（不许顺手封别的格 ✗）',
           _blk_poor == [(1, 5)], 'blocked 格 = %s' % (_blk_poor,))
        ck('★ 金币够 ⇒ 宝库格 **不** blocked（不能误伤正常购买 ✗）',
           not any(v.get('blocked') for v in _cells_rich.values()))
        ck('金币够 ⇒ 宝库块**在** `Problem.targets`（求解器看得到 ✓）',
           bool(_prob_rich.targets), 'targets=%s' % (sorted(_prob_rich.targets),))
        ck('金币不足 ⇒ 宝库块**不在** `Problem.targets`（求解器根本看不到它 ✓）',
           not _prob_poor.targets, 'targets=%s' % (sorted(_prob_poor.targets),))
        ck('★ 金币不足 ⇒ 宝库块在 `Problem` 的 **blocked 集合**里'
           '（求解器**既不点、也不借它走路** ✓ —— 这才是"彻底拉黑"的实现）',
           any(getattr(_prob_poor.blocks[bi], 'blocked', False) for bi in _prob_poor.blocks),
           'blocked 块 = %s'
           % ([bi for bi in _prob_poor.blocks
               if getattr(_prob_poor.blocks[bi], 'blocked', False)],))
        ck('金币读不到（None）⇒ 宝库仍 `target=True`（fail-open：照常买 ✓）',
           bool([k for k, v in _prob_with(None)[0].items() if v.get('target')]))
        ck('★ 金币读不到（None）⇒ **不写 blocked**（fail-open：也照常借道 ✓）',
           not any(v.get('blocked') for v in _prob_with(None)[0].values()))
    except Exception as _e:             # noqa: BLE001
        ck('行为级目标集合对拍', False, '异常 %r' % (_e,))

    _one = body_of('one_round')
    # ⚠⚠ 旧断言写的是 `'gold_enough' in _one` —— **假绿**：`_one` 是整个 `one_round()`
    #   函数体，而函数里**别处**本来就有 `gold_enough` ⇒ 就算就地买那一支没查金币也照样绿 ✗
    #   ⇒ 现在必须**定位到就地买那一支**再查（门禁自己要能证伪 ✓）
    _iv = _one.find('vault_panel_inline')
    ck('④ 点击循环的就地买宝库那支**也查金币**（否则它能绕过闸门 ✗）',
       _iv >= 0 and 'gold_enough_locked(st)' in _one[max(0, _iv - 2200):_iv],
       'vault_panel_inline 在第 %d 字符；其前 2200 字符内须有 gold_enough_locked(st)' % _iv)
    ck('④ 且金币不足时**只关不买**（`ensure_closed` ＋ `skip_low_gold_inline`）',
       'skip_low_gold_inline' in _one and 'ensure_closed' in _one[max(0, _iv - 2200):_iv])

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：金币 <50 万 ⇒ 商人/宝库**不买也不规划**（= 拉黑）；'
          '≥50 万照常买；读不到时保守照常买；四条路径全部挡住')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
