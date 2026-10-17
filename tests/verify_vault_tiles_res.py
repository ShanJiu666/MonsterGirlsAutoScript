# -*- coding: utf-8 -*-
"""verify_vault_tiles_res.py · 守住「宝库格检测的尺寸阈值必须跟着分辨率走」

真机事故（用户报「**为什么黄金宝库又不能正常买了？？**」＋
          「**买到第二层就把宝库关了，可能点到宝库外面了**」）：
    取证帧 `runs/vaultdbg/vault_no_hit_L2.png` = 第 2 层"没点中"那一刻。
    宝库面板完整开着、按钮「选择奖励」、第 2 层 8 格全是彩色底，
    可 `vault_tiles()` 返回 **0 个格** ⇒ `vault_pick` 回落到写死的理论网格 ⇒ 乱点 ⇒ 点关面板 ✗

根因：`vault_tiles()` 的 `min_area=4000 / min_side=100 / max_side=185`
      以及 `y > 700 / x < 960` 是**按 1080×1920 标的**，而 PC 端锁 **720×1280**。
      · 110 张真机宝库帧实测格子边长：
          1080×1920 的 3 张（`runs/vault_open.png` 等）格子 = **126** ⇒ 过 100 档 ✓
          720×1280 的 **107 张** 格子 = **84** ⇒ **全部被拒** ✗
        **126 / 84 = 1.5 = 1080 / 720** ⇒ 常数是 1080p 值 ✓

判据分四层：
  【1】数据级：`vault_tile_thr()` 必须按帧宽缩放 —— 720p 的 min_side 明显小于 100、
        1080p 上**逐值等于 1080 基准**（1080 是老标定屏 ⇒ 必须 no-op）
  【2】执行级（真机帧，**只读 `_verify/`**）：
        · 蓝本的 `vault_no_hit_L2` 帧 ⇒ `vault_tiles()` 必须检出第 2 层那 8 格
        · 圈层过滤后 `ring2` 必须正好 8 格（证"能选到第 2 层"）
  【3】守门：1080p 老帧的结果必须与"显式传老值"**逐值相同**（不许改坏老行为）
  【4】反向守门：把缩放关掉（退回写死 100/185/4000 + y>700）⇒ 720p 必须回到 **0 格**
        （否则本门禁是恒绿的摆设 ✗）
"""
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

_n = [0]
_fail = [0]
_skip = []


def ck(name, cond, extra=''):
    _n[0] += 1
    if cond:
        print('  [ok]   %s' % name)
    else:
        _fail[0] += 1
        print('  [FAIL] %s  %s' % (name, extra))


def skip(name, why):
    _skip.append(name)
    print('  [skip] %s  （%s）' % (name, why))


print('=' * 76)
print('【1】数据级：尺寸阈值必须跟着帧宽走（1080 基准 ⇒ 1080p 上是 no-op）')
print('=' * 76)

try:
    import buypanels as BP
except Exception as _e:                          # noqa: BLE001
    print('  ✗ import buypanels 失败：%r' % (_e,))
    sys.exit(1)

ck('存在 vault_tile_thr()（阈值按分辨率算的函数）', hasattr(BP, 'vault_tile_thr'))
ck('存在 _VAULT_TILE_REF（1080 基准常量）', hasattr(BP, '_VAULT_TILE_REF'))


class _FakeImg:
    def __init__(self, w):
        self.shape = (int(w * 16 / 9.0), int(w), 3)


try:
    _720 = BP.vault_tile_thr(_FakeImg(720))
    _1080 = BP.vault_tile_thr(_FakeImg(1080))
    _1440 = BP.vault_tile_thr(_FakeImg(1440))
    print('  720p  ->', _720)
    print('  1080p ->', _1080)
    print('  1440p ->', _1440)
    ck('720p 的 min_side < 100（不再把 84 的格子拒掉）', _720[1] < 100,
       'min_side=%s' % (_720[1],))
    ck('720p 的 min_side 落在「小于 84」一侧（格子过得去）', _720[1] <= 84,
       'min_side=%s vs 实测格子 84' % (_720[1],))
    ck('1080p 上逐值等于 1080 基准（老行为 no-op）',
       tuple(_1080) == tuple(BP._VAULT_TILE_REF),
       '%s vs %s' % (_1080, BP._VAULT_TILE_REF))
    ck('更高分辨率单调变松（不是写死）', _1440[1] > _1080[1] > _720[1],
       '%s %s %s' % (_720[1], _1080[1], _1440[1]))
    ck('取不到宽度时退回 1080 基准（绝不比原来更松）',
       tuple(BP.vault_tile_thr(None)) == tuple(BP._VAULT_TILE_REF),
       '%s' % (BP.vault_tile_thr(None),))
