# -*- coding: utf-8 -*-
"""verify_vault_pick.py · 回归：宝库选奖励 —— **不许在"图标还没画出来"的帧上做选择**

用户 2026-10-05 报（原话）：「**遇到天赋果实没有选择天赋果实作为奖励**」

真根因（真机取证帧逐帧统计，**不是猜**）
--------------------------------------
同一轮 5 张取证帧（`runs/vaultdbg/` = `D:\\sdcard\\...\\bagdbg\\`），面板区绿像素数：

    01_r1_start        0
    02_r1_after_buy    0
    03_r1_before_pick  0      ← ★ bot 就是**在这帧**做 `vault_pick` 的
    04_r1_after_pick   17040  ← 点了一格之后，图标才出现

那一帧上 `(167,497)` 是**纯亮黄方块**（最多色占 **4624/4624 = 100%**、绿像素 0）
  ⇒ 颜色法必然全灭（`color_none`）
  ⇒ 掉进**模板兜底**，而模板在**纯色块**上会**乱给分**（实测 0.552 判成「四叶草」）
  ⇒ **挑了一格错的** ✗✗

而**同一块面板**在图标画出来之后（`04` 帧）实测有 **2 个天赋果实**：
    `(359,881) pink=0.564` ｜ `(455,881) pink=0.520`
⇒ 用户说的「有天赋果实却没选它」**逐字复现** ✓

修法（`vault_pick`）
--------------------
颜色法全灭时**不立刻判**：先**重新取帧、多等几轮**（图标可能还没渲染完），
直到 `VAULT_SETTLE_SECS(4s)` 超时才退化到模板兜底。
⛔ **等待期间不点任何格子** —— 早期版本加过"点一格把图标翻出来"，
   但那条因果**没被证明**（03→04 之间既隔 4 秒、又隔 bot 那一下点击，两者分不开）
   ⇒ 用户追问「为什么选择奖励前要点一下？」后复查，**已删** ✓
   实测：光靠"等"就能在翻开帧上挑中天赋果实 ⇒ 那一点本来就不需要 ✓

本门禁（**驱动真 `vault_pick` + 真机帧**，四档）
------------------------------------------------
 ① 已翻开的现场帧（1 个幸运草）⇒ 必须挑中 **(167,785)**
 ② ⭐ **复现 01:13 那把的真实顺序**：第 1 帧给"没渲染完"的、之后给"渲染好"的
    ⇒ 必须挑中**渲染好的那帧里的天赋果实**（`(359,881)` 或 `(455,881)`）
    ⛔ 旧代码在这一档会挑 `(455,497)`（没图标的画面上蒙出来的假「四叶草」）← **牙齿**
    ⛔ 且**等待期间一下都不许点**（钉死"不盲点"这条新口径）
 ③ 一直认不出 ⇒ 不许崩、且必须走完重试（日志里要有 `color_retry`）
 ④ ⭐⭐ **02:43 真机第 2 圈那把**（用户原话「**我看他没选择天赋果实，即时阻止了**」）：
    同一帧里有两格都被颜色法判成「天赋果实」——
      `(455,689)` 真天赋果实（角标 **10**）｜`(263,593)` 粉**玫瑰卡**（**没有角标**）
    ⇒ 只有「档位 = 数量角标」能分开这两格；
    ⛔ 旧 `QTY_OFF=(32,22,50,50)` 从格中心 +32 才起裁 ⇒ 把 "10" 的前导 "1" 切掉
       ⇒ `read_qty` 返回 **0** ⇒ 两格同档 ⇒ 平档按扫描顺序 ⇒ **挑中玫瑰卡** ✗✗ ← **牙齿**
    ⇒ 必须挑中 `(455,689)`、且 `read_qty` 必须读出 **10** ✓
 ⑤ ⭐⭐⭐ **03:41 真机第 1 圈那把**（用户原话「**第一层幸运草和天赋果实全都要，结果都没选**」）：
    买完那一刻的帧**只画了底色**，颜色法在 `(455,497)` 上量到 `green=0.254`
    （旧阈值 0.25 ⇒ 只高 **0.004**）⇒ **假命中** ⇒ "没命中就等"的闸门**被骗过**
    ⇒ 立刻挑了这一格 ✗；而同一圈画完之后真有 6 个命中，含
    `(167,689) 四叶草 角标1` 与 `(551,785) 天赋果实 角标5` = 用户说的"两个都有" ✗✗
    ⛔ 旧代码在这一档挑 `(455,497)`（没画完的底色块）← **牙齿**
    ⇒ 必须挑中 **有数量角标** 的那两格之一（本档期望 `(551,785)` 天赋果实×5：
       同档 1.00 ⇒ 天赋果实优先 ✓），且日志里要有 `color_retry`（说明真的等了）

用法：
    python verify_vault_pick.py
"""
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
import time

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import buypanels as BP                      # noqa: E402


