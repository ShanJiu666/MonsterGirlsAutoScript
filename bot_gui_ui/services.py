# -*- coding: utf-8 -*-
"""bot_gui_ui/services.py · 进程与配置服务层（UI 重设计 Step 3，2026-10-11）

为什么要把这层从 `bot_gui.py` 里拆出来
--------------------------------------
`bot_gui.py` 原来是一个 1150 行的**上帝类**（`App`），把布局、子进程管理、配置读写、
sidecar、多开、统计**全塞在一起** ⇒ 三宗罪（见 `docs/05-PC端UI重设计方案与开发规划.md` §3）：
  · **P3 线程不安全**：`ensure_sidecar` / `scan_screen` 在**工作线程里直接调 `self.log()`**
    去操作 Text 控件（没走 Queue）；`check()` / `spawn_multi` / `dedupe_loops` 更狠 ——
    在**主线程同步跑 subprocess**（adb 最多 10s × N）⇒ **UI 直接冻住** ✗
  · **P2 样式散落**；**P5 配置作用域不一致**。

本模块把这三类职责收成三个**不碰 tk 的**服务：
  · `LoopRunner`     —— 子进程全生命周期（命令行拼装 / env 注入 / 队列泵 / taskkill / 日志镜像）
  · `Prefs`          —— 所有配置文件的读写（路径与格式**逐字保持现状**，见规划 §5 约束 2）
  · `DeviceService`  —— 设备发现 / 环境检查 / 扫屏 / 多开 / 查重（**全部后台线程 + 事件队列**）

⭐⭐ 两条铁律（改这个文件前必读）
--------------------------------
1. **一行 tkinter 都不许 import**：本层要能被 headless 直接 import 并单测
   （门禁 `verify_gate.py` 的「关键模块可 import」就会 import `bot_gui.py`）。
2. **子进程命令行 / env 变量名 / 配置文件名与格式，逐字保持重写前的现状** ✗不许"顺手优化"：
   子进程（`explore_loop.py`）靠 **mtime 热读** `runs/target_types.json`，
   格式一变，**正在跑的循环会读错配置** ✗。
   ⇒ 拼装逻辑集中在 `LoopRunner.build_cmd()` / `build_env()` 两个函数里，
     并有 `_selftest_services.py` 拿 **git HEAD 版 `bot_gui.py` 的 `App.start()`**
     逐字对拍（见规划 §6 Step 3 的验收要求）。

线程模型（消灭 P3）
-------------------
    LoopRunner     ：reader 线程只往 `queue.Queue` 塞行；主线程 `drain()` 取
    DeviceService  ：每个动作起一个 daemon 线程干活，结果往 `queue.Queue` 塞**纯数据事件**；
                     主线程 `drain()` 取事件后才去弹窗/改界面
    ⇒ 任何地方都**不许**在非主线程里碰 tk 组件 ✓
"""
import json
import os
import queue
import subprocess
import threading
import time

# ⚠ 从 GUI(pythonw 无控制台) 里起子进程，必须带上这个标志，
#   否则每调一次 adb 就弹一个黑窗口（用户 2026-10-06 报「启动时会闪过两次命令窗口」）。
#   （`mapbot.py` 的 `adb_connect()` 与本文件所有 `subprocess.*` 都要带 ✓）
CNW = 0x08000000 if os.name == 'nt' else 0

# ⭐ airtest 的噪声行（原来在 `bot_gui.App.pump` 里过滤，逐字搬过来 ✓）
#   ⚠ 这些行**不写日志框**，也**不写日志文件**（原来就是 continue 掉的）
LOOP_NOISE = ('DEBUG', 'UserWarning', 'warnings.warn',
              '[INFO]<', '[ERROR]<airtest', 'airtest.core', 'airtest.utils')


def _is_noise(line):
    """是不是 airtest 的噪声行（要丢掉）"""
    try:
        return any(k in line for k in LOOP_NOISE)
    except Exception:       # noqa: BLE001
        return False


