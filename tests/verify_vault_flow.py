# -*- coding: utf-8 -*-
"""verify_vault_flow.py · 回归：黄金宝库必须**买完三层**，且**不许连点「返回」**

用户 2026-10-04 报（原话）：
    「刚刚那把黄金宝库没正常购买完，修一下购买流程。正常来说应该是
      **购买，扫描奖励，点击奖励，选择奖励，返回**，这套循环，
      脚本有时候**连点两下返回**，有时候会**没买完第三层就关了黄金宝库页面**」

根因（读代码定位，不是猜）—— `vault_flow` 第 ③ 步原来是：

    点一次固定「返回」  **＋**  `if _dismiss(): _dismiss()`

而 `_dismiss(tries=3)` **每次最多再点 3 下「返回」** ⇒ 同一轮**最多点 5 下** ✗
奖励展示**关掉之后**剩下那几下就落在**宝库面板**上（(360,806) 一带正是格子）：
  轻则"连点两下返回"；重则点到格子、甚至把宝库面板点关
  ⇒ 第 3 层还没买就退出 = 用户看到的「没买完第三层就关了」✗（**两条症状同一个根因**）

修法：三处点「返回」的地方统一走 `_back_fixed()` ——
  **点一次 → 轮询等它真收起 → 真的还在才补一次**（上限 2 下，正常 1 下）
  ⚠ 关键认识：**收起是动画，要靠"等"，不是靠"再点一下"** ✓

本门禁**直接驱动真 `vault_flow`**（只把 `_items` / `vault_pick` 换成脚本），
面板按**时钟**变（不是按"第几次读"——那样测不出"等没等"）：

  ① 正常（点一下立刻收起）    ⇒ 三层买齐，每层「返回」**正好 1 下**
  ② **慢收起**（1.2s 才收起） ⇒ 每层**仍然正好 1 下** ← ★ 这一档是**牙齿**：
     旧代码读一帧发现"还在"就再点一下 = 用户看到的「连点两下返回」✗
  ③ 赖着不走（永不收起）      ⇒ 每处「返回」**≤2 下**，且**不许放弃后面的圈**

用法：
    python verify_vault_flow.py
"""
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
import time

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import buypanels as BP                     # noqa: E402


FAILS = []
PRICE = {1: 10000, 2: 20000, 3: 40000}
BTN = (596, 998)                           # 购买/选择奖励/离开 —— 同一个固定按钮
RET = tuple(BP.VAULT_RET)                  # 固定「返回」(360,806)


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


