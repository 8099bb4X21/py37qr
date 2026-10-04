package com.py37qr.scanner

import android.content.Context

// 历史记录存取共用：Main 存，HistoryActivity 取。最近 30 条，新在前。
// 存坏/读坏一律静默空结果，不挡扫码主流程。
object HistoryStore {
    private const val PREFS = "scan_history"
    private const val KEY = "items"
    const val MAX_ITEMS = 30
    // 单条上限 60000 字：prefs 无硬限制但 XML 过大会卡顿，超了截断打标记。
    const val MAX_CHARS = 60000

    fun save(context: Context, text: String) {
        val capped = if (text.length > MAX_CHARS) {
            text.take(MAX_CHARS) + "…（过长已截断）"
        } else {
            text
        }
        try {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val old = try {
                org.json.JSONArray(prefs.getString(KEY, "[]"))
            } catch (e: Exception) {
                org.json.JSONArray()
            }
            val next = org.json.JSONArray()
            next.put(
                org.json.JSONObject().put("t", capped).put("ts", System.currentTimeMillis())
            )
            var start = 0
            // 与最新一条内容相同就不重复记（连扫同一码不刷屏）。
            if (old.length() > 0) {
                try {
                    if (old.getJSONObject(0).optString("t") == capped) {
                        start = 1
                    }
                } catch (e: Exception) {
                }
            }
            for (i in start until minOf(old.length(), MAX_ITEMS - 1)) {
                next.put(old.get(i))
            }
            prefs.edit().putString(KEY, next.toString()).apply()
        } catch (e: Exception) {
        }
    }

    fun load(context: Context): List<Pair<String, Long>> {
        return try {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val arr = org.json.JSONArray(prefs.getString(KEY, "[]"))
            val out = mutableListOf<Pair<String, Long>>()
            for (i in 0 until minOf(arr.length(), MAX_ITEMS)) {
                val obj = arr.getJSONObject(i)
                out.add(obj.getString("t") to obj.getLong("ts"))
            }
            out
        } catch (e: Exception) {
            emptyList()
        }
    }
}
