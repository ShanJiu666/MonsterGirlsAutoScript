# -*- coding: utf-8 -*-
"""paths.py · ⭐ 路径解析：把「本机绝对路径」全换成「仓内相对 + 自动探测」（2026-10-02）

为什么有这个
------------
本项目要**发给朋友用**。原先所有路径都写死成本机布局：

    mapbot.py   ROOT = ''   ← 原项目目录
    mapbot.py   ADB  = (os.environ.get('MAPBOT_ADB') or 'adb')
    bot_gui.py  MAA_PY = ''

朋友机器上**这三条一条都不成立** ⇒ 一 clone 就连 `runs/` 都建不出来。
本模块把这类解析集中到一处，规则只有两条：

    ① **仓内的**（源码/模板/运行产物）一律用 `HERE` 相对 —— 换目录、换盘符都成立。
    ② **仓外的**（adb / MuMu / 数据表）一律**探测**，探测不到就**明确报错**，
       不用"猜一个默认路径然后静默失败"。

⚠ 环境变量优先：`MAPBOT_ADB` / `MAPBOT_MUMU_HOME` / `MAPBOT_DATATABLE` 可手动指定，
  探测不到时先用它们（装在奇怪位置的人有救了）。

⚠ **刻意不动 adb server 端口**：PC 端跑在 `ANDROID_ADB_SERVER_PORT=5038`
  （MuMu 自带 adb 占着 5037），这是 `mapbot.py` 里 import 期设的、已实测的正确行为。
  路径去硬编码 ≠ 改拓扑，两者别混。
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ⚠ 从 GUI(pythonw，无控制台) 里调 exe 会**每次弹一个黑窗口** —— 必须带这个标志
CNW = 0x08000000 if os.name == 'nt' else 0


# ══════════════════════════════════════════════════════════════════════
# ① 仓内路径（换机 clone 后恒成立）
# ══════════════════════════════════════════════════════════════════════
# ⭐ 2026-10-02：原 `ROOT` 指向**原项目目录** `<原项目目录>`。
#   已实证 `templates/` 两边**逐个文件大小完全一致**（11177 个 / 24042578 字节），
#   所以改成仓内相对是安全的，不会静默换成残缺模板。
ROOT = HERE
RUNS = os.path.join(HERE, 'runs')
TPL = os.path.join(HERE, 'templates')

# ⭐ 朋友机器上 clone 完 `runs/` 不存在 ⇒ 首次运行必须能自建，否则 os.makedirs 才不炸
for _d in (RUNS,):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:          # 只读介质/权限 ⇒ 延后到真正要写时再报错
        pass


# ══════════════════════════════════════════════════════════════════════
# ② 仓外路径（探测 + 找不到就明确报错）
# ══════════════════════════════════════════════════════════════════════
def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def find_adb():
    """找 adb.exe -> str | None

    探测顺序（**从最"专用"到最"通用"**，通用环境变量放最后 —— 防止拿到
    一个版本不对的 MuMu 内置 adb 反而连不上）：
        ① `MAPBOT_ADB` 环境变量（用户显式指定，最高优先）
        ② Android SDK 标准位置（`ANDROID_SDK_ROOT` / `ANDROID_HOME` / `LOCALAPPDATA`）
        ③ MuMu 安装目录里的 `shell/adb.exe`
        ④ `MuMuManager.exe` 所在目录反推（MuMu 装在非标准盘符时靠这条）
        ⑤ `PATH` 里的 adb
    """
    env = os.environ.get('MAPBOT_ADB')
    if env and os.path.exists(env):
        return env

    sdk_roots = [
        os.environ.get('ANDROID_SDK_ROOT'),
        os.environ.get('ANDROID_HOME'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk'),
    ]
    for r in sdk_roots:
        if r:
            p = os.path.join(r, 'platform-tools', 'adb.exe')
            if os.path.exists(p):
                return p

    for home in _mumu_homes():
        p = os.path.join(home, 'shell', 'adb.exe')
        if os.path.exists(p):
            return p

    # ⑤ PATH（shutil.which 在部分 pythonw 环境不稳 ⇒ 自己扫）
    for d in (os.environ.get('PATH') or '').split(os.pathsep):
        if not d:
            continue
        p = os.path.join(d.strip('"'), 'adb.exe')
        if os.path.exists(p):
            return p
    return None


def _mumu_homes():
    """MuMu 安装根目录候选 -> [str]（存在的）"""
    out = []
    env = os.environ.get('MAPBOT_MUMU_HOME')
    if env:
        out.append(env)
    # 从跑着的 MuMu 进程反推（最稳，能认出不标准盘符）
    try:
        ps = ('Get-CimInstance Win32_Process -Filter "Name=\'MuMuNxDevice.exe\'" '
              '-ErrorAction SilentlyContinue | Select-Object -ExpandProperty ExecutablePath')
        r = subprocess.run(['powershell', '-NoLogo', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True, errors='replace',
                           timeout=20, creationflags=CNW)
        for line in (r.stdout or '').splitlines():
            p = line.strip()
            if not p:
                continue
            # ...\<安装根>\nx_device\<版本>\shell\MuMuNxDevice.exe
            parts = p.split(os.sep)
            for i, seg in enumerate(parts):
                if seg.lower() == 'nx_device':
                    out.append(os.sep.join(parts[:i]))
                    break
    except Exception:       # noqa: BLE001
        pass
    out += [r + r'\MuMu Player 12' for r in ('C:', 'D:', 'E:', 'F:')]
    out += [os.path.join(r, 'Program Files', 'Netease', 'MuMuPlayer-12.0')
            for r in ('C:', os.environ.get('LOCALAPPDATA', '')) if r]
    seen, uniq = set(), []
    for h in out:
        if h and h not in seen and os.path.isdir(h):
            seen.add(h)
            uniq.append(h)
    return uniq


def find_mumu_manager():
    """MuMuManager.exe -> str | None（`info -v all` 是实例枚举的权威来源）"""
    env = os.environ.get('MAPBOT_MUMU_MANAGER')
    if env and os.path.exists(env):
        return env
    for home in _mumu_homes():
        p = os.path.join(home, 'nx_main', 'MuMuManager.exe')
        if os.path.exists(p):
            return p
    for pat in (r'?:\MuMu Player 12\nx_main\MuMuManager.exe',
                r'?:\*MuMu*\nx_main\MuMuManager.exe'):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


def find_datatable():
    """游戏数据表 server_datatable.json -> str | None

    ⚠ 它**不在本仓**（4MB，随游戏包/工具产出，gitignore 已排除）。
      只在**离线工具**（`spots.py` 生成图表等）用得到，**主循环 explore_loop 不读** ⇒
      找不到时降级成 None，由调用方决定跳过还是报错。
    """
    env = os.environ.get('MAPBOT_DATATABLE')
    if env and os.path.exists(env):
        return env
    for p in (os.path.join(HERE, 'server_datatable.json'),
              os.path.join(HERE, 'data', 'server_datatable.json'),
              os.path.join(HERE, '..', 'data', 'server_datatable.json')):
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


# ══════════════════════════════════════════════════════════════════════
# ③ 便捷常量（import 时探测成**普通 str**）
# ══════════════════════════════════════════════════════════════════════
# ⚠ 2026-10-02 改法记录（试过更"聪明"的做法，踩了坑，别再改回去）：
#   本来想让 adb 走**惰性**代理（import 时不探测，真用时才付 PowerShell 探测代价），
#   于是写了个 `str` 子类重载 `__str__` / `__fspath__` / `__bool__`。
#   ❌ **实测不成立**：
#       os.path.exists(ADB)   -> False          （hasattr 分支根本不走 __fspath__）
#       subprocess.run([ADB]) -> FileNotFoundError（Win32 直接吃底层缓冲，不调 __str__）
#   ⇒ 惰性代理在"假装自己是 str"这件事上骗不过 OS 那一层。
#   现在改成**import 时就探测成普通 str**：代价是无 MuMu 进程时 <10ms、
#   有 MuMu 进程时一次 Get-CimInstance ~0.6s，换来"到处都能直接用、不会静默走空" ✓
ADB = (find_adb() or 'adb')            # 探测不到退回裸 'adb'（依赖 PATH），不抛异常
MUMU_MANAGER = (find_mumu_manager() or '')


# ── 极速截图 sidecar 的 python（MaaFw 独立 venv）──────────────────────
# ⛔⛔ 2026-10-02 修「PC 端没装 MAA 快速截图」（用户问 + 实测确认）：
#   `bot_gui.ensure_sidecar()` 一直**静默退回 adb**（0.33s/张），
#   而 MAA 通道是 **0.013s/张（快 25 倍）** —— 用户全程没察觉，因为
#   `ensure_sidecar` 找不到 venv 只打一行「⚠ 没找到 MAA 环境」**不报错**。
#   根因：`MAA_PY` 写死 `<原项目目录>\_tmpman\maa_venv\...`（**原项目目录**），
#   2026-10-02 搬成两个仓之后那个目录对**新仓根本不存在** ⇒ 永远走 adb 兜底 ✗
#
#   ⇒ 现在：① 仓内 `_maa_venv`（**已随本机建好**：`python -m venv _maa_venv`
#            + `pip install MaaFw==5.14.0`，与旧 venv 版本逐条一致）
#        ② 环境变量 `MAPBOT_MAA_PY`（装在别处的人有救）
#        ③ 老位置（万一还有旧目录）
#     ⚠ venv **不能直接拷**（`pyvenv.cfg` 写死了创建路径）⇒ 要搬必须**重建**
#       （本机已于 2026-10-02 在仓内重建，MaaFw 5.14.0 / numpy 2.4.6，与旧的一致 ✓）
def find_maa_py():
    """sidecar 该用哪个 python（找不到返回 ''，调用方据此降级 adb ✓）

    探测顺序：
      ① 环境变量 `MAPBOT_MAA_PY`（用户显式指定，最高优先）
      ② **当前解释器自己** —— 发布包的做法：MAA 依赖已并进
         `python311/Lib/site-packages`，不需要独立 venv，同一个 python 起 sidecar 即可。
         ⚠ 判据是「真的能 import maa」而不是「目录存在」：
           裸解释器没有 maa 时必须继续往下找，否则会起一个必然失败的 sidecar ✗
      ③ 仓内 `_maa_venv`（本机开发时的老布局）
      ④ 老位置 `_tmpman/maa_venv`
    """
    import os
    env = os.environ.get('MAPBOT_MAA_PY')
    if env and os.path.exists(env):
        return env

    # ② 当前解释器能 import maa ⇒ 直接用它（发布包走这条）
    try:
        import importlib.util
        if importlib.util.find_spec('maa') is not None:
            return sys.executable
    except Exception:                   # noqa: BLE001
        pass

    # ③④ 老布局
    for c in (os.path.join(HERE, '_maa_venv', 'Scripts', 'python.exe'),
              os.path.join(HERE, '_tmpman', 'maa_venv', 'Scripts', 'python.exe')):
        if os.path.exists(c):
            return c
    return ''


MAA_PY = find_maa_py()


def adb_path():
    """'拿 adb 绝对路径'的正规入口（探测不到时返回 'adb'）"""
    return ADB


# ══════════════════════════════════════════════════════════════════════
# ④ 环境体检（GUI「环境检查」按钮 & 门禁用）
# ══════════════════════════════════════════════════════════════════════
def count_files(d, limit=None):
    """递归数文件（体检显示用；limit 给了就数到够为止，避免体检跑成几秒）"""
    n = 0
    for _root, _dirs, files in os.walk(d):
        n += len(files)
        if limit and n >= limit:
            break
    return n


def diagnose():
    """-> [{'key','label','ok','detail'}]：给 GUI 显示 / 门禁断言用"""
    adb = find_adb()
    mgr = find_mumu_manager()
    dt = find_datatable()
    n_tpl = count_files(TPL, limit=20000) if os.path.isdir(TPL) else 0
    return [
        {'key': 'root', 'label': '程序目录', 'ok': True, 'detail': HERE},
        {'key': 'templates', 'label': '模板资源', 'ok': n_tpl > 1000,
         'detail': ('%s（%d 个文件）' % (TPL, n_tpl)) if n_tpl
                   else '没找到模板 —— 确认 templates/ 已完整 clone'},
        {'key': 'adb', 'label': 'adb 可执行文件', 'ok': bool(adb),
         'detail': adb or '没找到。装 Android SDK，或设环境变量 MAPBOT_ADB 指向 adb.exe'},
        {'key': 'mumu', 'label': 'MuMu 多开器', 'ok': bool(mgr),
         'detail': mgr or '没找到 MuMuManager.exe（多开选设备要用；单开不影响）'},
        {'key': 'datatable', 'label': '游戏数据表（可选）', 'ok': bool(dt),
         'detail': dt or '没有（只有离线制表工具用得到，跑图不需要）'},
    ]


if __name__ == '__main__':
    import sys
    if sys.stdout is not None:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                       errors='replace')
    print('=' * 68)
    print('paths.py · 环境体检')
    print('=' * 68)
    _bad = 0
    for d in diagnose():
        print('  %s %-22s %s' % ('[ok]  ' if d['ok'] else '[FAIL]', d['label'], d['detail']))
        if not d['ok'] and d['key'] in ('adb', 'templates'):
            _bad += 1
    raise SystemExit(1 if _bad else 0)
