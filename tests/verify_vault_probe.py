# -*- coding: utf-8 -*-
"""★ 回归：宝库「第二层乱点」的**两个真根因**（2026-10-10）

用户报：「**第二层乱点了好几次才正常买上**」＋「**就不该点开详情页**」

⛔ 根因 A：`_probe_name` 里 **`log` 未定义** ⇒ "收起详情"那步**从没执行** ✗
   （签名 `(bot, at, wait)`，`log` 走全局查找而模块里没有 ⇒ NameError ⇒ 被 `except: pass` 吞）
   ⇒ 详情页一直盖着 ⇒ `_btn(it2)` 读不到按钮 ⇒ `#55 src='stale_pos'` **拿旧坐标硬点** ✗✗
⛔ 根因 B：`popups()` 里 **`rnd` 未定义** ⇒ 停脚本的"保现场"（截图+锁）**从没做成** ✗
   （`'round': rnd` 在 dict 字面量里 ⇒ **整块 `json.dump` 废掉** ⇒ 锁文件没写）
"""
import ast
import importlib
import inspect
import io
import os
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import buypanels as BP
import explore_loop as EL

OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('宝库「第二层乱点」根因回归（2026-10-10）')
print('=' * 94)

# ── A. `_probe_name` 的 `log` ──────────────────────────────────
print()
print('【A】`_probe_name` 必须能读到 `log`（否则"收起详情"从没执行）')
sig = inspect.signature(BP._probe_name)
c = BP._probe_name.__code__
ck('① 签名里有 `log`', 'log' in sig.parameters, str(sig))
ck('② `log` 不再是"全局查找"（`co_names` 里没有它）',
   'log' not in c.co_names or 'log' in c.co_varnames,
   'co_varnames=%s co_names 含 log=%s' % (c.co_varnames[:4], 'log' in c.co_names))

# ⭐ 执行级：真调一次，看"收起详情"那一下有没有点出去
class FB:
    def __init__(self):
        self.taps = []

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))

    def ocr(self, *a, **k):
        return []

    def img_dlg(self):
        import numpy as np
        return np.zeros((1280, 720, 3), np.uint8)

    def snap(self, *a, **k):
        return 'x.png'


b = FB()
log = []
r = BP._probe_name(b, (264, 593), log=log)
print('     调用后：点过 = %s' % (b.taps,))
print('     日志 = %s' % [str(x)[:70] for x in log][:3])
ck('③ ⭐ **点过 ≥2 下**（第 1 下点开格子、第 2 下点空白收起详情 ✓）',
   len(b.taps) >= 2, '实际 %d 下：%s' % (len(b.taps), b.taps))
ck('④ 第 2 下是 `VAULT[\'blank\']`（收起详情的位置 ✓）',
   len(b.taps) >= 2 and b.taps[1] == tuple(BP.VAULT['blank']),
   str(b.taps[1:2]))
ck('⑤ ⚠ 落了一条 `probe_blank_ok`/`probe_blank_fail`（**不许静默** ✓）',
   any('probe_blank' in str(x) for x in log), str(log[:2]))

# ── B. `popups()` 的 `rnd` ────────────────────────────────────
print()
print('【B】`popups()` 里不许再出现裸 `rnd`（停脚本的"保现场"要靠它）')
src = inspect.getsource(EL.popups)
_code_lines = [ln for ln in src.splitlines() if not ln.strip().startswith('#')]
_has_bare_rnd = any(('% rnd' in ln) or ("'round': rnd" in ln) for ln in _code_lines)
ck('⑥ **代码里**没有裸 `rnd`（注释里提到不算 ✓）', not _has_bare_rnd)
ck('⑦ 改用 `ctx[\'flags\']` 取轮次（与地图名同来源 ✓）',
   "'round')" in src and '_fl_stop0' in src)
# ⛔⛔ 2026-10-13 **本项已按新行为改写**（整套"停脚本锁"已按用户要求删除 ✗）
#   用户原话：「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓
#   ⇒ 原来断言 `foretell_lock_written` / `foretell_lock_fail` 两条日志 ——
#     那是**写锁**的痕迹，锁都没了 ⇒ 断言必然假红 ✗
#   ⇒ 现在改断言**该留的那半**：停脚本时**仍然留取证帧**（保现场的核心价值 ✓）
ck('⑧ ⚠ 停脚本时**仍留取证帧**（保现场 ✓；不再写锁 ✗）',
   'foretell_shot' in src and 'foretell_lock_written' not in src)

