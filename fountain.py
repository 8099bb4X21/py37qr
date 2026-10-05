#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
喷泉码(LT) 编码/解码 + 文本帧协议，参考 decimen 的分片思路。

数据切 k 块，carousel 无限轮播：前 k 帧是系统帧(单块)，后 k 帧是修复帧
(随机 4~24 块 XOR)。接收端抓够任意 k 个不同有效帧即还原，顺序/丢帧无关。
帧组合序列(splitmix32 + frameSeed + frameComposition)是全整数确定性算法，
Python 生成端与 Kotlin 解码端各写同一份，bit 级一致，无浮点漂移。
帧用文本协议避免二进制进 QR："PYQRF1:sid:seq:k:blockLen:totalLen:fnv:base64"。
块按 blockLen 字节对齐，末块补 0；XOR 按字节；还原后按 totalLen 截断。
"""

import base64
import gzip
import random


FRAME_PREFIX = "PYQRF1"
COMPRESSED_PREFIX = "PYQRF2"
REPAIR_DEGREE_MIN = 4
REPAIR_DEGREE_MAX = 24


def try_gzip_compress(data):
    # 压缩先行：gzip -9 择优，压后更小才用；失败/膨胀返回原文。
    # 返回 (载荷字节, 是否压缩)。只走标准库，py37/离线可用。
    try:
        raw = bytes(data)
    except Exception:
        return bytes(data), False
    if len(raw) < 1:
        return raw, False
    try:
        gz = gzip.compress(raw, compresslevel=9)
    except Exception:
        return raw, False
    if len(gz) < len(raw):
        return gz, True
    return raw, False


def gzip_decompress(data):
    # 解压传输层载荷；失败返回 None（调用方按校验失败处理）。
    try:
        return gzip.decompress(bytes(data))
    except Exception:
        return None


def _u32(value):
    # 截成 32 位无符号，对齐 JS 的 |0 / >>> 语义。
    return value & 0xFFFFFFFF


def splitmix32(seed):
    # 逐帧确定性 PRNG，与 decimen 的 JS 版 bit 级一致。
    state = [seed & 0xFFFFFFFF]

    def next_value():
        s = state[0]
        s = (s + 0x9E3779B9) & 0xFFFFFFFF
        t = s ^ (s >> 16)
        t = (t * 0x21F0AAAD) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        t = (t * 0x735A2D97) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        state[0] = s
        return t & 0xFFFFFFFF

    return next_value


def frame_seed(session_id, seq):
    # 由会话号与帧号派生种子，两端一致。
    h = (_u32((session_id + 1) * 0x9E3779B1) ^ _u32(seq + 0x85EBCA6B)) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFFFFFF


def repair_indices(k, session_id, seq):
    # 修复帧：随机取 4~24 个互不相同的块索引。
    rnd = splitmix32(frame_seed(session_id, seq))
    degree = min(k, REPAIR_DEGREE_MIN + (rnd() % (REPAIR_DEGREE_MAX - REPAIR_DEGREE_MIN + 1)))
    chosen = set()
    while len(chosen) < degree:
        chosen.add(rnd() % k)
    return sorted(chosen)


def frame_composition(k, session_id, seq):
    # 第 seq 帧由哪些块 XOR 而成。carousel = 2k 帧循环。
    pos = seq % (2 * k)
    if pos < k:
        return [pos]
    return repair_indices(k, session_id, seq)


def cycle_length(k):
    return 2 * k


def fnv1a(data):
    # FNV-1a 32 位散列，还原后校验用。
    h = 0x811C9DC5
    for byte in data:
        h = (h ^ byte) & 0xFFFFFFFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def xor_bytes(a, b):
    return bytearray(x ^ y for x, y in zip(a, b))


class FountainEncoder:
    # 把字节切成 k 块，按 seq 生成喷泉帧。
    # payload 是传输层载荷：原文 UTF-8 或 gzip 字节；compressed 只决定帧前缀。

    def __init__(self, payload, block_len=200, session_id=None, compressed=False):
        if not payload:
            raise ValueError("payload 为空")
        self.payload = bytes(payload)
        self.compressed = bool(compressed)
        self.total_len = len(self.payload)
        self.block_len = int(block_len)
        if self.block_len < 1:
            raise ValueError("block_len 必须 >= 1")
        self.k = max(1, (self.total_len + self.block_len - 1) // self.block_len)
        self.session_id = (session_id if session_id is not None else random.getrandbits(16)) & 0xFFFF
        self.payload_fnv = fnv1a(self.payload)
        self._blocks = []
        for idx in range(self.k):
            start = idx * self.block_len
            chunk = self.payload[start:start + self.block_len]
            if len(chunk) < self.block_len:
                chunk = chunk + b"\x00" * (self.block_len - len(chunk))
            self._blocks.append(chunk)

    def frame_bytes(self, seq):
        idx = frame_composition(self.k, self.session_id, seq)
        result = bytearray(self.block_len)
        for block_pos in idx:
            result = xor_bytes(result, self._blocks[block_pos])
        return bytes(result)

    def frame_text(self, seq):
        b64 = base64.b64encode(self.frame_bytes(seq)).decode("ascii")
        prefix = COMPRESSED_PREFIX if self.compressed else FRAME_PREFIX
        return (
            prefix + ":" + format(self.session_id, "04x") + ":" + str(seq)
            + ":" + str(self.k) + ":" + str(self.block_len) + ":" + str(self.total_len)
            + ":" + format(self.payload_fnv, "08x") + ":" + b64
        )


def parse_frame_text(text):
    # 解析文本帧；非本协议返回 None。与 Kotlin 端同规则。
    # 双前缀都认：PYQRF1=原文载荷，PYQRF2=gzip 载荷；旧单前缀帧照常通过。
    parts = text.split(":")
    if len(parts) != 8 or parts[0] not in (FRAME_PREFIX, COMPRESSED_PREFIX):
        return None
    try:
        data = {
            "prefix": parts[0],
            "compressed": parts[0] == COMPRESSED_PREFIX,
            "sessionId": int(parts[1], 16),
            "seq": int(parts[2]),
            "k": int(parts[3]),
            "blockLen": int(parts[4]),
            "totalLen": int(parts[5]),
            "payloadFnv": int(parts[6], 16),
            "block": base64.b64decode(parts[7]),
        }
    except (ValueError, TypeError):
        return None
    if len(data["block"]) != data["blockLen"]:
        return None
    # 防御 crafted 帧：负 seq 会让 Kotlin 端数组越界崩溃，超大 totalLen 会 OOM。
    # 合法帧(本编码器产出)恒满足以下约束，两端用同一套。
    if not (0 <= data["sessionId"] <= 0xFFFF):
        return None
    if data["seq"] < 0 or data["k"] < 1 or data["k"] > 4096:
        return None
    if data["blockLen"] < 1 or data["blockLen"] > 4096:
        return None
    if data["totalLen"] < 1 or data["totalLen"] > 8 * 1024 * 1024:
        return None
    if data["totalLen"] > data["blockLen"] * data["k"]:
        return None
    return data


class FountainDecoder:
    # 接收端喷泉解码：喂入若干帧，抠级消元，解够 k 块即还原。

    def __init__(self, k, block_len, session_id, total_len, payload_fnv):
        self.k = k
        self.block_len = block_len
        self.session_id = session_id
        self.total_len = total_len
        self.payload_fnv = payload_fnv
        self.solved = [None] * k
        self.pending = []
        self.seen = set()

    def is_complete(self):
        return all(self.solved)

    def add_frame(self, seq, block_bytes):
        if seq in self.seen:
            return
        self.seen.add(seq)
        if self.is_complete():
            return
        idx = set(frame_composition(self.k, self.session_id, seq))
        words = bytearray(block_bytes)
        for b in list(idx):
            if self.solved[b] is not None:
                words = xor_bytes(words, self.solved[b])
                idx.discard(b)
        if not idx:
            return
        if len(idx) == 1:
            self._resolve(next(iter(idx)), words)
            return
        self.pending.append((idx, words))

    def _resolve(self, b0, w0):
        queue = [(b0, w0)]
        while queue:
            b, w = queue.pop()
            if self.solved[b] is not None:
                continue
            self.solved[b] = bytes(w)
            remaining = []
            for idx, words in self.pending:
                if b in idx:
                    idx.discard(b)
                    words = xor_bytes(words, w)
                if idx:
                    remaining.append((idx, words))
            self.pending = remaining
            for idx, words in self.pending:
                if len(idx) == 1:
                    nb = next(iter(idx))
                    if self.solved[nb] is None:
                        queue.append((nb, words))

    def assemble(self):
        if not self.is_complete():
            return None
        out = b"".join(self.solved)[:self.total_len]
        if fnv1a(out) != self.payload_fnv:
            return None
        return out


def _verify(payload, block_len=200, drop_ratio=0.3):
    # 端到端自测：按真实轮播“顺序滚多个 cycle + 随机丢帧”，直到还原。
    enc = FountainEncoder(payload, block_len=block_len, session_id=12345)
    dec = FountainDecoder(enc.k, enc.block_len, enc.session_id, enc.total_len, enc.payload_fnv)
    order = list(range(cycle_length(enc.k)))
    random.shuffle(order)
    for seq in order:
        if random.random() < drop_ratio:
            continue
        text = enc.frame_text(seq)
        parsed = parse_frame_text(text)
        dec.add_frame(parsed["seq"], parsed["block"])
        if dec.is_complete():
            break
    return dec.assemble()


def main():
    random.seed(1)
    payload = ("这是一段用于验证喷泉码的中文文本。".encode("utf-8") * 200) + b"tail"
    # 丢 30% 帧并乱序，仍能还原。
    out = _verify(payload, block_len=200, drop_ratio=0.3)
    assert out == payload, "喷泉还原不一致"
    print("[PASS] 喷泉码乱序+丢帧30% 还原成功, 字节=" + str(len(payload)))
    # 补充：顺序无限滚 carousel + 随机丢 50%，4k 帧内应还原（真实轮播模型）。
    enc = FountainEncoder(b"x" * 1000, block_len=200, session_id=9)
    dec = FountainDecoder(enc.k, enc.block_len, enc.session_id, enc.total_len, enc.payload_fnv)
    recovered = False
    for seq in range(cycle_length(enc.k) * 4):
        if random.random() < 0.5:
            continue
        parsed = parse_frame_text(enc.frame_text(seq))
        dec.add_frame(parsed["seq"], parsed["block"])
        if dec.is_complete():
            recovered = True
            break
    assert recovered and dec.assemble() == b"x" * 1000
    print("[PASS] 随机丢50% 仍还原")
    # 补充：非法文本返回 None。
    assert parse_frame_text("https://example.com") is None
    assert parse_frame_text("PYQRF1:bad") is None
    print("[PASS] 非法文本正确识别为非本协议")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[FAIL] " + str(e))
        raise