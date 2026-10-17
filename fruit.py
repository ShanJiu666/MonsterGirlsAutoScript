# -*- coding: utf-8 -*-
"""天赋果实记录（2026-10-16）

用户口径（原话，分三次说的）：
    ① 「最后的最后（**做完日常，招募什么的且体力小于100就是最后了**）
       去**背包道具**里扫描下天赋果实数量，并且记录」
    ② 「类似**小助手的天赋果实记录**，做好放到**工具栏**里」
    ③ 补问确认：「存 runs 里吧，要**每个窗口独立计算**」
       「**自动扫描**，工具那里能看到天赋果实获取记录」

════════════════════════════════════════════════════════════════════
一、道具与图标（从游戏数据表查实）
════════════════════════════════════════════════════════════════════
`Special_Item` 里：
    `special_item_10` ⇒ `IDs = D00002_001`、`Name = 天赋果实`
    描述「**可激活角色的隐藏天赋。**」、`Type = 货币`
⚠ 与小助手 `FruitRecordView` 里的 `../Shop/D00002_001.png` **同一个道具 ID** ✓
⇒ 所以"小助手的天赋果实记录"和本模块记的是**同一个东西** ✓

════════════════════════════════════════════════════════════════════
二、小助手的记录口径（我逐字读了 `FruitRecordView-BKmsJjOZ.js`）
════════════════════════════════════════════════════════════════════
它是**手动输入**的（人自己填"今天有多少个"），存 `localStorage.fruit_record_data`。
每条记录：`{date, count, consumed, spreadAcrossDays, remark}`

### ⭐ 核心计算（`U(prev, curr)`，逐字复刻）
    netChange = curr.count - prev.count
    consumed  = 显式给的（若有），否则 max(0, -netChange)
    acquired  = max(0, netChange + consumed)      ← ⭐ **关键**
  ⇒ 为什么这么算：**果实会边收边用**（点天赋要消耗）
    涨了 5 个、同时用掉 3 个 ⇒ 这一天实际**获得 8 个** ✓
  ⇒ 若当天数量比上次**低了**（净减少）⇒ 那些差额**全算消耗** ✓

### 它统计的口径（我按同一套实现）
    · 总获取 = Σ acquired（**首日记录算基准，不计入** ✓）
    · 总消耗 = Σ consumed
    · 净变化 = 总获取 − 总消耗
    · 每天平均 = 总获取 / 有获取的天数跨度
    · 本周日均 / 本周新增 / 本月新增 / 日增峰值
    · 已记录天数
  ⚠ "间断天数均摊"（`spreadAcrossDays`）：两次记录隔了 N 天 ⇒
    把这段获取**按天摊平**（日均更准）✓ —— 本模块**默认开**（与小助手一致 ✓）

### ⚠ 与**小助手的一处不同**（如实说明）
    小助手是**人手动填**数量 ⇒ 想记哪天就记哪天。
    本模块是**脚本自动扫** ⇒ 只在"跑完一局收工"时记 ⇒ **每天自然最多一条** ✓
    ⇒ 所以 `consumed` 用"**净减少全算消耗**"那条兜底（不依赖人工填 ✓）

════════════════════════════════════════════════════════════════════
三、怎么扫到数量（模板匹配，与 `find_supply_icon` **同口径**）
════════════════════════════════════════════════════════════════════
· 路径：**公会 → 背包 → 道具页 → 找天赋果实图标 → 读它右下角的数量** ✓
· 模板：`templates/fruit_A_whole.png` + `_mask.png`（**从真机背包帧裁的**）
  ⚠ 掩膜把右下角**数量文字挖掉**（数量会变，不能参与匹配 ✗）
· 匹配：`TM_SQDIFF` + 掩膜 + 归一化（**逐字照抄 `find_supply_icon` 的算法** ✓）
  ⇒ 我第一版用 `TM_CCORR_NORMED` ⇒ **虚高到 0.92 但位置全错** ✗
    （大片同色背景会骗过它 ⇒ 分数高得没意义 ✓）
  ⇒ 换 `TM_SQDIFF` + 归一化后：**有果实 1.000 @ 正确格 / 无果实 0.802** ✓
· 阈值 `FRUIT_THR = 0.90`（实测 1.000 vs 0.802 之间 ✓）
· 数量：读果实格**附近**的一个纯数字 OCR 条目
  ⚠ 实测数量文字在格子**右下**（偏 (41, +9)）⇒ 按"离格心最近且是纯数字"取 ✓
  ⛔ **不写死"右下角那个坐标"** —— 格子位置会随背包排序变 ✓
"""
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import guild_common as GC                                     # noqa: E402

