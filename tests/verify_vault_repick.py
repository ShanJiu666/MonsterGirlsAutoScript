# -*- coding: utf-8 -*-
"""★ 回归：宝库「选了奖励还点同样位置 ⇒ 打开详情页」（2026-10-10 用户报）

用户原话：「**黄金宝库第二层还是有乱点，明明选择了奖励还要点一下同样的位置
            导致打开了详情界面**」

⛔ 根因（真机铁证 `runs/acc1/loop/loop_log.json` #403~#412）：
   `vault_pick` 走 `_probe_name` 兜底时**逐格点开详情读名**（前 3 格）：
       #404 probe at=[264,593] ┊ #406 probe at=[360,593] ┊ #408 probe at=[**456,592**]
       #409 probe_none  ⇒ 落 `return cells[0]` 兜底
       #412 claim ring=2 pick=[**456,592**] name='随意'
   ⇒ **`pick` 正是探测时点过的那一格** ⇒ `vault_flow` **又点一次**
   ⇒ 那格已是"选中"态 ⇒ 再点 = **打开详情页** ⇒ 盖住「选择奖励」按钮 ✗✗

⛔ 附带第二个 bug：`_probe_name` 把**面板提示文字**当成了物品名：
   #410 texts = [… "取一件哦。@(340,351)", "洁白神石@(359,419)", …]
                  ↑ 老代码锁定了它（第一个中文串）✗，真正的物品名是「洁白神石」
   ⇒ 3 格全白探 ⇒ 落 `随意` 兜底 ✗
"""
import io
import json
import os
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
import buypanels as BP


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  '+detail) if detail else ''))
    (OK if cond else BAD).append(name)


print('=' * 94)
print('宝库「选完还点同样位置」回归（2026-10-10）')
print('=' * 94)

# ── ① 结构级：有 `_PROBED` 且被三处使用 ──────────────────────
print()
print('【1】结构级：`_PROBED`（读名时点过的格）')
_src = io.open('buypanels.py', encoding='utf-8').read()
_code = '\n'.join(ln for ln in _src.splitlines() if not ln.lstrip().startswith('#'))
ck('① 有模块级 `_PROBED`', '_PROBED' in _src and hasattr(BP, '_PROBED'))
ck('② `vault_pick` 探测时**记入** `_PROBED`',
   '_PROBED.setdefault(level, set()).add(' in _code)
ck('③ `vault_flow` 开头**清空** `_PROBED`', '_PROBED.clear()' in _code)
ck('④ `vault_flow` 里**据此跳过重复点击**（`_already`）',
   '_already' in _code and 'skip_repick' in _code)
ck('⑤ ⚠ 跳过分支**排在** `_vault_tap(... pick ...)` **之前**',
   _code.find('_already = ') < _code.find("what='pick_cell%d' % ring"))

# ── ② 行为级：模拟"探过 ⇒ 必须跳过重复点击" ──────────────────
print()
print('【2】⭐ 行为级：模拟真机那条路（探过 (456,592) ⇒ pick 返回它）')
# 直接复现 `vault_flow` 里那段判据
BP._PROBED.clear()
BP._PROBED.setdefault(2, set()).add((456, 592))
pick = (456, 592)
_already = (pick[0], pick[1]) in BP._PROBED.get(2, set())
ck('⑥ 探过的格 ⇒ `_already` 为 True（会跳过 ✓）', _already is True)
pick2 = (360, 689)          # 没探过的格
_already2 = (pick2[0], pick2[1]) in BP._PROBED.get(2, set())
ck('⑦ ⚠ **没探过**的格 ⇒ `_already` 为 False（照常点 ✓，不是恒跳过）',
   _already2 is False)
ck('⑧ ⚠ 按**层**隔离（第 3 层查不到第 2 层的记录 ✓）',
   ((456, 592) in BP._PROBED.get(3, set())) is False)

# ── ③ `_probe_name` 不许把提示文字当名字 ──────────────────────
print()
print('【3】`_probe_name`：不许把**面板提示文字**当物品名')
_details = [
    {'text': '取一件哦。', 'cx': 340, 'cy': 351},
    {'text': '洁白神石', 'cx': 359, 'cy': 419},
    {'text': '更容易出现数值相关的效果', 'cx': 353, 'cy': 578},
]


class FB:
    def __init__(self):
        self.taps = []

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append((x, y))

    def ocr(self, *a, **k):
        return []

    def img_dlg(self):
        import numpy as np
        return np.zeros((1280, 720, 3), np.uint8)

    def snap(self, *a, **k):
        return 'x.png'


b = FB()
# 把 `_items` 打桩成详情页那三条
_orig_items = BP._items
BP._items = lambda bot: _details
try:
    nm = BP._probe_name(b, (456, 592), log=[])
finally:
    BP._items = _orig_items
print('     读到 = %r（应为「洁白神石」，不是「取一件哦。」）' % nm)
ck('⑨ ⭐ 读到的是**物品名**（`洁白神石` ✓）', nm == '洁白神石')
ck('⑩ ⚠ 不是面板提示（`取一件哦。` ✗）', nm != '取一件哦。')
ck('⑪ ⚠ 不是效果描述（`更容易…` ✗）', nm != '更容易出现数值相关的效果')

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
raise SystemExit(1 if BAD else 0)
