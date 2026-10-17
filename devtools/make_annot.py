# -*- coding: utf-8 -*-
"""make_annot.py · 真机首帧 + 逐格识别标注图（供用户手工核对）

产出两张图 + 一份数据 txt，丢进 `~/Desktop/地图核对\\`：
  · `<名>_标注.png`  真机原图，每格黄框 + 三行字（格号 / sid+名字 / 置信度+格数）
                        绿框 = 多格块（同一块跨多格）
  · `<名>_对照.png`  左原图 / 右识别图，**并排**方便直接比对
  · `<名>_数据.txt`  逐块明细（含成员格）

用法：
    python make_annot.py <图片路径> [输出目录] [图名]
"""
from __future__ import annotations

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
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import marks                                        # noqa: E402
import spots as spots_mod                           # noqa: E402
import targets_cfg as tcfg                          # noqa: E402


DESK = os.path.join(os.path.expanduser('~'), 'Desktop')

# ⚠ cv2.putText **不支持中文**（会画成一串 ?）⇒ 文字一律走 PIL + 微软雅黑 ✓
_FONT = r'C:\Windows\Fonts\msyh.ttc'

# ⭐⭐⭐ 基准网格 = **720×1280 设备系**（layout.REF 折算后，§1b）
#   ⚠⚠ **不要拿它直接去读别的分辨率的图** —— 那是 2026-10-02 踩的坑：
#     `runs/r_224535_0.png` 是 **1080×1920**（9-28 时代的老基准），
#     拿 720p 网格去读 ⇒ NCC 分数被压到 0.08~0.26 ⇒ **满盘瞎猜**
#     （连草地都认不出来），我据此以为"识别代码坏了"，其实代码一直是好的。
#   ⇒ 下面 `grid_for()` 按**图片实际尺寸**等比折算，任意分辨率都对。
BASE_W, BASE_H = 720, 1280
BASE_GRID = {'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0,
             'pitch': 96.0, 'cols': 7, 'rows': 5}


def grid_for(w, h):
    """按图片实际尺寸把 720×1280 基准网格等比折算（720p 原样、1080p ×1.5）"""
    kx, ky = w / float(BASE_W), h / float(BASE_H)
    return {'x0': BASE_GRID['x0'] * kx, 'y0': BASE_GRID['y0'] * ky,
            'cx': BASE_GRID['cx'] * kx, 'cy': BASE_GRID['cy'] * ky,
            'pitch': BASE_GRID['cx'] * kx,
            'cols': BASE_GRID['cols'], 'rows': BASE_GRID['rows']}


def _f(sz):
    try:
        return ImageFont.truetype(_FONT, sz)
    except Exception:                                   # noqa: BLE001
        return ImageFont.load_default()


def cell_box(r, c, g, pad=2):
    """格 (r,c) 1 基 -> 外接矩形 (x0,y0,x1,y1)"""
    x0 = int(g['x0'] + (c - 1) * g['cx']) - pad
    y0 = int(g['y0'] + (r - 1) * g['cy']) - pad
    return x0, y0, int(x0 + g['cx']) + pad, int(y0 + g['cy']) + pad


def draw(img, st, g):
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(pil, 'RGBA')
    # ── 先按 anchor 归组，算出每块占几格（绿框画在整块外沿）──
    groups = {}
    for (r, c), v in st.items():
        a = tuple(v.get('anchor') or (r, c))
        groups.setdefault(a, []).append((r, c))
    multi = {a for a, ms in groups.items() if len(ms) > 1}

    f = _f(11)
    for (r, c) in sorted(st):
        v = st[(r, c)]
        x0, y0, x1, y1 = cell_box(r, c, g)
        a = tuple(v.get('anchor') or (r, c))
        # 黄框：单格
        dr.rectangle([x0, y0, x1, y1], outline=(255, 210, 0), width=2)
        # 绿框：多格块的外沿
        if a in multi:
            ms = groups[a]
            ax0 = min(cell_box(x, y, g)[0] for x, y in ms)
            ay0 = min(cell_box(x, y, g)[1] for x, y in ms)
            ax1 = max(cell_box(x, y, g)[2] for x, y in ms)
            ay1 = max(cell_box(x, y, g)[3] for x, y in ms)
            dr.rectangle([ax0, ay0, ax1, ay1], outline=(0, 220, 0), width=3)

        nm = str(v.get('name') or '?')
        sid = str(v.get('sid') or '')
        sc = float(v.get('score') or 0)
        ncell = len(groups.get(a, [(r, c)]))
        blocked = tcfg.is_blocked_cell(v)
        low = sc < tcfg.BLOCKED_SCORE_MIN
        # ⭐ 加一行 ratio（揭示度）—— 雾格 ratio≈0.65、已揭示≈0.95~1.0
        #   手工核对时**先看 ratio 再看名字**：雾格本来就该低分，不是识别错 ✓
        ratio = float(v.get('ratio') or 0)
        fog = ratio < 0.80
        lines = ['%d,%d' % (r, c),
                 '%s %s' % (sid.split('_')[-1] if sid else '?', nm),
                 '%.2f %d格 r%.2f' % (sc, ncell, ratio)]
        # 雾格=青色，已揭示=白/红（红 = 低分或拉黑）
        if fog:
            col = (120, 230, 255)
        else:
            col = (255, 60, 60) if (low or blocked) else (255, 255, 255)
        for i, s in enumerate(lines):
            ty = y0 + 12 + i * 12
            dr.text((x0 + 3, ty), s, font=f, fill=(0, 0, 0, 220))
            dr.text((x0 + 3, ty - 1), s, font=f, fill=col + (255,))
    return pil


