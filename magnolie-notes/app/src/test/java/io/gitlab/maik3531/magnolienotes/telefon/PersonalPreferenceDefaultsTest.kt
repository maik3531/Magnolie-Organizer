package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PersonalPreferenceDefaultsTest {
    private lateinit var context: Context
    private fun storage(): TelefonAblage {
        val constructor = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java)
        constructor.isAccessible = true
        return constructor.newInstance(context)
    }

    @Before fun clearPreferences() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test fun freshDefaultsEnableOwnNotesTasksAndAutomaticWifi() {
        val store = storage()
        assertTrue(store.personalOwnDevice())
        assertTrue(store.personalNotesEnabled())
        assertTrue(store.personalTasksEnabled())
        assertTrue(store.personalAutoWifi())
        assertFalse(store.personalDeletionsEnabled())
    }

    @Test fun explicitDisableSurvivesStorageRecreation() {
        storage().setPersonalSync(false, false, false, false, false)
        val restored = storage()
        assertFalse(restored.personalOwnDevice())
        assertFalse(restored.personalNotesEnabled())
        assertFalse(restored.personalTasksEnabled())
        assertFalse(restored.personalAutoWifi())
    }

    @Test fun explicitEnabledPreferencesSurviveStorageRecreation() {
        storage().setPersonalSync(true, true, true, true, false)
        val restored = storage()
        assertTrue(restored.personalOwnDevice())
        assertTrue(restored.personalAutoWifi())
        assertFalse(restored.personalDeletionsEnabled())
    }

    @Test fun contactChoiceIsBoundToConfirmedComputerKeyAndManualDisableSurvivesReopen() {
        val id = "11111111-1111-4111-8111-111111111111"
        val key = TelefonKrypto.b64(ByteArray(32) { 3 })
        assertTrue(storage().rememberedContactReadChoice(id, key))
        storage().rememberContactReadChoice(id, key, true)
        assertTrue(storage().rememberedContactReadChoice(id, key))
        storage().rememberContactReadChoice(id, key, false)
        assertFalse(storage().rememberedContactReadChoice(id, key))
        assertTrue(storage().rememberedContactReadChoice(id, TelefonKrypto.b64(ByteArray(32) { 4 })))
    }

    @Test fun newTreeIsEnabledButStoredDisableIsNotOverridden() {
        assertTrue(Baumzustand().dienstAn)
        assertFalse(Json.decodeFromString<Baumzustand>("""{"dienstAn":false}""").dienstAn)
    }

    @Test fun groupWriteDefaultsOnAndExplicitChoiceIsBoundToComputerKey() {
        val id = "11111111-1111-4111-8111-111111111111"
        val key = TelefonKrypto.b64(ByteArray(32) { 3 })
        assertTrue(TelefonPeer(id, "Computer", key).contact_groups_write_enabled)
        assertTrue(storage().rememberedContactGroupWriteChoice(id, key))
        storage().rememberContactGroupWriteChoice(id, key, false)
        assertFalse(storage().rememberedContactGroupWriteChoice(id, key))
        assertTrue(storage().rememberedContactGroupWriteChoice(id, TelefonKrypto.b64(ByteArray(32) { 4 })))
        storage().rememberContactGroupWriteChoice(id, key, true)
        assertTrue(storage().rememberedContactGroupWriteChoice(id, key))
    }

    @Test fun generalContactWriteChoiceMigratesOptOutAndKeepsBothChoicesBoundToTheComputerKey() {
        val id = "11111111-1111-4111-8111-111111111111"
        val key = TelefonKrypto.b64(ByteArray(32) { 3 })
        val other = TelefonKrypto.b64(ByteArray(32) { 4 })
        assertTrue(TelefonPeer(id, "Computer", key).contacts_write_enabled)
        assertTrue(storage().rememberedContactWriteChoice(id, key))
        storage().rememberContactGroupWriteChoice(id, key, false)
        assertFalse(storage().rememberedContactWriteChoice(id, key))
        storage().rememberContactWriteChoice(id, key, true)
        assertTrue(storage().rememberedContactWriteChoice(id, key))
        assertTrue(storage().rememberedContactGroupWriteChoice(id, key))
        storage().rememberContactWriteChoice(id, key, false)
        assertFalse(storage().rememberedContactWriteChoice(id, key))
        assertFalse(storage().rememberedContactGroupWriteChoice(id, key))
        assertTrue(storage().rememberedContactWriteChoice(id, other))
        assertTrue(storage().rememberedContactWriteChoice("22222222-2222-4222-8222-222222222222", key))
    }

    @Test fun aLegacyEffectiveFlagIsNotMistakenForAnExplicitSavedOptOut() {
        val id = "11111111-1111-4111-8111-111111111111"
        val key = TelefonKrypto.b64(ByteArray(32) { 3 })
        assertFalse(TelefonPeer(id, "Computer", key, contact_groups_write_enabled = false).contacts_write_enabled)
        assertTrue(storage().rememberedContactWriteChoice(id, key))
        storage().rememberContactGroupWriteChoice(id, key, false)
        assertFalse(storage().rememberedContactWriteChoice(id, key))
    }
}
