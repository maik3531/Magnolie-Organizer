package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.io.File
import java.io.EOFException
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.Provider
import java.security.Security
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec

/** Actual encrypted TCP runtimes with synthetic established-session keys; no handset. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class PersonalSyncActorTransportTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun pythonActorRuntimeStagesPhoneSnapshotWithoutGuiAndSurvivesLostMarkedAck() {
        runHost(false)
    }

    @Test fun windowsActorRuntimeStagesPhoneSnapshotWithoutGui() {
        runHost(true)
    }

    private fun runHost(windows: Boolean) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("ActorCrossFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val oldStorage = field(TelefonAblage::class.java, "instance").get(null)
        val oldWork = field(TelefonWerk::class.java, "instance").get(null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        val image = byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10, 1, 2, 3)
        documents.setzeNotiz(Notiz("phone-note", "Owned phone snapshot", "Only private staging", angelegt = 1, geaendert = 2,
            anhaenge = listOf(io.gitlab.maik3531.magnolienotes.daten.Anhang("actor-image", "owned.png", "image",
                "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(image)))))
        documents.setzeAufgabe(Aufgabe("phone-task", "Owned phone task"))
        val storage = TelefonAblage.get(context)
        val identity = storage.identity("Owned actor phone"); identity.second.fill(0)
        storage.setEnabled(true); storage.setPersonalSync(true, true, true, false, false)
        val command = if (windows) listOf(requireNotNull(System.getenv("MAGNOLIE_DOTNET")),
            File("../magnolie-organizer-windows/tests/bin/Debug/net8.0/CoreTests.dll").canonicalPath,
            "--personal-actor-host", identity.first.device_id, identity.first.static_public)
        else listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
            "../magnolie-organizer/pruefungen/personal_actor_transport_host.py", identity.first.device_id, identity.first.static_public)
        val process = ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.PIPE).start()
        var work: TelefonWerk? = null
        try {
            val output = process.inputStream.bufferedReader()
            val host = TelefonKanonisch.json.parseToJsonElement(CompletableFuture.supplyAsync { output.readLine() }.get(20, TimeUnit.SECONDS)).jsonObject
            val peerId = host.string("device_id")
            storage.savePeer(TelefonPeer(peerId, "Owned actor desktop", host.string("static_public"),
                capabilities_revision = 1, grants_revision = 1, own_device = true,
                personal_notes_sync_granted = true, personal_tasks_sync_granted = true,
                remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
                remote_personal_notes_sync_versions = listOf(1, 2, 3, 5, 9, 10, 12),
                remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6, 7, 9, 10, 12)))
            val runtime = TelefonWerk.get(context); work = runtime
            runtime.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (name, value) ->
                if (name in setOf("personal_notes_sync", "personal_tasks_sync")) value.copy(versions = value.versions + 12) else value
            } }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(runtime, true)
            (field(TelefonWerk::class.java, "connecting").get(runtime) as AtomicBoolean).set(true)
            runtime.changeSharedSetting(peerId, host.string("static_public"), "content_mode", JsonPrimitive("phone_scope"))
            runtime.changeSharedSetting(peerId, host.string("static_public"), "auto_mode", JsonPrimitive("manual"))
            val queue = field(TelefonWerk::class.java, "queue").get(runtime) as TelefonQueue
            Socket("127.0.0.1", host.long("port").toInt()).use { socket ->
                socket.soTimeout = 1000
                val pipe = object : TelefonRoehre {
                    override val input = socket.getInputStream()
                    override val output = socket.getOutputStream()
                    override fun close() = socket.close()
                }
                field(TelefonWerk::class.java, "activeTransport").set(runtime, TelefonTransportArt.WIFI to pipe)
                TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                    ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                    field(TelefonWerk::class.java, "activeChannel").set(runtime, channel)
                    val session = PersonalNoteSession()
                    @Suppress("UNCHECKED_CAST")
                    val sessions = field(TelefonWerk::class.java, "noteSessions").get(runtime) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                    sessions[channel] = session
                    TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                        .apply { isAccessible = true }.invoke(runtime, storage.peers().peer)
                    val localPeer = requireNotNull(storage.peers().peer)
                    // Explicit owned-fixture advertisement; production phase1 remains unchanged.
                    queue.removeKind(peerId, "capabilities.update")
                    queue.queue(peerId, "capabilities.update", TelefonNachrichten.capabilities(localPeer.capabilities_revision,
                        runtime.sharedLocalCapabilities()), 86400000)
                    queue.queue(peerId, "personal_sync.settings", buildJsonObject { put("format", 1); put("own_device", true) }, 60000)
                    val pump = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java,
                        TelefonSecureChannel::class.java, Long::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                    fun pumpActor() {
                        // Preference agreement can refresh controls. Keep every owned-fixture
                        // advertisement consistent with its explicit v12 source hook.
                        queue.due(peerId, TelefonTransportArt.WIFI).map { it.payload }
                            .firstOrNull { it["kind"] == JsonPrimitive("capabilities.update") }?.let { control ->
                                val body = control.getValue("body").jsonObject
                                val items = body.getValue("items").jsonObject
                                val updated = JsonObject(items.mapValues { (name, value) ->
                                    if (name in setOf("personal_notes_sync", "personal_tasks_sync")) JsonObject(value.jsonObject +
                                        ("versions" to JsonArray((value.jsonObject.getValue("versions").jsonArray.map { it.jsonPrimitive.content.toInt() } + 12)
                                            .distinct().sorted().map(::JsonPrimitive)))) else value
                                })
                                if (updated != items) {
                                    queue.removeKind(peerId, "capabilities.update")
                                    queue.queue(peerId, "capabilities.update", JsonObject(body + ("items" to updated)), 86400000)
                                }
                            }
                        pump.invoke(runtime, storage.peers().peer, channel, 0L, false)
                    }
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(55)
                    var closed = false
                    while (!closed && System.nanoTime() < deadline) {
                        pumpActor()
                        val packet = try { channel.receive() } catch (_: SocketTimeoutException) { continue }
                            catch (error: EOFException) {
                                process.waitFor(3, TimeUnit.SECONDS)
                                val hostError = if (!process.isAlive) process.errorStream.bufferedReader().readText() else "Host still running"
                                throw AssertionError("Native actor host closed unexpectedly: $hostError", error)
                            }
                        when (packet.string("type")) {
                            "ack" -> runtime.handleSessionAck(requireNotNull(storage.peers().peer), packet, session, 0L, TelefonTransportArt.WIFI)
                            "message" -> {
                                if (packet["kind"] == JsonPrimitive(PersonalSyncActor.START_KIND)) {
                                    val current = requireNotNull(storage.peers().peer)
                                    val controls = TelefonWerk::class.java.getDeclaredMethod("contentScopeControlsReady", TelefonPeer::class.java,
                                        PersonalNoteSession::class.java).apply { isAccessible = true }.invoke(runtime, current, session)
                                    val live = io.gitlab.maik3531.magnolienotes.daten.PersonalSync.livePersonalContent(documents.bestand.value)
                                    assertNotNull("Phone source gate: active=${field(TelefonWerk::class.java, "activeChannel").get(runtime) === channel}, " +
                                        "fresh=${session.capabilitiesReceived}/${session.grantsReceived}/${session.ownSettingsReceived}, " +
                                        "own=${current.own_device}/${current.remote_own_device}/${session.actorOwnDecision}, " +
                                        "shared=${session.sharedSent == session.sharedReceived}, scope=${session.contentScopeMessages.size}/${session.contentScopeAccepted}, " +
                                        "enabled=${storage.enabled()}/${field(TelefonWerk::class.java, "serviceRunning").get(runtime)}, " +
                                        "generation=${field(TelefonWerk::class.java, "pairingGeneration").get(runtime)}, controls=$controls, " +
                                        "feature=${PersonalSyncActor.supported(current, runtime.sharedLocalCapabilities())}, " +
                                        "versions=${current.remote_personal_notes_sync_versions}/${current.remote_personal_tasks_sync_versions}, " +
                                        "selection=${session.contentScopeSelection == live}, epoch=${session.contentScopeRestoreEpoch == documents.baum.value.syncEpoch}, " +
                                        "preference=${session.contentScopePreference == session.sharedSent?.get("settings")?.jsonObject?.get("content_mode")}",
                                        runtime.currentActorSource(peerId, current.static_public, channel, 0L))
                                }
                                runtime.receiveMessage(requireNotNull(storage.peers().peer), packet, channel, 0L)
                            }
                            "ping" -> channel.send(buildJsonObject { put("type", "pong"); put("ping_id", packet.getValue("ping_id")); put("sent_ms", packet.getValue("sent_ms")) })
                            "pong" -> Unit
                            "close" -> closed = true
                            else -> error("Unexpected actor transport packet")
                        }
                    }
                    assertTrue("Native actor TCP exchange did not finish", closed)
                }
            }
            assertTrue(process.waitFor(10, TimeUnit.SECONDS)); assertEquals(0, process.exitValue())
            val result = TelefonKanonisch.json.parseToJsonElement(output.readLine()).jsonObject
            assertEquals(JsonPrimitive(!windows), result["lost_marked_ack_replayed"])
            assertEquals(JsonPrimitive(true), result["attachment_integrity_verified"])
            if (!windows) assertEquals(JsonPrimitive(true), result["attachment_request_retried"])
            assertEquals(JsonPrimitive(false), result["gui_adoption"]); assertEquals(JsonPrimitive(false), result["book_persisted"])
            @Suppress("UNCHECKED_CAST")
            val handles = field(TelefonWerk::class.java, "personalActorHandles").get(runtime) as Map<String, PersonalActorHandle>
            assertTrue(runtime.personalActorJournal.stopped(requireNotNull(handles[result.string("actor_id")])))
            val pendingAttachments = TelefonQueue::class.java.getDeclaredMethod("hasAuthenticatedOutgoingAttachments", String::class.java, String::class.java)
                .apply { isAccessible = true }.invoke(field(TelefonWerk::class.java, "queue").get(runtime), host.string("device_id"), result.string("actor_id")) as Boolean
            assertFalse("Native transfer completion left outgoing attachment chunks retained", pendingAttachments)
            assertEquals(setOf("phone-note"), documents.bestand.value.notizen.map { it.id }.toSet())
            assertEquals(setOf("phone-task"), documents.bestand.value.aufgaben.map { it.id }.toSet())
        } finally {
            work?.serviceStopped()
            if (process.isAlive) { process.destroy(); if (!process.waitFor(3, TimeUnit.SECONDS)) { process.destroyForcibly(); process.waitFor(3, TimeUnit.SECONDS) } }
            work?.let { (field(TelefonQueue::class.java, "helper").get(field(TelefonWerk::class.java, "queue").get(it)) as TelefonDatenbank).close() }
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            field(TelefonAblage::class.java, "instance").set(null, oldStorage)
            field(TelefonWerk::class.java, "instance").set(null, oldWork)
            context.deleteDatabase("magnolie_phone.db"); Security.removeProvider(provider.name)
        }
    }
}
