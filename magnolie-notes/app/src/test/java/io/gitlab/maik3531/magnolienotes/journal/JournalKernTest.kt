package io.gitlab.maik3531.magnolienotes.journal

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import javax.crypto.KeyGenerator

class JournalKernTest {
    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test fun `AES GCM roundtrip frische nonce und tamper detection`() {
        val crypto = AesGcmKrypto { key }
        val plain = "notizen und baum".toByteArray()
        val a = crypto.encrypt(plain, "id".toByteArray())
        val b = crypto.encrypt(plain, "id".toByteArray())
        assertFalse(a.contentEquals(b))
        assertArrayEquals(plain, crypto.decrypt(a, "id".toByteArray()))
        a[a.lastIndex] = (a.last().toInt() xor 1).toByte()
        assertThrows(Exception::class.java) { crypto.decrypt(a, "id".toByteArray()) }
    }

    @Test fun `Intervalle und default weekly sind korrekt`() {
        assertEquals(7L * 24 * 3600_000, JournalIntervall.WOECHENTLICH.millis)
        assertFalse(JournalRegeln.due(null, 1, JournalIntervall.AUS))
        assertTrue(JournalRegeln.due(null, 1, JournalIntervall.SECHS_STUNDEN))
        assertFalse(JournalRegeln.due(0, 6L * 3600_000 - 1, JournalIntervall.SECHS_STUNDEN))
        assertTrue(JournalRegeln.due(0, 6L * 3600_000, JournalIntervall.SECHS_STUNDEN))
    }

    @Test fun `Budget Reserve Dedupe und Retention Vertrag`() {
        assertEquals(512L * 1024 * 1024, JournalRegeln.budget(20L * 1024 * 1024 * 1024))
        assertEquals(50L, JournalRegeln.budget(1000))
        assertEquals(256L * 1024 * 1024, JournalRegeln.RESERVE_BYTES)
        assertEquals(15L * 60_000, JournalRegeln.DEDUPE_MS)
        val now = Instant.parse("2026-08-12T12:00:00Z").toEpochMilli()
        val entries = (0 until 30).map { i ->
            val reason = when { i < 6 -> "pre-restore"; i < 26 -> "pre-sync-full"; else -> "manual" }
            SnapshotManifest(uuid = "$i", createdUtc = Instant.ofEpochMilli(now - i * 86400_000L).toString(),
                appVersion = "1.0.5", reason = reason, domain = "android-app-data",
                payload = NutzlastManifest("h$i", i.toLong()), summary = "s", syncEpoch = "e",
                pinned = i == 29)
        }
        val keep = JournalRegeln.behalten(entries, now)
        assertTrue("29" in keep)
        assertTrue(entries.filter { it.uuid in keep && it.reason == "pre-restore" }.size <= 5)
        assertTrue(entries.filter { it.uuid in keep && it.reason.startsWith("pre-sync") }.size <= 20)
        val limited = JournalRegeln.behalten(entries, now, 3)
        assertEquals(setOf("0", "1", "2", "29"), limited)
        val restoring = entries.map { if (it.uuid == "29") it.copy(restoreOperationId = "restore") else it }
        assertEquals(setOf("0", "29"), JournalRegeln.behalten(restoring, now, 1))
    }

    @Test fun `Manifest besitzt gemeinsamen Vertrag`() {
        val m = JournalRegeln.manifest("manual", "android-app-data", "1.0.5", byteArrayOf(1),
            "one note", "epoch", true, now = 0)
        assertEquals("magnolie-snapshot", m.type)
        assertEquals(1, m.version)
        assertEquals("android", m.platform)
        assertEquals(64, m.payload.hash.length)
        assertEquals(1, m.payload.schema)
    }

    @Test fun `Geschuetzte Punkte und neuester unbekannter Grund bleiben erhalten`() {
        val now = Instant.parse("2026-09-10T12:00:00Z").toEpochMilli()
        val old = JournalRegeln.manifest("manual", "android-app-data", "1.0.14",
            byteArrayOf(1), "old", "epoch", pinned = true, now = now - 100L * 86400_000)
        val recent = JournalRegeln.manifest("future-reason", "android-app-data", "1.0.14",
            byteArrayOf(2), "recent", "epoch", now = now)
        assertEquals(setOf(old.uuid, recent.uuid), JournalRegeln.behalten(listOf(old, recent), now, 1))
        assertEquals(setOf(recent.uuid), JournalRegeln.behalten(listOf(old.copy(pinned = false, reason = "future-reason"), recent), now))
        val damaged = old.copy(uuid = "damaged", pinned = false, createdUtc = "invalid-date")
        assertNull(JournalRegeln.zeitpunkt(damaged))
        assertEquals(setOf(damaged.uuid, recent.uuid), JournalRegeln.behalten(listOf(damaged, recent), now, 1))
        assertEquals(setOf(damaged.uuid, recent.uuid), JournalRegeln.behalten(listOf(damaged, recent), now))
    }
}
