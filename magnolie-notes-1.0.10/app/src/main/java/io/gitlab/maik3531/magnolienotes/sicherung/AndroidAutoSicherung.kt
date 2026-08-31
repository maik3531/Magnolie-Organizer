package io.gitlab.maik3531.magnolienotes.sicherung

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.documentfile.provider.DocumentFile
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.ListenableWorker
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.PortableArchiv
import java.io.ByteArrayOutputStream
import java.io.FileNotFoundException
import java.io.IOException
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.runBlocking

enum class AutoSicherungsStatus {
    BEREIT, LAEUFT, ERFOLG, ERFOLG_AUFBEWAHRUNG_FEHLER, ORDNER_FEHLT,
    FREIGABE_FEHLT, PASSWORT_FEHLT, SCHLUESSEL_FEHLT, AUTHENTIFIZIERUNG_FEHLER, PROVIDER_FEHLER,
}

data class AutoSicherungsZustand(
    val aktiviert: Boolean = false,
    val ordnerGewaehlt: Boolean = false,
    val passwortGesichert: Boolean = false,
    val intervall: AutoSicherungsIntervall = AutoSicherungsIntervall.WOECHENTLICH,
    val aufbewahrung: Int = 7,
    val letzterErfolg: Long? = null,
    val status: AutoSicherungsStatus = AutoSicherungsStatus.BEREIT,
)

private class AndroidAutoSchluessel : AutoSicherungsSchluessel {
    private val store get() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    override fun vorhandener(): SecretKey? = try { store.getKey(ALIAS, null) as? SecretKey }
        catch (_: Exception) { throw AutoSicherungsSchluesselFehlt() }
    override fun anlegen(): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }

    private companion object { const val ALIAS = "magnolie-auto-portable-passwort-v1" }
}

private class SafSicherungsOrdner(context: Context, baum: Uri) : SicherungsOrdner {
    private val resolver = context.contentResolver
    private val wurzel = requireNotNull(DocumentFile.fromTreeUri(context, baum))
    private val nachKennung = mutableMapOf<String, Uri>()

    override fun anlegen(name: String, mime: String): SicherungsDokument {
        val datei = requireNotNull(wurzel.createFile(mime, name))
        return datei.wert(mime).also { nachKennung[it.kennung] = datei.uri }
    }

    override fun schreiben(dokument: SicherungsDokument, inhalt: ByteArray) {
        resolver.openOutputStream(uri(dokument), "w")?.use { strom ->
            strom.write(inhalt); strom.flush()
        } ?: throw FileNotFoundException()
    }

    override fun lesen(dokument: SicherungsDokument, maximum: Long): ByteArray {
        val aus = ByteArrayOutputStream()
        resolver.openInputStream(uri(dokument))?.use { strom ->
            val block = ByteArray(64 * 1024)
            var gesamt = 0L
            while (true) {
                val n = strom.read(block)
                if (n < 0) break
                gesamt += n
                require(gesamt <= maximum)
                aus.write(block, 0, n)
            }
        } ?: throw FileNotFoundException()
        return aus.toByteArray()
    }

    override fun auflisten(maximum: Int): BegrenzteDokumente {
        val kinder = DocumentsContract.buildChildDocumentsUriUsingTree(
            wurzel.uri, DocumentsContract.getTreeDocumentId(wurzel.uri))
        val spalten = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED)
        val dokumente = mutableListOf<SicherungsDokument>()
        var abgeschnitten = false
        resolver.query(kinder, spalten, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                if (dokumente.size == maximum) { abgeschnitten = true; break }
                val uri = DocumentsContract.buildDocumentUriUsingTree(wurzel.uri, cursor.getString(0))
                val dokument = SicherungsDokument(uri.toString(), cursor.getString(1).orEmpty(),
                    cursor.getString(2).orEmpty(), cursor.getLong(3))
                nachKennung[dokument.kennung] = uri
                dokumente += dokument
            }
        } ?: throw FileNotFoundException()
        return BegrenzteDokumente(dokumente, abgeschnitten)
    }

    override fun loeschen(dokument: SicherungsDokument) = nachKennung[dokument.kennung]?.let {
        DocumentsContract.deleteDocument(resolver, it)
    } ?: false
    private fun uri(dokument: SicherungsDokument) = Uri.parse(dokument.kennung)
    private fun DocumentFile.wert(vorgabeMime: String) = SicherungsDokument(
        uri.toString(), name.orEmpty(), type ?: vorgabeMime, lastModified())
}

class AndroidAutoSicherung private constructor(private val context: Context) {
    private val prefs = context.getSharedPreferences("automatische_portable_sicherung", Context.MODE_PRIVATE)
    private val geheimPrefs = context.getSharedPreferences("automatische_portable_sicherung_geheim", Context.MODE_PRIVATE)
    private val schluessel = AndroidAutoSchluessel()
    private val _zustand = MutableStateFlow(liesZustand())
    val zustand = _zustand.asStateFlow()

