#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""fountain + qr_converter 单元验证。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fountain
import qr_converter


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        raise SystemExit(1)


def roundtrip(payload, block_len, drop=0.3):
    # 端到端：按真实轮播“顺序滚多个 cycle + 随机丢帧”，直到还原。
    enc = fountain.FountainEncoder(payload, block_len=block_len, session_id=12345)
    dec = fountain.FountainDecoder(
        enc.k, enc.block_len, enc.session_id, enc.total_len, enc.payload_fnv)
    import random
    random.seed(7)
    for seq in range(fountain.cycle_length(enc.k) * 4):
        if random.random() < drop:
            continue
        parsed = fountain.parse_frame_text(enc.frame_text(seq))
        dec.add_frame(parsed["seq"], parsed["block"])
        if dec.is_complete():
            break
    return dec.assemble()


# 1. fountain 核心
payload = ("喷泉码中文测试" * 300).encode("utf-8")
check("喷泉乱序+丢30%还原", roundtrip(payload, 200, 0.3) == payload)
check("喷泉丢50%还原", roundtrip(b"x" * 1000, 200, 0.5) == b"x" * 1000)

# 2. 帧协议往返
enc = fountain.FountainEncoder(payload, block_len=150, session_id=7)
p = fountain.parse_frame_text(enc.frame_text(999))
check("帧协议往返字段正确", p["seq"] == 999 and p["k"] == enc.k)
check("非法文本返回None", fountain.parse_frame_text("https://x.com") is None)

# 2b. 两端一致金标：Kotlin 端必须算出完全相同的值，否则跨端失配。
check("金标frame_seed", fountain.frame_seed(12345, 7) == 2869426599)
check("金标frame_composition", (
    [fountain.frame_composition(5, 12345, s) for s in range(10)]
    == [[0], [1], [2], [3], [4], [0, 1, 2, 3, 4], [0, 1, 2, 3, 4],
        [0, 1, 2, 3, 4], [0, 1, 2, 3, 4], [0, 1, 2, 3, 4]]
))
check("金标fnv1a", format(fountain.fnv1a(b"abc"), "08x") == "1a47e90b")
r = fountain.splitmix32(99)
check("金标splitmix32", [r() for _ in range(3)] == [349753557, 2385026473, 2250837844])

# 2c. 恶意/畸形帧必须拒绝（对应 Kotlin 端防崩溃）。
import base64 as _b64
_good_block = _b64.b64encode(b"x" * 200).decode("ascii")


def _frame(seq, k, block_len, total_len):
    return "PYQRF1:0001:%s:%d:%d:%d:00000000:%s" % (
        seq, k, block_len, total_len, _good_block)


check("负seq拒绝", fountain.parse_frame_text(_frame("-5", 5, 200, 1000)) is None)
check("超大totalLen拒绝", fountain.parse_frame_text(_frame("0", 5, 200, 999999999)) is None)
check("totalLen超blockLen*k拒绝", fountain.parse_frame_text(_frame("0", 5, 200, 2000)) is None)
check("合法帧照常通过", fountain.parse_frame_text(_frame("3", 5, 200, 1000)) is not None)

# 3. qr_converter 单码/喷泉判定
short = qr_converter.EncodedStream("你好", error_name="M")
check("短文字单码", short.single and short.frame_count() == 1)
long_stream = qr_converter.EncodedStream("长" * 3000, error_name="M", block_len=120)
check("长文字喷泉轮播", (not long_stream.single) and long_stream.frame_count() == 2 * long_stream.k)

# 4. 轮播帧可完整还原原文（含 gzip 择优：载荷可能是压缩字节）
dec = fountain.FountainDecoder(
    long_stream.encoder.k, long_stream.encoder.block_len,
    long_stream.encoder.session_id, long_stream.encoder.total_len,
    long_stream.encoder.payload_fnv)
for i in range(fountain.cycle_length(long_stream.k)):
    parsed = fountain.parse_frame_text(long_stream.frame_text(i))
    dec.add_frame(parsed["seq"], parsed["block"])
_raw_out = dec.assemble()
if long_stream.compressed:
    check("轮播帧完整还原", fountain.gzip_decompress(_raw_out) == ("长" * 3000).encode("utf-8"))
else:
    check("轮播帧完整还原", _raw_out == ("长" * 3000).encode("utf-8"))

# 4b. P0-1 压缩先行：中文长文应触发压缩且 k 变小；单码保持原文
raw_long = ("长文测试，压缩先行。" * 500).encode("utf-8")
gz_payload, gz_flag = fountain.try_gzip_compress(raw_long)
check("中文长文触发gzip", gz_flag and len(gz_payload) < len(raw_long))
enc_raw = fountain.FountainEncoder(raw_long, block_len=120, session_id=11)
enc_gz = fountain.FountainEncoder(gz_payload, block_len=120, session_id=11, compressed=True)
check("压缩后k变小", enc_gz.k < enc_raw.k)
check("压缩帧前缀PYQRF2", enc_gz.frame_text(0).startswith("PYQRF2:"))
check("原文帧前缀PYQRF1", enc_raw.frame_text(0).startswith("PYQRF1:"))
p_gz = fountain.parse_frame_text(enc_gz.frame_text(3))
check("压缩帧解析回compressed", p_gz is not None and p_gz["compressed"] is True)
p_raw = fountain.parse_frame_text(enc_raw.frame_text(3))
check("原文帧解析回非压缩", p_raw is not None and p_raw["compressed"] is False)
# 压缩端到端：丢 30% 仍还原再解压
dec2 = fountain.FountainDecoder(
    enc_gz.k, enc_gz.block_len, enc_gz.session_id, enc_gz.total_len, enc_gz.payload_fnv)
import random as _rd
_rd.seed(11)
for seq in range(fountain.cycle_length(enc_gz.k) * 4):
    if _rd.random() < 0.3:
        continue
    _pp = fountain.parse_frame_text(enc_gz.frame_text(seq))
    dec2.add_frame(_pp["seq"], _pp["block"])
    if dec2.is_complete():
        break
check("压缩载荷丢帧还原", fountain.gzip_decompress(dec2.assemble()) == raw_long)
# 旧 PYQRF1 帧（无 compressed 概念前）仍按非压缩通过
check("旧帧兼容", fountain.parse_frame_text("PYQRF1:0001:3:5:200:1000:00000000:" + _good_block) is not None)
# 单码路径恒为原文（不压缩）
_single = qr_converter.EncodedStream("你好", error_name="M")
check("单码不压缩", _single.single and (not _single.compressed) and _single.frame_text(0) == "你好")

# 4c. 轮播帧对象缓存：同 seq 命中同一对象，矩阵与现编一致
_q0a = long_stream.qr_code(0)
_q0b = long_stream.qr_code(0)
check("缓存命中同一对象", _q0a is _q0b)
_fresh = qr_converter.try_encode(long_stream.frame_text(0), "M")
check("缓存矩阵与现编一致", list(_q0a.matrix) == list(_fresh.matrix))

# 5. 二维码图片可解码(仅验证 PNG 渲染，不依赖 zbar)
img = qr_converter.build_qr_image(short.frame_text(0), 4, 4, "M")
check("渲染单码图", img is not None and img.size[0] > 0)

print("[INFO] 全部验证通过")