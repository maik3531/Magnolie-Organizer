package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.pow

class ContrastRegressionTest {
    @Test fun smallHintTextMeetsNormalTextContrastOnBothPaperColors() {
        fun luminance(color: Color): Double {
            fun linear(value: Float): Double = if (value <= 0.04045f) value / 12.92
                else ((value + 0.055) / 1.055).pow(2.4)
            return 0.2126 * linear(color.red) + 0.7152 * linear(color.green) + 0.0722 * linear(color.blue)
        }
        for (paper in listOf(Magnolie.papier, Magnolie.papierTief)) {
            for (text in listOf(Magnolie.braunHell, Magnolie.goldDunkel, Magnolie.rot)) {
                val ratio = (luminance(paper) + 0.05) / (luminance(text) + 0.05)
                assertTrue("Contrast $ratio must be at least 4.5", ratio >= 4.5)
            }
        }
    }
}
