package io.gitlab.maik3531.magnolienotes.telefon

import java.security.MessageDigest
import java.util.Base64
import java.util.zip.GZIPInputStream
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PersonalBatchBoundaryTest {
    @Test fun sharedUtf8BodyLimitsAndActorEnvelope() {
        val fixture = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/personal-sync-batch-boundaries.json")).readText()).jsonObject
        val cases = fixture.getValue("cases").jsonArray
        assertEquals(16, cases.size)
        fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        for (item in cases.map { it.jsonObject }) {
            val name = item.getValue("name").jsonPrimitive.content
            val raw = GZIPInputStream(Base64.getDecoder().decode(item.getValue("gzip_base64").jsonPrimitive.content).inputStream()).use { it.readBytes() }
            val body = Json.parseToJsonElement(raw.toString(Charsets.UTF_8)).jsonObject
            assertEquals(name, item.getValue("body_bytes").jsonPrimitive.int, raw.size)
            assertEquals(name, item.getValue("sha256").jsonPrimitive.content, hash(raw))
            assertArrayEquals(name, raw, TelefonKanonisch.bytes(body))
            for (record in body.getValue("records").jsonArray) {
                val records = JsonArray(listOf(record))
                val single = JsonObject(body + ("records" to records) +
                    if (body.containsKey("records_hash")) mapOf("records_hash" to JsonPrimitive(hash(TelefonKanonisch.bytes(records)))) else emptyMap())
                PersonalSyncProtokoll.validate("personal_sync.batch", single)
            }
            val valid = item.getValue("valid").jsonPrimitive.boolean
            assertEquals(name, valid, runCatching { PersonalSyncProtokoll.validate("personal_sync.batch", body) }.isSuccess)
            val envelope = runCatching { PersonalSyncActor.wrap(body.getValue("run_id").jsonPrimitive.content, "personal_sync.batch", body) }
            assertEquals(name, valid, envelope.isSuccess)
            if (valid) {
                assertEquals(name, "personal_sync.batch" to body, PersonalSyncActor.unwrap(envelope.getOrThrow()))
                assertTrue(name, TelefonKanonisch.bytes(envelope.getOrThrow()).size < 256 * 1024)
            }
        }
    }
}