class VaultBot:
    """脚本化宝库面板：**按时间**给出 items，并按点击推进状态

    状态机（与用户口径一致）：
        buy(10000) --点按钮--> select --点按钮（选择奖励）--> reward
        reward --点「返回」，`close_delay` 秒后收起--> 下一圈 buy(20000) …
        第 3 圈之后 --> leave

    `close_delay=None` ⇒ **永不收起**（模拟面板赖着不走：旧代码在这档连点 5~7 下）
    """

    def __init__(self, close_delay=0.0, appear_delay=0.0):
        self.close_delay = close_delay
        self.appear_delay = appear_delay      # ⭐ 奖励面板**过多久才出现**（实测：过动画才出来）
        self.ring = 1
        self.state = 'buy'
        self.taps = []
        self.backs = []                    # 每次「返回」点击的时刻/当时是否还在展示
        self._pending_at = None            # 返回点击后，计划收起的时间点
        self._appear_at = None             # 选择奖励点击后，计划出现的时间点

    # ---- 面板 OCR（脚本化）----
    def items_now(self):
        # ⭐ 先结算"计划中的出现 / 收起"
        if self._appear_at is not None and time.time() >= self._appear_at:
            self._appear_at = None
            if self.state == 'select':
                self.state = 'reward'
        if self._pending_at is not None and self.close_delay is not None \
                and time.time() >= self._pending_at:
            self._pending_at = None
            if self.ring >= 3:
                self.state = 'leave'
            else:
                self.ring += 1
                self.state = 'buy'
        base = [{'text': '黄金宝库', 'cx': 360, 'cy': 300, 'conf': 1.0}]
        if self.state == 'buy':
            base += [{'text': '购买', 'cx': BTN[0], 'cy': BTN[1], 'conf': 1.0},
                     {'text': str(PRICE[self.ring]), 'cx': BTN[0] + 14, 'cy': BTN[1] + 22,
                      'conf': 1.0}]
        elif self.state == 'select':
            base += [{'text': '选择奖励', 'cx': BTN[0], 'cy': BTN[1], 'conf': 1.0}]
        elif self.state == 'reward':
            base += [{'text': '恭喜获得', 'cx': 360, 'cy': 200, 'conf': 1.0},
                     {'text': '返回', 'cx': RET[0], 'cy': RET[1], 'conf': 1.0}]
        elif self.state == 'leave':
            base += [{'text': '离开', 'cx': BTN[0], 'cy': BTN[1], 'conf': 1.0}]
        return base

    # ---- 被 vault_flow 调用的接口 ----
    def tap_dlg(self, x, y, wait=1.2):
        return self.tap(x, y)

    def tap(self, x, y, wait=1.2):
        x, y = int(x), int(y)
        self.taps.append((x, y))
        near_ret = abs(x - RET[0]) <= 3 and abs(y - RET[1]) <= 3
        near_btn = abs(x - BTN[0]) <= 6 and abs(y - BTN[1]) <= 6
        if near_ret:
            # 记录"点这一下的时候，奖励展示到底还在不在"
            self.backs.append({'ring': self.ring,
                               'shown': self.state == 'reward'})
            if self.state == 'reward' and self.close_delay is not None:
                self._pending_at = time.time() + self.close_delay
            return True
        if near_btn:
            if self.state == 'buy':
                self.state = 'select'
            elif self.state == 'select':
                # ⭐ 点「选择奖励」⇒ 奖励面板**过 `appear_delay` 秒才出来**（真机实测如此）
                self._appear_at = time.time() + self.appear_delay
                if self.appear_delay <= 0:
                    self._appear_at = None
                    self.state = 'reward'
            return True
        if self.state == 'select':
            self.state = 'reward'
        return True

    def snap(self, *a, **kw):
        return 'stub'

    def img(self):
        return None

    def ocr(self, *a, **kw):
        return []

    def ocr_dlg(self, *a, **kw):
        return []

    def board_luma(self):
        return 0.0


def run_case(close_delay, appear_delay=0.0):
    bot = VaultBot(close_delay=close_delay, appear_delay=appear_delay)
    log = []
    oi, op = BP._items, BP.vault_pick
    BP._items = lambda _b, reuse=True: bot.items_now()
    BP.vault_pick = lambda _b, _l, level, max_probe=25: ((300, 700), '天赋果实')
    try:
        acts = BP.vault_flow(bot, log)
    finally:
        BP._items, BP.vault_pick = oi, op
    return acts, bot, log


def per_ring(backs):
    d = {}
    for b in backs:
        d[b['ring']] = d.get(b['ring'], 0) + 1
    return d


