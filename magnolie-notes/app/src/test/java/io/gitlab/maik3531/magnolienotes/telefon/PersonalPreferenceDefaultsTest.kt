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
}
