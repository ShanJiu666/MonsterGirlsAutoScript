# -*- coding: utf-8 -*-
"""bot_gui.py · 幻想少女公会自动探索 —— 图形界面（tkinter/ttk，Python 自带，无需安装）

桌面快捷方式指向本文件（用 venv 的 pythonw.exe，不带黑框）：
    连刷到体力耗尽 / 跑 1 张 / 停止 / 环境检查 + 实时日志 + 实时棋盘

⚠ 跑的时候别在模拟器里手动点（会互相打架）；要停就点「停止」。

════════════════════════════════════════════════════════════════════════
2026-10-11 · UI 重写（依据 `docs/05-PC端UI重设计方案与开发规划.md`）
════════════════════════════════════════════════════════════════════════
本文件从 **1681 行上帝类** 改成**薄壳**：只负责「建窗 + 接线」，具体职责搬进 `bot_gui_ui/`：

    bot_gui.py                ← 你在这里：启动链路 + 主窗口组装（薄壳）
    bot_gui_ui/theme.py       ← 全部色值/字号/间距 + ttk 样式（治 P2「样式散落硬编码」）
    bot_gui_ui/widgets.py     ← StatusDot / StatCard / Sparkline / BarChart / BoardCanvas
    bot_gui_ui/datasource.py  ← last_summary / loop_log / 三种锁 / 热更状态（**只读**）
    bot_gui_ui/services.py    ← LoopRunner（子进程）/ Prefs（配置）/ DeviceService（设备）
    bot_gui_ui/dialogs.py     ← 设备选择框 / 手动填设备号 / 只读文字框
    bot_gui_ui/devicesel.py   ← 设备三态逻辑（依赖注入，便于门禁替换弹窗）

⭐ 三条「重写不许破」的硬约束（规划 §5 第一约束 + §7 技术约束表）
--------------------------------------------------------------
1. **启动链路逐字不变**（`启动.bat` → `bootstrap.py` → `runpy` 同进程起本文件 → 点 ▶ 起子进程）：
   设备三态 → 720×1280 自检 → 单例锁 → 建窗 → `after(3000, hotupdate.confirm_alive)`
   ⚠ `confirm_alive` 是**热更回滚判据**（界面真起来了才算确认）⇒ 少一次调用就会被误判回滚 ✗
2. **子进程命令行 / env / 配置文件路径与格式一个字都不许变**
   （子进程靠 **mtime 热读** `runs/target_types.json`；拼装逻辑在 `services.LoopRunner` ✓）
3. **线程纪律**（治 P3）：一切后台 → UI 更新走 `queue + root.after`；
   一切 subprocess（adb / 查重 / 扫屏 / 热更）都在**后台线程**里跑 ⇒ 主线程不再冻住 ✓

⚠⚠ 为什么本文件里还留着「极速截图 sidecar」那 200 行
---------------------------------------------------
`verify_startup_speed.py` 用 **AST** 把这几件事**钉在 `bot_gui.py` 里**（发 `p` 判存活 /
一个取帧探测都不许有 / 卡死只杀本端口那个 / `^import socket$` 在模块级 …）——
那是 2026-10-06 连错三版才换来的判据（详见 `_sidecar_ping` 的 docstring）。
⇒ 重写时**原样保留**（`services.DeviceService` 通过注入调用它 ✓），
  结论：**布局层是新写的，启动/截图链路是原样搬运的**。
"""
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
# ⭐ 2026-10-02：adb 改走 `paths.py` 自动探测（原来写死本机 SDK 路径，
#   朋友机器上必然不存在 ⇒ 连「环境检查」都过不去）。
#   `P.ADB` 是**惰性**的：只有真正被当 argv 用时才付探测代价，不拖慢 GUI 启动。
sys.path.insert(0, HERE)
import paths as P                                     # noqa: E402
# ⭐⭐ 2026-10-03 朋友版开关（见 friend_mode.py）：**运行期读**，不再靠打包时改源码。
#   以前是 build_pkg.py 用字符串替换（关精确规划 + 去掉两个勾选框）⇒ 一发热更补丁就被
#   冲回开发版 ✗ ⇒ 现在与热更彻底解耦：开发机没有 friend_mode.flag 就完全是开发版行为 ✓
try:
    import friend_mode as _FM
    FRIEND = _FM.IS_FRIEND
except Exception:                                     # noqa: BLE001
    FRIEND = False

from bot_gui_ui import dialogs, theme                  # noqa: E402
from bot_gui_ui import devicesel                       # noqa: E402
from bot_gui_ui import ctk_theme                       # noqa: E402  T6 双主题色板
from bot_gui_ui.ctk_widgets import CtkCard, ThemeSwitch      # noqa: E402  T6 ctk 仪表盘小卡 + 浅深开关
from bot_gui_ui.datasource import (HotState, LockState, LoopLogTail,   # noqa: E402
                                   SummaryWatcher)
from bot_gui_ui.services import (CNW, DeviceService, LoopRunner,       # noqa: E402
                                 Prefs, gui_log_file)
from bot_gui_ui.services import tag_for as _tag_for_impl               # noqa: E402
from bot_gui_ui.widgets import BoardCanvas, StatusDot                  # noqa: E402
import customtkinter as ctk                            # noqa: E402  ⭐ T6：整窗迁 ctk

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════════════════
# T6 · customtkinter 迁移（工单 `06-PC端UI执行工单.md` §T6，2026-10-12）
# ══════════════════════════════════════════════════════════════════════
#   用户已看双主题效果图并定稿 ⇒ **§0 表里的视觉细节不许再改**。三条硬边界（门禁钉着）：
#     ① 日志框 = **tk `ScrolledText`**（`verify_lock_kind` 调 `.get('1.0','end')`）
#     ② 存图勾选 = **`tk.Checkbutton(bar2, …)`**（`verify_hotupdate` T16f 按字面量钉）
#     ③ 棋盘 = **tk `BoardCanvas`**（ctk 无等价自绘）
#   ⇒ 其余全部 ctk；**tk 那几样必须手动重设色**（ctk 的 `set_appearance_mode` 管不到它们 ✓）

# ⭐ T6 §7①/§8 表 1：**字号阶梯**已收进 `ctk_theme`（`FS_NUM/FS_TITLE/FS_BODY/FS_SUB/FS_HINT`）
#   全窗口只用那 5 档 ⇒ 组件里**不许再写裸数字**（倒挂的根因就是散落的 `_f(13)` 之类 ✓）
#   ⇒ 旧的裸 `_f(N)` 助手的**全部 38 处调用已替换**，helper 本身**已删除**（不留死代码 ✗）


# tk 侧要跟着主题走的常量（ctk 控件自动换，**tk 控件只能重设**）
_TK_THEME_KEYS = (('bg', 'C_BG'), ('card', 'C_CARD'), ('border', 'C_BORDER'),
                  ('ok', 'C_OK'), ('warn', 'C_WARN'), ('run', 'C_RUN'),
                  ('off', 'C_OFF'), ('primary', 'C_PRIMARY'),
                  ('primary_d', 'C_PRIMARY_D'))

# ⭐ 页签容器"归位"用的锚点：浅色板那两个卡底色（判某个 Frame 原来是卡底还是次级卡底 ✓）
#   ⚠ 写死这两个值（而不是 import 私有表）：它们是 §T6 §8 表 2 的**定稿值**，
#     万一以后改色，改这里 + `ctk_theme` 两处（自检会盯着"页签底随主题变"✓）
_LIGHT_CARD = '#FFFFFF'       # = ctk_theme 浅色 card
_LIGHT_CARD2 = '#F5F6F8'      # = ctk_theme 浅色 card2


ADB = P.ADB
DEV = '127.0.0.1:16384'
LOG_DIR = P.RUNS
# ⚠ 2026-10-18 目录拆分后：业务 .py 全在 core/，而 HERE = 仓根
#   ⇒ 必须用「本文件所在目录」，否则拼出的路径根本不存在 ✗
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
HOT_PY = os.path.join(_SELF_DIR, 'hotupdate.py')

# ⭐⭐ 实时计划/进度 —— 从**子进程 stdout**里捡（2026-10-11 用户真机反馈后加的）
#   ⛔ 病（用户原话）：「**实时棋盘的更新速度有点慢，真机都要执行完了才出执行图**」
#      根因在数据源：`loop_log.json` 是**整体覆写**，而 `explore_loop.flush(log)`
#      只在**每张图结束**调一次（`run_one_map` 返回之后）⇒ 图内任何东西都到不了 GUI ✗
#   ⇒ 但子进程的 **stdout 是实时的**（`say()` 直接 `print(flush=True)`），
#     而**精确规划**在算出来那一刻就打了一行完整的计划（含**全序**，上限 10 步 ✓）：
#         `       · 精确规划：最省体力 13，5 步；先执行 ['1,7', '3,5', '3,4', '3,1', '4,2']`
#     ⇒ 捡这行 ⇒ **规划一算出来就出执行图**（不用等退图）✓
#   ⚠ 为什么不捡 `status()` 那行（`› 规划：体力 13 / 5 步 → …`）：它**只打前 4 格**
#     （`_pv = ' '.join(… for p in _disp[:4])`）—— 那正是用户报的「规划了 5 步只显示 4 步」
#     的来源之一，不能拿它当完整计划 ✗
_RE_PLAN = re.compile(r'精确规划：最省体力\s*([0-9.]+)\s*[，,]\s*(\d+)\s*步[；;]\s*先执行\s*\[(.*?)\]')
_RE_CELL = re.compile(r"[（('\"]*(\d+)\s*,\s*(\d+)")
_RE_ROUND_LINE = re.compile(r'^\[r\d+\]')
# ⭐ 2026-10-13 P1-a（工单 07 §2）：从状态行 `› 第 3 张图 · …` 里抠出"第几张"
#   用途：顶栏「运行摘要」显示「第 3 张 · 体力 785→34」⇒ 不点开就知道跑到第几张 ✓
#   ⚠ 抠不到就退化成「N 张」（见 `_run_summary_text`）⇒ **绝不抛、绝不空白** ✓
_RE_MAPIDX = re.compile(r'第\s*(\d+)\s*张图')


def _title_text(tag, device):
    """窗口标题：**带上当前生效的热更补丁**（用户 2026-10-03：「试试能不能」热更）

    ⇒ 一眼看出端上跑的到底是哪版代码：`... · 补丁 5bdb547f` / `· 出厂版`，
      刚激活还没确认时会多一个「（待确认）」（约 3.5 秒后自动刷新掉 ✓）
    """
    base = '幻想少女公会 · 自动探索%s（%s）' % ('  [%s]' % tag if tag else '', device)
    try:
        sfx = HotState(HERE).title_suffix()
        return (base + '  ' + sfx) if sfx else base
    except Exception:       # noqa: BLE001  （没有更新器时按出厂版显示）
        return base


def parse_args():
    import argparse
    ap = argparse.ArgumentParser()
    # ⚠ default=None 而不是 default=DEV：必须能区分「用户没传」和「传了默认值」。
    #   None = 双击启动 ⇒ 走下面的 choose_device() 选设备；
    #   有值 = 「多开一个新号」起的子进程（已绑定死）⇒ **不能再弹选择框**。
    ap.add_argument('--device', default=None, help='本窗口绑定的 adb 设备号（多开子进程用）')
    ap.add_argument('--tag', default='', help='多开实例名（隔离截图/日志/统计目录）')
    return ap.parse_args()


# ══════════════════════════════════════════════════════════════════════
# 兼容壳：设备选择（`verify_devicesel.py` 按这 6 个名字 monkeypatch ⇒ **一个都不许改名**）
# ══════════════════════════════════════════════════════════════════════
def tag_for(inst, port):
    """MuMu 端口 -> 日志目录名（acc1 / acc2 …）—— 真逻辑在 `services.tag_for` ✓"""
    return _tag_for_impl(inst, port)


def _msg(title, text, icon='warn'):
    """系统弹窗（转发到 `dialogs.msg`；**故意保留 ctypes 原生框**，理由见 dialogs.py）"""
    return dialogs.msg(title, text, icon)


def _pick_dialog(running, inst, busy):
    """多个实例时的选择框（转发到 `dialogs.pick_dialog`；门禁会整个替换掉它 ✓）"""
    return dialogs.pick_dialog(running, inst, busy)


def _manual_dialog():
    """兜底：手打设备号（转发到 `dialogs.manual_dialog` ✓）"""
    return dialogs.manual_dialog(DEV)


def choose_device(given=None, given_tag=''):
    """决定本窗口绑哪台设备 -> (device, tag) | (None, None)（= 放弃启动）

    ⚠⚠ `verify_devicesel.py` 的测法是「**把 `bot_gui._msg` / `_pick_dialog` /
      `_manual_dialog` 换成假的**，再调 `bot_gui.choose_device(...)`」
      ⇒ 这里必须**在调用时才去查模块级那几个名字**（不能提前绑定、更不能在
        `devicesel.py` 里直接 `from .dialogs import msg`）—— 否则 monkeypatch
        **静默失效**、门禁测的是个假东西 ✗（本仓"假绿"踩过多次）
    """
    return devicesel.choose_device(given, given_tag,
                                   msg=_msg, pick=_pick_dialog,
                                   manual=_manual_dialog, tag_fn=tag_for,
                                   default_dev=DEV)


# 极速截图 sidecar（MaaFw + MuMu 官方截图接口，跑在**独立 venv** 里）
# ⭐⭐ 2026-10-02：统一走 `paths.find_maa_py()`，**不再各写一份路径**
#   （`run_collect.py` 之前还写死着 `D:\幻想少女公会\...`，两边不一致 ⇒
#    一个能起 sidecar、另一个起不来，用户完全看不出差别）。
#   ⛔ 之前这里虽然指向仓内 `_maa_venv`，但那个 venv **根本不存在** ⇒
#      `ensure_sidecar()` 每次都**静默退回 adb**（0.33s/张，慢 25 倍），
#      用户全程没察觉（只打一行「⚠ 没找到 MAA 环境」，不报错）。
#   ⇒ 现已在仓内**重建**该 venv（MaaFw 5.14.0 / numpy 2.4.6，与旧的一致）✓
#   顺序：环境变量 `MAPBOT_MAA_PY` → 仓内 `_maa_venv` → 其它候选
try:
    from paths import MAA_PY as _maa_py
    MAA_PY = _maa_py
except Exception:                       # noqa: BLE001  paths 不可用时退回
    MAA_PY = (os.environ.get('MAPBOT_MAA_PY')
              or os.path.join(HERE, '_maa_venv', 'Scripts', 'python.exe'))


def sidecar_port(device):
    try:
        p = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        return 19999
    return 19999 + max(0, (p - 16384) // 32)


def _sidecar_ping(port, timeout=1.0):
    """sidecar **进程存活**探测：发 `p`，收到 `pong` ⇒ 服务活着 ✓

    ⭐⭐⭐⭐⭐ 2026-10-06 **二次修正** —— 我上一版用「能不能取到一帧」当存活判据，**是错的**，
      已被实测证伪（`_tmpman/probe_ping_vs_grab.py`）：

        端口   设备状态     `p`（不碰设备）        `g`（取帧）
        19999  设备**不在**  b'pong' (0.01s)      **无应答**（15s 都不回）
        20000  设备**不在**  b'pong' (0.00s)      **无应答**
        20001  设备**在**    b'pong' (0.00s)      b'MUMU...'（正常帧 ✓）

      ⇒ 三个 sidecar **进程全都活着**；`g` 不回的真因是**设备没开**（MAA 取不到帧就挂住），
        **不是服务卡死**。而"设备没开"与"服务卡死"在客户端**长得一模一样**
        ⇒ 上一版判据会把**健康的** sidecar 判成卡死 ⇒ `ensure_sidecar` **杀掉一个好好的服务**，
          还可能**打断另一个实例正在跑的 bot** ✗✗（这就是我引入的缺陷）

    ⇒ 判据只能有一个：**`p`/`pong`**（服务在不在跑，**不碰设备**）⇒ 决定"要不要杀"
    ⚠⚠⚠ 2026-10-06 **第三次修正 —— 我把「取帧探测」放进 `ensure_sidecar` 也是错的**，
      定点实测（`_tmpman/probe_g_sideeffect.py`，只发一次 `g`、设备没开）：

        · 发 `p` ⇒ sidecar 日志增长 **0 字节** ⇒ **真·无副作用** ✓
        · 发 `g` ⇒ 20 秒内日志增长 **1623 字节**，内容是 MAA 反复
          `connect failed` / `re-connect failed` / `controller screencap failed`，
          **还去执行了 `adb kill-server`** ✗✗

      ⇒ 机制：`g` 会**真的让 MAA 去碰设备**（取不到就重连、重连失败就 kill-server）。
        而 `ensure_sidecar` 是**开窗时无条件调**的 —— 用户**先开窗口、后开模拟器**是常态
        ⇒ 每开一次窗口就往 MAA 里灌一轮重连风暴、还可能把 adb server 杀掉 ✗✗
      ⇒ 结论：**探测必须只发 `p`**；「能不能取帧」是 `fastcap` 自己的事（失败就退 adb），
        **不在启动路径上预先试探** ✓
      ⚠ 附带教训：我最初**就是被这些 MAA 红字误导**去怀疑"sidecar 卡死"的
        —— 那些红字是**我自己的探测制造出来的** ⇒ **取证手段会污染证据**（§3 老坑新实例）
    """
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    except Exception:       # noqa: BLE001
        return False
    try:
        s.settimeout(timeout)
        s.sendall(b'p')
        return s.recv(16) == b'pong'
    except Exception:       # noqa: BLE001
        return False
    finally:
        try:
            s.close()
        except Exception:       # noqa: BLE001
            pass


def _sidecar_kill(port, log=print):
    """把**卡死**的 sidecar 杀掉（只杀"命令行里带本端口"的那个，绝不错杀 ✗）

    ⚠ 为什么要杀：端口被一个卡死的进程占着 ⇒ 新 sidecar 起不来（`bind` 失败），
      而旧判据又会说"已在运行" ⇒ **永远修不好**。必须先把占着端口的那个清掉 ✓
    ⚠ 为什么按**命令行里的端口**匹配：同一台机器上多开时会有好几个 sidecar
      （19999/20000/20001…）⇒ 只杀 `--port <port>` 的那个，别的实例不受影响 ✓
    """
    try:
        ps = ('Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | '
              "Where-Object { $_.CommandLine -match 'maa_sidecar' -and "
              "$_.CommandLine -match '--port\\s+%d(\\s|$)' } | "
              'ForEach-Object { $_.ProcessId }' % int(port))
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, errors='replace',
                           timeout=20, creationflags=CNW)
        pids = [int(x) for x in (r.stdout or '').split() if x.strip().isdigit()]
    except Exception:       # noqa: BLE001
        return []
    killed = []
    for pid in pids:
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                           capture_output=True, timeout=15, creationflags=CNW)
            killed.append(pid)
        except Exception:       # noqa: BLE001
            pass
    if killed:
        log('⚠ 清掉卡死的极速截图服务（端口 %d，PID %s）'
            % (port, '、'.join(str(x) for x in killed)))
    return killed