say = GC.say

# ══════════════════════════════════════════════════════════════════════
# ① 常量
# ══════════════════════════════════════════════════════════════════════
FRUIT_ID = 'D00002_001'
FRUIT_NAME = '天赋果实'

# 模板（相对本目录）
FRUIT_TPL = os.path.join('templates', 'fruit_A_whole.png')
FRUIT_MASK = os.path.join('templates', 'fruit_A_whole_mask.png')
# 匹配阈值：实测「有果实 1.000 @正确格」vs「无果实 0.802」⇒ 取 0.90 ✓
FRUIT_THR = 0.90
# 多尺度（模板是 720p 裁的 ⇒ 1.0 就是原生；留两档容错 ✓）
FRUIT_SCALES = (0.9, 1.0, 1.1)

# 道具网格搜索区（与 `find_supply_icon` 一致 ✓）
BAG_ITEM_BOX = (220, 1120, 40, 700)     # y0, y1, x0, x1

# 背包页签的 y 与各页签 x（真机实测：`素材102 装备231 符文360 宝箱489 道具617`）
BAG_TAB_Y = 173
BAG_TAB_ITEM_X = 617


def record_path(b=None, tag=None):
    """记录文件路径 ⇒ `runs/<tag>/fruit_record.json`（**按窗口独立** ✓）

    ⭐ 用户口径：「存 runs 里吧，要**每个窗口独立计算**」✓
      ⇒ 跟着 Bot 的 `runs` 目录走 ✓

    ⛔⛔ 2026-10-16 **修一个真不一致**（我自己的 CLI 试出来的）：
       · 有 Bot 时（扫描路径）⇒ `b.runs` = `runs/fruit/` ⇒ 文件在 `runs/fruit/` ✓
       · **没 Bot 时**（`--show` / 工具栏「果实记录」）我原来退到 `runs/` **根** ✗
         ⇒ 于是 `--show` **看不到**扫描写下的记录（**两个地方** ✗）
       ⇒ 修法：**没 Bot 也照 Bot 的口径拼** ✓

    ⚠⚠ 口径**逐字对齐 `Bot.__init__`**（`mapbot.py`）：
          `self.runs = os.path.join(RUNS, self.tag) if self.tag else RUNS`
        ⇒ **`tag` 有值** ⇒ `runs/<tag>/`
          **`tag` 空**   ⇒ `runs/`（**不是** `runs/default/` ✗）
    ⚠ 所以本函数**不能**用 `tag or 'default'` —— 那会与 Bot 分叉 ✗
      （单开时 Bot 写 `runs/`，而这里读 `runs/default/` ⇒ 又看不到 ✗）
    """
    if b is not None:
        try:
            return os.path.join(b.runs, 'fruit_record.json')
        except Exception:                                       # noqa: BLE001
            pass
    base = os.path.join(HERE, 'runs', tag) if tag else os.path.join(HERE, 'runs')
    return os.path.join(base, 'fruit_record.json')


