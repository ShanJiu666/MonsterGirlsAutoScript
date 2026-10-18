# -*- coding: utf-8 -*-
"""hotupdate.py · PC 端（桌面端）逻辑热更新 —— 与手机端 v1.41 同源，但落地方式不同

用户口径（2026-10-03）：「桌面端的如何搞热更新？」

为什么 PC 端只需要一层
----------------------
手机端要两层（逻辑补丁 + APK 自更新），因为壳是 Java、要过系统安装器。
PC 端**没有壳**：业务代码全在 `mapbot_pc/*.py`，`venv` / 依赖变了才需要重下整包（极罕见）
⇒ 日常迭代一个补丁就够（138 个 .py 共 1.85MB，补丁压完 <1MB）。

⭐⭐⭐ 为什么**不是**手机端那种 overlay（`sys.path` 插补丁目录）—— 2026-10-03 踩到的硬约束
------------------------------------------------------------------------------------
PC 端几乎每个业务模块**在 import 期**都会执行 `sys.path.insert(0, 自己所在目录)`
（`explore_loop.py:18` / `mapbot.py:25` / `marks.py:21` / `buypanels.py:43` … 共 40+ 处）。
⇒ 只要**任何一个内置模块**先被 import，它就把 `mapbot_pc` 重新顶到 `sys.path[0]`，
  把补丁目录压下去 ⇒ **补丁随机失效，失效与否取决于 import 顺序** ✗✗
（这不是"配错了"，是那 40 处 `sys.path.insert` 的必然结果；挨个改成 append 又要动 40 个文件，
 改漏一个就留一个随机 bug —— 不划算。）

⇒ 本模块用**原地覆盖 + 出厂版备份**：
    ① 下载到 `hot/pending/`（zip 解开，**先做语法检查，坏包装不上去**）
    ② 把将被覆盖的原文件**首次**备份进 `hot/orig/`（出厂版，永远保留第一份）
    ③ 原子替换 `mapbot_pc/` 里的对应文件（os.replace，同目录 ⇒ 原子）
    ④ **另起子进程**真 import 一遍核心模块 ⇒ 通过才起界面；失败立刻从 `hot/orig/` 恢复
    ⑤ 界面真起来后由 `bot_gui.py` 调 `confirm_alive()` 才算"已确认"
    ⑥ 覆盖后**连续 2 次**都没跑到确认点（起不来 / 被秒关）⇒ 下次启动恢复出厂版并拉黑该 id

⭐ 引导层（`bootstrap.py` / `hotupdate.py`）**绝不进补丁、绝不被覆盖**（见 `BOOT_LAYER`）：
  它们是"更新器自己"，改它们必须走整包 —— 否则一个坏补丁能把回滚能力一起弄没。

命令
----
    python hotupdate.py status     # 现在什么状态（补丁 id / 待激活 / 上次回滚）
    python hotupdate.py check      # 只查线上有没有新版
    python hotupdate.py hot        # 下载补丁（**下次启动生效**）
    python hotupdate.py apply      # 手动激活 pending（正常由 bootstrap 在启动期做）
    python hotupdate.py confirm    # 手动确认（界面起来后由 bot_gui 自动调）
    python hotupdate.py rollback   # 手动回滚到出厂版
    python hotupdate.py selftest   # 只跑运行时自检

更新源：**由使用者自己配置**（默认不连任何第三方地址）
    设 `MGAS_PC_UPDATE_BASE`（如 `https://github.com/<你>/<你的仓>`），或分别设
    `MGAS_PC_UPDATE_OWNER` / `MGAS_PC_UPDATE_REPO` / `MGAS_PC_MANIFEST_RAW` /
    `MGAS_PC_MANIFEST_API` 覆盖；未配置时 `hot` 子命令会**明确报错**，不会静默失败。
    约定布局：
    manifest.json               ← 清单
    pc/hot-pc-<ver>-<sha8>.zip  ← 逻辑补丁（文件名带内容 sha ⇒ 天然免疫缓存）
"""
import base64
import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

try:                                    # GBK 控制台打中文/✓ 会炸
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001  （pythonw 下 stdout 可能是 None）
    pass

HERE = os.path.dirname(os.path.abspath(__file__))       # core/（本文件所在目录 = 代码目录）

# ⭐⭐⭐⭐ 2026-10-06 用户报「启动时会闪过两次命令窗口」—— 本模块也在启动链上
#   引导层由 `启动.bat` 的 `start "" pythonw.exe bootstrap.py` 拉起 ⇒ **完全没有控制台**
#   （GUI 子系统：`GetConsoleWindow()==0`，不是"隐藏的控制台"）
#   ⇒ `_run_code()` 起 `python -c …` 做语法检查/import 自检时（**包内 python.exe 是
#     控制台程序**），Windows 必须新建控制台 ⇒ **默认可见** ⇒ 闪一下 ✗✗
#   实测（`_tmpman/exp_conhost3.py`）：无控制台父进程调控制台子程序
#     不带标志 ⇒ 新增 2 个可见控制台窗口；带本标志 ⇒ 0 个 ✓
#   ⚠ 引导层**不进补丁** ⇒ 本文件这一处**不会**随热更生效，要**重发整包**才修得掉 ✓
CNW = 0x08000000 if os.name == 'nt' else 0

