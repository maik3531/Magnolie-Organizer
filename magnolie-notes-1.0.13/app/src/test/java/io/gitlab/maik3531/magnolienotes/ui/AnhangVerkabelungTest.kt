package io.gitlab.maik3531.magnolienotes.ui

import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.File

class AnhangVerkabelungTest {
    @Test fun `Editor und Activity enthalten die vollstaendige SAF Verkabelung`() {
        val wurzel = File(System.getProperty("user.dir"))
        val editor = File(wurzel, "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/NotizBlatt.kt").readText()
        val activity = File(wurzel, "app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        assertTrue(editor.contains("R.string.notiz_anhang_hinzufuegen"))
        assertTrue(editor.contains("beiAnhangHinzufuegen"))
        assertTrue(activity.contains("ActivityResultContracts.OpenDocument()"))
        assertTrue(activity.contains("Intent.ACTION_CREATE_DOCUMENT"))
        assertTrue(activity.contains("input.mime"))
        assertTrue(activity.contains("Intent.EXTRA_TITLE"))
        assertTrue(activity.contains("AnhangDatei.speichern"))
        assertTrue(editor.contains("beiAnhangOeffnen: (Anhang) -> Unit"))
        assertTrue(editor.contains("beiAnhangSpeichern: (Anhang) -> Unit"))
        assertTrue(editor.contains("R.string.notiz_anhang_oeffnen"))
        assertTrue(editor.contains("R.string.notiz_anhang_speichern"))
        assertTrue(editor.contains("R.string.notiz_anhang_entfernen"))
        assertTrue(editor.contains("beiAnhaengeAenderung(anhaenge.filterNot"))
        listOf("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf").forEach {
            assertTrue(activity.contains("\"$it\""))
        }
    }

    @Test fun `Editor wechselt nur bei Platzbedarf in den Scrollmodus`() {
        val wurzel = File(System.getProperty("user.dir"))
        val editor = File(wurzel, "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/NotizBlatt.kt").readText()
        val manifest = File(wurzel, "app/src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android:windowSoftInputMode=\"adjustResize\""))
        assertTrue(editor.contains("BoxWithConstraints("))
        assertTrue(editor.contains("WindowInsets.ime.getBottom(density) > 0"))
        assertTrue(editor.contains("Modifier.weight(1f).navigationBarsPadding().imePadding()"))
        assertTrue(editor.contains(".imePadding()"))
        assertTrue(editor.contains("Modifier.verticalScroll(scrollState)"))
        assertTrue(editor.contains("Modifier.weight(1f).heightIn(min = 220.dp)"))
        assertTrue(editor.contains("val kompakteTextHoehe = (maxHeight - 28.dp).coerceAtLeast(220.dp)"))
    }

    @Test fun `normale Editorhoehe bleibt ohne Anhang ungescrollt`() {
        assertFalse(notizEditorKompakt(640f, 1f, false, 0))
    }

    @Test fun `sichtbare IME erzwingt kompakten Editor`() {
        assertTrue(notizEditorKompakt(640f, 1f, true, 0))
    }

    @Test fun `kleine Editorhoehe erzwingt kompakten Editor`() {
        assertTrue(notizEditorKompakt(520f, 1f, false, 0))
    }

    @Test fun `grosse Schrift erzwingt kompakten Editor`() {
        assertTrue(notizEditorKompakt(640f, 1.3f, false, 0))
    }

    @Test fun `ein Anhang passt bei normaler Hoehe aber mehrere scrollen`() {
        assertFalse(notizEditorKompakt(640f, 1f, false, 1))
        assertTrue(notizEditorKompakt(640f, 1f, false, 2))
    }
}
