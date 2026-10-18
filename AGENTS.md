# AGENTS.md · AI 必读（**不是给用户看的**）

> ⚠⚠⚠ **本文件是给 AI 助手 / 维护者的操作纪律，不是用户文档。**
> 用户文档是 `README.md`（面向使用者）和 `docs/`（用法说明）。
> 每当你要**打包、发版、上传、改启动器**之前 —— **先读完这一页**。

---

## 0. 这个仓是什么 / 不是什么

| | 说明 |
|---|---|
| ✅ 是 | **MGAS PC 端的唯一源码仓**（用户口径：「以发布仓为唯一源」）<br>业务代码全在 `core/`；资源在 `templates/` `data/` |
| ❌ 不是 | 不是「生成物仓」。**不要**从别处同步覆盖本仓；本仓就是源 |
| 📤 两个出口 | ① GitHub `ShanJiu666/MonsterGirlsAutoScript`（**公开**，完整代码）<br>② Gitee `geng-haojie/MonsterGirlsAutoScript`（**公开**，完整代码镜像） |
| 📦 热更出口 | Gitee `geng-haojie/MGAS-pc-update`（**公开**，manifest + 补丁 zip） |

---

## 1. ⛔⛔⛔ 最容易犯的错：把「自用版启动器」传上去

### 事实
`tools/launcher/` 下有**两个** exe，外观、大小、图标**完全一样**：

| 文件 | 怎么编 | 行为 | 该不该发人 |
|---|---|---|---|
| `MGAS.exe` | `python tools/launcher/build_launcher.py` | **朋友版**：不存图、关精确规划 | ✅ **这个才是要发的** |
| `MGAS-dev.exe` | `python tools/launcher/build_launcher.py --dev` | **自用版**：存图开 + 精确规划开 | ❌ **绝不外发** |

### 它们的唯一区别（字节级）
`MGAS-dev.exe` 里多一句话：
```csharp
#if MGAS_DEV
    psi.EnvironmentVariables["MAPBOT_FRIEND"] = "0";
#endif
```
编译后实测：
```
MGAS.exe      MAPBOT_FRIEND 出现 0 次   ← 朋友版干净
MGAS-dev.exe  MAPBOT_FRIEND 出现 1 次   ← 自用版才有
```

### 传错了会怎样
朋友的包会**每张图存一张 ≈0.7MB 的 PNG**（`runs/r_<时间>_0.png`）
⇒ 几十张图就把别人硬盘撑爆,且他们**不知道为什么**。
（用户已明确：「我自用的时候要开启存图功能」—— 那是**只给用户自己**的。）

### ⚠ exe 的位置（2026-10-18 已改，别按老习惯找）
```
tools\launcher\MGAS.exe        ← 朋友版源（打包脚本 build_release_pkg.py:385 拷这个）
tools\launcher\MGAS-dev.exe    ← 自用版源（打包时也会拷进包根）
dist\MGAS-v1.0-portable\       ← 整包（**两个 exe 都在这里**，这才是用户/你双击的地方）
```
⛔⛔ **仓根没有 `MGAS.exe` 了**（2026-10-18 按用户要求删除）
  ---- 为什么删 ----
    那个 exe 周围**没有 `python311/`** ⇒ 双击必然报「缺少依赖」（实测：PATH 里找
    到的 Python 3.11 缺 `rapidocr_onnxruntime`）⇒ 用户反复误点 ✗
    而 README 早就写着「仓库里没有能直接双击的根目录 exe」⇒ **删掉才与文档一致**
  ⇒ **以后不要再往仓根放 exe** ✓

### 自用版 = 你自己的那份（双击 `dist\...\MGAS-dev.exe`）
- `MAPBOT_FRIEND=0` ⇒ `IS_FRIEND=False` ⇒ **存图开 + 精确规划开**
- 实测：`IS_FRIEND=False SAVE=True SOLVER=True`
- ⚠ `MGAS-dev.exe` **不进 git**（`.gitignore` 已挡），只在 `dist/` 里出现
- ✅ 打包脚本已自动带上它（`build_release_pkg.py` 第 390 行之后）
  ⇒ 以前每次 `Remove-Item dist` 都会丢，现在不会了 ✓

### 动手前的三条自检
⚠⚠ **别用 PowerShell 数** —— 我实测踩过：`[Text.Encoding]::ASCII.GetString($b).Split(...)`
   在这台机上对**朋友版** exe 也报出 `MAPBOT_FRIEND = 1075`（**假阳性**），
   差点以为传错了自用版。**用下面这段 Python**（同一份文件它数出 0，才可信）：

