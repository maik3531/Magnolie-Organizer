package io.gitlab.maik3531.magnolienotes

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.annotation.StringRes
import androidx.core.content.ContextCompat

data class Einrichtungsschritt(@StringRes val titel: Int, val texte: List<Int>)

object Ersteinrichtung {
    private const val ABLAGE = "magnolie_ui_settings"
    private const val ABGESCHLOSSEN = "onboarding_completed_v1"

    val schritte = listOf(
        Einrichtungsschritt(R.string.blatt_notizen, listOf(R.string.notiz_leer)),
        Einrichtungsschritt(R.string.blatt_aufgaben, listOf(R.string.aufgabe_leer)),
        Einrichtungsschritt(R.string.blatt_einfuhr, listOf(R.string.einfuhr_erklaerung)),
        Einrichtungsschritt(R.string.blatt_baum, listOf(
            R.string.telefon_hinweis, R.string.personal_sync_hinweis, R.string.baum_erklaerung)),
        Einrichtungsschritt(R.string.blatt_journal, listOf(
            R.string.papierkorb_hinweis, R.string.journal_hinweis))
    )

    fun abgeschlossen(context: Context): Boolean =
        context.getSharedPreferences(ABLAGE, Context.MODE_PRIVATE).getBoolean(ABGESCHLOSSEN, false)

    fun abschliessen(context: Context): Boolean =
        context.getSharedPreferences(ABLAGE, Context.MODE_PRIVATE).edit()
            .putBoolean(ABGESCHLOSSEN, true).commit()

    /** Nur vom letzten Schritt der Ersteinrichtung, nie beim normalen Start. */
    internal fun abschliessenMitBenachrichtigungsfrage(context: Context, anfragen: () -> Unit): Boolean {
        if (abgeschlossen(context)) return true
        if (!abschliessen(context)) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            anfragen()
        }
        return true
    }
}
