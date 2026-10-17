# -*- coding: utf-8 -*-
"""verify_startup_speed.py · 回归：**启动闪黑窗** ＋ **极速截图通道自愈** ＋ **sidecar 健康判据**

用户 2026-10-06 原话（一次报三件事，本文件全包）：
    ①「**顺便把启动时会闪过两次命令窗口也修了**」
    ②（"很慢"的根因之一）极速截图**一次失败就永久退化**到 adb（慢 25 倍）
    ③（"很慢"的根因之二）sidecar **卡死但端口还开着**却被判"健康"

① 启动闪窗 —— **恰好两次**，真根因在 `mapbot.adb_connect()`
--------------------------------------------------------------
    机制：`启动.bat` 用 `start "" venv\\Scripts\\pythonw.exe bootstrap.py` 拉起引导层
      ⇒ `pythonw` 是 **GUI 子系统**程序 ⇒ **根本没有控制台**
        （不是"隐藏的控制台"：`GetConsoleWindow()==0` 且无控制台对象）
      ⇒ 它再调 `adb.exe` / `python.exe`（**控制台程序**）时，
        Windows **必须为它新建一个控制台** ⇒ **默认可见** ⇒ 黑窗闪一下 ✗✗
    ⚠ `adb_connect()` 里**恰好两条**命令（`connect` + `wait-for-device`）
      ⇒ **恰好闪两次** —— 与用户描述**逐字吻合** ✓
    ⭐ 决定性实测（`exp_conhost3.py`，父进程 pythonw 且**不带** CNW = 复现真实场景）：
        子程序**不带**标志 ⇒ 新增 **2 个可见控制台窗口**（本机默认终端是 Windows Terminal
                            ⇒ 类名 `CASCADIA_HOSTING_WINDOW_CLASS`）
        子程序**带** CNW ⇒ 新增 **0 个** ✓
    ⚠⚠ 两条**假象**实验（别再走回头路）：
      · WMI `Register-WmiEvent -Action` 数 conhost ⇒ `powershell -Command` 下**没有消息泵**
        ⇒ action 从不执行 ⇒ 数出 0（假的）✗
      · 用 `creationflags=CNW` 起 pythonw 父进程 ⇒ 它**有隐藏控制台**、子程序继承它
        ⇒ 也不弹（假阴性）✗ —— **父进程必须真的无控制台**才能复现 ✓
    ⇒ 判据：`adb_connect` 的**每一条** `subprocess.run` 都必须带 `creationflags`
      （用 **AST** 数，不 grep —— 注释里必然出现这些名字，grep 会假绿/假红 ✗）
    ⚠ 启动链上还有 `hotupdate._run_code()`（语法/import 自检起 `python -c`，包内 python
      是控制台程序）⇒ 一并要求带标志。**引导层不进补丁 ⇒ 这处要重发整包才生效** ✓

② 极速通道自愈 —— 旧行为「一次失败就永久退回 adb」✗
--------------------------------------------------------------
    旧代码 `snap()` / `wait_change()` / `wait_stable()` 里**任何一次** `fast.grab()`
    失败就把 `self.fast_ok = False` 一撸到底、**本次运行再也不试**，而且**一行日志都没有** ✗
    真机实证：`runs/sidecar_19999.log` 里 `adb connect` 子进程偶发失败**一次**，
    之后 sidecar 自己恢复了（探针 `✓ 正常 720x1280 [0.042s]`），
    可 bot **还在用 adb 截图 0.33 秒/张（慢 25 倍）**、日志上看不出来 ✗
    新行为：连续失败满 `FAST_MAX_FAIL` 次才关（**功能不受影响**，退回 adb）＋
            `FAST_RETRY_SEC` 秒后**自动试一次**（成功即切回 ✓）＋ **两侧都打日志** ✓
    ⚠ 为什么要有"上限"再关：sidecar 真死时每帧都 `connect` 会白等 timeout ⇒
      必须"关掉 + 冷却"，不能无限重试 ✓
    ⚠ `snap()` 里那条 **adb + airtest 双双失败**的分支**不再**关极速通道：
      那条路根本没问过极速通道 ⇒ 拿它顶罪没有依据 ✗

③ sidecar 健康判据 —— **只许发 `p`**；取帧探测**不许出现在启动路径**
--------------------------------------------------------------------
    旧实现只做 `socket.create_connection()`（TCP 三次握手）⇒ 端口**开着**就算"健康" ✗
    真机实证：**端口 20000 能连上，但发 `b'g'` 之后 `recv` 永不返回** ⇒ 而旧判据报
    「✓ 已在运行」⇒ bot 一直对着取不出帧的 sidecar 调 `grab()`，每次白等 timeout，
    **日志上一切正常** ✗✗

    ⚠⚠ 这一条我**连改错两版**，两次都是实测才抓住：
      · 第二版：拿「能不能取到一帧」当**存活**判据 ⇒ 实测（`_tmpman/probe_ping_vs_grab.py`）
        三个端口 `p` 全回 `pong`，而设备没开的两个 `g` 一律不回 ⇒ **设备没开**与
        **服务卡死**在客户端长得一模一样 ⇒ 会把**健康**的 sidecar 判死并 `_sidecar_kill`
        **杀掉**，还可能打断另一个实例正在跑的 bot ✗✗
      · 第三版（本版）：**连"取帧探测"本身都不该做** —— 定点实测
        （`_tmpman/probe_g_sideeffect.py`，只发一次 `g`、设备没开）：

          发 `p` ⇒ sidecar 日志增长 **0 字节** ⇒ 真·无副作用 ✓
          发 `g` ⇒ 20 秒内日志增长 **1623 字节**，全是 MAA
                   `connect failed` / `re-connect failed` / `controller screencap failed`，
                   **还去执行了 `adb kill-server`** ✗✗

        ⇒ `g` 会**真的让 MAA 去碰设备**；而 `ensure_sidecar` 是**开窗时无条件调**的，
          用户"先开窗口、后开模拟器"是常态 ⇒ 每开一次窗就灌一轮重连风暴、
          还可能把 adb server 杀掉 ✗✗
        ⇒ 结论：启动路径**只发 `p`**；「能不能取帧」是 `fastcap` 自己的事
          （取不到它会自己退 adb），**这里不预先试探** ✓
      ⚠ 附带教训：我最初**就是被这些 MAA 红字误导**去怀疑"sidecar 卡死"的 ——
        那些红字是**我自己的探测制造出来的** ⇒ **取证手段会污染证据**（§3 老坑新实例）
    ⚠ 卡死（`p` 也不回）时才**杀掉 + 重启**（只杀命令行里带**本端口**的那个 ⇒ 不错杀 ✓）
    ⚠ `fastcap` 取帧超时**分两档**：没预热过 **6s**（实测冷首帧最慢 **5.69s** ⇒ 一刀切
      1.5s 会**必然**判失败 ✗），预热过收紧到 **1.5s**（正常 0.010s/张 ⇒ 宽松 150 倍 ✓）

牙齿（falsifiable）
-------------------
    · 去掉 `adb_connect` 任一条的 `creationflags` ⇒ ① 红
    · `FAST_MAX_FAIL = 1`（= 退回旧行为）⇒ ② 红
    · 把 `_fast_try_revive()` 的冷却判断删掉 ⇒ ② 的"真死不每帧重试"红
    · `_sidecar_ping` 改回裸 `create_connection` ⇒ ③ 的"真卡死判 False"红
    · **拿取帧判据当存活判据**（我犯过的错）⇒ ③ 的"设备没开判 True"红 ✗✗
    · **在 `ensure_sidecar` 里加回任何 `g` 探测**（我犯的第二个错）⇒ ③ 的
      "启动路径一个 `g` 都不发"红 ✗✗
      （本文件**真起三个假 sidecar**：真卡死 / 设备没开 / 完全健康，不是字符串断言 ✓）
    · `FAST_WARM_TIMEOUT` 改回 1.5 ⇒ ③ 的冷首帧断言红
"""
import ast
import io
import os
import re
import socket
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
import threading
import time

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _src(fn):
    return io.open(os.path.join(HERE, fn), encoding='utf-8').read()


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _probe_calls(node):
    """收集一段 AST 里对 `_sidecar_ping` 的调用名（按源码顺序）"""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == '_sidecar_ping':
            out.append((n.lineno, n.func.id))
    return [x[1] for x in sorted(out)]


