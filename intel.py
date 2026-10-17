# -*- coding: utf-8 -*-
"""公会「情报」领奖 —— 每日情报 + 每周情报（2026-10-15）

用户口径（原话）：
    ① 「**接下来做点击情报领取奖励**」
    ② 「**每周情报也顺便点了**」
    ③ 「**每周情报可以直接盲点一下最上面的可领取的坐标**
        然后就可以关闭页面了」

════════════════════════════════════════════════════════════════════
一、面板是什么（真机逐帧实测，综合模拟器 2026-10-15）
════════════════════════════════════════════════════════════════════
入口：**公会展厅 → 右上角「情报」按钮 (660,258)**
      （`Main_Union_Intelligence_Button` = 情报；带红点 = 有奖励没领 ✓）
面板：「**情报指南**」（战斗通行证式），结构：
    · 顶部：等级 + 经验条（实测领奖时 **47→48→49 连升**）
    · 中部：**两个页签** —— 「每日情报 N/8」｜「每周情报 N/7」
    · 列表：每行 = 奖励点数 + 任务名 + **右侧状态按钮**
    · 底部：「情报任务」｜「等级奖励」两个 tab + 「每日情报将在05:00重置」

### 右侧状态按钮有**三种**（判据的关键）
    | 文字 | 含义 | 能不能点 |
    |---|---|---|
    | `可领取` | 绿底，**能领** | ✅ 点它 |
    | `已完成` | 灰底，**已领过** | ❌ 别碰 |
    | `N/M`    | 进度（如 `4/5` / `34/40` / `0/1`） | ❌ 别碰 |
    ⚠ **三态的 x 都是 547~549**（实测 6 行：548/549/548/548/547/548）
      ⇒ **判据 = 「可领取」这三个字**，不用猜位置 ✓
    ⚠ 行的 y 有**规律**：558 / 655 / 752 / 847 / 942 / 1039（步长≈96）
      —— 但**别用步长算**（列表会滚动、行数会变）⇒ **一律 OCR 现读** ✓

### 领一条的完整动作（实测）
    ① 点「可领取」`(548, y)` ⇒ 弹「恭喜获得」（货币 + 道具）
    ② **必须点弹窗的「返回」`(359,883)`** 才能继续领下一条 ✗
       （不点 ⇒ 弹窗挡住列表，下一条点不到）
    ③ 该行按钮文字变 `已完成` ⇒ 可以接着领下一条
    ⚠ 弹窗出现/消失有过渡帧 ⇒ **每一步都轮询 + 重新取帧**（别一次判死 ✗）

════════════════════════════════════════════════════════════════════
二、用户口径怎么落成实现（**两条页签策略不同**，这是他明确说的）
════════════════════════════════════════════════════════════════════
· **每日情报** ⇒ **OCR 循环**：反复找「可领取」并点，直到一条都找不到 ✓
    （每日有 8 条、数量会变 ⇒ 必须循环到空）
· **每周情报** ⇒ **盲点最上面那个可领取的坐标一次**，然后**关页面** ✓
    —— 用户原话「**可以直接盲点一下最上面的可领取的坐标，然后就可以关闭页面了**」
    ⚠ 这是**用户的明确指示**，不是我偷懒：每周任务少（7 条）、
      且多数时候**只有最上面那条可领** ⇒ 盲点一次最省事 ✓
    ⚠ 但**盲点前仍要 OCR 确认那一行确实写着「可领取」**（防瞎点 ✗）——
      用户说的是"盲点**坐标**"（不逐行找），不是"不确认状态" ✓
    ⚠ 盲点位置 = **第 1 行的按钮位 `(548, WEEKLY_FIRST_Y=559)`** ✓

════════════════════════════════════════════════════════════════════
三、安全边界（**只领奖，不改任何设置**）
════════════════════════════════════════════════════════════════════
· **不点**「购买情报指南」（那要花宝石 ✗）
· **不点**「等级奖励」tab（本轮没做，先不碰 ✓）
· **不点**「已完成」/「N/M」的行 ✓
· 领不到就**如实上报**，不硬凑 ✓
"""
import argparse
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import guild_common as GC                                     # noqa: E402

say = GC.say

