# -*- coding: utf-8 -*-
"""guild_tasks.py · 派遣任务（公会展厅 2 楼「黑晶女仆」那 4 把椅子）

用户口径（2026-10-14，原话）
--------------------------
· 「**不用放弃**」   ⇒ 绝不点「放弃」（每日限 3 次，浪费）
· 「**不召回**」     ⇒ 绝不点「召回」（会清空任务进度）
· 「这些我打算是**体力刷完自动去做**」⇒ 由主循环在收工时调用 ✓

干什么
------
把 4 把椅子全部弄成「**进行中**」：
    未接(`?`)      ⇒ 开面板 → 一键派遣 → 开始任务          （**两下**，见下）
    已完成(`!`)    ⇒ 领奖 → 椅子**换成新任务** → **回头再派一次** ← ⛔ 我第一轮漏了这步
    进行中(倒计时) ⇒ 什么都不做

⛔⛔ 最重要的一条（用户当场抓到我的漏洞）
----------------------------------------
「另外俩这么只领取了奖励，**没有派遣**」——
我第一轮 walk 是「椅1→椅2→椅3→椅4，每把只点一下」，而椅 2/3/4 当时是**已完成**：
点一下 = **领奖**，领完椅子立刻**换成新任务**（回到 `?`），可**我没回头再点它** ✗
⇒ 新任务就**一直挂着没派出去**。
⇒ 正确做法：**同一把椅子要一直弄到"它开始倒计时"为止**（见 `_ensure_dispatched`）✓

「一键派遣」为什么要两下（源码 `TaskInfoPanel.OnSubmitButtonClick` 逐字确证）
--------------------------------------------------------------------------
    第一下：`taskRoleCount < 1` ⇒ 只是**自动选 5 人**（填 playerRoleList）就 `return`，
            **一个请求都不发** ✗
    第二下：`taskRoleCount >= 1` ⇒ 才真的 `SubmitTeamToTask` ⇒ 拿到 ExpectFinishTime ✓
⇒ 判据就看**按钮文案**：
    「一键派遣」⇒ 这一下只是选人，**还要再点**
    「开始任务」⇒ 这一下就是提交 ✓

收益（源码公式 = 每人 +1 奖励、−10% 时间；实测逐值吻合）
    只派 1 人：奖励 1、8:00:00
    点满 5 人：奖励 6、4:00:00     ← 所以"一键派遣"总是赚的，没有取舍 ✓

用法
----
    # 只做派遣（不碰炼金）
    python guild_tasks.py --device 127.0.0.1:16448

    # 当模块用（主循环收工时调）
    import guild_tasks
    guild_tasks.run(bot, log)
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

# ⚠⚠ 2026-10-14 **真机首跑当场抓到的 NameError**：
#   本文件里有 **27 处** `say(...)`，但**从来没定义过它** ✗
#   （`guild_common` 里有 `say`，可我只 `import guild_common as GC`，
#     没把它引进本模块的命名空间 ⇒ `NameError: name 'say' is not defined`）
#   ⇒ 修法：显式取个别名。**为什么不写 `from guild_common import *`**：
#     那样会把 GC 里 40 多个名字全灌进来，日后重名会静默盖掉 ✗ ⇒ 只取要用的 ✓
say = GC.say


# ══════════════════════════════════════════════════════════════════════
# ① 椅子三态判定
# ══════════════════════════════════════════════════════════════════════
FREE, BUSY, DONE, UNKNOWN = 'free', 'busy', 'done', 'unknown'


def chair_timers(items):
    """椅子行里的倒计时文字 ⇒ {椅子号: 'HH:MM:SS'}

    ⚠ 这比"看气泡符号"**便宜得多也硬得多**（OCR 本来就要做，符号还得分形状）
      ⇒ **先用它**：有倒计时 = 进行中，一定是 BUSY ✓
    ⚠ 实测坑：OCR 会把两条倒计时**粘成一条**（`02:23:2702:33:26`）⇒ 得用
      `findall` 把里面的 `hh:mm:ss` 全抠出来，再看它离哪把椅子近 ✓
    """
    out = {}
    y0, y1 = GC.BUBBLE_Y0 - 25, GC.BUBBLE_Y1 + 25
    for it in (items or []):
        cy = it.get('cy', 0)
        if not (y0 < cy < y1):
            continue
        t = str(it.get('text') or '').replace(' ', '').replace('：', ':')
        # 一条里可能有 0~2 个 hh:mm:ss
        for m in GC.re.finditer(r'(\d{1,2}:\d{2}:\d{2})', t):
            # 按**字符位置**估它在这一条里的 x，再归到最近的椅子
            frac = (m.start() + m.end()) / 2.0 / max(1, len(t))
            cx = it.get('x0', it.get('cx', 0)) + frac * (
                it.get('x1', it.get('cx', 0)) - it.get('x0', it.get('cx', 0)))
            k = min(range(len(GC.CHAIR_X)),
                    key=lambda i: abs(GC.CHAIR_X[i] - cx))
            if abs(GC.CHAIR_X[k] - cx) <= 80:
                out.setdefault(k + 1, m.group(1))
    return out


def chair_state(b, items, idx):
    """单把椅子的状态（`idx` 1..4）⇒ (state, detail)

    判据顺序（先便宜后贵；**每一条都能单独站住**）：
      ① 椅子行有倒计时 ⇒ BUSY（最硬）
      ② 面板/弹窗开着 ⇒ 交给调用方（这里只看"没面板时椅子长什么样"）
      ③ 气泡里的字形是 `?` 还是 `!` ⇒ FREE / DONE
    """
    t = chair_timers(items).get(idx)
    if t:
        return BUSY, t
    # 没有倒计时 ⇒ 要么未接(`?`) 要么已完成(`!`)；用**点开面板**来区分最稳
    #   （读气泡形状要额外做图像处理，而"点开看按钮文案"本来就要做 ✓）
    return UNKNOWN, ''


# ══════════════════════════════════════════════════════════════════════
# ② 面板操作
# ══════════════════════════════════════════════════════════════════════
def task_panel_open(items):
    """派遣任务面板开着吗（标题「黑晶女仆」**整条相等**）

    ⚠ 必须 `exact`：正文里也有「黑晶女仆」这类字，子串会假命中 ✗
    """
    return GC.has(items, '黑晶女仆', exact=True)


def panel_action(items):
    """读面板底部主按钮的文案 ⇒ ('dispatch'|'submit'|'recall'|'unknown', 文字)

    ⚠ 实测 OCR 会把「一键派遣」读成「**键派遣**」（丢一个"一"）⇒ 判据用**子串**，
      且两个词都认 ✓
    """
    it = GC.find(items, '开始任务')
    if it:
        return 'submit', it['text']
    it = GC.find(items, '一键派遣', '键派遣')
    if it:
        return 'dispatch', it['text']
    it = GC.find(items, '召回')
    if it:
        return 'recall', it['text']
    return 'unknown', ''


def panel_state(items):
    """从面板文字判这格任务处于哪个阶段（纯日志/断言用）

    实测三种面板的**互斥**特征：
        未接    : 有「一键派遣」或「键派遣」，且「剩余时间：」
        已填队  : 有「开始任务」，且「剩余时间：」
        进行中  : 有「召回」，且「所需时间：」（注意是**所需**不是剩余 ✓）
    """
    if not task_panel_open(items):
        return 'no_panel'
    if GC.has(items, '所需时间：', '所需时间:'):
        return 'running'
    if GC.has(items, '剩余时间：', '剩余时间:'):
        if GC.has(items, '开始任务'):
            return 'filled'
        if GC.has(items, '一键派遣', '键派遣'):
            return 'free'
    return 'other'


def read_counts(items):
    """读「奖励数量：N」和「剩余时间：H:MM:SS」⇒ (n, 时间文字)，读不到给 None"""
    n = t = None
    it = GC.find(items, '奖励数量')
    if it:
        m = GC.re.search(r'(\d+)', it['text'])
        if m:
            n = int(m.group(1))
    it2 = GC.find(items, '剩余时间', '所需时间')
    if it2:
        m2 = GC.re.search(r'(\d{1,2}[:：]\d{2}[:：]\d{2})', it2['text'])
        if m2:
            t = m2.group(1)
    return n, t


def dismiss_reward(b, log, tag):
    """关掉「恭喜获得」奖励弹窗 ⇒ 点「返回」

    ⚠⚠ **用户口径（2026-10-14，原话）**：「**返回都不用按固定坐标点的**」✓
      ⇒ 这里**一律 OCR 现读坐标**，**不写死** ✓
    ⚠ 必须**每轮重新取帧**找「返回」（面板有弹出动画，一次判死会漏 ✗
      —— 本项目在 `relic_flow` 上正是栽在这：`has_ok_btn` 一次性判断 ✗）
    """
    return GC._dismiss_popup(b, log, tag)


# ══════════════════════════════════════════════════════════════════════
# ③ 单把椅子：一直弄到"它开始倒计时"为止
# ══════════════════════════════════════════════════════════════════════
def _ensure_dispatched(b, log, idx, max_rounds=3):
    """把第 idx 把椅子弄成**进行中** ⇒ 返回 'dispatched'|'already'|'failed'

    ⛔ 这是修「只领奖没派遣」的核心：**领完奖要回头再走一遍派遣** ✓
    """
    x = GC.CHAIR_X[idx - 1]
    for rnd in range(max_rounds):
        # ── 开面板（点椅子）──
        b.tap(x, GC.CHAIR_Y, wait=2.5)
        items = GC.ocr_items(b, tag='ct%d_%d_open' % (idx, rnd))

        # ① 直接领奖了（已完成）⇒ 关弹窗，**下一轮回头再派** ✓
        if GC.has(items, '恭喜获得'):
            say('       · 椅%d：已完成 ⇒ **领奖** ✓（领完会换成新任务，下一轮再派）'
                % idx)
            GC._log(log, {'task': 'claim', 'chair': idx, 'rnd': rnd})
            dismiss_reward(b, log, 'ct%d_%d' % (idx, rnd))
            continue                       # ← ⛔ 关键：**继续循环**，回头再点它一次

        # ② 面板没开 ⇒ 可能点在动画里/位置偏了，重试
        if not task_panel_open(items):
            GC._log(log, {'task': 'panel_miss', 'chair': idx, 'rnd': rnd,
                          'texts': GC._texts(items)[:10]})
            say('       · 椅%d：没开出面板（认到 %s）⇒ 重试'
                % (idx, GC._texts(items)[:6]))
            time.sleep(1.0)
            continue

        st = panel_state(items)
        GC._log(log, {'task': 'panel', 'chair': idx, 'rnd': rnd, 'state': st})
        n, t = read_counts(items)

        # ③ 进行中 ⇒ 什么都不做（**绝不点召回** ✗）
        if st == 'running':
            say('       · 椅%d：**进行中**（%s）⇒ 不动它 ✓' % (idx, t or '?'))
            GC.close_panel(b, GC.TASK_PANEL_X, 'ct%d_x' % idx,
                           probe_texts=('黑晶女仆',), log=log)
            return 'already'

        # ④ 未接 / 已填队 ⇒ 派它
        act, label = panel_action(items)
        GC._log(log, {'task': 'act', 'chair': idx, 'action': act,
                      'label': label, 'reward': n, 'time': t})
        if act == 'recall':
            # 理论到不了这里（running 分支已拦），真到了也**绝不点** ✓
            say('       · ⚠ 椅%d 面板只认到「召回」⇒ **不点**，关掉走人' % idx)
            GC.close_panel(b, GC.TASK_PANEL_X, 'ct%d_xr' % idx,
                           probe_texts=('黑晶女仆',), log=log)
            return 'failed'

        # 点主按钮；「一键派遣」只是选人 ⇒ 还要再点一次 ✓
        for hit in range(3):
            b.tap(*GC.TASK_ACTION_BTN, wait=2.5)
            items2 = GC.ocr_items(b, tag='ct%d_%d_t%d' % (idx, rnd, hit))
            if not task_panel_open(items2):
                # 面板没了 ⇒ 要么提交成功（回椅子行）、要么被关掉
                break
            act2, label2 = panel_action(items2)
            GC._log(log, {'task': 'act2', 'chair': idx, 'hit': hit + 1,
                          'action': act2, 'label': label2})
            say('       · 椅%d：点「%s」⇒ 现在按钮是「%s」'
                % (idx, label, label2 or '?'))
            if act2 == 'submit':
                continue          # 再点一下（这次才是提交）
            if act2 == 'dispatch':
                continue          # 还没选上人 ⇒ 再点
            break

        # ── 验证：**回椅子行看有没有倒计时**（这才是"派出去了"的硬证据）──
        time.sleep(1.2)
        items3 = GC.ocr_items(b, tag='ct%d_%d_v' % (idx, rnd))
        if task_panel_open(items3):
            GC.close_panel(b, GC.TASK_PANEL_X, 'ct%d_x2' % idx,
                           probe_texts=('黑晶女仆',), log=log)
            items3 = GC.ocr_items(b, tag='ct%d_%d_v2' % (idx, rnd))
        tm = chair_timers(items3).get(idx)
        if tm:
            say('       · 椅%d：**已派出** ⇒ 倒计时 %s ✓' % (idx, tm))
            GC._log(log, {'task': 'dispatched', 'chair': idx, 'timer': tm})
            return 'dispatched'
        say('       · 椅%d：点完了但**没看到倒计时** ⇒ 下一轮再看' % idx)
        GC._log(log, {'task': 'dispatch_unverified', 'chair': idx})
    return 'failed'


# ══════════════════════════════════════════════════════════════════════
# ④ 主流程
# ══════════════════════════════════════════════════════════════════════
def run(b, log=None, chairs=(1, 2, 3, 4), sweeps=2, leave=False):
    """派遣任务主流程 ⇒ 返回一份汇总 dict

    `sweeps`：**扫几遍**。默认 2 —— 因为"已完成"的椅子第一遍只领奖、
    第二遍才派出去（见 `_ensure_dispatched` 的说明）✓
    `leave`：做完要不要离开公会（默认不离开，交给调用方）
    """
    log = log if log is not None else []
    # ⛔⛔ 2026-10-19 **必须把设备号登记给 `guild_common`**（真机事故：
    #   用户报「**完全没有滑动**」，日志「滑了 8 次仍在椅子层」）
    #   ---- 根因 ----
    #     `guild_common.swipe_abs()` 走**裸 adb**，设备号来自 `_dev_of()`：
    #         `_DEV_CUR['dev'] or MAPBOT_DEVICE or DEV(=127.0.0.1:16384)`
    #     而 `_DEV_CUR['dev']` **只能由 `set_device()` 填**，
    #     它只在 `wrap_dry(bot)` 里被调用 —— 那两处调用**都在 `main()` CLI 路径**
    #     ⇒ 从 `explore_loop._guild_daily` 走**库调用**直进 `run()` 时
    #        **一次都没登记** ⇒ 退到默认 `16384`
    #     ⇒ 用户跑 16448，滑动却发到 16384（那台没游戏）⇒ **屏幕纹丝不动** ✗✗
    #   ---- 修法 ----
    #     入口就登记：`b.dev` 是 `GC.Bot` 的字段（`wrap_dry` 正是读它）✓
    try:
        GC.set_device(getattr(b, 'dev', None))
    except Exception:                   # noqa: BLE001
        pass
    res = {'ok': False, 'chairs': {}, 'claimed': 0, 'dispatched': 0}
    say('')
    say('=' * 62)
    say('📋 派遣任务')
    say('=' * 62)

    # ── 进公会（默认就在 2 楼，不用滚）──
    if not GC.goto_guild(b, log):
        say('   ✗ 进不了公会展厅 ⇒ 放弃（不动任何东西）')
        res['why'] = 'not_in_guild'
        return res
    say('   ✓ 已进公会展厅')
    # ⭐ 确保站在**有椅子**的那层 —— 用"**试点椅1、看面板开不开**"自证
    #   （⛔ 别再用"认楼层/认气泡"那套：2026-10-14 连写三版判据全被真机证伪，
    #     详见 `guild_common.ensure_chair_floor` 的 docstring ✓）
    if not GC.ensure_chair_floor(b, log):
        say('   ✗ 找不到派遣椅子那层 ⇒ 放弃（不动任何东西）')
        res['why'] = 'chair_floor_not_found'
        return res

    for sw in range(max(1, int(sweeps))):
        say('')
        say('   ── 第 %d/%d 遍 ──' % (sw + 1, sweeps))
        for idx in chairs:
            tm_before = chair_timers(GC.ocr_items(b, tag='ct%d_pre' % idx)).get(idx)
            if tm_before:
                say('   · 椅%d：进行中（%s）⇒ 跳过 ✓' % (idx, tm_before))
                res['chairs'][idx] = ('busy', tm_before)
                continue
            say('   · 椅%d：处理中…' % idx)
            r = _ensure_dispatched(b, log, idx)
            res['chairs'][idx] = (r, '')
            if r == 'dispatched':
                res['dispatched'] += 1
            elif r == 'already':
                pass
            else:
                # 'failed' 也可能是"领了奖但没派成"⇒ 下一遍再试
                res['chairs'][idx] = ('retry', '')

    # ── 收尾：四椅最终状态（如实报，不粉饰）──
    time.sleep(1.0)
    final = chair_timers(GC.ocr_items(b, tag='task_final'))
    res['final_timers'] = final
    say('')
    for idx in chairs:
        if idx in final:
            say('   ✓ 椅%d：进行中 %s' % (idx, final[idx]))
        else:
            say('   ⚠ 椅%d：**没看到倒计时**（未接 / 已完成待领 / 读不出）' % idx)
    res['ok'] = len(final) > 0
    res['busy_count'] = len(final)
    GC._log(log, {'task': 'done', 'busy': len(final), 'timers': final})
    if leave:
        GC.leave_guild(b, log)
    say('=' * 62)
    return res


def _chair_row_visible(items, img=None):
    """椅子行在不在这一屏

    ⛔ 2026-10-14 真机抓到的**判据错误**（第一版）：
      我原来写 `chair_timers(items) or GC.in_guild(items)` ——
      而 `in_guild` 只判"在不在公会"⇒ **3 楼/4 楼也返回 True** ✗
      ⇒ 于是"椅子看不见"被当成"椅子在"，再往下就点空了 ✗
    ⇒ 现在**直接用 `GC.chair_row_hint`**（它同时看文字 + **白色气泡图像**，
      是"**这就是椅子那层**"的判据，不是"在公会"）✓
    """
    return GC.chair_row_hint(items, img)


# ══════════════════════════════════════════════════════════════════════
# ⑤ CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:                                       # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='派遣任务（公会 2 楼 4 把椅子）')
    ap.add_argument('--device', default=None, help='adb 设备号，如 127.0.0.1:16448')
    ap.add_argument('--tag', default='guildtask', help='实例名（隔离截图目录）')
    ap.add_argument('--sweeps', type=int, default=2, help='扫几遍（默认 2）')
    ap.add_argument('--leave', action='store_true', help='做完离开公会')
    ap.add_argument('--chairs', default='1,2,3,4', help='只做这几把，如 3,4')
    ap.add_argument('--dry-run', action='store_true',
                    help='⭐ 试跑：**一下都不点**，只打印"认到啥 / 打算点哪"')
    a = ap.parse_args()

    dev = a.device or os.environ.get('MAPBOT_DEVICE') or GC.DEV
    chairs = tuple(int(v) for v in str(a.chairs).split(',') if v.strip())
    GC.DRY_RUN = bool(a.dry_run)
    say('设备：%s ｜ 实例：%s ｜ 椅子：%s ｜ 扫 %d 遍%s'
        % (dev, a.tag, list(chairs), a.sweeps,
           ' ｜ ⚠ **试跑模式：不会点任何东西**' if GC.DRY_RUN else ''))
    b = GC.wrap_dry(GC.Bot(log_prefix='guildtask', serial=dev, tag=a.tag), None)
    log = []
    try:
        res = run(b, log, chairs=chairs, sweeps=a.sweeps, leave=a.leave)
    finally:
        for e in log:
            print(e)
    say('')
    say('结果：%s' % ('✓ 有椅子在跑' if res.get('ok') else '⚠ 没有椅子在跑'))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