FAILS = []
V = os.path.join(HERE, '_verify')
LIVE = os.path.join(V, 'vault_live_20261005.png')          # 已翻开：1 个幸运草
UNDRAWN = os.path.join(V, 'vault_undrawn_20261005.png')    # 没翻开：纯色块
REVEALED = os.path.join(V, 'vault_after_reveal_20261005.png')  # 点一格之后：2 个天赋果实
CLOVER_AT = (167, 785)                                     # 现场帧上的幸运草
FRUITS_AT = ((359, 881), (455, 881))                       # 翻开帧上的两个天赋果实
OLD_BOGUS = (455, 497)                                     # 旧代码在纯色块上蒙出来的那格
# ⭐ 2026-10-05 02:43 真机第 2 圈那把（见文件头 ④）
R2_UNDRAWN = os.path.join(V, 'vault_r2_undrawn_20261005.png')    # 08_r2_before_pick（角标没渲染）
R2_RENDERED = os.path.join(V, 'vault_r2_rendered_20261005.png')  # 09_r2_after_pick（图标+角标都在）
R2_FRUIT = (455, 689)                                      # 真天赋果实（角标 10）
R2_ROSE = (263, 593)                                       # 粉"玫瑰卡"（无角标）＝ bot 当时选的 ✗
R2_FRUIT_QTY = 10                                          # 该格角标真值
# ⭐ 2026-10-05 03:41 真机第 1 圈那把（见文件头 ⑤）
R1_UNDRAWN = os.path.join(V, 'vault_r1_undrawn_20261005.png')    # 买完那一刻：只画了底色
R1_RENDERED = os.path.join(V, 'vault_r1_rendered_20261005.png')  # 画完：6 个命中
R1_FAKE = (455, 497)                                       # 未渲染帧上的假命中（green=0.254）✗
R1_FRUIT = (551, 785)                                      # 真天赋果实（角标 5）
R1_CLOVER = (167, 689)                                     # 真四叶草（角标 1）
R1_REALS = (R1_FRUIT, R1_CLOVER)                           # 本圈**有角标**的两格


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


# ⭐⭐⭐ 2026-10-06 **"同一格"判据**（治本文件 5 项断言把**理论坐标**钉死的问题）
#
#   起因：`vault_tiles()` 的尺寸阈值修成"跟分辨率走"之后（修「宝库买不到第二层」），
#     720p 上终于能检出**真实格心**（84×84 色块的质心）⇒ `vault_pick` 返回的就是质心，
#     而下面那些常量（`R2_FRUIT=(455,689)` 等）写的是**理论网格**坐标
#     ⇒ 实测差 **1~5px** ⇒ 5 项断言假红 ✗
#
#   ⚠ 这是**断言过时**，不是挑错格：实测
#       (359,881)→(360,882) Δ=2 ｜ (455,689)→(458,689) Δ=3 ｜ (551,785)→(555,786) Δ=5
#     且 `_vault_rc()` 算出的**格号完全一致** ⇒ **同一格** ✓
#   ⇒ 判据改成"落在同一格"（差 < 半格距 48px），**这比钉死坐标更贴近意图**
#     —— 我们真正要守的是"挑中了那一格"，不是"像素级落在常数值上" ✓
#   ⚠ 但**错格仍然必须红**：旧代码那个 `OLD_BOGUS=(455,497)` 与期望格差一整格
#     ⇒ 下面的 `_same_cell(OLD_BOGUS, ...)` 仍为假 ⇒ 牙齿不受影响 ✓
_HALF_PITCH = float(BP.VAULT['pitch']) / 2.0


