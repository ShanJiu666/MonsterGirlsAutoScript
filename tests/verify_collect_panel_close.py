# -*- coding: utf-8 -*-
"""★ 回归：退图前补点碰到「限时礼包/传承祭坛/勇者之墓/宝箱怪」⇒ **只关掉、不领奖**

用户原话：①「**这张图为什么显示退图失败然后停止了？**」
          ②（我问怎么修）选「**只"关掉"面板，不领奖**」✓

⛔ 病（真机铁证 `runs/acc3/loop/loop_log_prev.json`，第 6 张图）：
    `#263` 快照 `1,6 = ['014','限时礼包', 0.887]`     ← 补点点的是这格
    `#285 collect no_panel dim=1.0`
    `#286 collect tapped at=[552,716] opened=true **still=true**`（`(552,716)`=格 `1,6`）✗
    `#287 unstick collect_panel tried=[[493,225],[683,150]]`      ← 两个 X 都没关掉 ✗
    `#290~#319` **反复 22 次**点 `(360,1219)` ⇒ `unknown_panel_clear` closed=0/1
    `#320 finish timeout` ｜ `#321 finished=false finish_secs=**110.6**`
    ⇒ **整局停下**（用户看到的就是"退图失败然后停止"）✗✗

⛔ 根因（**覆盖面缺口**）：`popups()` 认 6 种特殊面板，而 `final_collect` 只认 2 种
    · 认：预言石板（关掉+拉黑）/ 预言石碑（领掉）
    · **不认：限时礼包 / 传承祭坛 / 勇者之墓 / 宝箱怪** ✗
    ⇒ 补点时弹出这 4 种 ⇒ 判 `still=True` ⇒ `force_unstick` 也关不掉
      ⇒ 退图阶段反复点万能位，而那个值 `(360,1219)` **等于**
        `fixed.A('start_adv_icon')`（底部导航「开始冒险」）⇒ 当然关不掉 ✗
      ⇒ 空转 110 秒 ⇒ `finish: timeout` ⇒ 停止 ✗✗

⭐ 修法：补点时认到那 4 种标题 ⇒ 调 `buypanels.ensure_closed()` **只收起面板**
   ⚠ **不调** `gift_flow`/`shrine_flow`/…（那些会**领奖/购买**，违背
     `final_collect` 的既定契约「只补点 + 关面板，不再打架、不再买、不再揭新格」✗）
   ⚠ 判据用**面板标题**（`_panel_title_of`：独立成条 + 剥前缀），不做子串匹配 ✓
"""
import io
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
import explore_loop as EL

OK, BAD = [], []
SKIP = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


def skip(name, detail=''):
    """前提不成立（缺真机语料）⇒ **响亮地跳过**（不算通过、也不算失败）。

    ⚠ 公开发布版**不含**开发者的真机录屏语料（本地私有数据）。
    """
    print('  [SKIP] %s%s' % (name, ('  · ' + detail) if detail else ''))
    SKIP.append(name)


