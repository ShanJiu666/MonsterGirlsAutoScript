# -*- coding: utf-8 -*-
"""verify_adb_reconnect.py · 回归：**别再用 MuMu 的 adb server、掉线要自愈**

用户 2026-10-05 贴的日志（真机连着丢图）：
    ⚠ 进图这一步出错（已跳过这张图）：
       AdbError(b'', b"adb.exe: device '127.0.0.1:16384' not found\\r\\n")
    == 第 2 张图 ==
    ... 同一个错又一遍

真根因（两份代码级铁证）
------------------------
1. **`ANDROID_ADB_SERVER_PORT` 在本项目这版 airtest 里根本没人读**
   （`airtest/core/android/adb.py:_set_cmd_options`：`server_addr` 为 None 就硬写 5037；
    全仓没有一处 `os.environ` 读它）⇒ `mapbot.py` 里那句 `os.environ.setdefault(...)`
   **等于没设** ✗
2. 真正决定用哪个 server 的是 **URI 里的 host:port**（`android.py:58` 把它当 `server_addr`）
   ⇒ 旧代码 URI 写死 `127.0.0.1:5037` ⇒ bot **一直在跟 MuMu 自带的 server 说话**
   （抓到的子进程铁证：`adb.exe -P 5037 -s 127.0.0.1:16416 shell …`）
   ⇒ MuMu 那边一动（模拟器重启/工具重连），它的设备表就清空 ⇒ bot 拿到
     `device not found` ⇒ 进图抛错 ⇒ **那张图白扔（体力照扣）** ✗✗

修法
----
· `mapbot.ADB_PORT`（默认 5038 = 我们自己的 server，与 MuMu 的 5037 隔离）
  **拼进 URI**（`_dev_uri`），`Bot.__init__` / `Bot.reconnect` 都走它
· `mapbot.adb_connect()`：连之前 `adb -P <port> connect <host:port>` + `wait-for-device`
  （自己的 server 一开始不认识设备，必须主动连 ✓；`emulator-5554` 那种不用 connect ✓）
· `Bot.reconnect()` **先 adb_connect 再 connect_device**（原来只 connect_device ——
  那**不会**把设备重新登记到 server 上 ⇒ 设备真掉线时一点用都没有 ✗）
· `explore_loop.enter_with_retry()`：进图遇到**连接类**错误 ⇒ `b.reconnect()` 再试一次，
  两次都失败才跳图（原来一次就跳 ✗）；**非连接类**错误照旧立刻上抛（不吞逻辑错 ✓）

牙齿（stash 掉本轮改动后必须红）
--------------------------------
旧代码：URI 里是 `127.0.0.1:5037`（不随环境变量变）✗、`reconnect()` 不调 adb_connect ✗、
`run_maps` 直接 `ensure_in_map`（没有重试）✗
"""
import os
import re
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
# ⚠ 业务模块已移进 `core/`（2026-10-17 目录整理）⇒ 也要能 import 到
CORE = _os.path.join(ROOT, "core")          # _MGAS_CORE_ADDED
if CORE not in _sys.path:
    _sys.path.insert(0, CORE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）


sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    import mapbot as MB
    import explore_loop as EL

    print('=== adb server 端口 / 掉线自愈 ===')

    # ── 0. 判据本身：真机那条消息必须被认成"连接类错误" ──────────────────
    #   ⚠ 这条是**本轮真踩到的**：旧关键词 `'device not found'` 是**连续子串**判据，
    #     而真机原文是 `device '127.0.0.1:16384' not found`（序列号夹在中间）
    #     ⇒ 一次都命不中 ⇒ 重试逻辑根本不触发 ✗（门禁就是这个作用 ✓）
    print()
    print('【0】`_is_conn_err` 必须认得真机那条（序列号夹在 `device` 与 `not found` 之间）')
    from airtest.core.error import AdbError
    _cases = [
        (AdbError(b'', b"adb.exe: device '127.0.0.1:16384' not found\r\n"), True,
         '真机原文（用户 10-05 贴的）'),
        (OSError("adb.exe: device '127.0.0.1:16416' not found"), True, 'acc2 那条'),
        (OSError('adb.exe: device emulator-5554 not found'), True, '无引号写法'),
        (OSError('device offline'), True, 'offline'),
        (ValueError('bug in my code'), False, '逻辑错：**不许**当连接错'),
        (TypeError("'NoneType' object is not subscriptable"), False, '逻辑错 2'),
    ]
    for _e, _want, _name in _cases:
        _got = MB._is_conn_err(_e)
        ck('%-34s ⇒ %s' % (_name, _want), _got is _want, '实际 %s' % _got)

    # ── 1. URI 里必须是**我们自己的**端口（随环境变量走）────────────────
    print()
    print('【1】设备 URI 的端口 = `ADB_PORT`（不再是写死的 MuMu 5037）')
    uri = MB._dev_uri('127.0.0.1:16384')
    print('      %s' % uri)
    ck('URI 用 `ADB_PORT`（默认 5038）', (':%d/' % MB.ADB_PORT) in uri,
       'ADB_PORT=%d' % MB.ADB_PORT)
    ck('端口默认值 = 5038（本项目自己的 server）', MB.ADB_PORT == 5038,
       '实际 %d' % MB.ADB_PORT)
    # 环境变量能改（⇒ 不是写死的常量）
    import subprocess
    code = ('import sys; sys.path.insert(0, r"%s"); import mapbot as M;'
            ' print(M._dev_uri("127.0.0.1:16384"))' % HERE)
    env = dict(os.environ, ANDROID_ADB_SERVER_PORT='5039', PYTHONIOENCODING='utf-8')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         env=env, timeout=120)
    port_ok = ':5039/' in (out.stdout or '')
    ck('设 `ANDROID_ADB_SERVER_PORT=5039` ⇒ URI 跟着变（不是写死）', port_ok,
       (out.stdout or out.stderr or '').strip()[:80])

    # ── 2. `adb_connect()` 必须真发 `adb -P <port> connect <dev>` ────────
    print()
    print('【2】`adb_connect()`：TCP 设备要 connect，emulator-xxxx 不要')
    calls = []

    class _R:
        returncode = 0

    real_run = MB.subprocess.run

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        return _R()

    try:
        MB.subprocess.run = fake_run
        MB.adb_connect('127.0.0.1:16384', port=5038)
        joined = ' '.join(' '.join(map(str, c)) for c in calls)
        ck('发了 `-P 5038 connect 127.0.0.1:16384`',
           ('-P' in joined and '5038' in joined and 'connect' in joined
            and '127.0.0.1:16384' in joined), joined[:120])
        ck('发了 `wait-for-device`（等设备真的可用）', 'wait-for-device' in joined)
        calls.clear()
        MB.adb_connect('emulator-5554', port=5038)
        joined2 = ' '.join(' '.join(map(str, c)) for c in calls)
        ck('`emulator-5554` 这种**不发** connect（交给 server 自动发现）',
           'connect' not in joined2, joined2[:120])
    finally:
        MB.subprocess.run = real_run

    # ── 3. `Bot.reconnect()` 必须**先 adb_connect** ─────────────────────
    print()
    print('【3】`Bot.reconnect()` 先 adb_connect 再 connect_device（原来只有后者 ✗）')
    order = []
    real_ac, real_cd = MB.adb_connect, MB.connect_device
    try:
        MB.adb_connect = lambda *a, **k: order.append('adb_connect')
        MB.connect_device = lambda *a, **k: order.append('connect_device')
        _inst = MB.Bot.__new__(MB.Bot)               # 只为调这一个方法（不跑 __init__）
        _inst.dev = '127.0.0.1:16384'
        MB.Bot.reconnect(_inst)
    except Exception as e:                            # noqa: BLE001
        order.append('EXC:%s' % repr(e)[:60])
    finally:
        MB.adb_connect, MB.connect_device = real_ac, real_cd
    ck('reconnect 里 adb_connect 在 connect_device **之前**',
       order[:2] == ['adb_connect', 'connect_device'], str(order))

    # ── 4. `enter_with_retry`：连接类错误重试一次，其它立刻抛 ────────────
    print()
    print('【4】`enter_with_retry()`：连接类错误重连重试一次；非连接类立刻上抛')
    class _B:
        def __init__(self):
            self.n = 0
        def reconnect(self):
            self.n += 1

    real_eim = EL.ensure_in_map
    try:
        # 4a. 第一次抛连接错、第二次成功
        state = {'k': 0}

        def eim_flaky(b, log, tag='', items0=None):
            state['k'] += 1
            if state['k'] == 1:
                raise OSError("adb.exe: device '127.0.0.1:16384' not found")
            return True

        EL.ensure_in_map = eim_flaky
        b = _B()
        log = []
        got = EL.enter_with_retry(b, log, tag='t_')
        ck('连接类错误 ⇒ 重连 + 重试成功（返回 True）',
           got is True and state['k'] == 2 and b.n == 1,
           'calls=%d reconnect=%d' % (state['k'], b.n))
        ck('重试这件事**记进了 log**（`enter_retry`）',
           any(isinstance(e, dict) and e.get('enter_retry') for e in log))

        # 4b. 一直抛连接错 ⇒ 试满 tries 次后上抛
        state['k'] = 0

        def eim_always(b, log, tag='', items0=None):
            state['k'] += 1
            raise OSError('device not found')

        EL.ensure_in_map = eim_always
        b2, raised = _B(), False
        try:
            EL.enter_with_retry(b2, [], tag='t_', tries=2)
        except Exception:                 # noqa: BLE001
            raised = True
        ck('两次都失败 ⇒ **上抛**（交回原来的跳图逻辑）', raised and state['k'] == 2,
           'calls=%d' % state['k'])

        # 4c. 非连接类错误 ⇒ **一次都不重试**（别吞逻辑错）
        state['k'] = 0

        def eim_logic(b, log, tag='', items0=None):
            state['k'] += 1
            raise ValueError('bug in my code')

        EL.ensure_in_map = eim_logic
        b3, raised2 = _B(), False
        try:
            EL.enter_with_retry(b3, [], tag='t_', tries=2)
        except ValueError:
            raised2 = True
        ck('非连接类错误（ValueError）⇒ 立刻上抛、**不重试**、不重连',
           raised2 and state['k'] == 1 and b3.n == 0,
           'calls=%d reconnect=%d' % (state['k'], b3.n))
    finally:
        EL.ensure_in_map = real_eim

    # ── 5. 调用点必须用 enter_with_retry（防止有人改回去）───────────────
    print()
    print('【5】`run_maps` 的进图调用点用的是 `enter_with_retry`（防回退）')
    src = open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    ck('源码里有 `_entered = enter_with_retry(` 这条调用',
       'enter_with_retry(b, log, tag=' in src)
    ck('没有残留"直接裸调 ensure_in_map 进图"的写法',
       '_entered = ensure_in_map(' not in src)
    # mapbot 里不许再有写死 5037 的设备 URI
    msrc = open(os.path.join(HERE, 'mapbot.py'), encoding='utf-8').read()
    ck('`mapbot.py` 里没有 `Android://127.0.0.1:5037` 这种写死端口的 URI',
       'Android://127.0.0.1:5037' not in msrc)
    ck('`mapbot.py` 里有 `ADB_PORT` 且被 `_dev_uri` 用上',
       bool(re.search(r'ADB_PORT\s*=', msrc)) and 'ADB_PORT, dev' in msrc)

    print()
    print('=' * 72)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：URI 端口可配（默认走我们自己的 5038）、reconnect 真重连、'
          '进图遇连接类错误会重连重试一次、逻辑错误照旧立刻抛')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
