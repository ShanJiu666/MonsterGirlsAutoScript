# -*- coding: utf-8 -*-
"""verify_battle_fast.py · A/B 实测：`battle_started_fast()` 到底省了几次 OCR

为什么写这个
------------
`verify_fastpath.py`【1d】只证了「模板认得准」（正样本命中 / 地图帧不命中），
**没证"它真的省下 OCR"** —— 而省 OCR 才是这次改动的全部目的。
本脚本用**真机帧 + 真 `start_fight()` 代码**做 A/B：

    A 组：快路径**开着**
    B 组：快路径**关掉**（把 `battle_started_fast` 打桩成恒 False = 改动前行为）

⚠⚠ 关键：画面必须**按时间**变，不能按"第几次 snap"变 ✗
  `start_fight` 现在会先跑一段**模板抢跑窗口**（0.12s 一轮、snap 很多次），
  如果假 Bot 按 snap 次数喂帧，A/B 两边看到的帧序列就**不一样** ⇒ 结论不可比。
  （我第一版就是这么写的 ⇒ B 组被窗口"喂"掉了地图帧、算出来只省 1 次，是假象。）
  ⇒ 现在：`ScriptedBot(map, settle, delay)` —— tap 之后 **delay 秒**画面才变成结算面板，
    这才是物理真相（实测 delay 落在 0.65~1.15s，见 `_FAST_POLL_SECS` 注释）。

⚠ 帧全来自 `runs/` 的真机帧（不是合成图），`start_fight` 是**仓库里那一份真代码**
  （不是复制品）⇒ 测的就是热路径 ✓

用法：
    python verify_battle_fast.py
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
import glob

sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

import fixed as F                           # noqa: E402
import explore_loop as EL                   # noqa: E402


FAILS = []
OCR_SEC = 0.52          # 真机分账里 OCR 单次耗时（长跑 276.4s/530 次 ≈ 0.52s）


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def _load(f):
    try:
        if os.path.getsize(f) < 1024:
            return None
        im = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:                       # noqa: BLE001
        return None
    return im if (im is not None and im.shape[:2] == (F.PC_H, F.PC_W)) else None


def _close_score(im):
    mx = 0.0
    for nm in ('close_tpl_0', 'close_tpl_1', 'close_tpl_2'):
        v = F.find(im, nm, box=(0, 780, 720, 1080))
        if v:
            mx = max(mx, v[2])
    return mx


def collect():
    """挑素材：settle = 真结算帧；map = 真地图帧（含「首领战斗胜利」横幅那种）

    ⛔⛔ 2026-10-10 **修「探针垃圾文件污染语料」**（门禁假红，真因不在被测代码 ✗）
      ---- 症状 ----
        `verify_battle_fast.py` 三项红，而**生产代码一行没改** ✗
        实测挑到的素材是 `runs/_a4_tmp.png`（`_close_score` = **0.960** ✓ 过阈值）
      ---- 根因 ----
        原来的候选是 `runs/**/*.png` **全量**（递归、无过滤）——
        而我这些天排查时往 `runs/` 写了 **290 个探针临时文件**（`_a4_tmp.png` /
        `_probe_tmp.png` / `_a6.png` …）
        其中 `_a4_tmp.png` 是一张**棋盘帧**，却因为 `_close_score` 到了 0.960
        被当成了"结算帧" ⇒ 后面 A/B 对比全错 ✗✗
      ---- 修法（**两条都要**）----
        ① 候选**只认生产命名的帧**：`r_*_0.png`（进图首帧）/ `loop_*.png` /
           `m?_r*.png` —— 与本脚本原来挑 map 帧的口径一致 ✓
        ② **排除 `_` 开头**（临时/中间产物一律不是语料 ✓）
      ⚠ 这是个**门禁自身的缺陷**（不是被测代码），与 v1.62c「注释里必然引用旧判据」
        是同一类"测试被无关因素带偏" ✓
    """
    settle, maps = [], []
    # ⛔⛔ 2026-10-13 **取"分数最高"的结算帧，不是"排序第一个"**（门禁自身的缺陷 ✗）
    #   ---- 症状 ----
    #     三项红，而**生产代码一行没改** ✗
    #     实测挑到的是 `runs/acc1/loop_0202.png`（用户当天新跑落下来的帧），
    #     它的 `_close_score` 过了 0.80 **但识别不出「结算面板」**
    #     ⇒ `battle_started` 恒 False ⇒ A/B 三档全 False ⇒ 三项假红 ✗
    #   ---- 根因 ----
    #     原来是 `sorted(...)` 后**取第一个过阈值的** ⇒ 谁的文件名排在前面就用谁
    #     ⇒ 用户跑一局、`runs/` 里多几张 `loop_XXXX.png` ⇒ **素材就换了**
    #     ⇒ 判据随"用户跑没跑图"漂移（同一类"测试被无关因素带偏" ✗）
    #   ---- 修法 ----
    #     把**所有**过阈值的候选**都算一遍**，取 `_close_score` **最高**的那张当结算帧 ✓
    #     ⇒ 语料再多也不影响：真正像结算面板的那张分数必然最高 ✓
    _cand = []
    for f in sorted(glob.glob(os.path.join(HERE, 'runs', '**', '*.png'), recursive=True)):
        _b = os.path.basename(f)
        # ① 排除临时/中间产物（我探针写的 `_xxx.png`）② 只认生产命名
        if _b.startswith('_'):
            continue
        if not _b.startswith(('r_', 'loop_', 'm0_', 'm1_', 'm2_', 'm3_')):
            continue
        im = _load(f)
        if im is None:
            continue
        _sc = _close_score(im)
        if _sc >= 0.80:
            _cand.append((_sc, f, im))
        elif not maps and _b.startswith(('m0_', 'loop_', 'r_')):
            maps.append((f, im))
    if _cand:
        _cand.sort(key=lambda x: -x[0])          # ⭐ 分数最高者优先
        settle.append((_cand[0][1], _cand[0][2]))
        print('     结算帧候选 %d 张，取最高分 %.3f：%s'
              % (len(_cand), _cand[0][0], os.path.basename(_cand[0][1])))
    return settle, maps


class ScriptedBot:
    """按**时间**喂帧的假 Bot —— tap 之后 `delay` 秒，画面变成结算面板

    ⚠ 它**不假装**识别逻辑：`ocr()` 走的是真 `mapbot.Bot.ocr`（真 RapidOCR），
      只是帧按时钟换 ⇒ 判据链 `battle_started(items)` 也是真的 ✓
    """

    def __init__(self, map_im, settle_im, delay):
        self.map_im = map_im
        self.settle_im = settle_im
        self.delay = delay
        self.t_tap = None
        self.ocr_n = 0
        self.ocr_t = 0.0
        self._img_arr = map_im
        self._cache = {}
        import mapbot as MB
        self._mb = MB.Bot.__new__(MB.Bot)     # 借真 Bot 的 ocr()（不连设备）
        self._mb.runs = HERE
        self._mb.t = {'ocr': 0.0, 'ocr_n': 0}
        self._mb._img_arr = map_im

    def _elapsed(self):
        return 0.0 if self.t_tap is None else time.time() - self.t_tap

    def _frame_now(self):
        return self.settle_im if self._elapsed() >= self.delay else self.map_im

    def snap(self, name=None, save=False):
        self._img_arr = self._frame_now()
        self._mb._img_arr = self._img_arr
        return name

    def img(self):
        return self._img_arr

    def tap_dlg(self, x, y, wait=1.2):
        """模型：点下去 ⇒ 画面开始变 ⇒ `wait_change` ~0.3s 后返回 True"""
        if self.t_tap is None:
            self.t_tap = time.time()
        time.sleep(0.3)
        return True

    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        """真 OCR；同**画面**重复问就复用（只影响速度，不影响调用计数 ✓）"""
        self.ocr_n += 1
        key = (self._img_arr is self.settle_im, band, min_conf)
        if key in self._cache:
            return self._cache[key]
        t0 = time.time()
        items = self._mb.ocr(min_conf=min_conf, img=self._img_arr, band=band, tag=None)
        self.ocr_t += time.time() - t0
        self._cache[key] = items
        return items


def run_case(delay, fast_on, window_on, map_im, settle_im):
    """跑一次**真 `start_fight`**：返回 (结果, OCR 次数, 墙上耗时秒, 事件表)

    三档对照（缺一不可）：
      · 新代码      fast_on=True,  window_on=True
      · **改动前**   fast_on=False, window_on=False   ← 这才是真 baseline
      · 只加模板     fast_on=True,  window_on=False   ← 第一次提交那版
    ⚠ "抢跑窗口"是**共享代码**：只关 `battle_started_fast` 而不关窗口，
      B 组自己也会白等一个窗口（面板早就出现）⇒ 数字被窗口篡改、不是真 baseline ✗
      （我第一版就漏了这一点。）打桩 `_FAST_POLL_SECS=0` 即可让窗口整段跳过 ✓
    """
    bot = ScriptedBot(map_im, settle_im, delay)
    log = []
    o_f, o_w = EL.battle_started_fast, EL._FAST_POLL_SECS
    if not fast_on:
        EL.battle_started_fast = lambda _b: False      # 打桩 = 没有模板快路径
    if not window_on:
        EL._FAST_POLL_SECS = 0.0                       # 打桩 = 没有抢跑窗口
    try:
        t0 = time.time()
        ok = EL.start_fight(bot, log, {'cx': 537, 'cy': 490}, marks=['boss'])
        dt = time.time() - t0
    finally:
        EL.battle_started_fast, EL._FAST_POLL_SECS = o_f, o_w
    return ok, bot.ocr_n, dt, log


def events(log):
    return [d.get('battle') for d in log if isinstance(d, dict) and 'battle' in d]


def main():
    print('=== battle_started_fast A/B 实测（真 start_fight + 真机帧 + 按时钟喂帧）===')
    settle, maps = collect()
    if not settle or not maps:
        print('素材不足（需要 runs/ 里有结算帧与地图帧）⇒ 跳过')
        return 0
    s_f, s_im = settle[0]
    m_f, m_im = maps[0]
    print('结算帧：%s' % os.path.basename(s_f))
    print('地图帧：%s（close_tpl 分 %.3f，必须 <0.80 ⇒ 不会误判）'
          % (os.path.basename(m_f), _close_score(m_im)))
    print('抢跑窗口 _FAST_POLL_SECS=%.2f ／ 轮询间隔 _FAST_POLL_GAP=%.2f'
          % (EL._FAST_POLL_SECS, EL._FAST_POLL_GAP))
    print()

    # delay = 结算面板在 tap 之后多久出现
    #   0.90 = 实测区间（0.65~1.15s）的中值，**窗口内** ⇒ 走抢跑快路径
    #   2.20 = 故意超出窗口 ⇒ 验"没命中时兜底是否照旧、不误判、不漏判"
    CASES = (0.90, 2.20)

    print('【1】窗口内（实测典型 0.90s）：三档结论必须一致，且新代码要省 2 次 OCR')
    rows = []
    for d in CASES:
        ok_a, n_a, t_a, la = run_case(d, True, True, m_im, s_im)      # 新代码
        ok_c, n_c, t_c, lc = run_case(d, True, False, m_im, s_im)     # 只加模板
        ok_b, n_b, t_b, lb = run_case(d, False, False, m_im, s_im)    # 改动前
        in_win = d <= EL._FAST_POLL_SECS
        tag = '窗口内' if in_win else '超出窗口'
        print('  ── 面板 tap 后 %.2fs 出现（%s）──' % (d, tag))
        if in_win:
            ck('三者结论一致（都 True）', ok_a is True and ok_b is True and ok_c is True,
               '新=%s / 只模板=%s / 改动前=%s' % (ok_a, ok_c, ok_b))
            ck('vs 改动前：OCR %d→%d 次（**省 %d**）｜ 返回 %.2fs→%.2fs（早 %.2fs）'
               % (n_b, n_a, n_b - n_a, t_b, t_a, t_b - t_a), n_b - n_a >= 2)
        else:
            # ⚠ 这一档**改动前本来就是 False** —— 它的"有效判定窗口"只有 ~2.2s
            #   （2 次 OCR 轮询 + 顶部复核；docstring 写的"最多等 5s"是**名义值**、
            #    实际覆盖不到 5s）。新代码窗口把覆盖拉到 ~4.3s ⇒ 这一档反而**能判出来**。
            #   ⇒ 断言写成"**不许比改动前更差** + 新代码仍要判 True"（变好不算回归 ✓）
            ck('新代码仍判 True（改动前在这一档会漏 ⇒ 新代码是**变好**）', ok_a is True,
               '新=%s / 只模板=%s / 改动前=%s' % (ok_a, ok_c, ok_b))
            ck('新代码不比改动前差（改动前 False 时新代码必须 True）',
               ok_b is False or ok_a is True)
        print('        新代码事件 %s' % (events(la),))
        print('        只模板事件 %s   （省 %d 次 OCR）' % (events(lc), n_b - n_c))
        print('        改动前事件 %s' % (events(lb),))
        rows.append((d, n_a, n_b, t_a, t_b))

    print()
    print('【2】不误判：只给地图帧（战斗并未结算）⇒ 两种模式都必须返回 False')
    bot = ScriptedBot(m_im, m_im, 99.0)          # settle 永远不出现
    log = []
    ok = EL.start_fight(bot, log, {'cx': 537, 'cy': 490}, marks=['boss'])
    ck('地图帧下 start_fight 返回 False（没把地图当结算）', ok is False, '（返回 %s）' % ok)
    ck('地图帧下没有任何 started_fast 事件',
       not any(str(e).startswith('started_fast') for e in events(log)),
       '%s' % (events(log),))

    print()
    print('【3】收益汇总（OCR 单次按真机分账 %.2fs 折算）' % OCR_SEC)
    # 用"窗口内"那一档当典型值（实测 9/9 都落在窗口内）
    d, n_a, n_b, t_a, t_b = rows[0]
    saved_ocr = n_b - n_a
    per_battle = saved_ocr * OCR_SEC + max(0.0, t_b - t_a) * 0.0
    print('   典型一场（面板 %.2fs 后出现）：省 %d 次 OCR ≈ %.2f s'
          % (d, saved_ocr, saved_ocr * OCR_SEC))
    print('   另外**返回更早**：%.2fs → %.2fs（早 %.2fs）——结算流程能提前开始 ✓'
          % (t_b, t_a, t_b - t_a))
    print('   ⇒ 全场 155 场：省 OCR ≈ %.0f 秒（另有提前返回的收益）'
          % (saved_ocr * OCR_SEC * 155))
    _ = per_battle

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：抢跑窗口确实省 OCR、结论不变、不误判、超窗也有兜底')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
