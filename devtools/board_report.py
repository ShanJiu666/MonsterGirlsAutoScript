# -*- coding: utf-8 -*-
"""board_report.py · 把「实盘同款地块识别结果」导出成**人工可核对**的两份产物

背景（2026-09-27）：用户每次推完图要手工核对「屏幕上的地块 vs 脚本认出来的地块」。
光给数字不好核；必须**叠在图上**，一眼看出「哪格认成什么、哪格没认出来」。

识别口径与实盘**完全一致**：`spots.Board(code).state(img)`
（alpha 真实占格 + 掩膜 NCC + 剔除高饱和图标像素）——不是另写一套近似实现 ✓
⇒ 这里看到什么，脚本推图时就认成什么 ✓

产出两份（默认写到 `--outdir`）：
  1. `<标题>_修正版数据.txt`  —— 逐块明细（锚点/ID/名称/置信度/占格/是否已揭示/成员格）+ 未覆盖格
  2. `<标题>_修正版标注.png`  —— 黄框=块锚点、浅绿底=多格块成员格、红叉=无覆盖

用法：
    # 单张
    python board_report.py runs/r_195302_0.png --title 图3 --outdir os.path.join(os.path.expanduser('~'), 'Desktop')
    # 批量（一次对比多张，自动编号）
    python board_report.py runs/r_195302_0.png runs/r_203000_0.png --title 图 --outdir ...
    # 换地图
    python board_report.py <png> --map 枯木丛林 --title 图4
"""
import argparse
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)
import cv2                                    # noqa: E402
import numpy as np                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont   # noqa: E402

import spots as SP                            # noqa: E402


FONT = 'C:/Windows/Fonts/msyh.ttc'
BASE_W, BASE_H = 1080, 1920                   # spots.GRID 的基准分辨率 ✓
ROWS, COLS = 5, 7

# 画色（RGBA —— PIL 叠加用）
C_ANCHOR_EDGE = (255, 215, 0, 255)      # 金黄 = 块锚点框
C_MEMBER_FILL = (60, 200, 120, 60)      # 浅绿 = 多格块成员格
C_ANCHOR_FILL = (0, 0, 0, 165)          # 锚点标签底
C_MISS = (255, 40, 40, 225)             # 红叉 = 无覆盖
C_REVEAL = (0, 255, 255, 235)           # 青 = 已揭示角标


def _font(size):
    for p in (FONT, 'C:/Windows/Fonts/msyhbd.ttc', 'C:/Windows/Fonts/simhei.ttf'):
        try:
            return ImageFont.truetype(p, size)
        except Exception:                                       # noqa: BLE001
            continue
    return ImageFont.load_default()


def analyze(path, code):
    """→ (img_bgr, state, blocks)  ；state = {(r,c): {...}}"""
    im = SP.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit('读不到图：%s' % path)
    if im.ndim == 3 and im.shape[2] == 4:
        im = cv2.cvtColor(im, cv2.COLOR_BGRA2BGR)
    b = SP.Board(code)
    st = b.state(im)
    return im, st


def lumps(state):
    """把 state 汇总成「块」列表（按锚点去重，按行×列排序）"""
    seen, out = {}, []
    for (r, c), v in state.items():
        anc = tuple(v['anchor']) if v['anchor'] else (r, c)
        if anc in seen:
            continue
        seen[anc] = True
        cells = [tuple(x) for x in (v['cells'] or [(r, c)])]
        out.append(dict(anchor=anc, sid=v['sid'], name=v.get('name'),
                        score=v['score'], size=v['size'], cells=cells,
                        revealed=v.get('revealed'),
                        block_score=v.get('block_score')))
    out.sort(key=lambda d: (d['anchor'][0], d['anchor'][1]))
    return out


