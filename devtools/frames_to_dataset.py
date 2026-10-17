# -*- coding: utf-8 -*-
"""frames_to_dataset.py · 进图首帧 → 结构化地块数据（**只存数据，不出标注图**）

用户 2026-09-27：「后面不用生成标注版本了，你直接存好这些数据准备搞生成算法吧」

识别口径与实盘**完全同源**：`spots.Board(code).state(img)`
（alpha 真实占格 + 掩膜 NCC + 剔高饱和图标像素）——不是另写一套近似实现 ✓
⇒ 数据里记成什么，脚本推图时就认成什么 ✓

每张图一条 JSONL（默认追加到 `runs/boards_dataset.jsonl`）：
```json
{"rel":"acc2/r_204705_0.png","sheet":"S00003","area":"夏日海滩","blocks":[
   {"anchor":[1,4],"sid":"S00003_221","name":"游乐设施","score":0.934,"size":5,
    "cells":[[1,4],[1,5],[2,4],[2,5],[2,6]],"revealed":false,"block_score":0.93}],
 "cells":{"1,1":"S00003_104", ...},          // 35 格全覆盖
 "n_blocks":24,"n_cells":35,"covered":35,"miss":[],"n_revealed":6,
 "mt":1234,"t":"2026-09-27 21:10:00"}
```

用法：
```bash
python frames_to_dataset.py runs/acc2 runs          # 两个目录的首帧一起收（幂等，跳过已入库）
python frames_to_dataset.py runs/acc2 --watch 30    # 每 30 秒扫一次新首帧（边采边入库）
python frames_to_dataset.py runs/acc2 --code S00003 # 强制指定地块表（不 OCR 标题）
python frames_to_dataset.py --stat                  # 只看库里有几条
```
"""
import argparse
import glob
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
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)
import cv2                                    # noqa: E402
import spots as SP                            # noqa: E402


ROWS, COLS = 5, 7
DEFAULT_DS = os.path.join(HERE, 'runs', 'boards_dataset.jsonl')


# --------------------------------------------------------------------------- 基础
def read_bgr(path):
    im = SP.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        return None
    if im.ndim == 3 and im.shape[2] == 4:
        im = cv2.cvtColor(im, cv2.COLOR_BGRA2BGR)
    return im


def lumps(state):
    """state → 块列表（按锚点去重；口径与 board_report.lumps 完全一致 ✓）"""
    seen, out = {}, []
    for (r, c), v in state.items():
        anc = tuple(v['anchor']) if v['anchor'] else (r, c)
        if anc in seen:
            continue
        seen[anc] = True
        cells = [list(tuple(x)) for x in (v['cells'] or [(r, c)])]
        out.append(dict(anchor=list(anc), sid=v['sid'], name=v.get('name'),
                        score=round(float(v['score']), 4), size=v['size'],
                        cells=cells, revealed=bool(v.get('revealed')),
                        block_score=(round(float(v['block_score']), 4)
                                     if v.get('block_score') is not None else None)))
    out.sort(key=lambda d: (d['anchor'][0], d['anchor'][1]))
    return out


# --------------------------------------------------------------------------- 图名识别（离线 OCR）
_OCR_TMP = os.path.join(HERE, 'runs', '_ds_ocr.png')


def ocr_top(bgr, y1=320):
    """离线 OCR 顶部标题区（不碰模拟器）→ 文本列表"""
    try:
        import mapbot
        os.makedirs(os.path.dirname(_OCR_TMP), exist_ok=True)
        cv2.imencode('.png', bgr[:y1])[1].tofile(_OCR_TMP)
        res, _ = mapbot._ocr()(_OCR_TMP)
        return [it[1].strip() for it in (res or []) if float(it[2]) >= 0.4]
    except Exception as e:          # noqa: BLE001
        return ['<ocr失败 %r>' % (e,)]


def detect_area(bgr, mt):
    """从标题 OCR 里认出图名 → (code, area, 全部命中, 冲突码)

    ⚠ 取**最长命中**（'夏日海滩' 命中 '夏日海滩[100]'）；多个不同 S 码同时命中 ⇒ 报冲突
    """
    txt = ' '.join(ocr_top(bgr))
    hits = sorted([k for k in mt if k and k in txt], key=len, reverse=True)
    codes = []
    for k in hits:
        if mt[k] not in codes:
            codes.append(mt[k])
    return (mt[hits[0]] if hits else None), (hits[0] if hits else None), hits, codes


