# -*- coding: utf-8 -*-
"""verify_no_720_drift.py · 防「1080p→720p 换基准」的坐标/几何漂移（2026-10-02）

事故背景
--------
PC 端把参考基准从 1080×1920 换成 720×1280（`layout.REF_W/REF_H`）。凡是**没有**
跟着换的裸坐标都会错位，而这四轮里反复出现同一类事故：

  · `spots._region()` 的 pad 算成负数   ⇒ 地块识别全线失效
  · `marks.GRID` + `GLYPH_SCALES`      ⇒ 标记扫描恒空 ⇒ 每轮「没有目标了」
  · `explore_loop.UNIVERSAL_CLOSE` 等 5 处 ⇒ 退图空转到超时
  · `FIGHT_Y` / 战斗按钮 y 带           ⇒ boss 打不了
  · **本轮**：`GUILD_BTN`/`BAG_BTN`/`UPGRADE_BTN`/`VAULT`/`MERCHANT` 等
    **十几处 1080p/1600 系常量** ⇒ 公会/背包/升星/宝库/商人**一按就点空**

共同特征：**门禁全绿，真机才炸** ⇒ 所以这里必须有一条**常驻**门禁。

本脚本断言
----------
① 运行时模块里**所有会被当成点击坐标的常量**都落在 720×1280 屏内
   （y < 1280 / x < 720）—— 越界 = 点在屏幕外，永远点不到
② `marks.GRID` / `cells.GRID` 与 `layout.REF` 一致（棋盘几何不漂）
③ `explore_loop` 的关键锚点与 `fixed.py` / `layout.REF` **逐条吻合**
④ 源码里**没有**「整体替换 marks.GRID」的写法（会丢 cols/rows）
⑤ `tap_dlg` 在 PC 上 C 恒 0 ⇒ 面板坐标**必须**已是设备系（不可依赖自动换算）

⚠ 零设备、零体力：纯静态检查 + 常量比对，不连 adb、不点任何东西。
"""
from __future__ import annotations

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
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）


os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PC_W, PC_H = 720, 1280

OK: list = []
BAD: list = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  [%s] %s%s' % ('ok  ' if cond else 'FAIL', name,
                           ('  ' + detail) if detail else ''))


# ── 会「按屏幕尺寸折叠」的模块：不查裸常量 ────────────────────────────
#   `fixed.py` 故意存 1080p 参考值（内部 `_r()` 会 ×0.6667）
#   `layout.py` 的 REF **就是** 720p 基准本身
SCALED_BY_DESIGN = {'fixed.py', 'layout.py'}

RUNTIME = ('explore_loop.py', 'mapbot.py', 'marks.py', 'spots.py', 'cells.py',
           'targets_cfg.py', 'mapsolve.py', 'mapsim.py', 'strategy.py',
           'grid_detect.py', 'badge.py', 'buypanels.py',
           'paths.py', 'mumu.py', 'fastcap.py', 'mapgen.py',
           # ⭐⭐ 2026-10-14 **公会展厅那一层**（派遣任务 / 炼金）：
           #   `guild_common.py` 里 **21 个点击坐标全是真机实测的裸 720p 值**
           #   （`_tmp_probe_dispatch/CALIBRATION.md`）—— 正是本门禁要守的那类东西 ✓
           #   ⚠ 它们**不是** `layout.REF` 抄来的：`layout.py` 根本没有公会楼层这一层
           #     ⇒ 只能靠本门禁兜"抄错/越界"，加进来才有意义 ✓
           #   `guild_tasks.py` / `alchemy.py` 自己**不存坐标**（全从 guild_common 取），
           #   但它们有"按钮位/判定带"这类数字 ⇒ 一并纳入扫描（零成本）✓
           'guild_common.py', 'guild_tasks.py', 'alchemy.py',
           # ⭐ 2026-10-14 免费指定招募（用户口径：「抄一下小助手的选项判断机制」）
           #   里面有公会右下角「招募」/ 大厅门 / 招募按钮 / 弹窗 X
           #   —— **全是真机实测的裸 720p 坐标** ✓
           #   ⚠ 2026-10-15 入口已按用户口径改成「公会 → 右下角招募 → 免费」✓
           'recruit.py',
           # ⭐⭐ 2026-10-15 **公会「情报」领奖**（用户口径：
           #   「接下来做点击情报领取奖励」＋「每周情报也顺便点了」）
           #   里面有「情报」按钮 / 面板关闭 X / 两个页签 / 列表按钮 x / 弹窗返回
           #   —— **全是真机实测的裸 720p 坐标** ✓
           'intel.py',
           # ⭐⭐ 2026-10-16 **天赋果实记录**（用户口径：
           #   「最后的最后…去背包道具里扫描下天赋果实数量，并且记录」）
           #   里面有背包页签 x/y / 道具网格搜索区 / 背包关闭 X
           #   —— **全是真机实测的裸 720p 坐标** ✓
           'fruit.py')
