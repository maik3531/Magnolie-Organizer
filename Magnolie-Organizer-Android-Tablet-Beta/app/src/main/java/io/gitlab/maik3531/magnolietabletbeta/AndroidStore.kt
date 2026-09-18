package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.concurrent.Executors
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

internal object AndroidStore {
    val io = Executors.newSingleThreadExecutor()
    private var instance: Vault? = null
    @Synchronized fun vault(context: Context): Vault {
        instance?.let { return it }
        val dir = context.noBackupFilesDir
        val alias = "magnolie-organizer-tablet-beta-vault-v1"
        val vault = Vault(dir, {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey(alias, null) as? SecretKey) ?: run {
                check(dir.listFiles().orEmpty().none { it.name.endsWith(".enc") || it.name.endsWith(".pending") }) {
                    "Missing key for existing ciphertext; refusing reset"
                }
                KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                    init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256).setRandomizedEncryptionRequired(true).build())
                }.generateKey()
            }
        })
        instance = vault
        return vault
    }
}
