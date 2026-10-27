# -*- coding: utf-8 -*-
"""verify_need_names.py · 回归：只判亮度时别做「15 个 code 全量消歧」

## 用户报告（2026-10-27）
    「图名「（图名未读到）」有歧义 [...15 个...] => 实测选 S00003」
    —— 这条日志还在刷

## 根因（AST 扫出来的两个调用点）
    `:4383`  board_hidden(cells_of(_im0))        <- 没传 mapname
    `:7605`  _c2 = cells_of(img2)               <- 没传 mapname
    两处都**只判亮度/格子数**（board_hidden 只读 gray/light/st.ratio）
    => 不需要地块名，却触发了 15 个 code 的全量消歧
    => 打那句误导日志 + 白花 4~10 秒

## ⛔ 第一版改错的地方（血证）
    让 need_names=False 时取 `_cands[0]` => 实测（r_195513_0.png，清缓存）：
      S00001 => light=23 gray=12
      S00003 => light=5  gray=23   <- 才是真的
    用错 code 时 ratio 分母变了 => light/gray 会反过来
    => board_hidden / looks_in 给出**相反**答案，比慢更糟

## 正确修法
    need_names=False 时**优先复用当前图已锁定的真 code**：
      `_LAST_MAPNAME["name"]`（one_round 锁图名时写的）
      -> `_CODE_DECIDED[图名]` 查 => 命中就是真 code
    只有真拿不到才退回 _cands[0]，并打印告警（不静默）

用法：python tests\verify_need_names.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
CORE = os.path.join(ROOT, "core")
for _p in (CORE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    os.chdir(ROOT)
except OSError:
    pass
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILS = []


def ck(name, cond, detail=""):
    _d = ("" if not detail else (detail if isinstance(detail, str) else str(detail)))
    print("  %s %s%s" % ("[ok]  " if cond else "[FAIL]", name, ("  " + _d) if _d else ""))
    if not cond:
        FAILS.append(name)


def main():
    import ast
    import time

    print("=" * 78)
    print("只判亮度时别做全量消歧（2026-10-27）")
    print("=" * 78)

    src = open(os.path.join(CORE, "explore_loop.py"), encoding="utf-8").read()
    _tree = ast.parse(src)

    print()
    print("【1】结构级：两个只判亮度的调用点必须传 need_names=False")
    _sites = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        _fn = _n.func
        _nm = getattr(_fn, "id", None) or getattr(_fn, "attr", None)
        if _nm not in ("cells_of", "_cells_cached"):
            continue
        _kws = {k.arg for k in _n.keywords}
        _has_mn = "mapname" in _kws
        _nn = "need_names" in _kws
        if not _has_mn:
            _sites.append((_n.lineno, _nn))
    ck("存在「没传 mapname」的 cells_of 调用", bool(_sites), repr(_sites))
    ck("⭐ 这些调用点**全部**传了 need_names=False",
       all(nn for _, nn in _sites), repr([x for x in _sites if not x[1]]))

    print()
    print("【2】⛔ 不许简单取 _cands[0] 当 code（实测会反过来）")
    ck("代码里优先查 _LAST_MAPNAME 锁定的真 code",
       "_LAST_MAPNAME.get(" in src and "_CODE_DECIDED.get(_known_mn)" in src)
    ck("⛔ 拿不到时必须打印告警（不许静默退回）",
       "need_names=False 但拿不到当前图的真 code" in src)

    print()
    print("【3】⭐⭐ 执行级：need_names=False 的结果必须与真 code 一致")
    try:
        import cv2
        import numpy as np
        import explore_loop as EL
        _fp = os.path.join(ROOT, "dist", "MGAS-v1.0-portable", "runs", "r_195513_0.png")
        if not os.path.exists(_fp):
            ck("夹具 r_195513_0.png 存在", False, "缺失")
        else:
            _im = cv2.imdecode(np.fromfile(_fp, dtype=np.uint8), cv2.IMREAD_COLOR)
            EL._CODE_DECIDED.clear()
            EL._LAST_MAPNAME["name"] = "夏日海滩"
            _ref = EL.cells_of(_im, mapname="夏日海滩")
            _t0 = time.time()
            _fast = EL.cells_of(_im, need_names=False)
            _dt = time.time() - _t0
            ck("light 数量一致",
               len(_fast.get("light") or []) == len(_ref.get("light") or []),
               "%d vs %d" % (len(_fast.get("light") or []), len(_ref.get("light") or [])))
            ck("gray 数量一致",
               len(_fast.get("gray") or []) == len(_ref.get("gray") or []),
               "%d vs %d" % (len(_fast.get("gray") or []), len(_ref.get("gray") or [])))
            ck("board_hidden 一致",
               EL.board_hidden(_fast) == EL.board_hidden(_ref))
            ck("⭐ 而且明显更快（< 3 秒，老路径 ~7 秒）", _dt < 3.0, "%.2f 秒" % _dt)
    except Exception as _e:      # noqa: BLE001
        ck("执行级可运行", False, repr(_e))

    print("=" * 78)
    if FAILS:
        print("FAIL %d 项未通过：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过：只判亮度的调用点跳过全量消歧，且结果与真 code 逐项一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
