# -*- coding: utf-8 -*-
"""fastcap.py · 极速截图客户端：从 MAA sidecar 取图（0.02 秒/张），失败自动退回 adb

sidecar = `maa_sidecar.py`（跑在 `_tmpman\\maa_venv`，用 MAA 的 EmulatorExtras 走 MuMu 官方
`external_renderer_ipc.dll`）。协议见 sidecar 文件头。

用法：
    from fastcap import FastCap
    fc = FastCap(device='127.0.0.1:16384', port=19999)
    img = fc.grab()          # -> BGR ndarray（1080x1920x3）；None = 不可用（调用方退回 adb）
    fc.close()

通道序：MAA 给的是 RGB，本模块**自动判定一次**（跟一张 adb 截图逐像素比），并让 sidecar 翻好。
"""
import os
import socket
import struct
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⭐ 2026-10-02：改走 `paths.py` 自动探测（原来写死本机 SDK 路径）
sys.path.insert(0, HERE)
import paths as P                                      # noqa: E402

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADB = P.ADB
CNW = 0x08000000 if os.name == 'nt' else 0
PORT_BASE = 19999
# ⭐⭐⭐⭐⭐ 2026-10-06 **二次修正**：取帧超时不能一刀切写死 1.5s —— **冷首帧会超**：
#   真机实测（`_tmpman/probe_cold_first_frame.py` / `probe_sidecar_deep.py`，设备在线）：
#       服务刚起 / 久闲后的**第一帧**：**5.69s / 3.98s / 2.34s**（MAA 截图管线首次预热）
#       预热之后的每一帧：**0.010s**
#   ⇒ 若一律 1.5s，**冷启动第一帧必然判失败** ⇒ 又退回 adb（慢 25 倍），
#     而这次失败**完全是我自己造成的** ✗（第一版只想着"卡死别白等 5s"）
#   ⇒ 分两档：**没预热过**给 6s（实测最慢 5.69s，留余量），**预热过**收紧到 1.5s
#     （正常 0.02s ⇒ 宽松 75 倍；卡死时不再每帧白等 ✓）
#   ⚠ 代价：sidecar 真卡死时，前 `FAST_MAX_FAIL`（3）帧各白等 6s ⇒ 之后关通道 + 冷却，
#     不再每帧白等 ✓（可接受；换来的是冷启动不再误判 ✗）
FAST_WARM_TIMEOUT = 6.0
FAST_HOT_TIMEOUT = 1.5


def port_for(device):
    """设备 → sidecar 端口（多开时按 MuMu 端口号错开：16384→19999、16416→20000…）"""
    try:
        p = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        return PORT_BASE
    idx = max(0, (p - 16384) // 32)
    return PORT_BASE + idx


class FastCap:
    def __init__(self, device, port=None, timeout=5.0):
        self.device = device
        self.port = port or port_for(device)
        self.sock = None
        self.checked = False
        self.ok = False
        self.timeout = timeout
        # ⭐ 是否已经拿到过完整一帧（决定用冷档 6s 还是热档 1.5s 超时，见 _grab_raw ✓）
        self.warmed = False

    # ---------- 连接 ----------
    def connect(self):
        if self.sock is not None:
            return True
        try:
            s = socket.create_connection(('127.0.0.1', self.port), timeout=self.timeout)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock = s
            return True
        except Exception:       # noqa: BLE001
            self.sock = None
            return False

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:   # noqa: BLE001
                pass
            self.sock = None

    # ---------- 取图 ----------
    def _recv_exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise IOError('sidecar 断开')
            buf += chunk
        return buf

    def _grab_raw(self):
        # ⭐⭐⭐⭐⭐ 2026-10-06 取帧阶段**分两档**超时（见 FAST_WARM_TIMEOUT 的实测表）：
        #   冷首帧实测最慢 **5.69s** ⇒ 没预热过必须给 6s，否则**第一帧必然失败** ✗
        #   预热过则是 0.010s/张 ⇒ 收紧到 1.5s（宽松 75 倍），卡死时不再每帧白等 5s ✓
        #   （超时后 `grab()` 返回 None ⇒ 走 mapbot 的自愈计数 + 退回 adb ✓）
        try:
            self.sock.settimeout(FAST_WARM_TIMEOUT if not self.warmed
                                 else FAST_HOT_TIMEOUT)
        except Exception:       # noqa: BLE001
            pass
        self.sock.sendall(b'g')
        head = self._recv_exact(16)
        if head[:4] != b'MUMU':
            raise IOError('sidecar 协议错')
        w, h, bpp = struct.unpack('<III', head[4:])
        if w == 0 or h == 0:
            return None
        data = self._recv_exact(w * h * bpp)
        arr = np.frombuffer(data, dtype=np.uint8, count=w * h * 3).reshape(h, w, 3)
        self.warmed = True      # ⭐ 拿到过完整一帧 ⇒ 之后按"热"档收紧超时 ✓
        return arr.copy()

    def grab(self):
        """-> BGR ndarray 或 None（None = 这条路不可用，调用方用 adb 兜底）"""
        if not self.connect():
            return None
        try:
            arr = self._grab_raw()
        except Exception:       # noqa: BLE001
            self.close()
            return None
        if arr is None:
            return None
        if not self.checked:
            self._check_order(arr)
        return arr

    def _check_order(self, arr):
        """跟一张 adb 截图逐像素比，决定要不要让 sidecar 翻通道"""
        self.checked = True
        try:
            tmp = os.path.join(HERE, 'runs', '_fastcap_cmp.png')
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with open(tmp, 'wb') as f:
                subprocess.run([ADB, '-s', self.device, 'exec-out', 'screencap', '-p'],
                               stdout=f, check=True, timeout=15, creationflags=CNW)
            ref = cv2.imdecode(np.fromfile(tmp, dtype=np.uint8), cv2.IMREAD_COLOR)
            if ref is None or ref.shape != arr.shape:
                return
            same = float(np.abs(arr.astype(int) - ref.astype(int)).mean())
            swap = float(np.abs(arr[:, :, ::-1].astype(int) - ref.astype(int)).mean())
            if swap < same - 5:            # 明显是反的 → 让 sidecar 翻
                self.sock.sendall(b's')
                self.sock.recv(32)
        except Exception:       # noqa: BLE001
            pass

    # ---------- 自检 ----------
    def bench(self, n=20):
        for _ in range(3):
            self.grab()
        t0 = time.time()
        img = None
        for _ in range(n):
            img = self.grab()
        dt = (time.time() - t0) / n
        return dt, (None if img is None else img.shape)


if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    dev = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1:16384'
    fc = FastCap(dev)
    dt, shape = fc.bench()
    print('设备 %s sidecar 端口 %d' % (dev, fc.port))
    print('极速截图：%.4f 秒/张  画面 %s' % (dt, shape))
    img = fc.grab()
    if img is not None:
        out = os.path.join(HERE, 'runs', 'fastcap_sample.png')
        cv2.imencode('.png', img)[1].tofile(out)
        print('已存样本 %s' % out)
    # adb 对照
    t0 = time.time()
    subprocess.run([ADB, '-s', dev, 'exec-out', 'screencap', '-p'],
                   stdout=open(os.path.join(HERE, 'runs', '_adb_cmp.png'), 'wb'),
                   check=True, timeout=15, creationflags=CNW)
    adt = time.time() - t0
    print('adb 截图：%.4f 秒/张  ⇒ 快 %.1f 倍' % (adt, adt / dt if dt else 0))
    fc.close()
