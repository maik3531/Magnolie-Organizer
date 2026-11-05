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
import androidx.compose.ui.state.ToggleableState
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.telefon.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
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
@Config(application = Application::class, sdk = [30], qualifiers = "de")
class MedienSyncEinstellungenUiTest {
    private val values = JsonObject(MediaSyncSettings.effective(MediaSyncSettings.create("11111111-1111-4111-8111-111111111111")))
    private val versions = values.keys.mapIndexed { index, field -> field to (index + 1).toString().repeat(64) }.toMap()
    private val state = mutableStateOf(TelefonUiZustand(mediaPreferencesSupported = true, mediaPreferencesValues = values,
        mediaPreferencesVersions = versions))
    private val changes = mutableListOf<Triple<String, JsonElement, String>>()
    private var permissions = 0
    private var runs = 0
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private var frame = 0L

    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent { MagnolieThema { MedienSyncEinstellungen(state.value, { field, value, version ->
            changes += Triple(field, value, version)
        }, { permissions++ }, { runs++ }) } }
        controller!!.start().resume().visible().windowFocusChanged(true); frames()
    }
    private fun frames() {
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame); shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(800, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(2400, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 800, 2400)
        }
    }
    private fun nodes(root: View = view): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        if (root is ViewRootForTest) return collect(root.semanticsOwner.rootSemanticsNode)
        return if (root is ViewGroup) (0 until root.childCount).flatMap { nodes(root.getChildAt(it)) } else emptyList()
    }
    private fun text(node: SemanticsNode): String = node.config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text }.orEmpty()
    private fun label(id: Int) = controller!!.get().getString(id)
    private fun click(node: SemanticsNode) { assertTrue(node.config[SemanticsActions.OnClick].action!!.invoke()); frames() }
    private fun checkbox(id: Int) = nodes().single { text(it) == label(id) && it.config.getOrNull(SemanticsProperties.ToggleableState) != null }
    private fun open() = click(nodes().single { text(it) == "▸ " + label(R.string.medien_sync_titel) })

    @Test fun masterStartsOffAndOnlyForwardsItsOwnVersionWithoutPermissionOrRun() {
        launch()
        assertFalse(nodes().any { text(it) == label(R.string.medien_sync_aktivieren) })
        open()
        val master = checkbox(R.string.medien_sync_aktivieren)
        assertEquals(ToggleableState.Off, master.config[SemanticsProperties.ToggleableState])
        assertEquals(ToggleableState.Off, checkbox(R.string.personal_sync_skip_deletions).config[SemanticsProperties.ToggleableState])
        assertNotNull(checkbox(R.string.medien_sync_fotos).config.getOrNull(SemanticsProperties.Disabled))
        assertTrue(changes.isEmpty()); assertEquals(0, permissions); assertEquals(0, runs)
        click(master)
        assertEquals(Triple("enabled", JsonPrimitive(true), versions.getValue("enabled")), changes.single())
        assertEquals(0, permissions)
        assertEquals(ToggleableState.Off, checkbox(R.string.medien_sync_aktivieren).config[SemanticsProperties.ToggleableState])
        state.value = state.value.copy(mediaPreferencesValues = JsonObject(values + ("enabled" to JsonPrimitive(true)))); frames()
        click(checkbox(R.string.personal_sync_skip_deletions))
        assertEquals(Triple("skip_deletions", JsonPrimitive(true), versions.getValue("skip_deletions")), changes.last())
        val permissionButton = nodes().single { text(it) == "Android · " + label(R.string.medien_sync_zugriff) }
        click(permissionButton); assertEquals(1, permissions)
        assertEquals(0, runs)
        val syncLabel = label(R.string.personal_sync_jetzt)
        assertNotNull(nodes().single { text(it) == syncLabel }.config.getOrNull(SemanticsProperties.Disabled))
        state.value = state.value.copy(mediaPreferencesReady = true); frames()
        click(nodes().single { text(it) == syncLabel }); assertEquals(1, runs)
        state.value = state.value.copy(mediaManualBusy = true); frames()
        assertNotNull(nodes().single { text(it) == syncLabel }.config.getOrNull(SemanticsProperties.Disabled))
    }

    @Test fun unsupportedOrMissingNativeValuesNeverExposeMediaControls() {
        state.value = state.value.copy(mediaPreferencesSupported = false); launch()
        assertFalse(nodes().any { text(it).contains(label(R.string.medien_sync_titel)) })
        state.value = state.value.copy(mediaPreferencesSupported = true, mediaPreferencesValues = null); frames()
        assertFalse(nodes().any { text(it).contains(label(R.string.medien_sync_titel)) })
        assertTrue(changes.isEmpty()); assertEquals(0, permissions)
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
