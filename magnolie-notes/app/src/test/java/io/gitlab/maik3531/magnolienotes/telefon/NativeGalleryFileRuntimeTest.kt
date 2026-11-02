package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class NativeGalleryFileRuntimeTest {
    private val now = 1_800_000_000_000L
    private val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
    private val remote = NativeFileControlIdentity("receiver_fixture_01", "e".repeat(64))
    private class Link {
        val output = ByteArrayOutputStream()
        val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
        val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16) { 2 },
            key.copyOf(), prefix, ByteArray(32) { 5 }, ByteArray(4) { 6 })
        fun sent(): JsonObject {
            val frame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray())); output.reset()
            val header = JsonObject(frame - "ciphertext")
            val cipher = java.util.Base64.getDecoder().decode(frame.string("ciphertext"))
            val plain = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")), cipher, TelefonKanonisch.bytes(header))
            return Json.parseToJsonElement(plain.decodeToString()).jsonObject
        }
    }

    private fun negotiatedRuntime(action: (NativeGalleryFileRuntime, () -> Unit) -> Unit) {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-source-command330-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val link = Link()
        val peer = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel, true, true, true, true, true, "1".repeat(64))
        val desktopPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, "1".repeat(64))
        val state = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
        val desktop = NativeFileControlSession(remote, { desktopPeer }, { state })
        val runtime = NativeGalleryFileRuntime(org.robolectric.RuntimeEnvironment.getApplication(), root, identity, protection, link.channel, { peer }, { true })
        try {
            fun echo() {
                if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(link.sent(), now), desktopPeer)
                val packet = desktop.packet(); desktop.markSent(packet)
                runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(link.sent(), now), desktopPeer)
            }
            echo()
            action(runtime, ::echo)
        } finally { runtime.close(); desktop.close(); link.channel.close(); root.deleteRecursively() }
    }

    private fun sourceCommand(operation: String, version: String? = null) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
        put("format", JsonPrimitive(1)); put("operation", JsonPrimitive(operation))
        if (version != null) {
            put("expected_version", JsonPrimitive(version)); put("enabled", JsonPrimitive(true))
            put("kinds", JsonArray(listOf(JsonPrimitive("camera"))))
        }
    }, 60_000, now)

    @Test fun sourceCommandExpiryReachesTheNativeConfigurerBeforePolicyPublicationAndReleasesItsTicket() {
        negotiatedRuntime { runtime, _ ->
            val before = runtime.savedPolicy()
            var ticks = 0; var replies = 0
            assertThrows(PhotoFolderScopeError::class.java) {
                runtime.receiveSourceCommand(sourceCommand("configure", before.version), { replies++ },
                    { if (++ticks >= 4) now + 60_000 else now })
            }
            assertEquals(0, replies)
            assertEquals(before, runtime.savedPolicy())
            runtime.receiveSourceCommand(sourceCommand("status"), { replies++ }, { now })
            assertEquals(1, replies)
            assertNull(runtime.savedPolicy().policy)
        }
    }

    @Test fun lostSourceConfigurationReplyPreservesCommittedPolicyWithoutInventingDeliveryOrReapplyingStaleSettings() {
        negotiatedRuntime { runtime, echo ->
            val command = sourceCommand("configure", runtime.savedPolicy().version)
            assertThrows(java.io.IOException::class.java) {
                runtime.receiveSourceCommand(command, { throw java.io.IOException("actual reply write failed") }, { now })
            }
            val committed = runtime.savedPolicy()
            assertTrue(committed.policy!!.enabled)
            assertFalse(committed.repairPending)
            assertNull(runtime.currentRequest())
            echo()
            var replies = 0
            assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(command, { replies++ }, { now }) }
            assertEquals(0, replies); assertEquals(committed, runtime.savedPolicy())
            runtime.receiveSourceCommand(sourceCommand("status"), { replies++ }, { now })
            assertEquals(1, replies)
        }
    }

    @Test fun preparedPermissionMetadataCannotAuthorizeBackgroundSendAfterExpiryVersionChangeOrRevocation() {
        for (change in listOf("expired", "version", "revoked", "unchanged")) {
            negotiatedRuntime { runtime, echo ->
                runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                val saved = runtime.savedPolicy()
                val command = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", JsonPrimitive(1)); put("operation", JsonPrimitive("request_read"))
                    put("expected_version", JsonPrimitive(saved.version))
                }, 60_000, now)
                val prepared = runtime.preparePermissionReply(command, NativeGalleryPermissionCommands(), { now })
                when (change) {
                    "version" -> {
                        runtime.configureFromAuthenticatedCommand(saved, true, setOf(GallerySourceKind.SCREENSHOTS)); echo()
                    }
                    "revoked" -> runtime.revokeControl()
                }
                var writes = 0
                val send = { _: JsonObject -> writes++; Unit }
                val clock = { if (change == "expired") now + 60_000 else now }
                if (change == "unchanged") runtime.sendPreparedPermissionReply(command, prepared, send, clock)
                else assertThrows(PhotoFolderScopeError::class.java) { runtime.sendPreparedPermissionReply(command, prepared, send, clock) }
                assertEquals(if (change == "unchanged") 1 else 0, writes)
            }
        }
    }

    @Test fun actualProtectedRuntimeJoinsInitialOffNativeEchoConfigurationAndFreshSourceGrant() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val app = org.robolectric.RuntimeEnvironment.getApplication()
        try {
            for (pairing in listOf("1".repeat(64), "1".repeat(64), "2".repeat(64))) {
                val link = Link()
                val peer = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel, true, true, true, true, true, pairing)
                val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, pairing)
                val pcState = NativeLocalFileGrant(DeviceFileGrantState(7, "b".repeat(64), false, true), Any(), true)
                NativeFileControlSession(remote, { pcPeer }, { pcState }).use { desktop ->
                    NativeGalleryFileRuntime(app, root, identity, protection, link.channel, { peer }, { true }).use { runtime ->
                        fun toDesktop() {
                            assertTrue(runtime.sendControls(now))
                            desktop.observeRemote(DeviceFileControlEnvelope.validate(link.sent(), now), pcPeer)
                        }
                        fun fromDesktop() {
                            val packet = desktop.packet(); desktop.markSent(packet)
                            runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                        }
                        assertNull(runtime.currentRequest())
                        toDesktop(); fromDesktop(); toDesktop()
                        val before = runtime.savedPolicy()
                        if (before.policy?.pairingEpoch == pairing) {
                            assertNotNull(runtime.currentRequest()) // Same protected association survives a fresh real channel.
                        } else {
                            assertNull(runtime.currentRequest())
                            val saved = runtime.configureFromAuthenticatedCommand(before, true, setOf(GallerySourceKind.CAMERA))
                            assertEquals(pairing, saved.policy!!.pairingEpoch)
                            assertNull(runtime.currentRequest()) // The changed send grant is not yet echoed.
                            toDesktop(); fromDesktop()
                            assertNotNull(runtime.currentRequest())
                        }
                        assertFalse(runtime.sendControls(now))
                        assertEquals(pairing, runtime.currentRequest()!!.receiver.pairingEpoch)
                        val owner = runtime.attachForeground { }
                        val action = NativeGalleryForeground.permissionAction(owner)
                        assertTrue(NativeGalleryForeground.acceptsPermissionAction(action.token))
                        assertThrows(PhotoFolderScopeError::class.java) {
                            NativeGalleryForeground.permissionAction(NativeGalleryForegroundOwner(runtime))
                        }
                        assertEquals("gallery_workflow_permission_host_missing", assertThrows(PhotoFolderScopeError::class.java) {
                            NativeGalleryForeground.performPermissionAction(action.token) }.code)
                        assertTrue(NativeGalleryForeground.acceptsPermissionAction(action.token))
                        runtime.close()
                        assertFalse(NativeGalleryForeground.acceptsPermissionAction(action.token))
                    }
                }
                link.channel.close()
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun runtimeCannotConfigureBeforeNativeHandshakeOrCreateOffPolicyFromReading() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-closed-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val link = Link()
        var peer: NativeFileControlPeer? = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel,
            true, true, true, true, true, "1".repeat(64))
        try {
            NativeGalleryFileRuntime(org.robolectric.RuntimeEnvironment.getApplication(), root, identity, protection, link.channel, { peer }, { true }).use { runtime ->
                val empty = runtime.savedPolicy()
                assertNull(empty.policy); assertNull(runtime.currentRequest())
                assertThrows(PhotoFolderScopeError::class.java) { runtime.configureFromAuthenticatedCommand(empty, true, setOf(GallerySourceKind.CAMERA)) }
                assertEquals(empty, runtime.savedPolicy())
                peer = null
                assertNull(runtime.currentRequest())
                assertEquals(empty, runtime.disableLocally(empty))
            }
        } finally { link.channel.close(); root.deleteRecursively() }
    }

    @Test fun nativeWorkerCloseRevokesImmediatelyButDoesNotClaimFinalUiCleanupBeforeItHappens() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-end-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val link = Link()
        val peer = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel, true, true, true, true, true, "1".repeat(64))
        val runtime = NativeGalleryFileRuntime(org.robolectric.RuntimeEnvironment.getApplication(), root, identity, protection, link.channel, { peer }, { true })
        try {
            val failure = java.util.concurrent.atomic.AtomicReference<Exception?>()
            val ended = java.util.concurrent.CountDownLatch(1)
            val worker = Thread {
                try { runtime.close() } catch (error: Exception) { failure.set(error) } finally { ended.countDown() }
            }
            worker.start()
            assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); worker.join(5000)
            assertEquals("gallery_permission_ui_thread_required", (failure.get() as PhotoFolderScopeError).code)
            assertNull(runtime.currentRequest())
            assertThrows(PhotoFolderScopeError::class.java) { runtime.sendControls(now) }
            assertNull(runtime.savedPolicy().policy) // Ownership was not falsely marked fully closed.
            runtime.close() // Actual final Activity/lifecycle cleanup on the UI thread.
            assertThrows(PhotoFolderScopeError::class.java) { runtime.savedPolicy() }
        } finally { runtime.close(); link.channel.close(); root.deleteRecursively() }
    }

    @Test fun passiveForegroundRouteAttachesAnExistingRuntimeAndOldActivityCannotRemoveItsReplacement() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-activity-").toFile()
        val otherRoot = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-other-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val link = Link(); val otherLink = Link()
        val peer = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel, true, true, true, true, true, "1".repeat(64))
        val otherPeer = peer.copy(owner = otherLink.channel)
        val app = org.robolectric.RuntimeEnvironment.getApplication()
        val runtime = NativeGalleryFileRuntime(app, root, identity, protection, link.channel, { peer }, { true })
        val other = NativeGalleryFileRuntime(app, otherRoot, identity, protection, otherLink.channel, { otherPeer }, { true })
        val firstActivity = org.robolectric.Robolectric.buildActivity(androidx.activity.ComponentActivity::class.java).create()
        val firstHost = GalleryPhotoPermissionHost(firstActivity.get())
        val secondActivity = org.robolectric.Robolectric.buildActivity(androidx.activity.ComponentActivity::class.java).create()
        val secondHost = GalleryPhotoPermissionHost(secondActivity.get())
        try {
            val owner = runtime.attachForeground { }
            assertTrue(NativeGalleryForeground.isCurrent(owner))
            assertFalse(NativeGalleryForeground.isCurrent(NativeGalleryForegroundOwner(runtime)))
            assertSame(owner, runtime.attachForeground { })
            assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryForeground.permissionAction(owner) }
            assertEquals("gallery_workflow_permission_host_missing", assertThrows(PhotoFolderScopeError::class.java) { runtime.requestReadPermission() }.code)
            NativeGalleryForeground.registerHost(firstHost)
            firstActivity.start().resume()
            assertEquals("gallery_source_not_activated", assertThrows(PhotoFolderScopeError::class.java) { runtime.requestReadPermission() }.code)
            assertNull(org.robolectric.Shadows.shadowOf(firstActivity.get()).lastRequestedPermission)
            assertThrows(PhotoFolderScopeError::class.java) { other.attachForeground { } }
            other.close()
            assertTrue(NativeGalleryForeground.isCurrent(owner))
            NativeGalleryForeground.registerHost(secondHost)
            secondActivity.start().resume()
            NativeGalleryForeground.unregisterHost(firstHost)
            assertEquals("gallery_source_not_activated", assertThrows(PhotoFolderScopeError::class.java) { runtime.requestReadPermission() }.code)
            assertNull(org.robolectric.Shadows.shadowOf(secondActivity.get()).lastRequestedPermission)
            runtime.close()
            assertFalse(NativeGalleryForeground.isCurrent(owner))
        } finally {
            runtime.close(); other.close()
            NativeGalleryForeground.unregisterHost(firstHost); NativeGalleryForeground.unregisterHost(secondHost)
            firstActivity.pause().stop().destroy(); secondActivity.pause().stop().destroy()
            link.channel.close(); otherLink.channel.close(); root.deleteRecursively(); otherRoot.deleteRecursively()
        }
    }

    @Test fun boundForegroundActionReachesActualAndroidLauncherOnceAndOldSourceIntentCannotRevive() {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-runtime330-tap-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val app = org.robolectric.RuntimeEnvironment.getApplication()
        org.robolectric.Shadows.shadowOf(app).denyPermissions(android.Manifest.permission.READ_EXTERNAL_STORAGE)
        val activity = org.robolectric.Robolectric.buildActivity(androidx.activity.ComponentActivity::class.java).create()
        val host = GalleryPhotoPermissionHost(activity.get())
        NativeGalleryForeground.registerHost(host); activity.start().resume()
        val link = Link()
        val peer = NativeFileControlPeer(remote.deviceId, remote.identitySha256, link.channel, true, true, true, true, true, "1".repeat(64))
        val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, "1".repeat(64))
        val state = NativeLocalFileGrant(DeviceFileGrantState(7, "b".repeat(64), false, true), Any(), true)
        val desktop = NativeFileControlSession(remote, { pcPeer }, { state })
        val runtime = NativeGalleryFileRuntime(app, root, identity, protection, link.channel, { peer }, { true })
        try {
            fun toDesktop() {
                assertTrue(runtime.sendControls(now))
                desktop.observeRemote(DeviceFileControlEnvelope.validate(link.sent(), now), pcPeer)
            }
            fun fromDesktop() {
                val packet = desktop.packet(); desktop.markSent(packet)
                runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
            }
            val results = mutableListOf<Result<GalleryReadCoverage>>()
            val owner = runtime.attachForeground { results += it }
            toDesktop(); fromDesktop(); toDesktop()
            runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
            toDesktop(); fromDesktop()
            val action = NativeGalleryForeground.permissionAction(owner)
            assertNull(org.robolectric.Shadows.shadowOf(activity.get()).lastRequestedPermission)
            NativeGalleryForeground.performPermissionAction(action.token)
            val pending = org.robolectric.Shadows.shadowOf(activity.get()).lastRequestedPermission!!
            assertFalse(NativeGalleryForeground.acceptsPermissionAction(action.token))
            assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryForeground.performPermissionAction(action.token) }
            org.robolectric.Shadows.shadowOf(app).grantPermissions(android.Manifest.permission.READ_EXTERNAL_STORAGE)
            @Suppress("DEPRECATION")
            activity.get().onRequestPermissionsResult(pending.requestCode, pending.requestedPermissions,
                IntArray(pending.requestedPermissions.size) { android.content.pm.PackageManager.PERMISSION_GRANTED })
            org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
            assertEquals(GalleryReadCoverage.FULL_IMAGES, results.single().getOrThrow())
            val oldAction = NativeGalleryForeground.permissionAction(owner)
            val oldIntent = GalleryPhotoPermissionIntent.create(app, oldAction)
            runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.SCREENSHOTS))
            assertFalse(NativeGalleryForeground.acceptsPermissionAction(GalleryPhotoPermissionIntent.token(oldIntent)!!))
            toDesktop(); fromDesktop()
            assertFalse(NativeGalleryForeground.acceptsPermissionAction(oldAction.token))
            assertEquals(1, results.size)
        } finally {
            runtime.close(); desktop.close(); NativeGalleryForeground.unregisterHost(host)
            activity.pause().stop().destroy(); link.channel.close(); root.deleteRecursively()
        }
    }
}
