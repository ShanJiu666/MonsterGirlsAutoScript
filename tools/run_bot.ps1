<#
幻想少女公会 · 自动探索 —— 启动器（纯本地，不需要 AI）

位置：`tools/run_bot.ps1`（仓根已整理，启动脚本归到 tools/）

用法（也可以直接双击）：
    右键本文件 → 使用 PowerShell 运行
    或：powershell -ExecutionPolicy Bypass -File run_bot.ps1

前置条件（缺一个就跑不起来，脚本会提示）：
    1) MuMu 模拟器已启动、游戏已登录、停在**选图界面或地图里**
    2) 能连上 adb（自动探测；也可用环境变量 MAPBOT_ADB 指定）
    3) 有 Python 环境并已 pip install -r requirements.txt

可用环境变量覆盖：
    MAPBOT_ADB     adb.exe 的绝对路径（探测不到时用）
    MAPBOT_DEV     设备号，默认 127.0.0.1:16384
    MAPBOT_PY      python.exe 的绝对路径，默认用 PATH 里的 python
#>

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ⚠ 本脚本在 `tools/` 里（2026-10-17 目录整理）：**仓根 = 上一级**
#   以下 `$Here` 一律指**仓根**（templates/ runs/ core/ 都相对它）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Here = Split-Path -Parent $ScriptDir          # tools/ 的上一级 = 仓根
Set-Location $Here

# python：优先环境变量，其次仓内 .venv，最后 PATH
$PY = $env:MAPBOT_PY
if (-not $PY) {
    $venvPy = Join-Path $Here '.venv\Scripts\python.exe'
    if (Test-Path $venvPy) { $PY = $venvPy } else { $PY = 'python' }
}

# adb：优先环境变量，其次 PATH
$ADB = $env:MAPBOT_ADB
if (-not $ADB) { $ADB = 'adb' }

$DEV = $env:MAPBOT_DEV
if (-not $DEV) { $DEV = '127.0.0.1:16384' }

$LOGDIR = Join-Path $Here 'runs'

function Check-Env {
    $ok = $true

    $pyExe = $null
    try { $pyExe = (Get-Command $PY -ErrorAction Stop).Source } catch { }
    if (-not $pyExe) {
        Write-Host "✗ 找不到 python（$PY）——装好 Python 并 pip install -r requirements.txt" -ForegroundColor Red
        Write-Host "  也可以用环境变量 MAPBOT_PY 指定绝对路径" -ForegroundColor DarkGray
        $ok = $false
    }

    $adbExe = $null
    try { $adbExe = (Get-Command $ADB -ErrorAction Stop).Source } catch { }
    if (-not $adbExe) {
        Write-Host "✗ 找不到 adb（$ADB）——装 Android SDK，或用环境变量 MAPBOT_ADB 指定" -ForegroundColor Red
        $ok = $false
    }

    if ($ok) {
        $devs = & $adbExe devices 2>$null
        if (-not ($devs -match [regex]::Escape($DEV))) {
            Write-Host "… 设备 $DEV 未连接，尝试连接（需要 MuMu 已启动）" -ForegroundColor Yellow
            & $adbExe connect $DEV | Out-Null
            Start-Sleep -Seconds 1
            $devs = & $adbExe devices 2>$null
        }
        if (-not ($devs -match [regex]::Escape($DEV))) {
            Write-Host "✗ 连不上 MuMu（$DEV）——先把模拟器打开、游戏登录好" -ForegroundColor Red
            Write-Host "  换设备号：`$env:MAPBOT_DEV = '127.0.0.1:16416' 后再运行本脚本" -ForegroundColor DarkGray
            $ok = $false
        }
    }
    return $ok
}

function Run-Bot([int]$Maps, [switch]$Quiet) {
    if (-not (Check-Env)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $LOGDIR ("run_$stamp.log")
    if (-not (Test-Path $LOGDIR)) { New-Item -ItemType Directory -Path $LOGDIR | Out-Null }
    Write-Host ""
    Write-Host "▶ 开始跑（最多 $Maps 张图，体力不足会自己停）" -ForegroundColor Green
    Write-Host "  日志：$log" -ForegroundColor DarkGray
    Write-Host "  ⚠ 跑的时候别在模拟器里手动点，会互相打架；要停就按 Ctrl+C" -ForegroundColor DarkYellow
    Write-Host ""
    $botArgs = @('core/explore_loop.py', '--device', $DEV, '--max-round', '45',
                 '--maps', "$Maps", '--deadline', '420')
    if ($Quiet) { $botArgs += '--no-dump' }
    & $PY @botArgs 2>&1 | Tee-Object -FilePath $log
    Write-Host ""
    Write-Host "■ 结束。日志已存：$log" -ForegroundColor Green
}

function Show-Status {
    if (-not (Check-Env)) { return }
    Write-Host ""
    & $PY 'devtools/see.py' 2>&1 | Select-String -NotMatch 'DEBUG|warn|CategoryInfo|FullyQualified|^\s*\+|所在位置' |
        Select-Object -First 30
}

while ($true) {
    Clear-Host
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host "   幻想少女公会 · 自动探索（纯视觉）" -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host "  1) 连刷 20 张图（推荐：跑到体力不足自动停）"
    Write-Host "  2) 只跑 1 张图"
    Write-Host "  3) 跑 3 张图"
    Write-Host "  4) 只看一眼当前屏幕（不点击）"
    Write-Host "  5) 检查环境（模拟器 / adb / python）"
    Write-Host "  0) 退出"
    Write-Host ""
    $c = Read-Host "选择"
    switch ($c) {
        '1' { Run-Bot 20 }
        '2' { Run-Bot 1 }
        '3' { Run-Bot 3 }
        '4' { Show-Status }
        '5' { if (Check-Env) { Write-Host "✓ 环境正常" -ForegroundColor Green } }
        '0' { return }
        default { Write-Host "输入 0-5" -ForegroundColor Yellow }
    }
    Write-Host ""
    Read-Host "按回车回到菜单" | Out-Null
}
