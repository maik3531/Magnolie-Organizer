package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test

class PersonalAutoSyncTest {
    private val local = mapOf("personal_notes_sync" to TelefonCapability(true, "available", listOf(1, 2, 3, 5, 8)),
        "personal_tasks_sync" to TelefonCapability(true, "available", listOf(1, 2, 3, 4, 6, 7, 8)))
    private val remote = TelefonPeer("fixture", "Synthetic", "fixture-key",
        remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
        remote_personal_notes_sync_versions = listOf(1, 2, 3, 5, 8),
        remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6, 7, 8))

    @Test fun bilateralFeatureNegotiationIsRequiredForTransportFreeAutomaticRuns() {
        assertTrue(PersonalAutoSync.supported(remote, local))
        assertFalse(PersonalAutoSync.supported(remote.copy(remote_personal_notes_sync_available = false), local))
        assertFalse(PersonalAutoSync.supported(remote.copy(remote_personal_tasks_sync_versions = listOf(1, 2, 3)), local))
        assertFalse(PersonalAutoSync.supported(remote, local - "personal_tasks_sync"))
        assertFalse(PersonalAutoSync.supported(remote, local + ("personal_notes_sync" to TelefonCapability(false, "disabled", listOf(8)))))
        // A feature marker never creates own-device or data-grant consent.
        assertFalse(remote.own_device || remote.remote_own_device || remote.personal_notes_sync_granted)
    }

    @Test fun legacyWifiTriggersKeepTheirMeaningAndBluetoothRequiresTheNewContract() {
        assertEquals("auto_wifi", PersonalAutoSync.trigger(TelefonTransportArt.WIFI, false))
        assertNull(PersonalAutoSync.trigger(TelefonTransportArt.BLUETOOTH, false))
        assertEquals("auto_connection", PersonalAutoSync.trigger(TelefonTransportArt.WIFI, true))
        assertEquals("auto_connection", PersonalAutoSync.trigger(TelefonTransportArt.BLUETOOTH, true))
        assertTrue(PersonalAutoSync.allowed("manual", false))
        assertTrue(PersonalAutoSync.allowed("auto_wifi", false))
        assertFalse(PersonalAutoSync.allowed("auto_connection", false))
        assertTrue(PersonalAutoSync.allowed("auto_connection", true))
        assertFalse(PersonalAutoSync.allowed("unknown", true))
        assertFalse(PersonalAutoSync.automatic("manual"))
        assertTrue(PersonalAutoSync.automatic("auto_connection"))
    }
}
