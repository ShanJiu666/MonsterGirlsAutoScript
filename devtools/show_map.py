# -*- coding: utf-8 -*-
"""show_map.py · 干净地显示一张真实地图（按真判据 ✓ 用户要"看看数据准不准"✓）

用法：python show_map.py [第几张，默认最新]
真判据（从存档字段实测得出 ✓）：
  战斗格 = isFightingBlock == True ✓
  boss   = battleEvent.isBossFight == True ✓
  宝库   = goldenVault.currentLevel > 0 ✓
  商人   = shop 非空 ✓
  传承   = heritage 非空 ✓   祭坛 = relic 非空 ✓   羁绊 = saga.iDs 存在 ✓
  预言   = foretellInfo.options 非空 ✓
  标记来源 = battleEvent.rewardBundle（equipList.star>0 ⇒ 红装 ✓ cloverList ⇒ 幸运草 ✓ …）
"""
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


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
DS = os.path.join(HERE, 'runs', 'maps_dataset.jsonl')
ROWS = None


def rows():
    global ROWS
    if ROWS is None:
        ROWS = [json.loads(l) for l in open(DS, encoding='utf-8') if l.strip()]
    return ROWS


def _nonempty(v):
    return bool(v) if isinstance(v, (list, dict, str)) else bool(v)


def describe(b):
    """一个块的标签（按真判据 ✓）"""
    tags = []
    be = b.get('battleEvent') or {}
    if b.get('isFightingBlock'):
        tags.append('★战斗')
    if be.get('isBossFight'):
        tags.append('BOSS')
    if be.get('iDs'):
        tags.append('事件:' + str(be.get('iDs')))
        rb = be.get('rewardBundle') or {}
        if rb.get('equipList'):
            stars = [e.get('star', 0) for e in rb['equipList'] if isinstance(e, dict)]
            if any((s or 0) > 0 for s in stars):
                tags.append('红装')
            else:
                tags.append('装备')
        if rb.get('chestList'):
            tags.append('宝箱')
        if rb.get('cloverList'):
            tags.append('幸运草')
        if rb.get('goldList'):
            tags.append('金币')
        if rb.get('specialItemList'):
            tags.append('特产')
        if be.get('dice'):
            tags.append('骰%d' % be.get('dice'))
        rl = be.get('roleList') or []
        if rl:
            tags.append('敌:%d' % len(rl))
    gv = b.get('goldenVault') or {}
    if isinstance(gv, dict) and int(gv.get('currentLevel') or 0) > 0:
        tags.append('宝库%d' % gv.get('currentLevel'))
    if _nonempty(b.get('shop')):
        tags.append('商人')
    if _nonempty(b.get('heritage')):
        tags.append('传承')
    if _nonempty(b.get('relic')):
        tags.append('祭坛')
    sg = b.get('saga') or {}
    if isinstance(sg, dict) and sg.get('iDs'):
        tags.append('羁绊:' + str(sg.get('iDs')))
    if _nonempty(b.get('gamble')):
        tags.append('赌场')
    if _nonempty(b.get('rune')):
        tags.append('符文')
    ft = b.get('foretellInfo') or {}
    if isinstance(ft, dict) and _nonempty(ft.get('options')):
        tags.append('预言')
    return ' '.join(tags) or '-'


def main():
    rs = rows()
    good = [r for r in rs
            if sum(1 for x in (r.get('blockBoard') or [])
                   if isinstance(x, int) and x >= 0) >= 10]
    print('数据集 %d 张，有效 %d 张' % (len(rs), len(good)))
    if not good:
        print('没有有效地图 ✗')
        return
    pick = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else 0
    pick = max(0, min(pick, len(good) - 1))
    rec = good[pick]
    bb = rec.get('blockBoard') or []
    bl = rec.get('blockList') or []
    print()
    print('=' * 92)
    print('真实地图：%s   难度=%s   块=%d   格=%d'
          % (rec.get('areaName'), rec.get('difficulty'), len(bl), len(bb)))
    print('=' * 92)
    print('棋盘（每格 → 块号 ✓）')
    for r_ in range(5):
        print('   ' + ' '.join('%3d' % bb[r_ * 7 + c] for c in range(7)))
    print()
    print('每块真值：')
    print('  块  地块ID        格数  是否战斗  内容')
    for j, b in enumerate(bl):
        if not isinstance(b, dict):
            continue
        n = sum(1 for x in bb if x == j)
        print('  %-3d %-13s %-5d %-9s %s'
              % (j, b.get('iDs'), n, b.get('isFightingBlock'), describe(b)))


if __name__ == '__main__':
    main()