# ⚠ 更新源：**默认内置**（别人的发布包要能直接检查更新 ✓）
#   ⭐ 2026-10-18 用户口径：「**要求别人能通过热更获得最新版**」
#      ---- 之前为什么是空的 ----
#        我为了让"个人仓址不出现在公开代码里"清空了 OWNER/REPO
#        ⇒ `configured()` 恒 False ⇒ **端上根本不去检查更新** ⇒ 热更等于没有 ✗✗
#      ---- 权衡 ----
#        这个仓（`MGAS-pc-update`）本来就是**公开**热更源，地址不是秘密；
#        而"功能可用"远比"藏一个已经公开的地址"重要 ⇒ 内置 ✓
#      ⚠ 仍**全部可用环境变量覆盖**（自建镜像 / 本地 http 测试都用得上 ✓）
#      ⚠ 本文件是**引导层**（`BOOT_LAYER`）⇒ 改动**不进补丁**，必须重发整包才生效 ✓
_OWNER_DEFAULT = 'geng-haojie'
_REPO_DEFAULT = 'MGAS-pc-update'
#: 更新源的站点根（Gitee 用 `/raw/master/...`；GitHub 用 `raw/...`）
_BASE_DEFAULT = 'https://gitee.com/%s/%s' % (_OWNER_DEFAULT, _REPO_DEFAULT)

OWNER = os.environ.get('MGAS_PC_UPDATE_OWNER') or _OWNER_DEFAULT
REPO = os.environ.get('MGAS_PC_UPDATE_REPO') or _REPO_DEFAULT
_BASE = (os.environ.get('MGAS_PC_UPDATE_BASE')
         or ('https://gitee.com/%s/%s' % (OWNER, REPO) if OWNER and REPO
             else '')).rstrip('/')
# ⚠ 三个都可用环境变量覆盖 —— **门禁 verify_hotupdate.py 就是靠它们把地址指到本地 http**
#   ⚠ 没配 _BASE 时**不能**拼出 '/raw/master/manifest.json' 这种半截 URL
#     （非空 ⇒ 后面的「未配置就跳过」判断会失效，实测踩过）
MANIFEST_RAW = (os.environ.get('MGAS_PC_MANIFEST_RAW')
                or (_BASE + '/raw/master/manifest.json' if _BASE else ''))
# ⚠ API 地址只在 **GitHub** 有 `releases/latest/download/` 那种形态；
#   Gitee 的公开仓没有等价物 ⇒ 走 raw 就够（`MANIFEST_RAW` 那条 ✓）
MANIFEST_API = (os.environ.get('MGAS_PC_MANIFEST_API')
                or (_BASE + '/releases/latest/download/manifest.json'
                    if _BASE else ''))


def configured():
    """更新源是否已配置（发布包默认**没有** ⇒ 所有更新动作静默跳过）"""
    return bool(_BASE or MANIFEST_RAW or MANIFEST_API)

UA = 'MGAS-PC-Updater/1'
CONNECT_TIMEOUT = 15
MAX_HOT_BYTES = 32 * 1024 * 1024        # 补丁上限（正常 <1MB，超了说明发错包了）
MAX_FILES = 4000                        # 补丁条目上限（防"发错成整包"）

# 引导层：**绝不进补丁、绝不被覆盖**（release_pc.py 拒收，门禁有专门一项守它）
BOOT_LAYER = ('bootstrap.py', 'hotupdate.py')

# 运行时自检要真 import 的模块（2026-10-03 本机实测：无模拟器/无游戏时全部 OK，合计 ~2.5s）
# ⚠ 挑的都是**纯逻辑**模块：不连 adb、不弹窗、不写 runs/
SELFTEST_MODULES = ('numpy', 'cv2', 'layout', 'fixed', 'marks', 'grid_detect',
                    'targets_cfg', 'badge', 'spots', 'strategy', 'mapsolve',
                    'mapgen', 'mapsim', 'buypanels', 'mapbot', 'explore_loop')

SELFTEST_TIMEOUT = 300                  # 首次 import cv2/背包面板较慢（实测 ~2.5s），给足余量

# 子进程自检：`python -c` 的 sys.path[0] 是 cwd ⇒ 必须显式 insert 包目录，
#   不能用 PYTHONPATH（它排在 cwd 之后，会 import 到别处的东西 ⇒ 那种自检等于没检查）
SELFTEST_SRC = r'''
import importlib, os, sys
pkg, mods = sys.argv[1], sys.argv[2].split(',')
sys.path.insert(0, pkg)
for m in mods:
    try:
        importlib.import_module(m)
    except BaseException as e:                              # noqa: BLE001
        print('IMPORT_FAIL %s: %r' % (m, e))
        sys.exit(4)
print('OK')
'''

