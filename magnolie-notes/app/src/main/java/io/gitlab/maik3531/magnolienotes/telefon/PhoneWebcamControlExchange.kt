package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Service
import android.os.SystemClock
import androidx.annotation.RequiresApi
import kotlinx.serialization.json.*
import java.net.InetAddress
import java.security.SecureRandom
import java.util.UUID

/** One fresh phone-initiated exchange on one original authenticated parent.
 * The mandatory liveParent guard must check the actual channel/generation and
 * freshly received desktop v24 control, NOT saved capability/preferences.
 * Parsing a packet alone never constructs a permit or authorizes wire SEND.
 * No advertisement, permission prompt, socket, reconnect or service autostart.
 */
@RequiresApi(30)
internal class PhoneWebcamControlExchange(private val parent: Any, private val liveParent: () -> Unit,
    private val monotonicMs: () -> Long = SystemClock::elapsedRealtime) : AutoCloseable {
    private val gate = Any()
    private val requestId = UUID.randomUUID().toString()
    private val nonce = NativeHex.lower(ByteArray(32).also { SecureRandom().nextBytes(it) })
    private var phase = "new"
    private val issued = monotonicMs()
    private var last = issued
    private var secret: ByteArray? = null
    private var original: PhoneWebcamCaptureRequest? = null
    private var run: PhoneWebcamForegroundRun? = null
    private var session: String? = null
    var port: Int? = null
        private set
    var terminalFailure: Throwable? = null
        private set

    /** This is a probe, NOT the original Organizer opt-in or an OS request. */
    fun probe(actualParent: Any): JsonObject {
        sameParent(actualParent)
        return checked {
            synchronized(gate) {
                check(phase == "new") { "webcam_control_probe_already_used" }
                phase = "probing"
                body("probe")
            }
        }
    }

    /** A stale/foreign packet does not retire a different original exchange. */
    fun acceptOffer(actualParent: Any, message: JsonObject): PhoneWebcamCaptureRequest? {
        sameParent(actualParent)
        val value = matching(message)
        return checked {
            synchronized(gate) {
                check(phase == "probing" && value.string("op") in setOf("offer", "unavailable")) { "webcam_control_offer_out_of_phase" }
                if (value.string("op") == "unavailable") { close(); return@checked null }
                session = value.string("session")
                secret = value.string("secret").chunked(2).map { it.toInt(16).toByte() }.toByteArray()
                port = value.long("port").toInt()
                phase = "offered"
            }
            // Constructing the original request invokes the native parent guard.
            // Never call that external guard while holding the exchange monitor.
            val request = PhoneWebcamCaptureRequest(value.string("session"), (value["muted"] as JsonPrimitive).boolean,
                (value["front"] as JsonPrimitive).boolean, ::requireCapture, monotonicMs)
            synchronized(gate) {
                if (phase != "offered") { request.close(); error("webcam_original_control_retired") }
                original = request
            }
            request
        }
    }

    /** Join only the permit minted for THIS original OS request. The prepared
     * callback must enter the parent's bounded control-send path; it must not
     * block a native capture callback with socket connect or unbounded writes.
     */
    fun createRun(actualParent: Any, permit: PhoneWebcamCapturePermit, expectedPeer: InetAddress,
        prepared: (JsonObject) -> Unit, ended: (Throwable?) -> Unit,
        captureFactory: (Service, PhoneWebcamCapturePermit, (Boolean, Long, ByteArray) -> Unit, (Throwable?) -> Unit) -> PhoneWebcamCaptureDevice =
            { service, permission, sample, stopped -> PhoneWebcamAndroidCapture(service, permission, sample, stopped) }): PhoneWebcamForegroundRun {
        sameParent(actualParent)
        return checked {
            synchronized(gate) {
                check(phase == "offered" && run == null && permit.belongsTo(checkNotNull(original))) { "webcam_original_capture_permit_required" }
                val material = checkNotNull(secret)
                try {
                    phase = "capturing"
                    PhoneWebcamForegroundRun(permit, material, expectedPeer, ::requireCapture, ::requireSend, {
                        val packet = checked {
                            synchronized(gate) {
                                check(phase == "capturing") { "webcam_control_prepared_out_of_phase" }
                                phase = "prepared"
                                body("prepared", withSession = true)
                            }
                        }
                        prepared(packet)
                    }, { error ->
                        retire(error)
                        ended(error)
                    }, captureFactory).also { run = it }
                } finally { material.fill(0); secret = null }
            }
        }
    }

    /** Only a matching original peer's fresh receiver-ready SEND message after
     * the real source prepared callback can release the binary lane guard. */
    fun acceptSend(actualParent: Any, message: JsonObject) {
        sameParent(actualParent)
        val value = matching(message)
        checked {
            synchronized(gate) {
                check(phase == "prepared" && value.string("op") == "send" && value.string("session") == session) { "webcam_control_send_out_of_phase" }
                phase = "sending"
            }
        }
    }

    fun acceptStop(actualParent: Any, message: JsonObject) {
        sameParent(actualParent)
        val value = matching(message)
        synchronized(gate) {
            check(value.string("op") in setOf("stop", "error") && value.string("session") == session) { "webcam_control_foreign_session" }
        }
        checked { close() }
    }

    private fun body(op: String, withSession: Boolean = false) = buildJsonObject {
        put("version", PhoneWebcamControl.DISCOVERY_VERSION); put("request_id", requestId); put("nonce", nonce); put("op", op)
        if (withSession) put("session", checkNotNull(session))
    }
    private fun sameParent(actual: Any) { check(actual === parent) { "webcam_original_parent_required" } }
    private fun matching(message: JsonObject): JsonObject {
        val value = PhoneWebcamControl.validateMessage(message)
        check(message.string("kind") == PhoneWebcamControl.REPORT && value.string("request_id") == requestId &&
            value.string("nonce") == nonce) { "webcam_control_foreign_exchange" }
        return value
    }
    private fun current() {
        liveParent()
        synchronized(gate) {
            val now = monotonicMs()
            check(phase != "retired" && now >= issued && now >= last &&
                (phase == "sending" || now - issued < PhoneWebcamControl.MAX_TTL_MS)) { "webcam_original_control_retired" }
            last = now
        }
    }
    private fun requireCapture() = checked {
        synchronized(gate) { check(phase in setOf("offered", "capturing", "prepared", "sending")) { "webcam_original_capture_required" } }
    }
    private fun requireSend() = checked {
        synchronized(gate) { check(phase == "sending") { "webcam_actual_receiver_ready_required" } }
    }
    private inline fun <T> checked(block: () -> T): T {
        try { current(); return block() }
        catch (error: Throwable) { retire(error); throw error }
    }
    override fun close() { retire(null) }
    private fun retire(error: Throwable?) {
        val capture = synchronized(gate) {
            if (phase == "retired") return
            phase = "retired"; terminalFailure = error
            original?.close(); secret?.fill(0); secret = null
            run
        }
        capture?.close()
    }
}
