# -*- coding: utf-8 -*-
"""广告领奖 —— 购买体力 / 四叶草 / 金币 ＋ 加速炼金（2026-10-15）

用户口径（原话，一次说全）：
    「**开始做领取广告（默认有免广），只做每天1次的加速炼金，
      每天三次的购买体力，幸运草和金币，单独加个有无免广的勾选，
      有就自动做**」
补问确认（我主动问的，用户选项）：
    · 免广勾选语义 = 「**勾 = 有免广，未勾则不做**」✓
    · 体力次数 = 「**广告都是 3 次**」（不是花宝石那 5 次）✓

════════════════════════════════════════════════════════════════════
一、⭐ 整套体系（**从游戏源码挖出来的，不是猜的**）
════════════════════════════════════════════════════════════════════
`SaveData.AdsType` 枚举 **7 项**，配 `MaxAdsDailyLimit = new int[7]
{ 3, 3, 3, 1, 1, 1, 999999 }`（**按枚举顺序一一对应**）：

    | # | AdsType          | 每日上限 | 本轮做不做 |
    |---|---|---|---|
    | 0 | `CloverSupply`   | **3** | ✅ 四叶草 |
    | 1 | `GoldSupply`     | **3** | ✅ 金币 |
    | 2 | `EnergySupply`   | **3** | ✅ 购买体力 |
    | 3 | `SagaGuarantee`  | 1 | ❌ 奇遇（用户没要）|
    | 4 | `ExploreSkip`    | 1 | ❌ 立即完成探索（没要）|
    | 5 | `AlchemySkip`    | **1** | ✅ 加速炼金 |
    | 6 | `DungeonSupply`  | 999999 | ❌ 秘境（没要）|
⇒ 用户说的「**每天三次**」正是 0/1/2；「**每天1次的加速炼金**」= `AlchemySkip` ✓
  **一个不多一个不少，全对上** ✓

════════════════════════════════════════════════════════════════════
二、⭐⭐ 「免广告」到底是什么（**这是本文件最要紧的一条**）
════════════════════════════════════════════════════════════════════
源码 `SaveData.CanSkipAds()` 的实现**只有一行**：
    `return GetMonthRightRemainDays().Any((int x) => x >= 0);`
⇒ **「免广告」= 月卡权益还有剩余天数** ⇒ 它**不是设置开关，是账号状态** ✓
⇒ 所以用户要的那个勾选 = **告诉脚本"这个号有免广"**，脚本据此走不同分支：
    · **有免广** ⇒ 点一下就**直接领**（源码 `canClaimReward = true`，**不跳广告**）✓
    · **无免广** ⇒ 要真播视频广告（`OnShowVideoAdClickListener`）✗
      ⚠⚠ **脚本做不了"看视频"** —— 那是 SDK 的原生播放器。
         **真机实测（综合模拟器 2026-10-15）**：点绿按钮后 `0/3` **纹丝不动**、
         画面无变化 ⇒ 模拟器里**广告起不来** ✗
⇒ 所以按用户口径：「**默认有免广**」＋「勾 = 有免广，未勾则不做」✓
   ⚠ **未勾时四个入口一下都不碰**（不是"碰了再说"，是**完全不进**）✓

════════════════════════════════════════════════════════════════════
三、⭐ 入口 = **顶部固定栏（HUD）上的资源数字 / 绿加号**
════════════════════════════════════════════════════════════════════
⛔ 我一开始在**商店**（充值页：月卡/成长基金/优惠礼包/超值充值）里找 ⇒ **找不到** ✗
真相（源码 `headFixedPanel` 的三个方法 ⇒ 我逐个真机点过 ✓）：

    | 资源 | 点哪里 | 确认框文案 | 面板标题 |
    |---|---|---|---|
    | **金币** | 绿加号 **`(481,26)`** | `Interface_Tips_77`「金币不足，是否购买金币？」 | 购买金币 |
    | **四叶草** | 绿加号 **`(462,59)`** | `Interface_Tips_79`「四叶草不足，是否购买四叶草？」 | 购买四叶草 |
    | **体力** | **体力数字** `(224,62)` | `Interface_Tips_76`「体力不足，是否购买体力？」 | 购买体力 |
    ⚠ 实测：**点绿加号/体力数字直接开面板**（本号没弹那个确认框）
      —— 确认框只在"资源不足"场景才拦 ✓ 所以**两条路都要处理**（见 `_maybe_confirm`）
    ⚠⚠ 文案里都带「**不足**」二字 ⇒ 它们是**资源不足时的提示** ✓

### 三个面板的按钮（**真机实测 bbox**）
    | 面板 | 左（花宝石） | 右（**看广告**，就是它） |
    |---|---|---|
    | 购买金币   | `(246,644)` 50 宝石 | **`(512,645)`** `0/3` |
    | 购买四叶草 | `(248,644)` 75 宝石 | **`(512,645)`** `0/3` |
    | 购买体力   | `(196,645)` 50 宝石 | **`(562,645)`** `3/3` |
                （体力多一个"用道具"按钮 ⇒ 广告按钮**右移 50px** ✗ 别混用）
    ⚠ **一律 OCR 现读那个 `N/M`**（<0.5s 的事）⇒ 不必依赖上面三个 x ✓
      上面三个值**只当兜底** ✓
    · 关闭 X = **`(613, 408)`**（三个面板同一个位置 ✓）

════════════════════════════════════════════════════════════════════
四、加速炼金（`AlchemySkip`，每日 1 次）
════════════════════════════════════════════════════════════════════
· 入口：炼金**进行中**时，箱子上的**沙漏** `ALCH_HOURGLASS = (361,338)` ✓
· 弹窗文案：`Tips_Allsystem_98`「**选择观看广告或者花费宝石加速炼金？**」
· 两个按钮（**早前已标定**，见 `guild_common`）：
    看广告 `ALCH_ACCEL_AD = (535,745)` ｜ 花宝石 `ALCH_ACCEL_GEM = (313,745)`
    关掉不加速 `ALCH_ACCEL_X = (671,486)` ✓
⚠ 有免广 ⇒ 点「看广告」那颗**直接加速** ✓
⚠ 无免广 ⇒ **不点**（真播广告做不了）⇒ 关掉弹窗、如实上报 ✓

════════════════════════════════════════════════════════════════════
五、安全边界（只领奖，**绝不花宝石**）
════════════════════════════════════════════════════════════════════
· **绝不点**左侧"花宝石"那颗（`50`/`75` 那个）✗
· **绝不点**面板下方「每日XX补给」那种**要花宝石**的商品 ✗
· 只看/点 `N/M` 那颗绿按钮 ✓
· 遇到「今日观看广告达到上限」`Tips_Allsystem_82` ⇒ **今天到此为止** ✓
· 遇到「广告播放失败」`Tips_ExtraText_01` ⇒ **如实上报、不重试死磕** ✓
"""
import argparse
import io
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import guild_common as GC                                     # noqa: E402

