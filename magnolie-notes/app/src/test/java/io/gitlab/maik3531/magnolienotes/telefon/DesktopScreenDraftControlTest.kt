package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class DesktopScreenDraftControlTest {
    private val vectors = Json.parseToJsonElement(File("../contracts/desktop-screen-control-draft-v1-vectors.json").readText()).jsonObject
    private val request = vectors.getValue("request").jsonObject
    private val offerFields = vectors.getValue("offer_fields").jsonObject

    @Test fun sharedVectorsAcceptExactOperationsOnlyFromCorrectRole() {
        val phone = DesktopScreenDraftControl.Role.PHONE
        val desktop = DesktopScreenDraftControl.Role.DESKTOP
        fun body(op: String, extra: JsonObject) = JsonObject(request + extra + ("op" to JsonPrimitive(op)))
        val offer = body("offer", offerFields)
        val stop = body("stop", JsonObject(mapOf("session" to offerFields.getValue("session"))))
        val receipt = JsonObject(mapOf("session" to offerFields.getValue("session"), "transcript" to vectors.getValue("transcript")))
        for ((message, role) in listOf(request to phone, offer to desktop, body("prepared", receipt) to phone,
            body("send", receipt) to desktop)) {
            assertEquals(message, DesktopScreenDraftControl.validate(message, role))
            assertThrows(IllegalArgumentException::class.java) {
                DesktopScreenDraftControl.validate(message, if (role == phone) desktop else phone)
            }
        }
        assertEquals(stop, DesktopScreenDraftControl.validate(stop, phone))
        assertEquals(stop, DesktopScreenDraftControl.validate(stop, desktop))
    }

    @Test fun sharedMutationsDoNotAdmitAddressesInputOrMalformedMetadata() {
        val offer = request + offerFields + ("op" to JsonPrimitive("offer"))
        for (mutation in vectors.getValue("bad_offer_mutations").jsonArray) {
            assertThrows(IllegalArgumentException::class.java) {
                DesktopScreenDraftControl.validate(JsonObject(offer + mutation.jsonObject), DesktopScreenDraftControl.Role.DESKTOP)
            }
        }
    }
}