    fun aktivierenNachStart() { planen() }

    fun ordnerSetzen(uri: Uri) {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        val bisher = ordnerUri()
        try {
            context.contentResolver.takePersistableUriPermission(uri, flags)
            check(freigabeVorhanden(uri))
        } catch (_: Exception) {
            status(AutoSicherungsStatus.FREIGABE_FEHLT, false)
            return
        }
        prefs.edit().putString(KEY_ORDNER, uri.toString()).putString(KEY_STATUS,
            AutoSicherungsStatus.BEREIT.name).apply()
        if (bisher != null && bisher != uri) runCatching {
            context.contentResolver.releasePersistableUriPermission(bisher, flags)
        }
        aktualisieren(); planen()
    }

    fun passwortSichern(passwort: CharArray) {
        var alt: ByteArray? = null
        try {
            alt = geheimPrefs.getString(KEY_HUELLE, null)?.let { Base64.decode(it, Base64.NO_WRAP) }
            val huelle = PasswortHuelle.sichern(passwort, alt, schluessel)
            geheimPrefs.edit().putString(KEY_HUELLE, Base64.encodeToString(huelle, Base64.NO_WRAP)).apply()
            huelle.fill(0)
            prefs.edit().putString(KEY_STATUS, AutoSicherungsStatus.BEREIT.name).apply()
        } catch (_: AutoSicherungsSchluesselFehlt) {
            status(AutoSicherungsStatus.SCHLUESSEL_FEHLT, false)
        } catch (_: KeyPermanentlyInvalidatedException) {
            status(AutoSicherungsStatus.SCHLUESSEL_FEHLT, false)
        } catch (_: Exception) {
            status(AutoSicherungsStatus.AUTHENTIFIZIERUNG_FEHLER, false)
        } finally { alt?.fill(0); passwort.fill('\u0000') }
        aktualisieren()
    }

    fun aktiviertSetzen(an: Boolean) {
        if (an) {
            val uri = ordnerUri() ?: return status(AutoSicherungsStatus.ORDNER_FEHLT, false)
            if (!freigabeVorhanden(uri)) return status(AutoSicherungsStatus.FREIGABE_FEHLT, false)
            if (!geheimPrefs.contains(KEY_HUELLE)) return status(AutoSicherungsStatus.PASSWORT_FEHLT, false)
            runCatching { passwortLaden().also { it.fill('\u0000') } }.onFailure {
                return status(AutoSicherungsStatus.SCHLUESSEL_FEHLT, false)
            }
        }
        prefs.edit().putBoolean(KEY_AKTIV, an).putString(KEY_STATUS, AutoSicherungsStatus.BEREIT.name).apply()
        aktualisieren(); planen()
    }

    fun intervallSetzen(intervall: AutoSicherungsIntervall) {
        prefs.edit().putString(KEY_INTERVALL, intervall.name).apply(); aktualisieren(); planen()
    }

    fun aufbewahrungSetzen(anzahl: Int) {
        prefs.edit().putInt(KEY_AUFBEWAHRUNG, anzahl.coerceIn(
            AutoSicherungsKonfiguration.MIN_AUFBEWAHRUNG, AutoSicherungsKonfiguration.MAX_AUFBEWAHRUNG)).apply()
        aktualisieren()
    }

    fun jetztTesten() {
        val state = liesZustand()
        if (!state.aktiviert) return
        WorkManager.getInstance(context).enqueueUniqueWork(TEST_WORK, ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<AutoSicherungsWorker>().setConstraints(constraints()).build())
    }

    internal fun ausfuehren(): ListenableWorker.Result {
        if (!prefs.getBoolean(KEY_AKTIV, false)) return ListenableWorker.Result.success()
        val uri = ordnerUri() ?: return endgueltig(AutoSicherungsStatus.ORDNER_FEHLT, deaktivieren = true)
        if (!freigabeVorhanden(uri)) return endgueltig(AutoSicherungsStatus.FREIGABE_FEHLT, deaktivieren = true)
        val passwort = try { passwortLaden() } catch (_: AutoSicherungsSchluesselFehlt) {
            return endgueltig(AutoSicherungsStatus.SCHLUESSEL_FEHLT, deaktivieren = true)
        } catch (_: KeyPermanentlyInvalidatedException) {
            return endgueltig(AutoSicherungsStatus.SCHLUESSEL_FEHLT, deaktivieren = true)
        } catch (_: Exception) {
            return endgueltig(AutoSicherungsStatus.AUTHENTIFIZIERUNG_FEHLER, deaktivieren = true)
        }
        status(AutoSicherungsStatus.LAEUFT)
        return try {
            val config = konfiguration()
            val ergebnis = synchronized(Ablage.SCHREIBSPERRE) {
                AutoSicherungsLauf(SafSicherungsOrdner(context, uri)).ausfuehren(
                    System.currentTimeMillis(), config.aufbewahrung,
                    archiv = { PortableArchiv.erstellen(Ablage.hole(context).bestand.value, passwort) },
                    authentifizieren = { PortableArchiv.pruefen(it, passwort) },
                    nachErfolg = {
                        prefs.edit().putLong(KEY_LETZTER_ERFOLG, System.currentTimeMillis())
                            .putString(KEY_STATUS, AutoSicherungsStatus.ERFOLG.name).apply()
                    },
                )
            }
            status(if (ergebnis == SicherungsLaufErgebnis.ERFOLG) AutoSicherungsStatus.ERFOLG
                else AutoSicherungsStatus.ERFOLG_AUFBEWAHRUNG_FEHLER)
            ListenableWorker.Result.success()
        } catch (_: SecurityException) {
            endgueltig(AutoSicherungsStatus.FREIGABE_FEHLT, deaktivieren = true)
        } catch (_: IOException) {
            status(AutoSicherungsStatus.PROVIDER_FEHLER); ListenableWorker.Result.retry()
        } catch (_: Exception) {
            endgueltig(AutoSicherungsStatus.AUTHENTIFIZIERUNG_FEHLER, deaktivieren = true)
        } finally { passwort.fill('\u0000') }
    }

