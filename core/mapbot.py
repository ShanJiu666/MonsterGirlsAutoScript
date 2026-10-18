# -*- coding: utf-8 -*-
"""mapbot core: MuMu ADB + Airtest + RapidOCR 封装。

用法:
    from mapbot import Bot
    bot = Bot()
    bot.snap()                     # 截图 -> runs/last.png
    pos = bot.find_text('进入地图')  # OCR 找文字 -> (x,y) | None
    bot.tap_text('进入地图')         # 点文字按钮
    bot.tap(540, 960)              # 绝对坐标
"""
import os
import subprocess
import sys
import time

# ⚠ 必须在 import airtest 之前设 —— airtest 的 ADB 包装类在 import 期就读它 ✗
#   本机 adb server 跑在 5038（不是默认 5037）；GUI 起子进程时会带这个变量，
#   但**手工跑脚本时没有** ⇒ 会连到空 server ⇒ "device not found" 这类怪错 ✗
#
# ⭐⭐⭐⭐ 2026-10-05 **勘误 + 真修**（用户报：「进图这一步出错（已跳过这张图）：
#   AdbError: adb.exe: device '127.0.0.1:16384' not found」，连着丢图）
#   ⚠ 上面那句注释**一直是错的**：本项目这版 airtest **从不读** `ANDROID_ADB_SERVER_PORT`
#     （`airtest/core/android/adb.py:_set_cmd_options`：`server_addr` 为 None 就**硬写 5037**，
#      全仓没有一处 `os.environ` 读它）⇒ 设这个环境变量**等于没设** ✗
#     而 `Android.__init__` 把 **URI 里的 host:port 当成 `server_addr`** 传下去
#     （`android.py:58`）⇒ 真正决定用哪个 adb server 的是 **URI 里的端口** ✓
#   ⇒ 本仓 URI 里写死 `127.0.0.1:5037` ⇒ bot **一直在跟 MuMu 自带的 5037 server 说话**
#     （抓到的子进程命令行铁证：`adb.exe -P 5037 -s 127.0.0.1:16416 shell …`）
#   ⇒ 而 5037 是 MuMu 自己的 server：模拟器一重启 / MuMu 工具一动，它的设备表就清空
#     ⇒ bot 拿到 `device not found` ⇒ 进图抛错 ⇒ **那张图被跳过**（体力照扣 ✗✗）
#   ⇒ 现在：① 端口**统一从 `ADB_PORT` 拼进 URI**（= 环境变量，默认 5038 = 我们自己的 server
#          ⇒ 与 MuMu 的 5037 隔离，它抖它的、不影响我们 ✓）
#        ② `adb_connect()`：连之前先 `adb -P <port> connect <host:port>` +
#          `wait-for-device`（我们自己的 server 一开始不认识这个设备，必须主动连 ✓）
#        ③ 进图报连接类错误时**重连再试一次**（见 `explore_loop.enter_with_retry`）✓
os.environ.setdefault('ANDROID_ADB_SERVER_PORT', '5038')   # 给子进程/其他工具留个一致的默认 ✓
ADB_PORT = int(os.environ.get('ANDROID_ADB_SERVER_PORT') or 5038)

# ⚠ 必须在 import airtest **之前**把本仓根目录加进 sys.path：
#   `mapbot.py` 可能被当作脚本从**别的目录**跑（`python D:\...\mapbot.py`、
#   或子进程 cwd 不在仓内）⇒ 否则 `import paths` 会 ModuleNotFoundError ✗
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from airtest.core.api import connect_device, snapshot, touch, swipe, keyevent, exists, Template
from airtest.core.cv import Template as CVTemplate
from rapidocr_onnxruntime import RapidOCR

import paths as P

# ⭐ 2026-10-02：全部改走 `paths.py`（仓内相对 + 仓外自动探测）。
#   原来写死 `<原项目目录>`（原项目目录）与
#   `<Android SDK>/adb.exe`（本机 SDK）⇒
#   **朋友机器上一条都不成立**，clone 完连 runs/ 都建不出来。
#   已实证仓内 templates/ 与原目录**逐个文件大小完全一致**（11177 个 / 24042578 字节），
#   所以改相对路径不会静默换成残缺模板 ✓
#   环境变量兜底：MAPBOT_ADB / MAPBOT_MUMU_HOME / MAPBOT_DATATABLE
ADB = P.ADB
DEV = '127.0.0.1:16384'
ROOT = P.ROOT
RUNS = P.RUNS
TPL = P.TPL
# ⚠ 从 GUI(pythonw，无控制台) 里调 adb.exe 会**每次弹一个黑窗口** —— 必须带这个标志
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
# ⭐⭐⭐⭐ 2026-10-06 极速截图**掉线自愈**（用户报「很慢」，根因是它**一次失败就永久退化**）
#   · 旧行为：`snap()`/`wait_change()`/`wait_stable()` 里**任何一次** `fast.grab()` 失败
#     （或返回 None）就把 `self.fast_ok = False` 一撸到底，**本次运行再也不试** ✗✗
#     ⇒ sidecar 只是**抖一下**（实测 `runs/sidecar_19999.log` 里 `adb connect` 子进程
#       偶发失败一次），之后它自己恢复了、真机探针 0.042s 正常，
#       可 bot **还在用 adb 截图 0.33 秒/张（慢 25 倍）**，而且**一行日志都没有** ✗
#   · 新行为：连续失败满 `FAST_MAX_FAIL` 次 ⇒ 关掉极速通道（退回 adb，**功能不受影响**），
#     但记下 `fast_off_at`；`FAST_RETRY_SEC` 秒后**自动试一次**（成功了就切回来 ✓）
#     ⇒ 抖动只损失一小段，不再赔掉整轮 ✓
#   · ⚠ 为什么要有"上限"再关：sidecar 真死掉时，**每帧都去 connect 一次**会白等
#     （`connect` 有 timeout）⇒ 必须**关掉 + 冷却**，不能无限重试 ✓
FAST_MAX_FAIL = 3            # 连续失败几次才判定"极速通道不可用"
FAST_RETRY_SEC = 30.0        # 关掉后多少秒再自动试一次（成功即切回）
# ⭐ OCR 前把图缩到多少倍（2026-09-25 实测 0.75：全屏 2.65s→1.54s 且识别率不掉）
OCR_SCALE = 0.75

_ocr_engine = None


def _stop_flag():
    """「用户点了停止」吗 —— 供**等待循环**做可中断判断（零回归 ✓）

    ⭐⭐ 2026-10-01 用户报「点 ■ 后还要运行一会」⇒ 真机实测请求→停止最长 **11.37 秒**，
      白等全在 `wait_change`/`wait_stable` 这些循环里（每次 0.6~3.0 秒 ✗）。
      · 端上：`explore_android.stop()` 会设 `explore_loop._ANDROID_STOP = True`
        （也是唯一权威来源 ✓）
      · PC：该名字根本不存在 ⇒ 恒 False ⇒ **行为一字不变** ✓
      · 拿不到模块（导入顺序/异常）⇒ 返回 False，绝不因为查询失败而误停 ✓
    """
    try:
        import sys as _sys
        _el = _sys.modules.get('explore_loop')
        if _el is None:
            return False
        return bool(getattr(_el, '_ANDROID_STOP', False))
    except Exception:       # noqa: BLE001
        return False


