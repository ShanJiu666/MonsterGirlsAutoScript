# -*- coding: utf-8 -*-
"""buypanels.py · 「买完」流程：旅行商人 / 黄金宝库（坐标全部实机实测 2026-09-25）

## 旅行商人（`GoldGambleBlockPanel`）
面板标题「旅行商人」(688,601)，X 关闭 (983,602)。用户口径：**买 4 次**。
实机验证过的循环：购买(895,1255) → 返回(539,1212)，重复 4 次 → 关闭 X。
（效果：依次在四个档位购买，每次消耗的金币递增）

## 黄金宝库（`GoldenVaultBlockPanel`，源码 57315 起）
5x5 的 25 件宝物，分 3 圈：外圈 16 件(1 层) / 内圈 8 件(2 层) / 正中心 1 件(3 层)，
**每层只能拿一件**；要拿下一层必须先花金币解锁：
    10000 解锁第 1 层 → 选一件领 → 20000 解锁第 2 层 → 选一件领
    → 40000 解锁第 3 层 → 选中心那件领 → 「完成」结算      合计 70000 金币
图标坐标：x = 251 + 144*c，y = 746 + 144*r（5x5，实测 135x135 一格）
按钮（购买/选择/完成都是它）：(896,1444)；标题「黄金宝库」(692,383)，X (983,384)

用法:
    from buypanels import merchant_flow, vault_flow
    merchant_flow(bot, log)
    vault_flow(bot, log)

## ⭐⭐ 坐标口径（2026-09-30 v0.61 修正，真机事故）
本模块所有常数（标题/按钮/5×5 格子/X/返回/空白）都是**PC 实测值**，而 PC 上
「弹窗空间 == 参考系」（C=0）⇒ 这些常数其实是**居中弹窗系**坐标。
真机上弹窗**锚设备屏幕中心**，与棋盘的「顶块锚顶 + 其余锚底」不是同一坐标系：
    真机 1280×2772 ⇒ C = RefMapper.dialogShift() = 209.44
    「选择奖励/购买」按钮 (895,1444)： b.tap → dev 2208 ／ b.tap_dlg → dev 1960
    差 **248px**，而按钮才 ~110px 高 ⇒ 旧写法（全走 b.tap）**每一击都落在按钮外面**，
    真机症状就是「黄金宝库买完 0 个 / 点不掉」（旅行商人同理）。
⇒ 现在**统一走弹窗系**：`_items()` 把 OCR 条目经 `dlg_items()` 映射到弹窗系，
  所有点击走 `bot.tap_dlg()`，图标模板匹配用 `bot.img_dlg()`。
  PC 侧 `dlg_items()` 恒等、`tap_dlg()`/`img_dlg()` 退化为 `tap()`/`img()` ⇒ **行为一字不变** ✓

⚠ 归一化帧会**整段丢掉**弹窗系 y ∈ (202, 509)（toRef 丢弃的弹性区）⇒ 标题「黄金宝库」
  (383) 与 X (384) 在归一化帧**根本不存在**，别再用 `_has(it, 标题)` 判面板存在性
  （旧代码为此补了 `_has_dlg` 的整帧弹窗 OCR，每次 ≈2s）。现在用**右下角按钮文字**判
  （它落在弹窗系 1444 ⇒ 归一化帧 1235，band 内看得见），`_has_dlg` 只作兜底。
"""
import os
import sys
import time

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `templates/` `runs/` `data/` 这些资源都相对**仓根** ⇒ 必须多上一级。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                    # ⭐ v0.61：两端共用一套「弹窗系」API
    from mapbot import dlg_items, dlg_shift      # noqa: F401
except Exception:                       # noqa: BLE001  老版 mapbot 没有 ⇒ 退化为恒等
    def dlg_items(items):
        return items

    def dlg_shift():
        return 0.0


# ⚠⚠⚠ 2026-10-02 全仓排查「1080p→720p 换基准」：本文件的常量是**720×1600 真机**
#   （归一化系）标定的，换到 PC 的 **720×1280** 基准后**整组越界**
#   （y 最大 1590 > 屏高 1280；x 最大 983 > 屏宽 720）⇒ 点宝库/商人一律点空 ✗
#   ⚠ PC 上 `mapbot.tap_dlg` 的 `dlg_c()` **恒 0** ⇒ tap_dlg 就是 tap
#     ⇒ **没有任何自动换算兜底** ⇒ 不折算必点空 ✓
#   系数 720/1080 的正确性有交叉验证：`MERCHANT['back']` 折算得 (359,808)，
#   与 `layout.REF['back_btn']` / `fixed.A('back_btn')` **完全一致** ✓
_PCS = 720.0 / 1080.0            # = 0.666667


def _s(v):
    """把旧基准（1080p 系）的标定值折算成 720×1280 设备系（整数）"""
    return int(round(v * _PCS))


MERCHANT = {'title': '旅行商人',
            'x': (_s(983), _s(602)), 'buy': (_s(895), _s(1255)),
            'back': (_s(539), _s(1212)), 'times': 4,
            # ⭐⭐⭐ 2026-10-02 用户报「四次间隔好像不一样」+ 真机时间戳实测（tap_trace）：
            #   第一次进商人：购买→返回 = **2.0 / 0.0 / 0.0 / 1.0 / 5.0 / 1.0 s**（乱✗）
            #   根因：`b.tap_dlg(..., wait=X)` **不是定死间隔** —— 极速截图下它是
            #     "画面一变就返回"（≈0.1~0.3s）⇒ 同一秒里能连点「购买」「返回」；
            #     再叠上 `_confirm()` 里那次 OCR/同帧缓存的命中与否 ⇒ 每轮又多一层差异 ✗
            #   ⇒ 现在：**三个间隔都用显式 `time.sleep` 定死，4 轮完全一样** ✓
            #     （用户 2026-10-02 口径：「**第一次购买和返回间隔是对的，后面三次都按第一次走**」）
            #   想调节奏只改这三行 —— 改完 4 轮一起变，不会再出现"每轮不一样"。
            #   参考：真机实测"能买到 4 件"的那一轮节奏 ≈ 5~7 秒/轮 ✓
            'buy_wait': 2.0,        # 点「购买」后等（照第一次实测的 2.0s）
            'reward_wait': 2.0,     # 奖励页/刷新站稳再点返回
                                    #   （原来这步叫 confirm_wait = "处理确认框"；
                                    #    2026-10-02 用户定调"完全不需要 OCR" ⇒ 确认框那步
                                    #    已删（真机日志里从没出现过购买确认框）⇒ 改名 ✓）
            'back_wait': 2.0}       # 点「返回」后等（回商店站稳再做下一轮）


def say(*a, **k):
    """本模块的日志出口。

    ⚠⚠ 2026-10-01 v0.97 修**真机崩溃**：本文件里只有一处用到 `say`（第 736 行附近那条
      "读不到按钮 ⇒ 标定坐标保底"），但**从来没导入过它** ⇒ 走到那条分支就
      `NameError: name 'say' is not defined` ⇒ **整条宝库流程当场中断**
      （真机 22:50 实测：第 2 圈连点 4 次「购买」后崩，面板停在「恭喜获得 装备」+「返回」
        的界面上，只能靠 `ensure_closed` 收尾 ✗）
      ⇒ 现在自带兜底：拿得到 `explore_loop.say` 就用它（两端日志口径一致 ✓），
        拿不到就 `print`（端上照样进 logcat ✓）。**惰性取**，避免循环导入 ✓
    """
    try:
        _el = sys.modules.get('explore_loop')
        _f = getattr(_el, 'say', None) if _el is not None else None
        if _f is not None:
            return _f(*a, **k)
    except Exception:       # noqa: BLE001
        pass
    print(*a)


# ⭐ v0.97：真机「返回」按钮的**专用判据窗口**（与 `VAULT['back']` 那个"兜底落点"解耦）
#   实测两处：奖励展示时的「返回」在弹窗系 (538, 1212)（PC 值）/ (538, 1267)（真机帧 OCR）
#   ⇒ 取中 (539, 1240) 作中心，容差放宽
VAULT_BACK_ZONE = (360, 806)
# ⭐⭐⭐ 2026-10-03 **真机实测重标**（用户报「黄金宝库无法正常购买」+ 当场让我抓屏：
#   `_verify/vault_back_20261003.png`，奖励展示态「恭喜获得 神石」）：
#       返回  cx=360 cy=808  bbox (332,792)-(387,823)  conf 1.00
#       购买  cx=598 cy=962  bbox (572,947)-(624,977)  conf 1.00
#   旧值 `VAULT_BACK_ZONE=(359,827)` ⇒ **落在「返回」按钮下边缘之下 4px ＝ 点空** ✗
#   旧值 `VAULT['buy']=(596,998)`   ⇒ **比按钮下边缘还低 21px ＝ 点空** ✗
#     （平时 OCR 读得到文字时用的是**识别到的坐标**，所以只有走"标定坐标兜底"才暴露 ✗）
#   ⇒ 现在两个都用实测值；购买/选择奖励两态的 y 分别是 962 / 978（差 16px）
#     ⇒ 取中间 **970**，两态都落在按钮内 ✓
#   ⚠ 「返回」是**另一个按钮**（用户当场纠正：「返回不是同一个按钮」）⇒ 绝不能用购买坐标点返回 ✗
# ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**购买和选择奖励是一个**（按钮）……
#   选择奖励后的返回也是固定位置」+「**返回不是同一个按钮**」⇒
#   整条宝库流程用**两个固定坐标**驱动，不再依赖 OCR 找按钮文字：
#       · 购买 / 选择奖励（**同一个按钮**）→ `VAULT['buy']`（720p = 596,998）
#       · 返回（**另一个按钮**，位置固定）   → `VAULT_RET`（720p = 359,827）✓
#   ⛔ 绝不能用购买按钮的坐标去点返回（用户当场纠正过）✗
VAULT_RET = VAULT_BACK_ZONE              # 「返回」的固定落点 ✓

# ⭐⭐⭐ 2026-10-01 **真机帧实测重标定**（vault4_dlg.png，用户停在宝库面板抓帧，
#   我把每个常量画在帧上逐个核对 —— 三个都是错的 ✗）：
#     常量        旧值          真机实际（帧上所见）                    后果
#     blank      (540,1700)   那里是**面板外**（底部格子区）⇒ 落点压在宝箱/棋盘上 ✗
#     back       (539,1212)   落在**第 4 行格子上**（不是「返回」按钮）✗
#     buy        (895,1444)   真机按钮文字在 y=**1498**（旧值偏上 54px）✗
#     x          (983, 384)   ✓ 正确（右上角 X）
#   ⇒ 「点空白处关详情」在真机上等于**在棋盘上乱点**（用户报「点一下左上角格子、
#     关闭宝库界面」的元凶之一 ✗）
#   ⇒ 现在：blank 取**面板内、网格下方、说明文字右侧**的安全空白；buy 用实测 1498
VAULT = {'title': '黄金宝库', 'x': (_s(983), _s(384)),
         'buy': (597, 970),              # ⭐ 2026-10-03 实测重标（旧 998 比按钮下边缘低 21px ⇒ 点空 ✗）
         # ⚠ `back`/`blank` 取**面板内安全空白**（绝不能落在奖励格上 ⇒ 等于替用户点那格）
         #   原 1080p 系 (660,1590) ⇒ 720p (440,1060)
         #
         # ⛔⛔⛔ 2026-10-06 **真机实测修：旧值 (440,1060) 落在面板【外面】** ✗✗
         #   用户原话：「**刚刚又买一半关掉黄金宝库界面了**」＋「**把黄金宝库的点击范围固定下**」
         #   ── 铁证（`runs/vaultdbg/vault_no_hit_L1.png`，我逐像素量的）────────────────
         #      · 宝库面板**底边实测 y = 1048**（米色底最后一行的下一行就是暗紫棋盘）
         #      · 而旧 `blank`/`back` = **(440, 1060)** ⇒ **在面板外 12px** ✗
         #        （我在帧上画十字看过：它压在**底部那排道具格**上）
         #      · 逐帧统计：旧值在 **107 张真机宝库帧里通过率 = 0/107（0%）** ✗✗
         #   ── 后果（正是用户报的那句）─────────────────────────────────
         #     `blank` 的用途 = `_probe_name()` 里"**点空白收起详情面板**"
         #       （buypanels.py:731 `_probe_name` 结尾、:1669 探格后收回详情）
         #     ⇒ 它点在**面板外** ⇒ 那一下**根本没点在面板上**：
         #         轻则详情面板不收（下一格读数全错）；
         #         重则那一下落到**面板外/道具栏**，把宝库面板整个弄掉
         #         ⇒ 用户看到的「**买一半关掉宝库**」✓
         #     ⚠ 而且它和 `back` **是同一个值** —— 两处含义不同却共用，本身就是隐患 ✓
         #       ⇒ 本次**拆成两个独立常量**（值暂时相同，但改一个不会再误伤另一个 ✓）
         #   ── 新值的来历（不是目测，是**88 张网格态帧求交集**）────────────
         #     扫 `runs/vaultdbg/` + `_verify/` 里 **111 张**宝库帧，取"网格态"（面板
         #     y[231..1048]）的 **88 张**，对每个像素求"周围 21×21 全米色" ⇒ 取交集：
         #         x[276,650] y[297,391]  共 **17762** 个点
         #     ⇒ 选 **(475, 391)**：说明文字框**底部**、网格**上方**的空白带
         #        · 距最近格子中心 **200px**（绝不可能误触格子 ✓）
         #        · 88/88 网格态帧全部通过 ✓
         #        · 该带由"说明框底 + 网格顶"夹住，**两者都跟着面板走** ⇒ 比"网格下方"稳
         #          （网格下方有 `※ 花费金币…` 两行文案，会被文字顶开 ✗）
         #     ⚠ 另有 19 张帧不通过 —— 逐张查过，**全是别的状态**（奖励展示态
         #       y[543..738] / 面板下移态），而 `blank` **只在网格态探格时调用**
         #       ⇒ 那些状态根本走不到这里 ⇒ 不受影响 ✓
         #     （探针 `_tmpman/probe_vault_blank{4,5}.py`、`probe_vault_fail19.py`，可复跑）
         'back': (475, 391),
         'blank': (475, 391),
         # ── ⭐⭐⭐⭐⭐ 2026-10-06 **面板安全区（运行时自检用）** ─────────────────
         #   用户口径：「**把黄金宝库的点击范围固定下**」
         #   ⛔ 上面那个 bug 的教训：**常量写错时没有任何东西会报错** ——
         #     点在面板外和点在面板内，代码走的是同一条路（都是 `tap_dlg`）⇒ 静默失效 ✗
         #   ⇒ 定一个**面板安全矩形**（真机 720p 实测：面板 x[39,680] y[228,1048]），
         #     由 `_vault_tap()` 在**点击之前**把坐标夹进去 ⇒ **结构性保证点不出去** ✓
         #   ⚠ 留 10px 内缩（面板圆角/描边 ⇒ 贴边可能落到外面 ✗）
         'safe': (49, 670, 238, 1038),
         # 网格几何也跟着折算（`pitch` 参与格子换算，见 `_cell_of`/`_icon_col` ✓）
         'gx0': _s(251), 'gy0': _s(746), 'pitch': _s(144),
         'cols': 5, 'rows': 5
         # 真机帧实测网格（1080p 系）：x 251~827 pitch 144、y 746~1322 ⇒ 外框 179~899/674~1394
         # 720p 折算后：x 167~551 pitch 96、y 497~881 ⇒ 外框 119~599/449~929 ✓ 全在屏内 ✓
         }
VAULT_RING = {1: (0, 0), 2: (1, 1), 3: (2, 2)}      # 每层代表格（0 基 行,列）


# ⭐ v1.20：上界由 1560 放宽到 **1720**（锚定模型推导，不是目测放宽）
#   BAND 是**归一化帧**的 OCR 搜索带（归一化帧恒 1080×1920），而面板内容
#   **锚设备屏幕中心** ⇒ 同一元素在归一化系里的位置 = dlg_y − C，
#   而 C = 960 + (shift − H/2)/kx 随分辨率变（9:16 ⇒ 0，真机 1264×2780 ⇒ 227.7）。
#     · C > 0（长屏，H > 1920·kx）⇒ 元素在归一化系里**上移** ⇒ 旧 300 下界够用 ✓
#     · C < 0（**宽屏矮胖**，H < 1920·kx，如 1200×1920 的 5:4）⇒ 元素**下移** ⇒ 旧 1560 盖不住：
#         购买钮 dlg 1498 ⇒ 归一化 **1594**、价格 1541 ⇒ **1637** ⇒ 全部 OCR 不到
#         ⇒ `_btn` 恒返回 (None,None,None) ⇒ `no_select_btn` ⇒ **整层不买不选** ✗
#           （与 v1.19 摇色子同族：搜索带写死在 9:16 上，换分辨率静默失效）
#   ⇒ 下界 300 保留（再往上是被 toRef 丢掉的弹性区，取不到），
#     上界 1720 覆盖最坏情况（1200×1920 ⇒ 1637，留 ~83px 余量给文案行数浮动）。
#   ⚠ 这条断言已固化进回归 ㉝ 组（`tools/verify_panel_band_allres.py` × 9 分辨率）
#   ⚠ PC 上 C 恒 0 ⇒ 本改动对 PC **行为零影响**（band 上界只放宽不收紧）
# ⚠ 2026-10-02 换 720×1280 基准：面板坐标整体折算后最大 y ≈ 1060，
#   ⇒ 上界跟着收窄到 (_s(300), _s(1720)) = (200, 1147)，否则会扫到
#   **面板之外的棋盘区域**误认文字（原 1720 在 1280 屏上根本不存在 ⇒ 被裁到屏底，
#   反而把面板下方那块也扫进来）✓
BAND = (_s(300), _s(1720))   # 归一化帧里要 OCR 的 y 段 ⇒ 弹窗系 (300+C, 1720+C)

# ⛔⛔ 2026-10-02 **「窄带提速」被真机实测否决**（别再改回来了）
#   我按「带高 947px 占屏 74% ⇒ 大头在扫没字的地方」推断，改成三条定点窄带
#   （标题 230~300 / 按钮 900~1120 / 返回 820~1080，合计 550px）。
#   **真机实测打脸**（`Bot.ocr` 逐档量，带 `mapbot` 真实 Bot 对象）：
#       整屏 1280px   0.688 s/次
#       整带  947px   0.698 s/次     ← 和整屏**几乎一样**
#       窄带  220px   0.656 s/次     ← 几乎没省
#       窄带   70px   0.868 s/次     ← **反而更慢**
#   ⇒ **OCR 耗时由「预处理 + 模型推理」主导，与带高几乎无关**；
#     而**多次调用**要各付一遍固定开销 ⇒ 拆 3 条窄带**净亏** ✗
#   ⇒ 保留**单次整带**（本文件原有行为）。
#   ⭐ 真正该省的是**调用次数**，不是带高 —— 见 `_items` 里的说明。
NARROW_BANDS = None       # 保留名字仅作记录；已实测无效，别再用

# ⭐⭐⭐ 2026-10-02 提速（按**实测**结论做，不是按推测）
#   实测：OCR 单次 0.65~0.70s，且**与带高几乎无关** ⇒ 唯一有效的省法是**少调几次**。
#   `vault_flow` 一次流程要调 `_items` **8~25 次**（真机分账：panel 12.7s/25 次）。
#   ⭐ 判「要不要重新 OCR」的条件用**画面有没有变**（`board_luma`/棋盘亮度 + 面板签名），
#     **同帧复用上一次结果** ⇒ 连续问「按钮是什么/奖励展示了吗」这类
#     **不需要新截图**的追问，直接拿缓存。
#   ⚠ 安全门：**只在没有 `tap`/`snap` 之后才允许复用** ——
#     `Bot.ocr()` 读的是「上一次截图」，而 `tap()` 会让画面变 ⇒ 必须失效缓存。
#   ⚠ 判据用 `board_luma`（相对比较，2026-09-28 定的口径，不受面板遮罩影响）
_CACHE = {'luma': None, 'items': None, 'taps': 0}


# ⭐ 缓存挂在**调用方的 bot 实例**上（模块级字典会在多开/多图之间串味 ✗）
def _cache_of(bot):
    c = getattr(bot, '_bp_cache', None)
    if c is None:
        c = {'luma': None, 'items': None}
        try:
            bot._bp_cache = c
        except Exception:                                   # noqa: BLE001
            pass
    return c


def _invalidate(bot=None):
    """有任何 `tap` 之后调用：画面会变，缓存作废 ✓"""
    if bot is not None:
        _cache_of(bot)['items'] = None
        return
    for _c in (_CACHE,):
        _c['items'] = None
        _c['luma'] = None


