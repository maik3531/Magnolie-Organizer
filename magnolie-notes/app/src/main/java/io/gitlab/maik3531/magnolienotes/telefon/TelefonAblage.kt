package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.KeyStore
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal interface TelefonPayloadStorage {
    fun encryptPayload(clear: ByteArray, type: String, id: String): ByteArray
    fun decryptPayload(value: ByteArray, type: String, id: String): ByteArray
}

class TelefonAblage private constructor(context: Context) : TelefonPayloadStorage {
    private val app = context.applicationContext
    val directory = File(app.filesDir, "telefon").apply { mkdirs() }
    private val identityFile = File(directory, "identity.json")
    private val peersFile = File(directory, "peers.bin")
    private val settings = app.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE)
    private val json = Json { encodeDefaults = true; ignoreUnknownKeys = false }

    init {
        if (!settings.getBoolean("native_messaging_removed", false)) {
            settings.edit().remove("sms_send_enabled").remove("sms_receive_enabled")
                .remove("sms_subscription_id").putBoolean("native_messaging_removed", true).commit()
        }
        if (settings.contains("pending_computer_selection")) {
            val selected = peers().peer
            if (selected?.device_id.orEmpty() == settings.getString("pending_computer_selection", ""))
                restoreComputerSettings(selected)
            else check(settings.edit().remove("pending_computer_selection").commit())
        }
        if (!settings.contains("calls_enabled")) {
            val configured = listOf("dial_request_enabled", "incoming_calls_enabled", "incoming_number_enabled", "answer_calls_enabled")
                .any(settings::contains)
            setCallsEnabled(TelefonModulStatus.dialResolvable(app) &&
                (dialRequestEnabled() || incomingCallsEnabled() || incomingNumberEnabled() || answerCallsEnabled() || !configured))
        }
    }

    fun enabled(): Boolean = settings.getBoolean("enabled", false)
    fun setEnabled(enabled: Boolean) { settings.edit().putBoolean("enabled", enabled).commit() }
    fun bluetoothEnabled(): Boolean = settings.getBoolean("bluetooth_enabled", false)
    fun setBluetoothEnabled(enabled: Boolean) { settings.edit().putBoolean("bluetooth_enabled", enabled).commit() }
    fun dialRequestEnabled(): Boolean = settings.getBoolean("dial_request_enabled", false)
    fun notificationsEnabled(): Boolean = settings.getBoolean("notifications_enabled", false)
    fun incomingCallsEnabled(): Boolean = settings.getBoolean("incoming_calls_enabled", false)
    fun incomingNumberEnabled(): Boolean = settings.getBoolean("incoming_number_enabled", false)
    fun answerCallsEnabled(): Boolean = settings.getBoolean("answer_calls_enabled", false)
    fun callsEnabled(): Boolean = settings.getBoolean("calls_enabled", false)
    fun setCallsEnabled(value: Boolean) {
        check(settings.edit().putBoolean("calls_enabled", value)
            .putBoolean("dial_request_enabled", value).putBoolean("incoming_calls_enabled", value)
            .putBoolean("incoming_number_enabled", value).putBoolean("answer_calls_enabled", value).commit())
    }
    fun selectedPackages(): Set<String> = settings.getStringSet("notification_packages", emptySet())?.toSet().orEmpty()
    fun setDialRequestEnabled(value: Boolean) { settings.edit().putBoolean("dial_request_enabled", value).commit() }
    fun setNotificationsEnabled(value: Boolean) { settings.edit().putBoolean("notifications_enabled", value).commit() }
    fun setIncomingCallsEnabled(value: Boolean) { settings.edit().putBoolean("incoming_calls_enabled", value).commit() }
    fun setIncomingNumberEnabled(value: Boolean) { settings.edit().putBoolean("incoming_number_enabled", value).commit() }
    fun setAnswerCallsEnabled(value: Boolean) { settings.edit().putBoolean("answer_calls_enabled", value).commit() }
    fun setSelectedPackages(value: Set<String>) { settings.edit().putStringSet("notification_packages", value).commit() }
    fun personalOwnDevice(): Boolean = peers().peer?.let { it.state == "paired" }
        ?: settings.getBoolean("personal_sync_own_device", true)
    fun personalNotesEnabled(): Boolean = settings.getBoolean("personal_sync_notes", true)
    fun personalTasksEnabled(): Boolean = settings.getBoolean("personal_sync_tasks", true)
    fun personalAutoWifi(): Boolean = settings.getBoolean("personal_sync_auto_wifi", true)
    fun personalDeletionsEnabled(): Boolean = settings.getBoolean("personal_sync_deletions", false)
    fun personalDeletionsConfigured(): Boolean = settings.contains("personal_sync_deletions")
    fun personalSyncReport(): String = settings.getString("personal_sync_report", "").orEmpty()
    fun personalSyncLastAuto(): Long = settings.getLong("personal_sync_last_auto", 0)
    fun setPersonalSyncLastAuto(value: Long) { settings.edit().putLong("personal_sync_last_auto", value).commit() }
    fun personalSyncLastCounter(): Long = settings.getLong("personal_sync_last_counter", -1)
    private fun contactChoiceKey(deviceId: String, publicKey: String): String =
        "contact_read_choice_" + deviceId + "_" + TelefonKrypto.sha256(publicKey.toByteArray()).joinToString("") { "%02x".format(it) }
    fun rememberContactReadChoice(deviceId: String, publicKey: String, enabled: Boolean) {
        check(settings.edit().putBoolean(contactChoiceKey(deviceId, publicKey), enabled).commit())
    }
    fun rememberedContactReadChoice(deviceId: String, publicKey: String): Boolean =
        settings.getBoolean(contactChoiceKey(deviceId, publicKey), true)
    private fun contactGroupWriteChoiceKey(deviceId: String, publicKey: String): String =
        "contact_groups_write_choice_" + deviceId + "_" + TelefonKrypto.sha256(publicKey.toByteArray()).joinToString("") { "%02x".format(it) }
    fun rememberContactGroupWriteChoice(deviceId: String, publicKey: String, enabled: Boolean) {
        check(settings.edit().putBoolean(contactGroupWriteChoiceKey(deviceId, publicKey), enabled).commit())
    }
    fun rememberedContactGroupWriteChoice(deviceId: String, publicKey: String): Boolean =
        settings.getBoolean(contactGroupWriteChoiceKey(deviceId, publicKey), true)
    private fun contactWriteChoiceKey(deviceId: String, publicKey: String): String =
        "contacts_write_choice_" + deviceId + "_" + TelefonKrypto.sha256(publicKey.toByteArray()).joinToString("") { "%02x".format(it) }
    fun rememberContactWriteChoice(deviceId: String, publicKey: String, enabled: Boolean) {
        check(settings.edit().putBoolean(contactWriteChoiceKey(deviceId, publicKey), enabled)
            .putBoolean(contactGroupWriteChoiceKey(deviceId, publicKey), enabled).commit())
    }
    fun rememberedContactWriteChoice(deviceId: String, publicKey: String): Boolean = when {
        settings.contains(contactWriteChoiceKey(deviceId, publicKey)) -> settings.getBoolean(contactWriteChoiceKey(deviceId, publicKey), false)
        settings.contains(contactGroupWriteChoiceKey(deviceId, publicKey)) -> settings.getBoolean(contactGroupWriteChoiceKey(deviceId, publicKey), false)
        else -> true
    }
    fun setPersonalSyncLastCounter(value: Long) { settings.edit().putLong("personal_sync_last_counter", value).commit() }
    fun setPersonalSync(own: Boolean, notes: Boolean, tasks: Boolean, autoWifi: Boolean,
                        deletions: Boolean = personalDeletionsEnabled(), rememberDeletions: Boolean = true) {
        val edit = settings.edit().putBoolean("personal_sync_own_device", own)
            .putBoolean("personal_sync_notes", own && notes)
            .putBoolean("personal_sync_tasks", own && tasks)
            .putBoolean("personal_sync_auto_wifi", own && autoWifi)
        if (rememberDeletions || personalDeletionsConfigured())
            edit.putBoolean("personal_sync_deletions", own && deletions)
        edit.commit()
    }
    fun setPersonalSyncReport(value: String) { settings.edit().putString("personal_sync_report", value.take(2000)).commit() }

    @Synchronized
    fun identity(defaultName: String): Pair<TelefonIdentitaet, ByteArray> {
        if (identityFile.exists()) {
            val identity = json.decodeFromString<TelefonIdentitaet>(identityFile.readText())
            return identity to decrypt(identity.wrapped_private, "identity-private", identity.device_id)
        }
        if (peersFile.exists()) throw TelefonProtokollFehler("Telefonidentität ist nicht lesbar; Zurücksetzen erforderlich.")
        val (private, public) = TelefonKrypto.schluesselpaar()
        val id = UUID.randomUUID().toString().lowercase()
        val identity = TelefonIdentitaet(
            device_id = id,
            display_name = DeviceStatusCollector.clean(defaultName, 60).ifBlank { "Magnolie Notes" },
            static_public = TelefonKrypto.b64(public),
            wrapped_private = encrypt(private, "identity-private", id)
        )
        atomic(identityFile, json.encodeToString(TelefonIdentitaet.serializer(), identity).toByteArray())
        private.fill(0)
        return identity to decrypt(identity.wrapped_private, "identity-private", id)
    }

    @Synchronized
    fun peers(): TelefonBestand = if (!peersFile.exists()) TelefonBestand() else {
        val clear = decrypt(peersFile.readText(), "peers", "v1")
        try {
            val (sanitized, migrated) = sanitizeLegacyPeer(TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject)
            val decoded = json.decodeFromJsonElement(TelefonBestand.serializer(), sanitized).validated()
            fun confirmed(peer: TelefonPeer): TelefonPeer = if (peer.state == "paired")
                peer.copy(own_device = true, remote_own_device = true) else peer
            val current = decoded.copy(peer = decoded.peer?.let(::confirmed),
                other_peers = decoded.other_peers.map(::confirmed))
            if (migrated || current != decoded) savePeers(current)
            current
        } finally { clear.fill(0) }
    }

    @Synchronized
    fun savePeer(peer: TelefonPeer?) {
        savePeers(peers().remember(peer))
    }

    private class FileAuthoritySnapshot(val cipher: ByteArray?, val raw: JsonObject?, val peers: TelefonBestand, val witness: String?)

    /** Transfer authority reads must not enter the normal initialising/migrating
     * phone-store loader. Missing keys/invalid records remain errors, never new
     * identities, replacement keys, migrated grants or rewritten defaults.
     */
    @Synchronized internal fun fileAuthorityPeers(): TelefonBestand = fileAuthoritySnapshot().peers

    private fun existingFileAuthorityKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return store.getKey(KEY_ALIAS, null) as? SecretKey ?: throw DeviceTransferKeyUnavailable()
    }

    private fun fileAuthoritySnapshot(): FileAuthoritySnapshot {
        val key = existingFileAuthorityKey()
        val path = peersFile.toPath()
        if (!Files.exists(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)) return FileAuthoritySnapshot(null, null, TelefonBestand(), null)
        fun attributes() = Files.readAttributes(path, java.nio.file.attribute.BasicFileAttributes::class.java, java.nio.file.LinkOption.NOFOLLOW_LINKS)
        val before = attributes()
        if (!before.isRegularFile || before.fileKey() == null || before.size() !in 1..FILE_AUTHORITY_LIMIT.toLong())
            DeviceFileControl.fail("file_pairing_unsafe_peer_record")
        val bytes = java.nio.channels.FileChannel.open(path, java.nio.file.StandardOpenOption.READ, java.nio.file.LinkOption.NOFOLLOW_LINKS).use { channel ->
            val buffer = java.nio.ByteBuffer.allocate(before.size().toInt() + 1)
            while (buffer.hasRemaining() && channel.read(buffer) != -1) { }
            if (buffer.position() != before.size().toInt()) DeviceFileControl.fail("file_pairing_peer_read_changed")
            buffer.flip(); ByteArray(buffer.remaining()).also { buffer.get(it) }
        }
        val after = attributes()
        if (before.fileKey() != after.fileKey() || before.size() != after.size() || before.lastModifiedTime() != after.lastModifiedTime())
            DeviceFileControl.fail("file_pairing_peer_read_changed")
        val clear = decryptUsingKey(bytes.toString(Charsets.US_ASCII), "peers", "v1", key)
        try {
            val raw = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString(throwOnInvalidSequence = true)) as? JsonObject
                ?: DeviceFileControl.fail("file_pairing_invalid_peer_record")
            val sanitized = sanitizeLegacyPeer(raw).first // Compatibility parsing only: never saved on read.
            val decoded = json.decodeFromJsonElement(TelefonBestand.serializer(), sanitized).validated()
            if (decoded.all().size > 8) DeviceFileControl.fail("file_pairing_peer_limit")
            fun confirmed(peer: TelefonPeer) = if (peer.state == "paired") peer.copy(own_device = true, remote_own_device = true) else peer
            val native = decoded.copy(peer = decoded.peer?.let(::confirmed), other_peers = decoded.other_peers.map(::confirmed))
            return FileAuthoritySnapshot(bytes, raw, native, before.fileKey().toString() + ":" + before.size() + ":" + before.lastModifiedTime())
        } finally { clear.fill(0) }
    }

    private fun sameFileAuthority(first: FileAuthoritySnapshot, second: FileAuthoritySnapshot): Boolean =
        first.witness == second.witness && if (first.cipher == null) second.cipher == null else second.cipher != null && first.cipher.contentEquals(second.cipher)

    /** Explicit authenticated native file-activation path only. Legacy reads do
     * not call this. Establishes relationship metadata, never a file/media grant,
     * source policy, personal-module preference or Android READ permission.
     */
    @Synchronized internal fun initializeFilePairingEpoch(expected: TelefonPeer, permitted: () -> Boolean): TelefonPeer {
        val current = fileAuthoritySnapshot()
        val peer = current.peers.peer ?: DeviceFileControl.fail("file_pairing_native_peer_changed")
        if (peer != expected || peer.state != "paired" || !peer.own_device || !peer.remote_own_device)
            DeviceFileControl.fail("file_pairing_native_peer_changed")
        fun fresh(wanted: FileAuthoritySnapshot) {
            if (!permitted() || !sameFileAuthority(fileAuthoritySnapshot(), wanted)) DeviceFileControl.fail("file_pairing_native_activation_revoked")
        }
        fresh(current)
        if (peer.file_pairing_epoch.isNotEmpty()) return peer
        val epoch = ByteArray(32).also { java.security.SecureRandom().nextBytes(it) }
            .joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }
        val next = peer.copy(file_pairing_epoch = epoch)
        val raw = current.raw ?: DeviceFileControl.fail("file_pairing_invalid_peer_record")
        val rawPeer = raw["peer"] as? JsonObject ?: DeviceFileControl.fail("file_pairing_invalid_peer_record")
        val wanted = JsonObject(raw + ("peer" to JsonObject(rawPeer + ("file_pairing_epoch" to JsonPrimitive(epoch)))))
        val clear = TelefonKanonisch.bytes(wanted)
        val cipher = try { encryptUsingKey(clear, "peers", "v1", existingFileAuthorityKey()).toByteArray(Charsets.US_ASCII) } finally { clear.fill(0) }
        if (cipher.size > FILE_AUTHORITY_LIMIT) DeviceFileControl.fail("file_pairing_peer_limit")
        Files.newDirectoryStream(requireNotNull(peersFile.parentFile).toPath(), peersFile.name + ".file-*.new").use { entries ->
            var held = 0
            for (entry in entries) {
                val value = Files.readAttributes(entry, java.nio.file.attribute.BasicFileAttributes::class.java, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                if (++held >= 4 || !value.isRegularFile || value.size() > FILE_AUTHORITY_LIMIT)
                    DeviceFileControl.fail("file_pairing_native_staging_held")
            }
        }
        // Unique native CREATE_NEW staging: preserve any old generic .new file.
        val temp = File(peersFile.parentFile, peersFile.name + ".file-" + java.util.UUID.randomUUID() + ".new").toPath()
        java.nio.channels.FileChannel.open(temp, setOf<java.nio.file.OpenOption>(java.nio.file.StandardOpenOption.CREATE_NEW, java.nio.file.StandardOpenOption.WRITE,
            java.nio.file.LinkOption.NOFOLLOW_LINKS), java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
            java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"))).use { channel ->
            val buffer = java.nio.ByteBuffer.wrap(cipher)
            while (buffer.hasRemaining()) if (channel.write(buffer) <= 0) DeviceFileControl.fail("file_pairing_stalled_peer_write")
            channel.force(true)
        }
        fresh(current) // Exact native consent and original ciphertext at publication.
        Files.move(temp, peersFile.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner(requireNotNull(peersFile.parentFile))
        val saved = fileAuthoritySnapshot()
        if (saved.raw != wanted || saved.cipher?.contentEquals(cipher) != true || saved.peers.peer != next)
            DeviceFileControl.fail("file_pairing_native_readback_failed")
        fresh(saved) // A lost reply keeps protected metadata, not a send grant.
        return saved.peers.peer!!
    }

    /** Only the completed code-confirmation path may replace this pinned relationship. */
    @Synchronized internal fun replaceConfirmedPeer(expected: TelefonPeer, replacement: TelefonPeer) {
        val current = peers()
        check(current.peer?.device_id == expected.device_id && current.peer.static_public == expected.static_public)
        require(replacement.device_id == expected.device_id && replacement.state == "paired_unverified")
        savePeers(current.remember(null).remember(replacement))
        // Confirmation replaces transport trust, not the user's saved choices.
        // The new peer receives fresh grants only after its finish proof.
    }

    @Synchronized
    fun revokeTimeSync(): Set<String> {
        val current = peers()
        if (current.all().none { it.personal_time_policy != null }) return emptySet()
        fun paused(peer: TelefonPeer): TelefonPeer = peer.personal_time_policy?.let { policy ->
            peer.copy(personal_time_policy = TimeSyncProtokoll.newSettings(false,
                policy.getValue("revision").jsonPrimitive.long + 1))
        } ?: peer
        savePeers(current.copy(peer = current.peer?.let(::paused), other_peers = current.other_peers.map(::paused)))
        return current.all().mapTo(mutableSetOf()) { it.device_id }
    }

    @Synchronized
    fun enableOwnDeviceTimeSync(): Set<String> {
        val current = peers()
        val ids = mutableSetOf<String>()
        fun enabled(peer: TelefonPeer): TelefonPeer {
            if (!peer.own_device || peer.state != "paired") return peer
            ids.add(peer.device_id)
            val local = peer.personal_time_policy
            if (local?.get("enabled") == JsonPrimitive(true)) return peer
            return peer.copy(personal_time_policy = TimeSyncProtokoll.newSettings(true,
                (local?.get("revision")?.jsonPrimitive?.long ?: 0) + 1))
        }
        val next = current.copy(peer = current.peer?.let(::enabled), other_peers = current.other_peers.map(::enabled))
        if (ids.isNotEmpty()) savePeers(next)
        return ids
    }

    @Synchronized
    fun selectPeer(id: String?) {
        val selected = peers().select(id)
        check(settings.edit().putString("pending_computer_selection", id.orEmpty()).commit())
        savePeers(selected)
        restoreComputerSettings(selected.peer)
    }

    private fun restoreComputerSettings(peer: TelefonPeer?) {
        val edit = settings.edit().putBoolean("personal_sync_own_device", peer?.own_device == true)
            .putBoolean("personal_sync_notes", peer?.personal_notes_sync_granted ?: true)
            .putBoolean("personal_sync_tasks", peer?.personal_tasks_sync_granted ?: true)
            .putBoolean("personal_sync_deletions", peer?.own_device == true && peer.personal_deletions_sync_granted)
            .putBoolean("personal_sync_auto_wifi", peer?.saved_auto_wifi ?: true)
            .putBoolean("bluetooth_enabled", peer?.saved_bluetooth == true)
            .putLong("personal_sync_last_auto", 0).putLong("personal_sync_last_counter", -1)
            .putString("personal_sync_report", "").remove("pending_computer_selection")
        if (peer == null) edit.remove("personal_sync_deletions")
        check(edit.commit())
    }

    private fun savePeers(value: TelefonBestand) {
        val clear = json.encodeToString(TelefonBestand.serializer(), value.validated()).toByteArray()
        try { atomic(peersFile, encrypt(clear, "peers", "v1").toByteArray()) } finally { clear.fill(0) }
    }

    override fun encryptPayload(clear: ByteArray, type: String, id: String): ByteArray =
        encrypt(clear, type, id).toByteArray(Charsets.US_ASCII)

    override fun decryptPayload(value: ByteArray, type: String, id: String): ByteArray =
        decrypt(value.toString(Charsets.US_ASCII), type, id)

    private fun encrypt(clear: ByteArray, type: String, id: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD("magnolie-phone-storage-v1\u0000$type$id".toByteArray())
        return Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(clear))
    }

    private fun encryptUsingKey(clear: ByteArray, type: String, id: String, existingKey: SecretKey): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, existingKey)
        cipher.updateAAD("magnolie-phone-storage-v1\u0000$type$id".toByteArray())
        return Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(clear))
    }

    private fun decrypt(value: String, type: String, id: String): ByteArray {
        val raw = Base64.getDecoder().decode(value)
        if (raw.size < 29) throw TelefonProtokollFehler("Telefonablage ist beschädigt.")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw.copyOfRange(0, 12)))
        cipher.updateAAD("magnolie-phone-storage-v1\u0000$type$id".toByteArray())
        return cipher.doFinal(raw.copyOfRange(12, raw.size))
    }

    private fun decryptUsingKey(value: String, type: String, id: String, existingKey: SecretKey): ByteArray {
        val raw = Base64.getDecoder().decode(value)
        if (raw.size < 29) throw TelefonProtokollFehler("Telefonablage ist beschädigt.")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, existingKey, GCMParameterSpec(128, raw.copyOfRange(0, 12)))
        cipher.updateAAD("magnolie-phone-storage-v1\u0000$type$id".toByteArray())
        return cipher.doFinal(raw.copyOfRange(12, raw.size))
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setUserAuthenticationRequired(false).build())
        return generator.generateKey()
    }

    private fun atomic(target: File, bytes: ByteArray) {
        val temp = File(target.parentFile, target.name + ".new")
        FileOutputStream(temp).use { it.write(bytes); it.flush(); it.fd.sync() }
        Files.move(temp.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING)
        io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner(requireNotNull(target.parentFile))
    }

    companion object {
        private const val FILE_AUTHORITY_LIMIT = 4 * 1024 * 1024
        const val KEY_ALIAS = "magnolie_phone_storage_v1"
        @Volatile private var instance: TelefonAblage? = null
        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: TelefonAblage(context).also { instance = it }
        }
    }
}

