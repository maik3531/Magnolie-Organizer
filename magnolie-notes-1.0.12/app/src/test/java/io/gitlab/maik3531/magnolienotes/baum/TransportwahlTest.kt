package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Partner
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.serialization.json.JsonObject

class TransportwahlTest {

    @Test
    fun `WLAN wird zuerst und Bluetooth als Rueckfall versucht`() {
        val wege = Versand.wegeZu(
            Partner(
                kennung = "zweig",
                adresse = "192.0.2.7",
                fernAdresse = "notes.example.org",
                fernPort = 9876,
                bluetooth = "AA:BB:CC:DD:EE:FF"
            ),
            bluetoothErlaubt = true
        )

        assertEquals(3, wege.size)
        assertTrue(wege[0] is WlanTransport)
        assertEquals("192.0.2.7:8737", wege[0].bezeichnung)
        assertEquals("notes.example.org:9876", wege[1].bezeichnung)
        assertTrue(wege[2] is BluetoothTransport)
    }

    @Test
    fun `abgeschaltetes Bluetooth erzeugt keinen Rueckfall`() {
        val wege = Versand.wegeZu(
            Partner(
                kennung = "zweig",
                adresse = "192.0.2.7",
                bluetooth = "AA:BB:CC:DD:EE:FF"
            ),
            bluetoothErlaubt = false
        )

        assertEquals(1, wege.size)
        assertTrue(wege.single() is WlanTransport)
    }

    @Test
    fun `gleiches lokales und entferntes Ziel wird nur einmal versucht`() {
        val wege = Versand.wegeZu(
            Partner(
                kennung = "zweig",
                adresse = "example.test",
                port = 8737,
                fernAdresse = "example.test",
                fernPort = 8737
            ),
            bluetoothErlaubt = true
        )

        assertEquals(listOf("example.test:8737"), wege.map { it.bezeichnung })
    }

    @Test
    fun `Dateipaarung versucht LAN vor Bluetooth und merkt erfolgreichen Weg`() {
        val aufrufe = mutableListOf<String>()
        fun transport(name: String, fehlschlag: Boolean) = object : Transport {
            override val bezeichnung = name
            override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
                aufrufe += name
                if (fehlschlag) throw BaumFehler("nicht erreichbar")
                return JsonObject(emptyMap())
            }
        }
        val bluetooth = Versand.Paarungsweg(
            transport("bluetooth", false), "AA:BB:CC:DD:EE:FF"
        )

        val (_, erfolgreich) = Versand.fragePaarung(
            listOf(Versand.Paarungsweg(transport("lan", true)), bluetooth),
            JsonObject(emptyMap())
        )

        assertEquals(listOf("lan", "bluetooth"), aufrufe)
        assertEquals("AA:BB:CC:DD:EE:FF", erfolgreich.bluetooth)
    }
}
