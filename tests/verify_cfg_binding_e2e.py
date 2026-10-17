# -*- coding: utf-8 -*-
"""★ 端到端：**GUI 起子进程 ⇒ 子进程真的读本设备那份配置**（最关键的验证 ✓）

思路：不真起子进程（要连模拟器），而是
  ① 用 `LoopRunner.build_env(targets_cfg_path=…)` 拼出 env
  ② 用**同一个 env** 起一个**极短的 python**，让它 import `targets_cfg` 并打印
     "它认为的配置路径 + 某个键的值"
  ⇒ 若子进程读到的路径 == 我们给的路径、且值 == 我们设的值 ⇒ 绑定成立 ✓
"""
import io
import json
import os
import shutil
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
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import bot_gui_ui.services as S


PY = sys.executable
OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('端到端：子进程读到的就是"本设备那份"配置（2026-10-13）')
print('=' * 94)

tmp = tempfile.mkdtemp(prefix='mgas_e2e_')
try:
    # ── ① 造两个"设备"的配置，值刻意不同 ──
    _a = S.Prefs(ROOT, tmp, device='127.0.0.1:16448', root=tmp)
    _b = S.Prefs(ROOT, tmp, device='127.0.0.1:16384', root=tmp)
    _a.save_special('旅行商人', True)
    _b.save_special('旅行商人', False)
    print('  A(16448) 旅行商人 = True')
    print('  B(16384) 旅行商人 = False')

    # ── ② 用生产代码拼 env（这是 GUI 起进程时真正走的那条 ✓）──
    _r = S.LoopRunner(PY, ROOT, tmp, tag='')
    env_a = _r.build_env(targets_cfg_path=_a.targets_path())
    env_b = _r.build_env(targets_cfg_path=_b.targets_path())
    print('  env[A] MAPBOT_TARGETS_CFG = %s' % env_a.get('MAPBOT_TARGETS_CFG'))
    print('  env[B] MAPBOT_TARGETS_CFG = %s' % env_b.get('MAPBOT_TARGETS_CFG'))
    ck('① env 里带上了本设备路径 ✓',
       env_a.get('MAPBOT_TARGETS_CFG') == _a.targets_path()
       and env_b.get('MAPBOT_TARGETS_CFG') == _b.targets_path())

    # ── ③ 起真子进程，让它照 `explore_loop` 那样读 ──
    #   ⚠ 子进程脚本落在 tmp/，它自己的 __file__ 不是仓根 ⇒ 必须**显式**把 ROOT
    #     传进去（本文件迁到 tests/ 后，`dirname(__file__)` 不再等于仓根）
    _SNIP = (
        'import sys, os\n'
        'sys.path.insert(0, %r)\n'
        'import targets_cfg as TC\n'
        '_p = (os.environ.get("MAPBOT_TARGETS_CFG") or "").strip()\n'
        'if _p:\n'
        '    TC.load(path=_p)\n'
        'print("PATH=" + str(TC._CACHE.get("path")))\n'
        'print("VAL=" + str(TC.enabled("旅行商人")))\n'
    ) % ROOT
    _sp = os.path.join(tmp, '_probe.py')
    io.open(_sp, 'w', encoding='utf-8').write(_SNIP)

    def _run(env):
        p = subprocess.run([PY, _sp], capture_output=True, text=True,
                           env=env, timeout=90, cwd=ROOT)
        return (p.stdout or '') + (p.stderr or '')

    _oa = _run(env_a)
    _ob = _run(env_b)
    print()
    print('  ── A 子进程输出 ──')
    for l in _oa.strip().splitlines()[-3:]:
        print('     %s' % l[:100])
    print('  ── B 子进程输出 ──')
    for l in _ob.strip().splitlines()[-3:]:
        print('     %s' % l[:100])

    def _val(out, key):
        for l in out.splitlines():
            if l.startswith(key + '='):
                return l.split('=', 1)[1].strip()
        return None

    ck('② ⭐⭐ A 子进程读的**就是 A 的路径**',
       _val(_oa, 'PATH') == _a.targets_path(), str(_val(_oa, 'PATH')))
    ck('③ ⭐⭐ B 子进程读的**就是 B 的路径**',
       _val(_ob, 'PATH') == _b.targets_path(), str(_val(_ob, 'PATH')))
    ck('④ ⭐⭐⭐ A 子进程读到 `旅行商人=True`（与 A 窗口一致 ✓）',
       _val(_oa, 'VAL') == 'True', str(_val(_oa, 'VAL')))
    ck('⑤ ⭐⭐⭐ B 子进程读到 `旅行商人=False`（与 B 窗口一致 ✓）',
       _val(_ob, 'VAL') == 'False', str(_val(_ob, 'VAL')))

    # ── ④ 反向：**不传** ⇒ 回落全局（老行为，不许崩 ✓）──
    env_c = _r.build_env()          # 不传 targets_cfg_path
    print()
    print('  不传时 MAPBOT_TARGETS_CFG = %r' % env_c.get('MAPBOT_TARGETS_CFG'))
    ck('⑥ ⚠ 不传 ⇒ **不设该变量**（子进程回落全局 ✓，不许崩 ✗）',
       not env_c.get('MAPBOT_TARGETS_CFG'))
    _oc = _run(env_c)
    ck('⑦ ⚠ 不传也能正常跑（读全局那份 ✓）',
       'PATH=' in _oc, _oc.strip().splitlines()[-1][:80] if _oc.strip() else '(空)')
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
