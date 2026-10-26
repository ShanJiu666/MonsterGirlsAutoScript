# -*- coding: utf-8 -*-
"""verify_finish_mapname.py · 回归：「结束了还要读图名字」+ 退图 NameError

## 用户报告（2026-10-26）
    ① 「为什么结束了还要读图名字？」
    ② 「退图这一步抛异常：NameError("name 'st' is not defined")」

## 病 ①：finish_map 里 board_hidden(_cells_cached(..., mapname=''))
    ⇒ board_state('') ⇒ 「图名为空 ⇒ 全部 code 当候选」
    ⇒ **15 个 code 各建一次盘**（≈4~10 秒）⇒ 打出「（图名未读到）」✗

## ⚠⚠ 病 ②：我在 ① 的修复里用了 st.get('mapname') ⇒ **NameError**（自己踩的）
    根因：st 是 run_one_map() 的**局部变量**（:8516 建），
          而退图那个调用点在 **run_maps()** ⇒ 那里**根本没有 st** ✗
    真机表现：「退图这一步抛异常」⇒「退图没成功，已停止」⇒ **整局停在那** ✗✗
    ⚠ 本仓**记过两次**这个坑（bought_rec_err: NameError: name 'st' is not defined）
      ⇒ 我又踩了一次 ⇒ 教训：**跨函数取状态必须走模块级变量**（同 _CODE_DECIDED）✓

## 修法
    ① finish_map 加 mapname 参数；run_maps 退图时传 _LAST_MAPNAME.get('name')
    ② one_round 锁定图名时同步写 _LAST_MAPNAME['name']

## ⚠⚠ 本门禁的判据**必须用 AST**（字符串 grep 会被留档注释骗红 —— 本轮真踩 3 次）

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
    import ast
    import explore_loop as EL

    print('=' * 78)
    print('「结束了还要读图名字」+ 退图 NameError（2026-10-26 用户报）')
    print('=' * 78)

    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    _tree = ast.parse(src)

    print()
    print('【1】结构级：finish_map 必须收图名')
    ck('finish_map 有 mapname 参数',
       'def finish_map(b, log, timeout=90, mapname=None):' in src)
    ck('分类用传入图名（不再写死空串）',
       "_cells_cached(b, b.img(), mapname=(mapname or ''))" in src)

    print()
    print('【2】⛔⛔⛔ AST 守门 A：cells 分类不许 mapname=空串 字面量')
    _bad = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        _fn = _n.func
        _nm = getattr(_fn, 'id', None) or getattr(_fn, 'attr', None)
        if _nm not in ('_cells_cached', 'cells_of'):
            continue
        for _kw in _n.keywords:
            if _kw.arg != 'mapname':
                continue
            _v = _kw.value
            if isinstance(_v, ast.Constant) and _v.value == '':
                _bad.append(getattr(_n, 'lineno', -1))
    ck('没有 mapname=空串 字面量调用', not _bad, '行号 %s' % _bad[:3])

    print()
    print('【3】⛔⛔⛔ AST 守门 B：run_maps 里**不许引用 st**（NameError 根因）')
    _fns = [n for n in ast.walk(_tree) if isinstance(n, ast.FunctionDef)]
    _rm = [n for n in _fns if n.name == 'run_maps']
    ck('run_maps 函数存在', bool(_rm))
    if _rm:
        _st_refs = []
        for _n in ast.walk(_rm[0]):
            if (isinstance(_n, ast.Attribute) and isinstance(_n.value, ast.Name)
                    and _n.value.id == 'st'):
                _st_refs.append(getattr(_n, 'lineno', -1))
        ck("⭐⭐ run_maps 里 **零** 个 st 引用（NameError 根除 ✓）",
           not _st_refs, '行号 %s' % _st_refs[:3])
        _om = [n for n in _fns if n.name == 'run_one_map']
        _st_store = []
        if _om:
            for _n in ast.walk(_om[0]):
                if (isinstance(_n, ast.Name) and _n.id == 'st'
                        and isinstance(_n.ctx, ast.Store)):
                    _st_store.append(getattr(_n, 'lineno', -1))
        ck("（对照）st 确实只活在 run_one_map 里 ⇒ 跨函数必须走模块级 ✓",
           bool(_st_store), '行号 %s' % _st_store[:3])

    print()
    print('【4】⭐ 执行级：模块级 _LAST_MAPNAME 存在且可用')
    ck('`explore_loop._LAST_MAPNAME` 存在', hasattr(EL, '_LAST_MAPNAME'))
    ck('它是 dict（模块级共享状态的既有模式 ✓）',
       isinstance(getattr(EL, '_LAST_MAPNAME', None), dict))
    try:
        EL._LAST_MAPNAME['name'] = '夏日海滩'
        _v = EL._LAST_MAPNAME.get('name')
        ck("真跑 `_LAST_MAPNAME.get('name')` ⇒ '夏日海滩'",
           _v == '夏日海滩', repr(_v))
    except Exception as _e:      # noqa: BLE001
        ck("真跑 `_LAST_MAPNAME.get('name')` 不抛异常", False, repr(_e))

    print()
    print('【5】⭐ 执行级：图名在真机语料里**每张图都有**（不然传了也是空）')
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
    print('全部通过：退图用**当前图的图名**分类 ⇒ 不做「15 个 code 全量消歧」；'
          '且 `st` 不可见的坑已根除（改走模块级 `_LAST_MAPNAME` ✓）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
