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
import androidx.recyclerview.widget.RecyclerView
import com.google.android.flexbox.AlignItems
import com.google.android.flexbox.FlexDirection
import com.google.android.flexbox.FlexWrap
import com.google.android.flexbox.FlexboxLayoutManager
import com.google.android.flexbox.JustifyContent

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
        // Flexbox 行内居中：不满一行的尾巴也居中，方格横向向两边长。
        recycler.layoutManager = FlexboxLayoutManager(this).apply {
            flexDirection = FlexDirection.ROW
            flexWrap = FlexWrap.WRAP
            justifyContent = JustifyContent.CENTER
            alignItems = AlignItems.FLEX_START
        }
        // 正方形边长 =（屏宽 - 页面边距 - 格间隙）/ 2，Adapter 里按此定死宽高。
        val density = resources.displayMetrics.density
        val marginPx = (4 * density).toInt()
        val cellPx = ((resources.displayMetrics.widthPixels - 40 * density) / 2).toInt()
        val gapPx = marginPx * 2
        recycler.adapter = SegmentAdapter(raw, cellPx, marginPx, ::copySegment)
        centerIfSmall(recycler, raw.size, cellPx, gapPx)

        if (savedInstanceState == null && mode == MODE_SCAN && raw.isNotEmpty()) {
            copySegment(raw[0], 1)
        }
    }

    private fun centerIfSmall(recycler: RecyclerView, count: Int, cellPx: Int, gapPx: Int) {
        // 内容不足一屏时整体垂直居中：算出内容高，顶部垫一半差值。
        recycler.post {
            val rows = (count + 1) / 2
            val contentH = rows * cellPx + (rows - 1) * gapPx
            val pad = ((recycler.height - contentH) / 2).coerceAtLeast(0)
            recycler.setPadding(
                recycler.paddingLeft, pad, recycler.paddingRight, pad
            )
        }
    }

    private fun copySegment(segment: String, index: Int) {
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        manager.setPrimaryClip(ClipData.newPlainText("py37qr-seg", segment))
        Toast.makeText(this, "已复制第" + index + "段", Toast.LENGTH_SHORT).show()
    }

    private inner class SegmentAdapter(
        private val segments: List<String>,
        private val cellPx: Int,
        private val marginPx: Int,
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
            // 宽高写死相等，保证正方形，不随内容撑开；边距手写（覆盖 XML 值）。
            val lp = FlexboxLayoutManager.LayoutParams(cellPx, cellPx)
            lp.setMargins(marginPx, marginPx, marginPx, marginPx)
            view.layoutParams = lp
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
