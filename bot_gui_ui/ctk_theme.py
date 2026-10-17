# -*- coding: utf-8 -*-
"""bot_gui_ui.ctk_theme · customtkinter **双主题**色板 + 外观模式（T6 新建 · 与 `theme.py` 并存）

出处（先读再改；⚠ **浅色值不许自己发明**）：
    · UI 执行工单 **§T6 §Step 1**（= 本文件的存在理由）——
      「主题层 `bot_gui_ui/ctk_theme.py`（新建）：双套色板（浅色/深色，对应 demo 的 `P` dict）
      ＋ `apply(mode)`（`ctk.set_appearance_mode`）＋ `current()` 读当前模式
      ＋ **持久化到 `runs/.ui_theme`**（'light'/'dark'，启动时读 ⇒ 记住用户选择）；
      色板字段：bg/card/card2/border/text/dim/primary/primary_d/ok/warn/danger/
      fog/plain/content/camp/edge/blocked/logbg」；
    · 同文档 **§T6 §0 用户已逐条定稿的视觉**：控件库 **customtkinter 6.0**、
      右上角 `CTkSegmentedButton` 浅色/深色**运行时切换**（不重启）、卡片圆角 12、
      **棋盘 Canvas / 日志 Textbox 保留 tk/ctk 混排**（⇒ 它们要**手动**重设色，见 Step 3/4）；
    · 同文档 **§T6 §Step 1 的第二条 ⚠**：「**棋盘/日志仍走 `theme.py`**（它们保留 tk）
      ⇒ ctk_theme 只管 ctk 控件的色，**两套并存**，棋盘那套色（`BOARD_*`）
      **也要按深/浅各给一份**（demo 深色已调：空地 `#2D4A33` / 内容 `#4A3A28`）」
      ⇒ 本文件 `board_colors()` 的键名**逐字等于 `theme.py` 的同名常量名**，
      主窗口 `setattr(theme, k, v)` 后重画棋盘即可（键名对不上 ⇒ 改了不生效 ✗）；
    · 同文档 **§T6 §Step 3**（棋盘/日志接入双主题色）、**§Step 4**（切换时 ① `set_appearance_mode`
      ② 重设 tk 控件色 ③ 写 `runs/.ui_theme`；「⚠ ctk 控件换主题是**自动**的，
      **tk 控件必须手动重设色**」）；
    · 同文档 **§T6 §DoD 第 6 条**：「深色下文字对比度：用 §4.5a **同一脚本**实测关键组合
      （正文/主色字/棋盘文字 on 深底）**≥4.5:1**（正文）/**≥3:1**（图形），
      不达标就调深色色板」⇒ 深色板每个键的注释里都记着**实测值**（公式见
      `wcag_contrast()`，本文件内自带 ⇒ 门禁/主窗口都能复算 ✓）；
    · `本仓/bot_gui_ui/theme.py` **v2 值**（= `docs/05-PC端UI重设计方案与开发规划.md`
      §4.5a 实测驱动修订的那一版）—— ⚠ **浅色板逐键等于它**（`#F5F5F5`/`#616161`/
      `#3F51B5`/`#2E7D32`/`#BF360C`/`#C62828`/`#1565C0`/`#9E9E9E`/`#DDDDDD`/
      `#E8F5E9`/`#FFF3E0`/`#BBDEFB`/`#BDBDBD`/`#FDECEA`/`#757575`…），
      **不许"顺手优化"**（§T6 §Step 1 明写「与现行 theme.py 的 v2 值**完全一致**，
      读完 theme.py 逐个对齐，**别自己发明**」）；
    · `docs/05-PC端UI重设计方案与开发规划.md` **§4.5a**「明确不改的（保持 v1，已验证达标或属装饰）」
      —— 浅色侧**边框 `#DDDDDD` / 格线 `#BDBDBD` / 灰 `#9E9E9E` / 雾格底 `#9E9E9E`**
      是**装饰性 1px 线 / 纯图形**，WCAG 不强制 3:1 ⇒ 浅色板**不得为凑 3:1 而改**
      （改了反而违反"与 theme.py 完全一致"这条硬口径 ✗）。

⚠⚠ 四条铁律（GUI 跑在 pythonw，**无控制台** ⇒ 抛了用户什么都看不见）：
    ① **一切函数对坏输入容错不抛**：`apply(None)` / `apply('乱七八糟')` / `palette(123)` /
       `save_pref('xyz')` / `runs/` 不可写 / `.ui_theme` 是目录或是垃圾字节 ⇒
       一律**返回安全值**（`'light'` / `False`），**绝不抛** ✓；
    ② **不 `import` `theme.py`、更不改它**（浅色值在本文件里**另存一份字面量**；
       "两处值必须相等"由验收脚本对拍，**不是**靠 import 耦合 ⇒ `theme.py` 一个字节不动 ✓）；
    ③ 本模块是**纯数据 + `ctk` 调用**：唯一的对外副作用就是 `apply()` 里的
       `ctk.set_appearance_mode()` —— **不改本模块之外的任何全局对象**（不 `setattr(theme,…)`，
       那是主窗口的活）✓；
    ④ `palette()` / `board_colors()` 返回的**永远是新建的 dict 副本** ⇒ 调用方
       就地改 / 反复改都**污染不到**本模块的表 ✓。

⭐ 与 `theme.py` 的分工（**别混**）：
    `theme.py`  —— tk/ttk 侧的唯一色源（棋盘 Canvas、日志 `ScrolledText`、**存图那个
                   保留 tk 的勾选** —— 工单 §T6 §2 门禁 `T16f` 钉死 `tk.Checkbutton(bar2)`）；
    本文件      —— ctk 侧的双主题色源（ctk 控件的 fg_color/text_color/hover_color…）
                   ＋ **棋盘那 13 个 `BOARD_*`/`C_*` 键的深色版**（Step 3 用）。
    两者在**浅色**下**色值同源**（浅色板逐键对齐 `theme.py`），在**深色**下只有棋盘键
    与 ctk 键各自成套 ⇒ 切主题时主窗口要"ctk 自动 + tk 手动"两头都做（§Step 4）✓。
"""
import os