def _ocr():
    """OCR 引擎（单例）

    ⭐ 2026-09-25 提速：`use_cls=False` 关掉**文字方向分类**模型
      —— 游戏 UI 全是水平文字，方向分类纯属浪费；干净环境下实测快 ~10%，
      且识别结果与原配置**逐条一致**（`_ocr_bench.py` 复核过）。
      其余尝试都无效或更慢：det/rec 的 int8 动态量化被 PP-OCR 的图结构挡住（Conv 权重不是
      initializer ⇒ ORT 量化器直接报错）、`rec_batch_num` 调大反而慢一倍、
      裁剪画面也没用（det 本就会把输入缩放到固定尺寸）。
    """
    global _ocr_engine
    if _ocr_engine is None:
        try:
            _ocr_engine = RapidOCR(use_cls=False)
        except Exception:       # noqa: BLE001  老版本不认这个参数就退回默认
            _ocr_engine = RapidOCR()
    return _ocr_engine


# ─────────── 「居中弹窗系」的 PC 退化桩（⭐ v0.61） ───────────
#   弹窗（旅行商人 / 黄金宝库 / 战斗事件 / 探索产出…）在真机上锚**设备屏幕中心**，
#   与棋盘的「顶块锚顶 + 其余锚底」不是同一坐标系（真机 1280×2772 ⇒ 差 C≈209px）。
#   PC / 9:16 参考分辨率上没有这段平移（C=0，弹窗空间 == 参考系）⇒ 这两个函数退化为
#   恒等/零，**面板代码两端共用同一份** `dlg_items(...)` + `bot.tap_dlg(...)` 一条路径 ✓
#   （与 `Bot.tap_dlg` 的退化桩同一设计，见其上方注释）
def dlg_shift():
    """居中弹窗系 − 归一化帧 的 y 偏移 C。PC 恒 0（Android 版同名函数走 RefMapper）。"""
    return 0.0


def dlg_items(items):
    """归一化帧 OCR 条目 → 居中弹窗系（cy + C，其余原样）。PC 上 C=0 ⇒ 原列表直返。"""
    return items


def _is_conn_err(e):
    """是不是「与设备/模拟器的连接断了」这类错误（值得**重连重试**）？

    ⭐ 2026-10-04 真机：`ConnectionResetError [WinError 10054] 远程主机强迫关闭了一个
      现有的连接` 从 `touch()` 里抛出来 —— 模拟器把触摸通道踢了。
      这种**重连一次通常就好**，不该让整局崩掉。

    ⚠ 判据必须**只认连接类**：`ConnectionResetError`/`BrokenPipeError` 都是
      `ConnectionError` 的子类 ⇒ `isinstance` 就够了；字符串兜底是为了 airtest
      把异常包了一层（`AndroidError`/`AdbError`）时也能认出来。
      **绝不能写成 `except Exception` 就重试** —— 那会把逻辑错误也吞掉（静默乱点，更难查 ✗）
    """
    if isinstance(e, (ConnectionError, BrokenPipeError)):
        return True
    s = repr(e) + ' ' + str(e)
    # ⭐⭐⭐ 2026-10-05 补**真机那条真实消息**（原来永远匹配不上 ⇒ 白丢图 ✗）
    #   真机原文（用户 10-05 贴的）：`adb.exe: device '127.0.0.1:16384' not found`
    #   ⚠ 序列号**夹在 `device` 和 `not found` 中间** ⇒ 旧关键词 `'device not found'`
    #     是**连续子串**判据 ⇒ 一次都命不中 ✗（本轮修的进图重试就因此没生效 —— 门禁抓到的）
    #   ⇒ 改成**正则**（序列号可有可无、可带引号）✓
    try:
        import re as _re
        if _re.search(r"device\s+['\"]?[\w.:\-]+['\"]?\s*not found", s):
            return True
    except Exception:       # noqa: BLE001
        pass
    return any(k in s for k in ('ConnectionResetError', 'WinError 10054', 'WinError 10053',
                                'Broken pipe', 'Connection aborted', 'Connection refused',
                                'device not found', 'device offline', 'socket'))


def _dev_uri(dev, cap_method='ADBCAP'):
    """airtest 设备 URI —— **端口必须显式拼进去**（见 `ADB_PORT` 那段勘误）

    ⚠ `Android.__init__` 把这个 URI 的 host:port 当 `server_addr` ⇒ 这里写什么端口，
      bot 就跟哪个 adb server 说话。**别再写死 5037**（那是 MuMu 自己的 server ✗）
    """
    return 'Android://127.0.0.1:%d/%s?adb_path=%s&cap_method=%s' % (
        ADB_PORT, dev, ADB, cap_method)


