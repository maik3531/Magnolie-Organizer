package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal class DeviceTransferKeyUnavailable : IOException("Existing phone storage key is unavailable.")

/** New transfer storage must never recreate a missing existing phone key.
 * No TelefonAblage constructor, KeyGenerator, key deletion or settings migration.
 * This object supplies protection only, never native consent/peer authority.
 */
internal class DeviceTransferProtection private constructor(private val existingKey: () -> SecretKey?) {
    private fun key(): SecretKey = existingKey() ?: throw DeviceTransferKeyUnavailable()
    private fun aad(domain: String): ByteArray {
        require(domain.length in 1..1024 && domain.all { it.code in 33..126 && it != '\\' })
        return ("magnolie-phone-storage-v1\u0000device_file_transfer_v1\u0000" + domain).toByteArray(Charsets.UTF_8)
    }

    fun seal(clear: ByteArray, domain: String): ByteArray {
        require(clear.size in 1..MAX_CLEAR_BYTES)
        val context = aad(domain)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        check(cipher.iv.size == 12)
        cipher.updateAAD(context)
        val owned = clear.copyOf()
        return try { cipher.iv + cipher.doFinal(owned) } finally { owned.fill(0) }
    }

    fun open(blob: ByteArray, domain: String): ByteArray {
        require(blob.size in 29..MAX_CLEAR_BYTES + 28)
        val context = aad(domain)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, blob.copyOfRange(0, 12)))
        cipher.updateAAD(context)
        return cipher.doFinal(blob.copyOfRange(12, blob.size))
    }

    companion object {
        const val MAX_CLEAR_BYTES = 2 * 1024 * 1024

        fun fromExistingAndroidPhoneKey() = DeviceTransferProtection {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            store.getKey(TelefonAblage.KEY_ALIAS, null) as? SecretKey
        }

        // Native/test injection of an EXISTING key reader, never a wire object.
        internal fun fromExistingKeyReader(read: () -> SecretKey?) = DeviceTransferProtection(read)
    }
}
