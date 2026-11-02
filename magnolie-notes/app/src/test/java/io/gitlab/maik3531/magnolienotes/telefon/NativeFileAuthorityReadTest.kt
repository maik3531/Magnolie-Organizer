package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.security.*
import java.security.cert.Certificate
import java.security.spec.AlgorithmParameterSpec
import java.util.Collections
import java.util.Date
import javax.crypto.KeyGeneratorSpi
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.*
import java.nio.file.Files

internal object NativeFileAuthorityKeyFixture {
    var key: SecretKey? = SecretKeySpec(ByteArray(32) { 37 }, "AES")
    var generations = 0
}
class NativeFileAuthorityTestKeyStore : KeyStoreSpi() {
    override fun engineGetKey(alias: String?, password: CharArray?) = NativeFileAuthorityKeyFixture.key
    override fun engineLoad(stream: java.io.InputStream?, password: CharArray?) = Unit
    override fun engineStore(stream: java.io.OutputStream?, password: CharArray?) = Unit
    override fun engineAliases() = Collections.enumeration(if (NativeFileAuthorityKeyFixture.key == null) emptyList() else listOf(TelefonAblage.KEY_ALIAS))
    override fun engineContainsAlias(alias: String?) = NativeFileAuthorityKeyFixture.key != null
    override fun engineSize() = if (NativeFileAuthorityKeyFixture.key == null) 0 else 1
    override fun engineIsKeyEntry(alias: String?) = engineContainsAlias(alias)
    override fun engineIsCertificateEntry(alias: String?) = false
    override fun engineGetCertificate(alias: String?): Certificate? = null
    override fun engineGetCertificateChain(alias: String?): Array<Certificate>? = null
    override fun engineGetCertificateAlias(cert: Certificate?): String? = null
    override fun engineGetCreationDate(alias: String?) = Date(0)
    override fun engineSetKeyEntry(alias: String?, key: Key?, password: CharArray?, chain: Array<out Certificate>?) = Unit
    override fun engineSetKeyEntry(alias: String?, key: ByteArray?, chain: Array<out Certificate>?) = Unit
    override fun engineSetCertificateEntry(alias: String?, cert: Certificate?) = Unit
    override fun engineDeleteEntry(alias: String?) { NativeFileAuthorityKeyFixture.key = null }
}
class NativeFileAuthorityTestKeyGenerator : KeyGeneratorSpi() {
    override fun engineInit(random: SecureRandom?) = Unit
    override fun engineInit(keysize: Int, random: SecureRandom?) = Unit
    override fun engineInit(params: AlgorithmParameterSpec?, random: SecureRandom?) = Unit
    override fun engineGenerateKey(): SecretKey {
        NativeFileAuthorityKeyFixture.generations++
        return SecretKeySpec(ByteArray(32) { 99 }, "AES").also { NativeFileAuthorityKeyFixture.key = it }
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class NativeFileAuthorityReadTest {
    private val provider = object : Provider("AndroidKeyStore", 1.0, "Synthetic file authority keys only") {
        init {
            put("KeyStore.AndroidKeyStore", NativeFileAuthorityTestKeyStore::class.java.name)
            put("KeyGenerator.AES", NativeFileAuthorityTestKeyGenerator::class.java.name)
        }
    }
    private var previousProvider: Provider? = null
    private lateinit var storage: TelefonAblage
    private lateinit var peersFile: File
    private lateinit var root: File
    private fun field(name: String) = TelefonAblage::class.java.getDeclaredField(name).also { it.isAccessible = true }
    @Before fun setup() {
        NativeFileAuthorityKeyFixture.key = SecretKeySpec(ByteArray(32) { 37 }, "AES")
        NativeFileAuthorityKeyFixture.generations = 0
        previousProvider = Security.getProvider("AndroidKeyStore")
        Security.removeProvider("AndroidKeyStore"); Security.insertProviderAt(provider, 1)
        field("instance").set(null, null)
        root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "file-authority330-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = root
        }
        storage = TelefonAblage.get(context)
        storage.identity("Synthetic file authority phone").second.fill(0)
        storage.savePeer(TelefonPeer("receiver_fixture_01", "Fixture desktop", TelefonKrypto.b64(ByteArray(32) { 7 }),
            own_device = true, remote_own_device = true))
        peersFile = field("peersFile").get(storage) as File
    }
    @After fun cleanup() {
        field("instance").set(null, null)
        Security.removeProvider(provider.name); previousProvider?.let { Security.addProvider(it) }
        NativeFileAuthorityKeyFixture.key = SecretKeySpec(ByteArray(32) { 37 }, "AES")
        root.deleteRecursively()
    }

    @Test fun missingKeyDuringNativeFileBootstrapNeverRegeneratesThePersonalStorageKey() {
        val expected = storage.peers().peer!!
        val original = peersFile.readBytes()
        NativeFileAuthorityKeyFixture.key = null
        val failure = runCatching { storage.initializeFilePairingEpoch(expected) { true } }.exceptionOrNull()
        assertEquals("Native file authority regenerated a missing storage key", 0, NativeFileAuthorityKeyFixture.generations)
        assertTrue(failure is DeviceTransferKeyUnavailable)
        assertNull(NativeFileAuthorityKeyFixture.key)
        assertArrayEquals(original, peersFile.readBytes())
    }

    private fun sealRaw(raw: JsonObject) {
        val method = TelefonAblage::class.java.getDeclaredMethod("encryptUsingKey", ByteArray::class.java, String::class.java,
            String::class.java, SecretKey::class.java).also { it.isAccessible = true }
        peersFile.writeText(method.invoke(storage, TelefonKanonisch.bytes(raw), "peers", "v1", NativeFileAuthorityKeyFixture.key) as String)
    }
    private fun raw(): JsonObject {
        val method = TelefonAblage::class.java.getDeclaredMethod("decryptUsingKey", String::class.java, String::class.java,
            String::class.java, SecretKey::class.java).also { it.isAccessible = true }
        val clear = method.invoke(storage, peersFile.readText(), "peers", "v1", NativeFileAuthorityKeyFixture.key) as ByteArray
        return try { Json.parseToJsonElement(clear.decodeToString()).jsonObject } finally { clear.fill(0) }
    }

    @Test fun authorityReadsDoNotPersistLegacyMigrationAndBootstrapChangesOnlyTheSelectedEpochField() {
        val json = Json { encodeDefaults = true }
        val selected = TelefonPeer("receiver_fixture_01", "Keep selected settings", TelefonKrypto.b64(ByteArray(32) { 7 }),
            own_device = false, remote_own_device = false, personal_notes_sync_granted = false)
        val other = TelefonPeer("another_receiver_01", "Keep other settings", TelefonKrypto.b64(ByteArray(32) { 8 }),
            own_device = false, remote_own_device = false, saved_auto_wifi = false)
        val base = json.encodeToJsonElement(TelefonBestand.serializer(), TelefonBestand(peer = selected, other_peers = listOf(other))).jsonObject
        val originalPeer = JsonObject(base["peer"]!!.jsonObject + ("remote_sms_send_granted" to JsonPrimitive(true)))
        val original = JsonObject(base + ("peer" to originalPeer))
        sealRaw(original)
        val cipher = peersFile.readBytes()
        val observed = storage.fileAuthorityPeers()
        assertTrue(observed.peer!!.own_device) // Existing completed-pairing trust, not new file consent.
        assertEquals("", observed.peer!!.file_pairing_epoch)
        assertArrayEquals(cipher, peersFile.readBytes())
        assertEquals(original, raw())
        val saved = storage.initializeFilePairingEpoch(observed.peer!!) { true }
        assertEquals(JsonObject(original + ("peer" to JsonObject(originalPeer + ("file_pairing_epoch" to JsonPrimitive(saved.file_pairing_epoch))))), raw())
        assertEquals(original["other_peers"], raw()["other_peers"])
        assertEquals(0, NativeFileAuthorityKeyFixture.generations)
    }

    @Test fun missingOrReplacedKeysNeverRewriteCiphertextOrInvokeKeyGenerationOnReadonlyAuthority() {
        val before = peersFile.readBytes()
        NativeFileAuthorityKeyFixture.key = null
        assertThrows(DeviceTransferKeyUnavailable::class.java) { storage.fileAuthorityPeers() }
        assertThrows(DeviceTransferKeyUnavailable::class.java) { DeviceTransferProtection.fromExistingAndroidPhoneKey().seal(byteArrayOf(1), "fixture") }
        NativeFileAuthorityKeyFixture.key = SecretKeySpec(ByteArray(32) { 99 }, "AES")
        assertThrows(Exception::class.java) { storage.fileAuthorityPeers() }
        assertEquals(0, NativeFileAuthorityKeyFixture.generations)
        assertArrayEquals(before, peersFile.readBytes())
    }

    @Test fun explicitBootstrapPreservesUnknownOlderGenericStagingArtifacts() {
        val expected = storage.fileAuthorityPeers().peer!!
        val old = File(peersFile.parentFile, peersFile.name + ".new")
        old.writeBytes("Keep earlier staging evidence".toByteArray())
        val original = old.readBytes()
        assertTrue(DeviceFileControl.hash(storage.initializeFilePairingEpoch(expected) { true }.file_pairing_epoch))
        assertArrayEquals(original, old.readBytes())
        assertEquals(0, NativeFileAuthorityKeyFixture.generations)
    }

    @Test fun boundedHeldNativeStagingRefusesAnotherWriteWithoutDeletingEvidence() {
        val expected = storage.fileAuthorityPeers().peer!!
        val before = peersFile.readBytes()
        val held = (0..3).map { File(peersFile.parentFile, peersFile.name + ".file-held$it.new").apply { writeBytes("held $it".toByteArray()) } }
        assertEquals("file_pairing_native_staging_held", assertThrows(PhotoFolderScopeError::class.java) {
            storage.initializeFilePairingEpoch(expected) { true } }.code)
        assertArrayEquals(before, peersFile.readBytes())
        held.forEachIndexed { index, file -> assertEquals("held $index", file.readText()) }
    }
}
