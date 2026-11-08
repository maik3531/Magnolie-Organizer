package io.gitlab.maik3531.magnolietabletbeta

import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import javax.crypto.KeyGenerator
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class StorageFileOpsTest {
    private val ops = NioStorageFileOps
    private fun directory(test: (File) -> Unit) {
        val dir = Files.createTempDirectory("storage-fileops-test").toFile()
        try { test(dir) } finally { dir.deleteRecursively() }
    }
    private fun reject(action: () -> Unit) {
        try { action(); fail("Expected filesystem failure") } catch (_: IOException) { }
    }
    private fun key() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private fun data(title: String) = JSONObject().put("version",6).put("termine",JSONArray().put(JSONObject().put("id","one").put("titel",title)))
        .put("aufgaben",JSONArray()).put("kontakte",JSONArray()).put("notizen",JSONArray()).put("einstellungen",JSONObject().put("fixture",true))
    private fun Vault.save(title: String) {
        val session = openSession().session; activate(session); save(session,data(title).toString(),JSONArray())
    }
    @Test fun privateModesCheckedAtomicReplacementAndRealDirectorySync() = directory { dir ->
        ops.ensurePrivateDirectory(dir)
        val old = dir.resolve("record.enc"); val next = dir.resolve("record.pending")
        ops.writeAndSync(old,"old".toByteArray(),32,true)
        ops.writeAndSync(next,"new".toByteArray(),32,true)
        val before = ops.stat(next)!!
        ops.atomicReplace(next,old); ops.syncDirectory(dir)
        assertTrue(before.sameFile(ops.stat(old)!!)); assertNull(ops.stat(next))
        assertEquals("new",String(ops.read(old,32)!!))
        assertEquals(0x1c0,ops.stat(dir)!!.mode and 0x1ff)
        assertEquals(0x180,ops.stat(old)!!.mode and 0x1ff)
        assertTrue(ops.delete(old)); ops.syncDirectory(dir); assertFalse(ops.delete(old))
    }
    @Test fun childCreationSyncsOwnedFrameworkStyleParentWithoutChangingItsMode() = directory { dir ->
        Files.setPosixFilePermissions(dir.toPath(),PosixFilePermissions.fromString("rwxrwx--x"))
        val child=dir.resolve("private-child")
        ops.ensurePrivateDirectory(child,true)
        assertEquals(0x1f9,ops.stat(dir)!!.mode and 0x1ff)
        assertEquals(0x1c0,ops.stat(child)!!.mode and 0x1ff)
        ops.ensurePrivateDirectory(dir)
    }
    @Test fun nofollowHardlinkAndBoundedReadWriteGuardsPreserveOriginals() = directory { dir ->
        val original = dir.resolve("original")
        ops.writeAndSync(original,"untouched".toByteArray(),32,true)
        val link = dir.resolve("link")
        Files.createSymbolicLink(link.toPath(),original.toPath())
        reject { ops.read(link,32) }; reject { ops.writeAndSync(link,"changed".toByteArray(),32) }
        reject { ops.delete(link) }
        assertEquals("untouched",String(ops.read(original,32)!!))
        val hardlink = dir.resolve("hard")
        Files.createLink(hardlink.toPath(),original.toPath())
        reject { ops.read(original,32) }; reject { ops.writeAndSync(hardlink,"changed".toByteArray(),32) }
        Files.delete(hardlink.toPath())
        reject { ops.read(original,2) }
        try { ops.writeAndSync(original,ByteArray(33),32); fail("Expected byte limit") } catch (_: IllegalArgumentException) { }
        assertEquals("untouched",String(ops.read(original,32)!!))
        reject { ops.writeAndSync(original,"changed".toByteArray(),32,true) }
        assertEquals("untouched",String(ops.read(original,32)!!))
    }
    @Test fun failedAtomicMoveNeverLooksLikeSuccessfulReplacement() = directory { dir ->
        val original = dir.resolve("original")
        ops.writeAndSync(original,"old".toByteArray(),32,true)
        reject { ops.atomicReplace(dir.resolve("missing"),original) }
        assertEquals("old",String(ops.read(original,32)!!))
        val directoryDestination = dir.resolve("directory"); ops.ensurePrivateDirectory(directoryDestination,true)
        val pending = dir.resolve("pending"); ops.writeAndSync(pending,"pending".toByteArray(),32,true)
        reject { ops.atomicReplace(pending,directoryDestination) }
        assertEquals("pending",String(ops.read(pending,32)!!))
    }
    @Test fun vaultRenameFailureWithholdsAckAndRetainsOriginalAfterReopen() = directory { dir ->
        val key=key(); Vault(dir,{key},fileOps=ops).save("old")
        val failing = object : StorageFileOps by ops {
            override fun atomicReplace(source: File,destination: File) { throw IOException("synthetic checked rename failure") }
        }
        val vault=Vault(dir,{key},fileOps=failing)
        try { vault.save("new"); fail("Expected commit failure") } catch (failure: CommitFailure) { assertEquals("uncertain",failure.outcome) }
        assertEquals("old",Vault(dir,{key},fileOps=ops).read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
    }
    @Test fun vaultDirectoryFailurePoisonsSessionUntilARealBarrierCompletes() = directory { dir ->
        val key=key(); Vault(dir,{key},fileOps=ops).save("old")
        var armed=false
        val failing=object : StorageFileOps by ops {
            override fun syncDirectory(directory: File) { if(armed) throw IOException("synthetic directory fsync failure"); ops.syncDirectory(directory) }
        }
        val vault=Vault(dir,{key},fileOps=failing)
        val session=vault.openSession().session; vault.activate(session); armed=true
        try { vault.save(session,data("new").toString(),JSONArray()); fail("Expected commit failure") } catch (failure: CommitFailure) { assertEquals("uncertain",failure.outcome) }
        assertFalse(vault.isWritable(session))
        val reopened=Vault(dir,{key},fileOps=ops); assertEquals("new",reopened.read()!!.getJSONObject("data").getJSONArray("termine").getJSONObject(0).getString("titel"))
        val loaded=reopened.openSession(); reopened.activate(loaded.session); assertTrue(reopened.isWritable(loaded.session))
    }
    @Test fun credentialAndConfigStoresUseTheInjectedBackendForEveryBarrier() = directory { dir ->
        val key=key(); val events=mutableListOf<String>()
        val tracked=object : StorageFileOps by ops {
            override fun writeAndSync(file: File,bytes: ByteArray,maximumBytes: Int,exclusive: Boolean) { events.add("write:"+file.name);ops.writeAndSync(file,bytes,maximumBytes,exclusive) }
            override fun atomicReplace(source: File,destination: File) { events.add("rename:"+destination.name);ops.atomicReplace(source,destination) }
            override fun syncDirectory(directory: File) { events.add("directory:"+directory.name);ops.syncDirectory(directory) }
        }
        val identity=DavCredentialIdentity("https://fixture.example","fixture")
        val credentials=DavCredentialStore(dir.resolve("credentials"),{key},fileOps=tracked)
        credentials.write(identity,"fixture-secret"); assertEquals("fixture-secret",credentials.read(identity))
        val config=DavAccountFileStore(dir,fileOps=tracked)
        config.replace(DavAccountConfiguration(davEnabled=true,server="https://fixture.example",user="fixture"))
        assertTrue(events.any {it=="rename:nextcloud.json"});assertTrue(events.any {it=="rename:"+identity.storageKey+".enc"})
        assertTrue(events.count {it.startsWith("directory:")} >= 2)
        assertTrue(credentials.delete(identity));config.replace(null)
    }
}
