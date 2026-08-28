package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Ein abgesetzter Abschnitt mit Überschrift, wie die Blöcke im Organizer. */
@Composable
fun Abschnitt(
    ueberschrift: String,
    modifier: Modifier = Modifier,
    hinweis: String = "",
    kopfAktion: @Composable () -> Unit = {},
    inhalt: @Composable () -> Unit
) {
    Card(
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        shape = RoundedCornerShape(4.dp),
        colors = CardDefaults.cardColors(containerColor = Magnolie.papier),
        border = BorderStroke(1.dp, Magnolie.linie)
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    ueberschrift,
                    fontFamily = FontFamily.Serif,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    color = Magnolie.braun,
                    modifier = Modifier.weight(1f)
                )
                kopfAktion()
            }
            Box(
                Modifier.padding(top = 5.dp, bottom = 9.dp)
                    .fillMaxWidth().height(1.dp).background(Magnolie.goldDunkel)
            )
            if (hinweis.isNotBlank()) {
                Text(
                    hinweis,
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    color = Magnolie.braunHell,
                    modifier = Modifier.padding(bottom = 10.dp)
                )
            }
            inhalt()
        }
    }
}

/** Der Knopf des Organizers: Leder mit Goldschrift. */
@Composable
fun Lederknopf(
    beschriftung: String,
    modifier: Modifier = Modifier,
    aktiv: Boolean = true,
    beiKlick: () -> Unit
) {
    Button(
        onClick = beiKlick,
        enabled = aktiv,
        modifier = modifier,
        shape = RoundedCornerShape(3.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Magnolie.leder,
            contentColor = Magnolie.gold,
            disabledContainerColor = Magnolie.lederHell.copy(alpha = 0.4f),
            disabledContentColor = Magnolie.gold.copy(alpha = 0.5f)
        ),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 10.dp)
    ) {
        // Die Goldschrift wird ausdrücklich gesetzt; geerbt wäre sie zu blass.
        Text(
            beschriftung,
            fontFamily = FontFamily.SansSerif,
            fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp,
            color = if (aktiv) Magnolie.gold else Magnolie.gold.copy(alpha = 0.55f)
        )
    }
}

/** Der zurückhaltende Knopf: nur Goldrand auf Papier. */
@Composable
fun Papierknopf(
    beschriftung: String,
    modifier: Modifier = Modifier,
    aktiv: Boolean = true,
    ausgewaehlt: Boolean = false,
    beiKlick: () -> Unit
) {
    OutlinedButton(
        onClick = beiKlick,
        enabled = aktiv,
        modifier = modifier.semantics { selected = ausgewaehlt },
        shape = RoundedCornerShape(3.dp),
        border = BorderStroke(if (ausgewaehlt) 2.dp else 1.dp, Magnolie.goldDunkel),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = if (ausgewaehlt) Magnolie.leder else Magnolie.papier,
            contentColor = if (ausgewaehlt) Magnolie.gold else Magnolie.braun
        ),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 9.dp)
    ) {
        Text(
            beschriftung,
            fontFamily = FontFamily.SansSerif,
            fontSize = 13.sp,
            color = when {
                !aktiv -> Magnolie.braunHell
                ausgewaehlt -> Magnolie.gold
                else -> Magnolie.braun
            },
            fontWeight = if (ausgewaehlt) FontWeight.Bold else FontWeight.Normal
        )
    }
}

/** Ein Eingabefeld, das wie eine beschriebene Zeile aussieht. */
@Composable
fun Schreibfeld(
    wert: String,
    beschriftung: String,
    beiAenderung: (String) -> Unit,
    modifier: Modifier = Modifier,
    einzeilig: Boolean = true,
    serifen: Boolean = false
) {
    OutlinedTextField(
        value = wert,
        onValueChange = beiAenderung,
        label = { Text(beschriftung, fontSize = 12.sp) },
        modifier = modifier.fillMaxWidth(),
        singleLine = einzeilig,
        shape = RoundedCornerShape(3.dp),
        textStyle = androidx.compose.ui.text.TextStyle(
            fontFamily = if (serifen) FontFamily.Serif else FontFamily.SansSerif,
            fontSize = if (serifen) 16.sp else 14.sp,
            lineHeight = if (serifen) 26.sp else 20.sp,
            color = Magnolie.tinte
        ),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Magnolie.goldDunkel,
            unfocusedBorderColor = Magnolie.linie,
            focusedLabelColor = Magnolie.braun,
            unfocusedLabelColor = Magnolie.braunHell,
            cursorColor = Magnolie.rot,
            focusedContainerColor = Magnolie.papier,
            unfocusedContainerColor = Magnolie.papier
        )
    )
}

/** Eine Zeile aus Beschriftung und Wert, wie im Einstellungsblatt. */
@Composable
fun Wertzeile(name: String, wert: String, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            name,
            fontFamily = FontFamily.SansSerif,
            fontSize = 12.sp,
            color = Magnolie.braunHell,
            modifier = Modifier.width(120.dp)
        )
        Text(
            wert,
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            color = Magnolie.tinte,
            modifier = Modifier.weight(1f)
        )
    }
}

