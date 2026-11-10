package com.medai.assistant.llm

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/** K7a: model catalog parsing and validation. */
class ModelCatalogTest {

    private fun realCatalogText(): String {
        val assets = File("src/main/assets/model_catalog.json")
        check(assets.isFile) {
            "run from the app module dir; missing ${assets.absolutePath}"
        }
        return assets.readText(Charsets.UTF_8)
    }

    @Test
    fun parsesRealCatalogWithExpectedEntries() {
        val models = ModelCatalog.parse(realCatalogText())
        assertEquals(2, models.size)
        val default = models.single { it.isDefault }
        assertEquals("qwen2.5-1.5b-instruct-q4km", default.id)
        assertEquals("qwen2.5-1.5b-instruct-q4_k_m.gguf", default.fileName)
        assertEquals(1_117_320_736L, default.sizeBytes)
        assertEquals("6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e", default.sha256)
        assertEquals(
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/" +
                "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            default.url
        )
        assertEquals("apache-2.0", default.license)
        assertEquals("license: apache-2.0", default.licenseLine)
        assertTrue(default.ramEstimateMb >= 1500)

        val fallback = models.single { !it.isDefault }
        assertEquals("qwen2.5-0.5b-instruct-q4km", fallback.id)
        assertEquals(491_400_032L, fallback.sizeBytes)
        assertEquals("74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db", fallback.sha256)
        assertTrue(fallback.ramEstimateMb in 600..1200)
    }

    @Test
    fun rejectsMissingDefaultModel() {
        val bad = """
            {
              "version": 1,
              "models": [
                {
                  "id": "a", "display_name": "A", "file_name": "a.gguf",
                  "repo": "o/a", "url": "https://huggingface.co/o/a/resolve/main/a.gguf",
                  "size_bytes": 10, "sha256": "${"0".repeat(64)}",
                  "license": "mit", "license_line": "license: mit",
                  "license_url": "https://huggingface.co/o/a/blob/main/LICENSE",
                  "ram_estimate_mb": 10, "ram_estimate_calc": "x", "default": false
                }
              ]
            }
        """.trimIndent()
        try {
            ModelCatalog.parse(bad)
            fail("catalog without a default model must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertNotNull(expected.message)
        }
    }

    @Test
    fun rejectsNonHttpsUrl() {
        val bad = """
            {
              "version": 1,
              "models": [
                {
                  "id": "a", "display_name": "A", "file_name": "a.gguf",
                  "repo": "o/a", "url": "http://huggingface.co/o/a/resolve/main/a.gguf",
                  "size_bytes": 10, "sha256": "${"0".repeat(64)}",
                  "license": "mit", "license_line": "license: mit",
                  "license_url": "https://huggingface.co/o/a/blob/main/LICENSE",
                  "ram_estimate_mb": 10, "ram_estimate_calc": "x", "default": true
                }
              ]
            }
        """.trimIndent()
        try {
            ModelCatalog.parse(bad)
            fail("non-HTTPS catalog url must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message!!.contains("HTTPS"))
        }
    }

    @Test
    fun rejectsMalformedSha256() {
        val bad = """
            {
              "version": 1,
              "models": [
                {
                  "id": "a", "display_name": "A", "file_name": "a.gguf",
                  "repo": "o/a", "url": "https://huggingface.co/o/a/resolve/main/a.gguf",
                  "size_bytes": 10, "sha256": "not-a-real-hash",
                  "license": "mit", "license_line": "license: mit",
                  "license_url": "https://huggingface.co/o/a/blob/main/LICENSE",
                  "ram_estimate_mb": 10, "ram_estimate_calc": "x", "default": true
                }
              ]
            }
        """.trimIndent()
        try {
            ModelCatalog.parse(bad)
            fail("malformed sha256 must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message!!.contains("sha256"))
        }
    }

    @Test
    fun rejectsDuplicateIds() {
        fun entry(id: String, isDefault: Boolean) = """
                {
                  "id": "$id", "display_name": "A", "file_name": "a.gguf",
                  "repo": "o/a", "url": "https://huggingface.co/o/a/resolve/main/a.gguf",
                  "size_bytes": 10, "sha256": "${"0".repeat(64)}",
                  "license": "mit", "license_line": "license: mit",
                  "license_url": "https://huggingface.co/o/a/blob/main/LICENSE",
                  "ram_estimate_mb": 10, "ram_estimate_calc": "x", "default": $isDefault
                }
        """.trimIndent()
        val bad = """
            {
              "version": 1,
              "models": [${entry("dup", true)}, ${entry("dup", false)}]
            }
        """.trimIndent()
        try {
            ModelCatalog.parse(bad)
            fail("duplicate ids must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message!!.contains("duplicate"))
        }
    }
}
