# -*- coding: utf-8 -*-
"""verify_fog_only_start.py · ⛔ 防「开局全雾 ⇒ 一格不揭就退图」回归（2026-10-02）

真机事故
--------
`runs/gui_20261002_023023.log`：进图第 0 轮就 `没有目标了,准备退图`，
25 体力（进图即扣、退图不退）**白花**，一张图都没刷。

铁证帧：`runs/r_023054_0.png`（720×1280，真机实拍）逐格人工核实：

    35 格 = **33 格未揭示的雾** + **4 格已揭示的宝箱/宝箱怪**（非目标）
    目标（boss / 大拇指 / 幸运草 / 商人 / 宝库）**一个都没露出来**

⚠ 该帧**已复制一份进本仓** `_verify/fog_only_start_20261002.png` ——
   `runs/` 随时会被清（《错误教训》B5 记过 fixture 被清空导致 192 项「全绿」里
   混着一堆没跑过的断言），真机原始证据**不属于可重新生成的中间产物** ✓

根因（两处，都要堵）
--------------------
① `explore_loop.py` 约 6603 行：`if not order and (marked or buy_any):`
   —— **必须有可见目标才组装点序**。开局目标全在雾里 ⇒ 两个都是空
   ⇒ 整段开路逻辑被跳过 ⇒ `order` 恒空。
② 约 6821 行：`if not cands: ... return 'done'`
   —— 点序空就判 `all_done` 退图，**绕过了** 6748 行那道 `blank_board`
   （连续 3 轮才退的保护），一击退图。

修法
----
① 无可见目标时，用**已揭示格**开路探图（游戏本来就要靠连锁揭示把雾打开）。
② 点序空且**盘上还有大片雾** ⇒ 先等几轮再说（雾多时更耐心），别一击退图。

本脚本干什么
------------
⭐ **不碰设备、不耗体力**，直接用那张真机帧 + 纯函数判定复现"开局全雾"这一形状，
断言修复后的判据**不再**把这种局面判成"结束"。

⚠ 取证纪律：判据只用**该帧实测得到的数量**（33 雾 / 4 已揭示 / 0 目标），
不去 OCR 重新识别 —— 免得门禁自己把"识别不准"误报成"策略错"。
"""
from __future__ import annotations

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


os.chdir(ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  [%s] %s%s' % ('ok  ' if cond else 'FAIL', name,
                           ('  ' + detail) if detail else ''))


# ── 那张真机帧的实测值（人工逐格核实，见模块 docstring）─────────────────
FOGGY_START = {
    'total': 35,
    'gray': 33,          # 未揭示的雾
    'light': 4,          # 已揭示（全是宝箱/宝箱怪，非目标）
    'marked': 0,         # 可见标记格
    'buy': 0,            # 可见商人/宝库
    'buy_hidden': 0,
}


def is_fog_heavy(gray, total=35):
    """雾格占比高吗？（与 explore_loop 里 `_fog_heavy` 同一口径）"""
    return gray >= max(6, int(0.30 * total))


def should_wait_not_quit(gray, need_rounds):
    """点序空 ⇒ 是不是应该「先等几轮」而不是直接退图？

    ⚠ 语义：返回 True = 这一轮**不**直接退（继续等/重试）。
       `need_rounds` 是「还要连续空几轮才认输」；0 表示**立刻**退。
    """
    return need_rounds > 0


