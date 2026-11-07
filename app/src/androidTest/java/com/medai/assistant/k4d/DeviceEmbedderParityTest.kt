package com.medai.assistant.k4d

import com.medai.assistant.embedder.OnnxEmbedder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * K4d: the 24 reference vectors (query + passage) are recomputed on the
 * emulator with onnxruntime-android and must stay within cosine 0.998.
 */
class DeviceEmbedderParityTest {

    @Test
    fun test24ReferenceVectorsOnDevice() {
        val entries = DeviceReferenceParsers.parseEmbedderReference(
            DeviceTestRuntime.mainAssetText("embedder_reference.json")
        )
        assertEquals("embedder_reference.json must contain 24 entries", 24, entries.size)

        var minCosine = 1.0f
        var minId = -1
        for (entry in entries) {
            val computed = if (entry.kind == "query") {
                DeviceTestRuntime.embedder.embedQuery(entry.input)
            } else {
                DeviceTestRuntime.embedder.embedPassage(entry.input)
            }
            val cosine = OnnxEmbedder.cosineSimilarity(computed, entry.vector)
            if (cosine < minCosine) {
                minCosine = cosine
                minId = entry.id
            }
            assertTrue(
                "Cosine for vector #${entry.id} (${entry.kind}) is $cosine, must be >= 0.998",
                cosine >= 0.998f
            )
        }
        println("K4d embedder parity: ${entries.size}/${entries.size} vectors, min cosine=$minCosine (id=$minId)")
    }
}
