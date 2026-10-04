package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.Serializable
import java.util.UUID

@Serializable
@OptIn(ExperimentalSerializationApi::class)
data class ZeitPapierkorb(
    @EncodeDefault val id: String = UUID.randomUUID().toString(),
    @EncodeDefault val removedMs: Long = System.currentTimeMillis(),
    val entries: List<Zeiteintrag>,
    val month: String? = null,
    val conflicts: Map<String, List<Zeiteintrag>> = emptyMap(),
    val pauseRuns: Map<String, ZeitPausenlauf> = emptyMap()
) {
    val expiresMs: Long get() = Math.addExact(removedMs, RETENTION_MS)

    companion object {
        const val RETENTION_MS = 30L * 24 * 60 * 60 * 1000
    }
}
