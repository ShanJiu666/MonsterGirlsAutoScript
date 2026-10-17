# -*- coding: utf-8 -*-
"""bot_gui_ui.theme · UI 样式层 —— **全项目唯一的色值 / 字体 / 间距来源**

出处（先读再改；别在这里"顺手"调颜色 ⚠）：
    · UI 重设计方案 **§4.5 视觉风格规范** ——
      主题 `clam` 底浅色、主色靛蓝 `#3F51B5`、成功绿 `#2E7D32`、警告橙 `#E65100`、
      危险红 `#C62828`、中性灰 `#616161` 文字 / `#F5F5F5` 卡底 / `#FFFFFF` 底；
      字体 UI 一律 `Microsoft YaHei UI`（正文 10 / 卡片数值 16 bold / 标题 13 bold /
      辅助 9 灰；日志与数据 `Consolas` 9）；
    · 同文档 **§4.3 整体布局** —— 窗口 1100×860、minsize 900×700、
      卡片 padding 12 / 卡片间距 8 / 页签内边距 10、按钮高 32（主按钮 40）；
    · 同文档 **§4.3 棋盘配色** —— 雾格灰 / 已揭示空地浅绿 / 内容格橙 / 营地蓝+🏕 /
      目标格靛蓝描边 2px / 拉黑格斜线纹 / 标记角标 5 色；
    · 同文档 **§4.5a 配色优化专项（2026-10-12 · WCAG 2.1 实测驱动）** —— ⭐ **v2 修订**
      按"19 个取色组合逐一实测对比度"定位 5 处不达标，**只改色值常量**（布局 / 组件结构 /
      样式名零改动）⇒ 各常量行尾的 `⭐ 05 §4.5a v2 清单第 N 项` 就是它的出处；
      修的是：次级灰字、警告文字的"文字/图形"语义拆分、雾格字、拉黑格底+斜纹、
      幸运草角标字；顺带把主色加深调浅一档（纯美观，非合规）✓
    · 同文档 **附录 E.2** —— 棋盘数据格式（1 基、键 `"行,列"`）。

⭐⭐ 为什么必须有这一层（= 痛点 P2「样式散落」的修法）：
    旧 `bot_gui.py`（1681 行裸 tkinter）里 `('Microsoft YaHei', 10)` 这类字面量
    出现 **30+ 处**、色值 `#2a7`/`#080`/`#a00`/`#048`/`#c60`/`#333`/`#555`/`#666`
    到处硬编码 ⇒ 改一处颜色要全文搜、还必然漏几处 ✗。
    ⇒ 从本文件起：`bot_gui_ui/` 下的组件文件里**不许再出现任何硬编码色值**，
      一律 `theme.C_XXX` ✓。

⚠ 纪律（GUI 跑在 pythonw，无控制台 ⇒ 抛了用户看不见）：
    本文件一切函数对坏数据**容错不抛**；`apply_theme` 整段 `try/except TclError` 兜底。

零第三方依赖：只用 `tkinter` / `tkinter.ttk` / 标准库 ✓（打包链路不许引新依赖）。
"""
import tkinter as tk
from tkinter import ttk

# ══════════════════════════════════════════════════════════════════════
# 一、色值（**唯一来源**；组件文件里不许再出现任何硬编码色值 ✓）
# ══════════════════════════════════════════════════════════════════════
C_PRIMARY = '#3F51B5'        # 主色靛蓝（主按钮 / 选中 / 计划序号 / 目标描边）
C_PRIMARY_D = '#3949AB'      # 主色加深（按下 / hover）⭐ 05 §4.5a v2 清单第 7 项
                             #   （原 `#303F9F` 过深、hover 反馈偏弱；白字 7.73:1 ✅）


def blend(c1, c2, t=0.5):
    """两色线性插值（`t=0` ⇒ `c1`，`t=1` ⇒ `c2`）⇒ `'#RRGGBB'`

    ⭐ 2026-10-12 为**伪抗锯齿**加的（见 `widgets._draw_order` 的"柔光晕"）：
      Tk 8.6 的 Canvas **没有抗锯齿**（实测 `-antialiasing` 不是合法选项 ✗）⇒
      斜线只能画成阶梯。用**在斜线下面先画一条更粗、更接近底色的同色线** ⇒
      阶梯被"染"成中间调 ⇒ 远看直、毛边明显减轻 ✓（这是 canvas 上的通行做法 ✓）
    ⚠ 认不出的色值 ⇒ 返回 `c1`（**绝不抛**；宁可没有晕也别把整盘画挂 ✗）
    """
    try:
        a, b = str(c1).lstrip('#'), str(c2).lstrip('#')
        if len(a) != 6 or len(b) != 6:
            return c1
        ia, ib = int(a, 16), int(b, 16)
        t = min(1.0, max(0.0, float(t)))
        out = 0
        for sh in (16, 8, 0):
            va, vb = (ia >> sh) & 0xFF, (ib >> sh) & 0xFF
            out |= int(round(va + (vb - va) * t)) << sh
        return '#%06X' % out
    except Exception:       # noqa: BLE001
        return c1
