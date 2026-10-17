# -*- coding: utf-8 -*-
"""shot_board_collect.py · 从**截图+OCR 的产出**里收割每张图的地块布局（纯文件 ✓ 零干扰）

⭐ 纯视觉路线：本脚本**不碰设备、不做任何注入**，只解析 `runs/loop/loop_log.json`
     （那份日志的 `board` / `marks` 就是脚本每轮截图 + OCR 的结果 ✓）

数据来源（`explore_loop.py` 每轮决策都会写）：
    {"round": N, "stamina": …, "marks": {"5,2": ["boss"]},
     "board": {"1,1": ["201", "海边杂物", 0.959, 0.666], …}}   ← 截图+OCR 逐格识别
     字段 = [地块ID, 中文名, 置信度, 面积比]

⭐ 关键用法：**跨轮合并**。单帧只能看到「已揭示」的格子；把同一张图**所有轮**的
   board 并起来 ⇒ 随着揭格推进，布局逐步补全 ✓（这正是纯视觉路线的正确姿势）

产出：`runs/shot_boards.jsonl`，每张图一条：
    {map_idx, area, difficulty, n_rounds, cells:{...}, marks:{...}, coverage}
    coverage = 识别格数 / 35（**缺的就是没揭示的灰雾格 ✗**）

⚠ 边界（实测，别指望它给路网）：
    · 拿得到：格子的**地块身份**（ID + 中文名 + 置信度）、标记（boss/宝箱/商人…）、
      地图名与难度（来自 OCR 文本）、营地位置
    · **拿不到**：`roadMap`（画面 35 格只有地块美术/灰雾，**没有道路视觉元素** ✗）、
      `blockList` / `blockBoard`（块号结构）、从未揭示的格子
    ⇒ 对「拟合路网生成算法」这条路**无效**；对「地块布局/标记/掉落统计」**有效** ✓

用法：
    python shot_board_collect.py                  # 收割一次，打印每张图
    python shot_board_collect.py --watch          # 持续盯着日志（每 20 秒看一次 ✓）
    python shot_board_collect.py --json           # 只输出 JSON
"""
import argparse
import json
import os
import re
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


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)
LOG_PATH = os.path.join(HERE, 'runs', 'loop', 'loop_log.json')
OUT = os.path.join(HERE, 'runs', 'shot_boards.jsonl')
ROWS, COLS, N = 5, 7, 35

# ⚠ 2026-09-27 口径修正（**很重要**）：
#   `board` 字典的键是**块的锚点**（`spots.py` 里每块带 anchor/cells/size ✓），
#   而 `explore_loop.py:3006` 只记 `v['anchor'] == k` 的格
#   ⇒ **一个多格地块只记一条** ⇒ `len(cells)` 是**块数**，不是格数 ✗
#   （我一开始写「23/35 = 66%」就是这么错的 ✗）
# 尺寸档编码在 **IDs 百位**（数据表里**没有** size 字段 ✓）：
#   _0xx = 1 格 / _1xx = 2~3 格 / _2xx = 4 格 / _3xx = 6~9 格
#   ⇒ 只能按百位**估算**占格数（取下限，保守 ✓）
SIZE_BY_HUNDRED = {0: 1, 1: 2, 2: 4, 3: 6}

# ⭐ 2026-09-27 用户核对反馈后新增：**置信度门槛**
#   用户看图核对：「除了战斗地块都对。战斗地块这种多格子连一起的，首格子写的也对。
#   就是图二 3,1 错了，3,1 是战斗格子这个战斗格子也没识别到。
#   3,6 作为幸运草的战斗格子也没识别到」
#   ⇒ 问题根因：**战斗地块上压着图标**（绿幸运草/红宝箱/怪物），盖住地块美术
#     ⇒ OCR 要么漏识别，要么**误识别**（3,1 只有 conf 0.423 却被写成「003 宝箱」✗）
#   ⇒ 对策：conf < 门槛的格**不当地块真值** —— 单独放进 `suspect`，免得污染统计数据 ✓
CONF_MIN = 0.6

