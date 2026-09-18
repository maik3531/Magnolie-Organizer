package io.gitlab.maik3531.magnolienotes.ui

import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Tag und Uhrzeit, wie sie im Organizer stehen: Datum in Ziffern, Uhrzeit
 * vierstellig, dazwischen ein Mittelpunkt.
 */
object Zeit {

    private fun form(muster: String) = SimpleDateFormat(muster, Locale.getDefault())

    fun uhrzeit(millis: Long): String = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(millis))

    fun datum(millis: Long): String = DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(millis))

    fun tagUndUhrzeit(millis: Long): String =
        datum(millis) + " · " + uhrzeit(millis)

    /** Die Überschrift einer Tagesgruppe: heute, gestern oder das volle Datum. */
    fun tagesueberschrift(millis: Long, heuteWort: String, gesternWort: String): String {
        val heute = Calendar.getInstance()
        val gestern = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -1) }
        val wann = Calendar.getInstance().apply { timeInMillis = millis }
        return when {
            gleicherTag(wann, heute) -> heuteWort
            gleicherTag(wann, gestern) -> gesternWort
            wann.get(Calendar.YEAR) == heute.get(Calendar.YEAR) -> form(
                android.text.format.DateFormat.getBestDateTimePattern(Locale.getDefault(), "EEEEdMMMM")
            ).format(Date(millis))
            else -> form(
                android.text.format.DateFormat.getBestDateTimePattern(Locale.getDefault(), "EEEEdMMMMy")
            ).format(Date(millis))
        }
    }

    /** Der Schlüssel, nach dem Notizen zu Tagen zusammenfallen. */
    fun tagesschluessel(millis: Long): String = form("yyyy-MM-dd").format(Date(millis))

    private fun gleicherTag(a: Calendar, b: Calendar): Boolean =
        a.get(Calendar.YEAR) == b.get(Calendar.YEAR) &&
            a.get(Calendar.DAY_OF_YEAR) == b.get(Calendar.DAY_OF_YEAR)
}
