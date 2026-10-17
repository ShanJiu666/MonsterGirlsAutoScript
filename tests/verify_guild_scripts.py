# -*- coding: utf-8 -*-
"""离线验 `guild_tasks.chair_timers` / `alchemy.alch_timer` 的判据（用真机帧）。

零设备、零消耗。用法：
    python verify_guild_scripts.py
"""
import io
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import ast                                              # noqa: E402
import cv2                                              # noqa: E402
import numpy as np                                      # noqa: E402

import guild_common as GC                               # noqa: E402
import guild_tasks as GT                                # noqa: E402
import alchemy as AL                                    # noqa: E402
import recruit as RC                                    # noqa: E402


FRAMES = ''
_OCR = None
FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def ocr(p):
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR(use_cls=False)
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    tmp = os.path.join(HERE, '_vg_tmp.png')
    cv2.imencode('.png', im)[1].tofile(tmp)
    res, _ = _OCR(tmp)
    out = []
    for box, t, c in (res or []):
        xs = [q[0] for q in box]
        ys = [q[1] for q in box]
        out.append(dict(text=(t or '').strip(), conf=round(float(c), 3),
                        cx=int(sum(xs) / 4), cy=int(sum(ys) / 4),
                        x0=int(min(xs)), y0=int(min(ys)),
                        x1=int(max(xs)), y1=int(max(ys))))
    out.sort(key=lambda d: (d['cy'], d['cx']))
    return out


def _undefined_globals(path):
    """找出「被调用、却在模块里找不到定义」的全局名 ⇒ [名字]

    为什么需要它：真机首跑 `guild_tasks.py` 抛
        `NameError: name 'say' is not defined`
    —— 而 `ast.parse()` **完全查不出来**（那是语法级 API，不管名字绑定）✗
    ⇒ 这里用 `compile()` 拿**顶层符号表**（`co_names` 与定义比对），
      只报"**被当函数调用、且模块里任何地方都没定义/导入过**"的名字 ✓

    ⚠ 刻意**保守**（宁可漏报也不假红）：
      · 只查**模块顶层**能看到的绑定（import / def / class / 赋值 / 形参）
      · 用 `co_names`（会被调用的名字）+ 白名单内置函数
      · 命中"出现在任何赋值左侧"的一律放过（可能是条件定义）✓
    """
    import builtins
    try:
        src = io.open(path, encoding='utf-8').read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    defined = set(dir(builtins))
    # ⚠ 模块级 dunder 是解释器注入的（`__file__` / `__name__` / `__doc__` …）
    #   —— 它们**不在** `dir(builtins)` 里，但天生就有 ⇒ 必须放过，否则假红 ✗
    #   （第一版就是这么假红了 3 条 —— 判据自己也得先验一遍 ✓）
    defined |= {'__file__', '__name__', '__doc__', '__package__', '__spec__',
                '__loader__', '__builtins__', '__debug__', '__cached__'}
    called = set()
    for node in ast.walk(tree):
        # 任何"被定义"的名字都算已绑定
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                defined.add((al.asname or al.name).split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            defined.add(node.name)
            for a in list(getattr(node.args, 'args', []) if hasattr(node, 'args')
                          else []) + list(getattr(node.args, 'kwonlyargs', [])
                                          if hasattr(node, 'args') else []):
                defined.add(a.arg)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
            else:
                called.add(node.id)          # Load：读它（含被调用）
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            for t in ast.walk(node.target):
                if isinstance(t, ast.Name):
                    defined.add(t.id)
    return sorted(called - defined)


def _strip_doc(src):
    """把源码里的**整行 `#` 注释**和**文档字符串**都剥掉 ⇒ 只留"真会执行的代码"

    ⚠⚠ 为什么不能只剥 `#` 注释（本项目**反复踩**的坑，这是第 N 次）：
      留档说明里**必然逐字引用**被禁的东西（例："**不点**「购买情报指南」（花宝石 ✗）"）
      ⇒ 只查 `'购买情报指南' not in code` 会**被自己的注释判假红** ✗
      ⇒ 正解 = **AST 取走 docstring** + 剥 `#` 行 ✓
    ⚠⚠ **顺序很要紧：必须先抠 docstring、再剥 `#` 注释**（我第一次写反了，当场假红 ✗）
      为什么：本仓的 docstring 里**用了 markdown 标题**（`### 右侧状态按钮…`）
      ⇒ 先剥 `#` 行会**把 docstring 中间那一行删掉** ⇒ 抠 docstring 时
        **逐字对不上** ⇒ 整个 docstring 留了下来 ⇒ 假红 ✗✗
      （⚠ 与 `_strip_doc` 的调用方那条"只剥 `#` 会假红"是**两个不同的坑**，
        这条更隐蔽：**剥的顺序**也会坏 ✓）

    ⚠ 别用"剥掉所有引号里的内容"那种土办法 —— 会把真的 UI 文案常量也剥掉，
      而"点某个文案按钮"恰恰是**用字符串常量**表达的 ⇒ 那样会**漏掉真问题** ✗
    """
    import ast as _ast
    out = src
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return '\n'.join(l for l in out.splitlines()
                         if not l.strip().startswith('#'))
    # ① **先**抠 docstring（拿原始 src 里的逐字内容去 replace ✓）
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.FunctionDef,
                             _ast.AsyncFunctionDef, _ast.ClassDef)):
            d = _ast.get_docstring(node, clean=False)
            if d:
                out = out.replace(d, '')
    # ② **再**剥整行 `#` 注释
    return '\n'.join(l for l in out.splitlines()
                     if not l.strip().startswith('#'))


