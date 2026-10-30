#include <jni.h>
#include <string>
extern "C" JNIEXPORT jstring JNICALL
Java_com_offlinemedical_chat_ml_LlamaEngine_nativeHello(JNIEnv* env, jobject) {
    return env->NewStringUTF("llama_jni ready");
}
