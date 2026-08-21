package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull
import org.bouncycastle.crypto.agreement.X25519Agreement
import org.bouncycastle.crypto.digests.SHA256Digest
import org.bouncycastle.crypto.generators.HKDFBytesGenerator
import org.bouncycastle.crypto.params.HKDFParameters
import org.bouncycastle.crypto.params.X25519PrivateKeyParameters
import org.bouncycastle.crypto.params.X25519PublicKeyParameters
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object TelefonParameter {
    const val PROTOKOLL = "magnolie-phone/1"
    const val PORT = 8741
    const val NSD_TYP = "_magnolie-phone._tcp"
    const val RFCOMM_UUID = "7b1d9e2a-5c43-4f68-a172-9d30e6b4c851"
    const val PAIRING_RAHMEN_MAX = 65_536
    const val VERSCHLUESSELT_RAHMEN_MAX = 1_048_576
    const val ANWENDUNG_MAX = 262_144
}

class TelefonProtokollFehler(nachricht: String) : Exception(nachricht)

/** Fassung 1: Unicode bleibt UTF-8; Schlüssel werden nach Unicode-Codepunkten sortiert. */
object TelefonKanonisch {
    val json = Json { isLenient = false; allowSpecialFloatingPointValues = false }

    fun bytes(wert: JsonElement): ByteArray = text(wert).toByteArray(Charsets.UTF_8)

    fun text(wert: JsonElement): String = buildString { schreibe(wert, this) }

    private fun schreibe(wert: JsonElement, aus: StringBuilder) {
        when (wert) {
            JsonNull -> aus.append("null")
            is JsonObject -> {
                aus.append('{')
                wert.keys.sortedWith(::codepunktVergleich).forEachIndexed { index, name ->
                    if (index > 0) aus.append(',')
                    zeichenkette(name, aus)
                    aus.append(':')
                    schreibe(wert.getValue(name), aus)
                }
                aus.append('}')
            }
            is JsonArray -> {
                aus.append('[')
                wert.forEachIndexed { index, teil ->
                    if (index > 0) aus.append(',')
                    schreibe(teil, aus)
                }
                aus.append(']')
            }
            is JsonPrimitive -> if (wert.isString) zeichenkette(wert.content, aus) else {
                if (wert.booleanOrNull == null && wert.longOrNull == null) {
                    throw TelefonProtokollFehler("Bruchzahlen sind in Protokollfassung 1 verboten.")
                }
                aus.append(wert.content)
            }
        }
    }

    private fun zeichenkette(text: String, aus: StringBuilder) {
        aus.append('"')
        text.forEach { zeichen ->
            when (zeichen) {
                '"' -> aus.append("\\\"")
                '\\' -> aus.append("\\\\")
                '\b' -> aus.append("\\b")
                '\u000c' -> aus.append("\\f")
                '\n' -> aus.append("\\n")
                '\r' -> aus.append("\\r")
                '\t' -> aus.append("\\t")
                else -> if (zeichen.code < 0x20) aus.append("\\u%04x".format(zeichen.code)) else aus.append(zeichen)
            }
        }
        aus.append('"')
    }

    private fun codepunktVergleich(a: String, b: String): Int {
        var ai = 0
        var bi = 0
        while (ai < a.length && bi < b.length) {
            val ac = a.codePointAt(ai)
            val bc = b.codePointAt(bi)
            if (ac != bc) return ac.compareTo(bc)
            ai += Character.charCount(ac)
            bi += Character.charCount(bc)
        }
        return (a.length - ai).compareTo(b.length - bi)
    }
}

object TelefonRahmen {
    fun schreiben(ausgabe: OutputStream, objekt: JsonObject, max: Int = TelefonParameter.PAIRING_RAHMEN_MAX) {
        val daten = TelefonKanonisch.bytes(objekt)
        if (daten.isEmpty() || daten.size > max) throw TelefonProtokollFehler("Ungültige Rahmenlänge.")
        DataOutputStream(ausgabe).apply { writeInt(daten.size); write(daten); flush() }
    }

    fun lesen(eingabe: InputStream, max: Int = TelefonParameter.PAIRING_RAHMEN_MAX): JsonObject {
        val laenge = DataInputStream(eingabe).readInt().toLong() and 0xffff_ffffL
        if (laenge == 0L || laenge > max) throw TelefonProtokollFehler("Ungültige Rahmenlänge.")
        val daten = ByteArray(laenge.toInt())
        DataInputStream(eingabe).readFully(daten)
        val text = try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(daten)).toString()
        } catch (_: Exception) {
            throw TelefonProtokollFehler("Ungültiges UTF-8.")
        }
        if (doppelteObjektschluessel(text)) throw TelefonProtokollFehler("Doppelter JSON-Schlüssel.")
        val element = try { TelefonKanonisch.json.parseToJsonElement(text) } catch (_: Exception) {
            throw TelefonProtokollFehler("Ungültiges JSON.")
        }
        return element as? JsonObject ?: throw TelefonProtokollFehler("Ein Rahmen muss ein JSON-Objekt sein.")
    }

    /* Der JSON-Parser akzeptiert Duplikate. Dieser Scanner verfolgt pro Objekt seine Schlüssel. */
    private fun doppelteObjektschluessel(text: String): Boolean {
        data class Ebene(val objekt: Boolean, val schluessel: MutableSet<String> = mutableSetOf(), var erwartet: Boolean = true)
        val stapel = ArrayDeque<Ebene>()
        var i = 0
        while (i < text.length) {
            when (text[i]) {
                '{' -> stapel.addLast(Ebene(true))
                '[' -> stapel.addLast(Ebene(false, erwartet = false))
                '}', ']' -> if (stapel.isNotEmpty()) stapel.removeLast()
                ',' -> stapel.lastOrNull()?.takeIf { it.objekt }?.erwartet = true
                '"' -> {
                    val start = i
                    i++
                    var escaped = false
                    while (i < text.length && (escaped || text[i] != '"')) {
                        escaped = !escaped && text[i] == '\\'
                        if (text[i] != '\\' || escaped.not()) escaped = false
                        i++
                    }
                    val ende = i
                    val ebene = stapel.lastOrNull()
                    if (ebene?.objekt == true && ebene.erwartet) {
                        var j = ende + 1
                        while (j < text.length && text[j].isWhitespace()) j++
                        if (j < text.length && text[j] == ':') {
                            val schluessel = TelefonKanonisch.json.parseToJsonElement(text.substring(start, ende + 1)).let {
                                (it as JsonPrimitive).content
                            }
                            if (!ebene.schluessel.add(schluessel)) return true
                            ebene.erwartet = false
                        }
                    }
                }
            }
            i++
        }
        return false
    }
}

