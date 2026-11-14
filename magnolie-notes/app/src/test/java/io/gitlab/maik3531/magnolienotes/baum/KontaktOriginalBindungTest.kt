package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.*
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.provider.ContactsContract
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.ProviderStatus
import android.provider.ContactsContract.CommonDataKinds.StructuredName
import android.provider.ContactsContract.CommonDataKinds.StructuredPostal
import android.provider.ContactsContract.CommonDataKinds.Organization
import android.provider.ContactsContract.CommonDataKinds.Event
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.CommonDataKinds.Email
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalBindungTest {
    private lateinit var context: Context
    private lateinit var provider: OriginalProvider
    private lateinit var approvals: KontaktOriginalFreigaben
    private var peer: KontaktOriginalFreigaben.Partner? = null
    private var decisions = 0
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        provider = OriginalProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        peer = KontaktOriginalFreigaben.Partner("native-peer", "native-pinned-public-key")
        approvals = KontaktOriginalFreigaben { peer }
        decisions = 0
    }
    private fun capture() = KontaktOriginalBindung.erfassen(context, "native-lookup")
    private fun writer(binding: KontaktOriginalBindung): KontaktOriginalInhalt {
        if (!approvals.gewuenscht) approvals.einrichten(listOf(binding)) { choices -> decisions++; choices.toSet() }
        return KontaktOriginalInhalt(approvals.freigabe(binding))
    }

    @Test fun exactNativeOriginalIsObservedWithoutAnyProviderMutationOrConsent() {
        val binding = capture()
        assertEquals(7L, binding.rawContactId); assertEquals("native-lookup", binding.lookupKey)
        assertEquals(123456L, binding.datenbankErstellt)
        assertEquals("original-server-id", binding.sourceId)
        assertEquals(KontaktOriginalBindung.Quelle("synthetic@example.invalid", "synthetic.provider", "native-set"), binding.quelle)
        assertEquals("Synthetic", binding.aktuell().daten.vorname)
        context.contentResolver.applyBatch(ContactsContract.AUTHORITY, ArrayList(binding.pruefungen()))
        assertEquals(0, provider.writes)
    }

    @Test fun missingReadOrWritePermissionStopsBeforeAnyNativeObservation() {
        for (permission in listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)) {
            Shadows.shadowOf(context as Application).denyPermissions(permission)
            val before = provider.queries
            assertThrows(SecurityException::class.java) { capture() }
            assertEquals(before, provider.queries)
            Shadows.shadowOf(context as Application).grantPermissions(permission)
        }
        val binding = capture()
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.WRITE_CONTACTS)
        assertThrows(SecurityException::class.java) { binding.pruefungen() }
        assertEquals(0, provider.writes)
    }

    @Test fun ambiguousAggregatesMissingRevisionsAndReadOnlyOrDeletedOriginalsStayHeld() {
        val cases: List<() -> Unit> = listOf(
            { provider.aggregate = true }, { provider.raw[RawContacts.VERSION] = null },
            { provider.raw[RawContacts.RAW_CONTACT_IS_READ_ONLY] = 1 },
            { provider.raw[RawContacts.RAW_CONTACT_IS_READ_ONLY] = null },
            { provider.raw[RawContacts.RAW_CONTACT_IS_READ_ONLY] = 0.5 },
            { provider.raw[RawContacts.DELETED] = "0" },
            { provider.raw[RawContacts.DELETED] = 1 },
            { provider.row[Data.IS_READ_ONLY] = 1 }, { provider.row[Data.IS_READ_ONLY] = null },
            { provider.row[Data.IS_READ_ONLY] = 0.5 },
            { provider.row[Data.RAW_CONTACT_ID] = 999L })
        for (change in cases) {
            setup(); change()
            assertThrows(Exception::class.java) { capture() }
            assertEquals(0, provider.writes)
        }
    }

    @Test fun capturedAccountSourceLookupRevisionAndContentCannotBeRetargeted() {
        val cases: List<() -> Unit> = listOf(
            { provider.raw[RawContacts.ACCOUNT_NAME] = "other@example.invalid" },
            { provider.raw[RawContacts.ACCOUNT_TYPE] = "other.provider" },
            { provider.raw[RawContacts.DATA_SET] = "other-set" },
            { provider.raw[RawContacts.SOURCE_ID] = "other-server-id" },
            { provider.raw[RawContacts.VERSION] = 42L },
            { provider.raw[RawContacts.CONTACT_ID] = 99L },
            { provider.status[ProviderStatus.DATABASE_CREATION_TIMESTAMP] = 654321L },
            { provider.contact[Contacts.LOOKUP_KEY] = "other-lookup" },
            { provider.row[StructuredName.GIVEN_NAME] = "External edit" })
        for (change in cases) {
            setup(); val binding = capture(); change()
            assertThrows(Exception::class.java) { binding.aktuell() }
            assertEquals(0, provider.writes)
        }
    }

    @Test fun atomicAssertionsCatchIdentityRevisionRightsAndLookupChangesAfterFinalPreflight() {
        val cases: List<() -> Unit> = listOf(
            { provider.raw[RawContacts.VERSION] = 42L },
            { provider.raw[RawContacts.ACCOUNT_NAME] = "other@example.invalid" },
            { provider.raw[RawContacts.SOURCE_ID] = "other-server-id" },
            { provider.raw[RawContacts.RAW_CONTACT_IS_READ_ONLY] = 1 },
            { provider.row[Data.IS_READ_ONLY] = 1 },
            { provider.contact[Contacts.LOOKUP_KEY] = "rebound-lookup" },
            { provider.status[ProviderStatus.DATABASE_CREATION_TIMESTAMP] = 654321L },
            { provider.aggregate = true })
        for (change in cases) {
            setup(); val binding = capture(); val operations = ArrayList(binding.pruefungen())
            provider.beforeBatch = change
            assertThrows(OperationApplicationException::class.java) {
                context.contentResolver.applyBatch(ContactsContract.AUTHORITY, operations)
            }
            assertEquals(0, provider.writes)
        }
    }

    @Test fun localNullAccountIdentityIsNotCoalescedWithAChangedEmptyStringIdentity() {
        provider.raw[RawContacts.ACCOUNT_NAME] = null; provider.raw[RawContacts.ACCOUNT_TYPE] = null
        provider.raw[RawContacts.DATA_SET] = null; provider.raw[RawContacts.SOURCE_ID] = null
        val binding = capture()
        assertEquals(KontaktOriginalBindung.Quelle(null, null, null), binding.quelle)
        provider.raw[RawContacts.ACCOUNT_NAME] = ""
        assertThrows(IllegalArgumentException::class.java) { binding.aktuell() }
    }

    @Test fun permissionLossDuringObservationCannotMintANativeBinding() {
        provider.onQuery = { Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.WRITE_CONTACTS) }
        assertThrows(SecurityException::class.java) { capture() }
        assertEquals(0, provider.writes)
    }

    @Test fun sourceIdentityChangeDuringTheLastNativeRereadIsHeld() {
        provider.beforeRawReread = { provider.raw[RawContacts.SOURCE_ID] = "changed-during-observation" }
        assertThrows(IllegalArgumentException::class.java) { capture() }
        assertEquals(0, provider.writes)
    }

    @Test fun profilesAndMissingNativeOriginalsNeverUseAnotherContactAsFallback() {
        provider.contact[Contacts.LOOKUP_KEY] = "another-original"
        assertThrows(IllegalArgumentException::class.java) { capture() }
        setup()
        provider.contact[Contacts._ID] = Long.MAX_VALUE
        provider.raw[RawContacts.CONTACT_ID] = Long.MAX_VALUE
        assertThrows(IllegalArgumentException::class.java) { capture() }
        assertEquals(0, provider.writes)
    }

    @Test fun busyMissingOrMalformedProviderGenerationCannotUseRawIdReuseAsOriginalIdentity() {
        for (value in listOf(null, 0L, -1L, "123456", 0.5)) {
            setup(); provider.status[ProviderStatus.DATABASE_CREATION_TIMESTAMP] = value
            assertThrows(IllegalArgumentException::class.java) { capture() }
        }
        setup(); provider.status[ProviderStatus.STATUS] = ProviderStatus.STATUS_BUSY
        assertThrows(IllegalArgumentException::class.java) { capture() }
        assertEquals(0, provider.writes)
    }

    @Test fun fullNamesScalarsAndPostalAreOneProtectedNativeTransactionWithExactReadback() {
        val postal = provider.postal("Old street", StructuredPostal.TYPE_CUSTOM)
        postal[StructuredPostal.LABEL] = "Keep custom label"; postal[StructuredPostal.POBOX] = "Keep PO box"
        postal[Data.SYNC1] = "Keep native metadata"; postal[Data.IS_PRIMARY] = 1
        val oldPostalId = postal[Data._ID]
        val phone = provider.add(Phone.CONTENT_ITEM_TYPE, mapOf(Phone.NUMBER to "123", Phone.TYPE to Phone.TYPE_CUSTOM, Phone.LABEL to "Native phone label"))
        val email = provider.add(Email.CONTENT_ITEM_TYPE, mapOf(Email.ADDRESS to "synthetic@example.invalid", Email.TYPE to Email.TYPE_WORK,
            Email.DISPLAY_NAME to "Native display"))
        val untouched = listOf(phone.toMap(), email.toMap())
        val binding = capture(); val before = binding.aktuell()
        val wanted = before.daten.copy(vorname = "Maria", nachname = "Cruz", anzeigename = "Independent display",
            vcardName = listOf("N:Cruz;Maria;Elena;Dr.;Jr.", "FN:Independent display"), firma = "Synthetic company",
            notiz = "Synthetic note\nSecond line", geburtstag = "--02-29", jubilaeum = "2020-03-04",
            anschriften = listOf(KontaktAnschrift("sonstige", "New street", "00000", "New town", "Region", "Country")))
        var protected = 0
        val actual = writer(binding).uebernehmen(wanted, {}, {
            assertEquals(before, it); assertEquals(0, provider.writes); protected++
        })
        assertEquals(wanted, actual.daten); assertEquals(1, protected); assertEquals(1, provider.batchCalls)
        assertEquals(7L, actual.rawContactId); assertEquals("native-lookup", actual.lookupKey)
        assertEquals(oldPostalId, postal[Data._ID]); assertEquals("New street", postal[StructuredPostal.STREET])
        assertEquals("Keep custom label", postal[StructuredPostal.LABEL]); assertEquals("Keep PO box", postal[StructuredPostal.POBOX])
        assertEquals("Keep native metadata", postal[Data.SYNC1]); assertEquals(1, postal[Data.IS_PRIMARY])
        assertNull(postal[StructuredPostal.FORMATTED_ADDRESS])
        assertEquals(untouched, listOf(phone.toMap(), email.toMap()))
    }

    @Test fun scalarOnlyWritePreservesUnrelatedRowsAndAmbiguousUneditedPostalMetadata() {
        val company = provider.add(Organization.CONTENT_ITEM_TYPE, mapOf(Organization.COMPANY to "Old company", Organization.TITLE to "Keep title"))
        provider.add(Event.CONTENT_ITEM_TYPE, mapOf(Event.TYPE to Event.TYPE_OTHER, Event.START_DATE to "2000-01-01"))
        provider.add("vnd.synthetic.unmodeled", mapOf(Data.DATA1 to "Keep application row"))
        provider.postal("Same street", StructuredPostal.TYPE_HOME)
        provider.postal("Same street", StructuredPostal.TYPE_HOME)[StructuredPostal.LABEL] = "Native duplicate label"
        val binding = capture(); val old = binding.aktuell().daten
        val untouched = provider.rows.filter { it !== company }.map { it.toMap() }
        assertEquals(old.copy(firma = "New company"), writer(binding).uebernehmen(old.copy(firma = "New company"), {}, {}).daten)
        assertEquals("Keep title", company[Organization.TITLE])
        assertEquals(untouched, provider.rows.filter { it !== company }.map { it.toMap() })
    }

    @Test fun ambiguousPostalOrScalarEditsAndOutOfScopeFieldsStopBeforeProtection() {
        for (mode in listOf("postal", "scalar", "phone", "groups", "photo")) {
            setup()
            if (mode == "postal") { provider.postal("First", StructuredPostal.TYPE_HOME); provider.postal("Second", StructuredPostal.TYPE_HOME) }
            if (mode == "scalar") { provider.add(Organization.CONTENT_ITEM_TYPE, mapOf(Organization.COMPANY to "A")); provider.add(Organization.CONTENT_ITEM_TYPE, mapOf(Organization.COMPANY to "B")) }
            val binding = capture(); val old = binding.aktuell().daten
            val wanted = when (mode) {
                "postal" -> old.copy(anschriften = listOf(KontaktAnschrift("privat", "Third")))
                "scalar" -> old.copy(firma = "New company")
                "phone" -> old.copy(telefone = listOf(KontaktWert("mobil", "123")))
                "groups" -> old.copy(gruppen = listOf("Not selected"))
                else -> old.copy(foto = "Unrequested picture")
            }
            assertThrows(IllegalArgumentException::class.java) {
                writer(binding).uebernehmen(wanted, {}, { fail("Ambiguous or unrelated field reached protection") })
            }
            assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
        }
    }

    @Test fun protectionFailureRevocationAndChangedOriginalStopBeforeAnyProviderMutation() {
        for (mode in listOf("protection", "revocation", "source-change")) {
            setup(); val binding = capture(); val wanted = binding.aktuell().daten.copy(notiz = "Pending note")
            var revoked = false
            assertThrows(Exception::class.java) {
                writer(binding).uebernehmen(wanted, { check(!revoked) }, {
                    when (mode) {
                        "protection" -> error("Controlled protection failure")
                        "revocation" -> revoked = true
                        else -> provider.raw[RawContacts.SOURCE_ID] = "Changed during protection"
                    }
                })
            }
            assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
        }
    }

    @Test fun postalKindChangesAdditionsAndRemovalsOnlyTouchRowsOfTheBoundOriginal() {
        val old = provider.postal("Same street", StructuredPostal.TYPE_CUSTOM)
        old[StructuredPostal.LABEL] = "Old custom label"; old[StructuredPostal.POBOX] = "Keep box"
        val id = old[Data._ID]
        val first = capture(); val wanted = first.aktuell().daten.copy(anschriften = listOf(KontaktAnschrift("arbeit", "Same street")))
        writer(first).uebernehmen(wanted, {}, {})
        assertEquals(id, old[Data._ID]); assertNull(old[StructuredPostal.LABEL])
        assertEquals(StructuredPostal.TYPE_WORK, old[StructuredPostal.TYPE]); assertEquals("Keep box", old[StructuredPostal.POBOX])
        val second = capture(); val next = second.aktuell().daten.copy(anschriften = wanted.anschriften + KontaktAnschrift("privat", "Added street"))
        assertEquals(next, writer(second).uebernehmen(next, {}, {}).daten)
        val third = capture(); val cleared = third.aktuell().daten.copy(anschriften = emptyList())
        val calls = provider.batchCalls
        assertThrows(IllegalArgumentException::class.java) {
            writer(third).uebernehmen(cleared, {}, { fail("Hidden postal value reached removal protection") })
        }
        assertEquals(calls, provider.batchCalls); assertEquals("Keep box", old[StructuredPostal.POBOX])
        // A separately observed native removal of the unmodeled value makes the
        // remaining modeled-only row removable; the return writer never erases it.
        context.contentResolver.update(ContentUris.withAppendedId(Data.CONTENT_URI, id as Long), ContentValues().apply {
            put(StructuredPostal.POBOX, "")
        }, null, null)
        assertEquals(cleared, writer(capture()).uebernehmen(cleared, {}, {}).daten)
        assertEquals(1, provider.rows.size); assertEquals(7L, provider.raw[RawContacts._ID])
    }

    @Test fun rejectedProviderBatchIsAtomicAndAnUnknownReadbackCannotBeReplayed() {
        val binding = capture(); val before = binding.aktuell(); val wanted = before.daten.copy(firma = "New company", notiz = "New note")
        val writer = writer(binding)
        provider.failAt = 6
        assertThrows(OperationApplicationException::class.java) { writer.uebernehmen(wanted, {}, {}) }
        assertEquals(before, capture().aktuell())
        assertThrows(IllegalStateException::class.java) { writer.uebernehmen(wanted, {}, {}) }
        setup()
        val second = capture(); val next = second.aktuell().daten.copy(notiz = "Unconfirmed note")
        val uncertain = writer(second); provider.dropUpdates = true
        assertThrows(IllegalArgumentException::class.java) { uncertain.uebernehmen(next, {}, {}) }
        val calls = provider.batchCalls
        assertThrows(IllegalStateException::class.java) { uncertain.uebernehmen(next, {}, {}) }
        assertEquals(calls, provider.batchCalls)
    }

    @Test fun legitimateLookupKeyChangeAfterNameWriteIsResolvedOnlyThroughTheSameNativeOriginal() {
        val binding = capture(); val wanted = binding.aktuell().daten.copy(vorname = "New name")
        provider.lookupAfterWrite = "native-lookup-after-name-edit"
        val actual = writer(binding).uebernehmen(wanted, {}, {})
        assertEquals(wanted, actual.daten); assertEquals(7L, actual.rawContactId)
        assertEquals("native-lookup-after-name-edit", actual.lookupKey)
        assertEquals(11L, actual.contactId); assertEquals("original-server-id", actual.herkuenfte.single().sourceId)
        assertThrows(IllegalArgumentException::class.java) { binding.aktuell() }
    }

    @Test fun aChangedAccountSourceDatabaseOrNativeContactAfterWritingIsNeverAConfirmedReturn() {
        val changes: List<() -> Unit> = listOf(
            { provider.raw[RawContacts.ACCOUNT_NAME] = "other@example.invalid" },
            { provider.raw[RawContacts.SOURCE_ID] = "other-source-id" },
            { provider.status[ProviderStatus.DATABASE_CREATION_TIMESTAMP] = 999999L },
            { provider.contact[Contacts._ID] = 999L })
        for (change in changes) {
            setup(); val binding = capture(); val wanted = binding.aktuell().daten.copy(notiz = "Pending note")
            val writer = writer(binding); provider.afterWrite = change
            assertThrows(IllegalArgumentException::class.java) { writer.uebernehmen(wanted, {}, {}) }
            assertEquals(1, provider.batchCalls)
            assertThrows(IllegalStateException::class.java) { writer.uebernehmen(wanted, {}, {}) }
            assertEquals(1, provider.batchCalls)
        }
    }

    @Test fun oversizedNativeBatchIsHeldBeforeProtectionRatherThanSplitOrSentToBinder() {
        val binding = capture()
        val text = "x".repeat(1900)
        val wanted = binding.aktuell().daten.copy(anschriften = List(100) {
            KontaktAnschrift("privat", "$it$text", text, text, text, text)
        })
        val failure = assertThrows(IllegalArgumentException::class.java) {
            writer(binding).uebernehmen(wanted, {}, { fail("Oversized batch reached original protection") })
        }
        assertEquals("contact_original_binder_budget_required", failure.message)
        assertEquals(0, provider.batchCalls); assertEquals(0, provider.writes)
    }

    @Test fun defaultOffAndFakeNativeGrantsDoNotObservePeersOrReachCallbacksAndProtection() {
        val binding = capture(); var peers = 0; var callbacks = 0
        val off = KontaktOriginalFreigaben { peers++; peer }
        val queries = provider.queries
        assertFalse(off.gewuenscht)
        assertThrows(SecurityException::class.java) { off.freigabe(binding) }
        assertEquals(queries, provider.queries); assertEquals(0, peers)
        val forged = KontaktOriginalFreigaben.Freigabe(binding, Any())
        assertThrows(SecurityException::class.java) {
            KontaktOriginalInhalt(forged).uebernehmen(binding.aktuell().daten.copy(notiz = "Unapproved"),
                { callbacks++ }, { fail("Fake grant reached protection") })
        }
        assertEquals(0, callbacks); assertEquals(0, provider.writes)
    }

    @Test fun oneNativeSourceDecisionCoversFreshRevisionsWithoutRepeatedConfirmation() {
        val first = capture(); val one = first.aktuell().daten.copy(notiz = "First native return")
        writer(first).uebernehmen(one, {}, {})
        val second = capture(); val two = second.aktuell().daten.copy(notiz = "Second native return")
        assertEquals(two, writer(second).uebernehmen(two, {}, {}).daten)
        assertEquals(1, decisions); assertEquals(2, provider.batchCalls)
    }

    @Test fun cancelAndUnOfferedSourcePreserveTheDecisionButEmptySelectionRevokesEveryOldWitness() {
        val binding = capture(); writer(binding)
        val grant = approvals.freigabe(binding)
        assertFalse(approvals.einrichten(listOf(binding)) { null })
        grant.pruefen()
        assertThrows(IllegalArgumentException::class.java) {
            approvals.einrichten(listOf(binding)) { choices -> setOf(choices.single().copy(datenbank = 999L)) }
        }
        grant.pruefen()
        assertTrue(approvals.einrichten(listOf(binding)) { emptySet() })
        assertFalse(approvals.gewuenscht)
        assertThrows(SecurityException::class.java) { grant.pruefen() }
        assertEquals(0, provider.writes)
    }

    @Test fun temporaryPeerWaitRetainsIntentButAnotherPeerKeyOrAccountCannotUseTheGrant() {
        val binding = capture(); writer(binding)
        val grant = approvals.freigabe(binding); val originalPeer = peer
        peer = null
        assertThrows(SecurityException::class.java) { grant.pruefen() }
        assertTrue(approvals.gewuenscht)
        peer = originalPeer!!.copy(schluessel = "Other pinned key")
        assertThrows(SecurityException::class.java) { grant.pruefen() }
        peer = originalPeer; grant.pruefen()
        provider.raw[RawContacts.ACCOUNT_NAME] = "other@example.invalid"
        assertThrows(IllegalArgumentException::class.java) { grant.pruefen() }
        assertThrows(SecurityException::class.java) { approvals.freigabe(capture()) }
        assertEquals(1, decisions); assertEquals(0, provider.writes)
    }

    @Test fun revocationCannotBeBypassedByAnExtraLifetimeCallbackOrAProtectionCallback() {
        for (mode in listOf("lifetime", "protection")) {
            setup(); val binding = capture(); val nativeWriter = writer(binding)
            assertThrows(SecurityException::class.java) {
                nativeWriter.uebernehmen(binding.aktuell().daten.copy(notiz = "Revoked"), {
                    if (mode == "lifetime") approvals.widerrufen()
                }, { if (mode == "protection") approvals.widerrufen() else fail("Revoked callback reached protection") })
            }
            assertEquals(0, provider.writes); assertEquals(0, provider.batchCalls)
        }
    }

    @Test fun revokeDuringTheDecisionCannotBeUndoneByItsStaleSelection() {
        val binding = capture()
        assertThrows(IllegalStateException::class.java) {
            approvals.einrichten(listOf(binding)) { choices -> approvals.widerrufen(); choices.toSet() }
        }
        assertFalse(approvals.gewuenscht)
        assertThrows(SecurityException::class.java) { approvals.freigabe(binding) }
        assertEquals(0, provider.writes)
    }

    @Test fun revocationAfterProviderWriteHoldsCompletionAndDoesNotReplayTheAttempt() {
        val binding = capture(); val nativeWriter = writer(binding)
        val target = binding.aktuell().daten.copy(notiz = "Outcome must stay held")
        provider.afterWrite = { approvals.widerrufen() }
        assertThrows(SecurityException::class.java) { nativeWriter.uebernehmen(target, {}, {}) }
        assertEquals(1, provider.batchCalls)
        assertThrows(IllegalStateException::class.java) { nativeWriter.uebernehmen(target, {}, {}) }
        assertEquals(1, provider.batchCalls)
    }

    @Test fun mutableNativeChoiceContainersCannotAddAnUnofferedSourceAfterValidation() {
        val binding = capture()
        var selected: MutableSet<KontaktOriginalFreigaben.Quelle>? = null
        val other = KontaktOriginalFreigaben.Quelle(binding.datenbankErstellt, binding.quelle.copy(kontoName = "other@example.invalid"))
        val scope = KontaktOriginalFreigaben { selected?.add(other); peer }
        assertTrue(scope.einrichten(listOf(binding)) { choices -> choices.toMutableSet().also { selected = it } })
        scope.freigabe(binding).pruefen()
        assertTrue(selected!!.contains(other)) // The caller really did mutate its own returned container.
        provider.raw[RawContacts.ACCOUNT_NAME] = "other@example.invalid"
        assertThrows(SecurityException::class.java) { scope.freigabe(capture()) }
        assertEquals(0, provider.writes)
    }

    private class OriginalProvider : ContentProvider() {
        val status = mutableMapOf<String, Any?>(ProviderStatus.STATUS to ProviderStatus.STATUS_NORMAL,
            ProviderStatus.DATABASE_CREATION_TIMESTAMP to 123456L)
        val raw = mutableMapOf<String, Any?>(RawContacts._ID to 7L, RawContacts.CONTACT_ID to 11L,
            RawContacts.VERSION to 3L, RawContacts.ACCOUNT_NAME to "synthetic@example.invalid",
            RawContacts.ACCOUNT_TYPE to "synthetic.provider", RawContacts.DATA_SET to "native-set",
            RawContacts.SOURCE_ID to "original-server-id", RawContacts.DELETED to 0,
            RawContacts.RAW_CONTACT_IS_READ_ONLY to 0)
        val contact = mutableMapOf<String, Any?>(Contacts._ID to 11L, Contacts.LOOKUP_KEY to "native-lookup",
            Contacts.IS_USER_PROFILE to 0, Contacts.CONTACT_LAST_UPDATED_TIMESTAMP to 1000L)
        val row = mutableMapOf<String, Any?>(Data._ID to 23L, Data.RAW_CONTACT_ID to 7L,
            Data.MIMETYPE to StructuredName.CONTENT_ITEM_TYPE, StructuredName.GIVEN_NAME to "Synthetic", Data.IS_READ_ONLY to 0)
        val rows = mutableListOf(row)
        private var nextId = 1000L
        var batchCalls = 0
        var failAt = -1
        var dropUpdates = false
        var lookupAfterWrite: String? = null
        var afterWrite: (() -> Unit)? = null
        var aggregate = false
        var queries = 0
        var writes = 0
        var beforeBatch: (() -> Unit)? = null
        var onQuery: (() -> Unit)? = null
        var beforeRawReread: (() -> Unit)? = null
        private var rawReads = 0
        override fun onCreate() = true
        override fun getType(uri: Uri): String? = null
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, sort: String?): Cursor {
            queries++
            onQuery?.also { onQuery = null }?.invoke()
            if (uri.pathSegments.first() == "raw_contacts" && uri.pathSegments.size > 1 && ++rawReads == 2)
                beforeRawReread?.also { beforeRawReread = null }?.invoke()
            val values: List<Map<String, Any?>> = when (uri.pathSegments.first()) {
                "provider_status" -> listOf(status)
                "raw_contacts" -> if (uri.pathSegments.size > 1) listOf(raw) else
                    listOf(raw) + if (aggregate) listOf(raw.toMap() + (RawContacts._ID to 8L)) else emptyList()
                "contacts" -> if (args != null && contact[Contacts.LOOKUP_KEY] !in args) emptyList() else listOf(contact)
                "data" -> rows.filter { value ->
                    if (uri.pathSegments.size > 1) value[Data._ID].toString() == uri.lastPathSegment
                    else args == null || value[Data.RAW_CONTACT_ID].toString() == args[0] &&
                        (args.size < 2 || value[Data.MIMETYPE] == args[1]) &&
                        (args.size < 3 || value[Event.TYPE].toString() == args[2])
                }
                else -> throw UnsupportedOperationException("Synthetic provider does not implement ${uri.path}")
            }
            val columns = requireNotNull(projection)
            return MatrixCursor(columns).apply { values.forEach { value -> addRow(columns.map { value[it] }.toTypedArray()) } }
        }
        override fun applyBatch(operations: ArrayList<ContentProviderOperation>): Array<ContentProviderResult> {
            beforeBatch?.also { beforeBatch = null }?.invoke()
            val previous = rows.map { it.toMap() }; val oldVersion = raw[RawContacts.VERSION]
            batchCalls++
            try {
                val results = arrayOfNulls<ContentProviderResult>(operations.size)
                operations.forEachIndexed { index, op ->
                    if (index == failAt) throw OperationApplicationException("Controlled atomic failure")
                    results[index] = op.apply(this, results, index)
                }
                return results.map { requireNotNull(it) }.toTypedArray()
            } catch (error: Exception) {
                row.clear(); row.putAll(previous.first()); rows.clear(); rows.add(row)
                rows.addAll(previous.drop(1).map { it.toMutableMap() }); raw[RawContacts.VERSION] = oldVersion
                throw error
            }
        }
        fun add(mime: String, values: Map<String, Any?>): MutableMap<String, Any?> =
            (values + mapOf(Data._ID to nextId++, Data.RAW_CONTACT_ID to 7L, Data.IS_READ_ONLY to 0, Data.MIMETYPE to mime)).toMutableMap().also { rows += it }
        fun postal(street: String, type: Int) = add(StructuredPostal.CONTENT_ITEM_TYPE, mapOf(
            StructuredPostal.STREET to street, StructuredPostal.TYPE to type, StructuredPostal.FORMATTED_ADDRESS to "Old formatted address"))
        private fun changed() {
            writes++; raw[RawContacts.VERSION] = (raw.getValue(RawContacts.VERSION) as Number).toLong() + 1
            lookupAfterWrite?.let { contact[Contacts.LOOKUP_KEY] = it }
            afterWrite?.also { afterWrite = null }?.invoke()
        }
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            check(uri.pathSegments.first() == "data")
            val value = requireNotNull(values)
            val inserted = add(value.getAsString(Data.MIMETYPE), value.valueSet().associate { it.key to it.value })
            if (dropUpdates) rows.remove(inserted)
            changed(); return ContentUris.withAppendedId(Data.CONTENT_URI, inserted.getValue(Data._ID) as Long)
        }
        override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?): Int {
            check(uri.pathSegments.first() == "data")
            val selected = rows.single { it[Data._ID].toString() == uri.lastPathSegment }
            if (!dropUpdates) requireNotNull(values).valueSet().forEach { selected[it.key] = it.value }
            changed(); return 1
        }
        override fun delete(uri: Uri, selection: String?, args: Array<out String>?): Int {
            check(uri.pathSegments.first() == "data")
            val selected = rows.single { it[Data._ID].toString() == uri.lastPathSegment }
            if (!dropUpdates) rows.remove(selected)
            changed(); return 1
        }
    }
}
