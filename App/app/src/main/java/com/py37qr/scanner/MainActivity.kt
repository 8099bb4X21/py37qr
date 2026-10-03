package com.py37qr.scanner

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Bundle
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

    // 本轮收集：序号 -> 正文；expectedTotal 为 null 表示还没进入多码会话。
    private val parts = LinkedHashMap<Int, String>()
    private var expectedTotal: Int? = null

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
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
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
        } else {
            statusText.text = "已扫 " + parts.size + "/" + total + "，继续对准剩余码"
        }
    }

    private fun showResult(text: String, total: Int) {
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
        // 用途：“全屏识别”按钮入口，拍最高分辨率静帧走 ZXing 整图多解。
        // 实时流分辨率有限，四码同屏时每个码像素不够，这是兜底的主力路径。
        if (!::imageCapture.isInitialized) {
            return
        }
        statusText.setText(R.string.capture_working)
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
        // 逐个喂给现有归组拼合逻辑（与实时流同一入口，结果行为一致）。
        // 微信引擎自带 CNN 检测 + 小码超分，同屏多码、远小码都归它管。
        try {
            if (!wechatReady.get()) {
                runOnUiThread { statusText.text = "微信引擎初始化中，稍后再拍" }
                return
            }
            val buffer = image.planes[0].buffer
            val bytes = ByteArray(buffer.remaining())
            buffer.get(bytes)
            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            if (bitmap == null) {
                runOnUiThread { statusText.setText(R.string.capture_none) }
                return
            }
            val results = try {
                WeChatQRCodeDetector.detectAndDecode(bitmap)
            } catch (e: Exception) {
                emptyList<String>()
            }
            runOnUiThread {
                if (results.isEmpty()) {
                    statusText.setText(R.string.capture_none)
                } else {
                    for (text in results) {
                        handleValue(text)
                    }
                }
            }
        } finally {
            image.close()
        }
    }

    private inner class QrAnalyzer(
        private val onResult: (List<String>) -> Unit
    ) : ImageAnalysis.Analyzer {

        @ExperimentalGetImage
        override fun analyze(imageProxy: ImageProxy) {
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
