package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonElement
import org.bouncycastle.crypto.agreement.X25519Agreement
import org.bouncycastle.crypto.digests.SHA256Digest
import org.bouncycastle.crypto.generators.HKDFBytesGenerator
import org.bouncycastle.crypto.params.HKDFParameters
import org.bouncycastle.crypto.params.X25519PrivateKeyParameters
import org.bouncycastle.crypto.params.X25519PublicKeyParameters
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Die kryptografischen Handgriffe des Magnolienbaums, eins zu eins nach
 * ENTWURF-MAGNOLIENBAUM.md, Abschnitte 5 und 6.
 */
object Krypto {

    val ZUSATZ: ByteArray = "magnolienbaum".toByteArray(Charsets.UTF_8)
    private val zufall = SecureRandom()

    // ------------------------------------------------------------ Grundlagen

    fun zufallsbytes(anzahl: Int): ByteArray = ByteArray(anzahl).also { zufall.nextBytes(it) }

    fun b64(roh: ByteArray): String = java.util.Base64.getEncoder().encodeToString(roh)

    /**
     * Strenges Base64 mit erwarteter Länge, wie `_fs_b64_lesen`. Der Decoder
     * von `java.util.Base64` weist – wie Pythons `validate=True` – alles ab,
     * was nicht ins Alphabet gehört.
     */
    fun b64Lesen(text: String?, laenge: Int): ByteArray {
        val roh = b64Roh(text ?: "") ?: throw BaumFehler("Base64 ist beschädigt.")
        if (roh.size != laenge) throw BaumFehler("Unerwartete Länge in der Nachricht.")
        return roh
    }

    /** Liefert null statt einer Ausnahme, wo ein Fehlschlag erwartbar ist. */
    fun b64Roh(text: String): ByteArray? = try {
        java.util.Base64.getDecoder().decode(text)
    } catch (fehler: IllegalArgumentException) {
        null
    }

    fun b64UrlLesen(text: String?, laenge: Int): ByteArray {
        if (text == null || text.contains("=") || text.length > 200) {
            throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        }
        val gefuellt = text + "=".repeat((4 - text.length % 4) % 4)
        val roh = try {
            java.util.Base64.getUrlDecoder().decode(gefuellt)
        } catch (fehler: IllegalArgumentException) {
            throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        }
        if (roh.size != laenge) throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        return roh
    }

    fun b64Url(roh: ByteArray): String =
        java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(roh)

    fun sha256(vararg teile: ByteArray): ByteArray {
        val d = MessageDigest.getInstance("SHA-256")
        teile.forEach { d.update(it) }
        return d.digest()
    }

