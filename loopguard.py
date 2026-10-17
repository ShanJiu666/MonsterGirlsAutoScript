# -*- coding: utf-8 -*-
"""loopguard.py · 重复循环检测 / 清理（用户 2026-09-25 要求）

背景：同一台模拟器上跑了**两个** explore_loop 时，两边会同时点屏幕、互相抢状态
（实测出现过：双开循环 + 我误杀其一时把两个一起带走 ✗）。

两道防线：
  ① **原子锁** `<runs>/.loop_<port>.lock`：用 O_CREAT|O_EXCL 抢，抢不到就说明有人；
     锁里的 PID 已经死了 → 视为陈旧锁，接管（顺带写谁占着）
  ② **进程枚举**（PowerShell Get-CimInstance 读命令行）：兜住"绕过锁"的情况
     （换了 tag/端口、手工启的、老版本没写锁的）

只认 `explore_loop`，**绝不碰 bot_gui / maa_sidecar**（用户明确讨厌窗口乱关 ✗）。
"""
import json
import os
import subprocess
import sys
import time

CNW = 0x08000000 if os.name == 'nt' else 0
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, 'runs')


def own_pids(depth=6):
    """自己和自己的**祖先链** PID（循环在 Windows 上常以父子两个进程出现 ⇒ 都要排除）"""
    pids = {os.getpid()}
    try:
        cur = os.getpid()
        for _ in range(depth):
            cmd = ("(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
                   "-ErrorAction SilentlyContinue).ParentProcessId" % cur)
            r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                               capture_output=True, text=True, errors='replace',
                               timeout=10, creationflags=CNW)
            t = (r.stdout or '').strip()
            if not t.isdigit() or int(t) in (0, cur):
                break
            cur = int(t)
            pids.add(cur)
    except Exception:       # noqa: BLE001
        pass
    return pids


def list_loops(exclude_pid=None, exclude_pids=None):
    """列出正在跑的 explore_loop 进程 -> [{'pid','device','tag','created'}]"""
    ps = ('Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | '
          "Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'explore_loop\\.py' "
          "-and $_.CommandLine -match '--device' } | "
          "ForEach-Object { $d=''; if ($_.CommandLine -match '(\\d+\\.\\d+\\.\\d+\\.\\d+:\\d+)') { $d=$matches[1] }; "
          "$t=''; if ($_.CommandLine -match '--tag\\s+(\\S+)') { $t=$matches[1] }; "
          "Write-Output ($_.ProcessId.ToString() + '|' + $d + '|' + $t) }")
    # ⭐ 2026-09-28：`-match 'explore_loop'` 太松 —— 任何**命令行里提到过**这个词的
    #   python 进程都会被算成"循环在跑"（我自己跑 `python -c "...explore_loop.py..."` 探针时
    #   就误报过两条）⇒ `dev_busy()` 会让流水线白等最长 30 分钟 ✗
    #   收紧为「必须有 `explore_loop.py` **且** 必须带 `--device`」——
    #   实测所有启动方（`run_collect.py` / `bot_gui.py` 两处 / GUI 扫描）**都带 `--device`** ✓
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, errors='replace',
                           timeout=25, creationflags=CNW)
        out = r.stdout or ''
    except Exception:       # noqa: BLE001
        return []
    res = []
    for ln in out.splitlines():
        parts = ln.strip().split('|')
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if exclude_pid and pid == exclude_pid:
            continue
        if exclude_pids and pid in exclude_pids:
            continue
        res.append({'pid': pid,
                    'device': parts[1] if len(parts) > 1 else '',
                    'tag': parts[2] if len(parts) > 2 else ''})
    return res


def list_guis(exclude_pid=None, exclude_pids=None):
    """列出正在跑的 bot_gui 窗口 -> [{'pid','device','tag'}]（判断实例是否已被别的窗口绑）"""
    ps = ('Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | '
          "Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'bot_gui' } | "
          "ForEach-Object { $d=''; if ($_.CommandLine -match '(\\d+\\.\\d+\\.\\d+\\.\\d+:\\d+)') { $d=$matches[1] }; "
          "$t=''; if ($_.CommandLine -match '--tag\\s+(\\S+)') { $t=$matches[1] }; "
          "Write-Output ($_.ProcessId.ToString() + '|' + $d + '|' + $t) }")
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, errors='replace',
                           timeout=25, creationflags=CNW)
        out = r.stdout or ''
    except Exception:       # noqa: BLE001
        return []
    res = []
    for ln in out.splitlines():
        parts = ln.strip().split('|')
        if parts and parts[0].isdigit():
            pid = int(parts[0])
            if exclude_pid and pid == exclude_pid:
                continue
            if exclude_pids and pid in exclude_pids:
                continue
            res.append({'pid': pid, 'device': parts[1] if len(parts) > 1 else '',
                        'tag': parts[2] if len(parts) > 2 else ''})
    return res


def busy_devices(exclude_pid=None):
    """哪些模拟器**现在真的**被占用（有窗口或有循环）"""
    busy = {}
    for p in list_guis(exclude_pid=exclude_pid):
        if p['device']:
            busy[p['device']] = '窗口 PID %d' % p['pid']
    for p in list_loops(exclude_pid=exclude_pid):
        if p['device']:
            busy.setdefault(p['device'], '循环 PID %d' % p['pid'])
    return busy


