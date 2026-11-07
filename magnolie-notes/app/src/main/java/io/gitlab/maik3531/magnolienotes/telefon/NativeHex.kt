package io.gitlab.maik3531.magnolienotes.telefon

/** Canonical lowercase bytes only; no hashing or authority decisions. */
internal object NativeHex {
    private const val DIGITS = "0123456789abcdef"
    internal fun lower(bytes: ByteArray): String {
        require(bytes.size <= Int.MAX_VALUE / 2)
        val result = CharArray(bytes.size * 2)
        for (index in bytes.indices) {
            val value = bytes[index].toInt() and 255
            result[index * 2] = DIGITS[value ushr 4]
            result[index * 2 + 1] = DIGITS[value and 15]
        }
        return result.concatToString()
    }
}
