package io.gitlab.maik3531.magnolienotes.journal

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import kotlinx.coroutines.runBlocking
import io.gitlab.maik3531.magnolienotes.BuildConfig
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.GeprueftesPortableArchiv
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.KeyStore
import java.time.Instant
import java.util.concurrent.TimeUnit
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

internal enum class SnapshotCommitSchritt {
    PAYLOAD_BEREIT,
    MANIFEST_BEREIT,
    ABSICHT_DAUERHAFT,
    PAYLOAD_VEROEFFENTLICHT,
    MANIFEST_VEROEFFENTLICHT,
    ABSICHT_ENTFERNT,
    NEBENDATEIEN_ENTFERNT
}

/** Roll-forward-Paarcommit: Ein Manifest wird nie vor seiner Nutzlast sichtbar. */
internal class DateiSnapshotStore(
    private val dir: File,
    private val json: Json,
    private val nachSchritt: (SnapshotCommitSchritt) -> Unit = {}
) : SnapshotStore {
    init {
        check(dir.exists() || dir.mkdirs())
        wiederaufnehmen()
    }

    @Synchronized
    override fun list(): List<SnapshotManifest> {
        wiederaufnehmen()
        return dir.listFiles { f -> f.extension == "json" }.orEmpty()
            .mapNotNull { runCatching { json.decodeFromString<SnapshotManifest>(it.readText()) }.getOrNull() }
            .sortedByDescending { it.createdUtc }
    }

    @Synchronized
    override fun write(manifest: SnapshotManifest, encryptedPayload: ByteArray) {
        wiederaufnehmen()
        val id = manifest.uuid
        dauerhaftSchreiben(payloadBereit(id), encryptedPayload)
        nachSchritt(SnapshotCommitSchritt.PAYLOAD_BEREIT)
        dauerhaftSchreiben(manifestBereit(id),
            json.encodeToString(SnapshotManifest.serializer(), manifest).toByteArray(Charsets.UTF_8))
        nachSchritt(SnapshotCommitSchritt.MANIFEST_BEREIT)
        veroeffentlichen(absicht(id), ByteArray(0))
        nachSchritt(SnapshotCommitSchritt.ABSICHT_DAUERHAFT)
        fertigstellen(id)
    }

    @Synchronized
    override fun read(id: String): Pair<SnapshotManifest, ByteArray> {
        wiederaufnehmen()
        val m = json.decodeFromString<SnapshotManifest>(manifest(id).readText())
        return m to payload(id).readBytes()
    }

    @Synchronized
    override fun delete(id: String) {
        wiederaufnehmen()
        check(manifest(id).delete() || !manifest(id).exists())
        ordnerSynchronisieren()
        check(payload(id).delete() || !payload(id).exists())
        ordnerSynchronisieren()
    }

    @Synchronized
    override fun bytes(): Long {
        wiederaufnehmen()
        return dir.listFiles().orEmpty().sumOf { it.length() }
    }

    private fun wiederaufnehmen() {
        dir.listFiles { f -> f.name.endsWith(ABSICHT_ENDE) }.orEmpty().forEach { marker ->
            val id = marker.name.removeSuffix(ABSICHT_ENDE)
            check(payloadBereit(id).isFile && manifestBereit(id).isFile) {
                "Unvollstaendiger Snapshot-Commit darf nicht veroeffentlicht werden: $id"
            }
            fertigstellen(id)
        }
        aufraeumen()
        val namen = dir.listFiles().orEmpty().mapTo(mutableSetOf()) { it.name }
        dir.listFiles().orEmpty().filter { datei ->
            (datei.extension == "json" && "${datei.nameWithoutExtension}.bin" !in namen) ||
                (datei.extension == "bin" && "${datei.nameWithoutExtension}.json" !in namen)
        }.forEach { check(it.delete() || !it.exists()) }
        ordnerSynchronisieren()
    }

    private fun fertigstellen(id: String) {
        installieren(payloadBereit(id), payload(id))
        nachSchritt(SnapshotCommitSchritt.PAYLOAD_VEROEFFENTLICHT)
        installieren(manifestBereit(id), manifest(id))
        nachSchritt(SnapshotCommitSchritt.MANIFEST_VEROEFFENTLICHT)
        check(absicht(id).delete() || !absicht(id).exists())
        ordnerSynchronisieren()
        nachSchritt(SnapshotCommitSchritt.ABSICHT_ENTFERNT)
        aufraeumen(id)
        nachSchritt(SnapshotCommitSchritt.NEBENDATEIEN_ENTFERNT)
    }

    private fun installieren(quelle: File, ziel: File) {
        val neu = File(dir, ziel.name + INSTALL_ENDE)
        FileInputStream(quelle).use { eingang ->
            FileOutputStream(neu).use { ausgang ->
                eingang.copyTo(ausgang)
                ausgang.flush()
                ausgang.fd.sync()
            }
        }
        ordnerSynchronisieren()
        atomarVerschieben(neu, ziel)
        ordnerSynchronisieren()
    }

    private fun veroeffentlichen(datei: File, inhalt: ByteArray) {
        val neu = File(dir, datei.name + NEU_ENDE)
        dauerhaftSchreiben(neu, inhalt)
        atomarVerschieben(neu, datei)
        ordnerSynchronisieren()
    }

    private fun dauerhaftSchreiben(datei: File, inhalt: ByteArray) {
        FileOutputStream(datei).use { strom ->
            strom.write(inhalt)
            strom.flush()
            strom.fd.sync()
        }
        ordnerSynchronisieren()
    }

    private fun atomarVerschieben(quelle: File, ziel: File) {
        Files.move(quelle.toPath(), ziel.toPath(), StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING)
    }

    private fun ordnerSynchronisieren() {
        runCatching { Files.newByteChannel(dir.toPath(), StandardOpenOption.READ).use { kanal ->
            (kanal as? java.nio.channels.FileChannel)?.force(true)
        } }
    }

    private fun aufraeumen(id: String? = null) {
        dir.listFiles().orEmpty().filter { datei ->
            (id == null || datei.name.startsWith("$id.")) &&
                (datei.name.endsWith(BEREIT_ENDE) || datei.name.endsWith(INSTALL_ENDE) ||
                    datei.name.endsWith(NEU_ENDE))
        }.forEach { check(it.delete() || !it.exists()) }
        ordnerSynchronisieren()
    }

    private fun payload(id: String) = File(dir, "$id.bin")
    private fun manifest(id: String) = File(dir, "$id.json")
    private fun payloadBereit(id: String) = File(dir, "$id.bin$BEREIT_ENDE")
    private fun manifestBereit(id: String) = File(dir, "$id.json$BEREIT_ENDE")
    private fun absicht(id: String) = File(dir, "$id$ABSICHT_ENDE")

    private companion object {
        const val BEREIT_ENDE = ".snapshot-bereit"
        const val INSTALL_ENDE = ".snapshot-install"
        const val ABSICHT_ENDE = ".snapshot-pending"
        const val NEU_ENDE = ".neu"
    }
}

