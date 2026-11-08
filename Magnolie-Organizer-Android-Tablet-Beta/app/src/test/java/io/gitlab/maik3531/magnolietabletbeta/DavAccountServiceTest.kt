package io.gitlab.maik3531.magnolietabletbeta

import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.crypto.KeyGenerator
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.Timeout

private class AccountConfigurationMemory : DavAccountConfigurationStore {
    override val revisionNamespace = "fixture-store"
    var value: DavAccountConfiguration? = null
    var failAfterReplaceOnce = false
    var failEveryReplace = false
    override fun read() = value
    override fun replace(configuration: DavAccountConfiguration?) {
        if (failEveryReplace) throw DavAccountException("native_operation_failed")
        value = configuration
        if (failAfterReplaceOnce) { failAfterReplaceOnce = false; throw DavAccountException("native_operation_failed") }
    }
}
private class AccountCredentialMemory : DavAccountCredentials {
    val items = mutableMapOf<String, String>()
    var failAfterWriteOnce = false
    var failAfterDeleteOnce = false
    var locked = false
    override fun read(identity: DavCredentialIdentity): String? {
        if (locked) throw DavCredentialException("credential_unavailable")
        return items[identity.storageKey]
    }
    override fun write(identity: DavCredentialIdentity, secret: String) {
        if (locked) throw DavCredentialException("credential_unavailable")
        items[identity.storageKey] = secret
        if (failAfterWriteOnce) { failAfterWriteOnce = false; throw DavCredentialException("credential_unavailable") }
    }
    override fun delete(identity: DavCredentialIdentity): Boolean {
        if (locked) throw DavCredentialException("credential_unavailable")
        val existed = items.remove(identity.storageKey) != null
        if (failAfterDeleteOnce) { failAfterDeleteOnce = false; throw DavCredentialException("credential_unavailable") }
        return existed
    }
}
private class AccountTransportScript(vararg responses: BoundedHttpResponse) : BoundedHttpTransport {
    val requests = mutableListOf<BoundedHttpRequest>()
    private val responses = responses.toMutableList()
    override fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse {
        requests.add(request)
        if (responses.isEmpty()) throw DavException("invalid_response")
        return responses.removeAt(0)
    }
}

