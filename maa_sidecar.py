# -*- coding: utf-8 -*-
"""maa_sidecar.py · 极速截图服务（跑在装了 MaaFw 的独立 venv 里）

背景（2026-09-25 实测）：
    adb exec-out screencap -p       0.24 秒/张（我们原来的口径）
    MAA Encode（纯 adb 口径）        0.55 秒/张（比我们还慢）
    MAA EmulatorExtras（MuMu 官方）  **0.022 秒/张** ← 走 MuMu 的 external_renderer_ipc.dll
MaaFw 需要 numpy 2.x，跟 mapbot venv（airtest 钉住 numpy 1.x）冲突 ⇒ 让它单独一个进程，
我们的 bot 通过本地 socket 取图。

协议（TCP 127.0.0.1:19999）：
    请求 1 字节：b'g' = 抓一帧；b'p' = ping；b'q' = 退出
    应答（'g'）：16 字节头 `MUMU` + w(u32) + h(u32) + bpp(u32) + 原始 BGR 字节
               （w=h=0 表示失败）

用法（必须用 maa_venv 的 python）：
    <MAA venv python> maa_sidecar.py --device 127.0.0.1:16384 --port 19999
    ... --tag acc2 --device 127.0.0.1:16416 --port 20000     # 多开第二个号
"""
import argparse
import io
import os
import socket
import struct
import sys

import threading
import time

# ⚠ 本文件住在**仓根**（它是运行时组件，不是排障脚本）：
#   `bot_gui.py` 起 sidecar 时把 cwd 设成仓根、用绝对路径调本文件。
#   `ROOT` = 仓根 = 本文件所在目录 —— 下面 `import paths` 要靠它。
#   ⚠ 这个变量必须**在本文件里定义**：早前把它移进 devtools/ 时我给那段
#     注入了「ROOT = 上一级」，后来移回仓根又剥掉了 ⇒ 结果 ROOT 未定义 ⇒
#     `sys.path.insert(0, ROOT)` 抛 NameError ⇒ `import paths` 失败 ⇒
#     ADB 退回裸 'adb' ⇒ sidecar 起不来 ⇒ **静默退回 adb 截图（慢 25 倍）** ✗✗
ROOT = os.path.dirname(os.path.abspath(__file__))
HERE = ROOT


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ⭐⭐ 2026-10-02 修「换机就废」：原来这里写死本机布局
#     （MuMu 装在 E 盘、SDK 装在 D 盘）⇒ 朋友机器上一条都不成立，sidecar 直接起不来，
#     悄悄退回 adb 截图（**慢 22 倍**：实测 0.28s/张 vs 0.0128s/张）。
#     2026-10-02 那轮 `paths.py` 改造漏了这个文件（它跑在独立 maa_venv 里，容易被漏）。
#     现在统一走 paths 探测 ✓（paths.py 只 import glob/os/subprocess，纯 stdlib，
#     **在 maa_venv 里能安全 import**，不会碰到 numpy 2.x 冲突）。
#     环境变量兜底：MAPBOT_ADB / MAPBOT_MUMU_HOME（见 paths.py 顶部说明）。
try:
    sys.path.insert(0, ROOT)
    import paths as P                                  # noqa: E402
except Exception:            # noqa: BLE001
    P = None

ADB = (P.ADB if P else (os.environ.get('MAPBOT_ADB') or 'adb'))


def _mumu_home():
    """MuMu 安装根目录（找得到就用真路径，找不到退回旧的 E 盘写法）"""
    if P:
        homes = P._mumu_homes()
        if homes:
            return homes[0]
    return ''


MUMU_HOME = os.environ.get('MAPBOT_MUMU_HOME') or _mumu_home()


class Capture:
    def __init__(self, device, mumu_index=0):
        # ⚠ 2026-10-02：探测失败要**说清楚是哪一环**，别再静默退回 adb 让人一头雾水。
        #   （原来写死路径时，MuMu 装别处 ⇒ 这里抛的异常只被 subprocess 吞掉 ⇒
        #     GUI 那边只看到"用 adb 截图（慢一些）"，完全不知道为什么 ⚠）
        if not os.path.exists(ADB):
            raise RuntimeError('找不到 adb：%s（装 Android SDK，或设环境变量 MAPBOT_ADB）'
                               % ADB)
        if not os.path.isdir(MUMU_HOME):
            raise RuntimeError('找不到 MuMu 安装目录：%s（或设 MAPBOT_MUMU_HOME）'
                               % MUMU_HOME)
        from maa.toolkit import Toolkit
        from maa.controller import AdbController
        from maa.define import (MaaAdbScreencapMethodEnum as S,
                                MaaAdbInputMethodEnum as I)
        Toolkit.init_option(os.path.join(HERE, 'maa_log'))
        cfg = {'extras': {'mumu': {'enable': True, 'index': mumu_index,
                                   'path': MUMU_HOME}}}
        self.ctl = AdbController(ADB, device, int(S.EmulatorExtras), int(I.EmulatorExtras),
                                 config=cfg)
        if not self.ctl.post_connection().wait().succeeded:
            raise RuntimeError('MAA 连接失败（设备 %s / MuMu 实例 %s / MuMu 目录 %s）'
                               % (device, mumu_index, MUMU_HOME))
        self.ctl.set_screenshot_use_raw_size(True)
        # 通道序由**客户端**判定（客户端有 cv2；本进程只装了 MaaFw+numpy）：
        # 客户端测好后用 's' 命令告诉我们要不要翻通道
        self.swap = False

    def grab(self):
        img = self.ctl.post_screencap().wait().get()
        if img is None:
            return None
        if self.swap:
            img = img[:, :, ::-1]
        return img


def serve(cap, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(4)
    print('listening 127.0.0.1:%d' % port, flush=True)
    while True:
        conn, _addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(cap, conn), daemon=True).start()


def handle(cap, conn):
    try:
        while True:
            cmd = conn.recv(1)
            if not cmd:
                return
            if cmd == b'q':
                conn.sendall(b'bye')
                os._exit(0)
            if cmd == b'p':
                conn.sendall(b'pong')
                continue
            if cmd == b's':                     # 切换通道序（客户端测好后告诉我们）
                cap.swap = not cap.swap
                conn.sendall(b'swap=%d' % (1 if cap.swap else 0))
                continue
            if cmd == b'g':
                img = cap.grab()
                if img is None:
                    conn.sendall(b'MUMU' + struct.pack('<III', 0, 0, 0))
                    continue
                h, w = img.shape[:2]
                conn.sendall(b'MUMU' + struct.pack('<III', w, h, 3))
                conn.sendall(img.tobytes())
    except Exception:       # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:   # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--device', default='127.0.0.1:16384')
    ap.add_argument('--port', type=int, default=19999)
    ap.add_argument('--mumu-index', type=int, default=0,
                    help='MuMu 多开实例下标（0=第一个，1=第二个…）')
    a = ap.parse_args()
    t0 = time.time()
    cap = Capture(a.device, a.mumu_index)
    print('MAA 截图就绪（%.1fs）' % (time.time() - t0), flush=True)
    # 自测速度
    for _ in range(5):
        cap.grab()
    n = 20
    t0 = time.time()
    for _ in range(n):
        cap.grab()
    print('自测：%.4f 秒/张' % ((time.time() - t0) / n), flush=True)
    serve(cap, a.port)


if __name__ == '__main__':
    main()