def write_txt(out_txt, title, mapname, code, blks, state, src, total_cells=ROWS * COLS):
    cover = set()
    for b in blks:
        cover |= set(b['cells'])
    miss = sorted([(r, c) for r in range(1, ROWS + 1) for c in range(1, COLS + 1)
                   if (r, c) not in cover and (r, c) not in state])
    import datetime
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    W = max(6, max(len(str(b['sid'])) for b in blks) if blks else 6)
    L = []
    L.append('■ %s · %s · 地块表 %s · 【修正版 · %s】' % (title, mapname or '?', code, ts))
    L.append('  源图：%s' % src)
    L.append('  识别方式：与实盘同款 spots.Board.state()（alpha 真实占格 + 掩膜 NCC + 剔高饱和图标像素）')
    L.append('  共 %d 块；覆盖 %d/%d 格' % (len(blks), len(cover), total_cells))
    L.append('')
    L.append('── 逐块明细（锚点：ID 名称 置信度 占格 揭示 成员格）──')
    for b in blks:
        r, c = b['anchor']
        n = len(b['cells'])
        cells = '  成员' + str([tuple(x) for x in b['cells']]) if n > 1 else ''
        L.append('  %d,%d  %-*s %-8s %.3f  %d格 %-3s%s'
                 % (r, c, W, b['sid'], (b['name'] or '?'), b['score'], n,
                    '已揭示' if b['revealed'] else '未揭示', cells))
    L.append('')
    L.append('── 未识别到的格（无任何块覆盖）──')
    L.append('  %s' % (' '.join('%d,%d' % k for k in miss) if miss else '（无 ✓ %d 格全覆盖）' % total_cells))
    # 补：有 state 但不在任何 anchor 块里的格（散块/单格，便于人工发现异常）
    L.append('')
    L.append('── 说明 ──')
    L.append('  「置信度」= 该格 top1 候选的 NCC 分（多格块会经归属修正 ⇒ 成员格分数是块分）。')
    L.append('  「未揭示」= 亮度比 < 0.75（游戏把未揭示格乘暗 disableColor，但 NCC 不受影响，仍可识别）。')
    open(out_txt, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return len(blks), cover, miss


def write_png(out_png, bgr, blks, code, src):
    tp = _bgr_to_tmp(bgr)                                        # 走临时文件最稳（中文路径）
    try:
        img = Image.open(tp)
        img.load()
        img = img.convert('RGB')
    finally:
        try:
            os.remove(tp)
        except OSError:
            pass
    W, H = img.size
    sx, sy = W / float(BASE_W), H / float(BASE_H)
    d = ImageDraw.Draw(img, 'RGBA')
    f_big, f_mid, f_sml = _font(int(17 * sx)), _font(int(15 * sx)), _font(int(13 * sx))
    g = SP.GRID
    cw, ch = int(g['cx'] * sx), int(g['cy'] * sy)

    def cell_xy(r, c):
        cx = int((g['x0'] + (c - 0.5) * g['cx']) * sx)
        cy = int((g['y0'] + (r - 0.5) * g['cy']) * sy)
        return cx, cy, cx - cw // 2, cy - ch // 2

    cover = set()
    for b in blks:
        cover |= set(b['cells'])

    # ① 多格块成员格 ⇒ 浅绿底（一眼看出"这几格是一整块"）
    for b in blks:
        if len(b['cells']) <= 1:
            continue
        for (r, c) in b['cells']:
            _cx, _cy, x0, y0 = cell_xy(r, c)
            d.rectangle([x0 + 2, y0 + 2, x0 + cw - 2, y0 + ch - 2], fill=C_MEMBER_FILL)

    # ② 无覆盖格 ⇒ 红叉
    for r in range(1, ROWS + 1):
        for c in range(1, COLS + 1):
            if (r, c) in cover:
                continue
            cx, cy, _x0, _y0 = cell_xy(r, c)
            m = int(20 * sx)
            d.line([cx - m, cy - m, cx + m, cy + m], fill=C_MISS, width=max(2, int(4 * sx)))
            d.line([cx - m, cy + m, cx + m, cy - m], fill=C_MISS, width=max(2, int(4 * sx)))

    # ③ 块锚点 ⇒ 黄框 + 三行标签
    for b in blks:
        r, c = b['anchor']
        cx, cy, x0, y0 = cell_xy(r, c)
        d.rectangle([x0 + 2, y0 + 2, x0 + cw - 2, y0 + ch - 2], fill=C_ANCHOR_FILL,
                    outline=C_ANCHOR_EDGE, width=max(2, int(3 * sx)))
        tx, ty = x0 + int(6 * sx), y0 + int(5 * sy)
        d.text((tx, ty), '%d,%d' % (r, c), font=f_big, fill=(255, 255, 0, 255))
        d.text((tx, ty + int(22 * sy)), '%s %s' % (b['sid'], b['name'] or '?'),
               font=f_mid, fill=(255, 255, 255, 255))
        d.text((tx, ty + int(43 * sy)), '%.3f  %d格' % (b['score'], len(b['cells'])),
               font=f_sml, fill=(170, 255, 190, 255))
        if b['revealed']:
            s2 = int(15 * sx)
            d.polygon([(x0 + cw - s2, y0 + ch), (x0 + cw, y0 + ch), (x0 + cw, y0 + ch - s2)],
                      fill=C_REVEAL)

    # ④ 底部图例
    bar = int(140 * sy)
    d.rectangle([0, H - bar, W, H], fill=(0, 0, 0, 205))
    ncell = len(cover)
    lines = [
        '%s   地块表=%s   块数=%d   覆盖 %d/%d 格' % (src, code, len(blks), ncell, ROWS * COLS),
        '黄框 = 块的**锚点**（左上角那格；标签 = 坐标 / ID 名称 / 置信度 占格）',
        '浅绿底 = 多格地块的**全部成员格**（属于同一块，不是独立目标）',
        '红叉 = 没有任何块覆盖的格     青角标 = 该格已揭示（亮度比 ≥ 0.75）',
        '口径与实盘一致：spots.Board.state()（alpha 真实占格 + 掩膜 NCC + 剔高饱和图标像素）',
    ]
    ty = H - bar + int(6 * sy)
    for i, ln in enumerate(lines):
        d.text((int(10 * sx), ty + i * int(22 * sy)), ln,
               font=f_mid if i == 0 else f_sml, fill=(255, 255, 255, 255))
    img.save(out_png)
    return img.size


def _bgr_to_tmp(bgr):
    """BGR ndarray → 临时 png 路径（中文路径下 PIL 最稳）"""
    import tempfile
    fd, p = tempfile.mkstemp(suffix='.png', prefix='boardrep_')
    os.close(fd)
    ok, buf = cv2.imencode('.png', bgr)
    if not ok:
        raise SystemExit('编码失败')
    buf.tofile(p)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('images', nargs='+', help='截图（进图首帧 r_HHMMSS_0.png 最佳）')
    ap.add_argument('--map', default='夏日海滩', help='地图名（默认 夏日海滩）')
    ap.add_argument('--code', default=None, help='直接给地块表 S 码（覆盖 --map）')
    ap.add_argument('--title', default='图', help='产物标题前缀（多张会自动加序号）')
    ap.add_argument('--outdir', default=os.path.join(HERE, 'runs'),
                    help='输出目录（默认 tools/mapbot/runs）')
    # ⭐ 2026-09-27 用户口径：「后面不用生成标注版本了，你直接存好这些数据准备搞生成算法吧」
    #   ⇒ **默认只出数据 txt**；要标注图得显式加 --png ✓
    ap.add_argument('--png', action='store_true',
                    help='另外生成人工核对用的 `_修正版标注.png`（默认**不生成**）')
    a = ap.parse_args()

    code = a.code or SP.code_of(a.map)
    if not code:
        raise SystemExit('认不出地图 %r 对应的 S 码，请用 --code 指定' % a.map)
    os.makedirs(a.outdir, exist_ok=True)
    multi = len(a.images) > 1
    print('地块表 = %s（%s）  共 %d 张' % (code, a.map, len(a.images)))

    for i, path in enumerate(a.images, 1):
        title = ('%s%d' % (a.title, i)) if multi else a.title
        bgr, st = analyze(path, code)
        blks = lumps(st)
        base = os.path.join(a.outdir, '%s_修正版' % title)
        nb, cover, miss = write_txt(base + '数据.txt', title, a.map, code, blks, st,
                                    os.path.basename(path))
        size = None
        if a.png:
            size = write_png(base + '标注.png', bgr, blks, code, os.path.basename(path))
        print()
        print('【%s】%s  →  %d 块 / 覆盖 %d/%d 格' % (title, os.path.basename(path),
                                                   nb, len(cover), ROWS * COLS))
        for b in blks:
            r, c = b['anchor']
            print('   %d,%d  %-12s %-8s %.3f  %d格 %s%s'
                  % (r, c, b['sid'], b['name'] or '?', b['score'], len(b['cells']),
                     '已揭示' if b['revealed'] else '未揭示',
                     ('  成员%s' % [tuple(x) for x in b['cells']]) if len(b['cells']) > 1 else ''))
        print('   未覆盖格：%s' % (' '.join('%d,%d' % k for k in miss) if miss else '（无 ✓）'))
        print('   产物：%s_修正版数据.txt%s'
              % (title, (' / %s_修正版标注.png' % title) if size else
                 '（默认不出标注图；要图加 --png）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
