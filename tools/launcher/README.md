# 启动器（MGAS.exe）

Windows 原生启动器，**18.5 KB（含图标），零运行时依赖**（用系统自带的 .NET Framework）。

图标：**「机甲核心魔偶」的官方像素头像**（`M31302_000`，30×30）

## 它是干什么的

只做三件事，**不含任何业务逻辑**（逻辑全在 Python 侧，便于热更新）：

1. 找到包内的 Python（`python311\python.exe`）
2. 启动 `bot_gui.py`
3. 出错时弹**可读的对话框** + 把完整输出写进 `logs\launcher.log`

## 图标怎么来的

```
head_M31302_000.png  （30×30 官方像素格，1947 B）
        ↓  make_exe_icon.py（NEAREST 放大 7 个尺寸）
    MGAS.ico         （9.4 KB：16/24/32/48/64/128/256）
        ↓  csc /win32icon:
    MGAS.exe         （图标内嵌）
```

**为什么必须用 NEAREST 放大**：源图是像素画，用双线性/双三次会糊成一团。
**为什么要多尺寸**：任务栏取 16/32、桌面取 48/256、资源管理器大图标取 96/128，
只放一个尺寸会被系统拉伸变糊。

重新生成图标：

```powershell
python tools\launcher\make_exe_icon.py   # → MGAS.ico
python tools\launcher\build_launcher.py  # → MGAS.exe（带图标）
```

> GUI **窗口**的左上角小图标另外处理：`bot_gui.py` 里的 `_set_window_icon()`
> 用 `iconphoto` 吃同一张 PNG（放大 4× 保住像素边缘）。

## 为什么不用 PyInstaller / cx_Freeze

| | PyInstaller 等 | 本方案 |
|---|---|---|
| 需要安装 | 要 `pip install pyinstaller` | **零安装**（系统自带 `csc.exe`） |
| 包体影响 | 会把整个 Python 塞进 exe（几十 MB） | **18.5 KB** |
| 热更新 | exe 一改就得重打包 | exe 不变，只更 Python 侧 |

## 重新编译

```powershell
python tools\launcher\build_launcher.py
```

产物：`tools/launcher/MGAS.exe`

## 两个已经踩过的坑（改动前必读）

### ① winexe 里不能直接设 `Console.OutputEncoding`

`/target:winexe` 的程序**没有控制台**，设 `Console.OutputEncoding` 会抛
`IOException: 句柄无效` ⇒ 启动器一启动就崩（退出码 `-532462766` / `0xE0434352`）。

**修法**：包在 `try { } catch { }` 里。

### ② python 的查找顺序

正式发布包把依赖**并进** `python311\Lib\site-packages`（不再带 venv），
所以必须**先找 `python311\python.exe`**。

> 若顺序反了（先找 venv），会命中一个没有依赖的裸解释器 ⇒ 启动时报
> `ModuleNotFoundError: customtkinter`。

**这也解释了为什么发布包不用 venv**：`venv\pyvenv.cfg` 的 `home` 必须是
**绝对路径**（Python 不接受相对路径），包一移动就报 `No Python at '...'`。
而 `python311\Lib\site-packages` 由解释器按自身位置算 ⇒ 随便搬都能跑。

## 相关的打包脚本

- `tools/build_release_pkg.py` —— 打「下载即用」的发布包（含内嵌 Python + 依赖）
- 使用说明（面向下载者）：`tools/launcher/使用说明-发布包.md`
