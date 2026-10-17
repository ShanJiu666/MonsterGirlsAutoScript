# -*- coding: utf-8 -*-
"""auto_collect_until.py · 「采图 → 入库」自动流水线：一直跑到数据集够大为止

用户 2026-09-27：「实例B模拟器可以随便用体力，直到采集够你需要的图的足够数量」

一轮 = ① `run_collect.py --maps N`（进图→存首帧→退图）② `frames_to_dataset.py`（增量入库）
循环直到「数据集条数 ≥ --target」或「体力耗尽（连续 2 轮 0 新增）」或「超时」。

⚠ 开跑前会**等设备锁空出来**（同设备已有循环在跑时会拒绝启动，这里先等它结束）
⚠ 体力约束交给 `run_collect.py --min-stamina 25`（进图费就是 25）⇒ 体力见底自动收工

用法：
    python auto_collect_until.py                          # 实例B 16416 / tag=acc2 / 目标 130 张
    python auto_collect_until.py --target 120 --batch 15
    python auto_collect_until.py --device 127.0.0.1:16384 --tag ""   # 换成主号
"""
import argparse
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)
import loopguard as LG                       # noqa: E402


PY = sys.executable
DS = os.path.join(HERE, 'runs', 'boards_dataset.jsonl')
COLLECT = os.path.join(ROOT, 'devtools', 'run_collect.py')
EXTRACT = os.path.join(ROOT, 'devtools', 'ingest_parallel.py')      # ⭐ 分片并行版（串行要 46~48 秒/张）
DEDUPE = os.path.join(ROOT, 'devtools', 'dedupe_dataset.py')
SHARDS = 3


def say(m=''):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), m), flush=True)


def ds_count():
    if not os.path.exists(DS):
        return 0
    with open(DS, encoding='utf-8') as f:
        return sum(1 for ln in f if ln.strip())


def shots_in(tag):
    import glob
    d = os.path.join(HERE, 'runs', tag) if tag else os.path.join(HERE, 'runs')
    return len(glob.glob(os.path.join(d, 'r_*_0.png')))


def dev_busy(device):
    """这台设备上有没有别的 explore_loop 在跑（有 ⇒ 等它，别抢点击）

    ⚠ 不要用 `loopguard.duplicates_for(device)`：它按 **(device, tag) 两个键**过滤，
      tag 传空只会匹配「无 tag」的循环 ⇒ **漏掉 acc2 那种带 tag 的** ✗
      这里直接 `list_loops()` 按**设备**筛（设备锁本来就是按设备一把的 ✓）
    """
    try:
        return [p for p in LG.list_loops() if p.get('device') == device]
    except Exception:               # noqa: BLE001
        return []


def wait_free(device, max_wait=1800, every=30):
    t0 = time.time()
    while dev_busy(device):
        if time.time() - t0 > max_wait:
            say('⚠ 等了 %.0f 秒设备还是被占着（%s）⇒ 放弃等待' % (max_wait, device))
            return False
        say('… %s 上已有循环在跑，等它结束（已等 %.0f 秒）' % (device, time.time() - t0))
        time.sleep(every)
    return True


def run(cmd, label):
    say('▶ %s：%s' % (label, ' '.join(cmd[1:])))
    t0 = time.time()
    rc = subprocess.call([PY] + cmd, cwd=HERE)
    say('◀ %s 结束（退出码 %s，耗时 %.0f 秒）' % (label, rc, time.time() - t0))
    return rc


def main():
    ap = argparse.ArgumentParser(description='采图 → 入库 自动流水线')
    ap.add_argument('--device', default='127.0.0.1:16416')
    ap.add_argument('--tag', default='acc2')
    ap.add_argument('--target', type=int, default=130, help='数据集目标条数（默认 130）')
    ap.add_argument('--batch', type=int, default=20, help='每轮采几张（默认 20）')
    ap.add_argument('--min-stamina', type=int, default=25)
    ap.add_argument('--auto-supply', action='store_true',
                    help='体力见底时自动吃「结实补给」(每个 +500)，用完为止（实例B已授权 ✓）')
    ap.add_argument('--max-hours', type=float, default=4.0)
    ap.add_argument('--no-wait', action='store_true', help='不等待设备锁（--force 交给下层）')
    a = ap.parse_args()

    dev, tag = a.device, a.tag
    say('═' * 62)
    say('采图流水线：%s（tag=%s）目标 %d 条 · 每轮 %d 张 · 上限 %.1f 小时'
        % (dev, tag or '（空）', a.target, a.batch, a.max_hours))
    say('每张图 **25 体力**（进图瞬间扣、退图不退）⇒ 体力 <25 时自动收工')
    say('自动补给：%s' % ('✓ 开（体力见底自动吃「结实补给」+500，查到没有才收工）'
                          if a.auto_supply else '✗ 关（体力见底即收工）'))
    say('═' * 62)

    t_all = time.time()
    empty_streak = 0
    rnd = 0
    while True:
        rnd += 1
        n0 = ds_count()
        if n0 >= a.target:
            say('✅ 数据集已 %d 条 ≥ 目标 %d ⇒ 收工' % (n0, a.target))
            break
        if (time.time() - t_all) / 3600.0 > a.max_hours:
            say('⏰ 已跑满 %.1f 小时 ⇒ 收工' % a.max_hours)
            break
        if not a.no_wait and not wait_free(dev):
            break
        say('── 第 %d 轮（数据集 %d 条，目标 %d，实例B首帧 %d 张）──'
            % (rnd, n0, a.target, shots_in(tag)))
        run(['run_collect.py', '--maps', str(a.batch), '--device', dev,
             '--min-stamina', str(a.min_stamina)]
            + (['--auto-supply'] if a.auto_supply else [])
            + (['--tag', tag] if tag else []),
            '采图 %d 张' % a.batch)
        # ⭐ 入库：先自检重复（防"两次跑同一份待办"把 n 灌水 ✗），再分片并行
        run(['dedupe_dataset.py'], '去重自检')
        run(['ingest_parallel.py',
             os.path.join(HERE, 'runs', tag) if tag else os.path.join(HERE, 'runs'),
             os.path.join(HERE, 'runs'), '--shards', str(SHARDS)],
            '增量入库（%d 分片并行）' % SHARDS)
        n1 = ds_count()
        say('本轮入库 +%d（数据集 %d 条）' % (n1 - n0, n1))
        if n1 == n0:
            empty_streak += 1
            say('⚠ 本轮 0 新增（第 %d 次）' % empty_streak)
            if empty_streak >= 2:
                say('⇒ 连续 0 新增，判定体力耗尽 / 进图失败 ⇒ 收工')
                break
        else:
            empty_streak = 0
    say('')
    say('═' * 62)
    say('流水线结束：数据集 %d 条（本次跑了 %d 轮，共 %.1f 分钟）'
        % (ds_count(), rnd, (time.time() - t_all) / 60.0))
    say('═' * 62)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n⏹ 已中断')
        sys.exit(130)
