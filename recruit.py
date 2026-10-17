# -*- coding: utf-8 -*-
"""recruit.py · **免费指定招募**（大厅中央大门 → 「指定招募」弹窗）

用户口径（2026-10-14，原话）
--------------------------
· 「现在这个界面是免费招募界面」
· 「你了解下机制，**抄一下小助手的选项判断机制**，**尽量能拿到高等级角色**」

机制（游戏源码 `PublicSummonPanel` 逐字确证）
--------------------------------------------
1. 大厅中央大门 ⇒ 弹「**指定招募**」面板（`PublicSummon_GLD`）
2. 面板上有 **N 个候选标签**（实测本号 **7 个**，菱形排布）
   —— 候选池由**服务端每日下发**（`save.publicSummonTags`），
     **不可重 roll**、**只能取消再选** ✓
3. 选 **1~3 个**（源码：`>=3` 提示「标签选择数量已达上限」；
   `<1` 提示「至少需要选择一个标签」）
4. 点「招募」⇒ `POST /Summon/PublicSummon {SelectedTags}` ⇒ **固定只出 1 个角色** ✓
5. 免费旗标：主界面文字从「**免费指定招募**」变成「角色招募」（每天 1 次）✓

「选项判断机制」= 小助手那套（**已逐字逆向 + 对拍过**）
-----------------------------------------------------
`Re` 匹配 + 组合枚举 + 加权排序（`_tmp_xzs/SNIPPETS.txt` 有逐字代码）：

    Re(角色, 标签) = 标签=='传说' ? 角色.稀有度==3
                   : 标签=='史诗' ? 角色.稀有度==2
                   : 角色.职业==标签 or 角色.种族==标签
                     or 角色.属性==标签 or 角色.地区==标签

    # 对 k=1..min(标签数,3) 的所有组合：
    命中 = [角色 for 角色 in 表 if 组合里每个标签都 Re 命中]
    if not 命中: 跳过
    minR = min(角色.稀有度 for 角色 in 命中)      # ⚠ **保底**最低稀有度，不是最高
    含传说 = 1 if 有角色.稀有度==3 else 0
    心愿   = 1000 if (minR>=2 and 命中里有心愿角色) else 0
    权重   = minR*100 + 含传说*10 + 组合长度*0.1 + 心愿

    ⇒ 按权重**降序**取第一名 ⇒ 那就是要选的标签组合 ✓

⚠⚠ **一个必须讲清的语义**（我第一版理解反了，小助手报告里明确纠正过）：
  `minR` 取的是**保底**（这组标签"最差"能出到什么稀有度），**不是最高**。
  所以 `射手+森林` 得 `minR=0`（因为候选里含普通角色）⇒ **反而是最差组合**。
  这正是用户要的「**尽量拿高等级角色**」——**保底越高越好** ✓

角色表从哪来（⭐ 本脚本的**关键决定**）
------------------------------------
⛔ **不抄**小助手那份 142 行快照（`_tmp_xzs/roles.json`）——
   实测对拍：它 = 游戏表推出来的 140 行 ＋ **1 条脏数据**
   （`当前普通池未出非限定火山`）＋ **1 个名字已漂移的旧条目**
   （`法师波波` 在游戏里叫 `啵啵`）✗
⇒ 直接**从游戏数据表实时推**（`paths.find_datatable()`）：
     `Source` 为空（= `canBePublicSummon` 源码判据）且 `IDs` 不含 `_`（非皮肤）
   逐字段对拍实测：**与小助手交集 140 行、稀有度分布一致** ✓
⇒ 好处：游戏更新角色后**不用改代码**，永远同步 ✓
⚠ 数据表**可能不存在**（换机/精简包）⇒ 那时退回**内置兜底表**并**显式告警** ✓

用法
----
    # 只分析、不招募（**零消耗**）：读当前 7 个标签 → 算出最优组合
    python recruit.py --device 127.0.0.1:16448 --analyze

    # 真招募（会花掉当天那一次免费机会）
    python recruit.py --device 127.0.0.1:16448

    # 试跑：一下都不点
    python recruit.py --device 127.0.0.1:16448 --dry-run
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import guild_common as GC                                  # noqa: E402

say = GC.say

# ══════════════════════════════════════════════════════════════════════
# ① 坐标（真机实测 2026-10-14，实例B测试号 16448）
# ══════════════════════════════════════════════════════════════════════
# ⭐⭐⭐⭐⭐ 2026-10-15 **正确入口**（用户教的，原话）：
#   「**少了两步，在公会界面要点击右下角的招募，再点击免费招募才有那个界面**」
#   ---- 两条实测路径 ----
#     ① 公会界面 → 右下角图标「**招募**」= **(628, 1040)**
#        （那一组 6 个图标：邮件/商店/招募 · 成就/公告/背包；
#          招募是右上角那个，图标 y≈1020、文字「招募」y≈1055 ⇒ 取 **1040** ✓）
#     ② 招募主页 → 左下角「**指定招募（免费）**」= **(145, 905)**
#        （实测文字「指定招募」在 (145,871)、「免费」在 (168,910)
#          ⇒ 按钮中心取 **905** ✓）
#   ⚠ 两处都优先 **OCR 现读**，读不到才退这两个标定值 ✓
GUILD_RECRUIT_BTN = (628, 1040)
# 大厅中央大门（**老路径，已降级为兜底** —— 用户纠正后它不再是主入口 ✓）
HALL_DOOR = (360, 690)
# ⭐⭐⭐ 2026-10-15 用户口径：「**最后要返回到地图界面**」✓
#   ⇒ 招募流程收尾**默认就返回选图界面**（不是可选项）✓
#   ⚠ 想停在招募页手动看：`return_to_map=False` 或 CLI `--no-back`
RETURN_TO_MAP = True
# ⭐⭐ 招募**主页**上的「指定招募」按钮（真机实测 2026-10-14）
#   主页三颗按钮（从左到右）：**指定招募(免费)** ｜ 招募一次! ｜ 招募十次!!
#   实测：左上那颗带红点、标着「免费」⇒ 点它进标签面板 ✓
#   ⚠ 坐标 **(125, 905)**：那是**整颗按钮**的中心（含「指定招募」字样与「免费」行）
RECRUIT_FREE_BTN = (125, 905)
RECRUIT_FREE_TXT = (125, 871)       # 文字「指定招募」那一行（OCR 命中点）
# 「指定招募」弹窗
RECRUIT_TITLE = '指定招募'
RECRUIT_CLOSE_X = (671, 126)        # 招募页右上角 X（**离开招募页**用 ✓）
RECRUIT_BTN = (360, 963)            # 「招募」按钮（选中标签后才可点）
RECRUIT_TIP_XY = (353, 806)         # 「最多选择3个标签…（N/3）」提示行
# ⭐⭐⭐ 2026-10-15 招募**收尾链**（用户口径：「跳过动画，那几步，最后要返回到地图界面」）
#   · 「跳过」= **(360, 963)** —— **与「招募」同位**（实测：点完招募，
#     同一位置那颗按钮的文案变成「跳过」✓）
#   · 「结束招募」= **(360, 1214)** —— 真机结果屏实测（综合模拟器 2026-10-15）✓
SKIP_BTN = (360, 963)
RECRUIT_END_BTN = (360, 1214)

# ⚠ 标签是**菱形排布**（实测 7 个，位置固定但**个数随账号/日期变**）
#   ⇒ 不能写死"第几个标签在哪"，必须**按 OCR 文字坐标现读** ✓
#     （真机实测：沙漠(373,465) 光系(227,532) 地系(518,532) 器灵(373,599)
#        生灵(227,664) 亡灵(519,665) 法师(373,730)）
TAG_BAND = (400, 800)               # 标签只可能落在这一段 y 里（收 OCR 用）
# ⛔⛔ 2026-10-14 真机实测：**不要往左偏**！`TAG_TAP_DX` 我一开始写 -95，
#   结果**点空了**（计数器不动、面板还被关掉）✗
#   ---- 量出来的按钮实际范围（`沙漠` 那一行，见 `g_tag1.png`）----
#     · 按钮整体 x ≈ **268~445**（含左侧宝石与文字）
#     · 文字「沙漠」中心 x = **373**（OCR 给的就是这个）✓
#     · 我点 **279** —— 名义上"还在按钮内"，可真机就是不生效 ✗
#   ---- 结论：**直接点 OCR 给的文字中心**最稳 ✓ ----
#     实测 `(373,465)` ⇒ 计数器 `0/3 → 1/3` 立刻生效 ✓
#     理由：文字中心**一定**在按钮的可点区内（游戏就是让玩家点它的 ✓），
#       而宝石那一段可能只是**装饰**、不在 Button 的 hitbox 里 ✗
TAG_TAP_DX = 0                      # ← **不偏移**（保留常量是为了让这个教训可见 ✓）

# ══════════════════════════════════════════════════════════════════════
# ② 角色表：从游戏数据表**实时推**（见文件头说明）
# ══════════════════════════════════════════════════════════════════════
# 位阶 → 稀有度（小助手 `Ne={3:传说,2:史诗,1:稀有,0:普通}` ✓ 同口径）
STEP2RARITY = {'S': 3, 'A': 2, 'B': 1, 'C': 0}
RARITY_CN = {3: '传说', 2: '史诗', 1: '稀有', 0: '普通'}

#: 数据表读不到时的**兜底**（只放"四大类"的取值域，用于让脚本还能跑）
#: ⚠ 兜底**不参与选最优**（那样等于瞎猜 ✗）—— 只在"读不到表"时用来**识别标签类别**，
#:   并**显式告警**让用户知道这次没算最优 ✓
FALLBACK_TAGS = {
    '职业': ('射手', '法师', '战士', '牧师'),
    '种族': ('生灵', '亡灵', '神灵', '魔灵', '器灵'),
    '属性': ('光系', '风系', '火系', '水系', '暗系', '地系'),
    '地区': ('平原', '森林', '沙滩', '海洋', '山脉', '沙漠', '星界', '雪原', '火山'),
    '星级': ('史诗', '传说'),
}


def load_roles(path=None):
    """读游戏数据表 ⇒ [(名字, 职业, 种族, 属性, 地区, 稀有度)]

    ⛔ 判据逐字照抄游戏源码（`RoleDataTable.RoleDataItem`）：
        `canBePublicSummon => string.IsNullOrEmpty(Source)`  ← **Source 为空**
        `isSkin            => IDs.Contains('_')`             ← 皮肤要排除
    ⇒ 与"招募池"口径**同源**，不是我自己编的筛选 ✓
    """
    p = path or _datatable_path()
    if not p or not os.path.exists(p):
        return None, '找不到游戏数据表（%s）' % (p,)
    try:
        with io.open(p, encoding='utf-8') as f:
            d = json.load(f)
        R = (d or {}).get('Role') or {}
    except Exception as e:                              # noqa: BLE001
        return None, '数据表读不动（%r）' % (e,)
    out = []
    for _k, v in R.items():
        try:
            if (v.get('Source') or '').strip():
                continue                    # 非 canBePublicSummon ⇒ 不进招募池 ✓
            ids = str(v.get('IDs') or '')
            if '_' in ids:
                continue                    # 皮肤 ⇒ 排除 ✓
            out.append((str(v.get('Name') or ''),
                        str(v.get('Class') or ''), str(v.get('Type') or ''),
                        str(v.get('Element') or ''), str(v.get('Map') or ''),
                        STEP2RARITY.get(str(v.get('Step') or ''), 0)))
        except Exception:                   # noqa: BLE001
            continue
    if not out:
        return None, '数据表里 Role 表是空的'
    return out, None


def _datatable_path():
    try:
        import paths as P
        return P.find_datatable()
    except Exception:                                   # noqa: BLE001
        for c in (os.path.join(HERE, 'server_datatable.json'),
                  os.path.join(HERE, '..', 'data', 'server_datatable.json')):
            if os.path.exists(c):
                return c
    return None


# ══════════════════════════════════════════════════════════════════════
# ③ 小助手的选项判断机制（**逐字移植**，见文件头）
# ══════════════════════════════════════════════════════════════════════
def tag_matches(role, tag):
    """`Re(角色, 标签)` —— 逐字对应小助手的 `Re` ✓

        Re=(e,t)=> t===`传说` ? e.稀有度===3
                  : t===`史诗` ? e.稀有度===2
                  : e.职业===t||e.种族===t||e.属性===t||e.地区===t

    ⚠ `传说`/`史诗` **只查稀有度**，不查那四个字符串字段 ✓
    """
    _n, cls, race, elem, area, rar = role
    if tag == '传说':
        return rar == 3
    if tag == '史诗':
        return rar == 2
    return tag in (cls, race, elem, area)


def rank_combos(tags, roles, wish=None, max_k=3):
    """枚举标签组合并按小助手权重排序 ⇒ [{'c':..., 'f':..., 'minR':..., 'w':...}]

    逐字对应小助手的 `Q`（`_tmp_xzs/SNIPPETS.txt` char [12532,13174)）：
        · k 从 1 到 `min(len(tags), 3)`
        · 组合用**排列外的组合**（小助手 `ze` 生成的是组合，不是排列 ✓）
        · `minR` = 命中角色里的**最低**稀有度（= 保底 ✓）
        · 权重 = minR*100 + 含传说*10 + 组合长度*0.1 + 心愿*1000
    `wish`：心愿/未拥有角色名集合（命中 +1000，绝对置顶 ✓）
    """
    wish = wish or set()
    if not tags:
        return []
    out = []
    for k in range(1, min(len(tags), int(max_k)) + 1):
        for combo in itertools.combinations(tags, k):
            hit = [r for r in roles if all(tag_matches(r, t) for t in combo)]
            if not hit:
                continue
            min_r = min(r[5] for r in hit)
            has_leg = 1 if any(r[5] == 3 for r in hit) else 0
            w_sh = 1000 if (min_r >= 2 and any(r[0] in wish for r in hit)) else 0
            w = min_r * 100 + has_leg * 10 + len(combo) * 0.1 + w_sh
            out.append({'c': list(combo), 'f': sorted(hit, key=lambda r: -r[5]),
                        'minR': min_r, 'w': w})
    out.sort(key=lambda d: -d['w'])
    return out


def badge(min_r):
    """`$=e=>e>=3?{text:'顶级招募'}:e>=2?{text:'资深保底'}:null` ✓"""
    if min_r >= 3:
        return '顶级招募'
    if min_r == 2:
        return '资深保底'
    return None


# ══════════════════════════════════════════════════════════════════════
# ④ 读面板上的标签（真机 OCR）
# ══════════════════════════════════════════════════════════════════════
def panel_open(items):
    """「指定招募」面板开着吗

    ⚠ 标题实测 OCR 读作 **「常规招募」**（`(361,126)`）——
      因为它上面那层是招募主页、标题写着「常规招募」✗
      ⇒ 真正可靠的判据是**那句提示行**（`最多选择3个标签招募特定角色（N/3）`）✓
    """
    if GC.has(items, '最多选择3个标签', '最多选择'):
        return True
    # 兜底：有标签行 + 有「招募」按钮
    return bool(read_tags(items)) and GC.has(items, '招募')


def read_tags(items, known=None):
    """把面板上的**标签**读出来 ⇒ [(名字, cx, cy)]（按 y、x 排序）

    判据（两条都要，宁可漏也不误认 ✗）：
      ① 文字在 `TAG_BAND` 的 y 带内（标签只可能在这一段）
      ② 文字**恰好等于**某个已知标签名（`exact` —— 防把说明文字骗进来）
    实测那 7 个：沙漠/光系/地系/器灵/生灵/亡灵/法师 ✓
    """
    known = set(known or _all_tag_names())
    out = []
    for it in (items or []):
        cy = it.get('cy', 0)
        if not (TAG_BAND[0] < cy < TAG_BAND[1]):
            continue
        t = str(it.get('text') or '').strip()
        if t in known:
            out.append((t, int(it.get('cx', 0)), int(cy)))
    out.sort(key=lambda d: (d[2], d[1]))
    return out


def _all_tag_names():
    """全部合法标签名（四类 + 两个星级）—— 优先从数据表取，失败用兜底表 ✓"""
    roles, _err = load_roles()
    names = set()
    if roles:
        for r in roles:
            names.update(x for x in (r[1], r[2], r[3], r[4]) if x)
    else:
        for v in FALLBACK_TAGS.values():
            names.update(v)
    names.update(FALLBACK_TAGS['星级'])
    return names


def tag_kind(tag):
    """标签属于哪一类（纯日志用）"""
    for k, vs in FALLBACK_TAGS.items():
        if tag in vs:
            return k
    return '?'


def read_counter(items):
    """读提示行里的 `（N/3）` ⇒ N（读不到 None）"""
    it = GC.find(items, '最多选择')
    if not it:
        return None
    m = GC.re.search(r'[（(]\s*(\d)\s*/\s*3\s*[)）]', it['text'])
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════════════════════════
# ⑤ 主流程
# ══════════════════════════════════════════════════════════════════════
def analyze(items, roles, wish=None, verbose=True):
    """对当前面板的标签算最优组合 ⇒ (best, all_ranked, tags)"""
    tags = [t for t, _x, _y in read_tags(items)]
    if verbose:
        say('   · 面板标签（%d 个）：%s'
            % (len(tags), ' / '.join('%s[%s]' % (t, tag_kind(t)) for t in tags)))
    if not roles:
        return None, [], tags
    ranked = rank_combos(tags, roles, wish=wish)
    if not ranked:
        return None, [], tags
    return ranked[0], ranked, tags


def pick_tags(b, chosen, tags_xy, log=None, tag='rec'):
    """按算出来的组合去**点标签** ⇒ True/False

    ⚠ 面板**每次都重新读**（点一下画面会变，缓存会骗人 ✗）
    ⚠ 点之前先看 `（N/3）` 计数器 —— 已经是 N 就不重复点（幂等 ✓）
         实测：点一下 0/3 → 1/3，面板不关、标签高亮 ✓
    """
    want = list(chosen or [])
    if not want:
        return False
    # ⛔⛔⛔ 2026-10-14 真机抓到的**第三个坑**（这条最隐蔽）：
    #   标签是 **toggle（再点一次 = 取消）**！游戏源码 `PublicSummonPanel.OnTagClicked`：
    #       `if (selectedTags.Contains(item)) selectedTags.Remove(item);
    #        else { if (count>=3) 提示; selectedTags.Add(item); }`
    #   ---- 我错在哪 ----
    #     我每轮**把三个目标标签都点一遍** ⇒ 第一轮全选中（1/3→2/3→3/3），
    #     第二轮**又把它们取消掉**（3/3→2/3→1/3）✗
    #     真机日志铁证：`计数器从 2/3 掉到 1/3（点到已选的了）` ✗
    #   ---- 修法 ----
    #     ① **只点"还差的那几个"** —— 可我**读不出"哪几个已选中"**（面板没有勾选标记的
    #        OCR 文本）⇒ 所以不能靠"逐个确认" ✗
    #     ② ⭐ 正解 = **只看计数器，按"还差几个"来点，且每轮从**已点过的**后面接着点**：
    #        第 1 轮点 want[0]；数到 1 就点 want[1]；数到 2 就点 want[2] ⇒
    #        **绝不重复点同一个** ✓
    #     ③ 更稳的一招：**先全部取消到 0，再依次点 3 个** —— 起点确定 ⇒ 不会 toggle 错 ✓
    #        （实测面板初次打开就是 0/3，所以正常路径第 ① 步不需要 ✓）
    #   ⇒ 实现：`_ensure_tags` —— 按计数器**严格递增**地推进，绝不回头点 ✓
    ok = _ensure_tags(b, want, log=log, tag=tag)
    GC._log(log, {'recruit': 'tags_done', 'want': want, 'ok': ok})
    return ok


def _ensure_tags(b, want, log=None, tag='rec', max_rounds=5):
    """把标签选成**恰好 want 这几个** ⇒ True/False

    做法（**按计数器严格推进，绝不重复点已选的** —— 因为 tag 是 toggle ✗）：
        读到 `n/3` ⇒ 下一颗要点的是 `want[n]`（因为面板初次是 0/3，按顺序点刚好对上 ✓）
        每点一颗 ⇒ 重新读计数 ⇒ n+1 就继续下一颗；没动就重试同一颗
    返回 True = 计数器最终 == len(want) ✓
    """
    want = list(want)
    target = len(want)
    for _r in range(max_rounds):
        items = GC.ocr_items(b, tag='%s_et%d' % (tag, _r))
        if not panel_open(items):
            say('       · ⚠ 标签面板被关掉了 ⇒ 停手（不点、也不招募）')
            GC._log(log, {'recruit': 'panel_closed_while_tapping'})
            return False
        n = read_counter(items)
        if n is None:
            say('       · ⚠ 读不到「（N/3）」计数器 ⇒ **不盲点**（怕 toggle 点错 ✗）')
            return False
        if n == target:
            return True
        if n > target:
            # 选多了 ⇒ 多点了一颗。**只能靠"取消再选"**，但这有风险
            #   ⇒ 如实报告，交给调用方（不硬凑 ✗）
            say('       · ⚠ 已选 %d 个 > 目标 %d 个 ⇒ 如实报失败（不硬凑 ✗）'
                % (n, target))
            GC._log(log, {'recruit': 'too_many_tags', 'n': n, 'want': target})
            return False
        # ⭐ 下一颗 = want[n]（**从 0 开始按序点**，绝不回头 ✓）
        t = want[n]
        xy = {x[0]: (x[1], x[2]) for x in read_tags(items)}
        if t not in xy:
            say('       · ⚠ 目标标签「%s」这一帧没读到（认到 %s）'
                % (t, [x[0] for x in read_tags(items)]))
            return False
        x, y = xy[t]
        b.tap(x + TAG_TAP_DX, y, wait=1.2)
        GC._log(log, {'recruit': 'tap_tag', 'tag': t, 'at': (x, y), 'was': n})
        say('       · 点第 %d 个标签「%s」(%d,%d)（当前 %d/3）'
            % (n + 1, t, x, y, n))
        time.sleep(0.6)
        items2 = GC.ocr_items(b, tag='%s_et%d_c' % (tag, _r))
        n2 = read_counter(items2)
        if n2 == n:
            say('         · 这一下没生效（仍 %s/3）⇒ 下一轮重点同一颗' % n2)
        elif n2 is not None and n2 < n:
            say('         · ⚠ 计数掉到 %s/3（点到已选的了）⇒ 下一轮重点' % n2)
    items3 = GC.ocr_items(b, tag='%s_et_fin' % tag)
    return read_counter(items3) == target


# ⛔⛔ 2026-10-15 **删掉 open_panel()** —— 它被拆成了两步（更清楚）✗
#   ---- 为什么删 ----
#     旧版把走到招募主页和点免费按钮进标签面板**揉在一个函数里** ⇒
#     可能不能免费那个判据**必须在主页上量**（按钮亮不亮）✗
#     揉在一起就没法在正确的时机量 ⇒ 只能像旧代码那样在门口瞎读大厅横幅 ✗
#   ---- 现在拆成两个 ----
#     _to_recruit_home() ⇒ **只走到主页**（公会右下角「招募」）✓
#     _tap_free_btn()   ⇒ **在主页上点免费按钮**进标签面板 ✓
#   调用方顺序：**先到主页 → 在主页量免费 → 再点** ✓（判据与读数同屏 ✓）
#   ⚠ 旧的大厅中央大门路径降级成 _to_recruit_home 里的**最后兜底** ✓


# ⛔⛔ 2026-10-15 **删掉 _guild_to_panel()** —— 它的活儿已并进 _to_recruit_home() ✗
#   （两个函数做同一件事 = 日后必然只改一个 ⇒ 判据漂移 ✗，本项目的老教训）


def _tap_free_btn(b, items, log=None, tag='rec', note=''):
    """在**招募主页**上点「指定招募(免费)」⇒ 标签面板 ✓

    ⚠ 坐标优先 **OCR 现读**（`_free_btn_xy`），读不到才退标定 `(145,905)` ✓
    """
    at = _free_btn_xy(items) or RECRUIT_FREE_BTN
    b.tap(at[0], at[1], wait=2.8)
    items2 = GC.ocr_items(b, tag='%s_free' % tag)
    _ok = panel_open(items2)
    GC._log(log, {'recruit': 'tap_free_btn', 'at': at, 'open': _ok})
    say('   · %s点「指定招募(免费)」(%d,%d) ⇒ %s'
        % (note, at[0], at[1], '标签面板已开 ✓' if _ok else '没开出面板 ✗'))
    return _ok


# ⛔⛔ 2026-10-15 **删掉 `goto_lobby()`** —— 它是"回大厅"方向遗留的错误产物 ✗
#   ---- 为什么删 ----
#     我原来以为招募入口在**大厅**（中央大门），于是写了个"回大厅"的函数。
#     用户纠正后真相是：**招募入口在「公会」右下角**（`GUILD_RECRUIT_STEPS`）✓
#     ⇒ "回大厅"这一步**从根上就不需要** ⇒ 留着它只会诱使后人再接回去 ✗
#   ---- 它当时也是真出过问题的 ----
#     真机日志：从**选图界面**点底部「开始冒险」四次都没进大厅
#     （那颗按钮在选图界面是「进入地图」，点它是**开图**不是回大厅 ✗）
#     ⇒ `goto_lobby` 返回 False ⇒ 招募被放弃 ⇒ 用户看到"没点招募就退了" ✗
#   ⚠ 正确的替代就是现在 `open_panel` 里的:能进公会就进公会（`GC.goto_guild`），
#     再点右下角「招募」⇒ 与用户教的路径**一致** ✓
#   （`GC.goto_guild` / `GC.leave_guild` 在 `guild_common.py` 里，那两条是对的 ✓）


def _to_recruit_home(b, items=None, log=None, tag='rec'):
    """走到「**招募主页**」⇒ 返回该帧的 items（到了）或 None（没到）✓

    ⭐⭐⭐ 2026-10-15 **按用户教的路径**（原话）：
        「**在公会界面要点击右下角的招募**，再点击免费招募才有那个界面」
    ---- 三条起点，逐条试（都在真机验过）----
      ① 已经在**招募主页** ⇒ 直接返回 ✓
      ② 在**公会界面** ⇒ 点右下角「招募」`(628,1040)` ⇒ 主页 ✓
      ③ 在**选图界面/图内/其它** ⇒ 先 `GC.goto_guild` 进公会 ⇒ 再走 ② ✓
    ⚠ 与旧 `open_panel` 的**关键区别**：本函数**只负责"走到主页"**，
      **不点**「指定招募」—— 因为"能不能免费"要在**主页上**量（那颗按钮亮不亮）✓
      量完再由调用方决定点不点（顺序：先到主页 → 再判 → 再点 ✓）
    ⚠ 老路径（大厅中央大门 `HALL_DOOR`）**留作最后兜底** ——
      用户纠正后它不再是主路径，但别的账号/版本可能真有大堂门 ✓
    """
    _it = items if items is not None else GC.ocr_items(b, tag='%s_h0' % tag)

    # ① 已经在主页
    if _on_recruit_home(_it):
        say('   · 已经在「招募主页」✓')
        return _it
    if panel_open(_it):
        # 标签面板开着（比主页更深一层）⇒ 也算"到了" —— 调用方会走"已开"分支 ✓
        return _it

    # ② 在公会 ⇒ 点右下角「招募」
    if not GC.in_guild(_it):
        # ③ 不在公会 ⇒ 先进公会（选图/图内/其它都能进 ✓）
        if not GC.goto_guild(b, log):
            say('   ✗ 进不了公会（招募入口在公会右下角）⇒ 走不通')
            return None
        _it = GC.ocr_items(b, tag='%s_h1' % tag)
        if _on_recruit_home(_it) or panel_open(_it):
            return _it

    # 点右下角「招募」：**优先 OCR 现读**，读不到才用标定值 ✓
    it = None
    for _i in (_it or []):
        if str(_i.get('text') or '').strip() == '招募':
            it = _i
            break
    at = (int(it['cx']), int(it['cy'])) if it else GUILD_RECRUIT_BTN
    b.tap(at[0], at[1], wait=2.8)
    items2 = GC.ocr_items(b, tag='%s_h2' % tag)
    GC._log(log, {'recruit': 'guild_tap_recruit', 'at': at,
                  'by': 'ocr' if it else 'calib',
                  'home': _on_recruit_home(items2), 'panel': panel_open(items2)})
    say('   · 公会右下角 ⇒ 点「招募」(%d,%d)%s ⇒ %s'
        % (at[0], at[1], '（OCR 现读）' if it else '（标定坐标）',
           '招募主页 ✓' if _on_recruit_home(items2) else
           ('标签面板 ✓' if panel_open(items2) else '没进招募页 ✗')))
    if _on_recruit_home(items2) or panel_open(items2):
        return items2

    # ④ 兜底：老路径（大厅中央大门）
    say('   · ⚠ 点了右下角「招募」没进招募页 ⇒ 试一下老路径（大厅中央大门）')
    b.tap(*HALL_DOOR, wait=2.6)
    items3 = GC.ocr_items(b, tag='%s_h3' % tag)
    GC._log(log, {'recruit': 'tap_door_fallback', 'at': HALL_DOOR,
                  'home': _on_recruit_home(items3)})
    if _on_recruit_home(items3) or panel_open(items3):
        return items3
    return None


def _on_recruit_home(items):
    """这一帧是不是**招募主页**（三颗按钮那一屏）

    主页专属文案（实测）：`指定招募` / `招募一次!` / `招募十次!!` /
                        `招募点数：` / `改变心愿` / `招募预览`
    ⚠ **不能**用「常规招募」当判据 —— 标签面板的标题**也是**「常规招募」✗
      （真机实测：面板开着时标题仍是「常规招募」，见 `panel_open` 的说明）
    """
    return GC.has(items, '招募一次', '招募十次', '招募点数', '改变心愿',
                  '招募预览')


def _free_btn_xy(items):
    """从当前帧里找「指定招募」按钮的文字坐标（**OCR 现读**，比写死稳 ✓）

    返回 `(x, y)` 或 None。
    ⚠ 取到的是**文字**中心 ⇒ y 会比按钮中心高一点；实测文字在 (125,871)、
      按钮中心 (125,905) ⇒ **下面补 +34px** 落到按钮中心 ✓
    """
    it = GC.find(items, '指定招募')
    if not it:
        return None
    try:
        return (int(it['cx']), int(it['cy']) + 34)
    except Exception:                                   # noqa: BLE001
        return None


# ⭐⭐⭐ 2026-10-14 **免费机会的视觉判据**（真机实测出来的，很关键）
#   ---- 背景：光看文字**判不出来** ----
#     用掉之后，那颗按钮上**仍然印着「免费」两个字**（实测 OCR 照读 ✓），
#     红点也还在 ⇒ 纯文字判据**永远认为"还能免费"** ✗✗
#   ---- 真机实测的差异（同区域 `(40,840)-(220,960)` 逐像素量）----
#     状态       按钮平均亮度   「免费」文字区亮度   红色像素
#     免费可用       **145.7**        **167.4**        369
#     已用掉(变灰)    **80.5**         **84.1**        199
#   ---- 与源码吻合 ----
#     `SummonButtonBehaviour.SetEnable(enable)`：
#       `((Graphic)btn).image).color = enable ? Color.white : Color.gray;`
#       红色小点 `transform.Find("redDot").SetActive(enable);`
#     ⇒ **禁用时整颗按钮压灰** ⇒ 亮度几乎腰斩 ✓
#   ⇒ 判据：**按钮区平均亮度 ≥ 110 ⇒ 还是亮的 ⇒ 免费可用** ✓
#     阈值取 110（145.7 与 80.5 的**中点偏上**，两边余量都 >30 ✓）
FREE_BTN_BOX = (40, 840, 220, 960)      # 「指定招募」那颗按钮的整块区域（设备系）
FREE_BTN_LIT = 110.0                    # 平均亮度 ≥ 它 ⇒ 亮着 = 还能免费 ✓


def free_available(b, items=None):
    """那颗「指定招募」**现在到底还能不能免费** ⇒ (bool, 亮度, 说明)

    ⚠ 必须靠**亮度**（见 `FREE_BTN_LIT` 的说明）：光看文字「免费」两个字
      **用掉之后也还在**，判不出来 ✗
    ⚠ 取不到帧/裁剪为空 ⇒ 返回 `(None, None, 原因)`（**不瞎猜** ✓）
    """
    try:
        img = b.img()
    except Exception as e:                              # noqa: BLE001
        return None, None, '取不到帧（%r）' % (e,)
    if img is None or getattr(img, 'size', 0) == 0:
        return None, None, '帧是空的'
    try:
        import cv2 as _cv2
        x0, y0, x1, y1 = FREE_BTN_BOX
        sub = img[y0:y1, x0:x1]
        if sub is None or sub.size == 0:
            return None, None, '裁剪区为空'
        lum = float(_cv2.cvtColor(sub, _cv2.COLOR_BGR2GRAY).mean())
    except Exception as e:                              # noqa: BLE001
        return None, None, '亮度算不出来（%r）' % (e,)
    ok = lum >= FREE_BTN_LIT
    return ok, round(lum, 1), ('亮着 ⇒ 免费可用' if ok else '发灰 ⇒ 免费已用掉')


def do_recruit(b, log=None, tag='rec'):
    """点「招募」⇒ **走完整个收尾链** ⇒ 结果 dict（⚠ **会花掉当天那次免费机会**）

    ⭐⭐⭐ 2026-10-15 用户口径（原话，两次）：
        「**就是跳过动画，那几步，最后要返回到地图界面**」
        「**不用读结果**」  ← 本次
    ---- 完整链条（真机逐帧实测）----
        ① 点「招募」`(360,963)` ⇒ 进入**开门动画**（一个小手推门 + 「跳过」按钮）
           ⚠⚠ **动画不会自己结束**（实测等 6 秒仍在同一帧）⇒ **必须点「跳过」** ✗
              我第一版点完就 `return` ⇒ 脚本**卡死在动画屏**（用户看到的就是这个）✗
        ② 点「**跳过**」`(360,963)` ⇒ 出结果屏
        ③ ⛔ **不读结果**（用户明确说「不用读结果」）⇒ 出结果屏后**直接往下走** ✓
           —— 抽到什么是**玩家自己看**的事，脚本不需要知道 ✓
           （原 `_read_result()` 已删；`role`/`shards` 两个字段也一并去掉 ✓）
        ④ 点「**结束招募**」`(360,1214)` ⇒ 回**招募主页**
        ⑤ **点右上角 X** `(671,126)` ⇒ **离开招募页** ✓
        ⑥ **返回地图界面**（用户点名要的收尾）—— 交给调用方 `GC.leave_guild`，
           因为"地图界面"= 选图界面，而那是**公会之外**的一步 ✓
    ⚠ 每一步都**轮询 + 验证**（动画/面板有过渡帧，一次判死会漏 ✗
      —— 本项目在 `claim_back_poll` 上栽过：轮询里漏了 `b.snap()` ✗）
    ⚠ 找不到「跳过」**不等于**失败：有些号不出动画、直接出结果 ✓
    """
    items = GC.ocr_items(b, tag='%s_btn' % tag)
    it = GC.find(items, '招募')
    # ⚠ 面板里「招募」字样很多（常规招募/异化招募/招募），必须**按位置**挑
    #   真按钮实测在 **(360,963)**（提示行下方那颗）✓
    if it and abs(it.get('cy', 0) - RECRUIT_BTN[1]) > 90:
        it = None                       # 读到的是别处的"招募"，别用
    at = (it['cx'], it['cy']) if it else RECRUIT_BTN
    b.tap(at[0], at[1], wait=2.5)
    GC._log(log, {'recruit': 'tap_btn', 'at': at})
    say('   · 点「招募」%s' % ('（OCR 现读）' if it else '（标定坐标）'))

    out = {'got': True, 'skipped': False, 'ended': False, 'closed': False}

    # ── ①② 动画 ⇒ 点「跳过」（**轮询**，每轮重新取帧 ✓）──
    #   ⚠ 实测：点完「招募」后约 1~2 秒出动画；动画**不会自己结束** ✗
    out['skipped'] = _click_skip_anim(b, log, tag)

    # ── ③ **不读结果**（用户口径）⇒ 直接从结果屏往下走 ✓ ──
    say('   · （按用户口径**不读结果**）⇒ 直接收尾')

    # ── ④ 点「结束招募」⇒ 回招募主页 ──
    out['ended'] = _click_text_btn(b, log, tag, ('结束招募',),
                                   fallback=RECRUIT_END_BTN, what='结束招募')

    # ── ⑤ 关掉招募页（右上角 X）⇒ 离开招募界面 ──
    it3 = GC.ocr_items(b, tag='%s_x' % tag)
    if _on_recruit_home(it3) or panel_open(it3):
        out['closed'] = _click_text_btn(
            b, log, tag, ('×', 'X', '关闭'), fallback=RECRUIT_CLOSE_X,
            what='关闭招募页', prefer_right=True)
    else:
        out['closed'] = True        # 已经不在招募页了 ⇒ 算关掉了 ✓
    return out


def _click_skip_anim(b, log=None, tag='rec', rounds=6):
    """点动画的「**跳过**」⇒ True/False（**轮询**，每轮重新取帧 ✓）

    ⚠⚠ 实测（2026-10-15，综合模拟器 PID 222025）：
      点完「招募」⇒ 出**开门动画**（小手推门 + 底部「跳过」`(360,963)`）
      **等 6 秒画面一动不动** ⇒ 动画**不会自己结束** ⇒ 必须点「跳过」✗
    ⚠ 但**不是每个号都出动画**（有的直接出结果）⇒ 找不到「跳过」
      **不算失败**：接着去找"结果屏"就行 ✓
    ⚠ 位置：优先 **OCR 现读**「跳过」，读不到用 `(360,963)`（与「招募」同一位）✓
    """
    for k in range(max(1, int(rounds))):
        items = GC.ocr_items(b, tag='%s_skip%d' % (tag, k))
        # 已经到结果屏 ⇒ 不用再跳过 ✓
        if GC.has(items, '恭喜获得', '结束招募'):
            return False
        it = GC.find(items, '跳过')
        at = (int(it['cx']), int(it['cy'])) if it else SKIP_BTN
        if not (it or GC.has(items, '跳过')):
            # 这一帧没看到「跳过」，也不像结果屏 ⇒ 可能是过渡帧 ⇒ 再等一轮
            time.sleep(0.6)
            continue
        b.tap(at[0], at[1], wait=1.6)
        GC._log(log, {'recruit': 'tap_skip', 'at': at, 'try': k + 1,
                      'by': 'ocr' if it else 'calib'})
        say('   · 点「跳过」(%d,%d)%s ⇒ 看结果'
            % (at[0], at[1], '（OCR 现读）' if it else '（标定坐标）'))
        return True
    return False


# ⛔ 2026-10-15 **删掉 _read_result()** —— 用户口径：「**不用读结果**」✗
#   （抽到什么是玩家自己看的事，脚本不需要知道 ⇒ 读结果纯属多余开销 ✓）


def _click_text_btn(b, log=None, tag='rec', texts=(), fallback=None,
                    what='', prefer_right=False, rounds=4):
    """点一个**文字按钮**（轮询找；找不到用 `fallback`）⇒ True/False

    ⚠ 一律**每轮重新取帧**再找（按钮有出现/消失动画，一次判死会漏 ✗）
    ⚠ `prefer_right=True` 时取**最靠右**的那个（关面板的 X 在右上角 ✓）
    """
    for k in range(max(1, int(rounds))):
        items = GC.ocr_items(b, tag='%s_%s%d' % (tag, what, k))
        cands = []
        for it in (items or []):
            t = str(it.get('text') or '').strip()
            for lb in texts:
                if t == lb or (lb in t and len(lb) >= 2):
                    cands.append(it)
                    break
        if cands:
            it = (max(cands, key=lambda d: d.get('cx', 0))
                  if prefer_right else min(cands, key=lambda d: d.get('cy', 0)))
            b.tap(it['cx'], it['cy'], wait=2.0)
            GC._log(log, {'recruit': 'tap_' + (what or 'btn'),
                          'text': it['text'], 'at': (it['cx'], it['cy']),
                          'try': k + 1})
            say('   · 点「%s」(%d,%d) ✓' % (it['text'], it['cx'], it['cy']))
            return True
        time.sleep(0.6)
    if fallback:
        b.tap(fallback[0], fallback[1], wait=2.0)
        GC._log(log, {'recruit': 'tap_' + (what or 'btn'),
                      'at': fallback, 'by': 'fallback'})
        say('   · 没读到「%s」⇒ 用标定坐标 (%d,%d)'
            % ('/'.join(texts), fallback[0], fallback[1]))
        return True
    GC._log(log, {'recruit': 'btn_miss', 'what': what, 'texts': list(texts)})
    say('   · ⚠ 没找到「%s」⇒ 不盲点（如实上报）' % ('/'.join(texts),))
    return False


def run(b, log=None, recruit=True, wish=None, leave=False, force=False,
        return_to_map=None):
    """主流程 ⇒ 汇总 dict

    `recruit=False`（或 CLI `--analyze`）⇒ **只分析不招募**（零消耗 ✓）
    `force=True` ⇒ 即使旗标不是"免费指定招募"也照做（默认关：别误花宝石 ✗）
    `return_to_map` ⇒ 做完**返回地图界面**（选图界面）✓
      ⚠ **默认按模块级 `RETURN_TO_MAP`（= True）** —— 用户口径
        「**最后要返回到地图界面**」⇒ 默认就该返回 ✓
        想停在招募页手动看：显式传 `False`（或 CLI `--no-back`）✓
    """
    log = log if log is not None else []
    res = {'ok': False, 'tags': [], 'picked': [], 'minR': None,
           'recruited': False}
    say('')
    say('=' * 62)
    say('🎲 免费指定招募（%s）' % ('**只分析、不招募**' if not recruit
                                  else '分析 + 招募'))
    say('=' * 62)

    roles, err = load_roles()
    if err:
        say('   ⚠ %s ⇒ **这次不选最优**（只按标签类别提示，不瞎猜 ✗）' % err)
    else:
        say('   ✓ 角色表：%d 行（从游戏数据表实时推 ✓）' % len(roles))

    # ══════════════════════════════════════════════════════════════════
    # 开面板 —— ⭐⭐⭐ 2026-10-15 **按用户教的路径重构**（原话）：
    #   「少了两步，在公会界面要点击右下角的招募，再点击免费招募才有那个界面」
    # ---- 这次重构把"免费判据"放到了**正确的位置** ----
    #   ⛔ 旧写法（错的，两个毛病）：
    #     ① 在"还没到招募页"时就先读**大厅横幅**「免费指定招募」
    #        ⇒ 入口根本不在大厅（在公会右下角）⇒ **恒读不到** ⇒ 白报一行
    #          `免费旗标：没读到` + `where:lobby` ⇒ 让人以为出错了 ✗
    #     ② 判据要量的那个东西（那颗按钮**亮不亮**）在**招募主页**上，
    #        而旧代码要么在门口瞎读、要么等面板开了才读（那时按钮被盖住）✗
    #   ⇒ 新顺序（**每一步都在正确的屏上做正确的判断**）：
    #     ① 标签面板已开 ⇒ 直接用（免费机会必然还在，否则进不来 ✓）
    #     ② 否则：**先走到招募主页**（`_to_recruit_home`）
    #     ③ **在主页上**量那颗「指定招募」的亮度（`free_available`）⇒ 判免费
    #     ④ 免费可用（或 `--force`）⇒ 点它进标签面板 ✓
    #   ⚠ 顺序很要紧：**先到主页、再判、再点** —— 判据与它读的东西在同一屏 ✓
    # ══════════════════════════════════════════════════════════════════
    items0 = GC.ocr_items(b, tag='rec0')
    if panel_open(items0):
        items = items0
        say('   · 标签面板**已经开着** ⇒ 直接用（免费机会必然还在 ✓）')
        GC._log(log, {'recruit': 'panel_already_open'})
    else:
        # ② 走到招募主页（公会 → 右下角「招募」）
        #   ⚠ 2026-10-15 真机抓到的 **NameError: name 'tag' is not defined** ——
        #     `run()` 的签名里**没有 `tag`**（那是各下层函数的**日志前缀**参数）✗
        #     我重构时顺手把 `tag` 传了进来 ⇒ 一跑就崩 ✗
        #   ⚠ 我的静态门禁（`verify_guild_scripts.py ⓪`）**没抓到它** ——
        #     因为 `ast` 符号表把**函数参数**都算"已定义"，而 `tag` 恰好是
        #     **别的函数的参数名** ⇒ 这类"跨函数串用参数名"的错它看不出来 ✓（诚实记账）
        #   ⇒ 修法：这里**用固定前缀 `'rec'`**（与 `main()` 里 `--tag` 那个
        #     "实例名"**不是一回事** —— 别混 ✗）
        home_items = _to_recruit_home(b, items0, log, 'rec')
        if home_items is None:
            say('   ✗ 没能走到「招募主页」⇒ 放弃（不动任何东西）')
            res['why'] = 'home_not_reached'
            return res
        # ③ **在主页上**量免费（那颗按钮亮着 = 还能免费 ✓）
        _avail, _lum, _why = free_available(b, home_items)
        GC._log(log, {'recruit': 'flag', 'where': 'recruit_home',
                      'free': _avail, 'lum': _lum, 'why': _why})
        if _avail is None:
            say('   ⚠ 免费判据算不出来（%s）⇒ **保守起见不动它**'
                '（宁可不做，也不误花宝石 ✗）；确认可用时加 `--force` ✓' % _why)
            res['why'] = 'free_unknown'
            return res
        if recruit and not _avail and not force:
            say('   ⚠ 那颗「指定招募」**是灰的**（亮度 %.1f < %.0f）⇒ '
                '今天的免费机会已用过 ⇒ **不动它**（避免误花宝石）'
                % (_lum, FREE_BTN_LIT))
            say('      要强行做：加 `--force` ✓')
            res['why'] = 'not_free'
            return res
        say('   · 免费判据：%s（按钮亮度 %.1f）' % (_why, _lum))
        # ④ 点「指定招募(免费)」⇒ 标签面板
        if not _tap_free_btn(b, home_items, log, 'rec', note='（招募主页）'):
            say('   ✗ 没打开「指定招募」标签面板 ⇒ 放弃（不动任何东西）')
            res['why'] = 'panel_not_open'
            return res
        items = GC.ocr_items(b, tag='rec1')
    say('   ✓ 「指定招募」面板已开')

    # ── 读标签 + 算最优 ──
    best, ranked, tags = analyze(items, roles, wish=wish)
    res['tags'] = tags
    if not tags:
        say('   ✗ 一个标签都没读到 ⇒ 放弃（不瞎点）')
        res['why'] = 'no_tags'
        return res
    if best is None:
        if not roles:
            say('   ⚠ 没有角色表 ⇒ 只读标签、**不选也不招募**（不瞎猜 ✗）')
            res['why'] = 'no_roles'
            return res
        say('   ✗ 所有组合都匹配不到角色 ⇒ 放弃')
        res['why'] = 'no_combo'
        return res

    res['picked'] = best['c']
    res['minR'] = best['minR']
    say('')
    say('   ★ 最优组合（小助手权重，共 %d 组）：**%s**'
        % (len(ranked), ' + '.join(best['c'])))
    say('     保底稀有度 = %d（%s）%s'
        % (best['minR'], RARITY_CN.get(best['minR'], '?'),
           ('  ⇒ 【%s】' % badge(best['minR'])) if badge(best['minR']) else ''))
    say('     权重 = %.1f ｜ 可能角色 %d 个：' % (best['w'], len(best['f'])))
    for r in best['f'][:8]:
        say('       · %-10s %-3s %s/%s/%s %s'
            % (r[0], RARITY_CN.get(r[5], '?'), r[1], r[2], r[3], r[4]))
    if len(best['f']) > 8:
        say('       …（还有 %d 个）' % (len(best['f']) - 8))
    say('')
    say('   · 备选前 3 组：')
    for r in ranked[1:4]:
        say('       %-22s 保底%d 权重%.1f（%d 角色）'
            % (' + '.join(r['c']), r['minR'], r['w'], len(r['f'])))

    if not recruit:
        say('')
        say('   ⓘ 只分析模式 ⇒ **没有点任何标签、没有招募** ✓')
        GC.close_panel(b, RECRUIT_CLOSE_X, 'rec_x', probe_texts=('最多选择',),
                       log=log)
        res['ok'] = True
        res['why'] = 'analyze_only'
        return res

    # ── 点标签 ──
    tags_xy = {t: (x, y) for t, x, y in read_tags(items)}
    if not pick_tags(b, best['c'], tags_xy, log=log):
        say('   ✗ 标签没选上 ⇒ **不点招募**（选了才允许招募 ✗）')
        res['why'] = 'tags_failed'
        GC.close_panel(b, RECRUIT_CLOSE_X, 'rec_x2',
                       probe_texts=('最多选择',), log=log)
        return res
    say('   ✓ 标签已选：%s' % (' + '.join(best['c'])))

    # ── 点招募 ⇒ **走完收尾链**（跳过动画 → 结束招募 → 关招募页）──
    #   ⭐ 用户口径：「**就是跳过动画，那几步，最后要返回到地图界面**」✓
    _r = do_recruit(b, log)
    res['recruited'] = bool(_r.get('got'))
    res['skipped'] = bool(_r.get('skipped'))
    res['ended'] = bool(_r.get('ended'))
    res['closed'] = bool(_r.get('closed'))
    res['ok'] = bool(res['recruited'])

    # ── ⭐ 最后一步：**返回地图界面**（用户点名要的收尾 ✓）──
    #   ⚠ "地图界面" = **选图界面**（不是公会、也不是大厅）⇒ `GC.leave_guild`
    #     会点底部「开始冒险」离开公会 ⇒ 回到选图界面 ✓
    #   ⚠ **默认就返回**（用户明确要的）—— `leave=False` 只用于"我要接着在招募页里
    #     手动看看"这种调试场景；正常调用（含自动化）**一律返回** ✓
    #   ⚠ 取值优先级：显式传参 > 模块级 `RETURN_TO_MAP`（默认 True）✓
    #     （写成一行三元容易看错 ⇒ 拆开写清楚 ✓）
    _back_wanted = (RETURN_TO_MAP if return_to_map is None
                    else bool(return_to_map)) or bool(leave)
    if _back_wanted:
        _back = GC.leave_guild(b, log)
        res['back_to_map'] = bool(_back)
        say('   · %s' % ('已返回地图界面（选图界面）✓' if _back
                        else '⚠ 没确认回到选图界面（如实上报）'))
    GC._log(log, {'recruit': 'done', 'picked': res['picked'],
                  'minR': res['minR'], 'recruited': res['recruited'],
                  'skipped': res['skipped'], 'ended': res['ended'],
                  'back_to_map': res.get('back_to_map')})
    say('=' * 62)
    return res


# ══════════════════════════════════════════════════════════════════════
# ⑥ CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:                                   # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='免费指定招募（抄小助手的选项判断）')
    ap.add_argument('--device', default=None, help='adb 设备号，如 127.0.0.1:16448')
    ap.add_argument('--tag', default='recruit', help='实例名')
    ap.add_argument('--analyze', action='store_true',
                    help='⭐ 只分析、**不招募**（零消耗；算完就关面板）')
    ap.add_argument('--force', action='store_true',
                    help='即使旗标不是「免费指定招募」也照做（默认关：别误花宝石）')
    ap.add_argument('--wish', default='',
                    help='心愿/未拥有角色名，逗号分隔（命中组合权重 +1000 置顶）')
    ap.add_argument('--dry-run', action='store_true',
                    help='⭐ 试跑：一下都不点，只打印"认到啥 / 打算点哪"')
    ap.add_argument('--leave', action='store_true', help='做完离开公会/回选图')
    ap.add_argument('--no-back', dest='back', action='store_false', default=None,
                    help='做完**不**返回地图界面（默认会返回 ✓ 用户口径）')
    a = ap.parse_args()

    dev = a.device or os.environ.get('MAPBOT_DEVICE') or GC.DEV
    GC.DRY_RUN = bool(a.dry_run)
    wish = {w.strip() for w in str(a.wish).split(',') if w.strip()}
    say('设备：%s ｜ 实例：%s ｜ 模式：%s%s'
        % (dev, a.tag,
           '只分析（不招募）' if a.analyze else '分析 + 招募',
           ' ｜ ⚠ **试跑：不会点任何东西**' if GC.DRY_RUN else ''))
    b = GC.wrap_dry(GC.Bot(log_prefix='recruit', serial=dev, tag=a.tag), None)
    log = []
    try:
        res = run(b, log, recruit=not a.analyze, wish=wish, leave=a.leave,
                  force=a.force, return_to_map=a.back)
    finally:
        for e in log:
            print(e)
    say('')
    say('结果：标签=%s ｜ 选中=%s ｜ 保底=%s' % (res.get('tags'),
                                             res.get('picked'), res.get('minR')))
    say('      招募=%s ｜ 跳过动画=%s ｜ 结束招募=%s ｜ 已返回选图=%s'
        % (res.get('recruited'), res.get('skipped'), res.get('ended'),
           res.get('back_to_map')))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