    fun hmac(schluessel: ByteArray, nachricht: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(schluessel, "HmacSHA256"))
        return mac.doFinal(nachricht)
    }

    /** Entspricht `_baum_hmac` bzw. `_fs_mac`: Kennung, dann kanonischer Wert. */
    fun hmacUeber(schluessel: ByteArray, kennung: ByteArray, wert: JsonElement): ByteArray =
        hmac(schluessel, kennung + Kanonisch.bytes(wert))

    fun gleich(a: ByteArray, b: ByteArray): Boolean = MessageDigest.isEqual(a, b)

    fun hkdf(material: ByteArray, salz: ByteArray?, info: ByteArray, laenge: Int): ByteArray {
        val gen = HKDFBytesGenerator(SHA256Digest())
        gen.init(HKDFParameters(material, salz, info))
        return ByteArray(laenge).also { gen.generateBytes(it, 0, laenge) }
    }

    // ------------------------------------------------------------ X25519

    fun neuesSchluesselpaar(): Pair<ByteArray, ByteArray> {
        val geheim = X25519PrivateKeyParameters(zufall)
        return geheim.encoded to geheim.generatePublicKey().encoded
    }

    fun oeffentlichZu(geheim: ByteArray): ByteArray =
        X25519PrivateKeyParameters(geheim, 0).generatePublicKey().encoded

    fun austausch(geheim: ByteArray, fremdOeffentlich: ByteArray): ByteArray {
        val vertrag = X25519Agreement()
        vertrag.init(X25519PrivateKeyParameters(geheim, 0))
        val aus = ByteArray(vertrag.agreementSize)
        vertrag.calculateAgreement(X25519PublicKeyParameters(fremdOeffentlich, 0), aus, 0)
        return aus
    }

    /**
     * Der langlebige Partnerschlüssel aus `_sitzungsschluessel()`. Beide
     * Kennungen gehen der Größe nach geordnet ein, damit beide Seiten
     * unabhängig voneinander dasselbe errechnen.
     */
    fun partnerschluessel(
        geheimB64: String,
        partnerOeffentlichB64: String,
        kennungA: String,
        kennungB: String
    ): ByteArray {
        val gemeinsam = austausch(
            b64Roh(geheimB64) ?: throw BaumFehler("Der eigene Schlüssel ist beschädigt."),
            b64Roh(partnerOeffentlichB64) ?: throw BaumFehler("Der fremde Schlüssel ist beschädigt.")
        )
        val (erst, dann) = if (kennungA <= kennungB) kennungA to kennungB else kennungB to kennungA
        val info = ZUSATZ + erst.toByteArray(Charsets.UTF_8) + "|".toByteArray() +
            dann.toByteArray(Charsets.UTF_8)
        return hkdf(gemeinsam, null, info, 32)
    }

    /** `_fs_auth_schluessel`: der Beglaubigungsschlüssel einer `baum-fs1`-Sitzung. */
    fun authSchluessel(
        geheimB64: String,
        partnerOeffentlichB64: String,
        eigeneKennung: String,
        partnerKennung: String
    ): ByteArray {
        val statisch = partnerschluessel(
            geheimB64, partnerOeffentlichB64, eigeneKennung, partnerKennung
        )
        return hkdf(statisch, null, ZUSATZ + "\u0000baum-fs1\u0000auth".toByteArray(), 32)
    }

    // ------------------------------------------------------------ AES-256-GCM

    fun verschluesseln(schluessel: ByteArray, nonce: ByteArray, klar: ByteArray, zusatz: ByteArray): ByteArray {
        val ziffer = Cipher.getInstance("AES/GCM/NoPadding")
        ziffer.init(Cipher.ENCRYPT_MODE, SecretKeySpec(schluessel, "AES"), GCMParameterSpec(128, nonce))
        ziffer.updateAAD(zusatz)
        return ziffer.doFinal(klar)
    }

    fun entschluesseln(schluessel: ByteArray, nonce: ByteArray, geheim: ByteArray, zusatz: ByteArray): ByteArray {
        val ziffer = Cipher.getInstance("AES/GCM/NoPadding")
        ziffer.init(Cipher.DECRYPT_MODE, SecretKeySpec(schluessel, "AES"), GCMParameterSpec(128, nonce))
        ziffer.updateAAD(zusatz)
        return ziffer.doFinal(geheim)
    }

    // ------------------------------------------------------------ Fingerabdruck

    /** `fingerabdruck()`: vier Vierergruppen aus den ersten 64 Bit. */
    fun fingerabdruck(oeffentlichB64: String): String {
        val roh = b64Roh(oeffentlichB64) ?: return ""
        val h = sha256(roh, ZUSATZ).joinToString("") { "%02X".format(it) }
        return (0 until 16 step 4).joinToString("-") { h.substring(it, it + 4) }
    }

    /** `paarungs_code()`: der sechsstellige Vergleichswert des kurzen Wegs. */
    fun paarungsCode(oeffentlichA: String, oeffentlichB: String): String {
        val a = b64Roh(oeffentlichA) ?: return ""
        val b = b64Roh(oeffentlichB) ?: return ""
        val kleiner = if (vergleiche(a, b) <= 0) a else b
        val groesser = if (vergleiche(a, b) <= 0) b else a
        val h = sha256(kleiner, groesser, ZUSATZ)
        var zahl = 0L
        for (i in 0 until 4) zahl = (zahl shl 8) or (h[i].toLong() and 0xff)
        val text = "%06d".format(zahl % 1000000)
        return text.substring(0, 3) + " " + text.substring(3)
    }

    /** Python vergleicht bytes vorzeichenlos; Kotlin täte es vorzeichenbehaftet. */
    private fun vergleiche(a: ByteArray, b: ByteArray): Int {
        for (i in 0 until minOf(a.size, b.size)) {
            val x = a[i].toInt() and 0xff
            val y = b[i].toInt() and 0xff
            if (x != y) return x - y
        }
        return a.size - b.size
    }
}

class BaumFehler(nachricht: String) : Exception(nachricht)
