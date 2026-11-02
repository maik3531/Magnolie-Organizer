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

/** Actual selection/layout recomposition; no printer or personal print job is used. */
@OptIn(InternalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28], qualifiers = "de")
class ZeitMonatsDruckUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private val trash = mutableStateOf(true)
    private val visible = mutableStateOf(true)
    private val selection = mutableStateOf<ZeitMonatsDruckAuswahl?>(null)
    private var frame = 0L
    private var saves = 0
    private var registrations = 0

    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent { MagnolieThema {
            androidx.compose.material3.Text(selection.value?.name.orEmpty())
            if (visible.value) ZeitMonate(ZeiterfassungStand(reportName = "Synthetic report"), false,
                { _, _ -> saves++ }, {}, PapierkorbEinstellungen(trash.value, 0),
                beiDruckAuswahl = { selection.value = it; registrations++ })
        } }
        controller!!.start().resume().visible().windowFocusChanged(true)
        frames()
    }

    private fun frames() {
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(600, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(1400, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 600, 1400)
        }
    }
    private fun nodes(): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        return collect((view.getChildAt(0) as ViewRootForTest).semanticsOwner.rootSemanticsNode)
    }
    private fun text(node: SemanticsNode) = node.config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text }.orEmpty()
    private fun button(label: Int) = nodes().single { text(it) == controller!!.get().getString(label) &&
        it.config.getOrNull(SemanticsActions.OnClick) != null }

    @Test fun emptyMonthStillRegistersAllWritingDaysAndNoLargePrintButtonRemains() {
        launch()
        val value = selection.value!!
        assertEquals((1..value.monat.lengthOfMonth()).toSet(), value.tage)
        assertEquals("Synthetic report", value.name)
        assertTrue(nodes().none { text(it) == controller!!.get().getString(R.string.zeit_drucken) })
        assertEquals(0, saves)
        frames(); assertTrue("Registration must settle, not cause an endless composition loop", registrations < 10)
        visible.value = false; frames(); assertNull(selection.value)
    }

    @Test fun monthRemovalAndTrashStayBesideEachOtherAndDisabledTrashDisappears() {
        launch()
        val remove = button(R.string.zeit_monat_entfernen); val bin = button(R.string.papierkorb_titel)
        assertTrue(remove.positionInRoot.x < bin.positionInRoot.x)
        assertEquals(remove.positionInRoot.y + remove.size.height / 2f, bin.positionInRoot.y + bin.size.height / 2f, 1f)
        trash.value = false; frames()
        assertTrue(nodes().none { text(it) == controller!!.get().getString(R.string.papierkorb_titel) })
    }

    @Test fun selectedDaysReachTheHeaderSelectionWithoutSavingOrPrinting() {
        launch()
        val allDays = nodes().single { it.config.getOrNull(SemanticsProperties.ToggleableState) != null &&
            it.config.getOrNull(SemanticsActions.OnClick) != null }
        allDays.config[SemanticsActions.OnClick].action!!.invoke(); frames()
        assertTrue(selection.value!!.tage.isEmpty())
        val days = nodes().filter { it.config.getOrNull(SemanticsProperties.ToggleableState) != null &&
            it.config.getOrNull(SemanticsActions.OnClick) != null }
        days[1].config[SemanticsActions.OnClick].action!!.invoke(); frames()
        assertEquals(setOf(1), selection.value!!.tage)
        assertEquals(0, saves)
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
