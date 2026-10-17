# -*- coding: utf-8 -*-
"""whoami_bot.py · 「这个窗口绑的是哪个号？」——抓图 + 读 HUD + 存缩略图

用法: python whoami_bot.py --device 127.0.0.1:16416 --tag acc2
输出一行身份信息（GUI 读这行显示），并把缩略图存到 runs/<tag>/whoami.png

做法：截图后 OCR 顶部区域（PID / 金币 / 体力都在顶部 HUD），再用 PIL 缩一张小图
给 GUI 弹出来 —— 你对着两个 MuMu 窗口一眼就能认出哪个是哪个号。
"""
import argparse
import io
import os
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


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, ROOT)   # 仓根（原为脚本自身目录）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--device', default=None)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    tag = (a.tag or '').strip()
    from mapbot import Bot, DEV
    b = Bot(log_prefix='whoami', serial=a.device or DEV, tag=tag or None)
    p = b.snap('whoami')
    items = b.ocr(min_conf=0.4, band=(0, 320))

    def find(*keys):
        for it in items:
            t = it['text'].replace(' ', '')
            if any(k in t for k in keys):
                return t
        return ''

    pid = find('PID')
    gold = ''
    stam = ''
    for it in items:
        t = it['text'].replace(' ', '').replace(',', '')
        if t.isdigit() and len(t) >= 6 and not gold:
            gold = t
        if '/' in t and not stam:
            stam = t
    # 缩略图（给 GUI 弹窗看）
    try:
        from PIL import Image
        im = Image.open(p)
        im.thumbnail((330, 590))
        thumb = os.path.join(b.runs, 'whoami.png')
        im.save(thumb)
    except Exception:       # noqa: BLE001
        thumb = p
    msg = ('设备 %s｜实例 %s｜%s｜金币 %s｜体力 %s'
           % (b.dev, tag or '单开', pid or 'PID ?', gold or '?', stam or '?'))
    print(msg)
    print('SHOT=%s' % thumb)


if __name__ == '__main__':
    main()
