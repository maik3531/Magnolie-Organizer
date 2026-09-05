package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.nio.file.Files

class WiederherstellungsPaarCommitTest {
    private class Prozessabbruch : Error()
    private class IoAbbruch : IOException()

    @Test fun `abbruch nach jedem commit schritt ergibt nach laden altes oder neues paar`() {
        PaarCommitSchritt.entries.forEach { abbruchNach ->
            val ordner = Files.createTempDirectory("paar-commit-").toFile()
            try {
                val notizen = ordner.resolve("notizen.json")
                val baum = ordner.resolve("baum.json")
                notizen.writeText("notizen-alt")
                baum.writeText("baum-alt")

                val commit = WiederherstellungsPaarCommit(ordner) { schritt ->
                    if (schritt == abbruchNach) throw Prozessabbruch()
                }
                try {
                    commit.commit("notizen-neu", "baum-neu", "operation-1")
                } catch (_: Prozessabbruch) {
                    // Simulierter harter Prozessabbruch: keinerlei Aufraeumen im alten Prozess.
                }

                WiederherstellungsPaarCommit(ordner).wiederaufnehmen()
                val paar = notizen.readText() to baum.readText()
                assertTrue("Inkonsistenter Stand nach $abbruchNach: $paar", paar ==
                    ("notizen-alt" to "baum-alt") || paar == ("notizen-neu" to "baum-neu"))
                assertFalse(ordner.resolve("wiederherstellung.pending").exists())
                assertFalse(ordner.resolve("notizen.json.restore").exists())
                assertFalse(ordner.resolve("baum.json.restore").exists())
            } finally {
                ordner.deleteRecursively()
            }
        }
    }

    @Test fun `io abbruch vor absichtsmarke behaelt alt danach wird neu fertiggestellt`() {
        PaarCommitSchritt.entries.forEach { abbruchNach ->
            val ordner = Files.createTempDirectory("paar-epoch-").toFile()
            try {
                ordner.resolve("notizen.json").writeText("N0")
                ordner.resolve("baum.json").writeText("B0")
                try {
                    WiederherstellungsPaarCommit(ordner) {
                        if (it == abbruchNach) throw IoAbbruch()
                    }.commit("N1", "B1", "operation-2")
                } catch (_: IoAbbruch) {
                }

                WiederherstellungsPaarCommit(ordner).wiederaufnehmen()
                val erwartet = if (abbruchNach <= PaarCommitSchritt.BAUM_BEREIT) "N0" to "B0" else "N1" to "B1"
                assertEquals(erwartet, ordner.resolve("notizen.json").readText() to
                    ordner.resolve("baum.json").readText())
                assertTrue((abbruchNach <= PaarCommitSchritt.BAUM_BEREIT) xor
                    ordner.resolve("wiederherstellung-operation-2.ok").exists())
            } finally {
                ordner.deleteRecursively()
            }
        }
    }

    @Test fun `beschaedigter marker und fehlende restore datei bleiben fail closed erhalten`() {
        val ordner = Files.createTempDirectory("paar-kaputt-").toFile()
        try {
            val marker = ordner.resolve("wiederherstellung.pending")
            marker.writeText("%%%")
            erwarteRecovery { WiederherstellungsPaarCommit(ordner).wiederaufnehmen() }
            assertEquals("%%%", marker.readText())

            marker.writeText(java.util.Base64.getUrlEncoder().withoutPadding()
                .encodeToString("operation-3".toByteArray()))
            ordner.resolve("notizen.json.restore").writeText("N1")
            erwarteRecovery { WiederherstellungsPaarCommit(ordner).wiederaufnehmen() }
            assertTrue(marker.exists())
            assertEquals("N1", ordner.resolve("notizen.json.restore").readText())
        } finally {
            ordner.deleteRecursively()
        }
    }

    private fun erwarteRecovery(block: () -> Unit) {
        try {
            block()
            org.junit.Assert.fail("Recoveryfehler wurde akzeptiert")
        } catch (fehler: StartFehler) {
            assertEquals(StartFehlerArt.RECOVERY, fehler.art)
        }
    }
}
