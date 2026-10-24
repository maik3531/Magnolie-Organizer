package io.gitlab.maik3531.magnolienotes.ui

import android.os.Handler
import android.os.Looper

/** A quiet single click opens About; a click sequence only reaches the existing developer gesture. */
internal class VersionsKlicks(private val beiEinzelklick: () -> Unit, private val beiVersionsklick: () -> Unit) {
    private val handler = Handler(Looper.getMainLooper())
    private var clicks = 0
    private var pending: Runnable? = null

    fun klicken() {
        pending?.let(handler::removeCallbacks)
        clicks++
        beiVersionsklick()
        val action = Runnable {
            val single = clicks == 1
            clicks = 0
            pending = null
            if (single) beiEinzelklick()
        }
        pending = action
        handler.postDelayed(action, 1_000)
    }

    fun abbrechen() {
        pending?.let(handler::removeCallbacks)
        pending = null
        clicks = 0
    }
}
