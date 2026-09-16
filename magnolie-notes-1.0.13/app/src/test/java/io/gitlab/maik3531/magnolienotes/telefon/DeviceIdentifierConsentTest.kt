package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import java.security.Provider
import java.security.Security
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 29, 33], application = Application::class)
class DeviceIdentifierConsentTest {
    private lateinit var context: Context
    private lateinit var storage: TelefonAblage
    private lateinit var work: TelefonWerk
    private val provider = object : Provider("IdentifierFixture", 1.0, "Synthetic test keystore") {
        init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
    }
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        Security.insertProviderAt(provider, 1)
        storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
        storage.setPersonalSync(true, false, false, false)
        storage.savePeer(TelefonPeer(UUID.randomUUID().toString(), "Fixture", TelefonKrypto.b64(ByteArray(32)),
            own_device = true, remote_own_device = true, remote_device_status_available = true, remote_device_status_versions = listOf(1, 2, 3, 4)))
        work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
            .apply { isAccessible = true }.newInstance(context, storage)
    }
    @After fun cleanup() { work.serviceStopped(); Security.removeProvider(provider.name) }

    @Test fun permissionGrantDenyAndRevocationAreExplicit() {
        assertFalse(storage.peers().peer!!.identifier_sharing_enabled)
        val denied = work.beginIdentifierPermission()!!
        work.completeIdentifierPermission(denied, false)
        assertFalse(storage.peers().peer!!.identifier_sharing_enabled)
        val granted = work.beginIdentifierPermission()!!
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_PHONE_NUMBERS)
        work.completeIdentifierPermission(granted, true)
        assertTrue(storage.peers().peer!!.identifier_sharing_enabled)
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.READ_PHONE_NUMBERS)
        work.runtimePermissionsChanged()
        assertFalse(storage.peers().peer!!.identifier_sharing_enabled)
    }

    @Test fun delayedPermissionCannotEnableDifferentPeerOrRevokedConsent() {
        val token = work.beginIdentifierPermission()!!
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_PHONE_NUMBERS)
        storage.savePeer(storage.peers().peer!!.copy(static_public = TelefonKrypto.b64(ByteArray(32) { 1 })))
        work.completeIdentifierPermission(token, true)
        assertFalse(storage.peers().peer!!.identifier_sharing_enabled)
        val revoked = work.beginIdentifierPermission()!!
        work.setIdentifierSharingEnabled(false)
        work.completeIdentifierPermission(revoked, true)
        assertFalse(storage.peers().peer!!.identifier_sharing_enabled)
    }

    @Test fun falseRequestHasOnlyNotSharedFieldsAndNeverQueuesResponse() {
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_PHONE_NUMBERS)
        work.setIdentifierSharingEnabled(true)
        val body = buildJsonObject { put("request_id", UUID.randomUUID().toString()); put("version", 4); put("include_identifiers", false) }
        val message = TelefonNachrichten.message("device_status.request", body, 60_000)
        val replies = mutableListOf<JsonObject>()
        val method = TelefonWerk::class.java.getDeclaredMethod("receiveMessage", TelefonPeer::class.java, JsonObject::class.java, kotlin.jvm.functions.Function1::class.java)
            .apply { isAccessible = true }
        method.invoke(work, storage.peers().peer, message, { value: JsonObject -> replies.add(value); Unit })
        val report = replies.single { it["kind"] == JsonPrimitive("device_status.report") }["body"]!!.jsonObject
        assertTrue(report["identifiers"]!!.jsonObject.values.all { it.jsonObject.string("status") == "not_shared" && it.jsonObject.string("value").isEmpty() })
        val database = TelefonDatenbank(context).readableDatabase
        database.rawQuery("SELECT COUNT(*) FROM outbox WHERE kind='device_status.report' OR kind='device_status.request'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
        replies.clear(); method.invoke(work, storage.peers().peer, message, { value: JsonObject -> replies.add(value); Unit })
        assertFalse(replies.any { it["kind"] == JsonPrimitive("device_status.report") })
    }
}
