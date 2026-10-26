# -*- coding: utf-8 -*-
"""verify_stop_no_afterwork.py · 回归：预言石碑 / 红装停了却还自动重开

## 用户报告（2026-10-26）
    「🛑🛑 抽到【元素·橙色】⇒ 立即停止（不退图，留着你自己处理）
      › ★ 抽到【元素·橙色】· 已停下，请手动处理。
      **因为预言石碑和红装停止的不要运行收工日常等等**」

## 真机铁证（runs/gui_20261026_184021.log，设备 16384，10-26）
    收工日常**确实被正确跳过了** ✓：
        「· 停止原因「预言石碑抽到要停的卡 → 立即停止（现场保留）」
          不是"体力用尽" ⇒ **跳过收工日常**（公会日常/免费招募/免广告都不碰 ✓）」
    **但紧接着又自动重开了** ✗✗：
        「   · 体力 **1507 > 100** ⇒ 够再刷一轮 ✓」
        「🔁 **体力够（>100）⇒ 重新开刷**（第 1 次重开）」
    ⇒ 又进图 → 又撞同一个面板 → 又停 → 又重开 …… 共 **5 轮** ✗

## 根因：两处判据不同源
    · 收工日常（`_ok_daily`）：**白名单** —— stopped 为空 或 含「体力」⇒ 才做 ✓
    · 自动重开（`_should_relaunch` ①）：**黑名单** —— 只排除「用户点了停止」✗
      ⇒ 「预言石碑…」「发现红装…」「到点自动停止…」全漏 ⇒ 停完又重开 ✗

## 修法：收成一份白名单 `_stop_allows_afterwork()`，两处都调它

用法：
    python tests\verify_stop_no_afterwork.py
"""
import os
import sys

_os = os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_HERE)
CORE = _os.path.join(ROOT, "core")
for _p in (CORE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    _os.chdir(ROOT)
except OSError:
    pass
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []


def ck(name, cond, detail=''):
    _d = ('' if not detail else (detail if isinstance(detail, str) else str(detail)))
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name, ('  ' + _d) if _d else ''))
    if not cond:
        FAILS.append(name)


# ⛔ 代码里**真实存在**的停止原因（逐条对拍，不许编）
#   来源：core/explore_loop.py 里每一处 `STATS['stopped'] = ...`
#   期望：True = 允许做收工后续（公会日常/免广告/免广 + 自动重开）
#        False = 一律不做（要人工处理 / 出错 ⇒ 等用户）
STOP_CASES = [
    # ---- 允许（唯一两种）----
    ('', True, '正常跑完（stopped 为空）'),
    ('体力 37 不足（要 50）', True, '体力用尽（真机那条）'),
    ('进图失败（体力不足 / 不在选图界面）', True, '含「体力」⇒ 保持现状'),
    # ---- 不允许：人要手动处理 ----
    ('用户点了停止', False, '用户点了停止'),
    ('发现红装（SS）标记 → 立即停止（现场保留）', False, '红装（用户点名要拦）'),
    ('预言石碑抽到要停的卡 → 立即停止（现场保留）', False, '预言石碑（用户点名要拦）'),
    ('到点自动停止（04:58）', False, '到点该停'),
    # ---- 不允许：出错 ----
    ('账号被其他设备顶下线', False, '顶号'),
    ('账号被顶下线', False, '顶号（另一处文案）'),
    ('游戏自动恢复失败', False, '恢复失败'),
    ('连续 3 张图进不去（进图步骤报错）', False, '连着进不去'),
    ('退图失败（采图模式）', False, '退图失败'),
    ('退图失败', False, '退图失败（短文案）'),
    ('连续 5 张图认不出棋盘（画面被判"被面板挡住"）｜诊断帧：x', False, '认不出棋盘'),
    ('连续 3 张图计划走不下去（目标不可达，画面正常）｜日志：x', False, '计划走不下去'),
    ('连续 3 次把游戏拉回来、但下一张仍跑不动', False, '拉回后仍跑不动'),
    ('手动中断（Ctrl+C）', False, '手动中断'),
    ('崩溃：RuntimeError(...)', False, '崩溃'),
]

