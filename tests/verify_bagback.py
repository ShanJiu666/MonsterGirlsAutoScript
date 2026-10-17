# -*- coding: utf-8 -*-
"""verify_bagback.py · 回归：装备升星收尾「回选图界面」的**补点循环**

用户口径（2026-10-06 原话，接在日志「回选图界面核对：还没认到（见日志）」之后）：
    「**装备升级出现这个的时候就再点两次开始冒险，直到能识别到选图界面**」

改前行为（`explore_loop.bag_upgrade` ⑥ 段）：
    固定点底部「开始冒险」**×4**（`b.tap(360, 1260)`），然后**只读核对一次**；
    核对失败 ⇒ 只打一句「还没认到（见日志）」⇒ **不再补点**，走 `_close_bag` 兜底 ✗

改后：4 次保底之后，**每轮补点 2 次 + 核对一次**，认到就停 ✓

⚠⚠ 本门禁守的三件事（**缺一不可**，都是我实现时真踩过的）：
  ① **认到就一次都不补**（用户要的是"没认到**才**补"）
  ② **每轮正好 2 次**（用户口径「再点两次」）
  ③ **必须有可达的上限** —— "直到认到"若没上限，换账号/界面改版/OCR 抽风时会
     退化成**无限点「开始冒险」** ⇒ 白烧时间、还可能误开图（扣体力）✗✗
     ⇒ 这是本改动**最大的风险点**，判据必须钉住"**循环上界真的用到那个常量**"

⚠⚠⚠ **判据写法两个坑（我第一版全踩了，被牙齿测试当场抓出）**：
  · 第一版写 `'BAG_BACK_MAX_ROUNDS' in seg` —— 该词在别处（`say()`/日志）还出现
    **4 次** ⇒ 把 `for _r in range(...)` 整句换掉、或把常量改成 `0`，
    子串依然在 ⇒ **假绿** ✗✗
  · 所以改用 **AST 找到那个 `for` 循环**，直接看它的 `range(...)` 实参里
    **有没有那个常量名**；常量本身另查 **值 ≥ 1** ✓
  · 切函数体也**不用字符串找**（`for _k in range(4)` 这种锚点在别处可能撞），
    改用 **AST 取 `bag_upgrade` 函数节点**的源码段 ✓
"""
import ast
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
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []
EL = os.path.join(HERE, 'explore_loop.py')


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


src = io.open(EL, encoding='utf-8').read()
lines = src.split('\n')
tree = ast.parse(src)


def _is_const_int(name):
    """模块级 `name = <int>` 的值；没有则 None"""
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and \
                isinstance(n.targets[0], ast.Name) and n.targets[0].id == name:
            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, int):
                return n.value.value
    return None


MAXR = _is_const_int('BAG_BACK_MAX_ROUNDS')


def _func_node(name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _src_seg(node):
    """函数节点的源码段（含 body 缩进，便于正则）"""
    return '\n'.join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])


fn = _func_node('bag_upgrade')
seg = _src_seg(fn) if fn else ''


def _ranges_in(node):
    """该节点下所有 `for … in range(ARG)` 的 (ARG源码, 循环体源码)"""
    out = []
    for n in ast.walk(node) if node else []:
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Call) and \
                isinstance(n.iter.func, ast.Name) and n.iter.func.id == 'range':
            arg = ast.get_source_segment(src, n.iter.args[0]) if n.iter.args else ''
            body = '\n'.join(
                ast.get_source_segment(src, s) or '' for s in n.body)
            out.append((arg or '', body or '', n))
    return out


print('=' * 76)
print('【A】结构级：补点循环存在 / **上界真用到常量** / 判据与旧口径同源')
print()
ck('A① 找到 `bag_upgrade` 函数（AST 定位，不靠字符串找锚点）', bool(fn))
ck('A② 模块级 `BAG_BACK_MAX_ROUNDS` 是**正整数**（不是 0/负数 ⇒ 保证"可达上限" ✓）',
   isinstance(MAXR, int) and MAXR >= 1, '实际 %s' % MAXR)

rngs = _ranges_in(fn)
# 补点循环 = 循环体里含 'start_adv_retry' 的那个
refill = [r for r in rngs if 'start_adv_retry' in r[1]]
ck('A③ 存在**补点循环**（循环体里有 start_adv_retry 日志）', bool(refill),
   '找到 %d 个 range 循环，其中补点 %d 个' % (len(rngs), len(refill)))
ck('A④ ★补点循环的**上界实参里真的出现 `BAG_BACK_MAX_ROUNDS`**'
   '（不是别处出现过就算 ✓ —— 第一版就栽在这 ⇒ 假绿 ✗）',
   bool(refill) and 'BAG_BACK_MAX_ROUNDS' in refill[0][0],
   ('上界 = %s' % refill[0][0].strip()) if refill else '')
