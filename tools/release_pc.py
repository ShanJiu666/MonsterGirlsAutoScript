# -*- coding: utf-8 -*-
"""release_pc.py · PC 端（桌面端）发版 + 热更推送 —— **一条命令搞定**

    # ① 日常迭代（99% 的情况）：打逻辑补丁 + 推清单
    python mapbot_pc\\tools\\release_pc.py --notes "修 XX 误判"

    # ② 只看要发什么、不推送
    python mapbot_pc\\tools\\release_pc.py --notes "测试" --dry-run

    # ③ 改了 bootstrap/hotupdate（引导层）或 venv ⇒ 要重发**整包**：
    #    先抬版本号（写进 PC_VERSION，朋友包里靠它做 minPack 判据），再手工把 zip 发给朋友
    python mapbot_pc\\tools\\release_pc.py --bump-pack 1.01 --notes "壳改动"

发给朋友的链路
--------------
    本脚本 → 公开仓 `geng-haojie/MGAS-pc-update`
             ├── manifest.json                  （端上拉这个判断有没有新版）
             └── pc/hot-pc-<包版本>-<sha8>.zip  （逻辑补丁，<1MB，raw 直读）
    朋友的端自己 HTTP 拉 —— **他不会打开 Gitee、不用注册、不用登录** ✓

⭐ 补丁里带哪些文件：**从 `bot_gui.py` / `explore_loop.py` 出发的 import 闭包**（AST 抓，
   含 `__import__('x')` / `import_module('x')` 这种写法）
   **＋ `templates/fixed/*.png`**（固定 UI 模板，代码行为的一部分 ⇒ 必须同版本，
     见 `ASSET_DIRS` 注释；2026-10-04 踩过"只发 .py ⇒ 新模板静默不生效"✗）。
   为什么不用"全部 .py"：会把 diag/verify/probe 一堆测试脚本也发出去（无害但没必要）。
   为什么不用手写白名单：**漏一个被 import 的模块 ⇒ 朋友那边"一半新一半旧"，
   比全旧还难查** ✗（闭包天然不会漏）

⚠ 两个**引导层**文件永不进补丁（`hotupdate.BOOT_LAYER`）：`bootstrap.py` / `hotupdate.py`
  —— 它们是"更新器自己"，改了必须走整包。脚本会拒收，门禁也有一项守它。

⚠ 令牌从哪来（**绝不能写进会被 push 的文件里**，AGENTS.md 有明确要求）：
    ① 环境变量 `GITEE_TOKEN`
    ② 用户主目录 `~/.gitee_token`
"""
import argparse
import ast
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