def _same_cell(a, b, tol=None):
    """两个坐标是不是**同一格**（默认容差 = 半格距 48px）

    ⚠ 用曼哈顿距离而不是 `_vault_rc` 相等：后者会把"跨格线上的点"归一化到某格、
      掩盖真实偏移；距离判据更直白、也更容易解释 ✓
    """
    if not a or not b:
        return False
    _t = _HALF_PITCH if tol is None else tol
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) < _t


def _any_same_cell(got, wants):
    return any(_same_cell(got, w) for w in wants)


def _load(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert im is not None and im.shape[:2] == (1280, 720), p
    return im


_ITEMS_CACHE = {}


def _items_of(im):
    """这一帧的面板 OCR 条目（只算一次，缓存）"""
    k = id(im)
    if k in _ITEMS_CACHE:
        return _ITEMS_CACHE[k]
    from rapidocr_onnxruntime import RapidOCR
    global _OCR
    if _OCR is None:
        _OCR = RapidOCR(use_cls=False)
    cv2.imencode('.png', im)[1].tofile(os.path.join(HERE, '_vp.png'))
    res, _ = _OCR(os.path.join(HERE, '_vp.png'))
    out = [{'text': t.strip(), 'cx': int(sum(q[0] for q in b) / 4),
            'cy': int(sum(q[1] for q in b) / 4),
            'x0': int(min(q[0] for q in b)), 'y0': int(min(q[1] for q in b)),
            'x1': int(max(q[0] for q in b)), 'y1': int(max(q[1] for q in b)), 'conf': c}
           for b, t, c in (res or []) if c > 0.4]
    _ITEMS_CACHE[k] = out
    return out


_OCR = None


class SeqBot:
    """按脚本给帧的假 Bot：第 i 次 `snap()` 换成第 i 帧（越界停在最后一帧）

    复现真机顺序：**第 1 帧"没翻开" → 之后"翻开"**（01:13 那把就是这个顺序）
    """

    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.taps = []
        self._img_arr = frames[0]
        import mapbot as MB
        self._mb = MB.Bot.__new__(MB.Bot)
        self._mb.runs = HERE
        self._mb.t = {'ocr': 0.0, 'ocr_n': 0}
        self._mb._img_arr = frames[0]

    def snap(self, name=None, save=False):
        if self.i < len(self.frames) - 1:
            self.i += 1
        self._img_arr = self.frames[self.i]
        self._mb._img_arr = self._img_arr
        return name

    def img(self):
        return self._img_arr

    def img_dlg(self):
        return self._img_arr

    def tap_dlg(self, x, y, wait=1.2):
        self.taps.append((int(x), int(y)))
        return True

    def tap(self, x, y, wait=1.2):
        return self.tap_dlg(x, y, wait)

    def board_luma(self):
        return 0.0

    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        cur = img if img is not None else self._img_arr
        return self._mb.ocr(min_conf=min_conf, img=cur, band=band, tag=None)


def run(frames, level=1):
    bot = SeqBot(frames)
    log = []
    oi = BP._items
    BP._items = lambda _b, reuse=True: _items_of(bot.img())
    try:
        at, name = BP.vault_pick(bot, log, level)
    finally:
        BP._items = oi
    return at, name, bot, log


def main():
    print('=== 宝库选奖励回归（真 vault_pick + 真机帧）===')
    for p in (LIVE, UNDRAWN, REVEALED, R2_UNDRAWN, R2_RENDERED, R1_UNDRAWN, R1_RENDERED):
        if not os.path.exists(p):
            print('   （缺基准帧 %s ⇒ 跳过本门禁）' % os.path.relpath(p, HERE))
            return 0
    live, undrawn, revealed = _load(LIVE), _load(UNDRAWN), _load(REVEALED)
    r2_undrawn, r2_rendered = _load(R2_UNDRAWN), _load(R2_RENDERED)
    r1_undrawn, r1_rendered = _load(R1_UNDRAWN), _load(R1_RENDERED)
    print('基准帧：现场(有草) / 未翻开(纯色块) / 翻开后(2 个果实) / 02:43 第2圈(玫瑰卡+真果实)'
          ' / 03:41 第1圈(只画了底色 → 画完)')
    print()

    # ── ① 已翻开的现场帧：必须挑中那个幸运草 ──
    print('【1】已翻开的现场帧（1 个幸运草）⇒ 必须挑中 %s' % (CLOVER_AT,))
    at1, nm1, bot1, log1 = run([live])
    print('      pick=%s  name=%s' % (at1, nm1))
    ck('挑中了幸运草那一格 %s' % (CLOVER_AT,), at1 == CLOVER_AT, '实际 %s' % (at1,))
    ck('判据走的是**颜色法**（不是模板蒙的）', '色判' in (nm1 or ''), nm1)
    ck('**没有**乱点别的格子', len(bot1.taps) == 0, 'taps=%s' % (bot1.taps,))

    # ── ② ⭐牙齿：复现 01:13 那把的真实顺序（先没翻开、后翻开）──
    print()
    print('【2】⭐ 复现真机顺序：第 1 帧没翻开 → 之后翻开 ⇒ 必须挑中**翻开帧里的天赋果实**')
    print('      ⛔ 旧代码在这一档会挑 %s（纯色块上蒙出来的假「四叶草」）' % (OLD_BOGUS,))
    at2, nm2, bot2, log2 = run([undrawn, revealed, revealed, revealed])
    print('      pick=%s  name=%s' % (at2, nm2))
    ck('挑中的是**天赋果实**（不是那个假的四叶草）', '天赋果实' in (nm2 or ''), nm2)
    ck('落点是翻开帧里真有的那两个果实之一 %s' % (FRUITS_AT,),
       _any_same_cell(at2, FRUITS_AT), '实际 %s' % (at2,))
    ck('**没有**挑到旧代码那个错格 %s' % (OLD_BOGUS,), at2 != OLD_BOGUS)
    ck('日志里留下了"重新取帧重扫"的痕迹（说明真的等了，不是碰巧）',
       any(isinstance(d, dict) and d.get('vault') == 'color_retry' for d in log2), '')
    # ⭐⭐ 2026-10-05 用户追问「**为什么选择奖励前要点一下？**」⇒ 复查后发现那条因果
    #   **没被证明**（03→04 之间既隔 4 秒、又隔 bot 那一下点击，两者分不开）
    #   ⇒ 按"不猜、只做有证据的事"，**盲点已删** ⇒ 这里反过来钉死：**一下都不许点**
    ck('⭐ **绝不盲点任何格子**（等待期间零点击）', len(bot2.taps) == 0,
       'taps=%s' % (bot2.taps,))

    # ── ③ 永远不翻开：不许崩，且必须走完重试 ──
    print()
    print('【3】永远不翻开 ⇒ 不许崩，且必须走完重试后才退化')
    t0 = time.time()
    at3, nm3, _b3, log3 = run([undrawn, undrawn, undrawn, undrawn])
    dt = time.time() - t0
    print('      pick=%s  name=%s  （耗时 %.1fs）' % (at3, nm3, dt))
    ck('没崩、有返回值', at3 is not None)
    ck('确实重试过（日志里有 color_retry）',
       any(isinstance(d, dict) and d.get('vault') == 'color_retry' for d in log3))

    # ── ④ ⭐⭐ 02:43 真机第 2 圈：粉"玫瑰卡" vs 真天赋果实（靠数量角标分开）──
    print()
    print('【4】⭐ 02:43 真机第 2 圈：同帧两格都判成「天赋果实」⇒ 必须选**带角标 10 的那个**')
    print('      真果实 %s（角标 10）｜粉玫瑰卡 %s（无角标，bot 当时选了它 ✗）'
          % (R2_FRUIT, R2_ROSE))
    at4, nm4, bot4, log4 = run([r2_undrawn, r2_rendered, r2_rendered, r2_rendered], level=2)
    q4 = BP.read_qty(bot4, R2_FRUIT[0], R2_FRUIT[1])
    print('      pick=%s  name=%s  read_qty(真果实)=%r' % (at4, nm4, q4))
    ck('挑中的是**真天赋果实** %s' % (R2_FRUIT,), _same_cell(at4, R2_FRUIT), '实际 %s' % (at4,))
    ck('**没有**挑到粉玫瑰卡 %s（旧 QTY_OFF 会挑它）' % (R2_ROSE,), at4 != R2_ROSE)
    ck('数量角标读出 %d（旧窗口从 +32 起裁 ⇒ 只读到 "0"）' % R2_FRUIT_QTY,
       q4 == R2_FRUIT_QTY, '实际 %r' % (q4,))
    _t4 = [d for d in log4 if isinstance(d, dict) and d.get('vault') == 'color_tier'
           and _same_cell(tuple(d.get('at') or (0, 0)), R2_FRUIT)]
    ck('该果实的档位 > 0（= 数量真被读出来了，不是靠顺序蒙的）',
       bool(_t4) and _t4[0].get('tier', 0) > 0, '实际 %s' % (_t4,))
    ck('**没有**盲点任何格子（等待期间零点击）', len(bot4.taps) == 0,
       'taps=%s' % (bot4.taps,))

    # ── ⑤ ⭐⭐⭐ 03:41 真机第 1 圈：只画了底色的帧上**假命中骗过了等待闸门** ──
    print()
    print('【5】⭐ 03:41 真机第 1 圈：买完那一刻只画了底色 ⇒ 不许按假命中挑，必须等画完')
    print('      假命中 %s（green=0.254，比旧阈值 0.25 只高 0.004）｜真有角标的两格 %s'
          % (R1_FAKE, R1_REALS))
    ink_fake = BP.badge_ink(r1_undrawn, R1_FAKE[0], R1_FAKE[1])
    ink_fruit = BP.badge_ink(r1_rendered, R1_FRUIT[0], R1_FRUIT[1])
    ink_clover = BP.badge_ink(r1_rendered, R1_CLOVER[0], R1_CLOVER[1])
    print('      badge_ink：假命中=%d ｜真果实=%d ｜真草=%d（阈值 %d）'
          % (ink_fake, ink_fruit, ink_clover, BP.BADGE_INK_MIN))
    ck('假命中格**没有**角标笔画（0）', ink_fake == 0, '实际 %d' % ink_fake)
    ck('真果实/真草**都有**角标笔画（≥ %d）' % BP.BADGE_INK_MIN,
       ink_fruit >= BP.BADGE_INK_MIN and ink_clover >= BP.BADGE_INK_MIN,
       '果实 %d / 草 %d' % (ink_fruit, ink_clover))
    at5, nm5, bot5, log5 = run([r1_undrawn, r1_rendered, r1_rendered, r1_rendered], level=1)
    print('      pick=%s  name=%s' % (at5, nm5))
    ck('挑中的是**有角标的真奖励**之一 %s' % (R1_REALS,),
       _any_same_cell(at5, R1_REALS), '实际 %s' % (at5,))
    ck('同档 1.00 时按用户口径挑**天赋果实** %s' % (R1_FRUIT,),
       _same_cell(at5, R1_FRUIT),
       '实际 %s' % (at5,))
    ck('**没有**挑未渲染帧上的假命中 %s（旧代码会挑它）' % (R1_FAKE,), at5 != R1_FAKE)
    ck('日志里有"角标=0 ⇒ 重新取帧"的痕迹（说明真的等了，不是碰巧）',
       any(isinstance(d, dict) and d.get('vault') == 'color_retry' and d.get('badged') == 0
           for d in log5), '')
    ck('**没有**盲点任何格子（等待期间零点击）', len(bot5.taps) == 0,
       'taps=%s' % (bot5.taps,))

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：已渲染好能挑中草；没渲染好时只**重新取帧多等几轮**（不点任何格子）再挑；'
          '同帧多个粉色格时按**数量角标**分档挑真果实；只画了底色的假命中骗不过等待闸门')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    finally:
        try:
            os.remove(os.path.join(HERE, '_vp.png'))
        except OSError:
            pass
