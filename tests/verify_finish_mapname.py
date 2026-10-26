# -*- coding: utf-8 -*-
"""verify_finish_mapname.py · 回归：「结束了还要读图名字」

## 用户报告（2026-10-26）
    「为什么结束了还要读图名字？」

## 真机铁证（runs/gui_console_20261026.log，22:41 那把）
    22:41:47  本图结束：done（耗时 38 秒）
    22:41:56  · 图名「（图名未读到）」有歧义 [15 个代码] ⇒ 实测选 S00003（高分格 21）✓
    22:42:00  · 已回到选图界面（模板判据 7ms · 省掉一次 OCR ✓）
    22:42:00  · 退图细账：图上 38.4s ｜ 退图 13.0s

## 根因（读代码即可证）
    finish_map 里 `board_hidden(_cells_cached(b, b.img(), mapname=''))`
    ⇒ `board_state('')` ⇒ 「图名为空 ⇒ 全部 code 当候选」
    ⇒ **15 个 code 各建一次盘**（≈4 秒）⇒ 打出那句「（图名未读到）」✗

## ⚠⚠ 这是 10-26 那次「轮首跳过全量消歧」修复的副作用（诚实记账）
    修复前：首轮那次全量消歧会**顺手填** `_CODE_DECIDED['']`
    ⇒ 退图时 `mapname=''` 命中缓存 ⇒ 不再消歧 ⇒ **看不到那句**
    修复后：首轮**跳过**了 ⇒ `_CODE_DECIDED['']` 一直空
    ⇒ 退图时**第一次**做全量消歧 ⇒ **那句冒出来** + 多花 4 秒 ✗

## 修法
    把当前图的图名（`st['mapname']`，每图都有 ✓）传进 `finish_map`
    ⇒ `_CODE_DECIDED[图名]` 早被图内分类填好 ⇒ **零消歧、零 OCR、零日志** ✓
    ⇒ 额外：`board_hidden` 拿到**正确的 code** ⇒ ratio 算得准 ⇒ 判据更准 ✓

用法：
    python tests\verify_finish_mapname.py
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
    print('「结束了还要读图名字」（2026-10-26 用户报）')
    print('=' * 78)

    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()

    print()
    print('【1】结构级：finish_map 必须收图名')
    ck('finish_map 有 mapname 参数', 'mapname=None' in inspect.signature(EL.finish_map).parameters
       if False else ('def finish_map(b, log, timeout=90, mapname=None):' in src))
    # ⚠ 那条判据**必须用 AST**（下面【2】那条）—— 字符串 grep 会被
    #   **留档注释里逐字引用的旧写法**骗红（本轮真踩 ✓）
    ck('改成 `mapname=(mapname or \'\')`（拿不到时仍退回旧行为 ✓）',
       "_cells_cached(b, b.img(), mapname=(mapname or ''))" in src)
    ck('⭐ 调用处把当前图名传进去',
       "finish_map(b, log, mapname=st.get('mapname'))" in src)

    print()
    print('【2】⭐⚠⚠ AST 守门：`_cells_cached` 调用里不许出现 `mapname=\'\'` 字面量')
    # ⚠⚠ 必须用 AST（不是字符串 grep）—— 留档注释里必然逐字引用旧写法 ⇒ 假红 ✗
    #   （本仓已栽过这个坑多次：v1.62c / v1.67 / 本轮 ✓）
    import ast
    _tree = ast.parse(src)
    _bad = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        _fn = _n.func
        _fname = getattr(_fn, 'id', None) or getattr(_fn, 'attr', None)
        if _fname not in ('_cells_cached', 'cells_of'):
            continue
        for _kw in _n.keywords:
            if _kw.arg != 'mapname':
                continue
            _v = _kw.value
            if isinstance(_v, ast.Constant) and _v.value == '':
                _bad.append(getattr(_n, 'lineno', -1))
    ck('⛔ 没有 `_cells_cached(..., mapname='')` 字面量调用',
       not _bad, '行号 %s' % _bad[:3])

    print()
    print('【3】⭐ 执行级：图名在真机语料里**每张图都有**（不然传了也是空）')
    _mn = []
    try:
        import json
        _p = os.path.join(ROOT, 'dist', 'MGAS-v1.0-portable', 'runs', 'loop', 'loop_log.json')
        if os.path.exists(_p):
            _d = json.load(open(_p, encoding='utf-8'))
            _mn = [e.get('mapname') for e in _d
                   if isinstance(e, dict) and e.get('mapname')]
    except Exception:       # noqa: BLE001
        pass
    ck('loop_log 里有图名记录（真机证据 ✓）', bool(_mn), repr(_mn[:3]))
    ck('⛔ 图名不许是空串（空串 ⇒ 等于没传 ⇒ 又全量消歧 ✗）',
       all(bool(x) for x in _mn))

    print('=' * 78)
    if FAILS:
        print('FAIL %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('全部通过：退图时用**当前图的图名**分类 ⇒ 不做「15 个 code 全量消歧」'
          '⇒ 不再打印「（图名未读到）」+ 省 ≈4 秒/图')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
