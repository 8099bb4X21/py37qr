package com.py37qr.scanner

// 跨页面传超长文本的中转：Intent extra 有 Binder 限制，方格文本可能很长。
object ResultHolder {
    var text: String? = null
}
