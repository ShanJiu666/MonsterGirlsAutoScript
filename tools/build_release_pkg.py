# -*- coding: utf-8 -*-
"""build_release_pkg.py · 打包成「下载后双击即用」的发布包

产物（默认 dist/）：
    MGAS-v<版本>-portable/          ← 目录（可直接运行）
    MGAS-v<版本>-portable.zip       ← 给网友下载的就是这个

包内布局：
    MGAS.exe                  ← 原生启动器（双击即开 GUI）
    幻想少女公会-自动探索.bat   ← 备用启动（exe 被拦时用）
    使用说明书.md / README.md / LICENSE / DISCLAIMER.md
    python311\\               ← 内嵌 Python（免安装）
    venv\\                    ← 依赖（numpy/cv2/onnxruntime/airtest…）
    core\\bot_gui.py / core\\explore_loop.py / …  ← 业务代码（在 core/ 里）
    templates\\ data\\         ← 识别资源
    tools\\ tests\\ devtools\\ docs\\ _verify\\

设计要点：
  ① **内嵌 Python**：不要求对方装 Python（这是「下载即用」的关键）
  ② **venv 的 pyvenv.cfg 改写成包内 python311** ⇒ 整个目录可搬家
  ③ **排除运行期与本机现场**：runs/ hot/ .git/ __pycache__/ logs/ _maa_venv/
  ④ 顶层放 `friend_mode.flag` ⇒ 启用「朋友版」默认（不含调试选项）

用法：
    python tools\\build_release_pkg.py                 # 全量打包
    python tools\\build_release_pkg.py --no-venv       # 只打代码+资源（体积小，需自备 Python）
    python tools\\build_release_pkg.py --no-zip        # 只出目录，不压缩
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ── 可被环境变量覆盖（别写死本机路径）─────────────────────────────────────
SRC_PY_DIST = os.environ.get('MGAS_SRC_PY_DIST') or ''
SRC_VENV = os.environ.get('MGAS_SRC_VENV') or ''
OUT_DIR = os.environ.get('MGAS_PKG_OUT') or os.path.join(REPO, 'dist')

# venv 里**不需要**进包的大件（体积省一半以上）
# ⚠ 但 `_distutils_hack` 不能删：site-packages 里的 `distutils-precedence.pth`
#   会在**每次启动 Python 时**导入它，删了包 ⇒ 每个模块加载前都刷一条
#   "Error processing line 1 of ... distutils-precedence.pth"（实测踩过）
VENV_DROP = ('__pycache__', 'pip', 'setuptools', 'pkg_resources',
             'wheel', 'onnxruntime\\test', 'torch',
             'torchvision', 'matplotlib')

# 这些 .pth 在打包后指向不存在的包 ⇒ 删掉（否则 Python 启动即告警）
VENV_DROP_PTH = ('distutils-precedence.pth',)

# ── MAA 极速截图（可选，但强烈建议带上）───────────────────────────────────
# 为什么要打包它：没有它 ⇒ 退回 adb 截图 0.33 s/张，**慢 25 倍**
#   （用户实际看到过这句提示，观感很差）
#
# ⚠ 关键实测结论：**不需要独立解释器**
#   本机那份 `_maa_venv` 里 numpy 是 2.x，看似与主环境 1.26 冲突；
#   但我实测 `MaaFw 5.14.0` 在 **numpy 1.26.4** 下 `import maa` 完全正常
#   ⇒ 直接把 `maa` / `MaaAgentBinary` / `strenum` 三个目录并进
#     包内 `python311/Lib/site-packages` 即可（那里已经 1.26.4）
#
# 源目录可用 MGAS_MAA_SITE 覆盖
MAA_SITE = (os.environ.get('MGAS_MAA_SITE')
            or r'D:\MGAS\mapbot_pc\_maa_venv\Lib\site-packages')
MAA_PKGS = ('maa', 'MaaAgentBinary', 'strenum')

# 仓内不进包的东西（运行期 / 本机现场 / 版本控制）
REPO_DROP_DIRS = ('.git', 'runs', 'hot', 'logs', 'dist', '__pycache__',
                  '_maa_venv', 'venv', '.venv', 'node_modules')
# ⚠ 这里只放**仓根**才该排除的东西。
#   以前写裸 `'_ocr_tmp.png'` ⇒ copy_tree 按**文件名**匹配 ⇒
#   `_verify/_ocr_tmp.png`（门禁语料）被一起排除 ⇒ 仓库与压缩包不一致 ✗
#   ⇒ 现在 copy_tree 对 drop_files 支持 `'/xxx'` 前缀表示"仅仓根"
REPO_DROP_FILES = ('/_ocr_tmp.png',   # 只排除仓根那份（运行期临时文件）
                   '/friend_mode.flag',  # 仓根那份是开发机状态，包里另放空文件
                   '/MGAS_dbg.exe')


def size_mb(p):
    if os.path.isfile(p):
        return os.path.getsize(p) / 1e6
    t = 0
    for dp, _dn, fns in os.walk(p):
        for f in fns:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t / 1e6


def copy_tree(src, dst, drop_dirs=(), drop_files=(), skip_ext=()):
    """复制目录（跳过指定项）。返回复制的文件数。

    `drop_files` 支持两种写法：
      · `'name.png'`   —— 匹配**任意层级**的同名文件（少用，容易误伤）
      · `'/name.png'`  —— **只匹配 src 根目录**下那份（推荐 —— 目录整理后
        子目录里常有同名文件，裸名字会把它们一起排除掉，实测踩过）
    """
    root_only = {f[1:] for f in drop_files if f.startswith('/')}
    any_level = {f for f in drop_files if not f.startswith('/')}
    n = 0
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d not in drop_dirs]
        rel = os.path.relpath(dp, src)
        at_root = (rel == '.')
        out = dst if at_root else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for f in fns:
            if f in any_level:
                continue
            if at_root and f in root_only:
                continue
            if skip_ext and os.path.splitext(f)[1].lower() in skip_ext:
                continue
            try:
                shutil.copy2(os.path.join(dp, f), os.path.join(out, f))
                n += 1
            except (OSError, shutil.Error):
                pass
    return n


def find_py_dist():
    """找「基础 Python 发行版」目录（不含 venv）"""
    if SRC_PY_DIST and os.path.isdir(SRC_PY_DIST):
        return SRC_PY_DIST
    # 从当前解释器往上找（venv 里的话，找 base）
    exe = sys.executable
    # venv: <base>/... ; 直接发行版: <dist>/python.exe
    d = os.path.dirname(exe)
    if os.path.basename(d).lower() in ('scripts', 'bin'):
        d = os.path.dirname(d)
    # venv 根下若有 pyvenv.cfg，说明这是 venv，真正的 base 在 cfg 里
    cfg = os.path.join(d, 'pyvenv.cfg')
    if os.path.isfile(cfg):
        try:
            for line in io.open(cfg, encoding='utf-8', errors='replace'):
                if line.lower().startswith('home'):
                    home = line.split('=', 1)[1].strip()
                    # home 指向 .../python311 或 .../python311/Scripts
                    if os.path.basename(home).lower() in ('scripts', 'bin'):
                        home = os.path.dirname(home)
                    if os.path.isdir(home):
                        return home
        except Exception:               # noqa: BLE001
            pass
    return d


def find_venv():
    if SRC_VENV and os.path.isdir(SRC_VENV):
        return SRC_VENV
    exe = sys.executable
    d = os.path.dirname(exe)
    if os.path.basename(d).lower() in ('scripts', 'bin'):
        return os.path.dirname(d)
    return None


def write_pyvenv_cfg(pkg_root, venv_rel):
    """把 venv 的 pyvenv.cfg 的 home 改成包内 python311。

    ⚠⚠ 但**光改这里不够**（实测教训）：`pyvenv.cfg` 的 `home` 必须是**绝对路径**，
        Python 不接受相对路径（`No Python at '..\\..\\python311\\python.exe'`）。
        ⇒ 包一旦被移动到别的目录（= 网友解压到任何地方），venv 就**断了**，
          `sys.base_prefix` 仍指向打包机的原路径。

    ⇒ 所以正式发布包**不再用 venv**：依赖直接并进 `python311/Lib/site-packages`
      （那里由解释器自己算，天然可搬家）。本函数降级为「--keep-venv」调试模式用。
    """
    cfg = os.path.join(pkg_root, venv_rel, 'pyvenv.cfg')
    if not os.path.isfile(cfg):
        return False
    lines = []
    for line in io.open(cfg, encoding='utf-8', errors='replace').read().splitlines():
        k = line.split('=', 1)[0].strip().lower() if '=' in line else ''
        if k == 'command':
            continue                    # 丢掉（含开发机路径，对使用者无用）
        if k == 'home':
            lines.append('home = %s' % os.path.join(pkg_root, 'python311'))
        elif k == 'executable':
            lines.append('executable = %s'
                         % os.path.join(pkg_root, 'python311', 'python.exe'))
        elif k == 'base-prefix':
            lines.append('base-prefix = %s' % os.path.join(pkg_root, 'python311'))
        elif k == 'base-executable':
            lines.append('base-executable = %s'
                         % os.path.join(pkg_root, 'python311', 'python.exe'))
        else:
            lines.append(line)
    io.open(cfg, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')
    return True


def merge_deps_into_python(pkg_root, venv_src):
    """把 venv 的 site-packages **并进** python311/Lib/site-packages。

    为什么要这样（而不是带一个 venv）：
      venv 的可搬家性依赖 `pyvenv.cfg` 里**绝对路径**的 `home`，
      包一移动就报 `No Python at '...'`。
      而 `python311/Lib/site-packages` 是解释器**自己按可执行文件位置算的**
      ⇒ 整个目录复制到任何地方都能跑 ✓（已用 clean-room 复制实测过）
    """
    dst = os.path.join(pkg_root, 'python311', 'Lib', 'site-packages')
    os.makedirs(dst, exist_ok=True)
    src = None
    for cand in (os.path.join(venv_src, 'Lib', 'site-packages'),
                 os.path.join(venv_src, 'lib', 'site-packages')):
        if os.path.isdir(cand):
            src = cand
            break
    if not src:
        return 0
    n = copy_tree(src, dst, drop_dirs=tuple(VENV_DROP),
                  drop_files=('pyvenv.cfg',) + tuple(VENV_DROP_PTH))
    return n


def scrub_dev_paths(pkg_root):
    """把包内残留的「开发机绝对路径」清掉（activate 脚本里的 VIRTUAL_ENV 等）。

    这些是 venv 创建时写死的，对使用者无用，且会泄露本机目录结构。
    """
    pats = [
        (re.compile(r'C:\\+Users\\+PC[^"\'\r\n]*?\.workbuddy[^"\'\r\n]*', re.I), ''),
        (re.compile(r'C:/+Users/+PC[^"\'\r\n]*?\.workbuddy[^"\'\r\n]*', re.I), ''),
        (re.compile(r'D:\\+MGAS\\+(?:mapbot_pc|_release_pc)[^"\'\r\n]*', re.I), ''),
    ]
    n = 0
    for rel in ('Scripts/activate', 'Scripts/activate.bat',
                'Scripts/activate.ps1', 'Scripts/activate_this.py'):
        p = os.path.join(pkg_root, 'venv', rel.replace('/', os.sep))
        if not os.path.isfile(p):
            continue
        try:
            s = io.open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        o = s
        for pat, rep in pats:
            s = pat.sub(rep, s)
        if s != o:
            io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-venv', action='store_true',
                    help='不内嵌 venv（包会小很多，但对方要自己装依赖）')
    ap.add_argument('--no-python', action='store_true',
                    help='不内嵌 Python 发行版（对方要自己装 Python）')
    ap.add_argument('--no-zip', action='store_true', help='只出目录，不压缩')
    ap.add_argument('--no-maa', action='store_true',
                    help='不打 MAA 极速截图组件（省 ~75MB，但截图退回 adb ⇒ 慢 25 倍）')
    ap.add_argument('--keep-venv', action='store_true',
                    help='⚠ 调试用：保留 venv（依赖放在 venv 里）。'
                         'venv 的 pyvenv.cfg 必须写绝对路径 ⇒ **包不可搬家**，'
                         '只适合在本机验证。正式发布别用。')
    ap.add_argument('--out', default=OUT_DIR)
    a = ap.parse_args()

    t0 = time.time()
    ver = '0.0'
    pv = os.path.join(REPO, 'PC_VERSION')
    if os.path.isfile(pv):
        ver = io.open(pv, encoding='utf-8', errors='replace').read().strip() or '0.0'

    name = 'MGAS-v%s-portable' % ver
    pkg = os.path.join(a.out, name)
    if os.path.isdir(pkg):
        print('清理旧包…')
        shutil.rmtree(pkg, ignore_errors=True)
    os.makedirs(pkg, exist_ok=True)

    print('=' * 66)
    print('打包 MGAS v%s → %s' % (ver, pkg))
    print('=' * 66)

    # ① 业务代码 + 资源
    print('\n[1/6] 复制代码与资源…')
    n = copy_tree(REPO, pkg, drop_dirs=REPO_DROP_DIRS, drop_files=REPO_DROP_FILES)
    print('  ✓ %d 个文件' % n)

    # ② 内嵌 Python
    if not a.no_python:
        dist = find_py_dist()
        print('\n[2/6] 内嵌 Python：%s' % dist)
        if dist and os.path.isdir(dist):
            m = copy_tree(dist, os.path.join(pkg, 'python311'),
                          drop_dirs=('test', 'tests', 'Tools', 'Doc', 'docs',
                                     'Lib\\test', 'Lib\\idlelib', 'Lib\\tkinter\\test',
                                     '__pycache__'),
                          skip_ext=('.pdb',))
            print('  ✓ %d 个文件 · %.0f MB' % (m, size_mb(os.path.join(pkg, 'python311'))))
        else:
            print('  ⚠ 找不到 Python 发行版 ⇒ 跳过（对方需自装 Python）')
    else:
        print('\n[2/6] 跳过内嵌 Python（--no-python）')

    # ③ 内嵌依赖
    #   ★ 关键决定：**不带宽 venv**，而是把依赖并进 `python311/Lib/site-packages`
    #     理由见 merge_deps_into_python() 的 docstring：
    #       venv 的 pyvenv.cfg 必须写绝对路径 ⇒ 包一移动就 `No Python at ...`
    #       （已实测：复制到别的目录后 base_prefix 仍指向打包机原路径）
    #     而 python311 的 site-packages 由解释器按自身位置算 ⇒ 天然可搬家 ✓
    if not a.no_venv:
        venv = find_venv()
        print('\n[3/6] 内嵌依赖：%s' % (venv or '(找不到)'))
        if venv and os.path.isdir(venv):
            if a.keep_venv:
                # 调试用：保留 venv（不可搬家，仅本机验证）
                m = copy_tree(venv, os.path.join(pkg, 'venv'),
                              drop_dirs=tuple(VENV_DROP),
                              drop_files=('pyvenv.cfg',))
                cfg_src = os.path.join(venv, 'pyvenv.cfg')
                if os.path.isfile(cfg_src):
                    shutil.copy2(cfg_src, os.path.join(pkg, 'venv', 'pyvenv.cfg'))
                write_pyvenv_cfg(pkg, 'venv')
                print('  ⚠ --keep-venv：保留 venv（**不可搬家**，只本机可跑）')
                print('  ✓ %d 个文件 · %.0f MB'
                      % (m, size_mb(os.path.join(pkg, 'venv'))))
            else:
                m = merge_deps_into_python(pkg, venv)
                sp = os.path.join(pkg, 'python311', 'Lib', 'site-packages')
                print('  ✓ 依赖并入 python311/Lib/site-packages')
                print('    %d 个文件 · %.0f MB（整个包可任意搬家 ✓）'
                      % (m, size_mb(sp)))
                # 清掉残留的 .pth（指向已剔除的包会让 python 每次启动刷告警）
                for pth in VENV_DROP_PTH:
                    fp = os.path.join(sp, pth)
                    if os.path.isfile(fp):
                        os.remove(fp)
                        print('    · 已删 %s（其目标包未进包）' % pth)
                # 顺手清掉激活脚本里的开发机路径（若带 venv 才有）
                scrub_dev_paths(pkg)

                # ── MAA 极速截图（并进同一个 site-packages）──────────────
                #   没有它 ⇒ 退回 adb 0.33 s/张（慢 25 倍），网友会看到
                #   「⚠⚠ 没找到 MAA 极速截图环境」的提示
                print('\n      MAA 极速截图（可选组件，但影响 25 倍速度）：')
                if not a.no_maa:
                    maa_ok = 0
                    for pkgname in MAA_PKGS:
                        src_pkg = os.path.join(MAA_SITE, pkgname)
                        if not os.path.isdir(src_pkg):
                            print('        · 跳过 %s（源里没有）' % pkgname)
                            continue
                        dst_pkg = os.path.join(sp, pkgname)
                        if os.path.isdir(dst_pkg):
                            shutil.rmtree(dst_pkg, ignore_errors=True)
                        n2 = copy_tree(src_pkg, dst_pkg,
                                       drop_dirs=('__pycache__',))
                        sz = size_mb(dst_pkg)
                        print('        ✓ %-16s %6.1f MB（%d 文件）'
                              % (pkgname, sz, n2))
                        maa_ok += 1
                    if maa_ok == 0:
                        print('        ⚠ 一个都没打进 ⇒ 发布包无极速截图（慢 25 倍）')
                        print('          先建：python -m venv _maa_venv && '
                              '_maa_venv\\Scripts\\python -m pip install MaaFw==5.14.0')
                else:
                    print('        （--no-maa：跳过）')
        else:
            print('  ⚠ 跳过（对方需自己 pip install -r requirements.txt）')
    else:
        print('\n[3/6] 跳过内嵌依赖（--no-venv）')

    # ④ 启动器
    print('\n[4/6] 启动器…')
    exe_src = os.path.join(REPO, 'tools', 'launcher', 'MGAS.exe')
    if os.path.isfile(exe_src):
        shutil.copy2(exe_src, os.path.join(pkg, 'MGAS.exe'))
        print('  ✓ MGAS.exe')
    else:
        print('  ⚠ 缺 tools/launcher/MGAS.exe（先跑 tools/launcher/build_launcher.py）')

    # ⭐ 2026-10-18 **自用版启动器也要进包**（用户：「dist那个是我的版本吗」
    #   「我自用的时候要开启存图功能」）
    #   ---- 为什么放进发布包里，不怕发错 ----
    #     `MGAS-dev.exe` 只是**多一个文件**；朋友双击 `MGAS.exe` 照旧是朋友版 ✓
    #     而用户自己双击 `MGAS-dev.exe` ⇒ `MAPBOT_FRIEND=0` ⇒ 存图开 ✓
    #   ⚠ 它**不进 git**（`.gitignore` 已挡 `MGAS-dev.exe`），只在本地打包时拷进去
    #   ⚠ 打包前会 `Remove-Item dist` ⇒ 不在这里补拷，用户那份每次都会消失 ✗
    dev_src = os.path.join(REPO, 'tools', 'launcher', 'MGAS-dev.exe')
    if os.path.isfile(dev_src):
        try:
            shutil.copy2(dev_src, os.path.join(pkg, 'MGAS-dev.exe'))
            print('  ✓ MGAS-dev.exe（自用版：开存图 + 精确规划）')
        except Exception as e:              # noqa: BLE001
            print('  ⚠ MGAS-dev.exe 拷不进去（%r）⇒ 自用版要手工放' % (e,))
    else:
        print('  · 没有 MGAS-dev.exe（自用版）⇒ 跳过')
        print('    （要的话：python tools\\launcher\\build_launcher.py --dev）')

    bat = os.path.join(pkg, '幻想少女公会-自动探索.bat')
    io.open(bat, 'w', encoding='utf-8', newline='\r\n').write(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        'cd /d "%~dp0"\r\n'
        'set PYTHONIOENCODING=utf-8\r\n'
        'set PYTHONUTF8=1\r\n'
        'if exist "venv\\Scripts\\python.exe" (\r\n'
        '  "venv\\Scripts\\python.exe" core\\bot_gui.py\r\n'
        ') else (\r\n'
        '  python core\\bot_gui.py\r\n'
        ')\r\n'
        'if errorlevel 1 pause\r\n')
    print('  ✓ 幻想少女公会-自动探索.bat（备用启动）')

    # ④b 出包即体检（缺依赖 / .pth 指向不存在的模块 / sys.path 跑到包外）
    #     用户实报过「解压没完就双击 ⇒ tkinter 缺失」和「pywin32_bootstrap 报错」，
    #     这两类都应该在**出包时**拦下来，而不是让用户去猜
    print('\n[4b] 完整性体检…')
    audit = os.path.join(HERE, 'audit_pkg_integrity.py')
    if os.path.isfile(audit):
        r = subprocess.run([sys.executable, audit, pkg], capture_output=True)
        out = ((r.stdout or b'').decode('utf-8', 'replace')
               + (r.stderr or b'').decode('utf-8', 'replace'))
        tail = [l for l in out.splitlines()
                if l.startswith('  [FAIL]') or '失败 ' in l]
        for l in tail:
            print('  ' + l.strip())
        if r.returncode != 0:
            print('  ⚠⚠ 体检有失败项 —— **这个包发出去会起不来**，先修再发')
        else:
            print('  ✓ 体检通过（依赖齐全、.pth 无悬空引用、sys.path 全在包内）')
    else:
        print('  （缺 tools/audit_pkg_integrity.py，跳过）')

    # ⑤ friend_mode.flag（朋友版默认）+ 面向使用者的说明
    flag = os.path.join(pkg, 'friend_mode.flag')
    io.open(flag, 'w', encoding='utf-8').write('')
    print('\n[5/6] 已放 friend_mode.flag（启用朋友版默认）')

    # 面向下载者的说明（覆盖 README，讲「双击就能用」而不是「怎么装依赖」）
    user_doc = os.path.join(HERE, 'launcher', '使用说明-发布包.md')
    if os.path.isfile(user_doc):
        shutil.copy2(user_doc, os.path.join(pkg, 'README.md'))
        print('  ✓ README.md 换成面向使用者的版本（双击即用）')

    # 清掉 venv 激活脚本里残留的开发机路径（VIRTUAL_ENV 等）
    n_scrub = scrub_dev_paths(pkg)
    if n_scrub:
        print('  · 已清理 %d 个激活脚本里的开发机路径' % n_scrub)

    # ⑥ 压缩
    if not a.no_zip:
        print('\n[6/6] 压缩…')
        zpath = os.path.join(a.out, name + '.zip')
        if os.path.isfile(zpath):
            os.remove(zpath)
        cnt = 0
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for dp, dns, fns in os.walk(pkg):
                dns[:] = [d for d in dns if d != '__pycache__']
                for f in fns:
                    fp = os.path.join(dp, f)
                    arc = os.path.join(name, os.path.relpath(fp, pkg))
                    try:
                        z.write(fp, arc)
                        cnt += 1
                    except (OSError, zipfile.BadZipFile):
                        pass
        print('  ✓ %s' % zpath)
        print('    %d 个文件 · %.0f MB' % (cnt, size_mb(zpath)))
    else:
        print('\n[6/6] 跳过压缩（--no-zip）')

    print('\n' + '=' * 66)
    print('完成，用时 %.0f 秒' % (time.time() - t0))
    print('  目录：%s  (%.0f MB)' % (pkg, size_mb(pkg)))
    print('=' * 66)


if __name__ == '__main__':
    main()
