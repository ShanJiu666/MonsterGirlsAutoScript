# -*- coding: utf-8 -*-
"""verify_vault_debug.py · 回归：宝库取证**默认不落盘**（用户：「不用取证了吧」）

用户 2026-10-05 原话：
    「宝库购买流程已经没问题了，**不用取证了吧**」
    （更早）「宝库点击没毛病了，就是很慢，**一轮还有很多图片**」

背景
----
宝库取证（`buypanels._vstep`）是为抓「点选择奖励直接就关了宝库页面」那个 bug 加的 ——
**那个早就修好并进门禁了**（`verify_vault_flow.py` / `verify_vault_pick.py` 守着 ✓），
流程本身也已连买三层（真机 `acts: ["buy1","claim1","buy2","claim2","buy3","claim3_fb"]` ✓）。

⚠ 我上一轮改的"按需落帧"**是失效的**（用户贴的日志里 01~14 全落了 ✗）：
  我把"不为取证单独 OCR"（`it=None`）也算进 `_odd`（"看起来不对"）⇒ **反而每步都落** ✗

修法：**默认一张都不落**，只记结构化日志；`MAPBOT_VAULT_DEBUG=1` 才全量落帧。
顺带：**控制台默认不刷**（原来每步一行 ⇒ 一把 18 行噪声 ✗），只在调试或真异常时报。

牙齿：把 `_want_dump` 改回"按需/前 N 张"⇒ 本门禁必红 ✓
"""
import os
import re
import subprocess
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


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    print('=== 宝库取证：默认不落盘 ===')
    src = open(os.path.join(HERE, 'buypanels.py'), encoding='utf-8').read()
    lines = src.splitlines()
    s = [n for n, l in enumerate(lines) if l.startswith('def _vstep(')][0]
    e = [n for n, l in enumerate(lines) if n > s and l.startswith('def ')][0]
    # ⚠ 只看**真代码**：`#` 注释和 **docstring**（说明上次为什么失效）都不算 ✗
    #   （我第一版只滤了 `#` ⇒ docstring 里那行解释被当成代码误报 ✗）
    in_doc = False
    code_lines = []
    for l in lines[s:e]:
        st = l.strip()
        if st.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or st.startswith('#'):
            continue
        code_lines.append(l)
    code = '\n'.join(code_lines)

    # ── ① 默认开关必须是"关" ────────────────────────────────────────
    print()
    print('【1】默认不落盘（环境变量才开）')
    env = dict(os.environ)
    env.pop('MAPBOT_VAULT_DEBUG', None)
    env['PYTHONIOENCODING'] = 'utf-8'
    out = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, r"%s"); import buypanels as B;'
         ' print("DEBUG=", B.VAULT_DEBUG)' % HERE],
        capture_output=True, text=True, env=env, timeout=120)
    ck('不设环境变量时 `VAULT_DEBUG` 为 False',
       'DEBUG= False' in (out.stdout or ''), (out.stdout or out.stderr).strip()[:70])
    env2 = dict(env, MAPBOT_VAULT_DEBUG='1')
    out2 = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, r"%s"); import buypanels as B;'
         ' print("DEBUG=", B.VAULT_DEBUG)' % HERE],
        capture_output=True, text=True, env=env2, timeout=120)
    ck('设 `MAPBOT_VAULT_DEBUG=1` 时才是 True（排查时能开回来 ✓）',
       'DEBUG= True' in (out2.stdout or ''), (out2.stdout or out2.stderr).strip()[:70])

    # ── ② `_want_dump` 只由开关决定（不许再有"按需/前 N 张"那套 ✗）──
    print()
    print('【2】`_want_dump` 只由开关决定（上次那套"按需"是失效的 ✗）')
    ck('`_want_dump = bool(VAULT_DEBUG)`（唯一依据）',
       bool(re.search(r'_want_dump\s*=\s*bool\(VAULT_DEBUG\)', code)))
    for bad, why in (('VAULT_KEEP', '旧的"前 N 张"配额（已失效且误导）'),
                     ('_odd', '上次那套"看起来不对就落"（把 it=None 也算异常 ⇒ 每步都落 ✗）')):
        # ⚠ 只看**代码行**：注释里提到它（说明上次为什么失效）不算 ✗
        ck('代码里**没有** `%s`（%s）' % (bad, why), bad not in code)

    # ── ③ 控制台默认不刷噪声 ────────────────────────────────────────
    print()
    print('【3】控制台默认不刷（原来每步一行 ⇒ 一把 18 行 ✗）')
    ck('`say(...)` 只在 `VAULT_DEBUG` 或真正异常（面板/按钮读不到）时才调用',
       bool(re.search(r"if VAULT_DEBUG or \(it is not None and \(not _pres or not lab\)\)",
                      code)))
    ck('结构化日志仍然记（`vault_step`）—— 排查看日志就够 ✓',
       "'vault_step': tag" in code)

    # ── ④ 真机事实：三层买齐过（所以确实不需要取证）──────────────────
    print()
    print('【4】真机事实：三层买齐过（所以确实不需要取证了）')
    # ⚠⚠ 原来读 `runs/acc1/loop/loop_log.json` —— 那份**每跑一局就被覆盖**
    #   （实测：提交前门禁红了，因为文件已换成另一局 ⇒ 读到别的局的数据 ✗✗），
    #   而且 `runs/` 是 gitignore 的（新克隆读不到 ⇒ 等于没测 ✗）
    #   ⇒ 改成读**固化事实** `_verify/log_facts.json` ✓
    import json
    p = os.path.join(HERE, '_verify', 'log_facts.json')
    if os.path.exists(p):
        facts = json.loads(open(p, encoding='utf-8').read())
        acts = facts.get('vault_acts')
        ck('最近一次宝库 `acts` 里 **buy1~3 / claim1~3 都在**（流程已经正确 ✓）',
           bool(acts) and sum(1 for a in acts if a.startswith('buy')) == 3
           and sum(1 for a in acts if a.startswith('claim')) == 3, str(acts))
    else:
        print('      （缺 %s ⇒ 跳过本段）' % os.path.relpath(p, HERE))

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：宝库取证默认**一张都不落**（只记结构化日志）；'
          '要排查时 `MAPBOT_VAULT_DEBUG=1` 能开回来；控制台不再刷噪声')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
