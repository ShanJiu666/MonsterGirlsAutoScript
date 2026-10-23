

import os
import sys

_os = os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
CORE = _os.path.join(ROOT, "core")
for _p in (CORE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    _os.chdir(ROOT)
except OSError:
    pass

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

V = _os.path.join(ROOT, '_verify')
FAILS = []


def ck(name, cond, detail=''):
    # ⚠ detail 允许传 list/元组（诊断用），这里统一转成字符串
    _d = ('' if not detail else (detail if isinstance(detail, str) else str(detail)))
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + _d) if _d else ''))
    if not cond:
        FAILS.append(name)


def _load(fn):
    import cv2
    import numpy as np
    p = _os.path.join(V, fn)
    if not _os.path.exists(p):
        return None
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def _blocks(im, use_width):
    """复算 `count_bubbles` 的判据（可开关宽度过滤）-> [(w, h, area, pure_r), ...]"""
    import cv2
    import numpy as np
    import guild_common as GC
    band = im[max(0, GC.BUBBLE_Y0 - 10):GC.BUBBLE_Y1 + 10, :]
    if band.size == 0:
        return []
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(white, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 400:
            continue
        if use_width and w < GC.BUBBLE_MIN_W:
            continue
        sub = hsv[y:y + h, x:x + w]
        pure = int(((sub[:, :, 1] < 20) & (sub[:, :, 2] > 230)).sum())
        pr = pure / float(max(1, w * h))
        if pr < 0.02:
            continue
        out.append((int(w), int(h), int(area), round(pr, 3)))
    return out
def main():
    import guild_common as GC

    print('=' * 78)
    print('4 楼被误判成"椅子层" ⇒ 炼金整段放弃（2026-10-23 用户报）')
    print('=' * 78)

    print()
    print('【1】`BUBBLE_MIN_W` 存在，且落在「4 楼假块 42」与「2 楼真气泡 84」之间')
    mw = getattr(GC, 'BUBBLE_MIN_W', None)
    ck('`guild_common.BUBBLE_MIN_W` 存在', mw is not None, '实际 %r' % (mw,))
    ck('取值在 43~83 之间（两侧都留余量）', mw is not None and 43 <= int(mw) <= 83,
       '实际 %r' % (mw,))

    print()
    print('【2】⛔ 撤回守门：`count_bubbles` 里**必须真的**拿宽度做过滤')
    src_p = _os.path.join(CORE, 'guild_common.py')
    src = open(src_p, encoding='utf-8').read()
    s = src.find('def count_bubbles(')
    e = src.find('\ndef ', s + 10)
    body = src[s:e] if s >= 0 else ''
    code = '\n'.join(l for l in body.splitlines() if not l.lstrip().startswith('#'))
    ck('找到 `count_bubbles` 定义', s >= 0)
    ck('代码行（剥掉注释后）里有 `w < BUBBLE_MIN_W`',
       'w < BUBBLE_MIN_W' in code)
    ck('⚠ 反向：**不是**恒真（`BUBBLE_MIN_W` 不是 0/负数）',
       mw is not None and int(mw) > 0, '实际 %r' % (mw,))

    print()
    print('【3】⭐⭐ 执行级：4 楼 4 帧 ⇒ `count_bubbles` 必须 **0**，`chair_row_hint` 必须 False')
    for i in (5, 6, 7, 8):
        fn = 'floor4_scroll_chk%d.png' % i
        im = _load(fn)
        if im is None:
            print('      （缺 %s ⇒ 跳过）' % fn)
            continue
        nb = GC.count_bubbles(im)
        hint = GC.chair_row_hint([], im)
        ck('%s ⇒ count_bubbles=%d（期望 0）｜chair_row_hint=%s（期望 False）'
           % (fn, nb, hint), nb == 0 and hint is False)

    print()
    print('【4】⚠⚠ 对照项：**关掉宽度过滤** ⇒ 4 楼那帧必须回到 2 个（复现原 bug）')
    im5 = _load('floor4_scroll_chk8.png')
    if im5 is not None:
        old = _blocks(im5, use_width=False)
        new = _blocks(im5, use_width=True)
        ck('关掉宽度过滤 ⇒ %d 块（复现"凑够 >=2 ⇒ 误判"）' % len(old), len(old) >= 2,
           [(b[0], b[1], b[3]) for b in old])
        ck('打开宽度过滤 ⇒ %d 块（修好了）' % len(new), len(new) == 0,
           [(b[0], b[1], b[3]) for b in new])
        ck('⚠⚠ 且两块的宽度都**小于**阈值（正是被判掉的原因）',
           bool(old) and all(b[0] < GC.BUBBLE_MIN_W for b in old),
           [(b[0], 'min=%s' % GC.BUBBLE_MIN_W) for b in old])

    print()
    print('【5】⭐⭐ 零损失：2 楼真椅子层必须**仍有 4 个**，`chair_row_hint` 必须 True')
    for fn in ('floor2_chair_probe.png', 'floor2_chair_probe_b.png'):
        im = _load(fn)
        if im is None:
            print('      （缺 %s ⇒ 跳过）' % fn)
            continue
        nb = GC.count_bubbles(im)
        hint = GC.chair_row_hint([], im)
        ck('%s ⇒ count_bubbles=%d（期望 4）｜chair_row_hint=%s（期望 True）'
           % (fn, nb, hint), nb == 4 and hint is True)

    print()
    print('【6】结构级：`scroll_to_top` 判到椅子层要**返回 False**（不是谎报到底）')
    s2 = src.find('def scroll_to_top(')
    e2 = src.find('\ndef ', s2 + 10)
    body2 = src[s2:e2] if s2 >= 0 else ''
    code2 = '\n'.join(l for l in body2.splitlines() if not l.lstrip().startswith('#'))
    ck('找到 `scroll_to_top`', s2 >= 0)
    ck('里面调用了 `chair_row_hint`', 'chair_row_hint' in code2)
    ck('`still_chair is True` 时**返回 False**（别在 2 楼点炼金坐标 ✗）',
       'return False' in code2 and 'still_chair' in code2)

    print()
    print('【7】结构级：`alchemy.run` 收到 False 要**放弃炼金**（不乱点坐标）')
    ap = _os.path.join(CORE, 'alchemy.py')
    asrc = open(ap, encoding='utf-8').read()
    s3 = asrc.find('def run(')
    e3 = asrc.find('\ndef ', s3 + 10)
    body3 = asrc[s3:e3] if s3 >= 0 else ''
    code3 = '\n'.join(l for l in body3.splitlines() if not l.lstrip().startswith('#'))
    ck('`alchemy.run` 里调用 `scroll_to_top`', 'scroll_to_top' in code3)
    ck('`not _topped` 时提前 return（`not_topped`）',
       'not_topped' in code3 and 'return res' in code3)

    print()
    print('=' * 78)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：4 楼不再被误判成椅子层（炼金能走到宝箱）；'
          '2 楼真气泡零损失；`scroll_to_top` / `alchemy.run` 的放弃链路完整')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())