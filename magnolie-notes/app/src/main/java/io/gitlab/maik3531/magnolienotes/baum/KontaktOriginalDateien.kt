package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import java.io.File
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardCopyOption.*
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** Shared private IO procedure for consent and outcome state, never permission.
 * No native peer/provider callbacks may run while this file lock is held.
 * Construction and missing-root reads create nothing. The caller supplies only
 * native private roots, never a path from an imported document or wire request.
 */
internal class KontaktOriginalDateien(private val root: File, private val maxBytes: Int = 257 * 1024,
                                     private val stage: (String) -> Unit = {}) {
    private val active = ThreadLocal.withInitial { false }
    init { require(maxBytes in 1..1024 * 1024) }

    fun <T> mitSperre(create: Boolean, block: () -> T): T? {
        check(!active.get()) { "contact_original_private_lock_reentry" }
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
                    active.set(true)
                    try { block() } finally { active.set(false) }
                }
            }
        }
    }

    fun lesen(name: String): ByteArray? {
        val path = path(name)
        if (!Files.exists(path, NOFOLLOW_LINKS)) return null
        val before = Files.readAttributes(path, BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        require(before.isRegularFile && before.fileKey() != null && before.size() in 1..maxBytes.toLong()) { "contact_original_private_file_required" }
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

    fun schreiben(name: String, bytes: ByteArray) {
        val target = path(name)
        require(bytes.size in 1..maxBytes)
        if (Files.exists(target, NOFOLLOW_LINKS)) lesen(name)
        val temp = Files.createTempFile(root.toPath(), "contact-", ".pending",
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

    private fun path(name: String): java.nio.file.Path {
        check(active.get()) { "contact_original_private_lock_required" }
        require(name.matches(Regex("[a-z0-9][a-z0-9.-]{0,100}")) && name != "guard.lock" && !name.endsWith(".pending"))
        return root.toPath().resolve(name)
    }

    private fun privatePermissions(path: java.nio.file.Path) {
        require(Files.getPosixFilePermissions(path, NOFOLLOW_LINKS).intersect(
            PosixFilePermissions.fromString("---rwxrwx")).isEmpty()) { "contact_original_private_permissions_required" }
    }

    companion object { private val locks = ConcurrentHashMap<String, ReentrantLock>() }
}