```powershell
$py = 'C:\Users\PC\.workbuddy\binaries\python\envs\mapbot\Scripts\python.exe'
& $py -c @"
import os
REL = r'D:\MGAS\_release_pc'
PKG = os.path.join(REL, 'dist', 'MGAS-v1.0-portable')
def marker(p):
    b = open(p, 'rb').read()
    return b.count(b'MAPBOT_FRIEND') + b.count('MAPBOT_FRIEND'.encode('utf-16-le'))
files = [('launcher/MGAS.exe', os.path.join(REL, 'tools', 'launcher', 'MGAS.exe')),
         ('launcher/MGAS-dev.exe', os.path.join(REL, 'tools', 'launcher', 'MGAS-dev.exe')),
         ('pkg/MGAS.exe', os.path.join(PKG, 'MGAS.exe')),
         ('pkg/MGAS-dev.exe', os.path.join(PKG, 'MGAS-dev.exe'))]
for label, p in files:
    if not os.path.isfile(p):
        print('  %-24s (不存在)' % label); continue
    m = marker(p)
    ok = (m == 0) if 'dev' not in label.lower() else (m == 1)
    print('  %-24s MARKER=%s %s' % (label, m, 'OK' if ok else '*** 错 ***'))
"@
```
期望输出：**仓根 + launcher 的 `MGAS.exe` 都是 0；只有 `MGAS-dev.exe` 是 1**。

```powershell
# ② MGAS-dev.exe 必须在 .gitignore 里
git -C D:\MGAS\_release_pc check-ignore -v tools/launcher/MGAS-dev.exe

# ③ 它不该出现在 git 跟踪列表里
git -C D:\MGAS\_release_pc ls-files tools/launcher/
```
**任一条不满足 ⇒ 停下，别打包。**

---

## 2. 「朋友版 / 自用版」的运行期机制（改之前先懂）

`core/friend_mode.py`：优先级 **环境变量 `MAPBOT_FRIEND` > 包根 `friend_mode.flag` > 默认开发版**

```
打包时写 friend_mode.flag 到包根
  ⇒ bootstrap.py 见到 flag ⇒ os.environ['MAPBOT_FRIEND']='1'
  ⇒ friend_mode.IS_FRIEND = True
  ⇒ bot_gui.py: if not FRIEND: 不成立 ⇒ **不创建存图勾选框**
  ⇒ saveimg_var 强制 False
```

| 状态 | `IS_FRIEND` | 存图 | 精确规划 |
|---|---|---|---|
| 发布包（有 flag） | True | ❌ | ❌ |
| `MAPBOT_FRIEND=0` | False | ✅ | ✅ |
| 删掉 flag | False | ✅ | ✅ |

⚠ **为什么不用「打包时改源码」**：热更补丁是按仓库源码生成的，
   改源码会被补丁冲回开发版 ⇒ 必须**运行期判断**（这正是 `friend_mode.py` 存在的原因）。

⚠ **`friend_mode.flag` 已在 `.gitignore`**，别把它提交。

---

## 3. 发版 / 热更操作手册

### 3a. 只发代码（99% 的情况，热更）
```powershell
$py = 'C:\Users\PC\.workbuddy\binaries\python\envs\mapbot\Scripts\python.exe'
cd D:\MGAS\_release_pc
& $py tools\release_pc.py --notes "说明" --dry-run   # 先看要发什么
& $py tools\release_pc.py --notes "说明"             # 真发
```
⇒ 更新 Gitee `MGAS-pc-update` 的 `manifest.json` + `pc/hot-pc-*.zip`

**补丁规则**（`release_pc.py` 自动处理，别手改）：
- 内容 = 从 `bot_gui.py`/`explore_loop.py` 出发的 **import 闭包** + `templates/fixed/*.png`
- zip 内路径**平铺**（`explore_loop.py`，不带 `core/`）—— 端上 `_dst_of()` 会落到 `core/` ✓
- **引导层永不进补丁**：`bootstrap.py` / `hotupdate.py`（改了必须重发整包）

### 3b. 必须重发整包的情况
- 改了 `bootstrap.py` / `hotupdate.py`（引导层）
- 改了 `MGAS.exe` 启动器
- 改了 `python311/` 依赖
- 改了 `friend_mode.flag` 相关逻辑

```powershell
& $py tools\build_release_pkg.py
# ⇒ dist/MGAS-v1.0-portable/  +  dist/MGAS-v1.0-portable.zip
# 然后 gh release upload（见 §3d）
```

