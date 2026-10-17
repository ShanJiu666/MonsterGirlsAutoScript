# -*- coding: utf-8 -*-
"""verify_finish_exit.py · 防「退图阶段跑不起来」回归（2026-10-02）

事故
----
用户报 PC 端「完全不能正常运行」。实跑 `explore_loop.py --maps 1` 抓出**三个**独立根因，
它们叠在一起，症状都收敛成「退图失败 / 退出码 1」：

① `explore_loop.finish_map()` 里 `in_map(b, img, items)` 用了**不存在的局部变量 `img`**
   ⇒ `NameError` ⇒ 每次退图走到 `idle>=2` 必崩，一张图都刷不完。

② 换 720×1280 基准时，**几个 1080×1920 系的硬编码坐标漏改**：
   `UNIVERSAL_CLOSE=(541,1890)` / `BACK_BTN=(539,1212)` / 兜底 `tap_dlg(sx(539),sy(1212))`
   ⇒ `LAYOUT.sy(1890)` 在 1280 高的屏上算出 **y=1890，点在屏幕外**
   ⇒ 退图兜底空转 20 多轮直到 90 秒超时（真机 tap_trace 全是这些无效坐标）。

③ 退图确认框的判据 `cy > LAYOUT.sy(800)` 太严。真帧实测（`runs/r_040316_0.png`）：
       提示 cy=505 / 正文 cy=593 / **取消 cx=203 cy=742** / **确定 cx=516 cy=742**
   ⇒ 确定在 742 < 800 ⇒ 这条分支**一次都命不中** ⇒ 弹窗关不掉 ⇒ 卡到超时。

本脚本断言
----------
① `finish_map` 函数体里不再引用裸 `img`（没有 NameError）
② 所有关键锚点算出来的坐标**都在 720×1280 屏内**（不是屏幕外的空点）
③ 真事故帧上，退图确认框判据**能命中「确定」且不误点「取消」**
④ 源码里没有残留的 1080 系坐标（`UNIVERSAL_CLOSE = (541, 1890)` 之类）

⚠ 零设备、零体力、零副作用：不连 adb、不点任何东西。
"""
from __future__ import annotations

import io
import os
import re
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
# ⚠ 业务模块已移进 `core/`（2026-10-17 目录整理）⇒ 也要能 import 到
CORE = _os.path.join(ROOT, "core")          # _MGAS_CORE_ADDED
if CORE not in _sys.path:
    _sys.path.insert(0, CORE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）


os.chdir(ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  [%s] %s%s' % ('ok  ' if cond else 'FAIL', name,
                           ('  ' + detail) if detail else ''))


# ⚠ 真事故帧：退图确认框那一帧（2026-10-02 04:03 抓的，进图首帧）。
#   放在 **`_verify/`** 而不是 `runs/`：`runs/` 在 .gitignore 里，
#   帧不入库 ⇒ 别人 clone 下来这条断言就会假红（"帧没了"）。
#   `_verify/` 是本仓**专门存取证帧**的目录（`verify_region_pad.py` 那些帧也在那）。
FRAME = os.path.join(HERE, '_verify', 'finish_confirm_dialog_20261002.png')


def _finish_map_body(src):
    """截出 finish_map 的函数体（到下一个顶层 def 为止）"""
    if 'def finish_map' not in src:
        return ''
    i = src.index('def finish_map')
    rest = src[i + 1:]
    m = re.search(r'\n(?=def |class )', rest)
    return rest[:m.start()] if m else rest


