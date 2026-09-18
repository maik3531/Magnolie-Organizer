package io.gitlab.maik3531.magnolienotes.baum

import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PaarungsLinkTest {
    @Test fun dekodiertUnveraendertenPaarungstext() {
        val text = "{\"magnolie\":\"magnolie-paarungsdatei\",\"fassung\":2}"
        val code = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(text.toByteArray(Charsets.UTF_8))
        assertEquals(text, PaarungsLink.dekodiere("magnolie-pair:$code"))
    }

    @Test fun lehntFremdeUndBeschaedigteLinksAb() {
        assertNull(PaarungsLink.dekodiere("https://example.org/abc"))
        assertNull(PaarungsLink.dekodiere("magnolie-pair:not+base64"))
        assertNull(PaarungsLink.dekodiere("magnolie-pair:"))
        assertNull(PaarungsLink.dekodiere("magnolie-pair:" + "a".repeat(8_200)))
    }

    @Test fun vorschauPrueftEinladungUndZeigtGegenstelleOhneGeheimnis() {
        val vektoren = Kanonisch.json.parseToJsonElement(
            javaClass.classLoader!!.getResourceAsStream("vektoren.json")!!
                .bufferedReader().readText()).jsonObject
        val paarung = vektoren.getValue("paarungsdatei").jsonObject
        val dokument = paarung.getValue("dokument").jsonObject
        val jetzt = paarung.getValue("jetzt").jsonPrimitive.content.toLong()
        val text = Kanonisch.json.encodeToString(JsonObject.serializer(), dokument)

        val vorschau = PaarungsLink.vorschau(text, jetzt)

        assertTrue(vorschau.name.isNotBlank())
        assertTrue(vorschau.adresse.contains(":"))
        assertTrue(vorschau.fingerabdruck.isNotBlank())
        assertEquals(text, vorschau.text)
    }
}
