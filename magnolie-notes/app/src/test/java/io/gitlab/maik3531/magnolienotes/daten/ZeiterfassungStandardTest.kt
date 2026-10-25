package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class ZeiterfassungStandardTest {
    private fun fixture(test: (Context, File, SecretKey) -> Unit) {
        val directory = Files.createTempDirectory("magnolie-time-default-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        try { test(context, directory, key) } finally { directory.deleteRecursively() }
    }

    @Test fun freshStorageEnablesTheFeatureWithoutStartingARecordOrWifiAutomation() = fixture { context, _, key ->
        val storage = Ablage.fuerTest(context) { key }
        val state = storage.bestand.value.zeiterfassung
        assertTrue(state.enabled)
        assertTrue(state.entries.isEmpty()); assertTrue(state.controlReceipts.isEmpty())
        assertFalse(state.wifi.enabled); assertEquals(ZeitFeierabendwecker(), state.endAlarm)
        assertTrue(Ablage.fuerTest(context) { key }.bestand.value.zeiterfassung.enabled)
    }

    @Test fun anExplicitOptOutSurvivesEncryptedRestart() = fixture { context, directory, key ->
        val storage = Ablage.fuerTest(context) { key }
        assertTrue(storage.bestand.value.zeiterfassung.enabled)
        storage.aendereZeiterfassung { it.copy(enabled = false) }
        assertTrue(File(directory, "notizen.json").isFile)
        assertFalse(Ablage.fuerTest(context) { key }.bestand.value.zeiterfassung.enabled)
    }

    @Test fun oldMissingFieldsRemainDisabledDuringMigrationAndRestart() {
        for (legacy in listOf("{}", "{\"zeiterfassung\":{}}")) fixture { context, directory, key ->
            File(directory, "notizen.json").writeText(legacy)
            val storage = Ablage.fuerTest(context) { key }
            assertFalse(storage.bestand.value.zeiterfassung.enabled)
            assertFalse(Ablage.fuerTest(context) { key }.bestand.value.zeiterfassung.enabled)
        }
    }

    @Test fun restoringADisabledSnapshotDoesNotApplyTheFreshInstallDefault() = fixture { context, _, key ->
        val storage = Ablage.fuerTest(context) { key }
        assertTrue(storage.bestand.value.zeiterfassung.enabled)
        val snapshot = Ablage.json.encodeToString(Bestand.serializer(), Bestand())
        assertTrue(storage.journalWiederherstellen(snapshot, storage.journalNutzlast().second, "owned-default-restore"))
        assertFalse(storage.bestand.value.zeiterfassung.enabled)
        assertFalse(Ablage.fuerTest(context) { key }.bestand.value.zeiterfassung.enabled)
    }

    @Test fun damagedExistingDataIsNotReplacedByANewEnabledEmptyBook() = fixture { context, directory, key ->
        val file = File(directory, "notizen.json")
        val before = "owned invalid existing data".toByteArray()
        file.writeBytes(before)
        assertTrue(runCatching { Ablage.fuerTest(context) { key } }.isFailure)
        assertArrayEquals(before, file.readBytes())
    }
}
