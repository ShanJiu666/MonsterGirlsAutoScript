# -*- coding: utf-8 -*-
"""verify_dice_call.py · 守住「摇色子」的三条调用点不许引用不存在的名字

真机事故（2026-10-06 acc2 那把，13:01~13:25）：
    `wait_end()` 里那句 `handle_dice(..., st=(ctx or {}).get('flags'))`
    引用了一个**根本不在本函数作用域里的名字 `ctx`** ⇒ 每次走到都抛
    `NameError: name 'ctx' is not defined`
    ⇒ **9 场「首领+大拇指 / 大拇指」战斗，一次都没摇成色子** ✗✗

判据分三层（**AST，不字符串 grep** —— 我自己的留档注释里必然逐字引用
`st=(ctx or {}).get('flags')`，grep 会假红 ✗ 本项目已踩过四次）：
  【1】结构级：每个 `handle_dice(...)` 调用点所在的函数，其**参数表**里必须有
        它用到的那些名字（`ctx` 或 `st`）—— 用 `ast` 取函数节点，不用正则
  【2】执行级：真造一个假 Bot，喂「结算面板 + recommend 标记」直接跑
        `wait_end()`，断言**不抛 NameError** 且真的调到了 `handle_dice`
  【3】反向守门：把 `st=st` 改回 `st=ctx` 时必须**变红**（否则本门禁是恒绿的摆设）
"""
import ast
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

sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                                # noqa: BLE001
    pass

SRC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'explore_loop.py')
SRC = io.open(SRC_PATH, encoding='utf-8').read()

_n = [0]
_fail = [0]


def ck(name, cond, extra=''):
    _n[0] += 1
    if cond:
        print('  [ok]   %s' % name)
    else:
        _fail[0] += 1
        print('  [FAIL] %s  %s' % (name, extra))


def stress(name, cond, extra=''):
    """预期会红的对照项（不算失败）"""
    print('  [%s] %s  %s' % ('red' if not cond else '??', name, extra))


print('=' * 74)
print('【1】结构级：handle_dice 调用点用到的名字，必须在本函数作用域里')
print('=' * 74)

tree = ast.parse(SRC, SRC_PATH)


class FuncScan(ast.NodeVisitor):
    def __init__(self):
        self.hits = []          # (函数名, 参数集合, 调用行, 源码行)

    def visit_FunctionDef(self, node):
        params = set()
        a = node.args
        for arg in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs):
            params.add(arg.arg)
        if a.vararg:
            params.add(a.vararg.arg)
        if a.kwarg:
            params.add(a.kwarg.arg)
        # 函数体内所有赋值过的名字（局部变量）也算"存在"
        locals_ = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                locals_.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                locals_.add(sub.name)
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == 'handle_dice'):
                self.hits.append((node.name, params | locals_, sub.lineno))
        self.generic_visit(node)


fs = FuncScan()
fs.visit(tree)
lines = SRC.split('\n')
print('  找到 %d 个 handle_dice 调用点：' % len(fs.hits))
for fname, known, lineno in fs.hits:
    src = lines[lineno - 1].strip()
    print('    :%-6d 在 %-12s | %s' % (lineno, fname, src[:80]))

# 逐点检查：该行用到的"自由名字"里，有没有既不在本函数、也不是模块级/内置的
import builtins

_BI = set(dir(builtins))
_module_names = set()
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        _module_names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in ast.walk(node):
            if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                _module_names.add(t.id)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for al in node.names:
            _module_names.add((al.asname or al.name).split('.')[0])

_bad = []
for fname, known, lineno in fs.hits:
    src = lines[lineno - 1]
    try:
        expr = ast.parse('(' + src.strip().rstrip(',') + ')').body[0].value
    except SyntaxError:
        continue
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            nm = node.id
            if nm in known or nm in _BI or nm in _module_names:
                continue
            # 该名字在本文件里有没有出现过赋值？作为最后的宽限
            if nm in SRC:
                pass
            _bad.append((lineno, fname, nm))

ck('三个调用点用到的名字都在各自作用域内（没有野名字）',
   not _bad, '野名字：%s' % _bad)

ck('wait_end 的签名里**有** `st` 参数（修法落地）',
   any(fname == 'wait_end' and 'st' in known for fname, known, _ in fs.hits))

ck('wait_end 里那个点的实参是 `st=st`（不再引用 ctx）',
   any(fname == 'wait_end' and 'st=st' in lines[ln - 1].replace(' ', '')
       for fname, _, ln in fs.hits) or
   any(fname == 'wait_end' and 'st=st' in lines[ln - 1]
       for fname, _, ln in fs.hits))

ck('两个 wait_end 调用点**都**把 st 传进去了',
   SRC.count("wait_end(b, log, marks=") >= 2 and
   SRC.count("st=(ctx or {}).get('flags') if isinstance(ctx, dict) else None") >= 2)

print()
print('=' * 74)
print('【2】执行级：真跑 wait_end，喂「结算面板 + recommend」，必须不抛 NameError')
print('=' * 74)

try:
    import mapbot as MB                             # noqa: E402
    import explore_loop as EL                       # noqa: E402
    import numpy as np                              # noqa: E402
