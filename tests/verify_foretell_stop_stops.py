# -*- coding: utf-8 -*-
"""★ 回归：`foretell_stop` 必须**立即停止**（2026-10-12 用户报「没有立即停止啊」✗）

用户原话：「**🛑🛑 抽到【元素·橙色】⇒ 立即停止 … 没有立即停止啊**」
            ＋「**甚至还要准备进下一图。。**」

⛔ 病：`run_maps` 里只有 `kicked` / `red_equip` / `stopped` **三个** `why` 分支，
   **漏了 `foretell_stop`** ✗ ⇒ 它一路走到 `finish_map()` ⇒ **退图 + 继续下一张** ✗✗

⛔ 真机铁证（`runs/gui_20261012_163344.log`）：
     🛑🛑 抽到【元素·橙色】⇒ **立即停止**（不退图，留着你自己处理）
        本图结束：foretell_stop（耗时 37 秒）      ← 正确返回了
        · 已回到选图界面                          ← ⚠ **还是退图了** ✗
     › 第 16 张图 · 完成（42 秒）                  ← ⚠ 当成正常完成 ✗
     == 第 17 张图 ==                             ← ⚠ **进入下一张** ✗✗

⚠ 讽刺：注释**早就写对了**（`explore_loop.py` 里）：
   「⇒ 最终 `run_one_map` 的调用方按 `why == 'red_equip'` 那样处置：
      **不退图、不补点，停在那里交给人处理** ✓」
   ⇒ **注释写了、代码没写** ✗（本项目第 N 次"文档对、实现漏"）
"""
import io
import os
import re
import sys

# ── 本文件位于子目录（tests/ 或 devtools/）：把「仓库根」接回工作基准 ──
#   仓根 = 本文件所在目录的上一级；模块导入与 templates/ 等相对资源都基于它。
_os = __import__('os')
_sys = __import__('sys')
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
if ROOT not in _sys.path:
    _sys.path.insert(0, ROOT)
try:
    _os.chdir(ROOT)
except OSError:
    pass
HERE = ROOT          # 兼容：原脚本里的 HERE 一律指仓根（它们原本就住在仓根）


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


_SRC = io.open('explore_loop.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _SRC.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('`foretell_stop` 必须立即停止（2026-10-12）')
print('=' * 94)

print()
print('【1】结构级')
ck('① `run_maps` 里有 `why == \'foretell_stop\'` 分支',
   "if why == 'foretell_stop':" in _CODE)
# 四个"停局"分支都要在（一个都不许漏）
for _w in ('kicked', 'red_equip', 'foretell_stop', 'stopped'):
    ck('② ⭐ `run_maps` 有 `why == \'%s\'` 分支' % _w,
       ("if why == '%s':" % _w) in _CODE)
ck('③ ⚠ 反向：`collect_stop`/`shrine_stop` 分支**已删**（[临时]停止删了 ✓）',
   "if why == 'collect_stop':" not in _CODE
   and "if why == 'shrine_stop':" not in _CODE)

print()
print('【2】⭐⭐ 关键：该分支必须 **break**（停局），不能是 continue/无动作')
_S = _SRC.splitlines()
_i = None
for _k, _l in enumerate(_S, 1):
    if _l.strip() == "if why == 'foretell_stop':" and not _l.lstrip().startswith('#'):
        _i = _k
        break
print('     分支在第 %s 行' % _i)
if _i:
    # 取该分支到下一个同级 if 之间的代码
    _blk = []
    for _j in range(_i, min(len(_S), _i + 40)):
        _l = _S[_j]
        if _j > _i and re.match(r"^\s{8}if why == ", _l):
            break
        _blk.append(_l)
    _blk_c = '\n'.join(x for x in _blk if not x.lstrip().startswith('#'))
    _has_break = re.search(r'^\s{12}break\s*$', _blk_c, re.M) is not None
    print('     分支内代码行数 = %d ｜ 有 break = %s' % (len(_blk), _has_break))
    ck('④ ⭐⭐ 分支里有 **`break`**（立即停局 ✓）', _has_break)
    ck('⑤ ⭐ 分支设了 `STATS[\'stopped\']`（如实记账 ✓）',
       "STATS['stopped']" in _blk_c)
    ck('⑥ ⚠ 分支里**没有**调 `finish_map`（不退图 ✓）',
       'finish_map' not in _blk_c)
else:
    ck('④ 找到分支', False, '没找到')

print()
print('【3】⚠ 反向：调用侧那两条也要对')
ck('⑦ `run_one_map` 的排除表含 `foretell_stop`（不补点 ✓）',
   "'foretell_stop'" in _CODE)
# `run_one_map` 里：why 非空 ⇒ 排除表之外才 final_collect
ck('⑧ `run_one_map` 里 `foretell_stop` 在"不补点"名单内',
   "if why not in ('kicked', 'red_equip', 'foretell_stop', 'stopped'):" in _CODE)
ck('⑨ `popups()` 里抽到要停的卡 ⇒ 返回 `foretell_stop`',
   "return 'foretell_stop'" in _CODE)
ck('⑩ `one_round` 把它原样往上传',
   _CODE.count("return 'foretell_stop'") >= 2,
   '%d 处' % _CODE.count("return 'foretell_stop'"))

print()
print('【4】⭐ 真机复算：那条日志的 `why` 是什么')
_LOG = os.path.join('runs', 'gui_20261012_163344.log')
if not os.path.exists(_LOG):
    ck('⑪ 有真机日志', False, _LOG)
else:
    _t = io.open(_LOG, encoding='utf-8', errors='replace').read()
    ck('⑪ ⭐ 日志里确实有 `本图结束：foretell_stop`',
       '本图结束：foretell_stop' in _t)
    # ⚠ 修前的**病灶**：它在那次**退图了**并进了下一张
    _bad = ('已回到选图界面' in _t)
    print('     日志里有「已回到选图界面」= %s（修前就是这样 ✗）' % _bad)
    ck('⑫ ⭐ 确认病灶：那次**确实退图了**（铁证 ✓）', _bad)
    ck('⑬ ⭐ 且**进了下一张**（`== 第 17 张图 ==` ✓）',
       '第 17 张图' in _t)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