try:                                    # GBK 控制台打中文/✓ 会炸
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # 仓根
# ⚠ 2026-10-18：业务 .py 在 `core/`（目录整理后），而资源
#   (`templates/` `data/`) 仍在仓根 ⇒ **两个基准**必须分清
#   ⚠ 但发包时 arcname 必须**平铺**（端上 `_dst_of` 会把根级 .py 落到 core/）
_CORE = os.path.join(ROOT, 'core')
CODE = _CORE if os.path.isdir(_CORE) else ROOT
# ⚠ `hotupdate` 在 `core/`（业务模块）⇒ 两个都加，兼容平铺/拆分布局
for _p in (CODE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hotupdate as HU                  # noqa: E402  （只为 BOOT_LAYER）

# ⚠ 更新源写在**本脚本**里（发布仓的 hotupdate 故意留空 ⇒ 不把某个人的仓址
#   写进公开代码；但发版工具**必须知道往哪发** ⇒ 只在这里写 ✓）
HU_OWNER = 'geng-haojie'
HU_REPO = 'MGAS-pc-update'

OWNER, REPO = HU_OWNER, HU_REPO
API = 'https://gitee.com/api/v5/repos/%s/%s' % (OWNER, REPO)
RAW = 'https://gitee.com/%s/%s/raw/master' % (OWNER, REPO)
MANIFEST_URL = RAW + '/manifest.json'
MANIFEST_API = API + '/contents/manifest.json'

SEEDS = ('bot_gui', 'explore_loop')     # 朋友版的两个入口（bot_gui 会 spawn explore_loop）
KEEP_HOT_ZIPS = 5                       # 仓库配额有限，只留最近 5 个补丁

# ⭐⭐ 补丁里的**资产**（非 .py）—— 必须跟代码一起发，否则就是"一半新一半旧"✗
#   2026-10-04 实证踩到：新增了模板 `templates/fixed/battle_win_title.png`（S 级提速用），
#   而补丁原来**只收 .py** ⇒ 朋友端 `fixed._load()` 找不到那个文件 ⇒ 返回 None
#   ⇒ `battle_started_fast()` 的 ① 判据**永远不命中**（只是恰好被 ② `close_tpl` 兜住，
#     所以表面上"还能用"）⇒ 这种"静默少一张图"极难查 ✗
#   ⚠ 只发 `templates/fixed/`（`fixed.py` **专用**的固定 UI 模板，17 张 ≈ 50KB）；
#     `templates/` 下别的目录是识别用图集（上万张 / ~24MB）⇒ **绝不能**塞进补丁
#     （补丁一直号称 <1MB，这是它的价值所在）。
ASSET_DIRS = ('templates/fixed',)


# ───────────────────────────── 小工具 ─────────────────────────────

def die(msg):
    print('✗ ' + msg)
    raise SystemExit(1)


def token():
    t = (os.environ.get('GITEE_TOKEN') or '').strip()
    if t:
        return t
    p = os.path.join(os.path.expanduser('~'), '.gitee_token')
    if os.path.isfile(p):
        with io.open(p, encoding='utf-8') as f:
            t = f.read().strip()
        if t:
            return t
    die('找不到 Gitee 令牌：设环境变量 GITEE_TOKEN，或写到 %s' % p)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def http_json(url, method='GET', body=None, timeout=60):
    data = None
    headers = {'User-Agent': 'MGAS-PC-Release/1'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8')
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:400]
        raise RuntimeError('HTTP %s %s → %s' % (e.code, url, detail))
    except urllib.error.URLError as e:
        raise RuntimeError('网络失败 %s → %s' % (url, e))


def read_manifest_live():
    """读线上 manifest（**必须走 contents API**，raw 有强缓存 —— 手机端 2026-10-03 实测）

    ⚠ 本脚本是"读旧清单 → 只改 pc 段 → 写回"；读到缓存的旧清单会把**手机端那两段
      （app/hot）覆盖成 null** ⇒ 手机端热更永久失效 ✗✗
    """
    try:
        d = http_json(MANIFEST_API)
        if isinstance(d, dict) and d.get('content'):
            return json.loads(base64.b64decode(d['content']).decode('utf-8'))
        return {}
    except Exception as e:              # noqa: BLE001
        print('  · API 读清单失败（回落 raw，可能读到缓存）：%s' % e)
        try:
            return http_json(MANIFEST_URL)
        except Exception as e2:         # noqa: BLE001
            print('  · raw 也读不到（首次发版）：%s' % e2)
            return {}


# ───────────────────────────── 补丁内容 ─────────────────────────────

def imports_of(path):
    """AST 抓一个 .py 里 import 到的顶层模块名（含 `__import__('x')` / `import_module('x')`）"""
    try:
        with io.open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), path)
    except Exception as e:              # noqa: BLE001
        print('  ⚠ 解析 %s 失败（当它没有 import）：%r' % (os.path.basename(path), e))
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                names.add(node.module.split('.')[0])
        elif isinstance(node, ast.Call):
            fn = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if fn in ('import_module', '__import__') and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    names.add(a0.value.split('.')[0])
    return names


