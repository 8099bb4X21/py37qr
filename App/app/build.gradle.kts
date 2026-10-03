plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.py37qr.scanner"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.py37qr.scanner"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        ndk {
            // 只留 arm64-v8a：微信引擎 .so 按架构分包，全留 APK 体积爆炸。
            abiFilters += "arm64-v8a"
        }
    }

    // 签名配置与《云编译/签名密钥配置说明.md》同一套密钥（别名 mykey）。
    // 密钥本身只存在 GitHub Secrets，绝不进仓库；本地无密钥时跳过签名。
    val keystoreFile = project.findProperty("KEYSTORE_FILE")?.toString()
    signingConfigs {
        create("release") {
            if (keystoreFile != null) {
                storeFile = file(keystoreFile)
                storePassword = project.findProperty("KEYSTORE_PASSWORD")?.toString()
                keyAlias = project.findProperty("KEY_ALIAS")?.toString()
                keyPassword = project.findProperty("KEY_PASSWORD")?.toString()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // CI 在 gradle.properties 里注入 KEYSTORE_* 后才签名，
            // 本地没有密钥时保持不签名也能编过（产物为 unsigned 包）。
            if (keystoreFile != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // ML Kit bundled 模型：打包进 APK，完全离线可用，无需 Play 服务。
    // 17.3.0 起含 auto-zoom（远码自动提示变焦），见 MainActivity。
    implementation("com.google.mlkit:barcode-scanning:17.3.0")

    // 微信扫码引擎（OpenCV 移植）：CNN 多码检测 + 小码超分，一次可出多个结果。
    // MavenCentral 坐标，2.6.0 要求 compileSdk>=34（我们就是 34）。
    implementation("com.github.jenly1314.WeChatQRCode:opencv:2.6.0")
    implementation("com.github.jenly1314.WeChatQRCode:opencv-armv64:2.6.0")
    implementation("com.github.jenly1314.WeChatQRCode:wechat-qrcode:2.6.0")

    val cameraxVersion = "1.3.4"
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")
}