C_OK = '#2E7D32'             # 成功绿
C_WARN = '#BF360C'           # 警告 —— **文字**语义（`Warn.TLabel` 的 fg…）
                             #   ⭐ 05 §4.5a v2 清单第 2 项：原 `#E65100` 当正文只有
                             #   3.79:1（<AA 4.5）⇒ 换深橙红，白底 5.60 / 卡底 5.14 ✅
C_WARN_BG = '#E65100'        # 警告 —— **图形 / 底线 / 填充**语义（图表柱、警告边框…）
                             #   ⚠ 05 §4.5a v2 清单第 2 项的**另一半**：`C_WARN` 拆成
                             #   "文字"与"图形"两个常量（图形不适用 AA 文字判据，
                             #   保持 `#E65100` 的醒目度 ✓）
C_DANGER = '#C62828'         # 危险红
C_TEXT = '#616161'           # 正文中性灰
C_TEXT_DIM = '#757575'       # 次级说明灰 ⭐ 05 §4.5a v2 清单第 1 项：原 `#888888`
                             #   白底 3.54 / 卡底 3.25（<AA 4.5）⇒ 白底 4.61 / 卡底 4.23 ✅
C_CARD = '#F5F5F5'           # 卡片底
C_BG = '#FFFFFF'             # 窗口底
C_BORDER = '#DDDDDD'         # 分隔线 / 边框
C_RUN = '#1565C0'            # 运行中蓝（状态灯）
C_OFF = '#9E9E9E'            # 灰（未连 / 空闲 / 未选中）

# ── 棋盘（§4.3 棋盘配色 + 附录 E.2 棋盘数据格式）──────────────────────
BOARD_BG = '#FFFFFF'         # 画布底（⭐ 也兼作"底深到能配白字"的角标字色回落，见 MARK_FG）
BOARD_FOG = '#9E9E9E'        # 雾格（无数据 / ratio 低）
BOARD_PLAIN = '#E8F5E9'      # 已揭示空地
BOARD_CONTENT = '#FFF3E0'    # 内容格
BOARD_CAMP = '#BBDEFB'       # 营地
BOARD_EDGE = '#BDBDBD'       # 格线
BOARD_BLOCKED = '#FDECEA'    # 拉黑格底（上面再叠斜线纹）⭐ 05 §4.5a v2 清单第 4 项：
                             #   原 `#EF9A9A` 深粉 ⇒ 配灰纹仅 1.65:1 ⇒ 浅红底 + 深红纹
                             #   是 Material 错误态惯例，斜纹在其上 4.92:1 ✅
# ── 棋盘上的"字色"派生常量（**组件里不许写死字面色** ⇒ 全部集中在这里 ✓）──
C_BLOCKED_HATCH = C_DANGER   # 拉黑格斜线纹 ⭐ 05 §4.5a v2 清单第 5 项：原灰 `C_TEXT_DIM`
                             #   ⇒ 换危险红（浅红底上 4.92:1 ✅ / 内容格上 5.13:1 ✅）
C_ON_FOG = '#FFFFFF'         # 雾格上的字（雾格 sid 小字）⭐ 05 §4.5a v2 清单第 3 项：
                             #   原 `C_TEXT_DIM` 灰字在 `BOARD_FOG` 上仅 1.32:1（严重不可读）
                             #   ⇒ 灰底白字（行业惯例；雾格是纯图形格、无关键文字 ⇒
                             #   2.68:1 按"图形级"可接受 ✓）
C_ON_CLOVER = '#3E2723'      # 幸运草角标内的字 ⭐ 05 §4.5a v2 清单第 6 项：原白字在
                             #   黄底 `#F9A825` 上仅 1.97:1 ⇒ 深棕字 7.01:1 ✅
                             #   （Material 规范里黄底配深棕/近黑）

# 标记角标：色 / 字（键与 `marks.py` 的标记名一致：boss/redEquip/recommend/clover/battle）
MARK_COLORS = {'boss': C_DANGER, 'redEquip': '#7B1FA2', 'recommend': C_OK,
               'clover': '#F9A825', 'battle': C_TEXT}
MARK_TEXT = {'boss': '王', 'redEquip': '装', 'recommend': '赞', 'clover': '草', 'battle': '战'}
# 角标内**文字**色：按标记名查表（⚠ 组件里不许 `if nm == 'clover'` 分支、更不许写死字面色 ✓）
#   ⭐ 05 §4.5a v2 清单第 6 项：只有**黄底**的幸运草角标 `#F9A825` 需要深字（白字仅
#     1.97:1 ❌）⇒ 登记 `C_ON_CLOVER`；其余角标底色都深（危险红 / 紫 / 成功绿 / 中性灰）
#     ⇒ 继续白字（`BOARD_BG`，与 v1 逐字相同 ✓）。
#   ⚠ **取不到就回落 `BOARD_BG`**（未知标记画的是灰实心点 `C_TEXT_DIM`，白字其上与 v1
#     完全一致 ⇒ 不引入新回归）—— 所以组件侧一律写 `MARK_FG.get(nm, BOARD_BG)` ✓
MARK_FG = {'clover': C_ON_CLOVER}

