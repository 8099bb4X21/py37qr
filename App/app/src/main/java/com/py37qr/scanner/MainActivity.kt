package com.py37qr.scanner

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Base64
import android.util.Size
import android.view.GestureDetector
import android.view.MotionEvent
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
import java.util.concurrent.atomic.AtomicBoolean

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
    private var camera: Camera? = null

    private var decoder: FountainDecoder? = null
    private val dialogShowing = AtomicBoolean(false)

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
        previewView = findViewById(R.id.previewView)
        statusText = findViewById(R.id.statusText)
        cameraExecutor = Executors.newSingleThreadExecutor()
        setupZoomGesture()

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
        if (dialogShowing.get()) return
        val frame = parseFrame(text)
        if (frame == null) {
            // 无头：普通单码，直接显示。
            showResult(text, 1)
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
                showResult(String(bytes, Charsets.UTF_8), d.k)
            } else {
                statusText.text = "校验失败，请重扫"
            }
        } else {
            statusText.text = "已收 " + d.solvedCount + "/" + d.k + " 块，继续对准屏幕"
        }
    }

    private fun showResult(text: String, total: Int) {
        if (dialogShowing.get()) return
        dialogShowing.set(true)
        val title = "成功识别 " + text.length + " 字（共 " + total + " 码）"
        val preview = if (text.length > 20) text.take(20) + "…" else text
        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(preview)
            .setCancelable(false)
            .setPositiveButton(R.string.btn_copy) { _, _ ->
                copyText(text)
                resetSession("已复制，继续扫描")
            }
            .setNegativeButton(R.string.btn_continue) { _, _ ->
                resetSession("继续扫描")
            }
            .show()
    }

    private fun resetSession(hint: String) {
        decoder = null
        dialogShowing.set(false)
        statusText.text = hint
    }

    private fun copyText(text: String) {
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        manager.setPrimaryClip(ClipData.newPlainText("py37qr", text))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
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

    private fun setupZoomGesture() {
        val detector = GestureDetector(
            this,
            object : GestureDetector.SimpleOnGestureListener() {
                override fun onScroll(
                    e1: MotionEvent?,
                    e2: MotionEvent,
                    distanceX: Float,
                    distanceY: Float,
                ): Boolean {
                    // 上滑放大，下滑缩小。
                    zoomBy(if (distanceY > 0) -1 else 1)
                    return true
                }
            },
        )
        previewView.setOnTouchListener { _, ev -> detector.onTouchEvent(ev) }
    }

    private fun zoomBy(dir: Int) {
        val cam = camera ?: return
        val state = cam.cameraInfo.zoomState.value ?: return
        val step = 0.2f
        val target = (state.zoomRatio + dir * step)
            .coerceIn(state.minZoomRatio, state.maxZoomRatio)
        cam.cameraControl.setZoomRatio(target)
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