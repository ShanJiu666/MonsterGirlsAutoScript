# -*- coding: utf-8 -*-
"""verify_newequip.py · 回归：①「获得新装备」战斗收尾检测节点 ②结束原因**计数分开**

用户 2026-10-05 两条口径（原话）：
  · 「**摇色子结束，关闭战斗胜利界面后需要一个获得新装备检测**」
  · 「**做1 报数/计数分开**」

① 为什么补新装备节点（`check_newequip_after_battle`）
   「获得新装备！」此前只有**下一轮** `popups()` 的弹窗闸门接得住，中间隔着整盘标记扫描
   + 规划（真机 1.5~4s），而它**盖住整盘** ⇒ 这一轮地块全判成暗格（白判）；连 2 张还会走到
   "被面板挡住"那套兜底。触发时机（用户 09-26 口径）：**打完大拇指格拿到装备**就弹 ⇒
   摇完色子、结算面板刚关掉正是那一刻。

② 为什么计数要分开（`map_end_kind`）
   真机 13:29 那把（`runs/acc2/loop/loop_log.json`，已切一片进
   `_verify/loopend_acc2_20261005.json`）3 张图的 `finish` 全是 `targets_unreachable`
   （计划里的步被 `give_up_step` 摘光，**画面好好的**），却被原代码一视同仁计成
   「连续 2 张图认不出棋盘（画面被判"被面板挡住"）」+ 让人去看 `runs\\bagdbg` 的诊断帧
   —— 而那条路**根本不落帧**（`board_hidden_*` 最新是 10-04 11:37）⇒ 拿旧帧找新问题 ✗✗

本门禁（不需要模拟器、不联网）
------------------------------
 ① 结构：战斗结算的**两个出口**都必须挂 `check_newequip_after_battle`
 ② 行为：桩 bot 喂「获得新装备」→ 必须点**写死的 (360,835)** 且返回 True；
    读不到标题 ⇒ 返回 False 且**零点击**（绝不乱点）
 ③ 行为：`map_end_kind()` 在**真机切片**上判 'unreachable'；
    board_not_visible ⇒ 'board_blind'、blank_board ⇒ 'blank'、其它 ⇒ 'other'；
    **不许越过 `{'map':…}` 分界看上一张图的记录**
 ④ 结构：停整局的判据只剩 `blind_maps`；`targets_unreachable` 有**自己那条**文案（不指 bagdbg）

用法：
    python verify_neweiquip.py
"""
import io
import json
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

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np                          # noqa: E402

import explore_loop as EL                   # noqa: E402


FAILS = []
SRC = io.open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
FIX = os.path.join(HERE, '_verify', 'loopend_acc2_20261005.json')
VER = os.path.join(HERE, '_verify')


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _veiled_img():
    """合成「整屏有模态暗罩」帧：**顶部 HUD 条压暗**、棋盘区保持白。

    ⚠ 为什么能这么造（两个判据读的是屏幕的**不同部位**）：
      · `modal_veil()` 只看 **HUD 条**（y 0..180）⇒ 压暗它就判"有暗罩" ✓
      · `panel_gone()` 走的是**棋盘**判据（`board_hidden`）⇒ 棋盘不动
        ⇒ 它的行为与旧的纯白帧**完全一致**（不会引入额外点击）✓
      ⇒ 这样本档能**单独**验"有暗罩 ⇒ 照旧 OCR"，不被 `panel_gone` 的点击干扰 ✓
    """
    im = np.full((1280, 720, 3), 255, np.uint8)
    im[:180, :, :] = 40
    return im


class StubBot:
    """只喂 `ocr()` 结果、记录点击的桩 bot（`panel_gone` 会先走便宜的图像判据：
    棋盘图给一片白 ⇒ `board_hidden` False ⇒ 判"面板已关" ⇒ 不再付 OCR ✓）

    ⭐ 2026-10-06：`img` 可配 —— `check_newequip_after_battle` 现在会先量
      **有没有模态暗罩**（`modal_veil()`）⇒ 桩必须能分别喂"有暗罩/没暗罩"两种帧，
      否则验不到那条新判据（默认纯白 = 没暗罩）。
    """

    def __init__(self, items, img=None):
        self.items = items
        self._im = np.full((1280, 720, 3), 255, np.uint8) if img is None else img
        self.taps = []
        self.ocr_n = 0

    def img(self):
        return self._im

    def snap(self, *a, **k):
        return None

    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        self.ocr_n += 1
        return list(self.items)

    def tap(self, x, y, wait=1.2):
        self.taps.append((int(x), int(y)))
        return True

    def tap_dlg(self, x, y, wait=1.2):
        return self.tap(x, y, wait)


