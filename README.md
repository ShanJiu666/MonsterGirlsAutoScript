# MGAS PC · 游戏探索自动刷图工具（PC 端）

> 基于**屏幕图像识别**的自动化辅助工具：截图 → OCR / 模板匹配 → 模拟点击，
> 在 MuMu 模拟器上自动完成游戏的「探索」玩法。
>
> **不做**：不读改游戏内存、不注入进程、不改网络数据包、不改游戏文件。
> 纯视觉 + 模拟输入，等价于「有个手在替你点」。

---

## 先读这个

### 我只是想用，不想装 Python

去 **[Releases](../../releases)** 下载 `MGAS-vX.Y-portable.zip`（约 370 MB）：
解压 → 双击 `MGAS.exe` → 开跑。**里面已经带好 Python 与全部依赖**。

> 压缩包里有近 3 万个文件，解压要一两分钟。
> **等进度条真正走完再双击**，否则会提示「包不完整」（那不是软件坏了）。

### 我下的是源码（clone 这个仓库）

⚠ **仓库里没有「能直接双击的根目录 exe」** —— 这是有意的：

| 你想要的 | 在哪 |
|---|---|
| **源码 / 自己改** | 本仓库就是（跑 `python bot_gui.py`，需自装依赖） |
| **exe 启动器** | `tools/launcher/MGAS.exe`（可以直接双击，但**周围没有 python311**，需要本机已装 Python 3.11 + 依赖） |
| **重新编译 exe** | `python tools\launcher\build_launcher.py`（用系统自带 csc，零安装） |
| **做一个能发给别人的整包** | `python tools\build_release_pkg.py` ⇒ 产出 `dist\MGAS-vX.Y-portable\` + `.zip`（这一步才会把 exe 复制到**包根**并内嵌 Python） |

> 为什么 exe 不放在仓库根？
> 因为根目录的 `MGAS.exe` **只有在有 `python311\` 陪同时才可用**。
> 源码仓库不带那 800 MB 运行时（也不该进 git），所以根目录放 exe 只会误导人。
> 打包脚本会自动把它放到包根 ⇒ **下载包的用户看得到，源码用户看得到来源**。

### 法律与风险

1. 本项目与游戏开发商 / 发行商**无任何关联**，未获其授权或背书。
2. 请只用**你自己拥有并自己登录**的账号，并自行确认所在游戏的规则。
3. 使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 它能做什么

| 能力 | 说明 |
|---|---|
| **自动进图** | 识别选图界面、读体力，体力不足时停下（门槛可配） |
| **识别棋盘** | 5×7 棋盘逐格识别地块类型（模板匹配，给出候选与置信度） |
| **识别标记** | 首领 / 大拇指 / 幸运草 / 红装等图标 |
| **最省体力规划** | 以体力消耗为代价做 A\* 求解，按点序执行 |
| **自动处理面板** | 黄金宝库、旅行商人、预言石碑、勇者之墓、限时礼包等 |
| **多开支持** | 多个模拟器实例独立运行（日志 / 截图 / 统计互不干扰） |
| **图形界面** | tkinter GUI：选设备、看实时日志、勾选目标类型 |

核心资产是识别 + 规划那套逻辑（`spots.py` / `mapsim.py` / `mapsolve.py` /
`explore_loop.py`），每条判据背后都有真机事故复盘，详见 [开发档案](docs/开发档案.md)。

---

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11 |
| Python | **3.10 / 3.11**（3.12+ 未验证；`airtest` 钉死 `numpy` 1.x） |
| 模拟器 | **MuMu 模拟器 12**（Android 12 或更高） |
| 分辨率 | **720×1280**（本项目唯一基准，见下） |

### 为什么锁定 720×1280

实测结论是「**能点固定位置的就用固定位置，只能 OCR 的才 OCR**」：

| 手段 | 单次耗时 |
|---|---|
| 模板匹配（固定 UI） | **6.8 ms** |
| 写死坐标直接点 | **0 ms** |
| OCR 一条带 | **3300 ~ 3600 ms** |

⇒ 固定 UI 一律走 `fixed.py` 的锚点 / 模板快查（比 OCR **快 400 倍以上**）。
代价是**不做任意分辨率自适应** —— 请把模拟器设为 **720×1280**。

---

## 快速开始

### 1. 装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
```