# ⚠ ctk 只在 `apply()` 里用到；**导入失败也不许炸本模块**（pythonw 下报错=白屏）
try:
    import customtkinter as _ctk
except Exception:                   # noqa: BLE001  （缺依赖 / 半装坏 / 非 Tk 环境）
    _ctk = None

# ══════════════════════════════════════════════════════════════════════
# 一、模式常量 / 中文名 / 环境钩子
# ══════════════════════════════════════════════════════════════════════
MODES = ('light', 'dark')           # 顺序固定（§T6 §Step 1）；上层可遍历/断言

# 偏好文件：`runs/.ui_theme`（§T6 §Step 1「持久化到 runs/.ui_theme」）——
#   ⚠ 内容只有 `light` / `dark` 两种可能；**认不出的值一律当 `light`**（见 load_pref）
PREF_FILE = '.ui_theme'
# ⚠ 本模块**唯一**的测试钩子：设了它就用它当 `runs/` 目录（探针/门禁造临时场景用；
#   正式运行**不设** ⇒ 走 `<mapbot_pc>/runs`）。名字跟仓内 `MAPBOT_*` 环境变量同族。
ENV_PREF_DIR = 'MAPBOT_UI_THEME_DIR'

# 中文名（§T6 §Step 0/§Step 4：右上角 `CTkSegmentedButton(['浅色','深色'])`）——
#   `label()` 只认这三个别名：`light`/`dark` ＋ 它们自己的中文名（回环 ⇒ 切页签时
#   把控件里读到的中文名再喂回来也不出错 ✓）；其余一律 `'浅色'`（**不猜**）。
LABELS = {'light': '浅色', 'dark': '深色'}
_ALIASES = {'light': 'light', 'dark': 'dark', '浅色': 'light', '深色': 'dark'}

_MODE = 'light'                     # 本模块记住的当前模式（`apply()` 成功后才更新）


def _norm(v):
    """把任意输入归一成 `'light'` / `'dark'`；**认不出返回 `None`**（绝不抛）

    ⚠ `None` / 数字 / 对象 / 乱码 / bytes 全走 `None` 分支 —— 调用方各自决定回落值
      （`apply()` 落 `'light'`、`label()` 落 `'浅色'`、`palette()` 落**当前模式**）。
    """
    try:
        s = v.strip().lower()
    except Exception:               # noqa: BLE001  （不是 str / 有毛病的 __str__）
        return None
    if not isinstance(s, str):      # bytes 之类：strip/lower 能过，但不是模式名 ⇒ 认不出
        return None
    return _ALIASES.get(s)


def _ctk_mod():
    """拿 customtkinter 模块（首次导入失败 ⇒ 每次调用再试一次；取不到返回 `None`）

    ⚠ 不在导入期硬失败：GUI 跑 pythonw，导入期抛异常等于**白屏无提示** ✗ ⇒
      取不到 ctk 时 `apply()` 按"ctk 抛异常"同款口径回落 `'light'`（§Step 1）✓
    """
    global _ctk
    if _ctk is None:
        try:
            import customtkinter as _m
            _ctk = _m
        except Exception:           # noqa: BLE001
            _ctk = None
    return _ctk


def wcag_contrast(a, b):
    """WCAG 2.1 对比度（**§T6 §DoD 第 6 条与 05 §4.5a 的同一把尺子**）；坏输入返回 `1.0`

    公式逐字照 WCAG 2.1：`(L_lighter + 0.05) / (L_darker + 0.05)`，
    单通道相对亮度 `c <= 0.03928 ? c/12.92 : ((c+0.055)/1.055) ** 2.4`。
    ⚠ 认不出的色值返回 `1.0`（= 最低对比度）而**不是抛** —— 让"喂错色值"在实测表里
      一眼可见（1.00 必然不达标），而不是把整个探针/门禁打断 ✓
    """
    try:
        la, lb = _luminance(a), _luminance(b)
    except Exception:               # noqa: BLE001
        return 1.0
    if la is None or lb is None:
        return 1.0
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def _luminance(hx):
    """`#RRGGBB` → WCAG 相对亮度；不是颜色返回 `None`（绝不抛）"""
    try:
        s = hx.strip()
        if s.startswith('#'):
            s = s[1:]
        if len(s) != 6:
            return None
        r, g, b = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:               # noqa: BLE001
        return None
    ch = []
    for c in (r, g, b):
        ch.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