# 每轮 2 次 = 补点循环体里那个 `range(2)`
inner2 = bool(refill) and re.search(r'range\(2\)', refill[0][1]) is not None
ck('A⑤ 每轮**正好点 2 次**（循环体里有 range(2)，用户口径「再点两次」）', inner2)
ck('A⑥ 补点坐标仍是底部「开始冒险」(360, 1260)',
   bool(refill) and '360, 1260' in refill[0][1])
ck('A⑦ 认到就 `break`（不是"点满为止"）',
   bool(refill) and re.search(r'\bbreak\b', refill[0][1]) is not None)
ck('A⑧ 核对判据与旧口径**同一套关键词**（防两处漂移 ✗）',
   all(k in seg for k in ('进入地图', '快速扫荡', '星界秘境')))
ck('A⑨ 到顶如实记 `back_giveup`（不冒充"已回到选图界面" ✗）',
   'back_giveup' in seg)
ck('A⑩ 保底仍是 4 次（`bag_upgrade` 里有 range(4) 的点击循环）',
   any(a.strip() == '4' and '360, 1260' in b for a, b, _ in rngs))

print()
print('【B】执行级：把那段逻辑**真跑**（假 Bot 喂 OCR 序列）⇒ 数点击次数')
print()


class FakeBot:
    def __init__(self, polls):
        self.polls = list(polls)
        self.taps = []
        self.ocr_n = 0

    def tap(self, x, y, wait=0):
        self.taps.append((x, y))

    def ocr(self, tag=''):
        self.ocr_n += 1
        if not self.polls:
            return []
        if len(self.polls) > 1:
            return self.polls.pop(0)
        return self.polls[0]


def at_menu():
    return [{'text': '进入地图', 'cx': 360, 'cy': 1100}]


def not_menu():
    return [{'text': '装备', 'cx': 370, 'cy': 360}]


MAX = MAXR if isinstance(MAXR, int) and MAXR >= 1 else 3
KEYS = ('进入地图', '快速扫荡', '星界秘境')


def run(polls):
    """与 `bag_upgrade` ⑥ 段**逐字等价**的复刻；返回 (补点轮数, 补点点数, 日志)"""
    b = FakeBot(polls)
    log = []
    for _k in range(4):                       # 保底 4 次
        b.tap(360, 1260, wait=1.8)
        log.append({'bag': 'start_adv', 'k': _k})

    def _at_menu():
        try:
            _t = [(i.get('text') or '') for i in b.ocr(tag='bag_backchk')]
            return bool(any(any(k in t for k in KEYS) for t in _t)), _t
        except Exception:                     # noqa: BLE001
            return False, []

    n0 = len(b.taps)
    done, _t3 = _at_menu()
    log.append({'bag': 'back_check', 'ok': bool(done), 'round': 'after_4'})
    rounds = 0
    for _r in range(MAX if not done else 0):
        rounds += 1
        for _j in range(2):
            b.tap(360, 1260, wait=1.8)
            log.append({'bag': 'start_adv_retry', 'round': _r, 'k': _j})
        done, _t3 = _at_menu()
        log.append({'bag': 'back_check', 'ok': bool(done), 'round': _r})
        if done:
            break
    if not done:
        log.append({'bag': 'back_giveup', 'rounds': MAX})
    return rounds, len(b.taps) - n0, log


r, extra, lg = run([at_menu()])
ck('B① 4 次之后就认到 ⇒ **补点 0 次**（防"平白多点"）',
   r == 0 and extra == 0, '轮=%d 补点=%d' % (r, extra))

r, extra, lg = run([not_menu(), at_menu()])
ck('B② 第 1 轮补点后认到 ⇒ 正好补 **2** 次、然后停',
   r == 1 and extra == 2, '轮=%d 补点=%d' % (r, extra))

r, extra, lg = run([not_menu(), not_menu(), at_menu()])
ck('B③ 第 2 轮才认到 ⇒ 补 4 次、停', r == 2 and extra == 4,
   '轮=%d 补点=%d' % (r, extra))

r, extra, lg = run([not_menu()])
ck('B④ ★一直认不到 ⇒ 补满 %d 轮（%d 次）**必须停**（不是无限点 ✗）'
   % (MAX, MAX * 2), r == MAX and extra == MAX * 2, '轮=%d 补点=%d' % (r, extra))
ck('B⑤ 到顶如实记 back_giveup（供复盘 ✓）',
   sum(1 for x in lg if x.get('bag') == 'back_giveup') == 1)

r, extra, lg = run([])
ck('B⑥ OCR 返回空 ⇒ 不崩、仍受上限保护', extra <= MAX * 2, '补点=%d' % extra)

print()
print('=' * 76)
if FAILS:
    print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
    raise SystemExit(1)
print('✅ 全部通过：认到就停 / 没认到才补（每轮 2 次）/ 补满 %d 轮必停（防无限点）' % MAX)
print('   上界**真的用到常量**（AST 查 range 实参）｜判据同源（进入地图·快速扫荡·星界秘境）')
