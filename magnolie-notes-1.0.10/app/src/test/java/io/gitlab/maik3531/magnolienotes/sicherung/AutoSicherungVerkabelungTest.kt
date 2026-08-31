package io.gitlab.maik3531.magnolienotes.sicherung

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoSicherungVerkabelungTest {
    private val android = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/sicherung/AndroidAutoSicherung.kt").readText()
    private val kern = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/sicherung/AutoSicherungKern.kt").readText()
    private val activity = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()

    @Test fun `persistierte Schreib und Lesefreigabe wird gesetzt und vor jedem Lauf geprueft`() {
        assertTrue(activity.contains("ActivityResultContracts.OpenDocumentTree()"))
        assertTrue(android.contains("takePersistableUriPermission"))
        assertTrue(android.contains("persistedUriPermissions.any"))
        assertTrue(android.contains("it.isReadPermission && it.isWritePermission"))
        assertTrue(android.contains("if (!freigabeVorhanden(uri))"))
    }

    @Test fun `eindeutige periodische Arbeit hat echte Tages und Wochenperioden sowie Bedingungen`() {
        assertTrue(android.contains("enqueueUniquePeriodicWork(PERIODIC_WORK"))
        assertTrue(android.contains("PeriodicWorkRequestBuilder<AutoSicherungsWorker>(tage, TimeUnit.DAYS)"))
        assertTrue(kern.contains("TAEGLICH(1), WOECHENTLICH(7)"))
        assertTrue(android.contains("NetworkType.CONNECTED"))
        assertTrue(android.contains("setRequiresBatteryNotLow(true)"))
        assertTrue(android.contains("setRequiresStorageNotLow(true)"))
        assertTrue(android.contains("cancelUniqueWork(PERIODIC_WORK)"))
        assertFalse(android.contains("15, TimeUnit.MINUTES"))
        assertEquals(1, Regex("Result\\.retry\\(\\)").findAll(android).count())
    }

    @Test fun `Passwort liegt nur als Keystore Huelle und Erfolg erst nach Readback vor`() {
        assertTrue(android.contains("automatische_portable_sicherung_geheim"))
        assertTrue(android.contains("PasswortHuelle.sichern"))
        assertTrue(android.contains("PortableArchiv.pruefen(it, passwort)"))
        assertTrue(kern.contains("authentifizieren(gelesen)"))
        assertTrue(kern.indexOf("authentifizieren(gelesen)") < kern.indexOf("nachErfolg()"))
        assertFalse(android.contains("putString(KEY_HUELLE, passwort"))
        assertFalse(android.contains("Log."))
    }
}