def legend(pil, st, src, code, g):
    """底部图例（覆盖式，不拉伸原图）"""
    dr = ImageDraw.Draw(pil, 'RGBA')
    W, H = pil.size
    bar = 76
    dr.rectangle([0, H - bar, W, H], fill=(20, 16, 12, 235))
    fl = _f(12)
    nblk = len({tuple(v.get('anchor') or k) for k, v in st.items()})
    rows = [
        '%s   地块表=%s   块数=%d   覆盖 %d/%d 格'
        % (os.path.basename(src), code, nblk, len(st), g['rows'] * g['cols']),
        '黄框=块  绿框=多格块  标签=格号 / ID 名称 / 置信度 占格 r揭示度',
        '青字=雾格(r<0.8，本来就认不准)   红字=已揭示但置信度<%.2f 或被拉黑'
        % tcfg.BLOCKED_SCORE_MIN,
        '白字=识别正常',
    ]
    for i, s in enumerate(rows):
        dr.text((6, H - bar + 6 + i * 17), s, font=fl, fill=(235, 235, 235, 255))
    return pil


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else DESK
    base = sys.argv[3] if len(sys.argv) > 3 else \
        os.path.splitext(os.path.basename(src))[0]
    os.makedirs(outdir, exist_ok=True)

    img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print('读不到图：%s' % src)
        return 1
    code = 'S00003'
    # ⭐ 按**图片实际尺寸**折算网格 —— 720p 图原样、1080p 图 ×1.5。
    #   拿错基准 = 满盘 0.1 分乱猜（2026-10-02 踩过，见 grid_for 的注释）✓
    g = grid_for(img.shape[1], img.shape[0])
    print('图 %dx%d → 格距 %.0f（720p 基准 %.0f，×%.2f）'
          % (img.shape[1], img.shape[0], g['cx'], BASE_GRID['cx'],
             img.shape[1] / float(BASE_W)))
    st = spots_mod.Board(code, grid=g).state(img)
    print('识别：%d 格，%d 块' % (
        len(st), len({tuple(v.get('anchor') or k) for k, v in st.items()})))

    ann = legend(draw(img, st, g), st, src, code, g)
    p_ann = os.path.join(outdir, '%s_标注.png' % base)
    ann.save(p_ann)

    # 并排对照：左原图 右标注
    orig = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    side = Image.new('RGB', (orig.width * 2, max(orig.height, ann.height)),
                     (0, 0, 0))
    side.paste(orig, (0, 0))
    side.paste(ann, (orig.width, 0))
    p_cmp = os.path.join(outdir, '%s_对照.png' % base)
    side.save(p_cmp)

    # ── 数据 txt ──
    groups = {}
    for (r, c), v in st.items():
        groups.setdefault(tuple(v.get('anchor') or (r, c)), []).append((r, c))
    L = ['■ %s · %s · 地块表 %s · 【%s】' % (
            base, '夏日海滩', code, time.strftime('%Y-%m-%d %H:%M')),
         '  源图：%s' % os.path.basename(src),
         '  识别方式：与实盘同款 spots.Board.state()（alpha 真实占格 + 掩膜 NCC + 剔高饱和图标像素）',
         '  共 %d 块；覆盖 %d/%d 格' % (len(groups), len(st),
                                        g['rows'] * g['cols']),
         '',
         '── 逐块明细（锚点：ID 名称 置信度 占格 揭示 标记 成员格）──']
    for a in sorted(groups):
        r, c = a
        v = st[a]
        ms = sorted(groups[a])
        blk = ('  成员%s' % ms) if len(ms) > 1 else ''
        mk = ','.join(v.get('marks') or []) or '—'
        bk = '  ★拉黑' if tcfg.is_blocked_cell(v) else ''
        lo = '  ★低分' if float(v.get('score') or 0) < tcfg.BLOCKED_SCORE_MIN else ''
        L.append('  %d,%-2d %s %-8s %.3f %d格 %s 标记[%s]%s%s%s'
                 % (r, c, v.get('sid') or '?', str(v.get('name') or '?'),
                    float(v.get('score') or 0), len(ms),
                    '已揭示' if v.get('revealed') else '未揭示', mk, lo, bk, blk))
    miss = [('%d,%d' % (r, c)) for r in range(1, g['rows'] + 1)
            for c in range(1, g['cols'] + 1) if (r, c) not in st]
    L += ['', '── 未识别到的格（无任何块覆盖）──',
          '  ' + ('、'.join(miss) if miss else '（无 ✓ %d 格全覆盖）'
                  % (g['rows'] * g['cols'])),
          '', '── 说明 ──',
          '  「置信度」= 该格 top1 候选的 NCC 分（多格块会经归属修正 ⇒ 成员格分数是块分）。',
          '  「★低分」= 置信度 < %.2f ⇒ 认不准，**不当拉黑**（本次修复，见 verify_blocked_score.py）'
          % tcfg.BLOCKED_SCORE_MIN,
          '  「★拉黑」= 名字在黑名单且置信度够高 ⇒ 真的不点。']
    p_txt = os.path.join(outdir, '%s_数据.txt' % base)
    io.open(p_txt, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')

    print('已生成：')
    for p in (p_ann, p_cmp, p_txt):
        print('  %s  (%d bytes)' % (p, os.path.getsize(p)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
