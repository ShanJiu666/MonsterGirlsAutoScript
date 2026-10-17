# -*- coding: utf-8 -*-
"""bootstrap.py · PC 端启动器：**更新 → 自检 → 起界面**（用户 2026-10-03：「桌面端怎么搞热更新」）

摆在哪
------
发布包里本文件在**包根**（与 `venv/` `python311/` `mapbot_pc/` 同级），`启动.bat` 调它；
开发机上也直接跑（`python mapbot_pc\\bootstrap.py`），两种摆法都能自己认出来。

它做四件事，顺序是硬约束
------------------------
    ① `hotupdate.boot_recover()`  —— 处理"上次覆盖后没起来"（连续 2 次 ⇒ 恢复出厂版）
    ② `hotupdate.apply_pending()` —— 把下载好的补丁落地（语法检查 → 备份 → 覆盖 → import 自检）
    ③ `hotupdate.auto_update()`   —— 静默下载新补丁（**下次启动生效**；没网就跳过）
    ④ `runpy.run_path(bot_gui.py)` —— **同进程**起界面（这样 GUI 起来后能调 confirm_alive）

⚠ 启动器**绝不能**因为热更失败而卡住：③ 的任何网络异常都被吞掉（`auto_update` 自己保证），
  ①② 整体也包了 try —— 最坏情况就是"这次不更新，照常起界面"。
  ⚠ 但 ② **不能**被吞掉成"覆盖了一半"：`apply_pending` 内部保证任何失败都恢复出厂版。

⚠ 引导层（本文件 + `hotupdate.py`）**不进补丁**（`hotupdate.BOOT_LAYER`）：
  更新器自己要稳；改它们走整包。
"""
import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _layout():
    """认两种摆法，返回 (包根 ROOT, 代码目录 PKG)

    A) 发布包：`<包根>/bootstrap.py` + `<包根>/mapbot_pc/…`（bat 调的就是这种）
    B) 开发机：`<mapbot_pc>/bootstrap.py`（本文件在代码目录里）
    """
    if os.path.isdir(os.path.join(HERE, 'mapbot_pc')):
        return HERE, os.path.join(HERE, 'mapbot_pc')
    return os.path.dirname(HERE), HERE


ROOT, PKG = _layout()

# ⭐ 朋友版开关：打包时在**包根**放一个 `friend_mode.flag`
#   ⇒ 开发机（没有这个文件）行为完全不变；朋友版固定关精确规划/不存图，且**与热更解耦**
#     （以前是靠 build_pkg.py 打包时字符串替换源码 —— 那样一发补丁就被冲回开发版 ✗）
if os.path.isfile(os.path.join(ROOT, 'friend_mode.flag')):
    os.environ['MAPBOT_FRIEND'] = '1'

sys.path.insert(0, PKG)                 # 让 hotupdate / bot_gui 都能 import
try:
    os.chdir(PKG)                       # 与旧 `启动.bat` 的 `cd mapbot_pc` 保持一致
except Exception:                       # noqa: BLE001
    pass


def _fatal(msg, exc=None):
    """界面都没起来时，别让朋友面对"双击没反应"：写日志 + 弹一个能看懂的框

    ⚠ `MGAS_PC_NO_POPUP=1` ⇒ 只写日志不弹框（门禁/无人值守跑启动链路时用；
      否则 messagebox 会**等人点击**，把自动化卡死）
    """
    text = msg if exc is None else '%s\n\n%s' % (msg, traceback.format_exc())
    try:
        logf = os.path.join(PKG, 'runs')
        os.makedirs(logf, exist_ok=True)
        with open(os.path.join(logf, 'bootstrap_error.log'), 'a', encoding='utf-8') as f:
            import time
            f.write('\n\n==== %s ====\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), text))
    except Exception:                   # noqa: BLE001
        pass
    if os.environ.get('MGAS_PC_NO_POPUP') == '1':
        return
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror('幻想少女公会 · 自动探索',
                             '%s\n\n详情见：%s\\runs\\bootstrap_error.log' % (msg, PKG))
        r.destroy()
    except Exception:                   # noqa: BLE001
        pass


def _confirm(hu):
    """⭐ 补丁代码**真的被加载并跑过**了 ⇒ 确认（`hotupdate.confirm_alive`）。

    ⚠⚠ 为什么"runpy 正常返回"也要算确认（2026-10-03 想清楚的，**别删**）：
      `bot_gui` 在「模拟器没开 / 分辨率不是 720×1280」时会**弹个提示就 return**
      —— 那时它**根本没建 Tk 窗口** ⇒ `root.after(3000, confirm_alive)` 永远不触发。
      若把这当成"没跑到确认点"，朋友一开机（MuMu 还没起）就被冤枉回滚，
      而且那个补丁 id 会被**永久拉黑** ✗✗
      ⇒ 判据应该是「**抛异常**了没有」：import 崩 / tkinter 崩根本走不到这里（走 except）。
      真正"坏补丁"仍然抓得住：`selftest` 抓 import 错，这里的 except 抓启动期崩溃。
    """
    try:
        if hu is not None:
            hu.confirm_alive()
    except Exception:                   # noqa: BLE001  （确认失败不该影响起界面）
        pass


def prepare():
    """①②③：把"能不能起界面"这件事先办完（失败也只记日志，不阻断启动）"""
    try:
        import hotupdate
    except Exception:                   # noqa: BLE001  连更新器都 import 不了 ⇒ 直接起现行版
        return None
    try:
        hotupdate.log('== 启动 == %s' % hotupdate.status_line())
        hotupdate.boot_recover()        # ① 上次没跑到确认点 ⇒ 连续 2 次则恢复出厂版
        ok, msg = hotupdate.apply_pending()
        if ok:
            hotupdate.log('  ✓ ' + msg)
        hotupdate.auto_update()         # ③ 下载新补丁（下次启动生效）
        hotupdate.log('== 就绪 == %s' % hotupdate.status_line())
    except Exception:                   # noqa: BLE001
        try:
            hotupdate.log('⚠ 启动期热更异常（继续用现行版启动）：\n' + traceback.format_exc())
        except Exception:               # noqa: BLE001
            pass
    return hotupdate


def main():
    # ⭐ `--hot-only`：只做热更准备（启动器 → 更新 → 自检），**不起界面**。
    #   用途：① 运维（先把补丁落好再开）② 门禁/自动化验证启动链路 ③ 朋友反馈时排查
    #   ⚠ 解析完就从 argv 里摘掉，别让它漏给 bot_gui 的 argparse（那边不认识会直接报错）
    hot_only = '--hot-only' in sys.argv
    if hot_only:
        sys.argv = [x for x in sys.argv if x != '--hot-only']
    hu = prepare()
    if hot_only:
        # ⚠ 这里**不确认**：确认的语义是"补丁代码真的被跑起来过"，而这一步没起界面
        return 0
    gui = os.path.join(PKG, 'bot_gui.py')
    if not os.path.isfile(gui):
        _fatal('找不到界面文件：%s' % gui)
        return 2
    try:
        runpy.run_path(gui, run_name='__main__')    # ④ 同进程起界面
    except SystemExit as e:                         # bot_gui 自己 sys.exit（正常收工）
        _confirm(hu)
        return e.code if isinstance(e.code, int) else 0
    except BaseException:
        # ⚠ 这里才是"补丁把界面搞崩了" ⇒ **不确认** ⇒ 下次启动判"没跑到确认点"
        _fatal('程序启动失败（已写日志）')
        return 1
    _confirm(hu)
    return 0


if __name__ == '__main__':
    sys.exit(main())
