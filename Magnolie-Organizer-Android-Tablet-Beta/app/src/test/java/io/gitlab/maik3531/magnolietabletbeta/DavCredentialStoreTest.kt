package io.gitlab.maik3531.magnolietabletbeta

import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class DavCredentialStoreTest {
    private fun identity(server: String = "https://cloud.example/nextcloud", username: String = "person", type: DavAccountType = DavAccountType.NEXTCLOUD) = DavCredentialIdentity(server, username, type)
    private fun key() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private fun expect(code: String? = null, action: () -> Unit) {
        try { action(); fail("Expected credential error") }
        catch (error: DavCredentialException) { if (code != null) assertEquals(code, error.code) }
    }
    private fun directory(test: (File) -> Unit) {
        val directory = Files.createTempDirectory("dav-private-credential-test").toFile()
        try { test(directory) } finally { directory.deleteRecursively() }
    }
    @Test fun canonicalIdentityMatchesMacAndIsolatesProviderServerAndUser() {
        val identity = identity()
        assertEquals("1cb2ad28b900dac0410f024c8b15c71a219ebacd31c9a89320fa4023d28f3ef4", identity.storageKey)
        assertEquals(identity.storageKey, identity("https://CLOUD.example:443/nextcloud/", " person ").storageKey)
        assertNotEquals(identity.storageKey, identity("https://other.example/nextcloud").storageKey)
        assertNotEquals(identity.storageKey, identity(username = "other").storageKey)
        assertNotEquals(identity.storageKey, identity(type = DavAccountType.GENERIC_DAV).storageKey)
    }
    @Test fun encryptedRoundtripFreshNonceUpdatesIsolationAndDeletion() = directory { dir ->
        val key = key(); val store = DavCredentialStore(dir, { key })
        val first = identity(); val second = identity(username = "other")
        assertNull(store.read(first))
        store.write(first, "fixture-app-password-ä")
        val file = dir.resolve(first.storageKey + ".enc")
        val initial = file.readBytes()
        assertFalse(String(initial).contains("fixture-app-password"))
        assertEquals("fixture-app-password-ä", store.read(first))
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(file.toPath())))
        assertEquals("rwx------", PosixFilePermissions.toString(Files.getPosixFilePermissions(dir.toPath())))
        store.write(first, "fixture-app-password-ä")
        assertFalse(initial.contentEquals(file.readBytes()))
        store.write(second, "other-secret")
        store.write(first, "replacement-secret")
        assertEquals("replacement-secret", store.read(first)); assertEquals("other-secret", store.read(second))
        assertEquals("replacement-secret", DavCredentialStore(dir, { key }).read(first))
        assertTrue(store.delete(first)); assertFalse(store.delete(first))
        assertEquals("other-secret", store.read(second))
    }
    @Test fun corruptionWrongKeyAndSwappedAccountFilesCannotBecomeEmptyAccounts() = directory { dir ->
        val key = key(); val store = DavCredentialStore(dir, { key })
        val first = identity(); val other = identity(username = "other")
        store.write(first, "fixture-secret")
        val file = dir.resolve(first.storageKey + ".enc")
        expect("credential_unavailable") { DavCredentialStore(dir, { key() }).read(first) }
        dir.resolve(other.storageKey + ".enc").writeBytes(file.readBytes())
        expect("credential_unavailable") { store.read(other) }
        file.writeBytes(file.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
        expect("credential_unavailable") { store.read(first) }
    }
    @Test fun invalidSecretsAndSymlinksAreRejectedBeforeOverwriting() = directory { dir ->
        val key = key(); val store = DavCredentialStore(dir, { key }); val account = identity()
        expect("invalid_secret") { store.write(account, "") }
        expect("invalid_secret") { store.write(account, "x".repeat(DavCredentialStore.MAX_SECRET_BYTES + 1)) }
        assertTrue(dir.listFiles().orEmpty().isEmpty())
        val outside = Files.createTempFile("dav-untouched", ".txt").toFile()
        try {
            outside.writeText("untouched")
            Files.createSymbolicLink(dir.resolve(account.storageKey + ".enc").toPath(), outside.toPath())
            expect("unsafe_file") { store.write(account, "fixture") }
            expect("unsafe_file") { store.read(account) }
            expect("unsafe_file") { store.delete(account) }
            assertEquals("untouched", outside.readText())
        } finally { outside.delete() }
    }
    @Test fun incompleteFirstWriteIsNeverAnAbsentCredential() = directory { dir ->
        val key = key(); val account = identity()
        val store = DavCredentialStore(dir, { key }, checkpoint = { if (it == "file-sync") error("synthetic I/O failure") })
        expect { store.write(account, "fixture-secret") }
        expect("recovery_required") { store.read(account) }
        expect("recovery_required") { DavCredentialStore(dir, { key }).read(account) }
    }
    @Test fun renameAndDirectorySyncFailuresWithholdSuccessUntilReload() {
        for (boundary in listOf("rename", "directory-sync")) directory { dir ->
            val key = key(); val account = identity()
            DavCredentialStore(dir, { key }).write(account, "old-secret")
            val store = DavCredentialStore(dir, { key }, checkpoint = { if (it == boundary) error("synthetic I/O failure") })
            expect("commit_uncertain") { store.write(account, "new-secret") }
            expect("recovery_required") { store.read(account) }
            assertEquals("new-secret", DavCredentialStore(dir, { key }).read(account))
        }
    }
    @Test fun failedDeletionDurabilityNeverAcknowledgesSuccess() = directory { dir ->
        val key = key(); val account = identity()
        DavCredentialStore(dir, { key }).write(account, "fixture-secret")
        val store = DavCredentialStore(dir, { key }, syncDirectory = { error("synthetic I/O failure") })
        expect("commit_uncertain") { store.delete(account) }
        expect("recovery_required") { store.read(account) }
        assertNull(DavCredentialStore(dir, { key }).read(account))
    }
}
