package io.gitlab.maik3531.magnolietabletbeta

import android.app.Instrumentation
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Test-only physical input and full native/renderer data-integrity comparison. */
internal object NativeDomainAcceptance {
    fun stroke(test: Instrumentation, web: WebView, target: JSONObject): JSONObject {
        val origin=IntArray(2)
        test.runOnMainSync { web.getLocationOnScreen(origin) }
        val density=web.resources.displayMetrics.density
        val x1=origin[0]+target.getDouble("x1")*density
        val x2=origin[0]+target.getDouble("x2")*density
        val y=origin[1]+target.getDouble("y")*density
        check(listOf(x1,x2,y).all { it.isFinite() && it>=0 } && x2>x1)
        val started=SystemClock.elapsedRealtime()
        val output=test.uiAutomation.executeShellCommand("input touchscreen swipe $x1 $y $x2 $y 420").use {
            ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().readText()
        }
        check(output.isBlank()) { "Native touchscreen injection failed" }
        return JSONObject().put("source","native-touchscreen").put("requestedDurationMs",420).put("durationMs",SystemClock.elapsedRealtime()-started)
    }
    private fun semantic(value: Any?): Any? = when(value) {
        null,JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().toList().sorted().associateWith { semantic(value.get(it)) }
        is JSONArray -> (0 until value.length()).map { semantic(value.get(it)) }
        is Number -> value.toDouble()
        else -> value
    }
    fun requireEqual(expected: JSONObject, actual: JSONObject, message: String) {
        check(semantic(expected)==semantic(actual)) { message }
    }
    fun hash(value: JSONObject): String = MessageDigest.getInstance("SHA-256")
        .digest(semantic(value).toString().toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
}
