package com.medai.assistant.gate

import java.io.File

/** Shared asset/report lookup for the K4 JVM tests. */
object GateTestAssets {
    fun find(candidates: List<String>): File? = candidates
        .asSequence()
        .map { File(it) }
        .firstOrNull { it.exists() }

    fun require(candidates: List<String>, label: String): File =
        find(candidates) ?: error("Missing $label; looked at: $candidates")

    val database: File
        get() = require(
            listOf(
                "src/main/assets/books_knowledge.db",
                "app/src/main/assets/books_knowledge.db",
                "../app/src/main/assets/books_knowledge.db",
                "assets/books_knowledge.db"
            ),
            "books_knowledge.db"
        )

    val vocab: File
        get() = require(
            listOf(
                "src/main/assets/gate_vocab.json",
                "app/src/main/assets/gate_vocab.json",
                "../app/src/main/assets/gate_vocab.json",
                "assets/gate_vocab.json"
            ),
            "gate_vocab.json (run scripts/write_gate_vocab.py)"
        )

    val config: File
        get() = require(
            listOf(
                "src/main/assets/gate_config.json",
                "app/src/main/assets/gate_config.json",
                "../app/src/main/assets/gate_config.json",
                "assets/gate_config.json"
            ),
            "gate_config.json"
        )

    val reference: File
        get() = require(
            listOf(
                "src/main/assets/gate_reference.json",
                "app/src/main/assets/gate_reference.json",
                "../app/src/main/assets/gate_reference.json",
                "assets/gate_reference.json"
            ),
            "gate_reference.json"
        )

    val retrievalCsv: File
        get() = require(
            listOf(
                "src/test/resources/retrieval_top5.csv",
                "app/src/test/resources/retrieval_top5.csv",
                "eval/retrieval_top5.csv",
                "../eval/retrieval_top5.csv",
                "retrieval_top5.csv"
            ),
            "retrieval_top5.csv"
        )

    val model: File
        get() = require(
            listOf(
                "src/main/assets/models/embedder/model_quantized.onnx",
                "app/src/main/assets/models/embedder/model_quantized.onnx",
                "../app/src/main/assets/models/embedder/model_quantized.onnx",
                "assets/models/embedder/model_quantized.onnx"
            ),
            "model_quantized.onnx"
        )

    val tokenizerBin: File
        get() = require(
            listOf(
                "src/main/assets/models/embedder/tokenizer.bin",
                "app/src/main/assets/models/embedder/tokenizer.bin",
                "../app/src/main/assets/models/embedder/tokenizer.bin",
                "assets/models/embedder/tokenizer.bin"
            ),
            "tokenizer.bin"
        )

    val embeddings: File
        get() = require(
            listOf(
                "src/main/assets/embeddings.bin",
                "app/src/main/assets/embeddings.bin",
                "../app/src/main/assets/embeddings.bin",
                "assets/embeddings.bin"
            ),
            "embeddings.bin"
        )

    fun reportDir(): File {
        val repoRoot = if (File("app").exists()) File(".") else File("..")
        val dir = File(repoRoot, "build/reports/parity")
        dir.mkdirs()
        return dir
    }

    fun parseCsv(file: File): List<Map<String, String>> {
        val lines = file.readLines(Charsets.UTF_8)
        if (lines.isEmpty()) return emptyList()
        val header = parseCsvLine(lines[0])
        val rows = mutableListOf<Map<String, String>>()
        for (index in 1 until lines.size) {
            val line = lines[index]
            if (line.isBlank()) continue
            val columns = parseCsvLine(line)
            val row = LinkedHashMap<String, String>()
            for (i in header.indices) {
                if (i < columns.size) {
                    row[header[i]] = columns[i]
                }
            }
            rows.add(row)
        }
        return rows
    }

    fun parseCsvLine(line: String): List<String> {
        val result = ArrayList<String>()
        val sb = StringBuilder()
        var inQuotes = false
        var i = 0
        while (i < line.length) {
            val c = line[i]
            if (c == '"') {
                if (inQuotes && i + 1 < line.length && line[i + 1] == '"') {
                    sb.append('"')
                    i++
                } else {
                    inQuotes = !inQuotes
                }
            } else if (c == ',' && !inQuotes) {
                result.add(sb.toString().trim())
                sb.clear()
            } else {
                sb.append(c)
            }
            i++
        }
        result.add(sb.toString().trim())
        return result
    }

    fun csvEscape(value: String): String {
        val needsQuotes = value.any { it == ',' || it == '"' || it == '\n' || it == '\r' }
        val escaped = value.replace("\"", "\"\"")
        return if (needsQuotes) "\"$escaped\"" else escaped
    }
}