# ⭐ 地块表 → 地图名 的**种子映射**
#   为什么需要：`area` 靠 OCR 文本 `夏日海滩[100]` 提，而那只在**碰到特定面板**（如「黄金宝库」）
#   时才有 texts ⇒ 多数图拿不到 ✗；而地块集本身**唯一标识地图**（同一个 `S00003` 就是同一张图的
#   地块池 ✓）⇒ 用种子 + 运行时学到的映射一起补全 ✓
#   `S00003 = 夏日海滩` 由用户 2026-09-27 截图顶部 `夏日海滩[100]` + OCR 名 24/24 吻合确认 ✓
SHEET_AREA_SEED = {'S00003': '夏日海滩'}


def est_cells(cells):
    """按 IDs 百位估算这些块一共占多少格（下限，保守 ✓）"""
    n = 0
    for v in cells.values():
        h = 0
        try:
            h = int(str(v[0]).zfill(3)[0])
        except Exception:                   # noqa: BLE001
            h = 0
        n += SIZE_BY_HUNDRED.get(h, 1)
    return n


def _load():
    try:
        with open(LOG_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, list) else (d.get('log') or [])
    except Exception:                       # noqa: BLE001
        return []


def _texts(m):
    """从这张图的**所有事件**里抠 OCR 文本（`地图名[难度]` 常在 `special` 事件里 ✓）"""
    out = list(m.get('texts') or [])
    for e in m['rounds']:
        for t in (e.get('texts') or []):
            out.append(str(t))
        for k in ('area', 'special', 'name'):
            if isinstance(e.get(k), str):
                out.append(e[k])
    return out


def parse(ev):
    """把扁平事件流切成「每张图」——按 `{'map': N, 'end_reason'|'finished'}` 分界 ✓"""
    maps, cur = [], None
    for e in ev:
        if not isinstance(e, dict):
            continue
        if cur is None:
            cur = {'map_idx': 0, 'rounds': []}
        if e.get('texts'):
            cur.setdefault('texts', []).extend(str(t) for t in e['texts'])
        if 'round' in e and ('board' in e or 'marks' in e):
            cur['rounds'].append(e)
        if 'map' in e and ('end_reason' in e or 'finished' in e):
            cur['end_reason'] = e.get('end_reason')
            cur['finished'] = e.get('finished')
            cur['map_idx'] = e.get('map', len(maps))
            maps.append(cur)
            cur = None
    if cur and cur['rounds']:
        maps.append(cur)
    return maps


_SHEET_CACHE = {'by_suf': None, 'full': None}


def _sheets():
    """数据表里按 prefix 分组的 (后缀 → 名称)：`S00003` = 夏日海滩那套 ✓

    ⚠ 2026-09-27 重要：地块表是**按地图分组**的 —— 同一个后缀 `201`
      在 `S00001` 是「霜冻图腾」、在 `S00003` 是「海边杂物」✗
      ⇒ 统计地块出现率**必须先用对表**，否则结论全错 ✗
    """
    if _SHEET_CACHE['by_suf'] is not None:
        return _SHEET_CACHE['by_suf']
    by = {}
    try:
        import spots as SP
        for k, r in (SP.spot_rows() or {}).items():
            p, suf = str(k).split('_')[0], str(k).split('_')[-1]
            by.setdefault(p, {})[suf] = (r.get('Name') or r.get('name') or '')
    except Exception:                   # noqa: BLE001
        pass
    _SHEET_CACHE['by_suf'] = by
    return by


def guess_sheet(cells):
    """用 OCR 出的 (ID, 中文名) 反查这是哪张地块表 ⇒ 返回 (prefix, 命中数, 总数) ✓"""
    by = _sheets()
    best, bs = None, 0
    for p, d in by.items():
        s = sum(1 for v in cells.values() if len(v) > 1 and d.get(v[0]) == v[1])
        if s > bs:
            best, bs = p, s
    return best, bs, len(cells)


