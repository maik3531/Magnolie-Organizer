package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.CommonDataKinds.Photo
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.journal.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalSicherungenTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktOriginalBindungTest.OriginalProvider
    private lateinit var binding: KontaktOriginalBindung
    private lateinit var scope: KontaktOriginalFreigaben
    private lateinit var dir: File
    private lateinit var store: DateiSnapshotStore
    private var key: SecretKey? = null
    private var writes = 0
    private var reads = 0
    private val mutation = "11111111-1111-4111-8111-111111111111"
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        provider = KontaktOriginalBindungTest.OriginalProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        scope = KontaktOriginalFreigaben { KontaktOriginalFreigaben.Partner("peer", "native-pinned-key") }
        scope.einrichten(listOf(binding)) { it.toSet() }
        dir = java.nio.file.Files.createTempDirectory(context.cacheDir.toPath(), "contact-before-image-").toFile()
        store = DateiSnapshotStore(dir, Ablage.json)
        key = SecretKeySpec(ByteArray(32) { 73 }, "AES")
    }
    @After fun cleanup() { dir.deleteRecursively() }
    private fun grant() = scope.freigabe(binding)
    private fun producer(ctx: Context = context, snapshotStore: DateiSnapshotStore = store, before: () -> Unit = {}) =
        KontaktOriginalSicherungen(ctx, snapshotStore, AesGcmKrypto { writes++; key ?: error("Existing test journal key unavailable") },
            AesGcmKrypto { reads++; key ?: error("Existing test journal key unavailable") }, { "synthetic-epoch" }, "synthetic", before)

    @Test fun actualEncryptedPinnedBeforeImageMatchesTheBoundOriginalAndSurvivesRetentionSelection() {
        val before = binding.aktuell()
        val proof = producer().sichern(grant(), mutation)
        val manifest = proof.manifest(binding)
        assertTrue(manifest.pinned); assertEquals("android-system-contacts", manifest.domain)
        val (saved, encrypted) = store.read(manifest.uuid); assertEquals(manifest, saved)
        assertFalse(encrypted.toString(Charsets.ISO_8859_1).contains("Synthetic"))
        val clear = AesGcmKrypto { requireNotNull(key) }.decrypt(encrypted, manifest.uuid.toByteArray())
        val content = Ablage.json.decodeFromString(KontaktNutzlast.serializer(), clear.toString(Charsets.UTF_8)); clear.fill(0)
        assertEquals(mutation, content.mutationId)
        val original = content.contacts.single()
        assertEquals(before.rawContactId, original.rawContactId); assertEquals(before.lookupKey, original.lookupKey)
        assertEquals(before.daten, original.portable); assertEquals(binding.sourceId, original.sourceId)
        assertEquals(KontaktSync.hash(before.daten), original.beforeHash)
        val later = JournalRegeln.manifest("manual", "synthetic-unrelated", "test", byteArrayOf(1), "Test", "test",
            now = System.currentTimeMillis() + 1000)
        assertTrue(manifest.uuid in JournalRegeln.behalten(listOf(manifest, later), System.currentTimeMillis(), 1))
        assertEquals(0, provider.writes); assertEquals(1, writes)
    }

    @Test fun fakeNativeGrantAndRetargetedProtectionCannotBecomeABeforeImageWitness() {
        assertThrows(SecurityException::class.java) { producer().sichern(KontaktOriginalFreigaben.Freigabe(binding, Any()), mutation) }
        assertTrue(store.list().isEmpty()); assertEquals(0, writes)
        val proof = producer().sichern(grant(), mutation)
        val otherPreparation = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(SecurityException::class.java) { proof.pruefen(otherPreparation) }
        proof.pruefen(binding); assertEquals(0, provider.writes)
    }

    @Test fun historicalProtectionRemainsReadableAfterRevocationButCannotSupplySourcePermission() {
        val oldGrant = grant(); val proof = producer().sichern(oldGrant, mutation)
        scope.widerrufen()
        proof.pruefen(binding)
        assertThrows(SecurityException::class.java) { oldGrant.pruefen() }
        assertEquals(0, provider.writes)
    }

    @Test fun missingReadKeyDoesNotRewriteOrRegenerateProtectedHistory() {
        val proof = producer().sichern(grant(), mutation); val manifest = proof.manifest(binding)
        val file = File(dir, "${manifest.uuid}.bin"); val bytes = file.readBytes(); val existing = key
        key = null
        assertThrows(IllegalStateException::class.java) { proof.pruefen(binding) }
        assertArrayEquals(bytes, file.readBytes()); assertEquals(1, writes)
        key = existing; proof.pruefen(binding)
    }

    @Test fun alteredManifestIsRejectedBeforeDecryptingAndTamperedPayloadCannotVerify() {
        val proof = producer().sichern(grant(), mutation); val manifest = proof.manifest(binding)
        val file = File(dir, "${manifest.uuid}.json"); val before = file.readBytes(); val readCount = reads
        file.writeText(Ablage.json.encodeToString(SnapshotManifest.serializer(), manifest.copy(domain = "android-app-data")))
        assertThrows(IllegalArgumentException::class.java) { proof.pruefen(binding) }
        assertEquals(readCount, reads)
        file.writeBytes(before)
        val payload = File(dir, "${manifest.uuid}.bin"); val bytes = payload.readBytes()
        bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte(); payload.writeBytes(bytes)
        assertThrows(Exception::class.java) { proof.pruefen(binding) }
        assertEquals(0, provider.writes)
    }

    @Test fun unsupportedApplicationBlobIsHeldRatherThanCapturedWithLossyRestoreTyping() {
        provider.add("vnd.synthetic.unmodeled", mapOf(Data.DATA1 to byteArrayOf(1, 2, 3)))
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val failure = assertThrows(IllegalArgumentException::class.java) { producer().sichern(grant(), mutation) }
        assertEquals("contact_original_unmodeled_blob_protection_required", failure.message)
        assertTrue(store.list().isEmpty()); assertEquals(0, writes); assertEquals(0, provider.writes)
    }

    @Test fun nativePhotoBlobUsesTheExistingLosslessPhotoRestoreEncoding() {
        val photo = byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 0)
        provider.add(Photo.CONTENT_ITEM_TYPE, mapOf(Photo.PHOTO to photo))
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val proof = producer().sichern(grant(), mutation); val manifest = proof.manifest(binding)
        val (_, encrypted) = store.read(manifest.uuid)
        val clear = AesGcmKrypto { requireNotNull(key) }.decrypt(encrypted, manifest.uuid.toByteArray())
        val content = Ablage.json.decodeFromString(KontaktNutzlast.serializer(), clear.toString(Charsets.UTF_8)); clear.fill(0)
        assertArrayEquals(photo, java.util.Base64.getDecoder().decode(content.contacts.single().rows.single {
            it.mime == Photo.CONTENT_ITEM_TYPE }.data[14]))
        assertEquals(0, provider.writes)
    }

    @Test fun missingNativeJournalRowsAndUnrestorableParcelBudgetsStopBeforeEncryption() {
        provider.nullJournalRows = true
        assertThrows(IllegalArgumentException::class.java) { producer().sichern(grant(), mutation) }
        provider.nullJournalRows = false
        provider.add("vnd.synthetic.unmodeled", mapOf(Data.DATA1 to "Keep", Data.SYNC1 to "x".repeat(400000)))
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val failure = assertThrows(IllegalArgumentException::class.java) { producer().sichern(grant(), mutation) }
        assertEquals("contact_original_restore_budget_required", failure.message)
        assertTrue(store.list().isEmpty()); assertEquals(0, writes); assertEquals(0, provider.writes)
    }

    @Test fun sourceChangeOrRevocationAtThePreWriteHookStopsBeforeJournalAndProviderMutation() {
        assertThrows(SecurityException::class.java) { producer(before = { scope.widerrufen() }).sichern(grant(), mutation) }
        assertTrue(store.list().isEmpty()); assertEquals(0, writes)
        scope.einrichten(listOf(binding)) { it.toSet() }
        assertThrows(IllegalArgumentException::class.java) {
            producer(before = { provider.raw[RawContacts.VERSION] = 99L }).sichern(grant(), mutation)
        }
        assertTrue(store.list().isEmpty()); assertEquals(0, writes); assertEquals(0, provider.writes)
    }

    @Test fun failedExistingSnapshotStoreCommitReturnsNoProtectionWitnessAndNoProviderMutation() {
        val failing = DateiSnapshotStore(File(dir, "failed"), Ablage.json) {
            if (it == SnapshotCommitSchritt.PAYLOAD_BEREIT) throw java.io.IOException("Controlled original protection failure")
        }
        assertThrows(java.io.IOException::class.java) { producer(snapshotStore = failing).sichern(grant(), mutation) }
        assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }
}