# 覆盖前的语法检查（在 pending 上做 ⇒ 坏包**一个字节都不落地**）
COMPILE_SRC = r'''
import glob, os, sys, tokenize
d = sys.argv[1]
bad = []
for f in sorted(glob.glob(os.path.join(d, '**', '*.py'), recursive=True)):
    try:
        with tokenize.open(f) as fh:
            src = fh.read()
        compile(src, f, 'exec')
    except Exception as e:                                  # noqa: BLE001
        bad.append('%s: %r' % (os.path.relpath(f, d), e))
if bad:
    print('COMPILE_FAIL ' + ' | '.join(bad[:4]))
    sys.exit(3)
print('OK')
'''


# ───────────────────────── 路径（**全部函数化**：门禁靠 MGAS_PC_PKG_DIR 指到临时副本）─────

def pkg_dir():
    """**代码目录**（= 装着 bot_gui.py / explore_loop.py 的那个目录）

    ⚠ 2026-10-17 目录整理后：代码在 `core/`，而 `templates/` `data/` 在**包根**
      ⇒ 补丁落地不能一律用本函数，见 `pkg_root()` / `_dst_of()`。
    """
    return os.path.abspath(os.environ.get('MGAS_PC_PKG_DIR') or HERE)


def pkg_root():
    """**包根**（= 代码目录的上一级；`templates/` `data/` `runs/` 都在这层）

    ⚠ 兼容旧布局：若 `pkg_dir()` 里就有 `templates/`（没分 core/ 的老包），
      则包根 == 代码目录。这样**老包照旧能热更** ✓
    """
    pkg = pkg_dir()
    # 老布局：templates/ 与代码同级 ⇒ 包根就是它
    if os.path.isdir(os.path.join(pkg, 'templates')):
        return pkg
    parent = os.path.dirname(pkg)
    if os.path.isdir(os.path.join(parent, 'templates')):
        return parent
    return pkg          # 都没有 ⇒ 退回代码目录（不会更差）


#: 补丁里「落在**代码目录**」的首段（其余一律落包根）
#:  ⚠ 只放**业务 .py 的名字**；别把 templates/data 写进来
_TOP_LEVEL_CODE = frozenset((
    'bootstrap.py', 'hotupdate.py',          # 引导层（其实会被 _pkg_rel_ok 拦掉）
))


def _dst_of(rel):
    """补丁条目 `rel`（包内相对路径）→ **磁盘绝对路径**（按首段选基准目录）

    规则：
      · `xxx.py`（根级 .py）            → `pkg_dir()/xxx.py`      （代码，在 core/）
      · `core/xxx.py`                   → `pkg_root()/core/xxx.py`（显式带 core/ 前缀）
      · `templates/…` `data/…` `docs/…` → `pkg_root()/…`           （资产，在包根）
      · 其它（`runs/` 等）              → `pkg_root()/…`
    """
    norm = _norm_rel(rel)
    parts = norm.split('/')
    head = parts[0]
    # 显式带 core/ 前缀 ⇒ 相对包根解析
    if head == 'core':
        return os.path.join(pkg_root(), *parts)
    # 根级 .py ⇒ 代码目录
    if len(parts) == 1 and head.endswith('.py'):
        return os.path.join(pkg_dir(), head)
    # 其余（templates/ data/ docs/ runs/ …）⇒ 包根
    return os.path.join(pkg_root(), *parts)


def hot_dir():
    return os.path.join(pkg_dir(), 'hot')


def pending_dir():
    return os.path.join(hot_dir(), 'pending')


def orig_dir():
    """**出厂版备份**（第一次被补丁覆盖前的原文件；永远保留最早那份）"""
    return os.path.join(hot_dir(), 'orig')


def bad_dir():
    return os.path.join(hot_dir(), 'bad')


def state_path():
    return os.path.join(hot_dir(), 'state.json')


def version_file():
    """`PC_VERSION` 的位置。

    ⚠ 2026-10-17 目录整理后：**代码在 `core/`**，但 `PC_VERSION` 留在**包根**
      （它描述"整个包"的版本，不是代码目录的）⇒ 先找包根、再退回代码目录。
      不改这里的话 `pack_version()` 会回落 `'0.0'`，状态栏显示「包 v0.0」✗
    """
    pkg = pkg_dir()
    root = os.path.dirname(pkg)              # core/ 的上一级 = 包根
    for d in (root, pkg):
        p = os.path.join(d, 'PC_VERSION')
        if os.path.isfile(p):
            return p
    return os.path.join(root, 'PC_VERSION')  # 都不在 ⇒ 返回包根那个（报错更准）


# ───────────────────────── 小工具 ─────────────────────────

def _out(s):
    """pythonw 下 sys.stdout 是 None，print 会炸 ⇒ 一律走这里"""
    try:
        print(s)
    except Exception:                       # noqa: BLE001
        pass


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _stamp():
    return time.strftime('%m%d_%H%M%S')


def _log_path():
    d = os.path.join(pkg_dir(), 'runs')
    try:
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'updater.log')
    except Exception:                       # noqa: BLE001  （只读介质 ⇒ 退回临时目录）
        return os.path.join(tempfile.gettempdir(), 'mgas_pc_updater.log')