def main():
    print('=== 黄金宝库流程回归（真 vault_flow + 脚本化面板，面板按**时钟**变）===')
    print('固定「返回」= %s ｜ 固定按钮 = %s' % (RET, BTN))
    print()

    # ── ① 正常：立刻收起 ⇒ 三层买齐，每层正好 1 下 ──
    print('【1】正常（点一下就收起）：三层必须买齐，每层「返回」**正好 1 下**')
    acts, bot, log = run_case(close_delay=0.0)
    print('      acts = %s' % (acts,))
    print('      每层返回次数 = %s' % (per_ring(bot.backs),))
    need = ['buy1', 'claim1', 'buy2', 'claim2', 'buy3', 'claim3']
    ck('三层都买齐（buy1/claim1 … buy3/claim3 齐全）',
       all(a in acts for a in need), '缺 %s' % [a for a in need if a not in acts])
    ck('第 3 层确实买到（不再"没买完第三层就关了"）', 'claim3' in acts, 'acts=%s' % (acts,))
    ck('每层「返回」**正好 1 下**（不连点）',
       all(per_ring(bot.backs).get(r) == 1 for r in (1, 2, 3)),
       '%s' % (per_ring(bot.backs),))
    ck('点「返回」时奖励展示**确实还在**（没对着宝库面板乱点）',
       all(b['shown'] for b in bot.backs), '%s' % (bot.backs,))

    # ── ② 牙齿：慢收起 ⇒ 每层**仍然正好 1 下**（旧代码会补成 2 下 = 用户看到的"连点两下"）──    print()
    print('【2】牙齿：面板 **1.2s 才收起** ⇒ 每层**仍然正好 1 下**')
    print('      （旧代码：读一帧发现"还在"就再点一下 ⇒ 「连点两下返回」✗）')
    acts2, bot2, _l2 = run_case(close_delay=1.2)
    print('      每层返回次数 = %s' % (per_ring(bot2.backs),))
    ck('每层「返回」**仍然正好 1 下**（靠**等**它收起，不是靠再点一下）',
       all(per_ring(bot2.backs).get(r) == 1 for r in (1, 2, 3)),
       '%s' % (per_ring(bot2.backs),))
    ck('慢收起下三层也全部买到（等待没有把流程拖坏）',
       all(a in acts2 for a in need), 'acts=%s' % (acts2,))
    ck('点「返回」时奖励展示确实还在', all(b['shown'] for b in bot2.backs))

    # ── ③ 赖着不走 ⇒ 每处 ≤2 下，且不许放弃后面的圈 ──
    print()
    print('【3】面板赖着不走（永不收起）⇒ 每处「返回」**≤2 下**，且不许放弃后面的圈')
    acts3, bot3, log3 = run_case(close_delay=None)
    ns = [d.get('n') for d in log3 if isinstance(d, dict) and d.get('vault') == 'back_fixed']
    print('      每次 back_fixed 的 n = %s' % (ns,))
    print('      acts = %s' % (acts3,))
    ck('每一处「返回」都 **≤2 下**（第 1 下没收干净才补第 2 下）',
       bool(ns) and max(ns) <= 2, 'max(n)=%s' % (max(ns) if ns else None))
    ck('**没有**任何一处点到第 3 下（旧代码这里是 3~4 下）',
       all(n <= 2 for n in ns), '%s' % (ns,))
    ck('没因为"收不干净"就放弃后面的圈（还试到了第 2/3 圈）',
       any('2' in a for a in acts3), 'acts=%s' % (acts3,))

    # ── ④ ⭐⭐ 本轮真机抓到的那个根因：奖励面板**慢出现**就点返回 = 打在棋盘格上 ──
    #   实测（用户当场点「选择奖励」，我前后各抓一帧）：
    #     点之后奖励面板**过动画才出来**；而 `tap_dlg(wait=2.6)` 里的 `wait_change` 会被
    #     "按钮自己按下去的高亮"**立刻触发** ⇒ 旧代码那时就去点 (360,806)，
    #     而**宝库面板上 (360,806) 正是棋盘格（行3,列2）** ⇒ 换选了别的格子 ✗
    #   ⇒ 本档断言：**每一次「返回」点击时，奖励展示必须已经出现**（`shown=True`）
    print()
    print('【4】⭐ 奖励面板**慢出现**（1.2s）⇒ 点「返回」时它必须**已经在了**')
    print('      （旧代码在这里会把第 1 下打在**棋盘格**上：宝库面板 (360,806) = 行3列2 ✗）')
    acts4, bot4, _l4 = run_case(close_delay=0.0, appear_delay=1.2)
    print('      每次返回点击（ring, 当时奖励展示在不在）= %s' % (bot4.backs,))
    ck('每一次「返回」点击时，奖励展示**已经出现**（没有一下打在棋盘格上）',
       bool(bot4.backs) and all(b['shown'] for b in bot4.backs),
       '%s' % (bot4.backs,))
    ck('每层「返回」仍然**正好 1 下**', all(per_ring(bot4.backs).get(r) == 1 for r in (1, 2, 3)),
       '%s' % (per_ring(bot4.backs),))
    ck('慢出现下三层也全部买到', all(a in acts4 for a in need), 'acts=%s' % (acts4,))

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：三层买齐；返回**只在奖励展示出现后**点、正常 1 下、异常 ≤2 下')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
