# -*- coding: utf-8 -*-
"""make_battle_tpl.py · 裁「战斗结算标题」模板（S 级提速用）

产出：`templates/fixed/battle_win_title.png`
  = 结算面板顶部标题「战斗胜利」那一块，**720×1280 设备坐标 (229,91)-(489,157)**

为什么裁它
----------
`start_fight()` 原来靠一次 ~0.52s 的 OCR 反复问「开打了没」（真机耗时分账：
`tap` = 276.4s / 530 次）。而「开打完了」在本游戏里 = **结算面板出现了**，
那是**固定 UI** ⇒ 一次模板匹配（~7~20ms）就能答，不必付 OCR。
（另一条判据「底部关闭按钮」直接复用已有 `close_tpl_{0,1,2}`，不在本脚本里。）

⚠⚠ 搜索带必须限定 x∈[200,520]（见 `explore_loop._BATTLE_TITLE_BOX`）
  地图界面左上角有一行 **「首领战斗胜利」**（实测 bbox **(21,100)-(138,123)**），
  与结算标题 **「战斗胜利」**（实测 bbox **(229,91)-(489,157)**）
  **y 重叠、x 完全不重叠**（间隔 91px）⇒ 只有限定 x 带才排除得掉它。
  这正是 `battle_started()` 用「整条等值」防的那个坑（`首领战斗胜利` 是 6 字长句 ⇒
  不等于 `战斗胜利`）；模板这边用**空间**防 —— 同一个坑，两种防法 ✓

标定（离线，零体力，2026-10-04）：
  正样本 = 180 张真机结算帧（`close_tpl` 判定）⇒ 最低 **1.000**
  负样本 = 90 张地图/背包帧 ⇒ 最高 **0.228**
  ⇒ 间隔 **0.772**，阈值取 **0.80**（宁可漏判回退 OCR，绝不误判 ✓）

用法：
    python make_battle_tpl.py              # 自动扫 runs/ 里的结算帧
    python make_battle_tpl.py <帧.png>      # 指定源帧
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
import glob

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import fixed as F                           # noqa: E402


# 结算标题的裁剪框（**设备系 720×1280**，来源：真机帧 OCR bbox 实测）
TITLE_BOX = (229, 91, 489, 157)
# 搜索带：必须装得下模板(260×66)，且 x0 ≥ 200 ⇒ 把地图横幅「首领战斗胜利」排除在外
SEARCH_BOX = (200, 70, 520, 190)
# 匹配阈值（比模块默认 MATCH_MIN=0.62 严；标定间隔 0.772 ⇒ 余量很大）
THR = 0.80
NAME = 'battle_win_title'


def _load(f):
    """读 720×1280 帧；坏帧/别的分辨率一律 None（截图工具会留半张图）"""
    try:
        if os.path.getsize(f) < 1024:
            return None
        im = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:                       # noqa: BLE001
        return None
    if im is None or im.shape[:2] != (F.PC_H, F.PC_W):
        return None
    return im


def _close_score(im):
    """这张帧像不像**结算面板**（复用 wait_end 已验证的 close_tpl 三档）"""
    mx = 0.0
    for nm in ('close_tpl_0', 'close_tpl_1', 'close_tpl_2'):
        v = F.find(im, nm, box=(0, 780, 720, 1080))
        if v:
            mx = max(mx, v[2])
    return mx


def scan(limit_pos=200, limit_neg=400):
    """扫 runs/ 分正负样本（正 = close_tpl ≥ 0.80 的结算帧）"""
    pos, neg = [], []
    for f in sorted(glob.glob(os.path.join(HERE, 'runs', '**', '*.png'), recursive=True)):
        im = _load(f)
        if im is None:
            continue
        if _close_score(im) >= THR:
            if len(pos) < limit_pos:
                pos.append((f, im))
        elif len(neg) < limit_neg:
            neg.append((f, im))
        if len(pos) >= limit_pos and len(neg) >= limit_neg:
            break
    return pos, neg


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    pos, neg = scan()
    if not pos and not src:
        print('找不到结算帧（runs/ 里没有 close_tpl 命中的 720×1280 帧）')
        print('用法：python make_battle_tpl.py <结算帧.png>')
        return 1
    x0, y0, x1, y1 = TITLE_BOX
    if src:                                  # 指定源帧
        im = _load(src)
        if im is None:
            print('源帧读不出或是非 720×1280：%s' % src)
            return 1
        crop = im[y0:y1, x0:x1]
        used = src
    else:
        crop = pos[0][1][y0:y1, x0:x1]
        used = pos[0][0]
    if crop.size == 0:
        print('裁剪为空 —— TITLE_BOX %s 越界？' % (TITLE_BOX,))
        return 1

    os.makedirs(F.TPL_DIR, exist_ok=True)
    out = os.path.join(F.TPL_DIR, NAME + '.png')
    cv2.imencode('.png', crop)[1].tofile(out)
    print('源帧: %s' % os.path.basename(used))
    print('裁剪: %s  %dx%d → %s' % (TITLE_BOX, crop.shape[1], crop.shape[0],
                                    os.path.basename(out)))
    print('搜索带: %s（x0=200 ⇒ 排除地图横幅「首领战斗胜利」x≤138 ✓）'
          % (SEARCH_BOX,))
    print()
    print('--- 标定（正样本必须命中 / 负样本必须不命中）---')
    t = F._load(NAME)
    if t is None:
        print('   ✗ 模板没写进去？')
        return 1
    bx0, by0, bx1, by1 = SEARCH_BOX
    if t.shape[0] > by1 - by0 or t.shape[1] > bx1 - bx0:
        print('   ✗ 模板 %dx%d 装不进搜索带 %s（会静默永不命中！）'
              % (t.shape[1], t.shape[0], SEARCH_BOX))
        return 1
    ps = []
    for _f, im in pos:
        r = cv2.matchTemplate(im[by0:by1, bx0:bx1].astype(np.float32),
                              t.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        ps.append(float(r.max()))
    ns = []
    for _f, im in neg:
        r = cv2.matchTemplate(im[by0:by1, bx0:bx1].astype(np.float32),
                              t.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        ns.append(float(r.max()))
    print('   正样本 %3d 张：最低 %.3f  %s'
          % (len(ps), min(ps) if ps else 0.0,
             '全部命中 ✓' if ps and min(ps) >= THR else '有未命中 ✗'))
    print('   负样本 %3d 张：最高 %.3f  %s'
          % (len(ns), max(ns) if ns else 0.0,
             '全部不命中 ✓' if ns and max(ns) < THR else '有误命中 ✗'))
    ok = bool(ps) and min(ps) >= THR and bool(ns) and max(ns) < THR
    print()
    print('下一步：python verify_fastpath.py（【1d】组会复核这两条）')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
