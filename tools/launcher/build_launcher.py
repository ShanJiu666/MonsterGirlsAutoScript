# -*- coding: utf-8 -*-
"""build_launcher.py · 编译 Windows 原生启动器 MGAS.exe（零安装）

为什么要自己编：
  · PyInstaller / cx_Freeze 都要 `pip install`，而本机 venv 里没有
  · 系统自带 .NET Framework 的 `csc.exe` 就能编出**免运行时依赖**的 exe
  · 启动器只有 8.5 KB，且**不含业务逻辑**（逻辑全在 Python 侧，便于热更新）

产物：tools/launcher/MGAS.exe

用法：
    python tools/launcher/build_launcher.py
"""
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
    if not os.path.isfile(SRC):
        print('❌ 找不到源码：%s' % SRC)
        return 2
    csc = find_csc()
    if not csc:
        print('❌ 找不到 csc.exe（.NET Framework 编译器）')
        print('   Win10/11 一般自带；若确实没有 ⇒ 装 .NET Framework 4.x 或改用 PyInstaller')
        return 3

    print('编译器：%s' % csc)
    cmd = [csc, '/nologo',
           '/target:winexe',            # 无控制台窗口
           '/platform:anycpu',
           '/optimize+',
           '/codepage:65001',           # UTF-8 源码
           '/out:' + OUT,
           '/r:System.Windows.Forms.dll',
           '/r:System.Drawing.dll']
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

    if r.returncode == 0 and os.path.isfile(OUT):
        print('✓ 已生成 %s（%.1f KB）' % (OUT, os.path.getsize(OUT) / 1024))
        return 0
    print('❌ 编译失败（exit %d）' % r.returncode)
    return 4


if __name__ == '__main__':
    sys.exit(main())
