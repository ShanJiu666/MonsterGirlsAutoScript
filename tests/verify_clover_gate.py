# -*- coding: utf-8 -*-
"""verify_clover_gate.py · 回归：**幸运草 < 8 就不摇色子**（用户口径）

用户 2026-10-05 原话（先 5 后改 8）：
    「**扫体力数值的时候顺便扫一下幸运草数值？如果幸运草低于5，这张图就不摇色子怎么样**」
    「**改成幸运草低于8就不摇色子吧**」

真机背景（`runs/acc3`，幸运草只剩 1 的那几张图）：
  点四叶草 ⇒ 游戏**不弹确认框** ⇒ 那道"没弹框就不点确定"的闸门跳掉这一圈
  ⇒ 白点 2 次、日志只写 `dice: no_dlg_skip` ⇒ **真因（幸运草不足）被掩盖** ✗

修法：判据从"猜框在不在"改成**确定性的"钱够不够"** ——
  · `clover_count(items)`：从**体力那一行的同一次 OCR** 里读幸运草（**零额外成本** ✓）
  · `handle_dice()` 开头：`< CLOVER_MIN_REROLL(8)` ⇒ **一次都不点，直接返回 0** ✓
  · 读不到 ⇒ **不猜、照常走**（保守：一次 OCR 失败不该导致永远不摇 ✓）

真机实测位置（6 帧，cx 恒定 462~463 / cy=59）：
    帧        幸运草   大拇指        帧        幸运草   大拇指
    17:54       3        0          19:12       2        0
    19:10       7        0          19:13       1        0
    19:11       5        0          19:14       1        0
  ⇒ 这 6 张**全部 < 8** ⇒ 按用户口径**都不该摇** ✓

牙齿：把闸门去掉 / 阈值改错 ⇒ 本门禁必红 ✓
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


sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import explore_loop as EL
    print('=== 幸运草 < 10 就不摇色子 ===')

    # ── ① 阈值（用户 2026-10-09：「**幸运草阈值都改成10**」）──────────
    print()
    print('【1】阈值 = 10（用户口径）')
    ck('`CLOVER_MIN_REROLL == 10`', int(EL.CLOVER_MIN_REROLL) == 10,
       '实际 %s（2026-10-09 用户：幸运草阈值都改成10 ✓）' % EL.CLOVER_MIN_REROLL)
    ck('⭐ 与宝箱怪闸门**同为 10**（用户要求统一 ✓）',
       int(EL.CLOVER_MIN_REROLL) == int(EL.MIMIC_CLOVER_MIN),
       '摇色子=%s 宝箱怪=%s' % (EL.CLOVER_MIN_REROLL, EL.MIMIC_CLOVER_MIN))

    # ── ② 读数判据：只认 HUD 那一段、去 `+`、不看别的数字 ────────────
    print()
    print('【2】`clover_count` 读数判据（真机位置 cx 462~463 / cy 59）')
    cases = [
        ([{'text': '1949/2100', 'cx': 224, 'cy': 62}], None,
         '只有体力 ⇒ 读不到 ⇒ None（**不猜** ✓）'),
        ([{'text': '441031', 'cx': 434, 'cy': 26},
          {'text': '1', 'cx': 463, 'cy': 59}], 1, '真机那把 ⇒ 1'),
        ([{'text': '3', 'cx': 462, 'cy': 59}], 3, '上面那张 ⇒ 3'),
        ([{'text': '7', 'cx': 463, 'cy': 59}], 7, '19:10 那张 ⇒ 7'),
        ([{'text': '1+', 'cx': 473, 'cy': 59}], 1, 'OCR 把 `+` 粘进来 ⇒ 仍读 1（去 `+` ✓）'),
        ([{'text': '441031', 'cx': 434, 'cy': 26}], None,
         '金币 6 位数（x=434 区间外）⇒ **不会误取** ✓'),
        ([{'text': '8365', 'cx': 587, 'cy': 26}], None, 'x=587 区间外 ✓'),
        ([{'text': '0', 'cx': 604, 'cy': 59}], None,
         'x=604 = **小鱼干**（用户 2026-10-05 纠正：右手边那个是**小鱼干**，'
         '不是大拇指 ✗）⇒ 区间外 ✓'),
        ([{'text': '12', 'cx': 470, 'cy': 59}], 12, '两位数 ⇒ 12'),
        # ⭐⭐⭐⭐ 2026-10-08 修：**草图标被 OCR 粘在数字上**（真机三帧实测）
        #   取证 `runs/spec_dev/acc3_all/clover_hud.png`（草 = 4 / 12 / 287）
        #   ⇒ 原来要求纯数字 ⇒ `isdigit()` 拒掉 ⇒ 返回 None ⇒ **闸门失效** ✗
        ([{'text': '4 Φ', 'cx': 473, 'cy': 59}], 4,
         '**草图标粘上**（真机 `4 Φ`）⇒ 仍读 4 ✓'),
        ([{'text': '12 ±', 'cx': 473, 'cy': 59}], 12,
         '草图标粘上（真机 `12 ±`）⇒ 仍读 12 ✓'),
        ([{'text': '287Φ', 'cx': 473, 'cy': 59}], 287,
         '⚠ **三位数也照粘**（真机 `287Φ`）⇒ 仍读 287 ✓'),
        # ⚠ 反向守门：**中间**有杂字的**不许**当数字（那是体力 `1949/2100` ✗）
        ([{'text': '1949/2100', 'cx': 473, 'cy': 59}], None,
         '⚠ 体力那种 `1949/2100` ⇒ **不许**截成 1949（中间杂字 ⇒ 整条放弃）✓'),
    ]
    for items, want, name in cases:
        got = EL.clover_count(items)
        ck('%-56s ⇒ %s' % (name, want), got == want, '实际 %s' % got)

    # ── ③ 真机帧：6 张全部 < 8 ⇒ 全部该跳过 ─────────────────────────
    print()
    print('【3】真机 6 帧实测（应与人眼一致，且都 < 8）')
    import glob
    import cv2
    import numpy as np
    import mapbot as MB
    # ⚠ 基准帧**必须放在 `_verify/`**（`runs/` 是 gitignore 的 ⇒ 新克隆下来门禁会静默跳过 = 没牙齿 ✗）
    #   `_verify` 里没有时才回落到 `runs/`（本机开发时两边都在 ✓）
    fr = sorted(glob.glob(os.path.join(HERE, '_verify', 'clover_*.png')))
    if len(fr) < 3:
        fr = sorted(glob.glob(os.path.join(HERE, 'runs', 'acc*', 'r_*.png')))[-6:]
    if len(fr) < 3:
        print('      （基准帧不足 ⇒ 跳过本段）')
    else:
        got = []
        for p in fr:
            im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            b = MB.Bot.__new__(MB.Bot)
            b._img_arr = im
            b._last = None
            b._img_path = None
            b.fast_ok = True
            b.runs = os.path.dirname(p)
            b.t = {'snap': 0, 'ocr': 0, 'wait': 0, 'wait_n': 0, 'tap': 0, 'ocr_n': 0}
            b.ocr_grabs = False
            it = b.ocr(min_conf=0.3, band=(0, 100), tag='gate_clover')
            n = EL.clover_count(it)
            got.append((os.path.basename(p), n))
        print('      读数：%s' % got)
        ck('每帧都读出了幸运草（不是 None）', all(n is not None for _f, n in got),
           str([f for f, n in got if n is None]))
        # ⚠ 2026-10-09 阈值 8→10 ⇒ 判据改成**跟常量比**（不写死数字 ✓）
        #   （写死就会在下次改阈值时假红 —— 本轮 8→10 正是这么被抓出来的 ✓）
        ck('这 6 帧**全部 < %d** ⇒ 全都不该摇（与真机现象吻合 ✓）' % EL.CLOVER_MIN_REROLL,
           all(n < EL.CLOVER_MIN_REROLL for _f, n in got), str(got))

    # ── ④ 闸门在"点四叶草之前"（否则还是白点）──────────────────────
    print()
    print('【4】闸门位置：必须在**第一次点四叶草之前**')
    src = open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def handle_dice(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    code = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
    i_gate = code.find('skip_low_clover')
    i_tap = code.find("b.tap(_btn[0], _btn[1]")
    ck('有 `skip_low_clover` 闸门', i_gate >= 0)
    ck('它在**第一次点四叶草之前**（否则还是会白点 ✗）',
       i_gate >= 0 and i_tap >= 0 and i_gate < i_tap,
       'gate@%d tap@%d' % (i_gate, i_tap))
    ck('闸门里 `return 0`（一次都不点 ✓）',
       'return 0' in code[i_gate:i_gate + 700])
    ck('跳过后**记日志 + 说清楚**（真因要能在日志里看到 ✓）',
       "'skip_low_clover'" in code and '这张图不摇色子' in code)
    ck('读不到幸运草时**照常走**（`is not None` 判断，不因一次 OCR 失败永远不摇 ✓）',
       '_cv_now is not None and _cv_now < CLOVER_MIN_REROLL' in code)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：阈值=%d（2026-10-09 用户「幸运草阈值都改成10」）；'
          '读数只认 HUD 那个位置（不误取金币/大拇指）；'
          '6 张真机帧全部 < %d；闸门在点四叶草之前、读不到时不猜'
          % (EL.CLOVER_MIN_REROLL, EL.CLOVER_MIN_REROLL))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
