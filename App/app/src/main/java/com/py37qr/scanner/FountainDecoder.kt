package com.py37qr.scanner

// LT 喷泉解码器：抓够 k 个不同有效帧即还原，顺序/丢帧无关。
// compressed 只做会话标记与解压分支，消元数学与原文/压缩无关。
class FountainDecoder(
    val k: Int,
    val blockLen: Int,
    val sessionId: Int,
    val totalLen: Int,
    val payloadFnv: Long,
    val compressed: Boolean = false,
) {
    private class PendingFrame(var idx: MutableSet<Int>, var words: ByteArray)

    private val solved = arrayOfNulls<ByteArray>(k)
    private val pending = mutableListOf<PendingFrame>()
    private val seen = mutableSetOf<Long>()

    val isComplete: Boolean
        get() = solved.all { it != null }

    val solvedCount: Int
        get() = solved.count { it != null }

    fun addFrame(seq: Long, block: ByteArray) {
        if (seq in seen) return
        seen.add(seq)
        if (isComplete) return

        val idx = Fountain.frameComposition(k, sessionId, seq).toMutableSet()
        var words = block
        for (b in idx.toList()) {
            val sb = solved[b]
            if (sb != null) {
                words = Fountain.xorBytes(words, sb)
                idx.remove(b)
            }
        }
        if (idx.isEmpty()) return
        if (idx.size == 1) {
            resolve(idx.first(), words)
            return
        }
        pending.add(PendingFrame(idx, words))
    }

    private fun resolve(b0: Int, w0: ByteArray) {
        val queue = ArrayDeque<Pair<Int, ByteArray>>()
        queue.add(b0 to w0)
        while (queue.isNotEmpty()) {
            val (b, w) = queue.removeFirst()
            if (solved[b] != null) continue
            solved[b] = w
            for (pf in pending) {
                if (b in pf.idx) {
                    pf.idx.remove(b)
                    pf.words = Fountain.xorBytes(pf.words, w)
                }
            }
            pending.removeAll { it.idx.isEmpty() }
            for (pf in pending) {
                if (pf.idx.size == 1) {
                    val nb = pf.idx.first()
                    if (solved[nb] == null) {
                        queue.add(nb to pf.words)
                    }
                }
            }
        }
    }

    fun assemble(): ByteArray? {
        if (!isComplete) return null
        val out = ByteArray(totalLen)
        var off = 0
        for (i in 0 until k) {
            val blk = solved[i] ?: return null
            val len = minOf(blk.size, totalLen - off)
            if (len > 0) {
                System.arraycopy(blk, 0, out, off, len)
                off += len
            }
        }
        if (Fountain.fnv1a(out) != payloadFnv) return null
        return out
    }
}