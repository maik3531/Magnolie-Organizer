package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
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
    require(data.toString().toByteArray(Charsets.UTF_8).size <= 16 * 1024 * 1024)
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

internal class Vault(private val directory: File, key: () -> SecretKey,
    private val checkpoint: (String) -> Unit = {},
    private val syncDirectory: (File) -> Unit = ::synchronisiereOrdner) {
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

    @Synchronized fun read(): JSONObject? {
        if (!file.exists()) {
            check(!File(directory, "tablet-vault.enc.pending").exists() &&
                !File(directory, "before-import.enc").exists()) { "Incomplete vault; recovery required" }
            return null
        }
        require(file.length() in 1..(MAX_BYTES + 1024).toLong())
        val value = parseObject(decodeUtf8(crypto.entschluesseln(file.readBytes(), file.name)))
        require(value.getInt("format") == 1)
        validateData(value.getJSONObject("data"))
        return value
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
        val text = value.toString().toByteArray(Charsets.UTF_8)
        require(text.size <= MAX_BYTES)
        val encrypted = crypto.verschluesseln(text, file.name)
        val pending = File(directory, file.name + ".pending")
        var attempted = false
        var durable = false
        try {
            FileOutputStream(pending).use { it.write(encrypted); it.fd.sync() }
            checkpoint("file-sync")
            attempted = true
            Files.move(pending.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            checkpoint("rename")
            syncDirectory(directory)
            durable = true
            checkpoint("directory-sync")
            checkpoint("commit-readback")
            check(file.readBytes().contentEquals(encrypted)) { "Committed bytes differ on readback" }
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
            val before = read() ?: error("Initial state not saved")
            val backup = File(directory, "before-import.enc")
            val pending = File(directory, "before-import.pending")
            val bytes = crypto.verschluesseln(before.toString().toByteArray(), "before-import.enc")
            FileOutputStream(pending).use { it.write(bytes); it.fd.sync() }
            Files.move(pending.toPath(), backup.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            synchronisiereOrdner(directory)
            checkpoint("backup-sync")
            val replacement = JSONObject().put("format", 1).put("data", data).put("alarms", JSONArray())
                .put("enabled", false).put("customEnabled", false).put("delivered", JSONObject())
                .put("revision", UUID.randomUUID().toString())
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
        val spec = PBEKeySpec(password, salt, ITERATIONS, 256)
        return try { SecretKeySpec(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
            .generateSecret(spec).encoded, "AES") } finally { spec.clearPassword() }
    }
    fun seal(text: String, password: CharArray): String {
        validateData(parseObject(text))
        val salt = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val key = key(password, salt)
        val bytes = DatenDateiKrypto({ key }).verschluesseln(text.toByteArray(Charsets.UTF_8), "tablet-export.json")
        return JSONObject().put("format", FORMAT).put("iterations", ITERATIONS)
            .put("salt", Base64.getEncoder().encodeToString(salt))
            .put("ciphertext", Base64.getEncoder().encodeToString(bytes)).toString()
    }
    fun open(text: String, password: CharArray): String {
        val obj = parseObject(text)
        require(obj.getString("format") == FORMAT && obj.getInt("iterations") == ITERATIONS)
        val salt = Base64.getDecoder().decode(obj.getString("salt"))
        val key = key(password, salt)
        val bytes = Base64.getDecoder().decode(obj.getString("ciphertext"))
        val plain = decodeUtf8(DatenDateiKrypto({ key }).entschluesseln(bytes, "tablet-export.json"))
        validateData(parseObject(plain))
        return plain
    }
}
