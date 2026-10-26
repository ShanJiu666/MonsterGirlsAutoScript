# -*- coding: utf-8 -*-
"""verify_single_cell_gap.py · 回归：「战斗地块被认成旅行商人/限时礼包」

## 用户报告（2026-10-26）
    「把战斗地块认成旅行商人，限时礼包了。。」帧 runs/r_234847_0.png

## 逐格 top5 铁证（实测）
    4,1  旅行商人  score=0.164  gap=0.037   带绿色大拇指图标的已揭示格
    5,2  限时礼包  score=0.441  gap=0.049   沙地上的宝箱堆（真身 003，0.392）
    5,3  海边小屋  score=0.330  gap=0.051   灰雾格
    => 三格 top5 全是低分互咬 => 没有一个候选「明显胜出」=> 名字是噪声

## 判据
    gap = top1 与「第一个不同 sid」的分差（同 sid 多变体不算）
    标定（30 张确认是夏日海滩的帧、1049 个有名字格）：
      用户那三格 gap 全 < 0.06；真帧 gap p05=0.056 p10=0.140 p50=0.667
    联合 score<0.45 且 gap<0.06，只对单格通道生效 => 命中 0.4%（4/1049）

## 必须限定「单格通道」
    不限通道时命中 1.8%，19 个里 9 个「巨大沙堡」+5 个「海边游客」，
    全是同分数连片格（r_125534 的 3,1/3,2/3,3 都 0.431）=> 那是真的大块地块
    （走块通道）=> 必须豁免

## 也不能只用分数门槛
    全量 1118 帧 score<0.28 要切 17.1%，但那是脏测量（4868 个「旅行商人 0.22」
    全来自用错地图模板的帧）；只看夏日海滩帧 p05=0.464 => 分数门槛几乎切不到东西，
    而用户那格 0.441 根本切不掉

用法：python tests\verify_single_cell_gap.py
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


def _frame(name):
    p = os.path.join(ROOT, "dist", "MGAS-v1.0-portable", "runs", name)
    if not os.path.exists(p):
        return None
    try:
        import cv2
        import numpy as np
        return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def main():
    import ast
    import spots as SP

    print("=" * 78)
    print("战斗地块被认成旅行商人/限时礼包（2026-10-26 用户报）")
    print("=" * 78)

    src = open(os.path.join(CORE, "spots.py"), encoding="utf-8").read()

    print()
    print("【1】结构级：判据存在且两条都齐")
    ck("有 SINGLE_NAME_GAP_MIN 常量", "SINGLE_NAME_GAP_MIN" in src)
    ck("有 SINGLE_NAME_SCORE_MAX 常量", "SINGLE_NAME_SCORE_MAX" in src)
    ck("判据里同时用 gap 与 score（缺一不可）",
       "gap < SINGLE_NAME_GAP_MIN" in src
       and "float(v) < SINGLE_NAME_SCORE_MAX" in src)
    ck("必须限定单格通道（anchor is None）—— 否则误伤真大块地块",
       "blk is None and anc is None" in src)

    print()
    print("【2】AST 守门：名字闸门附近不许改 ratio/revealed")
    _tree = ast.parse(src)
    _bad = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Assign):
            continue
        for _t in _n.targets:
            if isinstance(_t, ast.Subscript):
                _seg = ast.get_source_segment(src, _n) or ""
                if _seg.startswith("out[k]['ratio']") or _seg.startswith("out[k]['revealed']"):
                    _bad.append(getattr(_n, "lineno", -1))
    ck("没有在名字闸门里改 ratio/revealed", not _bad, "行号 %s" % _bad[:3])

    print()
    print("【3】执行级：用户报的那三格必须认不出")
    im = _frame("r_234847_0.png")
    if im is None:
        ck("夹具 r_234847_0.png 存在", False, "缺失 => 无法验证")
        st = {}
    else:
        bd = SP.Board("S00003")
        st = bd.state(im)
        for rr, cc, want in [(4, 1, "旅行商人"), (5, 2, "限时礼包"), (5, 3, "海边小屋")]:
            v = st.get((rr, cc)) or {}
            ck("%d,%d 原本会认成「%s」=> 现在必须认不出" % (rr, cc, want),
               not (v.get("name") or ""), repr(v.get("name")))
            ck("%d,%d 的 sid/ratio 保持原值（技术判定不变）" % (rr, cc),
               bool(v.get("sid")) and v.get("ratio") is not None)

    print()
    print("【4】对照项：真地块绝不许被误清（不是一刀切）")
    for rc, want in [((1, 1), "草地"), ((2, 4), "宝箱"), ((3, 4), "椰树"),
                     ((4, 3), "营地"), ((3, 7), "勇者之墓")]:
        v = st.get(rc) or {}
        ck("真地块 %s「%s」必须保留" % (rc, want),
           (v.get("name") or "") == want, repr(v.get("name")))

    print("=" * 78)
    if FAILS:
        print("FAIL %d 项未通过：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过：单格通道「没有候选明显胜出 => 认不出」，且真地块零误清")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
