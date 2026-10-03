#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 转换模块: 文字 -> 二维码图片列表(1 至 4 个)。

运行环境: Python3.7 (Windows 本机 / UOS20 ARM)，依赖 segno + Pillow。
B 机确认方式: python3 -c "import segno, PIL; print('ok')"
云编译: GitHub Action(ubuntu-24.04-arm + Debian10 容器，pyinstaller 单文件)。

使用方法:
    from qr_converter import text_to_qr_images, save_qr_images

注意:
    本文件为 UTF-8 无 BOM，LF 换行。
    所有字符(含换行、斜杠、反斜杠)都按 UTF-8 byte 模式编码，无需转义。
    编码用 segno(纯 Python、无编译依赖，ARM 离线友好)，
    预览渲染用 Pillow，存 PNG 直接用 PIL 图片保存。
"""

import os
import re

from typing import List
from typing import Tuple

import segno
from segno import DataOverflowError

from PIL import Image
from PIL import ImageOps


MAX_QR_COUNT = 4

# 多码拼接协议头: PY37QR:i/N:正文，i 从 1 开始，N 为总数。
# 单码默认无头(其他扫码软件看到的就是原文)；只有单码原文恰好撞上
# 该格式时才加 1/1 头，避免手机端误判为多码缺件。
# 手机端用同样规则解析归组排序拼合，见 parse_header。
PROTOCOL_PREFIX = "PY37QR:"
HEADER_RE = re.compile(r"^PY37QR:(\d+)/(\d+):([\s\S]*)$")

# 4 码分片上限内单个码的字符数绝对上限(版本 40-L 纯字母数字模式约 4296)。
# 超过这个数任何纠错等级都装不下，用于超长输入的快速失败，
# 避免对注定失败的输入做多次昂贵的编码尝试。
ABS_MAX_CHARS_PER_CODE = 4296

ERROR_LEVELS = ("L", "M", "Q", "H")

# 每个纠错等级的粗略单码字节上限(byte 模式，版本 40)。
# 只用于界面显示上限估算与友好提示，
# 真正是否装得下以 segno 是否抛 DataOverflowError 为准。
BYTE_BUDGET = {
    "L": 2953,
    "M": 2331,
    "Q": 1663,
    "H": 1273,
}


def get_error_correction(error_name):
    # 用途: 校验并归一化纠错等级字母，非法输入抛 ValueError。
    # 参数 error_name: 纠错等级字母，不区分大小写。
    # 返回: 大写字母 L/M/Q/H 之一，直接给 segno 的 error 参数用。
    # 异常: ValueError 输入不在 L/M/Q/H 中时抛出。
    key = str(error_name).strip().upper()
    if key not in ERROR_LEVELS:
        raise ValueError("纠错等级只支持 L/M/Q/H，当前是: " + str(error_name))
    return key


def try_encode(text_chunk, error_name):
    # 用途: 只编码不渲染，用于分片试探，装不下时抛 ValueError。
    # 为什么编码与渲染分离: 渲染(PIL 放大)是纯体力活，
    # 试探阶段只做编码，定稿后才渲染一次，避免重复渲染。
    # 参数 text_chunk: 非空字符串，原样编码，不做任何转义。
    # 参数 error_name: L/M/Q/H。
    # 返回: segno.QRCode 对象。
    # 异常: ValueError 文字为空或超出单个二维码容量时抛出。
    if text_chunk is None or text_chunk == "":
        raise ValueError("输入文字为空，无法生成二维码")
    level = get_error_correction(error_name)
    try:
        # boost_error=False: 保持用户选定的纠错等级，
        # 否则 segno 会在有空闲时静默升级等级，容量估算就失准了。
        # make_qr 强制标准 QR(不用 Micro QR)，扫码兼容性最好。
        qr = segno.make_qr(text_chunk, error=level.lower(), boost_error=False)
    except DataOverflowError as exc:
        raise ValueError("单个二维码装不下(长度约超限): " + str(exc))
    return qr


def render_qr_image(qr, box_size, border):
    # 用途: 把 segno 编码结果渲染成 PIL 图片(RGB)。
    # 参数 qr: try_encode 返回的 segno.QRCode 对象。
    # 参数 box_size: 每个模块像素数，建议 4-20。
    # 参数 border: 白边模块数，建议 2-10。
    # 返回: PIL.Image.Image 对象(RGB 模式)。
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


def build_single_qr(text_chunk, box_size, border, error_name):
    # 用途: 把一段文字做成一张二维码图片，装不下时抛 ValueError。
    # 参数 text_chunk: 非空字符串，原样编码，不做任何转义。
    # 参数 box_size: 每个模块像素数，建议 4-20。
    # 参数 border: 白边模块数，建议 2-10。
    # 参数 error_name: L/M/Q/H。
    # 返回: PIL.Image.Image 对象(RGB 模式)。
    # 异常: ValueError 文字为空或超出单个二维码容量时抛出。
    qr = try_encode(text_chunk, error_name)
    return render_qr_image(qr, box_size, border)


def split_text_evenly(text, parts):
    # 用途: 按字符数把长文字均匀切成 parts 段。
    # 为什么按字符而不是按字节: Python 字符串按字符切片不会把
    # UTF-8 多字节字符从中间切断，segno 侧再整体按 UTF-8 编码即可。
    # 参数 text: 原始全文。
    # 参数 parts: 切分数(2-4)。
    # 返回: List[str]，长度为 parts，不含空段。
    total = len(text)
    if parts <= 1:
        return [text]
    avg = (total + parts - 1) // parts
    chunks = []
    for idx in range(parts):
        part = text[idx * avg:(idx + 1) * avg]
        if part != "":
            chunks.append(part)
    return chunks


def parse_header(text):
    # 用途: 解析拼接协议头，手机端与自测用同一规则。
    # 参数 text: 扫到的单码全文。
    # 返回: (序号, 总数, 正文) 元组；无头返回 (1, 1, 原文)。
    # 异常: 无，所有输入都可解析。
    match = HEADER_RE.match(text)
    if match is None:
        return 1, 1, text
    return int(match.group(1)), int(match.group(2)), match.group(3)


def add_headers(chunks):
    # 用途: 给切分后的每段加序号头，多码必加，单码仅在原文撞头时加 1/1。
    # 参数 chunks: split_text_evenly 切出的段列表。
    # 返回: List[str]，加头后的每段。
    total = len(chunks)
    if total <= 1:
        single = chunks[0] if chunks else ""
        if HEADER_RE.match(single) is not None:
            return [PROTOCOL_PREFIX + "1/1:" + single]
        return chunks
    headed = []
    for idx, chunk in enumerate(chunks, start=1):
        headed.append(PROTOCOL_PREFIX + str(idx) + "/" + str(total) + ":" + chunk)
    return headed


def auto_split_text(text, error_name):
    # 用途: 自动决定拆成几个码(1-4)，尽量少拆，只编码不渲染。
    # 参数 text: 原始全文。
    # 参数 error_name: L/M/Q/H，用于预判容量。
    # 返回: List[str]，切分后的每段文字。
    # 异常: ValueError 即使拆成 4 个仍然装不下时抛出。
    if text is None or text == "":
        raise ValueError("输入文字为空，无法生成二维码")
    last_err = None
    for parts in range(1, MAX_QR_COUNT + 1):
        chunks = split_text_evenly(text, parts)
        # 注意按加头后的内容试容量，头本身也占字节，边界处可能刚好装不下。
        chunks = add_headers(chunks)
        ok = True
        for chunk in chunks:
            try:
                try_encode(chunk, error_name)
            except ValueError as exc:
                ok = False
                last_err = exc
                break
        if ok:
            return chunks
    detail = ""
    if last_err is not None:
        detail = "，详情: " + str(last_err)
    raise ValueError(
        "文字过长，即使拆成 4 个二维码也装不下"
        + "(可缩短文字或把纠错等级从 H 降到 L/M)"
        + detail
    )


def text_to_qr_images(text, box_size=10, border=4, error_name="M"):
    # 用途: 对外主入口，文字转 1-4 张二维码图片，单遍生成不做重复渲染。
    # 参数 text: 任意文字，支持中文、换行、斜杠、反斜杠。
    # 参数 box_size: 尺寸，默认 10。
    # 参数 border: 边框，默认 4。
    # 参数 error_name: 纠错等级，默认 M。
    # 返回: List[Image]，长度 1-4。
    # 异常: ValueError 参数非法或超长时抛出。
    box_size = int(box_size)
    border = int(border)
    if box_size < 1 or box_size > 30:
        raise ValueError("box_size 建议范围 1-30，当前是: " + str(box_size))
    if border < 0 or border > 20:
        raise ValueError("border 建议范围 0-20，当前是: " + str(border))
    if text is None or text == "":
        raise ValueError("输入文字为空，无法生成二维码")
    # 绝对上限快速失败：连理论最大值都超了就不再试编码，避免多次昂贵适配。
    if len(text) > ABS_MAX_CHARS_PER_CODE * MAX_QR_COUNT:
        raise ValueError(
            "文字过长，即使拆成 4 个二维码也装不下"
            + "(可缩短文字或把纠错等级从 H 降到 L/M)"
        )
    last_err = None
    for parts in range(1, MAX_QR_COUNT + 1):
        chunks = split_text_evenly(text, parts)
        chunks = add_headers(chunks)
        codes = []
        ok = True
        for chunk in chunks:
            try:
                codes.append(try_encode(chunk, error_name))
            except ValueError as exc:
                ok = False
                last_err = exc
                break
        if ok:
            images = []
            for qr in codes:
                images.append(render_qr_image(qr, box_size, border))
            return images
    detail = ""
    if last_err is not None:
        detail = "，详情: " + str(last_err)
    raise ValueError(
        "文字过长，即使拆成 4 个二维码也装不下"
        + "(可缩短文字或把纠错等级从 H 降到 L/M)"
        + detail
    )


def save_qr_images(images, base_path):
    # 用途: 把 1-4 张图片存为 PNG，单张直接存，多张加 _1/_2 后缀。
    # 参数 images: text_to_qr_images 的返回值，非空列表。
    # 参数 base_path: 目标路径，可带或不带 .png 后缀。
    # 返回: List[str]，实际写出的文件路径。
    # 异常: ValueError images 为空时抛出；OSError 写盘失败时抛出。
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
    # 用途: 命令行自测入口，演示换行、斜杠、反斜杠都能直接编码。
    print("[INFO] 转换模块自测开始")
    demo = "第一行\n第二行/斜杠\\反斜杠 ABC 123 中文"
    images = text_to_qr_images(demo, 10, 4, "M")
    print("[INFO] 输入长度=" + str(len(demo)) + "，生成数量=" + str(len(images)))
    saved = save_qr_images(images, "qr_demo")
    print("[INFO] 已保存: " + ", ".join(saved))
    print("[INFO] 自测完毕")


if __name__ == "__main__":
    import sys

    try:
        main()
    except Exception as e:
        print("[FAIL] 自测异常: " + str(e))
        raise
    finally:
        # GUI 通过窗口等待用户，命令行才需要按任意键。
        # 非交互式(管道、CI)下自动跳过，不会卡住。
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