def _ensure_first_test():
    """`ensure_sidecar` 里**第一个**由探测函数把关的 `if` 用的是哪个判据

    ⚠⚠ 为什么必须用 AST 而不是 grep：`if _sidecar_ping(port):` 这个**字符串**在函数里
      出现**两次**（开头判死活 ＋ 末尾等待循环），grep 拿"出现过"当判据 ⇒
      把开头的判据换成 `_sidecar_frame_ok`（= 会**误杀健康 sidecar** 的那个 bug）时，
      末尾那次仍然命中 ⇒ **门禁照样全绿** ✗✗ —— 牙齿 F 当场抓出过这个假绿。
    ⇒ 判据必须是"**第一个**把关的 `if` 是谁"，AST 天然能表达，grep 不能 ✓
    """
    fn = _func(ast.parse(_bs), 'ensure_sidecar')
    if fn is None:
        return None
    for n in fn.body:                     # ⚠ 只扫**顶层**语句：开头那道判死活的闸门
        if isinstance(n, ast.If):
            got = _probe_calls(n.test)
            if got:
                return got[0]
    return None


def _sends_in(fname):
    """某个函数里 `sock.sendall(b'X')` 实际发了哪些字节（AST 取常量，不靠正则窗口）

    ⚠ 为什么不用正则：`def _sidecar_ping[\\s\\S]{0,1200}?sendall\\(b'p'\\)` 这种**定长窗口**
      会随注释/文档字符串变长而**静默失效** —— 本轮就当场踩到（文档写详细了 ⇒ 窗口不够
      ⇒ 明明代码没动却报红 ✗）。AST 不受排版影响 ✓
    """
    fn = _func(ast.parse(_bs), fname)
    if fn is None:
        return None
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'sendall' \
                and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, bytes):
            out.append(n.args[0].value)
    return out


