package io.gitlab.maik3531.magnolienotes

import android.app.NotificationManager
import android.content.Intent
import android.net.Uri
import androidx.compose.runtime.MutableState
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import javax.crypto.spec.SecretKeySpec

// Exercise Activity intent/lifecycle code without starting services or native Keystore.
@Implements(MagnolieApp::class)
class CustomNavigationAppShadow : org.robolectric.shadows.ShadowApplication() {
    @Implementation fun onCreate() {}
}

@RunWith(RobolectricTestRunner::class)
@Config(application = MagnolieApp::class, sdk = [28], shadows = [CustomNavigationAppShadow::class])
class CustomNotificationNavigationTest {
    private lateinit var app: MagnolieApp
    private lateinit var ablage: Ablage
    private val key = SecretKeySpec(ByteArray(32) { 29 }, "AES")
    private val singleton = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
    private var previous: Any? = null

    @Before fun setup() {
        app = ApplicationProvider.getApplicationContext()
        previous = singleton.get(null)
        ablage = Ablage.fuerTest(app) { key }
        singleton.set(null, ablage)
    }

    @After fun cleanup() { singleton.set(null, previous) }

    private fun notificationIntent(): Intent {
        val due = java.time.Instant.ofEpochMilli(System.currentTimeMillis()).minusSeconds(60)
            .atZone(java.time.ZoneOffset.UTC).withSecond(0).withNano(0)
        val body = CustomFixtures.changed { value ->
            value["date"] = JsonPrimitive(due.toLocalDate().toString())
            value["time"] = JsonPrimitive(due.toLocalTime().toString())
            value["timezone"] = JsonPrimitive("UTC")
            value["lead_minutes"] = JsonPrimitive(0)
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + ("frequency" to JsonPrimitive("none")))
        }
        ablage.personalCustomChange { PersonalCustom.apply(CustomFixtures.state, body) }
        Erinnerung.customMelden(app, ablage.bestand.value.personalCustom.items.keys.single(), due.toInstant().toEpochMilli())
        val notification = shadowOf(app.getSystemService(NotificationManager::class.java)).allNotifications.single()
        assertTrue(notification.actions.isNullOrEmpty())
        assertTrue(shadowOf(notification.contentIntent).isImmutable)
        assertTrue(shadowOf(notification.contentIntent).isActivity)
        return Intent(shadowOf(notification.contentIntent).savedIntent)
    }

    // Reflection keeps the same regression executable against the unfixed source.
    private fun pending(activity: MainActivity): Intent? = MainActivity::class.java.declaredFields
        .firstOrNull { it.name == "gewuenschtesCustom" }?.apply { isAccessible = true }
        ?.get(activity)?.let { (it as MutableState<*>).value as? Intent }

    @Test fun coldStartRetainsTheActualNotificationTarget() {
        val intent = notificationIntent()
        val uri = intent.dataString
        val controller = Robolectric.buildActivity(MainActivity::class.java, intent).create()
        try {
            assertEquals("Cold start must retain the Custom URI for read-only navigation", uri, pending(controller.get())?.dataString)
            assertNull(controller.get().qrPaarung.value)
        } finally { controller.destroy() }
    }

    @Test fun warmIntentRetainsTargetAndDoesNotErasePendingPairing() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            controller.get().qrPaarung.value = "pending-confirmation"
            val intent = notificationIntent()
            val uri = intent.dataString
            controller.newIntent(intent)
            assertEquals("Warm arrival must retain the Custom target", uri, pending(controller.get())?.dataString)
            assertEquals("pending-confirmation", controller.get().qrPaarung.value)
        } finally { controller.destroy() }
    }

    @Test fun warmArrivalFlushesUnsavedNoteWithoutCommittingOrDiscardingIt() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            val draft = Notiz(id = "unsaved", titel = "Draft", text = "Latest keystroke")
            ablage.setzeNotizEntwurf(draft)
            app.startZustandFuerInstrumentation(StartZustand.Bereit)
            controller.newIntent(notificationIntent())
            assertEquals("Arrival must synchronously flush the latest draft", draft, Ablage.fuerTest(app) { key }.entwurf.value.notiz)
            assertEquals(draft, ablage.entwurf.value.notiz)
            assertTrue(ablage.notizen().isEmpty())
            assertNotNull(pending(controller.get()))
        } finally { controller.destroy() }
    }

    @Test fun unrelatedOrInvalidDataCannotEraseLegitimatePairing() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            controller.get().qrPaarung.value = "pending-confirmation"
            val intent = Intent(app, MainActivity::class.java).setData(Uri.parse("magnolie://custom/not-an-id"))
            controller.newIntent(intent)
            assertEquals("pending-confirmation", controller.get().qrPaarung.value)
            assertEquals("magnolie://custom/not-an-id", intent.dataString)
            val pairing = Intent(app, MainActivity::class.java).setData(Uri.parse("magnolie-pair:e30"))
            controller.newIntent(pairing)
            assertEquals("{}", controller.get().qrPaarung.value)
            assertNull(pairing.data)
        } finally { controller.destroy() }
    }

    @Test fun retainedRequestAndEncryptedDraftSurviveActivityRecreation() {
        val draft = Notiz("draft", text = "Keep across recreation")
        ablage.setzeNotizEntwurf(draft)
        app.startZustandFuerInstrumentation(StartZustand.Bereit)
        val controller = Robolectric.buildActivity(MainActivity::class.java, notificationIntent()).create()
        val saved = android.os.Bundle()
        val uri = pending(controller.get())!!.dataString
        controller.saveInstanceState(saved).destroy()
        ablage = Ablage.fuerTest(app) { key }; singleton.set(null, ablage)
        val recreated = Robolectric.buildActivity(MainActivity::class.java, Intent(controller.get().intent)).create(saved)
        try {
            assertEquals(uri, pending(recreated.get())?.dataString)
            assertEquals(draft, ablage.entwurf.value.notiz)
            assertTrue(ablage.notizen().isEmpty())
        } finally { recreated.destroy() }
    }

    @Test fun warmTaskDraftIsFlushedWithoutReplacingItWithTheCustomId() {
        val intent = notificationIntent().putExtra(MainActivity.ZEIGE_AUFGABE, "injected")
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            val draft = Aufgabe("draft-task", titel = "Unsaved task", erinnerungsMinute = 517)
            ablage.setzeAufgabenEntwurf(draft)
            app.startZustandFuerInstrumentation(StartZustand.Bereit)
            controller.newIntent(intent)
            assertEquals(draft, Ablage.fuerTest(app) { key }.entwurf.value.aufgabe)
            assertEquals(draft, ablage.entwurf.value.aufgabe)
            assertTrue(ablage.aufgaben().isEmpty())
            assertFalse(pending(controller.get())!!.hasExtra(MainActivity.ZEIGE_AUFGABE))
        } finally { controller.destroy() }
    }

    @Test fun customLookingExtrasDoNotConsumeALegitimatePairingUri() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            val pairing = notificationIntent().setData(Uri.parse("magnolie-pair:e30"))
                .putExtra(MainActivity.ZEIGE_AUFGABE, "injected")
            controller.newIntent(pairing)
            assertEquals("{}", controller.get().qrPaarung.value)
            assertNull(pending(controller.get()))
            assertNull(pairing.data)
        } finally { controller.destroy() }
    }

    @Test fun failedArrivalFlushKeepsLatestDraftAndPendingRequestForRetry() {
        val intent = notificationIntent()
        var fail = false
        ablage = Ablage.fuerTest(app) { if (fail) throw java.io.IOException("Synthetic flush failure") else key }
        singleton.set(null, ablage)
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        try {
            val draft = Notiz("draft", text = "Must not disappear")
            ablage.setzeNotizEntwurf(draft)
            app.startZustandFuerInstrumentation(StartZustand.Bereit)
            fail = true
            controller.newIntent(intent)
            assertEquals(draft, ablage.entwurf.value.notiz)
            assertNotNull(pending(controller.get()))
            assertTrue(ablage.notizen().isEmpty())
            fail = false
            controller.saveInstanceState(android.os.Bundle())
            assertEquals(draft, Ablage.fuerTest(app) { key }.entwurf.value.notiz)
        } finally { controller.destroy() }
    }

    @Test fun ordinaryReminderStillRoutesButMalformedCustomCannotInjectATaskId() {
        Erinnerung.melden(app, Aufgabe("ordinary", titel = "Ordinary reminder"))
        val notification = shadowOf(app.getSystemService(NotificationManager::class.java)).allNotifications.single()
        val ordinary = Intent(shadowOf(notification.contentIntent).savedIntent)
        val controller = Robolectric.buildActivity(MainActivity::class.java, ordinary).create()
        val field = MainActivity::class.java.getDeclaredField("gewuenschteAufgabe").apply { isAccessible = true }
        fun task() = (field.get(controller.get()) as MutableState<*>).value
        try {
            assertEquals("ordinary", task())
            val custom = CustomNavigation.absicht(app, CustomFixtures.state, "custom:" + "0".repeat(64))
                .setData(null).putExtra(MainActivity.ZEIGE_AUFGABE, "injected")
            controller.newIntent(custom)
            assertEquals("ordinary", task())
            assertNull(pending(controller.get()))
        } finally { controller.destroy() }
    }
}
