# -*- coding: utf-8 -*-
"""maa_extras.py · 单独量「MuMu 官方极速截图」= MAA 的 EmulatorExtras 方式

要点：
  · MAA 的 `EmulatorExtras` 截图方式**就是调用 MuMu 官方的 `external_renderer_ipc.dll`**
    （跟 MuMu 多开器/自带录屏用的是同一套接口）——所以「MAA 的 24ms」=「MuMu 官方极速截图」
  · 对比基准：我们现在的 `adb exec-out screencap -p`（实测 0.24s）
  · ⚠ MAA 默认会把截图**缩放**（刚才量到 1280x720）——必须 `set_screenshot_use_raw_size(True)`
    才是原始 1080x1920，否则跟我们的模板对不上
"""
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


ADB = (os.environ.get('MAPBOT_ADB') or 'adb')
DEV = '127.0.0.1:16384'


def main():
    from maa.toolkit import Toolkit
    from maa.controller import AdbController
    from maa.define import MaaAdbScreencapMethodEnum as S, MaaAdbInputMethodEnum as I

    Toolkit.init_option(os.path.join(HERE, 'maa_log'))

    # ① MAA 自动发现的 MuMu 实例（它自己就知道 extras 该怎么配）
    devs = Toolkit.find_adb_devices()
    mine = None
    for d in devs:
        if str(d.address) == DEV:
            mine = d
            break
    print('=== MAA 自动发现的设备 ===')
    for d in devs:
        print('   %s | %s | screencap=%s | config=%s'
              % (d.name, d.address, d.screencap_methods, d.config))
    cfg = dict(mine.config) if mine and mine.config else None
    adb_used = str(mine.adb_path) if mine else ADB

    # ② 原始尺寸 vs 默认缩放
    for raw in (False, True):
        for label, sm, im in (('EmulatorExtras（MuMu 官方极速）', int(S.EmulatorExtras),
                               int(I.EmulatorExtras)),
                              ('Encode（纯 adb 口径）', int(S.Encode), int(I.AdbShell))):
            try:
                c = AdbController(adb_used, DEV, sm, im, config=cfg)
                if not c.post_connection().wait().succeeded:
                    print('   %-32s raw=%-5s 连接失败' % (label, raw))
                    continue
                if raw:
                    c.set_screenshot_use_raw_size(True)
                for _ in range(3):
                    c.post_screencap().wait()
                n = 12
                t0 = time.time()
                img = None
                for _ in range(n):
                    img = c.post_screencap().wait().get()
                dt = (time.time() - t0) / n
                print('   %-32s raw=%-5s %.3f 秒/张  %s'
                      % (label, raw, dt, None if img is None else img.shape))
                c.post_inactive().wait()
            except Exception as e:      # noqa: BLE001
                print('   %-32s raw=%-5s 失败：%r' % (label, raw, e))


if __name__ == '__main__':
    main()
