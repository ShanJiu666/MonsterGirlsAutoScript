# -*- coding: utf-8 -*-
"""★ 回归：**用户自选配置按设备（窗口）绑定 + 自动用最近一次**（2026-10-13 用户要求）

用户原话：
  「**把特殊方块，停止规则，多少张图自动升星等需要用户自己选择的自动用最近一次配置
    并且和对应窗口绑定（选哪个窗口就自动用对应的配置）**」

⛔ 改之前（病）：
   · 全部偏好都在 **`runs/` 根**（一份，所有窗口共用）✗
     ⇒ 开两个窗口 ⇒ **勾选互相覆盖** ✗✗
   · `每 N 张图升星`（`bag_every`）**根本没落盘**，写死 `'10'` ✗
     ⇒ 用户填 `25`、关窗再开 ⇒ **变回 10** ✗

⭐⭐ 为什么按**设备端口**绑、不按 `tag`：
   `devicesel.choose_device` 里 **只开一台时 `tag=''`** ⇒ 按 tag 存会**全部落到"全局"**
   ⇒ 分不开 ✗✗（而"选哪个窗口就用哪份配置"在**单开**时同样要成立 ✓）

⚠⚠ 本轮踩到的两个真坑（都记下来）：
   ① **自检污染真 `runs/`**：`Prefs.root_runs` 原来写死 `here/runs`
      ⇒ **绕不过**自检对 `bot_gui.LOG_DIR` 的重定向 ⇒ 在真目录建了 `dev_16384/` ✗
      ⇒ 修法：`Prefs(..., root=LOG_DIR)` **显式传**（自检当场抓到 ✓）
   ② `_selftest_ui` 里 `TC.cfg_path` 打了桩，但 `save_special` 我改成走**显式路径**
      ⇒ 桩失效 ⇒ 断言假红 ⇒ 桩也要跟着指到 per-device 那份 ✓
"""
import io
import json
import os
import shutil
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
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import bot_gui_ui.services as S
import targets_cfg as TC


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('配置按设备绑定 + 自动用最近一次（2026-10-13）')
print('=' * 94)

