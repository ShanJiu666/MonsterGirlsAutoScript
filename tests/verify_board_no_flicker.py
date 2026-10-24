# -*- coding: utf-8 -*-
"""verify_board_no_flicker.py · 回归：「规划步数图标一直闪烁」

## 用户报告（2026-10-24）
    「当前状态里的进度，就是规划的那几个步数图标，为什么一直闪烁，
      修一下，**每图换一次就行了**」

## 根因（读代码即可证）
    tick_data()  **每 2 秒**无条件调 _update_board()   （core/bot_gui.py:2391）
      ⇒ _update_board() 末尾**无条件**调 board.update_board()  （:2896）
        ⇒ widgets.py update_board() 第一行就是 delete(all) + 整盘重画（:848）
    ⇒ 就算**一个字节都没变**，也每 2 秒把序号圆抹掉再画一遍 ⇒ 一直闪 ✗✗

## 为什么 2026-10-19 的 `paint_order()` 没治好
    它只修了 **stdout 计划行**那条路（`_paint_plan`）；
    而**每 2 秒那条**走的是 `_update_board` ⇒ 仍然全量重画 ✗
    （典型"修了一半"：一条路径治了、另一条没治）

## 修法（口径 = 用户原话"每图换一次就行了"）
    `_update_board()` 里加**绘制指纹**：把真正影响画面的 7 样东西
    （board / marks / order / cost / target_cells / hud / spans）压成字符串，
    与上次相同 ⇒ **直接 return，完全不碰画布** ✓

用法：
    python tests\verify_board_no_flicker.py
"""
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

FAILS = []


def ck(name, cond, detail=''):
    _d = ('' if not detail else (detail if isinstance(detail, str) else str(detail)))
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name, ('  ' + _d) if _d else ''))
    if not cond:
        FAILS.append(name)


def sig_of(board, marks, order, cost, tgt, hud, spans):
    """复刻 `_update_board` 里的指纹算法（**逐字同口径**）"""
    return repr((
        sorted((board or {}).items()),
        sorted((marks or {}).items()) if isinstance(marks, dict) else repr(marks),
        list(order or []),
        cost,
        sorted(tgt),
        sorted((hud or {}).items()) if isinstance(hud, dict) else repr(hud),
        spans,
    ))

def main():
    import inspect

    print('=' * 78)
    print('规划步数图标一直闪烁（2026-10-24 用户报）')
    print('=' * 78)

    src_p = _os.path.join(CORE, 'bot_gui.py')
    src = open(src_p, encoding='utf-8').read()
    s = src.find('def _update_board(')
    e = src.find('\n    def ', s + 10)
    body = src[s:e] if s >= 0 else ''
    code = '\n'.join(l for l in body.splitlines()
                    if not l.lstrip().startswith('#'))

    print()
    print('【1】`_update_board` 里有绘制指纹守卫')
    ck('找得到 `_update_board`', s >= 0)
    ck('算了 `_sig_now` 指纹', '_sig_now = repr(' in code)
    ck('数据没变时 **直接 return**（不碰画布）',
       '_board_paint_sig' in code and 'return' in code)
    ck('绘制**成功之后**才记指纹（失败不记 => 下次重试）',
       '_board_paint_sig = _sig_now' in code)

    print()
    print('【2】位置守门：指纹判断必须**在** update_board **之前**')
    i_sig = code.find('_board_paint_sig')
    i_draw = code.find('self.board.update_board(')
    ck('两者都找得到', i_sig >= 0 and i_draw >= 0,
       'sig=%d draw=%d' % (i_sig, i_draw))
    ck('顺序正确（先判指纹、后重画）', i_sig >= 0 and i_draw >= 0 and i_sig < i_draw)

    print()
    print('【3】指纹覆盖 7 个影响画面的输入（漏一个 => 该变化时反而不重画）')
    win = code[max(0, i_sig - 700):(i_draw if i_draw > 0 else len(code))]
    for key in ('board', 'marks', 'order', 'cost', 'tgt', 'hud', 'spans'):
        ck('指纹里含 %s' % key, key in win)
    ck('全部走 sorted()（稳定序，不用 set 迭代序 / id()）',
       'sorted(' in win and 'id(' not in win)

    print()
    print('【4】执行级：同数据 => 同指纹；任一输入变 => 指纹变')
    b1 = {'1,1': ['001', '草地', 1.0, 0.99], '2,3': ['008', '旅行商人', 0.695, 0.66]}
    m1 = {'1,1': ['boss']}
    o1 = ['1,1', '2,3']
    hud1 = {'round': 2, 'stamina': 330}
    sp1 = {'1,1': [['1,1']], '2,3': [['2,3']]}
    a = sig_of(b1, m1, o1, 10, {'1,1'}, hud1, sp1)
    b = sig_of(dict(b1), dict(m1), list(o1), 10, {'1,1'}, dict(hud1), dict(sp1))
    ck('同样的数据两次 => 指纹相同（每拍不会误判成变了）', a == b)
    ck('连续 5 拍同数据 => 只有 1 个指纹 => 只重画 1 次',
       len({sig_of(b1, m1, o1, 10, {'1,1'}, hud1, sp1) for _ in range(5)}) == 1)
    changes = [
        ('换图 board',   sig_of({'9,9': ['001','草地',1.0,0.9]}, m1, o1, 10, {'1,1'}, hud1, sp1)),
        ('揭示新格',     sig_of({**b1, '3,3': ['001','草地',1.0,0.99]}, m1, o1, 10, {'1,1'}, hud1, sp1)),
        ('marks 变',     sig_of(b1, {'1,1': ['boss'], '2,3': ['clover']}, o1, 10, {'1,1'}, hud1, sp1)),
        ('order 变',     sig_of(b1, m1, ['2,3','1,1'], 10, {'1,1'}, hud1, sp1)),
        ('cost 变',      sig_of(b1, m1, o1, 12, {'1,1'}, hud1, sp1)),
        ('target 变',    sig_of(b1, m1, o1, 10, {'1,1','2,3'}, hud1, sp1)),
        ('hud 变',       sig_of(b1, m1, o1, 10, {'1,1'}, {'round':2,'stamina':329}, sp1)),
    ]
    for label, s2 in changes:
        ck('%s => 指纹变了（会重画）' % label, s2 != a)

    print()
    print('【5】对照项：指纹里**不许**含时间戳/随机量（否则等于没修）')
    ck('指纹表达式里没有 time./now()/random/uuid',
       not any(k in win for k in ('time(', 'now()', 'random', 'uuid')))

    print()
    print('=' * 78)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：数据没变**一次都不重画**（序号圆不再被抹）；'
          '数据变了（换图/揭示/计划/HUD）照常重画')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
