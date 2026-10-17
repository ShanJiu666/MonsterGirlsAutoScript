@echo off
REM ===========================================================================
REM  MGAS launcher -- build_pkg copies this to the package root as Start.bat
REM
REM  EVERY RULE BELOW COST A DEBUGGING ROUND (2026-10-03). Do not "simplify":
REM
REM  1) THIS FILE MUST STAY **PURE ASCII**.
REM     cmd parses .bat with the console ANSI codepage. A UTF-8 .bat, an
REM     LF-only .bat, or any character GBK cannot represent splits lines and
REM     silently kills the commands below it (symptom: double-click does
REM     nothing, or a garbled "not recognized as an internal command").
REM
REM  2) NEVER write venv\pyvenv.cfg with `echo` here.
REM     cmd writes files in the **system ANSI codepage** (GBK on zh-CN), but
REM     Python 3.11 **reads pyvenv.cfg as UTF-8**. A path containing Chinese
REM     therefore becomes '????' and the venv dies with
REM         No Python at 'C:\...\????\python311\python.exe'   (exit code 103)
REM     `chcp 65001` is NOT a fix either: on a double-click cmd still uses the
REM     system ACP (verified). Instead we call fix_venv_cfg.py with the **base**
REM     interpreter python311\python.exe -- a standalone interpreter that does
REM     not read pyvenv.cfg, so it always starts and writes proper UTF-8.
REM
REM  3) Keep the written file GBK + CRLF (build_pkg does); pure ASCII means the
REM     bytes are identical either way, and CRLF keeps cmd happy.
REM
REM  4) Also: do NOT put `chcp 65001` here -- it would garble the file's own
REM     Chinese echoes (if any were ever added back) on a GBK console.
REM ===========================================================================
REM The Chinese startup banner is printed by fix_venv_cfg.py (this file must stay pure ASCII)
"%~dp0python311\python.exe" "%~dp0fix_venv_cfg.py"
cd /d "%~dp0mapbot_pc"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0bootstrap.py"
timeout /t 3 >nul
exit
