package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Symbol

/**
 * Die Sinnbilder der Notizen. Sie sind mit demselben Federstrich gezeichnet
 * wie die Symbole im Organizer: dünne Linien in Tinte, ohne Flächen, in einem
 * runden Papierfeld mit Goldrand.
 */
@Composable
fun Sinnbild(
    art: String,
    groesse: Dp = 34.dp,
    farbe: Color = Magnolie.braun,
    modifier: Modifier = Modifier
) {
    val name = sinnbildName(art)
    Box(
        modifier
            .size(groesse)
            .clip(CircleShape)
            .semantics { contentDescription = name },
        contentAlignment = Alignment.Center
    ) {
        Canvas(Modifier.size(groesse)) {
            val rand = size.minDimension * 0.5f
            drawCircle(Magnolie.papierTief, radius = rand)
            drawCircle(Magnolie.goldDunkel, radius = rand - 0.5f, style = Stroke(width = 1.2f))
            zeichne(art, farbe)
        }
    }
}

private fun DrawScope.zeichne(art: String, farbe: Color) {
    val breite = size.width
    val strich = Stroke(
        width = breite * 0.055f,
        cap = StrokeCap.Round,
        join = StrokeJoin.Round
    )
    // Alle Formen sind in einem 100x100-Feld gedacht und werden hochskaliert.
    fun p(x: Number, y: Number) =
        Offset(breite * x.toFloat() / 100f, breite * y.toFloat() / 100f)

    fun linie(x1: Number, y1: Number, x2: Number, y2: Number) =
        drawLine(farbe, p(x1, y1), p(x2, y2), strokeWidth = strich.width, cap = StrokeCap.Round)

    fun rahmen(x: Number, y: Number, b: Number, h: Number) {
        val (x0, y0) = x.toFloat() to y.toFloat()
        val (bb, hh) = b.toFloat() to h.toFloat()
        linie(x0, y0, x0 + bb, y0); linie(x0 + bb, y0, x0 + bb, y0 + hh)
        linie(x0 + bb, y0 + hh, x0, y0 + hh); linie(x0, y0 + hh, x0, y0)
    }

    fun kreis(x: Number, y: Number, r: Number) = drawCircle(
        farbe, radius = breite * r.toFloat() / 100f, center = p(x, y), style = strich
    )

    fun bogen(x: Number, y: Number, b: Number, h: Number, start: Number, weite: Number) = drawArc(
        color = farbe, startAngle = start.toFloat(), sweepAngle = weite.toFloat(),
        useCenter = false, topLeft = p(x, y),
        size = Size(breite * b.toFloat() / 100f, breite * h.toFloat() / 100f), style = strich
    )

    when (art) {
        Symbol.EINKAUF -> {                       // Korb mit Henkel
            linie(28, 42, 72, 42)
            linie(31, 42, 36, 72); linie(69, 42, 64, 72); linie(36, 72, 64, 72)
            bogen(36, 22, 28f, 34f, 180f, 180f)
        }
        Symbol.AUFGABE -> {                       // Häkchen im Kästchen
            rahmen(26, 26, 48f, 48f)
            linie(36, 51, 45, 60); linie(45, 60, 64, 39)
        }
        Symbol.TERMIN -> {                        // Uhr
            kreis(50, 50, 24f)
            linie(50, 50, 50, 34); linie(50, 50, 62, 56)
        }
        Symbol.IDEE -> {                          // Glühbirne
            kreis(50, 42, 18f)
            linie(42, 64, 58, 64); linie(44, 71, 56, 71)
        }
        Symbol.REISE -> {                         // Koffer
            rahmen(26, 40, 48f, 34f)
            bogen(40, 26, 20f, 20f, 180f, 180f)
            linie(26, 52, 74, 52)
        }
        Symbol.REZEPT -> {                        // Topf mit Deckel
            rahmen(28, 44, 44f, 28f)
            linie(22, 44, 78, 44)
            linie(50, 36, 50, 44)
        }
        Symbol.GELD -> {                          // Münze mit Strich
            kreis(50, 50, 24f)
            linie(50, 32, 50, 68)
            linie(41, 41, 59, 41); linie(41, 59, 59, 59)
        }
        Symbol.ARBEIT -> {                        // Aktentasche
            rahmen(24, 40, 52f, 34f)
            linie(40, 40, 40, 32); linie(60, 40, 60, 32); linie(40, 32, 60, 32)
            linie(24, 55, 76, 55)
        }
        Symbol.PERSON -> {                        // Kopf und Schultern
            kreis(50, 38, 13f)
            bogen(28, 54, 44f, 42f, 180f, 180f)
        }
        Symbol.GESUNDHEIT -> {                    // Kreuz
            linie(50, 30, 50, 70); linie(30, 50, 70, 50)
        }
        Symbol.ZITAT -> {                         // Anführungszeichen
            bogen(30, 34, 16f, 20f, 20f, 300f)
            bogen(54, 34, 16f, 20f, 20f, 300f)
            linie(34, 52, 34, 62); linie(58, 52, 58, 62)
        }
        else -> {                                 // Blatt Papier mit Eselsohr
            linie(34, 24, 60, 24); linie(60, 24, 68, 33)
            linie(68, 33, 68, 76); linie(68, 76, 34, 76); linie(34, 76, 34, 24)
            linie(60, 24, 60, 33); linie(60, 33, 68, 33)
            linie(41, 48, 61, 48); linie(41, 58, 61, 58)
        }
    }
}

/** Der lokalisierte Klartextname eines Sinnbilds. */
@Composable
fun sinnbildName(art: String): String = stringResource(
    when (art) {
        Symbol.EINKAUF -> R.string.symbol_einkauf
        Symbol.AUFGABE -> R.string.symbol_aufgabe
        Symbol.TERMIN -> R.string.symbol_termin
        Symbol.IDEE -> R.string.symbol_idee
        Symbol.REISE -> R.string.symbol_reise
        Symbol.REZEPT -> R.string.symbol_rezept
        Symbol.GELD -> R.string.symbol_geld
        Symbol.ARBEIT -> R.string.symbol_arbeit
        Symbol.PERSON -> R.string.symbol_person
        Symbol.GESUNDHEIT -> R.string.symbol_gesundheit
        Symbol.ZITAT -> R.string.symbol_zitat
        else -> R.string.symbol_notiz
    }
)
