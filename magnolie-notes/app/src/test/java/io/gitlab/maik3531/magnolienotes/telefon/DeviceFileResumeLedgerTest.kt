package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.FileNotFoundException
import java.io.RandomAccessFile
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Locale

class DeviceFileResumeLedgerTest {
    private val fileId = "c".repeat(32)
    private fun binding() = DeviceTransferBinding("sender_fixture_01", "receiver_fixture_01", "d".repeat(64), "e".repeat(64), "f".repeat(64), "0".repeat(64))
    private fun vector() = Json.parseToJsonElement(File("../contracts/file-transfer-manifest-v1-vectors.json").readText())
        .jsonObject["vectors"]!!.jsonArray.first().jsonObject
    private fun manifest(data: ByteArray): DeviceFileManifest {
        val original = vector()["manifest"]!!.jsonObject
        val hash = MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        val member = original["files"]!!.jsonArray.first().jsonObject
        return DeviceFileManifest.parse(JsonObject(original + mapOf("total_bytes" to JsonPrimitive(data.size),
            "files" to JsonArray(listOf(JsonObject(member + mapOf("size" to JsonPrimitive(data.size), "sha256" to JsonPrimitive(hash))))))))
    }
    private class OwnedFiles(root: File, private val fileId: String) {
        val path = File(root, "owned.part")
        var writes = 0
        fun write(id: String, offset: Long, data: ByteArray) {
            check(id == fileId)
            RandomAccessFile(path, "rw").use { output -> output.seek(offset); output.write(data); output.fd.sync() }
            writes++
        }
        fun read(id: String, offset: Long, size: Int): ByteArray {
            check(id == fileId)
            RandomAccessFile(path, "r").use { input ->
                input.seek(offset)
                return ByteArray(minOf(size.toLong(), maxOf(0L, input.length() - offset)).toInt()).also(input::readFully)
            }
        }
    }
    private fun own(block: (OwnedFiles) -> Unit) {
        val root = Files.createTempDirectory("magnolie-resume329-").toFile()
        try { block(OwnedFiles(root, fileId)) } finally { root.deleteRecursively() }
    }

    @Test fun partialActualReadbackResumeAndSharedCheckpoint() = own { owned ->
        val source = binding()
        val bytes = ByteArray(DeviceFileManifest.CHUNK_BYTES) { 'a'.code.toByte() } + byteArrayOf(1, 2, 3, 4)
        val description = manifest(bytes)
        val ledger = DeviceFileResumeLedger(description, source) { source }
        ledger.record(fileId, 1, byteArrayOf(1, 2, 3, 4), owned::write, owned::read)
        assertEquals(4L, ledger.verifiedBytes); assertEquals(listOf(0), ledger.missing(fileId))
        val resumed = DeviceFileResumeLedger.restore(description, source, { source }, ledger.checkpoint(), owned::read)
        resumed.record(fileId, 1, byteArrayOf(1, 2, 3, 4), owned::write, owned::read)
        assertEquals(1, owned.writes)
        resumed.record(fileId, 0, bytes.copyOfRange(0, DeviceFileManifest.CHUNK_BYTES), owned::write, owned::read)
        assertEquals(bytes.size.toLong(), resumed.verifiedBytes)
        assertEquals(description.files.single(), resumed.verifiedFile(fileId, owned::read))
        assertEquals(2, owned.writes)
        owned.path.delete()
        val small = manifest("hello".toByteArray())
        val exact = DeviceFileResumeLedger(small, source) { source }
        exact.record(fileId, 0, "hello".toByteArray(), owned::write, owned::read)
        val shared = vector()["resume_checkpoint"]!!.jsonObject
        assertEquals(shared, exact.checkpoint())
        assertEquals(small.files.single(), DeviceFileResumeLedger.restore(small, source, { source }, shared, owned::read)
            .verifiedFile(fileId, owned::read))
    }