def _mod_files(m):
    """模块名 -> 仓内相对 `.py` 路径（**正斜杠、含子目录**）；不存在 ⇒ `[]`（标准库/第三方）

    ⭐⭐⭐ 2026-10-11 新增（起因：UI 重设计把 `bot_gui.py` 拆成了 `bot_gui_ui/` **包**）
    ---- 病（原来只有一条规则 `os.path.join(CODE, m + '.py')` ⇒ **只认顶层单文件模块**）----
      包名映射不到文件 ⇒ `py_closure` 里 `if not os.path.isfile(p): continue`
      **静默跳过、不报错、不警告** ✗✗ ⇒ 补丁会打出「**新的 `bot_gui.py` + 根本没有包**」
      ⇒ 端上 `from bot_gui_ui import ...` 直接 `ModuleNotFoundError` ⇒ **界面起不来** ✗✗
      实测（对着已接线的 worktree 跑真函数）：`imports_of('bot_gui.py')` 里**确实有**
      `bot_gui_ui`，但 `py_closure()` 24 个模块里**一个 `bot_gui_ui/*` 都没有**。
      ⚠ 同族还有一处**已经发生**的漏网：设备逻辑搬进 `bot_gui_ui/services.py` 之后，
        `mumu` 不再出现在闭包里（25→24）⇒ 补丁会带新版 services + **旧版 mumu.py**，
        正是本文件开头警告的「一半新一半旧，比全旧还难查」✗ ⇒ 本函数一并修好 ✓
    ---- 修法（老行为**一字不改**，只加"包"这一支）----
      ① 顶层单文件：先试 `m + '.py'`（老路径，成功即返回）✓
      ② 否则看是不是**包**（目录里有 `__init__.py`）⇒ `os.walk` 递归收全部 `.py` ✓
      ③ 再否则 ⇒ `[]`（真·标准库/第三方，继续静默跳过 ✓）
    ⚠ 返回值**必须去掉 `.py`**：下游 `build_hot_zip` 用 `m + '.py'` 拼路径与 arcname
      （带上扩展名会让门禁 `verify_hotupdate.py` 的 `'hotupdate' in mods` **假红** ✗）
    """
    rel = m + '.py'
    if os.path.isfile(os.path.join(CODE, rel)):
        return [rel]
    d = os.path.join(CODE, *str(m).split('/'))
    if os.path.isfile(os.path.join(d, '__init__.py')):
        out, skipped = [], []
        for base, _dirs, fs in os.walk(d):
            for fn in sorted(fs):
                if not fn.endswith('.py'):
                    continue
                # ⚠ 包里的 `_*.py` 是**开发用**的（`_demo.py` 组件演示 / `_selftest_*.py`
                #   自检）⇒ **不进补丁**（朋友不需要，白占 ~110KB；且它们会 import tkinter
                #   真起窗口）。`__init__.py` 例外，必须带 ✓
                #   这与老闭包的天然行为一致：顶层那些 `_tip*.py` / `_probe_*.py`
                #   从来没人 import ⇒ 本来就不在闭包里 ✓
                if fn.startswith('_') and fn != '__init__.py':
                    skipped.append(fn)
                    continue
                out.append(os.path.relpath(os.path.join(base, fn), ROOT)
                           .replace(os.sep, '/'))
        if skipped:
            print('  · 包 %s 里的开发用文件**不进补丁**：%s'
                  % (m, ', '.join(sorted(skipped))))
        return sorted(out)
    return []


def py_closure(seeds=SEEDS):
    """从入口出发的 import 闭包（仓里真的存在的 `.py`；**支持包**，见 `_mod_files`）

    返回值 = **去扩展名、正斜杠**的相对路径（`'bot_gui'` / `'bot_gui_ui/theme'`），
    ⇒ `build_hot_zip` 里 `os.path.join(CODE, m + '.py')` 与 `arcname = m + '.py'`
      **一行都不用改**，`bot_gui_ui/theme.py` 天然就是 zip 里的子目录条目 ✓
      （zip 存子目录已有先例：`ASSET_DIRS` 的 `templates/fixed/*.png` 就是这么发的 ✓）
    """
    seen_mods, out, stack = set(), set(), list(seeds)
    while stack:
        m = stack.pop()
        if m in seen_mods:
            continue
        files = _mod_files(m)
        if not files:
            continue                    # 标准库 / 第三方
        seen_mods.add(m)
        for rel in files:
            out.add(rel[:-3])           # ⚠ 去 `.py`（下游要 `m + '.py'` 复原）
            for n in imports_of(os.path.join(CODE, rel.replace('/', os.sep))):
                if n not in seen_mods:
                    stack.append(n)
    return sorted(out)


def hot_assets():
    """补丁里的**资产**相对路径（仓内相对，正斜杠）—— 见 `ASSET_DIRS` 的长注释

    ⚠ 走 `HU._pkg_rel_ok()` 过一遍，保证与端上同一套"什么能落地"的判据
      （引导层/目录穿越在这里就该被挡住，而不是等端上才拒）
    """
    out = []
    for d in ASSET_DIRS:
        full = os.path.join(ROOT, d.replace('/', os.sep))
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            fp = os.path.join(full, fn)
            if not os.path.isfile(fp):
                continue
            rel = '%s/%s' % (d, fn)
            if not HU._pkg_rel_ok(rel):
                die('资产 %s 被 `_pkg_rel_ok` 拒绝（不该发生，检查 ASSET_DIRS）' % rel)
            out.append(rel)
    return out


