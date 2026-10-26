# -*- coding: utf-8 -*-
"""verify_multiblock_name.py · 回归：「很多空地看成巨大沙堡」

## 用户报告（2026-10-26）
    「还有第一张图怎么把很多空地看成巨大沙堡什么的了？」（帧 runs/r_191220_0.png）

## 病（逐格 top5 铁证，实测）
    那张帧上 6 格标「巨大沙堡」：(3,1)(3,2)(3,3)(3,4)(4,1)(5,1)
    但 block_score=None / anchor=None / cells=[只有自己] ⇒ **不是块采纳，是单格 top1**
    分数 0.117~0.260（**全低于块门槛 0.28**）；该格 top5 全是 211 的多个变体，
    第 4~5 名才是 301/302 —— 而 301/302/101/221/321 **全是多格块**
    ⇒ 该格**没有任何单格模板**能认 ⇒ 「巨大沙堡」纯属噪声
    对照（真沙堡帧 runs/r_195513_0.png）：4 格 block_score=0.586 / anchor=(2,1) ⇒ 块通道 ✓

## 修法
    判据 = 「该格没被任何块采纳」+「top1 sid 是多格块」+「分数 < MULTI_BLOCK_MIN(0.28)」
    ⇒ **名字置空**（认不出 ≠ 认错）
    ⚠⚠ **只置空 name**：sid/eff/ratio/revealed/anchor/cells 一个都不动
       （第一版改「重新挑 top1」⇒ eff 变 ⇒ ratio 分母变 ⇒ 1095 帧实测
        ratio 变 2817 格 / revealed 变 620 格 / 名字清空 9613 格 ✗✗ 已撤回）

用法：
    python tests\verify_multiblock_name.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
CORE = os.path.join(ROOT, 'core')
for _p in (CORE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    os.chdir(ROOT)
except OSError:
    pass
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=""):
    _d = ("" if not detail else (detail if isinstance(detail, str) else str(detail)))
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name, ('  ' + _d) if _d else ''))
    if not cond:
        FAILS.append(name)


def _frame(name):
    """取一张真机帧（不存在就跳过该项）"""
    p = os.path.join(ROOT, 'dist', 'MGAS-v1.0-portable', 'runs', name)
    if not os.path.exists(p):
        return None
    try:
        import cv2
        import numpy as np
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:       # noqa: BLE001
        return None
    return im


def main():
    import inspect
    import spots as SP

    print('=' * 78)
    print('多格块在「单格通道」不许显示名字（2026-10-26 用户报：巨大沙堡）')
    print('=' * 78)

    src = open(os.path.join(CORE, 'spots.py'), encoding='utf-8').read()

    print()
    print('【1】结构级：判据写在哪、动了什么')
    ck('有多格块名字置空的判据', 'MULTI_BLOCK_MIN' in src and '_multi_sids()' in src)
    ck('⛔ 判据含「没被块采纳」(blk is None)', 'blk is None' in src)
    ck('⛔ 判据含「分数 < 块门槛」（否则满分真地块被清空 ✗）',
       'float(v) < MULTI_BLOCK_MIN' in src)
    ck('⛔ 只置空 name：sid/eff/ratio/revealed 不许被改',
       "'name': _nm" in src)
    # ⚠⚠ 必须用 **AST** 判（不是字符串 grep）——
    #   留档注释里**必然**逐字引用旧写法 ⇒ grep 必假红 ✗
    #   （本仓已栽过这个坑多次：v1.62c / v1.67 / 本轮 ✓）
    #   ⚠ 也不能用变量名挑（如 `_pick`）—— `spots.py` 里**原本就有**同名变量
    #     （`_frame_picks` 那段，:348）⇒ 会撞名误判 ✗（本轮真踩）
    import ast
    _tree = ast.parse(src)
    _top1_ok = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Assign):
            continue
        _v = _n.value
        # 形如 `v, sid, _fi, _off = lst[0]` ⇒ 右边是 `lst[0]`
        if not (isinstance(_v, ast.Subscript)
                and isinstance(_v.value, ast.Name) and _v.value.id == 'lst'):
            continue
        if not (isinstance(_v.slice, ast.Constant) and _v.slice.value == 0):
            continue
        for _tg in _n.targets:
            # ⚠ 元组解包 `v, sid, _fi, _off = lst[0]` ⇒ target 是 **Tuple** 不是 Name ✗
            _names = (_tg.elts if isinstance(_tg, ast.Tuple) else [_tg])
            for _nm in _names:
                if isinstance(_nm, ast.Name) and _nm.id == 'sid':
                    _top1_ok.append(getattr(_n, 'lineno', -1))
    ck('⭐⭐ top1 仍然是 `lst[0]`（不许「重新挑」）⇒ eff/ratio/revealed 不变 ✓',
       len(_top1_ok) >= 1, '行号 %s' % _top1_ok[:3])
    ck('⛔ 不许新增 SINGLE_NAME_MIN 这种独立阈值（与块门槛同源即可）',
       'SINGLE_NAME_MIN' not in src)

    print()
    print('【2】执行级：假沙堡帧（用户指的那张）')
    im = _frame('r_191220_0.png')
    if im is None:
        skip('r_191220_0.png', '夹具不存在')
    else:
        bd = SP.Board('S00003')
        st = bd.state(im)
        sand = [k for k, v in st.items() if '沙堡' in str(v.get('name') or '')]
        ck('⚠⚠ 假沙堡帧：**不再有**任何格显示「巨大沙堡」',
           not sand, repr(sand))
        ck('那 6 格仍在盘上（只是**认不出**，不是消失）',
           all(k in st for k in [(3, 1), (3, 2), (3, 3), (3, 4), (4, 1), (5, 1)]))
        ck('⚠⚠ 那些格的名字是**空串**（不是 None ⇒ 下游 `in name` 不炸）',
           all(isinstance(st[k].get('name'), str) and not st[k]['name']
               for k in [(3, 1), (3, 2), (3, 3), (3, 4), (4, 1), (5, 1)]))
        ck('⛔ sid 保持不变（技术判定不受影响）',
           all(st[k].get('sid') == 'S00003_211'
               for k in [(3, 1), (3, 2), (3, 3), (3, 4)]) or
           all((st[k].get('sid') or '').startswith('S00003_')
               for k in [(3, 1), (3, 2), (3, 3), (3, 4)]))
        ck('⛔ ratio 仍在（已揭示判定不受影响）',
           all(st[k].get('ratio') for k in [(3, 1), (3, 2), (3, 3)]))

    print()
    print('【3】对照项：真沙堡帧（同一张图上的真沙堡必须还在）')
    im2 = _frame('r_195513_0.png')
    if im2 is None:
        skip('r_195513_0.png', '夹具不存在')
    else:
        st2 = bd.state(im2)
        sand2 = [k for k, v in st2.items() if '沙堡' in str(v.get('name') or '')]
        ck('⭐⭐ 真沙堡帧：**4 格**仍显示「巨大沙堡」',
           len(sand2) == 4, repr(sand2))
        ck('⭐⭐ 真沙堡走的是**块通道**（block_score ≥ 0.28）',
           all(float(st2[k].get('block_score') or 0) >= 0.28 for k in sand2))
        ck('⭐⭐ 真沙堡帧**没有任何**格名字被清空（零误伤）',
           not [k for k, v in st2.items() if not v.get('name')])

    print()
    print('【4】⭐⚠⚠ 对照项：满分真地块不许被清空（1095 帧实测抓到的漏点）')
    ck('判据含分数条件 ⇒ 满分(≥0.28)的多格块**保留** ✓',
       'float(v) < MULTI_BLOCK_MIN' in src)

    print('=' * 78)
    if FAILS:
        print('FAIL %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('全部通过：多格块在单格通道且分数不够时**显式认不出**（不再乱猜「巨大沙堡」）；'
          'sid/ratio/revealed 一个不动 ⇒ 技术判定零变化')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
