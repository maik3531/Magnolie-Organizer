package io.gitlab.maik3531.magnolietabletbeta

import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import android.system.StructStat
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileDescriptor
import java.io.IOException
import java.util.UUID

/** Public android.system.Os APIs exist since API21. No SDK branch, NIO desugar fallback,
 * unchecked File.renameTo, or weakened directory durability barrier is used on Android.
 */
object AndroidOsStorageFileOps : StorageFileOps {
    private val directoryFlags = OsConstants.O_RDONLY or OsConstants.O_DIRECTORY or OsConstants.O_NOFOLLOW or OsConstants.O_CLOEXEC
    private fun record(info: StructStat) = StorageFileStat(info.st_uid.toLong(), info.st_mode, info.st_size,
        info.st_nlink, info.st_dev, info.st_ino)
    override fun stat(file: File): StorageFileStat? = try { record(Os.lstat(file.path)) }
        catch (error: ErrnoException) { if (error.errno == OsConstants.ENOENT) null else throw IOException("Cannot inspect storage entry", error) }
    private fun validate(info: StorageFileStat, directory: Boolean, privateMode: Boolean = true) {
        if (info.owner != Os.getuid().toLong() || (if (directory) !info.isDirectory else !info.isRegular) ||
            (!directory && info.links != 1L) || (privateMode && info.mode and 0x3f != 0)) throw IOException("Unsafe storage entry")
    }
    private fun checkDirectory(file: File): StorageFileStat {
        val info = stat(file) ?: throw IOException("Storage directory missing")
        validate(info, true); return info
    }
    private fun checkRegular(file: File): StorageFileStat {
        val info = stat(file) ?: throw IOException("Storage file missing")
        validate(info, false); return info
    }
    private fun close(fd: FileDescriptor) { Os.close(fd) }
    override fun children(directory: File): List<File> {
        checkDirectory(directory)
        return directory.listFiles()?.toList() ?: throw IOException("Cannot list storage directory")
    }
    override fun ensurePrivateDirectory(directory: File, create: Boolean): File {
        var created = false
        if (stat(directory) == null && create) { Os.mkdir(directory.path, 0x1c0); created = true } // 0700
        val before = stat(directory) ?: throw IOException("Storage directory missing")
        validate(before, true, privateMode = false)
        val fd = Os.open(directory.path, directoryFlags, 0)
        try {
            val opened = record(Os.fstat(fd)); validate(opened, true, privateMode = false)
            if (!before.sameFile(opened)) throw IOException("Storage directory changed while opening")
            Os.fchmod(fd, 0x1c0)
            validate(record(Os.fstat(fd)), true)
        } finally { close(fd) }
        if (!before.sameFile(checkDirectory(directory))) throw IOException("Storage directory changed while hardening")
        val result = directory.canonicalFile
        checkDirectory(result)
        if (created) syncOwnedDirectory(result.parentFile!!, privateMode = false)
        return result
    }
    override fun read(file: File, maximumBytes: Int): ByteArray? {
        require(maximumBytes > 0 && maximumBytes < Int.MAX_VALUE)
        if (stat(file) == null) return null
        val before = checkRegular(file)
        val fd = Os.open(file.path, OsConstants.O_RDONLY or OsConstants.O_NOFOLLOW or OsConstants.O_CLOEXEC, 0)
        try {
            val opened = record(Os.fstat(fd)); validate(opened, false)
            if (!before.sameFile(opened) || opened.size !in 1..maximumBytes.toLong()) throw IOException("Storage file changed or exceeds bounded size")
            val output = ByteArrayOutputStream(minOf(maximumBytes, 65_536))
            val buffer = ByteArray(minOf(maximumBytes + 1, 65_536))
            while (true) {
                val count = try { Os.read(fd, buffer, 0, minOf(buffer.size, maximumBytes + 1 - output.size())) }
                            catch (error: ErrnoException) { if (error.errno == OsConstants.EINTR) continue else throw error }
                if (count == 0) break
                if (count < 0 || count > maximumBytes - output.size()) throw IOException("Storage file exceeds bounded size")
                output.write(buffer, 0, count)
            }
            val after = record(Os.fstat(fd)); validate(after, false)
            val current = checkRegular(file)
            if (!opened.sameFile(current) || after.size != opened.size || current.size != opened.size || output.size().toLong() != opened.size) throw IOException("Storage file changed while reading")
            return output.toByteArray()
        } finally { close(fd) }
    }
    override fun writeAndSync(file: File, bytes: ByteArray, maximumBytes: Int, exclusive: Boolean) {
        require(maximumBytes > 0 && bytes.size <= maximumBytes)
        checkDirectory(file.parentFile!!)
        val previous = stat(file)?.also { validate(it, false) }
        val flags = OsConstants.O_WRONLY or OsConstants.O_CREAT or OsConstants.O_NOFOLLOW or OsConstants.O_CLOEXEC or
            (if (exclusive) OsConstants.O_EXCL else 0)
        // No O_TRUNC before fstat: a substituted file must never be truncated before validation.
        val fd = Os.open(file.path, flags, 0x180) // 0600
        try {
            val opened = record(Os.fstat(fd)); validate(opened, false)
            if (previous != null && !previous.sameFile(opened)) throw IOException("Storage destination changed while opening")
            Os.fchmod(fd, 0x180)
            Os.ftruncate(fd, 0)
            var offset = 0
            while (offset < bytes.size) {
                val count = try { Os.write(fd, bytes, offset, minOf(65_536, bytes.size - offset)) }
                            catch (error: ErrnoException) { if (error.errno == OsConstants.EINTR) continue else throw error }
                if (count <= 0) throw IOException("Storage write made no progress")
                offset += count
            }
            Os.fsync(fd)
            val after = record(Os.fstat(fd)); validate(after, false)
            val current = checkRegular(file)
            if (!opened.sameFile(current) || after.size != bytes.size.toLong() || current.size != bytes.size.toLong()) throw IOException("Storage destination changed while writing")
        } finally { close(fd) }
    }
    override fun temporary(directory: File, prefix: String): File {
        checkDirectory(directory)
        require(prefix.isNotEmpty() && !prefix.contains('/') && !prefix.contains('\\'))
        return File(directory, prefix + UUID.randomUUID() + ".tmp").also { writeAndSync(it, byteArrayOf(), 1, true) }
    }
    override fun atomicReplace(source: File, destination: File) {
        checkDirectory(source.parentFile!!); checkDirectory(destination.parentFile!!)
        if (source.parentFile!!.canonicalFile != destination.parentFile!!.canonicalFile) throw IOException("Atomic storage move must stay in one directory")
        val original = checkRegular(source)
        if (stat(destination) != null) checkRegular(destination)
        Os.rename(source.path, destination.path) // Throws on failure; never ignore renameTo's boolean.
        val moved = checkRegular(destination)
        if (!original.sameFile(moved) || stat(source) != null) throw IOException("Atomic storage replacement could not be verified")
    }
    override fun delete(file: File): Boolean {
        if (stat(file) == null) return false
        checkDirectory(file.parentFile!!); checkRegular(file)
        Os.unlink(file.path)
        if (stat(file) != null) throw IOException("Storage deletion could not be verified")
        return true
    }
    override fun syncDirectory(directory: File) = syncOwnedDirectory(directory, privateMode = true)
    private fun syncOwnedDirectory(directory: File, privateMode: Boolean) {
        val before = stat(directory) ?: throw IOException("Storage directory missing")
        validate(before, true, privateMode)
        val fd = Os.open(directory.path, directoryFlags, 0)
        try {
            val opened = record(Os.fstat(fd)); validate(opened, true, privateMode)
            if (!before.sameFile(opened)) throw IOException("Storage directory changed while opening")
            Os.fsync(fd)
            val after = record(Os.fstat(fd)); validate(after, true, privateMode)
            val current = stat(directory) ?: throw IOException("Storage directory disappeared while syncing")
            validate(current, true, privateMode)
            if (!opened.sameFile(current)) throw IOException("Storage directory changed while syncing")
        } finally { close(fd) }
    }
}
