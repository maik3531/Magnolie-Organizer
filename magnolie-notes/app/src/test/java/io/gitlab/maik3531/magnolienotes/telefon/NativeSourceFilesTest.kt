package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class NativeSourceFilesTest {
    private fun outcome(action: () -> Unit): String = try { action(); "ok" }
        catch (error: PhotoFolderScopeError) { error.code }

    private fun oldRegular(file: File, root: java.nio.file.Path) {
        if (!Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS).isRegularFile ||
            Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root, NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            throw PhotoFolderScopeError("photo_jobs_unsafe_entry")
    }

    private fun oldDirectory(directory: File, rootKey: Any, closed: Boolean) {
        if (closed || !Files.readAttributes(directory.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS).isDirectory ||
            Files.readAttributes(directory.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS).fileKey() != rootKey || directory.canonicalFile != directory)
            throw PhotoFolderScopeError("photo_jobs_directory_changed")
        if (Files.getPosixFilePermissions(directory.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            throw PhotoFolderScopeError("photo_jobs_private_directory_required")
    }

    @Test fun freshCombinedFileAttributesKeepOriginalTypeOwnerModeAndSingleLinkDecisions() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "source-stat398-")
        try {
            val file = root.resolve("original").toFile().apply { writeText("original bytes") }
            fun equivalent(expected: String, target: File = file) {
                assertEquals(expected, outcome { oldRegular(target, root) })
                assertEquals(expected, outcome { NativeSourceFiles.regular(target, root) })
            }
            Files.setPosixFilePermissions(file.toPath(), PosixFilePermissions.fromString("rw-------")); equivalent("ok")
            Files.setPosixFilePermissions(file.toPath(), PosixFilePermissions.fromString("r--------")); equivalent("ok")
            for (mode in listOf("rw-r-----", "rw----r--", "rw-----w-", "rw------x")) {
                Files.setPosixFilePermissions(file.toPath(), PosixFilePermissions.fromString(mode)); equivalent("photo_jobs_unsafe_entry")
            }
            Files.setPosixFilePermissions(file.toPath(), PosixFilePermissions.fromString("rw-------"))
            val link = Files.createSymbolicLink(root.resolve("symbolic"), file.toPath()).toFile(); equivalent("photo_jobs_unsafe_entry", link)
            equivalent("photo_jobs_unsafe_entry", Files.createDirectory(root.resolve("directory")).toFile())
            val hard = Files.createLink(root.resolve("hard"), file.toPath()).toFile()
            equivalent("photo_jobs_unsafe_entry", hard); equivalent("photo_jobs_unsafe_entry")
            assertEquals("original bytes", file.readText())
        } finally { root.toFile().deleteRecursively() }
    }

    @Test fun directorySamplesRemainFreshAndRejectClosedReplacedLinkedAndNonprivateRoots() {
        val base = Files.createTempDirectory(File("/tmp/opencode").toPath(), "source-dir398-")
        try {
            val root = Files.createDirectory(base.resolve("root")).toFile();Files.setPosixFilePermissions(root.toPath(), PosixFilePermissions.fromString("rwx------"))
            val key = Files.readAttributes(root.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS).fileKey()!!
            fun equivalent(expected: String, target: File = root, closed: Boolean = false) {
                assertEquals(expected, outcome { oldDirectory(target, key, closed) })
                assertEquals(expected, outcome { NativeSourceFiles.directory(target, key, closed) })
            }
            equivalent("ok"); equivalent("photo_jobs_directory_changed", closed = true)
            val link = Files.createSymbolicLink(base.resolve("linked"), root.toPath()).toFile(); equivalent("photo_jobs_directory_changed", link)
            Files.setPosixFilePermissions(root.toPath(), PosixFilePermissions.fromString("rwxr-----")); equivalent("photo_jobs_private_directory_required")
            Files.setPosixFilePermissions(root.toPath(), PosixFilePermissions.fromString("rwx------")); equivalent("ok")
            assertTrue(root.renameTo(base.resolve("original-held").toFile()))
            assertTrue(root.mkdir());Files.setPosixFilePermissions(root.toPath(), PosixFilePermissions.fromString("rwx------"))
            equivalent("photo_jobs_directory_changed")
        } finally { base.toFile().deleteRecursively() }
    }

    @Test fun sharedImmutablePatternsMatchOriginalRevisionAndSchemaBytesForAllByteValues() {
        fun pattern(name: String): Regex = PhotoSourceMembership::class.java.getDeclaredField(name).also { it.isAccessible = true }.get(null) as Regex
        val revision = pattern("POSITIVE_REVISION"); val whitespace = pattern("SCHEMA_WHITESPACE")
        val values = (0..1000).map(Int::toString) + listOf("", "01", "-1", "+1", "1.0", "1e3", "1\n", "true", "١", Long.MAX_VALUE.toString())
        for (value in values) assertEquals(value, Regex("[1-9][0-9]*").matches(value), revision.matches(value))
        for (code in 0..255) {
            val sql = "CREATE${code.toChar()}TABLE source_meta (name TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)"
            assertArrayEquals(Regex("\\s+").replace(sql, "").toByteArray(Charsets.UTF_8), whitespace.replace(sql, "").toByteArray(Charsets.UTF_8))
        }
    }
}
