package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.AufgabenSortierung
import io.gitlab.maik3531.magnolienotes.daten.ListenAnzeige
import io.gitlab.maik3531.magnolienotes.daten.NotizenSortierung

/** Local presentation choices, deliberately separate from shared content and grants. */
internal class ListenEinstellungen(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("magnolie_list_view", Context.MODE_PRIVATE)
    fun lesen() = ListenAnzeige(
        aufgaben = AufgabenSortierung.entries.firstOrNull { it.name == prefs.getString("tasks_sort", null) } ?: AufgabenSortierung.FAELLIGKEIT,
        aufgabenAbsteigend = prefs.getBoolean("tasks_descending", false),
        notizen = NotizenSortierung.entries.firstOrNull { it.name == prefs.getString("notes_sort", null) } ?: NotizenSortierung.DATUM,
        notizenAbsteigend = prefs.getBoolean("notes_descending", true),
        tagesgruppen = prefs.getBoolean("notes_day_groups", true)
    )
    fun speichern(value: ListenAnzeige) {
        check(prefs.edit().putString("tasks_sort", value.aufgaben.name).putBoolean("tasks_descending", value.aufgabenAbsteigend)
            .putString("notes_sort", value.notizen.name).putBoolean("notes_descending", value.notizenAbsteigend)
            .putBoolean("notes_day_groups", value.tagesgruppen).commit()) { "view_preferences_unavailable" }
    }
}