say = GC.say

# ══════════════════════════════════════════════════════════════════════
# ① 坐标（**全是真机实测的 720×1280 裸坐标** —— 别乘 LAYOUT.k ✗）
# ══════════════════════════════════════════════════════════════════════
# HUD 上的入口（源码 `headFixedPanel` ⇒ 真机实测 ✓）
ADS_HUD_GOLD = (481, 26)        # 金币的**绿加号** ⇒ 购买金币
ADS_HUD_CLOVER = (462, 59)      # 四叶草的**绿加号** ⇒ 购买四叶草
ADS_HUD_ENERGY = (224, 62)      # 体力的**数字**（它没有绿加号）⇒ 购买体力
# 三个购买面板的**广告按钮**（右数那颗 `N/M`）—— **兜底值**，优先 OCR 现读 ✓
ADS_BUYAD_GOLD = (512, 645)
ADS_BUYAD_CLOVER = (512, 645)
ADS_BUYAD_ENERGY = (562, 645)
# 三个面板的关闭 X（同一个位置 ✓）
ADS_PANEL_X = (613, 408)
# 面板标题（**判"面板开着"的判据** —— 用标题，不用别的 ✗）
ADS_TITLES = {'gold': '购买金币', 'clover': '购买四叶草', 'energy': '购买体力'}
# 确认框的「确定」/「取消」（源码 `Interface_Tips_76/77/79` 那个 `ActionPrompt`）
#   ⚠ 文案里带「不足」⇒ 只在资源不足时才出现；按钮是通用的「确定/取消」
ADS_CONFIRM_YES = ('确定', '确认', '是')
ADS_CONFIRM_NO = ('取消', '否', '关闭')
# 「今日观看广告达到上限」/「广告播放失败」（源码文案，**判据**✓）
ADS_LIMIT_TIP = '今日观看广告达到上限'
ADS_FAIL_TIP = '广告播放失败'

# 加速炼金（`AlchemySkip`）—— 复用 `guild_common` 里**早前标定好**的那三个 ✓
ADS_ALCH_HOURGLASS = GC.ALCH_HOURGLASS          # (361,338) 沙漏 = 加速入口
ADS_ALCH_AD = GC.ALCH_ACCEL_AD                  # (535,745) 看广告 ⇒ 直接加速
ADS_ALCH_X = GC.ALCH_ACCEL_X                    # (671,486) 关掉、不加速


# ══════════════════════════════════════════════════════════════════════
# ② 小工具
# ══════════════════════════════════════════════════════════════════════
def _panel_open(items, which=None):
    """这一帧是不是某个**购买面板** ⇒ True/False

    ⚠ 判据 = **面板标题**（`购买金币`/`购买四叶草`/`购买体力`）✓
      —— 别用"有没有 `N/M`"，那个在别处也可能出现 ✗
    """
    if which:
        return GC.has(items, ADS_TITLES[which])
    return any(GC.has(items, t) for t in ADS_TITLES.values())


def _which_panel(items):
    """当前开着哪个购买面板 ⇒ 'gold'/'clover'/'energy'/None"""
    for k, t in ADS_TITLES.items():
        if GC.has(items, t):
            return k
    return None


_AD_RE = re.compile(r'^\s*(\d+)\s*/\s*(\d+)\s*$')


