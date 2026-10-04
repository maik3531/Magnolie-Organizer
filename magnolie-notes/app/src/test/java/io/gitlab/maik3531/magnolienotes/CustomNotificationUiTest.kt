package io.gitlab.maik3531.magnolienotes

import android.content.Intent
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.semantics.*
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.baum.Baumwerk
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal
import io.gitlab.maik3531.magnolienotes.sicherung.AndroidAutoSicherung
import io.gitlab.maik3531.magnolienotes.telefon.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import java.security.Provider
import java.security.Security
import java.time.Duration
import javax.crypto.spec.SecretKeySpec
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

/** Actual Compose navigation/scroll semantics under Robolectric, not a device test. */
@RunWith(RobolectricTestRunner::class)
@Config(application = MagnolieApp::class, sdk = [28], shadows = [CustomNavigationAppShadow::class])
class CustomNotificationUiTest {
    private lateinit var app: MagnolieApp
    private lateinit var ablage: Ablage
    private var controller: ActivityController<MainActivity>? = null
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var frameNanos = 0L
    private val fields = listOf(Ablage::class.java to "einzig", Baumwerk::class.java to "einzig",
        TelefonAblage::class.java to "instance", TelefonWerk::class.java to "instance",
        AndroidJournal::class.java to "instance", AndroidAutoSicherung::class.java to "instanz")
        .map { (type, name) -> type.getDeclaredField(name).apply { isAccessible = true } }
    private var previous = emptyList<Any?>()
    private val provider = object : Provider("CustomNavigationTestKeys", 1.0, "Synthetic keys only") {
        init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
    }

    @Before fun setup() {
        app = ApplicationProvider.getApplicationContext()
        previous = fields.map { it.get(null) }
        fields.forEach { it.set(null, null) }
        Security.insertProviderAt(provider, 1)
        ablage = Ablage.fuerTest(app) { SecretKeySpec(ByteArray(32) { 29 }, "AES") }
        fields.first().set(null, ablage)
        TelefonAblage.get(app).savePeer(TelefonPeer("fixture", "Fixture", "public-key", own_device = true,
            remote_own_device = true, remote_personal_tasks_sync_available = true,
            remote_personal_tasks_sync_versions = listOf(4)))
        ablage.personalCustomChange {
            val state = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
            val item = state.items.values.single()
            val otherId = PersonalSyncProtokoll.customSourceId(item.source, "other-item")
            val value = JsonObject(item.record.getValue("value").jsonObject + mapOf(
                "title" to JsonPrimitive("Unrelated item before the target"), "note" to JsonPrimitive("Other content\n".repeat(80))))
            val record = JsonObject(item.record + mapOf("id" to JsonPrimitive(otherId), "item_id" to JsonPrimitive("other-item"),
                "value" to value, "hash" to JsonPrimitive(PersonalSync.hash(value))))
            state.copy(items = linkedMapOf(otherId to item.copy(record = record)) + state.items)
        }
        Ersteinrichtung.abschliessen(app)
        app.startZustandFuerInstrumentation(StartZustand.Bereit)
    }

    @After fun cleanup() {
        controller?.pause()?.stop()?.destroy()
        recomposer.cancel()
        scope.cancel()
        fields.zip(previous).forEach { (field, value) -> field.set(null, value) }
        Security.removeProvider(provider.name)
    }

    private fun intent(): Intent {
        val state = ablage.bestand.value.personalCustom
        val target = state.items.entries.single { it.value.record.getValue("value").jsonObject.getValue("title").jsonPrimitive.content == "Water plants" }
        return CustomNavigation.absicht(app, state, target.key)
    }

    private fun launch(intent: Intent = Intent(app, MainActivity::class.java)) {
        controller = Robolectric.buildActivity(MainActivity::class.java, intent).create()
        val content = controller!!.get().findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as ComposeView
        content.setParentCompositionContext(recomposer)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        controller!!.start().resume().visible().windowFocusChanged(true)
        frames()
    }

