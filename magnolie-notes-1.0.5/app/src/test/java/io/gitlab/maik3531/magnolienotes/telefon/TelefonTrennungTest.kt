package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TelefonTrennungTest {
    @Test fun `Telefonquellen greifen nicht auf Baumzustand oder Baumtransport zu`() {
        val dir = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon")
        val source = dir.walkTopDown().filter { it.extension == "kt" }.joinToString("\n") { it.readText() }
        listOf("baum.json", "baum-post.json", "baum-eingang.json", "_magnolie._tcp", "8737", "Baumwerk",
            "BluetoothHorcher", "baum-fs1", "magnolienbaum").forEach { forbidden ->
            assertFalse("Telefonquelle enthält $forbidden", source.contains(forbidden))
        }
        assertTrue(source.contains("magnolie_phone_storage_v1"))
        assertTrue(source.contains("magnolie_phone.db"))
    }

    @Test fun `Baumdispatch kennt keine alten Geraetestatusarten mehr`() {
        val source = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/baum").walkTopDown()
            .filter { it.extension == "kt" }.joinToString("\n") { it.readText() }
        assertFalse(source.contains("geraete_status_anfrage"))
        assertFalse(source.contains("geraete_status"))
    }

    @Test fun `Entfernen leert nur peergebundene Telefonprotokolldaten`() {
        val database = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonDatenbank.kt").readText()
        listOf("outbox", "inbox", "dedupe", "personal_batch", "personal_run").forEach {
            assertTrue("Peer-Cleanup fehlt für $it", database.contains("\"$it\""))
        }
        assertTrue(database.contains("delete(\"event_dedupe\""))
        val work = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt").readText()
        assertTrue(work.contains("queue.deletePeer(it.device_id)"))
        assertTrue("Entkoppeln meldet sich nicht am authentisierten Organizer ab",
            work.contains("orderlyClose?.invoke(\"unpaired\")"))
        assertTrue(work.contains("put(\"reason\", JsonPrimitive(reason))"))
        assertFalse("Entkoppeln darf keine synchronisierten Inhalte löschen",
            work.substring(work.indexOf("fun unpair()"), work.indexOf("private fun reconnect()"))
                .contains("Ablage.hole"))
    }
}