# ⚠ `bot_gui.py` 不查：它是**桌面窗口**代码（`root.minsize(760,460)` 之类），
#   那些数字是窗口尺寸，与游戏画面坐标无关 ⇒ 查它只会误报 ✓

# OCR 搜索带 / 区域：越界只会被裁剪，不会点空 ⇒ 不算 bug
BAND_KEY = re.compile(r'\b(band|_bands?|BAND|region|box|roi|search|zone)\b', re.I)
# 这些调用内部**会**按屏幕折算 ⇒ 传参越界无所谓
FOLDED_CALL = re.compile(
    r'LAYOUT\.(sx|sy|pt|s)\(|\.tap_dlg\(|_panel_tap\(|_tap_verified\(|_bag_tap\(')

# ⚠⚠ 2026-10-06 **豁免：尺寸/阈值元组 ≠ 坐标**（只豁免「名字里写明是阈值」这一形态）
#   AGENTS.md §4.2：审计要先分清三类"长得像"的东西，否则误报一片 ✓
#   实例：`buypanels._VAULT_TILE_REF = (4000, 100, 185)`
#     = (最小面积, 最小边长, 最大边长)，**像素尺寸阈值**，根本不是 (x, y)
#     ⇒ 拿"y ≥ 1280 就报"去套它 ⇒ 把 `4000` 当 x、`100` 当 y？其实它连二元组都不是，
#       是**三元组**被 `module_constants()` 的 `else` 分支收进 `dcoord` ⇒ **误报** ✗
#   ⛔ 豁免必须**窄**：只认名字里含 THR/REF/SIZE/AREA/SIDE/SCALE 这类**阈值词**的常量；
#      `VAULT = {...}` 那种真坐标 dict **照旧全查**（它的键值才是点击坐标 ✓）
#   ⛔ 也**不许**把三元组一律放过 —— 真坐标也可能写成三元组，那时越界就等于点空 ✗
THRESHOLD_NAME = re.compile(
    r'(THR|THRESHOLD|SIZE|AREA|SIDE|SCALE|MIN|MAX|LIMIT|_REF|RANGE)', re.I)


def module_constants(path):
    """AST 抽出模块级 `NAME = (x, y)` / `NAME = (x, y, ...)` 常量 + dict 里的坐标"""
    try:
        tree = ast.parse(io.open(path, encoding='utf-8').read())
    except (OSError, SyntaxError) as e:                       # noqa: BLE001
        return None, None, str(e)
    consts, dcoord = [], []
    for node in tree.body:                       # 只看模块级（局部变量会跟着折算）
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            v = node.value
            if isinstance(v, ast.Tuple) and v.elts and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, int)
                    for e in v.elts):
                nums = tuple(e.value for e in v.elts)
                if len(nums) == 2:
                    consts.append((name, nums))
                else:
                    dcoord.append((name, nums))
            elif isinstance(v, ast.Dict):
                for k, val in zip(v.keys, v.values):
                    if not isinstance(val, ast.Tuple) or len(val.elts) != 2:
                        continue
                    if not all(isinstance(e, ast.Constant)
                               and isinstance(e.value, int) for e in val.elts):
                        continue
                    key = k.value if isinstance(k, ast.Constant) else '?'
                    dcoord.append(('%s[%s]' % (name, key),
                                   (val.elts[0].value, val.elts[1].value)))
    return consts, dcoord, None


def strip_comments_and_docstrings(path):
    """返回去掉注释与 docstring 后的源码行列表（AST 精确定位，不靠猜）"""
    try:
        src = io.open(path, encoding='utf-8').read()
    except OSError:
        return None
    tree = ast.parse(src)
    drop = set()                     # 要抹掉的行号（1-based）
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                ds = body[0]
                drop.update(range(ds.lineno, (ds.end_lineno or ds.lineno) + 1))
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if i in drop or s.startswith('#'):
            out.append('')            # 抹掉
            continue
        # 行尾注释里的坐标举例不算
        code = re.sub(r'#.*$', '', line)
        out.append(code)
    return out