    private fun frames() {
        val view = controller!!.get().window.decorView
        val bitmap = android.graphics.Bitmap.createBitmap(480, 800, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(bitmap)
        repeat(60) {
            Snapshot.sendApplyNotifications()
            shadowOf(Looper.getMainLooper()).idle()
            frameNanos += 16_000_000
            clock.sendFrame(frameNanos)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(800, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 480, 800)
            view.draw(canvas)
        }
        bitmap.recycle()
    }

    private fun nodes(): List<SemanticsNode> {
        fun owner(view: View): SemanticsOwner? {
            view.javaClass.methods.firstOrNull { it.name == "getSemanticsOwner" && it.parameterCount == 0 }
                ?.let { return it.invoke(view) as SemanticsOwner }
            if (view is ViewGroup) for (index in 0 until view.childCount) owner(view.getChildAt(index))?.let { return it }
            return null
        }
        fun walk(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::walk)
        return walk(checkNotNull(owner(controller!!.get().window.decorView)).unmergedRootSemanticsNode)
    }

    private fun tab(resource: Int) = nodes().single {
        it.config.getOrNull(SemanticsProperties.ContentDescription) == listOf(app.getString(resource)) &&
            it.config.getOrNull(SemanticsProperties.Role) == Role.Tab
    }

    private fun clickText(resource: Int) {
        val text = app.getString(resource)
        fun contains(node: SemanticsNode): Boolean = node.config.getOrNull(SemanticsProperties.Text)
            ?.any { it.text == text } == true || node.children.any(::contains)
        nodes().first { it.config.getOrNull(SemanticsActions.OnClick) != null && contains(it) }
            .config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
    }

    private fun awaitEditorClose() {
        // Rendering virtual frames does not wait for the real Dispatchers.IO save.
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
        do {
            frames()
            if (ablage.entwurf.value == EditorEntwurf() && nodes().any {
                    it.config.getOrNull(SemanticsProperties.Role) == Role.Tab
                }) {
                frames()
                return
            }
            Thread.sleep(5)
        } while (System.nanoTime() < deadline)
        fail("Editor did not complete its asynchronous save and return to the tabs")
    }

    private fun assertCustomVisibleAndReadOnly(saved: Notiz? = null) {
        assertEquals(true, tab(R.string.zeit_einstellungen).config.getOrNull(SemanticsProperties.Selected))
        val target = nodes().single { node -> node.config.getOrNull(SemanticsProperties.Text)
            ?.any { it.text.contains("Water plants") } == true }
        assertTrue("Custom text must be scrolled into the viewport", target.boundsInRoot.height > 0 && target.boundsInRoot.top >= 0)
        fun containsTarget(node: SemanticsNode): Boolean = node.config.getOrNull(SemanticsProperties.Text)
            ?.any { it.text.contains("Water plants") } == true || node.children.any(::containsTarget)
        assertTrue("The requested row, not the first Custom row, must receive focus", nodes().any {
            it.config.getOrNull(SemanticsProperties.Focused) == true && containsTarget(it) })
        assertEquals(EditorEntwurf(), ablage.entwurf.value)
        assertEquals(saved?.let { listOf(it.id) }.orEmpty(), ablage.notizen().map { it.id })
        saved?.let { assertEquals(it.text, ablage.notiz(it.id)?.text) }
        assertTrue(ablage.aufgaben().isEmpty())
        assertNull(controller!!.get().gewuenschtesCustom.value)
    }

    @Test fun coldStartSelectsTreeAndScrollsToReadOnlyCustomContent() {
        launch(intent())
        assertCustomVisibleAndReadOnly()
    }

    @Test fun warmNotificationLeavesAnotherTabAndFocusesCustomContent() {
        launch()
        tab(R.string.zeit_einstellungen).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        clickText(R.string.blatt_einfuhr)
        frames()
        assertEquals(true, tab(R.string.zeit_einstellungen).config.getOrNull(SemanticsProperties.Selected))
        assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.Text)
            ?.any { text -> text.text == app.getString(R.string.einfuhr_datei_knopf) } == true })
        controller!!.newIntent(intent())
        frames()
        assertCustomVisibleAndReadOnly()
        controller!!.newIntent(intent())
        frames()
        assertCustomVisibleAndReadOnly()
    }

    @Test fun draftDefersNavigationUntilTheEditorFinishes() {
        val draft = Notiz("unsaved", text = "Retained editor text")
        ablage.setzeNotizEntwurf(draft)
        launch(intent())
        assertEquals(draft, ablage.entwurf.value.notiz)
        assertNotNull(controller!!.get().gewuenschtesCustom.value)
        assertTrue(nodes().any { it.config.getOrNull(SemanticsActions.SetText) != null })
        controller!!.get().onBackPressedDispatcher.onBackPressed()
        awaitEditorClose()
        assertCustomVisibleAndReadOnly(draft)
    }

    @Test fun settingsGroupImportTreeAndBackupAndDisablingTimePreservesTheRunningRecord() {
        ablage.aendereZeiterfassung { it.copy(enabled = true).start(Zeiteintrag(startMinute = Zeiteintrag.currentMinute())) }
        val saved = ablage.bestand.value.zeiterfassung.entries.single()
        launch()
        assertEquals(4, nodes().count { it.config.getOrNull(SemanticsProperties.Role) == Role.Tab })
        tab(R.string.zeit_titel).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        assertEquals(true, tab(R.string.zeit_titel).config.getOrNull(SemanticsProperties.Selected))
        tab(R.string.zeit_einstellungen).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        for (resource in listOf(R.string.blatt_einfuhr, R.string.blatt_baum, R.string.blatt_journal))
            assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.Text)
                ?.any { text -> text.text == app.getString(resource) } == true })
        clickText(R.string.zeit_aktiv)
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
        while (ablage.bestand.value.zeiterfassung.enabled && System.nanoTime() < deadline) {
            frames(); Thread.sleep(5)
        }
        frames()
        assertFalse(ablage.bestand.value.zeiterfassung.enabled)
        assertEquals(saved, ablage.bestand.value.zeiterfassung.entries.single())
        assertEquals(3, nodes().count { it.config.getOrNull(SemanticsProperties.Role) == Role.Tab })
    }

    @Test fun timeSliderAcceptsFinalReleasePositionButRejectsTapsPartialDragsAndCancellation() {
        ablage.aendereZeiterfassung { it.copy(enabled = true) }
        launch()
        tab(R.string.zeit_titel).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        val slider = nodes().first { it.config.getOrNull(SemanticsProperties.ContentDescription) ==
            listOf(app.getString(R.string.zeit_starten)) &&
            it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo) != null }
        val bounds = slider.boundsInRoot
        assertEquals(1, nodes().count { it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo) != null })
        val content = controller!!.get().findViewById<ViewGroup>(android.R.id.content).getChildAt(0)
        fun gesture(fraction: Float, cancel: Boolean = false) {
            val downTime = android.os.SystemClock.uptimeMillis()
            val startX = bounds.left + 12f
            val endX = startX + (bounds.right - 4f - startX) * fraction
            fun send(action: Int, x: Float, time: Long) {
                val event = android.view.MotionEvent.obtain(downTime, time, action, x, bounds.center.y, 0)
                event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
                content.dispatchTouchEvent(event)
                event.recycle()
            }
            send(android.view.MotionEvent.ACTION_DOWN, startX, downTime)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(600))
            // No intermediate MOVE: exercise Android's coalesced final position.
            send(if (cancel) android.view.MotionEvent.ACTION_CANCEL else android.view.MotionEvent.ACTION_UP,
                endX, downTime + 600)
            frames()
        }
        gesture(0f)
        assertTrue(ablage.bestand.value.zeiterfassung.entries.isEmpty())
        gesture(0.5f)
        assertTrue(ablage.bestand.value.zeiterfassung.entries.isEmpty())
        gesture(1f, cancel = true)
        assertTrue(ablage.bestand.value.zeiterfassung.entries.isEmpty())
        gesture(1f)
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
        while (ablage.bestand.value.zeiterfassung.entries.isEmpty() && System.nanoTime() < deadline) {
            frames(); Thread.sleep(5)
        }
        assertEquals(1, ablage.bestand.value.zeiterfassung.entries.size)
        frames()
        fun control(resource: Int) = nodes().first {
            it.config.getOrNull(SemanticsProperties.ContentDescription) == listOf(app.getString(resource)) &&
                it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo) != null
        }
        fun confirm(resource: Int, finished: () -> Boolean) {
            assertTrue(control(resource).config.getOrNull(SemanticsActions.SetProgress)!!.action!!.invoke(1f))
            frames()
            assertTrue(control(resource).config.getOrNull(SemanticsActions.CustomActions)!!.single().action())
            val until = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
            while (!finished() && System.nanoTime() < until) { frames(); Thread.sleep(5) }
            frames()
            assertTrue(finished())
        }
        assertEquals(2, nodes().count { it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo) != null })
        assertEquals(bounds.top, control(R.string.zeit_beenden).boundsInRoot.top, 1f)
        val pauseTop = control(R.string.zeit_pausieren).boundsInRoot.top
        confirm(R.string.zeit_pausieren) { ablage.bestand.value.zeiterfassung.entries.single().pauseMinute != null }
        assertEquals(pauseTop, control(R.string.zeit_fortsetzen).boundsInRoot.top, 1f)
        confirm(R.string.zeit_fortsetzen) { ablage.bestand.value.zeiterfassung.entries.single().pauseMinute == null }
        confirm(R.string.zeit_beenden) { ablage.bestand.value.zeiterfassung.entries.single().endMinute != null }
        assertEquals(1, nodes().count { it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo) != null })
        assertEquals(bounds.top, control(R.string.zeit_starten).boundsInRoot.top, 1f)
    }

    @Test fun timeDraftDefersNotificationNavigationAndIsSavedThroughEncryptedDraftStorage() {
        ablage.aendereZeiterfassung { it.copy(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, type = "Original activity")) }
        val original = ablage.bestand.value.zeiterfassung.entries.single()
        ablage.setzeZeitEntwurf(ZeitEntwurf(original, kind = "Pending time edit"))
        launch(intent())
        assertNotNull(controller!!.get().gewuenschtesCustom.value)
        assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.EditableText)?.text == "Pending time edit" })
        assertEquals("Original activity", ablage.bestand.value.zeiterfassung.entries.single().type)
        ablage.sichereEntwurf()
        assertEquals("Pending time edit", ablage.entwurf.value.zeit?.kind)
        clickText(R.string.sichern)
        awaitEditorClose()
        assertEquals("Pending time edit", ablage.bestand.value.zeiterfassung.entries.single().type)
        assertCustomVisibleAndReadOnly()
    }

    @Test fun recoveryPageRestoresALocallyRemovedTimeMonth() {
        ablage.aendereZeiterfassung { it.copy(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC", type = "Saved activity")) }
        val saved = ablage.bestand.value.zeiterfassung.entries.single()
        ablage.aendereZeiterfassung { it.removeLocal(listOf(saved), month = "1970-01") }
        launch()
        tab(R.string.zeit_einstellungen).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        clickText(R.string.blatt_journal)
        frames()
        assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.Text)
            ?.any { text -> text.text.contains(app.getString(R.string.zeit_erfasste)) } == true })
        clickText(R.string.journal_restore)
        val until = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
        while (ablage.bestand.value.zeiterfassung.entries.isEmpty() && System.nanoTime() < until) {
            frames(); Thread.sleep(5)
        }
        assertEquals(listOf(saved), ablage.bestand.value.zeiterfassung.entries)
        assertTrue(ablage.bestand.value.zeiterfassung.trash.isEmpty())
        assertFalse(ablage.bestand.value.zeiterfassung.suppressIncoming(saved))
    }

    private fun invalidatedWhileEditing(change: (PersonalCustomState) -> PersonalCustomState) {
        val original = ablage.bestand.value.personalCustom
        val draft = Notiz("unsaved", text = "Keep this draft")
        ablage.setzeNotizEntwurf(draft)
        launch(intent())
        ablage.personalCustomChange(change)
        frames()
        assertNull(controller!!.get().gewuenschtesCustom.value)
        assertEquals(draft, ablage.entwurf.value.notiz)
        ablage.personalCustomChange { original }
        controller!!.get().onBackPressedDispatcher.onBackPressed()
        awaitEditorClose()
        assertEquals(true, tab(R.string.blatt_notizen).config.getOrNull(SemanticsProperties.Selected))
        assertNull(controller!!.get().gewuenschtesCustom.value)
        assertEquals(draft.text, ablage.notiz(draft.id)?.text)
    }

    @Test fun removalWhileEditingConsumesRequestAndDoesNotResurrectAfterFinish() =
        invalidatedWhileEditing { it.copy(items = emptyMap()) }

    @Test fun withdrawalWhileEditingConsumesRequestEvenIfConsentReturns() =
        invalidatedWhileEditing { it.copy(remote = CustomFixtures.consent.getValue("revoked").jsonObject) }

    @Test fun muteWhileEditingConsumesRequestEvenIfRemindersReturn() = invalidatedWhileEditing { state ->
        state.copy(items = state.items.mapValues { (_, item) ->
            val value = JsonObject(item.record.getValue("value").jsonObject + ("module_reminders" to JsonPrimitive(false)))
            item.copy(record = JsonObject(item.record + mapOf("value" to value, "hash" to JsonPrimitive(PersonalSync.hash(value)))))
        })
    }
}