# ══════════════════════════════════════════════════════════════════════
# ① LoopRunner —— 子进程全生命周期
# ══════════════════════════════════════════════════════════════════════
class LoopRunner:
    """跑一次 `explore_loop.py`（本窗口同一时刻只允许一个 ⇒ 用 `is_running()` 挡）

    重写自 `bot_gui.App.start/stop/reader/pump/wait_stop`（**逻辑原样搬运**，
    只把 `self.log(...)` 换成"往队列塞事件" ✓）。

    事件协议（`drain()` 的产出，都是纯数据、供主线程消费）：
        ('line', str)     —— 一行输出（已滤掉 airtest 噪声）
        ('exit', rc)      —— 进程结束（**每次 run 只发一次** ✓）
    """

    def __init__(self, python, here, runs_dir, tag=''):
        self.python = python                    # venv 的 python.exe（= sys.executable）
        self.here = here                        # mapbot_pc 目录（cwd + explore_loop.py 所在）
        self.runs_dir = runs_dir                # runs/ 或 runs/<tag>/
        self.tag = tag or ''
        self.q = queue.Queue()
        self.proc = None
        self.logf = None                        # 子进程 stdout 镜像文件
        self._settled = False                   # 本次 run 的 exit 是否已发过
        self._force_next = False                # 用户确认"要和旧循环并存" ⇒ 下一次带 --force

    # ---------- 命令行 / env（⭐ 逐字对拍的重点）----------
    def logfile_path(self, when=None):
        """`runs/<tag>/gui_YYYYmmdd_HHMMSS[_tag].log`（与重写前逐字一致 ✓）"""
        ts = when or time.strftime('%Y%m%d_%H%M%S')
        return os.path.join(self.runs_dir, 'gui_%s%s.log'
                            % (ts, '_' + self.tag if self.tag else ''))

    def build_cmd(self, device, maps, bag_every=10, auto_supply=False,
                  force=False, solver=True):
        """拼子进程命令行（**顺序与取值必须与重写前 `App.start()` 逐字一致** ✓）

        重写前那份（`bot_gui.py` HEAD 版 :1295-1316）：
            [PY, <here>/explore_loop.py,
             '--max-round','45', '--maps',<maps>, '--deadline','420', '--no-dump',
             '--device',<dev>]
            + ['--tag',<tag>]                       （有 tag 时）
            + ['--force']                           （用户确认并存时）
            + ['--min-stamina', '50' if maps>10 else '25']
            + ['--bag-every', str(max(0,<窗口填的>))]
            + ['--no-solver']                       （⭐ 只有 solver=False 才加）
            + ['--auto-supply']                     （勾选时）

        ⚠ `--no-solver` 这条**从 2026-10-03 起永远不会被 GUI 加上**
          （用户口径：「精确规划按钮删掉，之后都一直是依赖规划」⇒ `solver` 恒 True ✓）；
          形参保留是为了**把这个口径写死在代码里**、并且对拍时能双向验证 ✓
        """
        cmd = [self.python, os.path.join(self.here, 'core', 'explore_loop.py'),
               '--max-round', '45', '--maps', str(maps),
               '--deadline', '420', '--no-dump',
               '--device', device]
        if self.tag:
            cmd += ['--tag', self.tag]
        if force:
            cmd += ['--force']
        # 连刷模式（maps 很大）：进图前体力 <50 就收工（用户 2026-09-25 口径 ✓）
        cmd += ['--min-stamina', '50' if maps > 10 else '25']
        try:
            _be = max(0, int(bag_every))
        except Exception:       # noqa: BLE001
            _be = 10
        cmd += ['--bag-every', str(_be)]
        if not solver:
            cmd += ['--no-solver']
        if auto_supply:
            cmd += ['--auto-supply']
        return cmd

    def build_env(self, base=None, save_first=True, stop_lucky=True,
                  stop_peace=True, stop_elem_purple=True, stop_elem_orange=True,
                  targets_cfg_path=None, guild_tasks=False, alchemy=False,
                  recruit=False, adfree=True):
        """拼子进程 env（**变量名与取值口径逐字不变** ✓）

        · `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`
          ⚠ Windows 下子进程 stdout 默认 **GBK(cp936)**，GUI 按 UTF-8 解 ⇒ 中文全乱码 ✗
        · `MAPBOT_SAVE_FIRST`              0/1（存图勾选 ✓）
        · `MAPBOT_STOP_LUCKY/PEACE/ELEM_*` 0/1（预言石碑四个停脚本开关 ✓）
          ⚠ 四个开关**读不到变量时子进程默认开**；GUI 侧读不到变量也**默认传 '1'** ✓
            （宁可停下来让人处理，也别错过 ✓）
        · ⭐⭐ 2026-10-14 新增两个（用户口径：「炼金和派遣勾选选项加在没体力自动用补给前面」）
            `MAPBOT_GUILD_TASKS` 0/1 ⇒ 收工后做**派遣任务**
            `MAPBOT_ALCH_AUTO`   0/1 ⇒ 收工后做**炼金**（会投满星）
          ⚠ 这两个**读不到 ⇒ 子进程默认关**（与上面四个开关**方向相反**，别抄错 ✗）
            理由：它们会**改游戏状态**、炼金还会**消耗满星装备** ⇒ 必须用户显式勾 ✓
        """
        env = dict(base if base is not None else os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        env['MAPBOT_SAVE_FIRST'] = '1' if save_first else '0'
        for _k, _v in (('MAPBOT_STOP_LUCKY', stop_lucky),
                       ('MAPBOT_STOP_PEACE', stop_peace),
                       ('MAPBOT_STOP_ELEM_PURPLE', stop_elem_purple),
                       ('MAPBOT_STOP_ELEM_ORANGE', stop_elem_orange)):
            env[_k] = '1' if _v else '0'
        env['MAPBOT_GUILD_TASKS'] = '1' if guild_tasks else '0'
        env['MAPBOT_ALCH_AUTO'] = '1' if alchemy else '0'
        env['MAPBOT_RECRUIT'] = '1' if recruit else '0'
        # ⭐⭐ 2026-10-15 **情报领奖**（用户口径：「接下来做点击情报领取奖励」
        #   ＋「每周情报也顺便点了」✓）
        #   ⚠ 它**没有独立勾选** —— 和派遣/炼金同属"公会日常"那颗勾选 ✓
        #     （纯领奖、零消耗 ⇒ 不需要单独授权 ✓）
        #   ⚠ 但**环境变量仍独立**：这样命令行可以只做情报不做别的 ✓
        env['MAPBOT_INTEL'] = '1' if guild_tasks else '0'
        # ⭐⭐⭐ 2026-10-15 **免广告**（用户口径：「单独加个有无免广的勾选，有就自动做」✓）
        #   ⚠ **它有自己的勾选**（不像情报那样并进公会日常）——
        #     因为它**不是公会日常**（广告领奖在 HUD 上就能做，不用进公会 ✓）
        env['MAPBOT_ADFREE'] = '1' if adfree else '0'
        # ⭐⭐⭐⭐⭐ 2026-10-13 **本设备**的特殊方块配置路径（用户口径：'和对应窗口绑定' ✓）
        #   子进程启动第一件事就 `targets_cfg.load(path=它)` ⇒ 之后全走它 ✓
        #   ⚠ 传空/None ⇒ **不设这个变量** ⇒ 子进程回落全局那份（老行为 ✓，不许崩 ✗）
        _tp = str(targets_cfg_path or '').strip()
        if _tp:
            env['MAPBOT_TARGETS_CFG'] = _tp
            try:
                os.makedirs(os.path.dirname(_tp), exist_ok=True)
            except Exception:       # noqa: BLE001
                pass
        return env

    # ---------- 生命周期 ----------
    def is_running(self):
        return self.proc is not None

    def start(self, device, maps, bag_every=10, auto_supply=False,
              save_first=True, stop_lucky=True, stop_peace=True,
              stop_elem_purple=True, stop_elem_orange=True, when=None,
              targets_cfg_path=None, guild_tasks=False, alchemy=False,
              recruit=False, adfree=True):
        """起子进程 ⇒ 返回 (logfile 路径, cmd, env)；失败 ⇒ (None, cmd, env)

        ⚠ 用户已确认「要和旧循环并存」⇒ 只有**这一次**带 `--force`（`_force_next` ✓）
        """
        if self.proc:
            return None, None, None
        force = bool(self._force_next)
        self._force_next = False
        cmd = self.build_cmd(device, maps, bag_every=bag_every,
                             auto_supply=auto_supply, force=force)
        env = self.build_env(save_first=save_first, stop_lucky=stop_lucky,
                             stop_peace=stop_peace,
                             stop_elem_purple=stop_elem_purple,
                             stop_elem_orange=stop_elem_orange,
                             guild_tasks=guild_tasks, alchemy=alchemy,
                             recruit=recruit, adfree=adfree,
                             targets_cfg_path=targets_cfg_path)
        os.makedirs(self.runs_dir, exist_ok=True)
        logfile = self.logfile_path(when)
        self._settled = False
        try:
            self.logf = open(logfile, 'w', encoding='utf-8', errors='replace')
        except Exception:       # noqa: BLE001  （打不开镜像文件也要能跑，只是不落盘 ✓）
            self.logf = None
        try:
            self.proc = subprocess.Popen(cmd, cwd=self.here, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True,
                                         encoding='utf-8', errors='replace', bufsize=1,
                                         env=env, creationflags=CNW)
        except Exception:       # noqa: BLE001
            self.proc = None
            self._close_logf()
            return None, cmd, env
        threading.Thread(target=self._reader, daemon=True).start()
        return logfile, cmd, env

    def _close_logf(self):
        try:
            if self.logf:
                self.logf.close()
        except Exception:       # noqa: BLE001
            pass
        self.logf = None

    def _reader(self):
        """reader 线程：只往队列塞（**绝不碰 UI** ✓ —— 修 P3）"""
        p = self.proc
        if p is None:
            return
        try:
            for line in p.stdout:
                self.q.put(('line', line))
        except Exception:       # noqa: BLE001
            pass
        try:
            rc = p.wait()
        except Exception:       # noqa: BLE001
            rc = -1
        # ⭐ 2026-09-28 加固：子进程退出**必须留痕**
        #   背景：21:36 那把循环打印「进图前体力」后无声消失 —— GUI 侧没有任何提示，
        #   事后无法判断是"正常收工"还是"崩了"✗。现在退出码必打；非 0 再指向
        #   `runs/<tag>/_crash.log`（explore_loop 顶层兜底写）✓
        self._emit_exit(rc, '⏹ 循环进程已退出（退出码 %s）%s'
                        % (rc, '' if rc == 0 else
                           '  ⚠ 非 0 ⇒ 多半是崩溃，查看 runs/_crash.log'))

    def _emit_exit(self, rc, text=None):
        """发一次 exit（**每次 run 恰好一次** ✓）"""
        if self._settled:
            return
        self._settled = True
        if text:
            self.q.put(('line', text + '\n'))
        self.q.put(('exit', rc))

    def stop(self):
        """`taskkill /F /T` 整树（重写前口径 ✓）；杀不掉再 `terminate()`

        ⚠ 被 `taskkill /F` 杀掉的进程没机会自己收尾 ⇒ 由 reader 线程 EOF 后发 exit ✓
        """
        if not self.proc:
            return False
        pid = self.proc.pid
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           capture_output=True, timeout=10, creationflags=CNW)
        except Exception:               # noqa: BLE001
            try:
                self.proc.terminate()
            except Exception:           # noqa: BLE001
                pass
        # ⚠ reader 线程可能因为管道被强杀而**迟迟不 EOF** ⇒ 1.2 秒后兜底补一条 exit
        #   （重写前是 `wait_stop` 那条线程；这里保持同样的"兜底"语义，
        #     但 exit **只发一次** —— 重写前会发两次 None ⇒ 统计打印两遍 ✗，已修 ✓）
        threading.Thread(target=self._late_settle, daemon=True).start()
        return True

    def _late_settle(self, delay=1.2):
        time.sleep(delay)
        self.q.put(('line', '（已停止；下面是截至停止时的统计）\n'))
        self._emit_exit(0)

    def drain(self, limit=400):
        """主线程调用：把队列里的事件取干净（**不阻塞** ✓）

        顺手把子进程原始输出镜像到 `gui_<ts>.log`（重写前在 pump 里做 ✓）。
        """
        out = []
        for _ in range(max(1, int(limit))):
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            if kind == 'line':
                if _is_noise(payload):
                    continue
                if self.logf:               # 镜像落盘（跟窗口显示同时 ✓）
                    try:
                        self.logf.write(payload)
                        self.logf.flush()
                    except Exception:       # noqa: BLE001
                        pass
            elif kind == 'exit':
                self._close_logf()
                self.proc = None            # 主线程据此判"跑完了" ✓
            out.append((kind, payload))
        return out

    # ⭐ 用户已确认「要和旧循环并存」⇒ 下一次 start 带 --force
    def mark_force_next(self):
        self._force_next = True