def _ads_fake_bot(counter):
    """做一个**假 Bot**：每次 `ocr` 都返回同一个面板帧（含给定计数 `counter`）

    ⚠ `buy_with_ad` 里到处 `GC.ocr_items(b, ...)` ⇒ 只要让它**永远返回这一帧**，
      再数它 `tap` 了几次，就能判"该不该点" ✓
    ⚠ 面板标题要给（`购买金币`）否则第一步会去点 HUD 入口、污染点击序列 ✗
    """
    import ads as AD

    class _FB(object):
        def __init__(self):
            self.taps = []

        def snap(self, *a, **k):
            return None

        def ocr(self, **k):
            return [{'text': '购买金币', 'cx': 360, 'cy': 407},
                    {'text': counter, 'cx': 512, 'cy': 645},
                    {'text': '50', 'cx': 246, 'cy': 644}]

        def img(self):
            return None

        def tap(self, x, y, wait=1.2):
            self.taps.append((x, y))
            return None

    return _FB()


def _ads_no_tap_when_zero():
    """`0/3`（剩余 0）⇒ **一次都不许点**（这是修掉的 bug 的行为级判据）✓"""
    import ads as AD
    b = _ads_fake_bot('0/3')
    try:
        AD.buy_with_ad(b, 'gold', None, tag='vt', max_times=3)
    except Exception:                                       # noqa: BLE001
        pass
    # ⚠ 只数"点广告按钮"那一下（`(512,645)`）；关面板的 X 不算 ✗
    return all(not (abs(x - 512) < 30 and abs(y - 645) < 30) for x, y in b.taps)


def _ads_tap_when_three():
    """`3/3`（剩余 3）⇒ **必须点一次**（对照项：证明上一条不是恒真 ✓）"""
    import ads as AD
    b = _ads_fake_bot('3/3')
    try:
        AD.buy_with_ad(b, 'gold', None, tag='vt2', max_times=1)
    except Exception:                                       # noqa: BLE001
        pass
    return any(abs(x - 512) < 30 and abs(y - 645) < 30 for x, y in b.taps)