# ══════════════════════════════════════════════════════════════════════
# 二、浅色板（**逐键 = `theme.py` v2**；⚠ 不许自己发明，见模块头 §Step 1）
#     ⚠ `card2` 是例外：`theme.py` 里**没有**同名常量（它没有"次级卡底/输入底"这一档）
#       ⇒ ctk 侧新增，取 Material Grey 200 `#EEEEEE`（浅色 surface-variant 惯例值），
#       只用于 ctk 的"次级卡/输入框底"，**不改任何 tk 控件的既有底色** ✓
# ══════════════════════════════════════════════════════════════════════
_P_LIGHT = {
    # ⭐⭐ 2026-10-12 **T6 §8 表 2 定稿**（浅色列）：值与 §T6 §Step 1 那版**不同** ——
    #    以 §8 表 2 为准（用户看过真实版 vs 预览版对比后重定的；带同款实测对比度 ✓）
    'bg':        '#F0F1F3',   # 窗口根底色（§8 表 2；原来 = #FFFFFF 太白、卡片浮不起来）
    'card':      '#FFFFFF',   # 卡片底（§8 表 2：卡片**白**、窗口**浅灰** ⇒ 层次反过来）
    'card2':     '#F5F6F8',   # 卡内嵌套底（九卡/版本卡/锁定卡/输入框）
    'border':    '#E2E4E8',   # 卡片描边/分隔线/勾选框边（图形 1px）
    'text':      '#2B2F36',   # 正文（on card **13.44** ✅ —— §8 表 2 实测值）
    'dim':       '#7A8089',   # 次级说明（on card 3.98；§8 注：「浅色 3.98 用于 ≥10pt 辅助字可接受」）
    # ⚠ **主色分两个角色**（§8 纪律 1）：`primary` = 作**文字**用；`primary_btn` = 作**按钮底**用。
    #   浅色下二者同值（`#3F51B5`：作文字 6.87 ✅、白字 on 它 6.87 ✅ 两者兼得）；
    #   深色下**必须分开**（见 `_P_DARK`）✓
    'primary':   '#3F51B5',   # 主色**文字**（状态句/均耗/链接）—— 6.87 ✅
    'primary_btn': '#3F51B5', # 主色**按钮底**（白字 6.87 ✅）
    'primary_d': '#3949AB',   # hover/按下（白字 8.98 ✅）
    'ok':        '#2E7D32',   # 成功绿（补给勾选/状态灯）—— 5.13 ✅
    'warn':      '#BF360C',   # 警告**文字**（§4.5a v2 第 2 项）—— 5.60 ✅
    'danger':    '#C62828',   # 危险红（停止规则/解锁钮）—— 5.62
    'run':       '#1565C0',   # 运行中蓝（状态灯）—— 5.75 ✅
    'off':       '#9E9E9E',   # 灰（未连/空闲；纯图形 ✓）
    'fog':       '#9E9E9E',   # 雾格底
    'plain':     '#E8F5E9',   # 已揭示空地
    'content':   '#FFF3E0',   # 内容格
    'camp':      '#BBDEFB',   # 营地
    'edge':      '#D8DBDF',   # 格线（§8 表 2）
    'blocked':   '#FDECEA',   # 拉黑格底（上叠 danger 斜纹）
    'logbg':     '#FAFBFC',   # 日志/工具文本框底（§8 表 2）
    'logfg':     '#2B2F36',   # 日志字（= text）
}