> ⚠ 请确保 `numpy` 停在 **1.x**：`airtest` 与之绑定。
> `requirements.txt` 里已钉好版本，直接装即可。

### 2. 准备模拟器

1. 安装 **MuMu 模拟器 12**，在里面装好游戏并登录；
2. 启动模拟器，确认 `adb` 连得上：

```powershell
adb connect 127.0.0.1:16384
adb devices
```

> ⚠ MuMu 自带 `adb` 占着 **5037**，本项目用 **5038**。
> adb 路径一律**自动探测**，可用 `MAPBOT_ADB` 环境变量覆盖。

### 3. 环境体检

```powershell
python paths.py
```

`adb` 与 `templates` 两项应为 `[ok]`。缺 `templates/` ⇒ clone 不完整。

### 4. 启动图形界面

```powershell
python bot_gui.py
```

选设备 → 勾选目标 → 点「开始」。

### 5. 或直接命令行

```powershell
# ⚠ 先只跑 1 张图验证，别一上来就挂机
python explore_loop.py --device 127.0.0.1:16384 --maps 1 --deadline 180
```

---

## 命令行用法

```powershell
# 跑 5 张图，最多 10 分钟
python explore_loop.py --device 127.0.0.1:16384 --maps 5 --deadline 600

# 只看一帧的识别结果（不点任何东西，最安全的调试方式）
python spots.py board runs/some_frame.png
python marks.py runs/some_frame.png

# 离线复算：用一张截图建盘，跑一遍规划策略
python mapsim.py --sample runs/some_frame.png
```

常用环境变量：

| 变量 | 用途 |
|---|---|
| `MAPBOT_ADB` | adb.exe 路径（探测不到时显式指定） |
| `MAPBOT_MUMU_HOME` | MuMu 安装根目录 |
| `MAPBOT_DATATABLE` | 游戏数据表路径 |

---

## 工作原理

```
   ┌─────────────┐   截图     ┌────────────────┐
   │   模拟器     │ ─────────► │  Bot（mapbot）  │
   └─────────────┘            └───────┬────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
      │  识别层        │      │  规划层        │      │  执行层        │
      │  spots.py     │      │  mapsim.py    │      │  explore_loop │
      │  marks.py     │ ───► │  mapsolve.py  │ ───► │  面板处理      │
      │  grid_detect  │      │  strategy.py  │      │  buypanels.py │
      └───────────────┘      └───────────────┘      └───────────────┘
              ▲                                             │
              │            模板 / 数据表                      │ 模拟点击
              └─────────────────────────────────────────────┘
```

**一次循环**：截图 → 识别棋盘与标记 → 建模型（`MapSim`）→ A\* 求最省体力点序
→ 逐步执行（点格 / 处理面板 / 等战斗）→ 直到目标清空或体力不足。

**关键设计**：识别层与规划层**分离**，规划层只吃一个「观测快照」，
因此可以**离线复算**（`mapsim.py --sample`）。这也是本项目能积累大量回归测试的原因。

---

## 常见问题

**clone 下来跑不起来 / 提示缺文件**
先 `python paths.py` 体检：确认 `templates/` 完整（应有一万多个文件），
以及 `adb` 能被找到（装 Android SDK，或设 `MAPBOT_ADB`）。

**提示「找不到 adb」**
探测顺序：`MAPBOT_ADB` → `ANDROID_SDK_ROOT` / `ANDROID_HOME` →
`%LOCALAPPDATA%\Android\Sdk` → MuMu 安装目录 → `PATH`。装在非常规位置就显式指定：

```powershell
$env:MAPBOT_ADB = 'D:\MuMu Player 12\shell\adb.exe'
```

**分辨率不是 720×1280 会怎样**
**不会自适应**。所有坐标与模板都按 720×1280 标定，换分辨率会导致识别与点击错位。

