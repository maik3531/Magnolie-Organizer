package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.os.Looper
import android.system.Os
import android.system.OsConstants
import android.system.ErrnoException
import java.io.IOException
import java.io.File
import java.net.URI
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
    private const val directoryMode = 0x1c0
    private const val fileMode = 0x180
    private val ops = AndroidOsStorageFileOps

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

    private fun mode(file: File) = requireNotNull(ops.stat(file)).mode and 0x1ff
    private fun vaultBytes(root: File): Map<String,ByteArray?> = listOf("tablet-vault.enc","tablet-vault.enc.pending","before-import.enc","before-import.pending")
        .associateWith { name -> File(root,name).let { file ->
            check(ops.stat(file)?.isSymlink != true) { "Unsafe vault fixture" }
            ops.read(file,32 * 1024 * 1024 + 1024)
        } }

    private fun storageChecks(parent: File,key: SecretKey): JSONObject {
        val directory=File(parent,"os-storage");check(ops.stat(directory)==null)
        ops.ensurePrivateDirectory(directory,true)
        var renameDenied=false;var symlinkRejected=false;var hardlinkRejected=false;var boundedReadRejected=false
        var checkpoints=0
        var originalFailure:Throwable?=null
        try {
            val old=File(directory,"old");val pending=File(directory,"pending")
            ops.writeAndSync(old,"old".toByteArray(),32,true);ops.writeAndSync(pending,"new".toByteArray(),32,true)
            val before=requireNotNull(ops.stat(pending));ops.atomicReplace(pending,old);ops.syncDirectory(directory)
            check(before.sameFile(requireNotNull(ops.stat(old))) && ops.stat(pending)==null)
            check(Os.lstat(directory.path).st_uid==Os.getuid() && mode(directory)==directoryMode)
            check(Os.lstat(old.path).st_uid==Os.getuid() && mode(old)==fileMode)
            ops.writeAndSync(pending,"pending".toByteArray(),32,true)
            Os.chmod(directory.path,0x140) // 0500: force a real public Os.rename EACCES/EPERM.
            try { ops.atomicReplace(pending,old);error("Rename incorrectly accepted readonly directory") }
            catch (error: ErrnoException) { check(error.errno==OsConstants.EACCES || error.errno==OsConstants.EPERM);renameDenied=true }
            finally { ops.ensurePrivateDirectory(directory) }
            check(String(requireNotNull(ops.read(old,32)))=="new" && String(requireNotNull(ops.read(pending,32)))=="pending")
            val link=File(directory,"link");Os.symlink(old.path,link.path)
            try { ops.read(link,32);error("Followed storage symlink") } catch (_: IOException) { symlinkRejected=true }
            Os.remove(link.path)
            val hard=File(directory,"hard");Os.link(old.path,hard.path)
            try { ops.read(old,32);error("Accepted linked storage file") } catch (_: IOException) { hardlinkRejected=true }
            Os.remove(hard.path)
            try { ops.read(old,2);error("Read past configured byte bound") } catch (_: IOException) { boundedReadRejected=true }
            ops.delete(old);ops.delete(pending)
            val frameworkParent=File(directory,"framework-parent");ops.ensurePrivateDirectory(frameworkParent,true)
            Os.chmod(frameworkParent.path,0x1f9) // 0771, matching possible framework app-owned modes.
            val child=File(frameworkParent,"private-child");ops.ensurePrivateDirectory(child,true)
            check(mode(frameworkParent)==0x1f9 && mode(child)==directoryMode)
            check(Os.lstat(frameworkParent.path).st_uid==Os.getuid())
            Os.remove(child.path);ops.ensurePrivateDirectory(frameworkParent);ops.syncDirectory(frameworkParent)
            Os.remove(frameworkParent.path);ops.syncDirectory(directory)
            for (boundary in listOf("file-sync","rename","directory-sync")) {
                val fixture=File(directory,boundary);ops.ensurePrivateDirectory(fixture,true)
                fun data(title: String)=JSONObject().put("version",6).put("termine",org.json.JSONArray().put(JSONObject().put("id","fixture").put("titel",title)))
                    .put("aufgaben",org.json.JSONArray()).put("kontakte",org.json.JSONArray()).put("notizen",org.json.JSONArray()).put("einstellungen",JSONObject().put("fixture",true))
                val original=Vault(fixture,{key},fileOps=ops);val first=original.openSession().session;original.activate(first)
                original.save(first,data("old").toString(),org.json.JSONArray())
                val fault=Vault(fixture,{key},checkpoint={if(it==boundary)throw IOException("INSTRUMENTATION_STORAGE_CHECKPOINT")},fileOps=ops)
                val session=fault.openSession().session;fault.activate(session)
                try { fault.save(session,data("new").toString(),org.json.JSONArray());error("Faulty durable save acknowledged") }
                catch (error: CommitFailure) {
                    check(error.outcome==if(boundary=="file-sync")"before-commit" else if(boundary=="rename")"uncertain" else "committed")
                }
                if(boundary!="file-sync")check(!fault.isWritable(session))
                val reopened=Vault(fixture,{key},fileOps=ops)
                val value=requireNotNull(reopened.read()).getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel")
                check(value==if(boundary=="file-sync")"old" else "new")
                for(file in ops.children(fixture))check(ops.delete(file))
                Os.remove(fixture.path);ops.syncDirectory(directory);checkpoints++
            }
            check(renameDenied && symlinkRejected && hardlinkRejected && boundedReadRejected && checkpoints==3)
            return JSONObject().put("backend","android.system.Os").put("api",android.os.Build.VERSION.SDK_INT)
                .put("ownerUidVerified",true).put("directory0700",true).put("file0600",true)
                .put("realDirectoryFsync",true).put("atomicInodeMoved",true).put("readonlyDirectoryRenameRejected",renameDenied)
                .put("nofollowSymlinkRejected",symlinkRejected).put("hardlinkRejected",hardlinkRejected)
                .put("boundedReadRejected",boundedReadRejected).put("vaultDurabilityCheckpoints",checkpoints)
                .put("frameworkOwnedParent0771Preserved",true)
                .put("fixtureParentUid",Os.lstat(parent.parentFile!!.path).st_uid)
                .put("fixtureParentMode",Os.lstat(parent.parentFile!!.path).st_mode and 0x1ff)
        } catch(failure:Throwable) { originalFailure=failure; throw failure }
        finally { cleanupPreservingFailure(originalFailure) {
            ops.ensurePrivateDirectory(directory)
            val remaining=ops.children(directory)
            check(remaining.isEmpty()) { "Unexpected file in storage fixture; remainingCount=${remaining.size}" }
            Os.remove(directory.path);ops.syncDirectory(parent)
        } }
    }

    private fun accountChecks(context: Context): JSONObject {
        val root = ops.ensurePrivateDirectory(context.noBackupFilesDir)
        check(ops.stat(File(root,"nextcloud.json")) == null) { "Existing native account: refusing fixture mutation" }
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
        check(ops.stat(fixture) == null) { "Fixture directory already exists" }
        ops.ensurePrivateDirectory(fixture,create=true)
        val secret1 = "native-only-first-$token"
        val secret2 = "native-only-second-$token"
        var failMetadataOnce = false
        var result: JSONObject? = null
        var originalFailure:Throwable?=null
        try {
            val configuration = DavAccountFileStore(fixture,checkpoint={ stage ->
                if (failMetadataOnce && stage == "directory-sync") { failMetadataOnce=false; throw DavAccountException("native_operation_failed") }
            },fileOps=ops)
            val service = DavAccountService(configuration,credentials,BoundedHttpTransport { _, _ -> error("Real network forbidden in native account fixture") })
            val initial = service.status()
            check(initial.configuration == null && initial.revision != null)
            val saved = service.save(initial.revision!!,first,secret1)
            check(saved.configuration == first && saved.credentialPresent == true && !saved.connectivityChecked)
            check(saved.revision != initial.revision && mode(fixture) == directoryMode && mode(configuration.file) == fileMode)
            val encrypted = File(File(root,"dav-credentials-v1"),first.identity.storageKey + ".enc")
            val credentialBytes = requireNotNull(ops.read(encrypted,DavCredentialStore.MAX_SECRET_BYTES + 1024))
            check(mode(encrypted) == fileMode && credentialBytes.isNotEmpty() &&
                ops.stat(encrypted)!!.owner == Os.getuid().toLong() && ops.stat(root)!!.owner == Os.getuid().toLong())
            check(!String(credentialBytes,Charsets.ISO_8859_1).contains(secret1)) { "Credential stored in plaintext" }
            check(!configuration.file.readText().contains(secret1) && !JSONObject(saved.payload()).toString().contains(secret1)) { "Credential leaked into metadata" }
            val key = keyStore.getKey(ALIAS,null) as? SecretKey
            check(key != null && key.encoded == null && key.format == null && key.algorithm == "AES") { "Native account key must be non-exportable" }
            val reopened = DavAccountService(DavAccountFileStore(fixture,fileOps=ops),credentials,
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
                .put("credentialDeletionVerified",true).put("storage",storageChecks(fixture,requireNotNull(key)))
                .put("noBackupRootMode",mode(root)).put("frameworkDataParentMode",mode(root.parentFile!!))
                .put("frameworkDataParentUid",Os.lstat(root.parentFile!!.path).st_uid)
        } catch(failure:Throwable) { originalFailure=failure; throw failure }
        finally { cleanupPreservingFailure(originalFailure) {
            // Only the two previously absent UUID-bound fixture identities may be removed.
            credentials.delete(first.identity); credentials.delete(second.identity)
            check(credentials.read(first.identity) == null && credentials.read(second.identity) == null)
            val metadata = File(fixture,"nextcloud.json")
            ops.delete(metadata)
            val remaining=ops.children(fixture)
            check(remaining.isEmpty()) { "Unexpected file in owned fixture; refusing recursive deletion; remainingCount=${remaining.size}; storageDirectoryPresent=${remaining.any { it.name=="os-storage" }}" }
            Os.remove(fixture.path);ops.syncDirectory(root)
            val credentialDirectory = File(root,"dav-credentials-v1")
            val remainingCredentials = ops.children(credentialDirectory)
            if (!previousAlias && remainingCredentials.isEmpty()) keyStore.deleteEntry(ALIAS)
            val after = vaultBytes(root)
            check(before.keys == after.keys && before.all { (name, bytes) -> if (bytes == null) after[name] == null else after[name]?.let { bytes.contentEquals(it) } == true }) { "Account fixture altered vault bytes" }
            check(ops.stat(File(root,"nextcloud.json")) == null) { "Account fixture created production metadata" }
        } }
        return requireNotNull(result).put("fixtureCredentialsRemoved",true).put("fixtureMetadataRemoved",true).put("vaultBytesPreserved",true)
    }
}