_S = io.open('explore_loop.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _S.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('补点碰到 4 种特殊面板 ⇒ 只关掉、不领奖（2026-10-14）')
print('=' * 94)

print()
print('【1】结构级')
ck('① ⭐ 有 `_FC_CLOSE_TITLES` 常量', '_FC_CLOSE_TITLES' in _CODE)
ck('② ⭐ `final_collect` 里用了它', '_panel_title_of(_it3) in _FC_CLOSE_TITLES' in _CODE)
ck('③ ⭐ 走 `ensure_closed`（**只收起面板** ✓）',
   'buypanels.ensure_closed(b, log)' in _CODE)
# ⚠ 断言要**限定在 `final_collect` 里**（`gift_flow` 在 `popups()` 里合法存在 ✓）
#   我第一版查全文件 ⇒ 假红 ✗（探针自己的错）
_col_body = ''
_lines = _S.splitlines()
_i0 = None
for _i, _l in enumerate(_lines):
    if _l.startswith('def final_collect('):
        _i0 = _i
        break
if _i0 is not None:
    _b = []
    for _j in range(_i0, len(_lines)):
        _l = _lines[_j]
        if _j > _i0 and _l.strip() and not _l.startswith((' ', '\t')):
            break
        _b.append(_l)
    _col_body = '\n'.join(x for x in _b if not x.lstrip().startswith('#'))
ck('④ ⚠⚠ `final_collect` 里**不调** `gift_flow`/`shrine_flow`/`mimic_flow`'
   '（那会领奖/购买 ✗）',
   not any(k in _col_body for k in ('gift_flow', 'shrine_flow', 'mimic_flow')),
   str([k for k in ('gift_flow', 'shrine_flow', 'mimic_flow')
        if k in _col_body]))
ck('⑤ ⭐ 判据用**面板标题**（独立成条，不做子串 ✓）',
   '_panel_title_of(_it3) in _FC_CLOSE_TITLES' in _CODE)

print()
print('【2】⭐ 那 3 种标题都在表里（且**都是实测过的标题** ✓）')
for _t in ('限时超值礼包', '传承祭坛', '英灵使者'):
    ck('⑥ `%s` 在 `_FC_CLOSE_TITLES` 里' % _t, _t in EL._FC_CLOSE_TITLES)
# ⚠⚠ 2026-10-14 **我第一版在这里凭想象加了宝箱怪** ⇒ 被本回归 ⑦⑧ 当场抓到 ✗
#   `机巧宝箱怪`/`金属宝箱怪` **不在** `_PANEL_TITLES`（实测清单只有 5 个）
#   ⇒ `_panel_title_of` 根本认不出它 ⇒ **等于没写** ✗
#   ⇒ 现在按纪律：**只放实测过的标题** ✓
ck('⑥b ⚠ **不放宝箱怪**（它没有实测过的面板标题 ⇒ 按纪律不写 ✗）',
   '机巧宝箱怪' not in EL._FC_CLOSE_TITLES
   and '金属宝箱怪' not in EL._FC_CLOSE_TITLES,
   str(EL._FC_CLOSE_TITLES))
# ⚠ 表里每个标题都必须是**实测过的**（`_PANEL_TITLES` 是权威清单 ✓）
_bad_t = [t for t in EL._FC_CLOSE_TITLES if t not in EL._PANEL_TITLES]
ck('⑦ ⚠ 表里每个标题都在 `_PANEL_TITLES`（**不许凭想象加** ✓）', not _bad_t,
   str(_bad_t))

print()
print('【3】⭐⭐ 行为级：`_panel_title_of` 对那 3 种标题都认得')
for _t in ('限时超值礼包', '传承祭坛', '英灵使者'):
    _got = EL._panel_title_of([{'text': _t}])
    ck('⑧ `_panel_title_of(["%s"])` = `%s`' % (_t, _t), _got == _t, repr(_got))
# ⚠ 反向：**无关文字不许被当标题**（否则会误关真面板 ✗）
for _t in ('战斗胜利', '获得新装备！', '本次可选择1个预言！', '返回'):
    _got = EL._panel_title_of([{'text': _t}])
    ck('⑨ ⚠ 反向：`%s` **不算标题**（不误关 ✓）' % _t, _got is None, repr(_got))

print()
print('【4】⭐⭐⭐ 真机复算：**那格确实叫「限时礼包」**（bug 现场 ✓）')
import json

_p = 'runs/acc3/loop/loop_log_prev.json'
if not os.path.exists(_p):
    # ⚠ 这份语料是**滚动覆盖**的（每跑一局就被下次覆盖），且发布版本来就不带
    #   ⇒ 必须**响亮跳过**：既不能算通过（那是假绿），也不能算失败（不是代码问题）
    skip('⑩⑪⑫ 真机复算：那格确实叫「限时礼包」',
         '缺真机语料 %s（发布版不带私有录屏）⇒ 未真正验证' % _p)
else:
    d = json.load(io.open(_p, encoding='utf-8'))
    _snap = None
    for i, e in enumerate(d):
        if isinstance(e, dict) and e.get('board_snapshot') and i > 250:
            _snap = e
            break
    _b = (_snap or {}).get('board') or {}
    print('     快照 #? %s ｜ 1,6 = %s' % ((_snap or {}).get('mapname'), _b.get('1,6')))
    if _snap is None:
        skip('⑩⑪⑫ 真机复算：那格确实叫「限时礼包」',
             '%s 里没有 board_snapshot（语料已滚动）⇒ 未真正验证' % _p)
    else:
        ck('⑩ ⭐⭐ `1,6` = **限时礼包**（补点点它 ✓）',
           isinstance(_b.get('1,6'), list) and '限时礼包' in str(_b.get('1,6')),
           str(_b.get('1,6')))
        # 补点那次 tapped 的坐标
        _tapped = None
        for e in d:
            if isinstance(e, dict) and e.get('collect') == 'tapped':
                _tapped = e
        ck('⑪ ⭐ 补点 `still=true`（**面板没关掉** —— 这就是那个 bug ✓）',
           bool((_tapped or {}).get('still')), str((_tapped or {}).get('still')))
        _at = (_tapped or {}).get('at')
        ck('⑫ ⭐ 补点坐标 = `[552,716]`（= 格 `1,6` ✓）', _at == [552, 716], str(_at))

print()
print('【5】⚠⚠ 反向守门：**预言石碑仍要"领掉"**（不许被我这次改动带坏 ✗）')
ck('⑬ ⭐ 预言石碑那支**仍在**（`foretell_flow` ✓）',
   'buypanels.foretell_flow(' in _CODE)
ck('⑭ ⚠ `_FC_CLOSE_TITLES` **不含**「预言石板」/「预言石碑」'
   '（它们有专门处理，别进"只关掉"这支 ✗）',
   '预言石板' not in EL._FC_CLOSE_TITLES
   and '预言石碑' not in EL._FC_CLOSE_TITLES,
   str(EL._FC_CLOSE_TITLES))

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
for x in BAD:
    print('   ✗ ' + x)
if SKIP:
    print('   ⚠ 以下 %d 项**没真正验证**（缺真机语料，非代码问题）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.stdout.flush()
os._exit(1 if BAD else 0)
