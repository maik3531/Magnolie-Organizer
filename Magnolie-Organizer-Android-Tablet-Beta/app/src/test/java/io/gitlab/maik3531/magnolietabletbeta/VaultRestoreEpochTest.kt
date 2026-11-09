package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import javax.crypto.KeyGenerator

class VaultRestoreEpochTest {
    private val archived="11111111-1111-4111-8111-111111111111"
    private fun data(title:String)=JSONObject().put("version",6)
        .put("termine",JSONArray().put(JSONObject().put("id","one").put("titel",title).put("sync",true).put("geaendert",1)))
        .put("aufgaben",JSONArray()).put("kontakte",JSONArray()).put("notizen",JSONArray())
        .put("einstellungen",JSONObject().put("fixture",true)).put("futureRoot",JSONObject().put("keep","exact"))
    private fun page(vault:Vault)=vault.openSession().session.also(vault::activate)
    private fun reject(action:()->Unit) {try {action();fail("Expected rejection")} catch(_:Exception) {}}
    @Test fun actualVaultRestoreRotatesEpochQuarantinesAndKeepsLiveEvidence() {
        val dir=Files.createTempDirectory("vault-epoch-").toFile();val key=KeyGenerator.getInstance("AES").apply {init(256)}.generateKey()
        try {
            val vault=Vault(dir,{key});val live=data("live").put("personalSync",JSONObject().put("actor_id","live-device").put("custom_revision",7).put("custom_entities",JSONObject().put("local","keep")))
            vault.save(page(vault),VaultJson.encode(live,MAX_BYTES),JSONArray())
            val incoming=data("imported").put("syncEpoch",archived)
                .put("syncMetadaten",JSONObject().put("syncEpoch",archived).put("nextcloud",JSONObject().put("pendingCommitId","old").put("ausstehendeTransaktion","old").put("transaktionen",JSONObject().put("old",true)).put("future","keep")))
                .put("geloescht",JSONObject().put("termine",JSONArray().put(JSONObject().put("uid","archived-delete"))))
                .put("syncAbgleichBasis",JSONObject().put("old",true)).put("syncAbgleichNachweis",JSONObject().put("old",true))
                .put("personalSync",JSONObject().put("actor_id","archive-device"))
            val session=page(vault);val token=vault.prepareImport(session,VaultJson.encode(incoming,MAX_BYTES))
            val start=System.currentTimeMillis();val restored=vault.replace(session,token).getJSONObject("data");val end=System.currentTimeMillis()
            val epoch=BookRestore.persistedEpoch(restored).toString();assertNotEquals(archived,epoch)
            assertEquals("imported",restored.getJSONArray("termine").getJSONObject(0).getString("titel"))
            assertTrue(restored.getJSONArray("termine").getJSONObject(0).getLong("geaendert") in start..end)
            assertEquals("exact",restored.getJSONObject("futureRoot").getString("keep"))
            assertEquals("live-device",restored.getJSONObject("personalSync").getString("actor_id"))
            assertEquals(7,restored.getJSONObject("personalSync").getInt("custom_revision"))
            assertEquals("keep",restored.getJSONObject("personalSync").getJSONObject("custom_entities").getString("local"))
            assertFalse(restored.has("syncAbgleichBasis"));assertFalse(restored.has("syncAbgleichNachweis"))
            val meta=restored.getJSONObject("syncMetadaten");val cloud=meta.getJSONObject("nextcloud")
            assertFalse(cloud.has("pendingCommitId"));assertFalse(cloud.has("ausstehendeTransaktion"));assertEquals(0,cloud.getJSONObject("transaktionen").length())
            assertEquals("keep",cloud.getString("future"));assertTrue(restored.getJSONObject("syncNachRestore").getBoolean("loeschungsfrei"))
            assertEquals(0,restored.getJSONObject("geloescht").getJSONArray("termine").length())
            assertEquals("archived-delete",meta.getJSONObject("quarantinedDeletes").getJSONObject("geloescht").getJSONArray("termine").getJSONObject(0).getString("uid"))
            assertEquals(epoch,BookRestore.persistedEpoch(Vault(dir,{key}).openSession().value!!.getJSONObject("data")).toString())
            reject {vault.save(session,VaultJson.encode(incoming,MAX_BYTES),JSONArray())}
            val next=page(vault);val before=dir.resolve("tablet-vault.enc").readBytes()
            val changed=BookRestore.copy(restored).put("syncEpoch",archived)
            reject {vault.save(next,VaultJson.encode(changed,MAX_BYTES),JSONArray())};assertArrayEquals(before,dir.resolve("tablet-vault.enc").readBytes())
            restored.getJSONArray("termine").getJSONObject(0).put("titel","edited")
            vault.save(next,VaultJson.encode(restored,MAX_BYTES),JSONArray())
            assertEquals(epoch,BookRestore.persistedEpoch(vault.read()!!.getJSONObject("data")).toString())
            val repeatPage=page(vault);val again=vault.replace(repeatPage,vault.prepareImport(repeatPage,VaultJson.encode(incoming,MAX_BYTES))).getJSONObject("data")
            assertNotEquals(epoch,BookRestore.persistedEpoch(again).toString())
        } finally {dir.deleteRecursively()}
    }
    @Test fun ordinaryFirstSaveCannotMintRendererSuppliedAuthority() {
        val dir=Files.createTempDirectory("vault-epoch-absent-").toFile();val key=KeyGenerator.getInstance("AES").apply {init(256)}.generateKey()
        try {
            val incoming=data("first").put("syncEpoch",archived).put("syncMetadaten",JSONObject().put("syncEpoch",archived))
            incoming.getJSONObject("einstellungen").put("sync",JSONObject().put("syncEpoch",archived))
            val vault=Vault(dir,{key});vault.save(page(vault),VaultJson.encode(incoming,MAX_BYTES),JSONArray())
            val saved=Vault(dir,{key}).openSession().value!!.getJSONObject("data")
            assertFalse(saved.has("syncEpoch"));assertFalse(saved.getJSONObject("syncMetadaten").has("syncEpoch"))
            assertFalse(saved.getJSONObject("einstellungen").getJSONObject("sync").has("syncEpoch"))
            assertEquals("first",saved.getJSONArray("termine").getJSONObject(0).getString("titel"))
        } finally {dir.deleteRecursively()}
    }
    @Test fun restoreFailureBoundariesKeepActualOldOrNewBookAndRejectOldPage() {
        for(boundary in listOf("backup-sync","file-sync","rename","directory-sync","commit-readback")) {
            val dir=Files.createTempDirectory("vault-epoch-failure-").toFile();val key=KeyGenerator.getInstance("AES").apply {init(256)}.generateKey()
            try {
                val initial=Vault(dir,{key});initial.save(page(initial),VaultJson.encode(data("old"),MAX_BYTES),JSONArray())
                val before=dir.resolve("tablet-vault.enc").readBytes()
                val vault=Vault(dir,{key},checkpoint={if(it==boundary) error("Owned fixture failure")})
                val session=page(vault);val token=vault.prepareImport(session,VaultJson.encode(data("new"),MAX_BYTES))
                try {vault.replace(session,token);fail("Failure was acknowledged")} catch(error:CommitFailure) {
                    assertEquals(if(boundary in listOf("backup-sync","file-sync")) "before-commit" else if(boundary=="rename") "uncertain" else "committed",error.outcome)
                }
                assertFalse(vault.isWritable(session));reject {vault.save(session,VaultJson.encode(data("stale"),MAX_BYTES),JSONArray())}
                val actual=Vault(dir,{key}).openSession().value!!.getJSONObject("data")
                if(boundary in listOf("backup-sync","file-sync")) {assertArrayEquals(before,dir.resolve("tablet-vault.enc").readBytes());assertEquals("old",actual.getJSONArray("termine").getJSONObject(0).getString("titel"))}
                else {BookRestore.persistedEpoch(actual);assertEquals("new",actual.getJSONArray("termine").getJSONObject(0).getString("titel"))}
            } finally {dir.deleteRecursively()}
        }
    }
}