except Exception as _e:                          # noqa: BLE001
    ck('阈值缩放可调用', False, repr(_e))

print()
print('=' * 76)
print('【2】执行级：真机帧（只读 `_verify/`）')
print('=' * 76)

try:
    import cv2
except Exception as _e:                          # noqa: BLE001
    skip('执行级（需要 cv2）', repr(_e))
    cv2 = None

# 夹具：第 2 层"没点中"那张（已冻结进 _verify/）
FIX_L2 = os.path.join(HERE, '_verify', 'vault_L2_nohit_20261006.png')
FIX_1080 = os.path.join(HERE, '_verify', 'vault_1080_marker.png')

if cv2 is not None:
    ck('夹具存在：_verify/vault_L2_nohit_20261006.png', os.path.isfile(FIX_L2))
    if os.path.isfile(FIX_L2):
        _img = cv2.imread(FIX_L2)
        ck('夹具是 720p（真机 PC 基准）', _img is not None and _img.shape[1] == 720,
           'shape=%s' % (None if _img is None else _img.shape,))
        _t = BP.vault_tiles(_img)
        print('  vault_tiles(720p 第2层帧) -> %d 个格' % len(_t))
        for (x, y, w, h) in _t:
            print('      (%3d,%3d) %dx%d 圈层=%s' % (x, y, w, h, BP.tile_ring(x, y)))
        ck('第 2 层帧能检出格子（修前是 0 ⇒ 这条就是"能不能买第二层"）', len(_t) >= 8,
           '检出 %d 个' % len(_t))
        _cells = [(x, y) for (x, y, _w, _h) in _t]
        _r2 = [p for p in _cells if BP.tile_ring(p[0], p[1]) == 2]
        ck('圈层过滤后 ring2 正好 8 格（第 2 层可选中）', len(_r2) == 8,
           'ring2=%d %s' % (len(_r2), _r2))
        ck('检出的格全部落在宝库 5×5 点阵上（没把按钮/底色块混进来）',
           all(BP._vault_lattice(x, y) is not None for (x, y) in _cells))

print()
print('=' * 76)
print('【3】守门：1080p 老帧行为必须与"显式传 1080 老值"逐值相同')
print('=' * 76)
if cv2 is not None and os.path.isfile(FIX_1080):
    _i2 = cv2.imread(FIX_1080)
    _a = BP.vault_tiles(_i2)
    _b = BP.vault_tiles(_i2, min_area=4000, min_side=100, max_side=185)
    ck('1080p 帧：自适应结果 == 显式老值结果', _a == _b,
       'adaptive=%s explicit=%s' % (_a, _b))
    ck('1080p 夹具确实是 1080 宽', _i2 is not None and _i2.shape[1] == 1080,
       'shape=%s' % (None if _i2 is None else _i2.shape,))
else:
    skip('1080p 对照', '夹具不存在（%s）' % os.path.basename(FIX_1080))

print()
print('=' * 76)
print('【4】反向守门：把缩放关掉 ⇒ 720p 必须回到 0 格')
print('=' * 76)
if cv2 is not None and os.path.isfile(FIX_L2):
    import inspect
    _src = inspect.getsource(BP.vault_tiles)
    _old = _src.replace('_y_lo = 700 * _k', '_y_lo = 700') \
               .replace('_x_hi = 960 * _k', '_x_hi = 960')
    ck('构造出的"旧行为版"与现在不同（否则本项无意义）', _old != _src)
    _ns = {}
    try:
        exec(compile(_old, '<old>', 'exec'), BP.__dict__, _ns)
        _oldfn = _ns['vault_tiles']
        _r = _oldfn(cv2.imread(FIX_L2), min_area=4000, min_side=100, max_side=185)
        print('  退回写死 1080p 阈值 -> %d 个格' % len(_r))
        ck('退回旧阈值 ⇒ 720p 检出 0 格（证明修复真的在起作用，不是恒绿）',
           len(_r) == 0, '竟然检出 %d 个' % len(_r))
    except Exception as _e:                      # noqa: BLE001
        ck('反向守门可运行', False, repr(_e))
else:
    skip('反向守门', '夹具不存在')

print()
print('=' * 76)
if _skip:
    print('跳过 %d 项：%s' % (len(_skip), '、'.join(_skip)))
if _fail[0]:
    print('✗ 失败 %d / %d 项' % (_fail[0], _n[0]))
    sys.exit(1)
print('✅ 全部通过：宝库格检测的阈值跟着分辨率走（1080p 上是 no-op），'
      '720p 第 2 层认得出 8 格、退回旧阈值就变 0（不是恒绿）')