# ══════════════════════════════════════════════════════════════════════
# ① 坐标（**全是真机实测的 720×1280 裸坐标** —— 别乘 LAYOUT.k ✗）
# ══════════════════════════════════════════════════════════════════════
# 入口：公会展厅右上角「情报」（图标 y≈240 / 文字 y≈277 ⇒ 取中间偏上）
INTEL_BTN = (660, 258)
# 面板右上角**关闭 X**（实测量得 645,228）
INTEL_CLOSE_X = (645, 228)
# 两个页签（实测：「每日情报」center≈(279,439)、「每周情报」center≈(441,439)）
INTEL_TAB_DAILY = (279, 439)
INTEL_TAB_WEEKLY = (441, 439)
# 右侧状态按钮的 **x**（实测 547~549，取 548）
INTEL_BTN_X = 548
# 列表**第 1 行**的状态按钮 y（实测 558~561 ⇒ 取 559）
#   ⭐ **每周盲点就是点这个位置**（用户口径）✓
INTEL_FIRST_Y = 559
# 列表行的 y（实测，**仅用于日志展示** —— 判据一律 OCR 现读 ✗ 别用步长算）
INTEL_ROW_YS = (559, 655, 752, 847, 942, 1039)
# 领奖弹窗的「返回」（实测 (359,883)）
INTEL_POPUP_BACK = (359, 883)
# 面板标题（用于确认"面板开着"）
INTEL_TITLE = '情报指南'
# 「可领取」= 唯一可点的状态文字（三态里的那一态 ✓）
INTEL_CLAIMABLE = '可领取'
# 另两态（**明确列出来**，免得日后有人把"N/M"也当可点 ✗）
INTEL_DONE = '已完成'


def panel_open(items):
    """这一帧是不是**情报指南面板**（`情报指南` 标题 或 两个页签之一 ✓）

    ⚠ 用**面板专属**文案判：`情报指南` / `每日情报` / `每周情报`
      —— 公会展厅那一屏**也有**「情报」二字（那颗按钮）
      ⇒ **单看「情报」会把自己骗了** ✗（正是本项目反复踩的那类坑）
    """
    return GC.has(items, INTEL_TITLE, '每日情报', '每周情报')


def _claimable(items):
    """当前帧里所有「可领取」的条目（**按 y 从小到大** ⇒ 从上往下领 ✓）"""
    out = []
    for it in (items or []):
        if str(it.get('text') or '').strip() == INTEL_CLAIMABLE:
            out.append(it)
    out.sort(key=lambda d: d.get('cy', 0))
    return out


def open_panel(b, log=None, tag='intel'):
    """打开「情报指南」面板 ⇒ True/False

    ⭐ 路径（用户教的同款思路：**入口在公会右上角**）：
       公会展厅 → 点右上角「情报」`(660,258)` ⇒ 面板 ✓
    ⚠ 已在面板上（或用户手动开着）⇒ **直接返回 True**（不重点 ✗）
    ⚠ 不在公会 ⇒ 先 `GC.goto_guild`（那条路是对的 ✓）
    """
    items = GC.ocr_items(b, tag='%s_p0' % tag)
    if panel_open(items):
        say('   · 情报面板**已经开着** ⇒ 直接用 ✓')
        GC._log(log, {'intel': 'panel_already_open'})
        return True

    if not GC.in_guild(items):
        if not GC.goto_guild(b, log):
            say('   ✗ 进不了公会 ⇒ 走不到「情报」（它在公会右上角）')
            return False
        items = GC.ocr_items(b, tag='%s_p1' % tag)
        if panel_open(items):
            return True

    # 点右上角「情报」：**优先 OCR 现读**，读不到才用标定坐标 ✓
    it = None
    for _i in (items or []):
        if str(_i.get('text') or '').strip() == '情报':
            it = _i
            break
    at = (int(it['cx']), int(it['cy'])) if it else INTEL_BTN
    b.tap(at[0], at[1], wait=2.6)
    items2 = GC.ocr_items(b, tag='%s_p2' % tag)
    _ok = panel_open(items2)
    GC._log(log, {'intel': 'tap_btn', 'at': at,
                  'by': 'ocr' if it else 'calib', 'open': _ok})
    say('   · 点右上角「情报」(%d,%d)%s ⇒ %s'
        % (at[0], at[1], '（OCR 现读）' if it else '（标定坐标）',
           '面板已开 ✓' if _ok else '没开 ✗'))
    return _ok


