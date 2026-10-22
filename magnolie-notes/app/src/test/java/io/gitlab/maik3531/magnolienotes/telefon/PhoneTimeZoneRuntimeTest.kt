package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.Provider
import java.security.Security
import java.util.Base64
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class PhoneTimeZoneRuntimeTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    private fun check(scenario: String) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("TimeZoneFixture", 1.0, "Synthetic keys") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val originalZone = TimeZone.getDefault(); TimeZone.setDefault(TimeZone.getTimeZone("Asia/Tokyo"))
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        val oldStorage = field(TelefonAblage::class.java, "instance").get(null)
        val oldWork = field(TelefonWerk::class.java, "instance").get(null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        field(TelefonAblage::class.java, "instance").set(null, null); field(TelefonWerk::class.java, "instance").set(null, null)
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        val storage = TelefonAblage.get(context); storage.identity("Native timezone fixture").second.fill(0)
        storage.setEnabled(true); storage.setPersonalSync(true, false, false, false, false)
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Owned desktop", TelefonKrypto.b64(ByteArray(32) { 23 }),
            own_device = true, remote_own_device = true, device_status_granted = true, remote_device_status_granted = true,
            remote_device_status_available = true, remote_device_status_versions = listOf(1, 12))
        storage.savePeer(peer)
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        val wireOutput = ByteArrayOutputStream()
        val pipe = object : TelefonRoehre { override val input = ByteArrayInputStream(ByteArray(0)); override val output = wireOutput; override fun close() {} }
        field(TelefonWerk::class.java, "activeTransport").set(work, (if (scenario == "bluetooth") TelefonTransportArt.BLUETOOTH else TelefonTransportArt.WIFI) to pipe)
        try {
            documents.aendereZeiterfassung { ZeiterfassungStand(enabled = true) }
            val before = File(context.filesDir, "notizen.json").readBytes()
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                val session = PersonalNoteSession().apply {
                    capabilitiesReceived = scenario != "stale_capabilities"; grantsReceived = scenario != "stale_grants"; ownSettingsReceived = scenario != "stale_own"
                }
                @Suppress("UNCHECKED_CAST")
                (field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>)[channel] = session
                if (scenario == "own_off") storage.savePeer(peer.copy(remote_own_device = false))
                val request = buildJsonObject { put("version", 12); put("request_id", UUID.randomUUID().toString()) }
                val message = TelefonNachrichten.message("device_status.request", request, 60000)
                work.receiveMessage(peer, message, channel, if (scenario == "wrong_generation") 1 else 0)
                val input = ByteArrayInputStream(wireOutput.toByteArray()); val replies = mutableListOf<JsonObject>()
                while (input.available() > 0) {
                    val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
                    val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 11 }, TelefonKrypto.nonce(ByteArray(4) { 12 }, envelope.long("seq")),
                        Base64.getDecoder().decode(envelope.string("ciphertext")), TelefonKanonisch.bytes(JsonObject(envelope - "ciphertext")))
                    try { replies += TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject }
                    finally { clear.fill(0) }
                }
                val reports = replies.filter { it["kind"] == JsonPrimitive("device_status.report") }
                if (scenario in setOf("wifi", "bluetooth")) {
                    val report = reports.single()["body"]!!.jsonObject; PhoneTimeZone.validateReport(report)
                    assertEquals(request.string("request_id"), report.string("request_id")); assertEquals("Asia/Tokyo", report.string("time_zone"))
                } else assertTrue(reports.isEmpty())
                assertArrayEquals(before, File(context.filesDir, "notizen.json").readBytes())
            }
        } finally {
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, false)
            field(TelefonWerk::class.java, "activeChannel").set(work, null); field(TelefonWerk::class.java, "activeTransport").set(work, null)
            field(TelefonWerk::class.java, "instance").set(null, oldWork); field(TelefonAblage::class.java, "instance").set(null, oldStorage)
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            Security.removeProvider(provider.name); TimeZone.setDefault(originalZone)
        }
    }

    @Test fun actualChannelReportsClockOverWifiAndBluetoothWithoutWritingContent() { check("wifi"); check("bluetooth") }
    @Test fun cachedOrRevokedControlsAndWrongGenerationDoNotReportLocationClock() {
        for (scenario in listOf("stale_capabilities", "stale_grants", "stale_own", "own_off", "wrong_generation")) check(scenario)
    }
}
