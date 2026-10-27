# -*- coding: utf-8 -*-
"""verify_destiny_dialog.py · 回归：「命运预言」进图前置弹窗

## 用户报告（2026-10-27）
    「进图会弹出一个弹窗」（出现了之前没遇到的情况）

## 真机截图（现场截的，720x1280）
    标题  提示                    (360,505)
    正文  当前关卡将会触发命运预言     (361,612)
    按钮  取消 (204,742)  |  确定 (516,742)
    背后是选图界面（清凉沙滩 / 夏日海滩入侵 / 快速扫荡+进入地图）

## 病（会让整局卡死）
    1) popups() 对它返回 none（实测 act=none、taps=[]、log 空）
       => 没有任何代码会关掉它 => 弹窗一直挂着
       为什么接不住：末尾通用「确定」分支要求
         ok cy > sy(900) 且 exb(items, L[cancel]) is None
       => 本弹窗确定在 cy=742 < 900，而且有「取消」=> 双杀
    2) enter_map 却照样点「进入地图」(603,1079)
       => 点了被弹窗吞掉 => 9 轮 in_map 仍 False => enter: timeout
       => 整局「进图失败（体力不足 / 不在选图界面）」收工（体力明明够）
    3) 本仓 grep 命运预言 一条都没有 => 游戏版本升级新加的前置弹窗

## 修法
    popups() 最前面（kick 之后）加专属分支：正文含「命运预言」=> 点「确定」
    ⛔ 不能点「取消」（那是放弃进图）
    ⚠ 判据用正文独有词「命运预言」，比只看「确定」精确得多

用法：python tests\verify_destiny_dialog.py
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


def _items_from(path):
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    _o = RapidOCR()
    im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        return None, None
    sc = 0.75 * (1080.0 / im.shape[1])
    res, _ = _o(cv2.resize(im, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA))
    out = []
    for box, txt, conf in (res or []):
        cx = sum(q[0] for q in box) / 4.0 / sc
        cy = sum(q[1] for q in box) / 4.0 / sc
        out.append({"text": txt, "cx": cx, "cy": cy, "conf": conf})
    return im, out


class _SpyB(object):
    def __init__(self, im, items):
        self._img_arr = im
        self._items = items
        self.taps = []

    def img(self):
        return self._img_arr

    def snap(self, *a, **k):
        pass

    def ocr(self, *a, **k):
        return self._items

    @property
    def fast_ok(self):
        return True

    def tap(self, x, y, wait=0):
        self.taps.append((round(x), round(y)))

    def wait_change(self, *a, **k):
        pass


def main():
    import explore_loop as EL

    print("=" * 78)
    print("「命运预言」进图前置弹窗（2026-10-27 用户报）")
    print("=" * 78)

    src = open(os.path.join(CORE, "explore_loop.py"), encoding="utf-8").read()

    print()
    print("【1】结构级")
    ck("代码里有「命运预言」判据", "命运预言" in src)
    ck("判据在 popups() 里", "destiny_confirm" in src)
    ck("⛔ 点的是「确定」不是「取消」", "exb(items, L['ok'])" in src)

    print()
    print("【2】⭐⭐ 执行级：真机截图必须 handled + 点 (516,742)")
    _shot = None
    for _c in (os.path.join(_HERE, "_verify", "destiny_dialog_20261027.png"),
               os.path.join(ROOT, "_shot_now.png")):
        if os.path.exists(_c):
            _shot = _c
            break
    if not _shot:
        ck("夹具 tests/_verify/destiny_dialog_20261027.png 存在", False,
           "缺失 => 无法验证")
    else:
        _im, _it = _items_from(_shot)
        if _it is None:
            ck("夹具可解码", False)
        else:
            _b = _SpyB(_im, _it)
            _log = []
            _act = EL.popups(_b, _it, _log)
            ck("弹窗帧 => act == handled", _act == "handled", repr(_act))
            ck("点了恰好一次", len(_b.taps) == 1, repr(_b.taps))
            if _b.taps:
                _tx, _ty = _b.taps[0]
                ck("点的是「确定」那颗 (516,742) ±3px",
                   abs(_tx - 516) <= 3 and abs(_ty - 742) <= 3, repr(_b.taps[0]))
            ck("日志落 destiny_confirm",
               any(e.get("popup") == "destiny_confirm" for e in _log if isinstance(e, dict)))

    print()
    print("【3】⚠⚠ 对照项：普通地图帧**不许**被这个分支接住")
    _mf = os.path.join(ROOT, "dist", "MGAS-v1.0-portable", "runs", "r_195513_0.png")
    if not os.path.exists(_mf):
        ck("对照帧 r_195513_0.png 存在", False, "缺失")
    else:
        _im2, _it2 = _items_from(_mf)
        if _it2:
            ck("对照帧不含「命运预言」",
               not any("命运预言" in (i.get("text") or "") for i in _it2))
            _b2 = _SpyB(_im2, _it2)
            _log2 = []
            _act2 = EL.popups(_b2, _it2, _log2)
            ck("对照帧 act != handled（不许被本分支接住）",
               _act2 != "handled" or not _b2.taps, "%s %s" % (_act2, _b2.taps))

    print("=" * 78)
    if FAILS:
        print("FAIL %d 项未通过：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过：命运预言弹窗点「确定」继续进图；普通帧不误触发")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
