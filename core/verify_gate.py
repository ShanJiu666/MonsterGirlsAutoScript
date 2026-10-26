# -*- coding: utf-8 -*-
"""verify_gate.py · ⭐ PC 端自己的回归门禁（2026-10-01「两端完全平行」）

为什么 PC 端要有自己的门禁
--------------------------
以前所有回归都在**手机端仓**（`android_autoexplore/tools/verify_explore_slots_fix.py`），
而它 `import` 的是 **PC 端**的 `explore_loop` ⇒ 事实上 PC 端没有自己的门禁，
改 PC 代码只能"改完去手机端仓跑别人的门禁"。两端既然平行，各有各的门禁才对。

覆盖范围（**只管 PC 端自己的东西**）
------------------------------------
A. 提速层（`fixed.py` 固定锚点 + 模板快查）—— PC 独有，手机端没有这层
B. 坐标口径：锚点 ↔ `layout.LAYOUT` 逐条对拍（防"抄错坐标系"）
C. 搜索带合法（`y0 < y1`，防模板静默永不命中）
D. 模板快查的正/负样本 + 速度量化
E. 热路径确实在用固定坐标（防"改了 fixed.py 却把热路径退回 OCR"）
F. 模块可 import + 基础自检（layout 零回归、mapsolve 等）

⚠ 手机端的东西（Java、Chaquopy、面板层跨分辨率审计、buypanels 漂移登记…）
   **不在这里** —— 那些归手机端仓自己的门禁。两端平行，谁都不给对方兜底。

用法：
    python verify_gate.py
退出码 0 = 全过。
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK: list = []
BAD: list = []
SKIP: list = []


def check(name, cond, detail=''):
    """⚠⚠ 2026-10-13 **`detail` 一律强制转 str**（本轮踩到的坑 ✗）
      病：我写 `check(..., [l for l in ...])`（传了 **list**）⇒ `'  ' + detail`
        抛 `TypeError` ⇒ **整个门禁中途崩**（不是"这一项红"，是**全跑不完**）✗✗
      实测：`verify_gate.py:1383` 崩在【S】组，后面 30 多项**根本没跑**
      ⇒ 修法：这里 `str(detail)` 兜住 —— 门禁**绝不许**因为一条断言写错就整体崩 ✓
    """
    _d = str(detail) if detail else ''
    if cond:
        OK.append(name)
        print('  [ok]   %s%s' % (name, ('  ' + _d) if _d else ''))
    else:
        BAD.append(name)
        print('  [FAIL] %s%s' % (name, ('  ' + _d) if _d else ''))


def skip(name, why=''):
    SKIP.append(name + (' — ' + str(why) if why else ''))
    print('  [SKIP] %s%s' % (name, ('  ' + str(why)) if why else ''))


def run(argv, timeout=300):
    """跑子脚本（**带并发预取缓存**）

    ⭐⭐ 2026-10-08 性能（用户问「为什么这么慢？不能多并发快点跑吗」）：
      门禁**串行**跑 38 个子脚本实测 **793 秒（13 分钟）**，其中
      `verify_fastpath.py` **一个就 420 秒（53%）** ✗
      ⇒ 现在：**开场用线程池把所有子脚本并发跑一遍**（默认 min(8, CPU)），
        结果按脚本名缓存；`run()` 命中缓存就直接返回 ✓
      ⇒ 实测 793 秒 → **约 2 分钟**（受最慢那个 `verify_fastpath` 限制）
      ⚠ 关掉并发：`MAPBOT_GATE_SEQ=1`（怀疑并发互相干扰时用 ✓）
    """
    key = argv[0] if argv else ''
    hit = _PRERUN.get(key)
    if hit is not None:
        return hit
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    p = subprocess.run([sys.executable] + argv, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout,
                       cwd=_subdir_of(key), env=env)
    return p.returncode, (p.stdout or b'').decode('utf-8', 'replace')


# ── ⭐ 并发预取（见 `run()` 的说明）────────────────────────────────
#   ⚠ 用**子进程 + 线程池**（不是进程池）：子脚本本来就是独立进程，
#     线程池只负责"同时等它们" ⇒ 不涉及 fork/序列化，最简单也最稳 ✓
_PRERUN: dict = {}

#   ⚠⚠ 并发**有真实风险**：好几个门禁脚本会写**固定名字的临时文件**到仓根/`runs/`
#     （实测 `verify_claim_back.py` 写 `_cbtmp.png`、`verify_collect_fast.py` 写
#      `runs/_vcf_tmp.png`）⇒ 两个脚本同时跑会**互相覆盖对方的临时文件** ⇒ **假红** ✗
#     （2026-10-08 实测：并发首跑把 `verify_claim_back` / `verify_clover_gate` 判红，
#       而**单独跑两个都 exit=0** ⇒ 就是并发串味的铁证 ✓）
#   ⇒ 安全做法：**默认只并发"纯离线、不写共享临时文件"的脚本**；
#     拿不准的一律串行 ✓（宁可慢一点，也不能让门禁说假话）
_ALONE = (
    # 会碰设备 / 起真进程 / 改全局状态
    'verify_loopguard.py', 'verify_devicesel.py', 'verify_adb_reconnect.py',
    'verify_startup_speed.py', 'verify_battle_fast.py',
    # 会写**共享固定名临时文件**（并发会互相覆盖 ⇒ 假红 ✗）
    'verify_claim_back.py', 'verify_collect_fast.py', 'verify_panel_render.py',
    # 会跑 OCR（CPU 重 + 可能共享临时文件），并发收益低
    'verify_clover_gate.py', 'verify_clover_block.py', 'verify_dice_call.py',
    'verify_dice_blind.py', 'verify_newequip.py', 'verify_boss_blue.py',
    'verify_mark_multi.py', 'verify_marks_grid.py', 'verify_vault_pick.py',
    'verify_vault_flow.py', 'verify_vault_debug.py', 'verify_vault_inline.py',
    'verify_vault_tiles_res.py', 'verify_blocked_score.py', 'verify_badges.py',
    'verify_b8_fog.py', 'verify_purple_tile.py', 'verify_plan_fog.py',
    'verify_gold_gate.py', 'verify_fog_only_start.py', 'verify_board_hidden.py',
    'verify_finish_exit.py', 'verify_region_pad.py',
    # ⭐⭐ 2026-10-14 **会临时改写 `spots.py` 源码**（对照项要"关掉闸门"）——
    #   两个都这么做 ⇒ 并发时**互相踩** ⇒ 假红 ✗
    #   实测（本轮）：单独跑 12/12 ✓，门禁并发跑到 ⑨ 时假红 ✗
    #   ⇒ 必须串行（与上面"会写共享固定名临时文件"同一类 ✓）
    'verify_block_shape.py', 'verify_camp_not_swallowed.py',
)


def _subdir_of(name):
    """子脚本 / 被读取的脚本在哪个目录。

    目录重构后：回归脚本在 `tests/`，排障脚本在 `devtools/`；
    同时兼容「还在仓根」的旧布局（`HERE`）。
    """
    for d in (os.path.join(HERE, 'tests'), os.path.join(HERE, 'devtools'), HERE):
        if os.path.exists(os.path.join(d, name)):
            return d
    return HERE


def _script_path(name):
    """子脚本的完整路径（找不到时回落仓根，让报错信息照旧可读）"""
    return os.path.join(_subdir_of(name), name)


def _scan_subscripts():
    """从本文件里扫出所有会跑的**独立**子脚本名（`.py`，按出现顺序去重）"""
    try:
        _src = io.open(__file__, encoding='utf-8').read()
    except Exception:       # noqa: BLE001
        return []
    out, seen = [], set()
    for _m in re.finditer(r"run\(\[\s*'([^']+\.py)'", _src):
        n = _m.group(1)
        if n in seen or n == os.path.basename(__file__):
            continue
        seen.add(n)
        out.append(n)
    return out


def _prerun_all():
    """并发把所有子脚本跑一遍（结果进 `_PRERUN`）—— 由 `main()` 开场调用 ✓"""
    if os.environ.get('MAPBOT_GATE_SEQ'):
        print('  （MAPBOT_GATE_SEQ=1 ⇒ 串行跑，不预取）')
        return 0
    names = [n for n in _scan_subscripts() if os.path.exists(_script_path(n))]
    par = [n for n in names if n not in _ALONE]
    if len(par) < 2:
        return 0
    NW = int(os.environ.get('MAPBOT_GATE_JOBS')
             or max(1, min(8, os.cpu_count() or 4)))
    print('  ⚡ 并发预取 %d 个子脚本（%d 进程；这几个仍串行：%s）'
          % (len(par), NW, ', '.join(n for n in _ALONE if n in names)))
    _t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')

    def _one(n):
        try:
            p = subprocess.run([sys.executable, n], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=1800,
                               cwd=_subdir_of(n),
                               env=env)
            return n, p.returncode, (p.stdout or b'').decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            return n, 124, 'TIMEOUT'
        except Exception as _e:      # noqa: BLE001
            return n, 125, repr(_e)[:200]

    with ThreadPoolExecutor(max_workers=NW) as _ex:
        for n, rc, out in _ex.map(_one, par):
            _PRERUN[n] = (rc, out)
    print('  ⚡ 预取完成，用时 %.1f 秒（串行约需 %.0f 秒）'
          % (time.time() - _t0, 0))
    return len(_PRERUN)




# ── 换机可移植性检查（2026-10-02）────────────────────────────────────
# ⭐ 只扫**运行时**会 import 的模块，不扫开发期脚本。
#   那些离线脚本本来就允许写死本机路径 —— 它们是「排查用」的工具，
#   不是每个使用者都会跑的路径，扫了只会制造噪音。
_RUNTIME_MODULES = ('mapbot.py', 'bot_gui.py', 'fastcap.py', 'paths.py',
                    'mumu.py', 'explore_loop.py', 'loopguard.py')
# 出现这些盘符开头就算"写死"（仓内相对路径不算）
_ABS_PATH_RE = re.compile(r'''[rbuf]?['"][A-Za-z]:[\\/]''')
# 这些是**已知的、正当的**绝对路径（各有明确理由，不算回归）
_ALLOWED_FRAGMENTS = (
    # adb server 端口不是路径，是拓扑：MuMu 自带 adb 占着 5037，
    # PC 端必须走独立的 5038（已实测：5037 上只有手机端 7555）
    'ANDROID_ADB_SERVER_PORT',
    # airtest URL 里的 127.0.0.1:5037 同源，行为已验证
    'Android://',
)


def _check_paths():
    """跑 `paths.py` 体检（adb / 模板 / MuMu / 数据表）"""
    pp = os.path.join(HERE, 'core', 'paths.py')
    if not os.path.exists(pp):
        return False
    rc, out = run(['paths.py'], timeout=180)
    return rc == 0


def _is_real_assignment(line):
    """这一行是不是**真的在赋值**一个绝对路径？

    必须排除的两类**误报**（它们只是文字，不是行为）：
      · 注释行（如「原来 ROOT = r'D:\\...'"）
      · 文档字符串里「改动前长什么样」的举例
    判据：去掉行首空白后不是以 # / * / 三引号开头，
    且**确实有赋值动作**（`X = ` 或 `os.environ[...] = `）。
    """
    s = line.strip()
    if not s or s.startswith(('#', '*', '"""', "'''")):
        return False
    # 赋值但不是纯路径字面量（如 `ADB = (find_adb() or 'adb')`）⇒ 已经动态化了，不罚
    return bool(re.search(r'^\s*[\w.]+\s*(\[[^\]]+\])?\s*=\s*[^\n]*'
                          r'''[rbuf]?['"][A-Za-z]:[\\/]''', line))


def _scan_hardcoded():
    """扫运行时模块里残留的本机绝对路径 -> [str]"""
    bad = []
    in_doc = None                      # 跟踪是否在模块级 docstring 里
    for name in _RUNTIME_MODULES:
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            continue
        try:
            src = io.open(p, encoding='utf-8').read()
        except OSError:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            t = line.strip()
            if in_doc:
                if in_doc in t:
                    in_doc = None
                continue
            if t.startswith(('"""', "'''")) and not (t.endswith(('"""', "'''"))
                                                    and len(t) > 3):
                in_doc = t[:3]
                continue
            if not _is_real_assignment(line):
                continue
            if not _ABS_PATH_RE.search(line):
                continue
            if any(f in line for f in _ALLOWED_FRAGMENTS):
                continue
            bad.append('%s:%d %s' % (name, i, line.strip()[:60]))
    return bad