def merge(m, mode='first'):
    """一张图 → 一条记录

    mode='first'  ⭐ **只用刚进图那一帧**（2026-09-27 用户指示：
                    「只存每张图刚进去的那张图的数据就行吧。为了生成算法存」）
                  ⇒ 第一帧最干净、也最全（实测 round 0 = 23 格，后面 22→21 逐轮变少，
                    因为探索过程中图标会盖住地块美术 ⇒ 置信度下降/识别失败 ✗）
    mode='merged' ⇒ 跨轮合并（揭示更多，但混入探索过程噪声）
    """
    rounds = m['rounds']
    use = rounds[:1] if mode == 'first' else rounds
    cells, marks = {}, {}
    for r in use:
        for k, v in (r.get('board') or {}).items():
            if isinstance(v, list) and v:
                cells[k] = v
        for k, v in (r.get('marks') or {}).items():
            marks.setdefault(k, [])
            for x in (v if isinstance(v, list) else [v]):
                if x not in marks[k]:
                    marks[k].append(x)
    txts = _texts(m)
    area, diff = None, None
    for t in txts:
        mm = re.search(r'([\u4e00-\u9fa5·]{2,10})\[(\d+)\]', t)
        if mm:
            area, diff = mm.group(1), int(mm.group(2))
            break
    sheet, hit, tot = guess_sheet(cells)
    ec = est_cells(cells)
    # ⭐ 拆出「可疑格」：conf < CONF_MIN 的**不当地块真值** ✓
    #   （战斗地块被图标遮挡 ⇒ 误识别/漏识别，正是用户核对发现的问题 ✓）
    suspect = {k: v for k, v in cells.items() if len(v) > 2 and float(v[2]) < CONF_MIN}
    cells_ok = {k: v for k, v in cells.items() if k not in suspect}
    # 有标记的格（boss/clover/红装…）也单列：那格上一定有东西，地块识别**不可信** ✓
    marks = dict(marks)
    marked = sorted(marks.keys())
    return {'map_idx': m.get('map_idx'), 'mode': mode,
            'area': area, 'difficulty': diff,
            'sheet': sheet, 'sheet_hit': '%d/%d' % (hit, tot),
            'round_no': (use[0].get('round') if use else None),
            'n_rounds': len(rounds), 'n_used': len(use),
            'n_blocks': len(cells),                 # 块数（含可疑 ✓）
            'n_suspect': len(suspect),
            'est_cells': ec,                        # 估算占格数（按 IDs 百位 ✓）
            'coverage': round(min(1.0, ec / float(N)), 3),
            'cells': cells_ok,                      # ✅ 可信地块（conf ≥ CONF_MIN）
            'suspect': suspect,                     # ⚠ 不可信（多半被图标遮挡）
            'marked': marked,                       # ⚠ 有标记的格（地块识别必受影响）
            'marks': marks,
            'end_reason': m.get('end_reason'), 'finished': m.get('finished')}


def save(recs):
    """追加去重（按 mode + 地图 + cells 指纹）"""
    seen = set()
    if os.path.exists(OUT):
        for ln in open(OUT, encoding='utf-8'):
            try:
                r = json.loads(ln)
                seen.add((r.get('mode') or 'first', r.get('area'), r.get('difficulty'),
                          ','.join(sorted(r.get('cells') or {}))))
            except Exception:               # noqa: BLE001
                pass
    n = 0
    with open(OUT, 'a', encoding='utf-8') as f:
        for r in recs:
            fp = (r.get('mode') or 'first', r.get('area'), r.get('difficulty'),
                  ','.join(sorted(list(r['cells']) + list(r.get('suspect') or {}))))
            if not r['cells'] or fp in seen:
                continue
            seen.add(fp)
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            n += 1
    return n


