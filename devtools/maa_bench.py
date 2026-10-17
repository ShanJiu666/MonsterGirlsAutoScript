# -*- coding: utf-8 -*-
"""maa_bench.py · MaaFramework 截图/识别耗时实测（跟我们的 adb+RapidOCR+OpenCV 对比用）

在 **maa_venv** 里跑：
    <MAA venv python> maa_bench.py

测四件事：
  ① 各种截图方式的速度（EncodeToFileAndPull = 我们现在的 adb screencap 口径；
     **EmulatorExtras = MuMu 官方极速截图**，需要 external_renderer_ipc.dll）
  ② MAA 模板匹配识别的耗时（跟我们 OpenCV 多尺度掩码匹配比）
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
MUMU_DLL = ''


def main():
    from maa.toolkit import Toolkit
    from maa.controller import AdbController
    from maa.define import (MaaAdbScreencapMethodEnum as S,
                            MaaAdbInputMethodEnum as I)

    Toolkit.init_option(os.path.join(HERE, 'maa_log'))
    cases = [
        ('EncodeToFileAndPull（= 我们现在的 adb 截图口径）', int(S.EncodeToFileAndPull), None),
        ('RawWithGzip', int(S.RawWithGzip), None),
        ('EmulatorExtras（MuMu 官方极速）', int(S.EmulatorExtras),
         {'library_path': MUMU_DLL} if os.path.exists(MUMU_DLL) else None),
    ]
    print('=== ① 截图速度（每种抓 8 次取平均）===')
    for name, method, cfg in cases:
        try:
            c = AdbController(ADB, DEV, method, int(I.Default), config=cfg)
            ok = c.post_connection().wait().succeeded
            if not ok:
                print('  %-42s 连接失败，跳过' % name)
                continue
            for _ in range(2):          # 预热
                c.post_screencap().wait()
            t0 = time.time()
            n = 8
            img = None
            for _ in range(n):
                img = c.post_screencap().wait().get()
            dt = (time.time() - t0) / n
            shape = None if img is None else getattr(img, 'shape', None)
            print('  %-42s %.3f 秒/张  画面 %s' % (name, dt, shape))
            c.post_inactive().wait()
        except Exception as e:          # noqa: BLE001
            print('  %-42s 失败：%r' % (name, e))

    # ② 模板匹配识别耗时（用 MAA 的 Resource + Tasker 跑一个 TemplateMatch 任务）
    print()
    print('=== ② MAA 模板匹配识别 ===')
    try:
        from maa.resource import Resource
        from maa.tasker import Tasker
        res_dir = os.path.join(HERE, 'maa_res')
        os.makedirs(os.path.join(res_dir, 'image'), exist_ok=True)
        src = ''
        import shutil
        shutil.copy(src, os.path.join(res_dir, 'image', 'tpl.png'))
        import json
        pipe = {'benchTpl': {'recognition': 'TemplateMatch', 'template': 'image/tpl.png',
                             'threshold': 0.7}}
        open(os.path.join(res_dir, 'pipeline', 'bench.json'), 'w',
             encoding='utf-8') if False else None
        os.makedirs(os.path.join(res_dir, 'pipeline'), exist_ok=True)
        with open(os.path.join(res_dir, 'pipeline', 'bench.json'), 'w', encoding='utf-8') as f:
            json.dump(pipe, f, ensure_ascii=False)

        res = Resource()
        res.post_bundle(res_dir).wait()
        ctl = AdbController(ADB, DEV, int(S.EmulatorExtras), int(I.Default),
                            config={'library_path': MUMU_DLL})
        ctl.post_connection().wait()
        tasker = Tasker()
        tasker.bind(res, ctl)
        if not tasker.inited:
            ctl2 = AdbController(ADB, DEV, int(S.EncodeToFileAndPull), int(I.Default))
            ctl2.post_connection().wait()
            tasker.bind(res, ctl2)
        for _ in range(2):
            tasker.post_task('benchTpl').wait()
        t0 = time.time()
        n = 8
        for _ in range(n):
            r = tasker.post_task('benchTpl').wait()
        dt = (time.time() - t0) / n
        print('  %-42s %.3f 秒/次（含截图）' % ('TemplateMatch 整条任务', dt))
    except Exception as e:              # noqa: BLE001
        import traceback
        print('  模板匹配测试失败：%r' % e)
        print(traceback.format_exc()[-600:])


if __name__ == '__main__':
    main()
