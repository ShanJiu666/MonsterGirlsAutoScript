# -*- coding: utf-8 -*-
"""mumu.py · 查 MuMu 模拟器的「实例名 ↔ adb 端口」映射（多开对号用）

权威来源 = MuMu 自带的命令行工具：
    '' info -v all
输出 JSON，每个实例带 `name`（你在多开器里看到的名字）、`adb_port`、`android_version`、
`is_process_started`、`index` —— 例如：
    0 → 实例A (127.0.0.1:16384, 安卓12.0, 运行中)
    1 → 实例B (127.0.0.1:16416, 安卓15.0, 运行中)

用法:
    python mumu.py                 # 列出全部实例
    python mumu.py --device 127.0.0.1:16416    # 只查这个设备对应哪个实例
"""
import argparse
import glob
import json
import os
import subprocess
import sys



# ⚠ 只在命令行跑时才包 stdout —— GUI 是 pythonw，`sys.stdout is None`，
#   在 import 时就 `sys.stdout.buffer` 会直接 AttributeError（2026-09-25 踩过）
if __name__ == '__main__' and sys.stdout is not None:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CNW = 0x08000000 if os.name == 'nt' else 0
_cache = {}


def _candidates():
    """MuMuManager.exe 的候选路径（⭐ 2026-10-02 收敛到 `paths.py`）

    原来这里**自己维护一份**安装目录候选表 + 自己跑一次 PowerShell 反推进程路径，
    和 `paths.py` 里的 `_mumu_homes()` / `find_mumu_manager()` 是**同一套逻辑的两份拷贝**
    ⇒ 朋友装在 D 盘/F 盘时，两边可能给出不同答案。现在统一走 paths，
    本函数只负责把「安装根目录」翻译成「可执行文件路径」。
    """
    import paths as P
    return [os.path.join(h, 'nx_main', 'MuMuManager.exe') for h in P._mumu_homes()]


def manager_path():
    if 'mgr' in _cache:
        return _cache['mgr']
    found = None
    for p in _candidates():
        if os.path.exists(p):
            found = p
            break
    if not found:       # 兜底：浅层扫一遍常见盘根目录
        for pat in ('?:\\MuMu Player 12\\nx_main\\MuMuManager.exe',
                    '?:\\*MuMu*\\nx_main\\MuMuManager.exe',
                    '?:\\Program Files\\*MuMu*\\nx_main\\MuMuManager.exe'):
            hits = glob.glob(pat)
            if hits:
                found = hits[0]
                break
    _cache['mgr'] = found
    return found


def instances():
    """-> {port(int): {'name','android','running','index'}}；查不到返回 {}"""
    if 'inst' in _cache:
        return _cache['inst']
    mgr = manager_path()
    res = {}
    if mgr:
        try:
            r = subprocess.run([mgr, 'info', '-v', 'all'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=30,
                               creationflags=CNW)
            txt = (r.stdout or '').strip()
            i = txt.find('{')
            if i >= 0:
                data = json.loads(txt[i:])
                for _k, v in (data or {}).items():
                    port = v.get('adb_port')
                    if not port:
                        continue
                    res[int(port)] = {
                        'name': v.get('name') or ('实例%s' % v.get('index')),
                        'android': v.get('android_version') or '',
                        'running': bool(v.get('is_process_started')),
                        'index': str(v.get('index')),
                    }
        except Exception:       # noqa: BLE001
            pass
    _cache['inst'] = res
    return res


def name_for(device):
    """'127.0.0.1:16416' -> '实例B（安卓15.0，运行中）'；查不到返回 ''"""
    try:
        port = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        return ''
    info = instances().get(port)
    if not info:
        return ''
    tail = []
    if info.get('android'):
        tail.append('安卓%s' % info['android'])
    tail.append('运行中' if info.get('running') else '未启动')
    return '%s（%s）' % (info['name'], '，'.join(tail))


def label_for(device):
    n = name_for(device)
    return ('MuMu「%s」 · %s' % (n, device)) if n else ('%s（未能识别 MuMu 实例名）' % device)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--device', default=None)
    a = ap.parse_args()
    if a.device:
        print(label_for(a.device))
        return
    mgr = manager_path()
    print('MuMuManager: %s' % (mgr or '未找到'))
    for port, v in sorted(instances().items()):
        print('  实例%-3s %-10s 127.0.0.1:%-6d 安卓%-5s %s'
              % (v['index'], v['name'], port, v['android'],
                 '运行中' if v['running'] else '未启动'))


if __name__ == '__main__':
    main()