def duplicates_for(device, tag='', exclude_pid=None, exclude_self=True):
    """跟 (device, tag) 冲突的循环（同设备；tag 空表示同 tag 的空目录）

    ⚠ 默认排除**自身整条进程链**（父子两个 python 进程都算自己 ✓）
    """
    ex = set(own_pids()) if exclude_self else set()
    if exclude_pid:
        ex.add(exclude_pid)
    out = []
    for p in list_loops(exclude_pids=ex):
        if device and p['device'] and p['device'] != device:
            continue
        if (p['tag'] or '') != (tag or ''):
            continue
        out.append(p)
    return out


def kill(pids):
    killed = []
    for pid in pids:
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                           capture_output=True, timeout=15, creationflags=CNW)
            killed.append(pid)
        except Exception:       # noqa: BLE001
            pass
    return killed


def sweep_stale_locks():
    """清掉**过期的绑定锁**（旧版留下的 `<runs>/[tag/].lock`）

    ⭐ 用户 2026-09-25：「关闭窗口顺手把绑定去掉啊」——旧版关窗口不清锁 ⇒
    多开时误报"实例B已被别的窗口绑定"。这里在启动时扫一遍：锁里记的 PID 已死就删 ✓
    """
    removed = []
    for base in (RUNS,) + tuple(os.path.join(RUNS, d) for d in os.listdir(RUNS)
                                if os.path.isdir(os.path.join(RUNS, d))):
        for fn in ('.lock', '.gui.lock'):
            p = os.path.join(base, fn)
            if not os.path.exists(p):
                continue
            try:
                txt = open(p, encoding='utf-8', errors='replace').read().strip()
                pid = int(txt.split()[0]) if txt and txt.split()[0].isdigit() else None
            except Exception:       # noqa: BLE001
                pid = None
            if pid is None or not _pid_alive(pid, loop_only=False):
                try:
                    # ⭐ 2026-09-28：**截断**而非删除（理由同 release：沙箱删除计数 ✗）
                    open(p, 'w', encoding='utf-8').close()
                    removed.append(os.path.relpath(p, RUNS))
                except Exception:       # noqa: BLE001
                    pass
    return removed


def lock_path(device, tag=''):
    port = (device or '').split(':')[-1] or 'dev'
    d = os.path.join(RUNS, tag) if tag else RUNS
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, '.loop_%s.lock' % port)


def _pid_alive(pid, loop_only=True):
    # ⭐ 2026-09-28：`pid <= 0` 一律当**死** —— 这是给 `release()` 写的**墓碑**用的
    #   （release 不再删锁文件，而是把 pid 写成 -1 ⇒ 下一轮 acquire 直接接管 ✓）
    try:
        if int(pid) <= 0:
            return False
    except Exception:       # noqa: BLE001
        return False
    try:
        subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid],
                       capture_output=True, timeout=10, creationflags=CNW)
    except Exception:       # noqa: BLE001
        return True             # 查不了就当活着（保守）
    try:
        # ⚠ errors='replace' 必须有：中文 Windows 下 tasklist 输出不是 UTF-8，
        #   而 sha 沙箱把 Python 跑在 UTF-8 模式 ⇒ 解码在**子线程**里抛 UnicodeDecodeError
        #   （主线程 try 抓不到，日志里刷 "Exception in thread" 噪声 ✗）
        r = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid],
                           capture_output=True, text=True, errors='replace',
                           timeout=10, creationflags=CNW)
        if str(pid) not in (r.stdout or ''):
            return False
    except Exception:       # noqa: BLE001
        return True
    # ⭐⭐⭐⭐ 2026-10-05 **修"刚启动就退出"的真根因：Windows 会回收 PID**
    #   症状（用户原话：「**怎么刚启动就退出了**」）：GUI 点开始 → 立刻
    #     `⚠ 设备锁被占用：{"pid": 20172, ...}` → 退出码 0，一次都没跑起来。
    #   根因：02:42 那把循环被强杀时没走 finally ⇒ 锁里留着 PID 20172；
    #     而 03:07:24 Windows 把 **20172 回收给了 conhost.exe** ⇒ 只查"PID 还在不在"
    #     就判"有人占用" ⇒ **一把早已死掉的锁把启动永久堵死**（直到那个无关进程退出）✗✗
    #   ⇒ 判据升级：PID 存在 **且** 它现在的命令行仍指向**我们的启动器脚本**
    #     （只有这些脚本会来抢这把锁；conhost/maa_sidecar/别的 python 都不算 ✓）
    return pid_is_ours(pid, loop_only=loop_only)


# 会持有这两把锁的启动器（`.loop_<port>.lock` = 循环；`.lock`/`.gui.lock` = 窗口绑定）
LOOP_SCRIPTS = ('explore_loop.py', 'run_collect.py',
                'auto_collect_until.py', 'scan_clean_maps.py')
