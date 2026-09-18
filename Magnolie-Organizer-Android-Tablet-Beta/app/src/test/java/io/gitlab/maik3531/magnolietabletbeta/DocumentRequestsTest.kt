package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.Timeout
import java.nio.file.Files
import javax.crypto.KeyGenerator

class DocumentRequestsTest {
    @get:Rule val deadline: Timeout = Timeout.seconds(30)
    private val pageA = DocumentSession("page-A","revision-A")
    private val pageB = DocumentSession("page-B","revision-B")

    @Test fun lateCancelledPickerDoesNotConsumeNewPagesPicker() {
        val requests=DocumentRequests()
        val old=requests.begin(false,1,pageA)
        requests.cancel()
        val current=requests.begin(false,2,pageB)
        assertNull(requests.take(old.code,2,pageB))
        assertEquals(current,requests.take(current.code,2,pageB))
        assertNull(requests.take(current.code,2,pageB))
    }

    @Test fun resultRejectsChangedPageRevisionAndDestroyedHost() {
        for ((generation,session) in listOf(2 to pageA, 1 to pageB,
            1 to pageA.copy(revision="saved-again"), 1 to null)) {
            val requests=DocumentRequests()
            val request=requests.begin(false,1,pageA)
            assertNull(requests.take(request.code,generation,session))
            assertNull(requests.take(request.code,1,pageA))
        }
    }

    @Test fun recreatedActivityNeverReusesPendingRequestCode() {
        val old=DocumentRequests()
        val request=old.begin(true,1,pageA)
        val recreated=DocumentRequests(old.nextCode)
        val current=recreated.begin(false,1,pageB)
        assertNotEquals(request.code,current.code)
        assertNull(recreated.take(request.code,1,pageB))
        assertFalse(recreated.take(current.code,1,pageB)!!.export)
    }

    @Test fun selectedImportCannotBeReauthorizedAgainstNewVaultPage() {
        val dir=Files.createTempDirectory("tablet-picker-fence").toFile()
        try {
            val key=KeyGenerator.getInstance("AES").apply {init(256)}.generateKey()
            val vault=Vault(dir,{key})
            val original=vault.openSession().session.also {vault.activate(it)}
            val data=JSONObject().put("version",6).put("termine",JSONArray()).put("aufgaben",JSONArray())
                .put("kontakte",JSONArray()).put("notizen",JSONArray()).put("einstellungen",JSONObject().put("regional",JSONObject()))
            val saved=vault.save(original,data.toString(),JSONArray())
            val page=DocumentSession(original.id,saved.getString("revision"))
            val requests=DocumentRequests()
            val picker=requests.begin(false,1,page)
            val selected=requests.take(picker.code,1,page)!!
            val next=vault.openSession().session.also {vault.activate(it)}
            assertNotEquals(page.id,next.id)
            try {
                vault.prepareImport(selected.session,data.toString())
                fail("Late provider bytes must not authorize an import on the replacement page")
            } catch (_: IllegalStateException) { }
            assertTrue(vault.isWritable(next))
            assertTrue(data.similar(vault.read()!!.getJSONObject("data")))
        } finally {dir.deleteRecursively()}
    }
}
