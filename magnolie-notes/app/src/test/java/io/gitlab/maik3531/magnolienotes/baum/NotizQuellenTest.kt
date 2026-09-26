package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class NotizQuellenTest {
    @Test fun `actual local edits protect the source baseline but metadata and identical echoes do not conflict`() {
        val note = Notiz("local", titel = "Same", text = "Same", baumInhaltVersion = 3,
            baumFreigabe = Freigabe("share", listOf("peer"), quellen = listOf(NotizQuelle("peer", "share", 7, "peer", 3))))
        val metadata = NotizQuellen.lokaleAenderung(note, note.copy(geaendert = 100, baumInhaltVersion = 0))
        assertEquals(3L, metadata.baumInhaltVersion)
        val edited = NotizQuellen.lokaleAenderung(note, note.copy(text = "Own edit", baumFreigabe = null))
        assertEquals(note.baumFreigabe, edited.baumFreigabe)
        assertEquals(4L, edited.baumInhaltVersion)
        assertTrue(NotizQuellen.konflikt(edited, "peer", "share", note.copy(text = "Other edit")))
        assertFalse(NotizQuellen.konflikt(edited, "peer", "share", edited.copy(geaendert = 999)))
        assertFalse(NotizQuellen.konflikt(note, "peer", "share", note.copy(text = "Next source edit")))
    }

    @Test fun `consolidated source IDs are used for updates and return traffic`() {
        val first = Notiz("local-a", titel = "Same", text = "Same", baumQuelle = "peer-a", baumVersion = 100,
            baumFreigabe = Freigabe("share-a", listOf("peer-a")))
        val second = first.copy(id = "local-b", baumQuelle = "peer-b", baumVersion = 3,
            baumFreigabe = Freigabe("share-b", listOf("peer-b")))
        val compacted = PersonalSync.compactNotes(Bestand(notizen = listOf(first, second))).notizen.single()
        assertEquals(100L, NotizQuellen.quelle(compacted, "peer-a", "share-a")!!.version)
        assertEquals(3L, NotizQuellen.quelle(compacted, "peer-b", "share-b")!!.version)
        assertEquals("share-a", NotizQuellen.inhalte(compacted, "notiz_sync", "self", "peer-a").single().getValue("freigabeId").jsonPrimitive.content)
        assertEquals("share-b", NotizQuellen.inhalte(compacted, "notiz_sync", "self", "peer-b").single().getValue("freigabeId").jsonPrimitive.content)
        assertNull(NotizQuellen.quelle(compacted, "unknown", "share-a"))
        assertNull(NotizQuellen.quelle(compacted, "peer-b", "share-a"))
        assertTrue(NotizQuellen.inhalte(compacted, "notiz_sync", "self", "unknown").isEmpty())
    }

    @Test fun `multiple IDs at one partner remain addressable and revocation wins over old metadata`() {
        val note = Notiz("local", baumFreigabe = Freigabe("primary", listOf("peer"), quellen = listOf(
            NotizQuelle("peer", "first", 5), NotizQuelle("peer", "second", 7))))
        assertEquals(setOf("first", "second"), NotizQuellen.inhalte(note, "notiz_sync", "self", "peer")
            .map { it.getValue("freigabeId").jsonPrimitive.content }.toSet())
        assertEquals(7L, NotizQuellen.quelle(note, "peer", "second")!!.version)
        val revoked = note.copy(baumFreigabe = note.baumFreigabe!!.copy(partner = emptyList()))
        assertNull(NotizQuellen.quelle(revoked, "peer", "second"))
        assertTrue(NotizQuellen.inhalte(revoked, "notiz_sync", "self", "peer").isEmpty())
    }
}
