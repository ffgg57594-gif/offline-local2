// K7a: JNI bridge between Kotlin (com.medai.assistant.llm.LlamaBridge) and
// the llama.cpp submodule pinned in external/llama.cpp.
//
// Sampling is fixed and deterministic: greedy with repeat_penalty 1.1
// (last 64 tokens) and top_p 0.1, using the model's own chat template
// (ChatML for Qwen GGUF files; models without a template get the raw
// prompt). Models are mmapped. All long work happens on the caller's
// thread, which the Kotlin side confines to one dedicated engine thread.

#include <jni.h>
#include <android/log.h>

#include "llama.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#define TAG "llama_jni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

namespace {

struct EngineHandle {
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    std::mutex mutex;
    std::atomic<bool> cancelled{false};
    uint32_t n_batch = 256;

    // Stats of the last generate call on this handle.
    int prompt_tokens = 0;
    int output_tokens = 0;
    double ttft_ms = 0.0;
    double total_ms = 0.0;
    double tokens_per_second = 0.0;

    std::string model_info_json;
};

std::once_flag backend_once;

void ensure_backend() {
    std::call_once(backend_once, []() { llama_backend_init(); });
}

double now_ms() {
    using clock = std::chrono::steady_clock;
    return std::chrono::duration<double, std::milli>(
               clock::now().time_since_epoch())
        .count();
}

std::string json_escape(const std::string & in) {
    std::string out;
    out.reserve(in.size());
    for (char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if ((unsigned char) c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

bool progress_thunk(float progress, void * user_data) {
    auto * data = static_cast<std::pair<JNIEnv *, jobject> *>(user_data);
    JNIEnv * env = data->first;
    jobject listener = data->second;
    jmethodID method = env->GetMethodID(
        env->GetObjectClass(listener), "onProgress", "(F)Z");
    if (method == nullptr) {
        env->ExceptionClear();
        return true;
    }
    jboolean keep = env->CallBooleanMethod(listener, method, (jfloat) progress);
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
        return true;
    }
    return keep == JNI_TRUE;
}

jstring to_jstring(JNIEnv * env, const std::string & text) {
    return env->NewStringUTF(text.c_str());
}

} // namespace

extern "C" {

JNIEXPORT jlong JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeLoad(
        JNIEnv * env, jobject /*thiz*/, jstring j_path, jint j_n_ctx,
        jint j_n_batch, jint j_n_threads, jobject j_progress) {
    const char * path = env->GetStringUTFChars(j_path, nullptr);
    std::string path_str(path);
    env->ReleaseStringUTFChars(j_path, path);

    ensure_backend();

    auto * handle = new (std::nothrow) EngineHandle();
    if (handle == nullptr) {
        return 0;
    }

    llama_model_params mparams = llama_model_default_params();
    mparams.load_mode = LLAMA_LOAD_MODE_MMAP; // use_mmap = true
    mparams.n_gpu_layers = 0;                  // CPU only
    std::pair<JNIEnv *, jobject> progress_data{env, j_progress};
    if (j_progress != nullptr) {
        mparams.progress_callback = &progress_thunk;
        mparams.progress_callback_user_data = &progress_data;
    }

    handle->model = llama_model_load_from_file(path_str.c_str(), mparams);
    if (handle->model == nullptr) {
        LOGE("llama_model_load_from_file failed for %s", path_str.c_str());
        delete handle;
        return 0;
    }

    llama_context_params cparams = llama_context_default_params();
    const int32_t n_ctx_train = llama_model_n_ctx_train(handle->model);
    uint32_t n_ctx = (uint32_t) j_n_ctx;
    if (n_ctx_train > 0 && n_ctx > (uint32_t) n_ctx_train) {
        LOGI("requested n_ctx %u > model n_ctx_train %d; clamping",
             n_ctx, n_ctx_train);
        n_ctx = (uint32_t) n_ctx_train;
    }
    cparams.n_ctx = n_ctx;
    cparams.n_batch = (uint32_t) j_n_batch;
    cparams.n_ubatch = (uint32_t) j_n_batch;
    cparams.n_threads = j_n_threads;
    cparams.n_threads_batch = j_n_threads;

    handle->ctx = llama_init_from_model(handle->model, cparams);
    if (handle->ctx == nullptr) {
        LOGE("llama_init_from_model failed (n_ctx=%u n_batch=%u threads=%d)",
             n_ctx, cparams.n_batch, j_n_threads);
        llama_model_free(handle->model);
        delete handle;
        return 0;
    }
    handle->n_batch = cparams.n_batch;

    const llama_vocab * vocab = llama_model_get_vocab(handle->model);
    const char * tmpl = llama_model_chat_template(handle->model, nullptr);
    char desc[256] = {0};
    llama_model_desc(handle->model, desc, sizeof(desc));

    char info[1024];
    snprintf(info, sizeof(info),
             "{\"desc\":\"%s\",\"size_bytes\":%llu,\"n_ctx_train\":%d,"
             "\"n_ctx\":%u,\"n_vocab\":%d,\"has_chat_template\":%s,"
             "\"template\":\"%s\"}",
             json_escape(desc).c_str(),
             (unsigned long long) llama_model_size(handle->model),
             n_ctx_train,
             llama_n_ctx(handle->ctx),
             llama_vocab_n_tokens(vocab),
             (tmpl != nullptr && tmpl[0] != '\0') ? "true" : "false",
             json_escape(tmpl != nullptr ? tmpl : "").c_str());
    handle->model_info_json = info;

    LOGI("loaded %s (n_ctx=%u threads=%d)", path_str.c_str(),
         llama_n_ctx(handle->ctx), j_n_threads);
    return reinterpret_cast<jlong>(handle);
}

JNIEXPORT void JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeFree(
        JNIEnv * /*env*/, jobject /*thiz*/, jlong j_handle) {
    auto * handle = reinterpret_cast<EngineHandle *>(j_handle);
    if (handle == nullptr) {
        return;
    }
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    {
        std::lock_guard<std::mutex> lock(handle->mutex);
        ctx = handle->ctx;
        handle->ctx = nullptr;
        model = handle->model;
        handle->model = nullptr;
    }
    if (ctx != nullptr) {
        llama_free(ctx);
    }
    if (model != nullptr) {
        llama_model_free(model);
    }
    delete handle;
}

JNIEXPORT jboolean JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeGenerate(
        JNIEnv * env, jobject /*thiz*/, jlong j_handle, jstring j_prompt,
        jint j_max_tokens, jobject j_sink) {
    auto * handle = reinterpret_cast<EngineHandle *>(j_handle);
    if (handle == nullptr) {
        return JNI_FALSE;
    }

    std::unique_lock<std::mutex> lock(handle->mutex);
    if (handle->ctx == nullptr) {
        return JNI_FALSE;
    }
    handle->cancelled = false;

    // Reset last-run stats so a bailed-out run never reports stale values.
    handle->prompt_tokens = 0;
    handle->output_tokens = 0;
    handle->ttft_ms = 0.0;
    handle->total_ms = 0.0;
    handle->tokens_per_second = 0.0;

    const double start = now_ms();

    const char * prompt_raw = env->GetStringUTFChars(j_prompt, nullptr);
    std::string prompt_str(prompt_raw);
    env->ReleaseStringUTFChars(j_prompt, prompt_raw);

    const llama_vocab * vocab = llama_model_get_vocab(handle->model);

    // Apply the model's own chat template when it has one.
    const char * tmpl = llama_model_chat_template(handle->model, nullptr);
    const bool has_template = tmpl != nullptr && tmpl[0] != '\0';
    std::string prompt_text;
    if (has_template) {
        std::vector<llama_chat_message> msgs{
            {"user", prompt_str.c_str()}
        };
        const int32_t needed = llama_chat_apply_template(
            tmpl, msgs.data(), (size_t) 1, true, nullptr, 0);
        if (needed > 0) {
            std::vector<char> formatted((size_t) needed + 1);
            const int32_t written = llama_chat_apply_template(
                tmpl, msgs.data(), (size_t) 1, true, formatted.data(),
                (int32_t) formatted.size());
            if (written > 0) {
                prompt_text.assign(formatted.data(), (size_t) written);
            }
        }
    }
    if (prompt_text.empty()) {
        prompt_text = prompt_str;
    }

    // Tokenize (specials like <|im_start|> must parse as single tokens).
    // llama_tokenize's buffer contract in b12236 (common.cpp uses the
    // same idiom): a too-small buffer returns the NEGATED required token
    // count, never the positive one. So start with a generous buffer and
    // retry once at the exact count if it comes back short.
    std::vector<llama_token> tokens(prompt_text.size() + 16);
    int32_t n_prompt = llama_tokenize(
        vocab, prompt_text.c_str(), (int32_t) prompt_text.size(),
        tokens.data(), (int32_t) tokens.size(), false, true);
    if (n_prompt < 0 && n_prompt != std::numeric_limits<int32_t>::min()) {
        tokens.resize((size_t) (-(int64_t) n_prompt));
        n_prompt = llama_tokenize(
            vocab, prompt_text.c_str(), (int32_t) prompt_text.size(),
            tokens.data(), (int32_t) tokens.size(), false, true);
    }
    if (n_prompt <= 0) {
        LOGE("tokenize failed for a %zu-byte prompt (ret=%d)",
             prompt_text.size(), n_prompt);
        return JNI_FALSE;
    }
    LOGI("generate: %d prompt tokens, up to %d output tokens",
         n_prompt, j_max_tokens);
    handle->prompt_tokens = n_prompt;

    // Fresh KV cache for every run.
    llama_memory_t memory = llama_get_memory(handle->ctx);
    llama_memory_seq_rm(memory, 0, -1, -1);

    // Decode the prompt in n_batch-sized chunks. The b12236 batch API
    // tracks positions automatically from the KV cache state, so no
    // explicit pos bookkeeping is needed; sequence 0 is the default.
    const int32_t n_batch = (int32_t) std::min<uint32_t>(handle->n_batch, n_prompt);
    bool decode_failed = false;
    for (int32_t i = 0; i < n_prompt; i += n_batch) {
        const int32_t chunk = std::min<int32_t>(n_batch, n_prompt - i);
        llama_batch batch = llama_batch_get_one(&tokens[(size_t) i], chunk);
        const int32_t ret = llama_decode(handle->ctx, batch);
        if (ret != 0) {
            // 0 = success; 1 = no KV slot (context full); < 0 = fatal.
            decode_failed = true;
            break;
        }
    }

    // Deterministic sampling chain: penalties -> top_p -> greedy.
    llama_sampler_chain_params chain_params = llama_sampler_chain_default_params();
    llama_sampler * chain = llama_sampler_chain_init(chain_params);
    llama_sampler_chain_add(
        chain, llama_sampler_init_penalties(
                    llama_vocab_n_tokens(vocab), 64, 1.1f, 0.0f, 0.0f));
    llama_sampler_chain_add(chain, llama_sampler_init_top_p(0.1f, 1));
    llama_sampler_chain_add(chain, llama_sampler_init_greedy());

    jmethodID on_token = nullptr;
    if (j_sink != nullptr) {
        on_token = env->GetMethodID(
            env->GetObjectClass(j_sink), "onToken", "(Ljava/lang/String;)V");
        if (on_token == nullptr) {
            env->ExceptionClear();
        }
    }

    double first_token_ms = 0.0;
    int generated = 0;
    bool callback_failed = false;

    if (!decode_failed) {
        for (int32_t i = 0; i < j_max_tokens; ++i) {
            if (handle->cancelled) {
                break;
            }
            llama_token token = llama_sampler_sample(chain, handle->ctx, -1);
            if (llama_vocab_is_eog(vocab, token)) {
                break;
            }
            llama_sampler_accept(chain, token);

            char piece[512];
            const int32_t piece_len = llama_token_to_piece(
                vocab, token, piece, (int32_t) sizeof(piece), 0, false);
            if (piece_len > 0 && on_token != nullptr) {
                if (piece_len < (int32_t) sizeof(piece)) {
                    piece[piece_len] = '\0';
                } else {
                    piece[sizeof(piece) - 1] = '\0';
                }
                jstring j_piece = env->NewStringUTF(piece);
                if (j_piece != nullptr) {
                    env->CallVoidMethod(j_sink, on_token, j_piece);
                    env->DeleteLocalRef(j_piece);
                    if (env->ExceptionCheck()) {
                        env->ExceptionClear();
                        callback_failed = true;
                    }
                }
            }
            ++generated;
            if (generated == 1) {
                first_token_ms = now_ms();
            }
            if (callback_failed || handle->cancelled) {
                break;
            }

            llama_batch step = llama_batch_get_one(&token, 1);
            if (llama_decode(handle->ctx, step) != 0) {
                break;
            }
        }
    }

    llama_sampler_free(chain);

    const double end = now_ms();
    handle->output_tokens = generated;
    handle->ttft_ms = generated > 0 ? (first_token_ms - start) : 0.0;
    handle->total_ms = end - start;
    const double gen_ms = generated > 0 ? (end - first_token_ms) : 0.0;
    handle->tokens_per_second =
        (generated > 0 && gen_ms > 0.0)
            ? (generated * 1000.0 / gen_ms)
            : 0.0;

    const bool completed = !handle->cancelled && !decode_failed && !callback_failed;
    return completed ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeCancel(
        JNIEnv * /*env*/, jobject /*thiz*/, jlong j_handle) {
    auto * handle = reinterpret_cast<EngineHandle *>(j_handle);
    if (handle != nullptr) {
        handle->cancelled = true;
    }
}

JNIEXPORT jstring JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeStatsJson(
        JNIEnv * env, jobject /*thiz*/, jlong j_handle) {
    auto * handle = reinterpret_cast<EngineHandle *>(j_handle);
    if (handle == nullptr) {
        return env->NewStringUTF("{}");
    }
    std::lock_guard<std::mutex> lock(handle->mutex);
    char json[512];
    snprintf(json, sizeof(json),
             "{\"prompt_tokens\":%d,\"output_tokens\":%d,\"ttft_ms\":%.2f,"
             "\"total_ms\":%.2f,\"tokens_per_second\":%.2f}",
             handle->prompt_tokens, handle->output_tokens,
             handle->ttft_ms, handle->total_ms, handle->tokens_per_second);
    return env->NewStringUTF(json);
}

JNIEXPORT jstring JNICALL
Java_com_medai_assistant_llm_LlamaBridge_nativeModelInfoJson(
        JNIEnv * env, jobject /*thiz*/, jlong j_handle) {
    auto * handle = reinterpret_cast<EngineHandle *>(j_handle);
    if (handle == nullptr) {
        return env->NewStringUTF("{}");
    }
    std::lock_guard<std::mutex> lock(handle->mutex);
    return env->NewStringUTF(handle->model_info_json.c_str());
}

} // extern "C"