def switch_tab(b, which, log=None, tag='intel'):
    """切到**每日/每周**页签 ⇒ True/False

    ⚠ 切完**必须验**：怎么验？—— 页签自身没有"选中态"的文字差异，
      所以判据 = **列表第一行的任务名变了**或**页签仍读得到** ✓
      ⇒ 这里用**宽松判据**：切完仍在面板上 + 再读一次能读到「可领取 或 进度」✓
      （**不硬要求**读到某个特定任务名 —— 每周/每日的任务名会随版本变 ✗）
    """
    at = INTEL_TAB_WEEKLY if str(which).startswith('w') else INTEL_TAB_DAILY
    name = '每周情报' if str(which).startswith('w') else '每日情报'
    # 优先 OCR 现读那个页签文字
    items = GC.ocr_items(b, tag='%s_t0' % tag)
    it = GC.find(items, name)
    if it:
        at = (int(it['cx']), int(it['cy']))
    b.tap(at[0], at[1], wait=1.8)
    items2 = GC.ocr_items(b, tag='%s_t1' % tag)
    ok = panel_open(items2)
    GC._log(log, {'intel': 'switch_tab', 'to': name, 'at': at, 'ok': ok})
    say('   · 切到「%s」(%d,%d) ⇒ %s' % (name, at[0], at[1],
                                        '✓' if ok else '⚠ 面板不见了'))
    return ok


def _dismiss_reward(b, log=None, tag='intel'):
    """关掉领奖弹窗（点「**返回**」）⇒ True/False

    ⚠ 弹窗会**挡住列表** ⇒ 不点掉就领不到下一条 ✗（实测）
    ⚠ 真机弹窗按钮文案 = 「**返回**」（实测 (359,883)）✓
    ⚠ 但**有的账号/版本**可能给「确定」/「点击继续」⇒ **多文案轮询** ✓
    ⚠ 一律**每轮重新取帧**再找（弹窗有出现/消失动画 ✗）

    ⛔⛔⛔ 2026-10-15 **真机抓到我一个"提前返回"的 bug**（用户报：「情报领取怎么
        卡在恭喜获得了」）—— 卡死现场：弹窗开着、`返回` 就在 (359,883)，
        但日志里**一条 `dismiss_reward` 都没有** ⇒ 说明它**一次都没点** ✗
      ---- 病根：我那条"已经不在弹窗上"的判据用错了东西 ----
        旧代码：
            `if _claimable(items) or GC.has(items, INTEL_DONE): return True`
        我以为"能在列表里读到 `已完成`" ⇒ 弹窗已经关了 ✓
      ---- 可 `已完成` 在**弹窗底下照样读得到** ✗✗ ----
        那个「恭喜获得」弹窗是**半透明遮罩**，列表文字**透出来还在** ✓
        （真机抓帧为证：同一帧里**既有**「恭喜获得」，**也有** `已完成`）
        ⇒ 这条判据**恒为真** ⇒ 第一次轮询就 return ⇒ **永远不点返回** ✗
        ⇒ 症状正是用户看到的：**卡在「恭喜获得」** ✓
      ---- 修法：用**弹窗自己**的特征判（不是"别的东西还在不在"）----
        · 弹窗在 ⇒ 有「**恭喜获得**」（这是它独有的标题 ✓）
        · 弹窗没了 ⇒ **没有**「恭喜获得」
        ⇒ 判据：`not GC.has(items, '恭喜获得', '获得')` ⇒ 才算关掉了 ✓
      ⚠ 与本项目那条老教训**同一个形状**：**判据要盯着目标物本身，
        不要用"旁边的东西还在不在"来间接推断** —— 旁证会被挡住/透出来 ✗
    """
    for k in range(6):
        items = GC.ocr_items(b, tag='%s_rw%d' % (tag, k))
        it = GC.find(items, '返回', '确定', '点击继续', '确认')
        if it:
            b.tap(it['cx'], it['cy'], wait=1.7)
            GC._log(log, {'intel': 'dismiss_reward', 'text': it['text'],
                          'at': (it['cx'], it['cy']), 'try': k + 1})
            say('       · 弹窗 ⇒ 点「%s」(%d,%d) ✓'
                % (it['text'], it['cx'], it['cy']))
            return True
        # ⭐ 判"弹窗已经没了" ⇒ **只看弹窗自己的标题**（见上面那段推导）✓
        #   ⛔ **别**用 `_claimable` / `INTEL_DONE` —— 它们在半透明弹窗下**照样读得到** ✗
        if not GC.has(items, '恭喜获得', '获得'):
            return True
        time.sleep(0.5)
    # 轮询没找到 ⇒ 用标定坐标兜一次（**仍不盲点别的** ✓）
    b.tap(INTEL_POPUP_BACK[0], INTEL_POPUP_BACK[1], wait=1.7)
    GC._log(log, {'intel': 'dismiss_reward', 'at': INTEL_POPUP_BACK,
                  'by': 'fallback'})
    say('       · 没读到弹窗按钮 ⇒ 用标定坐标 (%d,%d)'
        % INTEL_POPUP_BACK)
    return True


