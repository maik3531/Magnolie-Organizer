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
import androidx.compose.ui.text.AnnotatedString
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
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
class ZeitArtOptionenUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private val state = mutableStateOf(ZeiterfassungStand())
    private val busy = mutableStateOf(false)
    private var frame = 0L
    private var saves = 0

    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent { MagnolieThema { ZeitArtOptionen(state.value, busy.value) { change, done ->
            state.value = change(state.value); saves++; done()
        } } }
        controller!!.start().resume().visible().windowFocusChanged(true)
        frames()
    }

    private fun frames() {
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(1600, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 480, 1600)
        }
    }
    private fun nodes(): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        return collect((view.getChildAt(0) as ViewRootForTest).semanticsOwner.rootSemanticsNode)
    }
    private fun button(label: Int) = nodes().single { node ->
        node.config.getOrNull(SemanticsActions.OnClick) != null &&
            node.config.getOrNull(SemanticsProperties.Text)?.any { it.text == controller!!.get().getString(label) } == true
    }
    private fun click(label: Int) { assertTrue(button(label).config[SemanticsActions.OnClick].action!!.invoke()); frames() }
    private fun edit(text: String) {
        val field = nodes().single { it.config.getOrNull(SemanticsActions.SetText) != null }
        assertTrue(field.config[SemanticsActions.SetText].action!!.invoke(AnnotatedString(text))); frames()
    }

    @Test fun customExamplesFreeTextEmptyAndAutomaticModeAreSavedOnlyOnExplicitSave() {
        launch()
        assertNotNull(button(R.string.sichern).config.getOrNull(SemanticsProperties.Disabled))
        click(R.string.zeit_art_eigene); click(R.string.zeit_art_training)
        assertNull(state.value.defaultType); assertEquals(0, saves)
        click(R.string.sichern); assertEquals("Trainingseinheit", state.value.defaultType)
        click(R.string.zeit_art_meeting); click(R.string.sichern); assertEquals("Meeting", state.value.defaultType)
        edit("Yoga am Abend"); click(R.string.sichern); assertEquals("Yoga am Abend", state.value.defaultType)
        edit(""); click(R.string.sichern); assertEquals("", state.value.defaultType)
        click(R.string.zeit_art_dienste); click(R.string.sichern); assertNull(state.value.defaultType)
        assertEquals(5, saves)
    }

    @Test fun tooLongNamesAndBusyStateCannotEnableSavingAndUnrelatedUpdatesKeepTheDraft() {
        launch(); click(R.string.zeit_art_eigene); edit("x".repeat(121))
        assertNotNull(button(R.string.sichern).config.getOrNull(SemanticsProperties.Disabled))
        edit("Trainingseinheit")
        state.value = state.value.copy(reportName = "Concurrent report"); frames()
        busy.value = true; frames()
        assertNotNull(button(R.string.sichern).config.getOrNull(SemanticsProperties.Disabled))
        busy.value = false; frames(); click(R.string.sichern)
        assertEquals("Trainingseinheit", state.value.defaultType)
        assertEquals("Concurrent report", state.value.reportName)
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