# ══════════════════════════════════════════════════════════════════════
# 三、深色板（**Material 深色规范**；⚠ 每个键的注释 = **DoD 第 6 条实测值**）
#     ⚠⚠ 深色**不是**把浅色反相：深底上必须把"当文字用的色"整体**调亮**——
#       浅色的主色 `#3F51B5` 在卡底 `#1E1E1E` 上只有 2.43:1（<4.5 ✗）、
#       浅色的边框 `#DDDDDD` 在深底上更是白得刺眼 ⇒ 两套板的**明度策略相反** ✓
#     ⚠ 深色板里 **6 个"棋盘色"与 `board_colors('dark')` 同值**（与浅色板同一约定：
#       UI 板与棋盘板不许打架，切主题时界面才协调 ✓）
# ══════════════════════════════════════════════════════════════════════
_P_DARK = {
    # ⭐⭐ **T6 §8 表 2 定稿**（深色列）。⚠ 深色**不是**反相：深底上"当文字用的色"要**调亮** ✓
    'bg':        '#1E1F22',   # 窗口底（§8 表 2）
    'card':      '#2B2D31',   # 卡底（比窗口底亮一档 ⇒ 卡片有层次）
    'card2':     '#313338',   # 卡内嵌套底（九卡/版本卡/锁定卡/输入框）
    'border':    '#3F4247',   # 描边/分隔线（图形 1px）
    'text':      '#DBDEE1',   # 正文（on card **10.21** ✅）
    # ⚠ 深色 dim **已从 #949BA4 调亮到 #A6ADB8**（§8 纪律 4：实测不达标后的修订值，
    #   **别再改回去** ✗）—— on card **6.10** ✅
    'dim':       '#A6ADB8',
    # ⚠⚠ **主色两个角色在深色下必须分开**（§8 纪律 1）：
    #   `#5865F2` 作**按钮底**白字 6.42 ✅ 很好，但作**文字**只有 **2.99 ❌** ✗✗
    #   ⇒ `primary`（文字）用调亮版 `#8B9DF0`（on card 5.37 ✅）；`primary_btn`（按钮底）
    #     用 `#5865F2`（白字 6.42 ✅）✓   ⚠ 上一版我把二者混成一个 `#8C9EFF`，
    #     正是 §8 点名要修的那类问题（"文字色与按钮底色分开"）✓
    'primary':   '#8B9DF0',   # 主色**文字**（§8 表 2；5.37 ✅）
    'primary_btn': '#5865F2', # 主色**按钮底**（§8 表 2；白字 6.42 ✅）
    'primary_d': '#4752C4',   # hover/按下（白字 **7.73** ✅）
    'ok':        '#57F287',   # 成功绿（9.50 ✅）
    'warn':      '#FEE75C',   # 警告（11.03 ✅）
    'danger':    '#ED4245',   # 危险红（3.59；§8 注「用于 bold/大控件可接受」）
    'run':       '#64B5F6',   # 运行中蓝（7.53 ✅）
    'off':       '#9E9E9E',   # 灰（深底上够亮 ✓）
    'fog':       '#4A4D53',   # 雾格底（§8 表 2 定稿值）
    'plain':     '#2D4A33',   # ⭐ §8 定稿（不许改）；格名 on it 7.27 ✅
    'content':   '#4A3A28',   # ⭐ §8 定稿（不许改）；格名 on it 8.07 ✅
    'camp':      '#2A3A52',   # 营地（§8 表 2 定稿值）；格名 on it 8.52 ✅
    'edge':      '#3F4247',   # 格线（§8 表 2 定稿值）
    'blocked':   '#5A2E30',   # 拉黑格底（§8 表 2 定稿值；上叠 danger 斜纹）
    'logbg':     '#18191C',   # 日志框底（§8 表 2）
    'logfg':     '#DBDEE1',   # 日志字（= text）
}

# ══════════════════════════════════════════════════════════════════════
# 四、棋盘板（**键名逐字 = `theme.py` 的同名常量名**；⚠ 少一个/拼错 = 悄悄不生效）
#     用途（§T6 §Step 3）：主窗口 `for k, v in ctk_theme.board_colors().items():
#                             setattr(theme, k, v)` 再重画棋盘/日志 ⇒
#     **键名必须与 `theme.py` 里一模一样**（父级按这个名字 `setattr`，改了就对不上 ✗）
#     ⚠ 这 13 个键的**浅色**值逐键等于 `theme.py`（含 `C_BLOCKED_HATCH = C_DANGER`）；
#       **深色**值见下（`plain`/`content` 是工单定稿值，其余按 Material 深色 + 实测达标配）
# ══════════════════════════════════════════════════════════════════════
_B_LIGHT = {
    'BOARD_BG':         '#FFFFFF',   # = theme.BOARD_BG（画布底；也兼作角标白字回落）
    'BOARD_FOG':        '#9E9E9E',   # = theme.BOARD_FOG（雾格）
    'BOARD_PLAIN':      '#E8F5E9',   # = theme.BOARD_PLAIN（已揭示空地）
    'BOARD_CONTENT':    '#FFF3E0',   # = theme.BOARD_CONTENT（内容格）
    'BOARD_CAMP':       '#BBDEFB',   # = theme.BOARD_CAMP（营地）
    'BOARD_EDGE':       '#BDBDBD',   # = theme.BOARD_EDGE（格线）
    'BOARD_BLOCKED':    '#FDECEA',   # = theme.BOARD_BLOCKED（拉黑格底）
    'C_TEXT':           '#616161',   # = theme.C_TEXT（格子名/正文）
    'C_TEXT_DIM':       '#757575',   # = theme.C_TEXT_DIM（次级说明）
    'C_PRIMARY':        '#3F51B5',   # = theme.C_PRIMARY（目标格描边 2px / 计划序号）
    'C_DANGER':         '#C62828',   # = theme.C_DANGER（boss 角标底 / 危险文字）
    'C_ON_FOG':         '#FFFFFF',   # = theme.C_ON_FOG（雾格上的字；⭐ 05 §4.5a v2 第 3 项）
    'C_BLOCKED_HATCH':  '#C62828',   # = theme.C_BLOCKED_HATCH（= C_DANGER；⭐ 05 §4.5a v2 第 5 项）
}

