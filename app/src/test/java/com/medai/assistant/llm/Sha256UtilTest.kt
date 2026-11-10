package com.medai.assistant.llm

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream

/** K7a: streaming sha256 verification used for every downloaded model. */
class Sha256UtilTest {

    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun knownVectorEmptyString() {
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            Sha256Util.digestBytes(ByteArray(0))
        )
    }

    @Test
    fun knownVectorAbc() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            Sha256Util.digestBytes("abc".toByteArray(Charsets.UTF_8))
        )
    }

    @Test
    fun streamAndFileDigestsMatch() {
        val bytes = ByteArray(3_000_003) { (it % 251).toByte() }
        val file = temp.newFile("blob.bin")
        file.writeBytes(bytes)
        val streamDigest = Sha256Util.digestStream(ByteArrayInputStream(bytes))
        val fileDigest = Sha256Util.digestFile(file)
        assertEquals(streamDigest, fileDigest)
        assertEquals(Sha256Util.digestBytes(bytes), fileDigest)
    }

    @Test
    fun detectsSingleByteFlip() {
        val bytes = ByteArray(1024) { (it % 7).toByte() }
        val original = Sha256Util.digestBytes(bytes)
        bytes[512] = (bytes[512].toInt() xor 0x01).toByte()
        assertFalse(Sha256Util.digestBytes(bytes) == original)
    }

    @Test
    fun validationOfHexSha256() {
        assertTrue(Sha256Util.isValidSha256("0".repeat(64)))
        assertFalse(Sha256Util.isValidSha256("0".repeat(63)))
        assertFalse(Sha256Util.isValidSha256("X".repeat(64)))
    }
}
