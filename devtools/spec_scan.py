# -*- coding: utf-8 -*-
"""spec_scan.py · 特殊地块**真机采图 + 坐标记录**

用途：在真机帧里找出**所有特殊地块**（`SpecialSpot ∈ {2,3,4,5,7,9}`），
      记下它们的 **格号 / 屏幕坐标 / 名字 / 置信度 / 是否在计划里**，
      并把每个特殊格**裁出来放大存档** ⇒ 供后续逐个标定面板坐标用。

设计（照本项目一贯口径）：
  · **不猜地图码**：按 `--code` 指定，或用 `--auto`（对给定码集取"格子分最高"的那个）
  · **只读**：本工具**不点击、不改状态**（纯截图 + 识别）
  · 复用生产同一个 `spots.Board`（口径与真机一致，不另写一套）
  · 输出：`runs/spec_scan/<时间戳>/` 下
      · `frame.png`             原帧
      · `annotated.png`         全盘标注（格号 + 名字 + 分数）
      · `tiles/<格号>_<名字>_<分>.png`   每个特殊格放大 6×
      · `spec.json`             结构化结果（★ 坐标表就存这里）

用法：
    python spec_scan.py --code S30001                # 抓一帧并扫
    python spec_scan.py --code S30001 --n 5          # 连抓 5 帧（找不同地块）
    python spec_scan.py --code S30001 --img a.png    # 扫已有帧（不连设备）
    python spec_scan.py --code S30001 --all          # 连**普通地块**也一起存（做对照）
"""
from __future__ import annotations

import argparse
import io
import json
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

os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import spots as SP                                    # noqa: E402
import targets_cfg as TC                              # noqa: E402


# 特殊地块：源码 `AreaSpotDataTable` 的 SpecialSpot 枚举
#   ⚠ 本项目**不做** 6（献祭宝箱怪）与 `SpotSize>=35`（异界之门）—— 用户 2026-10-07 明确
SPEC_ALL = {2: 'isMerchantBlock(商人/宝箱怪)', 3: 'isRelicBlock(勇者之墓)',
            4: 'isHeritageBlock(传承祭坛)', 5: 'isTimeLimitGiftBlock(限时礼包)',
            6: 'isTalentBlock(献祭宝箱怪)',
            7: 'isForetellBlock(预言石碑)', 9: 'isGoldenVaultBlock(黄金宝库)'}
SPEC_DO = (2, 3, 4, 5, 7, 9)          # ★ 本项目要做的（不含 6）

FONT = r'C:\Windows\Fonts\msyh.ttc'
DESK = os.path.join(os.path.expanduser('~'), 'Desktop')


def say(*a):
    print(*a, flush=True)


def _pil_text(pil_img, xy, text, size=15, color=(255, 255, 0)):
    from PIL import ImageDraw, ImageFont
    try:
        f = ImageFont.truetype(FONT, size)
    except Exception:               # noqa: BLE001
        f = ImageFont.load_default()
    ImageDraw.Draw(pil_img).text(xy, text, font=f, fill=color)


