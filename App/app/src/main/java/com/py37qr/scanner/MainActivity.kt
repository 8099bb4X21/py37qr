package com.py37qr.scanner

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Size
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.king.wechat.qrcode.WeChatQRCodeDetector
import org.opencv.OpenCV
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

// 与 PC 端 qr_converter.py 的拼接协议一致：PY37QR:序号/总数:正文。
// 单码无头（即全文），多码按序号排序拼合。
private val HEADER_REGEX = Regex("^PY37QR:(\\d+)/(\\d+):([\\s\\S]*)$")

class MainActivity : AppCompatActivity() {

    private lateinit var cameraExecutor: ExecutorService
    private lateinit var scanner: BarcodeScanner
    private lateinit var previewView: PreviewView
    private lateinit var statusText: TextView
    private lateinit var imageCapture: ImageCapture

    private var scanningEnabled = true
    private var dialogShowing = false
    private val wechatReady = AtomicBoolean(false)

    private val autoCaptureHandler = Handler(Looper.getMainLooper())
    @Volatile private var scanMode = MODE_NORMAL
    private var autoCaptureCount = 0

    // 本轮收集：序号 -> 正文；expectedTotal 为 null 表示还没进入多码会话。
    private val parts = LinkedHashMap<Int, String>()
    private var expectedTotal: Int? = null

    companion object {
        private const val MODE_NORMAL = 0
        private const val MODE_MULTI = 1
        private const val AUTO_CAPTURE_MAX = 20
    }

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
        findViewById<Button>(R.id.captureButton).setOnClickListener {
            captureFullFrame()
        }

        // 只扫 QR；auto-zoom 在 GmsBarcodeScanner 整屏 API 上，
        // 低阶 BarcodeScannerOptions 并没有该方法，不用它。
        val options = BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build()
        scanner = BarcodeScanning.getClient(options)
        cameraExecutor = Executors.newSingleThreadExecutor()

