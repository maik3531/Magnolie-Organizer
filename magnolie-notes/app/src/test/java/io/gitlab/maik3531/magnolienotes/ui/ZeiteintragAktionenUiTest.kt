package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.os.Looper
import android.view.View
import androidx.activity.ComponentActivity
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.InternalComposeUiApi
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Density
import io.gitlab.maik3531.magnolienotes.R
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

/** Actual Compose layout/semantics in Robolectric, not handset visual acceptance. */
@OptIn(InternalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28], qualifiers = "de")
class ZeiteintragAktionenUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private val neu = mutableStateOf(false)
    private val speichert = mutableStateOf(false)
    private val schrift = mutableStateOf(1f)
    private var frame = 0L
    private val calls = mutableListOf<String>()

    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent {
            CompositionLocalProvider(LocalDensity provides Density(1f, schrift.value)) {
                MagnolieThema {
                    ZeiteintragAktionen(neu.value, speichert.value, { calls += "save" }, { calls += "cancel" }, { calls += "request-delete" })
                }
            }
        }
        controller!!.start().resume().visible().windowFocusChanged(true)
    }

    private fun frames(width: Int = 480) {
        val bitmap = android.graphics.Bitmap.createBitmap(width, 220, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(bitmap)
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(220, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, width, 220); view.draw(canvas)
        }
        bitmap.recycle()
    }

    private fun buttons(): List<SemanticsNode> {
        val root = (view.getChildAt(0) as ViewRootForTest).semanticsOwner.rootSemanticsNode
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        return collect(root).filter { it.config.getOrNull(SemanticsActions.OnClick) != null && it.config.getOrNull(SemanticsProperties.Text) != null }
    }
    private fun button(label: Int) = buttons().single { node -> node.config[SemanticsProperties.Text].any { it.text == controller!!.get().getString(label) } }

    @Test fun editAndManualModesKeepTheirButtonsBesideEachOtherAndUseTheOriginalCallbacks() {
        launch(); frames()
        val save = button(R.string.sichern); val cancel = button(R.string.abbrechen); val delete = button(R.string.loeschen)
        assertTrue(save.positionInRoot.x < cancel.positionInRoot.x && cancel.positionInRoot.x < delete.positionInRoot.x)
        val centers = listOf(save, cancel, delete).map { it.positionInRoot.y + it.size.height / 2f }
        assertTrue(centers.max() - centers.min() <= 1f)
        for (node in listOf(save, cancel, delete)) assertTrue(node.config[SemanticsActions.OnClick].action!!.invoke())
        assertEquals(listOf("save", "cancel", "request-delete"), calls)
        neu.value = true; frames()
        assertEquals(2, buttons().size)
        assertTrue(buttons().none { node -> node.config[SemanticsProperties.Text].any { it.text == controller!!.get().getString(R.string.loeschen) } })
        speichert.value = true; frames()
        buttons().forEach { assertNotNull(it.config.getOrNull(SemanticsProperties.Disabled)) }
    }

    @Test fun smallWidthAndLargeFontScrollHorizontallyInsteadOfStackingOrShrinkingActions() {
        launch()
        for (width in listOf(280, 480)) for (font in listOf(1f, 2f)) {
            schrift.value = font; frames(width)
            val nodes = listOf(button(R.string.sichern), button(R.string.abbrechen), button(R.string.loeschen))
            val centers = nodes.map { it.positionInRoot.y + it.size.height / 2f }
            assertTrue("$width/$font", centers.max() - centers.min() <= 1f)
            assertTrue(nodes[0].positionInRoot.x < nodes[1].positionInRoot.x && nodes[1].positionInRoot.x < nodes[2].positionInRoot.x)
            nodes.forEach { assertTrue(it.size.height >= 40) }
        }
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
