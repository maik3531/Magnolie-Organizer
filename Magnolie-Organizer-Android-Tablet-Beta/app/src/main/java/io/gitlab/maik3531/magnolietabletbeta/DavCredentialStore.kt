package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import javax.crypto.SecretKey

class DavCredentialException(val code: String) : Exception(code)

/** Stable binding to provider + canonical server + case-sensitive username; never a password. */
class DavCredentialIdentity(server: String, username: String, accountType: DavAccountType = DavAccountType.NEXTCLOUD) {
    private val account = DavClient(server, username, "", accountType,
        BoundedHttpTransport { _, _ -> throw DavException("unexpected_request") })
    val server = account.server
    val username = account.username
    val accountType = account.accountType
    val storageKey: String
    init {
        val output = ByteArrayOutputStream()
        output.write("Magnolie-DAV-credential-v1\u0000".toByteArray(Charsets.UTF_8))
        DataOutputStream(output).use { stream ->
            for (field in listOf(accountType.wireName, account.server.toASCIIString(), account.username)) {
                val bytes = field.toByteArray(Charsets.UTF_8)
                stream.writeInt(bytes.size); stream.write(bytes)
            }
        }
        storageKey = MessageDigest.getInstance("SHA-256").digest(output.toByteArray()).joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}

/** Encrypted private account passwords are separate from organizer data and portable exports.
 * Production injects a non-exportable AndroidKeyStore key through AndroidDavCredentials.
 */
internal class DavCredentialStore(
    directory: File,
    key: () -> SecretKey,
    private val syncDirectory: (File) -> Unit = ::synchronisiereOrdner,
    private val checkpoint: (String) -> Unit = {}
) {
    private val directory: File
    private val crypto = DatenDateiKrypto(key)
    private var poisoned = false
    init {
        if (Files.isSymbolicLink(directory.toPath())) throw DavCredentialException("unsafe_directory")
        if (!directory.exists() && !directory.mkdirs()) throw DavCredentialException("storage_unavailable")
        if (!directory.isDirectory) throw DavCredentialException("storage_unavailable")
        this.directory = directory.canonicalFile
        if (!this.directory.setReadable(false, false) || !this.directory.setWritable(false, false) || !this.directory.setExecutable(false, false) ||
            !this.directory.setReadable(true, true) || !this.directory.setWritable(true, true) || !this.directory.setExecutable(true, true)) throw DavCredentialException("storage_unavailable")
    }
    private fun file(identity: DavCredentialIdentity) = File(directory, identity.storageKey + ".enc")
    private fun pending(identity: DavCredentialIdentity) = File(directory, identity.storageKey + ".enc.pending")
    private fun ensureReadable(identity: DavCredentialIdentity) {
        if (poisoned || pending(identity).exists()) throw DavCredentialException("recovery_required")
        if (Files.isSymbolicLink(file(identity).toPath()) || Files.isSymbolicLink(pending(identity).toPath())) throw DavCredentialException("unsafe_file")
    }
    @Synchronized fun read(identity: DavCredentialIdentity): String? {
        ensureReadable(identity)
        val file = file(identity)
        if (!file.exists()) return null
        if (!file.isFile || file.length() !in 1..(MAX_SECRET_BYTES + 1024).toLong()) throw DavCredentialException("invalid_stored_credential")
        var plain: ByteArray? = null
        try {
            plain = crypto.entschluesseln(file.readBytes(), file.name)
            if (plain.size !in 1..MAX_SECRET_BYTES) throw DavCredentialException("invalid_stored_credential")
            return Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(plain)).toString()
        } catch (error: Exception) {
            throw if (error is DavCredentialException) error else DavCredentialException("credential_unavailable")
        } finally { plain?.fill(0) }
    }
    @Synchronized fun write(identity: DavCredentialIdentity, secret: String) {
        ensureReadable(identity)
        val plain = secret.toByteArray(Charsets.UTF_8)
        if (plain.size !in 1..MAX_SECRET_BYTES) { plain.fill(0); throw DavCredentialException("invalid_secret") }
        val file = file(identity)
        val pending = pending(identity)
        var attemptedRename = false
        try {
            val encrypted = crypto.verschluesseln(plain, file.name)
            if (!pending.createNewFile()) throw DavCredentialException("recovery_required")
            if (!pending.setReadable(false, false) || !pending.setWritable(false, false) || !pending.setReadable(true, true) || !pending.setWritable(true, true)) throw DavCredentialException("storage_unavailable")
            FileOutputStream(pending).use { it.write(encrypted); it.fd.sync() }
            checkpoint("file-sync")
            attemptedRename = true
            Files.move(pending.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            checkpoint("rename")
            syncDirectory(directory)
            checkpoint("directory-sync")
            if (!file.readBytes().contentEquals(encrypted) || read(identity) != secret) throw DavCredentialException("readback_mismatch")
        } catch (error: Exception) {
            if (attemptedRename) poisoned = true
            throw if (error is DavCredentialException) error else DavCredentialException(if (attemptedRename) "commit_uncertain" else "credential_unavailable")
        } finally { plain.fill(0) }
    }
    @Synchronized fun delete(identity: DavCredentialIdentity): Boolean {
        ensureReadable(identity)
        val file = file(identity)
        if (!file.exists()) return false
        try {
            Files.delete(file.toPath())
            syncDirectory(directory)
            checkpoint("delete-directory-sync")
            if (file.exists()) throw DavCredentialException("readback_mismatch")
            return true
        } catch (error: Exception) {
            poisoned = true
            throw if (error is DavCredentialException) error else DavCredentialException("commit_uncertain")
        }
    }
    companion object { const val MAX_SECRET_BYTES = 16_384 }
}
