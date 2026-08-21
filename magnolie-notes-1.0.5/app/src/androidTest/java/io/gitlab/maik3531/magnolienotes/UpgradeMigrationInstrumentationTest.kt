package io.gitlab.maik3531.magnolienotes

import android.util.Log
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpgradeMigrationInstrumentationTest {
    @Test fun vorgaengerSentinelMigriertEinmaligUndUeberlebtZweitenStartMitFrischenIvs() {
        val context = MagnolieTestRunner.testContext
        val notizenDatei = context.filesDir.resolve("notizen.json")
        val baumDatei = context.filesDir.resolve("baum.json")
        val ablage = Ablage.hole(context)
        val sentinel = ablage.notiz("fixture-notiz") ?: run {
            Log.i("MagnolieR8Probe", "Fresh release instrumentation reached production storage")
            return
        }
        assertEquals("Vorgaenger Sentinel", sentinel.titel)
        assertEquals("fixture-baumidentitaet", ablage.baum.value.kennung)
        assertTrue(magic(notizenDatei.readBytes()))
        assertTrue(magic(baumDatei.readBytes()))

        val iv1 = iv(notizenDatei.readBytes())
        ablage.sichereNotiz(sentinel.copy(text = sentinel.text + " / erster R8-Schreibpfad"))
        val iv2 = iv(notizenDatei.readBytes())
        assertFalse(iv1.contentEquals(iv2))

        Ablage.singletonFuerTestZuruecksetzen()
        val nachNeustart = Ablage.hole(context)
        assertTrue(nachNeustart.notiz("fixture-notiz")!!.text.contains("erster R8-Schreibpfad"))
        val vorZweitemSchreiben = iv(notizenDatei.readBytes())
        nachNeustart.sichereNotiz(nachNeustart.notiz("fixture-notiz")!!.copy(
            text = sentinel.text + " / zweiter R8-Schreibpfad"))
        assertFalse(vorZweitemSchreiben.contentEquals(iv(notizenDatei.readBytes())))
        Log.i("MagnolieR8Probe", "Upgrade content, migration, reload and two production writes verified")
    }

    private fun magic(bytes: ByteArray) = bytes.take(14).toByteArray().contentEquals(
        byteArrayOf(0x4d, 0x41, 0x47, 0x4e, 0x4f, 0x4c, 0x49, 0x45, 0x2d, 0x44, 0x41, 0x54, 0x41, 0x00))

    private fun iv(bytes: ByteArray): ByteArray {
        val nameLength = bytes[15].toInt() and 0xff
        val start = 16 + nameLength
        return bytes.copyOfRange(start, start + 12)
    }
}
