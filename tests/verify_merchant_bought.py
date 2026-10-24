# -*- coding: utf-8 -*-
"""verify_merchant_bought.py · 回归：「商人明明买完了，还要去点一下」

## 用户报告（2026-10-24）
    「**为什么第三张图和第四张图的两个商人，明明买完了，还要去点一下？**」

## 真机证据（`runs/acc2/loop/loop_log.json`，设备 20000，22:50）
    #104 board `3,2` = `008 旅行商人` **score=0.695** ratio=0.66
    #128 {"bought_rec":[168,908],"cell":"3,2"}      ← 买完 4 档，记住了
    #131 {"bought_done_pruned":1,"kept":[]}          ← ★ 下一轮**把记忆删了**
    ⇒ 记忆没了 ⇒ 不再受"买完不放回"保护 ⇒ 又进目标 ⇒ 又点开 ✗
    （map 3 的 `5,7` score=0.669 同样复发 ✓）

## 两个叠加的 bug
### ① 同一个概念写了两套判据
    · `cells_of()`（收 buy 列表）：score >= 0.85 **or** `_buy_top_self(v)`
    · `vault_px_now()`（判记忆该不该删）：**只认** score >= 0.85
    ⇒ 0.695 的商人「进 buy 时算、判记忆时不算」⇒ 记忆被删 ⇒ 反复点 ✗
    修：抽 `_cell_is_strong_buy(v)`，**两处调同一个函数**

### ② `merchant_done` 是个**只写不读的死集合**
    写入：`st.setdefault('merchant_done', set()).add(...)`（"买完不放回"那段）
    读取：**全仓零处** ⇒ 对行为零影响 ✗
    修：在 buy 列表的**汇聚点**按它过滤（与金币闸门同位置）

用法：
    python tests\verify_merchant_bought.py
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

def main():
    import inspect
    import explore_loop as EL

    print('=' * 78)
    print('商人买完还要再点（2026-10-24 用户报）')
    print('=' * 78)

    # ---- ① 共用语词存在 ----
    print()
    print('【1】抽出了共用语词 `_cell_is_strong_buy`，且 `cells_of` / `vault_px_now` **都调它**')
    ck('`explore_loop._cell_is_strong_buy` 存在', hasattr(EL, '_cell_is_strong_buy'))
    ck('`cells_of` 调它（不再内联表达式）',
       '_cell_is_strong_buy' in inspect.getsource(EL.cells_of))
    ck('`vault_px_now` 调它（不再只认 score）',
       '_cell_is_strong_buy' in inspect.getsource(EL.vault_px_now))

    # ---- ② 撤回守门：不许退回"只认 score" ----
    print()
    print('【2】⛔ 撤回守门：`vault_px_now` 里**不许**再出现裸的 score 门槛')
    src_v = inspect.getsource(EL.vault_px_now)
    code_v = '\n'.join(l for l in src_v.splitlines() if not l.lstrip().startswith('#'))
    _bare = 'float(v.get(' + chr(39) + 'score' + chr(39) + ') or 0) < BUY_SCORE_MIN'
    ck('代码行里没有裸的 score 门槛（必须走 _cell_is_strong_buy）',
       _bare not in code_v)
    ck('仍保留 `strong_only` 开关（`_blocked_px` 等调用方行为不变）',
       'strong_only' in code_v)

    # ---- ③ 执行级：真机那两种分数必须判 True ----
    print()
    print('【3】⭐⭐ 执行级：真机那个 0.695 / 0.669 的商人必须判 **strong=True**')
    real = [
        ('map2 3,2 旅行商人', {'score': 0.695, 'name': '旅行商人',
                              'top': [[0.695, 'S10003_008'], [0.34, 'S00003_001'],
                                      [0.30, 'S00003_002']]}),
        ('map3 5,7 旅行商人', {'score': 0.669, 'name': '旅行商人',
                              'top': [[0.669, 'S10003_008'], [0.33, 'S00003_001']]}),
        ('宝库（高分）',      {'score': 0.999, 'name': '黄金宝库',
                              'top': [[0.999, 'S10003_016'], [0.40, 'S00003_001']]}),
    ]
    for label, v in real:
        ck('%s ⇒ strong=True' % label, EL._cell_is_strong_buy(v) is True,
           'score=%.3f top_self=%s' % (v['score'], EL._buy_top_self(v)))

    # ---- ④ ⚠ 对照项：误报必须仍被拒（证明不是"恒 True"）----
    print()
    print('【4】⚠⚠ 对照项：**误报不许变 True**（证明放宽不是恒真）')
    bad = {'score': 0.600, 'name': '旅行商人',
           'top': [[0.600, 'S10003_008'], [0.55, 'S00003_001']]}
    ck('低分 + top-gap 只有 0.05（实测误报区间 0.054~0.255）⇒ strong=False',
       EL._cell_is_strong_buy(bad) is False,
       'gap=%.3f' % (0.600 - 0.55))
    ck('拿不到 top ⇒ 退回老判据（0.60 < 0.85 ⇒ False）',
       EL._cell_is_strong_buy({'score': 0.600, 'name': '旅行商人'}) is False)
    ck('拿不到 score 也不崩（返回 False）',
       EL._cell_is_strong_buy({}) is False)

    # ---- ⑤ merchant_done 必须真被读 ----
    print()
    print('【5】⛔ `merchant_done` 不再是死集合：源码里必须**既有写也有读**')
    ap = _os.path.join(CORE, 'explore_loop.py')
    src_all = open(ap, encoding='utf-8').read()
    code_all = '\n'.join(l for l in src_all.splitlines()
                             if not l.lstrip().startswith('#'))
    n_write = code_all.count("setdefault('merchant_done'")
    n_read = code_all.count("st.get('merchant_done')")
    ck('有**写入**点（买完记进去）', n_write >= 1, 'n=%d' % n_write)
    ck('有**读取**点（过滤 buy 列表）', n_read >= 1, 'n=%d' % n_read)
    ck('读取点在 `one_round` 里（buy 汇聚点）',
       "_mdone = st.get('merchant_done')" in code_all)
    ck('过滤时用 `cell_of()` 把像素换成格号（merchant_done 存的是元组）',
       'cell_of(*p) not in _mdone' in code_all)

    print()
    print('=' * 78)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：商人/宝库的强匹配判据**只有一份**（cells_of 与 vault_px_now 同源）；'
          '真机 0.695/0.669 的商人判 True、误报仍判 False；merchant_done 有读点了')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
