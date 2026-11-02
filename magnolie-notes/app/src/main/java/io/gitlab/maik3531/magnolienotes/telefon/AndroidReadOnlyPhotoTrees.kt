package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import java.security.MessageDigest
import java.util.Locale

/** Only an explicit OpenDocumentTree result may be passed by the native UI owner. */
internal class AndroidReadOnlyPhotoTrees(context: Context) : ReadOnlyPhotoTrees {
    private val resolver = context.applicationContext.contentResolver

    override fun canonicalTree(uri: String): String {
        if (uri.length !in 1..4096 || uri.any { it.code < 32 || it.code == 127 })
            throw PhotoFolderScopeError("invalid_photo_tree")
        val value = Uri.parse(uri)
        if (value.scheme != "content" || value.query != null || value.fragment != null ||
            value.authority?.matches(Regex("[A-Za-z0-9._-]{1,255}")) != true || !DocumentsContract.isTreeUri(value))
            throw PhotoFolderScopeError("invalid_photo_tree")
        val id = DocumentsContract.getTreeDocumentId(value)
        if (id.isEmpty()) throw PhotoFolderScopeError("invalid_photo_tree")
        val canonical = DocumentsContract.buildTreeDocumentUri(value.authority, id)
        if (canonical != value) throw PhotoFolderScopeError("noncanonical_photo_tree")
        return canonical.toString()
    }

    override fun persistRead(uri: String) {
        val canonical = Uri.parse(canonicalTree(uri))
        resolver.takePersistableUriPermission(canonical, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (!hasPersistedRead(uri)) throw PhotoFolderScopeError("photo_tree_read_permission_missing")
    }

    override fun readGrantToken(uri: String): String? = runCatching {
        val canonical = Uri.parse(canonicalTree(uri))
        val permission = resolver.persistedUriPermissions.singleOrNull { it.uri == canonical && it.isReadPermission }
            ?: return null
        if (permission.persistedTime < 0) return null
        MessageDigest.getInstance("SHA-256").digest((canonical.toString() + "\u0000" + permission.persistedTime.toString())
            .toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    }.getOrNull()
}
