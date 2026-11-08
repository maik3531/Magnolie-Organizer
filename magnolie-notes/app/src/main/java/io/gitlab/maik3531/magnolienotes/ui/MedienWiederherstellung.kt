package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.Image
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Checkbox
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.telefon.*

/** Local recovery survives unpairing. Hidden when there is no existing archive;
 * displaying this panel never starts TelefonWerk or requests media permission. */
@Composable
internal fun MedienWiederherstellung(ablage: Ablage) {
    val context = LocalContext.current
    val owner = remember(context) { NativeGalleryLocalRecovery(context) }
    var rows by remember { mutableStateOf<List<NativeGalleryRecoveryRow>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    var session by remember { mutableStateOf<NativeGalleryRestoreSession?>(null) }
    val thumbnails = remember(owner) { mutableStateMapOf<String, Bitmap?>() }
    var preview by remember { mutableStateOf<Pair<NativeGalleryRecoveryRow, Bitmap>?>(null) }
    var previewRestore by remember { mutableStateOf<NativeGalleryRecoveryRow?>(null) }
    var showThumbnails by remember { mutableStateOf(false) }
    var expanded by remember { mutableStateOf(false) }
    DisposableEffect(owner) { onDispose {
        session?.close(); owner.close(); thumbnails.values.forEach { it?.recycle() }; thumbnails.clear()
        preview?.second?.recycle(); preview = null
    } }
    if (!owner.present) return

    fun permit() = NativeGalleryTrashBookPermit.capture(ablage) {
        Ablage.hole(context) === ablage && ablage.synchronisationsSchreibbar()
    }
    fun refresh() {
        if (busy) return
        busy = true; failed = false
        try {
            owner.refresh(permit()) { result ->
                busy = false; failed = result.isFailure
                rows = result.getOrDefault(emptyList())
            }
        } catch (_: Exception) { busy = false; failed = true; rows = emptyList() }
    }
    fun restore(row: NativeGalleryRecoveryRow) {
        failed = false
        try {
            val activity = recoveryActivity(context) ?: throw IllegalStateException("Native Activity required")
            val native = NativeGalleryRestoreSession.capture(activity, checkNotNull(row.action), permit())
            session = native; busy = true
            owner.restore(native) { result ->
                native.close(); session = null; busy = false; failed = result.isFailure
                if (result.isSuccess && expanded) refresh()
            }
        } catch (_: Exception) { session?.close(); session = null; busy = false; failed = true }
    }
    fun showPreview(row: NativeGalleryRecoveryRow) {
        if (busy) return
        busy = true
        try {
            owner.preview(row, permit(), 1024) { result ->
                busy = false
                result.onSuccess { bitmap ->
                    if (expanded && row in rows) { preview?.second?.recycle(); preview = row to bitmap }
                    else bitmap.recycle()
                }.onFailure { failed = true }
            }
        } catch (_: Exception) { busy = false; failed = true }
    }
    LaunchedEffect(rows, busy, preview, previewRestore, showThumbnails) {
        if (showThumbnails && !busy && preview == null && previewRestore == null) {
            val row = rows.take(NativeGalleryTrashArchive.MAX_ENTRIES).firstOrNull { it.entry.version !in thumbnails }
            if (row != null) {
                thumbnails[row.entry.version] = null; busy = true
                try {
                    owner.preview(row, permit(), 192) { result ->
                        busy = false
                        result.onSuccess { bitmap ->
                            if (showThumbnails && row in rows) thumbnails[row.entry.version] = bitmap else bitmap.recycle()
                        }
                    }
                } catch (_: Exception) { busy = false }
            }
        }
        val versions = rows.map { it.entry.version }.toSet()
        thumbnails.keys.filter { it !in versions }.forEach { thumbnails.remove(it)?.recycle() }
        if (preview?.first?.let { it !in rows } == true) { preview?.second?.recycle(); preview = null }
    }
    MedienWiederherstellungListe(rows, busy, failed, ::refresh, thumbnails, ::showPreview,
        options = { MedienVorschauOption(showThumbnails) { enabled ->
             showThumbnails = enabled
             if (!enabled) { thumbnails.values.forEach { it?.recycle() }; thumbnails.clear() }
        } }, onExpandedChanged = { open ->
            expanded = open
            if (open) refresh()
            else {
                session?.close(); session = null
                showThumbnails = false; thumbnails.values.forEach { it?.recycle() }; thumbnails.clear()
                preview?.second?.recycle(); preview = null; previewRestore = null
            }
        }, restore = ::restore)
    preview?.let { (row, bitmap) ->
        fun closePreview() { preview = null; bitmap.recycle() }
        AlertDialog(onDismissRequest = { closePreview() }, title = { Text(row.entry.displayName) },
            text = { Image(bitmap.asImageBitmap(), row.entry.displayName, Modifier.fillMaxWidth()) },
            confirmButton = {
                if (row.canRestore) TextButton(enabled = !busy, onClick = { closePreview(); previewRestore = row }) {
                    Text(stringResource(R.string.journal_restore))
                }
            }, dismissButton = { TextButton(onClick = { closePreview() }) { Text(stringResource(R.string.abbrechen)) } })
    }
    previewRestore?.let { row ->
        AlertDialog(onDismissRequest = { previewRestore = null }, title = { Text(stringResource(R.string.journal_restore)) },
            text = { Text(stringResource(R.string.media_recovery_confirm, row.entry.displayName)) },
            confirmButton = { TextButton(enabled = !busy && row in rows, onClick = {
                previewRestore = null; if (row in rows) restore(row)
            }) { Text(stringResource(R.string.journal_restore)) } },
            dismissButton = { TextButton(onClick = { previewRestore = null }) { Text(stringResource(R.string.abbrechen)) } })
    }
}

@Composable
internal fun MedienVorschauOption(enabled: Boolean, changed: (Boolean) -> Unit) {
    Row {
        Checkbox(checked = enabled, onCheckedChange = changed)
        Text(stringResource(R.string.journal_vorschau))
    }
}

@Composable
internal fun MedienWiederherstellungListe(rows: List<NativeGalleryRecoveryRow>, busy: Boolean, failed: Boolean,
    refresh: () -> Unit, thumbnails: Map<String, Bitmap?> = emptyMap(),
    showPreview: ((NativeGalleryRecoveryRow) -> Unit)? = null, options: @Composable () -> Unit = {},
    onExpandedChanged: (Boolean) -> Unit = {}, restore: (NativeGalleryRecoveryRow) -> Unit) {
    var selected by remember { mutableStateOf<NativeGalleryRecoveryRow?>(null) }
    var expanded by remember { mutableStateOf(false) }
    LaunchedEffect(rows) { if (selected != null && selected !in rows) selected = null }
    val title = stringResource(R.string.media_recovery_title)
    Abschnitt(title, hinweis = if (expanded) stringResource(R.string.media_recovery_hint) else "", kopfAktion = {
        Papierknopf(if (expanded) "▾" else "▸", Modifier.semantics { contentDescription = title }) {
            expanded = !expanded
            if (!expanded) selected = null
            onExpandedChanged(expanded)
        }
    }) {
        if (!expanded) return@Abschnitt
        options()
        if (busy) Text(stringResource(R.string.media_recovery_working))
        if (failed) Text(stringResource(R.string.media_recovery_unavailable))
        Papierknopf(stringResource(R.string.media_recovery_refresh), Modifier.fillMaxWidth(), aktiv = !busy) { refresh() }
        rows.forEach { row ->
            Column {
                thumbnails[row.entry.version]?.let { bitmap ->
                    Image(bitmap.asImageBitmap(), row.entry.displayName, Modifier.size(96.dp))
                }
                Text(row.entry.displayName)
                if (showPreview != null) Papierknopf(stringResource(R.string.journal_vorschau), aktiv = !busy) { showPreview(row) }
                Text(stringResource(when (row.action?.state) {
                    "trashed" -> R.string.media_recovery_trashed
                    "restore_row_prepared" -> R.string.media_recovery_unfinished
                    "restore_prepared", "prepared" -> R.string.media_recovery_uncertain
                    "restored" -> R.string.media_recovery_restored
                    else -> R.string.media_recovery_copy_only
                }))
                row.action?.restoredMember?.let { mapping ->
                    if (row.action?.state == "restored") Text(mapping.string("name"))
                }
                if (row.canRestore) Papierknopf(stringResource(if (row.action?.state == "restore_row_prepared")
                    R.string.media_recovery_continue else R.string.journal_restore), Modifier.fillMaxWidth(), aktiv = !busy) { selected = row }
            }
        }
    }
    selected?.let { row ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(stringResource(R.string.journal_restore)) },
            text = { Text(stringResource(R.string.media_recovery_confirm, row.entry.displayName)) },
            confirmButton = { TextButton(enabled = !busy, onClick = {
                selected = null; restore(row)
            }) { Text(stringResource(R.string.journal_restore)) } },
            dismissButton = { TextButton(onClick = { selected = null }) { Text(stringResource(R.string.abbrechen)) } })
    }
}

private fun recoveryActivity(context: Context): ComponentActivity? {
    var current = context
    while (current is ContextWrapper && current !is ComponentActivity) {
        val next = current.baseContext
        if (next === current) return null
        current = next
    }
    return current as? ComponentActivity
}
