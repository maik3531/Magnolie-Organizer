package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class KontaktVersion2Test {
    @Test fun `v2 name fields are exact bounded and participate in revisions without changing v1 hashes`() {
        val legacy = KontaktDaten(vorname = "Anna")
        assertEquals(KontaktSync.hash(legacy), KontaktSync.hash(legacy.copy(anzeigename = "Anna", vcardName = listOf("N:;Anna;;;", "FN:Anna"))))
        val full = legacy.copy(anzeigename = "Club contact", vcardName = listOf("N:;Anna;Maria;Dr.;", "FN:Club contact"))
        assertNotEquals(KontaktSync.hash(legacy), KontaktSync.hash(full))
        assertNotEquals(KontaktSync.hash(full), KontaktSync.hash(full.copy(vcardName = listOf("N:;Anna;Maria;Prof.;", "FN:Club contact"))))
        assertThrows(IllegalArgumentException::class.java) { KontaktSync.inhalt(KontaktNachricht("id", 1, "source", 0, full, 1)) }
        val wire = KontaktSync.inhalt(KontaktNachricht("id", 1, "source", 0, full, 2))
        assertEquals(full, KontaktSync.lies(wire)!!.kontakt)
        val data = wire["kontakt"] as JsonObject
        for (field in listOf("anzeigename", "vcardName")) assertNull(KontaktSync.lies(JsonObject(wire + ("kontakt" to JsonObject(data - field)))))
        for (names in listOf(listOf("UID:not-a-name"), listOf("FN:one\nFN:two"), List(33) { "FN:name" }, listOf("FN:" + "x".repeat(2049)))) {
            assertNull(KontaktSync.lies(JsonObject(wire + ("kontakt" to JsonObject(data + ("vcardName" to JsonArray(names.map(::JsonPrimitive))))))))
        }
    }

    @Test fun `F55 F56 supplied partial names and unknown years survive both wire formats`() {
        for ((given, family) in listOf("Anna Maria" to "", "" to "Van Dame", "Anne-Marie" to "Van der Berg")) {
            for (date in listOf("", "--06-07", "--02-29", "1604-02-29", "1980-12-31")) {
                for (version in 1..2) {
                    val contact = KontaktDaten(vorname = given, nachname = family, geburtstag = date)
                    val wire = KontaktSync.inhalt(KontaktNachricht("share", 1, "source", 1, contact, version))
                    val decoded = KontaktSync.lies(wire)!!
                    assertEquals(contact, decoded.kontakt)
                    assertEquals(wire, KontaktSync.inhalt(decoded))
                }
            }
        }
    }

    @Test fun `F57 old strict schema is unchanged and cannot silently drop anniversaries`() {
        val contact = KontaktDaten(vorname = "Anna", jubilaeum = "--02-29")
        assertThrows(IllegalArgumentException::class.java) {
            KontaktSync.inhalt(KontaktNachricht("share", 1, "source", 1, contact))
        }
        val modern = KontaktSync.inhalt(KontaktNachricht("share", 1, "source", 1, contact, 2))
        assertEquals(contact, KontaktSync.lies(modern)!!.kontakt)
        assertNull(KontaktSync.lies(JsonObject(modern + ("fassung" to JsonPrimitive(1)))))
        val payload = modern.getValue("kontakt") as JsonObject
        assertNull(KontaktSync.lies(JsonObject(modern + ("kontakt" to JsonObject(payload - "jubilaeum")))))
        for (invalid in listOf("--02-30", "0000-02-29", "2025-02-29", "--13-01")) {
            assertNull(KontaktSync.lies(JsonObject(modern + ("kontakt" to
                JsonObject(payload + ("jubilaeum" to JsonPrimitive(invalid)))))))
        }
        assertNull(KontaktSync.lies(JsonObject(modern + ("kontakt" to
            JsonObject(payload + ("guessed_field" to JsonPrimitive("not allowed")))))))
    }

    @Test fun `F57 anniversary is preserved by additive merge and prevents conflicting card union`() {
        val local = KontaktDaten(nachname = "Van Dame", geburtstag = "--02-29", jubilaeum = "--06-07")
        assertEquals(local, KontaktSync.mische(local, KontaktDaten()))
        assertNotEquals(KontaktSync.hash(local), KontaktSync.hash(local.copy(jubilaeum = "--06-08")))
        val cards = listOf(local, local.copy(jubilaeum = "--06-08")).mapIndexed { i, contact ->
            io.gitlab.maik3531.magnolienotes.daten.KontaktEingang("peer", "share-$i", 1, "source", 1, contact)
        }
        val group = KontaktEingangslogik.gruppiere(cards).single()
        assertFalse(group.zusammenfuehrbar)
        assertTrue(group.konflikte.any { it.feld == "jubilaeum" })
    }

    @Test fun `F57 capabilities are strict and do not accept discovery style extra fields`() {
        val expected = listOf(1, 2) to emptyList<Int>()
        assertEquals(expected, KontaktFaehigkeiten.lesen(KontaktFaehigkeiten.inhalt(false)))
        assertEquals(expected, KontaktFaehigkeiten.lesen(KontaktFaehigkeiten.inhalt(true)))
        val wire = KontaktFaehigkeiten.inhalt(false)
        assertEquals(listOf(1, 2) to listOf(1, 2), KontaktFaehigkeiten.lesen(JsonObject(wire +
            ("kontakt_import" to JsonArray(listOf(JsonPrimitive(1), JsonPrimitive(2)))))))
        for (bad in listOf(JsonArray(listOf(JsonPrimitive(2), JsonPrimitive(1))),
                JsonArray(listOf(JsonPrimitive("1"))), JsonArray(listOf(JsonPrimitive(1), JsonPrimitive(99))))) {
            assertNull(KontaktFaehigkeiten.lesen(JsonObject(wire + ("kontakt_sync" to bad))))
        }
        assertNull(KontaktFaehigkeiten.lesen(JsonObject(wire + ("adresse" to JsonPrimitive("192.0.2.99")))))
    }

    @Test fun `F57 one time import uses matching versioned manifest and cards`() {
        val sent = mutableListOf<JsonObject>()
        val flow = KontaktImportAblauf { _, body -> sent += body }
        val contact = KontaktDaten(nachname = "Van Dame", geburtstag = "--02-29", jubilaeum = "--06-07")
        val snapshot = KontaktSnapshot(listOf(AndroidKontakt("lookup", 1, contact)), true)
        assertThrows(IllegalArgumentException::class.java) { flow.vorschau(snapshot, "peer", "self", 1) }
        assertTrue(sent.isEmpty())
        val preview = flow.vorschau(snapshot, "peer", "self", 2)
        flow.bestaetigen(preview.id)
        assertEquals(2, sent.size)
        assertTrue(sent.all { it["fassung"] == JsonPrimitive(2) })
        assertEquals(JsonPrimitive("--06-07"), (sent.last()["kontakt"] as JsonObject)["jubilaeum"])
        assertEquals(JsonPrimitive(""), (sent.last()["kontakt"] as JsonObject)["vorname"])
    }
}
