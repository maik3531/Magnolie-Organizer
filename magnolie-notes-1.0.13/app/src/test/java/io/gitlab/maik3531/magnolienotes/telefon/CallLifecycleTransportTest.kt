package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.telecom.TelecomManager
import android.telecom.VideoProfile
import android.telephony.TelephonyManager
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.annotation.LooperMode
import java.io.File
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.Provider
import java.security.Security
import java.util.UUID

@Implements(TelecomManager::class)
class CallFixtureTelecom {
    companion object {
        var answers = 0
        var ends = 0
        var dials = 0
        var denied = false
        var answerEffect: () -> Unit = {}
    }
    @Implementation fun placeCall(address: Uri, extras: Bundle) {
        assertEquals("tel", address.scheme)
        assertEquals("+12025550123", address.schemeSpecificPart)
        dials++
    }
    @Implementation fun acceptRingingCall(videoState: Int) {
        assertEquals(VideoProfile.STATE_AUDIO_ONLY, videoState)
        answers++
        if (denied) throw SecurityException("fixture: OS restriction")
        answerEffect()
    }
    @Implementation fun endCall(): Boolean {
        ends++
        if (denied) throw SecurityException("fixture: OS restriction")
        return true
    }
}

/** Actual tracker, protocol receiver and encrypted queue; only Telecom effects are captured.
 * Paused loopers never execute recovery/discovery work. No real phone or Android device.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [CallFixtureTelecom::class])
@LooperMode(LooperMode.Mode.PAUSED)
class CallLifecycleTransportTest {
    private lateinit var context: Context
    private lateinit var storage: TelefonAblage
    private lateinit var work: TelefonWerk
    private lateinit var calls: EingehendeAnrufe
    private lateinit var queue: TelefonQueue
    private val peerId = "11111111-1111-4111-8111-111111111111"
    private val dialId = "22222222-2222-4222-8222-222222222222"
    private val endId = "33333333-3333-4333-8333-333333333333"
    private val provider = object : Provider("CallLifecycleFixture", 1.0, "Synthetic keys only") {
        init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
    }
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        storage = TelefonAblage.get(context)
        storage.setEnabled(true); storage.setIncomingCallsEnabled(true); storage.setAnswerCallsEnabled(true)
        storage.savePeer(TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)),
            remote_incoming_call_state_granted = true, remote_answer_call_granted = true,
            remote_answer_call_available = true, remote_end_call_granted = true, remote_end_call_available = true))
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_PHONE_STATE, Manifest.permission.ANSWER_PHONE_CALLS)
        work = TelefonWerk.get(context)
        // Do not start a service, discovery, listeners or real transports.
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as java.util.concurrent.atomic.AtomicBoolean).set(true)
        calls = field(TelefonWerk::class.java, "incoming").get(work) as EingehendeAnrufe
        field(EingehendeAnrufe::class.java, "serviceRunning").setBoolean(calls, true)
        field(EingehendeAnrufe::class.java, "incomingListening").setBoolean(calls, true)
        queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
        CallFixtureTelecom.answers = 0; CallFixtureTelecom.ends = 0; CallFixtureTelecom.dials = 0
        CallFixtureTelecom.denied = false; CallFixtureTelecom.answerEffect = {}
    }
    @After fun cleanup() {
        work.serviceStopped()
        field(TelefonWerk::class.java, "instance").set(null, null)
        field(TelefonAblage::class.java, "instance").set(null, null)
        Security.removeProvider(provider.name)
    }
    private fun state(value: Int, generation: Int? = null) {
        Shadows.shadowOf(context.getSystemService(TelephonyManager::class.java)).setCallState(value)
        EingehendeAnrufe::class.java.getDeclaredMethod("changed", Int::class.javaPrimitiveType,
            String::class.java, Int::class.javaPrimitiveType).apply { isAccessible = true }.invoke(calls, value, "",
            generation ?: field(EingehendeAnrufe::class.java, "listenerGeneration").getInt(calls))
    }
    private fun events() = queue.due(peerId, TelefonTransportArt.WIFI).map { it.payload }
        .filter { it.string("kind") == "incoming_call_state.event" }.map { it["body"]!!.jsonObject }
    private fun current() = events().maxBy { it.long("revision") }
    private fun command(kind: String, body: JsonObject) = command(TelefonNachrichten.message(kind, body, 10_000))
    private fun command(message: JsonObject) {
        val receive = TelefonWerk::class.java.getDeclaredMethod("receiveMessage", TelefonPeer::class.java,
            JsonObject::class.java, kotlin.jvm.functions.Function1::class.java).apply { isAccessible = true }
        val replies = mutableListOf<JsonObject>()
        receive.invoke(work, storage.peers().peer, message,
            { value: JsonObject -> replies.add(value); Unit })
        assertTrue(replies.isNotEmpty())
    }
    private fun sentMessages(): List<JsonObject> {
        val bytes = ByteArrayOutputStream()
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = bytes
            override fun close() = Unit
        }
        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        val channel = TelefonSecureChannel(pipe.input, bytes, ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4))
        TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java)
            .apply { isAccessible = true }.invoke(work, storage.peers().peer, channel)
        val input = ByteArrayInputStream(bytes.toByteArray())
        return buildList { while (input.available() > 0) {
            val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            val header = JsonObject(envelope.filterKeys { it != "ciphertext" })
            val cipher = java.util.Base64.getDecoder().decode(envelope.string("ciphertext"))
            val clear = TelefonKrypto.entschluesseln(ByteArray(32), TelefonKrypto.nonce(ByteArray(4), envelope.long("seq")), cipher, TelefonKanonisch.bytes(header))
            add(TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject)
        } }
    }
    @Test fun outgoingKeepsDirectionAndIdAcrossInitialIdleWireStartOffhookIdle() {
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.CALL_PHONE)
        Shadows.shadowOf(context.packageManager).setSystemFeature(PackageManager.FEATURE_TELEPHONY, true)
        storage.setDialRequestEnabled(true)
        val result = Waehlauftrag.submit(context, buildJsonObject {
            put("client_ref", dialId); put("to", "+12025550123")
        })
        assertEquals(result.toString(), "submitted", result.first)
        assertEquals(1, CallFixtureTelecom.dials)
        state(TelephonyManager.CALL_STATE_IDLE)
        assertEquals(1, events().size)
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        state(TelephonyManager.CALL_STATE_IDLE)
        val trace = events().sortedBy { it.long("revision") }
        assertEquals(listOf("ringing", "offhook", "idle"), trace.map { it.string("state") })
        assertTrue(trace.all { it.string("direction") == "outgoing" && it.string("call_ref") == dialId && it.string("control_origin") == "desktop" })
        export("outgoing", trace)
        // An interrupted attempt can leave only its at-most-once marker, with
        // no durable OS result. It must neither redial nor invent submission.
        val interruptedId = UUID.randomUUID().toString()
        assertTrue(TelefonEffekte(context).firstEvent("dial:$interruptedId"))
        val retry = Waehlauftrag.submit(context, buildJsonObject {
            put("client_ref", interruptedId); put("to", "+12025550123")
        })
        assertEquals("failed", retry.first)
        assertEquals(1, CallFixtureTelecom.dials)
        assertEquals(trace, events().sortedBy { it.long("revision") })
    }
    @Test fun explicitOutgoingWithGlobalIncomingAndEndGrantsOff() {
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.CALL_PHONE)
        Shadows.shadowOf(context.packageManager).setSystemFeature(PackageManager.FEATURE_TELEPHONY, true)
        storage.setDialRequestEnabled(true); storage.setIncomingCallsEnabled(false); storage.setAnswerCallsEnabled(false)
        field(EingehendeAnrufe::class.java, "incomingListening").setBoolean(calls, false)
        val capabilities = TelefonCapabilities.phase1(dialRequest = true, dialResolvable = true, dialPermission = true)
            .toMutableMap().apply { this["dial_request"] = TelefonCapability(true, "available", listOf(1, 2)) }
        command("capabilities.update", TelefonNachrichten.capabilities(10, capabilities))
        command("grants.update", TelefonNachrichten.grants(10, dialRequest = true))
        val dial = TelefonNachrichten.message("dial_request.command", buildJsonObject { put("client_ref", dialId); put("to", "+12025550123") }, 60_000)
        command(dial); command(dial)
        assertEquals(1, CallFixtureTelecom.dials)
        state(TelephonyManager.CALL_STATE_IDLE)
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        val beforeEnd = events().sortedBy { it.long("revision") }
        // Export the failed baseline too; this is generated by the real tracker/queue.
        export("scoped-before-end", beforeEnd)
        assertEquals(listOf("ringing", "offhook"), beforeEnd.map { it.string("state") })
        for ((ref, revision, state) in listOf(Triple(UUID.randomUUID().toString(), 2L, "offhook"),
            Triple(dialId, 1L, "offhook"), Triple(dialId, 2L, "ringing"))) {
            command("end_call.command", buildJsonObject { put("command_ref", UUID.randomUUID().toString()); put("call_ref", ref)
                put("expected_revision", revision); put("expected_state", state) })
        }
        command("answer_call.command", buildJsonObject { put("command_ref", UUID.randomUUID().toString()); put("call_ref", dialId); put("expected_state", "ringing") })
        assertEquals(0, CallFixtureTelecom.ends); assertEquals(0, CallFixtureTelecom.answers)
        command("end_call.command", buildJsonObject {
            put("command_ref", endId); put("call_ref", dialId)
            put("expected_revision", beforeEnd.last().long("revision")); put("expected_state", "offhook")
        })
        assertEquals(1, CallFixtureTelecom.ends)
        state(TelephonyManager.CALL_STATE_IDLE)
        val trace = events().sortedBy { it.long("revision") }
        assertEquals(listOf("ringing", "offhook", "idle"), trace.map { it.string("state") })
        export("scoped-outgoing", trace)
        val unknown = JsonObject(trace.first() + mapOf("call_ref" to JsonPrimitive(UUID.randomUUID().toString()), "direction" to JsonPrimitive("incoming")))
        work.publish("incoming_call_state.event", unknown, 60_000)
        assertEquals(3, events().size)
        // Also inject directly into the durable queue to test the second (send-time) filter.
        queue.queue(peerId, "incoming_call_state.event", unknown, 60_000)
        val sent = sentMessages()
        val lifecycle = sent.filter { it.string("kind") == "incoming_call_state.event" }.map { it["body"]!!.jsonObject }.sortedBy { it.long("revision") }
        assertEquals(trace, lifecycle)
        export("scoped-wire-messages", sent)
        command("dial_request.command", buildJsonObject { put("client_ref", dialId); put("to", "+12025550123") })
        assertEquals(1, CallFixtureTelecom.dials)
        command("end_call.command", buildJsonObject { put("command_ref", UUID.randomUUID().toString()); put("call_ref", dialId)
            put("expected_revision", 3); put("expected_state", "offhook") })
        assertEquals(1, CallFixtureTelecom.ends)
        assertFalse(storage.peers().peer!!.remote_incoming_call_state_granted)
        assertFalse(storage.peers().peer!!.remote_end_call_granted)
        assertFalse(storage.peers().peer!!.remote_answer_call_granted)
    }
    private fun coldDial(version: Int = 2) {
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.CALL_PHONE)
        Shadows.shadowOf(context.packageManager).setSystemFeature(PackageManager.FEATURE_TELEPHONY, true)
        storage.setDialRequestEnabled(true); storage.setIncomingCallsEnabled(false); storage.setAnswerCallsEnabled(false)
        field(EingehendeAnrufe::class.java, "incomingListening").setBoolean(calls, false)
        val caps = TelefonCapabilities.phase1(dialRequest = true, dialResolvable = true, dialPermission = true).toMutableMap()
        caps["dial_request"] = TelefonCapability(true, "available", (1..version).toList())
        command("capabilities.update", TelefonNachrichten.capabilities(10, caps))
        command("grants.update", TelefonNachrichten.grants(10, dialRequest = true))
        command("dial_request.command", buildJsonObject { put("client_ref", dialId); put("to", "+12025550123") })
        assertEquals(1, CallFixtureTelecom.dials)
    }
    @Test fun queuedScopeDoesNotReviveAfterRemoteDialRevocation() {
        coldDial()
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        assertEquals(2, events().size)
        command("grants.update", TelefonNachrichten.grants(11, dialRequest = false))
        command("grants.update", TelefonNachrichten.grants(12, dialRequest = true))
        assertTrue(sentMessages().none { it.string("kind") == "incoming_call_state.event" })
        command("end_call.command", buildJsonObject { put("command_ref", endId); put("call_ref", dialId)
            put("expected_revision", 2); put("expected_state", "offhook") })
        assertEquals(0, CallFixtureTelecom.ends)
    }
    @Test fun incomingOsRingingCannotInheritPendingOutgoingIdentity() {
        coldDial()
        state(TelephonyManager.CALL_STATE_RINGING)
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        val trace = events().sortedBy { it.long("revision") }
        assertEquals(listOf("ringing", "idle"), trace.map { it.string("state") })
        assertTrue(trace.all { it.string("direction") == "outgoing" && it.string("call_ref") == dialId })
        command("end_call.command", buildJsonObject { put("command_ref", endId); put("call_ref", dialId)
            put("expected_revision", 2); put("expected_state", "offhook") })
        assertEquals(0, CallFixtureTelecom.ends)
        assertEquals(0, CallFixtureTelecom.answers)
        export("scoped-incoming-collision", trace)
    }
    @Test fun unobservedOutgoingTimeoutTerminatesAssociationOnlyOnce() {
        coldDial()
        state(TelephonyManager.CALL_STATE_IDLE)
        val expire = EingehendeAnrufe::class.java.getDeclaredMethod("expireUnobservedOutgoing").apply { isAccessible = true }
        expire.invoke(calls); expire.invoke(calls)
        val trace = events().sortedBy { it.long("revision") }
        assertEquals(listOf("ringing", "idle"), trace.map { it.string("state") })
        assertEquals(0L, trace.last().long("offhook_ms"))
        assertEquals(1, CallFixtureTelecom.dials)
        export("scoped-timeout", trace)
    }
    @Test fun localDialRevocationAndPermissionLossDenyQueuedScopeAndEnd() {
        coldDial()
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        work.setDialRequestEnabled(false)
        assertTrue(sentMessages().none { it.string("kind") == "incoming_call_state.event" })
        work.setDialRequestEnabled(true)
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.READ_PHONE_STATE)
        work.runtimePermissionsChanged()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_PHONE_STATE)
        command("end_call.command", buildJsonObject { put("command_ref", endId); put("call_ref", dialId)
            put("expected_revision", 2); put("expected_state", "offhook") })
        assertEquals(0, CallFixtureTelecom.ends)
        assertTrue(sentMessages().none { it.string("kind") == "incoming_call_state.event" })
    }
    @Test fun unpairRekeyCannotInheritCapturedOutgoingScope() {
        coldDial()
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        val old = storage.peers().peer!!
        work.unpair()
        storage.savePeer(old.copy(static_public = TelefonKrypto.b64(ByteArray(32) { 1 })))
        assertTrue(sentMessages().none { it.string("kind") == "incoming_call_state.event" })
        command("end_call.command", buildJsonObject { put("command_ref", endId); put("call_ref", dialId)
            put("expected_revision", 2); put("expected_state", "offhook") })
        assertEquals(0, CallFixtureTelecom.ends)
    }
    @Test fun oldDesktopKeepsExactLegacyDialectWithoutImplicitScope() {
        coldDial(1)
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        assertTrue(events().isEmpty())
        assertTrue(sentMessages().none { it.string("kind") == "incoming_call_state.event" })
        val grants = TelefonNachrichten.grants(11, dialRequest = true, incomingCalls = true)
        command("grants.update", grants)
        state(TelephonyManager.CALL_STATE_IDLE)
        assertEquals(listOf("idle"), events().map { it.string("state") })
    }
    @Test fun incomingCommandInvokesTelecomButOnlyCallbackChangesStateAndOrigin() {
        state(TelephonyManager.CALL_STATE_RINGING)
        val ringing = current(); val id = ringing.string("call_ref")
        val command = buildJsonObject { put("command_ref", UUID.randomUUID().toString()); put("call_ref", id); put("expected_state", "ringing") }
        command("answer_call.command", command)
        assertEquals(1, CallFixtureTelecom.answers)
        assertEquals("ringing", current().string("state"))
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        assertEquals("desktop", current().string("control_origin"))
        state(TelephonyManager.CALL_STATE_IDLE)
        val trace = events().sortedBy { it.long("revision") }
        assertEquals(listOf("ringing", "offhook", "idle"), trace.map { it.string("state") })
        assertTrue(trace.all { it.string("call_ref") == id && it.string("direction") == "incoming" && it.string("number").isEmpty() })
        export("incoming", trace)
    }
    @Test fun synchronousOffhookDuringOsCallRetainsDesktopOrigin() {
        state(TelephonyManager.CALL_STATE_RINGING)
        CallFixtureTelecom.answerEffect = { state(TelephonyManager.CALL_STATE_OFFHOOK) }
        assertEquals("submitted", calls.answer(UUID.randomUUID().toString(), current().string("call_ref")).first)
        assertEquals("desktop", current().string("control_origin"))
    }
    @Test fun staleIdsGenerationsMissingPermissionsAndOsRestrictionsNeverFakeSuccess() {
        state(TelephonyManager.CALL_STATE_RINGING)
        val id = current().string("call_ref")
        assertEquals("failed", calls.answer(UUID.randomUUID().toString(), dialId).first)
        state(TelephonyManager.CALL_STATE_OFFHOOK, -1)
        assertEquals("ringing", current().string("state"))
        state(TelephonyManager.CALL_STATE_RINGING)
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.ANSWER_PHONE_CALLS)
        assertEquals("permission_missing", calls.answer(UUID.randomUUID().toString(), id).second)
        assertEquals(0, CallFixtureTelecom.answers)
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.ANSWER_PHONE_CALLS)
        CallFixtureTelecom.denied = true
        val attempted = UUID.randomUUID().toString()
        assertEquals("failed", calls.answer(attempted, id).first)
        assertEquals("failed", calls.answer(attempted, id).first)
        assertEquals(1, CallFixtureTelecom.answers)
        state(TelephonyManager.CALL_STATE_OFFHOOK)
        assertEquals("phone", current().string("control_origin"))
    }
    @Test fun rejectRequiresSameRevisionAndUsesEndCallWithoutInventingIdle() {
        state(TelephonyManager.CALL_STATE_RINGING)
        val id = current().string("call_ref")
        assertEquals("stale_call", calls.end(UUID.randomUUID().toString(), id, 2, "ringing").second)
        command("end_call.command", buildJsonObject {
            put("command_ref", UUID.randomUUID().toString()); put("call_ref", id)
            put("expected_revision", 1); put("expected_state", "ringing")
        })
        assertEquals(1, CallFixtureTelecom.ends)
        assertEquals("ringing", current().string("state"))
    }
    private fun export(name: String, trace: List<JsonObject>) {
        System.getenv("MAGNOLIE_CALL_TRACE_DIR")?.let { directory ->
            File(directory, "$name.json").writeText(JsonArray(trace).toString())
        }
    }
}
