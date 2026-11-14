package io.gitlab.maik3531.magnolienotes.baum

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Protection, not permission. The durable native decision store must validate
 * its setup witness independently before key rotation or approval publication.
 * Ordinary reads never initialize/repair/migrate keys and have no fallback to
 * the phone/tree/portable-book key. Only a genuine explicit decision may rotate.
 */
internal class KontaktOriginalSchutz private constructor(
    private val vorhandenerKey: () -> SecretKey?,
    private val neuerKey: () -> Unit,
    private val entferneKey: () -> Unit
) {
    private val cipher = DatenDateiKrypto({ vorhandenerKey() ?: error("contact_original_key_unavailable") })

    fun oeffnen(blob: ByteArray): ByteArray {
        require(blob.size in 1..MAX_BYTES + 1024)
        return cipher.entschluesseln(blob, DOMAIN).also { require(it.size in 1..MAX_BYTES) }
    }

    fun verschliessen(clear: ByteArray): ByteArray {
        klartextPruefen(clear)
        val owned = clear.copyOf()
        return try { cipher.verschluesseln(owned, DOMAIN) } finally { owned.fill(0) }
    }

    internal fun klartextPruefen(clear: ByteArray) { require(clear.size in 1..MAX_BYTES) }

    internal fun neuerEntscheidungsschluessel() = neuerKey()
    internal fun schluesselWiderrufen() = entferneKey()

    companion object {
        private const val KEY_ALIAS = "magnolie_contact_original_consent_v1"
        private const val DOMAIN = "kontakt-original-freigaben-v1"
        private const val MAX_BYTES = 256 * 1024

        fun android(): KontaktOriginalSchutz {
            fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            return KontaktOriginalSchutz(
                { store().getKey(KEY_ALIAS, null) as? SecretKey },
                {
                    val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
                    generator.init(KeyGenParameterSpec.Builder(KEY_ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256).setUserAuthenticationRequired(false).build())
                    generator.generateKey()
                    Unit
                },
                { store().deleteEntry(KEY_ALIAS) }
            )
        }

        internal fun fuerTest(existing: () -> SecretKey?, rotate: () -> Unit, revoke: () -> Unit) =
            KontaktOriginalSchutz(existing, rotate, revoke)
    }
}
