# -*- coding: utf-8 -*-
"""spots.py · 地块识别（逐格分类）—— 2026-09-25 重写

原理（已实机标定，见 fit_art.py 与 tools/mapbot/README.md）：
  * 每个地块 = **一整张格子贴图**（地面+物件画在一起），设计尺寸 30x30/格、
    格距 32px；多格地块就是更大一张（94x30 = 3 格，靠 SpotShape 对齐）。
  * `AreaBlock.FreshBlock` → `SetNativeSize()`，屏幕缩放 = **4.5 倍**
    ⇒ 屏幕格距 = 32*4.5 = **144.0 px**，单格贴图 135x135。
  * 于是不需要盲扫模板：**把每格像素切出来，跟该图的候选贴图逐帧比相似度**
    （灰度零均值归一化互相关，对迷雾的灰化/明暗变化不变），取最高分。
  * 结果既能用来找「旅行商人 / 黄金宝库」，也能顺手认出每一格是什么地块。

用法:
    python spots.py board runs/board_clean.png --map 夏日海滩       # 打印整盘分类
    python spots.py target runs/board_clean.png --map 夏日海滩      # 只报商人/宝库格
    python spots.py live --map 夏日海滩                             # 抓当前屏幕再分类
    python spots.py base --map 夏日海滩 --write                     # 重新标定几何
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT = os.path.join(ROOT, 'templates', 'unit')
RUNS = os.path.join(ROOT, 'runs')
import repo_paths as RP                                          # noqa: E402

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DT = RP.require(RP.DATATABLE, '游戏数据表 server_datatable.json')  # 2026-10-10 去仓库耦合

# ⭐⭐ 2026-10-02 换基准：棋盘几何**改为从 layout.REF 取**，不再在这里写死一份。
#   原因：这里原本写死 `x0=36, y0=1002, pitch=144`（1080×1920 系），
#   而 `apply_layout()` 只在**运行时**覆盖它 ⇒ 静态与运行时长期不一致。
#   更要命的是 `Board` 里的阈值 `thr = 0.80 * (px/144.0)` 把 144 当常数，
#   720p 真实格距是 96 ⇒ 公式的分母/基准全错 ⇒ NCC 分数被压到 0.07~0.26
#   ⇒ **每格都在瞎猜**（实测：同一格两轮认成不同地块，全是装饰，0 个战斗格）。
#   ⇒ 现在单一数据源 = `layout.REF`（已随基准换成 720p ⇒ 96），
#      `Board` 里的 px 恒等于实际格距，`thr` 公式自然成立 ✓
try:
    from layout import REF as _REF
    GRID = dict(x0=float(_REF['grid_x0']), y0=float(_REF['grid_y0']),
                pitch=float(_REF['grid_cx']),
                cx=float(_REF['grid_cx']), cy=float(_REF['grid_cy']),
                cols=_REF['grid_cols'], rows=_REF['grid_rows'])
except Exception:       # noqa: BLE001  layout 不可用时退回 720p 标定值（勿改回 1080 系）
    GRID = dict(x0=24.0, y0=668.0, pitch=96.0, cx=96.0, cy=96.0, cols=7, rows=5)

# ⚠ `SCALE` 只是 `Board.__init__` 的**默认参数**和两处日志打印里用到的历史遗留值
#   （= 144/32，来自旧 1080p 标定）。**实际算格距走 `self.px`，而 `self.px` 来自
#   `GRID['cx']`** ⇒ 换基准后 `SCALE` 本身不参与任何计算，不要拿它推算格距。
SCALE = 4.5

# ⭐ 基准格距（**与 `layout.REF_W/REF_H` 同步维护**）：720p 下棋盘格距 96px。
#   `Board.state()` 的 NCC 门槛按 `px / BASE_PX` 自适应 —— 换基准时只改这一处，
#   不要在任何公式里再写死 144（那是 1080p 的值，留着就是定时炸弹 ✗）。
BASE_PX = float(GRID.get('cx') or GRID.get('pitch') or 96.0)
DESIGN_PITCH = 32.0
DESIGN_TILE = 30.0
INNER = 3.0          # 裁掉设计尺寸的外圈像素（透明圆角，避免干扰）

# ⭐⭐ 2026-09-27：多格地块的**真实占格必须由 alpha 推导**（不能按 (dw+2)/32 的矩形外框 ✗）
#   实测 S00003_111：画布 62x62（2×2 外框）但 alpha 只覆盖 **3 格 L 形**（右上整片透明）。
#   旧代码把缺的那格也算进模板 ⇒ 而那格实际住着**邻居**（图1 (2,5) 是 103 游乐设施）
#   ⇒ 模板里混进了别人的美术 ⇒ NCC 被稀释到 0.554，被 0.80 门槛砍掉
#     ⇒ 这就是用户报的「战斗地块没识别出来是哪个」（0.554 → 掩膜后 **0.942** ✓）
#   旁证：真盘 dump 里 S00003_111 的 blockSize = **3**（而 201/202/203 是 4）✓
#   旁证2：图1 (2,4) 的大块 bbox 278x278 却只占 3 格 —— L 形的包围盒本来就是 2×2 ✓
_CELL_COV_MIN = 0.10     # alpha 在某 32px 设计格内覆盖率 > 该值 ⇒ 算它占该格 ✓
_MASK_FILL_MAX = 0.97    # alpha 整幅填充率 < 该值 ⇒ 非矩形覆盖 ⇒ 匹配时走掩膜 ✓
SAT_MAX = 40.0           # ⭐ 区域里「高饱和」像素 = clover/boss/redEquip **图标** ⇒ 匹配前剔除
                         #   （雾是灰的、美术也被灰化；图标是鲜绿/鲜红 ⇒ 饱和度天然可分 ✓
                         #     实测图2 (3,6) 被 clover 压住：0.768 → 剔除后 **0.819** ✓）

# ⭐⭐ 2026-09-28：**模板帧采样**（修「棋盘识别 46~68 秒/帧」，用户报「识别为什么这么慢」）
#   模板库 33 sid × **640 张动画帧**全量入库 ⇒ 每帧识别 = 640 模板 × 全盘所有合法摆放位置 NCC；
#   1 格组走矩阵乘（快），**多格非矩形贴图走掩膜 NCC 纯 python 循环**（423×423 大图、
#   每次 2~5ms、几千次调用）⇒ 46~68s 的大头。
#   动画帧间只有水波/装饰微动 ⇒ **每 sid 取前 3 帧** ⇒ 模板 640→~99（-85%）⇒ 识别 ~8-12s。
#   ⚠ MAPBOT_TPL_FRAMES=0 恢复全量（旧口径，若分类分数异常用它回退排查 ✓）
_TPL_FRAMES = max(0, int(os.environ.get('MAPBOT_TPL_FRAMES', '3') or '0'))


#: 优选帧清单缓存：{code: {sid: [帧文件名, ...]}}
_FRAME_PICKS = {}


def _frame_picks(code, sid):
    """该图块**离线优选**的帧文件名列表；没有清单 ⇒ None（调用方回退到前 N 帧）

    ⚠ `MAPBOT_TPL_PICKS=0` ⇒ 全局关掉（回退排查用，立刻回到旧口径 ✓）
    ⚠ 任何异常都返回 None —— 优选帧是**增益**，**不能**因为清单坏了就起不来 ✗
    """
    if (os.environ.get('MAPBOT_TPL_PICKS') or '').strip() == '0':
        return None
    if code not in _FRAME_PICKS:
        d = {}
        p = os.path.join(UNIT, code, '_frames.json')
        if os.path.isfile(p):
            try:
                import json as _json
                with open(p, encoding='utf-8') as f:
                    raw = _json.load(f)
                if isinstance(raw, dict):
                    d = {str(k): [str(x) for x in (v or [])]
                         for k, v in raw.items()
                         if isinstance(v, (list, tuple))}
            except Exception:               # noqa: BLE001
                d = {}
        _FRAME_PICKS[code] = d
    return _FRAME_PICKS[code].get(sid) or None


def _foot_from_alpha(alpha, dw, dh):
    """贴图 alpha → **真实占格**偏移 [(dr, dc), ...]（按 32px 设计格切）

    画布恒为 `n*32 - 2`（多格贴图外圈各留 1px）⇒ 设计格边界正好在 x=32*j ✓
    """
    ncy = max(1, int(round(dh / DESIGN_PITCH)))
    ncx = max(1, int(round(dw / DESIGN_PITCH)))
    H, W = alpha.shape[:2]
    out = []
    for i in range(ncy):
        for j in range(ncx):
            y0 = int(round(i * DESIGN_PITCH))
            y1 = min(int(round((i + 1) * DESIGN_PITCH)), H)
            x0 = int(round(j * DESIGN_PITCH))
            x1 = min(int(round((j + 1) * DESIGN_PITCH)), W)
            if y1 <= y0 or x1 <= x0:
                continue
            if float((alpha[y0:y1, x0:x1] > 127.5).mean()) > _CELL_COV_MIN:
                out.append((i, j))
    return tuple(out) or ((0, 0),)

# 需要「买完」的特殊地块（用户 2026-09-24 指定；主循环只用前两个）
BUY_OUT_NAMES = ('旅行商人', '黄金宝库')

# ⭐⭐⭐⭐⭐ 2026-10-09 **宝箱怪**（用户口径，原话）：
#   「商人黄金宝库和金属宝箱怪有自动拉黑机制，之前那个低于50w金币和**10幸运草**就是」
#   ⇒ 宝箱怪**花幸运草**买装备 ⇒ 与商人/宝库**同类**（花资源做取舍）
#   ⇒ 幸运草不足时**自动拉黑**（见 `explore_loop.MIMIC_CLOVER_MIN` ✓）
#   ⚠ **不能并进 `BUY_OUT_NAMES`** —— 那个名字的语义是"花**金币**买"，
#     而宝箱怪花的是幸运草 ⇒ 并进去会让**金币闸门**（`GOLD_MIN_BUY`）也管到它 ✗
#     （宝箱怪不该因为金币少而被拉黑 ✓）
MIMIC_NAMES = ('金属宝箱怪', '机巧宝箱怪')


def is_fight_spot(sid):
    """这一格**是不是"要打一场架"的地块**（用户口径 2026-10-03 ✓）

    ⭐⭐⭐ 为什么需要它（真机事故 acc1 `gui_20261003_140308` 第 2 张图）：
      计划 `['2,6','2,5','3,1']` 的第一步 2,6（`S00003_111` 海边杂物，格数 3）**是要打的**，
      但它的 `拦路` 标记是**规划完之后才贴上去的**（循环发现"计划路径穿过非空地"才标 ✗）
      ⇒ 规划那一刻它没有标记 ⇒ 被当"内容格·探索"按 size=3 计价（实际应 6 ✓）
      ⇒ 于是"打这一架(3)"和"绕路揭 4 格(1×4=4)"看起来差不多 ⇒ 平局时选了要打的那条 ✗
      手工对账：A=打 2,6(6)+2,5(1) 到 boss 门口共 **7 体**；B=绕路 1,7→1,6→1,5→2,5 只要 **4 体** ✓
      而求解器仍选 A ✗ ⇒ 必须按**地块类型**定价，而不是看临时标记 ✓

    判据来自数据表 `Area_Spot.EventNum`（本机 482 行实测）：
      · 草地 `1-1`、海螺 `1-1`、宝箱 `1-1`、岩石 `1-1`、勇者之墓 `1-1` ⇒ **不打** ✓
      · 海边杂物 `2-2`/`3-3`、游乐设施 `4-4`/`5-5`、巨大沙堡 `8-8`、海边小屋 `9-9` ⇒ **要打** ✓
      ⇒ 规则：`EventNum` 非空且首段数字 > 1 ⇒ 战斗型 ✓
    """
    try:
        row = (spot_rows() or {}).get(str(sid)) or {}
        ev = str(row.get('EventNum') or '').strip()
        if not ev:
            return False
        a = ev.split('-')[0].strip()
        return bool(a.isdigit() and int(a) > 1)
    except Exception:       # noqa: BLE001
        return False


def imread(path, flags=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)


def map_table():
    """Area_Spot -> {图名: S码}（同一图名的多行取一致前缀）"""
    d = json.load(open(DT, encoding='utf-8'))
    out = {}
    for r in d['Area_Spot'].values():
        ids = r.get('IDs') or ''
        name = (r.get('AreaName') or '').strip()
        if not ids.startswith('S') or not name:
            continue
        out.setdefault(name, ids.split('_')[0])
    return out




# ⭐ 名字覆盖（用户实测指正 ✓ 优先于数据表 ✓）
#   S00003_102：官方表写的是"海边杂物"，但用户屏幕上显示「海边游客」✓ 以用户为准 ✓
#   （只影响显示/日志 ✓ 不影响分类与费用 ✓）
NAME_FIX = {
    'S00003_102': '海边游客',
}


def _cached(fn):
    """⭐ 2026-09-28：数据表缓存 —— spot_rows()/map_table() 每次 json.load 全表
    （3.95MB，实测 0.05 秒/次）；explore_loop 每轮 cells_of/state/eff_order 多处调用
    ⇒ 累计可省。表是静态的 ⇒ 模块级缓存安全 ✓（显式 _cached_clear() 可清）"""
    _box = {}

    def wrapper():
        if 'v' not in _box:
            _box['v'] = fn()
        return _box['v']

    wrapper.clear_cache = _box.clear
    return wrapper


@_cached
def spot_rows():
    """{IDs: Area_Spot 行}"""
    with open(DT, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭
        d = json.load(f)
    out = {r['IDs']: r for r in d['Area_Spot'].values()}
    for _k, _v in NAME_FIX.items():      # 套用名字覆盖 ✓
        if _k in out:
            out[_k] = dict(out[_k], Name=_v)
    return out


@_cached
def map_table():
    """Area_Spot -> {图名: S码}（同一图名的多行取一致前缀）"""
    with open(DT, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭（端上靠 GC 回收会刷 ResourceWarning 噪音）
        d = json.load(f)
    out = {}
    for r in d['Area_Spot'].values():
        ids = r.get('IDs') or ''
        name = (r.get('AreaName') or '').strip()
        if not ids.startswith('S') or not name:
            continue
        out.setdefault(name, ids.split('_')[0])
    return out


FOG_SIL_MIN = 0.04        # 雾下"有东西"的剪影占比阈值（真机实测：有物体 0.064~0.292 / 平坦 0.014~0.016）


def fog_silhouette(img, r, c, board):
    """雾格剪影占比（0~1）—— 「雾底下有没有东西」的**尺度无关**判据

    做法：取该格图像 → 只留中间 80%（躲开外框/圆角）→ 雾底 = 中位亮度 →
    剪影掩码 = 明显暗于雾底（`median − max(12, 2.2·MAD)`，MAD 是稳健方差，抗纹理噪声）→
    开运算去毛刺 → 最大连通块/总面积（占比）。

    实测（1280×2772 真机帧，铁血高地，见 `_tmpman/fog_silhouette.py`）：
      有物体：0.292 岩石图腾 / 0.271 巨大木桩 / 0.169 宝箱(2,2) / 0.064 岩石 …
      平  坦：0.014~0.016（雾格里的空地）
    ⇒ 阈值 0.04：**判"非空地"** ⇒ 连锁到此为止（不再靠"雾格一律挡"的一刀切 ✓）
    """
    import cv2
    import numpy as np
    G = board.grid if board is not None else GRID
    cx = int(G['x0'] + (c - 1) * (G.get('cx') or G.get('pitch') or 144)
             + (G.get('cx') or G.get('pitch') or 144) / 2)
    cy = int(G['y0'] + (r - 1) * (G.get('cy') or G.get('pitch') or 144)
             + (G.get('cy') or G.get('pitch') or 144) / 2)
    half = int((G.get('cx') or 144) / 2)
    sub = img[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    if sub.size == 0:
        return 0.0
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = int(g.shape[0] * 0.10)
    if g.shape[0] > 3 * m and g.shape[1] > 3 * m:
        g = g[m:g.shape[0] - m, m:g.shape[1] - m]
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) or 1.0
    mask = ((med - g) > max(12.0, 2.2 * mad)).astype('uint8')
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    return float(mask.mean())


def code_of(mapname):
    mt = map_table()
    if mapname in mt:
        return mt[mapname]
    for k, v in mt.items():
        if mapname and (mapname in k or k in mapname):
            return v
    return None


class Board:
    """一格分类器：把候选地块贴图预转成矩阵，逐格算 NCC"""

    def __init__(self, code, scale=SCALE, inner=INNER, maxframes=0, grid=None):
        self.code = code
        self.scale = scale
        self.inner = inner
        # ⭐ 分辨率自适应：几何可外部注入（不传则用全局 GRID ⇒ 行为与旧版完全一致 ✓）
        self.grid = dict(GRID)
        if grid:
            self.grid.update({k: v for k, v in grid.items() if v is not None})
        # 残缺几何补齐（缺 rows/cols/pitch 也不会崩 ✓）
        self.grid.setdefault('cols', GRID.get('cols', 7))
        self.grid.setdefault('rows', GRID.get('rows', 5))
        self.grid.setdefault('pitch', self.grid.get('cx') or GRID.get('pitch', 144.0))
        # ⭐ 格距优先取几何里的 cx/pitch（显式传入或全局 GRID 都算 ✓）
        #   参考分辨率下 GRID.cx = 144 = 4.5×32 ⇒ 与旧行为完全一致 ✓（零回归 ✓）
        _cx = self.grid.get('cx') or self.grid.get('pitch')
        if _cx:
            self.px = float(_cx)
        else:
            self.px = scale * DESIGN_PITCH      # 屏幕格距（144.0）
        self.k = int(round(inner / DESIGN_PITCH * self.px))
        self.entries = []                       # (sid, dw, dh, frame_idx, cw, ch)
        self.groups = {}                        # (dw,dh) -> {'idx','mat','plain_idx','mask_idx'}
        self.foot = {}                          # sid -> ((dr,dc),...) 真实占格（由 alpha 推 ✓）
        self.midx = {}                          # entry 下标 -> (pos, gt) 掩膜 NCC 用
        tmp = {}
        for d in sorted(glob.glob(os.path.join(UNIT, code, '*'))):
            sid = os.path.basename(d)
            files = sorted(glob.glob(os.path.join(d, '*.png')))
            # ⭐ 2026-09-28 帧采样（_TPL_FRAMES，默认每 sid 前 3 帧 ✓ 显式 maxframes 优先 ✓）
            # ⭐⭐⭐⭐ 2026-10-18 **优选帧**（治"特殊地块分数不够被漏"）
            #   ---- 病（真机实测）----
            #     原来只是 `files[:_mf]` —— **按文件名取前 3 帧**，完全不看内容 ✗
            #     而真机显示的是动画的某一帧（可能是第 5/27 帧）：
            #       S10002_014 限时礼包：前3帧 0.75~0.79，**f05 = 0.974**
            #       S10002_016 黄金宝库：前3帧最高 0.574，**f18 = 0.869**
            #       S10002_008 旅行商人：前3帧 0.714，**f24 = 0.908**
            #     ⇒ 分数被"采样不全"拖低 ⇒ `< 0.85` 被当不可信 ⇒ 漏点 ✗✗
            #   ---- 修法 ----
            #     `templates/unit/<code>/_frames.json` 里存**离线选好的 3 帧**
            #     （判据：对"top3 出现过的格"覆盖均分最高 ⇒ 分离度最大）
            #     实测提升：宝库 +0.296 / 礼包 +0.188 / 商人 +0.194 ✓
            #   ---- 三条回退口（都不改就得旧行为）----
            #     ① `_frames.json` 不存在 ⇒ 返回 None ⇒ 走下面原来的 `files[:_mf]`
            #     ② `maxframes` 显式传入 ⇒ 尊重调用方（旧接口语义不变）
            #     ③ `MAPBOT_TPL_PICKS=0` ⇒ 全局关掉优选帧 ✓
            _pick = None
            if not maxframes:
                try:
                    _pick = _frame_picks(self.code, os.path.basename(d))
                except Exception:           # noqa: BLE001
                    _pick = None
            if _pick:
                _by_name = {os.path.basename(p): p for p in files}
                _sel = [_by_name[n] for n in _pick if n in _by_name]
                if _sel:
                    files = _sel
                else:
                    _mf = maxframes or _TPL_FRAMES
                    if _mf:
                        files = files[:_mf]
            else:
                _mf = maxframes or _TPL_FRAMES
                if _mf:
                    files = files[:_mf]
            for fi, f in enumerate(files):
                im = imread(f)
                if im is None or im.ndim < 3 or im.shape[2] < 4:
                    continue
                dh, dw = im.shape[:2]
                # 模板美术尺寸 × (px/DESIGN_PITCH) ✓ 与 _region 同一公式 ✓
                #   （屏幕美术 135px 居中在 144 格距里 ⇒ 设计 30px × 4.5 = 135 ✓）
                w = int(round(dw / DESIGN_PITCH * self.px))
                h = int(round(dh / DESIGN_PITCH * self.px))
                if w < 8 or h < 8:
                    continue
                # ⭐ 真实占格（同 sid 的多帧取并集，防动画帧 alpha 有缺 ✓）
                if sid in self.foot:
                    _f = _foot_from_alpha(im[:, :, 3], dw, dh)
                    if len(_f) > len(self.foot[sid]):
                        self.foot[sid] = _f
                else:
                    self.foot[sid] = _foot_from_alpha(im[:, :, 3], dw, dh)
                # 2026-09-27：彩色方案实测代价过高（7.4s/次 + 540MB ✗）⇒ 已取消 ✓ 恢复灰度 ✓
                g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
                g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
                # ⭐ 非矩形覆盖的多格贴图 ⇒ 记掩膜（只取 alpha 真正覆盖的像素做 NCC ✓）
                #   否则缺的那格会把邻居的美术算进来 ⇒ 分数被稀释（0.554 vs 0.942）
                sel = gt = None
                full = cv2.resize(im[:, :, 3], (w, h), interpolation=cv2.INTER_AREA) > 127.5
                if ((dw > DESIGN_PITCH * 1.5 or dh > DESIGN_PITCH * 1.5)
                        and float(full.mean()) < _MASK_FILL_MAX):
                    m = full.copy()
                    gc = g
                    if self.k:
                        m = m[self.k:-self.k, self.k:-self.k]
                        gc = g[self.k:-self.k, self.k:-self.k]
                    pos = np.flatnonzero(m.reshape(-1))
                    if pos.size > 200:
                        sel = pos.astype(np.int32)
                        # ⚠ 必须用**同样内缩过**的灰度取值（pos 是内缩坐标系 ✓）
                        gt = gc.reshape(-1)[pos].copy()
                if self.k:
                    g = g[self.k:-self.k, self.k:-self.k]
                v = g.reshape(-1)
                v = v - v.mean()
                sd = v.std()
                if sd < 1e-6:
                    continue
                key = (dw, dh)
                tmp.setdefault(key, []).append(((v / sd).astype(np.float32), sid, fi, sel, gt))
        for (dw, dh), lst in sorted(tmp.items()):
            idx = []
            mats = []
            for v, sid, fi, sel, gt in lst:
                idx.append(len(self.entries))
                self.entries.append((sid, dw, dh, fi,
                                     int(round((dw + 2) / DESIGN_PITCH)),
                                     int(round((dh + 2) / DESIGN_PITCH))))
                mats.append(v)
                if sel is not None and gt is not None:
                    self.midx[idx[-1]] = (sel, gt)
            ix = np.array(idx)
            ismask = np.array([int(i) in self.midx for i in ix], dtype=bool)
            self.groups[(dw, dh)] = {
                'idx': ix, 'mat': np.stack(mats),
                'plain_idx': ix[~ismask],                      # 矩形覆盖 ⇒ 走矩阵乘 ✓
                'mask_idx': [int(i) for i in ix[ismask]],      # 非矩形 ⇒ 走掩膜 NCC ✓
            }
        self.sids = [e[0] for e in self.entries]

    def footprint(self, sid):
        """该地块的**真实占格**偏移 [(dr,dc)...]（alpha 推导；无则退回矩形占位 ✓）"""
        fp = self.foot.get(sid)
        if fp:
            return fp
        cw, ch = self._tpl_size(sid)
        return tuple((i, j) for i in range(ch) for j in range(cw))

    def cells_of(self, sid, anchor):
        """锚点 + 真实占格 ⇒ 该块实际覆盖的格子列表 ✓（成员格不再按矩形外框算 ✗）"""
        ar, ac = int(anchor[0]), int(anchor[1])
        return [(ar + dr, ac + dc) for dr, dc in self.footprint(sid)]

    def _mscore(self, ent, g, sat):
        """**掩膜 NCC**：只比贴图 alpha 真正覆盖到的像素，并剔除高饱和的图标像素 ✓

        ⭐ 2026-09-28：灰度/饱和度由 scores() 位置层算一次共享传入（同位置多个掩膜
        模板不再各 cvtColor 一遍 ✓ 数学完全等价 ✓）"""
        sel, gt = self.midx[ent]
        if self.k:
            g = g[self.k:-self.k, self.k:-self.k]
            sat = sat[self.k:-self.k, self.k:-self.k]
        gf = g.reshape(-1)
        if gf.size <= int(sel.max()):
            return 0.0
        ok = sat.reshape(-1)[sel] < SAT_MAX
        if int(ok.sum()) < 200:
            ok = np.ones_like(ok)               # 全被图标盖住 ⇒ 没法剔，退回不剔 ✓
        a = gt[ok]
        b = gf[sel][ok]
        a = a - a.mean()
        b = b - b.mean()
        d = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(a @ b / d) if d > 1e-9 else 0.0

    def _region(self, img, r, c, dw, dh):
        """贴图左上角落在第 (r,c) 格的左上角 + 内缩（贴图居中在格子里）

        ⛔⛔ 2026-10-02 修真 bug：**内缩量算成了负数**，每格取图起点整体偏移
           ⇒ 模板与画面错位 ⇒ NCC 分数全线偏低（实测 0.10~0.30，门槛 0.80）
           ⇒ 认不出任何地块 ⇒ objects()/explore_blocks() 聚不出物件
           ⇒ `anchor` 全为 None ⇒ `explore_loop` 记的 `board` 恒空
           ⇒ solver 无输入 → `no_plan / exhausted` → **没有规划**（用户原话）
           ⇒ 再往上表现为「开局就退 / 棋盘被挡 / 目标全丢」，全是它的下游症状 ✗✗

           根因：模板尺寸用 `dw / DESIGN_PITCH * px`（**已跟着分辨率走** ✓），
           但内缩量却用**固定的 `self.scale`**（`SCALE=4.5` 是 1080p 系的旧值）：
               pad = (px − 30×4.5) / 2 = (96 − 135) / 2 = **−19.5**  ✗
           720p 下贴图只有 90px（=30/32×96），正确内缩是：
               pad = (px − dw/DESIGN_PITCH*px) / 2 = (96 − 90) / 2 = **+3.0**  ✓
           ⇒ 同一个公式、同一个 px，**不再引用 self.scale**（它已不参与几何计算）。

        ⛔⛔⛔ 2026-10-02 二次修正：上面那个 `pad=(px−w)/2` **只对单格模板成立**。
           多格模板 `w > px` ⇒ `pad` **变负数** ⇒ 取图起点向左反向偏移：

               dw= 30(单格) w= 90 pad=  +3   ✅
               dw= 62(2格)  w=186 pad= −45  ✗ 起点左偏 45px
               dw= 94(2×3)  w=282 pad= −93  ✗ 左偏 93px
               dw=126(3格)  w=378 pad=−141  ✗

           实测后果（真机帧 `runs/r_122222_0.png`，夏日海滩）：
             · `5,4`/`5,1` 的 x0 算成 **−21 / −69** ⇒ **越界 ⇒ `_region` 返回 None**
               ⇒ 正确的 2 格模板（103 游乐设施 / 111 海边杂物）**根本没进候选**；
             · 能取到图的也整块错位 ⇒ NCC 0.09~0.40
               ⇒ **所有多格地块（战斗格/大建筑）识别全线失效**，单格（草地 0.99）正常。
             ⇒ 这正是用户报「**战斗格子几乎全都识别错了**」的根因。

           正确口径：**多格贴图的左上角对齐 anchor 格的左上角**（不做居中）——
           因为多格贴图是「本体美术 + 透明边距」，它**本来就该以 anchor 为原点**铺开；
           只有**单格**贴图需要在自己的格子里居中（那才是 pad 的本意）。
           ⇒ 故：`pad = (px - w) / 2` 仅当 `w <= px`，否则 **pad = 0**。
        """
        px = self.px
        w = int(round(dw / DESIGN_PITCH * px))
        h = int(round(dh / DESIGN_PITCH * px))
        # ⭐ 单格才居中；多格贴图以 anchor 为原点铺开（pad 归零，见上方长注释）
        pad = ((px - w) / 2.0) if w <= px else 0.0
        x0 = self.grid['x0'] + (c - 1) * px + pad
        y0 = self.grid['y0'] + (r - 1) * px + pad
        xi, yi = int(round(x0)), int(round(y0))
        if xi < 0 or yi < 0 or xi + w > img.shape[1] or yi + h > img.shape[0]:
            return None
        return img[yi:yi + h, xi:xi + w]

    def _floor_luma(self, img, r, c):
        """该格**四角**区域亮度的**中位数** = "地板"亮度（图标/物件无关）

        ⭐⭐⭐⭐ 2026-10-05 新增。用途见 `cells()` 里 `floor` 那段长注释：
          `ratio` 的分子是**中心均值** ⇒ 雾格上叠的标记图标会把它抬起来（真机 (2,1) 冲到
          1.019、被判"已揭示"、真机点不动 ✗）；分母是**地块模板亮度** ⇒ 判据不可跨图。
          ⇒ 用**四角**（图标/美术最多压住一角，总有一角是纯地板）取中位数 ⇒ 雾格恒贴基准 ✓

        ⚠⚠ 2026-10-05 二次修正：**取中位数，不取最小值**
          （用户报「**夏日沙滩这把出问题了**」）
          最小值的毛病：**大件美术会盖住一两格的角** ⇒ "最暗角"量到的是美术本身，不是地板。
          真机铁证（`runs/acc1/r_155257_0.png`，`(1,1)` = `椰树` label，ratio **0.678 = 雾**）：
            四角 = [147, 153, 153, 153]（本帧雾簇 = 153、真已揭示 = **234**）
            ⇒ `min` = 147 落进雾簇 ⇒ p25 基准被拉低到 ≈147 ⇒ 阈值 154
            ⇒ **椰树雾格 `(1,1)` 被判"已揭示"** ✗✗ ⇒ 计划第一步就点它
            ⇒ 真机 `[r1] 标记格 1（含点不动的 1）` ⇒ 计划清空 ⇒ **stuck（19 秒白跑）**
          ⇒ 取**中位数**：椰树 [147,153,153,153] ⇒ **153**（贴雾簇 ✓）；
            真已揭示 234（明显高 ✓）⇒ 两类干净分开 ✓
          ⚠ 矿洞那张 `(2,1)`（boss 图标压在雾格上）四角 [176,65,65,65] ⇒ 中位数仍是 **65** ✓
            （一格被图标污染不影响中位数 ✓）

        ⚠ 尺寸全部按 `self.px`（本帧格距）算，不写死像素 ⇒ 换分辨率/缩放都成立 ✓
        ⚠ 取不到（越界）就返回 None ⇒ 调用方按"没有这个信息"处理（不猜 ✓）
        """
        try:
            px = int(self.px)
            inset = max(3, px // 12)          # 离格边内缩（避开格线与贴图边缘）
            w = max(6, px // 6)               # 角块边长
            x0 = int(self.grid['x0'] + (c - 1) * px)
            y0 = int(self.grid['y0'] + (r - 1) * px)
            if (x0 < 0 or y0 < 0 or x0 + px > img.shape[1] or y0 + px > img.shape[0]):
                return None
            sub = img[y0:y0 + px, x0:x0 + px]
            g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
            vals = []
            for (yy, xx) in ((inset, inset), (inset, px - inset - w),
                             (px - inset - w, inset), (px - inset - w, px - inset - w)):
                blk = g[yy:yy + w, xx:xx + w]
                if blk.size:
                    vals.append(float(np.median(blk)))
            return float(np.median(vals)) if vals else None
        except Exception:               # noqa: BLE001
            return None

    def _vec(self, sub):
        # 与模板一致：灰度 ✓（彩色方案实测代价过高已取消 ✓）
        g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if g.ndim == 3:
            for _ch in range(g.shape[2]):
                _c = g[:, :, _ch]
                g[:, :, _ch] = (_c - _c.mean()) / (_c.std() + 1e-6)
        if self.k:
            g = g[self.k:-self.k, self.k:-self.k]
        v = g.reshape(-1)
        v = v - v.mean()
        sd = v.std()
        if sd < 1e-6:
            return None, 0.0
        return v / sd, float(sd)

    def scores(self, img, topn=3):
        """逐格分类（含多格贴图的所有摆放位置）-> {(r,c): [(score, sid, frame, off) ...]}

        ⭐ 2026-09-27 重写：候选**只投给该贴图真正覆盖的格**（`cells_of`）✗ 不再按矩形外框投。
           理由：111 的 L 形缺右上格，旧代码会把候选投到那格（实际住着邻居 103）。
           同时：非矩形覆盖的多格贴图改走**掩膜 NCC**（`_mscore`）✓
        """
        best = {}
        rows, cols = self.grid['rows'], self.grid['cols']
        for (dw, dh), grp in self.groups.items():
            cw = int(round((dw + 2) / DESIGN_PITCH))
            ch = int(round((dh + 2) / DESIGN_PITCH))
            plain, masks = grp.get('plain_idx'), grp.get('mask_idx') or []
            for rr in range(1, rows - ch + 2):
                for cc in range(1, cols - cw + 2):
                    sub = self._region(img, rr, cc, dw, dh)
                    if sub is None:
                        continue
                    got = []
                    if plain is not None and plain.size:
                        v, _sd = self._vec(sub)
                        if v is not None and v.size == grp['mat'].shape[1]:
                            sc = grp['mat'] @ v / v.size
                            for oi in np.argsort(-sc)[:topn]:
                                e = self.entries[grp['idx'][oi]]
                                got.append((float(sc[oi]), e[0], e[3]))
                    if masks:
                        # ⭐ 2026-09-28：灰度/饱和度**位置层算一次共享** —— 同一位置的
                        #   多个掩膜模板不再各 cvtColor 一遍（数值完全等价 ✓ 纯提速 ✓）
                        gsub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                        satf = (sub.max(axis=2).astype(np.float32)
                                - sub.min(axis=2).astype(np.float32))
                        for ent in masks:
                            e = self.entries[ent]
                            got.append((self._mscore(ent, gsub, satf), e[0], e[3]))
                    if not got:
                        continue
                    got.sort(reverse=True)
                    for s, sid, fi in got[:topn]:
                        for (r, c) in self.cells_of(sid, (rr, cc)):
                            if 1 <= r <= rows and 1 <= c <= cols:
                                best.setdefault((r, c), []).append((s, sid, fi, (rr, cc)))
        for k in best:
            best[k] = sorted(best[k], reverse=True)[:topn]
        return best

    def objects(self, sc, thr=0.75, img=None):
        """把逐格分类整合成「物件」：同 ID + 摆放一致的多格贴图合并成一个物件

        -> {(r,c): {'sid':.., 'score':.., 'cells':[(r,c)...], 'anchor':(r,c)}}
        """
        out = {}
        seen = set()
        # ⭐⭐ 2026-09-27 修（用户报「识别错格子」的核心 ✓）：
        #   原来只做"逐格最高分优先"的贪心 ✗ ⇒ 1 格模板会抢走多格地块的上半格
        #   （实测 m1_r007 格(2,4)：海螺 0.956 抢走 ⇒ 1×2 的椰树整块消失 ✗
        #     ⇒ 费用模型把 4 点的战斗格当成 2 点的海螺 ⇒ 求解器"走它不亏"✗）
        #   ⇒ 先算出**多格模板**的最佳摆放 ✓，若其"覆盖各格平均分"够高 ⇒ 让它们**优先占位** ✓
        _multi = []
        for (dw, dh), grp in (getattr(self, 'groups', {}) if img is not None else {}).items():
            cw = int(round((dw + 2) / DESIGN_PITCH))
            ch = int(round((dh + 2) / DESIGN_PITCH))
            if cw * ch <= 1:
                continue                       # 只关心多格模板 ✓
            plain, masks = grp.get('plain_idx'), grp.get('mask_idx') or []
            rows_, cols_ = self.grid['rows'], self.grid['cols']
            for r in range(1, rows_ + 1):
                for c in range(1, cols_ + 1):
                    rr, cc = r - ch + 1, c - cw + 1
                    if not (1 <= rr <= rows_ - ch + 1 and 1 <= cc <= cols_ - cw + 1):
                        continue
                    sub = self._region(img, rr, cc, dw, dh)
                    if sub is None:
                        continue
                    _bs, _bsid = -9.0, None
                    # ① 矩形覆盖的模板：一次矩阵乘 ✓
                    if plain is not None and plain.size:
                        v, _sd = self._vec(sub)
                        if v is not None and v.size == grp['mat'].shape[1]:
                            sc2 = grp['mat'] @ v / v.size
                            oi = int(np.argmax(sc2))
                            _bs, _bsid = float(sc2[oi]), self.entries[grp['idx'][oi]][0]
                    # ② 非矩形覆盖（alpha 有空洞）⇒ 掩膜 NCC，逐个比 ✓
                    if masks:
                        # ⭐ 2026-09-28 修（真机 [warn] 地块分类失败: _mscore() missing
                        #   'sat'）：§30 共享灰度改造漏了这处调用 ⇒ objects() 每摆位抛
                        #   TypeError ⇒ cells_of 整体失败 ⇒ 全盘 26 格全 gray（识别崩 ✗，
                        #   21:22 重启首轮暴露）。同 scores() 的位置层共享算法补上。
                        gsub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                        satf = (sub.max(axis=2).astype(np.float32)
                                - sub.min(axis=2).astype(np.float32))
                        for ent in masks:
                            sm = self._mscore(ent, gsub, satf)
                            if sm > _bs:
                                _bs, _bsid = sm, self.entries[ent][0]
                    if _bsid is None:
                        continue
                    _multi.append((_bs, _bsid, (rr, cc), (cw, ch)))
        _multi.sort(reverse=True)
        # ⚠⚠⚠ 2026-10-02 修「PC 端进去啥都认不出就退图」（真机帧 runs/r_015542_0.png 逐格实测）：
        #   症状：35 格只分了 18 格，`plain`(可开路空地) **=0** ⇒ 规划器一步都展不开
        #     ⇒ 「没有目标了」⇒ 秒退图。
        #   根因：**多格合并没有绝对分数下限** —— 下面那句老判据只比「相对」：
        #       `if _sc2 + 0.25 < _best_single: continue`
        #   也就是「不比单格最高分差太多就认作本体」。而**认单格的门槛是 thr=0.80**，
        #   实测这盘空地各格最高分只有 **0.21~0.38**（认单格早就被否了），
        #   但因为 0.218 离别家的 0.218 差不到 0.25 ⇒ **强行被认成一个 3×2 的
        #   「巨大沙堡」大块**（用户核实：那几格本来就是空地 ✗）
        #   ⇒ 空地被当障碍 ⇒ 没有 plain 可开路 ⇒ 直接退图 ✗✗
        #   修法：多格模板**自己也必须过单格那道门槛**（`_MIN_MULTI`），
        #   相对判据保留作第二道（防「真多格但分略低」）——
        #   两者都过才合并，否则这格退回单格处理（该是空地就是空地 ✓）
        _thr_single = thr if thr is not None else (
            max(0.12, min(0.80, 0.80 * (float(self.px) / BASE_PX))))
        _MIN_MULTI = max(_thr_single, 0.45)
        for _sc2, _sid2, (_rr, _cc), (_cw, _ch) in _multi:
            # ⚠️ 绝对下限：认不准就不许硬凑成多格物件（2026-10-02 新增，见上方说明）
            if _sc2 < _MIN_MULTI:
                continue
            _cells2 = self.cells_of(_sid2, (_rr, _cc))   # ⭐ 真实占格（L 形只 3 格 ✓）
            if any(x in seen for x in _cells2):
                continue
            # 该处单格最高分（用于比较 ✓）
            _best_single = 0.0
            for x in _cells2:
                _l = sc.get(x)
                if _l:
                    _best_single = max(_best_single, _l[0][0])
            # 多格模板若比"单格最高分"差不太多 ⇒ 认定它是本体 ✓（阈值 0.25 实测可分出 ✓）
            if _sc2 + 0.25 < _best_single:
                continue
            for x in _cells2:
                seen.add(x)
                out[x] = {'sid': _sid2, 'score': round(_sc2, 3),
                          'anchor': (_rr, _cc), 'cells': _cells2,
                          'size': (_cw, _ch)}
        for (r, c), lst in sorted(sc.items(), key=lambda kv: -kv[1][0][0]):
            if (r, c) in seen:
                continue
            v, sid, _fi, (ar, ac) = lst[0]
            if v < thr:
                continue
            cw, ch = self._tpl_size(sid)
            cells = self.cells_of(sid, (ar, ac))         # ⭐ 真实占格 ✓
            for cc in cells:
                seen.add(cc)
                out[cc] = {'sid': sid, 'score': round(v, 3), 'anchor': (ar, ac),
                           'cells': cells, 'size': (cw, ch)}
        return out

    def patch(self, img, r, c, dw=30, dh=30):
        return self._region(img, r, c, dw, dh)

    # ---------- 综合状态（分类 + 已揭示判定） ----------
    def state(self, img, thr=None, attr=True):
        # ⭐ 2026-09-27 门槛随分辨率自适应。
        #   ⚠⚠ 2026-10-02 换基准 1080×1920 → 720×1280：这里的**分母不能写死 144**。
        #   旧写法 `0.80 * (px/144.0)` 在 px=96（720p）时算出 0.53，
        #   而 720p 下 NCC 正常值本身就低（模板与实拍同样被缩小）⇒ 0.53 仍偏高
        #   ⇒ 实测每格分数只有 0.07~0.26、全部认不出（同一格两轮认成不同地块）。
        #   现在以 `BASE_PX`（= 本仓基准 720p 的格距 96）为参照，与基准同步维护 ✓
        if thr is None:
            thr = 0.80 * (float(self.px) / BASE_PX)
            thr = max(0.12, min(0.80, thr))
        """逐格状态：分类 + 亮度比值（判断是否已揭示）

        实测（2026-09-25，find_buy.png）：
          * **整盘美术一开始就画出来了**，未揭示的格被 `AreaBlock.SetEnable(false)` 的
            `disableColor=(170,170,170)` 乘暗 ⇒ 亮度比 ≈ 0.65；已揭示 ≈ 1.00。
            （NCC 对亮度/对比度不变，所以**暗格也能认出是什么地块**）
          * 暗格点不动（`Button.enabled=false`），只有亮格能点。

        ⭐ 2026-09-26 修正：多格地块的**成员格归属**（`attr=True` 自动做）
        旧逻辑只看每格自己的 top1 ⇒ 一个 2×3 的紫/橙大块会出两个错：
          ① 分成 5~6 个独立目标（点哪一格弹的都是同一块的面板 ⇒ 重复弹面板/白点）
          ② 成员格里"裁剪里没有本体美术"的那格（实测 findA3 的 (1,7) 只有石板底纹）
             自己 top1 会变成空地 001（0.910 压过大块的 0.794）⇒ 整块丢一格，
             且被当 1 点体力的空地拿去开路（实际点它同样弹面板）
        ⇒ 先 `explore_blocks()` 从**任意成员格**的候选里还原大块的摆放位置，
          再把这个 footprint 里所有格的 sid/anchor/cells 改成同一个大块 ✓
          （`attr=False` 可退回旧行为，调试对拍时用 ✓）

        -> {(r,c): {'sid','name','score','ratio','revealed','anchor','cells','size',
                    'block_score','top':[...]}}
        """
        sc = self.scores(img, topn=STATE_TOPN)
        blocks = self.explore_blocks(sc) if attr else []
        objs = self.objects(sc, thr=thr, img=img)
        rows = spot_rows()
        owner = {}                      # 成员格 -> 所属大块（用于归属修正 ✓）
        for b in blocks:
            # ⚠ 绝不覆盖强匹配的商人/宝库（2026-09-25 卡死事故的教训 ✓）
            if any(_is_strong_buy(objs.get(k), rows) for k in b['cells']):
                continue
            # ⛔ 2026-10-12 那版判据**已撤换**（下面 2026-10-14 是现行的 ✓）
            #   旧版：`top1 >= 0.85` **且** `top1 - 块分 > 0.20` ⇒ 弃块
            #   ⛔ 撤换原因：它是**相对量**（含块分）⇒ **分不开**这两帧 ✗
            #     `runs/r_194934_0.png`（真没沙堡）与 `runs/acc1/r_143410_0.png`
            #     （`2,1` 真有沙堡）的那个 `211` 块**逐项相同**（块分都 0.361）
            #     ⇒ 相对量必然同判 ⇒ 要么修过头、要么漏修 ✗
            # ⭐⭐⭐⭐⭐ 2026-10-14 **按"空出来的形状"判块真假**（用户口径，原话）：
            #   「**为什么这么低？能不能按空出来的方块形状猜测空出来的这是什么？**」
            #   ---- 为什么换掉我 10-12 那版（gap 判据）----
            #     我那版用 **相对量** `top1 - 块分 > 0.20` ⇒ **分不开这两帧** ✗：
            #       · 10-12 `r_194934_0.png`（**真没沙堡**，人眼核对过）
            #       · 10-14 `r_143410_0.png`（**`2,1` 真有沙堡**，人眼核对过）
            #     两帧那个 `211` 块**逐项相同**（块分都 0.361、cells 都
            #     `(1,2)(2,2)(2,3)(2,4)`）⇒ 相对量判据必然同判 ✗
            #   ---- 用户的判据（**绝对量**，实测完美区分 ✓）----
            #     看块覆盖的每一格**自己的 top1 分**：
            #       · **全部偏低**（都被切碎）⇒ 它们是**同一块大美术**的碎片 ⇒ **采纳** ✓
            #       · **有任一格很高**（自成一体，如营地/草地/宝箱）⇒ 块**吞了独立物件** ⇒ **弃块** ✗
            #     实测（`runs/acc1/r_143410_0.png`）：
            #       摆 `2,1`（**真沙堡**）：0.308/0.416/0.441/0.327 ⇒ **全低** ⇒ 采纳 ✓✓
            #       摆 `1,2`（含水洼+营地）：0.996/0.998/0.998/0.994 ⇒ **全高** ⇒ 弃 ✗
            #     实测（`runs/r_194934_0.png`，真没沙堡）：
            #       摆 `2,1`：**海螺 1.000**/草地 0.994/… ⇒ **有高分** ⇒ 弃 ✓（正确拒绝）
            #   ⚠ 阈值 `0.85` 与 `BUY_SCORE_MIN` / `targets_cfg.NAME_SCORE_MIN`
            #     **同源**（"这个分数以上，该格的名字算数" ✓）
            #   ⚠ 逐格打分**天生偏低**是正常的：模板是**整块 L 形大图**（94×62），
            #     而逐格只截到它的**局部** ⇒ 单格分自然上不去（真沙堡 0.29~0.44）
            #     ⇒ 所以**不能用"块分低"判假**，只能看"格分是不是自成一体" ✓
            _blk_ok = True
            for _k in b['cells']:
                _l0 = sc.get(_k) or []
                if not _l0:
                    continue
                if float(_l0[0][0]) >= 0.85:      # ⭐ 该格**自成一体** ⇒ 块吞了它 ✗
                    _blk_ok = False
                    break
            if _blk_ok:
                for k in b['cells']:
                    owner[k] = b
        out = {}
        for (r, c), lst in sc.items():
            k = (r, c)
            v, sid, _fi, _off = lst[0]
            blk = owner.get(k)
            o = objs.get(k)
            # ⭐ 2026-09-27 修 bug：`o` 这条分支原先只改了 anc/cells/size，**漏改 eff**
            #   ⇒ 物件 footprint 的成员格会带着"该格自己的 raw top1"的 sid 返回，
            #     与同一块内其它格自相矛盾。实测 夏季海滩 巨大沙堡(211) 的成员格：
            #       (3,5) sid=211 ✓  (4,5) sid=003 宝箱 ✗  (4,6) sid=014 限时礼包 ✗  (4,7) sid=211 ✓
            #     ⇒ 下游把 cells 摊平时凭空多出 宝箱/限时礼包 各一个（2/84 张图受影响）。
            #   与上方 owner 那条守卫保持一致：**绝不覆盖强匹配的商人/宝库** ✓
            if blk:
                anc, cells, size = blk['anchor'], blk['cells'], blk['size']
                eff = blk['sid']                  # 归属修正后的地块 ID
            elif o:
                anc, cells, size = o['anchor'], o['cells'], o['size']
                eff = sid if _is_strong_buy(o, rows) else o['sid']
            else:
                anc, cells, size = None, [k], (1, 1)
                eff = sid
            sub = self._region(img, r, c, 30, 30)
            ratio = 0.0
            if sub is not None:
                g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                if self.k:
                    g = g[self.k:-self.k, self.k:-self.k]
                ratio = float(g.mean()) / max(1e-6, self._tpl_luma(eff))
            # ⭐⭐⭐⭐ 2026-10-05 **"地板"亮度**（图标无关）—— 治「雾格被判已揭示」的真根因
            #   用户原话：「**为什么在废弃矿洞的规划错得离谱，在夏日海滩的就是对的**」
            #            「**可能不是求解器的问题？是识别的问题？**」⇒ **就是识别** ✓
            #   真机铁证（`runs/acc2/r_145056_0.png`，废弃矿洞 14:50）：
            #     格子 `(2,1)` 上画着 **boss 标记图标**，`ratio = **1.019**` ⇒ 被判「已揭示」
            #     ⇒ 求解器拿它当第一步去点 ⇒ 真机 `give_up_step`（点不动）✗✗
            #     而按边/角实测它**明明是雾**：上65 下104 左117 右65 / 四角 [176,65,65,65]
            #     —— 只有**图标压着的那半边**亮，格子本身是 **65 = 本帧纯雾基准** ✓
            #   为什么 `ratio` 判不了（两项都不可靠）：
            #     · 分子 = **中心 60×60 平均亮度** ⇒ 游戏**会在雾格上叠标记图标**
            #       （boss/幸运草/大拇指…本文件 737 行那段教训已经写明）⇒ 中心被抬起 ✗
            #     · 分母 = **该格被判成的地块模板亮度** ⇒ 同一个亮度在不同地图/地块上
            #       算出不同 ratio ⇒ **判据不可跨图**：
            #         夏日海滩 草地模板亮 ⇒ 雾 0.65 / 已揭示 1.0~1.3，间隔干净 ✓
            #         废弃矿洞 岩石模板暗 + 图标亮 ⇒ 雾格冲到 0.85~1.02 ⇒ 一片误判 ✗✗
            #   ⇒ 取**四角中位数里最小的那个** = "地板"亮度：图标最多压住一角/一边，
            #     总有一个角是纯地板 ⇒ 雾格恒贴近本帧雾基准、已揭示格明显更高 ✓
            #   ⚠ 只**记录**，判定留给下面的两趟法（`floor_lit`）＋ explore_loop 的
            #     "带标记的格子由地板说了算"（那里才拿得到 marks ✓）
            floor = None
            try:
                floor = self._floor_luma(img, r, c)
            except Exception:           # noqa: BLE001
                floor = None
            # ⭐⭐⭐⭐⭐ 2026-10-26 **多格块不许在「单格通道」显示名字**
            #   （治「很多空地看成巨大沙堡」—— 判据与理由见 `MULTI_BLOCK_MIN` 下面那段）
            #   ⚠⚠⚠ **只置空 `name`**：`sid`/`eff`/`ratio`/`revealed`/`anchor`/`cells`
            #     **一个都不动** ⇒ 下游技术判断**完全不变** ✓
            #     （我第一版改的是「重新挑 top1」⇒ `eff` 变 ⇒ `ratio` 的分母变
            #      ⇒ 1095 帧实测 ratio 变 2817 格 / revealed 变 620 格 ✗✗ 已撤回）
            _nm = (rows.get(eff) or {}).get('Name') or ''
            # ⚠⚠ **还要「分数低于块门槛」这个条件**（1095 帧实测抓到的漏点）：
            #   真机帧 `r_221451_0.png` 的 `5,7`/`4,7` 是**椰树 1.000**（满分！真识别）
            #   ⇒ 只按「多格块」一刀切 ⇒ **把满分真地块也清空了** ✗✗
            #   ⇒ 完整判据 = 「没被块采纳」+「是多格块」+「分数 < 块门槛(0.28)」
            #     ⇒ 低分（< 0.28）= 噪声 ⇒ 清空 ✓
            #     ⇒ 高分（≥ 0.28）= 真识别 ⇒ **保留** ✓
            #     （阈值与 `MULTI_BLOCK_MIN` 同源 ⇒ 语义自洽：
            #       「连块门槛都够不到的分数，不足以证明这是个多格块」）✓
            if (blk is None and isinstance(eff, str)
                    and float(v) < MULTI_BLOCK_MIN):
                try:
                    if eff.split('_')[-1] in self._multi_sids():
                        _nm = ''              # ⛔ 单格通道 + 低分的多格块 ⇒「认不出」
                except Exception:           # noqa: BLE001
                    pass
            out[k] = {'sid': eff, 'name': _nm,
                      'score': round(float(v), 3), 'ratio': round(ratio, 3),
                      'floor': (round(float(floor), 1) if floor is not None else None),
                      'revealed': False,      # ⭐ 下面统一判定（见两趟法）
                      'anchor': anc, 'cells': cells, 'size': size,
                      'block_score': (round(blk['score'], 3) if blk else None),
                      'top': [(round(float(s), 3), s2, anch)
                              for s, s2, _f, anch in lst]}
            # ⭐⭐⭐ 2026-10-01 v1.03【雾格剪影识别】——用户口径「优化识别模型，认出雾格里那块不能穿过」：
            #   雾格（ratio≈0.65）**底下的真身只能靠剪影认**：分类器隔着雾猜名字，真机实测会把
            #   挡连锁的物体猜成「草地」（score 还 0.95 ✗）⇒ 规划以为连锁能穿过它 ✗✗
            #   而"雾底 + 暗剪影"是**看得见**的：真机同帧实测（1280×2772 设备帧，铁血高地）
            #     · 有物体的雾格 剪影占比 **0.064 ~ 0.292**（(2,2) 宝箱=0.169、(3,1) 石碑=0.292…）
            #     · 平坦雾格   剪影占比 **0.014 ~ 0.016**
            #   ⇒ 中间有 4 倍空档，阈值 0.04 判「雾下有没有东西」稳 ✓（判**非空地** ⇒ 连锁到此为止）
            if ratio and ratio < 0.78:
                try:
                    sil = fog_silhouette(img, r, c, self)
                    out[k]['fog_sil'] = sil
                    out[k]['fog_object'] = bool(sil >= FOG_SIL_MIN)
                    # ⭐ v1.05：**平坦**（剪影很小）= 雾下是空地 ⇒ 交给模型当 plain 用
                    #   （雾格上的模板名字很不可信：真机这盘中位分只有 0.276，平坦格还被
                    #    猜成「岩石/巨大木桩」✗ ⇒ 雾格的"是不是空地"以**剪影实测**为准 ✓）
                    out[k]['fog_flat'] = bool(sil < FOG_SIL_MIN)
                except Exception:       # noqa: BLE001
                    pass
        # ── ⭐⭐⭐ 2026-10-02「已揭示」改**相对本帧基准**判定（两趟法）──────────
        #   症状（用户）：「明明打开标记格子了」却报「标记格打不开（可能被挡路）」，
        #   打完大拇指格子**没摇色子就关了**。真机帧 runs/r_155829_0.png 实测：
        #       4,6 裁出来**明明是亮的**、上面还有 boss + 大拇指两个图标，
        #       但 `ratio = 0.708 < 0.75` ⇒ 被判「雾格/未揭示」⇒
        #       规划把它当第一步去点 ⇒ **点不动** ⇒ 战斗面板开不起来 ⇒
        #       于是「标记格打不开」⇒ 摇色子分支（要 recommend）也就没走到 ✗✗
        #   根因：`ratio >= 0.75` 是**绝对阈值**，而那一帧的 ratio 分布是
        #       0.70 0.72 0.70 0.71 0.65 0.71 0.65   ← 第4行整排已揭示都只有 0.70~0.72
        #   雾格基准恒 ≈0.65（项目 §5/§7 的实测），但**部分揭开的盘**里
        #   已揭示格可能只有 0.68~0.74 ⇒ 0.75 把它们**全判成雾格**。
        #   离线对拍 8 帧（绝对 0.75 vs 相对法）：
        #       r_152446_0  3 格 → 9 格    r_155757_0  4 格 → 8 格
        #       r_155829_0  4 格 → 11 格   r_150238_0 28 格 → 29 格（几乎一致，不倒退）
        #   ⇒ 改用**本帧自身的雾格基准**（10 分位）×1.06，并保底 0.66：
        #       雾格恒在基准附近 ⇒ 判为未揭示；明显高于基准 ⇒ 已揭示 ✓
        #   ⚠ **必须两趟**（先收齐全盘 ratio 再判定）—— 逐格算时拿不到分布。
        try:
            _rs = sorted(float(v.get('ratio') or 0.0) for k, v in out.items()
                         if isinstance(k, tuple))
            # ⭐⭐⭐⭐ 2026-10-05 **地板法的本帧基准**（与 ratio 两趟法并存，各管一段）
            #   已揭示 ⟺ 地板亮度明显高于**本帧雾基准**；本帧雾基准 = 全盘地板的 25 分位
            #   实测（4 张真机帧，人工核对过）：
            #     废弃矿洞 14:50  基准 65 ⇒ 判亮 5 格 = {(1,7),(2,6),(2,7),(3,6),(3,7)} ← 与肉眼一致 ✓
            #        （同帧 ratio 法判出 **11** 格，其中 (2,1)/(3,1)/(3,2)/(3,4)/(3,5)/(1,5) 全是雾 ✗✗）
            #     废弃矿洞 13:53  基准 65 ⇒ 判亮 4 格 = {(1,5),(1,6),(1,7),(2,6)} ✓
            #     废弃矿洞 13:36  基准 63 ⇒ 判亮 4 格（(1,6)(1,7)(2,7)＋营地）✓
            #     夏日海滩 13:36  基准 147 ⇒ 判亮 5 格 = {(1,5),(2,4),(2,5),(2,6),(3,5)} ✓
            _fl2 = sorted(float(v.get('floor') or 0.0) for k, v in out.items()
                          if isinstance(k, tuple) and v.get('floor') is not None)
            if _fl2:
                # ⭐⭐⭐ 2026-10-05 二次修正：基准取**众数**，不是 25 分位
                #   （用户报「**夏日沙滩这把出问题了**」）
                #   25 分位的毛病：**大件美术会盖住一格或两格的角** ⇒ 那些格的地板被量低
                #   （真机 `runs/acc1/r_155257_0.png`：椰树雾格四角 [196,153,147,153] ⇒
                #     `min`=147）⇒ 它们把 p25 拉到 **136** ⇒ 阈值 143
                #   ⇒ 连**纯雾草地(153)** 和椰树(147) 都被判"已揭示" ✗✗
                #     ⇒ 计划第一步点 `(1,1)` ⇒ 真机 `标记格 1（含点不动的 1）` ⇒
                #       计划清空 ⇒ **stuck 19 秒白跑** ✗
                #   ⇒ 取**众数**（雾盘上"最常见的那个地板值" = 本图**纯雾**亮度）：
                #       沙滩：众数 153 ⇒ 阈值 206 ⇒ 真已揭示 225/234 ✓、雾 147~153 ✗ ✓
                #       矿洞：众数 65  ⇒ 阈值 88  ⇒ 真已揭示 94~98 ✓、雾 65~83 ✗ ✓
                #   ⚠ 倍数 1.35 的依据：雾是**乘性压暗**（`ratio` 口径雾 ≈0.65 ⇒
                #     已揭示 ≈ 雾 ÷ 0.65 = 雾 × **1.54**）⇒ 取 1.35 给两边都留余量 ✓
                _hist = {}
                for _s in _fl2:
                    _hist[round(_s)] = _hist.get(round(_s), 0) + 1
                _fmode = max(sorted(_hist), key=lambda x: (_hist[x], -x))
                _fbase = max(float(_fmode) * 1.35, float(_fmode) + 12.0)
                for _k, _v in out.items():
                    if isinstance(_k, tuple) and _v.get('floor') is not None:
                        _v['floor_lit'] = bool(float(_v['floor']) > _fbase)
                out['_floor_thr'] = round(_fbase, 1)
            # ⭐⭐⭐⭐ 2026-10-05 **雾下"有没有东西"也要按本帧基准判**（用户报「不是最优步数」）
            #   原来 `fog_object = fog_sil >= FOG_SIL_MIN(0.04)` 是**绝对阈值**，
            #   标定在铁血高地的 **草地** 上（平坦 0.014~0.016 / 有物体 0.064~0.292）✓
            #   而**废弃矿洞的地面是「岩地」，它自带的雾底岩石纹理就占 0.126**：
            #   逐格实测 (1,1)(1,2)(1,3)(1,4)(1,6)(2,4)(2,5)(3,3)(4,1)(4,2)(4,3)(4,6)(5,7)
            #   的 `fog_sil` **完全相同 = 0.1257396449704142**（= 岩地贴图自带的剪影 ✓）
            #   ⇒ 旧阈值把**每一格岩地**都判成"雾下有东西" ⇒ `plain=False` ⇒ **连锁全断** ✗✗
            #   真机后果（`runs/acc2/r_150954_0.png`，用户原话「**不是最优步数**」／
            #   「**有两下无意义点击**」）：计划被迫**一格一格点** ——
            #     9 步 / 28 体力 `['1,7','1,6','1,5','1,4','2,4','3,4','5,1','3,3','2,1']`
            #     （真机日志：round0 连点 4 格、round1 点 (2,4) 再点 (3,4)…）
            #   修：**按本帧的众数取基准**（雾盘上"最常见的那个剪影值" = 本图空地的底纹）
            #       ⇒ 阈值 = `max(FOG_SIL_MIN, 众数 × 1.6)`：
            #         矿洞：众数 0.1257 ⇒ 阈值 **0.20** ⇒ 岩地(0.126) 判"平坦=空地" ✓
            #         铁血高地 / 海滩：众数 0.014~0.016 ⇒ 阈值仍 **0.04**（老行为，一字不变 ✓）
            #   同一帧实测：**9 步 / 28 体力 → 4 步 / 23 体力**
            #       `[(1,7),(2,1),(3,4),(5,1)]` ✓（先点真亮的 (1,7)，靠连锁开图 ✓）
            _sils = {_k: float(_v['fog_sil']) for _k, _v in out.items()
                     if isinstance(_k, tuple) and _v.get('fog_sil') is not None}
            if _sils:
                _hist = {}
                for _s in _sils.values():
                    _hist[round(_s, 3)] = _hist.get(round(_s, 3), 0) + 1
                _mode = max(sorted(_hist), key=lambda x: (_hist[x], -x))
                _sthr = max(float(FOG_SIL_MIN), float(_mode) * 1.6)
                for _k, _v in out.items():
                    if isinstance(_k, tuple) and _v.get('fog_sil') is not None:
                        _v['fog_object'] = bool(float(_v['fog_sil']) >= _sthr)
                        _v['fog_flat'] = not _v['fog_object']
                out['_fog_sil_thr'] = round(_sthr, 4)
            if _rs:
                _base = _rs[max(0, int(len(_rs) * 0.10) - 1)]
                _rev = max(0.66, _base * 1.06)
                for _k, _v in out.items():
                    if isinstance(_k, tuple):
                        _v['revealed'] = float(_v.get('ratio') or 0) >= _rev
                for _k in [k for k in out if not isinstance(k, tuple)]:
                    out.pop(_k, None)
        except Exception:                                   # noqa: BLE001
            for _k, _v in out.items():
                if isinstance(_k, tuple):
                    _v['revealed'] = float(_v.get('ratio') or 0) >= 0.75
        # ── ⭐⭐ 2026-10-02「有标记 ⇒ 一定已揭示」这条规则**已废除** ──────────
        #   起因：我以为「标记是硬证据」，用它推翻亮度判据。
        #   ⛔ 真机打脸（17:03 那把，用户原话「进图等好久才继续点」）：
        #       #24 marks={"5,4":["boss"], "1,3":["recommend"]}  order={"none":0,"gray":0}
        #            —— **已揭示 0 格**，1,3 ratio=0.648 明明是**刚进图的雾格**
        #            却被硬判成已揭示 ⇒ 排进点序 ⇒
        #       #31 {"tap":"fogged_noop","cell":"1,3","ratio":0.648}  ← 点不动
        #       #32~#34 连点三轮同样点不动 ⇒ 白等 30+ 秒 ✗✗
        #   ⭐ 用户澄清（关键）：**「那都是刚进去的，刚进去只有出生地附近四格是已揭示」**
        #     ⇒ 游戏**会在雾格上也叠标记图标**（提示「这里有大拇指/首领」），
        #       所以「有标记」**根本不能**当「已揭示」的证据 ✗
        #   ⇒ 现在：**标记完全不参与揭示判定**。
        #     揭示判定只用亮度（相对本帧雾格基准），这条已经过两帧真机验证：
        #       r_170325_0 已揭示 8 格、r_161050_0 已揭示 11 格
        #       两帧**已揭示格的 ratio 最低值都精确是 0.691** ⇒ 阈值稳 ✓
        #
        # ⛔⛔ 这里**不再调 `marks.scan_board()`**（2026-10-02 性能实测）：
        #   cProfile 实测它 **2.90 秒/次**，占 `state()` 总耗时 3.42s 的 **81%**
        #   （`cv2.matchTemplate` 调 210 次），而它当时只为填 `mark_but_fog`
        #   —— 那个字段**全仓没有任何读取方**（只写不读）⇒ 纯白花 ✗✗
        #   ⇒ 标记扫描由 `explore_loop` 在**自己需要时**单独调（那边本来就要用），
        #     不在这里重复一遍 ⇒ `state()` 3.42s → **约 0.5s**（快约 7 倍）✓
        return out

    # ---------- 紫/橙探索大块（2026-09-26 新） ----------
    def _tpl_size(self, sid):
        """该地块贴图占几格 -> (cols, rows)（缓存 ✓）"""
        sz = getattr(self, '_szmap', None)
        if sz is None:
            sz = self._szmap = {}
        if sid not in sz:
            cw = ch = 1
            for e in self.entries:
                if e[0] == sid:
                    cw, ch = e[4], e[5]
                    break
            sz[sid] = (cw, ch)
        return sz[sid]

    def _multi_sids(self):
        """本图里**算多格块**的 sid 末段集合（数据驱动，不硬编码）✓

        判据 = 地块表 `SpotSize > 1` **或** 该 sid 的真实占格数 > 1
        —— 两者取并集：前者来自数据表（权威），后者兜住「表里写 1 但贴图占多格」的。

        ⭐ 为什么要它（2026-10-02）：`explore_blocks` 原先只认 `EXPLORE_SUFFIX`
           （221/321/331 紫橙）⇒ **战斗格全漏网** ⇒ 成员格被单格模板抢走
           （实测 4,3 被 014 限时礼包以 0.435 压过 211 巨大沙堡 0.425）。
           ⇒ 改成「所有多格块都参与归属修正」，紫橙只是其中一类 ✓
        """
        if getattr(self, '_multi_cache', None) is None:
            out = set(EXPLORE_SUFFIX)
            for sid, row in spot_rows().items():
                try:
                    if int(row.get('SpotSize') or 1) > 1:
                        out.add(str(sid).split('_')[-1])
                except (TypeError, ValueError):
                    continue
            for sid in self.sids:              # 兜底：贴图真实占格 > 1 的
                try:
                    if len(self.footprint(sid)) > 1:
                        out.add(str(sid).split('_')[-1])
                except Exception:              # noqa: BLE001
                    continue
            self._multi_cache = out
        return self._multi_cache

    def explore_blocks(self, sc, min_score=None, suffix=None, all_multi=True):
        """从逐格候选里还原「多格大块」⇒ **一个大块只出一条记录** ✓

        为什么要这一层（见 `state()` 的 ① ② 两条）：
          一个大块的美术只覆盖部分成员格，逐格看永远不可能一致；只有回到
          **贴图的摆放位置（anchor + size）** 才能把整块一次性捞出来。

        算法：
          ① 扫所有格的所有候选，取 sid **是多格块**（`SpotSize>1` 或占格>1）
             且 score ≥ min_score 的
          ② 用 (sid, anchor) 聚合成"摆放位置"，分数取成员里的最大值，
             并记 votes = 有多少个不同的格投了它（票数越多越可信 ✓）
          ③ 按分数降序贪心：**与已占用格重叠的摆放丢弃** ⇒ 天然去重 ✓

        -> [{'sid','anchor','cells','size','score','votes'}]（分数降序）

        ⭐⭐⭐ 2026-10-02（用户手工核对后改）：**从「只认紫橙 221/321/331」
           扩到「所有多格块」**。
           原口径只处理紫橙 ⇒ **战斗格全是漏网的**：
             · 103 游乐设施（2格）、104 海边杂物（3格）、111（3格）、
               211 巨大沙堡（4格）… 都不做归属修正
             ⇒ 成员格各用各的 top1 ⇒ 只差 0.01 就被**单格模板**抢走
               （实测 4,3：014 限时礼包 0.435 压过 211 巨大沙堡 0.425）✗
           ⇒ 现在用 `self._multi_sids()`（**数据驱动**：地块表 `SpotSize>1`）
             ∪ `EXPLORE_SUFFIX`，把战斗格一并纳入 ✓
        """
        if min_score is None:                 # 常量在类之后定义 ⇒ 不能写在默认参数里 ✗
            min_score = EXPLORE_BLOCK_MIN if not all_multi else MULTI_BLOCK_MIN
        rows_n, cols_n = int(self.grid['rows']), int(self.grid['cols'])
        want = self._multi_sids() if all_multi else set(EXPLORE_SUFFIX)
        if suffix is not None:                 # 显式指定后缀（调试/离线对拍）⇒ 照旧
            want = set(suffix)
        place = {}
        for k, lst in sc.items():
            for s, sid, _fi, anch in lst:
                if not isinstance(sid, str) or sid.split('_')[-1] not in want:
                    continue
                if s < min_score:
                    continue
                try:
                    ar, ac = int(anch[0]), int(anch[1])
                except (TypeError, ValueError, IndexError):
                    continue
                cw, ch = self._tpl_size(sid)
                if ar < 1 or ac < 1 or ar + ch - 1 > rows_n or ac + cw - 1 > cols_n:
                    continue                      # 摆放超出棋盘 ⇒ 不合法 ✗
                rec = place.get((sid, (ar, ac)))
                if rec is None:
                    place[(sid, (ar, ac))] = {'score': float(s), 'votes': {k}}
                else:
                    rec['score'] = max(rec['score'], float(s))
                    rec['votes'].add(k)
        out = []
        used = set()
        for (sid, anc), rec in sorted(place.items(),
                                      key=lambda kv: (-kv[1]['score'], kv[0])):
            cw, ch = self._tpl_size(sid)
            cells = self.cells_of(sid, anc)      # ⭐ 真实占格（非矩形外框 ✓）
            if any(cc in used for cc in cells):
                continue                          # 被更高分的大块占了 ⇒ 丢弃 ✓
            used.update(cells)
            out.append({'sid': sid, 'anchor': anc, 'cells': cells,
                        'size': (cw, ch), 'score': round(rec['score'], 3),
                        'votes': len(rec['votes'])})
        # ⭐⭐⭐⭐⭐ 2026-10-08 **E7：同名「掩膜虚高」纠正**（真机 + 离线双重验证）
        #   ── 病（用户报「综合连派 3 支探索队」）──────────────────────
        #     `S00003_103 游乐设施`（2 格、非紫金）被认成 `S00003_221 游乐设施`
        #     （5 格、**紫金探索格**）⇒ 走「探索+派遣」⇒ 派了一支探索队去打本该打的格 ✗
        #   ── 根因（实测，不是猜）────────────────────────────────
        #     `221` 的 alpha 不满（2×3 里一格空）⇒ 走 **掩膜 NCC**（`_mscore`）
        #     ⇒ 只比 **70.1%** 的像素、且集中在美术上 ⇒ 分数**虚高**
        #     而 `103` 走 **矩形通道** ⇒ 整片 186×90 都要像 ⇒ 苛刻
        #     ⇒ `221`=0.747 压过 `103`=0.606（**两者不是一个量纲** ✗）
        #     ⚠ 而 `111`/`211` **也是掩膜块**（cov 0.60/0.54）⇒ **不能一概惩罚掩膜** ✗
        #       （实测：`pen=cov` 会把 `111→011` 误伤 23 格、`201→003` 34 格 ✗）
        #   ── 修法（外科式，**零连带**）──────────────────────────
        #     在上面贪心结果上，只做**不引起连锁**的局部替换：
        #       若某个**掩膜块** P 的格，同时被一个**同名 + 矩形**的块 Q 覆盖，
        #       且 ① 分差 `P.score - Q.score < GAP`（默认 0.20）
        #          ② **Q 的每一格都没被别的块占用**（除了 P）
        #       ⇒ 就地换成 Q ✓
        #     ⭐ 条件 ② 是"零连带"的关键：替换不会挤掉任何别的块 ✓
        #   ── 实测（`mapbot_pc/_ref_game_src/README_离线验证_掩膜惩罚.md`）──
        #     181 条真机现场：**只替换 2 处**，全部是 `221→103`（同名）✓
        #     用户人眼确认的 3 个真值格全对；`221` 多占的 3 格**正确退回** 空地/营地/空地 ✓
        #     其他 179 帧**一格未动** ✓
        if _E7_ON and out:
            out = self._e7_fix_same_name(out, place, sc)
        return out

    def _e7_fix_same_name(self, sel, place, sc=None):
        """⭐ E7：把「同名且矩形」的块换掉「掩膜虚高」的块（**只在不会连锁时**）

        见 `explore_blocks` 末尾的长注释（病 / 根因 / 修法 / 实测全在那边 ✓）

        ⭐ 两段式（**先算完所有替换、再一次性应用**）：
          · 中途抛异常 ⇒ `set` 不动 ⇒ 返回**原结果**（绝不留下"半替换"状态 ✓）
          · 出错**不静默** ⇒ 累加到 `_E7_ERR`（诊断用；门禁/日志能看见 ✓）
            ⚠ 本项目反复栽在"`except: pass` 吞掉异常、照跑"上（README §6.63/§6.72）
              ⇒ 这里**至少留一个计数器**，别做完全无声的兜底 ✗
        """
        swaps = []
        try:
            rows_ = spot_rows()
            used_by = {}
            for p in sel:
                for c in p['cells']:
                    used_by[c] = p
            # 候选池：同名 + 矩形 + 覆盖 P 的格
            pool = []
            for (sid, anc), rec in place.items():
                if self._is_mask_sid(sid):
                    continue                       # 只要矩形块 ✓
                pool.append({'sid': sid, 'anchor': anc,
                             'cells': self.cells_of(sid, anc),
                             'size': self._tpl_size(sid),      # ⚠ 必须有（下游要用 ✓）
                             'score': round(rec['score'], 3),
                             'votes': len(rec['votes']),
                             'name': (rows_.get(sid) or {}).get('Name') or sid})
            for i, p in enumerate(sel):
                nm_p = (rows_.get(p['sid']) or {}).get('Name') or p['sid']
                if not self._is_mask_sid(p['sid']):
                    continue                       # 只治掩膜块 ✓
                for q in pool:
                    if q['cells'] == p['cells'] or q['name'] != nm_p:
                        continue
                    if not (set(q['cells']) & set(p['cells'])):
                        continue
                    if (p['score'] - q['score']) >= _E7_GAP:
                        continue                   # 分差太大 ⇒ 不动 ✓
                    # ⭐⭐⭐⭐⭐ 2026-10-14 **保护：P 独有格里没有"高分格"时不许换** ✓
                    #   ---- 病（本轮降门槛后暴露，`4,5` 真值被弄坏 ✗）----
                    #     `runs/acc3/r_151634_0.png` 格 `4,5`（**用户人眼确认的真值**）：
                    #       P = `S20003_202`（4 格掩膜，覆盖 `4,5/5,5/5,6/5,7`）分 **0.425**
                    #       Q = `S20003_101`（2 格矩形，覆盖 `4,5/5,5`）       分 **0.327**
                    #     上面 ④（分差 0.098 < GAP）**放行** ⇒ 被换成 `101` ✗
                    #     可**人眼并排对比证明 `202` 才对**（`runs/_e7_cmp.png`）：
                    #       `5,6`/`5,7` 与 `5,5` **连成一片**的枯木林+蘑菇丛，
                    #       `101` 把右边两格**切掉了** ✗
                    #   ---- 两案例的**客观分界**（实测 `_tmpman/cmp_e7_cases.py`）----
                    #     看 `P 独有`（Q 没票）的那些格**自己的 top1 分**：
                    #       · 案例 X（`221→103`，**该换**）：独有 3 格 =
                    #           草地 **0.998** / 营地 **1.0** / 草地 **0.998**
                    #         ⇒ **有高分格** ⇒ P **吞了独立物件** ⇒ 换 ✓
                    #       · 案例 Y（`202→101`，**不该换**）：独有 2 格 =
                    #           限时礼包 **0.525** / None **0.471**
                    #         ⇒ **没有高分格** ⇒ 那些格**本来就认不准**、
                    #           本来就是 P 的一部分 ⇒ **不换** ✓
                    #   ⚠ 阈值 `0.85` 与 `BUY_SCORE_MIN` / `NAME_SCORE_MIN` /
                    #     上面"形状判据"**同源**（"这个分数以上，该格的名字算数" ✓）
                    #   ⚠ 为什么**不能**用"P 分更高就不换"（我第一版这么写，**错** ✗）：
                    #     案例 X 的 `P(0.747) > Q(0.606)` **也成立** ⇒ 会把
                    #     E7 该治的那 2 处一起挡掉 ✗（E7 的**全部价值**就没了）
                    _p_only = [c for c in p['cells'] if c not in q['cells']]
                    _hi_only = False
                    for _c in _p_only:
                        _l0 = (sc or {}).get(_c) or []
                        if _l0 and float(_l0[0][0]) >= 0.85:
                            _hi_only = True
                            break
                    if not _hi_only:
                        continue                   # ⭐ P 独有格都不"自成一体" ⇒ P 是对的 ✓
                    # ⭐ 零连带闸门：Q 的每一格要么属于 P、要么空着
                    if not all(used_by.get(c) in (None, p) for c in q['cells']):
                        continue
                    swaps.append((i, p, q))
                    for c in p['cells']:
                        if used_by.get(c) is p:
                            used_by.pop(c, None)
                    for c in q['cells']:
                        used_by[c] = q
                    break
        except Exception as _e:       # noqa: BLE001
            # ⚠ **不静默**：计数 + 留最后一条原因（`verify_e7.py` / 日志可查 ✓）
            global _E7_ERR, _E7_ERR_LAST
            _E7_ERR += 1
            _E7_ERR_LAST = repr(_e)[:120]
            return sel                 # ⇒ 原结果（绝不半替换 ✓）
        for i, _p, q in swaps:         # ⭐ 一次性应用（异常不会留半状态 ✓）
            sel[i] = q
        return sel

    def _is_mask_sid(self, sid):
        """该 sid 是否走**掩膜通道**（alpha 不满 ⇒ `_mscore`）—— 只读，带缓存 ✓"""
        c = getattr(self, '_maskmap', None)
        if c is None:
            c = self._maskmap = {}
        if sid in c:
            return c[sid]
        v = False
        try:
            for i, e in enumerate(self.entries):
                if e[0] != sid:
                    continue
                dw, dh = e[1], e[2]
                grp = self.groups.get((dw, dh)) or {}
                v = i in [int(x) for x in (grp.get('mask_idx') or [])]
                break
        except Exception:       # noqa: BLE001
            v = False
        c[sid] = v
        return v


    def _tpl_luma(self, sid):
        """该地块首帧贴图的平均亮度（用来算亮度比；缓存）"""
        if not hasattr(self, '_luma'):
            self._luma = {}
        if sid not in self._luma:
            files = sorted(glob.glob(os.path.join(UNIT, self.code, sid, '*.png')))
            v = 1.0
            if files:
                im = imread(files[0], cv2.IMREAD_UNCHANGED)
                if im is not None and im.ndim == 3:
                    g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
                    w = int(round(im.shape[1] / DESIGN_PITCH * self.px))
                    h = int(round(im.shape[0] / DESIGN_PITCH * self.px))
                    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
                    if self.k:
                        g = g[self.k:-self.k, self.k:-self.k]
                    v = float(g.mean())
            self._luma[sid] = v
        return self._luma[sid]


def ascii_board(img, cell=30):
    """把棋盘画成文字图（我看不了图片，用这个"看"）。每格取中心 60x60 的均色。"""
    pal = [((255, 236, 179), 'a'),   # 沙地浅黄
           ((220, 200, 150), 'b'),
           ((150, 150, 150), '.'),
           ((110, 110, 110), ','),
           ((80, 80, 80), ':'),
           ((255, 255, 255), 'W'),
           ((230, 200, 60), 'Y'),
           ((200, 80, 60), 'R'),
           ((80, 140, 220), 'B'),
           ((90, 180, 90), 'G'),
           ((150, 90, 200), 'P')]

    def ch(bgr):
        b, g, r = [float(v) for v in bgr]
        best, bd = '?', 1e18
        for (pr, pg, pb), cc in pal:
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < bd:
                bd, best = d, cc
        return best

    # ⚠ 2026-10-01 修 NameError：本函数是**模块级**的（不是 Board 的方法），
    #   原来写 `self.grid[...]` ⇒ 一调用就 NameError（state_cmd 走这里 ⇒ 诊断命令必崩）
    # ⇒ 改用模块级 GRID（Board 构造时也是从它拷的同一份几何 ✓）。
    px = GRID['pitch']
    lines = []
    for r in range(1, GRID['rows'] + 1):
        rowtxt = []
        for c in range(1, GRID['cols'] + 1):
            x = int(GRID['x0'] + (c - 1) * px + px / 2)
            y = int(GRID['y0'] + (r - 1) * px + px / 2)
            patch = img[max(0, y - 30):y + 30, max(0, x - 30):x + 30]
            if patch.size == 0:
                rowtxt.append('   ?    ')
                continue
            h, w = patch.shape[:2]
            sub = []
            for yy in range(3):
                s = ''
                for xx in range(3):
                    p = patch[yy * h // 3:(yy + 1) * h // 3, xx * w // 3:(xx + 1) * w // 3]
                    s += ch([int(v.mean()) for v in cv2.split(p)])
                sub.append(s)
            rowtxt.append('/'.join(sub))
        lines.append(' '.join(rowtxt))
    return lines


def names_of(sids):
    rows = spot_rows()
    return {s: ((rows.get(s) or {}).get('Name') or '?') for s in sids}


_PLAIN_CACHE = {}


def is_plain_spot(sid):
    """该地块是不是「空地」（Area_Spot: SpecialSpot==0 且 SpotSize==1）——点它才能揭一片"""
    if sid not in _PLAIN_CACHE:
        row = spot_rows().get(sid) or {}
        try:
            _PLAIN_CACHE[sid] = (int(row.get('SpecialSpot') or 0) == 0 and
                                 int(row.get('SpotSize') or 1) == 1)
        except Exception:           # noqa: BLE001
            _PLAIN_CACHE[sid] = False
    return _PLAIN_CACHE[sid]


def board_cmd(a):
    code = a.code or code_of(a.mapname)
    if not code:
        print('FAIL: 需要 --map 或 --code')
        return 1
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    b = Board(code)
    sc = b.scores(img)
    objs = b.objects(sc, thr=a.thr)
    nm = names_of(set(b.sids))
    print('=== 棋盘文字图（每格 3x3 主色，行1在第一条） ===')
    for i, ln in enumerate(ascii_board(img), 1):
        print('  r%d  %s' % (i, ln))
    print('=== 逐格分类（图 %s：%d 个地块 / %d 帧 / %d 种尺寸） ==='
          % (code, len(set(b.sids)), len(b.entries), len(b.groups)))
    for r in range(1, 6):
        for c in range(1, 8):
            lst = sc.get((r, c))
            if not lst:
                print('  (%d,%d)  --' % (r, c))
                continue
            top = lst[0]
            rest = ' '.join('%s:%.2f' % (s, v) for v, s, _f, _o in lst[1:])
            own = objs.get((r, c))
            tag = ''
            if own and own['anchor'] == (r, c):
                tag = '  ★物件%s %s' % (own['size'], own['cells'])
            elif own:
                tag = '  (属物件锚点%s)' % (own['anchor'],)
            print('  (%d,%d)  %-12s %-8s %.3f  摆放=%s  |%s%s'
                  % (r, c, top[1], nm.get(top[1], '?'), top[0], top[3], rest, tag))
    return 0


def target_cmd(a):
    code = a.code or code_of(a.mapname)
    if not code:
        print('FAIL: 需要 --map 或 --code')
        return 1
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    rows = spot_rows()
    want = {sid for sid, r in rows.items()
            if sid.startswith(code) and (r.get('Name') in BUY_OUT_NAMES)}
    b = Board(code)
    sc = b.scores(img)
    print('目标地块（%s）：%s  阈值 %.2f'
          % (code, {rows[s]['Name']: s for s in sorted(want)}, a.thr))
    hits = 0
    for (r, c), lst in sorted(sc.items(), key=lambda kv: -kv[1][0][0]):
        v, sid, _f, _off = lst[0]
        if sid in want and v >= a.thr:
            hits += 1
            print('  命中 格(%d,%d)  %s %s  score=%.3f' % (r, c, sid, rows[sid]['Name'], v))
    if not hits:
        print('  0 命中')
    return 0


def verify_cmd(a):
    """用 probe_spots.py 采到的「面板真值」回归分类器 -> 命中率 + 明细"""
    with open(a.probe, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭
        d = json.load(f)
    code = a.code or d.get('code') or code_of(d.get('map'))
    rows = spot_rows()
    allnames = {r.get('Name') for r in rows.values()}
    b = Board(code)
    cache = {}
    ok = bad = skip = 0
    for rec in d['records']:
        if rec.get('kind') != 'content':
            continue
        truth = [t for t in (rec.get('truth') or []) if t in allnames]
        if not truth:
            skip += 1
            continue
        png = os.path.join(RUNS, rec['pre_png'])
        if not os.path.exists(png):
            continue
        if png not in cache:
            cache[png] = b.scores(imread(png, cv2.IMREAD_COLOR))
        lst = cache[png].get(tuple(rec['cell']))
        if not lst:
            continue
        v, sid, _f, _o = lst[0]
        got = rows.get(sid, {}).get('Name')
        good = got in truth
        ok += good
        bad += (not good)
        print('  %s 格%-8s 分类=%-12s(%-6s) %.3f  真值=%-8s  %s'
              % ('OK ' if good else 'xx ', rec['cell'], sid, got, v, '/'.join(truth),
                 rec['pre_png']))
    tot = ok + bad
    print('命中 %d/%d（跳过无真值 %d）' % (ok, tot, skip))
    return 0


def live_cmd(a):
    from mapbot import Bot
    b0 = Bot(log_prefix='spots')
    p = b0.snap('spots_live')
    print('截图', p)
    a.img = p
    return board_cmd(a) if a.board else target_cmd(a)


def calib_cmd(a):
    """重新标定几何：给定一张已知含 N 个相同地块的截图，扫 pitch/原点"""
    print('几何：设计格距 32px × 缩放 %.1f = 屏幕格距 %.1f；左上 (%.0f, %.0f)；单格贴图 %.0fx%.0f'
          % (SCALE, SCALE * DESIGN_PITCH, GRID['x0'], GRID['y0'],
             DESIGN_TILE * SCALE, DESIGN_TILE * SCALE))
    print('重现：python fit_art.py scale <截图> --probe S00003_001  # 找缩放')
    print('      python fit_art.py peaks <截图> --probe S00003_001  # 峰间距=格距')
    return 0


def state_cmd(a):
    """打印整盘状态（我看不了图，靠这个"看"）：每格 地块/分数/亮度比/可否点"""
    code = a.code or code_of(a.mapname)
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    b = Board(code)
    st = b.state(img, thr=a.thr)
    print('=== 状态（%s）: 名/分数/亮度比/亮暗 ===' % (a.img or 'live'))
    for r in range(1, 6):
        cells = []
        for c in range(1, 8):
            v = st.get((r, c))
            if not v:
                cells.append('%-22s' % '-')
                continue
            cells.append('%-8s%.2f %.2f%s' % ((v['name'] or '?')[:8], v['score'], v['ratio'],
                                              '亮' if v['revealed'] else '暗'))
        print('  r%d %s' % (r, ' | '.join(cells)))
    print('=== 标记 ===')
    for (r, c), v in sorted(st.items()):
        if v['anchor'] != (r, c):
            continue
        tag = []
        if v['name'] in BUY_OUT_NAMES:
            tag.append('★买完')
        if v['revealed']:
            tag.append('已揭示')
        print('  (%d,%d) %-12s %-8s %.3f 比%.2f %s'
              % (r, c, v['sid'], v['name'], v['score'], v['ratio'], ' '.join(tag)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    for name in ('board', 'target'):
        p = sub.add_parser(name)
        p.add_argument('img', nargs='?')
        p.add_argument('--map', dest='mapname')
        p.add_argument('--code')
        p.add_argument('--thr', type=float, default=0.80)
        p.add_argument('--board', action='store_true')
    p = sub.add_parser('live')
    p.add_argument('--map', dest='mapname')
    p.add_argument('--code')
    p.add_argument('--thr', type=float, default=0.80)
    p.add_argument('--board', action='store_true')
    p = sub.add_parser('verify')
    p.add_argument('--probe', default=os.path.join(RUNS, 'probe_spots.json'))
    p.add_argument('--code')
    p = sub.add_parser('state')
    p.add_argument('img', nargs='?')
    p.add_argument('--map', dest='mapname')
    p.add_argument('--code')
    p.add_argument('--thr', type=float, default=0.80)
    p = sub.add_parser('calib')
    p.add_argument('--write', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'board':
        return board_cmd(a)
    if a.cmd == 'target':
        return target_cmd(a)
    if a.cmd == 'state':
        return state_cmd(a)
    if a.cmd == 'live':
        return live_cmd(a)
    if a.cmd == 'verify':
        return verify_cmd(a)
    if a.cmd == 'calib':
        return calib_cmd(a)
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())


def aplus_event_names(map_code):
    """某张图里「A 级以上（紫/橙/红）的探索事件地块」的中文名集合

    判据（游戏 Area_Spot 表）：
        SpecialSpot == 1        # 探索事件类（会弹事件 ✓）
        MinBattleStep ∈ {A,S,SS}  # 档位 ≥ A ⇒ 紫以上 ✓
    例：夏日海滩(S00003) ⇒ {'木桶'(A), '贝壳'(S)} ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        if int(r.get('SpecialSpot') or 0) != 1:
            continue
        if (r.get('MinBattleStep') or '').upper() in ('A', 'S', 'SS'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


def event_tile_names(map_code):
    """某张图里**所有会产出事件的地块**（EventNum 非空 ✓）的中文名集合

    这些地块点开会弹「探索 / 战斗」面板 ✓；面板里若显示紫/橙/红掉落 ⇒ 点探索 ✓
    （点开面板只是预览、不消耗 ✓ ⇒ 可以放心逐个探 ✓）
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        ev = str(r.get('EventNum') or '').strip()
        if ev and ev not in ('0-0', '0'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


PURPLE_SUFFIX = ('221', '321')      # 紫地块（小助手官方判定 ✓）
ORANGE_SUFFIX = ('331',)            # 橙地块
EXPLORE_SUFFIX = PURPLE_SUFFIX + ORANGE_SUFFIX   # 紫以上 ⇒ 能进探索格子 ✓

# ⭐ 2026-09-26：紫/橙大块归属修正的分数线
#   实测（findA3.png）真大块成员分数 0.794，而"看起来不清"的格子会瞎猜到 0.21/0.30
#   ⇒ 0.70 干净分开 ✓（探索循环里原本就是用的 0.70，保持一致）
EXPLORE_BLOCK_MIN = 0.70
# ⭐⭐⭐ 2026-10-02：多格块归属修正的分数线（**比 EXPLORE_BLOCK_MIN 低**）
#   为什么需要第二个：EXPLORE_BLOCK_MIN=0.70 是按「紫橙大块」标定的，
#   而**所有**多格块（战斗格 103/104/111/211/221…）的美术都只覆盖部分成员格，
#   成员格自己的 top1 常被**单格模板**抢走。
#
#   真机帧 `runs/r_132022_0.png`（用户 2026-10-02 手工核对）：
#       4,3 属于 211 巨大沙堡（占 3,2/4,2/4,3/4,4，4 格），
#       但它自己的 top1 是 **014 限时礼包 0.435**，而 211 的分数是 **0.425**
#       ⇒ 只差 0.01 就被单格模板抢走 ⇒ 那一格单独认成「限时礼包」✗
#       ⇒ 下游会把它当成一个**独立 1 格目标**（凭空多出礼包/宝箱）
#
#   门槛取 **0.35**：多格块本体（有本体美术的成员格）实测落在 0.35~0.85，
#   而单格模板的瞎猜在那些格上普遍 0.10~0.44。
#     · 曾用 **0.40**，结果 `1,1`+`1,2` 的 **102 海边游客只有 0.370**
#       ⇒ 差 0.03 被门槛滤掉 ⇒ 两格**没合并**（用户 2026-10-02 手工核对时指出）✗
#     · 0.35 把它捞回来；仍高于纯噪声（实测最低的多格候选 0.157）
#   ⇒ 归属修正**失败**的后果（成员格各认各的、凭空多目标）比误聚成块严重得多
#     （后者会被 votes + 重叠去重滤掉）⇒ 门槛宁低不高。
#
# ⭐⭐⭐⭐⭐ 2026-10-14 **0.35 → 0.28**（用户报「第二张图的巨大沙堡没识别出来」）
#   ---- 病 ----
#     真沙堡的**正确摆放**（`2,1` 起、覆盖 `(2,1)(3,1)(3,2)(3,3)`）分只有 **0.290**
#     ⇒ **低于 0.35 从未进候选** ✗；而**错误摆放**（`1,2` 起、**含营地**）分 0.361
#     ⇒ 成了唯一候选 ⇒ 营地被吞 ✗✗
#   ---- 为什么 0.35 挡不住这种 ----
#     模板 `211` 是**整块 L 形大图**（94×62，见 `templates/unit/S00003/S00003_211/`）
#     ⇒ 逐格只截到它的**局部** ⇒ **正确摆放的单格分天生偏低**（实测真沙堡处 0.29）
#       而"水洼/岩石"那种**碰巧像**的地方反而能到 0.36 ⇒ 门槛卡在两者之间 **必然错** ✗
#   ---- 修法（两条一起才成立 ✓）----
#     ① 门槛 **0.35 → 0.28** ⇒ 正确摆放（0.290）能进候选 ✓
#     ② 进候选后由**形状判据**（`state()` 里那段：有任一格"自成一体"就弃块）
#        挡掉"含营地/草地"的错摆放 ✓
#     ⚠ 单降门槛**不行**：40 帧实测采纳块数 97 → 143（+47%）、且真沙堡仍被吞 ✗
#     ⚠ 只加形状闸门**也不行**：0.35 下真沙堡根本没进候选 ⇒ 认不出 ✗
#     ⇒ 实测「0.28 + 形状判据」= **118 块**，且
#        今天 B 帧认回 `2,1` 真沙堡 ✓、昨天 A 帧正确不误认 ✓（`_tmpman/chk_combo.py`）
MULTI_BLOCK_MIN = 0.28
# ⭐⭐⭐⭐⭐ 2026-10-26 **多格块不许在「单格通道」显示名字**（治「很多空地看成巨大沙堡」）
#   ---- 用户报告（原话）----
#     「还有第一张图怎么把很多空地看成巨大沙堡什么的了？」（帧 runs/r_191220_0.png）
#   ---- 病（逐格 top5 铁证，我实测）----
#     那张帧上 **6 格**被标成「巨大沙堡」：(3,1)(3,2)(3,3)(3,4)(4,1)(5,1)
#     但它们 `block_score=None` / `anchor=None` / `cells=[只有自己]`
#     ⇒ **不是块采纳**，是**单格 top1**；分数 **0.117~0.260**，
#       而**块门槛 `MULTI_BLOCK_MIN`=0.28** ⇒ 这些分**本该进不了块通道** ✗
#     该格 top5 **全是 211 的多个变体**（0.147/0.147/0.131…），
#     第 4~5 名才轮到别的（301 0.139 / 302 0.131）—— 而 301/302/101/221/321
#     **全是多格块**（占 2~8 格）⇒ 该格**没有任何单格模板**能认 ✓
#     ⇒ **根因：单格通道下，多格块模板的「局部匹配分」虽远低于块门槛，
#        却仍是该格的 top1 ⇒ 6 格全被标成「巨大沙堡」** ✗✗
#     对照（真沙堡帧 runs/r_195513_0.png）：
#       4 格 `block_score=0.586` / `anchor=(2,1)` ⇒ **走的是块通道** ✓ 0.586 远超门槛
#   ---- 修法（**只动 `name`，别的全不动**）----
#     判据：**该格没被任何块采纳**（`blk is None`）**且**它自己的 top1 sid 是**多格块**
#           ⇒ **名字置空**（=「认不出」，而不是乱猜一个名字）
#     ⇒ 多格块**只走块通道**显示名字（口径与归属修正统一 ✓）
#   ---- ⚠⚠⚠ 为什么**只能**动 `name`（我第一版踩过，血证）----
#     我第一版改的是**「单格通道重新挑 top1」** ⇒ `eff`(=sid) 变了
#     ⇒ `ratio` 的分母 `self._tpl_luma(eff)` 跟着变
#     ⇒ **「已揭示」判定被破坏** ⇒ 真机语料 1095 帧实测：
#        ratio 变化 **2817** 格、revealed 变化 **620** 格、名字被清空 **9613** 格 ✗✗✗
#        （38325 格里占 25%）⇒ **完全不可接受** ⇒ 已撤回重做 ✓
#     ⇒ 现在：`sid` / `eff` / `ratio` / `revealed` / `anchor` / `cells` **一个都不动**
#        ⇒ 下游按 sid 的技术判断（紫橙探索格、商人宝库、雾格剪影）**行为完全不变** ✓
#        ⇒ 只影响**显示的名字**（GUI 棋盘上那行字）✓
#   ---- 「名字置空」的下游安全性 ----
#     `name` 仍是 **str**（空串，不是 None）⇒ 下游 `'商人' in name` 之类**不炸** ✓
#     ⚠ 名字空 ⇒ 该格不会被当目标（名字是目标判据的一半）
#       ⇒ 那些格本来就是**低分误认**（< 0.28，够不到 `NAME_SCORE_MIN` 0.85）
#       ⇒ **本来就当不了目标** ⇒ 置空**不改变任何规划** ✓
STATE_TOPN = 5          # state() 保留每格前 N 个候选（大块归属要用后面的候选 ✓
                        #  矩阵乘那步本来就全算 ⇒ topn 只影响 argsort，代价可忽略 ✓）

# ⭐⭐⭐⭐⭐ 2026-10-08 **E7：同名「掩膜虚高」纠正开关**（见 `explore_blocks` 末尾长注释）
#   病：`103 游乐设施`(2格, 非紫金) 被认成 `221 游乐设施`(5格, **紫金探索格**)
#       ⇒ 走「探索+派遣」⇒ 派小队去打本该打的格 ✗（用户报「综合连派 3 支」）
#   根因：`221` 走**掩膜通道**（alpha 不满 ⇒ 只比 70.1% 像素）⇒ 分数虚高，
#        与 `103` 的**矩形分不是一个量纲** ⇒ 0.747 压过 0.606 ✗
#   修法：外科式局部替换（**只在不会连锁时**）⇒ 181 条真机现场实测**只动 2 处** ✓
#   ⚠ 开关默认 **开**；`MAPBOT_E7=0` 可关（回退排查用 ✓）
_E7_ON = os.environ.get('MAPBOT_E7', '1') != '0'
_E7_GAP = float(os.environ.get('MAPBOT_E7_GAP', '0.20') or '0.20')
# ⚠ E7 出错的计数与最后原因（**不静默** —— 本项目反复栽在"except: pass"上）
_E7_ERR = 0
_E7_ERR_LAST = ''

# 商人/宝库的识别门槛（与 explore_loop.BUY_SCORE_MIN 一致 ✓ 这里兜底给 spots 内部用）
BUY_SCORE_MIN = 0.85


def _is_strong_buy(o, rows=None):
    """这个物件是不是**强匹配的商人/宝库**（永不覆盖 ⇒ 2026-09-25 卡死事故）"""
    if not o:
        return False
    if float(o.get('score') or 0) < BUY_SCORE_MIN:
        return False
    rows = rows if rows is not None else spot_rows()
    return (rows.get(o.get('sid')) or {}).get('Name') in BUY_OUT_NAMES


def purple_event_names(map_code):
    """⭐ 某张图里能填「探索格子」的地块名（**紫/橙**：ID 后缀 221/321/331 ✓）

    依据：实例B小助手 AreaBlockView 里的官方分类
        紫地块 = 后缀 221 / 321 ；橙地块 = 331
        （木桶 006 / 贝壳 007 属于「宝箱与装备」⇒ 进不了探索格子 ✗）
    夏日海滩 ⇒ 游乐设施(221) / 巨大沙堡(321) / 海边小屋(331) ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        if sid.split('_')[-1] in EXPLORE_SUFFIX:
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


def _old_purple_event_names(map_code):
    """某张图里「**固定紫/橙探索**」的地块名集合

    判据（游戏 Area_Spot 表）：
        EventNum 非空（会产出事件 ✓）
        且 MinBattleStep ∈ {A, S}（档位 ≥ A ⇒ 探索事件固定紫/橙 ✓）
    夏日海滩 ⇒ {木桶, 限时礼包, 黄金宝库, 游乐设施, 巨大沙堡, 异界之门,
                贝壳, 传承祭坛, 预言石碑, 海边小屋} ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        ev = str(r.get('EventNum') or '').strip()
        if not ev or ev in ('0-0', '0'):
            continue
        if (r.get('MinBattleStep') or '').upper() in ('A', 'S', 'SS'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out
