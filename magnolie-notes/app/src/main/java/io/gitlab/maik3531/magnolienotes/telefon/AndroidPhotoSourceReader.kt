package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import java.io.FilterInputStream
import java.io.InputStream

internal interface PhotoSourceAccess {
    fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal)
    fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): InputStream
}

/** Actual READ-only cancellable PFD boundary. Never opens a gallery/default source. */
internal class AndroidPhotoSourceReader(context: Context, private val scope: PhotoFolderScope) : PhotoSourceAccess {
    private val resolver = context.applicationContext.contentResolver
    private fun fresh(lease: NativePhotoSourceLease, cancellation: CancellationSignal) {
        cancellation.throwIfCanceled()
        if (!scope.isCurrent(lease)) throw PhotoFolderScopeError("photo_snapshot_source_revoked")
    }
    private fun document(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): Uri {
        fresh(lease, cancellation)
        if (lease !is PhotoFolderLease) throw PhotoFolderScopeError("photo_snapshot_wrong_source_kind")
        val tree = Uri.parse(lease.preference.treeUri)
        val document = DocumentsContract.buildDocumentUriUsingTree(tree, entry.documentId)
        if (document.toString() != entry.documentUri || !DeviceFileManifest.portablePath(entry.relativePath) ||
            !isPhotoTreeChild(resolver, DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree)), document))
            throw PhotoFolderScopeError("photo_snapshot_document_outside_tree")
        fresh(lease, cancellation)
        return document
    }
    override fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) {
        val document = document(lease, entry, cancellation)
        resolver.query(document, PROJECTION, android.os.Bundle(), cancellation)?.use { cursor ->
            fresh(lease, cancellation)
            if (!cursor.moveToFirst()) throw PhotoFolderScopeError("photo_snapshot_document_missing")
            fun text(column: String): String? = cursor.getColumnIndexOrThrow(column).let {
                if (cursor.getType(it) == Cursor.FIELD_TYPE_STRING) cursor.getString(it) else null
            }
            fun integer(column: String): Long? = cursor.getColumnIndexOrThrow(column).let {
                if (cursor.getType(it) == Cursor.FIELD_TYPE_INTEGER) cursor.getLong(it) else null
            }
            val mime = text(DocumentsContract.Document.COLUMN_MIME_TYPE)
            val flags = integer(DocumentsContract.Document.COLUMN_FLAGS)
            val size = integer(DocumentsContract.Document.COLUMN_SIZE)
            val modifiedIndex = cursor.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_LAST_MODIFIED)
            if (text(DocumentsContract.Document.COLUMN_DOCUMENT_ID) != entry.documentId ||
                text(DocumentsContract.Document.COLUMN_DISPLAY_NAME) != entry.relativePath.substringAfterLast('/') ||
                mime == null || !Regex("image/[a-z0-9][a-z0-9.+-]{0,126}").matches(mime) ||
                flags == null || flags < 0 || flags and DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT.toLong() != 0L ||
                size == null || size != entry.advertisedBytes || size !in 0..DeviceFileManifest.MAX_FILE_BYTES ||
                (cursor.getType(modifiedIndex) !in setOf(Cursor.FIELD_TYPE_NULL, Cursor.FIELD_TYPE_INTEGER)) ||
                integer(DocumentsContract.Document.COLUMN_LAST_MODIFIED) != entry.advertisedModifiedMs || cursor.moveToNext())
                throw PhotoFolderScopeError("photo_snapshot_metadata_changed")
            fresh(lease, cancellation)
        } ?: throw PhotoFolderScopeError("photo_snapshot_document_missing")
        fresh(lease, cancellation)
    }
    override fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): InputStream {
        val uri = document(lease, entry, cancellation)
        val descriptor = resolver.openFileDescriptor(uri, "r", cancellation)
            ?: throw PhotoFolderScopeError("photo_snapshot_document_missing")
        try { fresh(lease, cancellation) } catch (error: Exception) { descriptor.close(); throw error }
        return object : FilterInputStream(ParcelFileDescriptor.AutoCloseInputStream(descriptor)) {
            override fun read(): Int {
                fresh(lease, cancellation)
                return `in`.read().also { fresh(lease, cancellation) }
            }
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                fresh(lease, cancellation)
                return `in`.read(buffer, offset, length).also { fresh(lease, cancellation) }
            }
        }
    }
    companion object {
        private val PROJECTION = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_FLAGS)
    }
}