def build_hot_zip(pack_ver):
    """打补丁 zip（**顶层平铺**，与包内 `mapbot_pc/` 相对路径一致）

    ⚠ 闭包里**必然出现 `hotupdate`**（`bot_gui.py` 要 import 它来调 confirm_alive）
      ⇒ 这里把它和 `bootstrap.py` **剔除**（它们是引导层，端上也有各自的内置版，
        补丁绝不能覆盖 —— `hotupdate._pkg_rel_ok` 端上还会再拦一道 ✓）

    ⭐ 除了 .py，还带上 `ASSET_DIRS` 里的**资产**（`templates/fixed/*.png`）——
      模板是代码行为的一部分，缺一张就是"静默少一条判据"✗（详见 `ASSET_DIRS` 注释）
    """
    mods = [m for m in py_closure() if (m + '.py') not in HU.BOOT_LAYER]
    dropped = sorted(set(py_closure()) - set(mods))
    if dropped:
        print('  · 引导层已剔除（不进补丁）：%s' % ', '.join(dropped))
    assets = hot_assets()
    tmp = os.path.join(tempfile.gettempdir(), 'mgas_pc_hot_%d.zip' % int(time.time()))
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for m in mods:
            z.write(os.path.join(CODE, m + '.py'), m + '.py')
        for rel in assets:
            z.write(os.path.join(ROOT, rel.replace('/', os.sep)), rel)
    if assets:
        print('  · 资产 %d 个（templates/fixed）：%s'
              % (len(assets), ', '.join(os.path.basename(a) for a in assets)))
    return tmp, mods + assets


# ───────────────────────────── 推仓库 ─────────────────────────────

