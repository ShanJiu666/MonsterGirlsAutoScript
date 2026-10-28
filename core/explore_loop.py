# -*- coding: utf-8 -*-
"""explore_loop.py (2026-09-25 lean rewrite)

Verified rules only:
  * fight ONLY boss / 4-marked blocks; skip plain fights
  * reveal-first (unlock path), never poke locked marked cells first
  * marked cells are never blacklisted; blocked -> clear-path mode
  * result panel: click 关闭 only when OCR really saw it
  * recommend fight + win -> dice (max 3), stop when thumbs-up loot appears
  * all marked blocks done -> leave the map
"""
import os
import re
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np
import marks as marks_mod
import spots as spots_mod
import buypanels
import layout as layout_mod
import targets_cfg as tcfg_mod          # ⭐ 目标方块白名单（用户 2026-09-28 要求 ✓）
from mapbot import Bot, RUNS, ADB, DEV, CREATE_NO_WINDOW
from mapbot import _is_conn_err      # ⭐ 进图/触摸的"连接类错误"判据**同一份**（别各写一套 ✓）

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `templates/` `runs/` `data/` 这些资源都相对**仓根** ⇒ 必须多上一级。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ⭐ 2026-10-01：模板/资源根目录。
#   Android 侧由 `android_autoexplore/tools/port_loop.py` 注入（APK 内只读 ⇒ 指向
#   filesDir/mapbot_pack）；PC 侧**原来没定义** ⇒ 一调 `_find_ui_tpl` 就 NameError
#   （被 bag_upgrade 的兜底 except 吞成 `bag: error` ✗）。这里补一个 PC 兜底 ✓
try:
    _MAPBOT_ROOT                                       # noqa: B018
except NameError:
    _MAPBOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = os.path.join(RUNS, 'loop')
os.makedirs(WIN, exist_ok=True)
LOG_PATH = os.path.join(WIN, 'loop_log.json')
SUMMARY_PATH = os.path.join(RUNS, 'last_summary.json')
# ⭐ 多开模式（2026-09-25 用户要求）：每个实例用 `--tag acc2` 区分 ⇒ 截图/日志/统计各自独立
#   （截图进 `runs/acc2/`、日志 `runs/acc2/loop/loop_log.json`、统计 `runs/acc2/last_summary.json`），
#   两台模拟器同时跑不会互相覆盖：`--device 127.0.0.1:16416 --tag acc2`
# ⭐ 2026-09-25：控制台实时进度（用户要「桌面快捷方式，打开就能用」）
#   `--quiet` 关掉；结束时那份全量 json 日志照旧打印（--no-dump 关）
VERBOSE = True
DUMP_AT_END = True
# 进图前体力下限：低于它就收工（用户 2026-09-25：**连刷模式 <50 就停**；单张模式仍用 25）
# ⭐⭐⭐ 2026-10-15 **收工后重开的门槛**（用户口径，原话）：
#   「…都做完后，检查下体力，如果**超过100**，就**重新启动探图脚本**」✓
#   ⚠ 它与上面那个"收工下限"**是两回事**，别混：
#     · 收工下限（`MIN_STAMINA`，50/25）⇒ **什么时候停**
#     · 重开门槛（本常量，100）    ⇒ **停下来之后够不够再开一轮**
#   为什么重开门槛**比收工下限还高**？—— 因为收工后做了三个日常
#     （广告奖 +600、情报升级奖励…）⇒ 体力会**回血**；
#     设成 100 是用户要的"够刷几张才值得重开"（25 一张 ⇒ 至少 4 张 ✓）
RELAUNCH_STAMINA_MIN = 100
MIN_STAMINA = 25
STOP_AT_5AM = True      # ⭐ 凌晨自动停止（用户 2026-09-26；停每张图之间，正在打的会打完）
STOP_HM = (4, 58)       # ⭐ 停止时刻 = 04:58（用户 2026-09-26：「4.58停吧，打完最后一张图」）
STOP_TIME = None        # 本次运行的停止时刻（datetime）
_LOOP_LOCK = None          # 本进程占的设备锁 (device, tag)
EXPLORE_DISPATCH = True   # 探索/派遣功能（紫橙地块→探索→派遣 ✓）
# ⭐ 探索槽**封顶** = **3**（用户 2026-10-02 **当面确认**：「探索槽只有 3 个」；
#   与 2026-09-26 的用户口径「一共能装 3 个」一致 ⇒ PC 端一直是 3 ✓）
# ⛔⛔ 曾经被改成 4 —— 那是**从手机端抄过来的**（注释里写着 "Redmi 1280×2772" 实测 4 槽）。
#   而 `AGENTS.md §3` 早就点过这条：**两端不一致，别把一端的结论套到另一端**
#   （PC 3 / 手机 4）。抄错的后果（2026-10-02 22:15 真机铁证）：
#     `slots:{free_txt:0, busy_strict:3}` —— 明明是 **3 个槽全满**，
#     但总数按 4 算就"看起来还差一个" ⇒ 判不出满 ⇒ 对着紫格连点「探索」**24 轮** ✗✗
#   ⚠ 这个数只当「空闲数封顶」+ 「占用数是否已达总数」用；
#     **不许**再拿它去反推空闲个数（`TOTAL - busy` 反推法已废除 ⇒ 见 `explore_slots_free`）
EXPLORE_SLOTS_TOTAL = 3
AUTO_SUPPLY = False     # 没体力自动用「结实补给」（--auto-supply / GUI 按钮）
SUPPLY_USED = 0         # 本次已用个数（**只做统计**，不设上限 —— 用户 2026-09-25 要求）
OPT = False             # 体力最省模式（--opt）
INSTANCE_TAG = ''       # 多开实例名（空 = 单开，用共享目录）
INSTANCE_DEV = DEV      # 该实例绑定的模拟器 adb 设备号
_BOT = None             # 当前 Bot（统计要读它的耗时埋点）



#: `board_snapshot` 最少要有多少格才写（见下方"两道闸"注释）
#:  实测正常盘 21~29 格；只有 2~5 格的必然是"进图首帧没扫全" ⇒ 不写 ✓
_SNAP_MIN = 12

def say(msg):
    if VERBOSE:
        try:
            print(msg, flush=True)
        except Exception:       # noqa: BLE001
            pass


# ⭐⭐ 2026-09-30（用户口径）：「悬浮窗上很多日志太技术性了，没必要全都显示出来。
#   比如什么**识别了 xx 条、用时多久**，用户完全不需要看这些。这个日志是给**用户**看的，
#   用户只需要知道**现在在干什么**」。
#
#   根因：悬浮条原先直接吃**原始日志流**，靠 Java 侧 `describeAction()` 的正则猜「哪条是行动」，
#   而它最后有一条兜底 `if (len <= 46 and 无 '{') 照播` ⇒ 任何短技术行都会漏上去
#   （`识别棋盘：35 格`、`· 分类兜底：低门槛重试拿到 30 格 ✓`、`· 自动跳过已勾选 ✓` …）。
#   修法 = **显式 UI 通道**：只有走 `status()` 发出的短句才进悬浮条日志行；其余所有
#   `say()`/`print()` 一律只进界面控制台与 logcat（**那是给开发看的**）。
#
#   ⚠ 写 status() 的三条硬规矩：
#     ① **短** —— 悬浮条一行 ≈ 28px 加粗等宽，超过 ~28 个汉字会被滚动/省略号收尾；
#     ② **人话** —— 是"我现在在干什么"，不是状态机内部名（不要轮号/坐标/cost/步数）；
#     ③ **避开 OCR 关键词**（开始冒险 / 进入地图 / 一键派遣 / 探索配队 / 探索产出 /
#        关闭 / 探索 / 派遣 / 领取）—— `OverlayService.sanitize()` 会把它们糊成 ▓
#        （双保险：万一"涂平"失效，游戏也不会把它当面板文字）。所以这里说
#        「派小队 / 收起面板 / 拿奖励」，不说「派遣 / 关闭 / 领取」。
UI_MARK = '\u203a '          # `› ` —— 只做传输标记，OverlayService 会剥掉，不会画到屏幕上


def status(msg):
    """发一条**给用户看**的「当前行动」（→ 悬浮条日志行）。

    ⚠ 与 `say()` 的区别：`say()` 是开发者日志（可能非常啰嗦，只在控制台/logcat 里）；
       `status()` 是**唯一的**能上悬浮条的口子 ⇒ 调用要克制、要短、要人话。
    """
    if not msg:
        return
    try:
        print(UI_MARK + str(msg), flush=True)
    except Exception:       # noqa: BLE001
        pass


def cur_map_no():
    """当前是第几张图（1 基）。给 status() 拼文案用；不在图上时返回 0。"""
    try:
        return int(STATS.get('current_map') or 0)
    except Exception:       # noqa: BLE001
        return 0


# ⭐ 本次运行统计（用户 2026-09-25 要求：结束时要报「刷了几张图/平均耗时/打了几个 boss 关/
#   拿到几件大拇指装备/买完几个旅行商人/几个黄金宝库」）
STATS = {'clovers': 0, 
    'maps': 0,            # 刷完的图数
    'shots': 0,           # ⭐ 采图模式（--collect-only）存下的首帧数
    'map_secs': [],       # 每张图耗时
    'boss_fights': 0,     # 首领关战斗场次
    'boss_wins': 0,       # 首领关胜利
    'recommend_fights': 0,
    'recommend_wins': 0,
    'dice_got': 0,        # 摇色子拿到「大拇指装备」的次数
    'merchants': 0,       # 买完的旅行商人
    'vaults': 0,          # 买完的黄金宝库
    'battles': 0,         # 全部战斗场次
    'battle_wins': 0,
    'stopped': '',
    # ⭐⭐⭐ 2026-10-05 用户口径「报数/计数分开」：两个计数器**各管一件事**（见 `map_end_kind`）
    'blind_maps': 0,      # 连续「真·认不出棋盘（被面板挡住 / 整盘读成空格）」
    'stuck_maps': 0,      # 连续「画面正常但计划走不下去（目标不可达）」
    'current_map': 0,     # 正在跑的这张图（1 基）；被停止时用来说明跑到哪了
    'current_secs': 0,    # 这张图已耗时
    'stamina_entries': [],  # 每次「进图时」读到的体力（用户口径：两次进图相减 = 消耗）
    'running': True,
    'classify': 0.0,        # ⭐ 棋盘分类累计耗时（埋点用）
    'classify_n': 0,        # 分类调用次数
}


def device_lock_path(device):
    try:
        port = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        port = 0
    return os.path.join(RUNS, '.loop_%d.lock' % port)


def _read_lock_pid(p):
    """读设备锁里的 PID —— 兼容三种形态：JSON / 纯文本 PID / 空（已释放）

    ⭐ 2026-09-28：16384 的锁原来写纯文本 PID，而 16416（采集链路）的锁是 JSON
    （`{"pid":…,"released":…}`）—— **两种格式并存**读方要猜 ✗。统一按"先试 JSON
    再退回 int"解析，新旧锁都能读；写侧一律写 JSON（见 acquire_device_lock）。
    """
    try:
        raw = (open(p, encoding='utf-8').read() or '').strip()
    except Exception:       # noqa: BLE001
        return 0
    if not raw:
        return 0
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return int(obj.get('pid') or 0)
    except Exception:       # noqa: BLE001
        pass
    try:
        return int(raw)
    except Exception:       # noqa: BLE001
        return 0


def acquire_device_lock(device):
    """同一台模拟器**同时只允许一个循环**在跑（2026-09-25 教训：我在用户跑着的时候又起了一个，
    两边抢着点，互相打架）。已被占用就返回 None，调用方应直接退出。

    ⭐ 2026-09-28：写侧升级为 JSON（pid/device/started_at，便于事后判断谁是僵尸锁）；
    读到"PID 已不存在"的陈旧锁时**自动接管**并打一行提示（原来是静默覆写）。
    """
    p = device_lock_path(device)
    if os.path.exists(p):
        pid = _read_lock_pid(p)
        alive = False
        if pid:
            try:
                import subprocess as _sp
                out = _sp.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV'],
                              capture_output=True, text=True, errors='replace',
                              timeout=10,
                              creationflags=CREATE_NO_WINDOW).stdout
                # ⚠ 用带引号的精确匹配（CSV 里 PID 一定是 "1234" 形态）——
                #   原来的 `str(pid) in out` 是子串匹配，可能被别的列撞上 ✗
                alive = ('"%d"' % pid) in out
            except Exception:   # noqa: BLE001
                alive = False
            # ⭐⭐ 2026-10-05：**只查"PID 还在不在"不够 —— Windows 会回收 PID**
            #   （真机事故：`.loop_16384.lock` 里那个早已死掉的 20172 被系统分给了
            #    conhost.exe ⇒ 每次启动都判"被占用"⇒ 退出码 0、一把都跑不起来 ✗✗）
            #   ⇒ 再确认一次"这个 PID 现在到底是不是我们的循环脚本"（与 loopguard 同判据）
            if alive:
                try:
                    import loopguard as _lg
                    alive = _lg.pid_is_ours(pid, loop_only=True)
                except Exception:       # noqa: BLE001
                    pass                # 查不了 ⇒ 保守当活着（不冒"两个循环抢一台机器"的风险）
        if alive:
            # ⭐⭐⭐ 2026-09-28 修「**自我冲突**」真机 bug（22:02/22:03 两次 100% 复现）：
            #   main() 里两套锁机制**串行打架** —— 先 `guard_duplicates()` →
            #   `loopguard.acquire()` 把**本进程 PID** 写进 `.loop_<port>.lock`；
            #   紧接着本函数读**同一个文件** ⇒ 看到一个"活着的 PID" ⇒ 误判
            #   "已有另一个循环在跑" ⇒ 拒绝启动（其实那就是自己 ✗✗）。
            #   症状：GUI 点开始即报「已经有另一个自动探索在跑」、退出码 0、循环
            #   从未真正开跑（loop_log 不推进）。
            #   判据：**锁主 == 自己 ⇒ 不是别人，直接放行**（锁保持 loopguard 写的内容）。
            if pid == os.getpid():
                return p
            return None
        try:
            say('   ⚠ 发现陈旧设备锁（PID %s 已不存在，多半是上次崩溃没走 finally）'
                '⇒ 自动接管 ✓' % (pid or '?'))
        except Exception:       # noqa: BLE001
            pass
    try:
        os.makedirs(RUNS, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'pid': os.getpid(), 'device': device,
                                'started_at': time.strftime('%Y-%m-%d %H:%M:%S')},
                               ensure_ascii=False))
    except Exception:           # noqa: BLE001
        pass
    return p


def release_device_lock(p):
    """释放设备锁（⭐ 2026-09-28：**截断代替删除**）

    沙箱 `sitecustomize.py` 给 `os.remove` 挂了「每**次工具调用**计数，满 50 就
    `raise SystemExit(1)`」的守卫。长流水线每轮都要 release 一次 ⇒ 跑到第 11 轮
    就把采集进程打死（实测 `runs/_pipeline.log`）✗
    截断后文件仍在、内容为空 ⇒ `acquire_device_lock` 会当成没有锁直接覆写 ✓ 语义不变。
    """
    try:
        if p:
            open(p, 'w', encoding='utf-8').close()
    except Exception:           # noqa: BLE001
        pass


def stamina_line():
    """体力消耗（用户口径：两次进图的体力相减；**并按游戏 30 秒回 1 点做补偿**）

    单图消耗 = (进图体力_i − 进图体力_{i+1}) + (两次进图间隔秒数 / 30)
    —— 间隔期间游戏会自动回体力，不补回来的话会把「回复的」当成「没花的」，低估消耗。
    每段夹在 ≥0（中途吃药/大额补充时不冲抵别的段）。
    """
    ent = list(STATS.get('stamina_entries') or [])
    if len(ent) >= 2:
        total = 0.0
        parts = []
        for i in range(len(ent) - 1):
            s0, t0 = ent[i]
            s1, t1 = ent[i + 1]
            dt = max(0.0, t1 - t0)
            regen = dt / 30.0                     # 30 秒回 1 点
            spent = max(0.0, (s0 - s1) + regen)
            total += spent
            parts.append('%d→%d(-%d +回%.0f)' % (s0, s1, max(0, s0 - s1), regen))
        how = ('进图体力 %s 点；已按 30 秒/点补回间隔期间的回复'
               % '，'.join('%d' % s for s, _t in ent))
        return (total, how, parts)
    if len(ent) == 1:
        return (None, '只进了一张图，没有第二次进图可相减（进图时 %d）' % ent[0][0], [])
    return (None, '没读到体力', [])


def summary_text():
    s = STATS
    avg = (sum(s['map_secs']) / len(s['map_secs'])) if s['map_secs'] else 0
    spent, how, parts = stamina_line()
    # ⭐ 2026-09-27 用户要求：只显示「总消耗」+「平均每图」两条 ✓（去掉逐图明细/说明 ✗）
    _maps = max(1, int(s['maps']))
    _spent_txt = ('%.0f 点' % spent) if spent is not None else '—'
    _avg_txt = ('%.1f 点/张' % (spent / _maps)) if spent is not None else '—'
    lines = ['',
             '════════ 本次统计 ════════',
             '  消耗体力   ：%s' % _spent_txt,
             '  平均每图   ：%s' % _avg_txt,
             ]
    lines += [
             '  刷完地图   ：%d 张' % s['maps'],
             ]
    if s.get('shots'):
        # ⭐ 采图模式（--collect-only）：只存首帧、不推图 ⇒ 单独报一行 ✓
        lines += [
             '  采集首帧   ：%d 张（只进图截图退图；每张 25 体力）' % s['shots'],
             ]
    lines += [
             '  平均耗时   ：%.0f 秒/张（合计 %.0f 秒）' % (avg, sum(s['map_secs'])),
             '  首领关     ：%d 场（胜 %d）' % (s['boss_fights'], s['boss_wins']),
             '  全部战斗   ：%d 场（胜 %d）' % (s['battles'], s['battle_wins']),
             '  大拇指装备 ：%d 件（推荐战 %d 场 / 胜 %d；摇色子拿到 %d）'
             % (s['dice_got'], s['recommend_fights'], s['recommend_wins'], s['dice_got']),
             '  幸运草地块 ：%d 个' % s.get('clovers', 0),
             '  旅行商人   ：买完 %d 个' % s['merchants'],
             '  黄金宝库   ：买完 %d 个' % s['vaults'],
             ]
    if not s['running'] and s['current_map'] and s['current_secs']:
        lines.append('  ⚠ 第 %d 张图跑到 %.0f 秒时被停止（这张未计入）'
                     % (s['current_map'], s['current_secs']))
    if s['stopped']:
        lines.append('  结束原因   ：%s' % s['stopped'])
    lines.append('══════════════════════════')
    try:
        t = getattr(_BOT, 't', None)
        if t:
            total = sum(t.get(k, 0.0) for k in ('snap', 'ocr', 'wait')) + s.get('classify', 0.0)
            lines.append('  ⏱ 耗时分布：截图 %.1fs(%s)｜OCR %.1fs/%d次｜棋盘识别 %.1fs（%d次）'
                         '｜点击等待 %.1fs(%d次)'
                         % (t.get('snap', 0), '极速' if getattr(_BOT, 'fast_ok', False) else 'adb',
                            t.get('ocr', 0), t.get('ocr_n', 0), s.get('classify', 0.0),
                            s.get('classify_n', 0), t.get('wait', 0), t.get('wait_n', 0)))
            lines.append('               （以上合计 %.0f 秒；其余为游戏动画/面板本身的响应时间）' % total)
            by = t.get('ocr_by') or {}
            if by:
                detail = '｜'.join('%s %.1fs/%d次' % (k, v[0], v[1])
                                   for k, v in sorted(by.items(), key=lambda kv: -kv[1][0]))
                lines.append('              OCR 分账：%s' % detail)
    except Exception:       # noqa: BLE001
        pass
    return '\n'.join(lines)


def dump_summary():
    try:
        import json
        os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
        with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
            json.dump({'stats': STATS, 'text': summary_text(), 'tag': INSTANCE_TAG,
                       'device': INSTANCE_DEV}, f, ensure_ascii=False, indent=1)
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐ 2026-10-01 v1.12【给"别人的手机"留一份可读日志】
    #   背景：MGAS 发给朋友后出问题（"面板挡住了棋盘"/"一直把游戏拉回来"），
    #   而 **release 包不可 `run-as`** ⇒ 私有 `files/runs/**` 根本拿不出来 ✗
    #   朋友圈里也不方便跑 logcat ⇒ 直接把**最近日志 + 统计**写一份到公共目录：
    #     `/sdcard/Download/autoexplore/mgas_log.txt`（让他把这个文件发过来即可 ✓）
    try:
        _lines = []
        if os.name != 'posix':      # ⚠ 只在端上写（PC 上 '/sdcard/...' 会落到盘根，污染工作区 ✗）
            raise RuntimeError('skip on pc')
        for _e in (_GLOBAL_LOG[-400:] if _GLOBAL_LOG else []):
            try:
                _lines.append(json.dumps(_e, ensure_ascii=False)[:300])
            except Exception:       # noqa: BLE001
                pass
        _txt = (summary_text() + '\n\n---- 最近日志（最多 400 条）----\n'
                + '\n'.join(_lines) + '\n')
        os.makedirs(BAG_PUB_DIR, exist_ok=True)
        with open(os.path.join(BAG_PUB_DIR, 'mgas_log.txt'), 'w',
                  encoding='utf-8') as _f:
            _f.write(_txt)
    except Exception:       # noqa: BLE001
        pass

# ⭐ 2026-09-25 重标定：屏幕格距 144.0、棋盘左上 (36, 1002)（见 spots.GRID / fit_art.py）
GRID = spots_mod.GRID
# ⭐ 分辨率自适应：连接设备后由 apply_layout() 按实际屏幕刷新 ✓
# ⭐ 分辨率自适应总开关（False = 完全按 1080×1920 常量跑 ⇒ 等于改 720p 之前 ✓）
LEARN_TILES = False        # 边跑边学空地判据（默认关 ✓ 判据不稳会帮倒忙 ✗）
# ⭐ 2026-09-27 用户口径：**只存「刚进图那一张」**（最干净 ✓ 后面轮次图标会盖住地块美术 ✗）
#   · SAVE_FIRST（默认开）⇒ 每张图只存 **进图首帧** `runs/r_<HHMMSS>_0.png`（≈0.7MB/图）
#   · SAVE_ROUNDS（默认关，**没挂窗口按钮**）⇒ 逐轮全存。只作深度调试的后门
#     （`set MAPBOT_SAVE_ROUNDS=1`），平时别开 —— 会堆一堆图，且核对用不上 ✗
# ⭐⭐ 2026-10-03 朋友版开关（见 friend_mode.py）：**运行期读**，不再靠打包时改源码
#   ⚠ 以前是 `build_pkg.py` 打包时字符串替换这两行 ⇒ **一发逻辑热更补丁就被冲回开发版** ✗
#     （补丁按仓库源码生成，仓库里当然是开发版）⇒ 现在与热更彻底解耦：
#     开发机没有 friend_mode.flag ⇒ 行为与以前**一模一样** ✓
try:
    import friend_mode as _friend_mod
    _FRIEND = _friend_mod.IS_FRIEND
except Exception:       # noqa: BLE001  （缺模块 ⇒ 当开发版，绝不让它拦住主流程）
    _FRIEND = False
SAVE_ROUNDS = bool(os.environ.get('MAPBOT_SAVE_ROUNDS'))
SAVE_FIRST = os.environ.get('MAPBOT_SAVE_FIRST', '0' if _FRIEND else '1') != '0'

# ⭐⭐⭐⭐ 2026-10-07 **预言石碑的两个「停脚本」开关**（用户口径，原话）：
#   ①（幸运）「**这个预言要加个按钮，是否停止脚本（类似出现红装标记）**」
#   ②（和平）「**地图中必定出现金属宝箱怪也要单独拿出来弄个选项，遇到那个是否立即停止脚本**」
#   ⇒ 抽到对应预言时 **停脚本 + 保现场**（与红装 `red_equip` 同一套处置 ✓）
#   ⚠ 默认 **开**（用户要的就是"遇到就停"）；GUI 勾选框写 `runs/.stop_{lucky,peace}`，
#     子进程靠这两个环境变量读（与 `MAPBOT_SAVE_FIRST` 同一套机制 ✓）
STOP_LUCKY = os.environ.get('MAPBOT_STOP_LUCKY', '1') != '0'
STOP_PEACE = os.environ.get('MAPBOT_STOP_PEACE', '1') != '0'

# ⭐⭐⭐⭐⭐ 2026-10-09 用户口径（原话）：
#   「**预言石碑停止脚本加上橙色和紫色元素**」✓
#   ── 「元素」是什么（数据表 `Foretell` 实测 3 档，见 `_ref_game_src/README_预言石碑_全部预言.md`）
#       Id            Step   效果
#       foretell_50   B      地图中至少出现 N 只莱姆，且所有莱姆至少是**蓝色**位阶
#       foretell_51   A      …至少是**紫色**位阶    ← ⭐ 用户要停
#       foretell_52   S      …至少是**橙色**位阶    ← ⭐ 用户要停
#   ⇒ **两个独立开关**（用户要紫+橙；**蓝档不停** ✓）
#   ⚠ 默认 **开**（与 `STOP_LUCKY/STOP_PEACE` 同向：用户点名的就是"要停下来自己处理" ✓）
STOP_ELEM_PURPLE = os.environ.get('MAPBOT_STOP_ELEM_PURPLE', '1') != '0'
STOP_ELEM_ORANGE = os.environ.get('MAPBOT_STOP_ELEM_ORANGE', '1') != '0'

# ⛔ 2026-10-11 **删掉 `STOP_MIMIC2` / `STOP_SHRINE`（[临时]采集停止）** ✓
#   用户原话：「**把窗口那个临时用的采集停止去掉吧**」
#   ── 它原来是干什么的 ────────────────────────────────
#     2026-10-08 用户要求「临时给pc窗口加个遇到机巧宝箱怪和祭坛停止的，
#     用来测试最后两个特殊地块」⇒ 图上认出该地块 ⇒ **停脚本、保现场**，
#     方便人工去采面板坐标 ✓
#   ── 为什么现在能删 ──────────────────────────────────
#     **两个面板都已采到、流程都已写好**：
#       · 机巧宝箱怪 ⇒ 与金属共用 `buypanels.mimic_flow`（真机实测过 ✓）
#       · 传承祭坛   ⇒ `buypanels.shrine_flow`（面板 `_verify/shrine_panel.png`
#                       已采到；判据 = 右下角 30000 就买 ✓）
#     ⇒ 这个"临时工具"使命完成，留着只会**误停脚本** ✗
#   ── 删了什么 ────────────────────────────────────────
#     · 本两行常量 ＋ `COLLECT_STOP_NAMES`
#     · `popups()` 里 `STOP_SHRINE` 那条 `shrine_stop` 早退
#     · `one_round` 轮首的 `collect_stop` 早退
#     · `run_maps` 里 `why == 'collect_stop'` / `'shrine_stop'` 两个分支
#     · `bot_gui` 第 5 排那两个勾选框 ＋ 两个 `MAPBOT_STOP_*` 环境变量
#   ⚠ `shrine_stop` 这个**返回值本身保留**吗？—— **不保留**：它唯一的产生者就是
#     那条 `STOP_SHRINE` 早退；删了之后没有任何路径会返回它 ✓
#     （`传承祭坛` 现在正常走 `popups()` → `shrine_flow` ✓）
# ⭐⭐ 2026-09-27 用户要求：「开一个新脚本抓另一个模拟器 —— 只进图截图退图，拿图片快一些」
#   `--collect-only`（采图模式）：**进图 → 存首帧 → 退图**，不揭格 / 不打怪 / 不买 /
#   不补点 / 不背包升星 ⇒ 一张图 ≈ 30~40 秒换 1 张首帧（正常推图 ≈ 4 分钟才 1 张）
#   ⚠ 成本不变：**进图瞬间扣 25 体力**（实测 2282→2257、2180→2155，两次都是恰好 25），
#      退图**不退**体力 ⇒ 这是「用体力换图片」，不会白嫖 ✓
COLLECT_ONLY = False
SKIP_SPAWN_CLICK = False   # 执行序列里是否跳过出生点（默认关 ✓ 开了揭示起不来 ✗）
# ⭐⭐⭐ 2026-10-03 用户口径（实测后定的）：「**窗口不显示，固定开**」
#   朋友版**也开**精确规划 —— 关掉它的实测后果是 `targets_unreachable` ⇒ stuck 退图
#   （目标被暗格围住时启发式 EffPolicy 根本不给出可走步，25 体力白花 ✗）
#   而开着的代价是**零**：精确求解（建盘+编译+solve）实测 p50 0.65ms / p95 1.4ms
#   ⇒ 勾选框**只在开发版显示**（见 bot_gui.py），但两边**固定开** ✓
OPT_SOLVER = True     # ⭐ 每轮用精确解算器规划点序（最省体力 ✓ fail-open ✓）
#   ⚠ 仍保留 `--no-solver` 覆盖（开发机排查用），只是**不再跟朋友版绑定**
# ⭐⭐⭐ 2026-10-02 用户口径（**PC 端专属**）：「**去掉那些追加的，只按规划的走**」
#   ⇒ `order` **只由规划器产出**（solver ≤4 步 / EffPolicy ≤2 步），不再追加：
#       ① 「出生地→目标」路上用来开路的格
#       ② 交替插入的目标格（原来"点一格 → 试一次首领 → 再点一格"）
#       ③ 路上没可点格时的内容格兜底
#       ④ **也不再**把"当下就能点的 boss/红装"提到最前 ——
#          `_hoist_ready_boss_first` 是**手机端 v1.34 搬过来的**
#          （PC 代码里那行注释原文就是「⭐ 2026-10-02（手机端 v1.34 对齐）」；
#            用户 2026-10-02 指出「**提序我记得是手机端说过的**」⇒ PC 端不跟随）
#   ⚠ 仍然照旧计算的（**不是点击序列**，别一起删）：
#       `road_all` / `plain_road` / `plan_road` —— 它们还是「**哪些战斗该打**」的判据
#       （popups 的 `offroad_fight` / `forced_fight` / `on_plan` 都靠它们）✓
#   ⚠ 想回退：把这里改成 False 即恢复原来的"规划 + 追加"行为（其余代码一行没删）
FOLLOW_PLAN_ONLY = True
# ⭐⭐⭐ 2026-10-02 用户口径：「第七张图**第一次规划完全正确**啊，为什么后面会成这样？
#   **要不改成只规划一次**」⇒ 进图算一次、**逐轮消费同一份计划**，用完才重算 ✓
#   为什么（真机铁证，第 7 张图 gui_20261002_225339）：
#     r0 规划 `5,5→4,6→3,7`（体力 7/3 步）**完全正确**；
#     r2 重算成 `4,5→3,7`、r3+ 塌成 `3,7`（一步、且那格是**雾格**）
#     ⇒ 真机连点 5 轮全 `changed:false` ⇒ `no_progress` ⇒ **stuck 退图，boss 没打** ✗✗
#   根因：每轮重解吃的都是"**模型自己以为的状态**"，那份信念每轮都在漂
#     （它以为 4,5/4,6 已消耗/已揭示）⇒ 计划越算越歪。而 solver 拿的是
#     `mark_revealed=True`（标记格当"可点"）+ boss「永不拉黑」⇒ 错误计划不会被自动纠正 ✗
#   ⚠ 代价（项目 2026-09-30 的离线对拍结论，记录在此供权衡）：每轮重解比"只规划一次"
#     省约 **9.2%**（标记可见）/ **26.1%**（标记藏在雾里）体力 —— 但那是"全知最优"口径，
#     代价是上面这种"计划塌成点雾格 ⇒ 整张图白跑（25 体力）"✗
#     ⇒ 用户 2026-10-02 拍板：**正确性优先，只规划一次** ✓
#   ⚠ 想回退：改成 False 即恢复"每轮重解、旧计划直接丢弃"。
PLAN_ONCE = True
# ⭐⭐⭐ 2026-10-02 用户口径「能省 OCR 就省」：**轮首先用图像判"有没有弹面板"**，
#   没有 ⇒ **本轮整轮不 OCR**（那一整屏 OCR 是分账里最大头：一图 10~16 次 / 13.9s）✓
#   判据 = `board_hidden(分类结果)`（dim 计数 + 最亮格阈值，≈0.5s、**0 OCR**）——
#   正是给 `panel_gone` 做过的同款"图像短路"，离线正/负样本已验（面板帧 True / 棋盘帧 False）✓
#   ⚠ 与 2026-09-25 那次回退**不是同一件事**（代码里上一条注释）：那次是**窄带读字**判面板
#     （残留面板漏看 ⇒ 对着面板乱点 ✗）；这次是**图像判棋盘有没有被挡**，方向正确 ✓
#   ⚠ 防数据陈旧：**每 ROUND_OCR_EVERY 轮**、**有面板**、**还没读到图名**时一律照旧真读
#     ⇒ 体力/槽位最多陈旧 1 轮 ✓（`ROUND_OCR_EVERY=1` 即完全回到旧行为）
ROUND_OCR_EVERY = 2
# ⭐⭐⭐⭐ 2026-10-05 **"这一帧认出来的格数下限"** —— 少于它 ⇒ 判"棋盘被面板挡住"
#   （用户报「**点开了宝库，过了会就关掉宝库了**」的真根因之一）
#   真机铁证（`runs\loop\loop_log.json` 960→966）：
#     round4：`board` **13 格**（含 `(2,6) 黄金宝库 score=1.000`）⇒ 该去买 ✓
#     round5：`board` **只剩 2 格** ⇒ `buy:0` ⇒ **退图，宝库没买** ✗
#   而 `board_hidden()` 原来只看"被压暗的格数 ≥15" —— 面板盖住时**分类器认不出几格**
#   ⇒ 那个 `n` 天然就小 ⇒ **永远判不出被挡** ⇒ 免 OCR ⇒ 面板没人处理 ✗✗
#   ⇒ 阈值取 **8**：真机干净盘 35 格、部分揭开 13~26 格、被面板遮住只剩 2 格
#     ⇒ 8 落在两簇中间；**方向安全**（多判"被挡"只是多跑一次 OCR，绝不漏面板 ✓）
BOARD_MIN_CELLS = 8
# ⭐⭐⭐ 2026-10-03 大块（声明格数 ≥4：游乐设施/巨大沙堡/海边小屋…）的**最低置信度** ✓
#   背景（朋友版 `runs/r_172006_0.png`，用户贴日志 + 给出正确计划 ✓）：
#     (1,6)/(1,7) 被认成 **S00003_331 海边小屋（9 格、战斗）**，分数只有 **0.340** ✗
#     ⇒ 每格按 9×2 = **18 体** 计价 ⇒ 两格 36 体（总价 40 ✗✗），而**它们本来是同一块** ✓
#     ⇒ 用户口径「**16 和 17 是一个格子**」+ 正确计划 `1,6 → 2,5 → 4,3 → 5,3 → 5,1`（没有 1,7 ✓）
#   规则：大块分数 < BIG_BLOCK_MIN ⇒ **按单格**处理（`cells=[自己]`、`size=(1,1)` ✓）
#     ⇒ 幻觉大块消失 ⇒ 不再被重复计价、也不再把"揭示范围"放大到远处 ✗
#   ⛔⛔ 2026-10-03 用户口径（原话）：「**别随意降门槛。我发现揭示的战斗地块分数都很低**」✗
#   ⇒ **不能用分数当"降级成单格"的门槛** —— 战斗地块（海边小屋 331 之类）**已揭示了也低分**
#     （实测 (1,6) 真块只有 0.340 ✗）⇒ 按分数降级会把**真块拆散** ✗✗
#   ⇒ 因此本机制**默认关闭**（阈值设 0 ⇒ 永不触发 ✓），只留开关与日志以备将来用真值标定 ✓
#   ⇒ (1,6)/(1,7) 那个问题的**正确修法**是"**同一块应合并成一步**"（用户：「16 和 17 是一个格子」✓）
#     而不是降级 ✗ —— 下一步按这个方向做 ✓
BIG_BLOCK_MIN = 0.0
# ⭐⭐ 2026-10-02 **改为 True**（原来一直是 False ⇒ k 恒 1.0）
#   背景：PC 端已锁定 **720×1280**（见 README §1「提速层」），但本文件主体里
#   二十几处判据仍是 **1080×1920 参考系**的常数，而 `ADAPTIVE_LAYOUT=False` 让它们
#   **一个都没缩放** ⇒ 720p 下全部错位。最先炸的是 `enter_map`：
#       `it['cy'] > LAYOUT.sy(1400)` 在 k=1.0 时要求 cy>1400，
#       而「进入地图」实测在 cy=1078 ⇒ 永远不满足 ⇒ 永远不点 ⇒ 每次都「进图失败」。
#   打开后 720×1280 恰是 1080×1920 的**纯等比 0.6667**（宽高比相同，ox=oy=0，无黑边），
#   缩放后各锚点与 `fixed.py` 的 720p 锚点**逐条吻合**（实测 sy(1618)=1079
#   == fixed.A('enter_map')=(603,1079) ✓ 两套独立实现互相印证）。
#   ⇒ **不需要去逐个改那些常数**，打开缩放即可。
ADAPTIVE_LAYOUT = True
_GRID_CALIBRATED = {'done': False}   # 棋盘自检只跑一次 ✓
LAYOUT = layout_mod.DEFAULT        # 默认 = 参考分辨率（720×1280 ✓）
# ⚠⚠⚠ 2026-10-02 修「boss 打不了」：下面这组**模块级默认值**还是 1080×1920 系
#   （FIGHT_Y=735→已折算 490 / DISPATCH_BTN=(891,1507)→(594,1005) /
#     EXPLORE_BTN=(275,736)→(183,491) ← 这条 2026-10-02 才补上）。
#   `apply_layout()`（运行时）会用 `LAYOUT.sy(REF[...])` 覆盖它们 ✓，
#   但**初始化之前**被读到就还是旧值 ⇒ 战斗按钮兜底点在 y=735（720p 上是空棋盘）
#   ⇒「战斗」点不到 ⇒ 判 not_started ⇒ 「标记格打不开」⇒ boss 永远打不了 ✗✗
#   ⇒ 现在默认就**从 layout.REF 取**（与运行时覆盖同源 ⇒ 两边永远一致）✓
_R0 = layout_mod.REF
FIGHT_Y = LAYOUT.sy(_R0['fight_y'])                       # 490
DISPATCH_BTN = LAYOUT.pt(*_R0['dispatch_btn'])            # (594,1005)
EXPLORE_BTN = LAYOUT.pt(*_R0['explore_btn'])              # (183,491)
# ⭐ 面板掉落的高价值配色（源码 AreaBlockPanel.highValueColorCode ✓）
#   顺序 = [C 绿, B 蓝, A 紫, S 橙, SS 红]；我们要的是**紫以上** ⇒ 取后三个 ✓
HIGH_VALUE_COLORS = ((0x7d, 0x58, 0xa1), (0xbf, 0x77, 0x43), (0xe5, 0x50, 0x50))


def has_high_value_drop(img, tol=26, min_px=60):
    """面板区域里有没有紫/橙/红（A/S/SS）⇒ 决定值不值得点「探索」✓

    面板一般在中部（y 600~1000），这里整屏扫（更稳 ✓），命中像素数 ≥ min_px 才算 ✓
    """
    try:
        import numpy as _np
        if img is None:
            return False
        h, w = img.shape[:2]
        band = img[int(h * 0.30):int(h * 0.60), :]
        b = band[:, :, 0].astype(_np.int16)
        g = band[:, :, 1].astype(_np.int16)
        r = band[:, :, 2].astype(_np.int16)
        for (rr, gg, bb) in HIGH_VALUE_COLORS:
            m = ((abs(r - rr) <= tol) & (abs(g - gg) <= tol) & (abs(b - bb) <= tol))
            if int(m.sum()) >= min_px:
                return True
        return False
    except Exception:       # noqa: BLE001
        return True         # 判不了就别拦（宁可点探索 ✓）

# 逐格分类器缓存（按图号；一局只建一次，约 1~2 秒）
_BOARDS = {}


def apply_layout(w, h):
    """按实际屏幕尺寸刷新所有坐标常量 ✓（1080×1920 下与旧值完全一致 ✓）

    ⚠ ADAPTIVE_LAYOUT = False ⇒ **直接返回**（不改任何东西 ✓）
      ⇒ 全部常量保持 1080×1920 原值 ⇒ 行为等于"改 720p 之前" ✓
    """
    global LAYOUT, FIGHT_Y, DISPATCH_BTN, EXPLORE_BTN
    global CLOSE_X_RIGHT, CLOSE_X_LEFT, BACK_BTN, CLOSE_TR_PT, START_ADV
    global END_ADV, ENTER_MAP, SLOTS_Y, SLOT_XS, GRID
    if not ADAPTIVE_LAYOUT:
        return LAYOUT

    # 在连接设备后调用一次即可 ✓ 之后 FIGHT_Y / DISPATCH_BTN / EXPLORE_BTN /
    # 槽位 y / 骰子区 / X 按钮位置等全部随屏幕缩放 ✓
    LAYOUT = layout_mod.Layout(w, h)
    FIGHT_Y = LAYOUT.sy(layout_mod.REF['fight_y'])
    DISPATCH_BTN = LAYOUT.dispatch_btn
    EXPLORE_BTN = LAYOUT.explore_btn
    CLOSE_X_RIGHT = LAYOUT.sx(layout_mod.REF['close_x_right'])
    CLOSE_X_LEFT = LAYOUT.sx(layout_mod.REF['close_x_left'])
    BACK_BTN = LAYOUT.pt(*layout_mod.REF['back_btn'])
    CLOSE_TR_PT = LAYOUT.pt(*layout_mod.REF['close_bag'])
    START_ADV = LAYOUT.pt(*layout_mod.REF['start_adv'])
    END_ADV = LAYOUT.pt(*layout_mod.REF['end_adv'])
    ENTER_MAP = LAYOUT.pt(*layout_mod.REF['enter_map'])
    SLOTS_Y = LAYOUT.sy(layout_mod.REF['slots_y'])
    SLOT_XS = [LAYOUT.sx(x) for x in layout_mod.REF['slots_x']]
    # ⭐ 标记识别也要自适应 ✓：尺度区间与棋盘几何同步缩放 ✓
    #   ⚠ 2026-10-02：`marks.glyph_scales()` 直接**从格距推**尺度（144⇒3.8~5.2
    #     换算成比例，96⇒2.5~3.5 ✓）。旧代码兜底取 `min/max(GLYPH_SCALES)`
    #     再乘 k，k=1.0 时**原样保留 1080p 的 3.8~5.2** ⇒ 720p 真机一个都扫不到 ✗
    try:
        import marks as _mk
        _mk.set_grid({'x0': LAYOUT.sx(layout_mod.REF['grid_x0']),
                      'y0': LAYOUT.sy(layout_mod.REF['grid_y0']),
                      'cx': LAYOUT.s(layout_mod.REF['grid_cx']),
                      'cy': LAYOUT.s(layout_mod.REF['grid_cy'])})
        # set_grid 之后按**新格距**重算尺度（k≠1 时自动跟上 ✓）
        _mk.GLYPH_SCALES = _mk.glyph_scales()
    except Exception:       # noqa: BLE001
        pass

    # ⭐ 奖励行"大拇指装备"识别也要自适应 ✓（badge 的尺度/搜索框随分辨率缩 ✓）
    try:
        import badge as _bg
        _bg.SCALE_K = LAYOUT.k
    except Exception:       # noqa: BLE001
        pass

    # 棋盘几何也同步给 spots ✓（分类器按新格距工作 ✓）
    try:
        import spots as _sp
        g = LAYOUT.grid
        # ⭐ 必须**原地更新**（explore_loop.GRID 是 spots.GRID 的别名 ✓ 重新赋值它看不到 ✗）
        _sp.GRID.update({'x0': g['x0'], 'y0': g['y0'], 'cx': g['cx'], 'cy': g['cy'],
                         'pitch': g['cx'], 'cols': g.get('cols', 7),
                         'rows': g.get('rows', 5)})
        # 再把本模块的别名重新指一次（防御 ✓）
        globals()['GRID'] = _sp.GRID
        # ⭐ 三份 GRID 必须一致 ✓（marks 是独立的一份 ✗）
        #   ⚠ 2026-10-02：这里原来**整体重新赋值** `_mk3.GRID = {4 个键}`，
        #   把 `cols`/`rows` 弄丢了 ⇒ `scan_board()` 里 `GRID['rows']` 直接
        #   **KeyError** ⇒ 每轮标记扫描都抛异常 ⇒ marked 恒空 ⇒ 「没有目标了」✗✗
        #   ⇒ 改成走 `marks.set_grid()`（原地更新、且保留 cols/rows）✓
        try:
            import marks as _mk3
            _mk3.set_grid({'x0': g['x0'], 'y0': g['y0'],
                           'cx': g['cx'], 'cy': g['cy'],
                           'cols': g.get('cols', 7), 'rows': g.get('rows', 5)})
        except Exception:       # noqa: BLE001
            pass
        # ⚠ 2026-10-02：**删掉** `_sp.SCALE = g['cx']/DESIGN_PITCH` 这行重算。
        #   它只会改 `spots.SCALE`（4.5 → 720p 下的 3.0），而 `SCALE` 在
        #   `spots.py` 里**只**用于 `Board.__init__` 的默认参数和日志打印，
        #   **不参与任何实际计算**（格距一律走 `self.px` ← `GRID['cx']`）
        #   ⇒ 留着它只会让"静态常量"和"运行时常量"两个都叫 SCALE 的值
        #      含义漂移，排查时极易被误读成"格距倍数被缩放了"。
    except Exception:       # noqa: BLE001
        pass
    return LAYOUT


def auto_calibrate_grid(b, img, mapname=None, code=None, log=None):
    """⭐ 分辨率自适应：自动检测棋盘几何并用**分类分数**标定 ✓

    · 只在一张图开始时调用一次 ✓
    · 只有新几何的识别均分**高于**当前几何才采纳 ✓（绝不退化 ✗）
    """
    try:
        import grid_detect as GD
    except Exception as e:      # noqa: BLE001
        say('   ⚠ 棋盘自检模块不可用：%r' % (e,))
        return None
    code = code or spots_mod.code_of(mapname or '夏日海滩')
    hint = dict(LAYOUT.grid)
    try:
        # 当前几何的基线分
        cur = spots_mod.Board(code, grid=hint).state(img)
        base = sorted((v.get('score') or 0) for v in (cur or {}).values())
        base = sum(base[-10:]) / max(1, len(base[-10:]))
        # ⚠ 2026-10-02：空棋盘 / 全 None 分数时 base 会是 nan，
        #   后面 `det['score'] < base + 0.10` 与 nan 比较恒 False ⇒ 可能误采纳坏几何 ✗
        if not (base == base):        # nan 兜底
            base = 0.0

        det = GD.calibrate(img, code, hint=hint)
        if not det:
            say('   ⚠ 棋盘自检失败 ⇒ 用缩放几何（x0=%d y0=%d 格距=%.1f）✓'
                % (hint['x0'], hint['y0'], hint['cx']))
            return None
        # ⚠⚠ 2026-10-02 修「棋盘自检异常：TypeError('must be real number, not NoneType)」
        #   （GUI 日志 gui_20261002_013006.log 第 11 行）。
        #   根因：**顺序错了** —— 原来先执行下一行那条 `say('… %.3f' % (det['x0'], …))`，
        #   而 `det` 里的 x0/y0/cx/cy/score **允许是 None**（被一致性闸拒绝时会填 None）。
        #   `%.3f % None` ⇒ `TypeError: must be real number, not NoneType` ✗
        #   ⇒ **先校验再格式化**：缺任何一个字段就直接判"自检没过"，走缩放几何 ✓
        #   （语义不变：本来就要 return None，只是别用异常的方式表达）
        _need = ('x0', 'y0', 'cx', 'cy')
        _miss = [k for k in _need if det.get(k) is None]
        if _miss:
            say('   · 自检未通过一致性检查（缺 %s）⇒ 保持缩放几何 ✓（x0=%d y0=%d 格距=%.1f）'
                % ('/'.join(_miss), hint['x0'], hint['y0'], hint['cx']))
            if log is not None:
                log.append({'grid_calibrate': 'rejected', 'missing': _miss})
            return None
        say('   · 棋盘自检：x0=%d y0=%d 格距=%.1f/%.1f 识别均分 %.3f（当前几何 %.3f）'
            % (det['x0'], det['y0'], det['cx'], det['cy'], det['score'] or 0, base))
        if det.get('score') is None:
            # 被一致性闸拒绝（偏差过大 / 无法评分 ✓）⇒ 保持缩放几何 ✓
            say('   · 自检未通过一致性检查 ⇒ 保持缩放几何 ✓（x0=%d y0=%d 格距=%.1f）'
                % (hint['x0'], hint['y0'], hint['cx']))
            return None
        if det.get('src') == 'rejected_shift':
            say('   · 自检结果与当前几何偏差过大（>半格）⇒ 保持缩放几何 ✓（防点击偏移 ✗）')
            return None
        # ⭐ 提升不明显也不换（避免噪声把几何带偏 ✗ 用户 2026-09-27）
        if det['score'] is None or det['score'] < base + 0.10:
            say('   · 自检提升不明显（%.3f vs %.3f）⇒ 保持缩放几何 ✓'
                % (det['score'] or 0, base))
            return None
        # 采纳 ✓
        _newg = {'x0': det['x0'], 'y0': det['y0'],
                 'cx': det['cx'], 'cy': det['cy'],
                 'pitch': det['cx'],
                 'cols': spots_mod.GRID.get('cols', 7),
                 'rows': spots_mod.GRID.get('rows', 5)}
        spots_mod.GRID.update(_newg)
        globals()['GRID'] = spots_mod.GRID
        # ⭐⭐ 2026-09-27 关键修复：marks 的 GRID 是**另一份** ✗
        #   不同步 ⇒ 标记按旧格心找、点击按新格心点 ⇒ 标记错位到别的格子 ✗✗
        #   ⚠ 2026-10-02：改走 `marks.set_grid()`（原地更新，不整体替换 dict）
        try:
            import marks as _mk2
            _mk2.set_grid(_newg)
            _mk2.GLYPH_SCALES = _mk2.glyph_scales()     # 尺度跟着新格距重算 ✓
        except Exception:       # noqa: BLE001
            pass
        try:
            _BOARDS.clear()          # 让分类器按新几何重建 ✓
        except Exception:            # noqa: BLE001
            pass
        say('   · ✓ 已采纳自检几何（x0=%d y0=%d 格距=%.1f）' % (det['x0'], det['y0'], det['cx']))
        if log is not None:
            log.append({'grid_calibrate': {'x0': det['x0'], 'y0': det['y0'],
                                           'cx': det['cx'], 'cy': det['cy'],
                                           'score': det['score'], 'base': round(base, 4)}})
        return det
    except Exception as e:      # noqa: BLE001
        say('   ⚠ 棋盘自检异常 ⇒ 继续用缩放几何：%r' % (e,))
        return None


_PLAIN_NAMES = set(getattr(tcfg_mod, 'PLAIN_NAMES', ()) or
                   ('草地', '沙地', '雪地', '岩地', '海底'))
INFER_CONSUMED = True   # ⭐ 连锁消耗反推开关（见 `_infer_chain_consumed`）


def _is_plain_cell(v):
    """这一格看起来是「可连锁的裸地」吗（营地除外；与 `mapsim.Block.plain` 同口径）"""
    nm = str(v.get('name') or '')
    if '营地' in nm:
        return False
    return nm in _PLAIN_NAMES or '草' in nm


# ⭐⭐⭐ 2026-10-01 用户口径：「勾选就主动去处理，不勾选就**拉黑**，能自由选择」
#   拉黑的地块（弹窗类特殊地块里**没勾选**的那些）在规划/点击两侧都要排除：
#     · 不是目标（`targets_cfg.is_target` 已处理 ✓）
#     · **也不能当"内容格/开路格"被点**（点一下必弹面板 ⇒ 白花一轮 ✗）
#   ⇒ 这里把它从候选池里剔掉；如果整张图的目标必须借道它，solver 会自然绕开或判定不可达 ✓
def _blocked_px(st, c):
    """本帧**被拉黑**的格子像素集合（用户：不勾 = 不碰 ✓）

    ⭐ 2026-10-02 改走 `is_blocked_cell`（带 score 门槛）：分类器**认不准**时
      不该由它替用户决定「拉黑」—— 真机 5,4 的 boss 格 0.397 分蒙成
      「金属宝箱怪」⇒ 老口径直接把它永久剔除 ⇒ 首领不打了 ✗
      （详见 `targets_cfg.is_blocked_cell` 的长注释）
    """
    out = set()
    try:
        _cells = (st.get('obs') or (c.get('st') if c else {}) or {})
        for _k, _v in _cells.items():
            if tcfg_mod.is_blocked_cell(_v):
                try:
                    out.add(marks_mod.cell_center(int(_k[0]), int(_k[1])))
                except Exception:       # noqa: BLE001
                    pass
    except Exception:       # noqa: BLE001
        pass
    return out


def _infer_chain_consumed(cells, camp_rc, seed_rc=None, log=None, tag='solver',
                          marked_rc=None):
    """⭐ 反推「已经被消耗的格」—— 含**草地连锁连带吃掉**、但从来没点过的格

    揭示律（真机实测；与 `mapsolve.Problem.block_revealed` 是同一套）：
        已揭示 ⟺ 营地格 ／ 营地 4 邻 ／ 已消耗格自身 ／ 已消耗格的 4 邻
    ⇒ **反解唯一，不用猜**：一个"亮着的草地格"若既不是营地/营地 4 邻，
      也不挨着任何已知已消耗格 ⇒ 它只可能**自己已被消耗**（否则没有任何理由亮）✓

    为什么需要（用户 2026-09-30 问的「连锁连带消掉的格」）：
        点一格草地 ⇒ 游戏把**整片连通草地**一起吃掉（`mapsim.connected_plain` 同款逻辑，
        **可穿雾**）⇒ 那些没点过的格也变成裸地；但 `st['done']` 只记了**点过的那一格** ✗
        ⇒ 下一次截图里它们被分类成"已揭示的草地"（裸地贴图 ≈ 草地）
        ⇒ 模型里留下**幻影块**：以为"这片还没点" ⇒
          ① 重复规划去点它（真机 `fogged_noop`，白耗 cold）
          ② `plain_group`/揭示范围算错 ⇒ 走法不是最优 ✗✗

    ⚠ fail-open：**找不到营地就直接放弃**（返回 seed）——否则营地 4 邻会被误判成"已消耗"，
      把整张开局的可点格全抹掉 ✗

    ⭐⭐ 2026-09-30 **实测结论：本反推对"体力"是精确中性的，别指望它省体力** ✗
      三臂同执行器对拍（离线复算 96 张 / 多目标 16 张，
      phantom=plain+absent）：
           off（只剔真点过） 体力 725 ｜ 点击 233 ｜ 空转 1 ｜ 全清 95/96
           on （本反推）     体力 725 ｜ 点击 233 ｜ 空转 1 ｜ 全清 95/96
           oracle（真值全剔） 体力 725 ｜ 点击 233 ｜ 空转 0 ｜ 全清 95/96
      连"上帝视角"都 **0 收益** ⇒ 原因：**幻影格与已消耗格在模型里同价**
      （都是空地 1 体力、都可走），且 `Problem.targets` 从不含草地
      ⇒ 幻影格永远不会被当成"要去点的目标"，只可能被当成"走过的步" ⇒ 代价恒等 ✓
      它唯一的实际价值 = **模型语义正确**（不留幻影块）+ 约 0.01 次空转/张 的点击节省。

    ⚠ 两处已知边界（都**无害**，别再当 bug 追）：
      ① **残留**：被"真点过格"的 4 邻解释掉的连锁格反推不出来（本轮观测里它已揭示、
         但仍按"邻格揭示"解释）⇒ 幻影残留约 44/102 轮。⇒ 中性（见上表）✓
      ② **误剔**：若解释者自己是被连锁吃掉、且在该口径下**不在观测里**（phantom=absent），
         它的邻格会显得"无人解释" ⇒ 被误判成已消耗。实测只发生在**单格草地**
         （`_dbg_infer3.py`：4 例全是 `组内 1 格 ｜ 组内非草地成员=[]`）⇒ 无害 ✓
         ⚠ 真机口径是 phantom=plain（消耗格被分类成草地、**在观测里**）⇒ 误剔更少 ✓
      ③ 因此 `_cells_for_model` 里**反推的格只剔它自己、绝不连带整组**
         （只有 `st['done']` 真点过的格才允许按 anchor 整块剔）：
         万一某格与多格内容块同 anchor，整块剔会把真目标删出模型 ✗✗

    ⛔⛔⛔ 2026-10-11 **修「刷了 68 张图只打 62 个首领」**（用户报，原话 ✗）
      ---- 病 ----
        本函数**只看"亮着却没人能揭示"**就判"已被连锁吃掉"（下面那句），
        **完全没看这一格有没有内容标记** —— 函数体里 `marks` 出现 **0 次** ✗
        ⇒ 把**带 boss 标记**的格也当成"被吃掉的裸地"剔出模型 ✗✗
        真机铁证（`runs/acc1/loop/loop_log.json` #266~#294，同一张图）：
            #266 mark_floor_veto        : ["2,2", false, true, 0.834, 209.5]
            #267 chain_consumed_inferred: cells ["2,2"]      ← **误剔 boss 格** ✗
            #273 done_cells_dropped     : cells ["2,2"]
            #275 solver ok order ["3,2","4,1"]               ← 计划里**没有** 2,2 ✗
            #277 board marks {"2,2": ["boss"]}               ← boss 标记还在 ✗
            #293 stuck_why targets_unreachable  marked_n 1
            #294 finish targets_unreachable  ⇒ **退图，boss 没打** ✗✗
      ⇒ 全盘复算：68 张图里 **正好 6 张**是这种（用户看到的 68-62=6 **完全对上** ✓）
        那 6 张的 `in_map_secs` 都极短（7.6~39.6 秒）⇒ 才开局就判"没目标"退图 ✗
      ---- 为什么原判据在逻辑上就错 ----
        游戏里**连锁只吃"普通空地"**（`SpecialSpot==0` 的连通片，见数据表规则）✓
        ⇒ 带**内容标记**的格（boss/宝箱/幸运草/红装/大拇指…）**不可能**是
          "被连锁吃掉的裸地" ✗ ⇒ 反推时**必须跳过它们** ✓
      ---- 修法 ----
        加参数 `marked_rc`：调用方把"有标记的格"传进来，
        反推循环里**命中就跳过**（既不进 `consumed`、也不进 `odd`）✓
        ⚠ **fail-open**：`marked_rc` 传 None/空 ⇒ 行为**与修前完全一致**
          （不改变任何既有测试的期望 ✓）
        ⚠ 只跳过**有标记**的格；真·空地（无标记）照旧反推 ⇒ 不影响本函数的原有效用 ✓
    """
    seed = set(seed_rc or ())
    if not INFER_CONSUMED:
        return seed
    if not camp_rc:
        return seed
    try:
        rows, cols = int(GRID['rows']), int(GRID['cols'])
        camp = (int(camp_rc[0]), int(camp_rc[1]))

        def nbrs(rc):
            r, c = rc
            return {(r + dr, c + dc) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    if 1 <= r + dr <= rows and 1 <= c + dc <= cols}

        # 亮着的格（`_from_mark` 是"雾中标记格被强行当已揭示"喂进模型的，不算观测 ✓）
        R = {k for k, v in cells.items()
             if v.get('revealed') and not v.get('_from_mark')}
        covered = {camp} | nbrs(camp)
        consumed = set(seed)
        for x in consumed:
            covered.add(x)
            covered |= nbrs(x)
        odd = []
        _mk = set(marked_rc or ())       # ⭐ 有内容标记的格（不许被反推成"已消耗" ✓）
        _skip_marked = []
        for _ in range(rows * cols + 2):
            rest = sorted(R - covered)
            if not rest:
                break
            x = rest[0]
            # ⛔⛔ 2026-10-11 **跳过带标记的格**（治「68 张图只打 62 个首领」✗）
            #   理由：游戏里连锁**只吃普通空地** ⇒ 带标记的格（boss/宝箱/…）
            #   **不可能**是"被吃掉的裸地" ⇒ 判它"已消耗"必是误判 ✗
            #   ⚠ 既不进 `consumed`、也不进 `odd`（它本来就该被正常揭示/去点 ✓）
            if x in _mk:
                _skip_marked.append(x)
                covered.add(x)
                covered |= nbrs(x)
                continue
            if _is_plain_cell(cells.get(x) or {}):
                consumed.add(x)      # 亮着 + 没人能揭示它 ⇒ 只能是自己已被消耗 ✓
            else:
                odd.append(x)        # 非草地却亮着 ⇒ 本律解释不了，**别动它**（只记日志）
            covered.add(x)
            covered |= nbrs(x)
        if log is not None:
            if _skip_marked:
                log.append({tag: 'chain_infer_skip_marked', 'n': len(_skip_marked),
                            'cells': ['%d,%d' % k for k in sorted(_skip_marked)[:12]],
                            'note': '带标记格**不参与**连锁消耗反推（连锁只吃空地 ✓）'})
            _extra = consumed - seed
            if _extra:
                log.append({tag: 'chain_consumed_inferred', 'n': len(_extra),
                            'cells': ['%d,%d' % k for k in sorted(_extra)[:12]]})
            if odd:
                log.append({tag: 'revealed_unexplained', 'n': len(odd),
                            'cells': ['%d,%d' % k for k in odd[:8]]})
        return consumed
    except Exception:       # noqa: BLE001
        return seed


def _cells_for_model(st, c, log=None, tag='solver', mark_revealed=True,
                     drop_done=True):
    """⭐ 2026-09-28 抽公共：给模型（MapSim.from_observation）用的「观测合并」
    （solver_order / eff_order **共用这一份**，防止两处漂移 —— 参照 _fix_blank_cost_1
    只改 mapsolve 漏 mapsim 的教训 ✓）

    · `c['st']`（分类器格）∪ `st['marks']`（标记扫描）—— 标记优先 ✓
    · 有标记但分类器没给出的格补进去（认不出 ⇒ mark='battle' 兜底 ✓）
    · mark_revealed：
        True（solver 默认，保持原行为）—— 标记格当"可点"喂给 mapsolve
        （mapsolve 需要目标可达才求解；真机点不动由 nochange 兜底 ✓）
        False（**eff 必须用**）—— 雾中标记格保持"可见但不可点"：
        2026-09-28 离线验证抓到：True 时 EffPolicy 推演盘一步把雾中 boss/商人
        "消耗掉" ⇒ targets 丢方向、真机执行全是 fogged noop ⇒ 空转 ✗✗

    ⭐⭐⭐ 2026-09-30 两处关键修正（离线 `_bench_online.py` 80 张盘对拍，见当日日报）：
    ① **剔除已消耗格**（`drop_done`）：
         已消耗的格在地图上已经空了，但地块分类器照样会给它一个 top1（裸地 ≈ 草地贴图）
         ⇒ `from_observation` 会为它建一个**幻影空地** ⇒ 模型以为"这里还没走过"
         ⇒ `mapsolve.Problem.visible()` 只剩「营地四邻」⇒ **每轮规划都从营地重新起步**、
           走法必然不是最优，还会把已走过的格再排进计划（真机 `fogged_noop`）✗
         ⚠ 必须**按 anchor 整块剔**：真机只 tap 了块里的一格，`done` 也只记那一格，
           只剔那一格会把多格块剩下的成员留成"幻影块" ✗
      ② **补 `target` 字段**：`targets_cfg` 白名单（用户 2026-09-28 明确要求
         「勾选某一种类型的方块，后续就专门去拿那个方块」）此前**只在文件头 import、
         全文件从未调用** ⇒ 喂给求解器的 cells 里没有 `target` ⇒ `Block.want` 恒 None
         ⇒ `Problem.targets` 永远退回 `mark ∪ is_buy` 老口径
         ⇒ **紫橙探索格(221/321/331) 与用户勾选的类型压根不进规划** ✗
    """
    _mk_all = st.get('marks') or {}
    _cells_merged = {}
    # ⭐⭐⭐ 2026-10-01 修「规划很差劲」：模型输入的底子换成**跨轮累积观测** `st['obs']`
    #   （见 one_round 里 obs_merge 的注释）。原来直接用 `c['st']`＝**单帧**分类 ⇒
    #   面板/动画/加载那一帧认不到的格会从模型里消失 ⇒ 求解器以为要重新开路
    #   ⇒ cost 乱跳（真机 17:10~17:12 同一张图：2 → 17 → 7 ✗）。
    #   `st['obs']` 只增不减（已揭示永不翻回）⇒ 模型永不会"忘掉"走过的地方 ✓
    #   没有 obs（首轮/退化）时自然回落到本帧 `c['st']` ✓
    _base_cells = st.get('obs') or (c.get('st') or {})
    for _k, _v in _base_cells.items():
        _vv = dict(_v)
        _mlist = list((_mk_all.get(_k) or {}).get('marks') or [])
        # ⭐⭐ 2026-09-27 用户口径：「我认不出来的那几个就是战斗格」✓
        if _mlist:
            _vv['marks'] = _mlist
        # ⭐⭐⭐ 2026-09-28 二次修正（用户真机报「被宝箱隔断的草地被当连通」）：
        #   此处曾有 `score>=0.8 ⇒ revealed=True` —— **错误，已撤回**。
        #   分类器能"看穿雾"：雾格也拿 score 0.91（ratio 0.65）⇒ 该规则把**雾格**
        #   翻成"已揭示草地" ⇒ plain_group 穿雾假连通 ⇒ 规划认为能连锁 ✗。
        #   正确语义：**ratio 是"揭示状态"的唯一可靠信号**
        #   （雾 ratio≈0.65 vs 已揭示 ~1.0，干净间隔）；score 只说明"底下是什么"。
        #   首帧暗罩（全盘 ratio 被进图动画压到 0.65）的正确修法 =
        #   **进图后等暗罩散去再识别**（见 enter_map 的 _wait_fog_clear ✓）。
        _cells_merged[_k] = _vv
    # ⭐⭐⭐⭐ 2026-10-05 **揭示判据统一到 `REVEAL_RATIO_MIN`，且必须在这里就生效**
    #   （`_infer_chain_consumed` 紧跟着就要用 `revealed` ⇒ 晚了就来不及 ✗）
    #   真机铁证（acc2 13:53 第 7 张，`runs/acc2/r_135345_0.png`）：
    #     分类器 `spots` 的揭示判据是**自适应**的 `ratio ≥ max(0.66, 第10分位×1.06)`，
    #     那张盘算出阈值 ≈0.66 ⇒ 9 个 **ratio=0.672 的雾格**被判成"已揭示" ✗
    #     ⇒ `_infer_chain_consumed` 把"亮着却无人能解释"的它们反推成**已被连锁吃掉**
    #       （日志 `chain_consumed_inferred n=9`）⇒ 这 9 格被剔出模型 ⇒ 它们变成
    #       `board=-1`（= 模型眼里的"已消耗格"）⇒ `visible()` 把它们的 4 邻判成"已揭示"
    #     ⇒ **深雾里的 boss 块 (5,1)(5,2) 被算成可点** ⇒ 计划 = `[(5,1)]`
    #     ⇒ 真机点它没有任何反应（雾格）⇒ 计划一步摘光 ⇒ stuck、25 体力白花 ✗✗
    #   ⇒ 现在：**建完模型立刻按 ratio 纠正 revealed**（与规划/执行期同一个常量 ✓），
    #     下面的反推就只会认"真的亮着"的格 ⇒ 不再凭空造出"已消耗格" ✓
    try:
        for _k3, _v3 in _cells_merged.items():
            _rr3 = _v3.get('ratio')
            if _rr3 is not None:
                _v3['revealed'] = bool(float(_rr3) >= float(REVEAL_RATIO_MIN))
    except Exception:               # noqa: BLE001
        pass
    # ⭐⭐ 2026-09-27：**有标记但分类器没给出**的格子必须补进模型 ✓
    #   （实测 boss 格 (1,6) 六轮 board 全是 None ✗ 但标记看得到 ✓）
    for _k, _m in _mk_all.items():
        if _k in _cells_merged:
            continue
        _ml = list(_m.get('marks') or [])
        if not _ml:
            continue
        _cells_merged[_k] = {'sid': None, 'name': None, 'marks': _ml,
                             'revealed': mark_revealed,
                             'ratio': None, 'score': None, '_from_mark': True}
        if 'battle' not in _cells_merged[_k]['marks']:
            _cells_merged[_k]['marks'].append('battle')   # 认不出 ⇒ 当战斗格 ✓
        if log is not None:
            log.append({tag: 'mark_cell_added', 'cell': '%d,%d' % _k,
                        'marks': _ml})
    # ⭐⭐⭐⭐ 2026-10-05 **带标记的格子：由"地板"说了算，`ratio` 不算数**
    #   （用户原话：「**为什么在废弃矿洞的规划错得离谱，在夏日海滩的就是对的**」／
    #     「**可能不是求解器的问题？是识别的问题？**」⇒ 就是识别 ✓ 求解器只是忠实执行）
    #   真机铁证：`runs/acc2/r_145056_0.png`（废弃矿洞 14:50）
    #     · `(2,1)` 上画着 **boss 标记**，`ratio = 1.019` ⇒ 被判"已揭示" ⇒ 求解器拿它
    #       当**第一步**去点 ⇒ 真机 `give_up_step`（点不动）⇒ 计划 `2,1 → 3,3 → 3,4 → 5,1`
    #       全是建立在"点 (2,1) 会连锁揭格"这个假前提上 ⇒ **4 次点击全废、18.4 秒白跑** ✗✗
    #     · 而"地板"（四角最暗，`spots._floor_luma`）实测 `(2,1)=65` = **本帧纯雾基准**
    #       （同帧真已揭示格 83~98）⇒ 一眼就是雾 ✓
    #   为什么只给**带标记**的格子加这条（不整盘改用地板法）：
    #     · 游戏**会在雾格上叠标记图标**提示"这里有个首领/幸运草"（本仓 737 行那段教训
    #       已写明）⇒ **有标记 ≠ 已揭示**；而图标正好压在 `ratio` 的**分子**里
    #       （中心 60×60 均值）⇒ 标记格正是 `ratio` 最不可信的那一类 ✓
    #     · 标记格还有**反方向**的坑（`runs/r_155829_0.png`：格子真的亮着、上面叠了
    #       boss+大拇指两个图标，`ratio=0.708` 被判雾 ⇒ 计划打不开首领）⇒ 地板法救回来 ✓
    #   ⇒ 对**有标记**的格子：`revealed = 地板亮不亮`（`spots` 两趟法算好的 `floor_lit` ✓）
    #   ⚠ **没有标记的格子一条都不动**（`ratio` 两趟法照旧）⇒ 不动那 1068 格标定的口径 ✓
    _flip = []
    try:
        for _k4, _v4 in _cells_merged.items():
            if not (_v4.get('marks') or _v4.get('_from_mark')):
                continue
            _fl4 = _v4.get('floor_lit')
            if _fl4 is None:
                continue                     # 没有地板信息 ⇒ 不猜，保持 ratio 的结论 ✓
            _was4 = bool(_v4.get('revealed'))
            _v4['revealed'] = bool(_fl4)
            if _was4 != bool(_fl4):
                _flip.append((_k4, _was4, bool(_fl4), _v4.get('ratio'), _v4.get('floor')))
    except Exception:               # noqa: BLE001
        pass
    if _flip and log is not None:
        try:
            log.append({tag: 'mark_floor_veto', 'n': len(_flip),
                        'flips': [['%d,%d' % k, a, b, r, f] for k, a, b, r, f in _flip],
                        'note': '带标记的格子改用"地板"判揭示'
                                '（ratio 被图标抬高/压低都不可信 ✓）'})
        except Exception:           # noqa: BLE001
            pass
    # ---- ⭐⭐⭐ 2026-10-01 用户报「点了金属宝箱怪（说了不点的）」----
    #   根因：`_blocked_px` 只把拉黑格从 `nones_extra`（内容格/开路池）剔掉了，
    #   但**规划器（solver/eff）喂进去的 cells 里没剔** ⇒ 它照样把宝箱怪排进点序 ✗
    #   （真机铁血高地实证：规划 `['3,2','2,4','2,5']` 第一步 3,2 就是宝箱怪，
    #     点完弹面板、白转 26 秒 ✗）
    #   ⇒ 现在：**拉黑格留在模型里，但标记为"blocked"且强制非目标**（不再 pop ✗ ——
    #     见下面 v0.99 的说明：pop 会让它变成 `board < 0` = 模型眼里的"已消耗空地"，
    #     于是拉黑格被当成**能连锁穿过的空地**，规划整条走法都错 ✗✗）
    try:
        _blk_rc = set()
        for _k2, _v2 in list(_cells_merged.items()):
            # ⭐ 2026-10-02：带 score 门槛（`is_blocked_cell`）——
            #   分类器 0.3 分的乱猜**没有资格**把 boss 格判成「用户拉黑」
            if tcfg_mod.is_blocked_cell(_v2):
                _blk_rc.add(_k2)
        if _blk_rc:
            for _k2 in _blk_rc:
                _v2 = _cells_merged.get(_k2) or {}
                _v2['blocked'] = True
                _v2['target'] = False        # ⭐ 双保险：目标白名单里也不许有它 ✓
            if log is not None:
                log.append({tag: 'blocked_cells_tagged', 'n': len(_blk_rc),
                            'cells': ['%d,%d' % k for k in sorted(_blk_rc)[:12]]})
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐ 2026-10-01 v0.99 用户报「最近一次规划很差啊，**是把拉黑的看成能连锁了**？」
    #   —— 用户猜对了，就是我们自己引入的：
    #   v0.94 的修法是**把拉黑格从 `_cells_merged` 里 pop 掉**（防 solver 点它）。
    #   但 pop 掉 ⇒ `MapSim.from_observation` 不给它建块 ⇒ `board[cell] = -1`，
    #   而 `mapsolve.Problem.consumed_cells()` 把 **`board < 0` 一律当"已消耗的格"**
    #   （那是 2026-09-30 为"已经走出去的地图"补的 F3 语义），并且
    #   `block_revealed()` 里"与任一已消耗格 4 邻接 ⇒ 该块已揭示"也走这条
    #   ⇒ 后果三条，全是"规划很差"的直接来源：
    #     ① 拉黑格被当成**空地** ⇒ 相邻的**雾格**被判"已揭示/可点" ⇒ 计划里出现点不动的格 ✗
    #     ② 连通空地的**连锁**会**穿过**这个洞 ⇒ 体力/步数被严重低估（= 用户说的"看成能连锁"）✗
    #     ③ `_build_cache` 的 `EMPTY_ADJ`（可点集合）也把它算进去 ⇒ 可见范围虚高 ✗
    #   ⇒ 正确语义：拉黑格 = **一个不可点的普通内容格**（游戏里它同样**阻断连锁穿透** ✓）
    #      · 留在模型里 ⇒ `board >= 0` ⇒ 不是"已消耗" ⇒ 不参与连通/连锁 ✓
    #      · `target=False` + 非 plain（宝箱怪/预言石碑的 SpecialSpot>0 ✓）⇒ solver 不会去点它 ✓
    #      · 启发式点序里仍由 `_blocked_px` 排除（v0.94 那一层保留 ✓）
    # ---- ⭐ 2026-09-30 ①：剔除已消耗的块（按 anchor 整块剔） ----
    # `_seed_rc` = **真点过**的格（`st['done']`，真机只在 act∈{battle,battle_clear,
    #   handled} 或 商人/营地/预言石板 时写入）⇒ **高可信** ⇒ 允许按 anchor 整块剔
    # `_infer_rc` = 反推出来的**草地**格（连锁连带吃掉、从没点过）⇒ **只剔它自己**，
    #   ⚠ 绝不允许它连带剔掉整组 —— 万一它跟某个多格内容块同 anchor，
    #   整块剔会把**真目标**从模型里删掉（计划里再也不去拿）✗✗
    _seed_rc = set()
    _infer_rc = set()
    _done_rc = set()
    if drop_done:
        for _px in (st.get('done') or ()):
            try:
                _seed_rc.add(cell_of(_px[0], _px[1]))
            except Exception:           # noqa: BLE001
                pass
        _done_rc = set(_seed_rc)
        # ⭐⭐ 2026-09-30 补：`st['done']` 只记**点过**的格；草地连锁连带吃掉的格不在里面
        #   ⇒ 反推它们（见 `_infer_chain_consumed`）并一起剔 ✗→✓
        try:
            _camp_rc = None
            _sp = st.get('spawn') or st.get('camp')
            if _sp:
                _camp_rc = cell_of(_sp[0], _sp[1])
            if _camp_rc is None:
                for _k2, _v2 in _cells_merged.items():
                    if '营地' in str(_v2.get('name') or ''):
                        _camp_rc = _k2
                        break
            # ⭐⭐⭐ 2026-10-11 **把"有标记的格"传进去**（治「68 张图只打 62 个首领」✗）
            #   带标记的格不可能"被连锁吃掉" ⇒ 反推时必须跳过 ✓
            #   ⚠ 取**所有**标记（不只 boss）：宝箱/幸运草/红装/大拇指/推荐 都一样 ✓
            #   ⚠ 从 `st['obs']` 的 marks 取（那是分类器的原始标记 —— 与
            #     `mk`/`marked` 同源，但这里**只读不写** ⇒ 不影响别的链 ✓）
            _marked_rc = set()
            try:
                for _rk, _rv in (st.get('obs') or {}).items():
                    _ml = (_rv or {}).get('marks') or []
                    if not _ml:
                        continue
                    # ⚠ `obs` 的键是 **(r,c) 元组**，不是 '2,2' 字符串
                    #   （铁证：`cell_of` 的文档写着 `'st': {(r,c): {...}}` ✓）
                    #   ⇒ 两种都容错（元组优先，字符串兜底 ✓ 防以后改口径 ✗）
                    if isinstance(_rk, tuple) and len(_rk) == 2:
                        _marked_rc.add((int(_rk[0]), int(_rk[1])))
                    else:
                        _rr2, _cc2 = str(_rk).split(',')
                        _marked_rc.add((int(_rr2), int(_cc2)))
            except Exception:               # noqa: BLE001
                pass
            _done_rc = _infer_chain_consumed(_cells_merged, _camp_rc,
                                             seed_rc=_seed_rc, log=log, tag=tag,
                                             marked_rc=_marked_rc)
            _infer_rc = _done_rc - _seed_rc
        except Exception:               # noqa: BLE001
            pass
    _grp = {}
    # ⭐⭐⭐ 2026-10-02 **营地格先认出来**（用户口径：「营地最好认、恒已揭示 ⇒ 先固定下来」）
    #   为什么必须在剔除之前算：循环侧为了避免点出生点，把营地像素加进了 `done`
    #   （`done.add(camp_px)`，见「优化掉多余点击」那段）⇒ 下面"在 done 里的格整块剔掉"
    #   会把**营地连同它所在的多格块**（真机是 4 格块 `巨大沙堡`）一起删出模型 ✗
    #   ⇒ 我写在保留分支里的 `camp=True` 标记**根本没机会执行** ⇒
    #     `Problem.camp=None` ⇒ 揭示链没有起点 ⇒ 求解器把雾格当可点 / 或 `exhausted`
    #     （真机 00:09 那把铁证：`done_cells_dropped: [1,1,2,1,2,2,2,3]` 正好是整个沙堡块）
    #   ⇒ 现在：**营地格豁免这次剔除**，并带上 camp 标记 ✓
    _camp_rc = None
    try:
        _cp0 = st.get('spawn') or st.get('camp')
        if _cp0:
            _camp_rc = tuple(cell_of(_cp0[0], _cp0[1]))
    except Exception:               # noqa: BLE001
        _camp_rc = None
    for _k, _v in _cells_merged.items():
        _a = tuple(_v.get('anchor') or _k)
        _grp.setdefault(_a, []).append(_k)
    _out = {}
    _dropped = []
    _gold_off = []      # ⭐ 2026-10-06：金币不足 ⇒ 被按掉 target 的商人/宝库格（见下面那段）
    _mimic_off = []     # ⭐ 2026-10-09：幸运草<10 ⇒ 被按掉 target 的宝箱怪格（同上 ✓）
    for _a, _mem in _grp.items():
        if _seed_rc and any(m in _seed_rc for m in _mem):
            # ⭐ 营地所在的块：**豁免剔除**（否则模型没有揭示起点 ✗）✓
            if _camp_rc is not None and _camp_rc in _mem:
                if log is not None:
                    log.append({tag: 'camp_block_kept', 'camp': '%d,%d' % _camp_rc,
                                'block': ['%d,%d' % m for m in _mem[:6]],
                                'note': '营地所在块豁免剔除（否则模型没有揭示起点）'})
            else:
                _dropped.extend(_mem)   # 真点过 ⇒ 整块剔（真机口径：块里被点掉一个就没了）
                continue
        for _k in _mem:
            if _k in _infer_rc:         # 反推命中 ⇒ **只剔这一格**（绝不连带）✓
                _dropped.append(_k)
                continue
            _vv = dict(_cells_merged[_k])
            # ---------------------------------------------------------------
            # ⭐⭐⭐ 2026-10-02 修「规划去点雾格 ⇒ 连点 5 轮 no-op ⇒ stuck 退图」
            #   （真机铁证：第 7 张图 `gui_20261002_225339` / `loop_log` #260→#317）
            #   根因 = **分类器 `spots` 的揭示判据是自适应的**：
            #       `revealed ⟺ ratio ≥ max(0.66, 第10分位×1.06)`
            #     那张盘上算出阈值 **0.675**，而 boss 格 (3,7) 的 ratio = **0.678**
            #     ⇒ **只差 0.003** 就被判成"已揭示" ✗
            #     ⇒ 模型以为 boss 已亮 ⇒ `Problem.visible()` 含它 ⇒ 计划"直接点它"
            #     ⇒ 真机是雾格、`changed:false` ⇒ 连点 5 轮 ⇒ `no_progress` ⇒ **boss 没打就退图** ✗✗
            #   ⇒ 这里统一改用**本文件自己的口径** `REVEAL_RATIO_MIN = 0.75`
            #     （它的注释写明"已揭示 ≈1.0 / 未揭示 ≈0.65"，与 `spots`/`vault_probe_px` 同源）：
            #     只信 `ratio ≥ 0.75`，**不信**分类器那个自适应 flag ⇒ 0.678 正确判成未揭示 ✓
            #   ⚠ 方向安全：把"其实已亮但偏暗"的格当未揭示 ⇒ 最多多规划一步"点它"
            #     （点已亮的格 = 正常消耗、有进展）；反过来（把雾格当已亮）才会死锁 ✗
            #   ⚠ 只覆盖**能读到 ratio 的格**；`ratio=None`（标记补格等）保持原值 ✓
            try:
                _rr = _vv.get('ratio')
                if _rr is not None:
                    _vv['revealed'] = bool(float(_rr) >= float(REVEAL_RATIO_MIN))
            except Exception:           # noqa: BLE001
                pass
            # ⭐⭐⭐⭐ 2026-10-05 **这里也要过一遍"带标记 ⇒ 由地板说了算"**（用户报矿洞规划离谱）
            #   ⚠ 上面那句 `ratio >= REVEAL_RATIO_MIN` 是**最后一道覆写** ⇒ 会把更早那次
            #     `mark_floor_veto` 冲掉 ✗（我第一次就栽在这：veto 日志有了、模型里还是 true）
            #     ⇒ 判据只此一处生效：**有标记 ⇒ 看地板**；没标记 ⇒ 看 ratio ✓
            #   真机铁证见 `spots._floor_luma` / `mark_floor_veto` 两处注释（矿洞 14:50 的
            #     `(2,1)`：ratio 1.019 但四角地板 65 = 纯雾基准 ⇒ 真机点不动 ✗）
            if _vv.get('marks') or _vv.get('_from_mark'):
                _fl5 = _vv.get('floor_lit')
                if _fl5 is not None:
                    _vv['revealed'] = bool(_fl5)
            # ---- ⭐⭐⭐ 2026-10-02 **拆掉"误并的多格块"**（用户给的地面真值定案）----
            #   用户报「规划错了」那把（runs/r_000926_0.png），地面真值是：
            #       (1,1)=**空地**   (2,1)=**出生地(营地)**   (2,2)=**海螺**   (2,3)=空地
            #   而分类器把这 4 格**并成一个「巨大沙堡」S00003_211**（anchor=(1,1)）✗✗
            #   离线铁证（字段级自相矛盾）：每格的 `score` **恰好等于它自己单格候选 top1 的分**，
            #       而 `sid/name/anchor` 却来自多格分组 ⇒ 「分是单格的、名字是整块的」
            #       1,1: score 0.998 = top1 0.998 S00003_001(空地)   但 sid 写成 S00003_211
            #       2,1: score 1.000 = top1 1.000 S00003_000(营地)   但 sid 写成 S00003_211
            #       2,2: score 0.764 = top1 0.764 S00003_002(海螺)   但 sid 写成 S00003_211
            #       2,3: score 0.994 = top1 0.994 S00003_001(空地)   但 sid 写成 S00003_211
            #   ⇒ 规则：**本格 top1 的 sid 与分组 sid 不同、且 top1 分不低于分组分 ⇒ 以单格为准**
            #     （把 anchor 改回自己 ⇒ 该格从多格块里**拆出来当独立块**）✓
            #   为什么必须修：营地被吞 ⇒ `Problem.camp=None` ⇒ 揭示链没起点 ⇒
            #     幻影消耗 + 把雾格判成可点 ⇒ 计划点雾格空转（整条因果链的唯一根因）✗✗
            #   ⚠ 只作用于**喂给求解器的模型**（有日志可审），不动分类器本身 ✓
            #   ⭐⭐⭐ 2026-10-03 **收窄这条规则**（我 10-02 加的拆块，今天反过来咬了一口 ✗）
            #   真机事故（acc1 gui_20261003_140308 第 2 张图，用户：「为什么还是要去打战斗格子？这样不是会贵吗」）：
            #     合并模型里 `(2,6)` 被拆成 **S00003_011 勇者之墓（score 0.445）** ✗，
            #     而**分组 sid 本来是对的** `S00003_111 海边杂物`（且 (2,6)(3,6)(3,7) 真的
            #     有 3 格同型 ✓ 是真块 ✓）—— 因为两侧**分数相等**（都 0.445）⇒ 旧规则照拆 ✗✗
            #     后果：勇者之墓是"特殊面板格、不打架"⇒ 该格被定价 **1 体**（战斗应 6 体 ✗）
            #     ⇒ 模型以为"打架不要钱" ⇒ 放着绕路(12 体)不走、偏走打架那条(8 体) ✗✗
            #   ⇒ 拆分的目的**只是**"把营地/空地/海螺从误并的多格块里救出来"（见上面 10-02 的
            #     那 4 格真值 ✓）⇒ 只有"本格 top1 是**空地系/营地**"时才允许拆 ✓
            #     （同分/异型的多格互换一律不拆 ⇒ 保住分组原判 ✓）
            try:
                _tp = list(_vv.get('top') or [])
                if _tp:
                    _t0 = _tp[0]
                    _ts, _tsid = float(_t0[0]), str(_t0[1] or '')
                    _gs = float(_vv.get('score') or 0)
                    _gsid = str(_vv.get('sid') or '')
                    _tname = ''
                    try:
                        _tname = str(((spots_mod.spot_rows() or {}).get(_tsid) or {})
                                     .get('Name') or '')
                    except Exception:       # noqa: BLE001
                        _tname = ''
                    # ⛔⛔ 2026-10-03 **本条已回退**（试过"按分数严格判定 ⇒ 拆"，副作用大 ✗）：
                    #   改成 `_ts > _gs + 0.02` 之后，`r_184822_0.png` 那盘的求解器直接
                    #   **`exhausted`（无解、计划空）** ✗ —— 因为拆出来的 `211 巨大沙堡`
                    #   是"非空地且未揭示"⇒ 连锁链被切断 ⇒ 求解器找不到去目标的路线 ✗✗
                    #   ⇒ 「把混并块拆开」这件事**必须和"保守连锁 + 可达性"一起改** ✓
                    #     （单独改任何一头都会坏 ✓）⇒ 留到下一轮做整体方案 ✓
                    #   现已恢复成"救空地/营地/海螺"这条**已知安全**的口径 ✓
                    _rescue = (is_plain_spot(_tsid)
                               or _tname in ('营地', '海螺')
                               or str(_tsid).endswith('_000'))
                    if (_tsid and _tsid != _gsid and _ts >= _gs - 1e-6 and _rescue):
                        _vv['sid'] = _tsid
                        try:
                            _row_nm = (spots_mod.spot_rows() or {}).get(_tsid) or {}
                            if _row_nm.get('Name'):
                                _vv['name'] = _row_nm['Name']
                        except Exception:       # noqa: BLE001
                            pass
                        _vv['anchor'] = tuple(_k)   # ⭐ 拆出：自己是锚点 ⇒ 独立单格块 ✓
                        _vv['_split'] = True
                        if log is not None:
                            log.append({tag: 'cell_split_from_block',
                                        'cell': '%d,%d' % tuple(_k),
                                        'was': _gsid, 'now': _tsid,
                                        'score': round(_ts, 3),
                                        'note': '分组 sid 与单格 top1 矛盾 ⇒ 以单格为准（拆出独立块）'})
            except Exception:               # noqa: BLE001
                pass
            # ---- ⭐⭐⭐ 2026-10-03 **大块必须高分，否则按单格**（用户口径：给出正确计划 ✓）----
            #   真机事故（朋友版 `runs/r_172006_0.png`，用户贴的日志 + 用户给的正确计划 ✓）：
            #     求解器计划 = `1,6 1,7 2,5 4,3`，其中
            #       (1,6) 与 (1,7) 都被认成 **S00003_331「海边小屋」（9 格、EventNum 9-9 ⇒ 战斗）**
            #       分数只有 **0.340** ✗ ⇒ 每格按 9×2 = **18 体** 计价 ⇒ 两格 36 体（总价 40 ✗✗）
            #     而且两个"9 格块"分别锚在 (1,6)/(1,7) ⇒ **几何上互相重叠** ⇒ 显然是同一个幻觉 ✗
            #     用户给的**正确计划** = `1,6 → 2,5 → 4,3 → 5,3 → 5,1`（**没有 1,7** ✓）
            #   ⇒ 规则：**声明格数 ≥ 4 的大块**（游乐设施/巨大沙堡/海边小屋…）必须
            #     `score ≥ BIG_MIN(0.55)` 才认；否则**按单格**处理（cells=[自己]、size=1 ✓）
            #     ⇒ 幻觉大块消失 ⇒ 不再被重复计价、也不会把"揭示范围"放大到远处 ✗
            #   ⚠ 为什么门槛是 0.55：本仓实测 5 格「游乐设施」真块只有 0.489~0.559 ✗
            #     ⇒ 门槛不能高于 0.55（否则真块也被降级 ✗）；而 0.340 这种必然被降 ✓
            try:
                # ⚠ 判据要用**数据表声明的格数**（`SpotSize`），不是"观测到几格" ✗
                #   （这两格观测各只看到 1 格 ⇒ 用观测格数永远 <4 ⇒ 我第一版就没命中 ✗✗）
                _sid_d = str(_vv.get('sid') or '')
                _tbl_sz = 1
                try:
                    _tbl_sz = int(((spots_mod.spot_rows() or {}).get(_sid_d) or {})
                                  .get('SpotSize') or 1)
                except Exception:       # noqa: BLE001
                    _tbl_sz = 1
                _sz_claim = _vv.get('size')
                _n_claim = 1
                if isinstance(_sz_claim, (tuple, list)) and len(_sz_claim) == 2:
                    _n_claim = int(_sz_claim[0]) * int(_sz_claim[1])
                _n_claim = max(_n_claim, len(list(_vv.get('cells') or [])), _tbl_sz)
                if _n_claim >= 4 and float(_vv.get('score') or 0) < BIG_BLOCK_MIN:
                    _vv['cells'] = [tuple(_k)]
                    _vv['size'] = (1, 1)
                    _vv['block_score'] = None
                    _vv['_big_demoted'] = True
                    # ⚠⚠ 关键：`mapsim.Block.size` 读的是 **`SpotSize`**（数据表值 ✓），
                    #   不是这里的 `size` 元组 ✗ ⇒ 不一起改的话，模型仍按 9 格 ×2 = 18 体
                    #   计价（我第一版就漏了这一步 ⇒ 复算出来计划一点没变 ✗✗）
                    _vv['SpotSize'] = 1
                    if log is not None:
                        log.append({tag: 'big_block_demoted',
                                    'cell': '%d,%d' % tuple(_k),
                                    'sid': str(_vv.get('sid') or ''),
                                    'score': round(float(_vv.get('score') or 0), 3),
                                    'claimed_cells': _n_claim,
                                    'note': '大块但分数 < %.2f ⇒ 按单格处理（防 18 体幻觉 ✗）'
                                            % BIG_BLOCK_MIN})
            except Exception:               # noqa: BLE001
                pass
            # ---- ⭐⭐⭐ 2026-10-03 **相邻同型、但分类器没给 anchor 的格子 ⇒ 归到同一块** ----
            #   用户口径（原话）：「**16 和 17 是一个格子**」✓
            #   真机铁证（朋友版 `runs/r_172006_0.png`，离线 `why_not_merged.py` 实证）：
            #     分类器对 (1,6)/(1,7) 给的是 **`anchor=None`、`size=(1,1)`**（各当单格 ✗）
            #     而数据表 `S00003_331` 的 `SpotSize = 9`（真块 ✓）
            #     ⇒ 模型按表定价 ⇒ **同一块被算成两步、各 9×2 = 18 体** ⇒ 总价 40 ✗✗
            #   修法：没 anchor + 表里 SpotSize ≥ 4 的格子，若四邻里有**同 sid 且也没 anchor**
            #     的格子 ⇒ 归到同一个 anchor（取最小那格 ✓）⇒ 交给 `_from_anchors` 合并成一块 ✓
            #     ⇒ 计划里只出现一步 ✓（费用仍按表口径 9×2 ✓ —— 用户口径「别随意降门槛」✓）
            try:
                _sid_m = str(_vv.get('sid') or '')
                _tbl_m = 1
                try:
                    _tbl_m = int(((spots_mod.spot_rows() or {}).get(_sid_m) or {})
                                 .get('SpotSize') or 1)
                except Exception:       # noqa: BLE001
                    _tbl_m = 1
                if (not _vv.get('anchor')) and _tbl_m >= 4:
                    _mates = []
                    for _dr, _dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        _nb2 = (_k[0] + _dr, _k[1] + _dc)
                        _nbv = (_cells_merged or {}).get(_nb2) or {}
                        if (str(_nbv.get('sid') or '') == _sid_m
                                and not _nbv.get('anchor')):
                            _mates.append(_nb2)
                    if _mates:
                        _anc = min([tuple(_k)] + [tuple(x) for x in _mates])
                        _vv['anchor'] = tuple(_anc)
                        if log is not None:
                            log.append({tag: 'merge_anchorless',
                                        'cell': '%d,%d' % tuple(_k),
                                        'sid': _sid_m, 'anchor': '%d,%d' % _anc,
                                        'mates': ['%d,%d' % x for x in _mates],
                                        'tbl_size': _tbl_m,
                                        'note': '同型相邻且都没 anchor ⇒ 归一块（点一次吃整块 ✓）'})
            except Exception:               # noqa: BLE001
                pass
            #   循环侧已经用 `find_camp_cell()`（老判据 + sid 000 兜底）认出了营地并存在
            #   `st['spawn']`/`st['camp']` ⇒ 这里在观测里给那一格打 `camp=True`，
            #   让 `MapSim`/`Problem` 拿它当**揭示链的起点** ✓
            #   ⚠ 为什么必须喂：营地格常被多格块吞掉 ⇒ `Problem` 按块名找不到营地 ⇒
            #     `camp=None` ⇒ 揭示规则没有起点 ⇒ 求解器 `exhausted` 无解（真机 23:30）✗
            try:
                _cp = st.get('spawn') or st.get('camp')
                if _cp and tuple(_k) == tuple(cell_of(_cp[0], _cp[1])):
                    _vv['camp'] = True
            except Exception:           # noqa: BLE001
                pass
            # ---- ⭐ 2026-09-30 ②：补目标白名单字段（Block.want ⇒ Problem.targets） ----
            # ⭐⭐⭐⭐⭐ 2026-10-12 **把 `score` 传下去**（治「先打巨大沙堡」✗）
            #   真机铁证（`runs/loop/loop_log.json` 第 12 张，用户报）：
            #     `5,6` 被认成 `S00003_014 限时礼包`、**score 只有 0.441**
            #     ⇒ 旧写法 `is_target(name, sid, marks)` **不看 score** ⇒ 判 True
            #     ⇒ 求解器**专门去拿它** ⇒ 点它 ⇒ 实际打的是**整座巨大沙堡**（4 场）✗✗
            #   ⇒ 现在把 `score` 一起传：`< NAME_SCORE_MIN(0.85)` 的低分名字**不当目标** ✓
            #     ⚠ 该格仍可作踏脚石/开路步（只是不再"专门去拿" ✓）
            #     ⚠ `marks` / 探索格那两支**不受影响**（低分探索格照旧生效 ✓
            #       —— 实测探索格 score 本来就 0.39~0.73，靠 sid 后缀判定 ✓）
            try:
                _vv['target'] = bool(tcfg_mod.is_target(
                    _vv.get('name'), _vv.get('sid'), _vv.get('marks'),
                    score=_vv.get('score')))
            except Exception:           # noqa: BLE001
                pass
            # ⭐⭐⭐⭐⭐ 2026-10-18 **「前 3 名同 sid」补一条命中**（用户口径，原话：
            #   「可不可以如果没有任何过门槛的，**且前三个都是同一种格子**，
            #     就直接用那个」＋ 用户选定范围「**只对特殊地块放宽**」）
            #   ---- 它治什么（真机铁证）----
            #     `runs/r_194740_0.png` 第 3 张图 `5,3` = **限时礼包**：
            #       top5 = [014/0.737, 014/0.719, 014/0.686, 003/0.654, 003/0.644]
            #       ⇒ **前 3 名全是 014**（分类器自己很笃定）
            #       但 0.737 < `NAME_SCORE_MIN(0.85)` ⇒ target=False ⇒ **不点** ✗
            #     同族：黄金宝库 0.569（前3也全是 016）、枯木蜂巢 0.733、牛角图腾 0.734
            #   ---- 为什么"分低"不等于"认不准" ----
            #     `spots._TPL_FRAMES = 3` ⇒ 每个图块只加载**前 3 帧**，
            #     而真机那格可能是第 5/27 帧（实测 014 的 f05 能到 **0.974**、
            #     016 的 f27 到 **0.869**）⇒ 低分是**采样不全**，不是认错 ✓
            #     "前 3 名同一 sid" 恰好把这两种情况分开（模型自洽 = 笃定）✓
            #   ---- 三道保险，防重犯 2026-10-12 那个"打巨大沙堡"的 bug ----
            #     ① 只对 `SPECIAL_NAMES`（8 种特殊地块）生效 ⇒ 普通地块一字未改 ✓
            #     ② score 必须 >= `SPECIAL_SCORE_MIN(0.65)`（历史 bug 是 0.441）✓
            #     ③ 前 3 名必须**都等于本格 sid**（不是"都一致但都是别人"）✓
            if not _vv.get('target'):
                try:
                    _tp3 = list(_vv.get('top') or [])[:3]
                    _sid_now = str(_vv.get('sid') or '')
                    _sids3 = {str(t[1]) for t in _tp3 if len(t) >= 2}
                    _sc_now = float(_vv.get('score') or 0)
                    # ⛔⛔ 2026-10-19 **必须先确认"用户勾选了它"**（真机事故）
                    #   用户报：「为什么点14？」⇒ 计划第一步 `1,4` 是「勇者之墓」，
                    #   而他的 `target_types.json` 里**勇者之墓根本没勾**
                    #   ⛔ 根因：这段兜底**只判了"当前不是目标"**（`if not _vv.get('target')`）
                    #     就置 `target=True` ⇒ **把用户的勾选意愿整个覆盖掉** ✗
                    #   ⇒ 兜底只该解决"**识别分数不够**"（采样不全），
                    #     **绝不能改变"用户要不要它"** ✓
                    #   `tcfg_mod.enabled(name)` = 用户勾选状态（与 `is_blocked` 互为取反）
                    _nm_now = str(_vv.get('name') or '')
                    _user_want = True
                    try:
                        _user_want = bool(tcfg_mod.enabled(_nm_now))
                    except Exception:           # noqa: BLE001
                        _user_want = False      # 判不了 ⇒ 不兜底（fail-closed ✓）
                    if (len(_tp3) >= 2 and len(_sids3) == 1
                            and _sid_now in _sids3
                            and _nm_now in tcfg_mod.SPECIAL_NAMES
                            and _user_want
                            and _sc_now >= tcfg_mod.SPECIAL_SCORE_MIN):
                        _vv['target'] = True
                        if log is not None:
                            log.append({tag: 'target_by_top3',
                                        'cell': '%d,%d' % tuple(_k),
                                        'name': _vv.get('name'),
                                        'sid': _sid_now,
                                        'score': round(_sc_now, 3),
                                        'top3': [round(float(t[0]), 3) for t in _tp3],
                                        'note': '前3名同sid ⇒ 特殊地块按笃定采用'})
                except Exception:       # noqa: BLE001
                    pass
            # ⭐⭐⭐⭐⭐ 2026-10-06 **金币 < 50 万 ⇒ 商人/宝库「也不规划」必须挡在这里**
            #   （用户报：「**为什么这个号金币明明低于50万了，却还是去买宝库了**」）
            #   ⛔⛔ 真根因：闸门写了 **4 道**，可商人/宝库进计划有 **5 条路** ——
            #      `buy` / `buy_hidden` / 跨轮 `sticky` / `buy_seen` 记忆
            #      这 4 条都是**"待买清单"**，4 道闸门全在过滤那张清单 ✓
            #      但**求解器的目标集合根本不看那张清单**：它看 `Block.want`，
            #      而 `want` 由 `is_target(name, sid, marks)` **单独算**（就是上面那句）
            #      ⇒ 「黄金宝库」在默认配置里是**勾选**的（`targets_cfg.DEFAULT_ON`）
            #      ⇒ 哪怕 `buy` 被清空，它照样以 `target=True` 进 `Problem.targets` ✗✗
            #   真机铁证（acc3 `runs/acc3/loop/loop_log.json` 第 7 张图，index 282~292）：
            #      #282 {"hud_lock":"gold","v":95531,"enough":false}   ← 金币 95531 < 50 万 ✓
            #      #284 {"buy_blocked_low_gold":["1,5"]}              ← ① 清了 buy ✓
            #      #286 {"buy_pending_cleared_low_gold":["1,5"]}      ← ② 清了 pending ✓
            #      #292 {"solver":"ok","cost":14,"steps":4,"targets":3,
            #            "order":["5,6","1,1","1,5","4,7"]}           ← ✗✗ (1,5) 还在计划里！
            #      随后点 (456,716) = 格 (1,5) → 弹宝库面板 → **就地买掉** ✗
            #   ⇒ 在**模型层**把它的 `target` 按掉（判据与那 4 道闸门**同一个** ✓）：
            #     `gold_enough_locked(st)` 读的是**锁定值**（一图只确认一次 ✓）
            #   ⚠ 读不到金币 ⇒ 返回 True ⇒ **不动**（fail-open：照常买 ✓）
            #   ⚠ 幸运草够不够**不影响**这里（宝库的价值与摇色子无关 ✓）
            #
            # ⭐⭐⭐⭐⭐ 2026-10-06 **口径升级：只按 `target` 不够，要连 `blocked` 一起写**
            #   （用户原话：「**改成彻底拉黑**」）
            #   ── 用户报的现象 ────────────────────────────────────────────
            #     日志：「金币 490924 < 500000 ⇒ 商人/宝库**不进规划目标**（3,2）✓」
            #     下一行：「精确规划：… `['3,1','3,2','3,3','2,3']`」← **3,2 还在计划里** ✗
            #     随后真机点 (168,908) → **黄金宝库面板**（只关不买，但白点一下、面板弹一次）✗
            #   ── 为什么"不进目标"它还能进计划 ──────────────────────────
            #     那句话说的是**目标身份**，而 `3,2` 进计划时的身份是**垫脚石（借道）**：
            #       · 真目标只有 `(2,3)(2,4)` 废弃矿车
            #       · 但从营地 `(4,1)` 去 `2,3` 的**最省体力路**要穿过 `3,2`
            #       · 求解器把它当"一格能踩过去的地砖"⇒ 排进点序 ✓
            #     ⚠ 而**真机上"踩一格内容格" = "点它"**（一定弹面板）——
            #       模型里"借道"这个假设，在内容格上**根本不成立** ⇒ 必然白点 ✗
            #   ── 实测这笔账（`runs/acc2/r_231259_0.png`，独立 Dijkstra 交叉验证）──
            #       · 只按 target（旧）⇒ cost **7**，但会白点 `3,2`、弹一次宝库面板
            #       · 连 blocked 一起写（新）⇒ cost **11**（绕打 `1,1` 矿箱堆 6 体），
            #         **完全不碰 `3,2`** ⇒ 不再弹面板 ✓
            #     ⇒ 用户拍板：**宁可多花 4 体力，也不要"点一下宝库再关掉"** ✓
            #     （`3,2` **不是唯通路** —— 封死后仍有解，只是 +4 体 ✓）
            #   ⚠ `blocked` 的语义**已按用户口径扩展**：不再只是"弹窗类特殊地块没勾选"，
            #     而是**"这一格本图绝对不许碰"**（既不点、也不借道）——
            #     对"金币不够的商人/宝库"完全贴切：**本图就是不碰它** ✓
            #     （`mapsolve._build_cache` 的 `blocked_mask` 正好同时做到这两件事 ✓）
            #   ⚠ 读不到金币 ⇒ 仍**不写** blocked（fail-open：照常买、照常借道 ✓）
            try:
                if (str(_vv.get('name') or '') in spots_mod.BUY_OUT_NAMES
                        and not gold_enough_locked(st)):
                    if _vv.get('target'):
                        _gold_off.append('%d,%d' % tuple(_k))
                    _vv['target'] = False
                    _vv['blocked'] = True       # ⭐ 本图**彻底不碰**它（不点、不借道 ✓）
            except Exception:           # noqa: BLE001
                pass
            # ⭐⭐⭐⭐⭐ 2026-10-09 **幸运草 < 10 ⇒ 宝箱怪自动拉黑**（用户口径，原话）
            #   「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和**10幸运草**就是」
            #   ⇒ 与上面金币那条**完全同构**（target=False + blocked=True = 本图彻底不碰 ✓）
            #   ⚠ 只对 `金属宝箱怪 / 机巧宝箱怪`（它们**花幸运草**买装备）
            #   ⚠ 读不到幸运草 ⇒ **不拉黑**（fail-open：宁可多点一格，也别因一次 OCR 失败丢掉 ✓）
            try:
                if (str(_vv.get('name') or '') in spots_mod.MIMIC_NAMES
                        and not clover_enough_for_mimic(st)):
                    if _vv.get('target'):
                        _mimic_off.append('%d,%d' % tuple(_k))
                    _vv['target'] = False
                    _vv['blocked'] = True       # ⭐ 本图**彻底不碰**它 ✓
            except Exception:           # noqa: BLE001
                pass
            # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**最新一张图的规划里把拉黑的方块规划
            #   进去了，能不能一开始就不规划这个拉黑的？**」✓
            #   现状：拉黑块是**事后从点序里剔除**（日志「点序里有 N 个拉黑地块 ⇒ 已剔除」✗）
            #     ⇒ 计划本身仍然包含它 ⇒ 求解器的**连通性/代价**都是按"能走"算的 ✗
            #     ⇒ 剔除后计划出现断档/绕路不合理 ✓
            #   ⇒ 这里给每格打 `blocked` 标（在特殊方块清单里但没勾选 = 拉黑 ✓），
            #     求解器据此**既不点它、也不借它走路** ✓ ⇒ 计划**从生成起**就没有它 ✓
            # ⚠⚠⚠ 2026-10-06 **必须"只增不减"**（`or` 不能写成直接赋值 ✗✗）：
            #   上面"金币不足 ⇒ 商人/宝库彻底拉黑"那支**已经**给它写过 `blocked=True`，
            #   而「黄金宝库」在 `SPECIAL_NAMES` 里、且用户**是勾选**的
            #   ⇒ `is_blocked('黄金宝库')` = **False** ⇒ 直接赋值会把**金币那条拉黑抹掉** ✗✗
            #   （我第一版就写成直接赋值 ⇒ 实测 `blocked=False`、计划里照样有 `3,2`，
            #     被 `_tmpman/verify_goldblock.py` 当场抓出 ✓）
            #   ⇒ 用 `or`：**任何一条判据判它是拉黑，它就是拉黑**（多来源取并集 ✓）
            try:
                _vv['blocked'] = bool(_vv.get('blocked')) or \
                    bool(tcfg_mod.is_blocked(_vv.get('name')))
            except Exception:           # noqa: BLE001
                pass
            _out[_k] = _vv
    if _dropped and log is not None:
        log.append({tag: 'done_cells_dropped', 'n': len(_dropped),
                    'cells': ['%d,%d' % k for k in _dropped[:12]]})
    # ⭐⭐⭐⭐⭐ 2026-10-06 **金币不足 ⇒ 商人/宝库"彻底拉黑"**（用户报的真根因 + 口径升级）
    #   为什么必须单独记一条：这是**第 5 条路**（前 4 条是 buy/buy_hidden/sticky/buy_seen）
    #   ⇒ 只清那 4 条时日志看着"闸门全生效了"，计划里却还有它 ⇒ 必须让这条**自己出声** ✓
    #   ⚠⚠ 措辞必须写**"拉黑（不点也不借道）"**，不能只写"不进规划目标" ——
    #     旧措辞正是误导来源：日志说"不进规划目标 ✓"，下一行计划里却有它
    #     （因为它以**垫脚石**身份进去的）⇒ 看日志的人会以为闸门坏了 ✗
    if _gold_off and log is not None:
        try:
            log.append({'buy_target_off_low_gold': _gold_off,
                        'gold': st.get('gold_locked') if isinstance(st, dict) else None,
                        'min': GOLD_MIN_BUY,
                        'blocked': True,
                        'note': '金币不足 ⇒ 商人/宝库**彻底拉黑**（target=False + blocked=True）'
                                '—— 求解器既不把它当目标、也**不借它走路** ✓'
                                '（旧版只按 target ⇒ 它会以"垫脚石"身份进计划 ⇒ 白点一次 ✗）'})
            say('       · 金币 %s < %d ⇒ 商人/宝库**彻底拉黑**（不买、不规划、也**不借道**）（%s）✓'
                % (st.get('gold_locked') if isinstance(st, dict) else None,
                   GOLD_MIN_BUY, '、'.join(_gold_off)))
        except Exception:               # noqa: BLE001
            pass
    # ⭐⭐⭐⭐⭐ 2026-10-09 **幸运草不足 ⇒ 宝箱怪"彻底拉黑"**（用户口径，原话）
    #   「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和**10幸运草**就是」
    #   ⇒ 与上面金币那条**完全同构**（必须自己出声 ⇒ 否则日志看着"闸门生效了"，计划里却还有它 ✗）
    #   ⚠ 措辞明确写**"彻底拉黑（不点、不借道）"**（旧措辞"不进规划目标"是误导来源 ✗）
    if _mimic_off and log is not None:
        try:
            log.append({'mimic_target_off_low_clover': _mimic_off,
                        'clover': st.get('clover_locked') if isinstance(st, dict) else None,
                        'min': MIMIC_CLOVER_MIN,
                        'blocked': True,
                        'note': '幸运草不足 ⇒ 宝箱怪**彻底拉黑**（target=False + blocked=True）'
                                '—— 求解器既不把它当目标、也**不借它走路** ✓'})
            say('       · 幸运草 %s < %d ⇒ **宝箱怪彻底拉黑**（不买、不规划、也不借道）（%s）✓'
                % (st.get('clover_locked') if isinstance(st, dict) else None,
                   MIMIC_CLOVER_MIN, '、'.join(_mimic_off)))
        except Exception:               # noqa: BLE001
            pass
    return _out


def eff_order(st, c, log=None, max_steps=20):
    """⭐⭐ 2026-09-28：EffPolicy（片感知 + 一步前瞻）在线点序 —— solver 失败的兜底 ✓

    用与 solver_order **同一份**观测合并口径（_cells_for_model → from_observation）建盘，
    再让 EffPolicy 推演整条点序（strategy.EffPolicy.plan ✓）。特点：
      · 毫秒级（solver 是秒~分钟级）⇒ 调用方可**每轮用最新观测重算**（在线策略 ✓）
      · 部分观测天然支持：雾格 board=-1 不进候选（visible() 只给已揭示格 ✓）
      · 2000 张独立验证 11.021 vs 旧启发式 11.675（省 5.61%，地图生成算法.md §16）
    任何异常返回 [] ⇒ 调用方退回旧启发式 ✓（fail-open ✓）
    """
    try:
        import mapsim as _ms
        from strategy import EffPolicy as _Eff
        _cells_merged = _cells_for_model(st, c, log=log, tag='eff',
                                         mark_revealed=False)
        if not _cells_merged:
            return []
        sim = _ms.MapSim.from_observation(_cells_merged, spots_mod.spot_rows())
        # ⭐ stop_when_no_target=False：观测盘上目标可能还在雾里（targets 空 ≠ 图清完）
        #   ⇒ 没目标也继续开路（2026-09-28 离线验证抓到的坑，见 strategy.plan 注释 ✓）
        plan = _Eff().plan(sim, max_click=max_steps, stop_when_no_target=False)
        if log is not None:
            log.append({'eff': 'ok', 'steps': len(plan),
                        'order': ['%d,%d' % p for p in plan]})
        return plan
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'eff': 'error', 'e': repr(e)[:100]})
        return []


def solver_order(st, c, log=None, max_steps=6, out=None):
    """⭐ 用精确解算器算"当前信息下的最省体力点序" ✓

    返回 [(cell_row, cell_col), …]（按最优顺序 ✓ 取前 max_steps 步）
    任何异常/无解都返回 [] ⇒ 调用方退回启发式 ✓（fail-open ✓）

    `out`（可选 dict）：回填 `ok / cost / reason / no_targets`
      —— 2026-09-30 加：**每轮重解**后调用方要能区分
         「算不出（该降级）」vs「盘上已经没有目标了（正常收尾）」，
         否则会把"没目标"当成连续失败 ⇒ 白切 EffPolicy ✗
    """
    if not OPT_SOLVER:
        if out is not None:
            out['ok'] = False
        return []
    try:
        import mapsim as _ms
        import mapsolve as _mv
        _t0 = time.time()
        # ⭐⭐ 2026-09-27 根因修复（用户报「不点 1 体空白格、反去打更贵的战斗格」）：
        #   原样只传 `c['st']`（**地块分类** ✓）⇒ 模型看不到**标记** ⇒ targets 为空
        #   ⇒ 求解器不知道"点这个空白格能解锁两个标记格" ⇒ 点序变成乱走 ✗✗
        #   2026-09-28：合并逻辑抽成 _cells_for_model（eff_order 共用 ✓）
        # ⭐⭐⭐ 2026-10-02（用户报「规划错了」）：**solver 也用 `mark_revealed=False`** ✓
        #   原来 solver 用默认 True（"标记格当可点喂给 mapsolve"），理由是
        #   "mapsolve 需要目标可达才求解；真机点不动由 nochange 兜底" ——
        #   真机证明这条兜底靠不住：
        #     · 真机 23:30 那把规划出 `["1,2","2,4"]`，两格 ratio 0.665 / 0.717 **都是雾**
        #       ⇒ 连点两轮 `fogged_noop`、0 进展（`done_cells_dropped` 里 4 格被当已消耗）
        #     · 而 boss 有「永不拉黑」保护 ⇒ nochange 累计也纠正不了它 ⇒ 死循环 ✗
        #   ⇒ 与 `eff_order` 统一口径（那边注释早写明："True 时推演盘一步把雾中 boss
        #     消耗掉 ⇒ targets 丢方向、真机执行全是 fogged noop ⇒ 空转 ✗✗"）：
        #     **雾中的标记格 = "可见但不可点"** ⇒ 求解器会老实规划"先揭格子、再打目标" ✓
        #   ⚠ 与 `mapsolve.block_revealed` 的**观测闸门**（同一天加的）配套生效：
        #     闸门挡住"推演出来的可点"，这个参数挡住"标记格被无条件当成已揭示" ✓
        _cells_merged = _cells_for_model(st, c, log=log, tag='solver',
                                        mark_revealed=False)
        # ⚠ 2026-09-27 试过"摘掉出生点不点它" ✗ —— 实测**模型直接无解**：
        #     含出生点 ⇒ cost=11 / 4 步 ✓ ；摘掉 ⇒ cost=None / 0 步 ✗
        #   原因：开局其它空地块多为雾格（点不动 ✓）⇒ 出生点是唯一能启动"连锁揭示"的格 ✓
        #   ⇒ 保留出生点 ✓（它那一步不是多余的 ✓）；如需从"执行序列"里剔除，见下方开关 ✓
        sim = _ms.MapSim.from_observation(_cells_merged, spots_mod.spot_rows())
        prob = _mv.Problem(sim)
        # ⭐ 2026-09-28 加 max_secs=8（用户报「进图要等很久」）：复杂盘 60k 状态枚举
        #   可达 30~60s，失败后下轮还重试 ⇒ 进图几分钟不点格 ✗。8 秒算不出就
        #   fail-open ⇒（今日新链）EffPolicy 毫秒级接管 ✓
        #   ⭐ 2026-09-30 实测（真机盘 96 张、每轮重解）：完整链路 p50 0.65ms /
        #     p95 1.4ms / p99 1.9ms / max 2.4ms ⇒ 8 秒上限实际**永远碰不到** ✓
        _rep = {}
        cost, plan = _mv.solve(prob, max_states=60000, max_secs=8, report=_rep)
        if out is not None:
            out['cost'] = cost
            out['reason'] = _rep.get('reason')
            out['no_targets'] = (not plan) and cost == 0
            out['ok'] = bool(plan)
        if not plan:
            if log is not None:
                log.append({'solver': 'no_plan', 'cost': cost,
                            'reason': _rep.get('reason'),
                            'expanded': _rep.get('expanded'),
                            'secs': round(time.time() - _t0, 2)})
            return []
        # block idx → **真的能点的格**
        # ⭐⭐⭐ 2026-09-30 修（离线 `_bench_online.py` 80 张盘对拍，代价极大）：
        #   旧实现取「该块在 `c['st']` 里出现的第一个格」（实际等于 `cells[0]`，块首格）。
        #   但 `mapsolve` 的 `visible()` 会把**一整片连通空地**去重成「片内最小 idx 的
        #   代表块」⇒ 计划里的块常常是那个代表块，而**代表块本身还没揭示** ✗
        #   ⇒ 真机点它 = `fogged_noop`（不消耗、不揭示）⇒ 这片空地在下一帧里边界不变
        #   ⇒ **后面整条计划全部错位**：空转、重复点已走过的格、最后漏目标/卡住 ✗✗
        #   离线实测（80 张盘、`marks_in_fog`）：修前 **空转 1.62 次/张、平均 4.6 轮、
        #     48/80 张到最后目标都没清完**；修后 空转 0、1.0 轮、0/80 漏目标
        #   ⇒ 改用 `Problem.cells_for_plan()`：逐步推演模型状态，每一步在目标块（片）
        #     里挑一个**当下已揭示**的格 ✓
        out = []
        for _rc, _bi, _w in prob.cells_for_plan(plan[:max_steps]):
            if _rc not in out:
                out.append(_rc)
        # ⭐⭐⭐ 2026-10-03 用户口径「**统一**」：报总数必须与**逐格定价**同口径 ✓
        #   原来直接用 A* 的 `cost`（那是 g+h 的**内部量**）⇒ 真机对不上 ✗：
        #     acc1 `gui_20261003_140308` 第 2 张图计划 ['2,6','2,5','3,1']
        #     逐格 = 拦路 3×2=6 + 草地 1 + boss 6 = **13**，而它报 **8** ✗
        #   ⇒ 现在把 `cost` 重算成 `prob.step_cost()` 的**逐步求和** ⇒
        #     日志「最省体力 N」/ 悬浮条「规划：体力 N」从此能直接和实际体力对账 ✓
        #   （A* 原值仍记进 log 的 `cost_astar`，便于以后对拍算法 ✓）
        _cost_astar = None
        try:
            _cost_u = 0
            for _rc_u, _bi_u, _w_u in prob.cells_for_plan(plan[:max_steps]):
                _cost_u += int(prob.step_cost(None, _bi_u) or 0)
            if _cost_u:
                _cost_astar = cost
                cost = _cost_u
        except Exception:       # noqa: BLE001
            _cost_astar = None
        if _cost_astar is not None and log is not None:
            log.append({'solver': 'cost_unified', 'astar': _cost_astar,
                        'unified': cost, 'note': '报总数改用逐格口径（用户口径"统一"✓）'})
        try:
            _nt = len(sim.targets())
        except Exception:       # noqa: BLE001
            _nt = -1
        # ⭐ 2026-09-27：**输出里隐去出生点**（执行仍保留 ✓ 否则揭示起不来 ✗）
        _sp_px2 = st.get('spawn') or st.get('camp')
        _sp_rc2 = None
        if _sp_px2:
            try:
                _sp_rc2 = cell_of(_sp_px2[0], _sp_px2[1])
            except Exception:       # noqa: BLE001
                _sp_rc2 = None
        # ⭐ 2026-09-27 用户报「规划给我看的是错的，执行的是对的」⇒ **显示完整** ✓
        #   （之前隐去出生点 ⇒ 显示缺第一步 ⇒ 看起来像错的 ✗）
        _disp = list(out)
        _hidden = []
        # ⭐ 2026-09-27 用户要求：**步数统计也要减掉出生点那一步** ✓
        #   （显示里已隐去出生点 ✓ 步数还含它就不一致 ✗ "3 步"却只列 2 个 ✗）
        _steps_disp = len(_disp)
        if log is not None:
            _rec = {'solver': 'ok', 'cost': cost, 'steps': _steps_disp,
                    'steps_raw': len(plan), 'targets': _nt,
                    'order': ['%d,%d' % p for p in _disp],
                    'secs': round(time.time() - _t0, 2)}
            if _hidden:
                _rec['spawn_hidden'] = ['%d,%d' % p for p in _hidden]
            log.append(_rec)
        say('       · 精确规划：最省体力 %s，%d 步；先执行 %s'
            % (cost, _steps_disp, ['%d,%d' % p for p in _disp]
               or ['（只点出生点，已隐去）']))
        # ⭐⭐ 2026-10-01 用户报「怎么看不到规划了」⇒ 规划也发**悬浮条日志行** ✓
        #   背景：只有 `status()` 的行会上悬浮条；「精确规划」原来是 `say()`（只进 logcat
        #   与应用内日志）⇒ 用户盯悬浮条时看不到 ✗。文本避开 OCR 关键词（探索/派遣/关闭/领取/背包…）
        try:
            _pv = ' '.join('%d,%d' % p for p in _disp[:4]) or '（只点出生点）'
            status('规划：体力 %s / %d 步 → %s' % (cost, _steps_disp, _pv))
        except Exception:       # noqa: BLE001
            pass
        return out
    except Exception as e:      # noqa: BLE001
        if out is not None:
            out['ok'] = False
            out['err'] = repr(e)[:100]
        if log is not None:
            log.append({'solver': 'error', 'e': repr(e)[:100]})
        return []


def board_for(mapname=None, code=None):
    """取该图的地块分类器（mapname/code 二选一；失败返回 None）

    ⛔⛔ 2026-10-19 **不许再兜底「夏日海滩」**（真机事故，用户：
      「计划还是错的，实时棋盘也还是错的」）
      ---- 原代码 ----
          code = code or spots_mod.code_of(mapname or '夏日海滩')
      ---- 为什么是灾难 ----
        `mapname=None`（图名还没读到，进图首帧很常见）⇒ 兜底成 S00003 夏日海滩
        ⇒ 用**别的图**的模板分类本图 ⇒ 整盘地块名全错（实测：
          荒凉戈壁被认成「游乐设施 12 / 海边杂物 9 / 海边小屋 4 / 椰树 2」，
          分数 0.3~0.7）⇒ 计划按错棋盘算 ⇒ 点序全错 ✗✗
      ---- 现在 ----
        拿不到 code ⇒ **返回 None**，由 `board_state` 走"实测消歧"（用真帧说话）✓
    """
    code = code or (spots_mod.code_of(mapname) if mapname else None)
    if not code:
        return None
    if code not in _BOARDS:
        try:
            _BOARDS[code] = spots_mod.Board(code)
        except Exception as e:      # noqa: BLE001
            print('[warn] 地块分类器构建失败 %s: %r' % (code, e))
            _BOARDS[code] = None
    return _BOARDS[code]


_CODE_DECIDED = {}          # mapname -> 已实测消歧后的 code（按图名缓存，避免每轮重算 ✓）

# ⭐⭐⭐⭐⭐ 2026-10-26 **当前图的图名**（模块级，供 `run_maps` 里的退图用）
#   ---- 为什么需要它（我自己踩的坑，血证）----
#     我第一版直接在退图处写 `finish_map(b, log, mapname=st.get('mapname'))`
#     ⇒ **NameError: name 'st' is not defined** ✗✗
#     根因：`st` 是 `run_one_map()` 的**局部变量**（`:8475` 建、`:8547` 就随函数结束而没了），
#           而退图那个调用点在 **`run_maps()`**（`:13581`）⇒ 那里**根本没有 `st`** ✗
#     ⇒ 真机表现：退图这一步抛异常 ⇒ 「退图没成功，已停止」⇒ **整局停在那** ✗✗
#     ⚠ 这正是本仓**记过两次**的老坑（`bought_rec_err: NameError: name 'st' is not defined`）
#       —— 我又踩了一次 ⇒ 教训：**跨函数取状态，必须走模块级变量**（同 `_CODE_DECIDED`）✓
#   ---- 口径 ----
#     · 写入点：`one_round` 里**锁定图名**的那一处（`st['mapname'] = _mn_now`）
#     · 读取点：`run_maps` 退图时传给 `finish_map`
#     · 每张图进图时必写（进图首帧必 OCR ⇒ 必锁 ⇒ 必写）✓
_LAST_MAPNAME = {}          # {'name': '夏日海滩'} —— 当前图的图名


def _candidate_codes(mapname):
    """图名 → **所有可能的** code（>1 个就是有歧义，需要实测消歧 ✓）

    背景（2026-10-01 离线核查发现）：15 个图名里有几组很像，OCR 掉字时 `code_of`
    会**在同组里猜错成员** —— 实测「沙滩」→ 清凉沙滩(S40002)、「森林」→ 迷失森林(S20001)；
    若实际是夏日海滩/幽暗密林 ⇒ 用错模板集 ⇒ **整盘分类全错** ✗
    """
    try:
        mt = spots_mod.map_table()
    except Exception:       # noqa: BLE001
        return []
    nm = str(mapname or '').strip()
    # ⭐ 2026-10-03：先摘掉 OCR 常见尾巴（真机读到的是「广豪草原[100]」这种）
    nm = nm.split('[')[0].split('（')[0].strip()
    if not nm:
        return []
    if nm in mt:                       # 精确命中 ⇒ 无需消歧 ✓
        return [mt[nm]]
    out = []
    for k, v in mt.items():
        if (nm in k or k in nm) and v not in out:
            out.append(v)
    if out:
        return out
    # ⭐⭐⭐ 2026-10-03 A：**模糊匹配**（一字之差）
    #   真机事故（用户报 acc2「已进图…4 秒 stuck 退图」）：
    #     图名真值是「广**袤**草原」，而 OCR 读成「广**豪**草原」⇒ 精确查不到、
    #     子串也查不到（两个字完全不同）⇒ 分类器拿不到代码 ⇒ **整盘 ratio 全 0**
    #     ⇒ `light=0 / gray=28` ⇒ 命中"全暗"判据 ⇒ 判"棋盘被挡住" ⇒ 关面板/万能位
    #     ⇒ 4 秒把一张图丢掉（25 体力白花）✗✗
    #   实测（`runs/bagdbg/board_hidden_r0.png`）：
    #     mapname='' / '夏日海滩' ⇒ light=24（正常）✓
    #     mapname='广豪草原'       ⇒ ratio 全 0.000 ⇒ hidden=True ✗
    #   ⇒ 加"编辑距离 ≤1"的模糊匹配（同长度只差一个字、或差一个字的长短）✓
    def _same_chars(a, b):
        if abs(len(a) - len(b)) > 1:
            return 0
        return sum(1 for x, y in zip(a, b) if x == y)
    _best, _sc = [], 0
    for k, v in mt.items():
        s = _same_chars(nm, k)
        if s >= max(2, len(k) - 1):
            if s > _sc:
                _best, _sc = [v], s
            elif s == _sc and v not in _best:
                _best.append(v)
    if _best:
        return _best
    # ⭐⭐⭐ 2026-10-03 B：**自适应兜底** —— 连模糊都不中（数据表里有名字但本仓没有地块表的
    #   如「火山/雪原」，以及以后任何新图）⇒ **把所有已知代码都当候选**，
    #   交给既有的 `_disambiguate_map()` 用**真帧分类质量**挑最好的那个 ✓
    #   （代价：只在"名字完全对不上"时多付几次 0.5s 分类 ⇒ 换来"任何新图都不会全家瘫痪" ✓）
    try:
        return sorted(set(mt.values()))
    except Exception:       # noqa: BLE001
        return out


def _disambiguate_map(img, mapname, cands, log=None):
    """有多个候选图时：**各建一次盘、比分类质量**，取最高的那个 ✓

    判据 = 「已分类格数」+「高分格(≥0.85)数」的加权（用真实帧，不靠猜 ✓）
    代价：只在**图名有歧义**时做一次，且结果按图名缓存 ⇒ 每张图最多付一次（≈0.2~0.5s）✓
    """
    best, best_key = None, None
    for c in cands:
        bd = board_for(code=c)
        if bd is None:
            continue
        try:
            st = bd.state(img)
        except Exception:       # noqa: BLE001
            continue
        n = len(st or {})
        hi = sum(1 for v in (st or {}).values()
                 if float(v.get('score') or 0) >= 0.85)
        key = (hi, n)          # 高分格优先，其次格数 ✓
        if best_key is None or key > best_key:
            best, best_key = c, key
    if log is not None:
        log.append({'map_disambig': mapname, 'cands': cands, 'picked': best,
                    'key': list(best_key) if best_key else None})
    if best:
        say('   · 图名「%s」有歧义 %s ⇒ 实测选 %s（高分格 %s）✓'
            % (mapname, cands, best, best_key[0] if best_key else '?'))
    return best


def board_state(img, mapname=None, code=None, need_names=True):
    """整盘状态 -> {(r,c): {...}}；失败返回 {}（调用方退回旧的启发式）"""
    # ⭐⭐ 2026-10-01：图名有歧义时**用真实帧实测消歧**（按图名缓存 ✓）
    # ⭐⭐⭐ 2026-10-19 **图名读不到也要消歧**（不能兜底成某张固定的图）
    #   真机事故：`mapname=None` ⇒ 旧代码兜底夏日海滩 ⇒ 整盘地块名全错 ✗
    #   ⇒ 现在：mapname 空 ⇒ 用「全部 code」当候选，**拿真帧实测挑最好的** ✓
    #   ⚠ 只在图名空时做（有图名时仍走精确/模糊匹配，省时间 ✓）
    #   ⚠ 结果按 `mapname or ''` 缓存 —— 空图名也缓存，同一张图不重复消歧 ✓
    _mk = mapname or ''
    if code is None:
        code = _CODE_DECIDED.get(_mk)
        if code is None:
            _cands = _candidate_codes(mapname) if mapname else []
            if not _cands:
                # 图名空/认不出 ⇒ 全部 code 当候选（用真帧选）
                try:
                    _cands = sorted(set(spots_mod.map_table().values()))
                except Exception:           # noqa: BLE001
                    _cands = []
            # 2026-10-27 只判亮度/格子数（board_hidden / looks_in）时**不需要地块名**
            #   => 跳过「15 个 code 全量消歧」（省 4~10 秒 + 不打那句误导日志）
            #
            #   ⛔ 但**不能随便挑 `_cands[0]`** —— 实测（r_195513_0.png，清空缓存）：
            #        S00001 => light=23 gray=12
            #        S00003 => light=5  gray=23   <- 才是真的
            #      ⇒ 用错 code 时 ratio 分母变了 ⇒ **light/gray 数字会反过来** ✗✗
            #        （那样 board_hidden / looks_in 会给出相反的答案 —— 比慢更糟）
            #
            #   ⇒ 正确做法：**优先复用当前图已锁定的真 code**
            #     `_LAST_MAPNAME` 是 `one_round` 锁图名时写的（每张图都有 ✓）
            #     ⇒ 拿它的图名去 `_CODE_DECIDED` 查 ⇒ 命中就是**真 code** ✓
            #     只有真拿不到（比如还没进过图）才退回 `_cands[0]`（并记一条日志）
            if not need_names:
                _known_mn = _LAST_MAPNAME.get("name")
                code = (_CODE_DECIDED.get(_known_mn) if _known_mn else None)
                if code is None:
                    code = _cands[0] if _cands else None
                    if code is not None:
                        try:
                            print("[warn] need_names=False 但拿不到当前图的真 code "
                                  "=> 退回 %s（light/gray 可能与真实相反）" % code)
                        except Exception:       # noqa: BLE001
                            pass
                if code is None:
                    return {}
            elif len(_cands) > 1:
                code = _disambiguate_map(img, mapname or '（图名未读到）',
                                         _cands, log=None)
            elif _cands:
                code = _cands[0]
            if code:
                _CODE_DECIDED[_mk] = code
    bd = board_for(mapname, code)
    if bd is None:
        return {}
    _t0 = time.time()
    try:
        st = bd.state(img)
        if not st:
            # ⭐ 兜底：空结果 ⇒ 用更低门槛再试一次（小分辨率/雾格多时 ✓）
            st = bd.state(img, thr=max(0.10, 0.80 * (float(bd.px) / 144.0) * 0.6))
            if st:
                say('   · 分类兜底：低门槛重试拿到 %d 格 ✓' % len(st))
        STATS['classify'] = STATS.get('classify', 0.0) + (time.time() - _t0)
        STATS['classify_n'] = STATS.get('classify_n', 0) + 1
        return st
    except Exception as e:          # noqa: BLE001
        print('[warn] 地块分类失败: %r' % (e,))
        return {}

L = {
 'kick': ('其他设备', '退出游戏', '重新登录'),
 'low': ('能量不足', '体力不足'),
 'fight': '战斗事件', 'fbtn': '战斗', 'expl': '探索产出', 'ebtn': '探索',
 # ⭐ 敌方预览面板（2026-09-25：用户报卡在「偶遇强敌」）——底部是「邀请挑战」+「开始战斗」
 'strong': ('偶遇强敌', '遭遇强敌'), 'sbtn': '开始战斗',
 'claim': ('领取', '继续'), 'ok': '确定', 'cancel': '取消',
 'end': '结束冒险', 'menu': ('快速扫荡', '进入地图'), 'enter': '进入地图',
 'win': '战斗胜利', 'lose': '战斗失败', 'close': '关闭',
 'hud': ('背包', '神石', '预言'),
 'desc': ('【正面】', '【负面】'),
 'dice': ('幸运草', '骰', '摇'),
 'special': ('旅行商人', '金属宝箱怪', '机巧宝箱怪', '黄金宝库', '勇者之墓',
             '传承祭坛', '限时礼包', '献祭宝箱怪', '预言石碑',
             # ⛔⛔⛔ 2026-10-10 **同一面板两个名字**（用户报「图上有预言石碑，试一试」时抓到）：
             #   · 图上的**方块名** = `预言石碑`（数据表 `Area_Spot.Name` ✓）
             #   · 面板**标题**     = `预言石板`（真机 OCR 实测 `conf=0.99` ✓）
             #   ⇒ 本元组原来只有「**石碑**」⇒ `fb(items,'预言石碑')` 在**面板帧上恒 False** ✗
             #     ⇒ `for t in L['special']` 那一支**从来没被触发过**（连"认出是特殊地块"都不成立）
             #     ⇒ `foretell_flow` 到不了 ⇒ 面板被上面 `prophecy` 支关掉 + 拉黑 ✗✗
             #   门禁 `verify_foretell_path.py` 在真机帧上逐条量出来的：
             #       `预言石碑 ⇒ 没命中` / `预言石板 ⇒ ('预言石板', 360, 320)` ✓
             #   ⇒ **两个名字都列** ✓（面板名放前面：`fb` 是按给定顺序找 ✓）
             '预言石板',
             # ⛔⛔⛔ 2026-10-10 **同一族 bug 的另外两个**（我审计时用**真实面板帧**抓到 ✗）
             #   `勇者之墓` / `限时礼包` 和预言石碑**一模一样**：面板标题与方块名不同 ✗
             #   实测（真实取证帧 + 真实 OCR，**不手造条目**）：
             #       `runs/spec_dev/relic_panel.png`  ⇒ fb('勇者之墓')=**False**
             #                                          fb('英灵使者')=**True** ✓
             #       `runs/spec_dev/gift_free1.png`   ⇒ fb('限时礼包')=**False**
             #                                          fb('限时超值礼包')=**True** ✓
             #   ⇒ 不加这两个名字 ⇒ `for t in L['special']` 匹配不上 ⇒ 面板被
             #     「无视」支 `close_x_panels` + 盲点 X 关掉 ⇒ **flow 永远跑不到** ✗✗
             # ⚠⚠⚠ **我的 `verify_deadcode_relic.py` 当时是假绿**：
             #   我在夹具里**自己手写了「勇者之墓」**（真实面板上根本没这三个字 ✗）
             #   ⇒ 测试"通过"了，可生产路径照样进不去 ✓
             #   ⇒ 教训：**夹具必须用真实面板帧/真实 OCR 的文字**，不能凭"方块叫什么"手写 ✗
             #     （这与"直接调 flow 绕过 popups"是同一类错：**测试没走真实数据** ✓）
             '英灵使者', '限时超值礼包',
             # ⚠ 同理补上：金属/机巧宝箱怪的**面板名**（实测都是同名 ✓，此处仅作提醒）；
             #   `传承祭坛` 的面板名尚未实测（用户口径：「面板还没实测过」✓）
             ),
 'buy': ('购买', '解锁', '开启'),
 'buyout': ('旅行商人', '金属宝箱怪', '机巧宝箱怪', '黄金宝库'),
 # ⭐⭐⭐⭐⭐ 2026-10-10 **修「勇者之墓卡死」的死代码 bug**（用户报：
 #   「**刚刚那场没能正确点击勇者之墓，导致卡死**」）
 #
 #   ⛔⛔ 根因：`L['act_on']` 原来**只有商人和宝库** ——
 #     而 `popups()` 里那段的结构是：
 #         for t in L['special']:
 #             if fb(items, t):
 #                 if t **not in** L['act_on']:
 #                     close_x_panels(...); return 'handled'   # ← 勇者之墓栽在这
 #                 ... if '黄金宝库' in t: … / elif t == '勇者之墓': … ✗
 #     ⇒ **勇者之墓/限时礼包/预言石碑 那三支永远是死代码**（被上面 return 掉了）✗✗
 #       我在 10-07 写的 `relic_flow` / `gift_flow` / `foretell_flow` **一次都没执行过** ✗
 #
 #   ⚠ 我怎么漏的（**测试方法的系统性漏洞**，记下来防重犯）：
 #     我当时是**直接调 `buypanels.relic_flow(b, log)`** 测的 ⇒ 绕过了 `popups()`
 #     ⇒ 函数本身"跑通"了，可**生产路径根本进不去** ✗
 #     ⇒ 教训：**测面板流程必须从"点格子"那一步开始**，不能只调 flow 函数 ✓
 #
 #   后果（真机铁证 `runs/acc1/r_002548_0.png` + `runs/acc1/gui_20261010_002527_acc1.log`）：
 #     规划 `['3,6','3,7','2,7','1,6']`，`3,7` = 勇者之墓（`score 0.999`）
 #     ⇒ 点开「英灵使者」面板后被**盲点 X 关掉**（而不是走 `relic_flow`）
 #     ⇒ 那格已被 `done.add()` 标成"完成" ⇒ 不再重试 ⇒
 #        4 步全 `give_up_step` ⇒ `plan_left=0` ⇒ **`targets_unreachable` ⇒ stuck** ✗✗
 #
 #   ⇒ 修法：**把三个已实现流程的名字加进来**（它们各自都有完整的 `flow` ✓）
 #     ⚠ 加进来**不会**改变"没勾选就无视"的语义 —— 那层是 `targets_cfg.is_blocked`
 #       在**决策层**管的（没勾 ⇒ 压根不进计划 ⇒ 不会被点开 ✓）；
 #       这里管的是"**面板已经开着时怎么办**" ⇒ 已实现流程的就该走流程 ✓
 'act_on': ('旅行商人', '黄金宝库',
            # ⭐ 2026-10-10 加入（三个都有完整 flow，见 `buypanels.py`）
            #   ⚠ 这里**只写规范名** —— 别名由 `SPECIAL_ALIAS` 在入口归一 ✓
            #     （我一度把「预言石板」也硬塞进来 ⇒ 治标不治本，别名一多必然再漏 ✗）
            '勇者之墓', '限时礼包', '预言石碑',
            # ⛔⛔ 2026-10-10 审计补：**这两个有 `mimic_flow` 却没进 `act_on`** ✗
            #   ⇒ 与勇者之墓**同一个 bug**（实现了 flow、也测过，但**没接进 `popups()`**）
            #   ⇒ `t not in act_on` ⇒ 走"无视"支 `close_x_panels` + 盲点 X 关掉
            #   ⇒ **`mimic_flow` 永远跑不到** ✗（我在 `audit5` 里用"flow 在? × in act_on?"
            #     的**交叉表**扫出来的 ✓ —— 靠读代码不会发现，靠**结构比对**才会 ✓）
            '金属宝箱怪', '机巧宝箱怪',
            # ⭐⭐⭐ 2026-10-11 用户口径（原话）：「**我开了**」（= 把传承祭坛/机巧宝箱怪
            #   在窗口里勾上了，要采最后两个特殊地块的面板 ✓）
            #   ⛔ 病：`传承祭坛` **有面板、但代码里没有 handler** ✗
            #     ⇒ 它在 `special` 里、却不在 `act_on` ⇒ 走"无视"支
            #     ⇒ `close_x_panels` + 盲点 X **把面板关掉** ⇒ 采不到坐标 ✗✗
            #   ⇒ 加入 `act_on`：让它**不在这里被关掉** ⇒ 交给下面的 `elif` 分支 ✓
            '传承祭坛'),
 # ⭐「发现莱姆！」弹窗（用户 2026-09-25）：揭格/退图前补点都可能弹，**点「返回」关掉**
 #   实测版面：标题「发现莱姆！」(529,771)、莱姆名 (541,1025)、**返回按钮 (539,1309)**
 'lime': ('莱姆', '发现莱姆'),
 # ⭐「获得新装备！」弹窗（用户 2026-09-26 报卡住）：**同模板版面**
 #   实测（1080×1920，OCR conf）：标题「获得新装备！」(531,992)、装备描述 (528,1101)、
 #   **「返回」(540,1252) conf=1.00**
 #   ⚠ 触发场景（用户口径）：① 打完大拇指(recommend)地块 ② 退图前补点（发现莱姆点那下）
 #   ⚠ 不关掉它 ⇒ 整盘被遮 ⇒ board_hidden: all_dark ⇒ 认不到任何地块 ⇒ finish: timeout ✗
 'newequip': ('获得新装备', '获得装备', '新装备'),
 # ⭐「预言石板」占卜面板（用户 2026-09-26）：点出后就关掉，并**拉黑这格不再点** ✓
 #   ⚠ 别写成单独的 '预言' —— `L['hud']` 里也有「预言」（主界面入口），会误伤 ✓
 'prophecy': ('预言石板', '预言石碑', '占卜'),
}

# ⭐⭐⭐⭐⭐ 2026-10-10 **特殊地块「别名 → 规范名」归一表**（治本，别再逐处堆字符串 ✗）
#   ---- 为什么需要 ----
#     同一个面板在**图上**和**面板标题**上可能叫**不同的名字**，
#     而 `popups()` 里所有判据（`act_on` / `elif ... in t`）都是**按名字比** ⇒ 必然漏 ✗
#   ---- 我踩的连环坑（都在真机帧上被门禁 `verify_foretell_path.py` 抓出）----
#     ① `t not in L['act_on']` ⇒ 走"无视"支（盲点 X 关掉）✗
#     ② 只把「石碑」加进 `act_on` ⇒ 还是不算（`t` 是「石板」）✗
#     ③ `elif '预言石碑' in t` ⇒ 仍不匹配（**碑 ≠ 板**）⇒ 掉进 `else`
#        ⇒ **拿旅行商人流程去点预言面板** ⇒ 真机日志显示**买了 4 次** ✗✗✗
#   ---- 口径 ----
#     `alias → 规范名`；规范名 = 数据表 `Area_Spot.Name`（= 图上那个名字 ✓）
#     ⚠ 新增别名时**只改这张表**（`act_on` / `elif` / `special` 都不用动）✓
SPECIAL_ALIAS = {
    '预言石板': '预言石碑',      # 面板标题（真机 OCR conf=0.99）→ 方块名（数据表）
    # ⭐ 2026-10-10 又抓到两个**同类**（审计时用真实面板帧发现，见 `L['special']` 处的长注释）
    '英灵使者': '勇者之墓',      # 面板标题（`relic_panel.png` 实测）→ 方块名
    '限时超值礼包': '限时礼包',   # 面板标题（`gift_free1.png` 实测）→ 方块名
}

# ⭐⭐ 万能关闭点（用户 2026-09-26 实测口径：「点击中间最下面就可以关闭几乎所有弹窗，
#   而且还会在地图界面」）—— 就是底部导航中间那格 (541,1890)（平时是「开始冒险」）✓
#   有了它就不必给每个弹窗单独写关闭逻辑（预言石板/莱姆/各种未知面板都吃这一下）
#
# ⚠⚠ 定位（用户 2026-09-26 最新口径）：「**万能点位可以用来应对异常情况，防止任务过早中断**」
#   ⇒ 它是**异常兜底**，不是常规动作 ✗（别每轮都点一下）
#   ✅ 安全性（用户 2026-09-26 补充实测）：「**那边点了非常安全，不会有变化**」
#     我 2026-09-26 也复测过：在**选图界面**（那格文字正是「开始冒险」）点它，
#     前后两张 OCR 完全一致（只有体力自然 +1、倒计时正常走）⇒ 无副作用 ✓
#     （底部导航 公会/角色/开始冒险/斗技场/图鉴 在所有界面常驻，但点中间那格不会开图）
#   ⇒ 所以可以放心用作兜底；但仍**必须**保留「先认面板类型」：
#     战斗界面（有战斗胜利/失败/回放战斗）**只能点「关闭」(577,1439)** ✗不能点开始冒险
#     有底部「关闭」按钮的（结算/奖励面板）⇒ 点那个关闭 ✓
#     其余未知面板 ⇒ 点万能位 ✓
#   使用场景：① 整盘读成暗格（面板盖住棋盘）；② 退图 90 秒快超时的最后一救；
#            ③ 连续两轮一个可识别元素都认不到；④ 已认出面板类型（预言石板等）
UNIVERSAL_CLOSE = (360, 1219)


def universal_close(b, log, items=None, probe=None, where='', at=None):
    """关当前弹窗 —— **先认面板类型再决定点哪** ✓（也是任务"异常兜底"，用户 2026-09-26 口径）

    ⚠⚠ 用户 2026-09-26 明确：「**战斗界面还是得点关闭，不能点开始冒险**」✗
      ⇒ 判断顺序：
        ① 认到底部「关闭」按钮（战斗结算/胜利界面都是它）⇒ 点它 ✓
        ② 认到是战斗面板（战斗胜利/失败/回放战斗）但没量到「关闭」⇒ 按实测坐标
           **(577,1439)** 点关闭 ✓（**绝不点 (541,1890)** ✗）
        ③ 其它弹窗 ⇒ 点「中间最下面」万能位 (541,1890) ✓（用户实测：几乎所有弹窗都能关，
           而且关完还在图里）
      ✅ 安全性：用户 2026-09-26 补充「**那边点了非常安全，不会有变化**」⇒ 即使当前没弹窗，
        点它也无副作用（不切图/不走掉）⇒ 可放心当兜底用，但**别当常规动作每轮点** ✗
      关完还要**验证**（probe）⇒ 没关掉就走老兜底（找 X / 关闭符 / 硬脱困），不占死闭环。

    probe = 弹窗的识别文字（用来自查真的关掉了）
    at    = 点出这个弹窗的格子坐标（记下来给调用方拉黑 ⇒ 以后不再点它）
    """
    items = list(items or [])
    cl = bottom_close(items)
    # ⚠ 战斗面板判据必须严格（见 is_battle_panel 的注释：地图上「首领战斗胜利」会让
    #   宽松判据误判 ⇒ 点在棋盘格上 = 乱点 ✗）
    is_battle = is_battle_panel(items)
    if cl:
        _tap(b, cl['cx'], cl['cy'], wait=1.8)
        rec = {'panel_close': 'bottom_close', 'where': where, 'at': (cl['cx'], cl['cy'])}
    elif is_battle:
        # ⚠ 2026-10-02：原来写死 `LAYOUT.sy(959)`（1080p 系的 1439）。
        #   折算后 959 恰好与 `layout.REF['bottom_close']=(385,960)` 吻合（真帧实测 y≈960 ✓），
        #   但既然有单一数据源就别再靠巧合 ⇒ 改走 REF ✓
        _bc = layout_mod.REF['bottom_close']
        b.tap(int(LAYOUT.sx(_bc[0])), int(LAYOUT.sy(_bc[1])), wait=1.8)
        rec = {'panel_close': 'battle_close_fixed', 'where': where,
               'at': (int(LAYOUT.sx(_bc[0])), int(LAYOUT.sy(_bc[1]))),
               'note': '战斗界面点关闭，不点开始冒险'}
    else:
        b.tap(int(LAYOUT.sx(UNIVERSAL_CLOSE[0])), int(LAYOUT.sy(UNIVERSAL_CLOSE[1])),
              wait=1.6)
        rec = {'universal_close': where, 'at': list(UNIVERSAL_CLOSE)}
    if at:
        rec['cell'] = tuple(at) if isinstance(at, (list, tuple)) else at
    gone = True
    if probe:
        gone = panel_gone(b, probe)
        rec['still'] = (not gone)
    if not gone:
        # 万能位没关掉 ⇒ 老路子：找 X / 找关闭符 / 硬脱困 ✓（一样要验证）
        n = close_x_panels(b, b.img())
        x = find_x(ocr_ch(b, tag='uni'))
        if x:
            _tap(b, x['cx'], x['cy'], wait=1.3)
            n += 1
        if not n:
            force_unstick(b, log, 'universal_close', ctx={'tapped': at})
        rec['fallback'] = n
    log.append(rec)
    return True


def block_cell(log, st, cell, why):
    """把某格**拉黑**（本图不再点）——用户 2026-09-26：点出预言石板的那格不要再点 ✓"""
    if not cell:
        return
    try:
        c = (int(cell[0]), int(cell[1]))
    except (TypeError, ValueError, IndexError):
        return
    if isinstance(st, dict):
        st.setdefault('done', set()).add(c)
    log.append({'cell_blocked': why, 'at': list(c)})


def is_reward_panel(b=None, items=None):
    """画面是不是「奖励类弹窗」（莱姆 / 新装备 / 强敌 / 石板……）

    ⛔⛔⛔ 2026-10-02 两次踩坑后的**最终口径**：**只认 OCR 标题，别的一律不算**。
    ----
    ① 第一版：拿 `panel_seen()` 当判据 ⇒ **地图界面也常命中**
       ⇒ 每轮都点写死坐标 ⇒ 用户反馈「怎么刚进图就找莱姆了」✗✗
    ② 第二版：加「棋盘被遮住」当硬闸 ⇒ 仍不够 ——
       **宝库/商人面板弹出时棋盘同样被遮住** ⇒ 又被判成「奖励弹窗」
       ⇒ 真机日志连点 4 格都刷「弹出『获得新装备！』→ 点返回」，
          而那 4 格（5,5/4,5/3,5/2,5）是**宝库区域**，压根没有装备弹窗 ✗✗✗
       （用户原话：「获得新装备只有在获得大拇指装备和之前获得莱姆那个位置出现」）
    ⇒ **结论：奖励弹窗没有可靠的视觉特征能和其它面板区分**
      （都是「暗罩 + 中间一个框 + 底部一个按钮」），
      **唯一可靠的就是 OCR 读到标题** ⇒ 只用它。
    ⚠ 代价：标题读不出时这次弹窗会漏判 —— 接受。
      下一步 `popups()` 的**全屏 OCR** 会再兜一次（那里是原有代码，未被我改宽），
      再不行还有 `force_unstick`。**宁可漏判一次，也不能乱点打断规划** ✓
    ⚠ 安全门：`fixed.A('universal_close')` 在**导航条上**（y=1260），
       那个才是「点错会跳图鉴」的位 ⇒ **这里绝不用它** ✓

    ⛔⛔⛔ 2026-10-10 **「预言石碑被当奖励弹窗点掉」的第二处死代码**（用户报「图上有预言石碑，
       试一试」时抓到；真机取证 `runs/acc1/fs_cmp.png` 三帧对比）：
       本函数原来把 **`L['prophecy']`（预言石板/预言石碑/占卜）也算进"奖励弹窗"** ✗
       而 `popups()` 里的**执行顺序**是：
           ① `close_newequip(...)`  ← 用本函数兜底 ⇒ **命中 prophecy** ⇒ 点「返回」+ return ✗
           ② `if fb(items, *L['prophecy'])`  ← **专门处理预言石板的那支**（永远到不了）
           ④ 特殊地块 `for t in L['special']` → `预言石碑` → `foretell_flow`（也到不了）
       ⇒ **预言石碑一弹面板就被"当奖励弹窗"点返回关掉** ⇒ `foretell_flow` 从来没跑过 ✗✗
          （与 `L['act_on']` 那个死代码**同一族** —— 判据重叠 + 顺序错位 ⇒ 后面的支永不执行）
       实证（本次真机）：
           `popups()` 返回 `'handled'`，日志只有
           `{'newequip_back': 'popup', 'at': (360,835)}` ⇒ **面板被点返回关掉了** ✗
           而同一帧 OCR **明明读到了**「预言石板」`conf=0.99` ✓
       ⇒ 修法：**从本函数判据里去掉 `L['prophecy']`** ——
         它有自己的专门处理器（`popups()` 里 ② 那支，会**正确选卡 + 点确定** ✓）
         ⚠ **不是删功能**：预言石板照样会被处理，只是改由**正确的那支**处理 ✓
         ⚠ 另外三条（莱姆/新装备/强敌）**保留** —— 它们没有"要选卡"的语义，
           点返回就是正确处置 ✓
    """
    try:
        if b is not None and not items:
            try:
                items = b.ocr(min_conf=0.35, tag='reward_panel')
            except Exception:                               # noqa: BLE001
                items = None
        if not items:
            return False
        # ① 认到奖励类标题 —— **唯一可靠判据**（见上面长注释）
        #   ⛔ 2026-10-10：**不要加 `L['prophecy']`**（那会让预言石板被点返回关掉 ✗）
        #   ⛔⛔ 2026-10-12：莱姆改走 `_lime_popup_title`（**独立成条**）
        #     —— `fb(items,'莱姆')` 会被**预言卡正文**骗到（同 `popups()` 那次 ✗）
        return bool(_lime_popup_title(items) is not None
                    or fb(items, *L['newequip'])
                    or fb(items, *L['strong']))
    except Exception:                                       # noqa: BLE001
        return False


def _bottom_ok(items, lo=900, hi=1650):
    """弹窗下半屏的「返回 / 确定 / 确认」按钮（取最靠下那条）"""
    best = None
    for t in items or []:
        s = (t.get('text') or '').strip().replace(' ', '')
        if s in ('返回', '确定', '确认') and LAYOUT.sy(lo) < t['cy'] < LAYOUT.sy(hi):
            if best is None or t['cy'] > best['cy']:
                best = t
    return best


def lime_back(items):
    """「发现莱姆！」弹窗 → 返回按钮坐标（**写死** ✓ PC 端 §1b 提速约定）

    ⚠⚠ 2026-10-02：**不再按 OCR 找「返回」二字**，直接给写死坐标。
       · 写死 = **0ms**；OCR 一条带 = **3.3~3.6s**（实测，见 README §1）
       · 莱姆「返回」1080p 参考系实测 (539,1309) → `fixed.A('lime_back')` 设备系
       · 之前靠 `fb(items,'莱姆')` 判**有没有这个弹窗** + `_bottom_ok` 找按钮，
         两环任一失效（标题 OCR 读不出）就漏判 ⇒ 弹窗留在屏幕上 ⇒ 盖住棋盘 ⇒
         认不到「结束冒险」⇒ 万能位盲点 ⇒ **跳到「图鉴」大页面**（用户 2026-10-02 实测）✗✗
       ⇒ 判据改成**「有没有弹窗形态」**（`is_reward_panel`），不再依赖文字。
    """
    try:
        import fixed as _fx
        return {'cx': _fx.A('lime_back')[0], 'cy': _fx.A('lime_back')[1]}
    except Exception:                                       # noqa: BLE001
        return None


def newequip_back(items):
    """「获得新装备！」弹窗 → 返回按钮坐标（**写死** ✓ 同上）

    1080p 参考系实测 (540,1252) → `fixed.A('equip_back')` 设备系 (360,835) ✓
    """
    try:
        import fixed as _fx
        return {'cx': _fx.A('equip_back')[0], 'cy': _fx.A('equip_back')[1]}
    except Exception:                                       # noqa: BLE001
        return None


def close_newequip(b, items, log, where, at=None, verify=True):
    """⭐「获得新装备！」弹窗 → 点**写死**的返回位关掉；关不掉就强制脱困 ✓

    返回 True 表示「这个弹窗我处理了」（调用方据此 continue / return 'handled'）。

    ⭐⭐ 2026-10-02 按 PC 端 §1b 提速约定改：**直接点写死坐标**（0ms），
       不再「先 OCR 找按钮、找不到才回落」—— 那条路每次要多花一次 OCR（3.3~3.6s）
       且在退图收尾这种**必遇**弹窗的场景纯属浪费。
       坐标：1080p 参考系实测 (540,1252) → `fixed.A('equip_back')` 设备系 (360,835) ✓
    ⚠ 判据 = 「OCR 读到标题」**或** `is_reward_panel()`（后者内部已含
       **「棋盘被遮住」硬闸** ⇒ 正常地图界面恒不成立 ✓）
       ⚠ 2026-10-02 曾用裸 `panel_seen` 兜底 ⇒ 地图界面也命中 ⇒ 每轮都点写死坐标
         ⇒ 规划被打断（用户当场发现「刚进图就找莱姆」）⇒ **已收窄** ✓
    """
    if not (fb(items, *L['newequip']) or is_reward_panel(b=b, items=items)):
        return False
    nb = newequip_back(items)          # 写死坐标 ✓
    if nb is None:                     # 理论上不会（fixed 一定有），保底
        nb = {'cx': 360, 'cy': 835}
    _tap(b, int(nb['cx']), int(nb['cy']), wait=1.6)
    rec = {'newequip_back': where, 'at': (int(nb['cx']), int(nb['cy'])),
           'fixed': True}
    if at:
        rec['tap'] = tuple(at) if isinstance(at, (list, tuple)) else at
    key = 'newequip_%s' % where
    if verify and not panel_gone(b, L['newequip'][0]):
        # 关不掉 ⇒ 别让循环对着面板继续点 ✗（老毛病：不验证就 return handled = 死循环）
        _PANEL_STUCK[key] = _PANEL_STUCK.get(key, 0) + 1
        force_unstick(b, log, 'newequip_%s' % where, ctx={'tapped': at})
        rec['still'] = True
        rec['n'] = _PANEL_STUCK[key]
    else:
        _PANEL_STUCK[key] = 0
    log.append(rec)
    return True


def check_newequip_after_battle(b, log, where, wait=0.5):
    """⭐ 2026-10-05 用户口径（原话）：**「摇色子结束，关闭战斗胜利界面后需要一个获得新装备检测」**

    为什么必须补（现状的洞）：
      · 「获得新装备！」此前**只有**下一轮 `popups()` 的弹窗闸门（`where='popup'`）接得住，
        中间隔着整盘标记扫描 + 规划（真机实测 1.5~4s），而这个弹窗**盖住整盘**
        ⇒ 这一轮的地块分类全成暗格 ⇒ 白判一轮；连 2 张还会走到"被面板挡住"那套兜底 ✗
      · 触发时机（用户 2026-09-26 口径）：「获得新装备只有在**获得大拇指装备**和之前获得
        莱姆那个位置出现」⇒ **摇完色子、结算面板刚关掉**就是它出现的那一刻 ✓
    ⚠ 代价：每次战斗收尾多一次整带 OCR（≈0.7s）—— 只在这一条路径上付，战斗本来就少 ✓
    ⭐ 2026-10-06 提速：**先量有没有模态暗罩**（`modal_veil()`，0 OCR ≈3ms），
      没有 ⇒ 这一次免 OCR（真机 67 次里绝大多数都是这种"干净盘"）✓
      ⇒ 只有**真有面板**时才付那次 OCR；漏判方向是 fail-safe（见 `modal_veil()`）
    ⚠ 结构上：**它不是唯一防线**。`popups()` 的 `popup` 闸门、`finish_map` 的 `finish`、
      `final_collect` 的 `collect`/`collect3` 都还在 ⇒ 这一次没赶上也不会漏 ✓

    ⇒ True = 确实有弹窗并关掉了；False = 没有 / 出错（出错只记日志，绝不让它拖垮战斗收尾）
    """
    try:
        if wait:
            time.sleep(wait)                 # 给弹窗一点出现的余量（只等画面，不点任何东西）
        b.snap('newequip_chk')
        # ⭐⭐⭐ 2026-10-06 提速（BUG-3）：先花 ≈3ms 判「整屏有没有模态暗罩」，
        #   没有 ⇒ 这一次 **完全不用 OCR**（省 ≈1.1s）✓
        #   ⚠ 判的是**睡完之后的这一帧**（就是原来要送 OCR 的那一帧）⇒ 决策点不变；
        #     只把"读文字"换成"量亮度"，**单向**使用：只有"明确没有暗罩"才免 OCR，
        #     拿不到帧/出错/有暗罩 ⇒ 一律照旧 OCR ✓（真机定标见 `modal_veil()`）
        #   ⚠ 那 0.5s `sleep` **保留**：它是用户口径要的"给弹窗出现的余量"，
        #     不在这条提速里动（改了就是动用户已定的行为）✓
        if not modal_veil(b):
            log.append({'newequip_check': where, 'hit': False, 'ocr': 'skip_no_veil',
                        'note': '整屏无模态暗罩 ⇒ 免 OCR（省 ≈1.1s）；有弹窗必有暗罩'})
            return False
        it = b.ocr(band=(LAYOUT.sy(87), LAYOUT.sy(1040)), tag='newequip')
        if close_newequip(b, it, log, where):
            say('       · 获得新装备！→ 点返回')
            status('拿到新装备 · 返回')
            return True
        log.append({'newequip_check': where, 'hit': False})
    except Exception as _e:       # noqa: BLE001
        log.append({'newequip_check': where, 'err': repr(_e)[:80]})
    return False


#: flush 的写盘序号（让 tmp 文件名唯一，见 flush 内注释）
_FLUSH_SEQ = 0


def flush(log):
    # ⭐ v1.12：把最新日志挂到模块全局 ⇒ `dump_summary()` 能把它抄一份到**公共目录**
    #   （release 包不可 run-as，私有 runs/ 拿不出来；朋友的手机只能靠这个文件回传 ✓）
    try:
        global _GLOBAL_LOG
        _GLOBAL_LOG = log
    except Exception:       # noqa: BLE001
        pass
    try:
        import json
        # ⛔⛔ 2026-10-19 **原子替换**（真机事故：GUI 撞上半截文件 ⇒ 棋盘落后一张）
        #   ---- 病 ----
        #     `open(LOG_PATH, 'w')` 会**先把文件截断**，再 json.dump（~200KB，几十 ms）
        #     而 GUI 每 2 秒 poll 一次、且用 **mtime/size 指纹**判"变了没"
        #     ⇒ 截断瞬间 size 变小 ⇒ 指纹变 ⇒ **立刻去解析半截文件**
        #     ⇒ 真机日志：`JSONDecodeError('Expecting property name enclosed in double qu…')`
        #     ⇒ `LoopLogTail.poll()` 解析失败时**保留上次 events**
        #     ⇒ 棋盘停在**上一张图** ✗✗（用户报："实时棋盘用的上一张图的"）
        #   ---- 修法 ----
        #     ① 先写同目录的 `.tmp`（此时正式文件**完好无损**）
        #     ② `os.replace()` 一次性换名（Windows/POSIX 都是**原子**的 ✓）
        #     ⇒ 读侧要么看到**旧完整文件**、要么看到**新完整文件**，绝无半截 ✓
        # ⚠⚠ **tmp 名必须唯一**（压力测试抓到的：固定名会互相截断 → 8 次半截）
        #   · 固定 `.tmp` 时，上一轮还没 replace 掉、下一轮又 open('w') 截断它
        #     ⇒ 正在被换名的那个 tmp 内容被改 ⇒ 读侧读到半截 ✗
        #   ⇒ 带 pid + 单调计数 ⇒ 每次写都是独立文件 ✓
        #   ⇒ `os.replace` 换走后 tmp 就不存在了，不会堆积 ✓
        global _FLUSH_SEQ
        try:
            _FLUSH_SEQ = int(_FLUSH_SEQ) + 1
        except Exception:                   # noqa: BLE001
            _FLUSH_SEQ = 1
        _tmp = '%s.tmp.%d.%d' % (LOG_PATH, os.getpid(), _FLUSH_SEQ)
        with open(_tmp, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        # ⚠ **Windows 上 `os.replace` 会被读侧挡住**（实测 WinError 5 拒绝访问）
        #   原因：Windows 的 MoveFileEx 要对目标文件有写权限，
        #        而 GUI 正以只读方式打开它 ⇒ 失败（POSIX 没这问题）
        #   ⇒ 短重试 5 次 × 20ms（读侧关闭句柄后就成功了 ✓）
        _rep_ok = False
        for _k in range(5):
            try:
                os.replace(_tmp, LOG_PATH)
                _rep_ok = True
                break
            except Exception:               # noqa: BLE001
                try:
                    time.sleep(0.02)
                except Exception:           # noqa: BLE001
                    pass
        if not _rep_ok:
            # 全失败 ⇒ 别把 tmp 留着发霉，也别不落盘 ✗
            try:
                os.remove(_tmp)
            except Exception:               # noqa: BLE001
                pass
            raise IOError('os.replace 重试 5 次仍失败')
    except Exception:
        # ⚠ 兜底：原子替换失败（权限/磁盘满/跨盘）⇒ 退回老写法，**不能因此不落盘** ✗
        try:
            import json as _js_f
            with open(LOG_PATH, 'w', encoding='utf-8') as f:
                _js_f.dump(log, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
    # ⭐ 统计**边跑边落盘**：这样即使被「停止」（taskkill /F 杀进程）也能拿到最新总结
    dump_summary()


# ⭐⭐ 2026-09-27 用户要求：每连刷 N 张图，去背包→装备→**一键升级**
BAG_EVERY = 10          # 每几张图升级一次（0 = 关闭 ✓）
BAG_STEPS = (
    # (说明,           候选文字（命中任一即点 ✓）,        点完等几秒, 必须命中?)
    ('打开背包',       ('背包', '道具'),                    2.2, True),
    ('进装备页',       ('装备', '装备栏', '装 备'),          2.2, False),
    ('一键升级',       ('一键升级', '一键升阶', '一键强化'),   2.6, True),
    ('确认',           ('确定', '确认', '是'),               2.6, False),
    ('返回',           ('返回', '关闭'),                    2.2, False),
)


_UI_TPL_CACHE = {}
# ⭐ 2026-10-01：背包 UI 的关键帧落**公共目录**（诊断用；release 包不可 run-as ⇒ 私有拿不出来）
BAG_PUB_DIR = '/sdcard/Download/autoexplore/bagdbg'
# ⭐⭐ 落帧开关（**性能相关，用户 2026-10-01 问「跑一张图会不会变慢」**）：
#   · BAG_DUMP=False ⇒ 完全不落帧（零 I/O 零编码开销 ✓ 稳定后建议关）
#   · BAG_DUMP_ALL=False（默认）⇒ **只落"值得看"的帧**：每轮第一张起点帧 + 公会/背包结果帧
#     + 每次失败/兜底帧；routine 的成功帧不落 ⇒ 默认每图 ~3~5 张（≈0.1~0.3s/张 PNG 编码）
BAG_DUMP = os.environ.get('MAPBOT_BAG_DUMP', '1') != '0'
BAG_DUMP_ALL = os.environ.get('MAPBOT_BAG_DUMP_ALL', '0') == '1'
# 模板多尺度范围（老版 0.90~1.15 对"面板随分辨率非等比缩放"不够；放宽到 0.80~1.20 ✓）
_BAG_TPL_SCALES = (0.80, 0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15, 1.20)

def _find_ui_tpl(b, name, region=None, thr=0.80):
    """⭐⭐ 2026-09-30 治本（用户：「换个分辨率不就又用不了了」）：公会/背包 UI 入口改
    **模板匹配**，不再依赖写死的归一化坐标 —— 公会/背包窗口的 Unity UI **不守探索棋盘的
    锚定模型**（A 类弹窗/弹性布局），硬编码坐标换分辨率必错位（720x1600 实测 bag_not_open）。
    模板 = 归一化 1080x1920 帧系裁剪（templates/ui/，build_pack 随包分发），
    在当前归一化帧上多尺度 TM_CCOEFF_NORMED（0.9~1.15 容忍长屏非等比压缩）。
    region=(x0,y0,x1,y1) 限定搜索区。返回 (cx,cy,score) 或 None。"""
    try:
        import cv2
        import numpy as np
    except Exception:       # noqa: BLE001
        return None
    tpl = _UI_TPL_CACHE.get(name)
    if tpl is None:
        path = os.path.join(_MAPBOT_ROOT, 'templates', 'ui', name)
        if not os.path.exists(path):
            log_note = 'ui_tpl_missing:' + name
            say('   ⚙ ' + log_note)
            return None
        tpl = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        _UI_TPL_CACHE[name] = tpl
    if tpl is None:
        return None
    img = b.img()
    if img is None:
        return None
    H, W = img.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, W, H)
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    best = None
    th, tw = tpl.shape[:2]
    for s in (0.90, 0.95, 1.0, 1.05, 1.1, 1.15):
        w, h = int(tw * s), int(th * s)
        if w < 16 or h < 16 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sub.astype(np.float32), t.astype(np.float32),
                                cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, mxl[0] + w / 2 + x0, mxl[1] + h / 2 + y0)
    if best and best[0] >= thr:
        return (int(best[1]), int(best[2]), round(best[0], 3))
    return None


def _pub_dump(name, img, important=True):
    """把一帧写一份到**公共目录** `/sdcard/Download/autoexplore/bagdbg/`（诊断用 ✓）

    为什么不用私有 `runs/`：**release 包不可 `run-as`** ⇒ 真机截图根本拿不出来 ✗
    （Java 侧 `OverlayService.dump()` 就是往这儿写的，同一个 uid、同一档权限 ✓）

    ⚠ 性能（用户 2026-10-01 问「会不会变慢」）：一次 PNG 编码 + 落盘 ≈ 0.1~0.3 秒
    ⇒ **默认只落"值得看"的帧**（`important=True`：起点/公会/背包结果/失败/兜底）；
    routine 成功帧（装备页/确认框…）只在 `BAG_DUMP_ALL=1` 时才落 ✓；
    总开关 `BAG_DUMP=0`（或环境变量 `MAPBOT_BAG_DUMP=0`）⇒ 一张都不落 ✓
    """
    if not BAG_DUMP:
        return None
    if not important and not BAG_DUMP_ALL:
        return None
    try:
        if img is None:
            return None
        # ⭐⭐⭐ 2026-10-03 修「诊断帧存不下来」（真机 acc2 事故：日志说"已存档"，
        #   但**设备上和 PC 上都没有那张 `board_hidden_r0.png`** ⇒ 事后无法定位误判 ✗✗）
        #   两个原因：
        #     ① 调用方传进来的 name 里带反斜杠（如 `'bagdbg\\board_hidden_r0'`）——
        #        在 Windows 上它被当成**子目录**（目录不存在 ⇒ 写入失败 ✗），
        #        在 Android 上它更不是分隔符 ⇒ 文件名里多个反斜杠 ✗
        #     ② 整个函数 `except: return None` ⇒ **写失败静默无声** ✗
        #        （调用方看到返回 None 只记一条 `*_dump_fail`，人根本不会去看 ✗）
        #   ⇒ 修法：名字里的 `\\` `/` 一律换成 `_`；**确保父目录存在**；
        #     写失败**必须 say 出来**；并且在 **PC 侧 `runs/<tag>/bagdbg/` 再落一份副本**，
        #     这样离线排查时一定找得到 ✓
        _safe = str(name).replace('\\', '_').replace('/', '_')
        import cv2
        _out = []
        # ⚠ `BAG_PUB_DIR` 是 **Android 路径**（`/sdcard/...`）—— PC 上写不到模拟器里；
        #   而且**光判 `isdir('/sdcard')` 不可靠**：以前某次运行已经在**盘根**建出了
        #   一个野目录 `D:\sdcard\...`（自测实证 ✗）⇒ 必须用**真正的平台判据** ✓
        #   （`MAPBOT_ANDROID` 环境变量是全仓既有的 Android 标记，见 3661 行 ✓）
        _is_android = bool(os.environ.get('MAPBOT_ANDROID')) or sys.platform.startswith('linux')
        _dirs = [d for d in (BAG_PUB_DIR, os.path.join(RUNS, 'bagdbg'))
                 if d != BAG_PUB_DIR or _is_android]
        if not _dirs:
            _dirs = [os.path.join(RUNS, 'bagdbg')]
        for _d in _dirs:
            try:
                if not os.path.isdir(_d):
                    os.makedirs(_d, exist_ok=True)
                p = os.path.join(_d, _safe + '.png')
                ok, buf = cv2.imencode('.png', img)
                if not ok:
                    say('   ⚠ 诊断帧编码失败（%s）' % _safe)
                    continue
                buf.tofile(p)
                _out.append(p)
            except Exception as _e2:            # noqa: BLE001
                say('   ⚠ 诊断帧落盘失败（%s → %s）：%r' % (_safe, _d, _e2))
        return _out[0] if _out else None
    except Exception as e:       # noqa: BLE001
        say('   ⚠ 诊断帧存档异常：%r' % (e,))
        return None


def _cap_close(img, log=None, why=''):
    """把「当前屏出现了 关闭/确定 按钮」的**整帧**存一份（原生 720p）✓

    ⭐⭐⭐ 2026-10-03 用户口径：「**多攒一些关闭吧**」
    背景：战斗等待现在靠"165px 窄条 OCR"每 0.5s 查一次「关闭」（~0.12s/次）；
        我试过直接拿 acc1 那张真帧抠模板 ⇒ **泛化失败**（来源帧 1.000，但 acc2 那帧只有
        0.465、比负样本 0.592 还低 ✗）⇒ 各面板的「关闭」长得不一样 ✗
        要做成**模板快查（7ms/次，比 OCR 便宜 ~17 倍）**，必须**多种面板**的样本 ✓
    ⇒ 这里在每次"真正认得关闭"时顺手存一张整帧 ⇒ 跑几天就攒够样本了 ✓
    上限 `CLOSE_CAP_MAX` 张（默认 200），写 `runs/cap_close/`，失败只记日志不抛 ✓
    """
    if not CLOSE_CAP or img is None:
        return None
    if _CLOSE_CAP_N[0] >= CLOSE_CAP_MAX:
        return None
    try:
        import cv2
        d = os.path.join(RUNS, 'cap_close')
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, 'close_%s_%s_%03d.png'
                         % (why or 'x', time.strftime('%m%d_%H%M%S'), _CLOSE_CAP_N[0]))
        ok, buf = cv2.imencode('.png', img)
        if not ok:
            return None
        buf.tofile(p)
        _CLOSE_CAP_N[0] += 1
        if log is not None:
            log.append({'cap_close': p, 'why': why, 'n': _CLOSE_CAP_N[0]})
        return p
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'cap_close_fail': repr(e)[:80]})
        return None


CLOSE_CAP = True            # 收集「关闭/确定」样本（攒够后做成模板快查 ✓）
CLOSE_CAP_MAX = 200
_CLOSE_CAP_N = [0]


def _tpl_hit(img, name, region=None, scales=None, thr=0.80):
    """在**给定图像**（归一化帧 or 弹窗帧）上多尺度模板匹配 → (cx, cy, score) | None

    `_find_ui_tpl` 只能吃 `b.img()`（归一化帧）；这里抽出"吃任意帧"的版本，
    让背包流程能在**弹窗帧**上也做匹配（锚设备中心 ⇒ 分辨率无关的第二条路 ✓）
    """
    try:
        import cv2
        import numpy as np
    except Exception:       # noqa: BLE001
        return None
    tpl = _UI_TPL_CACHE.get(name)
    if tpl is None:
        path = os.path.join(_MAPBOT_ROOT, 'templates', 'ui', name)
        if not os.path.exists(path):
            say('   ⚙ ui_tpl_missing:' + name)
            return None
        tpl = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        _UI_TPL_CACHE[name] = tpl
    if tpl is None or img is None:
        return None
    H, W = img.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, W, H)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(x1)), min(H, int(y1))
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    best = None
    th, tw = tpl.shape[:2]
    for s in (scales or _BAG_TPL_SCALES):
        w, h = int(tw * s), int(th * s)
        if w < 16 or h < 16 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sub.astype(np.float32), t.astype(np.float32),
                                cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, mxl[0] + w / 2 + x0, mxl[1] + h / 2 + y0)
    if best and best[0] >= thr:
        return (int(best[1]), int(best[2]), round(best[0], 3))
    return None


def _bag_find(b, keys, prefer='top', tag='', exact=False):
    """⭐ 双通道找**文字目标** → (cx, cy, ch, text) 或 None（ch: 'norm' | 'dlg'）

    ① 归一化帧 `b.ocr()`（点用 `b.tap`）—— PC/9:16 与真机都走这条 ✓
    ② 查不到且 C>0（真机高分辨率）⇒ 补一次**弹窗帧** `b.ocr_dlg()`（点用 `b.tap_dlg`）
       —— 弹窗系坐标**锚设备屏幕中心**，分辨率一变它自己跟着缩放 ✓
    ⚠ **一律不做绝对 y 过滤**（老版 `cy<700` 在真机上把页签滤掉了 ✗）；同一通道里多个
      候选按**面板内相对位置**挑：`prefer='top'` 取最上（页签在面板顶部 ✓）、
      `prefer='bottomright'` 取最右下（按钮在面板右下 ✓）
    """
    cands = []
    try:
        cands.append(('norm', b.ocr(tag=(tag + '_n') if tag else None)))
    except Exception:       # noqa: BLE001
        pass
    for ch, its in cands:
        hit = _bag_pick(its, keys, prefer, exact)
        if hit:
            return (int(hit['cx']), int(hit['cy']), ch, (hit.get('text') or ''))
    if dlg_c() and hasattr(b, 'ocr_dlg'):
        try:
            its2 = b.ocr_dlg(tag=(tag + '_d') if tag else None)
        except Exception:       # noqa: BLE001
            its2 = []
        hit = _bag_pick(its2, keys, prefer, exact)
        if hit:
            return (int(hit['cx']), int(hit['cy']), 'dlg', (hit.get('text') or ''))
    return None


def _bag_pick(items, keys, prefer='top', exact=False):
    """在一组 OCR 条目里挑目标（见 `_bag_find`）"""
    hits = []
    for i in (items or []):
        t = (i.get('text') or '').replace(' ', '')
        if not t:
            continue
        if exact:
            ok = t in keys
        else:
            ok = any(k in t for k in keys)
        if ok:
            hits.append(i)
    if not hits:
        return None
    if prefer == 'bottomright':
        return max(hits, key=lambda z: (z.get('cy', 0), z.get('cx', 0)))
    return min(hits, key=lambda z: (z.get('cy', 0), z.get('cx', 0)))


def _panel_tap(b, x, y, ch='norm', log=None, what=''):
    """**面板类**点击：走完整阶梯（同点 → 下移 45px → 长按 350ms → **换通道**）✓

    ⭐ 2026-10-01 全分辨率体检：面板按钮有两套坐标系（归一化系 / 弹窗系），
    写死的常量必然只对其中一套成立 ⇒ `_tap_verified(tries=2)` 的"只重试 1 次"不够：
    第 1 下没生效时**必须允许换通道再试**（跨通道那一级）。
    ⚠ 这不会造成"连点"：`_tap_verified` 用 `b.tap` 的真实回报判生效，
    生效就立刻返回 ⇒ 正常情况**只点 1 下** ✓
    """
    return _tap_verified(b, x, y, ch, log=log, what=what, tries=4)


def _bag_tap(b, cx, cy, ch, wait=1.6):
    """按通道点击（弹窗系必须 `tap_dlg`，真机上用 b.tap 会偏 C≈200px ✗）
    → **返回"画面变没变"**（kt 侧监听；None=没等/未知 ✓）"""
    if ch == 'dlg':
        return b.tap_dlg(int(cx), int(cy), wait=wait)
    return b.tap(int(cx), int(cy), wait=wait)


def bag_upgrade(b, log, tag='bag'):
    """⭐ 每 N 张图去背包「装备」页做一键升级（用户 2026-09-27 要求 ✓）

    流程**复用 use_supply 那套**（用户：「和之前一样」✓）：
        公会 → 背包 → **装备页签** → 一键升级 →（确定）→ 关背包回地图界面
    ✅ 页签与按钮**优先按 OCR 文字找** ✓（不写死坐标 ✓）；找不到才用兜底坐标 ✓
    ✅ **必须站在选图界面**才动手（和 use_supply 同款安全闸 ✓ 免得在地图里误点棋盘 ✗）

    ⭐⭐ 2026-10-01 **重写：全分辨率适用**（用户要求「重新搞自动升星，要求全分辨率适用」）
    ────────────────────────────────────────────────────────────────────────
    老流程在真机（1280×2772）上的病（`_verify/phone_stamina_0930/autoexplore_bag*.log`）：
      · 「装备」页签判据带**绝对 y 过滤**（`cy < 700`）⇒ 面板位置随分辨率一变就被滤掉
        ⇒ 实测永远走兜底坐标；
      · 「一键升星」在**归一化帧**里认不到、模板也没命中（面板在真机上未必落进 toRef 的
        可见区）⇒ 全程碰运气；
      · 收尾把「进入地图」当点击候选 ⇒ 真开图（-25 体力）✗（已单独修 ✓）。
    新口径（四条，都是"分辨率无关"的）：
      ① **双通道识别**：每一步先查**归一化帧**（`b.ocr` → `b.tap`），没查着再查**弹窗帧**
         （`b.ocr_dlg` → `b.tap_dlg`）—— 弹窗系坐标**锚设备屏幕中心**，天生随分辨率缩放 ✓
         （PC/9:16 的 C=0 ⇒ 只有归一化通道，行为与旧版一致 ✓）
      ② **纯文字驱动**：目标 = 「背包」/「装备」/「一键升星·一键升级·一键升阶·一键强化」/
         「确定·确认」；**取消一切绝对 y 过滤**，改在**同一面板内按相对位置挑**
         （页签取**最上**、按钮取**最右下** ✓）
      ③ **模板两帧 × 多尺度**（0.80~1.20）兜底 —— 仍找不到才退锚点坐标，且**只在
         "已确认在背包里/在公会界面"**时才允许（绝不在任意画面盲点 ✗）
      ④ **真机自证**：每步把「用哪个通道 / 命中什么 / 点哪」`say` 出来，关键帧写一份到
         `/sdcard/Download/autoexplore/bagdbg/`（release 包不可 `run-as` ⇒ 私有 runs/ 拿不出来，
         公共目录 PC 侧能直接 `adb pull` 回来离线核对 ✓）
    """
    try:
        b.snap(tag + '0')
        items = b.ocr(tag=tag)
        txt = [i['text'] for i in items]
        in_map_now = any('结束冒险' in t for t in txt)
        on_select = any(any(k in t for k in ('进入地图', '快速扫荡', '开始冒险', '星界秘境'))
                        for t in txt)
        if in_map_now or not on_select:
            log.append({'bag': 'skip_not_on_select', 'in_map': bool(in_map_now),
                        'on_select': bool(on_select), 'texts': txt[:14]})
            say('   ⚙ 背包升级：现在不在选图界面 ⇒ 跳过（免得误点地图格 ✗）')
            status('不在选图界面 · 跳过升星')
            return False
        say('   ⚙ 背包一键升级：开始（复用补给的流程 ✓）')
        status('装备升星中…')

        # ① 公会（看不到 邮件/商店/招募 就先去公会 ✓）
        # ② 背包（⭐ 2026-09-30 深夜重构：实证「公会界面直接点 BAG_BTN」可开背包
        #    （bag_step2 手动验证 ✓），但「点 GUILD_BTN 按钮再点背包」的时序不稳
        #    （公会界面内点公会按钮后的画面状态不确定，v0.45 在公会界面 3 轮全失败）
        #    ⇒ 反转：**每轮先点 BAG_BTN 查「背包」，没开再 GUILD_BTN 进公会**，共 3 轮。
        #    起点已在公会 ⇒ 第 1 轮命中；起点在选图界面 ⇒ 第 1 轮点空、第 2 轮命中 ✓）
        # ⭐⭐ 2026-09-30 深夜【点击有效性自检】：模拟器 MuMu 的无障碍手势对公会界面会
        #   **静默失效**（dispatchGesture 返回 True 但事件丢失；input tap 同坐标有效 ——
        #   2026-09-30 对照实验）。失效时升级流程每次点击都打在空气上或误点别处
        #   （用户：「一直打开着头像界面却不知道在干嘛」——失败兜底的 _close_bag 盲点万能位）。
        #   ⇒ 判据：点击后**画面均值差 <2.0 = 零变化**，连续 2 轮 ⇒ 判定通道失效 ⇒
        #     **立即放弃**（不重试、不 _close_bag 盲点），say 明确报错让人手动升星 ✓
        import numpy as _np
        _frame0 = b.img()
        _pub_dump(tag + '_select', _frame0)      # 起点帧（选图界面）也留一份 ✓
        _dead = 0
        items = []
        opened = False
        # ⭐⭐ 2026-10-01 真机修（用户报「装备升星脚本出问题了，没有正常升星」）：
        #   现象：`⚙ 背包一键升级：开始` 之后 15 秒 → `背包没打开（重试 3 次）✗`（真机 15:34 实锤）
        #   根因（结构性问题）：原流程**第 1 轮就盲点「公会界面的 BAG_BTN(964,1680)」**，
        #   可此刻人站在**选图界面** ⇒ 那一击落点不可控（真机上可能点开图鉴等面板）
        #   ⇒ 之后"点公会 → 找背包图标"全在**错误画面**上做 ⇒ 3 轮全失败 ✗
        #   ⇒ 改成：**先确认在不在公会界面**（公会/邮件/商店/招募 任一），不在就
        #     「OCR 找『公会』二字进公会」（分辨率无关 ✓）→ 找不到才退写死坐标；
        #     进公会之后才找背包图标 ✓。每轮的关键信息**直接 say 出来**（结构化条目要等
        #     `flush(log)` 跑完才打印，真机上根本来不及看 ✗）
        # ⚠ 判据函数一律用**模块级** `_guild_on()`（2026-10-01：写成嵌套函数导致
        #   `NameError: free variable 'i' ...`，整个升星流程当场崩 —— 真机 15:41/15:51 实锤 ✗）
        for _try in range(3):
            # ① 先站到公会界面（不在才点，避免在公会界面里重复盲点）
            if not _guild_on(items):
                _g = None
                for _i in items:
                    if (_i.get('text') or '').strip().replace(' ', '') in ('公会', '公會'):
                        _g = _i
                        break
                _gat = (_g['cx'], _g['cy']) if _g else GUILD_BTN
                b.tap(_gat[0], _gat[1], wait=2.8)
                log.append({'bag': 'open_guild', 'at': _gat,
                            'by': 'ocr' if _g else 'fallback', 'try': _try})
                say('   ⚙ 升星第 %d 轮：先进公会 (%d,%d) %s'
                    % (_try + 1, _gat[0], _gat[1],
                       '（OCR 找到「公会」✓）' if _g else '（写死坐标）'))
                time.sleep(1.2)      # 公会界面静止时 wait_stable 会秒过 ⇒ 固定等
                b.snap(tag + 'g%d' % _try)
                items = b.ocr(tag=tag + 'g')
                _pub_dump('%sg%d_guild' % (tag, _try), b.img())
                if not _guild_on(items):
                    say('   ⚠ 点了公会但画面不像公会界面：认到 %s'
                        % ([i['text'] for i in items][:10],))
                    log.append({'bag': 'guild_not_reached', 'try': _try,
                                'texts': [i['text'] for i in items][:12]})
            # ② 开背包（⭐ 2026-10-01：**文字优先** —— 真机公会帧里「背包」二字清清楚楚
            #    （离线核对：`guild_bag_icon.png` 在真机帧上命中 **(964,1680) score 0.978** ✓，
            #    与写死坐标 BAG_BTN 完全一致）；顺序 = 文字「背包」→ 模板（归一化/弹窗两帧）
            #    → 锚点坐标（**只在已确认公会界面内**才允许 ✓）
            _bk = None
            for _i in (items or []):
                if (_i.get('text') or '').strip().replace(' ', '') in ('背包', '道具'):
                    _bk = _i
                    break
            if _bk:
                _tap_verified(b, _bk['cx'], _bk['cy'], 'norm', log=log,
                              what='背包(文字)')
                log.append({'bag': 'open_bag_text', 'at': (_bk['cx'], _bk['cy']),
                            'text': _bk.get('text'), 'try': _try})
                say('   ⚙ 开背包：OCR 找到「%s」(%d,%d) ✓'
                    % (_bk.get('text'), _bk['cx'], _bk['cy']))
            else:
                _hit, _ch = _tpl_hit(b.img(), 'guild_bag_icon.png',
                                     region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1000)),
                                             1080, 1920)), 'norm'
                if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                    _hit = _tpl_hit(b.img_dlg(), 'guild_bag_icon.png')
                    _ch = 'dlg'
                if _hit:
                    _tap_verified(b, _hit[0], _hit[1], _ch, log=log,
                                  what='背包(模板%.2f)' % _hit[2])
                    log.append({'bag': 'open_bag_tpl', 'at': (_hit[0], _hit[1]),
                                'score': _hit[2], 'ch': _ch, 'try': _try})
                    say('   ⚙ 开背包：模板命中 (%d,%d) %.2f（%s）'
                        % (_hit[0], _hit[1], _hit[2],
                           '弹窗帧' if _ch == 'dlg' else '归一化帧'))
                else:
                    _tap_verified(b, BAG_BTN[0], BAG_BTN[1], 'norm', log=log,
                                  what='背包(锚点)')
                    log.append({'bag': 'open_bag_anchor', 'at': BAG_BTN, 'try': _try})
                    say('   ⚙ 开背包：文字/模板都没中 ⇒ 公会界面锚点 (%d,%d)' % BAG_BTN)
            b.snap(tag + '1')
            items = b.ocr(tag=tag)
            _pub_dump('%s%d_bag' % (tag, _try), b.img())
            # ⭐⭐ 判"开了没"用**颜色判据**（真机 OCR 读不到标题「背包」二字 ✗）
            _op, _how = _bag_panel_open(b, items)
            if _op:
                opened = True
                say('   ⚙ 背包已打开 ✓（判据：%s）' % _how)
                log.append({'bag': 'bag_open_ok', 'how': _how, 'try': _try})
                break
            # ⭐⭐ 可诊断：这一轮点了哪、模板分数多少、屏幕上认到啥（logcat 直接可见 ✓）
            _txts = [i['text'] for i in items][:12]
            _where = (('模板命中 (%d,%d) %.2f' % (_hit[0], _hit[1], _hit[2])) if _hit
                      else ('写死坐标 (%d,%d)' % BAG_BTN))
            say('   ⚙ 开背包第 %d 轮未成：%s ⇒ 屏上认到 %s' % (_try + 1, _where, _txts))
            log.append({'bag': 'open_bag_miss', 'try': _try, 'at': _where, 'texts': _txts})
            if _hit is not None:
                # ⭐ 硬判据（v0.52：均值差判据被轮播横幅干扰——横幅一动 diff 就超阈值）：
                #   **模板命中背包图标、点击却没开出背包 = 点击通道失效铁证** ⇒ 立即放弃。
                #   重试同一点击无意义；GUILD_BTN/万能位兜底才是「打开着头像界面不知道在干嘛」
                #   的乱点源头 ⇒ 坚决不点（v0.53）
                say('   ⚠ 模板命中背包图标但点击未生效 ⇒ 放弃升星（点击通道异常），请手动操作')
                log.append({'bag': 'abort_tap_dead', 'at': (_hit[0], _hit[1]), 'try': _try})
                return False
            _now = b.img()
            if _frame0 is not None and _now is not None:
                _diff = float(_np.mean(_np.abs(
                    _now.astype(int) - _frame0.astype(int))))
            else:
                _diff = 999.0
            if _diff < 2.0:
                _dead += 1
                log.append({'bag': 'tap_no_effect', 'try': _try, 'diff': round(_diff, 2),
                            'tpl_hit': bool(_hit)})
                # ⭐ 判据收紧（v0.51 实测 diff=1.6 只触发 1 次没拦住 _close_bag 盲点）：
                #   **模板明明命中了图标、点了却零变化 = 通道失效铁证 ⇒ 一次即放弃**；
                #   兜底坐标轮连续 2 次零变化也放弃
                if _hit is not None or _dead >= 2:
                    say('   ⚠ 点击通道在此界面无效（画面零变化）⇒ 放弃升星，请手动操作')
                    log.append({'bag': 'abort_dead_channel', 'tpl_hit': bool(_hit)})
                    return False
            else:
                _dead = 0
                _frame0 = _now
            time.sleep(1.2)
        if not opened:
            _ftxts = [i['text'] for i in items][:20]
            log.append({'bag': 'bag_not_open', 'texts': _ftxts})
            say('   ⚙ 背包没打开（重试 3 次 ✗）｜最后一屏认到：%s' % (_ftxts,))
            if _dead < 2:        # 通道失效时绝不 _close_bag 盲点（乱点源头 ✗）
                _close_bag(b, items, log)
            return False
        # ③ **装备页签**（⭐ 2026-10-01 真机修正：**页签只在弹窗帧里** ⇒ 直接走
        #    `_bag_switch_tab('装备')`（实测弹窗帧 @dlg(346,314) ✓）；旧写法在归一化帧里
        #    找「装备」恒失败 ⇒ 退锚点 (370,360)（真机上那里是别的东西 ✗））
        _ok_tab = _bag_switch_tab(b, '装备', log=log, tag=tag)
        if not _ok_tab:
            _tab = _bag_find(b, ('装备', '装备栏'), prefer='top', tag=tag + '_tab')
        if _tab:
            _bag_tap(b, _tab[0], _tab[1], _tab[2], wait=1.6)
            log.append({'bag': 'equip_tab', 'at': (_tab[0], _tab[1]),
                        'by': 'ocr', 'ch': _tab[2], 'text': _tab[3]})
            say('      · 装备页 → 点 (%d,%d)（%s OCR ✓「%s」）'
                % (_tab[0], _tab[1], '弹窗帧' if _tab[2] == 'dlg' else '归一化帧', _tab[3]))
        else:
            # 兜底：模板（两帧 × 多尺度）→ 仍没有才用锚点坐标（**已确认在背包里**才允许 ✓）
            _hit, _ch = _tpl_hit(b.img(), 'bag_tab_equip.png',
                                 region=(0, 0, 1080, int(LAYOUT.sy(1100)))), 'norm'
            if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                _hit = _tpl_hit(b.img_dlg(), 'bag_tab_equip.png')
                _ch = 'dlg'
            if _hit:
                _bag_tap(b, _hit[0], _hit[1], _ch, wait=1.6)
                log.append({'bag': 'equip_tab_tpl', 'at': (_hit[0], _hit[1]),
                            'score': _hit[2], 'ch': _ch})
                say('      · 装备页 → 模板命中 (%d,%d) %.2f（%s）'
                    % (_hit[0], _hit[1], _hit[2], '弹窗帧' if _ch == 'dlg' else '归一化帧'))
            else:
                # ⭐ 2026-10-01 全分辨率体检修：旧兜底点 `EQUIP_TAB=(370,360)`（归一化系）——
                #   真机实测「装备」页签在**弹窗系** dlg(345,315) ⇒ 设备 y≈620；
                #   而 ref(370,360) ⇒ 设备 y≈923 ⇒ **差 ~300px，点空** ✗
                #   根因：页签落在 `toRef()` 丢弃的弹性带（真机设备 y 488~852）里 ⇒ 归一化系没有它 ✗
                _pt = BAG_TAB_DLG.get('装备', EQUIP_TAB)
                _panel_tap(b, _pt[0], _pt[1], 'dlg', log=log, what='装备页(弹窗系标定)')
                log.append({'bag': 'equip_tab_anchor_dlg', 'at': _pt})
                say('      · 装备页 → 页签没认到 ⇒ 弹窗系标定坐标 %s' % (_pt,))
        _pub_dump(tag + '_equip', b.img(), important=False)
        # ④ 一键升星（⭐ 重写：文字（双通道，取**最右下** = 面板右下那颗按钮 ✓）
        #    → 模板（两帧 × 多尺度）→ 锚点兜底（已确认在背包里 ✓））
        b.snap(tag + '2')
        _up = _bag_find(b, ('一键升星', '键升星', '一键升级', '一键升阶', '一键强化'),
                        prefer='bottomright', tag=tag + '_up')
        if _up:
            _bag_tap(b, _up[0], _up[1], _up[2], wait=2.6)
            log.append({'bag': 'upgrade_tap', 'text': _up[3], 'at': (_up[0], _up[1]),
                        'by': 'ocr', 'ch': _up[2]})
            say('      · 一键升星 → 点「%s」(%d,%d)（%s OCR ✓）'
                % (_up[3], _up[0], _up[1], '弹窗帧' if _up[2] == 'dlg' else '归一化帧'))
        else:
            _hit, _ch = _tpl_hit(b.img(), 'bag_upgrade_btn.png',
                                 region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1100)),
                                         1080, 1920)), 'norm'
            if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                _hit = _tpl_hit(b.img_dlg(), 'bag_upgrade_btn.png')
                _ch = 'dlg'
            if _hit:
                _bag_tap(b, _hit[0], _hit[1], _ch, wait=2.6)
                log.append({'bag': 'upgrade_tpl_btn', 'at': (_hit[0], _hit[1]),
                            'score': _hit[2], 'ch': _ch})
                say('      · 一键升星 → 模板命中 (%d,%d) %.2f（%s）'
                    % (_hit[0], _hit[1], _hit[2], '弹窗帧' if _ch == 'dlg' else '归一化帧'))
            else:
                b.tap(UPGRADE_BTN[0], UPGRADE_BTN[1], wait=2.6)
                log.append({'bag': 'upgrade_anchor', 'at': UPGRADE_BTN,
                            'texts': [i['text'] for i in items][:26]})
                say('      · 一键升星 → 文字/模板都没中 ⇒ 锚点坐标 %s（已确认在背包里 ✓）'
                    % (UPGRADE_BTN,))
        # ⑤ 确认弹框 —— ⭐⭐⭐ 2026-10-03 **改成纯固定坐标**（用户口径：「装备升星也该
        #   都**固定坐标 + 固定间隔**」）✓
        #   ⛔ 原来这套"OCR 找确定"是**错的**，真机铁证（我当场跑的 `bagtest`）：
        #       `{"bag":"confirm_tap","at":[616,1136],"row":[[133,1136,"筛选"],[616,1136,"键升星"]]}`
        #     它用"归一化帧 y 带 **1020~1220** 取最右"找确定，而**确认框的按钮行在 y≈742**
        #     （**带外** ✗）⇒ 带里只捞到**背包页自己的按钮** ⇒ 于是"确认"那一下
        #     **又点了一遍「一键升星」**，确认框根本没点 ⇒ 装备没升上去 ✗✗
        #     （用户当场指出「没点确认」✓）
        #   ⇒ 固定坐标：右按钮（确定 + 费用数字）实测 **(535,741)** ✓
        #     左按钮 (222,742) 是「取消」⇒ **绝不点** ✓（与全游戏确认框同一行 y=742 ✓）
        b.snap(tag + '3')
        _pub_dump(tag + '_confirm', b.img(), important=False)
        _cfx, _cfy = 535, 741
        try:
            b.tap(_cfx, _cfy, wait=2.8)
        except Exception:                   # noqa: BLE001
            pass
        log.append({'bag': 'confirm_fixed', 'at': (_cfx, _cfy),
                    'note': '固定坐标点确认框右按钮（=确定/费用）；左=取消 ✗ 不点 ✓'})
        say('      · 确认弹框 → 固定坐标点 (%d,%d)（右=确定/费用；左=取消 ✗ 不点 ✓）'
            % (_cfx, _cfy))
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**顺序错了，点了确认框后会有个返回需要点。
        #   最后再点关闭背包**；关闭背包的坐标还偏下没关掉」⇒
        #   正确顺序 = 确定(535,741) → **返回(359,808)** → 关闭背包(X) ✓
        #   （升星成功会弹「恭喜获得 / 升星奖励」奖励框 ⇒ 它会**盖住背包** ⇒
        #     必须先点它的「返回」，否则后面点背包 X 全是 `changed:false` 点不掉 ✗
        #     —— 真机实测已证：`close_bag_x × 6 全部 changed:false` ⇒ `back_done: ok=false` ✗）
        time.sleep(1.2)
        try:
            b.tap(BAG_UPGRADE_BACK[0], BAG_UPGRADE_BACK[1], wait=2.2)
        except Exception:                   # noqa: BLE001
            pass
        log.append({'bag': 'reward_back_fixed', 'at': BAG_UPGRADE_BACK,
                    'note': '奖励框「返回」（固定坐标）⇒ 再关背包 ✓'})
        say('      · 升星奖励框 → 固定坐标点「返回」%s（用户口径：先返回、最后关背包 ✓）'
            % (BAG_UPGRADE_BACK,))
        # ⭐ 2026-10-01 诊断（用户报「升星没变化」）：确认之后再扫一眼屏幕 ——
        #   有没有「升级成功/恭喜获得」、是不是还在背包/弹框 ⇒ logcat 里直接判成败 ✓
        time.sleep(0.8)
        _after = b.ocr(tag=tag + '_after')
        _atxt = [i['text'] for i in _after][:14]
        _pub_dump(tag + '_after', b.img())
        say('      · 确认后屏幕认到：%s' % (_atxt,))
        log.append({'bag': 'after_confirm', 'texts': _atxt})
        # ⑥ 回选图界面 ✓
        #   ⚠ 实测（2026-09-27）：
        #     ① `_close_bag`（返回/关闭/X）**关不掉背包** ✗
        #     ② 升星后会弹「恭喜获得 / 升星奖励」框 ⇒ **挡住底部导航** ✗
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**最后不点右上角的叉关闭背包，而是点最下面
        #   开始冒险三次**，也能关背包，还能直接回到选图界面」→ 实测 3 次停在**主界面**
        #   ⇒ 用户随后拍板：「**改成点 4 次开始冒险**」✓
        #   ⇒ 收尾 = **固定坐标点「开始冒险」×4 + 定死间隔**，**不再点 X、不再 OCR 判据** ✓
        # ⭐⭐⭐⭐ 2026-10-06 用户口径（原话，接在"回选图界面核对：还没认到"这条日志之后）：
        #   「**回选图界面核对：还没认到（见日志）装备升级出现这个的时候就再点两次
        #     开始冒险，直到能识别到选图界面**」
        #   ⇒ 把上面那 4 次固定点击**改成"点 → 核对 → 没认到就再点 2 次"的循环**
        #     （上面 4 次是**保底**，下面的循环是**补点**，直到 OCR 认到选图界面为止）✓
        #   ⚠ 安全边界（**必须有，别去掉** ✗）：`BAG_BACK_MAX_ROUNDS` 封顶
        #     —— 若一直认不到（换账号/界面改版/OCR 抽风），**不能无限点下去** ✗
        #     到顶就如实记 `back_giveup` 并走原来的兜底（`_close_bag`）✓
        done = False
        for _k in range(4):
            try:
                b.tap(360, 1260, wait=1.8)
            except Exception:                   # noqa: BLE001
                pass
            log.append({'bag': 'start_adv', 'k': _k, 'at': (360, 1260),
                        'note': '用户口径：点底部「开始冒险」×4 ⇒ 关背包并回选图界面 ✓'})
            say('      · 回选图界面 → 点底部「开始冒险」(360,1260)（第 %d/4 次 ✓）' % (_k + 1))
            time.sleep(0.8)
        # ⭐ 用户 2026-10-06 口径：**核对 + 没认到就再补点 2 次，直到认到为止**（有上限 ✓）
        #   ⚠ 判据与上面那句"只读核对"**同一套**（`进入地图/快速扫荡/星界秘境`）——
        #     不新造判据，避免两处漂移 ✓
        _BACK_KEYS = ('进入地图', '快速扫荡', '星界秘境')

        def _at_menu():
            """现在是不是选图界面（**只读**，不改状态 ✓）"""
            try:
                _it = b.ocr(tag=tag + '_backchk')
                _t = [(i.get('text') or '') for i in _it]
                _ok = any(any(k in t for k in _BACK_KEYS) for t in _t)
                return bool(_ok), _t
            except Exception:               # noqa: BLE001
                return False, []

        done, _t3 = _at_menu()
        log.append({'bag': 'back_check', 'ok': bool(done), 'texts': _t3[:16],
                    'round': 'after_4'})
        say('      · 回选图界面核对：%s'
            % ('已回到选图界面 ✓' if done else '还没认到（见日志）'))
        # 没认到 ⇒ 一轮点 2 次 + 核对；最多 `BAG_BACK_MAX_ROUNDS` 轮（**防无限点** ✓）
        for _r in range(BAG_BACK_MAX_ROUNDS if not done else 0):
            say('      · 还没认到选图界面 ⇒ 再点 2 次「开始冒险」（补点第 %d/%d 轮 ✓）'
                % (_r + 1, BAG_BACK_MAX_ROUNDS))
            for _j in range(2):
                try:
                    b.tap(360, 1260, wait=1.8)
                except Exception:           # noqa: BLE001
                    pass
                log.append({'bag': 'start_adv_retry', 'round': _r, 'k': _j,
                            'at': (360, 1260),
                            'note': '用户口径：没认到选图界面 ⇒ 再点 2 次开始冒险、直到认到 ✓'})
                time.sleep(0.8)
            done, _t3 = _at_menu()
            log.append({'bag': 'back_check', 'ok': bool(done),
                        'texts': _t3[:16], 'round': _r})
            say('      · 回选图界面核对（补点第 %d 轮）：%s'
                % (_r + 1, '已回到选图界面 ✓' if done else '还没认到'))
            if done:
                break
        if not done:
            log.append({'bag': 'back_giveup', 'rounds': BAG_BACK_MAX_ROUNDS,
                        'note': '补点 %d 轮仍认不到选图界面 ⇒ 停止补点、走兜底 ✓'
                                % BAG_BACK_MAX_ROUNDS})
            say('   ⚠ 补点 %d 轮仍没认到选图界面 ⇒ 停止补点（防止无限点 ✓）'
                % BAG_BACK_MAX_ROUNDS)
        for _k in range(0):
            items2 = b.ocr(tag=tag + '_back%d' % _k)
            txt2 = [(i.get('text') or '') for i in items2]
            if any(any(k in t for k in ('进入地图', '快速扫荡', '星界秘境')) for t in txt2):
                done = True
                log.append({'bag': 'back_ok', 'round': _k})
                break
            # ① 先关**弹窗**（⭐⭐ 2026-10-01 真机修：升星后会弹「升星奖励/恭喜获得」框，
            #   它**挡住背包的 X** ⇒ 老代码一路点 X，5 次都关不掉 ⇒ 用户看到"停留在装备界面" ✗）
            #   用户口径的「返回」就在这个框上 ✓
            #   ⚠ 老判据要求 `cy > 1200` ⇒ 真机上这个框的「返回」被漏掉 ✗
            #   ⇒ 放宽到 [sy(600), sy(1700))（**排除底部导航带**，避免点到 公会/角色/开始冒险 ✗）
            pop = None
            for i in items2:
                t = (i.get('text') or '').replace(' ', '')
                _cy = i.get('cy', 0)
                if t in ('返回', '关闭', '确定', '确认', '取消') \
                        and LAYOUT.sy(400) <= _cy < LAYOUT.sy(1133):
                    pop = i
                    break
            if pop:
                b.tap(pop['cx'], pop['cy'], wait=1.8)
                log.append({'bag': 'close_popup', 'text': pop.get('text'),
                            'at': (pop['cx'], pop['cy']), 'round': _k})
                say('      · 关弹窗「%s」(%d,%d) ✓' % (pop.get('text'), pop['cx'], pop['cy']))
                continue
            # ② 弹窗关完了、背包面板还开着 ⇒ 点**它的 X**（弹窗系 ✓）
            _op2, _how2 = _bag_panel_open(b, items2)
            if _op2:
                b.tap_dlg(BAG_X_DLG[0], BAG_X_DLG[1], wait=1.8)
                log.append({'bag': 'close_bag_x', 'at': BAG_X_DLG, 'round': _k,
                            'was': _how2})
                say('      · 关背包 → 点右上 X (%d,%d)（弹窗系 ✓）' % BAG_X_DLG)
                continue
            # 再点底部导航「开始冒险」✓
            # ⭐⭐⭐ 2026-10-01 用户报「装备升星的时候还要先点下进入地图是干什么。。」→ 修
            #   ⚠⚠ 原来这里点的是 `t in ('开始冒险', '进入地图') and cy > 1700` ——
            #     真机上只要那格读成 **「进入地图」**，这一下就**真的开图**：
            #       扣 25 体力 + 把刚升完星的收尾直接顶进地图（用户当场看到的就是这个 ✗✗）
            #   ⇒ **只点底部导航中间的「开始冒险」**（图标锚点 START_ADV=(540,1828)，
            #     用户 2026-09-27 实测「点中间那格不会开图」✓）；
            #     「进入地图 / 快速扫荡」只保留在**上面那句"回到选图界面了吗"的只读判据**里 ✓
            nav = None
            for i in items2:
                t = (i.get('text') or '').replace(' ', '')
                if t == '开始冒险' and i.get('cy', 0) >= LAYOUT.sy(1167):
                    nav = i
                    break
            at2 = START_ADV                       # 锚定的底部导航图标位（不看 OCR 也不会跑偏 ✓）
            b.tap(at2[0], at2[1], wait=2.2)
            log.append({'bag': 'back_tap', 'at': at2, 'saw_start_adv': bool(nav),
                        'round': _k})
            say('      · 回选图界面 → 点底部「开始冒险」(%d,%d)%s'
                % (at2[0], at2[1], '（OCR 也认到 ✓）' if nav else '（锚点坐标）'))
        log.append({'bag': 'back_done', 'ok': bool(done)})
        if not done:
            say('   ⚠ 收尾可能没回到选图界面（已尽力 ✓ 日志有记录 ✓）')
            try:
                _close_bag(b, b.ocr(tag=tag), log)
            except Exception:       # noqa: BLE001
                pass
        STATS['bag_upgrades'] = STATS.get('bag_upgrades', 0) + 1
        log.append({'bag': 'done', 'ok': True})
        say('   ⚙ 背包一键升级：完成 ✓')
        status('装备升星完成 ✓')
        return True
    except Exception as e:      # noqa: BLE001
        log.append({'bag': 'error', 'e': repr(e)[:120]})
        say('   ⚠ 背包升级异常：%r' % (e,))
        try:
            _close_bag(b, b.ocr(tag=tag), log)
        except Exception:       # noqa: BLE001
            pass
        return False


def fb(items, *labels):
    for lb in labels:
        for it in items:
            if lb in it['text']:
                return it
    return None


def exb(items, *labels):
    for lb in labels:
        for it in items:
            if it['text'].strip() == lb:
                return it
    return None


def bottom_close(items, min_cy=None):
    # ⭐ 2026-09-27 修：min_cy 原来写死 1100 ✗ ⇒ 720p 下关闭键(y=960)被排除 ⇒ 卡在结算界面 ✗
    # ⭐⭐⭐ 2026-10-02 再修一次（**这条就是「大拇指格不摇色子」的主根因**）：
    #   上一版的修法是「过布局层」，但**基准从 1080×1920 换成 720×1280 之后**
    #   `LAYOUT.sy(1100)` 变成 **1:1 = 1100**（REF_W/H 已改成 720×1280），
    #   而真机 720p 的「关闭」实测在 **cy=960** —— 铁证 `runs/loop/loop_log.json`
    #   （19:48 那把的 result_panel 条目：`{"t":"关闭","cx":385,"cy":960}`）
    #   ⇒ `960 < 1100` ⇒ 本函数在 720p 上**恒返回 None** ✗✗
    #   ⇒ 后果（离线在真机 items 上实测）：
    #       `wait_end` 的 `on_result = fb(items,*L['desc']) or bottom_close(items)`
    #       恒 False（那张结算面板上**没有**【正面】/【负面】）
    #       ⇒ `result_streak` 永远到不了 2 ⇒ **handle_dice 从来没被调用过** ✗✗✗
    #       （同一条也拖累 `is_battle_panel` / `_res` / `finish_map` / `final_collect`）
    #   ⇒ ×2/3 折算：1100 → **733**（语义不变：只认**下半屏**的「关闭」；
    #     733/1280 = 0.573 = 原 1100/1920 ✓）
    #   交叉验证：真机帧上 `bottom_close(items, 733)` 命中「关闭」cy=960 ✓
    if min_cy is None:
        min_cy = LAYOUT.sy(733)
    best = None
    for it in items:
        if L['close'] in it['text'] and it['cy'] >= min_cy:
            if best is None or it['cy'] > best['cy']:
                best = it
    return best


# ⭐⭐ v1.19（2026-10-01 1264×2780 真帧）结算面板「奖励行」定位：**锚定「关闭」**，不写死 y
#   实测（设备帧 OCR → 换算回参考系 1080×1920）：
#       PC 9:16 : 奖励行数字 907 / 994~1001 ｜ 回放 1223 ｜ 关闭 1440 ｜ 自动跳过 1563
#       真机    : 奖励行数字 636 / 752       ｜ 回放 1224 ｜ 关闭 1441 ｜ 自动跳过 1563
#   ⇒ 面板**底部三键两机一致**（锚定模型成立 ✓），但奖励行在真机**高 271px**（战斗 UI 纵向压缩）
#   ⇒ 旧常量 `sy(700)~sy(1180)`（文字带）/ `box=(40,840+C,1020,1140+C)`（图标框）
#      在 1264×2780 上**完全盖不到奖励行** ⇒ `no_btn` + 三路图标全 None ✓（真机复现）
#   ⇒ 改用「相对关闭按钮」：奖励行恒在关闭**上方** CLOSE_UP_MAX~CLOSE_UP_MIN，
#      且落在**左侧骰子区** x<sx(560)（实测奖励行在 x 103~1159，但骰子在左半区）
REWARD_X1 = 560          # 骰子/大拇指检测的右边界（参考系；实测图标在 x 134~464）
REWARD_CLOSE_UP_MIN = 520     # 奖励行最低（离关闭最远）
REWARD_CLOSE_UP_MAX = 1020    # 奖励行最高（必须在「回放战斗」上方，避免把按钮当奖励）


def _reward_box(items=None, c=0):
    """奖励行搜索框（参考系；c>0 时是**弹窗系** ⇒ y 要 +C，与旧代码同口径 ✓）

    ⚠ `items` 传进来时会**用真实「关闭」按钮**收紧上界（更准）；没有就退回默认常量。
    ⚠⚠ 教训：上界要 **min(常量, 关闭-60)**，不能反过来 —— 反过来 clamp 会让"关闭锚定"完全失效
       （我第一版写成 `min(MAX, close-60)` 而 MAX=1180 > close-60=1380 时永远取 1180 ✗）。
    """
    y0, y1 = REWARD_CLOSE_UP_MIN, REWARD_CLOSE_UP_MAX
    if items:
        _cl = bottom_close(items)
        if _cl:
            y1 = max(REWARD_CLOSE_UP_MIN,
                     min(REWARD_CLOSE_UP_MAX, int(_cl['cy']) - 260))
    return (20, y0 + c, REWARD_X1 + c, y1 + c)


def _reward_band(items=None, c=0):
    """骰子按钮的**文字**搜索带（cx, cy 上下界），同样锚定「关闭」

    ⚠⚠ 2026-10-01 实测：**奖励行是纯图标+数字，OCR 读不到「骰」字**
      （真机结算帧 OCR 只有 `1/3` `1/16` `5/5` `220 46 184` 这类）⇒ 文字通道在**任何**
      分辨率都不可能命中，它只作为**兜底**（万一某版本有字）保留 ✓
    """
    _x0, _y0, _x1, _y1 = _reward_box(items, c)
    return _x0, _y0, _y1


def is_battle_panel(items):
    """是不是**战斗结算/胜利/失败**面板（战斗界面 ⇒ 必须点「关闭」，不能点开始冒险 ✗）
      `fb(items, L['win'], L['lose'], L['close'], '回放战斗')` —— 而**地图界面左上角的
      挑战目标里有一行「首领战斗胜利」**，子串包含「战斗胜利」⇒ 在**干净地图**上被误判成
      战斗面板 ⇒ `universal_close` 去点 (577,1439) ✗ —— 那其实是**棋盘格 (4,4)** ⇒
      等于每两轮在棋盘上乱点一次！（铁证：`runs/m0_r003.png` 是干净地图 + 结束冒险，
      日志却记 `panel_close: battle_close_fixed`）

    现在的判据（都要求"确实像结算面板"）：
      ① 底部「关闭」(y≥1100) 认到         ⇒ 是结算/奖励面板 ✓
      ② 认到「回放战斗」                   ⇒ 结算面板独有 ✓
      ③ 有**恰好等于**「战斗胜利/战斗失败」的标题 ✓（`首领战斗胜利` 是 6 字长句 ⇒ 不算 ✗）
    """
    if bottom_close(items):
        return True
    if fb(items, '回放战斗'):
        return True
    for it in items:
        if (it.get('text') or '').strip() in ('战斗胜利', '战斗失败'):
            return True
    return False


def _reward_row_present(img):
    """这一帧里有没有**结算面板的奖励行**（点数牌 + 四叶草 + 四张奖励卡）

    ⭐⭐⭐ 2026-10-02：为什么需要它 ——
      结算面板的「回放战斗 / 关闭 / 自动跳过」**OCR 认不出来**（真机实测：
      `b.ocr(min_conf=0.20)` 在结算面板上只读到「首领战斗胜利」等地图上的字，
      面板上那三个按钮**一个字都没读到**）⇒ 纯文字判据恒 False ✗
      而**奖励行是纯图像特征**：一条横带 + 若干高饱和高亮的彩色卡 ⇒ 极稳 ✓
      （`handle_dice` 的绿箭头判据已在真机验证过，同一套定界逻辑）
    """
    try:
        if img is None:
            return False, []
        r = _reward_slot1_y()
        y0, y1 = max(0, r - 60), min(img.shape[0], r + 55)
        band = img[y0:y1, :]
        if band.size == 0:
            return False, []
        b_, g_, r_ = (band[:, :, 0].astype(np.int16),
                      band[:, :, 1].astype(np.int16),
                      band[:, :, 2].astype(np.int16))
        mx = np.maximum(np.maximum(b_, g_), r_)
        mn = np.minimum(np.minimum(b_, g_), r_)
        card = (mx > 120) & ((mx - mn) > 40)
        cnt = card.sum(axis=0)
        th = (y1 - y0) * 0.35
        segs, inseg = [], False
        for x in range(len(cnt)):
            if cnt[x] > th and not inseg:
                inseg, s0 = True, x
            elif cnt[x] <= th and inseg:
                inseg = False
                if x - s0 > 30:
                    segs.append((s0, x - 1))
        if inseg:
            segs.append((s0, len(cnt) - 1))
        # 结算面板 = **点数牌 + 四叶草 + 4 张奖励卡** ⇒ 至少 5 段
        #   （选择面板没有奖励行 ⇒ 0 段；地图上也不会有这排卡）
        return len([1 for a, b2 in segs if b2 - a >= 30]) >= 5, segs
    except Exception:                                   # noqa: BLE001
        return False, []


def _reward_slot1_y():
    import fixed as _f
    return int(_f.A('reward_slot_1')[1])


def _is_result_panel_now(*item_lists, img=None):
    """当前这一帧是不是**已经打完的结算面板**（不是「待开打的战斗选择面板」）

    ⭐⭐⭐ 2026-10-02 专治「大拇指格不摇色子」。

    ⚠ **不能只用 `is_battle_panel`**：它的判据①是「底部有『关闭』」，
      而**战斗选择面板也有『关闭』** ⇒ 会把「还没打」也当成「打完了」
      ⇒ 于是不进 `start_fight`、直接去摇色子 ⇒ 面板都还没开 ✗
    ⇒ 两条路取「或」：
      ① 文字：结算面板独有的「回放战斗」/ 标题**恰好**是「战斗胜利/战斗失败」
         （地图左上角挑战目标那行是「首领战斗胜利」6 字长句 ⇒ 靠"恰好相等"排除 ✓）
      ② ⭐ **图像**：奖励行定界出 ≥5 段（点数牌+四叶草+4 张卡）
         —— 这条是**主判据**，因为面板上那三个按钮文字 **OCR 真机认不到**（实测）
    """
    for its in item_lists:
        for it in (its or []):
            t = (it.get('text') or '').strip()
            if t == '回放战斗':
                return True
            if t in ('战斗胜利', '战斗失败'):
                return True
    if img is not None:
        ok, _segs = _reward_row_present(img)
        if ok:
            return True
    return False


# ⭐⭐⭐⭐ 2026-10-05 **幸运草读数**（用户口径：「**改成幸运草低于 8 就不摇色子吧**」）
#   背景：真机 `runs/acc3` 第 N 张图幸运草只剩 **1**，`handle_dice` 还是去点四叶草
#     ⇒ 游戏**不弹确认框** ⇒ 我那道"没弹框就不点确定"的闸门把这一圈跳掉
#     ⇒ 白点两次、日志还报 `no_dlg_skip`（用户看到的是"幸运草不足"这个真因被掩盖了）
#   ⇒ 判据从"猜框在不在"改成**确定性的"钱够不够"** ✓
#   ⚠ **零额外成本**：幸运草数字跟体力在**同一行 HUD**，而体力每轮本来就要读
#     （`stamina(items)` 用的就是同一次 `items`）⇒ 顺手多读一个数字而已 ✓
#   实测位置（6 张真机帧，cx 恒定 462~463 / cy=59）：
#       帧            幸运草   （右手边那个）
#       17:54          3        0
#       19:10          7        0
#       19:11          5        0
#       19:12          2        0
#       19:13          1        0
#       19:14          1        0
#     而体力在 cx≈224、金币 cx≈434 ⇒ 用 **x 区间** 区分最稳 ✓
#
# ⚠⚠⚠ 2026-10-05 **用户纠正我两处**（原话：「**你说的幸运草右边的数字？那个是小鱼干，
#   幸运草数字上面是金币**」）：
#     ① `cx≈604` 那个数字是 **小鱼干**，**不是**"'大拇指数'" —— 我早前那批注释写错了 ✗
#        （不影响判据：幸运草窗口在 `x 430~520`，小鱼干在 `≈592` ⇒ 本来就在窗口外 ✓）
#     ② 没有"跨账号 HUD 布局不同"这回事 —— 我一度拿 `runs/r_22*`（`Ver 1.1.2.7`）
#        那批帧的 `幸运草=285/296` 当成"布局变了"，**那是误报**：
#        逐帧对照（`_verify/_hud_right.png`）两批帧的 HUD **结构完全一致**
#        （金币 y≈26 / 幸运草 y≈59 / 小鱼干 y≈59 右侧），差别只是**数值大小** ✓
#        ⇒ 换句话说：那台机器上幸运草**真有 297 个**、小鱼干 778 —— 不是读错了 ✓
CLOVER_HUD_X = (430, 520)      # 幸运草数字所在 x 区间（实测 462~463）
CLOVER_HUD_Y = (35, 85)        # 所在 y 区间（实测 59）
CLOVER_MIN_REROLL = 10         # 低于它就**不摇色子**（用户口径）
#   ⭐⭐⭐⭐⭐ 2026-10-09 用户口径（原话）：「**幸运草阈值都改成10**」✓
#     ⇒ 原来是 8 ⇒ **改成 10**（与宝箱怪闸门统一 ✓）
#     ⚠ 三个用途**现在同一个数**，但**语义仍然不同**（各管各的事 ✓）：
#        · 摇色子   ⇒ `CLOVER_MIN_REROLL`（本常量）
#        · 大拇指格 ⇒ 也用 `CLOVER_MIN_REROLL`（`st['clover_block']` 那条 ✓）
#        · 宝箱怪   ⇒ `MIMIC_CLOVER_MIN`（独立常量：那是"买装备"、这是"摇色子" ✗）
#     ⇒ 我把它们**分开定义**不是多余 —— 用户完全可能明天只改其中一个 ✓

# ⭐⭐⭐⭐ 2026-10-05 **金币读数 + 低于 50 万就不买商人/宝库**（用户口径，原话）：
#   「扫体力顺便把金币数量也扫了吧，加个金币低于50万就自动不去购买商人和宝库
#     （也不规划，就相当于拉黑了），高于50w就还是正常买」
#   实测位置（14 张真机帧、**两个账号**）：
#       (435, 26) '441031'   ← acc1/acc2 的金币（6 位）
#       (429, 26) '2300302'  ← 另一账号（7 位，位数更多 ⇒ 中心 x 左移 6px，窗口要留裕量）
#     ⚠ 它与幸运草（y≈59）**只差一行 y** ⇒ 判据**必须用 y 分开**（x 区间有重叠 ✗）
#     ⚠ 与钻石/宝石（x≈581~587、y≈26）用 **x 区间**分开 ✓
GOLD_HUD_X = (395, 560)        # 金币数字所在 x 区间（实测中心 429~435；位数变时左右摆 ✓）
#   ⚠⚠ **y 窗口必须与幸运草严格错开**（实测金币 y≈25~26、幸运草 y≈59，中点在 ~42）：
#     门禁 `verify_gold_gate.py` 抓到我第一版写成 (8,45) ⇒ 与幸运草 (35,85) **在 35~45 重叠** ✗
#     ⇒ 收紧到 **(8, 30)**（上界 30 落在真值 26 与幸运草 59 之间，且 < 幸运草窗口下界 35 ✓
#        —— 真值 26 离上界 4px、离下界 8px，两边都有余量 ✓）
GOLD_HUD_Y = (8, 30)
GOLD_MIN_BUY = 500000          # 低于它 ⇒ **不买商人/宝库、也不把它们排进计划**（= 拉黑 ✓）

# ⭐⭐⭐⭐⭐ 2026-10-09 用户口径（原话）：
#   「**商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和10幸运草就是**」
#   ⇒ 金币那条（商人/宝库）**早已实现** ✓（`GOLD_MIN_BUY`）
#   ⇒ **幸运草这条（宝箱怪）原来没有** ✗ —— 我搜遍全仓零命中
#     （`CLOVER_MIN_REROLL=8` 是**摇色子**用的，**不是**宝箱怪闸门 ⇒ 别混用 ✗）
#   ⇒ 新增：**幸运草 < 10 ⇒ 金属/机巧宝箱怪自动拉黑**（不买、不规划）✓
#     ⚠ 为什么是 10：宝箱怪**最高档卖 8 草**（`GetCloverPrice`: C1/B2/A4/**S8**）
#       ⇒ 留 2 草余量（刷新要 1 草）⇒ 用户定的 10 ✓
#     ⭐ 2026-10-09 用户口径：「**幸运草阈值都改成10**」⇒ 与摇色子那个**同为 10** ✓
#       （此前摇色子是 8、这里是 10 ⇒ 现在统一 ✓）
MIMIC_CLOVER_MIN = 10          # 低于它 ⇒ 宝箱怪**自动拉黑**（不买也不规划）


def _hud_int(text):
    """从 HUD 文字里抠出整数 —— **容忍尾随的图标字符**

    ⭐⭐⭐⭐ 2026-10-08 真 bug（用户要求「**试试**」宝箱怪流程时抓到）：
      HUD 上「数字 + 草图标」那一格，OCR **有时把图标粘在数字上**：
          实测三帧（`runs/spec_dev/acc3_all/clover_hud.png` 是铁证）：
              草 = 4   ⇒ OCR `4 Φ`
              草 = 12  ⇒ OCR `12 ±`
              草 = 287 ⇒ OCR `287Φ`     ← ⚠ **三位数也照粘**
      ⇒ 原来的 `t.isdigit()` **一律拒掉** ⇒ `clover_count()` 返回 `None` ✗
      ⇒ 下游后果：**幸运草闸门失效**（读不到就当"不知道"，按 fail-open 照常摇色子/照常买）
        ⇒ 用户报过的「**幸运草低于8怎么还会摇色子？**」有它一份 ✓

    ⚠ 与"金币"同一个病（`gold_count` 原来也是裸 `isdigit()`）
      —— 批量实测 24 帧：`clover_count` 命中 17、`gold_count` 只命中 **10** ✗

    做法：**剥掉尾随的非数字**，只取开头那段数字 ✓
      · `287Φ` ⇒ `287` ✓    · `12 ±` ⇒ `12` ✓    · `4 Φ` ⇒ `4` ✓
      · `8365` ⇒ `8365` ✓   · `1949/2100` ⇒ `1949` ⚠ **这个不能要**（那是体力）
        ⇒ 所以**只剥"尾随"**、遇到中间的非数字就整体放弃（不截断）✗
          —— `1949/2100` 中间有 `/` ⇒ 不是"纯数字 + 尾随杂字" ⇒ 返回 None ✓
    """
    import re as _re
    t = str(text or '').replace(' ', '').replace(',', '').replace('+', '')
    m = _re.fullmatch(r'(\d+)\D*', t)      # 数字在**开头**，后面可以是任意杂字 ✓
    if not m:
        return None
    return int(m.group(1))


def gold_count(items):
    """HUD 上「金币」还剩多少 —— 读不到返回 None（**不猜** ✓）

    用户口径：「金币低于50万就自动不去购买商人和宝库（也不规划，就相当于拉黑了），
    高于50w就还是正常买」

    ⚠ 与 `stamina()` / `clover_count()` **同一次 OCR** ⇒ 没有任何额外开销 ✓
    ⚠ 只认**数字开头**、且落在 `GOLD_HUD_X/Y` 区间内 ⇒ 不会误取：
        · 幸运草（y≈59）—— **靠 y 分开**（x 区间与之重叠 ✗）
        · 钻石/宝石（x≈581~587）—— 靠 x 区间分开 ✓
        · 体力（'1949/2100' 带 `/`）—— **中间有杂字 ⇒ `_hud_int` 返回 None** ✓
        · PID / Ver（y≈25 但 x 152/266，且含冒号）⇒ 区间外 + `_hud_int` 拒 ✓
    """
    best = None
    for it in items or []:
        v = _hud_int(it.get('text'))
        if v is None:
            continue
        cx, cy = int(it.get('cx', -1)), int(it.get('cy', -1))
        if GOLD_HUD_X[0] <= cx <= GOLD_HUD_X[1] and GOLD_HUD_Y[0] <= cy <= GOLD_HUD_Y[1]:
            best = v if best is None else max(best, v)
    return best


def gold_enough(items_or_val):
    """金币够不够买（够 或 **读不到** ⇒ True = 照常买 ✓）

    ⚠ 读不到 ⇒ **不拦**（保守：宁可买一次，也别因为一次 OCR 失败就永远不买 ⇒
      那会把整局的商人/宝库全丢掉 ✗）
    """
    v = items_or_val
    if not isinstance(v, (int, float)):
        v = gold_count(items_or_val)
    if v is None:
        return True
    return int(v) >= GOLD_MIN_BUY


# ⭐⭐⭐⭐ 2026-10-05 **「一图只确认一次」**（用户口径，原话）：
#   「**金币幸运草都是一张图只确认一次**」
#   为什么必须锁（不是优化，是**正确性**）：
#     · HUD 上金币/幸运草都在**右上角那一小块**，被面板/横幅盖住时 OCR 会读不到或读偏；
#       若每轮都重读，同一个判断会在**同一张图里反复翻转** ⇒ 目标一会儿拉黑一会儿放回 ✗
#     · 与既有范式一致：`st['claim_checked']` 就是"每张图只跑一次"（见 8984 行那段）
#   ⇒ 进图第一次读到有效值就**锁进 `st`**（`gold_locked` / `clover_locked`）；
#     之后**一律用锁定的值**，不再改（读不到也不覆盖 ✓）
def _lock_hud_once(st, items, log=None, rnd=None):
    """把金币/幸运草**各锁一次**（进图首次读到有效值即锁 ✓）

    返回 (gold, clover)（锁定值；还没锁到 ⇒ None）
    用户口径：「金币幸运草都是一张图只确认一次」
    """
    # ---- 金币 ----
    if st.get('gold_locked') is None:
        _g = gold_count(items)
        if _g is not None:
            st['gold_locked'] = _g
            if log is not None:
                log.append({'hud_lock': 'gold', 'v': _g, 'round': rnd,
                            'enough': bool(_g >= GOLD_MIN_BUY), 'min': GOLD_MIN_BUY,
                            'note': '金币**一图只确认一次** ⇒ 锁死（用户口径 ✓）'})
    # ---- 幸运草 ----
    if st.get('clover_locked') is None:
        _c = clover_count(items)
        if _c is not None:
            st['clover_locked'] = _c
            if log is not None:
                log.append({'hud_lock': 'clover', 'v': _c, 'round': rnd,
                            'enough': bool(_c >= CLOVER_MIN_REROLL),
                            'min': CLOVER_MIN_REROLL,
                            'note': '幸运草**一图只确认一次** ⇒ 锁死（用户口径 ✓）'})
    return st.get('gold_locked'), st.get('clover_locked')


def clover_enough(st_or_val):
    """幸运草够不够摇色子（够 或 **读不到** ⇒ True）

    ⚠ 优先用 `st['clover_locked']`（一图只确认一次的锁定值 ✓）；
      传进来的若不是 dict 就当成**直接的值**（给单测/离线用 ✓）
    """
    if isinstance(st_or_val, dict):
        v = st_or_val.get('clover_locked')
        if v is None:
            v = st_or_val.get('clover')
    else:
        v = st_or_val
    if v is None:
        return True
    return int(v) >= CLOVER_MIN_REROLL


def gold_enough_locked(st_or_val):
    """金币够不够（同上：优先用锁定的 `st['gold_locked']` ✓）"""
    if isinstance(st_or_val, dict):
        v = st_or_val.get('gold_locked')
        if v is None:
            v = st_or_val.get('gold')
    else:
        v = st_or_val
    if v is None:
        return True
    return int(v) >= GOLD_MIN_BUY


def clover_enough_for_mimic(st_or_val):
    """幸运草够不够**买宝箱怪**（够 或 **读不到** ⇒ True = 不拉黑 ✓）

    ⭐⭐⭐⭐⭐ 2026-10-09 用户口径（原话）：
      「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和**10幸运草**就是」
    ⇒ 与 `clover_enough`（摇色子，阈值 8）**是两件事**，**不能共用一个常量** ✗
      · 摇色子：`CLOVER_MIN_REROLL = 8`
      · 宝箱怪：`MIMIC_CLOVER_MIN  = 10`（用户定；宝箱怪最高档卖 8 草 ✓）
    ⚠ 读不到 ⇒ **True = 不拉黑**（fail-open：宁可多点一格，也别因一次 OCR 失败丢掉 ✓）
    ⚠ 优先用 `st['clover_locked']`（一图只确认一次的锁定值 ✓）
    """
    if isinstance(st_or_val, dict):
        v = st_or_val.get('clover_locked')
        if v is None:
            v = st_or_val.get('clover')
    else:
        v = st_or_val
    if v is None:
        return True
    return int(v) >= MIMIC_CLOVER_MIN


def clover_count(items):
    """HUD 上「幸运草（四叶草）还剩几个」—— 读不到返回 None（**不猜** ✓）

    用户口径：「**改成幸运草低于 8 就不摇色子吧**」（原先想的是 5，后改成 8 ✓）

    ⚠ 与 `stamina()` 同一行、同一次 OCR ⇒ **没有额外开销** ✓
    ⚠ 只认**数字开头**、且落在 `CLOVER_HUD_X/Y` 区间内 ⇒ 不会被金币(434)/体力(224)误取
      （`stamina` 取的是"x/y"形式、金币那个是 6 位数且 y=26 ⇒ 都不会撞 ✓）
    ⚠⚠ 2026-10-08 修：原来要求**纯数字** ⇒ OCR 把**草图标**粘在数字上时
      （`4 Φ` / `12 ±` / `287Φ`）**一律拒掉** ⇒ 返回 None ⇒ 闸门失效 ✗
      ⇒ 改用 `_hud_int()`（**容忍尾随图标字符**；详见它的注释 ✓）
    """
    best = None
    for it in items or []:
        v = _hud_int(it.get('text'))
        if v is None:
            continue
        cx, cy = int(it.get('cx', -1)), int(it.get('cy', -1))
        if CLOVER_HUD_X[0] <= cx <= CLOVER_HUD_X[1] and CLOVER_HUD_Y[0] <= cy <= CLOVER_HUD_Y[1]:
            best = v if best is None else max(best, v)
    return best


def stamina(items):
    """读体力：HUD 左上角那个 `x/2500`（实测坐标 ≈ (338,94)）

    ⚠ 2026-09-25 修：原来取"第一个 x/y 文字"——在背包/图鉴里会取到别的计数器
      （装备 1634/1634、莱姆 41/50 …）⇒ 数字乱跳（实测出现过 -499 ✗）。
      现在只在**顶部 HUD 区域**(cy<130) 且 x<560 的条目里找 x/数字 的形式 ✓
    """
    cands = []
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if '/' not in t:
            continue
        a, _, b2 = t.partition('/')
        if a.isdigit() and b2.isdigit() and it.get('cy', 9999) < 130 and it.get('cx', 9999) < 560:
            cands.append((it['cy'], it['cx'], int(a)))
    if cands:
        cands.sort()
        return _stam_sanity(cands[0][2])
    # 退路：老口径（第一个 x/y），但排除背包里那种大分母
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if '/' in t:
            a, _, b2 = t.partition('/')
            if a.isdigit() and b2.isdigit() and int(b2) >= 100:
                return _stam_sanity(int(a))
    return None


# ⭐ 2026-09-26 实测：刚打完战斗/关面板那一帧，HUD 上的体力偶发**多认一位**
#   实测序列 864→1863、835→1834（真值应该是 863 / 834，前面凭空多个 "1"）
#   ⇒ 后果：① 日志/统计里体力会"回升"，② --min-stamina 收工判断会被高估的假值骗过去
#   修法：相邻两轮间隔只有几秒（一轮循环 ~3s），体力不可能凭空涨 ≈1000 ⇒ 修正回来
_LAST_STAM = {'v': None}


def _stam_sanity(v):
    """体力读数合理性校验：把 OCR 多认一位的假值修回来 ✓"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    prev = _LAST_STAM['v']
    try:
        # ⚠ 刚吃过补给 / 没历史值 ⇒ 不校验（补给是真涨 ✓）
        if prev is not None and not STATS.get('supply_used'):
            # ⭐ 两个必备特征：① 涨幅约 +1000（只可能是凭空多一位）
            #                ② 去掉首位后 ≈ 上一轮（一轮循环通常只花 1~8 点 ⇒ 放宽到 12）
            d = v - prev
            if 901 <= d <= 1099 and len(str(v)) == len(str(prev)) + 1:
                alt = v - 1000
                if abs(alt - prev) <= 12:         # 一轮的花销上限：大格 8 点 + 容错
                    say('       · 体力读数 %d 疑似 OCR 多认一位（上一轮 %d）⇒ 修正为 %d'
                        % (v, prev, alt))
                    v = alt
    except Exception:           # noqa: BLE001
        pass
    _LAST_STAM['v'] = v
    return v


def cell_of(cx, cy):
    return (int((cy - GRID['y0']) // GRID['cy']) + 1,
            int((cx - GRID['x0']) // GRID['cx']) + 1)


def cell_center(r, c):
    return (int(GRID['x0'] + (c - 1) * GRID['cx'] + GRID['cx'] / 2),
            int(GRID['y0'] + (r - 1) * GRID['cy'] + GRID['cy'] / 2))


def cells_of(img, mapname=None, code=None, need_names=True):
    """棋盘逐格状态（2026-09-25 起用地块分类器，不再靠中心色采样）

    -> {'gray': 未揭示格中心, 'light': 已揭示格中心,
        'plain': 已揭示的空地(草地/海边杂物这类可揭格), 'content': 已揭示的内容格,
        'buy': 已揭示的旅行商人/黄金宝库, 'st': {(r,c): {...}}, 'unknown': [格]}
    """
    out = {'gray': [], 'light': [], 'plain': [], 'content': [], 'buy': [],
           'buy_hidden': [], 'unknown': []}
    st = board_state(img, mapname, code, need_names=need_names)
    out['st'] = st
    if not st:
        # 兜底：老的颜色启发式（分类器不可用时至少还能跑）
        for r in range(1, 6):
            for c in range(1, 8):
                cx, cy = cell_center(r, c)
                w = img[cy - 35:cy + 35, cx - 45:cx + 45]
                if w.size == 0:
                    continue
                b, g, rr = cv2.split(w)
                ri, gi, bi = rr.astype(int), g.astype(int), b.astype(int)
                gray = ((rr >= 125) & (rr <= 175) & (abs(ri - gi) < 16) & (abs(gi - bi) < 16))
                light = ((rr >= 235) & (g >= 185) & (bi >= 105) & (bi <= 220))
                if float(gray.mean()) > 0.45:
                    out['gray'].append((cx, cy))
                elif float(light.mean()) > 0.35:
                    out['light'].append((cx, cy))
        return out
    for (r, c), v in sorted(st.items()):
        p = cell_center(r, c)
        if v['anchor'] != (r, c) and v['anchor'] is not None:
            continue                     # 多格物件只按锚点算一次
        # ⚠ 商人/宝库必须**匹配分数够高**才算（2026-09-25 卡死事故）：
        #   屏幕上若有面板/遮罩盖住棋盘，分类器会把整盘读成"暗格"，并凭 0.6~0.7 的
        #   弱匹配误报出好几个"未揭示的商人/宝库"；而商人宝库是**永不拉黑**的目标，
        #   于是循环对着点不动的格子空转（用户报「退出地图时卡住了」）。
        #   实测：真商人/宝库 0.95+（含变暗时 0.9+），误报 ≤0.7 ⇒ 阈值 0.85。
        #
        # ⭐⭐⭐⭐ 2026-10-16 **用户报「旅行商人没识别到」⇒ 加"顶部自洽"判据**
        #   ---- 病（真机铁证，用户给的两张图）----
        #     用户原话：「`r_001804_0.png` / `r_001906_0.png` 没识别到旅行商人？」
        #     那两块在 `1,7` / `4,7` —— 分类器**认对了**
        #     （`top1/2/3` 全是 `S10003_008 旅行商人`，第 4 名才 0.37 ⇒ 分离度很大）✓
        #     但分数 **0.727 / 0.689** < `BUY_SCORE_MIN(0.85)` ⇒ **被门槛挡掉** ✗
        #   ---- 为什么"旅行商人"天生分低（我逐格量过）----
        #     · **不是**亮度/饱和度问题：商人雾里饱和 14.1、宝库雾里 13.8（几乎一样）
        #       模板也都是彩色的（饱和 140 vs 145）⇒ 两边平等 ✓
        #     · 是**这个美术的 NCC 天生低**（同帧对比，已扫 600 帧标定）：
        #         黄金宝库 `S10003_016`：雾里也 **0.999** ✓
        #         旅行商人 `S10003_008`：雾里 0.689~0.727 ｜ **已亮也才 0.847** ✗
        #       ⇒ 0.85 这个门槛**连已揭示的商人都挡**（0.847 < 0.85，差 0.003）✗
        #     · 而 0.85 当年的样本**只覆盖了黄金宝库**（它确实 0.999）⇒ 门槛定高了 ✓
        #   ---- 修法（**用户选定**：「不改绝对门槛，改用顶部自洽」✓）----
        #     ⛔ 不去降 `BUY_SCORE_MIN`（那会同时放松宝库、削弱当年那道卡死防范 ✗）
        #     ✅ 保留 0.85 为**主判据**，**另加**一条"顶部自洽"作为**补充**判据：
        #        `_buy_top_self(v)` ⇒ `top[0]` 与"第一个不同 sid"的**分数差 ≥ 0.30**
        #     ---- ⭐ 0.30 是**离线标定**出来的（600 张真机帧，人眼核对过拼图）----
        #       真目标：gap = **0.35 ~ 0.66**（含用户那两个 0.353/0.343、已亮商人 0.477）✓
        #       误报　：gap = **0.05 ~ 0.26**（图上是一团**模糊的树/石头**，不是商人）✗
        #       ⇒ 分界取 **0.30**（真目标最小值 0.35 留了余量 ✓）
        #     ⚠⚠ **别用"top 里连续同 sid 的个数 k>=3"当判据**（我第一版就写了它 ⇒ **恒真** ✗）：
        #       实测 793 个格的 `k` **全是 3** —— 因为每类有好几个动画帧、
        #       同一 sid 自然占满 `top` 前几名 ⇒ `k` **完全没有区分度** ✗
        #       （真正有区分度的是 **gap** ✓）—— 这正是"夹具/判据要拿真数据标定"那条教训 ✓
        # ⭐ 2026-10-24 抽成共用语词 `_cell_is_strong_buy()` —— **与 `vault_px_now` 调同一个函数**
        #   原来这里是**内联表达式**、`vault_px_now` 另有**一套只认 score 的** ⇒ 两处漂移
        #   ⇒ 真机 0.695 的商人「进 buy 时算商人、判记忆时不算」⇒ 买完反复点开 ✗
        #   详见 `_cell_is_strong_buy()` 的 docstring（含真机 loop_log 铁证）✓
        strong = _cell_is_strong_buy(v)
        if not v['revealed']:
            out['gray'].append(p)
            # ⭐ 未揭示的商人/宝库**仍然是目标**（用户 2026-09-25：「有黄金宝库你没点就要退」）：
            #   它此时点不动，要像 boss 一样沿路开路把它解锁出来
            if strong and v['name'] in spots_mod.BUY_OUT_NAMES:
                out['buy_hidden'].append(p)
            continue
        out['light'].append(p)
        if strong and v['name'] in spots_mod.BUY_OUT_NAMES:
            out['buy'].append(p)
        elif is_plain_spot(v['sid']):
            out['plain'].append(p)
        elif not strong and _LOOKS_UNRELIABLE(v):
            # ⚠⚠⚠ 2026-10-02 修「进去啥都认不出就退图」（真机帧 r_015542_0.png 逐格实测）：
            #   用户核实：图里那几片明明是**空地**，但分类器给它们编了
            #     「巨大沙堡 / 海边小屋 / 椰树」等名字，score 只有 **0.21~0.38**
            #     （认单格的门槛是 0.80，差了 2~4 倍 ⇒ 分类器**自己都认不出**）。
            #   ⇒ 结果：空地进了 `content`（内容格）而不是 `plain`（可开路空地）
            #     ⇒ `plain=0` ⇒ 规划器一步都展不开 ⇒ 「没有目标了」秒退图 ✗✗
            #   ⇒ 修法：**认不准**（score 远低于门槛）就按「可开路空地」兜底**。
            #   ⚠ 为什么这样安全：宁可多点一次空地（点空地 = 白揭一格，代价 1 体力），
            #     也**不能**把空地当障碍 ⇒ 那会让整盘一步都走不了、直接退图 ✗
            #     —— 后者代价（一张图都不刷）远大于前者 ✓
            #   ⚠ 只兜底 `light`（已揭示、可点）那部分；`gray` 走不到这里 ✓
            out['plain'].append(p)
        else:
            out['content'].append(p)
    return out


BUY_SCORE_MIN = 0.85        # 认商人/宝库的最低匹配分（见上面注释）
# ⭐⭐⭐⭐ 2026-10-16 **「顶部自洽」补充判据**（用户报「旅行商人没识别到」⇒ 用户选定方案）
#   ---- 它治什么 ----
#     `BUY_SCORE_MIN = 0.85` 对**黄金宝库**合适（实测 0.999），
#     但对**旅行商人**太严：真商人只有 **0.689~0.847**
#     ⇒ 连**已揭示**的商人都被挡（0.847 < 0.85，差 0.003）✗
#   ---- 判据 ----
#     `top[0]` 与"第一个**不同 sid**"的分数差 ≥ `BUY_TOP_GAP_MIN`
#     ⇒ 意思是"**第一名明显甩开其它类别**"（分类器自己是笃定的 ✓）
#   ---- ⭐ `0.30` 是**离线标定**出来的（600 张真机帧 + 人眼核对拼图）----
#     真目标（用户那两格 + 已亮商人）：gap = **0.343 / 0.353 / 0.477 / 0.656** ✓
#     误报（图上是一团**模糊的树/石头**）：gap = **0.054 / 0.255** ✗
#     ⇒ 取 **0.30**（真目标最小值 0.343 留了余量 ✓）
#   ⚠⚠ **别用"连续同 sid 的个数 k"当判据**（我第一版就写了 ⇒ **恒真** ✗）：
#     实测 793 个格的 `k` **全是 3** —— 每类有好几个动画帧、
#     同一 sid 自然占满 `top` 前几名 ⇒ `k` **毫无区分度** ✗
#     真正有区分度的是 **gap** ✓（"判据必须拿真数据标定"那条教训的又一例 ✓）
BUY_TOP_GAP_MIN = 0.30

# ⭐⭐⭐⭐ 2026-10-16 **扫天赋果实的体力闸门**（用户口径，原话）：
#   「最后的最后（**做完日常，招募什么的且体力小于100就是最后了**）
#    去背包道具里扫描下天赋果实数量，并且记录」
#   ⇒ **体力 < 100** 才算"收尾"，才去扫 ✓
#   ⚠ 用 `100`（不是别处的 `RELAUNCH_STAMINA_MIN`）—— 用户**点名**了这个数 ✓
#     两者语义也不同：那个是"够不够再开一轮"，这个是"算不算收工了" ✓
#   ⚠ 读不到体力 ⇒ **不扫**（fail-closed，见 `_guild_daily` ⑤ 那段说明 ✓）
FRUIT_SCAN_MAX_STAMINA = 100


def _buy_top_self(v):
    """这格是不是**顶部自洽**（第一名明显甩开其它类别）⇒ True/False

    见 `BUY_TOP_GAP_MIN` 的长注释（含 0.30 的标定依据 ✓）
    ⚠ 拿不到 `top` / 格式不对 ⇒ **返回 False**（保守：不认 ⇒ 退回老判据 ✓）
      —— 宁可漏认（下次再点），也别把误报放进来（当年卡死事故就是误报导致的 ✗）
    """
    try:
        top = v.get('top') or []
        if len(top) < 2:
            return False
        sid0 = top[0][1]
        # 找第一个**不同 sid** 的条目
        for t in top[1:]:
            if t[1] != sid0:
                return (float(top[0][0]) - float(t[0])) >= BUY_TOP_GAP_MIN
        # 全同 sid ⇒ 没有"那一类"可甩开
        #   ⚠ 这时**不算自洽**（信息不足）—— 但 score 高的话老判据仍会接住 ✓
        return False
    except Exception:       # noqa: BLE001
        return False
def _cell_is_strong_buy(v):
    """这格算不算**强匹配的商人/宝库**（= 该被当目标、也 = 买完记忆该保住）

    ⛔⛔⛔ 2026-10-24 **这是唯一一份判据**（治「商人买完了还要再点一下」）
      ---- 为什么要抽成函数 ----
        原来**两个地方各写了一套**：
          · `cells_of()`（收 buy 列表）用
              strong = score >= BUY_SCORE_MIN **or** _buy_top_self(v)
          · `vault_px_now()`（`_prune_bought_done` 靠它判"那格还是不是商人"）
            只认 score >= BUY_SCORE_MIN
        ⇒ 真商人分数天生低（实测 **0.689~0.847**，2026-10-16 标定），
          **同一格**会出现「进 buy 列表时算商人、判记忆时不算商人」✗
      ---- 真机后果（`runs/acc2/loop/loop_log.json`，10-24 22:50，设备 20000）----
        #104 board `3,2` = `008 旅行商人` **0.695**
        #128 {"bought_rec":[168,908],"cell":"3,2"}   ← 买完 4 档，记住
        #131 {"bought_done_pruned":1,"kept":[]}       ← ★ 下一轮记忆被删
        ⇒ 又进目标 ⇒ 又点开（用户：「**明明买完了，还要去点一下**」）
        （map 3 的 `5,7` 0.669 同样复发 ✓）

    ⚠ 两个分支的口径**都保留**（不是新发明）：
        · `score >= BUY_SCORE_MIN` —— 宝库/高分商人走这条（实测宝库 0.999）
        · `_buy_top_self(v)` —— 顶部自洽放宽（2026-10-16 的标定：
          真目标 gap 0.343~0.656 / 误报 0.054~0.255 ⇒ 门槛 0.30）
    ⚠ 拿不到 `top` ⇒ `_buy_top_self` 返回 False ⇒ 退回老判据（保守 ✓）
    """
    try:
        return (float(v.get('score') or 0) >= BUY_SCORE_MIN) or _buy_top_self(v)
    except Exception:       # noqa: BLE001
        return False                 # 判不了 ⇒ 不算强匹配（与老行为一致 ✓）


BUY_PROBE_MAX = 3           # 「强匹配但被判未揭示」的宝库/商人：每格每图最多验证式点几下（见下）
# ⭐ 2026-10-02：`find_camp_cell()` 兜底用 —— 单格候选里「营地(000)」的**最低分**。
#   标定依据（离线真机帧，零体力）：
#     认得出的那把：营地单格 = `S00003_000` **0.998**（走老判据，不经过这里）
#     认不出的那把（用户报「怎么规划没了」）：营地格 (4,3) 的单格候选
#        `top[0] = (1.000, 'S00003_000')` / `top[1] = 0.996` / `top[2] = 0.991`
#        —— 而它**同块**的干扰候选是 `S00003_001 草地 0.998` ⇒ 0.9 这条线留足了区分度
#   ⚠ 只用于"老判据一个都没命中"时兜底；正常帧根本走不到这里 ✓
CAMP_TOP_MIN = 0.90


def _LOOKS_UNRELIABLE(v, thr_now=None):
    """这格的分类结果**可信吗**？（见 `cells_of` 里的调用点）

    ⛔⛔ 判据口径（2026-10-02 真机两次实证后定案，**别再改回比例式**）：
       现场：`runs/r_032640_0.png` 逐格实测 —— 35 格**全部认出**，
       但 score **中位数只有 0.176**、最高 0.484，**没有一格达到 0.80 门槛**。
       ⇒ 这是「整盘 NCC 偏低」，不是「个别格认不出」。
       ⇒ 若按「低于门槛一半(0.40)就当空地」判 ⇒ **整盘 28 格被当空地**
         ⇒ `board` 记成空 ⇒ `solver` 只展开 1 个状态就 exhausted
         ⇒ **完全没有规划**（用户报「没有规划了」）✗✗

    ⚠ 为什么不能按绝对比例算：分母是**模板亮度**（不同地块模板亮度不同），
       同一画面 ratio 能差出一大截。拿它推导"多低才算瞎猜"必然在某些盘上失效 ✓
    ⇒ 改用**保守绝对下限**：只有低于 0.15（极端瞎猜）才兜底。
       宁可少兜底（退回 content，行为同改前），也不要把整盘地块误分类成空地 ——
       后者代价是**目标全部消失**，比"多点一次"严重得多 ✗
    """
    try:
        sc = float(v.get('score') or 0.0)
    except (TypeError, ValueError):
        return True
    if sc != sc:                       # nan ⇒ 当不可信
        return True
    if thr_now is not None:
        try:
            return sc < float(thr_now)
        except (TypeError, ValueError):
            pass
    return sc < 0.15

_COLOR_TILES = ('宝库', '商人')


def _is_purple_cell(tapped_sid, ev_tiles=None, tapped=None):
    """这一格是不是**紫/橙探索格**（后缀 221/321/331 ✓ 小助手官方分类）

    ⭐⭐⭐⭐ 2026-10-05 用户报「**为什么漏了一个紫探索的战斗**」⇒ 抽成纯函数（可离线测 ✓）

    两条判据（**或**关系）：
      ① 顶层 sid 的后缀 ∈ `EXPLORE_SUFFIX` ✓（常规情形）
      ② **bot 本轮自己已经判定成紫/橙格的**（`st['ev_tiles']`）也算 ✓
    为什么必须有 ②（真机铁证 `runs/acc1/r_160935_0.png` 的 `(3,1)`）：
      · "发现紫/橙探索地块"那条检测用的是 **top-N 候选的后缀** ⇒ 判对了 ✓
      · 而这一格**顶层 sid 是垃圾**：`S30001_104 废弃矿车`、**score 只有 0.192**、
        ratio **1.709**（= 雾里那团**紫光** —— 紫/橙格在雾里正是靠这团光被认出来的 ✓）
      · ⇒ 只看顶层 sid ⇒ 后缀 104 ∉ {221,321,331} ⇒ **探索/派遣分支被整个跳过** ✗
        ⇒ 点开了面板却当普通面板处理/关掉 ⇒ **那一格探索战斗漏了**（用户看到的现象）✗✗
    ⚠ 不许"只要开了面板就算紫格"—— 必须**本轮 ev_tiles 里确有这一格**（否则会把
      预言石碑/宝箱那些内容格也当成探索格 ✗）
    """
    try:
        suf = set(getattr(spots_mod, 'EXPLORE_SUFFIX', ('221', '321', '331')))
        if ('_' in str(tapped_sid or '')) and (str(tapped_sid).split('_')[-1] in suf):
            return True
        if ev_tiles and tapped:
            rc = cell_of(tapped[0], tapped[1])
            if ('%d,%d' % rc) in set(ev_tiles):
                return True
    except Exception:       # noqa: BLE001
        pass
    return False


def vault_px_now(c, revealed_only=True, strong_only=True, any_color=False):
    """当前帧分类结果里的**商人/宝库格**（像素）—— `any_color=True` 时连"点开详情才认出的"也算

    ⭐ 2026-10-01 v0.96 新增（用户真机报「**黄金宝库明明都揭示了能直接点，他又去打了两个
    战斗地块**」）：这是**唯一**的「宝库像素来源」，供三处共用（防钉死 / 免拉黑 / 点序置顶），
    免得三份判据各写一遍又漂移 ✗

    ⛔⛔⛔ 2026-10-24 **强匹配判据必须与 `cells_of` 同一套**
      ---- 用户报告（原话）----
        「**为什么第三张图和第四张图的两个商人，明明买完了，还要去点一下？**」
      ---- 真机铁证（`runs/acc2/loop/loop_log.json`，设备 20000，10-24 22:50）----
        #104 board `3,2` = `008 旅行商人` **score=0.695** ratio=0.66
        #128 {"bought_rec":[168,908],"cell":"3,2"}      ← 买完 4 档，记住了
        #131 {"bought_done_pruned":1,"kept":[]}          ← ★ 下一轮**把记忆删了**
        ⇒ 记忆没了 ⇒ 不再受"买完不放回"保护 ⇒ 又进目标 ⇒ 又点开 ✗
        （map 3 的 `5,7` score=0.669 一模一样，两图各复发一次 ✓）
      ---- 根因：**同一个概念写了两套判据** ----
        · `cells_of()` 收 buy 用
            strong = score >= BUY_SCORE_MIN **or** _buy_top_self(v)
          （2026-10-16 为治「旅行商人认不到」加的**顶部自洽**放宽：真商人天生 NCC 低，
            实测 0.689~0.847 ⇒ 单靠 0.85 连**已揭示**的商人都挡 ✗）
        · 而**本函数**（`_prune_bought_done` 靠它判"那格还是不是商人"）**只认 score**
          ⇒ 0.695 < 0.85 ⇒ 判"它不在了" ⇒ 清记忆 ⇒ 反复点 ✗✗
        ⇒ 与 `alchemy.py:340` 那条「找到时认它、后续判断却不认」**完全同一个形状**
          —— 本项目第 N 次"判据写在两处、迟早漂移" ✓
      ---- 修法 ----
        `strong_only` 分支改成**与 `cells_of` 逐字同口径**：
            strong = (score >= BUY_SCORE_MIN) or _buy_top_self(v)
        ⇒ 商人 0.695 但 top-gap 够 ⇒ **继续算"还在"** ⇒ 记忆不被删 ✓
      ⚠ 方向安全：把"还在"判多了 ⇒ 最多多花一次"开面板看一眼"；
        判少了（现状）⇒ 反复点、反复开面板（用户看到的正是这个 ✗）
      ⚠ `strong_only=False` 的调用方（`_blocked_px` 等）行为**不变** ✓
      ⚠ 真商人面板里**本来就有 4 档**（买完面板仍在）⇒ 这也是"反复点"会看到的路由；
        修好后第一轮就记住，不会再开第二次 ✓
    """
    out = []
    for (r, cc), v in sorted(((c or {}).get('st') or {}).items()):
        v = v or {}
        if v.get('anchor') != (r, cc):
            continue                          # 多格物件只按锚点算一次 ✓
        nm = str(v.get('name') or '')
        if not any(k in nm for k in _COLOR_TILES):
            continue
        # ⛔⛔⛔ 2026-10-24 **判据与 `cells_of` 逐字同口径**（见 docstring 的铁证）
        #   ---- 病 ----
        #     原来只认 `score >= 0.85`；而 `cells_of` 早就放宽成
        #     `score >= 0.85 **or** _buy_top_self(v)`（真商人 NCC 天生低，实测 0.689~0.847）
        #     ⇒ **同一格**：进 buy 列表时算商人、判 pruned 时不算商人 ✗
        #     ⇒ 真机 0.695 的商人买完 → 下一轮记忆被删 → 反复点开（用户报的就是这个）
        #   ---- 修 ----
        #     两处**用同一个表达式**。别再各写一份（本项目已有太多次同族教训 ✓）
        if strong_only and not _cell_is_strong_buy(v):
            continue
        if revealed_only and not bool(v.get('revealed')):
            continue
        out.append(marks_mod.cell_center(r, cc))
    return out


# ⭐⭐ 2026-10-02 从手机端搬来（v1.29）：**探索模式闸门** —— 治「1~4 轮就退图」
#   PC 端原来只有 `targets_done`（没有目标就退），**缺**这道闸：
#     `marked=0 / pending_buy=0 / grays=20 / clicks=0` ⇒ 旧代码 `order=[]`
#     ⇒ 判 targets_done 退图 ⇒ **20 个暗格一格没开就收工**，25 体力白花 ✗✗
#   手机端真机包 `进图发了会呆就退出了.zip` 就是这条判据缺失导致的
#   （`r3 finish: targets_done, gray_left: 24`）⇒ 现在 PC 端补齐 ✓
EXPLORE_MIN_GRAY = 8        # 还剩 ≥8 暗格 = 「盘还没探开」（要探）
EXPLORE_MAX_CLICKS = 40     # 探图预算，防为了探图无限花体力 ✗
# ⭐ ratio = 「已揭示」的下限（与 `spots` 的 revealed、`vault_probe_px` 的口径同源 ✓）
#   已揭示格 ratio≈1.0，雾格≈0.65（真机实测间隔很干净）
#
# ⭐⭐⭐⭐ 2026-10-05 **0.75 → 0.97**（用户三连报「规划不对」的真根因之一）
#   真机 1068 个格的 ratio 分布（`runs/loop/loop_log.json` 全量 board）：
#       **雾簇**   0.61~0.80（698+49+4 个）＋ 0.851（map23 那两格）
#       **带标记的雾格** 0.910 / 0.910 / 0.910 / 0.928 / 0.941 / 0.954
#         ← ⭐ 这 6 个**全带 boss 标记**：雾格上画了亮图标 ⇒ ratio 被抬高 ✗
#       **已揭示簇** 0.984 / 0.985 / 0.986 / 0.989 / 0.993 / **0.994（绝大多数）** 起
#   ⇒ 两簇之间是干净的 **0.954 → 0.984** 空隙 ⇒ 取其**中点 0.97**：
#     离最坏的"带标记雾格" 0.954 有 **+0.016**，离最保守的"真已揭示" 0.984 有 **-0.014** ✓
#   ⚠ 旧值 0.75 太低：把 map23 的 `(2,7)/(3,6)`（0.851）判成"已揭示" ⇒ 计划去点雾格空转 ✗✗
#   ⚠ 也别取 0.99：那会把 0.984~0.989 的真格（勇者之墓/游乐设施这类偏暗的内容格）判成雾 ✗
#   方向安全（本项目一贯口径）：把"已亮但偏暗"的格当雾 ⇒ 模型最多多规划一步"点它"，
#     点已亮的格是正常消耗、有进展；**反过来（把雾当亮）才会死锁** ⇒ 宁高勿低 ✓
REVEAL_RATIO_MIN = 0.97


def need_explore(marked, pending_buy, grays_n, clicks):
    """⭐ 该不该「先探图」（没有目标、但盘还没探开）—— 纯函数，可离线对拍 ✓

    真机 `进图发了会呆就退出了.zip` 那一局：marked=0 / pending_buy=0 / grays=24 / clicks=0
    ⇒ 旧代码 order=[] ⇒ 判 targets_done 退图（24 个暗格一格没开）✗
    ⇒ 现在返回 True ⇒ 走探索模式（沿已揭示的可点格往外开，逼出标记/宝库）✓
    """
    return (not marked and not pending_buy
            and int(grays_n) >= EXPLORE_MIN_GRAY
            and int(clicks) < EXPLORE_MAX_CLICKS)


def _ready_boss_cells(st, order):
    """点序里**当下就能点**的首领/红装格（按原顺序）—— 纯函数 ✓

    「能点」= 该格在 `st['obs']`/本帧分类里是**已揭示**（ratio 落在揭示区间）。
    ⚠ 分类器能看穿雾 ⇒ **必须用 ratio 判揭示**，不能看 score
      （`_cells_for_model` 里那段踩坑注释：score≥0.8 的雾格是常见误判 ✗）。
    ⚠ **点不动的首领（还在雾里）绝不返回** —— 提上来也点不动，
      只会白花一体力并把真正该点的素材格挤掉 ⇒ 反而更差 ✗
    """
    _mk = st.get('marks') or {}
    if not _mk:
        return []
    _obs = st.get('obs') or {}
    _frame = st.get('frame_st') or {}
    out = []
    for _rc in order:
        _k = (_rc[0], _rc[1])
        _marks = list((_mk.get(_k) or {}).get('marks') or [])
        if not any(m in ('boss', 'redEquip') for m in _marks):
            continue                                    # 只管首领/红装 ✓
        _cell = _obs.get(_k) or _frame.get(_k) or {}
        _ratio = _cell.get('ratio')
        try:
            _ratio = float(_ratio) if _ratio is not None else None
        except (TypeError, ValueError):
            _ratio = None
        if _ratio is None:
            continue            # 认不出揭示状态 ⇒ 保守当「点不动」（fail-safe ✓）
        if _ratio < REVEAL_RATIO_MIN:
            continue
        out.append(_rc)
    return out


def _hoist_ready_boss_first(st, order, log=None, tag='solver'):
    """⭐⭐ 把「当下能点的高价值格」提到点序**最前面**，其余顺序不动

    手机端真机铁证（`fb_20261002_015406`）：`marks {"2,3": ["boss","recommend"]}` +
    `solver order ["3,5","2,3"]`，同一轮 `popup: fight_panel` 已弹出 ⇒ boss **可打**
    却被排在第 2 位 ⇒ 先白点一格素材 ✗

    ⚠ 只调整**执行顺序**，不碰解算器的结果本身（cost/其余步骤一律不变 ✓）
    ⚠ 任何异常都不改变点序（fail-open ✓）
    """
    try:
        if not order:
            return order
        _ready = _ready_boss_cells(st, order)
        if not _ready:
            return order
        _rest = [rc for rc in order if rc not in _ready]
        _new = _ready + _rest
        if log is not None and _new != list(order):
            log.append({tag: 'boss_hoisted',
                        'ready': ['%d,%d' % p for p in _ready],
                        'was': ['%d,%d' % p for p in order],
                        'now': ['%d,%d' % p for p in _new]})
        return _new
    except Exception:       # noqa: BLE001
        return order


def vault_probe_px(c, st):
    """**强匹配但被判"未揭示"**的宝库/商人格 —— 也值得点一下（验证式）

    根因（2026-10-01 真机复盘）：`revealed = ratio >= 0.75`，而
    `ratio = 格亮度 / **命中模板**亮度` ⇒ **模板一换，同一个已揭示的宝库格也会掉到
    0.75 以下**（真机：NCC 0.95+ 却 ratio 0.638 ⇒ 判"未揭示"）⇒ 它既进不了 `buy`、
    又被当"点不动"⇒ **机器人看着宝库不打，跑去开路/打拦路** ✗
    而 NCC 分数是**形状**匹配（与亮度无关）⇒ 分数高 + 名字是宝库/商人 = 值得点一次 ✓
    （点进去若真是雾格 ⇒ 白点一下，游戏不消耗；实测雾格点击 = 画面毫无变化 ⇒ 无损 ✓）

    上限 `BUY_PROBE_MAX` 次/格/图（防"一直点不开"空转，见 2026-09-25 卡死事故 ✓）。
    """
    probe = st.setdefault('buy_probe', {})
    out = []
    for p in vault_px_now(c, revealed_only=False, strong_only=True):
        if probe.get(p, 0) >= BUY_PROBE_MAX:
            continue
        out.append(p)
    return out


def vault_still_there(st):
    """该像素现在**还**是不是宝库/商人（当前帧 ∪ 跨轮累积观测 `st['obs']`）

    ⚠ 2026-10-01 v0.96 修**死代码**：原写法 `(st['cells'] or {}).get('board')` ——
    `st['cells']` 是分类器原样 dict（键是 `(r,c)` 元组，**没有 `board` 这个键**）
    ⇒ `_still_buy` 恒为空 ⇒ 「已买完/消耗就剔出粘性集」这条**永远不生效** ✗
    ⇒ 粘性宝库挂满 20 轮 = **幽灵目标**（真机日志：每一轮都是「没有目标了」却「还剩 1 个目标」，
    然后满地图开路打拦路 ✗）。这里按"当前帧 ∪ obs 里名字里还有宝库/商人"判定 ✓
    （买掉后该格名字会变成空地 ⇒ 立刻剔除 ✓，见 obs 的"已揭示+名字变了立即覆盖"规则 ✓）
    """
    out = set()
    for _src in ((st or {}).get('cells') or {}, (st or {}).get('obs') or {}):
        try:
            for _rc, _v in _src.items():
                _nm = str((_v or {}).get('name') or '')
                if any(k in _nm for k in _COLOR_TILES):
                    out.add(marks_mod.cell_center(_rc[0], _rc[1]))
        except Exception:       # noqa: BLE001
            pass
    return out


_PLAIN_CACHE = {}


def is_plain_spot(sid):
    """该地块是不是「空地」（Area_Spot: SpecialSpot==0 且 SpotSize==1）——才能点它揭一片"""
    if sid not in _PLAIN_CACHE:
        row = spots_mod.spot_rows().get(sid) or {}
        try:
            _PLAIN_CACHE[sid] = (int(row.get('SpecialSpot') or 0) == 0 and
                                 int(row.get('SpotSize') or 1) == 1)
        except Exception:           # noqa: BLE001
            _PLAIN_CACHE[sid] = False
    return _PLAIN_CACHE[sid]


def close_x_panels(b, img=None):
    # ⭐ v0.31 方案 B：真机上弹窗 X 关闭符（dlg≈225）落在 toRef 丢弃的弹性区 ⇒
    #   归一化帧上根本看不见 ✗ ⇒ C>0 时改用**弹窗帧**（b.img_dlg，Java 重投影）找，
    #   检测常数（67x67 / x≈493,1024 / y 带 180~300）就是弹窗系标定值，原样可用 ✓
    #   PC / 9:16 C=0 ⇒ 走原路，行为一字不变。
    _dlg = dlg_c()
    _im = None
    if _dlg:
        _im = b.img_dlg() if hasattr(b, 'img_dlg') else None
        if _im is None:              # 弹窗帧拿不到 ⇒ 退回归一化帧（聊胜于无）
            _dlg = 0.0
    im = _im if _im is not None else (img if img is not None else b.img())
    bb, gg, rr = cv2.split(im.astype(int))
    red = ((rr > 150) & (rr - gg > 70) & (rr - bb > 60))
    band = np.zeros_like(red)
    band[180:300, :] = True
    m = (red & band).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _l, st, ce = cv2.connectedComponentsWithStats(m, 8)
    xs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        # 真关闭钮恒 67x67 且**只在 x≈493 / x≈1024**（左右两块面板各一个）。
        # ⚠ 只按尺寸筛会点到居中面板上的 (759,225) —— 那是回放相关按钮，
        #   点它就会放一遍回放（用户 09-25 连报三次）
        cx0 = int(ce[i][0])
        if 1500 < a < 8000 and 55 <= w <= 72 and 55 <= h <= 72 and \
                min(abs(cx0 - 493), abs(cx0 - 1024)) <= 60:
            xs.append((cx0, int(ce[i][1])))
    xs.sort(reverse=True)
    for (x, y) in xs:
        if _dlg:
            b.tap_dlg(x, y, wait=1.6)    # 弹窗帧坐标 = 弹窗系 ⇒ 走弹窗点击通道
        else:
            b.tap(x, y, wait=1.6)
    return len(xs)


# ⭐ 2026-09-27：大厅专属 UI（`_probe_lobby_sig.py` 三图对拍得出）
#   ⚠ **绝对不要**用「底部导航有 角色/斗技场/图鉴/开始冒险」判大厅 ——
#     实测**大厅 / 选图界面 / 地图界面三者底部都有这套导航**（全局导航栏）✗
LOBBY_CORNERS = ('攻略', '活动', '首充', '情报')     # 大厅四角入口（另两者都没有）
LOBBY_BANNER = '免费指定招募'                        # 大厅中部招募横幅


def in_lobby(items):
    """是否在**大厅（主界面）**

    实测三图 OCR 对拍（`_probe_lobby_sig.py`，2026-09-27）：

        特征                              大厅   选图界面  地图界面
        底部导航(角色/斗技场/图鉴/开始冒险)  ✓      ✓        ✓    ← 不可用 ✗
        四角入口 攻略/活动/首充/情报        ✓      ✗        ✗    ← 用它 ✓
        「免费指定招募」横幅                ✓      ✗        ✗    ← 用它 ✓
        帮助 + NNN% / 当前难度NNN           ✗      ✓        ✓
        快速扫荡 / 进入地图 (y≈1618)        ✗      ✓        ✗
        结束冒险(y≈773) + 图名[难度]        ✗      ✗        ✓

    为什么必须能认出大厅：2026-09-27 实例B跑采图时**游戏自己重启**停在大厅，
    `in_map()` 的格子兜底把大厅背景数成 8+ 格 ⇒ 误判"已在地图里" ⇒ 恢复路径不触发。
    """
    if not items:
        return False
    txt = [i.get('text') or '' for i in items]
    if any(LOBBY_BANNER in t for t in txt):
        return True
    return sum(1 for h in LOBBY_CORNERS if any(t == h for t in txt)) >= 2


# ⭐⭐ 2026-09-29 真机踩坑：MGAS 自己的界面（或应用双开选择框）被格子兜底数成 13 格
#   （中位分 0.186）⇒ in_map 误判"已在地图" ⇒ 对着自己界面点了一整轮。
#   ⇒ 所有"我在看什么"的判定**先认自己的 UI 标记**：命中 ≥2 个 ⇒ 一定是自己的界面。
_SELF_UI_MARKERS = ('开始探索', '停止探索', '红装解锁', '授权截图', '推图日志',
                    '清空日志', '要使用的应用', 'MGAS')


def self_ui_hits(items):
    """当前帧里有几个 MGAS 自己的 UI 标记（≥2 ⇒ 画面是本应用/系统选择框，不是游戏）"""
    if not items:
        return 0
    hits = 0
    for it in items:
        t = (it.get('text') or '').replace(' ', '')
        if not t:
            continue
        for m in _SELF_UI_MARKERS:
            if m in t:
                hits += 1
                break
    return hits


def _login_page_hits(items):
    """当前帧里命中几个「**只在登录页出现**」的字（2026-10-01 v1.16 新增）。

    ⭐ 背景（MuMu 1264×2780 实测）：游戏没登录态时停在登录页，
    而 `in_map()` 的每一条否定证据在登录页都不成立 ⇒ 只能靠格子兜底
    ⇒ **把登录页误判成"已在图里"**（实测后果：`本图结束：stuck`，白跑 62 秒）。

    判据与 `game_recover._game_main_ok`（本文件内）**同源** —— 那几个字是
    `_game_main_ok` 判定"还没恢复成功"的同一批，所以不会自相矛盾。
    **≥1 就够了**（不要求多条同时出现：进登录动画时可能只 OCR 到其中一个）。
    """
    n = 0
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if (not t) or len(t) > 40:       # 跳过整行说明文字（不是按钮/标题）
            continue
        for k in ('开始游戏', '我已详细阅读', '健康游戏忠告', '登出', '适龄提示',
                  '批准文号', '出版物号', '游戏软著', '如遇登录或充值问题'):
            if k in t:
                n += 1
                break
    return n


def in_map(b, img, items):
    """是否已经在探索地图里

    ⚠ 2026-09-25 踩坑：选图界面中间那张**地图预览图**会被地块分类器"认出一堆格子"，
      于是 `cells_of` 判定通过 → 误判成"已在地图里" → 循环直接走「目标清完退图」，
      表现成「这两轮进不去地图」。现在：
        ① 先看图内特征：结束冒险 / HUD 行(背包·神石·预言 y900~1000) / 带 [难度] 的图名
        ② 一旦看到选图界面的「快速扫荡 / 进入地图」→ **明确判为不在图里**
        ③ ⭐ 大厅（四角入口/招募横幅）→ **明确判为不在图里**（2026-09-27 游戏重启后停大厅，
           大厅背景格会被下面的格子兜底数成 8+ ⇒ 误判"已在地图里"⇒ 恢复路径不触发 ✗）
        ⑤ ⭐⭐ 2026-09-29 真机：**MGAS 自己的界面 / 应用双开选择框** 也会被格子兜底数成 13 格
           （中位分 0.186）⇒ 误判"已在地图里" ⇒ 对着自己点 47 秒。先认自己的 UI 标记 ✓

    ⛔ 2026-10-02 撤回一条**错误**提速（留此记录，别再犯）：
       曾试过「模板快查确认在图内就短路返回 True」。**错在前提**——
       底部导航条在**大厅 / 选图 / 图内三个界面都常驻**（README 与 `in_lobby` 注释
       都写明过，实测 5 个导航模板在图内帧全 1.00 命中）⇒ 「导航条在」**推不出**
       「在图内」⇒ 会把大厅/选图误判成已进图 ⇒ 后面整套流程全错。
       ⇒ 提速只能做**单向且真有效**的那类（固定按钮直接点、band 收窄），
         **不许**拿"多处都有"的东西当界面判据。
    """
    if self_ui_hits(items) >= 2:
        return False
    if exb(items, L['end']):
        return True
    for it in items:
        if LAYOUT.sy(900) < it['cy'] < LAYOUT.sy(1000) and it['text'].strip() in L['hud']:
            return True
    # ⛔⛔⛔ 2026-10-27 **修一条**永远不命中**的判据**（实测铁证）**
    #   ---- 病 ----
    #     原来窗口写的是 `sy(150) < cy < sy(215)`，而**真机图名实测 cy≈122**：
    #       `runs/r_195513_0.png`  → `cx=360.0 cy=122.2 conf=0.91 '夏日海滩[100]'`
    #       `runs/acc3/r_123219_0.png` → 同样 cy=122
    #     ⇒ `122 < 150` ⇒ **这条判据从诞生起就没生效过** ✗✗
    #     （本项目第 N 次「判据在拿不到数据的地方」）
    #   ---- 影响 ----
    #     图内识别现在**只靠「结束冒险」**那一条（`exb(items, L['end'])`）。
    #     「结束冒险」是**结算/浮层**才有的按钮 ⇒ **进图首帧没有它** ⇒
    #     若那时别的判据也不命中 ⇒ `in_map` 判否 ⇒ `enter_map` 白等 9 轮 ✗
    #     ⚠ 2026-10-27 真机 `acc3` 12:43 那把就是这么失败的：
    #       点了 2 次「进入地图」(603,1079)，24 秒间隔，最后 `enter: timeout` ⇒
    #       整局以「进图失败」收工（体力 1997 明明够）✗
    #   ---- 修 ----
    #     窗口改成 **`sy(100) < cy < sy(215)`**（实测 122 落在中间 ✓），
    #     判据本身（`^.+\[\d+\]\s*$`）**一个字不改** ✓
    #     ⚠ 只放宽下界：上界 215 保留（再往下是战斗横幅区，容易误读） ✓
    for it in items:
        if LAYOUT.sy(100) < it['cy'] < LAYOUT.sy(215) and re.match(r'^.+\[\d+\]\s*$', it['text'].strip()):
            return True                      # 「夏日海滩[100]」这种只在图里出现
    if fb(items, *L['menu']):
        return False                         # 选图界面（快速扫荡/进入地图）
    # ⭐⭐⭐ 2026-10-01 v1.15【朋友机 realme RMX3800 / 1264×2780 实测】：
    #   他那台上「快速扫荡/进入地图」在 ref y≈**1618**（比本机更低），一旦这两条没被读到
    #   （进图动画帧 / 文字被压暗），下面的"格子兜底"就会把**选图界面**判成"在图里" ✗
    #   ⇒ 用户看到的是：进去就"面板挡住了棋盘 · 正在收起"，一直卡着，其实一次地图都没进 ✗✗
    #   ⇒ 补两条**只在选图界面出现、且在画面中部**（不受分辨率/band 影响）的字：
    #      `深渊NN`（难度页签）与 `星界秘境`（右下挑战入口）✓
    if any(('深渊' in it['text']) or ('星界秘境' in it['text']) for it in items):
        return False
    # ⭐⭐⭐ 2026-10-01 v1.16【登录页误判】（MuMu 1264×2780 实测）：
    #   游戏**没有登录态**时停在登录页（开始游戏 / 隐私政策 / 健康游戏忠告），
    #   而登录页没有「结束冒险/HUD/图名[难度]」、也没有「快速扫荡/进入地图」，
    #   下面所有否定证据全不成立 ⇒ 只能靠格子兜底 ⇒ 把登录页**误判成"已在图里"** ✗
    #   表现：日志「已进图，体力 ?」→ 棋盘区落在登录页空白文字区 → 判「棋盘被挡」
    #        → 反复关面板 → `本图结束：stuck`（实测 62 秒）。
    #   判据与 `game_recover._game_main_ok` **同源** ⇒ 读到就一定**不在图里** ✓
    if _login_page_hits(items) >= 1:
        return False
    if in_lobby(items):
        return False                         # ⭐ 大厅（四角入口 / 免费指定招募横幅）
    c = cells_of(img, mapname=map_name(items))
    n = len(c['gray']) + len(c['light'])
    if n < 8:
        return False
    # ⭐ v1.15：格子兜底还要看**有没有真·已揭示的亮格** —— 真棋盘进图时营地恒已揭示
    #   （ratio≈1.0）；而"选图界面/进图动画"那种帧被兜底数出来的格子全是压暗的
    #   （朋友机日志实测：`light: 0/1, gray: 16/17`，全盘 ratio<0.55）
    #   ⇒ 旧写法"≥8 格就算在图里"正是那次误判的最后一根稻草 ✗
    try:
        _mx = max([float((v or {}).get('ratio') or 0)
                   for v in (c.get('st') or {}).values()] or [0.0])
    except Exception:       # noqa: BLE001
        _mx = 0.0
    return bool(c['light']) and _mx >= 0.75


_MAPNAME_STOP = ('难度', '当前', '帮助', '回合', '存活', '不超过', '胜利', '战斗',
                 '入侵', '进度', '时间', '倒计')   # ⭐ 图名判据的停用词（真机帧实证 ✓）


def map_name(items):
    """从 HUD 顶部读当前图名（如「夏日海滩[100]」-> 夏日海滩）

    ⚠ 别只按 y 带取：同一带里还有左上角的「首领战斗胜利」横幅（cy≈166），
      曾经把图名读成「古首领战斗胜利」→ 分类器认不出图号 → 全部退回旧启发式。
    ⚠⚠ 2026-10-03 又踩一次（真机日志）：**右边那颗「当前难度1000」**（x≈651）也在
      这个 y 带里 ⇒ 被当图名 ⇒ 走进"15 个代码全量兜底"（≈7.5s/图 + 选错风险）✗
      ⇒ 现在要求「**居中** + 纯中文 2~6 字 + 非停用词」✓（见下面 `_MAPNAME_STOP`）
    """
    if items is None:
        return None
    for it in items:
        m = re.match(r'^(.+?)\s*\[(\d+)\]\s*$', it['text'].strip())
        if m:
            return m.group(1).strip()
    for it in items:
        t = it['text'].strip()
        # ⭐⭐⭐ 2026-10-03 真机修（用户贴的日志实证）：
        #   `· 图名「当前难度1000」有歧义 [15 个代码] ⇒ 实测选 S10002`
        #   ⇒ 第二条判据**把右边的「当前难度1000」当图名了** ✗
        #     （它实测在 y≈184 / **x≈651** ⇒ 正好落在旧的 y 带 160~210 里，
        #      而旧判据只挡了「战斗/胜利」⇒ 漏 ✗）
        #   后果：图名对不上 ⇒ 走**全量兜底**（15 个代码各分类一次 ≈7.5s/图 ✗）
        #         且有选错代码的风险 ✗
        #   ⇒ 补三条（都来自真机帧的实测位置/字形）：
        #     ① 图名**居中**（实测 广袤草原 x=358 / 夏日海滩 x=359 ⇒ ±100 内 ✓；
        #        「当前难度1000」在 x=651 ⇒ 排除 ✓）
        #     ② 纯中文 **2~6 字**、不含数字/百分号/括号（图名没有数字 ✓）
        #     ③ 停用词（难度/当前/帮助/回合/存活/不超过/入侵/胜利…）
        _is_c = abs(it['cx'] - LAYOUT.sx(360)) <= LAYOUT.sx(100)
        _ok_t = (2 <= len(t) <= 6 and re.match(r'^[\u4e00-\u9fa5]+$', t)
                 and not any(k in t for k in _MAPNAME_STOP))
        if (LAYOUT.sy(160) < it['cy'] < LAYOUT.sy(210) and _is_c and _ok_t):
            return t
    return None


def find_x(items):
    """独立关闭符。⚠ 实测面板关闭符**只在 x≈493 / x≈1024 两处**（左右两块面板各一个）；
    结算面板上 (759,225) 那个「X」夹在中间，是回放相关按钮 —— 点它就会放一遍回放
    （用户 09-25 连报两次「还在看回放」）。"""
    for it in items:
        if it['text'].strip() not in ('X', 'x', '\u00d7', '\u2715', '\u2716'):
            continue
        # ⭐ 坐标过布局层（720p 下 493/1024 要跟着缩 ✓）
        if min(abs(it['cx'] - LAYOUT.sx(493)),
               abs(it['cx'] - LAYOUT.sx(683))) <= LAYOUT.sx(40):
            return it
    return None


# ⭐ 2026-09-26 死循环根因修复（用户在实例B实测：探索槽满 + 紫橙探索格 ⇒ 卡死 45 轮、
#   体力/回合都不动 ⇒ 最后"退出地图失败"）
#   根因：`popups()` 里多处是「关一下 X ⇒ 就 return 'handled'」——**没人验证面板真的关掉了**。
#   一旦没关掉，下一帧还是同一段面板文字、又命中同一分支、又 return 'handled'，
#   整个闭环被这一句占住 ⇒ 不揭格、不打架、也不 reach 到 finish。
_PANEL_STUCK = {}


def panel_gone(b, probe, tag='unstick', dlg_btn=None):
    """关面板之后**重新截图验证**它真的没了 ✓（probe = 之前认到的那段面板文字）

    ⭐ v0.32：真机上面板标题（「探索产出/战斗事件」dlg≈443）落在 toRef 丢弃的弹性区
    ⇒ 归一化帧里永远看不见 ⇒ fb 恒 False ⇒ 会误判"已关" ✗
    ⇒ 传 dlg_btn（面板按钮文字，如「探索」）时补一道弹窗系验证：按钮还在 ⇒ 面板没关掉

    ⭐⭐⭐ 2026-10-02 提速审计：**先用便宜图像判据短路**（`cells_of` 0.35s、**0 OCR**）
      棋盘重新可见 ⇒ 面板（不管哪一个）一定已经不在了 ⇒ 直接 True ✓
      ⚠ 只在图像**证明不了**"面板没了"时才付那次 OCR ⇒ 行为与改动前**一致或更好**，
        不会因为提速而更差 ✓（用的是本文件自己那套 `board_hidden()`，
        它已按真帧标定、门禁㉗×4 守着）
      代价：每次"关面板后验证"从 ≈0.9s 降到 ≈0.35s（省一半以上）
    """
    try:
        _im0 = b.img()
        # 2026-10-27 need_names=False：这里只看「棋盘压没压暗」
        #   （board_hidden 只读 gray/light/st.ratio）=> 不需要地块名
        #   => 跳过 15 个 code 全量消歧（省时间 + 不打那句误导日志）
        if _im0 is not None and not board_hidden(
                cells_of(_im0, need_names=False)):
            return True
    except Exception:                       # noqa: BLE001
        pass
    if _OCR_CH['dlg'] and hasattr(b, 'ocr_dlg'):
        items = ocr_ch(b, tag=tag)      # ⭐ 弹窗模式：标题只在弹窗帧里，查归一化帧会误判"已关"
    else:
        b.snap(tag)
        items = b.ocr(tag=tag)
    if fb(items, probe):
        return False
    if dlg_btn and dlg_c() and _dlg_panel_btn(dlg_items(items), dlg_btn):
        return False
    return True


def force_unstick(b, log, why, ctx=None):
    """面板关不掉时的脱困：已知关闭点全试一遍 + 拉黑当前格 ⇒ 让循环能往后走 ✓"""
    tries = []
    # ⭐ v0.31 方案 B：这三个都是**面板上的**关闭点（弹窗系标定值）⇒ 走 tap_dlg
    #   （真机上原 b.tap 会落在面板下方/弹性区，全空点 ✗）
    # ⛔⛔⛔ 2026-10-02 修「点开探索格子后不知道点哪里就关了」（用户实测）：
    #   原来第一项写死 `(539, 1212)` —— 那是 **1080p 参考系**的「面板返回」，
    #   **从没换算过**。720×1280 上 y=1212 落在**底部导航条**里
    #   （`fixed.start_adv_icon`=(360,1219)、`nav_*` 全在 y≈1260）
    #   ⇒ `force_unstick` 不是在「关面板」，而是在**乱点导航** ✗✗
    #   ⇒ 表现就是用户说的「不知道点哪里就关了，没有正确探索」。
    #   ⇒ 现在三处全部走 `LAYOUT.sx/sy()`（或 `fixed` 锚点），两个基准都对 ✓
    #   720p 换算后：返回 (359,808) / 左X (329,150) / 右X (455,100)
    for (bx, by, w) in ((int(LAYOUT.sx(539)), int(LAYOUT.sy(1212)), 1.6),
                        (int(LAYOUT.sx(493)), int(LAYOUT.sy(225)), 1.2),
                        (int(LAYOUT.sx(683)), int(LAYOUT.sy(150)), 1.2)):
        # ⚠ 安全门：y 必须**离底部导航条足够远**（nav 行 y≈1260），
        #   否则又会变成「乱点导航」—— 换算后再钉一道，别只靠折算 ✓
        if by > LAYOUT.sy(1150):
            continue
        b.tap_dlg(bx, by, wait=w)
        tries.append((bx, by))
    try:
        tp = (ctx or {}).get('tapped')
        fl = (ctx or {}).get('flags') or {}
        if tp:
            fl.setdefault('done', set()).add((int(tp[0]), int(tp[1])))
    except Exception:           # noqa: BLE001
        pass
    log.append({'unstick': why, 'tried': tries})
    return tries


def find_orange_btn(img, x0=None, x1=None, y0=None, y1=None):
    # ⭐ 默认范围也要随分辨率缩 ✓
    x0 = LAYOUT.sx(200) if x0 is None else x0
    x1 = LAYOUT.sx(600) if x1 is None else x1
    y0 = LAYOUT.sy(600) if y0 is None else y0
    y1 = LAYOUT.sy(920) if y1 is None else y1
    """按颜色找面板底部那颗**橙色艺术字按钮**（「战斗」/「探索」都是这种字），
    返回最靠下的大色块中心 —— 比固定 y 稳（不同面板版面会挪位置）。

    艺术字实测色 ~ RGB(240,170,90)：R 高、G 中、B 低。
    """
    win = img[y0:y1, x0:x1].astype(int)
    b, g, r = cv2.split(win)
    m = ((r > 190) & (g > 120) & (g < 215) & (b < 130)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _l, st, ce = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 400 or w < 30:
            continue
        cy = int(ce[i][1]) + y0
        if best is None or cy > best[1]:
            best = (int(ce[i][0]) + x0, cy, int(a))
    return best


# ⭐⭐ 2026-10-01 修「地图界面被当成已开打」的假判（1264×2780 全分辨率实跑暴露）：
#   旧判据是**子串**匹配（`'回合' in t` / `L['win'] in t`），而《遗忘之海》地图 HUD
#   自带两条**常驻文案**：
#     · `★首领战斗不超过8回合`        ← 任务条件，含「回合」
#     · `首领战斗胜利` + `首领战斗2人存活` ← 任务达成状态，含「战斗胜利」
#   ⇒ 在图上点完「战斗」后只要 OCR 一次，这两个词必然命中 ⇒ **假判"已进战斗"**
#   ⇒ wait_end 空等 20 秒 → `back_in_map`，格子根本没打 → 下一轮原样再来一遍
#     （2026-10-01 14:29 实测：连打 4 轮「开打 · 拦路格」、STATS 战斗 0 场，
#       最后靠 same_action×4 强制脱困才停 ✗；离线复现见回归套件 ㉘ 组）
#   真·战斗/结算界面的文本形态（真机帧 `runs/bw2.json` 实测 ✓）：
#     `战斗胜利` / `战斗失败` —— **整条**（不是"首领战斗胜利"这种带前缀的横幅）
#     `第1/10回合` —— **整条**（正则）｜`加速` / `自动跳过` / `回放战斗`（战斗专属控件）
#   ⇒ 判据改成「整条严格匹配」+「带地图任务标记（★ / 不超过）的句子一律不算」✓
#   ⚠ 真·战斗界面行为不变（这些文本在真战斗里照样命中 ✓）；PC/9:16 同口径 ✓
_ROUND_RE = re.compile(r'^第\s*\d+\s*(?:[/／]\s*\d+\s*)?回合$')
_BATTLE_STRONG = ('加速', '自动跳过', '回放战斗')
_MAP_OBJ_MARK = ('★', '不超过')


def battle_started(items):
    """是否已进入战斗：看战斗特征，而不是「战斗事件面板消失没」。

    ⚠ 点一格可能同时弹出两块面板（目标格 + 相邻格）：打的那块开打后，
      另一块面板的「战斗事件」文字还在 -> 只看它消失会把**已经开打的**误判成没打
      （用户 09-25：「那场明明打完并且赢了」）。
    ⚠⚠ 但**不能**用宽子串（见上面那段教训）：地图自身的任务横幅也含「回合 / 战斗胜利」。
    """
    for it in items:
        t = (it.get('text') or '').strip()
        if t == L['win'] or t == L['lose']:          # 整条等值（"首领战斗胜利" 不算 ✓）
            return True
        if _ROUND_RE.match(t):                       # "第1/10回合" / "第3回合" 整条
            return True
        if any(k in t for k in _BATTLE_STRONG) and not any(k in t for k in _MAP_OBJ_MARK):
            return True
    return False


# ⭐⭐⭐ 2026-10-04 S 级提速：结算面板的**图像判据**（给 `battle_started_fast` 用）
#   ⚠ 两个搜索框都写死成 **720×1280 设备坐标**，且**直接**传给 `fixed.has(box=…)`。
#     为什么不走 `fx_has(b, name, band=…)`：那个 `band` 参数收的是 `fixed.BANDS` 的
#     **字符串键名**（它内部做 `BANDS.get(band)`）—— 传元组会 `.get()` 到 None
#     ⇒ **静默退化成全屏搜索**（结果对、但白花 3~5 倍时间）。这里不踩那个坑 ✓
#     （同一个坑 `wait_end` 也踩过 —— 2026-10-04 已一并修掉：那里改成 `band='settle'`；
#       根因最早由 `d7f13c2` 在"领取"那条路上诊断并修过一次，见该提交说明）
_BATTLE_TITLE_BOX = (200, 70, 520, 190)     # 结算标题「战斗胜利」；x0=200 ⇒ 排除地图横幅
# 结算面板底部「关闭」按钮带（close_tpl_{0,1,2} 的**紧搜索框**）
#   ⚠ 2026-10-04 实测收紧（原来的 (0,780,720,1080) 是**整条下半屏**，太浪费）：
#     全量 793 张真机结算帧上，模板命中位置只有两种（`close_tpl_0` 792 张在 (384,960)、
#     `close_tpl_1`/`_2` 各 1 张在 (379,876) ⇒ 不同版面高度）⇒ 取两者并集 + 15px 余量。
#     收益：3 连查 **40.1ms → 2.9ms**（快 14 倍）；门禁【1d】实测未命中路径 46.3ms → **4.6ms**。
#     安全性：同一份数据上召回 **793/793**、非结算帧误命中 **0/1753** ✓
#     （T1「只盖 close_tpl_0」召回 792/793 ⇒ 少一张；T3 再放宽只更慢、无收益 ⇒ 取本框）
_SETTLE_BOX = (327, 839, 439, 1015)
_BATTLE_TMPL_THR = 0.80                     # 比 fixed.MATCH_MIN(0.62) 严；标定间隔 0.772

# ⭐⭐⭐ 2026-10-04 第二轮提速：`start_fight` 的**模板抢跑窗口**
#   实测依据（实机 8 图 9 场，`runs/gui_20261004_151739.log` + `loop_log.json`）：
#     **9 场战斗全部**在 `k=1` 才命中结算面板（`try=0` 无重试点）⇒
#     `k=0` 那一次 OCR **每一场都在白花**（它每次都失败，实测 0.633s/次）。
#   做法：先给模板一个**只问模板、不问 OCR** 的抢跑窗口（模板一次 ~2ms，便宜到可以连问）：
#     · 窗口内命中 ⇒ **两次 OCR 全省**，而且比原来**更早**发现（0.12s 粒度 vs 原来 0.5s+OCR）
#     · 窗口内没命中 ⇒ **一秒不省地**走原来的 2 次 OCR + 顶部复核（兜底**一字没动** ✓）
#   ⚠ 窗口长度怎么取：必须 ≥「结算面板出现的时刻」（实测落在 tap 后 ~0.65~1.15s）
#     ⇒ 取 **1.6s** 留余量。代价只在"模板没命中"那条稀有路径上：多等这一窗口，
#       且**仍会**跑完整的 OCR 判定 ⇒ 不会漏判，只是慢一点（正确性不受影响 ✓）
#   ⚠ 为什么敢让 OCR 让位：模板在**全量 793 张真结算帧上召回 100%**
#     （见 `verify_battle_fast.py` 与 README §1），OCR 只当兜底。
_FAST_POLL_SECS = 1.6
_FAST_POLL_GAP = 0.12


def battle_started_fast(b):
    """图像快路径：**确证**结算面板已经在屏幕上（≈7~20ms，省掉一次 ~0.52s 的 OCR）

    ⭐ 2026-10-04 S 级提速。起因是真机耗时分账：OCR 里 `tap` = **276.4s / 530 次**
      （≈0.52s/次），其中很大一部分就是 `start_fight` 在这里反复 OCR，
      **只为问一句「开打了没」**。
      而「开打完了」在本游戏里 = **结算面板出现了**，那是**固定 UI**（位置/外观都不变）
      ⇒ 正是 `fixed.py` 该管的"能写死就写死"，用模板答这个问题：
        · ① 顶部标题「战斗胜利」→ 新模板 `battle_win_title`（`make_battle_tpl.py` 生成）
        · ② 底部「关闭」按钮   → 复用 `wait_end` 一直在用、已验证的 `close_tpl_{0,1,2}`
      标定（离线，零体力）：①正 200 张最低 **1.000** ／ 负 400 张最高 **0.199**；
      ②的标定见 `verify_fastpath.py` 【1c】（正 ≥0.986 ／ 负 ≤0.524）⇒ 阈值 0.80 稳 ✓

    ⚠⚠ **返回 False ≠ "没进战斗"** —— 只表示"模板没能确证"（可能战斗还在进行；
      也可能是「战斗失败」，而标题模板只认「战斗胜利」）。
      ⇒ 调用方**必须**继续走 `b.snap()` + `b.ocr()` + `battle_started()` 兜底，
        慢路径一行没动 ⇒ 整体行为在"模板没命中"时与改动前**逐字节一致** ✓
      （模板只做"提前确证"，绝不改判据语义 —— 这是本方案的安全底座）

    ⚠ 为什么标题模板必须限定 x∈[200,520]：地图界面左上角有一行
      **「首领战斗胜利」**（实测 bbox **(21,100)-(138,123)**），与结算标题
      **「战斗胜利」**（实测 bbox **(229,91)-(489,157)**）**y 重叠、x 不重叠**（间隔 91px）
      ⇒ 只有限定 x 带才排除得掉它。这正是 `battle_started()` 用
      「整条等值」防的那个坑（`首领战斗胜利` 是 6 字长句 ⇒ 不等于 `战斗胜利`）；
      模板这边用**空间**防 —— 同一个坑，两种防法 ✓（详见 `make_battle_tpl.py` 文件头）
    """
    if _FX is None:
        return False
    try:
        img = b.img()
        if img is None:
            return False
    except Exception:            # noqa: BLE001
        return False
    try:
        # ① 结算标题「战斗胜利」（x 带把地图横幅「首领战斗胜利」排除在外 ✓）
        if _FX.has(img, 'battle_win_title', box=_BATTLE_TITLE_BOX,
                   min_conf=_BATTLE_TMPL_THR):
            return True
        # ② 结算面板底部「关闭」按钮（复用已验证的 3 档模板 ✓）
        for _tp in ('close_tpl_0', 'close_tpl_1', 'close_tpl_2'):
            if _FX.has(img, _tp, box=_SETTLE_BOX, min_conf=_BATTLE_TMPL_THR):
                return True
    except Exception:            # noqa: BLE001
        return False
    return False


def start_fight(b, log, btn, marks=()):
    """点「战斗」→ **最多等 5s 看有没有进战斗**（用户 09-25：战斗胜利不会超过 5s，
    超过就是没进战斗）。没进就原位置再点一次（第一下可能被动画吃掉），再不行算失败。

    ⭐⭐⭐ 2026-10-02 修「明明打的就是 boss 格，却打印『标记格打不开』」（用户 20:36 报）：
      根因 = **检查循环没有重新取帧**。
        `b.tap()` 内部的 `wait_change()` 会把缓存帧更新成「**变化刚被检测到的那一帧**」
        （面板开始关/淡出的**过渡帧**），而下面 `b.ocr()` **不截图、只 OCR 上一帧**
        （见 `mapbot.Bot.img()` / `ocr()`）⇒ 循环里那两次 OCR 读的是**同一张缓存帧**
        ⇒ 中间那个 `time.sleep(0.5)` 完全没用 ⇒ 两次"检查"其实是同一次 ✗
        ⇒ 判 `no_battle_in_5s` → `not_started` → 「标记格打不开」✗✗
      铁证（离线复算，零体力）：那把判失败后 1 秒存的 `runs/notstarted.png`
        **就是结算画面**「战斗胜利(123) / 第1/10回合(230) / 回放战斗(816) / 关闭(961)」，
        我用它的**同一个 OCR 带 (130,980)** 跑 `battle_started()` = **True**
        （`第1/10回合` y=230、`回放战斗` y=816 都在带内）
        ⇒ **这一仗其实开打了、而且打赢了**，只是那一帧没被看到 ✗✗
      二次伤害（用户看到的后果）：误判 → `return 'blocked'` → `st['clear']=True`（清路模式）
        → 下一轮 boss 掉出点序（`order.marked=0`）→ `finish: targets_done`
        → **boss 没打就退图**（实际打过了，但代码不知道 ⇒ 统计没记、收尾那格也点不动）
      ⚠ 同一个教训在 `_tap_verified` 的 docstring 里早就写过一次
        （「`b.img()` 返回的是上一次 `snap()` 的缓存帧 ⇒ 前后永远是同一帧」）——
        这里是它的**第二份拷贝**。`wait_end()` 里就是对的（每次 OCR 前都有 `b.snap()` ✓）。
      ⇒ 修法（三处，都是"让它真的重新看一帧"，不引入任何新判据）：
        ① 每次 OCR 前先 `b.snap()`（**这一条才是真修**；次数仍保持原来的 2 次，
           但每一次看的都是**新帧** —— 原来那 2 次看的是**同一张**旧帧 ✗）；
        ② 判失败**之前**再用**新帧 + 顶部窄带 (40,320)** 复核一次 —— `battle_started()`
           是**战斗界面独有**的整条等值/回合正则判据（选择面板上不会命中 ✓，
           这正是上面 2882 行那段教训要求的"不能宽子串"口径）⇒ 认到就算开打成功 ✓
           窄带覆盖「战斗胜利」(y=123) 与「第N/M回合」(y=230)，只要 ~0.6s；
           ⛔ 不用全屏（2.5s）—— 按 PC 提速约定能窄带就窄带 ✓
    """
    # ⚠ 2026-09-26 用户报「连点两次战斗 ⇒ 第二下点到状态图标/战斗回放」✗
    #   ⇒ 只重试"点了完全没反应"的情况 ✓；画面变了但没进战斗**绝不重点** ✗
    tries = 0
    for i in range(2):
        # ⭐ v0.31 方案 B：btn 坐标是**弹窗系**（PC 标定），真机上走 tapRefDialog 换算
        #   （PC/9:16 C=0 ⇒ 与 b.tap 完全等价）
        changed = b.tap_dlg(btn['cx'], btn['cy'], wait=1.2)
        tries += 1
        if changed is False and i == 0:
            log.append({'battle': 'tap_no_change_retry', 'try': i})
            continue                           # 点空了 ⇒ 允许再点一次 ✓
        # ⭐⭐⭐ 2026-10-04 第二轮提速：**模板抢跑窗口**（先只问模板，命中就两次 OCR 全省）
        #   实测依据：实机 8 图 9 场，结算面板**每次**都在 `k=1` 才出现
        #     ⇒ `k=0` 那次 OCR 每场都在白花；而模板一次 ~2ms ⇒ 让它先连续问一阵。
        #   ⚠ 窗口内没命中 ⇒ 下面原来的 2 次 OCR + 顶部复核**原封不动**跑（兜底一字没改）✓
        #   ⚠ `stop_requested()`：用户点 ■ 要立刻停（同 `wait_end` 的做法 ✓）
        _tf = time.time()
        _fk = 0
        _fast_hit = False
        while time.time() - _tf < _FAST_POLL_SECS:
            if stop_requested():
                log.append({'battle': 'fast_poll_stopped',
                            'waited': round(time.time() - _tf, 2)})
                return False
            b.snap('battle_wait')              # ⚠ 每轮都**重新取帧**（血泪史见 docstring）
            _fk += 1
            if battle_started_fast(b):
                _fast_hit = True
                break
            time.sleep(_FAST_POLL_GAP)
        if _fast_hit:
            log.append({'battle': 'started_fast', 'at': (btn['cx'], btn['cy']),
                        'try': i, 'tries': tries, 'k': _fk,
                        'waited': round(time.time() - _tf, 2), 'marks': list(marks),
                        'note': '模板抢跑窗口内确证结算面板 ⇒ 两次 OCR 全省 ✓'})
            return True
        log.append({'battle': 'fast_poll_miss', 'try': i, 'n': _fk,
                    'waited': round(time.time() - _tf, 2),
                    'note': '窗口内模板没命中 ⇒ 走原 OCR 判定（行为同改动前，只是多等这一窗口）'})
        for _k in range(2):                    # ⚡ 中段 OCR（快 3 倍）≈ 1s/次
            b.snap('battle_wait')              # ⭐⭐⭐ 必须**重新取帧**（见 docstring）
            # ⭐⭐⭐ 2026-10-04 S 级提速：先花 ~7~20ms 用模板问「结算面板在不在」
            #   命中 ⇒ **这一次 ~0.52s 的 OCR 彻底省掉** ✓
            #   没命中 ⇒ 原样走下面的 OCR（`battle_started`）⇒ 行为与改动前一致 ✓
            #   ⚠ 顺序不能反：模板便宜、OCR 贵，先问便宜的（同 `finish_map` 的做法）
            if battle_started_fast(b):
                log.append({'battle': 'started_fast', 'at': (btn['cx'], btn['cy']),
                            'try': i, 'tries': tries, 'k': _k, 'marks': list(marks),
                            'note': '模板快查确证结算面板 ⇒ 省一次 OCR ✓'})
                return True
            items = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(980)), tag='tap')
            if battle_started(items):
                log.append({'battle': 'started', 'at': (btn['cx'], btn['cy']),
                            'try': i, 'tries': tries, 'k': _k, 'marks': list(marks)})
                return True
            time.sleep(0.5)
        # ⭐ 判失败前的最后一次复核：重新取帧 + **只 OCR 顶部窄带（~0.6s）**
        #   唯一盲区是「战斗胜利」横幅 —— 实测在 y=123，落在上面那个 (130,980) 带**之外**；
        #   而「第N/M回合」在 y=230 ⇒ 窄带 (40,320) **两条都覆盖** ✓
        #   ⛔ **不用全屏 OCR**（那要 2.5s）：按 PC 端提速约定，能窄带就窄带 ✓
        try:
            b.snap('battle_check')
            # ⭐⭐⭐ 2026-10-04 S 级提速：同款图像短路 —— 结算面板已经在屏幕上就
            #   直接判成功，**连这次顶部窄带 OCR 也不必付** ✓
            #   （这条尤其治「战斗失败」也命中：②的 `close_tpl` 不看胜负 ✓）
            if battle_started_fast(b):
                log.append({'battle': 'started_late_fast', 'at': (btn['cx'], btn['cy']),
                            'try': i, 'tries': tries, 'marks': list(marks),
                            'note': '模板快查确证结算面板（窄带复核之前）⇒ 省一次 OCR ✓'})
                return True
            _top = b.ocr(band=(LAYOUT.sy(40), LAYOUT.sy(320)), tag='tap_top')
            if battle_started(_top):
                log.append({'battle': 'started_late', 'at': (btn['cx'], btn['cy']),
                            'try': i, 'tries': tries, 'marks': list(marks),
                            'note': '窗口内没认到，顶部窄带复核认到战斗/结算界面 ⇒ 算开打成功'})
                return True
        except Exception as _e:                # noqa: BLE001
            log.append({'battle': 'check_err', 'e': repr(_e)[:80]})
        log.append({'battle': 'no_battle_in_5s', 'try': i, 'tries': tries,
                    'note': '画面变了但没进战斗 ⇒ 不再重点 ✓'})
        break                                  # ⭐ 不重试 ✗（防点到别的 UI）
    log.append({'battle': 'not_started', 'at': (btn['cx'], btn['cy']), 'tries': tries})
    return False


# ⭐ 2026-10-02 摇色子的**定死间隔**（用户口径：「直接定死坐标和间隔点不就完事了」）
#   ⚠ 为什么必须用 `time.sleep` 而不是 `b.tap(wait=…)`：
#     极速截图下 `tap()` 里的 `wait_change()` 是**画面一变就返回**（≈0.3s），
#     根本不是"等这么久" ⇒ 那正是"点太快、下一步盖在动画上"的来源 ✗
#   想调节奏只改这两行。
DICE_DLG_WAIT = 1.8          # 点四叶草 → 等「是否重掷？」确认框出来
DICE_ROLL_WAIT = 3.0         # 点「确定」→ 等重掷动画放完 + 奖励行刷新完


def handle_dice(b, log, items, tries=3, st=None):
    """重投命运之骰（源码 `GameApi.Explore.DiceRerollAsync` + `ChangeClover(-1,"重投命运之骰")`）：
    **每次重投消耗 1 个幸运草**，服务端返回新的掉落；`rerollTime` = 已重投次数（上限 3）。
    按钮就在**战斗结算面板**上（不是另开界面），文本含「骰 / 重投 / 命运」。
    摇到出现「带大拇目标记的装备」就停（用户 09-25 口径）。

    ⭐⭐ v0.35 重大修正（20:9 实测铁证，推翻 v0.31 的归类）：
      **结算面板不是居中弹窗，是归一化（锚底）系！**
      证据：20:9（720x1600, C=+240）跑图日志 `{'battle':'closed','at':(577,1440)}` ——
      bottom_close 是从**归一化帧** OCR 量到的「关闭」y=1440，与 PC 标定 (577,1439)
      只差 1px；若结算面板真是居中弹窗，归一化帧上它应在 1439-240=1199 ✗。
      （对照组：战斗事件面板的「战斗」钮归一化帧 495 = PC 735 - C ⇒ 那个才是弹窗系 ✓）
      ⇒ 本函数**一切按归一化系**：条目不再 +C、点击走 b.tap、找标记用归一化帧。
      v0.31 的 +C + tap_dlg 会把搜索带 [820,1070] 变成归一化 [580,830] ⇒
      骰子按钮（归一化 ~979）根本不在带里 ⇒ 永远 no_btn / rolls=0 ✗（真机不能摇色子根因）
    """
    rolls = 0
    btn_pos = None
    items = list(items)      # ⭐ v0.35：结算面板 = 归一化系，绝不再 +C

    # ⭐⭐⭐⭐ 2026-10-05 **幸运草不够就别摇**（用户口径：「幸运草低于 8 就不摇色子吧」）
    #   真机铁证（`runs/acc3`，幸运草只剩 **1** 的那几张图）：
    #     点四叶草 ⇒ 游戏**不弹确认框** ⇒ 我那道"没弹框就不点确定"的闸门跳掉这一圈
    #     ⇒ 白点 2 次、`dice: no_dlg_skip` ⇒ 日志里只看到"确认框没弹出来"，
    #       而**真因（幸运草不足）被掩盖** ✗（用户看日志才发现是草不够）
    #   ⇒ 现在**一进函数就先看 HUD 的幸运草数**：< `CLOVER_MIN_REROLL(8)` ⇒
    #     **一次都不点，直接返回 0** ✓
    #   ⚠ 读不到（OCR 没认出来）⇒ **不猜、照常走**（保守：宁可试一次，也别因为
    #     一次 OCR 失败就永远不摇 ✓ —— 那种情况下面"没弹框就不点确定"那道闸门兜住）
    #   ⭐⭐⭐ 2026-10-05 追加用户口径：「**金币幸运草都是一张图只确认一次**」
    #     ⇒ 优先用**锁定的** `st['clover_locked']`（一图只确认一次 ✓）；
    #       调用方没传 `st` 时才回落到现场读一次（老行为，向后兼容 ✓）
    _cv_now = None
    if isinstance(st, dict) and st.get('clover_locked') is not None:
        _cv_now = int(st['clover_locked'])
    else:
        _cv_now = clover_count(items)
    if _cv_now is not None and _cv_now < CLOVER_MIN_REROLL:
        STATS['dice_skip_low'] = STATS.get('dice_skip_low', 0) + 1
        log.append({'dice': 'skip_low_clover', 'clover': _cv_now,
                    'min': CLOVER_MIN_REROLL,
                    'note': '幸运草 %d < %d ⇒ **这张图不摇色子**（用户口径）；'
                            '一次都不点，省掉白点 + 白等 ✓'
                            % (_cv_now, CLOVER_MIN_REROLL)})
        say('       · 幸运草只剩 %d（< %d）⇒ 这张图不摇色子 ✓' % (_cv_now, CLOVER_MIN_REROLL))
        status('幸运草不足 · 跳过摇色子')
        STATS['dice_got'] = STATS.get('dice_got', 0)
        return 0

    # ⭐⭐ 2026-09-29 真机实锤（用户目击 + dice_0.png + loop_log mark_routes 佐证）：
    #   结算面板奖励行**初始就可能已带大拇指装备**（推荐怪掉的就是追踪装备）——
    #   旧逻辑无脑先摇第 1 次再检测 ⇒ 把初始的大拇指装备重投掉 + 白耗 1 草
    #   （用户原话「摇出大拇指了还继续用幸运草摇」；现场：第 1 摇后 dice_0.png 无拇指、
    #   三路由全 null，第 2 摇才认出 0.904）。⇒ 抽 _mark_routes()，进循环前先查一次，
    #   初始就有 ⇒ 一次都不摇。
    import badge as badge_mod

    # ⭐⭐⭐ 2026-10-02「追踪装备」判据 —— **NCC 模板匹配**（终于对了）─────────
    #   背景（我在这一段绕了 6 轮弯路，全写下来免得后人重犯）：
    #     ① `badge.find_reward_mark` 模板匹配真机**恒返回空**（0.70 门槛过不去）
    #     ② 「右上角绿像素」被**绿底奖励卡**骗（四张全绿底时每张 111~387）
    #     ③ 「绿细边框 ≥3 边」绿底卡同样有（实测 3/4）
    #     ④ 「底色绿度 <15」红底 vs 紫底分不开
    #     ⑤ 「红底判据」紫/棕底也满足
    #     ⑥ 「棕色底上的绿」窗口总碰到邻卡
    #   ⭐ **破局点 = 用户告诉我这东西叫「追踪装备」**（2026-10-02）
    #     ⇒ 奖励行里那个绿箭头 = 地图上的 recommend 图标（同一个「追踪中」标记）
    #     ⇒ 于是**直接从真机截图裁出它当模板**做 NCC —— 项目里最成熟的手段 ✓
    #
    #   模板：templates/marks/thumb_tab.png（26×30，从 runs/thumb_real.png 的
    #        x330..356 / y574..604 裁出；用户确认那格就是追踪装备）
    #
    #   NCC 实测（窗口 = 奖励行 560~615，模板 26×30）：
    #       thumb_real.png  **+1.000**  ← 有追踪装备（用户确认）
    #       t_after_3.png   **+0.987**  ← 有追踪装备（用户确认）
    #       ar / vn / tf / notstarted / dice_now   +0.437 ~ +0.455
    #   ⇒ 阈值 **0.80** 干净分开，5 帧零误判 ✓
    def _thumb_by_ncc():
        """奖励行有没有追踪装备 → (bool, {ncc, x, y})"""
        try:
            _im = b.img()
            if _im is None:
                return False, {}
            _p = os.path.join(_MGAS_ROOT, 'templates', 'marks', 'thumb_tab.png')
            _t = cv2.imdecode(np.fromfile(_p, np.uint8), cv2.IMREAD_COLOR)
            if _t is None:
                return False, {}
            _cy = _FX.A('reward_slot_1')[1]
            _y0 = max(0, int(_cy - 55))
            _y1 = min(_im.shape[0], _y0 + 55)
            _band = _im[_y0:_y1, :]
            if _band.shape[0] < _t.shape[0] or _band.shape[1] < _t.shape[1]:
                return False, {}
            _res = cv2.matchTemplate(cv2.cvtColor(_band, cv2.COLOR_BGR2GRAY),
                                     cv2.cvtColor(_t, cv2.COLOR_BGR2GRAY),
                                     cv2.TM_CCOEFF_NORMED)
            _mn, _mx, _, _mloc = cv2.minMaxLoc(_res)
            return _mx >= 0.80, {'ncc': round(_mx, 3), 'x': int(_mloc[0]),
                                 'y': int(_mloc[1] + _y0)}
        except Exception:                     # noqa: BLE001
            return False, []


    def _mark_routes():
        # ⭐⭐ v0.37：真机（C>0）上**归一化帧是非等比压缩**（横 ×0.844 / 纵 ×0.7195）
        #   ⇒ 大拇指图标被压扁 ~15% ⇒ ref 路由匹配分数掉到 0.43 ✗
        #   而**弹窗帧是等比 ×0.8437** ⇒ 图标 148×148 完好、scale 仍 4.4 ✓ ⇒ 必须用弹窗帧。
        #   但弹窗帧里元素坐标 = 归一化 + C ⇒ 检测框要跟着对位：
        #     · 结算面板若是 B 类（归一化系，实测「关闭」1440≈PC 1439）⇒ box **+C**
        #     · 若是 A 类（弹窗系）⇒ box 不变
        #   ⇒ 两路弹窗 + 一路归一化，取**分数最高**的那个（阈值 0.70 兜底防噪声）✓
        #
        # ⚠⚠ v1.19（2026-10-01 1264×2780 真帧）：box **不能写死绝对 y**。
        #   真机实测（设备帧 OCR，转回参考系）：
        #     奖励行数字 636~752 ｜ 回放战斗 1224 ｜ **关闭 1441** ｜ 自动跳过 1563
        #   PC 9:16 同位置是 907/994 ｜ 1223 ｜ 1440 ｜ 1563
        #   ⇒ 面板**底部三键两机完全一致**（锚定模型对 ✓），但**奖励行在真机上高 271px**
        #   （战斗 UI 纵向压缩）⇒ 旧 box (40,840+C,1020,1140+C) 在真机完全盖不到奖励行
        #   ⇒ 三路全 None、图标掉到 0.40「近失」，文字通道更绝（见 _reward_band 注释）。
        #   ⇒ 改成**锚定「关闭」**：奖励行 = 关闭上方 (600~1300)，任何分辨率都成立 ✓
        _c = int(round(dlg_c()))
        _routes = []
        _dimg = None
        if hasattr(b, 'img_dlg'):
            try:
                _dimg = b.img_dlg()
            except Exception:       # noqa: BLE001
                _dimg = None
        if _dimg is not None and _c:
            _routes.append(('dlg+C', badge_mod.find_reward_mark(
                _dimg, box=_reward_box(items, _c))))
            _routes.append(('dlg', badge_mod.find_reward_mark(_dimg, box=_reward_box(items))))
        _routes.append(('ref', badge_mod.find_reward_mark(b.img(), box=_reward_box(items))))
        _best = None
        for _t, _h in _routes:
            if _h and (not _best or _h[0][0] > _best[0][0]):
                _best = _h
        # ⭐ 三路由全空时必须返回 [] 而不是 None——调用方 `hits[:4]` 会
        #   TypeError（2026-09-29 模拟器 23:28 两场实锤：i=0 全空 → match_err → 近失诊断被吞）
        return _routes, _dimg, _c, (_best or [])

    def _detect(tag, i, retry=2):
        """⭐ 2026-09-29 深夜：带重试的三路由检测。
        模拟器 23:44 实锤（v0.40）：第 1 摇奖励行明明有大拇指（近失 0.45@(614,936)，
        下一摇同位置 0.943），但检测帧上拇指被「确认弹窗遮罩 / 奖励行动画」拉到
        0.45 < 0.70 ⇒ 单帧检测漏判。⇒ 首检失败等 1.5s 重试一次；仍失败输出近失候选。"""
        routes, dimg, c, hits = [], None, 0, []
        for k in range(retry):
            routes, dimg, c, hits = _mark_routes()
            log.append({'dice': tag, 'k': k, 'i': i, 'C': c,
                        'best': {t: (round(h[0][0], 3) if h else None)
                                 for t, h in routes}})
            if hits:
                return routes, dimg, c, hits
            if k < retry - 1:
                _near = []
                if dimg is not None and c:
                    _near += badge_mod.find_reward_mark(
                        dimg, box=_reward_box(items, c),
                        shape_min=0.0, color_min=0.0, top=2)
                _near += badge_mod.find_reward_mark(b.img(), box=_reward_box(items),
                                                    shape_min=0.0,
                                                    color_min=0.0, top=2)
                log.append({'dice': tag + '_near', 'k': k,
                            'top': [('近失', round(x[0], 3), round(x[1], 3),
                                     x[2], x[3], x[4]) for x in _near]})
                time.sleep(1.5)      # 等遮罩/动画结束再检一次（wait_stable 对静止遮罩会立即通过）
        return routes, dimg, c, hits

    def _hit(hits, i, rolls):
        if not hits:
            return False
        STATS['dice_got'] += 1
        say('       · 摇到大拇指装备，停止重摇（第 %d 次）' % rolls)
        status('摇骰子 · 拿到大拇指装备 ★')
        log.append({'dice': 'got_recommend', 'i': i,
                    'at': (hits[0][2], hits[0][3]), 'shape': round(hits[0][0], 3),
                    'color': round(hits[0][1], 3)})
        return True

    def _has_thumb(tag):
        """追踪装备判据（NCC 模板），命中即停摇 ✓"""
        _ok, _dbg = _thumb_by_ncc()
        if _ok:
            log.append({'dice': tag + '_thumb_ncc', 'ncc': _dbg})
        return _ok

    try:
        # ⭐⭐ 主判据：奖励行**初始**就查一次（别把已有的追踪装备重投掉）
        if _has_thumb('initial'):
            STATS['dice_got'] += 1
            say('       · 奖励行初始已带追踪装备，不重投 ✓')
            status('追踪装备 · 初始就带 ★')
            log.append({'dice': 'initial_recommend', 'how': 'ncc_tab'})
            return 0
        _r0, _d0, _c0, _h0 = _detect('initial_check', -1)
        if _h0:
            STATS['dice_got'] += 1
            say('       · 奖励行初始已带大拇指装备，不重投 ✓')
            log.append({'dice': 'initial_recommend', 'at': (_h0[0][2], _h0[0][3]),
                        'shape': round(_h0[0][0], 3), 'color': round(_h0[0][1], 3)})
            log.append({'dice': 'done', 'rolls': 0})
            return 0
    except Exception as e:      # noqa: BLE001
        log.append({'dice': 'initial_check_err', 'e': repr(e)})
    # ⭐⭐⭐ 2026-10-01 机制纠错（用户指正，推翻 v0.53）：**点骰子按钮只是触发
    #   「是否重掷？」确认框，点「确定」才真正摇**（扣幸运草、刷新奖励行）。
    #   v0.53 把确认框全点「取消」= 一次都没摇成 ⇒ 奖励行永远是初始掉落 ⇒
    #   「一直取消弹窗、永远没有大拇指」（用户 10-01 实锤）。
    #   ⇒ 正确流程：点骰子（触发确认框）→ **点确定执行摇** → 摇完的干净帧上检测
    #     （retry=2）→ 有拇指停；没有 → 再点骰子 → 再确定… 最多 tries 次 ✓
    # ⭐⭐⭐ 2026-10-02 用户定调（第二次简化：**把判断也删掉**）
    #   「**为什么要判定确认框在不在？直接定死坐标和间隔点不就完事了**」
    #   旧实现用「确认框标题区亮度 > 60」判框在不在 —— 真机（20:55 那把）量到 **44.1**
    #   ⇒ 判"没弹" ⇒ 它又去点了一次四叶草 (40,645)，而那一下正好点在弹窗**外面**
    #     ⇒ 等于把弹窗**取消**了 ✗（用户看到的「连点 2 次摇色子后弹出的弹窗被自动关了，
    #       然后就关闭了战斗」）；更糟：那一圈的 `else` 与圈尾**各点一次**四叶草
    #     ⇒ 一次误判 = 两次误点 ✗✗
    #   真机铁证 `runs/loop/loop_log.json`（20:55）：
    #       no_confirm_popup(streak 1, luma 44.1) → panel(40,645) →
    #       no_confirm_popup(streak 2, luma 44.1) → abort_no_confirm → done(rolls 0)
    #   ⇒ 现在**零判断**：每圈 = 点四叶草 → 定死等 → 点确定 → 定死等 →
    #     只看奖励行有没有大拇指（那一条 0.05s 图像判据是用户点名要保留的 ✓）
    #   ⚠ 间隔用 `time.sleep`（**定死**），不是 `tap(wait=…)` —— 极速截图下后者是
    #     "画面一变就返回"（≈0.3s），那正是"点太快"的来源 ✗
    for _k in range(int(tries)):
        _btn = _FX.A('dice_reroll')            # 奖励行左下角·四叶草 + 数字
        b.tap(_btn[0], _btn[1], wait=0.6)      # ① 点它 ⇒ 触发「是否重掷？」确认框
        time.sleep(DICE_DLG_WAIT)             # ② 定死等框出来（不判断）
        # ⛔⛔⛔ 2026-10-05 **点「确定」之前必须确认框真的弹出来了**
        #   （用户报「**还有摇完大拇指后有个点中间的盲点**」）
        #   真机坐标核对（`FX.A` + `cell_of`，硬事实）：
        #       `dice_reroll` = (40, 645)  ⇒ **棋盘外** ✓ 安全
        #       `dice_yes`    = **(520, 742)** ⇒ 落在格 **(1,6)**  ⚠⚠ **棋盘内**
        #       `dice_no`     = **(300, 742)** ⇒ 落在格 **(1,3)**  ⚠⚠ **棋盘内**
        #   ⇒ 原来 ③ 是**无条件点 (520,742)**；而点四叶草**没弹框**时（幸运草不够 /
        #     面板已变 / 点空）这一下就落在**棋盘 (1,6)** 上 ⇒ 白点 + 可能连锁消耗 ✗
        #     ⚠ 本函数上方注释自己就记着这个前科：「它又去点了一次四叶草 (40,645)，
        #       而那一下正好点在弹窗**外面** ⇒ 等于把弹窗**取消**了」
        #       —— 那次是"点外面=取消弹窗"，这次是"点里面=点棋盘"，同一类 ✗
        #   ⇒ 判据用**棋盘压暗**（`dim`）：模态确认框弹出时棋盘被遮罩压暗 ⇒ **零成本**
        #     （用户口径「这种不应该都是固定坐标点击吗」⇒ 用免费判据，不付 OCR ✓）
        #   ⚠ 方向安全：**没判定出框就不点确定**（这一圈白跑，但**绝不误点棋盘** ✓）
        _dlg_dim = 1.0
        try:
            _dlg_dim = float((getattr(b, 'last_change', None) or {}).get('dim', 1.0))
        except Exception:       # noqa: BLE001
            _dlg_dim = 1.0
        if _dlg_dim >= 0.85:
            log.append({'dice': 'no_dlg_skip', 'rolls': rolls, 'dim': round(_dlg_dim, 3),
                        'at': 'dice_yes', 'skipped_at': list(_FX.A('dice_yes')),
                        'note': '确认框没弹出来（棋盘没被压暗）⇒ **不点 (520,742)**'
                                '（那坐标落在棋盘格 (1,6) ✗）；这一圈作废 ✓'})
            say('       · 确认框没弹出来 ⇒ 不点「确定」（避开棋盘格 (1,6) ✗）')
            break
        _yp = _FX.A('dice_yes')
        b.tap(_yp[0], _yp[1], wait=0.6)        # ③ 点「确定」= 真正摇（扣 1 个幸运草）
        time.sleep(DICE_ROLL_WAIT)            # ④ 定死等重掷动画 + 奖励行刷新完
        rolls += 1
        log.append({'dice': 'reroll', 'at': tuple(_yp), 'rolls': rolls,
                    'waits': [DICE_DLG_WAIT, DICE_ROLL_WAIT],
                    'note': '全固定坐标 + 定死间隔（不判确认框、零 OCR）'})
        # ⚠ 看奖励行前**必须重新抓一帧**（0.02s，不是 OCR）：`tap()` 内部的
        #   `wait_change()` 是"一变就返回" ⇒ 缓存帧停在**动画中途** ⇒ 直接判会看不到
        #   大拇指（这个坑 `wait_stable` 的 docstring 里记着：用户报过「明明出了还继续摇」）
        try:
            b.snap('dice_after%d' % rolls)
        except Exception:                     # noqa: BLE001
            pass
        # ⑤ 唯一需要判断的：奖励行有没有大拇指装备（0.05s 图像判据，用户点名保留 ✓）
        if _has_thumb('roll%d' % rolls):
            STATS['dice_got'] += 1
            say('       · 摇到追踪装备，停止重摇（第 %d 次）' % rolls)
            status('摇骰子 · 拿到大拇指装备 ★')
            log.append({'dice': 'got_recommend', 'how': 'ncc_tab', 'rolls': rolls})
            break
        log.append({'dice': 'after', 'rolls': rolls, 'thumb': False})
    # 收尾兜底：万一最后一次「确定」没点掉（框还挂着）⇒ 点「取消」收干净 ✓
    # ⛔⛔⛔ 2026-10-05 **撤回这个"无条件点取消"**（用户报「**还有摇完大拇指后有个点中间的盲点**」）
    #   真机坐标核对（`FX.A` + `cell_of`，**这是硬事实不是猜**）：
    #       `dice_reroll` = (40, 645)  ⇒ **棋盘外**（左上角 ✓ 安全）
    #       `dice_yes`    = (520, 742) ⇒ 落在格 **(1,6)**  ⚠ 棋盘内
    #       `dice_no`     = **(300, 742)** ⇒ 落在格 **(1,3)** ⚠⚠ **就是用户说的"点中间"**
    #   ⇒ 原来这段**无任何判据**地每次点 (300,742) —— 那是**棋盘第 1 行的中间**！
    #     而"取消框不在"时这一下就落在**棋盘格**上：
    #       · 轻则空点一下（正是用户看到的"点中间的盲点"）
    #       · 重则该格被连锁消耗/弹面板 ⇒ 后面计划全错位 ✗
    #   ⚠ 原作者当时写的注释是「框不在时这一下落在**面板空白处**」—— **这个假设是错的**
    #     （742 在棋盘 y 范围内；只有 y>1000 那一带才是面板外/棋盘下部）✗
    #   ⇒ 现在：**只有确认框真的还在**才点取消 —— 判据用**棋盘压暗**（`dim`，**零成本** ✓）
    #     · 确认框是**模态**的（弹出来时棋盘被遮罩压暗，`dim` 明显 <1）
    #     · 不需要 OCR（用户口径：「这种不应该都是固定坐标点击吗」⇒ 尽量走免费判据 ✓）
    #     ⚠ 方向安全：**"没判定出框"就不点**（多留一个框给下一轮处理，无害 ✓）；
    #       反过来"框不在还点"才会点到棋盘格 ✗
    try:
        _tail_dim = 1.0
        try:
            _tail_dim = float((getattr(b, 'last_change', None) or {}).get('dim', 1.0))
        except Exception:       # noqa: BLE001
            _tail_dim = 1.0
        if _tail_dim < 0.85:
            _no_p = _FX.A('dice_no')
            b.tap(_no_p[0], _no_p[1], wait=0.6)
            log.append({'dice': 'tail_cancel', 'at': tuple(_no_p),
                        'dim': round(_tail_dim, 3),
                        'note': '棋盘被压暗 ⇒ 确认框还在 ⇒ 才点取消 ✓'})
        else:
            log.append({'dice': 'tail_skip', 'dim': round(_tail_dim, 3),
                        'note': '确认框不在（棋盘没被压暗）⇒ **不点 (300,742)**'
                                '（那坐标落在棋盘格 (1,3)，盲点就是"点中间的盲点" ✗）'})
    except Exception as _te:                    # noqa: BLE001
        log.append({'dice': 'tail_err', 'e': repr(_te)[:60]})
    log.append({'dice': 'done', 'rolls': rolls})
    return rolls


def wait_end(b, log, timeout=45, marks=(), exact_marks=None, st=None):
    """等战斗结算。⚠ 用户 09-25：战斗胜利不会超过 5s —— 超过很久还没结算就是没打起来，
    别死等（原来 180s，白耗时间）。

    ⚡ 2026-09-25 二次提速（OCR 是最大头，实测全屏 1.4s / 条带 1.0s 一次）：
    - 战斗过程一直在动 ⇒ 极速截图轮询（0.06s/张）几乎免费，**不做 OCR**
    - 画面**连续 ~1 秒完全不动**才算「该看一眼了」（`need=15` ≈ 0.9s@0.06）
      ⚠ 一开始设成 3 帧就被战斗动画的**每次停顿**触发 → 一场战斗 OCR 十几次（实测 22 次/35s）
    - 再叠加**最小间隔 3 秒**，最多 8 秒兜底一次 ⇒ 一场战斗通常只 OCR 2~4 次
    """
    say('       · 战斗中…')
    # ⭐ v1.08 用户口径：战斗期间悬浮条也要写清"在打什么格子"（多种标记全写 ✓）
    status('战斗中 · %s' % tile_phrase(marks))
    t0 = time.time()
    time.sleep(1.2)          # ⭐ 2.0→1.2：进场黑幕后的首次判定，早点看一眼
    diced = False
    result_streak = 0        # ⭐ 结算面板连续命中次数（防单帧误判触发摇色子）
    back = 0
    last_ocr = 0.0
    # ⭐ 用户 2026-09-25：「不是每个战斗都要等待，只有有大拇指的要等待」
    #   - 带 recommend 标记：要**细等**（等奖励行稳定，才判断得出有没有大拇指）→ wait_stable
    #   - 普通战斗：不追稳定，每 ~2.5 秒看一眼就够（结算面板一出现就关掉走人）
    # ⭐ 2026-09-27：只认**本格**标记（exact_marks ✓ 没传才退回 marks ✓）
    _ex = list(exact_marks) if exact_marks is not None else list(marks or [])
    if _ex != list(marks or []):
        log.append({'wait_end': 'exact_only', 'marks': list(marks or []), 'exact': _ex})
    need_dice = 'recommend' in _ex
    while time.time() - t0 < timeout:
        # ⭐⭐ 2026-10-01 用户报「点 ■ 后还要运行一会」⇒ 真机实测最长白等 **11.37 秒**，
        #   其中一大部分就是卡在战斗等待里（这个循环原本收到停止还会 continue 继续等 ✗）
        #   ⇒ 循环顶部查一次：收到停止就**立刻退出**（`wait_stable` 也可中断 ✓，
        #     两者合起来把延迟压到一次轮询 ≈ 0.06~0.1 秒 ✓）
        if stop_requested():
            log.append({'wait_end': 'stopped_by_user', 'elapsed': round(time.time() - t0, 1)})
            return False
        elapsed = time.time() - t0
        need_ocr = False
        if b.fast_ok:
            if need_dice:
                # ⭐ 用户 2026-09-25：「大拇指战斗等待不要那么长」
                #   原来是 8 秒上限 + 0.9 秒稳定判定（一场战斗能磨十几秒）⇒ 收紧到
                #   3 秒上限 + 0.5 秒稳定（need=8@0.06s），最小间隔 3s→1.5s
                stable = b.wait_stable(3.0, interval=0.06, thr=1.4, need=8, band=(LAYOUT.sy(87), LAYOUT.sy(1133)))
                need_ocr = bool(stable) or (elapsed - last_ocr >= 5.0)
                if need_ocr and (elapsed - last_ocr) < 1.5:
                    need_ocr = False
            else:
                # ⚠ 2026-09-25 用户报「普通战斗突然开始摇色子了」⇒ 门槛不能太低：
                #   降到 0.24 秒后**战斗中途的画面也被 OCR**，被误判成"结算面板"⇒ 误触发摇色子。
                # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**固定 0.5 吧**」
                #   ⇒ 普通战斗改成**固定 0.5s 间隔**轮询 ✓（不再等 `wait_stable`）
                #   安全性：现在每次轮询只 OCR **165px 的按钮窄条**（~0.12s ✓），
                #     而且只认「关闭/确定」这颗**只有结算面板才有**的按钮
                #     ⇒ 战斗动画中途的帧不会误命中 ✓（上面那个"误触发摇色子"的事故不会复活 ✓）
                #   收益：结算面板出现后**最多 0.5s** 就发现（原来最坏 1.5~2s）
                #     ⇒ 每场快 0.5~1s × ~2.8 场/图 ≈ **1.5~2.8s/图** ✓
                time.sleep(0.5)
                need_ocr = True
        else:
            time.sleep(1.5)
            need_ocr = True
        if not need_ocr:
            continue
        last_ocr = elapsed
        _OCR_CH['dlg'] = False      # ⭐ 战斗界面是**全屏**界面（不是居中弹窗）⇒ 一切回归一化系
        b.snap('battle_wait')
        # ⭐⭐⭐ 2026-10-03 用户口径「**加入**」⇒ 结算面板改用**模板快查**（不再付条带 OCR）
        #   素材：`runs/cap_close/` 攒到 82 张真机结算整帧（扫描 1600 张历史帧得来 ✓）
        #     ⇒ 自动聚成 3 档、每档一个模板：`templates/fixed/close_tpl_{0,1,2}.png`
        #   实测可分：**正样本最低 0.986** ｜ **负样本（地图首帧 12 张）最高 0.524**
        #     ⇒ 阈值 0.80 稳 ✓（原来单模板泛化失败：来源帧 1.000 但 acc2 只有 0.465 ✗）
        #   收益：0.5s 一轮的扫描从 165px 条带 OCR（~0.12s）降到 3 次模板匹配（~7~20ms ✓）
        #   搜索区用既有的 `BANDS['settle']`（y 780~1080 = 结算面板底部三键那一带 ✓）
        # ⭐⭐⭐ 2026-10-04 修（**与 d7f13c2 同一个根因**，那次修的是"领取"那条路）：
        #   `fx_has()` 的 `band` 参数收的是 **`fixed.BANDS` 的字符串键**（'nav'/'settle'…），
        #   它内部做 `box = _FX.BANDS.get(band)` —— 传**元组**必然 `.get()` 到 None
        #   ⇒ **静默退化成全屏搜索**：结果照样对（模板还在图上），但白花好几倍时间，
        #     而且**不报错**（最难发现的那种）。本行原来传的正是元组 ✗，
        #     而**上面这行注释写的就是"用 BANDS['settle']"** ⇒ 意图与实现不符，属笔误。
        #   ⇒ 改成字符串键；`BANDS['settle'] == (0, 780, 720, 1080)` 与本行想传的框**逐值相同** ✓
        #     收益：3 连查从「全屏」降到「720×300 条带」≈ 快一个数量级（`wait_end` 每 0.5s 就查一轮）
        _hit_tpl = False
        try:
            for _tp in ('close_tpl_0', 'close_tpl_1', 'close_tpl_2'):
                if fx_has(b, _tp, band='settle'):
                    _hit_tpl = True
                    break
        except Exception:                   # noqa: BLE001
            _hit_tpl = False
        if _hit_tpl:
            items = b.ocr(band=(LAYOUT.sy(87), LAYOUT.sy(1040)), tag='battle')
            # ⭐ 顺手续攒样本（用户：「多攒一些关闭吧」）✓
            _cap_close(b.img(), log, why='battle')
        else:
            # 模板没命中 ⇒ 结算面板还没出来 ⇒ 这一轮**不必 OCR** ✓
            items = []
        win = fb(items, L['win'])
        # ⚠ 摇色子触发必须限定在**真结算面板**上：地图顶部「首领战斗胜利」横幅也含
        #   「战斗胜利」，只看它会在地图界面误触发
        on_result = bool(fb(items, *L['desc'])) or bool(bottom_close(items))
        # ⭐⭐ 摇色子判定（2026-09-25 用户：「判断摇不摇色子直接看这个地块有没有对应标记」✓）
        #   marks 就是**这一格的标记**（由点它的那一下 + 本回合标记扫描得出）。
        #   ⚠ 踩过的坑：为了防"普通战斗误摇"加了「连续两帧确认」，但**首帧判成结算面板后
        #   立刻又走了下面的关面板分支** ⇒ 面板被关掉、永远等不到第 2 帧 ⇒ 真·大拇指战斗
        #   反而不摇色子（用户本次报的 bug）。正确做法：大拇指战斗在首帧**先别关**，
        #   隔 0.6 秒复核一次；复核仍是结算面板就去摇色子，否则照常关掉 ✓
        if win and on_result:
            result_streak += 1
        else:
            result_streak = 0
        if not diced and 'recommend' in list(marks):
            if result_streak < 2:
                time.sleep(0.6)                     # 复核一帧（不关面板，等它稳定）
                b.snap('battle_wait2')
                it3 = b.ocr(band=(LAYOUT.sy(87), LAYOUT.sy(1040)), tag='battle')
                if fb(it3, L['win']) and (bool(fb(it3, *L['desc'])) or bool(bottom_close(it3))):
                    result_streak += 1
                    items = it3
                else:
                    result_streak = 0
            if result_streak >= 2:
                diced = True
                # ⛔⛔⛔ 2026-10-06 **修 `NameError`**（真机 acc2 一把崩 9 次，摇色子全灭）：
                #   这里原来写的是 `st=(ctx or {}).get('flags')` —— 可 **`ctx` 根本不是
                #   本函数的参数**（`wait_end(b, log, timeout, marks, exact_marks)`），
                #   它只存在于 `popups(b, items, log, ctx=None)` 里 ⇒ 每次走到这一句都抛
                #   `NameError: name 'ctx' is not defined`。
                #   真机铁证（`runs/acc2/loop/loop_log.json`，9 条）：
                #     {"round": 1, "error": "NameError(\"name 'ctx' is not defined\")",
                #      "trace": ["    handle_dice(b, log, items, st=(ctx or {}).get('flags'))", …]}
                #   ⇒ **9 场「首领+大拇指 / 大拇指」战斗，一次都没摇成色子** ✗✗
                #     （`STATS['recommend_fights'] == 0`、`dice_got == 0`、`dice` 条目 0 条）
                #   ⚠ 为什么以前没暴露：这条 `handle_dice` 只在**真结算面板**且
                #     `result_streak >= 2` 时才走到；而更常见的路径是 `popups()` 的
                #     `_res` 分支（那个 `ctx` 是对的 ⇒ 不崩）⇒ 只在"wait_end 里直接
                #     确认结算面板"这条路上崩，平时被 `popups` 那条路盖住了 ✓
                #   ⚠⚠ 与 v1.63/v1.64/v1.71 **同一族**：判据/调用建在**拿不到数据**的地方
                #     （那边是 band 裁掉了 HUD，这边是**名字根本不存在**）✗
                #   ⇒ 修法：给 `wait_end` **正式加 `st=None` 参数**（不再引用野名字），
                #     两个调用点都把 `ctx.get('flags')`（就是 `st`）传进来 ✓
                handle_dice(b, log, items, st=st)
                items = b.ocr(band=(LAYOUT.sy(87), LAYOUT.sy(1040)), tag='battle')
        # ⭐ 2026-09-28 提速（P5）：真结算面板上把「自动跳过」勾上（只一次，已勾不点），
        #   之后的战斗跳过动画直接进结算 —— 战斗动画是单图最大动画开销 ✓
        if win and on_result and not _AUTO_SKIP['done']:
            _auto_skip_enable(b, log)
        cl = bottom_close(items)
        # ⭐⭐⭐ 2026-10-02 修「统计全是 0」：**统计挂在「战斗真的结束」这个出口上**，
        #   而不是挂在「找到关闭按钮」这一条路径里。
        #   原写法：计数写在 `if cl:` 分支内 ⇒ 只有 `bottom_close`（OCR 认到
        #   「关闭/确定」字样）那条路才计数；而 2026-10-02 好几局结算面板走的是
        #   `panel_close: battle_close_fixed`（认不到文字 ⇒ 写死 `REF['bottom_close']`
        #   点掉）⇒ **那一条完全不计数** ⇒ 连打 8 局，统计仍是
        #   「首领关 0 场 / 全部战斗 0 场 / 大拇指装备 0 件」✗✗
        #   ⇒ 现在：在**两个分支合流之后**、函数 `return True`（战斗结束）之前统一记一次 ✓
        _counted = [False]

        def _count_once(win_flag):
            """战斗结束只记一次（防止两条关闭路径重复累加）"""
            if _counted[0]:
                return
            _counted[0] = True
            STATS['battles'] += 1
            STATS['battle_wins'] += 1 if win_flag else 0
            # ⭐⭐ 2026-09-27 修（用户报「7 张图却报 9 个首领关」）：
            #   `marks` 里含 **±1 邻域**的标记（紧挨目标的拦路格也算 ✓ 那是"该不该打"的判据 ✓）
            #   ⇒ 但**统计**只能算"本格真有该标记"的 ✓（7 张图 ⇒ 正好 7 个首领关 ✓）
            if 'boss' in _ex:
                STATS['boss_fights'] += 1
                STATS['boss_wins'] += 1 if win_flag else 0
            if 'recommend' in _ex:
                STATS['recommend_fights'] += 1
                STATS['recommend_wins'] += 1 if win_flag else 0
            if _ex != (list(marks or [])):
                log.append({'stat': 'exact_marks', 'near': list(marks or []),
                            'exact': _ex})

        if cl:
            time.sleep(0.4)                 # ⭐ 0.8→0.4：结算面板不会自己消失，少等一半
            items = b.ocr(band=(LAYOUT.sy(87), LAYOUT.sy(1040)), tag='battle')
            cl = bottom_close(items)
            if cl:
                _tap(b, cl['cx'], cl['cy'], wait=1.6)
                win = bool(fb(items, L['win']))
                log.append({'battle': 'closed', 'at': (cl['cx'], cl['cy']), 'win': win})
                mk = list(marks or [])
                _count_once(win)
                say('       · 战斗结算已关闭（%s）' % ('胜利' if win else '未确认胜利'))
                # ⭐ v1.08：结算也带上"打的是什么格子"（用户口径：战斗日志要写清格子 ✓）
                status('%s ✓ · %s' % ('战斗胜利' if win else '战斗结束',
                                      tile_phrase(_ex or marks)))
                # ⭐⭐⭐ 2026-10-05 用户口径：「摇色子结束，关闭战斗胜利界面后需要一个
                #   获得新装备检测」⇒ **就在这个出口**（结算面板刚关掉）补一次 ✓
                check_newequip_after_battle(b, log, 'battle')
                return True
        el = time.time() - t0
        centered = any(i['text'] in (L['win'], L['lose']) and LAYOUT.sx(133) < i['cx'] < LAYOUT.sx(600) for i in items)
        # ⭐⭐⭐ 2026-10-02：认不到「关闭」文字时走的是 `battle_close_fixed`（写死 REF 点）
        #   ⇒ 那条路以前**完全不计数**（统计常年 0）。这里在**同一个出口**补上，
        #     两条关闭路径共用 `_count_once()` ⇒ 不会重复累加 ✓
        if not _counted[0] and centered:
            # 画面中央有「战斗胜利/失败」字样 ⇒ 这场仗确实打完了（只是没找到关闭按钮）
            _win_here = bool(fb(items, L['win']))
            log.append({'battle': 'closed_fixed', 'win': _win_here,
                        'note': '认不到关闭按钮 ⇒ 走写死坐标兜底，统计同样计入'})
            _count_once(_win_here)
        if el > 15 and exb(items, L['end']) and cl is None and not centered:
            back += 1
            if back >= 2:
                log.append({'battle': 'back_in_map', 'secs': int(el)})
                return True
        else:
            back = 0
        time.sleep(0.4)
    log.append({'battle': 'timeout'})
    return False


_AUTO_SKIP = {'done': False}
_AUTO_SKIP_BOX = (310, 1039)    # 结算面板「自动跳过」勾选框中心（1080x1920 实测截图标定 ✓）
# ⚠ 坐标教训：从聊天里「显示尺寸」估的坐标 (258,879) 是错的 —— 截图实际 1080x1920，
#   显示缩放 ~1.77 倍，第一版采样到了奖励图标上（bright=0.281 是紫色图标的值）。
#   判据用**框内均值亮度**：已勾选(亮黄) 实测 mean≈197；>140 按已勾；
#   <100 按未勾（去点一下）；100~140 拿不准 ⇒ 不点只记日志（防误 toggle ✗）


def _auto_skip_enable(b, log):
    """结算面板上的「自动跳过」勾选框：勾上后**之后的战斗跳过动画直接进结算**（P5）

    勾选状态游戏内持久 ⇒ 只处理一次（`_AUTO_SKIP['done']`）：
    已勾就不点——**绝不能盲点**（会把已勾的又点掉 ✗）。
    """
    _AUTO_SKIP['done'] = True
    try:
        arr = b.img()
        if arr is None:
            return
        x, y = int(LAYOUT.sx(_AUTO_SKIP_BOX[0])), int(LAYOUT.sy(_AUTO_SKIP_BOX[1]))
        k = max(4, int(round(10 * LAYOUT.k)))         # 内框半径（参考分辨率下 10px）
        box = arr[max(0, y - k):y + k, max(0, x - k):x + k]
        if box.size == 0:
            return
        mean_luma = float(box.mean())
        log.append({'auto_skip': 'probe', 'mean': round(mean_luma, 1)})
        if mean_luma > 140:
            say('       · 自动跳过已勾选 ✓')
            return
        if mean_luma >= 100:
            say('       · ⚠ 自动跳过勾选状态拿不准（mean=%.0f），本次不动（已记日志）'
                % mean_luma)
            return
        b.tap(x, y, wait=0.8)
        log.append({'auto_skip': 'tapped', 'at': (x, y), 'mean': round(mean_luma, 1)})
        say('       · 勾选「自动跳过」（后续战斗跳过动画，提速 ✓）')
    except Exception as e:      # noqa: BLE001
        log.append({'auto_skip': 'error', 'e': repr(e)[:100]})


# ⭐⭐ v0.31 方案 B（2026-09-30）：居中弹窗空间 ──────────────────────────────
# 真机实锤（1280×2772）：boss「战斗」钮归一化帧 y=582，PC 同一按钮 y=791
#   ⇒ 游戏**弹窗**锚定**设备屏幕中心**，不守棋盘的「顶块锚顶+其余锚底」模型。
# 弹窗系 = PC 参考系（PC 无缩放 ⇒ PC 标定的面板常数 FIGHT_Y / y 带 650~860 / X(493,225) 原样可用）；
# 归一化帧里弹窗内容 y = 弹窗系 y − C（纯平移，C = 960 + (shift − H/2)/kx；
# 真机 1280×2772 ⇒ 209、1080×2400 ⇒ 240、PC / 9:16 ⇒ 0）。
# 使用纪律：
#   · 面板按钮的 **y 带筛选** → 用 dlg_items()（+C）后的条目 ✓
#   · 面板**固定标定点**（FIGHT_Y=490 / 探索(183,491) / X(329,150) / 返回(359,808)）
#     → b.tap_dlg() ✓  ⚠ 全部是 720 设备系，别再抄 1080p 的数
#   · OCR **找到的**按钮按归一化坐标 b.tap() 本来就准（两套映射斜率相同），不必改 ✓
#   · 棋盘 / 底部导航 / 万能位 (541,1890) **不是弹窗系**，绝不换算 ✗
#   · dlg≈202~509 的内容（面板 X 关闭符）在真机落在 toRef 丢弃的弹性区 ⇒ 归一化帧**看不见**，
#     要看它必须走弹窗帧（端上 b.img_dlg()，Java grabDlgPng 重投影）
# ⭐⭐ v0.35 重大修正（20:9 实测，720x1600 C=+240 跑图铁证）——**面板分两类，不能一刀切**：
#   · A 类「居中弹窗」：战斗事件 / 探索产出 / 偶遇强敌 …
#       实证：归一化帧「战斗」钮 y=495，PC 标定 735 ⇒ 495 + C(240) = 735 ✓
#       ⇒ 条目 +C（dlg_items）、点击 tap_dlg、标题/X 在归一化帧不可见（要走弹窗帧）✓
#   · B 类「归一化（锚底）系」：**战斗结算面板**（胜利/失败/骰子/自动跳过/关闭）
#       实证：归一化帧「关闭」钮 y=1440 ≈ PC 标定 1439（差 1px ⇒ 完全不随 C 位移）
#       ⇒ 一切按归一化系：条目**不** +C、点击 b.tap、PC 标定区域原样可用
#       （v0.31 把结算面板也当成弹窗系 ⇒ handle_dice 搜索带错位 240 ⇒ 真机永远摇不了色子 ✗）
#   · 判别法（以后每个新面板都要先做这一步）：拿一张 C>0 的真机/20:9 帧，
#     看面板上某个已 PC 标定的元素在**归一化帧**里量到的 y 与 PC 值差多少：
#     差 ≈ C ⇒ A 类（弹窗系）；差 ≈ 0 ⇒ B 类（归一化系）。
_DLGS = {'C': None}


def dlg_c():
    """弹窗系 y 偏移 C（懒加载一次；PC 恒 0）"""
    if _DLGS['C'] is None:
        c = 0.0
        try:
            if os.environ.get('MAPBOT_ANDROID'):
                import mapbot as _mb
                c = float(_mb.dlg_shift())
        except Exception:       # noqa: BLE001
            c = 0.0
        _DLGS['C'] = c
        if c:
            say('       · 居中弹窗偏移 C=%+.0fpx（高分辨率屏 ⇒ 弹窗系 = 归一化帧 y+%d）'
                % (c, c))
    return _DLGS['C']


def dlg_items(items):
    """归一化帧 OCR 条目 → 弹窗系（cy +C）。C=0 时原样返回（PC/9:16 零开销零行为差）。

    ⚠ 只对弹窗系 y ≳ 509 的内容严格成立（更靠上的内容在真机归一化帧里被丢掉）；
    面板按钮筛选（650~860 / 820~1070 等）都在安全区 ✓
    """
    c = dlg_c()
    if not c or not items:
        return items
    out = []
    for it in items:
        d = dict(it)
        d['cy'] = it['cy'] + c
        out.append(d)
    return out


def _dlg_panel_btn(ditems, text, y0=650, y1=860):
    """⭐ 弹窗系里找**独立按钮**（严格相等匹配，防「战斗胜利/回放战斗」这类合并文本误命中）。

    用途：真机上面板**标题**（「战斗事件/探索产出」dlg≈443）和 X 关闭符（dlg≈225）
    落在 toRef 丢弃的弹性区 ⇒ 归一化帧里看不见 ⇒ 面板检测只能靠**看得见的按钮**
    （战斗/探索 dlg≈735~791，在归一化帧 526~582 处 ✓）。
    """
    for it in ditems:
        t = (it.get('text') or '').strip()
        if t == text and LAYOUT.sy(y0) <= it['cy'] <= LAYOUT.sy(y1):
            return it
    return None


def _dlg_btn_sig(ditems, kind):
    """⭐ v0.61：真机上靠**右下角按钮**认「黄金宝库」面板（零额外 OCR）。

    ⭐⭐⭐ 2026-10-01 **真机帧实测标定**（用户手动停在宝库面板，我只读抓帧 ✓）：
        弹窗帧实测：`黄金宝库` @dlg(690,438) conf 0.998 ／ `购买` @dlg(**895,1498**)
        conf 1.000 ／ `10000` @dlg(914,1541) ／ 说明文案「※花费金币分别解锁宝库的外层…」
        @dlg(387,1514)
      归一化帧里：**标题和按钮都看不见**（band 130~1080 内只有那句"只能领取一件哦"；
      按钮归一化 y ≈ 1498−209 = **1289** ⇒ 被 band 1080 截掉 ✗）
      ⇒ 这印证了本函数的思路（靠弹窗系按钮）**但原 y 带 1400~1530 太窄**：
        真机按钮在 **1498**、价格 1541 ⇒ 一旦文案变化（选择奖励/离开）就会掉出带外 ✗
      ⇒ 现按实测放宽到 **1330~1650**，并把认到的按钮写进日志（下次漂了一目了然 ✓）
    """
    if kind != 'vault':
        return False
    for it in ditems:
        t = (it.get('text') or '').strip()
        if 700 < it.get('cx', 0) < 1040 and 1330 < it.get('cy', 0) < 1650 \
                and any(k in t for k in ('购买', '选择', '离开', '完成', '领取')):
            return True
    return False


def vault_title_seen(ditems):
    """弹窗帧里有没有**宝库标题**（真机实测 @dlg(690,438) conf 0.998 ✓）

    ⚠ 此前文档里写的「宝库标题 dlg 383 落在 toRef 丢弃的弹性区 ⇒ 永远认不到」
      **不准确**：真机实测标题在 dlg 438，而丢弃带是 dlg>509 ⇒ **标题其实在带外、读得到** ✓
      （真正读不到的是归一化帧：那里标题被压到 y<300 的锚顶区，OCR band 又以 130 起 ⇒ 漏）
      ⇒ 两条件（标题 or 按钮）任一命中即认定宝库面板 ✓ 更稳
    """
    for it in ditems or []:
        t = (it.get('text') or '').strip()
        if '黄金宝库' in t or ('宝库' in t and '解锁' not in t):
            return True
    return False


def panel_seen(items, ditems=None, b=None):
    """⭐ v0.33：**现在有没有弹着面板**（特殊地块 / 探索 / 战斗 / 领取 / 结算 / 确定）。

    ⚠ `b`（Bot，可选）：只有走「真·弹窗帧 OCR 复核」那条路才需要它；
      不传就跳过那段（PC / 9:16 C=0 本来就走不到）✓

    ⚠⚠ 漏判的后果很严重：主循环靠它 `break` 出点序、交给 `popups()` 处理；判不成
      ⇒ 它就带着面板继续点后面的格子 ⇒ 点击全落到面板上 ⇒ "点了战斗格却不点战斗" ✗
    ⚠ 真机高分辨率（C>0）上面板**标题**（战斗事件/探索产出/获得新装备…）落在 toRef 丢弃的
      弹性区 ⇒ 归一化帧里看不见 ⇒ 只看标题必然漏判 ⇒ 补一条：弹窗系里出现独立的
      「战斗」/「探索」按钮（dlg 650~860）即判"面板弹着" ✓
      （PC / 9:16 C=0 ⇒ 与原来完全等价 ✓）
    ⚠⭐ v0.61 再补一条**黄金宝库**：它的标题（dlg 383）和 X（dlg 384）**都在丢带里**
      ⇒ `fb(items, *L['special'])` 对它恒 False（旅行商人标题 dlg 601 不在丢带，所以只有
      宝库会漏）⇒ 面板盖着棋盘却报"没面板" ⇒ 主循环继续点棋盘格（全落到面板上）⇒
      白烧 2 轮 + 一堆 OCR/等待才走「点了没反应」的兜底。改用归一化帧里看得见的签名：
        ① 说明文案「※花费金币分别解锁宝库的外层…」→ 含「解锁宝库」(dlg 1459 ⇒ 帧内 1250 ✓)
        ② 右下角按钮（dlg 1444 ⇒ 帧内 1235 ✓）
    """
    if fb(items, *L['special']) or fb(items, L['fight']) or fb(items, L['expl']) \
            or fb(items, *L['claim']) or fb(items, *L['desc']):
        return True
    if dlg_c():
        ditems = ditems if ditems is not None else dlg_items(items)
        if _dlg_panel_btn(ditems, L['fbtn']) or _dlg_panel_btn(ditems, L['ebtn']):
            return True
        if fb(items, '解锁宝库') or _dlg_btn_sig(ditems, 'vault'):
            return True
        # ⭐⭐⭐ 2026-10-01 真机修（用户报「识别到宝库，点开**瞬间就关**」）：
        #   上面 `ditems = dlg_items(items)` 只是**把归一化条目坐标 +C**，条目本身仍是
        #   归一化帧 OCR 的产物 ⇒ **band 之外的按钮（真机宝库在 ≈1121~1441）根本不在 items 里**
        #   ⇒ 换算后照样没有 ⇒ 宝库判据恒 False ✗
        #   ⇒ 这里再补一手**真·弹窗帧 OCR**（`dlg_ocr`）：它覆盖到弹窗系 1769，
        #     宝库/商人的按钮就在那儿 ✓（≈2s，且**只在 dlg 环境**、有面板嫌疑时跑 ✓）
        try:
            # ⚠⚠ 2026-10-01 修 NameError：这里原来直接用 `b`，但本函数**签名里没有 b**
            #   ⇒ 真机（走 dlg_c() 真分支时）必然 NameError ⇒ 被 except 吞掉
            #   ⇒ **整段「真·弹窗帧 OCR 复核」从来就没跑过**（PC C=0 走不到，真机是唯一受害者）
            #   这正是用户 10-01 报的「点开宝库瞬间就关」没修掉的直接原因。
            # ⇒ 现在 b 由调用方传入（可选）；没传就跳过这一段（保持旧行为，不崩）。
            if b is not None and hasattr(b, 'ocr_dlg'):
                _dp = dlg_ocr(b, tag='panel_seen_dlg')
                if _dp:
                    if _dlg_panel_btn(_dp, L['fbtn']) or _dlg_panel_btn(_dp, L['ebtn']):
                        return True
                    if vault_title_seen(_dp) or _dlg_btn_sig(_dp, 'vault'):
                        return True
        except Exception:       # noqa: BLE001
            pass
    return False


def tap_item(b, it, wait=1.2, in_dlg=False):
    """⭐ v0.34：点一个 **OCR 找到的**条目 —— 通道必须跟**条目所在坐标系**走。

    数学上 `b.tap(归一化帧 y)` 与 `b.tap_dlg(弹窗系 y)` 落在**同一个设备点**
    （两套映射斜率相同，弹窗系 = 归一化帧 + C）⇒ 只要条目和通道同源就必然点中 ✓；
    串味（弹窗系条目走 b.tap）会整体下移 C·k（真机 ≈248 设备px）⇒ 必空 ✗。
    固定标定点（FIGHT_Y / X(493,225) / 万能位…）**不走这里**——它们本来就有自己的通道。
    """
    if it is None:
        return False
    x, y = it.get('cx'), it.get('cy')
    if x is None or y is None:
        return False
    return b.tap_dlg(x, y, wait=wait) if in_dlg else b.tap(x, y, wait=wait)


# ⭐⭐ v0.34「通道同源」总闸：当前在闭环里流动的 **OCR 条目**是哪个坐标系。
#   · False（默认）：条目来自归一化帧（顶块锚顶 / 其余锚底）⇒ 点走 b.tap
#   · True        ：条目来自**弹窗帧**（弹窗系 == PC 参考系）⇒ 点必须走 b.tap_dlg
# 只要「条目坐标系」与「点击通道」同源就必然点中；串味会整体偏 C·kx（真机 ≈248 设备px）⇒ 必空。
# ⚠ 只管 **OCR 量出来的**条目；硬编码标定常数各有各的通道，不经过这里（保持真机已验证行为）。
# ⚠ 弹窗帧条目不翻译成归一化系再喂进来 —— 减 C 后会落进 y<300 的**顶块锚顶区**，
#   那里两段映射不同 ⇒ 同源律失效（X 关闭符 dlg≈225 就是这种情况）⇒ 必须整条链路留在弹窗系。
_OCR_CH = {'dlg': False}


def _tap(b, x, y, wait=1.2):
    """点一个**当前通道里量出来的**条目坐标（通道见 _OCR_CH）"""
    return b.tap_dlg(x, y, wait=wait) if _OCR_CH['dlg'] else b.tap(x, y, wait=wait)


def ocr_ch(b, tag=None, band=None, min_conf=None):
    """按**当前通道**取 OCR 条目 —— 弹窗模式下取弹窗帧 ⇒ 看得到面板标题（归一化帧看不见）"""
    if _OCR_CH['dlg'] and hasattr(b, 'ocr_dlg'):
        try:
            return list(b.ocr_dlg(min_conf=min_conf or 0.5, band=band, tag=tag) or [])
        except Exception:       # noqa: BLE001
            pass
    kw = {}
    if band is not None:
        kw['band'] = band
    if min_conf is not None:
        kw['min_conf'] = min_conf
    return b.ocr(tag=tag, **kw)


# ══════════════════════════════════════════════════════════════════════
# ⭐⭐ 2026-10-01 **PC 端提速层**（用户定：锁 720×1280 换速度，
#       「能点固定位置的就用固定位置，只能 OCR 的才 OCR」）
#
# 实测（720×1280，PC venv）：
#     OCR 一次 1.4~3.6s ／ 模板匹配一次 **6.8ms** ⇒ **快 530 倍**
# ⇒ 凡是「位置固定 + 长得固定」的，一律走 `fixed.py`；只有**会变的文字**才 OCR。
#
# ⚠ 口径：PC 端**锁定 720×1280**，所以 `fixed.A()` 给的就是**设备坐标**，
#    直接 `b.tap(x, y)` 即可，**不要**再乘 LAYOUT.k（那是给真机 1080 基准用的）。
#    手机端**不用这一层**（它是 1080×1920 归一化系 + 各种动态弹窗）⇒ 两端互不影响。
# ══════════════════════════════════════════════════════════════════════
try:
    import fixed as _FX
except Exception:            # noqa: BLE001  —— 缺模块就退回纯 OCR，不影响功能
    _FX = None

# 同一帧的快查缓存（模板匹配很便宜，但省掉重复 slice/编码仍有意义）
_FX_CACHE = {'stamp': None, 'val': {}}


def _fx_frame_id(b):
    """帧标识：用 Bot 的 snap 计数（每抓一张新帧就变）⇒ 同帧内缓存自动失效

    ⚠⚠ 2026-10-06 修 BUG-1：**本函数以前没有守卫**，而 `mapbot.Bot` 当时**根本没有**
    `_snap_n` ⇒ 返回恒定 `(None, id(b))` ⇒ `_FX_CACHE` **一旦缓存就永不失效**
    （实测：对纯黑帧问 `close_tpl_0` 仍返回上一帧结算面板的 `True` ✗）。
    现在 `mapbot.Bot` 已真的维护 `_snap_n`（见 `mapbot.py` `Bot.__init__`）；
    并且下面两处调用点**在 stamp 为 None 时干脆不缓存**（退化成"每次都真算"）——
    这样万一哪天计数器又没了，**代价只是慢一点，绝不会再返回陈旧值** ✓
    """
    return (getattr(b, '_snap_n', None), id(b))


def fx_has(b, name, band=None, refresh=False):
    """模板快查：这个固定元素**在不在**当前帧？返回 bool（从不抛异常）"""
    if _FX is None:
        return False
    try:
        img = b.img()
    except Exception:        # noqa: BLE001
        return False
    fid = _fx_frame_id(b)
    box = _FX.BANDS.get(band) if band else None
    # ⭐ BUG-1 兜底：拿不到帧号 ⇒ **不缓存**（宁可真算，也不返回陈旧值 ✓）
    if fid[0] is None and not refresh:
        return _FX.has(img, name, box=box)
    if refresh or _FX_CACHE['stamp'] != fid:
        _FX_CACHE['stamp'] = fid
        _FX_CACHE['val'] = {}
    if name in _FX_CACHE['val']:
        return _FX_CACHE['val'][name]
    v = _FX.has(img, name, box=box)
    _FX_CACHE['val'][name] = v
    return v


def fx_at(b, name, band=None, refresh=False):
    """模板快查：返回固定元素的 (x, y) 中心；没命中返回 None（用来直接点它）"""
    if _FX is None:
        return None
    try:
        img = b.img()
    except Exception:        # noqa: BLE001
        return None
    fid = _fx_frame_id(b)
    box = _FX.BANDS.get(band) if band else None
    # ⭐ BUG-1 兜底：同 fx_has（拿不到帧号 ⇒ 不缓存 ✓）
    if fid[0] is None and not refresh:
        hit = _FX.find(img, name, box=box)
        return (hit[0], hit[1]) if hit else None
    if refresh or _FX_CACHE['stamp'] != fid:
        _FX_CACHE['stamp'] = fid
        _FX_CACHE['val'] = {}
    key = (name, 'at')
    if key in _FX_CACHE['val']:
        return _FX_CACHE['val'][key]
    hit = _FX.find(img, name, box=box)
    v = (hit[0], hit[1]) if hit else None
    _FX_CACHE['val'][key] = v
    return v


def fx_tap(b, name, band=None, wait=1.2, log=None, what=''):
    """点一个**固定位置**的元素：先快查定位（ms 级），命中就直接点，**不 OCR**；
    没命中返回 False（调用方决定要不要回退 OCR 路径）。

    这是"能点固定位置的就用固定位置"的主入口。
    """
    pos = fx_at(b, name, band=band)
    if pos:
        b.tap(pos[0], pos[1], wait=wait)
        if log is not None:
            log.append({'fx_tap': what or name, 'at': pos, 'hit': True})
        return True
    if log is not None:
        log.append({'fx_tap': what or name, 'hit': False})
    return False


def fx_menu(b):
    """现在在**选图界面**吗？——「进入地图」按钮的**模板快查**（≈7ms、**0 OCR**）

    ⭐⭐⭐ 2026-10-02 新增（用户口径：「尽量减少 OCR，能定死坐标/模板的就定死」）：
      `in_map()` / `enter_map()` / `finish_map()` 三处都在问同一件事「现在是不是在选图界面」，
      原来各自靠 OCR 读「进入地图 / 快速扫荡」文字（**≈0.78s/次**）。
      而这两颗按钮**位置固定、外观固定** ⇒ 正是 `fixed.py` 该管的"固定 UI"✓
      模板 `templates/fixed/enter_map_btn.png`（150×110，中心 (603,1079)
      —— 与 `layout.REF['enter_map']` 逐像素同心 ✓）

    标定（离线，**真机帧**，零体力）：
      · 正样本 3 张真选图界面（含 `runs/_adb_cmp.png` 那张 bot 自己抓的）⇒ 全 **1.000**
      · 负样本 24 张（棋盘/结算面板/确认框/…）⇒ 最高 **0.423**
      ⇒ 阈值取 **0.80**（比模块默认 `MATCH_MIN=0.62` 更严）：
        **宁可漏判去走原来的 OCR，也绝不误判成"在选图界面"** ✓
        （搞错方向的代价不对称：误判 ⇒ `finish_map` 提前收工、在非选图界面去点进图 ✗）
    """
    if _FX is None:
        return False
    try:
        img = b.img()
        if img is None:
            return False
    except Exception:            # noqa: BLE001
        return False
    try:
        return bool(_FX.has(img, 'enter_map_btn',
                            box=_FX.BANDS.get('enter_btn'), min_conf=0.80))
    except Exception:            # noqa: BLE001
        return False


def fx_anchor(name):
    """取固定坐标（**设备系 720×1280**，直接给 b.tap 用）"""
    if _FX is None:
        return None
    return _FX.A(name)


# ⛔ 2026-10-02 **撤回**：曾加过 `fx_inmap_quick()`（用导航条模板判"在不在图内"）。
#   错在前提 —— 底部导航条在**大厅/选图/图内三界面都常驻**（实测图内帧 5 个模板
#   全 1.00 命中），「导航条在」推不出「在图内」⇒ 会把大厅/选图误判成已进图。
#   ⇒ **不要**再实现它。提速只走两条真安全的路：
#      ① 固定按钮直接点坐标（`fx_anchor` / `fx_tap`）—— 位置唯一、无歧义；
#      ② OCR 搜索带收窄 —— 同样判据、更少像素。


def dlg_ocr(b, min_conf=0.5, tag='dlg'):
    """⭐ v0.34：**弹窗帧** OCR —— 拿得到**面板标题**（归一化帧里看不见的那批）。

    真机上 `toRef` 会丢掉设备弹性区，而所有面板标题都落在那里（战斗事件 dlg≈443、
    偶遇强敌 dlg≈243、旅行商人/预言石板…）⇒ 归一化帧 OCR 永远认不出面板类型
    ⇒ 只在"面板确实开着但认不出类型"时补这一手（≈2s；**不是每轮都跑** ✓）。
    PC / 9:16（C=0）没有这个通道 ⇒ 返回 None（标题本来就可见，无需补）。

    返回：弹窗系条目列表（坐标**即** PC 参考系坐标），失败返回 None。
    """
    if not dlg_c() or not hasattr(b, 'ocr_dlg'):
        return None
    try:
        items = list(b.ocr_dlg(min_conf=min_conf, tag=tag) or [])
    except Exception:       # noqa: BLE001
        return None
    return items if items else None


# ══════════════════════════════════════════════════════════════════════════
# 探索小队槽（紫/橙地块「探索产出」的前置条件）
#
# ⭐⭐ 2026-09-30 真机事故修复（用户报「明明探索格子满了，还一直点探索」）
#   日志实证（Redmi / MGAS v0.64）：`{'explore': 'first_high_value', 'at': (274, 790)}`
#   **连打 18 轮**（105 秒、0 战斗 0 装备、白花 25 体力），末了只能人工停。
#   两条根因：
#     ① **倒计时被 OCR 吃掉一个冒号**：真机帧实测 `04:24:31` → `04:24831`（conf 0.87）
#        ⇒ 旧式 `TOTAL(3) - busy(2) = 空闲 1` = **假空闲**（真值 0）
#     ② 该账号 HUD 是 **4 个槽**（角标 1/2/3/4，其中 1 个"待领取"只有进度条没有倒计时）
#        ⇒ `EXPLORE_SLOTS_TOTAL=3` 的反推法**从根上不成立**，已废除。
#   ⇒ 新口径 = **只认正面证据**「空闲」二字：
#        · 认到 ⇒ 有空闲槽（几个算几个）
#        · 没认到 ⇒ **这一帧不下结论**（free=None，保留旧值）—— 真伪交给
#          popups 的「点一次 + 验证面板是否被受理」闭环：派进去了就是真有空闲，
#          连点两次都没反应 ⇒ 判满本图（改开打 ✓ 用户 09-26 口径）
#   ⚠ 为什么不干脆"没认到就当满"：那样会让**「空闲」字小/被遮认不出来的机器永远
#     派不出探索小队**。09-26 那版死在"假空闲"这个方向，两个方向都不能拍死 ✗
#
# ⭐⭐⭐ 2026-10-02 又补了**两条**（用户报「一直点紫探索」；22:15 那把铁证：
#   rounds 1→24 每轮都是 `{free_txt:0, busy_strict:3}`，而 slots_free 卡在**默认值 1**
#   ⇒ 「槽满」闸门永不成立 ⇒ 连点 24 轮、体力纹丝不动 ✗）：
#     ① `explore_slots_free`：**占用数已达槽总数 ⇒ 单向判满(0)**
#        ⛔ 这**不是**上面废除的 `TOTAL − busy` 反推 —— 那条是**算空闲个数**（还算出过
#           假空闲）；这条只是"占满了 ⇒ 没有空位"。失败方向同样安全：倒计时被 OCR
#           并成一条时 `strict` 偏小 ⇒ 本判据不成立 ⇒ 退回原行为，不会更差 ✓
#        ⚠ 前提是 `EXPLORE_SLOTS_TOTAL` 必须是**本账号**的真实槽数：它曾被误抄成
#           手机端的 4（见该常量处的注释），**3** 才是 PC/本账号的值。
#     ② popups 里「点了没效果」那条**必须有上限**：跨轮计数（存本图状态），
#        连续 3 轮都没效果就认满改开打（原来只要 HUD 说还有空槽就永远"下轮再试" ✗）
_EXPLORE_TIMER_RE = re.compile(r'\d{1,2}:\d{2}:\d{2}')
# 容错式：允许**吃掉一个冒号**（"04:24831"）。只认"整条基本就是计时器"的条目
# （`^\D{0,3}…\D{0,3}$`），防把 `PID:222025` / `4057162` 这类数字也数成倒计时 ✗
_EXPLORE_TIMER_BROKEN_RE = re.compile(r'^\D{0,3}\d{1,2}:\d{2,4}:?\d{2,4}\D{0,3}$')


def count_slot_timers(items):
    """数「探索槽倒计时」→ (严格命中数, 含容错命中数)。

    ⚠ 这个数**只进日志/诊断**，不再当闸门（见上面那段：用它反推空闲数会假空闲 ✗）
    """
    strict = loose = 0
    for it in (items or []):
        t = (it.get('text') or '').replace('：', ':').replace(' ', '')
        n = len(_EXPLORE_TIMER_RE.findall(t))
        if n:
            strict += n
            loose += n
        elif ':' in t and _EXPLORE_TIMER_BROKEN_RE.match(t):
            loose += 1
    return strict, loose


def explore_slots_free(items):
    """空闲探索槽 → (free | None, info)

    · 认到「空闲」⇒ free = 个数（封顶 EXPLORE_SLOTS_TOTAL）✓ 硬证据
    · 一个都没认到 ⇒ free = None（**这一帧不下结论**，见文件上方那段说明）
    · ⭐⭐ 认到「空闲」**但与倒计时数矛盾** ⇒ free = None（**这一帧不可信**）

    ⛔⛔⛔ 2026-10-02 真机事故（用户：「点开探索格子后不知道点哪里了就关了，
       没有正确探索」）：
        日志实证（gui_20261002_151411.log）：
            [r0] slots={free_txt:2, busy:2, busy_strict:2} free=2
            点「探索」= fixed.A('explore_btn')=(183,491) → 派出一支小队 ✓
            ⚠ 那条日志里记的 (275,736) 是 **1080p 旧值**，换基准漏改
              ⇒ 实际点在空处、面板永远关不掉（2026-10-02 修）
            [r1] slots={free_txt:2, busy:1, busy_strict:1} free=2   ← ★矛盾
            下一轮 `force_unstick(why='explore_slots_full')` 把面板关了 ✗✗
        真机现场 OCR（我抓的）**复现了矛盾**：
            空闲 (236,599)   空闲 (315,599)   ← 两个「空闲」
            04:27:04 (159,627)                  ← 一个在跑
        ⇒ 2 空闲 + 1 在跑 = **3** > 槽总数 ⇒ 至少有一个「空闲」是**误认**
          （空槽占位图 / 数字被当字 / 别的 UI 恰好写着「空闲」）。
        ⇒ 旧口径「只要认到『空闲』就无条件相信」（3623 行）⇒ **读数自相矛盾也照信**
          ⇒ 判成「还有 2 个空槽」⇒ 下一轮又派 / 或与 busy 打架 ⇒ `force_unstick`
          把面板一关，就成了用户看到的「不知道点哪里就关了，没有正确探索」✗✗
        ⇒ 修法：**加一道自洽性检查** ——
            认到的「空闲」数 + 数到的倒计时 **> 槽总数** ⇒ 这一帧两个读数至少错一个
            ⇒ **不下结论**（free=None，保留旧值）⇒ 交给 popups 的
              「点一次 + 验证面板是否被受理」闭环去裁决（那是 09-26 定下的正路）✓
          ⚠ 仍**不是**「没认到就当满」—— 那会让「空闲」字认不出的机器永远派不出小队
            （09-26 的教训，两个方向都不能拍死 ✗）
    """
    n_free = sum(1 for i in (items or []) if '空闲' in (i.get('text') or ''))
    strict, busy = count_slot_timers(items)
    info = {'free_txt': n_free, 'busy': busy, 'busy_strict': strict}
    if n_free > 0:
        # ⚠⚠ 2026-10-02 我在这里加过「空闲数按槽位锚点去重」的逻辑，**已撤回**：
        #   起因是我以为日志里 `free_txt:2, busy:1` 是**自相矛盾**（2 空闲 + 1 在跑
        #   > 槽总数），但现场 OCR 证明**那帧确实有 2 个真空闲槽**：
        #       空闲 (236,599)=slot_2   空闲 (315,599)=slot_3   04:27:04(159,627)=slot_1
        #   ⇒ 读数**完全正确**（3 槽、1 忙 2 空）⇒ 我判断错了，不是 bug ✗
        #   ⇒ 保留去重函数但**不接入**（它对真机数据输出不变，属无用改动），
        #     免得后人以为「槽位曾经算错过」。
        return max(0, min(int(EXPLORE_SLOTS_TOTAL), n_free)), info
    # ⭐⭐⭐ 2026-10-02 补一条**单向**结论：**占用数已达槽总数 ⇒ 就是满**（返回 0）
    #   真机铁证（用户报「一直点紫探索」，gui_20261002_221551 / loop_log rounds 1→24）：
    #     每一轮都是 `slots: {free_txt: 0, busy_strict: 3}`，而 `slots_free` 卡在
    #     **初始默认值 1** ⇒ popups 的「槽满」闸门（`slots_free <= 0`）永不成立
    #     ⇒ 对着紫格连点「探索」**24 轮**、体力纹丝不动 ✗✗
    #   为什么这条**不是**被废除的「TOTAL − busy 反推」：
    #     · 那条是拿它去**算空闲个数**（还会算出 free=1 ⇒ 假空闲 ⇒ 死循环）✗
    #     · 这条是**单向**的：数到的倒计时已经等于**总数** ⇒ 确实没有空位可用 ✓
    #   为什么失败方向是安全的（两个方向都试过，这条不会重蹈）：
    #     · 若 OCR 把多条倒计时**并成一条**（`04:24:3106:38:17` 那类），strict 会**偏小**
    #       ⇒ 本判据**不成立** ⇒ 退回原来的 `None`（保留旧值）⇒ 不会更差 ✓
    #     · 要误判成"满"，得凭空多认出一条 `hh:mm:ss`（`count_slot_timers` 用严格正则）
    #       ⇒ 代价只是"这格改开打"，**不是**死循环 ✓
    if n_free == 0 and int(strict) >= int(EXPLORE_SLOTS_TOTAL):
        return 0, info
    return None, info


def _count_slots_by_anchor(items):
    """按**槽位锚点 x**把「空闲 / 倒计时」归位，**同一槽位只算一次** ✓

    ⭐ 为什么必须这么数（2026-10-02 真机事故）：
       旧口径 `sum('空闲' in text)` 是**数条目**，不是**数槽位** ——
       同一个槽位被 OCR 拆成两条、或别的 UI 也写着「空闲」时就会多数 ⇒
       `n_free=2` 而真实只有 1 个空槽 ⇒ 与倒计时数打架 ⇒
       下一轮判「槽满」⇒ `force_unstick` 把面板一关，就成了
       「点开探索格子后不知道点哪里就关了」（用户原话）✗✗
    ⇒ 这里按 x 归位：每个槽位锚点（`fixed.slot_1/2/3`）**最多算一次** ✓
    """
    out = {'free': 0, 'busy': 0, 'total': 0, 'xs': []}
    try:
        import fixed as _fx
        xs = sorted({_FX.A('slot_1')[0], _FX.A('slot_2')[0],
                     _FX.A('slot_3')[0]})
    except Exception:                                       # noqa: BLE001
        return out
    _hit = {}
    for it in (items or []):
        t = (it.get('text') or '').replace('：', ':').replace(' ', '')
        kind = None
        if '空闲' in t:
            kind = 'free'
        elif _EXPLORE_TIMER_RE.search(t) or _EXPLORE_TIMER_BROKEN_RE.match(t):
            kind = 'busy'
        if kind is None:
            continue
        try:
            x = int(it.get('cx') or 0)
        except (TypeError, ValueError):
            continue
        # 归到**最近的**槽位锚点
        try:
            k = min(xs, key=lambda v: abs(v - x))
        except ValueError:
            continue
        if abs(k - x) > 60:          # 离所有槽位都远 ⇒ 不是槽位行里的东西
            continue
        # ⭐ 同一槽位**只记一次**（冲突时「在跑」优先 —— 倒计时是硬证据）
        prev = _hit.get(k)
        if prev is None or (prev == 'free' and kind == 'busy'):
            _hit[k] = kind
    out['xs'] = sorted(_hit)
    out['free'] = sum(1 for v in _hit.values() if v == 'free')
    out['busy'] = sum(1 for v in _hit.values() if v == 'busy')
    out['total'] = len(_hit)
    return out


def _set_slots_free(ctx, v):
    """把「空闲探索槽」写回**本轮 ctx** 与**持久 flags**（popups 里改结论用 ✓）

    ⚠ 必须两处都写：ctx 是这一趟 popups 用的，flags(=st) 是下一轮 one_round 读的。
    """
    try:
        v = int(v)
    except Exception:       # noqa: BLE001
        return
    try:
        ctx['slots_free'] = v
    except Exception:       # noqa: BLE001
        pass
    try:
        (ctx.get('flags') or {})['slots_free'] = v
    except Exception:       # noqa: BLE001
        pass


def _explore_panel_visible(items, ditems):
    """当前这帧是不是**地块面板**（「探索产出」标题 或 看得见的「探索」按钮）"""
    if fb(items, L['expl']):
        return True
    return bool(dlg_c()) and bool(_dlg_panel_btn(ditems, L['ebtn']))


def _fight_panel_visible(items, ditems):
    """当前这帧有没有**看得见的「战斗」按钮**（决定"槽满了改开打"能不能真的开打）"""
    if fb(items, L['fight']):
        return True
    return bool(dlg_c()) and bool(_dlg_panel_btn(ditems, L['fbtn']))


# ⭐⭐ 2026-09-30 成本审计（**零行为影响**，只写日志）
#   背景：用户报「最省体力算法出错：不点 1 体力的，去点 4 体力的」（现场存档见
#   `android_autoexplore/_verify/phone_stamina_0930/`）。logcat 里原本**只有格号没有成本**
#   ⇒ 事后无法判断"1 点的草地到底有没有排在点序前面"、还是"模型把贵地块看成了草地"。
#   口径 = `mapsolve.Problem.block_cost`（空地 1 / 内容格·探索 SpotSize / 内容格·战斗 ×2）
_COST_FIGHT_MARKS = ('boss', 'redEquip', 'recommend', 'battle',
                     '拦路')      # ⭐ 2026-10-03 用户口径：拦路格也是战斗 ⇒ 格数×2 ✓
# ⭐⭐ v1.08 标记中文名（用户口径：日志要写清"打的是什么格子"，多种标记全写出来 ✓）
MARK_CN = {'boss': '首领', 'recommend': '大拇指', 'clover': '四叶草',
           'redEquip': '红装', 'battle': '战斗'}


def mark_cn(marks):
    """标记英文 → 中文名列表（**全写出来**，用户 2026-10-01 口径）

    用户原话：「战斗时日志要写出打这个格子是什么格子，拦路的就写拦路格，首领就写首领格，
    四叶草就写四叶草格，大拇指就写大拇指格。同时有多种就都写出来，比如
    当前格子标志：首领，四叶草，大拇指，红装」✓
    """
    out = []
    for m in (marks or []):
        cn = MARK_CN.get(str(m))
        if cn and cn not in out:
            out.append(cn)
    return out


def tile_desc(marks):
    """该格的**中文标签串**（一个都没有 ⇒ 空串，调用方自己决定兜底成「拦路格」✓）"""
    _cn = mark_cn(marks)
    return '，'.join(_cn) if _cn else ''


def tile_phrase(marks):
    """该格的**完整中文说法**（用户 2026-10-01 口径的最终文案 ✓）

    · 无标记   ⇒ `拦路格`
    · 单个     ⇒ `首领格` / `四叶草格` / `大拇指格` / `红装格`
    · 多个     ⇒ `格子标志：首领，四叶草，大拇指，红装`（用户原话给的样例 ✓）
    """
    _cn = mark_cn(marks)
    if not _cn:
        return '拦路格'
    if len(_cn) == 1:
        return '%s格' % _cn[0]
    return '格子标志：%s' % '，'.join(_cn)


def model_cost(sid, marks=()):
    """这一格**模型以为**要花的体力（仅供日志审计 ✓ 不参与决策 ✗）"""
    try:
        row = (spots_mod.spot_rows().get(str(sid)) or {})
        size = int(row.get('SpotSize') or 1)
        if spots_mod.is_plain_spot(str(sid)):
            return 1                      # 空地（连锁）：固定 1 点 ✓
        if set(marks or ()) & set(_COST_FIGHT_MARKS):
            return size * 2               # 明确要打的 ⇒ SpotSize×2 ✓
        return size                       # 内容格·探索 = SpotSize ✓
    except Exception:       # noqa: BLE001
        return 1


# ⭐⭐⭐ 2026-10-11 **面板标题表**（治「第 46 张卡死 44 轮」✗）
#   为什么要它：`fb()` 是**子串**匹配 ⇒ **正文里的字**也会命中 ✗
#   真机铁证：预言石碑面板上有一张预言卡「奇遇」，效果文字写着
#     「地图中至少出现 1 个**勇者之墓**，并且勇者之墓奖励至少为橙色位阶」
#     ⇒ `fb(items,'勇者之墓')` 命中 ⇒ 面板被**错判成勇者之墓** ✗
#     ⇒ `relic_flow` 找不到自己的面板 ⇒ `panel_missing` ⇒ **重复 44 轮、零进展** ✗✗
#   ⭐ 面板**标题**是"当前开着哪个面板"的**唯一权威**（正文是软证据 ✓）
#   ⚠ 只列**实测过的标题**（`_ref_game_src/README_*_真机实测.md` + 真机帧 ✓）
#     没实测的别乱加 —— 加了会误导分派 ✗
_PANEL_TITLES = (
    '预言石板',        # = 预言石碑（真机 OCR conf=0.99 ✓）
    '英灵使者',        # = 勇者之墓（`runs/spec_dev/relic_panel.png` ✓）
    '限时超值礼包',    # = 限时礼包（`runs/spec_dev/gift_free1.png` ✓）
    '传承祭坛',        # 真机帧 `_verify/shrine_panel.png` ✓
    '黄金宝库',        # `runs/vaultdbg/*` ✓
)


#: ⭐⭐⭐⭐⭐ 2026-10-14 **退图前补点时"只关掉、不领奖"的面板标题**（用户口径 ✓）
#:   ---- 为什么要它（用户报「**这张图为什么显示退图失败然后停止了**」）----
#:     真机铁证（`runs/acc3/loop/loop_log_prev.json` 第 6 张图）：
#:       补点点到 `1,6`=`限时礼包` ⇒ 弹出面板 ⇒ `final_collect` **不认识它** ✗
#:       ⇒ `still=true` ⇒ `force_unstick` 关不掉 ⇒ 反复点万能位 `(360,1219)`
#:         （那个值**等于**底部导航「开始冒险」）⇒ 空转 **110.6 秒** ⇒ 整局停下 ✗✗
#:   ---- 覆盖面缺口（实测）----
#:     `popups()` 认 6 种特殊面板，而 `final_collect`（退图前补点）**只认 2 种**
#:       · 认：预言石板（关掉+拉黑）/ 预言石碑（领掉）
#:       · **不认**：限时礼包 / 传承祭坛 / 勇者之墓 ✗（宝箱怪见下）
#:   ⇒ 本表列出那 3 种的**面板标题**（都在 `_PANEL_TITLES` 实测清单里 ✓）
#:   ⚠⚠ **不放宝箱怪** —— 本仓纪律「**没实测过的标题别乱加**」（`_PANEL_TITLES`
#:     的注释原话 ✓）。实测 `_PANEL_TITLES` **只有 5 个**：
#:       `预言石板` / `英灵使者` / `限时超值礼包` / `传承祭坛` / `黄金宝库`
#:     **没有宝箱怪的** ⇒ 我第一版凭想象写了 `机巧宝箱怪`/`金属宝箱怪`
#:     ⇒ 回归 ⑦⑧ 当场抓到（`_panel_title_of` 根本认不出它们 ⇒ **等于没写** ✗✗）
#:     ⇒ 真要处理宝箱怪，得**先采一张 `mimic_panel.png` 读出真标题**（下一轮 ✓）
#:   ⚠ **只关不领**：`final_collect` 的契约是"只补点 + 关面板，不再打架、不再买、
#:     不再揭新格"（见它 docstring）⇒ 这里**不调** `gift_flow`/`shrine_flow`/…
#:     （那些会领奖/购买，违背"退图收尾"的原意 ✗）
_FC_CLOSE_TITLES = (
    '限时超值礼包',    # = 限时礼包（`S00003_014`；真机 `gift_free1.png` ✓）
    '传承祭坛',        # = 传承祭坛（真机 `_verify/shrine_panel.png` ✓）
    '英灵使者',        # = 勇者之墓（真机 `runs/spec_dev/relic_panel.png` ✓）
)


def _panel_title_of(items):
    """这一帧**明确读到**的面板标题（**标题优先**，找不到返回 None ✓）

    ⚠ 只在"**独立成条**"的文字里找（`text` **等于**标题），不做子串匹配 ——
      否则预言卡正文里的「勇者之墓」又会被当成标题 ✗（那正是本函数要治的病 ✓）

    ⚠⚠ 2026-10-11 真机发现：OCR 会把标题**带上前缀符号** ——
       `#2500` 那条读成 **`+预言石板`**（多一个 `+`）✗
       ⇒ 纯"等于"会**漏掉**它 ⇒ 这里**先剥掉首尾的非中文符号**再比 ✓
       （只剥符号、不剥中文 ⇒ 不会把 `本次可选择1个预言！` 之类剥成标题 ✓）
    """
    try:
        _txts = [str((it or {}).get('text') or '').strip() for it in (items or [])]
    except Exception:       # noqa: BLE001
        return None

    def _clean(s):
        # 只去掉**首尾**的非中文、非字母数字符号（`+预言石板` ⇒ `预言石板` ✓）
        _i, _j = 0, len(s)
        while _i < _j and not ('\u4e00' <= s[_i] <= '\u9fff' or s[_i].isalnum()):
            _i += 1
        while _j > _i and not ('\u4e00' <= s[_j - 1] <= '\u9fff'
                               or s[_j - 1].isalnum()):
            _j -= 1
        return s[_i:_j]

    _cl = [_clean(s) for s in _txts]
    for _t in _PANEL_TITLES:
        if _t in _txts or _t in _cl:       # ⭐ **等于**（不是 `in`）✓
            return _t
    return None


#: ⭐⭐⭐ 2026-10-12 **「发现莱姆！」弹窗的标题判据**（治「连续出现获得莱姆的点击」✗）
#:   ---- 为什么不能用 `fb`（子串匹配）----
#:     `fb(items, '莱姆')` ⇒ **任何含「莱姆」二字**的条目都命中 ✗
#:     而**预言石板面板**上的「元素」预言卡正文就含「莱姆」（数据表 `Foretell`）：
#:         `地图中至少出现 1 只莱姆，并且所有莱姆至少是蓝色位阶。`
#:       ⇒ 真机后果（`runs/gui_20261012_125244.log`）：
#:         点开 `5,4 预言石碑` ⇒ 面板正在画 ⇒ **连判 4 次"发现莱姆！"** ⇒
#:         点写死的 `lime_back()=(359,873)` ⇒ 4 次空点 ⇒ `loop_guard` 脱困 ⇒ 崩 ✗✗
#:   ---- 口径：标题必须**独立成条**（与 `_panel_title_of` 同一套思路 ✓）----
#:     弹窗标题在 OCR 里是**自己一条**；卡牌正文是**一长句**（带标点）
#:     ⇒ 用 **完全相等** 区分 ✓
#: ⚠ 允许的形态（**宁少勿滥** —— 多认会误点，少认只是漏一次）：
#:     · `发现莱姆！`  （真机实测标题 ✓）
#:     · `发现莱姆`    （去掉叹号，OCR 偶尔丢标点 ✓）
#:     · `莱姆`        （旧记录里的短形态 ✓ —— 但也**只认整条相等**）
#:   ⚠ **不认**含「莱姆」的长句（如"地图中至少出现1只莱姆…"）⇒ 那正是本次的误判源 ✓
_LIME_TITLES = ('发现莱姆！', '发现莱姆', '莱姆')


def _lime_popup_title(items):
    """这一帧**明确读到**「发现莱姆！」弹窗标题 ⇒ 返回那个标题，否则 None

    ⚠ 只在"**独立成条**"的文字里找（`text` **等于**标题），**不做子串匹配** ——
      否则预言卡正文里的「莱姆」又会被当成弹窗标题 ✗（那正是本函数要治的病 ✓）
    ⚠ 也剥掉首尾的非中文符号（OCR 偶尔带 `+`/`!` 前缀，与 `_panel_title_of` 同法 ✓）
    """
    try:
        _txts = [str((it or {}).get('text') or '').strip() for it in (items or [])]
    except Exception:       # noqa: BLE001
        return None

    def _clean(s):
        _i, _j = 0, len(s)
        while _i < _j and not ('\u4e00' <= s[_i] <= '\u9fff' or s[_i].isalnum()):
            _i += 1
        while _j > _i and not ('\u4e00' <= s[_j - 1] <= '\u9fff'
                               or s[_j - 1].isalnum()):
            _j -= 1
        return s[_i:_j]

    _cl = [_clean(s) for s in _txts]
    for _t in _LIME_TITLES:
        if _t in _txts or _t in _cl:
            return _t
    return None


def _is_foretell_panel(items):
    """这个面板是不是**预言石碑**（该走 `foretell_flow`）而不是要"关掉+拉黑"的占卜面板？

    ⭐⭐⭐ 2026-10-10 **抽成模块级共用判据**（治"改了 `popups()` 漏了别处" ✗）
      ---- 为什么必须共用 ----
        「预言石碑」这个面板在代码里有 **3 处**会碰到：
          ① `popups()` 的 `prophecy` 支（**最早**判，会 `universal_close` + 拉黑 ✗）
          ② 点击循环里的 `prophecy` 快路径（同上 ✗）
          ③ `final_collect` 退图补点里那两处（同上 ✗）
        ⇒ 我 10-10 只改了 ① ⇒ 用户当场又踩到 ②：
             `gui_20261010_203354_acc1.log:85`
             `· 点 (456,1100) 弹出「预言石板」→ 关掉并拉黑这格` ✗
        ⇒ README 早记过同一句教训（手机端 v1.63）：
            「**我前几轮一直在修 `popups()` 那条链，而真正吃掉这一格的是
              `final_collect()` 这条完全独立的路径**」
          ⇒ **同一个错又犯了一次** ⇒ 所以判据必须**一份、三处共用** ✓
      ---- 判据口径 ----
        · 方块名 `预言石碑`（数据表 `Area_Spot.Name`）
        · 面板标题 `预言石板`（真机 OCR conf=0.99）
        ⇒ **两个名字都算**（`预言石碑`/`预言石板` 是同一面板的两个名字 ✓）
        ⚠ 不含单独一个「预言」—— `L['hud']` 里也有「预言」（主界面入口）⇒ 会误伤 ✗
    """
    try:
        return bool(fb(items, '预言石碑') or fb(items, '预言石板'))
    except Exception:       # noqa: BLE001
        return False


def popups(b, items, log, ctx=None):
    ctx = ctx or {}
    markers = ctx.get('marks') or {}
    tapped = ctx.get('tapped')
    # ⭐ v0.32：弹窗系条目（+C）一次算好；真机上面板标题/X 在弹性区看不见，
    #   分支入口与按钮全靠它（C=0 时就是 items 本身，PC 零影响）
    # ⭐ v0.34：`in_dlg` ⇒ 调用方传进来的**就是弹窗帧条目**（已是弹窗系坐标），
    #   绝不能再 +C（否则按钮 y 带整体再抬 209 ⇒ 全都落空 ✗）
    ditems = items if (ctx or {}).get('in_dlg') else dlg_items(items)
    if fb(items, *L['kick']):
        log.append({'popup': 'kicked'})
        return 'kicked'
    # ===== DESTINY PROPHECY DIALOG (2026-10-27) =====
    # 用户报：「进图会弹出一个弹窗」—— 我现场截图确认（720x1280）：
    #   标题  提示                 (360,505)
    #   正文  当前关卡将会触发命运预言  (361,612)
    #   按钮  取消 (204,742)  |  确定 (516,742)
    #   背后是选图界面（清凉沙滩 / 夏日海滩入侵 / 底部 快速扫荡+进入地图）
    #
    # 病（会让整局卡死，真机可复现）：
    #   1) popups() 对它返回 'none'（实测 act='none'、taps=[]、log 空）
    #      => 没有任何代码会关掉它 => 弹窗一直挂着
    #      为什么接不住：末尾那条通用「确定」分支要求
    #        ok['cy'] > sy(900)  且  exb(items, L['cancel']) is None
    #      => 本弹窗「确定」在 cy=742 < 900，而且有「取消」=> 双杀
    #   2) enter_map 却照样点「进入地图」(603,1079)：
    #      on_menu=True（底部菜单字还在）、ent 也读得到
    #      => 点了被弹窗吞掉 => 9 轮 in_map 仍 False => enter: timeout
    #      => 整局「进图失败（体力不足 / 不在选图界面）」收工（体力明明够）
    #   3) 本仓 grep 命运预言 一条都没有 => 这条路径**从未被处理过**
    #      (我第一版误判成"游戏版本升级新加" — **错的**，见下面用户澄清)
    #
    # ---- 触发条件（用户 2026-10-27 澄清，原话）----
    #   「是上一张图三张卡选了SS级预言，这次进图就会弹弹窗」
    #   => 三张卡是在**上一张图**（预言石碑）选的，选到 SS 就挂着
    #      下一张图进图时才弹这个确认框 => **进图后不会再有卡** ✓
    #   数据表佐证：SS 档 7 种(foretell_4/10/14/26/27/32/49)，
    #     Duration 一律 1-1 = 只生效 1 张图 => 每次拿到 SS 必弹一次 ✓
    #   真机日志佐证（acc3 gui_console_20261027）：
    #     12:32:52 预言石碑完成（第 2 个，选了 命运）  <- foretell_49 = SS
    #     12:43:01 进图判定：体力 1997 / 下限 50
    #     12:43:48 进图失败（体力 1997 明明够）        <- 就是它 ✗
    # ---- ⚠⚠⚠ 注意：这是**两个不同的弹窗**，只是**坐标恰好相同** ----
    #             （用户 2026-10-27 澄清：「这是两种情况，一个是携带SS的
    #               弹窗，一个是携带了重复预言的弹窗。触发位置和时机不一样」）
    #   | | A：SS 携带 | B：重复预言 |
    #   |---|---|---|
    #   | 正文 | 当前关卡将会触发**命运预言** | 和平已有紫色**同名预言**，重复选择会将其覆盖 |
    #   | 时机 | **进图前**（选完 SS 的下一张图） | **选卡过程中**（点了重复的卡） |
    #   | 位置 | 选图界面 | 预言石板面板内 |
    #   | 处理者 | ❌ **无人**（本次补上） | ✅ `_foretell_dup_confirm`（10-19 已修） |
    #   坐标都是 `[取消(204,742)] [确定(516,742)]` —— 但**判据必须分开**：
    #     A 用正文「命运预言」（本分支）；B 由 `buypanels._foretell_dup_confirm` 接管
    #   ⚠ 我第一版误以为是"同一个弹窗" ⇒ **错**（用户当场纠正）
    #   ⚠ 而 B 那边（`buypanels.py:2780~2796`）的结论仍然值得继承：
    #     **绝不点「取消」—— 那等于这一次选择白做** ✓（A 同理：取消=不吃 SS 加成）
    # ---- 修法（点「确定」）：用户要的是进图 + 吃到 SS 加成 ----
    #   不能点「取消」—— 那是放弃进图
    #   判据用正文独有词 命运预言（比只看「确定」精确得多）
    #   放在最前面（kick 之后）：它是进图前置，被别的分支抢走就没法进图
    if any('命运预言' in (i.get('text') or '') for i in items):
        _ok_i = exb(items, L['ok'])
        if _ok_i:
            _tap(b, _ok_i['cx'], _ok_i['cy'], wait=2.0)
            log.append({'popup': 'destiny_confirm', 'at': (_ok_i['cx'], _ok_i['cy']),
                        'texts': [i['text'] for i in items
                                  if '命运预言' in (i.get('text') or '')][:2]})
            # 2026-10-27 用户说明：这个弹窗只在他身上挂着 SS 级预言时才出现
            #   （数据表 Foretell：SS 档 7 种，Duration 一律 1-1 = 只生效 1 张图
            #     => 每次拿到 SS，下一张图进图前必然弹一次 => 感觉像突然冒出来）
            #   旧代码对这条路径完全静默 => 用户只能看到 enter: timeout
            say('       - 「命运预言」前置弹窗 => 点「确定」继续进图')
            return 'handled'
        log.append({'popup': 'destiny_no_ok_btn',
                    'texts': [i['text'] for i in items][:10]})
    # ⭐⭐⭐⭐ 2026-10-15 **预言石板提前认出来**（用户报「预言石碑没有正常领取」）
    #   ---- 病（真机铁证 `runs/acc3/loop/loop_log.json`，map 14）----
    #     [799] `solver.order = ["1,4","3,3","1,6","3,6"]`  ← `3,6` 是预言石碑
    #     [825] `taps = [["1,6",…], ["3,6", 5.4, true, "S10003_013", 1]]` ← **点了它** ✓
    #     [826] `{"finish":"panel_rendering_wait","cell":"3,6","dim":0.253}`
    #            ⇒ 面板**正在渲染**（棋盘压暗、字还没画出来）⇒ 决定"再等一轮" ✓
    #     [828] `{"newequip_back":"popup","at":[360,835]}`  ← ⛔ **被当"新装备"点掉** ✗✗
    #     [834] `blank_board` ⇒ 计划走完 ⇒ 收工（预言石碑**一次都没轮到** ✗）
    #   ---- 为什么：`popups()` 里的**先后顺序** ----
    #     ① `close_newequip(...)`（**先**跑）⇒ 命中就点「返回」+ `return 'handled'` ✗
    #     ② `prophecy` 支（已有 `_is_foretell_panel` 守卫 ✓ —— 但**排在 ① 后面**）
    #     ④ `L['special']`（L≈6620）→ `预言石碑` → `foretell_flow`（**最后**）
    #     ⇒ 只要 ① 命中，② 和 ④ **永远到不了** ✗（与 10-10 那次"死代码"同一族）
    #   ---- ⚠ 诚实记账：我没能复现 ① 的误判 ----
    #     三种真机帧上跑过 `is_reward_panel` / `close_newequip`：
    #       渲染中（`r_232712_0.png`）⇒ False
    #       已画好（`spec_dev/foretell_panel2.png`，`_is_foretell_panel=True`）⇒ False
    #       面板前干净图 ⇒ False
    #     ⇒ `[828]` 那次是在**某个我没抓到帧的画面上**触发的
    #       （`popups()` 命中就 `return 'handled'`、**不落 OCR 全文** ⇒ 日志有盲区 ✗）
    #   ---- 修法（**用户选定**：「把预言石板判定提到 close_newequip 之前」✓）----
    #     ⛔ **不是**在这儿 `return`（那样会把下面 L≈6620 的 `foretell_flow` 也挡住 ✗
    #        —— 我第一版就是这么写的，写完当场发现是**把 bug 换了个形式** ✗）
    #     ⇒ 正解：**算一次判据，喂给下面那个"关闭类"分支当守卫** ——
    #       · 预言石板 ⇒ `close_newequip` **跳过它**（`_stele` 为真 ⇒ 调都不调 ✓）
    #       · 控制流**继续往下走** ⇒ `prophecy` 支（已有同款守卫）⇒ 最后到
    #         `L['special']` 那支 ⇒ `foretell_flow` **正常接住** ✓
    #     ⚠ 判据本身**不动**（`_is_foretell_panel` 在真机面板帧上已验证 =True，
    #       且不会被「藏宝/丰收」等卡片正文骗到 ✓）
    #     ⚠ **不删** `close_newequip` 对"真·新装备"的处理（那条路照常 ✓）
    _stele = _is_foretell_panel(items)
    if _stele:
        log.append({'popup': 'foretell_kept',
                    'title': _panel_title_of(items),
                    'note': '预言石板 ⇒ **不当弹窗关**，留给下面 foretell_flow ✓'})
    # ⭐「发现莱姆！」先处理（揭格/补点后可能弹，不处理会挡住后面的所有判断）
    #   ⚠ 2026-10-02：`lime_back()` 已是**写死坐标**（0ms），判据必须**窄** ——
    #     只认 OCR 读到的标题。⛔ **不用 `panel_seen` 兜底**（用户当场指出：
    #     「找莱姆的只在退出地图前最后那一次点击后啊，怎么刚进图就找莱姆了」）✗
    #
    # ⛔⛔⛔ 2026-10-12 **修「为什么会连续出现获得莱姆的点击」**（用户报，原话 ✗）
    #   ---- 病 ----
    #     判据是 `fb(items, *L['lime'])` —— 而 `fb` 是**子串**匹配 ✗
    #     `L['lime'] = ('莱姆', '发现莱姆')` ⇒ **任何含「莱姆」二字的 OCR 条目**
    #     都会命中 ⇒ 不只是那个弹窗 ✗✗
    #   ---- 真机铁证（`runs/gui_20261012_125244.log` + `runs/loop/loop_log.json`）----
    #     #14 plan order ["1,6","3,1","5,4"]        ← 计划剩的一步是 `5,4`
    #     #11 board["5,4"] = ['013', '预言石碑', 0.998, 0.65]   ← `5,4` 是**预言石碑**
    #     #29 {"finish": "panel_rendering_wait", "cell": "5,4", "dim": 0.268}
    #         ⇒ 点了预言石碑 ⇒ 弹**预言石板面板**（正在画）
    #     #31/#34/#37/#40 {"popup": "lime_back", "at": [359,873]}  ← **连判 4 次"莱姆"** ✗
    #     #41 {"loop_guard": "same_action", "n": 4} ⇒ 脱困
    #     ⇒ 崩（退出码 1）
    #   ---- 为什么预言面板会命中 ----
    #     预言石板面板上有**「元素」预言卡**，其效果文字（数据表 `Foretell`）是：
    #         「地图中至少出现 1 只**莱姆**，并且所有莱姆至少是蓝色位阶。」
    #       ⇒ 面板上**真的印着「莱姆」二字** ⇒ 子串匹配必中 ✗✗
    #     ⚠ 同一族还有「精灵」预言：`多格地块结算时至少有 N 只莱姆。` ✗
    #     ⚠ 与我 10-11 修的「预言石碑被错派成勇者之墓」**是同一个根因**：
    #        `fb` 子串匹配会被**卡牌效果正文**骗到 ✗（那次命中的是「勇者之墓」✓）
    #   ---- 修法：标题必须**独立成条**（与 `_panel_title_of` 同一口径 ✓）----
    #     弹窗标题在 OCR 里是**自己一条**（`'发现莱姆！'` / `'莱姆'`），
    #     而卡牌正文是**一长句**（含逗号/句号/方括号）⇒ 用"**完全相等**"区分 ✓
    #     ⚠ 保留**两种**允许形态：`'发现莱姆！'`（实测标题）与 `'莱姆'`（旧记录）✓
    #     ⚠ fail-open：相等判据更严 ⇒ 真弹窗**必须**能命中它原来的字面
    #       ⇒ 实测标题是 `发现莱姆！` ⇒ 一定要留它 ✓
    _lime_title = _lime_popup_title(items)
    if _lime_title is not None:
        lb = lime_back(items)
        if lb:
            _tap(b, lb['cx'], lb['cy'], wait=1.8)
            log.append({'popup': 'lime_back', 'at': (lb['cx'], lb['cy']),
                        'fixed': True, 'title': _lime_title})
            say('       · 发现莱姆！→ 点返回')
            status('遇到莱姆 · 返回')
            return 'handled'
    # ⭐「获得新装备！」（2026-09-26 用户报卡住）：打完大拇指地块 / 补点发现莱姆点都可能弹，
    #   它盖住整盘 ⇒ 后面的地块分类全是暗格 ⇒ 一路空转到退图超时 ✗
    # ⛔⛔ 2026-10-15 **加 `_stele` 守卫**（用户报「预言石碑没有正常领取」）：
    #   预言石板面板**不许**走这支（否则被点「返回」关掉 ⇒ `foretell_flow` 永远到不了 ✗）
    #   详见本函数开头那段"预言石板提前认出来"的长注释 ✓
    #   ⚠ 守的是**面板类型**，不是"新装备"那条路 —— 真·新装备照常处理 ✓
    if not _stele and close_newequip(b, items, log, 'popup'):
        if _PANEL_STUCK.get('newequip_popup', 0) >= 2:
            # 连着两次都关不掉 ⇒ 别再占着闭环（交给整盘暗格那套兜底处理）
            log.append({'popup': 'newequip_give_up'})
            return 'none'
        say('       · 获得新装备！→ 点返回')
        status('拿到新装备 · 返回')
        return 'handled'
    # ⭐「预言石板」等占卜面板（用户 2026-09-26）：**点中间最下面**关掉 + **拉黑这格** ✓
    #
    # ⛔⛔⛔ 2026-10-10 **第三处"预言石碑到不了 foretell_flow"的死代码**（用户报
    #   「图上有预言石碑，试一试」时，我的门禁 `verify_foretell_path.py` 当场抓到）：
    #   真机实测（帧 `runs/acc1/fst_opened.png`，OCR 读到「预言石板」conf=0.99）：
    #       `popups()` 走的是**本支** ⇒ `universal_close` 点 (360,1219) 关面板
    #       ＋ `block_cell(...)` **把那一格拉黑**（"以后不再点"）
    #       ⇒ 日志：`{'universal_close': 'prophecy', ...}` + `{'cell_blocked': 'prophecy'}` ✗
    #       ⇒ **`foretell_flow` 永远到不了**（它在下面 `for t in L['special']` 那支，行 ~790）
    #   为什么原来这么写：写本支时（2026-09-26）**预言石碑还没有 flow** ⇒
    #     "关掉 + 拉黑"就是当时唯一能做的 ✓ —— **现在 `foretell_flow` 有了，该让它接管** ✓
    #   ⇒ 修法：**`预言石碑` 不在这里处理**（跳过本支，交给下面 `L['special']` 那支）✓
    #     ⚠⚠⚠ **`预言石碑` 和 `预言石板` 是同一个面板的两个名字**（我第一版只排除了「石碑」
    #       ⇒ 守卫**恒为 True** ⇒ 没生效 ✗，被门禁 `verify_foretell_path.py` 当场抓出）：
    #          · 图上的**方块名** = `预言石碑`（数据表 `Area_Spot.Name` ✓）
    #          · 面板**标题**     = `预言石板`（真机 OCR 实测 conf=0.99 ✓）
    #       ⇒ 两个名字**必须都排除** ✓
    #     ⚠ 其余占卜类（`占卜`）**保持原样**（没有 flow ⇒ 还是"关掉+拉黑" ✓）
    #   ⭐ 2026-10-15：判据**复用本函数开头算好的 `_stele`** —— 不在这里重算 ✗
    #     （两处各调一次 `_is_foretell_panel` 是**重复计算**，且日后容易只改一处 ✓）
    if fb(items, *L['prophecy']) and not _stele:
        universal_close(b, log, items=items, probe=L['prophecy'][0], where='prophecy',
                        at=tapped)
        block_cell(log, ctx.get('flags'), tapped, 'prophecy')
        say('       · 预言石板 → 点中间最下面关掉，并拉黑这格（以后不再点）')
        status('触发预言石板 · 已跳过这格')
        return 'handled'
    if fb(items, *L['low']):
        return 'insufficient'
    # ⭐⭐ 2026-09-26 修（**这是"没打 boss 就退图"的根因**）：
    #   原来判据只有 `【正面】/【负面】 and 战斗胜利/失败` —— 但**有些结算面板不显示
    #   【正面】/【负面】**（实测 runs/m0_r008.png：面板上只有「战斗胜利 / 回放战斗 / 关闭」）
    #   ⇒ 这里判不成结算面板 ⇒ 一直走到函数尾巴 `return 'none'`
    #   ⇒ 棋盘被面板盖住 ⇒ `marks` 扫描读不到 boss 标记 ⇒ 误判 `finish: targets_done`
    #   ⇒ **boss 没打就退图** ✗（用户 2026-09-26 报「第一把没打到 boss 关就退了」）
    #   ⇒ 改成和 `wait_end()` 里 `on_result` **同一套判据**（那边早就修过了 ✓）：
    #      ①（【正面】/【负面】 and 胜负）  ② 底部「关闭」  ③ 「回放战斗」
    _res = bool(fb(items, *L['desc']) and fb(items, L['win'], L['lose'])) \
        or bool(bottom_close(items)) or bool(fb(items, '回放战斗'))
    if _res:
        # 结算面板：把所有按钮文字落盘（含幸运草/摇色子相关），供实现摇色子用
        log.append({'popup': 'result_panel',
                    'buttons': [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy']}
                                for i in items if i['cy'] > LAYOUT.sy(600) and len(i['text']) <= 8],
                    'texts': [i['text'] for i in items][:30]})
        # ⭐⭐⭐ 2026-10-02 **残留结算面板也要摇色子**（用户连报的那个 bug 的另一半）
        #   真机铁证 `runs/loop/loop_log.json`（19:48 那把）顺序：
        #     #43 popup:fight_panel(cell_marks=['recommend'])
        #     #45 battle:not_started                       ← 「战斗」点了没确认开起来
        #     #50 popup:result_panel                       ← **本分支**：屏幕上出现了结算面板
        #     → 旧代码在这里**直接关掉面板、一次都没摇色子** ✗✗
        #   根因：结算面板的**两个入口**里，只有战斗分支那个（`already_result_panel`）会摇，
        #     而"面板是战斗结束后才自己冒出来"这条走的是本分支 —— 这里**没有 mk / tapped**，
        #     格子的关联已经丢了 ⇒ 只能靠上一轮存进本图状态（`ctx['flags']` 就是 `st`）的
        #     `dice_pending`（见 `battle: blocked` 那一处）来补 ✓
        #   ⚠ 摇完**立刻清标记**：绝不让第二个出口（或下一轮）再摇一遍 ⇒ 白耗幸运草 ✗
        _fl = ctx.get('flags')
        if isinstance(_fl, dict) and _fl.get('dice_pending'):
            _pend = list(_fl.get('dice_pending') or [])
            _fl['dice_pending'] = None
            if 'recommend' in _pend:
                log.append({'dice': 'pending_result_panel', 'marks': _pend,
                            'note': '残留结算面板 ⇒ 补摇色子（来自上一轮 battle:blocked）'})
                try:
                    handle_dice(b, log, items, st=(ctx or {}).get('flags'))
                except Exception as _hd:            # noqa: BLE001
                    log.append({'dice': 'flow_err', 'e': repr(_hd)[:80]})
        cl = bottom_close(items)
        if cl:
            _tap(b, cl['cx'], cl['cy'], wait=2.5)
            log.append({'popup': 'result_closed', 'at': (cl['cx'], cl['cy'])})
            # ⭐ 2026-10-05：结算面板刚关掉 ⇒ 立刻查一次「获得新装备！」
            #   （同 `wait_end` 那个出口，用户口径见 `check_newequip_after_battle`）
            check_newequip_after_battle(b, log, 'battle_popup')
            return 'handled'
        # ⭐ 确实认到是结算面板却没量到「关闭」⇒ 交给 universal_close（内部按战斗面板
        #   点实测的关闭坐标 (577,1439)，**不会点开始冒险** ✓）——别再 return 'none' 干耗 ✗
        universal_close(b, log, items=items, where='result_no_close_btn')
        log.append({'popup': 'result_closed_fixed'})
        check_newequip_after_battle(b, log, 'battle_popup_fixed')
        return 'handled'
    img = b.img()

    def near():
        if not tapped:
            return []
        r0, c0 = cell_of(tapped[0], tapped[1])
        # ⭐ 2026-09-25 用户口径：「判断摇不摇色子直接看这个地块有没有对应标记」
        #   ⇒ **本格精确命中优先**（原来只在 ±1 邻域里挑最近的，本格没扫到标记时会误取邻格的）
        exact = markers.get((r0, c0))
        if exact is not None:
            return list(exact.get('marks') or [])
        hit, best = [], 99
        for (r, c), v in markers.items():
            d = max(abs(r - r0), abs(c - c0))
            if d <= 1 and d < best:
                best, hit = d, v['marks']
        return list(hit)

    # ⭐ 敌方预览面板「偶遇强敌 / 遭遇强敌」（2026-09-25 用户报卡在这里）：
    #   面板：标题(542,243) + 右上角 X(988,244) + 敌人名 + 底部「邀请挑战」(297,1587)
    #   用户口径变更（2026-09-25 晚）：**不打，关掉就行**（先前说过"遇到就打"，以本次为准）
    if fb(items, *L['strong']):
        mk = near()
        log.append({'popup': 'strong_panel', 'cell_marks': mk})
        x = find_x(items)
        if x:
            _tap(b, x['cx'], x['cy'], wait=1.5)
        else:
            close_x_panels(b, img)
        log.append({'skip': 'strong_closed', 'tapped': tapped, 'marks': list(mk),
                    'closed_at': (x['cx'], x['cy']) if x else None})
        say('       · 偶遇强敌 → 不打，关掉')
        status('遇到强敌 · 已避开')
        return 'handled'

    # ⭐⭐ 派遣探索面板（用户 2026-09-26 实测口径，**2026-10-01 用户明确要保留**）：
    #   点「探索」后弹出「探索配队」面板 ⇒ 一键派遣(891,1507) ⇒ 按钮变「开始探索」
    #   ⇒ 再点 (875,1507) ⇒ 上方一个格子被填（出现倒计时 ✓）
    #   ⚠ 必须在战斗分支之前判（该面板与地块面板一样，别掉进别的分支 ✗）
    #   ⚠⚠ 2026-10-01 我一度按"不点一键派遣"把这一整块删掉 ✗ —— 那是**误读**：
    #      用户说的「刚刚脚本不点派遣」是在报 **bug 现象**（它该点却卡着没点），
    #      不是口径。用户随后明确：「**恢复原逻辑：要点一键派遣**」⇒ 本块按原样保留 ✓
    if EXPLORE_DISPATCH and any(fb(items, k) for k in ('探索配队', '一键派遣',
                                                 '键派遣', '开始探索')):
        # ⭐ 槽位满了 ⇒ 不能派遣（用户：探索满了还在探索 ✗）⇒ 关掉面板 ✓
        if int(ctx.get('slots_free', 1) or 0) <= 0:
            log.append({'dispatch': 'skip_slots_full'})
            say('       · 三个探索槽已满，关掉派遣面板（不派遣 ✓）')
            status('三个小队槽已满 · 收起面板')
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.5)
            else:
                back = find_button(items, '返回', '取消', '关闭', maxlen=4)
                if back:
                    _tap(b, back['cx'], back['cy'], wait=1.5)
                else:
                    # ⭐ 2026-10-02 修 1080p 残留：(275,1507) 是**参考系旧值**，
                    #   在 720×1280 屏上 y=1507 **超出屏高 1280** ⇒ 必然点空 ✗
                    #   ⇒ ×2/3 折算 = (183,1005)；交叉验证：y=1005 与
                    #     `REF['dispatch_btn']`(891,1507)→(594,1005) **同一行**，
                    #     x=183 与 `REF['explore_btn']`(275,736) 同列 ⇒ 系数正确 ✓
                    _panel_tap(b, 183, 1005, 'norm', log=log, what='返回(兜底)')
            return 'handled'
        _gone = False
        it2 = None          # ⭐ 初始化：下面 `if _try and it2` 与收尾的 find_x/n_free 都要读它
        for _try in range(2):
            # ⭐⭐⭐ 2026-10-01 用户报「点搓（错）一键派遣位置了」⇒ **改用 OCR 现读的按钮坐标**：
            #   面板 OCR 里本来就有那颗按钮（真机实测读到 `键派遣`、`开始探索`）✗
            #   而代码却一直去点**写死的** `DISPATCH_BTN=(891,1507)` ——
            #   那个值是 PC 归一化系的旧标定，在真机上点不中（用户连报两次位置不对 ✗）
            #   ⇒ 现在**优先用 OCR 到的那颗按钮**（`it2`/`items` 里找），
            #     只有实在读不到文字时才退回标定常量（并有通道兜底 ✓）
            #   好处：与分辨率无关、与文案变化无关（键派遣/一键派遣/开始探索 都认 ✓）
            _btn_it = None
            # ⚠⚠ 2026-10-01 修 NameError：原来写 `for _src in (it2 if _try else items, items)`
            #   —— `it2` 只在**循环体末尾**（ocr_ch 之后）才赋值 ⇒ **首轮必然 NameError** ✗
            #   （被上层 `except Exception: pass` 吞掉 ⇒ 症状：派遣面板点了两下都关不掉，
            #    日志永远停在 dispatch 的第一条 ⇒ user 报「点不了一键派遣」）
            # ⇒ 第 1 轮只有 `items`；第 2 轮起才把上一轮 OCR 到的 `it2` 也纳入候选
            #   （面板文字会变：键派遣 → 开始探索，所以每轮仍会重新 OCR）。
            _src_list = [items]
            if _try and it2:
                _src_list.insert(0, it2)
            for _src in _src_list:
                for _it in (_src or []):
                    _t = (_it.get('text') or '').strip()
                    if ('派遣' in _t or '开始探索' in _t) and '预计时间' not in _t:
                        # 取**最靠右下**的那颗（面板底部主按钮 ✓）
                        if _btn_it is None or (_it.get('cy', 0), _it.get('cx', 0)) > \
                                (_btn_it.get('cy', 0), _btn_it.get('cx', 0)):
                            _btn_it = _it
                if _btn_it is not None:
                    break
            if _btn_it is not None:
                _bx, _by = int(_btn_it['cx']), int(_btn_it['cy'])
                # ⭐⭐⭐ 2026-10-01 **通道同源**（我上一次又在这里串味了 ✗）：
                #   `_btn_it` 来自 `ocr_ch()` ⇒ 它**跟着 `_OCR_CH['dlg']` 走**
                #   （dlg=False ⇒ 归一化帧坐标；True ⇒ 弹窗系坐标）。
                #   我上次写死 `tap_dlg` ⇒ 归一化坐标 + 弹窗通道 ⇒ 真机偏 C≈209px ✗
                #   真机实证（21:11）：`btn_by_ocr 键派遣 @(891,1350)` → tap1 后按钮变
                #   「开始探索」（说明第 1 击其实点中了），但第 2 击落到别处 ⇒ 状态弹回
                #   ⇒ `still_open_close`（面板两次都关不掉）✗
                #   ⇒ **必须用 `_tap()`**（它按 `_OCR_CH['dlg']` 自动选通道 = 同源 ✓）
                log.append({'dispatch': 'btn_by_ocr', 'text': _btn_it.get('text'),
                            'at': (_bx, _by), 'try': _try + 1,
                            'ch': 'dlg' if _OCR_CH['dlg'] else 'norm'})
                say('       · 一键派遣 → 点 OCR 读到的「%s」(%d,%d)（%s 通道 ✓）'
                    % ((_btn_it.get('text') or '')[:8], _bx, _by,
                       '弹窗帧' if _OCR_CH['dlg'] else '归一化帧'))
                _tap(b, _bx, _by, wait=2.5)
            else:
                # 兜底：读不到按钮文字 ⇒ 用标定常量（`_panel_tap` 会验证生效并自动换通道 ✓）
                log.append({'dispatch': 'btn_by_const', 'at': DISPATCH_BTN,
                            'try': _try + 1})
                say('       · ⚠ 没读到派遣按钮文字 ⇒ 退回标定坐标 %s' % (DISPATCH_BTN,))
                _panel_tap(b, DISPATCH_BTN[0], DISPATCH_BTN[1], 'norm', log=log,
                           what='一键派遣(标定)')
            it2 = ocr_ch(b, min_conf=0.2, tag='dispatch')
            t2 = [i['text'] for i in it2]
            log.append({'dispatch': 'tap%d' % (_try + 1), 'texts': t2[:8]})
            if not any(('探索配队' in x) or ('开始探索' in x) or ('派遣' in x) or
                       ('探索预计时间' in x) for x in t2):
                _gone = True
                break
        if not _gone:
            # ⚠ 点了两次面板还在 ⇒ 别再点了 ✗（用户报「一直点探索」就是这个）
            log.append({'dispatch': 'still_open_close'})
            say('       · 派遣面板点了两次还在 ⇒ 关掉它，不再重复点 ✓')
            x = find_x(it2)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.5)
            else:
                back = find_button(it2, '返回', '取消', '关闭', maxlen=4)
                if back:
                    _tap(b, back['cx'], back['cy'], wait=1.5)
                else:
                    # ⭐ 2026-10-02 修 1080p 残留：(275,1507) 是**参考系旧值**，
                    #   在 720×1280 屏上 y=1507 **超出屏高 1280** ⇒ 必然点空 ✗
                    #   ⇒ ×2/3 折算 = (183,1005)；交叉验证：y=1005 与
                    #     `REF['dispatch_btn']`(891,1507)→(594,1005) **同一行**，
                    #     x=183 与 `REF['explore_btn']`(275,736) 同列 ⇒ 系数正确 ✓
                    _panel_tap(b, 183, 1005, 'norm', log=log, what='返回(兜底)')
            return 'handled'
        n_free = sum(1 for i in it2 if '空闲' in i['text'])
        say('       · 已派遣一支探索队（上方还剩 %d 个空闲槽）' % n_free)
        status('已派出小队（还剩 %d 个空位）' % n_free)
        return 'handled'

    # ⭐⭐ 2026-09-26 用户口径：**三个探索格子有空闲时，紫/橙探索地块要点左边「探索」**
    #   实测面板同时含「探索产出(274,443)」与「战斗事件(806,442)」⇒ 必须先判探索 ✓
    #   否则会掉进下面的战斗分支、点成右边的「战斗」✗（用户当场抓到 ✗）
    # ⭐ 判据：**用当前点击位置现算** sid（原来用 st['tapped_sid'] 是上一轮的值 ✗ 导致
    #   紫橙探索格被当成普通格打了战斗 ✗ —— 用户 2026-09-26 报）
    _ev_tiles = ctx.get('ev_tiles') or []
    _tapped_sid = ''
    try:
        _tapped = ctx.get('tapped')      # ⭐ 改名 _tapped：原局部 `_tap` 遮蔽模块级
        _cst = ctx.get('st') or {}       #   点击函数 _tap ⇒ X 关闭分支 TypeError 崩溃
        if _tapped and _cst:
            _tc = cell_of(_tapped[0], _tapped[1])
            _tapped_sid = str((_cst.get(_tc) or {}).get('sid') or '')
    except Exception:       # noqa: BLE001
        _tapped_sid = ''
    _purple_suffix = set(getattr(spots_mod, 'EXPLORE_SUFFIX', ('221', '321', '331')))
    _is_purple = _is_purple_cell(_tapped_sid, (ctx.get('st') or {}).get('ev_tiles'),
                                 ctx.get('tapped'))
    if _is_purple and not (('_' in _tapped_sid)
                           and (_tapped_sid.split('_')[-1] in _purple_suffix)):
        try:
            log.append({'explore': 'purple_by_ev_tiles',
                        'cell': '%d,%d' % cell_of(*(ctx.get('tapped') or (0, 0))),
                        'top_sid': _tapped_sid,
                        'note': '顶层 sid 是垃圾猜测 ⇒ 以本轮 ev_tiles 判定为准 ✓'})
        except Exception:       # noqa: BLE001
            pass
    # ⭐ 槽位满了 ⇒ 不走探索 ✓（落到下面的战斗分支 ⇒ 打掉它 ✓ 用户 2026-09-26）
    _free_now = int(ctx.get('slots_free', 1) or 0)
    if (EXPLORE_DISPATCH and _is_purple and _free_now > 0
            and (fb(items, L['expl'])
                 # ⭐ v0.32：真机上「探索产出」标题（dlg≈443）落弹性区看不见 ⇒
                 #   用看得见的「探索」按钮（dlg≈735）进分支（仅 C>0 生效）
                 or (dlg_c() and _dlg_panel_btn(ditems, L['ebtn'])))):
        # ⭐ v0.31 方案 B：面板按钮 y 带是弹窗系标定 ⇒ 用 +C 后的条目筛、tap_dlg 点
        act = None
        for it in ditems:
            if L['ebtn'] in it['text'] and L['expl'] not in it['text'] and it['cy'] > LAYOUT.sy(620):
                act = it
                break
        # ⛔⛔⛔ 2026-10-02 修「紫橙格一直点探索点不动」（用户原话「只是一直点探索格子」）
        #   现象：紫金块能点开，但每轮都点 (275,736)，面板永远关不掉，一路点到 round 42。
        #   真机日志（runs/evchk）：#2/#6/#10/#14 都是 `{"popup":"fight_panel"}`，
        #   而 `{"explore":"first_fixed_btn","at":[275,736]}` 反复出现；
        #   `stamina` 全程 1834 纹丝不动 ⇒ 一格没推进。
        #   根因：`(275, 736)` 是 **1080p 系的旧标定值**（同批的 FIGHT_Y=735 /
        #   DISPATCH_BTN=(891,1507) 都已折算，唯独这个**漏改了**）。
        #       正确的「探索」按钮 = `fixed.A('explore_btn')` = **(183, 491)**（720 设备系）
        #       736 − 491 = **245 像素** ⇒ 那个位置在战斗面板上是**空的**，
        #       点下去**什么都不发生** ⇒ `panel_gone` 永远 False ⇒ 永远判「没生效」✗✗
        #   ⇒ 统一走 `fixed` 锚点（单一数据源，§4.2 铁律），不再写死 1080 系数值 ✓
        try:
            import fixed as _fx0
            _eat = (int(act['cx']), int(act['cy'])) if act else tuple(
                _fx0.A('explore_btn'))
        except Exception:                                   # noqa: BLE001
            _eat = (int(act['cx']), int(act['cy'])) if act else (183, 491)
        # ⭐⭐⭐ 2026-09-30 真机事故修复（用户报「明明探索格子满了，还一直点探索」）：
        #   旧版**点完直接 return handled、不验证** ⇒ 游戏侧槽位满时点「探索」**毫无反应、
        #   地块面板不关** ⇒ 下一轮又看到同一个面板、又点一次……
        #   真机日志实证：连续 18 轮 `{'explore': 'first_high_value', 'at': (274, 790)}`，
        #   整张图 105 秒 0 战斗 0 装备（25 体力白花，只能人工停 ✗）。
        #   ⇒ 与下面「探索产出」分支同口径：**点完必须验证游戏有没有受理**：
        #       面板关掉/换成「探索配队」⇒ 受理了 ⇒ 空闲槽 -1 ✓
        #       面板还在 ⇒ 没受理（槽其实是满的）⇒ 计数；连两次 ⇒ 判满本图 ✓
        b.tap_dlg(_eat[0], _eat[1], wait=3.0)
        _n_ex = (_PANEL_STUCK.get('expl') or 0) + 1
        _PANEL_STUCK['expl'] = _n_ex
        log.append({'explore': 'first_high_value' if act else 'first_fixed_btn',
                    'at': _eat, 'n': _n_ex, 'slots_free': _free_now})
        if panel_gone(b, L['expl'], dlg_btn=L['ebtn']):
            _PANEL_STUCK['expl'] = 0
            # ⭐ 2026-10-02：**受理了 ⇒ 把"连续点不动"的跨轮计数清零** ✓
            _fl_ok = ctx.get('flags')
            if isinstance(_fl_ok, dict):
                _fl_ok['expl_no_effect'] = 0
            # ⚠ **不在这里改 slots_free**：面板关掉只代表游戏受理了这下（多半换成
            #   「探索配队」面板，真正派遣在下面的 A 分支）⇒ 提前 -1 会让 A 分支
            #   把配队面板当成"槽满"关掉 ✗。空闲数一律以**下一轮轮首 HUD 读数**为准 ✓
            say('       · 点「探索」(%d,%d) → 事件进格子' % _eat)
            status('派出一支小队 · 探索中')
            return 'handled'
        if _n_ex < 2:
            say('       · 点了「探索」(%d,%d) 面板没关（第 %d 次，可能动画没走完）'
                % (_eat[0], _eat[1], _n_ex))
            return 'handled'
        # ⭐ 连点两次都没反应 ⇒ **可能**没有空闲槽（HUD 读数错了）⇒ 记满本图
        #   ⚠⚠⚠ 2026-10-02 补安全门：原来是**无条件** `_set_slots_free(ctx, 0)`，
        #     只要「点两次面板没关」就断定槽满 ⇒ 误判。
        #     真机反例（gui_20261002_163733）：`slots_free: 2`（**明明有 2 个空槽**），
        #     却连着几轮 `slots_full_latched` ⇒ 紫橙格全被送去「改开打」，
        #     而战斗分支又因为那格已被拉黑开不起来 ⇒ **卡在「一直点探索」** ✗✗
        #     ⇒ 现在：**只有 HUD 明确读到 0 个空槽**才认定「槽满」；
        #       读到 >0 却点不动 ⇒ 多半是**那一格点不动**（雾格/已被拉黑），
        #       **不要**推翻全局槽位读数，交给下一轮重试 ✓
        if _free_now is not None and _free_now > 0:
            # ⭐⭐ 2026-10-02：**这条"下轮再试"必须有上限** —— 真机实测（22:15 那把）
            #   这里连着 **24 轮**都是「HUD 说还有空槽 ⇒ 下轮再试」⇒ 一次都没推进、
            #   体力纹丝不动、纯空转 ✗（用户报「一直点紫探索」）
            #   ⇒ 跨轮计数（存**本图状态**）：连续 3 轮"点了没效果"就认满、改开打 ✓
            #     （真受理成功时上面已把该计数清零 ✓）
            _fl_ne = ctx.get('flags')
            _stk = 1
            if isinstance(_fl_ne, dict):
                _stk = int(_fl_ne.get('expl_no_effect', 0) or 0) + 1
                _fl_ne['expl_no_effect'] = _stk
            if _stk < 3:
                log.append({'explore': 'tap_no_effect_but_slots_free', 'n': _n_ex,
                            'slots_free': _free_now, 'streak': _stk,
                            'note': 'HUD 说还有空槽 ⇒ 不推翻槽位读数；'
                                    '连续 3 轮都没效果才认满（防空转）'})
                say('       · 点了「探索」没反应（连续第 %d 轮）；槽位显示还有 %d 个空 '
                    '⇒ 下轮再试' % (_stk, _free_now))
                _PANEL_STUCK['expl'] = 0          # 不算「槽满」，重新给机会
                return 'handled'
            say('       · 连续 3 轮点「探索」都没反应 ⇒ 这个 HUD 读数不可信，'
                '按「槽满」处理（本图改开打）')
            log.append({'explore': 'slots_full_by_streak', 'streak': _stk,
                        'slots_free_hud': _free_now})
        _set_slots_free(ctx, 0)
        _can_fight = _fight_panel_visible(items, ditems)
        log.append({'explore': 'slots_full_latched', 'taps': _n_ex,
                    'at': _eat, 'can_fight': _can_fight})
        say('       · 「探索」点了两次都没反应 ⇒ 探索槽确实是满的（本图改开打）')
        status('小队槽已满 · 这格改开打')
        if not _can_fight:
            # 这块面板连「战斗」都没有 ⇒ 下一轮的战斗分支也接不住 ⇒ 直接拉黑这格，
            # 免得在它身上来回空转（本图目标清完就正常退图 ✓）
            block_cell(log, ctx.get('flags'), tapped, 'explore_no_fight_btn')
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.4)
            else:
                close_x_panels(b, b.img())
        return 'handled'

    # ⭐⭐ v0.32 入口修复（真机 boss 面板点不到战斗的**真正根因**）：
    #   面板标题「战斗事件」dlg≈443 在真机落在 toRef 丢弃的弹性区 ⇒ 归一化帧看不见
    #   ⇒ fb(items,'战斗事件') 恒 False ⇒ 战斗分支**从来没进去过**（v0.27~v0.31 全白修）✗
    #   ⇒ C>0 时用看得见的独立「战斗」按钮（dlg≈735~791）进分支；
    #     严格相等匹配防「战斗胜利/回放战斗」误命中；PC/9:16 C=0 ⇒ 行为一字不变 ✓
    _fe_title = fb(items, L['fight'])
    _fe_btn = (not _fe_title) and bool(dlg_c()) and _dlg_panel_btn(ditems, L['fbtn'])
    # ⭐⭐⭐⭐ 2026-10-05 **紫/橙探索格 + 有空闲槽 ⇒ 必须先去探索，别掉进战斗分支**
    #   （用户第二次报「**修了个寂寞啊，和之前一模一样，没打探索格**」的真根因）
    #   真机证据链（`runs/acc1/` 第 5 张图，`runs/acc1/loop/loop_log.json`）：
    #     · `(3,1)` sid `S00003_221`（紫格，识别**正确** ✓）、`slots_free=1`（**有空槽** ✓）
    #     · 点它 ⇒ `changed=true`、round 条目记 `panel_via: "title"`
    #       ⇒ **面板被 5229 的战斗分支接住了**（它认到「战斗事件」标题）✗
    #     · 战斗分支里 `_is_purple=True` 但 `_free_now=1>0` ⇒ **5235 那条"槽满才打"不成立**
    #       ⇒ `mk=[]` ⇒ 掉进 `if not mk:`（5241）按"不在路上/不在计划里"判
    #       ⇒ **面板被关掉：既没探索、也没打** ✗✗
    #     · 日志实证：那一局**探索/派遣事件 0 条** ✓ 随后 `targets_done` 带 6 个未处理内容退图 ✗
    #   ⇒ 根因是**分支优先级**：探索分支的门是 `fb(items,'探索产出')`（标题「探索产出」），
    #     而这一格的面板被识别成「战斗事件」标题 ⇒ 两条门都只看标题、**这个面板只命中了后者** ✗
    #   ⇒ 现在：**紫/橙格 + 有空闲槽** ⇒ 在战斗分支最前面**直接走探索**（改开打只留给槽满 ✓）
    #     ⚠ 用与探索分支**同一个判据** `_is_purple_cell()`（顶层 sid 是垃圾猜测时靠 ev_tiles ✓）
    if _is_purple and _free_now > 0 and EXPLORE_DISPATCH and (_fe_title or _fe_btn):
        log.append({'popup': 'purple_prefer_explore', 'cell': '%d,%d' % cell_of(*tapped)
                    if tapped else None, 'tapped_sid': _tapped_sid,
                    'slots_free': _free_now, 'entry': 'title' if _fe_title else 'dlg_btn',
                    'note': '紫/橙格 + 有空闲槽 ⇒ 走探索，不进战斗分支 ✓'})
        say('       · 紫/橙探索格（有空闲槽 %d）⇒ 走探索，不按战斗处理 ✓' % _free_now)
        status('紫金地块 · 去派小队')
        # 落到下面 5490 的探索分支去处理 ✓
    elif _fe_title or _fe_btn:
        mk = near()
        # ⭐ 2026-09-26 用户口径（原话「满了后就改成战斗」）：
        #   探索槽**满了**时的紫/橙探索格（ID 后缀 221/321/331）⇒ **直接打掉** ✓
        #   ⚠ 不补这一条的话，它会掉进下面「不在路上 ⇒ 不打」的分支 ⇒ 面板只是被关掉
        #     ⇒ 既没探索也没打 ⇒ 还是白点一下 ✗（离线测 slots_free=0 就是 offroad_fight）
        if _is_purple and _free_now <= 0:
            mk = list(mk) + ['explore_full_fight']
            log.append({'popup': 'fight_panel_explore_full',
                        'slots_free': _free_now, 'tapped_sid': _tapped_sid})
        log.append({'popup': 'fight_panel', 'cell_marks': mk,
                    'entry': 'title' if _fe_title else 'dlg_btn'})
        if not mk:
            # ⭐ 用户 2026-09-25：**跟「接近 boss」无关的战斗格一律不打**。
            #   只有落在「出生地 → 待处理标记格」路上的那格才打（它挡着路，打掉才能连锁揭示）；
            #   其他内容格弹出来的战斗面板直接关掉（旧版只要 marked 非空就打 → 白打乱打）。
            road = set(ctx.get('road') or [])
            on_road = bool(tapped and (tapped in road or any(
                abs(tapped[0] - q[0]) <= GRID['cx'] and abs(tapped[1] - q[1]) <= GRID['cy']
                for q in road)))
            # ⭐⭐⭐ 2026-09-28 修「点了 33 却没点到开始战斗」（用户真机报，图二实锤：
            #   solver plan=['2,7','3,3','3,1'] ⇒ 点 (3,3) 弹 fight_panel ⇒ 被
            #   offroad_fight 关掉（closed=2）⇒ 格没清、后面点序全乱 ✗）：
            #   **计划内**的格弹出战斗面板 ⇒ 必打 —— solver/EffPolicy 已做过
            #   「绕开更贵」的权衡，它挡着计划；旧口径只认启发式 road_all ⇒
            #   计划内的开路战斗被误判"无关战斗" ✗。plan_road = 本轮计划执行步 ✓
            _proad = set(ctx.get('plan_road') or [])
            on_plan = bool(tapped and (tapped in _proad or any(
                abs(tapped[0] - q[0]) <= GRID['cx'] and abs(tapped[1] - q[1]) <= GRID['cy']
                for q in _proad)))
            # ⭐⭐ 2026-09-27 用户口径修正：
            #   「目标相邻的战斗格子**不是必打的**，只有附加没有空格子能连接目标格子才会被迫打」
            #   ⇒ 旧口径「紧挨目标 ⇒ 必打」(near_target) 作废 ✗
            #   ⇒ 新判据：**这条路上还有空地块(1 体)可走 ⇒ 不打** ✓；确实没有 ⇒ 被迫打 ✓
            # ⭐⭐ 2026-09-27 修（用户报「点了 33 却没打掉这个战斗格」）：
            #   路是**有序**的（path_to 从出生点往外 ✓）
            #   ⇒ 只看"**在它之前**"那段路上还有没有空地 ✓
            #      （旧版只看"整条路上有没有空地" ✗ ⇒ 障碍两侧各有空地时误判成"不用打"✗
            #        结果点了却关面板 ⇒ 障碍没清掉 ⇒ 后面根本过不去 ✗）
            _road_seq = list(ctx.get('road') or [])
            _plain_road = list(ctx.get('plain_road') or [])
            _plain_left = False
            if tapped:
                _idx = None
                for _i3, _q in enumerate(_road_seq):
                    if (abs(tapped[0] - _q[0]) <= GRID['cx'] * 1.05
                            and abs(tapped[1] - _q[1]) <= GRID['cy'] * 1.05):
                        _idx = _i3
                        break
                if _idx is None:
                    _plain_left = bool(_plain_road)      # 不在路上 ⇒ 保守不动 ✓
                else:
                    for _q in _road_seq[:_idx]:           # 只看它**前面**那段 ✓
                        for _p in _plain_road:
                            if (abs(_q[0] - _p[0]) <= 1 and abs(_q[1] - _p[1]) <= 1):
                                _plain_left = True
                                break
                        if _plain_left:
                            break
            forced_fight = bool((on_road and not _plain_left) or on_plan)
            if not forced_fight:
                # ⚠ 2026-09-25 踩坑：残留的战斗面板（比如上一轮/手动留下的）会让循环原地打转
                #   （日志刷 `skip: offroad_fight` + `tapped: None`）—— 这里必须**确实关掉**
                n = close_x_panels(b, img)
                if n == 0:
                    x = find_x(items)
                    if x:
                        _tap(b, x['cx'], x['cy'], wait=1.5)
                        n = 1
                if n == 0:
                    c = exb(items, L['cancel']) or fb(items, '关闭') or exb(items, '返回')
                    if c:
                        _tap(b, c['cx'], c['cy'], wait=1.5)
                        n = 1
                if n == 0 and tapped is None:
                    # ⭐ 2026-10-02 修 1080p 残留：(493,1024)/225 全是**参考系旧值**
                    #   ⇒ 720 屏宽下 x=1024 **超出屏宽 720** ⇒ 必点空 ✗
                    #   ⇒ ×2/3 折算 = x 329/683、y 150；
                    #     交叉验证：329/683 == `layout.REF['close_x_left']/['close_x_right']` ✓
                    for bx in (329, 683):           # 只认这两个真关闭符位置
                        # ⭐ v0.31 方案 B：X 关闭符是**弹窗系**标定坐标 ⇒ tap_dlg
                        #   （真机上原 b.tap(·,225) 落在弹性区/顶块，点不到 ✗）
                        b.tap_dlg(bx, 150, wait=1.1)
                    n = 2
                log.append({'skip': 'offroad_fight', 'tapped': tapped,
                            'road': sorted(road)[:4], 'closed': n})
                return 'handled' if n else 'none'
        if not mk and ctx.get('clear_fights', 0) >= 3:
            close_x_panels(b, img)
            log.append({'skip': 'clear_path_capped',
                        'clear_fights': ctx.get('clear_fights', 0)})
            return 'handled'
        # ⛔⛔⛔ 2026-10-02 修「大拇指格不摇色子」的关键一刀
        #   真机存帧（runs/notstarted.png，18:50 那把，用户报的）：
        #       弹出的一看就是**已经打完的结算面板** ——
        #       「战斗胜利」横幅 + 点数 6 + 四叶草 1 + 奖励行（紫包/紫罐/卷轴/蓝宝石）
        #       面板上只有「回放战斗 / 关闭 / 自动跳过」，**没有「战斗」二字**
        #   而旧流程**假定「弹出战斗面板 = 还没打的战斗面板」** ⇒ 找不到「战斗」字样
        #   ⇒ 点写死的 (536,490) 空白处 ⇒ `battle: not_started` ⇒ `return 'blocked'`
        #   ⇒ **`start_fight` 根本没执行、`handle_dice` 根本没被调** ⇒ 不摇色子 ✗✗
        #   ⇒ 修法：**弹出时若已经是结算面板**，说明这场仗早就打完了 ——
        #     带 recommend 的直接进 `handle_dice`（摇色子），再关面板走人 ✓
        #     不带 recommend 的直接关面板 ✓
        if _is_result_panel_now(items, ditems, img=b.img()):
            log.append({'popup': 'already_result_panel', 'marks': list(mk),
                        'note': '弹出时已是结算面板 ⇒ 战斗早已打完，直接走结算流程'})
            # ⭐ 2026-10-02：这里已经按 `mk` 摇过了 ⇒ 把「待摇」标记清掉，
            #   免得 `_res` 那条路（或下一轮）对同一个结算面板**再摇一遍** ✗（白耗幸运草）
            _flr = ctx.get('flags')
            if isinstance(_flr, dict):
                _flr['dice_pending'] = None
            if 'recommend' in list(mk):
                try:
                    handle_dice(b, log, items, st=(ctx or {}).get('flags'))
                    # ⭐ 2026-10-02 提速审计：这里原来还有一句
                    #   `items = b.ocr(tag='dice_after')`（整屏 ≈0.9s）—— 而下面紧接着就是
                    #   `close_x_panels` + `return 'handled'`，**这个 `items` 再也没被任何代码读过**
                    #   ⇒ 纯浪费一次 OCR ⇒ 删掉 ✓（每次摇色子省 ~0.9s）
                except Exception as _hd:         # noqa: BLE001
                    log.append({'dice': 'flow_err', 'e': repr(_hd)[:80]})
            close_x_panels(b, b.img())
            log.append({'popup': 'result_closed_already'})
            return 'handled'
        btn = None
        # ⭐⭐ v0.31 方案 B（真机 boss 面板实锤：战斗钮弹窗系 y=791，归一化帧里只有 582
        #   ⇒ 原 y 带 650~860 在真机永远落空 ✗）：y 带筛选必须用 **+C 后的弹窗系条目** ✓
        #   （PC/9:16 C=0 ⇒ dlg_items 原样返回，行为一字不变）
        # ⚠⚠ 2026-10-02 修「boss 打不了」：这条 y 带是 **1080p 系的 650~860**，
        #   换 720p 基准时漏改 ⇒ 真帧实测「战斗」在 **cy=490**（720p 设备系）
        #   ⇒ 490 < 650 ⇒ **永远落空** ⇒ 一律走下面的兜底，而兜底又按
        #     1080p 的 (541, 735) 去点 ⇒ 点的位置**根本不在按钮上** ✗✗
        #   ⇒ 改成 `layout.REF['fight_band_y0/y1']` 同一数据源（400~573）✓
        _FBY0, _FBY1 = (LAYOUT.sy(layout_mod.REF['fight_band_y0']),
                        LAYOUT.sy(layout_mod.REF['fight_band_y1']))
        for it in ditems:
            t = it['text'].strip()
            if L['fbtn'] in t and len(t) <= 4 and _FBY0 <= it['cy'] <= _FBY1 \
                    and L['fight'] not in t:
                btn = it
                break
        if btn is None:
            # 用户 09-25 口径：**只有「首领」标记的地块**才是居中单块面板；
            # 其余（普通格 / 大拇指 / 幸运草 / 红装）都是左右两列面板
            # ⚠ 2026-10-02：下面这两个数原来是 **1080p 系的 (541, 806)**，
            #   在 720p 下**点在按钮外面** ⇒ 「战斗」点了没反应 ⇒ 判 not_started ✗
            #   ⇒ 改走 `layout.REF`（fight_x_boss=361 / fight_x_normal=537）✓
            if 'boss' in list(mk):
                btn = {'cx': LAYOUT.sx(layout_mod.REF['fight_x_boss']),
                       'cy': FIGHT_Y, 'text': 'boss-fixed'}
            else:
                anchors = [it for it in ditems if L['fight'] in it['text']]
                if tapped:
                    anchors.sort(key=lambda it: abs(it['cx'] - tapped[0]))
                a = anchors[0] if anchors else fb(ditems, L['fight'])
                btn = {'cx': a['cx'] if a else LAYOUT.sx(layout_mod.REF['fight_x_normal']),
                       'cy': FIGHT_Y, 'text': 'normal'}
            log.append({'popup': 'fbtn_pos', 'at': (btn['cx'], btn['cy']),
                        'marks': list(mk), 'band': (_FBY0, _FBY1)})
        if not start_fight(b, log, btn, mk):
            # ⭐⭐⭐ 2026-10-02 加：**战斗没开起来时自动存帧**（用户要求）
            #   起因：用户报「明明打的就是 boss 格子，怎么还弹『标记格打不开』」，
            #     但那一刻的**面板画面没存** ⇒ 无法判断「战斗」按钮到底在哪、
            #     面板长什么样 ⇒ 只能靠猜 ⇒ 猜了几轮都没定论 ✗
            #   ⇒ 现在：失败即刻存图 + 记下**按钮坐标/标记/格位**，
            #     下次跑完直接看图就能定论 ✓
            #   ⚠ 存**点完按钮之后**的那一帧（最关键：它显示点了没反应时的真实画面）
            try:
                _nf = b.snap('notstarted', save=True)
                log.append({'battle_notstarted_dump': _nf,
                            'btn': (btn.get('cx'), btn.get('cy')),
                            'btn_text': btn.get('text'),
                            'marks': list(mk), 'tapped': list(tapped or ()),
                            'cell': ('%d,%d' % cell_of(*tapped)) if tapped else None})
                say('       · 这一帧已存档（诊断用）：%s' % _nf)
            except Exception as _end:        # noqa: BLE001
                log.append({'battle_notstarted_dump_fail': repr(_end)[:80]})
            close_x_panels(b, b.img())
            # ⭐⭐⭐ 2026-10-02 修「能点开紫探索格了，却一直点探索不打架」
            #   现象（用户）：紫橙格能点开，但每轮都重复「点探索」，
            #   永远派不出小队，也永远不开打。
            #   真机日志（gui_20261002_163733 / runs/loop）：
            #       #9  {"popup":"fight_panel","cell_marks":[]}   ← 战斗面板开了，**无标记**
            #       #10 {"battle":"no_battle_in_5s"}              ← 5 秒没进战斗
            #       #12 {"battle":"unmarked_no_start","note":"普通格点不动 -> 拉黑这格"}
            #       #37 {"explore":"first_fixed_btn","n":2}       ← 之后每轮重试点探索
            #       #38 {"explore":"slots_full_latched"}          ← 误判「槽满」→ 死循环
            #   根因：下面 `if not mk:` **只看「标记」**判「普通格点不动」⇒ 拉黑。
            #         而**紫/橙探索格本来就不带标记**（它靠地块 ID 后缀识别）⇒
            #         每个紫橙格都会被误判成「普通格点不动」⇒ 当场拉黑 ⇒
            #         之后点它没反应 ⇒ 循环退回「点探索」分支 ✗✗
            #   ⇒ 修法：**紫/橙格不算「普通格」** —— 它是**目标**，点不动只当
            #     「这次没开起来」，**绝不拉黑**（下一轮还要点它派小队）✓
            _is_ev = False
            try:
                if tapped:
                    _t_rc = cell_of(*tapped)
                    # ⭐⭐⭐ 2026-10-05 **必须跟探索分支用同一个判据**（`_is_purple_cell`）
                    #   用户第二次报「**修了个寂寞啊，和之前一模一样，没打探索格**」的真根因：
                    #   这里原来**只看顶层 sid 后缀** ⇒ 顶层是垃圾猜测时判不出来
                    #   （真机 `runs/acc1/r_160935_0.png` 的 `(3,1)`：顶层 `S30001_104`
                    #     score **0.192**，而它其实是 `S00003_221` 紫格 ⇒ 后缀对不上 ✗）
                    #   ⇒ `_is_ev=False` + `mk=[]` ⇒ 掉进下面 `unmarked_no_start`
                    #     ⇒ **被当成"普通格点不动"处理掉** ⇒ **永远走不到探索分支**
                    #     （日志实证：那一局**探索/派遣事件 0 条** ✓）✗✗
                    #   ⚠ 而且**战斗分支排在探索分支之前**（5375~5476 早于 5480）
                    #     ⇒ 只要在这里被 return 掉，5480 的探索分支**根本没机会跑** ✓
                    _is_ev = _is_purple_cell(
                        str(((ctx.get('st') or {}).get(_t_rc) or {}).get('sid') or ''),
                        (ctx.get('st') or {}).get('ev_tiles'), tapped)
            except Exception:                               # noqa: BLE001
                _is_ev = False
            if not mk and not _is_ev:
                # ⚠ 普通格点不动 = 这格就是点不动，**绝不开清路模式**
                #   （旧版把普通格的 not_started 也当「被挡路」，于是跑去打没标记的格 —— 用户 09-25 报）
                log.append({'battle': 'unmarked_no_start', 'note': '普通格点不动 -> 拉黑这格'})
                return 'handled'
            if _is_ev:
                log.append({'battle': 'ev_no_start', 'note': '紫/橙格这次没开起来 '
                                                     '⇒ 不拉黑（它仍是目标）'})
                say('       · 紫/橙格这次没开起来 ⇒ 不拉黑（它仍是目标）')
                return 'handled'
            # ⭐⭐⭐ 2026-10-02 修「大拇指格不摇色子」的**前半刀**：
            #   本格带 recommend、但「战斗」点了没被确认开起来 ⇒ 判 blocked 返回。
            #   真机 19:48 铁证：这里判 blocked **之后**，下一轮屏幕上就出现了结算面板
            #   ⇒ 说明这场仗**其实打起来了、而且打完了**，只是这一帧没确认到。
            #   ⇒ 把「这一战是大拇指格」记进**本图状态**（`ctx['flags']` 就是 `st`，跨轮存活），
            #     等那一帧结算面板被认出来时补摇色子 ✓
            #     （那条路在 `_res` 分支里读这个标记；`already_result_panel` 会把它清掉）
            if 'recommend' in list(mk):
                _flp = ctx.get('flags')
                if isinstance(_flp, dict):
                    _flp['dice_pending'] = list(mk)
            log.append({'battle': 'blocked', 'marks': mk})
            say('       · 标记格打不开（可能被挡路）: %s' % (mk,))
            return 'blocked'
        # ⭐ 统计：幸运草地块 / 大拇指地块各打了几次（用户 2026-09-26 要求）
        if 'clover' in (mk or []):
            STATS['clovers'] = STATS.get('clovers', 0) + 1
        # ⭐⭐⭐ 2026-10-01 v1.08 用户口径（原话）：「战斗时日志要写出打这个格子是什么格子，
        #   拦路的就写**拦路格**，首领就写**首领格**，四叶草就写**四叶草格**，大拇指就写
        #   **大拇指格**。同时有多种就都写出来，比如『当前格子标志：首领，四叶草，大拇指，红装』」
        #   ⇒ 控制台 + 悬浮条都按中文写全（在列的全写、逗号分隔；一个标记都没有 = 拦路格 ✓）
        _desc_open = tile_phrase(mk)
        say('       · 开打 · %s（标记 %s）' % (_desc_open, mk or ['拦路']))
        status('开打 · %s' % _desc_open)
        # ⭐ 本格标记（统计/摇色子用 ✓）：只取刚点那格的标记，不含 ±1 邻域 ✓
        _exm = None
        try:
            if tapped:
                _rc = cell_of(tapped[0], tapped[1])
                _mv = markers.get(_rc)
                _exm = list(_mv.get('marks') or []) if _mv else []
        except Exception:       # noqa: BLE001
            _exm = None
        wait_end(b, log, marks=mk, exact_marks=_exm,
                 st=(ctx or {}).get('flags') if isinstance(ctx, dict) else None)
        # ⚠ 2026-09-27 用户要求：**去掉**"战斗成功后下一轮先试点目标格" ✗
        #   （原来会 try_targets=True ⇒ 下一轮把目标排最前 ✓ 用户不要这个行为 ✗）
        return 'battle_clear' if not mk else 'battle'

    # ⭐ v0.32：入口同战斗分支 —— 真机上「探索产出」标题落弹性区看不见，
    #   C>0 时用看得见的「探索」按钮（dlg≈735）进分支；PC/9:16 行为一字不变 ✓
    # ⭐⭐⭐ 2026-10-05 再补一条入口：**紫/橙格 + 有空闲槽**（用户第二次报「没打探索格」）
    #   真机那块面板的标题被识别成「**战斗事件**」而不是「探索产出」⇒ 只按标题必然漏 ✗
    #   ⇒ 只要这一格是**紫/橙格**（`_is_purple`）且**有空闲槽**，就按探索处理 ✓
    #     （槽满时 5235 已把它改成"开打"那条路 ✓ 不会走到这里）
    _expl_entry = (fb(items, L['expl'])
                   or (dlg_c() and _dlg_panel_btn(ditems, L['ebtn']))
                   or (_is_purple and _free_now > 0))
    if _expl_entry:
        act = None
        for it in ditems:
            if L['ebtn'] in it['text'] and L['expl'] not in it['text'] and it['cy'] > LAYOUT.sy(620):
                act = it
                break
        # ⭐ 2026-09-26 用户口径：**面板掉落里有紫/橙/红（A/S/SS）才点探索** ✓
        #   （三个槽位要装"紫色以上的探索事件" ✓；只有绿/蓝就不值得，关掉换别的格子 ✓）
        # ⭐ 2026-09-26 用户口径：这些是**固定紫/橙探索**的地块 ⇒ 不用看颜色、直接点探索 ✓
        _is_target_tile = bool(ctx.get('ev_tiles'))
        _hv_img = None
        if _OCR_CH['dlg'] and hasattr(b, 'img_dlg'):
            try:
                _hv_img = b.img_dlg()
            except Exception:       # noqa: BLE001
                _hv_img = None
        hv = True if _is_target_tile else has_high_value_drop(_hv_img or img)
        # ⭐⭐ 2026-09-26 修复（用户在实例B实测卡死）：原来**不检查槽位**，只要 hv 就点探索。
        #   探索槽已经满了的时候点「探索」游戏没有反应 ⇒ 面板不关 ⇒ 下一帧又认到同一段
        #   面板文字、又点探索…⇒ 整个闭环卡死（最后表现就是"退出地图失败"）。
        _free2 = int(ctx.get('slots_free', 1) or 0)
        # ⚠⚠ 2026-10-01 修 NameError：`entry` 是 **one_round()** 的局部变量，本函数里根本没有
        #   ⇒ 走到「紫/橙探索格」分支时**必抛 NameError**（被上层 except 吞掉 ⇒
        #     症状：点到紫橙格就静默中断那一轮，日志里没有 explore_panel 记录）。
        # ⇒ 诊断信息改成直接进 `log`（本函数能写的），不依赖 one_round 的局部变量。
        log.append({'explore_panel': {'hv': bool(hv), 'btn': bool(act),
                                      'target_tile': _is_target_tile,
                                      'slots_free': _free2}})
        # ⭐ 不靠 slots_free 当闸门（OCR 偶尔认不到「空闲」会误判成 0 ✗），
        #   改成**先点、再验证**：点了「探索」面板还在 ⇒ 就是派不进去（多半槽位满）⇒ 改走战斗
        # ⭐⭐ 2026-09-30：**已经确认满本图**（`slots_full_latched`，两次点不动）时不再给
        #   第三次机会 —— 否则紫/橙格多起来又会"一格一下"地空转（用户报的就是这个体感 ✗）
        _latched = (_PANEL_STUCK.get('expl') or 0) >= 2 and _free2 <= 0
        if act and hv:
            if not _latched:
                b.tap_dlg(act['cx'], act['cy'], wait=3.5)   # ⭐ v0.31：弹窗系按钮 → tap_dlg
                if panel_gone(b, L['expl'], dlg_btn=L['ebtn']):
                    _PANEL_STUCK['expl'] = 0
                    # ⚠ 这里**不改** slots_free：面板关掉只说明"游戏受理了这一下"
                    #   （多半是换成「探索配队」面板，真正派遣在下面的 A 分支），
                    #   提前 -1 会把还有空槽的机器误判成满 ⇒ A 分支反而把配队面板关掉 ✗。
                    #   空闲数一律以**下一轮轮首的 HUD 读数**为准（见 one_round 顶部）✓
                    log.append({'explore': 'claimed_high_value'})
                    return 'handled'
                n = (_PANEL_STUCK.get('expl') or 0) + 1
                _PANEL_STUCK['expl'] = n
                log.append({'explore': 'tap_no_effect', 'n': n, 'slots_free': _free2})
                if n < 2:
                    return 'handled'          # 再给一次机会（可能只是动画没走完）
            else:
                log.append({'explore': 'skip_latched_full', 'slots_free': _free2})
            # ⭐ 用户 09-26 口径：**探索槽满了 ⇒ 紫橙格改当成普通目标打掉**（不再派探索）
            _mk2 = near()
            _fbtn = None
            for it in ditems:               # ⭐ v0.31 方案 B：y 带 = 弹窗系标定 ✓
                t = it['text'].strip()
                if (L['fbtn'] in t and len(t) <= 4 and L['fight'] not in t
                        and _FBY0 <= it['cy'] <= _FBY1):
                    _fbtn = it
                    break
            if _fbtn is None:
                # ⚠ 2026-10-02：原来兜底写死 `sx(537)`（1080p 系 806）⇒ 720p 点不到 ✗
                _fbtn = {'cx': int(LAYOUT.sx(layout_mod.REF['fight_x_normal'])),
                         'cy': FIGHT_Y, 'text': 'fixed'}
            log.append({'explore': 'slots_full_fight', 'at': (_fbtn['cx'], _fbtn['cy']),
                        'marks': list(_mk2)})
            if start_fight(b, log, _fbtn, _mk2):
                say('       · 探索槽已满 ⇒ 这一格改开打（标记: %s）' % (_mk2 or ['拦路'],))
                # ⭐ v1.08：悬浮条同样按中文写清是什么格子（多种标记全写 ✓）
                status('开打 · %s' % tile_phrase(_mk2))
                # ⭐ 2026-09-27：本格标记（不含 ±1 邻域 ✗）⇒ 防"邻格大拇指"白摇色子 ✓
                _exm2 = None
                try:
                    if tapped:
                        _rc2 = cell_of(tapped[0], tapped[1])
                        _mv2 = markers.get(_rc2)
                        _exm2 = list(_mv2.get('marks') or []) if _mv2 else []
                except Exception:       # noqa: BLE001
                    _exm2 = None
                wait_end(b, log, marks=_mk2, exact_marks=_exm2,
                         st=(ctx or {}).get('flags') if isinstance(ctx, dict) else None)
                # ⚠ 2026-09-27 用户要求：不再设 try_targets ✓（战斗后不抢着点目标 ✓）
                return 'battle_clear' if not _mk2 else 'battle'
            # 开不起来也不能像以前那样干耗着 ⇒ 强制脱困
            force_unstick(b, log, 'explore_slots_full', ctx)
            return 'none'
        if act and not hv:
            log.append({'explore': 'skip_low_value'})
            close_x_panels(b, img)
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.4)
            return 'handled'
        close_x_panels(b, img)
        return 'handled'

    # ⭐ 特殊地块（旅行商人 / 黄金宝库）必须**排在「领取」之前**判：
    #   黄金宝库面板的说明文案是「不管你看到多少宝物，每一层都只能**领取**一件哦」，
    #   先判「领取」会一直去点这句说明文字（点了没反应 → 每轮空转）
    # ⭐⭐ v0.61 真机**可达性**修复：宝库标题（dlg 383）落在 toRef 丢弃的弹性区 ⇒
    #   归一化帧里没有它 ⇒ 旧写法 `fb(items, '黄金宝库')` 在真机恒 False ⇒
    #   buypanels 整条链路只能靠"点了没反应 2 轮"的兜底碰运气进来（旅行商人标题
    #   dlg 601 不在丢带 ⇒ 它不受影响）。这里补一条**归一化帧里看得见**的签名
    #   （零额外 OCR，全靠已有的 items / ditems）：
    #     ① 说明文案「※花费金币分别解锁**宝库**的外层、内层、核心」(dlg 1459 ⇒ 帧内 1250 ✓)
    #     ② 右下角按钮 (dlg 1444 ⇒ 帧内 1235 ✓) 经 dlg_items 换算后按 dlg 标定值判
    _sp = []
    if dlg_c() and (fb(items, '解锁宝库') or _dlg_btn_sig(ditems, 'vault')):
        _sp.append('黄金宝库')
    for t in L['special']:
        if fb(items, t) or t in _sp:
            # ⛔⛔⛔ 2026-10-10 **第 N 次「同一面板两个名字」**（用户报「图上有预言石碑，试一试」）
            #   ---- 病 ----
            #     · 图上的**方块名** = `预言石碑`（数据表 `Area_Spot.Name`）
            #     · 面板**标题**     = `预言石板`（真机 OCR 实测 conf=0.99）
            #     ⇒ 命中的是哪个名字，`t` 就是**哪个名字**；
            #       而下面所有判据（`t not in act_on` / `elif '预言石碑' in t`）都是**按名字比**
            #       ⇒ 「石碑」匹配不上「石板」✗✗
            #   ---- 我踩过的三个连环坑（都在真机帧上被门禁抓出）----
            #     ① `t not in act_on` ⇒ 走"无视"支（盲点 X 关掉）✗
            #     ② 只加「石碑」进 `act_on` ⇒ 还是不算，因为 `t` 是「石板」✗
            #     ③ `elif '预言石碑' in t` ⇒ 仍不匹配（碑≠板）⇒ 掉进 `else`
            #        ⇒ **拿旅行商人流程去点预言面板**（真机日志：买了 4 次！）✗✗✗
            #   ---- 修法：**入口处把 `t` 归一到"规范名"**（一次性治本 ✓）----
            #     不要再逐处堆字符串 —— 那种写法每加一个别名就要改 N 处，必然再漏 ✗
            t = SPECIAL_ALIAS.get(t, t)
            # ⛔⛔⛔ 2026-10-11 **修「第 46 张卡死 44 轮」**（用户报「为什么刷了 68 张只打
            #   62 个首领」⇒ 我查到这一张**零进展 42 轮** ✗）
            #   ---- 病（真机铁证 `runs/acc1/loop/loop_log.json` #2460~#2687）----
            #     #2460 {"special": "勇者之墓",
            #            texts: ["预言石板", "本次可选择1个预言！", "路标",
            #                    "地图中至少出现1个勇者", "之墓，并且勇者之墓奖", ...]}
            #            ↑ 面板其实是**预言石碑**！可 `t` 被判成了**勇者之墓** ✗
            #     #2461 {"vault_step": "relic_start", "n": 88}
            #     #2462 {"relic": "panel_missing"}     ← 勇者之墓面板"不存在"
            #     …（**重复 44 轮**，体力一直 715 ⇒ `maxed` 退图，boss 也没打 ✗✗）
            #   ---- 根因：`fb()` 是**子串**匹配，而预言卡的效果描述里**含"勇者之墓"** ----
            #     · `fb(items,'勇者之墓')` 扫到的是预言卡「奇遇」的说明文字
            #       「地图中至少出现 1 个**勇者之墓**，并且勇者之墓奖励至少为橙色位阶」
            #       （OCR 断成 `"地图中至少出现1个勇者"` + `"之墓，并且勇者之墓奖"`）
            #     · 而 `L['special']` 里 **`勇者之墓` 排在 `预言石板` 之前** ✗
            #       ⇒ 先命中「勇者之墓」⇒ `t` = 勇者之墓 ⇒ 错派 ✗✗
            #     复算：全盘 **86 条** `special` 全是这种错派（面板字含「预言石板」✗）
            #   ---- 修法（**面板标题优先**，而不是"按元组顺序碰运气" ✓）----
            #     面板**标题**是"当前开着哪个面板"的**唯一权威** ✓
            #     ⇒ 若这一帧**明确读到某个面板标题**（`预言石板`/`英灵使者`/`限时超值礼包`/
            #       `传承祭坛`/…），就以它为准；只有标题都没读到，才退回原来的子串扫 ✓
            #     ⚠ 这就是"**先验标题、再兜底子串**"——本项目已在 `is_foretell_panel`
            #       等处用过同一思路（标题是硬证据，正文是软证据 ✓）
            _title = _panel_title_of(items)
            if _title:
                t = SPECIAL_ALIAS.get(_title, _title)
            if t not in L['act_on']:
                # 用户 09-25：特殊地块**只点旅行商人和黄金宝库**，其他一律无视
                close_x_panels(b, img)
                x = find_x(items)
                if x:
                    _tap(b, x['cx'], x['cy'], wait=1.8)
                # ⭐⭐ 2026-09-26：这里原来**直接 return 'handled'** ⇒ 面板没关掉时闭环被它占死
                #   （实测图13：连刷 45 次、stamina/round 都不动，最后退出地图失败）
                #   改：关完**重新截图验证**；还在 ⇒ 计数，第二次就强制脱困 + return 'none'
                #   （'none' ⇒ 主循环继续往下做决策，不再被这一条卡住）
                if panel_gone(b, t):
                    _PANEL_STUCK[t] = 0
                    log.append({'special_ignored': t, 'closed': True})
                    return 'handled'
                n = (_PANEL_STUCK.get(t) or 0) + 1
                _PANEL_STUCK[t] = n
                log.append({'special_ignored': t, 'closed': False, 'n': n})
                if n >= 2:
                    force_unstick(b, log, 'special:%s' % t, ctx)
                    _PANEL_STUCK[t] = 0
                    return 'none'
                return 'handled'
            log.append({'special': t, 'texts': [i['text'] for i in items][:24]})
            # ⭐⭐⭐⭐ 2026-10-05 **金币 < 50 万 ⇒ 不买**（用户口径，原话）：
            #   「金币低于50万就自动不去购买商人和宝库（也不规划，就相当于拉黑了），
            #     高于50w就还是正常买」
            #   ⚠ 这里管的是「面板**已经开着**」的情形 —— 金币不够就**只关面板不买** ✓
            #     （"不规划"那条在决策层，见 `pending_buy` 的过滤 ✓）
            #   ⚠ 读不到金币 ⇒ `gold_enough_locked` 返回 True ⇒ 照常买（保守 ✓）
            _fl_g = (ctx or {}).get('flags')
            if not gold_enough_locked(_fl_g):
                try:
                    buypanels.ensure_closed(b, log)
                except Exception:       # noqa: BLE001
                    pass
                say('       · 金币不足 %d ⇒ **不买%s**（只关面板 ✓ 用户口径）'
                    % (GOLD_MIN_BUY, t))
                status('金币不足 · 跳过%s' % t)
                log.append({'buy_skip_low_gold': t,
                            'gold': (_fl_g or {}).get('gold_locked')
                            if isinstance(_fl_g, dict) else None,
                            'min': GOLD_MIN_BUY})
                return 'handled'
            # ⭐ 2026-09-25：买完流程独立成 buypanels.py（坐标实测 + 每轮 OCR 定位按钮）
            #   旅行商人：购买(895,1255)→返回(539,1212) ×4 → X(983,602)
            #   黄金宝库：购买解锁一层(10000/20000/40000) → 现场认奖励（优先天赋果实/幸运草）
            #             →「选择奖励」→ 中间「返回」，三层完按钮变「离开」
            #
            # ⛔⛔⛔ 2026-10-10 **分派必须按语义、不能按精确等于**（第三次踩"两个名字"）：
            #   `t` 是 `for t in L['special']` 里**命中的那个名字** ——
            #   而「预言石碑」（方块名）/「预言石板」（面板名）是**同一面板两个名字** ✗
            #   ⇒ 原来写 `elif t == '预言石碑':` ⇒ 当 `t = '预言石板'` 时**匹配不上**
            #     ⇒ 会掉进最后的 `else`（**旅行商人 flow**）⇒ 拿商人流程去点预言面板 ✗✗
            #   ⇒ 改成 **`in` 判据**（与 `fb`/`act_on` 同口径：认名字的**子串** ✓）
            #   ⚠ 顺序仍然重要：先判最专的（宝库/预言/礼包/勇者之墓），最后才是商人 ✓
            if '黄金宝库' in t:
                status('发现黄金宝库 · 正在开箱…')
                # ⭐⭐⭐ 2026-10-01 用户报「第一层还没选择就乱点了」⇒ 两条硬规矩：
                #   ① **必须包 try/except**：`vault_flow` 一崩就抛到上层 ⇒ 面板留在屏幕上
                #      没人管 ⇒ 主循环继续按点序点棋盘格 ⇒ 那些点击**全落在宝库面板上**
                #      = 用户看到的"乱点" ✗✗（真机 18:35 实证：ICON_THR NameError ×3 轮）
                #   ② **只有真的买到了才计数**：旧写法无论成败都 `STATS['vaults'] += 1`
                #      ⇒ 日志会谎报"买完 1 个"，而用户看到的是没买到 ✗
                _vok = False
                try:
                    _vacts = buypanels.vault_flow(b, log)
                    _vok = bool(_vacts)
                except Exception as _ve:      # noqa: BLE001
                    import traceback as _tb
                    log.append({'vault': 'flow_error', 'e': repr(_ve)[:120],
                                'trace': _tb.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 宝库流程异常：%r ⇒ **不计数**，交给下一轮重试' % (_ve,))
                if _vok:
                    STATS['vaults'] += 1
                    # ⭐ 同商人口径记一笔（宝库通常是整格替换，但这行是**兜底**：
                    #   万一某次买完美术没变，也不会被「摘除」重新放回去重复点）
                    # ⛔ 2026-10-02：原来写的是裸 `st` —— `popups()` 里**没有**这个名字
                    #   （真机 #40 抓到 `NameError: name 'st' is not defined`）
                    #   ⇒ 宝库那条记录**从来没成功过**，只是 `except: pass` 吞掉了 ✗
                    #   ⇒ 改成和商人同一处：`ctx['flags']` ✓
                    try:
                        _stv = (ctx or {}).get('flags')
                        if tapped and _stv is not None:
                            _stv.setdefault('bought_done', set()).add(
                                (int(tapped[0]), int(tapped[1])))
                    except Exception:       # noqa: BLE001
                        pass
                    say('       · 黄金宝库买完（第 %d 个）' % STATS['vaults'])
                    status('黄金宝库 · 完成 ✓')
                else:
                    # ⚠ 不管成败都要**确保面板被收起**，否则下一轮又会点在面板上 ✗
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    say('       · 宝库本轮没走完 ⇒ 已尝试收起面板（下轮再来 ✓）')
                    status('宝库没走完 · 先收起面板')
            elif '勇者之墓' in t:
                # ⭐⭐⭐⭐ 2026-10-07 **勇者之墓**（面板叫「英灵使者」）—— 真机实测走通 ✓
                #   用户口径：「**三行都能点，优先点成功率100%的**」
                #   实测：**零成本**（不花钱不花体力），选一行 → 确定 → 事件成功 + 奖励
                #   （详见 `_ref_game_src/README_勇者之墓_真机实测.md`）
                status('发现勇者之墓 · 正在领奖…')
                _roks = None
                try:
                    _roks = buypanels.relic_flow(b, log)
                except Exception as _re:      # noqa: BLE001
                    import traceback as _tb3
                    log.append({'relic': 'flow_error', 'e': repr(_re)[:120],
                                'trace': _tb3.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 勇者之墓流程异常：%r ⇒ 已尝试收起面板' % (_re,))
                if _roks:
                    STATS['relics'] = STATS.get('relics', 0) + 1
                    say('       · 勇者之墓完成（第 %d 个）' % STATS['relics'])
                    status('勇者之墓 · 完成 ✓')
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    status('勇者之墓没走完 · 先收起面板')
            elif '限时礼包' in t:
                # ⭐⭐⭐⭐ 2026-10-07 **限时礼包**（面板叫「限时超值礼包」）—— 实测走通 ✓
                #   用户口径（原话）：「**720 分辨率下第一个免费按钮是固定坐标，
                #     只点最上面那个免费按钮**」⇒ 只领第 1 档（红宝石×20，免费）✓
                #   ⚠ 第 2 档要 6 幸运草、第 3 档用户说也不点 ⇒ 都不碰 ✓
                status('发现限时礼包 · 正在领取…')
                _goks = None
                try:
                    _goks = buypanels.gift_flow(b, log)
                except Exception as _ge:      # noqa: BLE001
                    import traceback as _tb4
                    log.append({'gift': 'flow_error', 'e': repr(_ge)[:120],
                                'trace': _tb4.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 限时礼包流程异常：%r ⇒ 已尝试收起面板' % (_ge,))
                if _goks:
                    STATS['gifts'] = STATS.get('gifts', 0) + 1
                    say('       · 限时礼包完成（第 %d 个）' % STATS['gifts'])
                    status('限时礼包 · 完成 ✓')
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    status('限时礼包没走完 · 先收起面板')
            elif '预言石碑' in t:
                # ⭐⭐⭐⭐⭐ 2026-10-07 **预言石碑**（面板叫「预言石板」）—— 实测走通 ✓
                #   用户口径（原话）：
                #     「**优先选 地图中至少有1名敌人拥有<紫/橙>色位阶的掉宝加护这个加护。
                #       其他就按品阶排，优先品质高的**」
                #     「**这个预言（幸运）要加个按钮，是否停止脚本（类似出现红装标记）**」
                #     「**地图中必定出现金属宝箱怪也要单独拿出来弄个选项，
                #       遇到那个是否立即停止脚本**」
                #   ⇒ 选卡：① 掉宝 ② 幸运/和平(金属宝箱怪) ③ 按品阶
                #   ⇒ 抽到 ② ⇒ **停脚本**（按 GUI 两个开关，见 `STOP_LUCKY/STOP_PEACE`）
                status('发现预言石碑 · 正在占卜…')
                _fout = None
                try:
                    _fout = buypanels.foretell_flow(
                        b, log, flags={'stop_peace_metal': STOP_PEACE,
                                       # ⭐ 2026-10-09 用户：「加上橙色和紫色元素」
                                       'stop_elem_purple': STOP_ELEM_PURPLE,
                                       'stop_elem_orange': STOP_ELEM_ORANGE})
                except Exception as _fe:      # noqa: BLE001
                    import traceback as _tb5
                    log.append({'foretell': 'flow_error', 'e': repr(_fe)[:120],
                                'trace': _tb5.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 预言石碑流程异常：%r ⇒ 已尝试收起面板' % (_fe,))
                if _fout and _fout.get('acts'):
                    STATS['foretells'] = STATS.get('foretells', 0) + 1
                    say('       · 预言石碑完成（第 %d 个，选了 %s）'
                        % (STATS['foretells'], '、'.join(_fout.get('picked') or [])))
                    status('预言石碑 · 完成 ✓')
                    # ⭐⭐ 停脚本闸门（用户口径）：
                    #   幸运 / 和平·金属宝箱怪 / **元素·紫** / **元素·橙** ⇒ 停 + 保现场
                    #   ⚠ 「元素·紫」「元素·橙」由 `foretell_flow` 按**开关**决定要不要
                    #     把 `stop` 写成这两个值 ⇒ 这里只需**无条件认它们**（双保险：
                    #     再按 `STOP_ELEM_*` 复核一次，防 flow 那边漏判 ✓）
                    _why = _fout.get('stop')
                    _do_stop = bool(_why) and (
                        ('幸运' in _why and STOP_LUCKY)
                        or ('和平' in _why and STOP_PEACE)
                        or ('元素·紫色' in _why and STOP_ELEM_PURPLE)
                        or ('元素·橙色' in _why and STOP_ELEM_ORANGE))
                    if _why and not _do_stop:
                        say('       · （抽到【%s】，但你在窗口里关了"遇到就停"⇒ 继续跑 ✓）'
                            % _why)
                        log.append({'foretell': 'stop_skipped_by_pref', 'why': _why})
                    if _do_stop:
                        # 与红装同一套：**停 + 保现场 + 上锁 + 截图**（用户原话"类似出现红装标记"）
                        # ⛔⛔ 2026-10-10 **修：`rnd` 在 `popups()` 里不存在**（审计抓到 ✗）
                        #   `popups(b, items, log, ctx=None)` 的签名里**没有 `rnd`** ✗
                        #   ⇒ 下面 `'foretell_stop_r%02d' % rnd` 与 `'round': rnd` 都抛 NameError
                        #   ⇒ 被各自的 `except Exception: pass` **静默吞掉** ✗✗
                        #   ---- 后果（**不是"没影响"**）----
                        #     · ① 截图那行抛 ⇒ `_shot` 恒 None ⇒ **保现场的截图从来没存过** ✗
                        #     · ② `json.dump` 那块**整块废掉** ⇒ **`red_lock_path` 锁文件没写** ✗
                        #       （`'round': rnd` 在 `dict` 字面量里 ⇒ 整个字面量求值就抛 ✓）
                        #     · ③ 但 `#1039` 的 `log.append` + `return 'foretell_stop'` **仍会执行** ✓
                        #       ⇒ **停脚本生效了，可"现场"没保住** —— 正是用户要的那半没做成 ✓
                        #   ---- 为什么一直没发现 ----
                        #     与 `v1.63/v1.64/v1.71` **同一族**：**判据建在拿不到数据的地方** +
                        #     `except: pass` 让它**一声不响**（本项目第 N 次 ✓）
                        #     ⚠ 门禁 ㉡ 当时只钉了"不许写裸 `st`"，**没钉 `rnd`** ⇒ 漏了 ✓
                        #   ---- 修法 ----
                        #     轮次与地图名**同一来源**：`ctx['flags']`（= 主循环的 `st`）
                        #     取不到 ⇒ 用 `-1` 占位（**不许再抛异常** ✓）
                        _fl_stop0 = (ctx or {}).get('flags') or {}
                        _rnd_v = (_fl_stop0.get('round') if isinstance(_fl_stop0, dict)
                                  else None)
                        if _rnd_v is None:
                            _rnd_v = -1
                        _shot = None
                        try:
                            _shot = b.snap('foretell_stop_r%02d' % int(_rnd_v), save=True)
                        except Exception:       # noqa: BLE001
                            pass
                        # ⛔⛔ 2026-10-12 **不再上锁**（用户原话：
                        #   「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
                        #   ⇒ 原来那一段 `json.dump({...}, red_lock_path(...))` 整块删掉
                        #     （它写了锁 ⇒ 下次启动被 `red_locked()` 拦住 ⇒ 还得人工解锁 ✗）
                        #   ⇒ 现在只**留取证帧 + 停脚本**，不写任何锁文件 ✓
                        #   ⚠ 保留 `_shot`（取证帧）—— 停现场时有用，且**不产生锁** ✓
                        if _shot:
                            log.append({'stop': 'foretell_shot',
                                        'why': _why, 'round': int(_rnd_v),
                                        'shot': os.path.basename(_shot)})
                        log.append({'stop': 'foretell_%s' % _why, 'why': _why,
                                    'shot': os.path.basename(_shot or '')})
                        say('')
                        say('🛑🛑 抽到【%s】⇒ **立即停止**（不退图，留着你自己处理）'
                            % _why)
                        say('')
                        status('★ 抽到【%s】· 已停下，请手动处理' % _why)
                        return 'foretell_stop'
                    return 'handled'
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    status('预言石碑没走完 · 先收起面板')
            elif '宝箱怪' in t:
                # ⭐⭐⭐⭐⭐ 2026-10-10 **金属/机巧宝箱怪**（审计补上的接线 ✓）
                #   ⛔ 病：`buypanels.mimic_flow` **早就写好并真机测过**，
                #     但 `L['act_on']` 里**没有这两个名字** ⇒ `t not in act_on`
                #     ⇒ 走"无视"支（`close_x_panels` + 盲点 X）⇒ **`mimic_flow` 从没跑过** ✗✗
                #     —— 与「勇者之墓」**同一个 bug**（实现了 flow 但没接进 `popups()` ✓）
                #   ⭐ 发现方式：`_tmpman/audit5_rest.py` 的**交叉表**
                #     （"flow 在? × in act_on?"）—— 读代码看不出来，**结构比对**才看得见 ✓
                #   ⚠ 用 `'宝箱怪' in t`（不是精确等于）—— 两个名字都要接住 ✓
                #   ⚠ `献祭宝箱怪`（SP=6）**不在这里**：数据表 `MaxNum=0` ⇒ 游戏不生成 ✓
                #     （用户 2026-10-03 口径：「删掉献祭宝箱怪」✓）
                #     ⇒ 但它若真出现，会走 `mimic_flow` 而不是被盲点 X 关掉 —— 可接受 ✓
                status('发现宝箱怪 · 正在看货…')
                _mout = None
                try:
                    _mout = buypanels.mimic_flow(b, log)
                except Exception as _me3:      # noqa: BLE001
                    import traceback as _tb6
                    log.append({'mimic': 'flow_error', 'e': repr(_me3)[:120],
                                'trace': _tb6.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 宝箱怪流程异常：%r ⇒ 已尝试收起面板' % (_me3,))
                if _mout and (_mout.get('bought') or _mout.get('skip')):
                    if _mout.get('bought'):
                        STATS['mimics'] = STATS.get('mimics', 0) + 1
                        say('       · 宝箱怪完成（第 %d 个，买到 %s）'
                            % (STATS['mimics'], _mout.get('bought')))
                        status('宝箱怪 · 完成 ✓')
                    else:
                        say('       · 宝箱怪没买（%s）⇒ 已收面板 ✓'
                            % (_mout.get('skip'),))
                        status('宝箱怪 · 跳过')
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    status('宝箱怪没走完 · 先收起面板')
            elif '传承祭坛' in t:
                # ⭐⭐⭐⭐⭐ 2026-10-11 用户口径（原话）：「**我开了**」
                #   （= 在窗口里勾上了「传承祭坛」/「机巧宝箱怪」，要采这两个的面板 ✓）
                #   ---- 现状 ----
                #     传承祭坛是**最后一个既没 flow、也没面板实测**的地块 ✗
                #     我把它加进 `L['act_on']` ⇒ 面板**不再被盲点 X 关掉** ✓
                #     但它**还没有 handler**（面板长什么样不知道）⇒ 不能瞎点 ✗
                #   ---- 所以这里**只做"采面板"需要的两件事** ----
                #     ① 落一张**取证帧**（命名带 shrine，方便找 ✓）
                #     ② 按用户在窗口里的[临时]开关决定**要不要停脚本保现场** ✓
                #        （`MAPBOT_STOP_SHRINE`，与"机巧宝箱怪"那套同一机制 ✓）
                #     ⚠ **不点任何坐标** —— 面板没实测，盲点必出事 ✗
                #     ⚠ 拿到面板后我再写 `shrine_flow`（与 `mimic_flow` 同构）✓
                say('       · 发现【传承祭坛】⇒ 走 `shrine_flow`（是 30000 就买 ✓）')
                status('发现传承祭坛 · 正在激活传承…')
                # ⛔⛔ 2026-10-11 **注意：这里不能写裸 `rnd`** ——
                #   `popups(b, items, log, ctx=None)` 的签名里**没有 `rnd`** ✗
                #   （我上一版就写了 `% rnd` ⇒ 与刚修的 `pal` 那个 bug **一模一样** ✗✗
                #     被门禁 `verify_vault_probe.py` 的 ⑥⑨ 当场抓出 ✓）
                #   ⇒ 轮次与地图名**同一来源**：`ctx['flags']`（= 主循环的 `st`）
                _fl_s0 = (ctx or {}).get('flags') or {}
                _rnd_s0 = (_fl_s0.get('round') if isinstance(_fl_s0, dict) else None)
                if _rnd_s0 is None:
                    _rnd_s0 = -1
                # ⭐ 取证帧（保底留一份 ⇒ 便于事后核对 ✓）
                try:
                    _shot_s = b.snap('shrine_panel_r%02d' % int(_rnd_s0), save=True)
                except Exception:       # noqa: BLE001
                    _shot_s = None
                log.append({'shrine': 'panel_seen', 'round': int(_rnd_s0),
                            'note': '传承祭坛面板 ⇒ 走 shrine_flow ✓'})
                _fl_s = _fl_s0
                # ⛔⛔ 2026-10-11 **删掉 `STOP_SHRINE` 那条早退**（用户要求去掉[临时]采集停止 ✓）
                #   原逻辑：`if STOP_SHRINE: 写锁 + 停脚本 + return 'shrine_stop'`
                #   ⇒ 那是"为采面板而临时停"用的；**面板已采到、`shrine_flow` 已写好**
                #   ⇒ 现在**直接走下面的正常流程**（读价 → 是 30000 就买 ✓）
                #   ⚠ 取证帧保留（无害，便于事后核对 ✓）
                # ── ⭐ 正常流程：走 `shrine_flow`（用户口径：是 30000 就买 ✓）──
                _sout = None
                try:
                    _sout = buypanels.shrine_flow(
                        b, log, flags=(_fl_s if isinstance(_fl_s, dict) else None))
                except Exception as _se:    # noqa: BLE001
                    import traceback as _tb7
                    log.append({'shrine': 'flow_error', 'e': repr(_se)[:120],
                                'trace': _tb7.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 传承祭坛流程异常：%r ⇒ 已尝试收起面板' % (_se,))
                if _sout and _sout.get('bought'):
                    STATS['shrines'] = STATS.get('shrines', 0) + 1
                    say('       · 传承祭坛完成（第 %d 个）✓' % STATS['shrines'])
                    status('传承祭坛 · 完成 ✓')
                elif _sout and _sout.get('skip'):
                    say('       · 传承祭坛没买（%s）⇒ 已收面板 ✓'
                        % (_sout.get('skip'),))
                    status('传承祭坛 · 跳过')
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    status('传承祭坛没走完 · 先收起面板')
                return 'handled'
            else:
                status('发现旅行商人 · 正在购物…')
                # ⭐ 2026-10-01 同宝库口径：包 try/except + 只有成功才计数 + 失败必收面板 ✓
                _mok = None
                try:
                    # ⚠ `merchant_flow` 返回**买到的次数**（可能为 0 = 正常结束但没钱）⇒
                    #   不能用 bool() 当成败判据（买到 0 次也是"流程走完了" ✓）
                    _mok = buypanels.merchant_flow(b, log)
                except Exception as _me:      # noqa: BLE001
                    import traceback as _tb2
                    log.append({'merchant': 'flow_error', 'e': repr(_me)[:120],
                                'trace': _tb2.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 商人流程异常：%r ⇒ **不计数**，交给下一轮重试' % (_me,))
                if _mok is not None:
                    STATS['merchants'] += 1
                    # ⭐⭐ 2026-10-02 记下「这一格买完了」（治「买完一直被重复点」）
                    #   商人格买完后**美术不变**（仍是「旅行商人」）⇒ 分类器认不出差别
                    #   ⇒ 只有这里知道它买过了 ⇒ 摘除逻辑要靠这个记录才不会反复摘 ✓
                    #   （宝库是整格替换，分类器立刻能看出变化；商人不行 —— 用户原话
                    #     「宝库买完才会消失」指的正是这个差别）
                    # ⛔⛔⛔ 2026-10-02 修「商人被重复买 9 次」——**根因终于定论**
                    #   真机日志（runs/loop）把整条链摆得清清楚楚：
                    #       #40 {"bought_rec_err":"NameError: name 'st' is not defined"}
                    #       #44 {"unpin_dbg":{"kept_bought":[], "now_vendor":[[456,1100]],
                    #                            "dropped":[[456,1100]]}}
                    #   ⇒ **`st` 在 `popups()` 里根本不存在**（签名只有
                    #     `popups(b, items, log, ctx=None)`，状态在 `ctx['flags']`）
                    #     ⇒ 每次记录都 NameError ⇒ `bought_done` **永远是空集**
                    #     ⇒ 摘除时 `_p not in _just_bought` 恒成立
                    #     ⇒ 「宝库永不丢」逻辑每轮都把商人格重新放回 `done`
                    #     ⇒ 同一格被买了 9 次（每次 4 件 = 36 件）✗✗
                    #   ⚠ 讽刺的是：这个 NameError 被 `except` 吞了，
                    #     只在诊断日志里留了一行 —— **没有异常、没有告警、照跑**，
                    #     所以我前面几轮都以为「修复已生效，只是另有原因」✗
                    try:
                        _st = (ctx or {}).get('flags')      # ⭐ 正确的来源
                        if tapped and _st is not None:
                            _bd = _st.setdefault('bought_done', set())
                            _bd.add((int(tapped[0]), int(tapped[1])))
                            # ⭐⭐⭐ 2026-10-26 **买完这一刻就记 `merchant_done`**
                            #   ---- 病 ----
                            #     `merchant_done` 原来**只在**「摘除逻辑」那段写，
                            #       而那段的条件是 `_p in done and _p not in _just_bought`
                            #       ⇒ **买完那一轮 `_just_bought` 正好有它** ⇒ 永远写不进去 ✗
                            #       ⇒ 那个集合是**只写不读的死集合**（本项目同族第 N 次 ✓）
                            #       ⇒ 真机实测：`grep -c skip_bought` = **0**（一次都没触发）
                            #       （真机 loop_log #39 = {"bought_rec":[264,1004],"cell":"4,3"}）
                            #   ---- 修法 ----
                            #     **在买完的现场就记**（这里 `tapped` 就是商人格坐标 ✓）
                            #     ⇒ 下一轮 `buy` 列表的过滤立刻生效 ⇒ 不再重复点 ✓
                            #   ⚠ 记的是 **(row,col) 格号**（与过滤那侧同量纲 ✓）
                            _md = _st.setdefault('merchant_done', set())
                            _md.add(tuple(cell_of(*tapped)))
                            log.append({'bought_rec': list(tapped),
                                        'cell': ('%d,%d' % cell_of(*tapped)),
                                        'bd': sorted(_bd),
                                        'merchant_done': len(_md)})
                        else:
                            log.append({'bought_rec_skip': list(tapped or ()),
                                        'why': ('no_tapped' if not tapped
                                                else 'no_flags')})
                    except Exception as _me2:      # noqa: BLE001
                        log.append({'bought_rec_err': repr(_me2)[:80]})
                    say('       · 旅行商人买完（第 %d 个，本次买到 %d 次）'
                        % (STATS['merchants'], _mok))
                    status('旅行商人 · 完成 ✓')
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    say('       · 商人本轮没走完 ⇒ 已尝试收起面板（下轮再来 ✓）')
                    status('商人没走完 · 先收起面板')
            return 'handled'

    it = fb(items, *L['claim'])
    if it and it['cy'] < LAYOUT.sy(1133) and len(it['text']) <= 4:
        _tap(b, it['cx'], it['cy'], wait=2)
        log.append({'popup': 'claim'})
        return 'handled'

    ok = exb(items, L['ok'])
    if ok and ok['cy'] > LAYOUT.sy(900) and exb(items, L['cancel']) is None:
        if fb(items, '购买', '钻石不足'):
            return 'none'
        _tap(b, ok['cx'], ok['cy'], wait=2.5)
        log.append({'popup': 'reward_confirm'})
        return 'handled'

    x = find_x(items)
    if x:
        _tap(b, x['cx'], x['cy'], wait=1.8)
        log.append({'popup': 'close_x'})
        return 'handled'
    return 'none'


def save_board_frame(b, log, rnd=0, img=None):
    """存一张棋盘帧 → `<实例目录>/r_<HHMMSS>_<轮次>.png`

    ⚠ 多开隔离（2026-09-27）：**必须落 `b.runs`**（带 `--tag acc2` 时 = `runs/acc2/`）。
      以前写死公共 `RUNS` ⇒ 主号与 2 号的首帧会混进同一个 `runs/` ✗（时间戳撞车就互相覆盖）
    """
    try:
        import cv2 as _cv2
        if img is None:
            img = b.img()
        if img is None:
            log.append({'shot': 'no_img', 'rnd': rnd})
            return None
        _dir = getattr(b, 'runs', None) or RUNS
        os.makedirs(_dir, exist_ok=True)
        rp = os.path.join(_dir, 'r_%s_%s.png' % (time.strftime('%H%M%S'), rnd))
        _cv2.imencode('.png', img)[1].tofile(rp)
        log.append({'shot': 'saved', 'rnd': rnd, 'file': os.path.basename(rp)})
        say('   ★ 存图：%s' % rp)
        return rp
    except Exception as e:      # noqa: BLE001
        log.append({'shot': 'error', 'rnd': rnd, 'e': repr(e)[:120]})
        return None


def enter_map(b, log, timeout=40):
    """在选图界面点「进入地图」。

    ⚠ 2026-09-25 用户报「退图后乱点切换到别的图」：进图前先确认**确实在选图界面**
    （有「快速扫荡/进入地图」这类菜单文字），并且只点识别到的那个按钮；
    没确认到就等下一轮，绝不盲点（盲点就会点到别的图卡片上）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        b.snap('enter')
        img = b.img()
        items = b.ocr(tag='round')
        if in_map(b, img, items):
            log.append({'enter': 'in_map', 'stamina': stamina(items)})
            return True
        if fb(items, *L['kick']):
            return False
        # ⭐ 2026-09-27：**大厅**（游戏重启后常见）⇒ 点底部中间「开始冒险」离开，
        #   再等下一轮验证 ⇒ 不会白等到 40 秒超时 ✗（用户口径：「点中间的开始冒险」✓）
        if in_lobby(items) and go_lobby_to_menu(b, log, items=items):
            time.sleep(1.0)
            continue
        # 确认在「选图界面」（菜单文字在）再点进入地图；否则等着，绝不盲点
        on_menu = bool(fb(items, *L['menu'])) or any(
            ('快速扫荡' in i['text']) or ('进入地图' in i['text']) for i in items)
        ent = None
        for it in items:
            if L['enter'] in it['text'] and it['cy'] > LAYOUT.sy(933):
                ent = it
                break
        if ent and on_menu:
            # ⭐⭐⭐ 2026-10-01 用户报「刚刚不到 25 还去点击进入地图」⇒ **每次点之前都复查体力**：
            #   这个 while 循环等不到地图会**再点一次「进入地图」**（见上面 2026-09-25 的注释），
            #   而原来**只在进函数前查过一次** ⇒ 第二/第三次点就可能是"体力已经扣完还点" ✗
            #   （真机日志里 `{'enter':'clicked'}` 出现过两次连续条目）
            #   规则：读得到且 < MIN_STAMINA ⇒ 立刻放弃（不点）；读不到 ⇒ 记一条告警但仍点
            #   （外层 `ensure_in_map` 已经做过严格判定 ✓，这里只是防"循环内重复点"）
            # ⭐⭐⭐ 2026-10-02 提速审计（用户口径「尽量减少 OCR」）：**同帧复用，不重复 OCR**
            #   原来专门再 OCR 一次窄带 (0,140)（旧注释写"≈0.25s 更稳"），但实测 **不成立**：
            #   720p 下窄带 (0,140) 中位 **1.74s**、整屏才 0.92s（窄带反而更慢，见门禁㉔
            #   同款结论：RapidOCR 的耗时跟带高无关）⇒ 而这条窄带和上面 4908 那次
            #   **全屏 OCR 读的是同一帧** ⇒ 纯浪费一次调用 ✗
            #   离线对拍 8 张真机帧：`stamina(全屏 items)` 与 `stamina(窄带 items)` **完全一致** ✓
            #   ⇒ 现在：先**免费**从本帧 items 读；读不到（HUD 被挡等）才补一次窄带 ✓
            _st_now = stamina(items)
            if _st_now is None:
                try:
                    _st_now = stamina(b.ocr(band=(0, 140), tag='enter_stam'))
                except Exception:       # noqa: BLE001
                    _st_now = None
                log.append({'enter_stam': 'band_fallback', 'ok': _st_now is not None})
            if _st_now is not None and _st_now < MIN_STAMINA:
                log.append({'enter': 'skip_low_stamina', 'stamina': _st_now,
                            'min': MIN_STAMINA, 'at': (ent['cx'], ent['cy'])})
                say('   ⚠ 体力 %d < %d ⇒ 不点「进入地图」（防止白点/白扣）'
                    % (_st_now, MIN_STAMINA))
                return False
            if _st_now is None:
                log.append({'enter': 'stamina_unknown_still_click',
                            'texts': [i['text'] for i in items][:8]})
            # ⭐ 2026-10-01 PC 提速：**「进入地图」位置固定**，不必用 OCR 读到的 cy 去点。
            #   ⚠ 安全边界**一条都没放松**：仍然要求 `on_menu`（确认在选图界面）+
            #     `ent`（确实读到「进入地图」字样）+ 体力 ≥ MIN_STAMINA 才点。
            #     变的只是"点哪个 y"：用固定锚点代替 OCR 出来的坐标（720p 固定布局）。
            _fx_ent = fx_anchor('enter_map')
            if _fx_ent:
                tap_at = _fx_ent
            else:
                tap_at = (ent['cx'], ent['cy'])
            b.tap(tap_at[0], tap_at[1], wait=2.0)
            log.append({'enter': 'clicked', 'at': tap_at,
                        'ocr_at': (ent['cx'], ent['cy']),
                        'fixed': bool(_fx_ent),
                        'stamina_before': _st_now})
            # ⚠ 2026-09-25 用户报「一进图就点一下右下角」：原来点完没立刻认出地图
            #   **同一秒又点了一次**，第二下正好落在刚加载出来的地图上（看起来像乱点）。
            #   现在点一下就**等地图加载**（每秒看一次，最多 ~14 秒），期间处理弹窗。
            for _w in range(9):
                time.sleep(1.5)
                b.snap('enter_wait')
                img2 = b.img()
                # ⭐⭐⭐ 2026-10-02 提速审计：**便宜图像预筛**，省掉等待轮次里的整屏 OCR
                #   `in_map()` 的**正面证据**就是它最后那条：棋盘上有**亮格**（营地/已走开的格
                #   ratio≥0.75，v1.15 为治「选图界面预览图被数成格子」加的）——
                #   这条用 `cells_of` 就能先判（≈0.35s、**0 OCR**）：
                #     不亮 ⇒ 这一轮**几乎肯定还没进图** ⇒ 跳过 OCR（只花 0.35s）
                #     亮   ⇒ 再付一次 OCR，跑**原封不动的** `in_map()`（判据一个字没改 ✓）
                #   ⚠ 兜底：**每 3 轮强制 OCR 一次** ⇒ 万一 `cells_of` 这次没看出亮格，
                #     也不会一路空转到 40 秒超时（原来每轮都 OCR ⇒ 最多 9 次；
                #     现在典型 1~2 次，最坏 3 次）✓
                _looks_in = True                       # 默认"要 OCR"（fail-safe）
                if _w % 3 != 0:
                    try:
                        # 2026-10-27 need_names=False：这里只判「有没有亮格」
                        #   => 不需要地块名 => 跳过全量消歧（省时间 + 不打那句）
                        _c2 = cells_of(img2, need_names=False)
                        try:
                            _mx2 = max([float((v or {}).get('ratio') or 0)
                                        for v in (_c2.get('st') or {}).values()] or [0.0])
                        except Exception:              # noqa: BLE001
                            _mx2 = 0.0
                        _looks_in = bool(_c2.get('light')) and _mx2 >= 0.75
                    except Exception:                  # noqa: BLE001
                        _looks_in = True
                if not _looks_in:
                    log.append({'enter_wait': 'skip_ocr', 'w': _w,
                                'note': '图像预筛：没有亮格 ⇒ 这轮不 OCR（省 ~0.9s）'})
                    continue
                it2 = b.ocr(tag='round')
                if in_map(b, img2, it2):
                    log.append({'enter': 'in_map', 'stamina': stamina(it2)})
                    return True
                if fb(it2, *L['kick']):
                    return False
                act = popups(b, it2, log)
                if act == 'kicked':
                    return False
            continue
        if not on_menu:
            log.append({'enter': 'not_menu_yet',
                        'texts': [i['text'] for i in items if i['cy'] > LAYOUT.sy(900)][:8]})
        time.sleep(1.5)
    log.append({'enter': 'timeout'})
    return False


def enter_with_retry(b, log, tag='', items0=None, tries=2):
    """进图（**设备瞬断时先重连再试一次**）—— 治「进图这一步出错（已跳过这张图）」

    ⭐⭐⭐⭐ 2026-10-05 真机事故（用户贴的日志）：
        `AdbError(b'', b"adb.exe: device '127.0.0.1:16384' not found\\r\\n")`
        ⇒ `run_maps` 里 `ensure_in_map` 一抛异常就**跳过这张图**（体力照扣 ✗）
        ⇒ 真机连丢两张（`gui_20261005_143017_acc2.log` 里连着两条同一个错）
    而"设备暂时不在 adb server 的设备表里"**几乎都是瞬断**（server 被重启 / 模拟器
    adb 桥抖一下），`adb connect` + `wait-for-device` 就能恢复（实测：报错那两分钟之后
    设备自己又回来了）⇒ **值得重连重试一次**，而不是白扔一张图 ✗

    ⚠ 只对**连接类**错误重试（`mapbot._is_conn_err`）；其它异常**原样上抛** ——
      逻辑错误重试只会白花时间、掩盖真 bug（与 `_touch_retry` 同一口径 ✓）
    ⚠ 重试仍失败 ⇒ 原样抛给调用方（那里照旧记日志 + 跳图 + 连续 3 次收工 ✓）
    """
    tries = max(1, int(tries or 1))
    for i in range(tries):
        try:
            return ensure_in_map(b, log, tag=tag, items0=items0 if i == 0 else None)
        except Exception as e:          # noqa: BLE001
            _conn = _is_conn_err(e)
            try:
                log.append({'enter_retry': i + 1, 'of': tries,
                            'conn_err': bool(_conn), 'err': repr(e)[:200]})
            except Exception:           # noqa: BLE001
                pass
            if i + 1 >= tries or not _conn:
                raise
            say('   ⚠ 进图报连接类错误（%s）⇒ 重连 adb 再试一次…' % repr(e)[:90])
            try:
                b.reconnect()
            except Exception as e2:     # noqa: BLE001
                try:
                    log.append({'enter_reconnect_failed': repr(e2)[:200]})
                except Exception:       # noqa: BLE001
                    pass
    raise RuntimeError('enter_with_retry 未返回（不该发生）')


def ensure_in_map(b, log, tag='', items0=None):
    for a in range(4):
        if a == 0 and items0:
            # ⭐ 2026-10-02 提速审计：调用方（`run_maps`）**刚为同一帧读过一次 OCR**
            #   （进图前那次 `pre`：画面特征 + 顶号 + 体力）⇒ 第 0 轮直接复用它，
            #   省掉一次整屏 OCR（≈0.9s/图）✓
            #   ⚠ 只有第 0 轮能复用（后面每轮都可能点过面板/换过画面）；
            #     且这里**故意不重新 snap** —— 保证 `items` 与 `b.img()` 是**同一帧** ✓
            items = list(items0)
        else:
            b.snap('%schk%d' % (tag, a))
            items = b.ocr(tag='round')
        img = b.img()
        # ⭐⭐ 2026-09-29 真机：画面是 MGAS 自己的界面/应用双开选择框 ⇒ 别再乱点
        #   （点下去全是自己的按钮），直接把原因讲清楚让人处理 ✓
        if self_ui_hits(items) >= 2:
            log.append({'pre': 'self_ui', 'attempt': a})
            say('⚠ 画面是 MGAS 自己的界面/应用选择框（游戏没在前台）')
            say('   ⇒ 请手动切到游戏、到「选图界面」后再点 ▶ 重试')
            say('   ⇒ （手机上若开了「应用双开」，切游戏会弹选择框 ⇒ 关掉双开即可）')
            status('⚠ 请先切到游戏，再点 ▶')
            flush(log)
            return False
        if in_map(b, img, items):
            _remember_items(b, items)      # ⭐ 记下这帧 items（供进图后读体力复用 ✓）
            return True
        act = popups(b, items, log)
        if act == 'kicked':
            return False
        n = close_x_panels(b, img)
        st = 'lobby' if in_lobby(items) else ('menu' if is_map_screen(items) else 'other')
        log.append({'pre': 'not_in_map', 'attempt': a, 'act': act,
                    'closed_x': n, 'state': st})
        flush(log)
        if act == 'none' and n == 0:
            # ⭐⭐ 2026-09-27 用户口径：「点中间的开始冒险就能回到选图界面」
            #   场景：采图中途**游戏自己重启** ⇒ 停在大厅 ⇒ 老逻辑到这就 break，
            #   接着 enter_map() 在非选图界面里等 40 秒 → 超时 → 整个任务中断 ✗
            #   现在：认出大厅就点「开始冒险」，回头再验一次 ⇒ 重启自愈 ✓
            if go_lobby_to_menu(b, log, items=items):
                continue
            break
    # ⭐⭐⭐ 2026-10-02 提速审计：**同一帧不要读两遍**
    #   这里原来又调了一次 `b.ocr(tag='round')`（整屏 ≈0.92s），只为读体力数字；
    #   而上面循环里 5071 那次整屏 OCR 的 `items` **就是同一帧**（中间没点任何东西
    #   —— 点过就会 `continue` 再循环一次、重新 OCR ✓）⇒ 直接复用它 ✓
    #   读不到（HUD 被挡/面板盖着）才补一次，并落一条日志，绝不静默 ✗
    try:
        _items_last = items                 # 循环里那次整屏 OCR 的产物（同一帧）
    except NameError:                       # 理论上到不了（range(4) 至少跑一次）
        _items_last = []
    st = stamina(_items_last)
    if st is None:
        st = stamina(b.ocr(tag='round'))
        log.append({'stamina': 're_ocr', 'note': '本帧 items 读不到体力 ⇒ 补一次整屏 OCR'})
    else:
        log.append({'stamina': 'reuse_items', 'value': st})
    # ⭐⭐ 2026-10-01 修（用户报「进图前怎么不检查体力」）：
    #   ① 老写法 `if st is not None and st < MIN_STAMINA` ⇒ **读不到体力就整段跳过检查、
    #      直接进图** ✗（fail-open）。现在：读不到就**换窄带(0~140)再读一次**（≈0.25s ✓ 更稳），
    #      两次都读不到才放行，但**明确 say 出来**（不留静默 ✗）
    #   ② 门限一律打进日志（`下限 N`）—— 安卓悬浮条那条调用曾把 min_stamina 写死 25，
    #      连刷模式下也是 25，日志却写着「连刷下限」⇒ 以后一眼能对出来 ✓
    if st is None:
        # ⭐⭐⭐ 2026-10-01 用户报「刚刚不到 25 还去点击进入地图」⇒ **fail-open 改成 fail-closed**：
        #   读不到体力就**不许进图**（多读几次，都读不到就停下并说明原因）。
        #   老写法是"读不到 ⇒ 跳过检查 ⇒ 照样进图" ✗ —— 体力见底时这一下就是白点/白扣。
        #   ⚠ 顺手把"读不到"的原因**落盘 + 打出来**（窄带读不到 ⇒ 再试全屏 ⇒ 还不行就存帧 +
        #     打顶部那几条文字）——体力必须在 ≤130 且 x<560 的 HUD 格里且**斜杠与数字在
        #     同一条 OCR 文本**里（实测那条 OCR 通常给的就是 `11/2500` 一整条 ✓；
        #     会读不到多半是 ① 被面板/加载盖住 ② 被拆成两条 ✗）
        for _k in range(3):
            time.sleep(1.2)
            _its = b.ocr(band=(0, 140), tag='pre_stam%d' % _k)
            st = stamina(_its)
            if st is None:
                _its2 = b.ocr(tag='pre_stam_full%d' % _k)      # 再给一次全屏机会 ✓
                st = stamina(_its2)
                if st is None:
                    _pub_dump('stamina_fail%d' % _k, b.img())
                    say('   · 体力读不到（第 %d 次）｜顶部认到：%s'
                        % (_k + 1, [i['text'] for i in (_its2 or _its)
                                   if i.get('cy', 9999) < 200][:8]))
            log.append({'pre': 'stamina_retry', 'n': _k + 1, 'stamina': st})
            if st is not None:
                break
        if st is None:
            log.append({'stop': 'stamina_unknown', 'min': MIN_STAMINA})
            say('   ⚠ 连续 3 次读不到体力 ⇒ **不进图**（无法确认够不够 %d）' % MIN_STAMINA)
            # ⭐ v1.07：悬浮条要说清"为什么停"，否则用户会以为脚本坏了（见下面 no_stamina 同因）
            status('体力读不到（要 ≥%d）· 先不进图，请看一眼体力' % MIN_STAMINA)
            return False
    say('   进图判定：体力 %s ｜ 下限 %d ｜ 自动补给 %s'
        % (st if st is not None else '?', MIN_STAMINA, '开' if AUTO_SUPPLY else '关'))
    log.append({'pre_gate': 'stamina', 'stamina': st, 'min': MIN_STAMINA,
                'auto_supply': bool(AUTO_SUPPLY)})
    if st is not None and st < MIN_STAMINA:
        # ⭐ 用户 2026-09-25：「加个自动使用结实补给的按钮（没体力就自动去背包里使用一个）」
        if AUTO_SUPPLY:
            log.append({'supply': 'try_before_giveup', 'stamina': st,
                        'min': MIN_STAMINA})
            for attempt in range(2):
                # ⚠⚠ 2026-10-02 修「PC 端用不了」（GUI 日志 gui_20261002_013006.log：
                #   第 2 张图进图前**无 traceback 退出码 1**）：原来这里 `use_supply(b, log)`
                #   是**裸调用** —— 它内部一旦抛异常（背包面板坐标/模板缺失/OCR 返回 None…），
                #   异常会一路穿出 `ensure_in_map` ⇒ **整条循环崩溃**，连
                #   `runs/<tag>/_crash.log` 都来不及写（实测那个文件根本没生成）✗
                #   ⇒ 补给是**锦上添花**功能，绝不该把"刷图主流程"带走：单次失败记日志后继续试，
                #     最坏退回下面那段"体力不够就正常收工"（用户口径里那就是正常结束）✓
                try:
                    _used = use_supply(b, log)
                except Exception as _e4:      # noqa: BLE001
                    _used = False
                    log.append({'supply': 'use_supply_raised', 'attempt': attempt + 1,
                                'e': repr(_e4)[:160]})
                    say('   ⚠ 用补给这一步报错（已跳过，不影响刷图）：%r' % (_e4,))
                if not _used:
                    break
                try:
                    st2 = stamina(b.ocr(band=(0, 140), tag='round'))
                except Exception as _e5:      # noqa: BLE001
                    st2 = None
                    log.append({'supply': 'stamina_read_raised', 'attempt': attempt + 1,
                                'e': repr(_e5)[:160]})
                log.append({'supply': 'after_use', 'attempt': attempt + 1,
                            'stamina': st2})
                # ⭐ 标记"刚吃过补给" ⇒ _stam_sanity 不再把这次真实涨幅当 OCR 误读 ✗
                STATS['supply_used'] = True
                if st2 is not None and st2 >= MIN_STAMINA:
                    say('   用了补给，体力 %s ≥ %d，继续刷' % (st2, MIN_STAMINA))
                    status('体力不够 · 已用结实补给，继续')
                    return enter_map(b, log)
            # ⚠ 2026-10-02 同源修：`stamina(...) or st` 读不到体力时会把 None 当 0 传下去
            #   （`None or st` 其实是 st，安全；但 `st` 也可能是 None ⇒ 下面 `st < MIN_STAMINA`
            #   比较虽被 `is not None` 挡住，本行仍可能抛）⇒ 显式兜底，别让不确定值流下去。
            try:
                _st_chk = stamina(b.ocr(band=(0, 140), tag='round'))
            except Exception as _e6:          # noqa: BLE001
                _st_chk = None
            if _st_chk is not None:
                st = _st_chk
        if st is not None and st < MIN_STAMINA:
            log.append({'stop': 'no_stamina', 'stamina': st, 'min': MIN_STAMINA,
                        'auto_supply': bool(AUTO_SUPPLY)})
            say('   体力 %d < %d（连刷下限），收工' % (st, MIN_STAMINA))
            # ⭐⭐⭐ 2026-10-01 v1.07 用户报「怎么连启动都启动不了了，完全用不了」
            #   —— 其实是**体力低于下限就正常收工**（一次点击都没做），但这句提示原先
            #   只进控制台（`say`），悬浮条上只写「体力不够了 · 收工」⇒ 用户看不到
            #   **差多少 / 下限是多少 / 自动补给是关的** ⇒ 以为脚本坏了 ✗
            #   ⇒ 悬浮条改成**可操作**的一句话：把三个数都写出来 + 给出怎么办 ✓
            #     ⚠ 文案避开 OCR 关键词（探索/派遣/领取/关闭/开始冒险…）—— 见硬约束③与
            #       `OverlayService.sanitize()`：否则会被糊成 ▓ ✗
            _tips = ('开自动补给可自动吃结实补给'
                     if not AUTO_SUPPLY else '补给没吃够，请手动补一次')
            status('体力 %d 不足（要 %d）· %s' % (st, MIN_STAMINA, _tips))
            # ⭐ v1.08：把原因也写进 `STATS['stopped']` ⇒ 收工那行（以及统计面板）都会带上它 ✓
            STATS['stopped'] = '体力 %d 不足（要 %d）' % (st, MIN_STAMINA)
            return False
    return enter_map(b, log)


# ⚠⚠ 2026-10-02：底部导航**大页面**的特征词（斗技场 / 角色 / 图鉴 / 公会 …）。
#   它们不是弹窗 ⇒「点中间最下面」那个万能位关不掉 ⇒ 旧逻辑只能空转到超时。
#   认到其中任意一个 ⇒ 说明用户（或误点）离开了探索流程 ⇒ 走底部导航回大厅 ✓
_BIG_PAGE_HINTS = ('斗技场', '查看战斗', '挑战赛', '巅峰赛', '模拟赛', '图鉴',
                   '邀请赛', '角色', '公会')


def _escape_to_lobby(b, log, items):
    """从「斗技场/角色/图鉴…」这类大页面 回大厅 —— 认到才动，绝不盲点

    ⚠ 2026-10-02 加这个的原因（GUI 日志 gui_20261002_014151.log）：
      退图阶段遇到斗技场 ⇒ 反复点万能位 ⇒ 空转 20 多轮 ⇒「退图没成功，已停止」。
      根因：这些是**大页面不是弹窗**，万能位对它们无效 ⇒ 没有任何分支能命中。

    做法：点底部中间的「开始冒险」导航（固定锚点 `start_adv_icon`）回大厅，
      之后由 `ensure_in_map` / `enter_map` 从大厅点回选图界面。

    ⚠ 安全边界：**必须 OCR 真认到大页面特征词**才点（绝不盲点万能位）；
      且已经在图里/已经在大厅就什么都不做 ✓
    """
    if not items:
        return False
    txt = [i.get('text') or '' for i in items]
    hit = next((t for t in txt if any(h in t for h in _BIG_PAGE_HINTS)), None)
    if not hit:
        return False
    fx_adv = fx_anchor('start_adv_icon')
    if not fx_adv:
        log.append({'escape_lobby': 'no_nav_anchor'})
        return False
    log.append({'escape_lobby': 'big_page', 'hit': hit, 'at': list(fx_adv)})
    say('   · ⚠ 画面跑到「%s」这类大页面了（不是弹窗，关不掉）⇒ 点底部导航回大厅'
        % hit.strip()[:10])
    b.tap(fx_adv[0], fx_adv[1], wait=2.6)
    status('跑到别的页面了 · 已点导航回来')
    return True


_CELLS_CACHE = {'stamp': None, 'key': None, 'val': None}
# ⭐ 2026-10-02：最近一次**整屏 items** + 它属于哪一帧（`b._snap_n`）
#   用途：进图成功后 `run_maps` 还要读一次体力（只用于日志）—— 那份 items 就在手边，
#   同一帧直接复用，不必再付一次 OCR（见 `enter_stam: reuse_items` 那处）✓
_LAST_ITEMS = {'stamp': None, 'items': None}


def _remember_items(b, items):
    """记下"这份 items 是哪一帧的" ✓（帧号变了就不许复用）"""
    _LAST_ITEMS['stamp'] = getattr(b, '_snap_n', None)
    _LAST_ITEMS['items'] = items


def _cells_cached(b, img, mapname=None, code=None):
    """同帧的分类结果缓存 —— `cells_of()` 是**纯函数**（同一帧 + 同一入参 ⇒ 同结果）✓

    ⭐ 2026-10-02 提速审计：`cells_of` 单次 **0.47s**（模板匹配），而真机日志显示
      **一轮里它被调 1~3 次**（`one_round` 轮首判面板 + 常规分类 + 暗罩复查各一次）
      ⇒ 同一帧重复调纯属白花。缓存 key = `(帧号, mapname, code)`，
      **帧号取 `b._snap_n`**（每次 `snap`/`tap` 都会 +1 ⇒ 画面一变必然 miss ✓）。
    ⚠ 这不是"猜画面没变"（那是 09-28 被否决的跳帧复用✗）—— 是**同一帧对象**的复用，
      帧号不同就一定重算，所以**结果逐字节可证相同** ✓
    """
    stamp = getattr(b, '_snap_n', None)
    key = (mapname, code)
    if (stamp is not None and _CELLS_CACHE['stamp'] == stamp
            and _CELLS_CACHE['key'] == key and _CELLS_CACHE['val'] is not None):
        return _CELLS_CACHE['val']
    val = cells_of(img, mapname=mapname, code=code)
    _CELLS_CACHE['stamp'] = stamp
    _CELLS_CACHE['key'] = key
    _CELLS_CACHE['val'] = val
    return val


def _ocr_cached(b, tag, cache):
    """同帧就别再 OCR（画面没变 ⇒ 结果一样）—— buypanels 那套同帧缓存的同款做法 ✓

    ⭐ 2026-10-02 提速审计：OCR 每次 **0.5~0.9s**（实测；且**与带高无关**、窄带反而更慢），
      所以唯一的杠杆是**少调**。`finish_map` 的循环每轮都整屏 OCR 一次只为看"回没回选图界面"，
      而很多轮次之间**一个点击都没发生过**（纯 idle 等待）⇒ 画面没变，结果必然一样。
      ⇒ 判据用 `mapbot.Bot.board_luma()`（buypanels 也是这么判的，阈值 0.8 同源）
      ⚠ 这是**纯缓存**，不引入任何新判断依据；命中与否都返回同一份 items 语义 ✓
    """
    try:
        _now = b.board_luma()
    except Exception:                       # noqa: BLE001
        _now = None
    if (cache.get('items') is not None and _now is not None
            and cache.get('luma') is not None
            and abs(_now - cache['luma']) < 0.8):
        cache['hit'] = cache.get('hit', 0) + 1
        return cache['items']
    b.snap(tag)
    _it = b.ocr(tag=tag)
    try:
        cache['luma'] = b.board_luma()
        cache['items'] = _it
    except Exception:                       # noqa: BLE001
        pass
    return _it


def finish_map(b, log, timeout=90, mapname=None):
    """结束冒险 → 回选图界面

    ⭐⭐⭐ 2026-10-26 **加 `mapname` 参数**（治「结束了还要读图名字」）
      ---- 用户报（原话）----
        「为什么结束了还要读图名字？」
      ---- 真机铁证（runs/gui_console_20261026.log，22:41 那把）----
        22:41:47  本图结束：done（耗时 38 秒）
        22:41:56  · 图名「（图名未读到）」有歧义 [15 个代码] ⇒ 实测选 S00003（高分格 21）✓
        22:42:00  · 已回到选图界面（模板判据 7ms · 省掉一次 OCR ✓）
        22:42:00  · 退图细账：图上 38.4s ｜ **退图 13.0s**
      ---- 根因（读代码即可证）----
        本函数里 `board_hidden(_cells_cached(b, b.img(), mapname=''))`（`:8016`）
        传的是 **空串** ⇒ `board_state('')` ⇒ 「图名为空 ⇒ 全部 code 当候选」
        ⇒ **15 个 code 各建一次盘**（≈4 秒）⇒ 打出那句「（图名未读到）」✗✗
        ⇒ 而**退图时根本不需要知道地块名** —— `board_hidden` 只看
          「有多少格被压暗」，但它的 `ratio` 分母 = **模板亮度** ⇒ 需要**正确的 code** ✓
      ---- ⚠⚠ 这是我 10-26 那次修复的**副作用**（诚实记账）----
        修复前：首轮那次全量消歧会**顺手填** `_CODE_DECIDED['']`
        ⇒ 退图时 `mapname=''` 命中缓存 ⇒ 不再消歧 ⇒ **看不到那句**
        修复后：首轮**跳过**了 ⇒ `_CODE_DECIDED['']` 一直是空
        ⇒ 退图时**第一次**做全量消歧 ⇒ **那句冒出来了** + 多花 4 秒 ✗
        ⇒ 修法：**把当前图的图名传进来**（`st['mapname']` 早就在手上 ✓）
        ⇒ `_CODE_DECIDED[图名]` 早被图内分类填好 ⇒ **零消歧、零 OCR、零日志** ✓
        ⇒ 额外好处：`board_hidden` 拿到**正确的 code** ⇒ ratio 算得准 ⇒ 判据更准 ✓
    ⚠ 2026-09-25：退图时**经常弹确认框**（「还有未拾取的战利品 / 是否结束冒险？」），
      按钮是 确定(774,1113) / 取消(305,1113) —— 只点靠右的那个，绝不点取消；
      另外还可能先弹结算面板（底部「关闭」）或奖励领取，都要先处理掉。
    """
    t0 = time.time()
    clicked = 0
    end_tapped_at = 0.0        # ⭐ 上次点「结束冒险」的时间（防连点 ✗）
    idle = 0                   # ⭐ 2026-09-26：连续"什么都认不到"的轮数
    # ⭐⭐ 2026-09-26 用户口径：「万能点位可以用来应对异常情况，防止任务过早中断」✓
    _rescued = False           # 退图快超时时是否已用万能位救过一次
    _fin_cache = {}            # ⭐ 2026-10-02：同帧 OCR 缓存（见 `_ocr_cached`）
    while time.time() - t0 < timeout:
        # ⭐⭐ 退图快超时 ⇒ 万能位**最后救一次**，并把截止时间**延后 20 秒**再继续跑 ✓
        #   老逻辑：超时就直接 `finish: timeout` + return False ⇒ **任务在这里中断** ✗
        #   现在：先让万能位（关得掉几乎所有弹窗，且点它无副作用）救一手，再多给 20 秒 ✓
        #   ⚠ 依然先认面板类型：战斗界面点「关闭」(577,1439)，绝不点开始冒险 ✓
        if not _rescued and timeout > 20 and time.time() - t0 > timeout - 6:
            _rescued = True
            universal_close(b, log, items=b.ocr(tag='fin_to'), where='finish_timeout')
            log.append({'universal_fallback': 'finish_timeout'})
            say('       · 退图快超时 → 万能位兜底关面板（截止时间延后 20 秒）')
            status('退出超时 · 强行脱困')
            timeout += 20.0
            continue
        b.snap('finish')
        # ⭐⭐⭐ 2026-10-02 提速：**先问最便宜的那个问题** ——「回到选图界面了吗？」
        #   模板快查 ≈7ms（vs 一次整屏 OCR 0.78s）⇒ 命中就直接收工，
        #   这一轮**连 OCR 都省了** ✓（阈值 0.80：宁可漏判退回 OCR，绝不误判）
        if fx_menu(b):
            log.append({'finish': 'back_to_menu', 'by': 'tpl_enter_map_btn'})
            say('       · 已回到选图界面（模板判据 7ms · 省掉一次 OCR ✓）')
            return True
        # ⭐ 2026-10-02 提速审计：改成**同帧缓存**读 items（画面没变就不 OCR，省 0.9s/轮）
        items = _ocr_cached(b, 'finish', _fin_cache)
        if fb(items, *L['menu']):
            log.append({'finish': 'back_to_menu'})
            return True
        # ⭐ 2026-09-27：**大厅**也算"已离开地图"⇒ 直接收工 ✓
        #   场景：退图途中游戏自己重启 ⇒ 停在大厅 ⇒ 老逻辑所有分支都不命中，
        #   一路 idle 到第 4 轮就 `universal_close()` 盲点 (541,1890)（就是大厅的「开始冒险」），
        #   或更糟 —— 90 秒 `finish: timeout` ⇒ 整个任务中断 ✗
        if in_lobby(items):
            log.append({'finish': 'lobby'})
            say('       · 已在大厅（退图途中重启过）⇒ 本轮按退图完成处理 ✓')
            return True
        # ①' 「发现莱姆！」/「获得新装备！」弹窗 → 点**写死**的返回位
        #   ⛔⛔⛔ 2026-10-02 修**我上一笔引入的严重回归**（用户当场发现）：
        #   我在这里加了 `or panel_seen(items, b=b)` 当兜底判据 ——
        #   ⚠ `panel_seen()` 在**地图界面**也常常为真（HUD/槽位行/结算残留都能命中）
        #     ⇒ 于是**每一轮都去点那个写死坐标** ⇒ 规划被反复打断、点序全乱，
        #       而且刚进图没多久就莫名其妙弹「莱姆」处理日志 ✗✗✗
        #   ⇒ **写死坐标只用在「确定是奖励弹窗」的地方**，
        #     判据必须**窄**：只认 OCR 读到的标题文字（莱姆/新装备），
        #     **绝不用 `panel_seen` 兜底**（它太宽，会误伤正常地图界面）。
        #   ⇒ 「标题 OCR 读不出」那个老问题交给 `final_collect()` 的轮询
        #     （那里本来就在「退图前最后一次点击之后」，上下文确定）✓
        #   ⛔⛔ 2026-10-12：莱姆改走 `_lime_popup_title`（**独立成条** ✓）
        #     —— `fb(items,'莱姆')` 会被**预言卡正文**（"…至少出现1只莱姆…"）骗到 ✗
        if _lime_popup_title(items) is not None or fb(items, *L['newequip']):
            lb = lime_back(items)
            if lb:
                b.tap(lb['cx'], lb['cy'], wait=1.8)
                log.append({'finish': 'reward_back', 'at': (lb['cx'], lb['cy']),
                            'fixed': True})
                continue
        # ①'' 「获得新装备！」→ 点返回（2026-09-26：盖住棋盘 ⇒ 认不到「结束冒险」⇒ 90 秒超时）
        if close_newequip(b, items, log, 'finish'):
            say('       · 获得新装备！→ 点返回')
            continue
        # ①''' 「预言石板」→ 点中间最下面（万能位）关掉
        #   ⛔ 2026-10-10：**预言石碑除外**（该领掉 ✗）—— 第 5 处（退图流程里的）✓
        if fb(items, *L['prophecy']) and not _is_foretell_panel(items):
            universal_close(b, log, items=items, probe=L['prophecy'][0], where='finish')
            say('       · 预言石板 → 点中间最下面关掉')
            continue
        # ①'''' 「预言石碑」⇒ **领掉它**（用户口径：预言白拿，不该关掉 ✓）
        if _is_foretell_panel(items):
            say('       · 预言石碑 → **领掉**（不关掉 ✓）')
            try:
                buypanels.foretell_flow(
                    b, log, flags={'stop_peace_metal': STOP_PEACE,
                                   'stop_elem_purple': STOP_ELEM_PURPLE,
                                   'stop_elem_orange': STOP_ELEM_ORANGE})
            except Exception as _fe7:      # noqa: BLE001
                log.append({'foretell': 'finish_flow_error', 'e': repr(_fe7)[:100]})
            continue
        # ①'' 「偶遇强敌」→ 不打，点 X 关掉（用户 2026-09-25 报退图流程被它卡住）
        if fb(items, *L['strong']):
            x = find_x(items)
            if x:
                b.tap(x['cx'], x['cy'], wait=1.5)
            else:
                close_x_panels(b, b.img())
            log.append({'finish': 'strong_closed',
                        'closed_at': (x['cx'], x['cy']) if x else None})
            continue
        # ① 结算/奖励面板：底部「关闭」
        cl = bottom_close(items)
        if cl:
            b.tap(cl['cx'], cl['cy'], wait=1.8)
            log.append({'finish': 'closed_result'})
            continue
        # ② 确认弹窗：确定/确认/是（取最靠右的，避开「取消」）
        # ⚠⚠ 2026-10-02 修「退图必超时」：原来要求 `cy > LAYOUT.sy(800)`（=800）。
        #   实测真帧（runs/r_040316_0.png，OCR 逐字量过）退图确认框是**居中弹窗**：
        #       提示 cy=505 / 正文 cy=593 / 取消 cx=203 cy=742 / 确定 cx=516 cy=742
        #   ⇒ 确定在 cy=742，**永远小于 800** ⇒ 这条分支一次都命不中
        #   ⇒ 弹窗关不掉，卡在它上面空转到 90 秒超时 ⇒ 每张图都「退图失败」。
        #   修法：放宽到 `sy(600)`（居中弹窗按钮带 700~760），并保留
        #   「取最靠右 ⇒ 一定是确定不是取消」这条安全判据 ✓
        ok = None
        for it in items:
            if it['text'].strip() in ('确定', '确认', '是') and it['cy'] > LAYOUT.sy(600):
                if ok is None or it['cx'] > ok['cx']:
                    ok = it
        if ok:
            b.tap(ok['cx'], ok['cy'], wait=2.5)
            log.append({'finish': 'confirmed', 'at': (ok['cx'], ok['cy'])})
            continue
        # ③ 领取 / 继续
        cl2 = fb(items, *L['claim'])
        if cl2 and cl2['cy'] < LAYOUT.sy(1133) and len(cl2['text']) <= 4:
            b.tap(cl2['cx'], cl2['cy'], wait=2)
            log.append({'finish': 'claimed'})
            continue
        # ④ 结束冒险
        end = exb(items, L['end'])
        if end:
            # ⚠ 2026-09-26 用户报「结束冒险还是会多点一下（可能导致切换地图）」：
            #   上一版点完只在一个窄带里找确认按钮，找不到就进下一轮 ⇒ 又看到「结束冒险」
            #   ⇒ 再点一次 ✗；那时弹框/画面可能已经变了 ⇒ 第二下落在**地图卡片**上 ⇒ 切图 ✗
            #   ⇒ 现在：点过一次后 **8 秒内绝不再点「结束冒险」**，只等确认框或等切到选图界面 ✓
            if time.time() - end_tapped_at < 8.0:
                time.sleep(1.0)
                continue
            clicked += 1
            if clicked > 3:
                n = close_x_panels(b, b.img())
                if not n:
                    x = find_x(items)
                    if x:
                        b.tap(x['cx'], x['cy'], wait=1.5)
                clicked = 0
                log.append({'finish': 'close_panel_retry'})
                continue
            b.tap(end['cx'], end['cy'], wait=2.5)
            end_tapped_at = time.time()
            log.append({'finish': 'clicked_end', 'at': (end['cx'], end['cy'])})
            # 等确认框：找「确定/确认」（取最靠右的 = 确定，避开"取消"），
            # 最多等 ~4 秒，等到就点掉；等不到也不回头乱点 ✓
            # ⭐ 2026-09-28 提速（P0）：原版每轮 `sleep(0.5)` + **全屏 OCR**（0.8s/次），
            #   而且循环里不重截帧 ⇒ 8 次基本在对**同一帧**反复 OCR（纯浪费，实测一轮
            #   退图能烧 6~10 秒）。确认按钮固定在 cy>700、cx>420 ⇒ 改 **band OCR**
            #   （~0.3s/次）+ `wait_change` 等弹框出现（画面一变立刻看，不再死等）✓
            # ⭐ 二次修正：3 张实测全是 `end_no_dialog` —— 多数情况**根本不弹确认框**
            #   （没有未拾取战利品），8 轮白等 ~7s ⇒ 砍到 **3 轮**（~2s）：真弹框
            #   一般 1~2 轮内出现；万一出现得晚，**外层轮询自己就有「确定/确认」分支**
            #   （上方 ②）兜底，不会漏 ✓
            ok2 = None
            # ⭐⭐⭐ 2026-10-02 提速：**先用图像判"结束确认框弹了吗"**（0 OCR）
            #   真机实测 3 张全是 `end_no_dialog` —— **多数情况根本不弹框**，
            #   而这 3 轮每轮都要 `wait_change(0.6)`/`sleep(0.5)` + 一次窄带 OCR(0.3s)
            #   ⇒ 白等 **1.5~2s/图** ✗
            #   ⚠ 为什么**不能**像 `fin_univ` 那样"先盲点固定坐标"：
            #     结束确认框的「确定」在 **(516,742)**，而**没有框时那里正是棋盘格 (1,6)**
            #     ⇒ 盲点会点到格子上（可能弹面板/开战）✗
            #     （`fin_univ` 那次固定位在 HUD 安全区，所以能盲点 —— 别照搬）
            #   ⇒ 用 `board_hidden`（确认框是模态 + 压暗棋盘 ⇒ dim 计数命中）来判：
            #     判"没框" ⇒ **这 3 轮整段跳过**（省 3 次 OCR + 1.5s 等待）✓
            #     判"有框"或判不出来 ⇒ 照旧走原逻辑（保守，行为不变）✓
            _cc_need = True
            try:
                # ⭐⭐⭐ 2026-10-26 **用当前图的图名**（不再用空串 ⇒ 不做全量消歧）
                #   详见 `finish_map` 的 docstring 那段（真机 22:41 的日志铁证）
                #   ⚠ 拿不到图名时仍传 '' ⇒ 退回到旧行为（全量消歧，兜底保留）✓
                _cc_need = bool(board_hidden(
                    _cells_cached(b, b.img(), mapname=(mapname or ''))))
            except Exception:                   # noqa: BLE001
                _cc_need = True
            if not _cc_need:
                log.append({'end_confirm': 'skip_no_dialog',
                            'note': '图像判无确认框 ⇒ 省掉 3 轮 OCR + 等待'})
            for _wait in range(3 if _cc_need else 0):
                if b.fast_ok:
                    b.wait_change(0.6, band=(int(LAYOUT.sy(400)), int(LAYOUT.sy(1000))),
                                  thr=4.0, min_sec=0.15)
                else:
                    time.sleep(0.5)
                it_after = b.ocr(min_conf=0.35,
                                 band=(int(LAYOUT.sy(453)), int(LAYOUT.sy(1000))), tag='pre')
                for t in it_after:
                    s2 = t['text'].strip()
                    if s2 in ('确定', '确认') and t['cy'] > LAYOUT.sy(700) and t['cx'] > LAYOUT.sx(420):
                        if ok2 is None or t['cx'] > ok2['cx']:
                            ok2 = t
                if ok2:
                    break
            if ok2:
                b.tap(ok2['cx'], ok2['cy'], wait=2.5)
                log.append({'finish': 'end_confirmed', 'at': (ok2['cx'], ok2['cy'])})
            else:
                log.append({'finish': 'end_no_dialog'})
            continue
        # ⭐⭐ 2026-09-26（rendslot 实测）：面板盖住棋盘时 OCR **根本看不到「结束冒险」**，
        #   于是上面每个分支都不命中 ⇒ 一直 sleep 到 90 秒 timeout ⇒ "退图没成功，已停止"
        #   （诱因常常是退图前那一下"补点"点出了面板）⇒ 认不到东西就先清面板再试
        # ⭐⭐⭐ 2026-10-02 修「还是运行不了」（GUI 日志 gui_20261002_014151.log）：
        #   症状：用户手动点了一下底部「斗技场」，游戏还在加载；bot 随后进图/退图，
        #     退图阶段 `idle>=4` 反复走下面那段「万能位清面板」⇒ 每 5~6 秒重复点
        #     **(541,1890) / (539,1212) / (493,225)** 三个坐标，**空转 20 多轮直到超时**，
        #     最后「⚠ 退图没成功，已停止」⇒ 一张都没刷成 ✓ 与用户描述吻合。
        #   根因：斗技场/角色/公会/图鉴这些是**大页面**，不是弹窗 ——
        #     「点中间最下面」那个万能位**根本关不掉它**（点了没反应），
        #     所以现有分支永远命中不了，只能无限重试到 90 秒 timeout ✗✗。
        #   ⇒ 补一条真退路：认出「离开了探索流程的大页面」⇒ 点底部「开始冒险」导航
        #     **回大厅**（再由 ensure_in_map 从大厅点回选图界面）✓
        if idle >= 2 and not in_map(b, b.img(), items):
            _back = _escape_to_lobby(b, log, items)
            if _back:
                idle = 0
                continue
        idle += 1
        if idle >= 4:
            # ⭐⭐ 2026-09-26 用户实测：**「点中间最下面」(541,1890) 能关掉几乎所有弹窗，
            #   而且关完还在图里** ⇒ 退图阶段第一步就试它 ✓（比"找 X / 找关闭符"稳）
            #   ⚠ 但**战斗界面必须点「关闭」**（用户明令：不能点开始冒险 ✗）
            #     ⇒ 交给 universal_close 认面板类型，别在这里硬点 ✓
            universal_close(b, log, items=items, where='finish_idle')
            n = close_x_panels(b, b.img())
            # ⭐⭐⭐ 2026-10-02 提速审计：**「左侧 X」位置是固定的**（`layout.REF['close_x_left']`
            #   = (329,150)）⇒ 先按**定死坐标**点一下（0ms），只有它回报"画面没变"时
            #   才付那次整屏 OCR 去找 X 的坐标（原来**无条件** `find_x(b.ocr(tag='fin_univ'))`
            #   = 每轮 ≈0.9s）✓ 判据一个字没改（`find_x` 仍原样保留为兜底）
            x = None
            if b.tap_dlg(int(LAYOUT.sx(329)), int(LAYOUT.sy(150)), wait=1.2) is False:
                x = find_x(b.ocr(tag='fin_univ'))
                if x:
                    b.tap(x['cx'], x['cy'], wait=1.5)
            else:
                n += 1
            if not n and not x:
                # 连关闭符都认不到 ⇒ 按实测的固定位置试（底部返回 + 左侧 X）
                # ⭐ v0.31 方案 B：这两个都是**面板上的**关闭点（弹窗系）⇒ tap_dlg ✓
                # ⚠ 2026-10-02 换 720p 基准时漏改：原来是 1080×1920 系的 (539,1212)/(493,225)。
                #   720p 设备系正确值见 `fixed.py` 的注释（→设备(359,808) / (329,150)）。
                b.tap_dlg(int(LAYOUT.sx(359)), int(LAYOUT.sy(808)), wait=1.5)
                b.tap_dlg(int(LAYOUT.sx(329)), int(LAYOUT.sy(150)), wait=1.2)
            log.append({'finish': 'unknown_panel_clear', 'idle': idle,
                        'closed': n, 'x': bool(x), 'universal': True})
            idle = 0
            continue
        # ⭐ 2026-09-28 提速（P3）：空转轮不再死等 1.2s —— 画面一变（面板关掉/界面
        #   切换）立刻进入下一轮识别；没变才等满 ✓
        if b.fast_ok:
            b.wait_change(1.2, band=(130, 1800), thr=4.0, min_sec=0.2)
        else:
            time.sleep(1.2)
    log.append({'finish': 'timeout'})
    return False


def final_collect(b, log, st):
    """⭐ 退出地图前的固定动作（用户 2026-09-25）：**只点一下**，点的是**最近点过的那格**

    用户口径原话：「退出前点一下之前点过的位置，**点一下就行**」「**不是各一下，是一共一下**」
    「**最后点的那一下是点最近点的那次的点位**」。
    只补点 + 关面板，不再打架、不再买、不再揭新格。

    ⭐⭐⭐ 2026-10-05 **入口/出口计时**（用户报「平均 66 秒/张，比以前慢很多」）：
      实测退图耗时 旧代码 **3 秒/张** ⇒ 新代码 **6~10 秒/张** ✗
      ⇒ 本函数的耗时记进 log（`final_collect_secs`），配合调用方的 `finish_secs`
        就能定位这 7 秒到底花在"补点/关面板"还是"退图其余部分" ✓
    """
    _t_fc = time.time()

    def _fc_done(_n=0):
        try:
            log.append({'final_collect_secs': round(time.time() - _t_fc, 1),
                        'ret': _n})
        except Exception:       # noqa: BLE001
            pass
        return _n

    clicks = list(st.get('clicked') or [])
    pos = clicks[-1] if clicks else st.get('last')
    if not pos:
        log.append({'collect': 'none'})
        return _fc_done(0)
    # ⭐⭐⭐⭐ 2026-10-05 **紫/橙探索格：补点没用，该走的是"探索/派遣"**
    #   （用户第二次报「**修了个寂寞啊，和之前一模一样，没打探索格**」的**真正根因**）
    #   真机证据链（`runs/acc1/` 第 3 张图，`runs/acc1/loop/loop_log.json` + gui 日志）：
    #     · 这一格 `(3,1)` = `S00003_221`（紫格 ✓）、`slots_free=1`（**有空闲槽** ✓）
    #     · 计划把它排在最后 ⇒ 它成了 `clicks[-1]` ⇒ **本函数补点又点它一次** ✗
    #     · 紫格弹出的是「探索产出」面板，而本函数只处理
    #       **莱姆 / 获得新装备 / 预言石板** 三种弹窗 ⇒ 紫格面板**关不掉**
    #     · gui 日志原文：`· 点 (72,908) → 弹面板`
    #                    `· 退图前补点点出了面板且关不掉 ⇒ 已强制脱困` ✓✓
    #     · 日志实证：那一局**探索/派遣事件 0 条**、带 `content_skipped=6` 退图 ✗
    #   ⇒ 这就是"和之前一模一样"的原因：**我前几轮一直在修 `popups()` 那条链，
    #     而真正吃掉这一格的是 `final_collect()` 这条完全独立的路径** ✗
    #   ⚠ 另一条同样致命的：**紫格是"目标"，本来就该在退图前被打掉/派出**，
    #     而不是被"补点"当成"随手再点一下"—— 补点第二次点它只会把面板再弹一次 ✓
    # ===== 2026-10-28 补点必须跳过「已经买完的商人/宝库」=====
    # 用户第 3~4 次反馈（原话）：「怎么旅行商人买完后还是会点开？我记得这个问题我反馈了三四次了」
    #
    # 真机铁证（runs/loop/loop_log.json，#505 -> #512~513）：
    #   #505 {"bought_rec":[360,1004],"cell":"4,4"}          <- 17:24 买完 (4,4)
    #   #512 {"collect":"fixed_close","at":[360,1004]}       <- **又点同一格**
    #   #513 {"collect":"tapped","at":[360,1004],"opened":true}  <- 面板被重新打开 ✗
    #
    # 根因：`pos = clicks[-1]` 取的是**最后一次点击的格**，
    #   而商人买完那一下正是最后一次点击 => 补点又点它一次。
    #   本函数**完全不看** bought_done / merchant_done（那是"已买"的账本）。
    #   ⚠ 与紫格那条是**同一个形状**：clicks[-1] 恰好是"不该补点"的格。
    #
    # 修法：补点前先查账本 —— 那格已买过 => 跳过（记一条日志，不静默）
    _fc_bought_rc = set()
    try:
        for _s in (st.get('bought_done') or set()):
            try:
                _fc_bought_rc.add(tuple(cell_of(int(_s[0]), int(_s[1]))))
            except Exception:       # noqa: BLE001
                continue
        _fc_bought_rc |= set(st.get('merchant_done') or set())
    except Exception:       # noqa: BLE001
        _fc_bought_rc = set()
    try:
        _fc_rc0 = cell_of(pos[0], pos[1])
    except Exception:       # noqa: BLE001
        _fc_rc0 = None
    if _fc_rc0 is not None and _fc_rc0 in _fc_bought_rc:
        log.append({'collect': 'bought_skip', 'at': list(pos),
                    'cell': '%d,%d' % _fc_rc0,
                    'note': '这格已经买过（账本里有）=> 不再补点（补点会重新打开面板 ✗）'})
        say('       - 退图前补点：(%d,%d) 已经买过 => 跳过 ✓' % _fc_rc0)
        return _fc_done(0)
    _fc_sid = ''
    try:
        _fc_rc = cell_of(pos[0], pos[1])
        _fc_sid = str((st.get('st') or {}).get(_fc_rc, {}).get('sid')
                      or (st.get('obs') or {}).get(_fc_rc, {}).get('sid') or '')
    except Exception:       # noqa: BLE001
        _fc_sid = ''
    _fc_purple = _is_purple_cell(_fc_sid, st.get('ev_tiles'), pos)
    _fc_free = int(st.get('slots_free') or 0)
    if _fc_purple and _fc_free > 0 and EXPLORE_DISPATCH:
        log.append({'collect': 'purple_skip', 'at': list(pos), 'sid': _fc_sid,
                    'slots_free': _fc_free,
                    'note': '紫/橙探索格是**目标**（不是"随手补点"的格）⇒ 补点会重复弹探索面板 ✗；'
                            '它该由探索分支处理 ✓'})
        say('       · 退图前补点：这格是**紫/橙探索格**（有空闲槽 %d）⇒ 跳过补点'
            '（它该走探索派遣，补点只会重复弹面板 ✗）' % _fc_free)
        return _fc_done(0)
    # ⚠ 2026-09-25 用户报「退出地图后乱点切换到别的图」：
    #   补点前**必须确认还在图里**！上一轮可能已经自己退图 / 被顶回选图界面，
    #   这时再按老坐标补一下 = 在选图界面上乱点（可能选到别的图）。
    b.snap('collect_pre')
    # ⭐⭐⭐ 2026-10-06 新增：**0-OCR 的模板快查先挡一道**。
    #   `fx_menu()`（`:4851`）用的是 `enter_map_btn` 模板 —— 它**只在选图界面**出现
    #   （标定见 `:4862`：真机选图帧 1.000 / 24 张负样本最高 0.423）⇒
    #   命中即"**绝不在图里**"，直接省掉下面那次 OCR（6.8ms vs 0.74s）✓
    #   ⚠⚠ **这不是 `in_map()` 那条被撤回的"模板短路"**（`:3527` 撤回的是拿
    #     **底部导航条**当"在图里"的**正面**判据 —— 导航条三界面都有 ⇒ 分不开 ✗）。
    #     这里是**反面**判据，方向相反、且模板本身只在选图界面存在 ⇒ 安全 ✓
    if fx_menu(b):
        log.append({'collect': 'skip_not_in_map', 'why': 'fx_menu'})
        say('       · 已经回到选图界面了（模板快查）→ 跳过退图前补点（避免乱点）')
        return _fc_done(0)
    # ⛔⛔⛔ 2026-10-06 **修 bug**：这里原来是 `band=(0, 320)`，把 `in_map()` 的
    #   **正反两面证据全裁掉了**，判定**完全由 `cells_of()` 格子兜底做出** ✗✗
    #     · 正面证据「结束冒险」实测 cy=**515**（真机 5 帧全是 515）⇒ 窄带里没有
    #     · 反面证据「快速扫荡/进入地图」实测 cy=**1079**、
    #       「深渊NN」cy=**655**、「星界秘境」cy=**496** ⇒ 窄带里也全没有
    #   ⇒ 而选图界面中间那张**地图预览图**会被地块分类器数出 8+ 格
    #     （`in_map()` docstring `:3519` 早就记着这个坑）⇒ 在**选图界面**上返回 True ✗
    #   ⇒ **实测铁证**（`_verify/`，只读探针 `_tmpman/probe_band_negev.py`）：
    #       `select_map_20261002.png`：全屏 in_map=**False** ✓ ／ (0,320) in_map=**True** ✗
    #       `now_20261003.png`      ：全屏 in_map=**False** ✓ ／ (0,320) in_map=**True** ✗
    #   ⇒ 讽刺的是：这个守卫**正是为「退出地图后乱点切换到别的图」加的**
    #     （见上面 `:6971` 的 2026-09-25 记录），却**在那张帧上完全失效** ✗
    #   ⚠ `it0` **只喂 `in_map()` 这一处**（本函数内 `it0` 无第二个消费者）
    #     ⇒ 收窄 band **没有任何别的好处**，纯粹是砍证据 ⇒ 改回全屏
    #     （代价 +0.23s/图：实测全屏 0.739s vs (0,320) 0.513s；换来"不在图里"判得准 ✓）
    it0 = b.ocr(min_conf=0.4, tag='pre')
    if not in_map(b, b.img(), it0):
        log.append({'collect': 'skip_not_in_map', 'why': 'in_map'})
        say('       · 已经不在图里了 → 跳过退图前补点（避免乱点）')
        return _fc_done(0)
    b.tap(pos[0], pos[1], wait=1.8)
    # ⛔⛔⛔ 2026-10-05 **撤回：不许无条件盲点 `lime_back`/`equip_back`**（我改坏过）
    #   用户报「**怎么开始点拉黑过的格子了？？**」—— 真机铁证（`runs/acc1/loop/loop_log.json`）：
    #     · `(3,4)` 被 `blocked_cells_tagged` **拉黑** ✓ 计划 `['4,3','3,5']` **没含它** ✓
    #     · 但 `{"collect":"fixed_ok","at":[456,908]}` ⇒ **点了棋盘上的格** ✗
    #   根因：我那条"快速路"**无条件盲点**两个固定锚点，而它们**都在棋盘里**：
    #       `lime_back`   = (359, 873) ⇒ 落在格 **(3,4)**   ← 正是那个被拉黑的格 ✗✗
    #       `equip_back`  = (360, 835) ⇒ 落在格 **(2,4)**
    #       `back_btn`    = (359, 808) ⇒ 落在格 (2,4)
    #   我当时的假设是"没弹面板时它们落在棋盘外的暗区" —— **这个假设是错的** ✗
    #   （873/835 都在棋盘 y 范围内；只有 `universal_close`(1260)/`bottom_close`(960)
    #     才偏到棋盘下部/外侧）
    #   ⚠ 教训：**盲点固定坐标必须先证明"不弹面板时它会落在哪"**，不能靠想当然
    #     —— 这与本仓《错误教训》B2「别把假设当证据」是同一类 ✓
    #   ⇒ 现在：**只有"确实弹出了面板"才动手**（`opened` 为真才走后面的固定坐标关面板），
    #     而"有没有弹"这件事**必须靠判据**（`dim` 压暗 / 面板判据），不能无条件点 ✗
    _panel_probably = False
    try:
        _dim_now = float((getattr(b, 'last_change', None) or {}).get('dim', 1.0))
        _panel_probably = _dim_now < 0.85
    except Exception:       # noqa: BLE001
        _panel_probably = False
    if _panel_probably:
        # ⭐ 只有"棋盘被压暗"（= 真弹了面板盖住棋盘）才用固定坐标关面板 ✓
        try:
            import fixed as _fx1
            _p_lime, _p_equip = _fx1.A('lime_back'), _fx1.A('equip_back')
            if _p_lime:
                b.tap(_p_lime[0], _p_lime[1], wait=1.1)
            if _p_equip:
                b.tap(_p_equip[0], _p_equip[1], wait=1.1)
            _fixed_fast = True
            log.append({'collect': 'fixed_close', 'at': pos, 'dim': round(_dim_now, 3),
                        'note': '棋盘被压暗 ⇒ 确认弹了面板 ⇒ 才用固定坐标关 ✓'})
            say('       · 退图前补点：棋盘被压暗(dim=%.2f) ⇒ 用固定坐标关面板 ✓' % _dim_now)
        except Exception as _efx:       # noqa: BLE001
            log.append({'collect': 'fixed_err', 'e': repr(_efx)[:120]})
            _fixed_fast = False
        if _fixed_fast:
            log.append({'collect': 'tapped', 'at': pos, 'opened': True, 'still': False,
                        'via': 'fixed_after_dim'})
            return _fc_done(1)
    log.append({'collect': 'no_panel', 'dim': round(_dim_now, 3) if '_dim_now' in dir() else None,
                'note': '补点后**棋盘没被压暗** ⇒ 没弹面板 ⇒ 不点任何固定坐标 ✓'})
    b.snap('collect')
    it = b.ocr()
    # ⭐ 补点后可能弹「发现莱姆！」（用户 2026-09-25）→ 要**点返回**
    #   ⚠ 2026-10-02：这里**保留**较宽的判据是安全的 ——
    #     本函数就是「退出地图前**最后一次**点击」之后的收尾（用户口径），
    #     此刻**确定刚点过格子**，弹的只可能是奖励类面板 ⇒ 不会误伤 ✓
    #     ⛔ 而 `finish_map()` 循环 / `popups()` 那些地方**不能**这么判
    #       （用户当场指出：「怎么刚进图就找莱姆了」）—— 已在那里改回窄判据 ✓
    #   ⛔⛔ 2026-10-12：**这里也改窄**（`_lime_popup_title`）——
    #     本函数确实在"最后一次点击之后"，但**面板可能是预言石板**（同一 bug 现场 ✓）
    #     而预言卡正文含「莱姆」⇒ 子串判据照样会误点写死坐标 ✗
    #     ⚠ `is_reward_panel` 仍是第二判据（它内部也已改窄 ✓）⇒ 能力没丢 ✓
    if _lime_popup_title(it) is not None or is_reward_panel(b=b, items=it):
        lb = lime_back(it)
        if lb:
            b.tap(lb['cx'], lb['cy'], wait=1.6)
            log.append({'collect': 'lime_back', 'at': (lb['cx'], lb['cy']),
                        'fixed': True})
            say('       · 发现莱姆！→ 点返回')
        return _fc_done(1)
    # ⭐ 也可能弹「获得新装备！」（用户 2026-09-26 报：最后点击最近一次点过的位置那出现）
    if close_newequip(b, it, log, 'collect', at=pos):
        say('       · 退图前补点弹出「获得新装备！」→ 点返回')
        return _fc_done(1)
    # ⭐ 或者「预言石板」→ 点中间最下面关掉 + 拉黑这格 ✓
    #   ⛔ 2026-10-10：**预言石碑除外**（它该走 `foretell_flow` 领预言 ✓）
    #     —— 这是那 3 处里的第 3 处（`popups()` / 点击循环 / 这里 ×2）✗ 我第一版漏了 ✓
    if fb(it, *L['prophecy']) and not _is_foretell_panel(it):
        universal_close(b, log, items=it, probe=L['prophecy'][0], where='collect', at=pos)
        block_cell(log, st, pos, 'prophecy')
        say('       · 退图前补点弹出「预言石板」→ 关掉并拉黑这格')
        return _fc_done(1)
    # ⭐ 「预言石碑」⇒ **领掉它**（用户口径：预言是白拿的，别关掉 ✗）
    if _is_foretell_panel(it):
        say('       · 退图前补点弹出「预言石碑」⇒ **领掉**（不关掉 ✓）')
        try:
            buypanels.foretell_flow(
            # ⛔ 2026-10-19 **必须传 flags**（原来这两处没传 ⇒ `flags=None` ⇒
            #   判停用默认 True、优先逻辑用默认 False ⇒ 两边矛盾 ✗）
            b, log, flags={'stop_peace_metal': STOP_PEACE,
                           'stop_elem_purple': STOP_ELEM_PURPLE,
                           'stop_elem_orange': STOP_ELEM_ORANGE})
        except Exception as _fe5:      # noqa: BLE001
            log.append({'foretell': 'collect_flow_error', 'e': repr(_fe5)[:100]})
        return _fc_done(1)
    # ⭐ 也可能弹「偶遇强敌」（2026-09-25 用户报卡住）→ 不打，点 X 关掉
    if fb(it, *L['strong']):
        x = find_x(it)
        if x:
            b.tap(x['cx'], x['cy'], wait=1.5)
        else:
            close_x_panels(b, b.img())
        log.append({'collect': 'strong_closed',
                    'closed_at': (x['cx'], x['cy']) if x else None})
        say('       · 退图前补点弹出「偶遇强敌」→ 不打，关掉')
        return _fc_done(1)
    opened = panel_seen(it, b=b) or bool(bottom_close(it))
    if opened:
        close_x_panels(b, b.img())
        cl = bottom_close(it)
        if cl:
            b.tap(cl['cx'], cl['cy'], wait=1.6)
        # ⭐ 2026-10-02 提速审计：下面这次与再下面那次 `find_x(b.ocr())` 原本**各读一帧**，
        #   而两次之间**只有找到按钮时才点一下** ⇒ 多数情况读的是**同一帧** ⇒ 合并成一次
        #   ⚠ 这两次调用原来还**没打 tag** ⇒ 运行时的 OCR 分账里根本看不见它们 ✗（现在有了）
        _it_p = b.ocr(tag='collect_panel')
        ok = exb(_it_p, L['ok'])
        if ok and ok['cy'] > LAYOUT.sy(900):
            b.tap(ok['cx'], ok['cy'], wait=1.5)
            _it_p = b.ocr(tag='collect_panel2')     # 点过 ⇒ 画面变了，必须重读
        x = find_x(_it_p)
        if x:
            b.tap(x['cx'], x['cy'], wait=1.2)
    # ⭐ 2026-09-26（rendslot 实测）：补点点出的面板**关不掉**时，后面 finish_map 会因为
    #   「结束冒险」被面板遮住而 OCR 不到 ⇒ 空转到 90 秒 timeout ⇒ "退图没成功，已停止"
    #   ⇒ 这里关完**验证**一次；还在就强制脱困
    # ⭐⭐⭐⭐ 2026-10-05 **提速：补点的"关弹窗"改成固定坐标优先**
    #   （用户原话：「**怎么还ocr？这种不应该都是固定坐标点击吗**」）
    #   原来这一段最多 **6 次整屏 OCR**（`pre`/`collect`/`collect_panel`/`collect2`/
    #   `collect3`×最多 4），每次 0.65~0.9 秒 ⇒ 真机 `taps` 实测这一下 **3.7~9.1 秒** ✓
    #   而这些弹窗按钮**位置是固定的**，`fixed.py` 里早有锚点：
    #       莱姆「返回」   `FX.A('lime_back')`       = (359, 873)
    #       新装备「返回」 `FX.A('equip_back')`      = (360, 835)
    #       通用「关闭」   `FX.A('universal_close')` = (361,1260)
    #       底部确认       `FX.A('bottom_close')`    = (385, 960)
    #   ⇒ **先盲点两个"点错也无害"的返回位**（都在面板中下部；没弹面板时它们落在
    #     棋盘外的暗区/说明条上，不会选中格子 ✓）
    #   ⚠ 然后**只确认一次**：仍认到面板才点 `universal_close`
    #     （`universal_close` 盲点会把普通界面点成"跳到图鉴" —— 本函数注释里记着的事故 ✗
    #      所以它必须**在确认之后**才点 ✓）
    #   ⚠ 确认仍不干净 ⇒ **落回下面原来的逐状态路径**（保留全部兜底，不删逻辑 ✓）
    it2 = b.ocr(tag='collect2')
    still = panel_seen(it2, b=b) or bool(bottom_close(it2))
    log.append({'collect': 'tapped', 'at': pos, 'opened': bool(opened),
                'still': bool(still)})
    # ⭐⭐⭐ 2026-10-02 修「退图前最后一次点击后卡在『获得莱姆』界面」
    #   现象（用户原话）：「模拟器现在卡在获得莱姆的界面」
    #   ⇒ 那正是**退图前最后一次补点**（`final_collect` 点 `clicks[-1]`）之后弹的。
    #
    #   为什么上面那段接不住（逐条核实，不是猜）：
    #     ① 补点后只 `wait=1.8` 就 OCR 一次 ⇒ **游戏弹窗动画慢一点就抓不到**；
    #     ② 抓到也没有第二次确认 —— `lime_back()/close_newequip()` 各只试一次，
    #        点「返回」若没生效（按钮还在 / 换了个弹窗）就当处理完了；
    #     ③ 于是弹窗留在屏幕上 ⇒ 盖住棋盘 ⇒ `finish_map` 认不到「结束冒险」
    #        ⇒ 走 `universal_close()` 盲点 ⇒ **跳到「图鉴」这类大页面**（用户实测）。
    #
    #   ⇒ 这里补一个**短轮询兜底**：反复 OCR，最多 ~6 秒，
    #     见到莱姆/新装备/强敌/石板就**当场关掉并验证**，
    #     关不掉才交给后面的 `force_unstick` ✓
    # ⭐⭐⭐ 2026-10-03 提速（用户「看看还有地方能省下来么」+「都做一下」）：
    #   `collect2`（上一句，0.85s）与下面轮询的**第 0 次**之间**没有任何点击/动作**
    #   ⇒ 同一帧 ⇒ 两次全屏 OCR 完全重复 ✗
    #   ⇒ 若 `collect2` 那帧**明确没有**任何要关的东西（没认到面板、也没见
    #     莱姆/新装备/强敌/石板的字样）⇒ **跳过轮询的第 0 次**（省 ~0.85s/图 ✓）
    #   ⚠ 保守做法：只跳过"已经明确干净"的第 0 次；一旦有疑点就照常整轮轮询 ✓
    _clean2 = (not panel_seen(it2, b=b)) and (not bottom_close(it2)) and not any(
        k in ' '.join((i.get('text') or '') for i in (it2 or []))
        for k in ('莱姆', '新装备', '强敌', '石板', '获得'))
    if _clean2:
        st['collect3_skip'] = st.get('collect3_skip', 0) + 1
    for _i in range(4):
        if _i == 0 and _clean2:
            continue                        # ← 同帧重复 ⇒ 省这一次 ✓
        _it3 = b.ocr(min_conf=0.35, tag='collect3')
        if not _it3:
            break
        _hit3 = False
        # ⚠ 2026-10-02：这里在 `final_collect` 收尾里（退图前**最后一次**点击之后），
        #   上下文确定 ⇒ 可以用较宽判据；但**仍不用裸 `panel_seen`**
        #   （它在地图界面也常为真，用户已指出那会导致「刚进图就找莱姆」）✓
        #   ⛔⛔ 2026-10-12：**同上一处，改走 `_lime_popup_title`** ✓
        if _lime_popup_title(_it3) is not None or is_reward_panel(b=b, items=_it3):
            _lb3 = lime_back(_it3)
            if _lb3:
                b.tap(_lb3['cx'], _lb3['cy'], wait=1.5)
                log.append({'collect3': 'lime_back',
                            'at': (_lb3['cx'], _lb3['cy']), 'fixed': True})
                say('       · 退图前补点弹出「发现莱姆」→ 点返回')
                _hit3 = True
        if not _hit3 and close_newequip(b, _it3, log, 'collect3', at=pos):
            say('       · 退图前补点弹出「获得新装备！」→ 点返回')
            _hit3 = True
        elif fb(_it3, *L['strong']):
            _x3 = find_x(_it3)
            if _x3:
                b.tap(_x3['cx'], _x3['cy'], wait=1.3)
            else:
                close_x_panels(b, b.img())
            log.append({'collect3': 'strong_closed'})
            say('       · 退图前补点弹出「偶遇强敌」→ 不打，关掉')
            _hit3 = True
        elif fb(_it3, *L['prophecy']) and not _is_foretell_panel(_it3):
            #   ⛔ 2026-10-10：**预言石碑除外**（该领掉、不该关掉 ✗）—— 第 4 处 ✓
            universal_close(b, log, items=_it3, probe=L['prophecy'][0],
                            where='collect3', at=pos)
            block_cell(log, st, pos, 'prophecy')
            say('       · 退图前补点弹出「预言石板」→ 关掉并拉黑这格')
            _hit3 = True
        elif _is_foretell_panel(_it3):
            say('       · 退图前补点弹出「预言石碑」⇒ **领掉**（不关掉 ✓）')
            try:
                buypanels.foretell_flow(
            # ⛔ 2026-10-19 **必须传 flags**（原来这两处没传 ⇒ `flags=None` ⇒
            #   判停用默认 True、优先逻辑用默认 False ⇒ 两边矛盾 ✗）
            b, log, flags={'stop_peace_metal': STOP_PEACE,
                           'stop_elem_purple': STOP_ELEM_PURPLE,
                           'stop_elem_orange': STOP_ELEM_ORANGE})
            except Exception as _fe6:      # noqa: BLE001
                log.append({'foretell': 'collect3_flow_error', 'e': repr(_fe6)[:100]})
            _hit3 = True
        # ⭐⭐⭐⭐⭐ 2026-10-14 **补点时弹出另外 4 种特殊面板 ⇒ 只关掉，不走完整流程**
        #   （用户口径：选「**只"关掉"面板，不领奖**」✓）
        #   ---- 病（用户报「**这张图为什么显示退图失败然后停止了**」）----
        #     真机铁证（`runs/acc3/loop/loop_log_prev.json` 第 6 张图）：
        #       `#263` 快照 `1,6 = ['014','限时礼包']`
        #       `#286 collect tapped at=[552,716] opened=true **still=true**`（`(552,716)`=格 `1,6`）
        #       `#287 unstick collect_panel tried=[[493,225],[683,150]]`
        #       `#290~#319` **反复 22 次**点 `(360,1219)` ⇒ `unknown_panel_clear`
        #       `#320 finish timeout` ｜ `#321 finished=false finish_secs=**110.6**` ✗✗
        #     ⇒ **整局停下**（用户看到的就是"退图失败然后停止"）✓
        #   ---- 根因（覆盖面缺口）----
        #     `popups()` 认 6 种特殊面板，而**这里（退图前补点）只认 2 种**：
        #       · 认：预言石板（关掉+拉黑）、预言石碑（领掉）
        #       · **不认：限时礼包 / 传承祭坛 / 勇者之墓 / 宝箱怪** ✗
        #     ⇒ 补点时弹出这 4 种 ⇒ 本函数判 `still=True`（关不掉）
        #       ⇒ `force_unstick` 的 3 个点也关不掉（它们不是这些面板的关闭点）
        #       ⇒ 退图阶段只好反复点万能位 —— 而那个值 `(360,1219)` **等于**
        #         `fixed.A('start_adv_icon')`（底部导航「开始冒险」）⇒ 当然关不掉 ✗
        #       ⇒ 空转 110 秒（90 秒 + 快超时延后 20 秒）⇒ `finish: timeout` ✗
        #   ---- 修法（**只关不领**，与 `final_collect` 的既有契约一致 ✓）----
        #     本函数的契约（见它 docstring）：**只补点 + 关面板，不再打架、不再买、
        #       不再揭新格** ⇒ 所以这里**不调 `gift_flow`/`shrine_flow`/…**
        #       （那些会领奖/购买，违背"退图收尾"的原意 ✗）
        #     ⇒ 改用 `buypanels.ensure_closed()` 把面板**收起来**（它本来就是
        #       "确保面板不挡路"的通用收尾 ✓），失败再交给后面的 `force_unstick` ✓
        #     ⚠ 判据用**面板标题**（`_panel_title_of`，独立成条 + 剥前缀 ✓）
        #       —— 与 `popups()` 的标题优先同源，不做子串匹配 ✗
        elif _panel_title_of(_it3) in _FC_CLOSE_TITLES:
            _t3 = _panel_title_of(_it3)
            say('       · 退图前补点弹出「%s」→ **只关掉，不领奖**（退图收尾口径 ✓）'
                % _t3)
            try:
                buypanels.ensure_closed(b, log)
            except Exception as _ce3:      # noqa: BLE001
                log.append({'collect3': 'ensure_closed_err', 'e': repr(_ce3)[:90]})
            log.append({'collect3': 'close_only', 'title': _t3, 'at': pos,
                        'note': '补点是退图收尾 ⇒ 只关面板、不领奖（用户 2026-10-14 口径 ✓）'})
            _hit3 = True
        if not _hit3:
            # ⭐ 兜底：**认不到标题、但确实有个「返回」按钮** ⇒ 也试着关一次。
            #   为什么需要：莱姆/新装备的判据都建立在「OCR 读到标题文字」上
            #   （`L['lime']` / `L['newequip']`），而弹窗标题**偶尔读不出来**
            #   （模糊/动画残影/字体小）⇒ 整条判据失效 ⇒ 弹窗留在屏幕上
            #   ⇒ 盖住棋盘 ⇒ `finish_map` 走万能位盲点 ⇒ **跳到「图鉴」大页面**（用户实测）。
            #   ⇒ 只要认到「返回」且它在下半屏（= 弹窗形态，不是主界面按钮），就关。
            #   ⚠ 只在**这轮确实弹了面板**（`opened`）时才做，避免误点地图上别的东西 ✓
            if opened:
                _cl3 = bottom_close(_it3)
                if _cl3 and _cl3['cy'] > LAYOUT.sy(880):
                    b.tap(_cl3['cx'], _cl3['cy'], wait=1.4)
                    log.append({'collect3': 'bottom_close_fallback',
                                'at': (_cl3['cx'], _cl3['cy']),
                                'note': '认不到标题但有返回按钮 ⇒ 兜底关一次'})
                    say('       · 认不出弹窗标题但有「返回」⇒ 兜底关一次 ✓')
                    _hit3 = True
        if not _hit3:
            break
        time.sleep(0.4)          # 可能有下一个弹窗（连着弹）⇒ 再看一轮
    if still:
        force_unstick(b, log, 'collect_panel',
                      ctx={'tapped': pos, 'flags': st if isinstance(st, dict) else {}})
        say('       · 退图前补点点出了面板且关不掉 ⇒ 已强制脱困')
    return _fc_done(1)


def run_one_map(b, log, max_round=45, prefix='', deadline=900):
    t0 = time.time()
    st = {'cold': {}, 'done': set(), 'last': None, 'err': 0, 'stuck': 0,
          'marks': {}, 'clear': False, 'clear_fights': 0, 'stall': 0, 'sig': None,
          'blank': 0, 'clicked': [], 'battles': []}
    # ⭐⭐ 2026-09-30：**「点了探索没反应」的连击计数每张图清零**（它属于"本图验证"）
    #   —— 全局留着的话，第一张图踩到"槽满"之后，**后面每张图只敢点 1 次就判满** ✗；
    #      而"槽真的空出来、只是「空闲」两个字认不出来"的机器就会**永远派不出探索小队** ✗✗
    #   每图给足 2 次机会 = 最坏每图多花 ~6 秒，换"槽一空就能重新派队" ✓
    #   （本图内一旦判满，`st['slots_free']=0` 会把后面的紫/橙格全部送去开打，不会反复点 ✓）
    if EXPLORE_DISPATCH:
        _PANEL_STUCK['expl'] = 0
    for rnd in range(max_round):
        # ⭐ 立即停止（2026-09-29 用户口径）：**每轮开头先查**，不等这张图打完
        if stop_checked(log, '轮首 r%d' % rnd):
            return 'stopped'
        if time.time() - t0 > deadline:
            log.append({'finish': 'deadline'})
            final_collect(b, log, st)
            return 'deadline'
        try:
            why = one_round(b, log, rnd, prefix, st)
            # ⭐⭐ 2026-09-29 诊断（真机「点了格子不点战斗」空转 15 秒排查）：
            #   每轮返回值落 log —— 之前 r1~r6 在 logcat 里**完全隐形**（轮首 say 都没有），
            #   无法判断卡在哪个状态。有这条后：每轮一条 `round_end`，配合轮首 say
            #   就能定位"每 2.2 秒一次 OCR 却零点击"到底发生在哪一段。
            log.append({'round_end': rnd, 'why': why,
                        'secs': round(time.time() - t0, 1)})
        except Exception as e:
            import traceback
            st['err'] += 1
            log.append({'round': rnd, 'error': repr(e),
                        'trace': traceback.format_exc().splitlines()[-3:]})
            flush(log)
            if st['err'] >= 3:
                log.append({'finish': 'too_many_errors'})
                final_collect(b, log, st)
                return 'errors'
            time.sleep(2)
            continue
        flush(log)
        if why:
            # ⚠ 「发现红装立即停止」时**什么都别做**（别补点、别退图），把现场留给人
            # ⚠ 「用户点了停止」同理：**绝不能补点**（`final_collect` 会再点一遍打过的格
            #   ⇒ 明明点了停还要多等十几秒，正是用户抱怨的"等打完这张图"✗）
            # ⛔ 2026-10-11 去掉 `'collect_stop'`/`'shrine_stop'`（[临时]采集停止已删 ✓）
            if why not in ('kicked', 'red_equip', 'foretell_stop', 'stopped'):
                final_collect(b, log, st)      # ⭐ 退出前固定补点（只点打过的格）
            return why
    final_collect(b, log, st)
    return 'maxed'


def line_cells(a, b):
    """两格之间按**直线**取格（Bresenham），含两端

    用户 2026-09-25 口径：「拦路 = 出生点到对应标记**那条直线上的格子**，两点之间直线最短」
    ⇒ 不要用「走廊」判据（`|d1+d2-d|<=2`，会把偏出去的格子也算成拦路）。
    """
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


def optimal_order(c, mk, st, log=None):
    """⭐ 用「体力最省」的最优解算本回合点序（mapsolve.Dijkstra，毫秒级）

    用户 2026-09-25：「要按消耗体力最少的方案走」。
    体力公式（源码 82956-82992）：普通格 = SpotSize；战斗格 = SpotSize*2。
    建盘：把视觉状态（每格 sid/是否已揭示/标记）交给 mapsim.from_observation（相邻同 sid 归一块），
    再交给 mapsolve.solve 求最省体力的动作序列 → 返回要点的像素坐标列表。
    失败(异常/无解)返回 None，调用方退回原来的启发式点序 ✓
    """
    try:
        import mapsim as sim_mod
        import mapsolve as solve_mod
        # ⭐⭐⭐ 2026-09-30：这里原来自己拼一份 cells（与 `_cells_for_model` 各写一遍）
        #   ⇒ ① 漏掉「按 anchor 整块剔已消耗格」和 `target` 白名单 ② 两处口径漂移
        #     （本仓库历史上 `_fix_blank_cost_1` 只改 mapsolve 漏 mapsim 就是这么踩的）
        #   ⇒ 统一改走 `_cells_for_model`（solver_order / eff_order 用的同一份 ✓）
        cells = _cells_for_model(st, c, log=log, tag='opt')
        if len(cells) < 8:
            if log is not None:
                log.append({'opt_skip': 'too_few_cells', 'n': len(cells)})
            return None
        sim = sim_mod.MapSim.from_observation(cells, spots_mod.spot_rows())
        prob = solve_mod.Problem(sim)
        if not prob.targets:
            if log is not None:
                log.append({'opt_skip': 'no_targets', 'blocks': len(sim.blocks),
                            'cells': len(cells), 'marks': len(mk or {})})
            return None
        # ⭐⭐⭐ 2026-10-01 v1.12 真机**空转卡死**修复（用户：「连地图都进不去了，显示正在把游戏
        #   拉回来」→ 实际是 **200% CPU 空转、日志停在进图后那次 OCR**）：
        #   本行原来只有 `max_states=40000`、**没有时间上限** ✗ —— 另一处（`solver_order`）
        #   早就加了 `max_secs=8`（2026-09-28「进图要等很久」），这一处漏了。
        #   一旦棋盘被切得很碎（例如雾格剪影判成"非空地"⇒ 连锁片变多、A* 状态空间爆炸），
        #   40000 个状态的展开就是**几分钟的满载空转**，而且**全程不打日志** ⇒
        #   用户看到的就是"卡在某一步不动"。⇒ 加 8 秒上限 + 前后落日志（下次一眼能看见）✓
        _t_opt = time.time()
        cost, acts = solve_mod.solve(prob, max_states=40000, max_secs=8)
        if log is not None:
            log.append({'opt_solved': {'secs': round(time.time() - _t_opt, 2),
                                       'cost': cost, 'steps': (len(acts) if acts else 0),
                                       'blocks': len(sim.blocks), 'targets': len(prob.targets)}})
        if not acts:
            if log is not None:
                log.append({'opt_skip': 'no_solution', 'targets': len(prob.targets),
                            'cost': cost})
            return None
        # ⭐ 2026-09-30：点击点必须取「当下已揭示的格」——理由见 `solver_order` 同处注释
        out = [marks_mod.cell_center(*_rc)
               for _rc, _bi, _w in prob.cells_for_plan(acts)]
        if out:
            say('       · 体力最优解：%d 步、预计 %s 点体力' % (len(acts), cost))
        return out or None
    except Exception as e:      # noqa: BLE001
        import traceback
        if log is not None:
            log.append({'opt_err': repr(e),
                        'trace': traceback.format_exc().splitlines()[-2:]})
        return None


BACK_BTN = (359, 808)        # 中间「返回」（交接文档实测坐标 ✓）
CLOSE_TR_PT = (656, 127)      # 背包右上角「关闭」
START_ADV = (360, 1219)       # 底部中间「开始冒险」**图标**（回地图界面）
# ⚠ 2026-09-28 修：原来是 (541,1889) —— 那是 OCR 到的**文字**位置，实测**点空** ✗
#   底部导航栏 = 图标在上(y≈1828)、文字在下(y≈1890)；文字那格点了不导航 ✓
CLOSE_TR, CLOSE_TR_Y = 656, 127    # 面板右上角关闭按钮（背包/招募/图鉴通用 ✓）

MAP_SCREEN_HINTS = ('开始冒险', '进入地图', '快速扫荡', '结束冒险', '探索度')


def is_map_screen(items):
    """判断是不是「地图/选图界面」（用户要求：用完补给必须回到这里）

    ⚠ 2026-09-27：`MAP_SCREEN_HINTS` 里的「开始冒险」**大厅也有**（全局底部导航），
      所以必须先用 `in_lobby()` 把大厅排除掉，否则大厅会被当成"已回到地图界面" ✗
    """
    if in_lobby(items):
        return False
    txt = [i.get('text') or '' for i in (items or [])]
    return any(any(h in t for h in MAP_SCREEN_HINTS) for t in txt)


def go_lobby_to_menu(b, log, items=None, wait=3.0):
    """大厅 → 点底部中间「开始冒险」→ 离开大厅

    ⭐ 用户 2026-09-27 明示：「点中间的开始冒险就能回到选图界面」
       （背景：实例B采图第 13 张时**游戏自己重启**，重启后停在大厅，
         每轮 `{'pre':'not_in_map','act':'none'}` 直到 40 秒超时 ✗）

    ⚠ 实测补充（2026-09-27 22:04 实例B真机）：从大厅点「开始冒险」的落点**有两种**——
        · 若存在**未完成的图** ⇒ **直接恢复到那张图**（实测落进「夏日海滩[100]」棋盘，
          体力 1406/2100 不变 ⇒ 确认不是新进图、没扣 25 体力 ✓）
        · 否则 ⇒ 回选图界面
       两种落点对调用方都可用：`ensure_in_map` 前者 `in_map()==True` 直接开工，
       后者交给 `enter_map()` 点「进入地图」✓
       所以函数名保留 menu，但语义是 **"离开大厅"**，不保证一定到选图界面。

    ⚠ 安全边界不变：**必须先 OCR 真认到「开始冒险」文本**（且 cy 在底部带内）才点；
      认不到就什么都不做 —— 绝不盲点万能位 (541,1890) ✗
      （地图/选图界面的底部也有「开始冒险」，所以这里**同时要求 `in_lobby()`**，
        避免在推图循环里误触它 ✗）
    """
    if items is None:
        items = b.ocr(tag='lobby')
    if not in_lobby(items):
        return False

    # ⭐⭐⭐ 2026-10-01 PC 提速：**位置写死了，不用再从 OCR 文字反推 y**
    #   旧做法（已废）：OCR 找到「开始冒险」文字 → 用 `y0-41 / cy-62 / …` 猜 4 个偏移 →
    #     逐个试（每次 1 次 OCR 验证 ≈ 3s，实测一轮白点 30 秒）。
    #   为什么能废：PC 端**锁定 720×1280**，底部导航栏是**固定竖屏布局**，
    #     「开始冒险」图标中心恒在设备坐标 (360, 1219) = 参考 (540, 1828)
    #     ⇒ 一次点击即可，**不需要 OCR 文字、也不需要猜偏移** ✓（530× 快）
    #   ⚠ 保留旧偏移链作为**兜底**（万一固定坐标失效，至少还能像以前那样试）。
    fx_adv = fx_anchor('start_adv_icon')
    if fx_adv:
        cands_y = [fx_adv[1]]
        adv_cx = fx_adv[0]
    else:
        adv = None
        for it in items:
            if '开始冒险' in (it.get('text') or '') and it['cy'] > LAYOUT.sy(1067):
                adv = it
                break
        if not adv:
            log.append({'lobby': 'no_start_adv_text'})
            say('   · 判定在大厅，但没认到「开始冒险」文本 ⇒ 不盲点，停在原地')
            return False
        # 旧兜底：按「文字顶边 −41px」点图标，然后依次试别的偏移
        cands_y = [adv['y0'] - 41, adv['cy'] - 62, adv['y0'] - 25, adv['cy']]
        adv_cx = adv['cx']
        log.append({'lobby': 'fx_fallback_to_ocr_offset'})

    for k, ty in enumerate(cands_y):
        ty = int(ty)
        b.tap(adv_cx, ty, wait=wait)
        log.append({'lobby': 'tap_start_adv', 'at': (adv_cx, ty), 'try': k,
                    'fixed': bool(fx_adv)})
        say('   ★ 大厅 → 点「开始冒险」图标 (%d,%d) 离开大厅（未完成的图会直接恢复 ✓）'
            % (adv_cx, ty))
        status('人在大厅 · 正在回地图')
        # ⭐ 2026-09-28：判定改成**最多看 3 次**（每次间隔 1.2 秒）
        #   因为「大厅→（恢复进图）/（选图界面）」有**场景过渡**，点完 3 秒时 OCR 常还停在大厅 ✗
        #   老逻辑一次判死 ⇒ 白点剩余 3 次偏移（实测每轮多花 ~30 秒，占单轮 20%）
        ok_leave = False
        for _k in range(3):
            _it2 = b.ocr(tag='lobby2')
            if not in_lobby(_it2):
                ok_leave = True
                break
            try:
                if in_map(b, b.img(), _it2):          # 直接恢复进图 ⇒ 也算离开大厅 ✓
                    log.append({'lobby': 'tap_start_adv_to_map'})
                    say('   ★ 点「开始冒险」后**直接恢复进图**（存在未完成的图）⇒ 已离开大厅 ✓')
                    ok_leave = True
                    break
            except Exception:           # noqa: BLE001
                pass
            time.sleep(1.2)
        if ok_leave:
            return True
        say('     · 这一下没离开大厅，换下一个偏移再试')
    log.append({'lobby': 'tap_start_adv_failed', 'tried': cands_y})
    say('   ✗ 四个偏移都点过还是在大厅 ⇒ 交回调用方（不盲点万能位 ✗）')
    return False


try:
    from mapbot import ADB
    CNW = CREATE_NO_WINDOW
except Exception:       # noqa: BLE001
    # ⭐ 2026-10-02：原来兜底写死 `<Android SDK>`（本机 SDK 路径），
    #   朋友机器上 `import mapbot` 万一失败，这里就会去调一个**不存在的 exe** ⇒
    #   报 "FileNotFoundError: adb"，比真因更难查。
    #   现在兜底也走 `paths.py` 探测；探测不到就退回裸 'adb'（依赖 PATH）。
    try:
        import paths as _P
        ADB = _P.ADB
    except Exception:       # noqa: BLE001
        ADB = 'adb'
    CNW = 0x08000000 if os.name == 'nt' else 0


def back_to_map(b, log, tries=5):
    """一路退回到地图界面（每步都**验证**，退到为止）"""
    for k in range(tries):
        b.snap('backmap')
        items = b.ocr(min_conf=0.2, tag='backmap')
        if is_map_screen(items):
            log.append({'back_to_map': 'ok', 'tries': k})
            return True
        # ⭐ 2026-09-27：大厅 ⇒ 点底部中间「开始冒险」
        #   ⚠ 绝不能落到下面的 ③ —— 大厅的 (984,191) 是**右上角齿轮（设置）**，
        #     点它会弹设置面板，越退越远 ✗
        if in_lobby(items):
            if go_lobby_to_menu(b, log, items=items, wait=2.5):
                continue
            log.append({'back_to_map': 'lobby_no_btn', 'try': k + 1})
            return False
        # ① 返回 / 关闭 / 取消
        back = find_button(items, '返回', '关闭', '取消', maxlen=4) or \
            find_in(items, '返回', '关闭')
        if back:
            b.tap(back['cx'], back['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_back', 'try': k + 1,
                        'text': back['text']})
            continue
        # ② 提示弹窗的 确定 / 确认（用完道具后常见；此时只是关提示，不会买东西 ✓）
        ok = find_button(items, '确定', '确认', maxlen=3)
        if ok and ok['cy'] > LAYOUT.sy(600):
            b.tap(ok['cx'], ok['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_ok', 'try': k + 1,
                        'at': (ok['cx'], ok['cy'])})
            continue
        # ③ ⭐ 右上角关闭按钮（用户提醒：背包右上角就有关闭 ✓；实测 (984,191)）
        b.tap(CLOSE_TR, CLOSE_TR_Y, wait=1.3)
        log.append({'back_to_map': 'tap_close_tr', 'try': k + 1,
                    'at': (CLOSE_TR, CLOSE_TR_Y)})
        continue
        # ④ X 按钮（万一是别的图标的 X）
        x = find_x(items)
        if x:
            b.tap(x['cx'], x['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_x', 'try': k + 1})
            continue
        # ④ 安卓返回键（面板类界面最通用的退法 ✓）
        try:
            import subprocess
            # ⚠ 设备号取 Bot 自己的（原来误用了模块里不存在的 SERIAL ✗）
            dev = getattr(b, 'dev', None) or getattr(b, 'serial', None) or ''
            cmd = [ADB, '-s', dev] if dev else [ADB]
            subprocess.run(cmd + ['shell', 'input', 'keyevent', '4'],
                           capture_output=True, timeout=10, creationflags=CNW)
            time.sleep(1.0)
            log.append({'back_to_map': 'keyevent_back', 'try': k + 1, 'dev': dev})
        except Exception as e:      # noqa: BLE001
            log.append({'back_to_map': 'no_more_fallback', 'try': k + 1, 'err': repr(e)})
            break
    b.snap('backmap_end')
    ok = is_map_screen(b.ocr(min_conf=0.2, tag='backmap'))
    log.append({'back_to_map': 'give_up', 'ok': bool(ok)})
    say('       · 回到地图界面: %s' % ('✓' if ok else '✗ 没退干净'))
    return bool(ok)


def find_button(items, *keys, maxlen=4):
    """找**按钮**（不是说明文字）：文字短(≤maxlen)、不含句号、含关键词

    现场教训：结实补给的说明是"使用后立即获得500点体力。"——含"使用"二字 ✗，
    之前的 find_in 把它当按钮点了 ⇒ 什么都没发生（体力 316→316）。
    真按钮「使用」在 (868,1013)，只有 2 个字 ✓
    """
    for it in sorted(items or [], key=lambda x: x['cy']):
        t = (it.get('text') or '').strip()
        if not t or len(t) > maxlen or t.endswith('。') or t.endswith('，'):
            continue
        if any(k in t for k in keys):
            return it
    return None


def find_in(items, *keys):
    """在 OCR 结果里找含任一关键词的条目（优先更靠上的那条）"""
    for it in sorted(items or [], key=lambda x: x['cy']):
        t = it.get('text') or ''
        if any(k in t for k in keys):
            return it
    return None


GUILD_BTN = (63, 1259)        # 主界面左下角「公会」
BAG_BTN = (643, 1120)         # 公会界面右下角「背包」（在「招募」正下方）
#   ⭐ 2026-09-30 重标定 (969,1700)→(964,1680)：模拟器 720x1600 放大条带实测背包图标中心
#   设备 (643,1440) ⇒ 归一化 (964,1680)。旧值 y=1700 的落点在图标热区下沿/横幅上 ⇒
#   公会界面点 BAG_BTN 无反应（bag_not_open ×3 轮，实拍 _verify/bag_final*.png ✓）
ITEM_TAB = (586, 240)         # 背包页签「道具」（最右；⭐ 2026-09-30 实拍校准 (586,360)设备 ✓）
# ⭐⭐ 2026-10-01 真机标定（用户手动停在页面上、我只读抓帧实测；两条通道互验一致 ✓）
#   ① 背包**页签**（素材/装备/符文/宝箱/道具）与**右上角 X** 都落在 `toRef()` 丢弃的
#      弹性带里 ⇒ **归一化帧根本看不见**（OCR 读不到、模板 0.38/0.61 也不中 ✗）
#      ⇒ 它们的坐标是**弹窗系**：必须 `b.tap_dlg(...)` 点（拿 `b.tap` 会偏 C≈209 ✗）
#   ② 「一键升星」两条通道都读到了：归一化帧 @(923,1550) ｜ 弹窗帧 @(923,1759)
#      （差 209 = C ✓ 自洽）⇒ 旧 `UPGRADE_BTN=(928,1789)` 是**弹窗系**值被当归一化系用 ✗
#      —— 真机实测归一化系在 y=1550，这就是"点了一键升星没反应"的原因之一 ✓
# ⭐⭐⭐ 2026-10-03 **真机实测重标**（用户报「装备升星有问题」+ 当场抓屏：
#   `_verify/bag_page_20261003.png` 背包页、`_verify/bag_after_upgrade_20261003.png` 确认框）：
#     页签行（素材/装备/符文/宝箱/道具）实测 **cy=172~173**（bbox y 153~192）
#       旧值 (…,210) ⇒ **落在页签下边缘之下 18px ＝ 点空** ✗
#     一键升星实测 **cx=616 cy=1136**（bbox (576,1119)-(656,1153)）
#       旧值 (615,1033) ⇒ **偏上 103px ＝ 完全点空** ✗ ← 这就是"升星没反应"的直接原因
#     确认框（"提示 / 将所有装备升至最高星级 / 10000"）实测：取消 (222,742)、
#       右按钮（确定+费用）≈**(536,742)** ⇒ 与全游戏确认框同一行 y=742 ✓
#       （dice_yes=(520,742)、退图确认=(516,742) ⇒ 同款控件 ✓）
BAG_TAB_DLG = {'素材': (101, 173), '装备': (231, 173), '符文': (360, 173),
               '宝箱': (489, 173), '道具': (617, 173)}
# ⚠ 2026-10-02 换 720×1280 基准：原 1080p/1600 系 (152,315)…(925,315)，
#   其中 x=732/925 在 720 宽屏上**越界** ⇒ 「宝箱/道具」页签永远点不到 ⇒ 背包断链 ✗
BAG_X_DLG = (705, 80)           # ⭐ 2026-10-03 实测重标（用户报"关闭背包坐标偏下、没关掉"）
                                #   旧值 (682,143)：比真图标**低 63px、靠左 23px** ⇒ 点不掉 ✗
                                #   实测来源：背包页帧 `_verify/bag_page_20261003.png`
                                #     右上角区域逐列/逐行亮度扫描 ⇒ 最亮点 = **(705,80)**
                                #     （面板右上角的 X 图标；区域均值 91、该点 253 ⇒ 明显是图标 ✓）
BAG_UPGRADE_BACK = (359, 808)    # ⭐ 2026-10-03 升星奖励框（「恭喜获得/升星奖励」）的「返回」
                                #   与宝库奖励框的「返回」同位置（实测 (360,808) ✓ 同一控件）
# ⭐⭐⭐⭐ 2026-10-06 升星收尾「回选图界面」的**补点上限**（用户口径，原话）：
#   「**回选图界面核对：还没认到（见日志）装备升级出现这个的时候就再点两次
#     开始冒险，直到能识别到选图界面**」
#   ⇒ 点完那 4 次保底之后，**每轮补点 2 次 + 核对一次**，认到就停 ✓
#   ⚠⚠ **上限必须有**（别去掉 ✗）：真机若换了账号/界面改版/OCR 抽风，
#     「直到认到」会退化成**无限点「开始冒险」** ⇒ 白烧时间、还可能误开图 ✗
#     3 轮 = 最多补 6 次（4 + 6 = 10 次封顶）；到顶就如实记 `bag: back_giveup`，
#     并走**原有兜底**（`_close_bag`）—— 行为与「加补点之前」完全一致 ⇒ 不会更坏 ✓
BAG_BACK_MAX_ROUNDS = 3
BAG_FILTER_DLG = (133, 1136)     # 底部「筛选」（弹窗系；实测 (133,1136) ✓）
UPGRADE_BTN = (616, 1136)        # ⭐ 2026-10-03 实测重标（旧 (615,1033) 偏上 103px ⇒ 点空 ✗）
BAG_UPGRADE_OK = (520, 742)      # 升星确认框「确定」＝ 全游戏统一确认框右按钮 ✓
                                 #   （实测右按钮≈536,742；取 520 与 dice_yes 同值 ⇒ 更保守居中 ✓）
# ⚠⚠ 2026-10-01 修：原来这行紧接着又定义了一次 `UPGRADE_BTN = (928, 1789)`（旧标定值）
#   ⇒ 后者生效，把上面注释标为「弹窗系值被当归一化系用 ✗」的错误值又启用了
#   ⇒ 兜底点击整体偏 C≈209px，真机「一键升星」点空。已删掉重复定义。
EQUIP_TAB = (370, 360)        # 背包页签「装备」（第 2 个；⭐ 2026-09-30 实拍校准 ✓）（⭐ 2026-09-27 新增；
                              #   首次跑会先 OCR 找「装备」✓ 找不到才用这个兜底 ✓）
SUPPLY_TPL = 'templates/items/supply_strong.png'
SUPPLY_MASK = 'templates/items/supply_strong_mask.png'
SUPPLY_THR = 0.90             # 识图匹配下限（自匹配 1.000，其他格子差得远）
# ⭐⭐⭐ 2026-10-02 修「自动体力箱子失效」——
#   真机日志（gui_20261002_221551）：`{"supply":"icon_not_found"}` +
#   「补给识图最好成绩 **0.676** @(345,1121)（阈值 0.90）」
#   ⇒ 公会→背包→道具页签全走通了，**只有识图那一步挂**。
#   根因 = **720p 换基准的第 7 处漏网**：模板 `supply_strong.png` 是 **2026-09-25
#   （1080p 时代）**从屏幕裁的 **150×150** ⇒ 720×1280 上图标只有 **~100×100**
#   ⇒ **单尺度** `matchTemplate` 永远够不到 0.90（实测 0.676 = 只对上一部分）✗
#   为什么门禁没抓到：补给是**次要功能**（平时跑不到）—— 正是 `AGENTS.md §4.2`
#   点名的那一类「平时跑不到 ⇒ 门禁不会红 ⇒ 真机用到才炸」。
#   ⇒ 改成**多尺度**匹配（同一判据、只换尺度；`_find_ui_tpl/_tpl_hit` 早就是这么做的 ✓）：
#     0.667 覆盖 720p、1.0 覆盖 1080p，两头各留余量 ⇒ 换基准/换机型都不怕 ✓
#   ⚠ 代价：7 档 × 一次带掩码匹配 ≈ 0.3s（整条补给流程本来就要好几秒，可忽略）
#   ⚠ 搜索区也从 1080 系折算了（原 330/1500/60/1020 ⇒ ×2/3）
SUPPLY_SCALES = (0.55, 0.62, 0.667, 0.72, 0.80, 0.90, 1.00)


def find_supply_icon(b, img=None):
    """⭐ 靠识图在背包「道具」页里找「结实补给」-> (cx, cy, score) 或 None

    模板是 2026-09-25 从用户屏幕上裁的 150×150 格子（掩码挖掉右下角数量数字，
    因为数量会变、不能参与匹配）。位置**不写死**：每个人背包不一样 ✓

    ⚠⚠ 2026-10-01 修（**Android 上这条以前 100% 失败**）：模板路径原来取的是
    `os.path.dirname(os.path.abspath(__file__))` —— Android 上那是 APK 内的
    `…/chaquopy/AssetFinder/app/`（**只读且没有 templates/** ✗），真正的资源包在
    `filesDir/mapbot_pack/`（= `_MAPBOT_ROOT`，由 port_loop 注入）⇒ 每次都在这里
    返回 None ⇒ 自动补给永远"识图没找到结实补给"✗。
    ⇒ 统一走 `_MAPBOT_ROOT`（PC 侧有兜底 = 本文件目录 ✓），并把"模板缺失/匹配分数"
    say 出来（否则失败是静默的 ✗）
    """
    import cv2
    import numpy as np
    tp = os.path.join(_MAPBOT_ROOT, SUPPLY_TPL)
    mp = os.path.join(_MAPBOT_ROOT, SUPPLY_MASK)
    if not (os.path.exists(tp) and os.path.exists(mp)):
        say('       · ⚠ 补给模板缺失：%s（_MAPBOT_ROOT=%s）' % (SUPPLY_TPL, _MAPBOT_ROOT))
        return None
    tpl = cv2.imdecode(np.fromfile(tp, dtype=np.uint8), cv2.IMREAD_COLOR)
    msk = cv2.imdecode(np.fromfile(mp, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        img = b.img()
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    y0, y1, x0, x1 = 220, 1120, 40, 700          # 道具网格区域（⭐ ×2/3 折算 + 各留余量）
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    sub = sub.astype(np.float32)
    # ⭐⭐⭐ 多尺度（见 SUPPLY_SCALES 处说明）：模板是 1080p 裁的 150×150，
    #   720p 上实物只有 ~100×100 ⇒ 单尺度要么漏、要么误 ✓
    best = None
    for _us in SUPPLY_SCALES:
        _w, _h = int(round(tpl.shape[1] * _us)), int(round(tpl.shape[0] * _us))
        if _w < 8 or _h < 8 or _w >= sub.shape[1] or _h >= sub.shape[0]:
            continue
        _t = cv2.resize(tpl, (_w, _h), interpolation=cv2.INTER_AREA).astype(np.float32)
        _m = cv2.resize(msk, (_w, _h), interpolation=cv2.INTER_NEAREST)
        _mf = (_m > 0).astype(np.float32)
        if float(_mf.sum()) < 20.0:
            continue
        res = cv2.matchTemplate(sub, _t, cv2.TM_SQDIFF, mask=_mf)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        mn, _, loc, _ = cv2.minMaxLoc(res)
        _sc = 1.0 - mn / (float(_mf.sum()) * 255.0 * 255.0)
        if best is None or _sc > best[0]:
            best = (_sc, _us, x0 + loc[0] + _w // 2, y0 + loc[1] + _h // 2)
    if best is None:
        return None
    score, _used, cx, cy = best
    say('       · 补给识图最好成绩 %.3f @(%d,%d) 尺度 %.3f（阈值 %.2f）'
        % (score, cx, cy, _used, SUPPLY_THR))
    return (int(cx), int(cy), round(float(score), 3)) if score >= SUPPLY_THR else None


def use_supply(b, log, names=('结实补给',)):
    """⭐ 使用一个「结实补给」回体力（用户 2026-09-25 给的流程）

        公会(95,1889) → 背包(969,1700) → 道具(926,261) → **识图**找结实补给 → 使用 → 回地图界面
    位置不写死（每个人背包不一样），靠模板匹配 ✓；OCR 只用来找「使用/确定」这类文字按钮。
    **不设数量上限**（勾了就按需一直用），只统计用了几个 ✓
    """
    # ⭐⭐ 2026-09-28 修：`SUPPLY_USED += 1` 走的是**局部变量**语义 ⇒ UnboundLocalError ✗
    #   （实测：补给其实**已经吃成功**（体力 14→489）、退图也退对了，
    #     只在最后统计那一行抛异常 ⇒ 被 except 吞掉 → 返回 False → 上层 `break`，
    #     全靠"后面再读一次体力发现够了"才没断线 ⇒ **侥幸跑通**，必须修 ✓）
    global SUPPLY_USED
    try:
        b.snap('supply0')
        items = b.ocr(tag='supply')
        txt = [i['text'] for i in items]
        # ⭐⭐ 安全闸（2026-09-26 教训）：**必须站在选图界面**才动手
        #   在地图里点 (95,1889) 会落在棋盘格子上 ✗（实测和正在跑的循环抢点击）
        in_map_now = any('结束冒险' in t for t in txt)
        on_select = any(any(k in t for k in ('进入地图', '快速扫荡', '开始冒险', '星界秘境'))
                        for t in txt)
        if in_map_now or not on_select:
            log.append({'supply': 'skip_not_on_select',
                        'in_map': bool(in_map_now), 'on_select': bool(on_select),
                        'texts': txt[:14]})
            say('       · 现在不在选图界面（%s），不碰补给，避免误点地图格子'
                % ('地图里' if in_map_now else '未知界面'))
            return False
        # ② 开背包（⭐ 2026-10-01 与升星同口径重做：**先确认公会界面** → 文字「背包」
        #    → 模板（两帧×多尺度）→ 公会界面锚点；全程 say + 落帧，真机可诊断 ✓）
        # ⭐ 2026-10-01 用户要求：「使用结实补给**记得在悬浮窗的弹窗上给用户看**」✓
        #   （只有 `status()` 的消息会上悬浮条日志行；文本避开 OCR 关键词：不写"背包/关闭/领取"）
        status('体力不够 · 去取结实补给')
        _pub_dump('supply_select', b.img())
        items = []
        opened = False
        for _try in range(3):
            if not _guild_on(items) and not any(
                    '背包' in (i.get('text') or '') for i in items):
                _g = None
                for _i in items:
                    if (_i.get('text') or '').strip().replace(' ', '') in ('公会', '公會'):
                        _g = _i
                        break
                _gat = (_g['cx'], _g['cy']) if _g else GUILD_BTN
                b.tap(_gat[0], _gat[1], wait=2.8)
                log.append({'supply': 'open_guild', 'at': _gat,
                            'by': 'ocr' if _g else 'anchor', 'try': _try})
                say('       · 补给第 %d 轮：先进公会 (%d,%d) %s'
                    % (_try + 1, _gat[0], _gat[1],
                       '（OCR「公会」✓）' if _g else '（底部导航锚点）'))
                time.sleep(1.2)
                b.snap('supply_g%d' % _try)
                items = b.ocr(tag='supply_g')
                _pub_dump('supply_g%d_guild' % _try, b.img())
                if not _guild_on(items):
                    say('       · ⚠ 点了公会但不像公会界面：认到 %s'
                        % ([i['text'] for i in items][:10],))
            _bk = None
            for _i in items:
                if (_i.get('text') or '').strip().replace(' ', '') in ('背包', '道具'):
                    _bk = _i
                    break
            if _bk:
                _tap_verified(b, _bk['cx'], _bk['cy'], 'norm', log=log, what='背包(文字)')
                log.append({'supply': 'open_bag_text', 'at': (_bk['cx'], _bk['cy']),
                            'text': _bk.get('text'), 'try': _try})
                say('       · 开背包：OCR 找到「%s」(%d,%d) ✓'
                    % (_bk.get('text'), _bk['cx'], _bk['cy']))
            else:
                _hit, _ch = _tpl_hit(b.img(), 'guild_bag_icon.png',
                                     region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1000)),
                                             1080, 1920)), 'norm'
                if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                    _hit = _tpl_hit(b.img_dlg(), 'guild_bag_icon.png')
                    _ch = 'dlg'
                if _hit:
                    _tap_verified(b, _hit[0], _hit[1], _ch, log=log,
                                  what='背包(模板%.2f)' % _hit[2])
                    log.append({'supply': 'open_bag_tpl', 'at': (_hit[0], _hit[1]),
                                'score': _hit[2], 'ch': _ch, 'try': _try})
                    say('       · 开背包：模板命中 (%d,%d) %.2f（%s）'
                        % (_hit[0], _hit[1], _hit[2],
                           '弹窗帧' if _ch == 'dlg' else '归一化帧'))
                else:
                    _tap_verified(b, BAG_BTN[0], BAG_BTN[1], 'norm', log=log, what='背包(锚点)')
                    log.append({'supply': 'open_bag_anchor', 'at': BAG_BTN, 'try': _try})
                    say('       · 开背包：文字/模板都没中 ⇒ 公会界面锚点 (%d,%d)' % BAG_BTN)
            b.snap('supply1')
            items = b.ocr(tag='supply')
            _pub_dump('supply%d_bag' % _try, b.img())
            # ⭐⭐ 判"开了没"用**颜色判据**（真机 OCR 读不到标题「背包」二字 ✗）
            _op, _how = _bag_panel_open(b, items)
            if _op:
                opened = True
                say('       · 背包已打开 ✓（判据：%s）' % _how)
                log.append({'supply': 'bag_open_ok', 'how': _how, 'try': _try})
                break
            log.append({'supply': 'open_bag_miss', 'try': _try,
                        'texts': [i['text'] for i in items][:12]})
            say('       · 背包未开（第 %d 轮）：屏上认到 %s'
                % (_try + 1, [i['text'] for i in items][:10]))
        if not opened:
            _ftxts = [i['text'] for i in items][:20]
            log.append({'supply': 'bag_not_open', 'texts': _ftxts})
            say('       · 背包没打开（重试 3 轮 ✗）｜最后一屏：%s' % (_ftxts,))
            _close_bag(b, items, log)
            return False
        # ③ 道具页签（⭐ 2026-10-01 真机修正：**页签只在弹窗帧里** —— 直接走 `_bag_switch_tab` ✓；
        #    旧写法在归一化帧里找「道具」永远找不到 ⇒ 退锚点坐标 (879,360)，而真机上那里是**装备** ✗）
        _ok_tab = _bag_switch_tab(b, '道具', log=log, tag='supply')
        if not _ok_tab:
            _tab = _bag_find(b, ('道具', '物品'), prefer='top', tag='supply_tab')
            if _tab:
                _bag_tap(b, _tab[0], _tab[1], _tab[2], wait=1.5)
                log.append({'supply': 'item_tab', 'at': (_tab[0], _tab[1]),
                            'by': 'ocr', 'ch': _tab[2], 'text': _tab[3]})
                say('       · 道具页 → 点 (%d,%d)（%s OCR ✓「%s」）'
                    % (_tab[0], _tab[1],
                       '弹窗帧' if _tab[2] == 'dlg' else '归一化帧', _tab[3]))
            else:
                # ⭐ 2026-10-01 体检修：同上（道具页签真机在弹窗系 dlg(925,315) ⇒ 设备 y≈620；
                #   旧 `ITEM_TAB=(879,360)` ref ⇒ 设备 y≈923 ⇒ 点空 ✗）
                _pt = BAG_TAB_DLG.get('道具', ITEM_TAB)
                _panel_tap(b, _pt[0], _pt[1], 'dlg', log=log, what='道具页(弹窗系标定)')
                log.append({'supply': 'item_tab_anchor_dlg', 'at': _pt})
                say('       · 道具页 → 页签没认到 ⇒ 弹窗系标定坐标 %s' % (_pt,))
        # ④ 识图找结实补给
        b.snap('supply2')
        _pub_dump('supply_items', b.img())
        hit = find_supply_icon(b)
        if not hit:
            log.append({'supply': 'icon_not_found'})
            say('       · 识图没找到结实补给 ✗')
            _close_bag(b, b.ocr(tag='supply'), log)
            return False
        cx, cy, score = hit
        log.append({'supply': 'icon_hit', 'at': (cx, cy), 'score': score})
        say('       · 识图找到结实补给 (%d,%d) 分数 %.3f' % (cx, cy, score))
        status('找到结实补给 · 正在用…')          # ⭐ 悬浮条上看得见 ✓（用户 2026-10-01 要求）
        b.tap(cx, cy, wait=1.4)
        # ⑤ 使用（⭐ 双通道文字优先：真机上「使用」可能在归一化帧外 ⇒ 补弹窗帧 ✓）
        b.snap('supply3')
        _pub_dump('supply_item_click', b.img(), important=False)
        items = b.ocr(tag='supply')
        _use = _bag_find(b, ('使用', '使用道具'), prefer='bottomright', tag='supply_use')
        if _use:
            _bag_tap(b, _use[0], _use[1], _use[2], wait=1.6)
            log.append({'supply': 'use', 'at': (_use[0], _use[1]), 'ch': _use[2],
                        'text': _use[3]})
            say('       · 使用 → 点「%s」(%d,%d)（%s）'
                % (_use[3], _use[0], _use[1], '弹窗帧' if _use[2] == 'dlg' else '归一化帧'))
        else:
            _btn = [i for i in items if (i['text'] or '').strip() in ('使用', '使用道具')
                    and i['cx'] > LAYOUT.sx(700)]
            if _btn:
                b.tap(_btn[0]['cx'], _btn[0]['cy'], wait=1.6)
                log.append({'supply': 'use_right', 'at': (_btn[0]['cx'], _btn[0]['cy'])})
            else:
                log.append({'supply': 'no_use_btn',
                            'texts': [i['text'] for i in items][:22]})
                say('       · ⚠ 没认到「使用」按钮 ⇒ 屏上：%s'
                    % ([i['text'] for i in items][:12],))
        # ⑥ 确认弹窗（双通道）
        for _ in range(2):
            b.snap('supply4')
            _pub_dump('supply_confirm', b.img(), important=False)
            _ok = _bag_find(b, ('确定', '确认', '使用', '是'), prefer='bottomright',
                            tag='supply_ok')
            if _ok and _ok[1] > LAYOUT.sy(700):
                _bag_tap(b, _ok[0], _ok[1], _ok[2], wait=1.5)
                log.append({'supply': 'confirm', 'at': (_ok[0], _ok[1]),
                            'text': _ok[3], 'ch': _ok[2]})
                say('       · 确认 → 点「%s」(%d,%d)' % (_ok[3], _ok[0], _ok[1]))
            else:
                break
        # ⭐⭐ 用完补给的**三步退图**（用户 2026-09-26 口径）：
        #   ① 「返回」→ ② 右上角关闭背包 → ③ 中间下面「开始冒险」回地图界面
        #   ⚠ ① 必须点**界面上那个「返回」按钮**（用 OCR 找文字），
        #     找不到就**跳过**，绝不盲点左上角 ✗（用户明确要求删掉这个动作 ✗）
        b.snap('supply_ret')
        it_ret = b.ocr(tag='supply')
        back = find_button(it_ret, '返回', maxlen=4) or find_in(it_ret, '返回')
        if back:
            _panel_tap(b, back['cx'], back['cy'], 'norm', log=log, what='返回(文字)')
            log.append({'supply_return': 'back_text', 'at': (back['cx'], back['cy']),
                        'text': back['text']})
        else:
            # 交接文档里记的实测坐标：中间「返回」= (539,1212)（**归一化系** ✓ 仅作兜底）
            # ⭐ 2026-10-01 体检修：走 `_panel_tap` ⇒ 没生效会自动换通道（弹窗系）再试 ✓
            _panel_tap(b, BACK_BTN[0], BACK_BTN[1], 'norm', log=log, what='返回(标定)')
            log.append({'supply_return': 'back_coord', 'at': BACK_BTN,
                        'texts': [i['text'] for i in it_ret][:10]})
        # ② 关闭背包（⭐⭐ 2026-10-01 真机修：背包那个 X 落在 toRef 丢弃的弹性带里
        #    ⇒ 只有**弹窗帧**看得见，且必须 `tap_dlg`（归一化系硬点会偏 C≈209 ✗）
        #    ⇒ 先按面板颜色判"背包还开着吗"，开着就点弹窗系 X；关了就直接走下一步 ✓）
        _op, _how = _bag_panel_open(b, it_ret)
        if _op:
            _panel_tap(b, BAG_X_DLG[0], BAG_X_DLG[1], 'dlg', log=log, what='关闭(弹窗系 X)')
            log.append({'supply_return': 'close_bag_x_dlg', 'at': BAG_X_DLG, 'was': _how})
            say('       · 关背包 → 点右上 X (%d,%d)（弹窗系 ✓ %s）' % (BAG_X_DLG + (_how,)))
            _op2, _how2 = _bag_panel_open(b, None)
            if _op2:
                _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                           what='关闭(归一化 X 兜底)')
                log.append({'supply_return': 'close_bag_ref', 'at': CLOSE_TR_PT,
                            'still': _how2})
        else:
            _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                       what='关闭(归一化 X)')
            log.append({'supply_return': 'close_bag', 'at': CLOSE_TR_PT, 'was': _how})
        # ③ 中间下面「开始冒险」→ 回地图界面
        b.tap(START_ADV[0], START_ADV[1], wait=1.5)
        log.append({'supply_return': 'start_adv', 'at': START_ADV})
        back_to_map(b, log)                 # 兜底：确认真的回到地图界面 ✓
        st = stamina(b.ocr(band=(0, 140), tag='supply'))
        SUPPLY_USED += 1
        log.append({'supply': 'done', 'stamina': st, 'used_total': SUPPLY_USED})
        say('       · 补给流程走完，体力 %s' % st)
        status('补给已用 · 体力 %s' % (st if st is not None else '?'))   # ⭐ 悬浮条可见 ✓
        return True
    except Exception as e:      # noqa: BLE001
        import traceback
        log.append({'supply': 'error', 'err': repr(e),
                    'trace': traceback.format_exc().splitlines()[-2:]})
        say('       · 使用补给出错: %r' % e)
        return False


def _guild_on(items):
    """这一帧像不像**公会界面**（公会/邮件/商店/招募 任一文字命中）

    ⚠ 必须是**模块级函数**：2026-10-01 曾把它写成 `bag_upgrade` 里的嵌套函数，
    内层生成式引用了 `i` 而外层函数又有 `for i in items2:` ⇒ `i` 成了闭包 cell，
    首次调用直接 `NameError: free variable 'i' referenced before assignment in
    enclosing scope` ⇒ **整个升星流程当场崩掉**（真机 15:41/15:51 两轮实锤 ✗）。
    教训：这类"判据函数"一律放模块级，别在长函数里用闭包 ✗
    """
    keys = ('公会', '邮件', '商店', '招募')
    for it in (items or []):
        t = (it.get('text') or '')
        if any(k in t for k in keys):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# 2026-10-01 晚：背包流程的两个真机硬事实（都用真机帧量过 ✓）
#   ① 「背包开了没」**不能靠 OCR 认字**：这台真机 OCR 读不到美术字标题「背包」
#      （日志里只认到物品数量 1931/2280 与 HUD）⇒ 老判据 `any('背包' in text)` 恒 False
#      ⇒ 明明开成功了却判"没开" ⇒ **又去点一次背包图标**（那一下正好点在已开的背包上
#      ⇒ 把它关掉）⇒ 来回空转、最后报「背包没打开」✗ —— 用户看到的就是"打开背包就没后续了"
#   ② 判据改用**颜色**：背包面板是大片棕色，实测占比
#        公会界面 0.29 ｜ 选图界面 0.22 ｜ **背包面板 0.91~0.94**
#      ⇒ 阈值 0.60 干净分开，而且"面积占比"天然与分辨率无关 ✓
BAG_PANEL_THR = 0.60


def _brown_frac(img, box=(200, 600, 900, 1400)):
    """面板棕色占比（见上面 ② 的实测值）"""
    try:
        import numpy as _np
        if img is None:
            return 0.0
        x0, y0, x1, y1 = box
        sub = img[y0:y1, x0:x1].astype(int)
        b, g, r = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        m = (r > b + 25) & (r > 80) & (r < 200) & (g > 40) & (g < 160) & (b < 130)
        return float(m.mean())
    except Exception:       # noqa: BLE001
        return 0.0


def _bag_panel_open(b, items=None):
    """背包面板开了没 → (bool, 依据串)：**颜色为主**（OCR 读不到标题 ✗）+ 文字为辅 ✓"""
    fr = _brown_frac(b.img())
    if fr >= BAG_PANEL_THR:
        return True, 'panel-color %.2f' % fr
    for it in (items or []):
        t = (it.get('text') or '')
        if any(k in t for k in ('背包', '道具', '装备', '材料', '筛选')):
            return True, 'text:%s' % t
    return False, 'panel-color %.2f' % fr


def _img_diff(a, bb):
    """两帧平均绝对差（None 安全 ✓）"""
    try:
        import numpy as _np
        if a is None or bb is None:
            return 999.0
        return float(_np.mean(_np.abs(a.astype(int) - bb.astype(int))))
    except Exception:       # noqa: BLE001
        return 999.0


def _tap_verified(b, x, y, ch='norm', log=None, what='', tries=2):
    """点一下并**验证真的生效** → True/False

    ⚠⚠ 2026-10-01 用户报「为什么要连点三下背包？？」—— **就是本函数的锅**：
      它原来拿 `b.img()` 前后对比判"画面变没变"，而 **`b.img()` 返回的是上一次 `snap()`
      的缓存帧**（点击后没重新取帧）⇒ 前后**永远是同一帧** ⇒ diff≈0 ⇒ 误判"没生效"
      ⇒ 一路重试（阶梯 4 级 × 外层 3 轮 = 最多十几下 ✗✗）。
      正确做法两条：
        ① **直接用 `b.tap()` 的返回值**（= Kotlin 侧"点击后画面有没有变"，最准、零额外开销 ✓）
        ② 需要自己比时必须**先 `b.snap()` 取新帧**（缓存帧不能当"之后"✗，只有长按那条路用）
      阶梯也收窄：默认**最多 2 下**（同点 + 下移 45px），确认没生效才继续 ✓
    """
    ladder = [(x, y, ch, 1.8, 'again'), (x, y + 45, ch, 1.8, 'below'),
              (x, y, ch, 0.35, 'hold'), (x, y, ('dlg' if ch == 'norm' else 'norm'), 1.8, 'cross')]
    for i, (ax, ay, ach, hold, mode) in enumerate(ladder[:max(1, int(tries))]):
        _chg = None
        _before = None
        if mode == 'hold':                  # 长按没返回值 ⇒ 只能前后比（先 snap ✓）
            try:
                b.snap('tapv_pre')
                _before = b.img()
            except Exception:       # noqa: BLE001
                _before = None
        try:
            if mode == 'hold':
                try:
                    b.api.tapRefHold(float(ax), float(ay), int(hold * 1000))
                except Exception:       # noqa: BLE001
                    _bag_tap(b, ax, ay, ach, wait=hold)
            else:
                _chg = _bag_tap(b, ax, ay, ach, wait=hold)
        except Exception as e:          # noqa: BLE001
            if log is not None:
                log.append({'tap_err': what, 'e': repr(e)[:90], 'n': i + 1})
        _diff = -1.0
        if _chg is True:
            _ok = True
        elif _chg is False:
            _ok = False                     # Kotlin 明确回报"没变" ⇒ 不必再自己比 ✓
        else:                               # 长按/无返回值 ⇒ 自己比（**必须 snap 新帧** ✓）
            try:
                b.snap('tapv_post')
                _diff = _img_diff(_before, b.img())
            except Exception:       # noqa: BLE001
                _diff = 999.0
            _ok = _diff >= 2.0
        if log is not None:
            log.append({'tap': what, 'at': (int(ax), int(ay)), 'ch': ach, 'mode': mode,
                        'changed': _chg, 'diff': round(_diff, 2), 'n': i + 1})
        if _ok:
            say('      · 点「%s」(%d,%d)[%s] 生效 ✓%s'
                % (what, ax, ay, mode,
                   ('（画面差 %.1f）' % _diff) if _diff >= 0 else '（b.tap 回报画面有变化 ✓）'))
            return True
        say('      · ⚠ 点「%s」(%d,%d)[%s] **没生效** ⇒ 换下一招' % (what, ax, ay, mode))
    return False


def _bag_switch_tab(b, name, log=None, tag=''):
    """切背包页签（**素材/装备/符文/宝箱/道具**）—— 走**弹窗帧**通道 ✓

    ⭐⭐ 2026-10-01 真机实锤（用户原话：「就是直接点道具那两个字。上面一排
    素材/装备/符文/宝箱/道具都能点」）：
      那一排落在 `toRef()` **丢弃的弹性带**里 ⇒ **归一化帧里根本没有它**
      （OCR 读不到、`bag_tab_*.png` 模板也匹配不上 ✗ —— 这就是"打开背包就没后续"的另一半原因）。
      但**弹窗帧**（`grabDlgPng`：原始帧按锚设备中心重投影，不丢弹性带）里清清楚楚，实测：
        素材 @dlg(152,315) ｜ 装备 (346,314) ｜ 符文 (540,315) ｜ 宝箱 (732,315) ｜ 道具 (925,315)
    ⇒ 切页签固定这么走：`ocr_dlg` **精确匹配**文字 → `tap_dlg` 点击 → 用画面差验证生效 ✓
    """
    try:
        if not (dlg_c() and hasattr(b, 'ocr_dlg')):
            say('      · ⚠ 切页签「%s」：本环境没有弹窗帧通道（C=0？）' % name)
            return False
        its = b.ocr_dlg(tag=(tag + '_tab') if tag else None)
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'bag': 'switch_tab_err', 'tab': name, 'e': repr(e)[:90]})
        return False
    hit = None
    for i in (its or []):
        t = (i.get('text') or '').strip().replace(' ', '')
        if t == name:
            hit = i
            break
    if hit is None:
        # ⭐ 兜底：用**真机标定的弹窗系坐标**（2026-10-01 用户手动停页面时只读抓帧测得 ✓）
        _pt = BAG_TAB_DLG.get(name)
        if _pt:
            # ⚠ 用 `_tap_verified` 判生效（`b.img()` 是缓存帧 ⇒ 自己比 diff 永远是 0 ✗）
            _ok2 = _tap_verified(b, _pt[0], _pt[1], 'dlg', log=log,
                                 what='页签「%s」(标定坐标)' % name)
            if log is not None:
                log.append({'bag': 'switch_tab_anchor', 'tab': name, 'at': _pt, 'ok': _ok2})
            if not _ok2:
                say('      · ⚠ 切页签「%s」用标定坐标也没生效' % name)
            return _ok2
        if log is not None:
            log.append({'bag': 'switch_tab_miss', 'tab': name,
                        'texts': [(i.get('text'), i.get('cx'), i.get('cy'))
                                  for i in (its or [])][:14]})
        say('      · ⚠ 弹窗帧里没找到页签「%s」（屏上：%s）'
            % (name, [i.get('text') for i in (its or [])][:10]))
        return False
    # ⭐ 找到文字页签 ⇒ 同样走 `_tap_verified`（用 b.tap_dlg 的返回值判生效 ✓
    #   —— 2026-10-01 踩过：自己用 b.img() 前后比 ⇒ 缓存帧 ⇒ 永远 diff=0 ⇒ 白点第二次 ✗）
    return _tap_verified(b, int(hit['cx']), int(hit['cy']), 'dlg', log=log,
                         what='页签「%s」' % name)


def _close_bag(b, items, log):
    """退回探索界面（返回/关闭/X 都试）—— **全分辨率**口径

    ⚠⚠ 2026-10-01 体检修（旧写法最后一个兜底是 `b.tap(96, 96)` ✗）：
      真机 1280×2772 上 ref y=96 ≤ 300 ⇒ 走**锚顶段** ⇒ 设备 y = 96×1.1852 + 132 ≈ **246**
      = 顶部 HUD（PID/头像那一排）⇒ **既关不掉面板、还可能误触** ✗
      更根本的：背包右上角 X 落在 `toRef()` **丢弃的弹性带**里
      （真机实测 dlg(1023,215) ⇒ 设备 y ≈ 503；弹性带 = 设备 y 488~852）
      ⇒ **归一化系里没有它的坐标**，只能走弹窗系 ✓
    ⇒ 现在：文字优先 → 面板还开着就点**弹窗系 X**（真机标定）→ 再退归一化系 X ✓
    """
    back = find_in(items, '返回', '关闭', '取消')
    if back:
        _panel_tap(b, back['cx'], back['cy'], 'norm', log=log, what='关闭(文字)')
    else:
        _op, _how = _bag_panel_open(b, items)
        x = find_x(items)
        if x:
            _panel_tap(b, x['cx'], x['cy'], 'norm', log=log, what='关闭(X/认到字)')
        elif _op:
            _panel_tap(b, BAG_X_DLG[0], BAG_X_DLG[1], 'dlg', log=log,
                       what='关闭(弹窗系 X %s)' % _how)
        else:
            _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                       what='关闭(归一化 X)')
    log.append({'supply': 'closed_bag'})


def board_hidden(c):
    """棋盘是不是**被面板/遮罩盖住**（⇒ cells_of 的分类结果不可信，标记也扫不到）

    ⭐ 2026-09-26 修（**"第一把没打到 boss 就退了"的根因**）：
      原来判据只有"全暗"（`light == 0 and gray >= 25`）—— 但**战斗结算面板只盖住棋盘中间**，
      下面还能认出 3 格 ⇒ `light = 3 > 0` ⇒ **漏判** ✗
      ⇒ 棋盘被盖 ⇒ `marks` 扫不到 boss 标记 ⇒ 误判 `finish: targets_done` ⇒ 提前退图 ✗

    实测数据（把 runs/ 里的截图离线丢进 `cells_of`，见 `_probe_board_cover.py`）：

    | 帧 | 内容 | gray | light | 亮度比<0.55 的格数 dim |
    |---|---|---|---|---|
    | `m0_r003.png` | 干净地图 | 6 | 26 | **0** |
    | `m0_r006.png` | 干净地图 | 6 | 26 | **0** |
    | `m0_r008.png` | 结算面板盖住中间 | 32 | 3 | **30** |

    ⇒ 加一条"多数格被压暗"（遮罩会把棋盘压暗 ~35%，`ratio` 掉到 0.25~0.35）；
      **未揭示格恒 ~0.65**（见 §5/§7），所以 0.55 这个阈值不会误伤普通暗格 ✓

    ⚠⚠ 2026-10-01 v1.11【**朋友真机翻车**：进图就报"面板挡住了棋盘 · 正在收起"，实际棋盘空的】
      根因：上面两条判据都是**绝对阈值**（0.55 / 0.85），而 `ratio = 画面亮度 / 模板亮度`
      **依赖设备**（不同机型的截图 gamma / 亮度 / 分辨率缩放会让整盘偏暗）
      ⇒ 正常棋盘被整盘判成"暗格+被压暗" ⇒ 每张图都走"关面板"分支、3 次后 `board_not_visible`
      ⇒ 退图失败 → 游戏恢复 → 下一张图**同样**⋯ ⇒ 用户看到的就是**一直卡在这** ✗✗
      修法（**只收窄、不放松**，绝不放跑真的面板遮挡）：
        ① 只要**有一格 ratio ≥ 0.85**（= 明确"已揭示"的亮格），就**不算被挡住**
           —— 真面板遮罩会把整盘压到 0.25~0.35，**不可能**还剩 0.85 的亮格 ✓
           （这正是朋友那台的情形：营地/已走开的格子还亮着，只是暗格被设备压到 0.55 以下）
        ② 判据里改用**相对本帧的**亮格证据：`light >= 1` 也算"画面正常" ✓
    """
    _st = c.get('st') or {}
    try:
        # ⭐ ref = 本帧**最亮的一格** —— 正常盘必然是"已揭示"的那格（营地/已走开的格），
        #   雾格恒比它暗 ⇒ 用 ref 做**本帧自身的亮度基准**，绝对阈值就变成相对阈值 ✓
        #   （真遮挡会把整盘压到 0.25~0.35 ⇒ ref 也很小 ⇒ 两条判据照样成立 ✓）
        _mx = max([float((v or {}).get('ratio') or 0) for v in _st.values()] or [0.0])
    except Exception:       # noqa: BLE001
        _mx = 0.0
    # ① 全盘"无亮格"：**且连最亮的一格都很暗**（<0.55）才算被遮
    #    —— 加 `_mx < 0.55` 是为了朋友那台"整体偏暗的设备"：它 light 也是 0（没格到 0.75），
    #    但最亮格能到 0.6+ ⇒ 那是**设备暗**、不是**面板遮** ✓（真遮罩不可能还剩 0.55+）
    if len(c.get('light') or []) == 0 and len(c.get('gray') or []) >= 25 and _mx < 0.40:
        return True
    # ⭐⭐⭐ 2026-10-02 修「进图就报『面板挡住了棋盘』→ 3 轮后 board_not_visible，0 产出」
    #   （用户报：「最近又出问题」，日志 gui_20261002_1545xx / runs/merchk）
    #   实测那一帧（runs/merchk/r_154536_0.png）：
    #       最亮一格 ratio = 1.311     ← 画面明确是正常地图
    #       ratio ≥ 0.85 的格数 = 20   ← 大量「已揭示」的亮格
    #       真正被压暗（绝对 <0.55）= **0 格**  ← 一格都没被遮！
    #   根因：下面 `_thr = 0.55 * _mx` 把阈值**跟着最亮格一起放大** ——
    #       _mx=1.311 ⇒ _thr=0.721，而**未揭示雾格恒 ≈0.65**（见 §5/§7）
    #       ⇒ **正常的雾格全部被算成「被压暗」** ⇒ 12 雾格 + 其它凑到 15
    #       ⇒ 刚好 `n >= 15` ⇒ 误判「面板遮住棋盘」✗✗
    #   ⚠ 这条缩放的本意是「设备整体偏暗时不误判」，但方向错了 ——
    #     偏暗设备是**整盘一起暗**（_mx 也小），阈值该跟着**降**；
    #     而现在 `_mx` 越大（画面越正常）阈值反而越高 ⇒ **越正常越容易被判遮挡** ✗
    #   ⇒ 修法：**用绝对阈值 0.55**（与文档里那张实测表一致：
    #     干净地图 dim=0、结算面板遮罩 dim=30），并**保留相对基准只做「设备偏暗」的兜底**：
    #       _thr = min(0.55, 0.55 * _mx)   ← _mx 大时取 0.55（雾格 0.65 不会被误算）
    #                                        _mx 小时取相对值（偏暗设备不误判）✓
    _thr = min(0.55, 0.55 * _mx) if _mx > 0 else 0.55
    n = 0
    for v in _st.values():
        if float((v or {}).get('ratio') or 1.0) < _thr:
            n += 1
    # ⭐⭐⭐⭐ 2026-10-05 **认出来的格太少 ⇒ 也是被挡**（用户报「点开了宝库，过了会就关掉宝库了」）
    #   真机铁证（`runs\loop\loop_log.json` 第 960→966 条）：
    #     960 round4：`board` **13 格**，含 `(2,6) 黄金宝库 score=1.000 ratio=0.994`
    #                 ⇒ `order.buy=1`（计划里该去买它 ✓）
    #     962 round5：`ocr: skip_no_panel`（**判"无面板"⇒ 免整屏 OCR**）
    #     966 round5：`board` **只剩 2 格**（`3,1` ratio 0.743、`5,6` 0.303）
    #                 ⇒ `buy:0`、`gray:6` ⇒ `pending_buy` 空 ⇒ **`targets_done` 退图** ✗
    #   根因：本函数**只看"被压暗的格数 ≥15"**；而**面板盖住棋盘时分类器根本认不出几格**
    #     （用户实测：那一帧只剩 2 格）⇒ `n` 最多 2 ⇒ `n >= 15` **永远不成立**
    #     ⇒ 判"没被挡" ⇒ **免 OCR** ⇒ 宝库面板**没人处理** ⇒ 直接退图 ⇒ 宝库没买 ✗✗
    #   ⚠ 当年（见本函数 docstring 那张实测表）面板遮住时**还能认出 32 格**
    #     （`gray 32 / light 3 / dim 30`）⇒ `>=15` 成立；而识别层收紧之后
    #     （地板判据 + fog/ratio 口径）被遮的帧只能认出个位数 ⇒ **那个前提失效了** ✗
    #   ⇒ 补一条：**认出来的格数本身太少**（`len(_st) < BOARD_MIN_CELLS`）也算被挡 ✓
    #     ⚠ 阈值取 8：真机干净盘 35 格、部分揭开也有 13~26 格；被面板遮住只剩 2 格
    #       ⇒ 8 落在两簇中间，**方向安全**（多判"被挡"只会多跑一次 OCR，绝不漏面板 ✓）
    #
    # ⛔⛔⛔ 2026-10-11 **修「无法正确点击传承祭坛」**（用户报，原话 ✗）
    #   ---- 病 ----
    #     阈值 `n >= 15` **太高** ⇒ **传承祭坛面板帧算出来 n = 14** ⇒ **差 1** ✗
    #     ⇒ 本函数返回 False（"没被挡"）⇒ 调用方 `_need_ocr = False`
    #       ⇒ `ocr: skip_no_panel` ⇒ **整轮免 OCR + 连 `popups()` 都不调** ✗✗
    #       ⇒ **`shrine_flow` 永远没机会跑** ⇒ 用户看到的就是"无法正确点击传承祭坛"✓
    #   ---- 真机铁证 ----
    #     · `runs/acc3/gui_20261011_164317_acc3.log`：
    #         · 点 (72,716) → 弹面板        ← 面板**真的弹出来了**
    #         · 无面板 ⇒ 本轮免 OCR          ← 下一轮却判"没面板"⇒ 跳过 ✗
    #     · 离线复算（生产口径 `board_hidden(cells_of(img))`，`_tmpman/chk_n15.py`）：
    #         干净棋盘 61 帧  ⇒ n **全是 0**
    #         结束冒险确认框  ⇒ n = 10
    #         **传承祭坛面板** ⇒ n = **14**  ← 卡在阈值 15 之下 ✗
    #         合成确认框      ⇒ n = 18
    #         黄金宝库面板    ⇒ n = 0（全屏面板，不吃遮罩）
    #   ---- 这是**同一个 bug 家族的第四次**（本项目反复出现的"判据阈值卡边" ✗）----
    #     代码里 2026-10-05 就记着**宝库版**的同一现象（`:11479`）：
    #       「128 round5：`ocr: skip_no_panel`（判"无面板"⇒ 免整屏 OCR）」
    #       「而**那一判据在宝库面板帧上算出了 False**…⇒ 宝库面板**从来没人处理** ✗」
    #     ⚠ 但当时的修法是**只给宝库开一条捷径**（点击循环里就地买 `vault_flow`）✗
    #       ⇒ **治了宝库、没治根因** ⇒ 祭坛这次又栽在同一个地方 ✓
    #       （教训：补"某一个面板的专用通道"之前，先问"为什么通用判据没接住它" ✓）
    #   ---- 修法：阈值降到实测分界的中点 ----
    #     干净盘 max = **0** ／ 有面板 min = **10**（除宝库那种全屏面板）
    #     ⇒ 取 **6**（落在 0 与 10 之间，两侧各留余量 ✓）
    #     ⚠ 只**降低**阈值（更敏感）⇒ 只会多判"被挡"⇒ 多跑一次全屏 OCR
    #       （代价 ≈0.9s/轮，**绝不漏面板**）—— 方向安全 ✓
    #     ⚠ 宝库那种 `n=0` 的全屏面板**本来就不吃这条判据**（它不压暗棋盘）
    #       ⇒ 那条专用捷径**保留**（两条腿走路 ✓）
    _DIM_N_MIN = 6
    if n >= _DIM_N_MIN:
        return True
    return len(_st) < BOARD_MIN_CELLS


def _board_dimmed(c):
    """⭐ 2026-09-28：进图首帧**暗罩**检测（与 board_hidden 的"面板遮罩"不同物）

    board_hidden() 的 dim 判据是 ratio<0.55（面板遮罩把棋盘压到 0.25~0.35），
    **判不出暗罩帧** —— 进图动画只把全盘均匀压暗 ~35%，已揭示格 ratio 掉到
    ~0.65 > 0.55，dim 计数恒 0 ✗。

    暗罩特征 = **全盘无一格 ratio≥0.85**：正常帧必有已揭示格（营地恒已揭示、
    每图必有营地，营地周边一圈通常也亮），已揭示 ~1.0 vs 暗/雾 ~0.65 是干净
    间隔（loop_log 实测 0.99~1.03 vs 0.65）。格数下限 20 防"只认出几格"的
    边角帧误触发。
    """
    vals = []
    for v in ((c or {}).get('st') or {}).values():
        r = (v or {}).get('ratio')
        if r is not None:
            vals.append(float(r))
    if len(vals) < 20:
        return False
    return not any(r >= 0.85 for r in vals)


#: BUG-3 判据参数：顶部 HUD 条（y 0..180）的**亮像素分位数**。
#: 模态面板给整屏叠一层乘性暗罩（实测 ≈0.27）⇒ **连 HUD 的白字都一起掉下去**。
_VEIL_HUD_Y1 = 180
_VEIL_P95_MIN = 110.0


def modal_veil(b, img=None):
    """整屏**模态暗罩**检测（0 OCR，≈3ms）—— 只回答「屏幕上有没有盖着面板」

    ⭐ 2026-10-06 新增（BUG-3）。量的是**顶部 HUD 条**（`y 0..180`）的 95 分位亮度：
      干净在图内时 HUD 有纯白字（金币/体力/幸运草）⇒ p95 ≈ 146~254；
      而**任何**模态面板（奖励 / 宝库 / 商人 / 结算 / 获得新装备…）都会给**整屏**
      叠一层暗罩 ⇒ HUD 白字被一起压暗 ⇒ p95 ≈ 54~67。

    真机实测定标（**2579 张 in-run 720 帧** ＋ 22 张标注 fixture ＋ 3 张决策点帧）：
      · 有暗罩：p95 **54~67**（真·获得新装备、领取弹窗、宝库面板、结算失败面板…）
      · 无暗罩：p95 **146~254**
      ⇒ 间隔 **67 → 146 之间一帧都没有**，阈值取 **110** 落在正中 ✓
      （`runs/cap_close/` 1283 帧里 70~146 危险带 = **0 帧**）

    ⚠ 它**不能**区分"是哪种面板" —— 奖励/宝库/商人**长得一样**
      （都是「暗罩 + 中间一个框 + 底部一个按钮」），这是 `is_reward_panel()` 早就
      写明的口径（两次视觉兜底都因此误判过）⇒ 本判据**只回答"有没有暗罩"** ✓
      ⛔ 别拿它去替代 `is_reward_panel()` 认奖励弹窗。

    ⚠⚠ **只许单向使用**：返回 `False`（无暗罩）才允许免 OCR；
      返回 `True`（有暗罩 / 判不出来 / 取不到帧 / 出错）⇒ **一律照旧 OCR** ✓
    """
    try:
        im = img if img is not None else (b.img() if b is not None else None)
        if im is None or getattr(im, 'size', 0) == 0:
            return True                      # 拿不到帧 ⇒ 保守：照旧 OCR ✓
        g = cv2.cvtColor(im[:_VEIL_HUD_Y1], cv2.COLOR_BGR2GRAY)
        if g.size == 0:
            return True
        return float(np.percentile(g, 95)) < _VEIL_P95_MIN
    except Exception:       # noqa: BLE001
        return True                          # 出错 ⇒ 保守：照旧 OCR ✓


def find_camp_cell(cells, log=None, where=''):
    """在本帧分类结果里找出**出生点（营地）**那一格 → `(cell, how, score)`

    `how` = `'exact'`（老判据命中）／`'fallback'`（兜底命中）／`None`（都没命中，cell=None）

    ⭐⭐⭐ 2026-10-02 新增兜底 —— 用户报「**怎么规划没了**」（那天那把的 GUI 日志里
      只有「正在找路」，**没有「› 规划：体力 X / N 步」那一行**；结构化日志是
      `{"solver":"no_plan","cost":null,"reason":"exhausted","expanded":1}`）。

      离线复算铁证（`runs/r_204323_0.png`，零体力）：
        · 营地真实位置 = **(4,3)**，它**自己**的单格最佳匹配就是
          `S00003_000 营地` **1.000（满分）**（`state()` 的 per-cell `top` 里写着）
        · 但它被**多格块归组**吞进了锚点 `(3,3)` 的 `S00003_211 巨大沙堡` 块
          （`cells=[(3,3),(4,3),(4,4),(4,5)]`）⇒ 该格对外报 `name='巨大沙堡'`、
          `anchor=(3,3)` ⇒ 老判据「`name=='营地'` **且** `anchor==自己`」两条全挂 ✗
        · ⇒ `st['spawn']` 为空 ⇒ `mapsolve.Problem.visible()` 里
          「开局可点 = **营地四邻**」那一支整体跳过 ⇒ 可点集合 = ∅
          ⇒ A\* 展开 1 个状态就堆空 ⇒ `no_plan`（`mapsolve.py:198-201/364/456`）
        · 附带：`_infer_chain_consumed()` 也拿营地当种子（"找不到营地就直接放弃"）
          ⇒ 连锁消耗推断同时失效
        · 对照（能规划的那把）：营地 `5,6 → S00003_000 / 0.998 / 单格 anchor` ✓

      兜底判据（**只读 `state()` 已经算好的数据，不新增模板、不新增阈值方向**）：
        每格的 `top` = 该格**单格**候选 `[(score, sid, anchor), …]` ⇒ 找
        `sid` 后缀 `000`（= 营地）且 `score ≥ CAMP_TOP_MIN` 的格子，取**分最高**的那个 ✓
        （多格块只会覆盖格子的 `sid/name`，**不会**改掉它单格候选的 `top` ✓）

      ⚠ 只在**老判据一个都没命中**时才用兜底 ⇒ 对"认得出营地"的帧**零影响** ✓
      ⚠ 每次兜底都落一条 `spawn_fallback` 日志（格号 + 分数）⇒ 事后可核对，不静默 ✗
    """
    if not cells:
        return None, None, 0.0
    # ① 老判据：单格块 + 名字就是营地（正常情形，优先，行为与改动前完全一致）
    for k, v in sorted(cells.items()):
        if v.get('anchor') == k and v.get('name') == '营地':
            return k, 'exact', float(v.get('score') or 0)
    # ② 兜底：在每格的**单格候选**里找营地分最高的那格
    best, best_sc = None, 0.0
    for k, v in sorted(cells.items()):
        for t in (v.get('top') or []):
            try:
                sc, sid = float(t[0]), str(t[1])
            except Exception:                 # noqa: BLE001
                continue
            if sid.split('_')[-1] == '000' and sc >= CAMP_TOP_MIN and sc > best_sc:
                best, best_sc = k, sc
    if best is not None:
        if log is not None:
            log.append({'spawn_fallback': '%d,%d' % best, 'score': round(best_sc, 3),
                        'where': where,
                        'note': '营地没被认成单格块（多半被多格块吞了）'
                                '⇒ 用该格单格候选里 000 的最高分兜底'})
        return best, 'fallback', best_sc
    return None, None, 0.0


def _prune_bought_done(st, c):
    """清掉「买完」记忆里**已经真的不再是商人/宝库**的格 —— ⛔ 棋盘被面板挡住时**绝不清** ✓

    ⭐⭐⭐ 2026-10-02 修用户报的「**商人买完后又打开了一次**」：
      真机日志（gui_20261002_223351 / loop_log）：
        #36 {"bought_rec":[72,1004], "cell":"4,1", "bd":[[72,1004]]}   ← 买完，记住了
        #47 {"unpin_dbg":{"kept_bought":[], "now_vendor":[[72,1004]], "dropped":[[72,1004]]}}
        #52 {"round":6, "vault_unpin":1}                              ← 被"放回"⇒ 排进点序
        #54 {"special":"旅行商人","texts":[...,"已购买","已购买","已购买","已购买"]}
                                                                     ← ★ 又开一次，4 档全"已购买"
        根因：**商人面板一开，棋盘就被挡住** ⇒ 本帧 `vault_px_now(c)` 当然是**空的**
          ⇒ 这段"它不再是商人了 ⇒ 清掉记忆"就**在买完的当下把记录删了** ✗
          ⇒ 下一轮摘除判据 `_p in done and _p not in _just_bought` 成立 ⇒ 放回 ⇒ 再点 ⇒ 面板又开 ✗✗
        ⇒ 修法：**棋盘不可见时一律不清**（分类结果此时**不能**当"它不在了"的证据）✓
          这也解释了为什么它"有时候不复现"：只要买完那一轮刚好看得见棋盘，就没事。
    返回清掉的个数（供日志）。
    """
    _n = 0
    try:
        _jb = st.get('bought_done')
        if not _jb:
            return 0
        if board_hidden(c):
            return 0                     # ⭐ 面板开着 ⇒ 看不见棋盘 ⇒ 不许清记忆
        _now_v = set(vault_px_now(c))
        for _q in list(_jb):
            if _q not in _now_v and cell_of(*_q) not in (c.get('buy') or []):
                _jb.discard(_q)
                _n += 1
    except Exception:                    # noqa: BLE001
        return 0
    return _n


def claim_back_poll(b, log, st=None, budget=10.0):
    """领完「探索已完成」奖励 ⇒ 轮询找奖励面板的「返回」并点掉（返回结果 dict）

    ⭐⭐ 2026-10-04 从 `one_round` 里**提取出来单独成函数** —— 目的是能被门禁
      **直接驱动**做回归（`verify_claim_back.py`），因为这段踩过一个真机坑：

      **轮询里漏了 `b.snap()`** ⇒ `b.ocr()` 几轮读的全是**同一张缓存帧**
      （= 点完「领取」那一瞬、面板还没画出来的**过渡帧**）⇒ 永远读不到「返回」
      ⇒ 奖励面板一直盖着棋盘 ⇒ 用户看到「**领取后还是没点返回，卡在返回界面**」✗✗

      ⚠ 这是同一个坑的**第三例**（前两例：`start_fight` docstring、`_tap_verified`）：
        `b.ocr()` 在 PC 上用 `b.img()` = **上一次 `snap()` 的缓存帧**，**不会自己重抓**。
        凡是"轮询看画面有没有变"的循环，每轮都必须先 `b.snap()`。

    实测（真机帧 `_verify/claim_now_20261003.png`，「返回」在 **(359,1196)** conf=1.00）：
      · 旧版窄带 `(1140,1240)` = **3.97~4.69s/次**；**全屏 = 1.41~1.48s/次**（窄带反而更慢！）
        ⇒ 旧版 6s 预算只够 3 轮，而全屏兜底的门槛是 `_polls>=4` ⇒ **是死代码** ✗
      · ⇒ 现在**每次全屏**：更快，且用户口径"返回不一定都在一个位置"本就要求全屏 ✓

    ⏱ 预算 `budget=10.0s`（用户 2026-10-04 口径：「**轮询找返回上限改为 10**」✓）：
      每轮 ≈2s（全屏 1.5s + sleep 0.5s）⇒ 约 **5 轮**。命中就立刻 break，
      所以正常情况**根本用不满**（实测轮询 2 次就命中 ⇒ 5.7s 就收掉了 ✓）。
    """
    _hb = None
    _hi = []
    _t0h = time.time()
    _polls = 0
    while time.time() - _t0h < budget:
        if stop_requested():            # 用户点 ■ 要立刻停
            break
        _polls += 1
        # ⭐⭐⭐ 必须**重新取帧**！漏了这句 ⇒ 下面几轮读的全是同一张旧帧（见 docstring）
        try:
            b.snap('claim_back')
        except Exception:               # noqa: BLE001
            pass
        try:
            _hi = b.ocr(tag='claim_back')
        except Exception:               # noqa: BLE001
            _hi = []
        _cand = [(_it['cy'], _it['cx']) for _it in (_hi or [])
                 if '返回' in (_it.get('text') or '')]
        if _cand:
            _cand.sort()                # 取最靠上那个（与旧逻辑同口径 ✓）
            _hb = (_cand[0][1], _cand[0][0])
            break
        time.sleep(0.5)                 # 0.5s 一次 ✓（用户口径）
    _secs = round(time.time() - _t0h, 1)
    if _hb is None:
        log.append({'explore': 'claim_back_ok', 'at': None, 'via': 'none',
                    'polls': _polls, 'secs': _secs,
                    'note': '全屏搜索没找到「返回」⇒ 放弃这次（不盲点 ✓）'})
        say('       · ⚠ 奖励面板没找到「返回」（轮询 %d 次 / %.1fs）'
            '⇒ 不盲点、留到下一轮/退图流程处理' % (_polls, _secs))
        # ⭐ 取证落盘：真有"找不到返回"的下次，有帧才能定根因（不猜 ✓）
        try:
            _pf = os.path.join(RUNS, (st.get('tag') if isinstance(st, dict) else '') or '',
                               'bagdbg', 'back_miss_%s.png' % time.strftime('%H%M%S'))
            os.makedirs(os.path.dirname(_pf), exist_ok=True)
            cv2.imencode('.png', b.img())[1].tofile(_pf)
            log.append({'explore': 'back_miss_shot', 'file': os.path.basename(_pf),
                        'texts': [(_i.get('text') or '')[:10] for _i in (_hi or [])][:14]})
        except Exception:               # noqa: BLE001
            pass
        return {'at': None, 'polls': _polls, 'secs': _secs}
    b.tap(_hb[0], _hb[1], wait=1.5)
    log.append({'explore': 'claim_back_ok', 'at': _hb, 'via': 'full',
                'polls': _polls, 'secs': _secs,
                'note': '奖励面板「返回」⇒ 收掉 ✓'})
    say('       · 奖励面板 ⇒ 点「返回」(%d,%d)（全屏命中，轮询 %d 次 / %.1fs）✓'
        % (_hb[0], _hb[1], _polls, _secs))
    time.sleep(0.6)
    return {'at': _hb, 'polls': _polls, 'secs': _secs}


def _stuck_why(st, c=None, rnd=None, extra=None):
    """⭐ 2026-10-06 BUG-2：**stuck 归因**（一条结构化日志，不改变任何行为）

    背景：51 张图里 **6 张 stuck（12%）**，合计 **251 秒**白跑（平均 42s/张），
    而 `loop_log.json` 里只有 `{'map':N,'end_reason':'stuck'}` —— **看不出为什么**。
    `map_end_kind`（:10953）已经把「认不出棋盘 / 计划走不下去」分开计数，
    但更细的原因（雾格点不动？没候选？点了没反应？面板盖住？）**没有任何字段**。

    ⇒ 本函数只**读** `st`/分类结果，拼一份诊断快照塞进日志，**不做任何决策** ✓
      （BUG-2 的口径：**先归因再谈修，别猜** —— 跑一轮真机收集证据。）

    返回的字段都刻意取"能从日志直接看出下一步该修哪儿"的那几个：
      · `nochange`  ：点了画面完全没反应（跨轮累计）的格数 ⇒ 大 = 雾格/死格
      · `plan_left` ：计划里还剩几步 ⇒ 0 且 `marked_n>0` = 计划摘光了但还有目标
      · `cands_n`   ：本轮**候选格**数（`order` 里没做过的）⇒ 0 = 真的没得点
      · `gray/light`：未揭示 / 已揭示格数 ⇒ 灰多 = 还大片雾（不该退）
      · `dark`      ：连续判"棋盘被挡"的次数 ⇒ ≥3 就是被面板盖住那条路
    """
    st = st or {}
    _why = {'stuck_why': 'no_progress', 'rnd': rnd}
    try:
        _nc = st.get('nochange') or {}
        _why['nochange_n'] = len(_nc)
        _why['nochange_max'] = max([int(v or 0) for v in _nc.values()] or [0])
        _why['plan_left'] = len(list(st.get('plan') or []))
        _why['marked_n'] = len(list((st.get('marks') or {}).keys()))
        _why['done_n'] = len(st.get('done') or ())
        _why['stuck_n'] = int(st.get('stuck') or 0)
        _why['dark_n'] = int(st.get('dark') or 0)
        _why['blank_n'] = int(st.get('blank') or 0)
        _why['nochange_rounds'] = int(st.get('nochange_rounds') or 0)
        if c:
            _why['gray'] = len(c.get('gray') or [])
            _why['light'] = len(c.get('light') or [])
        if extra:
            _why.update(extra)
    except Exception as _e:         # noqa: BLE001
        _why['stuck_why_err'] = repr(_e)[:80]
    return _why


def one_round(b, log, rnd, prefix, st):
    cold, done = st['cold'], st['done']
    _t_round = time.time()       # ⭐ 诊断用：本轮起点（点序里每次点击相对它记秒数，见 §37.3）
    b.snap('%sr%03d' % (prefix, rnd))
    img = b.img()
    # ⭐⭐⭐ 2026-09-28 修「进图首帧暗罩」（用户报：①精确规划逐格点草地
    #   ②被宝箱隔断的草地被规划当成可连锁）：
    #   进图动画把全盘均匀压暗 ~35% ⇒ 已揭示格 ratio 也掉到 ~0.65 ⇒
    #   ①旧版把全盘判"未揭示" ⇒ plain 连锁断裂 ⇒ 逐格点 ✗；
    #   ②中途加的 score≥0.8 硬翻 revealed 又把**真雾格**翻成已揭示
    #     （分类器能看穿雾，雾格也拿 0.91）⇒ 假连通 ✗。
    #   正确修法 = **等暗罩散去再存图/识别**：rnd==0 先无条件等 2 秒
    #   （enter_map 确认 in_map 后动画多半已播完，这 2 秒是兜底）；
    #   识别后再用 _board_dimmed() 复查兜底（见 cells_of 之后）。
    #   口径：**ratio 是"揭示状态"的唯一可靠信号**（已揭示 ~1.0 vs 暗/雾
    #   ~0.65 干净间隔）；score 只说明"底下是什么"——绝不用 score 硬翻。
    if rnd == 0:
        # ⭐ 2026-09-28 提速（P2）：原版无条件 sleep(2.0)。暗罩/进图动画多数 <1.5s
        #   就播完 ⇒ 改成「棋盘区域画面稳定（~0.5s 不动）就提前通过」，上限仍 2 秒；
        #   后面的 `_board_dimmed()` 复查兜底原样保留，行为不降级 ✓
        # ⛔⛔ 2026-10-02 修 band 是 **1080p 旧值**（§4.2 铁律的又一次翻车）：
        #   原来写死 `band=(1002, 1722)` —— 720×1280 上
        #     · 起点 1002 落在**棋盘下方**（棋盘真实 y = 668~1148）
        #     · 上界 1722 **超出屏高 1280**
        #   ⇒ 取样区几乎全在「棋盘之外」（屏幕最底部的导航条）
        #   ⇒ 那里**永远不变** ⇒ 0.09 秒就判「已稳定」⇒ **提前放行**
        #   ⇒ 暗罩/进图动画**还没播完**就往下走（实测 0.686s，而正确带子要 2.09s）
        #   ⇒ 表现就是「进图后等很久 / 或状态认错」。
        #   ⇒ 改成按 `LAYOUT` 现算**棋盘真实区域**，两个基准都对 ✓
        import layout as _lay_b
        _by0 = int(_lay_b.REF['grid_y0'])
        _by1 = _by0 + 5 * int(_lay_b.REF['grid_cy'])
        if b.fast_ok:
            b.wait_stable(2.0, interval=0.08, thr=1.6, need=6,
                          band=(_by0, _by1))
        else:
            time.sleep(2.0)
        b.snap('%sr%03d_fog' % (prefix, rnd))
        img = b.img()
        log.append({'fog_wait': 'pre_identify', 'secs': 2.0})
    # ⭐ 2026-09-27：**存图必须放在这里**（拿到 img 就存），不能放到函数尾部 ✗
    #   尾部在「动作分发」之后，而 `act == 'battle'/'handled'` 会**提前 return**（见下方）
    #   ⇒ 进图首帧 (rnd==0) 恰好是"点了就开打"的话，尾部那版**根本执行不到** ⇒ 白存 ✓
    #   （实测：末次连刷第 1 张图的 r0 就是 `开打（标记 boss）`，是 battle ⇒ 提前 return）
    #   口径（用户 2026-09-27）：**只存「刚进图那一张」**（最干净 ✓ 后面轮次图标盖住美术 ✗）
    if SAVE_ROUNDS or (SAVE_FIRST and rnd == 0):
        save_board_frame(b, log, rnd=rnd, img=img)
    # ⭐ 2026-09-25 第三次提速：回合开头的全屏 OCR（实测 1.2s，13 轮 = 15.8 秒，是最大头）
    #   其实这一下只需要读 HUD（图名 / 体力 / 踢下线提示）；面板文本在「点完那一下」
    #   已经用条带 OCR 看过了。所以：**只 OCR 顶部 0~320**，只有疑似盖着面板时才补全屏
    #   —— 判据是**棋盘亮度**（面板遮罩会把棋盘压暗 ~35%，跟上一轮比即可，不用绝对阈值）
    # ⚠ 2026-09-25 回退：曾试过「回合开头只 OCR 顶部 HUD（省 1 秒）」，结果**残留面板
    #   在回合开头被漏看 ⇒ 循环对着盖着面板的屏幕继续点 = 用户报的「乱点」**。
    #   正确性优先：回合开头一律**全屏 OCR**（0.75 倍缩放已经把它压到 ~1.5 秒）。
    # ⚠ 2026-09-28 实测否决「跳帧复用 OCR」（P4 试错，已撤）：连续两轮的帧差
    #   （96×160 灰度均值差）最小都有 **42.7** —— 夏日海滩水面等待机动画让画面
    #   永远在动，根本不存在"帧没变" ⇒ 复用永远命中不了，纯加噪音。别再加回来。
    # ⭐⭐⭐ 2026-10-02 提速（用户口径「能省 OCR 就省」）：**先花 ~0.5s 用图像判"有没有弹面板"**
    #   `board_hidden(分类结果)` = dim 计数 + 最亮格阈值（0 OCR）——
    #   正是给 `panel_gone` 做过的同款"图像短路"。
    #   · 没面板 ⇒ **本轮整轮不 OCR**（也不调 popups）✓
    #   · 有面板 / 到刷新轮 / 还没读到图名 ⇒ 照旧真读一次（体力、槽位最多陈旧 1 轮）✓
    #   ⚠ 这与上面 2026-09-25 那次回退**不是同一件事**：那次是**窄带读字**判面板
    #     （残留面板漏看 ⇒ 对着面板乱点 ✗）；这次是**图像判棋盘有没有被挡**，方向正确 ✓
    # ⛔⛔⛔ 2026-10-26 **首轮不要用「空图名」做那次分类**（治「一直是图名未读到」）
    #   ---- 病 ----
    #     原来传 `st.get('mapname') or ''` ⇒ **首轮传的是 ''**（=「试过了仍空」）
    #     ⇒ `board_state` 走「全部 code 当候选」⇒ **15 个 code 各建一次盘**
    #       ⇒ 打出**误导**的「图名『（图名未读到）』有歧义 [15个]」
    #       ⇒ 而**图名其实读到了**（真机 loop_log #7 = "夏日海滩" ✓）—— 只是这句在 OCR 之前打的 ✗
    #   ---- 关键洞察：**首轮那次分类的结果只用来决定要不要 OCR** ----
    #     `_need_ocr` 里已经有 `not st.get('mapname')` ⇒ **首轮必然 OCR** ✓
    #     ⇒ 那次「空图名全量消歧」的结果**只喂给 `board_hidden()`**（判面板），
    #       而它**不改变**「要不要 OCR」这个决定（首轮已经定了：要）⇒ **纯属白花** ✗
    #   ---- 修法（**只改这一处调用点，不动 `board_state` 的语义**）----
    #     首轮（还没图名）⇒ **跳过**那次分类，直接判「要 OCR」；
    #     OCR 之后**用真图名**再分类一次（下面 `c = _cells_cached(...)` 那行已经在做 ✓）
    #   ⚠ 为什么**不能**改 `board_state`（我第一版改错了，被门禁当场抓出 ✓）：
    #     `in_map()`（:4255）也调 `cells_of(img, mapname=map_name(items))`，
    #     那儿**空图名时也要分类结果**（靠「格子兜底」判在不在图里）⇒
    #     一旦让空图名返回空 ⇒ `n=0 < 8` ⇒ 把「在图里」判成「不在图里」⇒ **回归** ✗✗
    #   ⚠ 所以这里用「**跳过**」而不是「改语义」：只影响本函数首轮那一次 ✓
    _mn_have = st.get('mapname')
    if _mn_have:
        _c0 = _cells_cached(b, img, mapname=_mn_have)
        try:
            _panel0 = bool(board_hidden(_c0))
        except Exception:                   # noqa: BLE001
            _panel0 = True                  # 判不出来 ⇒ 保守：照旧真读一次 ✓
    else:
        # ⭐ 首轮：还没图名 ⇒ **必定** OCR（见 `_need_ocr`）⇒ 不必先花 15 个 code 消歧 ✓
        _panel0 = True
    _need_ocr = bool(_panel0 or not st.get('mapname')
                     or int(ROUND_OCR_EVERY) <= 1
                     or (rnd % max(1, int(ROUND_OCR_EVERY))) == 0)
    items = []
    if _need_ocr:
        items = b.ocr(tag='round')
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**为什么会在打的时候抓图名？这个不应该开局
        #   抓体力的时候顺便就抓了吗**」⇒ 对 ✓
        #   图名**只在图内 HUD 上有**（选图界面没有 ✗）⇒ 能读准的时机就是**进图第一帧**
        #     （r0：HUD 干净、没有战斗横幅/难度条干扰 ✓）
        #   而原来这里**每轮都覆盖**：`st['mapname'] = map_name(items) or st.get('mapname')`
        #     ⇒ 打到一半 HUD 上没有图名（或读到「当前难度1000」这类邻座文字 ✗）
        #       ⇒ **把开局读对的值覆盖成垃圾** ✗✗ ⇒ 分类器拿不到代码 ⇒ 走 15 个全量兜底
        #         （≈7.5s/图 + 选错风险 ✗）
        #   ⇒ 现在：**只在还没读到过时读一次**（就是进图第一帧 ✓），之后一律用记住的值 ✓
        if not st.get('mapname'):
            _mn_now = map_name(items)
            if _mn_now:
                st['mapname'] = _mn_now
                # ⭐ 2026-10-26 **同时记到模块级**（供 `run_maps` 退图时用 ——
                #   `st` 在那里**不可见** ⇒ 上一版就是栽在这 ⇒ NameError ✗）
                _LAST_MAPNAME['name'] = _mn_now
                log.append({'mapname': _mn_now, 'round': rnd, 'note': '进图首帧锁定图名 ✓'})
        else:
            _mn_again = map_name(items)
            if _mn_again and _mn_again != st['mapname']:
                # 只记一条诊断（**绝不覆盖** ✓）：帮我们看清"打到一半会读到什么"
                log.append({'mapname_ignored': _mn_again, 'kept': st['mapname'],
                            'round': rnd, 'note': '图名已锁定 ⇒ 忽略这次读数（防被邻座文字覆盖 ✗）'})
        entry = {'round': rnd, 'stamina': stamina(items)}
        # ⭐⭐⭐⭐ 2026-10-05 **金币/幸运草：一图只确认一次**（用户口径，原话）
        #   「扫体力顺便把金币数量也扫了吧…」「**金币幸运草都是一张图只确认一次**」
        #   · 零额外开销（同一份 `items` ✓）
        #   · 首次读到有效值就**锁进 st**；之后一律用锁定值（读不到也不覆盖 ✓）
        #   · 为什么必须锁：HUD 那块常被面板/横幅盖住 ⇒ 每轮重读会让同一张图里的
        #     判断**反复翻转**（目标一会儿拉黑一会儿放回 ✗）
        try:
            _gl, _cl = _lock_hud_once(st, items, log=log, rnd=rnd)
            entry['gold'] = _gl
            entry['clover'] = _cl
        except Exception:       # noqa: BLE001
            pass
        # ⭐⭐⭐⭐ 2026-10-05 **幸运草 < 8 ⇒ 大拇指目标也拉黑**（用户口径，原话）：
        #   「之前那个幸运草低于8不摇色子，改成低于8连直接把大拇指目标都拉黑，
        #     **直接不去打了**」／「也是幸运草大于8就自动不拉黑去打」
        #   理由：大拇指格（推荐战）的**唯一价值**就是打完摇色子出装备 ⇒
        #     幸运草不够 ⇒ 摇了也白摇 ⇒ **整格没价值** ⇒ 不该花体力去打 ✓
        #   ⚠ 判据用**锁定的** `clover_locked`（一图只确认一次 ✓）
        #   ⚠ 读不到幸运草 ⇒ `clover_enough` = True ⇒ **不拉黑**（保守：正常去打 ✓）
        #   ⚠⚠ **这里只记"该拉黑"这个意图**（`st['clover_block']`），
        #      **真正剔除必须等本帧 `mk` 扫完**（见下面 "把被拉黑的大拇指格从标记里摘掉" 那段）
        #      —— 我第一版写在这里，用的是**上一轮的 `mk`**（可能是 `None`）✗
        st['clover_block'] = (not clover_enough(st))
        # ⭐⭐⭐ 2026-09-30 真机事故修复：**每轮轮首都刷新「探索小队槽」**
        #   旧版只在**轮尾**算一次 slots_free ⇒ 凡是走 `act in ('handled','battle',…)`
        #   提前 return 的轮次**根本不会更新** ⇒ 值一直停在旧读数上 ✗。
        #   真机实锤：第 2 轮点「探索」时其实槽已满，可 st['slots_free'] 还是 1
        #   ⇒ 后面 18 轮全在点「探索」（游戏不响应）⇒ 整张图白跑。
        #   轮首这份 `items` 就是当前帧全屏 OCR ⇒ 零额外开销 ✓
        #   ⚠ `explore_slots_free` 认不到「空闲」时返回 None ⇒ **保留旧值**（不瞎写 ✓）；
        #     认到「空闲」= 硬证据 ⇒ 顺手把"两次点不动"的计数清零（说明槽真的空出来了）
        if EXPLORE_DISPATCH:
            _sf_now, _si = explore_slots_free(items)
            entry['slots'] = _si
            if _sf_now is not None:
                st['slots_free'] = _sf_now
                entry['slots_free'] = _sf_now
                if _sf_now > 0 and (_PANEL_STUCK.get('expl') or 0) >= 2:
                    _PANEL_STUCK['expl'] = 0
                    log.append({'slots': 'free_again', 'free': _sf_now})
            else:
                entry['slots_free'] = int(st.get('slots_free', 1) or 0)
    else:
        # 免 OCR 轮：棋盘没被挡 ⇒ **没有面板要处理** ⇒ 不读文字、**也不调 popups** ✓
        entry = {'round': rnd, 'stamina': st.get('stamina_last'),
                 'ocr': 'skip_no_panel',
                 'slots_free': int(st.get('slots_free', 1) or 0)}
        st['ocr_skipped'] = st.get('ocr_skipped', 0) + 1
        log.append({'ocr': 'skip_no_panel', 'round': rnd, 'n': st['ocr_skipped'],
                    'note': '图像判"无面板" ⇒ 本轮免整屏 OCR（省 ≈0.9s）'})
        say('   · 无面板 ⇒ 本轮免 OCR（本图累计省 %d 次）' % st['ocr_skipped'])
    if entry.get('stamina') is not None:
        st['stamina_last'] = entry['stamina']       # 供免 OCR 轮写 entry（统计不留空洞）✓
    if not _need_ocr:
        act = None                                  # 没面板 ⇒ 没有动作要处理 ✓
    else:
        act = popups(b, items, log, ctx={'road': st.get('road') or [], 'plain_road': st.get('plain_road') or [], 'plan_road': st.get('plan_road') or [], 'flags': st, 'st': st.get('cells'), 'slots_free': st.get('slots_free', 1), 'ev_tiles': st.get('ev_tiles') or [], 'tapped_sid': st.get('tapped_sid') or '', 'marks': st.get('marks') or {},
                                     'tapped': st.get('last'),
                                     'force_fight': st.get('force_fight'),
                                     'road': st.get('road') or [],
                                     'targets': (st.get('targets') or []),
                                     'clear_fights': st.get('clear_fights', 0)})
    # ⭐⭐ 2026-09-26 用户口径：「**万能点位可以用来应对异常情况，防止任务过早中断**」
    #   这里统计"一个可识别元素都没认到"（act=='none'）的**连续轮数**；
    #   连续 **3** 轮都没认到 ⇒ 多半盖着一个认不出的异常面板 ⇒ 用万能位兜一手 ✓
    #   ⚠⚠ 门槛不能低（我 2026-09-26 第一版用"连续 2 轮"⇒ 真机上**每两轮误触发一次**）：
    #     「连续 2 轮无弹窗」在正常跑图时是**常态**（点普通格/迷雾格本来就不弹面板）
    #     ⇒ 当时 `universal_close` 的 `is_battle` 判据太松，挑到 (577,1439) 去点，
    #       而**那是棋盘格** ⇒ 乱点 ✗（铁证 m0_r001/003/005 三轮；已由 `is_battle_panel` 修掉 ✓）
    #   ✅ 现在为什么敢点：`is_battle_panel` 严格之后，**在干净地图上**这个兜底只会点
    #     万能位 (541,1890)——用户实测「那边点了非常安全，不会有变化」⇒ 无副作用 ✓
    #   ⚠ 仍明确**不是常规动作**：只要有任何一次可识别的动作（handled/battle/…）就清零 ✓
    _nn = (st.get('popup_none', 0) + 1) if act == 'none' else 0
    st['popup_none'] = _nn
    # ⭐⭐⭐ 2026-09-30「同类动作连点不停」总闸门（真机事故后加的兜底网）
    #   事故原型：`{'explore': 'first_high_value'}` 连打 18 轮（105 秒 0 战斗 0 装备）。
    #   具体那条已在 popups 里修好（点完验证 + 两次判满 + 拉黑），这里再兜一层：
    #   **同一个动作签名连续出现 4 轮** ⇒ 不管它是什么，都认定卡死 ⇒ 万能位脱困 +
    #   拉黑当前格 ⇒ 一定走得掉 ✓（阈值 4 足够大，正常跑图不会连续 4 轮同一动作）
    try:
        _last = log[-1] if log else None
        _sig = None
        # ⚠ 只认**本轮 popups 刚追加的、动作名明确的**条目：
        #   · 带 'round' 的是上一轮的轮摘要 ⇒ 拿它当签名会把"这轮 popups 啥都没追加"
        #     误判成连点 ✗
        #   · 只管「探索/派遣/跳过/弹窗」这几类**动作名稳定**的条目；
        #     **宝库/商人的条目一律不管**（`vault/merchant/buy_*` 的 value 不进签名 ⇒
        #     pick→buy→claim 会被看成同一个签名 ⇒ 兜底网会把正在买的宝库拉黑 ✗
        #     那是用户报过的另一种事故；宝库自己已有 20 轮粘性上限兜底 ✓）
        _KEYS = ('explore', 'dispatch', 'skip', 'popup')
        if isinstance(_last, dict) and 'round' not in _last \
                and any(_last.get(k) for k in _KEYS):
            # ⚠⚠ 签名必须带**刚点的那一格**：像 `{'explore':'claimed_high_value'}` 这种
            #   条目里没有坐标，连派 4 个不同紫橙格会撞成同一个签名 ⇒ 被兜底网误伤 ✗
            _at = _last.get('at')
            _sig = (act,) + tuple(_last.get(k) for k in _KEYS) + (
                tuple(_at) if isinstance(_at, (list, tuple)) else _at,
                tuple(st.get('last') or ()) or None)
        if _sig is not None and _sig == st.get('act_sig'):
            st['act_rep'] = int(st.get('act_rep', 1) or 1) + 1
        else:
            st['act_rep'] = 1
        st['act_sig'] = _sig
        if _sig is not None and st['act_rep'] >= 4:
            log.append({'loop_guard': 'same_action', 'n': st['act_rep'], 'act': act,
                        'sig': [str(x) for x in _sig]})
            say('  [r%d] 同一个动作连续 %d 轮没变化 ⇒ 强制脱困（拉黑这一格）✗'
                % (rnd, st['act_rep']))
            status('卡住了 · 正在脱困')
            force_unstick(b, log, 'same_action_x%d' % st['act_rep'],
                          {'tapped': st.get('last'), 'flags': st})
            st['act_rep'] = 1
            st['act_sig'] = None
            log.append(entry)
            return None
    except Exception:       # noqa: BLE001
        pass
    if _nn >= 3:
        # ⭐⭐ 2026-10-01 用户报「识别到宝库，点开瞬间就关了，后面乱点」⇒ **关之前先自查**
        #   宝库/商人这类面板的标题在真机弹性区里认不到，签名又可能因坐标漂移失效 ⇒
        #   会一路被判成"认不出"然后被万能位关掉 ✗（真机 17:28 实锤）
        #   ⇒ 兜底顺序改成：① 先试**弹窗帧**再判一次面板（宝库签名 + 按钮在哪都记日志 ✓）
        #                  ② 认出来了 ⇒ **不关**，把控制权交回主循环（下一轮就会走 vault_flow ✓）
        #                  ③ 还是认不出 ⇒ 才按老办法万能位兜底 ✓
        try:
            if dlg_c():
                _dp2 = dlg_ocr(b, tag='popup_none_dlg')
                _dbg = [(i.get('cx'), i.get('cy'), (i.get('text') or '')[:8])
                        for i in (_dp2 or [])
                        if 700 < i.get('cx', 0) < 1040 and 1300 < i.get('cy', 0) < 1680]
                log.append({'popup_none_dlg': 'probe', 'btn_zone': _dbg[:8],
                            'n': len(_dp2 or [])})
                if _dlg_btn_sig(_dp2 or [], 'vault'):
                    log.append({'popup_none_dlg': 'vault_found',
                                'btn_zone': _dbg[:4]})
                    say('  [r%d] 弹窗帧认出**黄金宝库**面板 ⇒ 不关它（下一轮进购买流程 ✓）'
                        % rnd)
                    st['popup_none'] = 0
                    log.append(entry)
                    return None
        except Exception as _e:      # noqa: BLE001
            log.append({'popup_none_dlg': 'err', 'e': repr(_e)[:80]})
        universal_close(b, log, items=items, where='popup_none')
        st['popup_none'] = 0
        log.append(entry)
        log.append({'universal_fallback': 'popup_none', 'n': _nn})
        say('  [r%d] 连续 %d 轮认不到任何元素 → 万能位兜底关面板（防任务过早中断）'
            % (rnd, _nn))
        status('画面认不出 · 正在收起面板')
        return None
    if act == 'kicked':
        return 'kicked'
    if act == 'insufficient':
        return 'insufficient'
    # ⭐⭐⭐⭐ 2026-10-07 **预言石碑·停脚本**（用户口径：「类似出现红装标记」）
    #   抽到「幸运」/「和平·金属宝箱怪」且对应开关打开 ⇒ `popups()` 返回 `foretell_stop`
    #   ⇒ 这里**原样往上传**（与 `kicked`/`insufficient` 同一套写法 ✓）
    #   ⇒ 最终 `run_one_map` 的调用方按 `why == 'red_equip'` 那样处置：
    #     **不退图、不补点，停在那里交给人处理** ✓
    if act == 'foretell_stop':
        log.append(entry)
        return 'foretell_stop'
    # ⛔ 2026-10-11 去掉 `act == 'shrine_stop'`（[临时]采集停止已删 ✓）
    #   传承祭坛现在走正常 `handled`（`popups()` → `shrine_flow` ✓）
    if act == 'blocked':
        st['clear'] = True
        log.append(entry)
        return None
    if act in ('battle', 'battle_clear', 'handled'):
        st['stuck'] = 0
        if act in ('battle', 'battle_clear') and st.get('last'):
            # ⭐ 记下「打过架的格」：退出地图前要回到这几格各点一下（领战利品）
            if st['last'] not in (st.get('battles') or []):
                st.setdefault('battles', []).append(st['last'])
        if act == 'battle_clear':
            st['clear_fights'] = st.get('clear_fights', 0) + 1
        if st['last']:
            done.add(st['last'])
            c = cell_of(st['last'][0], st['last'][1])
            if c in (st.get('marks') or {}):
                st['clear'] = False
                st['clear_fights'] = 0
        log.append(entry)
        return None

    # ⭐ 2026-09-27：存图已**提到函数开头**（拿到 img 就存）—— 见 `one_round` 顶部注释 ✓
    #   这里不再存（原来放这儿会被 `act == 'battle'/'handled'` 的提前 return 跳过 ✗）
    c = _cells_cached(b, img, mapname=st.get('mapname') or map_name(items))
    # ⭐⭐⭐ 2026-09-28 暗罩复查（只看 rnd==0）：预等待 2 秒没盖住进图动画时兜底。
    #   _board_dimmed(c) = 全盘无一格 ratio≥0.85 ⇒ 这帧还是暗罩 ⇒ 等 2 秒重截
    #   重识别（最多 2 次；用尽则 fail-open 照常往下走，行为同旧版不会更糟）。
    #   ⚠ 复查只针对"全盘亮格缺失"（暗罩），真·面板遮罩（ratio<0.55）仍由
    #   board_hidden() 管，两套判据各管各的，别混。
    for _fi in range(2):
        if rnd != 0 or not _board_dimmed(c):
            break
        time.sleep(2.0)
        b.snap('%sr%03d_fog%d' % (prefix, rnd, _fi + 1))
        img = b.img()
        c = _cells_cached(b, img, mapname=st.get('mapname') or map_name(items))
        log.append({'fog_retry': _fi + 1, 'dimmed': _board_dimmed(c)})
    # ⭐ 2026-09-26：缓存分类结果 ✓ 供下一轮 popups() 判断"刚点那格是不是紫橙探索格"用 ✓（零额外开销 ✓）
    try:
        st['cells'] = c.get('st')
    except Exception:       # noqa: BLE001
        st['cells'] = None
    # ⭐⭐⭐ 2026-10-01 修「规划很差劲」的**观测脏**根因（用户真机报）：
    #   上面这行是**单帧整体覆盖** ⇒ 任何一帧被面板/动画/加载污染，已知的东西就**丢了**。
    #   真机铁证（17:10~17:12 同一张图）：
    #     [r2] 已揭示 10 → [r3] 已揭示 **11** → [r5] 已揭示 **9**（揭示过的格不该变少 ✗）
    #     ⇒ 下一轮地图模型里那些格又变成"未揭示" ⇒ 求解器以为还得重新开路
    #     ⇒ cost 在 2 → 17 → 7 之间乱跳（同一张图、同一个目标 ✗）
    #   修法：维护 **st['obs']**＝跨轮**只增不减**的观测累积：
    #     · 已揭示（revealed=True）一旦记下**永不被翻回 False**（揭示不可逆 ✓）
    #     · sid/name/ratio/score 用**较可信的那一帧**更新
    #       （已揭示 > 未揭示；同类则 score 高者优先 —— 暗罩帧 score 会掉 ✓）
    #     · mark 取并集（标记扫描也会被遮挡吞掉，见 5135 同因✓）
    #   `st['cells']` 仍保留原始单帧（popups 判"刚点那格"要当下帧 ✓，两套互不干扰 ✓）
    try:
        _obs = st.setdefault('obs', {})
        _added = 0
        for _k, _v in (c.get('st') or {}).items():
            _old = _obs.get(_k)
            _new_rev = bool(_v.get('revealed'))
            if _old is None:
                _obs[_k] = dict(_v)
                _added += 1
                continue
            _old_rev = bool(_old.get('revealed'))
            if _old_rev and not _new_rev:
                continue                     # ✗ 不让脏帧把"已揭示"翻回去
            if _new_rev and not _old_rev:
                _obs[_k] = dict(_v)          # ✓ 新揭示 ⇒ 覆盖（含 sid/name/ratio）
                _added += 1
                continue
            # ⭐⭐⭐ 2026-10-01 修（我上一轮加的累积观测埋的隐患）：
            #   **已揭示格**上"名字变了"必须立刻跟新 —— 尤其是**宝库/商人被买掉之后**：
            #   那一刻它会变成空地（低分/空名）⇒ 旧写法"分数不占优就保留旧值"
            #   会把 `黄金宝库` **永久留在 obs 里** ⇒ 模型/记忆一直以为那儿还有个宝库 ✗
            #   ⇒ 已揭示 + 新帧给的是**别的名字** ⇒ 直接覆盖（揭示后名字变更 = 语义变更 ✓）
            if _old_rev and _new_rev:
                _on = str(_old.get('name') or '')
                _nn = str(_v.get('name') or '')
                if _nn and _on and _nn != _on:
                    _obs[_k] = dict(_v)
                    continue
            _os = float(_old.get('score') or 0)
            _ns = float(_v.get('score') or 0)
            if _ns > _os:                    # 同类 ⇒ 谁看得清听谁的
                _keep = dict(_v)
                if _old.get('marks'):
                    _keep['marks'] = sorted(set(list(_old['marks'])
                                                + list(_v.get('marks') or [])))
                _obs[_k] = _keep
            elif _v.get('marks'):            # 分数不占优 ⇒ 至少把标记并进去 ✓
                _old['marks'] = sorted(set(list(_old.get('marks') or [])
                                           + list(_v.get('marks') or [])))
        # 标记扫描给出、分类器没给的格也累积（真机 boss 格常整帧认不到 ✓）
        for _k, _m in (st.get('marks') or {}).items():
            _ml = list(_m.get('marks') or [])
            if not _ml:
                continue
            _o = _obs.get(_k)
            if _o is None:
                _obs[_k] = {'sid': None, 'name': None, 'marks': _ml,
                            'revealed': bool(_m.get('revealed')), 'ratio': None,
                            'score': None, '_from_mark': True}
            else:
                _o['marks'] = sorted(set(list(_o.get('marks') or []) + _ml))
        if _added and log is not None:
            log.append({'obs_merge': 'grew', 'added': _added, 'total': len(_obs)})
    except Exception as _e:      # noqa: BLE001
        if log is not None:
            log.append({'obs_merge': 'err', 'e': repr(_e)[:80]})
    vis = (len(c['gray']) + len(c['light'])) >= 8
    # ⚠ 2026-09-25 卡死事故：屏幕上盖着面板/遮罩时，分类器会把整盘读成"暗格"，
    #   还会凭弱匹配误报出几个"未揭示的商人/宝库"⇒ 那两个是永不拉黑的目标 → 无限空转。
    #   这里加一道闸：**棋盘被遮住**就认定分类不可信，先关面板；连关 3 轮不行就退出本图。
    # ⭐⭐ 2026-09-26 修：判据原来只有"全暗"（light==0 且 gray>=25）—— 但**结算面板只盖住
    #   棋盘中间**，下面还能认出 3 格 ⇒ light=3>0 ⇒ **漏判** ✗ ⇒ marks 扫不到 boss 标记
    #   ⇒ 误判 `finish: targets_done` ⇒ **没打 boss 就退图**（用户 2026-09-26 报的就是这个）
    #   ⇒ 改用 `board_hidden()`（多一条"多数格被压暗"）；实测数据见该函数注释 ✓
    if board_hidden(c):
        # ⭐ A（2026-09-25 用户要求「暗格误判别浪费一整轮」）：战斗结算/动画过渡那一帧
        #   也会"整盘暗格" ⇒ 先**快速复查**（0.4 秒后重抓）——过渡帧通常已经过去，
        #   复查正常就照常继续，不白花一轮（实测每图能少 1~2 轮空转）
        # ⭐⭐⭐ 2026-10-03 **r0 要更耐心**（真机 acc2 事故，用户报「一进去就退了」）：
        #   日志 `[r0] 已揭示 0 / 暗格 25` + `本图结束：stuck（耗时 4 秒）`
        #   而**同一轮存下的** `runs/acc2/r_023121_0.png` 分类是 light=24/gray=10（正常盘！）
        #   ⇒ 真相是**进图加载还没结束**（黑屏/暗罩），只等 0.4 秒就下结论 ⇒ 判"被挡"⇒
        #     连着几轮关面板 ⇒ stuck 退图 ✗（那台机器进图明显慢于 0.4s）
        #   ⇒ r0 放宽到 **1.5s × 最多 4 次**；非 r0 仍用原来的 0.4s 快速复查 ✓
        #     （代价：只在"r0 且真被挡"时多花 ~6s，而那种情况本来就要 stuck ✓）
        _tries = 4 if rnd == 0 else 1
        _gap = 1.5 if rnd == 0 else 0.4
        c2 = None
        for _bi in range(_tries):
            time.sleep(_gap)
            b.snap('%sr%03d_b%d' % (prefix, rnd, _bi))
            img2 = b.img()
            c2 = cells_of(img2, mapname=st.get('mapname') or map_name(items))
            if not board_hidden(c2):
                log.append({'board_blink': 'ok_after_retry', 'try': _bi + 1,
                            'gap': _gap, 'rnd': rnd})
                c, img = c2, img2
                break
        if c2 is not None and not board_hidden(c2):
            pass                    # 复查后正常 ⇒ 照常往下走（不白花这一轮 ✓）
        else:
            # 整盘暗格 ⇒ 多半盖着面板 ⇒ 这里补一次**全屏 OCR** 再关
            items = b.ocr(tag='round_full')
            _hctx = {'road': st.get('road') or [], 'plain_road': st.get('plain_road') or [], 'plan_road': st.get('plan_road') or [], 'flags': st, 'st': st.get('cells'), 'slots_free': st.get('slots_free', 1), 'ev_tiles': st.get('ev_tiles') or [], 'tapped_sid': st.get('tapped_sid') or '', 'marks': st.get('marks') or {},
                     'tapped': st.get('last'),
                     'force_fight': st.get('force_fight'),
                     'road': st.get('road') or [],
                     'clear_fights': st.get('clear_fights', 0)}
            act2 = popups(b, items, log, ctx=_hctx)
            if act2 == 'kicked':
                return 'kicked'
            if act2 in ('battle', 'battle_clear', 'handled'):
                return None
            # ⭐⭐ v0.34（彻底解决"真机认不出面板类型"）：
            #   面板确实盖着棋盘（board_hidden 已确认）但 popups 没认出类型 ⇒
            #   八成是**面板标题落在归一化帧丢弃的弹性区**（战斗事件 dlg≈443 / 偶遇强敌
            #   dlg≈243 / 旅行商人 / 预言石板…）⇒ 补一次**弹窗帧** OCR（≈2s，
            #   **仅此一处**、仅真机高分辨率）再判一次 ✓（PC/9:16 直接跳过）
            if act2 in (None, 'none') and dlg_c():
                _dp = dlg_ocr(b, tag='round_dlg')
                if _dp:
                    _hctx2 = dict(_hctx)
                    _hctx2['in_dlg'] = True
                    _OCR_CH['dlg'] = True      # ⭐ _dp 是弹窗系 ⇒ 里面所有条目点击走 tap_dlg
                    try:
                        act3 = popups(b, _dp, log, ctx=_hctx2)
                    finally:
                        _OCR_CH['dlg'] = False
                    log.append({'popup': 'dlg_frame_retry', 'n_items': len(_dp),
                                'act': act3,
                                'texts': [(i.get('text') or '')[:10] for i in _dp][:26]})
                    if act3 == 'kicked':
                        return 'kicked'
                    if act3 in ('battle', 'battle_clear', 'handled'):
                        return None
                    act2 = act3
            n = close_x_panels(b, img)
            if not n:
                x = find_x(items)
                if x:
                    b.tap(x['cx'], x['cy'], wait=1.5)
                    n = 1
            if n == 0 and not st.get('last'):
                # ⭐ 2026-10-02 修 1080p 残留（同上面那处）：x 1024 超屏宽、y 225 是参考系值
                #   ⇒ ×2/3 = x 329/683、y 150（== `layout.REF['close_x_*']` ✓）
                for bx in (329, 683):
                    b.tap(bx, 150, wait=1.1)
                n = 2
            st['dark'] = st.get('dark', 0) + 1
            # ⭐⭐ 2026-09-26 用户口径：「万能点位可以用来应对异常情况，防止任务过早中断」
            #   「棋盘被盖住」= **面板挡住棋盘**的确凿证据（不是盲点）⇒ 这里点万能位最合适 ✓
            #   ⚠ 放在判 stuck 之前：老逻辑第 3 次就 `finish: board_not_visible` 中断任务 ✗，
            #     现在第 2 次先让万能位救一手（用户实测「那边点了非常安全，不会有变化」）✓
            #   ⚠ universal_close 会先认面板类型：战斗界面改点「关闭」(577,1439)，绝不点开始冒险 ✓
            if st['dark'] >= 2:
                universal_close(b, log, items=items, where='board_all_dark')
                log.append({'universal_fallback': 'board_all_dark', 'n': st['dark']})
                say('  [r%d] 棋盘被挡 → 万能位兜底关面板（第 %d 次）' % (rnd, st['dark']))
            # ⭐⭐⭐ 2026-10-01 v1.11【"被判挡住"必须能自证 + 不再无限循环】
            #   朋友真机实况：「进图就显示面板挡住了棋盘，正在收起，一直卡在这，棋盘上啥都没有」
            #   ① 第一次判"被挡"就**存帧**（诊断用）—— 我们手上没有任何"别的机型"的帧，
            #      没有它就无法给 `board_hidden` 的绝对阈值标定（见该函数注释）✗
            #   ② 连续多张图都判"被挡" ⇒ **整局停下并说清原因**（不再"退图失败→恢复→再来一张"）
            if st['dark'] == 1:
                try:
                    _hp = _pub_dump('board_hidden_r%d' % rnd, b.img())
                    if _hp:
                        say('     · 这一帧已存档（诊断用）：%s' % _hp)
                        log.append({'board_hidden_dump': _hp})
                except Exception as _eh:      # noqa: BLE001
                    log.append({'board_hidden_dump_fail': repr(_eh)[:80]})
            say('  [r%d] 棋盘被挡（读成暗格/压暗，面板挡住棋盘？）→ 关面板 %d 个（第 %d 次）'
                % (rnd, n, st['dark']))
            status('面板挡住了棋盘 · 正在收起')
            log.append(entry)
            log.append({'board_hidden': 'all_dark', 'closed': n, 'n': st['dark'],
                        'light': len(c['light']), 'gray': len(c['gray'])})
            if st['dark'] >= 3:
                log.append(_stuck_why(st, c, rnd, {'stuck_why': 'board_not_visible'}))
                log.append({'finish': 'board_not_visible'})
                return 'stuck'
            return None
    st['dark'] = 0
    # ⭐ 2026-10-02：能走到这里 = **棋盘是干净的**（没有被面板盖住）⇒ 上一轮记下的
    #   「待摇色子」已经不可能兑现了（结算面板早该在这一轮或上一轮出现）
    #   ⇒ 立刻作废，免得**很多轮之后**某个不相干的结算面板被误摇一次（白耗幸运草 ✗）
    #   （正常兑现路径：`_res` 或 `already_result_panel` 摇完就清，走不到这里）
    if st.get('dice_pending'):
        log.append({'dice': 'pending_expired', 'marks': list(st.get('dice_pending') or []),
                    'note': '棋盘已可见 ⇒ 上一轮记的待摇作废（没有结算面板可摇）'})
        st['dice_pending'] = None
    # ⚠⚠ 2026-10-02 修 `UnboundLocalError: _new_mk`（真机 #20 直接崩在这一轮）
    #   `_new_mk` / `_old_mk` / `_dim_now` 原本在 `if vis:` 里赋值，
    #   而下面 6693 行的「压暗保留」判据**在 if 之外**用到它们
    #   ⇒ 棋盘不可见那一帧（`vis` False）⇒ 三个都没定义 ⇒ UnboundLocalError
    #   ⇒ 整个循环进程退出（退出码 1）✗
    #   ⇒ 提到 if 之前先给安全默认值（下面 `if vis:` 里会覆盖真值 ✓）
    _new_mk, _old_mk, _dim_now = None, {}, 0
    if vis:
        _new_mk = marks_mod.scan_board(img)
        # ⭐⭐ 2026-09-26 保险：**别让"被压暗的一帧"把标记吞掉**
        #   实测 m0_r008：结算面板只盖住棋盘**中间**，那一帧 marks 扫成空
        #   ⇒ 上一轮的 boss 标记就此丢了 ⇒ 误判 `targets_done` ⇒ **没打 boss 就退图** ✗
        #   规矩：新扫结果为空 + 上一轮有标记 + 这一帧确实有被压暗的格（可疑）
        #   ⇒ **保留上一轮的标记**（宁可多找一次，也绝不漏 boss ✓ 用户口径：boss 必打）；
        #     真打过/不存在的标记会被 nochange 拉黑 + cold 兜住，不会死转 ✓
        _old_mk = st.get('marks') or {}
        _dim_now = 0
        for _v in (c.get('st') or {}).values():
            if float((_v or {}).get('ratio') or 1.0) < 0.55:
                _dim_now += 1
        if (not _new_mk) and _old_mk and _dim_now >= 3:
            log.append({'marks_kept': 'board_dimmed', 'dim': _dim_now, 'kept': list(_old_mk)})
            say('  [r%d] 这一帧棋盘被压暗（%d 格）却扫不到标记 → 保留上一轮的标记 ✓'
                % (rnd, _dim_now))
        else:
            st['marks'] = _new_mk
    mk = st.get('marks') or {}
    # ⚠ 2026-09-25：面板盖住棋盘时**不采信标记**（游戏用同一个红装图标标敌方 SS 装备，
    #   面板里的那枚会被误判成地图标记）。判据：该格亮度比 < 0.50（未揭示格恒 ~0.65）。
    # ⛔⛔ 2026-10-02 修「大拇指打了却不摇色子」（用户报）：
    #   这条判据把**结算面板遮罩下的真目标**一起丢掉了 ——
    #   面板压暗会把整盘拉到 0.2~0.3（实测 2,4 ratio=0.303），
    #   而上面的 `_new_mk` 空 ⇒ 已经判定「是面板压的，保留上一轮标记」，
    #   **紧接着这里又按 ratio<0.55 把它们全删了** ⇒ 自相矛盾 ✗✗
    #   真机日志（runs/loop）：
    #       #179 {"popup":"result_panel", …}                  ← 结算面板
    #       #186 {"marks_dropped_panel":"2,4","ratio":0.303,
    #             "marks":["recommend"]}                        ← 大拇指被丢
    #   ⇒ `'recommend' in marks` 不成立 ⇒ **摇色子分支永不进入** ⇒ 打完直接关面板。
    #   ⇒ 修法：**已经因「压暗」而保留下来的标记，不许再被压暗判据丢**；
    #     只丢「本帧新扫到、但又暗」的（那才是面板里的误判）✓
    _kept_by_dim = bool((not _new_mk) and _old_mk and _dim_now >= 3)
    if mk and c.get('st'):
        bad = []
        for k in list(mk):
            v = c['st'].get(k)
            if v is None:
                continue
            if float(v.get('ratio') or 1.0) < 0.55:
                # ⭐ 压暗期间**沿用上一轮**的标记 = 这些是**真目标**，只是被面板盖暗
                if _kept_by_dim and k in (_old_mk or {}):
                    continue
                bad.append(k)
        for k in bad:
            log.append({'marks_dropped_panel': '%d,%d' % k,
                        'ratio': round(float(c['st'][k].get('ratio') or 0), 3),
                        'marks': mk[k].get('marks')})
            mk.pop(k, None)
        if bad:
            say('       · 丢掉 %d 个疑似「面板里的图标」误判（那几格被面板盖着）' % len(bad))
        st['marks'] = mk
    if mk:
        entry['marks'] = {'%d,%d' % k: v['marks'] for k, v in mk.items()}
    # ⭐⭐⭐ 2026-10-12（工单 06 T3 / 规划 05 §4.5c）**进图后首次观测落盘**（BoardSnapshot）
    #   用户原话：「**实时棋盘显示的有点慢，能不能快一些，最好在真机执行之前，
    #              而且尽量不影响真机执行速度**」
    #   ---- 病 ----
    #     `st['obs']`/`c['st']`（整盘格名）在**第 1 轮分类**时就有了，但把它写进
    #     `loop_log.json` 的只有 `flush(log)`，而 flush 的调用点全在"退图/收工/异常"路径
    #     ⇒ 图内不落盘 ⇒ GUI 的棋盘要**等这张图跑完**才看得到格名 ✗（= 用户说的"慢"）
    #   ---- 修法（档 A：一次性、毫秒级、零识别开销）----
    #     **每张图只写一次**（`st['_snap_done']` 守卫，不是每轮 ✗）：
    #     把本帧分类结果压成与 round 事件 `board` **同构**的 dict ⇒ GUI 不用新解析 ✓
    #     ⚠ 字段名是**新的 `board_snapshot`**，**绝不用 `round`** —— 否则会被
    #       GUI/排查工具当成"真打了一轮" ✗（同理不写 `round` 键，只写 `snap_round`）
    #     ⚠ 位置：在**棋盘可信**（`board_hidden` 复查已过）与**标记已定**之后、
    #       **任何点击之前** ⇒ 进图 ~1 秒就到 GUI，远早于真机执行 ✓
    #     ⚠ 其余 flush 点**一个都不动**（"每张图结束才全量落盘"的既有节奏不变 ✓）
    if not st.get('_snap_done'):
        try:
            # ⛔⛔ 2026-10-19 **保留全部格，别再按 anchor 过滤**（真机事故）
            #   用户报：「就是多格战斗格子只显示一格」
            #   ---- 病 ----
            #     原来 `if v.get('anchor') == k` 只收"自己是锚点"的格 ✗
            #     而多格地块（遗迹石碑/白骨/枯木…占 2~4 格）在 `state()` 里
            #     **每一格都有一条**（同 sid 同 score，`anchor` 指锚点、`cells` 列全部格）
            #     真机实测：35 格里 **27 个锚点 + 8 个非锚点**
            #     ⇒ 快照只写 27 格 ⇒ GUI 少画 8 格 ⇒ "多格战斗格只显示一格" ✗✗
            #   ---- 修法 ----
            #     收**全部格**（与 `round` 事件的 `board` 口径一致 —— 那条一直是全格的 ✓）
            #     并在值里带上 `cells`（第 5 项），GUI 若需要"这是多格块"可直接读 ✓
            #   ⚠ 兼容：前 4 项 `(sid末段, name, score, ratio)` 顺序**不变** ✓
            _bs = {}
            for k, v in sorted((c.get('st') or {}).items()):
                try:
                    _cells_v = [list(map(int, x)) for x in (v.get('cells') or [])]
                except Exception:           # noqa: BLE001
                    _cells_v = []
                _bs['%d,%d' % k] = (str(v.get('sid') or '').split('_')[-1],
                                    v.get('name'), v.get('score'),
                                    v.get('ratio'), _cells_v)
            _bsm = {'%d,%d' % k: list(v.get('marks') or []) for k, v in (mk or {}).items()
                    if v.get('marks')}
            # ⛔⛔ 2026-10-19 **只按"格数够不够"判，不看图名**（两次真机事故的合并教训）
            #   ---- 事故一（用户：「荒凉戈壁模板用错了吧，显示海边杂物？」）----
            #     loop_log 里有多条 `board_snapshot` 只有 **2~5 格**，
            #     地块名还是上一张图（夏日海滩）的残留 ⇒ GUI 画出"假棋盘" ✗
            #   ---- 事故二（用户：「刚刚实时棋盘的都不是正在执行的那张图」）----
            #     我第一版修法写成 `bool(mapname) and len(_bs) >= _SNAP_MIN`，
            #     结果真机日志是 `{'snap_skip': 1, 'have': 28, 'mapname': ''}`
            #     ⇒ **28 格完整棋盘只因图名没读到就被拦了** ✗✗
            #     ⇒ 图内零整盘数据 ⇒ GUI 只能显示 `round` 的稀疏板（10 格）
            #       或**上一张图遗留的 board** ⇒ 用户看到"不是正在跑的那张图" ✗
            #   ---- 为什么图名不该当前提 ----
            #     · 棋盘准确性只依赖**分类器**（`_disambiguate_map` 已用真帧挑对地图 ✓）
            #     · 图名只影响 `bot_gui._new_map` 的换图判据（已有三重兜底 ✓）
            #     · 进图首帧读到图名的概率**不高** ⇒ 拿它当前提 = 经常不写 ✓
            #   ⇒ **只判格数**：`len(_bs) >= _SNAP_MIN`（正常盘 21~29，2~5 显然不可信）
            _snap_ok = (len(_bs) >= _SNAP_MIN)
            if not _snap_ok and rnd <= 2:
                st['_snap_skip'] = st.get('_snap_skip', 0) + 1
                if log is not None:
                    log.append({'snap_skip': st['_snap_skip'],
                                'have': len(_bs), 'need': _SNAP_MIN,
                                'mapname': st.get('mapname') or ''})
            if _snap_ok:
                st['_snap_done'] = True
                # ⭐⭐⭐ 2026-10-19 **加 `t0`（本图开始时刻）当"图身份"**
                #   ---- 为什么必须加（真机事故）----
                #     用户报：「实时棋盘用的上一张图的，规划用的现在这张图的」
                #     实测 4 张连刷图的快照：mapname 全是"幽暗密林"、格数全是 35、
                #     键集合完全一样 ⇒ **指纹完全相同** ⇒ GUI 判不出"换图了"
                #     ⇒ `_board_frozen` 永不清 ⇒ 棋盘永远停在第 1 张 ✗
                #     而 `_live_plan` 来自 stdout（每图刷新）⇒ 棋盘旧 + 规划新 = 错位 ✗✗
                #   ---- 为什么用 `t0` ----
                #     `st` 是**每图一份**新建 dict ⇒ 它的创建时刻天然"一图一值" ✓
                #     比"图名/格数/键集合"强得多（那些在连刷同图时会重复）
                #   ⚠ 取 `st.get('t0')`（若有）；没有就用当前时间（仍每图不同 ✓）
                _bs_t0 = st.get('t0') or st.get('_t0') or time.time()
                _bs_rec = {'board_snapshot': True, 'snap_round': rnd,
                           't0': round(float(_bs_t0), 3),
                           'mapname': st.get('mapname') or '', 'board': _bs}
                if _bsm:
                    _bs_rec['marks'] = _bsm
                _sp_px = st.get('spawn') or st.get('camp')
                if _sp_px:
                    try:
                        _bs_rec['spawn'] = '%d,%d' % cell_of(_sp_px[0], _sp_px[1])
                    except Exception:       # noqa: BLE001
                        pass
                log.append(_bs_rec)
                flush(log)          # ⭐ **整张图只这一次**（毫秒级纯写盘，不碰截图/OCR/点击 ✓）
        except Exception as _e_bs:      # noqa: BLE001
            try:
                log.append({'board_snapshot': 'err', 'e': repr(_e_bs)[:80]})
            except Exception:           # noqa: BLE001
                pass
    # 🛑 红装（SS）标记：**只在刚进图那拨扫描时判断**（用户 2026-09-25：「只扫描刚进图那一拨的
    #   图来确认有没有红装，后面不判断红装」）。
    #   ⚠ 为什么不能每轮都判：游戏给**敌方装备带 SS** 时用的是同一个 `mid_ico_map_0001` 图标，
    #   面板（偶遇强敌/结算）盖住棋盘时那枚图标会被当成"地图格上的红装标记"
    #   （实测两次误判都是 (4,3) 分数 0.901 / 配色 0.846，且该帧"已揭示 0 格、暗格 6 格"
    #    = 面板盖着棋盘 ⇒ 用户「我游戏里没看到红装啊」）。
    #   ⭐⭐ 再加一道**根因判据**：这一帧必须**看得见棋盘**（有已揭示格）才允许判红装 ——
    #   面板/结算盖住棋盘时一律不判，从根上堵死这个误判。
    red = []
    if rnd <= 1 and len(c.get('light') or []) > 0:
        red = sorted(k for k, v in mk.items() if 'redEquip' in (v.get('marks') or []))
    elif rnd <= 1:
        log.append({'red_skip': 'board_hidden', 'light': 0})
    if red:
        # ⭐ 留证据图（极速截图通道下帧只在内存，默认不落盘 —— 2026-09-25 用户问「红装截图在哪」）
        shot = None
        try:
            shot = b.snap('red_equip_r%02d' % rnd, save=True)
        except Exception:       # noqa: BLE001
            pass
        # ⛔⛔ 2026-10-12 **不再上锁**（用户原话：
        #   「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
        #   ---- 删掉了什么 ----
        #     原来这里 `json.dump({...}, red_lock_path(b.dev))` 写一个锁文件，
        #     启动时 `red_locked()` 读到它就**拒绝启动**，
        #     要人去窗口点「红装已处理·解锁」才放行 ✗
        #   ---- 为什么删 ----
        #     用户要的是"**遇到就停**"这个动作本身；
        #     锁是**额外的一层**（拒绝后续启动）⇒ 不必要、还老要人工解锁 ✗
        #     （真机就卡过两次：`kind=shrine` 那次报成"红装"、`kind=foretell` 那次
        #       显示"未知类型" ⇒ 用户问「**怎么解除锁定**」+「**我不需要这个锁定**」✓）
        #   ⇒ 现在：**只停、不锁** —— 停下来把现场留着，用户处理完直接再点「开始」✓
        log.append(entry)
        log.append({'stop': 'red_equip_mark',
                    'cells': ['%d,%d' % k for k in red],
                    'shot': os.path.basename(shot or '')})
        say('')
        say('🛑🛑 发现红装（SS）标记：%s → 立即停止（不点它、不退图，留着你自己打）'
            % '、'.join('第%d行第%d列' % k for k in red))
        say('')
        status('★ 发现红装 · 已停下，请手动处理')
        return 'red_equip'

    # ⛔⛔ 2026-10-11 **删掉「[临时]采集两停闸门」**（用户要求去掉[临时]采集停止 ✓）
    #   用户原话：「**把窗口那个临时用的采集停止去掉吧**」
    #   ── 它原来是干什么的 ────────────────────────────────
    #     2026-10-08 为了采"最后两个特殊地块"的面板而加的：图上认出
    #     `机巧宝箱怪` / `传承祭坛` ⇒ **立刻停 + 保现场** ✓
    #   ── 为什么现在能删 ──────────────────────────────────
    #     两个面板**都已采到、流程都已写好**：
    #       · 机巧宝箱怪 ⇒ 共用 `buypanels.mimic_flow`（真机实测 ✓）
    #       · 传承祭坛   ⇒ `buypanels.shrine_flow`（面板已采 ✓）
    #     ⇒ 留着只会**误停脚本** ✗（正是用户这次要删它的原因 ✓）
    #   ⚠ 删掉之后，`机巧宝箱怪`/`传承祭坛` 的处置**全部交给 `popups()`**：
    #     点开面板 → `mimic_flow` / `shrine_flow` ✓
    # ⭐ 2026-09-25 起：地块分类器直接给出「已揭示格」的三分类，不再靠中心色采样：
    #   plain   = 已揭示的空地（草地）→ 可以点它揭一片（连通消除）
    #   content = 已揭示的内容格（木箱/宝箱/游乐设施/勇者之墓…）→ 点了拿东西/开面板
    #   buy     = 已揭示的旅行商人 / 黄金宝库 → **最高优先**（用户口径：要买完）
    #   未揭示格（暗）点不动，只能靠揭格推进
    # ⭐ 目标集合（用户 2026-09-25 定案，提高效率）：
    #   = **标记格（首领/大拇指/幸运草/红装） ∪ 旅行商人 ∪ 黄金宝库**
    #   ⇒ 其他已揭示内容格（木箱/宝箱/海螺/游乐设施/勇者之墓…）**一律不点**；
    #     也没有「已露出内容格」这个退图条件了 —— 目标清完立刻退图
    # ⭐⭐⭐ 2026-10-01 v0.96【宝库永不丢 · ①不许被"点过一次"钉死】
    #   用户口径（2026-09-25 起反复强调）：「**有黄金宝库你没点就要退**」、「能直接点就先点」。
    #   而 `done` 是「这一格处理过了」的**永久**集合：只要某次点击弹出了面板（哪怕宝库面板
    #   被自己的下一次点击关掉、或层数奖励没走完），这一格就永远不再被点 ⇒
    #   真机复盘（autoexplore_vaultskip.log 22:28~22:32）里那格**已揭示的黄金宝库**
    #   再也没人碰，机器人却满地图开路、把体力花在"拦路"战斗上 ✗
    #   ⇒ 只要**本帧**它还是"已揭示 + 强匹配的商人/宝库"，就把它从 `done` 里摘出来
    #     （真被买掉 ⇒ 本帧名字变空地/它不再进 buy ⇒ 自然不再摘 ✓ 不会重复点已消耗格 ✓）
    #
    # ⛔⛔⛔ 2026-10-02 修「买完商人后规划不知道它买完了，直接挡在那里」
    #   （用户：「宝库买完才会消失」⇒ 商人买完**不消失**，一直被重复点）
    #   真机日志实证（gui_20261002_152415.log / runs/loop/loop_log.json）：
    #       #13 {"merchant": "done", "bought": 4}      ← 4,7 买完了，进了 done ✓
    #       #19 {"solver": "ok", "order": ["4,7", …]} ← 同一轮，规划又排它
    #       #20 {"round": 2, "vault_unpin": 1}        ← ★「摘除」把它放回去了
    #   根因：摘除判据是「本帧还是不是商人/宝库」，而**买完那一帧分类器还认得出商人**
    #   （面板刚关、格子尚未变成草地）⇒ 被判成「还没买掉」⇒ 摘掉 ⇒ 下一轮又点 ✗✗
    #   （注释里原先写的「真被买掉 ⇒ 本帧名字变空地」——**实测不成立**）
    #   ⇒ 修法：**本轮刚买完的格一律不摘**（它就是「已买完」，不是「还没买」）：
    #     记录 `_just_bought`（本会话买完的商人/宝库格），摘除时跳过它们 ✓
    #   ⚠ 为什么商人买完不消失、宝库会消失：宝库是**整格替换**成新面板/空地，
    #     分类器立刻就变了；商人是**同格循环购买**（本局 4 轮），
    #     买完那一格仍是「旅行商人」美术 ⇒ 只有靠「买完记录」才知道它买过了 ✗
    _just_bought = st.setdefault('bought_done', set())
    _unpinned = 0
    _now_v_dbg = set()
    _dropped_dbg = set()
    try:
        _now_v_dbg = set(vault_px_now(c))
        for _p in _now_v_dbg:
            if _p in done and _p not in _just_bought:
                # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「那把规划**又忘了旅行商人购买完后
                #   不消失，不能解锁后面相邻那个格子**」⇒ 商人格买完**绝不放回** ✓
                #   真机现象（`gui_20261003_132733_acc2.log`）每轮都刷：
                #     「已揭示的宝库/商人 1 格『还没买掉』⇒ 从处理过里放回」
                #     ⇒ r3/r4/r5/r6 反复出现「商人/宝库 1」⇒ 一直不揭新格、空转 ✗
                #   原因：**商人格买完画面不变**（格子还在 ⇒ 判据以为"还没买" ⇒ 放回 ✗），
                #     而且它**不解锁相邻格**（用户明确说的）⇒ 放回它没有任何收益 ✗
                #   ⇒ 宝库**保留**放回（它有多轮奖励，放回是对的 ✓），
                #     商人**一律不放回**：记进 `merchant_done` 并继续 ✓
                try:
                    _rc_p = cell_of(_p[0], _p[1])
                    _nm_p = str(((c.get('st') or {}).get(_rc_p) or {}).get('name') or '')
                except Exception:               # noqa: BLE001
                    _rc_p, _nm_p = None, ''
                if '商人' in _nm_p:
                    st.setdefault('merchant_done', set()).add(tuple(_rc_p))
                    log.append({'merchant': 'bought_no_repin', 'cell': '%d,%d' % _rc_p,
                                'note': '商人格买完不消失 ⇒ 不放回（用户口径 ✓）'})
                    continue
                done.discard(_p)
                _unpinned += 1
                _dropped_dbg.add(_p)
    except Exception:       # noqa: BLE001
        pass
    # 买完的格若已被点掉（本帧已变草地/不再匹配），清掉记忆，避免集合无限增长
    # ⭐⭐⭐ 2026-10-02 抽成函数并修「买完又被放回」——**棋盘被面板挡住时绝不清** ✓
    #   （详见 `_prune_bought_done` 的 docstring：商人面板一开就看不见棋盘 ⇒
    #    原来会在买完的当下把记录删掉 ⇒ 下一轮把商人格"放回" ⇒ 面板又开一次 ✗）
    _pruned = _prune_bought_done(st, c)
    if _pruned:
        log.append({'bought_done_pruned': _pruned, 'kept': sorted(_just_bought)})
    if _unpinned:
        entry['vault_unpin'] = _unpinned
        # ⚠ 2026-10-02 加诊断：摘除时把「bought_done 内容」和「本帧商人格坐标」都记下来。
        #   真机 dbt 那把反复 `vault_unpin: 1` ⇒ bought_done 与这里对不上，
        #   但**光看日志猜不出来**（前两次都猜错了）⇒ 必须两边坐标同框对拍 ✓
        try:
            log.append({'unpin_dbg': {'kept_bought': sorted(_just_bought),
                                      'now_vendor': sorted(_now_v_dbg),
                                      'dropped': sorted(_dropped_dbg)}})
        except Exception:                   # noqa: BLE001
            pass
        say('       · 已揭示的宝库/商人 %d 格「还没买掉」⇒ 从"处理过"里放回（宝库永不拉黑 ✓）'
            % _unpinned)
    buy = [p for p in c['buy'] if p not in done]
    buy_hidden = [p for p in c.get('buy_hidden', []) if p not in done]   # 未揭示的商人/宝库
    # ⭐⭐⭐⭐ 2026-10-05 **金币 < 50 万 ⇒ 商人/宝库"也不规划"**（用户口径，原话）：
    #   「金币低于50万就自动不去购买商人和宝库（**也不规划**，就相当于拉黑了），
    #     高于50w就还是正常买」
    #   ⇒ 在这里就把它们**从 buy / buy_hidden 剔掉** —— 效果等于"拉黑"：
    #     · 不进 `pending_buy` ⇒ **不会排进计划**（不规划 ✓）
    #     · 不进 `buy_px` ⇒ 不受"永不拉黑"保护 ⇒ 后面的开路边打/冷却规则照常管它 ✓
    #     · 面板万一已经开着 ⇒ `popups()` 里那道闸门**只关不买** ✓（上面那条）
    #   ⚠ 读不到金币（None）⇒ **不剔**（照常买，保守 ✓）
    #   ⚠ 只剔**本帧新认到的**；`sticky` / `buy_seen` 是跨轮记忆 ⇒ 下面一并过滤 ✓
    _gold_ok = gold_enough_locked(st)
    if not _gold_ok and (buy or buy_hidden):
        _gold_cells = (['%d,%d' % cell_of(*p) for p in (list(buy) + list(buy_hidden))])
        log.append({'buy_blocked_low_gold': _gold_cells,
                    'gold': st.get('gold_locked'), 'min': GOLD_MIN_BUY,
                    'note': '金币不足 ⇒ 商人和宝库**不买也不规划**（= 拉黑 ✓ 用户口径）'})
        say('       · 金币 %s < %d ⇒ 商人/宝库 **不买也不规划**（%s）✓'
            % (st.get('gold_locked'), GOLD_MIN_BUY, '、'.join(_gold_cells)))
        buy = []
        buy_hidden = []
    # ⛔⛔⛔ 2026-10-24 **商人格买完就不该再进目标**（治「明明买完了还要去点一下」）
    #   ---- 病 ----
    #     `merchant_done` 这个集合**只写不读**：
    #       · 写：上面那段「商人格买完不消失 ⇒ 不放回」里 setdefault(...).add(...)
    #       · 读：**全仓零处**（grep 只有那一条写入 + 一条注释）
    #     ⇒ 写进去了，但**没有任何判据用它** ⇒ 对行为零影响（死集合）✗
    #   ---- 真机证据（`runs/acc2/loop/loop_log.json`，10-24 22:50）----
    #     #128 {"bought_rec":[168,908],"cell":"3,2"}   ← 买完记住
    #     #131 {"bought_done_pruned":1,"kept":[]}       ← 记忆被删（判据不同源，另一条 bug）
    #     ⇒ 两条路都让"买完"这件事失传 ⇒ 下一轮又把它当目标 ✗
    #   ---- 修 ----
    #     在 **buy 列表的汇聚点**按 `merchant_done` 过滤一次（与金币闸门同位置）
    #     ⚠ 只滤**商人**，不滤宝库：宝库有多轮奖励（放回是对的 ✓，用户口径）
    #     ⚠ merchant_done 存的是 **(row,col) 元组**，而 buy 是**像素** ⇒ 用 cell_of() 换算 ✓
    _mdone = st.get('merchant_done') or set()
    if _mdone and buy:
        _kept_buy = [p for p in buy if cell_of(*p) not in _mdone]
        _cut = len(buy) - len(_kept_buy)
        if _cut:
            log.append({'merchant': 'skip_bought', 'cut': _cut,
                        'cells': sorted('%d,%d' % rc for rc in _mdone),
                        'note': '商人**买完不消失** ⇒ 已买过的格不再进目标（别再点 ✗）'})
            say('       · 商人已买过 %d 格 ⇒ 不再排进目标（买完格子不消失，不重复点 ✓）' % _cut)
            buy = _kept_buy
    # ⚠ 2026-09-25 修（用户报「实例B第一张图明明还有一个未揭示的商人就退了」）：
    #   未揭示的商人/宝库**点不动**，绝对不能排进点击序列 —— 旧版把它当普通目标去点，
    #   点一次没反应就 cold+1，4 轮后被「放弃」规则踢掉 → 判成目标清完 → 退图漏掉它。
    #   现在它只当**开路目标**（沿出生地→它那条直线揭格把它解锁出来）；
    #   放弃条件改成「连续多轮棋盘毫无变化」（真的一点都推不动了才放弃）。
    board_sig = (len(c['gray']), len(c['light']))
    if buy_hidden:
        if st.get('h_sig') == board_sig:
            st['h_stall'] = st.get('h_stall', 0) + 1
        else:
            st['h_stall'] = 0
        st['h_sig'] = board_sig
        if st['h_stall'] >= 8 and st.get('clear_clicks', 0) >= 24:
            for p in list(buy_hidden):
                done.add(p)
                buy_hidden.remove(p)
                say('       · 未揭示的商人/宝库 (%d,%d)：连着 8 轮棋盘毫无变化且开路预算用尽，'
                    '放弃它' % p)
                status('宝库/商人 点不开 · 放弃这一格')
            st['h_stall'] = 0
    else:
        st['h_stall'] = 0
        st['h_sig'] = None
    nones_extra = [p for p in c['content'] if p not in done]     # 只用于日志/统计 + 开路
    # ⭐⭐⭐ 2026-10-01 用户口径：「勾选就主动去处理，不勾选就**拉黑**」
    #   ⇒ 拉黑格（弹窗类特殊地块里没勾选的）**不参与开路**（点一下必弹面板 ✗）
    #   实现：从"内容格"候选池里剔除 ⇒ 既不进 clearable、也不进 cands、也不算 road 的
    #   plain_road/比例 ✓（目标侧由 `targets_cfg.is_target` 管 ✓）
    try:
        _blk = _blocked_px(st, c)
        if _blk:
            _n0 = len(nones_extra)
            nones_extra = [p for p in nones_extra if p not in _blk]
            if len(nones_extra) != _n0:
                entry['blocked_skipped'] = _n0 - len(nones_extra)
                say('       · 拉黑不碰的地块 %d 个（未勾选：宝箱怪/预言石碑…✓）'
                    % (_n0 - len(nones_extra)))
    except Exception:       # noqa: BLE001
        pass
    nones = [p for p in c['plain'] if p not in done]
    if c.get('st'):
        # ⭐ 2026-09-26：board 日志加记 **sid 后缀** —— 名字不够用：「游乐设施」有
        #   202(绿)/311(蓝)/221(紫) 三个同名 ID ✗，复盘"紫橙数量对不对"必须看 ID ✓
        entry['board'] = {('%d,%d' % k): (str(v.get('sid') or '').split('_')[-1],
                                          v['name'], v['score'], v['ratio'])
                          for k, v in sorted(c['st'].items()) if v['anchor'] == k}
    grays = list(c['gray'])
    # ⭐ 用户 2026-09-25：「优化掉多余点击，比如说点击出生点」
    #   出生点(营地) 点了只弹一个没用面板、不消耗、不揭示 ⇒ 直接当"已完成"排除，
    #   省掉一次点击 + 一次面板判定（约 1.5 秒/图），也少一次 OCR
    if c.get('st'):
        # ⭐⭐⭐ 2026-10-02 认营地改走 `find_camp_cell()`（带兜底）——
        #   用户报「怎么规划没了」那帧，营地格被多格块吞了 ⇒ 老判据两条全挂
        #   ⇒ `st['spawn']` 为空 ⇒ 求解器开局可点集合为空 ⇒ `no_plan / exhausted`
        #   （完整证据链见 `find_camp_cell()` 的 docstring）
        _ck, _chow, _csc = find_camp_cell(c['st'], log, where='spawn')
        if _ck is not None:
            camp_px = marks_mod.cell_center(_ck[0], _ck[1])
            done.add(camp_px)
            st['spawn'] = camp_px
            st['camp'] = camp_px
            if _chow != 'exact':
                entry['spawn'] = {'cell': '%d,%d' % _ck, 'how': _chow,
                                  'score': round(_csc, 3)}
    if c['unknown']:
        entry['unknown_cells'] = len(c['unknown'])
    # ⭐⭐⭐⭐ 2026-10-05 **把"纯大拇指格"从标记里摘掉**（用户口径：
    #   「幸运草低于8…把大拇指目标都拉黑，**直接不去打了**」／「大于8就自动不拉黑去打」）
    #   ⚠ 必须**摘在去重/组目标之前**（否则它照样进 `marked` ⇒ 计划照样排它 ⇒ 还是去打 ✗）
    #   ⚠⚠ **只摘"纯大拇指"格**（`marks == ['recommend']`）——
    #      同一格**还有别的标记**时（真机常见 `['boss','recommend']`）**必须保留**：
    #        · `boss` 是**必打**目标（用户口径「boss 必打」），跟幸运草无关
    #        · 打它照样该打；只是**打完别摇色子**（`handle_dice` 那道闸门管着 ✓）
    #      我第一版把 `['boss','recommend']` 也整格剔了 ⇒ **会漏打首领** ✗✗
    #   ⚠ 判据用 `st['clover_block']`（轮首按**锁定值**算好）—— 那一步在 `mk` 之前，
    #     只能用"该不该拉黑"这个**意图**；**真正的剔除必须在这里**（本帧 `mk` 才刚扫出来 ✓）
    try:
        if st.get('clover_block'):
            _removed = []
            for _rc in list(mk):
                _mks = list((mk[_rc] or {}).get('marks') or [])
                if _mks == ['recommend']:        # ⚠ **纯大拇指**才摘（含 boss 的保留 ✓）
                    _removed.append('%d,%d' % _rc)
                    del mk[_rc]
            if _removed:
                entry['recommend_blocked'] = _removed
                if not st.get('clover_block_logged'):
                    st['clover_block_logged'] = True
                    log.append({'recommend_blocked_low_clover': len(_removed),
                                'clover': st.get('clover_locked'),
                                'min': CLOVER_MIN_REROLL,
                                'cells': _removed,
                                'note': '幸运草不足 ⇒ **纯大拇指格**拉黑不去打（用户口径 ✓）；'
                                        '带首领的格子**保留**（boss 必打，只是不摇色子 ✓）；'
                                        '幸运草够时自动放回（下一张图重扫 ✓）'})
                    say('       · 幸运草 %s < %d ⇒ 纯大拇指格**拉黑不去打**（%s）✓'
                        % (st.get('clover_locked'), CLOVER_MIN_REROLL,
                           '、'.join(_removed)))
    except Exception:       # noqa: BLE001
        pass
    # ⭐ 2026-09-27：标记格也按**锚点**去重（多格大块的成员格会各报一次 ✓ 去重后只点一次 ✓）
    try:
        _mk_dedup, _by_anchor = [], {}
        for (r0, c0) in sorted(mk):
            _v0 = (c['st'].get((r0, c0)) or {}) if c.get('st') else {}
            _a0 = tuple(_v0.get('anchor') or (r0, c0))
            _n0 = len(mk[(r0, c0)] or [])
            if _a0 not in _by_anchor or _n0 > _by_anchor[_a0][1]:
                _by_anchor[_a0] = ((r0, c0), _n0)
        _mk_dedup = [v[0] for v in _by_anchor.values()]
        if len(_mk_dedup) < len(mk):
            entry['marks_dedup'] = '%d→%d' % (len(mk), len(_mk_dedup))
        mk = {k: mk[k] for k in _mk_dedup}
    except Exception:       # noqa: BLE001
        pass
    marked = [marks_mod.cell_center(r, cc) for (r, cc) in sorted(mk)]
    # ⭐⭐ 2026-09-26 用户需求（原话）：
    #   「如果探索格子有空闲的就要找这种格子点探索来填满；如果探索格子被填满就不需要找」
    #   这种格子 = 紫/橙探索地块（ID 后缀 221/321/331 ✓ 小助手官方分类 ✓）
    # ⭐ 判据 = 地块 **ID 后缀** ∈ {221,321,331}（紫/橙探索地块 ✓，小助手官方分类 ✓）
    #   ⚠ 不能按名字筛 ✗：「游乐设施」有 202(绿)/311(蓝)/221(紫) 多个 ID ✓
    try:
        _ap = set(spots_mod.EXPLORE_SUFFIX)
    except Exception:       # noqa: BLE001
        _ap = {'221', '321', '331'}
    # ⭐⭐⭐⭐ 2026-10-03 用户口径（原话）：
    #   「**领取流程应该只在进图那次扫描触发**，而且触发不应该检测到已完成才触发吗，
    #     为什么刚派遣还是倒计时的时候也回触发？**」✓
    #   ⇒ ① **每张图只跑一次**（用 `st['claim_checked']` 标记 ✓；`st` 是**每图一份** ✓）
    #        原来每轮都跑 ✗ ⇒ 图中间（刚派遣/战斗结算/面板堆叠）也会插进来 ✗
    #        ⇒ 撞上面板就乱点、卡在"获得奖励"界面 ✗✗
    #     ② 触发条件**本来就是**"模板命中「已完成」"✓（不是无条件触发 ✓）——
    #        你看到"刚派遣也触发"，是因为**另一个槽真的已完成** ✓
    #        （日志里领的一直是 x=159=槽1 ✓，而刚派遣的紫探索在别的槽 ✓）
    #     ③ 阈值钉 **0.9**（见下面 `fx_at` 处 ✓）
    #   ⇒ ④ 试过"用底部导航栏判断有没有面板"⇒ **不成立** ✗（实测：结算/奖励面板盖上来时
    #        `nav_dex` **仍然可见** ✓ —— 游戏把底部导航画在面板之上 ✗）
    #        ⇒ 这条闸已撤 ✓ 下次要用**压暗/棋盘被挡**那条现成信号（`dim` / `board_hidden` ✓）
    if (EXPLORE_DISPATCH and _ap and c.get('st')
            and not st.get('claim_checked')):
        # ⭐⭐⭐⭐ 2026-10-04 **本质修法**（用户口径：「**要从本质入手，别做加法**」✓）
        #   根因（不是模板不准 ✗）：`fx_at` 判的是 `b.img()` = **"当前帧"**，
        #     而"一进图"时当前帧**很可能还是进图前那一屏**（选图界面 / 上一张图 ✓）——
        #     那一屏的槽位**真的**写着「已完成」✓ ⇒ 于是每张图一进图就用**旧画面**
        #     判到"已完成"⇒ 白领一遍 ✗✗
        #   真机证据：`gui_20261004_031634.log` 第 9/10/11 张图**连着**在 (237,627) 命中 ✗，
        #     而那几张的 `r_*_0.png` 上该槽位最高只有 **0.37** ✗（根本不是那张帧判的 ✓）
        #   ⇒ 修：**判之前先强制抓一张新帧** ✓（`b.snap` 会 +1 `_snap_n` ⇒ 同帧缓存自动失效 ✓）
        #   ⚡ 开销**实测 17ms**（本机 `b.snap(save=False)` ×3 取均值 ✓）
        #      ⇒ 地图平均 ~31s ⇒ **0.05%** ✓ 可忽略（比一次 OCR 便宜 ~200 倍 ✓）
        #      ⇒ 想再省也行：把这步挪到"本轮已抓的那张帧"上（零额外截图 ✓）
        #        但 0.05% 不值得为它动结构 ✓（用户口径：能省就省，但不是这么省的 ✓）
        try:
            b.snap('claim_check', save=False)
        except Exception:           # noqa: BLE001
            pass
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**槽位里有个已完成，点击已完成就能领取**」
        #   ⇒ 轮首先**自动领取**已完成的探索小队 ✓（专项实测通过：点 (315,627) ⇒
        #     「已完成」消失 ✓，见 `_verify/slot_before_20261003.png` / `slot_after_20261003.png`）
        #   ⚠ 为什么必须专门做：「已完成」这三个字**正常 OCR 读不到** ✗
        #     （真机实测必须**放大 4 倍**才认得出，置信 0.99 ✓）
        #     ⇒ 它既不算「空闲」、也数不到倒计时 ⇒ `explore_slots_free` 以为"还有空位" ✗
        #       ⇒ 于是**反复点「探索 → 派遣」**而游戏不受理（待领取的槽派不进去 ✗）✗✗
        #   ⇒ 用模板快查（`slot_done`，~7ms ✓ 比 OCR 便宜 ~17 倍）命中即点它领取 ✓
        #     领完那个槽下一轮就是「空闲」⇒ 正常走"探索 → 派遣" ✓
        try:
            st['claim_checked'] = True      # ⭐ 本图已检查过领取（每图一次 ✓，见上方口径 ✓）
            # ⭐⭐ 阈值 **0.9**：真机量化（`_tmpman/measure_slot_tpl.py`）——
            #   真「已完成」= **1.000** ✓；空闲 / 倒计时 / 各首帧一律 **≤ 0.35** ✓
            #   ⇒ 判别边界极大 ⇒ 0.9 既不漏、也绝不可能假触发 ✓
            # ⭐⭐⭐ 2026-10-04 用户两条反馈（**关键**）：
            #   ①「**第一次确实槽位3是已完成，但是你领取的不是槽位3**」✗ ⇒ 点错位置
            #   ②「**刚刚三个槽位都没有完成，还是领取了**」✗ ⇒ 假命中
            #   ⇒ ① 搜索**限制在槽位条内**（x 110~380 ✓）——
            #        原来 `band` 是**整行**（y585~670, x 全宽 ✗）⇒ 槽位条以外的画面
            #        也可能命中 ⇒ 假命中来源之一 ✓
            #   ⇒ ② 命中时**落盘取证**（连位置一起 ✓）⇒ 下次复现就有铁证 ✓
            #        （不猜根因 ✗ 先拿证据 ✓ —— 本项目一贯做法 ✓）
            # ⛔⛔ 2026-10-19 **框扩到全部 4 个槽**（真机事故）
            #   用户报：「进图不领已完成探索」
            #   ---- 两层根因（都实测过）----
            #     ① **模板尺寸错**：旧 `slot_done.png` 是 **76×24**，而真机
            #        「已完成」实际只有 **约 51×17**（绿字，实测
            #        x 212~263 / y 619~636）⇒ 旧模板全量 140 帧最高只 **0.8169**
            #        （门槛 0.9）⇒ **永远不命中** ⇒ 领取代码一次都没跑过 ✗✗
            #        （已重裁 55×21，实测分离度 1.0000 vs 0.2631 ✓）
            #     ② **框太窄**：旧框 `x1=380` 只覆盖槽2/槽3，
            #        槽4 的「已完成」在 **x≈456~570** ⇒ 完全在框外 ✗
            #   ⇒ 新框 x 40~600 / y 600~660（覆盖全部 4 槽，上下各留余量）
            #   ⚠ `fixed.find` 只返回第一个命中 ⇒ 每图仍只领 1 个（既有行为 ✓）
            _SLOT_BOX = (40, 600, 600, 660)      # ← 覆盖全部 4 个槽 ✓
            #   ⚠ API 口径：`fx_at(b, name, band=键)` 的 `band` 是 **`fixed.BANDS` 的键**
            #     （不是坐标 ✗）；想按坐标框找 ⇒ 直接用 `fixed.find(img, name, box=…)` ✓
            _sd = None
            try:
                import fixed as _FXs
                _r0 = _FXs.find(b.img(), 'slot_done', box=_SLOT_BOX, min_conf=0.9)
                if _r0:
                    _sd = (int(_r0[0]), int(_r0[1]))
                    # ⭐ 取证落盘：命中即存整帧（下次复现就有铁证 ✓ 不猜根因 ✗）
                    try:
                        _p = os.path.join(RUNS, (st.get('tag') or ''), 'bagdbg',
                                          'claim_hit_%s.png' % time.strftime('%H%M%S'))
                        os.makedirs(os.path.dirname(_p), exist_ok=True)
                        ok_e, _be = cv2.imencode('.png', b.img())
                        _be.tofile(_p)
                        log.append({'explore': 'claim_shot', 'at': _sd,
                                    'file': os.path.basename(_p),
                                    'note': '命中「已完成」的取证帧（含位置 ✓）'})
                    except Exception:       # noqa: BLE001
                        pass
            except Exception:               # noqa: BLE001
                _sd = None
            if _sd:
                b.tap(_sd[0], _sd[1], wait=1.5)
                log.append({'explore': 'claim_done', 'at': (_sd[0], _sd[1]),
                            'note': '槽位「已完成」⇒ 点击领取（用户口径 ✓）'})
                say('       · 探索槽有「已完成」⇒ 点 (%d,%d) 领取 ✓' % (_sd[0], _sd[1]))
                # ⭐ 点完槽位会弹「探索小队结算」弹窗（用户：「点击已完成会出现个弹窗」✓）
                #   实测真机（`_verify/claim_popup_20261003.png`）：
                #     标题 = 小队名（巨大沙堡 361,320）｜ 探索时间 08:00:00 (107~208,652)
                #     ｜ 产出 ｜ **「领取」按钮 (582,757)** bbox=(552,740)-(611,775) 置信 1.00 ✓
                # ⭐⭐ 2026-10-03 用户口径（原话）：「**已完成和领取时间间隔 1s，
                #   领取和后面的返回间隔 3s**」⇒ 间隔照这个来 ✓
                #   （领取后会弹「恭喜获得」奖励面板 ✓ 实测 `_verify/claim_after_20261003.png`）
                time.sleep(1.0)                      # 已完成 → 领取 = 1s ✓
                # ⛔⛔⛔ 2026-10-10 **必修：这里漏了 `b.snap()`**（用户报
                #   「**为什么无法正常领取已完成探索**」，acc3 三次连续失败 ✓）
                #   ---- 病 ----
                #     `b.ocr()` 在 PC 上读的是 **`b.img()` = 上一次 `snap()` 的缓存帧**，
                #     **它不会自己重抓** ✗；而 `b.tap()` **也不抓帧**
                #     （实测 `mapbot.Bot.tap` 源码里 `snap` 出现 **0 次** ✓）。
                #     ⇒ 上面那下 `b.tap(_sd…)` 点了「已完成」，可**缓存帧还是点击之前那张**
                #       （纯棋盘，**根本没有「领取」按钮**）⇒ 下面这句 OCR 必然读不到 ✗✗
                #   ---- 铁证（取证帧 + 真人可读）----
                #     `runs/bagdbg/back_miss_175259.png`（= 失败时 `b.img()` 落盘的那帧）
                #     上「领取」**清清楚楚在 (582,758)**，我用生产口径 `band=(700,800)`
                #     离线跑同一帧 ⇒ **`(582,758) 领取 conf=1.00`** ✓
                #     ⇒ **判据没问题、坐标没问题、那一帧也没问题** —— 唯一的问题就是
                #       "当时读的不是那一帧" ✓
                #   ---- 为什么只错这一处 ----
                #     同一个坑**本项目第 4 例**（前 3 例：`start_fight` docstring /
                #     `_tap_verified` / `claim_back_poll`）—— 那三处都修了，
                #     **这处漏了** ✗（`claim_back_poll` 的 docstring 里甚至写着
                #     「凡是"轮询看画面有没有变"的循环，每轮都必须先 `b.snap()`」✓）
                #   ⚡ 代价：一次 `snap` 实测 ~17ms / 极速通道更少 ⇒ 可忽略 ✓
                try:
                    b.snap('claim_popup', save=False)
                except Exception:           # noqa: BLE001
                    pass
                try:
                    _rb = None
                    _ri = b.ocr(band=(700, 800), tag='claim_btn')
                    for _it in (_ri or []):
                        if '领取' in (_it.get('text') or ''):
                            _rb = (_it['cx'], _it['cy'])
                            break
                    if _rb is None:
                        # ⛔⛔ 2026-10-03 用户报（原话）：「**派遣完紫探索后直接触发领取，
                        #   结果卡在获得奖励界面**」⇒ 根因就是**无脑兜底** ✗
                        #   原来这里 `_rb = (582,757)` **硬点** ✗ ⇒ 面板根本不在时点到别处
                        #   ⇒ 越点越乱、卡死 ✗✗（真机日志：`返回` 连续 4 次都走"标定兜底" ✗）
                        #   ⇒ 改：**找不到「领取」就什么都不点** ✓（放弃这次，下一轮再看 ✓）
                        log.append({'explore': 'claim_btn_missing',
                                    'note': '弹窗里没读到「领取」⇒ 不盲点、放弃这次领取 ✓'})
                        say('       · 没读到「领取」⇒ **不盲点坐标**、放弃这次领取（下一轮再看）✓')
                    if _rb is not None:
                        b.tap(_rb[0], _rb[1], wait=1.5)
                        log.append({'explore': 'claim_popup_ok', 'at': _rb})
                        say('       · 探索结算弹窗 ⇒ 点「领取」(%d,%d) ✓' % _rb)
                except Exception:       # noqa: BLE001
                    pass
                # ⭐⭐⭐ 2026-10-04：这段**提取成了模块级函数 `claim_back_poll()`** ——
                #   它踩过"轮询里漏 `b.snap()` ⇒ 几轮读同一张旧帧 ⇒ 永远读不到「返回」"
                #   的真机坑（用户原话「**领取后还是没点返回**，卡在返回界面」），
                #   提出来才能被 `verify_claim_back.py` **直接驱动**做回归 ✓
                #   （完整根因 + 实测数字都写在该函数的 docstring 里 ✓）
                claim_back_poll(b, log, st)
        except Exception:       # noqa: BLE001
            pass
        # ⭐⭐ 空闲探索槽（2026-09-30 改口径，见文件上方 `explore_slots_free` 那段）：
        #   **只认正面证据「空闲」**；认不到 ⇒ 不下结论（保留 old / None）。
        #   ⚠ 旧版「总槽数 - 倒计时个数」反推法已**废除**（真机实证会假空闲 ⇒ 死循环 ✗）：
        #     · 那台机器 HUD 是 **4 个槽**（角标 1/2/3/4），`TOTAL=3` 反推本身就不成立
        #     · 倒计时还会被 OCR 吃掉一个冒号（`04:24:31` → `04:24831`）⇒ 少算一个"占用"
        #   轮首已经刷过一次（同一份 items）⇒ 这里只补落日志用的 entry 字段 ✓
        _sf_here, _si_here = explore_slots_free(items)
        _free_txt = _si_here['free_txt']
        _busy = _si_here['busy']
        if _sf_here is not None:
            _slots_free = _sf_here
            _saw_row = True
        else:
            _slots_free = int(st.get('slots_free', 1) or 0)     # 认不到 ⇒ 保留旧值
            _saw_row = False
        entry['slots_free'] = _slots_free      # ⭐ 空闲探索槽个数（0 = 已填满 ✓）
        entry['slots_busy'] = _busy
        entry['slots_busy_strict'] = _si_here['busy_strict']
        if _saw_row:
            st['slots_free'] = _slots_free
        # ⭐ 2026-09-26 用户要求：**不管满没满，紫橙格都是目标** ✓
        #   有空闲 ⇒ 点探索+派遣 ✓；满了 ⇒ 点战斗 ✓（都在 popups 里分流 ✓）
        if True:
            # ⭐⭐ 2026-09-26 修正：紫/橙格**按大块去重**，一个大块只给一个点击目标 ✓
            #   旧逻辑逐格看 sid ⇒ 一个 2×3 的 221 大块会产出 5~6 个目标，
            #   而点哪一格弹的都是**同一块的面板** ⇒ 重复弹面板 + 白点（用户发现）
            #   `Board.state()` 已经把成员格归属修正过了（同一大块 ⇒ 同一个 anchor、
            #   同一个 sid）⇒ 这里只要**按 anchor 归并**、每块挑一个还没点的格 ✓
            _ev_blocks = {}                 # anchor -> [成员格...]
            _seen_anchor = set()      # ⭐ 按锚点去重（一个大块只留一个目标 ✓）
            for _k, _v in sorted(c['st'].items()):
                _sid = str(_v.get('sid') or '')
                _suf = _sid.split('_')[-1] if '_' in _sid else ''
                _anc = tuple(_v.get('anchor') or _k)
                if _anc in _seen_anchor:
                    continue             # 同块成员格 ⇒ 跳过 ✓
                _seen_anchor.add(_anc)
                if _suf not in _ap:
                    continue
                # ⛔⛔⛔ 2026-10-02 修「盘上还有紫金格却写没目标」（用户报）
                #   现象：真机帧 runs/r_162357_0.png，左上角那个**跨 8 格的紫金大城堡**
                #   （S00003_321 巨大沙堡，带金旗）**明明白白在图上**，
                #   但 `block_score` 只有 **0.575** ⇒ 被下面那个 0.70 门槛全跳过
                #   ⇒ 紫金格不进目标 ⇒ 写「目标已清完」⇒ 直接退图 ✗✗
                #
                #   为什么不能用固定阈值：0.70 是从**某一帧**（9-28 findA3，真块 0.794）
                #   量出来的**单点值**，当成了通用门槛。实测同一张图的分布：
                #       真·紫金大块（8 格连成一片）= 0.575
                #       而 0.21/0.30 那种是**单格瞎猜**（碎片、无关联）
                #   ⇒ 区分点不在**绝对分**，而在**「多格连成一片」这个结构证据** ✓
                #
                #   修法（两条，取「或」）：
                #     ① 绝对分 ≥ 0.70（老口径，认得准的单格/小块照旧）
                #     ② ⭐ **同 sid 的成员格 ≥ 3 个且 footprint 连成一片**
                #        ⇒ 说明分类器对**这一整块**都认出了同一个 sid，
                #          噪声不可能在 5+ 格上同时一致 ⇒ 无论单格分多低都该认 ✓
                _sc = float(_v.get('block_score') or _v.get('score') or 0)
                if _sc < 0.70:
                    _same_sid = sum(
                        1 for _k2, _v2 in c['st'].items()
                        if str(_v2.get('sid') or '') == _sid
                        and tuple(_v2.get('anchor') or _k2) == _anc)
                    # ⭐ 同一大块 ≥3 格 ⇒ 结构证据成立（哪怕单格分只有 0.5x）
                    if _same_sid < 3:
                        continue
                _ev_blocks.setdefault(_v.get('anchor') or _k, []).append(_k)
            _ev_cells = []
            for _ak, _members in sorted(_ev_blocks.items()):
                # 优先点锚点；锚点已经点过了就退而选同块里其它没点过的成员 ✓
                _want = [k for k in [_ak] + _members
                         if marks_mod.cell_center(*k) not in done]
                if _want:
                    _ev_cells.append(_want[0])   # ⭐ 每块只出一个目标
            # ⭐ 用户口径：**有空闲槽时这些是必须清完的目标** ✓（含雾格 ⇒ 会开路去揭示 ✓）
            #   没有空闲槽时就不管它们 ✓（上面已经 return/记 full 了）
            if _ev_cells:
                _ev_px = [marks_mod.cell_center(r, cc) for (r, cc) in _ev_cells]
                marked = list(dict.fromkeys(marked + _ev_px))
                entry['event_tiles'] = ['%d,%d' % k for k in _ev_cells]
                st['ev_tiles'] = list(entry['event_tiles'])
                say('       · 发现 %d 块紫/橙探索地块（%d 个成员格 %s）⇒ %s（空闲槽 %d 个）'
                    % (len(_ev_cells), sum(len(v) for v in _ev_blocks.values()),
                       '/'.join(sorted(_ap)),
                       '去探索+派遣' if _slots_free > 0 else '探索槽已满 ⇒ 改战斗',
                       _slots_free))
                status('发现紫金地块 · %s' % ('去派小队' if _slots_free > 0 else '槽满，改开打'))
        else:
            entry['event_slots'] = 'full'
    marked = [p for p in marked if p not in done]
    need = [p for p in marked if cold.get(p, 0) >= 1]
    fresh = [p for p in marked if cold.get(p, 0) == 0]
    sig = (len(grays), len(nones))
    st['stall'] = (st.get('stall', 0) + 1 if st['sig'] == sig else 0) if need else 0
    st['sig'] = sig
    # 拦路格判定（用户 09-25）：**只要场上还有未处理的标记格**，普通战斗格就可能是
    # 「去 boss 路上的拦路格」，要打掉（上限由 popups 里的 clear_fights<3 控制）。
    # ⚠ 旧版要「打标记格失败」才知道被挡路 -> 表现成「遇到拦路格直接关掉不打」。
    st['force_fight'] = bool(marked) or st.get('clear')
    if st.get('clear_fights', 0) >= 3:
        st['force_fight'] = False
    entry['order'] = {'none': len(nones), 'gray': len(grays), 'marked': len(marked),
                      'fogged': len(need), 'force': st['force_fight'],
                      'content(unused)': len(nones_extra), 'buy': len(buy),
                      'buy_hidden': len(buy_hidden)}
    if not marked and not buy and not buy_hidden:
        # ⚠⚠⚠ 2026-10-02 修**自相矛盾的日志**（用户报「没有目标了为什么还要开路探图？」）
        #   原来这里无条件打印「没有目标了，准备退图」，而别处又打印
        #   「盘上暂无可见目标（还剩 N 格雾）⇒ 先揭几格开路探图」⇒ 两句矛盾同时刷出。
        #   ⚠ 更糟：那句「开路探图」是**死代码**（在 `return 'done'` 之后，永远到不了），
        #     当时为了盖「识别层坏 ⇒ 目标认不出」而加的探图闸门，识别修好后
        #     已被用户口径否定（见 6700 行那段长注释）⇒ 一并清掉。
        #   ⇒ 现在口径单一：**没有标记格 + 没有商人/宝库 ⇒ 这张图收工**，
        #     不再为了揭开全部雾格继续烧体力 ✓
        # ⭐⭐⭐ 2026-10-03 用户报「为什么会有这些提示，**我觉得有规划就够了**」——
        #   这条原来是"⇒ 本图收工"，但退图判定已挪到**点击循环之后**（见文件末尾）⇒
        #   标记清空**不再等于**这一轮就退（计划还有步就继续走）⇒ 原措辞"说了却不做" ✗
        #   ⇒ 改成以**计划**为准：还有剩余步就明说"继续按计划走"，剩余步为 0 才说收工 ✓
        _pl_left_msg = 0
        _pl_ok_msg = 0
        try:
            for _p2 in (st.get('plan') or []):
                if marks_mod.cell_center(_p2[0], _p2[1]) in done:
                    continue
                _pl_left_msg += 1
                # ⭐ 2026-10-03：区分「现在可点」与「现在是雾（点不动）」
                #   用户报「明明计划里没步数了」—— 因为原来只数"不在 done 里的格"，
                #   而雾格点多少次都不会进 done ⇒ 每轮都重复报"还剩 N 步" ✗（听着像卡死）
                _rr2 = ((c.get('st') or {}).get(tuple(_p2)) or {}).get('ratio')
                try:
                    if _rr2 is None or float(_rr2) >= REVEAL_RATIO_MIN:
                        _pl_ok_msg += 1
                except (TypeError, ValueError):
                    _pl_ok_msg += 1
        except Exception:                   # noqa: BLE001
            _pl_left_msg = _pl_ok_msg = 0
        if _pl_ok_msg:
            say('  [r%d] 目标标记已清，计划还剩 %d 步（其中 **%d 步现在可点**）⇒ 继续按计划走'
                % (rnd, _pl_left_msg, _pl_ok_msg))
        elif _pl_left_msg:
            say('  [r%d] 目标标记已清；计划剩 %d 步但**现在都点不动**（雾格）⇒ 本轮空转，'
                '等下轮再判' % (rnd, _pl_left_msg))
        else:
            say('  [r%d] 目标已清完、计划也走完（标记格 0 / 商人宝库 0，还剩 %d 格雾未揭）'
                '⇒ 本图收工' % (rnd, len(grays)))
    else:
        say('  [r%d] 标记格 %d（含点不动的 %d）| 商人/宝库 %d（未揭示 %d）| 已揭示 %d / 暗格 %d'
            % (rnd, len(marked), len(need), len(buy), len(buy_hidden),
               len(nones) + len(nones_extra), len(grays)))

    def dist(p):
        src = need or marked
        if not src:
            return 0
        return min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in src)

    nones = sorted(nones, key=dist)
    # 退图规则（用户 2026-09-25 定案）：**只有标记格 + 商人/宝库是目标**
    #   目标都处理完 → 立刻结束冒险；不为「已露出的内容格」多跑一趟、更不乱揭格
    # ⚠ 2026-09-25 修：`pending_buy` 必须**把「未揭示的商人/宝库」也算进去**
    #   —— 否则「已识别到但还没解锁」的宝库会被当成"目标清完"直接退图
    #   （用户报「第三张图未揭示的宝库还有一个没买就退地图了」：日志 r4 显示「未揭示 1」却 done）
    # ⭐⭐⭐ 2026-10-01 用户报「盘上有宝库但没识别到就退了」+「我是在地图里直接启动脚本、
    #   boss 关已经打过」⇒ 根因：**中途接手时那一帧常被残留面板/结算动画盖住**
    #   ⇒ `board_state` 整盘读成暗格 ⇒ `buy_hidden` 空 ⇒ 判「没有目标了」直接退图 ✗
    #   而稍后（我抓帧时）同一张图宝库分数 **0.974** —— 说明**识别没问题，是"那一帧没看见"**。
    #   ⇒ 加一份 **跨轮持久的宝库/商人记忆 `st['buy_seen']`**：
    #     · 任何一轮认到（≥ `BUY_MEMORY_MIN`）就记下，**本图内不再遗忘** ✓
    #     · 它只影响"要不要退图"：**别在还可能漏着宝库时就退图** ✓
    #     · 真的被买掉/消耗掉 ⇒ 本帧 board 里那格不再是宝库 ⇒ 自然从记忆里移除 ✓
    #     · 上限 `BUY_MEMORY_MAX_ROUNDS` 轮防死锁（一直点不开也不至于卡死 ✓）
    BUY_MEMORY_MIN = 0.60          # 比 0.85 低：宁可疑心，也别漏（漏了用户就得手动补 ✗）
    try:
        _seen = st.setdefault('buy_seen', {})
        _cells_now2 = (c.get('st') or {})
        for _k, _v in _cells_now2.items():
            _nm2 = str(_v.get('name') or '')
            _sc2 = float(_v.get('score') or 0)
            if _nm2 in spots_mod.BUY_OUT_NAMES and _sc2 >= BUY_MEMORY_MIN:
                _px = marks_mod.cell_center(*_k)
                _seen[_px] = st.get('_rnd', 0) + 1
        # 本帧还有没有它（已买掉 ⇒ 分类结果会变成别的名字/空地）
        _alive = set()
        for _k, _v in _cells_now2.items():
            if str(_v.get('name') or '') in spots_mod.BUY_OUT_NAMES:
                _alive.add(marks_mod.cell_center(*_k))
        # ⭐ 已揭示的格**名字变了**（= 已被买掉/消耗）⇒ 立刻从记忆里删 ✓
        for _k, _v in _cells_now2.items():
            if bool(_v.get('revealed')) and str(_v.get('name') or '') \
                    and str(_v.get('name') or '') not in spots_mod.BUY_OUT_NAMES:
                _seen.pop(marks_mod.cell_center(*_k), None)
        for _p in [q for q in list(_seen)
                   if q not in _alive and _seen[q] and
                   (st.get('_rnd', 0) + 1 - _seen[q]) > 4]:
            _seen.pop(_p, None)       # 4 轮都没再出现 ⇒ 真的没了 ✓（防死锁）
    except Exception:       # noqa: BLE001
        pass

    # ⚠ 2026-09-25 又修（用户报「漏了已经揭示的黄金宝库」）：
    #   **已揭示的商人/宝库不做 cold 过滤**（和标记格一样永不排除），否则点两次没开面板
    #   就被踢出 pending_buy → 判成「目标清完」直接退图，宝库白漏。
    #   未揭示的**不加 cold 过滤**（它压根不该被点，见上面 board_sig 那段）。
    # ⭐⭐⭐ 2026-09-30【粘性商人/宝库目标】（模拟器 10:31 实锤，用户报「宝库没正常购买」）：
    #   宝库暗格揭示后匹配分会**抖动**（0.978 → 0.822，暗罩/角度让 NCC 掉分），
    #   一旦低于 0.85 强匹配线就从 buy_hidden 掉出 ⇒ pending_buy 变空 ⇒
    #   「目标清完」直接退图，宝库没买（统计「买完 0 个」）。
    #   ⇒ 一旦识别为商人/宝库（≥0.80）就进 **st['buy_sticky'] 粘性集合**，持续算 pending；
    #     排除条件只有一个：本轮 board 里该格已不再是宝库/商人（= 已买完消耗/消失）。
    #     另设 20 轮上限防死锁（一直点不开的宝库到上限就放弃，deadline 兜底退图）。
    sticky = st.setdefault('buy_sticky', {})
    _buy_now = {}
    for _p in (list(buy) + list(buy_hidden)):
        _buy_now[_p] = True
        sticky[_p] = sticky.get(_p, 0) + 1
    _still_buy = vault_still_there(st)
    # ⚠⚠ 2026-10-01 v0.96：上面这行原来写成 `(st['cells'] or {}).get('board')` ——
    #   而 `st['cells']` 是**分类器原样 dict**（键 `(r,c)` 元组，没有 `board` 键）
    #   ⇒ `_still_buy` **恒为空** ⇒ 下面「已消耗就剔出粘性集」这条**是死代码** ✗
    #   后果（真机 autoexplore_vaultskip.log 22:28~22:32 实测）：粘性集里那个宝库挂满 20 轮，
    #   每轮 `pending_buy` 都非空 ⇒ **永远「还剩 1 个目标」**，而本帧又认不到它
    #   ⇒ 机器人满地图开路、把体力花在"拦路"战斗上（用户报「能直接点的黄金宝库不去点，
    #     却去打了两个战斗地块」就是这个）✗
    for _p in [q for q in list(sticky)
               if q not in _buy_now and q not in _still_buy]:
        sticky.pop(_p, None)          # 已消耗/消失 ⇒ 从粘性集移除 ✓
    for _p in [q for q in list(sticky) if sticky[q] > 20]:
        sticky.pop(_p, None)          # 20 轮都点不开 ⇒ 放弃这个目标（防死锁）
        log.append({'buy_sticky_giveup': _p})
    # ⭐⭐⭐ 2026-10-01 v0.96【宝库永不丢 · ②强匹配但被判"未揭示"的也要去点一下】
    #   `revealed` 是 ratio 判据（格亮度/命中模板亮度）⇒ **换模板/换贴图帧就会抖动**，
    #   真机实测：NCC 0.95+ 的已揭示宝库被判 ratio 0.638 = "未揭示" ⇒ 既不进 buy、
    #   又被当"点不动"⇒ 机器人看着宝库去开路打拦路 ✗（用户报的就是这个）
    #   ⇒ 强匹配(NCC≥0.85) + 名字是宝库/商人 ⇒ **验证式点它**（每格上限 BUY_PROBE_MAX 次）
    # ⛔⛔ 2026-10-03 用户口径（原话）：「**也不要去额外点宝库了，严格走计划**」✗
    #   ⇒ **关掉"强匹配但未揭示 ⇒ 也去点一下"这条**（原来是"不丢宝库"的验证式点击 ✗）
    #     · 现在：雾里的宝库/商人**一律不点** ⇒ 只按规划走 ✓（用户口径 ✓）
    #     · 想恢复旧行为：把 `VAULT_PROBE` 改成 True ✓
    VAULT_PROBE = False
    _probe_px = set()
    if VAULT_PROBE:
        try:
            _probe_px = set(vault_probe_px(c, st))
            _add = [p for p in _probe_px if p not in buy]
            if _add:
                buy = list(buy) + _add
                entry['buy_probe'] = ['%d,%d' % cell_of(*p) for p in _add]
                log.append({'buy_probe': ['%d,%d' % cell_of(*p) for p in _add]})
                say('       · 宝库/商人 %s 被判"未揭示"但强匹配 ⇒ 也去点一下（不丢宝库 ✓）'
                    % '、'.join('%d,%d' % cell_of(*p) for p in _add))
        except Exception:       # noqa: BLE001
            pass
    pending_buy = list(buy) + list(buy_hidden) +         [q for q in sticky if q not in _buy_now]
    # ⭐⭐⭐ 2026-10-01：把**跨轮记忆**里的宝库/商人也算进 pending ⇒ 这一帧被面板盖住
    #   也不会误判「没有目标了」直接退图（用户报的「盘上有宝库却没识别到就退了」✗）
    try:
        _mem = st.get('buy_seen') or {}
        for _p in _mem:
            if _p not in pending_buy:
                pending_buy.append(_p)
                st.setdefault('buy_mem_used', 0)
                st['buy_mem_used'] = st['buy_mem_used'] + 1
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐⭐ 2026-10-05 **金币不足 ⇒ "也不规划"必须彻底**（用户口径）：
    #   ⚠ 上面三条来源（本帧 buy/buy_hidden、跨轮 `sticky`、`buy_seen` 记忆）
    #     都可能把商人/宝库塞进 pending ⇒ **只过滤第一处是不够的**（那样它仍会被规划）
    #   ⇒ 在这里**统一清空**，保证"等于拉黑"真的成立 ✓
    if not gold_enough_locked(st) and pending_buy:
        _dropped = ['%d,%d' % cell_of(*p) for p in pending_buy]
        pending_buy = []
        try:
            st.setdefault('buy_sticky', {}).clear()
        except Exception:       # noqa: BLE001
            pass
        log.append({'buy_pending_cleared_low_gold': _dropped,
                    'gold': st.get('gold_locked'), 'min': GOLD_MIN_BUY,
                    'note': '金币不足 ⇒ 清空待买目标（含跨轮 sticky/记忆）'
                            '—— 商人和宝库**不买也不规划** ✓'})
    # ⭐⭐⭐ 2026-10-02 **按用户口径定案**（用户原话：「目标没了就可以退了，
    #   不用把雾格全揭开」）：
    #
    #   背景：这里原来从手机端 v1.29 搬来一个「探索模式闸门」——
    #   「没目标但盘上还有 N 格雾 ⇒ 先探图再收工」，理由是当年出现过
    #   `finish: targets_done, gray_left: 20`（25 体力一格没开就花掉）。
    #   ⚠⚠ 但那 20 格雾之所以「有目标却认不出」，**根因是识别层坏了**
    #   （`spots._region` 的 pad 对多格模板算成负数 ⇒ 战斗格全错，
    #    见 commits `1e64b1b` / `861687b` / `615fad1`），
    #   拿「继续探图」去盖一个**识别 bug**，属于治标 ✗
    #   ⇒ 识别修好后，真正的口径就是用户说的：**目标没了就退**，
    #     不为了「把雾全揭开」而继续烧体力。
    #
    #   ⇒ `_explore` 现在**只用于日志措辞**，不再参与退图判定；
    #     退图条件恢复成「没有标记格 且 没有商人/宝库」即可 ✓
    _explore = need_explore(marked, pending_buy, len(grays),
                            st.get('explore_clicks', 0))
    # ⭐⭐⭐ 2026-10-02 修「**规划没执行完就退图**」（用户报「为什么刚刚那把没执行完规划就退了？
    #   紫探索没打」）：
    # ⭐⭐⭐ 2026-10-03 用户口径（原话：「**就按这个做**」）：
    #   **把「退图判定」挪到点击循环之后** —— 原话逻辑：「紫金格不也在规划里吗？」
    #   ⇒ 对：只要判定挪到后面，计划的步就会被**点击循环消费掉**，
    #     不必再靠一个前置闸门"拦住退图" ✓
    #   为什么原位置是错的：这道判定原来在**点击循环之前** ⇒ 只要"标记格清空"就先
    #     `return 'done'` ⇒ 计划里剩下的步**这一回合根本走不到点击循环**、跟着整张图被丢掉 ✗
    #     （真机 00:24：规划 `1,1 1,2 2,4`，打完首领后剩紫金格 (2,4) 一下没点就退图，
    #       用户报「没执行完规划就退了，紫探索没打」）
    #   ⇒ 已删除 `_plan_left_now` / `keep_going` 那个补丁（它只是绕过结构问题，
    #     副作用是"剩余步是雾格时白耗 2~3 轮、每轮 ~4s"）✓
    #   ⇒ 现在的判定在 `one_round` **结尾**（点击/面板/脱困都跑完之后），见文件末尾那段 ✓
    # ⚠ 原来这里还有一句 `if _explore: say('先揭几格开路探图')` ——
    #   它在上面的 `return 'done'` **之后**，是**死代码**（永远到不了），
    #   但它的存在让源码读起来像「还在探图」，误导了后续维护 ⇒ 删掉 ✓
    #   （用户 2026-10-02：「目标没了就可以退了，不用把雾格全揭开」✓）
    # ⭐ 2026-09-30 悬浮条心跳：给用户看的是「第几张图 · 还剩几个目标」，
    #   **不是**轮号/坐标/cost/步数（那些只进控制台）。每轮更新一次 ⇒ 长时间无事件时
    #   用户也能看出"它还活着、在推进"，而不是盯着一句几分钟前的旧状态。
    # ⭐⭐⭐ 2026-10-03 用户口径：「**我觉得有规划就够了**」⇒ 悬浮条也以**计划**为准：
    #   原来只报"还剩 N 个目标"，标记清空后会显示"还剩 0 个目标"却仍在走（用户看着像卡住 ✗）
    #   ⇒ 现在把**计划剩余步数**报出来（0 步 + 0 目标 = 真收尾）✓
    _pl_left_status = 0
    try:
        for _p3 in (st.get('plan') or []):
            if marks_mod.cell_center(_p3[0], _p3[1]) in done:
                continue
            _pl_left_status += 1
    except Exception:                       # noqa: BLE001
        _pl_left_status = 0
    status('第 %d 张图 · %s（计划剩 %d 步 / %d 个目标）'
           % (cur_map_no(),
              '正在找路' if (len(marked) + len(pending_buy)) > 0 else '按计划走',
              _pl_left_status, len(marked) + len(pending_buy)))
    # 点序：**无条件交替** —— 揭一格 → 点一次商人/宝库 → 点一次标记格 → 再揭一格…
    #   ⭐ 内容格只在「还有未完成目标」时当**开路**用（用户 2026-09-25）：
    #      boss 那类标记格常常是「未揭示」状态、点不动，必须消耗它旁边的地块才会
    #      连锁揭示（`RemoveBlock` → `SetBlockVisible`）—— 内容格（宝箱/海螺/游乐设施…）
    #      点一下就消耗，正好用来开路。**目标一清完立刻退图，不再多点**（提高效率）。
    marks_any = fresh + need
    buy_any = pending_buy
    clearable = [p for p in nones_extra if p not in done and cold.get(p, 0) < 2]

    # 「出生地」= 营地格（用来判断哪些格在「出生地 → 目标」的路上）
    spawn = st.get('spawn')
    if not spawn and c.get('st'):
        # ⭐ 2026-10-02：同一个判据的第二处调用点，一起走 `find_camp_cell()`（带兜底）
        #   —— 免得"只改一半 ⇒ 线上仍复现"（`交接文档 §14.1` 的教训）
        _ck2, _chow2, _csc2 = find_camp_cell(c['st'], log, where='spawn_road')
        if _ck2 is not None:
            spawn = marks_mod.cell_center(_ck2[0], _ck2[1])
            st['spawn'] = spawn

    def path_to(target, limit=6):
        """出生地 → 目标 **那条直线上的可点格**（用户 2026-09-25 口径）

        判据 = Bresenham 直线取格；只保留「已揭示、能点」的格（点不动的暗格点了也没用）。
        顺序 = 从出生地那头往目标走（沿路推进）。
        直线上一格可点的都没有时，退回旧的走廊判据兜底（免得卡死）。
        """
        cands = [p for p in list(nones) + list(nones_extra)
                 if p not in done and cold.get(p, 0) < 2]
        if not spawn:
            cands.sort(key=lambda p: abs(p[0] - target[0]) + abs(p[1] - target[1]))
            return cands[:limit]
        sc_ = cell_of(spawn[0], spawn[1])
        tc_ = cell_of(target[0], target[1])
        line = line_cells(sc_, tc_)
        road = []
        for (rr, cc) in line:
            if (rr, cc) == tc_:
                continue                    # 目标格本身不是「拦路」
            pt = marks_mod.cell_center(rr, cc)
            if pt in cands and pt not in road:
                road.append(pt)
        if road:
            return road[:limit]
        # 兜底：直线上一格都点不了（都被点过/拉黑）→ 用走廊判据找附近的
        d_st = abs(spawn[0] - target[0]) + abs(spawn[1] - target[1])

        def key(p):
            d_t = abs(p[0] - target[0]) + abs(p[1] - target[1])
            d_s = abs(p[0] - spawn[0]) + abs(p[1] - spawn[1])
            return (abs((d_s + d_t) - d_st) > 2, d_t)
        cands.sort(key=key)
        return cands[:limit]

    order = []
    road_all = []
    if OPT:
        # ⭐ 体力最省模式：整轮点序由 Dijkstra 最优解给出（失败则退回下面的启发式 ✓）
        opt = optimal_order(c, mk, st, log)
        if opt:
            entry['opt_order'] = len(opt)
            road_all = list(opt)
            order = list(opt)
    # ⛔⛔⛔ 2026-10-02 修「开局全雾 ⇒ 一格不揭就退图」（真机帧 runs/r_023054_0.png 逐格核实）
    #
    #   症状：进图 r0 就 `没有目标了` → 退图，25 体力白花（该帧 33 格雾 + 4 格宝箱）。
    #   根因：下面 6603 那个分支的条件是 `not order and (marked or buy_any)` ——
    #         **必须有可见目标才组装点序**。可开局目标恰恰**全藏在雾里**
    #         （`marked`/`buy_any` 都空）⇒ 整段开路逻辑被跳过 ⇒ `order` 永远空。
    #   ⛔ 这是逻辑自相矛盾：「没目标」被当成「结束」，而正确含义是「**还没开图**」。
    #   ⇒ 补一条**无目标探图**路径：用**已揭示的格**揭几格开路，
    #     让连锁揭示把雾里的目标逐步露出来（这本来就是游戏玩法 ✓）。
    #   ⚠ 只在「确实没目标」时启用，且不碰 `marked`/`buy_any` 非空的老路径（零回归 ✓）。
    if not order and not marked and not buy_any:
        # ⚠⚠ 2026-10-02 用户口径：「目标没了就可以退了，不用把雾格全揭开」
        #   ⇒ **本段整体不再参与**（它就是那个"没目标也继续探图"的探图闸门）。
        #   留着它会：① 与上面 6703 的 `return 'done'` 抢跑（谁先到看执行顺序），
        #   ② 真机日志里 `probe_order` 反复列**已经点掉**的格（在点空气）✗✗
        #   ⇒ 已整段停用；下方 `marked or buy_any` 的老路径**不变**（零回归 ✓）。
        #   （`need_explore` / `_explore` 保留：`_explore` 仍被 6703 上方读取用于
        #     日志措辞，将来若要「开局全雾先揭两格」也不必重写。）
        pass
    if not order and (marked or buy_any):
        # ⭐⭐⭐ 2026-10-02 按用户口径改：`_explore` **不再**算「要组装点序」的依据
        #   （用户原话：「目标没了就可以退了，不用把雾格全揭开」）。
        #   ⚠ 原来这里带 `or _explore`（手机端 v1.29 搬来），后果是真机日志里：
        #        r3 点过 4 下揭掉 13 格雾 → r4/r5/r6 三轮 `order` 全空
        #        → `probe_order` 反复列**已经点掉**的 1,1/1,2（在点空气）
        #        → `blank_board` 连 3 轮才退图，白等 ~1 分钟 ✗✗
        #   ⇒ 现在：只有**真有目标**（标记格 / 商人 / 宝库）才组装点序；
        #     没目标 ⇒ 上面 6703 那条直接 `return 'done'` 收工 ✓
        # ⭐ 有标记格（或商人/宝库）未处理 -> 先把「出生地→目标」路上的可点格列出来，
        #   a) 优先沿路开路  b) 只有这些格弹出来的战斗才允许打（用户口径：无关战斗不打）
        if st.get('clear_clicks', 0) < 24:
            # 开路目标 = 点不动的标记格 / 所有标记格 / **商人宝库（含已揭示但点不开的）**
            road_targets = list(need or marked) + list(buy_any) + list(buy_hidden)
            for t in road_targets:
                for p in path_to(t):
                    if p not in road_all:
                        road_all.append(p)
        if road_all:
            entry['road'] = road_all[:6]
        # ⭐ 点序必须**严格交替**：揭一格/开一格 → 立刻试一次目标（首领/商人宝库）→ 再揭…
        #   用户 2026-09-25：「为什么连续点了好几次出生点周围的，中间没有去点首领判断能不能直接打？
        #   不应该是点一下判断一下首领吗」
        # ⚠ 2026-09-25 再修（用户：「还在点不是那条直线上的格子」）：
        #   有目标时**只点直线上的格**（`road_all`），别再把全部已揭示格（nones）也排进去；
        #   只有直线上真的没有可点的格时才退回 nones 兜底（否则会卡死）。
        # ⚠ 另：**未揭示的商人/宝库不进点击序列**（点不动，只会白耗 cold 被误判成放弃）
        targets = [p for p in buy_any if p in set(buy)] + marks_any
        if FOLLOW_PLAN_ONLY:
            # ⭐⭐⭐ 2026-10-02 用户口径：「去掉那些追加的，只按规划的走」⇒
            #   **这里一格都不追加**（路上开路格 / 交替插入的目标格 / 内容格兜底 全去掉），
            #   `order` 只由下面的规划器产出（solver ≤4 步 / eff ≤2 步）✓
            #   ⚠ `targets` 仍要算 —— 下面 `st['targets']` 要用它（**判据**，不是点击）✓
            order = []
        else:
            # ⭐ 点序必须**严格交替**：揭一格/开一格 → 立刻试一次目标（首领/商人宝库）→ 再揭…
            #   用户 2026-09-25：「为什么连续点了好几次出生点周围的，中间没有去点首领判断能不能直接打？
            #   不应该是点一下判断一下首领吗」
            # ⚠ 2026-09-25 再修（用户：「还在点不是那条直线上的格子」）：
            #   有目标时**只点直线上的格**（`road_all`），别再把全部已揭示格（nones）也排进去；
            #   只有直线上真的没有可点的格时才退回 nones 兜底（否则会卡死）。
            # ⚠ 另：**未揭示的商人/宝库不进点击序列**（点不动，只会白耗 cold 被误判成放弃）
            if road_all:
                reveals = list(road_all)
            else:
                reveals = list(nones)
            for p in reveals[:10]:
                order.append(p)
                order.extend(targets)
            order += reveals[10:] + targets
            # 直线上一格可点的都没有 → 才用内容格兜底开路（同样只在这时插）
            if not road_all and st.get('clear_clicks', 0) < 16:
                for q in clearable[:6]:
                    order.append(q)
                    order.extend(targets)
    else:
        order = []
    # ⭐⭐ 2026-09-27 用户要求：**每张图只在进图后规划一次** ✓（不要每轮都规划 ✗）
    #   ⭐⭐⭐ 2026-09-30 **推翻这条**（离线 96 张盘对拍）：
    #     ① 进图时规划的**目标集是残缺的**（未揭示的标记格 / 商人还没认出来）
    #        ⇒ 「进图规划一次」比全知最优贵 **+9.2%**（marks 可见时）/ **+26.1%**（marks 藏雾里），
    #        最坏单盘贵 **16 体** —— 这正是用户报的「算出了但不是最优走法」✗
    #     ② 当年"每轮重算要卡几十秒"是**旧 Dijkstra** 的数字；2026-09-29 A* 重构后
    #        求解**完整链路**（建盘+编译+solve）实测 **p50 0.65ms / p95 1.4ms / p99 1.9ms**
    #        ⇒ 每轮重解**零成本** ✓
    #     ③ 改「每轮用最新观测重解」后：真机盘 **95/95 张与全知最优逐字节相等**（0.00% 差）
    #        （`cur` 进图一次：89 相等 / 6 更贵；`EffPolicy`：75 相等 / 20 更贵）
    #   ⇒ 现在每轮都重解，旧计划**直接丢弃**（不再累积、不再"计划耗尽才兜底"）✓
    if OPT_SOLVER and c.get('st'):
        #   ⚠ 2026-09-27 修（保留）：原来"算一次失败就永久放弃" ✗
        #     （第一轮若棋盘被面板盖住 ⇒ solver 返回空 ⇒ 整张图都没计划 ✗）
        #     ⇒ 改成**没算出就下轮再试，最多 3 次** ✓
        #   ⭐⭐ 2026-09-28（保留）：连续 3 次算不出 ⇒ 本图切 EffPolicy（plan_src='eff'），
        #     避免每轮都白等一次超时 ✓
        _sol = None
        if st.get('plan_src') != 'eff':
            if not OPT_SOLVER:
                st['plan_src'] = 'eff'       # `--no-solver`：直奔 EffPolicy，别白数 3 轮 ✓
            else:
                # ⭐⭐⭐ 2026-10-02 用户口径：「第七张图**第一次规划完全正确**啊，
                #   为什么后面会成这样？**要不改成只规划一次**」⇒ `PLAN_ONCE`
                #   真机铁证（gui_20261002_225339 / loop_log #259→#317，第 7 张图）：
                #     r0 规划 `5,5 → 4,6 → 3,7`（体力 7 / 3 步）—— **完全正确** ✓
                #     r2 重算成 `4,5 → 3,7`、r3+ 塌成 `3,7`（**一步，且 3,7 是雾格**）
                #     ⇒ 真机点它 5 轮全 `changed:false`（雾格点不动）⇒ no_progress ⇒ stuck ✗✗
                #   根因：**每轮重解用的都是"模型自己以为的状态"**，而那份信念每轮都在漂
                #     （它以为 4,5/4,6 已经消耗/已揭示）⇒ 计划越算越歪，最后塌成"直接点雾格"。
                #     ⚠ 而 solver 是拿 `mark_revealed=True` 喂的（标记格当"可点"），
                #       加上 boss 有「永不拉黑」保护 ⇒ 这个错误计划**不会被自动纠正** ✗
                #   ⇒ 现在：**计划用完之前不重算**（进图算一次 → 逐轮消费同一份）；
                #     只有"剩余步为空"（用完 / 全被点掉）才重算一次，免得新揭出来的目标没人管 ✓
                _plan_left_rc = []
                for _p0 in (st.get('plan') or []):
                    if marks_mod.cell_center(_p0[0], _p0[1]) in done:
                        continue
                    _plan_left_rc.append(_p0)
                    if len(_plan_left_rc) >= 4:
                        break
                # ⭐⭐⭐⭐ 2026-10-04 用户口径（原话）：「**怎么还在多次规划？我不是说过一次规划
                #   就行**」✗ ⇒ 原来这里只在"还有没用完的步 **且** 没连续点雾"时才沿用 ✗
                #   ⇒ 于是两种情况下会**重算**：
                #      ① 计划里的步都已点过（`_plan_left_rc` 空 ✗）⇒ 重算 ⇒ 又得一份新计划
                #      ② 连续点了 2 轮雾格（`fog_noop_streak >= 2` ✗）⇒ 强制重算
                #   真机后果（用户贴的第 5 张图 ✓）：r0 算了 3 步、r2 又算 3 步、r5 又算 4 步 ✗
                #     ⇒ 地图耗时 71 秒、最后落到 `target_unreachable` ✗
                #   ⇒ 现在：**本图只要算过一次计划（`had_plan`）就一律沿用** ✓
                #      · 计划用完 ⇒ 剩余为空 ⇒ 本轮自然什么都不点 ⇒ 由收工逻辑决定 ✓
                #      · 连续点雾 ⇒ 也不再重算（重算出来的还是那几格 ✗ 白花时间 ✓）
                #      （想回到旧行为：把下面条件换回
                #         `PLAN_ONCE and _plan_left_rc and fog_noop_streak < 2` ✓）
                if PLAN_ONCE and st.get('had_plan'):
                    # 还有没用完的步 ⇒ **沿用**（不重算）✓；已用完 ⇒ 也沿用（空计划 ✓）
                    st['plan_reused'] = st.get('plan_reused', 0) + 1
                    log.append({'solver': 'plan_reused', 'left': len(_plan_left_rc),
                                'n': st['plan_reused'],
                                'note': '一图只规划一次：沿用进图那份计划（不再重算 ✓）'})
                    _so = {'reason': 'reused'}
                else:
                    # ⭐⭐⭐ 2026-10-02（C）**连续点雾格 ⇒ 强制重算**（无视 PLAN_ONCE）：
                    #   真机 23:30 那把：计划 `["1,2","2,4"]` 两格都是雾 ⇒ 两轮全
                    #   `fogged_noop` ⇒ `plan_reused` 让它**一直沿用** ⇒ 0 进展卡死 ✗
                    #   ⇒ 连续 ≥2 轮点雾就重算一次（配合 A 的观测闸门，新计划不会再排雾格）✓
                    _fstr = int(st.get('fog_noop_streak', 0) or 0)
                    if _fstr >= 2 and _plan_left_rc:
                        log.append({'solver': 'force_replan_fogged', 'streak': _fstr,
                                    'left': len(_plan_left_rc),
                                    'note': '连续点雾格无反应 ⇒ 强制重算计划（不再沿用）'})
                        say('       · 连续 %d 轮点到的都是雾格 ⇒ 强制重算计划 ✓' % _fstr)
                    _so = {}
                    # ⭐ 只要**前 4 步**（每轮真机就点 4 下；多要步数没有意义，还拖慢 ✓）
                    # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**上限改为 10 步**」✓
                    #   （原来 4 步 ⇒ 计划被截断 ⇒ 日志里只看得到前 4 步、每轮都要重算 ✗
                    #    实测解算 ~0.65ms ⇒ 多要几步成本可忽略 ✓）
                    _sol = solver_order(st, c, log=log, max_steps=10, out=_so)
                if _sol:
                    st['plan'] = list(_sol)      # ⭐ 每轮**覆盖**（不是追加）
                    st['had_plan'] = True        # ⭐ 2026-10-03：本图**算出过计划**
                                                 #   ⇒ 计划走完后 `blank_board` 立刻收工 ✓
                                                 #   （与"从没算出过计划"的全雾盘区分开 ✓）
                    st['plan_src'] = 'solver'
                    st['plan_tries'] = 0
                elif _so.get('reason') == 'reused':
                    pass                          # 沿用旧计划 ⇒ 什么都不用改 ✓
                else:
                    st['plan'] = []
                    # ⚠ 「盘上已经没有目标了」**不算失败**（正常收尾）——否则会白切 EffPolicy ✗
                    if not _so.get('no_targets'):
                        st['plan_tries'] = st.get('plan_tries', 0) + 1
                        if st['plan_tries'] >= 3:
                            st['plan_src'] = 'eff'
                            say('       · 精确规划连续 %d 轮没算出 ⇒ 本图改用片感知策略'
                                '（EffPolicy）' % st['plan_tries'])
                            try:        # ⭐ 悬浮条也告诉用户"这图改走兜底策略了" ✓
                                status('规划：改用片感知兜底（精确解算没出结果）')
                            except Exception:       # noqa: BLE001
                                pass
        else:
            st['plan'] = []
        # ⭐⭐ 2026-09-28：EffPolicy 兜底 —— 每轮用**最新观测**现算点序（毫秒级 ✓）
        if st.get('plan_src') == 'eff' and c.get('st'):
            _eff = eff_order(st, c, log=log, max_steps=20)
            _eff_pick = []
            for _p in _eff:
                if marks_mod.cell_center(_p[0], _p[1]) in done:
                    continue
                _eff_pick.append(_p)
                # ⭐ 取前 2 步（2026-09-28 离线扫描 60 张：batch=4 → 11.88，
                #   batch=2 → 10.97，batch=1 → 10.72；2→1 只省 0.25 但真机轮数翻倍
                #   （每轮截图+OCR 有开销）⇒ 2 是甜点 ✓ solver plan 消费保持 4 不动
                #   ——那是静态点序（不重算），多取几步减少空轮 ✓）
                if len(_eff_pick) >= 2:
                    break
            if _eff_pick:
                if not FOLLOW_PLAN_ONLY:
                    # ⭐ 2026-10-02 这是**手机端 v1.34 搬来的「提序」**（能点的 boss/红装提到最前）
                    #   ⇒ PC 端**不跟随**（用户 2026-10-02：「提序我记得是手机端说过的」）✓
                    _eff_pick = _hoist_ready_boss_first(st, _eff_pick, log=log, tag='eff')
                _eff_px = [marks_mod.cell_center(r, cc) for (r, cc) in _eff_pick]
                order = _eff_px + order
                entry['eff_order'] = ['%d,%d' % p for p in _eff_pick]
        else:
            _eff_pick = []
        _picked = []
        _plan = list(st.get('plan') or [])
        # ⭐⭐⭐ 2026-10-03 修**无限重规划循环**（我上一条"试一次就摘"引入的回归）：
        #   真机现象（用户贴的日志）：每轮都重算出**同样的 4 步**
        #     `['4,5','4,6','4,7','5,6']` ⇒ 又立刻被"已试过 ⇒ 摘掉"全摘掉 ⇒
        #     **一步都没点** ⇒ 下一轮再算同样的 ⇒ 无限循环、0 进展 ✗✗
        #   ⇒ 摘掉的步必须**记住**：本图内不再进点序（`st['plan_given_up']`）；
        #     若整份计划**全是**已摘掉的步 ⇒ 说明这张图推不动了 ⇒ **直接收工**（不再空转 ✓）
        _giv = set(st.get('plan_given_up') or ())
        if _plan:
            # 取"接下来还没做完的几步" ✓（已完成的跳过 ✓；**已摘掉的也跳过** ✓）
            for _p in _plan:
                if marks_mod.cell_center(_p[0], _p[1]) in done:
                    continue
                if tuple(_p) in _giv:
                    continue
                _picked.append(_p)
                if len(_picked) >= 4:
                    break
            if not _picked:
                _left_all_giv = [p for p in _plan
                                 if marks_mod.cell_center(p[0], p[1]) not in done]
                if _left_all_giv:
                    # ⛔⛔ 2026-10-03 用户口径：「**我希望模型推演的就是正确的，不要重新扫描**」✗
                    #   ⇒ **删掉"清空已摘步骤 + 强制重算一次"那条**（那是重扫 ✗ 会拖时间 ✗）
                    #   ⇒ 这里只保留**诚实的结论**：目标点不动 ⇒ 收尾并明确标记
                    #     `target_unreachable` ✓（不再冒充"目标已清完"✗）
                    #   治本在模型层（`mapsolve.visible()` / 起始"已消耗"集合 ✓）——
                    #   模型推演正确之后，计划就不会再出现雾格，这条路基本不会走到 ✓
                    log.append(entry)
                    log.append({'finish': 'target_unreachable',
                                'targets_left': len(_left_all_giv),
                                'cells': ['%d,%d' % tuple(p) for p in _left_all_giv[:6]],
                                'note': '目标点不动（雾里/被挡）⇒ 明确收工 ✓'
                                        '（**不是"目标已清完"** ✗；治本在模型推演 ✓）'})
                    say('   · 目标点不动（雾里/被挡）⇒ 本图收工'
                        '（标记为 **target_unreachable** ✓ 不是"目标已清完"）')
                    return 'done'
            if _picked:
                if not FOLLOW_PLAN_ONLY:
                    # ⭐ 2026-10-02 这是**手机端 v1.34 搬来的「提序」**：
                    #   真机铁证（手机端）：boss 已能打却被排在素材格后面，先白点一格 ✗
                    #   ⚠ 用户 2026-10-02 指出「**提序我记得是手机端说过的**」⇒
                    #     PC 端**不跟随**，严格按规划顺序点 ✓
                    _picked = _hoist_ready_boss_first(st, _picked, log=log, tag='solver')
                _sol_px = [marks_mod.cell_center(r, cc) for (r, cc) in _picked]
                order = _sol_px + order
                _sp_px3 = st.get('spawn') or st.get('camp')
                _sp_rc3 = None
                if _sp_px3:
                    try:
                        _sp_rc3 = cell_of(_sp_px3[0], _sp_px3[1])
                    except Exception:       # noqa: BLE001
                        _sp_rc3 = None
                entry['solver_order'] = ['%d,%d' % p for p in _picked
                                         if p != _sp_rc3]
                entry['plan_left'] = len(_plan)
        # ⭐⭐⭐ 2026-09-28 修「点了 33 却没打」（用户真机报）：计划内剩余步 =
        #   「计划内的路」⇒ popups 的战斗面板判定用（solver/EffPolicy 已做过
        #   「绕开更贵」的权衡 ⇒ 计划内弹出的战斗**必打**，不再被 offroad_fight
        #   旧口径关掉 ✗ → 参见 popups 里 on_plan 分支 ✓）
        st['plan_road'] = [marks_mod.cell_center(r, cc) for (r, cc) in
                           (_eff_pick if st.get('plan_src') == 'eff' else _picked)]

    # ⚠ 2026-09-27 用户要求：**去掉**"战斗刚结束 ⇒ 把目标格插到最前"这个行为 ✗
    #   （原来 st['try_targets'] 会在战斗后把目标排最前 ✓ 用户明确不要 ✓）
    if st.get('try_targets'):        # 兼容老状态：只清标记，不再改点序 ✓
        st['try_targets'] = False
    st['road'] = road_all
    # ⭐ 2026-09-27：`plain_road` = 这条路上**可点的空地块**（判断"是否被迫打"用 ✓）
    try:
        _nones_set = set(nones) | set(nones_extra)
        # ⚠ 必须排除**已完成**的格 ✓（否则"已经点掉的空地"还在算 ⇒ 会误判成"前面有空地"✗
        #   ⇒ 该打的障碍不打 ✗ = 用户报「点了 33 却没打掉这个战斗格」✓）
        st['plain_road'] = [p for p in road_all
                            if p in set(nones) and p not in done]
    except Exception:       # noqa: BLE001
        st['plain_road'] = []
    # ⭐ 待处理目标（供 popups 判「紧挨目标的战斗格 = 拦路」用）
    st['targets'] = list(marked) + list(buy_any)
    if not order and not marked:
        st['blank'] = st.get('blank', 0) + 1
        log.append(entry)
        # ⭐⭐⭐ 2026-10-03 用户口径（原话两次）：「**无意义的三轮不是早就让全删了吗**」⇒
        #   实测现象：日志连着刷「目标已清完、计划也走完 ⇒ 本图收工」却仍在 r5/r6 跑 ✗
        #   （那句话是规划段打印的，而真正退图要先过这里 3 轮 1.5s 的等待 ✗）
        #   为什么之前留着：门禁 `verify_fog_only_start` 守着历史事故
        #     「开局全雾 + 认不出目标 ⇒ `targets_done, gray_left: 20` ⇒ 25 体力一格没开就白花 ✗✗」
        #   ⇒ 现在**按"这张图到底规划过没有"精确区分**（两个目的都保住 ✓）：
        #       · `had_plan`（本次进图**算出过计划**）⇒ 计划已走完 ⇒ **立刻收工，不等** ✓
        #         （正常图都走这条 ⇒ 那无意义的三轮彻底消失 ✓）
        #       · 从没算出过计划（全雾/识别失败）⇒ 保留 3 轮耐心，给识别一次机会 ✓
        if st.get('had_plan'):
            log.append({'finish': 'blank_board', 'n': st['blank'], 'had_plan': True,
                        'note': '计划已走完 ⇒ 立刻收工（用户口径：删掉无意义的三轮 ✓）'})
            say('   · 计划已走完、也没有标记目标 ⇒ 立刻收工（不等那 3 轮 ✓）')
            # ⚠⚠ 2026-10-03 同样必须返回 **'done'**（不是 'blank' ✗）：
            #   'blank' 会被 `run_maps` 当"认不出棋盘"计数 ⇒ 连着 2 张正常收工就停整局 ✗✗
            return 'done'
        log.append({'finish': 'blank_board', 'n': st['blank'], 'had_plan': False})
        if st['blank'] >= 3:
            log.append(_stuck_why(st, c, rnd, {'stuck_why': 'blank_board',
                                              'blank_n': st['blank']}))
            return 'blank'
        time.sleep(1.5)
        return None
    # ⭐ 刚点那格的地块 ID（给 popups 判"是不是紫/橙探索地块"用 ✓）
    try:
        if st.get('last') and c.get('st'):
            _tc = cell_of(st['last'][0], st['last'][1])
            st['tapped_sid'] = str((c['st'].get(_tc) or {}).get('sid') or '')
    except Exception:       # noqa: BLE001
        st['tapped_sid'] = ''
    marked_px = set(marked)
    # ⭐⭐⭐ 2026-10-01 v1.00【用户问：「规划没有拉黑特殊地块？还是规划那里并且去点了」】
    #   答：**两条都得堵**。v0.99 已让"拉黑格不参与连通/连锁/目标"（模型侧 ✓），
    #   但**点序里还可能出现它**——因为求解器的"可点步"是按"已揭示的块"给的，
    #   而点掉一个内容格在模型里也算"消耗一个块、让邻居算已揭示"
    #   （真机也确实如此：点一下会揭开邻居）⇒ solver 可能把宝箱怪当**便宜的开路步**排进去 ✗
    #   而执行侧 `cands` 只看 `done/cold`，**不认拉黑** ⇒ 真把它点了 ✗✗
    #   ⇒ 这里在**点序进 keep 之前**做硬过滤：拉黑格（含 solver plan 里的）一律剔除，
    #     并落日志 `blocked_in_order`（这样"规划里有没有它"一眼可见 ✓）。
    _blk_set = set()
    try:
        _blk_set = set(_blocked_px(st, c))
    except Exception:       # noqa: BLE001
        _blk_set = set()
    if _blk_set:
        _drop = [p for p in order if p in _blk_set]
        if _drop:
            _drop_rc = []
            for _p in _drop[:8]:
                try:
                    _drop_rc.append('%d,%d' % cell_of(_p[0], _p[1]))
                except Exception:       # noqa: BLE001
                    pass
            entry['blocked_in_order'] = _drop_rc
            log.append({'blocked_in_order': _drop_rc,
                        'note': '拉黑地块被排进点序 ⇒ 剔除（不点 ✓）'})
            say('       · 点序里有 %d 个拉黑地块（%s）⇒ 已剔除，不去点 ✓'
                % (len(_drop), '、'.join(_drop_rc)))
            order = [p for p in order if p not in _blk_set]
    # ⭐ 商人/宝库格**永不拉黑**（用户 2026-09-25：「有黄金宝库你没点就要退」）：
    #   点它那一下如果面板没被 OCR 认到（动画/时机），旧逻辑会给它 cold+1，
    #   两次之后进 `done` 永久排除 → 下一轮 buy=0 → 直接退图，宝库白白漏掉。
    # ⭐⭐⭐ 2026-10-01 v0.96：免拉黑范围**扩到「粘性集 + 跨轮记忆 + 验证式探点」** ——
    #   上面那段注释说的"永不拉黑"必须对**认到过**的宝库成立，而不是只对"本帧还认得出"的成立：
    #   真机证据（用户报「能直接点的黄金宝库不去点，却去打了两个战斗地块」）：
    #   `st['plan']` 里明明排了那格宝库（日志「最省体力 1，1 步 → 2,7」），
    #   但本帧 buy/buy_hidden 恰好都空 ⇒ `buy_px` 空 ⇒ `cands` 用 `cold<2` 把它滤掉
    #   ⇒ 点序跳到下一个候选（开路格）⇒ 弹出的"拦路"战斗就这么打起来了 ✗
    buy_px = (set(buy) | set(buy_hidden) | set(sticky)
              | set(st.get('buy_seen') or {}) | set(_probe_px))
    # ⭐⭐⭐ 2026-10-01 v0.96【能直接点就先点】：**已揭示的商人/宝库排到点序最前**
    #   用户口径（2026-09-25 / 2026-10-01 两次强调）：「有黄金宝库你没点就要退」、
    #   「黄金宝库明明都揭示了能直接点，他又去打了两个战斗地块」。
    #   旧点序是"揭一格 → 试一次目标"**交替**（`for p in reveals: order.append(p); order += targets`）
    #   ⇒ 第一下永远是**开路格**；枯木丛林那类图的开路格常触发"拦路"战斗
    #   ⇒ 用户看到的就是"宝库就摆在眼前，机器人先去打了两个战斗地块"✗
    #   ⇒ 宝库是 1 体力、点完就买；直接把它放最前（面板流程照旧接管 ✓）
    try:
        _buy_first = [p for p in buy if p not in done]
        if _buy_first:
            order = _buy_first + list(order)
            entry['buy_first'] = ['%d,%d' % cell_of(*p) for p in _buy_first]
    except Exception:       # noqa: BLE001
        pass
    # ⭐ 2026-09-26：按格累计「点了画面完全没反应」（跨轮持久，见下方拉黑逻辑）
    _nc = st.setdefault('nochange', {})
    cands = [x for x in order if x not in done
             and (x in marked_px or x in buy_px or cold.get(x, 0) < 2)]
    if not cands:
        log.append(entry)
        if marked:
            log.append(_stuck_why(st, c, rnd, {'stuck_why': 'targets_unreachable',
                                              'cands_n': 0}))
            log.append({'finish': 'targets_unreachable'})
            return 'stuck'
        # ⛔⛔⛔ 2026-10-02 修「r0 就退图，一张图没刷」（真机帧 runs/r_023054_0.png 逐格核实）
        #
        #   症状：进图第 0 轮就 `没有目标了` → `all_done` → 退图，25 体力白花。
        #   根因：那帧是 **33 格雾 + 4 格已揭示宝箱**。雾格点不动（不进 `nones`），
        #         宝箱不是目标（不点）⇒ `order` 空 ⇒ 这里判"all_done"⇒ 退图。
        #   ⛔ **雾格不是"打完"，是"还没开始"** —— 开局目标全藏在雾里是**正常状态**。
        #   ⇒ 判据必须区分两种"没候选"：
        #        ① 盘上**还有大片未揭示的雾** ⇒ 说明还没开图完 ⇒ **不能退**
        #        ② 雾格都清完了、也真的没目标了 ⇒ 那才是"结束冒险"
        #   ⚠ 与 `blank_board`（6748 行，3 轮才退）是同一族问题，但**它先触发**：
        #     6748 只在 `not order and not marked` 时等 3 轮；而这里 `marked` 也空、
        #     走到 `cands` 为空就直接 return ⇒ 绕过了那道保护 ✗
        #   ⇒ 这里也用同样的"连续 N 轮才认输"口径，且**雾格占比大时先多等**。
        # ⭐⭐⭐ 2026-10-03 用户口径（原话选择）：「**删掉「求解器失败时的兜底」（= 计划空也照样退）**」
        #   ⇒ 这里**不再等 2~4 轮**：点序空 ⇒ 直接收工 ✓
        #   代价（如实记下，供以后回看）：求解器**偶发**失败（历史上 2026-09-27 三把各 1~2 次、
        #     10-02 11:58 连 3 轮 ⇒ 切 EffPolicy）时，这张图会被放弃 ⇒ 白扔 25 体力。
        #   收益：每张"计划算不出"的图**省 8~16s**（原来要等 `_need_rounds` 轮，每轮
        #     marks 2.0s + 分类 0.5s + OCR 0~0.9s + sleep 1.5s ≈ 4s）✓
        #   ⚠ `_fog_heavy` 的计算保留（只用于日志措辞/诊断），**不再参与等待判定** ✓
        _gray_left = len(grays)
        # 雾格占比：≥1/3 说明图基本还没开 ⇒ 目标大概率仍藏在里面
        _fog_heavy = _gray_left >= max(6, int(0.30 * 35))
        _need_rounds = 4 if _fog_heavy else 2      # ⚠ 仅诊断用（不再据此等待）
        _empty_n = st.get('empty_order', 0) + 1
        st['empty_order'] = _empty_n
        st['empty_order'] = 0
        log.append({'finish': 'all_done', 'gray_left': _gray_left,
                    'empty_n': _empty_n,
                    'fog_heavy': _fog_heavy,
                    'note': '用户口径：计划空就退（不再等 2~4 轮）✓'})
        say('   · 点序为空（还剩 %d 格雾没揭）⇒ 按用户口径直接收工（不再等 2~4 轮 ✓）'
            % _gray_left)
        return 'done'
    hit, tried = None, 0
    progress_set = set(clearable) | set(nones)     # 点这些格 = 开路/揭格（消耗地块 → 连锁揭示）
    tapped_progress = False
    # ⭐⭐ 2026-09-30 成本审计（零行为影响）：把"本轮点序前 12 格 + 模型体力"落日志
    #   用途：用户报「不点 1 体力的、去点 4 体力的」时，一眼看出
    #   ① 便宜格有没有排在前面（点序问题）② 模型把贵格看成了 1 点（分类问题）
    #   （现场存档 + 三种机制的判据见 `_verify/phone_stamina_0930/README.md`）
    try:
        _cells_now = c.get('st') or {}
        _marks_now = st.get('marks') or {}
        _oc = {}
        for _p in list(order)[:12]:
            _rc = cell_of(_p[0], _p[1])
            _v = _cells_now.get(_rc) or {}
            _mk = list((_marks_now.get(_rc) or {}).get('marks') or [])
            _oc['%d,%d' % _rc] = [model_cost(_v.get('sid'), _mk), _v.get('sid') or '?'] + _mk
        if _oc:
            entry['order_cost'] = _oc
    except Exception:       # noqa: BLE001
        pass
    for (cx, cy) in order:
        # ⭐⭐ 立即停止的**最细粒度**检查点（2026-09-29）：一次点击 + 连锁动画 ≈ 2~4 秒，
        #   放在这里 ⇒ 用户点 ■ 后**最多再等一次当前点击**就收工（不是"打完这张图"✓）
        if stop_checked(log, '点击前'):
            return 'stopped'
        if (cx, cy) in done or tried >= 12:
            continue
        if cold.get((cx, cy), 0) >= 2 and (cx, cy) not in marked_px \
                and (cx, cy) not in buy_px:
            done.add((cx, cy))
            continue
        tried += 1
        # ⭐ 2026-10-02（手机端 v1.29 对齐）：**探图预算记账**
        #   `need_explore()` 用 `st['explore_clicks']` 当预算上限（EXPLORE_MAX_CLICKS=40），
        #   但 PC 端**从来没写过这个计数** ⇒ 恒为 0 ⇒ 预算形同虚设、
        #   探图模式可能一路探下去不收工 ✗ ⇒ 在每次真实点击时 +1 ✓
        st['explore_clicks'] = st.get('explore_clicks', 0) + 1
        st['last'] = (cx, cy)
        if (cx, cy) not in (st.get('clicked') or []):
            st.setdefault('clicked', []).append((cx, cy))     # 退出前补点用
        # ⭐⭐ 2026-09-28 诊断（**零行为影响**，只多记几个字段）：每次点击记
        #   「格 / 本轮开始后第几秒 / 画面是否变化」⇒ 用来判"点了没反应"到底是
        #   ① 格子不可点（规则）还是 ② 连锁揭示动画还没播完（时序）。
        #   背景：r_221835_0 那把计划 8 点、实花 7 点，(4,5) 那一击 `changed is False`
        #   且没扣体力；(5,4) 却是"第一次 noop、第二次成功" ⇒ 两种解释都成立，
        #   必须靠"点击时刻"区分（见 <开发笔记> §37.3 ✓）
        _t_tap = time.time()
        # ⭐⭐ 2026-09-30 成本审计：这一格**模型以为**花多少体力（记进 taps，便于和体力读数对账）
        _cost_tap, _sid_tap = None, '?'
        try:
            _rc_tap = cell_of(cx, cy)
            _v_tap = (c.get('st') or {}).get(_rc_tap) or {}
            _mk_tap = list(((st.get('marks') or {}).get(_rc_tap) or {}).get('marks') or [])
            _sid_tap = _v_tap.get('sid') or '?'
            _cost_tap = model_cost(_v_tap.get('sid'), _mk_tap)
        except Exception:       # noqa: BLE001
            _cost_tap, _sid_tap = None, '?'
        changed = b.tap(cx, cy, wait=1.3)
        # ⭐ 2026-10-01 v0.96：验证式宝库点击**计数**（每格每图上限 BUY_PROBE_MAX ✓）
        #   —— 防"一直点不开的宝库"空转（2026-09-25 卡死事故的复刻预防 ✓）
        if (cx, cy) in _probe_px:
            try:
                st.setdefault('buy_probe', {})[(cx, cy)] = \
                    st['buy_probe'].get((cx, cy), 0) + 1
            except Exception:       # noqa: BLE001
                pass
        try:
            entry.setdefault('taps', []).append(
                ['%d,%d' % cell_of(cx, cy), round(_t_tap - _t_round, 1),
                 (changed is not False), _sid_tap, _cost_tap])
        except Exception:       # noqa: BLE001
            pass
        b.snap()
        # ⭐ B（2026-09-25 用户要求「都试试」）：**只在"画面完全没变"时**跳过这次 OCR
        #   （0.74 秒/次，36 次/图是大头）。
        #   ⚠ 为什么这次敢跳：弹面板**必然**引起画面变化 ⇒ `changed` 会是 True ⇒ 照样 OCR ✓；
        #     只有"点了跟没点一样"（点不动的暗格/被挡）才会 False ⇒ 那种情况 OCR 也读不到东西 ✓。
        #   （之前那次事故是因为**同时**还砍了"回合开头的全屏 OCR"，漏看残留面板 ⇒ 乱点；
        #     回合开头那次全屏 OCR 现在保留着 ✓）
        if changed is False:
            it2 = []
            # ⭐⭐ 2026-09-27 修（用户报「第 7 张图 boss 没打就说没目标」）：
            #   点不动有两种 —— ① **未揭示的雾格**（游戏本来就点不动 ✓ 正常 ✓）
            #   ② 真被面板/别的东西挡住 ✓。原来不分 ⇒ 雾格被记 nochange ⇒ 3 次拉黑 ✗
            #   ⇒ 拉黑后 boss 目标等同消失 ⇒ 判 targets_done 提前退图 ✗✗
            #   判据：该格亮度比 <0.8 = 未揭示（已揭示≈1.0 / 未揭示≈0.65 ✓）
            #   （v0.29 回退：v0.27 的 revealed 前置改动撤销，恢复 v0.26 原判定 ✓）
            _cells_now = (c.get('st') or {}) if c else {}
            _tap_rc = cell_of(cx, cy)
            _tv = _cells_now.get(_tap_rc) or {}
            _ratio = _tv.get('ratio')
            # ⚠⚠⚠ 2026-10-05：**必须与规划期同一个常量**（`REVEAL_RATIO_MIN`）
            #   原来这里写死 `0.8` ⇒ 与规划期的 0.75 各用各的 ⇒ 真机 map7 那把：
            #   boss 格 `(5,1)` ratio=**0.918**（视觉是雾）被这条判成"不是雾"
            #   ⇒ `fog_noop_streak` 不涨 ⇒ 「连续点雾强制重算」那道自救闸门**没触发**
            #   ⇒ 计划只有一步、一步摘光就 stuck（25 体力白花）✗
            _fogged = (_ratio is not None and float(_ratio) < REVEAL_RATIO_MIN) \
                or (_tap_rc not in _cells_now)
            if _fogged:
                # ⭐⭐⭐ 2026-10-02（C，用户报「规划错了」）**雾格空转要记账**：
                #   原来这条只记一行日志（"未揭示格点不动=正常"）⇒ 计划若整条都点在雾上，
                #   下一轮 `PLAN_ONCE` 还会**沿用同一份错计划**（真机 23:30 那把就是：
                #   `plan_reused left=2` + 两轮全 `fogged_noop` ⇒ 0 进展 ⇒ 卡死）✗
                #   ⇒ 记一个**跨轮连续计数**；连续 ≥2 轮都点雾 ⇒ 强制重算计划（见 PLAN_ONCE 处）✓
                st['fog_noop_streak'] = st.get('fog_noop_streak', 0) + 1
                log.append({'tap': 'fogged_noop', 'at': (cx, cy),
                            'cell': '%d,%d' % _tap_rc,
                            'ratio': _ratio, 'streak': st['fog_noop_streak'],
                            'note': '未揭示格点不动=正常 ⇒ 不计 nochange ✓'})
            else:
                st['fog_noop_streak'] = 0        # ⭐ C：有真实反应 ⇒ 计数清零 ✓
                entry.setdefault('tap_no_change', 0)
                entry['tap_no_change'] += 1
                # ⭐ 2026-09-26：**按格**记「点了画面完全没反应」
                _nc[(cx, cy)] = _nc.get((cx, cy), 0) + 1

        else:
            # ⭐⭐⭐ 2026-10-03 提速（用户口径「看看还有地方能省下来么」）：
            #   **点的是"纯空地"⇒ 不可能弹面板 ⇒ 省掉这次条带 OCR** ✓
            #   依据（游戏规则 + 项目自己的注释）：
            #     · 空地（草地/沙地/雪地/岩地/海底，见 `PLAIN_NAMES`）点了**只会连锁揭格** ✓
            #     · 会弹面板的只有**内容格/标记格/商人/宝库/预言石板**（`LEARN_TILES` 段也写着
            #       "判据必须是认到面板文字" ⇒ 空地没有面板文字 ✓）
            #   实测收益（acc1 134 张的长跑分账）：`tap` 条带 OCR 3.7s/图（5.1 次）
            #     ⇒ 其中多数是空地 ⇒ **省 ~2~3s/图（≈8~10%）** ✓
            #   ⚠ 安全网：真要有意外面板没被这次跳过漏掉，**下一轮轮首的全屏 OCR**
            #     照样会认到并处理 ✓（那一次从没砍过 ✓）
            _is_plain_tap = False
            try:
                _is_plain_tap = bool(_sid_tap and _sid_tap != '?' and is_plain_spot(_sid_tap))
            except Exception:               # noqa: BLE001
                _is_plain_tap = False
            if _is_plain_tap:
                it2 = []
                st['tap_ocr_skipped'] = st.get('tap_ocr_skipped', 0) + 1
                entry['tap_ocr_skip'] = st['tap_ocr_skipped']
            else:
                # ⭐ 2026-09-26：上界 980 → **1080**（「获得新装备！」标题实测在 y≈992，
                #   卡在条带外 ⇒ 认不到 ⇒ 循环对着弹窗继续点 ✗）。只多 100px（+12% 高度）✓
                it2 = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1080)), tag='tap')
            # ⭐⭐⭐ 2026-10-01 真机修（用户报「识别到宝库，但点开**瞬间就关掉了**，
            #   后面乱点」）：上面这条 band 到 1080 就断，而**宝库面板的签名**
            #   （右下「购买/选择奖励/离开」按钮）在真机上落在弹窗系 1330~1650
            #   ⇒ 归一化帧 ≈1121~1441 ⇒ **整条签名在 band 之外** ⇒ `panel_seen(it2)`
            #   认不出宝库 ⇒ 循环不 break，继续按点序点下一格 ⇒ 那一击正落在
            #   宝库面板按钮/关闭区 ⇒ **面板被自己的下一次点击关掉** ✗✗（"瞬间"就是这个）
            #   ⇒ 补一条**只在弹窗帧上判宝库**的检查（`_dlg_btn_sig`，零额外代价：
            #     dlg 帧条目本来就要取，且只在"点完画面变了"这条路径上做一次 ✓）
            try:
                _dts = dlg_ocr(b, tag='tap_dlg')
                if _dts and (vault_title_seen(_dts) or _dlg_btn_sig(_dts, 'vault')):
                    hit = ('tap', cx, cy)
                    done.add((cx, cy))
                    entry['panel_via'] = 'vault_dlg'
                    log.append({'tap': 'vault_panel_by_dlg', 'at': (cx, cy),
                                'btn_zone': [(i.get('cx'), i.get('cy'),
                                              (i.get('text') or '')[:6])
                                             for i in _dts
                                             if 700 < i.get('cx', 0) < 1040
                                             and 1300 < i.get('cy', 0) < 1680][:4]})
                    say('       · 点 (%d,%d) → 弹出**黄金宝库**' % (cx, cy))
                    # ⭐⭐⭐⭐ 2026-10-05 **就地买掉它**（用户：「修了个寂寞，还是打开黄金宝库
                    #   就关了，根本没购买」／「既然规划都点了宝库，肯定是规划知道这个是
                    #   已揭示能点的，什么东西不认可规划的判断？」）
                    #   真机铁证（`runs/loop/loop_log.json` 第 3 张图 126→131）：
                    #     126 round4：`taps` 里 `["5,7", 5.1, true, "S30001_016", 1]`
                    #                  ⇒ **确实点开了黄金宝库** ✓ `panel_via=title`
                    #     128 round5：**`ocr: skip_no_panel`**（判"无面板" ⇒ 免整屏 OCR）
                    #     131       **`finish: blank_board`** ⇒ 收工，**宝库没买** ✗
                    #   根因（两条叠加，都是"面板弹出来后没人接"）：
                    #     ① 这里原来**只 `break`**，把控制权交给**下一轮**的 `popups()`；
                    #     ② 而下一轮轮首的 `_panel0 = board_hidden(_cells_cached(b, img…))`
                    #        用的是**点开宝库之前那一帧**（`b.img()` 返回内存缓存帧，
                    #        轮内点击不会刷新它）⇒ 判"没面板" ⇒ **免 OCR**、**也不调
                    #        `popups()`** ⇒ 那个宝库面板**从来没人处理** ✗✗
                    #   ⇒ 现在：认到宝库面板就**当场走 `buypanels.vault_flow()`**（和
                    #     `popups()` 里那条路**同一个函数**，行为一致 ✓），买完继续点序 ✓
                    #   ⚠ 必须包 try/except：`vault_flow` 一崩就抛到上层 ⇒ 面板留在屏幕上
                    #     没人管 ⇒ 后面每一击都落在面板上（用户报过的"乱点" ✗）
                    _vok2 = False
                    try:
                        _vacts2 = buypanels.vault_flow(b, log)
                        _vok2 = bool(_vacts2)
                    except Exception as _ve2:     # noqa: BLE001
                        import traceback as _tb2
                        log.append({'vault': 'flow_error_tap', 'e': repr(_ve2)[:120],
                                    'trace': _tb2.format_exc().splitlines()[-3:]})
                        say('       · ⚠ 宝库流程异常：%r ⇒ 交给下一轮重试' % (_ve2,))
                    if _vok2:
                        STATS['vaults'] += 1
                        say('       · 宝库已购买 ✓（就地处理，不再等下一轮）')
                    break
            except Exception:       # noqa: BLE001
                pass
            # ⭐ v0.35：撤掉 tap_ocr 诊断日志（校准使命已完成：FIGHT_Y=735 已钉死；
            #   用户 09-29 要求去掉）。⚠ **OCR 本体保留** —— it2 是偶遇强敌/获得新装备/
            #   预言石板/发现莱姆的唯一判据，删了这些面板就全瞎了 ✗
        # ⭐ 2026-09-27：点完回报"连锁 or 面板"⇒ 边跑边学空地判据 ✓
        #   ⚠ 判据必须是"**认到面板文字**" ✓ 不能只看"画面有变化"✗
        #     （点空地连锁也会让画面变化 ✗ 我第一版就是这么写错的 ✗
        #      实测把草地 S00003_001 学成了 panel ✗ ⇒ 计划绕开草地 ✗）
        if LEARN_TILES:
            try:
                _sid_now = ''
                if st.get('last') and c.get('st'):
                    _tc2 = cell_of(st['last'][0], st['last'][1])
                    _sid_now = str((c['st'].get(_tc2) or {}).get('sid') or '')
                if _sid_now:
                    _ptxt = ' '.join((i.get('text') or '') for i in (it2 or []))
                    _has_panel = any(k in _ptxt for k in
                                     ('战斗事件', '探索产出', '探索配队', '选择奖励',
                                      '一键派遣', '开始探索'))
                    if changed is not None:
                        import mapsim as _ms2
                        _ms2.learn_tile(_sid_now, plain=not _has_panel)
                        log.append({'learn_tile': _sid_now,
                                    'as': 'panel' if _has_panel else 'plain'})
            except Exception:       # noqa: BLE001
                pass

        # ⭐ 2026-09-25 用户报「综合那个被遭遇强敌卡住了」：**点完这一下必须检查
        #   「偶遇强敌 / 遭遇强敌」和「发现莱姆」** —— 原来这两个不在检查列表里，
        #   于是循环对着面板继续点（把下面的点击全点到面板按钮上）= 卡住 + 乱点。
        #   这里就地关掉（强敌点右上角 X；莱姆点返回），然后继续点序里的下一格。
        if fb(it2, *L['strong']):
            x = find_x(it2)
            if x:
                b.tap(x['cx'], x['cy'], wait=1.5)
            else:
                close_x_panels(b, b.img())
            log.append({'tap': 'strong_closed', 'at': (cx, cy),
                        'closed_at': (x['cx'], x['cy']) if x else None})
            say('       · 点 (%d,%d) 弹出「偶遇强敌」→ 不打，关掉' % (cx, cy))
            continue
        # ⛔ 2026-10-02 收窄（用户当场发现回归：「怎么刚进图就找莱姆了」）：
        #   这里在**点序中途**（每点一格都走这段）⇒ 判据必须**最严**：
        #   ⛔ **绝不用 `panel_seen` / `is_reward_panel` 兜底** ——
        #     那些判据在正常地图界面也常成立 ⇒ 会每格都去点写死坐标
        #     ⇒ 规划/点序被反复打断（这正是用户看到的现象）✗✗
        #   ⇒ 只认 OCR 读到的「莱姆」标题；读不出就跳过，下一轮 `popups()` 全屏
        #     OCR 还会再兜一次（那里的判据是原有代码，没被我改宽）✓
        #   ⛔⛔ 2026-10-12：**这条就是本次 bug 的现场**（用户报「为什么会出现
        #     获得莱姆的点击」✗）—— 点开 `5,4 预言石碑` ⇒ 弹**预言石板面板**，
        #     面板上的「元素」预言卡正文含「莱姆」⇒ 旧子串判据命中 ⇒
        #     点写死的 `lime_back()=(359,873)` ⇒ **连点 4 次空点** ⇒ 脱困+崩 ✗
        #     ⇒ 改走 `_lime_popup_title`（**独立成条**，正文长句不命中 ✓）
        if _lime_popup_title(it2) is not None:
            lb2 = lime_back(it2)
            if lb2:
                b.tap(lb2['cx'], lb2['cy'], wait=1.5)
                log.append({'tap': 'lime_back', 'at': (cx, cy), 'fixed': True})
                say('       · 点 (%d,%d) 弹出「发现莱姆」→ 点返回' % (cx, cy))
            continue
        # ⭐「获得新装备！」（2026-09-26）：点到大拇指/莱姆点时弹，就地关掉再点下一格
        if close_newequip(b, it2, log, 'tap', at=(cx, cy)):
            say('       · 点 (%d,%d) 弹出「获得新装备！」→ 点返回' % (cx, cy))
            continue
        # ⭐「预言石板」（2026-09-26 用户要求）：点出它就关掉，并**拉黑这格不再点** ✓
        #   ⚠ 面板标题可能不在条带(y130~1080)里 ⇒ 这里只当**快路径**；漏了下一轮
        #     `popups()` 的全屏 OCR 还会兜住（那里也会关 + 拉黑 ✓）
        #
        # ⛔⛔⛔ 2026-10-10 **修「点开预言窗口就直接关了」**（用户报，第二处漏改 ✗）
        #   ---- 病 ----
        #     我 10-10 只改了 `popups()` 里那一处（加了 `not _is_stele` 守卫），
        #     **漏了点击循环里这一处、以及 `final_collect` 里那两处** ✗
        #     真机铁证 `runs/acc1/gui_20261010_203354_acc1.log:85`：
        #         `· 点 (456,1100) 弹出「预言石板」→ 关掉并拉黑这格`
        #     （这条消息**带坐标** ⇒ 正是本处，不是 `popups()` ✓）
        #     ⇒ 面板**根本没进 `foretell_flow`** 就被 `universal_close` 关掉 + 拉黑 ✗✗
        #   ---- 这是 README 早记过的同一句教训（手机端 v1.63）----
        #     「**我前几轮一直在修 `popups()` 那条链，而真正吃掉这一格的是
        #       `final_collect()` 这条完全独立的路径**」
        #     ⇒ **同一个错我又犯了一次** ⇒ 必须**三处一起改** ✓
        #   ---- 修法 ----
        #     `预言石碑`（面板名 `预言石板`）**不在这里处理** ⇒ 留给下方 `popups()` 那支
        #     （它会走 `foretell_flow`：选卡 → 点确定 → 拿预言 ✓）
        #     ⚠ 用一个**共用判据** `_is_foretell_panel(...)`（三处同源 ⇒ 不会再漏 ✓）
        if fb(it2, *L['prophecy']) and not _is_foretell_panel(it2):
            universal_close(b, log, items=it2, probe=L['prophecy'][0], where='tap',
                            at=(cx, cy))
            block_cell(log, st, (cx, cy), 'prophecy')
            say('       · 点 (%d,%d) 弹出「预言石板」→ 关掉并拉黑这格' % (cx, cy))
            continue
        if (cx, cy) in progress_set:
            st['clear_clicks'] = st.get('clear_clicks', 0) + 1
            tapped_progress = True
        # ⭐ v0.33：原来只认面板**标题** ⇒ 真机高分辨率上标题落在弹性区看不见
        #   ⇒ 判不成"弹了面板" ⇒ 主循环带着面板继续点后面的格（点击全落到面板上 ✗）
        #   ⇒ 改用 panel_seen()（补"弹窗系独立按钮"这条判据，PC 行为不变 ✓）
        if panel_seen(it2, b=b):
            hit = ('tap', cx, cy)
            done.add((cx, cy))
            # ⭐ v0.33 诊断：记下是"认到标题"还是"靠弹窗系按钮"判成的（真机只会是后者）
            _via_title = bool(
                fb(it2, L['fight'], L['expl'], *L['claim'])
                or fb(it2, *L['desc']) or fb(it2, *L['special']))
            entry['panel_via'] = 'title' if _via_title else 'dlg_btn'
            say('       · 点 (%d,%d) → 弹面板' % (cx, cy))
            # ⭐⭐⭐⭐ 2026-10-05 **就地买掉它**（用户：「修了个寂寞，还是打开黄金宝库
            #   就关了，根本没购买」／「既然规划都点了宝库，肯定是规划知道这个是
            #   已揭示能点的，什么东西不认可规划的判断？」）
            #   真机铁证（`runs/loop/loop_log.json` 第 3 张图 126→131）：
            #     126 round4：`taps` 里 `["5,7", 5.1, true, "S30001_016", 1]`
            #                  ⇒ **确实点开了黄金宝库** ✓ `panel_via="title"`
            #                  （就是**这一支**认到的：`fb(it2, *L['special'])`，
            #                    而 `L['special']` 含「黄金宝库」✓）
            #     128 round5：`ocr: skip_no_panel`（判"无面板" ⇒ 免整屏 OCR）
            #     131       `finish: blank_board` ⇒ 收工，**宝库没买** ✗✗
            #   为什么"下一轮 popups() 会接住"这个假设不成立：下一轮轮首用
            #     `_c0 = _cells_cached(b, img…)` + `board_hidden(_c0)` 判面板，
            #     而**那一判据在宝库面板帧上算出了 False**（真机实测；帧未落盘，
            #     无法离线复现，但 `ocr: skip_no_panel` 就是它的直接输出）
            #     ⇒ **免 OCR、也不调 `popups()`** ⇒ 宝库面板**从来没人处理** ✗
            #   ⇒ 现在：**认出是宝库面板就当场买**（和 `popups()` 里那条走**同一个
            #     `buypanels.vault_flow()`** ⇒ 行为完全一致 ✓），买完 `break` 去收尾。
            #   ⚠⚠ **只对"确认是宝库"动手** —— 绝不在这里调 `popups()`：
            #     它末尾有 `find_x()` **无条件盲点 X** 的兜底（5896 行），
            #     而宝库面板一旦没被认成宝库就会被那条**X 掉** —— 那正是用户报的
            #     **「打开黄金宝库就关了」** 本身 ✗✗ 不能引入这个风险。
            #   ⚠ 必须包 try/except：`vault_flow` 一崩就抛到上层 ⇒ 面板留在屏幕上
            #     没人管 ⇒ 后面每一击都落在面板上（用户报过的"乱点" ✗）
            try:
                # ⚠ 判据 = **只认宝库**（绝不吃别的面板 ⇒ 不引入"误买/误关"的风险）：
                #   · `fb(it2,'黄金宝库')` —— 归一化帧里真能读到标题时的硬证据 ✓
                #   · 或 `it2` 里同时出现「宝库」类按钮字（购买/选择奖励/离开/解锁宝库）
                #     且**不是**旅行商人那套（商人没有「选择奖励」这种字样）
                _t2s = ' '.join((i.get('text') or '') for i in (it2 or []))
                _is_vault_panel = bool('黄金宝库' in _t2s
                                       or ('宝库' in _t2s and '解锁' in _t2s))
                _vault_btn = bool(any(k in _t2s for k in ('选择奖励', '解锁宝库'))
                                  or ('购买' in _t2s and '解锁' in _t2s))
                # ⭐⭐⭐⭐⭐ 2026-10-06 **金币 < 50 万 ⇒ 这里也只关不买**（用户报的真漏口）
                #   ⛔ 真机铁证（acc3 第 7 张图，`runs/acc3/gui_20261006_002420_acc3.log`）：
                #      · 金币 None < 500000 ⇒ 商人/宝库 **不买也不规划**（1,5）✓   ← 闸门"生效"了
                #      · 点 (456,716) → **黄金宝库面板** ⇒ 就地购买 ✓              ← 却照样买 ✗
                #   根因：这一支是**独立于 `popups()` 的第五条路** ——
                #     `popups()` 那道闸门（`buy_skip_low_gold`）只管"面板**已经开着**、
                #     且被 `popups()` 认出来"的情形；而这里是在**点击循环里就地**
                #     认出宝库面板并当场买 ⇒ 完全没查金币 ✗
                #   ⚠ 门禁 `verify_gold_gate.py` 的 ④ 曾断言 `'gold_enough' in _one` ——
                #     `_one` 是整个 `one_round()` 函数体，而函数里**别处**就有 `gold_enough`
                #     ⇒ **假绿**（这正是"门禁全绿 ≠ 没病"的又一例 ✗）
                #   ⇒ 现在：金币不足 ⇒ 走 `ensure_closed` **只关面板**（不买 ✓），
                #     然后 `break` 去收尾（与下面"买完 break"同一语义 —— 面板刚被处理过，
                #     本轮的棋盘观测已失效 ⇒ 交给下一轮重新识别，别接着按旧计划点 ✓）
                #   ⚠ 读不到金币 ⇒ `gold_enough_locked` = True ⇒ 照常买（fail-open ✓）
                if (_is_vault_panel or (_vault_btn and '宝库' in _t2s)) \
                        and not gold_enough_locked(st):
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    log.append({'vault': 'skip_low_gold_inline', 'at': (cx, cy),
                                'gold': (st or {}).get('gold_locked')
                                if isinstance(st, dict) else None,
                                'min': GOLD_MIN_BUY,
                                'texts': [_t[:10] for _t in _t2s.split()][:14],
                                'note': '金币不足 ⇒ 就地认出宝库面板也**只关不买** ✓'})
                    say('       · 点 (%d,%d) → 黄金宝库面板，但金币 %s < %d '
                        '⇒ **只关面板不买** ✓'
                        % (cx, cy,
                           (st or {}).get('gold_locked') if isinstance(st, dict) else None,
                           GOLD_MIN_BUY))
                    break
                if _is_vault_panel or (_vault_btn and '宝库' in _t2s):
                    log.append({'tap': 'vault_panel_inline', 'at': (cx, cy),
                                'btn': _vault_btn, 'via_title': _via_title,
                                'texts': [_t[:10] for _t in _t2s.split()][:14]})
                    say('       · 点 (%d,%d) → **黄金宝库面板** ⇒ 就地购买 ✓' % (cx, cy))
                    _vok2 = False
                    try:
                        _vacts2 = buypanels.vault_flow(b, log)
                        _vok2 = bool(_vacts2)
                    except Exception as _ve2:     # noqa: BLE001
                        import traceback as _tb2
                        log.append({'vault': 'flow_error_tap', 'e': repr(_ve2)[:120],
                                    'trace': _tb2.format_exc().splitlines()[-3:]})
                        say('       · ⚠ 宝库流程异常：%r ⇒ 交给下一轮重试' % (_ve2,))
                    if _vok2:
                        STATS['vaults'] += 1
                        say('       · 宝库已购买 ✓（就地处理，不再等下一轮）')
            except Exception as _ei:      # noqa: BLE001
                log.append({'vault': 'inline_check_err', 'e': repr(_ei)[:140]})
            break
            # ===== 2026-10-28 买完立刻进 done + 摘掉永不拉黑记忆 =====
            # 用户第 3~4 次反馈（原话）：「怎么旅行商人买完后还是会点开？我记得这个问题我反馈了三四次了」
            #
            # 为什么前几次都没根治（这次把整条链读完了）：
            #   买完那格的"已买"只记进 bought_done / merchant_done，
            #   但**点序准入判据根本不看这两个集合**，它看的是：
            #     cands = [x for x in order if x not in done
            #               and (x in marked_px or x in buy_px or cold.get(x,0) < 2)]
            #   而 buy_px = set(buy) | set(buy_hidden) | set(sticky)
            #                | set(st[buy_seen]) | set(_probe_px)    <- 五条来源
            #   => 商人格**永远在 buy_px 里**（buy_seen/sticky 跨轮记忆一直记着它）
            #   => cold>=2 => done 那条**被 x not in buy_px 挡住**（永不拉黑口径）
            #   => 只要某轮 panel_seen() 没认出面板（动画/时机，实测会发生）
            #      就走 cold+1 分支 => 那格**既不进 done、又一直在点序里**
            #   => 下一轮重新排进计划 => **再点一次**
            # 关键：done 只被"认出面板"那条路写；"没认出面板"那条路被 buy_px 保护着
            #       => 两条路都不覆盖它 => 它成了漏网格
            #
            # 修法：买完那一刻就主动收尾
            #   ① done.add(那格)                    —— 本图不再点它
            #   ② 从 buy_seen / buy_sticky 里摘掉   —— 它们只该表示"还没买到"
            # 不动 bought_done / merchant_done（那是"买过"的账本，另有 prune 负责）
            # 只对真的买成功做；没买成要留着重试
            try:
                if act == 'handled' and (cx, cy):
                    _rc_b = cell_of(cx, cy)
                    _bought_rc = set()
                    for _s in (st.get('bought_done') or set()):
                        try:
                            _bought_rc.add(tuple(cell_of(int(_s[0]), int(_s[1]))))
                        except Exception:       # noqa: BLE001
                            continue
                    _bought_rc |= set(st.get('merchant_done') or set())
                    if _rc_b in _bought_rc:
                        done.add((cx, cy))
                        st.get('buy_seen', {}).pop((cx, cy), None)
                        st.get('buy_sticky', {}).pop((cx, cy), None)
                        log.append({'merchant': 'bought_done_now',
                                    'cell': '%d,%d' % _rc_b, 'at': (cx, cy),
                                    'note': '买完立刻进 done + 摘掉永不拉黑记忆 ✓'})
                        say('       · 商人/宝库 (%d,%d) 已买过 ⇒ 本图不再点它 ✓' % _rc_b)
            except Exception as _enb:       # noqa: BLE001
                log.append({'merchant': 'bought_done_now_err', 'e': repr(_enb)[:120]})
        cold[(cx, cy)] = cold.get((cx, cy), 0) + 1
        if cold[(cx, cy)] >= 2 and (cx, cy) not in marked_px \
                and (cx, cy) not in buy_px:
            done.add((cx, cy))
        # ⭐ 2026-09-26（用户报「综合乱点」）：同一格**点了没反应**也要计数拉黑 ✱
        #   原来只有 cold 计数，而 **marked（标记格）/ buy（商人宝库）被"永不拉黑"保护**
        #   ⇒ 面板盖着棋盘、它又点不动时 ⇒ **每轮点同一格**，实测连点 5 轮
        #   （日志 `tap_no_change:1, tried:1, clear_clicks:3` ×5）⇒ stuck⇒no_progress ✗
        #   ⇒ 现在：同一格累计 3 次「点了没反应」⇒ 本轮拉黑，下一轮不再点它 ✓
        if _nc.get((cx, cy), 0) >= 3:
            done.add((cx, cy))
            log.append({'tap_no_change_blacklist': '%d,%d' % (cx, cy),
                        'n': _nc[(cx, cy)]})
        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**应该只需要在退图前扫一次确认有没有莱姆或者
        #   新装备吧？三轮纯浪费**」⇒ 计划里"点了不消耗"的步**试过就摘掉**，不再每轮重试 ✓
        #   为什么原来会反复：受保护的格（**标记格 / 商人宝库**）被上面那句
        #   `not in marked_px and not in buy_px` 排除在 `cold>=2 ⇒ done` 之外
        #   （用户口径"永不拉黑"✓）⇒ 于是它**每轮都被重新排进点序** ⇒ 真机日志连着
        #   3 轮「计划还剩 1 步（1 步现在可点）」，每轮 marks 2.0s + 分类 0.5s + 点击 ≈4s ✗✗
        #   ⇒ 现在：**不拉黑它**（保持"永不丢"口径 ✓，下一张图照样会重排），
        #     但**从本图 `st['plan']` 里摘掉这一步** ⇒ 计划走完 ⇒ 正常收图 ✓
        #     （退图前 `finish_map`/`final_collect` 本来就会扫一次奖励弹窗 ⇒ 不会漏莱姆/新装备 ✓）
        try:
            # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「既然点了不消耗的步全删了不影响退图流程，
            #   **就全删了**」⇒ **试过一次就摘**（不再等第 2/3 次）✓
            #   安全性：这一段本身就是"**没弹面板**"的那条路 ⇒ 要么是被连锁消耗了（该摘 ✓）、
            #     要么是真没反应（也该摘 ✓）；退图前 `finish_map`/`final_collect`
            #     仍会扫一次奖励弹窗 ⇒ 不会漏莱姆/新装备 ✓
            #
            # ⛔⛔⛔ 2026-10-11 **但"带标记"的格不许摘**（治「68 张图只打 62 个首领」第二半 ✗）
            #   ---- 病（真机铁证 第 19/41/65 张，三张**全都没打到 boss** ✗）----
            #       #1109 board marks {"4,1": ["boss"]}          ← **标记扫描认出了 boss** ✓
            #       #1118 tap fogged_noop cell 4,1 ratio 0.222  ← 分类器却判它是**雾** ✗
            #       #1119 plan give_up_step cell 4,1             ← 于是"试过就摘" ✗
            #       #1125 stuck_why targets_unreachable  marked_n 1
            #       #1126 finish targets_unreachable             ⇒ **退图，boss 没打** ✗✗
            #     全盘复算：**3 张**图有这现象，**3 张全都没打到 boss** ✓
            #   ---- 为什么必须信"标记"而不是"雾" ----
            #     · 标记（`marks`）是**模板匹配**打上的 ⇒ 见到就是见到（硬证据 ✓）
            #     · `ratio=0.222` 是**亮度比**判"雾"⇒ 会被压暗/遮挡/渐显动画骗到（软判据 ✗）
            #     ⇒ 两者矛盾时**信标记**；大不了多点一次
            #       （本段是"没弹面板"那条路 ⇒ 多点一次最多白花 1 体力，
            #        远好过"整张图不打 boss 就退"✗✗）
            #   ⚠ **不拉黑**（保持"永不丢"口径 ✓）⇒ 只是**不从计划里摘**，
            #     下一轮它还会被排进点序 ⇒ 雾散后自然能点到 ✓
            if True:
                _rc_g = cell_of(cx, cy)
                if (cx, cy) in marked_px:
                    # 带标记 ⇒ **保留这一步**（如实记日志，别静默 ✗）
                    # ⚠⚠ `st['marks']` 的键是 **(row,col) 元组**！
                    #   （铁证：`marks.scan_board` 的 docstring 写着
                    #     `-> {(row,col): {'marks': [...], ...}}` ✓）
                    #   我第一版写成 `'%d,%d'` **字符串** ⇒ 永远取不到 ⇒
                    #   **保护完全失效** ✗（幸好真机数据复算时发现 ✓）
                    _mkcell = tuple(_rc_g)
                    _mkl = list((st.get('marks') or {}).get(_mkcell) or [])
                    log.append({'plan': 'keep_marked_step', 'cell': '%d,%d' % _rc_g,
                                'marks': _mkl,
                                'note': '带标记的格**不摘**（标记是硬证据；雾是软判据 ✓）'})
                    say('       · 点 (%d,%d) 没反应，但它**带标记**（%s）⇒ '
                        '**保留这一步**（可能是雾没散，下轮再试 ✓）'
                        % (cx, cy, '/'.join(_mkl) or '?'))
                else:
                    # ⭐ 2026-10-03：摘掉的步要**记住**（`plan_given_up`）——
                    #   否则下一轮重算出同样的步 ⇒ 又立刻摘掉 ⇒ 一步没点、无限循环 ✗✗
                    #   （真机日志：每轮都刷 4 条"已试过 ⇒ 摘掉这步"，然后 0 进展）
                    try:
                        st.setdefault('plan_given_up', set()).add(tuple(_rc_g))
                    except Exception:       # noqa: BLE001
                        pass
                    _pl_g = list(st.get('plan') or [])
                    if _rc_g in _pl_g:
                        _pl_g.remove(_rc_g)
                        st['plan'] = _pl_g
                        # ⚠ 2026-10-03 用户口径：「**日志不用写这个吧**」⇒ 控制台**不再逐格刷**
                        #   （原来每摘一步就 `say` 一行，正常图也会刷 4 行噪声 ✗）
                        #   只留结构化记录（在 loop_log 里，排查时才看 ✓）
                        log.append({'plan': 'give_up_step', 'cell': '%d,%d' % _rc_g,
                                    'nochange': int(_nc.get((cx, cy), 0)),
                                    'cold': int(cold.get((cx, cy), 0)),
                                    'note': '试过一次就摘（不拉黑、下张图重排 ✓）'})
        except Exception:           # noqa: BLE001
            pass
    entry['tried'] = tried
    entry['clear_clicks'] = st.get('clear_clicks', 0)
    entry['explore_clicks'] = st.get('explore_clicks', 0)   # ⭐ 探图预算（诊断用）
    # ⭐⭐ 整轮"点了都没反应" ⇒ 十有八九是**盖着面板** ⇒ 连续 2 轮就清面板/脱困，
    #   别再下一轮盲点（原来要等到 stuck>=4 才退图，中间全是白点 ✗）
    if entry.get('tap_no_change', 0) >= 1 and not hit:
        st['nochange_rounds'] = st.get('nochange_rounds', 0) + 1
        if st['nochange_rounds'] >= 2:
            n = close_x_panels(b, b.img())
            if not n:
                x = find_x(b.ocr(tag='nochange'))
                if x:
                    b.tap(x['cx'], x['cy'], wait=1.5)
                    n = 1
            if not n:
                # ⭐⭐ v0.34：连着两轮"点了没反应" + 关不掉 ⇒ 多半是**认不出类型的面板**
                #   （真机上标题落在归一化帧丢弃的弹性区：偶遇强敌/旅行商人/预言石板/…）
                #   ⇒ 补一次**弹窗帧** OCR（≈2s，只在真的卡住时）认类型再按类型处理 ✓
                _dp = dlg_ocr(b, tag='nochange_dlg')
                if _dp:
                    _OCR_CH['dlg'] = True      # ⭐ 同上：_dp 是弹窗系
                    try:
                        _act3 = popups(b, _dp, log, ctx={'in_dlg': True,
                                                         'flags': st,
                                                         'tapped': st.get('last'),
                                                         'marks': st.get('marks') or {},
                                                         'st': st.get('cells')})
                    finally:
                        _OCR_CH['dlg'] = False
                    log.append({'popup': 'dlg_frame_retry_nochange',
                                'n_items': len(_dp), 'act': _act3,
                                'texts': [(i.get('text') or '')[:10] for i in _dp][:26]})
                    if _act3 in ('battle', 'battle_clear', 'handled'):
                        n = 1
            if not n:
                force_unstick(b, log, 'tap_no_change',
                              ctx={'tapped': st.get('last'), 'flags': st})
            log.append({'tap': 'nochange_unstick', 'closed': n,
                        'rounds': st['nochange_rounds']})
            say('       · 连续 %d 轮点了没反应 ⇒ 清面板/脱困（closed=%d）'
                % (st['nochange_rounds'], n))
            status('点了没反应 · 正在脱困')
            st['nochange_rounds'] = 0
    else:
        st['nochange_rounds'] = 0
    if hit or tapped_progress:
        if hit:
            entry['hit'] = hit
        st['stuck'] = 0
    else:
        st['stuck'] += 1
        entry['stuck'] = st['stuck']
        if st['stuck'] >= 4:
            log.append(entry)
            log.append(_stuck_why(st, c, rnd, {'stuck_why': 'no_progress',
                                              'hit': bool(hit),
                                              'tapped_progress': bool(tapped_progress)}))
            log.append({'finish': 'no_progress'})
            return 'stuck'
    # ⭐⭐⭐ 2026-10-03 **退图判定挪到这里（点击循环之后）** —— 用户口径：「就按这个做」：
    #   "计划里还有步" 这件事**由点击循环消费掉**，而不是由一个前置闸门决定退不退图 ✓
    #   放在这里的好处：
    #     · 计划的步该点的都点过了（点了没反应的雾格也已经试过）⇒ 再判"真没得干"才退 ✓
    #     · 回合中途弹面板/被 `return 'handled'`/`battle` 截断时**根本走不到这里** ⇒
    #       不会像原来那样"面板还没处理完就判退图" ✓
    #   ⚠ 已删除的补丁：`_plan_left_now` / `keep_going`（只是绕过结构问题，
    #     副作用是"剩余步是雾格时白耗 2~3 轮"）✓
    if vis and rnd >= 2 and not marked and not pending_buy:
        # ⭐⭐⭐⭐ 2026-10-05 **退图前先确认"那一刻没有面板正在渲染"**
        #   （用户报「**修了个寂寞啊，和之前一模一样，没打探索格**」）
        #   真机铁证（`runs/acc1/_ocr_tmp.png`，点开紫格 `(3,1)` 之后**当时那一帧**）：
        #     画面里**只有 5 条文字**（体力 2601802/510/598、图名 `夏日海滩[100]`、`RTNl`），
        #     **面板一个字都没有** —— 但棋盘**已经被压暗**了（= 面板正在弹，美术还没画完 ✓）
        #     ⇒ `panel_seen(it)` 返回 **False**、`fb(items, '探索产出'/'探索')` 全 False ✗
        #   于是：本轮 `popups()` 读不到面板 ⇒ **什么都没做**；
        #     下一轮开头面板已经画好了，可它已经没有"刚点过"的上下文 ⇒ 被当普通棋盘
        #     ⇒ 这一格既没打探索、也没弹面板记录 ⇒ 走到这里 `not marked and rnd>=2`
        #     ⇒ **`targets_done` 直接退图**（真机 `content_skipped: 6`）⇒ **探索格漏了** ✗✗
        #   ⇒ 现在：`st['last']`（上一次点击）存在、且**棋盘被压暗**（`b.dim() < 0.85`）
        #     ⇒ 判"面板还在渲染" ⇒ **本图不判 done**，返回 None 让主循环再转一轮
        #     （下一轮面板画好 ⇒ `popups()` 正常接手 ⇒ 探索/战斗都能走 ✓）
        #   ⚠ 上限防死循环：最多让 3 轮（`st['panel_render_wait']`）✓
        _dim_wait = False
        try:
            _last_tap = st.get('last')
            # ⚠ `dim` 是 `Bot.last_change` 里的**相对压暗比**（`now_luma / ref_luma`），
            #   不是 `Bot.dim()` 方法（没有那个方法 ✗）；拿不到就按 1.0（= 不压暗）✓
            _dim = 1.0
            try:
                _dim = float((getattr(b, 'last_change', None) or {}).get('dim', 1.0))
            except Exception:       # noqa: BLE001
                _dim = 1.0
            _waited = int(st.get('panel_render_wait', 0) or 0)
            if _last_tap and float(_dim) < 0.85 and _waited < 3:
                st['panel_render_wait'] = _waited + 1
                _dim_wait = True
                _tgt_rc = cell_of(_last_tap[0], _last_tap[1])
                log.append(entry)
                log.append({'finish': 'panel_rendering_wait',
                            'cell': '%d,%d' % _tgt_rc, 'dim': round(float(_dim), 3),
                            'wait': st['panel_render_wait'],
                            'note': '棋盘被压暗但面板还没画出来 ⇒ 先不退图，'
                                    '再等一轮让 popups() 接住它 ✓'})
                say('       · 棋盘被压暗（dim=%.2f）但面板还没画出来 ⇒ 先不退图，'
                    '再等一轮 ✓' % float(_dim))
                status('面板正在弹出 · 再等一轮')
                return None
        except Exception:       # noqa: BLE001
            _dim_wait = False
        if not _dim_wait:
            log.append(entry)
            log.append({'finish': 'targets_done', 'gray_left': len(grays),
                        'content_skipped': len(nones_extra),
                        'at': 'after_click_loop',
                        'note': '用户口径：目标没了就退；判定已挪到点击循环之后 ✓'})
            return 'done'
    log.append(entry)
    return None


def scan_bag():
    """把当前屏 OCR 出来并落盘截图（用于标定背包/「使用」按钮坐标）"""
    # ⚠ 2026-10-01 修：这里原来写 `serial=SERIAL`，而 `SERIAL` **从未定义**
    #   （是早期 `INSTANCE_DEV` 的残留名）⇒ 真跑到这个标定入口就 NameError ✗
    b = Bot(log_prefix='scanbag', serial=INSTANCE_DEV, tag=INSTANCE_TAG, use_fast=True)
    b.snap('scanbag', save=True)
    items = b.ocr(min_conf=0.3, tag='scanbag')
    say('当前屏文字 %d 条：' % len(items))
    for i in sorted(items, key=lambda x: (x['cy'], x['cx'])):
        say('   (%4d,%4d) %s' % (i['cx'], i['cy'], i['text'][:36]))
    say('截图已存到 runs/ 目录（scanbag.png）')
    return 0


def _release_lock():
    if _LOOP_LOCK:
        try:
            import loopguard
            loopguard.release(_LOOP_LOCK[0], _LOOP_LOCK[1])
        except Exception:       # noqa: BLE001
            pass


def next_5am(now=None):
    """下一个停止时刻（默认 04:58；今天还没到就今天，否则明天）"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    t = now.replace(hour=STOP_HM[0], minute=STOP_HM[1], second=0, microsecond=0)
    if t <= now:
        t += _dt.timedelta(days=1)
    return t


def past_stop_time():
    """到点了吗（到点就该收工）"""
    import datetime as _dt
    if not STOP_AT_5AM or STOP_TIME is None:
        return False
    return _dt.datetime.now() >= STOP_TIME


def stop_requested():
    """⭐ **立即停止**信号（2026-09-29 用户口径：「停止键点了要立即停止，不要等打完这张图」）

    · 端上（APK）：悬浮条点 ■ ⇒ 广播 ⇒ `explore_android.stop()` ⇒ `android_request_stop()`
      ⇒ `_ANDROID_STOP = True` ⇒ 这里立刻返回 True
    · PC 上 `_ANDROID_STOP` **根本不存在** ⇒ 恒 False ⇒ **行为一字不变 ✓**（零回归风险）
    · 与 `past_stop_time()`（凌晨 5 点 / 两张图之间）的区别：那个**故意**等到图边界，
      这个**每一步都要查**（见 `run_one_map` 的轮首 + 每次点击前）
    """
    return bool(globals().get('_ANDROID_STOP'))


def stop_checked(log=None, where=''):
    """查到停止请求就记一条日志并返回 True（调用方负责立刻 return/break ✓）"""
    if not stop_requested():
        return False
    if log is not None:
        log.append({'stop': 'user_immediate', 'where': where})
    say('⏹ 收到「停止」⇒ %s 立刻收工（不等这张图打完 ✓）' % (where or '',))
    status('收到停止 · 立刻收工')
    return True


def guard_duplicates(device, tag, force=False):
    """⭐ 用户 2026-09-25：启动前查重 —— 同一台模拟器已经有循环在跑就**拒绝启动**

    两道防线见 `loopguard.py`：原子锁（同 tag 抢锁）+ 进程枚举（兜住绕过锁的）。
    `--force` 可以强行启动（调试用）。
    """
    try:
        import loopguard
    except Exception:       # noqa: BLE001
        return True
    try:
        return _guard_duplicates_inner(loopguard, device, tag, force)
    except Exception as ex:     # noqa: BLE001 —— 守卫自身出错就放行，绝不让它拖垮循环 ✓
        import traceback
        say('⚠ 重复循环自检出错（%r），本次直接放行' % ex)
        say('   ' + ' | '.join(traceback.format_exc().splitlines()[-2:]))
        return True


def _guard_duplicates_inner(loopguard, device, tag, force):
    dupes = loopguard.duplicates_for(device, tag, exclude_pid=os.getpid())
    if dupes:
        say('')
        say('⚠ 已经有一个循环在跑同一台模拟器（%s）：' % device)
        for p in dupes:
            say('     PID %-6d 设备 %-20s tag %s' % (p['pid'], p['device'] or '?',
                                                     p['tag'] or '-'))
        if not force:
            say('')
            say('   为避免两边抢点击，这次不启动 ✗')
            say('   · 想停掉旧的：在它的窗口点「停止」，或删掉锁文件后重来')
            say('   · 确实要强开（调试用）：加 --force')
            return False
        say('   --force：仍然启动（可能互相抢点击）')
    ok, info = loopguard.acquire(device, tag)
    if not ok:
        say('⚠ 设备锁被占用：%s' % json.dumps(info, ensure_ascii=False))
        # ⭐ 2026-10-05：把**锁文件路径**一起打出来 —— 真机踩过"PID 被系统回收 ⇒ 明明没人在跑
        #   却一直报占用"，那时用户需要知道**去哪清**（见 loopguard._pid_alive 的注释）
        try:
            say('   · 锁文件：%s' % loopguard.lock_path(device, tag))
            say('   · 若确认那个 PID 已经不是本项目的循环（被系统回收/早就崩了）'
                '⇒ 把上面这个锁文件清空再启动 ✓')
        except Exception:       # noqa: BLE001
            pass
        if not force:
            return False
    globals()['_LOOP_LOCK'] = (device, tag)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-round', type=int, default=45)
    ap.add_argument('--force', action='store_true',
                    help='已有同设备循环时也强行启动（调试用）')
    ap.add_argument('--no-guard', action='store_true',
                    help='跳过重复循环自检（GUI 已查过时用）')
    ap.add_argument('--scan-bag', action='store_true',
                    help='把当前屏 OCR 落盘（标定背包界面用）')
    ap.add_argument('--maps', type=int, default=1)
    ap.add_argument('--deadline', type=int, default=900)
    ap.add_argument('--quiet', action='store_true', help='关掉控制台实时进度')
    ap.add_argument('--no-dump', action='store_true', help='结束时不打印全量 json 日志')
    ap.add_argument('--min-stamina', type=int, default=25,
                    help='进图前体力下限（低于它就收工）；连刷模式用 50')
    ap.add_argument('--bag-every', type=int, default=10,
                    help='每连刷多少张图去背包做一次装备一键升星（0=关闭，默认10）')
    ap.add_argument('--no-solver', action='store_true',
                    help='关掉精确规划（走原来的启发式点序）')
    ap.add_argument('--device', default=None,
                    help='adb 设备号（多开：127.0.0.1:16384 / 16416 / 16448 …）')
    ap.add_argument('--tag', default='',
                    help='多开实例名（隔离截图/日志/统计目录），如 acc1 / acc2')
    ap.add_argument('--auto-supply', action='store_true',
                    help='没体力时自动进背包使用「结实补给」（窗口勾选框用）')
    ap.add_argument('--opt', action='store_true',
                    help='体力最省模式：每轮用 Dijkstra 求最优点序（mapsolve）')
    # ⭐⭐ 2026-09-27 用户要求：「开一个新脚本抓另一个模拟器 —— 只进图截图退图，拿图片快一些」
    ap.add_argument('--collect-only', dest='collect_only', action='store_true',
                    help='采图模式：只「进图 → 存首帧 → 退图」，不揭格/不打怪/不买/不补点'
                         '/不背包升星（拿到最干净的首帧；⚠ 每张图照旧扣 25 体力）')
    a = ap.parse_args()
    # ⭐ 用户 2026-09-25：「加个检测有没有重复的循环进程」
    #   同一台模拟器上已有循环在跑 ⇒ 拒绝启动（两个循环会互相抢点击、抢状态）
    if not getattr(a, 'no_guard', False):
        import atexit
        if not guard_duplicates(a.device or '', a.tag or '',
                                force=getattr(a, 'force', False)):
            return 3
        atexit.register(_release_lock)
    global VERBOSE, DUMP_AT_END, MIN_STAMINA, WIN, LOG_PATH, SUMMARY_PATH, AUTO_SUPPLY
    global INSTANCE_TAG, INSTANCE_DEV, _BOT, STOP_TIME, COLLECT_ONLY
    VERBOSE = not a.quiet
    DUMP_AT_END = not a.no_dump
    MIN_STAMINA = a.min_stamina
    # ⭐ 每 N 张图做一次装备升星（窗口可填 ✓ 默认 10 ✓）
    global BAG_EVERY, OPT_SOLVER   # 必须声明，否则只是局部变量（用户报取消勾选还规划）
    BAG_EVERY = max(0, int(getattr(a, 'bag_every', 10) or 0))
    OPT_SOLVER = not bool(getattr(a, 'no_solver', False))
    say('   · 精确规划：' + ('开 ✓' if OPT_SOLVER else '关（走启发式 ✓）'))
    say('   · 装备升星：' + (('每 %d 张图一次' % BAG_EVERY) if BAG_EVERY else '关闭（0）'))
    global STOP_TIME
    STOP_TIME = next_5am() if STOP_AT_5AM else None
    if STOP_TIME:
        say('⏰ 本次运行到 %s 自动停止（打完手上这张图就收工）'
            % STOP_TIME.strftime('%m-%d %H:%M'))
    AUTO_SUPPLY = bool(getattr(a, 'auto_supply', False))
    global OPT
    OPT = bool(a.opt)
    COLLECT_ONLY = bool(getattr(a, 'collect_only', False))
    if COLLECT_ONLY:
        # 采图模式下这些开关没意义 ⇒ 直接按最省的方式跑，免得误触
        BAG_EVERY = 0
        _tag = (getattr(a, 'tag', '') or '').strip()
        say('')
        say('📷 采图模式（--collect-only）：只做「进图 → 存首帧 → 退图」')
        say('   · 不揭格 / 不打怪 / 不买 / 不补点 / 不背包升星')
        say('   · ⚠ 每张图照旧扣 **25 体力**（进图瞬间扣，退图不退）—— 这是拿体力换图片')
        say('   · 存图目录：%s' % (os.path.join(RUNS, _tag) if _tag else RUNS))
        say('')
    INSTANCE_TAG = (a.tag or '').strip()
    INSTANCE_DEV = a.device or DEV
    # ⭐⭐⭐⭐⭐ 2026-10-13 **把「特殊方块」配置绑到本设备**（用户口径，原话）：
    #   「**把特殊方块，停止规则，多少张图自动升星等需要用户自己选择的自动用最近一次配置
    #     并且和对应窗口绑定（选哪个窗口就自动用对应的配置）**」✓
    #   ---- 病 ----
    #     `targets_cfg` 默认读 `runs/target_types.json`（**全局一份**）✗
    #     ⇒ 开两个窗口（两个号）⇒ **勾选互相覆盖** ✗✗
    #   ---- 修法 ----
    #     GUI 起子进程时用 **`MAPBOT_TARGETS_CFG=<绝对路径>`** 把"本设备那份"传进来；
    #     这里**第一时间** load 它 ⇒ 后面所有 `is_target/is_blocked/enabled` 都走它 ✓
    #     ⚠⚠ **必须在任何 `is_target` 之前**（`_CACHE['path']` 一旦被默认路径填上，
    #       `current()` 就会一直读全局那份 ⇒ 判据静默失效 ✗
    #       —— 本项目反复栽的同一族 bug，见 `v1.62/v1.63/v1.64/v1.71` ✓）
    #     ⚠ 环境变量**没有** ⇒ 保持老行为（读全局那份）⇒ 命令行直跑/老脚本不受影响 ✓
    try:
        _cfg_p = (os.environ.get('MAPBOT_TARGETS_CFG') or '').strip()
        if _cfg_p:
            import targets_cfg as _tc0
            _tc0.load(path=_cfg_p)          # ⭐ 预热 `_CACHE['path']` ⇒ 后续全走它 ✓
            say('特殊方块配置：%s（本设备专属 ✓）' % _cfg_p)
    except Exception as _e_cfg:             # noqa: BLE001
        # ⛔ 本项目铁律：**不许静默失效** —— 读不到要说出来（回落全局也要看得见 ✓）
        say('⚠ 本设备特殊方块配置读取失败（%r）⇒ 回落到全局那份' % (_e_cfg,))
    _lock = acquire_device_lock(INSTANCE_DEV)
    if _lock is None:
        say('⚠ 这台模拟器（%s）已经有另一个自动探索在跑了 —— 同时跑两个会互相抢点击。' % INSTANCE_DEV)
        say('   要强制重跑：先停掉那个窗口，或删掉 %s' % device_lock_path(INSTANCE_DEV))
        return
    # ⭐ 红装锁：上次发现红装还没处理 ⇒ **拒绝启动**，绝不把那一局带走
    #   （用户 2026-09-25：「下次遇到红装要立刻停止，不准退出图」）
    #
    # ⛔⛔ 2026-10-11 **修「不勾选还是自动停了」**（用户报，原话 ✗）
    #   ---- 病 ----
    #     这个锁文件被**多种**"停脚本保现场"共用（`red_lock_path` 只是文件名 ✓）：
    #       · `kind='red_equip'`（红装 —— 本来的用途）
    #       · `kind='shrine'`   （**传承祭坛**，我 2026-10-11 加的[临时]采集停止 ✗）
    #     可**启动提示写死了"发现了红装（SS）"** ⇒ 祭坛锁被**报成红装锁** ✗
    #     真机铁证（用户报的那把，`runs/red_equip_16448.lock.json`）：
    #         {"device":"127.0.0.1:16448","kind":"shrine","map":"废弃矿洞",
    #          "at":"2026-10-11 13:45:59","shot":"shrine_panel_r-1.png"}
    #       ⇒ 脚本却打印「🛑 上次…发现了红装（SS）…请先在游戏里处理掉那件红装」
    #       ⇒ 用户看了一头雾水：「**不勾选还是自动停了**」✗✗
    #     ⚠ 而且那个提示指向「红装已处理·解锁」按钮 —— 那只清红装锁
    #       ⇒ **祭坛锁没有解锁入口**（用户只能手删文件，不合理 ✗）
    #   ---- 修法 ----
    #     按 `kind` **分别报**（红装 / 传承祭坛 / 机巧宝箱怪 / 未知），
    #     并把「怎么解开」写清楚 —— **临时采集锁**只要关掉窗口里那个勾选、
    #     再删文件即可（本来就该由人采完主动清 ✓）
    #     ⭐ 关键：**文案必须如实反映是哪种锁**（不许一律说成红装 ✗）
    # ⛔⛔⛔ 2026-10-12 **删掉整段"停脚本锁 ⇒ 拒绝启动"**（用户原话：
    #   「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
    #   ---- 原来是什么 ----
    #     上次发现红装/要停的预言 ⇒ 写一个锁文件 ⇒ 本处读到就**拒绝启动** ✗
    #     要人去窗口点「红装已处理·解锁」才放行
    #   ---- 为什么删（三层理由）----
    #     ① 用户**明确不要**：锁定是多余的一层，他只要"遇到就停"这个动作 ✓
    #     ② 它带来**真实的麻烦**（本机卡过两次 ✗）：
    #          · `kind=shrine` 被报成"发现了红装"（用户：「不勾选还是自动停了」）
    #          · `kind=foretell` 显示"未知类型"、不给解锁指引（用户：「怎么解除锁定」）
    #     ③ **写锁的地方已经全删了**（红装那条 + 预言那条）
    #        ⇒ 本判据**不可能再命中**（没有任何写入方）⇒ 留着就是死代码 ✗
    #   ⇒ 现在：**只停、不锁** —— 停下来把现场留着，用户处理完**直接再点「开始」** ✓
    #     ⚠ `acquire_device_lock`（上面那个）**保留** —— 它防的是"同一台设备开两个脚本"，
    #       与"停脚本保现场"完全无关 ✓
    # ══════════════════════════════════════════════════════════════════
    # ⭐⭐⭐⭐ 2026-10-15 **收工后自动重开**（用户口径，原话）：
    #   「体力用完后，把勾选的公会日常，免费招募和免广告
    #     （**这三个脚本的最后都要回到地图界面，最开始都要进入公会界面**）
    #     都做完后，检查下体力，如果**超过100**，就**重新启动探图脚本**」
    #   ---- 为什么这层循环放在 `main()`、而不是塞进 `run_maps()` ----
    #     `run_maps` 内部有**一整套收尾状态机**（统计/落盘/日志留档/退图…）
    #     ⇒ 在里面插 `continue` 要同时照顾十几处状态 ✗ 风险很大（本项目吃过大改的亏 ✓）
    #     ⇒ `run_maps()` **一字不改**，在外面**多调几次**它 ✓
    #       每次调用都会重新建 Bot、重新自适应分辨率、重新留档日志
    #       —— 与"用户手动再点一次 ▶ 开跑"**等价** ✓（这正是用户说的"重新启动"✓）
    #   ---- 上限 ----
    #     `_MAX_RELAUNCH`（默认 5）⇒ 防呆。正常只能重开 1~2 次：
    #       广告奖每天只有 3+3+3 次、情报/派遣都是每日一次 ⇒ +600 体力后就没了 ✓
    #     ⚠ 上限到了就**如实报**，不静默继续 ✗
    #   ---- 什么时候**不**重开（每一道都是"重开也没用"）----
    #     · 用户点了停止（`stop_checked` 命中）✗
    #     · `run_maps` 报的是"游戏崩了/起不来"那类硬错 ✗
    #     · 三个勾选**一个都没开** ⇒ 根本没地方拿体力 ⇒ 重开必再收工 ✗
    #       （⚠ 这条最要紧：不然"没体力 + 没勾任何东西"会**空转 5 轮** ✗）
    # ══════════════════════════════════════════════════════════════════
    _MAX_RELAUNCH = 5
    _relaunch = 0
    try:
        while True:
            run_maps(a)
            # ── 这一轮收工了 ⇒ 判断要不要重开 ──
            _relaunch += 1
            if _relaunch > _MAX_RELAUNCH:
                say('   · 已重开 %d 次（上限 %d）⇒ 不再重开 ✓'
                    % (_relaunch - 1, _MAX_RELAUNCH))
                break
            _ok, _why = _should_relaunch(a)
            if not _ok:
                say('   · 不重开：%s' % _why)
                break
            say('')
            say('🔁 **体力够（>%d）⇒ 重新开刷**（第 %d 次重开）'
                % (RELAUNCH_STAMINA_MIN, _relaunch))
            status('体力够 · 自动再刷一轮（第 %d 次）' % _relaunch)
            # ⚠ 重开前**把"停"的标记清掉** —— 否则 `run_maps` 一进去就
            #   被 `stop_checked` / `STATS['stopped']` 当成"该停" ✗
            STATS['stopped'] = ''
            time.sleep(2.0)             # 给游戏一点时间把界面稳住 ✓
    finally:
        release_device_lock(_lock)


def _stop_allows_afterwork():
    """停止原因**允许**做「收工后续」吗？（公会日常 / 免费招募 / 免广告 / 自动重开）

    ⛔⛔⛔ 2026-10-26 **收工日常与自动重开必须用同一份判据**（用户报）
      ---- 用户报告（原话）----
        「🛑🛑 抽到【元素·橙色】⇒ 立即停止（不退图，留着你自己处理）
          › ★ 抽到【元素·橙色】· 已停下，请手动处理。
          **因为预言石碑和红装停止的不要运行收工日常等等**」
      ---- 真机铁证（`runs/gui_20261026_184021.log`，设备 16384，10-26 19:0x）----
        收工日常**确实被正确跳过了** ✓（判据本来就在）：
          「· 停止原因「预言石碑抽到要停的卡 → 立即停止（现场保留）」
            不是"体力用尽" ⇒ **跳过收工日常**（公会日常/免费招募/免广告都不碰 ✓）」
        **但紧接着又自动重开了** ✗✗：
          「收尾体力 1507（已记入统计 ✓）」
          「   · 体力 **1507 > 100** ⇒ 够再刷一轮 ✓」
          「🔁 **体力够（>100）⇒ 重新开刷**（第 1 次重开）」
        ⇒ 于是又进图 → 又撞上**同一个**面板 → 又停 → 又重开 ……
          同一把日志里「抽到【元素·橙色】」共 **5 轮**（每轮 3 行）✗✗
      ---- 根因：**两处判据不同源**（本项目第 N 次同族错）----
        · 收工日常（`_ok_daily`）：**白名单** —— `stopped` 为空 或 含「体力」⇒ 才做 ✓
        · 自动重开（`_should_relaunch` ①）：**黑名单** —— 只排除「用户点了停止」✗
          ⇒ 「预言石碑抽到要停的卡 → 立即停止（现场保留）」**不含**「用户点了停止」
            ⇒ 放行 ⇒ 体力 1507 > 100 ⇒ 重开 ✗
          ⇒ 「发现红装（SS）标记 → 立即停止（现场保留）」同理 ✗
          ⇒ 「到点自动停止（04:58）」也漏了 ✗（到点该停却重开）
      ---- 修法：收成**一份**白名单，两处都调它 ----
        · 白名单方向（fail-closed）：**新增停止原因默认不做收工后续** ✓
          （与 2026-10-19 收工日常那条**同一口径** ✓ —— 别再各写一份）
        · 「进图失败（体力不足 / 不在选图界面）」含「体力」⇒ 仍按体力耗尽处理
          （**保持现状**，不引入回归 ✓）
    返回 `(bool, 原因)`。
    """
    _stop = str(STATS.get('stopped') or '').strip()
    if not _stop:
        return True, '正常跑完（没停）'
    if '体力' in _stop:
        return True, '体力用尽'
    return False, _stop

def _should_relaunch(a):
    """收工后**要不要重开刷图** ⇒ `(bool, 原因)`

    ⭐⭐⭐ 2026-10-15 **用户口径**（原话）：
        「…三个脚本…都做完后，检查下体力，如果**超过100**，就**重新启动探图脚本**」

    ---- 判据（按顺序，任一不满足就**不重开**）----
      ① 用户没点过停止（`STATS['stopped']` 不含"用户点了停止"）
         ⚠ 这点最要紧：**用户说要停 ⇒ 绝不许自作主张再刷** ✗
      ② 至少勾了**一件**收工日常（公会日常 / 免费招募 / 免广告）
         ⚠ 全没勾 ⇒ 没地方补体力 ⇒ 重开必然是"再收工一次" ⇒ 空转 ✗
      ③ 当前**体力 > 100**（用户给的阈值 = `RELAUNCH_STAMINA_MIN` ✓）
         ⚠ 读不到体力 ⇒ **不重开**（fail-closed —— 宁可不刷，
           也别在"不知道够不够"的情况下反复进退图 ✗）
      ④ 上一轮**真跑过图**（`STATS['maps'] > 0`）
         —— 一张都没跑完说明进图就失败（多半被顶号/游戏没起）⇒ 重开也一样 ✗
    ⚠ 读体力要**重新取一帧**（`b.ocr` 读的是上一次 `snap` 的缓存 ✗
      —— 本项目在这上面栽过好几次："忘了 snap ⇒ 读到旧帧" ✓）
    """
    # ① 停止原因**允许**做收工后续吗？（**与收工日常同一份判据** ✓）
    #   ⚠ 2026-10-26 原来是**黑名单**（只排除「用户点了停止」）⇒
    #     「预言石碑抽到要停的卡」/「发现红装」/「到点自动停止」全漏了
    #     ⇒ 停完又自动重开 ⇒ 又撞同一个面板 ⇒ 连转 5 轮（真机铁证见
    #     `_stop_allows_afterwork()` 的 docstring）✗✗
    #   ⇒ 现在改成**白名单**（fail-closed）：只有「体力用尽」或「正常跑完」才重开 ✓
    _ok_aw, _why_aw = _stop_allows_afterwork()
    if not _ok_aw:
        return False, '停止原因「%s」⇒ **不重开**（要人工处理 / 出错）' % _why_aw
    # ② 三件日常至少要勾一件（否则没地方补体力）
    _any_task = any(
        str(os.environ.get(k, '0')).strip() == '1'
        for k in ('MAPBOT_GUILD_TASKS', 'MAPBOT_RECRUIT', 'MAPBOT_ADFREE'))
    if not _any_task:
        return False, '没收工日常可做（公会日常/免费招募/免广告都没勾）'
    # ④ 上一轮真跑过图
    if not STATS.get('maps'):
        return False, '上一轮一张图都没跑完'
    # ③ 读体力（**必须重新取帧** —— `b.ocr` 读的是缓存 ✗）
    try:
        _b = globals().get('_BOT')
        if _b is None:
            return False, '拿不到 Bot 实例'
        _its = _b.ocr(tag='relaunch')       # ⚠ `Bot.ocr` 内部会先 snap ✓
        _st = stamina(_its)
    except Exception as e:                  # noqa: BLE001
        return False, '体力读不出来（%r）' % (e,)
    if _st is None:
        return False, '体力读不出来（**保守不重开** ✗）'
    if _st <= RELAUNCH_STAMINA_MIN:
        return False, '体力 %d ≤ %d' % (_st, RELAUNCH_STAMINA_MIN)
    say('   · 体力 **%d > %d** ⇒ 够再刷一轮 ✓'
        % (_st, RELAUNCH_STAMINA_MIN))
    return True, '体力 %d' % _st


def _game_screen_ok(items):
    """当前帧 OCR 是否具备**游戏任何界面**的特征（崩溃自恢复检测用）。
    全 OCR 文字判据，无写死坐标 ⇒ 全分辨率适用 ✓"""
    import re as _re
    txts = [(i.get('text') or '') for i in items]
    for t in txts:
        if _re.search(r'\d+/\d+', t) and ('/' in t):      # HUD 体力/资源计数
            return True
    for k in ('开始冒险', '进入地图', '结束冒险', '快速扫荡', '公会', '斗技场',
              '星界秘境', '开始游戏', '检测到游戏更新'):
        if any(k in t for t in txts):
            return True
    return False


def _game_main_ok(items):
    """⭐ 恢复成功的**严格**判定：游戏已进到可玩界面（主界面/选图/图内）。
    登录页（开始游戏/我已同意/健康忠告）/热更提示（检测到游戏更新）/公告 都不算 ✓
    （v0.57 实锤：宽判据把登录页误判成恢复成功 ⇒ 公告没关 ⇒ 进图全卡 stuck）"""
    import re as _re
    txts = [(i.get('text') or '') for i in items]
    joined = ''.join(txts)
    for bad in ('开始游戏', '检测到游戏更新', '我已详细阅读', '健康游戏忠告', '公告'):
        if bad in joined:
            return False
    for t in txts:
        if _re.search(r'\d+/\d+', t):
            return True
    for k in ('开始冒险', '进入地图', '结束冒险', '快速扫荡', '斗技场', '星界秘境'):
        if any(k in t for t in txts):
            return True
    return False


def game_recover(b, log, tag='recover', timeout=600):
    """⭐⭐ 2026-10-01 崩溃自启动 + 热更新导航（用户要求：「游戏会热更新，记得做上这个备案」「全分辨率适用」）。

    游戏进程死亡/停在热更页/登录页时：
      bringGame 拉起 → **全 OCR 文字导航**（无写死坐标 ✓ 任意分辨率 ✓）：
        「检测到游戏更新/需下载」→ 点「确定」（开始下载）
        「下载中/更新中/加载资源」→ 静默等待（进度自己走）
        「公告」+「确定」→ 点确定
        「开始游戏」→ 点它（登录）
        「同意/同意并继续」→ 点它（隐私协议）
        主界面特征（开始冒险/进入地图/结束冒险/快速扫荡）→ 成功 ✓
    超时（timeout 秒）返回 False；每步动作/等待都落 log。"""
    dev = None
    try:
        from java import jclass as _jc      # Chaquopy（mapbot._api 同款）
        dev = _jc('com.fantasy.autoexplore.DeviceApi')
    except Exception as e:  # noqa: BLE001
        log.append({'recover': 'no_deviceapi', 'e': repr(e)[:120]})
        return False
    if not dev.bringGame():
        return False
    say('   ⚙ 游戏已拉起，等待加载/热更/登录（OCR 导航，最多 %d 秒）' % timeout)
    status('正在把游戏拉回来…')
    t0 = time.time()
    acted_at = 0.0
    while time.time() - t0 < timeout:
        if globals().get('_ANDROID_STOP') or stop_requested():
            return False
        b.snap(tag)
        items = b.ocr(min_conf=0.35, tag=tag)
        txts = [(i.get('text') or '').replace(' ', '') for i in items]
        joined = ''.join(txts)
        if _game_main_ok(items):
            # ⭐ 严格判定（_game_main_ok）：登录页/公告/热更提示都不算恢复成功，
            #   继续导航把它们处理掉 ✓
            log.append({'recover': 'ok', 'secs': round(time.time() - t0, 1)})
            say('   ⚙ 游戏恢复 ✓（用时 %.0f 秒）' % (time.time() - t0))
            status('游戏已恢复 ✓')
            return True
        act = None
        def _find_one(label, extra=()):
            for i in items:
                t = (i.get('text') or '').replace(' ', '')
                if t == label or any(k in t for k in (label,) + tuple(extra)):
                    return i
            return None
        if ('检测到游戏更新' in joined) or ('需下载' in joined):
            act = _find_one('确定')
            if act:
                b.tap(act['cx'], act['cy'], wait=2.5)
                log.append({'recover': 'update_confirm', 'at': (act['cx'], act['cy'])})
                say('   ⚙ 热更提示 → 点确定（开始下载）')
        elif ('下载' in joined) or ('更新中' in joined) or ('加载资源' in joined) or ('%' in joined):
            if time.time() - acted_at > 30:
                log.append({'recover': 'downloading', 'texts': txts[:10]})
                say('   ⚙ 热更资源下载中…（等待，不点击）')
                acted_at = time.time()
            time.sleep(4.0)
            continue
        # ⚠⚠ 2026-10-01 v1.16 修**真 bug**：登录页上「公告」两个字**仍在画面里**
        #   （实测 OCR：['公告','幻想少女公会','开始游戏','我已详细阅读并同意《',…]）
        #   ⇒ 旧的 `elif ('公告' in joined)` 抢先命中 → 帧上没有「确定」⇒ act=None
        #      → **`elif _find_one('开始游戏')` 永远轮不到**（elif 互斥）✗
        #      ⇒ 登录页永远点不到「开始游戏」，自动登录形同虚设。
        #   修法：**先判登录页**（最具体），公告分支放后面，并要求它有独立的「确定」按钮。
        elif _find_one('开始游戏'):
            act = _find_one('开始游戏')
            b.tap(act['cx'], act['cy'], wait=3.0)
            log.append({'recover': 'start_game', 'at': (act['cx'], act['cy'])})
            say('   ⚙ 登录页 → 点「开始游戏」')
        # 公告分支收紧：必须有**独立的「确定」按钮**才点，否则只记日志等画面推进
        #   （登录页/主界面上出现「公告」字样 ≠ 有公告弹窗 ✗）
        elif ('公告' in joined) and _find_one('确定'):
            act = _find_one('确定')
            b.tap(act['cx'], act['cy'], wait=2.5)
            log.append({'recover': 'notice_confirm', 'at': (act['cx'], act['cy'])})
            say('   ⚙ 公告弹窗 → 点确定')
        elif _find_one('同意', '同意并继续'):
            act = _find_one('同意', '同意并继续')
            b.tap(act['cx'], act['cy'], wait=2.5)
            log.append({'recover': 'agree', 'at': (act['cx'], act['cy'])})
        if act is not None:
            acted_at = time.time()
        else:
            time.sleep(3.0)      # 无识别目标 ⇒ 等画面推进
    log.append({'recover': 'timeout'})
    say('   ⚠ 游戏恢复超时（%d 秒）' % timeout)
    status('游戏起不来 · 已停下')
    return False


def _guild_daily(b, log):
    """⭐ 收工后的**公会日常**：派遣任务 + 炼金（用户 2026-10-14 口径）

    用户原话：「**这些我打算是体力刷完自动去做**」
    两条业务分别落在 `guild_tasks.py` / `alchemy.py`（各自可独立跑），
    这里只负责**顺序调度 + 异常隔离 + 记日志** ✓

    ---- 顺序 ----
      ① 派遣任务（公会展厅 **2 楼**，进公会默认就在这层）
      ② 炼金（**4 楼顶楼**，要往上滚）
    ⇒ 先做 2 楼（省一次滚动），再滚上去做炼金 ✓

    ---- 炼金要不要"自动投料" ----
      ⭐⭐⭐⭐ 2026-10-14 **用户明确要了**（我问过，原话选择）：
        「**自动投满星开炼（会消耗装备）**」
        ＋更早的口径：「炼金往上滑就能看到个有感叹号的箱子」
                      「这时候要**点满星**，然后点**开始炼金**」
      ⇒ 默认 **`auto_start=True`**（投满星开炼）✓
      ⚠⚠ 但它**仍然是"会消耗 6 件 5★ 满星装备"的不可逆动作** ⇒ 留一个反开关：
        `MAPBOT_ALCH_AUTO=0` ⇒ **只领取、不投料**（用户改主意 / 我调试时用 ✓）
      ⚠ 这条开关的口径是"**默认按用户授权执行，但可一键关掉**" ——
        与"默认关、要用户显式打开"**不同**，因为用户**已经明确授权过了** ✓
        （记录在案：授权来自 2026-10-14 的问答，不是我自己猜的 ✓）

    ---- 失败了怎么办 ----
      两个各包一层 try/except：**一个崩了不影响另一个**，更不影响收尾统计 ✓
    """
    say('')
    say('🏰 公会日常（收工）：派遣任务 + 炼金')
    # ⭐⭐⭐⭐ 2026-10-14 **两个开关各自独立**（用户口径：「炼金和派遣勾选选项加在
    #   没体力自动用补给前面」⇒ GUI 上是**两颗勾选框**，各自管一件事 ✓）
    #   · `MAPBOT_GUILD_TASKS` 1/0 ⇒ 做不做**派遣任务**
    #   · `MAPBOT_ALCH_AUTO`    1/0 ⇒ 做不做**炼金**（= 能不能投满星开炼）
    #   ⚠ **两个都关 ⇒ 整段跳过**（等价于"默认不做"，别白跑一趟公会 ✓）
    #   ⚠ 读不到 ⇒ **都当关**（`!= '1'`）—— 与 `.auto_supply` 同一口径：
    #     会改游戏状态 / 会消耗装备的动作，**绝不默认做** ✗
    #     （GUI 侧读不到偏好也默认传 '0' ⇒ 两边方向一致 ✓）
    # ⭐⭐⭐⭐ 2026-10-14 **用户口径**（两次，最终版）：
    #   ① 「炼金和派遣勾选选项加在没体力自动用补给前面」
    #   ② 「**派遣和炼金合成一个选项**」 ← 本次
    #   ⇒ GUI 上**只有一颗「公会日常」**，勾了就是"**两件都做**" ✓
    #   ⇒ 所以这里 `MAPBOT_GUILD_TASKS` 是**那颗勾选的开关**，
    #     勾上时 GUI 会**同时**把 `MAPBOT_ALCH_AUTO` 也置 1 ✓
    #     ⚠ 但仍然**两个变量都认** —— 这样命令行/老脚本可以只做其中一件 ✓
    #       （GUI 不给这个口子，但保留变量不额外花钱 ✓）
    _do_tasks = str(os.environ.get('MAPBOT_GUILD_TASKS', '0')).strip() == '1'
    _do_alch = str(os.environ.get('MAPBOT_ALCH_AUTO', '0')).strip() == '1'
    # ⭐ 2026-10-14 第三件：**免费指定招募**（用户口径：「尽量能拿到高等级角色」✓）
    _do_rec = str(os.environ.get('MAPBOT_RECRUIT', '0')).strip() == '1'
    # ⭐⭐ 2026-10-15 第四件：**情报领奖**（用户口径：「接下来做点击情报领取奖励」
    #   ＋「每周情报也顺便点了」✓）
    #   ⚠ 它**不需要独立勾选** —— 它和派遣/炼金一样是"公会日常"的顺手活儿，
    #     而且**纯领奖、零消耗**（不花体力/金币/宝石）⇒ 并进同一颗勾选最合理 ✓
    #     ⇒ 开关跟着 `MAPBOT_GUILD_TASKS`（= GUI 那颗「公会日常」）✓
    _do_intel = str(os.environ.get('MAPBOT_INTEL', '0')).strip() == '1'
    # ⭐⭐⭐ 2026-10-15 第五件：**广告领奖**（用户口径：
    #   「开始做领取广告（默认有免广），只做每天1次的加速炼金，
    #     每天三次的购买体力，幸运草和金币，单独加个有无免广的勾选，有就自动做」✓）
    #   ⚠ **它有自己的勾选**（`MAPBOT_ADFREE`）—— 不并进公会日常 ✓
    #     因为它**不在公会里做**（入口就在 HUD 上的资源数字/绿加号 ✓）
    #   ⚠ **未勾 ⇒ 一下都不碰**（无免广要真播视频广告，脚本做不了 ✓）
    _do_ads = str(os.environ.get('MAPBOT_ADFREE', '0')).strip() == '1'
    if not (_do_tasks or _do_alch or _do_rec or _do_intel or _do_ads):
        say('   · 公会日常/免费招募/免广告都没勾 ⇒ 跳过收工日常（一下都不点 ✓）')
        return False
    say('   · 本次要做：%s%s%s'
        % ('公会日常（派遣+炼金+情报） ' if (_do_tasks or _do_alch or _do_intel)
           else '',
           '免费招募 ' if _do_rec else '',
           ('广告领奖（免广）' if _do_ads else '')))

    # ⭐⭐⭐ 2026-10-15 **三个脚本，各自"进公会 → 干活 → 回地图"**（用户口径原话）：
    #   「把勾选的公会日常，免费招募和免广告（**这三个脚本的最后都要回到地图界面，
    #     最开始都要进入公会界面**）都做完后，检查下体力…」
    #   ---- 三个单元各自的进出场 ----
    #     ① **公会日常**（派遣+炼金+情报）⇒ 本函数开头 `goto_guild`、结尾 `leave_guild`
    #        ⚠ 三件事**都在公会里**，共用一次进出（不必每件各进一次 ✗）✓
    #     ② **免费招募** ⇒ `recruit.run` 内部自己进公会（入口在公会右下角）+ 回地图 ✓
    #     ③ **广告领奖** ⇒ `ads.run` 内部自己进公会（入口在 HUD，进公会只为语义一致）+ 回地图 ✓
    #   ⇒ 三者串起来 = 三次"进公会/回地图" ⇒ **位置可预测** ✓
    #     （用户要的正是这个 —— 原来三个挤在一起、只在最后 leave 一次 ✗）

    # ── ① 公会日常（派遣 + 炼金 + 情报）──
    _guild_entered = False
    if _do_tasks or _do_alch or _do_intel:
        say('')
        say('── ① 公会日常（派遣 + 炼金 + 情报）──')
        try:
            import guild_common as _gc
            _guild_entered = bool(_gc.goto_guild(b, log))
            if not _guild_entered:
                say('   ⚠ 进不了公会 ⇒ 跳过公会日常（派遣/炼金/情报）')
        except Exception as _eg:        # noqa: BLE001
            log.append({'guild_daily': 'enter_error', 'e': repr(_eg)[:120]})
            say('   ⚠ 进公会出错：%r' % (_eg,))

    # ① 派遣任务（2 楼）—— **只在勾了「派遣」时做** ✓
    _t = None
    if _do_tasks and _guild_entered:
        try:
            import guild_tasks as _gt
            _t = _gt.run(b, log, leave=False)
            say('   · 派遣任务：%s（%d 把在跑）'
                % ('✓' if _t.get('ok') else '⚠', _t.get('busy_count', 0)))
            STATS['guild_tasks_busy'] = _t.get('busy_count', 0)
        except Exception as _e1:        # noqa: BLE001
            import traceback as _tb1
            log.append({'guild_daily': 'tasks_error', 'e': repr(_e1)[:160],
                        'trace': _tb1.format_exc().splitlines()[-4:]})
            say('   ⚠ 派遣任务出错：%r' % (_e1,))
    else:
        say('   · 没勾「派遣任务」⇒ 跳过')

    # ⛔⛔ 2026-10-19 **派遣 → 炼金之间必须清一次面板**（真机事故）
    #   ---- 用户原话 ----
    #     「**派遣面板还开着呢，没划到炼金界面**」
    #   ---- 真机日志 ----
    #     `点 (240,445) ⇒ 没开出任何面板（认到 ['PID:162332','Ver1.2.2.8',...]）`
    #     ⇒ 那一帧只有主页 HUD ⇒ **面板还盖着**，炼金在面板上点空坐标 ✗
    #   ---- 为什么派遣完面板还在 ----
    #     · `guild_tasks.run(leave=False)` **不退出公会**（按设计 ✓）
    #     · `ensure_chair_floor()` 会"点椅1试层"，正常会 `close_panel`，
    #       但只要有一条路径没关成功（动画中 / OCR 没读到关钮）⇒ 面板留在屏上
    #     · **4 把椅子全 running** 时 `chair_timers` 直接 `continue`（不点椅子）
    #       ⇒ **没人负责关那个"试层"留下的面板** ✗
    #   ⇒ 这里显式清一次：`close_panel` 内部会多点几次 + probe 文本自证 ✓
    if _guild_entered and _do_alch:
        try:
            import guild_common as _gc0
            # ⚠ **先探测再点**（`close_panel` 是无条件 tap ⇒ 没面板时会乱点 ✗）
            _it0 = _gc0.ocr_items(b, tag='gd_pre_alch_probe')
            if _gc0.has(_it0, '黑晶女仆', '一键派遣', '派遣'):
                _gc0.close_panel(b, _gc0.TASK_PANEL_X, 'gd_before_alch',
                                 probe_texts=('黑晶女仆',), log=log)
                say('   · 派遣面板还开着 ⇒ 已关闭（准备上 4 楼炼金 ✓）')
            else:
                say('   · 派遣结束、无残留面板 ⇒ 直接上 4 楼炼金 ✓')
        except Exception as _e0:        # noqa: BLE001
            log.append({'guild_daily': 'pre_alch_clear_err',
                        'e': repr(_e0)[:120]})

    # ② 炼金（4 楼顶楼）—— **只在勾了「炼金」时做** ✓
    #   ⚠ 勾了就 `auto_start=True`（投满星）—— 这正是那颗勾选的语义 ✓
    #     （用户 2026-10-14 明确要的：「自动投满星开炼（会消耗装备）」）
    if _do_alch and _guild_entered:
        try:
            import alchemy as _al
            # ⭐⭐⭐ 2026-10-15 **用户口径**（原话）：
            #   「**勾选免广的话，做公会日常的时候，八小时炼金可以直接用一次免广立即领取**」✓
            #   ⇒ `accel` 跟着「**免广告**」那颗勾选（`MAPBOT_ADFREE`）走 ✓
            #     ⚠ 不是跟着炼金那颗 —— 因为"能不能用免广"取决于**账号有没有免广**，
            #       而不是有没有勾炼金 ✓（炼金勾了但号没免广 ⇒ 加速不了 ✗）
            #   ⚠ 无免广时 `ads.alchemy_accel` 自己会拒绝（要真播广告 ⇒ 做不了 ✓）
            _a = _al.run(b, log, auto_start=True, leave=False, accel=_do_ads)
            say('   · 炼金：领取=%s 开炼=%s 加速=%s 状态=%s'
                % (_a.get('claimed'), _a.get('started'),
                   _a.get('accelerated'), _a.get('state')))
            STATS['alch_claimed'] = bool(_a.get('claimed'))
            STATS['alch_state'] = _a.get('state')
        except Exception as _e2:        # noqa: BLE001
            import traceback as _tb2
            log.append({'guild_daily': 'alch_error', 'e': repr(_e2)[:160],
                        'trace': _tb2.format_exc().splitlines()[-4:]})
            say('   ⚠ 炼金出错：%r' % (_e2,))
    else:
        say('   · 没勾「炼金」⇒ 跳过')

    # ②b ⭐⭐ 情报领奖（公会展厅**右上角**「情报」）—— 2026-10-15 用户口径
    #   「**接下来做点击情报领取奖励**」＋「**每周情报也顺便点了**」✓
    #   ---- 为什么放在派遣/炼金**之后、招募之前** ----
    #     它就在**公会展厅**（不用滚楼层）⇒ 紧着公会里的活儿一起做完 ✓
    #     ⚠ 招募要**离开公会**（入口在大厅，见 `recruit.py`）⇒ 放最后 ✓
    #   ---- 为什么**纯领奖、零风险** ----
    #     只点「可领取」，**不碰**「购买情报指南」（要花宝石 ✗）、
    #     **不碰**「已完成」/「N/M」的行 ⇒ 不做任何不可逆动作 ✓
    if _do_intel and _guild_entered:
        try:
            import intel as _it
            _i = _it.run(b, log)
            say('   · 情报领奖：每日 %s 条 ｜ 每周 %s ｜ 已关页面 %s'
                % (_i.get('daily'), _i.get('weekly'), _i.get('closed')))
            STATS['intel_daily'] = _i.get('daily')
            STATS['intel_weekly'] = bool(_i.get('weekly'))
        except Exception as _e3:        # noqa: BLE001
            import traceback as _tb3
            log.append({'guild_daily': 'intel_error', 'e': repr(_e3)[:160],
                        'trace': _tb3.format_exc().splitlines()[-4:]})
            say('   ⚠ 情报领奖出错：%r' % (_e3,))
    else:
        say('   · 没勾「公会日常·情报」⇒ 跳过')

    # ── ⭐ **公会日常做完 ⇒ 回地图界面**（用户口径「最后都要回到地图界面」✓）──
    #   ⚠ 必须**在这里**就走（不能拖到三个都做完）——
    #     用户要的是**每个脚本各自**回到地图界面 ✓
    #     下一个脚本（免费招募）会**自己再进公会**（入口在公会右下角 ✓）
    if _guild_entered:
        try:
            import guild_common as _gc2
            _ok_leave = _gc2.leave_guild(b, log)
            say('   · %s' % ('① 公会日常 ⇒ 已回地图界面 ✓' if _ok_leave
                            else '⚠ ① 公会日常 ⇒ 没确认回到选图界面'))
            STATS['gd_back_to_map'] = bool(_ok_leave)
        except Exception as _el:        # noqa: BLE001
            log.append({'guild_daily': 'leave_error', 'e': repr(_el)[:120]})

    # ② 免费指定招募 —— **第二个脚本**（用户口径排序：公会日常 → 免费招募 → 免广告 ✓）
    #   ⚠ 它**自己**进出公会（入口在公会右下角「招募」）——
    #     所以上一个脚本结束时**必须在选图界面**（本段开头刚 leave 过 ✓）
    #   ⚠ 它自带"免费机会用掉了就跳过"的闸门（`recruit.FREE_BTN_LIT`）⇒ 不会花宝石 ✓
    #   ⚠ `return_to_map=True` 是默认值 ⇒ 它做完会自己回选图界面 ✓
    if _do_rec:
        say('')
        say('── ② 免费招募 ──')
        try:
            import recruit as _rc
            _r = _rc.run(b, log, recruit=True, leave=False,
                         return_to_map=True)
            say('   · 免费招募：选中=%s 保底=%s 成=%s 回地图=%s%s'
                % (_r.get('picked'), _r.get('minR'), _r.get('recruited'),
                   _r.get('back_to_map'),
                   '' if _r.get('ok') else '（%s）' % _r.get('why')))
            STATS['recruit_picked'] = _r.get('picked')
            STATS['recruit_done'] = bool(_r.get('recruited'))
        except Exception as _e4:        # noqa: BLE001
            import traceback as _tb4
            log.append({'guild_daily': 'recruit_error', 'e': repr(_e4)[:160],
                        'trace': _tb4.format_exc().splitlines()[-4:]})
            say('   ⚠ 免费招募出错：%r' % (_e4,))
    else:
        say('   · 没勾「免费招募」⇒ 跳过')

    # ④ ⭐⭐⭐ 广告领奖 —— **第三个脚本**（用户口径的排序：公会日常 → 免费招募 → 免广告 ✓）
    #   ⭐⭐ 2026-10-15 **用户口径**（原话，统一三个脚本的进出场）：
    #     「（**这三个脚本的最后都要回到地图界面，最开始都要进入公会界面**）」✓
    #   ---- 所以这里**去掉了中间那次 `leave_guild`** ----
    #     原来是「公会日常 → 免费招募 → **离开公会** → 广告」✗
    #       ⇒ 广告明明不依赖公会，却因为"上一段离开了"而**白跑一趟** ✗
    #         （而且它的入口就在 HUD 上，任何界面都能点 ✓）
    #     ⇒ 现在：**每个脚本自己"进公会 → 干活 → 回地图"** ✓
    #       三个脚本串起来 = 三次"进公会/回地图"，位置语义**可预测** ✓
    #       （用户要的正是这个 ✓）
    if _do_ads:
        try:
            import ads as _ad
            # ⚠ `enter_guild=True` / `return_to_map=True` 都是**默认值**，
            #   这里显式写出来 ⇒ 读代码的人一眼看到"它自己会进出公会"✓
            _ar = _ad.run(b, log, skip_ads=True,
                          enter_guild=True, return_to_map=True)
            say('   · 广告领奖：金币 %s ｜ 四叶草 %s ｜ 体力 %s ｜ 加速炼金 %s'
                % (_ar.get('gold'), _ar.get('clover'), _ar.get('energy'),
                   _ar.get('alchemy')))
            STATS['ads_gold'] = _ar.get('gold')
            STATS['ads_clover'] = _ar.get('clover')
            STATS['ads_energy'] = _ar.get('energy')
            STATS['ads_alchemy'] = bool(_ar.get('alchemy'))
        except Exception as _e5:        # noqa: BLE001
            import traceback as _tb5
            log.append({'guild_daily': 'ads_error', 'e': repr(_e5)[:160],
                        'trace': _tb5.format_exc().splitlines()[-4:]})
            say('   ⚠ 广告领奖出错：%r' % (_e5,))
    else:
        say('   · 没勾「免广告」⇒ 跳过广告领奖')

    # ⑤ ⭐⭐⭐⭐ 2026-10-16 **最后的最后：扫天赋果实**（用户口径，原话）
    #   「最后的最后（**做完日常，招募什么的且体力小于100就是最后了**）
    #    去**背包道具**里扫描下天赋果实数量，并且记录」
    #   ＋「类似**小助手的天赋果实记录**，做好放到**工具栏**里」
    #   ---- 为什么放在**最末尾** ----
    #     用户点明"**做完日常、招募什么的**"之后
    #     ⇒ 前面几件都可能**改变体力/道具**（尤其广告奖 +600 ✓）
    #       ⇒ 放最后才能记到"今天的最终状态" ✓
    #   ---- 闸门：**体力 < 100**（用户点名的条件 ✓）----
    #     ⚠ 为什么要有这道闸：它是"**收工**"的标志 ⇒
    #       体力还多说明没刷完，这时候去扫只是白扫一次（还会频繁改记录 ✗）
    #     ⚠ 读不到体力 ⇒ **不扫**（fail-closed：宁可不记，也别在"状态不明的"
    #       时候改记录 ✓ 与小助手"人工确认后才记"的谨慎口径一致 ✓）
    try:
        _st = None
        try:
            _its = b.ocr(tag='fruit_gate')      # ⚠ `Bot.ocr` 内部先 snap ✓
            _st = stamina(_its)
        except Exception as _e_s:               # noqa: BLE001
            log.append({'fruit': 'stamina_err', 'e': repr(_e_s)[:120]})
        say('')
        if _st is None:
            say('   · 扫天赋果实：**体力读不出来** ⇒ 不扫（保守 ✓）')
            STATS['fruit_scan'] = 'skip_stamina_unknown'
        elif _st >= FRUIT_SCAN_MAX_STAMINA:
            say('   · 扫天赋果实：体力 %d >= %d ⇒ **还没到收工**，不扫 ✓'
                % (_st, FRUIT_SCAN_MAX_STAMINA))
            STATS['fruit_scan'] = 'skip_stamina_ok'
        else:
            say('   · 体力 %d < %d ⇒ 到最后的收尾了 ⇒ 扫天赋果实 ✓'
                % (_st, FRUIT_SCAN_MAX_STAMINA))
            import fruit as _fr
            _fok, _fr_res, _fst = _fr.scan_and_record(b, log)
            STATS['fruit_scan'] = 'ok' if _fok else (
                _fr_res.get('why') or 'failed')
            STATS['fruit_count'] = _fr_res.get('count')
            STATS['fruit_total_get'] = _fst.get('total_get')
            say('   · 天赋果实：%s ｜ 累计获取 %s ｜ 日均 %s'
                % (_fr_res.get('count'), _fst.get('total_get'),
                   _fst.get('avg')))
    except Exception as _e6:        # noqa: BLE001
        import traceback as _tb6
        log.append({'guild_daily': 'fruit_error', 'e': repr(_e6)[:160],
                    'trace': _tb6.format_exc().splitlines()[-4:]})
        say('   ⚠ 扫天赋果实出错（**不影响收尾** ⇒ 继续）：%r' % (_e6,))
    return True


def map_end_kind(log):
    """这一张图**是怎么结束**的 → 'board_blind' / 'blank' / 'unreachable' / 'other'

    ⭐⭐⭐ 2026-10-05 用户口径（原话）：「**做1 报数/计数分开**」

    为什么要这个分类（真机 13:29 那把，`runs/acc2/loop/loop_log.json`）：
      · 3 张图的 `finish` 全是 **`targets_unreachable`**（计划里的步被 `give_up_step` 摘光，
        画面好好的、棋盘读得清清楚楚），而 `run_maps` 原来把所有 'stuck' 一视同仁
        ⇒ 报成「连续 2 张图认不出棋盘（画面被判"被面板挡住"）」+ 让人去看 `runs\\bagdbg`
        的诊断帧 —— 而那条路**根本不落帧**（落帧只在 `st['dark']==1` 那条真·被挡的分支）
        ⇒ 目录里 `board_hidden_*` 最新是 **10-04 11:37** ⇒ **拿旧帧去找新问题** ✗✗

    判据：扫**本图**最后一条 `finish`（从后往前，遇到 `{'map':…}` 分界就停）：
      `board_not_visible` → 'board_blind'（真·认不出棋盘）｜`blank_board` → 'blank'
      `targets_unreachable` → 'unreachable'（计划走不下去，画面正常）
      其它 / 没记 → 'other'
    ⚠ 也兜一道 `board_hidden`（那条每轮都记，真被挡时必有）✓
    """
    _kinds = {'board_not_visible': 'board_blind', 'blank_board': 'blank',
              'targets_unreachable': 'unreachable'}
    for e in reversed(list(log or [])):
        if not isinstance(e, dict):
            continue
        if 'map' in e and 'end_reason' in e:      # 上一张图的分界 ⇒ 本图的记录到头了
            break
        f = e.get('finish')
        if f in _kinds:
            return _kinds[f]
        if 'board_hidden' in e:
            return 'board_blind'
    return 'other'


def run_maps(a):
    global WIN, LOG_PATH, SUMMARY_PATH, _BOT
    b = Bot(log_prefix='loop', serial=INSTANCE_DEV, tag=INSTANCE_TAG or None)
    # ⭐ 分辨率自适应：拿到真实屏幕尺寸后刷新坐标 ✓（1080×1920 下零变化 ✓）
    try:
        _im = b.img()
        if _im is not None:
            _h, _w = _im.shape[:2]
            _L = apply_layout(_w, _h)
            say('屏幕 %dx%d ⇒ 缩放 k=%.4f（参考 1080×1920 ✓）' % (_w, _h, _L.k))
            if (_w, _h) != (layout_mod.REF_W, layout_mod.REF_H):
                say('   ⚠ 非参考分辨率：棋盘 x0=%d y0=%d 格距=%.1f（自适应 ✓）'
                    % (_L.grid['x0'], _L.grid['y0'], _L.grid['cx']))
    except Exception as _e:      # noqa: BLE001
        say('⚠ 分辨率自适应失败（按 1080×1920 继续 ✓）：%r' % (_e,))
    _BOT = b
    # ⭐⭐⭐ 2026-10-02：**每次开跑先把上一轮的 loop_log 留一份** ——
    #   原来每次运行都直接覆盖 `loop_log.json`，导致"跑完想查上一把的明细"时
    #   数据已经被下一次运行冲掉了（本轮排查 `pre` 6 次就是这么丢失的 ✗）。
    #   ⇒ 只留**一份上一轮**（`loop_log_prev.json`），不搞历史堆积 ✓
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2:
            import shutil as _sh
            _prev = os.path.join(os.path.dirname(LOG_PATH), 'loop_log_prev.json')
            _sh.copyfile(LOG_PATH, _prev)
            # ⛔⛔ 2026-10-19 **备份完必须清空主文件**（真机事故见文件头）
            #   用户报：「而且棋盘也没更新」「棋盘错了，计划也是错的」
            #   病：只备份不清空 ⇒ GUI 继续读上一轮的 loop_log ⇒ 画出旧地图的棋盘
            #       ⇒ 计划也按旧棋盘算 ⇒ 点序完全不对 ✗✗
            #   ⇒ 写个空数组 ⇒ GUI 读不到旧 board ⇒ 老老实实等新数据 ✓
            try:
                import json as _js
                with open(LOG_PATH, 'w', encoding='utf-8') as _f:
                    _js.dump([], _f)
            except Exception:               # noqa: BLE001
                pass
    except Exception as _e_lp:              # noqa: BLE001
        say('   ⚠ loop_log 留档失败（不影响跑图）：%r' % (_e_lp,))
    if INSTANCE_TAG:                      # 多开：日志/统计也各自独立
        WIN = os.path.join(b.runs, 'loop')
        os.makedirs(WIN, exist_ok=True)
        LOG_PATH = os.path.join(WIN, 'loop_log.json')
        SUMMARY_PATH = os.path.join(b.runs, 'last_summary.json')
        try:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2:
                import shutil as _sh2
                _sh2.copyfile(LOG_PATH,
                              os.path.join(WIN, 'loop_log_prev.json'))
                # ⛔ 同上：备份完清空（多开每窗口独立，各自清空 ✓）
                try:
                    import json as _js2
                    with open(LOG_PATH, 'w', encoding='utf-8') as _f2:
                        _js2.dump([], _f2)
                except Exception:           # noqa: BLE001
                    pass
        except Exception:                   # noqa: BLE001
            pass
    # ⭐ 兜底：文件还不存在（首次跑）也写个空数组 ⇒ GUI 早有文件可读，不报错 ✓
    try:
        if not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) < 3:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            import json as _js3
            with open(LOG_PATH, 'w', encoding='utf-8') as _f3:
                _js3.dump([], _f3)
    except Exception:                       # noqa: BLE001
        pass
    say('实例：%s  设备：%s  目录：%s' % (INSTANCE_TAG or '（单开）', INSTANCE_DEV, b.runs))
    log = []
    t_all = time.time()
    status('开跑 · 正在找游戏画面' if a.maps > 1 else '开跑（1 张）· 正在找游戏画面')
    for mi in range(a.maps):
        # ⭐ 2026-09-29 用户口径：点 ■ 要**立即停止**（比凌晨 5 点的判定点**更靠前**）
        if stop_checked(log, '地图边界（第 %d 张前）' % (mi + 1)):
            STATS['stopped'] = '用户点了停止'
            break
        # ⭐ 2026-09-26 用户要求：凌晨 5 点自动停止
        #   停**每张图之间**（不打断正在打的那张 ⇒ 退图流程照常走完，不会留下半张图 ✓）
        if past_stop_time():
            log.append({'stop': 'five_am', 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'stop_time': STOP_TIME.strftime('%m-%d %H:%M')})
            STATS['stopped'] = '到点自动停止（%02d:%02d）' % STOP_HM
            say('⏰ 到 %s 了（%02d:%02d 自动停止），最后一张图已打完，收工'
                % (STOP_TIME.strftime('%m-%d %H:%M'), STOP_HM[0], STOP_HM[1]))
            break
        b.snap('m%d_pre' % mi)
        # ⭐ 2026-09-28 提速（P1）：原版这里对**同一帧**跑了两遍全屏 OCR
        #   （一遍查顶号、一遍读体力，0.8s/次纯浪费）⇒ 合并成一次，两项都从这帧取 ✓
        _items_pre = b.ocr(tag='pre')
        if fb(_items_pre, *L['kick']):
            log.append({'stop': 'kicked'})
            STATS['stopped'] = '账号被其他设备顶下线'
            say('⚠ 账号被其他设备顶下线，已停止（不会自动点确定）')
            break
        # ⭐⭐ 2026-10-01 崩溃自恢复检测（用户要求「游戏会热更新，做上备案，全分辨率适用」）：
        #   当前帧没有游戏任何特征（游戏进程死亡/停在热更页/登录页/桌面）⇒
        #   bringGame 拉起 + OCR 文字导航（热更确定→下载等待→公告→开始游戏），全分辨率 ✓
        if not _game_screen_ok(_items_pre):
            say('   ⚠ 画面无游戏特征（崩溃/热更/登录页？）⇒ 自动恢复')
            status('画面不是游戏 · 正在把游戏拉回来…')
            log.append({'recover': 'trigger'})
            if not game_recover(b, log, tag='rec%d_' % mi):
                STATS['stopped'] = '游戏自动恢复失败'
                say('   ⚠ 游戏自动恢复失败 ⇒ 停止（可在悬浮条再点 ▶ 重试）')
                status('⚠ 游戏起不来 · 已停下（可再点 ▶ 重试）')
                break
            b.snap('m%d_recovered' % mi)
            _items_pre = b.ocr(tag='pre')       # 恢复后重读（kick/体力都从这帧取）
            log.append({'recover': 'recheck', 'ok': _game_screen_ok(_items_pre)})
        # ⭐⭐ 2026-09-30：装备升星**已挪到"每张图跑完"处**（本循环体末尾，`if ok:` 之后）——
        #   原来放在这里（`mi>0 and mi%10==0`）⇒ 实际触发点是**第 11 张图开始前**，语义是
        #   "刷够 10 张之后、下一张之前"。用户报「刚刷了 10 把没触发升星」：真机 14:12 实测
        #   刷完 10 张、`bag_upgrade` 调用 0 次 —— 因为 maps=10 的一局 `mi` 只到 9，
        #   **永远等不到第 11 张**（`mi%10==0` 需要 mi=10）。挪走后本处不再判，见循环末尾 ✓
        say('== 第 %d 张图 ==' % (mi + 1))
        status('第 %d 张图 · 准备进图' % (mi + 1))
        # ⭐ 2026-09-27：**进图前**读一次体力（选图界面 ✓ 此时还没扣那 25）
        #   ⇒ 相邻两次"进图前"的差 = 25 进图消耗 + 图内消耗 ✓（用户要求算进图消耗 ✓）
        try:
            _st_pre = stamina(_items_pre)
            if _st_pre is not None:
                STATS['stamina_entries'].append((_st_pre, time.time()))
                say('   进图前体力 %d（已记入统计 ✓）' % _st_pre)
        except Exception as _e3:      # noqa: BLE001
            say('   ⚠ 进图前体力读取失败：%r' % (_e3,))
        # ⚠⚠ 2026-10-02 修「PC 端用不了」（GUI 日志 gui_20261002_013006.log 退出码 1）：
        #   这整段（原 `ensure_in_map` 调用点）是**裸调用**。里面任何一处抛异常
        #   （补给面板坐标、OCR None、模板缺失、numpy nan…）都会**直接穿出主循环**，
        #   而 `explore_loop.py` 顶层兜底写 `_crash.log` 时用的是 `RUNS/<tag>/`，
        #   实测那个文件**压根没生成** ⇒ 用户只看到「循环进程已退出（退出码 1）」，
        #   什么线索都没有 ✗✗（这就是"完全用不了"的直接原因）。
        #   ⇒ 进图是**每张图的必经步骤**，单张失败只该跳过这张图、继续下一张；
        #     极端情况（反复失败）由 recover_n 计数后正常收工，绝不无声崩掉 ✓
        try:
            # ⭐ 2026-10-02 提速审计：把上面刚读过的 `_items_pre`（**同一帧**）传进去，
            #   让 `ensure_in_map` 第 0 轮不必再 OCR 一次 ⇒ 省 ≈0.9s/图 ✓
            # ⭐⭐⭐ 2026-10-05 `enter_with_retry`：连接类错误（`device not found` 这类瞬断）
            #   会**先重连再试一次**（见该函数注释）；两次都失败才走到下面"跳图" ✓
            _entered = enter_with_retry(b, log, tag='m%d_' % mi, items0=_items_pre)
        except Exception as _e7:      # noqa: BLE001
            _entered = False
            log.append({'map': mi, 'enter_raised': repr(_e7)[:200]})
            say('   ⚠ 进图这一步出错（已跳过这张图）：%r' % (_e7,))
            try:
                _pub_dump('enter_fail_m%d' % mi, b.img())
            except Exception:       # noqa: BLE001
                pass
            # ⚠ 连续多张都进不去 ⇒ 多半不是偶发，整局收工并说清楚（而不是空转到天荒地老）
            recover_n = STATS.get('recover_n', 0) + 1
            STATS['recover_n'] = recover_n
            if recover_n >= 3:
                STATS['stopped'] = '连续 %d 张图进不去（进图步骤报错）' % recover_n
                say('   ⚠ 连续 %d 张图都进不去 ⇒ 收工（已把出错时的画面存到 '
                    '/sdcard/Download/autoexplore/，可发给作者排查 ✓）' % recover_n)
                status('连续进不去图 · 已停下（请把诊断帧发我）')
                flush(log)
                break
            continue
        if not _entered:
            log.append({'map': mi, 'stop': 'not_in_map'})
            STATS['stopped'] = STATS['stopped'] or '进图失败（体力不足 / 不在选图界面）'
            say('⚠ 进图失败（可能体力不足 / 不在选图界面），已停止')
            status('⚠ 进图失败 · 已停下（体力不够？）')
            break
        # ⭐ 分辨率自适应：进图成功后标定一次棋盘几何 ✓（只跑一次 ✓ 永不退化 ✓）
        if ADAPTIVE_LAYOUT and not _GRID_CALIBRATED['done']:
            try:
                _im0 = b.img()
                if _im0 is not None:
                    auto_calibrate_grid(b, _im0, log=log)
                    # ⭐ 不管成功/被拒，本次启动只测一次 ✓（用户 2026-09-27）
                    _GRID_CALIBRATED['done'] = True
            except Exception as _e2:      # noqa: BLE001
                say('   ⚠ 棋盘自检异常：%r' % (_e2,))
        # ⭐ 2026-09-28 提速（P1）：体力在顶部 HUD ⇒ band OCR 就够（~0.25s），
        #   不必全屏（0.8s）；这行只用于日志展示，不进账（进账在"进图前"那次 ✓）
        # ⭐⭐⭐ 2026-10-02 再提速：**先看能不能复用刚读过的同帧结果** ——
        #   这行注释自己写着「**只用于日志展示，不进账**」⇒ 完全没必要为它单独付一次 OCR。
        #   `ensure_in_map` 刚刚（同一帧、未再点击）读过一份 items ⇒ 直接拿体力 ✓
        #   ⚠ 只在**帧号未变**时复用（`b._snap_n` 相同 ⇒ 同一帧，结果必然相同）✓
        _reuse_ok = (_LAST_ITEMS.get('items') is not None
                     and _LAST_ITEMS.get('stamp') is not None
                     and _LAST_ITEMS.get('stamp') == getattr(b, '_snap_n', None))
        if _reuse_ok:
            st_now = stamina(_LAST_ITEMS['items'])
            log.append({'enter_stam': 'reuse_items', 'stamina': st_now})
        else:
            st_now = stamina(b.ocr(band=(0, int(LAYOUT.sy(320))), tag='pre'))
        say('   已进图，体力 %s' % (st_now if st_now is not None else '?'))
        # ⭐⭐⭐ 2026-10-06 **图上时间戳**（治「退图细账」里那个恒等的假字段）
        #   用户问「退图细账：finish_map 10.9s（图内 10.9s ｜ 整周期 68.8s）这是什么东西」
        #   ⇒ 查出来是：那句 `say` 把 `_fin_secs` **传了两次** ✗
        #       say('…finish_map %.1fs（图内 %.1fs ｜ 整周期 %.1fs）'
        #           % (_fin_secs, _fin_secs, time.time() - t_one))
        #     ⇒ 「图内」永远 == 第一个数，等于**没有这个信息** ✗
        #   而注释的**本意是"把退图这一段拆开、别再猜"** ⇒ 那个数应该是别的量 ✓
        #   ⇒ 口径定为：**图内 = 进图完成 → 开始退图**（真正"在图里待了多久"）；
        #      整周期 = 进图前 → 现在（这张图的完整耗时）。
        #   ⚠ 只加一个时间戳，**不改任何行为**（纯日志）✓
        _t_in = time.time()
        status('第 %d 张图 · 已进图，正在看棋盘' % (mi + 1))
        if st_now is not None:
            # ⚠ 2026-09-27：这里**不再记账**（改由"进图前"那次记账 ✓）
            #   否则会把"扣完 25 之后"的值当基准 ⇒ 25 又丢了 ✗
            ent = STATS['stamina_entries']
            if len(ent) >= 2:
                (s0, t0), (s1, t1) = ent[-2], ent[-1]
                regen = max(0.0, t1 - t0) / 30.0
                say('   上一张图消耗体力约 %.0f（进图 %d → %d，间隔 %.0f 秒，期间回 +%.0f）'
                    % (max(0.0, (s0 - s1) + regen), s0, s1, t1 - t0, regen))
        STATS['current_map'] = mi + 1
        # ⭐⭐ 2026-09-27 采图模式（--collect-only）：
        #   进图成功这一刻的画面 = **整张图最干净的一帧**（没有任何图标/战斗/面板盖住）
        #   ⇒ 存下来 → 立刻退图 → 下一张。全程不揭格、不打怪、不买、不补点 ✓
        #   ⚠ 退图**不做 final_collect**（那一步是"把打过的格再点一遍领战利品"，
        #     采图模式一格没打过 ⇒ 点了反而会揭开新格/弹面板 ✗）
        if COLLECT_ONLY:
            t_one = time.time()
            _shot = save_board_frame(b, log, rnd=0)
            ok = finish_map(b, log)
            _dt = time.time() - t_one
            log.append({'map': mi, 'collect_only': True, 'finished': ok,
                        'shot': os.path.basename(_shot) if _shot else None,
                        'secs': round(_dt, 1)})
            say('   采图：%s（本张 %.0f 秒）%s'
                % (os.path.basename(_shot) if _shot else '⚠ 存图失败', _dt,
                   '' if ok else '  ⚠ 退图没成功'))
            if _shot:
                STATS['shots'] += 1
            if ok:
                STATS['map_secs'].append(_dt)
                STATS['current_map'] = 0
                STATS['current_secs'] = 0
            else:
                STATS['stopped'] = STATS['stopped'] or '退图失败（采图模式）'
                flush(log)
                break
            flush(log)
            continue
        t_one = time.time()
        # ⚠⚠⚠ 2026-10-02 修「还是运行不了」（GUI 日志 gui_20261002_015007.log 退出码 1）：
        #   原来这里是 `try: … finally: STATS[...]=…` —— **只有 finally、没有 except**，
        #   所以 `run_one_map` 内部任何异常（`final_collect` / `stop_checked` / 计时…）
        #   都会**直接穿出主循环**、进程带异常退出 ⇒ 用户只看到「退出码 1」，
        #   而 `runs/<tag>/_crash.log` **压根不会生成**（实测全程都没有）✗✗
        #   ⚠ 这是 2026-10-02 第三次修同一个病根（前面 `ensure_in_map`、`use_supply` 各一次）
        #     —— 教训：**凡是没有 except 的 try，异常都会穿透到进程最外层**。
        #   ⇒ 单张图失败只该影响这张图：记日志 + 落 traceback + 继续下一张 ✓
        try:
            why = run_one_map(b, log, a.max_round, prefix='m%d_' % mi, deadline=a.deadline)
        except Exception as _e8:      # noqa: BLE001
            import traceback as _tb
            why = 'error'
            _tb_txt = _tb.format_exc()
            log.append({'map': mi, 'run_one_map_raised': repr(_e8)[:200],
                        'trace': _tb_txt.splitlines()[-6:]})
            say('   ⚠ 这张图跑的过程中报错（已跳过，继续下一张）：%r' % (_e8,))
            try:
                _pub_dump('map_error_m%d' % mi, b.img())
            except Exception:       # noqa: BLE001
                pass
            # 落盘 traceback（GUI 那边提示的 `_crash.log` 就是它）
            try:
                _cf = os.path.join(RUNS, INSTANCE_TAG or '', '_crash.log')
                os.makedirs(os.path.dirname(_cf), exist_ok=True)
                with open(_cf, 'a', encoding='utf-8') as _f:
                    _f.write('\n===== %s  第 %d 张图 =====\n'
                             % (time.strftime('%Y-%m-%d %H:%M:%S'), mi))
                    _f.write(_tb_txt + '\n')
                say('   💥 栈已写入 %s' % _cf)
            except Exception:       # noqa: BLE001
                pass
        finally:
            STATS['current_secs'] = time.time() - t_one
        log.append({'map': mi, 'end_reason': why})
        say('   本图结束：%s（耗时 %.0f 秒）' % (why, time.time() - t_one))
        # ⭐⭐⭐ 2026-10-01 v1.11【"画面被判被挡"不许无限循环】（朋友真机：一张接一张地卡）
        #   旧路径：`board_not_visible` → 'stuck' → 退图失败 → game_recover → 下一张图
        #   → 同样判"被挡" → ⋯ **永远出不来**，用户看到的就是"一直卡在这" ✗✗
        #   ⇒ 连续 2 张都 stuck（且没跑完）⇒ 整局停下 + 悬浮条说明 + 已存诊断帧 ✓
        #
        # ⭐⭐⭐⭐ 2026-10-05 用户口径（原话）：「**做1 报数/计数分开**」——**计数分开**：
        #   真机 13:29 那把 3 张图全是 `finish: targets_unreachable`（计划里的步被摘光，
        #   见 `give_up_step`），却被上面这条**一视同仁**地计成"认不出棋盘"⇒
        #     ① 报错方向（「画面被判"被面板挡住"」，其实画面好好的）
        #     ② 还要人去看 `runs\bagdbg` 的诊断帧 —— 而那条路**根本不落帧**，
        #        目录里 `board_hidden_*` 最新是 10-04 11:37 ⇒ **拿旧帧去找新问题** ✗✗
        #    ⇒ 现在按 `map_end_kind()` 分两类：
        #      · **board_blind / blank**（真·认不出棋盘 / 整盘读成空格）⇒ 老行为：连着 2 张停
        #        + 提示诊断帧（这条确实落帧 ✓）
        #      · **unreachable**（计划走不下去，画面没问题）⇒ 单独计数，**不计进"认不出棋盘"**；
        #        连着 **3** 张才停，且说清是"计划走不下去"、指到 `loop_log.json`（不指 bagdbg）
        _end_kind = map_end_kind(log)
        if why in ('stuck', 'blank'):
            if _end_kind in ('board_blind', 'blank'):
                STATS['blind_maps'] = STATS.get('blind_maps', 0) + 1
                STATS['stuck_maps'] = 0
            else:
                STATS['blind_maps'] = 0
                STATS['stuck_maps'] = STATS.get('stuck_maps', 0) + 1
            if STATS['blind_maps'] >= 2:
                # ⭐⭐⭐ 2026-10-03 修**写死的旧路径**（真机日志实证：文案说
                #   `/sdcard/Download/autoexplore/bagdbg/`，而 PC 上诊断帧其实落在
                #   `runs/bagdbg/`（我 8ed6480 才把 `_pub_dump` 修成真落盘 ✗）
                #   ⇒ 文案改成**跟着实际落盘位置**说，并且把"该发哪几个文件"讲清 ✓
                _dbg_hint = os.path.join(RUNS, 'bagdbg')
                STATS['stopped'] = ('连续 %d 张图认不出棋盘（画面被判"被面板挡住"）'
                                    '｜诊断帧：%s' % (STATS['blind_maps'], _dbg_hint))
                say('   ⚠ 连续 %d 张图都认不出棋盘 ⇒ 停止'
                    '（诊断帧在 %s\\*.png，连同 runs\\gui_*.log 一起发给作者 ✓）'
                    % (STATS['blind_maps'], _dbg_hint))
                status('⚠ 连续认不出棋盘 · 已停下（请把诊断帧发我）')
                flush(log)
                break
            if STATS['stuck_maps'] >= 3:
                # ⭐ 2026-10-05：画面没问题、只是"计划走不下去"⇒ **不改文案混进上面那条**，
                #   自己一条说清楚（并且不指 bagdbg —— 那条路不落帧 ✓）
                _rep_hint = os.path.join(RUNS, INSTANCE_TAG or '', 'loop', 'loop_log.json')
                STATS['stopped'] = ('连续 %d 张图计划走不下去（目标不可达，画面正常）'
                                    '｜日志：%s' % (STATS['stuck_maps'], _rep_hint))
                say('   ⚠ 连续 %d 张图都"计划走不下去（目标不可达）" ⇒ 停止'
                    '（这条**不是**认不出棋盘；看 %s 里的 `give_up_step` / '
                    '`targets_unreachable` ✓）' % (STATS['stuck_maps'], _rep_hint))
                status('⚠ 连续目标不可达 · 已停下（请看 loop_log）')
                flush(log)
                break
        else:
            STATS['blind_maps'] = 0
            STATS['stuck_maps'] = 0
        if why == 'kicked':
            STATS['stopped'] = '账号被顶下线'
            break
        if why == 'red_equip':
            # 🛑 看到红装标记：**不退图、不补点**，停在原地交给人处理
            STATS['stopped'] = '发现红装（SS）标记 → 立即停止（现场保留）'
            say('⚠ 已停止：红装标记格留在图上，请你自己处理（本轮不再动作）')
            break
        # ⛔⛔⛔ 2026-10-12 **修「抽到元素·橙色没有立即停止」**（用户报，原话 ✗）
        #   ---- 病 ----
        #     本函数里只有 `kicked` / `red_equip` / `stopped` **三个** `why` 分支，
        #     **没有 `foretell_stop`** ✗
        #     ⇒ 它一路往下走到 `finish_map(b, log)` ⇒ **退图 + 继续下一张** ✗✗
        #   ---- 真机铁证（`runs/gui_20261012_163344.log`）----
        #     `🛑🛑 抽到【元素·橙色】⇒ **立即停止**（不退图，留着你自己处理）`
        #     `   本图结束：foretell_stop（耗时 37 秒）`      ← 正确返回了
        #     `       · 已回到选图界面`                      ← ⚠ **还是退图了** ✗
        #     `› 第 16 张图 · 完成（42 秒）`                  ← ⚠ 当成正常完成 ✗
        #     `== 第 17 张图 ==`                            ← ⚠ **进入下一张** ✗✗
        #     `… 正在停止（等这一小步做完）`                  ← 直到用户点停才停
        #   ---- 讽刺的是注释早就写对了（`:9717` 附近）----
        #     「⇒ 最终 `run_one_map` 的调用方按 `why == 'red_equip'` 那样处置：
        #        **不退图、不补点，停在那里交给人处理** ✓」
        #     ⇒ **注释写了、代码没写** ✗（本项目第 N 次"文档对、实现漏"）
        #   ---- 修法 ----
        #     补一个与 `red_equip` **完全同构**的分支：设 `STATS` + `say` + **break** ✓
        #     ⚠ 必须 `break`（不是 `continue`）—— 用户口径是"**立即停止**"，不是"跳过这张" ✓
        if why == 'foretell_stop':
            # 🛑 抽到要停的预言（幸运/和平/元素·紫/元素·橙）：
            #    **不退图、不补点**，停在原地交给人处理（与红装同一套 ✓）
            STATS['stopped'] = '预言石碑抽到要停的卡 → 立即停止（现场保留）'
            say('')
            say('⚠ 已停止：预言石碑面板留在图上（不退图），请你自己处理')
            say('   ⚠ 处理完后点「停止」再「开始」；或直接在游戏里继续')
            say('')
            status('★ 抽到要停的预言 · 已停下（现场保留）')
            break
        # ⛔ 2026-10-11 **删掉 `collect_stop` / `shrine_stop` 两个分支** ✓
        #   （用户要求去掉[临时]采集停止 ⇒ 这两个 `why` 已**没有任何产生者** ✓）
        #   ⇒ 传承祭坛/机巧宝箱怪现在正常走 `popups()` → `shrine_flow`/`mimic_flow` ✓
        if why == 'stopped':
            # ⭐ 2026-09-29 用户口径「点 ■ 要立即停止」：**连退图都别做**（打图动作立刻全停 ✓）
            #   留在图内即可：游戏账号空闲、下次启动可接着打这张图 ✓
            STATS['stopped'] = '用户点了停止'
            say('⏹ 已停止：留在图内，不退图不补点（下次启动可接着打 ✓）')
            status('已停止 · 留在图内（下次可接着打）')
            break
        # ⭐⭐ 2026-10-04 真机事故修：**原来是裸调用** ⇒ `finish_map` 里任何一处抛异常
        #   （真机实证：`touch()` 抛 `ConnectionResetError [WinError 10054]`，模拟器踢了
        #    触摸通道）都会**一路穿出 `run_maps` → `main` ⇒ 整局退出码 1** ✗✗
        #   （`runs/_crash.log` 的栈就是 `run_maps` → `finish_map` → `b.tap` → `touch`）
        #   ⇒ 现在：单张退图出错 ⇒ 只把这张记为失败，交给下面**已有的"退图失败 ⇒
        #     检测游戏是否还活着 ⇒ 自动恢复"那条路**处理，绝不无声崩掉 ✓
        #   ⚠ 底层 `mapbot.tap()` 也一并加了"连接类错误 ⇒ 重连重试一次"（见 `_touch_retry`）
        # ⭐⭐⭐ 2026-10-05 **退图耗时细账**（用户报「平均 66 秒/张，比以前慢很多」）
        #   实测：旧代码退图 **3 秒/张**（中位）⇒ 新代码 **6 秒**（19:28）/**10 秒**（20:39）
        #   ⇒ 先用计时把这一段拆开，别再猜（跑完看 `gui_*.log` 的 `退图细账` 一行 ✓）
        _t_fin0 = time.time()
        try:
            # ⭐ 2026-10-26 **把当前图的图名传进 `finish_map`**
            #   ⇒ 退图时那次 `board_hidden` 分类**用真 code** ⇒
            #     **不做「15 个 code 全量消歧」** ⇒ 不再打印「（图名未读到）」+ 省 ≈4 秒 ✓
            #   （真机 22:41 那把的日志铁证，详见 `finish_map` docstring）
            #   ⛔⛔⛔ **必须用模块级 `_LAST_MAPNAME`，不能用 `st`** ——
            #     `st` 是 `run_one_map()` 的**局部变量**，**这里（`run_maps`）根本看不到它**
            #     ⇒ 我第一版写 `st.get('mapname')` ⇒ **NameError** ⇒
            #        「退图这一步抛异常」⇒「退图没成功，已停止」⇒ **整局停在那** ✗✗
            #        （真机实测：用户报「退图这一步抛异常 NameError」）
            #        ⇒ 已改用模块级变量（同 `_CODE_DECIDED` 的既有模式 ✓）
            ok = finish_map(b, log, mapname=_LAST_MAPNAME.get('name'))
        except Exception as _e8:      # noqa: BLE001
            ok = False
            log.append({'map': mi, 'finish_raised': repr(_e8)[:200]})
            say('   ⚠ 退图这一步抛异常（已按"退图失败"处理，不中断整局）：%r' % (_e8,))
            status('⚠ 退图出错 · 正在尝试自动恢复')
        _fin_secs = time.time() - _t_fin0
        # ⭐⭐⭐ 2026-10-06 修**恒等假字段**（用户问「图内 10.9s 这是什么东西」查出来的）：
        #   原来是 `% (_fin_secs, _fin_secs, time.time() - t_one)` ——
        #   第 1、2 个实参**是同一个变量** ⇒「图内」永远 ==「finish_map」✗
        #   而注释的本意是「把这一段**拆开**，别再猜」⇒ 那个位置该是**另一个量** ✓
        #   ⇒ 现在三个数各有其义（**互不包含、互不重复**）：
        #       · 图上   = **进图完成 → 开始退图**（`_t_in` 记在"已进图"那一刻）
        #                  = 真正在图里探索/打怪的时间 ✓
        #       · 退图   = `finish_map` 这一步（结束冒险 → 回到选图界面）✓
        #       · 本轮   = `t_one` → 现在，**与下面 `map_secs` 和「完成（N 秒）」逐值相同**
        #                  ⚠ `t_one`（`:11346`）是在**进图之后**才赋的 ⇒ 本轮**不含进图段**；
        #                    这里如实叫「本轮」而不是「整周期」（后者会被误读成含进图）✓
        #   ⚠ `_t_in` 取不到时（`COLLECT_ONLY` 等提前 return 的路径）如实写 `?`，**不编数** ✓
        #   ⚠⚠ 用 `locals()` 判存在，**别用 `dir()`** —— `dir()` 无参返回当前作用域名字表，
        #      在函数里拿不到"赋值过没有"的语义，容易写出恒真的判据 ✗
        _fig_in = (_t_fin0 - _t_in) if '_t_in' in locals() else None
        _fig_all = time.time() - t_one
        log.append({'map': mi, 'finished': ok, 'finish_secs': round(_fin_secs, 1),
                    'in_map_secs': (round(_fig_in, 1) if _fig_in is not None else None),
                    'cycle_secs': round(_fig_all, 1)})
        try:
            say('   · 退图细账：图上 %s ｜ 退图 %.1fs ｜ 本轮 %.1fs'
                % (('%.1fs' % _fig_in) if _fig_in is not None else '?',
                   _fin_secs, _fig_all))
        except Exception:       # noqa: BLE001
            pass
        if ok:
            STATS['maps'] += 1
            STATS['map_secs'].append(time.time() - t_one)
            STATS['current_map'] = 0        # 正常跑完就不算「被停止」
            STATS['current_secs'] = 0
            STATS['recover_n'] = 0          # ⭐ v1.12：跑完一张 ⇒ 恢复计数清零 ✓
        say('   已退出地图并回到选图界面' if ok else '⚠ 退图没成功，已停止')
        if ok:
            status('第 %d 张图 · 完成（%.0f 秒）' % (mi + 1, time.time() - t_one))
        else:
            status('⚠ 退图没成功 · 已停下')
        # ⭐⭐ 2026-09-30 用户报「刷了 10 把没触发自动装备升星」⇒ 触发点从"第 N+1 张之前"
        #   改成**"每跑完 BAG_EVERY 张"**（此刻人正站在选图界面，正是去背包升星的时机 ✓）：
        #     · 用户口径「每 10 张图升一次星」现在字面成立：第 10/20/30… 张跑完就升 ✓
        #     · 旧写法（循环开头 `mi>0 and mi%10==0`）要求开跑第 11 张才触发 ⇒
        #       maps=10 的一局 **一次都不触发**（真机 14:12：刷完 10 张、调用 0 次 ✓ 实锤）
        #   `STATS['maps']` 在这里刚 +1 过（上一行几下）⇒ 用它计数最稳（恢复重试不会重复计 ✓）
        if ok and BAG_EVERY and STATS['maps'] and STATS['maps'] % BAG_EVERY == 0:
            try:
                bag_upgrade(b, log, tag='bag%d_' % STATS['maps'])
            except Exception as e:      # noqa: BLE001
                log.append({'bag': 'error', 'e': repr(e)[:120]})
                say('   ⚠ 背包升级异常：%r（已跳过，继续刷图 ✓）' % (e,))
        if not ok:
            # ⭐⭐ 2026-10-01 崩溃自恢复（用户要求）：退图失败最常见的原因就是
            #   **游戏进程已死/冻结**（画面冻结 ⇒ OCR 恒定 ⇒ 一路 idle 到超时）。
            #   ⇒ 退图失败不再直接停：先检测+恢复（game_recover：拉起+热更/登录导航），
            #     恢复成功 ⇒ continue 进下一张图；恢复失败 ⇒ 才停止 ✓
            _items_pre = b.ocr(tag='pre')
            if not _game_screen_ok(_items_pre):
                say('   ⚠ 画面无游戏特征 ⇒ 自动恢复（拉起+热更/登录导航）')
                status('画面不是游戏 · 正在把游戏拉回来…')
                log.append({'recover': 'trigger_after_finish_fail'})
                if game_recover(b, log, tag='recf%d_' % mi):
                    _items_pre = b.ocr(tag='pre')
                    log.append({'recover': 'recheck_after_finish_fail',
                                'ok': _game_screen_ok(_items_pre)})
                    # ⭐⭐⭐ 2026-10-01 v1.12 真机（**朋友那台**）报「连地图都进不去，一直显示
                    #   正在把游戏拉回来」——本分支原来**无计数**：恢复成功就 `continue` 下一张，
                    #   下一张要是又失败 ⇒ 又恢复 ⇒ **无限"拉回来"** ✗
                    #   ⇒ 连续 3 次"拉回来自检通过、但下一张还是跑不动"就**停整局**并提示发日志 ✓
                    STATS['recover_n'] = STATS.get('recover_n', 0) + 1
                    if STATS['recover_n'] >= 3:
                        STATS['stopped'] = ('连续 %d 次把游戏拉回来、但下一张仍跑不动'
                                            % STATS['recover_n'])
                        say('   ⚠ 连续 %d 次自动恢复后仍跑不动 ⇒ 停止（请把 logcat 发我 ✓）'
                            % STATS['recover_n'])
                        status('⚠ 拉回游戏后仍跑不动 · 已停下（请把日志发我）')
                        flush(log)
                        break
                    STATS['stopped'] = ''
                    continue          # 恢复成功 ⇒ 继续刷下一张 ✓
                STATS['stopped'] = '游戏自动恢复失败'
                say('   ⚠ 游戏自动恢复失败 ⇒ 停止（可在悬浮条再点 ▶ 重试）')
                status('⚠ 游戏起不来 · 已停下（可再点 ▶ 重试）')
                break
            STATS['stopped'] = STATS['stopped'] or '退图失败'
            break
    # ⭐⭐⭐⭐ 2026-10-14 **收工后的公会日常**（用户口径，原话）：
    #   「**这些我打算是体力刷完自动去做**」
    #     · 派遣任务：「不用放弃」「不召回」
    #     · 炼金：「炼金往上滑就能看到个有感叹号的箱子」
    #             「这时候要点满星，然后点开始炼金」
    #   ---- 放在哪：**地图循环之后、收尾统计之前** ✓ ----
    #     此刻人正站在**选图界面**（刚退完图）⇒ 正是进公会干活的时机，
    #     与 `bag_upgrade`（每 N 张图一次）同一个位置语义 ✓
    #   ---- 什么时候跑 ----
    #     · 只在**真跑过图**（`STATS['maps'] > 0`）时做 —— 没跑图就说明
    #       进图失败/被顶号，这时候去点公会纯属添乱 ✗
    #     · **要不要做、做哪几件，由 GUI 那两颗勾选决定**（2026-10-14 用户口径
    #       「炼金和派遣勾选选项加在没体力自动用补给前面」）：
    #         `MAPBOT_GUILD_TASKS=1` ⇒ 派遣任务 ｜ `MAPBOT_ALCH_AUTO=1` ⇒ 炼金
    #       两个都关 ⇒ `_guild_daily` 自己会跳过（这里不必判，读环境变量重复 ✗）
    #   ---- 失败了怎么办 ----
    #     **绝不能影响收尾**：整段包 try/except，出错只记日志、继续往下走 ✓
    #     （本项目铁律：收尾阶段任何异常都不许把整局带崩 ✗）
    # ⛔⛔ 2026-10-19 **只在"因为体力停止"时才做收工日常**（用户口径）
    #   ---- 用户原话 ----
    #     「立即停止后怎么去做日常了。日常招募免广这些**只在因为体力停止才触发**」
    #   ---- 病 ----
    #     旧判据只有 `STATS.get('maps')`（跑过图就做）⇒ 完全不看**为什么停** ✗
    #     真机：抽到「元素·紫色」⇒ `foretell_stop` 停下 ⇒ `maps=1`
    #     ⇒ **照样去跑公会日常/招募/免广** ✗✗（用户现场：面板还留着呢）
    #   ---- 修法（白名单，不用黑名单）----
    #     ① `stopped` 含「体力」⇒ 做（唯一该做的情况 ✓）
    #     ② `stopped` **为空** ⇒ 也做（正常跑完所有张 = 体力自然耗尽 ✓）
    #     ③ 其余一律跳过（含：用户停止 / 红装 / 预言石碑 / 顶号 / 崩溃 /
    #        认不出棋盘 / 计划走不下去 / 退图失败 / 到点自动停 …）
    #     ⚠ 用白名单而不是枚举黑名单 —— 以后**新增停止原因时默认不做日常**
    #       （fail-closed ✓ 与"判据宁可保守"的既有原则一致）
    # ⭐ 2026-10-26 **与「自动重开」共用同一份判据**（`_stop_allows_afterwork()`）
    #   ⇒ 两处不再各写一份（这正是「预言石碑/红装停了却还重开」的根因）✓
    _stop_why_daily = str(STATS.get('stopped') or '').strip()
    _ok_aw_daily, _why_aw_daily = _stop_allows_afterwork()
    _ok_daily = bool(STATS.get('maps')) and _ok_aw_daily
    try:
        if not STATS.get('maps'):
            say('   · 这局一张图都没跑完 ⇒ 跳过公会日常（派遣/炼金）')
        elif not _ok_daily:
            say('   · 停止原因「%s」不是"体力用尽" ⇒ **跳过收工日常**'
                '（公会日常/免费招募/免广告都不碰 ✓）' % _stop_why_daily)
            log.append({'guild_daily': 'skip_not_stamina',
                        'why': _stop_why_daily})
        else:
            _guild_daily(b, log)
    except Exception as _e_gd:      # noqa: BLE001
        import traceback as _tb_gd
        log.append({'guild_daily': 'error', 'e': repr(_e_gd)[:160],
                    'trace': _tb_gd.format_exc().splitlines()[-4:]})
        say('   ⚠ 公会日常出错（**不影响收尾** ⇒ 继续）：%r' % (_e_gd,))
    flush(log)
    STATS['running'] = False
    say('==== 全部结束，共 %.0f 秒；日志：%s' % (time.time() - t_all, LOG_PATH))
    if STATS['maps']:
        # ⭐⭐⭐ 2026-10-01 v1.08 用户报「悬浮窗还是只写了收工，**没有写是因为体力不够 50 才收工**」
        #   根因：`STATS['stopped']`（= 真正的结束原因，由 `pre_gate` 那一路写成
        #   「体力不足（37 < 50）」之类）**没被拼进收工那行** ⇒ 悬浮条永远只显示"收工：刷完 N 张" ✗
        #   ⇒ 把原因并进同一行（⚠ 文案要避开 OCR 关键词，且别太长 ✓）
        _why = str(STATS.get('stopped') or '').strip()
        status('收工：刷完 %d 张 · %s'
               % (STATS['maps'],
                  _why or ('平均 %.0f 秒/张'
                           % (sum(STATS['map_secs']) / max(1, len(STATS['map_secs']))))))
    else:
        _why0 = str(STATS.get('stopped') or '').strip()
        status('收工：一张都没跑完%s' % ('（%s）' % _why0 if _why0 else ''))
    say(summary_text())
    dump_summary()
    # ⭐ 2026-09-27：收尾再读一次体力 ⇒ 最后一张图的"25 + 图内消耗"也能算出来 ✓
    try:
        _st_end = stamina(b.ocr(tag='end'))
        if _st_end is not None:
            STATS['stamina_entries'].append((_st_end, time.time()))
            say('收尾体力 %d（已记入统计 ✓）' % _st_end)
    except Exception:       # noqa: BLE001
        pass

    if DUMP_AT_END:
        for e in log:
            print(e)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        STATS['stopped'] = STATS['stopped'] or '手动中断（Ctrl+C）'
        STATS['running'] = False
        say(summary_text())
        dump_summary()
    except SystemExit:
        # 锁冲突 / 红装锁等**正常退出路径**（main 里 return 或显式退出）⇒ 原样放行，
        # 不写 crash 日志（否则假崩溃太多 ✗）
        raise
    except BaseException as _e:        # noqa: BLE001
        # ⭐⭐⭐ 2026-09-28 加固：任何未捕获异常都**留下证据**
        #   背景：21:36 那把循环打印「进图前体力」后**无声消失**（无 traceback、
        #   无 summary、无 [warn]）⇒ 事后完全无法定位死因 ✗ 只能靠这个兜住。
        #   崩溃记录写 `runs/<tag>/_crash.log`（append，不覆盖历史）。
        # ⚠⚠ 2026-10-02 加固：原来这里的证据写入包在 `try` 里，而 `say()` 在
        #   pythonw（GUI 起子进程，stdout=None）下会炸 ⇒ **证据链整条断掉**，
        #   实测 GUI 崩了三次都没生成 `_crash.log`，只剩一句「退出码 1」✗
        #   ⇒ 落盘与 say 彻底分开：落盘用**最原始**的 open()，失败也只吞不抛；
        #     并且先落盘再喊话（保证喊话炸了也已经有证据）✓
        import traceback as _tbm
        try:
            _tb = _tbm.format_exc()
        except Exception:       # noqa: BLE001
            _tb = 'traceback 取不到：%r' % (_e,)
        _crash = os.path.join(RUNS, INSTANCE_TAG or '', '_crash.log')
        try:
            d = os.path.dirname(_crash)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(_crash, 'a', encoding='utf-8') as _f:
                _f.write('\n===== %s  pid=%d  dev=%s =====\n%s\n'
                         % (time.strftime('%Y-%m-%d %H:%M:%S'), os.getpid(),
                            INSTANCE_DEV, _tb))
        except Exception:       # noqa: BLE001
            pass
        try:
            say('💥 未捕获异常 ⇒ 已写入 %s（可据此定位死因）' % _crash)
            say(_tb)
        except Exception:       # noqa: BLE001
            pass
        STATS['stopped'] = STATS['stopped'] or ('崩溃：%s' % repr(_e)[:80])
        STATS['running'] = False
    finally:
        try:
            STATS['running'] = False
            dump_summary()
        except Exception:       # noqa: BLE001
            pass