    private fun passwortLaden(): CharArray {
        val text = geheimPrefs.getString(KEY_HUELLE, null) ?: throw IllegalStateException("Passworthuelle fehlt")
        val huelle = Base64.decode(text, Base64.NO_WRAP)
        return try { PasswortHuelle.laden(huelle, schluessel) } finally { huelle.fill(0) }
    }

    private fun planen() {
        val work = WorkManager.getInstance(context)
        if (!prefs.getBoolean(KEY_AKTIV, false)) {
            work.cancelUniqueWork(PERIODIC_WORK); work.cancelUniqueWork(TEST_WORK); return
        }
        val tage = konfiguration().intervall.tage
        val request = PeriodicWorkRequestBuilder<AutoSicherungsWorker>(tage, TimeUnit.DAYS)
            .setConstraints(constraints()).build()
        work.enqueueUniquePeriodicWork(PERIODIC_WORK, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    private fun constraints() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED)
        .setRequiresBatteryNotLow(true).setRequiresStorageNotLow(true).build()

    private fun freigabeVorhanden(uri: Uri) = context.contentResolver.persistedUriPermissions.any {
        it.uri == uri && it.isReadPermission && it.isWritePermission
    }
    private fun ordnerUri() = prefs.getString(KEY_ORDNER, null)?.let(Uri::parse)
    private fun konfiguration() = AutoSicherungsKonfiguration.lesen(
        prefs.getString(KEY_INTERVALL, null), prefs.getInt(KEY_AUFBEWAHRUNG, 7))
    private fun status(status: AutoSicherungsStatus, aktiv: Boolean? = null) {
        val edit = prefs.edit().putString(KEY_STATUS, status.name)
        if (aktiv != null) edit.putBoolean(KEY_AKTIV, aktiv)
        edit.apply(); aktualisieren()
    }
    private fun endgueltig(status: AutoSicherungsStatus, deaktivieren: Boolean = false): ListenableWorker.Result {
        status(status, if (deaktivieren) false else null)
        if (deaktivieren) planen()
        return ListenableWorker.Result.failure()
    }
    private fun aktualisieren() { _zustand.value = liesZustand() }
    private fun liesZustand(): AutoSicherungsZustand {
        val config = konfiguration()
        return AutoSicherungsZustand(
            prefs.getBoolean(KEY_AKTIV, false), ordnerUri() != null, geheimPrefs.contains(KEY_HUELLE),
            config.intervall, config.aufbewahrung,
            prefs.getLong(KEY_LETZTER_ERFOLG, -1).takeIf { it >= 0 },
            runCatching { AutoSicherungsStatus.valueOf(prefs.getString(KEY_STATUS, null).orEmpty()) }
                .getOrDefault(AutoSicherungsStatus.BEREIT),
        )
    }

    companion object {
        internal const val PERIODIC_WORK = "magnolie-auto-portable-backup"
        internal const val TEST_WORK = "magnolie-auto-portable-backup-test"
        private const val KEY_AKTIV = "enabled"
        private const val KEY_ORDNER = "tree_uri"
        private const val KEY_INTERVALL = "interval"
        private const val KEY_AUFBEWAHRUNG = "retention"
        private const val KEY_LETZTER_ERFOLG = "last_success"
        private const val KEY_STATUS = "last_status"
        private const val KEY_HUELLE = "password_envelope_v1"
        @Volatile private var instanz: AndroidAutoSicherung? = null
        fun hole(context: Context) = instanz ?: synchronized(this) { instanz ?:
            AndroidAutoSicherung(context.applicationContext).also { instanz = it } }
    }
}

class AutoSicherungsWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as MagnolieApp
        if (!runBlocking { app.awaitReady() }) return Result.failure()
        return AndroidAutoSicherung.hole(applicationContext).ausfuehren()
    }
}
