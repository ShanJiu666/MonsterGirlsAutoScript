# -*- coding: utf-8 -*-
"""verify_loopguard.py · 回归：设备锁 —— **Windows 回收 PID 不许把启动堵死**

用户 2026-10-05 报（原话）：「**怎么刚启动就退出了**」

真机取证（不是猜）
------------------
`runs/acc1/gui_20261005_031005/031039/031111_acc1.log` 三份都只有两行：

    ⚠ 设备锁被占用：{"pid": 20172, "device": "127.0.0.1:16384", "tag": "acc1", "at": "2026-10-05 02:42:21"}
    ⏹ 循环进程已退出（退出码 0）

根因链：
  ① 02:42 那把循环是**被强杀**的（用户在 02:43:21 手动阻止）⇒ finally 没跑 ⇒
     `.loop_16384.lock` 里留着 `pid=20172`；
  ② 03:07:24 Windows 把 **20172 回收给了 `conhost.exe`**（`Get-Process -Id 20172` 实测）；
  ③ 旧判据只查「PID 还在不在」（`tasklist` 命中就算活着）⇒ 判"有人占用" ⇒
     `loopguard.acquire()` 返回 False ⇒ 启动即退出（**一把早就死掉的锁把启动永久堵死**）✗✗

修法
----
`_pid_alive()` 加一道**身份确认**：PID 存在 **且** 它现在的命令行仍指向我们的启动器脚本
（`explore_loop.py` / `run_collect.py` / `auto_collect_until.py` / `scan_clean_maps.py`；
`.lock`/`.gui.lock` 另加 `bot_gui.py`）⇒ conhost / maa_sidecar / 无关 python 都不算占用 ✓
· 命令行**读得出但为空**（System/Idle 这类内核进程）⇒ 确定不是我们的 ⇒ 陈旧 ✓
· 查询本身失败（PowerShell 挂了）⇒ **保守当活着**（绝不冒"两个循环抢一台机器"的风险）✓
同判据也补进 `explore_loop.acquire_device_lock()`（第二套锁机制的同一个洞）。

本门禁（在**临时 RUNS 目录**上跑真 `loopguard`，不碰真 `runs/`、不碰模拟器）
------------------------------------------------------------------------
 ① 墓碑锁（pid=-1）/ 死 PID ⇒ 必须能接管
 ② ⭐ **活着的无关进程**（System=4 / 无标记 python）⇒ 必须能接管 ← **牙齿**
    （旧代码在这里恒 False = 报"占用"）
 ③ ⭐ **活着的我们的循环**（真起一个命令行带 `explore_loop.py` 的进程）⇒ 必须拒绝
    （反向牙齿：改宽了会双开抢点击）
 ④ `sweep_stale_locks()`：`.gui.lock` 里是活着的 bot_gui ⇒ **不许清**；
    是死/无关 PID ⇒ 必须清掉

用法：
    python verify_loopguard.py
"""
import json
import os
import shutil
import subprocess
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
import tempfile
import time

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import loopguard as LG                        # noqa: E402


FAILS = []
DEV = '127.0.0.1:16384'
TAG = 'vglock'


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _hold(marker, secs=25):
    """起一个"活着的、命令行里带 marker"的进程（复现"真有人占着"）"""
    return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(%d)' % secs,
                             os.path.join(HERE, marker)],
                            creationflags=LG.CNW)


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))


