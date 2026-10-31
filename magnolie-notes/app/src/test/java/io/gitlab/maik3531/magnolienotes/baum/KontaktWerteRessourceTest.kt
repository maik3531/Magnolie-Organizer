package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.OperationApplicationException
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.telefon.ContactValueWrite
import io.gitlab.maik3531.magnolienotes.telefon.ContactValueWriteAndroid
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class KontaktWerteRessourceTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktGruppenProviderTest.GroupProvider
    private lateinit var contacts: AndroidKontakte
    private lateinit var contact: AndroidKontakt
    private lateinit var writer: ContactValueWriteAndroid
    private val owner = Any()
    private var time = 1000L
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        provider = KontaktGruppenProviderTest.GroupProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        contacts = AndroidKontakte(context)
        contact = contacts.anlegen(KontaktDaten(vorname = "Synthetic", telefone = listOf(KontaktWert("mobil", "111")),
            emailEintraege = listOf(KontaktWert("arbeit", "old@example.invalid"))))
        writer = ContactValueWriteAndroid(context) { time }
    }
    @After fun cleanup() { provider.shutdown() }
    private fun prepare(names: Set<String> = ContactValueWrite.FIELDS) = buildJsonObject {
        put("version", ContactValueWrite.VERSION); put("request_id", UUID.randomUUID().toString()); put("action", "prepare")
        put("uid", contact.lookupKey); put("field_names", JsonArray(names.map(::JsonPrimitive)))
    }
    private fun apply(prepared: JsonObject, data: KontaktDaten, names: Set<String> = ContactValueWrite.FIELDS) = buildJsonObject {
        put("version", ContactValueWrite.VERSION); put("request_id", UUID.randomUUID().toString()); put("action", "apply")
        put("uid", contact.lookupKey); put("token", prepared.getValue("token")); put("fields", ContactValueWrite.values(data, names))
    }

    @Test fun prepareIsReadOnlyAndApplyUsesOneAtomicBatchWithRealSavedReadback() {
        val calls = provider.batchCalls
        val prepared = writer.execute(prepare(), owner)
        assertEquals(calls, provider.batchCalls); assertEquals("prepared", prepared["state"]!!.jsonPrimitive.content)
        val desired = contact.daten.copy(telefone = listOf(KontaktWert("mobil", "222")), emailEintraege = emptyList())
        val saved = writer.execute(apply(prepared, desired), owner)
        assertEquals(calls + 1, provider.batchCalls)
        assertEquals("saved", saved["state"]!!.jsonPrimitive.content)
        assertEquals(prepared["account"], saved["account"])
        assertEquals(ContactValueWrite.values(desired, ContactValueWrite.FIELDS), saved["fields"])
        assertEquals(desired.telefone, contacts.liesRaw(contact.rawContactId)!!.daten.telefone)
        assertTrue(contacts.liesRaw(contact.rawContactId)!!.daten.emailEintraege.isEmpty())
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, desired), owner) }
    }

    @Test fun ticketsBindSessionUidAndExactFieldsWithoutChangingUnselectedLists() {
        val prepared = writer.execute(prepare(setOf("telefone")), owner)
        val desired = contact.daten.copy(telefone = emptyList())
        val request = apply(prepared, desired, setOf("telefone"))
        assertThrows(Exception::class.java) { writer.execute(request, Any()) }
        assertThrows(Exception::class.java) { writer.execute(JsonObject(request + ("uid" to JsonPrimitive("other-uid"))), owner) }
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, desired), owner) }
        val saved = writer.execute(request, owner)
        assertEquals(setOf("telefone"), saved["fields"]!!.jsonObject.keys)
        assertEquals(contact.daten.emailEintraege, contacts.liesRaw(contact.rawContactId)!!.daten.emailEintraege)
    }

    @Test fun versionRaceConsumesTicketAndDoesNotPartiallyWriteEitherField() {
        val prepared = writer.execute(prepare(), owner)
        provider.beforeBatch = { provider.bump(contact.rawContactId) }
        val request = apply(prepared, contact.daten.copy(telefone = emptyList(), emailEintraege = emptyList()))
        assertThrows(OperationApplicationException::class.java) { writer.execute(request, owner) }
        val calls = provider.batchCalls
        assertThrows(Exception::class.java) { writer.execute(request, owner) }
        assertEquals(calls, provider.batchCalls)
        assertEquals(contact.daten, contacts.liesRaw(contact.rawContactId)!!.daten)
    }

    @Test fun expiryRevocationAndLifecycleClearInvalidatePreparations() {
        var prepared = writer.execute(prepare(), owner)
        time += 30_000
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, contact.daten), owner) }
        prepared = writer.execute(prepare(), owner)
        shadowOf(context as Application).denyPermissions(Manifest.permission.WRITE_CONTACTS)
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, contact.daten), owner) }
        shadowOf(context as Application).grantPermissions(Manifest.permission.WRITE_CONTACTS)
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, contact.daten), owner) }
        prepared = writer.execute(prepare(), owner); writer.clear()
        assertThrows(Exception::class.java) { writer.execute(apply(prepared, contact.daten), owner) }
    }

    @Test fun retiringOneSessionLeavesAnotherLiveOwnersPreparationUntouched() {
        val other = Any()
        val first = writer.execute(prepare(), owner)
        val second = writer.execute(prepare(), other)
        writer.clear(owner)
        assertThrows(Exception::class.java) { writer.execute(apply(first, contact.daten), owner) }
        assertEquals("saved", writer.execute(apply(second, contact.daten), other)["state"]!!.jsonPrimitive.content)
    }

    @Test fun linkedMessagingOverlayDoesNotBlockTheUniqueActualFieldOwner() {
        val overlayWriter = AndroidKontakte(context, android.accounts.Account("messenger", "overlay-provider"))
        val overlay = overlayWriter.anlegen(KontaktDaten(vorname = "Preserve overlay"))
        provider.aggregate(overlay.rawContactId, contact.contactId)
        val prepared = writer.execute(prepare(), owner)
        val desired = contact.daten.copy(telefone = listOf(KontaktWert("mobil", "222")))
        assertEquals("saved", writer.execute(apply(prepared, desired), owner)["state"]!!.jsonPrimitive.content)
        val scopedOverlay = AndroidKontakte(context, rawScope = setOf(overlay.rawContactId)).liesRaw(overlay.rawContactId)!!
        assertEquals("Preserve overlay", scopedOverlay.daten.vorname)
        assertTrue(scopedOverlay.daten.telefone.isEmpty()); assertTrue(scopedOverlay.daten.emailEintraege.isEmpty())
    }

    @Test fun multipleActualFieldOwnersAreRejectedBeforeAnyProviderChange() {
        val overlayWriter = AndroidKontakte(context, android.accounts.Account("other", "other-provider"))
        val overlay = overlayWriter.anlegen(KontaktDaten(vorname = "Other owner", telefone = listOf(KontaktWert("privat", "999"))))
        provider.aggregate(overlay.rawContactId, contact.contactId)
        val calls = provider.batchCalls
        assertThrows(Exception::class.java) { writer.execute(prepare(), owner) }
        assertEquals(calls, provider.batchCalls)
        assertEquals(listOf(KontaktWert("privat", "999")), AndroidKontakte(context, rawScope = setOf(overlay.rawContactId)).liesRaw(overlay.rawContactId)!!.daten.telefone)
    }
}
