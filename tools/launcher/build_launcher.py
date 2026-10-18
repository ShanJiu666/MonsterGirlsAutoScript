# -*- coding: utf-8 -*-
"""build_launcher.py · 编译 Windows 原生启动器 MGAS.exe（零安装）

为什么要自己编：
  · PyInstaller / cx_Freeze 都要 `pip install`，而本机 venv 里没有
  · 系统自带 .NET Framework 的 `csc.exe` 就能编出**免运行时依赖**的 exe
  · 启动器只有 20 KB 左右，且**不含业务逻辑**（逻辑全在 Python 侧，便于热更新）

产物：
    python tools/launcher/build_launcher.py         ⇒ MGAS.exe      （发朋友 = 朋友版）
    python tools/launcher/build_launcher.py --dev   ⇒ MGAS-dev.exe  （**自用**，开存图）

⭐⭐⭐ 2026-10-18 新增 `--dev`（用户口径：「以发布仓为唯一源，**我自用的时候要
   开启存图功能**」＋「能不能全自动，**我的启动器弄特殊一点**」）
  ---- 为什么要两个 exe ----
    一个包两用：自用要看帧（存图，≈0.7MB/图），朋友不该存（几十张就撑爆硬盘）。
    原来只能手工删 `friend_mode.flag` 或设环境变量 ⇒ **每次重下/更新都得重搞** ✗
  ---- 做法 ----
    `--dev` 编译时加 `/define:MGAS_DEV` ⇒ 那份 exe 里**多两行**设
    `MAPBOT_FRIEND=0`（⇒ `IS_FRIEND=False` ⇒ 存图开 + 精确规划开）
    朋友版**不含这两行的字节** ⇒ 照旧按 `friend_mode.flag` 走 ✓
  ⚠ `--dev` 的产物**自动改名 `MGAS-dev.exe`**，绝不覆盖要发布的 `MGAS.exe` ✓
  ⚠ 别把 `MGAS-dev.exe` 传上 GitHub（`.gitignore` 已挡）
"""
import argparse
import glob
import io
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'MGASLauncher.cs')
OUT = os.path.join(HERE, 'MGAS.exe')
OUT_DEV = os.path.join(HERE, 'MGAS-dev.exe')
ICON = os.path.join(HERE, 'MGAS.ico')

# 系统自带 csc（.NET Framework 4.x；Win10/11 默认都有）
CSC_CANDIDATES = [
    r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe',
    r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe',
]


def find_csc():
    for p in CSC_CANDIDATES:
        if os.path.isfile(p):
            return p
    # 兜底：搜 Framework64 下任意版本的 csc
    for pat in (r'C:\Windows\Microsoft.NET\Framework64\v*\csc.exe',
                r'C:\Windows\Microsoft.NET\Framework\v*\csc.exe'):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--dev', action='store_true',
                    help='编**自用版**（MGAS-dev.exe）：带 MAPBOT_FRIEND=0 ⇒ 开存图')
    a = ap.parse_args()

    if not os.path.isfile(SRC):
        print('❌ 找不到源码：%s' % SRC)
        return 2
    csc = find_csc()
    if not csc:
        print('❌ 找不到 csc.exe（.NET Framework 编译器）')
        print('   Win10/11 一般自带；若确实没有 ⇒ 装 .NET Framework 4.x 或改用 PyInstaller')
        return 3

    out_path = OUT_DEV if a.dev else OUT
    print('模式：%s' % ('⭐ 自用版（存图开 / 精确规划开）' if a.dev
                       else '朋友版（默认不存图）'))
    print('编译器：%s' % csc)
    cmd = [csc, '/nologo',
           '/target:winexe',            # 无控制台窗口
           '/platform:anycpu',
           '/optimize+',
           '/codepage:65001',           # UTF-8 源码
           '/out:' + out_path,
           '/r:System.Windows.Forms.dll',
           '/r:System.Drawing.dll']
    if a.dev:
        # ⚠ 只在自用版注入 —— 朋友版的 exe 里**不会有这段字节** ✓
        cmd.append('/define:MGAS_DEV')
    # 图标（可缺：缺了也能编，只是用系统默认图标）
    if os.path.isfile(ICON):
        cmd += ['/win32icon:' + ICON]
        print('图标：%s（%.1f KB）' % (os.path.basename(ICON),
                                      os.path.getsize(ICON) / 1024))
    else:
        print('图标：⚠ 缺 %s ⇒ 用系统默认图标' % os.path.basename(ICON))
        print('      先跑 python tools\\launcher\\make_exe_icon.py')
    cmd.append(SRC)
    r = subprocess.run(cmd, capture_output=True)
    out = (r.stdout or b'').decode('utf-8', 'replace') + \
          (r.stderr or b'').decode('utf-8', 'replace')
    if out.strip():
        print(out.strip())

    if r.returncode == 0 and os.path.isfile(out_path):
        print('✓ 已生成 %s（%.1f KB）'
              % (out_path, os.path.getsize(out_path) / 1024))
        if a.dev:
            print()
            print('  用法：把 MGAS-dev.exe 放进你的解压目录，双击它启动')
            print('        ⇒ 存图勾选会出现、默认开（每图存 runs/r_<时间>_0.png）')
            print('  ⚠ 别把它传到 GitHub（.gitignore 已挡 MGAS-dev.exe）')
        return 0
    print('❌ 编译失败（exit %d）' % r.returncode)
    return 4


if __name__ == '__main__':
    sys.exit(main())
