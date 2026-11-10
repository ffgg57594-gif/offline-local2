package com.medai.assistant.llm

import java.io.File
import java.io.InputStream
import java.security.MessageDigest

/** K7a: streaming sha256 helpers used to verify every downloaded model. */
object Sha256Util {

    private const val BUFFER = 1 shl 20

    fun digestStream(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(BUFFER)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
        return hex(digest.digest())
    }

    fun digestFile(file: File): String {
        file.inputStream().use { digestStream(it) }
    }

    fun digestBytes(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        return hex(digest.digest(bytes))
    }

    fun isValidSha256(value: String): Boolean = value.matches(Regex("[0-9a-f]{64}"))

    private fun hex(bytes: ByteArray): String {
        val sb = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            sb.append("0123456789abcdef"[v ushr 4])
            sb.append("0123456789abcdef"[v and 0x0F])
        }
        return sb.toString()
    }
}
