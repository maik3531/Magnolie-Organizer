package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.attribute.PosixFileAttributes

/** Fresh per-call, no-follow attribute samples, never a remembered FS grant.
 * File type/identity/owner/mode are obtained from the same POSIX stat instead of
 * separate repeated basic/owner/permissions stats. Link count stays explicit.
 */
internal object NativeSourceFiles {
    fun directory(directory: File, rootKey: Any, closed: Boolean) {
        if (closed) fail("photo_jobs_directory_changed")
        val actual = Files.readAttributes(directory.toPath(), PosixFileAttributes::class.java, NOFOLLOW_LINKS)
        if (!actual.isDirectory || actual.fileKey() != rootKey || directory.canonicalFile != directory)
            fail("photo_jobs_directory_changed")
        if (actual.permissions().any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            fail("photo_jobs_private_directory_required")
    }

    fun regular(file: File, root: java.nio.file.Path) {
        val actual = Files.readAttributes(file.toPath(), PosixFileAttributes::class.java, NOFOLLOW_LINKS)
        if (!actual.isRegularFile || actual.owner() != Files.getOwner(root, NOFOLLOW_LINKS) ||
            actual.permissions().any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            fail("photo_jobs_unsafe_entry")
    }

    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
