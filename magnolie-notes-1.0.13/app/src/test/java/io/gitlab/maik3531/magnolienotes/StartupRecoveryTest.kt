package io.gitlab.maik3531.magnolienotes

import android.system.ErrnoException
import android.system.OsConstants
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import io.gitlab.maik3531.magnolienotes.daten.StartFehlerArt
import io.gitlab.maik3531.magnolienotes.daten.startFehler
import java.io.File
import java.io.IOException
import javax.crypto.AEADBadTagException
import javax.crypto.spec.SecretKeySpec
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import kotlinx.coroutines.async
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StartupRecoveryTest {
    @Test fun `early system entry cannot wait forever on a replaced startup signal`() = runBlocking {
        val barrier = StartBarriere<Unit> { StartFehlerArt.UNBEKANNTES_FORMAT }
        val early = async(start = CoroutineStart.UNDISPATCHED) { barrier.awaitReady() }
        try {
            barrier.starten(this, initialisieren = { Unit })
            assertTrue(withTimeout(1000) { early.await() })
        } finally { early.cancel() }
    }
    @Test fun `bereit folgt erst auf vollstaendige Initialisierung und awaitReady`() = runBlocking {
        val weiter = CompletableDeferred<Unit>()
        val barriere = StartBarriere<Unit> { StartFehlerArt.UNBEKANNTES_FORMAT }
        barriere.starten(this, initialisieren = { weiter.await() })
        assertEquals(StartZustand.Laden, barriere.zustand.value)
        assertTrue(barriere.startLaeuft)
        weiter.complete(Unit)
        assertTrue(barriere.awaitReady())
        yield()
        assertEquals(StartZustand.Bereit, barriere.zustand.value)
        assertFalse(barriere.startLaeuft)
    }

    @Test fun `Exception bleibt strukturiert und Retry ist moeglich`() = runBlocking {
        val barriere = StartBarriere<Unit> { startFehler(it).art }
        barriere.starten(this, initialisieren = { throw IOException("kaputt") })
        assertFalse(barriere.awaitReady())
        assertEquals(StartZustand.Fehler(StartFehlerArt.EINGABE_AUSGABE), barriere.zustand.value)
        assertFalse(barriere.startLaeuft)
        barriere.starten(this, initialisieren = { Unit })
        assertTrue(barriere.awaitReady())
        assertEquals(StartZustand.Bereit, barriere.zustand.value)
    }

    @Test fun `alle Ciphertext Commitnamen sperren neue Schluesselerzeugung`() {
        val ordner = kotlin.io.path.createTempDirectory("magnolie-candidates").toFile()
        val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val namen = listOf(
            "notizen.json", "baum.json", "notizen.json.neu", "baum.json.neu",
            "notizen.json.restore", "baum.json.restore", "notizen.json.restore-install",
            "baum.json.restore-install", "notizen.json.pending", "baum.json.pending",
            "notizen.json.backup", "baum.json.bak", "paircommit-notizen.backup"
        )
        try {
            namen.forEach { name ->
                ordner.listFiles().orEmpty().forEach(File::delete)
                val datei = File(ordner, name)
                datei.writeBytes(DatenDateiKrypto({ key }).verschluesseln("{}".toByteArray(), name))
                val vorher = datei.readBytes()
                assertTrue(name, Ablage.enthaeltKryptoBestand(ordner))
                assertTrue(name, vorher.contentEquals(datei.readBytes()))
            }
        } finally {
            ordner.deleteRecursively()
        }
    }

    @Test fun `startfehler unterscheiden tamper format io und enospc`() {
        assertEquals(StartFehlerArt.MANIPULATION, startFehler(AEADBadTagException()).art)
        assertEquals(StartFehlerArt.UNBEKANNTES_FORMAT, startFehler(IllegalArgumentException()).art)
        assertEquals(StartFehlerArt.EINGABE_AUSGABE, startFehler(IOException()).art)
        assertEquals(StartFehlerArt.SPEICHER_VOLL,
            startFehler(ErrnoException("write", OsConstants.ENOSPC)).art)
    }
}
