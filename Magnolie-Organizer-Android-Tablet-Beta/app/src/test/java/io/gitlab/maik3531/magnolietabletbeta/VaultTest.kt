package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.Rule
import org.junit.rules.Timeout
import java.nio.file.Files
import javax.crypto.KeyGenerator

class VaultTest {
    @get:Rule val deadline: Timeout = Timeout.seconds(30)
    private fun key() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private fun data(title: String = "Test") = JSONObject().put("version",6)
        .put("termine",JSONArray().put(JSONObject().put("id","one").put("titel",title)))
        .put("aufgaben",JSONArray()).put("kontakte",JSONArray()).put("notizen",JSONArray())
        .put("einstellungen",JSONObject().put("regional",JSONObject().put("language","en")))
    private fun alarm(custom: Boolean = false) = JSONObject().put("id","a").put("at",100000L)
        .put("title","Private task").put("section","aufgaben").put("custom",custom)
    private fun reject(block: () -> Unit) { try { block(); fail("Must reject") } catch (_: Exception) {} }
    private fun Vault.session(): DocumentSession = openSession().session.also { activate(it) }
    // Unrelated primitive tests explicitly start a new loaded/acknowledged page per operation.
    private fun Vault.save(text: String, alarms: JSONArray): JSONObject = save(session(),text,alarms)
    private fun Vault.replace(text: String) { val page=session(); replace(page,prepareImport(page,text)) }

