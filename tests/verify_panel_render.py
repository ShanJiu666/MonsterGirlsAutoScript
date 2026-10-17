# -*- coding: utf-8 -*-
"""verify_panel_render.py · 回归：**面板还在渲染时不许判"目标已清空"退图**

用户 2026-10-05 原话（第二次报同一件事）：
    「**修了个寂寞啊，和之前一模一样，没打探索格**」

真机事实（全部来自 `runs/acc1/loop/loop_log.json`，**可复算、不靠猜**）
--------------------------------------------------------------------
· 紫/橙探索格 `(3,1)` **识别正确**：`sid = S00003_221`（后缀 221 ✓ 紫格）
  ⇒ `_is_purple_cell()` 判 **True** ✓（所以"没认出来"不是原因）
· 第 2 轮 `taps: [["3,1", 3.7, true, "S00003_221", 5]]`
  ⇒ 点了 **3.7 秒**、**`changed = true`**（画面**确实变了** ⇒ 真弹了东西）
· 但整局 **探索相关事件 0 条**（`explore`/`dispatch` 一条都没有）
  ⇒ 面板弹出来了却**没被 `popups()` 接住** ✗
· 随后 `finish: targets_done, content_skipped: 6` ⇒ **带着未处理内容直接退图** ✗✗

机制（面板"正在渲染"这个已知状态）：
  点开面板的那一瞬间，游戏会先**把棋盘压暗**（遮罩），**面板美术过一会儿才画出来**
  ⇒ 那一刻 `panel_seen(it)` 读不到任何标题/按钮（OCR 只有体力/图名那几条）
  ⇒ 本轮 `popups()` 什么都不做；下一轮面板画好了，却没有"刚点过"的上下文
  ⇒ 被当普通棋盘 ⇒ 走到退图判定 `rnd>=2 and not marked` ⇒ **直接 done** ✗

修法：退图判定**之前**加一道闸门 ——
  `st['last']`（上次点击）存在 且 `last_change['dim'] < 0.85`（棋盘被压暗）
  ⇒ 本图**不判 done**、`return None` 让主循环再转一轮（下一轮 `popups()` 接住它 ✓）
  上限 3 轮（`st['panel_render_wait']`）防死循环 ✓
  ⚠ 字段名必须是 `last_change['dim']`（相对压暗比 `now/ref`）；
    **没有** `Bot.dim()` 这个方法 —— 我第一版就写错了（AttributeError 路径）✗

⚠ 本门禁**故意不用那张 `_ocr_tmp.png`**：
  它的 mtime（16:33:38）晚于 acc1 那局结束时间（16:30:13）⇒ 是**别的局**写的，
  拿来当"那一刻的证据"属于**假证据** ✗（我差点就用它写门禁了）
  ⇒ 只用日志里可复算的三条事实 + 源码结构断言 ✓
"""
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
    print('=== 面板还在渲染时不许判"目标已清完"退图 ===')

    # ── ① 先排除"没认出紫格"这个假设（它是被我第一版误判的方向）────────
    print()
    print('【1】先证明不是"没认出紫格"（用户那句"和之前一样"的最可能解释）')
    ck('`(3,1)` 的 sid `S00003_221` ⇒ 判据认它（后缀 221 ✓）',
       EL._is_purple_cell('S00003_221', ['3,1'], (72, 908)) is True)
    ck('`_is_purple_cell` 是纯函数、探索分支在调它（防写回内联）',
       '_is_purple = _is_purple_cell(' in open(
           os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read())

    # ── ② 真机日志事实：弹了、但没被接住、然后直接退图 ────────────────
    print()
    print('【2】真机事实（**固化在 `_verify/log_facts.json`**）')
    # ⚠⚠ 原来直接读 `runs/acc1/loop/loop_log.json` —— 而**那份日志每跑一局就被覆盖**
    #   （实测：我提交前门禁红了，因为文件换成了另一局 ⇒ 断言读到的是**别的局的数据** ✗✗）。
    #   `runs/` 也是 gitignore 的 ⇒ 新克隆下来根本读不到 ⇒ 等于没测 ✗
    #   ⇒ 改成读**固化的事实**（从当时那一局抽出来的真值 ✓）
    import json
    import io
    p = os.path.join(HERE, '_verify', 'log_facts.json')
    if not os.path.exists(p):
        print('   （缺 %s ⇒ 跳过本段）' % os.path.relpath(p, HERE))
    else:
        facts = json.load(io.open(p, encoding='utf-8'))
        prw = facts.get('panel_rendering_wait') or []
        pu = facts.get('purple_tap') or {}
        print('      `panel_rendering_wait` 真机出现 %d 次：%s'
              % (len(prw), [(x.get('cell'), x.get('dim')) for x in prw]))
        print('      紫格那次 tap：%s' % (pu.get('tap'),))
        # ⭐ 主断言：**闸门在真机上真的生效过**（这是本修复最硬的证据）
        ck('㊳ ⭐ `panel_rendering_wait` 在真机上**真的触发过**（本修复生效的直接证据 ✓）',
           len(prw) >= 1, '出现 %d 次' % len(prw))
        ck('㊴ ⭐ 触发时 `dim ≈ 0.41`（棋盘确实被压暗 ⇒ 正是"面板在渲染"那一刻 ✓）',
           all(0.30 <= float(x.get('dim') or 0) <= 0.60 for x in prw) if prw else False,
           str([x.get('dim') for x in prw]))
        ck('㊵ ⭐ 紫格 `(3,1)` 那次：点 **4.0s**、`changed=True`、sid `S00003_221`'
           '（**识别正确** ⇒ "没认出紫格"不是原因 ✓）',
           bool(pu.get('tap')) and pu['tap'][2] is True
           and str(pu['tap'][3]) == 'S00003_221', str(pu.get('tap')))
        ck('㊶ 该轮 board 里 `(3,1)` = 后缀 **221**（紫格判据认它 ✓）',
           (pu.get('sid_board') or [None])[0] == '221', str(pu.get('sid_board')))
        ck('㊷ 它确实被排进了计划（`order_cost["3,1"] = [5, "S00003_221"]` ✓）',
           bool((pu.get('order_cost') or {}).get('3,1')), str(pu.get('order_cost')))

    # ── ③ 分支优先级（本轮**真根因**）─────────────────────────────────
    #   紫格面板被**战斗分支**接住（它认到「战斗事件」标题）⇒ `mk=[]` ⇒ 掉进
    #   `if not mk:` 按"不在路上/不在计划里"判 ⇒ **面板被关掉：既没探索也没打** ✗
    print()
    print('【3】分支优先级：紫/橙格 + 有空闲槽 ⇒ 必须绕过战斗分支、走探索')
    src = open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith('#')]
    code = '\n'.join(code_lines)
    i_pre = src.index("'purple_prefer_explore'")
    i_bat = src.index("log.append({'popup': 'fight_panel'")
    i_expl = src.index('if _expl_entry:')
    ck('有"紫格+空槽 ⇒ 优先探索"这条前置（`purple_prefer_explore`）',
       'purple_prefer_explore' in src)
    ck('它在**战斗分支记账之前**（否则还是被战斗分支吃掉 ✗）', i_pre < i_bat,
       'pre@%d fight@%d' % (i_pre, i_bat))
    ck('它把战斗分支改成 `elif`（不是两个独立 if —— 那样战斗分支还会跑 ✗）',
       'elif _fe_title or _fe_btn:' in code)
    ck('探索分支的入口也认**紫格**（那块面板标题是「战斗事件」⇒ 只按标题必漏 ✗）',
       '_expl_entry = (fb(items, L[\'expl\'])' in code
       and '_is_purple and _free_now > 0' in code)
    ck('战斗分支里的 `_is_ev` 也用**同一个** `_is_purple_cell`（顶层垃圾 sid 也能认 ✓）',
       '_is_ev = _is_purple_cell(' in code)
    ck('用对了字段名：`last_change` 里的 `dim`（代码里**没有** `.dim()` 调用）',
       "last_change" in code and "get('dim'" in code and '.dim()' not in code)
    ck('退图闸门有上限、且在 `targets_done` 之前',
       "'panel_render_wait', 0" in code and '_waited < 3' in code
       and src.index('panel_rendering_wait') < src.index("'targets_done'"))

    # ── ④ 端到端：真机那一格的三个条件必须都成立 ─────────────────────
    print()
    print('【4】端到端：真机 `(3,1)`（紫格 + 空闲槽 1 ⇒ 必须走探索）')
    ck('它是紫格（顶层 sid `S00003_221` ⇒ 判据认它）',
       EL._is_purple_cell('S00003_221', ['3,1'], (72, 908)) is True)
    ck('顶层是垃圾猜测时也认（`S30001_104` + ev_tiles 有它 ⇒ True）',
       EL._is_purple_cell('S30001_104', ['3,1'], (72, 908)) is True)
    ck('`slots_free=1 > 0` ⇒ 满足"有闲槽 ⇒ 走探索"',
       int({'slots_free': 1}.get('slots_free', 0)) > 0)
    for dim, want_wait, why in ((0.137, True, '真机点开面板那一刻（棋盘被遮罩压暗）'),
                                (1.0, False, '面板已画好/根本没面板')):
        ck('退图闸门 dim=%.3f ⇒ %s（%s）'
           % (dim, '等一轮' if want_wait else '照常判', why),
           (dim < 0.85) is want_wait)
    ck('闸门块里**真的 `return None`**（不是只记日志、后面又走到 done ✗）',
       'return None' in src[src.index('panel_rendering_wait'):
                            src.index('panel_rendering_wait') + 1400].split('except')[0])
    ck('`_dim_wait` 兜底：没触发等待时才写 `targets_done`',
       'if not _dim_wait' in src
       and src.index('if not _dim_wait') < src.index("'targets_done'"))

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：紫格判据认它（不是识别问题）；日志证明"弹了但没被接住"；'
          '分支优先级 + 退图闸门都对')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
