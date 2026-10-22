package io.gitlab.maik3531.magnolienotes

/** Shared by crash capture and diagnostic export; never change exception types/frames. */
internal object DiagnoseMaskierung {
    private val secret = Regex("""(?i)(["']?\b(?:password|passwd|passphrase|passwort|kennwort|pwd|secret|client_secret|token|access[_-]?token|refresh[_-]?token|api[_-]?key|private[_-]?key|session[_-]?key|authorization|cookie|pin|telefon(?:nummer)?|telephone|phone(?:[_-]?number)?|mobile|mobil|rufnummer|(?:e-?)?mail(?:[_-]?(?:address|adresse))?|ip(?:[_-]?address)?|(?:remote|local|peer)[_-]?(?:address|ip))\b["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n,;}\]]+)""")
    private val credentials = Regex("""(?i)(https?://)[^\s/@]+:[^\s/@]+@""")
    private val bearer = Regex("""(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+""")
    private val email = Regex("""(?<![\w.*])(?!\*+@)[A-Za-z0-9.!#\$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+""")
    private val ipv4 = Regex("""(?<=://)(?:\d{1,3}\.){3}\d{1,3}\b""")
    private val technical = Regex("""(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+Z-]+)?|\b(?:time_ms|created_ms|expires_ms|timestamp)\b["']?\s*[:=]\s*\d+""")
    private val phone = Regex("""(?<![\w])\+?\d[\d ()./-]{5,}\d(?![\w])""")

    fun maskiere(value: String): String {
        var text = secret.replace(value) { match ->
            val quote = match.groupValues[2].firstOrNull()?.takeIf { it == '"' || it == '\'' }?.toString().orEmpty()
            match.groupValues[1] + quote + "***" + quote
        }
        text = credentials.replace(text) { it.groupValues[1] + "***:***@" }
        text = bearer.replace(text) { it.groupValues[1] + "***" }
        text = email.replace(text, "***")
        text = ipv4.replace(text) { match -> if (match.value.split('.').all { it.toInt() <= 255 }) "***" else match.value }
        fun numbers(part: String) = phone.replace(part) { match ->
            if (match.value.count(Char::isDigit) in 7..15) "***" else match.value
        }
        return buildString {
            var offset = 0
            for (match in technical.findAll(text)) {
                append(numbers(text.substring(offset, match.range.first)))
                append(match.value); offset = match.range.last + 1
            }
            append(numbers(text.substring(offset)))
        }
    }
}