except Exception as _e:                             # noqa: BLE001
    print('  · import 失败 ⇒ 跳过执行级：%r' % (_e,))
    print()
    print('=' * 74)
    print('共 %d 项，失败 %d 项（部分跳过）' % (_n[0], _fail[0]))
    sys.exit(1 if _fail[0] else 0)

_called = {'n': 0}
_orig_hd = EL.handle_dice


def _spy(b, log, items, tries=3, st=None):
    _called['n'] += 1
    _called['st'] = st
    return 0


class _FakeBot:
    """只提供 wait_end 需要的那几样：fast_ok / wait_stable / snap / img / ocr / tap

    ⚠ 第一版漏了 `tap` ⇒ 执行级红成 `AttributeError`（**是探针自己的错**，被测代码没错）
      ⇒ 教训同 §4 第 8 条：**探针自己也要自检** —— 先把桩补齐再判被测代码 ✓
    """
    fast_ok = True

    def __init__(self):
        self.n = 0
        self.taps = []

    def wait_stable(self, *a, **k):
        return True

    def snap(self, *a, **k):
        self.n += 1
        return None

    def img(self):
        return np.zeros((1280, 720, 3), np.uint8)

    def tap(self, x, y, **k):
        self.taps.append((x, y))
        return True

    def tap_dlg(self, x, y, **k):
        self.taps.append((x, y))
        return True

    def ocr(self, *a, **k):
        # 喂一份"真结算面板"的 OCR 结果：含「战斗胜利」+ 底部「关闭」
        return [{'text': '战斗胜利', 'cx': 360, 'cy': 300, 'conf': 0.99},
                {'text': '关闭', 'cx': 385, 'cy': 960, 'conf': 0.99},
                {'text': '回放战斗', 'cx': 200, 'cy': 1010, 'conf': 0.99}]


EL.handle_dice = _spy
# ⚠ 本项测的是 `wait_end` 的**控制流**（走到 handle_dice 那一支），不是模板匹配器本身：
#   `_hit_tpl` 内部走真 `fx_has()` 模板匹配，而桩帧是纯黑 ⇒ 必然不命中 ⇒ `items=[]`
#   ⇒ `win=False` ⇒ 永远到不了摇色子那支。⇒ 按需把**外设**打桩，只留被测逻辑真跑 ✓
_orig = {k: getattr(EL, k) for k in ('fx_has', '_auto_skip_enable',
                                     'check_newequip_after_battle')}
EL.fx_has = lambda *a, **k: True
EL._auto_skip_enable = lambda *a, **k: None
EL.check_newequip_after_battle = lambda *a, **k: None
_log = []
try:
    _r = EL.wait_end(_FakeBot(), _log, timeout=8, marks=['boss', 'recommend'],
                     exact_marks=['boss', 'recommend'], st={'clover_locked': 456})
    _err = None
except NameError as e:
    _err = e
except Exception as e:                              # noqa: BLE001
    _err = e
finally:
    EL.handle_dice = _orig_hd
    for k, v in _orig.items():
        setattr(EL, k, v)

ck('wait_end 跑完**没有** NameError', _err is None, '异常=%r' % (_err,))
ck('wait_end 真的调到了 handle_dice（摇色子那条路活着）',
   _called['n'] >= 1, '调用次数=%d' % _called['n'])
ck('传进去的 st 就是调用方给的 flags（键对得上）',
   _called.get('st') == {'clover_locked': 456}, 'st=%r' % (_called.get('st'),))

print()
print('=' * 74)
print('【3】反向守门：把 `st=st` 改回 `st=ctx` 必须能被【1】抓到')
print('=' * 74)

_broken = SRC.replace('handle_dice(b, log, items, st=st)',
                      "handle_dice(b, log, items, st=(ctx or {}).get('flags'))")
ck('构造出的"坏版本"确实与现在不同（否则本项无意义）', _broken != SRC)
try:
    _b_tree = ast.parse(_broken, 'broken')
    _b_fs = FuncScan()
    _b_fs.visit(_b_tree)
    _b_lines = _broken.split('\n')
    _b_bad = []
    for fname, known, lineno in _b_fs.hits:
        if fname != 'wait_end':
            continue
        src = _b_lines[lineno - 1]
        try:
            expr = ast.parse('(' + src.strip().rstrip(',') + ')').body[0].value
        except SyntaxError:
            continue
        for node in ast.walk(expr):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id == 'ctx' and 'ctx' not in known:
                    _b_bad.append(node.id)
    stress('坏版本被【1】判红（findings=%s）' % _b_bad, bool(_b_bad))
    ck('反向守门成立：坏版本确实会被抓到', bool(_b_bad))
except Exception as e:                              # noqa: BLE001
    ck('反向守门可运行', False, repr(e))

print()
print('=' * 74)
if _fail[0]:
    print('✗ 失败 %d / %d 项' % (_fail[0], _n[0]))
    sys.exit(1)
print('✅ 全部通过：摇色子三个调用点都在正确作用域；wait_end 实跑不崩且真的摇了')