_B_DARK = {
    'BOARD_BG':         '#1B1B1B',   # 画布底（比窗口底再亮一档 ⇒ 棋盘区自成一块）
    'BOARD_FOG':        '#4A4D53',   # ⭐ §8 表 2 定稿（原 #6E6E6E 偏亮、雾格不"雾"）
    'BOARD_PLAIN':      '#2D4A33',   # ⭐ §8 定稿（不许改）；格名 on it 7.27 ✅
    'BOARD_CONTENT':    '#4A3A28',   # ⭐ §8 定稿（不许改）；格名 on it 8.07 ✅
    'BOARD_CAMP':       '#2A3A52',   # ⭐ §8 定稿；格名 on it 8.52 ✅
    'BOARD_EDGE':       '#3F4247',   # ⭐ §8 定稿（格线）
    'BOARD_BLOCKED':    '#5A2E30',   # ⭐ §8 定稿（拉黑格底）
    'C_TEXT':           '#DBDEE1',   # 格子名（on plain/content/camp = 7.27 / 8.07 / 8.52 ✅）
    'C_TEXT_DIM':       '#A6ADB8',   # 次级说明（与 UI 板 dim 同步 ✓）
    'C_PRIMARY':        '#5865F2',   # ⭐ §8 表 2 定稿：「计划序号圆 / 目标描边用**按钮底色**
                                     #   非文字色」（§8 表末那行）⇒ 取 `primary_btn` ✓
    'C_DANGER':         '#ED4245',   # boss 角标底（§8 表 2 danger ✓）
    'C_ON_FOG':         '#FFFFFF',   # 雾格上的字
    'C_BLOCKED_HATCH':  '#ED4245',   # 拉黑格斜线纹（= danger；深色底暗 ⇒ 纹要亮才看得见 ✓）
}

# ══════════════════════════════════════════════════════════════════════
# 三-B、⭐ T6 §7/§8 定稿：**字号阶梯**（全窗口唯一字号来源）+ **双色元组**
# ══════════════════════════════════════════════════════════════════════
#   §7① 病：字号散落且**倒挂**（勾选 `_f(13)` 比标签 `_f(9)`/正文 `_f(10)` 还大）
#   ⇒ §8 表 1 定死 **5 档**，全窗口只用这 5 档（组件里不许再写裸数字 ✓）
# ⛔⛔ 2026-10-12 **字体族已按用户要求换回**（原话：「**字体换回来吧**」）：
#   一度按「汉字黑体 + 数字 Times New Roman」分族（`is_numeric`/`num_family` 现算），
#   用户看了实际效果后要求**换回原来那一套** ⇒ 全窗恢复 `Microsoft YaHei UI` 单族 ✓
#   ⚠ 分族那套代码**已删除**（不留死代码 ✗）；**唯一保留的**是"进图体力那张卡字号大一点"
#     （用户明确要的，与字体族无关 ✓）
_FONT = 'Microsoft YaHei UI'
_MONO = 'Consolas'
FS_NUM = _FONT, 14, 'bold'          # 仪表盘九卡大数值
#   ⭐ 2026-10-13 P1-d（工单 07 §5）：**16 → 14pt**（数值不再"顶满"卡宽、九张更齐）
#   ⛔⛔ **不许取 13pt**：`_selftest_ui.py` ⑧ 断言「字号阶梯 5 档互异」，
#     而 `FS_TITLE` 就是 13 bold ⇒ 取 13 会与它**完全相同** ⇒ `set` 只剩 4 档 ⇒ 自检红 ✗✗
#     ⇒ 14 = 往下最接近又不撞档的一档 ✓
# ⭐ 进图体力那卡专用（**仍明显大一号**；用户 2026-10-12：「进图体力显示稍微大一点的」⇒ 不许拉平）
#   ⚠ 它是**唯一可能 8 字符**的卡（`1234→1234`）⇒ 给它更大的字号 + 更宽的列（见 bot_gui）
#   ⭐ P1-d：19 → **16pt**（= `FS_NUM` 的旧值；它在 5 档集合之外，可自由取 ✓）
FS_NUM_BIG = _FONT, 16, 'bold'
FS_TITLE = _FONT, 13, 'bold'        # 卡片标题、状态句（› 第 N 张图）（17px）
FS_BODY = _FONT, 11                 # **正文/按钮/HUD/勾选文字**（统一；勾选 13→11 ✓）（15px）
FS_SUB = _FONT, 10                  # 副标题、计划行、版本卡（13px）
FS_HINT = _FONT, 9                  # 页签小标题/底部说明/棋盘下说明（12px）
FS_MONO_SUB = _MONO, 10             # mono 同档（计划行/版本卡）
FS_MONO_LOG = _MONO, 9              # 日志（等宽小字）

# ⚠ 上一轮的"按内容分族"（汉字黑体/数字 Times New Roman）**已按用户要求整体撤掉**
#   ⇒ 这里那段注释与 `_NUM_CHARS` 一并删除（不留"注释指向已删代码"的残骸 ✗）
def font(spec):
    """字号阶梯 → `ctk.CTkFont`（坏输入 ⇒ 返回 None，调用方自己兜底 ✓）

    ⚠ 拿不到 ctk 时返回 None（`CTkLabel(font=None)` 会用默认字体，不抛 ✓）
    """
    try:
        _mod = _ctk_mod()
        fam, size, *rest = spec
        weight = (rest[0] if rest else 'normal')
        return _mod.CTkFont(family=fam, size=int(size), weight=weight)
    except Exception:               # noqa: BLE001
        return None


