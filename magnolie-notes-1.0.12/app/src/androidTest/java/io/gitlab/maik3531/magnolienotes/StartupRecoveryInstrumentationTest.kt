package io.gitlab.maik3531.magnolienotes

import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.app.Activity
import android.app.Application
import android.os.Bundle
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StartupRecoveryInstrumentationTest {
    @Test fun systemstartVorActivityUndComposeRecreationInAllenZustaenden() {
        val instrumentation = MagnolieTestRunner.instrumentation
        val app = MagnolieTestRunner.testContext.applicationContext as MagnolieApp
        repeat(500) {
            if (app.startZustand.value != StartZustand.Laden) return@repeat
            Thread.sleep(10)
        }
        assertEquals("Prozess-Startup wurde nicht vor der Activity abgeschlossen",
            StartZustand.Bereit, app.startZustand.value)

        val letzte = AtomicReference<MainActivity?>()
        val callbacks = object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: Activity, state: Bundle?) {
                if (activity is MainActivity) letzte.set(activity)
            }
            override fun onActivityStarted(activity: Activity) = Unit
            override fun onActivityResumed(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        }
        app.registerActivityLifecycleCallbacks(callbacks)
        var activity = instrumentation.startActivitySync(
            Intent(app, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        instrumentation.waitForIdleSync()

        val zustaende = listOf(
            StartZustand.Laden,
            StartZustand.Fehler(io.gitlab.maik3531.magnolienotes.daten.StartFehlerArt.RECOVERY),
            StartZustand.Laden,
            StartZustand.Bereit
        )
        try {
            zustaende.forEach { zustand ->
                app.startZustandFuerInstrumentation(zustand)
                letzte.set(null)
                instrumentation.runOnMainSync { activity.recreate() }
                repeat(50) {
                    instrumentation.waitForIdleSync()
                    if (letzte.get() != null) return@repeat
                    Thread.sleep(20)
                }
                activity = requireNotNull(letzte.get()) { "Activity-Recreation blieb aus" }
                assertEquals(zustand, app.startZustand.value)
                assertFalse(activity.isFinishing)
                val content = activity.findViewById<ViewGroup>(android.R.id.content)
                assertTrue("Compose-Inhalt fehlt", content.childCount > 0)
            }
        } finally {
            app.startZustandFuerInstrumentation(StartZustand.Bereit)
            app.unregisterActivityLifecycleCallbacks(callbacks)
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

}
