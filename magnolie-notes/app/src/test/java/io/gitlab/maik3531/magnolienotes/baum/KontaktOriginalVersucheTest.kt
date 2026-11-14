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

/** Actual private original mappings, protected holds, native apply and receipts. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalVersucheTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktOriginalBindungTest.OriginalProvider
    private lateinit var scope: KontaktOriginalFreigaben
    private lateinit var binding: KontaktOriginalBindung
    private lateinit var parent: File
    private lateinit var root: File
    private lateinit var mapping: KontaktOriginalZuordnungen.Zuordnung
    private lateinit var basis: String
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
        parent = java.nio.file.Files.createTempDirectory(context.cacheDir.toPath(), "contact-outcome-").toFile()
        root = File(parent, "holds")
        key = SecretKeySpec(ByteArray(32) { 71 }, "AES")
        val peer = KontaktOriginalFreigaben.Partner("peer", "pinned-native-key")
        scope = KontaktOriginalFreigaben { peer }
        val maps = KontaktOriginalZuordnungen.fuerTest(File(parent, "mapping")) { key }
        val offer = KontaktOriginalFreigaben.Original("canonical-original-kept", binding)
        scope.einrichtenOriginale(listOf(binding), listOf(offer), speichern = { maps.speichern(it) }) { sources, originals ->
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet())
        }
        mapping = maps.finden(peer, "canonical-original-kept")!!
        basis = mapping.basisHash(grant())
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
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, target, reference())
        assertEquals(0, provider.writes)
        val receipt = token.anwenden(wanted) {}
        assertEquals(target, receipt.zielHash()); assertEquals(request, receipt.anfrageId())
        assertEquals("canonical-original-kept", receipt.freigabeId())
        assertEquals(basis, receipt.basisHash())
        assertEquals(wanted, AndroidKontakte(context).liesRaw(binding.rawContactId)!!.daten)
        assertEquals(1, provider.batchCalls)
        assertThrows(IllegalStateException::class.java) { token.anwenden(wanted) {} }
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertEquals(request, ledger().laden(grant())!!.anfrageId())
        val restoredReceipt = ledger().laden(grant())!!.bestaetigung()!!
        assertEquals(target, restoredReceipt.zielHash()); assertEquals(request, restoredReceipt.anfrageId())
        assertEquals("canonical-original-kept", restoredReceipt.freigabeId())
        val next = UUID.randomUUID().toString()
        assertThrows(IllegalStateException::class.java) { ledger().vorbereiten(grant(), mapping, basis, next, requestHash, target, reference(next)) }
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
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
        assertThrows(IllegalArgumentException::class.java) { token.anwenden(target.copy(notiz = "Changed target")) {} }
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(request, ledger().laden(grant())!!.anfrageId()); assertEquals(0, provider.writes)
    }

    @Test fun lostProtectionOrHistoryDuringLifetimeStopsBeforeProviderMutation() {
        val target = binding.aktuell().daten.copy(notiz = "Held on key loss")
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
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
        val token = store.vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
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
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
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
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
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
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, expectedHash, reference())
        val receipt = token.anwenden(target) {
            addresses.clear(); addresses += KontaktAnschrift("arbeit", "Injected street")
        }
        assertEquals(expectedHash, receipt.zielHash())
        assertEquals(listOf(KontaktAnschrift("privat", "Bound street")), AndroidKontakte(context).liesRaw(7L)!!.daten.anschriften)
        assertEquals(1, provider.batchCalls)
    }

    @Test fun fakeOrSourceOnlyMappingCannotMintAFreshApplyToken() {
        val target = binding.aktuell().daten.copy(notiz = "Requires an actual selected original")
        assertThrows(SecurityException::class.java) {
            ledger().vorbereiten(grant(), KontaktOriginalZuordnungen.Zuordnung(Any()), basis, request, requestHash, KontaktSync.hash(target), reference())
        }
        scope.einrichten(listOf(binding)) { it.toSet() } // A source-only decision is deliberately not a mapping approval.
        assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
        }
        assertFalse(root.exists()); assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }

    @Test fun mappingLossDuringLifetimeHoldsTheAttemptBeforeAnyProviderWrite() {
        val target = binding.aktuell().daten.copy(notiz = "Must not outlive its canonical mapping")
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
        val file = File(parent, "mapping").listFiles()!!.single { it.extension == "bin" }
        assertThrows(SecurityException::class.java) { token.anwenden(target) {
            file.writeBytes(file.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
        } }
        assertNull(ledger().laden(grant())!!.bestaetigung())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }

    @Test fun mappingLossAfterProviderWritePreventsAConfirmedReceiptAndReplay() {
        val target = binding.aktuell().daten.copy(notiz = "Written before mapping loss")
        val token = ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference())
        val file = File(parent, "mapping").listFiles()!!.single { it.extension == "bin" }
        provider.afterWrite = { file.writeBytes(file.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }) }
        assertThrows(SecurityException::class.java) { token.anwenden(target) {} }
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val held = ledger().laden(grant())!!
        assertEquals("canonical-original-kept", held.freigabeId()); assertNull(held.bestaetigung())
        assertThrows(IllegalStateException::class.java) { token.anwenden(target) {} }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun olderUnmappedHeldRecordsRemainReadableButNeverGainCanonicalMappingAuthority() {
        ledger().vormerken(grant(), request, requestHash, targetHash, reference())
        val file = root.listFiles()!!.single { it.extension == "bin" }
        val domain = "kontakt-original-versuch-v1:${file.nameWithoutExtension}"
        val cipher = io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto({ requireNotNull(key) })
        val plain = cipher.entschluesseln(file.readBytes(), domain)
        val current = kotlinx.serialization.json.Json.parseToJsonElement(plain.toString(Charsets.UTF_8)) as kotlinx.serialization.json.JsonObject
        plain.fill(0)
        val legacy = kotlinx.serialization.json.JsonObject(current - setOf("share_id", "mapping_sha256")).toString().toByteArray()
        file.writeBytes(cipher.verschluesseln(legacy, domain)); legacy.fill(0)
        val held = ledger().laden(grant())!!
        assertNull(held.freigabeId()); assertNull(held.bestaetigung()); assertEquals(request, held.anfrageId())
        val next = UUID.randomUUID().toString()
        assertThrows(IllegalStateException::class.java) {
            ledger().vorbereiten(grant(), mapping, basis, next, requestHash, targetHash, reference(next))
        }
        assertEquals(0, provider.writes)
    }

    @Test fun wrongQuotedOriginalBaselineStopsBeforeReservationAndProviderMutation() {
        val target = binding.aktuell().daten.copy(notiz = "Stale sender must not overwrite the original")
        val error = assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereiten(grant(), mapping, "0".repeat(64), request, requestHash, KontaktSync.hash(target), reference())
        }
        assertEquals("contact_original_expected_baseline_changed", error.message)
        assertFalse(root.exists()); assertEquals(0, provider.writes)
    }

    @Test fun anOlderQuotedBaselineCannotBeFilledFromANewerNativeMappingBehindTheSender() {
        val previous = basis
        val maps = KontaktOriginalZuordnungen.fuerTest(File(parent, "mapping")) { key }
        val offered = KontaktOriginalFreigaben.Original("canonical-original-kept", binding)
        scope.einrichtenOriginale(listOf(binding), listOf(offered), speichern = { maps.speichern(it) }) { sources, originals ->
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet())
        }
        mapping = maps.finden(KontaktOriginalFreigaben.Partner("peer", "pinned-native-key"), "canonical-original-kept")!!
        assertNotEquals(previous, mapping.basisHash(grant()))
        val target = binding.aktuell().daten.copy(notiz = "Old sender still quotes its previous export")
        assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereiten(grant(), mapping, previous, request, requestHash, KontaktSync.hash(target), reference())
        }
        assertFalse(root.exists()); assertEquals(0, provider.writes)
    }

    @Test fun verifiedResultKeepsTheFullUnicodeCanonicalIdThroughPrivatePersistence() {
        val id = "😀".repeat(128)
        val maps = KontaktOriginalZuordnungen.fuerTest(File(parent, "mapping")) { key }
        val offered = KontaktOriginalFreigaben.Original(id, binding)
        scope.einrichtenOriginale(listOf(binding), listOf(offered), speichern = { maps.speichern(it) }) { sources, originals ->
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet())
        }
        val actual = maps.finden(KontaktOriginalFreigaben.Partner("peer", "pinned-native-key"), id)!!
        val quote = actual.basisHash(grant())
        val target = binding.aktuell().daten.copy(notiz = "Exact canonical Unicode identity")
        val receipt = ledger().vorbereiten(grant(), actual, quote, request, requestHash, KontaktSync.hash(target), reference()).anwenden(target) {}
        assertEquals(id, receipt.freigabeId()); assertEquals(quote, receipt.basisHash())
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertEquals(id, ledger().laden(grant())!!.bestaetigung()!!.freigabeId())
        assertEquals(1, provider.batchCalls)
    }

    @Test fun unknownPhysicalOriginalAttemptBlocksNativeExportBasisRefresh() = refreshHeld(false)
    @Test fun verifiedProviderResultStillBlocksExportUntilActualDesktopSaveLifecycleCompletes() = refreshHeld(true)

    private fun refreshHeld(verified: Boolean) {
        val maps = KontaktOriginalZuordnungen.fuerTest(File(parent, "mapping")) { key }
        val oldExport = KontaktOriginalExport.erfassen(grant(), "canonical-original-kept", maps, ledger())
        val mapFile = File(parent, "mapping").listFiles()!!.single { it.extension == "bin" }
        val before = mapFile.readBytes()
        if (verified) {
            val target = binding.aktuell().daten.copy(notiz = "Native provider saved, desktop save still unconfirmed")
            ledger().vorbereiten(grant(), mapping, basis, request, requestHash, KontaktSync.hash(target), reference()).anwenden(target) {}
        } else {
            ledger().vormerken(grant(), request, requestHash, targetHash, reference())
            provider.raw[RawContacts.VERSION] = 4L
        }
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(Exception::class.java) { oldExport.lesen() }
        val error = assertThrows(IllegalStateException::class.java) {
            maps.aktualisieren(grant(), "canonical-original-kept", ledger())
        }
        assertEquals("contact_original_attempt_held", error.message)
        assertThrows(IllegalStateException::class.java) {
            KontaktOriginalExport.erfassen(grant(), "canonical-original-kept", maps, ledger())
        }
        assertArrayEquals(before, mapFile.readBytes())
        assertEquals(verified, ledger().laden(grant())!!.bestaetigung() != null)
        assertEquals(if (verified) 1 else 0, provider.batchCalls)
    }

    @Test fun plannedAdmissionRejectsOutOfScopeInvalidAndUnchangedTargetsBeforeProtectionOrHold() {
        val before = binding.aktuell().daten
        val targets = listOf(before,
            before.copy(telefone = listOf(KontaktWert("privat", "123"))),
            before.copy(emailEintraege = listOf(KontaktWert("privat", "synthetic@example.invalid"))),
            before.copy(foto = "Not in requested full-content scope"),
            before.copy(gruppen = listOf("Not selected")),
            before.copy(notiz = "x".repeat(20_001)))
        for (target in targets) {
            assertThrows(IllegalArgumentException::class.java) {
                ledger().vorbereitenGeplant(grant(), mapping, basis, request, requestHash, target) {
                    fail("Invalid target reached durable original protection"); reference()
                }
            }
            assertFalse(root.exists())
        }
        assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
    }

    @Test fun plannedAdmissionRejectsOversizedParcelBeforeProtectionOrDurableReservation() {
        val text = "x".repeat(1900)
        val target = binding.aktuell().daten.copy(anschriften = List(100) {
            KontaktAnschrift("privat", "$it$text", text, text, text, text)
        })
        val error = assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereitenGeplant(grant(), mapping, basis, request, requestHash, target) {
                fail("Oversized batch reached protection"); reference()
            }
        }
        assertEquals("contact_original_binder_budget_required", error.message)
        assertFalse(root.exists()); assertEquals(0, provider.batchCalls)
    }

    @Test fun plannedAdmissionRejectsNativeScalarAmbiguityBeforeCreatingAnyProtection() {
        provider.add(ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE,
            mapOf(ContactsContract.CommonDataKinds.Organization.COMPANY to "First"))
        provider.add(ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE,
            mapOf(ContactsContract.CommonDataKinds.Organization.COMPANY to "Second"))
        provider.raw[RawContacts.VERSION] = 4L
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        val maps = KontaktOriginalZuordnungen.fuerTest(File(parent, "mapping")) { key }
        mapping = maps.aktualisieren(grant(), "canonical-original-kept", ledger())
        basis = mapping.basisHash(grant())
        val target = binding.aktuell().daten.copy(firma = "Ambiguous native company row")
        assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereitenGeplant(grant(), mapping, basis, request, requestHash, target) {
                fail("Ambiguous scalar reached protection"); reference()
            }
        }
        assertNull(ledger().laden(grant())); assertEquals(0, provider.batchCalls)
    }

    @Test fun plannedAdmissionChecksQuotedBasisBeforeProtectionAndDoesNotReserveAfterProtectionFailure() {
        val target = binding.aktuell().daten.copy(notiz = "Planned but not protected")
        assertThrows(IllegalArgumentException::class.java) {
            ledger().vorbereitenGeplant(grant(), mapping, "0".repeat(64), request, requestHash, target) {
                fail("Old quoted basis reached protection"); reference()
            }
        }
        assertThrows(java.io.IOException::class.java) {
            ledger().vorbereitenGeplant(grant(), mapping, basis, request, requestHash, target) {
                throw java.io.IOException("Controlled actual protection failure")
            }
        }
        assertFalse(root.exists()); assertEquals(0, provider.batchCalls)
    }

    @Test fun plannedAdmissionStillRequiresActualPinnedProtectionAndVerifiesTheProviderWrite() {
        val target = binding.aktuell().daten.copy(notiz = "Planned native original return")
        var calls = 0
        val token = ledger().vorbereitenGeplant(grant(), mapping, basis, request, requestHash, target) {
            calls++; reference()
        }
        assertEquals(1, calls); assertEquals(0, provider.batchCalls)
        val receipt = token.anwenden(target) {}
        assertEquals(KontaktSync.hash(target), receipt.zielHash())
        assertEquals("canonical-original-kept", receipt.freigabeId()); assertEquals(basis, receipt.basisHash())
        assertEquals(1, provider.batchCalls)
    }
}
