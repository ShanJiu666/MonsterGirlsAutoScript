# -*- coding: utf-8 -*-
"""在截图上画 5x7 棋盘网格，用于校准格子几何。
默认几何基于 1080x1920 截图目测，可调 OFFSET/CELL。
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
import cv2
import numpy as np

import repo_paths as RP                                          # noqa: E402

# 2026-10-10 去仓库耦合：原指旧仓库 `tools\mapbot\runs\in_map.png`（= 本仓 runs，走 junction）
_DEFAULT_IMG = os.path.join(RP.HERE, 'runs', 'in_map.png')
IMG = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_IMG
OUT = IMG.replace('.png', '_grid.png')

# 可调参数（实际 1080x1920 坐标）
X0 = 21.0      # 第0列左边缘
Y0 = 941.0     # 第0行上边缘
CELL_X = 148.6  # 格宽
CELL_Y = 154.3  # 格高
COLS, ROWS = 7, 5

img = cv2.imdecode(np.fromfile(IMG, dtype=np.uint8), cv2.IMREAD_COLOR)
for r in range(ROWS):
    for c in range(COLS):
        x = int(X0 + c * CELL_X)
        y = int(Y0 + r * CELL_Y)
        cv2.rectangle(img, (x, y), (x + int(CELL_X), y + int(CELL_Y)), (0, 0, 255), 3)
        cx, cy = int(x + CELL_X / 2), int(y + CELL_Y / 2)
        cv2.putText(img, f'{r},{c}', (cx - 30, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 6, (0, 255, 0), -1)
ok, buf = cv2.imencode('.png', img)
buf.tofile(OUT)
print('saved', OUT)
