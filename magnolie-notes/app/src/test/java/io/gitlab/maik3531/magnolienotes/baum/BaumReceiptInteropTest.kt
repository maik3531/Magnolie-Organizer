package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread

@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class BaumReceiptInteropTest {
    private class Host(val platform: String, val root: File, val initial: () -> JsonObject) : AutoCloseable {
        private lateinit var process: Process
        private val output = LinkedBlockingQueue<String>()
        lateinit var info: JsonObject
        fun start() {
            output.clear()
            val command = if (platform == "linux") listOf("python3", File("werkzeuge/receipt_host.py").absolutePath,
                root.absolutePath, File("../magnolie-organizer/bin/magnolie-organizer").canonicalPath)
            else listOf(System.getenv("MAGNOLIE_DOTNET") ?: error("Explicit .NET path is required"),
                System.getenv("MAGNOLIE_RECEIPT_HOST") ?: error("Fresh Windows receipt host DLL is required"), root.absolutePath,
                System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("Fresh CoreTests DLL is required"))
            process = ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.INHERIT).start()
            thread(isDaemon = true) { process.inputStream.bufferedReader().forEachLine {
                if (it.startsWith("RECEIPT_HOST ")) output.put(it.removePrefix("RECEIPT_HOST "))
            } }
            try { write(initial()); info = read() } catch (error: Throwable) { close(); throw error }
        }
        private fun write(value: JsonObject) { process.outputStream.write((Kanonisch.text(value) + "\n").toByteArray()); process.outputStream.flush() }
        private fun read(): JsonObject = Kanonisch.json.parseToJsonElement(output.poll(20, TimeUnit.SECONDS)
            ?: error("$platform host produced no response; alive=${process.isAlive}")).jsonObject
        fun command(op: String, vararg fields: Pair<String, JsonElement>): JsonObject {
            write(JsonObject(mapOf("op" to JsonPrimitive(op)) + fields)); return read()
        }
        override fun close() {
            if (!::process.isInitialized) return
            if (process.isAlive) runCatching { write(buildJsonObject { put("op", JsonPrimitive("quit")) }) }
            if (!process.waitFor(5, TimeUnit.SECONDS)) { process.destroy(); if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly() }
        }
    }
    @Test fun freshWindowsAndroidLegacyReceiptBothDirectionsAndFaults() = cross("windows")
    @Test fun freshLinuxAndroidLegacyReceiptBothDirectionsAndFaults() = cross("linux")

    private fun cross(platform: String) {
        assumeTrue("Explicit cross-platform fixture gate", System.getenv("MAGNOLIE_RECEIPT_INTEROP") == "1")
        for (mode in listOf("normal", "unsigned", "wrong-mac", "wrong-binding", "lost")) {
            val root = kotlin.io.path.createTempDirectory("baum-cross-$platform-").toFile()
            val androidDir = File(root, "android").apply { mkdirs() }
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = androidDir
            }
            val key = SecretKeySpec(ByteArray(32) { 49 }, "AES")
            fun load() = Ablage.fuerTest(context) { key }
            val own = Krypto.neuesSchluesselpaar().let { EigeneIdentitaet("android", "Owned Android", Krypto.b64(it.second), Krypto.b64(it.first), 8737) }
            var data = load()
            data.setzeBaum(Baumzustand(kennung = own.kennung, name = own.name, geheim = own.geheim, oeffentlich = own.oeffentlich, dienstAn = true))
            val calls = AtomicInteger()
            val incoming = AtomicReference<JsonObject>()
            var replyMode = mode
            lateinit var server: Server
            fun serve() {
                val work = Baumwerk.fuerTest(data, context)
                server = Server(object : Server.Handlung by work {
                    override fun legacyNachricht(umschlag: JsonObject, quelle: String): JsonObject {
                        calls.incrementAndGet(); incoming.set(umschlag)
                        val receipt = work.legacyNachricht(umschlag, quelle)
                        return when (replyMode) {
                            "unsigned" -> JsonObject(emptyMap())
                            "wrong-mac" -> JsonObject(receipt + ("mac" to JsonPrimitive(Krypto.b64(ByteArray(32)))))
                            "wrong-binding" -> {
                                val peer = data.baum.value.partner.single()
                                val partnerKey = Krypto.partnerschluessel(own.geheim, peer.oeffentlich, own.kennung, peer.kennung)
                                try { Baum1Quittung.erstellen(partnerKey, peer.kennung, "other", umschlag) } finally { partnerKey.fill(0) }
                            }
                            "lost" -> { server.anhalten(); receipt }
                            else -> receipt
                        }
                    }
                }, 0)
                check(server.starten())
            }
            serve()
            val host = Host(platform, File(root, "host").apply { mkdirs() }) { buildJsonObject {
                put("id", JsonPrimitive(own.kennung)); put("public", JsonPrimitive(own.oeffentlich)); put("port", JsonPrimitive(server.port))
            } }
            try {
                host.start()
                val id = host.info.getValue("id").jsonPrimitive.content
                val public = host.info.getValue("public").jsonPrimitive.content
                fun route() { data.aendereBaum { it.copy(partner = it.partner.map { p -> p.copy(port = host.info.getValue("port").jsonPrimitive.int) }) } }
                data.aendereBaum { it.copy(partner = listOf(Partner(id, "Owned host", public, adresse = "127.0.0.1",
                    port = host.info.getValue("port").jsonPrimitive.int, bestaetigt = true, vertraut = true, protokoll = "baum-1"))) }
                data.setzeAufgabe(Aufgabe("task", "Owned fixture", delegiertAn = id))
                fun body(clock: Long) = buildJsonObject { put("id", JsonPrimitive("task")); put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(clock)) }
                fun enqueue() { data.aendereBaum { it.copy(postfach = it.postfach + Sendung(UUID.randomUUID().toString(), Krypto.b64(Krypto.zufallsbytes(16)),
                    id, "stand", Kanonisch.text(body(100)), angelegt = System.currentTimeMillis(), syncEpoch = it.syncEpoch)) } }
                val vector = Kanonisch.json.parseToJsonElement(File("../contracts/baum-1-receipt-v1-vectors.json").readText()).jsonObject
                assertEquals(vector["receipt"], host.command("vector", "key" to vector.getValue("partnerKeyHex"), "envelope" to vector.getValue("envelope")))
                host.command("mode", "value" to JsonPrimitive(mode))
                enqueue()
                val work = Baumwerk.fuerTest(data, context)
                val reserved = work.sendungVorbereiten(data.baum.value.postfach.single().id)!!
                val wire = Kanonisch.json.parseToJsonElement(reserved.baum1Umschlag).jsonObject
                assertEquals(if (mode == "normal") 1 else 0, work.postfachAbarbeiten())
                assertEquals(1, host.command("stats").getValue("inbox").jsonPrimitive.int)
                if (mode != "normal") assertTrue(load().baum.value.postfach.single().brauchtPruefung)
                else assertTrue(load().baum.value.postfach.isEmpty())
                val sent = host.command("send", "body" to body(200))
                assertEquals(if (mode == "normal") 0 else 1, sent.getValue("outbox").jsonArray.size)
                assertTrue(data.aufgabe("task")!!.erledigt)
                assertEquals(1, calls.get())
                val peerKey = Krypto.partnerschluessel(own.geheim, public, own.kennung, id)
                if (mode == "normal") {
                    val receipt = WlanTransport("127.0.0.1", host.info.getValue("port").jsonPrimitive.int).anfrage("/magnolie/v1/nachricht", wire)
                    assertTrue(Baum1Quittung.pruefen(peerKey, own.kennung, id, wire, receipt))
                    assertEquals(1, host.command("stats").getValue("inbox").jsonPrimitive.int)
                    assertThrows(BaumFehler::class.java) { WlanTransport("127.0.0.1", host.info.getValue("port").jsonPrimitive.int)
                        .anfrage("/magnolie/v1/nachricht", JsonObject(wire + ("nonce" to JsonPrimitive("changed")))) }
                }
                host.close(); server.anhalten(); data = load(); replyMode = "normal"; serve(); host.start(); route()
                assertEquals(id, host.info.getValue("id").jsonPrimitive.content)
                assertEquals(public, host.info.getValue("public").jsonPrimitive.content)
                if (mode == "normal") {
                    val receipt = WlanTransport("127.0.0.1", host.info.getValue("port").jsonPrimitive.int).anfrage("/magnolie/v1/nachricht", wire)
                    assertTrue(Baum1Quittung.pruefen(peerKey, own.kennung, id, wire, receipt))
                    assertEquals(1, host.command("stats").getValue("inbox").jsonPrimitive.int)
                    val before = data.journalNutzlast()
                    val replay = WlanTransport("127.0.0.1", server.port).anfrage("/magnolie/v1/nachricht", incoming.get())
                    assertTrue(Baum1Quittung.pruefen(peerKey, id, own.kennung, incoming.get(), replay))
                    assertEquals(before, data.journalNutzlast())
                } else {
                    val previousCalls = calls.get()
                    enqueue()
                    assertEquals(0, Baumwerk.fuerTest(data, context).postfachAbarbeiten())
                    assertEquals(0, host.command("stats").getValue("requests").jsonPrimitive.int)
                    val after = host.command("send", "body" to body(300)).getValue("outbox").jsonArray
                    assertEquals(2, after.size)
                    assertEquals(JsonPrimitive(true), after.first().jsonObject["unsicher"])
                    assertEquals(JsonPrimitive(true), after.first().jsonObject["receiptAttempted"])
                    assertEquals(previousCalls, calls.get())
                    assertEquals(reserved.baum1Umschlag, load().baum.value.postfach.first().baum1Umschlag)
                }
                peerKey.fill(0)
            } finally { host.close(); server.anhalten(); root.deleteRecursively() }
        }
    }
}
