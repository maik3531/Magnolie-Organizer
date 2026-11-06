package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.os.Looper
import android.view.View
import android.view.ViewGroup
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
import org.robolectric.shadows.ShadowDialog
import java.time.Duration
import java.time.Instant

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
    private val time = mutableStateOf(ZeiterfassungStand(reportName = "Synthetic report"))
    private var nativeRemoval = false
    private val removedScopes = mutableListOf<String?>()
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
            if (visible.value) ZeitMonate(time.value, false,
                { change, done -> saves++; time.value = change(time.value); done() }, {}, PapierkorbEinstellungen(trash.value, 0),
                beiEntfernen = if (nativeRemoval) ({ entries, month, policy, done ->
                    removedScopes += month; time.value = time.value.removeLocal(entries, month = month, papierkorb = policy); done()
                }) else null,
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
    private fun nodes(root: View = view): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        if (root is ViewRootForTest) return collect(root.semanticsOwner.rootSemanticsNode)
        return if (root is ViewGroup) (0 until root.childCount).flatMap { nodes(root.getChildAt(it)) } else emptyList()
    }
    private fun text(node: SemanticsNode) = node.config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text }.orEmpty()
    private fun button(label: Int) = nodes().single { text(it) == controller!!.get().getString(label) &&
        it.config.getOrNull(SemanticsActions.OnClick) != null }
    private fun click(node: SemanticsNode) { assertTrue(node.config[SemanticsActions.OnClick].action!!.invoke()); frames() }
    private fun confirm() = click(nodes(ShadowDialog.getLatestDialog().window!!.decorView).single {
        text(it) == controller!!.get().getString(R.string.loeschen) && it.config.getOrNull(SemanticsActions.OnClick) != null })
    private fun checks() = nodes().filter { it.config.getOrNull(SemanticsProperties.ToggleableState) != null &&
        it.config.getOrNull(SemanticsActions.OnClick) != null }
    private fun entry(day: Int, month: String = "2026-11", hour: Int = 8): Zeiteintrag {
        val start = Instant.parse("$month-${day.toString().padStart(2, '0')}T${hour.toString().padStart(2, '0')}:00:00Z").epochSecond / 60
        return Zeiteintrag(startMinute = start, endMinute = start + 60, zone = "UTC")
    }

    private fun selectedRemoval(native: Boolean) {
        nativeRemoval = native
        val originals = listOf(entry(1), entry(1, hour = 10), entry(2), entry(3), entry(31, "2026-10"))
        time.value = time.value.copy(actor = "11111111-1111-4111-8111-111111111111", entries = originals)
        launch()
        assertEquals("Auswahl entfernen", controller!!.get().getString(R.string.zeit_monat_entfernen))
        click(checks().single())
        assertNotNull(button(R.string.zeit_monat_entfernen).config.getOrNull(SemanticsProperties.Disabled))
        click(checks()[1]); click(checks()[3])
        assertEquals(setOf(1, 3), selection.value!!.tage)
        click(button(R.string.zeit_monat_entfernen))
        assertTrue(ShadowDialog.getLatestDialog().isShowing)
        assertEquals(originals, time.value.entries)
        // The confirmation owns a frozen selection, not later additions on an
        // already selected date or all other records of the displayed month.
        val later = entry(1, hour = 12); time.value = time.value.copy(entries = time.value.entries + later); frames()
        confirm()
        assertEquals(setOf(originals[2].id, originals[4].id, later.id), time.value.entries.map { it.id }.toSet())
        assertEquals(setOf(originals[0].id, originals[1].id, originals[3].id), time.value.trash.single().entries.map { it.id }.toSet())
        assertNull(time.value.trash.single().month); assertTrue(time.value.removedMonths.isEmpty())
        assertFalse(time.value.suppressIncoming(entry(2, hour = 12)))
        assertEquals(if (native) listOf<String?>(null) else emptyList<String?>(), removedScopes)
    }

    @Test fun selectedRemovalLimitsActualFallbackMutationAndDoesNotSuppressTheWholeMonth() = selectedRemoval(false)
    @Test fun selectedRemovalPassesOnlyFrozenDaysAndNoMonthScopeToTheNativeCallback() = selectedRemoval(true)

    @Test fun explicitAllDaysStillRemovesTheDisplayedMonthOnly() {
        val entries = listOf(entry(1), entry(2), entry(31, "2026-10"))
        time.value = time.value.copy(actor = "11111111-1111-4111-8111-111111111111", entries = entries)
        launch(); click(button(R.string.zeit_monat_entfernen)); confirm()
        assertEquals(listOf(entries[2]), time.value.entries)
        assertEquals(setOf("2026-11"), time.value.removedMonths)
        assertEquals("2026-11", time.value.trash.single().month)
    }

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
