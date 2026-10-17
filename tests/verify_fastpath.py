# -*- coding: utf-8 -*-
"""verify_fastpath.py · 证明「模板快查」真的能替掉 OCR 的存在性判断

三件事：
  ① 正样本：模板在图里 ⇒ 必须命中（否则热路径会瞎跳）
  ② 负样本：把图**挖掉**那块 ⇒ 必须不命中（否则会到处乱跳）
  ③ 速度：同区域模板匹配 vs 条带 OCR，量化差多少倍
"""
import os
import re
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


FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def load_frames(maxn=None):
    """找 720×1280 的真帧。⭐ 优先用**本仓自带的** `_verify/`
    （2026-10-01「两端完全平行」：PC 端不能依赖手机端仓的目录），
    之后再退到本仓 `runs/`。

    ⚠ 2026-10-02：删掉了 `<容器临时区>` 这条兜底 —— 那是**本机**临时目录，
      朋友机器上永远不存在，留着只会让人以为这条路径是必需的。
      真帧已随 `_verify/` 入仓（12 张 720×1280），换机 clone 后自检照样有帧可测 ✓

    ⭐⭐ 2026-10-08 **`maxn` 参数**（治"门禁越跑越慢"）：
      实测 `runs/` 已累积 **2469 张 PNG**（其中 1459 张是 720p）⇒ 无上限地
      `imdecode` 全部 ⇒ **40 秒 + 3.8GB 内存** ✗
      而本文件下游**最远只用到 `frames[:40]`**（导航条 6 张 / 负样本 10 张 /
      settle 40 张）⇒ 全量解码纯属浪费 ✓
      ⇒ 默认取前 `maxn` 张**够用即止**；`MAPBOT_FASTPATH_MAXFRAMES=0` = 全量 ✓
    """
    if maxn is None:
        maxn = int(os.environ.get('MAPBOT_FASTPATH_MAXFRAMES') or 80)
    out = []
    skipped = []
    for d in (os.path.join(HERE, '_verify'),          # ⭐ 本仓自带（换机 clone 后仍在）
              os.path.join(HERE, 'runs')):            # 本仓运行产物（可无）
        if not os.path.isdir(d):
            continue
        for p in sorted(glob.glob(os.path.join(d, '*.png'))):
            if maxn and len(out) >= maxn:
                break
            # ⚠ 2026-10-02 修：先判大小再解码。
            #   `cv2.imdecode` 收到**空 buffer** 抛的是异常（`!buf.empty()` assertion），
            #   不是返回 None ⇒ 以前只要目录里混进一张 0 字节/截断的 PNG，整个门禁就崩
            #   （本机实测：runs/_fastcap_cmp.png 是抓帧中途被停留下的 0 字节文件）。
            #   截图工具随时可能再写一次半张图 ⇒ 这里**一律跳过并计数**，不能让它掀桌子。
            try:
                if os.path.getsize(p) < 1024:        # 太小 ⇒ 必是坏帧（好帧 ~190KB+）
                    skipped.append(p)
                    continue
                img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            except Exception as e:                   # noqa: BLE001  坏文件不许掀桌子
                skipped.append(p)
                print('   ⚠ 跳过坏帧 %s（%r）' % (os.path.basename(p), e))
                continue
            if img is None or img.shape[:2] != (F.PC_H, F.PC_W):
                continue
            out.append((p, img))
    return out, skipped


