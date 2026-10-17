# -*- coding: utf-8 -*-
"""verify_hotupdate.py · PC 端（桌面端）热更新门禁

    & $py 本仓\\verify_hotupdate.py        # 必须 exit 0

为什么单独一个门禁
------------------
热更的核心不是"能更新"，而是**更新失败时能自己退回去**。而这条路径平时**永远跑不到**
（跑不到 = 门禁不红 = 真出事时才发现 —— 和 AGENTS.md §4.2 的老教训同族）。
⇒ 这里在**临时假包目录**上把状态机真跑一遍（覆盖/回滚/拉黑/bootRecover），
  用一个本地 http server 当"更新源"，**绝不碰真仓、绝不联网**。

判据（全部必须过）
------------------
  T1  初始：无补丁 ⇒ 状态行说"出厂版"
  T2  下载：auto_update() 把补丁落到 hot/pending/（带 meta.json）
  T3  激活：apply_pending() 真覆盖 + 原文件进了 hot/orig/ + **子进程 import 到的是补丁版**
  T4  确认：confirm_alive() ⇒ confirmed=true（界面起来后才确认）
  T5  幂等：已是最新的补丁不会重复下载
  T6  坏包·语法错：**一个字节都不落地**（在覆盖之前就拦下）+ 拉黑
  T7  坏包·import 错：覆盖后自检失败 ⇒ **自动恢复出厂版** + 拉黑
  T8  校验：sha256 不符 ⇒ 不落 pending
  T9  恶意条目：`../evil.py` 与引导层（bootstrap.py/hotupdate.py）一律拒绝
  T10 未确认：连续 2 次没跑到确认点 ⇒ 回滚（第 1 次只重试，别冤枉快关窗口的用户）
  T11 拉黑：同一坏包 id **不会**再自动重装（否则每次启动都下一遍再回滚）
  T12 没网：拉清单失败 ⇒ 静默返回 None，**绝不抛**（不能让没网的朋友起不来）
  T13 引导层保护：补丁闭包里不可能出现 bootstrap/hotupdate
  T14 新增文件回滚：补丁新加的文件，回滚时会被删掉
  T15 端到端：**用真实发版脚本打的补丁**跑完整链路（下载→覆盖→自检→确认）
"""
import base64
import http.server
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
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）
import tempfile
import threading
import time
import urllib.parse
import zipfile

try:                                    # GBK 控制台打 '✓' 会炸 ⇒ 假红（见 AGENTS.md §2）
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                       # noqa: BLE001
    pass

WORK = tempfile.mkdtemp(prefix='mgas_hot_gate_')
PKG = os.path.join(WORK, 'pkg')
WWW = os.path.join(WORK, 'www')
MANIFEST = os.path.join(WWW, 'manifest.json')
PROBE = 'hot_probe_mod.py'                              # 探针模块（仓里没有，只有门禁造）

PASS, FAIL = [], []


PASS = []
FAIL = []
SKIP = []


def check(cond, name, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '   ← %s' % (extra,)))


def section(t):
    print('\n── %s ──' % t)


# ───────────────────────── 假包目录 ─────────────────────────

def build_pkg():
    """拷一份 mapbot_pc 顶层 .py 到临时目录（= 朋友的包），外加探针模块与空目录"""
    shutil.rmtree(PKG, ignore_errors=True)
    os.makedirs(PKG)
    for f in os.listdir(HERE):
        src = os.path.join(HERE, f)
        if f.endswith('.py') and os.path.isfile(src):
            shutil.copy2(src, os.path.join(PKG, f))
    for sub in ('templates', 'runs', 'models_int8', 'maa_res', 'hot'):
        os.makedirs(os.path.join(PKG, sub), exist_ok=True)
    # ⚠ 数据表必须带（2026-10-17 目录整理后它搬到了 `data/`）
    #   假包缺配表 ⇒ `spots.py` 在 import 期就 `SystemExit('找不到游戏数据表')`
    #   ⇒ 热更自检 import 失败 ⇒ T3/T4/T14/T16/T17/T18 一连串**假红** ✗
    os.makedirs(os.path.join(PKG, 'data'), exist_ok=True)
    _dt = os.path.join(HERE, 'data', 'server_datatable.json')
    if os.path.isfile(_dt):
        shutil.copy2(_dt, os.path.join(PKG, 'data', 'server_datatable.json'))
    io.open(os.path.join(PKG, 'PC_VERSION'), 'w', encoding='utf-8').write('1.0\n')
    io.open(os.path.join(PKG, PROBE), 'w', encoding='utf-8').write("TAG = 'B'\n")   # B = 内置
    shutil.rmtree(os.path.join(PKG, 'hot'), ignore_errors=True)


