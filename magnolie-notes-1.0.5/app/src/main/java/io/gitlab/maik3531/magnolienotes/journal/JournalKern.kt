package io.gitlab.maik3531.magnolienotes.journal

import kotlinx.serialization.Serializable
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

enum class JournalIntervall(val millis: Long?) {
    AUS(null), SECHS_STUNDEN(6L * 3600_000), ZWOELF_STUNDEN(12L * 3600_000),
    TAEGLICH(24L * 3600_000), WOECHENTLICH(7L * 24 * 3600_000)
}

@Serializable
data class NutzlastManifest(
    val hash: String,
    val size: Long,
    val schema: Int = 1
)

@Serializable
data class SnapshotManifest(
    val type: String = "magnolie-snapshot",
    val version: Int = 1,
    val uuid: String,
    val createdUtc: String,
    val platform: String = "android",
    val appVersion: String,
    val reason: String,
    val domain: String,
    val payload: NutzlastManifest,
    val summary: String,
    val syncEpoch: String,
    val pinned: Boolean = false,
    val mutationId: String = "",
    val restoreOperationId: String = ""
)

@Serializable
data class AppDatenNutzlast(val notizen: String, val baum: String)

@Serializable
data class KontaktZeile(
    val mime: String,
    val data: List<String?> = emptyList(),
    val sync: List<String?> = emptyList(),
    val primary: Boolean = false,
    val superPrimary: Boolean = false
)

@Serializable
data class KontaktRohstand(
    val rawContactId: Long = 0,
    val lookupKey: String = "",
    val accountName: String? = null,
    val accountType: String? = null,
    val dataSet: String? = null,
    val sourceId: String? = null,
    val aggregationMode: Int = 0,
    val rows: List<KontaktZeile> = emptyList(),
    val portable: io.gitlab.maik3531.magnolienotes.baum.KontaktDaten =
        io.gitlab.maik3531.magnolienotes.baum.KontaktDaten(),
    val beforeHash: String = "",
    val action: String = "",
    val generatedByMagnolie: Boolean = false
)

@Serializable
data class KontaktNutzlast(val contacts: List<KontaktRohstand>, val mutationId: String)

interface JournalKrypto {
    fun encrypt(plain: ByteArray, aad: ByteArray): ByteArray
    fun decrypt(ciphertext: ByteArray, aad: ByteArray): ByteArray
}

/** AES-256-GCM-Kern; der Schlüssel kann aus Android Keystore oder einem JVM-Fake kommen. */
class AesGcmKrypto(private val key: () -> SecretKey) : JournalKrypto {
    override fun encrypt(plain: ByteArray, aad: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(aad)
        return byteArrayOf(cipher.iv.size.toByte()) + cipher.iv + cipher.doFinal(plain)
    }

    override fun decrypt(ciphertext: ByteArray, aad: ByteArray): ByteArray {
        require(ciphertext.isNotEmpty())
        val n = ciphertext[0].toInt() and 0xff
        require(n in 12..32 && ciphertext.size > n + 16)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, ciphertext.copyOfRange(1, n + 1)))
        cipher.updateAAD(aad)
        return cipher.doFinal(ciphertext.copyOfRange(n + 1, ciphertext.size))
    }
}

interface SnapshotStore {
    fun list(): List<SnapshotManifest>
    fun write(manifest: SnapshotManifest, encryptedPayload: ByteArray)
    fun read(id: String): Pair<SnapshotManifest, ByteArray>
    fun delete(id: String)
    fun bytes(): Long
}

object JournalRegeln {
    const val RESERVE_BYTES = 256L * 1024 * 1024
    const val MAX_BYTES = 512L * 1024 * 1024
    const val DEDUPE_MS = 15L * 60_000
    fun budget(totalSpace: Long) = minOf(MAX_BYTES, totalSpace / 20)
    fun due(last: Long?, now: Long, interval: JournalIntervall) =
        interval.millis?.let { last == null || now - last >= it } ?: false

    fun behalten(entries: List<SnapshotManifest>, now: Long): Set<String> {
        val sorted = entries.sortedByDescending { Instant.parse(it.createdUtc).toEpochMilli() }
        val keep = sorted.filter { it.pinned }.mapTo(mutableSetOf()) { it.uuid }
        val preRestore = sorted.filter { it.reason == "pre-restore" }
        keep += preRestore.filter { now - Instant.parse(it.createdUtc).toEpochMilli() <= 30L * 86400_000 }
            .take(5).map { it.uuid }
        val short = sorted.filter { it.reason.startsWith("pre-sync") || it.reason.startsWith("contact-") }
            .filter { now - Instant.parse(it.createdUtc).toEpochMilli() <= 14L * 86400_000 }.take(20)
        keep += short.map { it.uuid }
        val regular = sorted.filter { it.reason == "scheduled" || it.reason == "manual" }
        keep += regular.distinctBy { Instant.parse(it.createdUtc).toString().take(10) }.take(8).map { it.uuid }
        keep += regular.distinctBy { Instant.parse(it.createdUtc).toString().take(7) }.take(6).map { it.uuid }
        return keep
    }

    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }

    fun manifest(reason: String, domain: String, appVersion: String, bytes: ByteArray,
                 summary: String, epoch: String, pinned: Boolean = false,
                 mutationId: String = "", now: Long = System.currentTimeMillis()) = SnapshotManifest(
        uuid = UUID.randomUUID().toString(), createdUtc = Instant.ofEpochMilli(now).toString(),
        appVersion = appVersion, reason = reason, domain = domain,
        payload = NutzlastManifest(sha256(bytes), bytes.size.toLong()), summary = summary,
        syncEpoch = epoch, pinned = pinned, mutationId = mutationId
    )
}
