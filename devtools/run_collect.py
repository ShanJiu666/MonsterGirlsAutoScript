# -*- coding: utf-8 -*-
"""run_collect.py · 采图专用启动器（**只做「进图 → 存首帧 → 退图」**）

用户 2026-09-27 原话：
    「能两个模拟器一起存真盘截图么。实例B模拟器那个我打算只让你进图截图退图，拿图片快一些」
    「再开一个新脚本吧」「用新脚本抓另一个模拟器吧」

为什么要单独一个脚本：
    `explore_loop.py` 原来的唯一路径是**推完整张图**（揭格/打怪/买/补点），
    ≈ 4 分钟才出 1 张首帧。采图模式（`--collect-only`）只做三步，≈ 30 秒 1 张 ⇒ 快 ~8 倍。

⚠ 成本（务必知悉）：
    进图**瞬间**就扣 **25 体力**（实测两次：2282→2257、2180→2155，都恰好 25），
    退图**不退**体力 ⇒ 这是「拿体力换图片」，不会白嫖。
    `--min-stamina` 低于就不进图，直接收工（默认 25）。

用法（双击 `collect_frames.bat`，或直接跑）：
    python run_collect.py                              # 实例B 16416 / tag=acc2 / 最多 50 张
    python run_collect.py --maps 10                    # 只采 10 张
    python run_collect.py --device 127.0.0.1:16384 --tag ""   # 改成主号（空 tag = 公共目录）
    python run_collect.py --no-sidecar                 # 不启极速截图（退回 adb，慢一些）

存图位置：`runs/<tag>/r_<HHMMSS>_0.png`（`--tag acc2` ⇒ `runs/acc2/`）
"""
import argparse
import os
import socket
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
import time


sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, ROOT)
# 解释器：本脚本要在**同一个 venv** 里起子进程，所以默认用当前解释器
PY = (os.environ.get('MAPBOT_PY')
      or os.path.join(HERE, '_maa_venv', 'Scripts', 'python.exe'))
if not os.path.exists(PY):
    PY = sys.executable
try:                                   # ⭐ 2026-10-02：adb / MAA 路径一律走 paths.py 自动探测
    import paths as _paths
    ADB = _paths.ADB
    MAA_PY = _paths.MAA_PY
except Exception:                       # noqa: BLE001  paths 不可用时才退回
    MAA_PY = (os.environ.get('MAPBOT_MAA_PY')
              or os.path.join(HERE, '_maa_venv', 'Scripts', 'python.exe'))
    ADB = os.environ.get('MAPBOT_ADB') or 'adb'
CNW = 0x08000000 if os.name == 'nt' else 0
RUNS = os.path.join(HERE, 'runs')
# 🚫 绝不碰的设备（用户 2026-09-25 明确：`emulator-5554` 不是我们的模拟器）
FORBIDDEN = ('emulator-5554',)


def say(m=''):
    print(m, flush=True)


