package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Build
import kotlinx.serialization.Serializable

@Serializable
data class TelefonIdentitaet(
    val storage_version: Int = 1,
    val device_id: String,
    val role: String = "phone",
    val display_name: String,
    val static_public: String,
    val wrapped_private: String
)

@Serializable
data class TelefonPeer(
    val device_id: String,
    val display_name: String,
    val static_public: String,
    val state: String = "paired",
    val capabilities_revision: Long = 0,
    val grants_revision: Long = 0,
    val remote_capabilities_revision: Long = 0,
    val remote_grants_revision: Long = 0,
    val device_status_granted: Boolean = true,
    val remote_device_status_granted: Boolean = true,
    val remote_device_status_available: Boolean = false,
    val remote_dial_request_granted: Boolean = false,
    val remote_dial_request_available: Boolean = false,
    val remote_answer_call_granted: Boolean = false,
    val remote_answer_call_available: Boolean = false,
    val remote_incoming_call_state_granted: Boolean = false,
    val remote_incoming_call_number_granted: Boolean = false,
    val remote_end_call_granted: Boolean = false,
    val remote_end_call_available: Boolean = false,
    val own_device: Boolean = false,
    val remote_own_device: Boolean = false,
    val personal_notes_sync_granted: Boolean = false,
    val personal_tasks_sync_granted: Boolean = false,
    val personal_deletions_sync_granted: Boolean = false,
    val remote_personal_notes_sync_granted: Boolean = false,
    val remote_personal_notes_sync_versions: List<Int> = listOf(1),
    val remote_personal_tasks_sync_granted: Boolean = false,
    val remote_personal_deletions_sync_granted: Boolean = false,
    val last_host: String = "",
    val last_contact_ms: Long = 0,
    val bluetooth_address: String = "",
    val pending_finish: String = "",
    val pending_finish_expires_ms: Long = 0
)

@Serializable
data class TelefonBestand(val storage_version: Int = 1, val peer: TelefonPeer? = null)

data class GefundenerDesktop(
    val deviceId: String,
    val name: String,
    val host: String,
    val token: String,
    val port: Int = TelefonParameter.PORT
)

enum class TelefonVerbindungsstatus {
    STOPPED, OFFLINE, DISCOVERING, HANDSHAKING, CODE_PENDING, PAIRED, AUTHENTICATING, ONLINE_WIFI, ONLINE_BLUETOOTH, ERROR
}

data class TelefonBluetoothZiel(val name: String, val address: String)
data class TelefonApp(val packageName: String, val label: String)

data class TelefonUiZustand(
    val enabled: Boolean = false,
    val bluetoothEnabled: Boolean = false,
    val connection: TelefonVerbindungsstatus = TelefonVerbindungsstatus.STOPPED,
    val peer: TelefonPeer? = null,
    val found: List<GefundenerDesktop> = emptyList(),
    val pairingCode: String = "",
    val pairingFingerprint: String = "",
    val pairingName: String = "",
    val bluetoothSelecting: Boolean = false,
    val bluetoothDevices: List<TelefonBluetoothZiel> = emptyList(),
    val dialRequestEnabled: Boolean = false,
    val dialAvailable: Boolean = false,
    val notificationsEnabled: Boolean = false,
    val incomingCallsEnabled: Boolean = false,
    val incomingNumberEnabled: Boolean = false,
    val answerCallsEnabled: Boolean = false,
    val personalOwnDevice: Boolean = false,
    val personalNotesEnabled: Boolean = false,
    val personalTasksEnabled: Boolean = false,
    val personalAutoWifi: Boolean = false,
    val personalDeletionsEnabled: Boolean = false,
    val personalSyncReport: String = "",
    val selectedPackages: Set<String> = emptySet(),
    val notificationApps: List<TelefonApp> = emptyList(),
    val notificationAccess: Boolean = false,
    val error: String = ""
)

data class DeviceStatus(
    val requestId: String,
    val model: String,
    val manufacturer: String,
    val osName: String = "Android",
    val osVersion: String,
    val batteryPercent: Int,
    val charging: String,
    val capturedMs: Long,
    val sdkInt: Int = Build.VERSION.SDK_INT,
    val batteryTemperatureDeciC: Int = -1,
    val powerSource: String = "unknown",
    val storageTotalBytes: Long = -1,
    val storageAvailableBytes: Long = -1,
    val memoryTotalBytes: Long = -1,
    val memoryAvailableBytes: Long = -1,
    val uptimeMs: Long = -1,
    val networkTransport: String = "none",
    val networkValidated: Boolean = false,
    val networkMetered: Boolean = false
)

data class TelefonCapability(val available: Boolean, val reason: String, val versions: List<Int> = listOf(1))

object TelefonCapabilities {
    fun phase1(notifications: Boolean = false, dialRequest: Boolean = false,
               dialResolvable: Boolean = false, dialPermission: Boolean = false,
               incomingCalls: Boolean = false,
               incomingNumber: Boolean = false, answerCalls: Boolean = false,
               endCalls: Boolean = false) = linkedMapOf(
        "device_status" to TelefonCapability(true, "available", listOf(1, 2)),
        "selected_notifications_readonly" to TelefonCapability(notifications, if (notifications) "available" else "disabled"),
        "dial_request" to TelefonCapability(dialRequest && dialResolvable && dialPermission,
            if (dialRequest && dialResolvable && dialPermission) "available" else if (!dialResolvable) "os_restricted"
            else if (!dialPermission) "permission_missing" else "disabled"),
        "incoming_call_state" to TelefonCapability(incomingCalls, if (incomingCalls) "available" else "disabled", listOf(2)),
        "incoming_call_number" to TelefonCapability(incomingNumber, if (incomingNumber) "available" else "disabled"),
        "answer_call" to TelefonCapability(answerCalls, if (answerCalls) "available" else "disabled"),
        "end_call" to TelefonCapability(endCalls, if (endCalls) "available" else if (Build.VERSION.SDK_INT < 28) "os_restricted" else "disabled"),
        "personal_notes_sync" to TelefonCapability(true, "available", listOf(1, 2)),
        "personal_tasks_sync" to TelefonCapability(true, "available"),
        "personal_deletions_sync" to TelefonCapability(true, "available"),
        "transport.bluetooth_rfcomm" to TelefonCapability(true, "available")
    )
}
