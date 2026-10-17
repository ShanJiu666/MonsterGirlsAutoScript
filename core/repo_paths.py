# -*- coding: utf-8 -*-
"""repo_paths.py · 离线游戏素材路径解析

作用
----
本仓有一批**离线工具**（制表、导图、回归取证）需要读游戏素材（数据表等）。
这些素材**不在仓里**，本模块负责把它们解析成一个明确的路径。

解析顺序（每个素材都一样）
-------------------------
    ① 环境变量（用户显式指定，最高优先）
    ② 仓内自备副本（`<仓根>/data/...`）—— 把素材放进仓内即可，推荐
    ③ 仓根直读（`<仓根>/server_datatable.json` 等常见落点）
    ④ None（由调用方 `require()` 报明确错误，绝不静默走空）

⚠ 与 `paths.py` 的分工：`paths.py` 管**运行期**（adb / MuMu / 模拟器进程）
  和仓内相对路径；本模块只管**离线游戏素材**。
  刻意**不 import paths**：那几个离线工具不必为一次 adb 探测付代价。

用法
----
    python repo_paths.py        # 体检：逐项打印解析结果与缺失项
"""
from __future__ import annotations

import os

# ⚠ 本文件住在 `core/` 里：仓根 = 上一级目录。
#   `sys.path` 仍要 `core/`（兄弟模块在这儿），但 `templates/` `runs/` `data/`
#   这些资源都相对**仓根** ⇒ 必须多上一级，否则全读不到。
_MGAS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, 'data')          # 仓内自备素材目录（可选）
SHARED = DATA                              # 兼容别名（旧调用方用这个名字）


def _first(paths):
    """返回第一个存在的路径（None 跳过）"""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _local(*parts):
    """仓内候选：data/ 下、以及仓根直读两种落点"""
    return os.path.join(DATA, *parts), os.path.join(HERE, *parts)


# ══════════════════════════════════════════════════════════════════════
# ① 数据表
# ══════════════════════════════════════════════════════════════════════
# 主数据表（`server_datatable.json`；本仓根目录自带一份）
DATATABLE = _first([
    os.environ.get('MGAS_DATATABLE'),
    *_local('server_datatable.json'),
])


# ══════════════════════════════════════════════════════════════════════
# ② 取用入口
# ══════════════════════════════════════════════════════════════════════
def require(path, what):
    """拿一个**必须有**的素材；没有就报明确错误（不要静默走空）"""
    if not path:
        raise SystemExit(
            '× 找不到%s。\n'
            '  已尝试：环境变量 → %s\n'
            '  修法：设对应环境变量，或把素材拷进 %s'
            % (what, DATA, DATA))
    return path


def describe():
    """-> [(名, 路径或 None)]：体检/排障用"""
    return [
        ('数据表', DATATABLE),
    ]


if __name__ == '__main__':
    import io
    import sys
    if sys.stdout is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    print('=' * 72)
    print('repo_paths.py · 离线素材解析')
    print('=' * 72)
    print('  仓根     : %s' % HERE)
    print('  自备目录 : %s' % DATA)
    print()
    miss = 0
    for name, p in describe():
        if p:
            print('  [ok]   %-16s %s' % (name, p))
        else:
            print('  [MISS] %-16s —' % name)
            miss += 1
    print()
    print('缺失 %d 项（缺的只影响对应离线工具，不影响自动探图主流程）' % miss)
    raise SystemExit(0)
