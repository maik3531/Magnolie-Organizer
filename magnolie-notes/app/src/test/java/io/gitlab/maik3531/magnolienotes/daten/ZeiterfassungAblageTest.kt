package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class ZeiterfassungAblageTest {
    @Test fun runningPauseSurvivesEncryptedRestartAndDisabledFeature() {
        val directory = Files.createTempDirectory("magnolie-time-record-").toFile()
        try {
            val base: Context = ApplicationProvider.getApplicationContext()
            val context = object : ContextWrapper(base) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = directory
            }
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val original = Zeiteintrag(startMinute = 1000000L, zone = "Europe/Berlin", note = "Synthetic private activity")
            val first = Ablage.fuerTest(context) { key }
            first.aendereZeiterfassung { it.copy(enabled = true).start(original) }
            val started = first.bestand.value.zeiterfassung.entries.single()
            first.aendereZeiterfassung { it.replace(started, started.pause(1000120L)) }
            first.aendereZeiterfassung { it.copy(enabled = false) }
            assertFalse(File(directory, "notizen.json").readBytes().toString(Charsets.UTF_8).contains(original.note))
            val restarted = Ablage.fuerTest(context) { key }
            val paused = restarted.bestand.value.zeiterfassung.entries.single()
            assertEquals(first.bestand.value.zeiterfassung, restarted.bestand.value.zeiterfassung)
            assertEquals(1000120L, paused.pauseMinute)
            assertEquals(120L, paused.totalMinutes(1000150L))
            restarted.aendereZeiterfassung { it.replace(paused, paused.finish(1000180L)) }
            val finished = restarted.bestand.value.zeiterfassung.entries.single()
            assertEquals(60L, finished.pauseMinutes)
            assertEquals(120L, finished.totalMinutes())
            assertEquals(3L, restarted.bestand.value.zeiterfassung.counter)
            assertEquals(restarted.bestand.value.zeiterfassung, Ablage.fuerTest(context) { key }.bestand.value.zeiterfassung)
            val draft = ZeitEntwurf(finished, note = "Synthetic unsaved private time note", pause = "invalid raw edit")
            restarted.setzeZeitEntwurf(draft)
            restarted.sichereEntwurf()
            assertFalse(File(directory, "entwurf.json").readBytes().toString(Charsets.UTF_8).contains(draft.note))
            assertEquals(draft, Ablage.fuerTest(context) { key }.entwurf.value.zeit)
        } finally { directory.deleteRecursively() }
    }

    @Test fun retriesAndStaleEditsCannotDuplicateOrOverwriteRecords() {
        val entry = Zeiteintrag(startMinute = 1000L, zone = "UTC")
        val started = ZeiterfassungStand(enabled = true).start(entry)
        assertEquals(started, started.start(entry))
        assertThrows(IllegalStateException::class.java) { started.start(Zeiteintrag(startMinute = 1001L)) }
        val current = started.entries.single()
        val changed = started.replace(current, current.pause(1010L))
        assertThrows(IllegalStateException::class.java) { changed.replace(current, current.finish(1020L)) }
        assertEquals(1010L, changed.entries.single().pauseMinute)
        assertEquals(started.actor, changed.actor)
        assertEquals(2L, changed.counter)
        val finished = changed.replace(changed.entries.single(), changed.entries.single().finish(1020L))
        val retried = finished.replace(changed.entries.single(), changed.entries.single().finish(1020L, changed = 1L))
        assertEquals(finished, retried)
    }

    @Test fun legacyDefaultsRemainStableWithoutCreatingAnActorDuringRead() {
        val json = Json { ignoreUnknownKeys = true }
        assertEquals(Bestand(), Bestand())
        assertEquals(ZeiterfassungStand(), json.decodeFromString(Bestand.serializer(), "{}").zeiterfassung)
        assertEquals("", ZeiterfassungStand().validate().actor)
    }

    @Test fun removalDropsLocalContentsWithoutCreatingASynchronizedDeletion() {
        val record = Zeiteintrag(startMinute = 1000, endMinute = 1060, note = "Private removable details")
        val before = ZeiterfassungStand(enabled = true).replace(null, record)
        val saved = before.entries.single()
        val removed = before.removeLocal(listOf(saved))
        assertTrue(removed.entries.isEmpty())
        assertEquals(setOf(saved.id), removed.removedIds)
        assertEquals(before.counter, removed.counter)
        assertEquals(saved, removed.trash.single().entries.single())
        val expired = removed.purgeExpired(removed.trash.single().expiresMs)
        assertFalse(Json.encodeToString(ZeiterfassungStand.serializer(), expired).contains(saved.note))
        assertEquals(removed, removed.removeLocal(listOf(saved)))
        assertEquals(removed, removed.start(record.copy(endMinute = null)))
        assertThrows(IllegalStateException::class.java) { removed.replace(null, record) }
        val changed = before.replace(saved, saved.copy(note = "Newer edit"))
        assertThrows(IllegalStateException::class.java) { changed.removeLocal(listOf(saved)) }
    }

    @Test fun removedMonthIsRestorableForThirtyDaysButCannotReappearThroughSyncAfterExpiry() {
        val record = Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC", note = "Month content")
        val before = ZeiterfassungStand(enabled = true).replace(null, record)
        val saved = before.entries.single()
        val removed = before.removeLocal(listOf(saved), now = 1000000L, month = "1970-01")
        val item = removed.trash.single()
        assertEquals(30L * 24 * 60 * 60 * 1000, item.expiresMs - item.removedMs)
        assertTrue(removed.suppressIncoming(saved))
        assertTrue(removed.suppressIncoming(record.copy(id = java.util.UUID.randomUUID().toString())))
        val restored = removed.restoreLocal(item.id, item.expiresMs - 1)
        assertEquals(listOf(saved), restored.entries)
        assertTrue(restored.trash.isEmpty())
        assertFalse(restored.suppressIncoming(saved))
        assertEquals(before.counter, restored.counter)
        assertThrows(IllegalStateException::class.java) { removed.restoreLocal(item.id, item.expiresMs) }
        val expired = removed.purgeExpired(item.expiresMs)
        assertTrue(expired.trash.isEmpty())
        assertTrue(expired.suppressIncoming(saved))
        assertEquals(before.counter, expired.counter)
    }
}
