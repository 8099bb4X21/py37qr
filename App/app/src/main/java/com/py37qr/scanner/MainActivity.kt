package com.py37qr.scanner

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Base64
import android.util.Size
import android.view.Menu
import android.view.MenuItem
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import zxingcpp.BarcodeReader
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

// 与 PC 端 fountain.py 协议一致：帧文本 "PYQRF1:sid:seq:k:blockLen:totalLen:fnv:base64"。
private data class FrameHeader(
    val sessionId: Int,
    val seq: Long,
    val k: Int,
    val blockLen: Int,
    val totalLen: Int,
    val payloadFnv: Long,
    val block: ByteArray,
)

class MainActivity : AppCompatActivity() {

    private lateinit var cameraExecutor: ExecutorService
    private lateinit var previewView: PreviewView
    private lateinit var statusText: TextView
    private lateinit var zoomBar: SeekBar
    private var camera: Camera? = null

    private var decoder: FountainDecoder? = null
    // 方格页打开期间不再收新结果；返回时 onResume 清掉。
    private var gridOpen = false
    // 从历史进的方格：AlertDialog 点选会自动关闭列表页，
    // 返回时靠这个标记重开历史列表，对齐“回历史记录”。
    private var returnToHistory = false

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startCamera()
            } else {
                statusText.setText(R.string.need_camera)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        setSupportActionBar(findViewById(R.id.toolbar))
        previewView = findViewById(R.id.previewView)
        statusText = findViewById(R.id.statusText)
        zoomBar = findViewById(R.id.zoomBar)
        zoomBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) {
                    applySliderZoom(progress)
                }
            }

            override fun onStartTrackingTouch(seekBar: SeekBar?) {}

            override fun onStopTrackingTouch(seekBar: SeekBar?) {}
        })
        cameraExecutor = Executors.newSingleThreadExecutor()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener(
            {
                val provider = providerFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val analysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(1280, 720))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build().also {
                        it.setAnalyzer(cameraExecutor, QrAnalyzer(::onQrs))
                    }
                provider.unbindAll()
                camera = provider.bindToLifecycle(
                    this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis
                )
                // 每次打开复位：变焦回到 1x，竖条位置由同一映射反推，不记忆上次。
                resetZoomSlider()
            },
            ContextCompat.getMainExecutor(this)
        )
    }

    private fun onQrs(texts: List<String>) {
        runOnUiThread {
            for (text in texts) {
                handleText(text)
            }
        }
    }

    private fun handleText(text: String) {
        if (gridOpen) return
        val frame = parseFrame(text)
        if (frame == null) {
            // 无头：普通单码，进方格页（单格，扫码进自动复制全文）。
            saveToHistory(text)
            openSegments(SegmentActivity.MODE_SCAN, text)
            return
        }
        if (frame.k < 1 || frame.k > 4096 || frame.blockLen < 1 || frame.totalLen < 1) {
            return
        }
        val cur = decoder
        if (cur == null || cur.sessionId != frame.sessionId ||
            cur.k != frame.k || cur.blockLen != frame.blockLen ||
            cur.totalLen != frame.totalLen
        ) {
            decoder = FountainDecoder(
                frame.k, frame.blockLen, frame.sessionId, frame.totalLen, frame.payloadFnv
            )
        }
        decoder?.addFrame(frame.seq, frame.block)
        val d = decoder ?: return
        if (d.isComplete) {
            val bytes = d.assemble()
            decoder = null
            if (bytes != null) {
                val full = String(bytes, Charsets.UTF_8)
                saveToHistory(full)
                openSegments(SegmentActivity.MODE_SCAN, full)
            } else {
                statusText.text = "校验失败，请重扫"
            }
        } else {
            statusText.text = "已收 " + d.solvedCount + "/" + d.k + " 块，继续对准屏幕"
        }
    }

    private fun openSegments(mode: String, text: String) {
        // 结果一律进方格页：超长文本走内存中转，不走 Intent（防 Binder 爆）。
        ResultHolder.text = text
        gridOpen = true
        startActivity(
            Intent(this, SegmentActivity::class.java)
                .putExtra(SegmentActivity.EXTRA_MODE, mode)
        )
    }

    override fun onResume() {
        super.onResume()
        // 从方格页回来：清掉压住的守卫，继续扫；历史进的则重开历史列表。
        gridOpen = false
        if (returnToHistory) {
            returnToHistory = false
            showHistory()
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.history_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_history -> {
                showHistory()
                true
            }
            R.id.action_exit -> {
                finish()
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun saveToHistory(text: String) {
        // 最近 30 次，新在前。存坏了就静默跳过，不挡扫码主流程。
        // 单条上限 60000 字：prefs 无硬限制但 XML 过大会卡顿，超了截断打标记。
        val capped = if (text.length > 60000) text.take(60000) + "…（过长已截断）" else text
        try {
            val prefs = getSharedPreferences("scan_history", Context.MODE_PRIVATE)
            val old = try {
                org.json.JSONArray(prefs.getString("items", "[]"))
            } catch (e: Exception) {
                org.json.JSONArray()
            }
            val next = org.json.JSONArray()
            next.put(org.json.JSONObject().put("t", capped).put("ts", System.currentTimeMillis()))
            for (i in 0 until minOf(old.length(), 29)) {
                next.put(old.get(i))
            }
            prefs.edit().putString("items", next.toString()).apply()
        } catch (e: Exception) {
        }
    }

    private fun loadHistory(): List<Pair<String, Long>> {
        return try {
            val prefs = getSharedPreferences("scan_history", Context.MODE_PRIVATE)
            val arr = org.json.JSONArray(prefs.getString("items", "[]"))
            val out = mutableListOf<Pair<String, Long>>()
            for (i in 0 until minOf(arr.length(), 30)) {
                val obj = arr.getJSONObject(i)
                out.add(obj.getString("t") to obj.getLong("ts"))
            }
            out
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun showHistory() {
        val items = loadHistory()
        if (items.isEmpty()) {
            Toast.makeText(this, R.string.history_empty, Toast.LENGTH_SHORT).show()
            return
        }
        val previews = items.map { (text, ts) ->
            val date = java.text.SimpleDateFormat(
                "MM-dd HH:mm", java.util.Locale.getDefault()
            ).format(java.util.Date(ts))
            val head = if (text.length > 20) text.take(20) + "…" else text
            "$date · ${text.length}字 · $head"
        }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle(R.string.history_title)
            .setItems(previews) { _, which ->
                returnToHistory = true
                openSegments(SegmentActivity.MODE_HISTORY, items[which].first)
            }
            .setNegativeButton(R.string.btn_close, null)
            .show()
    }

    private fun parseFrame(text: String): FrameHeader? {
        if (!text.startsWith("PYQRF1:")) return null
        val parts = text.split(":")
        if (parts.size != 8) return null
        return try {
            val block = Base64.decode(parts[7], Base64.NO_WRAP)
            if (block.size.toInt() != parts[4].toInt()) return null
            FrameHeader(
                parts[1].toInt(16),
                parts[2].toLong(),
                parts[3].toInt(),
                parts[4].toInt(),
                parts[5].toInt(),
                parts[6].toLong(16),
                block,
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun resetZoomSlider() {
        // 复位唯一出口：先设 1x，再把滑条拨到 1x 对应的刻度。
        // 这样 minZoomRatio 不是 1（如 0.6 广角）的机型也不会出现条位与实际脱节。
        val cam = camera
        if (cam == null) {
            zoomBar.progress = 0
            return
        }
        cam.cameraControl.setZoomRatio(1f)
        val state = cam.cameraInfo.zoomState.value
        if (state == null) {
            zoomBar.progress = 0
            return
        }
        val span = state.maxZoomRatio - state.minZoomRatio
        val pos = if (span > 0f) (1f - state.minZoomRatio) / span * 100f else 0f
        zoomBar.progress = pos.toInt().coerceIn(0, 100)
    }

    private fun applySliderZoom(progress: Int) {
        // 浮动竖条：往上拖 progress 变大 -> 拉近。按相机实际最大倍率线性映射。
        val cam = camera ?: return
        val state = cam.cameraInfo.zoomState.value ?: return
        val ratio = state.minZoomRatio +
            (progress / 100f) * (state.maxZoomRatio - state.minZoomRatio)
        cam.cameraControl.setZoomRatio(ratio)
    }

    private inner class QrAnalyzer(
        private val onResult: (List<String>) -> Unit,
    ) : ImageAnalysis.Analyzer {
        private val reader = BarcodeReader()

        @ExperimentalGetImage
        override fun analyze(imageProxy: ImageProxy) {
            val texts = imageProxy.use { proxy ->
                try {
                    reader.read(proxy).mapNotNull { it.text }
                } catch (e: Exception) {
                    emptyList()
                }
            }
            if (texts.isNotEmpty()) {
                onResult(texts)
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
    }
}