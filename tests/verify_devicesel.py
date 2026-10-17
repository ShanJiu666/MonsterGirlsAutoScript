# -*- coding: utf-8 -*-
"""verify_devicesel.py · 设备选择三态的回归（2026-10-02）

用户定的行为（`bot_gui.choose_device`）：
    · 多个 MuMu 在跑 → 弹选择框，用户挑
    · **只有一个在跑 → 直接连上，不弹任何窗口**
    · 一个都没启动   → 弹窗提醒去启动 MuMu，退出

为什么要有这个门禁
------------------
这段逻辑决定「用户双击之后看到什么」，**只有真机多开才发觉得到**：
朋友机器上没第二个实例、作者本机通常就开一个 ⇒ 改坏了很可能一路绿灯发出去，
到别人手上才炸。而它是纯逻辑（吃一份假的实例表就能测），完全该被门禁钉住。

⚠ **全程不碰真实 MuMu**：所有用例都把 `mumu.instances()` 换成假数据，
   也不会弹任何真窗口（`_msg` / `_pick_dialog` / `_manual_dialog` 都被替换掉）。
"""
from __future__ import annotations

import io
import os
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


os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _inst(names_and_running):
    """[(name, android, running, index), ...] -> MuMuManager 那套 dict"""
    out, port = {}, 16384
    for name, android, running, idx in names_and_running:
        out[port] = {'name': name, 'android': android, 'running': running,
                     'index': str(idx)}
        port += 32
    return out


def _run(fake_inst, given=None, given_tag='', pick=None, manual=None):
    """在假环境下跑一次 choose_device，返回 (result, 弹出的提示列表, 是否弹过选择框)"""
    import bot_gui
    import mumu
    saved = (mumu.instances, bot_gui._msg, bot_gui._pick_dialog,
             bot_gui._manual_dialog)
    msgs, asked = [], []

    def fake_msg(title, text, icon='warn'):
        msgs.append((title, text, icon))

    def fake_pick(running, inst, busy):
        asked.append(list(running))
        return pick(running, inst, busy) if pick else None

    try:
        mumu.instances = lambda: fake_inst
        bot_gui._msg = fake_msg
        bot_gui._pick_dialog = fake_pick
        bot_gui._manual_dialog = (lambda: manual) if manual else (lambda: None)
        # ⚠ 单实例那条路必须**完全静默** —— 用一个会炸的断言桩来保证没人偷偷加提示
        result = bot_gui.choose_device(given, given_tag)
        return result, msgs, asked
    finally:
        (mumu.instances, bot_gui._msg, bot_gui._pick_dialog,
         bot_gui._manual_dialog) = saved


def main():
    print('=== 设备选择三态（全程假数据，不碰真 MuMu）===\n')

    print('【1】只有一个实例在跑 ⇒ 自动连上，且**一个窗口都不弹**')
    fake = _inst([('实例B', '12.0', True, 0), ('没开的', '12.0', False, 1)])
    res, msgs, asked = _run(fake)
    ck('直接返回设备号', res and res[0] == '127.0.0.1:16384', str(res))
    ck('单开沿用空 tag（行为与从前一致）', bool(res) and res[1] == '', repr(res[1] if res else None))
    ck('**没有弹任何提示**', not msgs, '弹了 %d 次: %s' % (len(msgs), msgs[:1]))
    ck('**没有弹选择框**', not asked, '弹了 %d 次' % len(asked))

    print()
    print('【2】多个实例在跑 ⇒ 弹选择框，选项只含**运行中**的')
    fake = _inst([('实例B', '12.0', True, 0), ('小号A', '15.0', True, 1),
                  ('关着的', '12.0', False, 2)])
    res, msgs, asked = _run(fake, pick=lambda r, i, b: (r[-1], i[r[-1]]))
    ck('确实弹了选择框', len(asked) == 1)
    ck('选项里只有运行中的两个', asked and asked[0] == [16384, 16416], str(asked))
    ck('选了第二个 ⇒ 拿到它的设备号', res and res[0] == '127.0.0.1:16416', str(res))
    ck('按实例 index 派 tag', res and res[1] == 'acc2', repr(res[1] if res else None))

    print()
    print('【3】用户点「取消」⇒ 不启动，且不当成错误')
    res, msgs, asked = _run(fake, pick=lambda r, i, b: None)
    ck('返回空（main 会安静退出）', res == (None, None), str(res))
    ck('取消**不弹错误弹窗**', not msgs, '弹了 %d 次' % len(msgs))

    print()
    print('【4】一个实例都没启动 ⇒ 提醒去启动 MuMu')
    fake = _inst([('实例B', '12.0', False, 0), ('小号A', '15.0', False, 1)])
    res, msgs, asked = _run(fake)
    ck('不启动', res == (None, None), str(res))
    ck('弹了 1 次提醒', len(msgs) == 1, '弹了 %d 次' % len(msgs))
    text = msgs[0][1] if msgs else ''
    ck('提醒里说清「没启动」', '一个实例都没启动' in text, text[:40])
    ck('列出了本机每个实例', '实例B' in text and '小号A' in text)
    ck('**没有弹选择框**（没得选）', not asked)

    print()
    print('【5】多开子进程（已带 --device）⇒ 原样绑定，**不再打扰**')
    for dev, tag in (('127.0.0.1:16416', 'acc2'), ('127.0.0.1:16384', '')):
        res, msgs, asked = _run(_inst([('实例B', '12.0', True, 0),
                                       ('小号A', '15.0', True, 1)]),
                                given=dev, given_tag=tag,
                                pick=lambda r, i, b: (_ for _ in ()).throw(
                                    AssertionError('不该弹框！')))
        ck('原样返回 %s / %r' % (dev, tag), res == (dev, tag), str(res))
        ck('没弹提示也没弹框', not msgs and not asked)

    print()
    print('【6】tag 按 MuMu 实例 index 派（删实例不串号）')
    import bot_gui
    full = _inst([('A', '12.0', True, 0), ('B', '12.0', True, 1), ('C', '12.0', True, 2)])
    ck('index0 -> acc1', bot_gui.tag_for(full, 16384) == 'acc1')
    ck('index2 -> acc3', bot_gui.tag_for(full, 16448) == 'acc3')
    # ⚠ 这是旧实现 `sorted(inst).index(p)+1` 真正会错的场景：
    #   多开器里删掉中间那个（B）⇒ 按端口排序后 C 挤到第 2 位 ⇒ 旧算法给 acc2
    after_del = {16384: full[16384], 16448: full[16448]}
    got = bot_gui.tag_for(after_del, 16448)
    ck('删掉 B 后 C 仍是 acc3（旧算法会误给 acc2）', got == 'acc3', got)

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：设备选择三态符合预期')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