# --------------------------------------------------------------------------- 单张提取
_BOARDS = {}        # code → SP.Board（**必须缓存**：重建一次要几十秒，是最大头）


def board_for(code):
    b = _BOARDS.get(code)
    if b is None:
        b = SP.Board(code)
        _BOARDS[code] = b
    return b


def extract(path, code, area, rel):
    bgr = read_bgr(path)
    if bgr is None:
        return None, '读图失败'
    b = board_for(code)
    st = b.state(bgr)
    blks = lumps(st)
    # ⚠ 2026-09-27 修 bug：`cells` 原先直接摊 `st` 的逐格 sid，与 `blocks` 可以不一致。
    #   根因在 spots.Board.state() 的 `elif o:` 分支漏改 eff（已修）⇒ 物件 footprint 的
    #   成员格带着"自己 raw top1"的 sid。实测 2/84 张图受影响：
    #     S00003_003 宝箱 131→129、S00003_014 限时礼包 24→22、S00003_211 巨大沙堡 152→156
    #   ⇒ 这里改为**由 `blks` 展开**，结构上保证 cells 与 blocks 恒等一致；
    #     未被任何块覆盖的格（理论上不该有）再回退用 st 的逐格 sid，避免丢格。
    cells = {}
    for blk in blks:
        for rc in blk['cells']:
            key = '%d,%d' % (rc[0], rc[1])
            if key in cells and cells[key] != blk['sid']:
                print('   ⚠ 成员格归属冲突：%s  %s → %s' % (key, cells[key], blk['sid']))
            cells[key] = blk['sid']
    for key, v in st.items():
        k2 = '%d,%d' % key
        if k2 not in cells:
            cells[k2] = v['sid']
    cover = set()
    for x in blks:
        cover |= {tuple(y) for y in x['cells']}
    full = {(r, c) for r in range(1, ROWS + 1) for c in range(1, COLS + 1)}
    miss = sorted('%d,%d' % k for k in (full - cover))
    rec = dict(rel=rel.replace('\\', '/'), sheet=code, area=area,
               blocks=blks, cells=cells,
               n_blocks=len(blks), n_cells=len(cover), covered=len(cover),
               miss=miss,
               n_revealed=sum(1 for v in st.values() if v.get('revealed')),
               mt=int(os.path.getmtime(path)),
               t=time.strftime('%Y-%m-%d %H:%M:%S'))
    return rec, None


