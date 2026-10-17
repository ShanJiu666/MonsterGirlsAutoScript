# -*- coding: utf-8 -*-
"""⭐ 回归：**天赋果实记录**（2026-10-16 用户口径）。

用户原话（三次）：
    ① 「最后的最后（**做完日常，招募什么的且体力小于100就是最后了**）
       去**背包道具**里扫描下天赋果实数量，并且记录」
    ② 「类似**小助手的天赋果实记录**，做好放到**工具栏**里」
    ③ 「存 runs 里吧，要**每个窗口独立计算**」＋「**自动扫描**，工具那里能看到记录」

本门禁钉住四件事：
    ① 道具 ID 认对了（`D00002_001` = 天赋果实，**与小助手同一个** ✓）
    ② 计算口径与小助手 `FruitRecordView` **逐字一致**（`U(prev,curr)` 三式）
    ③ **模板能唯一命中**（有果实 1.000 / 无果实 0.802 ⇒ 阈值 0.90 分得开）
    ④ 接线：收工流程里**放在最后** + **体力 < 100 才扫** + 工具栏有那两颗按钮

用法：python verify_fruit.py
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
import json

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
os.chdir(ROOT)               # 仓根（原为脚本自身目录）
import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402
import fruit as F                                               # noqa: E402

N = [0]
FAILS = []


def ck(name, cond, detail=''):
    if cond:
        N[0] += 1
    else:
        FAILS.append(name)
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))


print('=' * 86)
print('天赋果实记录 · 回归')
print('=' * 86)
print()

print('【1】道具身份（与游戏数据表、小助手三方对齐）')
ck('① 道具 ID = `D00002_001`（游戏 `Special_Item` + 小助手 `Shop/D00002_001` 同名 ✓）',
   F.FRUIT_ID == 'D00002_001', 'FRUIT_ID=%s' % F.FRUIT_ID)
_dt = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server_datatable.json')
if os.path.exists(_dt):
    _d = json.load(io.open(_dt, encoding='utf-8', errors='replace'))
    _si = (_d.get('Special_Item') or {})
    _row = next((v for v in _si.values()
                 if v.get('IDs') == F.FRUIT_ID), None)
    ck('② 游戏表里 `D00002_001` 就叫「天赋果实」（且 Type=货币 ✓）',
       bool(_row) and _row.get('Name') == F.FRUIT_NAME
       and _row.get('Type') == '货币',
       'Name=%s Type=%s' % ((_row or {}).get('Name'), (_row or {}).get('Type')))

print()
print('【2】计算口径 —— **逐字复刻小助手 `FruitRecordView` 的 `U(prev,curr)`**')
# 小助手源码：
#   netChange = curr.count - prev.count
#   consumed  = 显式给的 或 max(0, -netChange)
#   acquired  = max(0, netChange + consumed)
_cases = [
    ({'date': 'a', 'count': 100}, {'date': 'b', 'count': 105, 'consumed': 3},
     (5, 3, 8), '涨 5 同时用 3 ⇒ 获取 8'),
    ({'date': 'a', 'count': 100}, {'date': 'b', 'count': 92},
     (-8, 8, 0), '降到 92 ⇒ 消耗 8、获取 0'),
    ({'date': 'a', 'count': 100}, {'date': 'b', 'count': 100},
     (0, 0, 0), '不变 ⇒ 全 0'),
    ({'date': 'a', 'count': 10}, {'date': 'b', 'count': 25, 'consumed': 0},
     (15, 0, 15), '涨 15、显式消耗 0 ⇒ 获取 15'),
]
for p, c, want, note in _cases:
    got = F.diff_of(p, c)
    ck('③ %-24s ⇒ %s（期望 %s）' % (note, got, want), got == want)

# 统计：首日算基准、间断均摊
_recs = [{'date': '2026-10-14', 'count': 50},
         {'date': '2026-10-16', 'count': 80, 'spreadAcrossDays': True}]
_st = F.stats(_recs)
ck('④ 首日**算基准不计入** ⇒ 50→80 跨 2 天：总获取 30 / 日均 15',
   _st['total_get'] == 30 and _st['avg'] == 15 and _st['span_days'] == 2,
   'total_get=%s avg=%s span=%s' % (_st['total_get'], _st['avg'],
                                    _st['span_days']))
_net, _cons, _acq = F.diff_of({'count': 50}, {'count': 30})
ck('⑤ 净减少（50→30）⇒ 消耗 20、获取 0（**差额全算消耗** ✓）',
   (_cons, _acq) == (20, 0), 'cons=%s acq=%s' % (_cons, _acq))

print()
print('【2b】⭐ **同一天多次统计只算一天**（用户口径：「本天内多次统计要计入一天内，'
      '不要当成多天」）')
print('     ⚠ 我实测抓到过：同一天 2 条时 `days=3`、`peak=66`（同一天被劈成两天 ✗）')
_same = [{'date': '2026-10-15', 'count': 2200},
         {'date': '2026-10-16', 'count': 2210},
         {'date': '2026-10-16', 'count': 2276}]
_st2 = F.stats(_same)
ck('㉑ `stats()` 里 `days` = **唯一日期数**（同一天 2 条 ⇒ days=2，**不是 3** ✗）',
   _st2['days'] == 2, 'days=%s（期望 2）' % _st2['days'])
ck('㉒ `peak` 按**按天归一后**算（2200→2276 ⇒ 峰值 76，'
   '**不是** 2210→2250 的 40 或被劈开的 66 ✗）',
   _st2['peak'] == 76, 'peak=%s（期望 76）' % _st2['peak'])
ck('㉓ `total_get` 也只算一次（76 ✓）',
   _st2['total_get'] == 76, 'total_get=%s' % _st2['total_get'])
# 同一天里"取最后一条的 count"（一天里越晚越准）
_m = F.merge_by_day(_same)
ck('㉔ `merge_by_day` 同一天取**最后一条的 count**（越晚越准 ✓）且条数变 2',
   len(_m) == 2 and _m[-1]['count'] == 2276,
   '%s' % [(r['date'], r['count']) for r in _m])
# 合并时 consumed 取最大、备注拼接（别丢数据）
_m2 = F.merge_by_day([{'date': '2026-10-16', 'count': 10, 'consumed': 3,
                       'remark': 'A'},
                      {'date': '2026-10-16', 'count': 20, 'consumed': 7,
                       'remark': 'B'}])
ck('㉕ 合并时 `consumed` 取**最大**、`remark` **拼接**（别丢数据 ✓）',
   _m2[0]['consumed'] == 7 and 'A' in _m2[0]['remark']
   and 'B' in _m2[0]['remark'],
   'consumed=%s remark=%s' % (_m2[0].get('consumed'), _m2[0].get('remark')))
# record() 写之前也归一（文件被人手工编辑过也不会变成两天）
import tempfile                                                 # noqa: E402
_rp2 = os.path.join(tempfile.gettempdir(), '_vf_same.json')
F.save_records([{'date': '2026-10-16', 'count': 100},
                {'date': '2026-10-16', 'count': 200}], None, _rp2)
F.record(None, 300, path=_rp2)
_w = F.load_records(None, _rp2)
ck('㉖ `record()` **写之前也按天归一** ⇒ 文件里同一天不会留两条 ✗',
   len([r for r in _w if r['date'] == '2026-10-16']) == 1
   and _w[-1]['count'] == 300,
   '%s' % [(r['date'], r['count']) for r in _w])
try:
    os.remove(_rp2)
except OSError:
    pass

print()
print('【3】模板命中（**必须唯一**，且能用阈值区分有/无）')
_tp = os.path.join('templates', 'fruit_A_whole.png')
_mp = os.path.join('templates', 'fruit_A_whole_mask.png')
ck('⑥ 模板与掩膜都在（`templates/fruit_A_whole*.png` ✓）',
   os.path.exists(_tp) and os.path.exists(_mp),
   '%s / %s' % (os.path.exists(_tp), os.path.exists(_mp)))
FRAMES = ''
_has = os.path.join(FRAMES, 'bag_items.png')        # 道具页（有果实）
_no = os.path.join(FRAMES, 'bag_open.png')          # 素材页（无果实）
if os.path.exists(_tp) and os.path.exists(_has):
    _tpl = cv2.imdecode(np.fromfile(_tp, np.uint8), cv2.IMREAD_COLOR)
    _msk = cv2.imdecode(np.fromfile(_mp, np.uint8), cv2.IMREAD_GRAYSCALE)
    _R = _tpl.shape[0]
    _Y0, _Y1, _X0, _X1 = F.BAG_ITEM_BOX

    def _best(p):
        img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        sub = img[_Y0:_Y1, _X0:_X1].astype(np.float32)
        bb = None
        for us in F.FRUIT_SCALES:
            w, h = int(_R * us), int(_R * us)
            if w < 8 or w >= sub.shape[1] or h >= sub.shape[0]:
                continue
            t = cv2.resize(_tpl, (w, h),
                           interpolation=cv2.INTER_AREA).astype(np.float32)
            m = cv2.resize(_msk, (w, h), interpolation=cv2.INTER_NEAREST)
            mf = (m > 0).astype(np.float32)
            if float(mf.sum()) < 20:
                continue
            res = cv2.matchTemplate(sub, t, cv2.TM_SQDIFF, mask=mf)
            res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
            mn, _mx, loc, _ml = cv2.minMaxLoc(res)
            sc = 1.0 - mn / (float(mf.sum()) * 255.0 * 255.0)
            if bb is None or sc > bb[0]:
                bb = (sc, _X0 + loc[0] + w // 2, _Y0 + loc[1] + h // 2)
        return bb

    _b1 = _best(_has)
    ck('⑦ **有果实**那帧 ⇒ 分数 ≥ 阈值（且落在果实格 ≈(95,437)）',
       bool(_b1) and _b1[0] >= F.FRUIT_THR
       and abs(_b1[1] - 95) < 25 and abs(_b1[2] - 437) < 25,
       '%s（阈值 %.2f）' % (_b1, F.FRUIT_THR))
    if os.path.exists(_no):
        _b2 = _best(_no)
        ck('⑧ ⚠ **无果实**那帧 ⇒ 分数 < 阈值（**不许误报** ✓ 对照项）',
           bool(_b2) and _b2[0] < F.FRUIT_THR,
           '%s（阈值 %.2f）' % (_b2, F.FRUIT_THR))
    ck('⑨ 用的是 `TM_SQDIFF` + 掩膜（**不是 `TM_CCORR_NORMED`** ✗ 那个会虚高）',
       'TM_SQDIFF' in io.open(os.path.join(CORE, 'fruit.py'), encoding='utf-8').read()
       or 'cv2.TM_SQDIFF' in io.open(os.path.join(CORE, 'fruit.py'), encoding='utf-8').read())

print()
print('【4】接线（收工流程 + 工具栏）')
_src = io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read()
_gd = _src.split('def _guild_daily')[1].split('\ndef map_end_kind')[0]
_pos = {nm: _gd.find(pat) for nm, pat in
        (('派遣', '_gt.run('), ('炼金', '_al.run('), ('情报', '_it.run('),
         ('招募', '_rc.run('), ('广告', '_ad.run('),
         ('扫果实', '_fr.scan_and_record'))}
ck('⑩ 扫果实在**最后**（在广告之后 ✓ 用户："**最后的最后**"）',
   _pos['扫果实'] > max(_pos['派遣'], _pos['炼金'], _pos['情报'],
                        _pos['招募'], _pos['广告']),
   str(_pos))
ck('⑪ 闸门 = **体力 < `FRUIT_SCAN_MAX_STAMINA`(100)**（用户点名的数 ✓）',
   'FRUIT_SCAN_MAX_STAMINA' in _gd
   and float(getattr(__import__('explore_loop'), 'FRUIT_SCAN_MAX_STAMINA', 0)) == 100,
   'FRUIT_SCAN_MAX_STAMINA=%s'
   % getattr(__import__('explore_loop'), 'FRUIT_SCAN_MAX_STAMINA', '（没有）'))
ck('⑫ 读不到体力 ⇒ **不扫**（fail-closed，别在状态不明时改记录 ✓）',
   '体力读不出来' in _gd and 'skip_stamina_unknown' in _gd)
_g = io.open(os.path.join(CORE, 'bot_gui.py'), encoding='utf-8').read()
# ⛔⛔ 2026-10-16 **用户口径**（本次）：
#   「**去掉扫天赋果实按钮**，点天赋果实记录要**能直接在工具那里看到果实记录，
#     不要还得去日志看**」
ck('⑬ ⛔ 「扫天赋果实」按钮**已删**（用户点名去掉 ✗；'
   '收工时体力<100 仍会**自动扫** ✓）',
   "'扫天赋果实'" not in _g, '（源码里不应再出现那颗按钮的文字）')
ck('⑭ ⭐ 工具栏有「**果实记录**」按钮',
   "'果实记录'" in _g and 'command=self.fruit_report' in _g)
# ⭐ 关键：点它 ⇒ **写工具页文本框**（`env_txt`），**不是**日志区
_fr_body = _g.split('def fruit_report')[1][:2200] if 'def fruit_report' in _g else ''
ck('⑮ ⭐⭐ 点「果实记录」⇒ **直接在工具页文本框里显示**'
   '（`env_txt`；用户：「不要还得去日志看」✗）',
   'env_txt.insert' in _fr_body and 'env_txt.delete' in _fr_body,
   '（必须走 `env_txt` —— 我第一版写的 `self.log(...)` ✗ 用户还得切日志页）')
# ⚠ 取 `fruit_report` **整个函数体**（到下一个 `def ` 为止）——
#   我第一版用 `[:2200]` 切片 ⇒ **溢到下一个方法里**了（那里本来就有 `self.log` ✗）
#   ⇒ 假红。教训同"切片别用固定长度，要用**结构边界**" ✓
# ⚠⚠ 还要**剥掉 docstring** —— 我的留档注释里**逐字写着** `self.log(...)`
#   （"我第一版写的是 `self.log(...)`"）⇒ 直接 grep 会**假红** ✗
#   本项目已踩过 N 次（"剥注释/文档字符串"那条老坑 ✓）
_fr_body = ''
if 'def fruit_report' in _g:
    _fr_body = _g.split('def fruit_report')[1].split('\n    def ')[0]
# 抠掉三引号 docstring（函数体里第一段 """ … """）
import re as _re2                                                  # noqa: E402

_fr_body_nodoc = _re2.sub(r'""".*?"""', '', _fr_body, count=1, flags=_re2.S)
ck('⑯ ⛔ `fruit_report` 的**代码**里不许用 `self.log(` 打正文'
   '（只允许"框写不进去"时的兜底 ✗；**注释不算** ⇒ 已剥 docstring）',
   _fr_body_nodoc.count('self.log(') <= 2,
   '代码里 self.log 出现 %d 次（2 次 = 那个兜底分支 ✓）'
   % _fr_body_nodoc.count('self.log('))
_sv2 = io.open(os.path.join('bot_gui_ui', 'services.py'),
               encoding='utf-8').read()
ck('⑰ ⛔ 「扫果实」那条服务通道也删了（不留死代码 ⇒ 免得日后误解还在用 ✗）',
   'fruit_scan_async' not in _sv2 and 'def _fruit_scan' not in _sv2)
ck('⑱ ⭐ 收工时自动扫仍在（去掉按钮**不影响**自动扫描 ✓）',
   '_fr.scan_and_record' in io.open(os.path.join(CORE, 'explore_loop.py'), encoding='utf-8').read())

print()
print('【5】记录文件按窗口独立（用户口径：「要每个窗口独立计算」✓）')
ck('⑯ 记录路径 = `runs/<tag>/fruit_record.json`（跟着 Bot 的 runs 目录 ✓）',
   'fruit_record.json' in io.open(os.path.join(CORE, 'fruit.py'), encoding='utf-8').read()
   and 'b.runs' in io.open(os.path.join(CORE, 'fruit.py'), encoding='utf-8').read())

# ⛔⛔ 2026-10-16 **撤回守门**（我自己试出来的真不一致）：
#   没 Bot 时的路径必须**与 `Bot.__init__` 逐字同口径** ——
#     `self.runs = os.path.join(RUNS, self.tag) if self.tag else RUNS`
#   ⇒ **`tag` 空 ⇒ `runs/`**，**不是** `runs/default/` ✗
#   ---- 病（我当时就写错了）----
#     `record_path(None)` 退到 `runs/` 根，而 `record_path(None,'fruit')`
#     是 `runs/fruit/` ⇒ `fruit.py --show`（不带 tag）**看不到**扫描写下的记录 ✗
#   ⇒ 这条断言把"三处口径"钉死（`fruit.record_path` / `Bot.runs` / GUI）✓
_rp = F.record_path
ck('⑰ ⛔ `record_path(None, None)` == `runs/`（**不是** `runs/default/` ✗'
   '，与 `Bot.__init__` 逐字对齐 ✓）',
   _rp(None, None).replace('\\', '/').endswith('/runs/fruit_record.json'),
   _rp(None, None))
ck('⑱ ⛔ `record_path(None, "")` 与 `record_path(None, None)` **同一个文件**'
   '（tag 空就是单开 ⇒ 两条路不能分叉 ✓）',
   _rp(None, '') == _rp(None, None), '%s vs %s' % (_rp(None, ''),
                                                  _rp(None, None)))
ck('⑲ ⭐ `record_path(None, "acc1")` == `runs/acc1/fruit_record.json`'
   '（有 tag 就跟 tag ✓ 与 `Bot(tag=...).runs` 一致）',
   _rp(None, 'acc1').replace('\\', '/').endswith('/runs/acc1/fruit_record.json'),
   _rp(None, 'acc1'))
_guisrc = io.open(os.path.join(CORE, 'bot_gui.py'), encoding='utf-8').read()
ck('⑳ ⭐ GUI 的 `_fruit_path` **复用 `fruit.record_path`**'
   '（不自己拼路径 ⇒ 不会与扫描分叉 ✓）',
   'import fruit as _fr' in _guisrc and '_fr.record_path(None, self.tag)'
   in _guisrc,
   '（我第一版在 GUI 里自己拼 `runs/<tag or default>/` ⇒ 与 CLI 不一致 ✗）')

print()
print('=' * 86)
if FAILS:
    print('通过 %d 项，失败 %d 项' % (N[0], len(FAILS)))
    for f in FAILS:
        print('   ✗ %s' % f)
    raise SystemExit(1)
print('通过 %d 项，失败 0 项' % N[0])
