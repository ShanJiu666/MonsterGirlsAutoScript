# -*- coding: utf-8 -*-
"""坐标可视化核对：把脚本要点的每个点画在真机帧上（只读，零设备）。

目的：肉眼确认"脚本要点的位置"真的落在目标按钮/箱子上，
      而不是靠 OCR 文字坐标"看起来差不多"。

用法：python verify_coords_visual.py
"""
import io
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import cv2                                              # noqa: E402
import numpy as np                                      # noqa: E402

import guild_common as GC                               # noqa: E402


FRAMES = ''
OUT = os.path.join(HERE, 'runs', 'guild_coordcheck')
os.makedirs(OUT, exist_ok=True)

# (帧文件, 标题, [(点名, 坐标, 颜色)])
PLANS = [
    ('chk_now.png', '派遣·椅子行', [
        ('椅1', (GC.CHAIR_X[0], GC.CHAIR_Y), (0, 0, 255)),
        ('椅2', (GC.CHAIR_X[1], GC.CHAIR_Y), (0, 0, 255)),
        ('椅3', (GC.CHAIR_X[2], GC.CHAIR_Y), (0, 0, 255)),
        ('椅4', (GC.CHAIR_X[3], GC.CHAIR_Y), (0, 0, 255)),
        ('公会tab', GC.NAV_GUILD, (255, 0, 255)),
        ('开始冒险', GC.NAV_START, (255, 0, 255)),
    ]),
    ('p3_open_after.png', '派遣·未接面板', [
        ('主按钮(一键派遣)', GC.TASK_ACTION_BTN, (0, 0, 255)),
        ('面板X', GC.TASK_PANEL_X, (255, 0, 0)),
    ]),
    ('p3_fill_after.png', '派遣·已填队面板', [
        ('主按钮(开始任务)', GC.TASK_ACTION_BTN, (0, 0, 255)),
    ]),
    ('f1_after.png', '派遣·进行中面板', [
        ('主按钮(召回)', GC.TASK_ACTION_BTN, (0, 0, 255)),
    ]),
    ('chest_after.png', '炼金·结果面板', [
        ('返回', GC.ALCH_RESULT_BACK, (0, 0, 255)),
    ]),
    ('alch_main_after.png', '炼金·主面板(空闲)', [
        ('开始炼金', GC.ALCH_START_BTN, (0, 0, 255)),
        ('全部取消', GC.ALCH_CANCEL_BTN, (0, 165, 255)),
        ('装备页签', GC.ALCH_TAB_EQUIP, (255, 0, 0)),
        ('符文页签', GC.ALCH_TAB_RUNE, (255, 0, 0)),
        ('满星筛选', GC.ALCH_FILTER_FULLSTAR, (0, 255, 0)),
        ('面板X', GC.ALCH_PANEL_X, (255, 0, 255)),
    ]),
    ('alch5.png', '炼金·顶楼入口', [
        ('炼金宝箱✅', GC.ALCHEMY_CHEST, (0, 255, 0)),
        ('大陶罐❌无反应', GC.ALCHEMY_DECO_POT, (0, 0, 255)),
        ('紫发角色❌宝箱怪', GC.ALCHEMY_WRONG_CHAR, (0, 0, 255)),
    ]),
    ('start_alch_after.png', '炼金·进行中', [
        ('沙漏(加速入口)', GC.ALCH_HOURGLASS, (0, 255, 255)),
    ]),
    ('hourglass_after.png', '炼金·加速弹窗', [
        ('宝石加速❌不点', GC.ALCH_ACCEL_GEM, (0, 0, 255)),
        ('看广告❌不点', GC.ALCH_ACCEL_AD, (0, 0, 255)),
        ('关闭X✅', GC.ALCH_ACCEL_X, (0, 255, 0)),
    ]),
]


def draw(img, pts, title):
    for name, (x, y), col in pts:
        cv2.drawMarker(img, (int(x), int(y)), col, cv2.MARKER_CROSS, 22, 2)
        cv2.circle(img, (int(x), int(y)), 12, col, 2)
        # 文字画在右上，避免挡到按钮本身
        cv2.putText(img, '%s(%d,%d)' % (name, x, y), (max(2, int(x) - 90),
                    max(14, int(y) - 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
    cv2.rectangle(img, (0, 0), (719, 30), (0, 0, 0), -1)
    cv2.putText(img, title, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 255, 255), 2)
    return img


def main():
    print('=== 坐标可视化核对（只读，产物落 runs/guild_coordcheck/）===')
    n = 0
    for fn, title, pts in PLANS:
        p = os.path.join(FRAMES, fn)
        if not os.path.exists(p):
            print('   · 缺帧 %s ⇒ 跳过' % fn)
            continue
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            continue
        draw(im, pts, title)
        op = os.path.join(OUT, '%s_%s' % (title.replace('·', '_'), fn))
        cv2.imencode('.png', im)[1].tofile(op)
        print('   ✓ %-22s ⇒ %s' % (title, op))
        n += 1
    print()
    print('共 %d 张 ⇒ %s' % (n, OUT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
