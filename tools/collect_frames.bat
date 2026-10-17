@echo off
chcp 65001 >nul
rem ⚠ 本脚本在 tools\ 里（2026-10-17 目录整理）：仓根 = 上一级
cd /d "%~dp0.."
rem 用 PATH 里的 python；也可先 set MAPBOT_PY=<python.exe 绝对路径> 覆盖
if defined MAPBOT_PY (
  "%MAPBOT_PY%" devtools\run_collect.py %*
) else (
  python devtools\run_collect.py %*
)
echo.
pause