def _has_const(fname, val):
    """函数里有没有某个字符串常量（如 `b'pong'`）—— 同样走 AST，不用正则窗口"""
    fn = _func(ast.parse(_bs), fname)
    if fn is None:
        return False
    return any(isinstance(n, ast.Constant) and n.value == val for n in ast.walk(fn))


def _frame_probes_in(fname='ensure_sidecar'):
    """`ensure_sidecar` 里所有**取帧探测**调用的行号（必须为空 ✗✗）

    ⚠⚠ 为什么整条路径都不许有：定点实测（`_tmpman/probe_g_sideeffect.py`）发一次 `g`
      ⇒ 设备没开时 MAA 会**反复重连**、**还执行 `adb kill-server`**（20 秒 +1623 字节
      红字日志）；而发 `p` 是 **0 字节**。
    `ensure_sidecar` 是**开窗时无条件调**的 ⇒ 每开一次窗就灌一轮重连风暴 ✗✗
    ⇒ 不只是"不许拿它判死活"，而是"**根本不许调**" ✓
    """
    fn = _func(ast.parse(_bs), fname)
    if fn is None:
        return []
    return sorted(n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ('_sidecar_frame_ok', '_sidecar_grab_probe'))


# ══════════════════════════════════════════════════════════════════════════
print('【1】启动闪黑窗 —— `adb_connect` 的**每一条**命令都必须带 `creationflags`')
print('     （恰好两条 ⇒ 恰好闪两次，与用户描述逐字吻合；用 AST 数，不用 grep）')
_mb = _src('mapbot.py')
_t = ast.parse(_mb)
_fn = _func(_t, 'adb_connect')
ck('找到 adb_connect()', _fn is not None)
_runs = [n for n in ast.walk(_fn) if isinstance(n, ast.Call)
         and getattr(n.func, 'attr', '') == 'run'
         and isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess'] \
    if _fn else []
ck('adb_connect 里**恰好 2 条** subprocess.run（= 闪两次 ✓）', len(_runs) == 2,
   '实际 %d 条' % len(_runs))
for _i, _c in enumerate(_runs):
    ck('第 %d 条带 creationflags（不带 ⇒ 新建可见控制台 ⇒ 闪黑窗 ✗）' % (_i + 1),
       'creationflags' in {k.arg for k in _c.keywords}, 'line %d' % _c.lineno)

print()
print('【1b】启动链上的另一处 —— `hotupdate._run_code`（语法/import 自检起 python -c）')
_hs = _src('hotupdate.py')
_hfn = _func(ast.parse(_hs), '_run_code')
_hruns = [n for n in ast.walk(_hfn) if isinstance(n, ast.Call)
          and getattr(n.func, 'attr', '') == 'run'] if _hfn else []
ck('_run_code 的 subprocess.run 带 creationflags',
   bool(_hruns) and all('creationflags' in {k.arg for k in c.keywords} for c in _hruns),
   '%d 条' % len(_hruns))
ck('hotupdate 定义了 CNW 常量（不是散落的魔法数字 ✓）',
   re.search(r'^CNW\s*=', _hs, re.M) is not None)
ck('⚠ 注释里写明"引导层不进补丁 ⇒ 要重发整包"（防后人以为热更能修 ✓）',
   '重发整包' in _hs or '不进补丁' in _hs)

# ══════════════════════════════════════════════════════════════════════════
print()
print('【2】极速通道自愈 —— 连续失败 N 次才关 ＋ 冷却后自动复活 ＋ 成功清零')
import mapbot as MB

ck('FAST_MAX_FAIL ≥ 2（= 1 就是旧行为"一次就永久关"✗）',
   isinstance(MB.FAST_MAX_FAIL, int) and MB.FAST_MAX_FAIL >= 2, str(MB.FAST_MAX_FAIL))
ck('FAST_RETRY_SEC > 0（关掉后会再试 ✓）', MB.FAST_RETRY_SEC > 0, str(MB.FAST_RETRY_SEC))
ck('自愈三件套都在（_fast_note_ok / _fast_note_fail / _fast_try_revive）',
   all(hasattr(MB.Bot, m) for m in
       ('_fast_note_ok', '_fast_note_fail', '_fast_try_revive', '_fast_log')))

# AST 判据：三个**取帧路径**里都不许再出现 `self.fast_ok = False` 硬关
#   ⚠ 只查这三处 —— `__init__`（初始状态/import 失败，且那时 self.fast 已是 None，
#     本来也无从复活 ✓）与 `_fast_note_fail` **自己**（它就该关 ✓）是**合法的**，
#     一并禁掉会把断言写宽成"永远红"✗
def _hardclose(fname):
    f = _func(_t, fname)
    if f is None:
        return None
    return [n.lineno for n in ast.walk(f)
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Attribute)
            and n.targets[0].attr == 'fast_ok'
            and isinstance(n.targets[0].value, ast.Name)
            and n.targets[0].value.id == 'self'
            and isinstance(n.value, ast.Constant) and n.value.value is False]


