package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.ContentUris
import android.content.ContentValues
import android.content.OperationApplicationException
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.telefon.ContactGroupTitleWrite
import io.gitlab.maik3531.magnolienotes.telefon.ContactGroupTitleWriteAndroid
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
class KontaktGruppenTitelRessourceTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktGruppenProviderTest.GroupProvider
    private lateinit var contacts: AndroidKontakte
    private lateinit var contact: AndroidKontakt
    private lateinit var writer: ContactGroupTitleWriteAndroid
    private val owner = Any()
    private var time = 1000L
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext(); provider = KontaktGruppenProviderTest.GroupProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        contacts = AndroidKontakte(context, android.accounts.Account("owner@example.test", "fixture"))
        contact = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Work")))
        writer = ContactGroupTitleWriteAndroid(context) { time }
    }
    @After fun cleanup() { provider.shutdown() }
    private fun request(action: String = "prepare", token: JsonElement? = null) = buildJsonObject {
        put("version", 20); put("request_id", UUID.randomUUID().toString()); put("action", action); put("uid", contact.lookupKey)
        put("old_title", "Work"); put("new_title", "Arbeit"); if (token != null) put("token", token)
    }
    @Test fun readonlyPreparationAndSavedReportKeepTheSameNativeGroupIdentity() {
        val before = provider.batchCalls
        val prepared = writer.execute(request(), owner)
        assertEquals(before, provider.batchCalls); assertEquals("prepared", prepared["state"]!!.jsonPrimitive.content)
        val saved = writer.execute(request("apply", prepared["token"]), owner)
        ContactGroupTitleWrite.validateReport(saved)
        assertEquals("saved", saved["state"]!!.jsonPrimitive.content)
        assertEquals(prepared["group_id"], saved["group_id"]); assertEquals(prepared["account"], saved["account"])
        assertEquals(listOf("Arbeit"), contacts.liesRaw(contact.rawContactId)!!.daten.gruppen)
        assertThrows(Exception::class.java) { writer.execute(request("apply", prepared["token"]), owner) }
    }
    @Test fun reportsRequireCanonicalPositiveNativeGroupIds() {
        val prepared = writer.execute(request(), owner)
        for (id in listOf("0", "-1", "+1", "01", " 1", "1 ", "1.0", "9223372036854775808"))
            assertThrows(Exception::class.java) { ContactGroupTitleWrite.validateReport(JsonObject(prepared + ("group_id" to JsonPrimitive(id)))) }
        ContactGroupTitleWrite.validateReport(JsonObject(prepared + ("group_id" to JsonPrimitive("9223372036854775807"))))
    }
    @Test fun ticketCannotRenameAnotherContactOrTitleOrBeUsedByAnotherSession() {
        val prepared = writer.execute(request(), owner); val apply = request("apply", prepared["token"])
        assertThrows(Exception::class.java) { writer.execute(apply, Any()) }
        assertThrows(Exception::class.java) { writer.execute(JsonObject(apply + ("uid" to JsonPrimitive("foreign"))), owner) }
        assertThrows(Exception::class.java) { writer.execute(JsonObject(apply + ("new_title" to JsonPrimitive("Other"))), owner) }
        assertEquals(listOf("Work"), contacts.liesRaw(contact.rawContactId)!!.daten.gruppen)
        assertEquals("saved", writer.execute(apply, owner)["state"]!!.jsonPrimitive.content)
    }
    @Test fun closingAnOldSessionDoesNotRevokeAnotherSessionsPreparation() {
        val other = Any()
        val first = writer.execute(request(), owner)
        val second = writer.execute(request(), other)
        writer.clear(owner)
        assertThrows(Exception::class.java) { writer.execute(request("apply", first["token"]), owner) }
        assertEquals("saved", writer.execute(request("apply", second["token"]), other)["state"]!!.jsonPrimitive.content)
    }
    @Test fun inspectionRecoversALostWriteReportWithoutRepeatingTheMutation() {
        val prepared = writer.execute(request(), owner)
        writer.execute(request("apply", prepared["token"]), owner) // The saved result may be lost in transport.
        val before = provider.batchCalls
        val inspect = JsonObject(request() + mapOf("action" to JsonPrimitive("inspect"),
            "group_id" to prepared.getValue("group_id"), "account" to prepared.getValue("account")))
        val observed = writer.execute(inspect, owner)
        assertEquals(before, provider.batchCalls)
        assertEquals("Arbeit", observed["current_title"]!!.jsonPrimitive.content)
        assertEquals(prepared["group_identity"], observed["group_identity"])
        assertFalse("token" in observed)
        val account = prepared.getValue("account").jsonObject
        assertThrows(Exception::class.java) { writer.execute(JsonObject(inspect + ("account" to JsonObject(account + ("name" to JsonPrimitive("foreign"))))), owner) }
        assertEquals(before, provider.batchCalls)
    }
    @Test fun inspectionDoesNotConfuseAReboundProviderSourceWithThePreparedGroup() {
        val prepared = writer.execute(request(), owner)
        val inspect = JsonObject(request() + mapOf("action" to JsonPrimitive("inspect"),
            "group_id" to prepared.getValue("group_id"), "account" to prepared.getValue("account")))
        assertEquals(prepared["group_identity"], writer.execute(inspect, owner)["group_identity"])
        val groupId = prepared.getValue("group_id").jsonPrimitive.content.toLong()
        assertEquals(1, context.contentResolver.update(ContentUris.withAppendedId(ContactsContract.Groups.CONTENT_URI, groupId),
            ContentValues().apply { put(ContactsContract.Groups.SOURCE_ID, "rebound-source") }, null, null))
        assertNotEquals(prepared["group_identity"], writer.execute(inspect, owner)["group_identity"])
        assertThrows(OperationApplicationException::class.java) { writer.execute(request("apply", prepared["token"]), owner) }
        assertEquals(listOf("Work"), contacts.liesRaw(contact.rawContactId)!!.daten.gruppen)
    }
    @Test fun invalidNativeSourceUnicodeCannotCollapseIntoAReplacementIdentity() {
        val prepared = writer.execute(request(), owner)
        val groupId = prepared.getValue("group_id").jsonPrimitive.content.toLong()
        context.contentResolver.update(ContentUris.withAppendedId(ContactsContract.Groups.CONTENT_URI, groupId),
            ContentValues().apply { put(ContactsContract.Groups.SOURCE_ID, "\uD800") }, null, null)
        val before = provider.batchCalls
        assertThrows(Exception::class.java) { writer.execute(request(), owner) }
        assertEquals(before, provider.batchCalls)
    }
    @Test fun concurrentContactChangeInvalidatesAndConsumesTheTitleTicket() {
        val prepared = writer.execute(request(), owner)
        provider.beforeBatch = { provider.bump(contact.rawContactId) }
        val apply = request("apply", prepared["token"])
        assertThrows(OperationApplicationException::class.java) { writer.execute(apply, owner) }
        assertThrows(Exception::class.java) { writer.execute(apply, owner) }
        assertEquals(listOf("Work"), contacts.liesRaw(contact.rawContactId)!!.daten.gruppen)
    }
    @Test fun expiryAndRevocationRequireANewPreparation() {
        var prepared = writer.execute(request(), owner); time += 30_000
        assertThrows(Exception::class.java) { writer.execute(request("apply", prepared["token"]), owner) }
        prepared = writer.execute(request(), owner)
        shadowOf(context as Application).denyPermissions(Manifest.permission.WRITE_CONTACTS)
        assertThrows(Exception::class.java) { writer.execute(request("apply", prepared["token"]), owner) }
        shadowOf(context as Application).grantPermissions(Manifest.permission.WRITE_CONTACTS)
        assertThrows(Exception::class.java) { writer.execute(request("apply", prepared["token"]), owner) }
    }
}
