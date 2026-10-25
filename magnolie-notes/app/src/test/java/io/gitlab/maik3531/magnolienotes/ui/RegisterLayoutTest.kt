package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class RegisterLayoutTest {
    private val root = File(requireNotNull(System.getProperty("user.dir")))

    @Test fun `konfigurierbare Register bleiben gleich hoch und einzeilig`() {
        val source = File(root,
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/Bausteine.kt").readText()
        assertTrue(source.contains(".height(58.dp)"))
        assertTrue(source.contains("Registersymbol(symbole.getOrElse(platz) { platz }, farbe)"))
        assertTrue(source.contains("maxLines = 1"))
        assertFalse(source.contains("maxLines = if (lang) 2 else 1"))
        assertTrue(source.contains("role = Role.Tab") && source.contains("selected = aktiv"))
    }

    @Test fun `Verbindungen ist in jeder Sprache ein vollstaendiger einzeiliger Menueeintrag`() {
        val factory = DocumentBuilderFactory.newInstance()
        val files = File(root, "app/src/main/res").listFiles().orEmpty()
            .filter { it.isDirectory && (it.name == "values" || it.name.startsWith("values-")) }
            .map { File(it, "strings.xml") }.filter(File::isFile)
        assertEquals(20, files.size)
        for (file in files) {
            val locale = file.parentFile?.name.orEmpty()
            val document = factory.newDocumentBuilder().parse(file)
            val nodes = document.getElementsByTagName("string")
            val label = (0 until nodes.length).map { nodes.item(it) }
                .first { it.attributes.getNamedItem("name")?.nodeValue == "blatt_baum" }.textContent.trim()
            // This resource names a full-width settings/intro entry, not a bottom tab.
            assertTrue("$locale: Verbindungsname fehlt", label.isNotBlank())
            assertFalse("$locale: Verbindungsname enthält einen Umbruch", label.contains('\n'))
            if (locale == "values") assertEquals("Connections", label)
            if (locale == "values-de") assertEquals("Verbindungen", label)
        }
    }
}
