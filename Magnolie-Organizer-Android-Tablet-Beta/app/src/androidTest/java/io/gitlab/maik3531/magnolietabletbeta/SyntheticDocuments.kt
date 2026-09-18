package io.gitlab.maik3531.magnolietabletbeta

import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract.Document
import android.provider.DocumentsContract.Root
import android.provider.DocumentsProvider
import java.io.File

/** Installed only in the test APK. No user files, accounts, or production provider. */
class SyntheticDocuments : DocumentsProvider() {
    private val directory get() = File(requireNotNull(context).filesDir,"synthetic-documents").apply { mkdirs() }
    private fun file(id: String): File {
        require(id.matches(Regex("[A-Za-z0-9._ -]{1,160}")) && id != "." && id != "..")
        return File(directory,id)
    }
    override fun onCreate() = true
    override fun queryRoots(projection: Array<out String>?): Cursor {
        val columns=projection ?: arrayOf(Root.COLUMN_ROOT_ID,Root.COLUMN_DOCUMENT_ID,Root.COLUMN_TITLE,
            Root.COLUMN_FLAGS,Root.COLUMN_MIME_TYPES,Root.COLUMN_AVAILABLE_BYTES)
        return MatrixCursor(columns).apply {
            val row=newRow()
            for(column in columns) row.add(column,when(column) {
                Root.COLUMN_ROOT_ID,Root.COLUMN_DOCUMENT_ID -> "root"
                Root.COLUMN_TITLE -> "Tablet Beta Test Documents"
                Root.COLUMN_FLAGS -> Root.FLAG_SUPPORTS_CREATE or Root.FLAG_LOCAL_ONLY
                Root.COLUMN_MIME_TYPES -> "application/json\napplication/pdf"
                Root.COLUMN_AVAILABLE_BYTES -> 100000000L
                else -> null
            })
        }
    }
    private fun cursor(ids: List<String>, projection: Array<out String>?): Cursor {
        val columns=projection ?: arrayOf(Document.COLUMN_DOCUMENT_ID,Document.COLUMN_DISPLAY_NAME,
            Document.COLUMN_MIME_TYPE,Document.COLUMN_FLAGS,Document.COLUMN_SIZE,Document.COLUMN_LAST_MODIFIED)
        return MatrixCursor(columns).apply {for(id in ids) {
            val f=if(id=="root") directory else file(id)
            val row=newRow()
            for(column in columns) row.add(column,when(column) {
                Document.COLUMN_DOCUMENT_ID -> id
                Document.COLUMN_DISPLAY_NAME -> if(id=="root") "Tablet Beta Test Documents" else id
                Document.COLUMN_MIME_TYPE -> if(id=="root") Document.MIME_TYPE_DIR else if(id.endsWith(".pdf")) "application/pdf" else "application/json"
                Document.COLUMN_FLAGS -> if(id=="root") Document.FLAG_DIR_SUPPORTS_CREATE else Document.FLAG_SUPPORTS_WRITE or Document.FLAG_SUPPORTS_DELETE
                Document.COLUMN_SIZE -> f.length()
                Document.COLUMN_LAST_MODIFIED -> f.lastModified()
                else -> null
            })
        }}
    }
    override fun queryDocument(documentId: String, projection: Array<out String>?) = cursor(listOf(documentId),projection)
    override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor {
        require(parentDocumentId=="root")
        return cursor(directory.listFiles().orEmpty().filter { it.isFile }.map { it.name }.sorted(),projection)
    }
    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor =
        ParcelFileDescriptor.open(file(documentId),ParcelFileDescriptor.parseMode(mode))
    override fun createDocument(parentDocumentId: String, mimeType: String, displayName: String): String {
        require(parentDocumentId=="root")
        val f=file(displayName); check(f.createNewFile()); return f.name
    }
    override fun deleteDocument(documentId: String) {check(file(documentId).delete())}
    override fun isChildDocument(parentDocumentId: String, documentId: String) = parentDocumentId=="root" && file(documentId).isFile
}
