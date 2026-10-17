# -*- coding: utf-8 -*-
"""mumu_capture.py · 直接调用 MuMu 官方极速截图接口（external_renderer_ipc.dll）

⭐ 这就是 MAA 的 `EmulatorExtras` 截图方式用的同一个接口：
     `nemu_connect` → `nemu_capture_display` → `nemu_disconnect`
   实测 MAA 走这条路 0.022 秒/张，而我们原来的 `adb exec-out screencap -p` 是 0.24 秒
   （MAA 自己的纯 adb 口径 Encode 反而 0.55 秒/张）⇒ 提速来自 MuMu 官方接口，不是 MAA。

DLL 导出（本机 `E:\\MuMu Player 12\\nx_main\\sdk\\external_renderer_ipc.dll`）：
    nemu_connect(path, instance_name, &handle)
    nemu_capture_display(handle, display_id, buffer_size, buffer, &width, &height)
    nemu_disconnect(handle)
    nemu_input_event_touch_down/up、nemu_input_event_key_down/up、nemu_input_text（点击注入，未启用）

用法：
    python mumu_capture.py                 # 自检：连、抓、存图、跟 adb 截图对比
    python mumu_capture.py --bench         # 只测速度（对比 adb）
"""
import argparse
import ctypes
import os
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）
import time
from ctypes import wintypes

import numpy as np


DEFAULT_DLL = ''
DEFAULT_HOME = ''
RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')
ADB = (os.environ.get('MAPBOT_ADB') or 'adb')


class MumuCapture:
    """MuMu 官方极速截图（0.02 秒/张，是 adb 的 10 倍以上）"""

    def __init__(self, dll=DEFAULT_DLL, home=DEFAULT_HOME, instance=None, display_id=0):
        self.display_id = display_id
        self.instance = instance
        self.dll = ctypes.CDLL(dll)
        self.dll.nemu_connect.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          ctypes.POINTER(ctypes.c_uint64)]
        self.dll.nemu_connect.restype = ctypes.c_int
        self.dll.nemu_disconnect.argtypes = [ctypes.c_uint64]
        self.dll.nemu_disconnect.restype = None
        self.dll.nemu_capture_display.argtypes = [ctypes.c_uint64, ctypes.c_uint,
                                                  ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte),
                                                  ctypes.POINTER(ctypes.c_int),
                                                  ctypes.POINTER(ctypes.c_int)]
        self.dll.nemu_capture_display.restype = ctypes.c_int
        self.handle = ctypes.c_uint64(0)
        self.rc = self.dll.nemu_connect(home, instance, ctypes.byref(self.handle))
        if self.rc != 0:
            raise RuntimeError('nemu_connect 失败 rc=%s（instance=%r）' % (self.rc, instance))
        self._buf = None
        self._w = self._h = 0

    def grab(self):
        """-> BGR ndarray（失败返回 None）"""
        if self._buf is None:
            self._buf = (ctypes.c_ubyte * (1920 * 1200 * 4))()
        w = ctypes.c_int(0)
        h = ctypes.c_int(0)
        rc = self.dll.nemu_capture_display(self.handle, self.display_id,
                                           len(self._buf), self._buf,
                                           ctypes.byref(w), ctypes.byref(h))
        if rc != 0 or w.value <= 0 or h.value <= 0:
            return None
        self._w, self._h = w.value, h.value
        arr = np.frombuffer(self._buf, dtype=np.uint8, count=self._w * self._h * 4)
        arr = arr.reshape(self._h, self._w, 4)
        return arr[:, :, :3].copy()          # MuMu 给的是 RGBA/BGRA，调用方按需换序

    def close(self):
        try:
            self.dll.nemu_disconnect(self.handle)
        except Exception:       # noqa: BLE001
            pass


def adb_grab(dev, out):
    import subprocess
    t0 = time.time()
    with open(out, 'wb') as f:
        subprocess.run([ADB, '-s', dev, 'exec-out', 'screencap', '-p'],
                       stdout=f, check=True, timeout=15)
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', default=DEFAULT_DLL)
    ap.add_argument('--home', default=DEFAULT_HOME)
    ap.add_argument('--instance', default=None, help='MuMu 实例名（默认不传 = 第一个实例）')
    ap.add_argument('--device', default='127.0.0.1:16384')
    ap.add_argument('--bench', action='store_true')
    a = ap.parse_args()
    os.makedirs(RUNS, exist_ok=True)
    import cv2

    mc = MumuCapture(a.dll, a.home, a.instance)
    print('nemu_connect OK，handle=%s' % mc.handle.value)
    img = mc.grab()
    print('一次抓图：%s' % (None if img is None else img.shape))
    if img is not None:
        cv2.imencode('.png', img)[1].tofile(os.path.join(RUNS, 'mumu_cap_raw.png'))
        # 通道序判定：跟 adb 那张比三种排列
        p = os.path.join(RUNS, '_adb_cmp.png')
        adb_grab(a.device, p)
        ref = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if ref is not None and ref.shape[:2] == img.shape[:2]:
            for name, cand in (('原样(BGRA?)', img), ('RGB->BGR', img[:, :, ::-1])):
                d = float(np.abs(cand.astype(int) - ref.astype(int)).mean())
                print('   与 adb 截图对比 %-12s 平均像素差 %.1f' % (name, d))
        else:
            print('   （adb 截图尺寸不同：%s，跳过通道序对比）'
                  % (None if ref is None else ref.shape))
    if a.bench:
        for _ in range(3):
            mc.grab()
        n = 20
        t0 = time.time()
        for _ in range(n):
            mc.grab()
        dt = (time.time() - t0) / n
        print('MuMu 极速截图：%.3f 秒/张（%d 次平均）' % (dt, n))
        t0 = time.time()
        adb_grab(a.device, os.path.join(RUNS, '_adb_cmp.png'))
        print('adb 截图      ：%.3f 秒/张' % (time.time() - t0))
        print('提速 %.1f 倍' % ((time.time() - t0) / dt if dt else 0))
    mc.close()


if __name__ == '__main__':
    sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                               errors='replace')
    main()
