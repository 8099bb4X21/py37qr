package com.py37qr.scanner

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Base64
import android.util.Size
import android.view.Menu
import android.view.MenuItem
import android.widget.SeekBar
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
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
        // 只有从方格页回来才重设：首次启动 camera 还没 bind，守卫里会空过。
        // 原因：部分机型在 pause/resume 后不保留变焦，代码里又没有任何路径设最大值，
        // 与其猜机型行为，不如每次回来按滑条显式对齐一次，结果恒等于滑条。
        val wasGrid = gridOpen
        gridOpen = false
        if (wasGrid) {
            applySliderZoom(zoomBar.progress)
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.history_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_history -> {
                startActivity(Intent(this, HistoryActivity::class.java))
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
        HistoryStore.save(this, text)
    }

    private fun parseFrame(text: String): FrameHeader? {
        if (!text.startsWith("PYQRF1:")) return null
        val parts = text.split(":")
        if (parts.size != 8) return null
        return try {
            val block = Base64.decode(parts[7], Base64.NO_WRAP)
            val sessionId = parts[1].toInt(16)
            val seq = parts[2].toLong()
            val k = parts[3].toInt()
            val blockLen = parts[4].toInt()
            val totalLen = parts[5].toInt()
            val fnv = parts[6].toLong(16)
            // 防御 crafted 帧：负 seq 会让解码数组越界崩溃，
            // 超大 totalLen 会在 assemble() 里 OOM；合法帧恒满足以下约束。
            if (seq < 0 || k < 1 || k > 4096) return null
            if (blockLen < 1 || blockLen > 4096) return null
            if (totalLen < 1 || totalLen > 8 * 1024 * 1024) return null
            if (totalLen > blockLen.toLong() * k) return null
            if (block.size != blockLen) return null
            FrameHeader(sessionId, seq, k, blockLen, totalLen, fnv, block)
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