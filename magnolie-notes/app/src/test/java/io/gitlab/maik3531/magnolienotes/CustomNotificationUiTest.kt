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
        assertEquals(true, tab(R.string.blatt_baum).config.getOrNull(SemanticsProperties.Selected))
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
        tab(R.string.blatt_einfuhr).config.getOrNull(SemanticsActions.OnClick)!!.action!!.invoke()
        frames()
        assertEquals(true, tab(R.string.blatt_einfuhr).config.getOrNull(SemanticsProperties.Selected))
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
