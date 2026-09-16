package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Build
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.gitlab.maik3531.magnolienotes.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun TelefonEinladungsDialog(onConnect: (GefundenerDesktop) -> Unit) {
    val context = LocalContext.current.applicationContext
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val connect by rememberUpdatedState(onConnect)
    val scope = rememberCoroutineScope()
    var generation by remember { mutableIntStateOf(0) }
    var receiver by remember { mutableStateOf<TelefonEinladungsEmpfang?>(null) }
    var unavailable by remember { mutableStateOf(false) }
    LaunchedEffect(generation) {
        unavailable = false
        var current: TelefonEinladungsEmpfang? = null
        var advertisement: AutoCloseable? = null
        try {
            current = withContext(Dispatchers.IO) {
                val storage = TelefonAblage.get(context)
                check(storage.enabled() && storage.peers().peer == null)
                val (identity, secret) = storage.identity(Build.MODEL.orEmpty())
                secret.fill(0)
                TelefonEinladungsEmpfang(identity.device_id, identity.display_name, { desktop ->
                    scope.launch {
                        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) connect(desktop)
                    }
                })
            }
            if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
                current.close(); unavailable = true
                return@LaunchedEffect
            }
            receiver = current
            advertisement = current.advertise(context)
            current.start()
            current.finished.collect { if (it) { advertisement?.close(); unavailable = true } }
        } catch (error: kotlinx.coroutines.CancellationException) { throw error }
        catch (_: Exception) { unavailable = true }
        finally { current?.close(); advertisement?.close(); receiver = null }
    }
    DisposableEffect(lifecycle, receiver) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) receiver?.close()
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    val current = receiver
    val invitation = current?.invitation?.collectAsState()?.value
    if (invitation != null) AlertDialog(
        onDismissRequest = { current.decide(false) },
        title = { Text(stringResource(R.string.telefon_titel)) },
        text = { Text(stringResource(R.string.telefon_verbinden, invitation.name)) },
        confirmButton = { TextButton(onClick = { current.decide(true) }) {
            Text(stringResource(R.string.telefon_verbinden, invitation.name))
        } },
        dismissButton = { TextButton(onClick = { current.decide(false) }) { Text(stringResource(R.string.abbrechen)) } }
    )
    if (unavailable) TextButton(onClick = { generation++ }) { Text(stringResource(R.string.telefon_suchen)) }
}