def log(msg):
    """热更日志：既写 `runs/updater.log`，也打控制台（bootstrap 用 pythonw 时只有文件）"""
    line = '[%s] %s' % (_now(), msg)
    _out(line)
    p = _log_path()
    try:
        if os.path.isfile(p) and os.path.getsize(p) > 2 * 1024 * 1024:
            try:
                os.replace(p, p + '.1')     # 简单轮转，别把它养成巨无霸
            except Exception:               # noqa: BLE001
                pass
        with io.open(p, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:                       # noqa: BLE001
        pass


def read_json(path, default=None):
    try:
        with io.open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else (default if default is not None else {})
    except Exception:                       # noqa: BLE001
        return default if default is not None else {}


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2))
    os.replace(tmp, path)                   # 原子替换：断电也不会留半个 state.json


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ver_tuple(v):
    """'1.10' → (1, 10)；非数字段一律当 0（宁可判"不用更"也别崩）"""
    out = []
    for part in str(v or '0').split('.'):
        try:
            out.append(int(''.join(c for c in part if c.isdigit()) or 0))
        except Exception:                   # noqa: BLE001
            out.append(0)
    return tuple(out) or (0,)


def pack_version():
    """本机**整包**版本（= 朋友解压的那个 zip 的版本）。没有文件就 '0.0'"""
    try:
        with io.open(version_file(), encoding='utf-8') as f:
            return f.read().strip() or '0.0'
    except Exception:                       # noqa: BLE001
        return '0.0'


def _http(url, timeout=CONNECT_TIMEOUT, max_bytes=1 << 20):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = io.BytesIO()
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > max_bytes:
                raise RuntimeError('响应超过上限 %dB，已中止（%s）' % (max_bytes, url))
        return buf.getvalue()


def _rmtree(p):
    try:
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    except Exception:                       # noqa: BLE001
        pass


def _copy(src, dst):
    d = os.path.dirname(dst)
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copy2(src, dst)


def _norm_rel(rel):
    """统一成 `a/b/c` 形式（去掉开头的 `./`）"""
    norm = str(rel).replace('\\', '/')
    while norm.startswith('./'):
        norm = norm[2:]
    return norm


def _pkg_rel_ok(rel):
    """补丁条目是否允许落到包内：拒绝对路径、`..`、以及**引导层**（bootstrap/hotupdate）"""
    norm = _norm_rel(rel)
    if not norm or norm.startswith('/') or '..' in norm.split('/'):
        return False
    parts = norm.split('/')
    if len(parts) == 1 and parts[0] in BOOT_LAYER:
        return False                        # ⭐ 引导层绝不被补丁覆盖
    return True


# ───────────────────────── 状态机 ─────────────────────────

def load_state():
    return read_json(state_path())


def save_state(st):
    write_json(state_path(), st)


def boot_recover():
    """冷启动第一件事（**必须在 GUI 起来之前**）。

    覆盖式热更的"上次没起来"判据：state.applied 有值但 confirmed=false
    ⇒ 上次覆盖完**从没跑到确认点**（GUI 起不来 / 被秒关）。

    ⚠ 给**一次**机会（`bootAttempts`）：朋友"开起来又马上关掉"也会停在未确认态，
      直接判坏会把一个好补丁冤枉拉黑（拉黑后那个 id 永不重装 ✗）。
      连续 2 次都到不了确认点 ⇒ 才恢复出厂版 + 拉黑。
    """
    st = load_state()
    os.makedirs(hot_dir(), exist_ok=True)
    hid = st.get('applied') or ''
    if hid and not st.get('confirmed', False):
        n = int(st.get('bootAttempts') or 0) + 1
        st['bootAttempts'] = n
        if n < 2:
            save_state(st)
            log('⚠ 补丁 %s 上次没跑到确认点（第 %d 次）⇒ 再试一次；连续 2 次才判坏回滚' % (hid, n))
        else:
            cnt = restore_orig(st)
            st.pop('applied', None)
            st['confirmed'] = False
            st['rolledBack'] = hid
            save_state(st)
            _archive_bad(hid + '-boot', 'boot')
            log('⚠ 补丁 %s 连续 %d 次没能启动 ⇒ 已恢复出厂版（还原 %d 个文件）' % (hid, n, cnt))


def confirm_alive():
    """⭐ GUI **真的起来之后**由 `bot_gui.py` 调用（`root.after(3000, …)`）。

    ⚠ 为什么确认点放在这里、而不是 bootstrap 的自检通过后：
      import 自检抓不到"tkinter 窗口起不来 / 主循环里立刻抛"这类错
      ⇒ 只有真跑到窗口存活才算数（与手机端 `onPythonStarted` 同一思路）。
    """
    st = load_state()
    if not st.get('applied') or st.get('confirmed', False):
        return False
    st['confirmed'] = True
    st['confirmedAt'] = _now()
    st['bootAttempts'] = 0
    save_state(st)
    log('✓ 补丁 %s 已确认（界面已起来）：%s' % (st.get('applied'), st.get('selftest') or 'OK'))
    return True