def main():
    print('=' * 78)
    print('预言石碑 / 红装停了却还自动重开（2026-10-26 用户报）')
    print('=' * 78)

    import explore_loop as EL

    print()
    print('【1】抽出了共用判据 `_stop_allows_afterwork()`')
    ck('`explore_loop._stop_allows_afterwork` 存在',
       hasattr(EL, '_stop_allows_afterwork'))

    print()
    print('【2】撤回守门：两处判据都改用共用判据')
    ap = _os.path.join(CORE, 'explore_loop.py')
    src = open(ap, encoding='utf-8').read()
    s = src.find('def _should_relaunch(')
    e = src.find(chr(10) + chr(10) + 'def ', s + 10)
    sr = src[s:e] if s >= 0 else ''
    d = src.find('def _stop_allows_afterwork(')
    dd = src.find(chr(10) + chr(10) + 'def ', d + 10)
    hd = src[d:dd] if d >= 0 else ''
    ck('`_should_relaunch` 调共用判据',
       '_stop_allows_afterwork' in sr)
    ck('`_should_relaunch` 里不再有「用户点了停止」黑名单',
       chr(39) + '用户点了停止' + chr(39) + ' in _stop' not in sr)
    ck('共用判据本身是白名单（含「体力」放行）',
       chr(39) + '体力' + chr(39) + ' in _stop' in hd)
    ck('共用判据是空则放行（正常跑完也做收工）',
       'if not _stop:' in hd)

    print()
    print('【3】执行级：代码里每一条真实停止原因逐条对拍')
    _orig = dict(EL.STATS)
    try:
        for _stop_text, _want, _label in STOP_CASES:
            EL.STATS['stopped'] = _stop_text
            _got, _why = EL._stop_allows_afterwork()
            ck('%-26s => %s' % (_label, '允许' if _got else '不碰'),
               _got is _want,
               repr(_stop_text))
    finally:
        EL.STATS.clear()
        EL.STATS.update(_orig)

    print()
    print('【4】对照项：判据不许恒真（否则等于没修）')
    EL.STATS['stopped'] = '体力 37 不足（要 50）'
    _g1, _ = EL._stop_allows_afterwork()
    EL.STATS['stopped'] = '预言石碑抽到要停的卡 → 立即停止（现场保留）'
    _g2, _ = EL._stop_allows_afterwork()
    EL.STATS['stopped'] = '发现红装（SS）标记 → 立即停止（现场保留）'
    _g3, _ = EL._stop_allows_afterwork()
    ck('体力用尽 => True', _g1 is True)
    ck('预言石碑 => False', _g2 is False)
    ck('红装 => False', _g3 is False)
    ck(
       '三个样本给出两种不同结论（证明不是恒值）',
       len({_g1, _g2, _g3}) == 2 and _g1 != _g2 and _g2 == _g3)

    print()
    print('【5】收工日常与自动重开必须同一份判据（不许各写一份）')
    g = src.find("_ok_daily = bool(STATS.get('maps'))")
    ck('`_ok_daily` 那行还在（白名单口径没被改回）', g >= 0)
    win = src[max(0, g - 400):g + 200]
    ck('`_ok_daily` 附近调了共用判据',
       '_stop_allows_afterwork' in win)


    # ---- ⑥ ⭐⭐ 执行级：直接调 `_should_relaunch`（真机那个场景）----
    print()
    print('【6】执行级：直接调 `_should_relaunch`（真机现场复现）')
    _orig2 = dict(EL.STATS)
    try:
        # 真机现场：第 31 张图抽到元素·橙色停下，体力 1507，勾了收工日常
        EL.STATS['stopped'] = '预言石碑抽到要停的卡 → 立即停止（现场保留）'
        EL.STATS['maps'] = 30
        _ok_r, _why_r = EL._should_relaunch(None)
        ck('真机场景（预言石碑停 + 体力 1507 + 勾了日常）⇒ **不重开**',
           _ok_r is False,
           _why_r[:60])
        EL.STATS['stopped'] = '发现红装（SS）标记 → 立即停止（现场保留）'
        _ok_r2, _why_r2 = EL._should_relaunch(None)
        ck('红装停 ⇒ **不重开**', _ok_r2 is False, _why_r2[:60])
        EL.STATS['stopped'] = '体力 37 不足（要 50）'
        _ok_r3, _why_r3 = EL._should_relaunch(None)
        # 体力用尽 ⇒ 白名单**放行**（后面 ②③④ 再决定）
        #   ⇒ 判据① 不该拦 ⇒ 原因里**不许**出现白名单那句「⇒ **不重开**」
        ck('体力用尽 ⇒ 判据① **放行**（没被白名单拦下）',
           '不重开' not in _why_r3,
           _why_r3[:60])
    finally:
        EL.STATS.clear()
        EL.STATS.update(_orig2)

    print('=' * 78)
    if FAILS:
        print('FAIL %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('全部通过：预言石碑/红装/用户停止/到点 => 一律不做收工后续'
          '（公会日常、免广告、免广、自动重开全都不碰）；'
          '体力用尽 / 正常跑完 => 照旧做')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