private fun androidKey(): SecretKey {
    val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (ks.getKey("magnolie-wiederherstellungsjournal-v1", null) as? SecretKey)?.let { return it }
    val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
    generator.init(KeyGenParameterSpec.Builder("magnolie-wiederherstellungsjournal-v1",
        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    return generator.generateKey()
}

data class JournalZustand(val entries: List<SnapshotManifest> = emptyList(),
                           val interval: JournalIntervall = JournalIntervall.WOECHENTLICH,
                           val maximum: Int = 20, val status: String = "", val last: Long? = null)

class AndroidJournal private constructor(private val context: Context) {
    private val json = Ablage.json
    private val store = DateiSnapshotStore(File(context.filesDir, "wiederherstellungsstaende"), json)
    private val crypto = AesGcmKrypto(::androidKey)
    private val prefs = context.getSharedPreferences("wiederherstellungsjournal", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(JournalZustand())
    val state = _state.asStateFlow()
    private var aktiviert = false

    init { refresh() }

    fun aktivieren() {
        if (aktiviert) return
        planen(context)
        faelligSichern()
        aktiviert = true
    }

    fun intervalSetzen(interval: JournalIntervall) {
        prefs.edit().putString("interval", interval.name).apply(); refresh(); planen(context)
    }

    fun maximumSetzen(maximum: Int) {
        prefs.edit().putInt("maximum", maximum.coerceIn(1, 100)).apply()
        bereinigen()
        refresh()
    }

    fun appSnapshot(reason: String, pinned: Boolean = false): SnapshotManifest = synchronized(Ablage.SCHREIBSPERRE) {
        val (notizen, baum) = Ablage.hole(context).journalNutzlast()
        val payload = json.encodeToString(AppDatenNutzlast.serializer(), AppDatenNutzlast(notizen, baum)).toByteArray()
        val z = Ablage.hole(context).baum.value
        create(reason, "android-app-data", payload,
            "${Ablage.hole(context).notizen().size} notes, ${Ablage.hole(context).aufgaben().size} tasks",
            z.syncEpoch, pinned)
    }

    fun kontaktSnapshot(reason: String, contacts: List<KontaktRohstand>, mutationId: String): SnapshotManifest {
        val bytes = json.encodeToString(KontaktNutzlast.serializer(), KontaktNutzlast(contacts, mutationId)).toByteArray()
        val names = contacts.map { listOf(it.portable.vorname, it.portable.nachname).joinToString(" ").trim() }
            .filter(String::isNotBlank).take(5).joinToString(", ")
        return create(reason, "android-system-contacts", bytes,
            "${contacts.size} contact(s)${if (names.isBlank()) "" else ": $names"}",
            Ablage.hole(context).baum.value.syncEpoch, mutationId = mutationId)
    }

    private fun create(reason: String, domain: String, payload: ByteArray, summary: String,
                       epoch: String, pinned: Boolean = false, mutationId: String = ""): SnapshotManifest {
        val hash = JournalRegeln.sha256(payload)
        val now = System.currentTimeMillis()
        store.list().firstOrNull { it.reason == reason && it.payload.hash == hash &&
            now - Instant.parse(it.createdUtc).toEpochMilli() <= JournalRegeln.DEDUPE_MS }?.let { return it }
        val manifest = JournalRegeln.manifest(reason, domain, BuildConfig.VERSION_NAME, payload,
            summary, epoch, pinned, mutationId, now)
        store.write(manifest, crypto.encrypt(payload, manifest.uuid.toByteArray()))
        prefs.edit().putLong("last", now).apply(); bereinigen(); refresh(); return manifest
    }

    fun payload(id: String): ByteArray {
        val (m, encrypted) = store.read(id)
        val plain = crypto.decrypt(encrypted, m.uuid.toByteArray())
        check(plain.size.toLong() == m.payload.size && JournalRegeln.sha256(plain) == m.payload.hash)
        return plain
    }

    fun restoreApp(id: String, operationId: String): Boolean = synchronized(Ablage.SCHREIBSPERRE) {
        val m = store.read(id).first; require(m.domain == "android-app-data")
        appSnapshot("pre-restore")
        val p = json.decodeFromString<AppDatenNutzlast>(payload(id).decodeToString())
        Ablage.hole(context).journalWiederherstellen(p.notizen, p.baum, operationId).also { refresh() }
    }

    fun restorePortable(archiv: GeprueftesPortableArchiv, operationId: String): Boolean =
        synchronized(Ablage.SCHREIBSPERRE) {
            appSnapshot("pre-restore")
            Ablage.hole(context).portableWiederherstellen(archiv.bestandJson, operationId).also { refresh() }
        }

    /** Selektiver Kontakt-Restore mit stabiler Operation und expliziter Konfliktstufe. */
    fun restoreContacts(id: String, operationId: String, conflictsConfirmed: Boolean = false): AndroidKontakte.RestoreErgebnis {
        val marker = File(context.filesDir, "kontakt-wiederherstellung-$operationId.ok")
        if (marker.exists()) return AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT
        val manifest = store.read(id).first; require(manifest.domain == "android-system-contacts")
        val payload = json.decodeFromString<KontaktNutzlast>(payload(id).decodeToString())
        val adapter = AndroidKontakte(context)
        val results = payload.contacts.map { adapter.wiederherstellen(it, conflictsConfirmed) }
        if (AndroidKontakte.RestoreErgebnis.KONFLIKT in results) return AndroidKontakte.RestoreErgebnis.KONFLIKT
        if (AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR in results) return AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR
        marker.writeText(id); refresh(); return AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT
    }

    fun delete(id: String) { store.delete(id); refresh() }
    fun faelligSichern() {
        val interval = interval()
        val last = prefs.getLong("last", -1).takeIf { it >= 0 }
        if (JournalRegeln.due(last, System.currentTimeMillis(), interval)) appSnapshot("scheduled")
    }
    private fun interval() = runCatching { JournalIntervall.valueOf(prefs.getString("interval", null)
        ?: JournalIntervall.WOECHENTLICH.name) }.getOrDefault(JournalIntervall.WOECHENTLICH)
    private fun maximum() = prefs.getInt("maximum", 20).coerceIn(1, 100)
    private fun bereinigen() {
        val entries = store.list()
        val keep = JournalRegeln.behalten(entries, System.currentTimeMillis(), maximum())
        entries.filterNot { it.uuid in keep }.forEach { store.delete(it.uuid) }
        val budget = JournalRegeln.budget(context.filesDir.totalSpace)
        store.list().sortedBy { it.createdUtc }.filterNot { it.pinned }.forEach {
            if (store.bytes() > budget || context.filesDir.usableSpace < JournalRegeln.RESERVE_BYTES) store.delete(it.uuid)
        }
    }
    private fun refresh(status: String = "") {
        val last = prefs.getLong("last", -1).takeIf { it >= 0 }
        _state.value = JournalZustand(store.list(), interval(), maximum(), status, last)
    }

    companion object {
        @Volatile private var instance: AndroidJournal? = null
        fun hole(context: Context) = instance ?: synchronized(this) { instance ?:
            AndroidJournal(context.applicationContext).also { instance = it } }
        fun planen(context: Context) {
            val request = PeriodicWorkRequestBuilder<JournalWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("magnolie-journal-due",
                ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }
}

class JournalWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = runCatching {
        val app = applicationContext as MagnolieApp
        if (!runBlocking { app.awaitReady() }) return Result.retry()
        AndroidJournal.hole(applicationContext).faelligSichern()
        Result.success()
    }.getOrElse { Result.retry() }
}
