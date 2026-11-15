package io.gitlab.maik3531.magnolienotes.journal

import android.content.Context
import android.database.Cursor
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.CommonDataKinds.Photo
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import io.gitlab.maik3531.magnolienotes.baum.KontaktOriginalBindung
import io.gitlab.maik3531.magnolienotes.baum.KontaktOriginalFreigaben
import io.gitlab.maik3531.magnolienotes.baum.KontaktSync
import kotlinx.serialization.json.Json
import java.util.UUID

/** A pinned contact before-image using the EXISTING snapshot store and cipher.
 * A descriptor/JSON object alone cannot mint this verified native witness.
 * No app/notebook payload is read; only the selected native contact is captured.
 */
internal class KontaktOriginalSicherungen(
    private val context: Context,
    private val store: DateiSnapshotStore,
    private val schreiben: AesGcmKrypto,
    private val lesen: AesGcmKrypto,
    private val epoch: () -> String,
    private val appVersion: String,
    private val vorSchreiben: () -> Unit = {}
) {
    private val json = Json { encodeDefaults = true }
    private class Beleg(val owner: KontaktOriginalSicherungen, val bindung: KontaktOriginalBindung,
        val manifest: SnapshotManifest, val original: KontaktNutzlast)
    class Sicherung internal constructor(private val beleg: Any) {
        private fun native(): Beleg = (beleg as? Beleg) ?: throw SecurityException("contact_original_native_protection_required")
        fun pruefen(bindung: KontaktOriginalBindung) {
            val current = native()
            if (current.bindung !== bindung) throw SecurityException("contact_original_protection_retargeted")
            current.owner.pruefen(current)
        }
        fun manifest(bindung: KontaktOriginalBindung): SnapshotManifest = native().also { pruefen(bindung) }.manifest
    }

    fun sichern(grant: KontaktOriginalFreigaben.Freigabe, mutationId: String): Sicherung {
        grant.pruefen()
        require(runCatching { UUID.fromString(mutationId).let { it.toString() == mutationId && it.version() == 4 } }.getOrDefault(false))
        val binding = grant.bindung
        val before = binding.aktuell()
        blobUnterstuetzung(binding)
        val adapter = AndroidKontakte(context, rawScope = setOf(binding.rawContactId))
        val frames = adapter.journalStaende(listOf(binding.rawContactId), "original-return")
        val original = frames.singleOrNull() ?: error("contact_original_protection_incomplete")
        require(original.rawContactId == binding.rawContactId && original.lookupKey == binding.lookupKey &&
            original.accountName == binding.quelle.kontoName && original.accountType == binding.quelle.kontoTyp &&
            original.dataSet == binding.quelle.datenSatz && original.sourceId == binding.sourceId &&
            original.portable == before.daten && original.beforeHash == KontaktSync.hash(before.daten) &&
            original.rows.size == binding.zeilenIds.size) { "contact_original_protection_incomplete" }
        AndroidKontakte.pruefeOriginalWiederherstellbar(original)
        grant.pruefen()
        require(adapter.journalStaende(listOf(binding.rawContactId), "original-return") == frames) { "contact_original_protection_changed" }
        grant.pruefen()
        val payload = KontaktNutzlast(frames, mutationId)
        val bytes = json.encodeToString(KontaktNutzlast.serializer(), payload).toByteArray(Charsets.UTF_8)
        try {
            require(bytes.size <= 4 * 1024 * 1024)
            require(store.bytes() + bytes.size + 4096 <= JournalRegeln.budget(context.filesDir.totalSpace) &&
                context.filesDir.usableSpace - bytes.size - 4096 >= JournalRegeln.RESERVE_BYTES) { "contact_original_protection_space_required" }
            vorSchreiben(); grant.pruefen()
            val manifest = JournalRegeln.manifest("contact-original-return", "android-system-contacts", appVersion,
                bytes, "1 contact", epoch(), pinned = true, mutationId = mutationId)
            val encrypted = schreiben.encrypt(bytes, manifest.uuid.toByteArray(Charsets.UTF_8))
            grant.pruefen()
            store.write(manifest, encrypted)
            grant.pruefen()
            return Sicherung(Beleg(this, binding, manifest, payload)).also { it.pruefen(binding) }
        } finally { bytes.fill(0) }
    }

    private fun blobUnterstuetzung(binding: KontaktOriginalBindung) {
        val ids = mutableSetOf<Long>()
        requireNotNull(context.contentResolver.query(Data.CONTENT_URI,
            arrayOf(Data._ID, Data.MIMETYPE) + (1..15).map { "data$it" }, "${Data.RAW_CONTACT_ID}=?",
            arrayOf(binding.rawContactId.toString()), null)).use { cursor ->
            while (cursor.moveToNext()) {
                require(ids.size < 500 && ids.add(cursor.getLong(0)))
                for (index in 2..16) if (cursor.getType(index) == Cursor.FIELD_TYPE_BLOB) {
                    // The existing restore codec knows Photo.DATA15; it does not
                    // retain arbitrary application-specific BLOB type tags.
                    require(cursor.getString(1) == Photo.CONTENT_ITEM_TYPE && index == 16) { "contact_original_unmodeled_blob_protection_required" }
                }
            }
        }
        require(ids == binding.zeilenIds) { "contact_original_protection_incomplete" }
    }

    private fun pruefen(beleg: Beleg) {
        val (manifest, encrypted) = store.read(beleg.manifest.uuid)
        require(manifest == beleg.manifest && manifest.pinned && manifest.domain == "android-system-contacts")
        val plain = lesen.decrypt(encrypted, manifest.uuid.toByteArray(Charsets.UTF_8))
        try {
            require(plain.size.toLong() == manifest.payload.size && JournalRegeln.sha256(plain) == manifest.payload.hash &&
                json.decodeFromString(KontaktNutzlast.serializer(), plain.decodeToString(throwOnInvalidSequence = true)) == beleg.original)
        } finally { plain.fill(0) }
    }
}
