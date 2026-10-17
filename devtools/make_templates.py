# -*- coding: utf-8 -*-
"""make_templates.py · 从 720×1280 真帧裁出「固定 UI」模板（喂给 fixed.py 的模板快查）

只裁**永远不变**的东西：底部导航条的 5 个 tab 图标。
⚠ 不要裁「会变」的东西：体力数字、倒计时、图名、道具名、价格 —— 那些必须 OCR。

用法：
    python make_templates.py <720p真帧.png> [更多帧...]
没有参数时自动去 `_tmpman/live7555/` 找一张 720×1280 的真帧。
"""
import os
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

sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import fixed as F                           # noqa: E402


OUT = F.TPL_DIR

# 模板名 → (中心 x, 中心 y, 宽, 高)  —— 中心取 fixed.A()，尺寸按 720p 实测量
# ⚠ 尺寸是**图标/文字**那一小块，不要框到相邻 tab（否则模板互相包含、互相误命中）
CUTS = {
    'nav_dex':    (None, 46, 30),    # 图鉴
    'nav_guild':  (None, 46, 30),    # 公会
    'nav_role':   (None, 46, 30),    # 角色
    'nav_arena':  (None, 46, 30),    # 斗技场
    'nav_start':  (None, 46, 30),    # 开始冒险（中心 tab）
}


def find_frame(argv):
    if argv:
        return argv[0]
    for d in ('', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')):
        if not os.path.isdir(d):
            continue
        for p in sorted(os.listdir(d)):
            if p.lower().endswith('.png'):
                fp = os.path.join(d, p)
                img = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None and img.shape[:2] == (F.PC_H, F.PC_W):
                    return fp
    return None


def main():
    p = find_frame(sys.argv[1:])
    if not p:
        print('找不到 720×1280 真帧')
        print('用法：python make_templates.py <真帧.png>')
        return 1
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    print('源帧: %s  %dx%d' % (p, w, h))
    if (h, w) != (F.PC_H, F.PC_W):
        print('⚠ 这不是 %dx%d 的帧！模板必须在目标分辨率下裁，否则匹配会失效' % (F.PC_W, F.PC_H))
        return 1
    os.makedirs(OUT, exist_ok=True)
    for name, (dx, tw, th) in CUTS.items():
        cx, cy = F.A(name)
        x0, y0 = max(0, cx - tw // 2), max(0, cy - th // 2)
        x1, y1 = min(w, x0 + tw), min(h, y0 + th)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            print('  ✗ %-12s 裁剪为空（锚点 %s 越界？）' % (name, (cx, cy)))
            continue
        out = os.path.join(OUT, name + '.png')
        cv2.imencode('.png', crop)[1].tofile(out)
        print('  ✓ %-12s 中心(%3d,%4d)  %dx%d → %s' % (name, cx, cy, crop.shape[1], crop.shape[0],
                                                        os.path.basename(out)))
    print()
    print('接下来跑 `python fixed.py` 看自检，然后就能在热路径用 fixed.has(img, "nav_dex")')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