# ── 状态灯 6 态色表（`StatusDot` 用；**唯一色值来源** ⇒ 组件里不硬编码 ✓）──
#    kind: 'ok'绿 | 'run'蓝 | 'lock'红（锁定待处理）| 'warn'橙 | 'danger'红 | 'off'灰
#    ⚠ `'warn'` **继续用 `C_WARN`（文字版）**，不换 `C_WARN_BG` —— 依据是同一份代码：
#      `widgets.StatusDot` 的 ● 圆点与它右边的文字**共用同一个 `self.fg`**
#      （`widgets.py` 的 `self._dot` / `self._lab` 都是 `fg=self.fg`）⇒ 这里若取图形色
#      `#E65100`，那行**警告文字**又会掉回 3.79:1（正是 §4.5a 第 2 项要修的病 ✗）；
#      取文字色 `#BF360C` 则圆点（白底 5.60:1）与文字**同时达标** ✓（单值两用 ⇒ 从严）
KIND_COLORS = {'ok': C_OK, 'run': C_RUN, 'lock': C_DANGER,
               'warn': C_WARN, 'danger': C_DANGER, 'off': C_OFF}
KINDS = tuple(KIND_COLORS)   # 顺序固定 ⇒ 上层可用来遍历/断言

# ══════════════════════════════════════════════════════════════════════
# 二、字体（§4.5：UI 一律 Microsoft YaHei UI，数据/日志 Consolas）
#   ⛔⛔ 2026-10-12 **换回原字体**（用户原话：「**字体换回来吧**」）——
#     曾按「汉字黑体 + 数字 Times New Roman」分族（`is_numeric`/`num_family`），
#     用户看过实际效果后要求换回 ⇒ 全窗恢复 `Microsoft YaHei UI` 单族 ✓
#     ⚠ 分族那套代码**已删除**（不留死代码 ✗）
# ══════════════════════════════════════════════════════════════════════
F_UI = 'Microsoft YaHei UI'
F_MONO = 'Consolas'
FONT_BODY = (F_UI, 11)       # ⭐ T6 §8 表 1：tk 侧正文与 ctk 的 `FS_BODY`(11) 对齐
                             #   ⚠ 原来是 10 ⇒ 混排时 tk 控件（存图勾选/日志说明）比
                             #     ctk 控件小一档、看着"不统一" ✗
FONT_TITLE = (F_UI, 13, 'bold')   # = ctk_theme.FS_TITLE（13 bold）
FONT_NUM = (F_UI, 14, 'bold')     # = ctk_theme.FS_NUM（14 bold）
                                  #   ⭐ 2026-10-13 P1-d（工单 07 §5 第 3 条）：随 ctk 侧一起
                                  #     16 → 14pt。**必须同改**，否则这句「= FS_NUM」会变成
                                  #     假话（本项目最忌"注释与代码不一致" ✗）。
                                  #   ⚠ 它被注册成 `Num.TLabel`（见下方 `apply_theme`），
                                  #     由 ttk 版 `StatCard` 使用（`widgets.py`；`_demo.py` 在用）
FONT_SUB = (F_UI, 10)        # ⭐ T6 §8：原 9 提到 10（= ctk 的 `FS_SUB`）
FONT_HINT = (F_UI, 9)        # = ctk 的 `FS_HINT`（9）
FONT_MONO = (F_MONO, 9)
FONT_BTN = (F_UI, 10)
FONT_BTN_MAIN = (F_UI, 10, 'bold')
# ⚠ 派生一条：棋盘左上角的 sid 后缀 / 标记角标的小字（比 FONT_MONO 再小一档）。
#   放在这里是为了守住"组件文件里不出现任何硬编码字体"这条纪律 ✓。
FONT_TINY = (F_MONO, 8)
FONT_TINY_UI = (F_UI, 8)