def port_for(device):
    """设备 → sidecar 端口（与 fastcap.port_for / bot_gui.sidecar_port 同一套算法）"""
    try:
        p = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        return 19999
    return 19999 + max(0, (p - 16384) // 32)


def adb(*args, timeout=20):
    try:
        r = subprocess.run([ADB] + list(args), capture_output=True, timeout=timeout,
                           creationflags=CNW)
        return (r.stdout or b'').decode('utf-8', 'replace')
    except Exception as e:      # noqa: BLE001
        return ''


def ensure_device(device):
    """确认设备在线（离线就先 connect 一次）"""
    if device in FORBIDDEN:
        say('🛑 设备 %s 是禁用设备（不是我们的模拟器），拒绝运行 ✗' % device)
        return False
    out = adb('devices')
    if device in out and 'device' in out.split(device, 1)[1].split('\n')[0]:
        return True
    say('… %s 不在线，尝试连接' % device)
    adb('connect', device)
    time.sleep(1)
    out = adb('devices')
    ok = device in out
    say(('✓ %s 已连接' % device) if ok else ('✗ 连不上 %s —— 先把模拟器开起来、游戏登录好' % device))
    return ok


def _sidecar_ping(port, timeout=1.0):
    """sidecar **进程存活**探测：发 `p` 收 `pong`（协议见 `maa_sidecar.py`；**不碰设备** ✓）

    ⭐⭐⭐⭐⭐ 2026-10-06 与 `bot_gui._sidecar_ping` **同一口径**（别再退回裸 TCP ✗）：
      · 旧实现只做 `socket.create_connection()` ⇒ 端口开着就算"已在运行"，
        而**卡死**的 sidecar 端口也是开着的 ⇒ bot 对着取不出帧的服务白等 ✗
      · ⚠ 但**也不能**用「能不能取到一帧」判存活：实测（`_tmpman/probe_ping_vs_grab.py`）
        设备没开时 `g` 恒不回、而服务**完全健康** ⇒ 拿它判死会**误杀健康服务** ✗✗
      ⇒ 存活只认 `pong` ✓（`g` 那一路留给 fastcap 自己，失败就退 adb，不影响功能 ✓）
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


def ensure_sidecar(device, timeout=30):
    """极速截图 sidecar（MAA 官方接口，0.02~0.06 秒/张）；起不来就退回 adb，不影响功能

    ⚠ 2026-10-06：判据统一成 `p`/`pong`（存活），**不再**用裸 TCP（见 `_sidecar_ping`）✓
    """
    port = port_for(device)
    if _sidecar_ping(port):
        say('✓ 极速截图服务已在运行（端口 %d，进程存活 ✓）' % port)
        return True
    if not os.path.exists(MAA_PY):
        say('⚠ 没有 MAA 环境 → 用 adb 截图（慢一些，功能不受影响）')
        return False
    try:
        idx = max(0, (int(str(device).split(':')[-1]) - 16384) // 32)
    except Exception:       # noqa: BLE001
        idx = 0
    say('… 启动极速截图服务（端口 %d，首次约 3~20 秒）' % port)
    try:
        subprocess.Popen([MAA_PY, os.path.join(ROOT, 'devtools', 'maa_sidecar.py'),
                          '--device', device, '--port', str(port), '--mumu-index', str(idx)],
                         cwd=HERE, creationflags=CNW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:      # noqa: BLE001
        say('⚠ 极速截图服务启动失败：%r → 用 adb 截图' % e)
        return False
    for i in range(timeout):
        time.sleep(1)
        if _sidecar_ping(port):
            say('✓ 极速截图服务已启动（端口 %d，%d 秒）' % (port, i + 1))
            return True
    say('⚠ 极速截图服务没起来 → 用 adb 截图')
    return False


def main():
    ap = argparse.ArgumentParser(description='采图模式启动器（进图 → 存首帧 → 退图）')
    ap.add_argument('--device', default='127.0.0.1:16416',
                    help='adb 设备号（默认实例B 16416；主号是 16384）')
    ap.add_argument('--tag', default='acc2',
                    help='实例名（隔离日志/截图目录；空字符串 = 公共 runs/）')
    ap.add_argument('--maps', type=int, default=50, help='最多采几张（默认 50）')
    ap.add_argument('--min-stamina', type=int, default=25,
                    help='进图前体力下限（默认 25 = 一张图的进图费）')
    ap.add_argument('--no-sidecar', action='store_true', help='不启极速截图（退回 adb）')
    ap.add_argument('--auto-supply', action='store_true',
                    help='体力 < --min-stamina 时自动进背包使用「结实补给」(+500)，用完为止')
    ap.add_argument('--yes', action='store_true', help='跳过开跑前的确认（批处理用）')
    a = ap.parse_args()

    _dir = os.path.join(RUNS, a.tag) if a.tag else RUNS
    say('')
    say('════════ 采图模式（只进图截图退图）════════')
    say('  设备      ：%s' % a.device)
    say('  实例名    ：%s' % (a.tag or '（空 = 公共目录）'))
    say('  存图目录  ：%s' % _dir)
    say('  最多采    ：%d 张' % a.maps)
    say('  ⚠ 每张图照旧扣 25 体力（进图瞬间扣、退图不退）⇒ 最多花 %d 体力'
        % (a.maps * 25))
    say('  自动补给  ：%s' % ('✓ 开（体力 <%d 自动吃「结实补给」+500，用完为止）'
                              % a.min_stamina if a.auto_supply else '✗ 关'))
    say('  ⚠ 跑的时候别手动点模拟器（会互相抢点击）；要停就按 Ctrl+C')
    say('══════════════════════════════════════')
    say('')

    if not ensure_device(a.device):
        return 2
    if not a.no_sidecar:
        ensure_sidecar(a.device)

    cmd = [PY, os.path.join(HERE, 'explore_loop.py'),
           '--collect-only', '--device', a.device,
           '--maps', str(a.maps), '--min-stamina', str(a.min_stamina)]
    if a.auto_supply:
        cmd += ['--auto-supply']
    if a.tag:
        cmd += ['--tag', a.tag]
    say('▶ 开跑：%s' % ' '.join('"%s"' % c if ' ' in c else c for c in cmd[1:]))
    say('')
    t0 = time.time()
    try:
        rc = subprocess.call(cmd, cwd=HERE)
    except KeyboardInterrupt:
        say('\n⏹ 用户中断')
        rc = 130
    say('')
    say('==== 采图结束（%.0f 秒，退出码 %s）；图片在 %s' % (time.time() - t0, rc, _dir))
    try:
        fs = sorted(f for f in os.listdir(_dir) if f.startswith('r_') and f.endswith('_0.png'))
        say('     该目录现有首帧 %d 张（最近 5 张：%s）'
            % (len(fs), ', '.join(fs[-5:]) if fs else '无'))
    except Exception:           # noqa: BLE001
        pass
    say('')
    return rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n⏹ 已中断')
        sys.exit(130)
