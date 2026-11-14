package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardCopyOption.*
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** Dedicated nonportable native consent storage, not a document grant loader.
 * Native peer/provider callbacks always run OUTSIDE the private file lock.
 * No receiver, UI or automatic capability is activated by this core.
 */
internal class KontaktOriginalDauerfreigaben internal constructor(
    private val root: File,
    private val schutz: KontaktOriginalSchutz,
    private val stage: (String) -> Unit = {}
) {
    private data class Inhalt(val generation: String, val partner: KontaktOriginalFreigaben.Partner,
                              val quellen: Set<KontaktOriginalFreigaben.Quelle>)
    private class Beleg(val store: KontaktOriginalDauerfreigaben, val inhalt: Inhalt, val hash: String)
    class Gespeichert internal constructor(private val beleg: Any) {
        private fun native(): Beleg = (beleg as? Beleg) ?: throw SecurityException("contact_original_native_store_required")
        fun pruefen() { native().let { it.store.pruefen(it) } }
        fun partner(): KontaktOriginalFreigaben.Partner = native().also { pruefen() }.inhalt.partner
        fun quellen(): Set<KontaktOriginalFreigaben.Quelle> = native().also { pruefen() }.inhalt.quellen.toSet()
        internal fun stammtVon(store: KontaktOriginalDauerfreigaben, hash: String?): Boolean = native().let {
            it.store === store && it.hash == hash
        }
        internal fun aus(store: KontaktOriginalDauerfreigaben): Boolean = native().store === store
        internal fun gleich(other: Gespeichert): Boolean = native().let {
            val second = other.native()
            it.store === second.store && it.hash == second.hash
        }
    }

    fun laden(): Gespeichert? = locked(create = false) {
        if (read("hold") != null) return@locked null
        val blob = read("approval.bin") ?: return@locked null
        val parsed = decode(blob)
        Gespeichert(Beleg(this, parsed, hash(blob)))
    }

    fun bewilligen(entscheidung: KontaktOriginalFreigaben.Entscheidung): Gespeichert? {
        entscheidung.pruefen()
        val peer = entscheidung.partner()
        val sources = entscheidung.quellen()
        if (sources.isEmpty()) {
            entscheidung.pruefen(); widerrufen(); entscheidung.pruefen()
            return null
        }
        val record = Inhalt(UUID.randomUUID().toString(), peer, sources.toSet())
        require(listOf(peer.kennung, peer.schluessel).all { it.isNotBlank() && gueltigerText(it) } &&
            sources.size in 1..32 && sources.all { source -> source.datenbank > 0 &&
                listOf(source.konto.kontoName, source.konto.kontoTyp, source.konto.datenSatz).all(::gueltigerText) }) {
            "contact_original_native_identity_unrepresentable"
        }
        val clear = encode(record)
        try { schutz.klartextPruefen(clear) } catch (error: Exception) { clear.fill(0); throw error }
        val hold = "pending:${record.generation}".toByteArray(Charsets.US_ASCII)
        var writtenHash: String? = null
        var publicationAttempted = false
        try {
            locked(create = true) { write("hold", hold) }
            entscheidung.pruefen()
            locked(create = false) {
                ownHold(hold)
                schutz.neuerEntscheidungsschluessel()
                val blob = schutz.verschliessen(clear)
                writtenHash = hash(blob)
                write("approval.bin", blob)
            }
            entscheidung.pruefen()
            locked(create = false) {
                ownHold(hold)
                val blob = requireNotNull(read("approval.bin"))
                require(hash(blob) == writtenHash && decode(blob) == record) { "contact_original_store_changed" }
                publicationAttempted = true
                Files.delete(root.toPath().resolve("hold"))
                stage("hold:removed")
                synchronisiereOrdner(root)
                stage("published")
            }
            entscheidung.pruefen()
            val result = laden() ?: error("contact_original_store_unavailable")
            require(result.stammtVon(this, writtenHash)) { "contact_original_store_changed" }
            return result
        } catch (error: Exception) {
            if (publicationAttempted) try {
                locked(create = false) {
                    // Never erase a different/newer native decision on failure.
                    val current = read("approval.bin")
                    if (current != null && hash(current) == writtenHash) {
                        write("hold", "failed:${record.generation}".toByteArray(Charsets.US_ASCII))
                        schutz.schluesselWiderrufen()
                    }
                }
            } catch (holdError: Exception) { error.addSuppressed(holdError) }
            throw error
        } finally { clear.fill(0) }
    }

    /** Explicit native revoke: persistent negative state precedes key deletion.
     * Any failure is reported; callers must keep volatile permission blocked.
     */
    fun widerrufen() {
        locked(create = true) {
            write("hold", "revoked:${UUID.randomUUID()}".toByteArray(Charsets.US_ASCII))
            schutz.schluesselWiderrufen()
            if (read("approval.bin") != null) Files.delete(root.toPath().resolve("approval.bin"))
            synchronisiereOrdner(root)
        }
    }

    private fun pruefen(beleg: Beleg) {
        val current = laden() ?: throw SecurityException("contact_original_stored_approval_unavailable")
        if (beleg.store !== this || !current.stammtVon(this, beleg.hash))
            throw SecurityException("contact_original_stored_approval_changed")
    }

    private fun ownHold(expected: ByteArray) {
        require(read("hold")?.contentEquals(expected) == true) { "contact_original_store_transaction_changed" }
    }

    private fun <T> locked(create: Boolean, block: () -> T): T? {
        val path = root.toPath().toAbsolutePath().normalize()
        return locks.computeIfAbsent(path.toString()) { ReentrantLock() }.withLock {
            if (!Files.exists(path, NOFOLLOW_LINKS)) {
                if (!create) return@withLock null
                Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")))
                synchronisiereOrdner(requireNotNull(root.parentFile))
            }
            require(Files.isDirectory(path, NOFOLLOW_LINKS)) { "contact_original_private_directory_required" }
            privatePermissions(path)
            val guard = path.resolve("guard.lock")
            if (create && !Files.exists(guard, NOFOLLOW_LINKS)) {
                Files.createFile(guard, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))
                synchronisiereOrdner(root)
            }
            val before = Files.readAttributes(guard, BasicFileAttributes::class.java, NOFOLLOW_LINKS)
            require(before.isRegularFile && before.fileKey() != null)
            privatePermissions(guard)
            FileChannel.open(guard, WRITE, NOFOLLOW_LINKS).use { channel ->
                channel.lock().use {
                    val after = Files.readAttributes(guard, BasicFileAttributes::class.java, NOFOLLOW_LINKS)
                    require(after.isRegularFile && after.fileKey() == before.fileKey()) { "contact_original_private_lock_changed" }
                    block()
                }
            }
        }
    }

    private fun read(name: String): ByteArray? {
        val path = root.toPath().resolve(name)
        if (!Files.exists(path, NOFOLLOW_LINKS)) return null
        val before = Files.readAttributes(path, BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        require(before.isRegularFile && before.fileKey() != null && before.size() in 1..MAX_FILE.toLong()) { "contact_original_private_file_required" }
        privatePermissions(path)
        val bytes = FileChannel.open(path, READ, NOFOLLOW_LINKS).use { channel ->
            val buffer = ByteBuffer.allocate(before.size().toInt() + 1)
            while (buffer.hasRemaining() && channel.read(buffer) != -1) { }
            require(buffer.position() == before.size().toInt()) { "contact_original_private_file_changed" }
            buffer.flip(); ByteArray(buffer.remaining()).also { buffer.get(it) }
        }
        val after = Files.readAttributes(path, BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        require(before.fileKey() == after.fileKey() && before.size() == after.size() && before.lastModifiedTime() == after.lastModifiedTime())
        return bytes
    }

    private fun write(name: String, bytes: ByteArray) {
        require(bytes.size in 1..MAX_FILE)
        val target = root.toPath().resolve(name)
        if (Files.exists(target, NOFOLLOW_LINKS)) read(name)
        val temp = Files.createTempFile(root.toPath(), "consent-", ".pending",
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))
        try {
            FileChannel.open(temp, WRITE, NOFOLLOW_LINKS).use { channel ->
                val buffer = ByteBuffer.wrap(bytes)
                while (buffer.hasRemaining()) channel.write(buffer)
                channel.force(true)
            }
            stage("$name:temporary_flushed")
            Files.move(temp, target, ATOMIC_MOVE, REPLACE_EXISTING)
            synchronisiereOrdner(root)
            stage("$name:replaced")
        } finally { Files.deleteIfExists(temp) }
    }

    private fun privatePermissions(path: java.nio.file.Path) {
        require(Files.getPosixFilePermissions(path, NOFOLLOW_LINKS).intersect(
            PosixFilePermissions.fromString("---rwxrwx")).isEmpty()) { "contact_original_private_permissions_required" }
    }

    private fun gueltigerText(value: String?): Boolean = value == null || value.length <= 2048 &&
        value.none(Char::isISOControl) && value.codePoints().noneMatch { it in 0xD800..0xDFFF }

    private fun encode(value: Inhalt): ByteArray = buildJsonObject {
        put("format", 1); put("generation", value.generation)
        put("peer", buildJsonObject { put("id", value.partner.kennung); put("key", value.partner.schluessel) })
        put("sources", JsonArray(value.quellen.sortedWith(compareBy({ it.datenbank }, { it.konto.kontoTyp },
            { it.konto.kontoName }, { it.konto.datenSatz })).map { source -> buildJsonObject {
            put("database", source.datenbank)
            put("name", source.konto.kontoName?.let(::JsonPrimitive) ?: JsonNull)
            put("type", source.konto.kontoTyp?.let(::JsonPrimitive) ?: JsonNull)
            put("data_set", source.konto.datenSatz?.let(::JsonPrimitive) ?: JsonNull)
        } }))
    }.toString().toByteArray(Charsets.UTF_8)

    private fun decode(blob: ByteArray): Inhalt {
        val clear = schutz.oeffnen(blob)
        try {
            val obj = Json.parseToJsonElement(clear.decodeToString(throwOnInvalidSequence = true)) as? JsonObject ?: error("contact_original_store_schema")
            require(obj.keys == setOf("format", "generation", "peer", "sources") && obj["format"] == JsonPrimitive(1))
            fun text(node: JsonElement?, nullable: Boolean = false): String? {
                if (nullable && node == JsonNull) return null
                val value = (node as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("contact_original_store_text")
                require(gueltigerText(value))
                return value
            }
            val generation = requireNotNull(text(obj["generation"]))
            require(UUID.fromString(generation).toString() == generation)
            val peer = obj["peer"] as? JsonObject ?: error("contact_original_store_peer")
            require(peer.keys == setOf("id", "key"))
            val id = requireNotNull(text(peer["id"])); val key = requireNotNull(text(peer["key"]))
            require(id.isNotBlank() && key.isNotBlank())
            val sources = obj["sources"] as? JsonArray ?: error("contact_original_store_sources")
            require(sources.size in 1..32)
            val parsed = sources.map { node ->
                val source = node as? JsonObject ?: error("contact_original_store_source")
                require(source.keys == setOf("database", "name", "type", "data_set"))
                val database = (source["database"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                require(database != null && database > 0)
                KontaktOriginalFreigaben.Quelle(database, KontaktOriginalBindung.Quelle(text(source["name"], true),
                    text(source["type"], true), text(source["data_set"], true)))
            }
            require(parsed.distinct().size == parsed.size)
            return Inhalt(generation, KontaktOriginalFreigaben.Partner(id, key), parsed.toSet()).also {
                require(encode(it).contentEquals(clear)) { "contact_original_store_canonical_required" }
            }
        } finally { clear.fill(0) }
    }

    companion object {
        private const val MAX_FILE = 257 * 1024
        private val locks = ConcurrentHashMap<String, ReentrantLock>()
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        fun android(context: Context) = KontaktOriginalDauerfreigaben(File(context.filesDir, "kontakt-original-consent"), KontaktOriginalSchutz.android())
    }
}
