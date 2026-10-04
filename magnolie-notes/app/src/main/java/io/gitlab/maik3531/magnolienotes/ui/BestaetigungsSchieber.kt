package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt
import kotlin.math.abs

/** A tap never commits. Pointer confirmation requires dragging the thumb to the end. */
@Composable
fun BestaetigungsSchieber(text: String, bestaetigenText: String, aktionsKey: String,
                         aktiv: Boolean = true, beiBestaetigung: () -> Unit) {
    var position by remember(aktionsKey) { mutableFloatStateOf(0f) }
    var breite by remember { mutableFloatStateOf(0f) }
    val handlung by rememberUpdatedState(beiBestaetigung)
    val thumb = with(LocalDensity.current) { 48.dp.toPx() }
    val rtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    val weg = (breite - thumb).coerceAtLeast(1f)
    LaunchedEffect(aktionsKey, aktiv) { position = 0f }
    fun bestaetigen(): Boolean {
        if (!aktiv || position < 0.98f) return false
        position = 0f
        handlung()
        return true
    }
    val form = RoundedCornerShape(28.dp)
    Box(Modifier.fillMaxWidth().height(58.dp).padding(vertical = 3.dp)
        .background(if (aktiv) Magnolie.leder else Magnolie.papierTief, form)
        .border(1.dp, if (aktiv) Magnolie.goldDunkel else Magnolie.linieStark, form)
        .padding(2.dp).onSizeChanged { breite = it.width.toFloat() }
        .semantics(mergeDescendants = true) {
            contentDescription = text
            progressBarRangeInfo = ProgressBarRangeInfo(position, 0f..1f, 9)
            if (!aktiv) disabled()
            setProgress { value -> if (aktiv) { position = value.coerceIn(0f, 1f); true } else false }
            customActions = listOf(CustomAccessibilityAction(bestaetigenText) { bestaetigen() })
        }
        .onPreviewKeyEvent { event ->
            if (!aktiv || event.type != KeyEventType.KeyDown) false else when (event.key) {
                Key.DirectionRight -> { position = (position + if (rtl) -0.1f else 0.1f).coerceIn(0f, 1f); true }
                Key.DirectionLeft -> { position = (position + if (rtl) 0.1f else -0.1f).coerceIn(0f, 1f); true }
                Key.Enter, Key.NumPadEnter -> bestaetigen()
                Key.Escape -> { position = 0f; true }
                else -> false
            }
        }.focusable(aktiv)
        .pointerInput(aktionsKey, aktiv, breite, rtl) {
            if (!aktiv) return@pointerInput
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false)
                val x = if (rtl) breite - down.position.x else down.position.x
                if (x !in (position * weg)..(position * weg + thumb)) return@awaitEachGesture
                val startPosition = position
                var dragging = false
                try {
                    while (true) {
                        val event = awaitPointerEvent()
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        if (change.isConsumed || event.changes.any { it.id != down.id && it.pressed }) break
                        val dx = change.position.x - down.position.x
                        val dy = change.position.y - down.position.y
                        if (!dragging) {
                            if (abs(dy) > viewConfiguration.touchSlop && abs(dy) > abs(dx)) break
                            dragging = abs(dx) > viewConfiguration.touchSlop
                        }
                        if (dragging) {
                            // Absolute pointer position includes the final UP position even
                            // when Android coalesces MOVE events under a slow frame rate.
                            position = (startPosition + (if (rtl) -dx else dx) / weg).coerceIn(0f, 1f)
                            change.consume()
                        }
                        if (!change.pressed) {
                            if (dragging) bestaetigen()
                            break
                        }
                    }
                } finally { position = 0f }
            }
        }, contentAlignment = Alignment.Center) {
        Text(text, color = if (aktiv) Magnolie.gold else Magnolie.braunHell,
            fontFamily = FontFamily.SansSerif, fontSize = 13.sp,
            modifier = Modifier.padding(horizontal = 48.dp))
        Box(Modifier.align(Alignment.CenterStart).offset { IntOffset((position * weg).roundToInt(), 0) }
            .size(48.dp).background(Magnolie.papier, RoundedCornerShape(24.dp))
            .border(1.dp, Magnolie.gold, RoundedCornerShape(24.dp)), contentAlignment = Alignment.Center) {
            Text(if (rtl) "‹" else "›", fontSize = 28.sp, color = Magnolie.leder)
        }
    }
}