for _fname in ('snap', 'wait_change', 'wait_stable'):
    _hc = _hardclose(_fname)
    ck('%s() 里**不再有** `self.fast_ok = False` 硬关（应走 _fast_note_fail ✓）'
       % _fname, _hc is not None and not _hc,
       ('仍在 line %s' % _hc) if _hc else '')
ck('三处旧失败点都改调 _fast_note_fail（snap / wait_change / wait_stable）',
   _mb.count('_fast_note_fail(') >= 3, '%d 处' % _mb.count('_fast_note_fail('))
ck('成功路径调 _fast_note_ok（清零计数 ✓）', _mb.count('_fast_note_ok(') >= 3,
   '%d 处' % _mb.count('_fast_note_ok('))


class FakeFast:
    """可控假极速通道"""
    def __init__(self):
        self.mode = 'ok'
        self.n = 0

    def grab(self):
        self.n += 1
        if self.mode == 'fail':
            return None
        import numpy as np
        return np.zeros((1280, 720, 3), dtype=np.uint8)

    def close(self):
        pass


class FakeBot(MB.Bot):
    """跳过 __init__（不连真设备），只手装极速通道 —— 纯行为级，不碰真机"""
    def __init__(self):
        self.dev = '127.0.0.1:16384'
        self.tag = None
        self.runs = os.path.join(HERE, '_verify', '_fasttmp')
        os.makedirs(self.runs, exist_ok=True)
        self.log_prefix = 'gate'
        self._seq = 0
        # ⭐ 必须与 `Bot.__init__`（mapbot.py）保持一致：本替身**跳过 __init__**
        #   （不连真设备），所以 `__init__` 里每个字段都得在这里手装一遍。
        #   ⚠ 2026-10-06 补 `_snap_n`（BUG-1 帧号）：`_fast_try_revive()` 取到新帧时
        #     会 `_snap_n += 1` ⇒ 少这一行本门禁当场 `AttributeError`（门禁的牙齿 ✓）。
        #   ⇒ 以后往 `Bot.__init__` 加字段，这里也要跟着加。
        self._snap_n = 0
        self._img_arr = None
        self._img_path = None
        self._last = None
        self.fast = FakeFast()
        self.fast_ok = True
        self._fast_fail = 0
        self._fast_off_at = 0.0
        self._fast_retry_n = 0
        self.t = {'snap': 0.0, 'ocr': 0.0, 'wait': 0.0, 'wait_n': 0,
                  'tap': 0, 'ocr_n': 0}
        self.last_change = {'changed': None, 'dim': 1.0}
        self._logged = []
        self._fast_log = lambda m: self._logged.append(m)