# ══════════════════════════════════════════════════════════════════════
# 三、间距 / 窗口尺寸（§4.3）
# ══════════════════════════════════════════════════════════════════════
PAD_CARD = 12                # 卡片内边距
PAD_GAP = 8                  # 卡片/控件间距
PAD_TAB = 10                 # 页签内边距
BTN_H = 32                   # 普通按钮高（px）
BTN_H_MAIN = 40              # 主按钮高（px）
# ⭐⭐⭐ 2026-10-15 宽度 **1100 → 1140**（用户报完"看不见"之后又加了一颗勾选）
#   ---- 账算清楚（实测 `_measure_ad_ck.py`）----
#     那一排原需 **1090px**（1100 下只余 10px）
#     ⇒ 2026-10-15 加「**免广告**」勾选 ⇒ 需 **1214px** ✗ 装不下
#     ⇒ 用户给方案：「**立即招募按钮移到下面的工具栏里**（= 工具页签）」
#       ⇒ 把它挪走后**降到 1130px** ⇒ 仍比 1100 多 **30px** ✗
#     ⇒ 只能**加宽窗口**：取 **1140**（比 1130 留 **10px** 余量）✓
#   ---- 与用户既有口径冲不冲突 ----
#     ⚠ 用户 2026-10-12 那条是「**窗口有点高，调低一点**」—— 管的是**高**，不是宽 ✓
#     ⚠ `docs/09` 那条「要和谐」讲的是**主题配色**，不是窗口宽 ✓
#     ⚠ 也没有门禁钉着宽度（已 grep）✓
WIN_W = 1140
# ⚠ 2026-10-12：900 → **860**（用户：「**窗口有点高，调低一点**」）
#   T6 整窗迁 ctk 之后控件更紧凑 ⇒ 860 高时**日志区仍有 ~140px**（判据要 >100px ✓）
#   ⇒ 回到规划 §4.3 的原定尺寸，不再需要 T5 那次"加高 40px" ✓
WIN_H = 860
# ⭐⭐⭐⭐ 2026-10-14 宽度下限 900 → **1000**（用户报「**装备升星和存图按钮都看不见了**」）
#   ---- 病 ----
#     主控制卡那一排（左三按钮 + 公会日常/免费招募/[立即招募]/自动补给/每N张升星/存图）
#     **本身就要 ~1090px**；而 `WIN_MIN` 允许拉到 **900** ⇒ 那时 bar 只有 876px
#     ⇒ 末尾的「张图升星」「存图」**直接被裁掉** ✗（正是用户看到的）
#   ---- 为什么抬下限，而不是继续缩控件 ----
#     我已经按用户要求把这一排**从"右锚"改成"紧跟停止按钮"**（`side='left'`）✓，
#     并把三个长标签缩短（「张图升星装备（0=关）」「存图（只存进图首帧）」
#       「没体力自动用补给」→「张图升星（0=关）」「存图」「自动补给」）✓
#     实测需要 **1090px**（`_measure_bar2.py` / `_measure_bar.py`）⇒
#     900 的旧下限**从根上装不下**，继续缩只会把文案缩成看不懂的缩写 ✗
#   ⇒ 下限取 **1060**（实测那一档「存图」**完整可见**，见下表的真图核对 ✓）
#     ⚠ 我第一版取了 1000 —— **不够**：真图 `runs/rowshot/row_1000.png` 显示
#       「存图」被挤到最右、**文字被裁成只剩一个勾选框** ✗
#       （`ctk` 的 pack 在空间不足时**压窄控件**而不是整体裁掉 ⇒
#        量"右边缘 ≤ bar 宽"会**误判为通过** ✗✗ —— 这条判据不够，必须**看真图** ✓）
#     实测（`_shot_row.py` 真图 + `_measure_real.py` 尺寸）：
#         1100 ⇒ 全部完整可见 ✓（默认窗宽）
#         1060 ⇒ 全部完整可见 ✓  ← 取它当下限
#         1000 ⇒ 「存图」文字被裁 ✗
#         900  ⇒ 明显更差 ✗
#   ⚠ 用户 2026-10-12 只说过「**窗口有点高，调低一点**」（管的是**高**，不是宽）⇒
#     抬宽度下限**不违背**那条口径 ✓
#   ⚠ 也没有门禁钉着 `WIN_MIN`（已 grep 确认）⇒ 改它不会破门禁 ✓
    #     ⚠ 2026-10-15：再加「免广告」并把「立即招募」挪去工具页签后
    #       实测需要 **1130px** ⇒ 下限跟着提到 **1120**（略低于默认 1140、留 10px）✓
WIN_MIN = (1120, 700)
TAB_PAD_X = PAD_TAB          # ttk.Notebook 页签左右内边距

# ══════════════════════════════════════════════════════════════════════
# 三-B、⭐ 2026-10-13 「手绘效果图 1:1 复刻」的行高表（docs/09-PC端UI复刻工单.md）
# ══════════════════════════════════════════════════════════════════════
# 用户口径（原话）：「**就按你画的这个效果图一比一复刻，我很喜欢。
#   去掉效果图那个窗口，里面的复刻就行**」⇒ 把每一排**钉成固定高度**，
#   不再让 ctk 的默认控件高度（`CTkLabel` 恒 28px）决定布局 ✗。
#
# ⚠ 为什么必须"钉死"：实测 `ctk.CTkLabel` 的默认高**恒为 28px**
#   （9pt 的字也是 28）⇒ 九卡自然高 102px、状态卡自然高 398px，
#   与效果图的 78 / 316 差一大截 ✗（详见 docs/08 的差异说明）
ROW_GAP = 6                  # 排与排之间的间距（效果图取值）
TOPBAR_H = 44                # 顶栏高（含底部 1px 分隔线）
MAINCARD_H = 58              # 主控制卡高（36 按钮 + 上下 11）
DASH_H = 78                  # 仪表盘九卡高（= 8 + 17 + 28 + 17 + 8）
MID_H = 349                  # 中栏高（棋盘卡/状态卡同高）
LEFT_CARD_W = 452            # 棋盘卡固定宽（与效果图一致）
BOARD_CELL = 54              # 棋盘每格边长（⛔ 2026-10-13 用户「**棋盘稍微放大一点**」
#   48 → **54**：删掉画布内标题行（_BHEADER 0）＋ 删掉卡内说明行（-25px）
#   ⇒ 省下的高度**全给棋盘**，日志区**一点不少**（用户最在意日志高低 ✓）
#   ⚠ 宽度校验：7×54 + 2×_BPAD(8) = **394** <= 卡内可用 452-2×12 = **428** ✓)
#   ⚠ 画布高 = 5×54 + 2×8 = **286**（原 5×48+24+16 = **280**）⇒ 只 +6px，
#     而删掉那行省了 25px ⇒ **净给日志 +19px** ✓
#   ⚠ 取值是**算出来的**，不是拍的：目标 = 手绘效果图的
#     · 盘面高 **270**（= 5×54）· 日志区 **260**
#     · 画布高 = 5×cell + `_BHEADER`(24) + 2×`_BPAD`(8) = 5×cell + 40
#     · 中栏**不钉高**（按内容自撑）⇒ 画布每 +5 ⇒ 中栏 +5 ⇒ **日志 -5**
#     ⇒ cell 48 ⇒ 画布 280 ⇒ 中栏 ~335、日志 **259**（与效果图 260 对齐 ✓）
#     ⛔ 别再"顺手调大"：cell 每 +1 ⇒ **日志 -5px**（用户最在意日志高低 ✓）
#   ⚠ `MID_H` 只作**记录值**（效果图里中栏是 316）；实跑中栏 ~335（差在画布内那行标题）
LBL_H = 17                   # 9pt 标签的紧凑高度（原 ctk 默认 28）
LBL_H_SUB = 20               # 11pt 标签的紧凑高度
LBL_H_TITLE = 24             # 13pt 标签的紧凑高度
TAB_PAD_Y = PAD_TAB // 2     # 上下留一半（页签不能太高，否则抢内容区）


