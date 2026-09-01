package io.gitlab.maik3531.magnolienotes

import android.content.Context
import androidx.annotation.StringRes

/** Übersetzt stabile technische Fehlermeldungen erst am Rand zur Oberfläche. */
object Fehlertext {
    const val DATEI_OEFFNEN = "file_open"

    @StringRes
    fun ressourcenId(nachricht: String?): Int = when (nachricht) {
        DATEI_OEFFNEN, "Die Datei ließ sich nicht öffnen." -> R.string.fehler_datei_oeffnen
        "Die eigene Identität fehlt noch." -> R.string.fehler_identitaet
        "Dieses Gerät hat gerade keine Netzadresse." -> R.string.fehler_keine_netzadresse
        "Nicht erreichbar.", "Die Gegenstelle ist nicht erreichbar." -> R.string.fehler_nicht_erreichbar
        "Der Zweig ist nicht bestätigt.",
        "Dieser Zweig ist noch nicht bestätigt.",
        "Dieser Zweig ist nicht bestätigt und vertraut." -> R.string.fehler_nicht_bestaetigt
        "Der Schlüssel dieses Zweigs hat sich geändert. Entferne die alte Verbindung zuerst und vergleiche den neuen Fingerabdruck besonders sorgfältig." ->
            R.string.fehler_schluessel_geaendert
        "Die Paarungsdatei ist zu groß." -> R.string.fehler_paarungsdatei_gross
        "Die Paarungsdatei ist abgelaufen. Erzeuge im Organizer eine neue.",
        "Die Paarungsdatei gilt nicht mehr." -> R.string.fehler_paarungsdatei_abgelaufen
        "Der andere Zweig hat die Paarungsdatei nicht nachgewiesen." -> R.string.fehler_paarung_nachweis
        "Die Paarungsanfrage ist ungültig.",
        "Die Paarungsanfrage ist unvollständig." -> R.string.fehler_paarungsanfrage
        "Die Paarungsdatei ist beschädigt.",
        "Die Paarungsdatei ist ungültig.",
        "Die Paarungsdatei behauptet eine zu lange Gültigkeit.",
        "Der Port in der Paarungsdatei ist ungültig.",
        "Die Paarungsdatei wurde verändert." -> R.string.fehler_paarungsdatei_beschaedigt
        "Der eigene Schlüssel ist beschädigt.",
        "Der fremde Schlüssel ist beschädigt.",
        "Der andere Zweig hat keinen gültigen Schlüssel geschickt." -> R.string.fehler_schluessel
        "Die Antwort auf die sichere Sitzung ist ungültig.",
        "Die Gegenstelle hat nichts geantwortet.",
        "Die Gegenstelle hat den Empfang nicht bestätigt." -> R.string.fehler_antwort
        "Die Anfrage für die sichere Sitzung ist ungültig.",
        "Die sichere Sitzung ist bereits verbraucht.",
        "Die sichere Sitzung ist unbekannt oder abgelaufen.",
        "Diese sichere Sitzung gibt es schon.",
        "Zu viele sichere Sitzungen sind offen." -> R.string.fehler_sitzung
        "Base64 ist beschädigt.",
        "Unerwartete Länge in der Nachricht.",
        "Das ist keine Magnolienbaum-Nachricht.",
        "Die Nachricht kommt von einem anderen Zweig.",
        "Die Nachricht ist beschädigt.",
        "Diese Nachricht kam schon einmal an.",
        "Die Nachricht ließ sich nicht öffnen.",
        "Die sichere Nachricht ist ungültig.",
        "Die sichere Nachricht ließ sich nicht öffnen.",
        "Der Inhalt ist unlesbar." -> R.string.fehler_nachricht
        "Dieses Gerät hat kein Bluetooth." -> R.string.fehler_bluetooth_nicht_verfuegbar
        "Bluetooth ist ausgeschaltet." -> R.string.fehler_bluetooth_aus
        "Die Bluetooth-Adresse ist ungültig." -> R.string.fehler_bluetooth_adresse
        "Die Bluetooth-Berechtigung fehlt." -> R.string.fehler_bluetooth_berechtigung
        "Die Bluetooth-Verbindung kam nicht zustande." -> R.string.fehler_bluetooth_verbindung
        "Die Nachricht ist zu groß für Bluetooth.",
        "Der Bluetooth-Rahmen ist ungültig.",
        "Der Bluetooth-Rahmen ist unvollständig." -> R.string.fehler_bluetooth_nachricht
        else -> when {
            nachricht?.startsWith("Die Gegenstelle antwortete mit ") == true ->
                R.string.fehler_nicht_erreichbar
            nachricht == "Der Magnolienbaum ist am Organizer ausgeschaltet." ||
                nachricht == "Zu viele Anfragen – kurz warten." -> R.string.fehler_nicht_erreichbar
            nachricht == "Die Gegenstelle hat den Zweig nicht anerkannt." ->
                R.string.fehler_nicht_bestaetigt
            else -> R.string.fehler_allgemein
        }
    }
}

fun Context.fehlertext(fehler: Throwable): String = getString(Fehlertext.ressourcenId(fehler.message))

fun Context.fehlertext(nachricht: String?): String = getString(Fehlertext.ressourcenId(nachricht))