_b = FakeBot()
_b.fast.mode = 'fail'
for _k in range(1, MB.FAST_MAX_FAIL):
    _b._fast_note_fail('t%d' % _k)
    ck('失败 %d 次（< %d）：**还没关**（旧代码这里就永久关了 ✗）'
       % (_k, MB.FAST_MAX_FAIL), _b.fast_ok is True, 'fail=%d' % _b._fast_fail)
_b._fast_note_fail('tN')
ck('失败满 %d 次：关掉（退回 adb ✓，功能不受影响）' % MB.FAST_MAX_FAIL,
   _b.fast_ok is False, 'fail=%d' % _b._fast_fail)
ck('关掉时记了时刻（= 冷却计时起点 ✓）', _b._fast_off_at > 0)
ck('关掉时**打了日志**（旧代码一行都没有 ✗）',
   any('退回 adb' in m for m in _b._logged), str(_b._logged[-1:]))
ck('日志里写明"会重试"与"慢多少倍"（用户能看懂 ✓）',
   any('重试' in m and '25 倍' in m for m in _b._logged))

_b.fast.mode = 'ok'
ck('冷却**未到**时不重试（不白等 ✓）', _b._fast_try_revive() is False)
_b._fast_off_at = time.time() - MB.FAST_RETRY_SEC - 1
ck('冷却**到了**且通道已恢复 ⇒ 复活成功 ✓', _b._fast_try_revive() is True)
ck('复活后 fast_ok=True ＋ 失败计数清零',
   _b.fast_ok is True and _b._fast_fail == 0)