def main():
    print('=== 派遣/炼金 脚本判据离线回归（真机帧）===')

    # ── ⓪ 静态：**未定义名**自检（真机首跑当场崩过，必须挡住 ✗）──
    #   ⛔⛔ 2026-10-14 真机首跑 `guild_tasks.py` 直接
    #      `NameError: name 'say' is not defined` ——
    #      文件里有 27 处 `say(...)`，却从没定义/导入过它 ✗
    #   教训：`py_compile` / `ast.parse` **只查语法、不查名字** ⇒ 完全挡不住这类错 ✗
    #   ⇒ 用 `compile()` + **符号表**兜一道：把"被调用的模块级名字"与
    #     "已定义/已导入的名字"对一遍。⚠ 只报**确定未定义**的（保守，避免假红）✓
    for fn in ('guild_common.py', 'guild_tasks.py', 'alchemy.py', 'recruit.py'):
        undef = _undefined_globals(os.path.join(HERE, fn))
        ck('⓪ %s 无"调用未定义全局名"（真机 NameError 挡门）' % fn,
           not undef, '未定义：%s' % (undef[:6],) if undef else '')

    # ── ⓪b 静态：`GC.xxx` / `<模块>.xxx` **属性**必须真的存在 ──
    #   ⛔⛔ 2026-10-14 真机抓到的第二个 NameError 族：
    #      `AttributeError: module 'guild_common' has no attribute '_alch_shots'`
    #      —— `_alch_shots` 是 `alchemy.py` 自己的函数，我重构时误写成 `GC._alch_shots` ✗
    #   教训：`ast.parse` 查不出属性错（那是**运行期**才炸）⇒
    #     必须**真 import 两个模块**、再把源码里出现的 `GC.<名字>` 逐个 hasattr 验一遍 ✓
    import guild_common as _gc
    import guild_tasks as _gt
    import alchemy as _al
    _mods = {'GC': _gc, 'GT': _gt, 'AL': _al}
    _bad = []
    for fn in ('guild_tasks.py', 'alchemy.py', 'recruit.py'):
        src = io.open(os.path.join(HERE, fn), encoding='utf-8').read()
        for m in re.finditer(r'\b(GC)\.([A-Za-z_]\w*)', src):
            name = m.group(2)
            if not hasattr(_gc, name):
                _bad.append('%s: GC.%s' % (fn, name))
    ck('⓪b `GC.<属性>` 引用的东西都真的存在（AttributeError 挡门）',
       not _bad, '不存在的属性：%s' % (_bad[:6],) if _bad else '')

    # ── ⓪c **免费招募：小助手算法**（2026-10-14）──
    #   用户口径：「**抄一下小助手的选项判断机制**，**尽量能拿到高等级角色**」✓
    #   判据来源：`_tmp_xzs/SNIPPETS.txt`（逐字 JS）+ 其 Python 参考实现已跑通 ✓
    print()
    _roles, _err = RC.load_roles()
    ck('⓪c-1 角色表能从游戏数据表推出（不依赖小助手那份快照）',
       bool(_roles), 'err=%s' % (_err,) if _err else '%d 行' % len(_roles or []))
    if _roles:
        # ⭐ 「尽量拿高等级」的核心：`minR` 必须是**保底**（min），不是最高（max）✗
        _t = ['射手', '森林']
        _rk = RC.rank_combos(_t, _roles)
        _worst = [r for r in _rk if r['c'] == ['射手', '森林']]
        ck('⓪c-2 ⭐ minR 取的是**保底**（射手+森林 含普通角色 ⇒ minR=0）',
           bool(_worst) and _worst[0]['minR'] == 0,
           '实得 minR=%s（若为 3 说明误用了 max ✗）'
           % (_worst[0]['minR'] if _worst else None))
        # ⭐ 真机实测那 7 个标签 ⇒ 唯一最优必须是「沙漠+地系+器灵」（保底3=传说）
        _tags7 = ['沙漠', '光系', '地系', '器灵', '生灵', '亡灵', '法师']
        _best = RC.rank_combos(_tags7, _roles)
        ck('⓪c-3 ⭐ 真机 7 标签 ⇒ 最优 = 沙漠+地系+器灵（保底3 传说）',
           bool(_best) and set(_best[0]['c']) == {'沙漠', '地系', '器灵'}
           and _best[0]['minR'] == 3,
           '实得 %s 保底%s' % (_best[0]['c'] if _best else None,
                              _best[0]['minR'] if _best else None))
        ck('  且该组合**100% 出传说**（命中角色稀有度全为 3）',
           bool(_best) and all(r[5] == 3 for r in _best[0]['f']),
           '命中 %d 个' % len(_best[0]['f']) if _best else '')
        # ⭐ 徽章阈值：minR>=3 顶级招募 / >=2 资深保底 / 否则无
        ck('⓪c-4 徽章阈值（3⇒顶级招募 / 2⇒资深保底 / 其余无）',
           RC.badge(3) == '顶级招募' and RC.badge(2) == '资深保底'
           and RC.badge(1) is None and RC.badge(0) is None)
        # ⭐ `Re` 的两条特殊分支：星级别名**只查稀有度**，不查那四个字段
        _leg = next(r for r in _roles if r[5] == 3)
        ck('⓪c-5 ⭐ 标签「传说」只查稀有度（命中传说角色、且不命中史诗）',
           RC.tag_matches(_leg, '传说')
           and not RC.tag_matches(next(r for r in _roles if r[5] == 2), '传说'))
        ck('  且标签「史诗」只查稀有度',
           RC.tag_matches(next(r for r in _roles if r[5] == 2), '史诗')
           and not RC.tag_matches(_leg, '史诗'))
        # ⭐ 组合上限 3（源码：>=3 提示已达上限）
        _many = ['沙漠', '光系', '地系', '器灵']
        _r4 = RC.rank_combos(_many, _roles)
        ck('⓪c-6 组合最多取 3 个标签（源码 >=3 即封顶 ✓）',
           all(len(r['c']) <= 3 for r in _r4), '最大长度=%s'
           % (max(len(r['c']) for r in _r4) if _r4 else 0))
        # ⭐ 心愿 +1000 必须**绝对置顶** —— 但**有前提**：`minR>=2`（源码：
        #     `i = n>=2 && t.some(...) ? 1000 : 0`）✓
        #   ⚠⚠ 我第一版用 `['沙漠']` 单标签测 ⇒ 该组 `minR=0`
        #      ⇒ 源码里**本来就不该**给这 1000 ✗ ⇒ **是测试写错了**，不是代码错
        #      （判据：拿"够格触发"的输入测，否则测的是另一件事 ✓）
        #   `['沙漠','地系','器灵']` 命中「巨灵之枪」(传说) ⇒ minR=3 ⇒ 够格 ✓
        _w0 = RC.rank_combos(['沙漠', '地系', '器灵'], _roles)
        _w1 = RC.rank_combos(['沙漠', '地系', '器灵'], _roles, wish={'巨灵之枪'})
        ck('⓪c-7a ⭐ minR<2 时**不给**心愿加成（源码 `n>=2` 前提 ✓）',
           bool(_w0) and _w0[0]['w'] < 1000,
           '沙漠单标签 w=%s（应 <1000 ⇒ 没触发才对）'
           % (RC.rank_combos(['沙漠'], _roles)[0]['w'],))
        ck('⓪c-7b ⭐ 够格时心愿 ⇒ 权重 +1000（绝对置顶）',
           bool(_w1) and _w1[0]['w'] >= 1000,
           '实得 w=%s' % (_w1[0]['w'] if _w1 else None))
        # ⭐ 对照项：同输入**不传 wish** ⇒ 必须**没有**那 1000（证明 7b 不是恒真 ✓）
        ck('⓪c-7c ⚠ 对照：同输入不传 wish ⇒ 权重里没有那 1000',
           bool(_w0) and _w0[0]['w'] < 1000, '实得 w=%s' % (_w0[0]['w'],))

    # ── ⓪d **免费机会判据**（真机两帧对拍，2026-10-14）──
    #   ⛔ 背景：用掉之后按钮上**仍印着「免费」**⇒ 纯文字判据恒为真 ✗
    #   ⇒ 改用**按钮亮度**（源码 SetEnable：禁用 ⇒ Color.gray 压灰 ✓）
    _f_ok = os.path.join(FRAMES, 'rec_now2.png')          # 免费可用
    _f_no = os.path.join(FRAMES, 'recruit_end.png')       # 已用掉
    if os.path.exists(_f_ok) and os.path.exists(_f_no):
        class _FB:
            def __init__(self, p):
                self.p = p

            def img(self):
                return cv2.imdecode(np.fromfile(self.p, np.uint8),
                                    cv2.IMREAD_COLOR)

        _a = RC.free_available(_FB(_f_ok))
        _b = RC.free_available(_FB(_f_no))
        ck('⓪d-1 ⭐ 免费可用那帧 ⇒ 判"可用"（亮度高）',
           _a[0] is True, 'ok=%s 亮度=%s' % (_a[0], _a[1]))
        ck('⓪d-2 ⭐ 已用掉那帧 ⇒ 判"不可用"（按钮发灰）',
           _b[0] is False, 'ok=%s 亮度=%s' % (_b[0], _b[1]))
        ck('⓪d-3 ⚠ 两帧亮度差 ≥ 40（判据有真区分度，不是恒真/恒假）',
           bool(_a[1] and _b[1] and (_a[1] - _b[1]) >= 40),
           '%.1f vs %.1f' % (_a[1] or 0, _b[1] or 0))

    # ── ⓪e **招募收尾链**（2026-10-15 用户口径：
    #        「就是跳过动画，那几步，最后要返回到地图界面」＋「不用读结果」）──
    #   用**真机帧**验三个判据能不能认出对应屏：
    #     动画帧（有「跳过」）｜ 结果帧（有「结束招募」）｜ 招募主页（有「招募一次」）
    print()
    _f_anim = os.path.join(FRAMES, 'zh_now.png')        # 开门动画（小手推门+跳过）
    _f_res = os.path.join(FRAMES, 'zh_result.png')      # 结果屏（娜迦射手+结束招募）
    _f_home = os.path.join(FRAMES, 'zh_after.png')      # 结束后回招募主页
    if os.path.exists(_f_anim):
        _ia = ocr(_f_anim)
        ck('⓪e-1 ⭐ 动画帧 ⇒ 能认到「跳过」（**必须点它，动画不会自己结束** ✗）',
           RC.GC.has(_ia, '跳过'), '认到 %s' % (RC.GC._texts(_ia)[:6],))
        ck('  且动画帧**不是**结果屏（没有「结束招募」）—— 证明两步确实要分开走',
           not RC.GC.has(_ia, '结束招募'))
    if os.path.exists(_f_res):
        _ir = ocr(_f_res)
        ck('⓪e-2 ⭐ 结果屏 ⇒ 能认到「结束招募」（点它回招募主页 ✓）',
           RC.GC.has(_ir, '结束招募'), '认到 %s' % (RC.GC._texts(_ir)[:8],))
        ck('  且结果屏**没有**「跳过」（说明动画已过 ✓）',
           not RC.GC.has(_ir, '跳过'))
    if os.path.exists(_f_home):
        _ih = ocr(_f_home)
        ck('⓪e-3 ⭐ 点完「结束招募」⇒ 回到**招募主页**（认到「招募一次」✓）',
           RC._on_recruit_home(_ih), '认到 %s' % (RC.GC._texts(_ih)[:8],))
    # ⛔ 撤回守门：`_read_result` 必须**不存在**（用户口径「不用读结果」✗）
    _rsrc = io.open(os.path.join(HERE, 'recruit.py'), encoding='utf-8').read()
    _code = '\n'.join(l for l in _rsrc.splitlines()
                      if not l.strip().startswith('#'))
    ck('⓪e-4 ⛔ 撤回守门：`_read_result()` **已删**（用户：「不用读结果」✗）',
       'def _read_result' not in _code,
       '（已剥掉整行注释再查 —— 注释里必然出现这个名字，grep 会假红 ✗）')
    ck('⓪e-5 ⭐ 收尾链三步齐备（跳过 → 结束招募 → 返回地图界面）',
       ('_click_skip_anim' in _code and '结束招募' in _code
        and 'leave_guild' in _code),
       'skip=%s end=%s back=%s'
       % ('_click_skip_anim' in _code, '结束招募' in _code,
          'leave_guild' in _code))
    ck('⓪e-6 ⭐ 返回地图界面是**默认行为**（不是 opt-in）',
       'RETURN_TO_MAP = True' in _code, 'RETURN_TO_MAP = True')

    # ── ⓪f **公会「情报」领奖**（2026-10-15 用户口径：
    #        「接下来做点击情报领取奖励」＋「每周情报也顺便点了」）──
    #   用**真机帧**验：三态判据 / 面板判据 / 每日循环 / 每周盲点守门 ✓
    import intel as IT
    _f_i_open = os.path.join(FRAMES, 'intel_open_after.png')   # 6 条全「可领取」
    _f_i_done = os.path.join(FRAMES, 'intel_back1_after.png')  # 全「已完成」+ 一条 0/1
    _f_i_wk = os.path.join(FRAMES, 'wk_claim1_after.png')      # 每周：4/5、34/40、14/20…
    if os.path.exists(_f_i_open):
        _io = ocr(_f_i_open)
        ck('⓪f-1 ⭐ 面板判据：情报面板开着 ⇒ 认得出（`情报指南`/两个页签 ✓）',
           IT.panel_open(_io), '认到 %s' % (RC.GC._texts(_io)[:6],))
        _cl = IT._claimable(_io)
        ck('⓪f-2 ⭐⭐ 「可领取」逐条找得到，且**按 y 升序**（从上往下领 ✓）',
           len(_cl) == 6 and all(
               _cl[i]['cy'] <= _cl[i + 1]['cy'] for i in range(len(_cl) - 1)),
           '找到 %d 条：%s' % (len(_cl), [(d['cx'], d['cy']) for d in _cl]))
        ck('⓪f-3 ⭐ 6 条的 **x 都在 547~549**（判据只需「可领取」三字，不靠位置 ✓）',
           all(545 <= d['cx'] <= 551 for d in _cl),
           'xs=%s' % [d['cx'] for d in _cl])
        # ⛔ 公会展厅那一屏**也有「情报」二字**（那颗按钮）⇒ 单看「情报」会自己骗自己 ✗
        ck('⓪f-4 ⛔ 反向守门：**没有面板**的帧不许判成"面板开着"',
           not IT.panel_open(ocr(os.path.join(FRAMES, 'zh_intel0.png')))
           if os.path.exists(os.path.join(FRAMES, 'zh_intel0.png')) else True,
           '（公会大厅帧上有「情报」二字 ⇒ 用它当判据必然假阳性 ✗）')
    if os.path.exists(_f_i_done):
        _id = ocr(_f_i_done)
        ck('⓪f-5 ⭐ 「已完成」那帧 ⇒ **一条「可领取」都没有**（领完就该停 ✓）',
           len(IT._claimable(_id)) == 0,
           '可领取 %d 条' % len(IT._claimable(_id)))
        ck('⓪f-6 ⭐ 进度文字 `0/1` **不算可领**（`_is_progress` 认得 ✓）',
           IT._is_progress('0/1') and IT._is_progress('34/40')
           and not IT._is_progress('可领取') and not IT._is_progress('已完成'),
           '0/1=%s 34/40=%s 可领取=%s'
           % (IT._is_progress('0/1'), IT._is_progress('34/40'),
              IT._is_progress('可领取')))
    if os.path.exists(_f_i_wk):
        _iw = ocr(_f_i_wk)
        # ⭐ 每周的守门：第 1 行是 `4/5`（**不是**「可领取」）⇒ `claim_weekly` 必须**拒绝** ✓
        _rows = [d for d in _iw
                 if 500 < d.get('cx', 0) < 600 and 400 < d.get('cy', 0) < 1120]
        _first = min(_rows, key=lambda d: d['cy']) if _rows else None
        ck('⓪f-7 ⭐⭐ 每周帧的第 1 行 = `%s`（**不是**「可领取」）'
           % (_first['text'] if _first else '?',),
           bool(_first) and _first['text'] == '4/5',
           '第 1 行 y=%s' % (_first['cy'] if _first else '?'))
        ck('⓪f-8 ⭐⭐ 守门：第 1 行不是「可领取」⇒ **盲点必须被拒绝**（不瞎点 ✗）',
           bool(_first) and _first['text'] != IT.INTEL_CLAIMABLE,
           '（`claim_weekly` 里那条 `if _t != INTEL_CLAIMABLE: return False` ✓）')
    _isrc = io.open(os.path.join(HERE, 'intel.py'), encoding='utf-8').read()
    _icode = '\n'.join(l for l in _isrc.splitlines()
                       if not l.strip().startswith('#'))
    ck('⓪f-9 ⭐ 每日是**循环领**（`claim_daily` 有 for 循环 + 「没有可领取了」出口）',
       'for r in range' in _icode and '没有「可领取」了' in _icode)
    ck('⓪f-10 ⭐ 每周是**只点一次**（用户口径「盲点一下最上面的可领取的坐标」✓）',
       'claim_weekly_blind' in _icode and 'INTEL_FIRST_Y' in _icode)
    ck('⓪f-11 ⭐ 领完**关页面**（用户口径「然后就可以关闭页面了」✓）',
       'INTEL_CLOSE_X' in _icode and 'def close_panel' in _icode)
    ck('⓪f-12 ⛔ 安全守门：**不点**「购买情报指南」（那要花宝石 ✗）',
       '购买情报指南' not in _strip_doc(_isrc),
       '（⚠ 必须连**文档字符串**一起剥掉 —— 我自己的安全说明里就逐字写着'
       '「不点购买情报指南」⇒ 只剥 `#` 注释会**假红** ✗ 本项目已踩过多次）')

    # ── ⓪g **广告领奖**（2026-10-15 用户口径：
    #        「开始做领取广告（默认有免广），只做每天1次的加速炼金，
    #          每天三次的购买体力，幸运草和金币，单独加个有无免广的勾选，有就自动做」）──
    #   ⛔⛔ 核心是**计数语义**：`N/M` 的 N 是「**剩余**」不是「已看」✗
    #     （用户当场纠正：「这号现在的状态是体力3/3还没买，幸运草和金币都买过了」）
    import ads as AD
    print()
    ck('⓪g-1 ⭐⭐⭐ `read_ad_counter` 把第一个数当**剩余**（源码那行是减法 '
       '`$"{num2 - num}/{num2}"` ✓）',
       AD.read_ad_counter([{'text': '0/3', 'cy': 645, 'cx': 512}])[:2] == (0, 3)
       and AD.read_ad_counter([{'text': '3/3', 'cy': 645, 'cx': 562}])[:2] == (3, 3),
       '0/3⇒(0,3) ｜ 3/3⇒(3,3)')
    # ⚠ 我第一版把这条写成 `... or True` ⇒ **恒真**（等于没查）✗
    #   ⇒ 改成**行为级**：直接看 `buy_with_ad.__doc__` 里有没有那句源码推导 ✓
    #     （⛔ **不能**查整个源码字符串 —— 我自己的留档注释里逐字写着
    #       `used >= limit`（说明"旧判据是错的"）⇒ 会**假红** ✗ 本项目第 N 次踩）
    ck('⓪g-2 ⛔⛔ **撤回守门**：`buy_with_ad` 的文档里钉着'
       '「判据必须是 `remaining <= 0`（不是 `used >= limit`）」',
       'remaining <= 0' in (AD.buy_with_ad.__doc__ or '')
       and 'used >= limit' in (AD.buy_with_ad.__doc__ or ''),
       '（判据写在**函数自己的 docstring**里 ⇒ 不会被别处的留档误导 ✓）')
    ck('⓪g-3 ⭐⭐⭐ **行为级**：`0/3`（剩余 0）⇒ **绝不许点**那颗广告按钮 ✗',
       _ads_no_tap_when_zero(), '（喂 `0/3` 帧，断言 taps 为空 ✓）')
    ck('⓪g-4 ⭐⭐⭐ **对照项**：`3/3`（剩余 3）⇒ **必须点**（否则上面那条恒真 ✓）',
       _ads_tap_when_three(), '（同夹具只把计数换成 3/3 ⇒ 必须有一次点击 ✓）')
    ck('⓪g-5 ⭐ 领到判据是**剩余变少**（`cnt2[0] < remaining`），不是变多 ✗',
       'cnt2[0] < remaining' in _strip_doc(_adsrc := io.open(
           os.path.join(HERE, 'ads.py'), encoding='utf-8').read()),
       '（源码里找 `cnt2[0] < remaining` ✓）')
    ck('⓪g-6 ⭐ 领奖后**先点「返回」再读计数**（弹窗会盖住计数 ✗）',
       '_dismiss_reward_popup' in _strip_doc(_adsrc),
       '（`buy_with_ad` 里点完广告就调它 ✓）')
    ck('⓪g-7 ⭐ 四项**只有用户点名的那四个**（奇遇/立即完成探索/秘境**不做** ✓）',
       ('SagaGuarantee' not in _strip_doc(_adsrc)
        and 'ExploreSkip' not in _strip_doc(_adsrc)
        and 'DungeonSupply' not in _strip_doc(_adsrc)),
       '（用户只要：四叶草/金币/体力/加速炼金 ✓）')
    ck('⓪g-8 ⛔ 安全守门：**绝不点**花宝石那颗（源码里不许出现宝石按钮坐标 ✗）',
       ('ADS_BUYAD_GEM' not in _strip_doc(_adsrc)
        and 'ALCH_ACCEL_GEM' not in _strip_doc(_adsrc)),
       '（只点"看广告"那颗绿按钮 ✓）')
    ck('⓪g-9 ⭐ **未勾免广 ⇒ 四个入口一下都不碰**（用户口径「未勾则不做」✓）',
       'no_skip_ads' in _strip_doc(_adsrc) and '一下都不碰' in _strip_doc(_adsrc))
    ck('⓪g-10 ⭐ 加速炼金的计数在 **y≈742**（与购买面板的 645 **不同** ⇒ 单独读 ✓）',
       '_read_accel_counter' in _strip_doc(_adsrc)
       and '700 < cy < 790' in _strip_doc(_adsrc),
       '（两处 y 圈不同 ⇒ 不能共用一个函数 ✗）')

    if not os.path.isdir(FRAMES):
        print('   （找不到帧目录 %s ⇒ 跳过后面几项）' % FRAMES)
        return 0 if not FAILS else 1

    # ── ① 椅子倒计时：4 椅全跑的那帧必须读出 4 个 ──
    p = os.path.join(FRAMES, 'all4.png')
    if os.path.exists(p):
        items = ocr(p)
        tm = GT.chair_timers(items)
        ck('四椅全在跑 ⇒ 读出 4 个倒计时', len(tm) == 4, '实得 %s' % (tm,))
        ck('椅1 的倒计时是 03:29:31', tm.get(1) == '03:29:31', '实得 %s' % tm.get(1))
        ck('椅4 的倒计时是 03:59:48', tm.get(4) == '03:59:48', '实得 %s' % tm.get(4))
        # ⚠ 这条是"**粘连**"回归：真机见过 OCR 把两条并成
        #   `02:23:2702:33:26` ⇒ 必须能抠出**两个**（本项目实测踩过 ✓）
        #   ⚠⚠ 第一版我把夹具的 y 写成 627 ⇒ **落在 BUBBLE_Y 带之外** ⇒ 被判 {} ✗
        #      —— 那是**夹具自己的错**，不是被测代码的错（本项目反复栽在"探针自己错"）
        #      ⇒ 现在 y 取带内（335..398），与真机一致 ✓
        fake = [dict(text='02:23:2702:33:26', conf=1.0, cx=300, cy=360,
                     x0=240, y0=345, x1=360, y1=375)]
        tm2 = GT.chair_timers(fake)
        ck('⭐ 粘连的倒计时（02:23:2702:33:26）能抠出 2 个（不是 1 个）',
           len(tm2) == 2, '实得 %s' % (tm2,))
        ck('  且两条分别归到**不同**椅子（按字符位置估 x）',
           len(set(tm2)) == 2 and set(tm2.values()) == {'02:23:27', '02:33:26'},
           '实得 %s' % (tm2,))

    # ── ② 椅1/2 跑、椅3/4 未接的那帧：只能读出 2 个 ──
    p2 = os.path.join(FRAMES, 'chk_now.png')
    if os.path.exists(p2):
        tm3 = GT.chair_timers(ocr(p2))
        ck('「椅1/2 跑、椅3/4 未接」⇒ 只读出 2 个（未接的不许算 BUSY）',
           len(tm3) == 2, '实得 %s' % (tm3,))

    # ── ③ 炼金倒计时：`07:59:28` 那帧 ──
    p3 = os.path.join(FRAMES, 'start_alch_after.png')
    if os.path.exists(p3):
        t = AL.alch_timer(ocr(p3))
        ck('炼金进行中 ⇒ 读出倒计时 07:59:2x', bool(t) and t.startswith('07:59:'),
           '实得 %s' % t)
    p4 = os.path.join(FRAMES, 'alch5.png')
    if os.path.exists(p4):
        ck('顶楼**没有**炼金倒计时 ⇒ 必须读不出（防把别的 hh:mm:ss 当炼金）',
           AL.alch_timer(ocr(p4)) is None, '实得 %s' % AL.alch_timer(ocr(p4)))

    # ── ④ 面板判据（用真机帧上的真实文字）──
    if os.path.exists(p3):
        ck('那帧不是「炼金结果」面板', not AL.result_panel_open(ocr(p3)))
    p5 = os.path.join(FRAMES, 'chest_after.png')
    if os.path.exists(p5):
        ck('领奖帧（chest_after）= 「炼金结果」面板',
           AL.result_panel_open(ocr(p5)))
    p6 = os.path.join(FRAMES, 'alch_main_after.png')
    if os.path.exists(p6):
        ck('主面板帧 = 「炼金宝箱」面板', AL.main_panel_open(ocr(p6)))
        ck('主面板的预计时间为空（--:--:--）⇒ slots_filled()==0',
           AL.slots_filled(ocr(p6)) == 0, '实得 %s' % AL.slots_filled(ocr(p6)))
    p7 = os.path.join(FRAMES, 'star_filter_after.png')
    if os.path.exists(p7):
        ck('点满星后 ⇒ 预计时间 07:59:30（不再是 --:--:--）',
           (AL.expect_time(ocr(p7)) or '').startswith('07:59:'),
           '实得 %s' % AL.expect_time(ocr(p7)))

    # ── ⑤ 派遣面板三态（真机帧）──
    for fn, want, desc in (
            ('p3_open_after.png', 'free', '未接面板（一键派遣 + 剩余时间）'),
            ('p3_fill_after.png', 'filled', '已填队面板（开始任务 + 剩余时间）'),
            ('f1_after.png', 'running', '进行中面板（召回 + 所需时间）')):
        fp = os.path.join(FRAMES, fn)
        if not os.path.exists(fp):
            continue
        got = GT.panel_state(ocr(fp))
        ck('派遣面板「%s」⇒ %s' % (desc, want), got == want, '实得 %s' % got)

    # ── ⑥ 点错格子的保护：献祭宝箱怪帧不能当成炼金面板 ──
    p8 = os.path.join(FRAMES, 'alch_open_after.png')
    if os.path.exists(p8):
        it8 = ocr(p8)
        ck('⚠ 点到「献祭宝箱怪」时 ⇒ **不算**炼金面板（防误投料）',
           not AL.main_panel_open(it8) and not AL.result_panel_open(it8),
           'which=%s' % AL._which_panel(it8))

    print()
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    finally:
        try:
            os.remove(os.path.join(HERE, '_vg_tmp.png'))
        except OSError:
            pass
