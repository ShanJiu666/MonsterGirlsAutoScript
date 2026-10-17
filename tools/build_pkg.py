# -*- coding: utf-8 -*-
"""build_pkg.py · 给朋友打包「幻想少女公会 · 自动探索」（PC 端整包）

    python mapbot_pc\\tools\\build_pkg.py          # 打整包（复制 + 压缩，约 4 分钟）

产物（默认落在 `<容器临时区>`）：
    自动探索\\                     ← 解压后的目录（963 MB）
    幻想少女公会-自动探索-v<版本>.zip ← 发朋友的就是这个（~394 MB）

它做的事
--------
    ① 复制基础 Python311（砍 test/Tools/Doc/idle）② 复制主 venv（砍 onnx/pip/ffmpeg-DLL）
    ③ 复制 MAA 快速截图 sidecar  ④ 复制代码 + templates + data（**排除 runs/.git/hot/_verify**）
    ⑤ 改写两个 `pyvenv.cfg` 的 home → 包内 python311（**可搬家的关键**）
    ⑥ 包根放 `friend_mode.flag` + `bootstrap.py` + `启动.bat` + 成品说明书
    ⑦ 压缩成 zip

⭐⭐ 2026-10-03 起的两条硬约定（**改这个脚本前必读**）
----------------------------------------------------
1. **朋友版差异不再靠改源码**，只放一个 `friend_mode.flag`（见 `mapbot_pc/friend_mode.py`）。
   以前这里对 `bot_gui.py`/`explore_loop.py` 做**字符串替换** —— 有了逻辑热更之后那立刻变
   bug：补丁是按**仓库源码**打的（= 开发版），一落地就把朋友版冲回开发版 ✗✗
2. **`hot/` 必须排除**：那是**本机**的热更现场（出厂备份 / 坏包取证 / state），
   打进包里会把我的现场带给朋友（而且补丁 id 对不上）。

⚠ 路径**全部可用环境变量覆盖**（别改代码 —— AGENTS.md 里"写死路径"是这个项目反复踩的坑）：
    `MAPBOT_SRC_PY` / `MAPBOT_SRC_VENV` / `MAPBOT_SRC_MAA` / `MAPBOT_SRC_DATA`
    `MAPBOT_PKG_OUT`（产物目录）、`MGAS` 自动从本文件位置推出来
"""
import io
import os
import shutil
import subprocess
import sys
import time
import zipfile

try:                                    # GBK 控制台打中文/✓ 会炸
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass

# ───────────────────────── 路径（默认从本文件位置推，可被环境变量覆盖）─────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))            # <仓>/tools
SRC_REPO = os.path.dirname(HERE)                             # <仓>（本仓）
MGAS = os.path.dirname(SRC_REPO)                             # 上一级目录（打包输出放这里）

SRC_PY = (os.environ.get('MAPBOT_SRC_PY')
          or sys.executable)
SRC_VENV = (os.environ.get('MAPBOT_SRC_VENV')
            or '')
SRC_MAA = os.environ.get('MAPBOT_SRC_MAA') or os.path.join(SRC_REPO, '_maa_venv')
SRC_DATA = os.environ.get('MAPBOT_SRC_DATA') or os.path.join(SRC_REPO, 'data')
OUT_DIR = (os.environ.get('MAPBOT_PKG_OUT')
           or os.path.join(SRC_REPO, 'dist'))

PKG = os.path.join(OUT_DIR, '自动探索')
try:
    PC_VER = io.open(os.path.join(SRC_REPO, 'PC_VERSION'), encoding='utf-8').read().strip() or '0.0'
except Exception:                       # noqa: BLE001
    PC_VER = '0.0'
# ⭐ zip 名字带**整包版本号**：热更清单里的 `minPack` 判据就是比这个号，
#   朋友说"我这是几版"时一眼能对上 ✓
ZIP = os.path.join(OUT_DIR, '幻想少女公会-自动探索-v%s.zip' % PC_VER)

DROP_FROM_PY = ['Lib\\test', 'Lib\\idlelib', 'Tools', 'Doc', 'Lib\\lib2to3',
                'Lib\\ensurepip', 'Lib\\turtledemo', 'Lib\\tkinter\\test']
DROP_SITE = ['onnx', 'pip', 'setuptools', '_distutils_hack',
             'pkg_resources', 'wheel']

# 包里**必须**存在于包根的文件（打完核对；缺了朋友起不来）
NEED_AT_ROOT = ('bootstrap.py', 'fix_venv_cfg.py', 'friend_mode.flag', '启动.bat', '使用说明书.md')
NEED_IN_CODE = ('bot_gui.py', 'explore_loop.py', 'hotupdate.py', 'friend_mode.py', 'PC_VERSION')


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def rc_ok(rc):
    return rc == 0 or rc == 1 or (2 <= rc <= 7)      # robocopy 0~7 都算成功


