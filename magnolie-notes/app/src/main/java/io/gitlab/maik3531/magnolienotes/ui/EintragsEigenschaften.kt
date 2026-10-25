package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import java.text.DateFormat
import java.util.Date

/** A read-only metadata view; the last transport sender is not treated as the creator. */
@Composable
internal fun EintragsEigenschaften(titel: String, erstellt: Long, geaendert: Long, ursprungApp: String,
                                   importQuelle: String = "", verbindungsQuelle: String = "", beiSchliessen: () -> Unit) {
    val unknown = stringResource(R.string.eigenschaften_unbekannt)
    fun time(value: Long): String = if (value > 0) DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(value)) else unknown
    val origin = when (ursprungApp) { "notes" -> "Magnolie Notes"; "organizer" -> "Magnolie Organizer"; else -> unknown }
    @Composable fun field(label: String, value: String) {
        Text(label, fontWeight = FontWeight.Bold)
        Text(value); Spacer(Modifier.height(8.dp))
    }
    AlertDialog(onDismissRequest = beiSchliessen,
        title = { Text(stringResource(R.string.eigenschaften_titel)) },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            if (titel.isNotBlank()) { Text(titel, fontWeight = FontWeight.Bold); Spacer(Modifier.height(12.dp)) }
            field(stringResource(R.string.eigenschaften_erstellt), time(erstellt))
            field(stringResource(R.string.eigenschaften_geaendert), time(geaendert))
            field(stringResource(R.string.eigenschaften_ursprung), origin)
            if (importQuelle.isNotBlank()) field(stringResource(R.string.eigenschaften_import), importQuelle)
            if (verbindungsQuelle.isNotBlank()) field(stringResource(R.string.eigenschaften_verbindung), verbindungsQuelle)
        } }, confirmButton = { Papierknopf(stringResource(R.string.zurueck), beiKlick = beiSchliessen) })
}