def main():
    print('=' * 78)
    print('防回归：退图阶段不许崩 / 不许点屏幕外 / 确认框必须点得掉  '
          '零设备、零体力')
    print('=' * 78)

    # ── ① finish_map 里不许有裸 img ──────────────────────────────
    print()
    print('【1】finish_map 里不得引用不存在的局部变量 img（NameError ⇒ 必崩）')
    try:
        src = io.open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    except OSError as e:                                # noqa: BLE001
        check('读得到 explore_loop.py', False, repr(e))
        return 1
    body = _finish_map_body(src)
    check('① 取得到 finish_map 函数体', bool(body))
    bare = [m.group(0) for m in re.finditer(r'in_map\(b,\s*img\b', body)]
    check('② finish_map 里没有 in_map(b, img, …) 这种裸 img',
          not bare, '' if not bare else '  发现 %d 处' % len(bare))
    check('③ 退图判据走 in_map(b, b.img(), items)',
          'in_map(b, b.img()' in body or 'in_map(b, img, items)' not in body)

    # ③-a 确认框判据用的阈值必须**真的**能覆盖真帧里「确定」的位置。
    #   ⚠ 教训：这条不能把阈值写死在本门禁里（那样改代码它就跟着变、永远绿）——
    #   必须从**源码里抠出真实阈值**再拿去套真帧（见下面【3】）。
    _m = re.search(r"in\s*\(\s*'确定'\s*,\s*'确认'\s*,\s*'是'\s*\)"
                   r"\s+and\s+it\['cy'\]\s*>\s*LAYOUT\.sy\((\d+)\)", body)
    confirm_thr = int(_m.group(1)) if _m else None
    check('④ 退图确认框判据能从源码里抠出阈值', confirm_thr is not None,
          '' if confirm_thr is not None else '  ⛔ 抠不出 ⇒ 判据被改形了就看不见')
    print('      源码里的阈值: sy(%s)' % confirm_thr)

    # ── ② 关键锚点必须在屏内 ───────────────────────────────────
    print()
    print('【2】关键锚点算出来必须落在 720×1280 屏内（不能是屏幕外的空点）')
    try:
        import layout
        L = layout.for_screen(720, 1280)
    except Exception as e:                               # noqa: BLE001
        check('能 import layout', False, repr(e))
        L = None
    if L is not None:
        import explore_loop as EL
        pts = {
            'UNIVERSAL_CLOSE': EL.UNIVERSAL_CLOSE,
            'BACK_BTN': EL.BACK_BTN,
        }
        for name, (rx, ry) in pts.items():
            dx, dy = L.sx(int(rx)), L.sy(int(ry))
            on = 0 <= dx < 720 and 0 <= dy < 1280
            check('① %-16s 参考(%s,%s) → 设备(%d,%d)'
                  % (name, rx, ry, dx, dy), on,
                  '' if on else '  ⛔ 越界 ⇒ 点在屏幕外，永远点不到')

        # 万能位应该落在底部导航中间那格（参考系 y≈1219，不是 1890）
        uy = L.sy(int(EL.UNIVERSAL_CLOSE[1]))
        check('② 万能位 y 落在 1150~1280（底部导航条带内）',
              1150 <= uy < 1280, '  y=%d' % uy)

    # ── ③ 真帧上确认框必须点得掉 ───────────────────────────────
    print()
    print('【3】真事故帧上，退图确认框判据必须命中「确定」（而不是「取消」）')
    if not os.path.exists(FRAME):
        check('① 事故帧还在（%s）' % os.path.basename(FRAME), False,
              '  帧丢了 ⇒ 这条断言没法验证，请把该帧一并入库')
    else:
        try:
            import cv2
            import numpy as np
            import mapbot
            import layout
            img = cv2.imdecode(np.fromfile(FRAME, np.uint8), cv2.IMREAD_COLOR)
            L = layout.for_screen(img.shape[1], img.shape[0])
            b = mapbot.Bot.__new__(mapbot.Bot)
            b.runs = os.path.join(HERE, 'runs')
            b.dev, b.tag, b.log_prefix = 'verify', None, 'vfe'
            b._img_arr, b._img_path, b._seq = img, FRAME, 0
            b.t = {'snap': 0., 'ocr': 0., 'wait': 0., 'wait_n': 0,
                   'tap': 0, 'ocr_n': 0}
            b.runs = os.path.dirname(FRAME)
            items = b.ocr(tag='vfe')
        except Exception as e:                           # noqa: BLE001
            check('① 能对事故帧跑 OCR', False, repr(e))
            items = []
        if items:
            # ⚠ 用**源码里抠出来的真实阈值**，不是本文件写死的数字 ——
            #   否则有人把判据改回 sy(800)，门禁会跟着一起绿，等于没测。
            thr = confirm_thr if confirm_thr is not None else 600
            L_ref = layout.for_screen(720, 1280)
            thr_px = L_ref.sy(thr)
            print('      用源码阈值 sy(%s)=%d 套这张帧' % (thr, thr_px))
            oks = [it for it in items
                   if it['text'].strip() in ('确定', '确认', '是')
                   and it['cy'] > thr_px]
            canc = [it for it in items if it['text'].strip() == '取消']
            best = max(oks, key=lambda z: z['cx']) if oks else None
            check('① 源码阈值下能认出「确定/确认」', best is not None,
                  '' if best else '  ⛔ 认不到 ⇒ 弹窗关不掉 ⇒ 退图必超时')
            if best:
                print('      命中 %s @ (%d,%d)' % (best['text'], best['cx'], best['cy']))
                check('② 点的是右边那个（确定），不是左边「取消」',
                      canc and best['cx'] > max(x['cx'] for x in canc),
                      '' if canc else '  （帧里没读到「取消」，跳过对照）')
                check('③ 命中坐标在 720×1280 屏内',
                      0 <= best['cx'] < 720 and 0 <= best['cy'] < 1280,
                      '  (%d,%d)' % (best['cx'], best['cy']))
            # 旧阈值的对照：证明 sy(800) 当时确实漏掉了它
            olds = [it for it in items
                    if it['text'].strip() in ('确定', '确认', '是')
                    and it['cy'] > L_ref.sy(800)]
            check('④ 旧阈值 sy(800) 会漏掉它（这就是当初必超时的原因）',
                  not olds,
                  '' if not olds else '  注意：旧阈值在这帧能命中，可能是别的帧不能')

    # ── ④ 源码不许有残留的 1080 系坐标 ──────────────────────────
    print()
    print('【4】源码里不许残留 1080×1920 系的坐标常量')
    for pat, why in ((r'UNIVERSAL_CLOSE\s*=\s*\(\s*541\s*,\s*1890\s*\)',
                      '万能位'),
                     (r'BACK_BTN\s*=\s*\(\s*539\s*,\s*1212\s*\)',
                      '面板返回'),
                     (r'LAYOUT\.sy\(1(?:8\d\d|9\d\d)\)',
                      'sy() 参数超出 1280 屏高')):
        m = re.search(pat, src)
        check('① 不残留 %s（%s）' % (why, pat), m is None,
              '' if m is None else '  ⛔ 命中：%s' % m.group(0))

    print()
    print('=' * 78)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
    for x in BAD:
        print('   ✗ ' + x)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
