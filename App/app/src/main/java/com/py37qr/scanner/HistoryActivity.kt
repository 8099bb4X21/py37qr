package com.py37qr.scanner

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView

// 历史记录页：每行圆角卡片，左 80% 放 3 行小字内容，右 20% 放更小的日期字数。
// 点行进方格页（历史模式，不自动复制）；返回键回本页（原生栈）。
class HistoryActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_history)
        val items = HistoryStore.load(this)
        val recycler = findViewById<RecyclerView>(R.id.historyList)
        val empty = findViewById<TextView>(R.id.historyEmpty)
        if (items.isEmpty()) {
            recycler.visibility = View.GONE
            empty.visibility = View.VISIBLE
            return
        }
        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = HistoryAdapter(items) { text ->
            ResultHolder.text = text
            startActivity(
                Intent(this, SegmentActivity::class.java)
                    .putExtra(SegmentActivity.EXTRA_MODE, SegmentActivity.MODE_HISTORY)
            )
        }
    }

    private inner class HistoryAdapter(
        private val items: List<Pair<String, Long>>,
        private val onTap: (String) -> Unit,
    ) : RecyclerView.Adapter<HistoryAdapter.Holder>() {

        inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
            val content: TextView = view.findViewById(R.id.rowContent)
            val date: TextView = view.findViewById(R.id.rowDate)
            val count: TextView = view.findViewById(R.id.rowCount)
            val box: View = view.findViewById(R.id.rowBox)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_history, parent, false)
            return Holder(view)
        }

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(holder: Holder, position: Int) {
            val (text, ts) = items[position]
            holder.content.text = text
            val date = java.text.SimpleDateFormat(
                "MM-dd", java.util.Locale.getDefault()
            ).format(java.util.Date(ts))
            val time = java.text.SimpleDateFormat(
                "HH:mm", java.util.Locale.getDefault()
            ).format(java.util.Date(ts))
            holder.date.text = date + "\n" + time
            holder.count.text = text.length.toString() + "字"
            holder.box.setOnClickListener { onTap(text) }
        }
    }
}
