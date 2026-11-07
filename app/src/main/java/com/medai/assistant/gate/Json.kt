package com.medai.assistant.gate

/**
 * Minimal JSON parser used by the gate classes.
 *
 * The app also runs these classes in JVM unit tests, where Android's org.json
 * is only a stub, so the gate must not depend on it.
 */
sealed interface JsonValue {
    data class JsonObject(val values: Map<String, JsonValue>) : JsonValue
    data class JsonArray(val values: List<JsonValue>) : JsonValue
    data class JsonString(val value: String) : JsonValue
    data class JsonNumber(val value: Double) : JsonValue
    data class JsonBoolean(val value: Boolean) : JsonValue
    data object JsonNull : JsonValue
}

object Json {
    fun parse(text: String): JsonValue {
        val parser = Parser(text)
        val value = parser.parseValue()
        parser.skipWhitespace()
        require(parser.position == text.length) {
            "Unexpected trailing JSON content at offset ${parser.position}"
        }
        return value
    }

    private class Parser(private val text: String) {
        var position: Int = 0

        fun skipWhitespace() {
            while (position < text.length && text[position].isWhitespace()) {
                position++
            }
        }

        fun parseValue(): JsonValue {
            skipWhitespace()
            require(position < text.length) { "Unexpected end of JSON" }
            return when (val c = text[position]) {
                '{' -> parseObject()
                '[' -> parseArray()
                '"' -> JsonValue.JsonString(parseString())
                't' -> {
                    expect("true")
                    JsonValue.JsonBoolean(true)
                }
                'f' -> {
                    expect("false")
                    JsonValue.JsonBoolean(false)
                }
                'n' -> {
                    expect("null")
                    JsonValue.JsonNull
                }
                else -> {
                    if (c == '-' || c.isDigit()) {
                        parseNumber()
                    } else {
                        error("Unexpected JSON character '$c' at offset $position")
                    }
                }
            }
        }

        private fun parseObject(): JsonValue.JsonObject {
            expect("{")
            val values = LinkedHashMap<String, JsonValue>()
            skipWhitespace()
            if (peek() == '}') {
                position++
                return JsonValue.JsonObject(values)
            }
            while (true) {
                skipWhitespace()
                require(peek() == '"') { "Expected object key at offset $position" }
                val key = parseString()
                skipWhitespace()
                expect(":")
                values[key] = parseValue()
                skipWhitespace()
                when (peek()) {
                    ',' -> {
                        position++
                    }
                    '}' -> {
                        position++
                        return JsonValue.JsonObject(values)
                    }
                    else -> error("Expected ',' or '}' at offset $position")
                }
            }
        }

        private fun parseArray(): JsonValue.JsonArray {
            expect("[")
            val values = mutableListOf<JsonValue>()
            skipWhitespace()
            if (peek() == ']') {
                position++
                return JsonValue.JsonArray(values)
            }
            while (true) {
                values.add(parseValue())
                skipWhitespace()
                when (peek()) {
                    ',' -> {
                        position++
                    }
                    ']' -> {
                        position++
                        return JsonValue.JsonArray(values)
                    }
                    else -> error("Expected ',' or ']' at offset $position")
                }
            }
        }

        private fun parseString(): String {
            expect("\"")
            val sb = StringBuilder()
            while (position < text.length) {
                val c = text[position++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        require(position < text.length) { "Unterminated escape" }
                        when (val escaped = text[position++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> {
                                require(position + 4 <= text.length) { "Invalid \\u escape" }
                                val hex = text.substring(position, position + 4)
                                position += 4
                                sb.append(hex.toInt(16).toChar())
                            }
                            else -> error("Invalid escape '\\$escaped' at offset $position")
                        }
                    }
                    else -> sb.append(c)
                }
            }
            error("Unterminated string")
        }

        private fun parseNumber(): JsonValue.JsonNumber {
            val start = position
            if (peek() == '-') position++
            while (position < text.length && text[position].isDigit()) position++
            if (position < text.length && text[position] == '.') {
                position++
                while (position < text.length && text[position].isDigit()) position++
            }
            if (position < text.length && (text[position] == 'e' || text[position] == 'E')) {
                position++
                if (position < text.length && (text[position] == '+' || text[position] == '-')) {
                    position++
                }
                while (position < text.length && text[position].isDigit()) position++
            }
            val raw = text.substring(start, position)
            return JsonValue.JsonNumber(raw.toDouble())
        }

        private fun expect(literal: String) {
            require(text.startsWith(literal, position)) {
                "Expected '$literal' at offset $position"
            }
            position += literal.length
        }

        private fun peek(): Char {
            require(position < text.length) { "Unexpected end of JSON" }
            return text[position]
        }
    }
}

fun JsonValue.asObject(): Map<String, JsonValue> {
    require(this is JsonValue.JsonObject) { "Expected JSON object, got $this" }
    return values
}

fun JsonValue.asArray(): List<JsonValue> {
    require(this is JsonValue.JsonArray) { "Expected JSON array, got $this" }
    return values
}

fun JsonValue.asString(): String {
    require(this is JsonValue.JsonString) { "Expected JSON string, got $this" }
    return value
}

fun JsonValue.asDouble(): Double {
    require(this is JsonValue.JsonNumber) { "Expected JSON number, got $this" }
    return value
}

fun JsonValue.asInt(): Int = asDouble().toInt()

fun JsonValue.asBoolean(): Boolean {
    require(this is JsonValue.JsonBoolean) { "Expected JSON boolean, got $this" }
    return value
}
