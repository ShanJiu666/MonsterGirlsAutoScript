# -*- coding: utf-8 -*-
"""★ 回归：「发现莱姆！」的判据必须**独立成条**（2026-10-12 用户报 ✗）

用户原话：「**为什么会出现获得莱姆的点击？这个不应该只在最后一次点击之后出现吗**」

⛔ 病：`popups()` 用 `fb(items, *L['lime'])` 判弹窗，而 `fb` 是**子串**匹配 ✗
   `L['lime'] = ('莱姆', '发现莱姆')` ⇒ **任何含「莱姆」二字的条目**都命中 ✗✗

⛔ 真机铁证（`runs/gui_20261012_125244.log` + `runs/loop/loop_log.json`）：
     #11 board["5,4"] = ['013', '预言石碑', 0.998, 0.65]   ← 计划剩的一步是**预言石碑**
     #29 {"finish": "panel_rendering_wait", "cell": "5,4", "dim": 0.268}
         ⇒ 点开预言石碑 ⇒ 弹**预言石板面板**
     #31/#34/#37/#40 {"popup": "lime_back", "at": [359,873]}  ← **连判 4 次"莱姆"** ✗
     #41 {"loop_guard": "same_action", "n": 4} ⇒ 脱困 ⇒ 崩（退出码 1）

⛔ 为什么预言面板会命中：面板上有**「元素」预言卡**，数据表 `Foretell` 里它的效果是
   「地图中至少出现 1 只**莱姆**，并且所有莱姆至少是蓝色位阶。」⇒ 面板上真印着「莱姆」✗
   ⚠ 同族还有「精灵」：`多格地块结算时至少有 N 只莱姆。` ✗
   ⚠ 与我 10-11 修的「预言石碑被错派成勇者之墓」**同一个根因**（`fb` 被正文骗 ✗）
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
import explore_loop as EL


OK, BAD = [], []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    (OK if cond else BAD).append(name)


_SRC = io.open('explore_loop.py', encoding='utf-8').read()
_CODE = '\n'.join(l for l in _SRC.splitlines() if not l.lstrip().startswith('#'))

print('=' * 94)
print('「发现莱姆！」判据必须独立成条（2026-10-12）')
print('=' * 94)

print()
print('【1】结构级')
ck('① 有 `_lime_popup_title`', hasattr(EL, '_lime_popup_title'))
ck('② 有 `_LIME_TITLES` 表', hasattr(EL, '_LIME_TITLES'),
   str(getattr(EL, '_LIME_TITLES', ())))
# ⭐⭐ 全仓**零残留**：`L['lime']` 的子串判据一共 5 处（popups/finish_map/
#    final_collect×2/点击循环），这次**一起改成**独立成条 ✓
_LIME_SUBSTR = [(i, l.strip()[:90]) for i, l in enumerate(_SRC.splitlines(), 1)
                if not l.lstrip().startswith('#') and "L['lime']" in l]
print('     代码里仍用 `L[\'lime\']` 子串判据的 = %s' % (_LIME_SUBSTR or '无 ✓'))
ck('③ ⭐⭐ **全仓零残留**（5 处子串判据全部改掉 ✓）',
   not _LIME_SUBSTR, str(_LIME_SUBSTR[:3]))
ck('④ `popups()` 里用的是 `_lime_popup_title(items)`',
   '_lime_popup_title(items)' in _CODE)
ck('⑤ 判据用**相等**（`_t in _txts`），不是子串', '_t in _txts' in _CODE)

print()
print('【2】⭐⭐ 行为级：真弹窗必须命中（**三种实测形态**）')
for _its, _note in (
        (['发现莱姆！', '返回', '小莱姆'], '实测标题'),
        (['发现莱姆', '返回'], '丢叹号'),
        (['莱姆', '返回'], '短形态'),
        (['+发现莱姆！', '返回'], 'OCR 带前缀符号')):
    _r = EL._lime_popup_title([{'text': t} for t in _its])
    print('     %-18s ⇒ %r' % (_note, _r))
    ck('⑥ %s 命中' % _note, _r is not None, repr(_r))

print()
print('【3】⭐⭐⭐ 决定性：**预言卡正文不许命中**（这就是那个 bug ✗）')
_CARDS = [
    '地图中至少出现1只莱姆，并且所有莱姆至少是蓝色位阶。',
    '地图中至少出现2只莱姆，并且所有莱姆至少是紫色位阶。',
    '地图中至少出现1只莱姆，并且所有莱姆至少是橙色位阶。',
    '多格地块结算时至少有2只莱姆。',          # 「精灵」预言
]
for _c in _CARDS:
    _new = EL._lime_popup_title([{'text': _c}])
    _old = EL.fb([{'text': _c}], *EL.L['lime'])
    print('     %-34s 新=%-8s 旧=%s' % (_c[:34], repr(_new), bool(_old)))
    ck('⑦ ⭐ 卡牌正文**不命中**：%s…' % _c[:14], _new is None, repr(_new))
ck('⑧ ⚠ **对照项**：旧判据 `fb` **确实会**被这些正文骗到（证明本回归测得出 ✓）',
   all(EL.fb([{'text': c}], *EL.L['lime']) for c in _CARDS))

print()
print('【4】⚠ 反向：预言面板整体（标题+卡名）也不许命中')
_PANEL = ['预言石板', '本次可选择1个预言！', '元素', '战场', '藏宝']
ck('⑨ 预言面板文字**不命中**',
   EL._lime_popup_title([{'text': t} for t in _PANEL]) is None)
ck('⑩ 战斗结算文字**不命中**',
   EL._lime_popup_title([{'text': t} for t in
                         ('战斗胜利', '关闭', '自动跳过')]) is None)
ck('⑪ 空 items 返回 None', EL._lime_popup_title([]) is None)

print()
print('【5】⭐ 真机复算：那条 `5,4 预言石碑` 的面板不该再被判成莱姆')
_FIX = os.path.join('_verify', 'foretell_misdispatch_texts.json')
if os.path.exists(_FIX):
    _fd = json.load(io.open(_FIX, encoding='utf-8'))
    _its = [{'text': t} for t in _fd['texts']]
    print('     真机 texts 含「莱姆」的 = %s'
          % [t for t in _fd['texts'] if '莱姆' in t])
    ck('⑫ 该真机帧 ⇒ **不判莱姆**（修前 `fb` 会中「勇者之墓」那种正文 ✓）',
       EL._lime_popup_title(_its) is None)
else:
    ck('⑫ 有真机夹具', False, _FIX)

print()
print('=' * 94)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
for x in BAD:
    print('   ✗ ' + x)
sys.stdout.flush()
os._exit(1 if BAD else 0)