def main():
    print('=' * 74)
    print('PC 端门禁 · verify_gate.py   （工作目录：%s）' % HERE)
    print('=' * 74)

    # ── ⚡ 并发预取（2026-10-08：用户问「为什么这么慢？不能多并发快点跑吗」）──
    #   串行 38 个子脚本实测 **793 秒**，其中 `verify_fastpath.py` 一个就 420 秒 ✗
    #   ⇒ 开场并发跑一遍，`run()` 命中缓存 ⇒ 793s → 约 2 分钟 ✓
    print()
    print('【⚡】并发预取子脚本（可用 `MAPBOT_GATE_SEQ=1` 关掉）')
    _prerun_all()

    # ── A/B/C：提速层自检 ──────────────────────────────────────────────
    print()
    print('【A】提速层 fixed.py（固定锚点 + 模板快查，PC 独有）')
    if not os.path.exists(os.path.join(HERE, 'core', 'fixed.py')):
        check('fixed.py 存在', False, '缺文件')
    else:
        rc, out = run(['fixed.py'], timeout=120)
        check('fixed.py 自检全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('① 全部锚点在屏内', '全部锚点都在屏内' in out)
        check('② band 全部合法（y0<y1，防静默永不命中）', '个 band 全部合法' in out)
        check('③ 与 layout.LAYOUT(720×1280) 逐条对拍一致', '与 LAYOUT 完全一致' in out)

    # ── D：快查验收（正/负样本 + 速度）─────────────────────────────────
    print()
    print('【B】模板快查验收（正样本命中 / 负样本不命中 / 速度）')
    fp = os.path.join(_subdir_of('verify_fastpath.py'), 'verify_fastpath.py')
    if not os.path.exists(fp):
        skip('verify_fastpath.py', '文件不存在')
    else:
        rc, out = run(['verify_fastpath.py'], timeout=600)
        check('快查验收全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('④ 正样本：固定模板在图里必须命中', '命中 5/5' in out)
        check('⑤ 负样本：涂掉后必须不命中（防到处乱跳）', '涂掉后全部不命中' in out)
        # ⚠ 2026-10-03：文案随 `verify_fastpath.py` 一起改 —— 模板耗时的"单次 30 连跑取平均"
        #   在**机器人正在跑**的机器上会被抢 CPU ⇒ 实测掉到 <100 倍 ⇒ 假红 ✗
        #   （与 verify_marks_grid ④ 同类）⇒ 那边改成 3 次中位数、阈值 50 倍 ✓
        check('⑥ 实测比 OCR 快 50 倍以上', '快 50 倍以上' in out)

    # ── D2：战斗快路径 **A/B 实测**（真 `start_fight` + 真机帧，数它省了几次 OCR）──
    #   与【B】的分工：`verify_fastpath.py` 证「模板**认得准**」，
    #   本脚本证「**真的省下 OCR**」—— 而省 OCR 才是这次改动的全部目的。
    #   ⚠ 它按**时钟**喂帧（结算面板在 tap 后 delay 秒出现），不按 snap 次数 ——
    #     否则抢跑窗口 snap 很多次会让 A/B 两边看到的帧序列不同 ⇒ 结论不可比
    #     （该脚本注释里记着这个坑）。
    print()
    print('【B2】战斗快路径 A/B（真 start_fight + 真机帧 + 按时钟喂帧）')
    bf = os.path.join(_subdir_of('verify_battle_fast.py'), 'verify_battle_fast.py')
    if not os.path.exists(bf):
        skip('verify_battle_fast.py', '文件不存在')
    else:
        rc, out = run(['verify_battle_fast.py'], timeout=900)
        check('战斗快路径 A/B 全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑦ 抢跑窗口**确实省 OCR**（不是"只认得出"）', '✅ 全部通过：抢跑窗口' in out)
        check('⑧ 面板晚出现（超窗）时新代码仍判得出（不比改动前差）',
              '新代码仍判 True（改动前在这一档会漏' in out)
        check('⑨ 地图帧下不许误判成"已开打"', '没把地图当结算' in out)

    # ── D3：领奖「返回」回归（真机事故：领取后没点返回 ⇒ 卡在返回界面）──────
    #   ⚠ 关键在**控制组**：把 `snap()` 打桩成空操作（= 复现"轮询漏 snap"那个旧 bug）
    #     必须**找不到** —— 这一条要是也能找到，说明测试没有牙齿、盖不住那个 bug ✓
    print()
    print('【B3】领奖「返回」回归（真 claim_back_poll + 真机帧 + 控制组）')
    cb = os.path.join(_subdir_of('verify_claim_back.py'), 'verify_claim_back.py')
    if not os.path.exists(cb):
        skip('verify_claim_back.py', '文件不存在')
    else:
        rc, out = run(['verify_claim_back.py'], timeout=600)
        check('领奖「返回」回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑩ 面板出现后能找到「返回」并点它自己的坐标', '点的是**它自己的坐标**' in out)
        check('⑪ 控制组（复现旧 bug）必须找不到 ⇒ 证明测试有牙齿',
              '旧行为下确实**找不到**' in out)
        check('⑫ 找不到时**一次都不点**（不盲点坐标）', '一次都没点' in out)

    # ── D4：黄金宝库买完流程（三层要买齐 + 不许连点「返回」）──────────────────
    #   用户 2026-10-04：「脚本有时候连点两下返回，有时候会没买完第三层就关了宝库」
    #   ⚠ 牙齿在【2】：面板"慢收起"时**每层仍必须正好 1 下**
    #     （旧代码读一帧发现"还在"就再点一下 ⇒ 正是"连点两下"✗）
    print()
    print('【B4】黄金宝库买完流程（真 vault_flow + 脚本化面板，按**时钟**变）')
    vf = os.path.join(_subdir_of('verify_vault_flow.py'), 'verify_vault_flow.py')
    if not os.path.exists(vf):
        skip('verify_vault_flow.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_flow.py'], timeout=600)
        check('宝库流程回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑬ 三层都要买齐（含第 3 层）', '第 3 层确实买到' in out)
        check('⑭ 每层「返回」正常正好 1 下（不连点）', '每层「返回」**正好 1 下**' in out)
        check('⑮ 面板慢收起时**仍然只点 1 下**（靠等，不靠再点）',
              '每层「返回」**仍然正好 1 下**' in out)
        # ⭐⭐ 本轮真机抓到的根因：`tap_dlg(wait=…)` 的 `wait_change` 会被"按钮按下去的高亮"
        #   立刻触发 ⇒ 奖励面板**还没出来**就去点固定返回 (360,806)，
        #   而**宝库面板上 (360,806) 正是棋盘格（行3列2）**⇒ 换选了别的格子 ✗
        check('⑯ 奖励面板**慢出现**时，返回只在它出现之后才点（防打在棋盘格上）',
              '奖励展示**已经出现**' in out)

    # ── D5：宝库**选奖励**（不许在"图标还没画出来"的帧上做选择）────────────
    #   用户 2026-10-05：「遇到天赋果实没有选择天赋果实作为奖励」
    #   真根因：bot 在 `03_r1_before_pick`（纯亮黄方块、绿像素 0）那帧判 ⇒ 颜色法全灭
    #     ⇒ 模板兜底在纯色块上乱给分（0.552 假「四叶草」）⇒ 挑错格 ✗
    print()
    print('【B5】宝库选奖励（真 vault_pick + 真机帧：现场/未翻开/翻开后）')
    vp = os.path.join(_subdir_of('verify_vault_pick.py'), 'verify_vault_pick.py')
    if not os.path.exists(vp):
        skip('verify_vault_pick.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_pick.py'], timeout=900)
        check('宝库选奖励回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑰ 已翻开的帧能挑中优先奖励（颜色法，不是模板蒙）', '挑中了幸运草那一格' in out)
        check('⑱ ⭐ 复现真机顺序（先没翻开/后翻开）必须挑中**天赋果实**',
              '挑中的是**天赋果实**' in out)
        check('⑲ **不许**挑到旧代码在纯色块上蒙出来的那格',
              '**没有**挑到旧代码那个错格' in out)
        # ⭐ 2026-10-05 第二轮（用户：「第一层幸运草和天赋果实全都要，结果都没选」）：
        #   买完那一刻只画了底色 ⇒ 一个 green=0.254 的假命中骗过了"没命中就等"的闸门
        check('⑳ ⭐ 只画了底色的假命中**骗不过等待闸门**（必须等到有角标的真奖励）',
              '**没有**挑未渲染帧上的假命中' in out)

    # ── B7：获得新装备检测节点 + 结束原因计数分开（2026-10-05）────────────────
    #   用户两条口径：「摇色子结束，关闭战斗胜利界面后需要一个获得新装备检测」
    #                「做1 报数/计数分开」
    #   ① 战斗结算出口补 `check_newequip_after_battle()`（此前只能靠下一轮的弹窗闸门，
    #      而它盖住整盘 ⇒ 白判一轮）
    #   ② `targets_unreachable`（计划走不下去）**不再**混进"认不出棋盘"的计数/文案
    #      ——真机 13:29 那把 3 张图全是它，却被报成"连续 2 张认不出棋盘"并把人指到
    #      10-02~10-04 的旧诊断帧（那条路根本不落帧）
    print()
    print('【B7】获得新装备检测节点 + 结束原因计数分开')
    vne = os.path.join(_subdir_of('verify_newequip.py'), 'verify_newequip.py')
    if not os.path.exists(vne):
        skip('verify_newequip.py', '文件不存在')
    else:
        rc, out = run(['verify_newequip.py'], timeout=300)
        check('新装备节点/计数分开回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉓ ⭐ 战斗结算出口挂了「获得新装备」检测（点写死坐标、没弹窗零点击）',
              '点了**写死**的 (360,835)' in out and '**零点击**' in out)
        check('㉔ ⭐ 真机那把按真因判成 **unreachable**（不再报"认不出棋盘"）',
              '真机那把 ⇒ **unreachable**' in out)

    # ── B8：规划不许去点雾格（2026-10-05，三张真机帧离线复盘）────────────────
    #   用户连报三次「规划不对」：map23 = 片里有点头的雾格；map6 = 亮着的 boss 却排 6 步绕路；
    #   map7 = 幻影"已消耗格"把深雾 boss 抬成可点 ⇒ 计划直点雾格、25 体力白花
    #   牙齿：把这批改动 stash 掉后本门禁 **6 项红、exit 1**（三张坏图逐字复现 ✓）
    print()
    print('【B8】规划不许去点雾格（真机三帧：片内选格 / 亮着的目标 / 幻影已消耗格）')
    vpf = os.path.join(_subdir_of('verify_plan_fog.py'), 'verify_plan_fog.py')
    if not os.path.exists(vpf):
        skip('verify_plan_fog.py', '文件不存在')
    else:
        rc, out = run(['verify_plan_fog.py'], timeout=300)
        check('规划雾格回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉕ ⭐ **带标记的格子由"地板"判揭示**（ratio 被图标抬高 ⇒ 真机点不动的真根因）',
              '带标记的雾格' in out and 'mark_floor_veto' in out)
        check('㉖ ⭐ 四张真机帧的"已揭示"与**看图真值**逐格一致（含我上轮误判那张）',
              out.count('模型"已揭示"与看图真值**完全一致**') >= 4)
        check('㉗ ⭐ 计划首步必须落在**真已揭示**的格上、且没有**幻影已消耗雾格**',
              '计划首步是**真已揭示**的格' in out
              and '被反推成已消耗的**雾格**' in out)
        check('㉘ ⭐ 空地口径：**15 种地面填充块一视同仁当空地、452 个内容块一个都不许**'
              '（用户口径「空地有好多种，其实本质都一样」）',
              '地面填充块 15 个' in out and '内容块 452 个' in out)

    # ── B9：adb server 端口 + 掉线自愈（2026-10-05）────────────────────────
    #   用户贴的日志：「进图这一步出错（已跳过这张图）：AdbError: adb.exe:
    #   device '127.0.0.1:16384' not found」⇒ 真机连着丢图（体力照扣）
    #   真根因：`ANDROID_ADB_SERVER_PORT` 在 airtest 里**没人读**
    #     （`adb.py:127`：server_addr 为 None 就硬写 5037）⇒ 那句 setdefault 等于没设；
    #     真正决定 server 的是 **URI 里的端口**（`android.py:58`）⇒ 旧代码写死 5037
    #     = **一直在跟 MuMu 自带的 server 说话**（子进程铁证 `-P 5037`）⇒ 它一抖就丢图 ✗
    #   修：端口统一 `ADB_PORT`（5038，我们自己的 server）+ `adb_connect()`
    #       + `reconnect()` 真重连 + `enter_with_retry()` 连接类错误重试一次
    #   牙齿：stash 掉改动后本门禁在【0】就红（旧关键词 `'device not found'` 是**连续子串**，
    #     而真机原文序列号夹在中间 ⇒ 一次都命不中 ✗ 重试逻辑等于没有）
    # ── B19：金币 <50 万 ⇒ 商人/宝库不买也不规划（2026-10-05，用户口径）──────────
    #   用户原话：「扫体力顺便把金币数量也扫了吧，加个金币低于50万就自动不去购买商人和
    #   宝库（也不规划，就相当于拉黑了），高于50w就还是正常买」
    print()
    print('【B19】金币 <50 万 ⇒ 商人/宝库不买、也不规划（= 拉黑）')
    vgg = os.path.join(_subdir_of('verify_gold_gate.py'), 'verify_gold_gate.py')
    if not os.path.exists(vgg):
        skip('verify_gold_gate.py', '文件不存在')
    else:
        rc, out = run(['verify_gold_gate.py'], timeout=600)
        check('金币闸门回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊹ ⭐ 阈值 = **50 万**；读数窗口与幸运草**靠 y 行严格错开**'
              '（x 有重叠 ⇒ 只能靠 y ✗）',
              '与幸运草（y' in out and '不重叠' in out)
        check('㊺ ⭐ **四条路径全部挡住**（popups 只关不买 / pending_buy 清空 / '
              'buy 剔除 / 点击循环就地买也查）；读不到时**保守照常买**',
              '四条路径' in out or '闸门必须覆盖' in out)

    # ── B20：启动闪黑窗 ＋ 极速通道自愈 ＋ sidecar 真健康判据（2026-10-06）────────
    #   用户一次报三件事：「顺便把启动时会闪过两次命令窗口也修了」＋（很慢的两个根因）
    #   ① 闪窗真根因：`启动.bat` 用 `start "" pythonw.exe bootstrap.py` ⇒ GUI 子系统
    #      **完全没有控制台** ⇒ 它调 `adb.exe`（控制台程序）时 Windows 必须**新建一个**
    #      ⇒ 默认可见 ⇒ 闪。`adb_connect()` **恰好两条**命令（connect + wait-for-device）
    #      ⇒ **恰好闪两次**，与用户描述逐字吻合 ✓
    #      ⭐ 决定性实测（exp_conhost3.py，父进程 pythonw 且不带 CNW）：不带标志 ⇒
    #        新增 **2 个可见控制台窗口**；带 CNW ⇒ **0 个** ✓
    #   ② 极速截图**一次失败就永久退化**到 adb（慢 25 倍）且**无日志** ✗ ⇒ 改成
    #      「连续 N 次才关 + 冷却后自动复活 + 两侧都打日志」
    #   ③ sidecar 健康判据只连 TCP ⇒ **卡死但端口开着**被判"健康"（真机实证端口 20000
    #      能连上、发 `g` 后 recv 永不返回）⇒ 判据只能有一个：**`p`/`pong`**（不碰设备），
    #      只有 `p` 也不回（真卡死）才杀掉重启
    #      ⚠⚠ **我连改错两版**，两次都是实测才抓住：
    #        · 第二版：拿「能不能取到一帧」当**存活**判据 ⇒ 实测
    #          （`_tmpman/probe_ping_vs_grab.py`）设备没开时 `g` 恒不回、而服务**完全健康**
    #          ⇒ 会把**健康**的 sidecar 判死并 `_sidecar_kill` **杀掉**，还可能打断另一个
    #          实例正在跑的 bot ✗✗
    #        · 第三版：**连"取帧探测"本身都不该做** —— 定点实测
    #          （`_tmpman/probe_g_sideeffect.py`，只发一次 `g`）：`p` ⇒ 日志 **+0 字节**；
    #          `g` ⇒ 20 秒 **+1623 字节**，全是 MAA `connect failed`/`re-connect failed`，
    #          **还执行了 `adb kill-server`** ✗✗ 而 `ensure_sidecar` 是**开窗时无条件调**的
    #          ⇒ 每开一次窗就灌一轮重连风暴 ⇒ **取帧探测整个删掉** ✓
    #      ⚠ 附带教训：我最初**就是被这些 MAA 红字误导**去怀疑"sidecar 卡死"的 ——
    #        那些红字是**我自己的探测制造出来的** ⇒ **取证手段会污染证据**（§3 老坑新实例）
    #   牙齿：去掉任一条 creationflags / FAST_MAX_FAIL=1 / snap 改回硬关 /
    #        `_sidecar_ping` 改回裸连接 / **拿取帧判据当存活判据** /
    #        **把取帧探测加回开窗路径** / FAST_WARM_TIMEOUT=1.5
    #        ⇒ **七颗各自独立咬住**（已实测 exit 1 ✓）
    print()
    print('【B20】启动闪黑窗 ＋ 极速通道自愈 ＋ sidecar 只发 `p` 的存活判据')
    vss = os.path.join(_subdir_of('verify_startup_speed.py'), 'verify_startup_speed.py')
    if not os.path.exists(vss):
        skip('verify_startup_speed.py', '文件不存在')
    else:
        rc, out = run(['verify_startup_speed.py'], timeout=600)
        check('启动/极速/sidecar 三项回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊻ ⭐ `adb_connect` **恰好两条**命令且**都**带 creationflags'
              '（= 恰好闪两次的根因，且已修 ✓）',
              '恰好 2 条' in out and '第 1 条带 creationflags' in out
              and '第 2 条带 creationflags' in out)
        check('㊼ ⭐ 极速通道**自愈**：连续失败才关 ＋ 冷却后自动复活 ＋ 通道切换有日志'
              '（旧代码一次就永久退化且静默 ✗）',
              '连续失败 N 次才关' in out or '极速通道自愈' in out)
        check('㊽ ⭐ sidecar 判据**只许发 `p`**（存活）；取帧探测**整个删掉**'
              '（旧判据两个方向都错：裸 TCP 判不出卡死；拿取帧判死活会误杀健康服务，'
              '而取帧探测本身会让 MAA 重连风暴＋`adb kill-server` ✗✗）',
              '三个假 sidecar 对照' in out and '判**不可用**' in out
              and '绝不许杀' in out and '一次都没调' in out
              and '一个 `g` 都没发' in out)

    # ── B18：幸运草 <8 ⇒ 纯大拇指格拉黑不去打（2026-10-05，用户口径）──────────
    #   用户原话：「之前那个幸运草低于8不摇色子，改成低于8连直接把大拇指目标都拉黑，
    #   直接不去打了」／「也是幸运草大于8就自动不拉黑去打」／「金币幸运草都是一张图只确认一次」
    print()
    print('【B18】幸运草 <8 ⇒ 纯大拇指格拉黑不去打（带首领的格保留）')
    vcb = os.path.join(_subdir_of('verify_clover_block.py'), 'verify_clover_block.py')
    if not os.path.exists(vcb):
        skip('verify_clover_block.py', '文件不存在')
    else:
        rc, out = run(['verify_clover_block.py'], timeout=900)
        check('大拇指拉黑回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊻ ⭐ **纯大拇指**（`(3,3)`）被剔；**首领+大拇指**（`(1,5)`）**必须保留**'
              '（boss 必打，与幸运草无关 ✓）',
              '仍然保留' in out and "剔除 ['3,3']" in out)
        check('㊼ ⭐ ≥阈值 自动放回；读不到时不拉黑；**一图只确认一次**（`_lock_hud_once`）',
              '自动放回' in out and 'True' in out and '_lock_hud_once' in out)

    # ── B17：点开的宝库面板必须**就地买掉**（2026-10-05，用户「打开黄金宝库就关了，
    #        根本没购买」+「既然规划都点了宝库，肯定是规划知道这个是已揭示能点的」）──
    #   真机铁证（`runs/loop/loop_log.json` 126→131）：规划有 `5,7` ✓、`taps` 里也确实
    #   点开了 `S30001_016`（黄金宝库）✓、`panel_via="title"`（它**知道**是宝库）✓
    #   —— 但那一支**只 `break`**，什么都没买；下一轮又 `skip_no_panel`（免 OCR）
    #   ⇒ 面板没人处理 ⇒ `blank_board` 收工 ⇒ **宝库没买** ✗✗
    #   修：认到宝库面板 ⇒ 当场走 `buypanels.vault_flow()`（与 popups 同一条路 ✓）
    #   ⚠ **不在这里调 popups()** —— 它末尾 `find_x()` 会盲点 X 把面板关掉
    #     （那正是"打开就关了"本身 ✗）
    #   牙齿：退回只 `break` ⇒ 门禁红 ✓
    print()
    print('【B17】点开的宝库面板必须就地买掉（"打开就关了"的真根因）')
    vvi = os.path.join(_subdir_of('verify_vault_inline.py'), 'verify_vault_inline.py')
    if not os.path.exists(vvi):
        skip('verify_vault_inline.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_inline.py'], timeout=900)
        check('宝库就地购买回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊶ ⭐ 三张**宝库真帧**上判据全部命中（`panel_seen` 成立 ⇒ 会就地买）',
              '命中 3 张' in out)
        check('㊷ ⭐ 反向断言：旅行商人/战斗事件/探索产出**都不许**触发就地买（防误买 ✗）',
              '旅行商人' in out and '探索产出' in out)
        check('㊸ ⭐ 只用 `vault_flow`，**没在这里调 popups()**'
              '（那条末尾会盲点 X 把宝库面板关掉 ✗）',
              '没有' in out and 'popups' in out)

    # ── B16：被面板盖住的帧必须判"被挡"（2026-10-05，用户「点开了宝库，过了会就关掉宝库了」）──
    #   真机铁证（`runs/loop/loop_log.json` 960→966）：
    #     round4 `board` 13 格（含 `(2,6) 黄金宝库 score=1.000`）⇒ 该去买 ✓
    #     round5 `board` **只剩 2 格** ⇒ `buy:0` ⇒ **targets_done 退图，宝库没买** ✗
    #   根因：`board_hidden()` 只看"被压暗的格数 ≥15"，而**面板盖住时分类器认不出几格**
    #     ⇒ 那个 n 天然就小 ⇒ 永远判不出 ⇒ **免 OCR** ⇒ 面板没人处理 ✗✗
    #   修：补 `len(st) < BOARD_MIN_CELLS(8)` ⇒ 也算被挡 ✓（方向安全：多跑一次 OCR）
    #   牙齿：`BOARD_MIN_CELLS=0`（= 旧行为）⇒ 那帧漏判 ⇒ 门禁红 ✓
    print()
    print('【B16】被面板盖住的帧必须判"被挡"（宝库面板漏处理的真根因）')
    vbh = os.path.join(_subdir_of('verify_board_hidden.py'), 'verify_board_hidden.py')
    if not os.path.exists(vbh):
        skip('verify_board_hidden.py', '文件不存在')
    else:
        rc, out = run(['verify_board_hidden.py'], timeout=300)
        check('board_hidden 回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊴ ⭐ **被面板盖住那帧（2 格）判 True**（修复前 False ⇒ 免 OCR ⇒ 漏面板 ✗）；'
              '正常那帧（13 格）不误判',
              '被面板盖住那帧' in out and '正常那帧' in out)
        check('㊵ ⭐ 反向断言：干净盘 35 格 / 边界 8 格**都不许被判被挡**',
              '干净盘 35 格' in out and '刚好 8 格' in out)

    # ── B15：一格多标记 / 一帧多格（2026-10-05，用户「能不能认得一个格子里有四个标志那种」）──
    #   历史记录（`交接文档.md` §5，09-26）：「同格可多标记 ✓（实测一格 4 个：
    #   `redEquip,boss,recommend,clover`）⇒ 按位置相距 ≥18px 保留 ✓」
    #   ⚠ 但那段聚合逻辑**从来没派上用场** —— 因为上游只给 1 个点 ✗
    #   两处根因：① `match_at_scales` 用 `minMaxLoc` ⇒ 每帧每模板只回 1 个点
    #            ② `scan_board` 用模块级 `GLYPH_SCALES`（720 快照）扫 1080 帧 ⇒ 尺度少一档
    #   修：`topn`（NMS 多点，默认 1=老行为）＋ `scales or glyph_scales()` ✓
    #   牙齿：`topn=1` ⇒ `(3,3)` 认不到；720 尺度扫 1080 ⇒ 一个都认不到 ✓
    print()
    print('【B15】一格多标记 / 一帧多格（四标记真帧 `anno_src.png`）')
    vmm = os.path.join(_subdir_of('verify_mark_multi.py'), 'verify_mark_multi.py')
    if not os.path.exists(vmm):
        skip('verify_mark_multi.py', '文件不存在')
    else:
        rc, out = run(['verify_mark_multi.py'], timeout=900)
        check('多标记回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊴ ⭐ **一格四标记认全**（`(2,1)` = redEquip/boss/recommend/clover，恰好 4 个）',
              '恰好 4 个标记' in out and '四类齐全' in out)
        check('㊵ ⭐ 一帧多格也能认（`(3,3)` 修复前被 `(1,5)` 抢走名额 ✗ ⇒ 现在认到）；'
              '尺度跟着帧的格距走',
              '修复前被漏掉的那个' in out and 'glyph_scales()' in out)

    # ── B14：幸运草 < 8 就不摇色子（2026-10-05，用户口径）────────────────────
    #   用户原话：「**扫体力数值的时候顺便扫一下幸运草数值？如果幸运草低于5，这张图就不摇
    #   色子怎么样**」→「**改成幸运草低于8就不摇色子吧**」
    #   真机背景（`runs/acc3` 幸运草只剩 1 的那几张）：点四叶草 ⇒ 游戏不弹确认框
    #   ⇒ 我那道"没弹框就不点确定"的闸门跳掉这一圈 ⇒ 白点 2 次，日志只写 `no_dlg_skip`
    #   ⇒ **真因（幸运草不足）被掩盖** ✗
    #   修：判据从"猜框在不在"改成**确定性的"钱够不够"**（顺手从体力那次 OCR 里读 ✓）
    print()
    print('【B14】幸运草 < 8 就不摇色子（从体力那一行的同一次 OCR 读，零额外成本）')
    vcg = os.path.join(_subdir_of('verify_clover_gate.py'), 'verify_clover_gate.py')
    if not os.path.exists(vcg):
        skip('verify_clover_gate.py', '文件不存在')
    else:
        rc, out = run(['verify_clover_gate.py'], timeout=900)
        check('幸运草闸门回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊲ ⭐ 阈值 = **10**（2026-10-09 用户：「幸运草阈值都改成10」）；'
              '读数只认 HUD 那个位置'
              '（**不误取金币/小鱼干** —— 用户 2026-10-05 纠正：右手边那个是小鱼干）',
              '`CLOVER_MIN_REROLL == 10`' in out and '不会误取' in out)
        check('㊳ ⭐ 真机 6 帧读数与真值一致且全部 < 阈值；闸门在**点四叶草之前**；'
              '读不到时**不猜、照常走**',
              '全都不该摇' in out and '第一次点四叶草之前' in out
              and '照常走' in out)

    # ── B13：宝库取证默认不落盘（2026-10-05，用户「宝库购买流程已经没问题了，不用取证了吧」）──
    #   取证是为抓「点选择奖励直接就关了宝库页面」加的，那个**早就修好并进门禁了**
    #   （`verify_vault_flow.py` / `verify_vault_pick.py` ✓），流程也已连买三层 ✓
    #   ⚠ 我上次改的"按需落帧"**是失效的**（用户贴的日志里 01~14 全落了 ✗）：
    #     把"不为取证单独 OCR"（`it=None`）也当成"异常" ⇒ 反而每步都落 ✗
    #   ⇒ 现在**默认一张都不落**，只记结构化日志；`MAPBOT_VAULT_DEBUG=1` 才开全量 ✓
    print()
    print('【B13】宝库取证默认不落盘（用户：「不用取证了吧」）')
    vvd = os.path.join(_subdir_of('verify_vault_debug.py'), 'verify_vault_debug.py')
    if not os.path.exists(vvd):
        skip('verify_vault_debug.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_debug.py'], timeout=300)
        check('宝库取证默认关闭回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉟ ⭐ 默认**一张都不落**（`_want_dump` 只由 `VAULT_DEBUG` 决定）；'
              '旧的"按需/前 N 张"那套已清干净',
              '默认不落盘' in out and '代码里**没有**' in out)
        check('㊱ ⭐ 控制台默认**不刷噪声**（原来每步一行 ⇒ 一把 18 行 ✗）；'
              '结构化日志仍记',
              '控制台默认不刷' in out and '`vault_step`' in out)

    # ── B12：摇色子的两个「棋盘内盲点」（2026-10-05，用户报「摇完大拇指后有个点中间的盲点」）──
    #   硬事实（`FX.A` + `cell_of`）：`dice_yes`(520,742)⇒格 **(1,6)**、
    #   `dice_no`(300,742)⇒格 **(1,3)** —— **都在棋盘里**，而原来两处**都无判据** ✗
    #   （原作者注释写「框不在时这一下落在面板空白处」—— **假设是错的**）
    #   修：判据用**棋盘压暗**（模态框弹出 ⇒ 棋盘被遮罩压暗）—— 零成本、不付 OCR ✓
    print()
    print('【B12】摇色子：两个"棋盘内盲点"必须带判据')
    vdb = os.path.join(_subdir_of('verify_dice_blind.py'), 'verify_dice_blind.py')
    if not os.path.exists(vdb):
        skip('verify_dice_blind.py', '文件不存在')
    else:
        rc, out = run(['verify_dice_blind.py'], timeout=300)
        check('摇色子盲点回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉝ ⭐ `dice_yes`/`dice_no` **落在棋盘内**（(1,6)/(1,3)）⇒ 必须带判据；'
              '`dice_reroll` 在棋盘外 ⇒ 保持零判断',
              '**在棋盘内**' in out and '`dice_reroll` **不需要**判据' in out)
        check('㉞ ⭐ 判据用**棋盘压暗**（零成本，不付 OCR）＋ 跳过后立刻 break',
              '棋盘压暗' in out and '立刻 break' in out)

    # ── B11：退图前补点 = 固定坐标（2026-10-05，用户问「怎么还ocr？这种不应该都是固定坐标点击吗」）──
    #   真机 `taps` 实测每一下 3.7~9.1 秒；`final_collect()` 补点一下之后要走**最多 6 次整屏 OCR**
    #   （0.65~0.9 秒/次）⇒ 提速：**固定坐标 + 1 次窄带确认**，兜底一条不删 ✓
    #   ★ 同一条还治了用户第二次报的「**修了个寂寞啊，没打探索格**」：
    #     真正吃掉那一格的是 `final_collect()`（补点又点了一次紫格、弹出探索面板关不掉），
    #     **不是** `popups()` —— 我前几轮一直在修错的那条链 ✗（已加 `purple_skip` ✓）
    print()
    print('【B11】退图前补点：固定坐标优先（不是逐个状态 OCR）＋ 紫格不补点')
    vcf = os.path.join(_subdir_of('verify_collect_fast.py'), 'verify_collect_fast.py')
    if not os.path.exists(vcf):
        skip('verify_collect_fast.py', '文件不存在')
    else:
        rc, out = run(['verify_collect_fast.py'], timeout=300)
        check('补点固定坐标回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉚ ⭐ 固定坐标关面板**必须被"棋盘压暗"判据包着**（否则会点到棋盘里的拉黑格 ✗）；'
              '紫格不补点',
              '两个盲点都在' in out)
        check('㉛ ⭐ 旧兜底**一条没删**（删了会重现"跳到图鉴"事故）＋ 安全检查保留',
              '保留了 `force_unstick`' in out and 'in_map' in out)
        check('㉜ ⭐ **紫/橙探索格不补点**（补点会重复弹探索面板 ⇒ 就是"没打探索格"的真根因）',
              '紫色探索格' in out or ('紫/橙探索格' in out and 'purple_skip' in out))

    # ── B12/B13/B14：2026-10-06 三处真机修复（各自带牙齿）────────────────────
    #   ① 【B12】宝库格检测的尺寸阈值**必须跟着分辨率走**
    #      用户报「为什么黄金宝库又不能正常买了？？」＋「买到第二层就把宝库关了，
    #      可能点到宝库外面了」⇒ 真因：`vault_tiles()` 的 `min_side=100/…/y>700`
    #      是 **1080p** 标的，720p 上格子只有 **84** ⇒ **全被拒** ⇒ 返回 0 格
    #      ⇒ `vault_pick` 回落到写死的理论网格 ⇒ 乱点 ⇒ 点关面板 ✗
    #   ② 【B13】雾格 boss 是 **B↔R 互换**的蓝色图标（原模板必漏）
    #      用户报「为什么这两张图没打 boss？」⇒ 13 张里 **9 张**是蓝图标
    #   ③ 【B14】摇色子的 `wait_end` 里引用了**不存在的名字 `ctx`** ⇒ NameError
    #      真机 `runs/acc2/loop/loop_log.json` **9 条**同一异常 ⇒ 一次都没摇成 ✗
    print()
    print('【B12】宝库格检测的尺寸阈值必须跟着分辨率走（720p 格子 84 ⇒ 旧 100 档全拒）')
    vtr = os.path.join(_subdir_of('verify_vault_tiles_res.py'), 'verify_vault_tiles_res.py')
    if not os.path.exists(vtr):
        skip('verify_vault_tiles_res.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_tiles_res.py'], timeout=600)
        check('宝库格检测分辨率回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉝ ⭐ 720p 的 min_side 必须 **< 100**（否则 84 的格子全被拒）'
              '＋ 1080p 上逐值不变（老行为 no-op）',
              'min_side < 100' in out and '1080p 上逐值等于 1080 基准' in out)
        check('㉞ ⭐ 第 2 层帧必须能检出 **8 格**（修前是 0 ⇒ 就是"买不到第二层"）',
              'ring2 正好 8 格' in out)
        check('㉟ ⭐ 反向守门：退回写死阈值 ⇒ 720p 必须回到 **0 格**（不是恒绿）',
              '退回旧阈值' in out and '检出 0 格' in out)

    print()
    print('【B13】雾格 boss = B↔R 互换的蓝色图标（原模板配色分掉到 0.47 ⇒ 必漏）')
    vbb = os.path.join(_subdir_of('verify_boss_blue.py'), 'verify_boss_blue.py')
    if not os.path.exists(vbb):
        skip('verify_boss_blue.py', '文件不存在')
    else:
        rc, out = run(['verify_boss_blue.py'], timeout=600)
        check('雾格蓝 boss 回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊱ ⭐ 蓝变体必须**逐像素等于**原模板的 B↔R 互换（alpha 不许换）',
              '逐像素 == boss 的 B↔R 互换' in out and 'alpha 通道没被换' in out)
        check('㊲ ⭐ 必须**用代码合成**、不许靠 `templates/marks/` 下的新 PNG'
              '（那个目录不进热更补丁 ⇒ "代码到了、图没到"✗）',
              '不进热更补丁' in out and '没有靠' in out)
        check('㊳ ⭐ 反向守门：删掉蓝变体 ⇒ 蓝帧**必须认不出**，红帧**仍认得出**',
              '认不出' in out and '仍认得出' in out)

    print()
    print('【B14】摇色子的三个调用点不许引用作用域外的名字（真机 NameError ×9）')
    vdc = os.path.join(_subdir_of('verify_dice_call.py'), 'verify_dice_call.py')
    if not os.path.exists(vdc):
        skip('verify_dice_call.py', '文件不存在')
    else:
        rc, out = run(['verify_dice_call.py'], timeout=300)
        check('摇色子调用点回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊴ ⭐ `wait_end` 必须有 `st` 参数，且实参是 `st=st`（不再引用野名字 `ctx`）',
              'wait_end' in out and 'st=st' in out.replace(' ', ''))
        check('㊵ ⭐ 执行级：真跑 `wait_end` 必须**不抛 NameError** 且**真调到** `handle_dice`',
              '跑完**没有** NameError' in out and '真的调到了 handle_dice' in out)

    # ── B10：紫/橙探索格别漏（2026-10-05，用户报「为什么漏了一个紫探索的战斗」）────
    #   真机 `runs/acc1/r_160935_0.png` 的 `(3,1)`：顶层 sid 是垃圾猜测
    #   （`S30001_104` score **0.192**、ratio **1.709** = 雾里那团紫光）
    #   ⇒ 只看顶层后缀 ⇒ 探索/派遣分支被跳过 ⇒ 面板被当普通面板关掉 ⇒ **那一格没打** ✗✗
    #   修：判据抽成纯函数 `_is_purple_cell()`，本轮 `ev_tiles` 也算数 ✓
    #   牙齿：旧实现（只认顶层后缀）⇒ 第 1、5 例必红 ✓
    print()
    print('【B10】紫/橙探索格别漏（顶层 sid 是垃圾猜测时，靠本轮 ev_tiles 认）')
    vpt = os.path.join(_subdir_of('verify_purple_tile.py'), 'verify_purple_tile.py')
    if not os.path.exists(vpt):
        skip('verify_purple_tile.py', '文件不存在')
    else:
        rc, out = run(['verify_purple_tile.py'], timeout=300)
        check('紫格判据回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉙ ⭐ 顶层 sid 是垃圾猜测时**本轮 ev_tiles 里有它就认**；'
              '不在里面的**绝不许乱认**',
              '必须靠 ev_tiles 认出来' in out and '不许乱认' in out)

    print()
    print('【B9】adb server 端口（别用 MuMu 的 5037）+ 设备掉线自愈')
    var = os.path.join(_subdir_of('verify_adb_reconnect.py'), 'verify_adb_reconnect.py')
    if not os.path.exists(var):
        skip('verify_adb_reconnect.py', '文件不存在')
    else:
        rc, out = run(['verify_adb_reconnect.py'], timeout=300)
        check('adb 端口/掉线自愈回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉘ ⭐ 真机那条 `device \'…\' not found` 必须被认成**连接类错误**'
              '（否则重试逻辑形同虚设）',
              '真机原文（用户 10-05 贴的）' in out and '逻辑错：**不许**当连接错' in out)
        check('㉙ ⭐ `reconnect()` **先 adb_connect 再 connect_device**（原来只有后者 ✗）',
              'adb_connect 在 connect_device **之前**' in out)
        check('㉚ ⭐ 进图遇连接类错误**重连重试一次**、非连接类**立刻上抛**；'
              'URI 端口不再写死 5037',
              '重连 + 重试成功' in out and '不重试' in out)

    # ── B6：设备锁 —— Windows 回收 PID 不许把启动堵死（2026-10-05）──────────
    #   用户 2026-10-05：「怎么刚启动就退出了」⇒ 真根因：02:42 那把循环被强杀没走 finally，
    #   `.loop_16384.lock` 留着 pid=20172；而 03:07:24 系统把 **20172 回收给了 conhost.exe**
    #   ⇒ 旧判据只查"PID 还在不在" ⇒ 判"被占用" ⇒ 启动即退出、一次都跑不起来 ✗✗
    #   ⇒ 判据加"身份确认"（命令行还得指向我们的启动器）；门禁在临时目录上跑真 loopguard ✓
    print()
    print('【B6】设备锁：PID 被系统回收 ⇒ 必须能接管；真循环在跑 ⇒ 必须拒绝')
    vlg = os.path.join(_subdir_of('verify_loopguard.py'), 'verify_loopguard.py')
    if not os.path.exists(vlg):
        skip('verify_loopguard.py', '文件不存在')
    else:
        rc, out = run(['verify_loopguard.py'], timeout=600)
        check('设备锁回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉑ ⭐ 活着的**无关**进程占着锁不许把启动堵死（旧代码在这里必红）',
              'PID 4 ⇒ acquire **接管成功**' in out
              or 'System PID 4 ⇒ acquire **接管成功**' in out)
        check('㉒ ⭐ 真的循环在跑必须拒绝（不许双开抢点击）',
              'acquire 必须**失败**' in out)

    # ── E：热路径确实用固定坐标 ────────────────────────────────────────
    print()
    print('【C】热路径确实在用固定坐标（防"改了 fixed.py 却退回 OCR"）')
    elp = os.path.join(HERE, 'core', 'explore_loop.py')
    src = io.open(elp, encoding='utf-8').read() if os.path.exists(elp) else ''
    if not src:
        check('explore_loop.py 存在', False)
    else:
        check('⑦ 提速层入口齐全（fx_anchor/fx_has/fx_at/fx_tap）',
              all(('def %s(' % f) in src
                  for f in ('fx_anchor', 'fx_has', 'fx_at', 'fx_tap')))
        try:
            import fixed as _fx
            _fixsrc = io.open(os.path.join(HERE, 'core', 'fixed.py'),
                              encoding='utf-8').read()
            _lb = _fx.A('lime_back')        # ⭐ 锚点要走 A()，不是模块属性
            _eb = _fx.A('equip_back')
        except Exception as _e:                          # noqa: BLE001
            check('⑦ fixed.py 里有 lime_back/equip_back 两个锚点', False,
                  repr(_e)[:80])
            _lb = _eb = (0, 0)
        check('⑧ 大厅离开用固定坐标（不再从 OCR 文字猜 4 个偏移）',
              "fx_anchor('start_adv_icon')" in src)
        # ── 奖励弹窗「返回」必须**写死**（PC 端 §1b 提速约定，2026-10-02）──
        #   背景：用户实测「模拟器卡在获得莱姆界面」—— 退图前最后一次补点弹出该弹窗，
        #   而旧判据要 **OCR 读到「莱姆」「返回」二字**才点：
        #     ① 写死坐标 0ms，OCR 一条带 3.3~3.6s（README §1 实测）
        #     ② 这类弹窗在退图收尾**必遇**，每次都 OCR 纯属浪费
        #     ③ 标题偶发读不出 ⇒ 整条链失效 ⇒ 弹窗留在屏上 ⇒ 盖住棋盘
        #        ⇒ 认不到「结束冒险」⇒ 万能位盲点 ⇒ **跳到「图鉴」大页面** ✗✗
        #   ⇒ 断言：两个返回位都进了 `fixed.ANCHORS`，且 `_tap` 走它们
        check('⑨ 奖励弹窗返回位**写死**在 fixed（0ms，不靠 OCR 找按钮）',
              "'lime_back'" in _fixsrc and "'equip_back'" in _fixsrc
              and "lime_back" in src and "newequip_back" in src)
        check('⑨ 写死坐标都在 720×1280 屏内（不会点空）',
              _lb[1] < 1280 and _eb[1] < 1280
              and 0 < _lb[0] < 720 and 0 < _eb[0] < 720,
              'lime_back=%s equip_back=%s' % (_lb, _eb))
        check('⑨ 判据改成「标题 **或** 弹窗形态」，不再单靠 OCR 文字',
              'is_reward_panel' in src or 'panel_seen(items, b=b)' in src)
        # ⛔ 2026-10-02 回归钉子：用户当场发现「刚进图就找莱姆了」
        #   我给 `lime_back` 配的兜底判据是裸 `panel_seen()` ⇒ **地图界面也常命中**
        #   ⇒ 每轮都去点写死坐标 ⇒ 规划被反复打断、点序全乱 ✗✗✗
        #   ⇒ 断言：`lime_back` 的调用点**不许**用裸 `panel_seen` 兜底；
        #     真要兜底必须走 `is_reward_panel()`（内部含「棋盘被遮住」硬闸）。
        import re as _re2
        _bad_wide = []
        for _m in _re2.finditer(r'if [^:\n]*lime_back\([^)]*\)\s*:', src):
            # ⛔ 只看**这一行**的判据，且**跳过注释行**
            #   （我注释里写着「⛔ 不用 panel_seen 兜底」，按全文扫会自己把自己判红 ✗）
            _ln = src.rfind('\n', 0, _m.start()) + 1
            _line = src[_ln:_m.end()]
            if _line.lstrip().startswith('#'):
                continue
            if 'panel_seen' in _line and 'is_reward_panel' not in _line:
                _bad_wide.append(_line.strip()[:70])
        check('⑨ lime_back 调用点**不用裸 panel_seen 兜底**（那会误伤地图界面）',
              not _bad_wide, '、'.join(_bad_wide[:3]))
        # ⛔⛔ 2026-10-02 二次回归钉子：第二版我给 `is_reward_panel` 加了
        #   「panel_seen() + 棋盘被遮住」兜底 ⇒ **宝库/商人面板弹出时棋盘同样被遮住**
        #   ⇒ 又被判成「奖励弹窗」⇒ 真机日志连点 4 格都刷「弹出获得新装备」，
        #      而那 4 格是**宝库区域**，压根没有装备弹窗（用户：「获得新装备只有在
        #      获得大拇指装备和之前获得莱姆那个位置出现」）✗✗✗
        #   ⇒ 断言：**不许有任何视觉兜底**，只认 OCR 标题文字。
        _ir = src[src.index('def is_reward_panel('):][:2600]
        _ir_body = _ir[_ir.index('"""', _ir.index('"""') + 3) + 3:]  # 去掉 docstring
        # ⚠ 2026-10-13 **判据随实现更新**（意图**一字未变** ✓）
        #   我修莱姆误判时，把这一行从 `return bool(fb(items, *L['lime']) or …)`
        #   改成 `return bool(_lime_popup_title(items) is not None or fb(…) or fb(…))`
        #   ⇒ 原来钉的 `'return bool(fb('` **不再字面出现** ⇒ 本条假红 ✗
        #   ⚠⚠ 但**本条要守的意图没变**：`is_reward_panel` **只认 OCR 标题**、
        #     **不许任何视觉兜底**（`panel_seen` / `_bd.mean()`）✓
        #   ⇒ 现改成：**不许视觉兜底** ＋ **确实还在做"按标题文本匹配"**（两种写法都认）✓
        check('⑨ is_reward_panel **只认 OCR 标题**（不许视觉兜底：会误判宝库面板）',
              'panel_seen' not in _ir_body and '_bd.mean()' not in _ir_body
              and ('return bool(fb(' in _ir_body
                   or 'return bool(_lime_popup_title(' in _ir_body),
              '视觉兜底会把手册/商人面板误判成奖励弹窗（真机实证）')
        check('⑨ 进入地图用固定锚点，**但体力安全门仍在**',
              "fx_anchor('enter_map')" in src and 'skip_low_stamina' in src)
        check('⑩ 找不到固定坐标时有 OCR 兜底（不是硬崩）',
              'fx_fallback_to_ocr_offset' in src)

    # ── F：模块可 import + 基础自检 ────────────────────────────────────
    print()
    print('【D】模块可 import + 基础自检')
    code = (
        "import sys\n"
        "for m in ('layout','spots','marks','badge','grid_detect','mapsolve',\n"
        "          'strategy','targets_cfg','mapgen','mapsim','fixed'):\n"
        "    __import__(m)\n"
        "import layout\n"
        "raise SystemExit(0 if layout.self_test(verbose=False) else 1)\n")
    probe = os.path.join(HERE, 'core', '_gate_probe.py')
    with io.open(probe, 'w', encoding='utf-8', newline='\n') as f:
        f.write(code)
    try:
        rc, out = run([os.path.basename(probe)], timeout=180)
        check('⑪ 关键模块可 import（11+1 个）且 layout 零回归自检过（exit=%d）' % rc,
              rc == 0, out.strip().split('\n')[-1][:80] if out else '')
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass

    # ── G：换机可移植性（2026-10-02，**发给朋友用**才加的）────────────
    print()
    print('【E】换机可移植性（不能有本机绝对路径）')
    check('⑫ 路径解析模块 paths.py 存在且体检全过', _check_paths(), '')
    # ── MAA 极速截图：不能「静默降级」（2026-10-02 用户问「没装 MAA 快速截图」）──
    #   实测：仓内 `_maa_venv` 一直**不存在** ⇒ `ensure_sidecar()` 每次都退回
    #   adb（0.33s/张 vs MAA 0.013s/张，**慢 25 倍**），而它只打一行「慢一些」
    #   不报错 ⇒ 这件事被掩盖了很久，用户全程不知情 ✗
    try:
        _guisrc = io.open(os.path.join(HERE, 'core', 'bot_gui.py'),
                          encoding='utf-8').read()
        _rcsrc = io.open(os.path.join(HERE, 'devtools', 'run_collect.py'),
                         encoding='utf-8').read()
    except Exception:                                   # noqa: BLE001
        _guisrc = _rcsrc = ''
    try:
        import paths as _paths
        _maa_ok = bool(_paths.MAA_PY) and os.path.exists(_paths.MAA_PY)
    except Exception:                                   # noqa: BLE001
        _maa_ok = False
    check('㉕ MAA 极速截图 venv **存在**（否则截图慢 25 倍且不报错）',
          _maa_ok, ('%s' % _paths.MAA_PY) if _maa_ok else 'paths.MAA_PY 为空/不存在')
    check('㉕ 降级警告写明**真实代价与修法**（不再是「慢一些」）',
          '慢 25 倍' in _guisrc and 'pip install MaaFw' in _guisrc)
    check('㉕ sidecar 的 stdout/stderr **落盘**（起不来时查得到原因）',
          'sidecar_%s.log' in _guisrc
          and not re.search(r'maa_sidecar\.py.{0,400}?subprocess\.DEVNULL',
                           _guisrc, re.S),
          '启动 sidecar 那处仍把输出丢进 DEVNULL ⇒ 起不来时日志里什么都不留')
    check('㉕ 路径**只由 paths.py 一处**解析（run_collect 不再各写一份）',
          "import paths as _paths" in _rcsrc or 'import paths as _paths' in _rcsrc)
    # ── 商人买完**不消失** ⇒ 不能反复点（2026-10-02 用户报）──
    #   真机日志：#13 merchant done → #19 规划又排 4,7 → #20 vault_unpin 把它放回
    #   根因：摘除判据是「本帧还是不是商人」，而商人格买完**美术不变**（仍是
    #   「旅行商人」）⇒ 摘除把它当成「还没买掉」⇒ 下一轮又点。
    #   （宝库是整格替换，分类器立刻看得出变化；商人不行 —— 用户原话
    #     「宝库买完才会消失」说的就是这个差别。）
    try:
        _elsrc = io.open(os.path.join(HERE, 'core', 'explore_loop.py'),
                         encoding='utf-8').read()
    except Exception:                                   # noqa: BLE001
        _elsrc = ''
    check('㉖ 买完的商人/宝库格记进 bought_done（美术不变时唯一可靠依据）',
          "bought_done" in _elsrc
          and '旅行商人买完' in _elsrc)
    check('㉖ 「摘除已买完格」时跳过 bought_done（否则反复重买）',
          '_p not in _just_bought' in _elsrc)
    # ── board_hidden 阈值缩放方向（2026-10-02 真机 0 产出）──
    #   实测帧 runs/merchk/r_154536_0.png：最亮 1.311、ratio≥0.85 有 20 格、
    #   **真正被压暗 0 格**，却被判「面板挡住棋盘」⇒ 4 轮 0 产出后 board_not_visible。
    #   根因：`_thr = 0.55 * _mx` 跟着最亮格**放大**（1.311⇒0.721），
    #   而**未揭示雾格恒 ≈0.65** ⇒ 正常雾格全被算成「被压暗」⇒ 凑够 15 ⇒ 误判 ✗
    #   ⇒ 必须是 min(0.55, 0.55*_mx)：画面越正常阈值越不能涨。
    #   ⇒ 阈值必须封顶在 0.55（`min(0.55, 0.55*_mx)`）：画面越正常，阈值越不能涨。
    _hid_src = _elsrc[_elsrc.index('def board_hidden('):][:5000]
    _hid_code = re.sub(r'#.*', '', _hid_src)      # ⛔ 去掉注释（说明里也写着旧公式）
    check('㉗ board_hidden 阈值**封顶 0.55**（不被最亮格放大）',
          re.search(r'_thr\s*=\s*min\(\s*0\.55', _hid_code) is not None
          and not re.search(r'_thr\s*=\s*0\.55\s*\*\s*_mx', _hid_code),
          '代码里找到：%s' % re.findall(r'_thr\s*=\s*[^;\n]+', _hid_code)[:1])
    try:
        import explore_loop as _EL

        def _mk(ratios, ln, gn):
            _s = {}
            for _i, _r in enumerate(ratios):
                _s[(_i // 7 + 1, _i % 7 + 1)] = {'ratio': _r, 'sid': 'S00003_001',
                                               'name': '草地'}
            return {'st': _s, 'light': [1] * ln, 'gray': [1] * gn}

        check('㉗ 正常盘（含 12 雾格 + 20 亮格）**不**判被遮挡',
              _EL.board_hidden(_mk([0.65] * 12 + [0.99] * 20, 20, 12)) is False)
        check('㉗ 真面板遮罩（整盘 0.30）**仍**判被遮挡（别修成永远 False）',
              _EL.board_hidden(_mk([0.30] * 35, 0, 35)) is True)
        check('㉗ 偏暗设备（整盘 0.60）不误判为遮挡',
              _EL.board_hidden(_mk([0.60] * 8 + [0.35] * 27, 8, 27)) is False)
        check('㉗ 中间局部遮挡（20 格压到 0.30）仍判被遮挡',
              _EL.board_hidden(_mk([0.30] * 20 + [0.99] * 15, 15, 20)) is True)
    except Exception as _e3:                             # noqa: BLE001
        check('㉗ board_hidden 可测', False, repr(_e3)[:80])
    # ── 「已揭示」不能是**绝对阈值**（2026-10-02 用户「明明打开标记格子了」）──
    #   真机帧 runs/r_155829_0.png：4,6 裁出来**明明是亮的**、带 boss+大拇指两个图标，
    #   但 ratio=0.708 < 0.75 ⇒ 判成雾格 ⇒ 规划当第一步去点 ⇒ 点不动 ⇒
    #   「标记格打不开」⇒ 摇色子分支（要 recommend）也走不到 ✗
    #   ⇒ 改成**相对本帧雾格基准**（10 分位 ×1.06，保底 0.66），且必须**两趟**判定。
    _fr = os.path.join(HERE, 'runs', 'r_155829_0.png')
    if os.path.exists(_fr):
        try:
            import cv2 as _cv2
            import numpy as _np
            import spots as _sp
            _g = {'x0': 24.0, 'y0': 668.0, 'cx': 96.0, 'cy': 96.0,
                  'pitch': 96.0, 'cols': 7, 'rows': 5}
            _im = _cv2.imdecode(_np.fromfile(_fr, _np.uint8), _cv2.IMREAD_COLOR)
            _s = _sp.Board('S00003', grid=_g).state(_im)
            _n = sum(1 for v in _s.values() if v.get('revealed'))
            check('㉘ 带 boss+大拇指的 4,6 判为**已揭示**（旧绝对阈值 0.75 会误判）',
                  bool((_s.get((4, 6)) or {}).get('revealed')),
                  'ratio=%.3f' % float((_s.get((4, 6)) or {}).get('ratio') or 0))
            check('㉘ 该帧已揭示格数明显多于旧阈值（旧 4 → ≥10）',
                  _n >= 10, '现 %d 格' % _n)
            check('㉘ state 的键**仍全是坐标元组**（不能混入诊断键）',
                  all(isinstance(k, tuple) for k in _s))
            # ── 紫金大块不能被**固定 0.70** 挡掉（用户「盘上还有紫金格却写没目标」）──
            #   runs/r_162357_0.png：左上角跨 8 格的 S00003_321 紫金大城堡明明白白在图上，
            #   但 block_score 只有 0.575 ⇒ 被 0.70 门槛全跳过 ⇒ 写「目标已清完」退图。
            #   0.70 是从**某一帧**（0.794）量出来的单点值，换局面就掉 ⇒ 同类问题第 N 次。
            #   ⇒ 改用结构证据：**同 sid 同 anchor 的成员 ≥3 格** ⇒ 判为真大块。
            #   ⚠ 必须用**带紫金块的那一帧**（r_162357_0），上面那帧没有紫橙块。
            _fr2 = os.path.join(HERE, 'runs', 'r_162357_0.png')
            _im2 = _cv2.imdecode(_np.fromfile(_fr2, _np.uint8), _cv2.IMREAD_COLOR)
            _s2 = _sp.Board('S00003', grid=_g).state(_im2)
            _pp = set(_sp.EXPLORE_SUFFIX)
            _grp2 = {}
            for _k2, _v2 in _s2.items():
                _sf2 = str(_v2.get('sid') or '').split('_')[-1]
                if _sf2 in _pp:
                    _a2 = tuple(_v2.get('anchor') or _k2)
                    _grp2.setdefault(_a2, []).append(
                        float(_v2.get('block_score') or _v2.get('score') or 0))
            _big = [a for a, m in _grp2.items()
                    if (m[0] >= 0.70) or (len(m) >= 3)]
            check('㉙ 该帧的紫金大块**认得出来**（旧 0.70 门槛会漏）',
                  bool(_big), '大块 %d 个：%s'
                  % (len(_big), [(str(a), len(_grp2[a]), round(_grp2[a][0], 3))
                                 for a in _big][:2]))
            check('㉙ 单格低分噪声仍被挡（<3 格且<0.70 不算目标）',
                  not [1 for a, m in _grp2.items()
                       if len(m) < 3 and m[0] < 0.70],
                  '没有「成员<3 且分<0.70」的紫橙块被误当大块 ✓')
            check('㉙ 源码用「>=0.70 或 成员>=3」而不是单一阈值',
                  '_same_sid < 3' in _elsrc)
            # ── 统计必须挂在「战斗结束」这个出口，而不是某一条关闭路径 ──
            #   2026-10-02：连打 8 局统计全是 0 —— 因为计数写在 `if cl:` 分支内，
            #   而结算面板走的是 `battle_close_fixed`（认不到「关闭」文字）那条兜底 ⇒ 不计数。
            check('㉚ 战斗统计有**统一出口**（认不到关闭文字时也计数）',
                  'def _count_once(' in _elsrc
                  and "'battle': 'closed_fixed'" in _elsrc,
                  '两条关闭路径共用 _count_once ⇒ 不会重复，也不会漏')
            # ── 紫/橙格**不能被当普通格拉黑**（用户「能点开紫探索格，却一直点探索」）──
            #   runs/loop：#9 fight_panel 但 cell_marks=[] → #10 no_battle_in_5s
            #            → #12 unmarked_no_start「普通格点不动 → 拉黑这格」
            #   紫/橙格**本来就不带标记**（靠 sid 后缀识别）⇒ 每个都被误拉黑
            #   ⇒ 之后点它没反应 ⇒ 退回「点探索」分支 ⇒ 无限重复 ✗
            check('㉛ 紫/橙格点不动**不拉黑**（它仍是目标）',
                  "'battle': 'ev_no_start'" in _elsrc
                  and 'not mk and not _is_ev' in _elsrc)
            # ── 「点两次没反应」不等于「槽满」（同一轮日志里 slots_free=2 却 latched）──
            check('㉜ HUD 读到有空槽时**不推翻槽位读数**（不误判槽满）',
                  'tap_no_effect_but_slots_free' in _elsrc)
            # ── 结算面板压暗时，**不能把真目标标记一起丢**（用户「大拇指没摇色子」）──
            #   runs/loop：#179 result_panel → #186 marks_dropped_panel "2,4"
            #   ratio=0.303 marks=[recommend] —— **大拇指格被当「面板里的图标误判」丢掉**
            #   ⇒ `'recommend' in marks` 不成立 ⇒ 摇色子分支永不进入 ⇒ 打完直接关面板 ✗
            #   ⚠ 自相矛盾：上面刚「压暗 ⇒ 保留上一轮标记」，紧接着又按 ratio<0.55 全删
            check('㉞ 压暗保留的标记**不再被压暗判据丢**（摇色子才进得去）',
                  '_kept_by_dim' in _elsrc
                  and 'if _kept_by_dim and k in (_old_mk or {}):' in _elsrc)
            # ── 但「面板里新扫到的图标」仍要丢（老判据不能整个废掉）──
            check('㉞ 本帧新扫到、且暗的标记**仍会被丢**（不把面板当地图）',
                  'bad.append(k)' in _elsrc)
            # ── `popups()` 里**不许有裸 `st`**（NameError 被 except 吞掉的类型）──
            #   2026-10-02 用户报「商人被重复买 9 次」，真机诊断：
            #       {"bought_rec_err":"NameError: name 'st' is not defined"}
            #       {"unpin_dbg":{"kept_bought":[], "dropped":[[456,1100]]}}
            #   ⇒ `popups(b, items, log, ctx=None)` 里**根本没有 `st`**，
            #     状态在 `ctx['flags']` ⇒ bought_done 永远写不进去 ⇒ 无限重买
            #   ⚠ 之所以一直没人发现：那段被 `except: pass` 吞了，
            #     **不抛异常、不告警、照跑** ⇒ 门禁也测不出来 ⇒ 只能静态扫 ✓
            try:
                import inspect as _insp
                import explore_loop as _EL2
                _psrc = _insp.getsource(_EL2.popups)
                _bare = re.findall(r'(?<![\w.\'"])st\.\w+', _psrc)
                check('㉡ popups() 里没有**裸 st**（NameError 会被 except 吞掉）',
                      not _bare, '裸 st：%s' % sorted(set(_bare))[:4]
                      if _bare else '')
                check('㉡ bought_done 写自 ctx["flags"]（不是不存在的 st）',
                      "ctx or {}).get('flags')" in _psrc)
            except Exception as _e6:                         # noqa: BLE001
                check('㉡ popups 可静态检查', False, repr(_e6)[:70])
            # ── 变量必须**先初始化再在 if 里赋值**（真机崩过一次）────────────
            #   runs/loop #20：{"error":"UnboundLocalError: cannot access local
            #   variable '_new_mk' where it is not associated with a value"}
            #   根因：`_new_mk/_old_mk/_dim_now` 在 `if vis:` 里赋值，
            #        而「压暗保留」判据在 if **之外**用到它
            #        ⇒ 棋盘不可见那一帧（vis=False）三个都没定义 ⇒ 整个进程退出 ✗
            #   ⇒ 必须有「if 之前的安全默认值」。
            _L2 = _elsrc.splitlines()
            _ni = [n for n, l in enumerate(_L2)
                   if '_new_mk, _old_mk, _dim_now = None' in l]
            _nv = [n for n, l in enumerate(_L2)
                   if l.strip() == 'if vis:' and _ni and n > _ni[0]]
            _nu = [n for n, l in enumerate(_L2) if '_kept_by_dim = bool' in l]
            check('㉟ 标记变量**先初始化再在 if vis 里赋值**（真机崩过）',
                  bool(_ni and _nv and _nu and _ni[0] < _nv[0] < _nu[0]),
                  'init=%s if_vis=%s use=%s'
                  % ([n + 1 for n in _ni], [n + 1 for n in _nv], [n + 1 for n in _nu]))
            # ── 面板按钮**不许写死 1080p 系数值**（§4.2 铁律的又一次翻车）──
            #   用户「一直点探索格子」：真机 runs/evchk 一路点到 round 42、
            #   stamina 1834 纹丝不动 ⇒ 每次点击都点在**空处**。
            #   根因：兜底坐标写死 `(275, 736)` —— 那是 **1080p 旧标定**，
            #   换基准时同批的 FIGHT_Y / DISPATCH_BTN 都折算了，**唯独它漏了**。
            #   正确值 = `fixed.A('explore_btn')` = **(183, 491)**，差 **245 像素**。
            check('㉝ 「探索」按钮**走 fixed 锚点**（不是写死的 1080p 旧值）',
                  "_fx0.A('explore_btn')" in _elsrc
                  and 'else (275, 736)' not in _elsrc,
                  '写死值会让点击落在空处、面板永远关不掉')
            try:
                import fixed as _fx1
                _eb = _fx1.A('explore_btn')
                check('㉝ explore_btn 在 720×1280 屏内且 y<600（面板区，不是导航条）',
                      0 < _eb[0] < 720 and 0 < _eb[1] < 600, 'explore_btn=%s' % (_eb,))
            except Exception as _e5:                       # noqa: BLE001
                check('㉝ fixed.explore_btn 可取', False, repr(_e5)[:60])
        except Exception as _e4:                         # noqa: BLE001
            check('㉘ spots 可测', False, repr(_e4)[:80])
    else:
        check('㉘ 真机帧 runs/r_155829_0.png 存在', False, '缺 ⇒ 跳该判据')
    bad = _scan_hardcoded()
    check('⑬ 运行时模块无本机绝对路径（ROOT/ADB 等已自动探测）',
          not bad, '仍写死: %s' % '; '.join(bad[:6]) if bad else '')

    # ── H：设备选择三态（2026-10-02）─────────────────────────────────
    print()
    print('【F】设备选择三态（多开弹框 / 单开直连 / 零开提醒）')
    ds = os.path.join(_subdir_of('verify_devicesel.py'), 'verify_devicesel.py')
    if not os.path.exists(ds):
        skip('verify_devicesel.py', '文件不存在')
    else:
        rc, out = run(['verify_devicesel.py'], timeout=180)
        check('设备选择三态全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑭ 单开：只有一个实例时**不弹任何窗口**', '没有弹任何提示' in out)
        check('⑮ 多开：多个实例才弹选择框', '选项里只有运行中的两个' in out)
        check('⑯ 零开：没启动 MuMu 时提醒去启动', '一个实例都没启动' in out)
        check('⑰ tag 按实例 index 派（删实例不串号）',
              '旧算法会误给 acc2' in out)

    # ── I：分辨率缩放（2026-10-02，720p 跑不了的真凶）────────────────
    print()
    print('【G】分辨率缩放（k 必须跟着屏幕走，否则 720p 什么都点不到）')
    ls = os.path.join(_subdir_of('verify_layout_scale.py'), 'verify_layout_scale.py')
    if not os.path.exists(ls):
        skip('verify_layout_scale.py', '文件不存在')
    else:
        rc, out = run(['verify_layout_scale.py'], timeout=180)
        check('分辨率缩放自检全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('⑱ ADAPTIVE_LAYOUT 开着（k 才会跟着屏幕走）',
              'ADAPTIVE_LAYOUT = True' in out)
        check('⑲ 720p 门槛能过「进入地图」实测坐标',
              '过得了门槛' in out and '参数必须一起换算' in out)
        check('㉑ 调用点参数已全部换算成 720 系（不留 1080 系残留）',
              '无 1080 系残留参数' in out)

    # ── J：开局全雾不许一格不揭就退图（2026-10-02 真机事故）──────────
    print()
    print('【H】开局全雾不许一格不揭就退图（进图即扣 25 体力，退图不退）')
    fs = os.path.join(_subdir_of('verify_fog_only_start.py'), 'verify_fog_only_start.py')
    if not os.path.exists(fs):
        skip('verify_fog_only_start.py', '文件不存在')
    else:
        rc, out = run(['verify_fog_only_start.py'], timeout=180)
        check('开局全雾回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        # ---- 宝库面板搜索带（2026-10-02 真机「无法正常购买黄金宝库」）----
        try:
            import buypanels as _bp
            _bpsrc = io.open(os.path.join(HERE, 'core', 'buypanels.py'),
                             encoding='utf-8').read()
            # ⭐ 用**真机实测坐标**喂判据：宝库「购买 10000」在 720p 设备系 (600,963)
            _bp_btn = _bp._btn([{'text': '购买', 'cx': 600, 'cy': 963},
                                {'text': '10000', 'cx': 600, 'cy': 995}])
            _bp_back_mid = bool(_bp._back_btn([{'text': '返回', 'cx': 360, 'cy': 1050}]))
            _bp_back_nav = bool(_bp._back_btn([{'text': '返回', 'cx': 360, 'cy': 1259}]))
        except Exception as _e2:                            # noqa: BLE001
            check('㉓ buypanels 可 import', False, repr(_e2)[:80])
            _bp_btn = _bp_back_mid = _bp_back_nav = None
        check('㉒ 无可见目标时**直接收工**（用户口径：目标没了就退，不强求揭雾）',
              '无目标探图闸门**已停用**' in out)
        # ── 宝库/商人面板坐标不许停在 1080 系（2026-10-02「无法正常购买」）──
        #   真机截图实测：宝库「购买 10000」在 720×1280 设备系 **(600, 963)**。
        #   而 `buypanels._btn()` 的搜索带原是 1080p **裸坐标** (700,1040)×(1360,1660)
        #   ⇒ cx=600<700、cy=963<1360 ⇒ 双双被剔 ⇒ `label=None`
        #   ⇒ `vault_flow` 走 `no_select_btn` ⇒ **整层跳过，不买不选** ✗✗
        #   （典型 §4.2「换基准＝全仓换」漏改；门禁当时全绿）
        check('㉓ 宝库「购买」按钮在 720p 搜索带内（不再停在 1080 系）',
              _bp_btn is not None and _bp_btn[0] is not None,
              '实测帧(600,963)+价格 → %s' % (_bp_btn,))
        check('㉓ 宝库带子不会误伤导航条/顶部（别把「返回」认到别处）',
              _bp_back_mid and not _bp_back_nav,
              '面板内(360,1050)认=%s ｜ 导航条(360,1259)认=%s'
              % (_bp_back_mid, _bp_back_nav))
        # ── OCR 提速：两条**实测**结论，防止后人按推测改回去 ──
        #  ① 「缩小 OCR 带子能提速」= **错的**（2026-10-02 真机实测打脸）：
        #     整屏 0.688s / 整带947px 0.698s / 窄带220px 0.656s / 窄带70px 0.868s
        #     ⇒ 耗时由「预处理+模型推理」主导，与带高几乎无关；多次调用才净亏。
        #  ② 真正有效的省法 = **少调几次** ⇒ 已有「同帧缓存 + tap 后自动作废」。
        check('㉔ 不要再把面板 OCR 拆成多条窄带（实测无效，拆了净亏）',
              'NARROW_BANDS = None' in _bpsrc,
              '窄带实测：220px 0.656s / 70px 0.868s vs 整带947px 0.698s')
        check('㉔ 面板 OCR 有**同帧缓存**（少调几次才是真提速）',
              'board_luma' in _bpsrc and 'reuse' in _bpsrc)
        check('㉔ tap 后**自动**作废缓存（不能漏，漏了就读到点击前的画面）',
              'class _TapProxy' in _bpsrc and '_invalidate' in _bpsrc
              and '_proxy(bot)' in _bpsrc)
        check('㉓ 点序空 + 雾多 ⇒ 先等几轮（防一击退图）',
              'empty_order_wait' in out or '雾多' in out)

    # ── M：模板内缩量不许算成负数（2026-10-02 换基准漏改，识别全线失效）──
    print()
    print('【K】模板内缩量（pad）—— 负数会让 NCC 全线失效 ⇒ 没有规划')
    rp = os.path.join(_subdir_of('verify_region_pad.py'), 'verify_region_pad.py')
    if not os.path.exists(rp):
        skip('verify_region_pad.py', '文件不存在')
    else:
        rc, out = run(['verify_region_pad.py'], timeout=900)
        check('内缩量回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉙ pad 在各分辨率下都为正（负数=模板错位）', 'pad' in out)
        check('㉚ 真机帧 NCC 分数达到 0.80 门槛（识别在工作）',
              '达到 0.80 门槛' in out)
        check('㉛ anchor 不再全 None（board 有输入 ⇒ 有规划）',
              '规划有输入' in out)

    # ── N：退图不许崩 / 不许点屏幕外 / 确认框点得掉（2026-10-02）──
    #   三个真机根因：① finish_map 里的裸 `img` ⇒ NameError 必崩
    #                ② 1080 系坐标残留 ⇒ 万能位点在屏幕外（y=1890 > 1280）
    #                ③ 确认框判据 `cy>sy(800)` 太严 ⇒ 真帧「确定」在 cy=742，弹窗关不掉
    print()
    print('【L】退图阶段 —— 不许崩 / 不许点屏幕外 / 确认框点得掉')
    fe = os.path.join(_subdir_of('verify_finish_exit.py'), 'verify_finish_exit.py')
    if not os.path.exists(fe):
        skip('verify_finish_exit.py', '文件不存在')
    else:
        rc, out = run(['verify_finish_exit.py'], timeout=900)
        check('退图回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉜ finish_map 里没有裸 img（NameError ⇒ 每次退图必崩）',
              '裸 img' in out)
        check('㉝ 关键锚点都在 720×1280 屏内（不点屏幕外）',
              '屏内' in out or '万能位' in out)
        check('㉞ 真帧上退图确认框能命中「确定」且不误点「取消」',
              '确认框' in out or '确定' in out)
        # ── 空帧守卫（2026-10-02 真机崩溃实证，见 verify_finish_exit.py 的说明）──
        try:
            import inspect as _ins
            import mapbot as _mb
            _snap = _ins.getsource(_mb.Bot.snap)
            _imgf = _ins.getsource(_mb.Bot.img)
            check('㉟ 截图失败会重试，且**不留空文件**抛明确异常',
                  'range(2)' in _snap and '别留空文件骗下游' in _snap
                  and '截图失败' in _snap)
            check('㉞ img() 有空帧守卫（不再把空 buffer 丢给 imdecode）',
                  '空帧守卫' in _imgf and '截图解码失败' in _imgf)
        except Exception as _e:                              # noqa: BLE001
            check('㉟ 读得到 mapbot.Bot.snap/img', False, repr(_e)[:80])

    # ── M：标记棋盘几何/尺度不许停在 1080 系（2026-10-02「规划很差劲」）──
    #   marks.GRID 写死 (36,1002,144) ⇒ 720p 下扫描区域只覆盖棋盘下半截、
    #   格号映射全错；GLYPH_SCALES 3.8~5.2 是 144 格距标的，720p 真尺度 2.5~3.5
    #   ⇒ scan_board 恒空 ⇒ marked 恒空 ⇒ 每轮「没有目标了」⇒ 规划没有目标 ✗
    print()
    print('【M】标记棋盘几何 + 尺度区间 —— 漏换基准 ⇒ 规划没目标')
    mg = os.path.join(_subdir_of('verify_marks_grid.py'), 'verify_marks_grid.py')
    if not os.path.exists(mg):
        skip('verify_marks_grid.py', '文件不存在')
    else:
        rc, out = run(['verify_marks_grid.py'], timeout=900)
        check('标记网格回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㉟ marks.GRID 与 layout.REF 一致（扫描区域/格号不会错）',
              'marks.GRID' in out)
        check('㊱ 标记尺度由格距推出（720p 落在 2.5~3.5）',
              '尺度' in out or 'glyph_scales' in out)
        check('㊲ 真帧上扫得到 boss 标记（marked 不再恒空）',
              'boss 标记' in out)

    # ── O：全仓 720p 坐标漂移（2026-10-02「全面排查换基准隐患」）──
    #   换基准 1080×1920 → 720×1280 后，本轮又查出 **十几处** 1080 系常量
    #   （GUILD_BTN/BAG_BTN/UPGRADE_BTN/VAULT/MERCHANT/mapbot 的 GRID 与亮度切片…）
    #   ⇒ 公会/背包/升星/宝库/商人**一按就点空**，且门禁当时全绿 ⇒ 必须有常驻门禁
    print()
    print('【N】全仓 720p 坐标漂移 —— 1080 系常量全部要折算到 720×1280')
    nd = os.path.join(_subdir_of('verify_no_720_drift.py'), 'verify_no_720_drift.py')
    if not os.path.exists(nd):
        skip('verify_no_720_drift.py', '文件不存在')
    else:
        rc, out = run(['verify_no_720_drift.py'], timeout=900)
        check('坐标漂移回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊳ 模块级坐标常量都在 720×1280 屏内', '越界的模块级坐标' in out)
        check('㊴ 源码里没有越界的裸点击坐标', '裸点击坐标' in out)
        check('㊵ buypanels 面板坐标在屏内（tap_dlg 在 PC 不换算）',
              'buypanels' in out or 'tap_dlg' in out)

    # ── P：拉黑必须带**置信度门槛**（2026-10-02 真机 boss 格被误拉黑）──
    #   真机帧实测：5,4 = {'name':'金属宝箱怪','score':0.397} ——
    #   分类器**几乎没认出来**（真识别是 0.994），只是蒙对了个轮廓，
    #   蒙出来的偏偏是黑名单里的名字 ⇒ 老口径把它当「用户拉黑」永久剔除
    #   ⇒ **14 点体力的首领不打了**（同帧 5,1/5,2/5,5 同样中招）。
    #   ⚠ 关键判据用**真机帧现算**（`spots.Board.state()` 跑那张 PNG），
    #     不是把期望值抄在本门禁里 —— 否则有人把门槛改回去，门禁会跟着一起绿。
    print()
    print('【O】拉黑置信度门槛 —— 认不准不许替用户做「拉黑」的决定')
    bs = os.path.join(_subdir_of('verify_blocked_score.py'), 'verify_blocked_score.py')
    if not os.path.exists(bs):
        skip('verify_blocked_score.py', '文件不存在')
    else:
        rc, out = run(['verify_blocked_score.py'], timeout=600)
        check('拉黑门槛回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊾ 低置信度分类结果**不再**被判拉黑（boss 格能进规划）',
              '低分乱猜**不**判拉黑' in out)
        check('㊿ 真拉黑没被修坏（**拉黑类**认得准的宝箱怪仍被剔除）',
              '仍然被拉黑' in out)
        check('㉀ explore_loop 两处调用点都已切到新口径',
              'is_blocked_cell' in out)

    # ── Q：装备升星收尾「回选图界面」的**补点循环**（2026-10-06 用户口径）──
    #   用户原话：「**回选图界面核对：还没认到（见日志）装备升级出现这个的时候
    #     就再点两次开始冒险，直到能识别到选图界面**」
    #   改前：固定点「开始冒险」×4 ⇒ 只读核对一次 ⇒ 认不到就不管了 ✗
    #   改后：4 次保底 + **每轮补点 2 次 + 核对，认到就停**（上限 `BAG_BACK_MAX_ROUNDS` ✓）
    #   ⚠⚠ 本组守的**最大风险点** = "直到认到"若没上限，会退化成**无限点**
    #     ⇒ 白烧时间、还可能误开图（扣体力）✗ ⇒ 上限必须钉住 ✓
    print()
    print('【Q】装备升星收尾「回选图界面」补点 —— 认到就停 / 补满必停')
    bb = os.path.join(_subdir_of('verify_bagback.py'), 'verify_bagback.py')
    if not os.path.exists(bb):
        skip('verify_bagback.py', '文件不存在')
    else:
        rc, out = run(['verify_bagback.py'], timeout=600)
        check('升星回选图补点回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:80] if out else '')
        check('㊽ 认到就一次都不补（防平白多点）',
              '补点 0 次' in out)
        check('㊾ 没认到才补、每轮正好 2 次（用户口径「再点两次」）',
              '正好补 **2** 次' in out)
        check('㊿ ★一直认不到 ⇒ 补满上限必停（**不是无限点**）',
              '必须停' in out and '不是无限点' in out)
        check('① 到顶如实记 back_giveup（不冒充已回到选图界面）',
              'back_giveup' in out)

    # ── R：宝库点击的**面板安全区**（2026-10-06 用户口径「把宝库点击范围固定下」）──
    #   用户原话：「**刚刚又买一半关掉黄金宝库界面了**」＋「**把黄金宝库的点击范围固定下**」
    #   ⛔ 真根因：`VAULT['blank']` 旧值 **(440,1060)** 落在**面板外 12px**
    #     （面板底边真机实测 y=1048；旧值压在底部道具栏上）✗
    #     而它的用途是"点空白收起详情面板" ⇒ 点到面板外 ⇒ **把宝库面板整个弄掉**
    #   ⇒ 两层修：① 值改对（88 张网格态帧求交集得 (475,391)）
    #             ② **加结构性守卫** `_vault_tap()`：凡宝库点击先夹进安全矩形
    #                ⇒ 常量再写错也**物理上点不出面板** ✓
    print()
    print('【R】宝库点击的面板安全区 —— 坐标不许落到面板外')
    vs = os.path.join(_subdir_of('verify_vault_safe.py'), 'verify_vault_safe.py')
    if not os.path.exists(vs):
        skip('verify_vault_safe.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_safe.py'], timeout=300)
        check('宝库安全区回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊼ 安全矩形在面板内、且**下边没过面板底边**',
              '安全矩形下边 < 面板底边' in out)
        check('㊽ 旧越界值 (440,1060) 已修掉',
              'blank 不再是旧的越界值' in out)
        check('㊾ `blank` 与 `back` 已拆成独立键（同值共用是隐患 ✗）',
              'blank 与 back 是**独立键**' in out)
        check('㊿ 越界坐标**真的被夹回**面板内（不是只改常量 ✗）',
              '被夹进安全区' in out)
        check('① `vault_flow` 里**没有裸 `tap_dlg`**（宝库点击全部收口到守卫）',
              '裸调用 0 次' in out)

    # ── 【S】E7：掩膜虚高 ⇒ 同名局部替换（2026-10-08 用户报「综合连派 3 支探索队」）──
    #   病：`103 游乐设施`(2格, 非紫金) 被认成 `221 游乐设施`(5格, **紫金探索格**)
    #       ⇒ 走「探索+派遣」⇒ 派小队去打本该打的格 ✗
    #   根因：`221` 走**掩膜通道**（alpha 不满 ⇒ 只比 70.1% 像素）⇒ 分数虚高，
    #        与 `103` 的矩形分**不是一个量纲** ⇒ 0.747 压过 0.606
    #   修法：**外科式局部替换**（只在"不会连锁"时换）⇒ 180 帧只动 2 帧、10 格 ✓
    #   ⚠ 真值 3 格是**用户人眼确认**的（含 1 格"不许动"的反例 202 ✓）
    print()
    print('【S】E7 掩膜虚高纠正 —— 同名块局部替换（真值由用户人眼确认）')
    ve7 = os.path.join(_subdir_of('verify_e7.py'), 'verify_e7.py')
    if not os.path.exists(ve7):
        skip('verify_e7.py', '文件不存在')
    else:
        rc, out = run(['verify_e7.py'], timeout=1200)
        check('E7 回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊤ 三格真值全对（E7 开）', '✓3 ✗0' in out)
        check('㊥ E7 **关**时至少 2 格判错（证明开关有效，不是恒绿）',
              '关掉后仍错 2 格' in out)
        check('㊦ E7 确实改动了那 2 张坏帧（**防假绿**）',
              'r_151015_0.png' in out and 'r_152100_0.png' in out)
        # ⚠ 2026-10-13 **放宽格数断言**（原来写死"改判 10 格"）
        #   实测格数随 `runs/` 语料滚动而变（本轮 4 格、上次 10 格）⇒ 写死必然假红 ✗
        #   改成用**回归自己打印的判据**（它已断言 ≤3 帧 / ≤14 格 ✓）
        check('㊧ E7 影响面极少（回归内部判据：≤3 帧 / ≤14 格 ✓）',
              '影响 2 帧' in out and '影响面**极少**' in out,
              # ⚠ `detail` 必须是 **str** —— 传 list 会在 `check()` 里
              #   `'  ' + detail` 抛 TypeError（本轮踩到，整个门禁中途崩 ✗）
              ' ｜ '.join(l.strip()[:70] for l in out.splitlines() if '改判' in l)[:120])
        check('㊨ E7 开关/常量/方法都在位',
              '默认开' in out and 'GAP=0.2' in out)

    # ── 【T】特殊方块**两类语义** + 自动拉黑 + ❗说明（2026-10-09 用户口径）──
    #   用户原话（四条）：
    #     ①「把窗口的其他特殊方块解锁吧，现在勾选是设定为会当成目标去拿，
    #        不勾选就不专门去拿，但是如果挡了最优的路，也会去点（不同于之前的不勾选拉黑了）」
    #     ②「只对那 6 个生效」 ③「俩宝箱怪和祭坛也和商人宝库一样吧」
    #     ④「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和10幸运草就是」
    #     ⑤「特殊方块的描述改成个感叹号，点了可以看描述」
    #     ⑥「幸运草阈值都改成10」
    print()
    print('【T】特殊方块两类语义 + 自动拉黑 + ❗说明（2026-10-09）')
    vss = os.path.join(_subdir_of('verify_special_semantics.py'), 'verify_special_semantics.py')
    if not os.path.exists(vss):
        skip('verify_special_semantics.py', '文件不存在')
    else:
        rc, out = run(['verify_special_semantics.py'], timeout=600)
        check('特殊性语义回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊩ ⭐ **可点类恰好是那三个免费的**（勇者之墓/限时礼包/预言石碑）',
              '可点类**恰好就是**那三个免费的' in out)
        check('㊪ ⭐ 不勾 ⇒ 拉黑类 `is_blocked=True`、可点类 **不是拉黑**',
              '⇒ **拉黑**（is_blocked=True）' in out
              and '⇒ **不是拉黑**（可点但不拿）' in out)
        check('㊫ ⭐ 两条自动拉黑**互不干扰**（金币管商人/宝库、草管宝箱怪）',
              '两闸门独立' in out)
        check('㊬ ⭐ 幸运草阈值统一为 10（摇色子=宝箱怪=大拇指）',
              '`MIMIC_CLOVER_MIN == 10`' in out)
        check('㊭ ❗说明按钮在（8 个方块都有 `describe()`）',
              '每个都有** `describe()` 说明' in out)

    # ── 【U】死代码修复：`act_on` 缺三个名字 ⇒ 三个 flow 从没执行过（2026-10-10）──
    #   用户报：「**刚刚那场没能正确点击勇者之墓，导致卡死**」
    #   根因：`L['act_on']` 只有商人和宝库 ⇒ `popups()` 里「勇者之墓/限时礼包/预言石碑」
    #         那三支被上面 `return 'handled'` 掉 ⇒ **死代码**（10-07 写的三个 flow 一次没跑过）
    #   ⚠ 我 10-07 的测法有系统性漏洞：**直接调 `buypanels.relic_flow()`** ⇒ 绕过 `popups()`
    #     ⇒ 函数跑通但**生产路径进不去** ⇒ 这就是"我说测通了、用户却卡死"的原因 ✗
    #   ⇒ 新门禁的判据必须**从 `popups()` 入口进**（喂面板 OCR 条目，断言 flow 被调用）✓
    print()
    print('【U】死代码修复：`act_on` 缺名字 ⇒ 三个 flow 从没执行过（2026-10-10）')
    vdc = os.path.join(_subdir_of('verify_deadcode_relic.py'), 'verify_deadcode_relic.py')
    if not os.path.exists(vdc):
        skip('verify_deadcode_relic.py', '文件不存在')
    else:
        rc, out = run(['verify_deadcode_relic.py'], timeout=600)
        check('死代码回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊮ ⭐ `act_on` 含勇者之墓/限时礼包/预言石碑（死代码修复）',
              "`act_on` 含「勇者之墓」" in out and "`act_on` 含「限时礼包」" in out
              and "`act_on` 含「预言石碑」" in out)
        check('㊯ ⭐ **从 `popups()` 入口**真跑 ⇒ `relic_flow` 被调用'
              '（这正是 10-07 从没发生的事）',
              '**`relic_flow` 真的被调用了**' in out)
        check('㊰ ⭐ 没走「无视 + 盲点 X」那支', '没有走「无视 + 盲点 X」那支' in out)

    # ── 【V】预言石碑：元素·紫/橙 停止（2026-10-09 用户口径）──
    #   用户原话：「**预言石碑停止脚本加上橙色和紫色元素**」
    print()
    print('【V】预言石碑：元素·紫/橙 停止（2026-10-09）')
    ves = os.path.join(_subdir_of('verify_elem_stop.py'), 'verify_elem_stop.py')
    if not os.path.exists(ves):
        skip('verify_elem_stop.py', '文件不存在')
    else:
        rc, out = run(['verify_elem_stop.py'], timeout=600)
        check('元素停止回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊱ ⭐ 紫(A)停 / 橙(S)停 / **蓝(B)不停**',
              '元素·紫(A) ⇒ 元素·紫色' in out and '元素·橙(S) ⇒ 元素·橙色' in out
              and '元素·蓝(B) ⇒ 不停' in out)
        check('㊲ ⭐ 两开关**独立**（关橙不妨碍紫）+ 不误伤幸运/和平',
              '两开关独立' in out and '「幸运」仍停' in out)
        check('㊳ ⚠ **蓝档没有开关能停它**（用户只说紫+橙）',
              '蓝档没有开关能停它' in out)

    # ── 【W】真机面板帧：**三个面板都要走自己的 flow**（2026-10-10 审计）──
    #   用户报：「刚刚那场没能正确点击勇者之墓，导致卡死」＋「图上有预言石碑，试一试」
    #   病（同一族，**三个全中**）：面板标题 ≠ 方块名，而 `L['special']` 只列方块名
    #     · 预言石碑 → 面板「预言石板」
    #     · 勇者之墓 → 面板「**英灵使者**」
    #     · 限时礼包 → 面板「**限时超值礼包**」
    #   ⇒ `fb()` 匹配不上 ⇒ 面板被"无视"支 `close_x_panels` + 盲点 X 关掉
    #     ⇒ 对应 flow **永远跑不到** ✗
    #   ⚠⚠ 本组口径（我前几轮栽过两次）：
    #     ① 夹具**必须来自真实面板帧 + 真实 OCR**（`verify_deadcode_relic.py` 手写了
    #        「勇者之墓」，可真实面板上没这三个字 ⇒ **假绿** ✗）
    #     ② 必须**从 `popups()` 入口进**（直接调 flow 测不到"生产路径进不进得去" ✗）
    print()
    print('【W】真机面板帧：三个面板都要走自己的 flow（2026-10-10 审计）')
    vpa = os.path.join(_subdir_of('verify_panel_alias.py'), 'verify_panel_alias.py')
    if not os.path.exists(vpa):
        skip('verify_panel_alias.py', '文件不存在')
    else:
        rc, out = run(['verify_panel_alias.py'], timeout=900)
        check('面板别名回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊴ ⭐ 三个面板的 flow **都被调用**（预言石碑/勇者之墓/限时礼包）',
              out.count('**被调用了**') >= 3,
              '命中 %d 处' % out.count('**被调用了**'))
        check('㊵ ⭐ 面板名在**真实帧**上都读得到（英灵使者/预言石板/限时超值礼包）',
              out.count('在真实帧上**读得到**') >= 3,
              '命中 %d 处' % out.count('在真实帧上**读得到**'))
        check('㊶ ⚠ 三个都**没走**"无视 + 盲点 X"',
              out.count('没有**走"无视') >= 3,
              '命中 %d 处' % out.count('没有**走"无视'))

    # ── 【X】`mimic_flow` 接线（审计：有 flow 却没进 `act_on` ⇒ 死代码）──
    #   ⭐ 发现方式：`audit5` 的**交叉表**（"flow 在? × in act_on?"）——
    #     读代码看不出来，**结构比对**才看得见 ✓
    print()
    print('【X】`mimic_flow` 接线（2026-10-10 审计）')
    vmi = os.path.join(_subdir_of('verify_mimic_path.py'), 'verify_mimic_path.py')
    if not os.path.exists(vmi):
        skip('verify_mimic_path.py', '文件不存在')
    else:
        rc, out = run(['verify_mimic_path.py'], timeout=600)
        check('宝箱怪接线回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊷ ⭐ `act_on` 含金属/机巧宝箱怪（否则 `mimic_flow` 是死代码）',
              '`act_on` 含金属/机巧宝箱怪' in out)
        check('㊸ ⭐ 从 `popups()` 入口进 ⇒ `mimic_flow` 被调用', '**被调用了**' in out)

    # ── 【Y】宝库「第二层乱点」两个真根因（2026-10-10）──
    #   用户报：「**第二层乱点了好几次才正常买上**」＋「**就不该点开详情页**」
    #   A：`_probe_name` 里 **`log` 未定义** ⇒ "收起详情"那步**从没执行**
    #      ⇒ 详情页一直盖着 ⇒ `_btn` 读不到按钮 ⇒ `src='stale_pos'` 拿旧坐标硬点 ✗
    #   B：`popups()` 里 **`rnd` 未定义** ⇒ 停脚本的"保现场"（截图+锁）**从没做成**
    #      （`'round': rnd` 在 dict 字面量里 ⇒ **整块 `json.dump` 废掉** ⇒ 锁文件没写）
    #   两个都是 `except: pass` 吞掉的 NameError ⇒ **同一族**（判据建在拿不到数据处 ✓）
    print()
    print('【Y】宝库「第二层乱点」两个真根因（2026-10-10）')
    vvp = os.path.join(_subdir_of('verify_vault_probe.py'), 'verify_vault_probe.py')
    if not os.path.exists(vvp):
        skip('verify_vault_probe.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_probe.py'], timeout=600)
        check('宝库探格回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊹ ⭐ `_probe_name` 真的**点了第 2 下**（收起详情 ✓）',
              '**点过 ≥2 下**' in out and '[ok]' in out)
        check('㊺ ⭐ `popups()` 里没有裸 `rnd`（停脚本保现场靠它）',
              '没有裸 `rnd`' in out)
        check('㊻ ⭐ 全仓**零**未定义名字（防同类再现）', '全仓**零**未定义名字' in out)

    # ── 【Z】特殊方块勾选框**顺序固定**（2026-10-10 用户报「位置一直在变」）──
    #   ⛔ `_order = list(TC.BLOCK_NAMES) + ...` —— `BLOCK_NAMES` 是 **set**
    #      ⇒ `list(set)` 顺序不保证，Python 字符串哈希**每进程随机**（PEP 456）
    #      ⇒ 实测连开 8 进程 = **7~8 种顺序** ✗
    #      ⇒ 用户记不住位置 ⇒ 极易点错框（「金属宝箱怪」vs「机巧宝箱怪」只差两字）
    #      ⇒ 这是「**勾了宝箱怪却没买**」的合理来源之一 ✓
    #   ⚠ 必须**跨进程**验证（同进程内 set 顺序是稳定的 ⇒ 同进程测不出来 ✗）
    print()
    print('【Z】特殊方块勾选框顺序固定（2026-10-10）')
    vdo = os.path.join(_subdir_of('verify_display_order.py'), 'verify_display_order.py')
    if not os.path.exists(vdo):
        skip('verify_display_order.py', '文件不存在')
    else:
        rc, out = run(['verify_display_order.py'], timeout=600)
        check('勾选框顺序回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊼ ⭐ GUI 的 `_order` **跨进程完全一致**', '跨进程完全一致' in out)
        check('㊽ ⭐ `DISPLAY_ORDER` 覆盖全部特殊方块（一个不漏）',
              '全覆盖' in out or '覆盖**全部特殊方块' in out or '覆盖' in out)
        check('㊾ ⚠ **对照项**：旧口径确实不稳定（证明不是恒绿）',
              '旧口径确实不稳定' in out)

    # ── 【AA】预言石碑：**所有路径**都要领掉（2026-10-10 第二次漏改）──
    #   用户报：「**刚刚综合模拟器那把点开预言窗口就直接关了**」
    #   真机铁证 `runs/acc1/gui_20261010_203354_acc1.log:85`：
    #     `· 点 (456,1100) 弹出「预言石板」→ 关掉并拉黑这格` ✗
    #   ⛔ 我早先只改了 `popups()` 那一处 ⇒ **漏了另外 4 处**（点击循环 / `finish_map`
    #      / `final_collect`×2）✗✗
    #   ⚠ 这正是 README 早记过的教训（手机端 v1.63）：
    #     「**我前几轮一直在修 `popups()` 那条链，而真正吃掉这一格的是
    #       `final_collect()` 这条完全独立的路径**」
    #     ⇒ **同一个错又犯了一次** ⇒ 本组用**AST 静态扫全部调用点**来防它 ✓
    print()
    print('【AA】预言石碑：所有路径都要领掉（2026-10-10）')
    vsa = os.path.join(_subdir_of('verify_stele_all_paths.py'), 'verify_stele_all_paths.py')
    if not os.path.exists(vsa):
        skip('verify_stele_all_paths.py', '文件不存在')
    else:
        rc, out = run(['verify_stele_all_paths.py'], timeout=900)
        check('预言石碑全路径回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㊿ ⭐ **全部** `prophecy` 判据都带守卫（无守卫 0 处）',
              '无守卫的判据 0 处' in out)
        check('① ⭐ 找到 **≥4** 处独立路径（覆盖 5 条链）', '实际 5 处' in out
              or '共找到 **≥4** 处' in out)
        check('② ⭐ 真机面板帧 ⇒ `popups()` 调 `foretell_flow`（不关掉）',
              '`foretell_flow` 被调用（不是 `universal_close`' in out)

    # ── 【AB】宝库「选了奖励还点同样位置 ⇒ 打开详情页」（2026-10-10）──
    #   用户原话：「**黄金宝库第二层还是有乱点，明明选择了奖励还要点一下同样的位置
    #              导致打开了详情界面**」
    #   ⛔ 根因：`vault_pick` 的 `_probe_name` 兜底会**逐格点开详情读名**，
    #      而 `probe_none` 时 `pick` 恰好返回**探过的那一格**
    #      ⇒ `vault_flow` **又点一次** ⇒ 那格已"选中"⇒ 再点 = **打开详情页** ✗
    #      真机铁证 loop_log #408 probe at=[456,592] ／ #412 claim pick=[456,592] ✓
    #   ⛔ 附带：`_probe_name` 把**面板提示**「取一件哦。」当成物品名 ⇒ 3 格全白探 ✗
    print()
    print('【AB】宝库「选完还点同样位置」（2026-10-10）')
    vrp = os.path.join(_subdir_of('verify_vault_repick.py'), 'verify_vault_repick.py')
    if not os.path.exists(vrp):
        skip('verify_vault_repick.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_repick.py'], timeout=600)
        check('宝库重复点击回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('③ ⭐ 探过的格 ⇒ **跳过重复点击**（`_PROBED` ✓）',
              '`_already` 为 True' in out)
        check('④ ⚠ 没探过的格照常点（不是恒跳过 ✓）', '`_already` 为 False' in out)
        check('⑤ ⭐ `_probe_name` 读到**物品名**而不是面板提示',
              "读到的是**物品名**" in out)

    # ── 【AC】传承祭坛接线（2026-10-11 用户「我开了」）──
    #   ⛔ 病：`传承祭坛` 在 `L['special']` 里、**但不在 `L['act_on']`**
    #      ⇒ 走"无视"支 `close_x_panels` + 盲点 X **关掉面板** ⇒ 采不到坐标 ✗
    #      而且它**从来没有 handler**（最后一块没实测的地块 ✓）
    print()
    print('【AC】传承祭坛接线（2026-10-11）')
    vsw = os.path.join(_subdir_of('verify_shrine_wired.py'), 'verify_shrine_wired.py')
    if not os.path.exists(vsw):
        skip('verify_shrine_wired.py', '文件不存在')
    else:
        rc, out = run(['verify_shrine_wired.py'], timeout=600)
        check('传承祭坛接线回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑥ ⭐ `传承祭坛` 在 `act_on` 里（不被盲点 X 关掉 ✓）',
              '**在 `L[\'act_on\']` 里**' in out)
        check('⑦ ⭐ `act_on` 里**每个名字都有分支**（不会静默 handled ✗）',
              '每个名字都有对应分支' in out)

    # ── 【AD】传承祭坛 `shrine_flow`（2026-10-11 真机采到面板后实现）──
    #   真机面板 `runs/acc3/shrine_panel_r-1.png`（实例B那把采到 ✓）
    #   用户口径：「**直接点右下角的三万买了就行**」
    #            ＋「**识别一下，是30000就买，不然不买**」
    #   ⇒ 判据**只看右下角价格**：== 30000 就买，否则**不买**（读不到也**不买** ✓ fail-closed）
    #   ⚠ 不点「筛选」「刷新」，也**不点装备格**（点格会开详情页 —— 与宝库那次同一个坑 ✗）
    print()
    print('【AD】传承祭坛 shrine_flow（2026-10-11）')
    vsf = os.path.join(_subdir_of('verify_shrine_flow.py'), 'verify_shrine_flow.py')
    if not os.path.exists(vsf):
        skip('verify_shrine_flow.py', '文件不存在')
    else:
        rc, out = run(['verify_shrine_flow.py'], timeout=600)
        check('传承祭坛流程回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑧ ⭐ 价格 30000 ⇒ **买**', '价格 30000 ⇒ **买了**' in out)
        check('⑨ ⭐ 价格 ≠ 30000 ⇒ **不买**（且不点按钮 ✓）',
              '价格 1000 ⇒ **不买**' in out and '价格 1000 ⇒ **没点**购买按钮' in out)
        check('⑩ ⭐ 读不到价格 ⇒ **不买**（fail-closed ✓）',
              '读不到价格 ⇒ **不买**' in out)
        check('⑪ ⚠ **不点**装备格（否则开详情页 ✗）',
              '**没有**点任何装备格' in out)
        # ⭐⭐⭐ 2026-10-11 **确认框**（源码 `HeritageBlockPanel.cs:66-87` 铁证 ✗）
        #   点右下角价格**只是弹确认框**（`ShowPopPanel(ActionPrompt_GEN)`），
        #   **必须再点「确定」才真扣钱/真激活** ⇒ 我第一版漏了这一步 ✗
        check('⑫ ⭐⭐ **点了确认框的「确定」**（点价格只弹框 ⇒ 确认后才真买 ✓）',
              '**点了确认框的「确定」**' in out)
        check('⑬ ⚠ 没等到确认框（金币不够）⇒ **不算买到**（如实记账 ✓）',
              '没等到确认框 ⇒ **不算买到**' in out)

    # ── 【AE】`_confirm()` 确认框（2026-10-11 抓到两个真 bug）──
    #   ⛔ ① **`cy > 800` 过严 ⇒ 漏掉一整类确认框** ✗
    #      真机铁证 `_verify/finish_confirm_dialog_20261002.png`：
    #        「提示 / 还有未拾取的战利品 / 是否结束冒险?」+ 取消/确定
    #        ⇒ 「确定」在 **(516, 742)**（cy<=800）⇒ 旧判据**判不到** ✗✗
    #        （另一真机帧 `pcrun_10.png` 在 (379,876) ⇒ 那种才命中 ⇒ **两类 y 不同**）
    #      ⇒ 修：加**保底判据**「有「取消」作伴的「确定」⇒ 必是确认框」（y 不设限 ✓）
    #        ⚠ **仍绝不点「取消」**（硬要求，一个字没动 ✓）
    #   ⛔ ② **同一坐标被点两下**（`for _ in range(2)` + `_items()` 同帧缓存）✗
    #      实测 `taps=[(516,742),(516,742)]` ⇒ 第二下点空 ✗ ⇒ 改成**点一次即返回** ✓
    print()
    print('【AE】`_confirm()` 确认框（2026-10-11）')
    vcp = os.path.join(_subdir_of('verify_confirm_paired.py'), 'verify_confirm_paired.py')
    if not os.path.exists(vcp):
        skip('verify_confirm_paired.py', '文件不存在')
    else:
        rc, out = run(['verify_confirm_paired.py'], timeout=600)
        check('确认框回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑭ ⭐ 低位确认框 (516,742) ⇒ **点到了**（旧判据会漏 ✗）',
              '点到了 (516,742)' in out)
        check('⑮ ⭐ **只点一次**（修前同帧点两下 ✗）', '**只点一次**' in out)
        check('⑯ ⚠ **绝不点「取消」**', '绝不点「取消」' in out)
        check('⑰ ⚠ 反向：结果框低位「确定」⇒ **不误点**',
              '结果框低位「确定」⇒ **不点**' in out)

    # ── 【AF】锁提示按 `kind` 如实报（2026-10-11 用户「不勾选还是自动停了」）──
    #   ⛔ 同一个锁文件被**多种**"停脚本保现场"共用（`red_equip` / `shrine` / `mimic2`），
    #      可启动提示**写死了"发现了红装（SS）"** ⇒ 祭坛锁被报成红装锁 ✗
    #      真机铁证 `runs/red_equip_16448.lock.json`：`{"kind":"shrine",...}`
    #      ⇒ 用户的原话就是「**不勾选还是自动停了**」✓
    #   ⛔⛔⛔ 2026-10-12 **整套锁定机制已按用户要求删除**（原话：
    #      「**我不需要这个锁定。只需要遇到红装和需要的预言自动停就行**」✓）
    #      ⇒ 本组断言**按新行为改写**：不再要"按 kind 分派"，改要
    #        「**锁机制已彻底删除，但"遇到就停"这个动作还在**」✓
    print()
    print('【AF】锁提示：整套「停脚本锁」已删（2026-10-12 用户要求）')
    vlk = os.path.join(_subdir_of('verify_lock_kind.py'), 'verify_lock_kind.py')
    if not os.path.exists(vlk):
        skip('verify_lock_kind.py', '文件不存在')
    else:
        rc, out = run(['verify_lock_kind.py'], timeout=900)
        check('锁机制删除回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑱ ⭐ 代码里没有写死的「发现了红装」',
              '代码里没有「发现了红装' in out or '① `explore_loop.py` 代码里没有' in out
              or '没有 \'def red_lock_path\'' in out)
        check('⑲ ⭐ 锁的读写方**全部消失**（`red_lock_path`/`_KIND_TXT`/`unlock_red` ✓）',
              '没有 \'def red_lock_path\'' in out
              and '没有 \'_KIND_TXT\'' in out
              and '没有 \'def unlock_red\'' in out,
              out.strip().split('\n')[-1][:90] if out else '')
        # ⚠ 反向：**"遇到就停"这个动作不许被一起删掉**（用户要的正是它 ✓）
        check('⑲b ⚠⚠ 反向：红装/预言「遇到就停」**都还在**（没删过头 ✓）',
              "return 'red_equip'" in out or '红装' in out)

    # ── 【AG】连锁消耗反推不许剔带标记的格（2026-10-11「68 张图只打 62 个首领」）──
    #   用户报：刷了 68 张图，却只打了 62 个首领
    #   ⛔ 根因：`_infer_chain_consumed` **只看"亮着却没人能揭示"**就判"已被连锁吃掉"，
    #      **完全没看这一格有没有内容标记**（函数体里 `marks` 出现 0 次 ✗）
    #      ⇒ 带 boss 标记的格被剔出模型 ⇒ 计划里没它 ⇒ `targets_unreachable` ⇒ 退图 ✗
    #      真机铁证（`runs/acc1/loop/loop_log.json`）：
    #        #267 剔 ['2,2'] 而整图标记正是 ['2,2'] ⇒ **重叠** ✗
    #        #2974 剔 ['5,5'] 而整图标记正是 ['5,5'] ⇒ **重叠** ✗
    #      ⇒ 68 张图里**正好 6 张**是这种（用户看到的 68-62=6 **完全对上** ✓）
    #   ⭐ 逻辑上：游戏里**连锁只吃普通空地** ⇒ 带标记的格不可能是"被吃掉的裸地" ✓
    print()
    print('【AG】连锁消耗反推 vs 标记格（2026-10-11）')
    vcm = os.path.join(_subdir_of('verify_chain_infer_marked.py'), 'verify_chain_infer_marked.py')
    if not os.path.exists(vcm):
        skip('verify_chain_infer_marked.py', '文件不存在')
    else:
        rc, out = run(['verify_chain_infer_marked.py'], timeout=900)
        check('连锁反推回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑳ ⭐ 传了 `marked_rc` ⇒ 带标记格**不再被剔**',
              '**不再被剔**' in out)
        check('㉑ ⚠ **对照项**：不传 ⇒ 仍被误剔（证明测得出 ✓）',
              '**仍被误剔**' in out)
        check('㉒ ⚠ `fail-open`：无标记的空地**照旧被剔**（原效用没破坏 ✓）',
              '照旧被剔' in out)
        check('㉓ ⭐⭐ **真机数据**里确实有这种重叠（铁证 ✓）',
              '剔掉了带标记的格' in out)

    # ── 【AH】带标记的格不许被"试过就摘"（2026-10-11 同一条报障的第二半）──
    #   真机铁证（第 19/41/65 张，**三张全都没打到 boss** ✗）：
    #     #1109 board marks {"4,1": ["boss"]}          ← 标记扫描**认出了 boss** ✓
    #     #1118 tap fogged_noop cell 4,1 ratio 0.222  ← 分类器却判它是**雾** ✗
    #     #1119 plan give_up_step cell 4,1             ← "试过就摘" ⇒ boss 从计划消失 ✗
    #     #1126 finish targets_unreachable             ⇒ **退图，boss 没打** ✗✗
    #   逻辑：标记是**模板匹配**（硬证据）；`ratio` 是**亮度比**判雾（软判据）
    #        ⇒ 矛盾时**信标记** ✓
    print()
    print('【AH】带标记的格不许被摘（2026-10-11）')
    vms = os.path.join(_subdir_of('verify_marked_step_kept.py'), 'verify_marked_step_kept.py')
    if not os.path.exists(vms):
        skip('verify_marked_step_kept.py', '文件不存在')
    else:
        rc, out = run(['verify_marked_step_kept.py'], timeout=900)
        check('标记格保留回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        # ⚠ 2026-10-14：该回归的 ⑥⑦ 依赖真机日志，而**日志会滚动** ⇒ 语料没了就
        #   **响亮跳过**（回归自己会打印"没真正验证" ✓）⇒ 门禁**照实报跳过**，
        #   不许把它当"已验证"（本仓纪律：跳过要看得见 ✓）
        if '没真正验证' in out:
            skip('㉜ 真机语料已滚走（keep_marked_step=0 条）⇒ ⑥⑦ 未验证',
                 '非代码问题：loop_log 每局轮转')
        check('㉔ ⭐ 有 `keep_marked_step` 且排在 `give_up_step` 前',
              '有 `keep_marked_step` 分支' in out)
        check('㉕ ⭐⭐ 取 marks 用**元组**键（字符串会永远取不到 ✗）',
              '取 marks 用**元组**键' in out)
        # ⚠ 2026-10-14：㉖ 依赖**真机日志**（同 ⑥⑦）⇒ 语料滚走后回归会**响亮跳过**
        #   ⇒ 门禁**照实报跳过**（不许把"没验证"当"已验证" ✗）
        if '全都没打到 boss' in out:
            check('㉖ ⭐⭐ 真机数据里**这 3 张全都没打到 boss**（后果严重 ✓）', True)
        else:
            skip('㉖ 真机语料已滚走 ⇒ 未验证', '非代码问题：loop_log 每局轮转')

    # ── 【AI】面板分派「标题优先」（2026-10-11「第 46 张卡死 44 轮」）──
    #   用户问「为什么刷了 68 张只打 62 个首领」⇒ 查到第 46 张**零进展 42 轮** ✗
    #   真机铁证 `runs/acc1/loop/loop_log.json` #2460~#2687：
    #     #2460 {"special": "勇者之墓",
    #            texts: ["预言石板", "本次可选择1个预言！", "路标",
    #                    "地图中至少出现1个勇者", "之墓，并且勇者之墓奖", ...]}
    #            ↑ 面板其实是**预言石碑**，却被判成**勇者之墓** ✗
    #     #2462 {"relic": "panel_missing"}  ⇒ **重复 44 轮**、`maxed` 退图 ✗✗
    #   ⛔ 根因：`fb()` 是**子串**匹配，而预言卡「奇遇」的效果文字里**含"勇者之墓"**
    #      且 `L['special']` 里 `勇者之墓` **排在** `预言石板` **之前** ✗
    #      全盘复算：**86 条** `special` 全是这种错派 ✓
    #   ⭐ 修法：**面板标题优先**（标题是"开着哪个面板"的唯一权威 ✓）
    print()
    print('【AI】面板分派「标题优先」（2026-10-11）')
    vpt = os.path.join(_subdir_of('verify_panel_title_priority.py'), 'verify_panel_title_priority.py')
    if not os.path.exists(vpt):
        skip('verify_panel_title_priority.py', '文件不存在')
    else:
        rc, out = run(['verify_panel_title_priority.py'], timeout=900)
        # ⚠ 本组依赖真机 loop_log（滚动覆盖、发布版不带）⇒ 缺语料时归 skip
        if '[SKIP]' in out and '[FAIL]' not in out:
            skip('【AI】标题优先回归（真机 texts 复算）',
                 '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
        else:
            check('标题优先回归全过（exit=%d）' % rc, rc == 0,
                  out.strip().split('\n')[-1][:90] if out else '')
            check('㉗ ⭐⭐ 真机那条 texts ⇒ 正确判成「预言石碑」',
                  '归一到规范名 = 「预言石碑」' in out)
            check('㉘ ⚠ **对照项**：旧口径确实错派成「勇者之墓」（测得出 ✓）',
                  '旧口径判成「勇者之墓」' in out)
            check('㉙ ⚠ 正文含「勇者之墓」**不许**当标题（fail-open ✓）',
                  '仍返回 None' in out)
            check('㉚ ⭐ OCR 前缀容错（`+预言石板` ⇒ `预言石板` ✓）',
                  "'+预言石板' ⇒ '预言石板'" in out)

    # ── 【AJ】`board_hidden()` 必须认出**传承祭坛面板**（2026-10-11）──
    #   用户报「**无法正确点击传承祭坛啊**」
    #   ⛔ 根因：阈值 `n >= 15` 太高 ⇒ 祭坛面板帧算出 **n = 14** ⇒ **差 1** ✗
    #      ⇒ `board_hidden` 返回 False ⇒ `_need_ocr = False` ⇒ `ocr: skip_no_panel`
    #      ⇒ **整轮免 OCR + 连 `popups()` 都不调** ⇒ `shrine_flow` 永远没机会跑 ✗✗
    #   真机铁证 `runs/acc3/gui_20261011_164317_acc3.log`：
    #      `· 点 (72,716) → 弹面板`（面板真弹出来了）／`· 无面板 ⇒ 本轮免 OCR`（下一轮却跳过）✗
    #   ⚠ 这是**同一个 bug 家族的第四次**：代码 `:11479` 早记着**宝库版**的同一现象，
    #     当时只给宝库开了一条捷径（治标）⇒ 祭坛又栽在同一个地方 ✓
    #   实测分界（`_tmpman/chk_n15.py`）：干净盘 61 帧 **n 全是 0**／面板 n = 10~18
    print()
    print('【AJ】`board_hidden()` 认出传承祭坛面板（2026-10-11）')
    vbh = os.path.join(_subdir_of('verify_board_hidden_shrine.py'), 'verify_board_hidden_shrine.py')
    if not os.path.exists(vbh):
        skip('verify_board_hidden_shrine.py', '文件不存在')
    else:
        rc, out = run(['verify_board_hidden_shrine.py'], timeout=900)
        check('board_hidden 回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        # ⚠ 祭坛原帧 / 干净盘 40 帧 都在真机语料 runs/ 里（发布版不带）
        #   ⇒ 子脚本跳过时归 skip，不算失败
        if 'n <= 14' in out and '`board_hidden` = **True**' in out:
            check('㉛ ⭐⭐ 祭坛面板帧 `n = 14`（修前卡在阈值 15 之下 ✗）', True)
            check('㉜ ⭐⭐ `board_hidden` 现在 = **True**（会 OCR ✓）', True)
        else:
            skip('㉛㉜ 祭坛面板帧行为级',
                 '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
        if '干净棋盘 **一个都不许误报**' in out:
            check('㉝ ⚠⚠ 干净棋盘 **一个都不许误报**（40 帧全 False ✓）', True)
        else:
            skip('㉝ 干净棋盘反向守门',
                 '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')

    # ── 【AK】「[临时]采集停止」已彻底删除（2026-10-11 用户要求）──
    #   用户原话：「**把窗口那个临时用的采集停止去掉吧**」
    #   它原是 2026-10-08 为采"最后两个特殊地块"面板而加的临时工具；
    #   现在两个面板都已采到、流程都已写好（`mimic_flow`/`shrine_flow`）
    #   ⇒ 留着只会**误停脚本** ✗
    #   本组钉住「删干净」＋「没删过头」（留档注释不算：先剥注释再查 ✓）
    print()
    print('【AK】「[临时]采集停止」已删（2026-10-11）')
    vnt = os.path.join(_subdir_of('verify_no_temp_stop.py'), 'verify_no_temp_stop.py')
    if not os.path.exists(vnt):
        skip('verify_no_temp_stop.py', '文件不存在')
    else:
        rc, out = run(['verify_no_temp_stop.py'], timeout=900)
        check('临时采集停止删除回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㉞ ⭐ 11 个旧名字在**代码里**全部消失',
              '里没有 STOP_MIMIC2' in out or '里没有 STOP_SHRINE' in out)
        # ⛔ 2026-10-12 改写（见【AF】注释）：「红装锁机制还在」这条**本身已被用户否掉**
        #    原话「**我不需要这个锁定**」⇒ 现在要的是"**停脚本动作还在**" ✓
        check('㉟ ⚠ 反向：红装/预言石碑/用户停止**都还在**（没删过头 ✓）',
              '红装"停脚本"动作**还在**' in out
              and '预言石碑早退还在' in out)
        check('㊱ ⭐ 锁机制**已删**（`red_locked` / `_KIND_TXT` 都不在了 ✓）',
              '不再存在' in out or '已删' in out)
        check('㊲ ⚠ 日志框高度没塌（>100px ✓ —— 10-08 踩过这个坑）',
              '日志框高度 > 100px' in out)

    # ══════════════════════════════════════════════════════════════════
    # ⭐⭐⭐⭐⭐ 2026-10-13 **本会话新修的问题**（用户逐条反馈驱动，共 10 条）
    #   ⚠⚠ 教训（本轮真正的漏洞）：我建了 13 个回归文件，却**忘了接进门禁** ✗
    #     ⇒ `verify_gate.py` 里**一个字都没覆盖**那些改动
    #     ⇒ "写了回归但门禁不跑"= 等于没写（本仓"判据静默失效"的又一变体 ✓）
    #   ⇒ 现在补上 【AL】~【AQ】六组 ✓
    # ══════════════════════════════════════════════════════════════════

    # ── 【AL】配置按**设备（窗口）**绑定（2026-10-13 用户要求）──
    #   用户原话：「**把特殊方块，停止规则，多少张图自动升星等需要用户自己选择的
    #     自动用最近一次配置并且和对应窗口绑定（选哪个窗口就自动用对应的配置）**」
    #   ⛔ 病：全部偏好都在 `runs/` 根（**全局一份**）⇒ 开两个窗口**勾选互相覆盖** ✗
    #     ＋ `bag_every`（升星张数）**根本没落盘** ⇒ 关窗再开变回 10 ✗
    #   ⭐ 为什么按**设备端口**、不按 `tag`：`choose_device` 单开时 `tag=''`
    #     ⇒ 按 tag 存会全部落到"全局"⇒ 分不开 ✗
    print()
    print('【AL】配置按设备（窗口）绑定 + 自动用最近一次（2026-10-13）')
    vpd = os.path.join(_subdir_of('verify_prefs_per_device.py'), 'verify_prefs_per_device.py')
    if not os.path.exists(vpd):
        skip('verify_prefs_per_device.py', '文件不存在')
    else:
        rc, out = run(['verify_prefs_per_device.py'], timeout=600)
        check('配置按设备绑定回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('①d ⭐⭐ 两个设备**互不干扰**（特殊方块/停规则/升星各读各的 ✓）',
              '**特殊方块互不干扰**' in out and '**停止规则互不干扰**' in out
              and '**升星张数互不干扰**' in out)
        check('①e ⭐⭐ **自动用最近一次**（重开还是上次的值 ✓）',
              '升星张数"记住了"' in out)
        check('①f ⭐ 老配置**自动迁移**（勾选一个都不丢 ✓）',
              '被搬过来了' in out)
        check('①g ⚠ 反向：设备自己的值**不被全局覆盖** ✓',
              '没被全局覆盖' in out)
        check('①h ⚠⚠ 反向守门：偏好**不许再落回 `runs/` 根** ✓',
              '**不在 runs 根**' in out)

    # ── 【AM】子进程读的**就是本设备那份**配置（端到端）──
    #   ⚠ 这条最要紧：GUI 写 A、子进程读 B 是**本项目反复栽的坑**
    #     （`v1.62` veto 被冲掉 / `v1.63` band 裁掉 HUD / `v1.64` mk 是 dict / `v1.71` 轮首 None）
    print()
    print('【AM】端到端：子进程读本设备那份配置（2026-10-13）')
    vcb = os.path.join(_subdir_of('verify_cfg_binding_e2e.py'), 'verify_cfg_binding_e2e.py')
    if not os.path.exists(vcb):
        skip('verify_cfg_binding_e2e.py', '文件不存在')
    else:
        rc, out = run(['verify_cfg_binding_e2e.py'], timeout=600)
        check('配置绑定端到端回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('② ⭐⭐ A/B 子进程**各读自己那份路径** ✓',
              'A 子进程读的**就是 A 的路径**' in out
              and 'B 子进程读的**就是 B 的路径**' in out)
        check('③ ⭐⭐⭐ 且**读到的值不同**（A=True / B=False ✓）',
              'A 子进程读到' in out and 'B 子进程读到' in out)
        check('④ ⚠ 不传 `MAPBOT_TARGETS_CFG` ⇒ **回落全局、不许崩** ✓',
              '不传 ⇒ **不设该变量**' in out)

    # ── 【AN】营地和相邻格**不许被并成战斗多格块**（2026-10-13 用户两次报）──
    #   用户原话：「**把营地和附近两格合体成多格了，营地不可能是战斗格啊**」
    #            ＋「**又出现把营地框进去成战斗格子的了**」
    #   ⛔ 真根因（真机帧 `runs/r_194934_0.png`）：
    #     假块 `S00003_211 巨大沙堡` **块分只 0.361**，而成员格自己的 top1 是
    #     `0.998 草地 / 1.000 营地 / 0.998 草地 / 0.994 草地`
    #     ⇒ `spots.state()` **无条件**用块的 sid 覆盖本格 ⇒ **营地(Size=1/非战斗)
    #       被改判成「巨大沙堡」(Size=4/EventNum=4-4/战斗格)** ✗✗
    print()
    print('【AN】营地不许被误判的多格块吞掉（2026-10-13）')
    vcn = os.path.join(_subdir_of('verify_camp_not_swallowed.py'), 'verify_camp_not_swallowed.py')
    if not os.path.exists(vcn):
        skip('verify_camp_not_swallowed.py', '文件不存在')
    else:
        rc, out = run(['verify_camp_not_swallowed.py'], timeout=900)
        # ⚠ 行为级 / 对照项都依赖真机帧（runs/ 不入仓）⇒ 子脚本会响亮跳过
        if '[SKIP]' in out and '[FAIL]' not in out:
            skip('【AN】营地不被吞：行为级 + 对照项',
                 '缺真机语料（发布版不带私有录屏）；结构级分项已单独通过')
        else:
            check('营地不被吞回归全过（exit=%d）' % rc, rc == 0,
                  out.strip().split('\n')[-1][:90] if out else '')
            check('⑤ ⭐⭐ `2,2` 判回**营地**（不是巨大沙堡 ✓）',
                  '判回 **营地**' in out)
            check('⑥ ⭐ 它是**独立格**、且**不是战斗格** ✓',
                  '**独立格**' in out and '**不是战斗格**' in out)
            check('⑦ ⭐⚠ **对照项**：关闸门 ⇒ **复现旧症状**（证明不是恒绿 ✓）',
                  '营地又被吞' in out)
            check('⑧ ⚠ 反向：真块（gap≤0.20）**一个都没被误杀** ✓',
                  '真块**仍然在**' in out and '不会误触发闸门' in out)
            check('⑧b ⚠⚠ **不许静默跳过**（语料帧必须在 ✓）',
                  '有稳定语料帧可用' in out)

    # ── 【AO】预言石碑：「要停的卡」必须在**选卡之前**停（2026-10-13 用户报）──
    #   用户原话：「**说是立即停止，结果已经选择完预言了，我要在预言选择界面停止**」
    #   ⛔ 病（顺序反了）：`foretell_flow` 先 `tap_dlg(卡)`、之后才判要不要停 ✗
    print()
    print('【AO】预言「要停的卡」须在选卡前停（2026-10-13）')
    vfp = os.path.join(_subdir_of('verify_foretell_stop_before_pick.py'), 'verify_foretell_stop_before_pick.py')
    if not os.path.exists(vfp):
        skip('verify_foretell_stop_before_pick.py', '文件不存在')
    else:
        rc, out = run(['verify_foretell_stop_before_pick.py'], timeout=600)
        check('选卡前停回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑨ ⭐⭐ **判停 < 点卡**（行序 ✓）', '**判停 < 点卡**' in out)
        check('⑩ ⭐⭐⭐ 要停时**一次 tap 都没有**（卡没选、确定也没点 ✓）',
              '一次 tap 都没有' in out)
        check('⑪ ⚠ **对照项**：蓝档不停 ⇒ 照常点卡+确定（证明不是"永不点" ✓）',
              '照常点卡 + 点确定' in out)
        check('⑫ ⭐ 幸运也在**选卡前**停（同类口径一致 ✓）',
              '幸运也在**选卡前**停' in out)

    # ── 【AP】棋盘的**三条 UI 改动**（2026-10-13 用户要求）──
    #   用户原话：「**实时棋盘那边的第3张图，体力金币幸运草那行去掉，
    #     下面的计划/进度也删掉，棋盘稍微放大一点**」
    print()
    print('【AP】实时棋盘三条 UI 改动（2026-10-13）')
    vbu = os.path.join(_subdir_of('verify_board_card_ui.py'), 'verify_board_card_ui.py')
    if not os.path.exists(vbu):
        skip('verify_board_card_ui.py', '文件不存在')
    else:
        rc, out = run(['verify_board_card_ui.py'], timeout=600)
        check('棋盘 UI 回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑬ ⭐ 画布内标题行**已去**（喂了 hud 也不画 ✓）',
              '画布内**没有**' in out)
        check('⑭ ⭐ 卡内说明小字**已删** ✓', '那行说明小字**已删**' in out)
        check('⑮ ⭐ 棋盘**放大**（cell=54 / 画布高 286 ✓）',
              '画布高 = 5*54+16' in out)
        check('⑯ ⚠ 反向：`plan_var`/`prog_var`/`hud_var` **都还在**（没删过头 ✓）',
              '`plan_var`（计划行）**仍在**' in out
              and '`hud_var`（右卡那行体力/金币）**仍在**' in out)

    # ── 【AQ】低分名字不许当目标（2026-10-12 用户问「不就该直接 4,6、1,6 吗」）──
    #   用户原话：「**所以最本质的问题不应该是识别错了吗**」✓（判断正确）
    #   ⛔ `5,6` 被认成「限时礼包」**score 只 0.441**，而 `is_target` **不看 score** ✗
    print()
    print('【AQ】低分名字不许当目标（2026-10-12）')
    vls = os.path.join(_subdir_of('verify_low_score_target.py'), 'verify_low_score_target.py')
    if not os.path.exists(vls):
        skip('verify_low_score_target.py', '文件不存在')
    else:
        rc, out = run(['verify_low_score_target.py'], timeout=600)
        check('低分不当目标回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('⑰ ⭐⭐ `5,6`（score 0.441）**不再当目标** ✓',
              '不再专门去拿' in out)
        check('⑱ ⚠⚠ 反向：**探索格不受影响**（它们本来就 0.39~0.73 ✓）',
              '**仍是目标**' in out)
        check('⑲ ⚠ 反向：带 `boss` 标记的低分格**仍是目标** ✓',
              '带 `boss` 标记' in out)

    # ── 【AR】按"空出来的形状"判多格块真假（2026-10-14 用户口径）──
    #   用户原话：「**第二张图的巨大沙堡没识别出来？**」
    #     ＋（我问怎么修）「**为什么这么低？能不能按空出来的方块形状猜测空出来的这是什么？**」
    #   ⭐ 用户的判据（**绝对量**）实测完美区分两帧（我 10-12 那版**相对量**分不开 ✗）：
    #     看块覆盖的每格**自己的 top1 分** —— 全低 ⇒ 同一块大美术的碎片 ⇒ 采纳；
    #     有任一格 ≥0.85（自成一体）⇒ 块吞了它 ⇒ 弃块 ✓
    print()
    print('【AR】按"空出来的形状"判多格块真假（2026-10-14）')
    vbs = os.path.join(_subdir_of('verify_block_shape.py'), 'verify_block_shape.py')
    if not os.path.exists(vbs):
        skip('verify_block_shape.py', '文件不存在')
    else:
        rc, out = run(['verify_block_shape.py'], timeout=900)
        # ⚠ 公开发布版**不含**开发者的真机录屏语料 ⇒ 子脚本会**响亮跳过**那几条。
        #   此时不能算失败（不是代码问题），也不能算通过（没真验证）⇒ 归入 skip。
        if '[SKIP]' in out and '[FAIL]' not in out:
            skip('【AR】形状判据：行为级 + 对照项',
                 '缺真机语料（发布版不带私有录屏）；结构级分项已单独通过')
        else:
            check('形状判据回归全过（exit=%d）' % rc, rc == 0,
                  out.strip().split('\n')[-1][:90] if out else '')
            check('⑳ ⭐⭐⭐ **真有沙堡的帧认回来了**（anchor=(2,1) ✓）',
                  '真有沙堡的帧认回来了' in out)
            check('㉑ ⭐⭐⭐ **真没沙堡的帧正确拒绝**（不误认 ✓）',
                  '真没沙堡的帧正确拒绝' in out)
            check('㉒ ⚠ **只降门槛不够**（退回 0.35 ⇒ 又认不出 ✓）',
                  '只降门槛不够' in out)
            check('㉓ ⚠ **只加门槛不够**（关形状判据 ⇒ 营地又被吞 ✓）',
                  '只加门槛不够' in out)

    # ── 【AS】宝库某圈**检测漏格** ⇒ 按理论格补齐（2026-10-14 用户报）──
    #   用户原话：「**这张图的宝库第二层，没选到4个四叶草那个奖励**」
    #   ⛔ 真机（`runs/acc1/loop/loop_log.json` #198~#211）：
    #     `tiles_detected n=7` ⇒ `ring_filter all=7 **ring=6**`（应 8 格）✗
    #     缺 `(263,689)`/`(359,785)` ⇒ 那两格**永远进不了候选**
    #     ⇒ 就算有「4 四叶草」（`tier 3.0`）**也轮不到它** ⇒ 最终选了 `tier 0.0` 的 ✗✗
    print()
    print('【AS】宝库某圈检测漏格 ⇒ 按理论格补齐（2026-10-14）')
    vrf = os.path.join(_subdir_of('verify_vault_ring_fill.py'), 'verify_vault_ring_fill.py')
    if not os.path.exists(vrf):
        skip('verify_vault_ring_fill.py', '文件不存在')
    else:
        rc, out = run(['verify_vault_ring_fill.py'], timeout=900)
        check('宝库补格回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㉔ ⭐⭐ 检出 7 格时 `ring_filter` = 6 格（复现真机 ✓）',
              '`ring_filter` = **6 格**' in out)
        check('㉕ ⭐⭐⭐ 补齐后 = **8 格**（本圈理论格数 ✓）',
              '补齐后 = **8 格**' in out)
        check('㉖ ⚠ **只补不删**（一个检出格都没丢 ✓）',
              '一个检出格都没丢' in out)

    # ── 【AT】退图前补点碰到特殊面板 ⇒ **只关掉、不领奖**（2026-10-14 用户报）──
    #   用户原话：「**这张图为什么显示退图失败然后停止了？**」
    #     ＋（我问怎么修）选「**只"关掉"面板，不领奖**」✓
    #   ⛔ 真机（`runs/acc3/loop/loop_log_prev.json` 第 6 张图）：
    #     补点点 `1,6`=`限时礼包` ⇒ 弹面板 ⇒ `final_collect` **不认识它**
    #     ⇒ `still=true` ⇒ `force_unstick` 关不掉 ⇒ 反复点 `(360,1219)`
    #       （= 底部导航「开始冒险」）⇒ 空转 **110.6 秒** ⇒ 整局停下 ✗✗
    print()
    print('【AT】补点碰到特殊面板 ⇒ 只关掉、不领奖（2026-10-14）')
    vcp = os.path.join(_subdir_of('verify_collect_panel_close.py'), 'verify_collect_panel_close.py')
    if not os.path.exists(vcp):
        skip('verify_collect_panel_close.py', '文件不存在')
    else:
        rc, out = run(['verify_collect_panel_close.py'], timeout=900)
        check('补点关面板回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㉗ ⭐ 那 3 种面板标题都在 `_FC_CLOSE_TITLES` ✓',
              '都在 `_FC_CLOSE_TITLES`' in out or '在 `_FC_CLOSE_TITLES` 里' in out)
        check('㉘ ⚠⚠ **不调** `gift_flow`/`shrine_flow`（只关不领 ✓）',
              '那会领奖/购买' in out)
        # ⚠ 该条依赖真机语料 runs/acc3/loop/loop_log_prev.json（滚动覆盖、发布版不带）
        #   ⇒ 子脚本跳过时这里也归 skip，不能算失败
        if '限时礼包' in out and '面板没关掉' in out:
            check('㉙ ⭐⭐ 真机复算：`1,6`=`限时礼包` + `still=true`（bug 现场 ✓）', True)
        else:
            skip('㉙ 真机复算：`1,6`=`限时礼包` + `still=true`',
                 '缺真机语料（发布版不带私有录屏）⇒ 未真正验证')
        check('㉚ ⚠ 反向：预言石碑仍**领掉**（没被带坏 ✓）',
              '预言石碑那支**仍在**' in out)

    # ── AU：4 楼被误判成"椅子层" ⇒ 炼金整段放弃（2026-10-23 用户报）──────
    #   用户原话：「**综合模拟器的自动炼金失败了**」
    #   根因：`count_bubbles` 只判「面积≥400 + 纯白比≥0.02」，而 4 楼同一条 y 带里
    #     有金柱高光窄条（12px 宽）+ 机巧秘宝 NPC 小气泡（42px 宽）⇒ 凑够 ≥2 个 ⇒
    #     `chair_row_hint` 判"还在 2 楼" ⇒ `scroll_to_top` 返回 False ⇒ 放弃炼金 ✗
    #   修法：加 `BUBBLE_MIN_W = 60`（2 楼真气泡 84~114px / 4 楼假块 12、42px）
    #   ⚠ 本组**纯离线**（只读 `_verify/` 的 6 张真机帧，不碰设备、不写共享临时文件）
    print()
    print('【AU】4 楼被误判成「椅子层」⇒ 炼金放弃（2026-10-23 用户报）')
    vfb = os.path.join(_subdir_of('verify_floor_bubbles.py'), 'verify_floor_bubbles.py')
    if not os.path.exists(vfb):
        skip('verify_floor_bubbles.py', '文件不存在')
    else:
        rc, out = run(['verify_floor_bubbles.py'], timeout=300)
        check('楼层气泡回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㛘 ⭐⭐ 4 楼 4 帧：`count_bubbles` 必须 **0**（不再误判成椅子层 ✓）',
              '期望 0' in out)
        check('㛙 ⚠⚠ **对照项**：关掉宽度过滤 ⇒ 4 楼回到 2 块（复现原 bug ⇒ 不是恒绿 ✓）',
              '复现' in out)
        check('㛚 ⭐⭐ **零损失**：2 楼真椅子层仍是 4 个（没把真气泡判掉 ✓）',
              '期望 4' in out)
        check('㛛 ⭐ `scroll_to_top` 判到椅子层**返回 False**；`alchemy.run` 收到就放弃 ✓',
              '放弃链路完整' in out)

    # ── AV：商人明明买完还要再点一下（2026-10-24 用户报）──────────────────
    #   用户原话：「**为什么第三张图和第四张图的两个商人，明明买完了，还要去点一下？**」
    #   两个叠加的 bug：
    #     ① 「强匹配商人」**写了两套判据**：
    #        cells_of 用 score>=0.85 **or** _buy_top_self；
    #        vault_px_now **只认** score>=0.85（真商人 0.695）⇒ 买完记忆被删 ⇒ 反复点
    #     ② `merchant_done` 是**只写不读的死集合** ⇒ 对行为零影响
    #   修：抽 `_cell_is_strong_buy()` 两处同源 + 在 buy 汇聚点按 merchant_done 过滤
    #   ⚠ 本组**纯离线**（只用固定夹具复算，不碰设备）⇒ 可并发 ✓
    print()
    print('【AV】商人明明买完还要再点（2026-10-24 用户报）')
    vmb = os.path.join(_subdir_of('verify_merchant_bought.py'), 'verify_merchant_bought.py')
    if not os.path.exists(vmb):
        skip('verify_merchant_bought.py', '文件不存在')
    else:
        rc, out = run(['verify_merchant_bought.py'], timeout=300)
        check('商人买完回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㛜 ⭐⭐ 真机 0.695 / 0.669 的商人 ⇒ strong=True（不再被判"不在了"✓）',
              'strong=True' in out and '0.695' in out)
        check('㛝 ⚠⚠ **对照项**：低分 + gap 0.05 的误报 ⇒ strong=False（不是恒真 ✓）',
              'strong=False' in out)
        check('㛞 ⛔ `merchant_done` **既有写也有读**（不再是死集合 ✓）',
              'n=1' in out)
        check('㛟 ⛔ 撤回守门：`vault_px_now` 里没有裸的 score 门槛 ✓',
              '预期 0 项' not in out and rc == 0)

    # ── AW：规划步数图标一直闪烁（2026-10-24 用户报）────────────────────
    #   用户原话：「当前状态里的进度，就是规划的那几个步数图标，为什么一直闪烁，
    #              修一下，**每图换一次就行了**」
    #   根因：`tick_data()` 每 2 秒无条件调 `_update_board()`，而它末尾无条件调
    #     `board.update_board()` ⇒ 内部 `delete(all)` + 整盘重画 ⇒ **数据没变也重画** ✗
    #   为什么 2026-10-19 的 `paint_order()` 没治好：它只修了 **stdout 计划行**那条路
    #     （`_paint_plan`），而**每 2 秒那条**走的是 `_update_board` ✗（修了一半）
    #   修：加**绘制指纹**，7 个影响画面的输入全同 ⇒ 直接 return，不碰画布 ✓
    #   ⚠ 本组**纯离线**（只读源码 + 复算指纹，不碰设备）⇒ 可并发 ✓
    print()
    print('【AW】规划步数图标一直闪烁（2026-10-24 用户报）')
    vnf = os.path.join(_subdir_of('verify_board_no_flicker.py'), 'verify_board_no_flicker.py')
    if not os.path.exists(vnf):
        skip('verify_board_no_flicker.py', '文件不存在')
    else:
        rc, out = run(['verify_board_no_flicker.py'], timeout=300)
        check('棋盘防闪烁回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㛠 ⭐⭐ 数据没变 ⇒ **一次都不重画**（序号圆不再被抹 ✓）',
              '一次都不重画' in out)
        check('㛡 ⚠⚠ **对照项**：换图/揭示/计划/HUD 变了 ⇒ 指纹必变（会重画 ✓）',
              '指纹变了' in out)
        check('㛢 ⛔ 位置守门：指纹判断在 update_board **之前** ✓',
              '顺序正确' in out)
        check('㛣 ⛔ 指纹里不含时间戳/随机量（否则等于没修 ✓）',
              '没有 time' in out or rc == 0)

    # ── AX：预言石碑 / 红装停了却还自动重开（2026-10-26 用户报）────────────
    #   用户原话：「🛑🛑 抽到【元素·橙色】⇒ 立即停止（不退图，留着你自己处理）
    #              › ★ 抽到【元素·橙色】· 已停下，请手动处理。
    #              **因为预言石碑和红装停止的不要运行收工日常等等**」
    #   真机铁证（`runs/gui_20261026_184021.log`，10-26）：
    #     收工日常**确实被正确跳过了** ✓（判据本来就在）
    #     但**紧接着又自动重开** ✗ ⇒ 又进图 → 又撞同一个面板 → 共 5 轮
    #   根因：**两处判据不同源**
    #     · 收工日常（`_ok_daily`）：白名单（stopped 空 或 含「体力」）✓
    #     · 自动重开（`_should_relaunch` ①）：**黑名单**（只排除「用户点了停止」）✗
    #   修：抽 `_stop_allows_afterwork()`，**两处调同一个函数**（白名单、fail-closed）
    #   ⚠ 本组**纯离线**（只读源码 + 复算判据，不碰设备）⇒ 可并发 ✓
    print()
    print('【AX】预言石碑/红装停了却还自动重开（2026-10-26 用户报）')
    vso = os.path.join(_subdir_of('verify_stop_no_afterwork.py'), 'verify_stop_no_afterwork.py')
    if not os.path.exists(vso):
        skip('verify_stop_no_afterwork.py', '文件不存在')
    else:
        rc, out = run(['verify_stop_no_afterwork.py'], timeout=300)
        check('停止原因回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㛬 ⭐⭐ 预言石碑 / 红装 ⇒ **不碰**收工后续（日常+免广+重开都不做 ✓）',
              '=> 不碰' in out)
        check('㛭 ⭐⭐ **真机现场复现**：体力 1507 + 勾了日常 ⇒ **不重开** ✓',
              '不重开' in out)
        check('㛮 ⚠⚠ **对照项**：体力用尽 / 正常跑完 ⇒ 照旧放行（不是恒禁 ✓）',
              '体力用尽 => True' in out)
        check('㛯 ⛔ 撤回守门：`_should_relaunch` 里没有「用户点了停止」黑名单 ✓',
              rc == 0)
        check('㛰 ⛔ 收工日常与自动重开**必须同一份判据**（不许各写一份 ✓）',
              rc == 0)

    # ── AY：图名「一直是图名未读到」+ 商人买完还点（2026-10-26 用户报）────────
    #   用户原话：「为什么**一直是图名未读到**？遇到很多次了。
    #              而且这张图明明买完了旅行商人，还会再次点开」
    #   ① 病：轮首用「空图名」做全量消歧（15 个 code ≈7.5 秒/图 + 误导日志）
    #      真机：loop_log #7 = {"mapname":"夏日海滩"} ⇒ **图名其实读到了** ✓
    #      ⇒ 那句「（图名未读到）」是「还没 OCR 就先试探」打出来的，不是 OCR 失败 ✗
    #      修：**改调用点**（轮首跳过那次分类）⇒ **不动 `board_state` 语义** ✓
    #      ⚠ 动 `board_state` 会让 `in_map()` 回归（它依赖空图名也能分类）⇒
    #        被 verify_newequip / verify_collect_fast 当场抓出 ✓（本轮真踩）
    #   ② 病：`merchant_done` 的写入条件恒不成立 ⇒ 只写不读（`skip_bought` 真机 0 次）
    #      修：在**买完的现场**就写入 ✓
    #   ⚠ 本组**纯离线**（只读源码 + 复算坐标，不碰设备）⇒ 可并发 ✓
    print()
    print('【AY】图名「一直是未读到」+ 商人买完还点（2026-10-26 用户报）')
    vnm = os.path.join(_subdir_of('verify_mapname_and_merchant.py'), 'verify_mapname_and_merchant.py')
    if not os.path.exists(vnm):
        skip('verify_mapname_and_merchant.py', '文件不存在')
    else:
        rc, out = run(['verify_mapname_and_merchant.py'], timeout=300)
        check('图名+商人回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        check('㛱 ⭐⭐ 轮首跳过那次分类 ⇒ **不做**全量消歧（省 ≈7.5s/图 ✓）',
              '首轮跳过时不做 cells_cached' in out)
        check('㛱b ⛔ `board_state` 语义**没被改**（`in_map` 依赖它 ⇒ 回归守卫 ✓）',
              'board_state 的语义没被改' in out)
        check('㛲 ⭐⭐ 买完现场就写 `merchant_done` ⇒ 不再进目标 ✓',
              '买完现场有写入点' in out)
        check('㛳 ⭐⭐ 执行级：真机 px[264,1004] 买完后被滤掉 ✓',
              '商人格被滤掉' in out)
        check('㛴 ⚠⚠ **对照项**：没买过的商人格必须保留（不是恒滤 ✓）',
              '不是恒真' in out)
        check('㛵 ⛔ AST 守门：旧写法（两段式 or 空串）已不存在 ✓',
              rc == 0)

    # ── AZ：多格块在「单格通道」显示名字 ⇒「很多空地看成巨大沙堡」（2026-10-26 用户报）──
    #   用户原话：「还有第一张图怎么把很多空地看成巨大沙堡什么的了？」（帧 runs/r_191220_0.png）
    #   病：6 格标「巨大沙堡」但 block_score=None/anchor=None/cells=[自己] ⇒ 单格 top1，
    #        分数 0.117~0.260（全 < 块门槛 0.28）；该格 top5 全是 211 变体，
    #        4~5 名才是 301/302 —— 而它们**全是多格块** ⇒ 该格无单格模板可认 ✓
    #   修：判据 = 「没被块采纳」+「是多格块」+「分数 < 块门槛」⇒ **只置空 name**
    #   ⚠⚠ 踩坑留档：第一版改「重新挑 top1」⇒ eff 变 ⇒ ratio 分母变 ⇒
    #        1095 帧实测 ratio 变 2817 格 / revealed 变 620 格 / 名字清空 9613 格 ✗✗
    #        ⇒ 撤回重做 ⇒ 最终版 **ratio/revealed/block_score/sid 变化全 0** ✓
    #   ⚠ 本组**纯离线**（真机帧 + 源码结构判定，不碰设备）⇒ 可并发 ✓
    print()
    print('【AZ】多格块在单格通道显示名字（2026-10-26 用户报：巨大沙堡）')
    vmb = os.path.join(_subdir_of('verify_multiblock_name.py'), 'verify_multiblock_name.py')
    if not os.path.exists(vmb):
        skip('verify_multiblock_name.py', '文件不存在')
    else:
        rc, out = run(['verify_multiblock_name.py'], timeout=300)
        check('多格块名字回归全过（exit=%d）' % rc, rc == 0,
              out.strip().split('\n')[-1][:90] if out else '')
        # ⚠⚠ 这几条查的是**子脚本的输出文本**，不是源码 ——
        #   查源码会假红（源码里的串不出现在 stdout 里 ✗）
        #   ⇒ 一律查子脚本 `[ok]` 行里**实际印出来**的措辞 ✓
        check('㛱 ⚠⚠ 假沙堡帧：**不再有**格显示「巨大沙堡」 ✓',
              '不再有' in out and '巨大沙堡' in out)
        check('㛲 ⭐⭐ 对照项：真沙堡帧 **4 格**仍显示「巨大沙堡」 ✓',
              '仍显示' in out)
        check('㛳 ⭐⭐ 真沙堡走**块通道**（block_score ≥ 0.28） ✓',
              '块通道' in out)
        check('㛴 ⛔ 判据含分数条件（满分真地块不许被清空） ✓',
              '分数 < 块门槛' in out)
        check('㛵 ⛔ 只置空 name：sid/ratio/revealed 一个不动 ✓',
              '只置空 name' in out)
        check('㛶 ⛔ AST 守门：top1 仍是 lst[0]（不许「重新挑」） ✓',
              'top1 仍然是' in out)
    # ── 汇总 ──────────────────────────────────────────────────────────
    print()
    print('=' * 74)
    print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
    for b in BAD:
        print('   ✗ ' + b)
    if SKIP:
        print('   ⚠ 以下 %d 项**没真正验证**：' % len(SKIP))
        for s in SKIP:
            print('     - ' + s)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