def annotate(img, st, rows, out_path, title=''):
    """全盘标注：每格写「格号 / 名字 / 分数(SP)」，特殊格描框

    ⚠ 颜色是 **BGR**（OpenCV 口径）：`(0,0,255)` = 红、`(0,140,255)` = 橙、`(255,0,0)` = 蓝
      （我第一版写成 `(255,0,0)` 想要"红"，实际画出来是**蓝的** ✗ 已修）
    """
    from PIL import Image
    px = float(SP.GRID['cx'])
    x0, y0 = float(SP.GRID['x0']), float(SP.GRID['y0'])

    # ① 先在**原图**上描框（OpenCV 画，BGR）
    for r in range(1, int(SP.GRID['rows']) + 1):
        for c in range(1, int(SP.GRID['cols']) + 1):
            X = int(x0 + (c - 1) * px)
            Y = int(y0 + (r - 1) * px)
            v = st.get((r, c)) or {}
            sid = str(v.get('sid') or '')
            sp = int(((rows.get(sid) or {}).get('SpecialSpot')) or 0)
            if sp not in SPEC_ALL:
                continue
            # 红 = 本项目要做的；橙 = 明确不做的（SP=6 献祭宝箱怪）
            col = (0, 0, 255) if sp in SPEC_DO else (0, 140, 255)
            cv2.rectangle(img, (X + 1, Y + 1), (X + int(px) - 2, Y + int(px) - 2),
                          col, 3)

    # ② 再贴文字（PIL，支持中文）
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if title:
        _pil_text(pil, (8, 4), title, 18, (0, 255, 255))
    for r in range(1, int(SP.GRID['rows']) + 1):
        for c in range(1, int(SP.GRID['cols']) + 1):
            X = int(x0 + (c - 1) * px)
            Y = int(y0 + (r - 1) * px)
            v = st.get((r, c)) or {}
            sid = str(v.get('sid') or '')
            sp = int(((rows.get(sid) or {}).get('SpecialSpot')) or 0)
            nm = v.get('name') or '?'
            sc = float(v.get('score') or 0)
            is_do = sp in SPEC_DO
            _pil_text(pil, (X + 3, Y + 2), '%d,%d' % (r, c), 14, (255, 255, 0))
            _pil_text(pil, (X + 3, Y + 19), '%s' % nm[:5], 14,
                      (255, 80, 80) if is_do else (0, 255, 120))
            _pil_text(pil, (X + 3, Y + 36),
                      '%.2f %s' % (sc, ('SP%d' % sp) if sp else ''),
                      13, (200, 200, 200))
    pil.save(out_path)


