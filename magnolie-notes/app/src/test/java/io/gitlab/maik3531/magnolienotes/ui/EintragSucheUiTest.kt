package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.os.Looper
import android.view.View
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.InternalComposeUiApi
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.Density
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId

@OptIn(InternalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35], qualifiers = "de")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class EintragSucheUiTest {
    private class Liste(private val breite: Int, private val schrift: Float, initialAufgaben: Boolean = false) : AutoCloseable {
        private val clock = BroadcastFrameClock()
        private var failure: Throwable? = null
        private val scope = CoroutineScope(Dispatchers.Main + clock + Job() + CoroutineExceptionHandler { _, error -> failure = error })
        private val recomposer = Recomposer(scope.coroutineContext)
        private val controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        private val view = ComposeView(controller.get()).apply { setParentCompositionContext(recomposer) }
        private val bitmap = Bitmap.createBitmap(breite, 1000, Bitmap.Config.ARGB_8888)
        val aufgaben = mutableStateOf(initialAufgaben)
        private var committed = "none"
        val neu = mutableListOf<String>()
        private var nanos = 0L
        init {
            controller.get().setContentView(view)
            scope.launch { recomposer.runRecomposeAndApplyChanges() }
            val september = LocalDate.of(2026, 9, 18).atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
            view.setContent {
                CompositionLocalProvider(LocalDensity provides Density(1f, schrift)) { MagnolieThema {
                    SideEffect { committed = if (aufgaben.value) "tasks" else "notes" }
                    if (aufgaben.value) AufgabenBlatt(
                        listOf(Aufgabe("a", titel = "September-Aufgabe", faellig = "2026-09-20"), Aufgabe("b", titel = "Juli-Aufgabe", faellig = "2026-07-01")),
                        beiOeffnen = {}, beiAbhaken = { _, _ -> }, beiNeu = { neu += "task" }, beiTeilaufgabe = {},
                        beiVerschieben = { _, _ -> }, beiWurzel = {}, beiLoeschen = { true }, beiAbgleichen = {})
                    else NotizBlatt(listOf(Notiz("a", titel = "September-Notiz", angelegt = september), Notiz("b", titel = "Juli-Notiz")),
                        emptyList(), {}, { neu += "note" }, { true }, {})
                } }
            }
            controller.start().resume().visible().windowFocusChanged(true); frames()
        }
        fun frames() { repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            nanos += 16_000_000; clock.sendFrame(nanos)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.forceLayout()
            view.getChildAt(0)?.forceLayout()
            controller.get().window.decorView.apply {
                forceLayout()
                measure(View.MeasureSpec.makeMeasureSpec(breite, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(1000, View.MeasureSpec.EXACTLY))
                layout(0, 0, breite, 1000); draw(Canvas(bitmap))
            }
            failure?.let { throw AssertionError("Compose failed", it) }
        } }
        fun nodes(): List<SemanticsNode> {
            fun collect(n: SemanticsNode): List<SemanticsNode> = listOf(n) + n.children.flatMap(::collect)
            return collect((view.getChildAt(0) as ViewRootForTest).semanticsOwner.rootSemanticsNode)
        }
        fun feld() = nodes().singleOrNull { it.config.contains(SemanticsActions.SetText) }
            ?: error("Search missing; committed=$committed, state=${recomposer.currentState.value}, view=${view.width}x${view.height}; visible=" + nodes().mapNotNull { it.config.getOrNull(SemanticsProperties.Text)?.joinToString { t -> t.text } }.take(20))
        fun knopf(wert: String) = nodes().first { it.config.contains(SemanticsActions.OnClick) && it.config.getOrNull(SemanticsProperties.Text)?.any { t -> t.text == wert } == true }
        fun sichtbar(wert: String) = nodes().any { it.config.getOrNull(SemanticsProperties.Text)?.any { t -> t.text == wert } == true }
        fun suche(wert: String) { assertTrue(feld().config[SemanticsActions.SetText].action!!.invoke(AnnotatedString(wert))); frames() }
        override fun close() { controller.pause().stop().destroy(); recomposer.cancel(); scope.cancel(); bitmap.recycle() }
    }

    @Test fun beideListenSuchenNachMonatUndTextUndLeerenStelltAlleEintraegeWiederHer() {
        Liste(480, 1f).use { ui ->
            ui.suche("09.2026"); assertTrue(ui.sichtbar("September-Notiz")); assertFalse(ui.sichtbar("Juli-Notiz"))
            ui.suche("09.26"); assertTrue(ui.sichtbar("September-Notiz")); assertFalse(ui.sichtbar("Juli-Notiz"))
            ui.suche(""); assertTrue(ui.sichtbar("Juli-Notiz"))
            ui.aufgaben.value = true; ui.frames()
            ui.suche("09.26"); assertTrue(ui.sichtbar("September-Aufgabe")); assertFalse(ui.sichtbar("Juli-Aufgabe"))
            ui.suche("jULi"); assertTrue(ui.sichtbar("Juli-Aufgabe")); assertFalse(ui.sichtbar("September-Aufgabe"))
            ui.suche(""); assertTrue(ui.sichtbar("September-Aufgabe")); assertTrue(ui.sichtbar("Juli-Aufgabe"))
        }
    }

    @Test fun aufgabenSuchfeldIstAuchOhneVorherigeNotizseiteBenutzbar() {
        Liste(480, 1f, initialAufgaben = true).use { ui ->
            ui.suche("09.26")
            assertTrue(ui.sichtbar("September-Aufgabe")); assertFalse(ui.sichtbar("Juli-Aufgabe"))
        }
    }

    @Test fun suchfeldUndNeuKnopfHabenInBeidenListenAuchBeiGrosserSchriftIdentischeMasse() {
        for ((width, scale) in listOf(480 to 1f, 320 to 2f)) Liste(width, scale).use { ui ->
            val field = ui.feld().boundsInRoot
            val fieldSize = ui.feld().size
            val noteButton = ui.knopf("Neue Notiz").boundsInRoot
            ui.knopf("Neue Notiz").config[SemanticsActions.OnClick].action!!.invoke()
            ui.aufgaben.value = true; ui.frames()
            val taskField = ui.feld().boundsInRoot
            val taskFieldSize = ui.feld().size
            val taskButton = ui.knopf("Neue Aufgabe").boundsInRoot
            assertEquals("field width $width/$scale", field.width, taskField.width, 0.5f)
            assertEquals("field height $width/$scale; measured $fieldSize/$taskFieldSize; bounds $field/$taskField", field.height, taskField.height, 0.5f)
            assertEquals(noteButton.width, taskButton.width, 0.5f); assertEquals(noteButton.height, taskButton.height, 0.5f)
            assertEquals(noteButton.top, taskButton.top, 0.5f)
            assertTrue(taskField.width > 0f)
            ui.knopf("Neue Aufgabe").config[SemanticsActions.OnClick].action!!.invoke()
            assertEquals(listOf("note", "task"), ui.neu)
        }
    }
}
