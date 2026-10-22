package io.gitlab.maik3531.magnolienotes

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

class DiagnoseMaskierungTest {
    @Test fun sharedVectorsMaskCredentialsAndContactsWithoutLosingTechnicalContext() {
        val source = listOf(File("../contracts/diagnostics-redaction-v1.json"), File("contracts/diagnostics-redaction-v1.json")).first { it.isFile }
        for (node in Json.parseToJsonElement(source.readText()).jsonObject.getValue("cases").jsonArray) {
            val entry = node.jsonObject
            val text = entry.getValue("input").jsonPrimitive.content
            val expected = entry.getValue("expected").jsonPrimitive.content
            assertEquals(expected, DiagnoseMaskierung.maskiere(text))
            assertEquals(expected, DiagnoseMaskierung.maskiere(expected))
        }
    }
}
