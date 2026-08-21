package io.gitlab.maik3531.magnolienotes.daten

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import io.gitlab.maik3531.magnolienotes.MagnolieTestRunner
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.File
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec

class AndroidKeyStoreDatenTest {
    private val alias = "magnolie-instrumentation-${System.nanoTime()}"
    private lateinit var ordner: File

    @Before fun setUp() {
        ordner = MagnolieTestRunner.testContext.filesDir
        datenDateien().forEach { it.delete() }
        keyStore().deleteEntry(alias)
    }

    @After fun tearDown() {
        datenDateien().forEach { it.delete() }
        keyStore().deleteEntry(alias)
    }

    @Test fun androidKeyStoreErzeugtFrischeIvUndErkenntManipulation() {
        val crypto = DatenDateiKrypto(::key)
        val klar = "geschuetzter Bestand".toByteArray()
        val eins = crypto.verschluesseln(klar, "notizen.json")
        val zwei = crypto.verschluesseln(klar, "notizen.json")
        assertFalse(eins.contentEquals(zwei))
        Log.i("MagnolieNachherProbe", "AndroidKeyStore provider IV accepted; ciphertext IVs differ")
        assertTrue(crypto.entschluesseln(eins, "notizen.json").contentEquals(klar))
        val manipuliert = eins.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
        try {
            crypto.entschluesseln(manipuliert, "notizen.json")
            fail("Manipulation wurde akzeptiert")
        } catch (_: Exception) {
        }
    }

    @Test fun callerProvidedIvReproduziertAltenProduktionsfehler() {
        val iv = ByteArray(12)
        try {
            Cipher.getInstance("AES/GCM/NoPadding").init(
                Cipher.ENCRYPT_MODE, key(), GCMParameterSpec(128, iv))
            fail("AndroidKeyStore hat eine caller-provided IV akzeptiert")
        } catch (fehler: Exception) {
            Log.e("MagnolieVorherProbe", "Alter Produktionspfad abgewiesen", fehler)
            assertTrue(generateSequence<Throwable>(fehler) { it.cause }
                .any { it.message.orEmpty().contains("Caller-provided IV not permitted") })
        }
    }

    @Test fun klartextmigrationUndZweiterStartMitAndroidKeyStore() {
        ordner.resolve("notizen.json").writeText("{}")
        ordner.resolve("baum.json").writeText("{}")
        val context = MagnolieTestRunner.testContext
        Ablage.fuerTest(context, ::key)
        val crypto = DatenDateiKrypto(::key)
        assertTrue(crypto.istVerschluesselt(ordner.resolve("notizen.json").readBytes()))
        assertTrue(crypto.istVerschluesselt(ordner.resolve("baum.json").readBytes()))
        Ablage.fuerTest(context, ::key)
    }

    @Test fun fehlenderAliasLaesstCiphertextUnveraendert() {
        val datei = ordner.resolve("notizen.json")
        datei.writeBytes(DatenDateiKrypto(::key).verschluesseln("{}".toByteArray(), datei.name))
        val vorher = datei.readBytes()
        keyStore().deleteEntry(alias)
        try {
            DatenDateiKrypto(key = { keyStore().getKey(alias, null) as SecretKey })
                .entschluesseln(vorher, datei.name)
            fail("Fehlender Alias wurde akzeptiert")
        } catch (_: Exception) {
        }
        assertTrue(vorher.contentEquals(datei.readBytes()))
    }

    @Test fun produktiverAliasverlustVorMoveBlockiertNeuenAliasUndJedeRecoveryAenderung() {
        val produktiv = "magnolie-hauptdaten-v1"
        keyStore().deleteEntry(produktiv)
        val crashDatei = ordner.resolve("notizen.json.restore-install")
        crashDatei.writeBytes(DatenDateiKrypto({ key(produktiv) })
            .verschluesseln("{\"notizen\":[]}".toByteArray(), "notizen.json"))
        val vorher = crashDatei.readBytes()
        keyStore().deleteEntry(produktiv)
        Ablage.singletonFuerTestZuruecksetzen()

        try {
            Ablage.hole(MagnolieTestRunner.testContext)
            fail("Produktiver Aliasverlust wurde akzeptiert")
        } catch (fehler: StartFehler) {
            assertEquals(StartFehlerArt.ALIAS_FEHLT, fehler.art)
        }
        assertFalse(keyStore().containsAlias(produktiv))
        assertTrue(vorher.contentEquals(crashDatei.readBytes()))
        assertEquals("ALIAS_FEHLT", ordner.resolve("alias-fehlt.recovery").readText().trim())
    }

    @Test fun beschaedigterPendingmarkerBleibtUnveraendert() {
        val marker = ordner.resolve("wiederherstellung.pending")
        val kaputt = "%%%kein-base64%%%".toByteArray()
        marker.writeBytes(kaputt)
        try {
            WiederherstellungsPaarCommit(ordner).wiederaufnehmen()
            fail("Beschaedigter Marker wurde akzeptiert")
        } catch (fehler: StartFehler) {
            assertEquals(StartFehlerArt.RECOVERY, fehler.art)
        }
        assertTrue(kaputt.contentEquals(marker.readBytes()))
    }

    private fun key(): SecretKey = key(alias)

    private fun key(name: String): SecretKey {
        (keyStore().getKey(name, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(name,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build())
            generateKey()
        }
    }

    private fun keyStore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun datenDateien() = listOf(
        "notizen.json", "baum.json", "notizen.json.neu", "baum.json.neu",
        "notizen.json.restore", "baum.json.restore", "notizen.json.restore-install",
        "baum.json.restore-install", "wiederherstellung.pending", "alias-fehlt.recovery"
    ).map(ordner::resolve)
}