class _TapProxy:
    """⭐ 包一层 `tap`：**自动**把面板 OCR 缓存作废（不必在 19 处手工加 `_invalidate()`）

    ⚠ 为什么要代理：`vault_flow` 一次流程点 8~19 次，每次点完画面都变，
      缓存必须立刻作废，否则会拿**点击前**的 items 继续判断
      （正是 2026-09-25 踩过的「宝库面板已开却判成没开」那一类）✗
    ⚠ 用代理而不是手工加，是为了**漏不掉**：漏一处就退化成读到旧画面 ⇒ 静默错判。
    """

    def __init__(self, bot):
        object.__setattr__(self, '_b', bot)

    def __getattr__(self, k):                             # 其余属性原样转发
        return getattr(object.__getattribute__(self, '_b'), k)

    def tap_dlg(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').tap_dlg(*a, **kw)

    def tap(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').tap(*a, **kw)

    def snap(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').snap(*a, **kw)


def _proxy(bot):
    """把 Bot 包成代理（同一实例只包一次，避免多层代理）"""
    if getattr(bot, '_bp_proxied', False):
        return bot
    try:
        bot._bp_proxied = True
    except Exception:                                       # noqa: BLE001
        pass
    return _TapProxy(bot)


def _items(bot, reuse=True):
    """面板 OCR 条目，**坐标已换算到居中弹窗系**（与下面所有常数同一口径）。

    ⚠ PC 版 `Bot.ocr()` 用的是**上一次截图**（缓存旧图），点完不重新截图会读到点击前的画面
      （2026-09-25 踩过：宝库面板已开却判成没开）⇒ PC 上必须先 `snap`。
      端侧 `Bot.ocr()` 走 `api.ocrJson` **自己抓当前帧**（`Bot.ocr_grabs = True`）⇒ 省掉那次
      snap（真机上一次 snap = toRef + PNG 编码 ≈ 0.3s，一个宝库面板要调它十几次）。

    ⛔ 不要再拆成多条窄带（2026-10-02 实测无效，见上方注释）。

    ⭐ `reuse=True`（默认）：**同帧复用** ——
      真机实测 OCR 0.65~0.70s/次且与带高无关 ⇒ 省时间的唯一办法是**少调**。
      判据：`board_luma` 与上次相同 ⇒ 画面没变 ⇒ 直接复用上次 items。
      ⚠ 每次 `tap` 都会让画面变 ⇒ 流程里点完必须 `_invalidate()`（下面各分支已接上）。
    """
    if getattr(bot, 'ocr_grabs', False):
        return dlg_items(bot.ocr(min_conf=0.35, band=BAND, tag='panel'))
    # ---- 同帧缓存：画面没变就别再 OCR ----
    _c = _cache_of(bot)
    if reuse and _c['items'] is not None:
        try:
            _now = bot.board_luma()
            if _now is not None and _c['luma'] is not None \
                    and abs(_now - _c['luma']) < 0.8:
                return _c['items']
        except Exception:                                   # noqa: BLE001
            pass
    bot.snap('bp')
    _it = dlg_items(bot.ocr(min_conf=0.35, band=BAND, tag='panel'))
    try:
        _c['luma'] = bot.board_luma()
        _c['items'] = _it
    except Exception:                                       # noqa: BLE001
        pass
    return _it


def _has(items, *labels):
    for lb in labels:
        for it in items:
            if lb in it['text']:
                return it
    return None


def _has_dlg(bot, *labels):
    """兜底的存在性判断：走**弹窗帧** OCR（坐标即弹窗系）。

    ⚠⚠ 2026-09-30 更正：这里原本写着「标题在归一化帧落到 y≈175，只是跑到 band 外」
      —— **不对**。归一化帧（`toRef`）会把弹窗系 y ∈ (202, 509) 这一段**整段丢掉**
      （见 `RefMapper.toRef` 的"两段拼接"），标题 383 落在丢带里 ⇒ 归一化帧**根本没有它**。
      所以任何 `_has(it, 标题)` 的判据在真机上是恒 False 的（v0.32 那次只修分支不修闸门
      才无效，见 09-29 日报）。

    ⭐ v0.61 起，正常路径**不再需要它**：面板存在性改用右下角按钮文字判（`_present`），
      因为按钮在弹窗系 1444（归一化帧 1235）**落在 band 内、看得见**，而且是免费的
      （`_items` 那一帧里就有）。只有「连按钮文字都认不出来」时才补这一手（≈2s）。
    PC 版 Bot 没有 ocr_dlg ⇒ 返回 None（PC 恒 C=0，也不需要）。"""
    ocr_dlg = getattr(bot, 'ocr_dlg', None)
    if ocr_dlg is None:
        return None
    try:
        items = ocr_dlg(min_conf=0.4)
    except Exception:       # noqa: BLE001
        return None
    for lb in labels:
        for it in items:
            if lb in (it.get('text') or '').replace(' ', ''):
                return it
    return None


def _present(bot, it):
    """面板还在不在？

    优先级（先便宜后贵）：
      ① 右下角那颗按钮的文字（购买/选择/离开/完成/领取/确定）—— 免费：就在 `it` 里，
         弹窗系 1444 ⇒ 归一化帧 1235，在 BAND 内 ⇒ 真机上也认得出来 ✓
      ② 标题（只有 C=0 的 PC/9:16 上才可能在帧里）
      ③ 兜底：整帧弹窗 OCR（≈2s，只在①②都没有时才付这个钱）
    """
    if _btn(it)[0]:
        return True
    if _has(it, VAULT['title']) or _has(it, '黄全宝库'):
        return True
    return bool(_has_dlg(bot, VAULT['title'], '黄全宝库'))


def _confirm(bot, log, tag=''):
    """处理可能的确认/奖励弹窗：只点「确定」，绝不点「取消」

    ⭐ 2026-10-02 尝试去 OCR 化，但**坐标没法离线标定** ——
       我手上**没有一张购买确认框的真机帧**（离线扫 40 帧，
       亮度筛选把地图界面也选进来了 ⇒ 全是误判）⇒ 写死坐标是**瞎猜** ✗
       ⇒ **保持原样**（OCR 找「确定」），等拿到真帧再改。
       ⚠ 绝不能为了提速把「只点确定」这条搞错 —— 点成「取消」会浪费道具/钱 ✗

    ⛔⛔ 2026-10-11 **修「`cy > 800` 过严 ⇒ 会漏掉一整类确认框」** ✗
      ---- 真机铁证（`_verify/` 136 帧全扫，`_tmpman/scan_confirm_y.py`）----
        · `finish_confirm_dialog_20261002.png` ⇒ 「确定」在 **(516, 742)**
          ⇒ **`cy > 800` 判不到** ⇒ 这一整类框**全被漏掉** ✗✗
          （那帧是「**提示 / 还有未拾取的战利品 / 是否结束冒险?**」+ 取消/确定 ✓）
        · 另一个真机帧 `pcrun_10.png` ⇒ 在 `(379, 876)` ⇒ `cy>800` 命中 ✓
      ⇒ **两类的 y 不同**（确认框位置随**文案行数**变 ⇒ 项目早有这条教训：
        `_find_text_btn` 的注释写着「结果框的「返回」随文案行数/奖励条目数变高变矮」✓）
      ---- 修法（**加一条判据，不删旧的** ✓）----
        旧：`text == '确定' and cy > 800`
        ⭐ 新增保底：`text == '确定'` **且同帧有「取消」** ⇒ **一定是确认框** ✓
           （购买/结束冒险框都是**成对**出现「取消/确定」；结果框只有「确定」或「返回」✓
             ⇒ 用「成对」当判据，**既能覆盖低位的框、又不会误点结果框** ✓）
        ⚠ **仍绝不点「取消」**（这条是硬要求，改成对之后也一个字没动 ✓）
    """
    for _i in range(2):
        it = _items(bot)
        ok = None
        # 旧判据：靠下的「确定」
        for t in it:
            if t['text'].strip() == '确定' and t['cy'] > 800:
                ok = t
                break
        # ⭐ 新判据（保底）：有「取消」作伴的「确定」⇒ 必是确认框（y 不设限 ✓）
        if not ok:
            _has_cancel = any(t['text'].strip() == '取消' for t in it)
            if _has_cancel:
                for t in it:
                    if t['text'].strip() == '确定':
                        ok = t
                        log.append({'buy_confirm_paired': tag,
                                    'at': (t['cx'], t['cy']),
                                    'note': '同帧有「取消」⇒ 确认框（旧 cy>800 会漏 ✗）'})
                        break
        if not ok:
            return False
        bot.tap_dlg(ok['cx'], ok['cy'], wait=2.0)
        log.append({'buy_confirm': tag, 'at': (ok['cx'], ok['cy'])})
        # ⚠⚠ 2026-10-11 **点一次就返回**（修"同一帧被点两下" ✗）
        #   原来 `for _ in range(2)` 是想"点不掉就再点一次"，但：
        #     · `_items()` 有**同帧缓存** ⇒ 第二轮读到的**还是点之前那一帧** ✗
        #       ⇒ 于是**同一坐标被点两下**（真机实测：taps=[(516,742),(516,742)] ✗）
        #     · 确认框是**单次**动作（点一下即消失）⇒ 第二下点在**空处** ✗
        #   而"点不掉"的兜底本来就由**调用方**的轮询负责
        #   （宝库 `_vault_click` 那条链会隔轮重试 ✓）⇒ 这里不需要自己重试 ✓
        if _i == 0:
            return True
    return True


def merchant_flow(bot, log):
    """旅行商人：购买 → 返回，重复 4 次 → 关 X（2026-09-25 实机验证过）

    ⭐⭐⭐ 2026-10-02 用户定调（原话，两次）：
        「**商人购买不刚需 OCR，固定的两个位置点就完事了**」
        「**商人购买完全不需要什么 OCR，都是固定位置点击和固定间隔**」
      ⇒ 整条流程**真·零 OCR**：
        · 三个固定坐标：购买 / 返回 / 关 X（`MERCHANT['buy'] / ['back'] / ['x']`）
        · 三个**定死间隔**：`buy_wait / reward_wait / back_wait`（显式 `time.sleep`）
        · 一个**图像**判据：面板还在不在（`_panel_gone()`，std<12，0.05s）
      ⛔ 2026-10-02 又删掉最后一处 OCR —— `_confirm(bot, log, ...)`：
        它是"OCR 找「确定」再点"，每轮要调 `_items()`（整屏/带 OCR ≈0.7~1.4s，
        还可能命中同帧缓存而**时快时慢**，正是"四轮间隔不一样"的第二个来源 ✗）。
        而真机日志里**从来没有**出现过 `{"buy_confirm": ...}` —— 说明商人这条路
        **根本没有购买确认框**（宝库那条才有，所以 `_confirm` 仍留给宝库用）⇒
        这一步纯属白花时间 + 给节奏加噪声 ⇒ 删掉，节奏完全由上面的定死间隔决定 ✓

    流程（每轮，**零 OCR**）：
        1. 点「购买」（固定坐标）→ 等 buy_wait
        2. 等 reward_wait（奖励页/刷新站稳 —— 原来这步是"处理确认框"，已删）
        3. 点「返回」（固定坐标）—— 商人面板是**同格循环**购买，返回后还在 → 等 back_wait
        4. 循环 4 次（4 轮节奏**完全一致**）
        5. 点 X 关掉
    """
    import cv2
    import numpy as np
    import layout as _lay

    def _panel_gone():
        """商人面板还在不在 —— 用**图像**（面板区纹理），不用 OCR ✓"""
        try:
            im = bot.img()
            if im is None:
                return False
            # 商人面板主体在屏幕中部；关掉后那里会变回棋盘
            y0, y1 = int(_lay.LAYOUT.sy(400)), int(_lay.LAYOUT.sy(700))
            x0, x1 = int(_lay.LAYOUT.sx(120)), int(_lay.LAYOUT.sx(600))
            reg = im[max(0, y0):y1, max(0, x0):x1]
            if reg.size == 0:
                return True
            return float(cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY).std()) < 12.0
        except Exception:                       # noqa: BLE001
            return False

    bought = 0
    for i in range(MERCHANT['times']):
        # ⭐⭐⭐ 2026-10-02 用户报「四次间隔不一样」⇒ **三个间隔全用显式 sleep 定死**：
        #   `tap(wait=)` 在极速截图下"一变就返回"（≈0.1~0.3s），定不住节奏 ✗
        #   ⇒ 每轮 = 点购买 →sleep(buy_wait) →sleep(reward_wait) →点返回 →sleep(back_wait)
        #     **4 轮一模一样、且全程不调 OCR** ✓
        bot.tap_dlg(*MERCHANT['buy'], wait=0.6)          # wait 只当"等它有反应"
        time.sleep(MERCHANT['buy_wait'])                 # ⭐ 定死（照第一次的节奏）
        time.sleep(MERCHANT['reward_wait'])              # ⭐ 定死（奖励页站稳；确认框那步已删）
        at = MERCHANT['back']
        bot.tap_dlg(at[0], at[1], wait=0.6)
        time.sleep(MERCHANT['back_wait'])                # ⭐ 定死
        bought += 1
        log.append({'merchant': 'bought', 'i': i, 'back': list(at),
                    'waits': [MERCHANT['buy_wait'], MERCHANT['reward_wait'],
                              MERCHANT['back_wait']],
                    'note': '固定坐标 + 定死间隔 + 零 OCR（4 轮一致）'})
        if _panel_gone():            # 面板已经不在了（钱不够/买完自动关）⇒ 收工
            log.append({'merchant': 'panel_gone_after', 'i': i, 'bought': bought})
            break
    bot.tap_dlg(*MERCHANT['x'], wait=2.0)
    log.append({'merchant': 'done', 'bought': bought, 'ocr': 0})
    return bought


# ⭐⭐⭐ 2026-10-01 用户口径定案（别再改回去）：
#   「**同挡位优先天赋果实，不是越大越好**」
#   · 档位**只由数量决定**（同一层里数量就是档位）：草 1/2/4/8、果 5/10/20/50 ✓
#   · **同档位 ⇒ 天赋果实优先**（草在低档时不会因为种类被抬高 ✗）
#   · 「幸运草」就是「四叶草」（用户 2026-10-01 明确：「幸运草应该就是四叶草，我一般这么叫」，
#     游戏 `GoldenVault` 表里也只有 `D00002_000,四叶草` 一项）⇒ **同一个物品的两个叫法**，
#     绝不能再当成两样东西排序 ✗（此前我写「幸运草 > 四叶草 > 果实」是错的，已作废）
#   · 与用户「优先幸运草和四叶草」的关系：那句是"**草/果优先于神石/装备/符文**"的意思 ✓
#     ⇒ 非草非果的档位取 (0, 0)，永远不会赢过草/果 ✓
VAULT_PRIORITY = ('四叶草', '天赋果实')

# 「具体奖励」图标模板（已随仓提供，见 templates/items/）
#   天赋果实 = Special_Item D00002_001 / 四叶草(幸运草) = D00002_000
ITEM_TPL_DIR = os.path.join(_MGAS_ROOT, 'templates', 'items')
ITEM_TPL = {'天赋果实': ['D00002_001.png'],
            '四叶草': ['D00002_000.png', 'D00002_000_2.png']}
ICON_FILL = 0.94          # 图标占格子间距的比例（实测 135/144 ✓）
_ICON_SRC = 30            # 图标源图 30px（该尺寸下与格子对齐 ✓）
# ⭐ 图标命中阈值（实测真命中 0.73~0.97，误命中 ≤0.35 ✓）
# ⚠⚠ 2026-10-01 **严重回归修复**：我把它误删了（改 `_icon_scales()` 时连 `ICON_SCALE`/`ICON_THR`
#   一起换掉，`ICON_THR` 却仍被 `vault_pick` 使用）⇒ 宝库一进购买流程就
#   `NameError: name 'ICON_THR' is not defined`（真机 18:35 铁证：`vault:buy` 点了「购买」
#   之后每一轮都崩 ⇒ **宝库买不成、卡在面板上、最后强制脱困退图** ✗）
#   ⇒ 教训：**删常量前必须全文件搜引用**（本轮回归套件没覆盖到"常量是否定义"这类错误 ✗，
#     已补一条守门：`ICON_THR` 必须既有定义又有使用 ✓）
ICON_THR = 0.55


def _icon_scales():
    """图标缩放候选 —— **由格子间距 pitch 推出来**（分辨率无关 ✓），并扫 ±25%

    ⚠⚠ 2026-10-01 用户报「第二圈有个幸运草，但没识别出来就没选」：
      原来写死 `ICON_SCALE = 4.5` 且只试 4.3 / 4.5 / 4.7（±4.4%）⇒ 真机上只要图标实际尺寸
      差出这个范围（面板缩放、图标内边距与 PC 不同…）就**整批落到阈值以下**
      ⇒ `vault_pick` 报 `no_icon_hit` ⇒ 退成「随意选」⇒ 幸运草被漏 ✗
      ⇒ 现在：基准 = `pitch × ICON_FILL / 30`，再从 -25% 扫到 +20%（9 档）✓
      （pitch 本身是弹窗系常数 ⇒ 换分辨率时它跟着面板走 ⇒ 这是"自适应"的关键 ✓）
    """
    base = VAULT['pitch'] * ICON_FILL / float(_ICON_SRC)
    return tuple(round(base * f, 3)
                 for f in (0.75, 0.80, 0.85, 0.90, 0.95, 1.0, 1.05, 1.12, 1.20))


_ICON_SCALES_WIDE = tuple(round(VAULT['pitch'] * ICON_FILL / float(_ICON_SRC) * f, 3)
                          for f in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6))

# 数量角标：相对格中心的 (dx, dy, w, h)
# ⭐⭐⭐⭐ 2026-10-05 **真机实测重标**（用户原话：「**我看他没选择天赋果实，即时阻止了**」）
#   那把（02:43:12~19，`runs/vaultdbg/09_r2_after_pick_024317.png`）第 2 圈的颜色法命中 4 格：
#        (263,593) 粉 **玫瑰卡**    pink 0.521  ← bot 选了它 ✗（其实**不是**天赋果实）
#        (455,689) 真天赋果实×10     pink 0.555  ← **该选的这个** ✗没选
#     两者 pink 只差 0.034 ⇒ 颜色法**分不开**；能分开的是「档位 = 数量角标」
#       （果 5/10/20/50、草 1/2/4/8；粉玫瑰卡**没有角标** ⇒ 该判 0 档 ✓）
#     但真机上 10 读成了 **0** ⇒ 两格同为 0 档 ⇒ 平档按扫描顺序 ⇒ 挑中玫瑰卡 ✗✗
#   ⇒ 逐像素量角标位置（相对格中心，真机帧）：**两位数 "10" 占 x +27..+45、一位数 "5" 占 +38..+45
#     （右对齐）、y 都占 +31..+45** —— 而旧窗口 `dx=32` **从 +32 才起裁** ⇒ 把 "10" 的
#     前导 "1" 切掉 ⇒ OCR 只看到 "0"、`int('0')=0` ⇒ 档位 0 ✗
#   ⇒ 新窗口 (16,16,56,44) 把整块角标含进余量后：
#        · "10" 读成 **10（conf 1.00）** ✓、"5" ✓、"1" ✓（3/3 已知角标全中）
#        · 9 张真机渲染帧 × 25 格 = **225 格扫描：相对旧窗零新增误报**，
#          并消掉一处旧窗误报（`vault_start` 空格上被读成 "1" 的浅色格纹）
#   ⚠ 手机端那份 `buypanels.py` 的 `QTY_OFF` **不动**：它跑的是 1080×1920 弹窗系（格距 144），
#     这里是 PC 的 720×1280 设备系（格距 96）—— 两端各自标定 ✓
QTY_OFF = (16, 16, 56, 44)

_TPL_CACHE = {}


def _load_item_tpl(wide=False):
    """{名称: [(灰度模板, 掩码, w, h) ...]}（多尺度 + 模板同名多文件）

    ⚠ 尺度由 `_icon_scales()` 给出（自适应 ✓）；`wide=True` 用更宽的一轮兜底 ✓
    """
    key = 'tpl_wide' if wide else 'tpl'
    if key in _TPL_CACHE:
        return _TPL_CACHE[key]
    import cv2
    import numpy as np
    out = {}
    _scales = _ICON_SCALES_WIDE if wide else _icon_scales()
    for name, files in ITEM_TPL.items():
        lst = []
        for fn in files:
            p = os.path.join(ITEM_TPL_DIR, fn)
            if not os.path.exists(p):
                continue
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None or img.ndim < 3:
                continue
            for s in _scales:
                w, h = int(round(img.shape[1] * s)), int(round(img.shape[0] * s))
                g = cv2.cvtColor(cv2.resize(img[:, :, :3], (w, h),
                                            interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2GRAY).astype(np.float32)
                m = cv2.resize(img[:, :, 3], (w, h),
                               interpolation=cv2.INTER_NEAREST) > 128
                if int(m.sum()) < 50:
                    continue
                v = g[m]
                v = v - v.mean()
                sd = v.std()
                if sd < 1e-6:
                    continue
                lst.append(((v / sd).astype(np.float32), m, w, h))
        if lst:
            out[name] = lst
    _TPL_CACHE[key] = out
    return out


def match_item_icon(img, cx, cy, wide=False, top=0):
    """该格是不是优先图标 -> (最好分数, 名称)（灰度掩码 NCC，对背景/亮度不敏感）

    ⭐ 2026-10-01：尺度自适应（见 `_icon_scales`）；搜索偏移 ±4 → **±7**
    （真机格子中心与理论值会有几像素偏差）；`top>0` 时返回**低于阈值的候选**
    供诊断（用户报「幸运草没识别出来」时要能看见分数 ✓）
    """
    import cv2
    import numpy as np
    tpls = _load_item_tpl(wide=wide)
    best, bestname = -1.0, None
    _rank = []
    for name, lst in tpls.items():
        _bn, _bs = None, -1.0
        for (tv, m, w, h) in lst:
            for dx in (-7, 0, 7):
                for dy in (-7, 0, 7):
                    x0 = int(cx - w / 2 + dx)
                    y0 = int(cy - h / 2 + dy)
                    sub = img[y0:y0 + h, x0:x0 + w]
                    if sub.shape[0] != h or sub.shape[1] != w:
                        continue
                    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                    pv = g[m]
                    pv = pv - pv.mean()
                    sd = pv.std()
                    if sd < 1e-6:
                        continue
                    sc = float((pv / sd * tv).mean())
                    if sc > _bs:
                        _bs, _bn = sc, name
                    if sc > best:
                        best, bestname = sc, name
        if _bn:
            _rank.append((round(_bs, 3), _bn))
    if top and _rank:
        return best, bestname, sorted(_rank, reverse=True)[:top]
    return best, bestname


def _qty_tmp_path():
    """数量角标临时 PNG 的路径 —— **必须先保证目录真的存在**。

    ⚠ 2026-09-29 安卓端踩坑（用户报「卡在黄金宝库购买界面」的真凶）：
      原来写死 `dirname(__file__)/runs`。端上这个根是**只读资源包** `files/mapbot_pack/`
      （只有 `templates/` 与数据表，**没有 `runs/`**）⇒ `cv2.imencode(...).tofile()` 抛
      `FileNotFoundError` ⇒ 黄金宝库每轮 `vault_pick` 都炸 ⇒ 3 轮后 `too_many_errors`
      ⇒ 收工离场，把游戏留在购买面板 ✗
    现在统一用 `mapbot.RUNS`（PC/安卓同一个口径，且安卓侧已 makedirs），再兜
    `MAPBOT_RUNS` 环境变量、模块旁的 runs、系统临时目录，每层都 makedirs。
    """
    cands = []
    try:
        from mapbot import RUNS as _R
        if _R:
            cands.append(_R)
    except Exception:
        pass
    if os.environ.get('MAPBOT_RUNS'):
        cands.append(os.environ['MAPBOT_RUNS'])
    cands.append(os.path.join(_MGAS_ROOT, 'runs'))
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, '_qty.png')
        except Exception:
            continue
    import tempfile
    return os.path.join(tempfile.gettempdir(), '_qty.png')


def read_qty(bot, cx, cy):
    """读图标右下角的数量角标（实测放大 8 倍 OCR 置信度 0.99~1.00）

    ⚠ v0.61：cx/cy 是**弹窗系**坐标 ⇒ 必须取弹窗帧（`bot.img_dlg()`）来裁这一小块，
      否则在真机上会从错 248px 的地方裁（读到的"数量"来自别的格子）。
    """
    import cv2
    import numpy as np
    from mapbot import _ocr
    img = bot.img_dlg()
    dx, dy, w, h = QTY_OFF
    x0, y0 = int(cx + dx), int(cy + dy)
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.size == 0:
        return None
    big = cv2.resize(sub, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
    tmp = _qty_tmp_path()
    cv2.imencode('.png', big)[1].tofile(tmp)
    res, _ = _ocr()(tmp)
    for it in (res or []):
        t = it[1].strip().replace('x', '').replace('X', '').replace('*', '')
        if t.isdigit() and 1 <= len(t) <= 4 and float(it[2]) >= 0.5:
            return int(t)
    return None



# 「四叶草(=口语"幸运草"，同一物品) / 天赋果实」在同一层里出现的**数量** ⇒ 档位
# （游戏 `GoldenVault` 表：草 1/2/4/8、果 5/10/20/50，按 Level 分档 ✓）
VAULT_TIER = {
    '四叶草': {1: 1, 2: 2, 4: 3, 8: 4},
    '天赋果实': {5: 1, 10: 2, 20: 3, 50: 4},
    '幸运草': {1: 1, 2: 2, 4: 3, 8: 4},     # 同一物品的口语别名（OCR/界面可能这么显示 ✓）
}


# 同档位的**平分决胜**（仅此才看种类）：**天赋果实优先**（用户 2026-10-01 口径 ✓）
PREF_FRUIT = 1
PREF_CLOVER = 0


def vault_tier_of(name, qty):
    """(名称, 数量) → (档位, 平分决胜)；排序键取最大 ⇒ **先比档位，同档天赋果实优先** ✓

    ⭐⭐⭐ 2026-10-01 用户口径（原话：「**同挡位优先天赋果实，不是越大越好**」）：
      ① **档位只由数量决定**（同一层里的数量就是档位）—— 8 草(档4) 与 50 果(档4) 同档，
         与 20 果(档3) 比时 **8 草胜**（档位高者胜 = 数量说话 ✓）
      ② **同档位 ⇒ 天赋果实优先**（`PREF_FRUIT=1` > `PREF_CLOVER=0` ✓）
         ⚠ 此前写过「同档草优先」和「数量越大越好」两种错法，都已作废 ✗
      ③ 非草非果（神石/装备/符文）⇒ (0, 0)：既进不了高档位，也赢不过草/果的同档 ✓
         （这就是用户「优先幸运草和四叶草」的实际含义：**草/果 优先于其它奖励** ✓）
    未知数量 ⇒ 近似：草按数量、果按 数量/6.25（= 8:50 的比值 ✓）
    ⚠⚠ 2026-10-01 修（离线执行测试发现的隐患）：近似公式**必须夹到已知档位区间内**，
      否则 `read_qty` 把「草」的数量误读成 50（或读成 999）时
      `t = 50` ⇒ 档位 **50.0** ⇒ **误判为远超最高的第 4 档** ⇒ 把垃圾选成最优 ✗
      （实测：打了 read_qty 桩返回 50 时，四叶草被算成 `档50.00`）
      现在：近似值夹进 [1, 4]（游戏只有 4 档 ✓），且**大于最高档数量**时判为"读错" ⇒ 降到 0 档
      比较保守 ⇒ 不会因为一个 OCR 误读就把别的真奖励挤掉 ✓
    """
    nm = name or ''
    q = int(qty or 0)
    _prio = PREF_FRUIT if '果' in nm else (
        PREF_CLOVER if ('幸运草' in nm or '四叶草' in nm) else 0)
    for key, tbl in VAULT_TIER.items():
        if key in nm:
            t = tbl.get(q)
            if t is None:                       # 表外数量 ⇒ 近似（**必须夹到 1~4 档** ✓）
                _qmax = max(tbl)                # 该物品的最高档数量（草 8 / 果 50）
                if q <= 0 or q > _qmax:
                    # 数量读错（> 最高档）或没读到 ⇒ **保守当 0 档**（不冒充当高档 ✓）
                    t = 0.0
                else:
                    t = (q / 6.25) if '果' in nm else float(q)
                    t = max(1.0, min(4.0, t))   # 夹进 4 档区间 ✓
            return (float(t), _prio)
    return (0.0, 0)          # 其它物品（神石/装备/符文）不进这个比较 ✓


# ⭐⭐⭐ 2026-10-10 **"读名时点过的格"**（治「重复点击 ⇒ 打开详情页」✗）
#   键 = ring（层号），值 = 该层探过的坐标集合
#   ⚠ **按层记**：不同层的格子各不相同 ⇒ 跨层记忆会误判 ✓
#   ⚠ 每次 `vault_flow` 开头清空（一局宝库一次 ✓）
_PROBED = {}


def _probe_name(bot, at, log=None, wait=1.5):
    """⭐ 2026-10-01 用户口径兜底：**点开这一格看它的名字**，再点空白处收起详情 ✓

    返回读到的名称串（读不到 → None）。全程弹窗系（宝库面板锚设备中心 ✓）。
    ⚠ 只用于「图标模板一个都没命中」的兜底路径 ⇒ 正常路径零额外开销、零额外点击 ✓

    ⛔⛔⛔ 2026-10-10 **必修：`log` 原来没在签名里**（用户报「**第二层乱点了好几次才正常买上**」）
      ---- 病 ----
        函数体里那行“收起详情”写的是
            `_vault_tap(bot, VAULT['blank'][0], VAULT['blank'][1], **log=log**, ...)`
        可**签名是 `(bot, at, wait=1.5)`** —— **没有 `log`** ✗
        实测（`_tmpman/chk_probe_log.py`）：
            `'log' in co_varnames` = **False**
            `'log' in co_freevars` = **False**
            `'log' in co_names`    = **True**（走全局查找）
            `hasattr(buypanels, 'log')` = **False** ⇒ **NameError** ✗
        而它被**下一行的 `except Exception: pass` 吞掉** ⇒ **一声不响** ✗✗
      ---- 后果（真机铁证 `runs/acc1/gui_20261010_191004_acc1.log` + loop_log #47~#56）----
        · `#48 no_icon_hit` ⇒ 走 `_probe_name` 兜底 ⇒ 点开详情读名
        · **详情页从来没被收起**（那一下 NameError 了）⇒ 一直盖在面板上 ✗
        · `#54 r2_after_pick: btn=**null**  texts=[【传承】剑客兜帽 …]` ⇒ 按钮读不到
        · `#55 will_tap_btn: ring=2 btn=null at=[596,978] src=**'stale_pos'**`
          ⇒ 拿**上一层残留的坐标**硬点 ⇒ **乱点** ✗✗
        · `#56 claim: pick=[456,592] name='随意'` ⇒ 兜底瞎选
      ---- 为什么"探到了就收手"没救回来 ----
        它确实在前 3 格里早停（`#50~#52` 三条 probe），但**每一格都没关详情** ⇒
        第二格是在**第一格的详情页上**点的 ⇒ 越点越乱 ✓
      ---- 修法 ----
        ① 签名补 `log=None`（并给默认值，兼容老调用 ✓）
        ② 调用点显式传 `log=log`（`vault_pick` 里那处 ✓）
        ③ ⚠ **`except Exception: pass` 保留**（收起详情失败不该拖垮宝库流程），
           但**成功/失败都落一条日志** ⇒ 下次能看见它到底跑没跑 ✓
            （本项目铁律：**不许静默失效** —— 这次的坑正是"被吞掉所以没人发现" ✓）
    """
    try:
        bot.tap_dlg(at[0], at[1], wait=wait)
    except Exception:       # noqa: BLE001
        return None
    # ⚠ 这里**不记** `_PROBED` —— 由调用方 `vault_pick` 记（它知道 ring ✓）
    #   （用函数属性传 ring 太脆 ⇒ 让知道 ring 的那一层去记 ✓）
    it = _items(bot)                       # 详情面板：文字集中在面板左/上，名称最显眼
    nm = ''
    for t in sorted(it, key=lambda z: (z['cy'], z['cx'])):
        s = (t['text'] or '').strip()
        if not s or len(s) > 12:
            continue
        # 跳过 UI 词与纯数字（价格/数量）
        if s in ('购买', '选择奖励', '离开', '完成', '领取', '确定', '确认', '返回',
                 '取消', '关闭', '宝库', '黄金宝库'):
            continue
        # ⛔⛔ 2026-10-10 **修「把面板提示文字当物品名」**（真机铁证，用户报第二层乱点）：
        #   详情页实测 OCR（loop_log #410）：
        #       … 取一件哦。@(340,351) ｜ **洁白神石**@(359,419) ｜ 更容易出现数值相关的效果@(353,578)
        #        ↑ 面板提示（cy 更小）        ↑ **真物品名**              ↑ 效果描述
        #   而老代码的 `if not nm and any(中文)` ⇒ **第一个中文串就被锁定** ✗
        #   ⇒ 读到的是「取一件哦。」（面板自己的提示）⇒ 3 格全白探 ⇒ 落 `随意` 兜底 ✗✗
        #   ⇒ 修法：**按标点排除"句子"** —— 物品名是**词组**（洁白神石/天赋果实/幸运草），
        #     句子才带 `。，、！？：` 或"每层/宝库/效果"这类说明词 ✓
        if any(ch in s for ch in '。，、！？；：'):
            continue
        if any(k in s for k in ('不管你看到', '花费金币', '并在每层', '更容易',
                                '取一件', '解锁宝库', '数值相关')):
            continue
        if s.replace(',', '').replace('+', '').isdigit():
            continue
        if any(k in s for k in ('幸运草', '四叶草', '天赋果实', '果实')):
            nm = s                        # 玩家要的三样：直接定案 ✓
            break
        if not nm and any('\u4e00' <= ch <= '\u9fff' for ch in s):
            nm = s                        # 其它中文名（神石/装备/符文…）也留着做兜底 ✓
    # ⭐ 收起详情（这一步以前因 `log` 未定义**从没执行过** ✗ ⇒ 现在能跑了 ✓）
    try:
        _vault_tap(bot, VAULT['blank'][0], VAULT['blank'][1], log=log,
                   what='probe_blank', wait=1.1)     # 收起详情（实测有效 ✓）
        if log is not None:
            log.append({'vault': 'probe_blank_ok',
                        'at': list(VAULT['blank']), 'name': nm or None,
                        'note': '读完名⇒点空白收起详情 ✓'})
    except Exception as _eb:    # noqa: BLE001
        # ⚠ 不静默！（本项目铁律）收起失败 ⇒ 详情页会盖住按钮 ⇒ 后面会乱点
        if log is not None:
            log.append({'vault': 'probe_blank_fail', 'e': repr(_eb)[:90],
                        'at': list(VAULT['blank']),
                        'note': '**收起详情失败** ⇒ 详情页可能还盖着 ⇒ 下一步会读不到按钮 ✗'})
    return nm or None


def _vstep(bot, log, tag, it=None):
    """⭐ 宝库流程**每一步**落一张帧 + 记下这一帧读到的按钮/状态（2026-10-04 新增）

    为什么加（用户原话：「**好像点选择奖励直接就关了宝库页面**」）：
      手上**一张"出错那一步"的真帧都没有** ⇒ 只能对着坐标猜 ✗✗
      （本次已经猜过一轮：把「返回」连点收敛了，但用户说"还是没好、像坐标有问题"）
      ⇒ 按本项目一贯做法：**不猜根因，先拿证据** ——
        每步落 `runs/vaultdbg/NN_tag_HHMMSS.png`，并在日志里同时记下：
          · 这一步 `_btn()` 读到的**按钮文字 + 坐标**（读不到就是 None）
          · 面板在不在 / 奖励展示在不在
          · 面板上认到的**全部文字**（带坐标，方便和帧逐条对）
      ⇒ 下次复现就能回答："点之前是什么状态 → 点了哪个坐标 → 点完变成什么" ✓

    ⚠ 开销只在**开宝库时**（一次流程 ~8~10 张帧 ≈ 2MB）⇒ 平时零成本 ✓
    ⚠ `it` 传进来就复用（省一次 OCR）；不传就自己读一帧

    ⭐⭐⭐⭐ 2026-10-05 **默认彻底不落盘**（用户原话：
       「宝库购买流程已经没问题了，**不用取证了吧**」／「就是很慢，一轮还有很多图片」）
      取证是为抓「点选择奖励直接就关了宝库页面」那个 bug 而加的 —— **那个早就修好并进门禁了**
      （`verify_vault_flow.py` / `verify_vault_pick.py` 守着 ✓），流程本身也已经连买三层
      （真机 `acts: ["buy1","claim1","buy2","claim2","buy3","claim3_fb"]` ✓）
      ⇒ 现在：
        · **默认：一张都不落**，只记结构化日志（`vault_step`，排查时看日志就够 ✓）
        · `MAPBOT_VAULT_DEBUG=1` ⇒ 恢复全量落帧（**只在真的要排查时**开 ✓）
      ⛔ 上一次我改的"按需落帧"是**失效的**：`it=None`（我不再为取证单独 OCR）被
        `_odd` 判据当成"异常"⇒ **反而每步都落**（用户贴的日志里 01~14 全落了 ✗）
        —— 这次不再有"按需"那套含糊逻辑，就是**默认关** ✓
    """
    try:
        _VSTEP[0] += 1
        lab, cost, pos = (None, None, None)
        if it is not None:
            lab, cost, pos = _btn(it)
        _pres = bool(_present(bot, it)) if it is not None else None
        _rew = bool(_reward_showing(it)) if it is not None else None
        _want_dump = bool(VAULT_DEBUG)
        name = '%02d_%s_%s' % (_VSTEP[0], str(tag).replace('/', '_'),
                               time.strftime('%H%M%S'))
        if _want_dump:
            _vault_dump(name, bot.img())
        try:
            log.append({'vault_step': tag, 'n': _VSTEP[0],
                        'file': (name + '.png') if _want_dump else None,
                        'btn': lab, 'cost': cost,
                        'at': list(pos) if pos else None,
                        'present': _pres, 'reward': _rew,
                        'texts': ['%s@(%d,%d)' % ((t.get('text') or '')[:12],
                                                  t.get('cx', -1), t.get('cy', -1))
                                  for t in it][:18]} if it is not None else
                        {'vault_step': tag, 'n': _VSTEP[0], 'file': None,
                         'note': '未读按钮/面板（不为取证单独 OCR ✓）'})
        except Exception:                   # noqa: BLE001
            pass
        # ⭐ 控制台**默认一声不吭**（原来每步一行 = 一把刷 18 行噪声 ✗）；
        #   只在调试模式下才逐行报 ✓
        if VAULT_DEBUG or (it is not None and (not _pres or not lab)):
            say('      · [宝库%s %02d] %s：按钮=%s%s 面板=%s 奖励展示=%s%s'
                % ('取证' if VAULT_DEBUG else '异常', _VSTEP[0], tag,
                   lab or '（读不到）',
                   ('@%s' % (list(pos),)) if pos else '',
                   _pres, _rew,
                   (' ' + name + '.png') if _want_dump else ''))
        return name if _want_dump else None
    except Exception:                       # noqa: BLE001
        return None


_VSTEP = [0]
# 取证策略开关（见 `_vstep` docstring）
VAULT_DEBUG = bool(os.environ.get('MAPBOT_VAULT_DEBUG'))


def _vault_dump(name, img):
    """把宝库面板帧落盘（**认不出图标时**才调，零成本不拖正常路径 ✓）

    安卓真机：优先落 `/sdcard/Download/autoexplore/bagdbg/`（release 包不可 run-as，
    私有 `runs/` 拿不出来 ✗）；PC：落 `RUNS/vaultdbg/` ✓

    ⚠⚠ 2026-10-05 修：`/sdcard/...` 这条候选在 **Windows 上会被当成相对路径**
      （`os.makedirs('/sdcard/...')` ⇒ 在**当前盘根**建出 `D:\\sdcard\\...`）
      ⇒ **"成功"写入、于是第二个候选 `RUNS/vaultdbg/` 永远轮不到** ✗
      实证：本机所有宝库取证帧都躺在 `D:\\sdcard\\Download\\autoexplore\\bagdbg\\`，
      连 `runs/vaultdbg/` 都是空目录 ⇒ 查问题时**根本想不到去那儿找** ✗
      ⇒ 现在：**只在非 Windows 上**才用 `/sdcard/...` 这条候选 ✓
    """
    try:
        import cv2
        cands = []
        if os.name != 'nt':                  # ⭐ 只有安卓/Linux 才认 `/sdcard`
            cands.append('/sdcard/Download/autoexplore/bagdbg')
        try:
            from mapbot import RUNS as _R
            if _R:
                cands.append(os.path.join(_R, 'vaultdbg'))
        except Exception:
            pass
        for d in cands:
            try:
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, str(name) + '.png')
                cv2.imencode('.png', img)[1].tofile(p)
                return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def _vault_lattice(x, y, tol=0.62):
    """(x, y) → 宝库 5×5 的 (行, 列)（**0 基**）；**不在点阵上** ⇒ None

    ⚠ 用途：挡掉"长得像格子但不是格子"的东西 —— 真机实测右下角「选择奖励/购买」按钮
      (895,1521) 同样是高饱和彩色块，会被 `_tile_mask` 检成奖励格 ✗
      按钮的行号 = (1521−746)/144 = **5.38**（点阵只有 0~4）⇒ None ⇒ 剔掉 ✓
    ⚠ 容差 0.62 个格距：真机上网格整体比常数低 ~50px（= 0.35 格），仍能对上 ✓
    """
    p = float(VAULT['pitch'] or 144)
    fc = (x - VAULT['gx0']) / p
    fr = (y - VAULT['gy0']) / p
    c, r = int(round(fc)), int(round(fr))
    if not (0 <= c <= 4 and 0 <= r <= 4):
        return None
    if abs(fc - c) > tol or abs(fr - r) > tol:
        return None
    return r, c


def _vault_rc(x, y):
    """检测到的奖励格 → 宝库 5×5 里的 (行, 列)（**0 基**）

    ⚠ 用"最近的理论格"判：真机上网格常比常数 `gy0` 低 ~50px（面板高度随文案变），
      但 `50 < 半格距(72)` ⇒ 最近邻判行列**免疫整体位移** ✓（实测 800→行0 / 942→行1 /
      1085→行2 / 1231→行3 / 1378→行4，逐个对得上 ✓）
    """
    p = float(VAULT['pitch'] or 144)
    c = int(round((x - VAULT['gx0']) / p))
    r = int(round((y - VAULT['gy0']) / p))
    return max(0, min(4, r)), max(0, min(4, c))


def tile_ring(x, y):
    """该格属于第几圈：**1 外圈 / 2 中圈 / 3 核心**（切比雪夫距中心 ✓，与 `vault_ring` 同口径）"""
    r, c = _vault_rc(x, y)
    d = max(abs(r - 2), abs(c - 2))
    return {0: 3, 1: 2, 2: 1}.get(d, 1)


def vault_pick(bot, log, level, max_probe=25):
    """在某一层里挑一件奖励（**用户口径：不点开详情，直接认图标**）

    1. 只扫该层那一圈格子（d=2 → 16 格 / d=1 → 8 格 / d=0 → 1 格）
    2. 图标模板匹配 → 认「天赋果实 / 四叶草(幸运草)」
    3. 命中的格子再 OCR 右下角数量角标 → **取数量最多的那件**
    4. 一个都没命中就随便取该圈第一格兜底
    ⭐ 用户口径（2026-09-25）：**第一轮只能选最外一圈、第二轮中间一圈、第三轮只有中间一格**
       ⇒ 第三轮不用扫，直接点中心
    """
    cells = vault_ring(level)[:max_probe]
    it = _items(bot)
    if not _present(bot, it):
        return (cells[0] if cells else VAULT['buy']), '?'
    img = bot.img_dlg()                     # ⚠ 弹窗系坐标 ⇒ 必须用弹窗帧
    # ⭐⭐⭐ 2026-10-01 v0.98【第一步：用**颜色检测**拿到"这一圈真实存在的奖励格"】
    #   真机实测（vault_no_hit_L2.png）：面板高度随提示文案变 ⇒ 网格比常数 `gy0=746` **低 ~51px**
    #   ⇒ 旧代码在格子上方 51px 处裁窗口 ⇒ 全盘 NCC 0.12~0.31 ⇒ 认不出草/果 ⇒ 逐格点开读名（乱点）✗
    #   彩色底（蓝/紫）= 有奖励的格（空格/已领格是棕色）⇒ 检测它的中心既修了裁图、也修了点击位置 ✓
    _rad = {}
    try:
        _tiles = vault_tiles(img)
    except Exception:       # noqa: BLE001
        _tiles = []
    if _tiles:
        log.append({'vault': 'tiles_detected', 'n': len(_tiles),
                    'at': [[x, y, w, h] for (x, y, w, h) in _tiles[:20]],
                    'const_first': [VAULT['gx0'], VAULT['gy0']]})
        cells = [(x, y) for (x, y, _w, _h) in _tiles]
        for (x, y, w, h) in _tiles:
            _rad[(x, y)] = int(min(w, h) * 0.36)
        # ⭐⭐⭐ 2026-10-01 v1.09 修**真机 bug**（用户报「**宝库又选不了奖励了**」）：
        #   v0.98 把 `cells` 直接换成"检测到的**全部**彩色格" ⇒ **圈层约束丢了** ✗
        #   真机铁证（logcat）：ring 1/2/3 三次 `pick` **全是同一个格 (540,1089)**（= 正中心），
        #   而游戏只允许选**当前那一圈**（源码 `RefreshDefaultSelectingIndex` 按 currentLevel
        #   定 `selectingIndex`；非本圈的选择 `OnFuncButtonClicked` 直接 return）
        #   ⇒ 点正中心在 1/2 圈 = 空操作 ⇒ 用户看到的就是**选不了奖励** ✗✗
        #   ⇒ 现在按检测格自己的 5×5 行列算圈层，**只留本圈**；本圈一个都没检出才退回理论圈 ✓
        _ring_cells = [p for p in cells if tile_ring(p[0], p[1]) == level]
        if _ring_cells:
            log.append({'vault': 'ring_filter', 'level': level, 'all': len(cells),
                        'ring': len(_ring_cells)})
            cells = _ring_cells
            # ⭐⭐⭐⭐⭐ 2026-10-14 **补齐本圈"没被检测到"的格**（用户报「**宝库第二层
            #   没选到 4 个四叶草那个奖励**」）
            #   ---- 真机铁证（`runs/acc1/loop/loop_log.json` #198~#211）----
            #     `#198 tiles_detected n=7`（第 2 层）
            #     `#199 ring_filter all=7 **ring=6**` ⇐ **本圈应有 8 格，少了 2 格** ✗
            #     缺的正是 `(263,689)` 与 `(359,785)`（=`vault_ring(2)` 里那两格）
            #     ⇒ 那两格**永远进不了候选** ⇒ 就算其中一格是「4 四叶草」（`tier 3.0`，
            #       高于当时唯一候选「天赋果实 qty=null ⇒ tier 0.0」）**也轮不到它** ✗✗
            #     实测该层最终 `#211 claim 天赋果实×0` —— 用户看到的"没选到 4 四叶草" ✓
            #   ---- 根因 ----
            #     `vault_tiles` 靠**彩色底**检测（蓝/紫/绿/红高饱和块）。
            #     可有些奖励格的底色**不够饱和**（贴图/压缩/该格美术偏淡）⇒ 检测漏格 ✗
            #     ⚠ 这是**召回**问题，不是"点错格" ⇒ 补格是安全的 ✓
            #   ---- 修法（**只补不删**，向"本圈理论格"取并集 ✓）----
            #     本圈理论格 `vault_ring(level)` 里，凡**没有被任何检出格覆盖**的
            #     （按行列判，容差半格 ⇒ 免疫面板整体位移 ✓）
            #     ⇒ 补进来当**额外候选**（用理论坐标；它本来就是标定过的格心 ✓）
            #     ⚠ **不删任何检出格**（检出的坐标更准，优先保留 ✓）
            #     ⚠ 只对 `level in (1, 2)` 补（第 3 层就 1 格，`center_only` 已处理 ✓）
            #     ⚠ 上限：最多补到 `max_probe`（与 `no_icon_hit` 的探测预算一致 ✓）
            if level in (1, 2):
                _have = set()
                for _p in cells:
                    _have.add(_vault_rc(_p[0], _p[1]))
                _add = []
                for _t in vault_ring(level):
                    if _vault_rc(_t[0], _t[1]) not in _have:
                        _add.append(_t)
                if _add:
                    # ⚠ 再防一手"坐标几乎重合"（行列判已足够，但重合的两个都留着没意义 ✗）
                    _real = [t for t in _add
                             if not any(abs(t[0] - p[0]) <= 48 and abs(t[1] - p[1]) <= 48
                                        for p in cells)]
                    if _real:
                        log.append({'vault': 'ring_fill', 'level': level,
                                    'was': len(cells), 'add': len(_real),
                                    'at': _real[:8],
                                    'note': '彩色底检测漏格 ⇒ 按本圈理论格补齐候选'
                                            '（治「第二层没选到 4 四叶草」✗）'})
                        cells = cells + _real
        else:
            log.append({'vault': 'ring_filter_fallback', 'level': level, 'all': len(cells)})
            cells = vault_ring(level)[:max_probe]
    if len(cells) == 1:                     # 第三轮：只有核心一格，无需扫描
        log.append({'vault': 'center_only', 'at': cells[0]})
        return cells[0], '核心'
    # ⭐⭐⭐ 2026-10-01 v0.98【第二步：**按颜色认种类**（尺度无关、真机区分度 0.35+ vs 0.005）】
    #   「天赋果实」= 洋红粉（R>150 且 B>0.55R）｜「四叶草/幸运草」= 绿（G 明显最大）
    #   ⇒ 认出就直接按档位选一件（用户口径：**识别到天赋果实和幸运草就直接选这俩其中一个** ✓）
    #   ⇒ 不再走"点开格子读名"那条会被用户看成乱点的路 ✓
    #
    # ⭐⭐⭐⭐ 2026-10-05 真机修 —— **"有天赋果实却没选它"的真根因：在"图标还没画出来"的帧上做识别**
    #   实证（**同一轮** 5 张取证帧，面板区绿像素数）：
    #     01_r1_start **0** ｜ 02_r1_after_buy **0** ｜ **03_r1_before_pick 0**（← bot 就在这帧判的）
    #     ｜ 04_r1_after_pick **17040** ⇒ **图标是点完之后才画出来的**
    #   那一帧实测：`(167,497)` 整块是**纯亮黄方块**（最多色占 **4624/4624 = 100%**、绿像素 0）
    #     ⇒ 颜色法必然全灭（`color_none`）
    #     ⇒ 掉进**模板兜底**，而模板在**纯色方块**上会**乱给分**（实测 0.552 判成「四叶草」）
    #     ⇒ **挑了一格错的** ✗✗ —— 用户原话「遇到天赋果实没有选择天赋果实作为奖励」
    #   ⇒ 修法：颜色法全灭时**先重新取帧、多等几轮**（图标可能只是还没渲染完）——
    #     ⛔ **不盲点任何格子**：一开始我在这里加过"点一下本圈第一格把图标翻出来"，
    #        但**那条因果没被证明**（03→04 之间既隔了 4 秒、又隔了 bot 那一下点击，
    #        两者分不开）⇒ 按本项目的规矩「**不猜、只做有证据的事**」，
    #        这里只**等待 + 重新取帧**，绝不额外点游戏 ✓
    #   ⇒ 直到 `VAULT_SETTLE_SECS` 超时仍认不出，才走模板兜底 ✓
    #
    # ⭐⭐⭐⭐ 2026-10-05 **第二把真机（03:41）**：上面那道"没命中就等"的闸门**自己被骗了** ——
    #   用户原话：「**刚刚那个黄金宝库第一层幸运草和天赋果实全都要，结果都没选**」
    #   真机取证（`runs/vaultdbg/03_r1_before_pick_034138.png` = 买完那一刻）：
    #     那一帧图标**还没画**，格子里只有**背景底色块**（青/洋红/小蓝点/小绿点），
    #     而颜色法在 `(455,497)` 上量到 **green=0.254**（阈值 0.25 ⇒ **只高 0.004**）
    #     ⇒ `_color_hits` 非空 ⇒ **重试闸门一次都没触发** ⇒ 立刻按这个假命中挑格 ✗✗
    #     同一圈画完之后（`04_r1_after_pick_034139.png`）真有 **6 个**命中，含
    #       `(167,689) 四叶草 green=0.564 角标1`、`(551,785) 天赋果实 pink=0.564 角标5`
    #     = 用户说的"幸运草和天赋果实都有"，两个**都没被看上** ✗
    #   ⇒ 两条修法（都有实测支撑）：
    #     ① `SPRITE_GREEN_THR` 0.25 → **0.30**（真草实测 0.356/0.366/0.564，
    #        底色块最高只到 0.254 ⇒ 两条边各留 ~0.05 余量 ✓）
    #     ② 闸门判据从"有没有命中"升级为"**有没有带数量角标的命中**"——
    #        真草/果右下角**必有数量角标**（草 1/2/4/8、果 5/10/20/50），
    #        而底色块 / 粉卡 / 绿卷轴**一个白字都没有**（实测：有角标 27~93 个近白像素，
    #        无角标 **12 个反例全是 0** ⇒ 阈值取 12 极稳 ✓，见 `badge_ink`）
    #        ⇒ 只认出"没角标的命中"时**继续等**，直到超时（那时若仍只有没角标的命中，
    #          按原逻辑挑，行为不回归 ✓）
    try:
        _t_settle = time.time()
        _settle_n = 0
        _color_hits = []
        while True:
            _color_hits = []
            for _p in cells:
                # ⭐⭐⭐ 2026-10-10 **多半径取最好**（治"采样窗口尺寸恰好落在坏点上"✗）
                #   ---- 真机铁证（`runs/vaultdbg/vault_no_hit_L2.png`，用户报
                #        「**第二层乱点了好几次才正常买上**」那把）----
                #     同一格、同一帧，`pink` 随采样半径**剧烈波动**：
                #         (458,689) pink@rad = 24:**0.435** 26:0.357 28:0.285
                #                               **30:0.231** 32:0.368 34:**0.362**
                #         (456,785) pink@rad = 24:**0.396** 26:0.326 28:0.261
                #                               **30:0.213** 32:0.356 34:**0.350**
                #     而生产原来只用 **一个** `rad = min(w,h)*0.36 ≈ 30`
                #     ⇒ 恰好在 **0.213/0.231**（阈值 0.35）⇒ **两个真天赋果实全认不出** ✗✗
                #     ⇒ 掉进 `_probe_name` 兜底（点开详情读名）⇒ 才有了"乱点" ✓
                #   ---- 为什么是 30 这个坏点 ----
                #     rad 大一点(32~34)就把**图标本体**包进来 ⇒ 粉占比回到 0.35+ ✓
                #     rad=30 时窗口边缘切在图标上 ⇒ 底色像素混进来把占比稀释了 ✓
                #   ---- 修法 ----
                #     对每格试 **3 个半径**（生产值 ±17%），取 pink/green 更大的那个
                #     ⚠ 代价：`sprite_colors` 是纯 numpy 局部运算（无 OCR/IO）⇒
                #       实测一帧 6 格 ×3 次仍在毫秒级 ✓（真机分账里可忽略）
                #     ⚠ **不改阈值**（0.35 是当年真机标定的 —— 改阈值会引入误命中 ✗）
                #       只把"采样窗口"这个**偶然因素**去掉 ✓
                _r0 = _rad.get(_p, int(VAULT['pitch'] * 0.36))
                _best = (None, None)
                for _rr in (max(6, int(_r0 * 0.83)), int(_r0), int(_r0 * 1.17)):
                    _kk, _fr = sprite_kind(img, _p[0], _p[1], _rr)
                    if _kk:
                        _best = (_kk, _fr)
                        break                       # 命中即止（最常见 ✓）
                    if _best[1] is None or \
                            max(_fr['pink'], _fr['green']) > \
                            max(_best[1]['pink'], _best[1]['green']):
                        _best = (None, _fr)         # 记下"最接近的那个"（供日志诊断 ✓）
                _kk, _fr = _best
                if _kk:
                    _color_hits.append((_p[0], _p[1], _kk,
                                        round(_fr['pink'], 3), round(_fr['green'], 3)))
            # ⭐ 只有"带数量角标"的命中才算**真奖励**（底色块/粉卡/绿卷轴都没有角标）
            _badged = [h for h in _color_hits if has_badge(img, h[0], h[1])]
            if _badged:
                break
            _waited = time.time() - _t_settle
            if _waited >= VAULT_SETTLE_SECS:
                break
            _settle_n += 1
            log.append({'vault': 'color_retry', 'n': _settle_n, 'waited': round(_waited, 1),
                        'cells': len(cells), 'hits': len(_color_hits),
                        'badged': 0,
                        'note': '认到的命中**都没有数量角标**（多半只画了底色）'
                                ' ⇒ 重新取帧再扫（图标可能还没渲染完）'})
            # ⭐ **必须重新取帧**（`img` 是传进来的旧帧，光 sleep 不会变）
            try:
                bot.snap('vault_settle')
                img = bot.img_dlg()
            except Exception:               # noqa: BLE001
                pass
            time.sleep(VAULT_SETTLE_GAP)
        if _color_hits:
            log.append({'vault': 'color_hit', 'n': len(_color_hits),
                        'hits': _color_hits,            # [x, y, 名称, pink, green]
                        'badged': [[h[0], h[1]] for h in
                                   [z for z in _color_hits
                                    if has_badge(img, z[0], z[1])]]})
            _cr = []
            for (x, y, _kk, _pk, _gr) in _color_hits:
                _ink = badge_ink(img, x, y)
                _q = read_qty(bot, x, y)
                _t = vault_tier_of(_kk, _q)
                _cr.append((_t, _q, _kk, (x, y)))
                log.append({'vault': 'color_tier', 'name': _kk, 'qty': _q, 'at': (x, y),
                            'tier': round(_t[0], 2), 'pref': _t[1],
                            'ink': _ink, 'pink': _pk, 'green': _gr})
            _cr.sort(key=lambda z: z[0], reverse=True)
            _t0, _q0, _k0, _at0 = _cr[0]
            log.append({'vault': 'pick_color', 'name': _k0, 'qty': _q0, 'at': _at0,
                        'tier': round(_t0[0], 2), 'retries': _settle_n,
                        'why': '颜色判种（尺度无关）＋先比档位(数量)、同档天赋果实优先 ✓'})
            return _at0, '%s×%d(色判)' % (_k0, _q0 or 0)
        log.append({'vault': 'color_none', 'cells': len(cells), 'retries': _settle_n})
    except Exception as _ec:        # noqa: BLE001
        log.append({'vault': 'color_error', 'e': repr(_ec)[:80]})
    cands = []
    _near = []
    for (x, y) in cells:
        _r = match_item_icon(img, x, y, top=2)
        sc, name = _r[0], _r[1]
        if len(_r) > 2 and _r[2]:
            _near.append({'at': (x, y), 'top': _r[2]})
        if name and sc >= ICON_THR:
            qty = read_qty(bot, x, y)
            cands.append((qty if qty else 0, round(sc, 3), name, (x, y)))
    # ⭐ 2026-10-01 诊断（用户报「幸运草没识别出来」）：把**每一格的最好分数**都记下来 ——
    #   低于阈值时也能看出"是差一点（0.4~0.55）"还是"根本没对上（<0.2）"，从而区分
    #   「尺寸不对」与「模板/图不对」✓（logcat 里 `vault_debug` 一行即可判 ✓）
    log.append({'vault_debug': 'cells', 'level': level, 'n': len(cells),
                'thr': ICON_THR, 'scales': list(_icon_scales()),
                'near': _near[:8]})
    if not cands:                           # ⭐ 兜底：宽尺度再扫一轮（尺寸差很多时救回来 ✓）
        for (x, y) in cells:
            sc2, name2 = match_item_icon(img, x, y, wide=True)
            if name2 and sc2 >= ICON_THR:
                qty2 = read_qty(bot, x, y)
                cands.append((qty2 if qty2 else 0, round(sc2, 3), name2, (x, y)))
        if cands:
            log.append({'vault': 'icon_hit_wide', 'n': len(cands)})
    # ⭐ 2026-09-27：按**档位**比；⭐ 2026-10-01 用户口径：同档 **幸运草 > 四叶草 > 天赋果实**
    for c in cands:
        c_t = vault_tier_of(c[2], c[0])
        log.append({'vault': 'icon_hit', 'name': c[2], 'qty': c[0], 'score': c[1],
                    'tier': round(c_t[0], 2), 'pref': c_t[1], 'at': c[3]})
    if cands:
        cands.sort(key=lambda c: vault_tier_of(c[2], c[0]), reverse=True)
        q, sc, name, at = cands[0]
        _t = vault_tier_of(name, q)
        log.append({'vault': 'pick_best', 'name': name, 'qty': q, 'at': at,
                    'tier': round(_t[0], 2), 'pref': _t[1],
                    'why': '先比档位(数量)；同档 天赋果实优先 ✓'})
        return at, '%s×%d(档%.2f)' % (name, q, _t[0])
    # ⭐⭐⭐ 2026-10-01 用户口径：「宝库要给它一个兜底：**如果识别不到，就点击进去看是什么**，
    #   如果有幸运草或者四叶草或者天赋果实就选，没有就选择默认或者其它的」
    #   ⇒ 图标全不中时不"随便点第一格"，而是**逐格点开详情 → OCR 读名称** ⇒ 认得就选 ✓
    # ⭐⭐⭐ 2026-10-01 用户报「点一下左上角的奖励格子，关闭宝库界面」⇒ 兜底路径重做：
    #   旧写法**逐格点开详情**（16 格 × (点击+2 次 OCR+收起详情) ≈ **40 秒**），
    #   而「收起详情」点的 `blank` 在真机上落在**面板外**（旧值 (540,1700)）
    #   ⇒ 每格都在棋盘上点一下 = 用户看到的**乱点/关掉面板** ✗✗
    #   新口径（省时 + 不乱点）：
    #     ① 只对**分数最接近阈值的前 3 格**点开详情（不再 16 格全点）✓
    #     ② 收起详情点**面板内安全空白**（VAULT['blank'] 已按真机帧修正 ✓）
    #     ③ 全部读不到名字 ⇒ 才回落"取第一格"（保持旧兜底语义 ✓）
    log.append({'vault': 'no_icon_hit', 'cells': len(cells)})
    try:
        _p = _vault_dump('vault_no_hit_L%d' % level, img)
        if _p:
            log.append({'vault': 'dump', 'path': _p})
    except Exception:       # noqa: BLE001
        pass
    # 候选 = 先算每格的分数，再按分数降序取**前 3 格**去点开详情（分数高的更可能是草/果 ✓）
    # ⚠ 2026-10-01 修：我第一版写成
    #     `sorted(((_r[0], _at) for _r, _at in [(match_item_icon(...)[0], (x,y)) ...]))`
    #   那是**先解包成 (分数, 坐标)、又当成 (分数, 坐标) 再解包一次** ✗
    #   ⇒ `TypeError: 'float' object is not subscriptable`（真机每轮崩、卡在"正在开箱" ✗）
    #   现在写成两步、变量名自解释，杜绝这类解包错误 ✓
    _scored = []
    for (_x, _y) in cells:
        _sc1 = match_item_icon(img, _x, _y)[0]        # 只要分数（名字此处不用 ✓）
        _scored.append((float(_sc1 or 0), (_x, _y)))
    _scored.sort(key=lambda z: z[0], reverse=True)
    _ranked = _scored[:3]                             # ⭐ 只探前 3 格（旧写法 16 格 ≈40 秒 ✗）
    _want = []
    for _i, (_sc3, _at) in enumerate(_ranked):        # _sc3 = float 分数，_at = (x,y) ✓
        nm = _probe_name(bot, _at, log=log)
        # ⭐ 2026-10-10 **记下"这一格被点开过"**（按层记 ✓）
        #   ⇒ `vault_flow` 据此**跳过重复点击**（否则会打开详情页盖住按钮 ✗）
        try:
            _PROBED.setdefault(level, set()).add((int(_at[0]), int(_at[1])))
        except Exception:       # noqa: BLE001
            pass
        log.append({'vault': 'probe', 'i': _i, 'at': _at,
                    'score': round(float(_sc3), 3), 'name': nm})
        if not nm:
            continue
        for _k, _prio in (('幸运草', 3), ('四叶草', 2), ('天赋果实', 1), ('果实', 1)):
            if _k in nm:
                _want.append((_prio, _at, _k, nm))
                break
        # ⭐ v0.97 用户报「购买第一层后**点击了好几个奖励**才选择奖励」⇒ 已经探到想要的就收手：
        #   分数最高的那格先探（最可能是草/果），探到了就**不再点开其它格**（少几下乱点 ✓）
        if _want:
            log.append({'vault': 'probe_early_stop', 'i': _i, 'of': len(_ranked)})
            break
    if _want:
        _want.sort(reverse=True)
        _prio, _at, _k, nm = _want[0]
        log.append({'vault': 'probe_pick', 'name': nm, 'kind': _k, 'prio': _prio,
                    'at': _at, 'why': '图标没中 ⇒ 点开前 3 格读名，草/果优先 ✓'})
        return _at, '%s(读名✓)' % nm
    log.append({'vault': 'probe_none'})
    return (cells[0] if cells else VAULT['buy']), '随意'



def vault_ring(k):
    """第 k 层（1 外层 16 / 2 内层 8 / 3 核心 1）的格子坐标列表

    5x5 里按到中心的切比雪夫距离分层：d=2 → 16 格，d=1 → 8 格，d=0 → 1 格
    """
    gx, gy, p = VAULT['gx0'], VAULT['gy0'], VAULT['pitch']
    d = {1: 2, 2: 1, 3: 0}[max(1, min(3, k))]
    out = []
    for r in range(5):
        for c in range(5):
            if max(abs(r - 2), abs(c - 2)) == d:
                out.append((gx + c * p, gy + r * p))
    return out


def _tile_mask(img):
    """「有奖励的格子」掩码 = **高饱和的彩色格子底**（蓝/紫/绿/红都算），排除棕色空格底

    ⚠ v0.98 定标（真机两帧）：只用"蓝底"（`b-g>25`）会**漏掉绿/红/黄底**的奖励格
      ⇒ 用「饱和度 + 非棕」更全；空格/已领格是棕色底（`r>b+30 & g>b+10`）⇒ 被排除 ✓
    """
    import numpy as np
    b = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    r = img[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    sat = mx - mn
    brown = (r > b + 30) & (g > b + 10) & (sat < 95)
    return ((sat > 60) & (mx > 120) & (~brown)).astype('uint8')


# ⭐⭐⭐⭐ 2026-10-06 **把 `vault_tiles` 的常数改成"跟着帧宽走"**（修「宝库买不到第二层」）
#
#   ⛔ 真机事故（用户报「为什么黄金宝库又不能正常买了？？」＋「买到第二层就把宝库关了，
#      可能点到宝库外面了」）：取证帧 `runs/vaultdbg/vault_no_hit_L2.png` 是第 2 层"没点中"
#      那一刻 —— 宝库面板**完整开着**、按钮「选择奖励」、第 2 层 8 格全是彩色底，可
#      `vault_tiles()` 返回 **0 个格** ⇒ `vault_pick` 回落到写死的理论网格 ⇒ 乱点 ⇒ 点关面板 ✗
#
#   ⛔ 根因：下面 `min_side=100 / max_side=185 / min_area=4000 / y>700 / x<960`
#      是**按 1080×1920 标的**，而 PC 端是 **720×1280**。
#      · 拿 **110 张真机宝库帧**量格子实际边长：
#          1080×1920 的 3 张老帧（`runs/vault_open.png` 等）格子 = **126** ⇒ 过 100 档 ✓
#          720×1280 的 **107 张**（含全部 `vaultdbg/` 与 `_verify/`）格子 = **84** ⇒ **全被拒** ✗
#        **126 / 84 = 1.5 = 1080 / 720** ⇒ 常数是 1080p 值，铁证 ✓
#      · 更深一层：**1080p 那 3 张是旧基准时代的遗留取证**，本项目现在锁 720×1280
#        （`AGENTS.md` §1b）⇒ 常数**必须跟分辨率走**，不能再写死 ✗
#
#   ⇒ 修法：常数按**帧宽的 1080 基准等比缩放**（与 `marks.glyph_scales()` 同一套思路 ✓）
#      · `_VAULT_TILE_REF = (min_area, min_side, max_side)` 是 **1080 基准值**
#      · 缩放系数 `k = img.shape[1] / 1080`
#      · ⚠ **1080p 上逐值不变**（k=1.0 ⇒ min_side 仍 100）⇒ 老帧行为**一字不改** ✓
#      · 720p ⇒ k=0.6667 ⇒ min_side **66.7**、max_side **123.3**、min_area **1778**
#        实测 720p 格子 84×84 / area 5300~6900 ⇒ **稳稳过闸**（两边都留余量）✓
#      ⚠ 为什么不干脆把 100 改成 76：那只是把"1080 的数"换成"720 的数"，
#        下次换分辨率**照旧全灭**（本项目已经因为"常数不跟分辨率走"翻过很多次 ✗）
_VAULT_TILE_REF = (4000, 100, 185)      # (min_area, min_side, max_side) @ 1080 宽


# ⭐⭐⭐⭐⭐ 2026-10-06 **宝库点击的"面板安全区"守卫**（用户口径：「把黄金宝库的点击范围固定下」）
#
#   ── 为什么需要（真机事故，用户原话：「刚刚又买一半关掉黄金宝库界面了」）──
#     `VAULT['blank']` 旧值 (440,1060) **落在面板外 12px**（面板底边实测 y=1048）✗
#     而它的用途是「点空白收起详情面板」（`_probe_name` 结尾 / 探格后收回）
#     ⇒ 那一下点到了**面板外的道具栏/棋盘** ⇒ **把宝库面板整个弄掉**
#       = 用户看到的「买一半关掉」✓
#
#   ── 本守卫解决的是**更深一层**的问题 ──────────────────────────
#     ⛔ 常量写错时**代码不会报任何错**：点在面板内、面板外**走的是同一条 `tap_dlg`**
#     ⇒ 这是**静默失效**（本项目反复栽的那一类）✗
#     ⇒ 不靠"把常量改对"（下次改别处又可能错），而是**加一道结构性保证**：
#       凡走宝库面板的点击，都先经这里**夹进安全矩形** ⇒ **物理上点不出去** ✓
#
#   ⚠ 只在**坐标越界时**才夹（`clamp`）并记日志 —— 正常坐标**一字不改** ✓
#     （所以它不会改变任何已验证过的正确行为；只兜住错的 ✓）
def _vault_tap(bot, x, y, log=None, what='', wait=1.8):
    """宝库面板内的点击：**先把坐标夹进面板安全区**，再点 ✓

    返回 `(真实点击的 x, y)`；`log` 非空时，越界会记一条 `vault: tap_clamped` ✓

    ⚠ 为什么要夹而不是"拒绝点击"：拒绝会让整个流程卡住（那格永远点不到 ⇒ 死循环 ✗）；
      夹进安全区至少是"点了面板内某个无害位置"，流程能继续 ✓
    """
    try:
        _sx0, _sx1, _sy0, _sy1 = VAULT['safe']
        try:
            xi, yi = int(round(float(x))), int(round(float(y)))
        except Exception:       # noqa: BLE001
            xi, yi = VAULT['blank'][0], VAULT['blank'][1]
        cx = min(max(xi, _sx0), _sx1)
        cy = min(max(yi, _sy0), _sy1)
        if (cx, cy) != (xi, yi) and log is not None:
            try:
                log.append({'vault': 'tap_clamped', 'what': what,
                            'asked': (xi, yi), 'used': (cx, cy),
                            'safe': [_sx0, _sx1, _sy0, _sy1],
                            'note': '坐标落在宝库面板**安全区之外** ⇒ 已夹回面板内'
                                    '（否则会点到面板外、把宝库关掉 ✗）'})
            except Exception:   # noqa: BLE001
                pass
        bot.tap_dlg(cx, cy, wait=wait)
        return (cx, cy)
    except Exception:           # noqa: BLE001
        try:
            bot.tap_dlg(x, y, wait=wait)
        except Exception:       # noqa: BLE001
            pass
        return (x, y)


def vault_tile_thr(img):
    """`vault_tiles` 的三个尺寸阈值，按**当前帧宽**从 1080 基准等比缩放 ✓

    ⚠ `img` 取不到宽度 ⇒ 退回 1080 基准（= 老行为，绝不比原来更松 ✗）
    """
    try:
        _w = int(img.shape[1])
    except Exception:                       # noqa: BLE001
        _w = 1080
    k = (_w / 1080.0) if _w > 0 else 1.0
    _ma, _mn, _mx = _VAULT_TILE_REF
    return int(round(_ma * k * k)), int(round(_mn * k)), int(round(_mx * k))


def vault_tiles(img, min_area=None, min_side=None, max_side=None):
    """当前这圈**可选的奖励格**（彩色底）中心/尺寸 —— **检测出来的，不是写死的网格常数**

    ⚠⚠ 2026-10-01 v0.98 真机根因（用户报「宝库选择奖励界面纯在乱点」）：
      面板高度随提示文案/按钮文案变（真机实测这屏提示是两行）⇒ 网格整体比
      `VAULT['gy0']=746` **低 ~51px**（实测行中心 942 / 1085 / 1231，常数 890 / 1034 / 1178）
      ⇒ 旧代码在格子**上方 51px** 的地方裁 135px 窗口去认图标 ⇒ 全盘 NCC 掉到 **0.12~0.31**
        （真机 log 实测）⇒ `no_icon_hit` ⇒ 退成"逐格点开读名" ⇒ **东点一下西点一下** ✗
      而"有奖励的格子"一定有**彩色底**（空格/已领格是棕色底）⇒ 直接检测它们，
      既拿到**真实格心**（顺便修了点击位置）又拿到"这一圈有哪些格" ✓
    ⚠ 彩色掩码会把**同一个格子切成两块**（精灵本身也高饱和）⇒ 按中心距离 60px 去重、留大块 ✓

    ⭐ 2026-10-06：三个尺寸阈值改为**按帧宽等比缩放**（见 `_VAULT_TILE_REF` 的长注释）——
      原来写死的 100/185/4000 是 1080p 值，在 720p 上**格子 84 全被拒** ⇒ 返回空 ✗
    """
    import cv2
    # ⭐ 阈值跟分辨率走（调用方显式传了就尊重调用方 ✓）
    _da, _dn, _dx = vault_tile_thr(img)
    min_area = _da if min_area is None else min_area
    min_side = _dn if min_side is None else min_side
    max_side = _dx if max_side is None else max_side
    # ⚠ 下面的 `y > 700 / x < 960` 也是 1080p 的"面板中下部、左侧"框 ⇒ 同样按 k 缩放
    #   （720p ⇒ y > 467 / x < 640；实测 720p 格心 y=497~881、x=167~551 ⇒ 全都落在框内 ✓）
    try:
        _k = int(img.shape[1]) / 1080.0
    except Exception:                       # noqa: BLE001
        _k = 1.0
    _y_lo = 700 * _k
    _x_hi = 960 * _k
    try:
        m = _tile_mask(img)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
        n, _lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    except Exception:       # noqa: BLE001
        return []
    raw = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        # ⚠⭐ 2026-10-06：这四道阈值**全部**改成跟帧宽缩放后的值（`_y_lo` / `_x_hi` 见上）
        #   原来写死 `y > 700 and x < 960` 是 1080p 的框，720p 上第 1/2 层格心 y=593/689
        #   **全在框外** ⇒ 连"尺寸合格"的格也一起被切掉 ✗
        #
        # ⛔⛔⛔ 2026-10-09 **修「第一层永远选不上天赋果实」的真根因**（用户报的，
        #   现场帧 `runs/vaultdbg/vault_no_hit_L1.png`）：
        #   `stats[i]` 的 `y` 是**包围盒左上角**，而这道闸门原来的注释
        #   （"720p ⇒ 实测格心 y=497~881 全都落在框内 ✓"）是**拿格心去比的** ✗
        #   ⇒ 两者**差半个格高（42px）**：
        #       第 1 行格心 y=497 ⇒ bbox_y = 455
        #       闸门 `y > 700×(720/1080)` = **466.7**
        #       ⇒ `455 > 466.7` **不成立** ⇒ **整行被滤掉** ✗✗
        #   后果（**全 87 张取证帧实测**：没有一张检出 lattice 第 0 行）：
        #       第 1 行 = **主奖励位**，第 1 层**所有奖励图标都在那行**
        #       （实测 row0 有 2 个「天赋果实」pink=0.52；row1~row4 **全 0.00**）
        #       ⇒ 检出的 16 格**全是木纹背景** ⇒ 颜色法/模板法**必然全灭** ✗
        #       ⇒ 用户看到「**刚刚那个宝库好像没选上天赋果实**」✓
        #   ⇒ 修法：**参照点改用格心** `cent[i][1]`（= 这条闸门自己注释的口径 ✓）
        #     ⚠ **网格坐标一个都没动**（`gx0/gy0/pitch` 不变）——
        #       用户原话：「**可是截图的格子都是对的啊，为什么要调成位置？**」✓
        #     ⚠ 防「选择奖励」按钮的**真正那道**是下面的 `_vault_lattice()`（精确按 5×5
        #       点阵剔，按钮行号 5.41 ∉ 0~4 ⇒ 稳 ✓）⇒ 本条只是让它别误伤第 1 行 ✓
        if a > min_area and min_side <= w <= max_side and min_side <= h <= max_side \
                and cent[i][1] > _y_lo and x < _x_hi:   # 弹窗帧：网格在面板中下部、左侧 ✓
            # ⭐⭐⭐ 2026-10-01 v1.09 修**按钮被当成奖励格**（真机 logcat 实证）：
            #   右下角那颗「选择奖励/购买」按钮 (895,1521) 同样是**高饱和彩色块**
            #   ⇒ 被 `_tile_mask` 检出、尺寸也刚好落在 100~185 里 ⇒ 混进 cells ✗
            #   后果：`vault_pick` 可能返回**按钮自己的坐标**（真机 ring1 的 pick 就是
            #   (895,1525)）⇒ 点它 = 点按钮、但当时**一个格子都没选** ⇒ 选不了奖励 ✗✗
            #   ⇒ 用**宝库 5×5 点阵**过滤：按钮的行号是 5.41（点阵只有 0~4）⇒ 剔掉 ✓
            if _vault_lattice(int(round(cent[i][0])), int(round(cent[i][1]))) is None:
                continue
            raw.append((int(round(cent[i][0])), int(round(cent[i][1])), int(w), int(h), int(a)))
    raw.sort(key=lambda z: -z[4])                 # 大块优先 ⇒ 去重时留它 ✓
    out = []
    for (x, y, w, h, _a) in raw:
        if any(abs(x - q[0]) < 60 and abs(y - q[1]) < 60 for q in out):
            continue
        out.append((x, y, w, h))
    out.sort(key=lambda z: (z[1], z[0]))          # 从上到下、从左到右 ✓
    return out


def sprite_colors(img, cx, cy, r):
    """格子里的**精灵**（去掉格子底色）颜色占比 -> {'pink':粉/洋红, 'green':绿, 'n':精灵像素数}

    ⭐ 真机实测（vault_no_hit_L2.png）区分度很好：
        粉果实×10   pink **0.574**   （洋红：R>150 且 B>0.55R 且 R-G>40）
        绿四叶草    green **0.356**  （绿：G-R>25 且 G-B>25 且 G>110）
        红宝石      pink  **0.005** ← 用"洋红"而不是"红"，把红宝石/装备排除掉了 ✓
        白水晶/紫水晶 pink ≤0.05 / green 0 ✓
    """
    import numpy as np
    r = int(r)
    sub = img[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
    if sub.size < 400:
        return {'pink': 0.0, 'green': 0.0, 'n': 0}
    px = sub.reshape(-1, 3).astype(int)
    q = px // 8
    key = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    vals, cnt = np.unique(key, return_counts=True)
    bg = vals[cnt.argmax()]
    bgc = np.array([(bg // 10000) * 8, ((bg // 100) % 100) * 8, (bg % 100) * 8])
    sp = px[np.abs(px - bgc).sum(axis=1) > 90]          # 去掉格子底色 ⇒ 剩下的就是精灵
    if len(sp) < 80:
        return {'pink': 0.0, 'green': 0.0, 'n': int(len(sp))}
    B, G, R = sp[:, 0], sp[:, 1], sp[:, 2]
    pink = float(((R > 150) & (B > 0.55 * R) & ((R - G) > 40)).mean())
    green = float((((G - R) > 25) & ((G - B) > 25) & (G > 110)).mean())
    return {'pink': pink, 'green': green, 'n': int(len(sp))}


# ⭐ 阈值（真机两帧实测标定，2026-10-01 v0.98）：
#   真「粉果实×10」pink **0.571** ｜ 真「绿四叶草」green **0.356**
#   误命中：红宝石/棕装备/水晶 pink **0.16~0.18**、green **0.00**
#   ⇒ pink 取 0.35（把红宝石那批 0.16~0.18 干净排除 ✓）、green 取 0.25（真值 0.356，余量足 ✓）
SPRITE_PINK_THR = 0.35
# ⭐⭐ 2026-10-05：绿阈值 0.25 → **0.30**（真机实证，见 `vault_pick` 里那段 03:41 的注释）
#   买完那一刻的帧上只有**背景底色块**，其中 `(455,497)` 的小绿点量到 **green=0.254**
#   —— 只比旧阈值 0.25 高 **0.004** ⇒ 假命中 ⇒ 骗过了"没命中就等"的闸门 ⇒ 挑错格 ✗
#   真草实测 **0.356 / 0.366 / 0.564** ⇒ 0.30 两边各留 ~0.05 余量 ✓
SPRITE_GREEN_THR = 0.30

# ⭐⭐⭐⭐ 2026-10-05 新增：**数量角标 = "这一格是真奖励"的判据**（`vault_pick` 的等待闸门用）
#   真草/果右下角**必有数量角标**（草 1/2/4/8、果 5/10/20/50），
#   而**只画了底色**的格 / 粉卡 / 绿卷轴**一个白字都没有**。
#   真机实测（17 个格，两种窗口都量过）：
#     有角标：clover1 **27** ｜ fruit5 **46** ｜ fruit10 **93** ｜ live-clover1 **43** ｜ fruit5(0341) **46**
#     无角标：**12 个反例全是 0**（玫瑰卡/绿卷轴×3/粉卡×4/空格/未渲染假命中 …）
#   ⇒ 阈值 12：离最小真值 27 差 15，离最大假值 0 差 12 ⇒ 极稳 ✓
#   窗口取 `(14,28,32,20)`：实测角标笔画在格中心 x **+27..+45**、y **+31..+45**（右对齐），
#   这个窗口把整块含进来，且**不碰格子白边框（±48）**、不伸到邻格 ✓
BADGE_BOX = (14, 28, 32, 20)      # 相对格中心 (dx, dy, w, h)
BADGE_INK_MIN = 12                # 近白笔画像素数下限


def badge_ink(img, cx, cy):
    """该格右下角**数量角标的白字笔画**像素数（0 = 这一格没有角标 ⇒ 不是真草/果）

    判据：近白（max>185）**且低饱和**（max-min<45）—— 角标是白字描黑边，
    而底色块/粉卡/绿卷轴那块区域要么是纯色、要么是棕格纹，都过不了这两条 ✓
    ⚠ 纯 numpy 切片，**没有 OCR**（~0.1ms）⇒ 放在等待循环里零成本 ✓
    """
    import numpy as np
    dx, dy, w, h = BADGE_BOX
    x0, y0 = int(cx + dx), int(cy + dy)
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.size == 0:
        return 0
    sub = sub.astype(int)
    b, g, r = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    return int(((mx > 185) & ((mx - mn) < 45)).sum())


def has_badge(img, cx, cy):
    """这一格是否有数量角标（= 是**真奖励**，不是只画了底色）✓"""
    return badge_ink(img, cx, cy) >= BADGE_INK_MIN

# ⭐⭐⭐⭐ 2026-10-05 真机新增：**等"图标渲染完"的窗口**（`vault_pick` 颜色法全灭时用）
#   实证（**同一轮** 5 张取证帧，面板区绿像素数）：
#     01_r1_start **0** ｜ 02_r1_after_buy **0** ｜ **03_r1_before_pick 0**（← bot 就在这帧判的）
#     ｜ 04_r1_after_pick **17040** ⇒ 图标是**过几秒才渲染出来的**
#   那一帧上颜色法必灭 ⇒ 掉进模板兜底 ⇒ 模板在"没有图标"的画面上**乱给分**
#     （实测 0.552 判成「四叶草」）⇒ **挑错格** = 用户报的「遇到天赋果实没有选择天赋果实」✗
#   ⇒ 现在：颜色法全灭时**先多等几轮、每轮重新取帧**，超时仍认不出才走模板兜底 ✓
#   ⇒ 用户口径（2026-10-05，原话）：「**选择奖励前的两次点击，第一次改成等待 1s**」
#      · **第 1 下**（原本是"点一下本圈第一格翻牌"）⇒ **不点了，改成等待 1s** ✓（见下）
#      · **第 2 下**（`vault_flow` 里"点挑中的那一格"）⇒ **保留不动** ✓
#        （⚠ 我中途误把第 2 下也改了，被用户当场指出「让你删一个点击，怎么两个都删了」⇒ 已恢复）
#   ⚠ 为什么不是"等 1s 就完"：真机实证图标**约 4 秒后才渲染出来**
#     （03 帧绿像素 0 → 04 帧 17040，隔 4 秒）⇒ 所以要**循环等**（每轮 1s、最多 4s）✓
# ⭐⭐⭐⭐⭐ 2026-10-09 用户口径（原话）：「**在之前的基础上加2s就够**」✓
#   依据（真机取证帧文件名自带的秒级时间戳，`runs/vaultdbg/*.png`）：
#       `02_r1_after_buy_151339`（点完购买那一刻）row0 图标 **0** 个
#       `03_r1_before_pick_151341`（2 秒后）       row0 图标 **2** 个 ✓
#       `01_r1_start_151333`（刚开面板）           row0 图标 **0** 个
#   ⇒ 从"点完购买"到"图标画出来"实测 **~2 秒** ⇒ 原来只等 4 秒**不够稳**（余量太小）
#     ⇒ **4.0 → 6.0**（+2s ✓）
#   ⚠ 用户同时明确：**不要动网格坐标**（`gx0/gy0/pitch` 一个没变）——
#     原话「**可是截图的格子都是对的啊，为什么要调成位置？**」✓
#     他也指出根本方向：「**这玩意调成一个固定等待时间不就行了，需要这么麻烦？**」✓
#     ⇒ 所以不动"每轮重取帧+判角标"那套逻辑，**只把这个时长加上去** ✓
VAULT_SETTLE_SECS = 6.0        # 一共等多久（超时才退化到模板兜底）
VAULT_SETTLE_GAP = 1.0         # 每轮等待（用户口径：1s）


def sprite_kind(img, cx, cy, r):
    """该格按**颜色**判是什么 -> ('天赋果实'/'四叶草', 占比) 或 (None, 占比)

    ⚠ 阈值必须按真机实测标定：只用"红"会把**红宝石/棕装备**（pink 0.16~0.18）也算成
      「天赋果实」✗ —— 所以判据是**洋红**（粉果实：R>150 且 B>0.55R）而不是"红"，
      阈值再定在 0.35（真值 0.571）⇒ 两帧真机数据零误命中 ✓
    """
    fr = sprite_colors(img, cx, cy, r)
    if fr['pink'] >= SPRITE_PINK_THR and fr['pink'] >= fr['green']:
        return '天赋果实', fr
    if fr['green'] >= SPRITE_GREEN_THR:
        return '四叶草', fr
    return None, fr


def _btn(it):
    """读面板右下角那颗按钮 ——**位置每次都可能不一样**，所以必须每轮 OCR 定位。

    ⭐⭐⭐ 2026-10-01 真机帧实测（用户停在宝库面板抓帧）：
        `购买` @dlg(**895, 1498**) ｜ 价格 `10000` @dlg(914, **1541**)
      而旧 y 带写死 `1400 ~ 1530` ⇒ 按钮文字落在 1498 时**勉强命中**、价格 1541 **在带外**；
      面板布局随文案变化（「选择奖励/离开/完成/领取」行数不同）就会整体掉出带外
      ⇒ `label=None` ⇒ `vault_flow` 走 `no_select_btn` ⇒ **跳过整层**（不买不选）✗
      ⇒ 用户报「第一层还没选择奖励就乱点了 / 选了默认没选天赋果实」的机制之一 ✓
      修法：y 带放宽到 **1360 ~ 1660**（覆盖实测 1498/1541 及三种文案的浮动 ✓）×
            x 带放宽到 **700 ~ 1040** ✓

    ⛔⛔⛔ 2026-10-02 修「无法正常购买黄金宝库」（用户实测）：
      上面那两个带子是 **1080×1920 系的标定值**（注释里写着
      「购买 @dlg(895,1498)｜价格 @dlg(914,1541)」，`dlg` 是 1080p 弹窗系），
      **从没换算过**。换到 720×1280 基准后，实测「购买 10000」在设备系 **(600, 963)**：
          cx=600 <  700 ⇒ 被 x 带剔掉
          cy=963 < 1360 ⇒ 被 y 带剔掉
      ⇒ `_btn` 恒返回 `label=None` ⇒ `vault_flow` 走 `no_select_btn`
      ⇒ **整层跳过，不买不选**（用户原话：「无法正常购买黄金宝库」）✗✗
      ⇒ 换成**实测的 720 设备系带子**（见下方常量）✓

    -> (label, cost, (cx,cy))；label ∈ 购买/选择奖励/离开/完成/领取
    """
    label, cost, pos = None, None, None
    KEYS = ('购买', '选择', '离开', '完成', '领取', '确定')
    # ⚠ 换算基准的坑：`layout.REF_W` 现在**已经是 720**（换基准时改过），
    #   所以**不能拿它当 1080 参照**去折算（会算出 K=1.0，带子根本没缩 ✗）
    #   —— 也不能 import `explore_loop.LAYOUT`（那是运行时按会话建的，模块级没有）
    #   ⇒ 直接用**实测的 720 设备系带子**，并注明它对应 1080 的哪一段 ✓
    _x0, _x1 = 500, 693          # 720p：覆盖实测(600,963) 的 x；对应 1080p 的 (750,1040)
    _y0, _y1 = 900, 1110         # 720p：覆盖实测(600,963) 的 y；对应 1080p 的 (1350,1665)
    for t in it:
        if not (_y0 < t['cy'] < _y1 and _x0 < t['cx'] < _x1):
            continue
        s = t['text'].strip()
        if any(k in s for k in KEYS):
            label = s
            pos = (t['cx'], t['cy'])
        elif s.replace(',', '').replace('+', '').isdigit() and len(s) >= 4:
            cost = int(s.replace(',', '').replace('+', ''))
            if pos is None:
                pos = (t['cx'], t['cy'])
    return label, cost, pos


def _back_btn(it):
    """中间那颗「返回」——按**文本 + 专用位置窗口**认，别用「不含离开」这种条件：
    领完奖励时「恭喜获得」+「返回」和右下角「离开」会同时出现，
    用 `not _has(it,'离开')` 会把「返回」漏掉（用户 2026-09-25 报「选择奖励后没有点返回」）

    ⚠⚠ 2026-10-01 v0.97 修真机根因（用户本轮报「**选择后不点返回就直接点购买**」）：
      位置判据原先锚在 `VAULT['back']` 上 —— 而 v0.88 把 `VAULT['back']` 从 (539,1212)
      改成了**面板内安全空白 (660,1590)**（那是给"兜底点一下收起详情"用的坐标）
      ⇒ 判据窗口跟着漂到 x 530~790 / y 1500~1680，而真机「返回」实测在 **dlg(538,1267)**
      ⇒ `_back_btn` **恒返回 None** ⇒ `vault_flow` 既收不掉奖励展示、又照样去点「购买」✗
      ⇒ 现在：`VAULT_BACK_ZONE` 专用窗口（±170/±120，覆盖 1212~1267 与布局浮动）
        + 一条"面板中下部任意「返回」"的文字兜底 ✓
    """
    for t in it:
        if '返回' not in (t.get('text') or ''):
            continue
        if abs(t['cx'] - VAULT_BACK_ZONE[0]) < 170 \
                and abs(t['cy'] - VAULT_BACK_ZONE[1]) < 120:
            return t
        # ⚠⚠ 2026-10-02：原带子 (900,1520)×(330,760) 是 **1080p 裸坐标**，没换算 ——
        #   720p 下会漏掉下半屏的「返回」⇒ `_back_btn` 认不到 ⇒ 收不掉奖励展示 ✗
        #   ⇒ 换成 720 设备系（1080 (900,1520)×(330,760) × 0.6667 = (600,1013)×(220,507)）
        #   ⚠ 宽度要留够：奖励展示的「返回」实测 x≈360（原 1080p 540 ⇒ 720p 360），
        #   落在 (220,510) 内 ✓；y 上界给到 1015 以覆盖 1080p 的 1267×0.667=845 ✓
        if 600 < t['cy'] < 1080 and 220 < t['cx'] < 510:
            return t                          # 文字兜底（面板挪动/文案行数变了也认得出 ✓）
    return None

def _reward_showing(it):
    """现在是不是**奖励展示态**（模态：「恭喜获得 …」/ 屏幕上还有「返回」）

    ⭐ v0.97：奖励展示是**模态**的 —— 此时点「购买」只会白点（真机被连点 4 次 ✗）。
      所以整个宝库流程里有一条硬规矩：**看到「返回/恭喜获得」就先把它们收掉，
      收不干净就本轮收工（下一轮再来），绝不去点购买** ✓
    """
    if _has(it, '恭喜获得'):
        return True
    return bool(_back_btn(it))



def _dismiss(bot, log, tries=3):
    """收起奖励展示（中间「返回」）/ 确认弹窗（只点确定）

    ⭐ v0.97：返回值 = **还看得见「返回」/「恭喜获得」吗**（True = 没收拾干净）
      —— 调用方必须用它挡住下一圈的「购买」：奖励展示是模态的，
      此时点购买只有两个下场：白点，或者**把面板点乱**（真机连点 4 次 ✗）。
    """
    for _ in range(tries):
        it = _items(bot)
        bk = _back_btn(it)
        if bk:
            bot.tap_dlg(bk['cx'], bk['cy'], wait=2.2)
            log.append({'vault': 'back', 'at': (bk['cx'], bk['cy'])})
            continue
        ok = None
        for t in it:
            if t['text'].strip() in ('确定', '确认') and t['cy'] > 700:
                ok = t
                break
        if ok:
            bot.tap_dlg(ok['cx'], ok['cy'], wait=2.2)
            log.append({'vault': 'confirm', 'at': (ok['cx'], ok['cy'])})
            continue
        return False
    it = _items(bot)
    return bool(_reward_showing(it))


def _back_fixed(bot, log, ring=None, via='', force_first=True,
                wait_appear=3.0, wait_close=3.0):
    """⭐ 点固定「返回」把奖励展示收起来 —— **先等它出现 → 点一次 → 等它收起 → 还开着才补一次**

    ⚠⚠ 2026-10-04 真机修（用户原话：「**有时候连点两下返回**」、「**有时候会没买完第三层
       就关了黄金宝库页面**」）—— 两条症状**同一个根因**：**在奖励面板出现之前就去点返回**。

       **实测铁证**（用户当场点了「选择奖励」，我在前后各抓一帧对比）：
           点之前：`黄金宝库(461,256)` + `选择奖励(597,978)`
           点之后：`黄金宝库(460,255)` + **`恭喜获得(360,505)`** + **`返回(359,808)`**
                   + `购买(597,963)`（按钮已变回「购买」= 可以买 20000 了）
         ⇒ 点「选择奖励」**不会关面板**；奖励面板是**过动画才出来**的。

       而 `tap_dlg(at, wait=2.6)` 里的 `wait_change()` **会被"按钮自己按下去的高亮"立刻触发**
       ⇒ 它返回时**奖励面板根本还没出来** ✗ ⇒ 旧代码那时就去点固定「返回」(360,806)，
       而**宝库面板上 (360,806) 正是棋盘格（行3,列2）**
       （`gx0=167 / gy0=497 / pitch=96` ⇒ 格心 (359,785)，(360,806) 落在格内）
       ⇒ 那一下 **打在棋盘格上 = 换选了另一个格子**：
            · 「连点两下返回」 = 第 1 下打在格子上、第 2 下才是真返回 ✗
            · 「点选择奖励像把宝库关了」 = 选中的格子被换掉，后续判据全乱 ✗

    ⇒ 现在：**① 先轮询等奖励展示真的出现（最多 `wait_appear` 秒）**
              **② 出现了才点「返回」；一直没出现 ⇒ 一下都不点**（绝不打在棋盘格上 ✓）
              **③ 每次点完再轮询等它收起；真的还在才补第 2 下**（上限 2 下，正常 1 下）
       ⚠ `force_first` 现在**只影响"等不到时"的日志措辞**（保留参数是为了不动三处调用点）——
         行为上三处**一律**"没看到奖励展示就不点" ✓（这正是本次修复的要点）
    """
    # ① 等奖励展示出现（**没出现就不点** —— 这是本次修复的核心）
    _t0 = time.time()
    _shown = bool(_reward_showing(_items(bot)))
    while not _shown and time.time() - _t0 < wait_appear:
        time.sleep(0.35)
        _shown = bool(_reward_showing(_items(bot)))
    if not _shown:
        log.append({'vault': 'back_skip_no_reward', 'ring': ring, 'via': via,
                    'force_first': bool(force_first),
                    'waited': round(time.time() - _t0, 1),
                    'note': '奖励展示没等到 ⇒ **一下都不点**（(360,806) 在宝库面板上是棋盘格 ✓）'})
        if ring is not None:            # 收尾那处（ring=None）本来就常常"没东西可收" ⇒ 不必刷屏
            say('      · 宝库第 %s 层：奖励展示没出现 ⇒ **不点返回**（防打在棋盘格上 ✓）'
                % ring)
        return 0
    n = 0
    for _try in range(2):
        if _try and not _reward_showing(_items(bot)):
            break                           # 已经收起 ⇒ **绝不再点** ✓
        try:
            # ⭐ 2026-10-06 走安全区守卫（用户口径「把宝库点击范围固定下」；见 `_vault_tap`）
            _vault_tap(bot, VAULT_RET[0], VAULT_RET[1], log=log,
                       what='back_fixed', wait=1.8)
        except Exception:                   # noqa: BLE001
            break
        n += 1
        log.append({'vault': 'back_fixed', 'ring': ring, 'at': list(VAULT_RET),
                    'n': n, 'via': via})
        # ⭐ 等它**真的收起来**（收起是动画，靠等；不是靠再点一下 ✗）
        _t0 = time.time()
        while time.time() - _t0 < wait_close:
            time.sleep(0.35)
            if not _reward_showing(_items(bot)):
                break
    return n


def vault_flow(bot, log):
    """黄金宝库买完 —— **按 1→2→3 圈依次走一遍**（用户 2026-09-25 定案）

    ⭐ 2026-10-02：`bot` 先包一层代理 ⇒ 每次 `tap` 自动作废面板 OCR 缓存 ✓

    为什么按圈遍历而不是「数自己买了几次」：中途接手时计数从 0 开始，
    会一直去点第 1 圈 → 死循环（用户：「你刚刚是一直重复第一圈」）。
    按圈遍历时，某一圈点错了也只是**空操作**（游戏 `OnFuncButtonClicked` 会检查
    `selectingIndex` 必须属于当前层，不属于就直接 return），不会误领，下一圈继续。

    每一圈：
      ① 按钮是「购买」→ 先点它解锁（10000 外层 / 20000 内层 / 40000 核心）
      ② 按钮是「选择奖励」→ 在**这一圈**里挑（优先天赋果实/四叶草，比右下角数量）
         → 点中选那格 → 点这颗按钮
      ③ 出现「返回」→ 点掉，回到宝库面板
    三圈走完按钮变「离开」→ 点它；还开着就点右上 X 兜底。
    """
    # ⭐ 2026-10-10：**每局清空"读名时点过的格"**（一局宝库一次 ✓）
    #   ⇒ 本函数里据此跳过重复点击（否则会打开详情页盖住按钮 ✗，
    #     真机铁证见 `pick, name = vault_pick(...)` 后面那段长注释 ✓）
    try:
        _PROBED.clear()
    except Exception:       # noqa: BLE001
        pass
    acts = []
    for ring in (1, 2, 3):
        _vstep(bot, log, 'r%d_start' % ring)        # ⭐ 取证：每圈开头
        # ① 需要时先解锁这一圈（⭐ 复用最后一帧：没买成时不必再 OCR 一次）
        it = None
        _buy_clicks = []                      # ⭐ v0.97：本圈点过的「购买」价格 ⇒ 防连点
        for _ in range(4):
            it = _items(bot)
            # ⭐⭐⭐ 2026-10-03 用户口径（原话）：「**领取奖励了，购买、选择奖励是一个按钮，
            #   且固定位置；选择奖励后的返回也是固定位置**」
            #   ⇒ 这三态**同一个按钮、同一个固定坐标**（真机实测 720p = **(596,978)**，
            #     见 loop_log `{"vault":"claim","btn":"选择奖励","at":[596,978]}`）
            #   ⇒ ⛔ 删掉 v0.97 那道 `_reward_showing + _dismiss` 闸门 ——
            #     它的假设是"屏幕上有奖励展示/返回 ⇒ 点购买是白点"，
            #     但按用户口径，**这时候按钮就叫「返回」，点它正是该做的事** ✓
            #     真机故障（用户报「最近一次黄金宝库无法正常购买」）：
            #       #35 buy ring1 ✓ → #39 claim ring1 ✓
            #       #40/#41 `fallback_blocked_by_reward` ring2/ring3 ⇒ 拒绝点击 ⇒ 直接跳过
            #       #43 done acts=["buy1","claim1"] ⇒ **只买了 1 圈就收工** ✗✗
            #     ⇒ 现在：**永远点那个固定按钮**（标签随状态变，不用读），节奏由定死间隔控制 ✓
            label, cost, pos = _btn(it)
            if label and '购买' in label:
                if cost is not None and cost in _buy_clicks:
                    # ⭐⭐⭐ v0.97 真机修（用户报「选择后不点返回就直接点购买」）：同一个价格的
                    #   「购买」又出现了 ⇒ 上一次点击**根本没生效**（被模态/钱不够/点空）
                    #   ⇒ 绝不再点（旧写法 `for _ in range(4)` 会连点 4 次 ✗）：
                    #     收起面板、这圈放弃、交给下一轮 ✓
                    log.append({'vault': 'buy_no_effect', 'ring': ring, 'cost': cost})
                    say('      · 宝库第 %d 层：点了「购买」没生效 ⇒ 不再连点（先收起面板 ✓）' % ring)
                    # ⚠ 2026-10-04：这里也**收敛成 1 下**（`_dismiss` 默认 tries=3 会连点 3 下
                    #   「返回」⇒ 同「连点两下返回」那类事故；这条是异常兜底，
                    #   "少点"永远比"多点"安全：多点会把宝库面板点关 ✗）
                    _dismiss(bot, log, tries=1)
                    it = None
                    break
                _buy_clicks.append(cost)
                # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）
                _vault_tap(bot, *(pos or VAULT['buy']), log=log,
                           what='buy_ring%d' % ring, wait=2.6)
                _confirm(bot, log, 'vault_buy%d' % ring)
                log.append({'vault': 'buy', 'ring': ring, 'cost': cost, 'at': pos})
                acts.append('buy%d' % ring)
                _vstep(bot, log, 'r%d_after_buy' % ring)     # ⭐ 取证：点了「购买」之后
                it = None                     # 画面变了 ⇒ 这一帧作废
                continue
            break                             # 不是「购买」⇒ it 就是当前帧，直接复用
        if it is None:
            it = _items(bot)
        if not _present(bot, it):
            log.append({'vault': 'panel_gone', 'ring': ring})
            break
        label, cost, pos = _btn(it)
        if label and '离开' in label:
            # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）
            _vault_tap(bot, pos[0], pos[1], log=log, what='leave', wait=2.4)
            log.append({'vault': 'leave'})
            break
        if not (label and ('选择' in label or '领取' in label)):
            # ⭐⭐⭐ 2026-10-01 用户报「第一层还没选择奖励就乱点了 / 选了默认没选天赋果实」：
            #   旧写法这里**直接 `continue` 跳过整层** ⇒ 既不点「选择奖励」也不挑格子
            #   ⇒ 游戏保持**默认选中**的格子 ⇒ 用户看到的"选了默认、没选果实" ✗✗
            #   ⇒ 改成：**读不到按钮就先做保底动作**，绝不静默跳过一整层 ✓
            #     ① 先按真机标定坐标点一次「选择奖励/购买」（VAULT['buy']，实测 895,1498 ✓）
            #     ② 再挑一格（图标认不出 ⇒ `vault_pick` 自带 `_probe_name` 点开详情读名 ✓）
            #     ③ 然后重新读按钮，读到就正常点 ✓
            # ⚠⚠ 2026-10-03 用户口径（同上）：**购买/选择奖励/返回是同一个固定按钮** ⇒
            #   原来这里"必须先确认没有奖励展示，否则不许点"的闸门**已删** ✗
            #   （真机后果就是 `fallback_blocked_by_reward` 把 ring2/ring3 整圈跳过 ⇒
            #     只买到 1 圈 = 用户报的「黄金宝库无法正常购买」）
            #   ⇒ 直接**点固定坐标**（按钮当前叫「购买/选择奖励/返回」都无所谓）✓
            log.append({'vault': 'no_select_btn_fallback', 'ring': ring, 'label': label})
            say('      · 宝库第 %d 层：读不到按钮文字 ⇒ 用标定坐标保底（不跳过整层 ✓）' % ring)
            _pick_fb, _name_fb = vault_pick(bot, log, ring)
            if ring < 3:
                # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）
                _vault_tap(bot, _pick_fb[0], _pick_fb[1], log=log,
                           what='claim_fb_pick%d' % ring, wait=1.7)
            log.append({'vault': 'claim_fallback', 'ring': ring,
                        'pick': _pick_fb, 'name': _name_fb})
            it = _items(bot)
            label, cost, pos = _btn(it)
            if not (label and ('选择' in label or '领取' in label)):
                # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）—— 标定坐标兜底 ✓
                _vault_tap(bot, VAULT['buy'][0], VAULT['buy'][1], log=log,
                           what='claim_fb_btn%d' % ring, wait=2.6)
                acts.append('claim%d_fb' % ring)
                # ⭐⭐⭐ 2026-10-03 用户报「购买宝库第三次选择奖励后**没点返回**，就点右上角关闭了」：
                #   根因就是这里原来 `_dismiss(bot, log)`（靠 OCR 找「返回」）+ `continue`
                #   ⇒ **③ 那一步固定返回被整个跳过** ✗
                #   真机 loop_log 铁证（gui_20261003_011030）：
                #       #76 back_fixed ring1 [360,806] ✓   #85 back_fixed ring2 ✓
                #       #88 buy_no_effect ring3 → #89 兜底分支 → #91 claim_fallback
                #       #92 leave → #93 x_close          ← ★ ring3 **没有 back_fixed** ✗
                #   ⇒ 改成与 ③ 同款：**点固定坐标的「返回」**（它是另一个按钮，位置固定）✓
                #   ⚠ 2026-10-04：并且要走**同一条有界口子** `_back_fixed()` ——
                #     原来这里也是裸点一下（配合 ③ 的连点 = 事故来源之一）
                _back_fixed(bot, log, ring=ring, via='fallback')
                continue
        # ② 在**这一圈**里挑一件 + 点按钮
        _vstep(bot, log, 'r%d_before_pick' % ring, it=it)   # ⭐ 取证：挑之前（复用这一帧 ✓）
        pick, name = vault_pick(bot, log, ring)
        # ⛔⛔⛔ 2026-10-10 **修「明明选了奖励还要点一下同样的位置 ⇒ 打开详情页」**
        #   （用户原话，真机铁证 `runs/acc1/loop/loop_log.json` #403~#412）
        #   ---- 病 ----
        #     `vault_pick` 走到 `_probe_name` 兜底时，会**逐格点开详情读名**（前 3 格）：
        #         #403 probe_blank_ok ｜ #404 probe at=[264,593]
        #         #405 probe_blank_ok ｜ #406 probe at=[360,593]
        #         #407 probe_blank_ok ｜ #408 probe at=[**456,592**]  ← 第 3 格
        #         #409 probe_none    ⇒ 落 `return cells[0]` 兜底
        #         #412 claim ring=2 pick=[**456,592**] name='随意'
        #     ⇒ **`pick` 正是探测时点过的那一格** ✗
        #     ⇒ 本行又 `_vault_tap(pick)` **点第二次** ⇒ 游戏里那格已是"选中"态
        #       ⇒ 再点 = **打开详情页** ⇒ 把右下角「选择奖励」按钮盖住 ✗✗
        #     ⇒ 与用户原话完全吻合：「**明明选择了奖励还要点一下同样的位置
        #        导致打开了详情界面**」✓✓
        #   ---- 为什么会选中同一格 ----
        #     `probe_none`（3 格都没读到名字）时返回 `cells[0]`；而 `cells` 顺序
        #     里 `cells[0]` 未必是探测过的那个 —— 本次恰好 `pick=[456,592]` 与
        #     第 3 次 probe 相同 ⇒ 撞上了 ✓（无论撞不撞，**探过就不该再点** ✓）
        #   ---- 修法 ----
        #     `vault_pick` 把"探测时点过的坐标"记进 `_PROBED`（本图/本层作用域）；
        #     这里**跳过重复点击** ⇒ 直接去读按钮 + 点「选择奖励」 ✓
        #     ⚠ 只在**同一圈**内记忆（跨圈会误判：不同圈的格子各不相同 ✓）
        _already = (pick[0], pick[1]) in _PROBED.get(ring, set())
        if _already:
            log.append({'vault': 'skip_repick', 'ring': ring,
                        'at': [pick[0], pick[1]],
                        'name': name,
                        'note': '这一格**在读名时已经点开过** ⇒ 跳过重复点击'
                                '（否则会打开详情页盖住按钮 ✗）'})
            say('       · 宝库第 %d 层：(%d,%d) 读名时已点过 ⇒ **跳过重复点击** ✓'
                % (ring, pick[0], pick[1]))
        elif ring < 3:
            # ⚠ 第 3 圈（中心格）**游戏会自动选中**（源码 RefreshDefaultSelectingIndex：
            #   currentLevel==3 时 selectingIndex=12），再点一次等于点已选中的格子 →
            #   会弹出该奖励的详情面板、把右下角按钮盖住（用户 2026-09-25 报「点两下中间的」）
            # ⚠⚠ 2026-10-05 复述：这一下**是用户认可保留的**（"选择奖励前的两次点击"的**第 2 下**）。
            #   我上一提交（ca6ba43）**误把它也改成 `time.sleep(1)` 了** —— 用户当场指出
            #   「**让你删一个点击，怎么两个都删了**」⇒ 已恢复原样 ✓
            #   （要改的是 `vault_pick` 里那个"点一格翻牌"= **第 1 下**：它已改成"只等不点" ✓）
            # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）—— 格子坐标本就该在面板内 ✓
            _vault_tap(bot, pick[0], pick[1], log=log,
                       what='pick_cell%d' % ring, wait=1.7)
        # ⭐ 2026-10-05：先读这一帧（`it2`），再让取证**复用**它 ⇒ 取证零额外 OCR ✓
        it2 = _items(bot)
        _vstep(bot, log, 'r%d_after_pick' % ring, it=it2)   # ⭐ 取证：点了格子之后
        l2, _c2, p2 = _btn(it2)
        if not (l2 and ('选择' in l2 or '领取' in l2)):
            # 按钮读不到 → 多半是详情面板盖住了，点空白处关掉再读一次
            # ⭐ 2026-10-06：走**安全区守卫**（见 `_vault_tap` —— 旧值在面板外 ✗）
            _vault_tap(bot, VAULT['blank'][0], VAULT['blank'][1], log=log,
                       what='after_pick_blank', wait=1.6)
            it2 = _items(bot)
            l2, _c2, p2 = _btn(it2)
        at = p2 if (l2 and ('选择' in l2 or '领取' in l2)) else pos
        log.append({'vault': 'will_tap_btn', 'ring': ring, 'btn': l2,
                    'at': list(at), 'src': 'ocr' if (l2 and p2) else 'stale_pos'})
        # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）——
        #   用户报的「点选择奖励直接就关了宝库页面」就发生在这一步 ⇒ 必须保证落在面板内 ✓
        _vault_tap(bot, at[0], at[1], log=log,
                   what='select_reward_btn%d' % ring, wait=2.6)
        log.append({'vault': 'claim', 'ring': ring, 'pick': pick, 'name': name,
                    'btn': l2, 'at': at})
        acts.append('claim%d' % ring)
        #   ⭐⭐ 取证：**用户报的"点选择奖励直接就关了宝库页面"就发生在这一步之后** ⇒ 必落帧
        _vstep(bot, log, 'r%d_after_select_tap' % ring)
        # ③ 收起奖励展示 —— ⭐⭐⭐ 2026-10-03 用户口径：「**选择奖励后的返回也是固定位置**」
        #   ⇒ 点**固定坐标**的「返回」（`VAULT_RET` = 实测 (360,806)；它是**另一个按钮**，
        #     绝不能拿购买按钮的坐标去点 ✗）
        #   ⛔ 而且**无论收没收到都不许放弃后面的圈** —— 旧版在 `_reward_showing` 为真时
        #     `return acts` ⇒ 真机只买到第 1 圈（用户报的「黄金宝库无法正常购买」）✗✗
        #
        # ⚠⚠ 2026-10-04 真机修（用户原话：「**有时候连点两下返回**」、「**有时候会没买完
        #   第三层就关了黄金宝库页面**」）—— **两条症状同一个根因**：
        #     旧写法 = 点一次固定返回 **＋** `if _dismiss(): _dismiss()`，
        #     而 `_dismiss(tries=3)` **每次最多再点 3 下「返回」**
        #     ⇒ 同一轮**最多点 5 下「返回」** ✗✗
        #     奖励展示**关掉之后**剩下那几下就落在**宝库面板**上（(360,806) 一带正是格子）：
        #       轻则"连点两下返回"；重则点到格子、甚至把宝库面板点关
        #       ⇒ 第 3 层还没买就退出 = 用户看到的「没买完第三层就关了」✗
        #   ⇒ 现在：**调 `_back_fixed()`** —— 点一次 → **等它真收起** → 还开着才补一次
        #     （上限 2 下、正常就是 1 下；三处统一走这同一条口子 ✓ 见该函数 docstring）
        _backs = _back_fixed(bot, log, ring=ring, via='claim')
        _vstep(bot, log, 'r%d_after_back' % ring)   # ⭐ 取证：点了「返回」之后
        if _backs > 1:
            say('      · 宝库第 %d 层：返回点了 %d 下（第 1 下没收拾干净才补的第 2 下）'
                % (ring, _backs))
        if _reward_showing(_items(bot)):
            log.append({'vault': 'reward_showing_after_fixed_back', 'ring': ring,
                        'backs': _backs,
                        'note': '已点固定返回仍显示奖励展示 ⇒ **继续下一圈**（不再连点）✓'})
            say('      · 宝库第 %d 层：奖励展示还在（已点固定返回）⇒ 继续下一圈 ✓' % ring)
    # 收尾：返回 → 离开 → X
    #   ⚠ 2026-10-04：`_dismiss()` 会**连点最多 3 下**「返回」⇒ 换成同一条有界口子
    #     （`force_first=False` ⇒ 没东西可收就**一下都不点** ✓）
    _back_fixed(bot, log, via='tail', force_first=False)
    it = _items(bot)
    label, _c, pos = _btn(it)
    if label and '离开' in label:
        # ⭐ 2026-10-06 走安全区守卫（见 `_vault_tap`）
        _vault_tap(bot, pos[0], pos[1], log=log, what='leave_tail', wait=2.4)
        log.append({'vault': 'leave'})
    it = _items(bot)
    if _present(bot, it):
        # ⭐ 2026-10-06 走安全区守卫（右上 X 在安全区内 ✓；越界也会被夹回来 ✓）
        _vault_tap(bot, VAULT['x'][0], VAULT['x'][1], log=log,
                   what='x_close', wait=2.0)
        log.append({'vault': 'x_close'})
    _confirm(bot, log, 'vault_after')
    log.append({'vault': 'done', 'acts': acts})
    return acts


def ensure_closed(bot, log):
    """兜底：把还开着的面板 X 掉（只认 x≈493 / x≈1024 的真关闭符）"""
    closed = 0
    for _ in range(3):
        it = _items(bot)
        x = None
        for t in it:
            if t['text'].strip() in ('X', 'x', '\u00d7', '\u2715', '\u2716') and \
                    min(abs(t['cx'] - 493), abs(t['cx'] - 1024)) <= 80:
                x = t
                break
        if not x:
            break
        bot.tap_dlg(x['cx'], x['cy'], wait=1.8)
        closed += 1
    if closed:
        log.append({'ensure_closed': closed})
    return closed


# ══════════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐⭐⭐ 2026-10-07 **三个新的特殊地块流程**（真机逐个实测出来的）
#
#   ① `relic_flow`    勇者之墓（SP=3）面板叫「英灵使者」
#   ② `gift_flow`     限时礼包（SP=5）面板叫「限时超值礼包」
#   ③ `foretell_flow` 预言石碑（SP=7）面板叫「预言石板」
#
#   数据来源：`_ref_game_src/README_{勇者之墓,限时礼包,预言石碑}_真机实测.md`
#   坐标全部 720×1280 实测；面板布局**固定**（多次随机面板逐像素验过 ✓）
#
#   ⚠⚠ 共同注意（三条都是实测踩过的）：
#     · **暗格点不动** ⇒ 必须先确认 `revealed=True`（调用方保证）
#     · **关闭面板统一用「万能点位」**(361,1260) —— 用户口径 ✓（不必找各自的 X）
#     · **结果框的「确定/返回」不能写死坐标** ⇒ 必须每帧 OCR 找（会随文案行数变）
# ══════════════════════════════════════════════════════════════════════════════

# 万能关闭点（= `fixed.A('universal_close')`；用户 2026-10-07 口径：
#   「礼包界面可以按万能点位关掉」⇒ 三个新面板**都走它** ✓）
UNIV_CLOSE = (361, 1260)

# ── ① 勇者之墓「英灵使者」（实测 runs/spec_dev/relic_panel*.png）────────────
RELIC = {
    'title': '英灵使者',
    # 三行卡片的点击落点（OCR conf 1.00；两次随机面板**逐像素相同** ✓）
    'rows': [(284, 544), (286, 674), (285, 804)],
    'ok': (458, 960),          # 「确定」（OCR conf 1.00）
    'x': (655, 302),           # 右上关闭 X（实测；平时用 UNIV_CLOSE 就够）
}
RELIC_WAIT_ROUNDS = 4          # 结果框「确定」最多找几轮
RELIC_WAIT_SEC = 0.8           # 每轮间隔（秒）


def _relic_close_result(bot, log=None):
    """**带重试**点掉勇者之墓的「结果框」-> (x, y) 或 None

    ⭐⭐ 用户 2026-10-08 口径（原话）：
      「**勇者之墓不能用万能点位关，得点击确认按钮**」✓

    为什么要重试（真机事故，2026-10-08 第二次真机测）：
      · 结果框**正在弹出动画中**时，一次性 OCR 读不到「确定」⇒ `has_ok_btn=False` ✗
      · 而原来的兜底是**万能点位** ⇒ **对这个结果框无效**（截图证明它照样开着）✗✗
      ⇒ 每轮**重新取帧 + OCR**，找到「确定/返回」就点 ✓
      ⚠ 4 轮都找不到 ⇒ 返回 None（**如实报"没点掉"**，不假装成功 ✓）

    ⚠ 「确定」有**两个位置**：面板上的 `(458,960)` 与结果框的 `(~360,770)`
      ⇒ 所以 `ymin/ymax` 必须**只框结果框那一段**（560~1060 会同时覆盖两者 ✗）
      ⇒ 本函数用 **560~900**（结果框在 ~770；面板的在 960 ⇒ 排除掉 ✓）
    """
    for rd in range(1, RELIC_WAIT_ROUNDS + 1):
        if rd > 1:
            try:
                import time as _t
                _t.sleep(RELIC_WAIT_SEC)
            except Exception:       # noqa: BLE001
                pass
        try:
            _invalidate(bot)
        except Exception:           # noqa: BLE001
            pass
        p = _find_text_btn(bot, ('确定', '返回'), 560, 900)
        if p:
            bot.tap_dlg(p[0], p[1], wait=2.0)
            if log is not None:
                log.append({'relic': 'close_result', 'at': [p[0], p[1]],
                            'text': p[2], 'round': rd, 'src': 'ocr'})
            return (p[0], p[1])
    if log is not None:
        log.append({'relic': 'close_result_fail', 'rounds': RELIC_WAIT_ROUNDS})
    return None


# ── ② 限时超值礼包（实测 runs/spec_dev/gift_*.png）──────────────────────────
GIFT = {
    'title': '限时超值礼包',
    # ⭐ 用户口径：「**720 分辨率下第一个免费按钮是固定坐标，只点最上面那个免费按钮**」
    'free1': (513, 527),       # 第 1 档「免费」（OCR conf 0.99）⇒ **只点这个** ✓
    'free3': (513, 840),       # 第 3 档「免费」（OCR conf 1.00）——**不点**（用户口径）
    'paid2': (513, 685),       # 第 2 档「6 草」——**不点**（要花幸运草）
    'back': (360, 807),        # 结果框「返回」（实测；但仍优先 OCR 找）
}

# ── ③ 预言石碑「预言石板」（实测 runs/spec_dev/foretell_*.png）──────────────
FORETELL = {
    'title': '预言石板',
    'cards_y': 620,            # 三张卡的点击 y（实测；x 由 OCR 标题给）
    'ok': (360, 888),          # 「确定」（OCR conf 1.00）
    # ⭐ 选择策略（用户 2026-10-07 口径，原话）：
    #   「优先选 地图中至少有1名敌人拥有<紫/橙>色位阶的**掉宝加护**这个加护。
    #     其他就按品阶排，优先品质高的」
    #   ＋「地图中必定出现**金属宝箱怪**也要单独拿出来弄个选项，遇到那个是否立即停止脚本」
    'PRIO_DROP': '掉宝',       # ① 最高优先级
    # ② "选了要停脚本"的优先挑（类似红装）
    #   ⚠ 「和平·金属宝箱怪」/「元素·紫」/「元素·橙」由**用户选项**控制是否真的停
    #     但**不管开不开**，这几个都值得**优先选**（用户在乎的东西 ✓）
    #   ⭐ 2026-10-09 用户：「预言石碑停止脚本加上橙色和紫色元素」⇒ 元素也进这里 ✓
    'PRIO_STOP': ('幸运', '和平', '元素'),
}

# ⭐⭐⭐ 2026-10-19 **「预言重复选择」二次确认弹窗**（用户要求"记住它，别被卡住"）
#   ---- 真机现场（`_imgs/now_screen.png`，2026-10-19 17:2x 设备 16448）----
#     点完「和平」这张卡后，游戏**先弹一个「提示」确认框**：
#        提示
#        和平已有紫色同名预言，
#        重复选择会将其覆盖。
#        [取消]  [确定]
#   ---- 为什么会卡死 ----
#     `FORETELL['ok'] = (360, 888)` 是「预言石板」主面板的确定按钮；
#     而这个提示弹窗在 **y≈742** ⇒ 点 (360,888) 落在弹窗下方**空白处**
#     ⇒ 弹窗不消失 ⇒ 后续所有点击全打在弹窗上 ⇒ **卡死** ✗✗
#   ---- 坐标来源（OCR 实测 conf 1.00，不是猜的）----
#     (204,742) 取消 ｜ (516,742) 确定
#   ---- 认它的判据（用文字，不用坐标）----
#     同一帧里出现「提示」+「重复选择会将其覆盖」（后者是这类弹窗独有的句子 ✓）
FORETELL_DUP = {
    'title': '提示',
    'line': '重复选择会将其覆盖',      # 独有句 ⇒ 不会误认别的"提示"弹窗 ✓
    'cancel': (204, 742),
    'ok': (516, 742),
}


def _univ_close(bot, log, what='', wait=1.6):
    """用**万能点位**关面板（用户口径；三个新面板都吃这一下 ✓）"""
    try:
        bot.tap_dlg(UNIV_CLOSE[0], UNIV_CLOSE[1], wait=wait)
        log.append({'close': 'universal', 'at': list(UNIV_CLOSE), 'what': what})
        return True
    except Exception:       # noqa: BLE001
        return False


def _find_text_btn(bot, texts, ymin=0, ymax=1280, k=2):
    """OCR 找**某个按钮文字**的真实坐标（**不写死** —— 结果框位置会变）

    ⚠ 真机教训（用户 2026-10-07 指出）：「**事件成功后的确认不是固定位置**」
      · 面板上的「确定」   = (458, 960)
      · 结果框的「确定」   = (360, 770)   ← 差 (98,190) ✗
      · 结果框的「返回」随**文案行数/奖励条目数**变高变矮
    ⇒ 凡是"结果框/奖励框"里的按钮，**必须每帧 OCR 找** ✓
    """
    if isinstance(texts, str):
        texts = (texts,)
    _best = None
    try:
        it = _items(bot)
    except Exception:       # noqa: BLE001
        return None
    for t in it:
        s = (t.get('text') or '').strip()
        if s not in texts:
            continue
        cy = t.get('cy') or 0
        if not (ymin <= cy <= ymax):
            continue
        # 取最靠中间的那个（多命中时）
        score = abs(cy - (ymin + ymax) / 2)
        if _best is None or score < _best[0]:
            _best = (score, t['cx'], t['cy'], s)
    if _best is None:
        return None
    return (_best[1], _best[2], _best[3])


def _tap_text_btn(bot, log, texts, fallback=None, ymin=0, ymax=1280, tag='', wait=2.0):
    """点一个"文字按钮"：**优先 OCR 找**，找不到才用 `fallback`（写死坐标）

    -> (x, y, src)；`src` = 'ocr' | 'fallback' | None
    """
    p = _find_text_btn(bot, texts, ymin, ymax)
    if p:
        bot.tap_dlg(p[0], p[1], wait=wait)
        log.append({tag: 'tap_text', 'text': p[2], 'at': [p[0], p[1]], 'src': 'ocr'})
        return (p[0], p[1], 'ocr')
    if fallback:
        bot.tap_dlg(fallback[0], fallback[1], wait=wait)
        log.append({tag: 'tap_text', 'text': str(texts), 'at': list(fallback),
                    'src': 'fallback'})
        return (fallback[0], fallback[1], 'fallback')
    log.append({tag: 'tap_text_none', 'text': str(texts)})
    return (None, None, None)


# ──────────────────────────────────────────────────────────────────────────────
# ① 勇者之墓（SP=3）→「英灵使者」：**三选一，零成本**（实测：不花钱不花体力 ✓）
# ──────────────────────────────────────────────────────────────────────────────
def relic_flow(bot, log):
    """勇者之墓买完 —— 真机全链路实测（2026-10-07）

    实测流水（`runs/spec_dev/flow_*`）：
        点格子 → 弹「英灵使者」→ 选一行 → 点「确定」→ **事件成功 + 奖励** → 关结果框
    账目核对：金银体力**都不变**（零成本 ✓）；奖励到手（如「战士铠甲」✓）

    选择策略（用户口径）：**优先成功率 100% 的行**
      · 面板三行成功率**通常都 100%**（属性远高于要求）⇒ 那就**取行1**（默认已选中）
      · 若某行不是 100% ⇒ **避开它**，选 100% 的
    实现：OCR 读「成功率N%」→ 按 y 映射到行号 → 选第一个 100% 的
    """
    acts = []
    b = _proxy(bot)
    _vstep(b, log, 'relic_start')
    it = _items(b)
    if not _has(it, RELIC['title']):
        log.append({'relic': 'panel_missing'})
        return acts

    # ── 读三行成功率（y 593/722/851 对应 行1/2/3）──
    y2row = {593: 0, 722: 1, 851: 2}
    succ = {}
    for t in it:
        s = (t.get('text') or '').replace(' ', '')
        if '成功率' not in s:
            continue
        cy = t.get('cy') or 0
        row = None
        for yy, rr in y2row.items():
            if abs(cy - yy) <= 14:
                row = rr
                break
        if row is None:
            continue
        succ[row] = ('100%' in s, s)
    log.append({'relic': 'succ', 'rows': {str(k): v[1] for k, v in sorted(succ.items())}})

    # ── 选行：优先 100%，没有就读不到 ⇒ 默认行1（它本来就是默认选中 ✓）──
    pick = None
    for r in (0, 1, 2):
        if succ.get(r, (False,))[0]:
            pick = r
            break
    if pick is None:
        pick = 0                    # 兜底：行1 默认选中 ✓
        say('      · 勇者之墓：读不到 100%% 的行 ⇒ 用默认（行1）【%s】' % (succ,))
    else:
        say('      · 勇者之墓：选第 %d 行（成功率 100%%）' % (pick + 1))

    # ⚠ 行1 本来就是默认选中 ⇒ 只有选 2/3 行时才真点（**少点一下** ✓）
    if pick != 0:
        bot.tap_dlg(RELIC['rows'][pick][0], RELIC['rows'][pick][1], wait=1.6)
        log.append({'relic': 'pick_row', 'row': pick + 1,
                    'at': list(RELIC['rows'][pick])})
    acts.append('pick%d' % (pick + 1))

    # ── 点「确定」──
    p = _find_text_btn(b, ('确定',))
    at = (p[0], p[1]) if p else RELIC['ok']
    bot.tap_dlg(at[0], at[1], wait=2.6)
    log.append({'relic': 'ok', 'at': list(at), 'src': 'ocr' if p else 'fallback'})
    acts.append('ok')

    # ── 读结果（成功/失败 + 奖励）──
    it2 = _items(b)
    txts = [(t.get('text') or '') for t in it2]
    joined = ' '.join(txts)
    # ⭐⭐ 2026-10-08 用户口径（原话）：「**直接识别确认按钮啊**」✓
    #   ⛔ 我第一版判 `'事件成功' in joined` ⇒ 真机实测结果框写的是
    #      「**事件大成功**」⇒ **判据漏了** ⇒ 走不进"关结果框"分支
    #      ⇒ 结果框留在屏幕上（后续流程全乱）✗
    #   ⇒ 改：**以「有没有确定按钮」为准**（那是结果框存在的**充分证据** ✓），
    #     文案只用来**记日志**（成功/失败/大成功都如实记，不参与控制流 ✓）
    ok = ('事件成功' in joined) or ('事件大成功' in joined) \
        or ('获得了勇者的认可' in joined)
    fail = '没能获得' in joined
    big = '事件大成功' in joined
    reward = [t for t in txts if '获得[' in t or '获得【' in t]
    # ⭐ 结果框在不在 ⇒ **只认按钮**（用户口径 ✓）
    has_ok_btn = _find_text_btn(b, ('确定', '返回'), 560, 1060) is not None
    log.append({'relic': 'result', 'ok': bool(ok), 'big': bool(big),
                'fail': bool(fail), 'btn': bool(has_ok_btn),
                'reward': reward[:4]})
    say('      · 勇者之墓结果：%s%s'
        % ('★★大成功' if big else ('★成功 ✓' if ok else
                                  ('✗失败' if fail else '？未读到文案')),
           ('  奖励=%s' % reward[:2]) if reward else ''))

    # ── 关结果框：**带重试地找「确定」**（用户 2026-10-08 口径）──
    #   ⭐⭐ 用户原话：「**勇者之墓不能用万能点位关，得点击确认按钮**」✓
    #   ── 真机事故（2026-10-08 第二次真机测）──
    #     日志：`{'relic':'tap_text_none'}` + 「⚠ 结果框按钮没 OCR 到 ⇒ 用万能点位兜底」
    #     截图 `runs/sptest/t2_final_relic.png` 是铁证：**结果框还开着**
    #     （「事件成功 / 获得[示警戒指]×1 / 确定」）✗✗
    #   ── 两个毛病 ──────────────────────────────
    #     ① `has_ok_btn` 是**一次性**判断 ⇒ 结果框**正在弹出动画中**时读到 False ✗
    #        （与 `foretell` 那个 bug **同一个族**：判据建在"拿不到数据"的时刻）
    #     ② 兜底用**万能点位** ⇒ 对这个结果框**无效** ✗（用户明确指出）
    #   ⇒ 修法：**每轮重新取帧 + OCR 找「确定」**，最多 4 轮；找到就点 ✓
    #     ⚠ **不再用万能点位兜底**（关不掉它，只会白点一下、把面板层级搞乱）
    if has_ok_btn or ok or fail or big:
        _vstep(b, log, 'relic_result')
        p2 = _relic_close_result(b, log)
        if p2:
            acts.append('close_result')
        else:
            # ⚠ 如实记：没能点掉（**不假装成功** ✓）；留给下一轮/人工
            say('      · ⚠ 4 轮都没找到「确定」⇒ **结果框可能还开着**（如实记录，不冒充已关）')

    # ── 兜底：面板还开着就万能点位关掉 ──
    if _has(_items(b), RELIC['title']):
        _univ_close(b, log, 'relic_tail')
    log.append({'relic': 'done', 'acts': acts})
    return acts


# ──────────────────────────────────────────────────────────────────────────────
# ② 限时礼包（SP=5）→「限时超值礼包」：**只点第 1 个「免费」**（用户口径 ✓）
# ──────────────────────────────────────────────────────────────────────────────
def gift_flow(bot, log):
    """限时礼包 —— 真机全链路实测（2026-10-07）

    用户口径（原话）：
      「**720 分辨率下第一个免费按钮是固定坐标，只点最上面那个免费按钮**」

    实测流水（`runs/spec_dev/gift_*`）：
        点格子 → 弹「限时超值礼包」→ 点第 1 档「免费」(513,527)
        → 「恭喜获得 / 货币 / 红宝石×20」 → 点「返回」(360,807) → 面板（该档变「已领取」）

    账目核对：宝石 8930 → 8950（**+20 到账 ✓**）；幸运草不变（**没点第 2 档** ✓）

    ⚠ 三档区别（实测）：
        礼包1  红宝石×20        免费     ← **只点这个** ✓
        礼包2  红宝石×60        6 草     ← 不点（要花草）
        礼包3  券×1            免费     ← 不点（用户只说点第一个）
    """
    acts = []
    b = _proxy(bot)
    _vstep(b, log, 'gift_start')
    it = _items(b)
    if not _has(it, GIFT['title']):
        log.append({'gift': 'panel_missing'})
        return acts

    # ── 点第 1 档「免费」（**固定坐标** ✓ 用户确认）──
    bot.tap_dlg(GIFT['free1'][0], GIFT['free1'][1], wait=2.4)
    log.append({'gift': 'tap_free1', 'at': list(GIFT['free1'])})
    acts.append('free1')

    # ── 读「恭喜获得」（有就说明领到了）──
    it2 = _items(b)
    txts = [(t.get('text') or '') for t in it2]
    joined = ' '.join(txts)
    got = '恭喜获得' in joined
    reward = [t for t in txts if t.strip() in ('货币', '道具', '装备')]
    log.append({'gift': 'result', 'got': bool(got), 'texts': txts[:8]})
    say('      · 限时礼包：%s' % ('★领到 ✓' if got else '（没看到"恭喜获得"，见日志）'))

    # ── 关结果框（OCR 找「返回」；**不写死** —— 与勇者之墓同一教训 ✓）──
    if got:
        _tap_text_btn(b, log, ('返回', '确定'), fallback=GIFT['back'],
                      ymin=700, ymax=900, tag='gift', wait=2.0)

    # ── 面板可能还开着 ⇒ 万能点位关掉（用户口径 ✓）──
    if _has(_items(b), GIFT['title']):
        _univ_close(b, log, 'gift_tail')
    log.append({'gift': 'done', 'acts': acts})
    return acts


# ──────────────────────────────────────────────────────────────────────────────
# ③ 预言石碑（SP=7）→「预言石板」：**多选 maxPick 个，按策略挑**
# ──────────────────────────────────────────────────────────────────────────────

# ⭐ 预言卡的**标题白名单**（来自数据表 `Foretell` 全 28 种，实测确实 54 行）
#   用途：① 带重试地"等卡片出现" ② 只认白名单里的名字（防把别的面板文字当卡片 ✗）
FORETELL_NAMES = (
    '丰收', '藏宝', '武装', '命运', '秘藏', '神兵', '强敌', '路标', '元素',
    '掉宝', '奇遇', '勇者', '机遇', '宝库', '黄金', '传承', '魔法', '财富',
    '伏击', '幸运', '祥和', '圣域', '战场', '精灵', '和平', '奇观',
)
FORETELL_CARD_Y = 439        # 卡片标题的 y（两次真机面板逐像素一致 ✓）
FORETELL_WAIT_ROUNDS = 6     # 等卡片的最多轮数
FORETELL_WAIT_SEC = 0.8      # 每轮间隔（秒）


def _foretell_read_cards(bot, log=None):
    """**带重试**读预言卡 -> (cards, 用了几轮)

    ⭐ 为什么必须重试（见 `foretell_flow` 里的长注释）：
      点开面板后有一段**弹出动画**，那时卡片区是空的（取证 `runs/sptest/ft_opened.png`）
      ⇒ 一次性读会得到 `cards=[]` ⇒ 被误判成"这面板没卡片"⇒ 关掉面板、白费机会 ✗
    ⇒ 每轮**重新取帧 + OCR**，读到**任一白名单标题**才算数 ✓

    返回的每个 card：`{'name','x','y','eff','tier'}`（`eff`/`tier` 由调用方补 ✓）
    """
    for rd in range(1, FORETELL_WAIT_ROUNDS + 1):
        if rd > 1:
            try:
                import time as _t
                _t.sleep(FORETELL_WAIT_SEC)
            except Exception:       # noqa: BLE001
                pass
        try:
            _invalidate(bot)                    # ⭐ 必须作废同帧缓存（否则读到旧帧 ✗）
        except Exception:           # noqa: BLE001
            pass
        try:
            it = _items(bot)
        except Exception as _e:     # noqa: BLE001
            if log is not None:
                log.append({'foretell': 'cards_ocr_err', 'round': rd,
                            'e': repr(_e)[:80]})
            continue
        cards = []
        for t in it:
            s = (t.get('text') or '').strip()
            cy = t.get('cy') or 0
            # ⭐ 只认白名单（比"2~4 个字"稳 ✓）；y 给一点余量
            if s not in FORETELL_NAMES:
                continue
            if not (FORETELL_CARD_Y - 20 <= cy <= FORETELL_CARD_Y + 26):
                continue
            if any(c['name'] == s for c in cards):
                continue                        # 同帧重复
            cards.append({'name': s, 'x': t.get('cx'),
                          'y': FORETELL['cards_y']})
        if cards:
            # 按 x 排序（左→右，与面板顺序一致 ✓）
            cards.sort(key=lambda c: c['x'] or 0)
            # 补上"同列的效果文案"
            for c in cards:
                eff = []
                for t in it:
                    s2 = (t.get('text') or '')
                    cy2 = t.get('cy') or 0
                    cx2 = t.get('cx') or 0
                    if cy2 <= 470 or cy2 > 760:
                        continue
                    if abs(cx2 - (c['x'] or 0)) > 60:
                        continue
                    eff.append(s2)
                c['eff'] = ' '.join(eff)
                c['tier'] = _foretell_tier(c['name'], c['eff'])
            if log is not None:
                log.append({'foretell': 'cards_ok', 'round': rd, 'n': len(cards),
                            'names': [c['name'] for c in cards]})
            return cards, rd
    return [], FORETELL_WAIT_ROUNDS


def _foretell_dup_confirm(bot, log=None, rounds=3):
    """认出「预言重复选择」提示 ⇒ 点**确定**（同意覆盖）⇒ True

    ⛔ 2026-10-19 用户报：「点中间的预言会**弹出没有见过的弹窗**」
      ⇒ 必须处理，否则后续点击全打在弹窗上 ⇒ 卡死 ✗

    ---- 判据（文字，不是坐标）----
      同帧出现「提示」+「重复选择会将其覆盖」
      ⚠ 后半句是这类弹窗**独有**的 ⇒ 不会误认别的"提示"框 ✓

    ---- 为什么点「确定」不点「取消」----
      这是游戏在问"要不要用新预言覆盖同色旧预言"
      ⇒ 点取消 = **这一次选择白做**（卡没选上，还白浪费一次机会）✗
      ⇒ 点确定 = 按我们的策略覆盖掉 ✓（用户要的就是"选更好的那张"）

    ---- 失败怎么办 ----
      等 `rounds` 轮仍没读到弹窗 ⇒ 返回 False（**不盲点**，交回上层）
    """
    import time as _t
    for rd in range(max(1, rounds)):
        if rd:
            _t.sleep(0.6)
        try:
            _invalidate(bot)
        except Exception:                   # noqa: BLE001
            pass
        try:
            it = _items(bot)
        except Exception:                   # noqa: BLE001
            continue
        # 同帧必须**两句都在**（只认「提示」会把别的确认框也认进来 ✗）
        has_title = any(str(t.get('text') or '').replace(' ', '') ==
                        FORETELL_DUP['title'] for t in it)
        has_line = any(FORETELL_DUP['line'] in
                       str(t.get('text') or '').replace(' ', '') for t in it)
        if not (has_title and has_line):
            continue
        if log is not None:
            log.append({'foretell': 'dup_confirm_seen', 'round': rd})
        try:
            bot.tap_dlg(*FORETELL_DUP['ok'], wait=1.4)
        except Exception as _e:             # noqa: BLE001
            if log is not None:
                log.append({'foretell': 'dup_confirm_err', 'e': repr(_e)[:80]})
            return False
        if log is not None:
            log.append({'foretell': 'dup_confirm_ok',
                        'at': list(FORETELL_DUP['ok'])})
        say('      · 遇到「预言重复」提示 ⇒ 点确定（同意覆盖）✓')
        return True
    return False


def foretell_flow(bot, log, flags=None):
    """预言石碑 —— 真机全链路实测（2026-10-07）

    ⭐⭐ 选择策略（用户 2026-10-07 口径，原话）：
      「**优先选 地图中至少有1名敌人拥有<紫/橙>色位阶的掉宝加护这个加护。
        其他就按品阶排，优先品质高的**」
      ＋「**地图中必定出现金属宝箱怪也要单独拿出来弄个选项，遇到那个是否立即停止脚本**」

    落地优先级：
        ① **`掉宝`**                    ⇒ 最优先（高于品阶）
        ② **`幸运`**                    ⇒ 选它 ＋ 触发「停脚本」（类红装）
           **`和平`（金属宝箱怪）**      ⇒ 选它 ＋ **按用户选项**决定是否停脚本
        ③ 其余                          ⇒ **按品阶排**（高→低）

    品阶怎么定（**不靠颜色**——我只实测了紫/蓝两种）：
        用 OCR 读到的**数值**反查 `Foretell` 表：
          `Foretell.TIER_BY_VALUE`（如 100=B / 200=A / 300=S / 500=SS ✓）

    -> dict：`{'acts':[...], 'stop': None|'幸运'|'和平', 'picked':[...]}`
       `stop` 非空 ⇒ **调用方负责停脚本**（像红装那样保现场）
    """
    out = {'acts': [], 'stop': None, 'picked': []}
    b = _proxy(bot)
    _vstep(b, log, 'foretell_start')
    it = _items(b)
    if not _has(it, FORETELL['title']):
        log.append({'foretell': 'panel_missing'})
        return out

    # ── 读 maxPick（「本次可选择 N 个预言！」）──
    import re as _re
    maxpick = 1
    for t in it:
        s = (t.get('text') or '').replace(' ', '')
        m = _re.search(r'可选择(\d+)个', s)
        if m:
            maxpick = max(1, int(m.group(1)))
            break
    log.append({'foretell': 'maxpick', 'n': maxpick})
    say('      · 预言石碑：本次可选 %d 个' % maxpick)

    # ── 读三张卡：标题（神兵/丰收/藏宝…）+ 它的效果文案（用来判 掉宝/幸运/和平）──
    #   卡片标题在 y≈439；效果文案在 y≈597/625（同 x）
    #
    # ⭐⭐⭐⭐ 2026-10-08 **带重试地读（治"面板动画未画完就判没卡片"）**
    #   ── 真机事故（用户要求「测一下点击预言石碑」时抓到）──
    #     点开 `1,6` 后**只等 2.8 秒**就调本流程 ⇒ `cards=[]` ⇒ 走"没卡片⇒关面板" ✗
    #     取证帧 `runs/sptest/ft_opened.png` 是铁证：**只有标题+提示，卡片区还是空的**
    #     （面板正在弹出动画中）⇒ 白费一次机会、还把面板关掉了 ✗✗
    #   ⚠⚠ **不是"面板画得慢"** —— 我单独量过：面板**开好之后** 0.8 秒就能读到卡片 ✓
    #     差的只是"**刚从点击弹出**"那一段动画窗口 ⇒ **不能用固定 sleep 猜** ✗
    #   ⭐ 这正是本项目反复栽的同一族 bug：**判据建在"拿不到数据"的时刻**
    #     （v1.62 veto 被冲掉 / v1.63 band 裁掉 HUD / v1.71 轮首读数为 None …）
    #   ⇒ 修法：**等元素出现**（每轮重新取帧 + OCR），读到任一卡片标题才算数；
    #     真超时才放弃 ⇒ 与 `_foretell_wait` 同口径 ✓
    cards, _rounds = _foretell_read_cards(b, log)
    if not cards:
        log.append({'foretell': 'cards_timeout', 'rounds': _rounds})
        say('      · ⚠ 等了 %d 轮仍没读到卡片 ⇒ 不盲点，关面板（下轮再来）' % _rounds)
        _univ_close(b, log, 'foretell_nocards')
        return out
    say('      · 读到 %d 张卡（第 %d 轮）' % (len(cards), _rounds))
    log.append({'foretell': 'cards', 'n': len(cards), 'round': _rounds,
                'cards': [{'n': c['name'], 'tier': c['tier'],
                           'eff': (c.get('eff') or '')[:28]} for c in cards]})

    # ── 排序：① 掉宝 ② **用户勾了才优先**的停脚本类 ③ 按品阶 ──
    # ⛔⛔⛔ 2026-10-19 **修「没勾和平却优先选和平」**（用户原话：
    #   「我窗口没有勾选和平啊」「勾选控制要优先」）
    #   ---- 真机证据 ----
    #     `runs/dev_16448/.stop_peace = 0`（**没勾**）
    #     脚本却优先选了「和平」⇒ 还弹出「和平已有紫色同名预言，重复选择会将其覆盖」✗
    #   ---- 病（两层）----
    #     ① `PRIO_STOP` 命中就无条件置顶 ⇒ 勾选**完全没参与"要不要优先"** ✗
    #     ② 数据表里「和平」有 **3 种**（名称一样、只能靠文案分）：
    #          foretell_22  A  …至少出现 N 个**金属宝箱怪**
    #          foretell_23  A  …至少出现 N 个**旅行商人**
    #          foretell_24  S  …至少出现 N 个**机巧宝箱怪**
    #        而旧判据只认「和平」两个字 ⇒ 三种一视同仁 ✗
    #        （用户口径一直只说**金属宝箱怪**那个 ✓）
    #   ---- 修法（按用户口径：**勾选 = 要不要优先**）----
    #     · 和平：**只有金属宝箱怪**那一种 ＋ 勾了 `.stop_peace` ⇒ 才优先
    #     · 元素：**只有紫/橙**档 ＋ 勾了对应开关 ⇒ 才优先（蓝档从不优先 ✓）
    #     · 幸运：`foretell_32` 是唯一一种、SS 级、且没有独立勾选
    #       ⇒ 用户从没反对 ⇒ **保留优先** ✓
    _fl = flags or {}

    def _is_prio_stop(c):
        """这张卡该不该"优先选"——**由用户勾选决定**（不是无条件）"""
        blob = c['name'] + c['eff']
        # ① 幸运（SS，唯一一种，无独立勾选）⇒ 保留优先 ✓
        if '幸运' in blob:
            return True
        # ② 和平：**只认金属宝箱怪** ＋ 必须勾了 stop_peace
        if '和平' in blob:
            if not bool(_fl.get('stop_peace_metal', False)):
                return False            # 没勾 ⇒ **不优先**（按品阶走 ✓）
            return '金属宝箱怪' in blob  # 勾了也只认金属宝箱怪那一种 ✓
        # ③ 元素：只认紫/橙（蓝档不优先），且要勾对应开关
        if '元素' in blob:
            if '橙色' in blob and bool(_fl.get('stop_elem_orange', False)):
                return True
            if '紫色' in blob and bool(_fl.get('stop_elem_purple', False)):
                return True
            return False                # 蓝档 / 没勾 ⇒ 不优先 ✓
        return False

    def _key(c):
        nm = c['name']
        if FORETELL['PRIO_DROP'] in (nm + c['eff']):
            return (0, 0)
        if _is_prio_stop(c):
            return (1, 0)
        return (2, -c['tier'])
    cards.sort(key=_key)
    pick = cards[:maxpick]
    say('      · 选卡：%s' % '、'.join(c['name'] for c in pick))

    # ⛔⛔⛔ 2026-10-13 **判停必须在点卡之前**（用户报 ✗）
    #   原话：「**说是立即停止，结果已经选择完预言了，我要在预言选择界面停止**」
    #   ---- 病（原代码顺序反了）----
    #     ① `for c in pick: tap_dlg(...)`   ← **先点卡**（已经选完）✗
    #     ② `for c in pick: if 元素...`      ← 之后才判要不要停
    #     ③ `tap_dlg(确定)`                  ← 再点确定
    #   ---- 修法 ----
    #     把"判停"提到最前 ⇒ **要停 ⇒ 一张都不点、连确定也不点** ⇒ 面板**原样留着** ✓
    #     （正是用户要的"在预言选择界面停止" ✓）
    # ── ⭐ 先判"要不要停脚本"（**在选卡之前**）──
    _stop_why = None
    for _c in pick:
        _blob = _c['name'] + _c['eff']
        if '幸运' in _blob:
            _stop_why = '幸运'
            break
        if '和平' in _blob and '金属宝箱怪' in _blob:
            # ⚠ 「和平」有 3 种（金属宝箱怪/旅行商人/机巧宝箱怪）
            #   用户口径只说**金属宝箱怪**那个 ⇒ 必须**精确匹配金属宝箱怪** ✓
            if bool((flags or {}).get('stop_peace_metal', True)):
                _stop_why = '和平·金属宝箱怪'
            break
        # ⭐⭐⭐⭐⭐ 2026-10-09 用户口径：「**预言石碑停止脚本加上橙色和紫色元素**」✓
        #   ── 「元素」的 3 档（数据表 `Foretell` 实测）──────────────────
        #       foretell_50  B  地图中至少出现 N 只莱姆，且所有莱姆至少是**蓝色**位阶
        #       foretell_51  A  …至少是**紫色**位阶   ← ⭐ 用户要停
        #       foretell_52  S  …至少是**橙色**位阶   ← ⭐ 用户要停
        #   ⇒ 判据 = **卡名含「元素」** ＋ **文案里带位阶词**
        #     ⚠ 用**文案里的位阶词**（`紫色`/`橙色`）判档，**不看边框颜色** ——
        #       只实测过紫(Hue141)/蓝(Hue98)，**橙没见过** ⇒ 写死颜色会错 ✗
        #     ⚠ **蓝档不停**（用户只说紫+橙 ✓）⇒ 判据里**不写「蓝色」** ✓
        if '元素' in _c['name']:
            _pf = bool((flags or {}).get('stop_elem_purple', True))
            _of = bool((flags or {}).get('stop_elem_orange', True))
            # ⭐ 2026-10-10 **把位阶写进日志**（真机那次"选了元素却没停"无法判断是蓝档
            #   还是判据漏了 —— 因为动画帧没留下文案 ✗）⇒ 下次一眼可判 ✓
            _tier11 = ('橙色' if '橙色' in _blob else
                       ('紫色' if '紫色' in _blob else
                        ('蓝色' if '蓝色' in _blob else '**未读到位阶词**')))
            log.append({'foretell': 'elem_tier', 'name': _c['name'],
                        'tier_word': _tier11,
                        'stop_purple': _pf, 'stop_orange': _of,
                        'eff': (_c.get('eff') or '')[:40]})
            if '橙色' in _blob and _of:
                _stop_why = '元素·橙色'
                break
            if '紫色' in _blob and _pf:
                _stop_why = '元素·紫色'
                break
            # ⚠ **蓝档 / 关了开关** ⇒ 不停，也不 break
            #   （继续看下一张卡 —— 别的卡也可能是"幸运"之类 ✓）
    if _stop_why:
        out['stop'] = _stop_why
        out['picked'] = []              # ⭐ **一张都没点**（面板原样留着 ✓）
        out['acts'] = ['stop_before_pick']
        log.append({'foretell': 'stop_before_pick', 'why': _stop_why,
                    'cards': [c['name'] for c in cards],
                    'note': '判停提到点卡之前 => 面板保持原样 ✓'})
        say('      · ⚠ 抽到【%s】⇒ **立即停止**（**不选卡、不点确定**，面板原样留着）'
            % _stop_why)
        log.append({'foretell': 'stop_requested', 'why': _stop_why})
        return out

    # ── 点选（多选：逐张点）──
    for c in pick:
        bot.tap_dlg(c['x'], c['y'], wait=1.4)
        log.append({'foretell': 'pick', 'name': c['name'],
                    'at': [c['x'], c['y']], 'tier': c['tier']})
        out['picked'].append(c['name'])

    # ⛔⛔ 2026-10-13 **旧判停块已删**（它排在"点卡"之后 ⇒ 见上面那段长注释）
    #   新判停已**提到点卡之前**并 `return` ⇒ 这里再判一次是**死代码** ✗
    #   ⚠ 留着更坏：它会走到「点确定」⇒ 万一前面漏判，它会**静默**填上 `out['stop']`
    #     而那时卡已选、确定已点 ⇒ **假的"立即停止"** ✗（正是用户报的那个现象）

    # ⛔⛔⛔ 2026-10-19 **先处理「预言重复选择」提示弹窗**（用户报「弹出没有见过的弹窗」）
    #   ---- 真机现场（`_imgs/now_screen.png`，设备 16448）----
    #     点完「和平」后游戏先弹：
    #        提示
    #        和平已有紫色同名预言，
    #        重复选择会将其覆盖。
    #        [取消(204,742)]  [确定(516,742)]
    #   ---- 为什么会卡死（就在下面三行）----
    #     `_find_text_btn(b, ('确定',), ymin=820, ymax=960)` **只找 y 820~960**
    #     而这个弹窗的「确定」在 **y=742** ⇒ **被 ymin 直接排除** ✗
    #     ⇒ 找不到 ⇒ 退回 `FORETELL['ok']=(360,888)`
    #     ⇒ 但弹窗只到 y≈800 ⇒ (360,888) 点在**弹窗下方空白**
    #     ⇒ 弹窗不消失 ⇒ 后面所有点击全打在弹窗上 ⇒ **卡死** ✗✗
    #   ---- 修法 ----
    #     点完卡就**先问一句**"是不是弹了重复选择提示"（`_foretell_dup_confirm`）
    #     是 ⇒ 点它的「确定」＝**同意覆盖**（用户要的就是"选更好的那张" ✓）
    #     ⚠ **绝不点「取消」** —— 那等于这一次选择白做 ✗
    _dup = False
    try:
        _dup = _foretell_dup_confirm(b, log)
    except Exception as _edu:               # noqa: BLE001
        log.append({'foretell': 'dup_probe_err', 'e': repr(_edu)[:80]})

    # ── 点「确定」（主面板）──
    if _dup:
        # 弹窗已经点掉 ⇒ 主面板的「确定」位置没变，但**别再用被抓的旧帧** ✗
        try:
            _invalidate(b)
        except Exception:                   # noqa: BLE001
            pass
        p = _find_text_btn(b, ('确定',), ymin=820, ymax=960)
        at = (p[0], p[1]) if p else FORETELL['ok']
        if _has(_items(b), FORETELL['title']):
            bot.tap_dlg(at[0], at[1], wait=2.2)
            log.append({'foretell': 'ok', 'at': list(at),
                        'src': 'ocr' if p else 'fallback', 'after_dup': True})
        else:
            log.append({'foretell': 'ok_skipped_panel_gone'})
    else:
        p = _find_text_btn(b, ('确定',), ymin=820, ymax=960)
        at = (p[0], p[1]) if p else FORETELL['ok']
        bot.tap_dlg(at[0], at[1], wait=2.2)
        log.append({'foretell': 'ok', 'at': list(at),
                    'src': 'ocr' if p else 'fallback'})
    out['acts'] = ['pick%d' % len(pick), 'ok']

    # ⚠ 实测：**点确定后没有结果框**（与勇者之墓不同 ✓）⇒ 不需要关结果框
    if _has(_items(b), FORETELL['title']):
        _univ_close(b, log, 'foretell_tail')
    log.append({'foretell': 'done', 'picked': out['picked'], 'stop': out['stop']})
    return out


# ── `Foretell` 表的「数值 → 品阶」对照（用于**不靠颜色**判品阶 ✓）──────────
#   数据来源：`server_datatable.json` 的 `Foretell` 表（54 行，实测）
#   规律：同一功能的 4 档 = B/A/S/SS，且 Value 严格递增（100/200/300/500 等）
_FORETELL_VALUE_TIER = {
    '丰收': {100: 2, 200: 3, 300: 4, 500: 5},
    '藏宝': {100: 2, 200: 3, 300: 4, 500: 5},
    '武装': {100: 2, 200: 3, 300: 4, 500: 5},
    '命运': {5: 2, 10: 3, 15: 4, 20: 5},
}
# 「至少是 X 位阶」型：颜色/位阶直接写在文案里 ⇒ 按词判
_FORETELL_WORD_TIER = {'蓝': 2, '紫': 3, '橙': 4}
# 只有单一档位的（没得比）⇒ 给个中位值，排序时不影响同类的相对次序
_FORETELL_FIXED_TIER = {
    '掉宝': 4, '宝库': 4, '圣域': 3, '战场': 3, '精灵': 3, '财富': 3,
    '黄金': 3, '传承': 5, '幸运': 5, '祥和': 2, '奇观': 2, '伏击': 4,
    '勇者': 2, '机遇': 2, '魔法': 5, '和平': 3, '强敌': 2, '元素': 2,
    '路标': 2, '秘藏': 2, '神兵': 2, '奇遇': 2,
}


def _foretell_tier(name, eff):
    """从「卡名 + 效果文案」推**品阶**（1=C … 5=SS）

    ⚠ 为什么不看边框颜色：我只实测过 **紫=141(A) / 蓝=98(B)** 两种，
      S/SS 的颜色**没见过** ⇒ 写死颜色会错 ✗
    ⇒ 改用**文案里的数值/位阶词**反查（数据表里 `Value` 与 `Step` 一一对应 ✓）
    """
    import re as _re
    try:
        # ① 数值型（丰收/藏宝/武装/命运）
        m = _re.search(r'\+(\d+)%', eff or '')
        if m and name in _FORETELL_VALUE_TIER:
            return _FORETELL_VALUE_TIER[name].get(int(m.group(1)), 2)
        m2 = _re.search(r'至少为(\d+)点', eff or '')
        if m2 and name in _FORETELL_VALUE_TIER:
            return _FORETELL_VALUE_TIER[name].get(int(m2.group(1)), 2)
        # ② 位阶词型（神兵/秘藏/强敌/路标/元素/掉宝/奇遇…）
        for w, tv in _FORETELL_WORD_TIER.items():
            if ('至少是%s' % w) in (eff or '') or ('%s色位阶' % w) in (eff or ''):
                return tv
        # ③ 单档位型
        return _FORETELL_FIXED_TIER.get(name, 2)
    except Exception:       # noqa: BLE001
        return 2


# ══════════════════════════════════════════════════════════════════════════════
# ④ 金属宝箱怪 / 机巧宝箱怪（SP=2）—— 2026-10-08 真机实测 + 用户口径
#
#   用户口径（原话，**权威**）：
#     「**一般只买 8 草的，宝箱怪默认不勾选，勾选就自动买 8 草的**」
#
#   落地三条：
#     ① 宝箱怪**默认不勾选** ⇒ 已是现状（`targets_cfg`：enabled=False/blocked=True ✓）
#     ② 勾选后才处理 ⇒ 既有设计（`is_blocked = not enabled` ✓ 不用改代码）
#     ③ **只买 8 草的**（= 面板最高档 S 级）＋ **不刷新** ＋ **草不够就不买**
#
#   ⭐ 实测价格表（源码 `GetCloverPrice(step) = 1 << (Step-1)`，真机面板一致）：
#        C=1 / B=2 / A=4 / **S=8**（SS=16，但**宝箱怪不出 SS** ⇒ 8 就是最高 ✓）
#      ⇒ 「只买 8 草的」= **只买最高档** ✓ 与"只买最好的"自洽 ✓
#
#   ⚠⚠ 购买是**两步**（真机实测，我第一版猜错过）：
#        点商品卡 ⇒ **弹详情页**（不是买）✗
#        点详情页**右下角价格按钮** ⇒ 才真的买 ✓
#      ⇒ 详情页购买按钮实测 `(586, 1053)`；但**仍优先 OCR**（与勇者之墓同一教训 ✓）
#
#   ⚠ 「取消追踪」`(160,1053)` 是**追踪功能**，**不是取消购买** ✗ 别点错
# ══════════════════════════════════════════════════════════════════════════════

# 四列商品 —— 2026-10-08 **放大 OCR 后重新标定**（原来那组偏了 ~20px ✗）
#   ⚠ 为什么之前读不到左边两列：**价格数字太小，整屏 OCR 漏检** ✗
#     实测（`runs/sptest/cal_now.png`）：
#       · 整屏 OCR        ⇒ 只读到 `8@448 / 4@596`（**少了左边两列**）✗
#       · **放大 3 倍**再 OCR ⇒ **四个全读到** `8@145 / 4@290 / 8@433 / 4@578` ✓
#   ⇒ 价格一律**放大后再 OCR**（见 `_mimic_read_prices` ✓）
#   草图标中心（绿色像素簇）：`130 / 274 / 418 / 562`
MIMIC_CARD_X = (127, 271, 415, 559)   # 四列**商品卡中心**（= 草图标中心 − 3）
MIMIC_PRICE_X = (145, 290, 433, 578)  # 四列**价格数字**中心（放大 OCR 实测 ✓）
MIMIC_CARD_Y = 675          # 商品卡点击 y（实测点中 ✓）
MIMIC_PRICE_Y = 730         # 价格行 y（立体 OCR 实测 730~731 ✓）
MIMIC_BUY_BTN = (586, 1053)  # 详情页**右下角价格按钮**（实测买入成功 ✓）
MIMIC_BUY_Y_RANGE = (830, 1110)  # 购买键的 y 范围（⚠ 实测详情页那个 `8` 在 y≈875，
                                 #   我第一版写 1000~1110 太严 ⇒ 找不到 ✗）
MIMIC_REFRESH = (598, 820)   # 「刷新 1 草」——**不点**（用户口径）✓
MIMIC_TARGET_PRICE = 8       # ⭐ **只买 8 草的**（用户口径 ✓）
# ⭐⭐ 2026-10-08 用户口径（原话）：「**从左开始数第一个必定是装备**」✓
#   ── 我上一版错在哪 ──────────────────────────────────
#     我只按"价格 == 8"筛 ⇒ ⇒ 把**第 3 列那个 8 草的符文**也买了 ✗
#     用户当场指出：「**不是说只买8草装备吗，为什么去买符文了**」✓
#   ── 口径 ────────────────────────────────────────
#     **从左数第一个**（`MIMIC_CARD_X[0]`）**必定是装备** ⇒ 只买它 ✓
#     （不再靠"价格==8"筛；即：装备且 8 草 ⇒ 买；装备但非 8 草 ⇒ 不买 ✓）
MIMIC_EQUIP_COL = 0          # 第 1 列（0-based）= 装备列 ✓
MIMIC_OCR_SCALE = 3          # 价格行**放大倍数**（放大才读得到左边两列 ✓）


def _mimic_read_prices(bot, log=None, rounds=5, sec=0.8):
    """**带重试 + 放大**读面板上四个商品的**价格**（幸运草数）-> ([(x, 价格)...], 轮数)

    ⭐ 两个都要（各有实测依据）：
      · **重试**：面板**正在弹出动画中**时商品/价格还没画出来（本项目反复栽的坑 ✗）
      · **放大 3 倍**：价格数字太小，**整屏 OCR 会漏掉左边两列** ✗
        实测：整屏只读到 `8@448 / 4@596`；放大 3 倍后**四个全读到** ✓
        （`MIMIC_OCR_SCALE`；只放大**价格行那一条带**，代价很小 ✓）

    ⚠ 价格是**单个数字**（1/2/4/8/16）⇒ 只认**纯数字**且 y 落在价格行 ✓
    """
    import re as _re
    for rd in range(1, rounds + 1):
        if rd > 1:
            try:
                import time as _t
                _t.sleep(sec)
            except Exception:       # noqa: BLE001
                pass
        try:
            _invalidate(bot)
        except Exception:           # noqa: BLE001
            pass
        # ⚠ 先 snap 拿帧（放大要自己裁图 ⇒ 不能直接吃 `_items` 的坐标 ✓）
        try:
            bot.snap('bp')
        except Exception:           # noqa: BLE001
            pass
        out = []
        has = False
        try:
            it = _items(bot)
            has = any(('未拥有' in (t.get('text') or '')) or
                      ('已售罄' in (t.get('text') or '')) for t in it)
        except Exception:           # noqa: BLE001
            it = []
        # ── 放大价格行再 OCR（治"漏掉左边两列" ✗）──
        try:
            _out2 = _mimic_prices_zoomed(bot)
            if _out2:
                out = _out2
        except Exception as _e:     # noqa: BLE001
            if log is not None:
                log.append({'mimic': 'price_zoom_err', 'round': rd,
                            'e': repr(_e)[:70]})
        # ── 兜底：放大也失败 ⇒ 用整屏 `_items` 的数字（可能只有 2 列 ⚠）──
        if not out:
            for t in it:
                s = (t.get('text') or '').strip()
                cy = t.get('cy') or 0
                if not _re.fullmatch(r'\d{1,2}', s):
                    continue
                if not (MIMIC_PRICE_Y - 26 <= cy <= MIMIC_PRICE_Y + 26):
                    continue
                out.append((t.get('cx') or 0, int(s)))
        if out:
            out.sort()
            if log is not None:
                log.append({'mimic': 'prices_ok', 'round': rd, 'prices': out,
                            'has_label': bool(has),
                            'zoomed': bool(_out2) if '_out2' in dir() else False})
            return out, rd
    return [], rounds


def _mimic_prices_zoomed(bot):
    """把**价格行那一条带**放大 `MIMIC_OCR_SCALE` 倍再 OCR -> [(x, 价格)...]

    ⭐ 为什么必须放大：整屏 OCR **读不到左边两列价格**（数字太小）✗
      实测（`runs/sptest/cal_now.png`）：
        整屏        ⇒ `8@448 / 4@596`（2 个）
        放大 3 倍   ⇒ `8@145 / 4@290 / 8@433 / 4@578`（**4 个全中** ✓）
    ⚠ 只放大**价格行那 65px**（不是整个面板）⇒ 代价小、也不会引入别处的误读 ✓
    ⚠ 反算坐标：`原图 x = 放大图 x / scale`（y 同理，再 + 带起点 ✓）
    """
    import cv2
    import numpy as np
    import re as _re
    # ⚠ PC 版 Bot：`img()` 取当前帧、`last_img` 是上一次截图 ✓（没有 `ocr_file`）
    img = None
    for getter in ('img', 'last_img'):
        try:
            v = getattr(bot, getter)
            img = v() if callable(v) else v
        except Exception:       # noqa: BLE001
            img = None
        if img is not None:
            break
    if img is None:
        return []
    y0 = int(MIMIC_PRICE_Y - 33)
    y1 = int(MIMIC_PRICE_Y + 35)
    band = img[max(0, y0):y1, :]
    if band.size == 0:
        return []
    sc = int(MIMIC_OCR_SCALE)
    big = cv2.resize(band, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_mimic_price.png')
    try:
        cv2.imwrite(tmp, big)
    except Exception:       # noqa: BLE001
        return []
    # 走 RapidOCR 直连（与 prod 同一个引擎 ✓；`Bot.ocr` 只吃整帧/带，不吃临时文件）
    try:
        from rapidocr_onnxruntime import RapidOCR
        _eng = (_mimic_prices_zoomed.eng
                if hasattr(_mimic_prices_zoomed, 'eng') else RapidOCR())
        _mimic_prices_zoomed.eng = _eng
        res, _ = _eng(tmp)
    except Exception:       # noqa: BLE001
        return []
    out = []
    for box, txt, conf in (res or []):
        s = str(txt).strip()
        m = _re.fullmatch(r'#?(\d{1,2})', s)     # ⚠ 放大后常读成 `#8` ⇒ 允许前缀 #
        if not m:
            continue
        xs = [q[0] for q in box]
        cx = int(sum(xs) / 4 / sc)               # ⭐ 反算回原图 ✓
        out.append((cx, int(m.group(1))))
    return out


def _mimic_buy_one(bot, log, card_x):
    """买**某一列**的商品：点卡看详情 → 点右下角价格按钮 → 关结果框

    -> True 买到 ／ False 没买到
    ⚠ 每一步都**核实**（不盲点）：点卡后必须确认"详情页出现了"才点购买 ✓
    """
    # ① 点商品卡（弹详情）
    bot.tap_dlg(card_x, MIMIC_CARD_Y, wait=2.0)
    log.append({'mimic': 'tap_card', 'x': card_x, 'y': MIMIC_CARD_Y})

    # ② 确认详情页：必须能看到「尚未拥有/已拥有」+ 价格按钮
    det = _find_text_btn(bot, ('尚未拥有', '已拥有', '未拥有'), 200, 500)
    # ③ 找**购买按钮**（右下角的价格数字）—— **优先 OCR**，落回固定坐标 ✓
    btn = None
    for rd in range(1, 4):
        if rd > 1:
            try:
                import time as _t
                _t.sleep(0.7)
            except Exception:       # noqa: BLE001
                pass
            try:
                _invalidate(bot)
            except Exception:       # noqa: BLE001
                pass
        it = _items(bot)
        best = None
        for t in it:
            s = (t.get('text') or '').strip()
            cy = t.get('cy') or 0
            if s in ('确定', '返回'):
                continue                    # 别把结果框按钮当购买键 ✗
            if s not in ('1', '2', '4', '8', '16', '免费'):
                continue
            if not (MIMIC_BUY_Y_RANGE[0] <= cy <= MIMIC_BUY_Y_RANGE[1]):
                continue
            if (t.get('cx') or 0) < 380:     # ⚠ 左边是「取消追踪」⇒ 排除 ✓
                continue
            best = (t.get('cx'), t.get('cy'), s)
            break
        if best:
            btn = best
            break
    if btn:
        at = (btn[0], btn[1])
        src = 'ocr'
    else:
        at = MIMIC_BUY_BTN
        src = 'fallback'
    log.append({'mimic': 'detail', 'has_detail': bool(det),
                'buy_at': list(at), 'src': src})
    if det is None and not btn:
        say('      · ⚠ 详情页没认出来、也没找到购买键 ⇒ **不盲点**（放弃这一件）')
        return False

    bot.tap_dlg(at[0], at[1], wait=2.4)
    log.append({'mimic': 'tap_buy', 'at': list(at)})

    # ④ 关结果框（「获得新装备！」→ 点「返回」；**带重试** ✓ 同勇者之墓教训）
    for rd in range(1, 5):
        if rd > 1:
            try:
                import time as _t
                _t.sleep(0.8)
            except Exception:       # noqa: BLE001
                pass
            try:
                _invalidate(bot)
            except Exception:       # noqa: BLE001
                pass
        p = _find_text_btn(bot, ('返回', '确定'), 560, 900)
        if p:
            bot.tap_dlg(p[0], p[1], wait=2.0)
            log.append({'mimic': 'close_reward', 'at': [p[0], p[1]],
                        'text': p[2], 'round': rd})
            return True
    log.append({'mimic': 'close_reward_fail'})
    return True         # 买是买到了；结果框没关掉**如实记**（不假装 ✓）


def mimic_flow(bot, log, flags=None):
    """金属宝箱怪 / 机巧宝箱怪 —— **只买 8 草的**（用户 2026-10-08 口径）

    -> dict：`{'acts': [...], 'bought': [...], 'skip': 原因}`

    ⭐ 用户原话：「**一般只买 8 草的，宝箱怪默认不勾选，勾选就自动买 8 草的**」

    流程（真机实测 `runs/spec_dev/mimic_panel.png` / `buy_*.png`）：
        面板（4 件商品，价格 8/4/8/4）
        → 逐列看价格，**只挑 8 草的**
        → 点卡（弹详情）→ 点右下角价格按钮（真买）→ 关结果框
        → **不刷新**（刷新 1 草，用户没说刷 ✓）

    ⚠ **草量闸门**：买之前必须 `草 >= 8`（不够就**不买**、只关面板 ✓）
       —— 与既有 `CLOVER_MIN_REROLL=8`（摇色子）**同数不同义**，
          那条是"摇色子"的闸门 ⇒ **不能挪用语义** ✗ 这里单独判 ✓
    """
    out = {'acts': [], 'bought': [], 'skip': None}
    b = _proxy(bot)
    _vstep(b, log, 'mimic_start')

    prices, rounds = _mimic_read_prices(b, log)
    if not prices:
        log.append({'mimic': 'panel_missing_or_timeout', 'rounds': rounds})
        say('      · ⚠ 宝箱怪面板读不到商品/价格 ⇒ 不盲点、关面板（下轮再来）')
        _univ_close(b, log, 'mimic_nopanel')
        out['skip'] = 'no_prices'
        return out
    say('      · 宝箱怪面板：%d 件商品，价格（x,草）= %s'
        % (len(prices), prices))

    # ⭐⭐ 选品口径（用户 2026-10-08，**权威**）：
    #   ① 「**从左开始数第一个必定是装备**」⇒ **只买第 1 列** ✓
    #   ② 「**一般只买 8 草的**」⇒ 第 1 列的价格**必须是 8** 才买 ✓
    #   ⛔ 我上一版只按"价格==8"筛 ⇒ 把第 3 列那个 **8 草的符文**也买了 ✗
    #      （用户当场指出：「不是说只买8草装备吗，为什么去买符文了」✓）
    eq_col = MIMIC_EQUIP_COL
    eq_x = MIMIC_CARD_X[eq_col]
    # 找出**第 1 列**（装备列）的价格 = 离 eq_x 最近的那个价格
    eq_price = None
    if prices:
        px, pv = min(prices, key=lambda t: abs(t[0] - eq_x))
        eq_price = pv
    log.append({'mimic': 'equip_col', 'col': eq_col, 'card_x': eq_x,
                'price': eq_price, 'prices': prices,
                'need': MIMIC_TARGET_PRICE})

    if eq_price != MIMIC_TARGET_PRICE:
        say('      · 装备列（第 %d 列）价格是 %s，不是 %d 草 ⇒ **不买**'
            '（用户口径：只买 %d 草的装备）'
            % (eq_col + 1, eq_price, MIMIC_TARGET_PRICE, MIMIC_TARGET_PRICE))
        out['skip'] = 'equip_not_target_price'
        _univ_close(b, log, 'mimic_price')
        return out
    want = [eq_x]
    say('      · 装备列（第 1 列 x=%d）= %d 草 ⇒ **买它**（只买装备 ✓）'
        % (eq_x, eq_price))
    if not want:
        say('      · 没有 %d 草的商品 ⇒ **不买**（用户口径：只买 %d 草的）'
            % (MIMIC_TARGET_PRICE, MIMIC_TARGET_PRICE))
        out['skip'] = 'no_target_price'
        _univ_close(b, log, 'mimic_notarget')
        return out

    # ⚠ 草量闸门（读不到草 ⇒ **保守不买**，避免买不起白点）
    try:
        clv = _clover_now(b)
    except Exception:       # noqa: BLE001
        clv = None
    log.append({'mimic': 'clover', 'now': clv, 'need': MIMIC_TARGET_PRICE})
    if clv is not None and clv < MIMIC_TARGET_PRICE:
        say('      · ⚠ 幸运草 %d < %d ⇒ **不买**（只关面板 ✓）'
            % (clv, MIMIC_TARGET_PRICE))
        out['skip'] = 'low_clover'
        _univ_close(b, log, 'mimic_lowclover')
        return out

    # ── 逐件买（只买 8 草的）──
    for x in want:
        if _mimic_buy_one(b, log, x):
            out['bought'].append(x)
            out['acts'].append('buy@%d' % x)
            say('      · 买到一件（x=%d，8 草）✓' % x)
        else:
            say('      · x=%d 这件没买成（见日志）' % x)

    # ── 收尾：关面板（**万能点位** ✓ 用户口径：宝箱怪面板能吃万能关闭）──
    if _has(_items(b), '金属宝箱怪') or _has(_items(b), '机巧宝箱怪'):
        _univ_close(b, log, 'mimic_tail')
    log.append({'mimic': 'done', 'bought': out['bought'], 'acts': out['acts']})
    return out


# ══════════════════════════════════════════════════════════════════════════
# 传承祭坛（SpecialSpot == 4）—— 2026-10-11 真机采到面板后实现
# ══════════════════════════════════════════════════════════════════════════
#   面板铁证：`runs/acc3/shrine_panel_r-1.png`（实例B那把，13:45:59 采到 ✓）
#   面板长这样（720×1280 设备系）：
#       标题「传承祭坛」              (461, 336)
#       说明「我来帮你激活潜藏在装备中的传承之力，传承会使装备拥有的羁绊等级+1。」
#       【选择装备】                  (360, 540)
#       装备网格 **3 行 × 6 列 = 18 件**（是**你已有的装备**，不是新商品 ✓）
#         首格中心 (111, 622)｜列距 99｜行距 100（全部实测，见下）
#       底部：(157,908) 筛选 ｜ (250,908) 刷新↻ ｜ (601,908) 价格「30000」
#       ✗ 关闭 (628, 335)
#
#   ⭐⭐⭐ 用户口径（2026-10-11，原话）：
#     · 「**直接点右下角的三万买了就行**」
#     · 「**识别一下，是30000就买，不然不买**」
#   ⇒ 所以判据**只看右下角价格**：== 30000 就买（用默认选中的第 1 件），否则**不买** ✓
#
#   ⚠ 与「勇者之墓」的区别：那边是**三选一奖励**；这边是**选自己的装备 + 花金币激活传承**
#   ⚠ 与「旅行商人/黄金宝库」的区别：那些是**买新东西**；这边是**升级已有装备** ✓
SHRINE_GX0 = 111          # 第 1 列中心（绿框实测 ✓）
SHRINE_GY0 = 622          # 第 1 行中心（绿框实测 ✓）
SHRINE_PITCH_X = 99       # 列距（实测 ✓）
SHRINE_PITCH_Y = 100      # 行距（实测 ✓）
SHRINE_ROWS = 3
SHRINE_COLS = 6
SHRINE_PRICE = 30000      # ⭐ **只买 30000 这档**（用户口径 ✓）
SHRINE_PRICE_XY = (601, 908)   # 「30000」文字中心（OCR conf=1.00 ✓）
SHRINE_BUY_XY = (594, 909)     # 价格按钮**点击点**（按钮底实测中心 ✓）
SHRINE_X_XY = (628, 335)       # ✗ 关闭（红像素块中心实测 ✓）
SHRINE_FILTER_XY = (157, 908)  # 「筛选」（**不点** —— 用户没说筛 ✓）
SHRINE_REFRESH_XY = (250, 908)  # ↻ 刷新（**不点** ✓）
SHRINE_TITLE = '传承祭坛'


def shrine_cells():
    """18 个格中心（3 行 × 6 列，**按行优先** ✓）"""
    return [(SHRINE_GX0 + c * SHRINE_PITCH_X,
             SHRINE_GY0 + r * SHRINE_PITCH_Y)
            for r in range(SHRINE_ROWS) for c in range(SHRINE_COLS)]


def _shrine_price(bot, log=None):
    """读右下角价格 —— 返回 int 或 None（**读不到返回 None，调用方不买** ✓）

    ⚠ 口径（用户 2026-10-11）：「**识别一下，是30000就买，不然不买**」
      ⇒ 读不到时**必须当"不能买"**（不是"猜一个"）✓
    """
    out = None
    try:
        its = bot.ocr(band=(870, 950), tag='shrine_price')
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'shrine': 'price_ocr_fail', 'e': repr(e)[:90]})
        return None
    # 价格数字在 x≈601 附近（左边 x≈543 那个金币图标会读成 `@` 之类，忽略 ✓）
    cands = []
    for t in (its or []):
        s = str(t.get('text') or '').strip()
        cx = int(t.get('cx') or 0)
        # ⚠ 只认**右侧**那块（x > 560）：筛选(157)/刷新(259) 都在左边 ⇒ 天然排除 ✓
        if cx < 560:
            continue
        d = ''.join(ch for ch in s if ch.isdigit())
        if d:
            cands.append((abs(cx - SHRINE_PRICE_XY[0]), int(d), s, cx))
    if cands:
        cands.sort()
        out = cands[0][1]
    if log is not None:
        log.append({'shrine': 'price_read', 'value': out,
                    'cands': [(c[1], c[3]) for c in cands][:4]})
    return out


def shrine_flow(bot, log, flags=None):
    """传承祭坛 —— **右下角是 30000 就买**（用户 2026-10-11 口径 ✓）

    -> dict：`{'acts': [...], 'bought': bool, 'skip': 原因}`

    流程：
        ① 读右下角价格
        ② `!= 30000` ⇒ **不买**，直接关面板 ✓
        ③ `== 30000` ⇒ 点右下角按钮买（**用面板默认选中的第 1 件**）✓
        ④ 关面板（✗ 或万能关闭）

    ⚠ **不点**「筛选」「刷新」（用户没说，且刷新要花钱 ✗）
    ⚠ 买之前**不点格子** —— 面板默认已选中第 1 件（绿框实测 ✓）
      且点格子会打开**详情页**（与宝库那次同一个坑 ✗）
    """
    out = {'acts': [], 'bought': False, 'skip': None}
    b = _proxy(bot)
    _vstep(b, log, 'shrine_start')

    it = _items(b)
    _pl = [t.get('text') for t in (it or [])][:14]
    if not _has(it, SHRINE_TITLE):
        log.append({'shrine': 'panel_missing', 'texts': _pl})
        say('      · ⚠ 读不到「传承祭坛」标题 ⇒ 不盲点、关面板（下轮再来）')
        _univ_close(b, log, 'shrine_nopanel')
        out['skip'] = 'no_panel'
        return out

    price = _shrine_price(b, log)
    say('      · 传承祭坛面板：右下角价格 = %s（要 %d 才买）'
        % (price, SHRINE_PRICE))

    if price != SHRINE_PRICE:
        say('      · 价格不是 %d ⇒ **不买**（用户口径：是 %d 就买，不然不买 ✓）'
            % (SHRINE_PRICE, SHRINE_PRICE))
        out['skip'] = 'price_not_target'
        log.append({'shrine': 'skip', 'why': 'price_not_target', 'price': price})
        _shrine_close(b, log)
        return out

    # ── 是 30000 ⇒ 买 ──
    log.append({'shrine': 'will_buy', 'at': list(SHRINE_BUY_XY),
                'price': price})
    say('      · 价格 = %d ⇒ **买**（点右下角 %s）'
        % (price, SHRINE_BUY_XY))
    try:
        b.tap_dlg(SHRINE_BUY_XY[0], SHRINE_BUY_XY[1], wait=2.0)
        out['acts'].append('buy@%s' % (SHRINE_BUY_XY,))
        out['bought'] = True
        say('      · 已点购买 ⇒ 等结果')
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'buy_tap_fail', 'e': repr(e)[:90]})
        out['skip'] = 'tap_fail'

    # ⛔⛔⛔ 2026-10-11 **补上「确认框」这一步**（我第一版漏了 ✗）
    #   ---- 游戏源码铁证（`_ref_game_src/HeritageBlockPanel.cs:66-87`）----
    #       public void OnConfirmClicked()   // = 点右下角价格按钮
    #       {
    #           if (gold < price) { GoldPurchasePrompt(); return; }   // 钱不够 ⇒ 充值提示
    #           ActionPrompt component = ...ShowPopPanel(ActionPrompt_GEN...);  // ⚠ **弹确认框**
    #           component.confirmFunc = delegate { PruchaseHeritage(price); };  // 确认后才真买
    #       }
    #   ⇒ 点价格按钮**只是弹确认框**，**必须再点「确定」才真扣钱/真激活** ✗
    #   ⇒ 我第一版点完价格就以为买到了 ⇒ **实际什么都没发生** ✗✗
    #   ---- 用既有的 `_confirm()`（宝库那条链早就在用同款 ✓）----
    #     · 它 **只点「确定」、绝不点「取消」** ✓（点错会浪费钱 —— 这条是硬要求）
    #     · 它按 OCR 找「确定」（`cy > 800`），**不写死坐标** ✓
    #       （`_confirm` 的注释写着：手上没有确认框真机帧 ⇒ **禁止瞎猜坐标** ✓）
    #   ⚠ 顺带把「金币够不够」也如实记下来：源码里钱不够**不会**弹确认框、
    #     而是弹充值提示 ⇒ 那时 `_confirm` 找不到「确定」⇒ `bought` 要改成 False ✓
    _had_confirm = False
    try:
        _had_confirm = bool(_confirm(b, log, 'shrine_buy'))
    except Exception as _ce:    # noqa: BLE001
        log.append({'shrine': 'confirm_fail', 'e': repr(_ce)[:90]})
    log.append({'shrine': 'confirm_step', 'got': _had_confirm,
                'note': '源码：点价格 ⇒ 弹确认框 ⇒ 点「确定」才真买 ✓'})
    if out['bought'] and not _had_confirm:
        # ⚠ **没等到确认框** ⇒ 多半是"金币不够"（源码走 `GoldPurchasePrompt`）
        #   ⇒ **不许谎报"买到了"** ✗ 如实改掉，交给下次/人工 ✓
        out['bought'] = False
        out['skip'] = 'no_confirm_dialog'
        say('      · ⚠ 点完价格**没等到确认框** ⇒ 多半金币不够（源码：钱不够弹充值）'
            '⇒ **不算买到**（如实记账 ✓）')

    # ── 关面板（买了之后可能弹「获得…」，用万能关闭兜 ✓）──
    _shrine_close(b, log)
    log.append({'shrine': 'done', 'bought': out['bought'], 'acts': out['acts']})
    return out


def _shrine_close(bot, log, wait=1.6):
    """关传承祭坛面板：**先看它还在不在**，在才点 ✗（不许盲点 ✗）

    ⛔⛔ 2026-10-11 **为什么必须先判"还在不在"**（游戏源码铁证 ✗）
      `HeritageBlockPanel.PruchaseHeritage()` 尾段（`HeritageBlockPanel.cs:110-114`）：
          if (isExplore) {
              Singleton<ExploreEnd>.Self.FinishBlock(block, SingleBlock);  // 格子被消耗
              Singleton<UIManager>.Self.PopAllPopPanel();                  // ⚠ **面板自己关**
          }
      ⇒ 买成功后**面板会自己关掉**、格子也被消耗 ✓
      ⇒ 若这时还无条件点 ✗ `(628,335)` ⇒ **点在空棋盘上** ✗（可能误点开别的格）
      ⇒ 所以：**先取帧确认标题还在**，在才关 ✓
    ⚠ 而且「没关掉」也要**如实记**（不许静默 ✓）
    """
    try:
        _it = _items(bot)
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_check_fail', 'e': repr(e)[:80]})
        return
    if not (_has(_it, SHRINE_TITLE) or _has(_it, '选择装备')):
        # ⭐ 面板已经自己关了（买成功后的正常情况 ✓）⇒ **一下都不点** ✓
        log.append({'shrine': 'already_closed', 'note': '面板已自己关（源码 PopAllPopPanel ✓）'})
        return
    try:
        bot.tap_dlg(SHRINE_X_XY[0], SHRINE_X_XY[1], wait=wait)
        log.append({'shrine': 'close_x', 'at': list(SHRINE_X_XY)})
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_x_fail', 'e': repr(e)[:80]})
    try:
        _it2 = _items(bot)
        if _has(_it2, SHRINE_TITLE) or _has(_it2, '选择装备'):
            log.append({'shrine': 'close_x_ineffective', 'retry': 'univ'})
            _univ_close(bot, log, 'shrine_tail')
        else:
            log.append({'shrine': 'close_ok'})
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_verify_fail', 'e': repr(e)[:80]})
        try:
            _univ_close(bot, log, 'shrine_tail2')
        except Exception:       # noqa: BLE001
            pass


def _clover_now(bot):
    """读当前幸运草数（HUD）—— 读不到返回 None（调用方**保守处理** ✓）

    ⚠ 复用 `explore_loop` 的读数口径（HUD 那一行），避免两处各写一份漂移 ✗
    """
    try:
        import explore_loop as _EL
        it = _items(bot)
        return _EL.clover_count(it)
    except Exception:       # noqa: BLE001
        return None

