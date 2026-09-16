package io.gitlab.maik3531.magnolienotes.daten

import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class, sdk = [28])
class PersonalCustomAlarmTest {
    @Test fun oneOffNotificationRemainsVisibleAndCannotFireTwice() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
        val field = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
        val previous = field.get(null)
        try {
            val ablage = Ablage.fuerTest(context) { key }; field.set(null, ablage)
            val due = java.time.Instant.ofEpochMilli(System.currentTimeMillis()).minusSeconds(60)
                .atZone(java.time.ZoneOffset.UTC).withSecond(0).withNano(0)
            val body = CustomFixtures.changed { value ->
                value["date"] = JsonPrimitive(due.toLocalDate().toString()); value["time"] = JsonPrimitive(due.toLocalTime().toString())
                value["timezone"] = JsonPrimitive("UTC"); value["lead_minutes"] = JsonPrimitive(0)
                value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + ("frequency" to JsonPrimitive("none")))
            }
            ablage.personalCustomChange { PersonalCustom.apply(CustomFixtures.state, body) }
            val id = ablage.bestand.value.personalCustom.items.keys.single()
            val notifications = shadowOf(context.getSystemService(NotificationManager::class.java))
            Erinnerung.customMelden(context, id, due.toInstant().toEpochMilli())
            assertEquals(1, notifications.allNotifications.size)
            assertTrue(notifications.allNotifications.single().actions.isNullOrEmpty())
            Erinnerung.customMelden(context, id, due.toInstant().toEpochMilli())
            assertEquals(1, notifications.allNotifications.size)
            Erinnerung.customNeuStellen(context)
            assertEquals(1, notifications.allNotifications.size)
            ablage.personalCustomChange { it.copy(active = false) }
            Erinnerung.customNeuStellen(context)
            assertEquals(0, notifications.allNotifications.size)
        } finally { field.set(null, previous) }
    }

    @Test fun durableMirrorReopenRebootAndRevocationCancelRealAlarmManagerEntries() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
        val field = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
        val previous = field.get(null)
        try {
            var ablage = Ablage.fuerTest(context) { key }
            field.set(null, ablage)
            ablage.personalCustomChange { PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch) }
            Erinnerung.customNeuStellen(context)
            val manager = shadowOf(context.getSystemService(AlarmManager::class.java))
            assertEquals(1, manager.scheduledAlarms.size)
            ablage = Ablage.fuerTest(context) { key }; field.set(null, ablage)
            assertEquals(1, ablage.bestand.value.personalCustom.items.size)
            Erinnerung.customNeuStellen(context)
            assertEquals(1, manager.scheduledAlarms.size)
            ablage.personalCustomChange { it.copy(local = CustomFixtures.consent.getValue("revoked").jsonObject) }
            Erinnerung.customNeuStellen(context)
            assertEquals(0, manager.scheduledAlarms.size)
            val restarted = Ablage.fuerTest(context) { key }
            assertEquals(1, restarted.bestand.value.personalCustom.items.size)
            assertThrows(IllegalStateException::class.java) { restarted.personalCustomChange { PersonalCustom.apply(it, CustomFixtures.batch) } }
            assertTrue(restarted.aufgaben().isEmpty())
        } finally { field.set(null, previous) }
    }
}
