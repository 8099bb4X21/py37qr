plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.py37qr.scanner"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.py37qr.scanner"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        ndk {
            // 只打包 arm64-v8a：现代手机标准架构，减体积；zxing-cpp aar 的多架构 .so 只留这一份。
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

    // zxing-cpp 官方 Android wrapper：C++ 解码引擎，快、零 Google、离线可用，
    // 直接吃 CameraX ImageProxy，返回 .text/.bytes。decimen 同款引擎。
    implementation("io.github.zxing-cpp:android:3.1.1")

    val cameraxVersion = "1.3.4"
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")
}
