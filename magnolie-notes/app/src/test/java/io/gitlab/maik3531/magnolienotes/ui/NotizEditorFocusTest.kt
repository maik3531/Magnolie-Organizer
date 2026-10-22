package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.R
import java.time.Duration
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/** Real editor hierarchy: body is focused before its viewport becomes compact. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class NotizEditorFocusTest {
    @Test fun firstBodyFocusSurvivesKeyboardResizeBackspaceAndTitleFocus() {
        val clock = BroadcastFrameClock()
        val scope = CoroutineScope(Dispatchers.Main + clock + Job())
        val recomposer = Recomposer(scope.coroutineContext)
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        val compose = ComposeView(controller.get()).apply { setParentCompositionContext(recomposer) }
        controller.get().setContentView(compose)
        val original = "Existing note text\n\n"
        val draft = MutableStateFlow(Notiz("focus-fixture", titel = "Synthetic title", text = original))
        var viewport by mutableStateOf(900.dp)
        var nanos = 0L
        val image = Bitmap.createBitmap(480, 1000, Bitmap.Config.ARGB_8888)
        fun frames() {
            repeat(20) {
                Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
                nanos += 16_000_000; clock.sendFrame(nanos)
                shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
                controller.get().window.decorView.apply {
                    measure(View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(1000, View.MeasureSpec.EXACTLY))
                    layout(0, 0, 480, 1000); draw(Canvas(image))
                }
            }
        }
        fun nodes(): List<SemanticsNode> {
            fun owner(view: View): SemanticsOwner? {
                view.javaClass.methods.firstOrNull { it.name == "getSemanticsOwner" && it.parameterCount == 0 }?.let { return it.invoke(view) as SemanticsOwner }
                if (view is ViewGroup) for (index in 0 until view.childCount) owner(view.getChildAt(index))?.let { return it }
                return null
            }
            fun walk(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::walk)
            return walk(requireNotNull(owner(compose)).unmergedRootSemanticsNode)
        }
        fun clickField(text: String) {
            val node = nodes().first { it.config.getOrNull(SemanticsProperties.EditableText)?.text == text && it.config.getOrNull(SemanticsActions.OnClick) != null }
            assertTrue(node.config[SemanticsActions.OnClick].action!!.invoke())
            frames()
        }
        fun regularLayout() {
            val body = nodes().first { it.config.getOrNull(SemanticsProperties.EditableText)?.text == original }
            assertTrue("Regular note body lost its remaining viewport height", body.boundsInRoot.height > 240f)
            val save = controller.get().getString(R.string.sichern)
            val footer = nodes().first { it.config.getOrNull(SemanticsProperties.Text)?.any { value -> value.text == save } == true }
            assertTrue("Regular editor footer is clipped", footer.boundsInRoot.height > 0f && footer.boundsInRoot.bottom <= 900f)
        }
        fun inputView(view: View): View? {
            if (view.onCheckIsTextEditor()) return view
            if (view is ViewGroup) for (index in 0 until view.childCount) inputView(view.getChildAt(index))?.let { return it }
            return null
        }
        try {
            compose.setContent {
                val note by draft.collectAsState()
                MagnolieThema {
                    Box(Modifier.width(480.dp).height(viewport)) {
                        NotizEditor(note, emptyList(), beiSichern = {}, beiEntwurf = { draft.value = it }, speichert = false,
                            beiLoeschen = {}, beiTeilen = {}, beiAnhangOeffnen = {}, beiAnhangSpeichern = {}, beiAnhangHinzufuegen = {},
                            anhangEreignis = null, beiAnhangEreignisVerbraucht = {}, beiAnhaengeAenderung = {})
                    }
                }
            }
            scope.launch { recomposer.runRecomposeAndApplyChanges() }
            controller.start().resume().visible().windowFocusChanged(true); frames()
            regularLayout()
            clickField(original)
            viewport = 480.dp; frames()
            val view = requireNotNull(inputView(compose))
            val connection = requireNotNull(view.onCreateInputConnection(EditorInfo()))
            assertTrue(connection.setSelection(original.length, original.length))
            assertTrue(connection.setComposingText("aaa", 1)); frames()
            assertEquals(original + "aaa", draft.value.text)
            repeat(3) {
                view.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DEL))
                view.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DEL)); frames()
            }
            val afterDelete = draft.value.text
            clickField(draft.value.titel)
            assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.EditableText)?.text == draft.value.titel && it.config.getOrNull(SemanticsProperties.Focused) == true })
            assertEquals("Viewport reflow must retain a valid body focus for Backspace", original, afterDelete)
            viewport = 900.dp; frames()
            regularLayout()
            clickField(original)
            assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.EditableText)?.text == original && it.config.getOrNull(SemanticsProperties.Focused) == true })
        } finally {
            controller.pause().stop().destroy(); recomposer.cancel(); scope.cancel(); image.recycle()
        }
    }
}