def adb_connect(dev, port=None, wait=True, timeout=6.0):
    """确保 `dev` 挂在**我们自己的 adb server**（`ADB_PORT`）上

    为什么必须主动连：我们用的是 5038（不是 MuMu 的 5037），那台 server 是**我们自己**
    起的 ⇒ 它一开始**不认识**任何设备（`127.0.0.1:16384` 这种 TCP 设备要 `adb connect`
    才会登记 ✓；`emulator-5554` 这种由 server 自动发现，不用连 ✓）

    ⚠ 全程**尽力而为**（任何异常都吞掉，只返回 True/False）—— 连不上就让 airtest 自己去报错，
      别在这里改变原有语义（老路径行为不变 ✓）

    ⭐⭐⭐⭐ 2026-10-06 **用户报「启动时会闪过两次命令窗口」的真根因就在本函数** ✓
      · 本函数恰好起**两条**命令（`connect` + `wait-for-device`）⇒ **恰好闪两次** ✓
      · 机制：调用方 `explore_loop` 是 GUI 用 `creationflags=CNW` 起的，而 `PY=sys.executable`
        ⇒ GUI 跑在 `pythonw.exe`（**GUI 子系统**）时，循环进程**根本没有控制台**
        （不是"隐藏的控制台"，是 `GetConsoleWindow()==0` 且无控制台对象）
        ⇒ 它再调 `adb.exe`（**控制台程序**）时，Windows **必须为它新建一个控制台**
        ⇒ **默认可见** ⇒ 用户看到的"黑窗闪一下" ✗✗
      · **实测铁证**（`_tmpman/exp_conhost3.py`，父进程 pythonw 且**不带** CNW = 复现真实场景）：
          不带标志 ⇒ 新增 **2 个可见控制台窗口**（本机默认终端 = Windows Terminal
                       ⇒ 类名 `CASCADIA_HOSTING_WINDOW_CLASS`）
          带  CNW ⇒ 新增 **0 个** ✓
        ⚠⚠ 前两次实验都是**假象**，别再走回头路：
          · 用 WMI `Register-WmiEvent -Action` 数 conhost ⇒ `powershell -Command` 下
            **没有消息泵** ⇒ action 从不执行 ⇒ 数出 0（假的）✗
          · 用 `creationflags=CNW` 起 pythonw 父进程 ⇒ 它**有隐藏控制台**、子程序继承它
            ⇒ 也不弹（假阴性）✗ —— **父进程必须真的无控制台**才能复现 ✓
      · 所以这里**必须**带 `CREATE_NO_WINDOW`：这是**唯一的**修法
        （`CREATE_NO_WINDOW` 对 GUI 子系统子程序无害，且能阻止新建可见控制台 ✓）
    """
    port = int(port or ADB_PORT)
    ok = False
    try:
        if ':' in str(dev):                 # 只有 host:port 形式才需要 connect
            subprocess.run([ADB, '-P', str(port), 'connect', str(dev)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=False,
                           creationflags=CREATE_NO_WINDOW)      # ⭐ 别删（见上）
        if wait:
            subprocess.run([ADB, '-P', str(port), '-s', str(dev), 'wait-for-device'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=False,
                           creationflags=CREATE_NO_WINDOW)      # ⭐ 别删（见上）
        ok = True
    except Exception:       # noqa: BLE001
        pass
    return ok


class Bot:
    ocr_grabs = False        # ⭐ v0.61：`ocr()` 会不会**自己重新取帧**？
    #   PC = False（`ocr()` 用的是 `img()` 缓存的那一帧 ⇒ 必须先 `snap()` 再 OCR）
    #   Android = True（`ocr()` 走 `api.ocrJson`，内部自己抓当前帧；`band` 仍在 Python 侧过滤）
    #   buypanels 据此决定要不要多付一次 `snap()`（真机上一次 toRef+PNG ≈ 0.3s）

    def __init__(self, log_prefix='run', serial=None, tag=None, use_fast=True):
        """serial = adb 设备号（多开时一个模拟器一个）；tag = 实例名（隔离截图/日志目录）

        多开：MuMu 多开器的实例端口一般是 16384 / 16416 / 16448 …
              （`adb connect 127.0.0.1:16416` 连得上就说明第二实例在跑）
        不同 tag ⇒ 截图写进 `runs/<tag>/`，两边不会互相覆盖。

        use_fast：走 `fastcap`（MAA sidecar + MuMu 官方极速截图，0.02~0.06 秒/张）——
                  连不上 sidecar 就自动退回 adb 截图（0.24 秒/张），不影响功能。
        """
        self.dev = serial or DEV
        self.tag = tag or None
        self.runs = os.path.join(RUNS, self.tag) if self.tag else RUNS
        os.makedirs(self.runs, exist_ok=True)
        self.log_prefix = log_prefix
        self._seq = 0
        # ⭐⭐⭐ 2026-10-06 修 BUG-1：**帧号**（每拿到一张**新帧**就 +1）
        #   `explore_loop` 的三处"同帧缓存"（`_fx_frame_id` / `_cells_cached` /
        #   `_LAST_ITEMS` 复用）都拿 `b._snap_n` 当帧标识，而**本文件从来没有过这个属性**
        #   ⇒ `getattr(b,'_snap_n',None)` 恒 None ⇒ 两处带 `is not None` 守卫的判据
        #   **永远不命中**（空缓存、纯亏），而 `_fx_frame_id` 没有守卫 ⇒ 帧号恒定
        #   ⇒ `_FX_CACHE` **一旦缓存就永不失效**（跨帧返回陈旧模板结果 ✗）。
        #   ⚠ 自增点 = **每一处把 `_img_arr` 换成新帧的地方**（见下方 `_snap_n += 1` 注释），
        #     包括 `wait_change`/`wait_stable` 的轮询取帧（它们不经过 `snap()` ✓）。
        self._snap_n = 0
        self._img_arr = None            # 极速通道的当前帧（内存里，不落盘）
        self._img_path = None
        self.fast = None
        self.fast_ok = False
        # ⭐ 极速通道自愈状态（见 FAST_MAX_FAIL / FAST_RETRY_SEC 的说明）
        self._fast_fail = 0         # 连续失败计数（成功即清零 ✓）
        self._fast_off_at = 0.0     # 关掉的时刻（0 = 没关过）
        self._fast_retry_n = 0      # 自动重试了几次（统计/日志用）
        # ⭐ 耗时埋点（用户关心「时间花在哪」）：分类在 explore_loop 里另记 'classify'
        self.t = {'snap': 0.0, 'ocr': 0.0, 'wait': 0.0, 'wait_n': 0, 'tap': 0, 'ocr_n': 0}
        self.last_change = {'changed': None, 'dim': 1.0}
        if use_fast:
            try:
                import fastcap
                self.fast = fastcap.FastCap(self.dev)
                # 探一次：拿得到帧才算可用
                probe = self.fast.grab()
                if probe is not None and probe.size:
                    self._img_arr = probe
                    self._img_path = None
                    self._snap_n += 1       # ⭐ BUG-1：新帧 ⇒ 帧号 +1（下同）
                    self.fast_ok = True
            except Exception:       # noqa: BLE001
                self.fast = None
                self.fast_ok = False
        adb_connect(self.dev)               # ⭐ 先把它挂到**我们自己的** server 上（见 ADB_PORT ✓）
        connect_device(_dev_uri(self.dev))

    # ---------- 极速通道自愈 ----------
    def _fast_note_ok(self):
        """极速通道这一帧**成功** ⇒ 清零连续失败计数

        还要记一条"已切回极速"的日志（只在**真的从关着变回开着**时打一次，
        不刷屏 ✓）—— 否则用户永远不知道中途换过通道（旧代码就是这么静默的 ✗）
        """
        if self._fast_fail:
            self._fast_fail = 0
        if self._fast_off_at and self.fast_ok:
            self._fast_off_at = 0.0
            self._fast_log('✓ 极速截图**已恢复**（自动重试第 %d 次成功）'
                           '⇒ 截图回到 %.2f 秒/张' % (self._fast_retry_n, 0.02))

    def _fast_note_fail(self, why=''):
        """极速通道这一帧**失败** ⇒ 计数；连续满 FAST_MAX_FAIL 次才关（可自愈）

        ⚠ 为什么**不**一次就关（旧行为 ✗）：sidecar 偶发抖一下（实测 `adb connect`
          子进程失败一次）就把整轮赔进 adb 通道（慢 25 倍），而它几秒后就自己好了 ✗
        ⚠ 为什么**也**不能无限重试：sidecar 真死时每帧都 `connect` 会白等 timeout ⇒
          关掉 + 冷却 FAST_RETRY_SEC 后再试一次 ✓
        """
        self._fast_fail += 1
        if self.fast_ok and self._fast_fail < FAST_MAX_FAIL:
            return                      # 还在容忍范围内 ⇒ 下一帧继续试极速 ✓
        if self.fast_ok:
            self.fast_ok = False
            self._fast_off_at = time.time()
            self._fast_log('⚠ 极速截图连续失败 %d 次%s ⇒ 暂时退回 adb 截图'
                           '（%.2f 秒/张，**慢 25 倍**；%d 秒后自动重试 ✓）'
                           % (self._fast_fail, ('（%s）' % why) if why else '',
                              0.33, int(FAST_RETRY_SEC)))

    def _fast_try_revive(self):
        """被关掉且过了冷却 ⇒ 试着重连一次（成功则切回极速 ✓）

        返回 True = 现在可以用极速通道。**只在冷却到点时**才真的去 connect，
        所以 sidecar 真死时也只每 FAST_RETRY_SEC 秒白等一次 ✓
        """
        if self.fast is None:
            return False
        if not self._fast_off_at:
            return False
        if time.time() - self._fast_off_at < FAST_RETRY_SEC:
            return False
        self._fast_retry_n += 1
        self._fast_off_at = time.time()     # 先把冷却时钟推后，避免失败时每帧都试 ✗
        try:
            self.fast.close()               # 旧连接可能已半死 ⇒ 重连
        except Exception:                   # noqa: BLE001
            pass
        try:
            arr = self.fast.grab()
        except Exception:                   # noqa: BLE001
            arr = None
        if arr is not None and getattr(arr, 'size', 0):
            self.fast_ok = True
            self._fast_fail = 0
            self._img_arr = arr
            self._img_path = None
            self._snap_n += 1               # ⭐ BUG-1：复活时也是一张新帧 ✓
            self._fast_log('✓ 极速截图**已恢复**（自动重试第 %d 次成功）'
                           '⇒ 截图回到 %.2f 秒/张' % (self._fast_retry_n, 0.02))
            return True
        return False

    @staticmethod
    def _fast_log(msg):
        """打一行极速通道日志（走 explore_loop.say ⇒ 进 GUI 日志；拿不到就 stdout）

        ⚠ 用延迟 import 避免 mapbot ←→ explore_loop 的循环导入 ✓
        """
        try:
            import explore_loop as _el
            _el.say('   · %s' % msg)
        except Exception:                   # noqa: BLE001
            try:
                print('   · %s' % msg, flush=True)
            except Exception:               # noqa: BLE001
                pass

    # ---------- 截图 ----------
    def snap(self, name=None, save=False):
        """截图

        优先 `fastcap`（MAA sidecar → MuMu 官方极速截图 0.02~0.06s，帧留在内存不落盘，
        要靠 adb 的 0.24s）；失败自动退回 `adb exec-out screencap -p`（再失败退 airtest）。
        `save=True` 时才把当前帧写进 `runs/<name>.png`（调试/取证用）。
        """
        self._seq += 1
        name = name or f'{self.log_prefix}_{self._seq:04d}'
        p = os.path.join(self.runs, name + '.png')
        _t0 = time.time()
        # ⭐ 被关掉且冷却到了 ⇒ 先试着复活（成功则本帧就走极速 ✓）
        if not self.fast_ok and self._fast_try_revive():
            pass
        if self.fast_ok:
            try:
                arr = self.fast.grab()
            except Exception:       # noqa: BLE001
                arr = None
            if arr is not None and arr.size:
                self._fast_note_ok()
                self._img_arr = arr
                self._img_path = None
                self._snap_n += 1           # ⭐ BUG-1：极速通道新帧 ⇒ 帧号 +1 ✓
                self._last = p
                if save:
                    cv2.imencode('.png', arr)[1].tofile(p)
                    self._img_path = p
                self.t['snap'] += time.time() - _t0
                return p
            # ⚠ 旧代码这里写死 `self.fast_ok = False`（**一次就永久退化** ✗）
            #   ⇒ 改成计数 + 冷却 + 自动重试（见 FAST_MAX_FAIL / _fast_note_fail ✓）
            self._fast_note_fail('snap')
        ok = False
        try:
            with open(p, 'wb') as f:
                subprocess.run([ADB, '-s', self.dev, 'exec-out', 'screencap', '-p'],
                               stdout=f, check=True, timeout=15,
                               creationflags=CREATE_NO_WINDOW)
            ok = os.path.getsize(p) > 10000
        except Exception:      # noqa: BLE001
            ok = False
        if not ok:
            try:
                snapshot(filename=p, quality=99)
            except Exception:       # noqa: BLE001
                pass
            ok = os.path.exists(p) and os.path.getsize(p) > 10000
        # ⭐⭐⭐ 2026-10-02 修**空帧 ⇒ 整个循环崩溃**（真机 crash log 实证）
        #   症状：`cv2.error: (-215) !buf.empty() in cv::imdecode_`，栈是
        #        `finish_map → b.ocr → Bot.img → cv2.imdecode`
        #        根因：adb `exec-out screencap` 与 airtest `snapshot` **双双失败**时，
        #        这里**照样** `self._img_path = p` 留下一个**空/半截文件**，
        #        下一个 `img()` 读到空 buffer ⇒ 直接抛异常 ⇒ 整个循环退出（退出码 1）。
        #        ⚠ 旧代码 `ok` 只用于「要不要退回 airtest」，**从不校验最终结果**。
        #   ⇒ 现在：**重试 2 次**（截图偶发失败很常见，MuMu 切图/动画期高发），
        #     仍失败则抛**带诊断信息**的异常，而不是留一个空文件让下游崩。
        for _try in range(2):
            if ok:
                break
            try:
                with open(p, 'wb') as f:
                    subprocess.run([ADB, '-s', self.dev, 'exec-out',
                                    'screencap', '-p'],
                                   stdout=f, check=True, timeout=15,
                                   creationflags=CREATE_NO_WINDOW)
            except Exception:      # noqa: BLE001
                pass
            ok = os.path.exists(p) and os.path.getsize(p) > 10000
            if not ok:
                time.sleep(0.4)   # 稍等再试（动画/切图瞬间容易抓空）
        if not ok:
            try:
                os.remove(p)     # 别留空文件骗下游 ✓
            except OSError:
                pass
            self._img_arr = None
            self._img_path = None
            self._last = None
            # ⚠ 这里**不再**关极速通道：本路径是 **adb + airtest 双双失败**，
            #   极速通道压根没被问到 ⇒ 拿它顶罪没有依据 ✗（旧代码写死 `fast_ok=False`）
            #   ⇒ 下一轮仍会先试极速（它可能好着）；真不行它自己会按计数关掉 ✓
            self.t['snap'] += time.time() - _t0
            raise RuntimeError(
                '截图失败（已重试 2 次）：adb exec-out 与 airtest 都拿不到帧。'
                '设备=%s  adb=%s  —— 多半是模拟器卡住/切图动画期/adb server 掉线'
                % (self.dev, ADB))
        self._img_arr = None
        self._img_path = p
        self._last = p
        # ⭐ BUG-1：adb/airtest 路径也拿到了**新帧**（在磁盘上，`img()` 会去解码）
        #   ⇒ 帧号必须 +1，否则"上一张内存帧"的缓存会被当成这一帧的答案 ✗
        self._snap_n += 1
        self.t['snap'] += time.time() - _t0
        return p

    def wait_change(self, max_sec=1.5, band=(130, 1700), thr=3.0, interval=0.06,
                    min_sec=0.22, around=None, radius=260):
        """等画面发生变化（极速截图轮询）—— 用来代替点击后的固定 sleep

        `around=(x, y)` 时**只看点击点周围 ±radius 的区域** —— ⭐ 2026-09-25 关键修正：
        整屏平均变化对「局部揭一格」不敏感（均值被大片不变区域稀释），于是每次都白等满
        1.3 秒；改成看局部后，揭格/弹面板都能在 0.3~0.6 秒内被发现 ⇒ 每次点击省 ~0.7 秒。
        变化幅度超过 `thr` 就立刻返回 True；`max_sec` 到点还没变就返回 False。
        没有极速截图时退化成 `time.sleep(min(max_sec, 1.2))`。
        """
        if not self.fast_ok:
            # ⭐ 冷却到了 ⇒ 试着复活一次（成功就继续走下面的轮询 ✓）
            if not self._fast_try_revive():
                time.sleep(min(max_sec, 1.2))
                return False
        _wt0 = time.time()
        ref = self._img_arr
        t0 = time.time()
        if ref is None:
            time.sleep(min_sec)
            return False
        if around:
            x, y = int(around[0]), int(around[1])
            x0, x1 = max(0, x - radius), min(ref.shape[1], x + radius)
            y0, y1 = max(0, y - radius), min(ref.shape[0], y + radius)
        else:
            y0, y1 = band
            x0, x1 = 0, ref.shape[1]
        refb = ref[y0:y1, x0:x1]
        # ⚠⚠ 2026-10-02 修「PC 端用不了」（GUI 日志 gui_20261002_013006.log 崩在这里）：
        #   上面 `band` / `around+radius` 切出来的 `refb` **可能是空片**（y0>=y1 或 x0>=x1），
        #   原实现直接 `.mean()` ⇒ 抛 `RuntimeWarning: Mean of empty slice`，
        #   且 numpy 对空数组返回 **nan** ⇒ `nan >= thr` 恒 False ⇒ **每次都在这里白等到
        #   max_sec 超时**，等变化失败 → 调用方连锁空转 → 整条循环退出码 1 ✗。
        #   ⚠ 这条不会抛异常（只是 nan），所以以前一直**静默失效**，只在 GUI 日志里留下
        #     两行 warning，肉眼极难发现。
        #   ⇒ 空片直接判定「没法比」：按"没等到变化"处理并立刻返回，绝不 nan 流入比较 ✓
        if refb.size == 0:
            self.last_change = {'changed': False, 'dim': 1.0, 'empty_band': True,
                                'band': (y0, y1, x0, x1)}
            return False
        # ⭐ 同时记录棋盘区域（**720×1280 参考系** y 668~1148）的**亮度比**：
        #   弹面板必然给棋盘压暗（未揭示格 = ×0.65，实测；面板遮罩同理）
        #   ⇒ 没变暗就说明只是揭了个格
        # ⚠ 2026-10-02 换基准修：原来写死 `(1002, 1722)`（1080×1920 系），
        #   在 720×1280 上 **y0=1002 已接近屏底、y1=1722 越界** ⇒ 切片几乎全黑
        #   ⇒ `ref_luma` 恒定 ⇒ **`dim` 压暗判定静默失效**（面板盖住棋盘也认不出）✗
        #   ⇒ 改为从 `layout.REF` 取（与 marks/spots 同一数据源）✓
        import layout as _lay
        _gx0, _gy0 = _lay.REF['grid_x0'], _lay.REF['grid_y0']
        _gcx, _gcy = _lay.REF['grid_cx'], _lay.REF['grid_cy']
        _br = (int(_gy0), int(_gy0 + 5 * _gcy))
        ref_luma = float(cv2.cvtColor(ref[_br[0]:_br[1]], cv2.COLOR_BGR2GRAY).mean())
        if not (ref_luma == ref_luma):        # nan 兜底（空片时上面已挡；这里防其它 nan 源）
            ref_luma = 0.0
        self.last_change = {'changed': False, 'dim': 1.0}
        while time.time() - t0 < max_sec:
            time.sleep(interval)
            # ⭐⭐ 2026-10-01 停止可中断（用户报「点 ■ 后还要运行一会」）：
            #   真机实测请求→停止最长 **11.37 秒**，白等的来源就是这些 wait 循环
            #   （一次 0.6~3.0 秒，战斗/结算里连续叠几次就是十几秒 ✗）
            #   ⇒ 每次轮询（interval≈0.06s）顺便问一次「收到停止了吗」，
            #     收到就**立刻返回**（调用方随即走 stop_checked 收工 ✓）代价≈0 ✓
            if _stop_flag():
                self.last_change = {'changed': True, 'dim': 1.0, 'stopped': True}
                return True
            if time.time() - t0 < min_sec:
                continue
            arr = None
            try:
                arr = self.fast.grab()
            except Exception:       # noqa: BLE001
                arr = None
            if arr is None:
                # ⚠ 旧代码 `self.fast_ok = False`（一次就永久退化 ✗）
                #   ⇒ 计数 + 冷却 + 自动重试（见 FAST_MAX_FAIL / _fast_note_fail ✓）
                self._fast_note_fail('wait_change')
                return False
            self._fast_note_ok()
            self._img_arr = arr
            self._img_path = None
            self._snap_n += 1               # ⭐ BUG-1：轮询取到新帧也算新帧 ✓
            # ⚠⚠ 2026-10-02 同源修：帧尺寸可能变（分辨率被改 / 旋转 / sidecar 换源）。
            #   旧代码不校验就相减 ⇒ 抛异常被 except 吞成 d=99.0（**误判成"变了"**），
            #   而形状不同又可能让 numpy 广播出垃圾值。
            #   ⇒ 尺寸/形状对不上就**重新取基准**，保持语义正确（比不了就重来，别乱判）✓
            if arr.shape[:2] != ref.shape[:2]:
                ref = arr
                refb = ref[y0:y1, x0:x1]
                if refb.size == 0:
                    self.last_change = {'changed': False, 'dim': 1.0, 'empty_band': True}
                    return False
                continue
            try:
                d = float(np.abs(arr[y0:y1, x0:x1].astype(np.int16)
                                 - refb.astype(np.int16)).mean())
            except Exception:       # noqa: BLE001
                d = 99.0
            if not (d == d):        # ⚠ nan 兜底：nan >= thr 恒 False ⇒ 静默白等
                d = 99.0            #   宁可判定"变了"（让调用方往下走），也别卡死
            if d >= thr:
                try:
                    now_luma = float(cv2.cvtColor(arr[_br[0]:_br[1]],
                                                 cv2.COLOR_BGR2GRAY).mean())
                    _dim = (now_luma / ref_luma) if ref_luma else 1.0
                    # ⚠ 2026-10-02：nan 会顺着 dim 流进下游判据（面板压暗判定）
                    #   ⇒ 同样必须挡掉，兜底 1.0（= 没变暗）
                    if not (_dim == _dim):
                        _dim = 1.0
                    self.last_change = {'changed': True, 'dim': _dim}
                except Exception:       # noqa: BLE001
                    self.last_change = {'changed': True, 'dim': 1.0}
                self.t['wait'] += time.time() - _wt0
                self.t['wait_n'] += 1
                return True
        self.t['wait'] += time.time() - _wt0
        self.t['wait_n'] += 1
        return False

    def wait_stable(self, max_sec=3.0, interval=0.08, thr=1.6, need=2, band=(130, 1800)):
        """等画面**连续 need 帧几乎不变**（稳定）——用于「点完等奖励刷新完」这种场景

        ⚠ 2026-09-25 踩坑：`wait_change()` 是「一变就返回」，点在「确定」上时它会在
          奖励还没重绘完就返回 ⇒ 摇色子判定看不到大拇指（用户报「明明出了还继续摇」）。
          需要「看到最终画面」的地方一律用本函数：等它**停下来**再去识别。
        """
        if not self.fast_ok:
            # ⭐ 冷却到了 ⇒ 试着复活一次（成功就继续往下走 ✓）
            if not self._fast_try_revive():
                time.sleep(min(max_sec, 1.2))
                return False
        y0, y1 = band
        t0 = time.time()
        prev = None
        stable = 0
        while time.time() - t0 < max_sec:
            time.sleep(interval)
            # ⭐⭐ 2026-10-01 停止可中断（同 wait_change，用户报「点 ■ 后还要运行一会」✓）
            if _stop_flag():
                return True
            try:
                arr = self.fast.grab()
            except Exception:       # noqa: BLE001
                arr = None
            if arr is None:
                # ⚠ 旧代码一次就永久退化 ✗ ⇒ 计数 + 冷却 + 自动重试 ✓
                self._fast_note_fail('wait_stable')
                return False
            self._fast_note_ok()
            self._img_arr = arr
            self._img_path = None
            self._snap_n += 1               # ⭐ BUG-1：轮询取到新帧也算新帧 ✓
            cur = arr[y0:y1]
            if prev is not None:
                try:
                    d = float(np.abs(cur.astype(np.int16)
                                     - prev.astype(np.int16)).mean())
                except Exception:   # noqa: BLE001
                    d = 99.0
                if d <= thr:
                    stable += 1
                    if stable >= need:
                        return True
                else:
                    stable = 0
            prev = cur
        return False

    def board_luma(self, img=None):
        """棋盘区域平均亮度 —— 用来判断「是不是盖着面板」（面板遮罩会把棋盘压暗 ~35%）

        ⚠ 用**相对比较**（跟上一轮的值比），不用绝对阈值（不同地图底色差很多）
        """
        im = img if img is not None else self._img_arr
        if im is None:
            return None
        try:
            # ⚠ 2026-10-02 换基准修：原来写死 `im[1002:1722]`（1080p 系），
            #   720×1280 上 y1 越界 ⇒ 切片几乎全黑 ⇒ 亮度均值失真 ✗
            import layout as _lay1
            _by = int(_lay1.REF['grid_y0'])
            _bb = _by + 5 * int(_lay1.REF['grid_cy'])
            return float(cv2.cvtColor(im[_by:_bb], cv2.COLOR_BGR2GRAY).mean())
        except Exception:       # noqa: BLE001
            return None

    def last_img(self):
        return getattr(self, '_img', None) or self.img()

    def last(self):
        """最近一帧的**磁盘路径**；极速通道下帧只在内存 ⇒ 需要路径时才落盘一次"""
        if self._img_path:
            return self._img_path
        if self._img_arr is not None and getattr(self, '_last', None):
            try:
                cv2.imencode('.png', self._img_arr)[1].tofile(self._last)
                self._img_path = self._last
            except Exception:       # noqa: BLE001
                return None
            return self._img_path
        return getattr(self, '_last', None)

    def img(self):
        """取当前帧（内存优先；否则走 `last()`/`snap()`）✓

        ⭐ 2026-10-02 加**空帧守卫**：`_img_arr` 为空 / 落盘文件是 0 字节时
           **重新抓一帧**再试一次，而不是把空 buffer 丢给 `cv2.imdecode`
           （那会抛 `(-215) !buf.empty()` 把整个循环打挂，见 `snap()` 里的长注释）。
        """
        if self._img_arr is not None and getattr(self._img_arr, 'size', 0):
            return self._img_arr
        p = self.last()
        if p and os.path.exists(p) and os.path.getsize(p) > 1000:
            im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if im is not None and im.size:
                return im
        # ↓ 落盘帧不可用（None / 空文件 / 解不出）⇒ 重新抓
        p = self.snap()          # 失败会抛带诊断的 RuntimeError（不再静默留空文件）
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None or not im.size:
            raise RuntimeError('截图解码失败（文件非空但解不出图）：%s' % p)
        return im

    # ⭐ v0.61：弹窗帧。PC 上弹窗空间 == 参考系 ⇒ 与 `img()` 等价（Android 版才真的重投影）。
    #   这样 buypanels 的图标模板匹配可以两端共用 `bot.img_dlg()` 一条路径 ✓
    def img_dlg(self):
        return self.img()

    # ---------- OCR ----------
    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        """OCR；band=(y0, y1) 时**只 OCR 这一段**（快 3 倍），返回的坐标仍然是全屏坐标

        实测：全屏 2.47s / 中段 y150-900 只要 0.79s。面板标题、按钮、选项都在中段，
        所以「点一下看弹没弹面板」这种热路径一律用 band。

        ⭐ 2026-09-25 再提速：默认把图缩到 **0.75 倍**再喂给 OCR（`OCR_SCALE`）。
        实测（真实截图，含面板）：
            全屏 1.00x → 2.65s / 43 条；**0.75x → 1.54s / 38 条**（关键文字全在，
            甚至比 1.0x 多认出一个「开始战斗」）；0.60x → 1.35s（仍可用，但余量变小）
        游戏字号大，0.75 倍不掉识别率；坐标会按比例换算回全屏。
        """
        im = img if img is not None else self.img()
        # ⭐ 2026-09-27 分辨率自适应：让喂给 OCR 的图**宽度恒定 ≈810px**（=0.75×1080 ✓）
        #   原来固定 0.75 ✗ ⇒ 720p 下只有 540px 宽 ⇒ 小字（商人面板等）认不到 ✗
        #   ⚠ 必须在 im 赋值**之后**算 ✗（放前面会 NameError ⇒ 一启动就停 ✗）
        if scale is None:
            _w = im.shape[1] if im is not None else 1080
            sc = OCR_SCALE * (1080.0 / float(_w)) if _w else OCR_SCALE
        else:
            sc = float(scale)
        _ot0 = time.time()
        y0 = 0
        if band:
            y0, y1 = int(band[0]), int(band[1])
            im = im[max(0, y0):y1]
            if im.size == 0:
                return []
        if sc != 1.0:
            im = cv2.resize(im, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        # ⭐⭐⭐⭐⭐ 2026-10-18 **直接把 ndarray 交给 OCR，不再「编码成 PNG 落盘再读回来」**
        #   ---- 病（改前每一轮 OCR 都在白花）----
        #     `cv2.imencode(""".png""")` + `buf.tofile(tmp)` ⇒ 再让 RapidOCR
        #     用 `Image.open(tmp)` **从磁盘读回来**：一次完整 PNG 编码 + 一次完整解码，
        #     纯为传参（这个临时文件**没有任何别的消费者**：全仓只有注释提到过它）✗
        #   ---- 实测（720×1280 真机帧，本机，热引擎，12 次交替调用抵消预热漂移）----
        #     走 PNG 文件 **0.912 s/次** ｜ 直接 ndarray **0.754 s/次** ⇒ **省 0.158 s/次（17%）**
        #     一次跑图有 **几十次** OCR（真机分账 round 82 次 / pre 73 次只在 5 张图上就 345 次）
        #     ⇒ 每张图省 **1~4 秒**，而且**完全不给游戏端多加一次 I/O** ✓
        #   ---- 为什么安全（读的是已安装版本的真实源码，不是猜）----
        #     `rapidocr_onnxruntime.utils.LoadImage.__call__` 接受 `np.ndarray`，
        #     且 `convert_img()` 对 ndarray 的处理是：**原样返回**（不转通道）——
        #     从文件读时它才做 `RGB→BGR` 转换。而本函数的 `im` 本来
        #     就是 **cv2 解出来的 BGR**（`img()` → `imdecode(..., IMREAD_COLOR)`），
        #     **与从 PNG 读回来的结果同色序** ⇒ 两条路的输入逐像素相同 ✓
        #   ---- 实测证据（不是推理）----
        #     12 次对照：**文字 + 四个角点逐条完全一致，不一致 0/12** ✓
        #     ⚠ 剩下的差别只有"不再产生 `runs/_ocr_tmp.png`"这一个副作用文件 ——
        #       而它**没有任何读取方**（`verify_panel_render.py` 的注释还特意写明
        #       "本门禁故意不用那张 _ocr_tmp.png"）⇒ 删掉它不破坏任何门禁 ✓
        #   ⚠ 保留 `self.t[""ocr""]`/分账计时口径不变（拿数对得上历史日志 ✓）
        res, _ = _ocr()(im)
        items = []
        inv = 1.0 / sc if sc else 1.0
        for it in (res or []):
            box, txt, conf = it[0], it[1], it[2]
            if conf < min_conf:
                continue
            xs = [q[0] * inv for q in box]
            ys = [q[1] * inv + y0 for q in box]
            items.append({'text': txt.strip(), 'cx': int(sum(xs)/4), 'cy': int(sum(ys)/4),
                          'x0': int(min(xs)), 'y0': int(min(ys)),
                          'x1': int(max(xs)), 'y1': int(max(ys)),
                          'conf': round(float(conf), 3)})
        items.sort(key=lambda d: (d['cy'], d['cx']))
        self.t['ocr'] += time.time() - _ot0
        self.t['ocr_n'] = self.t.get('ocr_n', 0) + 1
        if tag:                     # ⭐ 按来源分账（看 OCR 时间到底花在哪）
            cur = self.t.setdefault('ocr_by', {}).get(tag, [0.0, 0])
            self.t['ocr_by'][tag] = [cur[0] + (time.time() - _ot0), cur[1] + 1]
        return items

    def find_text(self, label, min_conf=0.5, near_y=None):
        """精确优先、部分匹配兜底；near_y 选同行的那个。"""
        items = self.ocr(min_conf=min_conf)
        return self._pick(items, label, near_y)

    @staticmethod
    def _pick(items, label, near_y=None):
        exact = [i for i in items if i['text'] == label]
        part = [i for i in items if label in i['text']]
        cands = exact or part
        if not cands:
            return None
        if near_y is not None:
            cands = sorted(cands, key=lambda i: abs(i['cy'] - near_y))
        return cands[0]

    # ---------- 模板匹配 ----------
    def find_tpl(self, tpl_name, threshold=0.85):
        t = CVTemplate(os.path.join(TPL, tpl_name), threshold=threshold)
        m = exists(t)
        return m  # None or coordinate

    def tap_tpl(self, tpl_name, threshold=0.85, wait=1.5):
        m = self.find_tpl(tpl_name, threshold)
        if m is None:
            return False
        touch(m)
        time.sleep(wait)
        return True

    # ---------- 操作 ----------
    def _touch_retry(self, x, y):
        """点一下；**触摸通道断了就重连再点一次**，别让整局崩掉

        ⭐ 2026-10-04 真机事故（用户报「领取后卡在返回界面」之后那次）：
          `runs/_crash.log` 铁证 —— 异常发生在 `touch()` 里：
              ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接
          而 `touch()` 原来**没有任何守卫** ⇒ 异常一路穿出 `finish_map` → `run_maps`
          → `main` ⇒ **整局退出码 1**（本来只是"这一下没点到"而已）✗✗

        ⚠ 只对**连接类**错误重连重试；其他异常（ValueError/TypeError…）**原样抛出** ——
          别把逻辑错误也吞掉（那会变成静默乱点，比崩还难查 ✗）
        """
        try:
            touch((x, y))
            return True
        except Exception as e:          # noqa: BLE001
            if not _is_conn_err(e):
                raise
            try:
                self.reconnect()
            except Exception:           # noqa: BLE001
                pass
            time.sleep(0.3)
            touch((x, y))               # 再点一次；再失败就抛给调用方（上层还有守卫）
            return True

    def reconnect(self):
        """重连 airtest 设备（触摸通道断了 / 设备瞬断以后用）

        ⭐⭐⭐⭐ 2026-10-05 加**真重连**：原来只 `connect_device()` —— 而 airtest 的
          `connect_device` 只会**重新绑一次 airtest 侧的对象**，**不会**把设备重新登记到
          adb server 上 ⇒ 设备真掉线（`device not found`）时它一点用都没有 ✗
          ⇒ 现在先 `adb_connect()`（`adb -P <port> connect <dev>` + `wait-for-device`），
            再 `connect_device()` ⇒ 设备瞬断能自愈 ✓
        """
        adb_connect(self.dev)
        connect_device(_dev_uri(self.dev))

    def tap(self, x, y, wait=1.2):
        # 点击轨迹：把每次点击落盘，便于事后定位「怎么会点到状态图标/说明文字」
        try:
            with open(os.path.join(RUNS, 'tap_trace.txt'), 'a', encoding='utf-8') as f:
                f.write('%s %d,%d\n' % (time.strftime('%H:%M:%S'), int(x), int(y)))
        except Exception:
            pass
        self._touch_retry(x, y)
        # ⭐ 极速截图可用时：**等画面真的变化**（变了立刻走），最多等 wait 秒
        #   —— 原来的死等 1.2~2.5 秒是单图耗时的大头（实测占 35~50 秒/图）
        #   返回 True/False = 画面有没有变（调用方可据此跳过后面那次昂贵的 OCR）
        changed = None
        if self.fast_ok and wait > 0:
            # 只看点击点周围（局部揭格/弹面板几毫秒就能发现，不用等满）
            changed = self.wait_change(wait, around=(x, y), thr=4.0)
        else:
            time.sleep(wait)
        return changed

    # ⭐ v0.31 方案 B（居中弹窗空间）：PC 上弹窗空间==参考系（1080×1920 无缩放）
    #   ⇒ 与 tap 完全等价。端上（mapbot.py Android 版）才真正换算（tapRefDialog）。
    #   这样 explore_loop 的面板代码可以两端共用 `b.tap_dlg(...)` 一条路径 ✓
    def tap_dlg(self, x, y, wait=1.2):
        return self.tap(x, y, wait=wait)

    def tap_text(self, label, wait=1.5, near_y=None, required=True):
        p = self.find_text(label, near_y=near_y)
        if p is None:
            if required:
                raise RuntimeError(f'找不到按钮: {label}')
            return None
        touch((p['cx'], p['cy']))
        time.sleep(wait)
        return (p['cx'], p['cy'])

    def swipe(self, x1, y1, x2, y2, ms=300, wait=1.2):
        swipe((x1, y1), (x2, y2), duration=ms)
        time.sleep(wait)

    def back(self, wait=1.5):
        keyevent('BACK')
        time.sleep(wait)

    # ---------- 便捷 ----------
    def wait_text(self, label, timeout=15, interval=1.2, required=True):
        t0 = time.time()
        while time.time() - t0 < timeout:
            p = self.find_text(label)
            if p:
                return p
            time.sleep(interval)
        if required:
            raise RuntimeError(f'等待 {label} 超时')
        return None

    def energy(self):
        """体力 149/2500 -> 149"""
        for it in self.ocr():
            if '/' in it['text'] and it['text'].replace('/', '').isdigit():
                return int(it['text'].split('/')[0])
        return None

    # ---------- 探索棋盘几何 ----------
    # ⚠⚠⚠ 2026-10-02 换基准修：这里还是 **1080×1920** 的 (36,1002,144)，
    #   而 PC 已锁定 **720×1280** ⇒ `tap_cell()` 会点在屏幕外（y0=1002 已在屏底）✗
    #   （`explore_loop` 走的是 `marks.cell_center`，没踩到；但这是给脚本用的公开入口，
    #     留着迟早被自己或朋友用到 ✗）
    #   ⇒ 单一数据源 = `layout.REF`（与 marks/spots 完全一致）✓
    #   历史标定（1080p 系，仅供追溯）：贴图设计 30x30 / 格距 32px × 缩放 4.5 = 144.0，
    #     棋盘左上 (36, 1002)；换 720p 后 = ×0.66667 ⇒ (24, 668, 96) ✓
    import layout as _lay0
    GRID_X0 = float(_lay0.REF['grid_x0'])      # 24.0
    GRID_Y0 = float(_lay0.REF['grid_y0'])      # 668.0
    GRID_CX = float(_lay0.REF['grid_cx'])      # 96.0
    GRID_CY = float(_lay0.REF['grid_cy'])      # 96.0
    COLS, ROWS = _lay0.REF['grid_cols'], _lay0.REF['grid_rows']

    def cell_center(self, row, col):
        x = self.GRID_X0 + (col + 0.5) * self.GRID_CX
        y = self.GRID_Y0 + (row + 0.5) * self.GRID_CY
        return (int(x), int(y))

    def tap_cell(self, row, col, wait=2.5):
        x, y = self.cell_center(row, col)
        self.tap(x, y, wait=wait)
        return (x, y)

    def sand_mask(self, img=None):
        """沙地/浅黄内容格的颜色掩码（BGR: R235-255 G195-245 B125-205）。"""
        im = img if img is not None else self.img()
        b, g, r = cv2.split(im)
        mask = ((r >= 235) & (r <= 255) & (g >= 195) & (g <= 245) &
                (b >= 125) & (b <= 205)).astype(np.uint8) * 255
        kernel = np.ones((5, 5), np.uint8)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    def sand_blobs(self, min_area=8000):
        """检测沙地色连通块 -> [(cx, cy, area, w, h)]（设施格/未消除内容格参考）。"""
        mask = self.sand_mask()
        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        out = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area >= min_area and 40 < w < 400 and 40 < h < 400:
                out.append((int(cents[i][0]), int(cents[i][1]), int(area), int(w), int(h)))
        out.sort(key=lambda t: (t[1] // 120, t[0]))
        return out

    # ---------- 内容格品质识别（2026-09-24 用户规则：紫色以上才处理） ----------
    @staticmethod
    def quality_at(img, cx, cy, rw=55, rh=45):
        """采样格子中心区域, 返回主内容色 'purple'|'gold'|'red'|'green'|'blue'|'none'。
        紫色 RGB ~ (170,120,215)（紫宝石/紫装）, 金/橙 ~ (250,190,80), 红 ~ (200,80,90),
        绿 ~ (130,215,128), 蓝 ~ (120,150,220)。"""
        win = img[max(0, cy-rh):cy+rh, max(0, cx-rw):cx+rw]
        if win.size == 0:
            return 'none'
        b, g, r = cv2.split(win.astype(int))
        purple = ((r > 130) & (b > 160) & (g < r - 25) & (g < b - 25)).mean()
        gold = ((r > 200) & (g > 130) & (g < 215) & (b < 110)).mean()
        red = ((r > 170) & (g < 110) & (b < 130)).mean()
        green = ((g > 170) & (g > r + 30) & (g > b + 30)).mean()
        blue = ((b > 170) & (b > r + 25) & (b > g + 25)).mean()
        scores = {'purple': purple, 'gold': gold, 'red': red,
                  'green': green, 'blue': blue}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0.10 else 'none'
