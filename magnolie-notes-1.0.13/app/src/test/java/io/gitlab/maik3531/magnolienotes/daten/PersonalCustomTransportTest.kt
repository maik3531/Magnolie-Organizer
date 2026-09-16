package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.app.AlarmManager
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.telefon.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File
import java.net.Socket
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import javax.crypto.spec.SecretKeySpec

/** Established authenticated-session fixtures, not real pairing or real user profiles. */
@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class, sdk = [28])
class PersonalCustomTransportTest {
    @Test fun pythonAndNativeWindowsSecureQueuesReachDurableAndroidMirrorAndAlarms() {
        val python = System.getenv("MAGNOLIE_PYTHON") ?: "python3"
        val dotnet = System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required")
        val dll = System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required")
        val commands = listOf(listOf(python, "../magnolie-organizer-2.0.0/pruefungen/personal_custom_transport_host.py"),
            listOf(dotnet, dll, "--personal-custom-host"))
        val context = ApplicationProvider.getApplicationContext<Context>()
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
        val field = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
        val old = field.get(null)
        try {
            for (command in commands) {
                val process = ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.INHERIT).start()
                try {
                    val port = CompletableFuture.supplyAsync { process.inputStream.bufferedReader().readLine().toInt() }.get(20, TimeUnit.SECONDS)
                    var ablage = Ablage.fuerTest(context) { key }; field.set(null, ablage)
                    ablage.personalCustomChange { CustomFixtures.state }
                    Socket("127.0.0.1", port).use { socket ->
                        socket.soTimeout = 20_000
                        TelefonSecureChannel(socket.getInputStream(), socket.getOutputStream(), ByteArray(32) { 7 },
                            ByteArray(32) { 11 }, ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                            repeat(4) { index ->
                                val packet = channel.receive(); TelefonNachrichten.validate(packet)
                                val body = packet.getValue("body").jsonObject
                                if (index == 3) {
                                    ablage.personalCustomChange { it.copy(local = CustomFixtures.consent.getValue("revoked").jsonObject) }
                                    ablage = Ablage.fuerTest(context) { key }; field.set(null, ablage)
                                    assertThrows(IllegalStateException::class.java) { ablage.personalCustomChange { PersonalCustom.apply(it, body) } }
                                } else {
                                    ablage.personalCustomChange { PersonalCustom.apply(it, body) }
                                    ablage = Ablage.fuerTest(context) { key }; field.set(null, ablage)
                                    assertEquals(1, ablage.bestand.value.personalCustom.items.size)
                                }
                                Erinnerung.customNeuStellen(context)
                                assertEquals(if (index < 2) 1 else 0, shadowOf(context.getSystemService(AlarmManager::class.java)).scheduledAlarms.size)
                                assertTrue(ablage.aufgaben().isEmpty()); assertTrue(ablage.notizen().isEmpty())
                                channel.send(TelefonNachrichten.ack(packet.getValue("message_id").jsonPrimitive.content,
                                    if (index == 3) "rejected" else "accepted", if (index == 3) "not_granted" else "none"))
                            }
                            val setting = TelefonNachrichten.message("personal_sync.custom_settings", CustomFixtures.consent.getValue("revoked").jsonObject, 60_000)
                            channel.send(setting)
                            val ack = channel.receive(); TelefonNachrichten.validateAck(ack)
                            assertEquals("accepted", ack.getValue("status").jsonPrimitive.content)
                        }
                    }
                    assertTrue(process.waitFor(10, TimeUnit.SECONDS)); assertEquals(0, process.exitValue())
                } finally { process.destroyForcibly() }
            }
        } finally { field.set(null, old) }
    }
}
