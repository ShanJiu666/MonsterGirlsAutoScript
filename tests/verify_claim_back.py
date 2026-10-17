# -*- coding: utf-8 -*-
"""verify_claim_back.py · 回归：领奖后必须能**找到并点掉**奖励面板的「返回」

为什么写这个
------------
2026-10-04 真机事故（用户原话）：**「领取后还是没点返回，综合现在就卡在返回界面」**
  日志铁证：`claim_back_ok {at: None, via: none, polls: 3, secs: 8.0}`
  ⇒ 3 轮都没读到「返回」⇒ 放弃 ⇒ 奖励面板一直盖着棋盘 ✗

⚠⚠ 根因**不是模板/判据不准**，是 **"同帧读旧帧"那个老坑的第三例**：
  `b.ocr()` 在 PC 上用 `b.img()` = **上一次 `snap()` 的缓存帧**（不会自己重抓），
  而那个轮询循环里**一次 `b.snap()` 都没有** ⇒ 几轮读的全是**同一张**
  「点完『领取』那一瞬」的过渡帧（面板还没画出来）⇒ 永远找不到 ✗✗
  （前两例：`start_fight` docstring、`_tap_verified`）

所以本门禁的关键是**控制组**：
  ① 正常组：假 Bot **会**按时钟换帧（模拟真实 `snap()`）⇒ 必须找到 ✓
  ② 控制组：把 `snap()` 打桩成**空操作**（= 复现旧 bug，帧永远停在面板出现前）
     ⇒ **必须找不到**。这一条要是"也能找到"，说明本测试**没有牙齿**、
     根本盖不住那个 bug ⇒ 同样判失败 ✓

用法：
    python verify_claim_back.py
"""
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
import time

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import fixed as F                           # noqa: E402
import explore_loop as EL                   # noqa: E402


FAILS = []
PANEL = os.path.join(HERE, '_verify', 'claim_now_20261003.png')   # 真机帧：「返回」(359,1196)
BACK_AT = (359, 1196)


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _load(f):
    try:
        if not os.path.exists(f) or os.path.getsize(f) < 1024:
            return None
        im = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:                       # noqa: BLE001
        return None
    return im if (im is not None and im.shape[:2] == (F.PC_H, F.PC_W)) else None


def _map_frame():
    """一张**没有「返回」**的地图帧（当"面板还没出现"的那一屏）

    ⚠ 每张都要真 OCR 一遍才知道有没有「返回」⇒ **限 4 张**（不然本门禁会慢得没必要）
    """
    import glob
    for f in sorted(glob.glob(os.path.join(HERE, 'runs', 'loop_*.png')))[:4]:
        im = _load(f)
        if im is None:
            continue
        if not any('返回' in (t or '') for t in _ocr_real(im)):
            return im
    return None


_OCR = None


def _ocr_real(im):
    """真 OCR（全屏）⇒ 返回文本列表"""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR(use_cls=False)
    cv2.imencode('.png', im)[1].tofile(os.path.join(HERE, '_cbtmp.png'))
    res, _ = _OCR(os.path.join(HERE, '_cbtmp.png'))
    return [t for _b2, t, c in (res or []) if c > 0.5]


class PanelBot:
    """假 Bot：**按时钟**喂帧 —— 面板在 tap 之后 `delay` 秒才出现

    ⚠ 必须按时间（不能按"第几次 snap"）：`claim_back_poll` 每轮都 snap，
      按次数喂帧会让"有没有 snap"这件事看不出差别 ⇒ **测不出那个 bug** ✗
    """

    def __init__(self, pre_im, panel_im, delay):
        self.pre_im = pre_im
        self.panel_im = panel_im
        self.delay = delay
        self.t0 = time.time()
        self.taps = []
        self._img_arr = pre_im
        self._cache = {}
        import mapbot as MB
        self._mb = MB.Bot.__new__(MB.Bot)
        self._mb.runs = HERE
        self._mb.t = {'ocr': 0.0, 'ocr_n': 0}
        self._mb._img_arr = pre_im
        self.snap_works = True          # ← 控制组：置 False 复现旧 bug

    def _frame_now(self):
        return self.panel_im if (time.time() - self.t0) >= self.delay else self.pre_im

    def snap(self, name=None, save=False):
        if not self.snap_works:
            return name                 # 空操作 = 帧永远停在 pre（复现旧 bug）
        self._img_arr = self._frame_now()
        self._mb._img_arr = self._img_arr
        return name

    def img(self):
        return self._img_arr

    def tap(self, x, y, wait=1.2):
        self.taps.append((int(x), int(y)))
        return True

    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        key = (id(self._img_arr), band, min_conf)
        if key in self._cache:
            return self._cache[key]
        items = self._mb.ocr(min_conf=min_conf, img=self._img_arr, band=band, tag=None)
        self._cache[key] = items
        return items


