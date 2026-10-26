package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import io.gitlab.maik3531.magnolienotes.BuildConfig
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.aktualisierung.NotesVeroeffentlichung
import io.gitlab.maik3531.magnolienotes.aktualisierung.NotesVersionsInfo
import kotlinx.coroutines.CancellationException

@Composable
internal fun NotesVersionsHinweis() {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val uriHandler = LocalUriHandler.current
    val quelle = remember { NotesVeroeffentlichung() }
    var generation by remember { mutableIntStateOf(0) }
    var prueft by remember { mutableStateOf(true) }
    var info by remember { mutableStateOf<NotesVersionsInfo?>(null) }
    LaunchedEffect(lifecycle, generation) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            prueft = true; info = null
            try { info = quelle.pruefen(BuildConfig.VERSION_NAME) }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { info = null }
            prueft = false
        }
    }
    Column {
        val current = info
        when {
            prueft -> Text(stringResource(R.string.about_update_checking))
            current == null -> Text(stringResource(R.string.about_update_unavailable))
            current.neuer -> Text(stringResource(R.string.about_update_available, current.version))
            else -> Text(stringResource(R.string.about_update_published, current.version))
        }
        if (!prueft && current?.neuer == true) Papierknopf(stringResource(R.string.about_update_release)) {
            uriHandler.openUri(current.releaseUrl)
        }
        if (!prueft) Papierknopf(stringResource(R.string.about_update_retry)) { generation++ }
    }
}
