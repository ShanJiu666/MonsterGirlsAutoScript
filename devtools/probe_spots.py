# -*- coding: utf-8 -*-
"""probe_spots.py · 采样本 + 验证地块分类器（纯视觉，不打架）

一轮的动作：
  1. 处理已开的面板（关掉；不打架 —— 没传 marks 上下文时战斗面板会被跳过）
  2. `spots.Board` 逐格分类 + 颜色判「迷雾 / 空沙地 / 内容格」
  3. 有内容格 → 点**分类分最高**的那格（商人/宝库优先），读面板文字当真值，落盘
  4. 没有内容格 → 点一格「已揭示的空沙地」推进（连通消除，露出新格）
  5. 到达轮数上限 / 无可点 → 收工，输出混淆表

真值判定：面板文字里**整条等于** Area_Spot 名字的（如「旅行商人」「黄金宝库」），
取最靠上的那条；没有则记 None（无面板/面板无标题）。

用法:
    python probe_spots.py --map 夏日海滩 --rounds 40
    python probe_spots.py --map 夏日海滩 --rounds 40 --reveal-only   # 只揭格采图，不点内容格
"""
import argparse
import json
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

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
import cv2
import numpy as np
import explore_loop as EL
import spots as SP
from mapbot import Bot, RUNS


SAND = (179, 236, 255)      # BGR 沙地浅黄


def cell_feats(board, img, r, c):
    sub = board.patch(img, r, c)
    if sub is None:
        return None
    k = int(round(SP.INNER / 32.0 * board.scale * 32.0))
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)[k:-k, k:-k]
    b, gr, rr = [v.mean() for v in cv2.split(sub.astype(float))]
    diff = max(rr, gr, b) - min(rr, gr, b)
    sand = ((rr >= 235) & (gr >= 185) & (b >= 105) & (b <= 225)).mean()
    return {'diff': round(float(diff), 1), 'gsd': round(float(g.std()), 1),
            'sand': round(float(sand), 2), 'rgb': (int(rr), int(gr), int(b))}


def truth_of(items, names):
    """面板真值 = 整条文本 == Area_Spot 名字（排除 HUD/导航行），按 cy 升序

    实测版面（2026-09-25）：
      * 大物件（SpotSize>1）点开的是**左右两块面板**：左标题(cx≈274,cy≈224)=地块名，
        右标题(cx≈805,cy≈224)=敌方队伍名（摸鱼小队/巡逻卫队…）
      * 单格特殊地块（旅行商人…）点开的是整块面板，标题在 (688,601)
      * HUD 行 cy 900~1010（背包/神石/预言）、底部导航 cy>1800 必须排除
    """
    out = []
    for it in items:
        t = it['text'].strip()
        if t not in names:
            continue
        if 880 < it['cy'] < 1030 or it['cy'] > 1750:
            continue
        out.append((it['cy'], it['cx'], t))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', dest='mapname', default='夏日海滩')
    ap.add_argument('--code')
    ap.add_argument('--rounds', type=int, default=40)
    ap.add_argument('--reveal-only', action='store_true')
    ap.add_argument('--maxframes', type=int, default=0)
    ap.add_argument('--out', default=os.path.join(RUNS, 'probe_spots.json'))
    a = ap.parse_args()

    code = a.code or SP.code_of(a.mapname)
    rows = SP.spot_rows()
    names = {r.get('Name') for r in rows.values() if r.get('Name')}
    board = SP.Board(code, maxframes=a.maxframes)
    print('图 %s → %s：候选 %d 地块 / %d 帧' % (a.mapname, code, len(set(board.sids)), len(board.meta)))

    b = Bot(log_prefix='ps')
    log = []
    if not EL.ensure_in_map(b, log):
        print('进图失败', log)
        return 1
    recs = []
    done, cold = set(), {}
    for rnd in range(a.rounds):
        p = b.snap('ps_%03d' % rnd)
        items = b.ocr()
        img = b.img()
        act = EL.popups(b, items, log)
        if act in ('kicked', 'insufficient'):
            print('中断:', act)
            break
        if act in ('battle', 'battle_clear'):
            continue
        if act == 'handled':
            continue
        sc = board.scores(img)
        st = board.state(img)
        feats = {}
        plains, contents = [], []
        for (r, c), lst in sc.items():
            f = cell_feats(board, img, r, c)
            if f is None:
                continue
            feats[(r, c)] = f
            if (r, c) in done or cold.get((r, c), 0) >= 2:
                continue
            v = st.get((r, c)) or {}
            if v.get('anchor') != (r, c):
                continue
            sid, sco = lst[0][1], lst[0][0]
            if not v.get('revealed'):
                continue                      # 暗格点不动
            if SP.is_plain_spot(sid):
                plains.append((r, c, sid, sco, f))
            else:
                contents.append((r, c, sid, sco, f))
        if not contents and not plains:
            print('无可点格，收工')
            break
        want = {sid for sid, r in rows.items()
                if sid.startswith(code) and (r.get('Name') in SP.BUY_OUT_NAMES)}
        r = c = None
        if contents and not a.reveal_only:
            contents.sort(key=lambda t: (t[2] not in want, -t[3]))
            r, c, sid, sco, f = contents[0]
        elif plains:
            plains.sort(key=lambda t: -t[3])
            r, c, sid, sco, f = plains[0]
        else:
            break
        cx = int(SP.GRID['x0'] + (c - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        cy = int(SP.GRID['y0'] + (r - 1) * SP.GRID['pitch'] + SP.GRID['pitch'] / 2)
        b.tap(cx, cy, wait=2.2)
        p2 = b.snap('ps_%03d_after' % rnd)
        it2 = b.ocr()
        ts = truth_of(it2, names)
        rec = {'round': rnd, 'cell': (r, c), 'tap': (cx, cy), 'kind': 'content' if contents and not a.reveal_only and (r, c) == contents[0][:2] else 'plain',
               'top1': sid, 'score': round(sco, 3), 'feat': f,
               'truth': [t for _y, _x, t in ts], 'pre_png': os.path.basename(p),
               'after_png': os.path.basename(p2),
               'texts': [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy']} for i in it2]}
        recs.append(rec)
        if rec['kind'] == 'content':
            print('#%-3d 内容格(%d,%d) 分类=%-12s %.3f  面板名=%s' %
                  (rnd, r, c, sid, sco, [t for _y, _x, t in ts] or '-'))
            if ts:
                done.add((r, c))
            else:
                cold[(r, c)] = cold.get((r, c), 0) + 1
        else:
            print('#%-3d 揭格   (%d,%d) 分类=%-12s %.3f' % (rnd, r, c, sid, sco))
            cold[(r, c)] = cold.get((r, c), 0) + 1
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump({'map': a.mapname, 'code': code, 'records': recs, 'log': log},
                  f, ensure_ascii=False, indent=1)
    print('明细:', a.out)
    conf = {}
    for rec in recs:
        if rec['kind'] != 'content':
            continue
        t = rec['truth'][0] if rec['truth'] else None
        conf[(rec['top1'], t)] = conf.get((rec['top1'], t), 0) + 1
    print('=== 分类 vs 面板真值 ===')
    for (pred, t), n in sorted(conf.items(), key=lambda kv: -kv[1]):
        print('   %-12s(%-6s) -> %-10s x%d' % (pred, rows.get(pred, {}).get('Name', '?'),
                                               t or '(无面板)', n))
    return 0


if __name__ == '__main__':
    sys.exit(main())
