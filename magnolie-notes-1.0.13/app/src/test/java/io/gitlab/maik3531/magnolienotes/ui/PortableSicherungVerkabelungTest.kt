package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class PortableSicherungVerkabelungTest {
    @Test fun `SAF Vorschau und bestehender Restore sind getrennt verdrahtet`() {
        val activity = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        val ui = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/JournalBlatt.kt").readText()
        val ablage = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/Ablage.kt").readText()
        assertTrue(activity.contains("Intent.ACTION_CREATE_DOCUMENT"))
        assertTrue(activity.contains("ActivityResultContracts.OpenDocument()"))
        assertFalse(activity.contains("OpenDocumentTree") && activity.contains("portableImport.launch(null)"))
        assertTrue(ui.contains("portableVorschau"))
        assertTrue(ui.contains("portable_restore_warnung"))
        assertTrue(ablage.contains("portableWiederherstellen"))
        assertTrue(ablage.contains("json.encodeToString(Baumzustand.serializer(), _baum.value)"))
        assertTrue(activity.contains("journal.restorePortable"))
    }

    @Test fun `generische Einfuhr weist vollstaendiges Archiv weiter ab`() {
        val import = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/einfuhr/Einfuhr.kt").readText()
        assertTrue(import.contains("PortableArchiv.istArchiv(roh)"))
        assertTrue(import.contains("throw GesamtarchivNichtUnterstuetzt()"))
    }
}
