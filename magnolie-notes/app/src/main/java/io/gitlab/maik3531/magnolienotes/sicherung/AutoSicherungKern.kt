package io.gitlab.maik3531.magnolienotes.sicherung

import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.nio.ByteBuffer
import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction
import java.security.SecureRandom
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

enum class AutoSicherungsIntervall(val tage: Long) { TAEGLICH(1), WOECHENTLICH(7) }

data class AutoSicherungsKonfiguration(
    val intervall: AutoSicherungsIntervall = AutoSicherungsIntervall.WOECHENTLICH,
    val aufbewahrung: Int = 7,
) {
    fun begrenzt() = copy(aufbewahrung = aufbewahrung.coerceIn(MIN_AUFBEWAHRUNG, MAX_AUFBEWAHRUNG))

    companion object {
        const val MIN_AUFBEWAHRUNG = 2
        const val MAX_AUFBEWAHRUNG = 30

        fun lesen(intervall: String?, aufbewahrung: Int) = AutoSicherungsKonfiguration(
            runCatching { AutoSicherungsIntervall.valueOf(intervall.orEmpty()) }
                .getOrDefault(AutoSicherungsIntervall.WOECHENTLICH),
            aufbewahrung.coerceIn(MIN_AUFBEWAHRUNG, MAX_AUFBEWAHRUNG),
        )
    }
}

class AutoSicherungsSchluesselFehlt : IllegalStateException("Automatikschluessel fehlt")

interface AutoSicherungsSchluessel {
    fun vorhandener(): SecretKey?
    fun anlegen(): SecretKey
}

/** Versionierte, authentifizierte Huelle; der Android-Keystore bleibt ausserhalb des testbaren Formats. */
object PasswortHuelle {
    private val MAGIC = byteArrayOf(0x4d, 0x4e, 0x41, 0x50) // MNAP
    private const val VERSION = 1
    private const val NONCE_BYTES = 12
    private const val TAG_BYTES = 16
    private const val MAX_PASSWORT_BYTES = 4096
    private const val KOPF_BYTES = 10

    fun verschluesseln(passwort: CharArray, key: SecretKey, zufall: SecureRandom = SecureRandom()): ByteArray {
        require(passwort.isNotEmpty() && passwort.size <= 1024)
        val kodiert = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(passwort))
        val klar = ByteArray(kodiert.remaining()).also(kodiert::get)
        require(klar.size in 1..MAX_PASSWORT_BYTES)
        val kopf = kopf(klar.size + TAG_BYTES)
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            // Keystore keys require the provider to choose the encryption IV.
            if (key.format == null) cipher.init(Cipher.ENCRYPT_MODE, key)
            else cipher.init(Cipher.ENCRYPT_MODE, key, zufall)
            val nonce = requireNotNull(cipher.iv)
            require(nonce.size == NONCE_BYTES)
            cipher.updateAAD(kopf)
            kopf + nonce + cipher.doFinal(klar)
        } finally {
            klar.fill(0)
            if (kodiert.hasArray()) kodiert.array().fill(0)
        }
    }

    fun entschluesseln(huelle: ByteArray, key: SecretKey): CharArray {
        require(huelle.size in (KOPF_BYTES + NONCE_BYTES + TAG_BYTES + 1)..
            (KOPF_BYTES + NONCE_BYTES + MAX_PASSWORT_BYTES + TAG_BYTES))
        require(huelle.copyOfRange(0, MAGIC.size).contentEquals(MAGIC))
        require(huelle[4].toInt() and 0xff == VERSION)
        require(huelle[5].toInt() and 0xff == NONCE_BYTES)
        val geheimLaenge = ByteBuffer.wrap(huelle, 6, 4).int
        require(geheimLaenge in (TAG_BYTES + 1)..(MAX_PASSWORT_BYTES + TAG_BYTES))
        require(KOPF_BYTES + NONCE_BYTES + geheimLaenge == huelle.size)
        val klar = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key,
                GCMParameterSpec(128, huelle.copyOfRange(KOPF_BYTES, KOPF_BYTES + NONCE_BYTES)))
            updateAAD(huelle.copyOfRange(0, KOPF_BYTES))
            doFinal(huelle.copyOfRange(KOPF_BYTES + NONCE_BYTES, huelle.size))
        }
        return try {
            val zeichen = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(klar))
            require(zeichen.remaining() in 1..1024)
            try { CharArray(zeichen.remaining()).also(zeichen::get) }
            finally { if (zeichen.hasArray()) zeichen.array().fill('\u0000') }
        } finally { klar.fill(0) }
    }

    fun sichern(passwort: CharArray, vorhandeneHuelle: ByteArray?, quelle: AutoSicherungsSchluessel): ByteArray {
        val key = quelle.vorhandener() ?: if (vorhandeneHuelle == null) quelle.anlegen()
            else throw AutoSicherungsSchluesselFehlt()
        return verschluesseln(passwort, key)
    }

    fun laden(huelle: ByteArray, quelle: AutoSicherungsSchluessel): CharArray =
        entschluesseln(huelle, quelle.vorhandener() ?: throw AutoSicherungsSchluesselFehlt())

    private fun kopf(geheimLaenge: Int): ByteArray = ByteArrayOutputStream().let { aus ->
        DataOutputStream(aus).use { it.write(MAGIC); it.writeByte(VERSION); it.writeByte(NONCE_BYTES); it.writeInt(geheimLaenge) }
        aus.toByteArray()
    }
}

