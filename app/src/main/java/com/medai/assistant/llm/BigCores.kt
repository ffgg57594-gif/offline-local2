package com.medai.assistant.llm

import java.io.File

/**
 * K7a: counts the "big" CPU cores from /sys cpufreq as the default thread
 * count for llama.cpp. A core is big when its max frequency is at least
 * 80% of the highest max frequency on the device; falls back to 4 when
 * cpufreq is not readable (e.g. the x86_64 emulator).
 */
object BigCores {

    const val FALLBACK = 4

    fun count(): Int {
        val cpuDir = File("/sys/devices/system/cpu")
        val cpus = cpuDir.listFiles { file ->
            file.isDirectory && file.name.matches(Regex("cpu\\d+"))
        } ?: return FALLBACK
        val freqs = cpus.mapNotNull { cpu ->
            runCatching {
                File(cpu, "cpufreq/cpuinfo_max_freq").readText().trim().toLongOrNull()
            }.getOrNull()
        }
        if (freqs.isEmpty()) return FALLBACK
        val highest = freqs.max()
        if (highest <= 0) return FALLBACK
        val big = freqs.count { it >= highest * 8 / 10 }
        return if (big in 1..MAX_THREADS) big else FALLBACK
    }

    private const val MAX_THREADS = 8
}
