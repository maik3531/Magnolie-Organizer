package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.RawContacts
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec
import org.robolectric.shadows.ShadowContentResolver

/** Native combined setup, encrypted private map and source store; no UI/device. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalZuordnungenTest {
    private lateinit var context: Context
    private lateinit var parent: File
    private lateinit var mapRoot: File
    private lateinit var provider: KontaktOriginalBindungTest.OriginalProvider
    private lateinit var binding: KontaktOriginalBindung
    private lateinit var sourceStore: KontaktOriginalDauerfreigaben
    private lateinit var scope: KontaktOriginalFreigaben
    private var journalKey: SecretKey? = null
    private var consentKey: SecretKey? = null
    private var reads = 0
    private var rotations = 0
    private var peer = KontaktOriginalFreigaben.Partner("synthetic-peer", "native-pinned-key")
    private var peerHook: (() -> Unit)? = null
    private val share = "canonical-share-kept-verbatim"
    private fun maps() = KontaktOriginalZuordnungen.fuerTest(mapRoot) { reads++; journalKey }
    private fun freshScope() = KontaktOriginalFreigaben(sourceStore) {
        peerHook?.also { peerHook = null }?.invoke()
        peer
    }
    private fun candidate(id: String = share, bound: KontaktOriginalBindung = binding) = KontaktOriginalFreigaben.Original(id, bound)
    private fun approve(id: String = share) {
        val offered = candidate(id)
        assertTrue(scope.einrichtenOriginale(listOf(binding), listOf(offered), speichern = { maps().speichern(it) }) { sources, originals ->
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet())
        })
    }
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        provider = KontaktOriginalBindungTest.OriginalProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        parent = java.nio.file.Files.createTempDirectory(context.cacheDir.toPath(), "contact-native-mapping-").toFile()
        mapRoot = File(parent, "maps")
        journalKey = SecretKeySpec(ByteArray(32) { 79 }, "AES")
        sourceStore = KontaktOriginalDauerfreigaben(File(parent, "consent"), KontaktOriginalSchutz.fuerTest(
            { consentKey }, { rotations++; consentKey = SecretKeySpec(ByteArray(32) { rotations.toByte() }, "AES") }, { consentKey = null }))
        scope = freshScope()
    }
    @After fun cleanup() { parent.deleteRecursively() }

    @Test fun absentOrForgedMappingCreatesNoFilesKeysOrNativePermission() {
        val queries = provider.queries
        assertNull(maps().finden(peer, share)); assertFalse(mapRoot.exists()); assertEquals(0, reads)
        assertThrows(SecurityException::class.java) { maps().speichern(KontaktOriginalFreigaben.Entscheidung(Any())) }
        assertThrows(SecurityException::class.java) { KontaktOriginalZuordnungen.Zuordnung(Any()).freigabeId() }
        assertEquals(queries, provider.queries); assertEquals(0, rotations); assertEquals(0, provider.writes)
    }

    @Test fun combinedNativeDecisionPreservesCanonicalIdAndFreshOwnerCanVerifyTheExactOriginal() {
        approve()
        val proof = maps().finden(peer, share)!!
        assertEquals(share, proof.freigabeId()); proof.pruefen(scope.freigabe(binding))
        val exportedBasis = proof.basisHash(scope.freigabe(binding))
        val encrypted = mapRoot.listFiles()!!.single { it.extension == "bin" }.readBytes()
        assertFalse(encrypted.toString(Charsets.ISO_8859_1).contains(share))
        assertFalse(encrypted.toString(Charsets.ISO_8859_1).contains("original-server-id"))
        val reopenedSource = KontaktOriginalDauerfreigaben(File(parent, "consent"), KontaktOriginalSchutz.fuerTest(
            { consentKey }, { fail("Restore may not rotate consent keys") }, { fail("Restore may not revoke") }))
        val fresh = KontaktOriginalFreigaben(reopenedSource) { peer }
        assertTrue(fresh.wiederherstellen(reopenedSource.laden()!!))
        val actual = KontaktOriginalBindung.erfassen(context, "native-lookup")
        maps().finden(peer, share)!!.pruefen(fresh.freigabe(actual))
        assertEquals(exportedBasis, maps().finden(peer, share)!!.basisHash(fresh.freigabe(actual)))
        assertEquals(1, rotations); assertEquals(0, provider.writes)
    }

    @Test fun sourceOnlyApprovalDoesNotBlessPortableOrUnselectedOriginalMappings() {
        scope.einrichten(listOf(binding), speichern = { decision -> assertTrue(maps().speichern(decision).isEmpty()) }) { it.toSet() }
        scope.freigabe(binding).pruefen()
        assertNull(maps().finden(peer, share)); assertFalse(mapRoot.exists()); assertEquals(0, reads)
        assertEquals(0, provider.writes)
    }

    @Test fun onlyOfferedExactOriginalAndItsChosenSourceCanBeSelected() {
        val offer = candidate()
        for (mode in listOf("clone", "no-source")) {
            assertThrows(IllegalArgumentException::class.java) {
                scope.einrichtenOriginale(listOf(binding), listOf(offer), speichern = { fail("Invalid mapping reached storage") }) { sources, _ ->
                    KontaktOriginalFreigaben.Auswahl(if (mode == "no-source") emptySet() else sources.toSet(),
                        setOf(if (mode == "clone") candidate() else offer))
                }
            }
        }
        val otherCapture = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(IllegalArgumentException::class.java) {
            scope.einrichtenOriginale(listOf(binding), listOf(candidate(bound = otherCapture))) { _, _ ->
                fail("A nonoffered native observation reached the chooser"); null
            }
        }
        assertFalse(mapRoot.exists()); assertEquals(0, rotations); assertEquals(0, provider.writes)
    }

    @Test fun cancelPreservesTheOldAcceptedSourceAndMappingWithoutASecondPublication() {
        approve()
        val file = mapRoot.listFiles()!!.single { it.extension == "bin" }; val previous = file.readBytes()
        val grant = scope.freigabe(binding)
        assertFalse(scope.einrichtenOriginale(listOf(binding), listOf(candidate()), speichern = { fail("Cancel persisted mappings") }) { _, _ -> null })
        assertArrayEquals(previous, file.readBytes()); maps().finden(peer, share)!!.pruefen(grant)
        assertEquals(1, rotations); assertEquals(0, provider.writes)
    }

    @Test fun canonicalShareCannotBeRetargetedToAnotherNativeSourceIdentity() {
        approve()
        val file = mapRoot.listFiles()!!.single { it.extension == "bin" }; val previous = file.readBytes()
        provider.raw[RawContacts.SOURCE_ID] = "different-native-source"
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(IllegalArgumentException::class.java) { approve() }
        assertArrayEquals(previous, file.readBytes()); assertEquals(1, rotations)
        assertFalse(scope.gewuenscht); assertEquals(0, provider.writes)
    }

    @Test fun missingHistoryKeyDoesNotRegenerateItOrEraseAcceptedSourceIntent() {
        approve(); val existing = journalKey
        val file = mapRoot.listFiles()!!.single { it.extension == "bin" }; val previous = file.readBytes()
        journalKey = null
        assertThrows(IllegalStateException::class.java) { maps().finden(peer, share) }
        scope.freigabe(binding).pruefen()
        assertArrayEquals(previous, file.readBytes()); assertEquals(1, rotations)
        journalKey = existing
        maps().finden(peer, share)!!.pruefen(scope.freigabe(binding))
        assertEquals(0, provider.writes)
    }

    @Test fun missingKeyDuringCombinedSetupCannotPublishSourcePermissionOrMappingDirectories() {
        journalKey = null
        assertThrows(IllegalStateException::class.java) { approve() }
        assertFalse(mapRoot.exists()); assertNull(sourceStore.laden()); assertEquals(0, rotations)
        assertFalse(scope.gewuenscht); assertEquals(0, provider.writes)
    }

    @Test fun partialMappingDependencyCannotBeUsedWithAnOlderAcceptedSourceDecision() {
        scope.einrichten(listOf(binding)) { it.toSet() } // Old accepted source intent has NO exact mapping authority.
        val oldSource = File(parent, "consent/approval.bin").readBytes()
        val offer = candidate()
        assertThrows(java.io.IOException::class.java) {
            scope.einrichtenOriginale(listOf(binding), listOf(offer), speichern = {
                maps().speichern(it)
                throw java.io.IOException("Controlled setup stops before owned source publication")
            }) { sources, originals -> KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet()) }
        }
        assertArrayEquals(oldSource, File(parent, "consent/approval.bin").readBytes())
        val fresh = freshScope(); fresh.wiederherstellen(sourceStore.laden()!!)
        assertThrows(IllegalArgumentException::class.java) { maps().finden(peer, share)!!.pruefen(fresh.freigabe(binding)) }
        assertEquals(1, rotations); assertEquals(0, provider.writes)
    }

    @Test fun changedNativeRevisionAndAnotherPeerDoNotAcquireTheStoredMapping() {
        approve()
        assertThrows(IllegalArgumentException::class.java) { maps().finden(peer.copy(schluessel = "different-key"), share) }
        provider.raw[RawContacts.VERSION] = 99L
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        assertThrows(IllegalArgumentException::class.java) { maps().finden(peer, share)!!.pruefen(scope.freigabe(binding)) }
        assertEquals(0, provider.writes)
    }

    @Test fun returnedMutableSelectionCannotAddAnOriginalAfterTheNativeDecision() {
        val offer = candidate(); val injected = candidate("not-offered")
        val selected = mutableSetOf(offer)
        scope.einrichtenOriginale(listOf(binding), listOf(offer), speichern = { maps().speichern(it) }) { sources, _ ->
            peerHook = { selected.clear(); selected += injected }
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), selected)
        }
        assertTrue(injected in selected)
        maps().finden(peer, share)!!.pruefen(scope.freigabe(binding))
        assertNull(maps().finden(peer, "not-offered")); assertEquals(0, provider.writes)
    }

    @Test fun mappingTamperDuringTheFinalNativeObservationCannotReturnAnOldValidWitness() {
        approve()
        val proof = maps().finden(peer, share)!!; val grant = scope.freigabe(binding)
        val before = provider.queries
        proof.pruefen(grant)
        val queryCount = provider.queries - before
        assertTrue(queryCount > 0)
        val file = mapRoot.listFiles()!!.single { it.extension == "bin" }
        val old = file.readBytes(); var queries = 0
        lateinit var hook: () -> Unit
        hook = {
            queries++
            if (queries == queryCount) file.writeBytes(old.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
            else provider.onQuery = hook
        }
        provider.onQuery = hook
        assertThrows(Exception::class.java) { proof.pruefen(grant) }
        assertEquals(queryCount, queries)
        assertEquals(0, provider.writes)
    }

    @Test fun mappingContinuityProofIsNotRetargetableOrConstructibleFromImportedMetadata() {
        approve(); val grant = scope.freigabe(binding)
        val proof = maps().finden(peer, share)!!.festhalten(grant)
        proof.pruefen(grant)
        assertThrows(SecurityException::class.java) { proof.pruefen(scope.freigabe(binding)) }
        val queries = provider.queries
        assertThrows(SecurityException::class.java) { KontaktOriginalZuordnungen.Fortbestand(Any()).pruefen(grant) }
        assertEquals(queries, provider.queries); assertEquals(0, provider.writes)
    }

    @Test fun canonicalShareLimitUsesTheExistingProtocolUnicodeCodePointCountWithoutRenaming() {
        val id = "😀".repeat(128)
        approve(id)
        assertEquals(id, maps().finden(peer, id)!!.freigabeId())
        maps().finden(peer, id)!!.pruefen(scope.freigabe(binding))
        assertThrows(IllegalArgumentException::class.java) { approve(id + "a") }
        assertEquals(1, rotations); assertEquals(0, provider.writes)
    }
}