def main():
    print('=== 设备锁回归：Windows 回收 PID 不许把启动堵死（真 loopguard，临时目录）===')
    real_runs = LG.RUNS
    tmp = tempfile.mkdtemp(prefix='vglock_')
    LG.RUNS = tmp
    procs = []
    try:
        p = LG.lock_path(DEV, TAG)
        print('临时 RUNS：%s' % tmp)
        print()

        # ── ① 墓碑 / 死 PID ⇒ 必须能接管 ──
        print('【1】墓碑锁 / 死 PID ⇒ 必须能接管')
        for tag_, body in (('墓碑 pid=-1', {'pid': -1, 'released': True}),
                           ('死 PID 999999', {'pid': 999999}),
                           ('空锁文件', '')):
            _write(p, body)
            ok, info = LG.acquire(DEV, TAG)
            ck('%s ⇒ acquire 成功' % tag_, ok, '返回 %s' % (info,))
            LG.release(DEV, TAG)

        # ── ② ⭐ 牙齿：活着的**无关**进程 ⇒ 必须能接管（旧代码在这里必红）──
        print()
        print('【2】⭐ 活着的无关进程占着锁 ⇒ 必须**当作陈旧锁接管**')
        others = [('System PID 4', 4)]
        ch = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)'],
                              creationflags=LG.CNW)
        procs.append(ch)
        time.sleep(1.5)
        others.append(('无标记 python PID %d' % ch.pid, ch.pid))
        for name, pid in others:
            _write(p, {'pid': pid, 'device': DEV, 'tag': TAG,
                       'at': time.strftime('%Y-%m-%d %H:%M:%S')})
            ck('%s 的命令行确实不像我们的启动器' % name,
               not LG.pid_is_ours(pid, loop_only=True),
               'cmdline=%r' % (LG.pid_cmdline(pid),))
            ok, info = LG.acquire(DEV, TAG)
            ck('%s ⇒ acquire **接管成功**（旧代码判"占用"⇒ 启动即退出 ✗）' % name,
               ok, '返回 %s' % (info,))
            LG.release(DEV, TAG)

        # ── ③ ⭐ 反向牙齿：真的循环在跑 ⇒ 必须拒绝 ──
        print()
        print('【3】⭐ 真的循环在跑（命令行带 explore_loop.py）⇒ 必须**拒绝**（不许双开）')
        hold = _hold('explore_loop.py')
        procs.append(hold)
        time.sleep(1.5)
        ck('它被判成"我们的循环"', LG.pid_is_ours(hold.pid, loop_only=True),
           'cmdline=%r' % (LG.pid_cmdline(hold.pid),)[:90])
        _write(p, {'pid': hold.pid, 'device': DEV, 'tag': TAG})
        ok, info = LG.acquire(DEV, TAG)
        ck('acquire 必须**失败**（返回占用信息 pid=%d）' % hold.pid,
           (not ok) and int((info or {}).get('pid') or 0) == hold.pid,
           'ok=%s info=%s' % (ok, info))
        ck('_pid_alive(真循环) 为真', LG._pid_alive(hold.pid, loop_only=True))
        ck('_pid_alive(真循环, 但按"窗口锁"口径) 也认（bot_gui 名单之外的脚本名）',
           LG._pid_alive(hold.pid, loop_only=False))
        hold.kill()

        # ── ④ sweep_stale_locks：窗口锁不许误清 ──
        print()
        print('【4】sweep_stale_locks()：活着的 bot_gui 不许清、死/无关的必须清')
        gui = _hold('bot_gui.py')
        procs.append(gui)
        time.sleep(1.5)
        d = os.path.join(tmp, TAG)
        _write(os.path.join(d, '.gui.lock'), str(gui.pid))
        _write(os.path.join(d, '.lock'), '999999')
        LG.sweep_stale_locks()
        kept = open(os.path.join(d, '.gui.lock'), encoding='utf-8').read().strip()
        gone = open(os.path.join(d, '.lock'), encoding='utf-8').read().strip()
        ck('活着的 bot_gui 绑定锁**保留**（pid 还在）', kept == str(gui.pid),
           '实际 %r' % (kept,))
        ck('死 PID 的绑定锁被清空', gone == '', '实际 %r' % (gone,))
        gui.kill()

        # ── ⑤ 保守性：查询失败不许放行 ──
        print()
        print('【5】命令行**查不出来**（PowerShell 失败/不可用）⇒ 保守当活着（宁可手清一次锁）')
        oi = LG.pid_cmdline
        LG.pid_cmdline = lambda pid: None
        try:
            ck('pid_is_ours 在查不出命令行时返回 True', LG.pid_is_ours(4) is True)
            ck('_pid_alive 在查不出命令行时返回 True', LG._pid_alive(4) is True)
        finally:
            LG.pid_cmdline = oi
        print('  （旧库里的"不确定就当活着"这条**没变**：不确定 ≠ 可以接管）')
    finally:
        for q in procs:
            try:
                q.kill()
            except Exception:       # noqa: BLE001
                pass
        LG.RUNS = real_runs
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('=' * 68)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：无关进程占着锁 ⇒ 接管；真循环在跑 ⇒ 拒绝；查不出 ⇒ 保守拒绝')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