def read_ad_counter(items):
    """读那颗**广告按钮**上的计数 ⇒ `(remaining, limit, 条目)` 或 None

    ⛔⛔⛔ 2026-10-15 **我把这个数读反了，用户当场纠正**（最值钱的一条）
      用户原话：「**这号现在的状态是体力3/3还没买，幸运草和金币都买过了**」
      ---- 源码怎么写 ----
        `FreshAdsTimeText()`：
            `int num2 = SaveData.MaxAdsDailyLimit[(int)currentAdType];`
            `((TMP_Text)adsTimeText).text = $"{num2 - num}/{num2}";`
        其中 `num = save.AdsWatchedTime[(int)adType]`（**已看**次数）
        ⇒ 显示的是 **`{上限 - 已看}/{上限}` = 「剩余/上限」** ✓
      ---- 所以 ----
        · **`3/3`** = 剩 **3** 次 = **今天还没买** ✓（体力就是这个）
        · **`0/3`** = 剩 **0** 次 = **今天已用完** ✓（金币/四叶草就是这个）
      ---- 我的错（**真机铁证**）----
        我原来按"**已看**/上限"读 ⇒ `used=0, limit=3` ⇒ 判据 `used >= limit`
        = `0 >= 3` = **False** ⇒ 在**已经用完**的面板上**照样去点** ✗
        点了之后画面弹出「**今日观看广告达到上限**」`Tips_Allsystem_82`
        —— 这行提示**正好证明 `0/3` = 没得领了** ✓✓
      ---- ⚠ 教训 ----
        源码里那行是 `$"{num2 - num}/{num2}"`，**是个减法** ——
        屏幕上看到的 `N/M` 里 **N 是倒数（剩余）**，不是正数（已用）✗
        「看起来像进度、其实是余量」这种反直觉的显示，**光看截图猜不出来，
          必须读源码那行字符串插值** ✓

    ⚠ 判据 = 形如 `0/3` / `3/3` 的**纯数字比**（面板上只有它是这个形状 ✓）
      —— 别把宝石价 `50` 当它（那是单个数字 ✗）
    ⚠ 实测那颗在 **y≈645**（三个面板都在这一行）⇒ 用 y 圈定，避开
      列表里别的 `N/M`（比如「每日限购1/1」在 y≈862）✓
    """
    best = None
    for it in (items or []):
        t = str(it.get('text') or '')
        m = _AD_RE.match(t)
        if not m:
            continue
        cy = it.get('cy', 0)
        if not (560 < cy < 700):        # ⭐ 只看那一行（实测 630~660）✓
            continue
        # ⚠⚠ 第一个数是**剩余**（不是已用）—— 见上面那段源码推导 ✓
        remaining, lim = int(m.group(1)), int(m.group(2))
        if best is None or cy < best[2].get('cy', 9999):
            best = (remaining, lim, it)
    if best is None:
        return None
    return best


def _dismiss_reward_popup(b, log=None, tag='ads', sub=''):
    """点掉「恭喜获得」那种**领奖弹窗** ⇒ True/False

    ⚠⚠ 2026-10-15 真机实测：**领奖成功后必弹这个，它会把 `N/M` 计数盖住** ✗
      不点掉就读不到新计数 ⇒ 会误判成"没领到" ✗
      （体力那格实测：点广告 ⇒ 弹「恭喜获得 货币 200」⇒ 点「返回」⇒ 计数 `3/3→2/3` ✓）
    ⚠ 一律**每轮重新取帧**再找（弹窗有出现动画 ✗）
    ⚠ 文案以「返回」为主（实测），「确定/确认」兜底 —— 都是**关掉**的语义 ✓
    """
    for k in range(5):
        items = GC.ocr_items(b, tag='%s_dp%d' % (sub or tag, k))
        if not GC.has(items, '恭喜获得', '获得'):
            return True             # 没弹窗 ⇒ 已经是干净的 ✓
        it = GC.find(items, '返回', '确定', '确认')
        if not it:
            time.sleep(0.5)
            continue
        b.tap(it['cx'], it['cy'], wait=1.9)
        GC._log(log, {'ads': 'dismiss_reward', 'text': it['text'],
                      'at': (it['cx'], it['cy']), 'try': k + 1})
        return True
    return False


def _maybe_confirm(b, log=None, tag='ads'):
    """处理"资源不足 ⇒ 是否购买"那个**确认框**（源码 `Interface_Tips_76/77/79`）⇒ True/False

    ⚠ 实测本号**没弹**（点绿加号直接开面板）—— 但**资源不足时会弹** ✓
      ⇒ 两条路都要处理，不能假设只有一条 ✗
    ⚠ 只点「确定/是」，**绝不点「取消」**以外的东西（`ADS_CONFIRM_NO` 兜底关掉 ✓）
    """
    for k in range(3):
        items = GC.ocr_items(b, tag='%s_cf%d' % (tag, k))
        # 已经是购买面板了 ⇒ 说明确认框已经过了（或本来就没弹）✓
        if _panel_open(items):
            return True
        # 认确认框：文案里带「不足」+ 「是否购买」
        _hit = None
        for it in (items or []):
            t = str(it.get('text') or '')
            if ('不足' in t and '购买' in t) or '是否购买' in t:
                _hit = it
                break
        if not _hit:
            return False                    # 没确认框 ⇒ 没有要处理的 ✓
        say('   · 出现确认框：「%s」⇒ 点「确定」' % _hit['text'])
        _yes = None
        for it in (items or []):
            if str(it.get('text') or '').strip() in ADS_CONFIRM_YES:
                _yes = it
                break
        if _yes:
            b.tap(_yes['cx'], _yes['cy'], wait=2.0)
            GC._log(log, {'ads': 'confirm_yes', 'text': _yes['text'],
                          'at': (_yes['cx'], _yes['cy'])})
        else:
            return False                    # 找不到确定 ⇒ **不瞎点** ✗
        time.sleep(0.6)
    return _panel_open(GC.ocr_items(b, tag='%s_cf_f' % tag))