### 3c. 三个出口的推送
```powershell
# GitHub（SSH）
git push origin main

# Gitee 代码镜像（⚠ 令牌走临时 URL，**绝不 add remote**，否则令牌进 .git/config）
$tok = Get-Content "$env:USERPROFILE\.gitee_token" -Raw
$u = "https://geng-haojie:$($tok.Trim())@gitee.com/geng-haojie/MonsterGirlsAutoScript.git"
git push $u HEAD:master --force
git remote -v    # ← 推完必须确认这里**没有**令牌

# 热更：用 §3a 的 release_pc.py，别手动 git push 那个仓
```

### 3d. 更新 GitHub Release 整包
```powershell
gh release upload v1.0 dist\MGAS-v1.0-portable.zip `
   --repo ShanJiu666/MonsterGirlsAutoScript --clobber
# 核 digest：
gh release view v1.0 --repo ShanJiu666/MonsterGirlsAutoScript --json assets
```

---

## 4. 已验证的坑（都是真机上抓到的，别再踩）

| # | 坑 | 后果 | 现状 |
|---|---|---|---|
| 1 | `prune_old_hot` 按**文件名字典序**删旧补丁 | `0ed0504c` 的 `'0' < '6'` ⇒ **刚传的新补丁被删** ⇒ 客户端 404 | ✅ 已修（按 manifest id 保护 + 时间倒序） |
| 2 | `hotupdate.OWNER/REPO` 留空 | `configured()=False` ⇒ **端上根本不检查更新** ⇒ 热更等于不存在 | ✅ 已内置 |
| 3 | Gitee 没有 `releases/latest/download/` API | 先试 API ⇒ **白等 15 秒**超时才回落 raw | ✅ 已改成默认直接走 raw（0.36 秒） |
| 4 | 目录整理后 `join(HERE,'maa_sidecar.py')` | `HERE`=仓根、文件在 `core/` ⇒ **极速截图永久失效**（退回 adb 慢 15 倍） | ✅ 已改用 `_SELF_DIR` |
| 5 | 同族的 `HERE` 拼 `.py` 路径 | `hotupdate.py` / `recruit.py` / `bot_gui.py` / tests 25 个文件 | ✅ 已全盘排查修完 |

⚠ **改任何「按路径引用文件」的代码后，跑一遍这个扫描**（找 `join(HERE|_MGAS_ROOT, 'xxx.py')` 但文件在 `core/`）：

```powershell
& $py -c @"
import io, os, re
REL = r'D:\MGAS\_release_pc'
CORE = os.path.join(REL, 'core')
CORE_PY = {f for f in os.listdir(CORE) if f.endswith('.py')}
PAT = re.compile(r\"os\.path\.join\(\s*(HERE|_MGAS_ROOT|ROOT)\s*,\s*'([A-Za-z_]\w*\.py)'\")
bad = []
for sub in ('core', 'bot_gui_ui', 'tests'):
    d = os.path.join(REL, sub)
    if not os.path.isdir(d): continue
    for f in sorted(os.listdir(d)):
        if not f.endswith('.py'): continue
        s = io.open(os.path.join(d, f), encoding='utf-8', errors='replace').read()
        for m in PAT.finditer(s):
            if m.group(2) in CORE_PY:
                bad.append('%s/%s: %s' % (sub, f, m.group(2)))
print('需检查 %d 处' % len(bad))
for b in bad[:20]: print('  ' + b)
"@
```

---

## 5. 门禁（改完必跑）

```powershell
$py = 'C:\Users\PC\.workbuddy\binaries\python\envs\mapbot\Scripts\python.exe'
$env:MAPBOT_GATE_SEQ = '1'          # 串行，避免并发抢资源
& $py core\verify_gate.py
```
**基线：0 失败 / 7 跳过**。不一致就别提交。

⚠ 跑前清干净：`runs/` `logs/` `__pycache__/`（否则残留会干扰）。

---

## 6. 提交信息怎么写

用中文，说清 **为什么改** + **真机证据** + **怎么验证的**。
坏例子：`fix bug`
好例子（本仓真实提交）：
```
fix(paths): 目录拆分遗漏 —— sidecar 启动路径仍按仓根找，导致极速截图永久失效

用户实测：
    ⚠ 极速截图服务没起来 → 本次用 adb 截图
sidecar_20001.err 真因：can't open file '...\maa_sidecar.py'
根因：拆分后 bot_gui.py 的 HERE 改成仓根，但 maa_sidecar.py 在 core/
修法：改用 _SELF_DIR（= core/）
验证：包内 python311 起 sidecar ⇒ 端口 listen、抓帧 0.021 秒 ✓
```

---

## 7. 绝对不要做的事

1. ❌ **把 `MGAS-dev.exe` 传上 GitHub / 打进发布包**（见 §1）
2. ❌ 把 Gitee 令牌写进任何**会被提交**的文件 / `git remote add`
3. ❌ 用 `git checkout -f` / `git reset --hard`（会冲掉未提交的工作）
4. ❌ 手改 `dist/` 里的文件后重新压缩（必须走 `build_release_pkg.py`）
5. ❌ 改 `core/hotupdate.py` 后指望热更生效（它是引导层，必须重发整包）
6. ❌ 在两个仓之间「整文件覆盖」同步（`mapbot_pc` 已废弃，见 §8）

---

## 8. 历史遗留：`D:\MGAS\mapbot_pc`（**已废弃**）

那是旧的平铺结构自用仓（217 个 `.py` 在仓根 + 4.4GB `runs/`）。
用户已决定「**以发布仓为唯一源**」⇒ **不要**再往它同步，也不要从它拷代码。

### ✅ 那五处性能优化 + UI 优化**已经搬完**（2026-10-18，提交 `c8aaf5f`）

| # | 位置 | 改动 | 实测（本仓，真机帧） |
|---|---|---|---|
| 1 | `core/marks.py` `match_jobs_parallel` | 4 线程并行匹配 | **0.896 s**（串行 2.97） |
| 2 | `core/marks.py` 模板像素级去重 | 8→7 job | 少 80 次匹配 |
| 3 | `core/mapbot.py` `Bot.ocr` | 直接传 ndarray，不落盘 | **0.688 s**（旧 0.912，省 17%） |
| 4 | `core/loopguard.py` `own_pids` | 一条 PS 脚本取完整祖先链 | **1.667 s**（旧 3.489） |
| 5 | `core/fastcap.py` `_recv_exact` | 整帧共用 deadline + `bytearray` | 已接线 |

**UI 也搬了**：`ctk_widgets.py`（方案 A 描边）、`theme.py`（棋盘 54→56）、
`ctk_theme.py`、`widgets.py` 全量覆盖；`bot_gui.py` **hunk 级移植 32/36**
（跳过 4 个是我自己的 `core/` 路径修复）。

### ⚠⚠ 搬的时候踩了 3 个「搬一半」的坑（记住这个模式）

| # | 坑 | 后果 |
|---|---|---|
| 1 | `marks.py` 漏 `from concurrent.futures import ThreadPoolExecutor` | **运行时 `NameError`，scan_board 直接崩** |
| 2 | `fastcap` 只搬函数体、**没搬调用点** | `deadline` 收不到 ⇒ **优化零效果** |
| 3 | 补调用点时漏了 `_budget` 定义段 | `NameError: _budget` |

⇒ **教训：「函数搬过来了」≠「优化生效了」** —— 依赖（import / 调用点 / 局部变量）
   必须逐个核对。第 1 个是**真机 bench 跑出异常**才发现的，光看语法检查会漏 ✗

---

## 9. 关键路径速查

```
D:\MGAS\_release_pc\               ← 本仓（唯一源）
├── core\                          ← 业务 .py（32 个）
├── bot_gui_ui\                    ← GUI 子包
├── templates\                     ← 识别模板（11193 个）
├── data\                          ← server_datatable.json
├── tools\
│   ├── build_release_pkg.py       ← 打整包
│   ├── release_pc.py              ← 发热更补丁（★ 只在这个仓有）
│   ├── audit_pkg_integrity.py     ← 包完整性体检
│   └── launcher\
│       ├── MGASLauncher.cs        ← 启动器源码（#if MGAS_DEV）
│       ├── build_launcher.py      ← 编译（--dev = 自用版）
│       ├── MGAS.exe               ← ✅ 要发的（朋友版）
│       └── MGAS-dev.exe           ← ⛔ 自用（.gitignore 已挡）
├── dist\                          ← 打包产物（.gitignore）
└── runs\ logs\                    ← 运行期（.gitignore）

令牌位置：C:\Users\PC\.gitee_token   （32 字符，**不在仓里**）
```

---

**最后一句**：这个项目的历史教训是「**判据在拿不到数据的地方 ⇒ 静默失效**」，
已经踩了至少 6 次。改任何判据前，先问：**它拿得到数据吗？拿不到时会怎样？**