        // 微信引擎初始化放后台：拷模型 + 加载 .so 要几秒，不能卡启动。
        cameraExecutor.execute {
            try {
                if (OpenCV.initOpenCV()) {
                    WeChatQRCodeDetector.init(this@MainActivity)
                    wechatReady.set(true)
                }
            } catch (e: Exception) {
                wechatReady.set(false)
            }
        }

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
                // 分析流提到 1280x720：码多同屏时每个码分到的像素才够解。
                val analysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(1280, 720))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build().also {
                        it.setAnalyzer(cameraExecutor, QrAnalyzer(::onQrs))
                    }
                imageCapture = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                    .build()
                provider.unbindAll()
                provider.bindToLifecycle(
                    this, CameraSelector.DEFAULT_BACK_CAMERA,
                    preview, analysis, imageCapture
                )
            },
            ContextCompat.getMainExecutor(this)
        )
    }

    private fun onQrs(values: List<String>) {
        // 分析线程回调，切回主线程再碰界面与会话状态。
        runOnUiThread {
            for (value in values) {
                handleValue(value)
            }
        }
    }

    private fun handleValue(raw: String) {
        if (!scanningEnabled || dialogShowing) {
            return
        }
        val parsed = parseHeader(raw)
        if (parsed == null) {
            // 无头即单码：直接弹结果。
            showResult(raw, 1)
            return
        }
        val (index, total, body) = parsed
        if (total < 1 || total > 99 || index < 1 || index > total) {
            return
        }
        if (expectedTotal != null && expectedTotal != total) {
            // 混入另一组码：以新码为准重开一轮，避免两组内容拼串。
            parts.clear()
        }
        expectedTotal = total
        parts[index] = body
        if (parts.size >= total) {
            val full = (1..total).joinToString("") { parts[it] ?: "" }
            showResult(full, total)
        } else if (scanMode == MODE_NORMAL) {
            // 扫到带序号头的码但还没集齐：进入多码模式，
            // 自动连拍补全剩余码，不用再手点按钮。
            enterMultiMode()
        } else {
            statusText.text = "已扫 " + parts.size + "/" + total + "，自动识别剩余中…"
        }
    }

    private fun enterMultiMode() {
        scanMode = MODE_MULTI
        autoCaptureCount = 0
        statusText.text = "已扫 " + parts.size + "/" + expectedTotal + "，自动识别中…"
        // 先立即拍一张，之后靠 decodeFullFrame 尾部按需续拍。
        scheduleAutoCapture(0)
    }

    private fun exitMultiMode(hint: String) {
        scanMode = MODE_NORMAL
        autoCaptureHandler.removeCallbacksAndMessages(null)
        statusText.text = hint
    }

    private fun stopAutoCapture() {
        autoCaptureHandler.removeCallbacksAndMessages(null)
    }

    private fun scheduleAutoCapture(delayMs: Long) {
        // 用途：节流调度下一张，避免连拍过快吃满相机管线。
        if (delayMs <= 0) {
            autoCaptureHandler.post { runAutoCaptureStep() }
        } else {
            autoCaptureHandler.postDelayed({ runAutoCaptureStep() }, delayMs)
        }
    }

    private fun runAutoCaptureStep() {
        if (scanMode != MODE_MULTI || dialogShowing) {
            return
        }
        autoCaptureCount++
        if (autoCaptureCount > AUTO_CAPTURE_MAX) {
            exitMultiMode("仍未扫齐，请靠近后重试或点“全屏识别”")
            return
        }
        if (!wechatReady.get()) {
            statusText.text = "识别引擎初始化中…"
            scheduleAutoCapture(1000)
            return
        }
        takePictureAndDecode()
    }

    private fun showResult(text: String, total: Int) {
        stopAutoCapture()
        scanMode = MODE_NORMAL
        scanningEnabled = false
        dialogShowing = true
        val title = "成功识别 " + text.length + " 字（共 " + total + " 个码）"
        // 弹框只给前 20 字预览，多了放不下；复制走的仍是全文。
        val preview = if (text.length > 20) text.take(20) + "…" else text
        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(preview)
            .setCancelable(false)
            .setPositiveButton(R.string.btn_copy) { _, _ ->
                copyText(text)
                resetSession("已复制，继续对准下一个")
            }
            .setNegativeButton(R.string.btn_continue) { _, _ ->
                resetSession("继续扫描")
            }
            .show()
    }

    private fun resetSession(hint: String) {
        stopAutoCapture()
        scanMode = MODE_NORMAL
        parts.clear()
        expectedTotal = null
        dialogShowing = false
        scanningEnabled = true
        statusText.text = hint
    }

    private fun copyText(text: String) {
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        manager.setPrimaryClip(ClipData.newPlainText("py37qr", text))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }

    private fun parseHeader(raw: String): Triple<Int, Int, String>? {
        val match = HEADER_REGEX.matchEntire(raw) ?: return null
        return Triple(
            match.groupValues[1].toInt(),
            match.groupValues[2].toInt(),
            match.groupValues[3]
        )
    }

    private fun captureFullFrame() {
        // 用途：“全屏识别”按钮入口，手动补拍一张（多码模式下也会自动连拍，按钮作兜底）。
        statusText.setText(R.string.capture_working)
        takePictureAndDecode()
    }

    private fun takePictureAndDecode() {
        if (!::imageCapture.isInitialized) {
            return
        }
        imageCapture.takePicture(
            cameraExecutor,
            object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    decodeFullFrame(image)
                }

                override fun onError(exception: ImageCaptureException) {
                    runOnUiThread {
                        statusText.text = "拍照失败：" + exception.message
                    }
                }
            }
        )
    }

    private fun decodeFullFrame(image: ImageProxy) {
        // 用途：后台线程把整帧 JPEG 解成位图，微信引擎一次找出所有码，
        // 逐个喂给归组拼合逻辑（与实时流同一入口，结果行为一致）。
        // 微信引擎自带 CNN 检测 + 小码超分，同屏多码、远小码都归它管。
        try {
            if (!wechatReady.get()) {
                runOnUiThread { statusText.text = "识别引擎初始化中…" }
                return
            }
            val buffer = image.planes[0].buffer
            val bytes = ByteArray(buffer.remaining())
            buffer.get(bytes)
            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            if (bitmap == null) {
                runOnUiThread { onDecodeFinished(emptyList()) }
                return
            }
            val results = try {
                WeChatQRCodeDetector.detectAndDecode(bitmap)
            } catch (e: Exception) {
                emptyList<String>()
            }
            runOnUiThread { onDecodeFinished(results) }
        } finally {
            image.close()
        }
    }

    private fun onDecodeFinished(results: List<String>) {
        // 用途：解码结果落袋后，决定是否继续自动连拍。
        if (results.isNotEmpty()) {
            for (text in results) {
                handleValue(text)
            }
        }
        if (scanMode == MODE_MULTI && !dialogShowing) {
            // 仍未集齐：稍等再拍下一张，形成“自动识别剩余码”的闭环。
            statusText.text = "已扫 " + parts.size + "/" + expectedTotal + "，自动识别中…"
            scheduleAutoCapture(800)
        } else if (results.isEmpty() && scanMode == MODE_NORMAL && !dialogShowing) {
            statusText.setText(R.string.capture_none)
        }
    }

    private inner class QrAnalyzer(
        private val onResult: (List<String>) -> Unit
    ) : ImageAnalysis.Analyzer {

        @ExperimentalGetImage
        override fun analyze(imageProxy: ImageProxy) {
            // 多码模式靠微信引擎连拍补全，这里停 ML Kit 省电，也避免单码弹窗抢戏。
            if (scanMode != MODE_NORMAL) {
                imageProxy.close()
                return
            }
            val mediaImage = imageProxy.image
            if (mediaImage == null) {
                imageProxy.close()
                return
            }
            val input = InputImage.fromMediaImage(
                mediaImage, imageProxy.imageInfo.rotationDegrees
            )
            scanner.process(input)
                .addOnSuccessListener { barcodes ->
                    val values = barcodes.mapNotNull { it.rawValue }
                    if (values.isNotEmpty()) {
                        onResult(values)
                    }
                }
                .addOnCompleteListener {
                    imageProxy.close()
                }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        scanner.close()
    }
}
