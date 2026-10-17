# -*- coding: utf-8 -*-
"""spec_dev.py · 真机小工具：**截图 / 点击 / 找特殊地块**（只做这几件事）

设计原则（照本项目口径）：
  · **不猜坐标**：每个动作要么用 `fixed.py` 的实测锚点，要么由调用方显式给坐标
  · **每次动作前自动留证**：`shots/<tag>_<序号>.png`
  · **不自动连点**：一次调用只点一下，调用方自己决定下一步（便于用户确认）
  · 只用 adb（`-P 5038 -s 127.0.0.1:16448`），不走 airtest ⇒ 启动快、不弹窗

用法：
    python spec_dev.py shot  <tag>                 # 截图
    python spec_dev.py tap   <x> <y> <tag>         # 点一下（自动等 1.2s）
    python spec_dev.py key   back                  # 返回键
    python spec_dev.py find  <地图码> [tag]         # 截图 + 找特殊地块（不点击）
"""
from __future__ import annotations

import io
import json
import os
import subprocess
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

import cv2
import numpy as np


os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ADB = ''
PORT = '5038'
DEV = '127.0.0.1:16448'
SHOTS = os.path.join('runs', 'spec_dev')
os.makedirs(SHOTS, exist_ok=True)
CNW = 0x08000000

SPEC_ALL = {2: '商人/宝箱怪', 3: '勇者之墓', 4: '传承祭坛', 5: '限时礼包',
            6: '献祭宝箱怪', 7: '预言石碑', 9: '黄金宝库'}
SPEC_DO = (2, 3, 4, 5, 7, 9)


def _adb(*args, t=25, binary=False):
    """跑一条 adb 命令

    ⚠⚠ `binary=True` 时**绝不能带 `text=True`** —— 那会把 PNG 当文本用 utf-8 解码
      ⇒ 数据被破坏 ⇒ `imdecode` 返回 None ⇒ **静默没写出文件** ✗
      （我第一版就栽在这：命令"成功"了，但 `runs/spec_dev/` 里什么都没有 ✓）
    """
    return subprocess.run([ADB, '-P', PORT, '-s', DEV] + list(args),
                          capture_output=True,
                          text=(not binary),
                          encoding=None if binary else 'utf-8',
                          errors=None if binary else 'replace',
                          timeout=t, creationflags=CNW)


def adb_ok():
    """设备在不在（避免命令挂住）"""
    try:
        o = _adb('get-state', t=8).stdout
        o = o.decode('utf-8', 'replace').strip() if isinstance(o, bytes) else o.strip()
        return o == 'device', o
    except Exception as e:      # noqa: BLE001
        return False, repr(e)


def shot(tag='shot', save=True):
    """截一帧（**按字节**取 PNG，不经过文本解码）"""
    img = None
    try:
        p = _adb('exec-out', 'screencap', '-p', t=25, binary=True)
        raw = p.stdout or b''
        if raw[:8] == b'\x89PNG\r\n\x1a\n':
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except Exception:           # noqa: BLE001
        img = None
    if img is None:
        # 兜底：让 adb 直接写文件（PowerShell 重定向那条路已验证可行）
        tmp = os.path.join(SHOTS, '_tmp_raw.png')
        try:
            with open(tmp, 'wb') as f:
                subprocess.run([ADB, '-P', PORT, '-s', DEV, 'exec-out',
                                'screencap', '-p'],
                               stdout=f, timeout=25, creationflags=CNW)
            img = cv2.imdecode(np.fromfile(tmp, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:       # noqa: BLE001
            img = None
    if img is not None and save:
        ok = cv2.imwrite(os.path.join(SHOTS, '%s.png' % tag), img)
        if not ok:
            print('  ⚠ 写 %s.png 失败' % tag)
    return img


def tap(x, y, tag='tap', wait=1.2):
    _adb('shell', 'input', 'tap', str(int(x)), str(int(y)), t=12)
    time.sleep(wait)
    return shot(tag, save=True)


def key(name='back'):
    _adb('shell', 'input', 'keyevent', 'KEYCODE_%s' % name.upper(), t=12)
    time.sleep(1.0)


def find(code, tag='find'):
    """截图 + 找特殊地块（**只读**）"""
    import spots as SP
    img = shot(tag, save=True)
    if img is None or img.shape[:2] != (1280, 720):
        print('  ✗ 帧不对：%s' % (None if img is None else img.shape))
        return None, []
    bd = SP.Board(code)
    st = bd.state(img)
    rows = SP.spot_rows() or {}
    px = float(SP.GRID['cx'])
    x0, y0 = float(SP.GRID['x0']), float(SP.GRID['y0'])
    out = []
    for (r, c), v in sorted(st.items()):
        sid = str(v.get('sid') or '')
        sp = int(((rows.get(sid) or {}).get('SpecialSpot')) or 0)
        if not sp:
            continue
        out.append({
            'cell': '%d,%d' % (r, c),
            'tap_xy': [int(x0 + (c - 1) * px + px / 2),
                       int(y0 + (r - 1) * px + px / 2)],
            'sp': sp, 'meaning': SPEC_ALL.get(sp, ''),
            'name': v.get('name'), 'score': round(float(v.get('score') or 0), 3),
            'in_scope': sp in SPEC_DO,
            'revealed': bool(v.get('revealed')),
        })
    print('  帧 %s ｜ 特殊格 **%d** 个' % (tag, len(out)))
    for x in out:
        print('     %-5s SP=%-2s %-10s 分=%-6s 点击=%s 已揭示=%s %s'
              % (x['cell'], x['sp'], x['name'], x['score'], x['tap_xy'],
                 x['revealed'], '' if x['in_scope'] else '⛔不做'))
    return img, out


def main():
    ok, st = adb_ok()
    print('设备 %s ⇒ %s' % (DEV, st))
    if not ok:
        print('  ⚠ 设备不可用；先确认模拟器开着、且 `adb -P %s connect %s` 成功' % (PORT, DEV))
        return 1
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == 'shot':
        tag = sys.argv[2] if len(sys.argv) > 2 else 'shot'
        img = shot(tag, save=True)
        print('  -> %s' % os.path.join(SHOTS, tag + '.png'))
    elif cmd == 'tap':
        x, y, tag = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        img = tap(x, y, tag)
        print('  点了 (%d,%d) -> %s' % (x, y, os.path.join(SHOTS, tag + '.png')))
    elif cmd == 'key':
        key(sys.argv[2] if len(sys.argv) > 2 else 'back')
        print('  按了返回键')
    elif cmd == 'find':
        find(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'find')
    else:
        print(__doc__)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