    @Test fun encryptedRoundtripAndFreshNonce() {
        val dir=Files.createTempDirectory("tablet-test").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key})
            assertNull(vault.read())
            vault.save(data("private-calendar-title").toString(),JSONArray())
            val first=dir.resolve("tablet-vault.enc").readBytes()
            assertFalse(String(first).contains("private-calendar-title"))
            assertEquals("private-calendar-title",vault.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
            vault.save(data("private-calendar-title").toString(),JSONArray())
            assertFalse(first.contentEquals(dir.resolve("tablet-vault.enc").readBytes()))
        } finally { dir.deleteRecursively() }
    }
    @Test fun corruptionAndMissingKeyNeverProduceEmptyState() {
        val dir=Files.createTempDirectory("tablet-test").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key}); vault.save(data().toString(),JSONArray())
            reject { Vault(dir,{key()}).read() }
            val file=dir.resolve("tablet-vault.enc")
            file.writeBytes(file.readBytes().also {it[it.lastIndex]=(it.last().toInt() xor 1).toByte()})
            reject { vault.read() }
        } finally { dir.deleteRecursively() }
    }
    @Test fun everyDurabilityFailureWithholdsSuccessAndLeavesACompleteVersion() {
        for (boundary in listOf("file-sync","rename","directory-sync")) {
            val dir=Files.createTempDirectory("tablet-test").toFile()
            try {
                val key=key(); val vault=Vault(dir,{key}); vault.save(data("old").toString(),JSONArray())
                reject { Vault(dir,{key},{if(it==boundary) error("injected I/O failure")})
                    .save(data("new").toString(),JSONArray()) }
                val actual=vault.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel")
                assertEquals(if(boundary=="file-sync") "old" else "new",actual)
            } finally {dir.deleteRecursively()}
        }
    }
    @Test fun interruptedFirstWriteIsNotTreatedAsFirstLaunch() {
        val dir=Files.createTempDirectory("tablet-test").toFile()
        try {
            val key=key()
            reject {Vault(dir,{key},{if(it=="file-sync") error("crash")}).save(data().toString(),JSONArray())}
            reject {Vault(dir,{key}).read()}
        } finally {dir.deleteRecursively()}
    }
    @Test fun importKeepsEncryptedBackupAndRevokesAllNotificationConsent() {
        val dir=Files.createTempDirectory("tablet-test").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key}); val state=vault.save(data("old").toString(),JSONArray().put(alarm(true)))
            state.put("enabled",true).put("customEnabled",true); vault.write(state)
            vault.replace(data("new").toString())
            assertTrue(dir.resolve("before-import.enc").length()>0)
            assertFalse(String(dir.resolve("before-import.enc").readBytes()).contains("old"))
            assertFalse(vault.read()!!.getBoolean("enabled")); assertFalse(vault.read()!!.getBoolean("customEnabled"))
            assertEquals(0,vault.read()!!.getJSONArray("alarms").length())
        } finally {dir.deleteRecursively()}
    }
    @Test fun portablePasswordRoundtripRejectsWrongPasswordAndTampering() {
        val clear=data("Export beta").toString()
        val sealed=Portable.seal(clear,"a-good-password".toCharArray())
        assertFalse(sealed.contains("Export beta"))
        assertEquals(clear,Portable.open(sealed,"a-good-password".toCharArray()))
        reject {Portable.open(sealed,"a-wrong-password".toCharArray())}
        val obj=JSONObject(sealed); obj.put("iterations",1)
        reject {Portable.open(obj.toString(),"a-good-password".toCharArray())}
        reject {Portable.seal(clear,"short".toCharArray())}
    }
    @Test fun validationBoundsDepthAndRejectsInvalidEncoding() {
        reject {parseObject("{\"a\":"+"[".repeat(65)+"0"+"]".repeat(65)+"}")}
        reject {parseObject("{} trailing")}
        reject {decodeUtf8(byteArrayOf(0xc3.toByte(),0x28))}
        reject {validateData(JSONObject("{\"version\":6,\"termine\":[]}"))}
        assertEquals(6,parseObject(data().toString()).getInt("version"))
    }
    @Test fun backgroundAlarmConsentDeletionReceiptAndExpiry() {
        val state=JSONObject().put("enabled",false).put("customEnabled",false)
            .put("alarms",JSONArray().put(alarm(true))).put("delivered",JSONObject())
        assertTrue(eligibleAlarms(state,100000L).isEmpty())
        state.put("enabled",true)
        assertTrue(eligibleAlarms(state,100000L).isEmpty())
        state.put("customEnabled",true)
        assertEquals(1,eligibleAlarms(state,100000L).size)
        assertTrue(eligibleAlarms(state,100000L+86400001L).isEmpty())
        state.getJSONObject("delivered").put("a",100000L)
        assertTrue(eligibleAlarms(state,100000L).isEmpty())
        state.put("alarms",JSONArray())
        assertTrue(eligibleAlarms(state,100000L).isEmpty())
    }
    @Test fun originAllowlistRejectsRemoteFilesCredentialsAndLookalikes() {
        assertTrue(trustedOrigin("https://appassets.androidplatform.net/assets/web/index.html"))
        assertTrue(trustedOrigin("https://appassets.androidplatform.net:443"))
        for (url in listOf("http://appassets.androidplatform.net", "https://appassets.androidplatform.net.evil.test",
            "https://evil.test", "https://appassets.androidplatform.net:444", "file:///android_asset/index.html",
            "content://provider/doc", "javascript:alert(1)", "https://user@appassets.androidplatform.net",
            "https://appassets.androidplatform.net@evil.test", "https://appassets.androidplatform.net\\@evil.test")) {
            assertFalse(url,trustedOrigin(url))
        }
    }
    @Test fun restorePostRenameFailureMustFenceOldSnapshot() {
        val dir=Files.createTempDirectory("tablet-a2").toFile()
        try {
            val key=key(); var armed=false
            val vault=Vault(dir,{key},{if(armed && it=="rename") {armed=false; error("post-rename failure")}})
            vault.save(data("A").toString(),JSONArray())
            val oldPage=vault.session()
            val token=vault.prepareImport(oldPage,data("B").toString())
            armed=true
            reject {vault.replace(oldPage,token)}
            assertEquals("B",vault.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
            reject {vault.save(oldPage,data("A").toString(),JSONArray())}
            assertEquals("B",vault.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
        } finally {dir.deleteRecursively()}
    }
    @Test fun restoreOutcomesFenceEveryCheckpointAndRequireVerifiedReload() {
        for ((boundary,outcome,title) in listOf(Triple("backup-sync","before-commit","A"),
            Triple("file-sync","before-commit","A"),Triple("rename","uncertain","B"),
            Triple("directory-sync","committed","B"),Triple("commit-readback","committed","B"))) {
            val dir=Files.createTempDirectory("tablet-a2-boundary").toFile()
            try {
                val key=key(); var armed=false
                val vault=Vault(dir,{key},{if(armed && it==boundary) {armed=false; error("injected $boundary")}})
                vault.save(data("A").toString(),JSONArray())
                val page=vault.session()
                val token=vault.prepareImport(page,data("B").toString())
                armed=true
                try {vault.replace(page,token); fail("Must fail at $boundary")}
                catch(e: CommitFailure) {assertEquals(outcome,e.outcome)}
                reject {vault.save(page,data("A").toString(),JSONArray())}
                reject {vault.cancelImport(page,token)}
                val loaded=vault.openSession()
                assertEquals(title,loaded.value!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
                reject {vault.save(loaded.session,data("A").toString(),JSONArray())}
                vault.activate(loaded.session)
                assertTrue(vault.isWritable(loaded.session))
                assertNotEquals(page.id,loaded.session.id)
                reject {vault.save(page,data("A").toString(),JSONArray())}
            } finally {dir.deleteRecursively()}
        }
    }
    @Test fun closedFileChannelAtDirectorySyncPoisonsPublishedRestoreOnHostJvm() {
        val dir=Files.createTempDirectory("tablet-a2-channel").toFile()
        try {
            val key=key(); var armed=false
            val vault=Vault(dir,{key},syncDirectory={directory ->
                val channel=java.nio.channels.FileChannel.open(directory.toPath(),java.nio.file.StandardOpenOption.READ)
                channel.use {if(armed) {armed=false; it.close()}; it.force(true)}
            })
            vault.save(data("A").toString(),JSONArray()); val page=vault.session()
            val token=vault.prepareImport(page,data("B").toString()); armed=true
            try {vault.replace(page,token); fail("Expected channel failure")}
            catch(e: CommitFailure) {assertEquals("uncertain",e.outcome); assertTrue(e.cause is java.nio.channels.ClosedChannelException)}
            reject {vault.save(page,data("A").toString(),JSONArray())}
            assertEquals("B",vault.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
        } finally {dir.deleteRecursively()}
    }
    @Test fun nativeImportTokenBindsSelectedBytesSessionAndLatestRevision() {
        val dir=Files.createTempDirectory("tablet-a2-authorization").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key}); vault.save(data("A").toString(),JSONArray())
            val page=vault.session()
            val imported=data("B").put("session",page.id).put("revision",page.revision)
                .put("token","file-supplied-token")
                .put("unknownScalar","retain me").put("nested",JSONObject("{\"rows\":[[1,null,false],{\"children\":[{\"label\":\"leaf\",\"values\":[\"x\",2]}]}]}"))
            val token=vault.prepareImport(page,imported.toString())
            reject {vault.replace(page,"file-supplied-token")}
            val stale=page
            vault.save(page,data("A2").toString(),JSONArray())
            reject {vault.replace(stale,token)}
            val current=vault.session(); val currentToken=vault.prepareImport(current,imported.toString())
            reject {vault.replace(DocumentSession("another-activity",current.revision),currentToken)}
            val result=vault.replace(current,currentToken)
            assertTrue(imported.similar(result.getJSONObject("data")))
            assertTrue(imported.similar(vault.read()!!.getJSONObject("data")))
            assertNotEquals(current.revision,result.getString("revision"))
            reject {vault.save(current,data("A").toString(),JSONArray())}
            reject {vault.replace(current,currentToken)}
            val recreated=Vault(dir,{key}); val loaded=recreated.openSession()
            assertNotEquals(current.id,loaded.session.id)
            reject {recreated.activate(current)}
            recreated.activate(loaded.session)
            assertTrue(imported.similar(loaded.value!!.getJSONObject("data")))
            assertFalse(loaded.value.getBoolean("enabled")); assertFalse(loaded.value.getBoolean("customEnabled"))
        } finally {dir.deleteRecursively()}
    }
    @Test fun cancellationBeforeCommitKeepsOldPageButCannotAuthorizeRestore() {
        val dir=Files.createTempDirectory("tablet-a2-cancel").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key}); vault.save(data("A").toString(),JSONArray())
            val page=vault.session(); val token=vault.prepareImport(page,data("B").toString())
            vault.cancelImport(page,token)
            assertTrue(vault.isWritable(page)); reject {vault.replace(page,token)}
            vault.save(page,data("A edited").toString(),JSONArray())
        } finally {dir.deleteRecursively()}
    }
    @Test fun successfulRestoreFollowupFailureNeverRestoresOldSaveAuthority() {
        val dir=Files.createTempDirectory("tablet-a2-followup").toFile()
        try {
            val key=key(); val vault=Vault(dir,{key}); vault.save(data("A").toString(),JSONArray())
            val page=vault.session(); val token=vault.prepareImport(page,data("B").toString())
            val result=vault.replace(page,token)
            reject {error("simulated notification scheduler unavailable")}
            reject {vault.save(page,data("A").toString(),JSONArray())}
            assertTrue(result.getJSONObject("data").similar(vault.openSession().value!!.getJSONObject("data")))
        } finally {dir.deleteRecursively()}
    }
    @Test fun actualEditorAlarmVectorsReachNativeConsentAndReceiptGate() {
        val root=java.io.File(requireNotNull(System.getProperty("tablet.root")))
        val proof=JSONObject(root.resolve("artifacts/a3-editor-vectors.json").readText())
        val projection=JSONObject(root.resolve("app/build/generated/projection/assets/projection.json").readText())
        assertEquals(projection.getString("sourceHash"),proof.getString("sourceHash"))
        val cases=proof.getJSONArray("cases")
        for(i in 0 until cases.length()) {
            val case=cases.getJSONObject(i); val alarms=case.getJSONArray("alarms")
            if(alarms.length()==0) continue
            val time=alarms.getJSONObject(0).getLong("at")
            val value=JSONObject().put("enabled",true).put("customEnabled",true)
                .put("delivered",JSONObject()).put("alarms",alarms)
            assertEquals(case.getString("name"),alarms.length(),eligibleAlarms(value,time).size)
            value.put("enabled",false); assertTrue(eligibleAlarms(value,time).isEmpty())
            value.put("enabled",true).put("customEnabled",false)
            if(alarms.getJSONObject(0).getBoolean("custom")) assertTrue(eligibleAlarms(value,time).isEmpty())
            else assertEquals(alarms.length(),eligibleAlarms(value,time).size)
            value.put("customEnabled",true)
            val first=alarms.getJSONObject(0).getString("id")
            value.getJSONObject("delivered").put(first,time)
            assertEquals(alarms.length()-1,eligibleAlarms(value,time).size)
        }
    }
}
