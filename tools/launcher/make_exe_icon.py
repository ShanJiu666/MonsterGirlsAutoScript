# -*- coding: utf-8 -*-
"""make_exe_icon.py · 把官方 30×30 像素头像做成 exe 用的 .ico

为什么要多尺寸：
  Windows 在不同场合取不同尺寸的图标 ——
    · 任务栏 / 标题栏：16×16、32×32
    · 桌面大图标：48×48、256×256
    · 资源管理器「大图标」：96×96、128×128
  只放一个尺寸 ⇒ 某些地方会被系统拉伸、糊掉。

关于放大方式（重要）：
  源图是 **30×30 像素画**。放大到 256 必须用 **NEAREST（最近邻）**，
  这样才能保住像素边缘的硬朗感；
  用双线性/双三次会糊成一团（这是像素画的基本原则）。

源资产：官方图集 M31302_000 那一格（head_M31302_000.png，1947 B，30×30）
"""
import io
import os
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))       # 仓根

# 源图：优先用仓内副本；退回到安卓端的官方格
CANDIDATES = [
    os.path.join(HERE, 'head_M31302_000.png'),
    os.path.join(REPO, 'tools', 'launcher', 'head_M31302_000.png'),
    r'D:\MGAS\android_autoexplore\tools\icon\head_M31302_000.png',
    r'D:\MGAS\_icon_ref\m31302\head_M31302_000.png',
]

# .ico 里放的尺寸（覆盖任务栏 / 桌面 / 资源管理器大图标）
SIZES = (16, 24, 32, 48, 64, 128, 256)

OUT = os.path.join(HERE, 'MGAS.ico')


def find_src():
    for p in CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def png_bytes_nearest(src_img, size):
    """把源图用 NEAREST 放大/缩小到 size×size，返回 PNG 字节"""
    from PIL import Image
    im = src_img.convert('RGBA').resize((size, size), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def build_ico(src_path, out_path, sizes=SIZES):
    """写一个真正的 .ico（每个尺寸内含 PNG 数据，Vista+ 支持）"""
    from PIL import Image
    src = Image.open(src_path)
    print('源图：%s  %dx%d  模式=%s'
          % (os.path.basename(src_path), src.width, src.height, src.mode))

    entries = []          # (size, png_bytes)
    for s in sizes:
        data = png_bytes_nearest(src, s)
        entries.append((s, data))
        print('  %3d×%-3d  %5d B' % (s, s, len(data)))

    # ICONDIR: reserved(2) type(2) count(2)
    header = struct.pack('<HHH', 0, 1, len(entries))
    # ICONDIRENTRY: w(1) h(1) colors(1) reserved(1) planes(2) bpp(2)
    #               size(4) offset(4)   —— 宽高 256 记作 0
    offset = 6 + 16 * len(entries)
    dir_parts, data_parts = [], []
    for s, data in entries:
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        dir_parts.append(struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32,
                                     len(data), offset))
        data_parts.append(data)
        offset += len(data)

    blob = header + b''.join(dir_parts) + b''.join(data_parts)
    with open(out_path, 'wb') as f:
        f.write(blob)
    return len(blob)


def main():
    src = find_src()
    if not src:
        print('❌ 找不到源图 head_M31302_000.png')
        print('   候选：')
        for c in CANDIDATES:
            print('     %s%s' % (c, '' if os.path.isfile(c) else '  (缺)'))
        return 2
    try:
        n = build_ico(src, OUT)
    except ImportError:
        print('❌ 需要 Pillow（pip install pillow）')
        return 3
    print('\n✓ 已生成 %s（%.1f KB，%d 个尺寸）'
          % (OUT, n / 1024, len(SIZES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
