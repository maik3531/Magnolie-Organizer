package io.gitlab.maik3531.magnolietabletbeta

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.PosixFilePermission
import java.nio.file.attribute.PosixFilePermissions
import java.util.UUID

/** Real Unix/JVM reference implementation. Android factories never select this backend. */
object NioStorageFileOps : StorageFileOps {
    private val owner: Long by lazy {
        val probe = Files.createTempFile("magnolie-storage-owner-", ".tmp")
        try { (Files.getAttribute(probe, "unix:uid", LinkOption.NOFOLLOW_LINKS) as Number).toLong() }
        finally { Files.delete(probe) }
    }
    private val directoryMode = setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE)
    private val fileMode = setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)
    override fun stat(file: File): StorageFileStat? {
        val attrs = try { Files.readAttributes(file.toPath(), "unix:uid,mode,size,nlink,dev,ino", LinkOption.NOFOLLOW_LINKS) }
                    catch (_: NoSuchFileException) { return null }
        fun number(name: String) = (attrs.getValue(name) as Number).toLong()
        return StorageFileStat(number("uid"), number("mode").toInt(), number("size"), number("nlink"), number("dev"), number("ino"))
    }
    private fun directory(directory: File): StorageFileStat {
        val info = stat(directory) ?: throw IOException("Storage directory missing")
        if (!info.isDirectory || info.owner != owner || info.mode and 0x3f != 0) throw IOException("Storage directory is not private")
        return info
    }
    private fun regular(file: File): StorageFileStat {
        val info = stat(file) ?: throw IOException("Storage file missing")
        if (!info.isRegular || info.owner != owner || info.links != 1L || info.mode and 0x3f != 0) throw IOException("Unsafe storage file")
        return info
    }
    override fun children(directory: File): List<File> {
        directory(directory)
        return directory.listFiles()?.toList() ?: throw IOException("Cannot list storage directory")
    }
    override fun ensurePrivateDirectory(directory: File, create: Boolean): File {
        var created = false
        if (stat(directory) == null && create) {
            Files.createDirectory(directory.toPath(), PosixFilePermissions.asFileAttribute(directoryMode)); created = true
        }
        val info = stat(directory) ?: throw IOException("Storage directory missing")
        if (!info.isDirectory || info.owner != owner) throw IOException("Unsafe storage directory")
        Files.setPosixFilePermissions(directory.toPath(), directoryMode)
        val result = directory.canonicalFile
        if (!info.sameFile(directory(result))) throw IOException("Storage directory changed while hardening")
        if (created) syncOwnedDirectory(result.parentFile!!, privateMode = false)
        return result
    }
    override fun read(file: File, maximumBytes: Int): ByteArray? {
        require(maximumBytes > 0 && maximumBytes < Int.MAX_VALUE)
        if (stat(file) == null) return null
        val before = regular(file)
        if (before.size !in 1..maximumBytes.toLong()) throw IOException("Storage file exceeds bounded size")
        FileChannel.open(file.toPath(), StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { channel ->
            val opened = regular(file)
            if (!before.sameFile(opened) || channel.size() != before.size) throw IOException("Storage file changed while opening")
            val output = ByteArrayOutputStream(minOf(maximumBytes, 65_536))
            val buffer = ByteBuffer.allocate(minOf(maximumBytes + 1, 65_536))
            while (true) {
                buffer.clear()
                buffer.limit(minOf(buffer.capacity(), maximumBytes + 1 - output.size()))
                val count = channel.read(buffer)
                if (count < 0) break
                if (count == 0) continue
                if (count > maximumBytes - output.size()) throw IOException("Storage file exceeds bounded size")
                output.write(buffer.array(), 0, count)
            }
            val after = regular(file)
            if (!before.sameFile(after) || after.size != before.size || channel.size() != before.size || output.size().toLong() != before.size) throw IOException("Storage file changed while reading")
            return output.toByteArray()
        }
    }
    override fun writeAndSync(file: File, bytes: ByteArray, maximumBytes: Int, exclusive: Boolean) {
        require(maximumBytes > 0 && bytes.size <= maximumBytes)
        directory(file.parentFile!!)
        val previous = stat(file)?.also { regular(file) }
        val options = if (exclusive) setOf(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)
                      else setOf(StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)
        FileChannel.open(file.toPath(), options, PosixFilePermissions.asFileAttribute(fileMode)).use { channel ->
            val actual = regular(file)
            if (previous != null && !previous.sameFile(actual)) throw IOException("Storage destination changed while opening")
            Files.setPosixFilePermissions(file.toPath(), fileMode)
            channel.truncate(0)
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) channel.write(buffer)
            channel.force(true)
        }
    }
    override fun temporary(directory: File, prefix: String): File {
        directory(directory)
        require(prefix.isNotEmpty() && !prefix.contains('/') && !prefix.contains('\\'))
        return File(directory, prefix + UUID.randomUUID() + ".tmp").also { writeAndSync(it, byteArrayOf(), 1, true) }
    }
    override fun atomicReplace(source: File, destination: File) {
        directory(source.parentFile!!); directory(destination.parentFile!!)
        if (source.parentFile!!.canonicalFile != destination.parentFile!!.canonicalFile) throw IOException("Atomic storage move must stay in one directory")
        regular(source)
        if (stat(destination) != null) regular(destination)
        Files.move(source.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
    }
    override fun delete(file: File): Boolean {
        if (stat(file) == null) return false
        regular(file); Files.delete(file.toPath()); return true
    }
    override fun syncDirectory(directory: File) = syncOwnedDirectory(directory, privateMode = true)
    private fun syncOwnedDirectory(directory: File, privateMode: Boolean) {
        val before = stat(directory) ?: throw IOException("Storage directory missing")
        if (!before.isDirectory || before.owner != owner || (privateMode && before.mode and 0x3f != 0)) throw IOException("Unsafe storage directory")
        FileChannel.open(directory.toPath(), StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { channel ->
            val current = stat(directory) ?: throw IOException("Storage directory disappeared while syncing")
            if (!before.sameFile(current) || current.owner != owner || !current.isDirectory || (privateMode && current.mode and 0x3f != 0)) throw IOException("Storage directory changed while opening")
            channel.force(true)
        }
    }
}