def main():
    frames, skipped = load_frames()
    print('=== 模板快查验收 ===')
    print('720×1280 真帧 %d 张，模板 %d 个'
          % (len(frames), len(os.listdir(F.TPL_DIR)) if os.path.isdir(F.TPL_DIR) else 0))
    if skipped:
        # ⚠ 坏帧是**截图工具的正常产物**（抓一半被打断），不是代码问题 ⇒ 只提示不判失败
        print('（另有 %d 张坏帧/非 720×1280 帧已跳过：%s）'
              % (len(skipped),
                 '、'.join(os.path.basename(s) for s in skipped[:5])
                 + ('…' if len(skipped) > 5 else '')))
    if not frames:
        print('没有 720×1280 帧可测')
        return 1

    print()
    print('【1】正样本：导航条在图里 ⇒ **5 个导航条模板**都要命中')
    # ⚠ 2026-10-02：这里**只测导航条模板**。原来它遍历 `templates/fixed/` 下**所有**模板，
    #   一旦 fixed 里新增"非导航条"的模板（如选图界面的 `enter_map_btn`），
    #   在导航条带里当然找不到 ⇒ 计数从 5/5 变成 5/6 ⇒ **门禁 ④ 假红**（它 grep 的就是 '命中 5/5'）。
    #   这个检查的**本意**是"导航条在 ⇒ 5 个 tab 模板都必须命中"，所以按本意限定 ✓
    #   新模板的覆盖见下面【1b】（正/负样本齐全，失败同样会让本脚本 exit≠0 ⇒ 门禁照样抓得住）。
    NAV_NAMES = ('nav_guild', 'nav_role', 'nav_start', 'nav_arena', 'nav_dex')
    for p, img in frames[:6]:
        res = {n: F.find(img, n, box=F.BANDS['nav']) for n in NAV_NAMES}
        ok = sum(1 for v in res.values() if v)
        sc = [v[2] for v in res.values() if v]
        ck('%s  命中 %d/%d  分数 %s'
           % (os.path.basename(p), ok, len(NAV_NAMES),
              ['%.2f' % s for s in sc]), ok >= len(NAV_NAMES) - 1,
           '(允许 1 个因遮挡未命中)')

    print()
    print('【2】负样本：把导航条区域涂黑 ⇒ 必须**全部不命中**（否则会到处乱跳）')
    p, img = frames[0]
    blank = img.copy()
    blank[F.BANDS['nav'][1]:, :] = (0, 0, 0)          # 涂掉导航条
    names = [f[:-4] for f in os.listdir(F.TPL_DIR) if f.endswith('.png')]
    # ⭐ 2026-10-03：本项**只测导航条模板** ✓
    #   原因：新增的 `close_tpl_{0,1,2}` 是"结算面板按钮"（搜索区在 y 780~1080 ✗），
    #     把它们也放进来判"涂掉导航条后不许命中"，语义就不对了（它们本来就不在导航条上 ✓）
    #   ⇒ 与【1】同口径，只列 NAV_NAMES ✓
    #   （这几张新模板的**正/负样本验收**见【1c】：82 张真机结算帧 vs 12 张地图帧 ✓）
    names = [n for n in names if n in
             ('nav_guild', 'nav_role', 'nav_start', 'nav_arena', 'nav_dex')]
    res = {n: F.find(blank, n, box=F.BANDS['nav']) for n in names}
    bad = [n for n, v in res.items() if v]
    ck('涂掉后全部不命中', not bad, '仍命中: %s' % (bad or '无'))

    # ── 【1b】⭐ 2026-10-02：选图界面模板 `enter_map_btn`（`fx_menu()` 用的那个）──
    #   正样本 = 真·选图界面帧 —— ⚠ **只用入库的 `_verify/select_map_*.png`**：
    #     `runs/_adb_cmp.png` / `runs/_fastcap_cmp.png` 虽然抓的时候也是选图界面，
    #     但它们是**每次运行都被覆盖**的诊断文件（2026-10-02 实测：23:29 被新帧覆盖后
    #     得分直接掉到 0.000 ⇒ 本项**假红**）⇒ 不能当正样本 ✗
    #   标定实测：正样本 1.000 ／ 负样本最高 0.000 ／ 阈值取 0.80（比 MATCH_MIN 更严）✓
    print()
    print('【1b】选图界面模板 enter_map_btn（正样本必须命中 / 棋盘帧必须不命中）')
    _pos = [im for p2, im in frames
            if os.path.basename(p2).startswith('select_map_')]
    if not _pos:
        print('   （本机没有选图界面真帧 ⇒ 跳过此项；换机 clone 后 _verify/select_map_*.png 会在）')
    else:
        sc_p = []
        for im in _pos:
            v = F.find(im, 'enter_map_btn', box=F.BANDS['enter_btn'])
            sc_p.append(v[2] if v else 0.0)
        ck('正样本 %d 张全部命中（阈值 0.80）' % len(_pos),
           all(s >= 0.80 for s in sc_p), ' '.join('%.3f' % s for s in sc_p))
    _neg = [im for p2, im in frames
            if not os.path.basename(p2).startswith('select_map_')
            # ⚠⚠ 2026-10-03：**排除当天新存的"过程取证帧"** ✗
            #   （`slot_*` / `claim_*` / `slots_*` / `acc2_chk`）—— 它们拍的是
            #   "点槽位→领取→返回"这一串的**中间态**，其中 `claim_back_after` 那张
            #   我点完「返回」后画面**回到了选图界面** ⇒ 里面**真**有「进入地图」按钮 ✓
            #   ⇒ 拿它当"棋盘帧负样本"判"不许命中"，命中了反而是**正确**的 ✗ ⇒ 假红
            and not any(k in os.path.basename(p2)
                        for k in ('slot', 'claim', 'acc2_chk'))][:8]
    sc_n = []
    for im in _neg:
        v = F.find(im, 'enter_map_btn', box=F.BANDS['enter_btn'])
        sc_n.append(v[2] if v else 0.0)
    ck('负样本 %d 张都不命中（最高 %.3f）' % (len(sc_n), max(sc_n) if sc_n else 0.0),
       all(s < 0.80 for s in sc_n))

    # ── 【1c】⭐ 2026-10-03：结算面板「关闭」模板 —— 战斗等待快查用的那 3 张 ──
    #   背景：战斗等待原来每 0.5s OCR 一次 165px 条带（~0.12s/次）；
    #     攒了 82 张真机结算整帧（扫 1600 张历史帧得来）后自动聚成 **3 档**模板：
    #       `templates/fixed/close_tpl_{0,1,2}.png` ⇒ 每轮 3 次模板匹配（~7~20ms ✓）
    #   标定实测：**正样本最低 0.986** ／ **负样本（地图首帧）最高 0.524** ⇒ 阈值 0.80 ✓
    #   ⚠ 样本目录缺失时**跳过**（换机 clone 后没有 `runs/cap_close/` 很正常 ✓）
    print()
    print('【1c】结算面板「关闭」模板 close_tpl_*（正样本必须命中 / 棋盘帧必须不命中）')
    _cap_dir = os.path.join(os.path.dirname(F.TPL_DIR), '..', 'runs', 'cap_close')
    _cap_dir = os.path.abspath(_cap_dir)
    # ⚠⚠⚠ 2026-10-06 **收紧采样口径**（原来 `glob('close_*.png')` 把杂帧也当正样本）
    #
    #   真机发现：这一项报「正样本 **1355** 张全部命中」，可**最低分 0.000** ✗
    #   逐张量过之后：**8 张 < 0.80**，而它们的名字是
    #       `close_hist_dice_ok_1/2`、`close_hist_dice_1/2`、
    #       `close_hist__probe_tmp`、`close_hist__after_restart`、`close_hist__save_probe_1`
    #     ⇒ **历史探针留下的杂帧**（不是结算面板整帧），只是恰好也以 `close_` 开头 ⇒ 被收进来 ✗
    #   ⚠ 而**本次运行新落的 14 张**（`close_battle_1006_145…`）**全部合格** ⇒
    #     证明"模板匹配本身没坏"，是**门禁的采样口径太宽** ✓
    #   ⇒ 判据收紧为**真结算帧的命名规则** `close_battle_<4位日期>_<6位时刻>_<3位序号>.png`
    #     （`_cap_close()` 的命名就是 `close_battle_1006_145044_013.png` 这样：
    #       `_1006_` 是 MMDD、`_145044_` 是 HHMMSS ⇒ **6 位时刻**，别写成 8 位日期 ✗
    #       —— 我第一版就按 8 位日期写，结果把 **1355 张全跳过** ⇒ 正样本 0 张 ✗已修）
    #     （杂帧一律不进正样本集合 ✓）
    #   ⚠ 名称不符的**不删**、也不报错，只是**不作为正样本**（保持"夹具不动"的规矩 ✓）
    _all_cp = sorted(glob.glob(os.path.join(_cap_dir, 'close_*.png')))
    _RE_REAL = re.compile(r'^close_battle_\d{4}_\d{6}_\d{3}\.png$')
    _cp = [p for p in _all_cp if _RE_REAL.match(os.path.basename(p))]
    # ⚠⚠ 命名对了但**内容是坏帧**的也要剔掉（判据要钉"它真是结算面板"，不是只看文件名）
    #   实例：`close_battle_1006_135150_000.png` 只有 **4878 B**、**整帧纯黑**
    #   （抓帧失败/模拟器黑屏的产物）⇒ 匹配分 0.000 ⇒ 又把整项判红 ✗
    #   ⇒ 用「整帧亮度几乎为 0」这条**内容判据**排除（比大小阈值更直接、也更能解释 ✓）
    _cp_bad = []
    _cp_ok = []
    for p in _cp:
        _im = cv2.imread(p)
        if _im is None or float(_im.mean()) < 2.0:      # 全黑/读不出 ⇒ 不是结算面板
            _cp_bad.append(os.path.basename(p))
        else:
            _cp_ok.append(p)
    if _cp_bad:
        print('   ⚠ 再剔除 %d 张**全黑坏帧**（抓帧失败的产物，不是结算面板）：%s'
              % (len(_cp_bad), ', '.join(_cp_bad[:6])))
    _cp = _cp_ok
    _cp_skip = [os.path.basename(p) for p in _all_cp if p not in _cp]
    if _cp_skip:
        print('   ⚠ 跳过 %d 张**非结算帧命名的杂帧**（历史探针残留，不是正样本）：%s'
              % (len(_cp_skip), ', '.join(_cp_skip[:6])
                 + ('…' if len(_cp_skip) > 6 else '')))
    _names_c = ('close_tpl_0', 'close_tpl_1', 'close_tpl_2')

    def _close_hit(im):
        # ⚠ 样本可能来自不同抓帧路径（<720 宽 / 缩放过的诊断帧 ✗）
        #   ⇒ 先统一到 **720 宽**再匹配，与模板的标定尺度一致 ✓
        if im is None:
            return 0.0
        if im.shape[1] != 720:
            im = cv2.resize(im, (720, int(round(im.shape[0] * 720.0 / im.shape[1]))),
                            interpolation=cv2.INTER_AREA)
        mx = 0.0
        for nm in _names_c:
            v = F.find(im, nm, box=(0, 780, 720, 1080))
            if v:
                mx = max(mx, v[2])
        return mx

    if not _cp:
        print('   （本机没有 runs/cap_close/ 样本 ⇒ 跳过此项 ✓）')
    else:
        # ⚠ 与【1b】同口径：`frames` 里是**彩色**帧，模板也必须是彩色（`fixed.py` 约定 ✓）
        #   （我第一版把模板存成灰度 ⇒ `cv2.matchTemplate` 类型不匹配直接抛 ✗ 已改回彩色 ✓）
        #
        # ⭐⭐ 2026-10-08 **正样本抽样**（治"门禁越跑越慢"）：
        #   用户问「**为什么这么慢？不能多并发快点跑吗**」⇒ 剖析定位到就是这里 ✗
        #   实测：`runs/cap_close/` 累积 **2122 张**真结算帧，单张 `_close_hit`（3 模板）
        #         0.054s ⇒ **本项一项就 114 秒**（整个 `verify_fastpath` 420s 的大头）
        #   ⚠ 这是**语料膨胀**（跑得越多、图存得越多），不是代码退化 ✓
        #   ⇒ 本项要证明的是「**模板没坏**」（能命中真结算帧、不误命中棋盘帧），
        #     不是"2122 张必须逐张过" ⇒ **固定种子等距抽样**（可复现 ✓）取前 N 张
        #     ⚠ 用**固定种子**（不是随机）⇒ 同一仓跑两次结果一致，门禁可复现 ✓
        #     ⚠ 上限可调：`MAPBOT_FASTPATH_MAXPOS`（默认 160；设 0 = 全量，慢但彻底 ✓）
        _lim = int(os.environ.get('MAPBOT_FASTPATH_MAXPOS') or 160)
        if _lim > 0 and len(_cp) > _lim:
            _step = max(1, len(_cp) // _lim)
            _cp_s = _cp[::_step][:_lim]
            print('   ⚡ 正样本 %d 张 ⇒ **等距抽样 %d 张**（固定步长 %d；'
                  '全量见 `MAPBOT_FASTPATH_MAXPOS=0`）'
                  % (len(_cp), len(_cp_s), _step))
        else:
            _cp_s = _cp
        _sp = [_close_hit(cv2.imread(p2)) for p2 in _cp_s]
        _sp = [s for s in _sp if s is not None]
        ck('正样本 %d 张全部命中（阈值 0.80，最低 %.3f）'
           % (len(_sp), min(_sp) if _sp else 0.0),
           bool(_sp) and all(s >= 0.80 for s in _sp))
        _sn = [_close_hit(im) for _p2, im in frames
               if not os.path.basename(_p2).startswith('select_map_')][:10]
        ck('棋盘帧 %d 张都不命中（最高 %.3f）'
           % (len(_sn), max(_sn) if _sn else 0.0),
           all(s < 0.80 for s in _sn))

    # ── 【1d】⭐⭐⭐ 2026-10-04：`battle_started_fast()` 的**标题判据** ──
    #   背景：`start_fight` 原来每轮付一次 ~0.52s 的 OCR 问「开打了没」
    #     （真机耗时分账：`tap` = 276.4s / 530 次）⇒ 改成**图像**先答：
    #     ① 新模板 `battle_win_title`（结算标题「战斗胜利」）← 本项测它
    #     ② 既有 `close_tpl_{0,1,2}`（底部「关闭」）      ← 【1c】已在测 ✓
    #   标定（离线，零体力）：①正样本最低 **1.000** ／ 负样本最高 **0.199** ⇒ 阈值 0.80
    #   ⚠⚠ 本项**存在的唯一理由**：负样本必须是**含地图横幅「首领战斗胜利」的地图帧**。
    #     该横幅实测 bbox **(21,100)-(138,123)**，与结算标题 **(229,91)-(489,157)**
    #     **y 重叠、x 不重叠**（间隔 91px）⇒ 判据正确性**完全依赖 x 带 [200,520]**。
    #     拿普通负样本测（不含该横幅）等于没测 —— 这正是 `battle_started()` 在
    #     docstring 里反复警告的「首领战斗胜利」坑，模板版必须有门禁守住 ✓
    #
    #   ⚠ 判据阈值/搜索框**从 `explore_loop.py` 源码里抠**，不在本门禁里另写一份：
    #     否则有人把热路径的常量改错，门禁会跟着一起绿 ⇒ 等于没测
    #     （同 `verify_finish_exit.py` 的口径 ✓）
    print()
    print('【1d】战斗结算标题模板 battle_win_title（正样本必须命中 / 地图横幅帧必须不命中）')
    import re as _re
    _elsrc = open(os.path.join(HERE, 'explore_loop.py'), encoding='utf-8').read()
    _mb = _re.search(r'^_BATTLE_TITLE_BOX\s*=\s*\(([^)]*)\)', _elsrc, _re.M)
    _mt = _re.search(r'^_BATTLE_TMPL_THR\s*=\s*([\d.]+)', _elsrc, _re.M)
    _has_tpl = os.path.exists(os.path.join(F.TPL_DIR, 'battle_win_title.png'))
    if not _has_tpl:
        print('   （本机没有 templates/fixed/battle_win_title.png ⇒ 跳过；'
              '跑 `python make_battle_tpl.py` 生成）')
    elif not (_mb and _mt):
        ck('热路径里的 _BATTLE_TITLE_BOX / _BATTLE_TMPL_THR 能从源码抠出来', False,
           '抠不到 ⇒ 常量被改名/挪走了，本门禁会失去意义')
    else:
        _box = tuple(int(float(x)) for x in _mb.group(1).split(','))
        _thr = float(_mt.group(1))
        # 抠出来的搜索框必须**装得下模板**（fixed.py 的经典静默失效坑：装不下 ⇒ 永远 None）
        _t = F._load('battle_win_title')
        _fits = bool(_t is not None and _box[1] + _t.shape[0] <= _box[3]
                     and _box[0] + _t.shape[1] <= _box[2])
        ck('搜索框 %s 装得下模板 %s' % (_box, None if _t is None else _t.shape[:2]), _fits,
           '（装不下 ⇒ 模板永远 0 命中，而且是静默的 ✗）')

        def _title_hit(im):
            """在**热路径同款搜索框**里找标题模板，返回最高分（0 = 没命中）"""
            if im is None or im.shape[:2] != (F.PC_H, F.PC_W):
                return 0.0
            x0, y0, x1, y1 = _box
            try:
                r = cv2.matchTemplate(im[y0:y1, x0:x1].astype(np.float32),
                                      _t.astype(np.float32), cv2.TM_CCOEFF_NORMED)
                return float(r.max())
            except Exception:                    # noqa: BLE001
                return 0.0

        # 正样本 = `runs/cap_close/` 的真机结算整帧（与【1c】同一素材源 ✓）
        _sp = [_title_hit(cv2.imread(p2)) for p2 in _cp[:120]]
        _sp = [s for s in _sp if s is not None]
        ck('正样本 %d 张全部命中（阈值 %.2f，最低 %.3f）'
           % (len(_sp), _thr, min(_sp) if _sp else 0.0),
           bool(_sp) and all(s >= _thr for s in _sp))

        # ⚠⚠ 负样本**必须是地图帧**（含「首领战斗胜利」横幅）——
        #   取法：既不是结算帧（close_tpl 未命中）、也不是选图界面帧
        _neg_im = [im for p2, im in frames
                   if not os.path.basename(p2).startswith('select_map_')
                   and _close_hit(im) < 0.80]
        _sn = [_title_hit(im) for im in _neg_im[:40]]
        ck('地图/其它帧 %d 张都不命中（最高 %.3f）'
           % (len(_sn), max(_sn) if _sn else 0.0),
           bool(_sn) and all(s < _thr for s in _sn))

        # ── ② 同款紧框上的 `close_tpl_*`（热路径**也**用它，比【1c】的整条下半屏快 14 倍）──
        #   ⚠ 必须拿**热路径那份 `_SETTLE_BOX`** 测：改成紧框后搜索范围只剩 1/11，
        #     万一"收紧过头"漏掉某个版面变体，只有这一项抓得住 ✗
        #     （2026-10-04 收紧依据：全量 793 张结算帧里模板只落在 (384,960) 与 (379,876)
        #       两个位置 ⇒ 取并集 + 15px；漏掉后者的代价 = 少认一张，门禁当场红 ✓）
        _msb = _re.search(r'^_SETTLE_BOX\s*=\s*\(([^)]*)\)', _elsrc, _re.M)
        if not _msb:
            ck('热路径里的 _SETTLE_BOX 能从源码抠出来', False,
               '抠不到 ⇒ 常量被改名/挪走了')
        else:
            _sbox = tuple(int(float(x)) for x in _msb.group(1).split(','))

            def _settle_hit(im):
                """紧框下 3 个 close_tpl 的最高分（0 = 都没命中）"""
                if im is None or im.shape[:2] != (F.PC_H, F.PC_W):
                    return 0.0
                mx = 0.0
                for nm in _names_c:
                    v = F.find(im, nm, box=_sbox)
                    if v:
                        mx = max(mx, v[2])
                return mx

            _tfit = [F._load(nm) for nm in _names_c]
            ck('紧框 %s 装得下 3 个 close_tpl 模板' % (_sbox,),
               all(t2 is not None and _sbox[1] + t2.shape[0] <= _sbox[3]
                   and _sbox[0] + t2.shape[1] <= _sbox[2] for t2 in _tfit))
            _csp = [_settle_hit(cv2.imread(p2)) for p2 in _cp[:150]]
            _csp = [s for s in _csp if s is not None]
            ck('紧框下正样本 %d 张全部命中（阈值 %.2f，最低 %.3f）'
               % (len(_csp), _thr, min(_csp) if _csp else 0.0),
               bool(_csp) and all(s >= _thr for s in _csp))
            _csn = [_settle_hit(im) for im in _neg_im[:40]]
            ck('紧框下地图帧 %d 张都不命中（最高 %.3f）'
               % (len(_csn), max(_csn) if _csn else 0.0),
               bool(_csn) and all(s < _thr for s in _csn))

    print()
    print('【3】速度：模板匹配 vs OCR（同区域判「导航条在不在」）')
    n = 30
    # ⚠⚠ 2026-10-03 修**计时抖动假红**：模板耗时用"单次 30 连跑取平均"，
    #   而机器上**两个机器人实例正在跑**时会被抢 CPU ⇒ 实测掉到 <100 倍 ⇒ 假红 ✗
    #   （与 `verify_marks_grid` ④ 同类问题）⇒ 改成**取 3 次的中位数**，阈值放宽到 50 倍 ✓
    _runs = []
    for _r in range(3):
        t0 = time.time()
        for _ in range(n):
            F.has(img, 'nav_dex', box=F.BANDS['nav'])
        _runs.append((time.time() - t0) / n)
    _runs.sort()
    t_tpl = _runs[1]
    print('   模板匹配（限定导航条条带）: %7.2f ms/次（3 次中位：%s）'
          % (t_tpl * 1000, ' '.join('%.2f' % (x * 1000) for x in _runs)))

    try:
        import mapbot as MB
        bot = MB.Bot.__new__(MB.Bot)
        bot.runs = HERE
        bot.t = {'ocr': 0.0}
        bot.log = []
        band = (F.BANDS['nav'][1], F.PC_H)
        t0 = time.time()
        for _ in range(3):
            bot._img_arr = img
            bot.ocr(min_conf=0.4, band=band)
        t_ocr = (time.time() - t0) / 3
        print('   OCR（同一条带）          : %7.2f ms/次' % (t_ocr * 1000))
        print('   ⇒ 模板快 %.0f 倍' % (t_ocr / t_tpl if t_tpl else 0))
        ck('模板匹配确实比 OCR 快 50 倍以上',
           t_ocr / t_tpl > 50 if t_tpl else False,
           '%.0f 倍' % (t_ocr / t_tpl if t_tpl else 0))
    except Exception as e:                      # noqa: BLE001
        print('   (OCR 对比跳过: %r)' % (e,))

    print()
    print('=' * 66)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过：模板快查可安全替代 OCR 的存在性判断')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