**整体偏慢**
OCR 是主要瓶颈（一条带 3.3~3.6 秒）。本项目已把**固定 UI 全部改走模板快查**，
OCR 只留给确实会变的内容（体力数字、倒计时、图名、道具名、价格）。

可选装 MaaFramework 极速截图通道（0.013 秒/帧 vs adb 0.33 秒/帧，快 25 倍）。
若 `_maa_venv` 不存在会自动退回 adb 截图，**只是慢，不影响功能**。

**自检套件里有失败项**
本仓**不包含**开发时的真机录屏语料（开发者本地数据，且含个人游戏数据）。
少数依赖那些语料的回归项会**明确报「跳过 / 缺语料」**，这不是代码故障。
不依赖语料的核心自检：

```powershell
python verify_gate.py
```

---

## 项目结构

**仓根只放运行时模块、入口与必须项**（38 个文件，一眼能看完），其余都进子目录。

```
仓根（运行时）
├── explore_loop.py        主状态机（最核心）
├── bot_gui.py             tkinter 图形界面
├── mapbot.py              设备接口：截图 / 点击 / OCR / 等待
├── spots.py               棋盘识别（逐格模板匹配）
├── marks.py               标记识别（首领 / 大拇指 / 幸运草 / 红装）
├── mapsim.py              棋盘模型（地块语义 → 可规划对象）
├── mapsolve.py            A* 最省体力求解
├── mapgen.py              地图生成器（离线复算 / 对照）
├── strategy.py            策略与目标优先级
├── fixed.py               提速层：720×1280 固定锚点 + 模板快查
├── buypanels.py           宝库 / 商人 / 石碑等面板流程
├── layout.py              版面锚点常量
├── targets_cfg.py         目标类型配置
├── grid_detect.py / badge.py / cells.py    几何自检与角标识别
├── paths.py / repo_paths.py                路径探测与环境体检
├── bootstrap.py / hotupdate.py / loopguard.py   启动、热更、看门狗
├── fruit.py / recruit.py / guild_*.py      果实记录、招募、公会
├── verify_gate.py         回归测试总入口
├── requirements.txt / PC_VERSION           依赖与版本号
├── run_bot.ps1 / collect_frames.bat        两个启动器
├── README.md / LICENSE / DISCLAIMER.md / .gitignore
│
└── 子目录
    ├── bot_gui_ui/        GUI 主题与控件
    ├── templates/         识别模板与资源        ⚠ 见下
    ├── data/              游戏数据表            ⚠ 见下
    ├── tests/             各模块回归测试（74 个）
    ├── devtools/          排障 / 取证 / 离线分析（58 个）
    ├── tools/             打包工具
    ├── docs/              使用说明书 / 算法 / 策略
    └── _verify/           回归测试用的冻结帧
```

| 目录 | 里面是什么 | 怎么用 |
|---|---|---|
| `tests/` | 回归测试（结构级 + 执行级 + 对照项） | `python verify_gate.py` 一次跑全套 |
| `devtools/` | 排障与离线分析 | 按需单跑，如 `python devtools/see.py` |
| `docs/` | 使用说明书 / 地图生成算法 / 策略说明 | 直接读 |

判据都集中在**少数几个模块**里，且每个判据背后都写着它是被哪次真机事故逼出来的
（在源码注释里搜「真机铁证」能看到全部）。

### 关于 `templates/` 与 `data/server_datatable.json`

这两个是**识别与规划所必需**的资源，其权利属于**游戏开发商**。
本项目的 MIT 许可证**不覆盖**它们（见 [LICENSE](LICENSE) 与 [DISCLAIMER.md](DISCLAIMER.md)）。

如果你是权利人并希望移除，请提出，会立即删除。
删除后**纯逻辑层仍可完整运行**（地图生成、求解器、规划策略都不依赖它们），
但**逐格识别会失效** —— 因为识别本质上就是拿游戏自己的贴图做模板匹配。

---

## 许可

- **源代码与文档**：[MIT](LICENSE)
- **第三方素材**（游戏美术、数据表等）：权利归各自权利人，**不在 MIT 授权范围内**
- 使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)