# ══════════════════════════════════════════════════════════════════════
# 四、颜色 → 语义 kind（把"现成 fg 色值"归一成 6 态之一）
# ══════════════════════════════════════════════════════════════════════
# ⭐ 用途：上层（将来的 datasource / 主窗口）手里往往只有**一个现成的 fg 色值**
#   （比如旧的 `#2a7` / `#080` / `#a00`，或 loop_log 里的状态色）——
#   而 `StatusDot` 只认 kind。`kind_of_color()` 就是那座桥 ✓。
# ⚠ 映射表里同时收**新规范色值**和**旧 bot_gui.py 的历史色值**：
#   历史值留着，是为了让"旧数据源直接喂"时不至于一律落到灰 ✗。
_EXACT = {
    # 新规范色值
    C_PRIMARY: 'run', C_PRIMARY_D: 'run', C_RUN: 'run',
    #   ⚠ `C_WARN` 与 `C_WARN_BG` **两个都要登记成 'warn'**（05 §4.5a v2 清单第 2 项把
    #   警告色拆成"文字/图形"两半）：漏掉 `C_WARN_BG` 的话，拿 `#E65100` 去问
    #   `kind_of_color()` 会**落 'off' 灰**（历史表里只有 `'#E60'`⇒`#EE6600`，与它不等 ✗）
    C_OK: 'ok', C_WARN: 'warn', C_WARN_BG: 'warn', C_DANGER: 'danger', C_TEXT: 'off',
    C_TEXT_DIM: 'off', C_OFF: 'off', C_BORDER: 'off', C_CARD: 'off', C_BG: 'off',
    #   ⚠ `C_ON_FOG`(=`#FFFFFF`) / `C_BLOCKED_HATCH`(=`C_DANGER`) 无需另登记
    #     （与 `C_BG` / `C_DANGER` **同键**，写两遍是同一个 key ⇒ 反而像"两套值"✗）；
    #     `C_ON_CLOVER` `#3E2723` 明度太低 ⇒ `_hue_kind()` 已归 'off' ✓
    BOARD_FOG: 'off', BOARD_EDGE: 'off', BOARD_BLOCKED: 'danger',
    BOARD_CAMP: 'run', BOARD_PLAIN: 'ok', BOARD_CONTENT: 'warn',
    MARK_COLORS['boss']: 'danger', MARK_COLORS['redEquip']: 'warn',
    MARK_COLORS['recommend']: 'ok', MARK_COLORS['clover']: 'warn',
    # 旧 `bot_gui.py` 里的历史色值（保留，别删 ⚠ 见上面注释）
    '#2A7': 'ok', '#080': 'ok', '#0A0': 'ok', '#00A000': 'ok',
    '#048': 'run', '#00F': 'run', '#08C': 'run',
    '#A00': 'danger', '#C00': 'danger', '#F00': 'danger',
    '#C60': 'warn', '#E60': 'warn', '#F80': 'warn', '#F9A825': 'warn',
    '#333': 'off', '#444': 'off', '#555': 'off', '#666': 'off',
    '#777': 'off', '#888': 'off', '#999': 'off', '#AAA': 'off',
    '#BBB': 'off', '#CCC': 'off', '#DDD': 'off', '#EEE': 'off',
}
# tk 自带的颜色名（只收常见的；认不出的一律 'off'，**不猜** ✓）
_TK_NAMES = {
    'red': 'danger', 'firebrick': 'danger', 'crimson': 'danger',
    'green': 'ok', 'darkgreen': 'ok', 'forestgreen': 'ok', 'limegreen': 'ok',
    'blue': 'run', 'navy': 'run', 'royalblue': 'run', 'steelblue': 'run',
    'orange': 'warn', 'darkorange': 'warn', 'goldenrod': 'warn', 'purple': 'warn',
    'gray': 'off', 'grey': 'off', 'dim gray': 'off', 'dimgray': 'off',
    'silver': 'off', 'black': 'off', 'darkgray': 'off', 'darkgrey': 'off',
}
_HEX = '0123456789ABCDEF'