def claim_daily(b, log=None, tag='intel', max_rounds=12):
    """**每日情报**：反复找「可领取」并点，直到一条都没有 ⇒ 领到的条数

    ⚠ 为什么要循环：每日有 **8 条**、且"哪几条能领"每次都不同 ⇒
      **不能写死条数**，只能"领到没有为止" ✓
    ⚠ `max_rounds` 是**防呆上限**（正常 8 条以内；万一判据出问题不至于死循环 ✗）
    """
    got = 0
    for r in range(max(1, int(max_rounds))):
        items = GC.ocr_items(b, tag='%s_d%d' % (tag, r))
        if not panel_open(items):
            say('   ⚠ 每日情报：面板不见了 ⇒ 停手（领了 %d 条）' % got)
            GC._log(log, {'intel': 'daily_panel_lost', 'got': got})
            break
        rows = _claimable(items)
        if not rows:
            say('   · 每日情报：没有「可领取」了 ⇒ 完成（共领 %d 条）✓' % got)
            break
        it = rows[0]                    # **从上往下**领（y 最小的那条 ✓）
        b.tap(it['cx'], it['cy'], wait=1.9)
        GC._log(log, {'intel': 'claim_daily', 'i': r + 1,
                      'at': (it['cx'], it['cy']), 'left': len(rows)})
        say('   · 每日情报 [%d] ⇒ 点「可领取」(%d,%d)（这帧还剩 %d 条可领）'
            % (got + 1, it['cx'], it['cy'], len(rows)))
        _dismiss_reward(b, log, tag)
        got += 1
    return got


def claim_weekly(b, log=None, tag='intel'):
    """**每周情报**：**盲点最上面那个可领取的坐标一次** ⇒ True/False

    ⭐⭐⭐ 用户口径（原话）：
        「**每周情报可以直接盲点一下最上面的可领取的坐标
          然后就可以关闭页面了**」
    ---- 怎么落 ----
      ① 切到「每周情报」页签 ✓
      ② **OCR 确认第 1 行确实写着「可领取」**（防瞎点 ✗）
         —— 用户说的是"盲点**坐标**"（不逐行找），**不是**"不确认状态" ✓
      ③ 点 **`(548, 559)`**（= 第 1 行状态按钮位）**一次** ✓
      ④ 关掉领奖弹窗 ⇒ 返回（调用方随后关页面 ✓）
    ⚠ **只点一次**（用户口径），不像每日那样循环 ✓
    ⚠ 第 1 行若**不是**「可领取」（是 `N/M` 或 `已完成`）⇒ **不点**、如实上报 ✓
    """
    if not switch_tab(b, 'weekly', log, tag):
        return False
    items = GC.ocr_items(b, tag='%s_w0' % tag)
    # 找**最上面**那个状态条目（y 最小的「可领取」/「已完成」/进度）
    _first = None
    for _i in (items or []):
        _t = str(_i.get('text') or '').strip()
        _cy = _i.get('cy', 0)
        _cx = _i.get('cx', 0)
        if not (500 < _cx < 600 and 400 < _cy < 1120):
            continue
        if _t == INTEL_CLAIMABLE or _t == INTEL_DONE or _is_progress(_t):
            if _first is None or _cy < _first.get('cy', 9999):
                _first = _i
    if _first is None:
        say('   ⚠ 每周情报：读不到第 1 行的状态 ⇒ **不盲点**（不瞎猜 ✗）')
        GC._log(log, {'intel': 'weekly_no_row'})
        return False
    _t = str(_first['text']).strip()
    if _t != INTEL_CLAIMABLE:
        say('   · 每周情报：第 1 行是「%s」（不是「可领取」）⇒ **不点** ✓' % _t)
        GC._log(log, {'intel': 'weekly_first_not_claimable', 'text': _t})
        return False
    # ⭐ **盲点**用户指定的坐标（第 1 行按钮位）—— 不追着 OCR 的坐标点 ✓
    b.tap(INTEL_BTN_X, INTEL_FIRST_Y, wait=1.9)
    GC._log(log, {'intel': 'claim_weekly_blind',
                  'at': (INTEL_BTN_X, INTEL_FIRST_Y),
                  'ocr_saw': (_first['cx'], _first['cy'])})
    say('   · 每周情报 ⇒ **盲点最上面那个可领取** (%d,%d) ✓'
        % (INTEL_BTN_X, INTEL_FIRST_Y))
    _dismiss_reward(b, log, tag)
    return True


