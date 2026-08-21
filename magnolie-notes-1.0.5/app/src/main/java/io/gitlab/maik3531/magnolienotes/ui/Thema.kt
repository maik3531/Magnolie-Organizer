package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Dieselbe Farbwelt und derselbe Zuschnitt wie das Stilblatt des Organizers:
 * Leder und Gold außen, Papier mit Linienspiegel innen, Tinte als Schrift.
 */
object Magnolie {
    val lederDunkel = Color(0xFF3C1F15)
    val leder = Color(0xFF55291C)
    val lederHell = Color(0xFF6B3A29)
    val gold = Color(0xFFD8B25C)
    val goldDunkel = Color(0xFFA8823C)
    val papier = Color(0xFFF6EFDC)
    val papierTief = Color(0xFFECE1C4)
    val linie = Color(0xFFD8C39A)
    val linieStark = Color(0xFFAB9468)
    val tinte = Color(0xFF3A3128)
    val braun = Color(0xFF5A4630)
    val braunHell = Color(0xFF93805D)
    val rot = Color(0xFFB5443A)
    val filz = Color(0xFF2E3A34)

    /** Die Registerfarben des Organizers, für die Notizbücher. */
    val register = listOf(
        Color(0xFFC99A63), Color(0xFF8FA98C), Color(0xFFB08AA6),
        Color(0xFF7E9BB5), Color(0xFFC58F7A), Color(0xFF9A9668)
    )
}

private val farben = lightColorScheme(
    primary = Magnolie.leder,
    onPrimary = Magnolie.gold,
    primaryContainer = Magnolie.lederHell,
    onPrimaryContainer = Magnolie.gold,
    secondary = Magnolie.goldDunkel,
    onSecondary = Magnolie.papier,
    background = Magnolie.papier,
    onBackground = Magnolie.tinte,
    surface = Magnolie.papier,
    onSurface = Magnolie.tinte,
    surfaceVariant = Magnolie.papierTief,
    onSurfaceVariant = Magnolie.braun,
    outline = Magnolie.linieStark,
    error = Magnolie.rot,
    onError = Magnolie.papier
)

/** Serifen fürs Gedruckte, Grotesk für die Beschriftungen – wie im Organizer. */
private val schrift = Typography(
    titleLarge = TextStyle(
        fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold,
        fontSize = 21.sp, color = Magnolie.gold
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.Serif, fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp, color = Magnolie.tinte
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Serif, fontSize = 16.sp,
        lineHeight = 26.sp, color = Magnolie.tinte
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif, fontSize = 14.sp, color = Magnolie.tinte
    ),
    bodySmall = TextStyle(
        fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.braunHell
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp
    )
)

@Composable
fun MagnolieThema(inhalt: @Composable () -> Unit) {
    MaterialTheme(colorScheme = farben, typography = schrift, content = inhalt)
}

/** Der Ledereinband als Hintergrund – für Kopfleiste und Register. */
fun Modifier.lederflaeche(): Modifier = this.background(
    Brush.linearGradient(
        colors = listOf(Color(0xFF7A4530), Magnolie.leder, Color(0xFF361A10)),
        start = Offset.Zero,
        end = Offset(600f, 600f)
    )
)

/**
 * Ein Blatt Papier mit Linienspiegel. Die Linien liegen bewusst blass hinter
 * dem Text, wie im gedruckten Organizer.
 */
@Composable
fun Papierblatt(
    modifier: Modifier = Modifier,
    linien: Boolean = true,
    innen: PaddingValues = PaddingValues(16.dp),
    inhalt: @Composable BoxScope.() -> Unit
) {
    Box(
        modifier = modifier
            .background(Magnolie.papier, RoundedCornerShape(3.dp))
            .drawBehind {
                if (!linien) return@drawBehind
                val abstand = 26.dp.toPx()
                var y = abstand
                while (y < size.height) {
                    drawLine(
                        color = Magnolie.linie,
                        start = Offset(12.dp.toPx(), y),
                        end = Offset(size.width - 12.dp.toPx(), y),
                        strokeWidth = 1f
                    )
                    y += abstand
                }
            }
            .padding(innen),
        content = inhalt
    )
}

/** Der schmale Goldstrich, der im Organizer Abschnitte trennt. */
@Composable
fun Goldlinie(modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxSize()
            .background(
                Brush.horizontalGradient(
                    listOf(Color.Transparent, Magnolie.goldDunkel, Color.Transparent)
                )
            )
    )
}