def _close_panel(b, log=None, tag='ads'):
    """关掉当前购买面板（点 X）⇒ True/False"""
    items = GC.ocr_items(b, tag='%s_cx' % tag)
    if not _panel_open(items):
        return True
    b.tap(ADS_PANEL_X[0], ADS_PANEL_X[1], wait=1.8)
    items2 = GC.ocr_items(b, tag='%s_cx2' % tag)
    ok = not _panel_open(items2)
    GC._log(log, {'ads': 'close_panel', 'at': ADS_PANEL_X, 'ok': ok})
    return ok


def _is_hud_screen(items):
    """这一帧是不是**有 HUD 的普通界面**（HUD 入口在那儿）

    ⚠ HUD 上的资源数字（金币 `5982359` / 四叶草 `779` / 体力 `N/2500`）
      在**大厅/公会/选图**都有 ⇒ 只要能看到它们就能点入口 ✓
    ⚠ 判据用 **体力 `数字/2500` 那一格**（它在 HUD 左侧、最稳 ✓）
      或直接认金币/四叶草的数字都在 ✓
    """
    has_energy = False
    for it in (items or []):
        t = str(it.get('text') or '')
        cy = it.get('cy', 999)
        if cy < 90 and '/' in t and re.match(r'^\s*\d+\s*/\s*\d+\s*$', t):
            # 体力那格（`1306/2500`）—— **不是**广告的 `0/3`（那个在面板里 y>600）✓
            if cy < 90:
                has_energy = True
    return has_energy


