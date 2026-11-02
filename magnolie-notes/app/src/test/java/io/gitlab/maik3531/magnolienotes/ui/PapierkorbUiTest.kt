package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.os.Looper
import android.view.View
import androidx.activity.ComponentActivity
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.InternalComposeUiApi
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.journal.JournalZustand
import io.gitlab.maik3531.magnolienotes.sicherung.AutoSicherungsZustand
import kotlinx.coroutines.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import java.time.Duration

@OptIn(InternalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28], qualifiers = "de")
class PapierkorbUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private val book = mutableStateOf(Bestand())
    private val busy = mutableStateOf(false)
    private var frame = 0L
    private val calls = mutableListOf<String>()

    private fun handlers() = JournalHandlungen(
        beiIntervall = {}, beiMaximum = {}, beiJetzt = {}, beiWiederherstellen = { _, _, _ -> false },
        beiLoeschen = {}, beiPapierkorbSchalter = { _, _ -> }, beiPapierkorbTage = { _, _ -> },
        beiPapierkorbWiederherstellen = { calls += "restore-note:$it" }, beiPapierkorbLoeschen = {},
        beiPapierkorbLeeren = { calls += "clear:${it.size}" }, absturzberichtVorhanden = false,
        beiAbsturzberichtTeilen = {}, portableImportBereit = false, portableVorschau = null,
        portableLaeuft = false, portableFehler = false, beiPortableExport = {}, beiPortableDatei = {},
        beiPortablePruefen = {}, beiPortableWiederherstellen = {}, beiPortableAbbrechen = {},
        autoSicherung = AutoSicherungsZustand(), beiAutoOrdner = {}, beiAutoPasswort = {},
        beiAutoAktiv = {}, beiAutoIntervall = {}, beiAutoAufbewahrung = {}, beiAutoJetzt = {},
        zeitSpeichert = busy.value, beiZeitWiederherstellen = { calls += "restore-time:$it" })

    private fun mixed(): Bestand {
        val now = System.currentTimeMillis()
        val time = ZeiterfassungStand(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, type = "Synthetic time"))
        val note = PapierkorbLogik.loescheNotiz(Bestand(notizen = listOf(Notiz("synthetic", titel = "Synthetic note"))), "synthetic", now - 1000)
        return note.copy(zeiterfassung = time.removeLocal(time.entries, now),
            papierkorbEinstellungen = PapierkorbEinstellungen(true, 0))
    }

    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent { MagnolieThema { JournalBlatt(JournalZustand(), book.value, handlers()) } }
        controller!!.start().resume().visible().windowFocusChanged(true)
        frames()
    }

    private fun frames() {
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(600, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(1200, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 600, 1200)
        }
    }

    private fun nodes(): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        return collect((view.getChildAt(0) as ViewRootForTest).semanticsOwner.rootSemanticsNode)
    }
    private fun text(node: SemanticsNode) = node.config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text }.orEmpty()
    private fun clearButtons() = nodes().filter { text(it) == controller!!.get().getString(R.string.papierkorb_leeren) &&
        it.config.getOrNull(SemanticsActions.OnClick) != null }

    @Test fun mixedTrashHasOneClearActionAndInterleavesTypesByDeletionTime() {
        book.value = mixed(); launch()
        assertEquals(1, clearButtons().size)
        val texts = nodes().map(::text)
        assertTrue(texts.indexOf("Synthetic time") < texts.indexOfFirst { it.contains("Synthetic note") })
        val restores = nodes().filter { text(it) == controller!!.get().getString(R.string.journal_restore) &&
            it.config.getOrNull(SemanticsActions.OnClick) != null }
        assertEquals(2, restores.size)
        restores.forEach { it.config[SemanticsActions.OnClick].action!!.invoke() }
        assertTrue(calls[0].startsWith("restore-time:")); assertTrue(calls[1].startsWith("restore-note:"))
    }

    @Test fun timeOnlyTrashCanBeEmptiedButBusyStateDisablesTheAction() {
        book.value = mixed().copy(papierkorb = emptyList()); launch()
        assertEquals(1, clearButtons().size)
        busy.value = true; frames()
        assertNotNull(clearButtons().single().config.getOrNull(SemanticsProperties.Disabled))
        assertTrue(calls.isEmpty())
    }

    @Test fun disablingHidesBothTypesRetentionAndClearWithoutMutatingTheBook() {
        val original = mixed()
        book.value = original; launch()
        book.value = original.copy(papierkorbEinstellungen = PapierkorbEinstellungen(false, 0)); frames()
        assertTrue(clearButtons().isEmpty())
        assertTrue(nodes().none { text(it).contains("Synthetic") || text(it) == "365" })
        assertEquals(original.papierkorb, book.value.papierkorb)
        assertEquals(original.zeiterfassung.trash, book.value.zeiterfassung.trash)
        book.value = original; frames()
        assertEquals(1, clearButtons().size)
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