/** Das Register am unteren Rand – die Reiter des Organizers. */
@Composable
fun Register(
    blaetter: List<String>,
    gewaehlt: Int,
    beiWahl: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    // Ab Android 15 zeichnen Apps grundsätzlich bis unter die Systemleisten.
    // Das Leder darf dorthin reichen, die Reiter selbst nicht: sonst liegen
    // sie unter den Navigationsknöpfen.
    Row(
        modifier
            .fillMaxWidth()
            .lederflaeche()
            .windowInsetsPadding(WindowInsets.navigationBars)
            .padding(horizontal = 5.dp, vertical = 5.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        blaetter.forEachIndexed { platz, name ->
            val aktiv = platz == gewaehlt
            Box(
                Modifier
                    .weight(1f)
                    .height(58.dp)
                    .background(
                        if (aktiv) Magnolie.papier else Magnolie.lederHell,
                        RoundedCornerShape(topStart = 6.dp, topEnd = 6.dp)
                    )
                    .clickable { beiWahl(platz) }
                    .semantics {
                        role = Role.Tab
                        selected = aktiv
                        contentDescription = name
                    }
                    .padding(horizontal = 2.dp, vertical = 5.dp),
                contentAlignment = Alignment.Center
            ) {
                val farbe = if (aktiv) Magnolie.leder else Magnolie.gold
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Registersymbol(platz, farbe)
                    Spacer(Modifier.height(2.dp))
                    Text(
                        name,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = if (aktiv) FontWeight.Bold else FontWeight.Normal,
                        fontSize = 10.sp,
                        lineHeight = 11.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                        color = farbe
                    )
                }
            }
        }
    }
}

/** Kleine, sprachunabhängige Registersymbole im Federstrich des Organizers. */
@Composable
private fun Registersymbol(platz: Int, farbe: Color) {
    Canvas(Modifier.size(20.dp)) {
        val strich = Stroke(width = 1.7.dp.toPx(), cap = StrokeCap.Round)
        val mitte = size.width / 2f
        fun linie(x1: Float, y1: Float, x2: Float, y2: Float) =
            drawLine(farbe, Offset(x1, y1), Offset(x2, y2), strich.width, StrokeCap.Round)
        when (platz) {
            0 -> {
                drawRoundRect(farbe, Offset(3f, 2f), Size(size.width - 6f, size.height - 4f),
                    CornerRadius(2f, 2f), style = strich)
                linie(6f, 7f, size.width - 5f, 7f); linie(6f, 11f, size.width - 5f, 11f)
            }
            1 -> {
                drawRect(farbe, Offset(3f, 3f), Size(size.width - 6f, size.height - 6f), style = strich)
                linie(6f, mitte, 9f, mitte + 3f); linie(9f, mitte + 3f, size.width - 5f, 6f)
            }
            2 -> {
                linie(mitte, 2f, mitte, 13f); linie(mitte, 13f, 6f, 9f); linie(mitte, 13f, size.width - 6f, 9f)
                linie(4f, 16f, size.width - 4f, 16f)
            }
            3 -> {
                linie(mitte, 3f, mitte, size.height - 3f)
                linie(mitte, 8f, 5f, 5f); linie(mitte, 11f, size.width - 5f, 7f)
                drawCircle(farbe, 1.8f, Offset(5f, 5f)); drawCircle(farbe, 1.8f, Offset(size.width - 5f, 7f))
            }
            else -> {
                drawRoundRect(farbe, Offset(3f, 4f), Size(size.width - 6f, size.height - 7f),
                    CornerRadius(3f, 3f), style = strich)
                linie(6f, 8f, size.width - 6f, 8f); linie(7f, 12f, size.width - 7f, 12f)
            }
        }
    }
}

/** Die Kopfleiste: Ledereinband mit goldener Prägung. */
@Composable
fun Einband(titel: String, modifier: Modifier = Modifier, rechts: @Composable () -> Unit = {}) {
    Column(
        modifier
            .fillMaxWidth()
            .lederflaeche()
            .windowInsetsPadding(WindowInsets.statusBars)
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                titel,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Bold,
                fontSize = 20.sp,
                color = Magnolie.gold,
                modifier = Modifier.weight(1f)
            )
            rechts()
        }
        Box(Modifier.fillMaxWidth().height(2.dp).background(Magnolie.goldDunkel))
    }
}

@Composable
fun Zwischenraum(hoehe: Int = 10) {
    Spacer(Modifier.height(hoehe.dp))
}

/** Ein kleiner runder Knopf, wie die Symbolknöpfe im Gesundheitsblatt. */
@Composable
fun Rundknopf(
    zeichen: String,
    modifier: Modifier = Modifier,
    beschreibung: String,
    beiKlick: () -> Unit
) {
    Box(
        modifier
            .size(36.dp)
            .background(Magnolie.papierTief, RoundedCornerShape(18.dp))
            .semantics { contentDescription = beschreibung }
            .clickable(onClick = beiKlick),
        contentAlignment = Alignment.Center
    ) {
        Text(zeichen, fontFamily = FontFamily.Serif, fontSize = 18.sp, color = Magnolie.braun)
    }
}