# ══════════════════════════════════════════════════════════════════════
# ③ 单项：购买体力 / 四叶草 / 金币（各自的广告按钮）
# ══════════════════════════════════════════════════════════════════════
def buy_with_ad(b, which, log=None, tag='ads', max_times=3, dry=False):
    """对某一项（gold/clover/energy）**反复看广告领奖** ⇒ 领到的次数

    ---- 完整动作（每一轮都重新取帧 ✓）----
      ① 点 HUD 入口（绿加号 / 体力数字）⇒ 开购买面板
      ② 处理可能的确认框（`_maybe_confirm`）
      ③ **OCR 现读**那颗 `N/M`（`read_ad_counter`，⚠ **N 是「剩余」**）
         · 没读到 ⇒ **不瞎点**、如实上报 ✗
         · **剩余 ≤ 0**（`remaining <= 0`）⇒ **今天到此为止** ✓
           ⛔⛔ 判据必须是 `remaining <= 0`（**不是** `used >= limit` ✗）——
             我原来读成"已看/上限"⇒ `0 >= 3` 为假 ⇒ 在**已经用完**的面板上照样点 ✗
             （真机铁证：点下去弹「今日观看广告达到上限」✓ 用户也当场纠正过 ✓）
      ④ 点那颗绿按钮 ⇒ **有免广时直接领到**
         ⚠ 领完会弹「**恭喜获得**」，**它盖住计数** ⇒ 必须**先点「返回」再读计数** ✗
      ⑤ 关面板 ⇒ 下一轮
    ⚠ `max_times` 是**防呆上限**（三项的源码上限都是 3 ⇒ 默认 3 ✓）
    ⚠ 用户口径「**每天三次**」⇒ 领满 3 次就停 ✓
    """
    title = ADS_TITLES[which]
    got = 0
    for r in range(max(1, int(max_times))):
        if dry:
            say('   · [dry-run] %s：跳过第 %d 次' % (title, r + 1))
            continue
        # ① 开面板
        items = GC.ocr_items(b, tag='%s_%s_o%d' % (tag, which, r))
        if not _panel_open(items, which):
            entry = {'gold': ADS_HUD_GOLD, 'clover': ADS_HUD_CLOVER,
                     'energy': ADS_HUD_ENERGY}[which]
            b.tap(entry[0], entry[1], wait=2.4)
            items = GC.ocr_items(b, tag='%s_%s_o%dc' % (tag, which, r))
            GC._log(log, {'ads': 'open_panel', 'which': which,
                          'at': entry, 'open': _panel_open(items, which)})
            if not _panel_open(items, which):
                _maybe_confirm(b, log, tag)
                items = GC.ocr_items(b, tag='%s_%s_o%dd' % (tag, which, r))
            if not _panel_open(items, which):
                say('   · %s：没打开面板（第 %d 次）⇒ 停手如实上报' % (title, r + 1))
                GC._log(log, {'ads': 'panel_not_open', 'which': which})
                break
        # ③ 读广告计数（⚠ 第一个数是**剩余**，见 `read_ad_counter` 的源码推导）
        cnt = read_ad_counter(items)
        if cnt is None:
            say('   · %s：读不到广告次数 `N/M` ⇒ **不瞎点** ✗' % title)
            GC._log(log, {'ads': 'counter_missing', 'which': which})
            _close_panel(b, log, tag)
            break
        remaining, limit, it = cnt
        # ⛔⛔ 判据必须是 `remaining <= 0`（**不是** `used >= limit`）✗
        #   「`0/3` = 没得领了」—— 我原来读反了，在已用完的面板上照点 ✗
        if remaining <= 0:
            say('   · %s：广告次数**已用完**（剩 %d/%d）⇒ 今天到此为止 ✓'
                % (title, remaining, limit))
            GC._log(log, {'ads': 'limit_reached', 'which': which,
                          'remaining': remaining, 'limit': limit})
            _close_panel(b, log, tag)
            break
        say('   · %s：还能领 **%d** 次（剩 %d/%d）'
            % (title, remaining, remaining, limit))
        # ④ 点绿按钮（**看广告那颗**）
        b.tap(it['cx'], it['cy'], wait=2.6)
        GC._log(log, {'ads': 'tap_ad_btn', 'which': which,
                      'at': (it['cx'], it['cy']),
                      'was_remaining': remaining, 'limit': limit})
        say('   · %s [%d] ⇒ 点广告按钮 (%d,%d)（当时剩 %d/%d）'
            % (title, got + 1, it['cx'], it['cy'], remaining, limit))
        # ⭐⭐ 2026-10-15 **真机实测：点完会弹「恭喜获得」，它挡住计数** ✗
        #   铁证（体力那格）：点完 ⇒ 体力 `1306 → 1555`（+200）+ 弹「恭喜获得」
        #     ⇒ **免广告真的生效**（没播视频直接给了 ✓）
        #     但那时**读不到 `N/M`**（被弹窗盖住）⇒ 必须先点「返回」 ✓
        #     点完「返回」⇒ 计数变 `3/3 → 2/3` ✓（**这就是"领到了"的铁证**）
        #   ⚠ 所以顺序 = **点广告 → 点返回 → 读计数**（别省中间那步 ✗）
        _dismiss_reward_popup(b, log, tag, '%s_%s' % (tag, which))
        items2 = GC.ocr_items(b, tag='%s_%s_r%d' % (tag, which, r))
        if GC.has(items2, ADS_LIMIT_TIP):
            say('   · ⚠ 提示「%s」⇒ 今天到此为止 ✓' % ADS_LIMIT_TIP)
            GC._log(log, {'ads': 'limit_tip', 'which': which})
            _close_panel(b, log, tag)
            break
        if GC.has(items2, ADS_FAIL_TIP):
            say('   · ⚠ 提示「%s」⇒ **如实上报、不重试死磕** ✗' % ADS_FAIL_TIP)
            GC._log(log, {'ads': 'ad_failed', 'which': which})
            _close_panel(b, log, tag)
            break
        # 剩余数**变少** ⇒ 领到了 ✓（**不靠"掉了什么"判，靠计数** —— 面板数字最可靠 ✓）
        cnt2 = read_ad_counter(items2)
        if cnt2 and cnt2[0] < remaining:
            got += 1
            say('       · ✓ 领到（剩余 %d/%d → %d/%d）'
                % (remaining, limit, cnt2[0], cnt2[1]))
            GC._log(log, {'ads': 'claimed', 'which': which,
                          'now_remaining': cnt2[0], 'limit': cnt2[1]})
        else:
            # 剩余没动 ⇒ **不猜**，如实记下来，交给上层看日志 ✓
            say('       · ⚠ 剩余数没变（仍 %s）⇒ 如实记录（见日志）'
                % ('%d/%d' % (cnt2[0], cnt2[1]) if cnt2 else '读不到'))
            GC._log(log, {'ads': 'counter_unchanged', 'which': which,
                          'before_remaining': remaining, 'limit': limit,
                          'after': ('%d/%d' % (cnt2[0], cnt2[1])) if cnt2 else None,
                          'texts': GC._texts(items2)[:12]})
            # ⚠ **这里不能再 got += 1**（我原来那么写 ⇒ 白点也算"领了" ✗）
            #   —— 剩余数没动说明**没领到** ⇒ 如实不加 ✓
            #   ⚠ 但也**不能死循环**：`max_times` 兜住 ✓
            break
        # ⑤ 关面板（下一轮重新开 ⇒ 拿到最新计数 ✓）
        it3 = GC.ocr_items(b, tag='%s_%s_e%d' % (tag, which, r))
        if not _panel_open(it3, which):
            # 面板自己关了（可能因为领奖后自动关）⇒ 下一轮重新开 ✓
            continue
        _close_panel(b, log, tag)
    return got


