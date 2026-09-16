package io.gitlab.maik3531.magnolienotes

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import io.gitlab.maik3531.magnolienotes.daten.PersonalCustom
import io.gitlab.maik3531.magnolienotes.daten.PersonalCustomState
import io.gitlab.maik3531.magnolienotes.telefon.PersonalSyncProtokoll
import io.gitlab.maik3531.magnolienotes.telefon.TelefonPeer
import kotlinx.serialization.json.*

/** Notification-only navigation, never a phone command or an ordinary editor ID. */
internal object CustomNavigation {
    private const val ACTION = "io.gitlab.maik3531.magnolienotes.ZEIGE_CUSTOM"
    private const val OWNER = "custom_owner"
    private const val GENERATION = "custom_generation"
    private const val LOCAL_EPOCH = "custom_local_epoch"
    private const val REMOTE_EPOCH = "custom_remote_epoch"
    private val uri = Regex("magnolie://custom/(custom:[0-9a-f]{64})")
    private fun component(context: Context) = ComponentName(context, MainActivity::class.java.name + "Custom")

    fun absicht(context: Context, state: PersonalCustomState, id: String): Intent =
        Intent(ACTION).setComponent(component(context)).setData(Uri.parse("magnolie://custom/$id")).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(OWNER, state.owner)
            putExtra(GENERATION, state.generation)
            putExtra(LOCAL_EPOCH, state.local?.get("epoch")?.jsonPrimitive?.content)
            putExtra(REMOTE_EPOCH, state.remote?.get("epoch")?.jsonPrimitive?.content)
        }

    fun anfrage(context: Context, intent: Intent?): Intent? = runCatching {
        if (intent == null || intent.component != component(context) || intent.action != ACTION ||
            intent.selector != null || intent.type != null || !intent.categories.isNullOrEmpty() ||
            intent.`package`?.let { it != context.packageName } == true ||
            !uri.matches(intent.dataString.orEmpty())) return null
        // Only the non-exported alias accepts this route. Do not retain caller extras.
        Intent(ACTION).setComponent(component(context)).setData(intent.data).apply {
            for (key in listOf(OWNER, GENERATION, LOCAL_EPOCH, REMOTE_EPOCH)) {
                val value = intent.getStringExtra(key)?.takeIf { it.length in 1..256 } ?: return null
                putExtra(key, value)
            }
        }
    }.getOrNull()

    fun ziel(context: Context, intent: Intent?, state: PersonalCustomState, peer: TelefonPeer?): String? = runCatching {
        val request = anfrage(context, intent) ?: return null
        val id = uri.matchEntire(request.dataString!!)?.groupValues?.get(1) ?: return null
        val item = state.items[id] ?: return null
        if (peer == null || peer.state != "paired" || !peer.own_device || !peer.remote_own_device ||
            !peer.remote_personal_tasks_sync_available || 4 !in peer.remote_personal_tasks_sync_versions ||
            state.owner != peer.device_id + ":" + peer.static_public ||
            request.getStringExtra(OWNER) != state.owner || request.getStringExtra(GENERATION) != state.generation ||
            request.getStringExtra(LOCAL_EPOCH) != state.local?.get("epoch")?.jsonPrimitive?.content ||
            request.getStringExtra(REMOTE_EPOCH) != state.remote?.get("epoch")?.jsonPrimitive?.content ||
            !PersonalCustom.remindersAllowed(state, item) || item.record["id"]?.jsonPrimitive?.content != id) return null
        // Reuse the wire validator for source-ID binding, exact fields, hash and values.
        // Restored or malformed local content must not acquire authority from an Intent.
        PersonalSyncProtokoll.validateCustomBody("personal_sync.custom_batch", buildJsonObject {
            put("format", 4); put("trigger", "manual")
            put("sender_epoch", state.remote!!.getValue("epoch"))
            put("receiver_epoch", state.local!!.getValue("epoch"))
            put("sender_revision", state.remote.getValue("revision"))
            put("receiver_revision", state.local.getValue("revision"))
            put("source_id", item.source); put("revision", item.revision)
            put("upserts", JsonArray(listOf(item.record))); put("deletions", JsonArray(emptyList()))
        })
        id
    }.getOrNull()
}
