package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
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
    DisposableEffect(owner) { onDispose { session?.close(); owner.close() } }
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
    LaunchedEffect(owner) { refresh() }
    MedienWiederherstellungListe(rows, busy, failed, ::refresh) { row ->
        failed = false
        try {
            val activity = recoveryActivity(context) ?: throw IllegalStateException("Native Activity required")
            val native = NativeGalleryRestoreSession.capture(activity, checkNotNull(row.action), permit())
            session = native; busy = true
            owner.restore(native) { result ->
                native.close(); session = null; busy = false; failed = result.isFailure
                if (result.isSuccess) refresh()
            }
        } catch (_: Exception) { session?.close(); session = null; busy = false; failed = true }
    }
}

@Composable
internal fun MedienWiederherstellungListe(rows: List<NativeGalleryRecoveryRow>, busy: Boolean, failed: Boolean,
    refresh: () -> Unit, restore: (NativeGalleryRecoveryRow) -> Unit) {
    var selected by remember { mutableStateOf<NativeGalleryRecoveryRow?>(null) }
    LaunchedEffect(rows) { if (selected != null && selected !in rows) selected = null }
    Abschnitt(stringResource(R.string.media_recovery_title), hinweis = stringResource(R.string.media_recovery_hint)) {
        if (busy) Text(stringResource(R.string.media_recovery_working))
        if (failed) Text(stringResource(R.string.media_recovery_unavailable))
        Papierknopf(stringResource(R.string.media_recovery_refresh), Modifier.fillMaxWidth(), aktiv = !busy) { refresh() }
        rows.forEach { row ->
            Column {
                Text(row.entry.displayName)
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
