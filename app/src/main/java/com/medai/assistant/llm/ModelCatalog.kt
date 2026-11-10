package com.medai.assistant.llm

import com.medai.assistant.gate.Json
import com.medai.assistant.gate.asArray
import com.medai.assistant.gate.asBoolean
import com.medai.assistant.gate.asInt
import com.medai.assistant.gate.asObject
import com.medai.assistant.gate.asString

/**
 * K7a: one downloadable GGUF model from `assets/model_catalog.json`.
 *
 * Parsing uses the project's minimal JSON parser so the catalog can be
 * validated in JVM unit tests where Android's org.json is a stub.
 */
data class CatalogModel(
    val id: String,
    val displayName: String,
    val fileName: String,
    val repo: String,
    val url: String,
    val sizeBytes: Long,
    val sha256: String,
    val license: String,
    val licenseLine: String,
    val licenseUrl: String,
    val ramEstimateMb: Int,
    val ramEstimateCalc: String,
    val isDefault: Boolean
)

object ModelCatalog {

    fun parse(text: String): List<CatalogModel> {
        val root = Json.parse(text).asObject()
        val version = root["version"]?.asInt()
        require(version == 1) { "Unsupported model catalog version: $version" }
        val models = root["models"]?.asArray()
            ?: error("model catalog is missing the 'models' array")
        require(models.isNotEmpty()) { "model catalog contains no models" }
        val parsed = models.mapIndexed { index, entry ->
            val obj = entry.asObject()
            val model = CatalogModel(
                id = obj.getString("id"),
                displayName = obj.getString("display_name"),
                fileName = obj.getString("file_name"),
                repo = obj.getString("repo"),
                url = obj.getString("url"),
                sizeBytes = obj.getLong("size_bytes"),
                sha256 = obj.getString("sha256"),
                license = obj.getString("license"),
                licenseLine = obj.getString("license_line"),
                licenseUrl = obj.getString("license_url"),
                ramEstimateMb = obj.getInt("ram_estimate_mb"),
                ramEstimateCalc = obj.getString("ram_estimate_calc"),
                isDefault = obj["default"]?.asBoolean() ?: false
            )
            require(model.id.matches(Regex("[a-z0-9._-]+"))) {
                "catalog entry ${index}: invalid id '${model.id}'"
            }
            require(model.fileName.endsWith(".gguf")) {
                "catalog entry ${model.id}: file_name must end with .gguf"
            }
            require(model.url.startsWith("https://")) {
                "catalog entry ${model.id}: url must be HTTPS, got ${model.url}"
            }
            require(model.url == "https://huggingface.co/${model.repo}/resolve/main/${model.fileName}") {
                "catalog entry ${model.id}: url is not the pinned resolve/main link for ${model.repo}"
            }
            require(model.sizeBytes > 0) {
                "catalog entry ${model.id}: size_bytes must be positive"
            }
            require(model.sha256.matches(Regex("[0-9a-f]{64}"))) {
                "catalog entry ${model.id}: sha256 must be 64 lowercase hex chars"
            }
            require(model.ramEstimateMb > 0) {
                "catalog entry ${model.id}: ram_estimate_mb must be positive"
            }
            require(model.license.isNotBlank()) {
                "catalog entry ${model.id}: license must not be blank"
            }
            model
        }
        val ids = parsed.map { it.id }
        require(ids.size == ids.toSet().size) { "duplicate model ids in catalog" }
        require(parsed.count { it.isDefault } == 1) { "catalog must mark exactly one default model" }
        return parsed
    }

    private fun Map<String, com.medai.assistant.gate.JsonValue>.getString(key: String): String {
        val value = this[key] ?: error("catalog entry is missing '$key'")
        return value.asString()
    }

    private fun Map<String, com.medai.assistant.gate.JsonValue>.getInt(key: String): Int {
        val value = this[key] ?: error("catalog entry is missing '$key'")
        return value.asInt()
    }

    private fun Map<String, com.medai.assistant.gate.JsonValue>.getLong(key: String): Long {
        val value = this[key] ?: error("catalog entry is missing '$key'")
        return value.asDouble().toLong()
    }
}
