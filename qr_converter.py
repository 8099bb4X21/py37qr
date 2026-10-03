#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 转换模块: 文字 -> 单码(短) 或 喷泉轮播流(长)。

运行环境: Python3.7+，依赖 segno(纯 Python) + Pillow(渲染)。
编码用 segno，长文切块用 fountain.py 的 LT 喷泉码 + 文本帧协议。

使用方法:
    stream = EncodedStream(text, error_name="M", block_len=200)
    stream.single          # True=单码, False=喷泉轮播
    stream.frame_text(i)   # 第 i 帧的文本(单码=原文, 喷泉=PYQRF1 头帧)
    stream.render_frames(box_size, border)  # 预渲染所有帧的 PIL 图列表
"""

import os

import segno
from segno import DataOverflowError

from PIL import Image
from PIL import ImageOps

import fountain


ERROR_LEVELS = ("L", "M", "Q", "H")


def get_error_correction(error_name):
    # 校验并归一化纠错等级，非法输入抛 ValueError。
    key = str(error_name).strip().upper()
    if key not in ERROR_LEVELS:
        raise ValueError("纠错等级只支持 L/M/Q/H，当前是: " + str(error_name))
    return key


def try_encode(text_chunk, error_name):
    # 只编码不渲染；装不下抛 ValueError。返回 segno.QRCode。
    if text_chunk is None or text_chunk == "":
        raise ValueError("输入文字为空，无法生成二维码")
    level = get_error_correction(error_name)
    try:
        # mask=4 固定掩模，跳过 segno 的 8 种掩模寻优评估，编码提速约 4 倍
        # (同 decimen 的 PINNED_MASK_PATTERN，轮播要快这点很关键)。
        qr = segno.make_qr(text_chunk, error=level.lower(), boost_error=False, mask=4)
    except DataOverflowError as exc:
        raise ValueError("单个二维码装不下: " + str(exc))
    return qr


def render_qr_image(qr, box_size, border):
    # segno 矩阵 -> PIL RGB 图。参数释义见下。
    side = len(qr.matrix)
    small = Image.new("1", (side, side), 1)
    pixels = small.load()
    for row_idx, row in enumerate(qr.matrix):
        for col_idx, dark in enumerate(row):
            if dark:
                pixels[col_idx, row_idx] = 0
    if border > 0:
        small = ImageOps.expand(small, border=int(border), fill=1)
    total = side + int(border) * 2
    big = small.resize((total * int(box_size), total * int(box_size)), Image.NEAREST)
    return big.convert("RGB")


def build_qr_image(text, box_size, border, error_name):
    # 一段文字 -> 一张二维码 PIL 图。
    qr = try_encode(text, error_name)
    return render_qr_image(qr, box_size, border)


class EncodedStream:
    # 文字 -> 单码(1 帧) 或 喷泉轮播(2k 帧)。GUI 轮播源。

    def __init__(self, text, error_name="M", block_len=200):
        # 判定单码/轮播：纯文本能否塞进一个 QR，能则静止，否则喷泉切片。
        self.error_name = get_error_correction(error_name)
        self.text = text
        payload = text.encode("utf-8")
        try:
            try_encode(text, self.error_name)
            self.single = True
        except ValueError:
            self.single = False
        if self.single:
            self.encoder = None
            self.k = 1
        else:
            self.encoder = fountain.FountainEncoder(payload, block_len=block_len)
            self.k = self.encoder.k

    def frame_count(self):
        # 轮播帧数：单码 1，喷泉一整个 carousel 2k。
        if self.single:
            return 1
        return fountain.cycle_length(self.k)

    def frame_text(self, seq):
        # 第 seq 帧文本；单码返回原文，喷泉返回 PYQRF1 头帧。
        if self.single:
            return self.text
        return self.encoder.frame_text(seq)


def save_qr_images(images, base_path):
    # 单张直接存，多张加 _N 后缀。返回已写文件路径列表。
    if not images:
        raise ValueError("images 为空，没有可保存的内容")
    root = str(base_path).strip()
    if root == "":
        raise ValueError("保存路径为空")
    stem = root
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    parent = os.path.dirname(os.path.abspath(stem))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    saved = []
    if len(images) == 1:
        out = stem + ".png"
        images[0].save(out, format="PNG")
        saved.append(out)
    else:
        for idx, img in enumerate(images, start=1):
            out = stem + "_" + str(idx) + ".png"
            img.save(out, format="PNG")
            saved.append(out)
    return saved


def main():
    # 命令行自测：单码 + 喷泉轮播各走一遍。
    print("[INFO] 自测开始")
    short_stream = EncodedStream("你好 QR", error_name="M")
    assert short_stream.single and short_stream.frame_count() == 1
    print("[PASS] 短文字判定为单码")
    long_text = "长文测试" * 400
    long_stream = EncodedStream(long_text, error_name="M", block_len=80)
    assert (not long_stream.single) and long_stream.frame_count() == 2 * long_stream.k
    print("[PASS] 长文字判定为喷泉轮播, k=" + str(long_stream.k))
    img = build_qr_image(long_stream.frame_text(0), 10, 4, "M")
    print("[PASS] 渲染单帧成功, 尺寸=" + str(img.size))
    # 用 fountain 端到端再验：渲染出的帧文本能被 FountainDecoder 还原。
    dec = fountain.FountainDecoder(
        long_stream.encoder.k,
        long_stream.encoder.block_len,
        long_stream.encoder.session_id,
        long_stream.encoder.total_len,
        long_stream.encoder.payload_fnv,
    )
    for i in range(fountain.cycle_length(long_stream.k)):
        parsed = fountain.parse_frame_text(long_stream.frame_text(i))
        dec.add_frame(parsed["seq"], parsed["block"])
    assert dec.assemble() == long_text.encode("utf-8")
    print("[PASS] 喷泉轮播帧可完整还原原文")
    print("[INFO] 自测完毕")


if __name__ == "__main__":
    import sys

    try:
        main()
    except Exception as e:
        print("[FAIL] 自测异常: " + str(e))
        raise
    finally:
        if sys.stdin.isatty():
            print("\n按任意键退出...", end="", flush=True)
            try:
                if sys.platform.startswith("win"):
                    import msvcrt

                    msvcrt.getch()
                else:
                    import termios
                    import tty

                    fd = sys.stdin.fileno()
                    old = termios.tcgetattr(fd)
                    try:
                        tty.setraw(fd)
                        sys.stdin.read(1)
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass
            print("")