@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
internal fun sanitizeLegacyPeer(value: JsonObject): Pair<JsonObject, Boolean> {
    val topFields = setOf("storage_version", "peer", "other_peers")
    if (!value.keys.containsAll(setOf("storage_version", "peer")) || (value.keys - topFields).isNotEmpty())
        throw TelefonProtokollFehler("Unbekanntes Feld in der Telefonablage.")
    if ("other_peers" in value) {
        val others = value["other_peers"] as? kotlinx.serialization.json.JsonArray
            ?: throw TelefonProtokollFehler("Ungültige Rechnerliste.")
        val active = sanitizeLegacyPeer(JsonObject(value - "other_peers"))
        val normalized = others.map { other ->
            if (other !is JsonObject) throw TelefonProtokollFehler("Ungültige Rechnerliste.")
            sanitizeLegacyPeer(JsonObject(mapOf("storage_version" to value.getValue("storage_version"), "peer" to other)))
        }
        return JsonObject(active.first + ("other_peers" to kotlinx.serialization.json.JsonArray(normalized.map { it.first.getValue("peer") }))) to
            (active.second || normalized.any { it.second })
    }
    val peer = value["peer"] as? JsonObject ?: return value to false
    val descriptor = TelefonPeer.serializer().descriptor
    val current = (0 until descriptor.elementsCount).map(descriptor::getElementName).toSet()
    val legacy = setOf("remote_sms_send_granted", "remote_sms_send_available")
    if ((peer.keys - current - legacy).isNotEmpty())
        throw TelefonProtokollFehler("Unbekanntes Feld in der Telefonablage.")
    for (name in listOf("personal_note_policy", "remote_personal_note_policy")) {
        val policy = peer[name]
        if (policy != null && policy != kotlinx.serialization.json.JsonNull)
            PersonalNoteMode.validate(policy as? JsonObject ?: throw TelefonProtokollFehler("Ungültige Notizrichtung."))
    }
    peer["remote_desktop_features"]?.takeUnless { it == kotlinx.serialization.json.JsonNull }?.let {
        PersonalDesktopFeatures.validate(it as? JsonObject ?: throw TelefonProtokollFehler("Ungültige Desktop-Funktionen."))
    }
    for (name in listOf("personal_time_policy", "remote_personal_time_policy")) {
        peer[name]?.takeUnless { it == kotlinx.serialization.json.JsonNull }?.let {
            TimeSyncProtokoll.settings(it as? JsonObject ?: throw TelefonProtokollFehler("Ungültige Zeiterfassungsfreigabe."))
        }
    }
    val sanitized = peer.filterKeys { it !in legacy }.toMutableMap()
    var migrated = peer.keys.any { it in legacy }
    for (name in setOf("remote_incoming_call_number_granted", "remote_end_call_granted",
            "remote_end_call_available", "own_device", "remote_own_device",
            "personal_notes_sync_granted", "personal_tasks_sync_granted",
            "personal_deletions_sync_granted", "remote_personal_notes_sync_granted",
            "remote_personal_tasks_sync_granted", "remote_personal_deletions_sync_granted")) {
        if (name !in sanitized) {
            sanitized[name] = kotlinx.serialization.json.JsonPrimitive(false)
            migrated = true
        }
    }
    return if (migrated) JsonObject(value + ("peer" to JsonObject(sanitized))) to true else value to false
}