def probe_tag_in_pkg():
    """**另起子进程** import 探针模块 —— 这是"补丁真的生效"的硬证据（不是只看文件内容）"""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run([sys.executable, '-c', 'import %s as m; print(m.TAG)' % PROBE[:-3]],
                       cwd=PKG, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    return ((r.stdout or '') + (r.stderr or '')).strip()


def read_pkg(rel):
    p = os.path.join(PKG, *rel.split('/'))
    if not os.path.isfile(p):
        return None
    return io.open(p, encoding='utf-8', errors='replace').read()


def clear_state():
    shutil.rmtree(os.path.join(PKG, 'hot'), ignore_errors=True)


# ───────────────────────── 更新源（本地 http）─────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):          # 别把 http 日志刷到门禁输出里
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == '/api/manifest.json':
                body = json.dumps({'content': base64.b64encode(
                    open(MANIFEST, 'rb').read()).decode()}).encode('utf-8')
            elif path == '/manifest.json':
                body = open(MANIFEST, 'rb').read()
            elif path.startswith('/pc/'):
                body = open(os.path.join(WWW, *path.lstrip('/').split('/')), 'rb').read()
            else:
                self.send_error(404)
                return
        except Exception:               # noqa: BLE001
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def skip(name):
    """前提不成立（缺可选组件）⇒ **响亮跳过**（不算通过、不算失败）"""
    print('  [SKIP] %s' % name)
    SKIP.append(name)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

os.environ['MGAS_PC_PKG_DIR'] = PKG
os.environ['MGAS_PC_MANIFEST_API'] = 'http://127.0.0.1:%d/api/manifest.json' % PORT
os.environ['MGAS_PC_MANIFEST_RAW'] = 'http://127.0.0.1:%d/manifest.json' % PORT
os.environ.pop('MAPBOT_FRIEND', None)
sys.path.insert(0, ROOT)
import hotupdate as HU                                            # noqa: E402


# 端口是启动后才知道的 ⇒ 再显式钉一次（模块级常量在 import 时取的是 env）
HU.MANIFEST_API = os.environ['MGAS_PC_MANIFEST_API']
HU.MANIFEST_RAW = os.environ['MGAS_PC_MANIFEST_RAW']


def sha256(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def publish(files, hid, min_pack='1.0', notes='gate', corrupt_sha=False, pack_ver='1.0'):
    """把补丁放到"线上"（本地 www/pc/），并写好 manifest"""
    os.makedirs(os.path.join(WWW, 'pc'), exist_ok=True)
    zp = os.path.join(WWW, 'pc', hid + '.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, content in files.items():
            z.writestr(rel, content)
    data = open(zp, 'rb').read()
    entry = {'id': hid, 'minPack': min_pack,
             'url': 'http://127.0.0.1:%d/pc/%s.zip' % (PORT, hid),
             'size': len(data), 'sha256': ('0' * 64 if corrupt_sha else sha256(data)),
             'files': len(files), 'notes': notes}
    write_manifest(entry, pack_ver)
    return entry


def write_manifest(hot=None, pack_ver='1.0'):
    io.open(MANIFEST, 'w', encoding='utf-8').write(json.dumps({
        'schema': 1, 'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'app': None, 'hot': None,
        'pc': {'hot': hot, 'pack': {'version': pack_ver, 'notes': 'gate'}},
    }, ensure_ascii=False))


def state():
    return HU.load_state()


# ───────────────────────── 用例 ─────────────────────────

# ── `release_pc.py` 是**作者的发版工具**（含发布者仓库地址）
#   公开版已剔除 ⇒ T13/T15 在发布仓里无法运行
#   ⚠ 必须**响亮跳过**而不是崩：那两段一崩，后面的 T14/T16/T17 全跑不到
try:
    sys.path.insert(0, os.path.join(HERE, 'tools'))
    import release_pc                                    # noqa: E402,F401
    HAS_RELEASE_PC = True
except Exception:                                        # noqa: BLE001
    HAS_RELEASE_PC = False

def main():
    build_pkg()
    os.makedirs(WWW, exist_ok=True)

    # T1 初始状态
    section('T1 初始：没有补丁')
    # ⚠ 2026-10-17 **按新行为改写**（不是"改断言让它过"，是用户口径变了）：
    #   用户：「去掉窗口上的那个出厂版」
    #   ⇒ `status_line()` 在没有补丁时**不再**输出「补丁=无（出厂版）」，
    #     而是只留 `包 vX.Y · 包目录=…`（普通用户不关心热更字段）
    #   ⚠ 断言仍要**双向钉住**：
    #     ① 没补丁时**不含**「出厂版」（新行为）
    #     ② 仍含包版本与包目录（status_line 的核心信息没被误删）
    _s1 = HU.status_line()
    check('出厂版' not in _s1, 'T1a 无补丁时状态行**不出现**「出厂版」（用户口径）', _s1)
    check('包 v' in _s1 and '包目录' in _s1,
          'T1a2 状态行仍含包版本与包目录（核心信息没删）', _s1)
    check(HU.load_state() == {}, 'T1b state.json 还不存在')

    # T2/T3 好补丁：覆盖 + 生效
    section('T2/T3 好补丁：下载 → 激活 → 真的生效')
    clear_state()
    good = {PROBE: "TAG = 'H'\n"}
    ent = publish(good, 'hot-pc-1.0-good0001')
    msg = HU.auto_update()
    check(bool(msg), 'T2a auto_update 拿到补丁', msg)
    check(os.path.isfile(os.path.join(HU.pending_dir(), 'meta.json')), 'T2b pending/meta.json 就绪')
    check(HU.load_state().get('applied') in (None, ''), 'T2c 下载阶段**还没**覆盖（下次启动才生效）')
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T2d 内置文件此刻未被改动')
    okp, detp = HU.apply_pending()
    check(okp, 'T3a apply_pending 成功', detp)
    check(probe_tag_in_pkg().endswith('H'), 'T3b **子进程 import 到的是补丁版**（真生效）',
          probe_tag_in_pkg())
    check(os.path.isfile(os.path.join(HU.orig_dir(), PROBE)), 'T3c 出厂版已备份进 hot/orig/')
    check(read_pkg_orig(PROBE).strip() == "TAG = 'B'", 'T3d 备份里是**出厂版**内容')
    check(state().get('applied') == ent['id'], 'T3e state.applied = 补丁 id', state())
    check(state().get('confirmed') is False, 'T3f 覆盖后**尚未确认**（等界面起来）')
    check('OK' in str(state().get('selftest')), 'T3g 运行时自检通过', state().get('selftest'))

    # T4 确认
    section('T4 确认点')
    check(HU.confirm_alive() is True, 'T4a confirm_alive 返回 True')
    check(state().get('confirmed') is True, 'T4b state.confirmed = true')
    check(HU.confirm_alive() is False, 'T4c 已确认后再调是 no-op')

    # T5 幂等
    section('T5 已是最新')
    check(HU.auto_update() is None, 'T5a 同一个补丁不会重复下载')
    check(not os.path.isfile(os.path.join(HU.pending_dir(), 'meta.json')), 'T5b pending 里没有残留')

    # T6 坏包·语法错（**不能落地**）
    section('T6 坏包·语法错：一个字节都不落地')
    build_pkg()
    publish({PROBE: "TAG = 'X'\n", 'broken_syntax.py': 'def f(:\n    pass\n'},
            'hot-pc-1.0-syntax01')
    HU.auto_update()
    okp, detp = HU.apply_pending()
    check(okp is False, 'T6a apply_pending 判失败', detp)
    check('语法' in detp or 'COMPILE' in detp, 'T6b 原因是语法检查', detp)
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T6c 目标文件**没被改动**（覆盖前就拦下）',
          read_pkg(PROBE))
    check(not os.path.isfile(os.path.join(PKG, 'broken_syntax.py')), 'T6d 坏文件没落地')
    check(state().get('rolledBack') == 'hot-pc-1.0-syntax01', 'T6e 该 id 已拉黑', state())

    # T7 坏包·import 错（覆盖后自检失败 ⇒ 自动恢复）
    section('T7 坏包·import 错：覆盖后自检失败 ⇒ 自动恢复出厂版')
    build_pkg()
    publish({'probe_boom.py': 'raise RuntimeError("boom at import")\n',
             PROBE: "TAG = 'X'\n"}, 'hot-pc-1.0-import01')
    HU.auto_update()
    okp, detp = HU.apply_pending()
    check(okp is False, 'T7a apply_pending 判失败', detp)
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T7b 目标文件已**恢复出厂版**', read_pkg(PROBE))
    check(not os.path.isfile(os.path.join(PKG, 'probe_boom.py')), 'T7c 新增的坏文件被删掉')
    check(state().get('rolledBack') == 'hot-pc-1.0-import01', 'T7d 该 id 已拉黑', state())
    check(os.path.isdir(HU.bad_dir()) and os.listdir(HU.bad_dir()),
          'T7e 坏包留在 hot/bad/ 取证（不删）')

    # T8 sha256 不符
    section('T8 sha256 不符')
    build_pkg()
    publish({PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-badsha1', corrupt_sha=True)
    msg = HU.auto_update()
    check(msg is None, 'T8a 下载被拒（auto_update 静默返回 None）', msg)
    check(not os.path.isfile(os.path.join(HU.pending_dir(), 'meta.json')), 'T8b pending 未就绪')

    # T9 恶意条目
    section('T9 恶意条目：目录穿越 + 引导层')
    build_pkg()
    before_boot = read_pkg('bootstrap.py')
    before_hu = read_pkg('hotupdate.py')
    publish({'../evil.py': 'print(1)\n', 'bootstrap.py': '# pwned\n',
             'hotupdate.py': '# pwned\n', PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-evil0001')
    HU.auto_update()
    HU.apply_pending()
    check(not os.path.isfile(os.path.join(WORK, 'evil.py')), 'T9a `../evil.py` 没写到包外')
    check(read_pkg('bootstrap.py') == before_boot, 'T9b bootstrap.py 未被覆盖（引导层）')
    check(read_pkg('hotupdate.py') == before_hu, 'T9c hotupdate.py 未被覆盖（引导层）')

    # T10 未确认 ⇒ 连续 2 次才回滚
    section('T10 未确认：第 1 次重试，连续 2 次才回滚')
    build_pkg()
    # 模拟"已经正常覆盖过一次"（含出厂版备份），只是没跑到确认点
    os.makedirs(HU.orig_dir(), exist_ok=True)
    io.open(os.path.join(HU.orig_dir(), PROBE), 'w', encoding='utf-8').write("TAG = 'B'\n")
    io.open(os.path.join(PKG, PROBE), 'w', encoding='utf-8').write("TAG = 'H'\n")   # 假装已覆盖
    HU.save_state({'applied': 'hot-pc-1.0-hang0001', 'confirmed': False,
                   'appliedMeta': {'files': [PROBE]}, 'bootAttempts': 0})
    HU.boot_recover()
    check(state().get('applied') == 'hot-pc-1.0-hang0001', 'T10a 第 1 次不判坏（可能是秒关窗口）')
    check(state().get('bootAttempts') == 1, 'T10b 计数 = 1', state())
    check(read_pkg(PROBE).strip() == "TAG = 'H'", 'T10c 文件仍是补丁版')
    HU.boot_recover()
    check(state().get('applied') in (None, ''), 'T10d 第 2 次 ⇒ 判坏回滚', state())
    check(state().get('rolledBack') == 'hot-pc-1.0-hang0001', 'T10e 该 id 拉黑')
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T10f 文件已恢复出厂版', read_pkg(PROBE))

    # T11 拉黑后不再重装
    section('T11 拉黑后不再自动重装')
    build_pkg()
    publish({PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-hang0001')          # 线上还是那个坏 id
    HU.save_state({'rolledBack': 'hot-pc-1.0-hang0001'})
    check(HU.auto_update() is None, 'T11a 同一个坏 id 不再下载')
    check(not os.path.isfile(os.path.join(HU.pending_dir(), 'meta.json')), 'T11b pending 空')

    # T12 没网
    section('T12 没网：绝不抛异常')
    api_bak, raw_bak = HU.MANIFEST_API, HU.MANIFEST_RAW
    HU.MANIFEST_API = 'http://127.0.0.1:9/manifest.json'
    HU.MANIFEST_RAW = 'http://127.0.0.1:9/manifest.json'
    try:
        msg = HU.auto_update(timeout=2)
        check(msg is None, 'T12a 没网时静默返回 None', msg)
        crashed = False
    except Exception as e:              # noqa: BLE001
        crashed = True
        check(False, 'T12a 没网时静默返回 None', repr(e))
    finally:
        HU.MANIFEST_API, HU.MANIFEST_RAW = api_bak, raw_bak
    check(not crashed, 'T12b 没有把异常抛给启动器')

    # ⚠ T13 依赖 release_pc.py（作者发版工具，公开版已剔除）
    if not HAS_RELEASE_PC:
        skip('T13 引导层保护（静态）：需 tools/release_pc.py（公开版未含）')
    else:
        # T13 引导层保护（静态）
        section('T13 引导层保护（静态）')
        check(HU.BOOT_LAYER == ('bootstrap.py', 'hotupdate.py'), 'T13a BOOT_LAYER 就这两个')
        check(HU._pkg_rel_ok('bootstrap.py') is False, 'T13b bootstrap.py 不许进包')
        check(HU._pkg_rel_ok('hotupdate.py') is False, 'T13c hotupdate.py 不许进包')
        check(HU._pkg_rel_ok('sub/bootstrap.py') is True, 'T13d 子目录同名文件不误伤')
        check(HU._pkg_rel_ok('../x.py') is False, 'T13e 穿越被拒')
        sys.path.insert(0, os.path.join(HERE, 'tools'))
        import release_pc                                          # noqa: E402
        mods = release_pc.py_closure()
        check(len(mods) > 10, 'T13f 发版闭包算得出来（%d 个模块）' % len(mods), mods)
        # ⚠ 闭包里**一定**有 hotupdate（bot_gui 要 import 它调 confirm_alive）
        #   ⇒ 保护方式不是"闭包不含它"，而是"发版时剔除 + 端上再拦一道"
        check('hotupdate' in mods, 'T13g 闭包确实会拉到 hotupdate（所以必须剔除）', mods)
        _zp, patched = release_pc.build_hot_zip('1.0')
        check('hotupdate' not in patched and 'bootstrap' not in patched,
              'T13h 发版补丁里已剔除引导层', patched)
        check('explore_loop' in patched and 'mapbot' in patched and 'marks' in patched,
              'T13i 补丁覆盖核心模块', patched)
        # ⭐⭐ 2026-10-04 新增：补丁**必须带上 `templates/fixed/` 资产**
        #   起因：加了新模板 `battle_win_title.png`（S 级提速的判据①），而补丁原来只收 .py
        #     ⇒ 朋友端 `fixed._load()` 找不到文件 ⇒ 返回 None ⇒ 那条判据**永远不命中**
        #     （只是恰好被判据② `close_tpl` 兜住，所以表面"还能用"）⇒ 静默半新半旧 ✗✗
        assets = release_pc.hot_assets()
        check(len(assets) >= 5,
              'T13j 补丁会带上 templates/fixed 资产（%d 个）' % len(assets), assets)
        check(any(a.endswith('/battle_win_title.png') for a in assets),
              'T13k 新模板 battle_win_title.png 在补丁资产里（S 级提速判据①依赖它）', assets)
        # ⚠ 守门：**只允许** templates/fixed（templates/ 下别的目录是上万张 / ~24MB 识别图集，
        #   一塞进去补丁就不再是"<1MB 一个补丁"，热更的意义就没了）
        check(all(a.startswith('templates/fixed/') for a in assets),
              'T13l 资产只允许 templates/fixed/（不许把 24MB 图集塞进补丁）', assets)
        import zipfile as _zf                                        # noqa: E402
        with _zf.ZipFile(_zp) as _z2:
            _zn = _z2.namelist()
        check('templates/fixed/battle_win_title.png' in _zn,
              'T13m 打出来的 zip 里**确实有**那个模板文件（不是只在名单里）',
              [n for n in _zn if n.endswith('.png')][:4])
        check(not any(n.startswith('bootstrap') or n.startswith('hotupdate') for n in _zn),
              'T13n zip 里没有引导层（连资产路径也不能混进去）', _zn[:3])

        # T14 新增文件回滚 = 删掉
    section('T14 补丁新增的文件，回滚时删掉')
    build_pkg()
    publish({'brand_new_mod.py': 'V = 1\n', PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-newfile1')
    HU.auto_update()
    okp, _ = HU.apply_pending()
    check(okp and os.path.isfile(os.path.join(PKG, 'brand_new_mod.py')), 'T14a 新文件已落地')
    HU.rollback('门禁用例')
    check(not os.path.isfile(os.path.join(PKG, 'brand_new_mod.py')), 'T14b 回滚后新文件被删')
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T14c 探针回到出厂版')

    # T15 端到端：真实发版脚本的补丁
    # ⚠ T15 同样依赖 release_pc.py（端到端用的是它的真实补丁）
    if not HAS_RELEASE_PC:
        skip('T15 端到端（真实补丁）：需 tools/release_pc.py（公开版未含）')
    else:
        section('T15 端到端：真实发版脚本打的补丁')
        build_pkg()
        zp, real_mods = release_pc.build_hot_zip('1.0')
        hid = 'hot-pc-1.0-%s' % sha256(open(zp, 'rb').read())[:8]
        os.makedirs(os.path.join(WWW, 'pc'), exist_ok=True)
        shutil.copy(zp, os.path.join(WWW, 'pc', hid + '.zip'))
        data = open(os.path.join(WWW, 'pc', hid + '.zip'), 'rb').read()
        write_manifest({'id': hid, 'minPack': '1.0',
                        'url': 'http://127.0.0.1:%d/pc/%s.zip' % (PORT, hid),
                        'size': len(data), 'sha256': sha256(data),
                        'files': len(real_mods), 'notes': 'e2e'}, '1.0')
        msg = HU.auto_update()
        check(bool(msg), 'T15a 真实补丁下载成功', msg)
        okp, detp = HU.apply_pending()
        check(okp, 'T15b 真实补丁覆盖 + 自检通过', detp)
        check(HU.confirm_alive() is True, 'T15c 确认')
        check('已确认' in HU.status_line(), 'T15d 状态行显示已确认', HU.status_line())
        HU.rollback('门禁用例收尾')
        check(HU.load_state().get('applied') in (None, ''),
              'T15e 收尾回滚成功（假包回到出厂版）')

        # T16 朋友版开关（**与热更解耦** —— 这是本次设计的要点）
    section('T16 朋友版开关与热更解耦')

    def run_env(code, friend):
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        if friend is None:
            env.pop('MAPBOT_FRIEND', None)
        else:
            env['MAPBOT_FRIEND'] = friend
        r = subprocess.run([sys.executable, '-c', code], cwd=PKG, env=env,
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=180)
        return ((r.stdout or '') + (r.stderr or '')).strip()

    CODE = ("import explore_loop as e; "
            "print('SAVE_FIRST=%s OPT_SOLVER=%s' % (e.SAVE_FIRST, e.OPT_SOLVER))")
    out_f = run_env(CODE, '1')
    out_d = run_env(CODE, '0')
    out_n = run_env(CODE, None)
    # ⭐ 2026-10-03 用户口径改：「**窗口不显示，固定开**」
    #   ⇒ 朋友版 OPT_SOLVER 也是 True（关着实测会 targets_unreachable/stuck ✗）
    check('SAVE_FIRST=False OPT_SOLVER=True' in out_f,
          'T16a 朋友版：不存图 + **固定开**精确规划', out_f)
    check('SAVE_FIRST=True OPT_SOLVER=True' in out_d,
          'T16b 开发版：默认存图 + 开精确规划', out_d)
    check('SAVE_FIRST=True OPT_SOLVER=True' in out_n,
          'T16c 不设环境变量 ⇒ 默认开发版（开发机行为不变）', out_n)
    gui_src = io.open(os.path.join(HERE, 'bot_gui.py'), encoding='utf-8').read()
    loop_src = io.open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    check(gui_src.count('if not FRIEND:') >= 1,
          'T16d bot_gui 里朋友版分支还在（存图勾选框被 `if not FRIEND:` 包住）'
          ' ⚠ 2026-10-11 按新事实改写：本项原来要求 ≥2 处，指的是「存图 + 精确规划」两个勾选框；'
          '而精确规划那个勾选框已按用户 2026-10-03 口径删除'
          '（bot_gui.py 里写着「精确规划按钮删掉，之后都一直是依赖规划」）⇒ 只剩一处，不是漏了 ✓',
          gui_src.count('if not FRIEND:'))
    check('friend_mode' in gui_src and 'friend_mode' in loop_src,
          'T16e 两处都改走 friend_mode（不再靠打包时改源码）')
    check('if not FRIEND' in gui_src and 'tk.Checkbutton(bar2' in gui_src,
          'T16f 存图勾选框确实被条件包住（不是删掉不看 flag）')

    # T17 启动链路（**真跑 bootstrap.py**）：早退要确认、真崩不确认
    section('T17 启动链路：环境没就绪要确认、补丁把界面搞崩不确认')

    def run_bootstrap():
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['MGAS_PC_NO_POPUP'] = '1'       # ⚠ 否则 messagebox 会等人点击，把门禁卡死
        r = subprocess.run([sys.executable, os.path.join(PKG, 'bootstrap.py')],
                           cwd=PKG, env=env, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=300)
        return r.returncode, ((r.stdout or '') + (r.stderr or ''))

    def fake_gui(code):
        io.open(os.path.join(PKG, 'bot_gui.py'), 'w', encoding='utf-8').write(code)

    build_pkg()
    publish({PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-boot0001')
    # ① "模拟器没开/分辨率不对" —— bot_gui 提示一下就 return（**根本没建 Tk 窗口**）
    fake_gui('def main():\n    return 0\n\n\nif __name__ == "__main__":\n    main()\n')
    run_bootstrap()                                  # 第 1 次：下载到 pending
    rc2, out2 = run_bootstrap()                      # 第 2 次：激活 + 自检 + 早退
    check(rc2 == 0, 'T17a 启动器正常退出（界面早退版）', (rc2, out2[-300:]))
    check(state().get('applied') == 'hot-pc-1.0-boot0001', 'T17b 补丁已激活', state())
    check(state().get('confirmed') is True,
          'T17c 界面早退（环境没就绪）**也算确认** —— 不再冤枉回滚/拉黑', state())

    # ② 补丁把界面搞崩：runpy 抛异常 ⇒ 不确认 ⇒ 连续 2 次后回滚
    build_pkg()
    publish({PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-boot0002')
    fake_gui("raise RuntimeError('boom in gui')\n")
    run_bootstrap()                                  # 第 1 次：下载
    rc3, _ = run_bootstrap()                         # 第 2 次：激活 + 自检过 + 界面崩
    check(state().get('applied') == 'hot-pc-1.0-boot0002'
          and state().get('confirmed') is False,
          'T17d 补丁把界面搞崩 ⇒ **不确认**', state())
    check(rc3 == 1, 'T17e 启动器返回 1（起不来）', rc3)
    run_bootstrap()                                  # 第 3 次：boot_recover 第 1 次未确认 ⇒ 重试
    check(state().get('bootAttempts') == 1, 'T17f 第 1 次只重试（不冤枉）', state())
    run_bootstrap()                                  # 第 4 次：第 2 次 ⇒ 回滚
    check(state().get('applied') in (None, ''), 'T17g 连续 2 次 ⇒ 自动回滚', state())
    check(read_pkg(PROBE).strip() == "TAG = 'B'", 'T17h 探针回到出厂版', read_pkg(PROBE))

    # T18 子进程 stderr 有噪音时，自检**不能**被误判成失败
    #   （真包 2026-10-03 实测：朋友版 venv 残留 distutils-precedence.pth ⇒ 每起子进程
    #    一行 ModuleNotFoundError 到 stderr ⇒ 旧判定 `out.endswith('OK')` 直接判失败 + 拉黑 ✗✗）
    section('T18 stderr 噪音不许把自检判失败')
    build_pkg()
    publish({'noisy_mod.py': "import sys\nprint('noise-from-module', file=sys.stderr)\n",
             PROBE: "TAG = 'H'\n"}, 'hot-pc-1.0-noisy001')
    HU.auto_update()
    okp, detp = HU.apply_pending()
    check(okp is True, 'T18a stderr 有噪音也照样通过', detp)
    # 直接验判定本身（不依赖 selftest 在成功时的 detail 措辞）
    ok2, det2, _dt = HU._run_code("import sys; print('noise-from-module', file=sys.stderr)",
                                  [], 60)
    check(ok2 is True and 'noise-from-module' in det2,
          'T18b stderr 有噪音 + exit 0 ⇒ 判通过（且噪音可见于 detail）', (ok2, det2))
    check(probe_tag_in_pkg().endswith('H'), 'T18c 补丁确实生效了', probe_tag_in_pkg())

    # ── 汇总 ──
    print('\n' + '=' * 58)
    # ⚠ 跳过要**如实报**（以前写死 "跳过 0"，跳了也看不出来 ✗）
    print('通过 %d / 失败 %d / 跳过 %d' % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print('失败项：')
        for f in FAIL:
            print('  ✗ %s' % f)
    if SKIP:
        print('跳过项（前提不成立，非代码问题）：')
        for s in SKIP:
            print('  - %s' % s)
    print('临时目录（可删）：%s' % WORK)
    return 1 if FAIL else 0


def read_pkg_orig(rel):
    p = os.path.join(HU.orig_dir(), *rel.split('/'))
    if not os.path.isfile(p):
        return None
    return io.open(p, encoding='utf-8', errors='replace').read()


if __name__ == '__main__':
    try:
        code = main()
    finally:
        try:
            srv.shutdown()
        except Exception:               # noqa: BLE001
            pass
    sys.exit(code)