# ══════════════════════════════════════════════════════════════════════
# ② 扫描：背包 → 道具 → 找果实 → 读数量
# ══════════════════════════════════════════════════════════════════════
def find_fruit(b, img=None):
    """在**背包道具页**里找天赋果实 ⇒ `(cx, cy, score)` 或 None

    ⚠ 算法与 `explore_loop.find_supply_icon` **逐字同口径**（`TM_SQDIFF` + 掩膜 +
      归一化）—— 见本文件头"三、怎么扫到数量"里那段（我第一版用错了算法 ✗）
    """
    import cv2
    import numpy as np
    tp = os.path.join(HERE, FRUIT_TPL)
    mp = os.path.join(HERE, FRUIT_MASK)
    if not (os.path.exists(tp) and os.path.exists(mp)):
        say('   ⚠ 果实模板缺失：%s' % FRUIT_TPL)
        return None
    tpl = cv2.imdecode(np.fromfile(tp, dtype=np.uint8), cv2.IMREAD_COLOR)
    msk = cv2.imdecode(np.fromfile(mp, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if tpl is None or msk is None:
        say('   ⚠ 果实模板读不出来')
        return None
    if img is None:
        img = b.img()
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    y0, y1, x0, x1 = BAG_ITEM_BOX
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    sub = sub.astype(np.float32)
    best = None
    for _us in FRUIT_SCALES:
        _w = int(round(tpl.shape[1] * _us))
        _h = int(round(tpl.shape[0] * _us))
        if _w < 8 or _h < 8 or _w >= sub.shape[1] or _h >= sub.shape[0]:
            continue
        _t = cv2.resize(tpl, (_w, _h),
                        interpolation=cv2.INTER_AREA).astype(np.float32)
        _m = cv2.resize(msk, (_w, _h), interpolation=cv2.INTER_NEAREST)
        _mf = (_m > 0).astype(np.float32)
        if float(_mf.sum()) < 20.0:
            continue
        res = cv2.matchTemplate(sub, _t, cv2.TM_SQDIFF, mask=_mf)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        mn, _mx, loc, _ml = cv2.minMaxLoc(res)
        _sc = 1.0 - mn / (float(_mf.sum()) * 255.0 * 255.0)
        if best is None or _sc > best[0]:
            best = (_sc, _us, x0 + loc[0] + _w // 2, y0 + loc[1] + _h // 2)
    if best is None:
        return None
    score, _used, cx, cy = best
    say('   · 果实识图最好成绩 %.3f @(%d,%d) 尺度 %.2f（阈值 %.2f）'
        % (score, cx, cy, _used, FRUIT_THR))
    return ((int(cx), int(cy), round(float(score), 3))
            if score >= FRUIT_THR else None)


def _read_count(items, cx, cy, max_d=90):
    """读果实图标**附近**的数量（纯数字条目）⇒ int / None

    ⚠ 实测数量文字在格子**右下**（偏 (41, +9)）——
      但**不写死那个偏移**（格子位置会随排序变 ✓）
      ⇒ 取"离格心最近、且是纯数字"的那一条 ✓
    ⚠ 排除那些**明显是别的东西**的数字：只认 `cx` 在格心**右侧**、
      `cy` 在格心**±40** 内的（数量都印在右下角 ✓）
    """
    best = None
    for it in (items or []):
        t = str(it.get('text') or '').strip()
        if not t.isdigit():
            continue
        _cx, _cy = it.get('cx', -9999), it.get('cy', -9999)
        if abs(_cy - cy) > 40:
            continue
        if not (cx - 10 <= _cx <= cx + max_d):
            continue
        d = abs(_cx - cx) + abs(_cy - cy)
        if best is None or d < best[0]:
            best = (d, int(t), it)
    return best[1] if best else None


def scan(b, log=None, leave=True, enter_guild=True):
    """扫一次天赋果实数量 ⇒ `{'ok':…, 'count':…, 'why':…}`

    流程（**真机实测**）：
        ① `GC.goto_guild` 进公会
        ② 点 `BAG_BTN` 开背包
        ③ 点「**道具**」页签（x=617, y=173 —— 实测页签就在这一行 ✓）
        ④ `find_fruit` 找果实 ⇒ 读它右下角的数量
        ⑤ 关背包（点右上 X）
        ⑥ 需要的话 `GC.leave_guild` 回选图
    ⚠ 每一步都**验**；失败**如实返回**，绝不瞎报一个数 ✓
    """
    log = log if log is not None else []
    res = {'ok': False, 'count': None, 'why': None,
           'score': None, 'at': None}
    say('')
    say('=' * 62)
    say('🍒 扫天赋果实（背包 → 道具 → 读数量）')
    say('=' * 62)

    if enter_guild:
        if not GC.goto_guild(b, log):
            say('   ✗ 进不了公会 ⇒ 放弃（不瞎报数字 ✓）')
            res['why'] = 'not_in_guild'
            return res

    # ② 开背包（用生产锚点 ✓）
    try:
        import explore_loop as _EL
        bag_btn = tuple(_EL.BAG_BTN)
    except Exception:                                           # noqa: BLE001
        bag_btn = (643, 1120)
    b.tap(bag_btn[0], bag_btn[1], wait=2.6)
    items = GC.ocr_items(b, tag='fruit_bag')
    _opened = GC.has(items, '背包', '素材', '装备', '符文', '道具', '宝箱')
    GC._log(log, {'fruit': 'open_bag', 'at': bag_btn, 'opened': _opened})
    say('   · 开背包 %s ⇒ %s' % (bag_btn, '已打开 ✓' if _opened else '没打开 ✗'))
    if not _opened:
        res['why'] = 'bag_not_open'
        return res

    # ③ 道具页签（**点 OCR 现读的坐标**优先；读不到才用标定 ✓）
    it = GC.find(items, '道具')
    tab = (int(it['cx']), int(it['cy'])) if it else (BAG_TAB_ITEM_X, BAG_TAB_Y)
    b.tap(tab[0], tab[1], wait=2.4)
    items = GC.ocr_items(b, tag='fruit_items')
    GC._log(log, {'fruit': 'tap_item_tab', 'at': tab,
                  'by': 'ocr' if it else 'calib'})
    say('   · 切「道具」页 %s %s' % (tab, '（OCR 现读）' if it else '（标定）'))

    # ④ 找果实 + 读数量
    hit = find_fruit(b)
    if not hit:
        say('   ✗ 识图没找到「天赋果实」⇒ 如实报失败'
            '（可能这号背包里没有它 ✓）')
        GC._log(log, {'fruit': 'not_found'})
        res['why'] = 'fruit_not_found'
        _close_bag(b, log)
        if leave:
            _back(b, log)
        return res
    cx, cy, score = hit
    res['score'] = score
    res['at'] = (cx, cy)
    items2 = GC.ocr_items(b, tag='fruit_cnt')
    cnt = _read_count(items2, cx, cy)
    GC._log(log, {'fruit': 'icon_hit', 'at': (cx, cy), 'score': score,
                  'count': cnt})
    say('   · 认到果实 (%d,%d) 分数 %.3f ⇒ 数量 = **%s**'
        % (cx, cy, score, cnt if cnt is not None else '读不到 ✗'))
    _close_bag(b, log)
    if leave:
        _back(b, log)
    if cnt is None:
        res['why'] = 'count_unreadable'
        return res
    res['ok'] = True
    res['count'] = cnt
    say('   ✓ 天赋果实 = **%d** 个' % cnt)
    say('=' * 62)
    return res


def _close_bag(b, log=None):
    """关背包：先试**右上角 X**（弹窗系 671,126），再试 `_close_bag` ✓"""
    try:
        import explore_loop as _EL
        if hasattr(_EL, '_close_bag'):
            _EL._close_bag(b, b.ocr(tag='fruit_close'), log)
            return True
    except Exception as e:                                      # noqa: BLE001
        GC._log(log, {'fruit': 'close_bag_err', 'e': repr(e)[:100]})
    try:
        b.tap(671, 126, wait=1.8)
    except Exception:                                           # noqa: BLE001
        return False
    return True


def _back(b, log=None):
    """回选图界面（用户口径：「这三个脚本的最后都要回到地图界面」同理 ✓）"""
    try:
        ok = GC.leave_guild(b, log)
        GC._log(log, {'fruit': 'back_to_map', 'ok': bool(ok)})
        say('   · %s' % ('已返回地图界面 ✓' if ok else '⚠ 没确认回到选图界面'))
        return ok
    except Exception as e:                                      # noqa: BLE001
        GC._log(log, {'fruit': 'back_err', 'e': repr(e)[:100]})
        return False


# ══════════════════════════════════════════════════════════════════════
# ③ 记录 + 统计（**逐字复刻小助手 `FruitRecordView` 的口径**）
# ══════════════════════════════════════════════════════════════════════
def load_records(b=None, path=None):
    """读记录 ⇒ `[{'date','count','consumed','spreadAcrossDays','remark'}, …]`

    ⚠ 格式与小助手 `localStorage.fruit_record_data` **同构**（数组 + 同样字段 ✓）
      ⇒ 以后想导出给小助手/从它导入都方便 ✓
    """
    p = path or record_path(b)
    if not os.path.exists(p):
        return []
    try:
        with io.open(p, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get('records'), list):
            d = d['records']
        if not isinstance(d, list):
            return []
        return [r for r in d if isinstance(r, dict) and r.get('date')
                and isinstance(r.get('count'), int)]
    except Exception:                                           # noqa: BLE001
        return []


def save_records(recs, b=None, path=None):
    """写记录（**原子写**：先写临时文件再替换 ⇒ 断电/崩溃不会写坏 ✓）"""
    p = path or record_path(b)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(recs, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
        return True
    except Exception as e:                                      # noqa: BLE001
        say('   ⚠ 记录写入失败：%r' % (e,))
        return False


def _today():
    return time.strftime('%Y-%m-%d')


def _d2(s):
    """`YYYY-MM-DD` ⇒ date 对象（失败 ⇒ None）"""
    import datetime as _dt
    try:
        y, m, d = [int(x) for x in str(s).split('-')[:3]]
        return _dt.date(y, m, d)
    except Exception:                                           # noqa: BLE001
        return None


def diff_of(prev, curr):
    """**逐字复刻**小助手的 `U(prev, curr)` ⇒ `(net, consumed, acquired)`

        净变化  = curr.count - prev.count
        消耗    = 显式给的（若有），否则 max(0, -净变化)
        获取    = max(0, 净变化 + 消耗)      ← ⭐ 边收边用 ⇒ 涨了5个+用掉3个 = 获得8个
    """
    net = int(curr.get('count') or 0) - int(prev.get('count') or 0)
    if 'consumed' in (curr or {}) and curr.get('consumed') is not None:
        cons = max(0, int(curr.get('consumed') or 0))
    else:
        cons = max(0, -net)
    acq = max(0, net + cons)
    return net, cons, acq


def merge_by_day(recs):
    """把**同一天的多条**合并成**一条** ⇒ 新列表（按日期升序）

    ⭐⭐⭐ 2026-10-16 **用户口径**（原话）：
        「**本天内多次统计要计入一天内，不要当成多天**」

    ---- 为什么需要它（我实测抓到的）----
      `record()` 走的是"同一天**覆盖更新**"⇒ 正常路径**本来就只有一条** ✓
      但**记录文件是人可读可编辑的**（用户口径要"存 runs 里"，就是打算能看能改 ✓）
      而且小助手那份格式是**数组**（能被导入/导出）⇒ **同一天两条是可能的** ✗
      实测（`_tmp_probe_dispatch/probe_sameday.py`）：同一天有 2 条时
        · `days = 3`（**数的是条数** ✗ 应为 2）
        · `peak = 66`（**同一天被劈成两天** ⇒ 峰值算错 ✗ 应为 76）
      ⇒ 所以**不能假设"每人只写一条"** ⇒ 统计前必须**按天归一** ✓

    ---- 合并规则 ----
      · **取当天最后一条的 count**（一天里越晚越准 ✓）
      · `consumed` 取**最大**（同一天多次记的消耗不该丢 ✓）
      · `remark` **非空的拼起来**（别丢备注 ✓）
      · `spreadAcrossDays` 取**最后一条**的（它是"这天怎么摊"的属性 ✓）
    ⚠ 日期解析失败的条目**原样保留**（宁可多一条也别悄悄丢数据 ✓）
    """
    byday = {}
    order = []
    passthrough = []
    for r in (recs or []):
        d = str(r.get('date') or '')
        if _d2(d) is None:
            passthrough.append(r)
            continue
        if d not in byday:
            byday[d] = dict(r)
            order.append(d)
            continue
        old = byday[d]
        # count 取**后一条**（列表里越靠后越晚；`record()` 也是这么覆盖的 ✓）
        old['count'] = int(r.get('count') or 0)
        # consumed 取最大（多次记的消耗别丢）
        if r.get('consumed') is not None:
            old['consumed'] = max(int(old.get('consumed') or 0),
                                  int(r.get('consumed') or 0))
        # 备注拼接（去重、保持顺序）
        _r1 = str(old.get('remark') or '').strip()
        _r2 = str(r.get('remark') or '').strip()
        _parts = [x for x in (_r1, _r2) if x]
        if _parts:
            _seen, _keep = set(), []
            for p in _parts:
                if p not in _seen:
                    _seen.add(p)
                    _keep.append(p)
            old['remark'] = '，'.join(_keep)
        if r.get('spreadAcrossDays') is not None:
            old['spreadAcrossDays'] = r.get('spreadAcrossDays')
    out = [byday[d] for d in sorted(order)] + passthrough
    return out


def stats(recs):
    """按小助手那套口径算统计 ⇒ dict

    返回：`total_get / total_used / net / days / avg / peak /
           today / today_got / today_used / last / last_date`
    ⚠ "**首日算基准**、不计入获取"（小助手口径 ✓）
    ⚠ `spreadAcrossDays`（间断天数均摊）默认开 ⇒ 日均按**跨度**算 ✓
    ⭐⭐ 2026-10-16 **先按天归一**（用户口径：「本天内多次统计要计入一天内」✓）
      ⇒ 同一天绝不会被当成多天 ✓（见 `merge_by_day` 的实测依据 ✓）
    """
    rs = merge_by_day([r for r in (recs or []) if r.get('date')])
    out = {'total_get': 0, 'total_used': 0, 'net': 0, 'days': len(rs),
           'avg': 0, 'peak': 0, 'today': _today(), 'today_got': 0,
           'today_used': 0, 'last': None, 'last_date': None,
           'span_days': 0}
    if not rs:
        return out
    span = 0
    for i in range(1, len(rs)):
        p, c = rs[i - 1], rs[i]
        _net, cons, acq = diff_of(p, c)
        out['total_used'] += cons
        out['total_get'] += acq
        if acq > 0:
            out['peak'] = max(out['peak'], acq)
            d1, d2 = _d2(p['date']), _d2(c['date'])
            gap = (d2 - d1).days if (d1 and d2) else 1
            # 「间断天数均摊」：跨 N 天就按 N 天摊（小助手默认开 ✓）
            span += gap if c.get('spreadAcrossDays', True) is not False else 1
        if c['date'] == out['today']:
            out['today_got'] = acq
            out['today_used'] = cons
    out['net'] = out['total_get'] - out['total_used']
    out['span_days'] = span
    out['avg'] = int(round(out['total_get'] / span)) if span > 0 else 0
    out['last'] = rs[-1]
    out['last_date'] = rs[-1]['date']
    return out


def record(b, count, log=None, consumed=None, remark='', path=None):
    """记一条（同一天**覆盖更新**）⇒ `(ok, stats)`

    ⚠ 同一天重复扫 ⇒ **更新**那一条（不新增 ✗）—— 与小助手 `hr()` 一致 ✓
    ⚠ `consumed` 不给 ⇒ 交给 `diff_of` 按"净减少"兜底 ✓
    """
    log = log if log is not None else []
    recs = load_records(b, path)
    today = _today()
    item = {'date': today, 'count': int(count),
            'spreadAcrossDays': True, 'remark': remark}
    if consumed is not None:
        item['consumed'] = max(0, int(consumed))
    # ⭐⭐ 2026-10-16 **先按天归一**（用户口径：「本天内多次统计要计入一天内」✓）
    #   ---- 为什么写之前就要归一 ----
    #     文件是**人可读可编辑**的（用户要"存 runs 里"就是想能看能改 ✓），
    #     同一天**可能已经有两条**（手工编辑 / 从别处导入 / 老版本写下的 ✗）
    #     ⇒ 若只 `next(...)` 找**第一条**，会漏掉后面那条 ⇒ 又变成"同一天两天" ✗
    #   ⇒ 归一之后再更新，保证**一天只有一条** ✓
    recs = merge_by_day(recs)
    idx = next((i for i, r in enumerate(recs) if r.get('date') == today), -1)
    if idx >= 0:
        # 更新：保留原有的 consumed（除非显式给）与小助手同口径 ✓
        old = recs[idx]
        if consumed is None and 'consumed' in old:
            item['consumed'] = old.get('consumed')
        if remark and old.get('remark'):
            # 备注**累加**（不覆盖 ✓）—— 与 `merge_by_day` 的拼接口径一致 ✓
            item['remark'] = '，'.join([x for x in (old['remark'], remark) if x])
        recs[idx] = item
    else:
        recs.append(item)
    ok = save_records(recs, b, path)
    st = stats(recs)
    GC._log(log, {'fruit': 'record', 'date': today, 'count': int(count),
                  'updated': idx >= 0, 'ok': ok,
                  'total_get': st['total_get'], 'days': st['days']})
    say('   · 记录 %s：%d 个（%s）｜累计获取 %d ｜日均 %d'
        % (today, int(count), '更新' if idx >= 0 else '新增',
           st['total_get'], st['avg']))
    return ok, st


def scan_and_record(b, log=None, leave=True):
    """**扫一次 + 记一条**（收工/工具栏都用这个）⇒ `(ok, res, stats)`"""
    log = log if log is not None else []
    res = scan(b, log, leave=leave)
    if not res.get('ok'):
        return False, res, stats(load_records(b))
    ok, st = record(b, res['count'], log)
    return ok, res, st


# ══════════════════════════════════════════════════════════════════════
# ④ 报告（给工具栏/控制台看）
# ══════════════════════════════════════════════════════════════════════
def report_text(b=None, path=None, limit=20):
    """人看的记录文本（**给小助手的口径对齐**：总获取/日均/本周/本月/峰值 ✓）

    ⭐ 2026-10-16：表格也用 `merge_by_day` 的结果 ⇒
      **同一天绝不出现两行**（用户口径：「本天内多次统计要计入一天内」✓）
    """
    recs = load_records(b, path)
    st = stats(recs)
    lines = []
    lines.append('🍒 天赋果实记录（%s）' % ('共 %d 天' % st['days']
                                            if st['days'] else '还没有记录'))
    if not recs:
        lines.append('   （跑完一局收工后会自动扫一次；也可点「扫天赋果实」手动扫）')
        return '\n'.join(lines)
    lines.append('   最新：%s ⇒ **%s 个**'
                 % (st['last_date'], st['last']['count']))
    lines.append('   累计获取 %d 个 ｜ 累计消耗 %d 个 ｜ 净变化 %+d'
                 % (st['total_get'], st['total_used'], st['net']))
    lines.append('   每天平均 %d 个/天（有效跨度 %d 天）｜ 日增峰值 %d'
                 % (st['avg'], st['span_days'], st['peak']))
    if st['today_got'] or st['today_used']:
        lines.append('   今日：获取 +%d ｜ 消耗 %d'
                     % (st['today_got'], st['today_used']))
    lines.append('   ⓘ 同一天的多次扫描**只算一天**（取当天最后一次的数量）✓')
    lines.append('')
    lines.append('   日期          数量   获取   消耗   备注')
    lines.append('   ' + '-' * 52)
    # ⚠ **必须用 merge_by_day 的结果**（否则同一天会出现两行 ✗）
    rs = merge_by_day(recs)
    for i, r in enumerate(rs):
        if i == 0:
            lines.append('   %-12s %5s   %4s   %4s   %s'
                         % (r['date'], r['count'], '基准', '-',
                            r.get('remark') or ''))
            continue
        _net, cons, acq = diff_of(rs[i - 1], r)
        lines.append('   %-12s %5s   %+4d   %4d   %s'
                     % (r['date'], r['count'], acq, cons,
                        r.get('remark') or ''))
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════
# ⑤ CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    import argparse
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:                                           # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='天赋果实：扫描 / 记录 / 看统计')
    ap.add_argument('--device', default=None, help='adb 设备号')
    ap.add_argument('--tag', default='fruit', help='实例名')
    ap.add_argument('--scan', action='store_true', help='扫一次并记录')
    ap.add_argument('--show', action='store_true', help='只看记录（不碰设备）')
    ap.add_argument('--no-record', action='store_true', help='只扫不记')
    ap.add_argument('--set', type=int, default=None,
                    help='手动记一个数量（不碰设备；调试/补录用）')
    a = ap.parse_args()

    if a.show:
        say(report_text(None, record_path(None, a.tag)))
        return 0
    if a.set is not None:
        # ⚠ 补录也要落到**这个 tag 的记录文件**里（与扫描同一个 ✓）
        ok, st = record(None, a.set, path=record_path(None, a.tag))
        say(report_text(None, record_path(None, a.tag)))
        return 0 if ok else 1

    if a.device:
        GC.set_device(a.device)
    import mapbot as MB
    b = MB.Bot(log_prefix='fruit', serial=a.device, tag=a.tag)
    log = []
    if a.no_record:
        r = scan(b, log)
        say(report_text(b))
        return 0 if r.get('ok') else 1
    ok, r, st = scan_and_record(b, log)
    say('')
    say(report_text(b))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
