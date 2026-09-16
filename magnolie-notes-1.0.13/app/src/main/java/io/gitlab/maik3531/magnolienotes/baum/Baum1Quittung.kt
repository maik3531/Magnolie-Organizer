package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** contracts/baum-1-receipt-v1.md; independent of FS1 receipts. */
object Baum1Quittung {
    private val DOMAIN = "magnolienbaum\u0000baum-1\u0000receipt-v1".toByteArray(Charsets.UTF_8)

    fun hash(umschlag: JsonObject): String = Krypto.sha256(Kanonisch.bytes(umschlag))
        .joinToString("") { "%02x".format(it) }

    fun erstellen(partnerKey: ByteArray, sender: String, recipient: String, umschlag: JsonObject): JsonObject {
        require(partnerKey.size == 32)
        val counter = umschlag["zaehler"] as? JsonPrimitive ?: throw BaumFehler("Die Nachricht ist beschädigt.")
        require(!counter.isString && counter.content.toLongOrNull()?.let { it > 0 } == true)
        require(umschlag["von"] == JsonPrimitive(sender))
        val core = buildJsonObject {
            put("format", JsonPrimitive("baum-1-receipt")); put("version", JsonPrimitive(1))
            put("sender", JsonPrimitive(sender)); put("recipient", JsonPrimitive(recipient))
            put("counter", counter); put("envelopeSha256", JsonPrimitive(hash(umschlag)))
            put("status", JsonPrimitive("accepted"))
        }
        val key = Krypto.hkdf(partnerKey, null, DOMAIN, 32)
        return try { JsonObject(core + ("mac" to JsonPrimitive(Krypto.b64(
            Krypto.hmacUeber(key, DOMAIN + byteArrayOf(0), core))))) }
        finally { key.fill(0) }
    }

    fun pruefen(partnerKey: ByteArray, sender: String, recipient: String, umschlag: JsonObject, receipt: JsonObject): Boolean =
        runCatching {
            val expected = erstellen(partnerKey, sender, recipient, umschlag)
            val macText = (receipt["mac"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return false
            val mac = Krypto.b64Lesen(macText, 32)
            Krypto.b64(mac) == macText && JsonObject(receipt - "mac") == JsonObject(expected - "mac") &&
                Krypto.gleich(mac, Krypto.b64Lesen((expected.getValue("mac") as JsonPrimitive).content, 32))
        }.getOrDefault(false)
}