def crop_tile(img, r, c, out_path, k=6):
    """把一格放大并存档（带格号水印）"""
    px = float(SP.GRID['cx'])
    x0, y0 = float(SP.GRID['x0']), float(SP.GRID['y0'])
    X = int(x0 + (c - 1) * px)
    Y = int(y0 + (r - 1) * px)
    sub = img[Y:Y + int(px), X:X + int(px)]
    if sub.size == 0:
        return False
    big = cv2.resize(sub, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
    big = cv2.copyMakeBorder(big, 34, 8, 8, 8, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(big, '%d,%d' % (r, c), (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 255, 255), 2)
    cv2.imwrite(out_path, big)
    return True


def scan(img, code, outdir, rows, want_all=False):
    """扫一帧 ⇒ 返回特殊格清单"""
    bd = SP.Board(code)
    st = bd.state(img)
    px = float(SP.GRID['cx'])
    x0, y0 = float(SP.GRID['x0']), float(SP.GRID['y0'])
    tiles_dir = os.path.join(outdir, 'tiles')
    os.makedirs(tiles_dir, exist_ok=True)

    spec = []
    for (r, c), v in sorted(st.items()):
        sid = str(v.get('sid') or '')
        sp = int(((rows.get(sid) or {}).get('SpecialSpot')) or 0)
        sz = int(((rows.get(sid) or {}).get('SpotSize')) or 1)
        if not (sp in SPEC_ALL or (want_all and True)):
            continue
        if not sp and not want_all:
            continue
        # 屏幕中心（点它的位置）
        cxp = int(x0 + (c - 1) * px + px / 2)
        cyp = int(y0 + (r - 1) * px + px / 2)
        rec = {
            'cell': '%d,%d' % (r, c), 'row': r, 'col': c,
            'tap_xy': [cxp, cyp],                    # ★ 点击坐标（屏幕中心）
            'sid': sid, 'name': v.get('name'),
            'score': round(float(v.get('score') or 0), 3),
            'ratio': round(float(v.get('ratio') or 0), 3),
            'special_spot': sp,
            'special_meaning': SPEC_ALL.get(sp, ''),
            'in_scope': sp in SPEC_DO,               # ★ 本项目做不做
            'spot_size': sz,
            'revealed': bool(v.get('revealed')),
            'anchor': list(v.get('anchor')) if v.get('anchor') else None,
            'is_target_now': bool(TC.is_target(v.get('name'), sid,
                                               v.get('marks') or [])),
            'is_blocked_now': bool(TC.is_blocked(v.get('name'))),
        }
        spec.append(rec)
        if sp:
            fn = '%s_%s_%s.png' % ('%d%d' % (r, c), (v.get('name') or 'x'),
                                   ('SP%d' % sp))
            crop_tile(img, r, c, os.path.join(tiles_dir, fn))

    annotate(img, st, rows, os.path.join(outdir, 'annotated.png'),
             title='%s  SP found=%d' % (code, len(spec)))
    return st, spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', required=True, help='地图码，如 S30001')
    ap.add_argument('--img', help='扫已有帧（不连设备）')
    ap.add_argument('--n', type=int, default=1, help='连抓几帧')
    ap.add_argument('--all', action='store_true', help='非特殊格也一起记')
    ap.add_argument('--out', help='输出目录（默认 runs/spec_scan/<ts>）')
    a = ap.parse_args()

    outdir = a.out or os.path.join(
        'runs', 'spec_scan', time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(outdir, exist_ok=True)
    rows = SP.spot_rows() or {}
    say('=' * 74)
    say('地图码 %s ｜ 输出 %s' % (a.code, outdir))
    say('=' * 74)

    allrec = []
    imgs = []
    if a.img:
        imgs.append((a.img, None))
    else:
        import mapbot as MB
        b = MB.Bot(log_prefix='specscan', tag='specscan')
        for i in range(max(1, a.n)):
            p = b.snap('spec_%02d' % i, save=True)
            fp = p if os.path.exists(p) else None
            if fp:
                imgs.append((fp, 'runs/%s' % os.path.basename(p)))
            time.sleep(0.6)

    for i, (p, _) in enumerate(imgs):
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            say('  ⚠ 读不到 %s' % p)
            continue
        if img.shape[:2] != (1280, 720):
            say('  ⚠ %s 尺寸 %s ≠ 720x1280 ⇒ 跳过（基准不符）' % (p, img.shape[:2]))
            continue
        sub = os.path.join(outdir, 'f%02d' % i)
        os.makedirs(sub, exist_ok=True)
        cv2.imwrite(os.path.join(sub, 'frame.png'), img)
        st, spec = scan(img, a.code, sub, rows, want_all=a.all)
        say('  帧 %d：找到 **%d** 个（范围内 %d 个）'
            % (i, len(spec), sum(1 for x in spec if x['in_scope'])))
        for x in spec:
            if x['special_spot']:
                say('     %-5s %-10s SP=%-2s %-22s 分=%-6s 点击=%s'
                    % (x['cell'], x['name'], x['special_spot'],
                       x['special_meaning'], x['score'], x['tap_xy']))
        for x in spec:
            x['frame'] = os.path.basename(p)
            x['frame_dir'] = 'f%02d' % i
        allrec += spec

    with open(os.path.join(outdir, 'spec.json'), 'w', encoding='utf-8') as f:
        json.dump({'code': a.code, 'n_frames': len(imgs), 'items': allrec},
                  f, ensure_ascii=False, indent=2)

    say('')
    say('★ 汇总（%d 帧 / %d 条）' % (len(imgs), len(allrec)))
    got = sorted({x['special_spot'] for x in allrec if x['special_spot']})
    say('  出现过的 SpecialSpot：%s' % got)
    for sp in SPEC_DO:
        cnt = sum(1 for x in allrec if x['special_spot'] == sp)
        say('    SP=%-2s %-26s %d 次 %s'
            % (sp, SPEC_ALL[sp], cnt, '' if cnt else '← 还没遇到'))
    say('  ⇒ 坐标表：%s' % os.path.join(outdir, 'spec.json'))
    say('  ⇒ 标注图：%s' % os.path.join(outdir, 'f00', 'annotated.png'))


if __name__ == '__main__':
    main()
