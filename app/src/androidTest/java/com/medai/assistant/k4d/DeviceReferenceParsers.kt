package com.medai.assistant.k4d

/**
 * Small dependency-free parsers for the reference files packaged into the
 * instrumented-test APK. They mirror the JVM tests so the exact same data is
 * checked on the emulator.
 */
object DeviceReferenceParsers {

    data class EmbedderRefEntry(
        val id: Int,
        val kind: String,
        val input: String,
        val vector: FloatArray
    )

    data class TokenizerRefCase(
        val id: Int,
        val category: String,
        val input: String,
        val ids: List<Int>,
        val expectedAttentionLength: Int
    )

    fun parseCsv(text: String): List<Map<String, String>> {
        val lines = text.lines()
        if (lines.isEmpty()) return emptyList()
        val header = parseCsvLine(lines[0])
        val rows = mutableListOf<Map<String, String>>()
        for (index in 1 until lines.size) {
            val line = lines[index]
            if (line.isBlank()) continue
            val columns = parseCsvLine(line)
            val row = LinkedHashMap<String, String>()
            for (i in header.indices) {
                if (i < columns.size) row[header[i]] = columns[i]
            }
            rows.add(row)
        }
        return rows
    }

    private fun parseCsvLine(line: String): List<String> {
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

    fun parseEmbedderReference(jsonStr: String): List<EmbedderRefEntry> {
        val entries = mutableListOf<EmbedderRefEntry>()
        val entriesPos = jsonStr.indexOf("\"entries\"")
        val searchStart = if (entriesPos != -1) entriesPos else 0
        var startIdx = jsonStr.indexOf('{', searchStart)
        while (startIdx != -1) {
            var depth = 0
            var endIdx = -1
            var inStr = false
            var escape = false
            for (i in startIdx until jsonStr.length) {
                val c = jsonStr[i]
                if (escape) {
                    escape = false
                    continue
                }
                if (c == '\\') {
                    escape = true
                    continue
                }
                if (c == '"') {
                    inStr = !inStr
                    continue
                }
                if (!inStr) {
                    if (c == '{') depth++
                    else if (c == '}') {
                        depth--
                        if (depth == 0) {
                            endIdx = i
                            break
                        }
                    }
                }
            }
            if (endIdx == -1) break
            val objStr = jsonStr.substring(startIdx, endIdx + 1)
            parseEmbedderEntry(objStr)?.let { entries.add(it) }
            startIdx = jsonStr.indexOf('{', endIdx + 1)
        }
        return entries
    }

    private fun parseEmbedderEntry(objStr: String): EmbedderRefEntry? {
        val idVal = extractJsonInt(objStr, "id") ?: return null
        val kindVal = extractJsonString(objStr, "kind") ?: return null
        val inputVal = extractJsonString(objStr, "input") ?: return null
        val vectorVal = extractJsonFloatArray(objStr, "vector") ?: return null
        return EmbedderRefEntry(idVal, kindVal, inputVal, vectorVal)
    }

    private fun extractJsonInt(json: String, key: String): Int? {
        val pattern = "\"$key\"\\s*:\\s*([0-9]+)".toRegex()
        return pattern.find(json)?.groupValues?.get(1)?.toIntOrNull()
    }

    private fun extractJsonString(json: String, key: String): String? {
        val k = "\"$key\""
        val idx = json.indexOf(k)
        if (idx == -1) return null
        val colon = json.indexOf(':', idx + k.length)
        if (colon == -1) return null
        val startQuote = json.indexOf('"', colon + 1)
        if (startQuote == -1) return null
        val sb = StringBuilder()
        var escape = false
        var i = startQuote + 1
        while (i < json.length) {
            val c = json[i]
            if (escape) {
                when (c) {
                    '"' -> sb.append('"')
                    '\\' -> sb.append('\\')
                    'n' -> sb.append('\n')
                    'r' -> sb.append('\r')
                    't' -> sb.append('\t')
                    'u' -> {
                        if (i + 4 < json.length) {
                            val hex = json.substring(i + 1, i + 5)
                            val codePoint = hex.toIntOrNull(16)
                            if (codePoint != null) {
                                sb.append(codePoint.toChar())
                                i += 4
                            }
                        }
                    }
                    else -> sb.append(c)
                }
                escape = false
            } else if (c == '\\') {
                escape = true
            } else if (c == '"') {
                return sb.toString()
            } else {
                sb.append(c)
            }
            i++
        }
        return null
    }

    private fun extractJsonFloatArray(json: String, key: String): FloatArray? {
        val k = "\"$key\""
        val idx = json.indexOf(k)
        if (idx == -1) return null
        val startBracket = json.indexOf('[', idx + k.length)
        if (startBracket == -1) return null
        val endBracket = json.indexOf(']', startBracket)
        if (endBracket == -1) return null
        val inner = json.substring(startBracket + 1, endBracket)
        val tokens = inner.split(',')
        val arr = FloatArray(tokens.size)
        for (i in tokens.indices) {
            arr[i] = tokens[i].trim().toFloatOrNull() ?: 0.0f
        }
        return arr
    }

    fun parseTokenizerReference(jsonText: String): List<TokenizerRefCase> {
        val cases = ArrayList<TokenizerRefCase>()
        val marker = "\"cases\": ["
        val startIdx = jsonText.indexOf(marker)
        if (startIdx == -1) return cases

        val arrayContent = jsonText.substring(startIdx + marker.length)
        var pos = 0

        while (pos < arrayContent.length) {
            val objStart = arrayContent.indexOf('{', pos)
            if (objStart == -1) break
            var depth = 0
            var inStr = false
            var escape = false
            var objEnd = -1

            for (i in objStart until arrayContent.length) {
                val c = arrayContent[i]
                if (escape) {
                    escape = false
                    continue
                }
                if (c == '\\') {
                    escape = true
                    continue
                }
                if (c == '"') {
                    inStr = !inStr
                    continue
                }
                if (!inStr) {
                    if (c == '{') depth++
                    else if (c == '}') {
                        depth--
                        if (depth == 0) {
                            objEnd = i
                            break
                        }
                    }
                }
            }

            if (objEnd == -1) break
            val objJson = arrayContent.substring(objStart, objEnd + 1)
            pos = objEnd + 1

            val id = extractInt(objJson, "\"id\":")
            val cat = extractString(objJson, "\"category\":")
            val input = extractString(objJson, "\"input\":")
            val ids = extractIntList(objJson, "\"ids\":")
            val attLen = extractInt(objJson, "\"expected_attention_length\":")

            cases.add(TokenizerRefCase(id, cat, input, ids, attLen))
        }

        return cases
    }

    private fun extractInt(json: String, key: String): Int {
        val idx = json.indexOf(key)
        if (idx == -1) return 0
        val start = idx + key.length
        val end = json.indexOfAny(charArrayOf(',', '\n', '}'), start)
        val numStr = json.substring(start, if (end != -1) end else json.length).trim()
        return numStr.toIntOrNull() ?: 0
    }

    private fun extractString(json: String, key: String): String {
        val idx = json.indexOf(key)
        if (idx == -1) return ""
        val quote1 = json.indexOf('"', idx + key.length)
        if (quote1 == -1) return ""
        var quote2 = quote1 + 1
        var escape = false
        while (quote2 < json.length) {
            val c = json[quote2]
            if (escape) {
                escape = false
            } else if (c == '\\') {
                escape = true
            } else if (c == '"') {
                break
            }
            quote2++
        }
        val raw = json.substring(quote1 + 1, quote2)
        return raw.replace("\\\"", "\"")
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
    }

    private fun extractIntList(json: String, key: String): List<Int> {
        val idx = json.indexOf(key)
        if (idx == -1) return emptyList()
        val bracket1 = json.indexOf('[', idx + key.length)
        if (bracket1 == -1) return emptyList()
        val bracket2 = json.indexOf(']', bracket1)
        if (bracket2 == -1) return emptyList()
        val listStr = json.substring(bracket1 + 1, bracket2).trim()
        if (listStr.isEmpty()) return emptyList()
        return listStr.split(',').mapNotNull { it.trim().toIntOrNull() }
    }
}
