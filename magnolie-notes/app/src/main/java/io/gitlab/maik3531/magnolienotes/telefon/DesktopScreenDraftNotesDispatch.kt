package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import kotlinx.serialization.json.JsonObject

/** Private attachment to the established, authenticated WLAN reader. It does
 * not advertise, start an Activity, observe durable queues, or grant consent. */
internal class DesktopScreenDraftNotesDispatch {
    internal class Original(
        val deviceId: String, val key: String, val label: String,
        val channel: TelefonSecureChannel, val pipe: TelefonTcpRoehre, val live: () -> Unit,
    )

    private class Slot(val original: Original, val attempt: DesktopScreenDraftPhoneAttempt)

    @Volatile private var current: Original? = null
    @Volatile private var slot: Slot? = null

    @Synchronized
    fun bind(original: Original): Original {
        current = original
        return original
    }

    @Synchronized
    fun retire(channel: TelefonSecureChannel? = null) {
        if (channel == null || current?.channel === channel) current = null
        // The owner's live guard fences PREPARED/media and its main-context
        // tick closes the viewer. Neither the session reader nor Werk joins it.
    }

    fun candidate(deviceId: String, publicKey: String): Original {
        val original = checkNotNull(current)
        check(original.deviceId == deviceId && original.key == publicKey)
        requireLive(original)
        return original
    }

    private fun requireLive(original: Original) {
        check(current === original)
        original.live()
        original.channel.requireOriginalWlanPipe(original.pipe)
        check(current === original)
    }

    /** Only an explicit native action can take this slot. A replacement source
     * or Activity cannot re-use the request, consent, or an undrained slot. */
    fun begin(activity: ComponentActivity, original: Original, mode: Int,
        budgetMs: Long = 27_000, // Leave headroom below the receiver's absolute 30 s ceiling.
    ): DesktopScreenDraftPhoneAttempt {
        check(Looper.myLooper() == Looper.getMainLooper())
        val attempt = synchronized(this) {
            check(slot?.attempt?.drained != false)
            requireLive(original)
            DesktopScreenDraftPhoneAttempt(activity, original.label, original.channel, original.pipe,
                { requireLive(original) }, mode, budgetMs, ::release).also { slot = Slot(original, it) }
        }
        attempt.begin()
        return attempt
    }

    @Synchronized
    private fun release(attempt: DesktopScreenDraftPhoneAttempt) {
        if (slot?.attempt === attempt) slot = null
    }

    /** The sole active reader passes its own original witness, never one looked
     * up by the sender's payload or borrowed from the latest connection. */
    fun receive(original: Original, frame: JsonObject): Boolean {
        val owner = slot?.takeIf { it.original === original } ?: return false
        if (current !== original) return false
        return owner.attempt.receive(original.channel, frame)
    }
}
