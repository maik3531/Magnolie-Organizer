package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.net.Uri
import android.os.CancellationSignal
import android.provider.DocumentsContract
import java.util.ArrayDeque
import java.util.Collections

/** Provider metadata is NOT a frozen sender snapshot, digest or resume identity.
 * Callers must still freeze/read back actual source bytes before creating an offer.
 */
internal data class PhotoInventoryEntry(val documentUri: String, val documentId: String,
    val relativePath: String, val advertisedBytes: Long, val advertisedModifiedMs: Long?)

internal class PhotoFolderInventory internal constructor(val lease: PhotoFolderLease, entries: List<PhotoInventoryEntry>) {
    val entries: List<PhotoInventoryEntry> = Collections.unmodifiableList(entries.toList())
}

/** Bounded read-only enumeration of precisely the native selected tree.
 * No file contents are opened, no provider writes/deletes or permission changes,
 * no MediaStore fallback, and no automatic worker or capability advertisement.
 */
internal class AndroidPhotoFolderInventory(context: Context, private val scope: PhotoFolderScope) {
    private val resolver = context.applicationContext.contentResolver
    private data class Directory(val id: String, val path: String, val depth: Int)

    fun enumerate(lease: PhotoFolderLease, cancellation: CancellationSignal = CancellationSignal()): PhotoFolderInventory {
        fun fresh() {
            cancellation.throwIfCanceled()
            if (!scope.isCurrent(lease)) throw PhotoFolderScopeError("photo_inventory_source_revoked")
        }
        fresh()
        val tree = Uri.parse(lease.preference.treeUri)
        val treeId = DocumentsContract.getTreeDocumentId(tree)
        val rootDocument = DocumentsContract.buildDocumentUriUsingTree(tree, treeId)
        val pending = ArrayDeque<Directory>().apply { add(Directory(treeId, "", 0)) }
        val seen = mutableSetOf(treeId)
        val paths = mutableSetOf<String>()
        val entries = mutableListOf<PhotoInventoryEntry>()
        var directories = 1
        var visited = 0
        var total = 0L
        while (pending.isNotEmpty()) {
            fresh()
            val parent = pending.removeFirst()
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parent.id)
            val cursor = resolver.query(children, PROJECTION, android.os.Bundle(), cancellation)
                ?: throw PhotoFolderScopeError("photo_inventory_provider_unavailable")
            cursor.use {
                val idColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
                val nameColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
                val mimeColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_MIME_TYPE)
                val sizeColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_SIZE)
                val modifiedColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_LAST_MODIFIED)
                val flagsColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_FLAGS)
                while (true) {
                    fresh()
                    if (!it.moveToNext()) break
                    fresh()
                    if (++visited > MAX_VISITED) throw PhotoFolderScopeError("photo_inventory_entry_limit")
                    val id = if (it.isNull(idColumn)) null else it.getString(idColumn)
                    if (id.isNullOrEmpty() || id.length > 4096 || id.any { character -> character.code < 32 || character.code == 127 } || !seen.add(id))
                        throw PhotoFolderScopeError("photo_inventory_ambiguous_document")
                    val document = DocumentsContract.buildDocumentUriUsingTree(tree, id)
                    if (!isChild(rootDocument, document))
                        throw PhotoFolderScopeError("photo_inventory_document_outside_tree")
                    fresh()
                    val mime = if (it.isNull(mimeColumn)) null else it.getString(mimeColumn)
                    val isDirectory = mime == DocumentsContract.Document.MIME_TYPE_DIR
                    // Unselected non-image files are not sources. They still
                    // consume traversal budget and must remain in this tree.
                    if (!isDirectory && (mime == null || !IMAGE_MIME.matches(mime))) continue
                    if (it.isNull(nameColumn) || it.isNull(flagsColumn)) throw PhotoFolderScopeError("photo_inventory_missing_metadata")
                    val name = it.getString(nameColumn)
                    if (name.isNullOrEmpty() || '/' in name) throw PhotoFolderScopeError("photo_inventory_unsafe_name")
                    val relative = if (parent.path.isEmpty()) name else parent.path + "/" + name
                    if (!DeviceFileManifest.portablePath(relative)) throw PhotoFolderScopeError("photo_inventory_unsafe_path")
                    val alias = java.text.Normalizer.normalize(relative.uppercase(java.util.Locale.ROOT)
                        .lowercase(java.util.Locale.ROOT).uppercase(java.util.Locale.ROOT), java.text.Normalizer.Form.NFC)
                    if (!paths.add(alias)) throw PhotoFolderScopeError("photo_inventory_path_alias")
                    if (it.getType(flagsColumn) != android.database.Cursor.FIELD_TYPE_INTEGER || it.getLong(flagsColumn) < 0)
                        throw PhotoFolderScopeError("photo_inventory_invalid_flags")
                    if (it.getLong(flagsColumn) and DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT.toLong() != 0L)
                        throw PhotoFolderScopeError("photo_inventory_virtual_document")
                    if (isDirectory) {
                        if (++directories > MAX_DIRECTORIES || parent.depth + 1 >= MAX_DEPTH)
                            throw PhotoFolderScopeError("photo_inventory_directory_limit")
                        pending.add(Directory(id, relative, parent.depth + 1))
                    } else {
                        if (it.getType(sizeColumn) != android.database.Cursor.FIELD_TYPE_INTEGER) throw PhotoFolderScopeError("photo_inventory_unknown_size")
                        val bytes = it.getLong(sizeColumn)
                        if (bytes !in 0..DeviceFileManifest.MAX_FILE_BYTES || entries.size >= DeviceFileManifest.MAX_FILES)
                            throw PhotoFolderScopeError("photo_inventory_file_limit")
                        total += bytes
                        if (total > DeviceFileManifest.MAX_TOTAL_BYTES) throw PhotoFolderScopeError("photo_inventory_total_limit")
                        if (!it.isNull(modifiedColumn) && it.getType(modifiedColumn) != android.database.Cursor.FIELD_TYPE_INTEGER)
                            throw PhotoFolderScopeError("photo_inventory_invalid_modified_time")
                        val modified = if (it.isNull(modifiedColumn)) null else it.getLong(modifiedColumn)
                        if (modified != null && modified < 0) throw PhotoFolderScopeError("photo_inventory_invalid_modified_time")
                        entries.add(PhotoInventoryEntry(document.toString(), id, relative, bytes, modified))
                    }
                }
            }
            fresh()
        }
        fresh()
        return PhotoFolderInventory(lease, entries)
    }

    private fun isChild(parent: Uri, child: Uri): Boolean {
        if (android.os.Build.VERSION.SDK_INT >= 29) return DocumentsContract.isChildDocument(resolver, parent, child)
        // API26-28: use the same read-only provider call as Android's framework,
        // via public ContentResolver.call (no hidden-API reflection). The public
        // DocumentsContract resolver convenience method was only added in API29.
        // Protocol: AOSP android-8.0.0_r1 DocumentsContract.isChildDocument(client,...).
        val arguments = android.os.Bundle().apply {
            putParcelable("uri", parent)
            putParcelable("android.content.extra.TARGET_URI", child)
        }
        return resolver.call(parent, "android:isChildDocument", null, arguments)?.get("result") == true
    }

    companion object {
        const val MAX_VISITED = 512
        const val MAX_DIRECTORIES = 32
        const val MAX_DEPTH = 16
        private val IMAGE_MIME = Regex("image/[a-z0-9][a-z0-9.+-]{0,126}")
        private val PROJECTION = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_FLAGS)
    }
}