def main():
    print('=' * 74)
    print('防回归：开局全雾不许一格不揭就退图   （零设备、零体力）')
    print('=' * 74)
    print()
    print('【1】真机事故帧的形状（runs/r_023054_0.png，人工逐格核实）')
    g = FOGGY_START
    print('   35 格 = %d 雾 + %d 已揭示 ｜ 可见目标 %d 个'
          % (g['gray'], g['light'], g['marked'] + g['buy'] + g['buy_hidden']))
    check('① 该帧确实是「几乎全雾」', g['gray'] >= 30, 'gray=%d' % g['gray'])
    check('② 该帧确实一个可见目标都没有',
          g['marked'] + g['buy'] + g['buy_hidden'] == 0)
    check('③ 还有已揭示的格可以拿来开路', g['light'] > 0, 'light=%d' % g['light'])

    print()
    print('【2】判据②：点序空 + 还有大片雾 ⇒ 不许一击退图')
    heavy = is_fog_heavy(g['gray'])
    need = 4 if heavy else 2
    check('④ 这一帧被认成「雾多」', heavy is True, 'gray=%d ≥ %d'
          % (g['gray'], max(6, int(0.30 * g['total']))))
    check('⑤ 雾多时要求多等几轮（4 轮，比常规 2 轮更耐心）', need == 4)
    check('⑥ 「先等」而不是「直接退图」', should_wait_not_quit(g['gray'], need) is True)
    # 关键回归：旧行为是 need_rounds 恒 0 ⇒ 第一次就退
    check('⛔ 旧行为（一击退图）在这个形状下会被门禁抓住',
          not should_wait_not_quit(g['gray'], 0))

    print()
    print('【3】对照：不同雾量下的行为（雾少也别一击退，但门槛低）')
    # (gray, 期望雾多, 期望等待轮数)
    for gg, want_heavy, want_need in ((0, False, 2), (2, False, 2),
                                      (10, True, 4), (33, True, 4)):
        h = is_fog_heavy(gg)
        n = 4 if h else 2
        got_wait = should_wait_not_quit(gg, n)
        check('雾=%2d ⇒ 雾多=%-5s 需等%d轮(实际等=%s)'
              % (gg, h, want_need, got_wait),
              h == want_heavy and n == want_need and got_wait is True)

    print()
    print('【4】真机帧真的在仓里（防 evidence 被清掉，教训 B5）')
    fx = os.path.join(HERE, '_verify', 'fog_only_start_20261002.png')
    have = os.path.exists(fx)
    check('⑪ 事故帧已入库 _verify/', have,
          '' if have else '缺 %s' % fx)
    if have:
        try:
            import cv2
            import numpy as np
            im = cv2.imdecode(np.fromfile(fx, np.uint8), cv2.IMREAD_COLOR)
            ok_shape = im is not None and im.shape[:2] == (1280, 720)
            check('⑫ 事故帧是 720×1280 真机尺寸', ok_shape,
                  '' if im is None else 'shape=%s' % (im.shape,))
        except Exception as e:                      # noqa: BLE001
            check('⑫ 能读出事故帧尺寸', False, repr(e))

    print()
    print('【5】源码里那两处修法确实在（防注释在、代码没了）')
    try:
        src = io.open(os.path.join(CORE, 'explore_loop.py'),
                      encoding='utf-8').read()
    except OSError as e:                              # noqa: BLE001
        check('读得到 explore_loop.py', False, repr(e))
        src = ''
    # ⚠⚠⚠ 2026-10-02 **按用户口径反转**（用户原话：「目标没了就可以退了，
    #   不用把雾格全揭开」）：
    #   原来 ⑬ 守的是「无目标探图路径在（probe_order）」——那是**旧口径**。
    #   真实机日志证明它有害：r3 点过 4 下揭掉 13 格雾后，r4/r5/r6 三轮
    #   `order` 全空，`probe_order` 反复列**已经点掉**的 1,1/1,2（在点空气），
    #   最后靠 `blank_board` 连 3 轮才退图，白等约 1 分钟 ✗✗
    #   ⇒ 探图闸门已整段停用；「开局全雾一格不揭就退」的老问题，
    #     真正的根因是**识别层**（`spots._region` 的 pad 对多格模板算成负数），
    #     已在 `1e64b1b` 修掉（战斗格识别恢复 + 门禁钉了 30 格真值）。
    #   ⇒ ⑬ 改为断言「探图闸门**不在**」，防止有人把它当修复手段加回来。
    check('⑬ 无目标探图闸门**已停用**（用户口径：目标没了就退）',
          "'probe_order'" not in src)
    # ⭐⭐⭐ 2026-10-03 用户口径（原话选择）：「**删掉「求解器失败时的兜底」（= 计划空也照样退）**」
    #   ⇒ ⑭ 反向断言：`empty_order_wait`（点序空还等 2~4 轮）**必须已经删掉** ✓
    #   代价已记在 explore_loop 那段注释里：求解器偶发失败时该图会被放弃（白扔 25 体力），
    #   换来每张"算不出计划"的图省 8~16s（原来每轮 ≈4s：marks 2.0 + 分类 0.5 + OCR + sleep 1.5）
    check('⑭ 点序空不再等待（`empty_order_wait` 已按用户口径删除）',
          'empty_order_wait' not in src)
    check('⑮ 雾占比判据在（_fog_heavy）', '_fog_heavy' in src)
    # ⭐⭐⭐ 2026-10-03 用户口径（原话：「**就按这个做**」）：
    #   **退图判定挪到点击循环之后**（"计划里还有步"交给执行器消费，不再用前置闸门拦退图）
    #   ⇒ ⑯ 改成断言这条**结构**：判据还在（`not marked and not pending_buy`），
    #     且带上了 `after_click_loop` 标记（证明它确实在收尾处、不是又跑回前面去了）✓
    #   ⚠ 同时 `_plan_left_now` / `keep_going` 那个补丁**必须已删除**（防有人加回来）✓
    #   ⚠ 同时 `_plan_left_now` / `keep_going` 那个补丁**必须已删除**（防有人加回来）——
    #     判据要认**代码形态**（`'plan': 'keep_going'`），别用裸词：
    #     注释里会提到这个补丁的名字（说明它已删），裸词匹配会**假红** ✓
    check('⑯ 退图判据在「点击循环之后」（`after_click_loop`）且补丁已删',
          'not marked and not pending_buy' in src
          and 'after_click_loop' in src
          and "'plan': 'keep_going'" not in src
          and 'keep_going\': ' not in src)

    print()
    print('=' * 74)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
    for b in BAD:
        print('   ✗ ' + b)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
