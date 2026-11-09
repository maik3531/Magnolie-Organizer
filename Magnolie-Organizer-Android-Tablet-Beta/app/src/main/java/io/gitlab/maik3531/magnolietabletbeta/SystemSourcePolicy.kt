package io.gitlab.maik3531.magnolietabletbeta

import java.security.MessageDigest

/** Public-provider source metadata only; these identifiers confer no authority. */
internal object SystemSourcePolicy {
    enum class Kind(val wire: String) { EVENTS("events"), CONTACTS("contacts") }
    data class Source(val uid: String, val name: String, val kind: Kind, val providerWritable: Boolean = false)
    data class Snapshot(val state: String, val sources: List<Source>? = null, val errorCode: String? = null) {
        init { require((state == "authorized") == (sources != null)); require(sources == null || sources.size <= 1000) }
    }
    fun discover(allowed: Boolean, checkCurrent: () -> Unit, read: () -> List<Source>): Snapshot {
        checkCurrent()
        if (!allowed) return Snapshot("not_granted",errorCode="permission_required")
        return try {
            val sources=read();checkCurrent()
            check(sources.size<=1000) { "source_limit" }
            require(sources.map {it.uid}.toSet().size==sources.size)
            Snapshot("authorized",sources)
        } catch (_: SecurityException) {
            checkCurrent();Snapshot("not_granted",errorCode="permission_required")
        } catch (error: Exception) {
            checkCurrent() // Cancellation/deadline never becomes an empty successful discovery.
            Snapshot("unavailable",errorCode=if(error.message=="source_limit") "source_limit" else "provider_unavailable")
        }
    }
    fun kind(value: String): Kind = Kind.entries.firstOrNull { it.wire == value }
        ?: throw IllegalArgumentException("Unsupported Android system source kind")
    fun uid(kind: Kind, vararg parts: String?): String {
        val hash=MessageDigest.getInstance("SHA-256")
        for (part in parts) {
            // Length framing distinguishes null, empty strings, and delimiter-containing account names.
            val bytes=part?.toByteArray(Charsets.UTF_8)
            require(bytes == null || bytes.size <= 8192) { "source_metadata_limit" }
            hash.update(java.nio.ByteBuffer.allocate(4).putInt(bytes?.size ?: -1).array())
            if (bytes != null) hash.update(bytes)
        }
        return "android-${kind.wire}:"+hash.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
    }
    fun label(title: String?, account: String?): String {
        val primary=title?.takeIf { it.isNotBlank() } ?: account?.takeIf { it.isNotBlank() } ?: "Android"
        return (primary+if (!account.isNullOrBlank() && primary!=account) " ($account)" else "").take(1024)
    }
}
