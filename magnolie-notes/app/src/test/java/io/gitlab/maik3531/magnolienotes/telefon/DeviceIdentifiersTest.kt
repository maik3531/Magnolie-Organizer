package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DeviceIdentifiersTest {
    private class Source(override val sdk: Int, override val phonePermission: Boolean = true,
                         override val statePermission: Boolean = true, val subscription: Int = 7) : DeviceIdentifierSource {
        var reads = 0
        var denied = false
        override fun defaultVoiceSubscription() = subscription
        override fun phoneNumber(subscription: Int): String { check(subscription == 7); reads++; if (denied) throw SecurityException(); return "001234" }
        override fun serial(): String { reads++; if (denied) throw SecurityException(); return "fixture-serial" }
        override fun imei(subscription: Int): String { check(subscription == 7); reads++; if (denied) throw SecurityException(); return "000000000000001" }
    }
    @Test fun api28EligibleAndLeadingZerosRemainStrings() {
        val source = Source(28); val result = DeviceIdentifiers.collect(source, true)
        assertEquals(3, source.reads)
        assertTrue(result["imei"]!!.jsonObject["value"]!!.jsonPrimitive.isString)
        assertTrue(result["imei"]!!.jsonObject["value"]!!.jsonPrimitive.content.startsWith("0"))
    }
    @Test fun api29And33NeverReadRestrictedHardwareIds() {
        for (api in listOf(29, 33)) {
            val source = Source(api); val result = DeviceIdentifiers.collect(source, true)
            assertEquals(1, source.reads)
            for (name in listOf("serial", "imei")) assertEquals("os_restricted", result[name]!!.jsonObject.string("status"))
        }
    }
    @Test fun deniedMissingSimAndOffDoNotInventValues() {
        val off = Source(28); DeviceIdentifiers.collect(off, false); assertEquals(0, off.reads)
        val denied = Source(28, false, false); val result = DeviceIdentifiers.collect(denied, true)
        assertEquals(0, denied.reads); assertTrue(result.values.all { it.jsonObject.string("status") == "permission_missing" })
        val noSim = Source(33, subscription = -1); val absent = DeviceIdentifiers.collect(noSim, true)
        assertEquals(0, noSim.reads); assertEquals("no_subscription", absent["phone_number"]!!.jsonObject.string("status"))
        val revoked = Source(28).also { it.denied = true }; val unavailable = DeviceIdentifiers.collect(revoked, true)
        assertTrue(unavailable.values.all { it.jsonObject.string("value").isEmpty() })
    }
    @Test fun exactNegotiationAndFalseRequests() {
        val body = buildJsonObject { put("request_id", "11111111-1111-4111-8111-111111111111"); put("version", 4); put("include_identifiers", false) }
        TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", body, 60000))
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", JsonObject(body - "include_identifiers"), 60000))
        }
        assertEquals(11, TelefonCapabilities.phase1(identifiers = true).size)
        assertFalse(4 in TelefonCapabilities.phase1().getValue("device_status").versions)
        assertTrue(4 in TelefonCapabilities.phase1(identifiers = true).getValue("device_status").versions)
    }
}
