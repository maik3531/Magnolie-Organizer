package io.gitlab.maik3531.magnolienotes

import android.app.Activity
import android.app.Instrumentation
import android.content.Context
import android.os.Bundle
import io.gitlab.maik3531.magnolienotes.daten.AndroidKeyStoreDatenTest
import org.junit.runner.JUnitCore

/** Minimaler lokaler Runner, damit die Keystore-Instrumentation keine Netzabhaengigkeit einfuehrt. */
class MagnolieTestRunner : Instrumentation() {
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        testContext = targetContext
        start()
    }

    override fun onStart() {
        instrumentation = this
        val ergebnis = JUnitCore.runClasses(
            StartupRecoveryInstrumentationTest::class.java,
            UpgradeMigrationInstrumentationTest::class.java,
            AndroidKeyStoreDatenTest::class.java
        )
        val fehlertext = StringBuilder()
        ergebnis.failures.forEach {
            if (fehlertext.isNotEmpty()) fehlertext.append('\n')
            fehlertext.append(it.toString())
        }
        val meldung = Bundle().apply {
            putString("stream", fehlertext.toString())
            putInt("numtests", ergebnis.runCount)
            putInt("failures", ergebnis.failureCount)
        }
        finish(if (ergebnis.wasSuccessful()) Activity.RESULT_OK else Activity.RESULT_CANCELED, meldung)
    }

    companion object {
        lateinit var testContext: Context
            private set
        lateinit var instrumentation: Instrumentation
            private set
    }
}
