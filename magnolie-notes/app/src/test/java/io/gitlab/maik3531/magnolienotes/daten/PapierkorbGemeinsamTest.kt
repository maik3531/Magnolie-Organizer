package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.*
import org.junit.Test

class PapierkorbGemeinsamTest {
    private val day = 86_400_000L
    private fun withBothTrash(now: Long): Bestand {
        val time = ZeiterfassungStand(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, type = "Synthetic time"))
        val note = PapierkorbLogik.loescheNotiz(Bestand(notizen = listOf(Notiz("owned", titel = "Synthetic note"))), "owned", now)
        return note.copy(zeiterfassung = time.removeLocal(time.entries, now))
    }

    @Test fun oneRetentionPolicyExpiresBothKindsAndZeroKeepsBoth() {
        val input = withBothTrash(day)
        val manual = PapierkorbLogik.bereinigen(input.copy(papierkorbEinstellungen = PapierkorbEinstellungen(true, 0)), 400 * day)
        assertEquals(input.papierkorb, manual.papierkorb)
        assertEquals(input.zeiterfassung.trash, manual.zeiterfassung.trash)
        val expired = PapierkorbLogik.bereinigen(input.copy(papierkorbEinstellungen = PapierkorbEinstellungen(true, 7)), 9 * day)
        assertTrue(expired.papierkorb.isEmpty())
        assertTrue(expired.zeiterfassung.trash.isEmpty())
        assertEquals(input.zeiterfassung.removedIds, expired.zeiterfassung.removedIds)
    }

    @Test fun disablingDoesNotDestroyEitherExistingTrashPayload() {
        val input = withBothTrash(day).copy(papierkorbEinstellungen = PapierkorbEinstellungen(false, 7))
        val later = PapierkorbLogik.bereinigen(input, 400 * day)
        assertEquals(input, later)
    }

    @Test fun disabledTrashRemovesTimesWithoutArchivingOrRemoteDeletion() {
        val input = withBothTrash(day)
        val time = input.zeiterfassung.replace(null,
            Zeiteintrag(startMinute = 2000, endMinute = 2060, type = "Second synthetic time"))
        val original = time.entries.single()
        val disabled = PapierkorbEinstellungen(false, 7)
        val removed = time.removeLocal(listOf(original), 400 * day, papierkorb = disabled)
        assertTrue(removed.entries.isEmpty())
        assertEquals(time.trash, removed.trash)
        assertEquals(time.removedIds + original.id, removed.removedIds)
        assertEquals(time.actor, removed.actor)
        assertEquals(time.counter, removed.counter)
    }

    @Test fun oneEmptyOperationClearsBothPayloadListsAndPreservesEveryOtherField() {
        val input = withBothTrash(day)
        val cleared = PapierkorbLogik.leeren(input)
        assertEquals(input.copy(papierkorb = emptyList(), zeiterfassung = input.zeiterfassung.copy(trash = emptyList())), cleared)
        assertTrue(cleared.zeiterfassung.removedIds.isNotEmpty())
        cleared.zeiterfassung.validate()
    }

    @Test fun restoredTimeUsesTheCommonRetentionInsteadOfFixedThirtyDays() {
        val input = withBothTrash(day).zeiterfassung
        val item = input.trash.single()
        assertTrue(input.restoreLocal(item.id, 100 * day, retentionDays = 0).trash.isEmpty())
        assertTrue(input.restoreLocal(item.id, 100 * day, retentionDays = 365).entries.isNotEmpty())
        assertThrows(IllegalStateException::class.java) { input.restoreLocal(item.id, 9 * day, retentionDays = 7) }
    }

    @Test fun emptyConfirmationIsBoundToBothTypedCollectionsAndRejectsNewItems() {
        val input = withBothTrash(day)
        val sameId = input.copy(papierkorb = input.papierkorb.map { it.copy(id = input.zeiterfassung.trash.single().id) })
        val expected = PapierkorbLogik.kennungen(sameId)
        assertEquals(2, expected.size)
        assertTrue(PapierkorbLogik.leeren(sameId, expected).papierkorb.isEmpty())
        val changed = sameId.copy(papierkorb = sameId.papierkorb + sameId.papierkorb.single().copy(id = "new-item"))
        assertThrows(IllegalStateException::class.java) { PapierkorbLogik.leeren(changed, expected) }
        assertEquals(2, changed.papierkorb.size)
        assertEquals(1, changed.zeiterfassung.trash.size)
    }

    @Test fun notesTasksAttachmentsAndTimesUseTheSamePolicyAndEmptyOperation() {
        val note = Notiz("with-attachment", titel = "Synthetic", anhaenge = listOf(Anhang("a", "Synthetic attachment")))
        val task = Aufgabe("synthetic-task", titel = "Synthetic task")
        val input = withBothTrash(day).copy(notizen = listOf(note), aufgaben = listOf(task))
        val attachment = PapierkorbLogik.loescheAnhang(input, note.id, "a", day)
        val deleted = PapierkorbLogik.loescheAufgabe(attachment, task.id, day)
        assertEquals(setOf("note", "task", "attachment"), deleted.papierkorb.map { it.art }.toSet())
        assertEquals(4, PapierkorbLogik.kennungen(deleted).size)
        val empty = PapierkorbLogik.leeren(deleted, PapierkorbLogik.kennungen(deleted))
        assertTrue(empty.papierkorb.isEmpty()); assertTrue(empty.zeiterfassung.trash.isEmpty())
        assertEquals(deleted.notizen, empty.notizen)
        val disabled = input.copy(papierkorbEinstellungen = PapierkorbEinstellungen(false, 7))
        val permanent = PapierkorbLogik.loescheAufgabe(PapierkorbLogik.loescheAnhang(disabled, note.id, "a", day), task.id, day)
        assertEquals(input.papierkorb, permanent.papierkorb)
        assertTrue(permanent.aufgaben.isEmpty()); assertTrue(permanent.notizen.single().anhaenge.isEmpty())
    }

    @Test fun permanentlyRemovedMonthKeepsLocalSuppressionWithoutCreatingTrash() {
        val input = ZeiterfassungStand(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC"))
        val removed = input.removeLocal(input.entries, day, month = "1970-01", papierkorb = PapierkorbEinstellungen(false, 0))
        assertTrue(removed.trash.isEmpty())
        assertEquals(setOf("1970-01"), removed.removedMonths)
        assertTrue(removed.suppressIncoming(input.entries.single()))
        assertEquals(input.counter, removed.counter)
    }
}