# ══════════════════════════════════════════════════════════════════════
# ② Prefs —— 配置文件读写（⭐ 路径与格式一个字都不许变）
# ══════════════════════════════════════════════════════════════════════
class Prefs:
    """`runs/` 下那一堆小配置文件（⭐ 2026-10-13 起**按设备端口隔离** ✓）

    ⭐⭐⭐⭐⭐ 2026-10-13 用户口径（原话）：
      「**把特殊方块，停止规则，多少张图自动升星等需要用户自己选择的自动用最近一次配置
        并且和对应窗口绑定（选哪个窗口就自动用对应的配置）**」✓

    ---- 改之前是什么（病）----
      全部偏好都在 **`runs/` 根**（一份，所有窗口共用）✗：
        · `.auto_supply` / `.save_img` / `.stop_*` ⇒ 全局
        · `target_types.json`（特殊方块）     ⇒ 全局
        · `每 N 张图升星`（`bag_every`）      ⇒ **根本没落盘**，每次开窗都是硬编码 `10` ✗
      ⇒ 开两个窗口（两个号）⇒ **勾选互相覆盖** ⇒ 你按 A 号的习惯勾的，B 号跟着变 ✗✗
      ⇒ 更糟：`bag_every` 连"最近一次"都记不住 ⇒ 每次重开都得手填 ✗

    ---- 现在（按**设备**绑定，不是按 tag）----
      ⚠⚠ 为什么**不用 `tag`**（`acc1/acc2`）：`devicesel.choose_device` 里
        **只开一台时 `tag=''`** ⇒ 按 tag 存会**全部落到"全局"** ⇒ 分不开 ✗✗
        （而"选哪个窗口就用对应配置"这个需求，单开场景**同样**要成立 ✓）
      ⇒ 键 = **设备端口**（`127.0.0.1:16448` → `16448`）—— 单开/多开都唯一 ✓
      ⇒ 目录：`runs/dev_<port>/`（与日志/统计的 `runs/<tag>/` **并列、互不干扰** ✓）

    ---- 迁移（老用户无感）----
      首次为某设备建目录时：`runs/` 根那份**全局**配置**复制过去**当初始值 ✓
        ⇒ 你原来的勾选**一个都不丢** ✓（而不是被重置成默认 ✗）
      ⚠ 只在**目标不存在**时复制 ⇒ 不会覆盖设备自己的配置 ✓
    """

    #: ⭐ 设备配置目录前缀（`runs/dev_16448/`）—— 与 `runs/acc1/` 明确区分 ✓
    DEV_PREFIX = 'dev_'

    def __init__(self, here, runs_dir, device='', root=None):
        self.here = here
        self.runs_dir = runs_dir        # per-tag 的日志目录（保留：老调用方仍传它 ✓）
        # ⭐⭐⭐ 2026-10-13 **`root` 显式可传**（原来写死 `here/runs` ⇒ 绕不过重定向 ✗）
        #   ---- 为什么必须可传（自检当场抓到）----
        #     自检把 `bot_gui.LOG_DIR` 改道到临时目录、`TC.cfg_path` 也改道了，
        #     可本类原来写死 `os.path.join(here, 'runs')` ⇒ **绕过重定向**
        #     ⇒ 自检**在真 `runs/` 下建了 `dev_16384/`** ✗✗（污染用户真目录）
        #   ⇒ 现在由调用方传**真正的 runs 根**（`LOG_DIR`）✓
        #   ⚠ 不传 ⇒ 回落 `here/runs`（老行为 ✓，命令行/老脚本不受影响 ✓）
        self.root_runs = str(root) if root else os.path.join(here, 'runs')
        # ---- ⭐ 本设备自己的配置目录（**挂在 `root_runs` 下** ⇒ 改道 `root_runs` 即可整体重定向 ✓）----
        self.device = str(device or '')
        self.dev_name = self._dev_name(self.device)

    # ---------- 路径 ----------
    @classmethod
    def _dev_name(cls, device):
        """`127.0.0.1:16448` → `dev_16448`；设备号拿不到 ⇒ `dev_unknown` ✓

        ⚠ 拿不到设备号时**退化成一个共用目录**（而不是报错）⇒ 老行为兜底、绝不崩 ✓
        """
        try:
            port = int(str(device).split(':')[-1])
            return '%s%d' % (cls.DEV_PREFIX, port)
        except Exception:       # noqa: BLE001
            return cls.DEV_PREFIX + 'unknown'

    def dev_root(self):
        """本设备配置目录 = `<root_runs>/dev_<port>` ✓

        ⚠ **挂在 `self.root_runs` 下**（不是 `self.here/runs`）—— 这样自检/测试把
          `root_runs` 改道到临时目录时，**本设备目录跟着一起走** ⇒ 不会污染真 `runs/` ✓
        """
        return os.path.join(self.root_runs, self.dev_name)

    def targets_path(self):
        """本设备的 `target_types.json` 全路径（**子进程必须读同一个** ✓）"""
        self._migrate_once()
        return os.path.join(self.dev_root(), 'target_types.json')

    def _migrate_once(self):
        """⭐ 首次建本设备目录 ⇒ 把 `runs/` 根那份**全局**配置复制过来当初始值 ✓

        ⚠⚠ **不能覆盖**设备自己的文件（只在目标不存在时复制 ✓）
        ⚠ 迁移的是**那一份文件**，不是整个目录（`runs/` 根还有日志/统计，别乱搬 ✗）
        ⚠ 失败**不抛**（迁移是锦上添花，失败了用默认值也能跑 ✓）
        """
        try:
            _dst = self.dev_root()
            if os.path.isdir(_dst):
                return
            os.makedirs(_dst, exist_ok=True)
            import shutil
            for _n in ('.auto_supply', '.save_img', '.bag_every',
                       '.stop_lucky', '.stop_peace',
                       '.stop_elem_purple', '.stop_elem_orange',
                       'target_types.json'):
                _src_p = os.path.join(self.root_runs, _n)
                _dst_p = os.path.join(_dst, _n)
                if os.path.exists(_src_p) and not os.path.exists(_dst_p):
                    try:
                        shutil.copyfile(_src_p, _dst_p)
                    except Exception:       # noqa: BLE001
                        pass
        except Exception:       # noqa: BLE001
            pass

    def _path(self, name):
        """本设备的偏好文件路径（**会顺手做一次迁移** ✓）"""
        self._migrate_once()
        return os.path.join(self.dev_root(), name)

    # ---------- 单值偏好（'1'/'0' 纯文本）----------
    def _read_flag(self, name, default):
        """读 '1'/'0' 单值文件；**读不到 / 内容不认识 ⇒ 用调用方给的 default** ✓

        ⚠ 两个方向的默认值**故意不同**（重写前口径，别顺手统一 ✗）：
          · `.auto_supply` default=False（别偷偷花道具）
          · `.save_img` / `.stop_*` default=True（宁可多存/宁可停下让人处理）
        """
        try:
            s = open(self._path(name), encoding='utf-8').read().strip()
        except Exception:       # noqa: BLE001
            return default
        if s == '1':
            return True
        if s == '0':
            return False
        return default

    def _write_flag(self, name, v):
        try:
            _p = self._path(name)
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            with open(_p, 'w', encoding='utf-8') as f:
                f.write('1' if v else '0')
            return True
        except Exception:       # noqa: BLE001
            return False

    def auto_supply_path(self):
        """`<runs>/dev_<port>/.auto_supply` ✓"""
        return self._path('.auto_supply')

    def save_img_path(self):
        """`<runs>/dev_<port>/.save_img` ✓"""
        return self._path('.save_img')

    def stop_path(self, which):
        """`<runs>/dev_<port>/.stop_<which>`（which ∈ lucky/peace/elem_purple/elem_orange ✓）"""
        return self._path('.stop_%s' % which)

    # ---------- ⭐ 每 N 张图升星（用户要"记住最近一次" ✓）----------
    def bag_every_path(self):
        """`<runs>/dev_<port>/.bag_every` ✓"""
        return self._path('.bag_every')

    def load_bag_every(self, default=10):
        """读"每 N 张图升星装备" ⇒ int（**读不到/坏值 ⇒ default** ✓）

        ⛔⛔ 改之前：这个值**根本没落盘** —— `bot_gui` 里写死 `tk.StringVar(value='10')`
          ⇒ 用户填了 `25`、关窗再开 ⇒ **变回 10** ✗✗（正是用户说的"要用最近一次配置"）
        """
        try:
            s = open(self.bag_every_path(), encoding='utf-8').read().strip()
            v = int(s)
            return max(0, v)
        except Exception:       # noqa: BLE001
            return max(0, int(default or 0))

    def save_bag_every(self, v):
        try:
            _p = self.bag_every_path()
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            with open(_p, 'w', encoding='utf-8') as f:
                f.write(str(max(0, int(v))))
            return True
        except Exception:       # noqa: BLE001
            return False

    def load_auto_supply(self, default=False):
        """读不到 ⇒ **关**（重写前口径 ✓：默认不用补给，别偷偷花道具 ✗）"""
        return self._read_flag('.auto_supply', default)

    def save_auto_supply(self, v):
        return self._write_flag('.auto_supply', bool(v))

    def load_save_img(self, default=True):
        """读不到 ⇒ **开**（重写前口径 ✓：用户就是要连刷也存图）"""
        return self._read_flag('.save_img', default)

    def save_save_img(self, v):
        return self._write_flag('.save_img', bool(v))

    # ---------- ⭐⭐ 2026-10-14 公会日常两个开关（派遣任务 / 炼金）----------
    #   用户口径（原话）：「**炼金和派遣勾选选项加在没体力自动用补给前面**」✓
    #   ---- 语义（与 `MAPBOT_GUILD_DAILY` / `MAPBOT_ALCH_AUTO` 两个环境变量对应）----
    #     `.guild_tasks` 勾选 ⇒ 子进程 `MAPBOT_GUILD_TASKS=1` ⇒ 收工后做**派遣任务**
    #     `.alchemy`     勾选 ⇒ 子进程 `MAPBOT_ALCH_AUTO=1`   ⇒ 收工后做**炼金**（投满星）
    #   ---- 默认值（**刻意都取 False**，与 `.auto_supply` 同一口径）----
    #     · 都是"**会改游戏状态**"的动作（炼金还会**消耗 6 件满星装备** ✗）
    #       ⇒ 读不到偏好时**一律关**，绝不在用户没勾的情况下偷偷做 ✓
    #       （本项目铁律：消耗类动作先问/需显式授权 ✓）
    #   ⚠ 与 `explore_loop._guild_daily` 的对应关系：
    #       两个都不勾 ⇒ 整段公会日常**跳过**（等价旧的"默认不做"）✓
    #       只勾一个   ⇒ 只做那一个 ✓
    #     —— 这也是把"总开关 MAPBOT_GUILD_DAILY"**降级成两个细分开关**的原因：
    #        用户要的是"分别选要不要做"，一个总开关不够用 ✓
    def guild_tasks_path(self):
        """`<runs>/dev_<port>/.guild_tasks` ✓"""
        return self._path('.guild_tasks')

    def load_guild_tasks(self, default=False):
        """读不到 ⇒ **关**（与 `.auto_supply` 同口径：别偷偷改游戏状态 ✗）"""
        return self._read_flag('.guild_tasks', default)

    def save_guild_tasks(self, v):
        return self._write_flag('.guild_tasks', bool(v))

    def alchemy_path(self):
        """`<runs>/dev_<port>/.alchemy` ✓"""
        return self._path('.alchemy')

    def load_alchemy(self, default=False):
        """读不到 ⇒ **关**（⚠ 炼金会**消耗满星装备**，更不能偷偷开 ✗）"""
        return self._read_flag('.alchemy', default)

    def save_alchemy(self, v):
        return self._write_flag('.alchemy', bool(v))

    # ⭐ 2026-10-14 第三颗：「免费招募」（用户口径：「尽量能拿到高等级角色」）
    #   ⚠ 读不到 ⇒ **关**（它会消耗**当天那一次免费机会**；虽然不花宝石，
    #     但"替用户把机会用掉"仍属消耗类动作 ⇒ 必须显式勾 ✓）
    def recruit_path(self):
        """`<runs>/dev_<port>/.recruit` ✓"""
        return self._path('.recruit')

    def load_recruit(self, default=False):
        """读不到 ⇒ **关**（与 `.auto_supply` 同口径 ✓）"""
        return self._read_flag('.recruit', default)

    def save_recruit(self, v):
        return self._write_flag('.recruit', bool(v))

    # ⭐⭐⭐ 2026-10-15 **「免广告」**（用户口径：
    #   「开始做领取广告（默认有免广）…单独加个有无免广的勾选，有就自动做」✓）
    #   ---- 语义（**源码级**）----
    #     `SaveData.CanSkipAds()` = `GetMonthRightRemainDays().Any(x => x >= 0)`
    #     ⇒ **"免广告" = 月卡权益还有剩余天数** ⇒ **账号状态**，不是设置开关 ✓
    #   ---- ⚠⚠ 默认值的方向与别的偏好**相反**----
    #     · 这里 **读不到 ⇒ 开（True）** —— 用户明确说「**默认有免广**」
    #     · 而 `.recruit`/`.alchemy` 是「读不到 ⇒ 关」（那些有消耗 ✗）
    #     ⇒ 判据：**这个开关会消耗东西吗？**
    #        广告领奖是**纯领奖、零消耗**（不花体力/金币/宝石）⇒ 默认开安全 ✓
    def adfree_path(self):
        """`<runs>/dev_<port>/.adfree` ✓"""
        return self._path('.adfree')

    def load_adfree(self, default=True):
        """读不到 ⇒ **开**（用户口径「默认有免广」✓）"""
        return self._read_flag('.adfree', default)

    def save_adfree(self, v):
        return self._write_flag('.adfree', bool(v))

    def load_stop(self, which, default=True):
        """读不到 ⇒ **开**（重写前口径 ✓：遇到就停、保现场让人处理）"""
        return self._read_flag('.stop_%s' % which, default)

    def save_stop(self, which, v):
        return self._write_flag('.stop_%s' % which, bool(v))

    # ---------- 特殊方块（targets_cfg，mtime 热读）----------
    def load_special(self):
        """读配置 + 补默认（**原样搬运 `App.__init__` 那一段** ✓）

        返回 `(cfg, types, 是否改过配置需要落盘)`：
          · `BLOCK_NAMES`（拉黑类）**缺键 ⇒ 补默认 True**（首次默认勾选 ✓）
            ⚠ 只在"缺这个键"时补 ⇒ 用户**手动取消勾选不会被强制勾回** ✓
          · 其余 6 个**不再强制清掉**（2026-10-09 起"解锁勾选"，缺键 = False = 不专门拿 ✓）

        ⭐ 2026-10-13：改走**本设备**的 `target_types.json`（`special_path()` ✓）；
          `_migrate_once()` 已把老的全局那份复制过来了 ⇒ 老勾选不丢 ✓
        """
        import targets_cfg as TC
        cfg = TC.load(path=self.targets_path())

        types = dict(cfg.get('types') or {})
        changed = False
        # ⭐⭐ 2026-10-17 **改成按 `DEFAULT_ON` 补默认**（原来是按 `BLOCK_NAMES`）
        #   ---- 病（用户报「解压后默认勾选不对」）----
        #     用户要的默认：商人/宝库/限时礼包/预言石碑/标记格/紫橙探索格 共 6 个
        #     可界面勾了 **7 个** —— 因为旧代码按 `BLOCK_NAMES` 补：
        #       BLOCK_NAMES 含 金属宝箱怪/机巧宝箱怪/传承祭坛 ⇒ 缺键就补 True ✗
        #     ⇒ **同一个"默认值"有两处真相**（`DEFAULT_ON` 与 `BLOCK_NAMES`），
        #       改一处没用 —— 这跟本项目前面几次"判据改在错的层"是同一类错 ✓
        #   ---- 修法 ----
        #     `DEFAULT_ON` 当**唯一真相源**：在它里面 ⇒ 缺键补 True，否则补 False
        #     ⚠ `BLOCK_NAMES` **一个字都不动**：它表示"不勾 = 完全拉黑"的**语义**，
        #       被 `is_blocked` / `role` 等处使用，改它会波及运行逻辑 ✗
        #     ⚠ 补 False 也是**必要**的：不写键的话 `TC.enabled()` 会走它自己的
        #       兜底（`DEFAULT_ON` 判断），结果一致；但显式写下来能让
        #       `target_types.json` 自解释（用户看得见"这个我关了"）✓
        _want_on = set(TC.DEFAULT_ON)
        for nm in TC.SPECIAL_NAMES:
            if nm not in types:
                types[nm] = nm in _want_on
                changed = True
        if changed:
            cfg['types'] = types
            TC.save(cfg)
        return cfg, types, changed

    def display_order(self):
        """⭐ 勾选框显示顺序 = `targets_cfg.DISPLAY_ORDER`（**必须固定** ✓）

        2026-10-10 真事故：原来用 `list(BLOCK_NAMES) + sorted(...)`，而 `BLOCK_NAMES`
        是 **set** ⇒ `list(set)` 顺序不保证、Python 字符串哈希**每进程随机**
        ⇒ **每开一次窗口勾选框顺序都不一样** ⇒ 用户点错框（「金属宝箱怪」vs「机巧宝箱怪」）
        ⇒ 这就是「勾了宝箱怪却没买」的合理来源之一 ✓
        ⚠ 元组里没有的名字（以后 `SPECIAL_NAMES` 加了新的却忘了加进 `DISPLAY_ORDER`）
          ⇒ **补到末尾**（不许静默丢掉 ✗），并把补齐的名字返回给调用方打日志 ✓
        """
        import targets_cfg as TC
        order = list(TC.DISPLAY_ORDER)
        missing = [x for x in sorted(TC.SPECIAL_NAMES) if x not in order]
        order.extend(missing)
        return order, missing

    def save_special(self, name, on):
        """勾选变化 ⇒ **立刻落盘** ✓（`targets_cfg.save()`；子进程 mtime 热读 ⇒ 下一轮生效）

        ⛔⛔ 2026-10-03 关键修正（**必须显式写 False，不能删键** ✗）：
          `targets_cfg.load()` 里有 `for k in DEFAULT_ON: types.setdefault(k, True)`
          ⇒ 商人/宝库**缺键就会被补成 True** ⇒ 原来"不勾 = 删键"的写法**永远无效** ✗✗
          ⇒ 写 `False` = 用户明确选择（`setdefault` 不覆盖已存在的 False ✓）

        ⭐ 2026-10-13：改走**本设备**的 `target_types.json`（`special_path()` ✓）
          ⚠ 路径**必须**和 `load_special()` / 子进程读的那份**逐字一致** ✗
            （本项目反复栽在"写 A 读 B"⇒ 判据静默失效，见 `v1.62/v1.63/v1.64/v1.71` ✓）
        """
        import targets_cfg as TC
        _p = self.targets_path()
        cfg = TC.load(path=_p)
        types = dict(cfg.get('types') or {})
        types[name] = True if on else False
        cfg['types'] = types
        return bool(TC.save(cfg, _p))


