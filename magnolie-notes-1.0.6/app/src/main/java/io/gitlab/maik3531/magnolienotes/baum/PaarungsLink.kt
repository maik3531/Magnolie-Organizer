package io.gitlab.maik3531.magnolienotes.baum

import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.util.Base64
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class PaarungsVorschau(
    val text: String,
    val name: String,
    val adresse: String,
    val fingerabdruck: String
)

/** Dekodiert nur den QR-Transport; die Vertrauensprüfung bleibt in Paarung. */
object PaarungsLink {
    private const val PRAEFIX = "magnolie-pair:"
    private const val MAX_LINK_ZEICHEN = 8_192

    fun dekodiere(link: String?): String? {
        if (link == null || link.length !in (PRAEFIX.length + 1)..MAX_LINK_ZEICHEN ||
            !link.startsWith(PRAEFIX)) return null
        val nutzlast = link.substring(PRAEFIX.length)
        if (!nutzlast.matches(Regex("[A-Za-z0-9_-]+"))) return null
        return runCatching {
            val roh = Base64.getUrlDecoder().decode(
                nutzlast + "=".repeat((4 - nutzlast.length % 4) % 4))
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(roh)).toString()
        }.getOrNull()
    }

    fun vorschau(text: String, jetztSekunden: Long = System.currentTimeMillis() / 1000): PaarungsVorschau {
        val dokument = Paarung.pruefeDatei(text, jetztSekunden)
        val einlader = dokument.getValue("einlader").jsonObject
        val ziel = dokument.getValue("ziel").jsonObject
        val kennung = einlader.getValue("kennung").jsonPrimitive.content
        val name = einlader["name"]?.jsonPrimitive?.contentOrNull.orEmpty().ifBlank { kennung }
        val adresse = ziel.getValue("adresse").jsonPrimitive.content
        val port = ziel.getValue("port").jsonPrimitive.int
        val oeffentlich = einlader.getValue("oeffentlich").jsonPrimitive.content
        return PaarungsVorschau(text, name, "$adresse:$port", Krypto.fingerabdruck(oeffentlich))
    }
}
