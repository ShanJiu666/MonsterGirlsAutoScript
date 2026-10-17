# -*- coding: utf-8 -*-
"""bot_gui_ui/dialogs.py · 弹窗（设备选择 / 手动填设备号 / 系统提示）2026-10-11

为什么单独一个文件
------------------
`bot_gui.py` 原来把三个弹窗（`_msg` / `_pick_dialog` / `_manual_dialog`）直接写在
设备选择那一段里，用的是**裸 tkinter**（无 ttk / 无主题 / 无图标）⇒ 与重设计后的
`clam` 主题不一致 ✗（规划 §4.6「ctypes 弹窗换 ttk 对话框」）。

⭐ 但 `_msg`（系统提示）**故意保留 ctypes 原生 MessageBoxW**，理由有三条（不是偷懒）：
  1. 它会在 **`tk.Tk()` 之前**被调用（`main()` 里"分辨率不是 720×1280 ⇒ 拒绝建窗"那一支）
     —— 那时还没有任何 Tk 根窗口，建一个临时 root 再销毁属于**自找麻烦**（多开时更乱）；
  2. GUI 跑在 **pythonw.exe（无控制台）**：`print` 出去用户根本看不见 ⇒ 必须原生弹窗；
  3. `bootstrap.py` 用 `MGAS_PC_NO_POPUP=1` 做无人值守/门禁跑启动链路，`_msg` 是那条
     链路上唯一会**卡住等人点击**的东西 ⇒ 这里也认同一个环境变量（门禁友好 ✓）。

⚠ 这两个选择框（`pick_dialog` / `manual_dialog`）行为必须与重写前**逐字一致**
  （`verify_devicesel.py` 会把它们整个替换掉做纯逻辑回归 ⇒ 函数名与签名不许变，
   也**不许**在里面调 `bot_gui` 的任何东西 ⇒ 保持零依赖）。
"""
import os
import sys

from . import theme


def msg(title, text, icon='warn'):
    """系统弹窗 —— GUI 跑在 pythonw（无 console），print 出去用户根本看不见

    `MGAS_PC_NO_POPUP=1` ⇒ **只打印不弹框**（门禁/无人值守要的，见模块 docstring ✓）
    """
    if os.environ.get('MGAS_PC_NO_POPUP') == '1':
        try:
            print('[%s] %s' % (title, text), flush=True)
        except Exception:       # noqa: BLE001
            pass
        return
    import ctypes
    flag = {'warn': 0x30, 'error': 0x10, 'info': 0x40}.get(icon, 0x30)
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flag)
    except Exception:           # noqa: BLE001
        try:
            print('[%s] %s' % (title, text), flush=True)
        except Exception:       # noqa: BLE001
            pass


def _styled_root(title, w, h):
    """建一个**独立**的 ttk 风格小窗（设备选择发生在主窗口之前 ⇒ 只能自己建 root）"""
    import tkinter as tk
    root = tk.Tk()
    root.title(title)
    root.geometry('%dx%d' % (w, h))
    root.attributes('-topmost', True)
    theme.apply_theme(root)
    return root


def pick_dialog(running, inst, busy):
    """多个 MuMu 实例时的选择框 -> (port, inst[port]) | None（None = 用户取消）

    ⚠ 选项**只列运行中的**（`running` 已经过滤好了 ✓），运行中的在前；
      已被别的窗口占用的会标出来（`busy` = `{device: 占用描述}` ✓）
    """
    import tkinter as tk
    from tkinter import ttk
    root = _styled_root('选择要控制的 MuMu 实例', 520, 380)
    ttk.Label(root, text='这台机器上有多个 MuMu 实例在运行',
              style='Title.TLabel').pack(pady=(14, 2))
    ttk.Label(root, text='选一个来绑定（运行中的在前面；已被别的窗口占用的会标出来）',
              style='Hint.TLabel').pack()
    box = ttk.Frame(root)
    box.pack(fill='both', expand=True, padx=16, pady=10)
    box.grid_rowconfigure(0, weight=1)
    box.grid_columnconfigure(0, weight=1)
    lb = tk.Listbox(box, font=theme.FONT_BODY, activestyle='dotbox',
                    selectbackground=theme.C_PRIMARY, selectforeground='#FFFFFF',
                    highlightthickness=0)
    lb.grid(row=0, column=0, sticky='nsew')
    sb = ttk.Scrollbar(box, orient='vertical', command=lb.yview)
    sb.grid(row=0, column=1, sticky='ns')
    lb.configure(yscrollcommand=sb.set)
    order = []
    for p in sorted(running):
        v = inst[p]
        mark = '（已被别的窗口占用）' if ('127.0.0.1:%d' % p) in (busy or {}) else ''
        lb.insert('end', '%s   %s   %s%s'
                  % (v.get('name'), '127.0.0.1:%d' % p, v.get('android') or '', mark))
        order.append(p)
    lb.selection_set(0)
    lb.focus_set()
    pick = {'result': None}

    def confirm(_evt=None):
        sel = lb.curselection()
        if not sel:
            msg('幻想少女公会', '请先选一个实例', 'warn')
            return
        p = order[sel[0]]
        pick['result'] = (p, inst[p])
        root.destroy()

    bar = ttk.Frame(root)
    bar.pack(pady=(0, 14))
    ttk.Button(bar, text='就用这个', width=12, style='Primary.TButton',
               command=confirm).pack(side='left', padx=6)
    ttk.Button(bar, text='取消', width=12, command=root.destroy).pack(side='left', padx=6)
    lb.bind('<Double-1>', confirm)
    root.bind('<Return>', confirm)
    root.mainloop()
    # ⭐⭐⭐ 2026-10-03 真事故（这里**原来写 `pick.result = None`，而 `pick` 从未定义**）：
    #   一进这个对话框就 `NameError` ⇒ 整个 GUI 启动即退；而快捷方式用 `pythonw.exe`
    #   （**没有控制台**）⇒ 错误被吞掉 ⇒ 用户看到的就是"点了没反应、打不开" ✗✗
    #   （同文件的 `_manual_dialog` 用的是 `man = {...}` 字典 ✓ 这里漏了）
    #   ⇒ 现在两边都是**先建字典**再进 `mainloop` ✓
    return pick['result']