def _archive_bad(name, kind=''):
    """把 pending（坏包）挪进 hot/bad/ 留证据（**不删** —— 反馈包要能取证）"""
    p = pending_dir()
    if os.path.isdir(p):
        dst = os.path.join(bad_dir(), '%s-%s' % (name, _stamp()))
        try:
            os.makedirs(bad_dir(), exist_ok=True)
            if os.path.exists(dst):
                _rmtree(dst)
            os.replace(p, dst)
            log('  · 坏包已留证：%s（%s）' % (dst, kind or '?'))
        except Exception:                   # noqa: BLE001
            _rmtree(p)


def restore_orig(st=None):
    """从 hot/orig/ 恢复出厂版。返回还原的文件数。

    - orig 里有 ⇒ 拷回去
    - orig 里没有（补丁**新增**的文件）⇒ 删掉它
    """
    st = load_state() if st is None else st
    meta = st.get('appliedMeta') or {}
    files = meta.get('files') or []
    n = 0
    root = orig_dir()
    pkg = pkg_dir()
    for rel in files:
        if not _pkg_rel_ok(rel):
            continue
        src = os.path.join(root, *rel.split('/'))
        dst = _dst_of(rel)     # ⚠ 按首段选基准（代码 core/ / 资产包根）
        try:
            if os.path.isfile(src):
                _copy(src, dst)
                n += 1
            elif os.path.isfile(dst):
                os.remove(dst)              # 补丁新增的文件 ⇒ 回滚 = 删掉
                n += 1
        except Exception as e:              # noqa: BLE001
            log('⚠ 还原 %s 失败：%r' % (rel, e))
    _drop_pyc(files)
    return n


def _drop_pyc(files):
    """覆盖/还原后删掉对应的 `__pycache__` 缓存（避免拿着旧 .pyc 跑 —— 双保险）"""
    cache = os.path.join(pkg_dir(), '__pycache__')
    if not os.path.isdir(cache):
        return
    for rel in files:
        parts = rel.split('/')
        if len(parts) != 1 or not parts[0].endswith('.py'):
            continue
        stem = parts[0][:-3]
        for p in glob.glob(os.path.join(cache, stem + '.*.pyc')):
            try:
                os.remove(p)
            except Exception:               # noqa: BLE001
                pass


def apply_pending():
    """激活 `hot/pending/` 里的补丁：语法检查 → 备份出厂版 → 原子覆盖 → 运行时自检。

    返回 (成功?, 给人看的一句话)。**任何一个环节失败都保证包目录回到出厂版。**
    """
    pend = pending_dir()
    meta = read_json(os.path.join(pend, 'meta.json'))
    if not meta:
        return False, '没有待激活的补丁'
    hid = meta.get('id') or '?'
    st = load_state()

    # ① 语法检查（**在覆盖之前** ⇒ 语法错的包一个字节都不落地）
    ok, detail = compile_check(pend)
    if not ok:
        log('⚠ 补丁 %s 语法检查失败 ⇒ 丢弃（未覆盖任何文件）：%s' % (hid, detail))
        _archive_bad(hid + '-compile', 'compile')
        st['rolledBack'] = hid
        save_state(st)
        return False, '语法检查失败：%s' % detail

    # ② 备份出厂版 + 原子覆盖
    try:
        files = _patch_files(pend)
        if not files:
            raise RuntimeError('补丁里一个文件都没有')
        _backup_orig(files)
        for rel in files:
            src = os.path.join(pend, *rel.split('/'))
            dst = _dst_of(rel)     # ⚠ 按首段选基准（同覆盖路径）
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + '.hotnew'
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)            # 同目录 rename ⇒ 原子（不会留半个文件）
        _drop_pyc(files)
    except Exception as e:                  # noqa: BLE001
        log('⚠ 覆盖补丁 %s 失败 ⇒ 立即恢复出厂版：%r' % (hid, e))
        n = restore_orig(st)
        _archive_bad(hid + '-apply', 'apply')
        st.pop('applied', None)
        st['rolledBack'] = hid
        save_state(st)
        return False, '覆盖失败（已还原 %d 个文件）：%r' % (n, e)

    st['applied'] = hid
    st['appliedMeta'] = {'files': files, 'at': _now(), 'notes': meta.get('notes') or ''}
    st['confirmed'] = False
    st['bootAttempts'] = 0
    save_state(st)
    log('补丁 %s 已覆盖（%d 个文件），开始运行时自检……' % (hid, len(files)))

    # ③ 运行时自检（另起子进程真 import 一遍：固定清单 ∪ **补丁自带的模块**）
    ok2, detail2 = selftest(_patch_modules(files))
    if ok2:
        # ⚠ **这里不写 confirmed** —— 交给 GUI 起来后调 confirm_alive()
        #   （import 自检抓不到 tkinter 层面的起不来）
        st['selftest'] = str(detail2)[:400]
        save_state(st)
        _rmtree(pend)
        log('✓ 补丁 %s 自检通过（等界面起来确认）：%s' % (hid, detail2))
        return True, '补丁 %s 已生效（%d 个文件）：%s' % (hid, len(files), detail2)

    log('⚠ 补丁 %s **自检失败** ⇒ 恢复出厂版：%s' % (hid, detail2))
    n = restore_orig(st)
    _archive_bad(hid + '-selftest', 'selftest')
    st.pop('applied', None)
    st['confirmed'] = False
    st['rolledBack'] = hid
    save_state(st)
    return False, '自检失败（已还原 %d 个文件）：%s' % (n, detail2)