def _hex6(v):
    """把 `#abc` / `#AABBCC` / `aabbcc` 归一成 `#AABBCC`；不是颜色就 None（**绝不抛**）

    ⚠ 3 位缩写要展开（旧 GUI 里 `#2a7` 这种写法就有 ⇒ 不展开会一律落灰 ✗）。
    """
    try:
        s = v.strip().upper()
    except Exception:               # noqa: BLE001  （不是 str / 有毛病的 __str__）
        return None
    if s.startswith('#'):
        s = s[1:]
    if len(s) == 3 and all(ch in _HEX for ch in s):
        return '#' + ''.join(ch * 2 for ch in s)
    if len(s) == 6 and all(ch in _HEX for ch in s):
        return '#' + s
    return None


def _hue_kind(hx):
    """`#RRGGBB` 按 明度/饱和度/色相 粗分 6 态（认不出就 'off'，**不猜** ✓）

    判据（够用即可，不追求色彩学精确）：
        饱和度过低 或 太暗 ⇒ 'off'（当"灰字/黑字"看）
        色相 20°~70° ⇒ 'warn'（橙/黄）；70°~165° ⇒ 'ok'（绿）；
        165°~265° ⇒ 'run'（蓝/靛）；265°~340° ⇒ 'warn'（紫，如红装紫）；
        其余（正红/品红）⇒ 'danger'。
    """
    try:
        r = int(hx[1:3], 16) / 255.0
        g = int(hx[3:5], 16) / 255.0
        b = int(hx[5:7], 16) / 255.0
    except Exception:               # noqa: BLE001
        return 'off'
    mx, mn = max(r, g, b), min(r, g, b)
    if mx <= 0.0:
        return 'off'
    sat = (mx - mn) / mx
    if sat < 0.15 or mx < 0.35:
        return 'off'
    if mx == mn:
        return 'off'
    if mx == r:
        hue = (60.0 * ((g - b) / (mx - mn))) % 360.0
    elif mx == g:
        hue = 60.0 * ((b - r) / (mx - mn)) + 120.0
    else:
        hue = 60.0 * ((r - g) / (mx - mn)) + 240.0
    if hue < 20.0 or hue >= 340.0:
        return 'danger'
    if hue < 70.0 or hue >= 265.0:
        return 'warn'
    if hue < 165.0:
        return 'ok'
    return 'run'


def kind_of_color(fg):
    """把任意现成 fg 色值/字符串映射成 `'ok'|'run'|'lock'|'warn'|'danger'|'off'`

    ⚠ 对**任何**输入都返回这 6 个之一（含 None / 数字 / 对象 / 乱码）——
      宁可落 'off'（灰）也**绝不抛、绝不返回 None** ✓（调用方不必再判空）。
    ⭐ `'lock'`（红装锁定待处理）与 `'danger'` 同色（都红），但**语义不同** ⇒
      这个函数**不会主动产生 'lock'**（它只从颜色反推，红就是红）；
      要区分锁定态，请直接 `dot.set(text='已锁定', kind='lock')` ✓。
      若 `fg` 本身就是 kind 名（`'ok'`/`'lock'` …）⇒ 原样回环（方便"两种入口混用"）。
    """
    if fg is None:
        return 'off'
    hx = _hex6(fg)
    if hx is not None:
        return _EXACT.get(hx) or _hue_kind(hx)
    try:
        s = fg.strip().lower()
    except Exception:               # noqa: BLE001
        return 'off'
    if s in KIND_COLORS:            # 传进来的本来就是 kind 名 ⇒ 回环 ✓
        return s
    if s.upper() in _EXACT:         # 大写归一后再查一次（表里存的是大写色值）
        return _EXACT[s.upper()]
    if s in _TK_NAMES:
        return _TK_NAMES[s]
    return 'off'


# ══════════════════════════════════════════════════════════════════════
# 五、apply_theme —— 注册**全部**样式名（名字逐字固定，上层按名引用）
# ══════════════════════════════════════════════════════════════════════
def _btn_pad(h):
    """把"按钮高 px"换算成 ttk 的纵向 padding（⚠ ttk 按钮**没有 height 选项**）

    一行 10pt 文字实测约 16px ⇒ `(h - 16) / 2` 的上下内边距才能撑到 h 高。
    最小值夹到 2，避免算出负数（老 Tk / 奇怪 DPI 下也能起窗 ✓）。
    """
    try:
        return max(2, int((int(h) - 16) / 2))
    except Exception:               # noqa: BLE001
        return 6


