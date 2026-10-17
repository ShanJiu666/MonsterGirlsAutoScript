# -*- coding: utf-8 -*-
"""verify_board_hidden.py · 回归：**被面板盖住的帧必须判成"被挡"**

用户 2026-10-05 原话：
    「**我看点开了宝库，过了会就关掉宝库了**」

真机铁证（`runs/loop/loop_log.json` 第 960 → 966 条）
-----------------------------------------------------
    960 round4：`board` **13 格**，含 `(2,6) 黄金宝库 score=1.000 ratio=0.994`
                ⇒ `order.buy=1`（计划里该去买它 ✓）
    962 round5：`ocr: skip_no_panel`（**判"无面板" ⇒ 免整屏 OCR**）
    966 round5：`board` **只剩 2 格**（`3,1` 0.743 / `5,6` 0.303）
                ⇒ `buy:0`、`gray:6` ⇒ `pending_buy` 空 ⇒ **`targets_done` 退图** ✗
    ⇒ 结果：**宝库面板开着，却没人处理它，直接退图**（= 用户看到的现象）

根因：`board_hidden()` 只看「**被压暗的格数 ≥ 15**」
    —— 而**面板盖住棋盘时分类器根本认不出几格** ⇒ 那个 `n` 天然就小
    ⇒ `n >= 15` **永远不成立** ⇒ 判"没被挡" ⇒ 免 OCR ⇒ 面板没人处理 ✗✗
    （该函数 docstring 那张实测表是"面板遮住时还能认出 32 格"的年代 —— 识别层收紧后前提失效 ✗）

修法：补一条 **`len(st) < BOARD_MIN_CELLS(8)` ⇒ 也算被挡** ✓
    方向安全：多判"被挡"只会**多跑一次 OCR**，绝不漏面板 ✓

本门禁（离线，用真机两帧的 `board` 复现）
"""
import json
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
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _c_from_board(bd):
    """把 loop_log 里的 board 还原成 `cells_of` 的 c 结构（board_hidden 只读这些）"""
    st = {}
    for k, v in (bd or {}).items():
        try:
            rc = tuple(int(x) for x in str(k).split(','))
        except Exception:                       # noqa: BLE001
            continue
        st[rc] = {'ratio': float(v[3]) if len(v) > 3 else None}
    light = [1 for v in st.values() if (v.get('ratio') or 0) >= 0.85]
    gray = [1 for v in st.values() if (v.get('ratio') or 0) < 0.85]
    return {'st': st, 'light': light, 'gray': gray}


def main():
    import explore_loop as EL
    print('=== 被面板盖住的帧必须判成"被挡"（用户：「点开了宝库，过了会就关掉宝库了」）===')

    # ── ① 阈值存在、方向安全 ────────────────────────────────────────
    print()
    print('【1】判据：认出的格数太少也算被挡（`BOARD_MIN_CELLS`）')
    ck('`BOARD_MIN_CELLS` 存在', hasattr(EL, 'BOARD_MIN_CELLS'),
       '实际 %s' % getattr(EL, 'BOARD_MIN_CELLS', None))
    ck('阈值 = 8（真机：干净盘 35 格 / 部分揭开 13~26 / 被遮 2 格 ⇒ 落在两簇中间 ✓）',
       int(getattr(EL, 'BOARD_MIN_CELLS', 0)) == 8,
       '实际 %s' % getattr(EL, 'BOARD_MIN_CELLS', None))
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def board_hidden(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    body = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
    ck('`board_hidden` 里真的用了它（不是只定义常量 ✗）',
       'len(_st) < BOARD_MIN_CELLS' in body)

    # ── ② 真机两帧：被遮的必须 True、正常的必须 False ────────────────
    #   ⚠⚠ **基准数据必须固化**（`_verify/board_hidden_cases.json`）——
    #     原来直接读 `runs/loop/loop_log.json`，而**那个文件每跑一局就被覆盖**
    #     （实测：我提交前那次门禁就因为文件被新一局覆盖 ⇒ 条目少 ⇒ **IndexError** 假红 ✗✗）
    #     `runs/` 本来也是 gitignore 的 ⇒ 新克隆下来根本读不到 ⇒ 等于没测 ✗
    print()
    print('【2】真机两帧（固化在 `_verify/board_hidden_cases.json`）')
    p = os.path.join(HERE, '_verify', 'board_hidden_cases.json')
    if not os.path.exists(p):
        print('      （缺 %s ⇒ 跳过本段）' % os.path.relpath(p, HERE))
    else:
        cases = json.loads(open(p, encoding='utf-8').read())
        bd_ok = (cases.get('960') or {}).get('board') or {}
        bd_hid = (cases.get('966') or {}).get('board') or {}
        o_ok = (cases.get('960') or {}).get('order') or {}
        o_hid = (cases.get('966') or {}).get('order') or {}
        c_ok, c_hid = _c_from_board(bd_ok), _c_from_board(bd_hid)
        print('      条目 960（%d 格，含黄金宝库，order.buy=%s）⇒ board_hidden=%s'
              % (len(bd_ok), o_ok.get('buy'), EL.board_hidden(c_ok)))
        print('      条目 966（%d 格，面板盖住，order.buy=%s）  ⇒ board_hidden=%s'
              % (len(bd_hid), o_hid.get('buy'), EL.board_hidden(c_hid)))
        ck('**被面板盖住那帧**（2 格）⇒ 判 True（修复前 False ⇒ 免 OCR ⇒ 漏面板 ✗）',
           EL.board_hidden(c_hid) is True)
        ck('**正常那帧**（13 格，有宝库）⇒ 判 False（不许误判成被挡 ✗）',
           EL.board_hidden(c_ok) is False)
        ck('同帧对比也钉住：960 认到宝库（`order.buy=1`）而 966 丢了（`buy=0`）'
           '—— 这正是用户报的"打开宝库就关了、根本没购买" ✓',
           int(o_ok.get('buy') or 0) == 1 and int(o_hid.get('buy') or 0) == 0)

    # ── ③ 反向断言：干净盘 / 部分揭开的盘都不许被误判 ───────────────
    print()
    print('【3】反向断言：正常盘（含"格数偏少"的正常盘）不许被误判')
    cases = [
        ('干净盘 35 格（ratio 合理）',
         {tuple((i // 7 + 1, i % 7 + 1)): {'ratio': 0.99 if i % 3 else 0.65}
          for i in range(35)}, False),
        ('部分揭开 13 格（真机 960 那帧）', None, False),
        ('极少数格 2 格（真机 966 那帧）', None, True),
        ('只有 7 格（阈值之下）',
         {tuple((i // 7 + 1, i % 7 + 1)): {'ratio': 0.99} for i in range(7)}, True),
        ('刚好 8 格（阈值边界 ⇒ 不算被挡）',
         {tuple((i // 7 + 1, i % 7 + 1)): {'ratio': 0.99} for i in range(8)}, False),
    ]
    for name, st, want in cases:
        if st is None:
            continue
        c = {'st': st,
             'light': [1 for v in st.values() if v['ratio'] >= 0.85],
             'gray': [1 for v in st.values() if v['ratio'] < 0.85]}
        got = EL.board_hidden(c)
        ck('%-34s ⇒ %s' % (name, want), got is want, '实际 %s' % got)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：被面板盖住的帧（格数极少）判"被挡"⇒ 本轮会真 OCR + 调 popups() '
          '⇒ 宝库面板不会再被漏掉；正常盘不受影响')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
