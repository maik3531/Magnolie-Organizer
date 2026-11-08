package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.nio.file.attribute.PosixFilePermission
import java.security.SecureRandom
import java.util.concurrent.CancellationException
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import org.json.JSONObject
import org.json.JSONTokener

class DavAccountException(val code: String) : Exception(code)

/** Canonical native nextcloud.json metadata; no organizer records, source selections or passwords. */
class DavAccountConfiguration(
    val accountType: DavAccountType = DavAccountType.NEXTCLOUD,
    val davEnabled: Boolean,
    val mailboxEnabled: Boolean = false,
    server: String,
    user: String
) {
    val identity: DavCredentialIdentity
    val server: String
    val user: String
    init {
        if (server.toByteArray(Charsets.UTF_8).size > 4096 || accountType == DavAccountType.GENERIC_DAV && mailboxEnabled) invalidConfiguration()
        identity = DavCredentialIdentity(server, user, accountType)
        this.server = identity.server.toASCIIString(); this.user = identity.username
    }
    fun toCanonicalMap(): Map<String, Any> = linkedMapOf("kontoArt" to accountType.wireName,
        "davAktiv" to davEnabled, "briefkastenAktiv" to mailboxEnabled, "server" to server, "benutzer" to user)
    override fun equals(other: Any?): Boolean = other is DavAccountConfiguration && toCanonicalMap() == other.toCanonicalMap()
    override fun hashCode(): Int = toCanonicalMap().hashCode()
    companion object {
        fun fromCanonicalMap(value: Map<String, Any?>): DavAccountConfiguration {
            val keys = value.keys
            if (keys != setOf("aktiv", "server", "benutzer") &&
                keys != setOf("davAktiv", "briefkastenAktiv", "server", "benutzer") &&
                keys != setOf("kontoArt", "davAktiv", "briefkastenAktiv", "server", "benutzer")) invalidConfiguration()
            val type = if ("kontoArt" !in keys) DavAccountType.NEXTCLOUD else
                DavAccountType.entries.firstOrNull { it.wireName == value["kontoArt"] } ?: invalidConfiguration()
            val legacy = "aktiv" in keys
            return DavAccountConfiguration(type,
                value[if (legacy) "aktiv" else "davAktiv"] as? Boolean ?: invalidConfiguration(),
                value[if (legacy) "aktiv" else "briefkastenAktiv"] as? Boolean ?: invalidConfiguration(),
                value["server"] as? String ?: invalidConfiguration(), value["benutzer"] as? String ?: invalidConfiguration())
        }
        private fun invalidConfiguration(): Nothing = throw DavAccountException("invalid_config")
    }
}

interface DavAccountConfigurationStore {
    val revisionNamespace: String
    fun read(): DavAccountConfiguration?
    /** null is reserved for rollback of a failed initial setup. */
    fun replace(configuration: DavAccountConfiguration?)
}
interface DavAccountCredentials {
    fun read(identity: DavCredentialIdentity): String?
    fun write(identity: DavCredentialIdentity, secret: String)
    fun delete(identity: DavCredentialIdentity): Boolean
}
internal class DavStoredAccountCredentials(private val store: DavCredentialStore) : DavAccountCredentials {
    override fun read(identity: DavCredentialIdentity) = store.read(identity)
    override fun write(identity: DavCredentialIdentity, secret: String) = store.write(identity, secret)
    override fun delete(identity: DavCredentialIdentity) = store.delete(identity)
}

