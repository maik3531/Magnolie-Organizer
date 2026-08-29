package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Die kanonische Schreibweise des Magnolienbaums.
 *
 * Sie muss zeichengenau dem entsprechen, was der Organizer in
 * `_baum_kanonisch()` erzeugt:
 *
 *     json.dumps(wert, ensure_ascii=True, sort_keys=True,
 *                separators=(",", ":"), allow_nan=False)
 *
 * Jede Abweichung – ein Leerzeichen, eine andere Schlüsselreihenfolge, ein
 * nicht maskiertes Sonderzeichen – lässt jeden HMAC und jeden AES-GCM-Zusatz
 * auseinanderlaufen. Darum wird hier nichts der Bibliothek überlassen.
 */
object Kanonisch {

    val json = Json {
        ignoreUnknownKeys = true
        isLenient = false
        encodeDefaults = true
    }

    fun bytes(wert: JsonElement): ByteArray = text(wert).toByteArray(Charsets.UTF_8)

    fun text(wert: JsonElement): String {
        val bau = StringBuilder()
        schreibe(wert, bau)
        return bau.toString()
    }

    private fun schreibe(wert: JsonElement, bau: StringBuilder) {
        when (wert) {
            is JsonNull -> bau.append("null")
            is JsonObject -> {
                bau.append('{')
                // Python sortiert nach Unicode-Codepunkt, nicht nach UTF-16-Einheit.
                val schluessel = wert.keys.sortedWith(::vergleicheCodepunkte)
                for ((platz, name) in schluessel.withIndex()) {
                    if (platz > 0) bau.append(',')
                    zeichenkette(name, bau)
                    bau.append(':')
                    schreibe(wert.getValue(name), bau)
                }
                bau.append('}')
            }
            is JsonArray -> {
                bau.append('[')
                for ((platz, teil) in wert.withIndex()) {
                    if (platz > 0) bau.append(',')
                    schreibe(teil, bau)
                }
                bau.append(']')
            }
            is JsonPrimitive -> {
                if (wert.isString) {
                    zeichenkette(wert.content, bau)
                } else {
                    // Zahlen und Wahrheitswerte stehen schon in der Schreibweise
                    // da, in der Python sie ausgibt; sie werden unverändert
                    // durchgereicht.
                    bau.append(wert.content)
                }
            }
        }
    }

    /**
     * Genau Pythons `py_encode_basestring_ascii`: alles außerhalb von
     * 0x20–0x7e wird maskiert, `\` und `"` ebenfalls, die fünf kurzen
     * Fluchtzeichen bleiben kurz, Hexziffern sind klein.
     */
    private fun zeichenkette(wert: String, bau: StringBuilder) {
        bau.append('"')
        for (zeichen in wert) {
            when {
                zeichen == '\\' -> bau.append("\\\\")
                zeichen == '"' -> bau.append("\\\"")
                zeichen.code in 0x20..0x7e -> bau.append(zeichen)
                zeichen == '\u0008' -> bau.append("\\b")
                zeichen == '\u000C' -> bau.append("\\f")
                zeichen == '\n' -> bau.append("\\n")
                zeichen == '\r' -> bau.append("\\r")
                zeichen == '\t' -> bau.append("\\t")
                else -> bau.append("\\u").append("%04x".format(zeichen.code))
            }
        }
        bau.append('"')
    }

    /** Vergleicht zwei Zeichenketten nach Codepunkten, wie Python es tut. */
    private fun vergleicheCodepunkte(a: String, b: String): Int {
        var i = 0
        var j = 0
        while (i < a.length && j < b.length) {
            val pa = a.codePointAt(i)
            val pb = b.codePointAt(j)
            if (pa != pb) return pa.compareTo(pb)
            i += Character.charCount(pa)
            j += Character.charCount(pb)
        }
        return (a.length - i).compareTo(b.length - j)
    }
}