# ══════════════════════════════════════════════════════════════════════
# ④ 加速炼金（`AlchemySkip`，每日 1 次）
# ══════════════════════════════════════════════════════════════════════
def alchemy_accel(b, log=None, tag='ads'):
    """炼金加速（`AlchemySkip`）：点沙漏 → **读 `N/1` 计数** → 点「看广告」⇒ True/False

    ⭐ 用户口径（原话）：
        「**正在倒计时的炼金宝箱就能看到用广告的界面，点那个沙漏就行，你之前点过**」
      ---- 真机实测路径（2026-10-15，综合模拟器）----
        ① 炼金**进行中**时，宝箱上有**倒计时** `(240,338)`
           ⚠ 倒计时**旁边那颗橙色沙漏**就是加速入口 = **`(360,338)`** ✓
        ② 点沙漏 ⇒ 弹「**提示**」框：
             文案 `Tips_Allsystem_98`「**选择观看广告或者花费宝石加速炼金？**」
             左红宝石 `(226,742)` = 花 **187 宝石**（`cost = timer/60 + 1` ⇒ **随剩余时间变**）
             **右绿按钮 `(510,742)` = `0/1`** ← 看广告 ✓
        ③ 点绿按钮 ⇒ 有免广就**关弹窗 + 给奖励**

    ⛔⛔ 2026-10-15 **我又踩了一个坑，而且这次是"部分对"**（诚实记账）
      ---- 我原来的推断 ----
        「有免广 ⇒ `canSkipAds = true` ⇒ 点一下 `canClaimReward = true; OnClose()`
          ⇒ **直接领到**」—— 只对了**一半** ✗
      ---- 源码里那两行的**真实顺序**（`AdPrompt.OnWatchAdBtnClicked`）----
            `int num  = save.AdsWatchedTime[(int)currentAdType];`     // 已看
            `int num2 = SaveData.MaxAdsDailyLimit[(int)currentAdType];`
            `if (num >= num2) { ShowMessage("今日观看广告达到上限"); return; }` ← ⚠ **先查上限**
            `...`
            `if (canSkipAds) { canClaimReward = true; OnClose(); }`        ← 才轮到免广
      ⇒ **次数用完 ⇒ 连免广都领不到**，直接弹「今日观看广告达到上限」✓
      ---- 真机铁证 ----
        我在 `0/1`（**剩余 0** = 今天用过）的弹窗上点了 3 次，每次都是
        弹一下「**今日观看广告达到上限**」就没了（抓到 0.35 秒那一帧为证）✓
      ---- ⚠ 教训 ----
        `canSkipAds` 那段**看着像"免广 = 无条件直接领"**，但它**前面还有一道上限闸门** ✗
        「读到一段分支就下结论、没往上读两行」—— 这正是本项目反复吃的那种亏 ✓

    ⚠ 所以本函数**必须和那三项一样先读计数**（`read_ad_counter`，第一个数是**剩余**）✓
    ⚠ 弹窗里的 `N/1` 也在 **y≈742** —— `read_ad_counter` 圈的是 `560<y<700` ✗ 够不着
      ⇒ 本函数**自带一个读法**（`_read_accel_counter`），y 圈 `700<y<790` ✓
    ⚠ 只点**绿按钮**（看广告）；**绝不点花宝石**那颗（187 宝石 ✗）
    """
    items = GC.ocr_items(b, tag='%s_al0' % tag)
    _on_popup = (GC.has(items, '观看广告') or GC.has(items, '加速炼金')
                 or GC.has(items, '花费宝石'))
    if not _on_popup:
        # ① 点沙漏（**倒计时旁边那颗**）
        b.tap(ADS_ALCH_HOURGLASS[0], ADS_ALCH_HOURGLASS[1], wait=2.4)
        items = GC.ocr_items(b, tag='%s_al1' % tag)
        _on_popup = (GC.has(items, '观看广告') or GC.has(items, '加速炼金')
                     or GC.has(items, '花费宝石'))
        GC._log(log, {'ads': 'alch_hourglass', 'at': ADS_ALCH_HOURGLASS,
                      'popup': _on_popup})
        if not _on_popup:
            say('   · 加速炼金：点了沙漏但没出加速弹窗'
                '（多半是**炼金没在进行中**）⇒ 跳过 ✓')
            return False
    say('   · 加速弹窗已开（含「观看广告/加速炼金」✓）')
    # ② **读计数**（`N/1`，第一个数是**剩余** —— 与那三项同口径 ✓）
    _cnt = _read_accel_counter(items)
    if _cnt is None:
        say('   · 加速炼金：读不到 `N/1` 计数 ⇒ **不瞎点** ✗')
        GC._log(log, {'ads': 'alch_counter_missing',
                      'texts': GC._texts(items)[:12]})
        b.tap(ADS_ALCH_X[0], ADS_ALCH_X[1], wait=1.6)   # 关掉，不加速 ✓
        return False
    remaining, limit, it = _cnt
    if remaining <= 0:
        # ⚠ 这就是我实跑撞到的那次：`0/1` ⇒ 今天用过了 ⇒ **点也没用**（会弹上限提示）✗
        say('   · 加速炼金：广告次数**已用完**（剩 %d/%d）⇒ 今天到此为止 ✓'
            % (remaining, limit))
        GC._log(log, {'ads': 'alch_limit_reached',
                      'remaining': remaining, 'limit': limit})
        b.tap(ADS_ALCH_X[0], ADS_ALCH_X[1], wait=1.6)   # 关掉弹窗 ✓
        return False
    say('   · 加速炼金：还能领 %d 次（剩 %d/%d）' % (remaining, remaining, limit))
    # ③ 点绿按钮（**看广告那颗**）—— **OCR 现读**优先 ✓
    b.tap(it['cx'], it['cy'], wait=2.6)
    GC._log(log, {'ads': 'alch_tap_ad', 'at': (it['cx'], it['cy']),
                  'was_remaining': remaining, 'limit': limit})
    say('   · 加速炼金 ⇒ 点「看广告」(%d,%d)（当时剩 %d/%d）'
        % (it['cx'], it['cy'], remaining, limit))
    # ④ 看结果（**快速抓**，上限/失败提示只显示一两秒 ✗）
    items2 = GC.ocr_items(b, tag='%s_al2' % tag)
    if GC.has(items2, ADS_FAIL_TIP):
        say('   · ⚠ 「%s」⇒ 如实上报 ✗' % ADS_FAIL_TIP)
        GC._log(log, {'ads': 'alch_ad_failed'})
        return False
    if GC.has(items2, ADS_LIMIT_TIP):
        say('   · ⚠ 「%s」⇒ 今天到此为止 ✓' % ADS_LIMIT_TIP)
        GC._log(log, {'ads': 'alch_limit'})
        b.tap(ADS_ALCH_X[0], ADS_ALCH_X[1], wait=1.6)
        return False
    # ⑤ 判"成了"：**弹窗消失** 或 **倒计时明显变短** ✓
    #   ⚠ 有免广时源码走 `OnClose()` ⇒ **弹窗直接关掉**（不给「恭喜获得」✗）
    #     ⇒ 所以"弹窗没了"就是最强信号 ✓
    _gone = not (GC.has(items2, '观看广告') or GC.has(items2, '花费宝石'))
    GC._log(log, {'ads': 'alch_result', 'popup_gone': _gone,
                  'texts': GC._texts(items2)[:12]})
    say('   · %s' % ('加速弹窗已关 ⇒ 加速成功 ✓' if _gone
                    else '弹窗还在 ⇒ 没加速成（如实上报）'))
    return bool(_gone)