def font_bold(spec):
    """同档字号但**加粗**（**分组小标题**用：与正文同号 + bold ⇒ 层级清楚又不抢卡片标题 ✓）

    ⭐ 2026-10-12 用户口径：「为什么具体的旅行商人字体会比特殊方块大，
      **明明特殊方块才是标题**」⇒ 分组小标题必须**比它下面的勾选文字显眼**：
        · 旧版小标题 `FS_HINT`(9) < 勾选 `FS_BODY`(11) ⇒ **倒挂** ✗
        · 新版：小标题 = `FS_BODY`(11) **bold**、勾选 = `FS_BODY`(11) regular
          ⇒ 同号但更重 ⇒ 一眼看出"这是标题"；又不会压过卡片标题(13 bold) ✓
    """
    try:
        fam, size, *_ = spec
        return _ctk_mod().CTkFont(family=fam, size=int(size), weight='bold')
    except Exception:               # noqa: BLE001
        return None


# ══════════════════════════════════════════════════════════════════════
# 二-B、⭐⭐ T6 §7② 治本：**色板给双色元组**（ctk 随主题自动切，不用手动重设）
# ══════════════════════════════════════════════════════════════════════
#   病（代码级）：`ctk.set_appearance_mode()` **只自动更新"没显式给色"的控件**
#     （用默认双色元组的那些）。而上一版 `bot_gui.py` 有 **52 处** `fg_color=_p['card']`
#     —— `_p` 是**建窗那一刻**的色板快照 ⇒ 切换后那些控件**全停在旧色** ✗✗
#   ⇒ 修法（工单推荐 A）：`palette()` 每个键返回 **`(浅色, 深色)` 元组**，
#     控件直接 `fg_color=_p['card']` ⇒ 值本身就是双色 ⇒ **ctk 一切全换** ✓
#   ⚠ 向后兼容：`palette(mode='light'/'dark')`（**显式**给了具体模式）时返回**单值**
#     —— 因为那时调用方要的是"这一套色"（tk 控件用 / 探针用），给元组反而没法用 ✓
#     只有 `palette()`（不给 mode = 当前模式）才给元组。**这是本次的关键接口约定**。
# ══════════════════════════════════════════════════════════════════════
_TUPLE_KEYS = True          # 模块级开关（排查时可置 False 关掉元组行为）


# 模式 → 色板（**唯一**取值出口；外部只经 `palette()` / `board_colors()` 拿副本）
_PALETTES = {'light': _P_LIGHT, 'dark': _P_DARK}
_BOARDS = {'light': _B_LIGHT, 'dark': _B_DARK}

# 给验收/门禁用的**分类阈值**（§T6 §DoD 第 6 条；05 §4.5a 同款判据）
WCAG_TEXT_MIN = 4.5                 # 正文类（正文/主色字/日志字/棋盘格名）
WCAG_GRAPHIC_MIN = 3.0              # 图形类（边框/描边/雾格底/角标底/灰）

# ⚠⚠ 浅色板实测有 **11 个组合低于上面阈值**，但**一个都不许改** —— 它们全部由
#    `theme.py` v2 锁定值造成，且 `docs/05 §4.5a` 已逐条判过（原文实证如下）：
#      · 边框 `#DDDDDD` on bg / card       = **1.36 / 1.25** —— 装饰性 1px 线，WCAG 不强制
#      · 灰 `#9E9E9E` on bg / card         = **2.68 / 2.46** —— 「仅图形」非文字
#      · 格线 `#BDBDBD` on 画布白          = **1.88** —— 装饰性
#      · 雾格底 `#9E9E9E` on 画布白        = **2.68** —— 原文「图形可用（<3 但非文字）」
#      · 雾格字 `#FFFFFF` on 雾格底        = **2.68** —— 原文「雾格是纯图形格、无关键文字」
#      · 次级灰 `#757575` on 卡/次级卡/空地 = **4.23 / 3.97 / 4.10** —— v2 清单第 1 项判「卡底 4.23 ✅」
#      · 棋盘格名 `#616161` on 营地 `#BBDEFB` = **4.41** —— 05 §4.5a 实测表原文
#        「棋盘名 on 空地/内容/营地格 5.51 / 5.65 / **4.41** ✅ 达标（营地接近下限）」
#    ⇒ §T6 §Step 1 明令浅色板与 `theme.py` **完全一致** ⇒ 为凑阈值改浅色 = 违反硬口径 ✗；
#      **深色板则一条例外都没有**（每个键的注释里都记着实测值）✓
#    ⚠ 本模块**只带公式与阈值**，不下"哪些算例外"的结论 —— 那是验收脚本/门禁的活（避免
#      这里写死的例外表把**新生失败**也一并赦免掉 ✗）。


