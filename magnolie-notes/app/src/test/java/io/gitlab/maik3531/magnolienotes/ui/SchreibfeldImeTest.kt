package io.gitlab.maik3531.magnolienotes.ui

import android.view.View
import android.view.ViewGroup
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import androidx.activity.ComponentActivity
import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.platform.ComposeView
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.material3.OutlinedTextField
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import android.os.Looper
import java.time.Duration
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class SchreibfeldImeTest {
    // Use the same explicit frame/recomposer pattern as the full editor tests.
    // WindowRecomposer's cached dispatcher can otherwise belong to a previous
    // Robolectric looper when this class follows another Compose test class.
    private class NativeEditor : AutoCloseable {
        private val clock = BroadcastFrameClock()
        private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
        private val recomposer = Recomposer(scope.coroutineContext)
        private val controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        private val compose = ComposeView(controller.get()).apply { setParentCompositionContext(recomposer) }
        private val bitmap = Bitmap.createBitmap(480, 800, Bitmap.Config.ARGB_8888)
        private var nanos = 0L
        init { controller.get().setContentView(compose) }
        fun get() = controller.get()
        fun setContent(content: @Composable () -> Unit) {
            compose.setContent(content)
            scope.launch { recomposer.runRecomposeAndApplyChanges() }
            controller.start().resume().visible().windowFocusChanged(true)
            frames()
        }
        fun frames() {
            repeat(12) {
                Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
                nanos += 16_000_000; clock.sendFrame(nanos)
                shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
                get().window.decorView.apply {
                    measure(View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(800, View.MeasureSpec.EXACTLY))
                    layout(0, 0, 480, 800); draw(Canvas(bitmap))
                }
            }
        }
        override fun close() {
            controller.pause().stop().destroy(); recomposer.cancel(); scope.cancel(); bitmap.recycle()
        }
    }

    @Test fun nativeImeEditingAndDraftFlowKeepTheTypedSuffixDeletable() {
        composingImeCanDeleteLastCharacterAndSelectionWithoutReplacingTheDraft()
        checkKeyboardBackspace(true)
        checkKeyboardBackspace(false)
    }

    private fun checkKeyboardBackspace(platformBaseline: Boolean) {
        val original = "Existing note text\n\n"
        val draft = MutableStateFlow(original)
        val requester = FocusRequester()
        val activity = NativeEditor()
        try {
            activity.setContent {
                val text by draft.collectAsState()
                if (platformBaseline) OutlinedTextField(text, { draft.value = it }, modifier = Modifier.focusRequester(requester), singleLine = false)
                else Schreibfeld(text, "Note", { draft.value = it }, modifier = Modifier.focusRequester(requester), einzeilig = false)
                LaunchedEffect(Unit) { requester.requestFocus() }
            }
            activity.frames()
            fun editor(view: View): View? {
                if (view.onCheckIsTextEditor()) return view
                if (view is ViewGroup) for (index in 0 until view.childCount) editor(view.getChildAt(index))?.let { return it }
                return null
            }
            val view = requireNotNull(editor(activity.get().window.decorView))
            val connection = requireNotNull(view.onCreateInputConnection(EditorInfo()))
            assertTrue(connection.setSelection(original.length, original.length))
            assertTrue(connection.setComposingText("aaa", 1))
            activity.frames()
            assertEquals(original + "aaa", draft.value)
            assertTrue(connection.finishComposingText())
            activity.frames()
            assertTrue(connection.setSelection(draft.value.length, draft.value.length))
            activity.frames()
            assertEquals(draft.value, connection.getTextBeforeCursor(draft.value.length + 1, 0).toString())
            repeat(3) { index ->
                // Native InputChannel delivery from BaseInputConnection is not
                // simulated by Robolectric; dispatch at its actual View target.
                assertTrue(view.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DEL)))
                view.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DEL))
                activity.frames()
                assertEquals("Backspace did not remove the typed suffix", original + "a".repeat(2 - index), draft.value)
            }
            // Multiple IME edits can arrive before the StateFlow is collected
            // by the next composition. Returning to the old value is a write.
            assertTrue(connection.beginBatchEdit())
            assertTrue(connection.commitText("aaa", 1))
            repeat(3) { assertTrue(connection.deleteSurroundingText(1, 0)) }
            connection.endBatchEdit()
            activity.frames()
            assertEquals("An IME batch must be able to remove its entire new suffix", original, draft.value)
        } finally { activity.close() }
    }

    private fun composingImeCanDeleteLastCharacterAndSelectionWithoutReplacingTheDraft() {
        var text by mutableStateOf("")
        val requester = FocusRequester()
        val activity = NativeEditor()
        try {
            activity.setContent {
                Schreibfeld(text, "Note", { text = it }, modifier = Modifier.focusRequester(requester), einzeilig = false)
                LaunchedEffect(Unit) { requester.requestFocus() }
            }
            activity.frames()
            fun editor(view: View): View? {
                if (view.onCheckIsTextEditor()) return view
                if (view is ViewGroup) for (index in 0 until view.childCount) editor(view.getChildAt(index))?.let { return it }
                return null
            }
            val view = requireNotNull(editor(activity.get().window.decorView)) { "Focused native Compose editor missing" }
            val connection = requireNotNull(view.onCreateInputConnection(EditorInfo()))
            assertTrue(connection.setComposingText("Notiz", 1))
            activity.frames()
            assertEquals("Notiz", text)
            // Gboard and other composing IMEs can delete before finishing the
            // word. Keep this path distinct from a committed-text deletion.
            assertTrue(connection.deleteSurroundingText(1, 0))
            activity.frames()
            assertEquals("Noti", text)
            assertTrue(connection.finishComposingText())
            assertTrue(connection.setSelection(1, 3))
            assertTrue(connection.commitText("", 1))
            activity.frames()
            assertEquals("Ni", text)
            assertTrue(connection.setSelection(0, text.length))
            assertTrue(connection.commitText("A\uD83D\uDE00", 1))
            activity.frames()
            assertTrue(connection.deleteSurroundingTextInCodePoints(1, 0))
            activity.frames()
            assertEquals("A", text)
        } finally { activity.close() }
    }
}
