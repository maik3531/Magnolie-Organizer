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
        expectUpgradeSentinel = arguments?.getString("expect_upgrade_sentinel") == "true"
        start()
    }

    override fun onStart() {
        instrumentation = this
        val classes = arrayOf(
            StartupRecoveryInstrumentationTest::class.java,
            UpgradeMigrationInstrumentationTest::class.java,
            AndroidKeyStoreDatenTest::class.java
        )
        val expected = classes.sumOf { type -> type.methods.count { it.isAnnotationPresent(org.junit.Test::class.java) } }
        val ergebnis = JUnitCore.runClasses(*classes)
        val complete = ergebnis.wasSuccessful() && ergebnis.runCount == expected && expected > 0 &&
            ergebnis.ignoreCount == 0 && ergebnis.assumptionFailureCount == 0
        val fehlertext = StringBuilder()
        ergebnis.failures.forEach {
            if (fehlertext.isNotEmpty()) fehlertext.append('\n')
            fehlertext.append(it.toString())
        }
        val meldung = Bundle().apply {
            putString("stream", fehlertext.toString())
            putInt("numtests", ergebnis.runCount)
            putInt("failures", if (complete) 0 else maxOf(1, ergebnis.failureCount))
            putInt("declaredtests", expected)
        }
        finish(if (complete) Activity.RESULT_OK else Activity.RESULT_CANCELED, meldung)
    }

    companion object {
        var expectUpgradeSentinel: Boolean = false
            private set
        lateinit var testContext: Context
            private set
        lateinit var instrumentation: Instrumentation
            private set
    }
}