object TelefonKrypto {
    private val zufall = SecureRandom()
    private fun label(text: String) = text.toByteArray(Charsets.UTF_8)

    fun zufall(laenge: Int) = ByteArray(laenge).also(zufall::nextBytes)
    fun b64(daten: ByteArray): String = Base64.getEncoder().encodeToString(daten)
    fun b64(text: String, laenge: Int): ByteArray = try { Base64.getDecoder().decode(text) } catch (_: Exception) {
        throw TelefonProtokollFehler("Ungültiges Base64.")
    }.also { if (it.size != laenge || b64(it) != text) throw TelefonProtokollFehler("Ungültiges Base64.") }

    fun schluesselpaar(): Pair<ByteArray, ByteArray> = X25519PrivateKeyParameters(zufall).let {
        it.encoded to it.generatePublicKey().encoded
    }

    fun austausch(privat: ByteArray, oeffentlich: ByteArray): ByteArray {
        val agreement = X25519Agreement().apply { init(X25519PrivateKeyParameters(privat, 0)) }
        return ByteArray(32).also {
            agreement.calculateAgreement(X25519PublicKeyParameters(oeffentlich, 0), it, 0)
            if (it.all { byte -> byte == 0.toByte() }) throw TelefonProtokollFehler("Ungültiger X25519-Schlüssel.")
        }
    }

    fun sha256(vararg teile: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").run {
        teile.forEach(::update); digest()
    }

    fun hmac(schluessel: ByteArray, vararg teile: ByteArray): ByteArray = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(schluessel, "HmacSHA256")); teile.forEach(::update); doFinal()
    }

    fun hkdf(ikm: ByteArray, salz: ByteArray?, info: ByteArray, laenge: Int): ByteArray {
        val generator = HKDFBytesGenerator(SHA256Digest()).apply { init(HKDFParameters(ikm, salz, info)) }
        return ByteArray(laenge).also { generator.generateBytes(it, 0, it.size) }
    }

    fun paarung(init: JsonObject, antwort: JsonObject, eigenEphemerPrivat: ByteArray,
                eigenStatischPrivat: ByteArray): PaarungsMaterial {
        val transcript = sha256(TelefonKanonisch.bytes(init), TelefonKanonisch.bytes(antwort))
        val e = austausch(eigenEphemerPrivat, b64(antwort.getValue("ephemeral_public").toString().trim('"'), 32))
        val s = austausch(eigenStatischPrivat, b64(antwort.getValue("static_public").toString().trim('"'), 32))
        val key = hkdf(e + s,
            sha256(label("magnolie-phone-pair-v1/salt\u0000"), transcript),
            label("magnolie-phone-pair-v1/key\u0000") + transcript, 32)
        val hash = hmac(key, label("magnolie-phone-pair-v1/code\u0000"), transcript)
        val zahl = ByteBuffer.wrap(hash, 0, 4).int.toLong() and 0xffff_ffffL
        val roh = "%06d".format(zahl % 1_000_000)
        return PaarungsMaterial(transcript, key, roh.substring(0, 3) + " " + roh.substring(3))
    }

    fun beweis(material: PaarungsMaterial, label: String, seite: String): ByteArray =
        hmac(material.schluessel, this.label(label), seite.toByteArray(), material.transcript)

    fun fingerabdruck(oeffentlich: ByteArray): String = sha256(
        label("magnolie-phone-fingerprint-v1\u0000"), oeffentlich
    ).take(8).joinToString("") { "%02X".format(it) }.chunked(4).joinToString("-")

    fun nonce(prefix: ByteArray, seq: Long): ByteArray {
        require(prefix.size == 4 && seq >= 0)
        return prefix + ByteBuffer.allocate(8).putLong(seq).array()
    }

    fun verschluesseln(key: ByteArray, nonce: ByteArray, klar: ByteArray, aad: ByteArray): ByteArray =
        Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce)); updateAAD(aad); doFinal(klar)
        }

    fun entschluesseln(key: ByteArray, nonce: ByteArray, geheim: ByteArray, aad: ByteArray): ByteArray =
        Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce)); updateAAD(aad); doFinal(geheim)
        }
}

data class PaarungsMaterial(val transcript: ByteArray, val schluessel: ByteArray, val code: String)
