package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import io.gitlab.maik3531.magnolienotes.R

@Composable
fun EinstellungenBlatt(zeiterfassungAn: Boolean, speichert: Boolean, beiZeiterfassung: (Boolean) -> Unit,
                       beiBlatt: (Int) -> Unit, beiRechten: () -> Unit, beiBenachrichtigungen: () -> Unit) {
    Column(Modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())) {
        Abschnitt(stringResource(R.string.zeit_einstellungen)) {
            Papierknopf(stringResource(R.string.blatt_einfuhr), Modifier.fillMaxWidth()) { beiBlatt(2) }
            Papierknopf(stringResource(R.string.blatt_baum), Modifier.fillMaxWidth()) { beiBlatt(3) }
            Papierknopf(stringResource(R.string.blatt_journal), Modifier.fillMaxWidth()) { beiBlatt(4) }
            Papierknopf(stringResource(R.string.zeit_systemrechte), Modifier.fillMaxWidth(), beiKlick = beiRechten)
            Papierknopf(stringResource(R.string.zeit_benachrichtigungen), Modifier.fillMaxWidth(), beiKlick = beiBenachrichtigungen)
        }
        ZeiterfassungsOptionen(zeiterfassungAn, speichert, beiZeiterfassung) { beiBlatt(6) }
    }
}

@Composable
internal fun ZeiterfassungsOptionen(zeiterfassungAn: Boolean, speichert: Boolean,
                                   beiZeiterfassung: (Boolean) -> Unit, beiOeffnen: (() -> Unit)? = null) {
        Abschnitt(stringResource(R.string.zeit_titel), hinweis = stringResource(R.string.zeit_hinweis)) {
            Row(Modifier.fillMaxWidth().toggleable(zeiterfassungAn, enabled = !speichert,
                role = Role.Checkbox, onValueChange = beiZeiterfassung), verticalAlignment = Alignment.CenterVertically) {
                Checkbox(zeiterfassungAn, null, enabled = !speichert)
                Text(stringResource(R.string.zeit_aktiv))
            }
            if (beiOeffnen != null) Papierknopf(stringResource(R.string.zeit_titel), Modifier.fillMaxWidth(), beiKlick = beiOeffnen)
        }
}
