package io.gitlab.maik3531.magnolienotes.journal

import io.gitlab.maik3531.magnolienotes.daten.Ablage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.time.Instant

class DateiSnapshotStoreTest {
    private class Prozessabbruch : Error()

    @Test fun `neustart nach jeder commitgrenze zeigt alten oder neuen gueltigen snapshot`() {
        SnapshotCommitSchritt.entries.forEach { grenze ->
            val ordner = Files.createTempDirectory("snapshot-paar-").toFile()
            try {
                val alt = manifest("alt", 3)
                DateiSnapshotStore(ordner, Ablage.json).write(alt, byteArrayOf(1, 2, 3))
                val neu = manifest("neu", 2)

                try {
                    DateiSnapshotStore(ordner, Ablage.json) {
                        if (it == grenze) throw Prozessabbruch()
                    }.write(neu, byteArrayOf(4, 5))
                } catch (_: Prozessabbruch) {
                    // Harter Abbruch: Der alte Prozess fuehrt keinerlei finally-Aufraeumen aus.
                }

                val nachNeustart = DateiSnapshotStore(ordner, Ablage.json)
                val ids = nachNeustart.list().map { it.uuid }.toSet()
                val erwartet = if (grenze <= SnapshotCommitSchritt.MANIFEST_BEREIT) setOf("alt")
                    else setOf("alt", "neu")
                assertEquals("Falscher Stand nach $grenze", erwartet, ids)
                assertEquals(alt to byteArrayOf(1, 2, 3).toList(),
                    nachNeustart.read("alt").let { it.first to it.second.toList() })
                if ("neu" in ids) assertEquals(neu to byteArrayOf(4, 5).toList(),
                    nachNeustart.read("neu").let { it.first to it.second.toList() })
                assertTrue(ordner.listFiles().orEmpty().all {
                    it.extension == "json" || it.extension == "bin"
                })
            } finally {
                ordner.deleteRecursively()
            }
        }
    }

    @Test fun `neustart entfernt vorbereitete dateien und verwaiste halbpaare`() {
        val ordner = Files.createTempDirectory("snapshot-bereinigung-").toFile()
        try {
            ordner.resolve("vorbereitet.bin.snapshot-bereit").writeBytes(byteArrayOf(1))
            ordner.resolve("installation.json.snapshot-install").writeText("{}")
            ordner.resolve("nur-payload.bin").writeBytes(byteArrayOf(2))
            ordner.resolve("nur-manifest.json").writeText("{}")

            val store = DateiSnapshotStore(ordner, Ablage.json)

            assertTrue(store.list().isEmpty())
            assertFalse(ordner.listFiles().orEmpty().any { it.isFile })
        } finally {
            ordner.deleteRecursively()
        }
    }

    private fun manifest(id: String, size: Long) = SnapshotManifest(
        uuid = id,
        createdUtc = Instant.EPOCH.toString(),
        appVersion = "test",
        reason = "manual",
        domain = "android-app-data",
        payload = NutzlastManifest("hash-$id", size),
        summary = id,
        syncEpoch = "epoch"
    )
}