def _warm_ocr():
    """⭐ 2026-10-14 **本测试自己修的一处 flaky**（不是被测代码的 bug）

    ---- 现象（我实测复现过）----
      同一份代码连跑 3 次：**2 次通过、1 次失败** ✗
      失败时：`at=None polls=1 secs=10.3`
    ---- 根因（用时序量出来的）----
      本测试的 budget 只有 **8.0 s**，每轮 = `snap` + **OCR** + `sleep(0.5)`。
      而 **RapidOCR 第一次调用是冷启动**：
          引擎初始化   0.50 s
          **第一次** OCR **4.26 s**   ← 冷启动
          第二次     OCR   1.20 s   ← warm
      ⇒ 若第一轮正好撞上冷启动（4.26s + 0.5s 等待 > 1.0s 的面板出现延迟），
        第一轮就读到**面板出现前**那帧 ⇒ `polls=1` ⇒ 8s 预算当场耗光 ⇒ 判红 ✗
      ⇒ 与"漏 snap 那个 bug"**毫无关系**，是测试自己的时序太紧 ✓
    ---- 为什么以前偶尔绿 ----
      上一轮别的测试（`verify_gate` 并发预取）**已经预热过 OCR 引擎** ⇒ 本测试一上来就是 warm ✓
      而单独跑、且是那次进程里第一个 OCR ⇒ 撞冷启动 ⇒ 红 ✗
    ---- 修法 ----
      **开跑前先热一次引擎**（拿真机帧空跑一遍，不进断言）✓
      ⇒ 断言里的 OCR 一律是 warm ⇒ 时序余量从"几乎没有"变成"数倍" ✓
    ⚠⚠ 必须热**对的那个引擎**（我第一版热错了，白修一轮 ✗）：
      · 本测试里有**两个** OCR 引擎实例：
          ① `_ocr_real()` 里自己 `RapidOCR(...)` 建的那个（`_OCR` 全局）
          ② `PanelBot.ocr()` 走的是 **`mapbot._ocr()`** 的单例（`self._mb.ocr(...)`）
      · 断言用的全是 ② ⇒ **必须热 ②**；热 ① 对断言毫无帮助 ✗
      · 判据：`import mapbot; mapbot._ocr()` 调一次即可（它内部有单例缓存 ✓）
    """
    try:
        panel = _load(PANEL)
        if panel is None:
            return
        print('   （预热 OCR 引擎：冷启动那一下实测 4.26s，会吃掉本测试 8s 预算）')
        import mapbot as MB
        _eng = MB._ocr()                    # ← 热 **mapbot 的单例**（断言用的就是它 ✓）
        import cv2 as _cv
        _tmp = os.path.join(HERE, '_cbwarm.png')
        _cv.imencode('.png', panel)[1].tofile(_tmp)
        t0 = time.time()
        _eng(_tmp)                          # 真正跑一次 ⇒ 触发冷启动的那部分开销
        print('   （预热完成，用了 %.2fs；之后每轮 OCR ≈1.2s ✓）' % (time.time() - t0))
        try:
            os.remove(_tmp)
        except OSError:
            pass
    except Exception as e:              # noqa: BLE001
        print('   （预热失败：%r ⇒ 继续，必要时会重跑）' % (e,))