print()
print('【1】结构级')
_S = io.open('bot_gui_ui/services.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _S.splitlines() if not l.lstrip().startswith('#'))
ck('① `Prefs` 有 `DEV_PREFIX`', 'DEV_PREFIX' in _CODE)
ck('② ⭐ `Prefs.__init__` 收 `device`', 'device=' in _CODE and 'self.dev_name' in _CODE)
ck('③ ⭐⭐ `Prefs.__init__` 收 `root`（**可重定向** ✓）',
   'root=LOG_DIR' in io.open(os.path.join(CORE, 'bot_gui.py'), encoding='utf-8').read()
   or 'root=LOG_DIR' in _S)
ck('④ 有 `_migrate_once`（老配置自动搬过来 ✓）', '_migrate_once' in _CODE)
ck('⑤ 有 `load_bag_every` / `save_bag_every` ✓',
   'load_bag_every' in _CODE and 'save_bag_every' in _CODE)
_EL = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
ck('⑥ ⭐ 子进程认 `MAPBOT_TARGETS_CFG`（读**同一份** ✓）',
   'MAPBOT_TARGETS_CFG' in _EL)
_G = io.open(os.path.join(CORE, 'bot_gui.py'), encoding='utf-8').read()
ck('⑦ ⭐ GUI 把 `targets_cfg_path=` 传给子进程',
   'targets_cfg_path=' in _G)
ck('⑧ ⭐ 升星输入框改成**读回最近一次**（不再写死 10 ✗）',
   'load_bag_every' in _G)
ck('⑨ ⭐ 升星失焦/回车时**落盘**', 'save_bag_every' in _G)

print()
print('【2】⭐⭐ 行为级：两个"设备"配置**互不干扰**（核心需求 ✓）')
tmp = tempfile.mkdtemp(prefix='mgas_devcfg_')
try:
    for _dev in ('127.0.0.1:16448', '127.0.0.1:16384'):
        _p = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp, device=_dev, root=tmp)
        print('     设备 %-18s ⇒ dev_root=%s' % (_dev, os.path.basename(_p.dev_root())))
    _a = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp, device='127.0.0.1:16448', root=tmp)
    _b = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp, device='127.0.0.1:16384', root=tmp)

    # A 窗口：勾上"旅行商人"、停规则关掉 lucky、升星 25
    _a.save_special('旅行商人', True)
    _a.save_stop('lucky', False)
    _a.save_bag_every(25)
    # B 窗口：全部相反
    _b.save_special('旅行商人', False)
    _b.save_stop('lucky', True)
    _b.save_bag_every(7)

    _ca = json.loads(io.open(_a.targets_path(), encoding='utf-8').read())
    _cb = json.loads(io.open(_b.targets_path(), encoding='utf-8').read())
    print('     A(16448) 旅行商人=%s lucky=%s bag_every=%s'
          % ((_ca['types'] or {}).get('旅行商人'), _a.load_stop('lucky'),
             _a.load_bag_every()))
    print('     B(16384) 旅行商人=%s lucky=%s bag_every=%s'
          % ((_cb['types'] or {}).get('旅行商人'), _b.load_stop('lucky'),
             _b.load_bag_every()))
    ck('⑩ ⭐⭐ **特殊方块互不干扰**（A=True / B=False ✓）',
       (_ca['types'] or {}).get('旅行商人') is True
       and (_cb['types'] or {}).get('旅行商人') is False)
    ck('⑪ ⭐⭐ **停止规则互不干扰**（A=False / B=True ✓）',
       _a.load_stop('lucky') is False and _b.load_stop('lucky') is True)
    ck('⑫ ⭐⭐ **升星张数互不干扰**（A=25 / B=7 ✓）',
       _a.load_bag_every() == 25 and _b.load_bag_every() == 7,
       '%s / %s' % (_a.load_bag_every(), _b.load_bag_every()))

    print()
    print('【3】⭐⭐ "自动用最近一次" = 新建 Prefs 实例也读得到')
    _a2 = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp, device='127.0.0.1:16448', root=tmp)
    _ca2 = json.loads(io.open(_a2.targets_path(), encoding='utf-8').read())
    print('     重新 new 后：旅行商人=%s lucky=%s bag_every=%s'
          % ((_ca2['types'] or {}).get('旅行商人'), _a2.load_stop('lucky'),
             _a2.load_bag_every()))
    ck('⑬ ⭐⭐ 特殊方块"记住了"（重开还是 True ✓）',
       (_ca2['types'] or {}).get('旅行商人') is True)
    ck('⑭ ⭐⭐ 停止规则"记住了"（重开还是 False ✓）',
       _a2.load_stop('lucky') is False)
    ck('⑮ ⭐⭐ 升星张数"记住了"（重开还是 25 ✓，**原来会变回 10** ✗）',
       _a2.load_bag_every() == 25, str(_a2.load_bag_every()))

    print()
    print('【4】⭐ 迁移：老的全局配置**自动搬进**设备目录（勾选不丢 ✓）')
    tmp2 = tempfile.mkdtemp(prefix='mgas_migrate_')
    try:
        # 造一份"老的全局配置"（模拟用户之前在 runs 根的那份）
        io.open(os.path.join(tmp2, '.stop_lucky'), 'w', encoding='utf-8').write('0')
        io.open(os.path.join(tmp2, '.bag_every'), 'w', encoding='utf-8').write('30')
        io.open(os.path.join(tmp2, 'target_types.json'), 'w',
                encoding='utf-8').write(json.dumps(
                    {'version': 1, 'types': {'旅行商人': False, '黄金宝库': True}},
                    ensure_ascii=False))
        _c = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp2, device='127.0.0.1:16448', root=tmp2)
        _got_stop = _c.load_stop('lucky', default=True)
        _got_bag = _c.load_bag_every(default=10)
        _cg = json.loads(io.open(_c.targets_path(), encoding='utf-8').read())
        print('     迁移后：lucky=%s bag_every=%s 旅行商人=%s'
              % (_got_stop, _got_bag, (_cg['types'] or {}).get('旅行商人')))
        ck('⑯ ⭐ 全局 `.stop_lucky`=0 被搬过来了 ✓', _got_stop is False)
        ck('⑰ ⭐ 全局 `.bag_every`=30 被搬过来了 ✓', _got_bag == 30, str(_got_bag))
        ck('⑱ ⭐ 全局 `target_types.json` 的**取消勾选**被搬过来了 ✓',
           (_cg['types'] or {}).get('旅行商人') is False)
        ck('⑲ ⚠ 迁移**只搬那几个文件**（不动 runs 根的日志/统计 ✓）',
           os.path.exists(os.path.join(tmp2, '.stop_lucky')))

        print()
        print('【5】⚠ 反向：**已有设备配置不许被全局覆盖**（迁移只补缺 ✓）')
        _c.save_bag_every(99)          # 设备自己改成 99
        # 全局那份再改（模拟另一个窗口/手改）
        io.open(os.path.join(tmp2, '.bag_every'), 'w', encoding='utf-8').write('11')
        _c2 = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp2, device='127.0.0.1:16448', root=tmp2)
        print('     设备自己=99 ｜ 全局改成 11 ⇒ 重开读到 %s' % _c2.load_bag_every())
        ck('⑳ ⚠ 设备自己的值**没被全局覆盖**（仍 99 ✓）',
           _c2.load_bag_every() == 99, str(_c2.load_bag_every()))
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    print()
    print('【6】⚠⚠ 反向守门：**不许再落到 `runs/` 根**（那样就白改了 ✗）')
    _d = S.Prefs(os.path.dirname(os.path.abspath(__file__)), tmp, device='127.0.0.1:16448', root=tmp)
    for _nm, _p in (('auto_supply', _d.auto_supply_path()),
                    ('save_img', _d.save_img_path()),
                    ('stop_lucky', _d.stop_path('lucky')),
                    ('bag_every', _d.bag_every_path()),
                    ('target_types', _d.targets_path())):
        _ok = os.path.dirname(os.path.abspath(_p)) != os.path.abspath(tmp)
        ck('㉑ ⚠ `%s` **不在 runs 根**（在 dev_* 里 ✓）' % _nm, _ok,
           os.path.relpath(_p, tmp))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
