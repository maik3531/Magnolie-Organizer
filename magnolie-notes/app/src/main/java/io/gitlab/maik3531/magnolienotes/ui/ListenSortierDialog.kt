package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.*

@Composable
internal fun ListenSortierKnopf(aufgaben: Boolean, beiKlick: () -> Unit) {
    val label = stringResource(if (aufgaben) R.string.sortierung_aufgaben else R.string.sortierung_notizen)
    IconButton(onClick = beiKlick, modifier = Modifier.semantics { contentDescription = label }) {
        Canvas(Modifier.size(24.dp)) {
            val line = size.width / 12
            val top = size.height * .16f; val bottom = size.height * .84f
            val left = size.width * .3f; val right = size.width * .7f; val head = size.width * .17f
            drawLine(Magnolie.gold, Offset(left, bottom), Offset(left, top), line, StrokeCap.Round)
            drawLine(Magnolie.gold, Offset(left - head, top + head), Offset(left, top), line, StrokeCap.Round)
            drawLine(Magnolie.gold, Offset(left + head, top + head), Offset(left, top), line, StrokeCap.Round)
            drawLine(Magnolie.gold, Offset(right, top), Offset(right, bottom), line, StrokeCap.Round)
            drawLine(Magnolie.gold, Offset(right - head, bottom - head), Offset(right, bottom), line, StrokeCap.Round)
            drawLine(Magnolie.gold, Offset(right + head, bottom - head), Offset(right, bottom), line, StrokeCap.Round)
        }
    }
}

@Composable
internal fun ListenSortierDialog(aufgaben: Boolean, value: ListenAnzeige, beiSpeichern: (ListenAnzeige) -> Unit, beiAbbrechen: () -> Unit) {
    var draft by remember(value, aufgaben) { mutableStateOf(value) }
    @Composable fun choice(label: String, selected: Boolean, choose: () -> Unit) {
        Row(Modifier.fillMaxWidth().selectable(selected, role = Role.RadioButton, onClick = choose), verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected, null); Text(label)
        }
    }
    AlertDialog(onDismissRequest = beiAbbrechen,
        title = { Text(stringResource(if (aufgaben) R.string.sortierung_aufgaben else R.string.sortierung_notizen)) },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            if (aufgaben) {
                for ((mode, text) in listOf(AufgabenSortierung.FAELLIGKEIT to R.string.sortierung_faelligkeit,
                    AufgabenSortierung.ERSTELLT to R.string.sortierung_erstellt, AufgabenSortierung.GEAENDERT to R.string.sortierung_geaendert,
                    AufgabenSortierung.PRIORITAET to R.string.sortierung_prioritaet, AufgabenSortierung.MANUELL to R.string.sortierung_manuell)) {
                    choice(stringResource(text), draft.aufgaben == mode) { draft = draft.copy(aufgaben = mode) }
                }
            } else {
                choice(stringResource(R.string.sortierung_erstellt), draft.notizen == NotizenSortierung.DATUM) { draft = draft.copy(notizen = NotizenSortierung.DATUM) }
                choice(stringResource(R.string.sortierung_geaendert), draft.notizen == NotizenSortierung.GEAENDERT) { draft = draft.copy(notizen = NotizenSortierung.GEAENDERT) }
            }
            val descending = if (aufgaben) draft.aufgabenAbsteigend else draft.notizenAbsteigend
            choice(stringResource(R.string.sortierung_aufsteigend), !descending) { draft = if (aufgaben) draft.copy(aufgabenAbsteigend = false) else draft.copy(notizenAbsteigend = false) }
            choice(stringResource(R.string.sortierung_absteigend), descending) { draft = if (aufgaben) draft.copy(aufgabenAbsteigend = true) else draft.copy(notizenAbsteigend = true) }
            if (!aufgaben) Row(Modifier.fillMaxWidth().toggleable(draft.tagesgruppen, role = Role.Checkbox,
                onValueChange = { draft = draft.copy(tagesgruppen = it) }), verticalAlignment = Alignment.CenterVertically) {
                Checkbox(draft.tagesgruppen, null); Text(stringResource(R.string.sortierung_tagesgruppen))
            }
        } },
        confirmButton = { Papierknopf(stringResource(R.string.sichern)) { beiSpeichern(draft) } },
        dismissButton = { Papierknopf(stringResource(R.string.abbrechen), beiKlick = beiAbbrechen) })
}