def main():
    print('=== 领奖「返回」回归（真 explore_loop.claim_back_poll + 真机帧）===')
    panel = _load(PANEL)
    if panel is None:
        print('   （缺 %s ⇒ 跳过本门禁）' % os.path.relpath(PANEL, HERE))
        return 0
    pre = _map_frame()
    if pre is None:
        print('   （找不到"没有返回"的地图帧 ⇒ 跳过）')
        return 0
    print('面板帧：%s（「返回」在 %s）' % (os.path.relpath(PANEL, HERE), BACK_AT))
    print('面板前帧：无「返回」的地图帧')
    print()
    # ⭐ 2026-10-14：**先热 OCR 引擎**（否则冷启动会吃掉 8s 预算 ⇒ 假红 ✗，
    #   见 `_warm_ocr` 的实测数据）✓
    _warm_ocr()
    print()

    # ── ① 正常组：面板 1.0s 后出现 ⇒ 必须找到并点它 ──
    print('【1】正常组：面板 1.0s 后出现 ⇒ 必须找到「返回」并点掉')
    b1 = PanelBot(pre, panel, 1.0)
    log1 = []
    r1 = EL.claim_back_poll(b1, log1, None, budget=8.0)
    ck('找到了「返回」（判据：返回 at 非空）', r1['at'] is not None,
       'at=%s polls=%s secs=%s' % (r1['at'], r1['polls'], r1['secs']))
    ck('点的是**它自己的坐标**（≈%s）' % (BACK_AT,),
       bool(b1.taps) and abs(b1.taps[-1][0] - BACK_AT[0]) <= 6
       and abs(b1.taps[-1][1] - BACK_AT[1]) <= 8, '实际点位 %s' % (b1.taps,))
    ck('确实**等了几轮**（说明不是巧合命中第一帧）', r1['polls'] >= 2, 'polls=%d' % r1['polls'])
    ck('日志记了 claim_back_ok 且 via=full',
       any(isinstance(d, dict) and d.get('explore') == 'claim_back_ok'
           and d.get('via') == 'full' for d in log1))

    # ── ② 控制组：把 snap 打桩成空操作 = 复现旧 bug ⇒ **必须找不到** ──
    #   这一条是"本测试有没有牙齿"的元判据：它要是也能找到，说明帧本来就在变，
    #   那这个门禁根本盖不住"漏 snap"那个 bug ⇒ 判失败 ✓
    print()
    print('【2】控制组（元判据）：`snap()` 打桩成空操作 = 复现旧 bug ⇒ **必须找不到**')
    b2 = PanelBot(pre, panel, 1.0)
    b2.snap_works = False               # ← 帧永远停在"面板出现前"
    log2 = []
    r2 = EL.claim_back_poll(b2, log2, None, budget=6.0)
    ck('旧行为下确实**找不到**「返回」（证明本测试有牙齿）', r2['at'] is None,
       'at=%s polls=%s' % (r2['at'], r2['polls']))
    ck('旧行为下**一次都没点**（不许盲点坐标）', not b2.taps, 'taps=%s' % (b2.taps,))

    # ── ③ 只给地图帧（面板从头到尾没出现）⇒ 不许盲点 ──
    print()
    print('【3】面板始终不出现 ⇒ 不许盲点任何坐标')
    b3 = PanelBot(pre, pre, 99.0)
    log3 = []
    r3 = EL.claim_back_poll(b3, log3, None, budget=2.0)
    ck('没找到「返回」', r3['at'] is None)
    ck('全程**零点击**（不盲点 ✓）', not b3.taps, 'taps=%s' % (b3.taps,))

    # ── ④ 真帧上的搜索成本：全屏为什么替掉了窄带 ──
    print()
    print('【4】真帧实测：全屏 vs 旧窄带 (1140,1240) 的耗时（解释为什么改全屏）')
    import mapbot as MB
    rb = MB.Bot.__new__(MB.Bot)
    rb.runs = HERE
    rb.t = {'ocr': 0.0, 'ocr_n': 0}
    rb._img_arr = panel
    t0 = time.time(); rb.ocr(band=(1140, 1240), tag=None); t_band = time.time() - t0
    t0 = time.time(); rb.ocr(tag=None); t_full = time.time() - t0
    print('   窄带 (1140,1240): %.2f s ｜ 全屏: %.2f s' % (t_band, t_full))
    ck('全屏不比窄带慢（RapidOCR 耗时与带高无关 ⇒ 窄带反而更慢）',
       t_full <= t_band * 1.15, '%.2fs vs %.2fs' % (t_full, t_band))

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：领奖后能找到「返回」；且证明测试对"漏 snap"那个 bug 有牙齿')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    finally:
        try:
            os.remove(os.path.join(HERE, '_cbtmp.png'))
        except OSError:
            pass
