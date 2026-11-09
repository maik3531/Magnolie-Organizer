package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.File
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.SecureRandom
import java.util.UUID
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

internal const val MAX_BYTES = 32 * 1024 * 1024

internal fun trustedOrigin(value: String): Boolean = try {
    val uri = java.net.URI(value)
    uri.scheme == "https" && uri.host == "appassets.androidplatform.net" &&
        uri.rawUserInfo == null && uri.port in setOf(-1,443)
} catch (_: Exception) { false }

internal fun parseObject(text: String): JSONObject {
    require(text.toByteArray(Charsets.UTF_8).size <= MAX_BYTES)
    var depth = 0
    var quoted = false
    var escaped = false
    for (c in text) {
        if (quoted) {
            if (escaped) escaped = false else if (c == '\\') escaped = true else if (c == '"') quoted = false
        } else when (c) {
            '"' -> quoted = true
            '{', '[' -> { depth++; require(depth <= 64) }
            '}', ']' -> { depth--; require(depth >= 0) }
        }
    }
    require(depth == 0 && !quoted)
    val tokener = JSONTokener(text)
    val result = tokener.nextValue() as? JSONObject ?: error("JSON object required")
    require(tokener.nextClean() == '\u0000')
    return result
}

internal fun decodeUtf8(bytes: ByteArray): String = Charsets.UTF_8.newDecoder()
    .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
    .decode(ByteBuffer.wrap(bytes)).toString()

internal fun validateData(data: JSONObject) {
    VaultJson.encode(data,16 * 1024 * 1024)
    require(data.getInt("version") == 6)
    for (key in listOf("termine", "aufgaben", "kontakte", "notizen")) {
        val array = data.getJSONArray(key)
        require(array.length() <= 100000)
        for (i in 0 until array.length()) require(array.get(i) is JSONObject)
    }
    require(data.getJSONObject("einstellungen").length() > 0)
}

internal data class DocumentSession(val id: String, val revision: String)
internal data class LoadedDocument(val session: DocumentSession, val value: JSONObject?)
internal class CommitFailure(val outcome: String, cause: Exception) : Exception(outcome, cause)

