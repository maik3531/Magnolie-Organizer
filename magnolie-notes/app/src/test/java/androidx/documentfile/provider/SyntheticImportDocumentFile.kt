package androidx.documentfile.provider

import android.net.Uri

/** Test node lives beside DocumentFile because its constructor is package-private. */
class SyntheticImportDocumentFile(private val label: String, val bytes: ByteArray = byteArrayOf(),
                                  private val children: Array<SyntheticImportDocumentFile>? = null) : DocumentFile(null) {
    override fun getName() = label
    override fun isDirectory() = children != null
    override fun isFile() = children == null
    override fun listFiles(): Array<DocumentFile> = children?.map { it as DocumentFile }?.toTypedArray() ?: emptyArray()
    override fun length() = bytes.size.toLong()
    override fun lastModified() = 0L
    override fun canRead() = true
    override fun canWrite() = false
    override fun exists() = true
    override fun isVirtual() = false
    override fun getType(): String? = null
    override fun getUri(): Uri = throw AssertionError("Traversal must not access an unrequested URI")
    override fun createFile(mimeType: String, displayName: String): DocumentFile? = null
    override fun createDirectory(displayName: String): DocumentFile? = null
    override fun delete() = false
    override fun renameTo(displayName: String) = false
}
