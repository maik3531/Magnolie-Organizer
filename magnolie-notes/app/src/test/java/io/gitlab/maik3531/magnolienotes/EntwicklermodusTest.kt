package io.gitlab.maik3531.magnolienotes

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import java.io.File
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class EntwicklermodusTest {
    @Test fun crashReadIsBoundedReadOnlyAndUnavailableOutsideLocalDebugging() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("magnolie_developer", Context.MODE_PRIVATE).edit().clear().commit()
        val developer = Entwicklermodus(context)
        val report = File(context.filesDir, "diagnostics/magnolie-crash.txt")
        report.parentFile!!.mkdirs(); report.delete()
        assertTrue(runCatching { developer.bericht(mitAbsturz = true) }.isFailure)
        developer.aktivieren(); developer.wlanSetzen(true)
        assertEquals("false", developer.bericht(true)["crash_report"]!!.jsonObject["available"].toString())
        val text = "Magnolie Notes crash report\nException type: java.lang.IllegalArgumentException\nSynthetic stack\npassword=fixture-password; mail=person@example.test; phone=+49 351 1234567"
        report.writeText(text)
        assertFalse(developer.bericht().containsKey("crash_report"))
        val crash = developer.bericht(true)["crash_report"]!!.jsonObject
        assertEquals(setOf("available", "text", "truncated"), crash.keys)
        assertEquals("true", crash["available"].toString())
        assertEquals("Magnolie Notes crash report\nException type: java.lang.IllegalArgumentException\nSynthetic stack\npassword=***; mail=***; phone=***", (crash["text"] as kotlinx.serialization.json.JsonPrimitive).content)
        assertEquals(text, report.readText())
        report.writeText("x".repeat(20_000))
        val bounded = developer.bericht(true)["crash_report"]!!.jsonObject
        assertEquals("true", bounded["truncated"].toString())
        assertEquals(16_384, (bounded["text"] as kotlinx.serialization.json.JsonPrimitive).content.length)
        assertEquals(20_000L, report.length())
        developer.deaktivieren()
        assertTrue(runCatching { developer.bericht(true) }.isFailure)
    }

    @Test fun tenClicksPersistButDisableRevokesWifiAndResetsCounter() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("magnolie_developer", Context.MODE_PRIVATE).edit().clear().commit()
        val developer = Entwicklermodus(context)
        repeat(9) { assertFalse(developer.versionAngeklickt()) }
        assertTrue(developer.versionAngeklickt())
        developer.wlanSetzen(true)
        assertTrue(Entwicklermodus(context).wlan)
        developer.ereignis("online", "wifi")
        val report = developer.bericht()
        assertEquals(BuildConfig.VERSION_NAME, report["app_version"]?.toString()?.trim('"'))
        assertTrue(report["events"]!!.jsonArray.isNotEmpty())
        developer.ereignis("secret-token-or-contact", "wifi")
        assertEquals(report, developer.bericht())
        repeat(200) { developer.ereignis("failed", "wifi", true) }
        val bounded = developer.bericht()["events"]!!.jsonArray
        assertEquals(128, bounded.size)
        assertTrue(bounded.all { it.jsonObject.keys == setOf("time_ms", "stage", "transport", "failure") })
        assertTrue(File(context.filesDir, "diagnostics/wlan-debug.jsonl").length() <= 65536)
        developer.deaktivieren()
        assertFalse(Entwicklermodus(context).wlan)
        assertTrue(runCatching { developer.bericht() }.isFailure)
        repeat(9) { assertFalse(developer.versionAngeklickt()) }
        assertTrue(developer.versionAngeklickt())
        assertFalse(developer.wlan)
    }
}
