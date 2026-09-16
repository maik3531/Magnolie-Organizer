package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.booleanOrNull
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID

internal fun JsonObject.string(name: String): String =
    (getValue(name) as? JsonPrimitive)?.takeIf { it.isString }?.content
        ?: throw TelefonProtokollFehler("Falscher Feldtyp: $name")

internal fun JsonObject.long(name: String): Long =
    (getValue(name) as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull()
        ?: throw TelefonProtokollFehler("Falscher Feldtyp: $name")

object TelefonNachrichten {
    private val uuid4 = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    fun message(kind: String, body: JsonObject, ttlMs: Long, now: Long = System.currentTimeMillis(),
                id: String = UUID.randomUUID().toString()): JsonObject {
        require(ttlMs in 1..2_592_000_000L)
        return buildJsonObject {
            put("type", JsonPrimitive("message")); put("v", JsonPrimitive(1)); put("message_id", JsonPrimitive(id))
            put("kind", JsonPrimitive(kind)); put("created_ms", JsonPrimitive(now)); put("expires_ms", JsonPrimitive(now + ttlMs))
            put("body", body)
        }
    }

    fun capabilities(revision: Long = 1, itemsValue: Map<String, TelefonCapability> = TelefonCapabilities.phase1()): JsonObject = buildJsonObject {
        put("revision", JsonPrimitive(revision))
        put("items", JsonObject(itemsValue.mapValues { (_, value) -> buildJsonObject {
            put("available", JsonPrimitive(value.available)); put("reason", JsonPrimitive(value.reason))
            put("versions", JsonArray(value.versions.map(::JsonPrimitive)))
        }}))
    }

    fun grants(revision: Long = 1, notifications: Boolean = false, dialRequest: Boolean = false,
                incomingCalls: Boolean = false, incomingNumber: Boolean = false,
                answerCalls: Boolean = false, endCalls: Boolean = false,
                personalNotes: Boolean = false, personalTasks: Boolean = false,
                personalDeletions: Boolean = false): JsonObject = buildJsonObject {
        put("revision", JsonPrimitive(revision)); put("grants", buildJsonObject {
            put("device_status", JsonPrimitive(true)); put("selected_notifications_readonly", JsonPrimitive(notifications))
            put("dial_request", JsonPrimitive(dialRequest))
            put("incoming_call_state", JsonPrimitive(incomingCalls))
            put("incoming_call_number", JsonPrimitive(incomingNumber))
            put("answer_call", JsonPrimitive(answerCalls))
            put("end_call", JsonPrimitive(endCalls))
            put("personal_notes_sync", JsonPrimitive(personalNotes))
            put("personal_tasks_sync", JsonPrimitive(personalTasks))
            put("personal_deletions_sync", JsonPrimitive(personalDeletions))
        })
    }

    fun ack(id: String, status: String, error: String) = buildJsonObject {
        put("type", JsonPrimitive("ack")); put("message_id", JsonPrimitive(id))
        put("status", JsonPrimitive(status)); put("error", JsonPrimitive(error))
    }

    fun validate(message: JsonObject, now: Long = System.currentTimeMillis()) {
        validateHeader(message, now)
        val created = message.long("created_ms"); val expires = message.long("expires_ms")
        val body = message["body"] as? JsonObject ?: fail()
        when (message.string("kind")) {
            "device_status.request" -> {
                if (body.keys == setOf("request_id")) uuid(body.string("request_id"))
                else if (body.keys == setOf("request_id", "version", "include_identifiers")) {
                    uuid(body.string("request_id"))
                    if (body.long("version") != 4L || (body["include_identifiers"] as? JsonPrimitive)?.let {
                        !it.isString && it.booleanOrNull != null } != true) fail()
                }
                else {
                    exact(body, setOf("request_id", "version")); uuid(body.string("request_id"))
                    if (body.long("version") !in 1L..3L) fail()
                }
                if (expires - created > 60_000L) fail()
            }
            "dial_request.command" -> validateDialRequest(body, expires - created)
            "dial_request.result" -> validateDialResult(body, expires - created)
            "selected_notifications_readonly.event" -> validateNotification(body, expires - created)
            "incoming_call_state.event" -> validateIncomingCall(body, expires - created)
            "answer_call.command" -> validateAnswerCommand(body, expires - created)
            "answer_call.result" -> validateAnswerResult(body, expires - created)
            "end_call.command" -> validateEndCommand(body, expires - created)
            "end_call.result" -> validateEndResult(body, expires - created)
            "capabilities.update" -> { if (expires - created > 86_400_000L) fail(); validateCapabilities(body) }
            "grants.update" -> { if (expires - created > 86_400_000L) fail(); validateGrants(body) }
            "personal_sync.custom_settings", "personal_sync.custom_request", "personal_sync.custom_batch" -> {
                if (expires - created > 86_400_000L) fail(); PersonalSyncProtokoll.validateCustomBody(message.string("kind"), body)
            }
            "personal_sync.settings" -> { if (expires - created > 86_400_000L) fail(); PersonalSyncProtokoll.validate(message.string("kind"), body) }
            "personal_sync.request" -> { if (expires - created > 3_600_000L) fail(); PersonalSyncProtokoll.validate(message.string("kind"), body) }
            "personal_sync.batch", "personal_sync.report", "personal_sync.attachment_request",
            "personal_sync.attachment_chunk", "personal_sync.attachment_result", "personal_sync.deletion_proposals",
            "personal_sync.deletion_decision" -> {
                if (expires - created > 86_400_000L) fail(); PersonalSyncProtokoll.validate(message.string("kind"), body)
            }
            else -> fail()
        }
    }

    private fun validateDialRequest(body: JsonObject, ttl: Long) {
        exact(body, setOf("client_ref", "to")); uuid4(body.string("client_ref"))
        if (ttl > 60_000L || !Regex("\\+[0-9]{3,15}").matches(body.string("to"))) fail()
    }

    private fun validateDialResult(body: JsonObject, ttl: Long) {
        exact(body, setOf("client_ref", "state", "error", "occurred_ms")); uuid4(body.string("client_ref"))
        val state = body.string("state"); val error = body.string("error")
        if (ttl > 60_000L || state !in setOf("submitted", "failed") ||
            error !in setOf("none", "invalid_destination", "dial_unavailable", "not_granted",
                "permission_missing", "no_telephony", "os_restricted", "unknown") ||
            (state == "failed") != (error != "none") || body.long("occurred_ms") !in 0..253_402_300_799_999L) fail()
    }

    private fun validateNotification(body: JsonObject, ttl: Long) {
        exact(body, setOf("notification_id", "event", "package", "app_label", "title", "text", "posted_ms",
            "is_default_sms_app"))
        uuid(body.string("notification_id")); val event = body.string("event")
        if (ttl > 86_400_000 || event !in setOf("posted", "removed") || body.string("package").length !in 1..255 ||
            body.string("app_label").length > 80 || body.string("title").length > 500 || body.string("text").length > 5000 ||
            invalidControl(body.string("title")) || invalidControl(body.string("text")) ||
            (body["is_default_sms_app"] as? JsonPrimitive)?.booleanOrNull == null ||
            body.long("posted_ms") !in 0..253_402_300_799_999L || event == "removed" &&
            (body.string("title").isNotEmpty() || body.string("text").isNotEmpty())) fail()
    }

    private fun validateIncomingCall(body: JsonObject, ttl: Long) {
        exact(body, setOf("call_ref", "revision", "state", "direction", "number", "number_status", "started_ms",
            "offhook_ms", "ended_ms", "occurred_ms", "spam_status", "control_origin", "battery_percent", "battery_captured_ms"))
        uuid4(body.string("call_ref")); val status = body.string("number_status"); val number = body.string("number")
        if (ttl > 60_000 || body.long("revision") < 1 || body.string("state") !in setOf("ringing", "offhook", "idle") ||
            body.string("direction") !in setOf("incoming", "outgoing", "unknown") || status !in setOf("available", "withheld",
                "unavailable", "permission_missing", "not_shared") || body.string("control_origin") !in setOf("desktop", "phone", "unknown") ||
            (status == "available") != Regex("\\+[0-9]{3,15}").matches(number) ||
            status != "available" && number.isNotEmpty() || body.string("spam_status") !in setOf("suspected", "unknown")) fail()
        val occurred = body.long("occurred_ms"); val started = body.long("started_ms")
        val offhook = body.long("offhook_ms"); val ended = body.long("ended_ms"); val battery = body.long("battery_percent")
        if (occurred !in 0..253_402_300_799_999L || started !in 1..occurred || offhook !in 0..occurred ||
            ended !in 0..occurred || (body.string("state") == "idle") != (ended > 0) ||
            body.string("state") == "offhook" && offhook == 0L || offhook > 0 && offhook < started ||
            ended > 0 && ended < maxOf(started, offhook) || battery !in -1..100 ||
            body.long("battery_captured_ms") !in 0..occurred ||
            (battery < 0) != (body.long("battery_captured_ms") == 0L)) fail()
    }

    private fun validateAnswerCommand(body: JsonObject, ttl: Long) {
        exact(body, setOf("command_ref", "call_ref", "expected_state")); uuid4(body.string("command_ref")); uuid4(body.string("call_ref"))
        if (ttl > 10_000 || body.string("expected_state") != "ringing") fail()
    }

    private fun validateAnswerResult(body: JsonObject, ttl: Long) {
        exact(body, setOf("command_ref", "call_ref", "state", "error", "occurred_ms")); uuid4(body.string("command_ref")); uuid4(body.string("call_ref"))
        val state = body.string("state"); val error = body.string("error")
        if (ttl > 60_000 || state !in setOf("submitted", "already_answered", "failed") || error !in setOf("none", "expired",
                "not_granted", "permission_missing", "not_ringing", "stale_call", "os_restricted", "unknown") ||
            (state == "failed") != (error != "none") || body.long("occurred_ms") !in 0..253_402_300_799_999L) fail()
    }

    private fun validateEndCommand(body: JsonObject, ttl: Long) {
        exact(body, setOf("command_ref", "call_ref", "expected_revision", "expected_state"))
        uuid4(body.string("command_ref")); uuid4(body.string("call_ref"))
        if (ttl > 10_000 || body.long("expected_revision") < 1 || body.string("expected_state") !in setOf("offhook", "ringing")) fail()
    }

    private fun validateEndResult(body: JsonObject, ttl: Long) {
        exact(body, setOf("command_ref", "call_ref", "state", "error", "occurred_ms"))
        uuid4(body.string("command_ref")); uuid4(body.string("call_ref"))
        val state = body.string("state"); val error = body.string("error")
        if (ttl > 60_000 || state !in setOf("submitted", "already_ended", "failed") || error !in setOf("none", "expired",
                "not_granted", "permission_missing", "unsupported_api", "stale_call", "not_active", "os_restricted", "unknown") ||
            (state == "failed") != (error != "none") || body.long("occurred_ms") !in 0..253_402_300_799_999L) fail()
    }

    private fun invalidControl(value: String) = value.any { it.isISOControl() && it !in "\n\t" }

    fun validateHeader(message: JsonObject, now: Long = System.currentTimeMillis()) {
        exact(message, setOf("type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"))
        if (message.string("type") != "message" || message.long("v") != 1L || !uuid4.matches(message.string("message_id"))) fail()
        val created = message.long("created_ms"); val expires = message.long("expires_ms")
        if (created !in 0..253_402_300_799_999L || expires <= created || expires - created > 2_592_000_000L ||
            now > expires + 300_000L || created > now + 300_000L) fail()
        if (message["body"] !is JsonObject) fail()
    }

    fun validateReady(value: JsonObject) {
        exact(value, setOf("type", "connection_id", "capabilities_revision", "last_received_seq"))
        if (value.string("type") != "session_ready" || value.long("capabilities_revision") < 1 ||
            value.long("last_received_seq") != -1L) fail()
        uuid4(value.string("connection_id"))
    }

    fun validateHeartbeat(value: JsonObject) {
        exact(value, setOf("type", "ping_id", "sent_ms"))
        if (value.string("type") !in setOf("ping", "pong")) fail()
        uuid(value.string("ping_id"))
        if (value.long("sent_ms") !in 0..253_402_300_799_999L) fail()
    }

    fun validateAck(value: JsonObject) {
        exact(value, setOf("type", "message_id", "status", "error")); uuid(value.string("message_id"))
        val status = value.string("status"); val error = value.string("error")
        if (status !in setOf("accepted", "duplicate", "rejected") || (status != "rejected" && error != "none") ||
            (status == "rejected" && error !in setOf("expired", "invalid_schema", "unsupported", "not_granted",
                "too_large", "permanent_failure", "restore_unavailable", "conflict"))) fail()
    }

    fun duplicateAck(result: String, error: String): Pair<String, String> =
        if (result == "accepted") "duplicate" to "none" else "rejected" to error

    private fun validateCapabilities(body: JsonObject) {
        exact(body, setOf("revision", "items")); if (body.long("revision") < 1) fail()
        val items = body["items"] as? JsonObject ?: fail()
        if (items.keys != TelefonCapabilities.phase1().keys) fail()
        items.values.forEach { item ->
            val value = item as? JsonObject ?: fail(); exact(value, setOf("available", "reason", "versions"))
            val versions = value["versions"] as? JsonArray ?: fail()
            if ((value["available"] as? JsonPrimitive)?.booleanOrNull == null || value.string("reason") !in
                setOf("available", "not_implemented", "no_hardware", "disabled", "permission_missing", "os_restricted") ||
                ((value["available"] as JsonPrimitive).booleanOrNull == true) != (value.string("reason") == "available") ||
                versions.size !in 1..16 || versions.map { (it as? JsonPrimitive)?.takeIf { part -> !part.isString }?.content?.toIntOrNull() }
                    .let { numbers -> numbers.any { it == null || it !in 1..65_535 } || numbers.distinct().size != numbers.size }) fail()
        }
    }

    private fun validateGrants(body: JsonObject) {
        exact(body, setOf("revision", "grants")); if (body.long("revision") < 1) fail()
        val grants = body["grants"] as? JsonObject ?: fail()
        if (grants.keys != setOf("device_status", "selected_notifications_readonly", "dial_request",
                "incoming_call_state", "incoming_call_number", "answer_call", "end_call",
                "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync") ||
            grants.values.any { (it as? JsonPrimitive)?.booleanOrNull == null }) fail()
    }

    internal fun exact(value: JsonObject, fields: Set<String>) { if (value.keys != fields) fail() }
    internal fun uuid(value: String) { if (runCatching { UUID.fromString(value).toString() == value }.getOrDefault(false).not()) fail() }
    internal fun uuid4(value: String) { uuid(value); if (!uuid4.matches(value)) fail() }
    private fun fail(): Nothing = throw TelefonProtokollFehler("Ungültiges Nachrichtenschema.")
}

object TelefonWiederholung {
    private val delays = longArrayOf(1_000, 2_000, 5_000, 10_000, 30_000, 60_000)
    fun naechsterVersuch(now: Long, attempts: Int): Long = now + delays.getOrNull(attempts).let {
        it ?: 240_000L + SecureRandom().nextInt(120_001)
    }
}

class TelefonSecureChannel(
    private val input: InputStream,
    private val output: OutputStream,
    private val sid: ByteArray,
    private val sendKey: ByteArray,
    private val sendPrefix: ByteArray,
    private val receiveKey: ByteArray,
    private val receivePrefix: ByteArray
) : AutoCloseable {
    private var sendSequence = 0L
    private var receiveSequence = 0L

    @Synchronized fun send(payload: JsonObject) {
        val clear = TelefonKanonisch.bytes(payload)
        if (clear.size > TelefonParameter.ANWENDUNG_MAX) throw TelefonProtokollFehler("Anwendungsnachricht ist zu groß.")
        val header = header(sendSequence, "phone_to_desktop")
        val encrypted = TelefonKrypto.verschluesseln(sendKey, TelefonKrypto.nonce(sendPrefix, sendSequence), clear, TelefonKanonisch.bytes(header))
        sendSequence++
        TelefonRahmen.schreiben(output, JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(encrypted)))),
            TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
    }

    fun receive(): JsonObject {
        val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
        val header = header(receiveSequence, "desktop_to_phone")
        TelefonNachrichten.exact(envelope, header.keys + "ciphertext")
        if (header.any { envelope[it.key] != it.value }) throw TelefonProtokollFehler("Falscher sicherer Umschlag.")
        val cipherText = TelefonKrypto.b64(envelope.string("ciphertext"), Base64Length.any(envelope.string("ciphertext")))
        val clear = try { TelefonKrypto.entschluesseln(receiveKey, TelefonKrypto.nonce(receivePrefix, receiveSequence),
            cipherText, TelefonKanonisch.bytes(header)) } catch (_: Exception) { throw TelefonProtokollFehler("Authentisierung fehlgeschlagen.") }
        receiveSequence++
        if (clear.size > TelefonParameter.ANWENDUNG_MAX) throw TelefonProtokollFehler("Anwendungsnachricht ist zu groß.")
        val value = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString(throwOnInvalidSequence = true)) as? JsonObject
            ?: throw TelefonProtokollFehler("Sicherer Inhalt ist kein Objekt.")
        if (!MessageDigest.isEqual(clear, TelefonKanonisch.bytes(value)))
            throw TelefonProtokollFehler("Sicherer Inhalt ist nicht kanonisch.")
        return value
    }

    private fun header(sequence: Long, direction: String) = buildJsonObject {
        put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("sid", JsonPrimitive(TelefonKrypto.b64(sid)))
        put("seq", JsonPrimitive(sequence)); put("dir", JsonPrimitive(direction))
    }

    override fun close() { sendKey.fill(0); receiveKey.fill(0) }

    private object Base64Length {
        fun any(value: String): Int {
            val raw = try { java.util.Base64.getDecoder().decode(value) } catch (_: Exception) { throw TelefonProtokollFehler("Ungültiges Base64.") }
            if (TelefonKrypto.b64(raw) != value || raw.size < 16) throw TelefonProtokollFehler("Ungültiges Base64.")
            return raw.size
        }
    }
}