data class SicherungsDokument(
    val kennung: String,
    val name: String,
    val mime: String,
    val geaendert: Long,
)

data class BegrenzteDokumente(val dokumente: List<SicherungsDokument>, val abgeschnitten: Boolean)

interface SicherungsOrdner {
    fun anlegen(name: String, mime: String): SicherungsDokument
    fun schreiben(dokument: SicherungsDokument, inhalt: ByteArray)
    fun lesen(dokument: SicherungsDokument, maximum: Long): ByteArray
    fun auflisten(maximum: Int): BegrenzteDokumente
    fun loeschen(dokument: SicherungsDokument): Boolean
}

enum class SicherungsLaufErgebnis { ERFOLG, ERFOLG_AUFBEWAHRUNG_FEHLER }

object AutoSicherungsRegeln {
    const val MIME = "application/vnd.magnolie.notes-backup"
    const val LISTEN_GRENZE = 256
    private val NAME = Regex("magnolie-notes-auto-\\d{8}T\\d{6}Z-[0-9a-f]{32}\\.magnolie")
    private val FORMAT = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC)

    fun name(zeit: Long, uuid: UUID = UUID.randomUUID()) =
        "magnolie-notes-auto-${FORMAT.format(Instant.ofEpochMilli(zeit))}-${uuid.toString().replace("-", "")}.magnolie"

    // ExternalStorageProvider derives unknown extensions as generic binary MIME.
    // The filename is only a candidate filter; authenticated readback remains mandatory.
    fun istEigen(dokument: SicherungsDokument) = dokument.mime in setOf(MIME, "application/octet-stream") && NAME.matches(dokument.name)

    fun zuLoeschen(dokumente: List<SicherungsDokument>, bestaetigterName: String,
                   aufbewahrung: Int): List<SicherungsDokument> {
        val eigen = dokumente.filter(::istEigen)
        val bestaetigt = eigen.singleOrNull { it.name == bestaetigterName } ?: return emptyList()
        if (eigen.size <= 1) return emptyList()
        val limit = aufbewahrung.coerceIn(AutoSicherungsKonfiguration.MIN_AUFBEWAHRUNG,
            AutoSicherungsKonfiguration.MAX_AUFBEWAHRUNG)
        val behalten = buildSet {
            add(bestaetigt.kennung)
            eigen.filterNot { it.kennung == bestaetigt.kennung }
                .sortedWith(compareByDescending<SicherungsDokument> { it.geaendert }.thenByDescending { it.name })
                .take(limit - 1).forEach { add(it.kennung) }
        }
        return eigen.filterNot { it.kennung in behalten }.sortedBy { it.geaendert }
    }
}

/** Providerunabhaengiger Vertrag: schreiben, schliessen, neu lesen, authentifizieren, erst dann Erfolg. */
class AutoSicherungsLauf(private val ordner: SicherungsOrdner) {
    fun ausfuehren(zeit: Long, aufbewahrung: Int, archiv: () -> ByteArray,
                  authentifizieren: (ByteArray) -> Unit, nachErfolg: () -> Unit): SicherungsLaufErgebnis {
        val name = AutoSicherungsRegeln.name(zeit)
        val dokument = ordner.anlegen(name, AutoSicherungsRegeln.MIME)
        try {
            check(dokument.name == name && AutoSicherungsRegeln.istEigen(dokument))
            val bytes = archiv()
            val erwartet = io.gitlab.maik3531.magnolienotes.daten.ArchivIdentitaet(bytes)
            try { ordner.schreiben(dokument, bytes) } finally { bytes.fill(0) }
            val gelesen = ordner.lesen(dokument, io.gitlab.maik3531.magnolienotes.daten.PortableArchiv.MAX_ARCHIV_BYTES)
            try { erwartet.pruefen(gelesen); authentifizieren(gelesen) } finally { gelesen.fill(0) }
        } catch (fehler: Throwable) {
            runCatching { ordner.loeschen(dokument) }
            throw fehler
        }
        nachErfolg()
        return try {
            val liste = ordner.auflisten(AutoSicherungsRegeln.LISTEN_GRENZE)
            if (liste.abgeschnitten) return SicherungsLaufErgebnis.ERFOLG_AUFBEWAHRUNG_FEHLER
            AutoSicherungsRegeln.zuLoeschen(liste.dokumente, dokument.name, aufbewahrung)
                .forEach { alt ->
                    val bytes = ordner.lesen(alt, io.gitlab.maik3531.magnolienotes.daten.PortableArchiv.MAX_ARCHIV_BYTES)
                    try { authentifizieren(bytes) } finally { bytes.fill(0) }
                    check(ordner.loeschen(alt))
                }
            SicherungsLaufErgebnis.ERFOLG
        } catch (_: Exception) { SicherungsLaufErgebnis.ERFOLG_AUFBEWAHRUNG_FEHLER }
    }
}
