package com.py37qr.scanner

// 喷泉码整数算法，与 PC 端 fountain.py 逐位一致。
// 所有 32 位运算用 Long 承载(0..0xFFFFFFFF)再截断，避免 Int 负数取模差异。
object Fountain {
    const val FRAME_PREFIX = "PYQRF1"
    const val COMPRESSED_PREFIX = "PYQRF2"

    fun splitmix32(seed: Long): () -> Long {
        var s = seed and 0xFFFFFFFFL
        return {
            s = (s + 0x9E3779B9L) and 0xFFFFFFFFL
            var t = s xor (s ushr 16)
            t = (t * 0x21F0AAADL) and 0xFFFFFFFFL
            t = t xor (t ushr 15)
            t = (t * 0x735A2D97L) and 0xFFFFFFFFL
            t = t xor (t ushr 15)
            t and 0xFFFFFFFFL
        }
    }

    fun frameSeed(sessionId: Int, seq: Long): Long {
        var h = (((sessionId.toLong() + 1L) * 0x9E3779B1L) xor
            (seq + 0x85EBCA6BL)) and 0xFFFFFFFFL
        h = ((h xor (h ushr 13)) * 0xC2B2AE35L) and 0xFFFFFFFFL
        return (h xor (h ushr 16)) and 0xFFFFFFFFL
    }

    fun repairIndices(k: Int, sessionId: Int, seq: Long): List<Int> {
        val rnd = splitmix32(frameSeed(sessionId, seq))
        val degree = minOf(k, 4 + (rnd() % 21L).toInt())
        val chosen = mutableSetOf<Int>()
        while (chosen.size < degree) {
            chosen.add((rnd() % k.toLong()).toInt())
        }
        return chosen.sorted()
    }

    fun frameComposition(k: Int, sessionId: Int, seq: Long): List<Int> {
        val pos = (seq % (2L * k)).toInt()
        return if (pos < k) listOf(pos) else repairIndices(k, sessionId, seq)
    }

    fun cycleLength(k: Int): Int = 2 * k

    fun fnv1a(data: ByteArray): Long {
        var h = 0x811C9DC5L
        for (b in data) {
            h = (h xor (b.toLong() and 0xFFL)) and 0xFFFFFFFFL
            h = (h * 0x01000193L) and 0xFFFFFFFFL
        }
        return h
    }

    fun xorBytes(a: ByteArray, b: ByteArray): ByteArray {
        val out = ByteArray(a.size)
        for (i in a.indices) {
            out[i] = (a[i].toInt() xor b[i].toInt()).toByte()
        }
        return out
    }
}