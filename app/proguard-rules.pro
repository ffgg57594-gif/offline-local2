# Keep rules for release build
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**
# SQLite Android Bindings (FTS5 on-device gate)
-keep class org.sqlite.** { *; }
-dontwarn org.sqlite.**
# K7a: llama.cpp JNI bridge. The native code in llama_jni.cpp looks these
# classes and methods up by exact name, so R8 must not rename or strip them.
-keep class com.medai.assistant.llm.LlamaBridge { *; }
-keep class com.medai.assistant.llm.LlamaBridge$TokenSink { *; }
-keep class com.medai.assistant.llm.LlamaBridge$LoadProgressListener { *; }
-keep class * implements com.medai.assistant.llm.LlamaBridge$TokenSink
-keep class * implements com.medai.assistant.llm.LlamaBridge$LoadProgressListener
-keep class com.medai.assistant.llm.LlamaEngine { *; }
-keep class com.medai.assistant.llm.LlamaEngine$* { *; }
