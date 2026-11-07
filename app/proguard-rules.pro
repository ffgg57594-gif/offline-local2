# Keep rules for release build
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**
# SQLite Android Bindings (FTS5 on-device gate)
-keep class org.sqlite.** { *; }
-dontwarn org.sqlite.**
