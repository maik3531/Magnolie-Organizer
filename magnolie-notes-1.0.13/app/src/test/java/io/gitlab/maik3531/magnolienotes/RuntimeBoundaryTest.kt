package io.gitlab.maik3531.magnolienotes

import io.gitlab.maik3531.magnolienotes.baum.*
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.sicherung.*
import org.junit.Assert.*
import org.junit.Test
import java.io.InputStream
import java.nio.file.Files

class RuntimeBoundaryTest {
    private class Endless : InputStream() {
        var read = 0
        override fun read(): Int { read++; return 1 }
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            b.fill(1, off, off + len); read += len; return len
        }
    }

    @Test fun pairingStreamStopsAtLimitPlusOne() {
        val stream = Endless()
        assertThrows(BaumFehler::class.java) { Paarung.liesDatei(stream) }
        assertEquals(Paarung.DATEI_MAX + 1, stream.read)
    }

    @Test fun shareBudgetBoundsUnknownStreamsBeforeEncoding() {
        val budget = AnhangLeser.ImportBudget()
        repeat(2) { budget.lesen(ByteArray(AnhangLeser.ROH_MAX).inputStream()) }
        val stream = Endless()
        assertThrows(java.io.IOException::class.java) { budget.lesen(stream) }
        assertTrue(stream.read < AnhangLeser.ROH_MAX)
        val count = AnhangLeser.ImportBudget()
        repeat(AnhangLeser.ImportBudget.DATEIEN_MAX) { count.lesen(byteArrayOf(1).inputStream()) }
        val untouched = Endless()
        assertThrows(IllegalStateException::class.java) { count.lesen(untouched) }
        assertEquals(0, untouched.read)
    }

    @Test fun pendingPairingIsBoundedExpiresAndPreservesPins() {
        val pin = Partner("confirmed", oeffentlich = "pinned", bestaetigt = true, vertraut = true)
        var state = Baumzustand(partner = listOf(pin))
        repeat(Paarung.OFFEN_MAX) { state = Paarung.partnerAufnehmen(state, Partner("p$it"), jetzt = 1000) }
        assertThrows(BaumFehler::class.java) { Paarung.partnerAufnehmen(state, Partner("overflow"), jetzt = 1000) }
        val restarted = Ablage.json.decodeFromString(Baumzustand.serializer(), Ablage.json.encodeToString(Baumzustand.serializer(), state))
        assertEquals(listOf(pin), Paarung.bereinigen(restarted, 1000 + Paarung.OFFEN_MS).partner)
        assertEquals(Paarung.OFFEN_MAX + 1, Paarung.bereinigen(restarted, 1001).partner.size)
    }

    @Test fun pairingWindowAndRateLimitsCannotBeResetByReopening() {
        var now = 1000L
        val window = CodePaarungsFenster { now }
        assertThrows(BaumFehler::class.java) { window.zulassen("a") }
        window.oeffnen()
        repeat(2) { window.zulassen("a") }
        window.oeffnen()
        assertThrows(BaumFehler::class.java) { window.zulassen("a") }
        repeat(6) { window.zulassen("source-$it") }
        assertThrows(BaumFehler::class.java) { window.zulassen("overflow") }
        now += 60_000
        window.zulassen("a")
        now += 60_000
        assertThrows(BaumFehler::class.java) { window.zulassen("a") }
        assertThrows(BaumFehler::class.java) { CodePaarungsFenster { now }.zulassen("a") }
    }

    @Test fun directorySyncIsRealAndErrorsPropagate() {
        val dir = Files.createTempDirectory("directory-sync-").toFile()
        try {
            assertThrows(java.io.IOException::class.java) { java.io.FileOutputStream(dir).close() }
            synchronisiereOrdner(dir)
            assertThrows(java.io.IOException::class.java) { synchronisiereOrdner(java.io.File(dir, "missing")) }
        } finally { dir.deleteRecursively() }
    }

    @Test fun allBackupDomainsAreExcludedInBothSections() {
        val document = javax.xml.parsers.DocumentBuilderFactory.newInstance().newDocumentBuilder()
            .parse(java.io.File("app/src/main/res/xml/datenregeln.xml"))
        for (section in listOf("cloud-backup", "device-transfer")) {
            val children = document.getElementsByTagName(section).item(0).childNodes
            val domains = (0 until children.length).mapNotNull {
                children.item(it).attributes?.getNamedItem("domain")?.nodeValue }.toSet()
            assertEquals(setOf("root", "file", "database", "sharedpref", "external", "device_root",
                "device_file", "device_database", "device_sharedpref"), domains)
        }
    }

    @Test fun olderValidBackupNeverReportsSuccessOrRunsRetention() {
        val password = "synthetic-test-password".toCharArray()
        val old = PortableArchiv.erstellen(Bestand(), password)
        val fresh = PortableArchiv.erstellen(Bestand(notizen = listOf(Notiz(id = "new", titel = "recent"))), password)
        PortableArchiv.pruefen(old, password)
        PortableArchiv.pruefen(fresh, password)
        var success = false
        var listed = false
        var authenticated = false
        val deleted = mutableListOf<String>()
        val provider = object : SicherungsOrdner {
            override fun anlegen(name: String, mime: String) = SicherungsDokument("new", name, mime, 1)
            override fun schreiben(dokument: SicherungsDokument, inhalt: ByteArray) { assertArrayEquals(fresh, inhalt) }
            override fun lesen(dokument: SicherungsDokument, maximum: Long) = old.copyOf()
            override fun auflisten(maximum: Int): BegrenzteDokumente { listed = true; return BegrenzteDokumente(emptyList(), false) }
            override fun loeschen(dokument: SicherungsDokument): Boolean { deleted += dokument.kennung; return true }
        }
        assertThrows(IllegalStateException::class.java) {
            AutoSicherungsLauf(provider).ausfuehren(1000, 2, { fresh.copyOf() },
                { authenticated = true; PortableArchiv.pruefen(it, password) }, { success = true })
        }
        assertFalse(success); assertFalse(listed); assertFalse(authenticated)
        assertEquals(listOf("new"), deleted)
        val identity = ArchivIdentitaet(fresh)
        identity.pruefen(fresh.copyOf())
        assertThrows(IllegalStateException::class.java) { identity.pruefen(fresh.copyOf().also {
            it[it.lastIndex] = (it.last().toInt() xor 1).toByte()
        }) }
        assertThrows(IllegalStateException::class.java) { identity.pruefen(old) }
        password.fill('\u0000'); old.fill(0); fresh.fill(0)
    }
}
