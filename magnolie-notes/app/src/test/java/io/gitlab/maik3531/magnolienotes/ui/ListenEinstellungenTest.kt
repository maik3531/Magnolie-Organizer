package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class ListenEinstellungenTest {
    private lateinit var context: Context
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("magnolie_list_view", Context.MODE_PRIVATE).edit().clear().commit()
    }
    @Test fun freshPreferencesUseTheRequestedDefaults() {
        assertEquals(ListenAnzeige(), ListenEinstellungen(context).lesen())
    }
    @Test fun bothListChoicesAndOptionalDayGroupingSurviveRecreation() {
        val value = ListenAnzeige(aufgaben = AufgabenSortierung.PRIORITAET, aufgabenAbsteigend = true,
            notizen = NotizenSortierung.GEAENDERT, notizenAbsteigend = false, tagesgruppen = false)
        ListenEinstellungen(context).speichern(value)
        assertEquals(value, ListenEinstellungen(context).lesen())
        ListenEinstellungen(context).speichern(value.copy(tagesgruppen = true))
        assertTrue(ListenEinstellungen(context).lesen().tagesgruppen)
    }
    @Test fun unknownFutureEnumValuesFallBackWithoutErasingStoredChoices() {
        val prefs = context.getSharedPreferences("magnolie_list_view", Context.MODE_PRIVATE)
        prefs.edit().putString("tasks_sort", "future-mode").putString("notes_sort", "future-mode").commit()
        assertEquals(ListenAnzeige(), ListenEinstellungen(context).lesen())
        assertEquals("future-mode", prefs.getString("tasks_sort", null))
    }
}
