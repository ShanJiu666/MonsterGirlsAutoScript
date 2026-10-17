# -*- coding: utf-8 -*-
"""bot_gui_ui/devicesel.py · 设备选择三态（从 `bot_gui.py` 搬出来，2026-10-11）

用户 2026-10-02 定的三态（`verify_devicesel.py` 逐条钉住）：
    多个 MuMu 在跑  → 弹选择框，用户挑
    **只有一个在跑** → 直接连上，**不打扰**（一个窗口都不弹 ✓）
    一个都没启动    → 弹窗提醒去启动 MuMu，退出

⚠⚠ 为什么这里**用依赖注入**（`msg`/`pick`/`manual`/`tag_fn` 都当形参传进来）
---------------------------------------------------------------------
`verify_devicesel.py` 是这么测的（`verify_devicesel.py:53-74`）：
    saved = (mumu.instances, bot_gui._msg, bot_gui._pick_dialog, bot_gui._manual_dialog)
    bot_gui._msg = fake_msg ; bot_gui._pick_dialog = fake_pick ; ...
    result = bot_gui.choose_device(given, given_tag)
⇒ 它**monkeypatch 的是 `bot_gui` 模块的名字**，而且**全程不碰真 MuMu、不弹真窗口**。
⇒ 所以：① `bot_gui.py` 必须继续有同名的模块级 `_msg`/`_pick_dialog`/`_manual_dialog`
        （转发到 `dialogs.py`），② `choose_device` 内部**必须在调用时去查这几个名字**
        ⇒ 本函数把它们收成形参、由 `bot_gui.choose_device` 的**包装层**传进来 ✓
   （如果本函数直接 `from .dialogs import msg` 去用，monkeypatch 就**静默失效**，
     门禁会变成"测了个假东西"✗ —— 这正是本轮要避免的"假绿"）
"""
import os


def choose_device(given=None, given_tag='', msg=None, pick=None, manual=None,
                  tag_fn=None, default_dev='127.0.0.1:16384'):
    """决定本窗口绑哪台设备 -> (device, tag) | (None, None)（= 放弃启动）

    `given` 有值 = 「多开」子进程已绑定死，直接用，**不打扰用户** ✓
    """
    if given:
        return given, given_tag
    inst = {}
    try:
        import mumu
        inst = mumu.instances()
    except Exception as e:      # noqa: BLE001
        inst = {}
        msg('幻想少女公会', '查 MuMu 实例失败：%r' % e, 'error')
    if not inst:
        # 分不清「没装 MuMu」还是「装了但多开器里一个实例都没有」——两种都给手动入口
        msg('幻想少女公会 · 自动探索',
            '没找到运行中的 MuMu 实例。\n\n'
            '请先打开 MuMu 模拟器并登录游戏，然后重新启动本程序。\n'
            '（用的是真机或其它模拟器？点「确定」手动填设备号）', 'warn')
        d = manual()
        return (d, '') if d else (None, None)

    running = [p for p in inst if (inst[p] or {}).get('running')]
    if not running:
        lines = '\n'.join('  · %s（%s）— 未启动'
                          % ((v or {}).get('name'), '127.0.0.1:%d' % p)
                          for p, v in sorted(inst.items()))
        msg('幻想少女公会 · 自动探索',
            'MuMu 里一个实例都没启动，没法连。\n\n'
            '请打开模拟器并登录游戏，再重新启动本程序。\n\n'
            '本机已有的实例：\n%s' % lines, 'warn')
        return None, None
    if len(running) == 1:
        p = running[0]
        # ⭐ 单开：tag 留空 = 沿用共享目录，行为与从前一致 ✓（**一个窗口都不弹** ✓）
        return '127.0.0.1:%d' % p, ''

    busy = {}
    try:
        import loopguard
        busy = loopguard.busy_devices(exclude_pid=os.getpid())
    except Exception:           # noqa: BLE001
        pass
    sel = pick(running, inst, busy)
    if not sel:
        return None, None
    p, _v = sel
    return '127.0.0.1:%d' % p, (tag_fn or (lambda i, pp: ''))(inst, p)
