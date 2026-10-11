package io.gitlab.maik3531.magnolienotes.telefon

/** Capability marker, not a new personal record format. Legacy Wi-Fi runs stay bound. */
internal object PersonalAutoSync {
    const val VERSION = 8
    const val CONNECTION = "auto_connection"
    val TRIGGERS = setOf("manual", "auto_wifi", CONNECTION)

    fun supported(peer: TelefonPeer, local: Map<String, TelefonCapability>): Boolean =
        peer.remote_personal_notes_sync_available && peer.remote_personal_tasks_sync_available &&
            VERSION in peer.remote_personal_notes_sync_versions && VERSION in peer.remote_personal_tasks_sync_versions &&
            local["personal_notes_sync"]?.let { it.available && VERSION in it.versions } == true &&
            local["personal_tasks_sync"]?.let { it.available && VERSION in it.versions } == true

    fun trigger(transport: TelefonTransportArt, negotiated: Boolean): String? = when {
        negotiated -> CONNECTION
        transport == TelefonTransportArt.WIFI -> "auto_wifi"
        else -> null
    }

    fun allowed(trigger: String, negotiated: Boolean): Boolean =
        trigger in TRIGGERS && (trigger != CONNECTION || negotiated)

    fun automatic(trigger: String): Boolean = trigger == "auto_wifi" || trigger == CONNECTION
}
