# -*- coding: utf-8 -*-
"""verify_mapname_and_merchant.py · 回归：「一直是图名未读到」+「商人买完还点」

## 用户报告（2026-10-26）
    「为什么**一直是图名未读到**？遇到很多次了。
      而且这张图明明买完了旅行商人，还会再次点开」

## 真机铁证（runs/gui_console_20261026.log + loop_log.json，设备 16384）
    19:55:19  · 图名「（图名未读到）」有歧义 [15 个 code] ⇒ 实测选 S00003
    同一次运行 loop_log #7：
      {"mapname": "夏日海滩", "round": 0, "note": "进图首帧锁定图名 ✓"}
    ⇒ **图名其实读到了**！那句是**另一条路径**打出来的（误导）
    OCR 实测（r_195513_0.png）：cx=360 cy=122 conf=0.91 "夏日海滩[100]" ✓

## 病 ①：轮首用「空图名」做全量消歧（≈7.5 秒/图 + 误导日志）
    one_round 轮首顺序：
      ① _c0 = _cells_cached(b, img, mapname=st.get("mapname") or "")
         ⇒ 首轮还没 OCR ⇒ 传 "" ⇒ board_state 走「全部 code 当候选」
         ⇒ 15 个 code 各建一次盘 ⇒ 打出「（图名未读到）」
      ② items = b.ocr(tag="round")  ← 这时才真 OCR
      ③ st["mapname"] = _mn_now（#7 ✓ 锁上了）
    ⇒ 修（**改调用点，不改 board_state 语义**）：首轮**跳过**那次分类，
      OCR 之后用真图名再分类（`c = _cells_cached(...)` 那行已经在做 ✓）

## 病 ②：merchant_done 的写入条件恒不成立 ⇒ 只写不读
    写入条件 `_p in done and _p not in _just_bought`
    ⇒ **买完那一轮 `_just_bought` 正好有它** ⇒ 永远写不进去
    ⇒ 真机实测 `grep -c skip_bought` = 0（一次都没触发）
    ⇒ 修：在**买完的现场**（popups 里）就记

用法：
    python tests\verify_mapname_and_merchant.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
CORE = os.path.join(ROOT, 'core')
for _p in (CORE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    os.chdir(ROOT)
except OSError:
    pass
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=""):
    _d = ("" if not detail else (detail if isinstance(detail, str) else str(detail)))
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name, ('  ' + _d) if _d else ''))
    if not cond:
        FAILS.append(name)


def main():
    import inspect
    import explore_loop as EL

    print('=' * 78)
    print('图名未读到 + 商人买完还点（2026-10-26 用户报）')
    print('=' * 78)

    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()

    print()
    print('【1】轮首跳过那次「空图名全量消歧」（省约 7.5s/图 + 不打误导日志）')
    # ⚠ 修法是「**改调用点**」，**不是**改 `board_state` 的语义 ——
    #   `in_map()` 也调 `cells_of(img, mapname=map_name(items))`，
    #   那儿**空图名时也要分类结果**（靠「格子兜底」判在不在图里）
    #   ⇒ 一旦让空图名返回空 ⇒ `n=0 < 8` ⇒ 把「在图里」判成「不在图里」⇒ **回归**
    #   （我第一版就改错了，被 verify_newequip / verify_collect_fast 当场抓出 ✓）
    ck('轮首有 _mn_have 分支', "_mn_have = st.get('mapname')" in src)
    ck('首轮跳过时不做 cells_cached（不花 15 个 code 消歧）',
       'if _mn_have:' in src
       and '_c0 = _cells_cached(b, img, mapname=_mn_have)' in src)
    ck('非首轮照旧用真图名分类', '_panel0 = bool(board_hidden(_c0))' in src)
    ck('board_state 的语义没被改（in_map 依赖空图名也能分类）',
       'if mapname is None:' not in inspect.getsource(EL.board_state))
    ck('board_state 仍保留全量消歧（兜底不能丢）',
       '_disambiguate_map' in inspect.getsource(EL.board_state))

    print()
    print('【2】AST 守门：轮首不许再出现「两段式 or 空串」')
    import ast
    _tree = ast.parse(src)
    _old_hits = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        for _kw in _n.keywords:
            if _kw.arg != 'mapname':
                continue
            _v = _kw.value
            if not (isinstance(_v, ast.BoolOp) and isinstance(_v.op, ast.Or)
                    and _v.values and isinstance(_v.values[-1], ast.Constant)
                    and _v.values[-1].value == ''):
                continue
            _seg = ast.get_source_segment(src, _v) or ""
            # ⚠⚠ 判据必须**精确**：只抓「`st.get('mapname')` or 空串」这一种，
            #   **不能**抓所有「or 空串」——
            #   否则会误伤 `mapname=(mapname or '')`（**语义不同**！
            #   那是「用**传进来的**图名，取不到就空」⇒ 2026-10-26 退图修复用的就是它）
            #   ⇒ 我第一版把判据写太宽 ⇒ AY 组把 BA 组的正确写法判成红 ✗（本轮真踩）
            if 'st.get(' not in _seg:
                continue
            if 'map_name(' not in _seg:
                _old_hits.append(getattr(_n, "lineno", -1))
    ck('旧写法 mapname=st.get(mapname) or 空串 已不存在（AST 判定，**只抓 st.get 式**）',
       not _old_hits, "行号 %s" % _old_hits[:3])
    # ⚠⚠ **牙齿实测**：光靠上面那条抓不到「变量赋值式」的回归
    #   （`_mn_have = st.get('mapname') or ''` 不是 keyword 参数 ⇒ AST 那条漏掉 ✗）
    #   ⇒ 必须**再钉一条**：`_mn_have` 的赋值**右边不许是 or 空串** ✓
    _assign_hits = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Assign):
            continue
        for _tg in _n.targets:
            if not (isinstance(_tg, ast.Name) and _tg.id == '_mn_have'):
                continue
            _v = _n.value
            if (isinstance(_v, ast.BoolOp) and isinstance(_v.op, ast.Or)
                    and _v.values and isinstance(_v.values[-1], ast.Constant)
                    and _v.values[-1].value == ''):
                _assign_hits.append(getattr(_n, 'lineno', -1))
    ck('⛔ `_mn_have` 赋值不许是 `or 空串`（牙齿实测：AST 那条抓不到这种 ✗）',
       not _assign_hits, "行号 %s" % _assign_hits[:3])

    print()
    print('【3】merchant_done 必须在买完的现场就写入')
    ck('买完现场有写入点',
       "_md = _st.setdefault('merchant_done', set())" in src)
    ck('写入的是格号 cell_of(*tapped)',
       '_md.add(tuple(cell_of(*tapped)))' in src)
    ck('写入点至少两处（现场 + 摘除那段）',
       src.count("setdefault('merchant_done'") >= 2)

    print()
    print('【4】过滤侧与写入侧量纲一致（否则过滤不生效）')
    ck('过滤用 cell_of(*p) not in _mdone',
       '_kept_buy = [p for p in buy if cell_of(*p) not in _mdone]' in src)
    ck('不许出现像素比像素', 'tuple(p) not in _mdone' not in src)

    print()
    print('【5】执行级：真机坐标 (264,1004) 买完后必须被滤掉')
    _px = (264, 1004)
    _cell = EL.cell_of(*_px)
    ck('真机 #39：px[264,1004] -> 格号 4,3', _cell == (4, 3), repr(_cell))
    _md = {tuple(_cell)}
    _buy = [(264, 1004), (72, 908), (552, 716)]
    _kept = [p for p in _buy if EL.cell_of(*p) not in _md]
    ck('商人格被滤掉', (264, 1004) not in _kept, repr(_kept))
    ck('其它两格保留', len(_kept) == 2, repr(_kept))

    print()
    print('【6】对照项：没买过的商人格必须保留（不是恒滤）')
    _md2 = {(9, 9)}
    _kept2 = [p for p in _buy if EL.cell_of(*p) not in _md2]
    ck('买了别处 => 这三格全保留', len(_kept2) == 3, repr(_kept2))
    ck('过滤是按格判的，不是恒真/恒假', len(_kept) != len(_kept2))

    print('=' * 78)
    if FAILS:
        print('FAIL %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('全部通过：轮首不再用空图名全量消歧（省约 7.5s/图 + 不打误导日志）；'
          'merchant_done 在买完现场就写入 => 买过的商人格不再进目标')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
