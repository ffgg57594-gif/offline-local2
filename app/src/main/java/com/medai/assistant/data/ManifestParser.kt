package com.medai.assistant.data

import com.medai.assistant.Patterns

data class ManifestAsset(
    val name: String,
    val size: Long,
    val sha256: String
)

data class ManifestData(
    val chunkCount: Int,
    val chunkTextsSha256: String,
    val assets: List<ManifestAsset>
)

object ManifestParser {
    fun parse(jsonString: String): ManifestData {
        // Pure Kotlin JSON parser for standard manifests without android.os/org.json JVM stub issues
        val chunkCount = Patterns.MANIFEST_CHUNK_COUNT.find(jsonString)?.groupValues?.get(1)?.toInt() ?: 0
        val chunkTextsSha256 = Patterns.MANIFEST_CHUNK_TEXT_SHA.find(jsonString)?.groupValues?.get(1) ?: ""

        val assets = mutableListOf<ManifestAsset>()
        // Match each asset block: { "name": ..., "size": ..., "sha256": ... }
        Patterns.MANIFEST_ASSET_BLOCK.findAll(jsonString).forEach { match ->
            val name = match.groupValues[1]
            val size = match.groupValues[2].toLong()
            val sha256 = match.groupValues[3]
            assets.add(ManifestAsset(name, size, sha256))
        }

        return ManifestData(chunkCount, chunkTextsSha256, assets)
    }

    fun serialize(chunkCount: Int, chunkTextsSha256: String, assets: List<ManifestAsset>): String {
        val sb = StringBuilder()
        sb.append("{\n")
        sb.append("  \"chunk_count\": $chunkCount,\n")
        sb.append("  \"chunk_texts_sha256\": \"$chunkTextsSha256\",\n")
        sb.append("  \"assets\": [\n")
        assets.forEachIndexed { index, a ->
            sb.append("    {\n")
            sb.append("      \"name\": \"${a.name}\",\n")
            sb.append("      \"size\": ${a.size},\n")
            sb.append("      \"sha256\": \"${a.sha256}\"\n")
            sb.append(if (index < assets.size - 1) "    },\n" else "    }\n")
        }
        sb.append("  ]\n")
        sb.append("}\n")
        return sb.toString()
    }
}
