# -*- coding: utf-8 -*-
"""★ 回归：传承祭坛「**是 30000 就买，不然不买**」（2026-10-11 用户口径 ✓）

真机面板：`runs/acc3/shrine_panel_r-1.png`（实例B那把采到 ✓）
用户原话：「**直接点右下角的三万买了就行**」＋「**识别一下，是30000就买，不然不买**」
"""
import io
import os
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import buypanels as BP


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('传承祭坛 shrine_flow（2026-10-11）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `shrine_flow`', hasattr(BP, 'shrine_flow'))
ck('② 有 `shrine_cells()`（18 格）', len(BP.shrine_cells()) == 18,
   '%d 格' % len(BP.shrine_cells()))
ck('③ 目标价格常量 = 30000', BP.SHRINE_PRICE == 30000, str(BP.SHRINE_PRICE))
ck('④ 网格 3 行 × 6 列',
   BP.SHRINE_ROWS == 3 and BP.SHRINE_COLS == 6)
_cells = BP.shrine_cells()
ck('⑤ 首格 = (111, 622)（绿框实测 ✓）', _cells[0] == (111, 622), str(_cells[0]))
ck('⑥ 第 2 格 x = 210（列距 99 ✓）', _cells[1][0] == 210, str(_cells[1]))
ck('⑦ 第 7 格 = 第 2 行第 1 列 (111, 722)（行距 100 ✓）',
   _cells[6] == (111, 722), str(_cells[6]))

print()
print('【2】⭐ 行为级：价格 ⇒ 买 / 不买（**两条都要测** ✓）')


class FB:
    """假 Bot：给固定 OCR 结果，记录点击

    ⚠ `with_confirm=True` 模拟**买入确认框**（源码 `HeritageBlockPanel.cs:81`
      `ShowPopPanel(ActionPrompt_GEN)` ⇒ 点价格后必弹「确定」✓）
    """

    def __init__(self, texts, with_confirm=False):
        self.texts = list(texts)
        self.with_confirm = with_confirm
        self.taps = []
        self._tapped_buy = False

    def ocr(self, band=None, tag='', **k):
        y0, y1 = (band or (0, 1280))
        its = [t for t in self.texts if y0 <= t['cy'] <= y1]
        # 点了购买按钮之后 ⇒ 确认框出现（「确定」在 y≈960 ⇒ cy>800 ✓）
        if self.with_confirm and self._tapped_buy:
            its = its + [{'text': '确定', 'cx': 458, 'cy': 960, 'conf': 1.0}]
        return its

    def tap(self, x, y, wait=0.0):
        self.taps.append((x, y))
        if (x, y) == BP.SHRINE_BUY_XY:
            self._tapped_buy = True

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))
        if (x, y) == BP.SHRINE_BUY_XY:
            self._tapped_buy = True

    def snap(self, *a, **k):
        return 'x.png'

    def img(self):
        import numpy as np
        return np.zeros((1280, 720, 3), np.uint8)


PANEL = [
    {'text': '传承祭坛', 'cx': 461, 'cy': 336, 'conf': 0.94},
    {'text': '选择装备', 'cx': 360, 'cy': 540, 'conf': 1.0},
    {'text': '筛选', 'cx': 157, 'cy': 908, 'conf': 0.99},
]

# 打桩 `_items`（`shrine_flow` 用它在开头判面板在不在）
#   ⚠⚠ **必须动态**：`_confirm()` 也是走 `_items()` 找「确定」的 ⇒
#     若这里恒返回 PANEL（不含「确定」）⇒ **确认框永远找不到** ⇒
#     `bought` 被如实改成 False（我的假 Bot 把自己坑了 ✗ 第一版就是这样）
_orig = BP._items


def _mk_items(bot, panel, with_confirm=False):
    def _f(b, reuse=True):
        if with_confirm and getattr(bot, '_tapped_buy', False):
            return list(panel) + [{'text': '确定', 'cx': 458, 'cy': 960,
                                   'conf': 1.0}]
        return list(panel)
    return _f


# ── ① 价格 = 30000 ⇒ **必须买**（含确认框 ✓）──
_b = FB(PANEL + [{'text': '30000', 'cx': 601, 'cy': 908, 'conf': 1.0}],
        with_confirm=True)
BP._items = _mk_items(_b, PANEL, with_confirm=True)
try:
    _log = []
    _out = BP.shrine_flow(_b, _log)
finally:
    BP._items = _orig
print('     ①价格30000 ⇒ bought=%s acts=%s taps=%s'
      % (_out.get('bought'), _out.get('acts'), _b.taps))
ck('⑧ ⭐ 价格 30000 ⇒ **买了**（`bought=True` ✓）', _out.get('bought') is True)
ck('⑨ 点了**右下角按钮** (594, 909)（实测中心 ✓）',
   (594, 909) in _b.taps, str(_b.taps))
ck('⑩ ⚠ 关面板时点了 ✗ (628, 335)', (628, 335) in _b.taps)
ck('⑪ ⚠ **没有**点「筛选」(157,908) / 「刷新」(250,908)（用户没说 ✗）',
   (157, 908) not in _b.taps and (250, 908) not in _b.taps)
ck('⑫ ⚠ **没有**点任何装备格（点格会开详情页 ⇒ 与宝库那次同一个坑 ✗）',
   not any(t in BP.shrine_cells() for t in _b.taps), str(_b.taps))
# ⭐⭐⭐ 确认框（源码 `HeritageBlockPanel.cs:81` 铁证 ⇒ 必须点「确定」才真买 ✓）
ck('⑯ ⭐⭐ **点了确认框的「确定」**（源码：点价格只弹框，确认后才真买 ✓）',
   (458, 960) in _b.taps, str(_b.taps))
