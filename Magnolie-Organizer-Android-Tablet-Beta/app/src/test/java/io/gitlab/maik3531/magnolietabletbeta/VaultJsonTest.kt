package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.math.BigDecimal
import java.nio.file.Files
import javax.crypto.KeyGenerator

class VaultJsonTest {
    private val literal="""{"version":6,"termine":[],"aufgaben":[],"kontakte":[],"notizen":[],"einstellungen":{"regional":{"language":"en"}},"futureNumber":9223372036854775808}"""
    private fun reject(action:()->Unit) {try {action();fail("Expected rejection")} catch(_:Exception) {}}
    private fun token(text:String)=Regex("\"futureNumber\"\\s*:\\s*([^,}\\s]+)").find(text)!!.groupValues[1]
    private fun exact(text:String) {assertEquals(0,BigDecimal(token(text)).compareTo(BigDecimal("9223372036854775808")))}
    private fun key()=KeyGenerator.getInstance("AES").apply {init(256)}.generateKey()
    @Test fun floatingBoundaryAndIntegerControlKeepTheirValuesAndKinds() {
        val value=JSONObject(literal).put("signedMax",Long.MAX_VALUE).put("floatingOne",1.0)
            .put("negativeZero",-0.0).put("enabled",true).put("none",JSONObject.NULL)
        val text=VaultJson.encode(value,MAX_BYTES);exact(text)
        val parsed=JSONObject(text)
        assertEquals(Long.MAX_VALUE,parsed.getLong("signedMax"))
        assertEquals(java.lang.Double.doubleToRawLongBits(-0.0),java.lang.Double.doubleToRawLongBits(parsed.getDouble("negativeZero")))
        assertTrue(text.contains("\"floatingOne\":1.0"));assertTrue(text.contains("\"enabled\":true"))
        assertTrue(parsed.isNull("none"));assertEquals(text,VaultJson.encode(value,MAX_BYTES))
    }
    @Test fun unicodeAndExactUtf8OutputLimitsAreCheckedWithoutChangingInput() {
        val value=JSONObject().put("é","東京 😀\n/\"").put("e\u0301",JSONArray().put(JSONObject.NULL).put(true))
        val text=VaultJson.encode(value,MAX_BYTES);val length=text.toByteArray(Charsets.UTF_8).size
        assertEquals(text,VaultJson.encode(value,length));reject {VaultJson.encode(value,length-1)}
        val parsed=JSONObject(text);assertEquals("東京 😀\n/\"",parsed.getString("é"))
        assertTrue(parsed.has("e\u0301"));assertTrue(parsed.has("é"));assertEquals(2,parsed.length())
        reject {VaultJson.encode(JSONObject().put("invalid","\ud800"),MAX_BYTES)}
    }
    @Test fun finiteFloatingEdgesRoundtripWithoutSaturatedIntegerCasts() {
        for(number in listOf(0.0,-0.0,1.0,-1.0,0.1,-0.1,Double.MIN_VALUE,Double.MAX_VALUE,
            -Double.MAX_VALUE,9007199254740991.0,9007199254740992.0,9007199254740994.0,
            Long.MIN_VALUE.toDouble(),9223372036854775808.0)) {
            val encoded=VaultJson.encode(JSONObject().put("number",number),4096)
            val reopened=JSONObject(encoded).getDouble("number")
            assertEquals(java.lang.Double.doubleToRawLongBits(number),java.lang.Double.doubleToRawLongBits(reopened))
        }
    }
    @Test fun cyclesAndDeepObjectsRejectBeforeStorage() {
        val cyclic=JSONObject();cyclic.put("self",cyclic);reject {VaultJson.encode(cyclic,MAX_BYTES)}
        val root=JSONObject();var current=root
        repeat(65) {val child=JSONObject();current.put("next",child);current=child}
        reject {VaultJson.encode(root,MAX_BYTES)}
    }
    @Test fun actualEncryptedSaveAndReplacementReopenWithoutNumericClamping() {
        val directory=Files.createTempDirectory("vault-number-").toFile()
        try {
            val key=key();val crypto=DatenDateiKrypto({key});val vault=Vault(directory,{key})
            var session=vault.openSession().session;vault.activate(session)
            vault.save(session,literal,JSONArray())
            fun actual()=decodeUtf8(crypto.entschluesseln(File(directory,"tablet-vault.enc").readBytes(),"tablet-vault.enc"))
            exact(actual())
            val reopened=Vault(directory,{key});val loaded=reopened.openSession();reopened.activate(loaded.session)
            assertEquals(9223372036854775808.0,loaded.value!!.getJSONObject("data").getDouble("futureNumber"),0.0)
            session=loaded.session
            reopened.replace(session,reopened.prepareImport(session,literal))
            exact(actual());assertNotNull(Vault(directory,{key}).openSession().value)
            reject {reopened.save(session,literal,JSONArray())}
        } finally {directory.deleteRecursively()}
    }
    @Test fun recoveryRetainsExactAuthenticatedPlaintextAndItsOwnAAD() {
        val directory=Files.createTempDirectory("vault-recovery-number-").toFile()
        try {
            val key=key();val crypto=DatenDateiKrypto({key})
            val original="""{ "format":1, "revision":"public-old", "data":$literal, "alarms":[], "enabled":false, "customEnabled":false, "delivered":{} }""".toByteArray(Charsets.UTF_8)
            NioStorageFileOps.ensurePrivateDirectory(directory)
            NioStorageFileOps.writeAndSync(File(directory,"tablet-vault.enc"),crypto.verschluesseln(original,"tablet-vault.enc"),MAX_BYTES+1024)
            val vault=Vault(directory,{key});val session=vault.openSession().session;vault.activate(session)
            vault.replace(session,vault.prepareImport(session,literal))
            val backup=File(directory,"before-import.enc").readBytes()
            assertArrayEquals(original,crypto.entschluesseln(backup,"before-import.enc"))
            reject {crypto.entschluesseln(backup,"tablet-vault.enc")}
        } finally {directory.deleteRecursively()}
    }
}