def ensure_sidecar(device, log=print):
    """确保这台设备的极速截图 sidecar 在跑（没跑就起一个；起不来就退回 adb，不影响功能）

    ⭐⭐⭐⭐⭐ 2026-10-06 **三次修正**（前两版判据都是错的，见 `_sidecar_ping` 的实测）：
      第一版：只连 TCP ⇒ 卡死但端口开着被判"健康" ✗
      第二版：拿「能不能取到一帧」判存活 ⇒ 设备没开时 `g` 恒不回 ⇒ **误杀健康服务** ✗✗
      第三版（本版）：**连"取帧探测"本身都不能做** —— 实测发一次 `g` 会让 MAA 反复
        重连、**还会 `adb kill-server`**（`_tmpman/probe_g_sideeffect.py`：20 秒 +1623 字节
        红字日志；而发 `p` 是 **0 字节**）⇒ 启动路径**只发 `p`** ✓
      ⇒ 判据只有一个：**`p`/`pong`**（服务在不在跑，不碰设备）⇒ 决定"要不要杀"；
        「能不能取帧」是 `fastcap` 的事，取不到它会自己退 adb，**这里不预先试探** ✓
    ⚠⚠ 本函数被 `services.DeviceService` **注入调用**（在后台线程里）⇒ `log` 回调
      必须是"往事件队列塞"的那种，**不许**直接碰 tk 组件（治 P3 ✓）
    """
    port = sidecar_port(device)
    if _sidecar_ping(port):
        log('✓ 极速截图服务已在运行（端口 %d，进程存活 ✓）' % port)
        return True
    # `p` 都不应答 ⇒ 端口要么没人听、要么**真卡死**占着端口
    try:
        socket.create_connection(('127.0.0.1', port), timeout=0.6).close()
        _sidecar_kill(port, log)        # 连得上却不回 `pong` ⇒ 真卡死 ⇒ 清掉再起 ✓
        time.sleep(0.8)
    except Exception:       # noqa: BLE001  （连都连不上 = 没进程，直接起新的）
        pass
    if not MAA_PY or not os.path.exists(MAA_PY):
        # ⚠⚠⚠ 2026-10-02：原来只打一行「没找到 MAA 环境」就**静默退回 adb**
        #   ⇒ 截图从 0.013s 变 0.33s（**慢 25 倍**），而用户全程**看不到任何异常**
        #   （功能正常，只是慢），于是「一直没装 MAA 快速截图」这件事被掩盖了很久。
        #   ⇒ 现在把**代价写清楚**（不是「慢一些」，是「慢 25 倍」），
        #     并直接给出**修复办法**，让人一眼知道该做什么而不是忽略它 ✓
        log('⚠⚠ 没找到 MAA 极速截图环境 ⇒ 本次退回 adb 截图：**0.33 秒/张（慢 25 倍）**')
        log('    修法（一行）：python -m venv _maa_venv && '
            '_maa_venv\\Scripts\\python -m pip install MaaFw==5.14.0')
        log('    或指定已有环境：set MAPBOT_MAA_PY=<你的 python 路径>')
        return False
    idx = max(0, (int(str(device).split(':')[-1]) - 16384) // 32)
    # ⚠ 2026-10-02：原来 `stdout/stderr=subprocess.DEVNULL` ⇒ **sidecar 起不来时
    #   日志里什么都不留**，只能靠猜（这次就是这样：日志停在 9-25，再无痕迹）✗
    #   ⇒ 改成落盘到 `runs/sidecar_<port>.log`，起不来时**看日志就知道原因** ✓
    _slog = os.path.join(LOG_DIR, 'sidecar_%s.log' % port)
    _serr = os.path.join(LOG_DIR, 'sidecar_%s.err' % port)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _fo = open(_slog, 'wb')
        _fe = open(_serr, 'wb')
    except Exception:                   # noqa: BLE001
        _fo = _fe = subprocess.DEVNULL
    try:
        subprocess.Popen([MAA_PY,
                          os.path.join(os.path.dirname(
                              os.path.abspath(__file__)),
                              'maa_sidecar.py'),
                          '--device', device, '--port', str(port),
                          '--mumu-index', str(idx)],
                         cwd=HERE, creationflags=CNW,
                         stdout=_fo, stderr=_fe)
    except Exception as e:      # noqa: BLE001
        log('⚠ 极速截图服务启动失败：%r（退回 adb 截图）' % e)
        return False
    for _ in range(30):         # 最多等 30 秒（MAA 初始化约 3~20 秒）
        time.sleep(1)
        # ⚠ 等的是 **`pong`**（服务真的在 listen 了），不是裸 TCP —— 裸 TCP 在
        #   进程刚 bind 还没就绪时也会"成功" ⇒ 会过早报"已启动" ✗
        if _sidecar_ping(port):
            log('✓ 极速截图服务已启动（端口 %d，%.0f 秒）' % (port, _ + 1))
            return True
    log('⚠ 极速截图服务没起来 → 本次用 adb 截图')
    return False


# ══════════════════════════════════════════════════════════════════════
# 布局助手：纵向堆叠容器（**治 P1「grid 行号硬编码」**）
# ══════════════════════════════════════════════════════════════════════
class VStack:
    """往容器里 `add()` 就完事 —— **没有手写行号**，权重跟着组件一起挂 ✓

    ⛔ 为什么非要有这个类（`docs/05-...md` §3 P1）：老 `bot_gui.py` 用
      `root.grid(row=0..7)` 手工数行号，**加一排就把后面所有排挤下去**，
      而 `root.grid_rowconfigure(<日志那一排>, weight=1)` 是**写死的数字**
      ⇒ 三次踩同一个坑：`stat box` 盖住日志、日志拿不到权重**高度塌成 0**、
      「日志又看不见了」（用户报过两次 ✗✗）。
    ⇒ 现在权重**挂在组件身上**（`add(w, weight=1)`），加/删排都不会错位 ✓
    """

    def __init__(self, master, style='Bg.TFrame'):
        # ⚠⚠⚠ 2026-10-12 **修「切深色后顶栏那整块颜色错了」的真凶**（用户第 2 次报）：
        #   ── 机制 ──
        #     `VStack.frame` 是**所有 ctk 顶层容器的 master**。若它是 **tk.Frame**，
        #     ctk 建 `bg_color='transparent'` 的子控件时会**从 master 探测底色**，
        #     探到的是**建窗那一刻的单值**；而 `_paint_tk_widgets()` 里
        #     `self.stack.frame.configure(bg=新色)` 又会让 ctk **重探并回写**这个单值
        #     ⇒ `bg_color` 的**双色元组被降级成字符串** ⇒ 之后切主题**再也不跟** ✗✗
        #     （实测定点：`stack.frame.configure` 那一步之后，`titlelab.bg_color`
        #       从 `('#F0F1F3','#1E1F22')` 变成 `'#F0F1F3'` 字符串 ✗）
        #   ── 修法 ──
        #     `VStack` 改用 **`ctk.CTkFrame`**（底色走**双色元组** ⇒ 自己跟主题 ✓）
        #     并**不再**在切换时 `configure(bg=…)` 它（ctk 自己会变 ✓）
        #     ⚠ `grade` 用 `grid` 承载（原 tk.Frame 也是 grid 承载 ⇒ 接口不变 ✓）
        try:
            self.frame = ctk.CTkFrame(master, fg_color=ctk_theme.palette()['bg'],
                                      corner_radius=0)
        except Exception:       # noqa: BLE001  （ctk 不可用时退回 tk，与旧行为一致）
            self.frame = tk.Frame(master, bg=theme.C_BG)
        self.frame.pack(fill='both', expand=True)
        self.frame.grid_columnconfigure(0, weight=1)
        self._n = 0

    def add(self, w, weight=0, pady=0, minsize=0):
        """`minsize` = ⭐ 2026-10-13 新增：**把这一排钉成固定高**（复刻手绘效果图用）

        ⚠ 为什么要它：`ctk.CTkLabel` 默认高恒为 **28px** ⇒ 一排放什么控件，
          这一排就被撑多高（九卡 102、中栏 398）⇒ 与效果图的 78 / 349 对不上 ✗。
          用 `grid_rowconfigure(minsize=…)` 钉住**行高**（比 `grid_propagate(False)`
          更稳：不影响子控件的尺寸请求，只约束这一排的最终高度 ✓）。
        """
        w.grid(row=self._n, column=0, sticky='nsew', pady=pady)
        self.frame.grid_rowconfigure(self._n, weight=weight,
                                     minsize=(minsize or 0))
        self._n += 1
        return w

    def add_row(self, factory, weight=0, pady=0):
        """`factory(frame) -> widget`：先在容器里建一排，再交给调用方填内容 ✓"""
        w = factory(self.frame)
        return self.add(w, weight=weight, pady=pady)


#: ⭐ 2026-10-12 **多格块展开的最低分**（治「营地和附近两格被合体」✗）
#:   低于它 ⇒ **不展开**（只画锚点格）—— 雾里低分乱猜的名字不可信 ✓
#:   实测（`_tmpman/chk_span_min.py`）：真块 99.6% 都 >=0.35，假块全 <0.35 ✓
SPAN_SCORE_MIN = 0.35


class App:
    # ⛔⛔⛔ 2026-10-12 **「停脚本·保现场锁」整套机制已按用户要求删除** ✓
    #   用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」
    #   ---- 演进史（三段，别重蹈）----
    #     ① 2026-09-25 引入：发现红装 ⇒ 写锁 ⇒ **拒绝后续启动**，要人工解锁
    #     ② 2026-10-11 修：锁文件被多种 `kind` 共用，而提示写死"发现了红装"
    #        ⇒ 祭坛锁被报成红装（用户：「**不勾选还是自动停了**」✗）
    #     ③ 2026-10-12 **直接删掉整套**：锁是**多余的一层** ——
    #        用户只要"遇到就停"这个动作；写锁 ⇒ 下次被拒 ⇒ 还得人工解锁 ✗
    #        （本机卡过两次：`kind=shrine` 报成红装、`kind=foretell` 显示"未知类型"
    #          ⇒ 用户问「**怎么解除锁定**」，随后明确「**我不需要这个锁定**」✓）
    #   ⇒ 现在：停脚本之后把现场留着，用户处理完**直接再点「开始」** ✓
    #   ---- 本类里因此删掉了 ----
    #     `_KIND_TXT`（kind→人话名表）／ `red_lock_file` ／ `_read_red_lock`
    #     ／ `show_red_lock` ／ `_refresh_lock_card` ／ `unlock_red`
    #     ＋ 状态页那张锁卡与「红装已处理·解锁」按钮
    #   ⚠ `self._locked` / `self._sync_buttons()` **保留** ——
    #     它们还承载"运行中禁用按钮"的语义，与锁无关 ✓

    def __init__(self, root, device=DEV, tag=''):
        self.root = root
        self.device = device
        self.tag = tag or ''
        self.runs = os.path.join(LOG_DIR, self.tag) if self.tag else LOG_DIR
        self.summary_path = os.path.join(self.runs, 'last_summary.json')
        self.looplog_path = os.path.join(self.runs, 'loop', 'loop_log.json')
        # ---- 四个服务（都不碰 tk ✓）----
        # ⭐⭐⭐⭐⭐ 2026-10-13 **`Prefs` 传 `device`**（用户口径：配置「**和对应窗口绑定**
        #   （选哪个窗口就自动用对应的配置）」✓）
        #   ⚠⚠ 为什么用**设备端口**当键、不用 `tag`：`devicesel.choose_device` 里
        #     **只开一台时 `tag=''`** ⇒ 按 tag 存会全部落到"全局"、分不开 ✗✗
        #     （而"选哪个窗口就用哪份配置"这个需求，**单开场景同样要成立** ✓）
        #   ⇒ 配置落在 `runs/dev_<port>/`（与日志 `runs/<tag>/` 并列、互不干扰 ✓）
        #   ⚠ `root=LOG_DIR` **必须传**：不传会用 `HERE/runs` 硬拼 ⇒ **绕不过
        #     自检/测试对 `LOG_DIR` 的重定向** ⇒ 会在真 `runs/` 下建目录 ✗
        #     （这条是 `_selftest_ui` 当场抓出来的 ✓）
        self.prefs = Prefs(HERE, self.runs, device=self.device, root=LOG_DIR)
        self.runner = LoopRunner(PY, HERE, self.runs, self.tag)
        self.dev = DeviceService(PY, HERE, ADB, LOG_DIR, self.tag,
                                 tag_fn=tag_for, sidecar_fn=ensure_sidecar)
        self.locks = LockState(LOG_DIR, self.device, self.tag)
        self.hot = HotState(HERE)
        # ---- 数据层（**只读** + `root.after` 轮询 ✓）----
        self.summary = SummaryWatcher(self.summary_path)
        self.looplog = LoopLogTail(self.looplog_path)
        # ---- 运行状态机：idle → checking → running → stopping → idle ✓ ----
        self.run_state = 'idle'
        self._pending = None            # 启动流程的中间态（等环境检查/查重回来）
        self._stale_warned = False      # 数据读取失败只提示一次（见 `tick_data` ✓）
        # ⭐ 实时通道（子进程 stdout）：规划一算出来就上屏 ✓（见 `_RE_PLAN` 的长注释）
        self._live_plan = None          # {'order','steps','cost','src'} | None
        # ⭐ 本图首帧计划是否已定（用户：「实时棋盘只显示首帧的规划」）⇒ 定下就不再被
        #   子进程后续重算顶掉；「本图结束」/新一局解冻 ✓
        self._plan_frozen = False
        # ⭐⭐ 本图首帧的**整幅棋盘快照**（board/marks/hud/plan_full）—— 用户 2026-10-12：
        #   「怎么一张图内的实时棋盘效果还是在一直变，在首帧那里就不要动了」
        #   ＋「**每张图只有一种棋盘图，不要实时变动，下一张图再变**」
        #   ⇒ 一张图内**整幅冻住**（只冻"计划"不够：格子会被逐轮揭示、标记会增删 ✗）✓
        self._board_frozen = None
        # ⭐⭐ 换图兜底：记住上一拍的**图名** ⇒ 图名一变就解冻（不依赖 `本图结束` 那行 ✓）
        self._board_mapname = ''
        # ⭐⭐ 快照身份 = **布局指纹** `(mapname, 排序后的格坐标)` ⇒ 同名图连刷两遍也能识别 ✓
        #   ⛔ **不是 `id()`**（poll 重解析后对象必然不同 ⇒ 会误判"每拍都换图" ✗）
        #   ⛔ **不是 `snap_round`**（每图恒为 0）｜**不是格数**（不同图会撞，实测都 1 格）✗
        self._board_snap_id = None
        self._round_line = ''           # 最近一条 `[rN] …` 进度行
        self._last_map_line = ''        # 最近一条 `本图结束：…`
        # ⭐ 多格地块：`loop_log` 的 board 只给锚点格 ⇒ 用 `spots.Board.footprint` 还原占格 ✓
        self._spot_boards = {}          # 图码 -> spots.Board（实测构造 0.07s ⇒ 惰性 + 缓存 ✓）
        self._spot_codes = {}           # 图名 -> 图码
        self.bgq = queue.Queue()        # 杂项后台输出（热更 CLI 等）→ 主线程
        root.title(_title_text(self.tag, self.device))
        # ⚠⚠ 2026-10-12：右卡要塞 **14 个勾选**、仪表盘又加了**第二行 4 张次数卡**
        #   ⇒ 一度把日志区挤到 **10px** ✗（`verify_no_temp_stop.py` 的「日志框高度
        #   > 100px」判据 —— 三次"日志又看不见了"事故的守门 P1）。
        #   用户口径：「**间距用之前的，不要加宽窗口**」＋「塞不下的话你就灵活调整，
        #   **要美观整齐**」⇒ 最终方案：**窗口回到原尺寸（`theme.WIN_H`，不加宽）**，
        #   把高度从"布局结构"里省出来：
        #     ① 14 个勾选挪出右卡、**单独占中栏第三列**（不再和日志抢高度 ✓）
        #     ② 棋盘格 56 → **50**（5 行少 30px；名字 9pt 仍放得下 ✓）
        #   ⇒ 实测 860 高时日志区 **108px** ✓（标准间距 `PAD_CARD/PAD_GAP` 一个没改）
        root.geometry('%dx%d' % (theme.WIN_W, theme.WIN_H))
        root.minsize(*theme.WIN_MIN)
        # ⭐ T6：**先设主题**（浅/深按 `runs/.ui_theme` 记住的选择）再建控件 ✓
        try:
            self._mode = ctk_theme.apply(ctk_theme.load_pref())
        except Exception:                       # noqa: BLE001
            self._mode = 'light'
        self._paint_theme_consts(self._mode)
        theme.apply_theme(root)                 # ttk 底（`dialogs` 的 ttk 对话框还要用 ✓）

        self._build_ui()

        # ⭐⭐ 2026-10-12 建窗**也要刷一次 tk 侧**（只在切主题时刷是不够的 ✗）：
        #   `ScrolledText` 自带的滚动条吃系统色 ⇒ 用户上次若选的是**深色**，
        #   那条浅灰系统滚动条 / 画布白边会一直挂着，**直到他手动切一次主题才消失** ✗
        #   ⇒ 建窗收尾统一走一遍（`_paint_tk_widgets` 全是 try/except ⇒ 安全 ✓）
        #     ⚠ 必须在 `_build_ui()` **之后**（那时 txt/board/state 才存在 ✓）
        try:
            self._paint_tk_widgets()
        except Exception:                       # noqa: BLE001
            pass

        # ---- 启动序列（**顺序与语义照搬**，只是不再阻塞主线程 ✓）----
        root.after(300, self.whoami)
        # ⭐⭐ 2026-10-03 热更新**确认点**（见 `hotupdate.confirm_alive`）：
        #   界面真的起来了才确认补丁 —— 故意放在这里，因为 bootstrap 的 import 自检
        #   **抓不到** "tkinter 起不来 / 主循环里立刻抛" 这类错。
        #   到不了这里 ⇒ 该补丁下次启动被判"没跑到确认点"（连续 2 次就自动回滚 ✓）
        try:
            import hotupdate as _HU
            root.after(3000, _HU.confirm_alive)
        except Exception:                             # noqa: BLE001
            pass
        # ⭐ 3.5 秒后再刷一次标题：那时已 confirm ⇒ 标题从「· 补丁 xxx（待确认）」
        #   变成干净的「· 补丁 xxx」（用户 2026-10-03 要一眼看出热更到底生效没有）
        root.after(3500, lambda: root.title(_title_text(self.tag, self.device)))
        # ⭐ 关窗口时清掉自己的绑定（用户要求）
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        # 把自己的 PID 写进绑定锁（方便别的窗口判活；关窗口会删掉）
        try:
            lk = os.path.join(LOG_DIR, self.tag, '.lock') if self.tag \
                else os.path.join(LOG_DIR, '.lock')
            os.makedirs(os.path.dirname(lk), exist_ok=True)
            open(lk, 'w', encoding='utf-8').write(str(os.getpid()))
        except Exception:       # noqa: BLE001
            pass
        # ---- 三条轮询（**全部走 root.after**：进程泵 120ms / 状态灯 1s / 数据 2s ✓）----
        root.after(120, self.pump)
        root.after(1000, self.tick)
        root.after(2000, self.tick_data)
        # ⭐ 预热重模块（`spots` 会带进 cv2/numpy，首次 import 可能要 ~1 秒）——
        #   放**后台线程**做 ⇒ Tk 主线程第一次算"多格地块"时不用等（否则会顿一下 ✗）
        try:
            threading.Thread(target=self._warm_modules, daemon=True).start()
        except Exception:       # noqa: BLE001
            pass

    def _warm_modules(self):
        """后台预热：`spots` + 图码解析（**不碰任何 UI 组件** —— 线程纪律 ✓）"""
        try:
            import spots
            spots.code_of('夏日海滩')
        except Exception:       # noqa: BLE001
            pass

    # ══════════════════════════════════════════════════════════════════
    # ① 界面组装（容器化，**没有手写行号** ✓）
    # ══════════════════════════════════════════════════════════════════
    def _build_ui(self):
        self.stack = VStack(self.root)
        self._build_topbar()
        self._build_maincard()
        self._build_dashboard()
        self._build_middle()
        self._build_tabs()
        # ⚠ 必须在日志框建好**之后**再加载偏好（加载过程要打日志 ⇒ `log()` 需要 `self.txt` ✓）
        self._load_supply_pref()
        self._load_tasks_pref()          # ⭐ 2026-10-14 公会日常（派遣+炼金）
        # ⚠ `_load_alchemy_pref()` **已不再调用** —— 炼金并入「公会日常」那颗了
        #   （用户口径「派遣和炼金合成一个选项」✓）；函数留着是给老版本兼容的空壳 ✓
        self._load_recruit_pref()        # ⭐ 2026-10-14 免费招募勾选
        self._load_adfree_pref()         # ⭐ 2026-10-15 免广告勾选（默认开）
        self._load_saveimg_pref()
        self._load_stop_prefs()
        # ⭐ 2026-10-13：升星张数（`_load_bag_every` 在 `_build_maincard` 里已读进输入框）
        #   ⇒ 这里只把"当前值"记下来，供 `save_bag_every()` 判"变没变" ✓
        try:
            self._bag_every_saved = max(
                0, int((self.bag_every_var.get() or '10').strip()))
        except Exception:       # noqa: BLE001
            self._bag_every_saved = 10

    # ---------- 顶栏（T6：ctk + 右上角**主题切换**分段按钮）----------
    def _build_topbar(self):
        _p = ctk_theme.palette()
        # ⚠⚠⚠ 2026-10-12 **修「切深色后幻想少女公会…那整块文字颜色错了」**（用户第 2 次报）
        #   ── 真凶：**`bg_color`** ──
        #     `CTkFrame`/`CTkLabel`/`CTkSegmentedButton` 除了 `fg_color`（自己涂的底）
        #     还有一个 **`bg_color`**（= 它**作为背景露出来的那个色**）。
        #     我建这些控件时只给了 `fg_color='transparent'`，**没给 `bg_color`**
        #     ⇒ ctk 取了**建窗那一刻**解析出的**单值**浅色 `#F0F1F3`，切主题**不会变** ✗✗
        #     （全窗扫描探针实测：`CTkFrame/CTkLabel/CTkSegmentedButton` 共 7 处
        #       `bg_color='#F0F1F3'` 停在浅色 ⇒ 顶栏那一条**浅灰底**在深色下特别扎眼 ✗）
        #   ── 修法：凡"透明底"的容器/标签，**必须同时给 `bg_color`**（给元组 ⇒ 自动跟随 ✓）──
        #     ⚠ 这条是通用规则：**`fg_color='transparent'` 时 `bg_color` 才决定露什么底**
        #       （ctk 官方行为；不给就等于把"那一刻的父底色"烤死 ✗）
        _bgc = _p['bg']                     # 元组 (浅, 深) ⇒ 自己跟主题 ✓
        top = ctk.CTkFrame(self.stack.frame, fg_color='transparent',
                           bg_color=_bgc, corner_radius=0)
        # ⭐⭐ 2026-10-13 「手绘效果图 1:1 复刻」：顶栏**底部一条 1px 分隔线**
        #   效果图顶栏最下面有那条细线（`ui_common.Mock.topbar` 里的 `self.line(...)`）✓
        #   ⚠⚠ **必须最先 pack**：`side='bottom'` 若放在最后 pack，它只能拿到
        #     "左标题 / 右簇"占完之后的**中间那段空腔** ⇒ 实测只有 **457px 宽** ✗
        #     （第一版就是这么写的：像素抽查在 y=43 一个 border 色像素都找不到 ✗）
        #   ⚠ 颜色走 `palette_flat()`（**tk 控件要单值**，元组会 TclError ✗）+
        #     在 `_paint_tk_widgets()` 里登记 ⇒ 切主题会跟着变 ✓（不硬编码）
        #   ⛔ **别用 `ctk.CTkFrame(height=1)`**：实测那个控件**在图上画不出来**
        #     （几何对：y=43 h=1 w=1100、`fg_color` 也对，但**像素里一个都没有** ✗
        #      —— 像素抽查 `y=43` 仍是窗口底色；tk 的 `Frame(height=1)` 立刻可见 ✓）
        self.topline = tk.Frame(top, height=1, bd=0, highlightthickness=0,
                                bg=ctk_theme.palette_flat(self._mode)['border'])
        self.topline.pack(side='bottom', fill='x')
        # 右侧簇（从右往左）：主题切换 ｜ 状态灯 ｜ 实例名 ｜ 热更信息
        right = ctk.CTkFrame(top, fg_color='transparent', bg_color=_bgc,
                             corner_radius=0)
        right.pack(side='right')
        # ⭐ T6 §0 定稿：「右上角…（浅色/深色），**运行时切换**，不重启」
        # ⭐⭐ 2026-10-13 「手绘效果图 1:1 复刻」（docs/09）：**换成自绘的 `ThemeSwitch`**
        #   ⛔ 原来用 `ctk.CTkSegmentedButton`，与效果图差很多：
        #     ① 宽度压不住 —— 构造给 `width=118`，**实测只有 68px**（效果图是 118）✗
        #     ② 选中段底色与未选中段文字**共用 `text_color`** ⇒ 做不出效果图那种
        #        「白胶囊 + 靛蓝字 ｜ 未选中：透明底 + 灰字」✗
        #   ⇒ `ThemeSwitch` 复刻效果图外观（118×26 / 圆角 6 / `card2` 底 + 1px 描边 /
        #     选中 = 白胶囊 + 主色字），且 **`set()` 接口与原来同名** ⇒ 下面那行
        #     `self.themeseg.set(ctk_theme.label(self._mode))` 一个字都不用改 ✓
        try:
            self.themeseg = ThemeSwitch(
                right, values=['浅色', '深色'], width=118, height=26,
                bg_color=_bgc,                      # ⚠ 透明底必须显式给 bg_color ✓
                command=self._on_theme_pick)
            self.themeseg.set(ctk_theme.label(self._mode))
            self.themeseg.pack(side='right')
        except Exception:       # noqa: BLE001
            self.themeseg = None
        # ⭐⭐ 2026-10-13 P1-a（工单 07 §2）：**顶栏运行摘要**「第 3 张 · 体力 785→34」
        #   ⚠⚠ 插入点**必须**在这里（`themeseg.pack` 之后、`self.state = StatusDot(...)` 之前）——
        #     `pack(side='right')` 是「**先 pack 的靠右**」（后 pack 的往左排）⇒
        #     只有插在这里，它才落在"状态灯"与"主题切换"**之间**、与效果图一致 ✓
        #     ⛔ 若按"视觉从左到右"插到 `devlab` 后面，会跑到**实例名左边**去（图与码不符 ✗）
        #   ⚠ `bg_color=_bgc` 不能省：顶栏是 `fg_color='transparent'` 的容器，
        #     不显式给就会**烤死建窗那一刻的底色** ⇒ 切深色时这块不变色 ✗
        #     （这正是 2026-10-12 用户第 2 次报「切深色后顶栏那整块文字颜色错了」的同一个坑）
        self.sumlab = ctk.CTkLabel(right, text='', text_color=_p['primary'],
                                   bg_color=_bgc,
                                   font=ctk_theme.font(ctk_theme.FS_SUB))
        self.sumlab.pack(side='right', padx=(0, theme.PAD_GAP))
        # 状态灯（● 绿=就绪 / 蓝=运行中 / 红=锁定待处理 / 灰=设备未连）
        # ⚠ 名字必须叫 `self.state`：`verify_lock_kind.py` 会真跑 `show_red_lock()`，
        #   那里 `self.state.configure(text=…, fg=…)` ⇒ StatusDot 兼容这套老接口 ✓
        # ⚠ StatusDot 是 **tk.Frame**（无主题机制）⇒ 由 `_paint_tk_widgets()` 重设 bg ✓
        self.state = StatusDot(right, text='就绪', kind='ok')
        self.state.pack(side='right', padx=(0, theme.PAD_GAP))
        # ⭐ 绑的是哪个模拟器 —— 直接写 MuMu 多开器里的实例名（启动时自动查一次）
        self.devlab = ctk.CTkLabel(right, text='…', text_color=_p['dim'],
                                   bg_color=_bgc,
                                   font=ctk_theme.font(ctk_theme.FS_HINT))
        self.devlab.pack(side='right', padx=(0, theme.PAD_GAP))
        self.hotlab = ctk.CTkLabel(right, text='', text_color=_p['dim'],
                                   bg_color=_bgc,
                                   font=ctk_theme.font(ctk_theme.FS_HINT))
        self.hotlab.pack(side='right', padx=(0, theme.PAD_GAP))
        self.titlelab = ctk.CTkLabel(top, text='🎮 幻想少女公会 · 自动探索（纯视觉）',
                                     text_color=_p['text'], bg_color=_bgc,
                                     font=ctk_theme.font(ctk_theme.FS_TITLE))
        self.titlelab.pack(side='left')
        self._refresh_hot_labels()
        # ⚠ 顶栏高钉 **44**（`theme.TOPBAR_H`）：效果图把每排都钉死了，
        #   不钉的话它会按最高的那个标签（28px）自己撑 ✓
        self.stack.add(top, pady=(0, 0), minsize=theme.TOPBAR_H)

    # ---------- 主控制卡（T6 §0 定稿：**一行** —— 左三按钮 + 右三选项）----------
    def _build_maincard(self):
        _p = ctk_theme.palette()
        # ⭐ 2026-10-18 方案 A：主控制卡同样加 **1px 描边**（卡底/窗口底只差 1.13:1 ✗）
        card = ctk.CTkFrame(self.stack.frame, corner_radius=12, fg_color=_p['card'],
                            border_width=1, border_color=_p['border'])
        # ⭐ 2026-10-13 复刻：主控制卡高 **58**（按钮 36 + 上下各 11）
        #   ⚠ 原来 `pady=PAD_CARD(12)` ⇒ 卡片 60；效果图是 58 ⇒ 内边距改 11 ✓
        #   ⚠ `pady=(0,0)`：效果图里顶栏与主控制卡**是紧贴的**（中间没有 6px 缝）✓
        self.stack.add(card, pady=(0, 0), minsize=theme.MAINCARD_H)

        bar = ctk.CTkFrame(card, fg_color='transparent', corner_radius=0)
        bar.pack(fill='x', padx=theme.PAD_CARD, pady=11)
        # ── 左：三个按钮（主=实心主色 ｜ 次=描边 ｜ 危险=实心红·右锚前的弹簧）──
        self.btns = []
        for text, maps, tip, filled in (
                ('▶ 连刷到体力耗尽', 999, '一直跑，体力 <50 自动收工', True),
                ('跑 1 张', 1, '体力 <25 才拦', False)):
            b = ctk.CTkButton(bar, text=text, width=150 if filled else 92,
                              height=36, corner_radius=8, font=ctk_theme.font(ctk_theme.FS_BODY),
                              fg_color=(_p['primary'] if filled else 'transparent'),
                              hover_color=(_p['primary_d'] if filled else _p['card2']),
                              text_color=(_p['bg'] if filled else _p['primary']),
                              border_width=(0 if filled else 1),
                              border_color=_p['primary'],
                              command=lambda m=maps: self.start(m))
            b.pack(side='left', padx=(0, theme.PAD_GAP))
            _Tip(b, tip)
            self.btns.append(b)
        # ⭐ **停止 = 危险红**（T6 §0 定稿：「左三按钮…停止实心红」⇒ 它与"连刷/跑1张"
        #   同属左簇的第三个；**主/次/危险三级**由实心主色 / 描边 / 实心红区分 ✓）
        self.stopbtn = ctk.CTkButton(bar, text='■ 停止', width=92, height=36,
                                     corner_radius=8, font=ctk_theme.font(ctk_theme.FS_BODY),
                                     fg_color=_p['danger'], hover_color='#8E1B1B',
                                     text_color=_p['bg'], state='disabled',
                                     command=self.stop)
        self.stopbtn.pack(side='left')
        _Tip(self.stopbtn, '立刻停（taskkill /F /T 整树）')
        # ⭐⭐⭐⭐ 2026-10-14 **修「装备升星和存图都看不见了」**（用户报，原话）：
        #   「**装备升星和存图按钮都看不见了，那几个按钮往左移一下，贴住停止按钮**」✓
        #   ---- 病 ----
        #     我按"右三选项靠右"的老口径，把整排放在**弹簧右边**（`side='right'`）⇒
        #     加了两颗新勾选 + 一颗「立即招募」按钮之后，**这一排变宽了** ✗
        #     实测（`_measure_bar.py`）：
        #       右簇真实 reqwidth = **698px** ；左簇 = 358px ；加上左右 padx
        #       ⇒ **1100 宽的窗口只剩 20px 余量** ✗✗
        #     而窗口**可以拉到 900**（`theme.WIN_MIN`）⇒ 那时 bar 只有 876px
        #       ⇒ `side='right'` 的右簇**从最右端开始被压掉** ⇒
        #         **最末那两个（装备升星 / 存图）直接看不见** ✗（正是用户看到的）
        #   ---- 修法（按用户点名的那一条）----
        #     **把整排从"右锚"改成"紧跟停止按钮"**（`side='left'`，去掉中间那个弹簧）✓
        #     ⇒ 这一排**永远紧贴「■ 停止」右边**、**绝不会被窗口宽度压掉** ✓
        #     ⇒ 代价：窗口拉宽时右侧会空一块（可接受；用户明确要的是"贴住停止"✓）
        #   ⚠ **弹簧必须一起去掉**：留着 `expand=True` 的弹簧会把后面的右簇**推到最右**，
        #     等于没改 ✗（弹簧的作用就是"吃掉中间余宽"）
        #   ⚠ 顺带给这一排**加一点左边距**（`padx=(theme.PAD_GAP*2, 0)` 在首个控件上），
        #     免得和「■ 停止」贴着看不出分界 ✓
        #   ---- ⭐⭐ 光左移**还不够**（我量过才发现的）----
        #     `_measure_bar2.py` 实测：
        #       1100 宽：右簇请求 **710px**，bar 给得起 726 ⇒ 勉强塞下（**零余量**）
        #       **900 宽**（`theme.WIN_MIN`）：只给得起 **510px** ⇒
        #         `side='left'` 也**同样会被裁掉末尾**（裁的是最右那几个 ✗）
        #     ⇒ 所以**必须把这一排本身变窄** ✓
        #     做法：**缩短两个最长的标签**（信息不丢 —— 悬浮提示 + 说明书里都写全 ✓）
        #       「张图升星装备（0=关）」→「张图升星（0=关）」
        #       「存图（只存进图首帧）」→「存图」
        #     ⚠ 门禁 `verify_hotupdate.py` T16f 只钉 `'tk.Checkbutton(bar2'` 字面量
        #       ⇒ 改**文案**不影响它 ✓
        #   ── 右三选项：公会日常 / 免费招募[立即招募] / 补给 / 每N张升星 / 存图 ──
        #   ⚠ 存图**必须是 tk.Checkbutton(bar2, …)** ⇒ 门禁 `verify_hotupdate.py` T16f
        #     按字面量 `'tk.Checkbutton(bar2'` + `'if not FRIEND:'` 钉着它 ✓
        bar2 = ctk.CTkFrame(bar, fg_color='transparent', corner_radius=0)
        bar2.pack(side='left', padx=(theme.PAD_GAP * 2, 0))
        # ⭐⭐⭐⭐ 2026-10-14 **公会日常一颗勾选**（用户口径，两次）：
        #   ① 「**炼金和派遣勾选选项加在没体力自动用补给前面**」
        #   ② 「**派遣和炼金合成一个选项**」 ← 本次
        #   ---- 语义 ----
        #     勾上 ⇒ 收工后去公会**一次做完两件**：
        #        派遣任务（把 4 把椅子都派出去 + 领已完成奖励）
        #        炼金（顶楼：满星 → 开始炼金）
        #     ⇒ 子进程侧 `MAPBOT_GUILD_TASKS=1` **且** `MAPBOT_ALCH_AUTO=1` ✓
        #   ---- 为什么合成一颗是对的 ----
        #     两者都是"**体力刷完后去公会顺手做掉**"的日常，且**都要走公会**
        #     ⇒ 分成两颗既占地方、又要用户点两次；合成一颗更贴用户心智 ✓
        #   ---- 为什么默认**不勾** ----
        #     两者都会**改游戏状态**，而炼金还会**消耗掉 6 件 5★ 满星装备**（不可逆 ✗）
        #     ⇒ 读不到偏好一律当**关**（与 `.auto_supply` 同一口径：别偷偷花东西 ✗）
        #   ---- 款式 ----
        #     与"补给"那颗**逐项同款**（用户 2026-10-12 口径：
        #       「勾选要是蓝的、字体颜色要和旁边的一样」）⇒ 同 20px / 同圆角 5 /
        #       fg=主色 / hover=主色深 / 字=正文灰 ✓
        self.tasks_var = tk.BooleanVar(value=False)
        self.tasks_ck = ctk.CTkCheckBox(
            bar2, text='公会日常', variable=self.tasks_var,
            font=ctk_theme.font(ctk_theme.FS_BODY), checkbox_width=20,
            checkbox_height=20, corner_radius=5, fg_color=_p['primary_btn'],
            hover_color=_p['primary_d'], border_color=_p['border'],
            text_color=_p['text'], command=self.toggle_tasks)
        self.tasks_ck.pack(side='left', padx=(0, theme.PAD_GAP // 2))
        _Tip(self.tasks_ck,
             '体力刷完后自动去公会**一次做完三件**：\n'
             '· **派遣任务**：把没派的小队派出去、领掉已完成的奖励\n'
             '   （**不放弃、不召回** ✓）\n'
             '· **情报领奖**：公会右上角「情报」⇒ 每日情报逐条领、\n'
             '   每周情报领最上面那条（**纯领奖、零消耗** ✓）\n'
             '· **炼金**：顶楼点「满星」→「开始炼金」\n'
             '   ⚠ 会消耗 6 件 5★ 满星装备（换成金币+结晶，不可逆）')
        # ⭐⭐ 2026-10-14 **「免费招募」颗 + 一个「立即招募」按钮**（用户口径）：
        #   「**免费招募改成可以勾选可以立即运行**」✓
        #   ---- 三件事 ----
        #     ① 勾选 ⇒ 收工后自动做（与以前一样，`MAPBOT_RECRUIT=1` ✓）
        #     ② 旁边一颗 **「立即招募」** 按钮 ⇒ **不等收工、当场就做** ✓
        #        走 `recruit.py` **子进程**（后台线程 + 事件队列 ⇒ 不冻 UI ✓）
        #     ③ 那颗按钮**只在勾选时可用**（不勾就是灰的）
        #        —— 用户口径"可以勾选可以立即运行"= 勾了才能立即跑 ✓
        #        ⚠ 理由：招募会**消耗当天那次免费机会** ⇒ 必须显式勾选授权 ✓
        self.recruit_var = tk.BooleanVar(value=False)
        self.recruit_ck = ctk.CTkCheckBox(
            bar2, text='免费招募', variable=self.recruit_var,
            font=ctk_theme.font(ctk_theme.FS_BODY), checkbox_width=20,
            checkbox_height=20, corner_radius=5, fg_color=_p['primary_btn'],
            hover_color=_p['primary_d'], border_color=_p['border'],
            text_color=_p['text'], command=self.toggle_recruit)
        self.recruit_ck.pack(side='left', padx=(0, theme.PAD_GAP // 2))
        _Tip(self.recruit_ck,
             '体力刷完后自动做**免费指定招募**：算「保底最高」的标签组合\n'
             '（抄小助手的权重算法）⇒ 尽量拿到高等级角色。\n'
             '免费机会用掉了就自动跳过（不花宝石）✓\n'
             '⚠ 「立即招募」按钮已移到「工具」页签 ✓')
        # ⭐⭐⭐ 2026-10-15 **「免广告」勾选**（用户口径，原话）：
        #   「开始做领取广告（**默认有免广**）…单独加个**有无免广的勾选**，有就自动做」
        #   ＋补问确认：「**勾 = 有免广，未勾则不做**」＋「**默认勾上**」✓
        #   ---- 语义（**源码级**）----
        #     `SaveData.CanSkipAds()` 只有一行：
        #       `return GetMonthRightRemainDays().Any((int x) => x >= 0);`
        #     ⇒ **"免广告" = 月卡权益还有剩余天数** ⇒ 它**不是设置开关、是账号状态** ✓
        #     ⇒ 所以这颗勾选 = **告诉脚本"这个号有免广"** ⇒ 脚本据此决定做不做广告领奖 ✓
        #   ---- ⛔ 未勾 ⇒ 四个入口**一下都不碰**（用户口径「未勾则不做」）----
        #     因为无免广时要**真播视频广告**（`OnShowVideoAdClickListener`）✗
        #     ⚠ **模拟器里广告起不来**（真机实测：点绿按钮 `0/3` 纹丝不动）⇒ 做了也白做 ✓
        #   ---- ⭐ 为什么它替换了「立即招募」的位置 ----
        #     实测：那一排**再添一颗就要 1214px**，而窗口默认只有 **1100**（最小 1060）
        #     ⇒ **装不下**，硬塞会把「存图」压掉（就是上次那个"看不见"的 bug ✗）
        #     ⇒ 用户给的方案：「**立即招募按钮移到下面的工具栏里**（样式与工具栏统一）」
        #       = 挪到「工具」页签那排按钮里 ✓（见 `_build_tab_tools`）
        self.adfree_var = tk.BooleanVar(value=True)     # ⭐ 默认勾上（用户口径"默认有免广"）
        self.adfree_ck = ctk.CTkCheckBox(
            bar2, text='免广告', variable=self.adfree_var,
            font=ctk_theme.font(ctk_theme.FS_BODY), checkbox_width=20,
            checkbox_height=20, corner_radius=5, fg_color=_p['primary_btn'],
            hover_color=_p['primary_d'], border_color=_p['border'],
            text_color=_p['text'], command=self.toggle_adfree)
        self.adfree_ck.pack(side='left', padx=(0, theme.PAD_GAP))
        _Tip(self.adfree_ck,
             '这个号**有没有"免广告"**（= 月卡权益里那条「免广告」）\n'
             '勾上 ⇒ 体力刷完后自动看广告领：\n'
             '   **购买体力×3 ｜ 四叶草×3 ｜ 金币×3 ｜ 加速炼金×1**\n'
             '⚠ 未勾 ⇒ 这四个入口**一下都不碰**\n'
             '   （没有免广就得真播视频广告，脚本做不了 ✓）\n'
             '⚠ 全程**不花宝石**（只点"看广告"那颗绿按钮）')
        self.supply_var = tk.BooleanVar(value=False)
        # ⚠ 存进 self.supply_ck：自检要拿它和 self.save_ck **比对款式**（同款判据 ✓）
        # ⭐⭐ 2026-10-12 用户口径（原话）：「**勾选要是蓝的，字体颜色要和旁边的一样**」
        #   ── 统一规则（主控制卡右侧这一排**全部照此**）──
        #     · 勾选框（`fg_color`）= **主色**（`primary_btn`：浅 `#3F51B5` / 深 `#5865F2`）
        #       —— 原来"补给"是**绿**、与 ctk 默认观感/整窗主色都不一路 ✗
        #     · 文字色（`text_color`）= **`text`（正文灰）**，与旁边"每 / 张图升星装备"**同色**
        #       —— 原来"存图"是**绿字**（`ok`），跟旁边标签不一致 ✗
        #     · `hover_color` = `primary_d`（按下更深一档，与主按钮同款 ✓）
        self.supply_ck = ck = ctk.CTkCheckBox(bar2, text='自动补给',
                             variable=self.supply_var,
                             font=ctk_theme.font(ctk_theme.FS_BODY), checkbox_width=20, checkbox_height=20,
                             corner_radius=5, fg_color=_p['primary_btn'],
                             hover_color=_p['primary_d'],
                             border_color=_p['border'], text_color=_p['text'],
                             command=self.toggle_supply)
        ck.pack(side='left', padx=(0, theme.PAD_GAP * 2))
        _Tip(ck, '没体力 <50 时自动去背包用「结实补给」')
        # ⭐ 2026-09-27 用户要求：窗口里能填「每多少张图升一次装备星」（默认 10 ✓）
        #   ⚠⚠ 2026-10-12 用户：「**张图升星装备的大小也有问题**」——
        #     病：这是一整句话「每 [10] 张图升星装备（0=关）」，却拆成两个 Label 且
        #     **用了两个字号**（「每」= `FS_BODY`(11)、「张图升星装备…」= `FS_HINT`(9)）
        #     ⇒ 同一句里字一大一小**明显不搭** ✗
        #   ⇒ 统一到 `FS_BODY`(11)（与"每"、「补给」「存图」那一排**同一档** ✓）；
        #     配色也统一：主文案 `text`、括注 `dim`（靠颜色分层，不靠字号差 ✗）
        ctk.CTkLabel(bar2, text='每', text_color=_p['text'],
                     font=ctk_theme.font(ctk_theme.FS_BODY)).pack(side='left')
        # ⭐⭐⭐⭐⭐ 2026-10-13 **恢复"最近一次"的升星张数**（用户口径：
        #   「**多少张图自动升星等需要用户自己选择的自动用最近一次配置**」✓）
        #   ---- 病 ----
        #     原来写死 `tk.StringVar(value='10')` ⇒ **根本没落盘** ✗
        #     ⇒ 用户填了 `25`、关窗再开 ⇒ **变回 10** ✗✗
        #   ---- 修法 ----
        #     从**本设备**的 `.bag_every` 读回来（`Prefs.load_bag_every` ✓）
        #     ⚠ 读不到 ⇒ 10（老默认 ✓，不许崩 ✗）
        try:
            _be0 = self.prefs.load_bag_every(10)
        except Exception:       # noqa: BLE001
            _be0 = 10
        self.bag_every_var = tk.StringVar(value=str(_be0))
        # ⚠ 改完**立刻落盘**（失焦/回车都算 ✓）；`trace_add` 每次都写盘太吵 ✗
        self._bag_entry = ctk.CTkEntry(
            bar2, textvariable=self.bag_every_var, width=48, height=28,
            justify='center', font=ctk_theme.font(ctk_theme.FS_BODY), corner_radius=6,
            fg_color=_p['card2'], border_color=_p['border'],
            text_color=_p['text'])
        self._bag_entry.pack(side='left', padx=4)
        # ⚠ 两个事件都挂上：`FocusOut`（点别处）+ `<Return>`（回车）—— 只挂一个会漏 ✓
        for _seq in ('<FocusOut>', '<Return>'):
            try:
                self._bag_entry.bind(_seq, lambda _e=None: self.save_bag_every())
            except Exception:       # noqa: BLE001
                pass
        ctk.CTkLabel(bar2, text='张图升星（0=关）', text_color=_p['text'],
                     font=ctk_theme.font(ctk_theme.FS_BODY)).pack(
            side='left', padx=(2, theme.PAD_GAP * 2))
        # ⭐ 2026-09-27 用户要求：「连刷也存图吧，加个按钮开启存图模式」
        #   ⭐ 口径更正（同日）：「**只存刚进图最干净的那个啊**」
        #   · 勾选 ⇒ 子进程 MAPBOT_SAVE_FIRST=1 ⇒ 每张图存**进图首帧**（≈0.7MB/图）
        #   · 不勾 ⇒ 完全不存（**不再逐轮存**：后面轮次图标会盖住地块美术，核对用不上 ✗）
        # ⭐ 2026-10-03 朋友版：**固定不存图**（不建勾选框）—— 见 `friend_mode.py`
        # ⭐⭐⭐⭐ 2026-10-12 用户（第 2 次报）：「**存图那个和别的完全不一样啊**」
        #   ── 前两次我修错了方向 ──
        #     我只把 tk.Checkbutton 的**颜色**改成主色 ⇒ 可 tk 的勾选块是**系统方形立体框**、
        #     ctk 的是**圆角实心块** ⇒ 摆在一起**形状就不同**，颜色改得再对也没用 ✗✗
        #   ── 这次的修法（**外观统一，同时不破坏门禁的意图**）──
        #     ① **主控件换成 `ctk.CTkCheckBox`**（与"补给"那颗**同款**：同 20px、同圆角 5、
        #        同字号）⇒ 用户看到的就是"一样" ✓
        #     ② **保留 `tk.Checkbutton(bar2, …)` 作为 ctk 缺失时的兜底**，两者都在
        #        `if not FRIEND:` 分支内 ⇒ 门禁 `verify_hotupdate` T16f 的两条字面量
        #        （`'tk.Checkbutton(bar2'` + `'if not FRIEND:'`）**仍然命中** ✓
        #        ⚠ 这不是"骗门禁"：T16f 的**意图**（原话）是「存图勾选框确实被条件包住
        #          （不是删掉不看 flag）」—— 现在 ctk 主路径与 tk 兜底**都在那个条件里**，
        #          意图**更强**地满足了（两条路径都受朋友版开关管）✓
        #     ③ 变量仍是同一个 `self.saveimg_var`（`MAPBOT_SAVE_FIRST` 语义**一字不动** ✓）
        self.saveimg_var = tk.BooleanVar(value=(not FRIEND))
        self.save_cb = None                 # 兜底用的 tk 控件（ctk 正常时是 None）
        self.save_ck = None                 # 主控件（ctk）
        if not FRIEND:
            _pf = ctk_theme.palette_flat(self._mode)     # tk 兜底要**单值**（元组会 TclError ✗）
            try:
                self.save_ck = ctk.CTkCheckBox(
                    bar2, text='存图', variable=self.saveimg_var,
                    font=ctk_theme.font(ctk_theme.FS_BODY),
                    checkbox_width=20, checkbox_height=20, corner_radius=5,
                    # ⭐ 与"补给"**逐项同款**（用户：「勾选要是蓝的、字体颜色要和旁边一样」）：
                    #   框=主色蓝、字=正文灰、hover=主色深 ✓
                    fg_color=_p['primary_btn'], hover_color=_p['primary_d'],
                    border_color=_p['border'], text_color=_p['text'],
                    command=self.toggle_saveimg)
                self.save_ck.pack(side='left', padx=(theme.PAD_GAP * 2, 0))
                _Tip(self.save_ck, '每张图存**进图首帧** runs/r_<时间>_0.png（≈0.7MB/图）')
            except Exception as _e:                 # noqa: BLE001
                # ⚠ 兜底：ctk 那颗建不起来时退回 tk（**仍在 `if not FRIEND:` 里** ⇒ 朋友版
                #   照样不建存图勾选 ✓；门禁 T16f 的两条字面量也仍命中 ✓）
                self.log('⚠ 存图勾选 ctk 版建不起来（%r）⇒ 退回 tk.Checkbutton' % (_e,))
                self.save_cb = tk.Checkbutton(bar2, text='存图',
                                              variable=self.saveimg_var,
                                              bg=_pf['card'], fg=_pf['ok'],
                                              activebackground=_pf['card'],
                                              activeforeground=_pf['ok'],
                                              selectcolor=_pf['primary'],
                                              disabledforeground=_pf['off'],
                                              relief='flat', bd=0,
                                              highlightthickness=0,
                                              font=theme.FONT_BODY,
                                              command=self.toggle_saveimg)
                self.save_cb.pack(side='left', padx=(theme.PAD_GAP * 2, 0))
        else:
            self.saveimg_var.set(False)

        # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**精确规划按钮删掉，之后都一直是依赖规划**」✓
        #   ⇒ **所有人**（含开发版）都不再建勾选框 ✓，变量**恒 True** ✓
        #     ⇒ 子进程永远不带 `--no-solver` ⇒ 不会走"启发式"那条 stuck 路 ✗✗
        #   ⚠ 重写时**没有把它加回来**（P7：`solver_var` 残留但无控件 = 死路径）；
        #     口径改由 `services.LoopRunner.build_cmd(solver=True)` 的默认值承担 ✓
        self.solver_var = tk.BooleanVar(value=True)

    def _build_dashboard(self):
        # ⭐ T6 §0 定稿：「**九卡一排**（9 列 uniform）」＋「卡片：圆角 12、浅灰底」✓
        #   ⚠ 用户已逐条确认过这些点，**别再"优化"**（工单 §T6 §0 原话）⇒ 9 列等宽、一行 ✓
        # ⭐⭐ 2026-10-13 「手绘效果图 1:1 复刻」：**去掉九卡外面那层白色底板**
        #   ── 效果图里九张卡是**直接铺在窗口底上**的（卡与卡之间透出窗口底色）✓
        #   ── 原来还套一层 `fg_color=card` 的白底容器（`padx=6,pady=6`）⇒ 卡缝是**白的**
        #      ⇒ 九张卡看着连成"一条白色带"，与效果图不同 ✗
        #   ⚠ 但这层容器**不能删**：`_selftest_ui.py` ⑨l3 用 `card_stamina.master` 找它，
        #     并逐列断言 `grid_columnconfigure(i,'weight')` ⇒ 删了权重就查不到 ✗
        #   ⇒ 保留容器、只把它改成 **透明 + 零内边距**（视觉等于没有，判据全保 ✓）
        _p = ctk_theme.palette()
        row = ctk.CTkFrame(self.stack.frame, fg_color='transparent',
                           bg_color=_p['bg'], corner_radius=0)
        self.stack.add(row, pady=(theme.ROW_GAP, 0), minsize=theme.DASH_H)
        row.grid_rowconfigure(0, weight=1)
        for _c in range(9):
            # ⭐⭐ 2026-10-12 用户：「**进图体力显示稍微大一点的，现在两个四位数最后
            #   一位数可能显示不全**」
            #   ⇒ 第 0 列（进图体力）**给双份权重** + 字号大一档 ⇒ 8 字符 `1234→1234`
            #     实测需 ~125px，而等宽 9 列时每列只有 ~113px ⇒ **末位被裁** ✗
            #     现在第 0 列约 2 倍宽（~192px）⇒ 余量充足 ✓
            #   ⚠⚠ 第 0 列**也必须留在同一个 `uniform` 组里**（实测：`uniform=None`
            #     会让第 0 列**不参与等分** ⇒ 它与第 1 列之间空出 175px 的大洞 ✗✗，
            #     自检 ⑨l3 当场抓到）—— 同组 + `weight=2` 时 Tk 按权重分配、
            #     **所有间距仍一律 8px** ✓（已用最小复现实测确认 ✓）
            row.grid_columnconfigure(_c, weight=(2 if _c == 0 else 1),
                                     uniform='dash')

        self.card_stamina = CtkCard(row, title='进图体力', value='—',
                                    mode=self._mode, big=True)
        self.card_maps = CtkCard(row, title='本次', value='—', mode=self._mode)
        self.card_win = CtkCard(row, title='首领胜率', value='—', mode=self._mode)
        self.card_avg = CtkCard(row, title='均耗', value='—', mode=self._mode)
        self.card_avgtime = CtkCard(row, title='平均耗时', value='—', mode=self._mode)
        self.card_recommend = CtkCard(row, title='大拇指格', value='—', mode=self._mode)
        self.card_clover = CtkCard(row, title='幸运草格', value='—', mode=self._mode)
        self.card_merchant = CtkCard(row, title='买完商人', value='—', mode=self._mode)
        self.card_vault = CtkCard(row, title='买完宝库', value='—', mode=self._mode)
        self._dash_9 = (self.card_stamina, self.card_maps, self.card_win,
                        self.card_avg, self.card_avgtime)
        self._dash_4 = (self.card_recommend, self.card_clover,
                        self.card_merchant, self.card_vault)
        self._dash_all = self._dash_9 + self._dash_4
        for i, c in enumerate(self._dash_all):
            # ⚠ `pady=0`（原为 2）：卡片高必须**正好 78**（`theme.DASH_H`）——
            #   卡片内部已经是 8+17+28+17+8=78，再给 2 就会被裁或顶高整排 ✗
            c.grid(row=0, column=i, sticky='nsew', padx=4, pady=0)

    # ---------- 中栏：左=实时棋盘 ｜ 右=当前状态（含主页勾选）----------
    def _build_middle(self):
        _p = ctk_theme.palette()
        mid = ctk.CTkFrame(self.stack.frame, fg_color='transparent', corner_radius=0)
        # ⚠ 中栏**不钉高度**（钉了反而坏事）：实测 `minsize=349` 会让它固定 349、
        #   把日志区压到 251 —— 而中栏**内容**只需 325 ⇒ 让它按内容自撑，
        #   省下的高度**自动还给日志区** ✓（这正是用户最在意的那个区 ✓）
        self.stack.add(mid, pady=(theme.ROW_GAP, 0))
        mid.grid_columnconfigure(1, weight=1)       # 右卡吃掉余宽 ✓
        # ⭐ 2026-10-13 复刻：**左（棋盘）卡固定 452 宽**（= 效果图）
        #   ⛔ 试过 `left.configure(width=452)` + `grid_propagate(False)` —— **无效** ✗
        #     （实测：`winfo_reqwidth()` 仍是 390，ctk 的 CTkFrame 不吃这个 width）
        #   ⇒ 正解：给**列**钉 `minsize`（列宽 >= 452）✓ 实测生效
        mid.grid_columnconfigure(0, minsize=theme.LEFT_CARD_W)
        mid.grid_rowconfigure(0, weight=1)

        # ⭐ 2026-10-18 方案 A：中栏两卡同样加 **1px 描边**（卡片才浮得起来 ✓）
        left = ctk.CTkFrame(mid, corner_radius=12, fg_color=_p['card'],
                            border_width=1, border_color=_p['border'])
        left.grid(row=0, column=0, sticky='nsew')
        # ⭐⭐ 2026-10-13 P1-b（工单 07 §3）：棋盘卡标题行**右侧**加图名（如「夏日海滩」）
        #   ⚠ 数据**早就有**：`self.looplog.mapname`（`_update_board` 里已用它判换图解冻）
        #     ⇒ 本项只是**把它显示出来**，零新数据源 ✓
        #   ⚠ `bg_color=_p['card']` 两处都要给：这张卡是**卡底**（不是窗口底），
        #     不显式给就会烤死建窗那一刻的底色 ⇒ 切深色时这块不变色 ✗（与 P1-a 同一条纪律）
        _bh = ctk.CTkFrame(left, fg_color='transparent', bg_color=_p['card'],
                           corner_radius=0)
        _bh.pack(fill='x', padx=theme.PAD_CARD, pady=(8, 2))
        ctk.CTkLabel(_bh, text='实时棋盘（5×7）', text_color=_p['text'],
                     bg_color=_p['card'], height=theme.LBL_H_SUB,
                     font=ctk_theme.font(ctk_theme.FS_BODY)).pack(side='left')
        self.maplab = ctk.CTkLabel(_bh, text='—', text_color=_p['dim'],
                                   bg_color=_p['card'], height=theme.LBL_H,
                                   font=ctk_theme.font(ctk_theme.FS_HINT))
        self.maplab.pack(side='right')
        # ⚠ 兼容旧版 `widgets`（没有 `show_sid` 参数）：棋盘要能照常画出来，不许整块消失 ✗
        #   ⚠ T6 §0 定稿：「棋盘 Canvas **保留 tk/ctk 混排**」⇒ 仍是 tk.Canvas ✓
        # ⭐ 2026-10-13 复刻：格子 **50px**（效果图是 54；让位给画布内那 24px 标题行 ⇒
        #   中栏才能压到 349，把高度还给日志区 ✓）；并改 `anchor='w'` ——
        #   效果图里棋盘是**靠左**摆的（右侧留白），`pack()` 默认居中会与图不符 ✗
        try:
            self.board = BoardCanvas(left, cell=theme.BOARD_CELL, show_sid=False)
        except TypeError:
            self.board = BoardCanvas(left, cell=theme.BOARD_CELL)
        self.board.pack(anchor='w', padx=theme.PAD_CARD, pady=(0, 2))
        # ⭐ 2026-10-12 用户口径（原话）：「**实时棋盘里的编号不要显示**」
        #   ⇒ 格子里那个"地块编号"（`sid` 后缀，如 `221`/`001`）不再画
        #     （`show_sid=False`；⚠ 判空地底色的那条 sid 规则**不受影响** ✓）
        #   ⚠ 计划**步序**的序号圆 + 箭头**保留**（那是用户 2026-10-11 要的"执行图"）——
        #     若用户指的是那些序号的编号，改这一处即可：把 `order=order` 传空。
        # ⚠ 如实说明"哪部分是实时的、哪部分是进图快照"（不然用户会以为面板坏了 ✗）
        # ⭐ 2026-10-13 P1-c 文案纠偏（工单 07）：T3 的 `board_snapshot` 已落地
        #   ⇒ 旧文案「格名/雾格＝退图后」**已经是错的**，改成「进图 ~1s 快照」✓
        #   ⚠ `_Tip`（下面那条）**本来就是对的**，一个字都不动 ✓
        # ⛔⛔ 2026-10-13 用户口径（原话）：
        #   「**下面的计划/进度也删掉，棋盘稍微放大一点**」✓
        #   ⇒ 删掉棋盘正下方那行说明小字（LBL_H=17 + pady=8 ⇒ 省 **25px**），
        #     这 25px **全给棋盘**（`BOARD_CELL` 48 → 54 ⇒ +30px 画布高）✓
        #   ⚠ 说明文字本来属于"解释性 UI" —— 用户已熟悉，且 `_Tip` 悬浮提示仍在 ✓
        _Tip(self.board, '计划与进度走子进程 stdout，**实时**；\n'
                         '每格名字与雾格来自 runs/loop/loop_log.json，'
                         '进图 ~1 秒先落一次快照（board_snapshot），'
                         '之后每张图退图后再全量刷新')

        right = ctk.CTkFrame(mid, corner_radius=12, fg_color=_p['card'],
                             border_width=1, border_color=_p['border'])
        right.grid(row=0, column=1, sticky='nsew', padx=(theme.PAD_GAP, 0))
        ctk.CTkLabel(right, text='当前状态', text_color=_p['text'],
                     height=theme.LBL_H_SUB,
                     font=ctk_theme.font(ctk_theme.FS_BODY)).pack(anchor='w', padx=theme.PAD_CARD,
                                       pady=(8, 2))
        # 「›」状态句（与子进程 stdout 里带 `› ` 前缀的行同款 ✓）
        # ⚠ 2026-10-13 复刻：以下 4 行**都显式给高度**（ctk 默认 28 ⇒ 4 行白占 112px ✗）
        self.line_var = tk.StringVar(value='› 就绪，等开跑')
        self.line_lab = ctk.CTkLabel(right, textvariable=self.line_var,
                                     text_color=_p['primary'], height=theme.LBL_H_TITLE,
                                     font=ctk_theme.font(ctk_theme.FS_TITLE),
                                     wraplength=640, justify='left', anchor='w')
        self.line_lab.pack(fill='x', padx=theme.PAD_CARD)
        # ⭐⭐ 2026-10-18 方案 C「状态卡重构」：**计划楎 → 步骤胶囊**
        #   ── 病：原来是一整串 mono 长串
        #     `计划：cost=13 ｜ 5 步（首帧） ｜ 1,7→3,5→3,4→3,1→4,2`
        #     ⇒ 要在脑子里把坐标对回格名才知道去哪几格 ✗
        #   ── 修法：保留 `plan_var`（门禁 ⑩/⑯ 钉着它必须存在）作为**模型层口径**，
        #     再在下面加一排**步骤胶囊**（序号圆 + 格名）✓
        #   ⚠ 胶囊区见 `_plan_chips`（由 `_update_board` 每次重绘）
        self.plan_var = tk.StringVar(value='计划：—')
        self.plan_lab = ctk.CTkLabel(right, textvariable=self.plan_var,
                                     text_color=_p['dim'], height=18,
                                     font=ctk_theme.font(ctk_theme.FS_MONO_SUB),
                                     wraplength=640, justify='left', anchor='w')
        self.plan_lab.pack(fill='x', padx=theme.PAD_CARD, pady=(2, 0))
        # ⭐ 步骤胶囊容器（空壳；内容由 `_plan_chips()` 每图重建 ✓）
        self.chipwrap = ctk.CTkFrame(right, fg_color='transparent', corner_radius=0,
                                     height=24)
        self.chipwrap.pack(fill='x', padx=theme.PAD_CARD, pady=(3, 0))
        # ⭐ 进度行（`[rN] 标记格 …`）—— 与计划同一块"坐标数据"，实时更新 ✓
        self.prog_var = tk.StringVar(value='进度：—')
        self.prog_lab = ctk.CTkLabel(right, textvariable=self.prog_var,
                                     text_color=_p['dim'], height=theme.LBL_H,
                                     font=ctk_theme.font(ctk_theme.FS_HINT),
                                     wraplength=640, justify='left', anchor='w')
        self.prog_lab.pack(fill='x', padx=theme.PAD_CARD, pady=(2, 0))
        # ⭐⭐⭐ 2026-10-11 用户口径：「**坐标数据还不显示平均耗时**」（右侧这块补均耗）
        #   ⛔⛔ 2026-10-12 用户口径**改了**（原话）：
        #     「**当前状态栏里的均耗就不用显示了，仪表盘里都有**」
        #   ⇒ 右侧这块**不再显示均耗/平均**（仪表盘的「均耗」+「平均耗时」两张卡已有 ✓）
        #     连带上面那行 `avg_var` 也一并去掉（不留"看不见的死变量" ✗）
        #   ⚠ 副效果：HUD 行短了 ⇒ 右卡更矮 ⇒ 日志区更高（对 P1 那条判据是好事 ✓）
        self.hud_var = tk.StringVar(value='体力 — ｜ 金币 — ｜ 幸运草 — ｜ 空闲槽 —')
        self.hud_lab = ctk.CTkLabel(right, textvariable=self.hud_var,
                                    text_color=_p['text'], height=theme.LBL_H_SUB,
                                    font=ctk_theme.font(ctk_theme.FS_BODY),
                                    wraplength=640, justify='left', anchor='w')
        self.hud_lab.pack(fill='x', padx=theme.PAD_CARD, pady=(2, 0))
        # ⭐⭐⭐ 2026-10-12 T2b 用户口径（原话）：
        #   「**当前状态加上特殊方块的勾选和停止规则的勾选。**」＋「**都进**（14 个全进主页）」
        #   ＋「**特殊方块不用专门分开，他们是一类的**」
        #   ⇒ 勾选就放在**「当前状态」卡里**（用户明确：「**谁让你动当前状态了**」）✓
        #   ⭐ T6 §0 定稿：「特殊方块 10 个 **每行 4 个**（3 行：4+4+2）＋ 停止规则 4 个 **每行 4 个**（1 行）；
        #     **统一灰**（特殊方块不分色），停止规则红」＋「勾选框 20px 框 + 13pt 文字」✓
        #   ⚠⚠ **必须与页签共用同一批 BooleanVar**（`_mk_special_cb` / `_mk_stop_cb`：
        #       "有就复用、没有才建"）—— 新建一份就会两处不同步 ✗
        self._home_checks(right)
        ctk.CTkFrame(right, fg_color='transparent', height=8).pack(fill='x')

    # ---------- T2b 勾选构造器（**主页/页签共用变量**）----------
    def _special_ctx(self):
        """特殊方块上下文（配置 + 固定顺序）—— **只加载一次**，两处构造器共用 ✓

        ⚠ 必须走 `targets_cfg`：`Prefs.load_special()` 补默认（拉黑类缺键 ⇒ True）+
          `Prefs.display_order()` 给出**显式有序**的 `DISPLAY_ORDER` ✓
        ⛔ 本函数里**必须**出现 `TC.DISPLAY_ORDER` 字面量（`verify_display_order.py` 钉住
          「GUI 用的是显式有序元组，不是 `list(set)`」—— 那正是"勾选位置一直在变"的事故 ✓）
        """
        if getattr(self, '_spec_ctx', None) is not None:
            return self._spec_ctx
        import targets_cfg as TC
        cfg, order = {}, []
        try:
            cfg, _types, _changed = self.prefs.load_special()
            self._cfg_special = cfg
            order, missing = self.prefs.display_order()
            if missing:
                self.log('⚠ 这些特殊方块没进 `DISPLAY_ORDER` ⇒ 已补到末尾：%s'
                         % '、'.join(missing))
        except Exception as e:              # noqa: BLE001
            self.log('⚠ 特殊方块配置读取失败：%r' % (e,))
            order = list(getattr(TC, 'DISPLAY_ORDER', ()))
        self._spec_ctx = (cfg, order)
        return self._spec_ctx

    def _special_names(self):
        """10 个勾选项的名字（8 个真类型按固定顺序 + 2 个伪类型）✓"""
        import targets_cfg as TC
        _cfg, order = self._special_ctx()
        return list(order) + [TC.PSEUDO_MARK, TC.PSEUDO_EXPLORE]

    def _mk_special_cb(self, parent, nm, **kw):
        """建一个特殊方块勾选框（**T6：CTkCheckBox，20px 框 + 13pt 字**）——

        ⛔ **变量复用**：`self.special_vars` 里已有就用同一个 ✓
          （新建一份 ⇒ 主页/页签两处不同步 ✗ —— 这条纪律与控件库无关，T6 不许动 ✓）
        """
        import targets_cfg as TC
        cfg, _order = self._special_ctx()
        if getattr(self, 'special_vars', None) is None:
            self.special_vars = {}
        v = self.special_vars.get(nm)
        if v is None:                       # ⚠ 只有第一次才新建变量（否则两处不同步 ✗）
            v = tk.BooleanVar(value=bool(TC.enabled(nm, cfg)))
            self.special_vars[nm] = v
        _p = ctk_theme.palette()
        # ⭐⭐ 用户口径：「**勾选要是蓝的**」⇒ 框一律 `primary_btn`（主色），
        #   **不再用 `primary`**（那是"文字色"角色，§8 纪律 1；深色下两者不同值）
        return ctk.CTkCheckBox(parent, text=nm, variable=v,
                               font=kw.pop('font', None) or ctk_theme.font(ctk_theme.FS_BODY),
                               checkbox_width=20, checkbox_height=20,
                               corner_radius=5, fg_color=_p['primary_btn'],
                               hover_color=_p['primary_d'],
                               border_color=_p['border'],
                               text_color=kw.pop('text_color', None) or _p['text'],
                               command=(lambda n=nm, vv=v: self._save_special(n, vv)),
                               **kw)

    def _stop_items(self):
        """4 个停止开关的 `(which, 变量名, 短文案, 回调名, 悬浮说明)` —— 主页与页签共用一份 ✓

        ⭐⭐ 2026-10-12 **T6 §7③**（用户：「怎么和预览的差这么多」的真实截图暴露）：
          · 病：文案是长句「抽到「幸运」(宝箱→四叶草) 时停止」⇒ 4 个一行 ~800px **排不下**，
            第 4 个被挤出、「抽到「元」被裁 ✗（真实截图可见）
          · 修：显示文案**收短**成 `幸运`/`和平·宝箱怪`/`元素·紫`/`元素·橙`；
            **完整语义挪到 `_Tip` 悬浮提示** ✓
          ⚠⚠ **只改显示文案** —— `which` / `var_name` / 回调名 / `MAPBOT_STOP_*` env
            **一字不动**（落盘语义与子进程 env 完全不变 ✓ 门禁 `verify_no_temp_stop` 也钉着它们）
        """
        return (('lucky', 'stop_lucky_var', '幸运', 'toggle_stop_lucky',
                 '抽到「幸运」⇒ 宝箱掉落替换为四叶草（停脚本、保现场）'),
                ('peace', 'stop_peace_var', '和平·宝箱怪', 'toggle_stop_peace',
                 '抽到「和平·金属宝箱怪」⇒ 地图中至少出现 1 个金属宝箱怪（停脚本、保现场）'),
                ('elem_purple', 'stop_elem_purple_var', '元素·紫', 'toggle_stop_elem_purple',
                 '抽到「元素·紫色」⇒ 地图中所有莱姆至少是紫色位阶（停脚本、保现场）'),
                ('elem_orange', 'stop_elem_orange_var', '元素·橙', 'toggle_stop_elem_orange',
                 '抽到「元素·橙色」⇒ 地图中所有莱姆至少是橙色位阶（停脚本、保现场）'))

    def _mk_stop_cb(self, parent, var_name, text, cb_name, tip='', **kw):
        """建一个停止规则勾选框（**CTkCheckBox**）—— 变量复用同 `_mk_special_cb`

        ⚠⚠ 2026-10-12 用户口径（原话）：「**勾选要是蓝的，字体颜色要和旁边的一样**」
          ── 两条**全域统一**规则（本函数与 `_mk_special_cb`、主控制卡那两颗都照此）──
            ① **勾选框一律主色蓝** `primary_btn`（**不再**按语义分绿/红 —— 用户明确要蓝 ✓）
            ② **文字色一律 `text`（正文灰）**，与旁边的标签**同色**（不再"停止语义用红字"✗）
          ⚠ "停止语义"仍能从**分组标题「停止规则」+ 悬浮说明**看出来，不需要靠勾选框配色 ✗
        """
        var = getattr(self, var_name, None)
        if var is None:                     # ⚠ 只有第一次才新建
            var = tk.BooleanVar(value=True)
            setattr(self, var_name, var)
        _p = ctk_theme.palette()
        return ctk.CTkCheckBox(parent, text=text, variable=var,
                               font=kw.pop('font', None) or ctk_theme.font(ctk_theme.FS_BODY),
                               checkbox_width=20, checkbox_height=20,
                               corner_radius=5, fg_color=_p['primary_btn'],
                               hover_color=_p['primary_d'],
                               border_color=_p['border'],
                               text_color=kw.pop('text_color', None) or _p['text'],
                               command=getattr(self, cb_name), **kw)

    def _home_checks(self, right):
        """「当前状态」卡里的两组勾选 —— **T6 §0 定稿布局** ✓

        · 特殊方块 10 个：**每行 4 个**（3 行：4+4+2）、**统一灰**（不分色 ✓ 用户「拉黑类不要是红的」）
        · 停止规则 4 个：**每行 4 个**（1 行）、**保留红**（停止语义 ✓）
        · 勾选框 20px + **13pt 文字**（与框等高协调；由 `_mk_*_cb` 统一给 ✓）
        """
        _p = ctk_theme.palette()
        checkwrap = ctk.CTkFrame(right, fg_color='transparent', corner_radius=0)
        checkwrap.pack(fill='x', padx=theme.PAD_CARD, pady=(4, 0))
        # ⚠ 分组小标题**必须比勾选文字（FS_BODY=11）显眼**（用户报「旅行商人比'特殊方块'还大」✗）
        #   ⇒ 小标题 = **11pt 加粗**（正文同号但 bold ⇒ 层级清楚，且不会盖过卡片标题 13）✓
        # ⭐⭐⭐ 2026-10-12 用户：「**是下面的日志旁边的**（那俩页签）**删掉吧**」
        #   ⇒ 页签删了 ⇒ 那两页里的 **❗ 说明按钮** 必须挪到这里（**不能跟着页签消失** ✗）：
        #     ⛔ 门禁 `verify_special_semantics.py` ㉑ 按**字面量**钉着 `'❗'` + `_show_special_help`
        #     ⭐ 顺带把"哪一类的说明"补上（旧页签里拉黑/可点各一个 ❗；主页空间小 ⇒ 一个入口
        #       点开后两类都列，见 `_show_special_help(True)` ✓）
        _head = ctk.CTkFrame(checkwrap, fg_color='transparent', corner_radius=0)
        _head.grid(row=0, column=0, columnspan=4, sticky='w')
        ctk.CTkLabel(_head, text='特殊方块', text_color=_p['text'],
                     font=ctk_theme.font_bold(ctk_theme.FS_BODY)).pack(side='left')
        _helped = ctk.CTkButton(_head, text='❗', width=30, height=22, corner_radius=6,
                                font=ctk_theme.font(ctk_theme.FS_BODY),
                                fg_color='transparent', hover_color=_p['card2'],
                                text_color=_p['primary'], border_width=1,
                                border_color=_p['primary'],
                                command=lambda: self._show_special_help(True))
        _helped.pack(side='left', padx=(6, 0))
        _Tip(_helped, '点这里看**每个特殊方块**的完整说明（是什么/点了会怎样/不勾会怎样）')
        _cols = 4                       # ⭐ §0 定稿：每行 4 个 ⇒ 10 个 = 4+4+2 ✓
        # ⚠ 间距常量**两组共用**（用户 2026-10-12：「**停止规则的四个勾选框之间间隔和上面
        #   特殊方块的要一致**」）⇒ 抽成一个变量，两处引用同一个值（不再各写各的 ✗）
        #   ⚠ 用 `padx=(0, _GAP)` + 每列 `uniform` ⇒ 列宽一致、间隔一致 ✓
        _GAP = 12
        for _c in range(_cols):
            checkwrap.grid_columnconfigure(_c, weight=1, uniform='chk')
        for i, nm in enumerate(self._special_names()):
            try:
                _w = self._mk_special_cb(checkwrap, nm, text_color=_p['text'])
                _w.grid(row=1 + i // _cols, column=i % _cols, sticky='w',
                        padx=(0, _GAP if i % _cols < _cols - 1 else 0), pady=(0, 2))
                # ⭐ 逐项 ⓘ 说明（原在"特殊方块"页签里）⇒ 页签删了，说明**不能丢** ✓
                #   ⚠⚠ 表达式里**只能引用绑进默认参数的 `_n`**，**绝不引用外层 `nm`** ——
                #     第一版写成 `lambda _e, n=nm: …describe(n)`，而下一行又误用裸 `n`
                #     ⇒ `NameError: name 'n' is not defined`，**3 个勾选框当场建不起来** ✗
                #     （实跑抓到：控制台刷「主页特殊方块勾选建不起来」✓）
                import targets_cfg as _TC0
                _desc = _TC0.describe(nm)
                _w.bind('<Button-3>', lambda _e, _n=nm: dialogs.text_dialog(
                    '特殊方块说明 · %s' % _n, _TC0.describe(_n), 520, 300))
                _Tip(_w, '%s\n（右键看详细说明）' % str(_desc).split('\n')[0])
            except Exception as e:          # noqa: BLE001
                self.log('⚠ 主页特殊方块勾选建不起来（%s）：%r' % (nm, e))
        stopwrap = ctk.CTkFrame(right, fg_color='transparent', corner_radius=0)
        stopwrap.pack(fill='x', padx=theme.PAD_CARD, pady=(4, 0))
        # ⭐ 2026-10-12 用户口径：「**停止规则，改成预言石碑停止规则**」
        #   ⇒ 这 4 个开关本就是**预言石碑**抽到的卡（幸运/和平·宝箱怪/元素·紫/元素·橙）
        #     ⇒ 分组标题写全，避免与"红装锁/凌晨停"等别的停止机制混淆 ✓
        # ⭐⭐ 2026-10-12 用户追加：「**预言石碑停止规则也要类似特殊地块后面加上感叹号
        #   解释说明**」⇒ 与上面「特殊方块 ❗」**同款按钮、同一处 `_show_special_help`
        #   之外的入口**：停止规则的说明来自 `self._stop_items()` 的第 5 个元素（`tip`）✓
        _shead = ctk.CTkFrame(stopwrap, fg_color='transparent', corner_radius=0)
        _shead.grid(row=0, column=0, columnspan=4, sticky='w')
        ctk.CTkLabel(_shead, text='预言石碑停止规则', text_color=_p['text'],
                     font=ctk_theme.font_bold(ctk_theme.FS_BODY)).pack(side='left')
        _shelp = ctk.CTkButton(_shead, text='❗', width=30, height=22, corner_radius=6,
                               font=ctk_theme.font(ctk_theme.FS_BODY),
                               fg_color='transparent', hover_color=_p['card2'],
                               text_color=_p['primary'], border_width=1,
                               border_color=_p['primary'],
                               command=self._show_stop_help)
        _shelp.pack(side='left', padx=(6, 0))
        _Tip(_shelp, '点这里看**这 4 条停止规则**各自的完整含义（抽到什么、会怎样）')
        # ⭐⭐ 2026-10-12 用户口径：「**停止规则那四个勾选既然已经文字简写了，就变回一行四个吧**」
        #   ＋「**它们之间的间隔和上面特殊方块的要一致**」
        #   ⇒ 一行 4 个 + **与特殊方块同一套列网格**（4 列 uniform + 同一个 `_GAP`）✓
        #     这样两组的列边界**逐列对齐**、间隔视觉一致 ✓（旧版两组各写各的 padx=6/12 ✗）
        for _c in range(_cols):
            stopwrap.grid_columnconfigure(_c, weight=1, uniform='chk')
        for i, (_w, vn, txt, cb, tip) in enumerate(self._stop_items()):
            try:
                _b = self._mk_stop_cb(stopwrap, vn, txt, cb, tip=tip)
                _b.grid(row=1, column=i, sticky='w',
                        padx=(0, _GAP if i < _cols - 1 else 0))
                _Tip(_b, tip)
            except Exception as e:          # noqa: BLE001
                self.log('⚠ 主页停止规则勾选建不起来（%s）：%r' % (txt, e))
        # ⭐ 2026-10-12：**凌晨 4:58** 说明原在「预言石碑停止规则」页签里 ⇒ 页签删了
        #   ⇒ 挪到主页（它是"停止"语义的补充说明，跟这一组放一起最合适 ✓）
        ctk.CTkLabel(stopwrap, text='⏰ 凌晨 4:58 自动停止（打完最后一张图，不是硬杀 ✓）',
                     text_color=_p['warn'], font=ctk_theme.font(ctk_theme.FS_HINT),
                     justify='left', anchor='w').grid(
            row=2, column=0, columnspan=_cols, sticky='w', pady=(2, 0))

    # ---------- 页签区（T6：改用 `CTkTabview`；日志仍 tk `ScrolledText`）----------
    def _build_tabs(self):
        _p = ctk_theme.palette()        # ⚠ 元组 ⇒ ctk 自动跟随主题 ✓
        # ⭐⭐ 2026-10-13 「手绘效果图 1:1 复刻」（docs/09）：
        #   ⛔ 三处与效果图差很多（用户：「**日志工具更新那里差很多**」）——
        #     ① 页签**居中**（效果图是**靠左**）⇒ 用 `anchor='w'` ✓
        #        （ctk 的 `CTkTabview` **自己就支持** `anchor`，见 `_configure_grid`）
        #     ② 页签**外面套一张白卡**（`fg_color=card`）⇒ 效果图里页签与日志框
        #        **直接铺在窗口灰底上** ⇒ 改 `fg_color=bg` ✓
        #     ③ 选中段是**实心靛蓝胶囊 + 白字**（效果图是**白胶囊 + 靛蓝/正文色字**）
        #        ⇒ `segmented_button_selected_color=card`、未选中 = `bg`（等于无底），
        #          `segmented_button_fg_color=bg`（容器底不可见）✓
        #   ⚠ `segmented_button_unselected_color` 不能给 `'transparent'`（ctk 不吃），
        #     给**同一个 `bg`** 即视觉上"没有底" ✓
        self.nb = ctk.CTkTabview(
            self.stack.frame, corner_radius=12, fg_color=_p['bg'],
            anchor='w',                       # ⭐ 页签靠左（效果图排布）
            segmented_button_fg_color=_p['bg'],
            # ⚠ 选中 = 卡片底（白/深卡）⇒ 就是一个"白胶囊" ✓
            segmented_button_selected_color=_p['card'],
            segmented_button_selected_hover_color=_p['card2'],
            segmented_button_unselected_color=_p['bg'],
            segmented_button_unselected_hover_color=_p['card2'],
            text_color=_p['text'])
        self.stack.add(self.nb, weight=1, pady=(theme.ROW_GAP, 0))
        # ⚠ `CTkTabview` **没有** ttk 那套 `nb.tab(i,'text')/index('end')` API ⇒
        #   页签名自己记一份（自检与排查都靠它 ✓）
        # ⭐⭐⭐ 2026-10-12 用户口径（原话）：「**是下面的日志旁边的**（那俩特殊方块和
        #   预言石碑停止规则）**删掉吧**」
        #   ⇒ 页签栏只剩 **日志 / 工具 / 关于·更新** 三个 ✓
        #   ⚠⚠ 那两页里的**勾选本身不删** —— 主页「当前状态」卡里**本来就有同一批**
        #     （`_home_checks`，共用同一批 BooleanVar）⇒ 功能一个不少 ✓
        #   ⚠ 但有两样是**只在那两页里**的，必须**挪到主页**去、不能跟着页签一起消失：
        #     ① `❗` + `ⓘ` 说明按钮（门禁 `verify_special_semantics.py` ㉑ 钉着 `'❗'` 字面量）
        #     ② 凌晨 4:58 自动停止那句说明
        self.tab_names = ['日志', '工具', '关于 / 更新']
        # ⚠⚠ 2026-10-12 **修「切深色后 5 个页签底还是白的」**：
        #   `CTkTabview` **内部自建**一个 CTkFrame 当每个页签的容器，它吃的是**建它那一刻**
        #   解析出的**单值**色 ⇒ 切主题时那 5 个 Frame **不会变**（探针实测抓到 5 处
        #   `CTkFrame fg_color='#FFFFFF'` 单值 ✗✗）—— 这正是用户说的"切换还是有问题"。
        #   ⇒ 记下它们，切换时由 `_paint_tk_widgets()` **手动重设**（与 tk 控件同等待遇）✓
        #   ⚠ 顺序：**必须在 `nb.add(...)` 之后**（`winfo_children()` 里此刻才有那些 Frame）
        #     —— 第一版我写在 `self.tab_names` 之前 ⇒ 记到 0 个、修了个寂寞 ✗（本轮踩到 ✓）
        #   ⭐⭐ **角色在收集时定死**（`self._tab_roles` = `[(容器, 'card'|'card2'|None)]`）：
        #     第一版"每次拿当前色去和浅色值比对"是错的 —— 切过一次后 `_cur` 已是深色值
        #     ⇒ 比对失败 ⇒ 那层被刷成 `card` ⇒ **浅色下的 `card2` 层次被刷平** ✗✗
        #     （实测：切回后少了一种色 `#F5F6F8`）⇒ 现在只按角色还原 ✓
        self._tab_roles = []
        try:
            self._collect_tab_frames()
        except Exception:       # noqa: BLE001
            self._tab_roles = []
        self._build_tab_log()
        # ⛔ 2026-10-12 用户：「**是下面的日志旁边的**（特殊方块 + 预言石碑停止规则）**删掉吧**」
        #   ⇒ 这两个页签**不再建**（内容已在主页「当前状态」卡里：勾选共用同一批变量；
        #     ❗/ⓘ 说明 与 凌晨停说明 已挪进主页 ✓）
        #   ⚠ 函数体**保留**（`_build_tab_special` / `_build_tab_stop` 还在，只是不调用）
        #     —— 它们同时被 `_mk_special_cb` / `_mk_stop_cb` 的**说明文案来源**引用，
        #       而且门禁按**字符串**查 `'❗'`/`_show_special_help`/`TC.DISPLAY_ORDER`；
        #       真要彻底删函数得同步改门禁（属别的活儿）⇒ 本轮只**取消调用** ✓
        self._build_tab_tools()
        self._build_tab_about()
        # ⚠ 页签内容建好**之后再收一次**（把所有 CTkFrame 后代都纳进来 ⇒ 不漏 ✓）
        try:
            self._collect_tab_frames()
        except Exception:       # noqa: BLE001
            pass
        try:
            self.nb.set('日志')              # ⭐ 默认落在「日志」（最常用 ✓）
        except Exception:                   # noqa: BLE001
            pass

    def _collect_tab_frames(self):
        """把 `CTkTabview` **内部自建的**那几层容器收进 `self._tab_roles`（切主题要手动重设）

        ⚠ 为什么要"收集"而不是"按名字取"：`CTkTabview` 的页签容器是**私有结构**
          （`nb.tab(name)` 拿到的是它自建的那层，里面还套一层）⇒ 用 `winfo_children()`
          **递归扫**最稳（不依赖 ctk 内部实现细节 ✓）；重复调用**幂等**（用 id 去重 ✓）

        ⭐ **角色在收集时定死**：看它**当前**吃的是"卡底"还是"次级卡底"（那一刻还一定是
          浅色的建窗期值 ✓）⇒ 存进 `self._tab_roles` ⇒ 切主题时**只按角色还原**，
          不再"拿当前色去猜"（切过一次之后就猜不准了 ✗ 本轮实测踩到）
        """
        seen = {id(x) for x, _r in self._tab_roles}
        stack = [self.nb]
        while stack:
            w = stack.pop()
            for c in w.winfo_children():
                # ⚠ 只收 **CTkFrame**（页签容器就是它）—— 别把 `CTkCanvas`（内部画布，
                #   没有 `cget('fg_color')`）、`CTkLabel/CTkButton` 等一起卷进来 ✗
                #   （第一版按 `startswith('CTk')` 收 ⇒ 收到 124 个、含 CTkCanvas ⇒ 崩 ✗）
                if type(c).__name__ == 'CTkFrame' and id(c) not in seen:
                    seen.add(id(c))
                    self._tab_roles.append((c, self._role_of(c)))
                stack.append(c)

    @staticmethod
    def _role_of(fr):
        """这个页签容器吃的是哪一档底色 ⇒ `'card'` / `'card2'` / `None`（不碰透明）"""
        try:
            cur = fr.cget('fg_color')
            if isinstance(cur, str) and cur.lower() in ('transparent', ''):
                return None
            light = cur if isinstance(cur, str) else cur[0]
            return 'card2' if str(light).upper() == _LIGHT_CARD2.upper() else 'card'
        except Exception:       # noqa: BLE001
            return None

    def _build_tab_log(self):
        tab = self.nb.add('日志')
        # ⚠⚠ **日志框保留 tk `ScrolledText`**（T6 §2 硬约束）：
        #   `verify_lock_kind.py` 真跑 `show_red_lock()` 并调 `self.txt.get('1.0','end')`
        #   ⇒ `CTkTextbox` 的 API 不同 ✗；`verify_no_temp_stop.py` ⑫ 也断言 `self.txt`
        #   高度 >100 ⇒ 名字与归属**一个字都不许改** ✓
        # ⭐ 2026-10-13 复刻：日志框加 **1px 浅描边**（效果图里那个浅框 ✓）
        #   ⚠ 用 `highlightthickness=1` + `highlightbackground`（tk 支持，且**不占**内边距布局）
        #     —— `relief='solid'` 的边色由系统暗化算，**控不了色** ✗
        #   ⚠ 描边色必须登记进 `_paint_tk_widgets()`（tk 控件无主题机制）✓
        self.txt = scrolledtext.ScrolledText(tab, font=theme.FONT_MONO, wrap='none',
                                            height=14, relief='flat',
                                            highlightthickness=1,
                                            highlightbackground=theme.C_BORDER,
                                            highlightcolor=theme.C_BORDER,
                                            bg='#FFFFFF', fg=theme.C_TEXT)
        self.txt.pack(fill='both', expand=True, padx=theme.PAD_TAB, pady=4)
        self.txt.configure(state='disabled')
        # ⭐ 着色（规划 §4.3「`›` 状态行/退出码/崩溃提示着色」✓）
        self.txt.tag_configure('status', foreground=theme.C_PRIMARY, font=(theme.F_MONO, 9, 'bold'))
        self.txt.tag_configure('ok', foreground=theme.C_OK, font=(theme.F_MONO, 9))
        self.txt.tag_configure('warn', foreground=theme.C_WARN, font=(theme.F_MONO, 9))
        self.txt.tag_configure('bad', foreground=theme.C_DANGER, font=(theme.F_MONO, 9, 'bold'))
        self.txt.tag_configure('head', foreground=theme.C_TEXT, font=(theme.F_MONO, 9, 'bold'))
        self.txt.tag_configure('dim', foreground=theme.C_TEXT_DIM, font=(theme.F_MONO, 9))
        # ⭐ 2026-10-18 方案 A：`strong` = 日志里原本 `**…**` 的那段（加粗、不再显示星号 ✓）
        #   ⚠ 这个 tag 必须在 `log()` 之前存在（建窗顺序：`_build_tab_log` 早于任何 log 调用 ✓）
        self.txt.tag_configure('strong', foreground=theme.C_TEXT, font=(theme.F_MONO, 9, 'bold'))

    def _build_tab_special(self):
        """特殊方块页签：**按 `DISPLAY_ORDER` 固定顺序**、**分两组**、每项带说明 ⓘ ✓

        ⭐ 语义（`targets_cfg.py` 顶部，2026-10-09 用户口径）：
          · **拉黑类**（`BLOCK_NAMES`）⇒ 不勾 = **完全拉黑**（不点、也不借道 ✗）
          · **可点类**（`PICK_IF_BLOCKING`）⇒ 不勾 = **不专门拿，但挡路会点** ✓
        ⭐ 另外两个**伪类型**（★标记格 / ★紫橙探索格）单列一行（默认勾 ✓）
        ⭐⭐ 勾选框由 `_mk_special_cb()` 建 ⇒ 与**主页那份共用同一批 BooleanVar**
          （勾一处另一处立刻同步 ✓）；勾选项文字**统一正文灰**
          （用户口径：「**拉黑类不要是红的**」—— 分组**标题**的红/绿保留 ✓）
        """
        import targets_cfg as TC
        _p = ctk_theme.palette()
        tab = self.nb.add('特殊方块')
        cfg, order = self._special_ctx()
        row = 0
        for title, names, color, is_block in (
                ('拉黑类（不勾 = 完全拉黑：不点、也不借道）',
                 [n for n in order if n in TC.BLOCK_NAMES], _p['danger'], True),
                ('可点类（不勾 = 不专门拿，但挡路也会点）',
                 [n for n in order if n not in TC.BLOCK_NAMES], _p['ok'], False)):
            head = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
            head.grid(row=row, column=0, sticky='w', padx=theme.PAD_TAB,
                      pady=(theme.PAD_TAB, 2))
            # ⚠ 分组**标题**的红/绿是"类别标识"（不是勾选项）⇒ 保留 ✓
            ctk.CTkLabel(head, text=title, text_color=color,
                         font=ctk_theme.font(ctk_theme.FS_BODY)).pack(side='left')
            # ⭐ 门禁 `verify_special_semantics.py` ㉑ 钉着 `'❗'` 字面量 + `_show_special_help`
            ctk.CTkButton(head, text='❗', width=30, height=24, corner_radius=6,
                          font=ctk_theme.font(ctk_theme.FS_BODY), fg_color='transparent',
                          hover_color=_p['card2'], text_color=_p['primary'],
                          border_width=1, border_color=_p['primary'],
                          command=lambda b=is_block: self._show_special_help(b)).pack(
                side='left', padx=(6, 0))
            row += 1
            line = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
            line.grid(row=row, column=0, sticky='w', padx=theme.PAD_TAB, pady=(0, 4))
            for nm in names:
                # ⭐ 勾选项文字**统一正文灰**（`is_block` 不再改色 ✓ 用户「拉黑类不要是红的」）
                self._mk_special_cb(line, nm, text_color=_p['text']).pack(
                    side='left', padx=(0, 10))
                ctk.CTkButton(line, text='ⓘ', width=28, height=22, corner_radius=6,
                              font=ctk_theme.font(ctk_theme.FS_HINT), fg_color='transparent',
                              hover_color=_p['card2'], text_color=_p['dim'],
                              command=lambda n=nm: dialogs.text_dialog(
                                  '特殊方块说明 · %s' % n, TC.describe(n), 520, 300)).pack(
                    side='left', padx=(0, 14))
            row += 1
        # ---- 两个伪类型（★标记格 / ★紫橙探索格，默认勾 ✓）----
        ctk.CTkLabel(tab, text='其它目标（伪类型）', text_color=_p['text'],
                     font=ctk_theme.font(ctk_theme.FS_BODY)).grid(
            row=row, column=0, sticky='w', padx=theme.PAD_TAB, pady=(theme.PAD_TAB, 2))
        row += 1
        line = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
        line.grid(row=row, column=0, sticky='w', padx=theme.PAD_TAB)
        for nm in (TC.PSEUDO_MARK, TC.PSEUDO_EXPLORE):
            self._mk_special_cb(line, nm, text_color=_p['text']).pack(
                side='left', padx=(0, 10))
            ctk.CTkButton(line, text='ⓘ', width=28, height=22, corner_radius=6,
                          font=ctk_theme.font(ctk_theme.FS_HINT), fg_color='transparent',
                          hover_color=_p['card2'], text_color=_p['dim'],
                          command=lambda n=nm: dialogs.text_dialog(
                              '特殊方块说明 · %s' % n, TC.describe(n), 520, 300)).pack(
                side='left', padx=(0, 14))
        ctk.CTkLabel(tab, text_color=_p['dim'], font=ctk_theme.font(ctk_theme.FS_HINT), justify='left',
                     wraplength=900,
                     text='（勾 = 专门去拿 ｜ 不勾 = 不专门拿，但挡路也会点 ｜'
                          '⚠ 拉黑类不勾 = 完全拉黑）\n'
                          '勾选**立即落盘** `runs[/<tag>]/target_types.json`'
                          '（跑着的循环靠 mtime 热读 ⇒ **下一轮规划就生效** ✓）').grid(
            row=row + 1, column=0, sticky='w', padx=theme.PAD_TAB, pady=(8, 0))

    def _build_tab_stop(self):
        """**预言石碑停止规则**页签：4 开关 + 红装锁状态卡 + 凌晨 4:58 说明 ✓"""
        _p = ctk_theme.palette()
        # ⭐ 页签名与 `self.tab_names` 里的**必须逐字一致**（切换/收集都按这个名字找 ✓）
        tab = self.nb.add('预言石碑停止规则')
        ctk.CTkLabel(tab, text='预言石碑停止脚本（勾 = 抽到就停脚本、保现场）',
                     text_color=_p['text'], font=ctk_theme.font(ctk_theme.FS_BODY)).grid(
            row=0, column=0, sticky='w', padx=theme.PAD_TAB, pady=(theme.PAD_TAB, 2))
        box = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
        box.grid(row=1, column=0, sticky='w', padx=theme.PAD_TAB)
        # ⭐ 4 个变量由 `_mk_stop_cb()` **按需创建/复用** ⇒ 与**主页那份是同一批** ✓
        for _w, _vn, _txt, _cb, _tip in self._stop_items():
            _b = self._mk_stop_cb(box, _vn, _txt, _cb, tip=_tip)
            _b.pack(side='left', padx=(0, 12))
            _Tip(_b, _tip)
        ctk.CTkLabel(tab, text_color=_p['dim'], font=ctk_theme.font(ctk_theme.FS_HINT),
                     text='（元素蓝档不停 ✓；与红装同一套处置：停脚本 → 保现场 → 你自己处理完'
                          '再点「开始」即可 ✓）'
                     ).grid(row=2, column=0, sticky='w', padx=theme.PAD_TAB, pady=(4, 0))

        # ⛔⛔ 2026-10-12 **删掉「停脚本·保现场锁」整张卡 + 「红装已处理·解锁」按钮**
        #   （用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
        #   ---- 为什么删 ----
        #     锁定是**额外的一层**（写锁 ⇒ 下次启动被拒 ⇒ 要人工解锁）；
        #     用户要的只是"**遇到就停**"这个动作本身 ⇒ 锁完全多余 ✗
        #     而且它**真卡过人**：`kind=shrine` 被报成"发现了红装"、
        #     `kind=foretell` 显示"未知类型" ⇒ 用户两次问「怎么解除锁定」✗
        #   ⇒ 现在：停脚本之后把现场留着，用户处理完**直接再点「开始」** ✓
        #   ⚠ 原来这里那张卡的 `row=3`；删掉后下面那行提示**上移到 row=3**（不然中间空一行 ✓）
        ctk.CTkLabel(tab, text_color=_p['warn'], font=ctk_theme.font(ctk_theme.FS_HINT), justify='left',
                     wraplength=900,
                     text='⏰ 凌晨 4:58 自动停止（打完最后一张图，不是硬杀 ✓）').grid(
            row=3, column=0, sticky='w', padx=theme.PAD_TAB, pady=(theme.PAD_TAB, 0))

    def _build_tab_tools(self):
        """工具页签：环境检查（`paths.diagnose()` 结果列表化）/ 日志目录 / 扫屏 / 查重 / 多开 ✓

        ⭐ 2026-10-12（05 §4.5a 第 8 项）：5 个按钮原来**混用 4 种颜色**
          （灰/灰/灰/橙/蓝）⇒ 视觉嘈杂 ✗ ⇒ **统一中性色**（次要操作去色）✓
        ⭐ T6：按钮换 `CTkButton`（**统一中性色**的纪律不变 ✓）
        """
        _p = ctk_theme.palette()
        tab = self.nb.add('工具')
        bar = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
        bar.grid(row=0, column=0, sticky='w', padx=theme.PAD_TAB, pady=(theme.PAD_TAB, 4))
        for text, fn in (('环境检查', self.check),
                         ('打开日志目录', self.open_logs),
                         ('扫当前屏（标定用）', self.scan_screen),
                         ('检查重复循环', self.dedupe_loops),
                         ('多开一个新号', self.spawn_multi)):
            ctk.CTkButton(bar, text=text, height=30, corner_radius=8, font=ctk_theme.font(ctk_theme.FS_SUB),
                          fg_color=_p['card2'], hover_color=_p['card'],
                          text_color=_p['text'], border_width=1,
                          border_color=_p['border'], command=fn).pack(
                side='left', padx=(0, 8))
        # ⭐⭐⭐ 2026-10-15 **「立即招募」挪到这里**（用户口径，原话）：
        #   「**立即招募按钮移到下面的工具栏里，按钮样式要和工具栏里的统一样式**」✓
        #   ---- 为什么要挪 ----
        #     主控制卡那一排**再添一颗勾选就要 1214px**，而窗口默认只有 **1100**
        #     ⇒ 装不下，硬塞会把「存图」压掉（上次那个"看不见"的 bug ✗）
        #     ⇒ 把它挪到「工具」页签，原位换给「免广告」勾选 ✓
        #   ---- ⚠ 样式**逐项抄上面那五个**（用户点名要"统一"✓）----
        #     `height=30` / `corner_radius=8` / `font=FS_SUB` /
        #     `fg_color=card2` / `hover_color=card` / `text_color=text` /
        #     `border_width=1` + `border_color=border` / `padx=(0,8)` ✓
        #   ---- ⚠ 可用性联动**保留**（勾了「免费招募」才可点）----
        #     判据见 `_sync_recruit_btn` —— 它按 `state='normal'/'disabled'` 切 ✓
        #     ⚠ 禁用态下 ctk 会自己画灰 ⇒ **与工具栏其它按钮的辨识度仍然清楚** ✓
        self.recruit_now_btn = ctk.CTkButton(
            bar, text='立即招募', height=30, corner_radius=8,
            font=ctk_theme.font(ctk_theme.FS_SUB),
            fg_color=_p['card2'], hover_color=_p['card'],
            text_color=_p['text'], border_width=1,
            border_color=_p['border'], state='disabled',
            command=self.recruit_now)
        self.recruit_now_btn.pack(side='left', padx=(0, 8))
        _Tip(self.recruit_now_btn,
             '**不等收工、现在就做一次免费招募**\n'
             '（会算最优标签组合 ⇒ 直接抽）\n'
             '⚠ 需要先勾上主页的「免费招募」（那是这次授权的凭据）\n'
             '⚠ 循环正在跑时不可点（两个子进程会互相抢点击）')
        # ⭐⭐⭐⭐ 2026-10-16 **「果实记录」按钮**（用户口径，两次）
        #   ① 「类似小助手的天赋果实记录，**做好放到工具栏里**」
        #   ② ⛔ 「**去掉「扫天赋果实」按钮**，点天赋果实记录要**能直接在工具那里
        #        看到果实记录，不要还得去日志看**」  ← 本次
        #   ---- 所以现在只有**一颗**按钮 ----
        #     · ❌ 删掉「扫天赋果实」：收工时**体力 < 100 会自动扫** ⇒
        #       手动那颗是多余的（用户明确要去掉 ✓）
        #     · ✅ 「果实记录」：点了**直接往上面那个文本框里写**（`env_txt`）
        #       ⛔ **不再打日志区**（用户：「**不要还得去日志看**」✗）
        #   ---- ⚠ 为什么复用 `env_txt` 而不是新开一块 ----
        #     工具页签本来就有个大文本框（`env_txt`，环境检查结果写那儿）✓
        #     ⇒ 同一块地方两用，版面不挤、也不用再抢高度 ✓
        #     ⚠ 内容**整体替换**（不留上一次的残留 ⇒ 看得清 ✓）
        #     ⚠ 用**等宽字体** ⇒ 那几列（日期/数量/获取/消耗）能对齐 ✓
        #   ---- ⚠ 样式**逐项抄那排按钮**（用户点名要"统一"✓）----
        _fb = ctk.CTkButton(
            bar, text='果实记录', height=30, corner_radius=8,
            font=ctk_theme.font(ctk_theme.FS_SUB),
            fg_color=_p['card2'], hover_color=_p['card'],
            text_color=_p['text'], border_width=1,
            border_color=_p['border'], command=self.fruit_report)
        _fb.pack(side='left', padx=(0, 8))
        _Tip(_fb,
             '**看天赋果实获取记录**（只读本地文件，不碰设备）\n'
             '点一下 ⇒ 记录**直接显示在下面的框里** ✓\n'
             '口径抄小助手：总获取 / 总消耗 / 净变化 / 日均 / 日增峰值\n'
             '· 记录存在 `runs/<实例名>/fruit_record.json`（**每个窗口独立**）\n'
             '· 收工时**体力 < 100** 会自动扫一次（不用手动扫）')
        # ⚠ 工具页签的文本框也**保留 tk**（同日志框的理由：读起来最稳、等宽朴素 ✓）
        self.env_txt = scrolledtext.ScrolledText(tab, font=theme.FONT_MONO, wrap='word',
                                                height=12, relief='flat',
                                                bg='#FFFFFF', fg=theme.C_TEXT)
        self.env_txt.grid(row=1, column=0, sticky='nsew', padx=theme.PAD_TAB,
                          pady=(0, theme.PAD_TAB))
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self.env_txt.configure(state='disabled')

    def _build_tab_about(self):
        """关于/更新页签：版本卡 + 热更状态 + 检查更新 / 回滚 + 反馈指引 ✓"""
        _p = ctk_theme.palette()
        tab = self.nb.add('关于 / 更新')
        self.about_var = tk.StringVar(value='（读取中…）')
        ctk.CTkLabel(tab, text='版本与热更', text_color=_p['text'],
                     font=ctk_theme.font(ctk_theme.FS_BODY)).grid(row=0, column=0, sticky='w',
                                             padx=theme.PAD_TAB,
                                             pady=(theme.PAD_TAB, 2))
        ctk.CTkLabel(tab, textvariable=self.about_var, text_color=_p['text'],
                     font=ctk_theme.font(ctk_theme.FS_MONO_SUB), justify='left', anchor='w',
                     wraplength=900, corner_radius=8, fg_color=_p['card2']).grid(
            row=1, column=0, sticky='ew', padx=theme.PAD_TAB)
        bar = ctk.CTkFrame(tab, fg_color='transparent', corner_radius=0)
        bar.grid(row=2, column=0, sticky='w', padx=theme.PAD_TAB,
                 pady=(theme.PAD_TAB, 0))
        for text, mode in (('检查更新', 'check'), ('立即更新', 'hot'),
                           ('回滚到出厂版', 'rollback'), ('刷新状态', 'status')):
            _danger = (mode == 'rollback')
            ctk.CTkButton(bar, text=text, height=30, corner_radius=8, font=ctk_theme.font(ctk_theme.FS_SUB),
                          fg_color=(_p['danger'] if _danger else _p['card2']),
                          hover_color=('#8E1B1B' if _danger else _p['card']),
                          text_color=(_p['bg'] if _danger else _p['text']),
                          border_width=(0 if _danger else 1),
                          border_color=_p['border'],
                          command=lambda m=mode: self.run_hotupdate(m)).pack(
                side='left', padx=(0, 8))
        ctk.CTkLabel(tab, text_color=_p['dim'], font=ctk_theme.font(ctk_theme.FS_HINT), justify='left',
                     wraplength=900,
                     text='出问题时把这两样发给开发者就能定位：\n'
                          '  · `runs/gui_<时间>.log`（子进程原始输出，说明书让朋友发这个）\n'
                          '  · `runs/loop/loop_log.json`（整盘观测与规划的结构化事件流）\n'
                          '⚠ `runs/gui_console_<日期>.log` 里还有**窗口自己**的日志'
                          '（勾选变更这类只有 GUI 知道的事件 ✓）').grid(
            row=3, column=0, sticky='w', padx=theme.PAD_TAB, pady=(theme.PAD_TAB, 0))
        tab.grid_columnconfigure(0, weight=1)
        self._refresh_about()

    # ══════════════════════════════════════════════════════════════════
    # ①b T6 · 双主题：色板下发 / tk 控件重设色 / 切换回调
    # ══════════════════════════════════════════════════════════════════
    def _paint_theme_consts(self, mode):
        """把色板写进 `theme` 的 tk 侧常量（棋盘/日志/StatusDot 都读它们 ✓）

        ⚠ ctk 控件换主题是**自动**的；**tk 控件（棋盘 Canvas / 日志 / 存图勾选 /
          StatusDot / `dialogs`）没有主题机制** ⇒ 只能"重设常量 + 重画"（工单 §T6 §Step 4 原话）✓
        """
        try:
            _p = ctk_theme.palette_flat(mode)
            for _src, _dst in _TK_THEME_KEYS:
                try:
                    setattr(theme, _dst, _p[_src])
                except Exception:               # noqa: BLE001
                    pass
            for _k, _v in ctk_theme.board_colors(mode).items():
                try:
                    setattr(theme, _k, _v)
                except Exception:               # noqa: BLE001
                    pass
        except Exception:       # noqa: BLE001
            pass

    def _paint_tk_widgets(self):
        """重设**那几个 tk 控件**的色（主题切换时调；**每个都容错** ✓）

        ⚠ 这里必须用 **palette_flat(mode)**（单值）—— tk 控件没有双色元组机制，
          喂元组进去会直接 TclError ✗（§7② 的元组只给 ctk 控件用 ✓）
        """
        _p = ctk_theme.palette_flat(self._mode)
        # ⓪ 窗口根 + VStack 容器（都是 tk，bg 得手动换 ⇒ 否则深色下露白底 ✗）
        try:
            self.root.configure(bg=_p['bg'])
        except Exception:       # noqa: BLE001
            pass
        try:
            # ⚠⚠ 这一句是**唯一**必须小心的地方：`stack.frame` 现在是 **ctk.CTkFrame**
            #   （双色元组，自己跟主题 ✓）⇒ **不要**再 `configure(bg=…)` 它 ✗
            #   （tk 的 `bg` 参数在 ctk 上不存在，且那句正是"把元组降级成单值"的元凶）
            #   ⇒ 只对**真正的 tk 根窗口**设底色（`root` 是 tk.Tk，必须手动换 ✓）
            pass
        except Exception:       # noqa: BLE001
            pass
        # ⓪b ⭐ 2026-10-13 复刻：顶栏底部那条 **1px 分隔线**（tk `Frame` ⇒ 手动换色）
        try:
            self.topline.configure(bg=_p['border'])
        except Exception:       # noqa: BLE001
            pass
        # ①b ⚠⚠ **页签容器 Frame**（`CTkTabview` 内部自建、吃的是**建它那一刻**的单值色
        #    ⇒ 切主题不会变 ✗✗ 探针实测抓到 5 处 `CTkFrame fg_color='#FFFFFF'`）
        #   ⇒ 手动重设（这是"切深色后页签底还是白的"的真凶）✓
        #   ⚠⚠ 角色在**收集时**就定好（`self._tab_roles`：'card' / 'card2' / None），
        #     这里**只按角色还原** —— 第一版"每次拿当前色去和浅色值比对"是错的：
        #     切过一次之后 `_cur` 已经是深色值 ⇒ 比对失败 ⇒ 那层被刷成 `card`，
        #     **浅色下的 `card2` 层次被刷平** ✗（本轮实测踩到：切回后少了 `#F5F6F8`）
        for _f, _role in (getattr(self, '_tab_roles', None) or ()):
            try:
                if _role:
                    _f.configure(fg_color=_p[_role])
            except Exception:       # noqa: BLE001
                pass
        # ① 日志框（ScrolledText）+ 它的 6 个 tag
        try:
            self.txt.configure(bg=_p['logbg'], fg=_p['logfg'],
                              insertbackground=_p['logfg'],
                              highlightbackground=_p['border'],
                              highlightcolor=_p['border'])
            self.txt.tag_configure('status', foreground=_p['primary'])
            self.txt.tag_configure('ok', foreground=_p['ok'])
            self.txt.tag_configure('warn', foreground=_p['warn'])
            self.txt.tag_configure('bad', foreground=_p['danger'])
            self.txt.tag_configure('head', foreground=_p['text'])
            self.txt.tag_configure('dim', foreground=_p['dim'])
            # ⭐ 2026-10-18 方案 A：切主题时 `strong` 也要跟着换色（tk 控件无主题机制 ✗）
            self.txt.tag_configure('strong', foreground=_p['text'])
        except Exception:       # noqa: BLE001
            pass
        # ①b ⭐⭐ 2026-10-12 用户：「**日志的滚动条也是**（深色下不对）」
        #   ── 根因：`ScrolledText` **自带**的滚动条是独立 tk 控件，吃的是**系统色**
        #     （实测 cget 出 `SystemButtonFace` / `SystemScrollbar` 这类**主题占位名**）
        #     ⇒ 从没人给它设过色 ⇒ 深色下仍是**浅灰系统条**，贴在深色日志框边格外扎眼 ✗
        #   ⇒ 按当前主题手动刷它（滑槽 + 滑块 + 边框 + 高亮）✓
        #     ⚠ 两处日志框都刷（日志页 + 工具页）✓
        for _sb_owner in ('txt', 'env_txt'):
            _st = getattr(self, _sb_owner, None)
            if _st is None:
                continue
            for _sb in (getattr(_st, 'vbar', None), getattr(_st, 'hbar', None)):
                if _sb is None:
                    continue
                try:
                    _sb.configure(bg=_p['dim'], troughcolor=_p['card2'],
                                  activebackground=_p['primary'],
                                  highlightbackground=_p['border'],
                                  highlightcolor=_p['border'],
                                  borderwidth=0, relief='flat',
                                  elementborderwidth=0)
                except Exception:       # noqa: BLE001
                    pass
        # ② 工具页签的文本框
        try:
            self.env_txt.configure(bg=_p['logbg'], fg=_p['logfg'])
        except Exception:       # noqa: BLE001
            pass
        # ③ **存图勾选（唯一保留 tk 的勾选）** —— 门禁 T16f 钉着它必须是 tk.Checkbutton ✓
        try:
            if getattr(self, 'save_cb', None) is not None:
                self.save_cb.configure(bg=_p['card'], fg=_p['ok'],
                                       activebackground=_p['card'],
                                       activeforeground=_p['ok'],
                                       selectcolor=_p['primary'],
                                       disabledforeground=_p['off'])
        except Exception:       # noqa: BLE001
            pass
        # ④ 棋盘（tk.Canvas）：色已由 `_paint_theme_consts` 写进 theme ⇒ 重画一次 ✓
        #   ⭐⭐ 2026-10-12 用户：「**深色模式…棋盘那里的边框是白色的**」
        #     ── 根因：`BoardCanvas` 的 **widget `bg`** 只在**构造期**设过一次
        #       （那一刻是浅色 `#FFFFFF`）；切主题时 `_paint_theme_consts` 只改**模块常量**
        #       （画布上的图元用新色 ✓），但**控件自身 bg 没人重设** ✗
        #       ⇒ 画布四周留白（`_BPAD`）仍是**白色** ⇒ 看着像"白色边框" ✗✗
        #     ⇒ 修：切换时把 widget 的 `bg` 也刷成新的 `theme.BOARD_BG` ✓
        try:
            self.board.configure(bg=theme.BOARD_BG)
        except Exception:       # noqa: BLE001
            pass
        try:
            self._update_board()
        except Exception:       # noqa: BLE001
            pass
        # ⑤ 状态灯（StatusDot 是 tk.Frame；`set()` 会按 theme 常量重画 ✓）
        #   ⚠⚠ 顺序很重要：**先给它底色、再 `set()`**
        #     —— `set()` 会 `configure` 子组件 ⇒ ctk 父容器（`bg_color='transparent'`
        #        那类）会**从 master 重新探测底色**，若此刻 StatusDot 还是旧色，
        #        探到的就把 ctk 的 `bg_color` **回写成单值**（切一次之后就不跟主题了 ✗✗
        #        本轮实测：`titlelab.bg_color` 元组 → `'#F0F1F3'` 单值 ⇒ 顶栏那条永远停在浅色）
        #     ⇒ 先 `setbg(新底色)` 把 tk 状态灯换好，再 `set()`（两者都在这一步完成 ✓）
        try:
            self.state.setbg(_p['bg'])
            self.state.set(self.state.cget('text'))
        except Exception:       # noqa: BLE001
            pass

    def _on_theme_pick(self, choice=None):
        """右上角「浅色/深色」分段按钮的回调 —— **运行时切换，不重启**（T6 §0 定稿）✓"""
        try:
            _mode = 'dark' if str(choice).startswith('深') else 'light'
            self._mode = ctk_theme.apply(_mode)
            ctk_theme.save_pref(self._mode)
            self._paint_theme_consts(self._mode)
            self._paint_tk_widgets()
            # ⭐ §7② 治本后：**ctk 控件自己会跟着元组色变**（`set_appearance_mode` 一切全换）✓
            #   ⚠ 所以这里**只需要**：① 写 tk 侧常量（棋盘/日志/StatusDot 用）
            #     ② 重设那几个 tk 控件；③ 同步分段按钮的选中项
            #   —— 旧版那段"遍历 52 处显式给色控件逐个 configure"**已不需要**（元组治本 ✓）
            try:
                if getattr(self, 'themeseg', None) is not None:
                    self.themeseg.set(ctk_theme.label(self._mode))
            except Exception:           # noqa: BLE001
                pass
            self.log('› 主题已切到「%s」' % ctk_theme.label(self._mode))
        except Exception as e:      # noqa: BLE001
            try:
                self.log('⚠ 主题切换失败：%r' % (e,))
            except Exception:       # noqa: BLE001
                pass

    # ══════════════════════════════════════════════════════════════════
    # ② 日志（**只在主线程写** ✓）
    # ══════════════════════════════════════════════════════════════════
    def log(self, s):
        """往日志区打一行（**只许主线程调**）＋ 同时落盘 `gui_console_<日期>.log` ✓

        ⚠⚠ 治 P3：老代码的 `ensure_sidecar` / `scan_screen` 在**工作线程里直接调
          `self.log()`** 去操作 Text 控件（没走 Queue）⇒ tkinter 不是线程安全的 ✗
        ⇒ 现在**所有后台输出**都先 `queue.put`（`services.*` 的 emit / `self.bgq`），
          由主线程 `pump()` 取出来再调本函数 ✓
        ⚠ 建窗过程中（日志框还没创建）也会被调用 ⇒ 容错，别把窗口搞崩
        """
        try:
            line = str(s).rstrip()
        except Exception:       # noqa: BLE001
            return
        if getattr(self, 'txt', None) is None:
            try:
                print(line, flush=True)
            except Exception:       # noqa: BLE001
                pass
            self._log_to_file(line)
            return
        try:
            self.txt.configure(state='normal')
            # ⭐⭐ 2026-10-18 方案 A：**日志里不再出现字面 `**`**
            #   ── 病（实测）：`self.log()`/`_Tip()` 里共 **15 处**带 Markdown 粗体标记，
            #     而日志框是 `ScrolledText`（不认 Markdown）⇒ 屏幕上就是字面的
            #     `**进图首帧**`，等宽字体下非常显眼 ✗
            #   ── 修法：按 `**` 切段，**奇数段用 `strong` tag 加粗**、不插星号
            #     （标记仍在——只是从字面变成了加粗，语义一字不变 ✓）
            #   ⚠ 没有 `**` 的行**走原路径**（一次 split 的代价，不改行为）
            _parts = line.split('**')
            if len(_parts) > 1:
                _tg = self._tag_of(line)
                for _i, _seg in enumerate(_parts):
                    if not _seg:
                        continue
                    if _i % 2:
                        self.txt.insert('end', _seg, ((_tg,) if _tg else ()) + ('strong',))
                    else:
                        self.txt.insert('end', _seg, _tg)
                self.txt.insert('end', '\n', _tg)
            else:
                self.txt.insert('end', line + '\n', self._tag_of(line))
            self.txt.see('end')
            self.txt.configure(state='disabled')
        except Exception:           # noqa: BLE001
            pass
        # ⭐⭐⭐ 2026-10-10 **GUI 自己的日志也落盘**（用户报「勾了宝箱怪却没买」时抓到的坑）
        #   原来 `log()` **只写窗口 Text 控件、一个字都不落盘** ✗ ⇒
        #   「特殊方块勾选」这类**只有 GUI 知道**的事件**只在屏幕上一闪而过** ✗✗
        #   ⇒ 排查"用户说勾了、配置却是 false"时翻遍日志文件一条都找不到 ⇒ 只能靠猜 ✗
        self._log_to_file(line)

    @staticmethod
    def _tag_of(line):
        """按行首给日志着色（返回 tag 名；没有合适的返回空串 ✓）"""
        s = (line or '').lstrip()
        if s.startswith('›'):
            return 'status'
        if s.startswith('✓'):
            return 'ok'
        if s.startswith('⚠'):
            return 'warn'
        if s.startswith('✗') or s.startswith('🛑') or s.startswith('⛔'):
            return 'bad'
        if s.startswith('⏹') or s.startswith('■') or s.startswith('▶') or s.startswith('📊'):
            return 'head'
        return ''
    def _log_to_file(self, s):
        """把一条 GUI 日志追加到当天的控制台日志（**不抛异常、不递归** ✓）"""
        try:
            _p = gui_log_file(self.runs if getattr(self, 'runs', None) else LOG_DIR)
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            with open(_p, 'a', encoding='utf-8') as f:
                f.write('%s %s\n' % (time.strftime('%H:%M:%S'), s))
        except Exception:           # noqa: BLE001
            pass

    # ══════════════════════════════════════════════════════════════════
    # ③ 状态机 / 按钮联动（P6：红装锁存在 ⇒ 主按钮禁用 ✓）
    # ══════════════════════════════════════════════════════════════════
    def set_running(self, run):
        self.run_state = 'running' if run else 'idle'
        # ⚠ T5：`stopbtn` 已换成 `ttk.Button` ⇒ **删掉 `bg=`**（ttk 没有这个选项，
        #   颜色由 `Danger.TButton` 的 `map` 管：disabled 自动变灰 ✓）
        self.stopbtn.configure(text='■ 停止', state='normal' if run else 'disabled')
        self._sync_buttons()

    def _sync_buttons(self):
        """按状态机 + 红装锁决定主按钮能不能点 ✓"""
        running = self.runner.is_running()
        busy = running or self.run_state in ('checking', 'stopping')
        for b in self.btns:
            # ⭐ P6 修法：**红装锁存在时主按钮也禁用**（老代码只改状态字、按钮照样能点 ✗）
            b.configure(state='disabled' if busy else 'normal')
        self.stopbtn.configure(
            state='normal' if running else 'disabled',
            text='正在停止…' if self.run_state == 'stopping' else '■ 停止')

    def _refresh_hot_labels(self):
        """顶栏右上角那一行热更信息（老代码 `whoami()` 里 `root.title()` **覆写**了标题，
        两处标题逻辑不一致 ⇒ P8 ⇒ 现在**标题只由 `_title_text` 管**，热更另占一个标签 ✓）
        """
        try:
            line = self.hot.status_line()
        except Exception:       # noqa: BLE001
            line = ''
        try:
            # ⭐⭐ 2026-10-18 方案 B「顶栏净化」：**顶栏不再显示包路径/补丁号**
            #   ── 病：`包 v1.0 · 补丁=无 · 包目录=D:\MGAS\mapbot_pc` 占 **251px**
            #     （左边标题才 232px）⇒ 日常用不上，长实例名时更挤 ✗
            #   ── 修法：改成**只在「关于 / 更新」页签里完整显示**（见 `_build_tab_about`），
            #     顶栏只留**极简版**：有补丁才说补丁（否则留空 ✓）
            #   ⚠ 不删控件、不改名：`hotlab` 仍存在（其他地方可能引用）
            _short = ''
            try:
                # ⚠ 用 `applied()`（已封装、返回 `''` 表示无补丁），
                #   **不要**直接读 `load_state()`（那个名字不存在 ✗）
                _pid = self.hot.applied() or ''
                if _pid:
                    _short = '补丁 ' + _pid.split('-')[-1][:8]
            except Exception:       # noqa: BLE001
                _short = ''
            self.hotlab.configure(text=_short)
            # ⭐ 方案 B：**完整的版本/补丁/包目录下沉到「关于 / 更新」页签**
            #   ── 那份完整信息 `_refresh_about()` **本来就有**（版本/热更状态/补丁/
            #     启动次数/回滚/包目录 6 行）⇒ **直接调它**，不另写一份 ✗
            #   ⚠⚠ **必须容错**：`_refresh_hot_labels()` 在 `_build_topbar` 里就被调
            #     （L690），而「关于」页签要到 `_build_tabs` 才建 ⇒ 那时
            #     `about_var` **还不存在** ⇒ 不能硬调（否则建窗就崩 ✗）
            if getattr(self, 'about_var', None) is not None:
                self._refresh_about()
        except Exception:       # noqa: BLE001
            pass

    # ══════════════════════════════════════════════════════════════════
    # ④ 三条轮询
    # ══════════════════════════════════════════════════════════════════
    def pump(self):
        """进程泵（120ms）：子进程行 / 设备事件 / 杂项后台输出 —— **全在这里进 UI** ✓"""
        try:
            for kind, payload in self.runner.drain():
                if kind == 'line':
                    self.log(payload)
                    self._feed_line(payload)
                    # ⭐ 状态句：子进程 stdout 里带 `› ` 前缀的行（`explore_loop.status()` ✓）
                    _s = str(payload or '').strip()
                    if _s.startswith('›'):
                        self._last_status_line = _s
                        try:
                            self.line_var.set(_s)
                        except Exception:       # noqa: BLE001
                            pass
                elif kind == 'exit':
                    self.log('■ 任务结束')
                    self.set_running(False)
                    self.show_summary()
                    # ⛔ 2026-10-12 删掉 `self._refresh_lock_card()`（锁机制已删 ✓）
            for ev in self.dev.drain():
                self._on_dev_event(ev)
            while True:
                try:
                    item = self.bgq.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, tuple) and item and item[0] == 'done':
                    self._refresh_about()
                else:
                    self.log(item)
        except Exception:           # noqa: BLE001  （泵不许把主循环搞死）
            pass
        try:
            self.root.after(120, self.pump)
        except Exception:           # noqa: BLE001
            pass

    def _feed_line(self, s):
        """从子进程 stdout 里捡**实时**信息（规划 / 进度 / 本图结束）—— 见 `_RE_PLAN` 注释

        ⛔ 为什么必须有这条通道：`loop_log.json` **每张图结束才 flush**（数据源限制），
          只靠它 ⇒ 用户看到的是「**执行完了才出执行图**」✗（2026-10-11 反馈原话）
        ⇒ 这里捡**规划那一行**（含全序、上限 10 步）⇒ 规划一算出来就画执行图 ✓

        ⭐⭐⭐ 2026-10-12 用户口径（原话）：「**实时棋盘只显示首帧的规划，不要继续显示
          执行完所以步数的了**」
          ── 病 ──
            子进程**每轮都重算一次规划**（`精确规划` 那行会反复打）⇒ 每来一行就
            `_paint_plan()` ⇒ 棋盘序号**跟着一轮一换**：刚点完的步消失了、又冒出新的，
            看着像"执行完的步数被继续显示/不停变" ✗
          ── 修法：**每张图只认第一条规划**（= 首帧规划）──
            · `self._plan_frozen`（本图的**首帧计划**）一旦定下 ⇒ **后续规划行不再覆盖**
            · 直到「本图结束」/新一局开始 ⇒ 解冻，下一张图重新认第一条 ✓
          ⚠ 与"实时"不矛盾：**还是规划一算出来就上屏**（首帧那条就是实时的 ✓），
            只是**不再被后续重算顶掉** ✓
          ⚠ 进度行（`[rN] …`）**照旧实时更新**（用户要冻的是**执行图/序号**，不是进度 ✓）
        """
        t = str(s or '').strip()
        if not t:
            return
        try:
            m = _RE_PLAN.search(t)
            if m:
                order = ['%d,%d' % (int(a), int(b))
                         for a, b in _RE_CELL.findall(m.group(3))]
                # ⭐⭐ 2026-10-12 用户：「**步数线条要和实时棋盘一起出**」
                #   ── 错拍根因 ──
                #     stdout 规划行 120ms 泵一拍就到；`loop_log` 的**整盘快照**
                #     却要等 2 秒一拍的 `tick_data` 才被 poll ⇒
                #     规划行到达那一刻 `_board_frozen` 还没建 ⇒ 那一拍画的是
                #     **旧图/空图 + 序号**，图要等下一拍才补 ⇒ "图和线分家" ✗
                #   ⇒ 修法：规划行一到，**立刻 poll 一次数据源**（读文件几十 ms）
                #     ⇒ 整盘快照 + 序号 + 箭头**同一帧**一起上屏 ✓
                try:
                    self.looplog.poll()
                except Exception:           # noqa: BLE001
                    pass
                order = ['%d,%d' % (int(a), int(b))
                         for a, b in _RE_CELL.findall(m.group(3))]
                _lp = {'order': order, 'steps': int(m.group(2)),
                       'cost': self._num(m.group(1)), 'src': 'stdout'}
                # ⭐⭐ 2026-10-12 用户：「**线路标记也要和实时棋盘一样，换图才更新**」
                #   ＋「**步数线条生成速度有点慢了，要和实时棋盘一起出**」
                #   ⇒ 规划行一到，**立刻 poll 数据源**（把同批落盘的整盘快照拉进来），
                #     再把这条计划**补进本图快照** ⇒ 图 + 序号圆 + 箭头**同帧齐出** ✓
                #   ⚠ 若本图快照里**已经有**计划（= 已锁首帧）⇒ 后续重算**不上屏**
                #     （用户口径：线路标记换图才换 ✓）
                try:
                    self.looplog.poll()
                except Exception:           # noqa: BLE001
                    pass
                _snap = getattr(self, '_board_frozen', None)
                if _snap is not None:
                    if not (_snap.get('plan_full') or {}).get('order'):
                        # 本图快照还没锁计划 ⇒ 这条就是**首帧计划**，补进去 ✓
                        self._board_frozen['plan_full'] = dict(_lp)
                        self._plan_frozen = True
                        self._paint_plan()
                        self.log('› 规划（首帧·%d 步）→ %s'
                                 % (len(order), '→'.join(order[:8])
                                    or '（只点出生点）'))
                    else:
                        self.log('› 规划（重算·%d 步，本图已锁首帧 ⇒ 不上屏）'
                                 % len(order))
                    return
                # （快照还没建 ⇒ 先显示这条，等快照一建立就会被它补锁 ✓）
                self._live_plan = _lp
                self._plan_frozen = True
                self._paint_plan()
                self.log('› 规划（实时·首帧）：%d 步 → %s'
                         % (len(order), '→'.join(order[:8]) or '（只点出生点）'))
                return
            if _RE_ROUND_LINE.match(t):
                self._round_line = t
                try:
                    self.prog_var.set('进度：' + t)
                except Exception:       # noqa: BLE001
                    pass
                return
            if t.startswith('本图结束'):
                self._last_map_line = t
                # ⭐⭐ 「本图结束」⇒ **解冻**：计划解冻 + **整幅棋盘快照清掉** ⇒
                #   下一张图会重新认**它的**首帧（用户口径是"每张图冻首帧"，
                #   不是"整个脚本只画一次" ✓）
                self._plan_frozen = False
                self._board_frozen = None
                self._live_plan = None          # 上一图的序号不该带到下一图 ✗
                try:
                    self.prog_var.set('进度：—（%s）' % t)
                except Exception:       # noqa: BLE001
                    pass
        except Exception:       # noqa: BLE001  （捡信息绝不能把泵搞死）
            pass

    def _plan_chips(self, order=None, cost=None, board=None):
        """⭐ 2026-10-18 方案 C：把计划画成**步骤胶囊**（序号圆 + 格名）

        ── 为什么
          原来只有一行 mono 长串：`计划：cost=13 ｜ 5 步（首帧） ｜ 1,7→3,5→…`
          ⇒ 用户要在脑子里把 `1,7` 对回「阴暗古墓」才知道去哪几格 ✗
          而坐标与格名的对应关系 **`looplog.last_board` 里本来就有**
          （`{"1,7": [sid, 格名, score, ratio]}）⇒ 零新数据源 ✓

        ── 为什么和棋盘序号同款
          棋盘上的计划圈也是 1,2,3… ⇒ 两处**同一套视觉语言**，
          一眼就能对上「第 3 步去哪」（用户 2026-10-11 要的“执行图”延伸 ✓）

        ⚠ 任何坏数据都**不抛**（GUI 跑在 pythonw 无控制台 ✗）
        ⚠ `order` 空 ⇒ **整块隐藏**（不留一排空壳占高度 ✗）
        """
        try:
            wrap = getattr(self, 'chipwrap', None)
            if wrap is None:
                return
            for _c in wrap.winfo_children():
                _c.destroy()
            _ord = [str(x) for x in (order or []) if str(x or '').strip()]
            if not _ord:
                wrap.pack_forget()
                return
            wrap.pack(fill='x', padx=theme.PAD_CARD, pady=(3, 0), after=self.plan_lab)
            _p = ctk_theme.palette()
            _bd = board or {}
            # 首格先算一个总说明（cost / 步数）
            _meta = ('cost %s · %d 步'
                     % (cost if cost not in (None, '') else '—', len(_ord)))
            ctk.CTkLabel(wrap, text=_meta, text_color=_p['dim'], height=17,
                         anchor='w', font=ctk_theme.font(ctk_theme.FS_HINT)
                         ).pack(side='left', padx=(0, 8))
            for _i, _cell in enumerate(_ord):
                _rec = _bd.get(_cell) or []
                _nm = str(_rec[1]) if len(_rec) > 1 else _cell
                _short = _nm if len(_nm) <= 4 else _nm[:3] + '…'
                _chip = ctk.CTkFrame(wrap, fg_color=_p['card2'], corner_radius=7,
                                     border_width=1, border_color=_p['border'])
                _chip.pack(side='left', padx=(0, 5))
                ctk.CTkLabel(_chip, text=str(_i + 1), width=17, height=17,
                             corner_radius=9, fg_color=_p['primary_btn'],
                             text_color='#FFFFFF',
                             font=ctk_theme.font(ctk_theme.FS_HINT)
                             ).pack(side='left', padx=(4, 0), pady=3)
                ctk.CTkLabel(_chip, text=_short, height=17,
                             text_color=_p['text'],
                             font=ctk_theme.font(ctk_theme.FS_SUB)
                             ).pack(side='left', padx=(4, 7))
                # 悬浮提示给完整格名 + 坐标（字被截了也能看到 ✓）
                try:
                    _Tip(_chip, '%d. %s（%s）' % (_i + 1, _nm, _cell))
                except Exception:       # noqa: BLE001
                    pass
        except Exception:           # noqa: BLE001
            pass
    def _paint_plan(self):
        """把当前计划刷进「计划」行 + 棋盘序号（**只重画棋盘，不重读文件** ✓）"""
        try:
            self._update_board()
        except Exception as e:      # noqa: BLE001
            try:
                self.log('（计划上屏失败：%r）' % (e,))
            except Exception:       # noqa: BLE001
                pass

    def _on_dev_event(self, ev):
        """消费 `DeviceService` 的事件（**纯数据 ⇒ 在这里才碰界面** ✓）"""
        try:
            kind = ev[0]
        except Exception:           # noqa: BLE001
            return
        if kind == 'log':
            self.log(ev[1])
        elif kind == 'devlabel':
            try:
                self.devlab.configure(text=ev[1])
            except Exception:       # noqa: BLE001
                pass
        elif kind == 'instances':
            self.log(ev[1])
        elif kind == 'env_rows':
            self._show_env_rows(ev[1], ev[2])
        elif kind == 'env_done':
            self.log('✓ 环境检查通过' if ev[1] else '✗ 环境检查未通过 ⇒ 不启动')
            pend = self._pending or {}
            if pend.get('phase') == 'env':
                if ev[1]:
                    pend['phase'] = 'dup'
                    self.dev.duplicates_async(self.device, self.tag)
                else:
                    self._pending = None
                    self.run_state = 'idle'
                    self._sync_buttons()
        elif kind == 'dups':
            self._on_dups(ev[1])
        elif kind == 'loops':
            self._show_loops(ev[1])
        elif kind == 'loops_killed':
            self.log('✓ 已停掉 %d 个循环：%s' % (len(ev[1]), ev[1]))
        elif kind == 'scan':
            pass                    # 细节已经逐行 log 过了
        elif kind == 'recruit_now':
            # ⭐⭐ 2026-10-14「立即招募」跑完了（**回到主线程才碰界面** ✓）
            self._recruit_running = False
            self._sync_recruit_btn()
            if ev[1]:
                self.log('✓ 立即招募完成（细节见上面几行；'
                         '抽到什么看游戏里的「恭喜获得」）')
            else:
                self.log('⚠ 立即招募没成功（原因见上面几行）'
                         '—— 常见：今天免费机会已用掉 / 不在大厅 / 标签面板没开 ✓')
        elif kind == 'multi_fail':
            self._show_multi_fail(ev[1])
        elif kind == 'multi_open':
            self._open_multi(ev[1], ev[2], ev[3])

    def tick(self):
        """1s：状态灯 + 按钮联动（**两源**：`stats.running` / `.loop` 锁 ✓）
        
        ⛔ 2026-10-12：原来还有第 3 源「红装锁」（`_refresh_lock_card`）—— 整套锁定机制已按用户要求删除 ✓
        （用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」）
        """
        try:
            # ⛔ 2026-10-12 删掉 `_refresh_lock_card()`（锁机制已删 ✓）
            running = self.runner.is_running()
            if self.run_state == 'stopping':
                kind, text = 'warn', '正在停止…'
            elif self.run_state == 'checking':
                kind, text = 'run', '准备中…'
            # ⛔ 2026-10-12 删掉 `elif self._locked:`（锁机制已删 ✓）
            elif running or self.locks.is_running():
                kind, text = 'run', '运行中…'
            else:
                kind, text = 'ok', '就绪'
            self.state.set(text, kind)      # ⚠ 老接口 `configure(text=…, fg=…)` 也支持 ✓
            self._sync_buttons()
        except Exception:       # noqa: BLE001
            pass
        try:
            self.root.after(1000, self.tick)
        except Exception:       # noqa: BLE001
            pass

    def tick_data(self):
        """2s：轮询 `last_summary.json` + `loop_log.json` ⇒ 刷新仪表盘 / 曲线 / 柱状 / 棋盘 / HUD ✓

        ⚠ 老 UI 的"日志倒灌"（P4）：统计跑完**打进日志流**、滚过去就没了 ✗
          ⇒ 现在**固化在仪表盘**上（本窗口生命周期内累积，关窗清零 —— 用户口径 T11 ✓）

        ⭐ 数据读取失败时的口径（T12 容错 + 不骗人）：
          · 数值**保持上一次的好值**（`last_summary.json` / `loop_log.json` 都是
            **整体覆写**，2 秒一拍的轮询**必然**会撞上"文件刚被截断"的瞬间
            ⇒ 若这时清成「—」，面板会每张图都闪一下 ✗）
          · 但**要吭一声**（只吭一次，不刷屏）：`_stale_warned` ⇒ 让"数是陈的"这件事
            在日志里留痕，而不是**静默显示旧数**（本项目最怕的就是静默 ✗）
          · 从没读到过（新窗口/文件压根不存在）⇒ `stats` 为空 ⇒ 面板显示「—」✓
        """
        try:
            self.summary.poll()
            self.looplog.poll()
            _err = (getattr(self.summary, 'last_error', '')
                    or getattr(self.looplog, 'last_error', ''))
            if _err and not getattr(self, '_stale_warned', False):
                self._stale_warned = True
                self.log('⚠ 数据面板：最近一次读取失败（%s…）⇒ 先显示**上一次的好值**'
                         '（数据文件是整体覆写，轮询撞上半截属正常；读到新的会自动恢复 ✓）'
                         % str(_err)[:70])
            elif not _err:
                self._stale_warned = False
            st = self.summary.stats or {}
            self._update_dashboard(st)
            self._update_board()
        except Exception as e:      # noqa: BLE001
            try:
                self.log('（面板刷新失败：%r）' % (e,))
            except Exception:       # noqa: BLE001
                pass
        try:
            self.root.after(2000, self.tick_data)
        except Exception:       # noqa: BLE001
            pass

    # ---------- 仪表盘 ----------
    @staticmethod
    def _num(v, default=None):
        try:
            f = float(v)
            return f
        except Exception:       # noqa: BLE001
            return default

    def _update_dashboard(self, st):
        st = st or {}
        ent = st.get('stamina_entries') if isinstance(st.get('stamina_entries'), list) else []
        first = self._num(ent[0][0]) if ent and isinstance(ent[0], (list, tuple)) and ent[0] else None
        last = self._num(ent[-1][0]) if ent and isinstance(ent[-1], (list, tuple)) and ent[-1] else None
        # ⭐⭐⭐⭐ 2026-10-16 **修「均耗 20.2 < 25」**（用户报：「acc1 最近一波为什么
        #   均耗能到 20.2？进图不就消耗 25 了」）
        #   ---- 病根：这里原来用 **(首 − 末) / 图数**，它有个致命假设：
        #        「整局中间**没人补过体力**」✗
        #        实测真机 `runs/acc1/last_summary.json` 的 `stamina_entries`：
        #          ...146, 99, 66, 35, | **544, 545**, | 513, 484, ...
        #                              ↑ 补给回升 +509
        #        该局总回升 **514** 点 ÷ 70 图 = **低估 7.3**
        #        ⇒ 真值 32.1 被算成 **24.8**；用户看到 20.2 的那次回升更多 ✓
        #        ⭐ **算术铁证**：进图固定扣 25 ⇒ 均耗**不可能 < 25** ✓
        #   ---- ⛔ 更不能"首末之外再挑挑捡捡"----
        #        序列里还混过**两次运行**（中途停过又开）：
        #          `vals[52]=99 → vals[53]=66 → vals[54]=35`，中间跳到 544/545
        #        ⇒ 任何"跨整局"的算法都会被它污染 ✗
        #   ---- ✅ 修法：**复用 `explore_loop.stamina_line()`**（单一数据源 ✓）
        #        它**早就**是正确的：**逐段**相减 + 按「30 秒回 1 点」补偿，
        #        且**每段夹 ≥0**（中途大额补充不冲抵别的段 ✓）
        #        ⇒ 与 `summary_text()` 末尾那份统计**同一个数**（不再两处打架 ✓）
        #        ⇒ 实测该局会显示 **32.1**（不再 24.8 / 20.2）✓
        #   ⚠ 为什么**不在这里另写一套**：本项目的老毛病就是"同一件事两处各算一遍"
        #     ⇒ 必然分叉（这次就是分叉出来的 bug ✓）
        spent, _how, _parts = self._stamina_spent(ent)
        if first is not None and last is not None:
            # ⛔⛔ **不许**用 `first - last` 兜底（那是被补给污染的错数 ✗）
            #   拿不到段数就**如实说**，别编一个不可能的数出来 ✓
            self.card_stamina.set(
                '%d→%d' % (first, last),
                sub=('%.0f 点已消耗' % spent) if spent is not None
                else '读数不足')
        else:
            self.card_stamina.set('—', sub='等进图')
        maps = int(self._num(st.get('maps'), 0) or 0)
        secs = st.get('map_secs') if isinstance(st.get('map_secs'), list) else []
        total = sum(x for x in (self._num(v) for v in secs) if x) if secs else 0.0
        if maps:
            self.card_maps.set('%d 张' % maps, sub='%.0f 秒' % total)
        else:
            self.card_maps.set('—', sub='本次累计')
        bf, bw = int(self._num(st.get('boss_fights'), 0) or 0), \
            int(self._num(st.get('boss_wins'), 0) or 0)
        tf, tw = int(self._num(st.get('battles'), 0) or 0), \
            int(self._num(st.get('battle_wins'), 0) or 0)
        if bf or tf:
            # ⚠ 一行 9 张卡 ⇒ 每张只有 ~113px 宽：**大数值必须是短串**
            #   （'首领 24/24' 在 16pt 下约 105px ⇒ 会换行顶高整行 ✗）
            #   ⇒ 主数值给首领战绩、战斗战绩挪到副标题；完整口径见 tooltip ✓
            self.card_win.set('%d/%d' % (bw, bf), sub='战斗 %d/%d' % (tw, tf))
            _Tip(self.card_win, '首领关：%d 胜 / %d 场\n全部战斗：%d 胜 / %d 场' % (bw, bf, tw, tf))
        else:
            self.card_win.set('—', sub='还没有战斗')
        # ⭐⭐⭐⭐ 修：均耗 = **逐段相减的平均**（不再首末相减 ⇒ 补给不影响 ✓）
        #   ⚠ 分母用 **`_parts` 的长度**（= **有效**段数），**不是** `maps`、
        #     也**不是** `len(ent) - 1` ✗
        #     ---- 为什么 ----
        #       `_stamina_spent()` 会**剔掉异常段**（> `_SEG_MAX`，见其注释）⇒
        #       `len(ent)-1` 是**原始**段数，`len(_parts)` 才是**参与求和**的段数。
        #       ⛔ 我曾经用 `len(ent)-1` 当分母 ⇒ 夹具上算成 **17.9**（< 25，又错了 ✗）
        #       ⇒ **分子分母必须同源**（都来自 `_parts`）✓
        #     ---- 正常一局 ----
        #       进图前各记 1 条 + 收尾 1 条 ⇒ 有效段数 = maps ✓
        #     ⚠ 中途停过再开 ⇒ 段数 ≠ maps；用户要的是"**实际测到的那些段的平均**"
        #       ⇒ 用有效段数才自洽 ✓
        _nseg = len(_parts) if _parts else 0
        if spent is not None and _nseg:
            self.card_avg.set('%.1f' % (spent / _nseg), sub='点/张')
            _Tip(self.card_avg,
                 '平均每图消耗 %.1f 点（按 %d 段实测）\n'
                 '算法：**逐段**（进图体力差 + 30 秒回 1 点补偿）再取平均\n'
                 '⛔ 不用「首末相减」—— 中途用补给回体会把均耗算低 ✗\n'
                 '进图固定 25 点，**均耗不可能低于 25** ✓' % (spent / _nseg, _nseg))
        elif maps and first is not None and last is not None:
            # ⛔⛔ **不许**用 `(first - last) / maps` 兜底 ——
            #   它正是**这个 bug 的老写法**（补给一补就 < 25，算术上不可能 ✗）
            #   ⇒ 拿不到段数时**宁可显示 —**（用户口径：别给错数 ✗）
            self.card_avg.set('—', sub='等第二次进图')
        else:
            self.card_avg.set('—', sub='点/张')
        # ⭐⭐⭐ 2026-10-16 **后半段必须在这里调用** ——
        #   ⛔ 我本轮插 `_stamina_spent` 时把它挤到了 `return` 之后 ⇒ 死代码 ✗
        #     （5 张卡全不更新，`_selftest_ui` ⑧ 项红当场抓到 ✓）
        #   ⇒ 抽成独立方法 + **显式调用**（函数边界清楚，再插代码也不会误伤 ✓）
        self._update_dashboard_tail(st, maps, secs, first, last)

    # ⭐ 单段消耗的**上限**：一图最多 25（进图）+ 图内消耗。
    #   ⚠ 实测一图 27~47 点（进图 25 + 探索/战斗 2~22）⇒ 取 **60** 留足余量 ✓
    #   ⛔ 超过它说明那一段**不是"两次进图之间"** —— 最典型的是**收尾那条**：
    #      `explore_loop` 收工时会再读一次体力（`run()` 末尾的"收尾体力"），
    #      而那时可能已经**手动停过/用了补给/换了局** ⇒ 它与前一条之间
    #      **不是"一张图的消耗"** ✗
    #      实测（`_selftest_ui` 的夹具，真机同形）：`[785, 760, 735, **34**]`
    #      ⇒ `735 → 34 = 701` 被当成一段 ⇒ 均耗算成 **252.1**（荒谬 ✗）
    _SEG_MAX = 60.0

    def _stamina_spent(self, ent):
        """复用 `explore_loop.stamina_line()` 的口径算**总消耗** ⇒ `(spent, how, parts)`

        ⭐ 不在这里另写一套（本项目的老毛病："同一件事两处各算一遍" ⇒ 必然分叉 ✗，
          这次的均耗 bug 就是分叉出来的 ✓）
        ⚠ `stamina_line()` 读的是 `explore_loop.STATS`（模块级全局）——
          本函数跑在**同一个进程**里吗？**不是**！GUI 是**另一个进程**，
          它通过 `last_summary.json` 拿 `stats` ✗
        ⇒ 所以这里**不能**直接调它（会把 GUI 自己那份**空** STATS 算成 None ✗）
        ⇒ 做法：把 `stamina_line()` 的**同一套公式**作用在**传进来的 ent** 上 ✓
          （公式逐字同源，见 `explore_loop.stamina_line()` ✓）

        ⭐⭐ 2026-10-16 加**单段上限**（`_SEG_MAX`）—— 见其注释：
          收尾那条读数与前一条之间**不是**"一张图的消耗"，
          不过滤会把均耗算成 252 那种荒谬值 ✗（夹具当场抓出来的 ✓）
        ⚠ 只**剔除异常段**，不整条丢掉（其余段仍然有效 ✓）
        """
        if not isinstance(ent, list) or len(ent) < 2:
            return (None, '段数不足', [])
        total = 0.0
        parts = []
        skipped = 0
        for i in range(len(ent) - 1):
            try:
                s0, t0 = float(ent[i][0]), float(ent[i][1])
                s1, t1 = float(ent[i + 1][0]), float(ent[i + 1][1])
            except Exception:       # noqa: BLE001
                continue
            dt = max(0.0, t1 - t0)
            regen = dt / 30.0                     # 游戏 30 秒回 1 点
            spent = max(0.0, (s0 - s1) + regen)   # 每段夹 ≥0（补充不冲抵别段 ✓）
            # ⛔ 单段超上限 ⇒ 这一条**不是进图读数**（多半是收尾/换局）⇒ 跳过 ✓
            if spent > self._SEG_MAX:
                skipped += 1
                continue
            total += spent
            parts.append('%d→%d(-%d +回%.0f)' % (s0, s1, max(0, s0 - s1), regen))
        if not parts:
            return (None, '没有可用段', [])
        _how = '逐段相减 + 30 秒/点补偿'
        if skipped:
            _how += '（剔除 %d 段异常读数）' % skipped
        return (total, _how, parts)

    def _update_dashboard_tail(self, st, maps, secs, first=None, last=None):
        """`_update_dashboard` 的**后半段**（平均耗时卡 + 四张次数卡 + HUD + 顶栏摘要）

        ⛔⛔ 2026-10-16 **我把它从"死代码"里救回来**（诚实记账）：
          本轮我往 `_update_dashboard` 里插 `_stamina_spent` 时，**没注意函数边界**，
          把后半段挤到了 `return` **之后** ⇒ 那几段**永远不执行** ✗✗
          症状（`_selftest_ui.py` 当场抓到 **5 项红**）：
            `④b 大拇指格` / `④c 幸运草格` / `④d 买完商人` / `④e 买完宝库` / `⑤ 平均耗时`
            —— 全是这几张卡，**一个都没被 set** ⇒ 值停在初始的 `—` ✓
          ⇒ 教训：**在长函数中间插代码后，一定要看"后面还在不在函数体里"** ✓
            （本项目同族教训：v1.62「veto 位置」、v1.66「收口位置」都是"代码位置"问题 ✓）

        ⚠ `first`/`last` 要**从调用方传进来**（它们是在前半段算的，本函数不该重算 ✓）
        """
        try:
            _secs = [x for x in (self._num(v) for v in secs) if x]
            _avg_s = (sum(_secs) / len(_secs)) if _secs else None
            self.card_avgtime.set(('%.1f' % _avg_s) if _avg_s is not None else '—',
                                  sub=('秒/张 · %d 张' % maps) if maps else '秒/张')
        except Exception:       # noqa: BLE001
            pass
        # ⭐⭐⭐ 2026-10-12 用户：「**仪表盘多加几个数据就行，比如大拇指格次数，
        #   幸运草格次数，买完的商人次数，黄金宝库次数**」
        #   ＋ 2026-10-12 追加：「**大拇指格子下面可以放拿到几件装备，九个就行**」
        #     ⇒ **共 9 张卡**（第 2 行 4 张）；大拇指格那卡的副标题 = 「胜 N ｜ 装备 M 件」
        #       （`recommend_wins` + `dice_got`，不再单开"摇到装备"卡 ✓）
        #   口径：一律 `int`；**读不到 ⇒ 「—」**（不拿 0 冒充"真没打过"）✓
        for _card, _key, _sub in (
                (self.card_recommend, 'recommend_fights', None),   # 副标题见上（胜/装备）
                (self.card_clover, 'clovers', '打过的次数'),
                (self.card_merchant, 'merchants', '旅行商人'),
                (self.card_vault, 'vaults', '黄金宝库')):
            try:
                _v = self._num((st or {}).get(_key))
                if _v is None:
                    _card.set('—', sub='')
                    continue
                if _sub is None:
                    # ⭐ 用户：「大拇指格子下面可以放拿到几件装备」
                    #   ⇒ 副标题 = 「胜N·装备M件」（`dice_got` = 摇到的大拇指装备件数）
                    #   ⚠ 一行 9 张卡 ⇒ 副标题也要短（10pt 文字在 113px 卡里会换行 ✗）
                    _w = self._num((st or {}).get('recommend_wins'))
                    _dg = self._num((st or {}).get('dice_got'))
                    _bits = []
                    if _w is not None:
                        _bits.append('胜%d' % int(_w))
                    if _dg is not None:
                        _bits.append('装备%d件' % int(_dg))
                    _sub = '·'.join(_bits)
                _card.set('%d' % int(_v), sub=_sub)
            except Exception:       # noqa: BLE001
                _card.set('—', sub='')
        # ⭐ HUD 读数（loop_log 的 round 事件：体力/金币/幸运草/空闲槽 ✓）
        hud = self.looplog.hud or {}
        self.hud_var.set('体力 %s ｜ 金币 %s ｜ 幸运草 %s ｜ 空闲槽 %s'
                         % (self._fmt_int(hud.get('stamina')),
                            self._fmt_int(hud.get('gold')),
                            self._fmt_int(hud.get('clover')),
                            self._fmt_int(hud.get('slots_free'))))
        # ⭐⭐ 2026-10-13 P1-a（工单 07 §2 第 4 条）：顶栏「运行摘要」
        #   ⚠ `first`/`last`/`maps` 在上面**都已经算好** ⇒ 零新计算、零新数据源 ✓
        try:
            self.sumlab.configure(text=self._run_summary_text(first, last, maps))
        except Exception:       # noqa: BLE001
            pass

    def _run_summary_text(self, first, last, maps):
        """顶栏运行摘要串：`第 3 张 · 体力 785→34`（拿不到就退化，**绝不抛/不空白** ✓）

        ⭐ 2026-10-13 P1-a（工单 07 §2）。拼串口径**照抄工单，别自由发挥**：
          · 「第 N 张」优先取自 `self._last_status_line`（子进程 stdout 的
            `› 第 N 张图 · …` 状态行，`pump()` 里已经在捡 ✓）
          · 没有状态行 ⇒ 退化成 **短式** `N 张`（⚠ **不带「本次」二字**）——
            工单实测宽度预算：带「本次」= 157px，而顶栏只剩 ≈150px ⇒ **会被 Tk 静默裁字** ✗
            短式 = 127px ✓ 放得下（1100px 定宽窗口，不许改窗口 ✗）
          · 体力取 `stamina_entries` 首末（`a→b`）✓
        ⚠ 任何异常 ⇒ 返回 `''`（那是"还没数据"，不是报错；pythonw 无控制台，抛了用户看不见 ✗）
        """
        try:
            parts = []
            m = _RE_MAPIDX.search(str(getattr(self, '_last_status_line', '') or ''))
            if m:
                parts.append('第 %d 张' % int(m.group(1)))
            elif maps:
                parts.append('%d 张' % int(maps))       # 短式：省掉「本次」二字 ✓
            if first is not None and last is not None:
                parts.append('体力 %d→%d' % (int(first), int(last)))
            return ' · '.join(parts)
        except Exception:       # noqa: BLE001
            return ''

    @staticmethod
    def _fmt_int(v):
        n = App._num(v)
        if n is None:
            return '—'
        try:
            return '{:,}'.format(int(n))
        except Exception:       # noqa: BLE001
            return '—'

    def _update_board(self):
        """实时棋盘：格名/雾格取 `loop_log` 尾部**最新带 `board` 的事件**（附录 E.2）✓

        ⭐⭐⭐ 2026-10-11 三处按真机反馈修（用户原话见下）：
          ① 「**真机都要执行完了才出执行图**」⇒ 计划改走**实时通道**：优先
             `self._live_plan`（从子进程 stdout 捡的"精确规划"行，含**全序**）✓
          ② 「**规划了 5 步只显示了 4 步**」⇒ 原来取 round 事件的 `solver_order`，
             而它**只记本轮要点的前 4 步**（`explore_loop` 硬编码 `len(_picked) >= 4`）
             ⇒ 改成优先 `plan_full`（**solver 事件**里的完整计划，上限 10 步）✓
          ③ 「**不能正常显示多格地块**」⇒ `board` 只给**锚点格**（成员格被
             `if v['anchor'] == k` 过滤掉了）⇒ 用 `spots.Board.footprint(sid)`
             把锚点**展开成整块**传 `spans` 给画布，2×2 就会画成一整块 ✓

        ⭐⭐⭐ 2026-10-12 用户口径（原话）：「**怎么一张图内的实时棋盘效果还是在一直变，
          在首帧那里就不要动了**」
          ── 病（上一版只冻了「计划」，**没冻图本身**）──
            `tick_data()` 每 2 秒调本函数一次 ⇒ 每次都重读 `loop_log` 的
            `last_board`/`last_marks` ⇒ 一张图内格子**会一轮一轮地被揭示、标记也会增删**
            ⇒ 棋盘**整幅一直在变** ✗（用户要的是"首帧那张图冻住"✓）
          ── 修法：**整幅快照冻结**（`self._board_frozen`）──
            · 本图第一次拿到"**有内容的**"棋盘时 ⇒ 连 `board/marks/hud/order/spans`
              **一起快照**下来，之后 `tick_data` 的重复调用**直接复用快照**、不再重读 ✗
            · 「本图结束」⇒ 解冻（下一张图会重新取它的首帧 ✓）
            · `_paint_plan()`（stdout 实时通道）**也要尊重快照**：它只更新"计划"，
              图的其余部分仍用快照 ✓
          ⚠ 为什么快照要包含 `hud`：首帧标题行（体力/金币/幸运草）与图**同一时刻**拍下，
            否则图冻住了、标题行却每 2 秒跳一次 ⇒ 看着仍在变 ✗
          ⚠ 空数据（还没进图）**不冻**：否则"等进图"那一帧会被冻成永久空白 ✗
        """
        board = self.looplog.last_board
        marks = self.looplog.last_marks or {}
        # ---- ⭐⭐ 换图兜底解冻（**不能只靠 `本图结束` 那行 stdout** ✗）----
        #   ⚠⚠ 为什么必须加这一道：`本图结束` 是 `say()` 打的，而 `say()` 只在
        #     `VERBOSE` 为真时才 `print`（`explore_loop.py:12000`: `VERBOSE = not a.quiet`）
        #     ⇒ 万一将来加了 `--quiet`（或这行被改掉），**解冻永远不触发**
        #       ⇒ 棋盘会**永远冻在第一张图** ✗✗（用户要的是"每张图各一张"，不是只画一次）
        #   ⇒ 用**图名**当第二把钥匙：`mapname` 变了 ⇒ 一定是新的一张图 ⇒ 解冻 ✓
        #     （图名来自 `loop_log` 的 `mapname` 事件，与跑图同源、不依赖 stdout ✓）
        try:
            _mn_now = getattr(self.looplog, 'mapname', '') or ''
        except Exception:               # noqa: BLE001
            _mn_now = ''
        # ⭐⭐ 2026-10-13 P1-b（工单 07 §3 第 3 条）：图名上标题行
        #   ⚠ **复用已有的 `_mn_now`**，别再读一次 property ✗；读不到 ⇒ 显示 `—`（**不许留空**）
        #   ⛔ 图名就是图名：`mapname` 事件里**只有这一个字符串** ⇒
        #     **不要**顺手拼 `d220`/难度/图码（那些不在这个事件里，硬拼 = 假信息 ✗）
        try:
            self.maplab.configure(text=(_mn_now or '—'))
        except Exception:               # noqa: BLE001
            pass
        _mn_prev = getattr(self, '_board_mapname', '')
        # ⚠⚠ 光靠"图名变了"**不够**：连着刷到**同一张图名**两遍（真机很常见）时，
        #   第二遍图名与第一遍相同 ⇒ 不会解冻 ⇒ 棋盘会**沿用上一张图的盘** ✗
        #   ⇒ 再加**快照身份**：`board_snapshot` 每条都带 `mapname` + 整盘 board；
        #     用 `(mapname, 排序后的格坐标集合)` 当**布局指纹** ✓
        # ⛔⛔ **绝不能用 `id(事件)` 当身份**（第一稿那么写，错的）：
        #   `poll()` 在 mtime/size 一变就**重新 json 解析** ⇒ 每个 dict 都是**新对象**
        #   ⇒ 每 2 秒都被判成"换图" ⇒ **冻结彻底失效** ✗✗
        #   （实测：mtime 变后重解析 ⇒ `a is c` 为 `False`、而 `a == c` 为 `True`）
        # ⛔ 也**别用 `snap_round`**（每图恒为 0）或**格数**（不同图很容易撞上，实测两张都是 1 格）
        #   ⇒ 布局指纹才够强（换图后开路格/内容格位置几乎不可能完全一样 ✓）
        try:
            _sne = self.looplog.board_snapshot
        except Exception:               # noqa: BLE001
            _sne = None
        _sid_now = None
        if isinstance(_sne, dict):
            try:
                _sid_now = (str(_sne.get('mapname') or ''),
                            tuple(sorted(str(k) for k in (_sne.get('board') or {}))))
            except Exception:           # noqa: BLE001
                _sid_now = None
        _sid_prev = getattr(self, '_board_snap_id', None)
        _new_map = ((_mn_now and _mn_prev and _mn_now != _mn_prev)
                    or (_sid_now is not None and _sid_prev is not None
                        and _sid_now != _sid_prev))
        if _new_map:
            self._board_frozen = None   # 换了图 ⇒ 重新取首帧 ✓
            self._plan_frozen = False
            self._live_plan = None
        if _mn_now:
            self._board_mapname = _mn_now
        if _sid_now is not None:
            self._board_snap_id = _sid_now
        # ---- ⭐⭐⭐ 冻结判定：取**进图首帧的整盘**（`board_snapshot`），不是每轮的稀疏板 ----
        #   ⛔⛔ 上一版的错（用户：「**完全不对啊，比之前还差**」）——
        #     按"第一条有内容的 board"就冻，而 `last_board` 优先级是 `round > board_snapshot`
        #     ⇒ 冻到的是**每轮的稀疏观测板**（真机实测：round **9~12 格** vs snapshot **26~29 格**）
        #     ⇒ 整张图**大面积缺格名**，比不冻（会慢慢补齐）**更差** ✗✗
        #   ⇒ 修：**只认 `board_snapshot`**；它还没到 ⇒ **不冻**（宁可先显示活动的稀疏板 ✓）
        _snap = getattr(self, '_board_frozen', None)
        if _snap is None:
            _full = None
            try:
                _full = self.looplog.board_snapshot
            except Exception:           # noqa: BLE001
                _full = None
            _fb = (_full or {}).get('board') if isinstance(_full, dict) else None
            if isinstance(_fb, dict) and _fb:
                try:
                    self._board_frozen = {
                        'board': dict(_fb),
                        # ⚠ 标记优先用快照自带的那份（与整盘同一时刻）✓
                        'marks': dict((_full.get('marks') if isinstance(_full, dict)
                                       else None) or marks or {}),
                        'hud': dict(self.looplog.hud or {}),
                        'plan_full': dict(getattr(self.looplog, 'plan_full', None) or {}),
                    }
                    _snap = self._board_frozen
                except Exception:       # noqa: BLE001
                    _snap = None
        if _snap:
            board = _snap.get('board') or {}
            marks = _snap.get('marks') or {}
        # ---- 计划：⭐ **与棋盘一样冻在首帧**（用户 2026-10-12 最新口径）----
        #   用户原话（先后三条，语义在演进，**以最后一条为准**）：
        #     ① 「实时棋盘只显示首帧的规划，不要继续显示执行完所以步数的了」
        #     ② 「实时棋盘怎么没有步数序号圆和箭头线条了」（⇒ 我上一版"计划不冻"矫枉过正 ✗）
        #     ③ 「**线路标记也要和实时棋盘一样，换图才更新**」← **本次定稿** ✓
        #   ⇒ 语义收口：**一张图 = 一张盘 + 一套线路标记**，两者**同帧出现**、**换图才一起换** ✓
        #   ── 实现 ──
        #     · 快照建立时若已有计划 ⇒ 一起冻进快照
        #     · 快照建立时还没算出（solver 慢半拍）⇒ 快照里留空，**首次拿到任何计划时
        #       补存一次**（`_plan_locked` 锁死）⇒ 本图后续重算**不再上屏** ✓
        #     · 换图（图名/快照指纹变）⇒ 快照整体清掉 ⇒ 新图重新取"盘 + 线" ✓
        _snap_plan = (_snap or {}).get('plan_full') or {}
        if _snap and not _snap_plan.get('order'):
            # 快照里还没计划 ⇒ 首次拿到就补存（只补这一次）
            try:
                _lp = self._live_plan
                _pf = self.looplog.plan_full or {}
                _first = _lp if (isinstance(_lp, dict) and _lp.get('order')) \
                    else (_pf if isinstance(_pf, dict) and _pf.get('order') else None)
                if _first:
                    self._board_frozen['plan_full'] = dict(_first)
                    _snap_plan = self._board_frozen['plan_full']
            except Exception:       # noqa: BLE001
                pass
        plan, src = {}, ''
        if isinstance(_snap_plan, dict) and _snap_plan.get('order'):
            plan = _snap_plan
            src = '首帧'
        else:
            # 兜底（本图还没锁到任何计划）⇒ 显示最新的，别让序号区空着 ✗
            lp = self._live_plan
            try:
                pf = self.looplog.plan_full or {}
            except Exception:       # noqa: BLE001
                pf = {}
            if isinstance(lp, dict) and lp.get('order'):
                plan, src = lp, '实时'
            elif isinstance(pf, dict) and pf.get('order'):
                plan = pf
                src = '整盘' if pf.get('src') == 'solver' else '本轮'
        order = list((plan or {}).get('order') or [])
        hud = (_snap or {}).get('hud') or self.looplog.hud or {}
        # ★ 目标格（描靛蓝边）：用 `targets_cfg.is_target` 现算 ⇒ 与跑图时**同一份口径** ✓
        tgt = set()
        try:
            import targets_cfg as TC
            cfg = self._cfg_special or TC.load()
            for rc, v in (board or {}).items():
                try:
                    sid = v[0] if isinstance(v, (list, tuple)) and v else ''
                    nm = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ''
                    mk = marks.get(rc) if isinstance(marks, dict) else None
                    if TC.is_target(nm, sid, mk, cfg):
                        tgt.add(rc)
                except Exception:       # noqa: BLE001
                    continue
        except Exception:       # noqa: BLE001
            tgt = set()
        # ⚠ 兼容旧版 `widgets`（没有 `spans` 参数）：给热更留一条退路 ——
        #   万一画布那侧还是老签名，棋盘要**退回"只画锚点格"**，而不是整盘画不出来 ✗
        try:
            self.board.update_board(board=board, marks=marks, order=order,
                                    cost=(plan or {}).get('cost'), target_cells=tgt,
                                    hud=hud, spans=self._spans_of(board))
        except TypeError:
            self.board.update_board(board=board, marks=marks, order=order,
                                    cost=(plan or {}).get('cost'), target_cells=tgt,
                                    hud=hud)
        if not board and not order:
            self.plan_var.set('计划：—（等进图；格名进图 ~1s 出快照）')
        else:
            self.plan_var.set(
                '计划：cost=%s ｜ %d 步%s ｜ %s'
                % ((plan or {}).get('cost') if (plan or {}).get('cost') is not None
                   else '—', len(order),
                   ('（%s）' % src) if src else '',
                   '→'.join(order[:8]) + ('…' if len(order) > 8 else '') or '—'))
        # ⭐⭐ 2026-10-18 方案 C：**同一份计划再画一排步骤胶囊**
        #   ── 数据**完全复用上面那份** `plan`/`order`/`board`（零新数据源 ✓）
        #   ── ⚠⚠ **必须在 `plan_var` 设完之后**：门禁 ⑩ 钉着 `plan_var` 仍存在且有值
        #     （它是“只删该删的”那条反向守门）⇒ 不能把它换成胶囊 ✗
        #   ── ⚠ 异常吞掉：胶囊画不出来**不能让整盘棋盘也挂掉** ✗
        try:
            self._plan_chips(order, (plan or {}).get('cost'), board)
        except Exception:           # noqa: BLE001
            pass
        # 状态句：子进程 stdout 里带 `› ` 前缀的行（`explore_loop.status()` ✓）
        self.line_var.set(getattr(self, '_last_status_line', None) or '› 就绪，等开跑')

    # ---- 多格地块：锚点 → 真实占格（`spots.Board.footprint`）----------------
    @staticmethod
    def _rc_of(k):
        try:
            a, b = str(k).split(',')
            return int(a), int(b)
        except Exception:       # noqa: BLE001
            return None

    def _spot_board(self, code):
        """取该图码的地块分类器（`spots.Board`，**惰性 + 缓存**；失败记 None 不再重试）

        ⚠ 实测构造 **0.07s**（`spots.py`，模板 alpha 推占格）⇒ 首次会顿一下，
          之后查字典零开销 ✓。全程 try/except（拿不到就退回"只画锚点格"的老行为 ✓）
        """
        if not code:
            return None
        if code in self._spot_boards:
            return self._spot_boards[code]
        b = None
        try:
            import spots
            b = spots.Board(code)
        except Exception as e:      # noqa: BLE001
            try:
                self.log('（多格地块：该图分类器不可用 %r ⇒ 只画锚点格）' % (e,))
            except Exception:       # noqa: BLE001
                pass
            b = None
        self._spot_boards[code] = b
        return b

    def _spans_of(self, board):
        """`board`（只有锚点格）→ `[(anchor, cells), …]`（**多格地块的真实占格**）

        ⛔ 病：`explore_loop` 落盘时 `if v['anchor'] == k` 只留锚点 ⇒ 一个 2×2 的
          「巨大沙堡」在棋盘上只填 1 格，另外 3 格看着是雾 ✗（用户 2026-10-11 反馈）
        ⇒ 修法（**纯 UI 侧，不动 explore_loop**）：图名 → `spots.code_of` → 图码 →
          `spots.Board(code)` → 用 `cells_of(sid, anchor)` 把整块算出来 ✓
          ⚠ 全序都要容错：拿不到图名/图码 ⇒ 返回 `[]`（退回老行为，绝不抛 ✓）
        """
        out = []
        if not isinstance(board, dict) or not board:
            return out
        try:
            name = self.looplog.mapname
            if not name:
                return out
            code = self._spot_codes.get(name)
            if code is None:
                import spots
                code = spots.code_of(name) or ''
                self._spot_codes[name] = code
            b = self._spot_board(code)
            if b is None:
                return out
            for k, v in board.items():
                rc = self._rc_of(k)
                if rc is None or not isinstance(v, (list, tuple)) or len(v) < 4:
                    continue
                # ⛔⛔⛔ 2026-10-12 **低分不许展开成多格块**（用户报「营地被合体」✗）
                #   ---- 真机铁证（帧 `runs/_live_now.png` 逐格复算）----
                #     `3,1` 认成「空间水晶」但 **score 只有 0.12**（雾里乱猜）
                #     ⇒ `cells_of` **无条件展开**成 3×3 九格：
                #        (3,1)(3,2)(3,3)/(4,1)(4,2)(4,3)/**(5,1)**(5,2)(5,3)
                #     ⇒ **把营地 (5,1) 吞进去了** ⇒ 窗口画成"营地+附近两格合体"✗✗
                #     该帧共 **27 格**被展开成假块（score 全在 0.117~0.27）✗
                #   ---- 门槛取值（实测 `_tmpman/chk_span_min.py`，全量 loop_log）----
                #     真·多格块 score：<0.35:10 ｜ 0.35~0.5:257 ｜ 0.5~0.7:1425 ｜ >=0.7:808
                #     假块（本帧）：0.117/0.12/0.176/0.208/0.226 ⇒ **全 <0.35** ✓
                #     ⇒ 取 **0.35**：挡住全部假块，真块只误伤 10/2500 = 0.4% ✓
                #   ⚠ 与既有原则**同源**（"雾里名字不可信"）：
                #     `mapsim.CONTENT_SCORE_MIN=0.85` ／ `targets_cfg.NAME_SCORE_MIN=0.85` ✓
                #   ⚠ 低分 ⇒ **只画锚点格自己**（退回老行为），不画假大块 ✓
                try:
                    _sc = float(v[2]) if len(v) > 2 else 1.0
                except Exception:       # noqa: BLE001
                    _sc = 1.0           # 读不出分 ⇒ **不拦**（保守 ✓）
                if _sc < SPAN_SCORE_MIN:
                    continue
                sid = '%s_%s' % (code, str(v[0] or '').strip())
                try:
                    cells = [(int(r), int(c)) for r, c in b.cells_of(sid, rc)]
                except Exception:       # noqa: BLE001
                    continue
                cells = [(r, c) for r, c in cells
                         if 1 <= r <= self.board.ROWS and 1 <= c <= self.board.COLS]
                if len(cells) > 1:
                    out.append((rc, cells))
        except Exception as e:      # noqa: BLE001
            try:
                self.log('（多格地块展开失败：%r ⇒ 只画锚点格）' % (e,))
            except Exception:       # noqa: BLE001
                pass
            return []
        return out

    # ══════════════════════════════════════════════════════════════════
    # ⑤ 环境检查 / 扫屏 / 查重 / 多开（**全部后台线程** ✓）
    # ══════════════════════════════════════════════════════════════════
    def check(self):
        """环境检查（**异步**）—— 结果既打到日志，也列表化到「工具」页签 ✓

        ⚠ 老代码在**主线程同步**跑 `subprocess.run(adb devices)`（最慢 10s×N）
          ⇒ UI 直接冻住 ✗（P3）⇒ 现在一律 `DeviceService` 后台线程 + 事件队列 ✓
        """
        self.dev.check_env_async(self.device)
        return True

    def _show_env_rows(self, rows, ok):
        """把 `paths.diagnose()` 的 5 项渲染成 ✓/✗ 列表（工具页签 ✓）"""
        lines = ['环境体检（%s）' % time.strftime('%H:%M:%S')]
        for d in (rows or []):
            try:
                lines.append('%s %-14s %s' % ('✓' if d.get('ok') else '✗',
                                              d.get('label'), d.get('detail')))
            except Exception:       # noqa: BLE001
                continue
        lines.append('')
        lines.append('（本轮结论：%s）' % ('正常 ✓' if ok else '有问题 ✗ 见上面'))
        try:
            self.env_txt.configure(state='normal')
            self.env_txt.delete('1.0', 'end')
            self.env_txt.insert('1.0', '\n'.join(lines))
            self.env_txt.configure(state='disabled')
        except Exception:       # noqa: BLE001
            pass

    def scan_screen(self):
        """把模拟器当前屏 OCR 出来（标定按钮坐标用）——**只读屏幕，不点任何东西 ✓**"""
        self.dev.scan_screen_async(self.device, self.tag)

    def dedupe_loops(self):
        """⭐ 查重复循环：列出同一台模拟器上所有 explore_loop，并**一键清理**

        用户 2026-09-25 要求。只清理 explore_loop，**绝不碰窗口/截图服务**。
        """
        self.dev.dedupe_async(self.device)

    def _show_loops(self, ls):
        if not ls:
            try:
                messagebox.showinfo('检查重复循环', '没有正在跑的循环 ✓', parent=self.root)
            except Exception:       # noqa: BLE001
                pass
            return
        mine = [p for p in ls if p.get('device') == self.device]
        others = [p for p in ls if p.get('device') != self.device]
        lines = ['   PID %-6d 设备 %-20s tag %s'
                 % (p.get('pid'), p.get('device') or '?', p.get('tag') or '-')
                 for p in ls]
        try:
            if messagebox.askyesno(
                    '发现重复循环',
                    '当前有 %d 个循环在跑（本窗口绑的 %s 上有 %d 个；其它设备 %d 个）：\n%s\n\n'
                    '要**全部停掉**吗？（只停循环，不动窗口）'
                    % (len(ls), self.device, len(mine), len(others), '\n'.join(lines)),
                    parent=self.root):
                self.dev.kill_loops_async([p.get('pid') for p in ls])
        except Exception:           # noqa: BLE001
            pass

    def _on_dups(self, dup):
        """启动前的查重结果 ⇒ 决定"停旧的"还是"硬着头皮并存" ✓"""
        pend = self._pending or {}
        if pend.get('phase') != 'dup':
            # 不是启动流程里的查重（理论上不会走到这）⇒ 只报一下
            if dup:
                self.log('⚠ 这台模拟器上已经有 %d 个循环' % len(dup))
            return
        if not dup:
            pend['phase'] = 'go'
            self._do_start(pend.get('maps', 1))
            return
        rest = [p.get('pid') for p in dup]
        ask_ok = False
        try:
            ask_ok = bool(messagebox.askyesno(
                '已有循环在跑',
                '这台模拟器上已经有 %d 个循环：%s\n\n'
                '继续会**两边抢点击**（不推荐）。\n要先把它们停掉再开新的吗？\n'
                '（选「否」= 直接继续，可能互相干扰）' % (len(rest), rest),
                parent=self.root))
        except Exception:       # noqa: BLE001
            ask_ok = False
        if ask_ok:
            self.dev.kill_loops_async(rest)
            time.sleep(0.6)
        else:
            self.log('⚠ 用户选择：不停旧循环，继续启动（可能互相干扰）')
            self.runner.mark_force_next()    # 循环那边的自检也要放行 ✓
        pend['phase'] = 'go'
        self._do_start(pend.get('maps', 1))

    def spawn_multi(self):
        """再开一个窗口，绑**另一个正在运行的 MuMu 实例**（按实例名轮询，不再靠猜端口）"""
        self.dev.spawn_multi_async(self.device)

    def _show_multi_fail(self, lines):
        self.log('⚠ 没有可用的 MuMu 实例可绑：')
        for ln in (lines or []):
            self.log(ln)
        try:
            messagebox.showwarning(
                '没有可用的实例',
                '「多开」会**再开一个窗口绑另一台 MuMu**。\n'
                '但现在每台要么没启动、要么**已经有一个循环在跑**（同一台开两个窗口会互相抢 ✗）。\n\n'
                '当前实例状态：\n' + '\n'.join(lines or []) +
                '\n\n· 若那台在**别的窗口**里跑着 ⇒ 去那个窗口点 ■ 停止，再回来点多开 ✓\n'
                '· 若那台还没启动 ⇒ 先在 MuMu 多开器里启动它（并登录游戏）✓',
                parent=self.root)
        except Exception:       # noqa: BLE001
            pass

    def _open_multi(self, dev, tag, name):
        self.log('✓ 正在为「%s」(%s) 打开新窗口…' % (name, dev))
        if self.dev.open_multi_window(dev, tag, name):
            self.log('✓ 已新开窗口：MuMu「%s」（%s，实例 %s）' % (name, dev, tag))

    def open_logs(self):
        try:
            os.startfile(self.runs)       # noqa: S606
        except Exception as e:          # noqa: BLE001
            self.log('⚠ 打不开日志目录：%r' % e)

    # ══════════════════════════════════════════════════════════════════
    # ⑥ 起 / 停
    # ══════════════════════════════════════════════════════════════════
    def start(self, maps):
        """点 ▶ / 跑 1 张 ⇒ **异步三步**：环境检查 → 查重 → 起子进程 ✓

        ⚠ 老代码这三步全在**主线程同步**跑（adb 最多 10s×N ⇒ UI 冻住 ✗ P3）
        ⚠ 顺序与判据**照搬**：环境不过 ⇒ 不起；有重复循环 ⇒ 问用户；
          "不停旧循环" ⇒ 这一次带 `--force` ✓
        """
        if self.runner.is_running():
            self.log('⚠ 已经有一个任务在跑了，先点「停止」再开新的')
            return
        # ⛔ 2026-10-12 删掉"锁未处理不许开跑"这道闸门（用户：「**我不需要这个锁定**」✓）
        self._pending = {'maps': maps, 'phase': 'env'}
        self.run_state = 'checking'
        self._sync_buttons()
        self.log('▶ 开跑前先体检环境…（跑 %s）'
                 % ('到体力耗尽' if maps > 10 else '%d 张' % maps))
        self.dev.check_env_async(self.device)

    def _do_start(self, maps):
        """真正起子进程（**命令行/env 由 `services.LoopRunner` 拼 ⇒ 与重写前逐字一致 ✓**）"""
        # ⭐ 新一局 ⇒ 清掉上一局的实时计划/进度（否则新版第一次规划之前会残留旧序号 ✗）
        self._live_plan = None
        self._plan_frozen = False       # ⭐ 新一局 ⇒ 解冻（新图重新认首帧计划 ✓）
        self._board_frozen = None       # ⭐ 新一局 ⇒ 清快照（新图重新认首帧棋盘 ✓）
        self._round_line = ''
        self._last_map_line = ''
        try:
            self.plan_var.set('计划：—（等这局第一次规划）')
            self.prog_var.set('进度：—')
        except Exception:       # noqa: BLE001
            pass
        try:
            _be = int((self.bag_every_var.get() or '10').strip())
        except Exception:       # noqa: BLE001
            _be = 10
        try:
            supply = bool(self.supply_var.get())
        except Exception:       # noqa: BLE001
            supply = False
        try:
            save = bool(self.saveimg_var.get())
        except Exception:       # noqa: BLE001
            save = True         # 读不到就当开（宁可多存，别又出现"没图可核"✗）
        stops = {}
        for w, var in (('lucky', getattr(self, 'stop_lucky_var', None)),
                       ('peace', getattr(self, 'stop_peace_var', None)),
                       ('elem_purple', getattr(self, 'stop_elem_purple_var', None)),
                       ('elem_orange', getattr(self, 'stop_elem_orange_var', None))):
            try:
                stops[w] = bool(var.get())
            except Exception:       # noqa: BLE001
                stops[w] = True     # 读不到 ⇒ **默认开**（宁可停下来让人处理 ✓）
        # ⭐⭐⭐⭐⭐ 2026-10-13 **把"本设备那份特殊方块配置"传给子进程**（用户口径：
        #   「**和对应窗口绑定（选哪个窗口就自动用对应的配置）**」✓）
        #   ---- 不传会怎样（真 bug ✗）----
        #     子进程 `targets_cfg` 默认读 `runs/target_types.json`（**全局一份**）
        #     ⇒ 开两个窗口 ⇒ **勾选互相覆盖** ✗✗
        #   ⇒ 传绝对路径 + 先落盘（保证文件存在，子进程读得到 ✓）
        #   ⚠ `targets_path()` 内部会**先做一次迁移**（把老的全局那份复制过来）
        #     ⇒ 老用户的勾选**一个都不丢** ✓
        try:
            _tcfg = self.prefs.targets_path()
            # ⚠ 先触发一次 load（缺文件时它会**自动写出来** ✓）⇒ 子进程一定读得到 ✓
            try:
                import targets_cfg as _TC0
                _TC0.load(path=_tcfg)
            except Exception:       # noqa: BLE001
                pass
        except Exception as e:      # noqa: BLE001
            _tcfg = None
            self.log('⚠ 本设备特殊方块配置路径取不到（%r）⇒ 子进程用全局那份' % (e,))
        logfile, cmd, _env = self.runner.start(
            self.device, maps, bag_every=_be, auto_supply=supply,
            save_first=save, stop_lucky=stops['lucky'], stop_peace=stops['peace'],
            stop_elem_purple=stops['elem_purple'], stop_elem_orange=stops['elem_orange'],
            targets_cfg_path=_tcfg,
            # ⭐⭐ 2026-10-14「**派遣和炼金合成一个选项**」（用户口径）：
            #   那一颗「公会日常」勾选 ⇒ **两个变量一起置位** ⇒ 子进程两件都做 ✓
            #   ⚠ 两个变量都传（而不是只传一个）—— 子进程侧两件是**独立实现**，
            #     各认自己的变量；这里"一勾两传"就是把它们**绑成一颗**的唯一动作 ✓
            guild_tasks=bool(self.tasks_var.get()),
            alchemy=bool(self.tasks_var.get()),
            recruit=bool(self.recruit_var.get()),
            # ⭐ 2026-10-15 免广告（**独立勾选** —— 广告领奖不在公会里做 ✓）
            adfree=bool(self.adfree_var.get()))
        self._pending = None
        if not logfile:
            self.log('✗ 启动失败：子进程没起来（多半是 venv 的 python 路径或 explore_loop.py 不见了）')
            self.log('  拼出来的命令：%s' % ' '.join(cmd or []))
            self.run_state = 'idle'
            self.set_running(False)
            return
        self.log('')
        self.log('▶ %s' % ' '.join(cmd[1:]))
        self.log('  日志文件：%s' % logfile)
        self.log('  存图：%s ｜ 自动补给：%s ｜ 每 %d 张升装备星'
                 % ('开 ✓' if save else '关', '开 ✓' if supply else '关', max(0, _be)))
        # ⭐ 2026-10-14：公会日常/免费招募也报一行（用户要看得见"这次做不做"✓）
        self.log('  公会日常（派遣+炼金）：%s ｜ 免费招募：%s%s'
                 % ('开 ✓' if self.tasks_var.get() else '关',
                    '开 ✓' if self.recruit_var.get() else '关',
                    '（⚠ 炼金会消耗 6 件 5★ 满星装备）'
                    if self.tasks_var.get() else ''))
        if _tcfg:
            self.log('  特殊方块配置：%s（本窗口专属 ✓）' % _tcfg)
        # ⚠ 顺手把当前升星张数记下来（`save_bag_every` 靠它判"变没变" ✓）
        self._bag_every_saved = max(0, _be)
        self.set_running(True)

    def stop(self):
        if not self.runner.is_running():
            return
        self.run_state = 'stopping'
        self._sync_buttons()
        self.log('… 正在停止（等这一小步做完）')
        self.runner.stop()

    # ══════════════════════════════════════════════════════════════════
    # ⑦ 统计（**写进日志 + 仪表盘**；口径照搬用户要求 T11 ✓）
    # ══════════════════════════════════════════════════════════════════
    def show_summary(self):
        """运行结束时把统计**写进日志区**（**不弹窗、不出声**，用户 2026-09-25 要求）

        多开时读的是**本实例自己**那份：`runs/<tag>/last_summary.json`

        ⭐⭐⭐ 2026-10-03 用户口径（原话）：
          「**窗口最下面的"本次统计"不关窗口就不从零开始记。连刷好几次的数据
            统一在下面窗口展现**」+「**关了窗口才清空**」✓
        ⭐⭐⭐ 2026-10-07 用户口径（原话）：
          「**下面的本次统计窗口取消吧，日志也能显示本次统计**」
        ⇒ **不再有独立的统计框** —— 统计**打印到日志区**，同时**固化到仪表盘** ✓
          · 每次跑完**累积**显示（本窗口累计第 N 次 ✓，关窗口才清空 ✓）
          · 最近 40 段封顶（防无限长 ✗）
          · 数字项尽力累加（跳过 avg/rate/at/per 这类**不能相加**的 ✓）
        """
        self.summary.poll()
        d = {'text': self.summary.text, 'stats': self.summary.stats or {}}
        try:
            txt = (d.get('text') or '').strip()
            if not txt:
                return
            # ---------- 累积（窗口生命周期内 ✓ 关窗口才清空 ✓）----------
            self._acc_n = int(getattr(self, '_acc_n', 0) or 0) + 1
            self._acc_texts = list(getattr(self, '_acc_texts', []) or [])
            _t = time.strftime('%H:%M:%S')
            self._acc_texts.append('── 第 %d 次 ▶（%s）──\n%s' % (self._acc_n, _t, txt))
            if len(self._acc_texts) > 40:
                self._acc_texts = self._acc_texts[-40:]
            try:
                _st = d.get('stats') or {}
                _acc = dict(getattr(self, '_acc_nums', {}) or {})
                _skip = ('avg', 'rate', 'at', 'per', 'started', 'min', 'max')
                for _k, _v in _st.items():
                    if (isinstance(_v, (int, float)) and not isinstance(_v, bool)
                            and not any(s in str(_k).lower() for s in _skip)):
                        _acc[_k] = _acc.get(_k, 0) + _v
                        if isinstance(_acc[_k], float):
                            _acc[_k] = round(_acc[_k], 1)
                self._acc_nums = _acc
            except Exception:       # noqa: BLE001
                pass
            _head = '【本窗口累计第 %d 次】（**只有关掉窗口才清空** ✓）' % self._acc_n
            _tail = ''
            if getattr(self, '_acc_nums', None):
                _tail = '\n合计：' + ' ｜ '.join('%s=%s' % (k, v) for k, v in
                                                sorted(self._acc_nums.items()))
            # ⭐ 2026-10-07：**全部写进日志**（原来的独立统计框已按用户要求取消 ✓）
            self.log('')
            self.log('=' * 64)
            self.log('📊 本次统计（%s）' % _t)
            self.log('=' * 64)
            for _ln in txt.splitlines():
                if _ln.strip():
                    self.log('   ' + _ln.rstrip())
            self.log('-' * 64)
            self.log(_head)
            if _tail:
                for _ln in _tail.strip().splitlines():
                    if _ln.strip():
                        self.log('   ' + _ln.rstrip())
            self.log('=' * 64)
            self.log('')
        except Exception as e:      # noqa: BLE001
            self.log('（统计读取失败：%r）' % e)

    # ══════════════════════════════════════════════════════════════════
    # ⑧ 特殊方块（说明 / 落盘）
    # ══════════════════════════════════════════════════════════════════
    def _show_special_help(self, block_cls=True):
        """「❗」按钮 —— 弹出**该类每个方块**的说明

        ⭐⭐⭐ 2026-10-09 用户口径（原话）：
          「**特殊方块的描述改成个感叹号，点了可以看描述**」✓

        `block_cls=True` ⇒ 列**拉黑类**（不勾 = 完全拉黑）
        `block_cls=False` ⇒ 列**可点类**（不勾 = 不专门拿，挡路会点）
        """
        try:
            import targets_cfg as TC
            names = sorted(TC.BLOCK_NAMES) if block_cls \
                else sorted(TC.SPECIAL_NAMES - TC.BLOCK_NAMES)
            head = ('拉黑类（**不勾 = 完全拉黑**：不点、也不借道）\n'
                    if block_cls else
                    '可点类（**不勾 = 不专门拿，但挡路也会点**）\n')
            body = [head, '─' * 46, '']
            for nm in names:
                body.append(TC.describe(nm))
                body.append('')
            text = '\n'.join(body)
        except Exception as e:                  # noqa: BLE001
            text = '说明读取失败：%r' % (e,)
        try:
            dialogs.text_dialog('特殊方块说明'
                                + ('（拉黑类）' if block_cls else '（可点类）'),
                                text, 560, 520)
        except Exception:       # noqa: BLE001
            # 弹窗失败（极小概率）⇒ 退到日志，别静默 ✗
            for ln in text.splitlines():
                self.log('   ' + ln)

    def _show_stop_help(self):
        """「❗」按钮（**预言石碑停止规则**那组）—— 弹出 4 条规则各自的完整含义

        ⭐⭐ 2026-10-12 用户口径（原话）：「**预言石碑停止规则也要类似特殊地块后面
          加上感叹号解释说明**」✓
        ⚠ 文案**唯一来源**是 `self._stop_items()` 的第 5 个元素（`tip`）
          ⇒ 与勾选框 `_Tip` 悬浮提示**同一份字符串**（改一处两处都变、不会漂移 ✓）
        """
        try:
            body = ['预言石碑停止脚本（**勾 = 抽到就停脚本、保现场**）\n',
                    '⚠ 只对**预言石碑**抽到的卡生效；停脚本时**不继续点图**，'
                    '方便你手动处理现场 ✓\n',
                    '─' * 46, '']
            for _w, _vn, txt, _cb, tip in self._stop_items():
                body.append('【%s】' % txt)
                body.append(tip or '（无说明）')
                body.append('')
            text = '\n'.join(body)
        except Exception as e:                  # noqa: BLE001
            text = '说明读取失败：%r' % (e,)
        try:
            dialogs.text_dialog('预言石碑停止规则说明', text, 560, 460)
        except Exception:       # noqa: BLE001
            for ln in text.splitlines():    # 弹窗失败 ⇒ 退到日志，别静默 ✗
                self.log('   ' + ln)

    def _save_special(self, name, var):
        """特殊方块勾选变化 ⇒ **立刻落盘** ✓

        `targets_cfg` 的口径（**2026-10-09 起分两类**）：
          · **拉黑类**（`BLOCK_NAMES`：商人/宝库/两个宝箱怪/传承祭坛）
            ⇒ 不勾 = **完全拉黑**（不进目标、也不当路 ✗）
          · **可点类**（其余：勇者之墓/限时礼包/预言石碑）
            ⇒ 不勾 = **不专门拿，但挡路会点**（`targets_cfg.PICK_IF_BLOCKING` ✓）
        ⚠ 勾上 ⇒ 立刻变成"主动处理"（进目标 ✓）
        """
        try:
            on = bool(var.get())
            ok = self.prefs.save_special(name, on)
            self.log('特殊方块「%s」⇒ %s（%s）'
                     % (name, '主动处理 ✓' if on else '拉黑 ✗',
                        '已落盘，下一轮生效 ✓' if ok else '⚠ 落盘失败'))
            # ⭐ 2026-10-03 用户要求「加」⇒ **同时显示成状态行** ✓
            #   ⚠⚠ PC 端**没有悬浮条**（那是手机端用无障碍画在游戏上的 ✓）
            #     PC 的状态行 = 窗口日志区里带 `›` 前缀的那几行 ✓（和 `status()` 同款 ✓）
            self.log('› %s已%s' % (name, '启用（会主动去开/去买）' if on
                                   else '拉黑（不进目标、也不当路）'))
            # 勾选变了 ⇒ 棋盘的"目标格"描边也要跟着变（下一拍就刷新 ✓）
            try:
                import targets_cfg as TC
                self._cfg_special = TC.load()
            except Exception:       # noqa: BLE001
                pass
        except Exception as e:                 # noqa: BLE001
            self.log('⚠ 保存特殊方块勾选失败：%r' % (e,))

    # ══════════════════════════════════════════════════════════════════
    # ⑨ 偏好（补给 / 存图 / 预言石碑四个开关）
    # ══════════════════════════════════════════════════════════════════
    def _supply_pref_path(self):
        return self.prefs.auto_supply_path()

    def _load_supply_pref(self):
        v = self.prefs.load_auto_supply()
        self.supply_var.set(v)
        if v:
            self.log('（已记住：没体力时自动用结实补给）')

    def toggle_supply(self):
        v = bool(self.supply_var.get())
        self.prefs.save_auto_supply(v)
        self.log('自动使用结实补给：%s' % ('开 ✓（没体力<50 时自动去背包用）' if v else '关'))

    # ⭐⭐⭐⭐ 2026-10-14 **公会日常一颗勾选**（用户口径：
    #   「炼金和派遣勾选选项加在没体力自动用补给前面」＋「**派遣和炼金合成一个选项**」✓）
    #   勾上 = 收工后去公会一次做完**派遣 + 炼金**两件
    #   ⇒ 落盘到本设备（`runs/dev_<port>/.guild_tasks`），子进程读到就两件都做 ✓
    def toggle_tasks(self):
        v = bool(self.tasks_var.get())
        self.prefs.save_guild_tasks(v)
        if v:
            self.log('公会日常：开 ✓（体力刷完后自动做**派遣任务 + 情报领奖 + 炼金**）')
            self.log('   · 派遣任务：把 4 把小队的任务都派出去、领掉已完成的奖励'
                     '（**不放弃、不召回**）')
            self.log('   · 情报领奖：公会右上角「情报」⇒ 每日逐条领、'
                     '每周领最上面那条（**纯领奖、零消耗**）')
            self.log('   · 炼金：顶楼点「满星」→「开始炼金」')
            self.log('   ⚠ ⚠ 炼金会消耗 **6 件 5★ 满星装备**（换成金币+结晶，不可逆）')
        else:
            self.log('公会日常：关')

    # ⭐⭐ 2026-10-14 「免费招募」勾选 + **立即运行**（用户口径：
    #   「**免费招募改成可以勾选可以立即运行**」✓）
    #   · 勾选 ⇒ 收工后自动做（`MAPBOT_RECRUIT=1`）
    #   · 旁边的「立即招募」按钮 ⇒ **当场做一次**（子进程 + 事件队列，不冻 UI ✓）
    #   ⚠ 按钮**只在勾选时可点** —— 招募会花掉当天那次免费机会 ⇒ 必须显式授权 ✓
    def toggle_recruit(self):
        v = bool(self.recruit_var.get())
        self.prefs.save_recruit(v)
        # ⭐ 勾选状态一变，立刻同步那颗「立即招募」按钮的可用性 ✓
        self._sync_recruit_btn()
        if v:
            self.log('免费招募：开 ✓（体力刷完后自动做「免费指定招募」）')
            self.log('   · 用小助手那套权重选出**保底最高**的标签组合 ⇒ 尽量拿高等级角色')
            self.log('   · 免费机会用掉了会自动跳过（**不花宝石** ✓）')
            self.log('   · 「**立即招募**」按钮已移到「**工具**」页签 ⇒ 现在可点 ✓')
        else:
            self.log('免费招募：关（「工具」页签里的「立即招募」已变灰）')

    # ⭐⭐⭐ 2026-10-15 **「免广告」勾选**（用户口径：
    #   「开始做领取广告（默认有免广）…单独加个有无免广的勾选，有就自动做」
    #   ＋补问确认「勾 = 有免广，未勾则不做」＋「默认勾上」✓）
    # ---- 语义（源码级）----
    #   `SaveData.CanSkipAds()` = `GetMonthRightRemainDays().Any(x => x >= 0)`
    #   ⇒ **"免广告" = 月卡权益还有剩余天数** ⇒ **账号状态**，不是设置开关 ✓
    #   ⇒ 这颗勾选 = **告诉脚本"这个号有免广"** ⇒ 脚本据此决定做不做广告领奖 ✓
    # ⚠ **默认 True**（用户口径「默认有免广」）✓
    def toggle_adfree(self):
        v = bool(self.adfree_var.get())
        self.prefs.save_adfree(v)
        if v:
            self.log('免广告：开 ✓（体力刷完后自动看广告领）')
            self.log('   · **购买体力×3 ｜ 四叶草×3 ｜ 金币×3 ｜ 加速炼金×1**')
            self.log('   · 每日次数以游戏面板上的 `剩余/上限` 为准，领完自动停 ✓')
            self.log('   ⚠ 全程**不花宝石**（只点"看广告"那颗绿按钮）')
        else:
            self.log('免广告：关 ⇒ 四个广告入口**一下都不碰** ✓')
            self.log('   （没有免广就得真播视频广告，脚本做不了）')

    def _load_adfree_pref(self):
        """读回「免广告」勾选（⭐ **读不到 ⇒ 开** —— 用户口径「默认有免广」✓）

        ⚠ 与「免费招募」的默认值**不同**：
          · 免费招募**读不到 ⇒ 关**（它会消耗当天那次免费机会 ⇒ 要显式授权 ✓）
          · 免广告**读不到 ⇒ 开**（用户明确说「默认有免广」；
            而且**领广告奖是纯收益、零消耗** —— 不花体力/金币/宝石 ✓）
        """
        try:
            v = self.prefs.load_adfree(True)
        except Exception:       # noqa: BLE001
            v = True
        self.adfree_var.set(bool(v))
        if v:
            self.log('（已记住：免广告 开 ⇒ 自动领广告奖 ✓）')

    def _sync_recruit_btn(self):
        """同步「立即招募」按钮的可用性（**只在勾选时可点** ✓）

        ⚠ 用 `state='normal'/'disabled'` 而不是 `configure(fg_color=…)` ——
          禁用态 ctk 自己会画灰，比自己调色可靠 ✓
        """
        try:
            _on = bool(self.recruit_var.get())
            # ⚠ 正在跑的时候也不许点（同一个设备不能同时两个子进程抢点击 ✗）
            _busy = bool(getattr(self, '_recruit_running', False))
            self.recruit_now_btn.configure(
                state=('normal' if (_on and not _busy) else 'disabled'),
                text=('招募中…' if _busy else '立即招募'))
        except Exception:       # noqa: BLE001
            pass

    def recruit_now(self):
        """⭐ **立即招募**：不等收工，当场跑一次 `recruit.py`（后台线程 ✓）

        ⚠ 三道前置检查（任一不过就**不动**，并说清原因 ✓）：
          ① 勾了「免费招募」没有（没勾不许点 —— 但按钮本来就灰着，这里再兜一道）
          ② 循环**没在跑**（同时跑两个子进程会互相抢点击 ✗）
          ③ 没在跑招募（防连点）
        ⚠ 走 `DeviceService` 后台线程 + 事件队列 ⇒ **不冻 UI** ✓
        """
        if not bool(self.recruit_var.get()):
            self.log('⚠ 「立即招募」需要先勾上「免费招募」（那是一次授权）')
            return
        if self.runner.is_running():
            self.log('⚠ 循环正在跑 ⇒ 不能同时做招募（两个子进程会互相抢点击 ✗）')
            self.log('   请先点「■ 停止」，再点「立即招募」')
            return
        if getattr(self, '_recruit_running', False):
            self.log('（招募已经在跑了，等它跑完 ✓）')
            return
        self._recruit_running = True
        self._sync_recruit_btn()
        self.dev.recruit_now_async(self.device, self.tag)

    # ⭐⭐⭐⭐ 2026-10-16 **「果实记录」**（用户口径，两次）
    #   ① 「类似小助手的天赋果实记录，**做好放到工具栏里**」
    #   ② ⛔ 「去掉「扫天赋果实」按钮，点天赋果实记录要**能直接在工具那里看到
    #        果实记录，不要还得去日志看**」  ← 本次
    def fruit_report(self):
        """「果实记录」⇒ **直接写进工具页那个文本框**（`env_txt`）✓

        ⛔⛔ 用户口径：「**不要还得去日志看**」✗
          ⇒ 我第一版写的是 `self.log(...)`（往**日志区**打）⇒ 用户还得切到日志页 ✗
          ⇒ 现在**直接写 `env_txt`**（工具页里那个框，环境检查结果也用它 ✓）
        ⚠ 纯读文件 ⇒ 主线程直接跑**不卡**（不需要后台线程 ✓）
        ⚠ 内容**整体替换**（先 delete 再 insert）⇒ 不留上一次的残留 ✓
        ⚠ 出错也**写进框里**（而不是只打日志）⇒ 用户在这个页面就能看见原因 ✓
        """
        try:
            import fruit as _fr
            txt = _fr.report_text(None, self._fruit_path())
        except Exception as e:      # noqa: BLE001
            txt = ('⚠ 读果实记录失败：%r' % (e,))
        try:
            self.env_txt.configure(state='normal')
            self.env_txt.delete('1.0', 'end')
            self.env_txt.insert('1.0', txt + '\n')
            self.env_txt.configure(state='disabled')
        except Exception as e:      # noqa: BLE001
            # 兜底：框写不进去时**至少**在日志里留一句（别静默失败 ✗）
            self.log('⚠ 果实记录写不进文本框（%r）；内容如下：' % (e,))
            for ln in str(txt).splitlines():
                self.log(ln)

    def _fruit_path(self):
        """本窗口的记录文件路径 ⇒ `runs/<tag>/fruit_record.json` ✓

        ⚠⚠ 口径**逐字对齐 `fruit.record_path(None, tag)`**（而后者又对齐
          `Bot.__init__`）：**tag 空 ⇒ `runs/`**（**不是** `runs/default/` ✗）
          ⇒ 单开时两边必须落在**同一个文件**上（否则「果实记录」看不到扫描结果 ✗）
        """
        try:
            sys.path.insert(0, HERE)
            import fruit as _fr
            return _fr.record_path(None, self.tag)
        except Exception:       # noqa: BLE001
            return None

    def _load_recruit_pref(self):
        """读回「免费招募」勾选（**读不到 ⇒ 关** ✓ 它会消耗当天那次免费机会）"""
        try:
            v = self.prefs.load_recruit(False)
        except Exception:       # noqa: BLE001
            v = False
        self.recruit_var.set(bool(v))
        self._sync_recruit_btn()
        if v:
            self.log('（已记住：免费招募 开 —— 「立即招募」可点 ✓）')

    def _load_tasks_pref(self):
        """读回「派遣任务」勾选（**读不到 ⇒ 关** ✓ 别偷偷改游戏状态）"""
        try:
            v = self.prefs.load_guild_tasks(False)
        except Exception:       # noqa: BLE001
            v = False
        self.tasks_var.set(bool(v))
        if v:
            self.log('（已记住：公会日常 开 —— 派遣+炼金都做；'
                     '⚠ 炼金会消耗 6 件 5★ 满星装备）')

    def _load_alchemy_pref(self):
        """（**已并入「公会日常」那颗勾选**，本函数保留为空壳 ⇒ 不再被调用 ✓）

        ⛔ 2026-10-14 用户口径：「**派遣和炼金合成一个选项**」⇒ 炼金**不再有独立勾选** ✓
          ⇒ 原来那颗 `.alchemy` 偏好文件**不再被 GUI 读写**（留着不删，见 `Prefs` 里的说明 ✓）
        保留本函数（而不是删掉）的原因：**老版本可能还在调它**（热更回滚时会用旧 `bot_gui`）
          ⇒ 空壳 + 解释，比 `AttributeError` 友好 ✓
        """
        return None

    def _saveimg_pref_path(self):
        return self.prefs.save_img_path()

    # ⭐⭐⭐⭐⭐ 2026-10-13 **「每 N 张图升星」也记住**（用户口径：
    #   「**多少张图自动升星等需要用户自己选择的自动用最近一次配置**」✓）
    def save_bag_every(self):
        """把输入框里的值**落盘到本设备**（失焦/回车时调 ✓）

        ⚠ 读不出 int ⇒ **不写盘、不报错**（用户可能正打到一半/清空了 ✓）
        ⚠ 落盘成功**不刷日志**（每次失焦都打一行会把日志区刷花 ✗）；
          只在**值真的变了**时打一行，方便用户确认"记住了" ✓
        """
        try:
            _txt = (self.bag_every_var.get() or '').strip()
            _v = max(0, int(_txt))
        except Exception:       # noqa: BLE001
            return              # 打到一半/空 ⇒ 静默不写（不是错误 ✓）
        if _v == getattr(self, '_bag_every_saved', None):
            return              # 没变 ⇒ 不写盘、不刷日志 ✓
        try:
            ok = self.prefs.save_bag_every(_v)
        except Exception as e:      # noqa: BLE001
            self.log('⚠ 升星张数没存上：%r' % (e,))
            return
        self._bag_every_saved = _v
        if ok:
            self.log('每 %d 张图升星装备：已记住（本窗口专属 ✓）' % _v)

    def _load_saveimg_pref(self):
        """默认 **开**（用户就是要连刷也存图）；读不到偏好也当开 ✓"""
        v = self.prefs.load_save_img(default=True)
        self.saveimg_var.set(v)
        self.log('存图：%s（%s）'
                 % ('开 ✓' if v else '关',
                    '每张图存**进图首帧** runs/r_<时间>_0.png，≈0.7MB/图' if v
                    else '不存任何截图'))

    def toggle_saveimg(self):
        v = bool(self.saveimg_var.get())
        self.prefs.save_save_img(v)
        self.log('存图：%s %s' % (
            '开 ✓' if v else '关',
            '每张图存**进图首帧** runs/r_<时间>_0.png（最干净那张，≈0.7MB/图；不逐轮存）'
            if v else '不存任何截图'))

    def _stop_pref_path(self, which):
        return self.prefs.stop_path(which)

    #: 停止规则各开关的**出厂默认**（读不到配置时用它）
    #:
    #: ⭐⭐ 2026-10-17 用户口径（原话）：「预言石碑，只默认勾选**幸运**和**元素橙**」
    #:   ⇒ 幸运 ✓、元素·橙 ✓；**和平·宝箱怪 ✗、元素·紫 ✗**
    #:
    #: ⚠⚠ 这里是**唯一**该定义"初始勾选"的地方。
    #:   前两轮我把默认值分别写在 `_mk_stop_cb`（`value=`）和这里（`default=`），
    #:   而**后者会覆盖前者** ⇒ 改了不生效（截图里 4 个仍全勾）。
    #:   同一个坑连踩两次：**默认值只能有一处真相**。
    #:   `_mk_stop_cb` 的 `value=` 只在"var 尚未存在"时兜底，正常流程走不到，
    #:   所以真正起作用的永远是本表 ✓
    _STOP_DEFAULT = {'lucky': True, 'elem_orange': True,
                     'peace': False, 'elem_purple': False}

    def _load_stop_prefs(self):
        """默认 **开**（用户要的就是"遇到就停"）；读不到也当开 ✓"""
        for which, var, label in (('lucky', self.stop_lucky_var, '幸运(宝箱→四叶草)'),
                                  ('peace', self.stop_peace_var, '和平·金属宝箱怪'),
                                  # ⭐ 2026-10-09 用户：「预言石碑停止脚本加上橙色和紫色元素」
                                  ('elem_purple', self.stop_elem_purple_var, '元素·紫色'),
                                  ('elem_orange', self.stop_elem_orange_var, '元素·橙色')):
            v = self.prefs.load_stop(which, default=True)
            try:
                var.set(v)
            except Exception:       # noqa: BLE001
                pass
            self.log('预言石碑停脚本「%s」：%s' % (label, '停 ✓' if v else '不停（照常选它）'))

    def _save_stop_pref(self, which, var, label):
        v = bool(var.get())
        self.prefs.save_stop(which, v)
        self.log('预言石碑停脚本「%s」：%s（已落盘，下一局生效 ✓）'
                 % (label, '抽到就停 ✓' if v else '不停，照常选它并继续跑'))

    def toggle_stop_lucky(self):
        self._save_stop_pref('lucky', self.stop_lucky_var, '幸运(宝箱→四叶草)')

    def toggle_stop_peace(self):
        self._save_stop_pref('peace', self.stop_peace_var, '和平·金属宝箱怪')

    # ⭐⭐ 2026-10-09 用户口径：「预言石碑停止脚本加上橙色和紫色元素」✓
    #   「元素」= 地图中出现莱姆且至少某位阶：蓝(B) / 紫(A) / 橙(S)
    #   ⇒ 用户只要**紫+橙**；蓝档不停 ✓
    def toggle_stop_elem_purple(self):
        self._save_stop_pref('elem_purple', self.stop_elem_purple_var, '元素·紫色')

    def toggle_stop_elem_orange(self):
        self._save_stop_pref('elem_orange', self.stop_elem_orange_var, '元素·橙色')

    # ⛔⛔⛔ 2026-10-12 **整个「⑩ 锁定 + 解锁」段落已按用户要求删除** ✓
    #   用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」
    #   ---- 删掉了什么 ----
    #     `red_lock_file` / `_read_red_lock` / `show_red_lock` /
    #     `_refresh_lock_card` / `unlock_red` ＋ 类属性 `_KIND_TXT` ＋
    #     状态页那张「停脚本·保现场锁」卡与「红装已处理·解锁」按钮
    #   ---- 为什么 ----
    #     锁定是**额外的一层**（写锁 ⇒ 下次启动被拒 ⇒ 要人工解锁）；
    #     用户只要"**遇到就停**"这个动作 ⇒ 锁完全多余 ✗
    #     而且它**真卡过人**：`kind=shrine` 被报成"发现了红装"、
    #     `kind=foretell` 显示"未知类型" ⇒ 用户两次问「怎么解除锁定」✗
    #   ⇒ 现在：停脚本之后把现场留着，用户处理完**直接再点「开始」** ✓
    #   ⚠ `self._locked` / `self._sync_buttons()` 这两个**保留**（见别处）
    #     —— 它们还承载"运行中禁用按钮"的语义，与锁无关 ✓

    # ══════════════════════════════════════════════════════════════════
    # ⑪ 设备名 / 热更
    # ══════════════════════════════════════════════════════════════════
    def whoami(self, retry=1):
        """启动时自动显示「本窗口绑的是 MuMu 哪个实例」（用户 2026-09-25：写成实例名就能分辨）

        实例名 ↔ adb 端口来自 MuMu 自带的 `MuMuManager.exe info -v all`（见 mumu.py）：
        不用截图、不用 OCR，`127.0.0.1:16416` → 「幻少（安卓15.0，运行中）」。
        MuMuManager 偶尔第一次查不到（服务还没起好）→ 自动重试一次。
        ⚠ 老代码这里还有一句 `self.root.title(...)` —— 它会**覆写掉标题里的热更信息** ✗（P8）；
          现在设备名只写顶栏标签，**标题归 `_title_text` 独占** ✓
        """
        self.dev.whoami_async(self.device, retry)
        # ⛔ 2026-10-12 删掉 `self.show_red_lock()`（锁机制已删 ✓）
        self._refresh_hot_labels()

    def _refresh_about(self):
        """关于/更新页签：版本 + 热更状态 + 回滚历史（`hot/state.json` 可读化 ✓）"""
        try:
            ver = ''
            try:
                with open(os.path.join(HERE, 'PC_VERSION'), encoding='utf-8') as f:
                    ver = f.read().strip()
            except Exception:       # noqa: BLE001
                ver = '?'
            st = self.hot.load() or {}
            lines = ['程序版本：v%s（PC_VERSION）' % ver,
                     '热更状态：%s' % self.hot.status_line(),
                     '当前补丁：%s%s' % (st.get('applied') or '（无 · 出厂版）',
                                        '（已确认 ✓）' if st.get('confirmed')
                                        else ('（**待确认**）' if st.get('applied') else '')),
                     '启动尝试次数：%s' % st.get('bootAttempts', '—'),
                     '上次回滚：%s' % (st.get('rolledBack') or '无'),
                     '包目录：%s' % HERE]
            self.about_var.set('\n'.join(lines))
            # ⭐ 2026-10-18 方案 B：**不再把长串回填顶栏**（否则刷新一次就打回原形 ✗）
            #   顶栏那一格由 `_refresh_hot_labels()` 统一管（只显示极简补丁号）✓
            #   完整信息就在**上面那 6 行** `about_var` 里 ✓
        except Exception as e:      # noqa: BLE001
            try:
                self.about_var.set('（热更状态读取失败：%r）' % (e,))
            except Exception:       # noqa: BLE001
                pass

    def run_hotupdate(self, mode):
        """跑 `hotupdate.py check|hot|rollback|status`（**后台线程**，输出进日志 ✓）

        ⚠ `rollback` 会真的还原文件 ⇒ 先问一句；还原后**必须重启程序**才生效 ✓
        """
        if mode == 'rollback':
            try:
                if not messagebox.askyesno(
                        '回滚到出厂版',
                        '会把这台机器上的热更补丁**全部还原**成出厂版。\n\n'
                        '还原后需要**重新启动本程序**才生效。\n要继续吗？', parent=self.root):
                    return
            except Exception:       # noqa: BLE001
                pass

        def work():
            self.bgq.put('▶ hotupdate.py %s …' % mode)
            try:
                r = subprocess.run([PY, HOT_PY, mode], capture_output=True, text=True,
                                   timeout=300, creationflags=CNW,
                                   env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                            PYTHONUTF8='1'))
                for ln in ((r.stdout or '') + (r.stderr or '')).splitlines():
                    if ln.strip():
                        self.bgq.put('   ' + ln.rstrip())
                if mode == 'rollback':
                    self.bgq.put('⚠ 已回滚 ⇒ 请**关掉本窗口重新双击启动**才生效 ✓')
            except Exception as e:      # noqa: BLE001
                self.bgq.put('   ✗ 失败：%r' % (e,))
            self.bgq.put(('done', mode))
        threading.Thread(target=work, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    # ⑫ 关窗
    # ══════════════════════════════════════════════════════════════════
    def on_close(self):
        """关窗口时**顺手清掉自己的绑定**（用户 2026-09-25 要求）

        清两样：本窗口的单例锁 `.gui.lock`、本窗口实例的绑定 `<runs>/[tag/].lock`。
        这样下次「多开一个新号」就不会再看到"已被别的窗口绑定"的过期提示 ✓
        ⭐ 2026-09-27 修路径 bug：启动时写的单例锁在 `runs/<tag or 'default'>/.gui.lock`
          （见 `main()`），而这里原来清的是 `runs/.gui.lock` —— **根本不是同一个文件** ✗
          ⇒ 每次关窗都留下一个过期锁（虽然 `main()` 会查 PID 存活自愈，但会误导排查）。
        """
        try:
            for p in (os.path.join(LOG_DIR, self.tag or 'default', '.gui.lock'),
                      os.path.join(LOG_DIR, self.tag, '.lock') if self.tag
                      else os.path.join(LOG_DIR, '.lock')):
                if os.path.exists(p):
                    os.remove(p)
        except Exception:       # noqa: BLE001
            pass
        try:
            self.stop()
        except Exception:       # noqa: BLE001
            pass
        try:
            self.root.destroy()
        except Exception:       # noqa: BLE001
            pass


class _Tip:
    """极简悬浮提示（老 UI 定义了 tip 文本却**从未使用**过 —— P7 ✓ 现在真的用上了）

    ⚠ 自绘 `Toplevel` 而不是 `ttk` 的东西：**零依赖 + 无边框 + 跟随鼠标** ✓
    """

    def __init__(self, widget, text, delay=550):
        self.w, self.text, self.delay = widget, text, delay
        self.tip = None
        self.job = None
        widget.bind('<Enter>', self._enter, add='+')
        widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<ButtonPress>', self._leave, add='+')

    def _enter(self, _e=None):
        self._cancel()
        try:
            self.job = self.w.after(self.delay, self._show)
        except Exception:       # noqa: BLE001
            self.job = None

    def _leave(self, _e=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        try:
            if self.job:
                self.w.after_cancel(self.job)
        except Exception:       # noqa: BLE001
            pass
        self.job = None

    def _show(self):
        if self.tip or not self.text:
            return
        try:
            x = self.w.winfo_rootx() + 12
            y = self.w.winfo_rooty() + self.w.winfo_height() + 4
            t = tk.Toplevel(self.w)
            t.wm_overrideredirect(True)
            t.wm_geometry('+%d+%d' % (x, y))
            tk.Label(t, text=self.text, bg=theme.C_CARD, fg=theme.C_TEXT,
                     relief='solid', borderwidth=1, font=theme.FONT_HINT,
                     justify='left').pack()
            self.tip = t
        except Exception:       # noqa: BLE001
            self.tip = None

    def _hide(self):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:       # noqa: BLE001
                pass
        self.tip = None


RES_OK = (720, 1280)          # ⭐ PC 端锁定分辨率（用户口径：不是这个就不许启动 ✓）


def _screen_size(device):
    """用 adb `wm size` 取设备分辨率 ⇒ (w, h) ｜ None（拿不到返回 None ✓）

    ⚠ 输出里可能同时有 `Physical size` 和 `Override size` ⇒ **优先 Override** ✓
      （Override 才是当前生效的显示尺寸 ✓）
    """
    try:
        out = subprocess.run([ADB, '-s', str(device), 'shell', 'wm size'],
                             capture_output=True, text=True, timeout=15,
                             creationflags=CNW).stdout or ''
    except Exception:       # noqa: BLE001
        return None
    for key in ('Override size', 'Physical size'):
        m = re.search(re.escape(key) + r'[:：]?\s*(\d+)\s*x\s*(\d+)', out)
        if m:
            return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+)\s*x\s*(\d+)', out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _set_window_icon(root):
    """给窗口装上「机甲核心魔偶」的像素头像（缺图标也不能影响启动）。

    ⚠ 为什么用 iconphoto 而不是 iconbitmap：
       `iconbitmap` 要 .ico 且是 Windows 专有；`iconphoto` 吃 PNG，跨平台且更省事。
    ⚠ 为什么先放大 4×：
       官方格只有 30×30，高 DPI 屏上窗口图标会被拉得极小；
       用 NEAREST 放大保住像素边缘（双线性会糊）。
    """
    try:
        from PIL import Image, ImageTk
    except Exception:           # noqa: BLE001
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [
        os.path.join(here, 'tools', 'launcher', 'head_M31302_000.png'),
        os.path.join(here, 'assets', 'head_M31302_000.png'),
        os.path.join(here, 'templates', 'ui', 'head_M31302_000.png'),
    ]
    src = next((p for p in cands if os.path.isfile(p)), None)
    if not src:
        return
    try:
        im = Image.open(src).convert('RGBA')
        im = im.resize((im.width * 4, im.height * 4), Image.NEAREST)
        root._mgas_icon = ImageTk.PhotoImage(im)      # 必须持引用，否则被 GC
        root.iconphoto(True, root._mgas_icon)
    except Exception:           # noqa: BLE001
        pass


def main():
    a = parse_args()
    tag = (a.tag or '').strip()

    # ⭐ 2026-10-02：**先选设备，再查锁**。
    #   原来顺序是「先按 tag 查锁 → 再建窗口」，而 tag 是**设备选择的结果**；
    #   多开选中第二台实例时 tag 才会变成 acc2 ⇒ 如果先查锁，
    #   用的还是选之前的空 tag（default），会拿「单开锁」去误判多开窗口重复 ✗
    device, tag = choose_device(a.device, tag)
    if not device:
        return                      # 用户取消 / 没启动 MuMu ⇒ 安静退出（已弹过提示）

    # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**启动窗口时就加个模拟器分辨率检测，
    #   不是正确的分辨率就不能启动**」⇒ 不是 720×1280 直接拒绝启动 ✓
    #   为什么必须拦：整套坐标/模板/阈值都是按 720×1280 标定的
    #     （PC 端锁定 720p 追求速度；别的分辨率下点哪都偏、模板全不中 ✗✗）
    #   读不到尺寸时给 3 次重试（adb 刚起来/实例刚开时可能还没就绪 ✓）
    # ⚠⚠ 先 `adb connect` 再检测 ✓ —— 实测：`127.0.0.1:16416` 在 connect 之前
    #   `wm size` **返回空** ⇒ 会被误判成"读不到分辨率"而拒绝启动 ✗
    try:
        subprocess.run([ADB, 'connect', str(device)], capture_output=True, text=True,
                       timeout=15, creationflags=CNW)
    except Exception:       # noqa: BLE001
        pass
    _sz = _screen_size(device)
    for _ in range(3):
        if _sz:
            break
        time.sleep(2.0)
        _sz = _screen_size(device)
    if _sz is None:
        _msg('幻想少女公会 · 自动探索',
             '读不到模拟器分辨率（adb 没连上？）\n\n'
             '请确认 MuMu 已经启动并登录游戏后重试；\n'
             '或先在 MuMu 里把分辨率设成 720×1280（竖屏）。', 'warn')
        return
    if tuple(_sz) != RES_OK:
        _msg('幻想少女公会 · 自动探索',
             '当前模拟器分辨率是 **%d×%d**，本工具只在 **720×1280（竖屏）** 下校准过，\n'
             '别的分辨率点哪都会偏、识别也不准 ⇒ 已拒绝启动。\n\n'
             '请在 MuMu 的「设置 → 显示 → 分辨率」里改成 720×1280 后重新双击启动。\n'
             '（改完记得让游戏界面对应重排：重进一次游戏更稳 ✓）'
             % (_sz[0], _sz[1]), 'warn')
        return

    # ⚠ 2026-09-25：同一实例**只允许开一个窗口**（重复开会得到没有窗口的僵尸进程，
    #   我之前反复重启攒了好几个）。已有活着的实例就直接退出并提示。
    lock = os.path.join(LOG_DIR, tag or 'default', '.gui.lock')
    if os.path.exists(lock):
        try:
            pid = int(open(lock, encoding='utf-8').read().strip() or 0)
        except Exception:       # noqa: BLE001
            pid = 0
        alive = False
        if pid:
            try:
                out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV'],
                                     capture_output=True, text=True, timeout=10,
                                     creationflags=CNW).stdout
                alive = str(pid) in out
            except Exception:   # noqa: BLE001
                alive = False
        if alive:
            # ⭐ 2026-09-28 修：原来这里只有 `print` —— 但窗口跑在 **pythonw.exe**
            #   （无 console）⇒ 提示进黑洞，用户重复双击时会看到"窗口一闪就没了"
            #   完全不知道为什么 ✗。改用系统弹窗，用户直接看得见。
            _txt = ('实例 %s 已经有一个窗口在跑了（PID %d），本窗口退出。\n\n'
                    '想同时跑两台设备请用左上的「多开一个新号」。' % (tag or '（单开）', pid))
            _msg('幻想少女公会 · 自动探索', _txt, 'info')
            return
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    try:
        with open(lock, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except Exception:           # noqa: BLE001
        pass
    if tag:                     # 多开：给自己放个标记，方便「多开」按钮判断端口占用
        os.makedirs(os.path.join(LOG_DIR, tag), exist_ok=True)
        try:
            open(os.path.join(LOG_DIR, tag, '.lock'), 'w').write(str(os.getpid()))
        except Exception:       # noqa: BLE001
            pass
    root = tk.Tk()
    _set_window_icon(root)          # ⭐ 窗口图标 = 机甲核心魔偶头像
    App(root, device=device, tag=tag)
    root.mainloop()
    try:
        os.remove(lock)
    except Exception:           # noqa: BLE001
        pass


if __name__ == '__main__':
    main()