# ══════════════════════════════════════════════════════════════════════
# 五、外观模式：apply / current / toggle（§T6 §Step 1 ＋ §Step 4）
# ══════════════════════════════════════════════════════════════════════
def apply(mode):
    """设 ctk 外观模式 ⇒ 返回**生效**的模式（`'light'` / `'dark'`）；**绝不抛**

    ⚠ 坏 `mode`（`None` / `'乱七八糟'` / 数字/对象）或 ctk 抛异常 ⇒ **回落 `'light'`**
      并返回 `'light'`（§T6 §Step 1；GUI 无控制台，抛了用户看不见 ✗）；
    ⚠ 只做 `ctk.set_appearance_mode()` 这一件对外的事 —— ctk 控件会**自动**跟着换色
      （§Step 4「⚠ ctk 控件换主题是**自动**的」），**tk 控件（棋盘/日志/存图勾选）
      必须由主窗口手动重设色**，本模块**不碰**它们 ✓；
    ⚠ 接受中文名 `'浅色'`/`'深色'`（= `label()` 的输出 ⇒ `CTkSegmentedButton` 的回调
      可以把控件里读到的中文名直接喂回来，不必自己映射 ✓）。
    """
    m = _norm(mode)
    if m is None:
        m = 'light'                 # 坏输入 ⇒ 安全值（**不抛**）
    ctk = _ctk_mod()
    if ctk is None:                 # 取不到 ctk ⇒ 同"ctk 抛异常"口径
        _remember('light')
        return 'light'
    try:
        ctk.set_appearance_mode(m)
    except Exception:               # noqa: BLE001
        _remember('light')
        try:                        # 尽力把 ctk 也掰回浅色；掰不动也不抛 ✓
            ctk.set_appearance_mode('light')
        except Exception:           # noqa: BLE001
            pass
        return 'light'
    _remember(m)
    return m


def _remember(mode):
    """记住生效模式（模块内全局；**只写本模块**的变量 ✓ —— 铁律③）"""
    global _MODE
    _MODE = mode if mode in MODES else 'light'


def current():
    """当前模式 ⇒ `'light'` / `'dark'`（**永远**是这两个之一，绝不抛、绝不返回 None）

    ⭐ **优先问 ctk**（`ctk.get_appearance_mode()`）：若有人绕过本模块直接调了
      `ctk.set_appearance_mode('dark')`（比如用户的 `CTkSegmentedButton` 回调），
      这里读到的才是**屏幕上真正生效**的那个；ctk 取不到/读不出来 ⇒ 回落本模块记住的值 ✓
    """
    ctk = _ctk_mod()
    if ctk is not None:
        try:
            got = _norm(ctk.get_appearance_mode())
        except Exception:           # noqa: BLE001
            got = None
        if got in MODES:
            return got
    return _MODE if _MODE in MODES else 'light'


def toggle():
    """浅 ↔ 深 切换（内部走 `apply()`）⇒ 返回新模式（`'light'` / `'dark'`）

    ⚠ 以 `current()` 为准（**不**用本模块记住的值盲翻）—— 有人从别处改过外观模式时
      才能真正翻到"另一种" ✓；`apply()` 失败 ⇒ 返回它回落后的 `'light'` ✓
    """
    return apply('dark' if current() == 'light' else 'light')


# ══════════════════════════════════════════════════════════════════════
# 六、取色板：palette（ctk 用）/ board_colors（tk 棋盘/日志用）
# ══════════════════════════════════════════════════════════════════════
def _resolve(mode):
    """把 `mode` 解析成一定合法的模式名

    ⚠ `None` 或**认不出**的值 ⇒ **当前模式**（而不是写死 `'light'`）：
      目的是"喂错值时给出的色板仍与**屏幕上真正生效**的那套一致"，
      避免主窗口拿到与画面不符的颜色去 `setattr(theme, …)` 造成深浅混搭 ✗
    """
    m = _norm(mode)
    if m is None:
        m = current()
    return m if m in MODES else 'light'


def palette(mode=None, tuples=None):
    """⭐ **T6 §7② 治本**：默认返回**双色元组**色板 `{键: (浅色值, 深色值)}`（21 个键）

    **为什么要元组**（§7② 的根因）：`ctk.set_appearance_mode()` **只自动更新"没显式给色"
    的控件**；上一版主窗口 52 处写了 `fg_color=_p['card']`（**建窗那一刻的单值快照**）
    ⇒ 切换后那些控件全停在旧色 ✗✗ ⇒ 改成元组后，控件自己就带两套色 ⇒ **一切全换** ✓

    参数
    ----
    `mode`   `None` ⇒ 返回**双色元组**（给 ctk 控件用，推荐 ✓）
             `'light'`/`'dark'` ⇒ 返回**该模式的单值色板**（给 tk 控件 / 探针 / 门禁用 ✓）
    `tuples` 显式覆盖上面那条推断（`True`/`False`；`None` = 按 `mode` 推断 ✓）

    ⚠ 两种形态的**键完全一样**（21 个），只是值一个是元组一个是字符串 ✓
    ⚠ 一律返回**副本**（铁律④）：调用方随便改，改不到本模块的表 ✓
    """
    try:
        if tuples is None:
            tuples = bool(_TUPLE_KEYS) and (mode is None)
        if not tuples:
            return dict(_PALETTES.get(_resolve(mode), _P_LIGHT))
        out = {}
        for k in _P_LIGHT:
            out[k] = (_P_LIGHT.get(k), _P_DARK.get(k, _P_LIGHT.get(k)))
        return out
    except Exception:               # noqa: BLE001
        return dict(_P_LIGHT)


def palette_flat(mode=None):
    """**单值**色板（= `palette(mode)` 的老行为；给 tk 控件 / 探针 / 门禁用 ✓）"""
    return palette(mode, tuples=False)


