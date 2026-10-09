package io.gitlab.maik3531.magnolienotes.ui

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Insets
import android.os.Looper
import android.view.View
import android.view.WindowInsets as AndroidInsets
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SystemNavigationLayoutTest {
    @Test fun brownNavigationAreaSurvivesEditorChangesInsetsKeyboardAndHiddenBars() {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup().visible()
        val activity = controller.get()
        activity.enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Magnolie.lederDunkel.toArgb()),
            navigationBarStyle = SystemBarStyle.dark(Magnolie.lederDunkel.toArgb())
        )
        val editor = mutableStateOf(true)
        var contentBounds: Rect? = null
        activity.setContent {
            MagnolieThema {
                Box(Modifier.fillMaxSize()
                    .background(if (editor.value) Magnolie.papier else Magnolie.leder)
                    .navigationBarsPadding().imePadding()
                    .onGloballyPositioned { contentBounds = it.boundsInRoot() })
            }
        }
        val decor = activity.window.decorView
        fun frame(left: Int = 0, right: Int = 0, bottom: Int = 0, ime: Int = 0) {
            val insets = AndroidInsets.Builder()
                .setInsets(AndroidInsets.Type.navigationBars(), Insets.of(left, 0, right, bottom))
                .setVisible(AndroidInsets.Type.navigationBars(), left + right + bottom > 0)
                .setInsets(AndroidInsets.Type.ime(), Insets.of(0, 0, 0, ime))
                .setVisible(AndroidInsets.Type.ime(), ime > 0).build()
            decor.dispatchApplyWindowInsets(insets)
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(1, TimeUnit.SECONDS)
            decor.measure(View.MeasureSpec.makeMeasureSpec(320, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.EXACTLY))
            decor.layout(0, 0, 320, 480)
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(1, TimeUnit.SECONDS)
        }
        fun pixel(x: Int, y: Int): Int {
            val bitmap = Bitmap.createBitmap(320, 480, Bitmap.Config.ARGB_8888)
            return try { decor.draw(Canvas(bitmap)); bitmap.getPixel(x, y) } finally { bitmap.recycle() }
        }
        try {
            // Compose installs its platform Insets listener after the first composition.
            // Initializing the attached view first makes the following dispatch real.
            frame()
            frame(bottom = 48)
            assertNotNull("Compose must produce a real measured layout", contentBounds)
            assertEquals(432f, contentBounds!!.bottom, 0.1f)
            assertEquals(Magnolie.lederDunkel.toArgb(), pixel(160, 460))
            assertEquals(Magnolie.papier.toArgb(), pixel(160, 400))
            editor.value = false
            frame(bottom = 24)
            assertEquals(456f, contentBounds!!.bottom, 0.1f)
            assertEquals(Magnolie.lederDunkel.toArgb(), pixel(160, 470))
            editor.value = true
            frame(right = 40)
            assertEquals(280f, contentBounds!!.right, 0.1f)
            assertEquals(Magnolie.lederDunkel.toArgb(), pixel(300, 240))
            frame(left = 36)
            assertEquals(36f, contentBounds!!.left, 0.1f)
            assertEquals(Magnolie.lederDunkel.toArgb(), pixel(10, 240))
            frame(bottom = 24, ime = 200)
            assertEquals("IME and navigation insets are consumed once", 280f, contentBounds!!.bottom, 0.1f)
            frame()
            assertEquals(480f, contentBounds!!.bottom, 0.1f)
            assertEquals(Magnolie.papier.toArgb(), pixel(160, 470))
        } finally { controller.pause().stop().destroy() }
    }
}
