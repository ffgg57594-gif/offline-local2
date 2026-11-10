import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.medai.assistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.medai.assistant"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += "arm64-v8a" }
        // K7a: llama.cpp JNI bridge. arm64-v8a is built for release
        // (ARMv8.2-A + dotprod flags live in the CMake file); debug also
        // builds x86_64 for the emulator via the debug abiFilters below.
        externalNativeBuild {
            cmake {
                path = file("src/main/cpp/CMakeLists.txt")
                version = "3.22.1"
            }
        }
        val buildTimeUtc = SimpleDateFormat(
            "yyyy-MM-dd'T'HH:mm:ss'Z'",
            Locale.ROOT
        ).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date())
        buildConfigField("String", "BUILD_TIME", "\"$buildTimeUtc\"")
    }

    signingConfigs {
        create("release") {
            val ks = System.getenv("KEYSTORE_PATH")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        debug {
            // Instrumented tests run on an x86_64 API 34 emulator. Release
            // stays arm64-v8a only through defaultConfig above.
            ndk {
                abiFilters.clear()
                abiFilters.addAll(listOf("arm64-v8a", "x86_64"))
            }
        }
        release {
            // Keep the shipped APK arm64-v8a only even though debug adds x86_64.
            ndk {
                abiFilters.clear()
                abiFilters.add("arm64-v8a")
            }
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures { compose = true; buildConfig = true }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    packaging { jniLibs { useLegacyPackaging = true } }
    androidResources { ignoreAssetsPattern = "!books:!models/embedder/tokenizer.json" }

    androidResources { noCompress += listOf("gguf", "onnx", "db", "bin", "traineddata") }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.2")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.material3)
    implementation("androidx.compose.material:material-icons-core")
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")
    // SQLite Android Bindings: FTS5 + porter tokenizer on device.
    implementation("mil.nga:sqlite-android:3450200")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
    testImplementation("org.xerial:sqlite-jdbc:3.45.3.0")
    testImplementation("com.microsoft.onnxruntime:onnxruntime:1.18.0")

    // K4d device (emulator) parity suite.
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test:rules:1.6.1")
    // K5b Compose UI tests on the emulator.
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.compose.ui:ui-test-manifest")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