def _patch_files(pend):
    """pending 里的补丁文件清单（相对路径，正斜杠；跳过 meta.json）"""
    out = []
    for base, _dirs, fs in os.walk(pend):
        for f in fs:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, pend).replace('\\', '/')
            if rel == 'meta.json':
                continue
            if _pkg_rel_ok(rel):
                out.append(rel)
            else:
                log('⚠ 跳过不允许的条目：%s（引导层/越界）' % rel)
    return sorted(out)


def _backup_orig(files):
    """把将被覆盖的**出厂版**存进 hot/orig/ —— ⚠ 已存在就不覆盖（永远保留最早那份）"""
    root = orig_dir()
    pkg = pkg_dir()
    for rel in files:
        src = _dst_of(rel)     # ⚠ 按首段选基准（代码 core/ / 资产包根）
        dst = os.path.join(root, *rel.split('/'))
        try:
            if os.path.isfile(src) and not os.path.isfile(dst):
                _copy(src, dst)
        except Exception as e:              # noqa: BLE001
            log('⚠ 备份 %s 失败（继续，但该文件将无法回滚）：%r' % (rel, e))


def rollback(reason='手动回滚'):
    """回滚到出厂版（并把当前补丁 id 拉黑）"""
    st = load_state()
    hid = st.get('applied') or 'unknown'
    n = restore_orig(st)
    st.pop('applied', None)
    st['confirmed'] = False
    st['rolledBack'] = hid
    save_state(st)
    log('⚠ 补丁 %s 已回滚到出厂版（%s，还原 %d 个文件）' % (hid, reason, n))
    return n


# ───────────────────────── 线上清单 ─────────────────────────

def fetch_manifest(timeout=CONNECT_TIMEOUT):
    """拉清单（**两条通道**：先 API，失败回落 raw ✓）

    ⚠ 2026-10-18 更新口径：更新源**已内置**（见本文件 `_OWNER_DEFAULT` 那段）
      —— 用户的发布包要能**直接**检查更新，不需要让使用者去配环境变量 ✓
      ---- 两条通道为什么要分 ----
        · `MANIFEST_API`：GitHub 的 `releases/latest/download/` 形态（带缓存语义）
          ⚠ Gitee 的公开仓**没有等价物** ⇒ 那条会 404 ⇒ **正常回落 raw** ✓
        · `MANIFEST_RAW`：`/raw/master/manifest.json`，Gitee 走这条
      ⇒ 所以「API 404」**不是错误**，是预期路径（日志会记一行，便于排查 ✓）
      ⚠ 仍然**全部可用环境变量覆盖**（自建镜像 / 本地 http 门禁测试 ✓）
    """
    if not (MANIFEST_API or MANIFEST_RAW):
        raise RuntimeError(
            '未配置更新源 ⇒ 不执行热更新。\n'
            '  设环境变量 `MGAS_PC_UPDATE_BASE`（例如 https://github.com/<你>/<你的仓>）\n'
            '  或 `MGAS_PC_MANIFEST_RAW` / `MGAS_PC_MANIFEST_API` 指向你自己的清单。')
    # ⚠ 2026-10-18 **顺序很重要**：Gitee 的公开仓没有 API 通道 ⇒ 先试它会白等一个
    #   `CONNECT_TIMEOUT`（15 秒）才回落 ⇒ 别人点「检查更新」先愣 15 秒 ✗
    #   ⇒ 判据：**显式配了 `MANIFEST_API` 环境变量**才先走 API（GitHub / 自建用）；
    #     否则**直接走 raw**（Gitee 默认这条路，零等待 ✓）
    if os.environ.get('MGAS_PC_MANIFEST_API'):
        try:
            o = json.loads(_http(MANIFEST_API, timeout=timeout,
                                 max_bytes=1 << 20).decode('utf-8'))
            b64 = (o.get('content') or '').replace('\n', '').replace('\r', '')
            if not b64:
                raise RuntimeError('contents 响应里没有 content')
            return json.loads(base64.b64decode(b64).decode('utf-8'))
        except Exception as e:              # noqa: BLE001
            log('  · API 通道读清单失败 ⇒ 回落 raw：%s' % e)
    return json.loads(_http(MANIFEST_RAW, timeout=timeout,
                            max_bytes=1 << 20).decode('utf-8'))


def hot_verdict(mf, st=None):
    """补丁可用性判据。返回 (给人看的一句话, 可安装的 entry|None)

    三种"不可用"每种都要能说清为什么 —— 否则线上没法排查（"更新完还是老样子"）。
    """
    st = load_state() if st is None else st
    hot = ((mf or {}).get('pc') or {}).get('hot')
    if not isinstance(hot, dict) or not hot.get('url'):
        return '无', None
    hid = hot.get('id') or '?'
    minpack = hot.get('minPack') or ''
    if minpack and ver_tuple(pack_version()) < ver_tuple(minpack):
        return ('需要先更新整包（补丁要求包 ≥ %s，本机 %s）' % (minpack, pack_version())), None
    if hid == st.get('applied'):
        return '已是最新', None
    if hid == st.get('rolledBack'):
        return '该补丁上次自检失败已拉黑（等下一个 id）', None
    return '可用', hot


