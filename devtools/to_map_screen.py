# -*- coding: utf-8 -*-
"""to_map_screen.py · 把游戏带回「选图界面」（只认文本，绝不盲点）

为什么需要它（2026-09-27 实测）：实例B采图跑到第 13 张时**游戏自己重启了**
（现场截图 = 「登录成功」启动画面 ⇒ 不是退图逻辑的问题），
重启后停在大厅 ⇒ `ensure_in_map` 找不到「进入地图 / 快速扫荡」⇒ 一直等到 40 秒超时。

⭐ 用户口径（2026-09-27）：「**点中间的开始冒险就能回到选图界面**」
   ⇒ 认出大厅就点底部中间的「开始冒险」，这就是本条恢复路径的正解。

----------------------------------------------------------------------------
三界面判别（`_probe_lobby_sig.py` 实测 OCR 对拍，2026-09-27）

    特征                              大厅   选图界面  地图界面
    底部导航(角色/斗技场/图鉴/开始冒险)  ✓      ✓        ✓    ← **不可用**（全局导航）
    四角入口 攻略/活动/首充/情报        ✓      ✗        ✗    ← 大厅判据 ✓
    「免费指定招募」横幅                ✓      ✗        ✗    ← 大厅判据 ✓
    帮助 + NNN% / 当前难度NNN           ✗      ✓        ✓
    快速扫荡 / 进入地图 (y≈1618)        ✗      ✓        ✗    ← 选图界面判据 ✓
    结束冒险(y≈773) + 图名[难度]        ✗      ✗        ✓    ← 地图判据 ✓

⚠ 用户的硬规则：底部中间 (541,1890) 这个「万能位」**没弹窗时是「开始冒险」，绝不可盲点**。
  所以这里**必须先 OCR 真认到 `开始冒险` 文本、且 `in_lobby()` 为真**才点；
  认不到就只做保守的返回/关闭。安全边界收在最严的一档。

用法：
    python to_map_screen.py                          # 实例B 16416 / tag=acc2
    python to_map_screen.py --device 127.0.0.1:16384 --tag ""
    python to_map_screen.py --dry                    # 只看状态，不点任何东西
"""
import argparse
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
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)
from mapbot import Bot                  # noqa: E402
import explore_loop as EL               # noqa: E402


MENU_HINTS = ('快速扫荡', '进入地图', '星界秘境', '当前难度')     # 选图界面/图内共有


def where(b, items, img):
    """→ 'in_map' | 'menu'（选图界面=目的地）| 'lobby' | 'other'

    ⚠ 不要直接依赖 `EL.is_map_screen()` 判目的地：它含「开始冒险」这个**三者都有**的
      全局导航文本（虽已加 `in_lobby()` 守卫，但语义太宽）。这里 `menu` 只认
      **选图界面专有**的 L['menu']=（快速扫荡 / 进入地图）。
    """
    if EL.in_map(b, img, items):
        return 'in_map'
    if EL.in_lobby(items):
        return 'lobby'
    if EL.fb(items, *EL.L['menu']):
        return 'menu'                       # ⭐ 选图界面（进入地图就在这）
    txt = [i.get('text') or '' for i in (items or [])]
    if any(h in t for h in MENU_HINTS for t in txt):
        return 'menu'
    return 'other'


def main():
    ap = argparse.ArgumentParser(description='把游戏带回选图界面（认到「开始冒险」才点）')
    ap.add_argument('--device', default='127.0.0.1:16416')
    ap.add_argument('--tag', default='acc2')
    ap.add_argument('--dry', action='store_true', help='只看状态不点')
    ap.add_argument('--tries', type=int, default=8)
    a = ap.parse_args()

    b = Bot(log_prefix='tomap', serial=a.device, tag=a.tag)
    last = None
    for k in range(a.tries):
        b.snap('tomap%d' % k)
        img = b.img()
        items = b.ocr(min_conf=0.3, tag='tomap')
        texts = [i['text'] for i in items]
        st = where(b, items, img)
        print('[%d] 状态=%s  OCR=%s' % (k, st, texts[:16]))
        if st in ('in_map', 'menu'):
            out = os.path.join(b.runs, '_to_map.png')
            try:
                import cv2 as _cv2
                _cv2.imencode('.png', img)[1].tofile(out)
            except Exception:       # noqa: BLE001
                out = None
            print('✓ 已到 %s ⇒ 停手（截图 %s）' % (st, out))
            return 0
        if a.dry:
            print('--dry：不点任何东西，退出')
            return 0
        # ⭐① 大厅 → 点底部中间「开始冒险」（唯一正解；内部已含「必须认到文本」守卫）
        if st == 'lobby':
            if EL.go_lobby_to_menu(b, _LOG):
                time.sleep(1.0)
                continue
            print('    ⚠ 在大厅但没认到「开始冒险」文本 ⇒ 不盲点，停手')
            break
        # ② 别处（登录画面 / 弹窗 / 未知）→ 只点明确读到的 返回/关闭/取消/确定
        adv = None
        for it in items:
            if '开始冒险' in (it.get('text') or '') and it['cy'] > EL.LAYOUT.sy(1600):
                adv = it
                break
        if adv:
            print('    → OCR 认到「开始冒险」@(%d,%d) 置信 %.2f ⇒ 点它'
                  % (adv['cx'], adv['cy'], adv.get('conf', 0)))
            b.tap(adv['cx'], adv['cy'], wait=2.5)
            time.sleep(1.0)
            continue
        back = None
        for it in items:
            t = (it.get('text') or '').strip()
            if t in ('返回', '关闭', '取消', '确定', '确认', '点击开始', '进入游戏'):
                back = it
                break
        if back:
            print('    → 认到「%s」⇒ 点掉它' % back['text'])
            b.tap(back['cx'], back['cy'], wait=1.5)
            last = back['text']
            continue
        print('    ⚠ 既没有「开始冒险」也没有返回/关闭 ⇒ 不再乱点，停手')
        break
    print('✗ 没能回到选图界面（请人工看一眼模拟器）')
    return 1


_LOG = []           # 只为把 go_lobby_to_menu 的日志收下（不落盘）


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        for e in _LOG[-8:]:
            print('      · %s' % e)