/** Shares the same no-backup directory as the native app but never touches its vault/export files. */
class DavAccountFileStore(
    directory: File,
    private val syncDirectory: (File) -> Unit = ::synchronisiereOrdner,
    private val checkpoint: (String) -> Unit = {}
) : DavAccountConfigurationStore {
    private val directory: File
    val file: File
    override val revisionNamespace: String get() = file.absolutePath
    init {
        if (Files.isSymbolicLink(directory.toPath()) || !directory.isDirectory) throw DavAccountException("native_operation_failed")
        this.directory = directory.canonicalFile
        file = File(this.directory, "nextcloud.json")
        validateDirectory()
    }
    private fun validateDirectory() {
        if (!directory.isDirectory || Files.isSymbolicLink(directory.toPath())) throw DavAccountException("native_operation_failed")
        val permissions = Files.getPosixFilePermissions(directory.toPath(), LinkOption.NOFOLLOW_LINKS)
        if (permissions.any { it !in setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE) }) throw DavAccountException("native_operation_failed")
    }
    private fun validateFile() {
        if (Files.isSymbolicLink(file.toPath()) || !Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS) ||
            Files.getOwner(file.toPath(), LinkOption.NOFOLLOW_LINKS) != Files.getOwner(directory.toPath(), LinkOption.NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), LinkOption.NOFOLLOW_LINKS).any { it !in setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE) }) throw DavAccountException("invalid_config")
        if (file.length() !in 1..16_384) throw DavAccountException("invalid_config")
    }
    @Synchronized override fun read(): DavAccountConfiguration? {
        validateDirectory()
        if (!Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)) return null
        validateFile()
        try {
            val data = file.readBytes()
            if (data.size !in 1..16_384) throw DavAccountException("invalid_config")
            val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()
            val tokener = JSONTokener(text)
            val parsed = tokener.nextValue() as? JSONObject ?: throw DavAccountException("invalid_config")
            if (tokener.nextClean() != '\u0000') throw DavAccountException("invalid_config")
            val value = parsed.keys().asSequence().associateWith { parsed.get(it) }
            return DavAccountConfiguration.fromCanonicalMap(value)
        } catch (error: Exception) { throw DavAccountException("invalid_config") }
    }
    @Synchronized override fun replace(configuration: DavAccountConfiguration?) {
        validateDirectory()
        if (Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)) validateFile()
        if (configuration == null) {
            if (!Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)) return
            Files.delete(file.toPath()); syncDirectory(directory)
        } else {
            val bytes = JSONObject(configuration.toCanonicalMap()).toString().toByteArray(Charsets.UTF_8)
            if (bytes.size > 16_384) throw DavAccountException("invalid_config")
            val temporary = Files.createTempFile(directory.toPath(), ".nextcloud-", ".tmp").toFile()
            try {
                Files.setPosixFilePermissions(temporary.toPath(), setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE))
                FileOutputStream(temporary).use { it.write(bytes); it.fd.sync() }
                checkpoint("file-sync")
                Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
                checkpoint("rename")
                syncDirectory(directory)
                checkpoint("directory-sync")
            } finally { Files.deleteIfExists(temporary.toPath()) }
        }
        if (read() != configuration) throw DavAccountException("verification_failed")
    }
}

class DavAccountStatus internal constructor(
    val configuration: DavAccountConfiguration?, val credentialPresent: Boolean?, val revision: String?,
    val state: String, val errorCode: String, val calendars: List<DavCollection> = emptyList(),
    val addressBooks: List<DavCollection> = emptyList(), val connectivityChecked: Boolean = false
) {
    fun payload(requestId: String? = null, persisted: Boolean? = null): Map<String, Any> {
        val config = configuration
        val value = linkedMapOf<String, Any>("verfuegbar" to true, "aktiv" to (config?.mailboxEnabled ?: false),
            "kontoArt" to (config?.accountType?.wireName ?: "nextcloud"), "davAktiv" to (config?.davEnabled ?: false),
            "briefkastenAktiv" to (config?.mailboxEnabled ?: false), "server" to (config?.server ?: ""),
            "url" to (config?.server ?: ""), "benutzer" to (config?.user ?: ""),
            "kennwortVorhanden" to (credentialPresent ?: false), "revision" to (revision ?: JSONObject.NULL),
            "zustand" to state, "fehlerCode" to errorCode, "fehler" to message(errorCode),
            "kalender" to calendars.map(::collectionPayload), "adressbuecher" to addressBooks.map(::collectionPayload),
            "connectivityChecked" to connectivityChecked)
        if (requestId != null) { value["requestId"] = requestId; value["ok"] = true }
        if (persisted != null) { value["persisted"] = persisted; value["verified"] = persisted }
        return value
    }
    private fun collectionPayload(collection: DavCollection): Map<String, Any> {
        val value = linkedMapOf<String, Any>("uid" to collection.uid, "name" to collection.name, "href" to collection.href.toASCIIString(), "art" to collection.kind.wireName)
        if (collection.kind == DavKind.CALENDAR) value["supportsVtodo"] = collection.supportsVtodo
        return value
    }
    private fun message(code: String): String = when (code) {
        "none" -> ""
        "http_401" -> "DAV authentication failed (HTTP 401)."
        "http_403" -> "DAV access was denied (HTTP 403)."
        "conflict" -> "The account changed. Read its current state before retrying."
        "app_password_missing" -> "The account application password is missing."
        "secret_service_unavailable" -> "The protected account credential is unavailable."
        "unsupported_feature" -> "The Nextcloud mailbox is not implemented on this platform."
        "timeout" -> "DAV discovery exceeded its time limit."
        "verification_failed" -> "The account change could not be verified. Reload before retrying."
        else -> "The DAV account operation failed."
    }
}
class DavAccountDiscovery internal constructor(val status: DavAccountStatus, val reachable: Boolean, val partial: Boolean) {
    fun connectionTestPayload(requestId: String): Map<String, Any> = linkedMapOf("requestId" to requestId,
        "ok" to true, "revision" to (status.revision ?: JSONObject.NULL), "reachable" to reachable,
        "partial" to partial, "errorCode" to status.errorCode, "calendars" to status.calendars.size, "addressBooks" to status.addressBooks.size)
}