def size_mb(p):
    t = 0
    for root, _d, fs in os.walk(p):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(root, f))
            except Exception:           # noqa: BLE001
                pass
    return t / 1048576.0


def copy(src, dst, xd=None, xf=None):
    os.makedirs(dst, exist_ok=True)
    cmd = ['robocopy', src, dst, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1']
    if xd:
        cmd += ['/XD'] + xd
    if xf:
        cmd += ['/XF'] + xf
    rc, out = run(cmd)
    if not rc_ok(rc):
        print('   ⚠ robocopy 失败 rc=%d %s' % (rc, out[-200:]))
        return False
    return True


# ───────────────────────── ⓪ 体检（**必须在删旧包之前**）─────────────────────────

print('== 打包前体检 ==')
_bad = []
for _label, _p in (('基础 Python', SRC_PY), ('主 venv', SRC_VENV), ('MAA sidecar', SRC_MAA),
                   ('仓（mapbot_pc）', SRC_REPO)):
    _ok = os.path.isdir(_p)
    print('   %-16s %s  %s' % (_label, '✓' if _ok else '✗', _p))
    if not _ok and _label != 'MAA sidecar':      # MAA 缺了只是退化（慢 15%），不算失败
        _bad.append(_p)
for _f in NEED_IN_CODE:
    _p = os.path.join(SRC_REPO, _f)
    if not os.path.isfile(_p):
        print('   ✗ 仓里缺关键文件：%s（热更/启动会坏）' % _p)
        _bad.append(_p)
if not os.path.isdir(SRC_DATA):
    print('   ⚠ 没有 %s（data 阶段会跳过）' % SRC_DATA)
if _bad:
    print('\n✗ 体检不过 ⇒ **没有动任何东西就退出**（别在缺料时把旧包删了 ✗）')
    sys.exit(1)
print('   ⇒ 体检通过，版本 v%s，产物目录 %s' % (PC_VER, OUT_DIR))

# ───────────────────────── ① ~ ⑥ ─────────────────────────

t0 = time.time()
if os.path.isdir(PKG):
    print('\n清掉旧包 …')
    shutil.rmtree(PKG, ignore_errors=True)
os.makedirs(PKG, exist_ok=True)
print('目标：%s' % PKG)

# ① 基础 Python（砍掉测试/文档/idle 等）
print('\n[1/7] 复制基础 Python（砍 test/Tools/Doc…）…')
if not copy(SRC_PY, os.path.join(PKG, 'python311'), xf=['*.pdb']):
    sys.exit(1)
for rel in DROP_FROM_PY:
    shutil.rmtree(os.path.join(PKG, 'python311', rel), ignore_errors=True)
print('   = %.0f MB' % size_mb(os.path.join(PKG, 'python311')))

# ② 主环境（砍 onnx/pip/ffmpeg）
print('\n[2/7] 复制主环境（砍 onnx/pip/ffmpeg-DLL）…')
vdst = os.path.join(PKG, 'venv')
if not copy(SRC_VENV, vdst, xd=['__pycache__']):
    sys.exit(1)
sp = os.path.join(vdst, 'Lib', 'site-packages')
for n in DROP_SITE:
    shutil.rmtree(os.path.join(sp, n), ignore_errors=True)
# ⚠⭐ 2026-10-03：`_distutils_hack` 被上面砍了，但 `distutils-precedence.pth` 还在
#   ⇒ **每起一个 python 子进程**都往 stderr 打一行
#     `ModuleNotFoundError: No module named '_distutils_hack'`
#   ⇒ 曾在真包端到端测试里把热更的"语法检查"误判成失败、补丁被拉黑 ✗✗
#     （判定已改成只看 returncode，但噪音本身也该清掉 ✓）
for _n in ('distutils-precedence.pth',):
    try:
        os.remove(os.path.join(sp, _n))
    except Exception:                   # noqa: BLE001
        pass
for root, _d, fs in os.walk(os.path.join(sp, 'cv2')):
    for f in fs:
        if 'ffmpeg' in f.lower() and f.lower().endswith('.dll'):
            os.remove(os.path.join(root, f))
for target in (os.path.join(vdst, 'Scripts', 'pip.exe'),
               os.path.join(vdst, 'Scripts', 'pip3.exe')):
    try:
        os.remove(target)
    except Exception:                   # noqa: BLE001
        pass

# ③ MAA 快速截图服务
print('\n[3/7] 复制 MAA 快速截图服务 …')
if not copy(SRC_MAA, os.path.join(PKG, '_maa_venv'), xd=['__pycache__']):
    print('   ⚠ 没复制成功（可继续，朋友会退化成慢速截图）')

# ④ 代码 + 模板（不含 runs/.git/_tmpman/_verify/_maa_venv/**hot**）
print('\n[4/7] 复制代码 + templates …')
code = os.path.join(PKG, 'mapbot_pc')
if not copy(SRC_REPO, code,
            xd=[os.path.join(SRC_REPO, 'runs'), os.path.join(SRC_REPO, '.git'),
                os.path.join(SRC_REPO, '_tmpman'), os.path.join(SRC_REPO, '_verify'),
                os.path.join(SRC_REPO, '_maa_venv'), os.path.join(SRC_REPO, 'hot'),
                '__pycache__'],
            xf=['*.log', '*.pyc', '_msg.tmp', '*.tmp']):
    sys.exit(1)
os.makedirs(os.path.join(code, 'runs'), exist_ok=True)
if os.path.isdir(SRC_DATA):
    copy(SRC_DATA, os.path.join(PKG, 'data'))
print('   mapbot_pc = %.0f MB ｜ data = %.0f MB'
      % (size_mb(code), size_mb(os.path.join(PKG, 'data'))))

# ⑤ 改写两个 venv 的 home ⇒ 指向包内 python311（可搬家的关键 ✓）
print('\n[5/7] 改写 pyvenv.cfg（home → 包内 python311）…')
for rel in ('venv', '_maa_venv'):
    cfg = os.path.join(PKG, rel, 'pyvenv.cfg')
    if not os.path.exists(cfg):
        continue
    lines = io.open(cfg, encoding='utf-8', errors='replace').read().split('\n')
    out = []
    for ln in lines:
        if ln.strip().lower().startswith('home'):
            out.append('home = %s' % os.path.join(PKG, 'python311'))
        elif ln.strip().lower().startswith('executable'):
            out.append('executable = %s' % os.path.join(PKG, 'python311', 'python.exe'))
        else:
            out.append(ln)
    io.open(cfg, 'w', encoding='utf-8').write('\n'.join(out))
    print('   %s ✓' % cfg)

# ⑥ 朋友模式 flag + bootstrap.py + 启动.bat + 说明书
print('\n[6/7] 朋友模式 flag + bootstrap.py + 启动.bat + 说明书 …')

# ⭐⭐ 朋友版差异**只靠这个 flag**（运行期读），不再改源码 —— 见文件头注释 1
_friend_flag = os.path.join(PKG, 'friend_mode.flag')
io.open(_friend_flag, 'w', encoding='utf-8').write(
    '此包为「朋友版」：默认关精确规划、不存图、窗口不显示这两个勾选框。\n'
    '删除本文件即恢复开发版默认值（正常别删）。\n')
print('   ✓ friend_mode.flag（朋友版开关，运行期读 ⇒ 不会被热更补丁冲掉）')

# bootstrap.py：**启动器**（更新 → 自检 → 起界面），放**包根**（与 venv/mapbot_pc 同级）
_boot_src = os.path.join(code, 'bootstrap.py')
if os.path.isfile(_boot_src):
    shutil.copy2(_boot_src, os.path.join(PKG, 'bootstrap.py'))
    print('   ✓ bootstrap.py（启动器：热更 → 自检 → 起界面）')
else:
    print('   ✗ 缺 mapbot_pc\\bootstrap.py ⇒ 包里的启动.bat 会失败！')
    sys.exit(1)

# 启动器的搭档：按当前位置把两个 venv 的 pyvenv.cfg 重写成 **UTF-8**
#   ⚠ 为什么必须用 Python 写而不是 bat 里 echo：Python 读 cfg 按 UTF-8，
#     而 cmd 的 echo 按系统 ANSI(GBK) 写 ⇒ 路径含中文就变 '?' ⇒ `No Python` ✗✗
#     （2026-10-03 为此debug了两轮，详见 tools/fix_venv_cfg.py 顶部注释）
_fix_src = os.path.join(HERE, 'fix_venv_cfg.py')
if os.path.isfile(_fix_src):
    shutil.copy2(_fix_src, os.path.join(PKG, 'fix_venv_cfg.py'))
    print('   ✓ fix_venv_cfg.py（每次启动按当前位置重写 pyvenv.cfg，UTF-8）')
else:
    print('   ✗ 缺 %s ⇒ 包搬到别处（尤其含中文路径）会起不来！' % _fix_src)
    sys.exit(1)

# 启动器：从仓里的模板拷，**必须以 GBK 写入** ——
#   cmd.exe 按**控制台 ANSI 码页**解析 .bat，UTF-8 的 bat 会拆断行结构，
#   把关键重定向整段吃掉（2026-10-03 为此debug了一整轮）✗
#   模板在仓里保持 UTF-8（便于维护/评审），打包时转码 ✓
_bat_src = os.path.join(HERE, 'pkg_launcher.bat')       # HERE = mapbot_pc/tools
if os.path.isfile(_bat_src):
    _txt = io.open(_bat_src, encoding='utf-8').read()
    _gbk = _txt.encode('gbk', 'replace').decode('gbk')
    if _gbk != _txt:            # 有 GBK 表示不了的字符（emoji 等）⇒ 会变 '?'，可能弄坏一行
        print('   ⚠ 模板里有 GBK 表示不了的字符（已替换成 ?）：'
              '请把 %s 的注释改成纯 ASCII' % os.path.basename(_bat_src))
    io.open(os.path.join(PKG, '启动.bat'), 'w', encoding='gbk', errors='replace',
            newline='\r\n').write(_txt)     # ⚠ GBK + CRLF 都是硬要求，别改成 utf-8/LF
    print('   ✓ 启动.bat（拷 tools\\pkg_launcher.bat，已转成 GBK 编码 + CRLF）')
else:
    print('   ✗ 缺 %s ⇒ 包里没有启动器！' % _bat_src)
    sys.exit(1)

# ⭐⭐ 说明书用**仓里的成品**（`使用说明书.md`，手工完善过：有 SmartScreen / 分辨率拒启说明）
#   以前这里内嵌的是**简版模板** ⇒ 重打包会把手写完善的那份**覆盖成简版** ✗
_src_readme = os.path.join(SRC_REPO, 'docs', '使用说明书.md')
if os.path.isfile(_src_readme):
    shutil.copy2(_src_readme, os.path.join(PKG, '使用说明书.md'))
    print('   ✓ 启动.bat ／ 使用说明书.md（拷仓里的成品版）')
else:
    print('   ⚠ 仓里缺 %s ⇒ 包里没有说明书' % _src_readme)

total = size_mb(PKG)
print('\n=== 打包完成，解压后 = %.0f MB，用时 %.1f 分钟 ===' % (total, (time.time() - t0) / 60))

# ⑦ 核对包根关键文件（**别等压缩完 394MB 才发现漏了**）
print('\n[7/7] 核对包根 …')
_missing = [f for f in NEED_AT_ROOT if not os.path.exists(os.path.join(PKG, f))]
_missing += ['mapbot_pc\\' + f for f in NEED_IN_CODE
             if not os.path.exists(os.path.join(code, f))]
if _missing:
    print('   ✗ 缺：%s' % '、'.join(_missing))
    sys.exit(1)
print('   ✓ %s 都在' % '、'.join(NEED_AT_ROOT))

# ⑧ 压缩（内置 ZipFile，比 Compress-Archive 快）
print('\n压缩中（zip，Windows 双击即可解压）…')
t1 = time.time()
if os.path.exists(ZIP):
    os.remove(ZIP)
with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, _d, fs in os.walk(PKG):
        for f in fs:
            fp = os.path.join(root, f)
            z.write(fp, os.path.relpath(fp, os.path.dirname(PKG)))
print('=== zip = %.0f MB，用时 %.1f 分钟 ===' % (os.path.getsize(ZIP) / 1048576.0,
                                                 (time.time() - t1) / 60))

# ⑨ 再按 zip 内容核对一遍（压错了/漏了顶层目录时能立刻发现）
with zipfile.ZipFile(ZIP) as z:
    _names = z.namelist()
_top = set(n.split('/')[1] for n in _names if n.startswith('自动探索/') and n.count('/') >= 1)
print('   zip 顶层：%s' % '、'.join(sorted(x for x in _top if x)))
for _f in NEED_AT_ROOT:
    _in = ('自动探索/' + _f) in _names
    print('   %s %s' % ('✓' if _in else '✗', _f))

print('\n成品：%s' % ZIP)
print('整包版本：v%s（热更清单里的 minPack 判据就是它；包里 PC_VERSION 同值）' % PC_VER)
print('\n⚠⚠ **发这个整包时，强烈建议同时发一个补丁**：')
print('    python mapbot_pc\\tools\\release_pc.py --notes "同整包 v%s"' % PC_VER)
print('   原因：朋友首次启动会去拉**线上最新补丁**并覆盖包内文件 —— 若线上那个补丁比')
print('   这个整包**旧**，等于把他的新代码降级 ✗（补丁比包新才是安全的）')
print('\n⚠ 只改了业务逻辑 ⇒ **不用重打包**，发补丁即可：'
      'python mapbot_pc\\tools\\release_pc.py --notes "…"')
print('⚠ 改了 bootstrap.py / hotupdate.py（引导层）或 venv 依赖 ⇒ 才必须重发这个整包')