def apply_theme(root):
    """把整窗挂上统一主题 → 返回 `ttk.Style`

    `clam` 底 + 浅色（§4.5）。**注册的样式名逐字固定**（上层按名引用，别改名 ⚠）：

        TFrame / Bg.TFrame / Card.TFrame
        TLabel / Bg.TLabel / Card.TLabel / Title.TLabel / CardTitle.TLabel /
        Num.TLabel / Sub.TLabel / Hint.TLabel / Ok.TLabel / Warn.TLabel /
        Bad.TLabel / Mono.TLabel
        TButton / Primary.TButton / Danger.TButton / Tool.TButton / Main.TButton /
        Main2.TButton
        TCheckbutton / Card.TCheckbutton / TEntry
        TNotebook / TNotebook.Tab / TLabelframe / TLabelframe.Label

    ⚠ 顺带 `root.configure(bg=C_BG)`（老 `tk.Frame/Label` 混进 ttk 布局时底不白 ⇒
      会露出系统灰 ✗）。
    ⚠ 全程容错：GUI 跑在 pythonw（无控制台），这里抛了用户**什么都看不见** ⇒
      逐段 `try/except (tk.TclError, Exception)` 兜底；真拿不到 Style 对象就返回 None
      （调用方**不该**假设一定非空 —— 但几乎不可能走到）。
    """
    st = None
    try:
        st = ttk.Style(root)
    except Exception:               # noqa: BLE001  （理论上不会；防御一下）
        try:
            st = ttk.Style()
        except Exception:           # noqa: BLE001
            st = None
    if st is None:
        return None
    try:
        st.theme_use('clam')        # §4.5：clam 底（没这个主题就留系统默认，不抛）
    except tk.TclError:
        pass
    except Exception:               # noqa: BLE001
        pass

    v_pad, v_main = _btn_pad(BTN_H), _btn_pad(BTN_H_MAIN)
    try:
        # ── 容器（Frame）──────────────────────────────────────────────
        st.configure('TFrame', background=C_BG)
        st.configure('Bg.TFrame', background=C_BG)
        st.configure('Card.TFrame', background=C_CARD, relief='flat', borderwidth=0)

        # ── 文字（Label）──────────────────────────────────────────────
        st.configure('TLabel', background=C_BG, foreground=C_TEXT, font=FONT_BODY)
        st.configure('Bg.TLabel', background=C_BG, foreground=C_TEXT, font=FONT_BODY)
        st.configure('Card.TLabel', background=C_CARD, foreground=C_TEXT, font=FONT_BODY)
        st.configure('Title.TLabel', background=C_BG, foreground=C_TEXT, font=FONT_TITLE)
        st.configure('CardTitle.TLabel', background=C_CARD, foreground=C_TEXT,
                     font=FONT_SUB)
        st.configure('Num.TLabel', background=C_CARD, foreground=C_PRIMARY, font=FONT_NUM)
        st.configure('Sub.TLabel', background=C_CARD, foreground=C_TEXT_DIM, font=FONT_SUB)
        st.configure('Hint.TLabel', background=C_BG, foreground=C_TEXT_DIM, font=FONT_HINT)
        st.configure('Ok.TLabel', background=C_BG, foreground=C_OK, font=FONT_BODY)
        # ⚠ 本段里**唯一**的 C_WARN 用法，且正是"**文字**场景"（05 §4.5a v2 清单第 2 项
        #   明写：「`bot_gui.py` 停止规则页签的提示文字保持 `C_WARN`」）⇒ 保持文字色 ✓
        #   —— 本文件里**没有任何**把 C_WARN 当 background / 边框 / 填充用的地方
        #   （图形侧全部走 `C_WARN_BG`，如 `widgets.BarChart` 的警告柱）✓
        st.configure('Warn.TLabel', background=C_BG, foreground=C_WARN, font=FONT_BODY)
        st.configure('Bad.TLabel', background=C_BG, foreground=C_DANGER, font=FONT_BODY)
        st.configure('Mono.TLabel', background=C_BG, foreground=C_TEXT, font=FONT_MONO)

        # ── 按钮（⚠ 高度只能靠 padding 撑：ttk 没有 height 选项）──────
        st.configure('TButton', font=FONT_BTN, padding=(PAD_GAP + 2, v_pad),
                     background=C_CARD, foreground=C_TEXT, borderwidth=1,
                     relief='raised', anchor='center')
        st.map('TButton',
               background=[('disabled', C_CARD), ('pressed', C_BORDER),
                           ('active', C_BORDER)],
               foreground=[('disabled', C_OFF)])
        st.configure('Primary.TButton', font=FONT_BTN, padding=(PAD_GAP + 2, v_pad),
                     background=C_PRIMARY, foreground=C_BG, borderwidth=0,
                     relief='flat', anchor='center')
        st.map('Primary.TButton',
               background=[('disabled', C_OFF), ('pressed', C_PRIMARY_D),
                           ('active', C_PRIMARY_D)],
               foreground=[('disabled', C_BG)])
        # ⚠ 2026-10-12 T5：`Danger.TButton` 的纵向 padding 由 `v_pad`(32px) 改 **`v_main`(40px)**
        #   —— 工单 §T5 改动 3：「**三个按钮**（主/次/危险）高度都由 `_btn_pad(BTN_H_MAIN)` 撑」
        #   ⇒ 主控制卡第一排三个按钮**等高**才整齐（否则"停止"比"连刷"矮一截 ✗）
        #   ⚠ 本样式的使用者只有：主控制卡「■ 停止」＋ `_demo.py` 的「✕ 关窗」（一起变高，无害 ✓）
        st.configure('Danger.TButton', font=FONT_BTN, padding=(PAD_GAP + 2, v_main),
                     background=C_DANGER, foreground=C_BG, borderwidth=0,
                     relief='flat', anchor='center')
        st.map('Danger.TButton',
               background=[('disabled', C_OFF), ('pressed', '#8E1B1B'),
                           ('active', '#A52222')],
               foreground=[('disabled', C_BG)])
        st.configure('Tool.TButton', font=FONT_SUB, padding=(PAD_GAP, max(2, v_pad - 2)),
                     background=C_CARD, foreground=C_TEXT, borderwidth=1,
                     relief='raised', anchor='center')
        st.map('Tool.TButton',
               background=[('disabled', C_CARD), ('pressed', C_BORDER),
                           ('active', C_BORDER)],
               foreground=[('disabled', C_OFF)])
        st.configure('Main.TButton', font=FONT_BTN_MAIN, padding=(PAD_GAP + 8, v_main),
                     background=C_PRIMARY, foreground=C_BG, borderwidth=0,
                     relief='flat', anchor='center')
        st.map('Main.TButton',
               background=[('disabled', C_OFF), ('pressed', C_PRIMARY_D),
                           ('active', C_PRIMARY_D)],
               foreground=[('disabled', C_BG)])
        # ⭐ 2026-10-12 T5（工单 06 §T5 第 1 项）：**次要主操作**按钮
        #   用户：「**主控制卡太丑了，优化下**」——病根之一是"连刷"与"跑 1 张"
        #   **同款同色** ⇒ 看不出哪个是主操作 ✗
        #   ⇒ 三种视觉分级：**主=实心靛蓝（Main）** / **次=描边靛蓝（Main2）** /
        #     **危险=实心红（Danger）** ✓
        #   ⚠ clam 底下的"描边按钮"做法：`background` 用窗口白、`bordercolor` 用主色、
        #     `borderwidth=1` 才有那圈线（只写 foreground 是画不出边框的 ✗）
        #   ⚠ 纵向 padding **比 Main 少 2px**：`borderwidth=1` 会额外撑高 4px（上下各 2）
        #     ⇒ 实测不减去会变成 49px，而 Main/Danger 是 45px（三个按钮不等高 ✗）
        st.configure('Main2.TButton', font=FONT_BTN_MAIN,
                     padding=(PAD_GAP + 8, max(2, v_main - 2)),
                     background=C_BG, foreground=C_PRIMARY,
                     bordercolor=C_PRIMARY, borderwidth=1,
                     relief='solid', anchor='center')
        st.map('Main2.TButton',
               background=[('disabled', C_CARD), ('pressed', C_BORDER),
                           ('active', C_CARD)],
               foreground=[('disabled', C_OFF)],
               bordercolor=[('disabled', C_BORDER)])

        # ── 勾选 / 输入 ───────────────────────────────────────────────
        st.configure('TCheckbutton', background=C_BG, foreground=C_TEXT, font=FONT_BODY,
                     focuscolor=C_BG)
        st.map('TCheckbutton', background=[('active', C_BG)],
               foreground=[('disabled', C_OFF)])
        st.configure('Card.TCheckbutton', background=C_CARD, foreground=C_TEXT,
                     font=FONT_BODY, focuscolor=C_CARD)
        st.map('Card.TCheckbutton', background=[('active', C_CARD)],
               foreground=[('disabled', C_OFF)])
        st.configure('TEntry', font=FONT_BODY, fieldbackground=C_BG,
                     foreground=C_TEXT, bordercolor=C_BORDER, insertcolor=C_TEXT,
                     padding=(4, 3))
        st.map('TEntry', fieldbackground=[('disabled', C_CARD)],
               foreground=[('disabled', C_OFF)])

        # ── 页签 ──────────────────────────────────────────────────────
        st.configure('TNotebook', background=C_BG, bordercolor=C_BORDER,
                     tabmargins=(PAD_GAP, 4, 0, 0), borderwidth=0)
        st.configure('TNotebook.Tab', font=FONT_BODY, padding=(TAB_PAD_X, TAB_PAD_Y),
                     background=C_CARD, foreground=C_TEXT, borderwidth=0)
        st.map('TNotebook.Tab',
               background=[('selected', C_BG), ('active', C_BORDER)],
               foreground=[('selected', C_PRIMARY), ('disabled', C_OFF)])

        # ── 分组框 ────────────────────────────────────────────────────
        st.configure('TLabelframe', background=C_BG, bordercolor=C_BORDER,
                     borderwidth=1, relief='solid')
        st.configure('TLabelframe.Label', background=C_BG, foreground=C_TEXT,
                     font=FONT_BTN_MAIN)
    except tk.TclError:
        pass                        # 个别选项在当前 Tk 上不认 ⇒ 已注册的照旧生效 ✓
    except Exception:               # noqa: BLE001
        pass

    try:
        root.configure(bg=C_BG)     # 老 tk 控件混排时的兜底底色（§4.3 白底）
    except Exception:               # noqa: BLE001
        pass
    return st