data class TelefonSessionSecrets(val start: JsonObject, val sid: ByteArray, val ephemeralPrivate: ByteArray,
                                 val staticRoot: ByteArray, val authKey: ByteArray)

object TelefonSession {
    fun start(identity: TelefonIdentitaet, peer: TelefonPeer, staticPrivate: ByteArray,
              sid: ByteArray = TelefonKrypto.zufall(16), ephemeral: Pair<ByteArray, ByteArray> = TelefonKrypto.schluesselpaar(),
              nonce: ByteArray = TelefonKrypto.zufall(32)): TelefonSessionSecrets {
        val ids = ids(identity.device_id, peer.device_id)
        val root = TelefonKrypto.hkdf(TelefonKrypto.austausch(staticPrivate, TelefonKrypto.b64(peer.static_public, 32)),
            TelefonKrypto.sha256("magnolie-phone-fs1/static-salt\u0000".toByteArray(), ids),
            "magnolie-phone-fs1/static-root\u0000".toByteArray() + ids, 32)
        val auth = TelefonKrypto.hkdf(root, null, "magnolie-phone-fs1/auth\u0000".toByteArray(), 32)
        val withoutMac = buildJsonObject {
            put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("session_start"))
            put("sid", JsonPrimitive(TelefonKrypto.b64(sid))); put("from", JsonPrimitive(identity.device_id)); put("to", JsonPrimitive(peer.device_id))
            put("initiator_role", JsonPrimitive("phone")); put("ephemeral_public", JsonPrimitive(TelefonKrypto.b64(ephemeral.second)))
            put("nonce", JsonPrimitive(TelefonKrypto.b64(nonce))); put("versions", JsonArray(listOf(JsonPrimitive(1))))
        }
        val mac = TelefonKrypto.hmac(auth, "magnolie-phone-fs1/start\u0000".toByteArray(), TelefonKanonisch.bytes(withoutMac))
        return TelefonSessionSecrets(JsonObject(withoutMac + ("mac" to JsonPrimitive(TelefonKrypto.b64(mac)))), sid, ephemeral.first, root, auth)
    }

    fun finish(secrets: TelefonSessionSecrets, response: JsonObject, identity: TelefonIdentitaet, peer: TelefonPeer,
               input: InputStream, output: OutputStream): TelefonSecureChannel {
        TelefonNachrichten.exact(response, setOf("p", "type", "sid", "from", "to", "ephemeral_public", "nonce", "version", "mac"))
        if (response.string("p") != TelefonParameter.PROTOKOLL || response.string("type") != "session_response" ||
            response.string("sid") != TelefonKrypto.b64(secrets.sid) || response.string("from") != peer.device_id ||
            response.string("to") != identity.device_id || response.long("version") != 1L) fail()
        TelefonKrypto.b64(response.string("nonce"), 32)
        val withoutMac = JsonObject(response.filterKeys { it != "mac" })
        val expected = TelefonKrypto.hmac(secrets.authKey, "magnolie-phone-fs1/response\u0000".toByteArray(),
            TelefonKanonisch.bytes(secrets.start), TelefonKanonisch.bytes(withoutMac))
        if (!MessageDigest.isEqual(expected, TelefonKrypto.b64(response.string("mac"), 32))) fail()
        val transcript = TelefonKrypto.sha256(TelefonKanonisch.bytes(secrets.start), TelefonKanonisch.bytes(response))
        val salt = TelefonKrypto.hmac(secrets.staticRoot, "magnolie-phone-fs1/session-salt\u0000".toByteArray(), transcript)
        val material = TelefonKrypto.hkdf(TelefonKrypto.austausch(secrets.ephemeralPrivate,
            TelefonKrypto.b64(response.string("ephemeral_public"), 32)), salt,
            "magnolie-phone-fs1/session-keys\u0000".toByteArray() + transcript, 72)
        secrets.ephemeralPrivate.fill(0); secrets.staticRoot.fill(0); secrets.authKey.fill(0)
        return TelefonSecureChannel(input, output, secrets.sid, material.copyOfRange(0, 32), material.copyOfRange(32, 36),
            material.copyOfRange(36, 68), material.copyOfRange(68, 72)).also { material.fill(0) }
    }

    private fun ids(a: String, b: String) = listOf(a, b).sorted().joinToString("\u0000").toByteArray()
    private fun fail(): Nothing = throw TelefonProtokollFehler("Ungültige Sitzungsantwort.")
}