def _read_accel_counter(items):
    """读加速弹窗里的 `N/1` ⇒ `(remaining, limit, 条目)` 或 None

    ⚠ 与 `read_ad_counter` 的**唯一区别是 y 圈**：加速弹窗那行在 **y≈742**
      （购买面板那三项在 y≈645）—— 所以不能共用一个函数 ✗
    ⚠ 第一个数仍是**剩余**（`{上限-已看}`，同源码那行减法 ✓）
    """
    best = None
    for it in (items or []):
        t = str(it.get('text') or '')
        m = _AD_RE.match(t)
        if not m:
            continue
        cy = it.get('cy', 0)
        if not (700 < cy < 790):        # ⭐ 加速弹窗那一行（实测 742）✓
            continue
        remaining, lim = int(m.group(1)), int(m.group(2))
        if best is None or cy < best[2].get('cy', 9999):
            best = (remaining, lim, it)
    return best


# ══════════════════════════════════════════════════════════════════════
# ⑤ 主流程
# ══════════════════════════════════════════════════════════════════════
def run(b, log=None, skip_ads=True, alchemy=True, times=3, dry=False,
        enter_guild=True, return_to_map=True):
    """广告领奖总入口 ⇒ 汇总 dict

    用户口径：**默认有免广**（`skip_ads=True`）⇒ 四项都自动做 ✓
    ⚠⚠ **`skip_ads=False` ⇒ 四个入口一下都不碰**（用户口径「未勾则不做」✓）
      —— 因为无免广时要真播视频广告，**脚本做不了**（模拟器里广告起不来 ✗）
    ⚠ 只做用户点名的四项：购买体力(3) / 四叶草(3) / 金币(3) / 加速炼金(1) ✓
      源码里另外三项（奇遇/立即完成探索/秘境）**不做** ✓

    ⭐⭐⭐ 2026-10-15 **用户口径**（原话，统一三个脚本的进出场）：
        「体力用完后，把勾选的公会日常，免费招募和免广告
          （**这三个脚本的最后都要回到地图界面，最开始都要进入公会界面**）
          都做完后，检查下体力，如果超过100，就重新启动探图脚本」
      ---- 所以本函数也**统一成"进公会 → 干活 → 回地图"** ✓ ----
        · 入口：`enter_guild=True` ⇒ 先 `GC.goto_guild`
          ⚠ 广告领奖本身**不依赖公会**（入口在 HUD，任何界面都能点 ✓）
            那为什么还进公会？—— 用户要的是**三个脚本位置语义一致**：
            上一个（招募）结束时在选图界面，下一个（广告）开头进公会 ⇒
            串起来可预测 ✓
        · 出口：`return_to_map=True` ⇒ `GC.leave_guild` 回选图界面 ✓
    """
    log = log if log is not None else []
    res = {'ok': False, 'skip_ads': bool(skip_ads), 'gold': 0, 'clover': 0,
           'energy': 0, 'alchemy': False, 'why': None}
    say('')
    say('=' * 62)
    say('📺 广告领奖（购买体力/四叶草/金币 + 加速炼金）')
    say('=' * 62)

    # ── 入口：**先进公会**（用户口径「最开始都要进入公会界面」✓）──
    #   ⚠ 放在 `skip_ads` 早退**之前** —— 不然"没勾免广"时就不进公会了，
    #     与用户要的"三个脚本行为一致"不符 ✗（进公会本身无害 ✓）
    if enter_guild:
        _ing = GC.goto_guild(b, log)
        res['entered_guild'] = bool(_ing)
        if not _ing:
            say('   ⚠ 进不了公会 ⇒ 仍继续做广告领奖'
                '（它的入口在 HUD 上，**不依赖公会** ✓）')

    if not skip_ads:
        # ⛔ **用户口径：「未勾则不做」** ⇒ 一下都不碰 ✓
        say('   · ⚠ 没勾「有免广告」⇒ **四个入口一下都不碰** ✓')
        say('      （无免广要真播视频广告，脚本做不了 ⇒ 不冒险 ✗）')
        res['why'] = 'no_skip_ads'
        res['ok'] = True            # **不是失败** —— 是"按口径不做" ✓
        _ads_back_to_map(b, log, res, return_to_map)
        return res

    say('   · 有免广告 ⇒ 点一下就**直接领**（不跳广告）✓')
    say('   · 本次四项：金币×3 ｜ 四叶草×3 ｜ 体力×3 ｜ 加速炼金×1')
    say('   ⚠ 全程**不花宝石**（只点"看广告"那颗绿按钮 ✗）')

    # ---- ① 三项资源（都在 HUD 上，**同一屏就能全做**）----
    for which, nm in (('gold', '金币'), ('clover', '四叶草'), ('energy', '体力')):
        try:
            n = buy_with_ad(b, which, log, tag='ads', max_times=times, dry=dry)
            res[which] = n
            say('   · **%s**：领了 %d 次 ✓' % (nm, n) if n
                else '   · **%s**：没领到（0 次）' % nm)
        except Exception as e:                          # noqa: BLE001
            import traceback as _tb
            log.append({'ads': '%s_error' % which, 'e': repr(e)[:160],
                        'trace': _tb.format_exc().splitlines()[-4:]})
            say('   ⚠ %s 出错：%r' % (nm, e))
        time.sleep(0.4)

    # ---- ② 加速炼金（**只炼金进行中才有** — 用户口径「每天1次」）----
    if alchemy:
        try:
            res['alchemy'] = alchemy_accel(b, log, tag='ads')
            say('   · **加速炼金**：%s' % ('已加速 ✓' if res['alchemy']
                                        else '没做（没在炼 / 没加速成）'))
        except Exception as e:                          # noqa: BLE001
            import traceback as _tb2
            log.append({'ads': 'alchemy_error', 'e': repr(e)[:160],
                        'trace': _tb2.format_exc().splitlines()[-4:]})
            say('   ⚠ 加速炼金出错：%r' % (e,))
    else:
        say('   · 没勾「加速炼金」⇒ 跳过')

    res['ok'] = True
    GC._log(log, {'ads': 'done', 'gold': res['gold'], 'clover': res['clover'],
                  'energy': res['energy'], 'alchemy': res['alchemy']})
    _ads_back_to_map(b, log, res, return_to_map)
    say('=' * 62)
    return res


