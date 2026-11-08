package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.os.Looper
import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.PosixFilePermission
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.crypto.SecretKey
import javax.xml.parsers.SAXParserFactory
import org.json.JSONObject

/** Real Android parser/filesystem/Keystore evidence. No WebView test bridge or live account/network.
 * Called by instrumentation on its worker thread in a disposable emulator only.
 */
internal object NativeDavAccountSmoke {
    private const val ALIAS = "magnolie-organizer-tablet-beta-dav-credentials-v1"
    private val directoryMode = setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE)
    private val fileMode = setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)

    fun run(context: Context): JSONObject {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Native DAV checks require an instrumentation worker" }
        check(DisposableEmulatorPolicy.accepts(android.os.Build.FINGERPRINT, android.os.Build.MODEL, android.os.Build.BRAND)) { "Disposable emulator required" }
        val result = parserChecks()
        val task = AndroidStore.io.submit<JSONObject> { accountChecks(context.applicationContext) }
        val account = try { task.get(35,TimeUnit.SECONDS) }
            finally { if (!task.isDone) task.cancel(true) }
        result.put("account",account).put("liveNetworkUsed",false).put("fullSyncAccepted",false)
        return result
    }

    private class Script(vararg replies: BoundedHttpResponse) : BoundedHttpTransport {
        private val replies = replies.toMutableList()
        val requests = mutableListOf<BoundedHttpRequest>()
        override fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse {
            cancellation.check()
            check(request.uri.scheme == "https" && request.uri.host == "native-dav.example.test") { "Unexpected fixture origin" }
            check(replies.isNotEmpty()) { "Unexpected fixture request" }
            requests.add(request)
            return replies.removeAt(0)
        }
        fun complete() { check(replies.isEmpty()) { "Fixture responses not consumed" } }
    }
    private fun xml(rows: String) = BoundedHttpResponse(207,body=("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:a='urn:ietf:params:xml:ns:carddav'>$rows</d:multistatus>").toByteArray())
    private fun row(href: String, properties: String) = "<d:response><d:href>$href</d:href><d:propstat><d:prop>$properties</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    private fun reject(code: String, action: () -> Unit) {
        val failure = try { action(); null } catch (error: DavException) { error }
        check(failure?.code == code) { "Native DAV rejection did not match expected safe code" }
    }
    private fun rejectAccount(code: String, action: () -> Unit) {
        val failure = try { action(); null } catch (error: DavAccountException) { error }
        check(failure?.code == code) { "Native account rejection did not match expected safe code" }
    }

    private fun parserChecks(): JSONObject {
        val parser = SAXParserFactory.newInstance().newSAXParser().xmlReader.javaClass.name
        check(parser.contains("Expat")) { "Android Expat parser required; JVM XML parsing is not native evidence" }
        val base = "https://native-dav.example.test"
        val calendar = URI("$base/calendars/synthetic/personal/")
        val addressBook = URI("$base/addressbooks/synthetic/contacts/")
        val event = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:native-event\nDTSTART:20261109T090000Z\nRRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Synthetic event\nEND:VEVENT\nEND:VCALENDAR\n"
        val task = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:native-task\nDUE:20261110T120000Z\nSUMMARY:Synthetic task\nEND:VTODO\nEND:VCALENDAR\n"
        val card = "BEGIN:VCARD\nVERSION:4.0\nUID:native-contact\nFN:Synthetic Contact\nEND:VCARD\n"
        val transport = Script(
            xml(row("/.well-known/caldav","<d:current-user-principal><d:href>/principals/synthetic/</d:href></d:current-user-principal>")),
            xml(row("/principals/synthetic/","<c:calendar-home-set><d:href>/calendars/synthetic/</d:href></c:calendar-home-set>")),
            xml(row(calendar.path,"<d:displayname>Native &amp; Synthetic</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype><c:supported-calendar-component-set><c:comp name='VEVENT'/><c:comp name='VTODO'/></c:supported-calendar-component-set>")),
            xml(row("/.well-known/carddav","<d:current-user-principal><d:href>/principals/synthetic/</d:href></d:current-user-principal>")),
            xml(row("/principals/synthetic/","<a:addressbook-home-set><d:href>/addressbooks/synthetic/</d:href></a:addressbook-home-set>")),
            xml(row(addressBook.path,"<d:displayname>Synthetic contacts</d:displayname><d:resourcetype><a:addressbook/></d:resourcetype>")),
            xml(row(calendar.resolve("event.ics").path,"<d:getetag>&quot;event-v1&quot;</d:getetag><c:calendar-data><![CDATA[$event]]></c:calendar-data>") +
                row(calendar.resolve("task.ics").path,"<d:getetag>W/&quot;task-v1&quot;</d:getetag><c:calendar-data><![CDATA[$task]]></c:calendar-data>")),
            xml(row(addressBook.resolve("contact.vcf").path,"<d:getetag>&quot;contact-v1&quot;</d:getetag><a:address-data><![CDATA[$card]]></a:address-data>")))
        val client = DavClient(base,"synthetic","native-only-fixture",transport=transport)
        val calendars = client.collections(DavKind.CALENDAR)
        check(calendars.single().href == calendar && calendars.single().supportsVtodo && calendars.single().name == "Native & Synthetic")
        val books = client.collections(DavKind.ADDRESSBOOK)
        check(books.single().href == addressBook)
        val resources = client.report(calendar,DavKind.CALENDAR)
        check(resources.size == 2 && resources[0].data == event && resources[1].data == task)
        check(resources[0].etag == "\"event-v1\"" && resources[1].etag == "W/\"task-v1\"")
        val contacts = client.report(addressBook,DavKind.ADDRESSBOOK)
        check(contacts.single().data == card && contacts.single().etag == "\"contact-v1\"")
        check(transport.requests.map { it.method } == List(6) { "PROPFIND" } + List(2) { "REPORT" })
        transport.complete()
        var rejected = 0
        for (bad in listOf(
            "<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///nonexistent-native-dav-fixture'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<!DOCTYPE x [<!ENTITY x SYSTEM 'https://native-dav.example.test/never-request'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<!DOCTYPE x [<!ENTITY x 'amplify'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'><d:response></d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'>" + "<d:x>".repeat(65) + "</d:x>".repeat(65) + "</d:multistatus>")) {
            val script = Script(BoundedHttpResponse(207,body=bad.toByteArray()))
            reject("malformed_xml") { DavClient(base,"synthetic","fixture",transport=script).report(calendar,DavKind.CALENDAR) }
            check(script.requests.size == 1); rejected++
        }
        val oversized = Script(BoundedHttpResponse(207,body=ByteArray(DavClient.XML_LIMIT + 1)))
        reject("response_too_large") { DavClient(base,"synthetic","fixture",transport=oversized).home(DavKind.CALENDAR) }
        check(oversized.requests.size == 1); rejected++
        return JSONObject().put("androidXmlParser",parser).put("calendarCollections",calendars.size)
            .put("addressBookCollections",books.size).put("reportEventsAndTasks",resources.size)
            .put("reportContacts",contacts.size).put("etagsPreserved",true).put("recurrenceBodyPreserved",true)
            .put("nativeXmlNegativeCases",rejected).put("externalEntitiesRejected",true)
    }

    private fun mode(file: File) = Files.getPosixFilePermissions(file.toPath(),LinkOption.NOFOLLOW_LINKS)
    private fun vaultBytes(root: File): Map<String,ByteArray?> = listOf("tablet-vault.enc","tablet-vault.enc.pending","before-import.enc","before-import.pending")
        .associateWith { name -> File(root,name).let { file ->
            check(!Files.isSymbolicLink(file.toPath())) { "Unsafe vault fixture" }
            if (file.exists()) { check(file.length() <= 32 * 1024 * 1024) { "Disposable small vault required" }; file.readBytes() } else null
        } }

    private fun accountChecks(context: Context): JSONObject {
        val root = context.noBackupFilesDir
        check(!Files.exists(File(root,"nextcloud.json").toPath(),LinkOption.NOFOLLOW_LINKS)) { "Existing native account: refusing fixture mutation" }
        val before = vaultBytes(root)
        val nativeCredentials = AndroidDavCredentials.store(context)
        val credentials = DavStoredAccountCredentials(nativeCredentials)
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val previousAlias = keyStore.containsAlias(ALIAS)
        val token = UUID.randomUUID().toString()
        val first = DavAccountConfiguration(davEnabled=true,server="https://native-$token.example.test",user="native-fixture-first")
        val second = DavAccountConfiguration(davEnabled=true,server=first.server,user="native-fixture-second")
        check(credentials.read(first.identity) == null && credentials.read(second.identity) == null) { "Fixture credentials already exist" }
        val fixture = File(root,".native-dav-fixture-$token")
        check(fixture.mkdir()) { "Fixture directory already exists" }
        Files.setPosixFilePermissions(fixture.toPath(),directoryMode)
        val secret1 = "native-only-first-$token"
        val secret2 = "native-only-second-$token"
        var failMetadataOnce = false
        var result: JSONObject? = null
        try {
            val configuration = DavAccountFileStore(fixture,checkpoint={ stage ->
                if (failMetadataOnce && stage == "directory-sync") { failMetadataOnce=false; throw DavAccountException("native_operation_failed") }
            })
            val service = DavAccountService(configuration,credentials,BoundedHttpTransport { _, _ -> error("Real network forbidden in native account fixture") })
            val initial = service.status()
            check(initial.configuration == null && initial.revision != null)
            val saved = service.save(initial.revision!!,first,secret1)
            check(saved.configuration == first && saved.credentialPresent == true && !saved.connectivityChecked)
            check(saved.revision != initial.revision && mode(fixture) == directoryMode && mode(configuration.file) == fileMode)
            val encrypted = File(File(root,"dav-credentials-v1"),first.identity.storageKey + ".enc")
            check(mode(encrypted) == fileMode && encrypted.readBytes().isNotEmpty() &&
                Files.getOwner(encrypted.toPath()) == Files.getOwner(root.toPath()))
            check(!String(encrypted.readBytes(),Charsets.ISO_8859_1).contains(secret1)) { "Credential stored in plaintext" }
            check(!configuration.file.readText().contains(secret1) && !JSONObject(saved.payload()).toString().contains(secret1)) { "Credential leaked into metadata" }
            val key = keyStore.getKey(ALIAS,null) as? SecretKey
            check(key != null && key.encoded == null && key.format == null && key.algorithm == "AES") { "Native account key must be non-exportable" }
            val reopened = DavAccountService(DavAccountFileStore(fixture),credentials,
                BoundedHttpTransport { _, _ -> error("Real network forbidden in native account fixture") }).status()
            check(reopened.configuration == first && reopened.credentialPresent == true)
            rejectAccount("conflict") { service.save(initial.revision!!,first,secret1) }
            rejectAccount("app_password_missing") { service.save(saved.revision!!,second) }
            check(service.status().configuration == first && credentials.read(first.identity) == secret1 && credentials.read(second.identity) == null)
            failMetadataOnce = true
            rejectAccount("native_operation_failed") { service.save(saved.revision!!,second,secret2) }
            check(service.status().configuration == first && credentials.read(first.identity) == secret1 && credentials.read(second.identity) == null) { "Native rollback failed" }
            val changed = service.save(service.status().revision!!,second,secret2)
            check(changed.configuration == second && credentials.read(first.identity) == null && credentials.read(second.identity) == secret2)
            val disabled = DavAccountConfiguration(davEnabled=false,server=second.server,user=second.user)
            val cleared = service.save(changed.revision!!,disabled,clearPassword=true)
            check(cleared.configuration == disabled && cleared.credentialPresent == false && credentials.read(second.identity) == null)
            result = JSONObject().put("productionAccountService",true).put("productionCredentialProvider",true)
                .put("isolatedMetadata",true).put("nativePrivatePermissions",true).put("encryptedCredential",true)
                .put("keystoreNonExportable",true).put("saveReadback",true).put("reopenReadback",true)
                .put("staleRevisionRejected",true).put("identityChangeNeedsPassword",true)
                .put("metadataCommitRollback",true).put("identityChangeOldCredentialRemoved",true)
                .put("credentialDeletionVerified",true)
        } finally {
            // Only the two previously absent UUID-bound fixture identities may be removed.
            credentials.delete(first.identity); credentials.delete(second.identity)
            check(credentials.read(first.identity) == null && credentials.read(second.identity) == null)
            val metadata = File(fixture,"nextcloud.json")
            if (metadata.exists()) { check(metadata.delete()) }
            check(fixture.listFiles().orEmpty().isEmpty()) { "Unexpected file in owned fixture; refusing recursive deletion" }
            check(fixture.delete())
            val credentialDirectory = File(root,"dav-credentials-v1")
            val remainingCredentials = requireNotNull(credentialDirectory.listFiles()) { "Could not verify fixture credential cleanup" }
            if (!previousAlias && remainingCredentials.isEmpty()) keyStore.deleteEntry(ALIAS)
            val after = vaultBytes(root)
            check(before.keys == after.keys && before.all { (name, bytes) -> if (bytes == null) after[name] == null else after[name]?.let { bytes.contentEquals(it) } == true }) { "Account fixture altered vault bytes" }
            check(!File(root,"nextcloud.json").exists()) { "Account fixture created production metadata" }
        }
        return requireNotNull(result).put("fixtureCredentialsRemoved",true).put("fixtureMetadataRemoved",true).put("vaultBytesPreserved",true)
    }
}
