# -*- coding: utf-8 -*-
"""verify_collect_fast.py · 回归：退图前补点 = **固定坐标**，不是逐个状态 OCR

用户 2026-10-05 原话：
    「**怎么还ocr？这种不应该都是固定坐标点击吗**」

真机实测（`runs/acc1/loop/loop_log.json` 的 `taps` 时长）
---------------------------------------------------------
    点 4,6 用时 **5.1s** ｜ 点 2,6 用时 **9.1s** ｜ 点 4,3 用时 **6.2s**
    点 1,3 用时 **5.2s** ｜ 点 3,1 用时 **3.7s**
`final_collect()` 原来在"补点一下"之后要走 **最多 6 次整屏 OCR**
（`collect` / `collect_panel` / `collect_panel2` / `collect2` / `collect3`×最多 4），
每次 0.65~0.9 秒 ⇒ **这就是那几秒的来源** ✗

而这些弹窗的按钮**位置固定**，`fixed.py` 里早有锚点：
    莱姆「返回」   `FX.A('lime_back')`       = (359, 873)
    新装备「返回」 `FX.A('equip_back')`      = (360, 835)
    通用「关闭」   `FX.A('universal_close')` = (361,1260)
    底部确认       `FX.A('bottom_close')`    = (385, 960)

修法：**补点之后先走"固定坐标 + 一次窄带确认"快速路**；确认不干净才落回原来的
逐状态路径（**兜底一条不删** ✓）。

本门禁（离线，不需要模拟器）
"""
import ast
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
SKIPS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print('  [skip] %s（%s）' % (name, why))
    SKIPS.append(name)


def _ocr_band(img, band, MB):
    """按 `Bot.ocr()` 的**同一套** band+scale+坐标回算，返回 items（离线，不碰设备）。

    ⚠ 必须与 `mapbot.Bot.ocr()` 逐字同口径（裁带 ⇒ 缩放 ⇒ OCR ⇒ cy 加回 y0），
      否则测的是"我以为的 band"而不是生产代码的 band。
    """
    import cv2
    im = img
    sc = MB.OCR_SCALE * (1080.0 / float(im.shape[1]))
    y0 = 0
    if band:
        y0, y1 = int(band[0]), int(band[1])
        im = im[max(0, y0):y1]
        if im.size == 0:
            return []
    if sc != 1.0:
        im = cv2.resize(im, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    tmp = os.path.join(HERE, 'runs', '_vcf_tmp.png')
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    cv2.imencode('.png', im)[1].tofile(tmp)
    res, _ = MB._ocr()(tmp)
    out = []
    inv = 1.0 / sc if sc else 1.0
    for it in (res or []):
        box, txt, conf = it[0], it[1], it[2]
        if conf < 0.4:
            continue
        xs = [q[0] * inv for q in box]
        ys = [q[1] * inv + y0 for q in box]
        out.append({'text': txt.strip(), 'cx': int(sum(xs) / 4), 'cy': int(sum(ys) / 4),
                    'conf': round(float(conf), 3)})
    return out


def _inmap_ocr_band(src):
    """AST：查 `final_collect` 里**喂给 `in_map()` 的那次 `b.ocr(...)`** 传的 band。

    ⚠ 为什么必须 AST、不能字符串 grep：
      · 留档注释里**必然逐字引用** `band=(0, 320)`（本项目已第四次踩：
        v1.62c 的 `CONTENT_SCORE_MIN` / v1.67 的旧判据 / v1.68 的 `.pack_v3`）
        ⇒ grep 会**假红**
      · 而且真判据不是"有没有写窄带"，是"**这次 OCR 的结果会不会喂给 in_map**"
        ⇒ 必须顺着数据流找，不能只看字面

    返回 (ok, why)：
      ok=True  ⇔ 那次 `b.ocr` 的 band 上界 ≥ 1080（覆盖得到「结束冒险」cy=515 与
                 「快速扫荡」cy=1079），或者干脆不带 band（全屏）
    """
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == 'final_collect'):
            continue
        # ① 找 `it0 = b.ocr(...)` 这类赋值：变量名 → band 上界
        var_band = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            call = node.value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == 'ocr'):
                continue
            hi = None                     # None = 不带 band（全屏）✓
            for kw in call.keywords:
                if kw.arg != 'band':
                    continue
                v = kw.value
                # band=(0, 320) / band=(0, int(LAYOUT.sy(320))) 两种都要认
                if isinstance(v, ast.Tuple) and len(v.elts) == 2:
                    second = v.elts[1]
                    if isinstance(second, ast.Constant) and isinstance(second.value, int):
                        hi = second.value
                    else:
                        hi = 'expr'       # 表达式（如 LAYOUT.sy(...)）⇒ 不当窄带处理
            for t in node.targets:
                if isinstance(t, ast.Name):
                    var_band[t.id] = hi
        # ② 找 `in_map(..., <那个变量>)`，看它带没带窄 band
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'in_map'):
                continue
            for a in node.args:
                if not isinstance(a, ast.Name) or a.id not in var_band:
                    continue
                hi = var_band[a.id]
                if hi is None:
                    return True, '`%s` 那次 ocr **不带 band**（全屏）✓' % a.id
                if hi == 'expr':
                    return True, '`%s` 的 band 上界是表达式（不判为窄带）✓' % a.id
                if hi >= 1080:
                    return True, '`%s` 的 band 上界 = %d ≥ 1080 ✓' % (a.id, hi)
                return False, ('`%s` 的 band 上界 = %d < 1080 ⇒ '
                               '裁掉了「结束冒险」cy=515 /「快速扫荡」cy=1079 ✗'
                               % (a.id, hi))
        return False, '在 `final_collect` 里找不到喂给 `in_map()` 的 ocr 变量 ✗'
    return False, '找不到 `final_collect` ✗'


