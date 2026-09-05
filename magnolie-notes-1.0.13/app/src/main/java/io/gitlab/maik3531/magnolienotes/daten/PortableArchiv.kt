package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.security.SecureRandom
import java.time.Instant
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

@Serializable
private data class PortableNutzlast(
    val type: String = "magnolie-portable-bestand",
    val version: Int = 2,
    val createdUtc: String,
    val bestand: Bestand,
)

data class PortableVorschau(
    val erstellt: String,
    val notizen: Int,
    val notizbuecher: Int,
    val aufgaben: Int,
    val papierkorb: Int,
)

class GeprueftesPortableArchiv internal constructor(
    val bestandJson: String,
    val vorschau: PortableVorschau,
)

/** Eigenstaendiges, passwortgeschuetztes Archiv ohne Baum- oder Keystore-Material. */
object PortableArchiv {
    const val ITERATIONEN = 240_000
    const val MAX_ARCHIV_BYTES = 128L * 1024 * 1024
    private const val MAX_KLARTEXT_BYTES = 120L * 1024 * 1024
    private const val SALZ_BYTES = 16
    private const val NONCE_BYTES = 12
    private const val TAG_BYTES = 16
    private val MAGIC = "MAGNOLIE-ARCHIV".toByteArray(Charsets.US_ASCII)
    private val zufall = SecureRandom()

    fun erstellen(bestand: Bestand, passwort: CharArray): ByteArray =
        erstellen(bestand, passwort, 2)

    internal fun erstellen(bestand: Bestand, passwort: CharArray, version: Int): ByteArray {
        require(version in 1..2)
        pruefePasswort(passwort)
        val portable = portable(bestand, version >= 2)
        val klar = Ablage.json.encodeToString(PortableNutzlast.serializer(), PortableNutzlast(
            version = version, createdUtc = Instant.now().toString(), bestand = portable)).toByteArray(Charsets.UTF_8)
        require(klar.size <= MAX_KLARTEXT_BYTES)
        val salz = ByteArray(SALZ_BYTES).also(zufall::nextBytes)
        val nonce = ByteArray(NONCE_BYTES).also(zufall::nextBytes)
        val kopf = kopf(salz, nonce, klar.size + TAG_BYTES, version)
        val key = schluessel(passwort, salz, ITERATIONEN)
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce))
            cipher.updateAAD(kopf)
            (kopf + cipher.doFinal(klar)).also { require(it.size.toLong() <= MAX_ARCHIV_BYTES) }
        } finally {
            klar.fill(0)
            key.encoded?.fill(0)
        }
    }

    fun pruefen(archiv: ByteArray, passwort: CharArray): GeprueftesPortableArchiv {
        pruefePasswort(passwort)
        require(archiv.size.toLong() <= MAX_ARCHIV_BYTES)
        val minimum = MAGIC.size + 1 + 1 + 1 + 1 + 4 + 1 + 8 + SALZ_BYTES + NONCE_BYTES + TAG_BYTES
        require(archiv.size >= minimum)
        var p = 0
        fun u8() = archiv[p++].toInt() and 0xff
        require(archiv.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)); p += MAGIC.size
        val archivVersion = u8()
        require(archivVersion in 1..2)
        require(u8() == 1) // PBKDF2WithHmacSHA256
        require(u8() == 1) // AES-256-GCM
        val salzLaenge = u8()
        require(salzLaenge in 16..32)
        val iterationen = ((u8() shl 24) or (u8() shl 16) or (u8() shl 8) or u8())
        require(iterationen == ITERATIONEN)
        val nonceLaenge = u8()
        require(nonceLaenge == NONCE_BYTES)
        var geheimLaenge = 0L
        repeat(8) { geheimLaenge = (geheimLaenge shl 8) or u8().toLong() }
        require(geheimLaenge in TAG_BYTES.toLong()..(MAX_KLARTEXT_BYTES + TAG_BYTES))
        val kopfLaenge = p + salzLaenge + nonceLaenge
        require(kopfLaenge.toLong() + geheimLaenge == archiv.size.toLong())
        val salz = archiv.copyOfRange(p, p + salzLaenge); p += salzLaenge
        val nonce = archiv.copyOfRange(p, p + nonceLaenge); p += nonceLaenge
        val key = schluessel(passwort, salz, iterationen)
        val klar = try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, nonce))
            cipher.updateAAD(archiv.copyOfRange(0, kopfLaenge))
            cipher.doFinal(archiv.copyOfRange(p, archiv.size))
        } finally { key.encoded?.fill(0) }
        return try {
            require(klar.size <= MAX_KLARTEXT_BYTES)
            val payload = Ablage.json.decodeFromString(PortableNutzlast.serializer(), klar.decodeToString())
            require(payload.type == "magnolie-portable-bestand" && payload.version == archivVersion)
            Instant.parse(payload.createdUtc)
            val migrated = migrieren(payload.version, payload.bestand)
            val bestand = portable(migrated)
            require(bestand == migrated) { "Nicht portabler Bestand" }
            val bestandJson = Ablage.json.encodeToString(Bestand.serializer(), bestand)
            GeprueftesPortableArchiv(bestandJson, PortableVorschau(payload.createdUtc,
                bestand.notizen.size, bestand.notizbuecher.size, bestand.aufgaben.size,
                bestand.papierkorb.size))
        } finally { klar.fill(0) }
    }

    fun istArchiv(roh: ByteArray): Boolean = roh.size >= MAGIC.size &&
        roh.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)

    internal fun migrieren(version: Int, bestand: Bestand): Bestand {
        require(version in 1..2)
        return bestand.copy(aufgaben = AufgabenHierarchie.normalisieren(bestand.aufgaben))
    }

    private fun portable(bestand: Bestand, normalisiereAufgaben: Boolean = true): Bestand = bestand.copy(
        notizen = bestand.notizen.map(::portable),
        aufgaben = bestand.aufgaben.map(::portable).let {
            if (normalisiereAufgaben) AufgabenHierarchie.normalisieren(it) else it
        },
        papierkorb = bestand.papierkorb.map { it.copy(
            notiz = it.notiz?.let(::portable), aufgabe = it.aufgabe?.let(::portable)) },
        personalSync = PersonalSyncState(),
    )

    private fun portable(notiz: Notiz) = notiz.copy(baumFreigabe = null, baumGeaendert = 0,
        baumVersion = 0, baumQuelle = "")

    private fun portable(aufgabe: Aufgabe) = aufgabe.copy(herkunft = "", vonZweig = "",
        fremdId = "", delegiertAn = "")

    private fun kopf(salz: ByteArray, nonce: ByteArray, geheimLaenge: Int, version: Int): ByteArray {
        val aus = ByteArrayOutputStream()
        DataOutputStream(aus).use {
            it.write(MAGIC); it.writeByte(version); it.writeByte(1); it.writeByte(1)
            it.writeByte(salz.size); it.writeInt(ITERATIONEN); it.writeByte(nonce.size)
            it.writeLong(geheimLaenge.toLong()); it.write(salz); it.write(nonce)
        }
        return aus.toByteArray()
    }

    private fun schluessel(passwort: CharArray, salz: ByteArray, iterationen: Int): SecretKeySpec {
        val spec = PBEKeySpec(passwort, salz, iterationen, 256)
        return try { SecretKeySpec(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
            .generateSecret(spec).encoded, "AES") } finally { spec.clearPassword() }
    }

    private fun pruefePasswort(passwort: CharArray) = require(passwort.isNotEmpty() && passwort.size <= 1024)
}