internal class Vault(directory: File, key: () -> SecretKey,
    private val checkpoint: (String) -> Unit = {},
    syncDirectory: ((File) -> Unit)? = null,
    private val fileOps: StorageFileOps = NioStorageFileOps) {
    private val directory = fileOps.ensurePrivateDirectory(directory)
    private val syncDirectory = syncDirectory ?: fileOps::syncDirectory
    private val crypto = DatenDateiKrypto(key)
    private val file = File(directory, "tablet-vault.enc")
    private var currentSession: DocumentSession? = null
    private var activated = false
    private var poisoned = false
    private var newDocument = false
    private data class Import(val token: String, val session: DocumentSession, val text: String)
    private var pendingImport: Import? = null

    @Synchronized fun openSession(): LoadedDocument {
        currentSession = null; activated = false; pendingImport = null
        // A new page must verify the actual disk outcome, not reuse the old in-memory snapshot.
        syncDirectory(directory)
        checkpoint("load-readback")
        val value = read()
        newDocument = value == null
        poisoned = false
        val revision = value?.optString("revision")?.takeIf { it.isNotEmpty() } ?: UUID.randomUUID().toString()
        // Existing debug-beta format-1 vaults predate native revisions.
        if (value != null && !value.has("revision")) commit(value.put("revision", revision))
        val session = DocumentSession(UUID.randomUUID().toString(), revision)
        currentSession = session
        return LoadedDocument(session, value)
    }

    @Synchronized fun activate(session: DocumentSession) {
        check(!poisoned && session == currentSession)
        check(read()?.getString("revision")?.let { it == session.revision } ?: newDocument)
        activated = true
    }

    @Synchronized fun isWritable(session: DocumentSession): Boolean =
        !poisoned && activated && currentSession == session

    @Synchronized fun requireSession(session: DocumentSession) {
        check(isWritable(session)) { "Stale or unacknowledged document session" }
        check(read()?.getString("revision")?.let { it == session.revision } ?: newDocument) { "Stale document revision" }
    }

    private data class Snapshot(val value: JSONObject, val plaintext: ByteArray)
    @Synchronized fun read(): JSONObject? {
        val snapshot=readSnapshot() ?: return null
        return snapshot.value.also {snapshot.plaintext.fill(0)}
    }
    private fun readSnapshot(): Snapshot? {
        val encrypted = fileOps.read(file, MAX_BYTES + 1024)
        if (encrypted == null) {
            check(fileOps.stat(File(directory, "tablet-vault.enc.pending")) == null &&
                fileOps.stat(File(directory, "before-import.enc")) == null) { "Incomplete vault; recovery required" }
            return null
        }
        val plaintext=crypto.entschluesseln(encrypted,file.name)
        try {
            val value=parseObject(decodeUtf8(plaintext))
            require(value.getInt("format")==1)
            validateData(value.getJSONObject("data"))
            return Snapshot(value,plaintext)
        } catch(error:Exception) {plaintext.fill(0);throw error}
    }

    @Synchronized fun write(value: JSONObject) {
        check(!poisoned) { "Uncertain commit; reload required" }
        val current = read() ?: error("Native update requires an existing document")
        check(value.getString("revision") == current.getString("revision")) { "Stale native snapshot" }
        commit(value)
    }

    private fun commit(value: JSONObject) {
        require(value.getInt("format") == 1)
        validateData(value.getJSONObject("data"))
        val text = VaultJson.encode(value,MAX_BYTES).toByteArray(Charsets.UTF_8)
        require(text.size <= MAX_BYTES)
        val encrypted = crypto.verschluesseln(text, file.name)
        val pending = File(directory, file.name + ".pending")
        var attempted = false
        var durable = false
        try {
            fileOps.writeAndSync(pending, encrypted, MAX_BYTES + 1024)
            checkpoint("file-sync")
            attempted = true
            fileOps.atomicReplace(pending, file)
            checkpoint("rename")
            syncDirectory(directory)
            durable = true
            checkpoint("directory-sync")
            checkpoint("commit-readback")
            check(fileOps.read(file, MAX_BYTES + 1024)?.contentEquals(encrypted) == true) { "Committed bytes differ on readback" }
            read() ?: error("Committed vault missing")
        } catch (error: Exception) {
            if (attempted) { poisoned = true; activated = false; currentSession = null; pendingImport = null }
            throw CommitFailure(if (durable) "committed" else if (attempted) "uncertain" else "before-commit", error)
        }
    }

    @Synchronized fun save(session: DocumentSession, text: String, alarms: JSONArray): JSONObject {
        requireSession(session)
        val data = parseObject(text)
        validateData(data)
        require(alarms.length() <= 100000)
        for (i in 0 until alarms.length()) {
            val a = alarms.getJSONObject(i)
            require(a.getString("id").length <= 1024 && a.getLong("at") > 0)
            require(a.getString("section") in setOf("kalender", "aufgaben"))
            require(a.getString("title").length <= 300)
            a.getBoolean("custom")
        }
        val value = read() ?: JSONObject().put("format", 1).put("enabled", false)
            .put("customEnabled", false).put("delivered", JSONObject())
        value.put("data", data).put("alarms", alarms).put("revision", UUID.randomUUID().toString())
        // Keep delivery receipts only for live alarms; edits/deletions invalidate old schedules.
        val old = value.optJSONObject("delivered") ?: JSONObject()
        val retained = JSONObject()
        for (i in 0 until alarms.length()) {
            val id = alarms.getJSONObject(i).getString("id")
            if (old.has(id)) retained.put(id, old.get(id))
        }
        value.put("delivered", retained)
        commit(value)
        newDocument = false
        currentSession = DocumentSession(session.id, value.getString("revision"))
        pendingImport = null
        return value
    }

    @Synchronized fun prepareImport(session: DocumentSession, text: String): String {
        requireSession(session)
        validateData(parseObject(text))
        val token = UUID.randomUUID().toString()
        pendingImport = Import(token, session, text)
        return token
    }

    @Synchronized fun cancelImport(session: DocumentSession, token: String) {
        requireSession(session)
        check(pendingImport?.let { it.token == token && it.session == session } == true)
        pendingImport = null
    }

    @Synchronized fun replace(session: DocumentSession, token: String): JSONObject {
        requireSession(session)
        val candidate = pendingImport ?: error("No native import authorization")
        check(candidate.session == session && candidate.token == token) { "Stale import authorization" }
        pendingImport = null; currentSession = null; activated = false
        try {
            val data = parseObject(candidate.text)
            validateData(data)
            val replacement = JSONObject().put("format", 1).put("data", data).put("alarms", JSONArray())
                .put("enabled", false).put("customEnabled", false).put("delivered", JSONObject())
                .put("revision", UUID.randomUUID().toString())
            VaultJson.encode(replacement,MAX_BYTES) // Reject the full output before changing any recovery file.
            val before = readSnapshot() ?: error("Initial state not saved")
            val backup = File(directory, "before-import.enc")
            val pending = File(directory, "before-import.pending")
            val bytes = try {crypto.verschluesseln(before.plaintext,"before-import.enc")}
                finally {before.plaintext.fill(0)}
            fileOps.writeAndSync(pending, bytes, MAX_BYTES + 1024)
            fileOps.atomicReplace(pending, backup)
            syncDirectory(directory)
            checkpoint("backup-sync")
            commit(replacement)
            return replacement
        } catch (error: CommitFailure) { throw error }
        catch (error: Exception) { throw CommitFailure("before-commit", error) }
    }
}

internal object Portable {
    private const val FORMAT = "Magnolie-Organizer-Android-Tablet-Beta-1"
    private const val ITERATIONS = 210000
    private fun key(password: CharArray, salt: ByteArray): SecretKey {
        require(password.size in 8..1024 && salt.size == 32)
        val bytes=Pbkdf2Sha256.derive(password,salt,ITERATIONS)
        return try { SecretKeySpec(bytes,"AES") } finally { bytes.fill(0) }
    }
    fun seal(text: String, password: CharArray): String {
        validateData(parseObject(text))
        val salt = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val key = key(password, salt)
        val bytes = DatenDateiKrypto({ key }).verschluesseln(text.toByteArray(Charsets.UTF_8), "tablet-export.json")
        return JSONObject().put("format", FORMAT).put("iterations", ITERATIONS)
            .put("salt", StandardBase64.encode(salt))
            .put("ciphertext", StandardBase64.encode(bytes)).toString()
    }
    fun open(text: String, password: CharArray): String {
        val obj = parseObject(text)
        require(obj.getString("format") == FORMAT && obj.getInt("iterations") == ITERATIONS)
        val salt = StandardBase64.decode(obj.getString("salt"))
        val key = key(password, salt)
        val bytes = StandardBase64.decode(obj.getString("ciphertext"))
        val plain = decodeUtf8(DatenDateiKrypto({ key }).entschluesseln(bytes, "tablet-export.json"))
        validateData(parseObject(plain))
        return plain
    }
}