def _is_progress(t):
    """`4/5` / `34/40` / `0/1` 这种**进度**文字 ⇒ True（**不可点** ✗）"""
    t = str(t or '').strip()
    if '/' not in t:
        return False
    a, _sep, bb = t.partition('/')
    return a.strip().isdigit() and bb.strip().isdigit()


def close_panel(b, log=None, tag='intel'):
    """关掉情报页面 ⇒ True/False（**用户口径："然后就可以关闭页面了"** ✓）

    ⚠ 优先 **OCR 现读**那种右上角的 X（本项目的通用做法 ✓）；
      招募页实测过 X 中心 ≈ `(671,126)`、情报页实测 ≈ `(645,228)`
      —— **两页不一样** ⇒ 所以这里**用标定的情报页 X** ✓
    ⚠ 关完**验一下**（回到公会展厅 ⇒ 不再是情报面板 ✓）
    """
    items = GC.ocr_items(b, tag='%s_c0' % tag)
    if not panel_open(items):
        say('   · 已经不在情报页面了 ⇒ 不用关 ✓')
        return True
    # 读 X：面板右上角那颗（**用 OCR 找不到"X"这种符号** ⇒ 用标定坐标 ✓）
    b.tap(INTEL_CLOSE_X[0], INTEL_CLOSE_X[1], wait=2.0)
    items2 = GC.ocr_items(b, tag='%s_c1' % tag)
    _ok = not panel_open(items2)
    GC._log(log, {'intel': 'close_panel', 'at': INTEL_CLOSE_X, 'ok': _ok})
    say('   · 关掉情报页面 (%d,%d) ⇒ %s'
        % (INTEL_CLOSE_X[0], INTEL_CLOSE_X[1], '✓' if _ok else '⚠ 还在面板上'))
    return _ok