ck('复活打了日志（通道切换可见 ✓）', any('已恢复' in m for m in _b._logged),
   str(_b._logged[-1:]))

_b2 = FakeBot()
_b2.fast.mode = 'fail'
for _ in range(MB.FAST_MAX_FAIL):
    _b2._fast_note_fail('x')
_b2._fast_off_at = time.time() - MB.FAST_RETRY_SEC - 1
ck('通道**真死**：第 1 次重试失败（返回 False ✓）', _b2._fast_try_revive() is False)
ck('通道**真死**：紧接着再问**不再重试**（冷却时钟已推后 ⇒ 不每帧白等 ✓）',
   _b2._fast_try_revive() is False)

# ══════════════════════════════════════════════════════════════════════════
print()
print('【3】sidecar 判据 —— **只许发 `p`**；取帧探测**不许出现在启动路径**')
print('     ⚠ 教训一：拿「能不能取到一帧」判存活 ⇒ 设备没开时 `g` 恒不回')
print('       ⇒ 会把**健康**的 sidecar 判成卡死 ⇒ 杀掉好好的服务 ✗✗')
print('     ⚠ 教训二（更严重）：连「取帧探测」本身都不该做 —— 实测发一次 `g`')
print('       ⇒ MAA 反复重连、**还 `adb kill-server`**（+1623 字节红字）')
print('       而发 `p` 是 **0 字节** ⇒ 开窗时无条件调它 = 每次开窗灌一轮重连风暴 ✗✗')
_bs = _src('bot_gui.py')
ck('有 _sidecar_ping（**唯一**判据：发 `p` 收 `pong`，不碰设备 ✓）',
   _sends_in('_sidecar_ping') == [b'p'] and _has_const('_sidecar_ping', b'pong'),
   '实际发 %r' % _sends_in('_sidecar_ping'))
ck('⭐⭐ 取帧探测函数**已整个删掉**（`_sidecar_frame_ok` 不该存在 ⇒ 有副作用 ✗✗）',
   'def _sidecar_frame_ok' not in _bs)
ck('⭐⭐ `ensure_sidecar` 里**一个取帧探测都没有**（开窗路径只发 `p` ✓）',
   _frame_probes_in() == [], '在 line %s 里看到取帧探测' % _frame_probes_in())
ck('`_sidecar_ping` 探测无副作用：**只**发 `p`（不发 `g`/`s`/`q` ✓）',
   _sends_in('_sidecar_ping') == [b'p'], '实际发 %r' % _sends_in('_sidecar_ping'))
ck('卡死时会杀掉再重启（否则端口一直被占 ⇒ 永远修不好 ✓）',
   'def _sidecar_kill(' in _bs and '_sidecar_kill(port' in _bs)
ck('只杀**本端口**的 sidecar（多开时不许错杀别的实例 ✗）',
   re.search(r"--port.{0,40}%d", _bs) is not None or '--port\\s+%d' in _bs)
ck('ensure_sidecar 用**存活**判据决定"要不要杀"（不是取帧判据 ✗）',
   _ensure_first_test() == '_sidecar_ping', '实际 %r' % _ensure_first_test())
ck('socket 已提到模块级 import（旧代码是函数内 import ⇒ 现在会 NameError ✗）',
   re.search(r'^import socket\s*$', _bs, re.M) is not None)
_fs = _src('fastcap.py')
ck('fastcap 冷首帧给足超时（实测最慢 5.69s ⇒ 写死 1.5s 会**必然**判失败 ✗）',
   re.search(r'FAST_WARM_TIMEOUT\s*=\s*([3-9]|1\d)(\.\d+)?', _fs) is not None)
ck('fastcap 热帧收紧超时（正常 0.01s/张 ⇒ 卡死时不再每帧白等 ✓）',
   re.search(r'FAST_HOT_TIMEOUT\s*=\s*1\.5', _fs) is not None)