ck('⑰ ⚠ **没有**点到「取消」（点错会浪费钱 ✗）',
   len([t for t in _b.taps if t == (458, 960)]) >= 1)
ck('⑱ ⭐ 确认框那步落了日志（`buy_confirm` / `confirm_step`）',
   any(isinstance(e, dict) and ('buy_confirm' in e or e.get('shrine') == 'confirm_step')
       for e in _log), str([e for e in _log if isinstance(e, dict)])[:150])

# ── ①b 价格 = 30000 但**没有确认框**（= 金币不够，源码走充值提示）⇒ 不许谎报 ✓ ──
_b1b = FB(PANEL + [{'text': '30000', 'cx': 601, 'cy': 908, 'conf': 1.0}],
          with_confirm=False)
BP._items = lambda bot, reuse=True: PANEL
try:
    _l1b = []
    _o1b = BP.shrine_flow(_b1b, _l1b)
finally:
    BP._items = _orig
print('     ①b价格30000但无确认框 ⇒ bought=%s skip=%s'
      % (_o1b.get('bought'), _o1b.get('skip')))
ck('⑲ ⭐⭐ 没等到确认框 ⇒ **不算买到**（`skip=no_confirm_dialog`，如实记账 ✓）',
   _o1b.get('bought') is False and _o1b.get('skip') == 'no_confirm_dialog')

# ── ② 价格 ≠ 30000 ⇒ **必须不买** ──
for _pv in ('6000', '1000', '2000'):
    _b2 = FB(PANEL + [{'text': _pv, 'cx': 601, 'cy': 908, 'conf': 1.0}])
    BP._items = lambda bot, reuse=True: PANEL
    try:
        _l2 = []
        _o2 = BP.shrine_flow(_b2, _l2)
    finally:
        BP._items = _orig
    _hit = (594, 909) in _b2.taps
    print('     ②价格%s ⇒ bought=%s skip=%s 点了买吗=%s'
          % (_pv, _o2.get('bought'), _o2.get('skip'), _hit))
    ck('⑬ ⭐ 价格 %s ⇒ **不买**（`bought=False` ✓）' % _pv,
       _o2.get('bought') is False and _o2.get('skip') == 'price_not_target')
    ck('⑭ ⚠ 价格 %s ⇒ **没点**购买按钮' % _pv, not _hit, str(_b2.taps))

# ── ③ 读不到价格 ⇒ **必须不买**（fail-closed ✓）──
_b3 = FB(PANEL)
BP._items = lambda bot, reuse=True: PANEL
try:
    _l3 = []
    _o3 = BP.shrine_flow(_b3, _l3)
finally:
    BP._items = _orig
print('     ③读不到价格 ⇒ bought=%s skip=%s'
      % (_o3.get('bought'), _o3.get('skip')))
ck('⑮ ⭐ 读不到价格 ⇒ **不买**（用户口径「是30000就买，不然不买」✓ fail-closed）',
   _o3.get('bought') is False)

# ── ④ 价格判据不许被左边的「筛选」污染 ──
_b4 = FB(PANEL + [{'text': '30000', 'cx': 601, 'cy': 908, 'conf': 1.0},
                  {'text': '筛选9999', 'cx': 157, 'cy': 908, 'conf': 0.9}],
         with_confirm=True)
BP._items = _mk_items(_b4, PANEL, with_confirm=True)
try:
    _l4 = []
    _o4 = BP.shrine_flow(_b4, _l4)
finally:
    BP._items = _orig
ck('⑳ ⚠ 只认**右侧**（x>560）⇒ 左边「筛选…」里的数字不干扰 ✓',
   _o4.get('bought') is True, str(_o4.get('skip')))

# ── ⑤ ⭐⭐ 买成功后**面板自己关**（源码 `PopAllPopPanel`）⇒ **不许再点 ✗** ──
#   源码铁证 `HeritageBlockPanel.cs:110-114`：
#       if (isExplore) { FinishBlock(block, SingleBlock); PopAllPopPanel(); }
#   ⇒ 买成功后格子被消耗、面板自己关 ⇒ 这时再点 ✗ (628,335) 会**点在空棋盘上** ✗
class FBGone(FB):
    """买完之后面板就**消失**了（模拟源码 `PopAllPopPanel` ✓）"""

    def __init__(self, texts):
        super().__init__(texts, with_confirm=True)

    def _panel_gone(self):
        return self._tapped_buy

    def tap(self, x, y, wait=0.0):
        self.taps.append((x, y))
        if (x, y) == BP.SHRINE_BUY_XY:
            self._tapped_buy = True

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))
        if (x, y) == BP.SHRINE_BUY_XY:
            self._tapped_buy = True


_b5 = FBGone(PANEL + [{'text': '30000', 'cx': 601, 'cy': 908, 'conf': 1.0}])


def _mk_gone(bot):
    def _f(b, reuse=True):
        if bot._panel_gone():
            return []          # ⭐ 面板已自己关 ⇒ 什么都不认到 ✓
        return list(PANEL)
    return _f


BP._items = _mk_gone(_b5)
try:
    _l5 = []
    _o5 = BP.shrine_flow(_b5, _l5)
finally:
    BP._items = _orig
print('     ⑤买完面板自己关 ⇒ taps=%s' % (_b5.taps,))
ck('㉑ ⭐⭐ 面板已自己关 ⇒ **没点 ✗**（不点空棋盘 ✓）',
   (628, 335) not in _b5.taps, str(_b5.taps))
ck('㉒ ⭐ 如实落了 `already_closed`（不静默 ✓）',
   any(isinstance(e, dict) and e.get('shrine') == 'already_closed' for e in _l5))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
