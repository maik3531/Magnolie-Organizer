package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.pm.ProviderInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.CommonDataKinds.Photo
import android.provider.ContactsContract.CommonDataKinds.StructuredName
import android.provider.ContactsContract.CommonDataKinds.GroupMembership
import android.provider.ContactsContract.Groups
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.util.Base64
import java.util.UUID
import java.io.ByteArrayOutputStream

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ContactReadProviderTest {
    private lateinit var context: Context
    private lateinit var provider: ReadOnlyProvider
    @Before fun prepare() {
        context = ApplicationProvider.getApplicationContext()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS)
        provider = ReadOnlyProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = "com.android.contacts"; exported = true })
        ShadowContentResolver.registerProviderInternal("com.android.contacts", provider)
    }
    private fun request(action: String) = buildJsonObject {
        put("version", JsonPrimitive(5)); put("request_id", JsonPrimitive(UUID.randomUUID().toString()))
        put("action", JsonPrimitive(action)); put("offset", JsonPrimitive(0))
        put("uids", if (action == "index") JsonArray(emptyList()) else JsonArray(listOf(JsonPrimitive("fixture-lookup"))))
    }
    @Test fun indexReadsMetadataOnly() {
        val result = ContactReadAndroid(context).read(request("index"))
        assertEquals(1L, result.long("total"))
        assertEquals(listOf("/contacts"), provider.queries)
    }
    @Test fun selectedCardReadsPhotoAndExplicitMessengerRowsWithoutWrites() {
        val result = ContactReadAndroid(context).read(request("cards"))
        val card = (result["contacts"] as JsonArray).single().jsonObject.string("vcard").replace("\r\n ", "")
        assertTrue(card.contains("TEL;TYPE=CELL:+49123456789"))
        assertTrue(card.contains("PHOTO;ENCODING=b;TYPE=JPEG:/9j"))
        assertTrue(card.contains("X-MAGNOLIE-SOZIALES-MEDIUM:"))
        assertTrue(card.contains("whatsapp"))
        assertTrue(card.contains("CATEGORIES:Fixture\\, group"))
        assertTrue(provider.sawSelection)
        assertEquals(2, provider.rawReads)
    }
    @Test fun rejectsProviderEditDuringReadAndMissingSystemPermission() {
        provider.changeVersion = true
        assertTrue(runCatching { ContactReadAndroid(context).read(request("cards")) }.isFailure)
        provider.queries.clear()
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.READ_CONTACTS)
        assertTrue(runCatching { ContactReadAndroid(context).read(request("index")) }.isFailure)
        assertTrue(provider.queries.isEmpty())
    }

    @Test fun rejectsChangedGroupTitleDuringReadWithoutInferringNames() {
        provider.changeGroup = true
        assertTrue(runCatching { ContactReadAndroid(context).read(request("cards")) }.isFailure)
    }

    @Test fun selectedAggregatedContactPhotoWinsOverLinkedAccountPhoto() {
        val bitmap = Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.BLUE)
        provider.displayPhoto = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        bitmap.recycle()
        val result = ContactReadAndroid(context).read(request("cards"))
        val card = (result["contacts"] as JsonArray).single().jsonObject.string("vcard").replace("\r\n ", "")
        val photo = card.lineSequence().first { it.startsWith("PHOTO;") }.substringAfter(':')
        val bytes = Base64.getDecoder().decode(photo)
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        val colour = decoded.getPixel(0, 0)
        assertTrue(Color.blue(colour) > 240 && Color.red(colour) < 20 && Color.green(colour) < 20)
        decoded.recycle()
        assertTrue(provider.photoUris.contains("/contacts/10/display_photo"))
    }

    class ReadOnlyProvider : ContentProvider() {
        val queries = mutableListOf<String>()
        var rawReads = 0
        var changeVersion = false
        var sawSelection = false
        var groupReads = 0
        var changeGroup = false
        var displayPhoto: ByteArray? = null
        val photoUris = mutableListOf<String>()
        override fun onCreate() = true
        override fun getType(uri: Uri): String? = null
        override fun insert(uri: Uri, values: ContentValues?): Uri? = error("read-only query attempted an insert")
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = error("read-only query attempted an update")
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = error("read-only query attempted a deletion")
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            assertEquals("r", mode);photoUris += uri.path.orEmpty()
            val bytes = displayPhoto ?: throw java.io.FileNotFoundException()
            assertEquals("/contacts/10/display_photo", uri.path)
            val pipe = ParcelFileDescriptor.createPipe()
            ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]).use { it.write(bytes) }
            return pipe[0]
        }
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            val columns = projection ?: error("projection required")
            queries += uri.path.orEmpty()
            val rows: List<Map<String, Any?>> = when (uri.path) {
                "/raw_contacts" -> {
                    rawReads++
                    listOf(mapOf(RawContacts._ID to 1L, RawContacts.CONTACT_ID to 10L, RawContacts.ACCOUNT_TYPE to "fixture",
                        RawContacts.ACCOUNT_NAME to "Fixture", RawContacts.VERSION to if (changeVersion && rawReads > 1) 2L else 1L))
                }
                "/contacts" -> {
                    if (selectionArgs != null) {
                        assertEquals(listOf("fixture-lookup"), selectionArgs.toList())
                        assertTrue(selection.orEmpty().contains(Contacts.LOOKUP_KEY)); sawSelection = true
                    }
                    listOf(mapOf(Contacts._ID to 10L, Contacts.LOOKUP_KEY to "fixture-lookup", Contacts.CONTACT_LAST_UPDATED_TIMESTAMP to 1700000000000L))
                }
                "/data" -> if (selection.orEmpty().contains(Data.MIMETYPE)) {
                    assertEquals("10", selectionArgs!!.first())
                    if (selectionArgs[1] == GroupMembership.CONTENT_ITEM_TYPE) listOf(mapOf(GroupMembership.GROUP_ROW_ID to 7L))
                    else listOf(mapOf(Data.MIMETYPE to "vnd.android.cursor.item/vnd.com.whatsapp.profile", Data.DATA1 to "49123456789@s.whatsapp.net"))
                } else {
                    assertTrue(selection.orEmpty().contains("IN (1)"))
                    listOf(mapOf(Data.RAW_CONTACT_ID to 1L, Data.MIMETYPE to StructuredName.CONTENT_ITEM_TYPE,
                            Data.DATA1 to "Fixture Contact", Data.DATA2 to "Fixture", Data.DATA3 to "Contact"),
                        mapOf(Data.RAW_CONTACT_ID to 1L, Data.MIMETYPE to Phone.CONTENT_ITEM_TYPE, Data.DATA1 to "+49123456789", Data.DATA2 to Phone.TYPE_MOBILE),
                        mapOf(Data.RAW_CONTACT_ID to 1L, Data.MIMETYPE to Photo.CONTENT_ITEM_TYPE, Data.DATA15 to Base64.getDecoder().decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")))
                }
                "/groups" -> { groupReads++; listOf(mapOf(Groups.TITLE to if (changeGroup && groupReads > 1) "Changed group" else "Fixture, group")) }
                "/contacts/10/photo" -> emptyList()
                else -> error("unexpected contact URI")
            }
            return MatrixCursor(columns).apply { rows.forEach { row -> addRow(columns.map { row[it] }.toTypedArray()) } }
        }
    }
}