def board_colors(mode=None):
    """当前（或指定）模式的**棋盘色板** ⇒ 新 dict

    键（13 个，**逐字 = `theme.py` 的同名常量名**，§T6 §Step 1/§Step 3）：
    BOARD_BG / BOARD_FOG / BOARD_PLAIN / BOARD_CONTENT / BOARD_CAMP / BOARD_EDGE /
    BOARD_BLOCKED / C_TEXT / C_TEXT_DIM / C_PRIMARY / C_DANGER / C_ON_FOG /
    C_BLOCKED_HATCH

    ⭐ 用法（主窗口 §Step 3/§Step 4）::

        from . import theme
        for k, v in ctk_theme.board_colors().items():
            setattr(theme, k, v)         # ⚠ 键名对不上就静默不生效
        # …然后重画棋盘 / 重设日志框底色（tk 控件不会自己跟着 ctk 变 ✗）

    ⚠ 返回**副本**（铁律④）✓
    """
    return dict(_BOARDS.get(_resolve(mode), _B_LIGHT))


def label(key):
    """模式的中文名（给 `CTkSegmentedButton` 用）⇒ `'浅色'` / `'深色'`

    `'light'`→`'浅色'`、`'dark'`→`'深色'`；**认不出 ⇒ `'浅色'`**（§T6 §Step 1，绝不抛）
    ⚠ `'浅色'`/`'深色'` 本身也认（回环 ⇒ 控件里读到的中文名再喂回来不会掉成 `'浅色'`）✓
    """
    return LABELS.get(_norm(key), '浅色')


# ══════════════════════════════════════════════════════════════════════
# 七、持久化：`runs/.ui_theme`（§T6 §Step 1「记住用户选择」/ §Step 4 ③）
# ══════════════════════════════════════════════════════════════════════
def _pref_dir():
    """偏好文件所在目录（= `runs/`）；**绝不抛**

    优先级：① 环境变量 `MAPBOT_UI_THEME_DIR`（探针/门禁的临时场景）
            ② `<mapbot_pc>/runs`（= 本包父目录下的 `runs/` ⇒ **与 cwd 无关**，
               双击 `启动.bat` / pythonw 从任何目录拉起都指向同一个文件 ✓）
            ③ 兜底 `runs`（相对 cwd；只在 `__file__` 都取不到时才会走到）
    ⚠ 用"包父目录"而不是 cwd：`tools/` 下的脚本、快捷方式、任务计划拉起的 cwd
      各不相同 ⇒ 用 cwd 会**每次换一个偏好文件**（看着像"记不住选择" ✗）✓
    """
    try:
        env = os.environ.get(ENV_PREF_DIR)
        if env and env.strip():
            return env.strip()
    except Exception:               # noqa: BLE001
        pass
    try:
        here = os.path.dirname(os.path.abspath(__file__))       # …/bot_gui_ui
        return os.path.join(os.path.dirname(here), 'runs')      # …/mapbot_pc/runs
    except Exception:               # noqa: BLE001
        return 'runs'


def load_pref():
    """读 `runs/.ui_theme` ⇒ `'light'` / `'dark'`

    ⚠ **读不到 / 坏值 / 文件是目录 / 无权限 / 编码是垃圾 ⇒ 一律 `'light'`**（绝不抛）：
      偏好文件是"锦上添花"，**绝不能**因为它坏了就起不了窗 ✗
    ⚠ 容忍 BOM 与首尾空白（`'dark\\n'` / `'\\ufeffDark'` 都认）；内容非法 ⇒ `'light'` ✓
    """
    try:
        p = os.path.join(_pref_dir(), PREF_FILE)
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            txt = f.read(64)        # 只可能是 'light'/'dark' ⇒ 读 64 字节足够，防超大文件
    except Exception:               # noqa: BLE001
        return 'light'
    got = _norm(txt.replace('\ufeff', ''))
    return got if got in MODES else 'light'


def save_pref(mode=None):
    """写 `runs/.ui_theme`（内容 `'light'` / `'dark'` ＋ `\\n`，**LF**）⇒ `True` / `False`

    · `mode` 省略 / `None` ⇒ 写**当前**模式（§Step 4 ③：切换后落盘）；
    · 坏 `mode` ⇒ **不写**、返回 `False`（宁可不动用户的偏好，也不把垃圾写进磁盘 ✓）；
    · 目录不存在 ⇒ 先 `makedirs`（首次运行 `runs/` 可能还没有 ⇒ 这是**正常**路径）；
    · 任何失败（只读盘 / 无权限 / 路径是目录…）⇒ `False`，**绝不抛** ✓
    ⚠ 显式 `newline='\\n'`：Windows 上默认会写出 `\\r\\n`（本仓文件一律 LF，保持一致 ✓）
    """
    if mode is None:
        m = current()
    else:
        m = _norm(mode)
        if m is None:
            return False
    try:
        d = _pref_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:           # noqa: BLE001  （已存在 / 竞态 ⇒ 无视，靠下面的 open 定成败）
            pass
        with open(os.path.join(d, PREF_FILE), 'w', encoding='utf-8', newline='\n') as f:
            f.write(m + '\n')
        return True
    except Exception:               # noqa: BLE001
        return False
