package io.gitlab.maik3531.magnolietabletbeta

import okio.ByteString.Companion.decodeBase64
import okio.ByteString.Companion.toByteString

/** Standard RFC 4648 transport encoding on API23+, using the already pinned
 * Okio implementation. Validation preserves java.util.Base64's Basic decoder
 * contract: no whitespace, URL alphabet, stray padding or ignored Unicode. */
internal object StandardBase64 {
    fun encode(bytes: ByteArray): String = bytes.toByteString().base64()

    fun decode(text: String): ByteArray {
        val firstPadding = text.indexOf('=')
        val contentLength = if (firstPadding < 0) text.length else firstPadding
        for (index in 0 until contentLength) {
            val c = text[index]
            require(c in 'A'..'Z' || c in 'a'..'z' || c in '0'..'9' || c == '+' || c == '/') { "Invalid standard Base64 data" }
        }
        if (firstPadding < 0) {
            // The existing Basic decoder also accepts omitted terminal padding.
            require(text.length % 4 != 1) { "Invalid standard Base64 length" }
        } else {
            val padding = text.length - firstPadding
            require(text.length % 4 == 0 && padding in 1..2 && contentLength % 4 == 4 - padding &&
                (firstPadding until text.length).all { text[it] == '=' }) { "Invalid standard Base64 padding" }
        }
        return requireNotNull(text.decodeBase64()) { "Invalid standard Base64 data" }.toByteArray()
    }
}