# --------------------------------------------------------------------------- 库
def load_keys(ds):
    keys = set()
    if not os.path.exists(ds):
        return keys
    with open(ds, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                keys.add(json.loads(ln)['rel'])
            except Exception:       # noqa: BLE001
                pass
    return keys


def append_rec(ds, rec):
    os.makedirs(os.path.dirname(ds), exist_ok=True)
    with open(ds, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def frames_of(dirs):
    """目录 → 按时间排序的 `r_*_0.png` 首帧（也接受直接给单张 png）"""
    out = []
    for d in dirs:
        if os.path.isfile(d):
            out.append(d)
            continue
        out += glob.glob(os.path.join(d, 'r_*_0.png'))
    return sorted(set(out))


def rel_of(path):
    """⚠ 必须归一化为**正斜杠**：库里 rel 由 extract() 写成 `runs/acc2/xxx.png`，
    而 os.path.relpath 在 Windows 下返回 `runs\\acc2\\xxx.png` ⇒ 不归一化会让
    load_keys 的判重**永远失配**，每次运行都全量重做（2026-09-27 踩坑：
    连续 4 次调用把库从 115 撑到 193 行全重复）。"""
    try:
        return os.path.relpath(path, HERE).replace('\\', '/')
    except Exception:               # noqa: BLE001
        return path.replace('\\', '/')


# --------------------------------------------------------------------------- main
def run_once(dirs, ds, code, mapname, quiet=False, limit=0):
    mt = SP.map_table()
    keys = load_keys(ds)
    todo = [p for p in frames_of(dirs) if rel_of(p) not in keys]
    if limit:
        todo = todo[:limit]
    if not todo:
        if not quiet:
            print('没有新首帧（库里已有 %d 条）✓' % len(keys))
        return 0
    n_ok, n_bad, t0 = 0, 0, time.time()
    for i, p in enumerate(todo, 1):
        rel = rel_of(p)
        _code, area = code, mapname
        note = ''
        if not _code:
            bgr = read_bgr(p)
            if bgr is None:
                print('  ✗ %s 读图失败' % rel)
                n_bad += 1
                continue
            got, area2, hits, codes = detect_area(bgr, mt)
            if got:
                _code = got
                area = area2
            else:
                print('  ✗ %s 认不出地图（OCR 未命中任何图名）⇒ 跳过，请用 --code 指定' % rel)
                n_bad += 1
                continue
            if len(codes) > 1:
                note = ' ⚠ 图名冲突 %s 取最长命中' % codes
        if not _code:
            print('  ✗ %s 没给地块表 ⇒ 跳过' % rel)
            n_bad += 1
            continue
        rec, err = extract(p, _code, area, rel)
        if rec is None:
            print('  ✗ %s %s' % (rel, err))
            n_bad += 1
            continue
        append_rec(ds, rec)
        n_ok += 1
        sides = {}
        for b in rec['blocks']:
            _sz = b['size']
            if isinstance(_sz, (list, tuple)):      # 兜底：万一是坐标元组
                _sz = len(b['cells'])
            sides[int(_sz)] = sides.get(int(_sz), 0) + 1
        side_txt = ' '.join(['%d格x%d' % (k, v) for k, v in sorted(sides.items())])
        print('  [%d/%d] %-24s %s %-6s %2d 块 / 覆盖 %2d/35 / 已揭示 %2d  (格数分布 %s)%s'
              % (i, len(todo), rel, _code, area or '?', rec['n_blocks'], rec['covered'],
                 rec['n_revealed'], side_txt, note))
    print('入库 %d 条（失败 %d），耗时 %.1f 秒 → %s'
          % (n_ok, n_bad, time.time() - t0, ds))
    return n_ok


def stat(ds):
    if not os.path.exists(ds):
        print('库还不存在：%s' % ds)
        return
    recs = [json.loads(l) for l in open(ds, encoding='utf-8') if l.strip()]
    from collections import Counter
    by_sheet = Counter(r['sheet'] for r in recs)
    print('库：%s' % ds)
    print('  共 %d 张；按表：%s' % (len(recs), dict(by_sheet)))
    for s in sorted(by_sheet):
        rs = [r for r in recs if r['sheet'] == s]
        nb = [r['n_blocks'] for r in rs]
        cov = [r['covered'] for r in rs]
        print('  %s：%d 张 · 块数 %d~%d（均 %.1f）· 覆盖 %d~%d/35 · 已揭示均 %.1f'
              % (s, len(rs), min(nb), max(nb), sum(nb) / len(nb),
                 min(cov), max(cov), sum(r['n_revealed'] for r in rs) / len(rs)))


def main():
    ap = argparse.ArgumentParser(description='进图首帧 → 结构化地块数据（只存数据）')
    ap.add_argument('dirs', nargs='*', help='目录或单张 png（默认 runs/acc2 runs）')
    ap.add_argument('--out', default=DEFAULT_DS, help='数据集路径（默认 runs/boards_dataset.jsonl）')
    ap.add_argument('--code', default=None, help='强制地块表 S 码（不给就 OCR 标题自动认）')
    ap.add_argument('--map', default=None, help='强制图名（默认与 --code 配套）')
    ap.add_argument('--watch', type=int, default=0, help='每 N 秒扫一次新首帧（0=只跑一次）')
    ap.add_argument('--limit', type=int, default=0, help='本次最多处理几张（0=不限）')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--stat', action='store_true', help='只打印库概览')
    a = ap.parse_args()

    if a.stat:
        stat(a.out)
        return 0
    dirs = a.dirs or [os.path.join(HERE, 'runs', 'acc2'), os.path.join(HERE, 'runs')]
    if a.watch:
        print('👀 watch：每 %d 秒扫一次 %s' % (a.watch, dirs))
        while True:
            try:
                run_once(dirs, a.out, a.code, a.map, quiet=True, limit=a.limit)
            except KeyboardInterrupt:
                print('\n⏹ 停止 watch')
                return 0
            except Exception as e:      # noqa: BLE001
                print('⚠ 异常（继续）：%r' % (e,))
            time.sleep(max(5, a.watch))
    run_once(dirs, a.out, a.code, a.map, quiet=a.quiet, limit=a.limit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
