package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.*
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** Existing native fingerprint is the oracle, not a newly sorted JSON hash. */
class KontaktOriginalHashVertragTest {
    @Test fun desktopFullReturnVectorsMatchTheActualNativeContentFingerprint() {
        val fixture = Json.parseToJsonElement(File("../contracts/contact-original-return-hash-v1-vectors.json").readText()).jsonObject
        for (raw in fixture.getValue("vectors").jsonArray) {
            val vector = raw.jsonObject
            val native = Json.decodeFromJsonElement(KontaktDaten.serializer(), vector.getValue("contact"))
            assertEquals(vector.getValue("name").jsonPrimitive.content,
                vector.getValue("sha256").jsonPrimitive.content, KontaktSync.hash(native))
        }
    }
}