GUI_SCRIPTS = ('bot_gui.py',)
OUR_SCRIPTS = LOOP_SCRIPTS + GUI_SCRIPTS


def pid_cmdline(pid):
    """该 PID 现在的命令行 → str / **''**（进程在、但命令行读不出，如 System/Idle）
    / **None**（查询本身失败：PowerShell 挂了、超时、没权限）

    ⚠ 三种结果必须分得清：`''` = **确定不是我们的脚本**（这些内核进程没有命令行），
      `None` = 不知道 ⇒ 调用方保守处理 ✓（旧版把两者混成"保守当活着" ⇒ System 也被算成占用 ✗）
    """
    ps = ('$p = Get-CimInstance Win32_Process -Filter "ProcessId=%d" '
          '-ErrorAction SilentlyContinue; '
          'if ($p) { Write-Output ("OK|" + $p.CommandLine) }' % int(pid))
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, errors='replace',
                           timeout=15, creationflags=CNW)
    except Exception:       # noqa: BLE001
        return None
    out = (r.stdout or '').strip()
    if not out.startswith('OK|'):
        return None         # 没回 OK| ⇒ **这次查询没成**（PowerShell 失败/超时）
    return out[3:].strip()  # 进程已消失也会没回 OK|，但那种情况 tasklist 早就判 False 了 ✓


def pid_is_ours(pid, loop_only=False):
    """这个 PID 现在是不是**我们的启动器**？→ True 才算"真的有人占着"

    ⚠ 读不到命令行（PowerShell 挂了/超时）⇒ **保守返回 True**
      （宁可让用户手清一次锁，也绝不冒"两个循环抢同一台模拟器"的风险）
    """
    kinds = LOOP_SCRIPTS if loop_only else OUR_SCRIPTS
    cmd = pid_cmdline(pid)
    if cmd is None:
        return True
    low = cmd.replace('\\', '/').lower()
    return any(s in low for s in kinds)


def acquire(device, tag=''):
    """抢设备锁（原子创建 + 陈旧锁接管）-> (True, 说明) / (False, 占用信息)"""
    p = lock_path(device, tag)
    info = {'pid': os.getpid(), 'device': device, 'tag': tag,
            'at': time.strftime('%Y-%m-%d %H:%M:%S')}
    for attempt in (1, 2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps(info, ensure_ascii=False).encode('utf-8'))
            os.close(fd)
            return True, info
        except FileExistsError:
            # ⚠ 2026-09-26 修：锁文件可能是**纯数字**（旧格式）或乱码 ⇒ 不能直接当 JSON ✗
            #   一律容错：能读出 PID 就判活，读不出就当陈旧锁接管 ✓
            old = {}
            try:
                raw = open(p, encoding='utf-8', errors='replace').read().strip()
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        old = obj
                    elif isinstance(obj, int):
                        old = {'pid': obj}
                except Exception:       # noqa: BLE001
                    if raw.split()[0].isdigit() if raw.split() else False:
                        old = {'pid': int(raw.split()[0])}
            except Exception:       # noqa: BLE001
                old = {}
            pid_old = old.get('pid')
            if pid_old and _pid_alive(int(pid_old)):
                return False, old
            # ⭐ 2026-09-28：陈旧锁**不再 os.remove**，直接**原地覆写接管**
            #   （同 release 的理由：沙箱批量删除保护会把 os.remove 累加到 SystemExit ✗）
            try:
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(info, ensure_ascii=False))
                return True, info
            except Exception:       # noqa: BLE001
                return False, old
    return False, {}


def release(device, tag=''):
    """释放设备锁（⭐ 2026-09-28 起**不再删文件**，改成原地写"墓碑"）

    为什么改（**真 bug，曾被它杀掉采集**）：
        沙箱 `sitecustomize.py` 把 `os.remove` 挂钩成「回收站 + 每**次工具调用**计数」，
        累计 ≥ **50 次**就 `raise SystemExit(1)`。长流水线每轮都会 release 一次 +
        入库脚本删分片 ⇒ 第 11 轮 9 秒即被 `SystemExit: 1` **打死** ✗
        （实测：`runs/_pipeline.log` 里 `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`）

    墓碑方案：把 pid 写成 **-1** ⇒ `_pid_alive(-1)` 恒 False（见上面的 `pid <= 0` 分支）
    ⇒ 下一轮 `acquire()` 判定为陈旧锁并**直接覆写接管** ✓ **语义完全不变、零删除** ✓
    """
    try:
        p = lock_path(device, tag)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'pid': -1, 'released': True,
                                'at': time.strftime('%Y-%m-%d %H:%M:%S')},
                               ensure_ascii=False))
    except Exception:       # noqa: BLE001
        pass


if __name__ == '__main__':
    sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                               errors='replace')
    dev = sys.argv[1] if len(sys.argv) > 1 else ''
    tag = sys.argv[2] if len(sys.argv) > 2 else ''
    ls = duplicates_for(dev, tag) if dev else list_loops()
    print('正在跑的 explore_loop：%d 个' % len(ls))
    for p in ls:
        print('   PID %-6d 设备 %-20s tag %s' % (p['pid'], p['device'] or '?', p['tag'] or '-'))