class DavAccountServiceTest {
    @get:Rule val deadline: Timeout = Timeout.seconds(15)
    private fun config(server: String = "https://cloud.example/nextcloud", user: String = "person", active: Boolean = true) =
        DavAccountConfiguration(davEnabled = active, server = server, user = user)
    private fun expect(code: String, action: () -> Unit) {
        try { action(); fail("Expected account failure") }
        catch (error: DavAccountException) { assertEquals(code, error.code) }
    }
    private fun xml(content: String) = BoundedHttpResponse(207, body = ("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:a='urn:ietf:params:xml:ns:carddav'>$content</d:multistatus>").toByteArray())
    private fun row(href: String, props: String) = "<d:response><d:href>$href</d:href><d:propstat><d:prop>$props</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    private fun replies() = listOf(
        xml(row("/.well-known/caldav", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>")),
        xml(row("/calendars/person/personal/", "<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>Personal</d:displayname>")),
        xml(row("/.well-known/carddav", "<a:addressbook-home-set><d:href>/addressbooks/person/</d:href></a:addressbook-home-set>")),
        xml(row("/addressbooks/person/contacts/", "<d:resourcetype><a:addressbook/></d:resourcetype><d:displayname>Contacts</d:displayname>")))
    private fun directory(action: (File) -> Unit) {
        val dir = Files.createTempDirectory("dav-account-test").toFile()
        try { action(dir) } finally { dir.deleteRecursively() }
    }
    @Test fun canonicalAndLegacyShapesRejectSecretsWrongTypesAndMailboxMismatch() {
        val wanted = config()
        assertEquals(wanted, DavAccountConfiguration.fromCanonicalMap(wanted.toCanonicalMap()))
        val legacy = DavAccountConfiguration.fromCanonicalMap(mapOf("aktiv" to false, "server" to "https://CLOUD.example:443/nextcloud/", "benutzer" to " person "))
        assertEquals(wanted.server, legacy.server); assertFalse(legacy.davEnabled)
        for (changes in listOf(mapOf("appKennwort" to "never-persist"), mapOf("davAktiv" to 1), mapOf("kontoArt" to 1), mapOf("kontoArt" to "unknown"))) {
            expect("invalid_config") { DavAccountConfiguration.fromCanonicalMap(wanted.toCanonicalMap() + changes) }
        }
        expect("invalid_config") { DavAccountConfiguration(DavAccountType.GENERIC_DAV, true, true, wanted.server, wanted.user) }
    }
    @Test fun metadataAndSaveReceiptContainNoSecretAndDoNotClaimConnectivity() {
        val config = AccountConfigurationMemory(); val secrets = AccountCredentialMemory()
        val service = DavAccountService(config, secrets)
        val initial = service.status()
        assertEquals("nicht_eingerichtet", initial.state); assertTrue(initial.revision!!.matches(Regex("^[a-f0-9]{64}$")))
        val wanted = config()
        val saved = service.save(initial.revision, wanted, "fixture-app-password")
        assertEquals(wanted, config.value); assertEquals(true, saved.credentialPresent)
        assertNotEquals(initial.revision, saved.revision); assertFalse(saved.connectivityChecked)
        val payload = saved.payload("request-1", true)
        assertEquals(true, payload["persisted"]); assertEquals(true, payload["verified"])
        assertEquals("request-1", payload["requestId"])
        val publicJSON = JSONObject(payload).toString()
        assertFalse(publicJSON.contains("fixture-app-password")); assertFalse(publicJSON.contains("Authorization"))
        assertFalse(publicJSON.contains("synced")); assertFalse(wanted.toCanonicalMap().containsKey("password"))
    }
    @Test fun keyedRevisionsFenceExternalCredentialChangesAndDifferAcrossSessions() {
        val config = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[config.value!!.identity.storageKey] = "first-fixture-secret"
        val first = DavAccountService(config, secrets); val second = DavAccountService(config, secrets)
        val one = first.status(); assertNotEquals(one.revision, second.status().revision)
        secrets.items[config.value!!.identity.storageKey] = "externally-replaced-fixture-secret"
        assertNotEquals(one.revision, first.status().revision)
        expect("conflict") { first.save(one.revision!!, config.value!!) }
    }
    @Test fun activeEndpointChangeRequiresExplicitPasswordAndPreservesPreviousContext() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        val old = store.value!!; secrets.items[old.identity.storageKey] = "old-fixture-secret"
        val service = DavAccountService(store, secrets); val before = service.status()
        val wanted = config(server = "https://other.example")
        expect("app_password_missing") { service.save(before.revision!!, wanted) }
        assertEquals(old, store.value); assertEquals(mapOf(old.identity.storageKey to "old-fixture-secret"), secrets.items)
        val saved = service.save(before.revision!!, wanted, "new-fixture-secret")
        assertEquals(wanted, saved.configuration); assertNull(secrets.items[old.identity.storageKey])
        assertEquals("new-fixture-secret", secrets.read(wanted.identity))
    }
    @Test fun clearPasswordRequiresDisabledServicesAndKeepsConfiguration() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
        val service = DavAccountService(store, secrets); val before = service.status()
        expect("invalid_config") { service.save(before.revision!!, store.value!!, clearPassword = true) }
        expect("invalid_config") { service.save(before.revision!!, config(active = false), applicationPassword = "new", clearPassword = true) }
        val disabled = config(active = false)
        val saved = service.save(before.revision!!, disabled, clearPassword = true)
        assertEquals(disabled, store.value); assertEquals(false, saved.credentialPresent); assertEquals("aus", saved.state)
        assertTrue(secrets.items.isEmpty())
    }
    @Test fun failedCredentialAndConfigurationWritesRollBackCompletePreviousContext() {
        for (credentialFailure in listOf(false, true)) {
            val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
            val old = store.value!!; secrets.items[old.identity.storageKey] = "old-fixture-secret"
            val service = DavAccountService(store, secrets); val before = service.status()
            store.failAfterReplaceOnce = !credentialFailure; secrets.failAfterWriteOnce = credentialFailure
            try { service.save(before.revision!!, config(server = "https://other.example"), "new-fixture-secret"); fail("Expected injected failure") }
            catch (_: DavAccountException) { } catch (_: DavCredentialException) { }
            assertEquals(old, store.value); assertEquals(mapOf(old.identity.storageKey to "old-fixture-secret"), secrets.items)
            assertEquals(before.revision, service.status().revision); assertEquals("none", service.status().errorCode)
        }
    }
    @Test fun failedOldCredentialDeletionRestoresOldConfigurationAndBothCredentialStates() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        val old = store.value!!; secrets.items[old.identity.storageKey] = "old-fixture-secret"
        val service = DavAccountService(store, secrets); val before = service.status()
        secrets.failAfterDeleteOnce = true
        try { service.save(before.revision!!, config(server = "https://other.example"), "new-fixture-secret"); fail("Expected delete failure") }
        catch (_: DavCredentialException) { }
        assertEquals(old, store.value); assertEquals(mapOf(old.identity.storageKey to "old-fixture-secret"), secrets.items)
    }
    @Test fun failedInitialSetupRestoresAbsentConfigurationAndNoCredential() {
        val store = AccountConfigurationMemory(); val secrets = AccountCredentialMemory()
        val service = DavAccountService(store, secrets); val before = service.status()
        store.failAfterReplaceOnce = true
        expect("native_operation_failed") { service.save(before.revision!!, config(), "fixture-secret") }
        assertNull(store.value); assertTrue(secrets.items.isEmpty())
    }
    @Test fun unverifiableRollbackPoisonsFurtherMutationsAndDoesNotPublishRevision() {
        val store = AccountConfigurationMemory(); val secrets = AccountCredentialMemory()
        val service = DavAccountService(store, secrets); val before = service.status()
        store.failEveryReplace = true
        expect("verification_failed") { service.save(before.revision!!, config(), "fixture-secret") }
        val after = service.status()
        assertNull(after.revision); assertNull(after.credentialPresent); assertEquals("verification_failed", after.errorCode)
        expect("verification_failed") { service.save(before.revision!!, config(), "fixture-secret") }
    }
    @Test fun lockedCredentialsAndUnsupportedMailboxCannotPretendToBeSuccessful() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        val service = DavAccountService(store, secrets)
        secrets.locked = true
        val locked = service.status()
        assertNull(locked.revision); assertNull(locked.credentialPresent); assertEquals("secret_service_unavailable", locked.errorCode)
        secrets.locked = false
        val before = service.status()
        val mailbox = DavAccountConfiguration(davEnabled = true, mailboxEnabled = true, server = "https://cloud.example", user = "person")
        expect("unsupported_feature") { service.save(before.revision!!, mailbox, "fixture-secret") }
        assertTrue(secrets.items.isEmpty())
    }
    @Test fun realDiscoveryHasStableSourceBindingsAndPassiveStatusUsesExactRevisionCache() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
        val transport = AccountTransportScript(*replies().toTypedArray())
        val service = DavAccountService(store, secrets, transport); val before = service.status()
        val result = service.discover(before.revision!!)
        assertTrue(result.reachable); assertFalse(result.partial); assertEquals("none", result.status.errorCode)
        assertEquals("nextcloud-calendar:6541706891c0a0615cbaad7ae060941cecf7aec6e453a3ed28f8785050229ae4", result.status.calendars.single().uid)
        assertEquals(1, result.status.addressBooks.size); assertTrue(result.status.connectivityChecked)
        val receipt = result.connectionTestPayload("request-1")
        assertEquals(before.revision, receipt["revision"]); assertEquals(1, receipt["calendars"]); assertFalse(receipt.containsKey("synced"))
        assertEquals(result.status.calendars, service.status().calendars); assertEquals(4, transport.requests.size)
        service.save(before.revision, config(active = false))
        assertTrue(service.status().calendars.isEmpty()); assertFalse(service.status().connectivityChecked)
    }
    @Test fun externalConfigurationCredentialAndLockedStorageChangesInvalidateCache() {
        for (kind in listOf("configuration", "credential", "locked")) {
            val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
            val identity = store.value!!.identity; secrets.items[identity.storageKey] = "fixture-secret"
            val service = DavAccountService(store, secrets, AccountTransportScript(*replies().toTypedArray()))
            val before = service.status(); service.discover(before.revision!!)
            when (kind) {
                "configuration" -> store.value = config(active = false)
                "credential" -> secrets.items[identity.storageKey] = "external-secret"
                "locked" -> secrets.locked = true
            }
            val changed = service.status()
            assertTrue(changed.calendars.isEmpty()); assertTrue(changed.addressBooks.isEmpty()); assertFalse(changed.connectivityChecked)
            if (kind == "locked") {
                assertNull(changed.revision); secrets.locked = false
                assertEquals(before.revision, service.status().revision); assertTrue(service.status().calendars.isEmpty())
            } else assertNotEquals(before.revision, changed.revision)
        }
    }
    @Test fun failedPartialDiscoveryRemainsHonestInPassiveStatusAndNeverChangesConfiguration() {
        for (partial in listOf(false, true)) {
            val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
            secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
            val replies = (if (partial) replies().take(2) else emptyList()) + BoundedHttpResponse(401)
            val service = DavAccountService(store, secrets, AccountTransportScript(*replies.toTypedArray()))
            val before = service.status(); val result = service.discover(before.revision!!)
            assertEquals(partial, result.partial); assertEquals(partial, result.reachable)
            val status = service.status()
            assertEquals("http_401", status.errorCode); assertEquals("fehler", status.state)
            assertEquals(if (partial) 1 else 0, status.calendars.size); assertEquals(before.revision, status.revision)
        }
    }
    /** A real old calendar capability is parsed before its last response is held.
     * New success/error then owns the cache at the unchanged account revision. */
    private fun overlappingDiscovery(oldFailure: String? = null, newerFailure: String? = null) {
        val store=AccountConfigurationMemory().apply {value=config()};val secrets=AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey]="fixture-secret"
        fun capabilities(todo:Boolean)=replies().toMutableList().apply {
            this[1]=xml(row("/calendars/person/personal/","<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>Personal</d:displayname><c:supported-calendar-component-set><c:comp name='VEVENT'/>"+
                (if(todo)"<c:comp name='VTODO'/>" else "")+"</c:supported-calendar-component-set>"))
        }
        val oldEntered=CountDownLatch(1);val oldRelease=CountDownLatch(1)
        val role=ThreadLocal<String>()
        val initial=AccountTransportScript(*capabilities(true).toTypedArray())
        val older=AccountTransportScript(*capabilities(true).toTypedArray())
        val newer=AccountTransportScript(*capabilities(false).toTypedArray())
        var oldCalls=0;var newCalls=0
        val transport=BoundedHttpTransport {request,cancellation ->
            check(request.uri.host=="cloud.example" && request.method=="PROPFIND")
            when(role.get()) {
                "old" -> {
                    val index=oldCalls++
                    val held=if(oldFailure=="empty")0 else if(oldFailure=="partial")2 else 3
                    if(index==held) {
                        oldEntered.countDown();check(oldRelease.await(3,TimeUnit.SECONDS))
                        if(oldFailure!=null) throw DavException("unauthorized")
                    }
                    older.send(request,cancellation)
                }
                "new" -> {
                    val index=newCalls++
                    if(newerFailure=="empty" && index==0 || newerFailure=="partial" && index==2) throw DavException("unauthorized")
                    newer.send(request,cancellation)
                }
                else -> initial.send(request,cancellation)
            }
        }
        val service=DavAccountService(store,secrets,transport);val revision=service.status().revision!!
        check(service.discover(revision).status.calendars.single().supportsVtodo)
        val executor=Executors.newFixedThreadPool(2)
        try {
            val old=executor.submit<String> {
                role.set("old")
                try {service.discover(revision);"unexpected_success"} catch(error:DavAccountException) {error.code}
            }
            assertTrue(oldEntered.await(3,TimeUnit.SECONDS))
            // Accepted refresh clears the old connectivity result before network completion.
            assertFalse(service.status().connectivityChecked);assertTrue(service.status().calendars.isEmpty())
            val current=executor.submit<DavAccountDiscovery> {role.set("new");service.discover(revision)}.get(3,TimeUnit.SECONDS)
            assertEquals(revision,current.status.revision)
            assertEquals(if(newerFailure==null)"none" else "http_401",current.status.errorCode)
            assertEquals(newerFailure=="partial",current.partial)
            if(newerFailure!="empty") assertFalse(current.status.calendars.single().supportsVtodo)
            val expected=service.status().payload()
            oldRelease.countDown()
            assertEquals("conflict",old.get(3,TimeUnit.SECONDS))
            assertEquals(expected,service.status().payload())
            assertEquals(revision,service.status().revision)
            assertTrue(service.status().connectivityChecked)
        } finally {oldRelease.countDown();executor.shutdownNow();assertTrue(executor.awaitTermination(2,TimeUnit.SECONDS))}
    }
    @Test fun olderSuccessCannotOverwriteNewerSameRevisionCapabilities() = overlappingDiscovery()
    @Test fun olderFailureOrPartialResultCannotOverwriteNewerSuccess() {
        overlappingDiscovery(oldFailure="empty");overlappingDiscovery(oldFailure="partial")
    }
    @Test fun olderSuccessCannotHideNewerFailureOrPartialStatus() {
        overlappingDiscovery(newerFailure="empty");overlappingDiscovery(newerFailure="partial")
    }

    @Test fun accountChangeDuringNetworkDiscoveryRejectsLateResults() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
        val entered = CountDownLatch(1); val release = CountDownLatch(1)
        val script = AccountTransportScript(*replies().toTypedArray())
        val gated = BoundedHttpTransport { request, cancellation ->
            if (script.requests.isEmpty()) { entered.countDown(); check(release.await(3, TimeUnit.SECONDS)) }
            script.send(request, cancellation)
        }
        val service = DavAccountService(store, secrets, gated); val before = service.status()
        val executor = Executors.newSingleThreadExecutor()
        try {
            val outcome = executor.submit<String> {
                try { service.discover(before.revision!!); "unexpected_success" }
                catch (error: DavAccountException) { error.code }
            }
            assertTrue(entered.await(3, TimeUnit.SECONDS))
            service.save(before.revision!!, config(active = false))
            release.countDown()
            assertEquals("conflict", outcome.get(3, TimeUnit.SECONDS))
            assertFalse(store.value!!.davEnabled)
        } finally { release.countDown(); executor.shutdownNow() }
    }
    @Test fun cancelledDiscoveryDoesNotSendRequestsOrPublishConnectivity() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
        val transport = AccountTransportScript(*replies().toTypedArray())
        val service = DavAccountService(store, secrets, transport)
        val before = service.status()
        val cancellation = DavCancellation().apply { cancel() }
        try { service.discover(before.revision!!, cancellation); fail("Expected cancellation") }
        catch (_: java.util.concurrent.CancellationException) { }
        assertTrue(transport.requests.isEmpty()); assertEquals(before.revision, service.status().revision)
        assertFalse(service.status().connectivityChecked); assertTrue(service.status().calendars.isEmpty())
    }
    @Test fun sixtySecondDeadlineCoversAllDiscoveryRequestsTogether() {
        val store = AccountConfigurationMemory().apply { value = config() }; val secrets = AccountCredentialMemory()
        secrets.items[store.value!!.identity.storageKey] = "fixture-secret"
        var now = 0L
        val script = AccountTransportScript(*replies().toTypedArray())
        val transport = BoundedHttpTransport { request, cancellation ->
            now += TimeUnit.SECONDS.toNanos(31)
            script.send(request, cancellation)
        }
        val service = DavAccountService(store, secrets, transport, monotonicNanos = { now })
        val result = service.discover(service.status().revision!!)
        assertFalse(result.reachable); assertEquals("timeout", result.status.errorCode)
        assertEquals(2, script.requests.size); assertTrue(script.requests[1].timeoutMillis <= 29_000)
    }
    @Test fun realConfigurationStoreIsPrivateCanonicalAndLeavesOrganizerBytesUntouched() = directory { dir ->
        val organizer = dir.resolve("tablet-vault.enc"); val original = byteArrayOf(4, 5, 6, 7); organizer.writeBytes(original)
        val store = DavAccountFileStore(dir)
        assertNull(store.read()); store.replace(config()); assertEquals(config(), store.read())
        assertEquals(setOf("kontoArt", "davAktiv", "briefkastenAktiv", "server", "benutzer"), JSONObject(store.file.readText()).keys().asSequence().toSet())
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(store.file.toPath())))
        assertArrayEquals(original, organizer.readBytes())
        store.replace(null); assertNull(store.read()); assertArrayEquals(original, organizer.readBytes())
    }
    @Test fun realEncryptedCredentialAndConfigStoresRollBackAfterRenameDirectorySyncFailure() = directory { dir ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val secretDirectory = dir.resolve("credentials")
        val secrets = DavStoredAccountCredentials(DavCredentialStore(secretDirectory, { key }))
        var injected = false; var failStorage = false
        val store = DavAccountFileStore(dir, syncDirectory = {
            if (failStorage && !injected) { injected = true; throw java.io.IOException("synthetic directory fsync error") }
            io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner(it)
        })
        val service = DavAccountService(store, secrets)
        val old = config(); val before = service.save(service.status().revision!!, old, "old-fixture-secret")
        failStorage = true
        try { service.save(before.revision!!, config(server = "https://new.example"), "new-fixture-secret"); fail("Expected I/O failure") }
        catch (_: java.io.IOException) { }
        assertTrue(injected); assertEquals(old, store.read()); assertEquals("old-fixture-secret", secrets.read(old.identity))
        assertNull(secrets.read(config(server = "https://new.example").identity)); assertEquals(before.revision, service.status().revision)
    }
}
