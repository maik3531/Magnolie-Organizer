package io.gitlab.maik3531.magnolienotes.journal

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class JournalVerkabelungTest {
    @Test fun `WorkManager statt AlarmManager und Startpruefung`() {
        val android = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/journal/AndroidJournal.kt").readText()
        assertTrue(android.contains("PeriodicWorkRequestBuilder"))
        assertTrue(android.contains("15, TimeUnit.MINUTES"))
        assertFalse(android.contains("AlarmManager"))
        val app = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/MagnolieApp.kt").readText()
        assertTrue(app.contains("withContext(Dispatchers.IO)"))
        assertTrue(app.contains("AndroidJournal.hole(this@MagnolieApp)"))
        assertTrue(app.indexOf("_startZustand.value = StartZustand.Bereit") <
            app.indexOf("BaumDienst.starten(this@MagnolieApp)"))
        assertTrue(File("app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/BaumDienst.kt").readText()
            .contains("faelligSichern"))
    }

    @Test fun `risikopfade blockieren bei fehlgeschlagenem Snapshot und Batch hat einen Snapshot`() {
        val werk = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt").readText()
        val batch = werk.substring(werk.indexOf("fun sichereKontaktGruppenImportieren"),
            werk.indexOf("fun kontaktGruppeAblehnen"))
        assertEquals(1, Regex("kontaktSnapshot\\(").findAll(batch).count())
        assertTrue(batch.indexOf("kontaktSnapshot") < batch.indexOf("gruppen.forEach"))
        assertTrue(werk.indexOf("appSnapshot(\"pre-sync-full\")") < werk.indexOf("Synchronisation.planen"))
        assertTrue(werk.contains("journalStaende(listOf(spur.rawContactId), \"delete\")"))
        assertTrue(werk.contains("contact-keep-together"))
    }

    @Test fun `Kontaktserialisierung Restore Epoch und UI Vertrag sind verdrahtet`() {
        val contacts = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/AndroidKontakte.kt").readText()
        listOf("ACCOUNT_NAME", "ACCOUNT_TYPE", "DATA_SET", "SOURCE_ID", "AGGREGATION_MODE",
            "(1..15)", "(1..4)", "IS_PRIMARY", "IS_SUPER_PRIMARY").forEach { assertTrue(it, contacts.contains(it)) }
        val ablage = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/Ablage.kt").readText()
        listOf("wiederherstellung-${'$'}operationId.ok", "syncEpoch = neueEpoch",
            "additiveBaselineAusstehend = true", "quarantiniertesPostfach").forEach { assertTrue(it, ablage.contains(it)) }
        val ui = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/JournalBlatt.kt").readText()
        listOf("journal_zuletzt", "journal_naechste", "journal_status", "journal_intervall",
            "journal_jetzt", "journal_vorschau", "journal_restore", "journal_loeschen_frage").forEach {
            assertTrue(it, ui.contains(it))
        }
        assertTrue(ui.contains("ausgewaehlt = bestand.papierkorbEinstellungen.tage == tage"))
        assertTrue(ui.contains("ausgewaehlt = zustand.interval == interval"))
        assertFalse(ui.contains("Papierknopf(stringResource(R.string.ok), modifier = Modifier.padding(top = 7.dp))"))
        assertTrue(ui.contains("takeIf { it in 1..100 }?.let(handlungen.beiMaximum)"))
        assertTrue(ui.contains("takeIf { it in 2..30 }"))
        assertTrue(ui.contains("?.let(handlungen.beiAutoAufbewahrung)"))
        val components = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/Bausteine.kt").readText()
        assertTrue(components.contains("containerColor = if (ausgewaehlt) Magnolie.leder else Magnolie.papier"))
        assertTrue(components.contains("selected = ausgewaehlt"))
        assertTrue(components.contains("disabledContainerColor = Magnolie.papierTief"))
        assertTrue(components.contains("disabledContentColor = Magnolie.braun"))
    }
}