def main():
    print('=== 获得新装备检测节点 + 结束原因计数分开（真机日志 / 桩 bot）===')

    # ── ① 结构：战斗结算的两个出口都挂了检测 ──
    print()
    print('【1】结构：`wait_end` / `popups` 的战斗结算出口都必须挂新装备检测')
    for tag in ("check_newequip_after_battle(b, log, 'battle')",
                "check_newequip_after_battle(b, log, 'battle_popup')",
                "check_newequip_after_battle(b, log, 'battle_popup_fixed')"):
        ck('源码里有 %s' % tag, tag in SRC)
    ck('检测函数本体存在（`def check_newequip_after_battle`）',
       'def check_newequip_after_battle(' in SRC)
    ck('它走的是**写死坐标**的 `close_newequip()`（不是自己找按钮）',
       'if close_newequip(b, it, log, where):' in SRC)
    ck('它在战斗收尾里被调用 ≥3 处（两个结算出口 + 兜底那条）',
       SRC.count("check_newequip_after_battle(b, log, '") >= 3,
       '实际 %d' % SRC.count("check_newequip_after_battle(b, log, '"))

    # ── ② 行为：有暗罩 ⇒ 必须 OCR 并点写死坐标；无暗罩 ⇒ 免 OCR、零点击 ──
    print()
    print('【2】行为：有暗罩 ⇒ OCR + 点写死的 (360,835)；无暗罩 ⇒ **免 OCR**、零点击')
    hit_items = [{'text': '获得新装备！', 'cx': 360, 'cy': 430, 'conf': 0.99}]
    b1 = StubBot(hit_items, img=_veiled_img())
    log1 = []
    r1 = EL.check_newequip_after_battle(b1, log1, 'battle', wait=0)
    print('      有暗罩+有弹窗：ret=%s  ocr=%d  taps=%s'
          % (r1, b1.ocr_n, b1.taps))
    ck('返回 True（= 处理了弹窗）', r1 is True)
    ck('点了**写死**的 (360,835)（`fixed.A(\'equip_back\')`）', b1.taps == [(360, 835)],
       '实际 %s' % (b1.taps,))
    ck('日志里留下 `newequip_back`（where=battle）',
       any(isinstance(e, dict) and e.get('newequip_back') == 'battle' for e in log1))
    print('      （旧代码里 `check_newequip_after_battle` **不存在** ⇒ 这两档必红 ✓）')

    b2 = StubBot([{'text': '夏日海滩[100]', 'cx': 359, 'cy': 122, 'conf': 0.99}])
    log2 = []
    r2 = EL.check_newequip_after_battle(b2, log2, 'battle', wait=0)
    print('      无暗罩（干净盘）：ret=%s  ocr=%d  taps=%s' % (r2, b2.ocr_n, b2.taps))
    ck('返回 False', r2 is False)
    ck('**零点击**（没弹窗时一下都不许点）', b2.taps == [], '实际 %s' % (b2.taps,))
    ck('日志里记了 `newequip_check/hit=False`',
       any(isinstance(e, dict) and e.get('newequip_check') == 'battle'
           and e.get('hit') is False for e in log2))

    # ── ②b ⭐ 提速本体：干净盘必须**一次 OCR 都不付** ──
    print()
    print('【2b】⭐ 提速本体：干净盘（无暗罩）⇒ **零 OCR**；有暗罩 ⇒ 照旧 OCR')
    ck('干净盘 ⇒ **没调过 ocr()**（这一档就是 BUG-3 的提速 ✓）', b2.ocr_n == 0,
       '实际调了 %d 次' % b2.ocr_n)
    ck('干净盘 ⇒ 日志里写明 `ocr=skip_no_veil`（可取证：省了几次）',
       any(isinstance(e, dict) and e.get('ocr') == 'skip_no_veil' for e in log2))
    ck('有暗罩 ⇒ **照旧**调了 ocr()（不许把真有面板的帧短路掉 ✗）', b1.ocr_n >= 1,
       '实际调了 %d 次' % b1.ocr_n)

    # ⚠ 对照：把干净盘**人为压暗 HUD** ⇒ 必须退回"照旧 OCR"（证明判据不是恒真/恒假）
    b3 = StubBot([], img=_veiled_img())
    log3 = []
    EL.check_newequip_after_battle(b3, log3, 'battle', wait=0)
    ck('对照项：同一份"没弹窗"的 OCR 结果，**只把 HUD 压暗** ⇒ 必须照旧 OCR',
       b3.ocr_n >= 1, '实际 %d 次（若为 0 ⇒ 判据恒判"无暗罩"、等于没测）' % b3.ocr_n)

    # ── ③ 行为：map_end_kind 分类（真机切片 + 合成边界）──
    print()
    print('【3】`map_end_kind()`：真机切片判 unreachable；被挡/空格/其它各归各的')
    if not os.path.exists(FIX):
        ck('真机切片 %s 存在' % os.path.relpath(FIX, HERE), False)
    else:
        fx = json.load(io.open(FIX, encoding='utf-8'))
        real = fx.get('unreachable') or []
        k = EL.map_end_kind(real)
        print('      真机切片（%d 条，最后一条 finish=%r）⇒ %s'
              % (len(real), [e.get('finish') for e in real if isinstance(e, dict)
                             and e.get('finish')][-1:], k))
        ck('真机那把 ⇒ **unreachable**（不是"认不出棋盘"）', k == 'unreachable', k)
    cases = [('board_not_visible', [{'round': 0}, {'board_hidden': 'all_dark', 'n': 3},
                                    {'finish': 'board_not_visible'}], 'board_blind'),
             ('blank_board', [{'finish': 'blank_board', 'n': 3}], 'blank'),
             ('正常退图', [{'finish': 'clicked_end'}, {'finish': 'back_to_menu'}], 'other'),
             ('只有 board_hidden（无 finish）', [{'board_hidden': 'all_dark'}], 'board_blind'),
             ('跨图分界', [{'finish': 'board_not_visible'},
                          {'map': 0, 'end_reason': 'stuck'},
                          {'finish': 'targets_unreachable'}], 'unreachable')]
    for name, rows, want in cases:
        got = EL.map_end_kind(rows)
        ck('%s ⇒ %s' % (name, want), got == want, '实际 %s' % got)

    # ── ③b ⭐ 判据定标：真机 fixture 上「有暗罩 / 无暗罩」必须分得开 ──
    print()
    print('【3b】⭐ `modal_veil()` 定标：真机 fixture 上"有面板(暗罩)"与"干净盘"必须分得开')
    import cv2                              # noqa: E402
    #: (文件名, 真值是否"有暗罩") —— 全部取自本仓 `_verify/`（冻结 fixture，不读 runs/）
    FIXTURES = [
        # 真·有面板（整屏暗罩 ⇒ 必须判 True ⇒ 照旧 OCR）
        ('claim_popup_20261003.png', True), ('claim_after_20261003.png', True),
        ('vault_live_20261005.png', True), ('vault_r2_rendered_20261005.png', True),
        ('vault_r1_undrawn_20261005.png', True), ('vault_after_reveal_20261005.png', True),
        ('vault_start_20261005.png', True), ('back_test_before_20261003.png', True),
        ('slot_after_20261003.png', True), ('finish_confirm_dialog_20261002.png', True),
        # 干净盘（在图内、没面板 ⇒ 必须判 False ⇒ 免 OCR）
        ('live_01.png', False), ('live_02.png', False), ('live_03.png', False),
        ('live_04.png', False), ('live_05.png', False), ('live_06.png', False),
        ('live_07.png', False), ('live_08.png', False),
        ('clover_1_r_175413_0.png', False), ('clover_2_r_191036_0.png', False),
        ('clover_3_r_191134_0.png', False), ('clover_4_r_191248_0.png', False),
        ('clover_5_r_191336_0.png', False), ('clover_6_r_191429_0.png', False),
        ('now_20261003.png', False), ('acc2_chk.png', False),
        ('select_map_20261002.png', False), ('slots_now_20261003.png', False),
        ('stuck_reward_20261003.png', False),
        ('wsp_05_settle0_20261003.png', False), ('wsp_06_settle1_20261003.png', False),
    ]
    wrong = []
    p95_pos, p95_neg = [], []
    n_missing = 0
    for fn, want in FIXTURES:
        p = os.path.join(VER, fn)
        if not os.path.exists(p):
            n_missing += 1
            continue
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            ck('fixture %s 可读' % fn, False)
            continue
        if im.shape[:2] != (1280, 720):
            im = cv2.resize(im, (720, 1280), interpolation=cv2.INTER_AREA)
        got = EL.modal_veil(None, img=im)
        p95 = float(np.percentile(cv2.cvtColor(im[:180], cv2.COLOR_BGR2GRAY), 95))
        (p95_pos if want else p95_neg).append(p95)
        if got != want:
            wrong.append('%s(p95=%.0f 期望%s)' % (fn, p95, '有暗罩' if want else '无暗罩'))
    print('      有面板 %d 张 ｜ 干净盘 %d 张 ｜ 缺 %d 张'
          % (len(p95_pos), len(p95_neg), n_missing))
    ck('定标 fixture 够用（两边都 ≥8 张 ⇒ 不是拿一两个样本蒙的）',
       len(p95_pos) >= 8 and len(p95_neg) >= 8,
       '有面板 %d / 干净 %d' % (len(p95_pos), len(p95_neg)))
    if p95_pos and p95_neg:
        print('      暗罩帧 hud_p95 [%.0f, %.0f] ｜ 干净帧 [%.0f, %.0f] ｜ 阈值 %.0f'
              % (min(p95_pos), max(p95_pos), min(p95_neg), max(p95_neg),
                 EL._VEIL_P95_MIN))
        ck('⭐ **两簇完全不重叠**（否则单一阈值不可能同时满足两边）',
           max(p95_pos) < min(p95_neg),
           '暗罩最大 %.0f vs 干净最小 %.0f' % (max(p95_pos), min(p95_neg)))
        ck('⭐ 阈值落在两簇**中间**（不贴任何一边 ⇒ 留了余量，抗光照/地图差异）',
           max(p95_pos) < EL._VEIL_P95_MIN < min(p95_neg),
           '%.0f < %.0f < %.0f' % (max(p95_pos), EL._VEIL_P95_MIN, min(p95_neg)))
    ck('⭐ **每一张**真机 fixture 都判对（有面板不漏、干净盘不误伤）', not wrong,
       '判错 %d 张：%s' % (len(wrong), wrong))

    # ⚠ 对照项：证明这组定标**不是恒绿** —— 把干净帧的 HUD 条涂黑，必须翻成"有暗罩"
    _clean = None
    for fn, want in FIXTURES:
        if want is False and os.path.exists(os.path.join(VER, fn)):
            _clean = cv2.imdecode(np.fromfile(os.path.join(VER, fn), dtype=np.uint8),
                                  cv2.IMREAD_COLOR)
            break
    if _clean is not None:
        if _clean.shape[:2] != (1280, 720):
            _clean = cv2.resize(_clean, (720, 1280), interpolation=cv2.INTER_AREA)
        _dark = _clean.copy()
        _dark[:180] = 30
        ck('对照项：干净帧**只把 HUD 条涂黑** ⇒ 判据必须翻成"有暗罩"',
           EL.modal_veil(None, img=_dark) is True and EL.modal_veil(None, img=_clean) is False,
           '涂黑后=%s 原帧=%s' % (EL.modal_veil(None, img=_dark),
                                 EL.modal_veil(None, img=_clean)))
    ck('对照项：`modal_veil(None, img=None)` ⇒ **保守判"有暗罩"**（拿不到帧 ⇒ 照旧 OCR）',
       EL.modal_veil(None, img=None) is True)
    ck('对照项：空帧（size=0）⇒ 也保守判"有暗罩"',
       EL.modal_veil(None, img=np.zeros((0, 0, 3), np.uint8)) is True)

    # ── ④ 结构：停整局只看 blind_maps，且两条文案各说各的 ──
    print('【4】结构：停整局的判据只剩 `blind_maps`；"目标不可达"有自己那条文案')
    ck('按 `blind_maps` 计数并判停', "STATS['blind_maps'] >= 2" in SRC)
    ck('"目标不可达"单独计数（`stuck_maps >= 3`）', "STATS['stuck_maps'] >= 3" in SRC)
    ck('"认不出棋盘"那条文案只关 blind_maps',
       "连续 %d 张图认不出棋盘" in SRC and "% (STATS['blind_maps'], _dbg_hint)" in SRC)
    ck('"目标不可达"那条文案**不指 bagdbg**（那条路不落帧），指 loop_log.json',
       '连续 %d 张图计划走不下去（目标不可达，画面正常）' in SRC
       and "'loop', 'loop_log.json'" in SRC)
    ck('两个计数器都在 STATS 里初始化（不再靠 .get 隐式建）',
       "'blind_maps': 0" in SRC and "'stuck_maps': 0" in SRC)

    print()
    print('=' * 70)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：战斗收尾会查「获得新装备」；结束原因按真因分开计数/报数')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
