# -*- coding: utf-8 -*-
"""fix_venv_cfg.py · 把两个 venv 的 `pyvenv.cfg` 按**当前位置**重写（UTF-8，幂等）

为什么非要有这个文件（2026-10-03 踩了两轮，别删）
--------------------------------------------------
1. `pyvenv.cfg` 里的 `home` 是**打包时的绝对路径** ⇒ 包一搬家（解压到别处 / 发给朋友）
   就 `No Python at '…'`（退出码 103），什么都起不来。
2. 想"每次启动自动改"，最自然的写法是 `启动.bat` 里用 `echo > pyvenv.cfg` —— **但那一定错**：
   cmd 的 `echo` 按**系统 ANSI 码页**写文件（中文系统 = GBK），
   而 **Python 3.11 读 `pyvenv.cfg` 是按 UTF-8 解码的** ⇒ 路径里的中文被解成 `?`
   ⇒ 照样 `No Python at 'C:\\…\\????\\python311\\python.exe'` ✗✗
   （`chcp 65001` 也不保险：双击场景下 cmd 用的是系统 ACP，实测仍写 GBK）

⇒ 解法：用**基础解释器** `python311\\python.exe` 来写这个文件 ——
   它是独立解释器（**不会去读 pyvenv.cfg**，所以不存在"先有鸡还是先有蛋"），
   而且它按 Python 的规则写 UTF-8 ✓ 完全可控。

调用（由 `启动.bat` 每次启动时执行，见 tools/pkg_launcher.bat）：
    "%~dp0python311\\python.exe" "%~dp0fix_venv_cfg.py"
"""
import io
import os

ROOT = os.path.dirname(os.path.abspath(__file__))       # 包根（本文件在包根）
PY311 = os.path.join(ROOT, 'python311')
VER = '3.11.9'

BODY = ('home = %s\r\n'
        'include-system-site-packages = false\r\n'
        'version = %s\r\n'
        'executable = %s\r\n')

# 启动时的中文提示（用**户双击 启动.bat 时在 cmd 窗口里看到的那段**）
# ⚠ 为什么由 Python 打、不写在 启动.bat 里：
#   cmd 按**控制台 ANSI 码页**解析 .bat，bat 里出现非 ASCII 就会拆断行、
#   把后面的命令吃掉（2026-10-03 为此debug了两轮，模板现已强制纯 ASCII）✗
#   ⇒ 中文提示只能由 Python 输出：Python 对 Windows 控制台走 UTF-16 接口
#     （PEP 528），中文在任何码页下都正常 ✓
BANNER = '''============================================
  幻想少女公会 - 自动探索
============================================

请先：1) 打开 MuMu 模拟器  2) 进游戏停在「选图界面」
      3) 分辨率设 720x1280

马上就要打开操作窗口（几秒后会弹出）...
'''


def banner():
    try:
        print(BANNER)
    except Exception:                   # noqa: BLE001  （控制台编码异常也别炸）
        pass


def main():
    banner()                            # 启动提示（与原 启动.bat 里那段中文一致）
    done = []
    for rel in ('venv', '_maa_venv'):
        d = os.path.join(ROOT, rel)
        if not os.path.isdir(d):
            continue
        cfg = os.path.join(d, 'pyvenv.cfg')
        try:
            # ⚠ newline='' ⇒ 不做换行转换（上面已手写 \r\n）
            with io.open(cfg, 'w', encoding='utf-8', newline='') as f:
                f.write(BODY % (PY311, VER, os.path.join(PY311, 'python.exe')))
            done.append(rel)
        except Exception as e:                          # noqa: BLE001
            print('fix_venv_cfg: 写 %s 失败：%r' % (cfg, e))
    if done:
        print('fix_venv_cfg: 已按当前位置重写 %s 的 pyvenv.cfg（UTF-8）' % '/'.join(done))
    else:
        print('fix_venv_cfg: 没找到 venv/_maa_venv（跳过）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
