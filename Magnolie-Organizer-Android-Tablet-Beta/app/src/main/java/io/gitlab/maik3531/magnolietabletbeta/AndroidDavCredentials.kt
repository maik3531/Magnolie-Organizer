package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Uses the same AES-GCM/non-exportable AndroidKeyStore strategy as AndroidStore, with a
 * separate credential alias and no-backup subdirectory. No organizer export can include it.
 */
internal object AndroidDavCredentials {
    private var instance: DavCredentialStore? = null
    @Synchronized fun store(context: Context): DavCredentialStore {
        instance?.let { return it }
        val ops = AndroidOsStorageFileOps
        val parent = ops.ensurePrivateDirectory(context.noBackupFilesDir)
        val directory = File(parent, "dav-credentials-v1")
        val alias = "magnolie-organizer-tablet-beta-dav-credentials-v1"
        val credentials = DavCredentialStore(directory, {
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (keyStore.getKey(alias, null) as? SecretKey) ?: run {
                if (ops.children(directory).any { it.name.endsWith(".enc") || it.name.endsWith(".pending") }) {
                    throw DavCredentialException("missing_key_existing_credentials")
                }
                KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                    init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256).setRandomizedEncryptionRequired(true).build())
                }.generateKey()
            }
        }, fileOps = ops)
        instance = credentials
        return credentials
    }
}
