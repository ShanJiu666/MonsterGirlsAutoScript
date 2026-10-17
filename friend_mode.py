# -*- coding: utf-8 -*-
"""friend_mode.py · 「朋友版」运行期开关（用户 2026-10-03）

为什么要有这个文件
------------------
"发给朋友的包"和"我自己用的"在默认值上不一致（朋友版：关精确规划、不存图、窗口里
不显示那两个勾选框）。原来是 `_tmpman/build_pkg.py` **打包时字符串替换源码**实现的。

⭐ 一旦有了逻辑热更，那种做法立刻变成 bug：补丁是按**仓库源码**生成的（= 开发版），
   一发补丁就把朋友版的差异**冲回开发版** ✗。⇒ 改成运行期判断：

    打包时：在**包根**写一个空的 `friend_mode.flag`
    bootstrap.py：见到这个 flag ⇒ `os.environ['MAPBOT_FRIEND'] = '1'`
    本模块：读环境变量 / flag ⇒ `IS_FRIEND`

⇒ 补丁里带的是同一份源码，行为由"包根有没有那个 flag"决定 ⇒ **与热更彻底解耦** ✓
   ⚠ 开发机（仓库里）没有 flag，也（通常）没有环境变量 ⇒ 完全保持开发版行为不变 ✓

优先级：环境变量 `MAPBOT_FRIEND`（1/0） > 包根 `friend_mode.flag` > 默认（开发版）
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# ⚠⚠ 两个位置都要看（2026-10-03 实战踩到）：
#   ① 发布包里 `friend_mode.flag` 在**包根**（与 venv/mapbot_pc 同级），bootstrap.py 读它并设
#      环境变量 `MAPBOT_FRIEND=1` —— 正常链路走这条 ✓
#   ② **但只要不是通过 bootstrap 启动**（有人直接双击 `mapbot_pc\bot_gui.py`、或用老式
#      `启动.bat`、或从别处拷来的半成品包），环境变量就没人设 ⇒ 掉回开发版
#      ⇒ 表现成"发给朋友了却还有精确规划/存图勾选框" ✗✗
#   ⇒ 所以这里也认**文件**：同目录一份、包根（上一层）一份，双保险 ✓
FLAG = os.path.join(HERE, 'friend_mode.flag')
FLAG_PKG = os.path.join(os.path.dirname(HERE), 'friend_mode.flag')


def _from_env():
    v = (os.environ.get('MAPBOT_FRIEND') or '').strip().lower()
    if v in ('1', 'true', 'yes', 'on'):
        return True
    if v in ('0', 'false', 'no', 'off'):
        return False
    return None


_ENV = _from_env()
if _ENV is not None:
    IS_FRIEND = _ENV
    REASON = '环境变量 MAPBOT_FRIEND=%s' % os.environ.get('MAPBOT_FRIEND')
elif os.path.isfile(FLAG):
    IS_FRIEND = True
    REASON = 'mapbot_pc 内有 friend_mode.flag'
elif os.path.isfile(FLAG_PKG):
    IS_FRIEND = True
    REASON = '包根有 friend_mode.flag（%s）' % FLAG_PKG
else:
    IS_FRIEND = False
    REASON = '默认（开发版）'

# 朋友版的固定默认值（供 explore_loop / bot_gui 直接取用）
SOLVER_DEFAULT = not IS_FRIEND          # 精确规划
SAVE_FIRST_DEFAULT = not IS_FRIEND      # 存图（进图首帧）