# ══════════════════════════════════════════════════════════════════════
# ③ DeviceService —— 设备/环境（**全部后台线程 + 事件队列**，消灭主线程同步 subprocess）
# ══════════════════════════════════════════════════════════════════════
class DeviceService:
    """设备发现、环境体检、扫屏、多开、查重 —— 都**异步**跑，结果经 `drain()` 回主线程

    事件协议（`drain()` 的产出）：
        ('log', text)                       —— 往日志区打一行
        ('devlabel', text)                  —— 顶栏「实例名」标签
        ('instances', text)                 —— 本机其它实例的一句话
        ('env_rows', rows, ok)              —— 环境检查结果（rows = paths.diagnose() 的 list）
        ('adb', ok, text)                   —— adb devices 复检结果
        ('scan', ok, text)                  —— 扫当前屏结束
        ('loops', ls, mine_n, others_n)     —— 查重结果（主线程弹确认框）
        ('loops_killed', killed)            —— 已清理的 PID 列表
        ('multi_fail', lines)               —— 没有可用实例（主线程弹提示）
        ('multi_open', dev, tag, name)      —— 勾到可用实例（主线程开新窗口）

    ⭐ `tag_fn` = `bot_gui.tag_for`（注入，避免与 `bot_gui.py` 循环 import）；
      ⚠ 它必须**按 MuMu 实例自己的 index 派 tag**（删实例不串号 ✓）
    """

    def __init__(self, python, here, adb, runs_dir, tag='', tag_fn=None,
                 sidecar_fn=None):
        self.python = python
        self.here = here
        self.adb = adb
        self.runs_dir = runs_dir
        self.tag = tag or ''
        self.q = queue.Queue()
        self._tag_fn = tag_fn or (lambda inst, p: 'acc%d' % (sorted(inst).index(p) + 1))
        # ⚠ 极速截图 sidecar 的 ensure 由 `bot_gui.py` **注入** —— 那两个函数被
        #   `verify_startup_speed.py` 用 AST **钉在 `bot_gui.py` 里**（发 `p` / 不取帧 /
        #   只杀本端口 …），搬走会让门禁假红；注入也顺带避免 bot_gui ↔ services 循环 import ✓
        self._sidecar_fn = sidecar_fn

    # ---------- 事件口 ----------
    def emit(self, *ev):
        self.q.put(tuple(ev))

    def drain(self, limit=200):
        out = []
        for _ in range(max(1, int(limit))):
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        return out

    def _spawn(self, fn, *a, **kw):
        threading.Thread(target=self._guard, args=(fn, a, kw), daemon=True).start()

    def _guard(self, fn, a, kw):
        """所有后台工作的统一外壳：**绝不让异常逃出线程**（pythonw 无控制台 ⇒ 看不见 ✗）"""
        try:
            fn(*a, **kw)
        except Exception as e:              # noqa: BLE001
            self.emit('log', '⚠ 后台任务出错：%r' % (e,))

    # ---------- ① 实例名 + 其它实例（原 App.whoami）----------
    def whoami_async(self, device, retry=1):
        self._spawn(self._whoami, device, retry)

    def _whoami(self, device, retry=1):
        label = ''
        try:
            import mumu
            label = mumu.label_for(device)
        except Exception as e:              # noqa: BLE001
            self.emit('log', '（查 MuMu 实例名异常：%r）' % e)
        if not label and retry > 0:
            self.emit('devlabel', '%s（正在查 MuMu 实例名…）' % device)
            time.sleep(1.8)
            return self._whoami(device, retry - 1)
        if not label:
            label = '%s（未能识别 MuMu 实例名）' % device
        self.emit('devlabel', label)
        # ⭐ 顺手确保极速截图服务在跑（**在本线程里**做 ⇒ 不冻 UI ✓ 重写前也是这样 ✓）
        try:
            if self._sidecar_fn is not None:
                self._sidecar_fn(device, lambda s: self.emit('log', s))
        except Exception as e:              # noqa: BLE001
            self.emit('log', '（极速截图服务检查异常：%r）' % e)
        try:
            import mumu
            inst = mumu.instances()
            others = ['%s(%s:%d)' % (v['name'], '127.0.0.1', p)
                      for p, v in sorted(inst.items())
                      if str(p) != str(device).split(':')[-1]]
            if others:
                self.emit('instances', '   机器上其它 MuMu 实例：%s（未启动的会标出来）'
                          % '、'.join(others))
        except Exception:                   # noqa: BLE001
            pass

    # ---------- ② 环境检查（原 App.check）----------
    def check_env_async(self, device):
        self._spawn(self._check_env, device)

    def _check_env(self, device):
        rows, ok = [], True
        try:
            import paths as P
            rows = list(P.diagnose())
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ 环境体检不可用：%r' % (e,))
            rows = []
        for d in rows:
            self.emit('log', '%s %s：%s' % ('✓' if d.get('ok') else '✗',
                                            d.get('label'), d.get('detail')))
            if not d.get('ok') and d.get('key') in ('adb', 'templates'):
                ok = False
        self.emit('env_rows', rows, ok)
        if not ok:
            self.emit('log', '✗ 上面标 ✗ 的项目必须先解决，否则跑不起来。')
            self.emit('log', '  · adb 找不到：装 Android SDK，或设环境变量 MAPBOT_ADB 指向 adb.exe')
            self.emit('log', '  · 模板不完整：重新 clone（或确认 templates/ 目录完整拷贝）')
            self.emit('env_done', False)    # ⭐ 主窗口靠它决定"还跑不跑"
            return False
        if not os.path.exists(str(self.adb)):
            self.emit('log', '✗ 找不到 adb: %s' % self.adb)
            self.emit('env_done', False)
            return False
        try:
            out = subprocess.run([str(self.adb), 'devices'], capture_output=True,
                                 text=True, timeout=10, creationflags=CNW).stdout
            if device not in out:
                subprocess.run([str(self.adb), 'connect', device], capture_output=True,
                               timeout=10, creationflags=CNW)
                out = subprocess.run([str(self.adb), 'devices'], capture_output=True,
                                     text=True, timeout=10, creationflags=CNW).stdout
            if device in out:
                self.emit('log', '✓ 设备已连接：%s' % device)
                self.emit('adb', True, '设备已连接')
            else:
                self.emit('log', '✗ 连不上 %s ——先打开模拟器并登录游戏' % device)
                self.emit('adb', False, '连不上设备')
                ok = False
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ adb 检查失败：%r' % e)
            self.emit('adb', False, 'adb 检查失败')
            ok = False
        if ok:
            self.emit('log', '✓ 环境正常，可以开跑')
        self.emit('env_done', bool(ok))
        return ok

    # ---------- ③ 扫当前屏（只读，标定用）----------
    def scan_screen_async(self, device, tag=''):
        self._spawn(self._scan_screen, device, tag)

    def _scan_screen(self, device, tag=''):
        self.emit('log', '')
        self.emit('log', '▶ 扫描当前屏（只读，不会点任何东西）…')
        cmd = [self.python, os.path.join(self.here, 'core', 'explore_loop.py'),
               '--device', device, '--scan-bag']
        if tag:
            cmd += ['--tag', tag]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                               creationflags=CNW,
                               env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                        PYTHONUTF8='1'))
            for ln in (r.stdout or '').splitlines():
                if ln.strip():
                    self.emit('log', '   ' + ln.rstrip())
            if r.returncode != 0:
                self.emit('log', '   ✗ 扫描失败：%s' % (r.stderr or '')[-200:])
                self.emit('scan', False, (r.stderr or '')[-200:])
            else:
                self.emit('scan', True, '')
        except Exception as e:              # noqa: BLE001
            self.emit('log', '   ✗ 扫描失败：%r' % e)
            self.emit('scan', False, repr(e))

    # ---------- ④ 查重复循环（原 App.dedupe_loops）----------
    def dedupe_async(self, device):
        self._spawn(self._dedupe, device)

    # ⛔⛔ 2026-10-16 **删掉「扫天赋果实」那条服务通道**（用户口径：
    #   「**去掉扫天赋果实按钮**，点天赋果实记录要能直接在工具那里看到」✗）
    #   ---- 为什么整条删掉（而不是留着不用）----
    #     · 用户明确要去掉那颗**按钮** ⇒ 没人会调它了 ✓
    #     · 而**收工时的自动扫描仍然在**（explore_loop._guild_daily ⑤
    #       里 ruit.scan_and_record）—— 那条走的是 explore_loop 子进程，
    #       **不经过这里** ⇒ 删掉本段**不影响自动扫** ✓
    #   ⇒ 留着就是死通道（本项目的老毛病：留着的死代码日后会被误认为还在用 ✗）

    # ---------- ⭐⭐ 「立即招募」（2026-10-14 用户口径：「免费招募改成可以勾选可以立即运行」）----------
    #   走**子进程**（与收工时的自动招募**同一份代码** `recruit.py`）：
    #     · 不冻 UI（后台线程 + 事件队列 ✓）
    #     · 与自动路径**行为完全一致** ⇒ 不会出现"手动能跑、自动不能跑"的分叉 ✓
    #     · 超时 300s（要滚动、OCR、点标签、等动画 ⇒ 给足 ✓）
    def recruit_now_async(self, device, tag=''):
        self._spawn(self._recruit_now, device, tag)

    def _recruit_now(self, device, tag=''):
        self.emit('log', '')
        self.emit('log', '🎲 **立即招募**（不等收工，现在就做一次免费指定招募）…')
        cmd = [self.python, os.path.join(self.here, 'core', 'recruit.py'),
               '--device', device]
        if tag:
            cmd += ['--tag', tag]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               creationflags=CNW,
                               env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                        PYTHONUTF8='1'))
            for ln in (r.stdout or '').splitlines():
                # ⚠ 只放行"人看得懂"的行（airtest 的 DEBUG/INFO 噪声很多 ✗）
                s = ln.rstrip()
                if not s.strip():
                    continue
                if _is_noise(s):
                    continue
                self.emit('log', '   ' + s)
            ok = (r.returncode == 0)
            if not ok:
                _err = (r.stderr or '')[-300:]
                self.emit('log', '   ⚠ 立即招募退出码 %s' % r.returncode)
                if _err.strip():
                    self.emit('log', '   %s' % _err.replace('\n', ' ')[-200:])
            self.emit('recruit_now', ok, (r.stderr or '')[-200:])
        except subprocess.TimeoutExpired:
            self.emit('log', '   ✗ 立即招募超时（300s）⇒ 可能卡住了，请点「扫描当前屏」看现场')
            self.emit('recruit_now', False, 'timeout')
        except Exception as e:              # noqa: BLE001
            self.emit('log', '   ✗ 立即招募出错：%r' % e)
            self.emit('recruit_now', False, repr(e))

    def _dedupe(self, device):
        try:
            import loopguard
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ 查重模块加载失败：%r' % e)
            return
        try:
            ls = loopguard.list_loops()
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ 列出循环失败：%r' % e)
            return
        mine = [p for p in ls if p.get('device') == device]
        others = [p for p in ls if p.get('device') != device]
        if not ls:
            self.emit('log', '✓ 没有正在跑的循环')
            self.emit('loops', [], 0, 0)
            return
        self.emit('log', '发现 %d 个循环（本窗口 %s 上有 %d 个；其它设备 %d 个 —— 那些是正常的 ✓）：'
                  % (len(ls), device, len(mine), len(others)))
        for p in ls:
            self.emit('log', '   PID %-6d 设备 %-20s tag %s'
                      % (p.get('pid'), p.get('device') or '?', p.get('tag') or '-'))
        self.emit('loops', ls, len(mine), len(others))

    def kill_loops_async(self, pids):
        self._spawn(self._kill_loops, list(pids))

    def _kill_loops(self, pids):
        try:
            import loopguard
            killed = loopguard.kill(pids)
            self.emit('loops_killed', killed)
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ 停循环失败：%r' % e)

    # ---------- ④b 启动前查重（原 App.start 里那段；**只查本窗口绑的那台**）----------
    #   用户 2026-09-25 澄清：两个窗口绑两台模拟器 = 各自的进程，可以同时跑 ✓；
    #   要防的是"**同一台模拟器上跑两份**"✗
    def duplicates_async(self, device, tag=''):
        self._spawn(self._duplicates, device, tag)

    def _duplicates(self, device, tag=''):
        try:
            import loopguard
            dup = loopguard.duplicates_for(device, tag, exclude_pid=os.getpid())
        except Exception as e:              # noqa: BLE001
            self.emit('log', '⚠ 查重不可用（%r），跳过' % e)
            dup = []
        self.emit('dups', list(dup or []))

    # ---------- ⑤ 多开（原 App.spawn_multi 的"挑实例"那半）----------
    def spawn_multi_async(self, device):
        self._spawn(self._spawn_multi, device)

    def _spawn_multi(self, device):
        try:
            import mumu
            inst = mumu.instances()
        except Exception as e:              # noqa: BLE001
            self.emit('multi_fail', ['✗ 查 MuMu 实例失败：%r' % e])
            return
        if not inst:
            self.emit('multi_fail', ['⚠ 没查到 MuMu 实例（MuMuManager.exe 找不到？）'])
            return
        mine = str(device).split(':')[-1]
        busy = None
        try:
            import loopguard
            loopguard.sweep_stale_locks()       # 先清过期锁（关窗口没清干净的）
            busy = loopguard.busy_devices(exclude_pid=os.getpid())
        except Exception as e:              # noqa: BLE001
            self.emit('log', '⚠ 进程查重不可用（%r），退回锁文件判断' % e)
        used = set()
        if busy is not None:
            for p in inst:
                if ('127.0.0.1:%d' % p) in busy:
                    used.add(p)
        else:
            # ⚠ 只有**进程查不出来**时才退回锁文件（否则过期锁会误报"已被绑定" ✗）
            for p in inst:
                tg = self._tag_fn(inst, p)
                if os.path.exists(os.path.join(self.runs_dir, tg, '.lock')):
                    used.add(p)
        if busy:
            self.emit('log', '   正在被占用的模拟器：%s'
                      % '、'.join('%s（%s）' % (d, w) for d, w in busy.items()))
        cand = None
        for p, v in sorted(inst.items()):
            if str(p) == mine or p in used:
                continue
            if not v.get('running'):
                continue
            cand = p
            break
        if cand is None:
            lines = self._multi_status_lines(inst, mine, busy, used)
            self.emit('multi_fail', lines)
            return
        dev = '127.0.0.1:%d' % cand
        v = inst[cand]
        tg = self._tag_fn(inst, cand)
        try:
            subprocess.run([str(self.adb), 'connect', dev], capture_output=True,
                           text=True, timeout=10, creationflags=CNW)
        except Exception as e:              # noqa: BLE001
            self.emit('multi_fail', ['⚠ adb connect 失败：%r' % e])
            return
        self.emit('multi_open', dev, tg, v.get('name') or '')

    def _multi_status_lines(self, inst, mine, busy, used):
        """⚠ 逐台写清**真实状态**（原来那句"必须先在多开器里启动第二个实例"**教错了** ✗）

        2026-10-03 诊断（`_tmpman/diag_multi.py`）：`busy_devices` 显示两台**都已经有循环在跑**
        ⇒ 它**正确地拒绝**了（同一台设备开两个窗口会互相抢 ✗）；可原提示让用户去多开器启动
        第二个实例 —— 而实例明明在运行 ✗ ⇒ 用户按提示做也没用 ✗✗
        """
        lines = []
        for p, v in sorted(inst.items()):
            dv = '127.0.0.1:%d' % p
            if str(p) == mine:
                mark = '← 本窗口'
            elif dv in (busy or {}):
                mark = '★ %s ⇒ **想在新窗口用它，先把它停掉**（该窗口点 ■ 停止，或结束该 PID）' \
                       % (busy[dv],)
            elif p in used:
                mark = '（已被别的窗口绑）'
            elif v.get('running'):
                mark = '运行中 ✓ 应该能绑上'
            else:
                mark = '**未启动** ✗（要先在 MuMu 多开器里启动它）'
            lines.append('   · %s → %s  %s' % (v.get('name'), dv, mark))
        return lines

    # ---------- ⑥ 开新窗口（原 App.spawn_multi 的后半，主线程调也行：很快 ✓）----------
    def open_multi_window(self, dev, tag, name=''):
        """`bot_gui.py --device X --tag accN`（命令行**与重写前逐字一致** ✓）"""
        try:
            os.makedirs(os.path.join(self.runs_dir, tag), exist_ok=True)
            subprocess.Popen([self.python, os.path.join(self.here, 'core', 'bot_gui.py'),
                              '--device', dev, '--tag', tag],
                             cwd=self.here, creationflags=CNW)
            return True
        except Exception as e:              # noqa: BLE001
            self.emit('log', '✗ 新开窗口失败：%r' % e)
            return False


