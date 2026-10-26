#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 转换模块: 文字 -> 单码(短) 或 喷泉轮播流(长)。

运行环境: Python3.7+，依赖 segno(纯 Python) + Pillow(渲染)。
编码用 segno，长文先 gzip 择优压缩再用 fountain.py 的 LT 喷泉码 + 文本帧协议切片。

使用方法:
    stream = EncodedStream(text, error_name="M", block_len=200)
    stream.single          # True=单码, False=喷泉轮播
    stream.compressed      # 喷泉载荷是否 gzip 过（单码恒 False）
    stream.frame_text(i)   # 第 i 帧文本(单码=原文, 喷泉=PYQRF1/PYQRF2 头帧)
    build_qr_image(...)    # 文本 -> PIL 图(调用方可按需逐帧渲染)
    save_qr_stream(...)    # 整流出图落盘(单码 1 张, 喷泉 k 张, 逐帧写不攒内存)
"""

import os

import segno
from segno import DataOverflowError

from PIL import Image
from PIL import ImageOps

import fountain


ERROR_LEVELS = ("L", "M", "Q", "H")

# 单码字符数理论上限：QR 40-L 数字模式最多 7089 个字符，超过它任何模式都装不下。
# segno 在超大文本上要白跑数秒（实测 20 万字符 1.7s / 100 万字符 8.4s），
# 命中上限就直接走喷泉，别让界面卡住。
SINGLE_MAX_CHARS = 7089

# 轮播帧矩阵边长按(纠错等级,块长,静默区)缓存：界面每次预览都会查，避免重复编码。
_FRAME_MODULES_CACHE = {}


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


def fountain_frame_modules(error_name, block_len=200, border=4):
    # 轮播帧的矩阵边长 + 两侧静默区（单位=模块），给界面把短码放大到与轮播帧同一显示量级。
    # 帧文本长度只由块长、几个数字位数和 base64 决定，所以用同结构哑载荷造一帧即可定版本；
    # 结果按(等级,块长,静默区)缓存，同一次运行里只编码一次。
    level = get_error_correction(error_name)
    key = (level, int(block_len), int(border))
    cached = _FRAME_MODULES_CACHE.get(key)
    if cached is not None:
        return cached
    sample = fountain.FountainEncoder(
        b"\x00" * (int(block_len) * 3), block_len=int(block_len), session_id=1)
    modules = len(try_encode(sample.frame_text(0), level).matrix) + int(border) * 2
    _FRAME_MODULES_CACHE[key] = modules
    return modules


class EncodedStream:
    # 文字 -> 单码(1 帧) 或 喷泉轮播(2k 帧)。GUI 轮播源。
    # 单码恒为原文明文；长文才 gzip 择优压缩后再喷泉切片。

    # 帧对象缓存上限：轮播同帧反复渲染，segno 编码只做一次；
    # 超长文本帧数太多时不缓存，防矩阵对象吃内存。
    QR_CACHE_MAX_FRAMES = 256

    def __init__(self, text, error_name="M", block_len=200):
        # 判定单码/轮播：纯文本能否塞进一个 QR，能则静止，否则喷泉切片。
        if text is None or text == "":
            raise ValueError("输入文字为空，无法生成二维码")
        self.error_name = get_error_correction(error_name)
        self.text = text
        self.compressed = False
        payload = text.encode("utf-8")
        self.raw_len = len(payload)
        self.payload_len = self.raw_len
        self._qr_cache = {}
        # 字符数超过单码理论上限时不必试编码：直接按喷泉走。
        self.single = False
        if len(text) <= SINGLE_MAX_CHARS:
            try:
                try_encode(text, self.error_name)
                self.single = True
            except ValueError:
                self.single = False
        if self.single:
            self.encoder = None
            self.k = 1
        else:
            payload, self.compressed = fountain.try_gzip_compress(payload)
            self.payload_len = len(payload)
            self.encoder = fountain.FountainEncoder(
                payload, block_len=block_len, compressed=self.compressed)
            self.k = self.encoder.k

    def frame_count(self):
        # 轮播帧数：单码 1，喷泉一整个 carousel 2k。
        if self.single:
            return 1
        return fountain.cycle_length(self.k)

    def frame_text(self, seq):
        # 第 seq 帧文本；单码返回原文，喷泉返回 PYQRF1/PYQRF2 头帧。
        if self.single:
            return self.text
        return self.encoder.frame_text(seq)

    def qr_code(self, seq):
        # 第 seq 帧的 segno 对象；轮播缓存命中直接返回，不命中编码一次后存入。
        # 新 EncodedStream 自带空缓存，换文本即失效，不存在脏数据。
        cached = self._qr_cache.get(seq)
        if cached is not None:
            return cached
        qr = try_encode(self.frame_text(seq), self.error_name)
        if self.frame_count() <= self.QR_CACHE_MAX_FRAMES:
            self._qr_cache[seq] = qr
        return qr


def _png_target_paths(base_path, count):
    # 校验保存路径并生成落盘文件名：单张不加后缀，多张加 _1.._count。
    root = str(base_path).strip()
    if root == "":
        raise ValueError("保存路径为空")
    stem = root[:-4] if root.lower().endswith(".png") else root
    parent = os.path.dirname(os.path.abspath(stem))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if count == 1:
        return [stem + ".png"]
    paths = []
    for idx in range(1, count + 1):
        paths.append(stem + "_" + str(idx) + ".png")
    return paths


def save_qr_stream(stream, box_size, border, base_path):
    # 把整个流逐帧渲染落盘：单码 1 张，喷泉 k 张系统帧(seq 0..k-1)。
    # 逐帧写盘而不是先攒一个 images 列表：大 k 时 k 张图同时留在内存会直接 OOM。
    # 返回已写文件路径列表。
    count = 1 if stream.single else stream.k
    paths = _png_target_paths(base_path, count)
    for seq, out in enumerate(paths):
        img = render_qr_image(stream.qr_code(seq), box_size, border)
        img.save(out, format="PNG")
        del img
    return paths


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
    restored = dec.assemble()
    if long_stream.compressed:
        # 长文择优压缩后，assemble 拿到的是 gzip 载荷，要解压才等于原文。
        restored = fountain.gzip_decompress(restored)
    assert restored == long_text.encode("utf-8")
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