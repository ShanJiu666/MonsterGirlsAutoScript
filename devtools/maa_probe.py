# -*- coding: utf-8 -*-
"""maa_probe.py · 排查 MAA 连不上/截不了图的原因（最小探针）"""
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
MUMU_DLL = ''


def main():
    from maa.toolkit import Toolkit
    from maa.controller import AdbController
    from maa.define import MaaAdbScreencapMethodEnum as S, MaaAdbInputMethodEnum as I

    Toolkit.init_option(os.path.join(HERE, 'maa_log'))
    print('--- MAA 自己找设备 ---')
    try:
        devs = Toolkit.find_adb_devices()
        for d in devs:
            print('   ', d)
    except Exception as e:      # noqa: BLE001
        print('    find_adb_devices 失败：%r' % e)

    trials = [
        ('All / All', int(S.All), int(I.All), None),
        ('Encode(2) / AdbShell', int(S.Encode), int(I.AdbShell), None),
        ('EncodeToFileAndPull / AdbShell', int(S.EncodeToFileAndPull), int(I.AdbShell), None),
        ('EmulatorExtras / EmulatorExtras', int(S.EmulatorExtras), int(I.EmulatorExtras),
         {'library_path': MUMU_DLL}),
    ]
    print('--- 逐个试 controller ---')
    for name, sm, im, cfg in trials:
        try:
            c = AdbController(ADB, '127.0.0.1:16384', sm, im, config=cfg)
            ok = c.post_connection().wait().succeeded
            print('   %-34s connect=%s' % (name, ok))
            if not ok:
                continue
            print('        info: %s' % str(c.info)[:160])
            t0 = time.time()
            img = c.post_screencap().wait().get()
            print('        截图 %.3f 秒，形状 %s' % (time.time() - t0,
                                              None if img is None else img.shape))
            c.post_inactive().wait()
        except Exception as e:      # noqa: BLE001
            print('   %-34s 异常：%r' % (name, e))


if __name__ == '__main__':
    main()