# ══════════════════════════════════════════════════════════════════════
# ④ 零散工具（原来散在 bot_gui 里的两处）
# ══════════════════════════════════════════════════════════════════════
def tag_for(inst, port):
    """MuMu 端口 -> 日志目录名（acc1 / acc2 …）

    ⭐ 2026-10-02 统一到这一个函数。以前 `choose_device` / `spawn_multi` / 锁文件兜底
      **三处各写了一份** `sorted(inst).index(p) + 1`，而排序位置在「多开器里删掉中间某个
      实例」后会整体前移 ⇒ 同一台设备换个时间打开，日志目录名会变（acc2 变 acc1），
      历史记录对不上。现在一律按 **MuMu 实例自己的 `index`** 派，删实例不影响别的 ✓
    """
    v = (inst or {}).get(port) or {}
    try:
        return 'acc%d' % (int(str(v.get('index') or '').strip()) + 1)
    except (TypeError, ValueError):
        return 'acc%d' % (sorted(inst).index(port) + 1)


def gui_log_file(runs_dir, when=None, tag=''):
    """GUI 自己的日志（`gui_console_<日期>.log`，按天分文件 ✓）

    ⭐⭐⭐ 2026-10-10 教训（用户报「勾了宝箱怪却没买」时抓到的坑）：
      原来 `log()` **只写窗口 Text 控件、一个字都不落盘** ✗ ⇒
      「特殊方块勾选」这类**只有 GUI 知道**的事件**只在屏幕上一闪而过** ✗✗
      ⇒ 排查"用户说勾了、配置却是 false"时**翻遍所有日志文件一条都找不到** ⇒ 只能靠猜 ✗
    """
    day = when or time.strftime('%Y%m%d')
    return os.path.join(runs_dir, 'gui_console_%s.log' % day)
