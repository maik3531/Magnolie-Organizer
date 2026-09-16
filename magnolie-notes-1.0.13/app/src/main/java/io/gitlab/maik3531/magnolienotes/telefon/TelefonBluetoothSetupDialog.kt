package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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

@Composable
fun TelefonBluetoothSetupDialog() {
    val context = LocalContext.current
    val work = remember(context) { TelefonWerk.get(context) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    fun denied() = Toast.makeText(context, R.string.telefon_bluetooth_berechtigung, Toast.LENGTH_LONG).show()
    val discoverable = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode > 0 && lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
            runCatching { work.startBluetoothSetup() }.onFailure { denied() }
        else denied()
    }
    fun requestDiscoverability() {
        runCatching { discoverable.launch(Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE)
            .putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, 120)) }.onFailure { denied() }
    }
    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants[Manifest.permission.BLUETOOTH_CONNECT] == true && grants[Manifest.permission.BLUETOOTH_ADVERTISE] == true)
            requestDiscoverability() else denied()
    }
    Text(stringResource(R.string.telefon_bluetooth_setup_hinweis))
    TextButton(onClick = {
        if (Build.VERSION.SDK_INT >= 31 && listOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE)
                .any { context.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED })
            permissions.launch(arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE))
        else requestDiscoverability()
    }) { Text(stringResource(R.string.telefon_bluetooth_setup)) }
    val request by work.bluetoothPairingRequest.collectAsState()
    val invitation = request?.invitation?.collectAsState()?.value
    if (invitation != null) AlertDialog(
        onDismissRequest = { request?.decide(false) },
        title = { Text(stringResource(R.string.telefon_titel)) },
        text = { Text(stringResource(R.string.telefon_verbinden, invitation.name)) },
        confirmButton = { TextButton(onClick = { request?.decide(true) }) { Text(stringResource(R.string.telefon_verbinden, invitation.name)) } },
        dismissButton = { TextButton(onClick = { request?.decide(false) }) { Text(stringResource(R.string.abbrechen)) } }
    )
    DisposableEffect(lifecycle, work) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) work.stopBluetoothSetup() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); work.stopBluetoothSetup() }
    }
}