def _ads_back_to_map(b, log, res, want):
    """收尾：**回地图界面（选图界面）** ✓

    ⭐ 用户口径：「**这三个脚本的最后都要回到地图界面**」✓
    ⚠ 三个出口（没勾免广的早退 / 正常做完 / 后面可能再加）**都要走这里** ⇒
      抽成一个函数，免得某个出口忘了回 ✗（本项目踩过"某条分支漏了收尾"的坑 ✓）
    """
    if not want:
        say('   · 按要求**停在原地**（没回地图界面）')
        return
    _back = GC.leave_guild(b, log)
    res['back_to_map'] = bool(_back)
    say('   · %s' % ('已返回地图界面（选图界面）✓' if _back
                    else '⚠ 没确认回到选图界面（如实上报）'))
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
    ap = argparse.ArgumentParser(description='广告领奖（需有免广告）')
    ap.add_argument('--device', default=None, help='adb 设备号')
    ap.add_argument('--tag', default='ads', help='实例名')
    ap.add_argument('--no-skip-ads', dest='skip_ads', action='store_false',
                    default=True, help='**没有免广告**（⇒ 四个入口都不碰 ✓）')
    ap.add_argument('--no-alchemy', dest='alchemy', action='store_false',
                    default=True, help='不做加速炼金')
    ap.add_argument('--times', type=int, default=3,
                    help='每项领几次（源码上限 3）')
    ap.add_argument('--dry-run', action='store_true', help='只看不点')
    a = ap.parse_args()

    if a.device:
        GC.set_device(a.device)
    import mapbot as MB
    b = MB.Bot(log_prefix='ads', serial=a.device, tag=a.tag)
    log = []
    res = run(b, log, skip_ads=a.skip_ads, alchemy=a.alchemy,
              times=a.times, dry=a.dry_run)
    say('')
    say('结果：金币 %s ｜ 四叶草 %s ｜ 体力 %s ｜ 加速炼金 %s%s'
        % (res.get('gold'), res.get('clover'), res.get('energy'),
           res.get('alchemy'),
           ('（%s）' % res['why']) if res.get('why') else ''))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