# ── C. 结构级：全仓不许再有"真 NameError" ─────────────────────
print()
print('【C】全仓扫描：不许再有「未定义名字 + 被 except 吞」')
import builtins
_BI = set(dir(builtins))
real = []
for f in ('explore_loop.py', 'buypanels.py'):
    tree = ast.parse(io.open(f, encoding='utf-8').read())
    m = importlib.import_module(os.path.splitext(f)[0])
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        cc = getattr(getattr(m, node.name, None), '__code__', None)
        if cc is None:
            continue
        bound = set()
        for a in (node.args.args + node.args.kwonlyargs + node.args.posonlyargs):
            bound.add(a.arg)
        if node.args.vararg:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg:
            bound.add(node.args.kwarg.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                bound.add(sub.id)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                for al in sub.names:
                    bound.add((al.asname or al.name).split('.')[0])
            elif isinstance(sub, ast.ExceptHandler) and sub.name:
                bound.add(sub.name)
            elif isinstance(sub, (ast.FunctionDef, ast.Lambda)):
                for a in (sub.args.args + sub.args.kwonlyargs + sub.args.posonlyargs):
                    bound.add(a.arg)
                if sub.args.vararg:
                    bound.add(sub.args.vararg.arg)
                if sub.args.kwarg:
                    bound.add(sub.args.kwarg.arg)
            elif isinstance(sub, ast.comprehension):
                for n2 in ast.walk(sub.target):
                    if isinstance(n2, ast.Name):
                        bound.add(n2.id)
            elif isinstance(sub, (ast.Global, ast.Nonlocal)):
                bound.update(sub.names)
        used = {n.id for n in ast.walk(node)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        for nm in sorted(used & set(cc.co_names)):
            if nm in _BI or nm in bound or hasattr(m, nm):
                continue
            # 手机端专用（PC 上不可达）⇒ 白名单
            if nm == '_GLOBAL_LOG':
                continue
            real.append('%s:%s:%s' % (f, node.name, nm))
ck('⑨ 全仓**零**未定义名字（`_GLOBAL_LOG` 是手机端专用、PC 不可达 ⇒ 白名单 ✓）',
   not real, str(real[:4]))

print()
print('【D】多半径采样：同一帧上那两个真天赋果实必须认出来（修前 0 个 ✗）')
# ⭐ 真机铁证帧：`vault_no_hit_L2.png`（用户报「第二层乱点」那把）
#   同一格 pink 随 rad 剧烈波动：(458,689) 24:0.435 **30:0.231** 34:0.362
#   ⇒ 生产原来只用 rad=min(w,h)*0.36≈30 ⇒ 恰好最差 ⇒ 两个真果实全认不出 ⇒ 掉进兜底乱点
import cv2 as _cv2
import numpy as _np

# ⛔⛔ 2026-10-11 **修本回归的假红**（基准帧被覆盖 ✗）：
#   原来用 `runs/vaultdbg/vault_no_hit_L2.png` 当基准 —— 而
#   `_vault_dump('vault_no_hit_L%d')` 是**固定文件名** ⇒ **每次 no_hit 都覆盖它** ✗✗
#   ⇒ 基准帧早就不是当初那张了（内容变了、命中数也变了）⇒ 回归假红（代码没坏）✗
#   ⇒ 改成 `_verify/vault_r2_multitile.png`（**稳定的基准语料** ✓
#     README 明令 `_verify/` 不能删；且它是 `wspC_01_cur_20261003.png` 的副本 ✓）
#   ⚠ 该帧实测：**单半径 0 命中 ／ 多半径 12 命中** ⇒ 对照度比原来那张更好 ✓
_P2 = os.path.join(r'_verify', 'vault_r2_multitile.png')
if not os.path.exists(_P2):
    _P2 = r'runs\vaultdbg\vault_no_hit_L2.png'      # 兜底（⚠ 可能已被覆盖）
if not os.path.exists(_P2):
    ck('⑩ 有真机取证帧（可复算）', False, _P2)
else:
    _img = _cv2.imdecode(_np.fromfile(_P2, dtype=_np.uint8), _cv2.IMREAD_COLOR)
    _tiles = BP.vault_tiles(_img)
    print('     基准帧 = %s（检出 %d 格）' % (os.path.basename(_P2), len(_tiles)))
    # 复现生产那段"多半径取最好"（**用检测出来的格**，不再写死坐标 ✓）
    _hits, _single = [], []
    for (_x, _y, _w, _h) in _tiles:
        _r0 = int(min(_w, _h) * 0.36)
        for _rr in (max(6, int(_r0 * 0.83)), int(_r0), int(_r0 * 1.17)):
            _k, _fr = BP.sprite_kind(_img, _x, _y, _rr)
            if _k:
                _hits.append((_x, _y, _k))
                break
        if BP.sprite_kind(_img, _x, _y, _r0)[0]:
            _single.append((_x, _y))
    print('     多半径命中 %d 个 %s' % (len(_hits), _hits[:4]))
    print('     单半径命中 %d 个' % len(_single))
    ck('⑩ ⭐ 多半径认出 **≥1** 个（修前 0 个 ⇒ 才掉进兜底乱点 ✗）',
       len(_hits) >= 1, '%d 个' % len(_hits))
    ck('⑪ ⭐ 多半径**比单半径多**（证明"多半径"真在解决问题 ✓）',
       len(_hits) > len(_single),
       '单=%d 多=%d' % (len(_single), len(_hits)))
    ck('⑫ ⚠ **对照项**：旧口径（单半径）在这帧上**一个都认不出**'
       '（证明多半径不是恒真 ✓）', len(_single) == 0,
       '旧口径命中 %s' % _single[:4])

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
