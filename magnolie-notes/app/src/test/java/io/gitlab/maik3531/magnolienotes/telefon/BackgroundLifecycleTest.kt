package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import android.net.nsd.NsdManager
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.baum.Entdeckung
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implements
import org.robolectric.annotation.Implementation
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.Provider
import java.security.Security
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

@Implements(NsdManager::class)
class LifecycleNsdShadow {
    companion object { var starts = 0; var stops = 0 }
    @Implementation fun discoverServices(type: String, protocol: Int, listener: NsdManager.DiscoveryListener) { starts++ }
    @Implementation fun stopServiceDiscovery(listener: NsdManager.DiscoveryListener) { stops++ }
}

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, application = Application::class, shadows = [LifecycleNsdShadow::class])
class BackgroundLifecycleTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private val plain = object : TelefonPayloadStorage {
        override fun encryptPayload(clear: ByteArray, type: String, id: String) = clear.copyOf()
        override fun decryptPayload(value: ByteArray, type: String, id: String) = value.copyOf()
    }
    private fun field(work: TelefonWerk, name: String) = TelefonWerk::class.java.getDeclaredField(name).apply { isAccessible = true }
    private fun fixture(action: (TelefonAblage, TelefonWerk, TelefonQueue) -> Unit) {
        val provider = object : Provider("BackgroundLifecycleKeys", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        var work: TelefonWerk? = null
        try {
            val storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
            work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
                .apply { isAccessible = true }.newInstance(context, storage)
            action(storage, work, field(work, "queue").get(work) as TelefonQueue)
        } finally { work?.serviceStopped(); Security.removeProvider(provider.name) }
    }

    @Test fun unpairInvalidatesPausedSessionEffectsAndPurgesDurableQueues() = fixture { storage, work, queue ->
        for (boundary in listOf("handshake", "received-control", "prepare-controls", "personal-sync")) {
            val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)),
                own_device = true, remote_own_device = true, personal_notes_sync_granted = true,
                remote_personal_notes_sync_granted = true)
            storage.savePeer(peer)
            queue.queue(peer.device_id, "capabilities.update", TelefonNachrichten.capabilities(), 60_000)
            val generation = field(work, "pairingGeneration").getLong(work)
            val ready = CountDownLatch(1)
            val resume = CountDownLatch(1)
            val outcome = java.util.concurrent.CompletableFuture<Throwable?>()
            val worker = thread(isDaemon = true) {
                ready.countDown()
                try {
                    check(resume.await(3, TimeUnit.SECONDS))
                    when (boundary) {
                        "handshake" -> work.sessionEstablished(peer, generation, TelefonTransportArt.WIFI)
                        "received-control" -> TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), ByteArrayOutputStream(),
                            ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4)).use { channel ->
                            work.receiveMessage(peer, TelefonNachrichten.message("grants.update", TelefonNachrichten.grants(), 60_000), channel, generation)
                        }
                        "prepare-controls" -> TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                            .apply { isAccessible = true }.invoke(work, peer)
                        else -> work.personalSyncNow()
                    }
                    outcome.complete(null)
                } catch (error: Throwable) { outcome.complete(if (error is java.lang.reflect.InvocationTargetException) error.cause else error) }
            }
            assertTrue(ready.await(3, TimeUnit.SECONDS))
            work.unpair()
            assertNull(storage.peers().peer)
            resume.countDown()
            assertTrue("$boundary was not revoked", outcome.get(3, TimeUnit.SECONDS) is TelefonProtokollFehler)
            worker.join(3000)
            assertFalse(worker.isAlive)
            assertNull(storage.peers().peer)
            assertFalse(queue.hasKind(peer.device_id, "capabilities.update"))
            assertFalse(queue.hasKind(peer.device_id, "grants.update"))
            assertFalse(queue.hasKind(peer.device_id, "personal_sync.settings"))
            assertThrows(TelefonProtokollFehler::class.java) { work.personalSyncNow() }
            // Re-pairing the same identity does not revive a prior session generation.
            storage.savePeer(peer)
            assertThrows(TelefonProtokollFehler::class.java) { work.peerEffect(peer, generation) { error("stale effect") } }
            work.unpair()
        }
    }

    @Test fun switchingComputersPreservesPairingsQueuesAndPerComputerPreferences() = fixture { storage, work, queue ->
        val home = TelefonPeer(UUID.randomUUID().toString(), "Same name", TelefonKrypto.b64(ByteArray(32) { 1 }),
            own_device = true, personal_notes_sync_granted = true)
        val office = TelefonPeer(UUID.randomUUID().toString(), "Same name", TelefonKrypto.b64(ByteArray(32) { 2 }),
            own_device = true, personal_tasks_sync_granted = true)
        storage.savePeer(home)
        storage.setPersonalSync(true, true, false, true)
        queue.queue(home.device_id, "capabilities.update", TelefonNachrichten.capabilities(), 60_000)
        val oldGeneration = field(work, "pairingGeneration").getLong(work)
        work.selectComputer(null)
        assertNull(storage.peers().peer)
        assertEquals(listOf(home.device_id), storage.peers().all().map { it.device_id })
        assertTrue(queue.hasKind(home.device_id, "capabilities.update"))
        storage.savePeer(office)
        storage.setPersonalSync(true, false, true, false)
        queue.queue(office.device_id, "capabilities.update", TelefonNachrichten.capabilities(), 60_000)
        work.selectComputer(home.device_id)
        assertEquals(home.static_public, storage.peers().peer!!.static_public)
        assertTrue(storage.personalAutoWifi()); assertTrue(storage.personalNotesEnabled()); assertFalse(storage.personalTasksEnabled())
        assertEquals(2, work.state.value.pairedComputers.size)
        assertThrows(TelefonProtokollFehler::class.java) { work.peerEffect(home, oldGeneration) { error("stale session") } }
        assertTrue(queue.hasKind(office.device_id, "capabilities.update"))

        val reloaded = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java)
            .apply { isAccessible = true }.newInstance(context)
        assertEquals(storage.peers(), reloaded.peers())
        work.selectComputer(office.device_id)
        assertTrue(storage.personalTasksEnabled()); assertFalse(storage.personalNotesEnabled()); assertFalse(storage.personalAutoWifi())
        val notes = io.gitlab.maik3531.magnolienotes.daten.Ablage.hole(context)
        notes.sichereNotiz(io.gitlab.maik3531.magnolienotes.daten.Notiz("retained-note", text = "Keep this content"))
        for (computer in listOf(home, office)) notes.personalSyncStageProposals(UUID.randomUUID().toString(), computer.device_id,
            listOf(io.gitlab.maik3531.magnolienotes.daten.PersonalDeletionProposal("", UUID.randomUUID().toString(), "note", "retained-note",
                clock = emptyList(), prior_hash = "a".repeat(64), deleted_ms = 1)))
        val beforeUnpair = notes.notizen()
        work.unpair()
        assertEquals(beforeUnpair, notes.notizen())
        assertEquals(listOf(home.device_id), notes.bestand.value.personalSync.pending_proposals.map { it.source_device })
        assertEquals(listOf(home.device_id), storage.peers().all().map { it.device_id })
        assertFalse(queue.hasKind(office.device_id, "capabilities.update"))
        assertTrue(queue.hasKind(home.device_id, "capabilities.update"))
        work.selectComputer(home.device_id)
        assertEquals(home.static_public, storage.peers().peer!!.static_public)
        assertThrows(IllegalArgumentException::class.java) { storage.savePeer(home.copy(static_public = office.static_public)) }
        assertEquals(home.static_public, storage.peers().peer!!.static_public)
    }

    @Test fun interruptedComputerSelectionRestoresOnlyThePersistedComputerPreferences() = fixture { storage, _, _ ->
        val first = TelefonPeer(UUID.randomUUID().toString(), "First", TelefonKrypto.b64(ByteArray(32) { 1 }),
            own_device = true, personal_notes_sync_granted = true, saved_auto_wifi = true)
        val second = TelefonPeer(UUID.randomUUID().toString(), "Second", TelefonKrypto.b64(ByteArray(32) { 2 }),
            own_device = true, personal_tasks_sync_granted = true)
        storage.savePeer(first); storage.setPersonalSync(true, true, false, true)
        val prefs = context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE)
        fun reopen() = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java)
            .apply { isAccessible = true }.newInstance(context)
        prefs.edit().putString("pending_computer_selection", second.device_id).commit()
        assertEquals(first, reopen().peers().peer)
        assertTrue(storage.personalNotesEnabled()); assertFalse(storage.personalTasksEnabled())
        prefs.edit().putString("pending_computer_selection", second.device_id).commit()
        storage.savePeer(second)
        val recovered = reopen()
        assertEquals(second, recovered.peers().peer)
        assertFalse(recovered.personalNotesEnabled()); assertTrue(recovered.personalTasksEnabled())
        assertFalse(recovered.personalAutoWifi()); assertFalse(prefs.contains("pending_computer_selection"))
        assertEquals(2, recovered.peers().all().size)
    }

    @Test fun interruptedDiscoveryAlwaysUnregisters() {
        for (phone in listOf(true, false)) {
            LifecycleNsdShadow.starts = 0; LifecycleNsdShadow.stops = 0
            val t = thread {
                Thread.currentThread().interrupt()
                if (phone) TelefonEntdeckung.suchen(context) else Entdeckung.suchen(context, "fixture")
                assertTrue(Thread.currentThread().isInterrupted)
            }
            t.join(3000)
            assertFalse(t.isAlive)
            assertEquals(1, LifecycleNsdShadow.starts)
            assertEquals(1, LifecycleNsdShadow.stops)
        }
    }

    @Test fun stopClosesSocketWithoutCallingGracefulWriter() = fixture { _, work, _ ->
        val closed = CountDownLatch(1)
        var wrote = false
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = object : java.io.OutputStream() {
                override fun write(value: Int) { wrote = true; closed.await(5, TimeUnit.SECONDS) }
            }
            override fun close() { closed.countDown() }
        }
        field(work, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        val t = thread { work.serviceStopped() }
        t.join(2000)
        assertFalse(t.isAlive)
        assertEquals(0L, closed.count)
        assertFalse(wrote)
    }

    @Test fun unpairCanCloseBlockedTransmissionWithoutWaitingForItsWriterLock() = fixture { storage, work, queue ->
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)))
        storage.savePeer(peer); storage.setEnabled(true)
        field(work, "serviceRunning").setBoolean(work, true)
        queue.queue(peer.device_id, "capabilities.update", TelefonNachrichten.capabilities(), 60_000)
        val writing = CountDownLatch(1)
        val closed = CountDownLatch(1)
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = object : java.io.OutputStream() {
                override fun write(value: Int) {
                    writing.countDown()
                    check(closed.await(3, TimeUnit.SECONDS))
                    throw java.io.IOException("synthetic closed pipe")
                }
            }
            override fun close() { closed.countDown() }
        }
        field(work, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        val outcome = java.util.concurrent.CompletableFuture<Throwable?>()
        val worker = thread(isDaemon = true) {
            try {
                TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4)).use {
                    TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java)
                        .apply { isAccessible = true }.invoke(work, peer, it)
                }
                outcome.complete(null)
            } catch (error: Throwable) { outcome.complete(error) }
        }
        try {
            assertTrue(writing.await(3, TimeUnit.SECONDS))
            java.util.concurrent.CompletableFuture.runAsync { work.unpair() }.get(2, TimeUnit.SECONDS)
            assertNotNull(outcome.get(3, TimeUnit.SECONDS))
            assertNull(storage.peers().peer)
            assertFalse(queue.hasKind(peer.device_id, "capabilities.update"))
        } finally { pipe.close(); worker.join(3000) }
    }

    @Test fun masterOffPurgesAndRefusesNotificationCapture() = fixture { storage, work, queue ->
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)))
        storage.savePeer(peer); storage.setSelectedPackages(setOf("fixture.messages"))
        android.provider.Settings.Secure.putString(context.contentResolver, "enabled_notification_listeners", "${context.packageName}/.Fixture")
        val body = JsonObject(mapOf("package" to JsonPrimitive("fixture.messages")))
        queue.queue(peer.device_id, "selected_notifications_readonly.event", body, 60_000)
        storage.setEnabled(false); work.serviceStopped()
        work.publish("selected_notifications_readonly.event", body, 60_000)
        assertFalse(queue.hasKind(peer.device_id, "selected_notifications_readonly.event"))
    }

    @Test fun numberRevocationPurgesImmediatelyAndPresendRechecksPermissions() = fixture { storage, work, queue ->
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)),
            remote_incoming_call_state_granted = true, remote_incoming_call_number_granted = true)
        storage.savePeer(peer); storage.setEnabled(true); storage.setIncomingCallsEnabled(true)
        storage.setIncomingNumberEnabled(true)
        field(work, "serviceRunning").setBoolean(work, true)
        val now = System.currentTimeMillis()
        val body = JsonObject(mapOf("call_ref" to JsonPrimitive(UUID.randomUUID().toString()), "revision" to JsonPrimitive(1),
            "state" to JsonPrimitive("ringing"), "direction" to JsonPrimitive("incoming"), "number" to JsonPrimitive("+12025550123"),
            "number_status" to JsonPrimitive("available"), "started_ms" to JsonPrimitive(now), "offhook_ms" to JsonPrimitive(0),
            "ended_ms" to JsonPrimitive(0), "occurred_ms" to JsonPrimitive(now), "spam_status" to JsonPrimitive("unknown"),
            "control_origin" to JsonPrimitive("unknown"), "battery_percent" to JsonPrimitive(-1), "battery_captured_ms" to JsonPrimitive(0)))
        val first = queue.queue(peer.device_id, "incoming_call_state.event", body, 60_000)
        TelefonNachrichten.validate(first)
        work.setIncomingNumberEnabled(false)
        assertFalse(queue.hasKind(peer.device_id, "incoming_call_state.event"))
        // A recovered old row must also be rejected at the final transmission boundary.
        storage.setIncomingNumberEnabled(true)
        val recovered = queue.queue(peer.device_id, "incoming_call_state.event", body, 60_000)
        Shadows.shadowOf(context as Application).grantPermissions(android.Manifest.permission.READ_PHONE_STATE)
        Shadows.shadowOf(context as Application).denyPermissions(android.Manifest.permission.READ_CALL_LOG)
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = ByteArrayOutputStream()
            override fun close() = Unit
        }
        field(work, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4)).use { channel ->
            TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java)
                .apply { isAccessible = true }.invoke(work, peer, channel)
        }
        assertFalse(queue.hasKind(peer.device_id, "incoming_call_state.event"))
        assertEquals(0, queue.attempts(recovered.string("message_id")))
    }

    @Test fun bluetoothEligibleRowsAreSelectedBeforeLimit() {
        val queue = TelefonQueue(context, plain)
        val now = System.currentTimeMillis()
        val run = UUID.randomUUID().toString()
        val request = request(run, "auto_wifi")
        queue.rememberPersonalRun("fixture", request, now + 60_000, now - 1000)
        repeat(40) { queue.queue("fixture", "personal_sync.request", request, 60_000, now - 1000, "wifi_only") }
        val control = queue.queue("fixture", "capabilities.update", TelefonNachrichten.capabilities(), 60_000, now)
        assertEquals(listOf(control.string("message_id")), queue.due("fixture", TelefonTransportArt.BLUETOOTH, now + 1).map { it.messageId })
    }

    private fun request(id: String, trigger: String = "manual") = JsonObject(mapOf("format" to JsonPrimitive(1),
        "run_id" to JsonPrimitive(id), "trigger" to JsonPrimitive(trigger), "modules" to JsonArray(listOf(JsonPrimitive("notes")))))

    @Test fun retentionRemovesExpiredRunsButPreservesPendingDecisionMetadata() {
        val queue = TelefonQueue(context, plain)
        val now = System.currentTimeMillis()
        val expired = UUID.randomUUID().toString(); val pending = UUID.randomUUID().toString()
        for (id in listOf(expired, pending)) queue.rememberPersonalRun("fixture", request(id), now + 100, now)
        queue.cleanup(now + 200, setOf("fixture" to pending))
        TelefonDatenbank(context).use { helper ->
            helper.readableDatabase.rawQuery("SELECT run_id FROM personal_run", null).use { c ->
                assertTrue(c.moveToFirst()); assertEquals(pending, c.getString(0)); assertFalse(c.moveToNext())
            }
            assertThrows(TelefonProtokollFehler::class.java) { helper.writableDatabase.phoneCapacity("personal_run", rows = 1) }
            helper.writableDatabase.execSQL("INSERT INTO event_dedupe(event_key,seen_ms) VALUES (?,?)", arrayOf("a".repeat(64), now))
            assertThrows(TelefonProtokollFehler::class.java) {
                helper.writableDatabase.phoneCapacity("event_dedupe", bytes = 50 * 1024 * 1024 - 32)
            }
        }
        queue.cleanup(now + 200)
        assertNull(queue.personalRun("fixture", pending))
    }

    @Test fun cleanupRetainsUnappliedControlPayloadAndReplayProofBeyondWireTtl() {
        val queue = TelefonQueue(context, plain)
        val message = TelefonNachrichten.message("grants.update", TelefonNachrichten.grants(), 100, now = 1000)
        assertEquals("accepted", queue.receive("fixture", message, now = 1000).first)
        val late = 2000 + TelefonQueue.RETENTION_MS
        queue.cleanup(late)
        assertTrue(queue.receivedMatches("fixture", message))
        assertEquals("duplicate" to "none", queue.duplicateResult("fixture", message.string("message_id")))
        queue.controlApplied("fixture", message.string("message_id"))
        queue.cleanup(late)
        assertFalse(queue.receivedMatches("fixture", message))
        assertNull(queue.duplicateResult("fixture", message.string("message_id")))
    }

    @Test fun authenticationDeadlineClosesOwnedPipeUnlessDisarmed() {
        for (disarm in listOf(false, true)) {
            val closed = CountDownLatch(1)
            val pipe = object : TelefonRoehre {
                override val input = ByteArrayInputStream(byteArrayOf())
                override val output = ByteArrayOutputStream()
                override fun close() { closed.countDown() }
            }
            TelefonPaarungsRoehre(pipe, 100).use { deadline ->
                if (disarm) deadline.disarm()
                assertEquals(!disarm, closed.await(300, TimeUnit.MILLISECONDS))
            }
            assertEquals(0L, closed.count)
        }
    }

    @Test fun api35AdvertisesPermittedIncomingNumberCapture() = fixture { storage, work, queue ->
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)))
        storage.savePeer(peer); storage.setIncomingCallsEnabled(true); storage.setIncomingNumberEnabled(true)
        Shadows.shadowOf(context as Application).grantPermissions(android.Manifest.permission.READ_PHONE_STATE, android.Manifest.permission.READ_CALL_LOG)
        TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java).apply { isAccessible = true }.invoke(work, peer)
        val body = queue.due(peer.device_id, TelefonTransportArt.WIFI).first { it.payload.string("kind") == "capabilities.update" }.payload["body"] as JsonObject
        val capability = (body["items"] as JsonObject)["incoming_call_number"] as JsonObject
        assertEquals(JsonPrimitive(true), capability["available"])
    }

    @Test fun api35CallerNumberStillRequiresCallLogPermission() = fixture { storage, work, queue ->
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)))
        storage.savePeer(peer); storage.setIncomingCallsEnabled(true); storage.setIncomingNumberEnabled(true)
        Shadows.shadowOf(context as Application).grantPermissions(android.Manifest.permission.READ_PHONE_STATE)
        Shadows.shadowOf(context as Application).denyPermissions(android.Manifest.permission.READ_CALL_LOG)
        TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java).apply { isAccessible = true }.invoke(work, peer)
        val body = queue.due(peer.device_id, TelefonTransportArt.WIFI).first { it.payload.string("kind") == "capabilities.update" }.payload["body"] as JsonObject
        val capability = (body["items"] as JsonObject)["incoming_call_number"] as JsonObject
        assertEquals(JsonPrimitive(false), capability["available"])
    }
}
