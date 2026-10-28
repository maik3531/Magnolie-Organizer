package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
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

/** Actual Compose pointer dispatch and recomposition, not a device screenshot test. */
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28])
class WischVerbindungUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var frame = 0L
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private val available = mutableStateOf(false)
    private val actions = mutableListOf<WischAktion>()
    private val settings = WischAnzeige()

    private fun launch(rtl: Boolean = false) {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get())
        view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent {
            CompositionLocalProvider(LocalLayoutDirection provides if (rtl) LayoutDirection.Rtl else LayoutDirection.Ltr) {
                MagnolieThema {
                    EintragsWischen(settings, { actions += it }, abgleichMoeglich = { available.value }) {
                        Box(Modifier.fillMaxWidth().height(100.dp)) { Text("Owned row") }
                    }
                }
            }
        }
        controller!!.start().resume().visible().windowFocusChanged(true)
        frames()
    }

    private fun frames(count: Int = 30) {
        val bitmap = android.graphics.Bitmap.createBitmap(480, 800, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(bitmap)
        repeat(count) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(800, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 480, 800); view.draw(canvas)
        }
        bitmap.recycle()
    }

    private fun swipe(left: Boolean, during: (() -> Unit)? = null) {
        val down = SystemClock.uptimeMillis()
        fun event(kind: Int, x: Float) {
            MotionEvent.obtain(down, SystemClock.uptimeMillis(), kind, x, 30f, 0).also {
                view.dispatchTouchEvent(it); it.recycle()
            }
            frames(1)
        }
        val start = if (left) 440f else 40f
        val delta = if (left) -400f else 400f
        event(MotionEvent.ACTION_DOWN, start)
        for (step in 1..24) {
            event(MotionEvent.ACTION_MOVE, start + delta * step / 24)
            if (step == 8) { during?.invoke(); frames(2) }
        }
        event(MotionEvent.ACTION_UP, start + delta)
        frames()
    }

    @After fun close() {
        controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel()
    }

    @Test fun offlineSyncIsInertButDeleteRemainsAndTheSavedChoiceReturnsOnReconnect() {
        launch()
        swipe(true); assertTrue(actions.isEmpty())
        swipe(false); assertEquals(listOf(WischAktion.LOESCHEN), actions)
        available.value = true; frames()
        swipe(true); assertEquals(listOf(WischAktion.LOESCHEN, WischAktion.ABGLEICHEN), actions)
        assertEquals(WischAktion.ABGLEICHEN, settings.links)
    }

    @Test fun disconnectDuringAnAlreadyStartedGestureCannotDispatchSync() {
        available.value = true; launch()
        swipe(true) { available.value = false }
        assertTrue(actions.isEmpty())
        available.value = true; frames(); swipe(true)
        assertEquals(listOf(WischAktion.ABGLEICHEN), actions)
    }

    @Test fun physicalLeftAndRightRetainTheirActionsInRtl() {
        launch(true)
        swipe(true); assertTrue(actions.isEmpty())
        available.value = true; frames(); swipe(true)
        assertEquals(listOf(WischAktion.ABGLEICHEN), actions)
        available.value = false; frames(); swipe(false)
        assertEquals(listOf(WischAktion.ABGLEICHEN, WischAktion.LOESCHEN), actions)
    }
}