def download_hot(entry):
    """下载补丁 → 校验 sha256 → 解到 pending（**下次启动由 apply_pending 激活**）"""
    hid = entry.get('id') or '?'
    url = entry['url']
    size = int(entry.get('size') or 0)
    sha = (entry.get('sha256') or '').lower()

    _rmtree(pending_dir())
    os.makedirs(pending_dir(), exist_ok=True)
    data = _http(url, timeout=60, max_bytes=MAX_HOT_BYTES)
    if size and len(data) != size:
        raise RuntimeError('补丁大小不符：下到 %d，清单写 %d' % (len(data), size))
    got = hashlib.sha256(data).hexdigest()
    if sha and got != sha:
        raise RuntimeError('补丁 sha256 不符（下到 %s…，清单写 %s…）' % (got[:12], sha[:12]))
    zp = os.path.join(hot_dir(), 'dl.zip')
    os.makedirs(hot_dir(), exist_ok=True)
    with open(zp, 'wb') as f:
        f.write(data)
    try:
        n = _unzip(zp, pending_dir())
    finally:
        try:
            os.remove(zp)
        except Exception:                   # noqa: BLE001
            pass
    if not n:
        raise RuntimeError('补丁里一个文件都没有（发错包了？）')
    write_json(os.path.join(pending_dir(), 'meta.json'), {
        'id': hid, 'sha256': sha, 'files': n, 'installedAt': _now(),
        'notes': entry.get('notes') or '', 'packVersion': pack_version(),
    })
    return '补丁 %s 已就绪（%d 个文件，%.2fMB）· 下次启动生效' % (hid, n, len(data) / 1048576.0)


def _unzip(zip_path, dst):
    """解压到 dst（返回文件数）。⚠ 防目录穿越 + 拒绝引导层（别把 bootstrap 换成补丁里的）"""
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if len(names) > MAX_FILES:
            raise RuntimeError('补丁里条目太多（%d）⇒ 发错包了？' % len(names))
        for name in names:
            norm = name.replace('\\', '/')
            if norm.endswith('/'):
                continue
            rel = _norm_rel(norm)
            if not _pkg_rel_ok(rel):
                log('⚠ 跳过不允许的条目：%s' % name)
                continue
            out = os.path.join(dst, *rel.split('/'))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(name) as src, open(out, 'wb') as f:
                shutil.copyfileobj(src, f, 1 << 16)
            n += 1
    return n


def auto_update(timeout=CONNECT_TIMEOUT):
    """启动期静默更新：有新版就**下载到 pending**（下次启动激活）。

    返回给人看的一句话；没什么可说 / 网络不通 ⇒ None（**绝不让没网的朋友起不来**）

    ⚠ 未配置更新源（本仓默认如此）⇒ **直接返回、连尝试都不做**。
      以前这里会去 fetch_manifest，而它抛「未配置更新源」
      ⇒ 每次启动都往日志里刷一条失败，网友看着像报错 ✗
    """
    # 没配更新源 ⇒ 静默跳过（不联网、不打日志）
    if not configured():
        return None
    st = load_state()
    try:
        mf = fetch_manifest(timeout=timeout)
    except Exception as e:                  # noqa: BLE001
        log('  · 拉清单失败（静默跳过更新）：%s' % e)
        return None
    verdict, entry = hot_verdict(mf, st)
    if not entry:
        log('  · 无需更新：%s' % verdict)
        return None
    try:
        msg = download_hot(entry)
    except Exception as e:                  # noqa: BLE001
        log('  · 下载补丁失败（静默跳过，继续用现行版）：%s' % e)
        return None
    st['lastCheck'] = _now()
    st['lastCheckVerdict'] = verdict
    save_state(st)
    log('  ✓ ' + msg)
    return msg


# ───────────────────────── 自检 ─────────────────────────

def _run_code(src, args, timeout):
    # ⚠ 必须继承 os.environ（含 `MGAS_PC_PKG_DIR`）：子进程要检查**同一个包目录**
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    exe = sys.executable or 'python'
    t0 = time.time()
    try:
        r = subprocess.run([exe, '-c', src] + list(args), cwd=pkg_dir(), env=env,
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout,
                           creationflags=CNW)      # ⭐ 别删：否则启动时闪黑窗（见顶部）
    except subprocess.TimeoutExpired:
        return False, '超时（>%ds）' % timeout, time.time() - t0
    except Exception as e:                  # noqa: BLE001
        return False, '起不来：%r' % e, time.time() - t0
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    # ⚠⚠⚠ 判定**只看 returncode**，绝不能用 `out.endswith('OK')` ——
    #   子进程启动时 `site.py` 可能往 **stderr** 打警告，那样"输出末尾不是 OK"就会把
    #   **语法检查/自检误判成失败** ✗✗
    #   真包实测（2026-10-03）：朋友版 venv 里残留 `distutils-precedence.pth`
    #   （`_distutils_hack` 被 build_pkg 砍掉了）⇒ 每起一次子进程就一行
    #   `ModuleNotFoundError: No module named '_distutils_hack'` 到 stderr
    #   ⇒ 好补丁被丢弃 + **拉黑**（朋友那边表现为"永远更不了"）✗✗
    #   ⇒ 成功/失败由 SELFTEST_SRC / COMPILE_SRC **自己 sys.exit(3/4)** 表达 ✓
    ok = (r.returncode == 0)
    return ok, 'exit=%s %s' % (r.returncode, out[-600:] or '(无输出)'), time.time() - t0


