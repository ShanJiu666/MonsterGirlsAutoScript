# -*- coding: utf-8 -*-
"""verify_merchant_no_retap.py · 回归：「旅行商人买完后还是会点开」

## 用户反馈（第 3~4 次，2026-10-28）
    「怎么旅行商人买完后还是会点开？我记得这个问题我反馈了三四次了」

## 真机铁证（runs/loop/loop_log.json，#505 -> #512~513）
    #505 {"bought_rec":[360,1004],"cell":"4,4"}            <- 17:24 买完 (4,4)
    #512 {"collect":"fixed_close","at":[360,1004]}         <- **又点同一格**
    #513 {"collect":"tapped","at":[360,1004],"opened":true} <- 面板被重新打开

## 根因（为什么前几次都没根治）
    买完的"已买"只记进 bought_done / merchant_done，
    但**有三条独立的点击路径都不看这个账本**：
      ① 点序准入 `cands = [... and (x in marked_px or x in buy_px or cold<2)]`
         buy_px 含 buy_seen/buy_sticky 跨轮记忆 => 商人格永远受"永不拉黑"保护
         => `cold>=2 => done` 被挡住 => 没认出面板那轮它既不进 done 又留在点序
      ② 点击循环 `panel_seen` 那条有 done.add，但**没认出面板**时没有
      ③ `final_collect` 取 `clicks[-1]`（最后点击的格）去补点 ——
         而商人买完那一下正是最后一次点击 => **补点又点它一次** <- 本次真机中的就是这条

## 修法（两处）
    ① 点击循环：买完（act==handled 且账本里有该格）=> done.add + 从 buy_seen/buy_sticky 摘掉
    ② final_collect：补点前查账本，那格已买过 => 跳过（记 bought_skip 日志，不静默）

用法：python tests\verify_merchant_no_retap.py
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
    import inspect
    import explore_loop as EL

    print("=" * 78)
    print("旅行商人买完后还是会点开（2026-10-28 第 3~4 次反馈）")
    print("=" * 78)

    src = open(os.path.join(CORE, "explore_loop.py"), encoding="utf-8").read()
    _tree = ast.parse(src)

    print()
    print("【1】⭐ final_collect：补点前必须查「已买」账本（本次真机中的就是这条）")
    _fc = inspect.getsource(EL.final_collect)
    ck("final_collect 读 bought_done", "bought_done" in _fc)
    ck("final_collect 读 merchant_done", "merchant_done" in _fc)
    ck(
        "⭐ 命中就跳过（bought_skip）", "bought_skip" in _fc)
    ck("⛔ 不许静默跳过（必须有日志）", "log.append" in _fc and "bought_skip" in _fc)

    print()
    print("【2】⭐ 点击循环：买完立刻 done.add + 摘掉永不拉黑记忆")
    ck("有 bought_done_now 日志", "bought_done_now" in src)
    ck("会 done.add 那一格", "done.add((cx, cy))" in src)
    ck("会从 buy_seen 摘掉", "st.get('buy_seen', {}).pop" in src)
    ck("会从 buy_sticky 摘掉", "st.get('buy_sticky', {}).pop" in src)
    ck("只对 act==handled 生效（不误伤其它面板）",
       "act == 'handled'" in src)

    print()
    print("【3】⭐⭐ 执行级：给定账本，补点必须跳过那一格")
    # 造一个最小 st：pos 那格在 bought_done 里
    # 给真帧：否则关掉守卫时会一路崩到下游，牙齿测试报出来的是 TypeError 而不是「没跳过」
    _img1 = None
    try:
        import cv2 as _cv2
        import numpy as _np
        _fp1 = os.path.join(ROOT, "dist", "MGAS-v1.0-portable", "runs", "r_195513_0.png")
        if os.path.exists(_fp1):
            _img1 = _cv2.imdecode(_np.fromfile(_fp1, dtype=_np.uint8), _cv2.IMREAD_COLOR)
    except Exception:       # noqa: BLE001
        _img1 = None
    st = {"clicked": [(360, 1004)], "bought_done": {(360, 1004)},
          "st": {}, "obs": {}, "slots_free": 0}
    _taps = []

    class _B(object):
        def snap(self, *a, **k):
            pass

        def img(self):
            return _img1

        def tap(self, x, y, wait=0):
            _taps.append((x, y))

        def ocr(self, *a, **k):
            return []

        @property
        def fast_ok(self):
            return True

        def wait_change(self, *a, **k):
            pass

    _log = []
    try:
        EL.final_collect(_B(), _log, st)
        _hit = [e for e in _log if isinstance(e, dict) and e.get("collect") == "bought_skip"]
        ck("⭐⭐ 账本里有 (360,1004) => 补点被跳过", bool(_hit), repr(_hit[:1])[:120])
        ck("而且**一次都没点**", not _taps, repr(_taps))
    except Exception as _e:      # noqa: BLE001
        ck("执行级可运行", False, repr(_e))

    print()
    print("【4】⚠⚠ 对照项：账本里**没有**那格 => 仍要照常补点（不是一刀切）")
    # ⚠ 夹具必须给**真帧**：final_collect 后面要 img/ocr 判面板；
    #   给 None 会在下游崩 ⇒ 那是**夹具的错**，不是被测代码的错（本轮真踩）
    _img2 = None
    for _c in (os.path.join(ROOT, "dist", "MGAS-v1.0-portable", "runs", "r_195513_0.png"),):
        if os.path.exists(_c):
            try:
                import cv2
                import numpy as np
                _img2 = cv2.imdecode(np.fromfile(_c, dtype=np.uint8), cv2.IMREAD_COLOR)
            except Exception:       # noqa: BLE001
                _img2 = None
            break
    if _img2 is None:
        ck("对照项需要真帧夹具", False, "r_195513_0.png 缺失")
    else:
        st2 = {"clicked": [(72, 908)], "bought_done": set(),
               "st": {}, "obs": {}, "slots_free": 0}
        _taps2 = []

        class _B3(_B):
            def img(self):
                return _img2

            def tap(self, x, y, wait=0):
                _taps2.append((x, y))

        _log2 = []
        try:
            EL.final_collect(_B3(), _log2, st2)
            _skip2 = [e for e in _log2
                      if isinstance(e, dict) and e.get("collect") == "bought_skip"]
            ck("账本为空 => 不该记 bought_skip", not _skip2, repr(_skip2[:1]))
        except Exception as _e2:     # noqa: BLE001
            ck("对照项可运行", False, repr(_e2))

    print("=" * 78)
    if FAILS:
        print("FAIL %d 项未通过：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过：买完的格不再被补点；账本为空时行为不变")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
