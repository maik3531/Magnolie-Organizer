package io.gitlab.maik3531.magnolienotes.daten

import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Binaeres, selbstkennzeichnendes Format fuer die privaten Hauptdateien. */
internal class DatenDateiKrypto(
    private val key: () -> SecretKey,
    private val random: SecureRandom = SecureRandom()
) {
    private var letzteIv: ByteArray? = null

    fun istVerschluesselt(bytes: ByteArray): Boolean =
        bytes.size >= MAGIC.size && bytes.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)

    fun schluesselPruefen() {
        key()
    }

    @Synchronized
    fun verschluesseln(klartext: ByteArray, dateiname: String): ByteArray {
        val name = dateiname.toByteArray(Charsets.UTF_8)
        require(name.isNotEmpty() && name.size <= 255)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val schluessel = key()
        // AndroidKeyStore verbietet caller-provided IVs. Software-Schluessel
        // behalten einen injizierbaren SecureRandom fuer deterministische Tests.
        if (schluessel.format == null) cipher.init(Cipher.ENCRYPT_MODE, schluessel)
        else cipher.init(Cipher.ENCRYPT_MODE, schluessel, random)
        val iv = requireNotNull(cipher.iv) { "GCM-Provider lieferte keine IV" }.copyOf()
        require(iv.size == IV_BYTES) { "GCM-Provider lieferte eine ungueltige IV" }
        check(letzteIv?.contentEquals(iv) != true) { "GCM-IV wurde wiederverwendet" }
        letzteIv = iv.copyOf()
        val kopf = MAGIC + byteArrayOf(VERSION, name.size.toByte()) + name + iv
        cipher.updateAAD(kopf)
        return kopf + cipher.doFinal(klartext)
    }

    fun entschluesseln(datei: ByteArray, erwarteterDateiname: String): ByteArray {
        require(istVerschluesselt(datei)) { "Unbekanntes Datenformat" }
        val fest = MAGIC.size
        require(datei.size >= fest + 2 + IV_BYTES + TAG_BYTES)
        require(datei[fest] == VERSION) { "Nicht unterstuetzte Datenformatversion" }
        val nameLaenge = datei[fest + 1].toInt() and 0xff
        val kopfLaenge = fest + 2 + nameLaenge + IV_BYTES
        require(nameLaenge > 0 && datei.size >= kopfLaenge + TAG_BYTES)
        val name = String(datei, fest + 2, nameLaenge, Charsets.UTF_8)
        require(name == erwarteterDateiname) { "Daten-Dateiname stimmt nicht" }
        val ivStart = fest + 2 + nameLaenge
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(),
            GCMParameterSpec(TAG_BITS, datei.copyOfRange(ivStart, kopfLaenge)))
        cipher.updateAAD(datei.copyOfRange(0, kopfLaenge))
        return cipher.doFinal(datei.copyOfRange(kopfLaenge, datei.size))
    }

    companion object {
        private val MAGIC = byteArrayOf(
            0x4d, 0x41, 0x47, 0x4e, 0x4f, 0x4c, 0x49, 0x45,
            0x2d, 0x44, 0x41, 0x54, 0x41, 0x00
        )
        private const val VERSION: Byte = 1
        private const val IV_BYTES = 12
        private const val TAG_BYTES = 16
        private const val TAG_BITS = 128
    }
}