    @Test fun changedIdentityPermissionTargetAndCorruptBytesCannotResume() = own { owned ->
        val source = binding(); var live: DeviceTransferBinding? = source
        val description = manifest("hello".toByteArray())
        val ledger = DeviceFileResumeLedger(description, source) { live }
        ledger.record(fileId, 0, "hello".toByteArray(), owned::write, owned::read)
        val saved = ledger.checkpoint()
        for (changed in listOf(source.copy(senderIdentitySha256 = "1".repeat(64)), source.copy(receiverIdentitySha256 = "1".repeat(64)),
            source.copy(permissionEpoch = "1".repeat(64)), source.copy(destinationToken = "1".repeat(64)))) {
            live = changed
            assertThrows(TelefonProtokollFehler::class.java) { DeviceFileResumeLedger.restore(description, changed, { live }, saved, owned::read) }
            assertThrows(TelefonProtokollFehler::class.java) { DeviceFileResumeLedger.restore(description, source, { live }, saved, owned::read) }
        }
        live = source
        owned.path.writeText("other")
        assertThrows(TelefonProtokollFehler::class.java) { DeviceFileResumeLedger.restore(description, source, { live }, saved, owned::read) }
        assertThrows(TelefonProtokollFehler::class.java) { ledger.verifiedFile(fileId, owned::read) }
        assertEquals(1, owned.writes)
    }

    @Test fun revocationAndWrongReadbackDoNotManufactureProgress() = own { owned ->
        val source = binding(); var live = source
        val ledger = DeviceFileResumeLedger(manifest("hello".toByteArray()), source) { live }
        assertThrows(TelefonProtokollFehler::class.java) {
            ledger.record(fileId, 0, "hello".toByteArray(), owned::write) { _, _, _ -> "other".toByteArray() }
        }
        assertEquals(0L, ledger.verifiedBytes)
        assertThrows(TelefonProtokollFehler::class.java) {
            ledger.record(fileId, 0, "hello".toByteArray(), { id, offset, bytes ->
                owned.write(id, offset, bytes); live = source.copy(permissionEpoch = "1".repeat(64)) }, owned::read)
        }
        live = source
        assertEquals(0L, ledger.verifiedBytes)
    }

    @Test fun exactCheckpointAndFullDigestEofRemainMandatory() = own { owned ->
        val source = binding(); val description = manifest("hello".toByteArray())
        val ledger = DeviceFileResumeLedger(description, source) { source }
        ledger.record(fileId, 0, "hello".toByteArray(), owned::write, owned::read)
        val saved = ledger.checkpoint(); val proof = saved["chunks"]!!.jsonArray.first().jsonObject
        val malformed = listOf(JsonObject(saved + ("format" to JsonPrimitive(true))), JsonObject(saved + ("extra" to JsonPrimitive(true))),
            JsonObject(saved + ("chunks" to JsonArray(listOf(proof, proof)))),
            JsonObject(saved + ("chunks" to JsonArray(listOf(JsonObject(proof + ("index" to JsonPrimitive(true))))))),
            JsonObject(saved + ("chunks" to JsonArray(listOf(JsonObject(proof + ("sha256" to JsonPrimitive("0".repeat(64)))))))))
        malformed.forEach { value -> assertThrows(TelefonProtokollFehler::class.java) {
            DeviceFileResumeLedger.restore(description, source, { source }, value, owned::read) } }
        owned.path.appendText("extra")
        assertThrows(TelefonProtokollFehler::class.java) { ledger.verifiedFile(fileId, owned::read) }
        owned.path.delete()
        val wrong = DeviceFileResumeLedger(description, source) { source }
        wrong.record(fileId, 0, "other".toByteArray(), owned::write, owned::read)
        assertEquals(5L, wrong.verifiedBytes)
        assertThrows(TelefonProtokollFehler::class.java) { wrong.verifiedFile(fileId, owned::read) }
        owned.path.delete()
        val empty = DeviceFileResumeLedger(manifest(byteArrayOf()), source) { source }
        assertThrows(FileNotFoundException::class.java) { empty.verifiedFile(fileId, owned::read) }
        owned.path.writeBytes(byteArrayOf())
        assertEquals(0L, empty.verifiedFile(fileId, owned::read).size)
    }
}
