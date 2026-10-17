# -*- coding: utf-8 -*-
"""alchemy.py · 炼金（公会展厅 **4 楼顶楼**左边那个普通宝箱）

用户口径（2026-10-14，原话）
--------------------------
· 「炼金往上滑就能看到个有感叹号的箱子」
· 「这时候要**点满星**，然后点**开始炼金**」
· 「这些我打算是**体力刷完自动去做**」⇒ 由主循环在收工时调用 ✓

位置（实测，**别点错**）
----------------------
    公会展厅 → 手指下滑滚到顶楼（4 楼）→ **左边普通宝箱 (248,455)**
    ⛔ 同一层还有两个**看起来像、但完全不是炼金**的东西：
        (370,430) 大陶罐          ⇒ 点了**无反应**
        (519,455) 紫发角色        ⇒ 是「**献祭宝箱怪**」（天赋互换）✗
      （我第一轮就把这两个都点错过，见 `_tmp_probe_dispatch/CALIBRATION.md`）

炼金四态（点箱子之后会怎样）
--------------------------
    ① **已炼好待领** ⇒ 弹「**炼金结果**」面板（货币 + 道具 + 「返回」）
                        ⇒ 点「返回」(359,931) 领走 ✓（金币已到账，实测 +96000）
    ② **炼金进行中** ⇒ 开「炼金宝箱」面板；箱子上有 `HH:MM:SS` 倒计时浮层
                        ⇒ 本脚本**默认不动它**（除非 `--accel`）
    ③ **空闲无待领** ⇒ 开「炼金宝箱」面板（6 个空槽 + 「开始炼金」）
                        ⇒ `--auto-start` 时走"满星 → 开始炼金" ✓

「满星」为什么是关键（实测 + 源码）
--------------------------------
    `ALCH_FILTER_FULLSTAR = (341,1118)` 点一下 ⇒ **6 个投料槽自动填满 5★ 满星装备**
      · 预计时间从 `--:--:--` 变成 `07:59:30` ✓（实测）
      · 再点「开始炼金」(600,471) 就开跑 ⇒ 箱子上出现 `07:59:28` ✓（实测）
    这就是用户说的「点满星，然后点开始炼金」—— **两步**而已 ✓

⚠⚠ 消耗类动作（默认为**开**，可一键关掉）
----------------------------------------
    「开始炼金」会**消耗掉投入的 6 件满星装备**（换成金币 + 结晶）——**不可逆**。
    ⭐⭐⭐⭐ 2026-10-14 **用户明确授权**（我问过，他选的就是这一项）：
        「**自动投满星开炼（会消耗装备）**」
    ⇒ 所以 `run(auto_start=True)` 是**默认口径** ✓
    ⚠ 但留反开关：`MAPBOT_ALCH_AUTO=0`（或 CLI 不加 `--auto-start` / 加
      `--no-auto-start`）⇒ **只领取、不投料** ✓
      —— 口径是"**默认按用户授权执行，但可一键关掉**"，
        不是"默认关、要用户每次显式打开"（用户已经授权过了 ✓）

用法
----
    # 领取 + 满了就自动投满星开炼（**用户授权口径**）
    python alchemy.py --device 127.0.0.1:16448

    # 只领取（**零消耗**；改主意 / 调试时用）
    python alchemy.py --device 127.0.0.1:16448 --no-auto-start

    # 试跑：一下都不点，只打印"认到啥 / 打算点哪"
    python alchemy.py --device 127.0.0.1:16448 --dry-run

    # 当模块用
    import alchemy
    alchemy.run(bot, log)                    # 默认会自动投料
    alchemy.run(bot, log, auto_start=False)  # 只领
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import guild_common as GC                                  # noqa: E402

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⚠⚠ 2026-10-14 **真机首跑当场抓到的 NameError**（与 `guild_tasks.py` 同一个错）：
#   本文件里有 **27 处** `say(...)`，却**从没定义过** ⇒ 一跑就崩 ✗
#   ⇒ 显式取别名（不用 `import *`，免得 40 多个名字静默盖掉重名 ✓）
say = GC.say


# ══════════════════════════════════════════════════════════════════════
# ① 面板/浮层判定
# ══════════════════════════════════════════════════════════════════════
def result_panel_open(items):
    """「炼金结果」面板开着吗（标题**整条相等**）"""
    return GC.has(items, GC.ALCH_RESULT_TITLE, exact=True)


def main_panel_open(items):
    """「炼金宝箱」主面板开着吗"""
    return GC.has(items, '炼金宝箱', exact=True)


def alch_timer(items):
    """箱子上那层倒计时（炼金进行中）⇒ 文字或 None

    实测两种位置：
      · 滚到顶楼看全景时：箱子气泡处 (240,338)
      · 点沙漏前后：仍是那一条
    ⇒ 判据 = **y≈310~370 之间的 `hh:mm:ss`** ✓
    """
    for it in (items or []):
        if not (305 < it.get('cy', 0) < 375):
            continue
        t = str(it.get('text') or '').replace(' ', '').replace('：', ':')
        m = GC.re.search(r'(\d{1,2}:\d{2}:\d{2})', t)
        if m:
            return m.group(1)
    return None


def expect_time(items):
    """主面板的「预计时间：HH:MM:SS」⇒ 文字（`--:--:--` 归一成 `--:--:--`）；读不到 None

    ⛔⛔ 2026-10-14 **实测踩到的真 bug**（离线回归当场抓出）：
      OCR 把「预计时间：」和它后面的**值**切成**两条** ✗
        · 投料后：`'预计时间：'`(151,477) + **`'07:59:30'` 是另一条**
        · 空槽时：`'预计时间：'`(151,477) + `'.'`(247,478, **conf 只有 0.52**)
          ← `--:--:--` 被 OCR 读成了**一个点** ✗✗
      ⇒ 我第一版只在这**一条**里 findall 时间 ⇒ **两条都读不到**
        （投料后那条 lucky 地粘在一起才过；空槽必然返回 None ✗）
      ⇒ 修法：**在标签右侧找邻居条目**（同一行、x 更大、距离近），把它拼上来 ✓
      ⚠ 拼不上也不算失败 —— 但"读不到"和"空槽"是**两件事**，必须能分开：
        这里返回 `'--:--:--'`（明确的"空"）或 None（"真读不到"）✓
    """
    lab = GC.find(items, '预计时间')
    if not lab:
        return None
    # ① 先看标签自己那条里有没有
    m = GC.re.search(r'(\d{1,2}\s*[:：]\s*\d{2}\s*[:：]\s*\d{2})', lab['text'])
    if m:
        return GC.re.sub(r'\s+', '', m.group(1)).replace('：', ':')
    if GC.re.search(r'-{2,}', lab['text']):
        return '--:--:--'
    # ② 再找**同一行右侧**的邻居（值被 OCR 切出去了）
    lx = lab.get('x1', lab.get('cx', 0))
    ly = lab.get('cy', 0)
    best = None
    for it in (items or []):
        if it is lab:
            continue
        if abs(it.get('cy', 0) - ly) > 22:          # 不同行 ⇒ 不是它
            continue
        if it.get('x0', 0) < lx - 6:                # 在标签左边 ⇒ 不是它
            continue
        if best is None or it.get('x0', 0) < best.get('x0', 0):
            best = it
    if best is None:
        return None
    bt = str(best.get('text') or '').strip()
    m2 = GC.re.search(r'(\d{1,2}\s*[:：]\s*\d{2}\s*[:：]\s*\d{2})', bt)
    if m2:
        return GC.re.sub(r'\s+', '', m2.group(1)).replace('：', ':')
    # 空槽：OCR 把 `--:--:--` 读成 `.` / `-` / `…` 这类**短且非数字**的东西
    #   ⚠ 判据刻意收窄：**必须是 1~3 个字符且不含数字**，否则宁可说"读不到" ✓
    if bt and len(bt) <= 3 and not GC.re.search(r'\d', bt):
        return '--:--:--'
    return None


def slots_filled(items):
    """6 个投料槽填了几个（靠「预计时间」推：`--:--:--` = 0 个）

    ⚠ 不数图标 —— 投料槽里的装备图标要靠模板匹配，代价大且易错。
      而「预计时间」是**免费**的（反正要读），且与投入能量**一一对应** ✓
    """
    t = expect_time(items)
    if t is None:
        return None
    return 0 if t.startswith('--') else 1


# ══════════════════════════════════════════════════════════════════════
# ② 领取「炼金结果」
# ══════════════════════════════════════════════════════════════════════
def claim_result(b, log, items=None, tag='alch'):
    """在「炼金结果」面板上领走奖励 ⇒ True/False

    ⚠ **只点「返回」**：结果面板上只有这一个按钮，**没有任何花费** ✓
      （金币在**弹面板那一刻就入账了**，实测 6112859 → 6208859 ✓）
    ⚠ 找不到「返回」⇒ **不盲点**（本项目在 `relic_flow` 上栽过：
      一次性判据 + 万能位兜底 ⇒ 关不掉还把面板层级搞乱 ✗）
    """
    items = items if items is not None else GC.ocr_items(b, tag='%s_res' % tag)
    if not result_panel_open(items):
        return False
    # 有动画 ⇒ 轮询找「返回」（每轮重新取帧 ✓）
    for k in range(4):
        it = GC.find(items, '返回')
        if it:
            b.tap(it['cx'], it['cy'], wait=2.0)
            GC._log(log, {'alch': 'claim_back', 'at': (it['cx'], it['cy']),
                          'try': k + 1})
            say('       · 炼金结果 ⇒ 点「返回」(%d,%d) 领走 ✓'
                % (it['cx'], it['cy']))
            return True
        time.sleep(0.8)
        items = GC.ocr_items(b, tag='%s_res%d' % (tag, k))
    GC._log(log, {'alch': 'claim_back_miss'})
    say('       · ⚠ 4 轮没找到「返回」⇒ **不盲点**（如实记录）')
    return False


def read_result(items):
    """从结果面板抠出（金币数, 道具条数）—— 只做日志，不参与决策"""
    gold = None
    for it in (items or []):
        t = str(it.get('text') or '').replace(',', '')
        if 520 < it.get('cy', 0) < 600 and GC.re.fullmatch(r'\d{3,}', t):
            try:
                gold = int(t)
            except ValueError:
                pass
    n_item = sum(1 for it in (items or [])
                 if 610 < it.get('cy', 0) < 900 and it.get('text'))
    return gold, n_item


# ══════════════════════════════════════════════════════════════════════
# ③ 投料开炼（满星 → 开始炼金）
# ══════════════════════════════════════════════════════════════════════
def start_alchemy(b, log, tag='alch'):
    """在主面板上「**点满星 → 点开始炼金**」⇒ 'started'|'nothing'|'failed'

    ⚠⚠ **消耗类**：会吃掉投入的满星装备 ⇒ 只有调用方显式允许才会走到这里 ✓
    """
    items = GC.ocr_items(b, tag='%s_main' % tag)
    if not main_panel_open(items):
        GC._log(log, {'alch': 'main_panel_miss'})
        return 'failed'

    t0 = expect_time(items)
    GC._log(log, {'alch': 'main', 'expect': t0})
    if t0 and not t0.startswith('--'):
        # 已经有料了（可能是上次没清掉）⇒ 不再重复投
        say('       · 主面板已有投料（预计时间 %s）⇒ 不重复投，直接开炼' % t0)
    else:
        # ① 点「满星」⇒ 自动填满 6 格
        b.tap(*GC.ALCH_FILTER_FULLSTAR, wait=2.5)
        items = GC.ocr_items(b, tag='%s_star' % tag)
        t1 = expect_time(items)
        GC._log(log, {'alch': 'tap_fullstar', 'at': GC.ALCH_FILTER_FULLSTAR,
                      'expect_after': t1})
        say('       · 点「满星」⇒ 预计时间 %s' % (t1 or '?'))
        if not t1 or t1.startswith('--'):
            say('       · ⚠ 点了满星但**投料槽还是空的** ⇒ 不点开始炼金'
                '（避免空烧）')
            GC._log(log, {'alch': 'no_fill', 'note': '满星后预计时间仍为空'})
            return 'nothing'

    # ② 点「开始炼金」⇒ 提交
    b.tap(*GC.ALCH_START_BTN, wait=3.0)
    items2 = GC.ocr_items(b, tag='%s_start' % tag)
    tm = alch_timer(items2)
    GC._log(log, {'alch': 'tap_start', 'at': GC.ALCH_START_BTN, 'timer': tm,
                  'panel_still': main_panel_open(items2)})
    if tm:
        say('       · ⭐ 炼金已开始 ⇒ 倒计时 %s ✓' % tm)
        return 'started'
    if main_panel_open(items2):
        # 面板还在 ⇒ 可能是"确认/提示"挡住了
        say('       · ⚠ 点了开始炼金但面板还在（可能弹了确认框）⇒ 再看一轮')
        it = GC.find(items2, '确定', '确认')
        if it:
            b.tap(it['cx'], it['cy'], wait=2.5)
            items3 = GC.ocr_items(b, tag='%s_start2' % tag)
            tm2 = alch_timer(items3)
            GC._log(log, {'alch': 'confirm_ok', 'timer': tm2})
            if tm2:
                say('       · ⭐ 确认后炼金已开始 ⇒ 倒计时 %s ✓' % tm2)
                return 'started'
        GC.close_panel(b, GC.ALCH_PANEL_X, 'alch_x_start',
                       probe_texts=('炼金宝箱',), log=log)
        return 'failed'
    say('       · 面板已关但**没读到倒计时** ⇒ 下一轮再看（不假装成功）')
    return 'failed'


# ══════════════════════════════════════════════════════════════════════
# ④ 主流程
# ══════════════════════════════════════════════════════════════════════
def run(b, log=None, auto_start=False, leave=False, accel=False):
    """炼金主流程 ⇒ 汇总 dict

    流程：进公会 → 滚到顶楼 → 点普通宝箱 → 按面板类型分流：
        结果面板 ⇒ **领奖** ✓（总是做，零消耗）
        主面板   ⇒ 有倒计时 ⇒ 进行中（不动）；空闲 ⇒ `auto_start` 时才投料开炼
    `auto_start=False` 时**绝不消耗任何道具** ✓
    """
    log = log if log is not None else []
    res = {'ok': False, 'claimed': False, 'started': False, 'state': None}
    say('')
    say('=' * 62)
    say('⚗️  炼金%s' % ('（**会自动投料开炼**）' if auto_start else '（只领取，不消耗）'))
    say('=' * 62)

    if not GC.goto_guild(b, log):
        say('   ✗ 进不了公会展厅 ⇒ 放弃')
        res['why'] = 'not_in_guild'
        return res

    # ── 滚到顶楼（4 楼 = 炼金那层）──
    #   ⭐ 先固定滚 N 次（到顶后再滚无害），再用**候选点组**去点宝箱
    #     —— 宝箱的 y 会随滚动深度漂 ~35px，见 `ALCHEMY_CHEST_YS` 的说明 ✓
    GC.scroll_to_top(b, log)

    # ── 点宝箱（正式进入流程）：**试一组候选点**，试到开出面板为止 ──
    #   ⚠⚠ 2026-10-14 真机教训：**必须验证"点出面板了没"**，否则会
    #     "对着空处点完就往下走" ⇒ **静默失效**（本项目第 N 次同族 bug ✗）
    _opened = None
    _hit_at = None
    for _x in GC.ALCHEMY_CHEST_XS:
        for _y in GC.ALCHEMY_CHEST_YS:
            b.tap(_x, _y, wait=3.0)
            items = GC.ocr_items(b, tag='alch_open')
            _opened = _which_panel(items)
            GC._log(log, {'alch': 'open', 'at': (_x, _y), 'panel': _opened,
                          'texts': GC._texts(items)[:12]})
            if (result_panel_open(items) or main_panel_open(items)
                    or GC.has(items, '献祭宝箱怪', '当前正在炼金中')):
                _hit_at = (_x, _y)
                say('   · 点 (%d,%d) ⇒ %s ✓' % (_x, _y, _opened))
                break
            say('   · 点 (%d,%d) ⇒ %s（继续试下一个候选点）' % (_x, _y, _opened))
        if _hit_at:
            break
    GC._log(log, {'alch': 'open_final', 'panel': _opened, 'hit': _hit_at})
    # ⛔⛔ 2026-10-15 **真机抓到的 bug**：第 320 行把「当前正在炼金中」算**命中**
    #   （= 找到宝箱了 ✓），可**这里**只认 `result/main_panel` ⇒ 判成"没开出面板" ⇒
    #   **直接 return 放弃** ✗ ⇒ 后面那段"加速炼金"**根本没机会跑** ✗✗
    #   ---- 真机铁证 ----
    #     炼金进行中（倒计时 05:06:48）时点宝箱 ⇒ 弹「**当前正在炼金中**」提示，
    #     日志：`open_final hit=(240,445)` 但**接着就报失败**、"候选点都试过"✗
    #   ---- 这条正是本项目反复记的那类错 ----
    #     「**两处判据不一致**：找到的时候认它，后续判断却不认」 ✗
    #   ⇒ 修法：**两处用同一套判据**（把「当前正在炼金中」也算"开了"）✓
    #     ⚠ 它**不是**面板，但它明确表示"炼金在进行中" ——
    #       这正是本函数要处理的状态（`running` 那一支）✓
    _is_running_tip = GC.has(items, '当前正在炼金中')
    if not (result_panel_open(items) or main_panel_open(items)
            or _is_running_tip):
        say('   ✗ 候选点都试过了，没开出炼金面板 ⇒ **如实报失败**（不假装成功）')
        res['why'] = 'panel_not_opened'
        res['state'] = _opened
        return res

    # ⭐ 「当前正在炼金中」提示 ⇒ **等价于 running**（炼金在跑，只是面板没弹出）
    #   ⇒ 直接走下面的"进行中"那一支（含免广加速 ✓）
    if _is_running_tip and not (result_panel_open(items)
                               or main_panel_open(items)):
        say('   · 点宝箱回到「**当前正在炼金中**」提示'
            '（= 炼金在跑、面板没弹）⇒ 按"进行中"处理 ✓')
        GC._log(log, {'alch': 'running_tip', 'at': _hit_at})
        # ⛔⛔ 2026-10-15 **真机又抓到一个**（我第一版修错了）：
        #   我原来写"点 `(360,640)` 关掉这个提示" ⇒ **错得离谱** ✗
        #     那个坐标落在 3 楼的「**情报专家**」按钮上 ⇒
        #     一点就打开了**兑换商店面板** ⇒ 画面整个跑偏，
        #     后面找沙漏当然找不到（`popup: False`）✗
        #   ---- 正解：不用"点掉提示"，而是**滚回炼金楼层** ----
        #     ① 那个提示**会自己消失**（游戏内的 toast 类提示 ✓）
        #     ② 沙漏只在**炼金楼层**才有 ⇒ 滚到顶就是它 ✓
        #     ③ 楼层滚动**是安全的**（不会误点任何按钮 ✓）
        #        —— 而"点空白处"永远有落在某个按钮上的风险 ✗
        time.sleep(1.2)                 # 等提示自己消失
        GC.scroll_to_top(b, log)        # 滚回顶楼（= 炼金那层，沙漏在那儿 ✓）
        items = GC.ocr_items(b, tag='alch_tip_closed')
        GC._log(log, {'alch': 'tip_scrolled',
                      'timer': (alch_timer(items) or expect_time(items)),
                      'still_tip': GC.has(items, '当前正在炼金中')})

    # ① 结果面板 ⇒ 领奖
    if result_panel_open(items):
        gold, n_item = read_result(items)
        say('   · 炼金结果：金币 %s ｜ 道具约 %d 条' % (gold, n_item))
        if claim_result(b, log, items):
            res['claimed'] = True
            res['state'] = 'claimed'
            # 领完 ⇒ **再点一次箱子**看能不能接着开一炉（这一步**不消耗**，
            #   只是开面板；要不要投料由 auto_start 决定 ✓）
            time.sleep(1.2)
            b.tap(*GC.ALCHEMY_CHEST, wait=3.0)
            items = GC.ocr_items(b, tag='alch_reopen')
            GC._log(log, {'alch': 'reopen', 'panel': _which_panel(items)})
            say('   · 领完再点箱子 ⇒ %s' % _which_panel(items))

    # ② 主面板 ⇒ 看是"进行中"还是"空闲"
    #   ⭐ 2026-10-15：**「当前正在炼金中」提示也算 running**（见上面那段推导 ✓）
    #     —— 那时候**面板没开**，但炼金确实在跑、沙漏就在楼层上 ✓
    if main_panel_open(items) or _is_running_tip:
        tm = alch_timer(items) or expect_time(items)
        running = bool(alch_timer(items)) or _is_running_tip
        res['state'] = 'running' if running else 'idle'
        if running:
            say('   · 炼金**进行中**（%s）' % (tm or '提示「当前正在炼金中」'))
            # ⭐⭐⭐ 2026-10-15 **用户口径**（原话，两次）：
            #   ① 「**勾选免广的话，做公会日常的时候，八小时炼金可以直接用一次免广立即领取**」
            #   ② 「**记得加上限制，勾了免广才进行二次炼金**」
            #      ＋补问澄清：「**不开新炉，只是加速领取**」✓
            #   ---- 所以这里的语义是（**别做过头** ✗）----
            #     · `accel=True`（勾了免广）⇒ 用免广**加速 → 立刻领走**
            #     · **不开新炉**（用户明确说了"不开新炉"✓）
            #       ⚠ 但**下一轮调用**会走到下面那个 `else`（空闲）分支 ⇒
            #         若 `auto_start=True` 就会**又开一炉** ✗
            #         ⇒ 用 `res['accelerated']` 记住"这轮刚加速过" ⇒
            #           让**下面那段**别在同一轮里接着开新炉 ✓（见 `_just_accelerated`）
            _acc_done = False
            if accel:
                try:
                    import ads as _ad
                    _acc_done = bool(_ad.alchemy_accel(b, log, tag='alch'))
                    res['accelerated'] = _acc_done
                    say('   · 加速炼金：%s' % ('✓ 已用免广立即完成'
                                            if _acc_done else '没做（次数用完/无免广）'))
                except Exception as _e_ac:          # noqa: BLE001
                    import traceback as _tb_ac
                    log.append({'alch': 'accel_error', 'e': repr(_e_ac)[:160],
                                'trace': _tb_ac.format_exc().splitlines()[-4:]})
                    say('   ⚠ 加速炼金出错：%r' % (_e_ac,))
                if _acc_done:
                    # ⭐ 加速成功 ⇒ 炼金**已经完成** ⇒ 立刻再点箱子领结果 ✓
                    #   （用户口径要的就是"立即领取"，别等下一轮 ✗）
                    time.sleep(1.5)
                    b.tap(*GC.ALCHEMY_CHEST, wait=3.0)
                    it_r = GC.ocr_items(b, tag='alch_acc_res')
                    GC._log(log, {'alch': 'accel_reopen',
                                  'panel': _which_panel(it_r)})
                    say('   · 加速后再点箱子 ⇒ %s' % _which_panel(it_r))
                    if result_panel_open(it_r):
                        _g, _n = read_result(it_r)
                        say('   · 炼金结果：金币 %s ｜ 道具约 %d 条' % (_g, _n))
                        if claim_result(b, log, it_r):
                            res['claimed'] = True
                            res['state'] = 'claimed_after_accel'
                            say('   · ✓ 已**立即领走**（免广加速 → 领奖 一条链 ✓）')
                    # ⛔⛔⭐⭐ 2026-10-15 **用户口径**（原话）：
                    #   ① 「勾选免广的话，做公会日常的时候，八小时炼金可以直接用一次免广立即领取」
                    #   ② 「**记得加上限制，勾了免广才进行二次炼金**」
                    #      ＋补问澄清：「**不开新炉，只是加速领取**」✓
                    #   ---- 所以这里**就地收工**，不许接着开新炉 ✗ ----
                    #     ⚠⚠ 我第一版把限制写在**下面那个 `else`（空闲）分支**里 ⇒
                    #       **死代码** ✗ 因为 `accelerated` 只在本分支设，
                    #       而能走到 `else` 就说明 `running=False`
                    #       ⇒ `res.get('accelerated')` **恒为 None** ✗✗
                    #       （我事后用 AST 查了一遍 `if running` 的 orelse 才发现的 ✓）
                    #     ⇒ 正解：**在这里直接收尾**（`return`），
                    #       根本不让控制流回到"空闲 ⇒ 开新炉"那段 ✓
                    say('   · ⛔ 本轮**刚用免广加速领取过** ⇒ **不再开新炉**'
                        '（用户口径「不开新炉，只是加速领取」✓）')
                    GC._log(log, {'alch': 'skip_new_batch_after_accel'})
                    res['ok'] = True
                    if leave:
                        GC.leave_guild(b, log)
                    say('=' * 62)
                    return res
            if not _acc_done:
                # 没加速（无免广 / 次数用完 / 没勾）⇒ 老行为：不动它 ✓
                say('   · 不动它 ✓')
                # ⚠ 只有**面板真的开着**才需要关（"当前正在炼金中"那种提示不用关 ✓）
                if main_panel_open(items):
                    GC.close_panel(b, GC.ALCH_PANEL_X, 'alch_x_run',
                                   probe_texts=('炼金宝箱',), log=log)
        else:
            if not auto_start:
                say('   · 炼金**空闲**（预计时间 %s）⇒ 只领取模式，**不投料** ✓'
                    % (expect_time(items) or '?'))
                GC.close_panel(b, GC.ALCH_PANEL_X, 'alch_x_idle',
                               probe_texts=('炼金宝箱',), log=log)
            else:
                say('   · 炼金空闲 ⇒ 自动投料开炼（满星 → 开始炼金）')
                r = start_alchemy(b, log)
                res['started'] = (r == 'started')
                res['state'] = r
                if r != 'started':
                    GC.close_panel(b, GC.ALCH_PANEL_X, 'alch_x_fail',
                                   probe_texts=('炼金宝箱',), log=log)

    res['ok'] = bool(res['claimed'] or res['started']
                     or res['state'] in ('running', 'idle'))
    GC._log(log, {'alch': 'done', **{k: res[k] for k in ('claimed', 'started',
                                                         'state', 'ok')}})
    if leave:
        GC.leave_guild(b, log)
    say('=' * 62)
    return res


def _which_panel(items):
    if result_panel_open(items):
        return '「炼金结果」（**已完成待领**）'
    if main_panel_open(items):
        if alch_timer(items):
            return '「炼金宝箱」+ 倒计时（**进行中**）'
        return '「炼金宝箱」（**空闲可投料**）'
    if GC.has(items, '献祭宝箱怪'):
        return '⚠ 「献祭宝箱怪」——**点错格子了**（那是天赋互换，不是炼金）'
    if GC.has(items, '当前正在炼金中'):
        return '「当前正在炼金中」提示'
    return '**没开出任何面板**（认到 %s）' % (GC._texts(items)[:8],)


def _alch_shots(log, items):
    """把这次的关键文字记进日志（排查"点错格子"用）"""
    GC._log(log, {'alch': 'texts', 't': GC._texts(items)[:16]})


# ══════════════════════════════════════════════════════════════════════
# ⑤ CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:                                       # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='炼金（公会 4 楼顶楼左边普通宝箱）')
    ap.add_argument('--device', default=None, help='adb 设备号，如 127.0.0.1:16448')
    ap.add_argument('--tag', default='alchemy', help='实例名')
    ap.add_argument('--no-auto-start', dest='auto_start',
                    action='store_false', default=None,
                    help='只领取、**不投料**（默认是自动投满星开炼 ✓ 用户授权口径）')
    ap.add_argument('--auto-start', dest='auto_start', action='store_true',
                    help='（默认就是它）自动投满星开炼 ⚠ 会消耗 5★ 满星装备')
    ap.add_argument('--accel', action='store_true',
                    help='进行中时打开加速弹窗**看一眼**（不点任何加速按钮）')
    ap.add_argument('--leave', action='store_true', help='做完离开公会')
    ap.add_argument('--dry-run', action='store_true',
                    help='⭐ 试跑：**一下都不点**，只打印"认到啥 / 打算点哪"')
    a = ap.parse_args()

    dev = a.device or os.environ.get('MAPBOT_DEVICE') or GC.DEV
    n = os.environ.get('MAPBOT_ALCH_AUTO')
    _env_auto = (str(n).strip() != '0') if n is not None else None
    # 优先级：CLI 给了就用 CLI；没给就看环境变量；都没有 ⇒ **默认开**（用户授权 ✓）
    auto = a.auto_start if a.auto_start is not None else (
        _env_auto if _env_auto is not None else True)
    GC.DRY_RUN = bool(a.dry_run)
    say('设备：%s ｜ 实例：%s ｜ 自动开炼：%s%s'
        % (dev, a.tag, '**开**（会消耗 6 件 5★ 满星装备）' if auto else '关（只领取）',
           ' ｜ ⚠ **试跑模式：不会点任何东西**' if GC.DRY_RUN else ''))
    b = GC.wrap_dry(GC.Bot(log_prefix='alchemy', serial=dev, tag=a.tag), None)
    log = []
    try:
        res = run(b, log, auto_start=auto, leave=a.leave, accel=a.accel)
    finally:
        for e in log:
            print(e)
    say('')
    say('结果：领取=%s ｜ 开炼=%s ｜ 状态=%s'
        % (res.get('claimed'), res.get('started'), res.get('state')))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
