package io.gitlab.maik3531.magnolienotes.daten

import java.util.Base64

/** Neutral attachment validation shared by storage, import and personal sync. */
object AnhangPruefung {
    const val ROH_MAX = 8 * 1024 * 1024
    const val DATA_URL_MAX = 12_000_000
    val arten = mapOf("image/jpeg" to "image", "image/png" to "image", "image/webp" to "image",
        "image/gif" to "image", "application/pdf" to "pdf")

    data class Inhalt(val bytes: ByteArray, val mime: String)

    fun mime(roh: ByteArray): String? = when {
        roh.size >= 3 && roh[0] == 0xff.toByte() && roh[1] == 0xd8.toByte() && roh[2] == 0xff.toByte() -> "image/jpeg"
        roh.size >= 8 && roh.copyOfRange(0, 8).contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) -> "image/png"
        roh.size >= 12 && String(roh, 0, 4, Charsets.US_ASCII) == "RIFF" && String(roh, 8, 4, Charsets.US_ASCII) == "WEBP" -> "image/webp"
        roh.size >= 6 && String(roh, 0, 6, Charsets.US_ASCII) in setOf("GIF87a", "GIF89a") -> "image/gif"
        roh.size >= 5 && String(roh, 0, 5, Charsets.US_ASCII) == "%PDF-" -> "application/pdf"
        else -> null
    }

    fun dataUrl(value: String): Inhalt? {
        if (value.isEmpty() || value.length > DATA_URL_MAX || !value.startsWith("data:")) return null
        val marker = ";base64,"; val split = value.indexOf(marker)
        if (split <= 5 || value.indexOf(marker, split + 1) >= 0) return null
        val mime = value.substring(5, split)
        if (mime !in arten) return null
        val encoded = value.substring(split + marker.length)
        if (encoded.isEmpty() || !Regex("[A-Za-z0-9+/]*={0,2}").matches(encoded)) return null
        val raw = runCatching { Base64.getDecoder().decode(encoded) }.getOrNull() ?: return null
        if (raw.size !in 1..ROH_MAX || Base64.getEncoder().encodeToString(raw) != encoded || mime(raw) != mime) return null
        return Inhalt(raw, mime)
    }
}
