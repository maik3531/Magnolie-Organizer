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
import io.gitlab.maik3531.magnolienotes.telefon.*
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

/** Real Compose semantics/confirmation, not physical handset acceptance. */
@OptIn(InternalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [30], qualifiers = "de")
class MedienWiederherstellungUiTest {
    private val clock = BroadcastFrameClock()
    private val scope = CoroutineScope(Dispatchers.Main + clock + Job())
    private val recomposer = Recomposer(scope.coroutineContext)
    private var controller: ActivityController<ComponentActivity>? = null
    private lateinit var view: ComposeView
    private var frame = 0L
    private val rows = mutableStateOf<List<NativeGalleryRecoveryRow>>(emptyList())
    private val busy = mutableStateOf(false)
    private val failed = mutableStateOf(false)
    private val restored = mutableListOf<NativeGalleryRecoveryRow>()
    private val previewed = mutableListOf<NativeGalleryRecoveryRow>()
    private val thumbnails = mutableStateMapOf<String, android.graphics.Bitmap?>()
    private val thumbnailsEnabled = mutableStateOf(false)
    private var refreshed = 0

    private fun row(state: String?, name: String = "Synthetic photo.jpg"): NativeGalleryRecoveryRow {
        val entry = NativeGalleryArchiveEntry("10000000-0000-0000-0000-000000000001", "a".repeat(64), 5, "b".repeat(64), name, 1000, true)
        return NativeGalleryRecoveryRow(entry, state?.let {
            NativeGalleryTrashAction("20000000-0000-0000-0000-000000000002", entry.id, entry.version,
                if (it == "trashed") 2 else 4, it, 2000, "c".repeat(64))
        })
    }
    private fun launch() {
        controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        view = ComposeView(controller!!.get()); view.setParentCompositionContext(recomposer)
        controller!!.get().setContentView(view)
        scope.launch { recomposer.runRecomposeAndApplyChanges() }
        view.setContent { MagnolieThema {
            MedienVorschauOption(thumbnailsEnabled.value) { thumbnailsEnabled.value = it }
            MedienWiederherstellungListe(rows.value, busy.value, failed.value, { refreshed++ },
                thumbnails = if (thumbnailsEnabled.value) thumbnails else emptyMap(), showPreview = { previewed += it }, restore = { restored += it })
        } }
        controller!!.start().resume().visible().windowFocusChanged(true); frames()
    }
    private fun frames() {
        repeat(12) {
            Snapshot.sendApplyNotifications(); shadowOf(Looper.getMainLooper()).idle()
            frame += 16_000_000; clock.sendFrame(frame)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(16))
            view.measure(View.MeasureSpec.makeMeasureSpec(600, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(1600, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 600, 1600)
        }
    }
    private fun nodes(root: View = view): List<SemanticsNode> {
        fun collect(node: SemanticsNode): List<SemanticsNode> = listOf(node) + node.children.flatMap(::collect)
        if (root is ViewRootForTest) return collect(root.semanticsOwner.rootSemanticsNode)
        return if (root is ViewGroup) (0 until root.childCount).flatMap { nodes(root.getChildAt(it)) } else emptyList()
    }
    private fun text(node: SemanticsNode) = node.config.getOrNull(SemanticsProperties.Text)?.joinToString { it.text }.orEmpty()
    private fun buttons(label: Int, root: View = view) = nodes(root).filter {
        text(it) == controller!!.get().getString(label) && it.config.getOrNull(SemanticsActions.OnClick) != null
    }
    private fun click(label: Int, root: View = view) { assertTrue(buttons(label, root).single().config[SemanticsActions.OnClick].action!!.invoke()); frames() }

    @Test fun listShowsTruthfulStatesAndOnlyConfirmedTrashOrProtectedHeldRowCanRestore() {
        rows.value = listOf(row("trashed"), row("restore_row_prepared", "Held.mp4"), row("prepared", "Uncertain.jpg"), row("restored", "Done.jpg"), row(null, "Only copy.jpg"))
        launch()
        assertEquals(1, buttons(R.string.journal_restore).size); assertEquals(1, buttons(R.string.media_recovery_continue).size)
        for (label in listOf(R.string.media_recovery_trashed, R.string.media_recovery_unfinished, R.string.media_recovery_uncertain,
            R.string.media_recovery_restored, R.string.media_recovery_copy_only)) {
            assertTrue(nodes().any { text(it) == controller!!.get().getString(label) })
        }
        assertTrue(restored.isEmpty()); assertEquals(0, refreshed)
    }

    @Test fun nativeConfirmationIsRequiredAndKeepsTheExactVersionedSelection() {
        val selected = row("trashed"); rows.value = listOf(selected); launch()
        click(R.string.media_recovery_refresh); assertEquals(1, refreshed)
        click(R.string.journal_restore); assertTrue(restored.isEmpty())
        var dialog = ShadowDialog.getLatestDialog(); assertTrue(dialog.isShowing)
        click(R.string.abbrechen, dialog.window!!.decorView); assertTrue(restored.isEmpty())
        click(R.string.journal_restore); dialog = ShadowDialog.getLatestDialog()
        click(R.string.journal_restore, dialog.window!!.decorView)
        assertSame(selected, restored.single())
    }

    @Test fun actualThumbnailAndPreviewSelectionNeverRestoreOrRefreshTheArchive() {
        val selected = row("trashed"); rows.value = listOf(selected)
        val image = android.graphics.Bitmap.createBitmap(12, 6, android.graphics.Bitmap.Config.ARGB_8888)
        thumbnails[selected.entry.version] = image
        launch()
        assertFalse(thumbnailsEnabled.value)
        assertFalse(nodes().any { it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(selected.entry.displayName) == true })
        val option = nodes().single { it.config.getOrNull(SemanticsProperties.Role) == Role.Checkbox }
        assertTrue(option.config[SemanticsActions.OnClick].action!!.invoke()); frames()
        assertTrue(nodes().any { it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(selected.entry.displayName) == true })
        click(R.string.journal_vorschau)
        assertSame(selected, previewed.single()); assertTrue(restored.isEmpty()); assertEquals(0, refreshed)
        assertTrue(nodes().single { it.config.getOrNull(SemanticsProperties.Role) == Role.Checkbox }.config[SemanticsActions.OnClick].action!!.invoke()); frames()
        assertFalse(nodes().any { it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(selected.entry.displayName) == true })
        busy.value = true; frames()
        assertNotNull(buttons(R.string.journal_vorschau).single().config.getOrNull(SemanticsProperties.Disabled))
    }

    @Test fun changedSelectionDismissesConfirmationAndBusyStateDisablesActions() {
        rows.value = listOf(row("restore_row_prepared")); launch()
        click(R.string.media_recovery_continue); assertTrue(ShadowDialog.getLatestDialog().isShowing)
        rows.value = listOf(row("restored")); frames()
        assertFalse(ShadowDialog.getLatestDialog().isShowing); assertTrue(restored.isEmpty())
        rows.value = listOf(row("trashed")); busy.value = true; failed.value = true; frames()
        for (label in listOf(R.string.journal_restore, R.string.media_recovery_refresh))
            assertNotNull(buttons(label).single().config.getOrNull(SemanticsProperties.Disabled))
        assertTrue(nodes().any { text(it) == controller!!.get().getString(R.string.media_recovery_unavailable) })
    }

    @After fun close() { controller?.pause()?.stop()?.destroy(); recomposer.cancel(); scope.cancel() }
}
