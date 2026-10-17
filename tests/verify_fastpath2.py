# -*- coding: utf-8 -*-
"""verify_fastpath2.py · 验证「大厅/选图/图内」三态判定能用模板快查替掉 OCR

用户的提速原则：**能点固定位置的就用固定位置，只能 OCR 的才 OCR**。
这个脚本回答：哪些"我在哪个界面"的判断**不需要 OCR**。

三态的固定特征（720×1280 实测）：
    大厅     底部导航条在 + 四角入口(攻略/活动/首充/情报)
    选图界面 底部导航条在 + 「进入地图」(y≈1078) / 「快速扫荡」
    图内     底部导航条在 + 「结束冒险」(y≈515) + 棋盘
⇒ **底部导航条在** 这件事用**模板 6.8ms** 就能判（OCR 要 1.4~3.6s）；
   但**区分大厅 vs 选图 vs 图内**需要读文字 ⇒ 那一层仍然必须 OCR（诚实说明）。
"""
import os
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）
import glob
import time
import ast
import inspect
import textwrap

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import fixed as F                           # noqa: E402
import mapbot as MB                         # noqa: E402  ⭐ 只为 AST 对拍真 `Bot.__init__`
import explore_loop as EL                   # noqa: E402



def load_720():
    """找 720×1280 的真帧。⭐ 优先本仓自带的 `_verify/`（两端平行，不依赖手机端仓）"""
    out = []
    for d in (os.path.join(HERE, '_verify'), os.path.join(HERE, 'runs'),
              ''):
        if not os.path.isdir(d):
            continue
        for p in sorted(glob.glob(os.path.join(d, '*.png'))):
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None and img.shape[:2] == (F.PC_H, F.PC_W):
                out.append((p, img))
    return out


def _real_init_attrs():
    """从**真的** `mapbot.Bot.__init__` 里 AST 抠出它到底设了哪些实例属性。

    ⚠ 为什么必须查真的（2026-10-06 教训，本条就是那次假绿的直接产物）：
      下面的 `_FakeBot` **跳过 `__init__`**（不连设备），凡是 `__init__` 里的字段
      都得在这里手装一遍 ⇒ **两边一漂移，替身就会凭空补上一个真 Bot 根本没有的
      属性，把真机的 bug 藏起来** ✗。
      这正是 BUG-1 假绿的原因：真 `Bot` **从来没有** `_snap_n`，
      而本替身一直在提供它 ⇒ `fx_has`/`fx_at` 的**帧号缓存判据"看着能用"、
      真机上却恒失效**（`getattr(b,'_snap_n',None)` 恒 `None` ⇒ 缓存永不失效 ✗✗）。
    ⇒ 所以这里不写死名单，**每次跑都跟真源码对一遍**：真 `Bot` 哪天又少了哪个
      字段，本脚本当场红，而不是继续假绿 ✓。
    """
    src = textwrap.dedent(inspect.getsource(MB.Bot.__init__))
    names = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == 'self'
                and isinstance(node.ctx, ast.Store)):
            names.add(node.attr)
    return names


class _FakeBot:
    """最小 Bot 替身：只提供 fx_* 用到的 img() / _snap_n

    ⚠ 本替身手装的**每一个**字段都必须真的存在于 `mapbot.Bot.__init__`（见上）。
    """

    #: 本替身手装、且**必须**在真 `Bot.__init__` 里存在的字段
    HAND_SET = ('_img_arr', '_snap_n')

    def __init__(self, img, n=0):
        _real = _real_init_attrs()
        for _k in self.HAND_SET:
            if _k not in _real:
                raise AssertionError(
                    '⭐ 替身自检失败：真 `mapbot.Bot.__init__` 里**没有** `%s`，'
                    '而本替身在提供它 ⇒ 会凭空补上真机没有的属性、把 bug 藏起来 ✗'
                    '（BUG-1 就是这么假绿的）' % _k)
        self._img_arr = img
        self._snap_n = n

    def img(self):
        return self._img_arr


def main():
    frames = load_720()
    print('=== 三态判定的快查可行性 ===')
    print('720×1280 真帧 %d 张' % len(frames))
    if not frames:
        return 1

    print()
    print('【1】底部导航条存在性（模板 vs OCR）')
    n_ok = 0
    for p, img in frames[:8]:
        b = _FakeBot(img, n=1)
        t0 = time.time()
        has = EL.fx_has(b, 'nav_dex', band='nav', refresh=True)
        dt = (time.time() - t0) * 1000
        n_ok += 1 if has else 0
        print('   %-22s nav_dex=%-5s %6.2fms' % (os.path.basename(p), has, dt))
    print('   ⇒ %d/%d 帧判出导航条在' % (n_ok, min(8, len(frames))))

    print()
    print('【2】能完全免 OCR 的判断 vs 必须 OCR 的判断')
    rows = [
        ('底部导航条在不在（大厅/选图/图内 都有）', '✅ 模板 6.8ms', '导航条恒在，判据稳定'),
        ('面板盖住了没有（棋盘被挡）',           '✅ 模板/像素 <5ms', '结束冒险 区域有无固定图标'),
        ('点击固定按钮（开始冒险/结束冒险/关闭）', '✅ 直接写死坐标 0ms', '720p 固定布局'),
        ('体力数字 / 倒计时 / 图名 / 道具名 / 价格', '❌ 必须 OCR', '内容每轮都变'),
        ('大厅 vs 选图 vs 图内 的区分',           '⚠ 部分：导航条只能判"不在图外"', '四角入口/进入地图/结束冒险 是文字'),
        ('战斗结算面板（回放/关闭/跳过）',         '⚠ 部分：三键坐标固定，但"有没有结算"要判', '需先知道面板开没开'),
    ]
    for what, how, why in rows:
        print('   %-40s %-22s %s' % (what, how, why))

    print()
    print('【3】单轮省下来的时间（按设备日志实测 206.8s/43 次 OCR ≈ 4.8s/次）')
    ocr_cost = 4.8
    for k, nfix in ((1, 1), (2, 3), (4, 6)):
        saved = nfix * (ocr_cost - 0.007)
        print('   每轮 %d 处改用固定坐标 ⇒ 省 %5.1f 秒' % (nfix, saved))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
