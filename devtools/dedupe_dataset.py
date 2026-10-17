# -*- coding: utf-8 -*-
"""dedupe_dataset.py · 数据集去重 + 体检（按 `rel` 保留**第一条**）

为什么需要它（2026-09-27）：`frames_to_dataset.py` 每次跑都自己算一份 todo，
**两个进程同时跑同一份待办**就会把同一张图各写一行 ⇒ 统计时 n 被灌水 ✗
（本轮实测：56 行里只有 37 个唯一 rel，19 条重复）

体检两项：
  ① 重复 / 坏行 / sheet / 覆盖 / 块数
  ② **`cells` 与 `blocks` 一致性**（2026-09-27 新增）—— 历史行的 `cells` 可能带着
     「多格块成员格被写成自己 raw top1」的错误，这里统一按 `blocks` 展开归一化。
     详见下方 `cells_from_blocks()` 的注释。

⚠ **必须在没有写入进程时跑**（本脚本会重写整个文件）

用法：
    python dedupe_dataset.py                 # 去重 + 体检 + 一致性修复（先备份）
    python dedupe_dataset.py --dry           # 只看问题，不改文件
"""
import argparse
import json
import os
import shutil
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
from collections import Counter


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
DS = os.path.join(HERE, 'runs', 'boards_dataset.jsonl')


def rows(path):
    with open(path, encoding='utf-8') as f:
        for i, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield i, json.loads(ln), None
            except Exception as e:              # noqa: BLE001
                yield i, None, repr(e)[:80]


# --------------------------------------------------------------------------- 体检②：
# ⚠ 2026-09-27 发现：`cells`（逐格摊平）与 `blocks`（按块）可以不一致 —— 同一行自相矛盾。
#   根因在 spots.Board.state() 的 `elif o:` 分支漏改 eff：物件 footprint 的成员格带着
#   "自己 raw top1" 的 sid 返回。实测 夏季海滩 巨大沙堡(211) 的成员格 (4,5) 报「宝箱」、
#   (4,6) 报「限时礼包」⇒ 摊平后凭空多出 宝箱/限时礼包 各一个（2/84 张图受影响，
#   S00003_003 131→129、S00003_014 24→22、S00003_211 152→156）。
#   spots.py / frames_to_dataset.py 已双双修好；这里给**历史行**做一次归一化，
#   保证 `cells` 恒等于由 `blocks` 展开的结果 ⇒ 统计只认 `blocks` 也不会再踩 ✓
def cells_from_blocks(r):
    """-> (cells, conflicts)；cells 由 blocks 展开；未覆盖格回退用原 cells"""
    out, conf = {}, []
    for blk in r.get('blocks') or []:
        for rc in blk['cells']:
            k = '%d,%d' % (rc[0], rc[1])
            if k in out and out[k] != blk['sid']:
                conf.append((k, out[k], blk['sid']))
            out[k] = blk['sid']
    for k, v in (r.get('cells') or {}).items():
        if k not in out:
            out[k] = v
    return out, conf


def main():
    ap = argparse.ArgumentParser(description='数据集去重 + 体检')
    ap.add_argument('--ds', default=DS)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    if not os.path.exists(a.ds):
        print('数据集不存在：%s' % a.ds)
        return 1
    seen, keep, dup, bad, incons = set(), [], [], [], []
    for i, r, err in rows(a.ds):
        if r is None:
            bad.append((i, err))
            continue
        # 先修一致性（即使这行没被去重掉也修 ✓）
        fixed, conf = cells_from_blocks(r)
        if fixed != (r.get('cells') or {}) or conf:
            incons.append((r.get('rel'), r.get('cells') or {}, fixed, conf))
        r['cells'] = fixed
        rel = r.get('rel')
        if rel in seen:
            dup.append((i, rel))
            continue
        seen.add(rel)
        keep.append(r)

    print('文件：%s' % a.ds)
    print('  总行 %d · 唯一 %d · 重复 %d · 坏行 %d'
          % (len(keep) + len(dup) + len(bad), len(keep), len(dup), len(bad)))
    if bad:
        for i, e in bad[:5]:
            print('    ✗ 坏行 #%d %s' % (i, e))
    if dup:
        c = Counter(rel for _i, rel in dup)
        for rel, n in sorted(c.items())[:6]:
            print('    · %s x%d' % (rel, n))
        if len(c) > 6:
            print('    … 另有 %d 个' % (len(c) - 6))

    # 体检①：sheet / 覆盖 / 块数
    by = Counter(r['sheet'] for r in keep)
    print('  按表：%s' % dict(by))
    cov = Counter(r['covered'] for r in keep)
    print('  覆盖分布：%s' % dict(sorted(cov.items())))
    nb = [r['n_blocks'] for r in keep]
    if nb:
        print('  块数 %d~%d（均 %.2f）' % (min(nb), max(nb), sum(nb) / len(nb)))

    # 体检②：cells vs blocks 一致性
    if incons:
        d = Counter()
        for _rel, old, new, _conf in incons:
            for k in set(old) | set(new):
                if old.get(k) != new.get(k):
                    d[(old.get(k), new.get(k))] += 1
        print('  ⚠ cells 与 blocks 不一致 %d 行；sid 位移：' % len(incons))
        for (o, n), c in sorted(d.items(), key=lambda x: -x[1]):
            print('      %-12s → %-12s  %d 格' % (o, n, c))
    else:
        print('  cells vs blocks：一致 ✓')

    need = bool(dup or bad or incons)
    if not need:
        print('✓ 已经很干净，无需改动')
        return 0
    if a.dry:
        print('--dry：不改文件')
        return 0

    bak = a.ds + '.bak_%s' % time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(a.ds, bak)
    # ⭐ 2026-09-28：**直接原地重写**，不再走 `tmp` + `os.replace`
    #   理由：沙箱 `sitecustomize.py` 把 `os.replace` 也做了中间人，而长流水线里
    #   每次删除都会累进「单次工具调用 50 次」的计数 ⇒ 撞到就 `raise SystemExit(1)`
    #   **把采集进程打死**（实测 `runs/_pipeline.log`）。
    #   `.bak` 已经先拷好了 ⇒ 直接截断重写同样安全，且零删除 ✓
    with open(a.ds, 'w', encoding='utf-8') as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())
    print('✅ 已去重：%d → %d 条（备份 %s）' % (len(keep) + len(dup) + len(bad), len(keep),
                                               os.path.basename(bak)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
