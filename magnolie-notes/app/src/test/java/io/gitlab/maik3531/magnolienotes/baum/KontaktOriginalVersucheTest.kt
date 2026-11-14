package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.journal.AesGcmKrypto
import io.gitlab.maik3531.magnolienotes.journal.DateiSnapshotStore
import io.gitlab.maik3531.magnolienotes.journal.KontaktOriginalSicherungen
import io.gitlab.maik3531.magnolienotes.daten.Ablage
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
import java.util.UUID
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** Durable negative holds with actual encrypted pinned before-images; no apply receipt. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalVersucheTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktOriginalBindungTest.OriginalProvider
    private lateinit var scope: KontaktOriginalFreigaben
    private lateinit var binding: KontaktOriginalBindung
    private lateinit var parent: File
    private lateinit var root: File
    private var key: SecretKey? = null
    private var reads = 0
    private val request = "11111111-1111-4111-8111-111111111111"
    private val requestHash = "b".repeat(64)
    private val targetHash = "a".repeat(64)
    private fun ledger() = KontaktOriginalVersuche.fuerTest(root) { reads++; key }
    private fun grant() = scope.freigabe(binding)
    private fun reference(id: String = request): KontaktOriginalSicherungen.Sicherung {
        val store = DateiSnapshotStore(File(parent, "protection"), Ablage.json)
        val crypto = AesGcmKrypto { key ?: error("Controlled existing journal key unavailable") }
        return KontaktOriginalSicherungen(context, store, crypto, crypto, { "synthetic-epoch" }, "synthetic").sichern(grant(), id)
    }

    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        provider = KontaktOriginalBindungTest.OriginalProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        scope = KontaktOriginalFreigaben { KontaktOriginalFreigaben.Partner("peer", "pinned-native-key") }
        scope.einrichten(listOf(binding)) { it.toSet() }
        parent = java.nio.file.Files.createTempDirectory(context.cacheDir.toPath(), "contact-outcome-").toFile()
        root = File(parent, "holds")
        key = SecretKeySpec(ByteArray(32) { 71 }, "AES")
    }
    @After fun cleanup() { parent.deleteRecursively() }

    @Test fun defaultMissingLedgerAndFakeNativeWitnessesCreateNothing() {
        val store = ledger()
        assertNull(store.laden(grant())); assertFalse(root.exists()); assertEquals(0, reads)
        assertThrows(SecurityException::class.java) { KontaktOriginalVersuche.Offen(Any()).pruefen() }
        assertThrows(SecurityException::class.java) {
            store.vormerken(KontaktOriginalFreigaben.Freigabe(binding, Any()), request, requestHash, targetHash, KontaktOriginalSicherungen.Sicherung(Any()))
        }
        assertFalse(root.exists()); assertEquals(0, reads); assertEquals(0, provider.writes)
    }

    @Test fun heldOriginalSurvivesANewOwnerAndAnotherRequestCannotOverwriteIt() {
        val store = ledger(); val first = store.vormerken(grant(), request, requestHash, targetHash, reference())
        assertEquals(request, first.anfrageId()); assertEquals(targetHash, first.zielHash())
        val file = root.listFiles()!!.single { it.extension == "bin" }; val before = file.readBytes()
        val current = ledger().laden(grant())!!
        assertEquals(request, current.anfrageId())
        val next = UUID.randomUUID().toString()
        assertThrows(IllegalStateException::class.java) { ledger().vormerken(grant(), next, requestHash, targetHash, reference(next)) }
        assertArrayEquals(before, file.readBytes()); first.pruefen(); current.pruefen()
        assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }

    @Test fun aNewProviderRevisionDoesNotBypassAnUnknownAttemptOnTheSameOriginal() {
        ledger().vormerken(grant(), request, requestHash, targetHash, reference())
        provider.raw[RawContacts.VERSION] = 99L
        provider.row[ContactsContract.CommonDataKinds.StructuredName.GIVEN_NAME] = "Changed externally"
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertEquals(request, ledger().laden(grant())!!.anfrageId())
        val next = UUID.randomUUID().toString()
        assertThrows(IllegalStateException::class.java) { ledger().vormerken(grant(), next, requestHash, targetHash, reference(next)) }
        assertEquals(0, provider.writes)
    }

    @Test fun differentObservedNativeOriginalIdsHaveIndependentHoldsAndCannotSwapCiphertext() {
        val first = ledger().vormerken(grant(), request, requestHash, targetHash, reference())
        val one = root.listFiles()!!.single { it.extension == "bin" }
        provider.raw[RawContacts._ID] = 8L; provider.raw[RawContacts.CONTACT_ID] = 12L
        provider.raw[RawContacts.SOURCE_ID] = "another-native-original"
        provider.contact[Contacts._ID] = 12L; provider.contact[Contacts.LOOKUP_KEY] = "second-lookup"
        provider.row[Data.RAW_CONTACT_ID] = 8L
        binding = KontaktOriginalBindung.erfassen(context, "second-lookup")
        val next = UUID.randomUUID().toString()
        val second = ledger().vormerken(grant(), next, requestHash, targetHash, reference(next))
        assertEquals(request, first.anfrageId()); assertEquals(next, second.anfrageId())
        val two = root.listFiles()!!.single { it.extension == "bin" && it != one }
        two.writeBytes(one.readBytes())
        assertThrows(IllegalArgumentException::class.java) { ledger().laden(grant()) }
        first.pruefen(); assertEquals(0, provider.writes)
    }

    @Test fun missingHistoryKeyIsNotRegeneratedAndCannotBeReplacedByTheConsentKey() {
        val store = ledger(); val hold = store.vormerken(grant(), request, requestHash, targetHash, reference())
        val before = root.listFiles()!!.single { it.extension == "bin" }.readBytes(); val existing = key
        key = null
        assertThrows(IllegalStateException::class.java) { hold.pruefen() }
        assertThrows(IllegalStateException::class.java) { ledger().laden(grant()) }
        key = SecretKeySpec(ByteArray(32) { 1 }, "AES") // A separate synthetic consent key is not the journal key.
        assertThrows(Exception::class.java) { ledger().laden(grant()) }
        key = existing
        assertEquals(request, ledger().laden(grant())!!.anfrageId())
        assertArrayEquals(before, root.listFiles()!!.single { it.extension == "bin" }.readBytes())
        assertEquals(0, provider.writes)
    }

    @Test fun missingKeyBeforeReservationDoesNotCreateAnEmptyReplacementLedger() {
        val protection = reference()
        key = null
        assertThrows(Exception::class.java) { ledger().vormerken(grant(), request, requestHash, targetHash, protection) }
        assertFalse(root.exists()); assertNull(key); assertEquals(0, provider.writes)
    }

    @Test fun damagedHeldRecordNeverFallsBackToNoAttemptOrGetsOverwritten() {
        ledger().vormerken(grant(), request, requestHash, targetHash, reference())
        val file = root.listFiles()!!.single { it.extension == "bin" }
        val bytes = file.readBytes(); bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte(); file.writeBytes(bytes)
        assertThrows(Exception::class.java) { ledger().laden(grant()) }
        assertThrows(IllegalStateException::class.java) { ledger().vormerken(grant(), request, requestHash, targetHash, reference()) }
        assertArrayEquals(bytes, file.readBytes()); assertEquals(0, provider.writes)
    }

    @Test fun fakeOrUncorrelatedProtectionIsRejectedBeforeAnyHistoryKeyRead() {
        assertThrows(SecurityException::class.java) {
            ledger().vormerken(grant(), request, requestHash, targetHash, KontaktOriginalSicherungen.Sicherung(Any()))
        }
        val other = reference(UUID.randomUUID().toString())
        assertThrows(IllegalArgumentException::class.java) { ledger().vormerken(grant(), request, requestHash, targetHash, other) }
        assertFalse(root.exists()); assertEquals(0, reads); assertEquals(0, provider.writes)
    }

    @Test fun anotherPeerOrNativeSourceIdentityCannotBypassTheHeldPhysicalOriginal() {
        ledger().vormerken(grant(), request, requestHash, targetHash, reference())
        val file = root.listFiles()!!.single { it.extension == "bin" }; val before = file.readBytes()
        scope = KontaktOriginalFreigaben { KontaktOriginalFreigaben.Partner("different-peer", "different-key") }
        scope.einrichten(listOf(binding)) { it.toSet() }
        assertThrows(IllegalArgumentException::class.java) { ledger().laden(grant()) }
        val next = UUID.randomUUID().toString()
        val protection = reference(next)
        assertThrows(IllegalStateException::class.java) { ledger().vormerken(grant(), next, requestHash, targetHash, protection) }
        provider.raw[RawContacts.SOURCE_ID] = "changed-source-id"
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(IllegalArgumentException::class.java) { ledger().laden(grant()) }
        val changed = reference(next)
        assertThrows(IllegalStateException::class.java) { ledger().vormerken(grant(), next, requestHash, targetHash, changed) }
        assertArrayEquals(before, file.readBytes()); assertEquals(0, provider.writes)
    }

    @Test fun onlyFreshPersistedReservationCanPerformOneProtectedNativeWrite() {
        val wanted = binding.aktuell().daten.copy(notiz = "Controlled protected return")
        val target = KontaktSync.hash(wanted)
        val token = ledger().vorbereiten(grant(), request, requestHash, target, reference())
        assertEquals(0, provider.writes)
        val receipt = token.anwenden(wanted) {}
        assertEquals(target, receipt.zielHash()); assertEquals(request, receipt.anfrageId())
        assertEquals(wanted, AndroidKontakte(context).liesRaw(binding.rawContactId)!!.daten)
        assertEquals(1, provider.batchCalls)
        assertThrows(IllegalStateException::class.java) { token.anwenden(wanted) {} }
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertEquals(request, ledger().laden(grant())!!.anfrageId())
        val restoredReceipt = ledger().laden(grant())!!.bestaetigung()!!
        assertEquals(target, restoredReceipt.zielHash()); assertEquals(request, restoredReceipt.anfrageId())
        val next = UUID.randomUUID().toString()
        assertThrows(IllegalStateException::class.java) { ledger().vorbereiten(grant(), next, requestHash, target, reference(next)) }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun fabricatedApplyTokenDoesNotCallLifetimeOrTouchTheProvider() {
        val target = binding.aktuell().daten.copy(notiz = "Unapproved")
        val queries = provider.queries
        assertThrows(SecurityException::class.java) {
            KontaktOriginalVersuche.Vorbereitet(Any()).anwenden(target) { fail("Fake token reached callback") }
        }
        assertEquals(queries, provider.queries); assertFalse(root.exists()); assertEquals(0, provider.writes)
    }

    @Test fun changedTargetConsumesTheTokenButKeepsThePersistentUnknownHold() {
        val target = binding.aktuell().daten.copy(notiz = "Bound target")
        val token = ledger().vorbereiten(grant(), request, requestHash, KontaktSync.hash(target), reference())
        assertThrows(IllegalArgumentException::class.java) { token.anwenden(target.copy(notiz = "Changed target")) {} }
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(request, ledger().laden(grant())!!.anfrageId()); assertEquals(0, provider.writes)
    }

    @Test fun lostProtectionOrHistoryDuringLifetimeStopsBeforeProviderMutation() {
        val target = binding.aktuell().daten.copy(notiz = "Held on key loss")
        val token = ledger().vorbereiten(grant(), request, requestHash, KontaktSync.hash(target), reference())
        val old = key
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) { key = null } }
        key = old
        assertEquals(request, ledger().laden(grant())!!.anfrageId())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }

    @Test fun providerWriteWithoutDurableReceiptRemainsUnknownAndCannotBeReplayed() {
        var failReceipt = false
        val store = KontaktOriginalVersuche.fuerTest(root, stage = {
            if (failReceipt && it.endsWith(".bin:temporary_flushed")) throw java.io.IOException("Controlled receipt write failure")
        }) { key }
        val target = binding.aktuell().daten.copy(notiz = "Written but receipt not saved")
        val token = store.vorbereiten(grant(), request, requestHash, KontaktSync.hash(target), reference())
        provider.afterWrite = { failReceipt = true }
        assertThrows(java.io.IOException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val unknown = ledger().laden(grant())!!
        assertNull(unknown.bestaetigung()); assertEquals(request, unknown.anfrageId())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun fakeVerifiedReceiptCannotBeCreatedFromImportedMetadata() {
        assertThrows(SecurityException::class.java) { KontaktOriginalVersuche.Verifiziert(Any()).pruefen() }
        assertFalse(root.exists()); assertEquals(0, provider.writes)
    }

    @Test fun revocationAfterProviderWriteNeverProducesAReceiptOrAReplayGrant() {
        val target = binding.aktuell().daten.copy(notiz = "Changed before revoke")
        val token = ledger().vorbereiten(grant(), request, requestHash, KontaktSync.hash(target), reference())
        provider.afterWrite = { scope.widerrufen() }
        assertThrows(SecurityException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        scope.einrichten(listOf(binding)) { it.toSet() }
        assertNull(ledger().laden(grant())!!.bestaetigung())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun rejectedExactNativeReadbackRetainsTheUnknownRecordWithoutASavedResult() {
        val target = binding.aktuell().daten.copy(notiz = "Provider silently drops this")
        val token = ledger().vorbereiten(grant(), request, requestHash, KontaktSync.hash(target), reference())
        provider.dropUpdates = true
        assertThrows(IllegalArgumentException::class.java) { token.anwenden(target) {} }
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertNull(ledger().laden(grant())!!.bestaetigung())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun callerMutableTargetContainersCannotChangeTheOwnedWriteAfterAdmission() {
        val addresses = mutableListOf(KontaktAnschrift("privat", "Bound street"))
        val target = binding.aktuell().daten.copy(anschriften = addresses)
        val expectedHash = KontaktSync.hash(target)
        val token = ledger().vorbereiten(grant(), request, requestHash, expectedHash, reference())
        val receipt = token.anwenden(target) {
            addresses.clear(); addresses += KontaktAnschrift("arbeit", "Injected street")
        }
        assertEquals(expectedHash, receipt.zielHash())
        assertEquals(listOf(KontaktAnschrift("privat", "Bound street")), AndroidKontakte(context).liesRaw(7L)!!.daten.anschriften)
        assertEquals(1, provider.batchCalls)
    }
}