/** Account mutations are synchronous under one monitor; network discovery releases that monitor.
 * Call from a background executor. This service never modifies records or claims a completed sync.
 */
class DavAccountService(
    private val configuration: DavAccountConfigurationStore,
    private val credentials: DavAccountCredentials,
    private val transport: BoundedHttpTransport = OkHttpBoundedTransport(),
    private val monotonicNanos: () -> Long = System::nanoTime
) {
    private val revisionKey = ByteArray(32).also { SecureRandom().nextBytes(it) }
    private var epoch = 0L
    private var poisoned = false
    private var cachedDiscovery: DavAccountDiscovery? = null
    private class Snapshot(val configuration: DavAccountConfiguration?, val secret: String?, val revision: String)
    private fun snapshot(): Snapshot {
        if (poisoned) throw DavAccountException("verification_failed")
        val config = configuration.read()
        val secret = config?.let { credentials.read(it.identity) }
        val output = ByteArrayOutputStream()
        DataOutputStream(output).use { stream ->
            fun field(value: String?) {
                if (value == null) stream.writeInt(-1) else {
                    val bytes = value.toByteArray(Charsets.UTF_8)
                    try { stream.writeInt(bytes.size); stream.write(bytes) } finally { bytes.fill(0) }
                }
            }
            field("Magnolie-DAV-account-revision-v1"); field(configuration.revisionNamespace)
            stream.writeLong(epoch)
            if (config == null) stream.writeBoolean(false) else {
                stream.writeBoolean(true); field(config.accountType.wireName); stream.writeBoolean(config.davEnabled)
                stream.writeBoolean(config.mailboxEnabled); field(config.server); field(config.user)
            }
            field(secret)
        }
        val material = output.toByteArray()
        try {
            val hmac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(revisionKey, "HmacSHA256")) }.doFinal(material)
            return Snapshot(config, secret, hmac.joinToString("") { "%02x".format(it.toInt() and 0xff) })
        } finally { material.fill(0) }
    }
    private fun status(snapshot: Snapshot, calendars: List<DavCollection> = emptyList(), books: List<DavCollection> = emptyList(), checked: Boolean = false, error: String = "none"): DavAccountStatus {
        val config = snapshot.configuration
        val state = when {
            error != "none" -> "fehler"
            config == null -> "nicht_eingerichtet"
            !config.davEnabled && !config.mailboxEnabled -> "aus"
            snapshot.secret.isNullOrEmpty() -> "unvollstaendig"
            config.mailboxEnabled -> "fehler"
            else -> "bereit"
        }
        return DavAccountStatus(config, !snapshot.secret.isNullOrEmpty(), snapshot.revision, state,
            if (error == "none" && config?.mailboxEnabled == true) "unsupported_feature" else error, calendars.toList(), books.toList(), checked)
    }
    @Synchronized fun status(): DavAccountStatus {
        try {
            val current = snapshot()
            cachedDiscovery?.takeIf { it.status.revision == current.revision }?.let { return it.status }
            cachedDiscovery = null
            return status(current)
        } catch (error: Exception) {
            cachedDiscovery = null
            return DavAccountStatus(try { configuration.read() } catch (_: Exception) { null }, null, null,
                "fehler", errorCode(error))
        }
    }
    @Synchronized fun save(expectedRevision: String, configuration: DavAccountConfiguration,
                           applicationPassword: String = "", clearPassword: Boolean = false): DavAccountStatus {
        val previous = snapshot()
        if (previous.revision != expectedRevision) throw DavAccountException("conflict")
        if (configuration.mailboxEnabled) throw DavAccountException("unsupported_feature")
        if (clearPassword && (applicationPassword.isNotEmpty() || configuration.davEnabled) || applicationPassword.toByteArray(Charsets.UTF_8).size > 16_384) throw DavAccountException("invalid_config")
        val target = configuration.identity
        val oldIdentity = previous.configuration?.identity
        val sameIdentity = target.storageKey == oldIdentity?.storageKey
        val priorTarget = credentials.read(target)
        if (snapshot().revision != previous.revision || sameIdentity && priorTarget != previous.secret) throw DavAccountException("conflict")
        val replacement = if (applicationPassword.isNotEmpty()) applicationPassword else if (clearPassword) null else priorTarget
        if (configuration.davEnabled && (replacement.isNullOrEmpty() || !sameIdentity && applicationPassword.isEmpty())) throw DavAccountException("app_password_missing")
        try {
            if (applicationPassword.isNotEmpty()) credentials.write(target, applicationPassword)
            else if (clearPassword) credentials.delete(target)
            this.configuration.replace(configuration)
            val readback = snapshot()
            if (readback.configuration != configuration || readback.secret != replacement) throw DavAccountException("verification_failed")
            if (oldIdentity != null && !sameIdentity) {
                credentials.delete(oldIdentity)
                if (credentials.read(oldIdentity) != null) throw DavAccountException("verification_failed")
            }
            val final = snapshot()
            if (final.configuration != configuration || final.secret != replacement) throw DavAccountException("verification_failed")
            epoch++
            cachedDiscovery = null
            return status(snapshot())
        } catch (error: Exception) {
            try {
                val actual = this.configuration.read()
                if (actual != previous.configuration && actual != configuration) throw DavAccountException("verification_failed")
                val currentTarget = credentials.read(target)
                if (currentTarget != priorTarget && currentTarget != replacement) throw DavAccountException("verification_failed")
                if (oldIdentity != null && !sameIdentity) {
                    val currentOld = credentials.read(oldIdentity)
                    if (currentOld != null && currentOld != previous.secret) throw DavAccountException("verification_failed")
                    restore(previous.secret, oldIdentity)
                }
                restore(priorTarget, target)
                this.configuration.replace(previous.configuration)
                val restored = snapshot()
                if (restored.configuration != previous.configuration || restored.secret != previous.secret || credentials.read(target) != priorTarget) throw DavAccountException("verification_failed")
            } catch (rollback: Exception) {
                poisoned = true; cachedDiscovery = null
                throw DavAccountException("verification_failed")
            }
            throw error
        }
    }
    private fun restore(secret: String?, identity: DavCredentialIdentity) {
        if (secret != null) credentials.write(identity, secret) else credentials.delete(identity)
    }
    fun discover(expectedRevision: String, cancellation: DavCancellation = DavCancellation()): DavAccountDiscovery {
        val before = synchronized(this) {
            snapshot().also {
                if (it.revision != expectedRevision) throw DavAccountException("conflict")
                if (it.configuration?.davEnabled != true) throw DavAccountException("not_active")
                if (it.secret.isNullOrEmpty()) throw DavAccountException("app_password_missing")
            }
        }
        val config = before.configuration!!
        val deadline = monotonicNanos() + TimeUnit.SECONDS.toNanos(60)
        val bounded = BoundedHttpTransport { request, token ->
            token.check()
            val remaining = deadline - monotonicNanos()
            if (remaining <= 0) throw DavException("timeout")
            val response = transport.send(BoundedHttpRequest(request.uri, request.method, request.headers, request.body,
                minOf(request.timeoutMillis, TimeUnit.NANOSECONDS.toMillis(remaining).coerceAtLeast(1)), request.maxResponseBytes), token)
            token.check()
            if (monotonicNanos() > deadline) throw DavException("timeout")
            response
        }
        val client = DavClient(config.server, config.user, before.secret!!, config.accountType, bounded)
        var calendars = emptyList<DavCollection>(); var books = emptyList<DavCollection>(); var code = "none"
        try {
            calendars = client.collections(DavKind.CALENDAR, cancellation)
            synchronized(this) { if (snapshot().revision != before.revision) throw DavAccountException("conflict") }
            books = client.collections(DavKind.ADDRESSBOOK, cancellation)
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) { code = errorCode(error) }
        cancellation.check()
        return synchronized(this) {
            if (snapshot().revision != before.revision) throw DavAccountException("conflict")
            val partial = code != "none" && (calendars.isNotEmpty() || books.isNotEmpty())
            val result = DavAccountDiscovery(status(before, calendars, books, true, code), code == "none" || partial, partial)
            cachedDiscovery = result
            result
        }
    }
    companion object {
        fun errorCode(error: Throwable): String = when (error) {
            is DavAccountException -> error.code
            is DavCredentialException -> "secret_service_unavailable"
            is DavException -> when (error.code) {
                "unauthorized" -> "http_401"
                "forbidden" -> "http_403"
                "conflict" -> error.status?.let { "http_$it" } ?: "conflict"
                "invalid_configuration" -> "invalid_config"
                "transport_error" -> "network_error"
                "dav_origin_rejected", "malformed_xml", "partial_multistatus", "incomplete_report", "report_outside_collection", "invalid_response", "response_too_large", "incomplete_response" -> "invalid_response"
                "timeout" -> "timeout"
                else -> if (error.status != null) "http_${error.status}" else "nextcloud_error"
            }
            else -> "native_operation_failed"
        }
    }
}