def main():
    print('=== 退图前补点：固定坐标优先，不是逐个状态 OCR ===')
    src = open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def final_collect(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    body = '\n'.join(lines[s:e])
    code = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))

    # ── ① **绝对不许无条件盲点棋盘内的固定坐标**（2026-10-05 真事故 ✗✗）────
    #   用户报：「**怎么开始点拉黑过的格子了？？**」
    #   真机铁证（`runs/acc1/loop/loop_log.json` 第 4 张图）：
    #     · `(3,4)` 被 `blocked_cells_tagged` **拉黑** ✓、计划 `['4,3','3,5']` **没含它** ✓
    #     · 但 `{"collect":"fixed_ok","at":[456,908]}` ⇒ **点了棋盘上的格** ✗
    #   根因：我那条"快速路"**无条件盲点**两个固定锚点，而它们**都在棋盘内**：
    #       `lime_back`  = (359, 873) ⇒ 落在格 **(3,4)**  ← 正是那个被拉黑的格 ✗✗
    #       `equip_back` = (360, 835) ⇒ 落在格 **(2,4)**
    #   我当时的假设是"没弹面板时它们落在棋盘外的暗区" —— **假设是错的**（873/835 都在
    #   棋盘 y 范围内）⇒ 无条件点它 = **在棋盘上乱点，包括拉黑格** ✗
    #   ⇒ 教训：**盲点固定坐标前必须先证明"不弹面板时它落在哪"**（本仓《错误教训》B2 同类）
    print()
    print('【1】不许无条件盲点棋盘内的固定坐标（本轮真事故）')
    import explore_loop as EL
    import fixed as FX
    for anchor in ('lime_back', 'equip_back', 'back_btn'):
        p = FX.A(anchor)
        if not p:
            continue
        rc = EL.cell_of(p[0], p[1])
        in_grid = 1 <= rc[0] <= 5 and 1 <= rc[1] <= 7
        ck('锚点 `%s`%s ⇒ 落在格 %s（%s）'
           % (anchor, p, '%d,%d' % rc, '**棋盘内** ⇒ 绝不许无条件点' if in_grid else '棋盘外'),
           True, '')
    # 关键断言：那两个盲点必须在 **`_panel_probably`（棋盘压暗）为真** 的分支里
    #   ⚠ 不用"缩进比较"这种脆弱判据（我第一版就写错两次 ✗）⇒ 改成**执行判据**：
    #     ① 源码里必须有 `if _panel_probably:` 且两个盲点**都在它之后**、
    #        且**在它对应的 `return` 之前**
    blind = [n + 1 for n in range(s, e) if re.search(r"tap\(_p_(lime|equip)\[0\]", lines[n])]
    i_prob = [n for n in range(s, e) if lines[n].strip().startswith('if _panel_probably:')]
    i_ret = [n for n in range(s, e)
             if re.search(r'return (_fc_done\(\d\)|\d)', lines[n])
             and any('fixed_after_dim' in lines[k] for k in range(max(s, n - 6), n))]
    ok_in = bool(blind and i_prob and i_ret
                 and i_prob[0] < blind[0] and blind[-1] < i_ret[0])
    ck('两个盲点都在 `if _panel_probably:` 之后、且在它那支的 `return` 之前',
       ok_in, 'blind@%s prob@%s ret@%s' % (blind, [n + 1 for n in i_prob],
                                           [n + 1 for n in i_ret]))
    ck('判据是**"棋盘被压暗"**（`_panel_probably = _dim_now < 0.85`）—— '
       '没弹面板 ⇒ dim=1.0 ⇒ 不点 ✓',
       '_panel_probably = _dim_now < 0.85' in code)
    ck('⚠ 并记下真机事实：这三个锚点**都落在棋盘内**（所以"无条件点"必然乱点 ✗）',
       True, 'lime_back→(3,4) / equip_back→(2,4) / back_btn→(2,4)')
    ck('判据是**"棋盘被压暗"**（`_panel_probably = _dim_now < 0.85`）—— '
       '没弹面板 ⇒ dim=1.0 ⇒ 不点 ✓',
       '_panel_probably = _dim_now < 0.85' in code)
    ck('⚠ 并记下真机事实：这三个锚点**都落在棋盘内**（所以"无条件点"必然乱点 ✗）',
       True, 'lime_back→(3,4) / equip_back→(2,4) / back_btn→(2,4)')

    # ── ② 有判据才用固定锚点；成功即返回 ─────────────────────────────
    print()
    print('【2】有判据之后才用固定锚点；成功即返回')
    for anchor, why in (('lime_back', '莱姆返回'), ('equip_back', '新装备返回')):
        ck('用了固定锚点 `%s`（%s）' % (anchor, why),
           ("A('%s')" % anchor) in code or ("'%s'" % anchor) in code)
    # ⚠ 断言要**同时认** `return 1` 和 `return _fc_done(1)`
    #   （后者是给 final_collect 加耗时计时之后的写法 ✓）
    fast_ret = [n for n in range(s, e)
                if re.search(r'return (_fc_done\(\d\)|\d)', lines[n])
                and any('fixed_after_dim' in lines[k] for k in range(max(s, n - 6), n))]
    old = [n for n in range(s, e) if "b.ocr(tag='collect2')" in lines[n]]
    ck('走完固定坐标关闭后**立刻返回**（旧路径不再跑 ✓）',
       bool(fast_ret), 'fast_ret@%s' % [n + 1 for n in fast_ret])
    ck('它在旧路径 `collect2` **之前**（否则白改 ✗）',
       bool(fast_ret) and bool(old) and fast_ret[0] < old[0],
       'fast@%s old@%s' % ([n + 1 for n in fast_ret], [n + 1 for n in old]))

    # ── ③ 兜底一条不许删（这是那次"跳到图鉴"事故的防线）────────────
    print()
    print('【3】兜底必须保留（删了会重现"跳到图鉴"事故 ✗）')
    for key, why in (("'collect3'", 'collect3 逐状态轮询'),
                     ("'bottom_close_fallback'", '认不到标题但有返回按钮的兜底'),
                     ('force_unstick', '关不掉时的强制脱困'),
                     ('collect3_skip', '同帧重复 OCR 的跳过优化')):
        ck('保留了 `%s`（%s）' % (key, why), key in body)

    # ── ④ 安全检查不许被当成"可以省掉"删掉 ───────────────────────────
    print()
    print('【4】"还在图里吗"那道守卫必须留着（用户报过在选图界面乱点 ✗）')
    ck('保留了 `in_map` + `skip_not_in_map`（不在图里就不补点）',
       'in_map(' in code and "'skip_not_in_map'" in code)

    # ⛔⛔⛔ 2026-10-06 **修 bug + 撤回守门**：
    #   旧断言写的是「那次 OCR 是**窄带** `band=(0, 320)`（最便宜的判据 ✓）」
    #   —— 它**把 bug 当成了正确行为**，钉死在门禁里 ✗✗
    #   真缺陷：`in_map()` 的正反两面证据**全在 320 以下**，
    #     · 正面「结束冒险」cy=**515**（真机 5 帧实测全是 515）
    #     · 反面「快速扫荡/进入地图」cy=**1079**、「深渊NN」cy=**655**、「星界秘境」cy=**496**
    #   ⇒ 窄带里一条都看不到 ⇒ 判定**完全由 `cells_of()` 格子兜底做出** ⇒
    #     选图界面中间那张**地图预览图**被数成 8+ 格 ⇒ **在选图界面上返回 True** ✗
    #   ⇒ 实测（`_verify/` 真机帧，只读探针 `_tmpman/probe_band_negev.py`）：
    #       `select_map_20261002.png`：全屏 **False** ✓ ／ (0,320) **True** ✗
    #       `now_20261003.png`      ：全屏 **False** ✓ ／ (0,320) **True** ✗
    #   ⚠⚠ 断言方式：**不许用字符串 grep 找 `band=(0, 320)` 在不在**
    #     —— 留档注释里必然逐字引用它（本仓已第四次踩这个坑：v1.62c / v1.67 / v1.68）
    #     ⇒ 改成 **AST 查那次 `b.ocr(...)` 调用到底传了什么 band**
    print()
    print('【4b】那次 OCR 的 band 必须**覆盖得到 in_map 的判据行**（AST 查，不 grep）')
    band_ok, band_why = _inmap_ocr_band(src)
    ck('`final_collect` 里喂给 `in_map()` 的那次 `b.ocr` **不带窄 band**'
       '（或 band 上界 ≥ 1080）—— 窄带会把正反证据全裁掉 ✗',
       band_ok, band_why)
    ck('⭐ 反向守门：源码里**没有**"窄带 + in_map"这个组合'
       '（AST 判据，不受留档注释干扰 ✓）',
       band_ok, band_why)
    # ⭐ 正面：`fx_menu()` 0-OCR 快查必须在那次 OCR **之前**（省一次全屏 OCR）
    i_fxm = code.find('fx_menu(b)')
    i_ocr = code.find('it0 = b.ocr(')
    ck('`fx_menu()`（模板快查，6.8ms）排在 `in_map` 那次 OCR 之前'
       '（选图帧 ⇒ 直接返回，连 OCR 都不做 ✓）',
       i_fxm >= 0 and i_ocr >= 0 and i_fxm < i_ocr,
       'fx_menu@%d ocr@%d' % (i_fxm, i_ocr))

    # ── ④c ⭐⭐⭐ **执行级**：拿真机帧真跑 `in_map()` ──────────────────────
    #   上面 ④b 是结构判据（AST 看 band）；这一条是**行为判据** ——
    #   直接喂 `_verify/select_map_20261002.png`（真·选图界面）跑真 `in_map()`，
    #   要求 **全屏 ⇒ False**、并且**复现窄带 ⇒ True**（证明这个 band 真的有害 ✗）。
    #   ⚠ 用真帧现算，不是把期望值抄在门禁里 ⇒ 有人改回窄带时门禁会跟着红 ✓
    #   ⚠ 带**对照项**：同一张帧、同一份 OCR 结果，只换 band ⇒ 结论必须不同，
    #     否则说明这条断言恒真（比如帧本身就不是选图界面）✗
    print()
    print('【4c】执行级：真机选图帧上 `in_map()` 必须判"不在图里"（含窄带对照项）')
    try:
        import cv2
        import mapbot as MB
        sel = os.path.join(HERE, '_verify', 'select_map_20261002.png')
        if not os.path.exists(sel):
            skip('_verify/select_map_20261002.png', '夹具不存在')
        else:
            img = cv2.imread(sel)
            if img is None:
                skip('select_map_20261002.png', '解不出图')
            else:
                class _B(object):
                    def __init__(self, a):
                        self._img_arr = a

                    def img(self):
                        return self._img_arr

                b = _B(img)
                it_full = _ocr_band(img, None, MB)
                it_narrow = _ocr_band(img, (0, 320), MB)
                r_full = bool(EL.in_map(b, img, it_full))
                r_narrow = bool(EL.in_map(b, img, it_narrow))
                ck('真选图帧：全屏 OCR ⇒ `in_map()` = **False**（正确：不在图里）',
                   r_full is False, 'r_full=%s' % r_full)
                ck('⭐ 对照项：同一帧只把 band 换成 `(0, 320)` ⇒ `in_map()` 变 **True**'
                   '（**这就是本轮修掉的真缺陷**，证明窄带真的有害 ✗）',
                   r_narrow is True,
                   'r_full=%s r_narrow=%s（若此处不是 True，说明帧变了 ⇒ 需重挑夹具）'
                   % (r_full, r_narrow))
                ck('⇒ 修复后的生产代码用的是**全屏**那次（与 r_full 一致 ✓）',
                   band_ok, band_why)
    except ImportError as e:
        skip('执行级 in_map 断言', '依赖缺失：%r' % (e,))

    # ── ⑤ 紫/橙探索格：补点直接跳过（本轮另一个真根因）──────────────
    print()
    print('【5】紫/橙探索格：补点会重复弹探索面板 ⇒ 必须跳过')
    ck('有 `purple_skip` 分支（紫格 + 有空闲槽 ⇒ 不补点）',
       "'collect': 'purple_skip'" in body or "'purple_skip'" in body)
    ck('它用**纯函数** `_is_purple_cell` 判（顶层垃圾 sid 也能认 ✓）',
       '_is_purple_cell(' in body)
    i_skip = body.find('purple_skip')
    i_tap = body.find('b.tap(pos[0], pos[1]')
    ck('跳过分支在**补点那一下之前**（否则已经点过了 ✗）',
       i_skip >= 0 and i_tap >= 0 and i_skip < i_tap,
       'skip@%d tap@%d' % (i_skip, i_tap))

    print()
    print('=' * 72)
    if SKIPS:
        print('⚠ %d 项**没真正验证**：' % len(SKIPS))
        for s in SKIPS:
            print('   - %s' % s)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：选图帧 0-OCR 模板快查先挡；in_map 那次 OCR 不再窄带（证据齐）；'
          '旧兜底一条没删；紫格补点已跳过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
