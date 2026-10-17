# -*- coding: utf-8 -*-
"""发布包完整性体检：把「运行时会 import 但包里没有」的东西全找出来。

触发背景（用户实报）：
  桌面解压后双击 MGAS.exe 失败，日志两条：
    ① `ModuleNotFoundError: No module named 'pywin32_bootstrap'`
       ← `pywin32.pth` 第 7 行 `import pywin32_bootstrap`，而该 .py **没进包**
    ② `ModuleNotFoundError: No module named 'tkinter'`
       ← 这条是**解压未完成**时双击的产物（包内 tcl/tk/_tkinter.pyd 齐全，
         解压完整后直接 import 成功）⇒ 需要在用户侧给出更明确的提示

本脚本检查：
  A. 包内每个 `.pth` 引用的顶层模块是否真的存在
  B. 核心依赖能否 import（tkinter / pywin32 / cv2 / numpy / onnxruntime / maa）
  C. `sys.path` 里有没有指向包外的条目（搬家后会断）
"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 默认包路径**从本文件位置推**（别写死本机路径 —— AGENTS.md 里反复踩的坑）
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
PKG = (sys.argv[1] if len(sys.argv) > 1
       else os.path.join(_REPO, 'dist', 'MGAS-v1.0-portable'))
PY = os.path.join(PKG, 'python311', 'python.exe')
SP = os.path.join(PKG, 'python311', 'Lib', 'site-packages')
fails = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  · ' + str(detail)) if detail else ''))
    if not cond:
        fails.append(name)


print('=' * 72)
print('A. .pth 引用的模块是否都在包里')
print('=' * 72)
# .pth 里可能是「目录」也可能是「import 语句」
for f in sorted(os.listdir(SP)) if os.path.isdir(SP) else []:
    if not f.endswith('.pth'):
        continue
    p = os.path.join(SP, f)
    for line in io.open(p, encoding='utf-8', errors='replace').read().splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = re.match(r'^(?:import\s+)?([A-Za-z_]\w*)$', s)
        if m:
            name = m.group(1)
            # ⚠ 查找范围要**包含 site-packages 下的子目录**（按 .pth 逐个加进来的）
            #   典型坑：`pywin32_bootstrap.py` 在 `win32/lib/` 里，
            #   而 `pywin32.pth` 是先把 `win32`、`win32\lib` 加进 sys.path、
            #   **最后**才 `import pywin32_bootstrap` ⇒ 它在**那个子目录**能被找到。
            #   只查 site-packages 顶层会误报成"缺失"。
            ok = (os.path.isdir(os.path.join(SP, name))
                  or os.path.isfile(os.path.join(SP, name + '.py')))
            if not ok:
                for sub in ('win32', 'win32/lib', 'pythonwin', 'win32com'):
                    d2 = os.path.join(SP, *sub.split('/'))
                    if (os.path.isfile(os.path.join(d2, name + '.py'))
                            or os.path.isdir(os.path.join(d2, name))):
                        ok = True
                        break
            if not ok:
                ck('%s → %s' % (f, name), False,
                   '目录/模块都不存在（pth 会让每次启动报错）')
            else:
                print('  [ok]   %s → %s' % (f, name))
        elif s.startswith('import '):
            for mod in re.findall(r'[A-Za-z_]\w*', s[7:]):
                ok = (os.path.isdir(os.path.join(SP, mod))
                      or os.path.isfile(os.path.join(SP, mod + '.py')))
                ck('%s → import %s' % (f, mod), ok,
                   '' if ok else '模块不存在（pth 会让每次启动报错）')

print()
print('=' * 72)
print('B. 核心模块能否 import（用包内 python311）')
print('=' * 72)
probe = r'''
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
out = {}
for m in ("tkinter", "win32api", "win32gui", "cv2", "numpy",
          "onnxruntime", "rapidocr_onnxruntime", "customtkinter",
          "airtest", "docx", "maa"):
    try:
        __import__(m); out[m] = "ok"
    except BaseException as e:
        out[m] = "ERR:%s:%s" % (type(e).__name__, str(e)[:70])
out["_path"] = [p for p in sys.path if p]
sys.stdout.write("__JSON__" + json.dumps(out, ensure_ascii=False))
'''
r = subprocess.run([PY, '-c', probe], cwd=PKG, capture_output=True, timeout=300)
txt = ((r.stdout or b'').decode('utf-8', 'replace')
       + (r.stderr or b'').decode('utf-8', 'replace'))
m = re.search(r'__JSON__(.*)', txt, re.S)
if not m:
    print('  ❌ 探针无输出：')
    print(txt[-1500:])
    fails.append('probe')
else:
    import json
    d = json.loads(m.group(1).splitlines()[0])
    for k in ('tkinter', 'win32api', 'win32gui', 'cv2', 'numpy', 'onnxruntime',
              'rapidocr_onnxruntime', 'customtkinter', 'airtest', 'maa'):
        ck(k, str(d.get(k)) == 'ok', d.get(k))
    # C. sys.path 有没有指向包外
    print()
    print('=' * 72)
    print('C. sys.path 是否有指向包外的条目（搬家会断）')
    print('=' * 72)
    outside = []
    for p in d.get('_path') or []:
        if not os.path.normcase(p).startswith(os.path.normcase(PKG)):
            outside.append(p)
    for p in outside:
        print('     ' + p)
    ck('sys.path 全在包内', not outside, '%d 条在外' % len(outside))

print()
print('=' * 72)
print('失败 %d 项 %s' % (len(fails), '✅ 全部通过' if not fails else ''))
for f in fails:
    print('   ✗ ' + f)
print('=' * 72)