# ══════════════════════════════════════════════════════════════════════
# ② 主流程
# ══════════════════════════════════════════════════════════════════════
def run(b, log=None, daily=True, weekly=True, close=True,
        enter_guild=True, return_to_map=True):
    """领「情报」奖励 ⇒ 汇总 dict

    流程（用户口径：每日循环 + 每周盲点一次 + 关页面 ✓）：
        ① 打开情报面板（公会右上角「情报」）
        ② **每日情报**页签 ⇒ OCR 循环领到没有为止
        ③ **每周情报**页签 ⇒ **盲点最上那条一次**
        ④ **关掉页面** ⇒ 回公会展厅

    ⭐⭐⭐ 2026-10-15 **用户口径**（原话，统一三个脚本的进出场）：
        「体力用完后，把勾选的公会日常，免费招募和免广告
          （**这三个脚本的最后都要回到地图界面，最开始都要进入公会界面**）
          都做完后，检查下体力，如果超过100，就重新启动探图脚本」
      ⇒ 这里补上**回地图界面**那一步（原来只做到"关页面回公会" ✗）
        ⚠ 情报**本来就在公会里**（入口是公会右上角那颗）⇒
          `enter_guild` 只是保证"从别处来时能进公会" ✓
    """
    log = log if log is not None else []
    res = {'ok': False, 'daily': 0, 'weekly': False, 'closed': False}
    say('')
    say('=' * 62)
    say('📋 公会「情报」领奖（每日 + 每周）')
    say('=' * 62)

    # ── 入口：**先进公会**（用户口径「最开始都要进入公会界面」✓）──
    if enter_guild and not open_panel(b, log):
        say('   ✗ 没打开情报面板 ⇒ 放弃（不动任何东西）')
        res['why'] = 'panel_not_open'
        _intel_back_to_map(b, log, res, return_to_map)
        return res
    elif not enter_guild:
        # 调用方自己负责进场（老行为：直接开面板，它内部会按需进公会 ✓）
        if not open_panel(b, log):
            say('   ✗ 没打开情报面板 ⇒ 放弃（不动任何东西）')
            res['why'] = 'panel_not_open'
            return res

    # ② 每日情报：**先切页签**再循环领（面板默认停在"每日"，
    #    但用户可能手动切到"每周" ⇒ 显式切一下更稳 ✓）
    if daily:
        if switch_tab(b, 'daily', log):
            res['daily'] = claim_daily(b, log)
            say('   · 每日情报共领 **%d** 条 ✓' % res['daily'])
    else:
        say('   · 没勾「每日情报」⇒ 跳过')

    # ③ 每周情报：**盲点最上那条一次**
    if weekly:
        res['weekly'] = claim_weekly(b, log)
        say('   · 每周情报：%s' % ('领了最上面那条 ✓' if res['weekly']
                                  else '没有可领的（或第 1 行不是「可领取」）✓'))
    else:
        say('   · 没勾「每周情报」⇒ 跳过')

    # ④ 关页面
    if close:
        res['closed'] = close_panel(b, log)
    else:
        say('   · 没勾「关闭页面」⇒ 留在情报页')
    res['ok'] = True
    GC._log(log, {'intel': 'done', 'daily': res['daily'],
                  'weekly': res['weekly'], 'closed': res['closed']})
    _intel_back_to_map(b, log, res, return_to_map)
    say('=' * 62)
    return res


def _intel_back_to_map(b, log, res, want):
    """收尾：**回地图界面（选图界面）** ✓

    ⭐ 用户口径：「**这三个脚本的最后都要回到地图界面**」✓
    ⚠ 原来只做到"关掉情报页 ⇒ 回公会展厅"，**没回选图界面** ✗
      ⇒ 这一步补上（`GC.leave_guild` 点底部「开始冒险」✓）
    """
    if not want:
        say('   · 按要求**停在原地**（没回地图界面）')
        return
    _back = GC.leave_guild(b, log)
    res['back_to_map'] = bool(_back)
    say('   · %s' % ('已返回地图界面（选图界面）✓' if _back
                    else '⚠ 没确认回到选图界面（如实上报）'))


# ══════════════════════════════════════════════════════════════════════
# ③ CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:                                   # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='公会「情报」领奖（每日+每周）')
    ap.add_argument('--device', default=None, help='adb 设备号')
    ap.add_argument('--tag', default='intel', help='实例名')
    ap.add_argument('--no-daily', dest='daily', action='store_false',
                    default=True, help='不领每日情报')
    ap.add_argument('--no-weekly', dest='weekly', action='store_false',
                    default=True, help='不领每周情报')
    ap.add_argument('--no-close', dest='close', action='store_false',
                    default=True, help='领完**不关**页面')
    a = ap.parse_args()

    if a.device:
        GC.set_device(a.device)
    import mapbot as MB
    # ⚠ `mapbot.Bot` **没有 `close()`**（它有 `stdout` 重定向，但没有收尾方法 ✗）
    #   ⇒ 不要写 `finally: b.close()`（会 AttributeError 把真错误盖住 ✗）
    b = MB.Bot(log_prefix='intel', serial=a.device, tag=a.tag)
    log = []
    res = run(b, log, daily=a.daily, weekly=a.weekly, close=a.close)
    say('')
    say('结果：每日领 %s 条 ｜ 每周 %s ｜ 已关页面 %s'
        % (res.get('daily'), res.get('weekly'), res.get('closed')))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