def main():
    print('=' * 78)
    print('防回归：全仓不得有「会被当点击坐标的 1080p 常量」  '
          '(720x1280 屏内)  零设备')
    print('=' * 78)

    # ── ① 模块级坐标常量必须在屏内 ──────────────────────────────
    print()
    print('【1】模块级 / dict 坐标常量必须落在 %dx%d 屏内' % (PC_W, PC_H))
    bad = []
    for name in RUNTIME:
        path = os.path.join(HERE, name)
        if not os.path.exists(path) or name in SCALED_BY_DESIGN:
            continue
        consts, dcoord, err = module_constants(path)
        if err:
            check('① %s 可解析' % name, False, err)
            continue
        for label, vals in consts + dcoord:
            if not vals or len(vals) < 2:
                continue
            # ⚠ 阈值/尺寸类常量**不是坐标** ⇒ 跳过（见 `THRESHOLD_NAME` 的长注释）
            #   ⛔ 只认名字里写明是阈值的；真坐标常量照旧全查 ✓
            if THRESHOLD_NAME.search(label):
                continue
            x, y = vals[0], vals[1]
            if y >= PC_H or x >= PC_W:
                bad.append('%s:%s = %s' % (name, label, str(vals)))
    for b in bad:
        print('      ⛔ %s' % b)
    check('① 无越界的模块级坐标常量', not bad,
          '' if not bad else '  %d 处：%s' % (len(bad), bad[:4]))

    # ── ② 源码里裸的 (x, y) 字面量（tap 类调用点） ──────────────
    print()
    print('【2】源码里「直接当点击坐标用的 (x,y)」不得越界')
    bad2 = []
    for name in RUNTIME:
        path = os.path.join(HERE, name)
        if not os.path.exists(path) or name in SCALED_BY_DESIGN:
            continue
        try:
            lines = strip_comments_and_docstrings(path)
        except SyntaxError as e:
            check('① %s 可解析' % name, False, str(e))
            continue
        if lines is None:
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if not s:
                continue
            # ⚠⚠ 2026-10-02 **豁免：OCR 搜索带 ≠ 点击坐标**（只豁免「带子两端」这一形态）
            #   AGENTS.md §4.2：审计要先分清三类「长得像」的东西，否则误报一片。
            #   本条抓的是「**当成点击坐标用**、在屏外 ⇒ 点空」；
            #   而 `_x0, _x1 = 500, 693` 是 **OCR 搜索带的两个端点**，
            #   越界后果只是「少认几个字」，**不会点空屏幕** ⇒ 不该报。
            #   实例：宝库「购买」搜索带 720p (500,693)×(900,1110)
            #        （= 1080p 老值 × 0.6667）—— 1110 < 1280 本就在屏内 ✓
            #   ⛔ 只认「两端同时赋值」这一形态；`a, b = 123, 456`（真坐标拆写）
            #      仍照报 —— 2026-10-02 升星确认框就是这么漏的 ✗
            if re.match(r'^_\w*0\s*,\s*_\w*1\s*=\s*\d+\s*,\s*\d+\s*(#.*)?$', s):
                continue
            # 会折算的调用 ⇒ 参数越界无所谓
            if FOLDED_CALL.search(line) or BAND_KEY.search(line):
                continue
            # ⚠⚠ 2026-10-09 **豁免：阈值/范围名字的元组 ≠ 点击坐标**（与【1】同口径 ✓）
            #   实例（我本轮踩的）：`MIMIC_BUY_Y_RANGE = (830, 1110)`
            #     = **y 的搜索范围**（购买键在哪一档 y），不是 (x, y) 坐标 ✗
            #     ⇒ 拿"y ≥ 1280 就报"套它 ⇒ **误报** ✓
            #   ⭐ 判据与【1】`THRESHOLD_NAME` **同一份**（`THR/SIZE/AREA/SIDE/SCALE/
            #      MIN/MAX/LIMIT/_REF/RANGE`）—— 两处用同一个正则，免得漂移 ✓
            #   ⛔ 仍然**窄**：名字里没这些词的坐标（如 `MIMIC_BUY_BTN = (586, 1053)`）
            #      **照旧全查** ✓
            _lhs = line.split('=')[0]
            if THRESHOLD_NAME.search(_lhs):
                continue
            # 纯记录/说明性字符串（log/say/print 里的历史坐标举例）不是点击坐标
            if re.search(r"['\"](at|note|text)['\"]\s*:", s) or \
                    re.search(r"\b(say|print|log\.append)\s*\(", line):
                continue
            for m in re.finditer(r'\(\s*(\d{3,4})\s*,\s*(\d{3,4})\s*\)', s):
                x, y = int(m.group(1)), int(m.group(2))
                if y >= PC_H or x >= PC_W:
                    bad2.append('%s:%d  %s' % (name, i, s.strip()[:70]))
            # ⭐ 局部 `a, b = 123, 456`（拆成两个数的坐标赋值）也要查 ——
            #   2026-10-02 真踩过：升星确认框写成 `_cfx, _cfy = 803, 1112`
            m = re.match(r'^([a-z_]\w*)\s*,\s*([a-z_]\w*)\s*=\s*(\d{2,4})\s*,\s*(\d{2,4})\s*$', s)
            if m:
                x, y = int(m.group(3)), int(m.group(4))
                if y >= PC_H or x >= PC_W:
                    bad2.append('%s:%d  %s  %s:%d' % (name, i, s.strip()[:48],
                                                       m.group(1), y))
    seen, uniq = set(), []
    for b in bad2:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    for b in uniq:
        print('      ⛔ %s' % b)
    check('② 源码里没有越界的裸点击坐标', not uniq,
          '' if not uniq else '  %d 处' % len(uniq))

    # ── ③ 关键锚点与 fixed.py 对拍 ──────────────────────────────
    print()
    print('【3】explore_loop 关键锚点必须与 layout.REF / fixed.py 一致')
    try:
        import layout
        import fixed as FX
        REF = layout.REF
        pairs = [('close_bag', REF['close_bag'], FX.A('close_bag')),
                 ('start_adv', REF['start_adv'], FX.A('start_adv_icon')),
                 ('enter_map', REF['enter_map'], FX.A('enter_map')),
                 ('back_btn', REF['back_btn'], FX.A('back_btn'))]
        for nm, a, b in pairs:
            check('① REF[%-10s]=%-12s 与 fixed.A 同值' % (nm, str(a)), a == b,
                  '' if a == b else '  fixed=%s ⇒ 两套实现漂移了' % (b,))
    except Exception as e:                                    # noqa: BLE001
        check('① 能 import layout/fixed', False, repr(e))

    # ── ④ marks/cells 棋盘几何 ─────────────────────────────────
    print()
    print('【4】棋盘几何单一数据源（不许各写一份）')
    try:
        import marks
        import cells
        want = {'x0': float(REF['grid_x0']), 'y0': float(REF['grid_y0']),
                'cx': float(REF['grid_cx']), 'cy': float(REF['grid_cy'])}
        for mod, nm in ((marks, 'marks'), (cells, 'cells')):
            for k, v in want.items():
                got = float(mod.GRID.get(k) or -1)
                check('① %s.GRID[%-2s]=%-7.1f = REF' % (nm, k, got),
                      abs(got - v) < 0.5)
            check('② %s.GRID 有 cols/rows（防被整体替换弄丢）' % nm,
                  'cols' in mod.GRID and 'rows' in mod.GRID)
    except Exception as e:                                    # noqa: BLE001
        check('① 能 import marks/cells', False, repr(e))

    # ── ⑤ tap_dlg 在 PC 上 C 恒 0 ⇒ 坐标必须已是设备系 ──────────
    print()
    print('【5】tap_dlg 在 PC 上不做换算（C 恒 0）⇒ 面板坐标必须已折算')
    try:
        import mapbot as MB
        check('① PC 端 dlg_shift() 恒 0（= tap_dlg 就是 tap）',
              float(MB.dlg_shift()) == 0.0)
        import buypanels as BP
        for nm, v in (('VAULT.buy', BP.VAULT['buy']),
                      ('VAULT.x', BP.VAULT['x']),
                      ('VAULT.back', BP.VAULT['back']),
                      ('VAULT.blank', BP.VAULT['blank']),
                      ('MERCHANT.buy', BP.MERCHANT['buy']),
                      ('MERCHANT.x', BP.MERCHANT['x']),
                      ('MERCHANT.back', BP.MERCHANT['back'])):
            on = 0 <= v[0] < PC_W and 0 <= v[1] < PC_H
            check('② buypanels.%-16s = %-12s 在屏内' % (nm, str(v)), on)
        # 交叉验证：MERCHANT.back 应与 REF['back_btn'] 一致
        check('③ buypanels.MERCHANT.back == REF[back_btn]（折算系数自证）',
              BP.MERCHANT['back'] == (359, 808),
              '  得 %s，期望 (359, 808)' % (BP.MERCHANT['back'],))
    except Exception as e:                                    # noqa: BLE001
        check('① 能 import mapbot/buypanels', False, repr(e))

    print()
    print('=' * 78)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
    for x in BAD:
        print('   ✗ ' + x)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
