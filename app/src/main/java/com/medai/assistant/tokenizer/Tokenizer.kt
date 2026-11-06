package com.medai.assistant.tokenizer

import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.charset.StandardCharsets

/**
 * High-performance, zero-heavy-dependency tokenizer matching HuggingFace/SentencePiece Unigram
 * model for multilingual-e5-small.
 *
 * Implements:
 * 1. Stream parsing of 17MB `tokenizer.json` directly from input stream.
 * 2. Precompiled charsmap normalizer (SentencePiece double-array trie emulation) + multiple space collapse.
 * 3. Metaspace pre-tokenization with replacement ' ' (U+2581) and add_prefix_space=true.
 * 4. Unigram Viterbi segmentation over character substrings with Trie prefix matching.
 * 5. Unknown token handling (<unk>, id=3) with K_UNK_PENALTY=10.0 matching Python HuggingFace.
 * 6. Special tokens <s> (id=0) and </s> (id=2).
 * 7. Truncation to max_length (default 384 tokens including special tokens).
 */
class Tokenizer private constructor(
    val unkId: Int,
    val bosId: Int,
    val eosId: Int,
    val minScore: Double,
    val precompiledNormalizer: PrecompiledNormalizer?,
    private val vocabScores: DoubleArray,
    private val trie: FlatByteTrie
) {
    companion object {
        const val MAX_LENGTH = 384
        private const val K_UNK_PENALTY = 10.0

        /**
         * Stream parse `tokenizer.json` from [InputStream].
         * Memory efficient, does not load heavy JSON AST trees.
         */
        fun fromStream(inputStream: InputStream): Tokenizer {
            val parser = TokenizerJsonStreamParser()
            return parser.parse(inputStream)
        }

        /**
         * Fast memory-mapped binary loader from `tokenizer.bin`.
         * Reads flat arrays with bulk copies and no per-node loops.
         */
        fun fromBinaryFile(file: File): Tokenizer {
            FileInputStream(file).use { fis ->
                val channel = fis.channel
                val buffer = channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size())
                buffer.order(ByteOrder.LITTLE_ENDIAN)
                return fromByteBuffer(buffer)
            }
        }

        /**
         * Fast binary loader from [ByteBuffer] (must be LITTLE_ENDIAN).
         */
        fun fromByteBuffer(buffer: ByteBuffer): Tokenizer {
            buffer.order(ByteOrder.LITTLE_ENDIAN)

            // Header (76 bytes)
            val magic = ByteArray(4)
            buffer.get(magic)
            val magicStr = String(magic, StandardCharsets.US_ASCII)
            require(magicStr == "TKBN") { "Invalid magic in binary tokenizer: $magicStr" }

            val version = buffer.int
            require(version == 1) { "Unsupported tokenizer.bin version: $version" }

            val sha256Bytes = ByteArray(32)
            buffer.get(sha256Bytes)

            val unkId = buffer.int
            val bosId = buffer.int
            val eosId = buffer.int
            val vocabSize = buffer.int
            val minScore = buffer.double
            val charsmapLen = buffer.int
            val pieceBlobLen = buffer.int
            val trieNodeCount = buffer.int

            // 1. Charsmap
            val precompiledNormalizer = if (charsmapLen > 0) {
                val charsmapBytes = ByteArray(charsmapLen)
                buffer.get(charsmapBytes)
                PrecompiledNormalizer.fromBytes(charsmapBytes)
            } else {
                null
            }

            // 2. Vocab scores (float32 array)
            val vocabScores = DoubleArray(vocabSize)
            val floatBuf = buffer.asFloatBuffer()
            val tempFloats = FloatArray(vocabSize)
            floatBuf.get(tempFloats)
            buffer.position(buffer.position() + vocabSize * 4)
            for (i in 0 until vocabSize) {
                vocabScores[i] = tempFloats[i].toDouble()
            }

            // 3. Piece offsets (int32 array)
            val pieceOffsets = IntArray(vocabSize + 1)
            val intBuf1 = buffer.asIntBuffer()
            intBuf1.get(pieceOffsets)
            buffer.position(buffer.position() + (vocabSize + 1) * 4)

            // 4. Piece blob
            val pieceBlob = ByteArray(pieceBlobLen)
            buffer.get(pieceBlob)

            // Build pieces array from blob and offsets
            val pieces = Array(vocabSize) { i ->
                val start = pieceOffsets[i]
                val end = pieceOffsets[i + 1]
                String(pieceBlob, start, end - start, StandardCharsets.UTF_8)
            }

            // 5. Trie node byte
            val nodeByte = ByteArray(trieNodeCount)
            buffer.get(nodeByte)

            // 6. Trie node vocab id
            val nodeVocabId = IntArray(trieNodeCount)
            val intBuf2 = buffer.asIntBuffer()
            intBuf2.get(nodeVocabId)
            buffer.position(buffer.position() + trieNodeCount * 4)

            // 7. Trie node first child
            val nodeFirstChild = IntArray(trieNodeCount)
            val intBuf3 = buffer.asIntBuffer()
            intBuf3.get(nodeFirstChild)
            buffer.position(buffer.position() + trieNodeCount * 4)

            // 8. Trie node next sibling
            val nodeNextSibling = IntArray(trieNodeCount)
            val intBuf4 = buffer.asIntBuffer()
            intBuf4.get(nodeNextSibling)
            buffer.position(buffer.position() + trieNodeCount * 4)

            val trie = FlatByteTrie(
                nodeByte = nodeByte,
                nodeVocabId = nodeVocabId,
                nodeFirstChild = nodeFirstChild,
                nodeNextSibling = nodeNextSibling
            )

            return Tokenizer(
                unkId = unkId,
                bosId = bosId,
                eosId = eosId,
                minScore = minScore,
                precompiledNormalizer = precompiledNormalizer,
                vocabScores = vocabScores,
                trie = trie
            )
        }
    }

    /**
     * Represents the tokenization result.
     */
    data class Encoding(
        val ids: List<Int>,
        val tokens: List<String>,
        val attentionLength: Int
    )

    /**
     * Encode text into subword IDs with truncation to [maxLength].
     * Matches the Python pipeline:
     * - Normalize
     * - Metaspace pre-tokenize (add ' ' prefix, replace ' ' with ' ')
     * - Segment each word via Unigram Viterbi
     * - Wrap with <s> and </s>
     * - Truncate to [maxLength]
     */
    fun encode(text: String, maxLength: Int = MAX_LENGTH): Encoding {
        val normalized = precompiledNormalizer?.normalize(text) ?: fallbackNormalize(text)

        // Metaspace pre-tokenization matching Hugging Face Metaspace(replacement='▁', add_prefix_space=true)
        // If normalized starts with ' ', that space itself becomes the prefix '▁'.
        // Otherwise, '▁' is prepended.
        val metaspace = if (normalized.isEmpty()) {
            ""
        } else {
            buildString(normalized.length + 1) {
                if (!normalized.startsWith(' ')) {
                    append('▁')
                }
                for (ch in normalized) {
                    if (ch == ' ') {
                        append('▁')
                    } else {
                        append(ch)
                    }
                }
            }
        }

        // Viterbi segmentation over metaspace text
        val (pieceIds, pieceTokens) = segmentUnigram(metaspace)

        // Post-processing: add <s> (id=0) at beginning and </s> (id=2) at end
        val finalIds = ArrayList<Int>(pieceIds.size + 2)
        val finalTokens = ArrayList<String>(pieceTokens.size + 2)

        finalIds.add(bosId)
        finalTokens.add("<s>")

        finalIds.addAll(pieceIds)
        finalTokens.addAll(pieceTokens)

        finalIds.add(eosId)
        finalTokens.add("</s>")

        // Truncate to maxLength (matches Python build_embeddings: ids[:384])
        val truncatedIds = if (finalIds.size > maxLength) {
            finalIds.subList(0, maxLength)
        } else {
            finalIds
        }

        val truncatedTokens = if (finalTokens.size > maxLength) {
            finalTokens.subList(0, maxLength)
        } else {
            finalTokens
        }

        return Encoding(
            ids = truncatedIds,
            tokens = truncatedTokens,
            attentionLength = truncatedIds.size
        )
    }

    /**
     * Unigram Viterbi lattice segmentation over UTF-8 byte representation.
     */
    private fun segmentUnigram(sentence: String): Pair<List<Int>, List<String>> {
        if (sentence.isEmpty()) {
            return Pair(emptyList(), emptyList())
        }

        val sentenceBytes = sentence.toByteArray(StandardCharsets.UTF_8)
        val len = sentenceBytes.size
        val unkScore = minScore - K_UNK_PENALTY

        // Lattice nodes grouped by start position and end position
        val beginNodes = Array(len + 1) { ArrayList<LatticeNode>() }
        val endNodes = Array(len + 1) { ArrayList<LatticeNode>() }

        val bosNode = LatticeNode(id = bosId, pos = 0, length = 0, score = 0.0)
        val eosNode = LatticeNode(id = eosId, pos = len, length = 0, score = 0.0)
        endNodes[0].add(bosNode)
        beginNodes[len].add(eosNode)

        // Buffer to collect trie matches
        val matchLengths = IntArray(64)
        val matchVocabIds = IntArray(64)

        // Populate lattice nodes
        var pos = 0
        while (pos < len) {
            val charLen = getUtf8CharLength(sentenceBytes[pos])
            var hasSingleNode = false

            val matchCount = trie.commonPrefixSearch(sentenceBytes, pos, matchLengths, matchVocabIds)
            for (i in 0 until matchCount) {
                val offset = matchLengths[i]
                val matchId = matchVocabIds[i]
                val score = vocabScores[matchId]
                val node = LatticeNode(id = matchId, pos = pos, length = offset, score = score)
                beginNodes[pos].add(node)
                endNodes[pos + offset].add(node)
                if (!hasSingleNode && offset == charLen) {
                    hasSingleNode = true
                }
            }

            if (!hasSingleNode) {
                val unkNode = LatticeNode(id = unkId, pos = pos, length = charLen, score = unkScore)
                beginNodes[pos].add(unkNode)
                endNodes[pos + charLen].add(unkNode)
            }

            pos += charLen
        }

        // Viterbi forward pass
        pos = 0
        while (pos <= len) {
            if (beginNodes[pos].isEmpty()) {
                break
            }
            for (rnode in beginNodes[pos]) {
                var bestScore = Double.NEGATIVE_INFINITY
                var bestNode: LatticeNode? = null
                for (lnode in endNodes[pos]) {
                    val score = lnode.backtraceScore + rnode.score
                    if (bestNode == null || score > bestScore) {
                        bestNode = lnode
                        bestScore = score
                    }
                }
                rnode.prev = bestNode
                rnode.backtraceScore = bestScore
            }

            if (pos < len) {
                pos += getUtf8CharLength(sentenceBytes[pos])
            } else {
                break
            }
        }

        // Backtrace
        val results = ArrayList<LatticeNode>()
        var curr = eosNode.prev
        while (curr != null && curr.prev != null) {
            results.add(curr)
            curr = curr.prev
        }
        results.reverse()

        val ids = ArrayList<Int>(results.size)
        val tokens = ArrayList<String>(results.size)
        for (node in results) {
            ids.add(node.id)
            val tokStr = String(sentenceBytes, node.pos, node.length, StandardCharsets.UTF_8)
            tokens.add(tokStr)
        }

        return Pair(ids, tokens)
    }

    private class LatticeNode(
        val id: Int,
        val pos: Int,
        val length: Int,
        val score: Double
    ) {
        var backtraceScore: Double = 0.0
        var prev: LatticeNode? = null
    }

    /**
     * Compact First-Child / Next-Sibling byte trie backed by flat primitive arrays.
     * Takes ~10MB total heap for ~800,000 nodes.
     */
    class FlatByteTrie(
        private val nodeByte: ByteArray,
        private val nodeVocabId: IntArray,
        private val nodeFirstChild: IntArray,
        private val nodeNextSibling: IntArray
    ) {
        fun commonPrefixSearch(
            sentenceBytes: ByteArray,
            pos: Int,
            outLengths: IntArray,
            outVocabIds: IntArray
        ): Int {
            var curr = 0
            var count = 0
            var offset = 0
            val len = sentenceBytes.size

            while (pos + offset < len) {
                val b = sentenceBytes[pos + offset]
                var child = nodeFirstChild[curr]
                var found = -1
                while (child != -1 && child != 0) {
                    if (nodeByte[child] == b) {
                        found = child
                        break
                    }
                    child = nodeNextSibling[child]
                }
                if (found <= 0) {
                    break
                }
                offset++
                val vid = nodeVocabId[found]
                if (vid != -1) {
                    if (count < outLengths.size) {
                        outLengths[count] = offset
                        outVocabIds[count] = vid
                        count++
                    }
                }
                curr = found
            }
            return count
        }
    }

    private fun getUtf8CharLength(leadByte: Byte): Int {
        val b = leadByte.toInt() and 0xFF
        return when {
            b < 0x80 -> 1
            b in 0xC0..0xDF -> 2
            b in 0xE0..0xEF -> 3
            b in 0xF0..0xF7 -> 4
            else -> 1
        }
    }

    private fun fallbackNormalize(text: String): String {
        val sb = StringBuilder(text.length)
        for (c in text) {
            val code = c.code
            if (c in "\t\n\r\u000c" || c in "\u200b\ufeff") {
                sb.append(' ')
            } else if (code == 0) {
                sb.append('\u0000')
            } else if (code < 0x20 || (code in 0x7f..0x9f)) {
                // skip control
            } else {
                sb.append(c)
            }
        }
        val nfkc = java.text.Normalizer.normalize(sb.toString(), java.text.Normalizer.Form.NFKC)
        return nfkc.replace(Regex(" {2,}"), " ")
    }

    /**
     * Implements SentencePiece's Double-Array Trie Precompiled charsmap normalizer.
     */
    class PrecompiledNormalizer(
        private val array: IntArray,
        private val normalizedBytes: ByteArray
    ) {
        companion object {
            fun fromBytes(data: ByteArray): PrecompiledNormalizer {
                val trieSize = (data[0].toInt() and 0xFF) or
                        ((data[1].toInt() and 0xFF) shl 8) or
                        ((data[2].toInt() and 0xFF) shl 16) or
                        ((data[3].toInt() and 0xFF) shl 24)
                val trieUnits = trieSize / 4
                val array = IntArray(trieUnits)
                var offset = 4
                for (i in 0 until trieUnits) {
                    val n = (data[offset].toInt() and 0xFF) or
                            ((data[offset + 1].toInt() and 0xFF) shl 8) or
                            ((data[offset + 2].toInt() and 0xFF) shl 16) or
                            ((data[offset + 3].toInt() and 0xFF) shl 24)
                    array[i] = n
                    offset += 4
                }
                val normalizedBytes = ByteArray(data.size - offset)
                System.arraycopy(data, offset, normalizedBytes, 0, normalizedBytes.size)
                return PrecompiledNormalizer(array, normalizedBytes)
            }
        }

        private fun getOffset(u: Int): Int {
            val shift = ((u and (1 shl 9)) ushr 6)
            return (u ushr 10) shl shift
        }

        private fun getLabel(u: Int): Int = u and (((1 shl 31)) or 0xFF)
        private fun hasLeaf(u: Int): Boolean = ((u ushr 8) and 1) == 1
        private fun getValue(u: Int): Int = u and 0x7FFFFFFF

        fun transform(chunkBytes: ByteArray): String? {
            var nodePos = 0
            var unit = array[nodePos]
            nodePos = nodePos xor getOffset(unit)

            var matchValue = -1
            for (b in chunkBytes) {
                val c = b.toInt() and 0xFF
                if (c == 0) break
                nodePos = nodePos xor c
                if (nodePos < 0 || nodePos >= array.size) return null
                unit = array[nodePos]
                if (getLabel(unit) != c) return null
                nodePos = nodePos xor getOffset(unit)
                if (hasLeaf(unit)) {
                    matchValue = getValue(array[nodePos])
                    break // shortest prefix match in spm_precompiled
                }
            }

            if (matchValue < 0) return null

            var end = matchValue
            while (end < normalizedBytes.size && normalizedBytes[end].toInt() != 0) {
                end++
            }
            return String(normalizedBytes, matchValue, end - matchValue, StandardCharsets.UTF_8)
        }

        fun normalize(text: String): String {
            val sb = StringBuilder(text.length)
            var i = 0
            while (i < text.length) {
                val cp = text.codePointAt(i)
                val charCount = Character.charCount(cp)
                val charStr = text.substring(i, i + charCount)
                val charBytes = charStr.toByteArray(StandardCharsets.UTF_8)
                val transformed = transform(charBytes)
                if (transformed != null) {
                    sb.append(transformed)
                } else {
                    sb.append(charStr)
                }
                i += charCount
            }
            // Replace {2,} spaces with single space
            return sb.toString().replace(Regex(" {2,}"), " ")
        }
    }

    /**
     * Efficient stream parser for `tokenizer.json`.
     */
    private class TokenizerJsonStreamParser {
        fun parse(inputStream: InputStream): Tokenizer {
            val reader = inputStream.bufferedReader(StandardCharsets.UTF_8)
            var unkId = 3
            val bosId = 0
            val eosId = 2
            var precompiledNormalizer: PrecompiledNormalizer? = null

            val vocabScoresList = ArrayList<Double>(250005)
            var minScore = 0.0

            // Pre-allocate flat arrays for Trie (~800k nodes)
            var capacity = 850000
            var nodeByte = ByteArray(capacity)
            var nodeVocabId = IntArray(capacity) { -1 }
            var nodeFirstChild = IntArray(capacity)
            var nodeNextSibling = IntArray(capacity)
            var nodeCount = 1 // Root node is index 0

            fun ensureCapacity(needed: Int) {
                if (needed >= capacity) {
                    val newCap = (capacity * 1.5).toInt()
                    val newByte = ByteArray(newCap)
                    System.arraycopy(nodeByte, 0, newByte, 0, nodeCount)
                    nodeByte = newByte

                    val newVid = IntArray(newCap) { -1 }
                    System.arraycopy(nodeVocabId, 0, newVid, 0, nodeCount)
                    nodeVocabId = newVid

                    val newFc = IntArray(newCap)
                    System.arraycopy(nodeFirstChild, 0, newFc, 0, nodeCount)
                    nodeFirstChild = newFc

                    val newNs = IntArray(newCap)
                    System.arraycopy(nodeNextSibling, 0, newNs, 0, nodeCount)
                    nodeNextSibling = newNs

                    capacity = newCap
                }
            }

            var inPrecompiled = false
            var inVocab = false

            var line = reader.readLine()
            while (line != null) {
                val trimmed = line.trim()

                if (trimmed.contains("\"type\": \"Precompiled\"")) {
                    inPrecompiled = true
                } else if (inPrecompiled && trimmed.startsWith("\"precompiled_charsmap\":")) {
                    val startQuote = trimmed.indexOf('"', trimmed.indexOf(':'))
                    val endQuote = trimmed.lastIndexOf('"')
                    if (startQuote != -1 && endQuote > startQuote) {
                        val b64 = trimmed.substring(startQuote + 1, endQuote)
                        val bytes = java.util.Base64.getDecoder().decode(b64)
                        precompiledNormalizer = PrecompiledNormalizer.fromBytes(bytes)
                    }
                    inPrecompiled = false
                } else if (trimmed.startsWith("\"unk_id\":")) {
                    val numStr = trimmed.substringAfter(":").trim().trimEnd(',')
                    unkId = numStr.toIntOrNull() ?: 3
                } else if (trimmed.startsWith("\"vocab\": [")) {
                    inVocab = true
                    line = reader.readLine()
                    continue
                }

                if (inVocab) {
                    if (trimmed.startsWith("]")) {
                        inVocab = false
                    } else if (trimmed.startsWith("[")) {
                        val lineTok = reader.readLine() ?: break
                        val lineScore = reader.readLine() ?: break
                        reader.readLine() // closing ']' or '],'

                        val tokStr = parseJsonString(lineTok.trim())
                        val scoreStr = lineScore.trim().trimEnd(',')
                        val score = scoreStr.toDoubleOrNull() ?: 0.0

                        val vocabId = vocabScoresList.size
                        vocabScoresList.add(score)
                        if (score < minScore) {
                            minScore = score
                        }

                        // Add to FlatByteTrie
                        val bytes = tokStr.toByteArray(StandardCharsets.UTF_8)
                        var curr = 0
                        for (b in bytes) {
                            var child = nodeFirstChild[curr]
                            var found = 0
                            while (child != 0) {
                                if (nodeByte[child] == b) {
                                    found = child
                                    break
                                }
                                child = nodeNextSibling[child]
                            }
                            if (found == 0) {
                                ensureCapacity(nodeCount + 1)
                                val nxt = nodeCount++
                                nodeByte[nxt] = b
                                nodeVocabId[nxt] = -1
                                nodeFirstChild[nxt] = 0
                                nodeNextSibling[nxt] = nodeFirstChild[curr]
                                nodeFirstChild[curr] = nxt
                                curr = nxt
                            } else {
                                curr = found
                            }
                        }
                        nodeVocabId[curr] = vocabId
                    }
                }

                line = reader.readLine()
            }

            val vocabScoresArray = DoubleArray(vocabScoresList.size)
            for (i in vocabScoresList.indices) {
                vocabScoresArray[i] = vocabScoresList[i]
            }

            // Trim arrays to exact nodeCount
            val finalByte = ByteArray(nodeCount)
            System.arraycopy(nodeByte, 0, finalByte, 0, nodeCount)

            val finalVid = IntArray(nodeCount)
            System.arraycopy(nodeVocabId, 0, finalVid, 0, nodeCount)

            val finalFc = IntArray(nodeCount)
            System.arraycopy(nodeFirstChild, 0, finalFc, 0, nodeCount)

            val finalNs = IntArray(nodeCount)
            System.arraycopy(nodeNextSibling, 0, finalNs, 0, nodeCount)

            val trie = FlatByteTrie(finalByte, finalVid, finalFc, finalNs)

            return Tokenizer(
                unkId = unkId,
                bosId = bosId,
                eosId = eosId,
                minScore = minScore,
                precompiledNormalizer = precompiledNormalizer,
                vocabScores = vocabScoresArray,
                trie = trie
            )
        }

        private fun parseJsonString(raw: String): String {
            val trimmed = raw.trimEnd(',')
            if (trimmed.length >= 2 && trimmed.startsWith("\"") && trimmed.endsWith("\"")) {
                val inner = trimmed.substring(1, trimmed.length - 1)
                val sb = StringBuilder(inner.length)
                var i = 0
                while (i < inner.length) {
                    val c = inner[i]
                    if (c == '\\' && i + 1 < inner.length) {
                        val next = inner[i + 1]
                        when (next) {
                            '"' -> { sb.append('"'); i += 2 }
                            '\\' -> { sb.append('\\'); i += 2 }
                            '/' -> { sb.append('/'); i += 2 }
                            'b' -> { sb.append('\b'); i += 2 }
                            'f' -> { sb.append('\u000c'); i += 2 }
                            'n' -> { sb.append('\n'); i += 2 }
                            'r' -> { sb.append('\r'); i += 2 }
                            't' -> { sb.append('\t'); i += 2 }
                            'u' -> {
                                if (i + 5 < inner.length) {
                                    val hex = inner.substring(i + 2, i + 6)
                                    val code = hex.toIntOrNull(16)
                                    if (code != null) {
                                        sb.append(code.toChar())
                                        i += 6
                                    } else {
                                        sb.append(c)
                                        i++
                                    }
                                } else {
                                    sb.append(c)
                                    i++
                                }
                            }
                            else -> { sb.append(next); i += 2 }
                        }
                    } else {
                        sb.append(c)
                        i++
                    }
                }
                return sb.toString()
            }
            return raw
        }
    }
}
