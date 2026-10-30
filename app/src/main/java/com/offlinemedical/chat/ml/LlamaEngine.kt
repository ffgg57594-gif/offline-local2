package com.offlinemedical.chat.ml

class LlamaEngine {
    external fun nativeHello(): String
    companion object { init { System.loadLibrary("llama_jni") } }
}