def manual_dialog(default='127.0.0.1:16384'):
    """兜底：MuMu 查不到时让用户手打设备号（真机/其他模拟器也能用）"""
    import tkinter as tk
    from tkinter import ttk
    root = _styled_root('手动指定设备', 420, 240)
    ttk.Label(root, justify='left', style='Bg.TLabel',
              text='没自动找到 MuMu 实例。\n'
                   '如果你是用真机或别的模拟器，填 adb 设备号；\n'
                   'MuMu 一般是 127.0.0.1:16384（第二实例 16416 …）。'
              ).pack(padx=16, pady=14)
    var = tk.StringVar(value=default)
    e = ttk.Entry(root, textvariable=var, width=24, font=theme.FONT_MONO,
                  justify='center')
    e.pack(pady=(0, 14))
    e.focus_set()
    e.select_range(0, 'end')
    man = {'ok': False, 'dev': ''}

    def confirm(_evt=None):
        v = (var.get() or '').strip()
        if not v:
            return
        man['ok'], man['dev'] = True, v
        root.destroy()

    ttk.Button(root, text='确定', width=12, style='Primary.TButton',
               command=confirm).pack(pady=(0, 14))
    e.bind('<Return>', confirm)
    root.mainloop()
    return man['dev'] if man['ok'] else None


def text_dialog(title, text, width=460, height=420):
    """只读文字框（特殊方块说明 / 热更状态详情用）—— 替代 `messagebox.showinfo`

    ⚠ 说明文本**很长**（8 个方块各 4~6 行）⇒ 用 messagebox 会挤成一坨看不清 ✗
      ⇒ 换成可滚动的只读框（与规划 §4.3「特殊方块」页签的口径一致 ✓）
    """
    import tkinter as tk
    from tkinter import ttk
    root = _styled_root(title, width, height)
    box = ttk.Frame(root, style='Bg.TFrame')
    box.pack(fill='both', expand=True, padx=theme.PAD_TAB, pady=theme.PAD_TAB)
    box.grid_rowconfigure(0, weight=1)
    box.grid_columnconfigure(0, weight=1)
    txt = tk.Text(box, wrap='word', font=theme.FONT_BODY, height=18,
                  relief='flat', bg=theme.C_BG, fg=theme.C_TEXT)
    txt.grid(row=0, column=0, sticky='nsew')
    sb = ttk.Scrollbar(box, orient='vertical', command=txt.yview)
    sb.grid(row=0, column=1, sticky='ns')
    txt.configure(yscrollcommand=sb.set)
    txt.insert('1.0', text)
    txt.configure(state='disabled')
    ttk.Button(root, text='关闭', width=10, style='Primary.TButton',
               command=root.destroy).pack(pady=(0, theme.PAD_CARD))
    root.bind('<Escape>', lambda _e: root.destroy())
    root.mainloop()


def main():        # pragma: no cover - 只为 `python -m bot_gui_ui.dialogs` 手看样式
    text_dialog('特殊方块说明（演示）', '这是一段很长的说明文字。\n' * 30)


if __name__ == '__main__':        # pragma: no cover
    main()
    sys.exit(0)