def _patch_modules(files):
    """补丁里的顶层 `.py` ⇒ 模块名。

    ⚠⚠ **自检必须连它们一起 import**，否则"补丁新增/修改的模块"根本没被检查到
       —— 2026-10-03 门禁 T7 就是这么抓出来的：只查固定清单时，补丁里塞一个
       import 期必抛异常的模块，自检**照样"通过"** ✗✗
    """
    out = []
    for rel in files:
        if '/' in rel or not rel.endswith('.py'):
            continue
        stem = rel[:-3]
        if stem.isidentifier() and stem not in out:
            out.append(stem)
    return out


def compile_check(directory):
    """语法检查目录下所有 .py（**覆盖之前**做 ⇒ 坏包零落地）"""
    ok, detail, dt = _run_code(COMPILE_SRC, [directory], 120)
    return ok, ('OK %.1fs' % dt) if ok else detail


def selftest(extra=()):
    """**另起子进程**真 import 一遍：固定清单 ∪ **补丁自带的模块**。

    覆盖之后做，失败就恢复出厂版。返回 (ok, detail)。
    任何异常都当失败（宁枉勿纵：宁可回滚也不能让朋友开不起来）。
    """
    mods = list(SELFTEST_MODULES)
    for m in extra:
        if m and m not in mods:
            mods.append(m)
    ok, detail, dt = _run_code(SELFTEST_SRC, [pkg_dir(), ','.join(mods)], SELFTEST_TIMEOUT)
    return ok, ('OK %.1fs（%d 模块）' % (dt, len(mods))) if ok else detail


# ───────────────────────── 状态行 / CLI ─────────────────────────

def status_line():
    """一句话说清热更三态（朋友说"更新完还是老样子"时，先看这一行）"""
    try:
        st = load_state()
        applied = st.get('applied') or ''
        rolled = st.get('rolledBack') or ''
        pend = read_json(os.path.join(pending_dir(), 'meta.json'))
        sb = ['包 v%s' % pack_version()]
        # ⚠ 没补丁时**不写 "补丁=无（出厂版）"**（用户口径：窗口上不要出现"出厂版"）：
        #   普通用户从没热更过，这个字段对他们没意义，只会显得像"我的包是残缺的" ✗
        #   真装了补丁时仍照旧显示 `补丁=xxx(已确认/待确认)` ✓
        if applied:
            sb.append('补丁=%s%s' % (applied, '(已确认)' if st.get('confirmed') else '(待确认)'))
        if pend.get('id'):
            sb.append('待激活=%s' % pend['id'])
        if rolled:
            sb.append('上次回滚=%s' % rolled)
        sb.append('包目录=%s' % pkg_dir())
        return ' · '.join(sb)
    except Exception as e:                  # noqa: BLE001
        return '热更状态读取失败：%r' % e


def main(argv):
    mode = (argv[1] if len(argv) > 1 else 'status').lower()

    if mode == 'status':
        _out(status_line())
        return 0

    if mode == 'check':
        st = load_state()
        try:
            mf = fetch_manifest()
        except Exception as e:              # noqa: BLE001
            _out('✗ 拉清单失败：%r' % e)
            return 2
        verdict, entry = hot_verdict(mf, st)
        pc = (mf.get('pc') or {})
        _out('本机 %s' % status_line())
        _out('线上：补丁=%s ｜ 整包 v%s ｜ 更新于 %s'
             % (verdict, (pc.get('pack') or {}).get('version', '?'), mf.get('updated', '?')))
        if entry:
            _out('  · %s  %.2fMB  %s' % (entry.get('id'),
                                         (entry.get('size') or 0) / 1048576.0,
                                         entry.get('notes') or ''))
        return 0

    if mode in ('hot', 'update'):
        msg = auto_update()
        if not msg:
            _out('没有可更新的补丁（详见 %s）' % _log_path())
        return 0

    if mode == 'apply':
        ok, msg = apply_pending()
        _out(('✓ ' if ok else '✗ ') + msg)
        return 0 if ok else 1

    if mode == 'confirm':
        _out('✓ 已确认' if confirm_alive() else '（当前没有待确认的补丁）')
        return 0

    if mode == 'rollback':
        n = rollback('用户手动回滚（hotupdate.py rollback）')
        _out('✓ 已回滚到出厂版（还原 %d 个文件）' % n)
        return 0

    if mode == 'selftest':
        ok, detail = selftest()
        _out('%s 自检：%s' % ('✓' if ok else '✗', detail))
        return 0 if ok else 1

    _out(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
