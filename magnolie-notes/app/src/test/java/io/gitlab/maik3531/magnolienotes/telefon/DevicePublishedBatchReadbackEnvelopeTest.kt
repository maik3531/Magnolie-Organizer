package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DevicePublishedBatchReadbackEnvelopeTest {
    private val fixture = Json.parseToJsonElement(File("../contracts/file-published-readback-batch-v2-vectors.json").readText()).jsonObject
    private val message = fixture.getValue("message").jsonObject
    private val offer = fixture.getValue("offer").jsonObject
    private val now = fixture.long("now_ms")
    private val body = message.getValue("body").jsonObject
    private val context = JsonObject(body - setOf("destination_token", "binding_sha256", "readback_sha256"))
    private val binding = fixture.getValue("binding").jsonObject.let {
        DeviceTransferBinding(it.string("sender_id"), it.string("receiver_id"), it.string("sender_identity_sha256"),
            it.string("receiver_identity_sha256"), it.string("permission_epoch"), it.string("destination_token"))
    }

    private fun parse(frame: JsonObject = message, receiver: DeviceTransferBinding = binding) =
        DevicePublishedBatchReadbackEnvelope.parse(frame, offer, receiver, GalleryMediaType.IMAGES, now)

    @Test fun sharedVectorIsByteExactButNotSavedOrSingleFileReadback() {
        assertEquals(binding.destinationToken, DevicePublishedBatchReadbackEnvelope.destinationToken(context))
        assertEquals(body, DevicePublishedBatchReadbackEnvelope.encodeBody(context, binding))
        val result = parse()
        assertEquals(body, result.body)
        assertFalse(result.grantsWriteAuthority)
        assertFalse(result.isSavedReceipt)
        assertFalse(result.allowsChunkOutput)
        assertThrows(Exception::class.java) {
            DevicePublishedReadbackEnvelope.parse(message, offer, binding, GalleryMediaType.IMAGES, now)
        }
    }

    @Test fun rehashedSubsetAndSubstitutionDoNotProveTheOriginalOffer() {
        val members = context.getValue("members").jsonObject
        val fileId = members.keys.last()
        val row = members.getValue(fileId).jsonObject
        val variants = listOf(members - fileId, members - fileId + ("6".repeat(32) to row),
            members + (fileId to JsonObject(row + ("size" to JsonPrimitive(row.long("size") + 1)))),
            members + (fileId to JsonObject(row + ("sha256" to JsonPrimitive("0".repeat(64))))))
        for (variant in variants) {
            val changed = JsonObject(context + ("members" to JsonObject(variant)))
            val receiver = binding.copy(destinationToken = DevicePublishedBatchReadbackEnvelope.destinationToken(changed))
            val forged = DevicePublishedBatchReadbackEnvelope.encodeBody(changed, receiver)
            assertThrows(Exception::class.java) { parse(JsonObject(message + ("body" to forged)), receiver) }
        }
    }

    @Test fun rowAliasesAndNonIntegerSizesAreRejectedBeforeEncoding() {
        val members = context.getValue("members").jsonObject
        val first = members.values.first().jsonObject
        val last = members.entries.last()
        val changes = mapOf("row_sha256" to first.getValue("row_sha256"),
            "publication_sha256" to first.getValue("publication_sha256"),
            "size" to JsonPrimitive("456"), "mime_type" to JsonPrimitive("video/mp4"))
        for (change in changes) {
            val changed = JsonObject(members + (last.key to JsonObject(last.value.jsonObject + (change.key to change.value))))
            assertThrows(Exception::class.java) {
                DevicePublishedBatchReadbackEnvelope.destinationToken(JsonObject(context + ("members" to changed)))
            }
        }
    }

    @Test fun receiptCannotExtendTheOfferLifetimeOrMoveToAnotherPair() {
        for (expiry in listOf(now, offer.long("expires_ms") + 1)) {
            assertThrows(Exception::class.java) {
                parse(JsonObject(message + ("expires_ms" to JsonPrimitive(expiry))))
            }
        }
        assertThrows(Exception::class.java) { parse(receiver = binding.copy(receiverIdentitySha256 = "0".repeat(64))) }
        assertThrows(Exception::class.java) {
            parse(JsonObject(message + ("body" to JsonObject(body + ("readback_sha256" to JsonPrimitive("0".repeat(64)))))))
        }
    }
}
