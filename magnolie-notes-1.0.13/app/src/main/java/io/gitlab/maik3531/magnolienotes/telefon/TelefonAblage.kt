package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
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
    fun selectedPackages(): Set<String> = settings.getStringSet("notification_packages", emptySet())?.toSet().orEmpty()
    fun setDialRequestEnabled(value: Boolean) { settings.edit().putBoolean("dial_request_enabled", value).commit() }
    fun setNotificationsEnabled(value: Boolean) { settings.edit().putBoolean("notifications_enabled", value).commit() }
    fun setIncomingCallsEnabled(value: Boolean) { settings.edit().putBoolean("incoming_calls_enabled", value).commit() }
    fun setIncomingNumberEnabled(value: Boolean) { settings.edit().putBoolean("incoming_number_enabled", value).commit() }
    fun setAnswerCallsEnabled(value: Boolean) { settings.edit().putBoolean("answer_calls_enabled", value).commit() }
    fun setSelectedPackages(value: Set<String>) { settings.edit().putStringSet("notification_packages", value).commit() }
    fun personalOwnDevice(): Boolean = settings.getBoolean("personal_sync_own_device", false)
    fun personalNotesEnabled(): Boolean = settings.getBoolean("personal_sync_notes", false)
    fun personalTasksEnabled(): Boolean = settings.getBoolean("personal_sync_tasks", false)
    fun personalAutoWifi(): Boolean = settings.getBoolean("personal_sync_auto_wifi", false)
    fun personalDeletionsEnabled(): Boolean = settings.getBoolean("personal_sync_deletions", false)
    fun personalSyncReport(): String = settings.getString("personal_sync_report", "").orEmpty()
    fun personalSyncLastAuto(): Long = settings.getLong("personal_sync_last_auto", 0)
    fun setPersonalSyncLastAuto(value: Long) { settings.edit().putLong("personal_sync_last_auto", value).commit() }
    fun personalSyncLastCounter(): Long = settings.getLong("personal_sync_last_counter", -1)
    fun setPersonalSyncLastCounter(value: Long) { settings.edit().putLong("personal_sync_last_counter", value).commit() }
    fun setPersonalSync(own: Boolean, notes: Boolean, tasks: Boolean, autoWifi: Boolean,
                        deletions: Boolean = personalDeletionsEnabled()) {
        settings.edit().putBoolean("personal_sync_own_device", own)
            .putBoolean("personal_sync_notes", own && notes)
            .putBoolean("personal_sync_tasks", own && tasks)
            .putBoolean("personal_sync_auto_wifi", own && autoWifi)
            .putBoolean("personal_sync_deletions", own && deletions).commit()
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
            json.decodeFromJsonElement(TelefonBestand.serializer(), sanitized).also {
                if (migrated) savePeer(it.peer)
            }
        } finally { clear.fill(0) }
    }

    @Synchronized
    fun savePeer(peer: TelefonPeer?) {
        val clear = json.encodeToString(TelefonBestand.serializer(), TelefonBestand(peer = peer)).toByteArray()
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

    private fun decrypt(value: String, type: String, id: String): ByteArray {
        val raw = Base64.getDecoder().decode(value)
        if (raw.size < 29) throw TelefonProtokollFehler("Telefonablage ist beschädigt.")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw.copyOfRange(0, 12)))
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
        const val KEY_ALIAS = "magnolie_phone_storage_v1"
        @Volatile private var instance: TelefonAblage? = null
        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: TelefonAblage(context).also { instance = it }
        }
    }
}

@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
internal fun sanitizeLegacyPeer(value: JsonObject): Pair<JsonObject, Boolean> {
    val topFields = setOf("storage_version", "peer")
    if (value.keys != topFields) throw TelefonProtokollFehler("Unbekanntes Feld in der Telefonablage.")
    val peer = value["peer"] as? JsonObject ?: return value to false
    val descriptor = TelefonPeer.serializer().descriptor
    val current = (0 until descriptor.elementsCount).map(descriptor::getElementName).toSet()
    val legacy = setOf("remote_sms_send_granted", "remote_sms_send_available")
    if ((peer.keys - current - legacy).isNotEmpty())
        throw TelefonProtokollFehler("Unbekanntes Feld in der Telefonablage.")
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