ck('fastcap 按**是否预热过**分档选超时（不是一刀切 ✗）',
   re.search(r'settimeout\(FAST_WARM_TIMEOUT if not self\.warmed', _fs) is not None)
ck('fastcap 拿到完整一帧后置 warmed（否则永远用冷档 ⇒ 卡死时每帧白等 6s ✗）',
   re.search(r'self\.warmed\s*=\s*True', _fs) is not None)

print()
print('【3b】三个假 sidecar 对照 —— 关键那条：**设备没开（回 pong、不回帧）不许被杀** ✗')
print('     （旧判据会判它"卡死"并杀掉 ⇒ 正是我引入的缺陷，必须被这条牙齿钉住 ✓）')


def _wedged(port, ev):
    """**真卡死**：连得上，但 `p`/`g` 一律不回（复现"端口开着却什么都不答"）"""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(4)
    ev.set()
    conns = []
    while True:
        try:
            c, _ = srv.accept()
        except Exception:       # noqa: BLE001
            break
        conns.append(c)          # 收下就不管 ⇒ 发 p/g 都永不回（复现卡死 ✓）


def _pong_only(port, ev):
    """**服务活着、设备没开**：`p` 回 `pong` ✓，`g` **永不回帧**（真机 19999/20000 实测行为）

    ⇒ 这才是最容易误杀的那一类：服务完全健康，只是模拟器没开。
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(4)
    ev.set()
    conns = []
    while True:
        try:
            c, _ = srv.accept()
        except Exception:       # noqa: BLE001
            break
        try:
            if c.recv(1) == b'p':
                c.sendall(b'pong')
            else:
                conns.append(c)  # `g` ⇒ 收下不回（设备没开 ✓）
        except Exception:       # noqa: BLE001
            pass
        finally:
            try:
                c.close()
            except Exception:   # noqa: BLE001
                pass


def _good(port, ev, hits=None):
    """**完全健康**：`p` 回 `pong` ✓（顺带记录收到过哪些命令，供"一个 `g` 都不发"断言）

    ⚠ 这里仍然**能**答 `g`（万一被测代码退回去发 `g`，要能被 `hits` 抓到 ⇒ 报红 ✓）
    """
    import struct
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(4)
    ev.set()
    while True:
        try:
            c, _ = srv.accept()
        except Exception:       # noqa: BLE001
            break
        try:
            _cmd = c.recv(1)
            if hits is not None:
                hits.append(_cmd)
            if _cmd == b'p':
                c.sendall(b'pong')
            elif _cmd == b'g':
                c.sendall(b'MUMU' + struct.pack('<III', 720, 1280, 3))
                c.sendall(b'\x00' * (720 * 1280 * 3))
        except Exception:       # noqa: BLE001
            pass
        finally:
            try:
                c.close()
            except Exception:   # noqa: BLE001
                pass


import bot_gui as BG


_P1, _P2, _P3 = 21987, 21988, 21989
_e1, _e2, _e3 = threading.Event(), threading.Event(), threading.Event()
_HITS = []                       # `_P2` 上收到的原始命令字节
threading.Thread(target=_wedged, args=(_P1, _e1), daemon=True).start()
threading.Thread(target=_good, args=(_P2, _e2, _HITS), daemon=True).start()
threading.Thread(target=_pong_only, args=(_P3, _e3), daemon=True).start()
_e1.wait(5)
_e2.wait(5)
_e3.wait(5)

try:
    socket.create_connection(('127.0.0.1', _P1), timeout=0.6).close()
    _old_says = True
except Exception:       # noqa: BLE001
    _old_says = False
ck('旧判据（只连 TCP）会把**卡死的** sidecar 判成"健康"（复现用户症状 ✓）', _old_says)

_t0 = time.time()
_new_says = BG._sidecar_ping(_P1, timeout=1.0)
_dt = time.time() - _t0
ck('真卡死（`p` 也不回）⇒ 判**不可用** ✓（⇒ 允许杀）', _new_says is False)
ck('且**在超时内**返回（不挂死 ✓）', _dt < 4.0, '%.2fs' % _dt)
ck('对照组：**完全健康**的 sidecar 存活判 True（不是恒 False ✓）',
   BG._sidecar_ping(_P2, timeout=2.0) is True)

# ⭐⭐⭐ 本轮最关键的一条：设备没开 ≠ 服务卡死
ck('⭐⭐ **设备没开**（回 `pong`、不回帧）⇒ 存活判 **True**（**绝不许杀** ✗✗）',
   BG._sidecar_ping(_P3, timeout=2.0) is True)

# ⭐⭐⭐⭐⭐ 端到端：**真跑一次 ensure_sidecar**，对着"设备没开"的假 sidecar
#   这是本轮最重要的一条 —— 前面都是判据级，这条才是**行为级**：
#   旧实现（拿取帧判死活）会在这里**真去杀进程** ✗✗
_P3_DEV = '127.0.0.1:%d' % (16384 + (_P3 - 19999) * 32)   # 反解出映射到 _P3 的设备号
assert BG.sidecar_port(_P3_DEV) == _P3, '反解设备号失败'
_killed = []
_real_kill = BG._sidecar_kill
BG._sidecar_kill = lambda port, log=print: (_killed.append(port), [])[1]
_logs = []
try:
    _ret = BG.ensure_sidecar(_P3_DEV, log=_logs.append)
finally:
    BG._sidecar_kill = _real_kill
_joined = '\n'.join(_logs)
ck('⭐⭐⭐ ensure_sidecar 对"设备没开"的健康服务返回 **True**（不是 False ✗）', _ret is True)
ck('⭐⭐⭐ 且**一次都没调 `_sidecar_kill`**（设备没开 ⇒ 绝不杀服务 ✓✓）',
   _killed == [], '被杀的端口 %r' % _killed)
ck('⭐⭐⭐ 且日志里**没有**"清掉卡死"（不能谎报杀了）', '清掉卡死' not in _joined)
print('       日志：%s' % _joined.replace('\n', ' | '))

# ⭐⭐⭐⭐⭐ 行为级：**整条开窗路径一个 `g` 都不许发**（发了就会引发 MAA 重连风暴 ✗✗）
#   在**健康**的假 sidecar（`_P2`）上再跑一次 ensure_sidecar，数它收到了什么命令。
#   这样断言的是**真实网络行为**，不是"源码里有没有那个字符串" ✓
_HITS.clear()
_P2_DEV = '127.0.0.1:%d' % (16384 + (_P2 - 19999) * 32)
assert BG.sidecar_port(_P2_DEV) == _P2, '反解设备号失败'
_killed2 = []
BG._sidecar_kill = lambda port, log=print: (_killed2.append(port), [])[1]
try:
    _ret2 = BG.ensure_sidecar(_P2_DEV, log=lambda s: None)
finally:
    BG._sidecar_kill = _real_kill
time.sleep(0.3)
ck('⭐⭐⭐⭐⭐ 开窗路径**一个 `g` 都没发**（只发 `p` ✓✓ 旧版会发 `g` ⇒ MAA 重连风暴 ✗✗）',
   _HITS.count(b'g') == 0, '实际收到的命令 %r' % _HITS)
ck('⭐⭐⭐⭐⭐ 且确实发过 `p`（证明上面那条不是"什么都没发"的空过 ✓）',
   _HITS.count(b'p') >= 1, '实际收到的命令 %r' % _HITS)
ck('⭐ 健康服务上也不许杀（`_killed2` 空 ✓）', _killed2 == [], '%r' % _killed2)
ck('⭐ 健康服务返回 True ✓', _ret2 is True)

print()
print('=' * 72)
if FAILS:
    print('❌ %d 项未通过：%s' % (len(FAILS), '；'.join(FAILS[:6])))
    sys.exit(1)
print('✅ 全部通过')
sys.exit(0)
