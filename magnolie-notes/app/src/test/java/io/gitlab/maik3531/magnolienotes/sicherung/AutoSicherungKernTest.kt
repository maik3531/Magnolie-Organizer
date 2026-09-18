package io.gitlab.maik3531.magnolienotes.sicherung

import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class AutoSicherungKernTest {
    @Test fun `generic SAF binary MIME still requires successful encrypted readback`() {
        val events = mutableListOf<String>()
        val folder = FakeOrdner(events, reportedMime = "application/octet-stream")
        assertEquals(SicherungsLaufErgebnis.ERFOLG, AutoSicherungsLauf(folder).ausfuehren(
            1_700_000_000_000, 2, archiv = { byteArrayOf(4, 2) },
            authentifizieren = { assertTrue(it.contentEquals(byteArrayOf(4, 2))); events += "auth" },
            nachErfolg = { events += "erfolg" }))
        assertTrue(events.indexOf("auth") < events.indexOf("erfolg"))
        assertThrows(IllegalStateException::class.java) {
            AutoSicherungsLauf(FakeOrdner(mutableListOf(), "application/octet-stream")).ausfuehren(
                1_700_000_000_000, 2, { byteArrayOf(0) }, { error("invalid archive") }, { error("must not report success") })
        }
    }

    @Test fun `Konfiguration begrenzt Aufbewahrung und kennt nur echte Perioden`() {
        assertEquals(2, AutoSicherungsKonfiguration.lesen("TAEGLICH", -5).aufbewahrung)
        assertEquals(AutoSicherungsIntervall.TAEGLICH,
            AutoSicherungsKonfiguration.lesen("TAEGLICH", 3).intervall)
        assertEquals(30, AutoSicherungsKonfiguration.lesen("falsch", 999).aufbewahrung)
        assertEquals(AutoSicherungsIntervall.WOECHENTLICH,
            AutoSicherungsKonfiguration.lesen("falsch", 3).intervall)
        assertEquals(1L, AutoSicherungsIntervall.TAEGLICH.tage)
        assertEquals(7L, AutoSicherungsIntervall.WOECHENTLICH.tage)
    }

    @Test fun `Schreiben Lesen Authentifizieren kommt vor Erfolg und Aufbewahrung`() {
        val ereignisse = mutableListOf<String>()
        val ordner = FakeOrdner(ereignisse)
        val ergebnis = AutoSicherungsLauf(ordner).ausfuehren(1_700_000_000_000, 2,
            archiv = { ereignisse += "archiv"; byteArrayOf(4, 2) },
            authentifizieren = { assertTrue(it.contentEquals(byteArrayOf(4, 2))); ereignisse += "auth" },
            nachErfolg = { ereignisse += "erfolg" })
        assertEquals(SicherungsLaufErgebnis.ERFOLG, ergebnis)
        assertTrue(ereignisse.indexOf("schreiben") < ereignisse.indexOf("lesen"))
        assertTrue(ereignisse.indexOf("lesen") < ereignisse.indexOf("auth"))
        assertTrue(ereignisse.indexOf("auth") < ereignisse.indexOf("erfolg"))
        assertTrue(ereignisse.indexOf("erfolg") < ereignisse.indexOf("auflisten"))
    }

    @Test fun `fehlgeschlagene Authentifizierung entfernt nur die neue Teildatei`() {
        val ereignisse = mutableListOf<String>()
        val ordner = FakeOrdner(ereignisse)
        assertThrows(IllegalStateException::class.java) {
            AutoSicherungsLauf(ordner).ausfuehren(1_700_000_000_000, 2,
                archiv = { byteArrayOf(1) }, authentifizieren = { error("defekt") },
                nachErfolg = { ereignisse += "erfolg" })
        }
        assertTrue("loeschen" in ereignisse)
        assertFalse("erfolg" in ereignisse)
        assertFalse("auflisten" in ereignisse)
    }

    @Test fun `Aufbewahrung ignoriert fremde Dateien und behaelt bestaetigte gute Datei`() {
        val neu = eigen("neu", 30)
        val alt = eigen("alt", 10)
        val mitte = eigen("mitte", 20)
        val fremd = SicherungsDokument("fremd", alt.name, "text/plain", 0)
        val geloescht = AutoSicherungsRegeln.zuLoeschen(listOf(alt, mitte, neu, fremd), neu.name, 2)
        assertEquals(listOf("alt"), geloescht.map { it.kennung })
        assertFalse(geloescht.any { it.kennung == neu.kennung || it.kennung == fremd.kennung })
        assertTrue(AutoSicherungsRegeln.zuLoeschen(listOf(alt), alt.name, 2).isEmpty())
    }

    @Test fun `retention authenticates generic binary candidates before deleting them`() {
        for (validOld in listOf(false, true)) {
            val deleted = mutableListOf<String>()
            val read = mutableListOf<String>()
            val old = eigen("old", 1).copy(mime = "application/octet-stream")
            val middle = eigen("middle", 2).copy(mime = "application/octet-stream")
            lateinit var newest: SicherungsDokument
            var content = byteArrayOf()
            val folder = object : SicherungsOrdner {
                override fun anlegen(name: String, mime: String) = SicherungsDokument("new", name, "application/octet-stream", 3)
                    .also { newest = it }
                override fun schreiben(dokument: SicherungsDokument, inhalt: ByteArray) { content = inhalt.copyOf() }
                override fun lesen(dokument: SicherungsDokument, maximum: Long): ByteArray {
                    read += dokument.kennung
                    return if (dokument.kennung == "new" || validOld) content.copyOf() else byteArrayOf(0)
                }
                override fun auflisten(maximum: Int) = BegrenzteDokumente(listOf(old, middle, newest), false)
                override fun loeschen(dokument: SicherungsDokument): Boolean { deleted += dokument.kennung; return true }
            }
            val result = AutoSicherungsLauf(folder).ausfuehren(1_700_000_000_000, 2, { byteArrayOf(4, 2) },
                { check(it.contentEquals(byteArrayOf(4, 2))) }, {})
            assertEquals(listOf("new", "old"), read)
            assertEquals(if (validOld) listOf("old") else emptyList<String>(), deleted)
            assertEquals(if (validOld) SicherungsLaufErgebnis.ERFOLG else SicherungsLaufErgebnis.ERFOLG_AUFBEWAHRUNG_FEHLER, result)
        }
    }

    private fun eigen(id: String, zeit: Long) = SicherungsDokument(id,
        AutoSicherungsRegeln.name(1_700_000_000_000 + zeit, UUID.nameUUIDFromBytes(id.toByteArray())),
        AutoSicherungsRegeln.MIME, zeit)

    private class FakeOrdner(private val ereignisse: MutableList<String>, private val reportedMime: String? = null) : SicherungsOrdner {
        private lateinit var neu: SicherungsDokument
        private var inhalt = ByteArray(0)
        override fun anlegen(name: String, mime: String) = SicherungsDokument("neu", name, reportedMime ?: mime, 100)
            .also { neu = it; ereignisse += "anlegen" }
        override fun schreiben(dokument: SicherungsDokument, inhalt: ByteArray) {
            this.inhalt = inhalt.copyOf(); ereignisse += "schreiben"
        }
        override fun lesen(dokument: SicherungsDokument, maximum: Long): ByteArray {
            ereignisse += "lesen"; return inhalt.copyOf()
        }
        override fun auflisten(maximum: Int): BegrenzteDokumente {
            ereignisse += "auflisten"; return BegrenzteDokumente(listOf(neu), false)
        }
        override fun loeschen(dokument: SicherungsDokument): Boolean { ereignisse += "loeschen"; return true }
    }
}
