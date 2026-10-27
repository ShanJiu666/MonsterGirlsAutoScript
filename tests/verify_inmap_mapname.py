# -*- coding: utf-8 -*-
"""verify_inmap_mapname.py · 回归：`in_map` 的图名判据窗口（曾经永远不命中）

## 病（2026-10-27 实测铁证）
    原来窗口写的是 `sy(150) < cy < sy(215)`，而真机图名实测 **cy≈122**：
      runs/r_195513_0.png      -> cx=360.0 cy=122.2 conf=0.91 "夏日海滩[100]"
      runs/acc3/r_123219_0.png -> 同样 cy=122
    => 122 < 150 => **这条判据从诞生起就没生效过**

## 影响
    图内识别只剩「结束冒险」一条（exb(items, L["end"])），
    而那是结算/浮层才有的按钮 => **进图首帧没有它** => in_map 判否
    => enter_map 白等 9 轮 => 真机 acc3 12:43 那把点了 2 次 (603,1079)
       还是 enter: timeout => 整局以「进图失败」收工（体力 1997 明明够）

## 修法
    窗口改成 `sy(100) < cy < sy(215)`（实测 122 落在中间），
    判据本身（^.+\[\d+\]\s*$）一个字不改；上界 215 保留

## ⚠⚠ 本门禁必须**从源码 AST 读窗口值**，不能硬编码 ——
    第一版硬编码 `SY(100)` => 把源码改回 150 也照样全绿 => **假绿** ✗
    （牙齿实测当场抓出，已改）

用法：python tests\verify_inmap_mapname.py
"""
import os
import re
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


def _window_from_source():
    """从 `in_map` 源码里把图名判据那一行的**两个窗口常数**读出来（AST）

    形如 `if LAYOUT.sy(100) < it["cy"] < LAYOUT.sy(215) and re.match(...)`
    -> (100, 215)；找不到 -> (None, None)
    """
    import ast
    src = open(os.path.join(CORE, "explore_loop.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "in_map"]
    if not fn:
        return (None, None)
    # ⚠⚠ 不能見到 sy( 和 cy 就當命中 —— in_map 裡還有 HUD 那一條
    #   （sy(900) < cy < sy(1000)）=> 會抓錯（第一版就抓成了 900~1000）
    #   => 判據必須**同時**含 re.match（圖名那條的獨有特征）
    for n in ast.walk(fn[0]):
        if not isinstance(n, ast.If):
            continue
        seg = ast.get_source_segment(src, n) or ""
        if "sy(" not in seg or "cy" not in seg or "re.match" not in seg:
            continue
        nums = [int(x.value) for x in ast.walk(n.test)
                if isinstance(x, ast.Constant) and isinstance(x.value, int)]
        if len(nums) >= 2:
            return (min(nums[:2]), max(nums[:2]))
    return (None, None)


def main():
    import explore_loop as EL

    print("=" * 78)
    print("in_map 的图名判据窗口（曾经永远不命中）")
    print("=" * 78)

    SY = EL.LAYOUT.sy
    lo, hi = _window_from_source()

    print()
    print("【1】⭐ 从源码 AST 读出的窗口：%s ~ %s" % (lo, hi))
    ck("能在源码里找到图名判据的窗口常数", lo is not None and hi is not None)
    if lo is None:
        print("FAIL 找不到窗口常数 => 后面无法判定")
        return 1
    ck("窗口下界能装下实测 cy=122", lo <= 122, "lo=%s" % lo)
    ck("窗口上界 >= 122", hi >= 122, "hi=%s" % hi)
    ck("上界仍 <= 215（不放大到战斗横幅区）", hi <= 215, "hi=%s" % hi)

    print()
    print("【2】⭐⭐ 执行级：用**源码读出的**窗口判真机样本")
    _pat = re.compile(r"^.+\[\d+\]\s*$")

    def _hit(cy, text):
        return SY(lo) < cy < SY(hi) and bool(_pat.match(str(text).strip()))

    ck("真机样本 cy=122.2 / \"夏日海滩[100]\" 必须命中",
       _hit(122.2, "夏日海滩[100]"))
    ck("对照：非图名文字（开始冒险）不命中", not _hit(122.2, "开始冒险"))
    ck("对照：位置不对（cy=400）不命中", not _hit(400.0, "夏日海滩[100]"))

    print("=" * 78)
    if FAILS:
        print("FAIL %d 项未通过：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过：图名判据窗口（源码 %s~%s）能装下实测 cy=122，且不误判" % (lo, hi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
