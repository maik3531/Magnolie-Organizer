package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import java.net.URI

/** The existing calendar Open action may hand an exact saved HTTPS attachment to Android. Refs #682. */
internal data class AttachmentLaunchRequest(val uri: String, val requestId: String, val session: String, val revision: String) {
    companion object {
        const val CALLBACK = "externalAttachmentResult"
        fun parse(value: JSONObject): AttachmentLaunchRequest {
            val keys = setOf("cmd", "dienst", "wert", "aktionArt", "aktionZiel", "land", "requestId", "session", "revision")
            require(value.keys().asSequence().toSet() == keys) { "invalid_request" }
            require(value.opt("cmd") == "sozial" && value.opt("dienst") == "custom" && value.opt("aktionArt") == "url") { "unsupported_action" }
            fun text(key: String, max: Int = 1024, allowEmpty: Boolean = false): String = (value.opt(key) as? String)?.also {
                require((allowEmpty || it.isNotEmpty()) && it.toByteArray(Charsets.UTF_8).size <= max) { "invalid_request" }
            } ?: error("invalid_request")
            val target = text("wert", 8192)
            require(text("aktionZiel", 8192) == target) { "invalid_request" }
            text("land", 128, true) // Part of the shared command, never an authority or URI input.
            return AttachmentLaunchRequest(AttachmentLaunchPolicy.https(target), text("requestId"), text("session"), text("revision"))
        }
    }
    fun reply(ok: Boolean, reason: String? = null): JSONObject = JSONObject().put("requestId", requestId)
        .put("session", session).put("revision", revision).put("ok", ok).also {
            if (reason != null) it.put("reason", reason)
        }
}

internal object AttachmentLaunchPolicy {
    /** Return the unchanged URI. Do not silently upgrade HTTP or resolve/download a URL here. */
    fun https(value: String): String {
        require(value.isNotEmpty() && value.toByteArray(Charsets.UTF_8).size <= 8192) { "invalid_url" }
        require(value.none { it <= ' ' || it == '\u007f' || it == '\\' || it in '\u202a'..'\u202e' || it in '\u2066'..'\u2069' }) { "invalid_url" }
        val uri = try { URI(value).parseServerAuthority() } catch (_: Exception) { throw IllegalArgumentException("invalid_url") }
        require(uri.scheme == "https" && !uri.isOpaque && !uri.host.isNullOrEmpty() && uri.rawUserInfo == null &&
            (uri.port == -1 || uri.port in 1..65535)) { "invalid_url" }
        // Encoded controls/backslashes can be interpreted differently by an external handler.
        var decoded = value
        repeat(4) {
            val next = StringBuilder(); var at = 0
            while (at < decoded.length) {
                if (decoded[at] == '%' && at + 2 < decoded.length) {
                    val byte = decoded.substring(at + 1, at + 3).toIntOrNull(16)
                    if (byte != null) {
                        require(byte >= 0x20 && byte != 0x7f && byte != 0x5c) { "invalid_url" }
                        next.append(byte.toChar()); at += 3; continue
                    }
                }
                next.append(decoded[at++])
            }
            decoded = next.toString()
        }
        require(!Regex("/(?:remote\\.php/dav|webdav)(?:/|$)", RegexOption.IGNORE_CASE).containsMatchIn(uri.path.orEmpty())) { "unsupported_action" }
        return value
    }

    fun savedTarget(request: AttachmentLaunchRequest, book: JSONObject): String {
        val uri = https(request.uri)
        var found = false
        for (section in listOf("termine", "aufgaben")) {
            val records = book.optJSONArray(section) ?: continue
            for (i in 0 until records.length()) {
                val attachments = records.optJSONObject(i)?.optJSONArray("kalenderAnhaenge") ?: continue
                for (j in 0 until attachments.length()) {
                    val item = attachments.optJSONObject(j) ?: continue
                    if (item.opt("uri") == uri) {
                        require(item.opt("localOnly") == false && item.opt("anbieter") in setOf("Web", "Google Drive", "OneDrive", "Dropbox")) { "attachment_blocked" }
                        found = true
                    }
                }
            }
        }
        require(found) { "attachment_not_saved" }
        return uri
    }
}
