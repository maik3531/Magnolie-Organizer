package io.gitlab.maik3531.magnolietabletbeta

import java.io.File

/** No java.nio.file types in the product storage boundary: Android's public Os backend is used
 * explicitly on every supported Android API, while JVM tests retain the real NIO reference path.
 */
interface StorageFileOps {
    fun stat(file: File): StorageFileStat?
    fun children(directory: File): List<File>
    fun ensurePrivateDirectory(directory: File, create: Boolean = false): File
    fun read(file: File, maximumBytes: Int): ByteArray?
    fun writeAndSync(file: File, bytes: ByteArray, maximumBytes: Int, exclusive: Boolean = false)
    fun temporary(directory: File, prefix: String): File
    fun atomicReplace(source: File, destination: File)
    fun delete(file: File): Boolean
    fun syncDirectory(directory: File)
}

data class StorageFileStat(val owner: Long, val mode: Int, val size: Long, val links: Long,
                           val device: Long, val inode: Long) {
    val isRegular: Boolean get() = mode and 0xf000 == 0x8000
    val isDirectory: Boolean get() = mode and 0xf000 == 0x4000
    val isSymlink: Boolean get() = mode and 0xf000 == 0xa000
    fun sameFile(other: StorageFileStat): Boolean = device == other.device && inode == other.inode
}
