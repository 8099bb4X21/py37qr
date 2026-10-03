package com.py37qr.scanner

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView

// 方格结果页：4500字一段，2列正方形格，点格复制该段。
// 扫码进自动复制第一段，历史进不自动复制；返回键回上层（原生栈）。
class SegmentActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_MODE = "mode"
        const val MODE_SCAN = "scan"
        const val MODE_HISTORY = "history"
        const val SEGMENT_SIZE = 4500
        const val PREVIEW_CHARS = 30
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_segment)
        // 不清 holder：旋转重建靠它恢复；每次进页 Main 必先 set，不会串味。
        val text = ResultHolder.text ?: ""
        val mode = intent.getStringExtra(EXTRA_MODE)

        val raw = if (text.isEmpty()) listOf("") else text.chunked(SEGMENT_SIZE)
        val recycler = findViewById<RecyclerView>(R.id.segmentGrid)
        recycler.layoutManager = GridLayoutManager(this, 2)
        recycler.adapter = SegmentAdapter(raw, ::copySegment)

        // 只在首次创建自动复制；旋转重建（savedInstanceState 非空）不再重复弹 Toast。
        if (savedInstanceState == null && mode == MODE_SCAN && raw.isNotEmpty()) {
            copySegment(raw[0], 1)
        }
    }

    private fun copySegment(segment: String, index: Int) {
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        manager.setPrimaryClip(ClipData.newPlainText("py37qr-seg", segment))
        Toast.makeText(this, "已复制第" + index + "段", Toast.LENGTH_SHORT).show()
    }

    private inner class SegmentAdapter(
        private val segments: List<String>,
        private val onTap: (String, Int) -> Unit,
    ) : RecyclerView.Adapter<SegmentAdapter.Holder>() {

        inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
            val preview: TextView = view.findViewById(R.id.cellPreview)
            val label: TextView = view.findViewById(R.id.cellLabel)
            val box: View = view.findViewById(R.id.cellBox)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_segment, parent, false)
            return Holder(view)
        }

        override fun getItemCount(): Int = segments.size

        override fun onBindViewHolder(holder: Holder, position: Int) {
            val seg = segments[position]
            val head = if (seg.length > PREVIEW_CHARS) seg.take(PREVIEW_CHARS) + "…" else seg
            holder.preview.text = head
            holder.label.text = "第" + (position + 1) + "段·共" + seg.length + "字"
            holder.box.setOnClickListener { onTap(seg, position + 1) }
        }
    }
}