def show(recs):
    for r in recs:
        if not r['cells']:                  # 退图前的补点轮次没有 board ⇒ 跳过 ✓
            continue
        tag = ('**刚进图那一帧** round=%s' % r.get('round_no')) \
            if r.get('mode') == 'first' else ('跨 %d 轮合并' % r.get('n_used', 0))
        print()
        print('--- 图 %s：%s d%s  地块表=%s(%s)  （%s）---'
              % (r['map_idx'], r.get('area') or '?', r.get('difficulty') or '?',
                 r.get('sheet') or '?', r.get('sheet_hit') or '?', tag))
        print('    **块数 %d 个（可疑 %d）/ 估算占 %d 格 / 棋盘 %d 格**'
              % (r.get('n_blocks', 0), r.get('n_suspect', 0),
                 r.get('est_cells', 0), N))
        if not r['cells'] and not r.get('suspect'):
            print('    （还没识别到任何地块）')
            continue
        from collections import Counter
        c = Counter((v[0], v[1]) for v in r['cells'].values())
        for (sid, nm), k in c.most_common():
            print('    %-7s %-12s ×%d' % (sid, nm, k))
        if r.get('suspect'):
            print('    ⚠ 可疑格 %d 个（conf<%.2f ⇒ **不当地块真值**）：%s'
                  % (len(r['suspect']), CONF_MIN,
                     '  '.join('%s→%s(%.2f)' % (k, v[1], v[2])
                               for k, v in sorted(r['suspect'].items()))))
        if r.get('marked'):
            print('    ⚠ 有标记的格（地块识别必受影响）：%s'
                  % '  '.join('%s→%s' % (k, ','.join(r['marks'][k])) for k in r['marked']))
        print('    未覆盖（估算）：约 %d 格 = 未揭示的灰雾 ✗' % max(0, N - r.get('est_cells', 0)))


def once(quiet=False, mode='first'):
    ev = _load()
    if not ev:
        if not quiet:
            print('读不到 %s（脚本还没跑过？）' % LOG_PATH)
        return []
    recs = [merge(m, mode) for m in parse(ev)]
    # ⭐ 地图名补全：`area` 靠 OCR 文本 `夏日海滩[100]` 提，但那只在**碰到特定面板**
    #   （如「黄金宝库」）时才有 texts ⇒ 有的图会拿不到 ⇒ area=None ✗
    #   而地块集本身**唯一标识地图**（`S00003` 就是夏日海滩 ✓）
    #   ⇒ 用已确认记录的 `sheet → area` 映射补全 ✓
    known = {}
    if os.path.exists(OUT):
        for ln in open(OUT, encoding='utf-8'):
            try:
                r0 = json.loads(ln)
                if r0.get('sheet') and r0.get('area'):
                    known[r0['sheet']] = (r0['area'], r0.get('difficulty'))
            except Exception:               # noqa: BLE001
                pass
    for r in recs:
        if not r.get('area') and r.get('sheet') in known:
            r['area'], r['difficulty'] = known[r['sheet']]
            r['area_src'] = 'sheet映射'
        if not r.get('area') and r.get('sheet') in SHEET_AREA_SEED:
            r['area'] = SHEET_AREA_SEED[r['sheet']]
            r['area_src'] = '种子映射'
    if not quiet:
        show(recs)
        n = save(recs)
        print()
        print('已入库 %d 张新图 → %s（mode=%s）' % (n, OUT, mode))
        print('⚠ 边界：截图+OCR **拿不到 roadMap**（画面无道路视觉元素）'
              '与块号结构；缺的格子=从未揭示 ✓')
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--watch', action='store_true', help='持续盯着日志（每 20 秒 ✓）')
    ap.add_argument('--interval', type=float, default=20.0)
    ap.add_argument('--json', action='store_true', help='只输出 JSON')
    ap.add_argument('--mode', choices=('first', 'merged'), default='first',
                    help='first=只存刚进图那一帧（默认 ✓ 用户要求）；merged=跨轮合并')
    a = ap.parse_args()

    if a.json:
        recs = once(quiet=True, mode=a.mode)
        print(json.dumps(recs, ensure_ascii=False, indent=1))
        return
    if not a.watch:
        once(mode=a.mode)
        return
    print('=== 盯着 %s（只读文件 ✓ 不碰设备 ✓）每 %.0f 秒看一次，mode=%s ==='
          % (LOG_PATH, a.interval, a.mode))
    last, tot = None, 0
    try:
        while True:
            try:
                mt = os.path.getmtime(LOG_PATH)
            except OSError:
                mt = None
            if mt != last:
                last = mt
                recs = once(quiet=True, mode=a.mode)
                n = save(recs) if recs else 0
                tot += n
                if n:
                    print('[%s] ★ 新入库 %d 张（累计 %d）'
                          % (time.strftime('%H:%M:%S'), n, tot))
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print('\n收工，累计入库 %d 张 → %s' % (tot, OUT))


if __name__ == '__main__':
    main()