def push_files(tok, files, commit_msg):
    """clone → 覆盖 → commit → push（⚠ 用 git 而不是 contents API：补丁是二进制，API 要塞 base64）"""
    work = os.path.join(tempfile.gettempdir(), 'mgas_pc_update_push_%d' % int(time.time()))
    shutil.rmtree(work, ignore_errors=True)
    url = 'https://%s:%s@gitee.com/%s/%s.git' % (OWNER, urllib.parse.quote(tok), OWNER, REPO)
    print('  · clone %s' % REPO)
    r = subprocess.run(['git', 'clone', '--depth', '1', url, work],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        die('clone 失败：%s' % (r.stderr or r.stdout))
    for src, rel in files:
        dst = os.path.join(work, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        print('  · 写入 %s (%.1f KB)' % (rel, os.path.getsize(src) / 1024.0))
    for c in (['git', 'add', '-A'],
              ['git', '-c', 'user.name=MGAS-pc-release', '-c', 'user.email=release@local',
               'commit', '-m', commit_msg],
              ['git', 'push', 'origin', 'master']):
        r = subprocess.run(c, cwd=work, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            # ⚠ 判定用 `'commit' in c`（commit 那条带 `-c user.name=…` 前缀，c[1] 是 '-c'）
            if 'commit' in c and 'nothing to commit' in (r.stdout or '') + (r.stderr or ''):
                print('  · 无变化，跳过 commit')
                return work
            die('%s 失败：%s' % (' '.join(c[:3]), (r.stderr or r.stdout)[:800]))
    print('  ✓ 已推送 %s' % commit_msg)
    return work


def prune_old_hot(tok, keep=KEEP_HOT_ZIPS, keep_id=''):
    """只留最近 keep 个补丁（仓库配额 1GB —— hb-web 的老教训）"""
    try:
        items = http_json('%s/contents/pc?access_token=%s' % (API, urllib.parse.quote(tok)))
    except Exception as e:              # noqa: BLE001
        print('  · 读 pc/ 目录失败（跳过清理）：%s' % e)
        return
    if not isinstance(items, list):
        return
    zips = [i for i in items if i.get('name', '').endswith('.zip')]

    # ⛔⛔ 2026-10-18 **真机抓到的严重 bug**（发一次就中招，客户端 404）
    #   原来：`zips = sorted(..., key=name)` 然后删 `zips[:-keep]`
    #     ⇒ `hot-pc-1.0-0ed0504c` 的 `'0' < '6'` ⇒ 排最前 ⇒ **刚传的新补丁被删** ✗
    #   实测：manifest 指向 0ed0504c，但 pc/ 里没有它 ⇒ 下载补丁 404 ✗✗
    #   ⚠ 这个 bug 一直在，只是以前的 sha 首字母恰好排后面才没触发 ✓
    # ---- 修法 ----
    #   ① `keep_id`（= **manifest 当前指向的那个**）**永不删** —— 删了客户端必 404
    #   ② 其余按 `updated_at` 倒序（Gitee contents 返回里有），保留最新若干个
    #   ③ 兜底：待删列表里**再过滤一次** keep_id（双保险）
    cur = None
    if keep_id:
        want = '%s.zip' % keep_id
        cur = next((z for z in zips if z.get('name') == want), None)
        if cur is None:
            print('  · ⚠ manifest 指向 %s 但 pc/ 里没有（先查 push 是否成功）' % keep_id)
    rest = [z for z in zips if z is not cur]

    def _t(z):
        return str(z.get('updated_at') or z.get('created_at') or '')
    timed = [z for z in rest if _t(z)]
    untimed = [z for z in rest if not _t(z)]
    if timed:
        rest = sorted(timed, key=_t, reverse=True) + untimed

    budget = max(0, int(keep) - (1 if cur else 0))
    victims = rest[budget:]
    if keep_id:
        victims = [v for v in victims if v.get('name') != '%s.zip' % keep_id]

    if not victims:
        print('  · 无需清理（共 %d 个补丁，保留全部）' % len(zips))
        return
    for it in victims:
        try:
            http_json('%s/contents/%s?access_token=%s&sha=%s&message=%s'
                      % (API, urllib.parse.quote(it['path']), urllib.parse.quote(tok),
                         it['sha'], urllib.parse.quote('prune old hot zip')),
                      method='DELETE')
            print('  · 清理旧补丁 %s' % it['name'])
        except Exception as e:          # noqa: BLE001
            print('  · 清理 %s 失败（不影响发版）：%s' % (it['name'], e))


# ───────────────────────────── 主流程 ─────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--notes', default='', help='更新说明（进 manifest，端上留痕）')
    ap.add_argument('--bump-pack', default='', metavar='VERSION',
                    help='抬整包版本号（写进 PC_VERSION；只有重发整包时才需要）')
    ap.add_argument('--min-pack', default='', help='补丁要求的最低整包版本（默认=当前）')
    ap.add_argument('--manifest-only', action='store_true',
                    help='只重写 manifest 里的 pc 段（不重打补丁、不推送 zip）')
    ap.add_argument('--dry-run', action='store_true', help='只生成、不推送')
    a = ap.parse_args()

    ver = HU.pack_version()
    if a.bump_pack:
        io.open(HU.VERSION_FILE, 'w', encoding='utf-8').write(a.bump_pack.strip() + '\n')
        ver = a.bump_pack.strip()
        print('  · 整包版本号已抬到 %s（注意：**整包 zip 要另行发给朋友**）' % ver)

    tok = None if a.dry_run else token()
    print('== MGAS PC 端发版 ==  整包版本 %s' % ver)

    old = read_manifest_live()
    if old:
        print('  · 现有清单已读到（手机端 app=%s hot=%s ｜ pc=%s）'
              % (bool(old.get('app')), bool(old.get('hot')), bool(old.get('pc'))))
    else:
        print('  · 没有现有清单（首次发版）')

    # ⚠ 只改 pc 段，**手机端那两段原样保留**（否则一发 PC 补丁就把手机端热更弄死 ✗）
    manifest = {'schema': 1, 'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'app': old.get('app'), 'hot': old.get('hot'), 'pc': old.get('pc') or {}}
    files = []

    if not a.manifest_only:
        zp, mods = build_hot_zip(ver)
        sha = sha256_file(zp)
        hid = 'hot-pc-%s-%s' % (ver, sha[:8])
        size = os.path.getsize(zp)
        rel = 'pc/%s.zip' % hid
        manifest['pc'] = dict(manifest.get('pc') or {})
        manifest['pc']['hot'] = {
            'id': hid,
            'minPack': a.min_pack or ver,
            'url': '%s/%s' % (RAW, rel),
            'size': size,
            'sha256': sha,
            'files': len(mods),
            'notes': a.notes,
        }
        print('  · 补丁 %s：%d 个文件，%.1f KB' % (hid, len(mods), size / 1024.0))
        print('    文件：%s' % ', '.join(mods))
        files.append((zp, rel))

    manifest['pc'] = dict(manifest.get('pc') or {})
    manifest['pc']['pack'] = {'version': ver, 'notes': a.notes,
                              'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                              'zip': manifest['pc'].get('pack', {}).get('zip', '')}

    mf = os.path.join(tempfile.gettempdir(), 'mgas_pc_manifest.json')
    with io.open(mf, 'w', encoding='utf-8') as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    files.append((mf, 'manifest.json'))
    print('  · manifest 就绪：')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if a.dry_run:
        print('\n[dry-run] 到此为止，没有推送。')
        return 0

    push_files(tok, files, 'pc release v%s (%s)' % (ver, a.notes or 'update'))
    prune_old_hot(tok, keep_id=hid)

    print('\n✓ PC 端发版完成 v%s' % ver)
    print('  清单：%s' % MANIFEST_URL)
    if manifest.get('pc', {}).get('hot'):
        print('  补丁：%s' % manifest['pc']['hot']['url'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
