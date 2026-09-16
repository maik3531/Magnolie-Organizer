package io.gitlab.maik3531.magnolienotes

import android.content.Context
import android.content.ContextWrapper
import io.gitlab.maik3531.magnolienotes.daten.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.UUID
import javax.crypto.spec.SecretKeySpec

/** Only the emulator-only validation runner can supply this isolated context. */
class StorageDurabilityInstrumentationTest {
    private fun isolated(test: (Context) -> Unit) {
        val base = ValidationTestRunner.instance.targetContext
        check(base.packageName == "io.gitlab.maik3531.magnolienotes.validation")
        val directory = File(base.filesDir, "storage-fixture-${UUID.randomUUID()}")
        check(directory.mkdir())
        val context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try { test(context) } finally { directory.deleteRecursively() }
    }

    @Test fun directorySyncUsesReadableDescriptorAndPropagatesErrors() = isolated { context ->
        assertThrows(IOException::class.java) { FileOutputStream(context.filesDir).close() }
        synchronisiereOrdner(context.filesDir)
        assertThrows(IOException::class.java) { synchronisiereOrdner(File(context.filesDir, "missing")) }
    }

    @Test fun ambiguousCommitRefusesWritesUntilRecovery() {
        for (restore in listOf(false, true)) for (step in PaarCommitSchritt.entries) isolated { context ->
            val key = SecretKeySpec(ByteArray(32) { 42 }, "AES")
            Ablage.fuerTest(context) { key }.setzeBaum(Baumzustand(
                partner = listOf(Partner("fixture-peer", bestaetigt = true))))
            val store = Ablage.fuerTest(context, { key }) { if (it == step) throw IOException("synthetic checkpoint") }
            val snapshot = Bestand(notizen = listOf(Notiz(id = "incoming", titel = "Synthetic snapshot")))
            assertThrows(IOException::class.java) {
                if (restore) store.journalWiederherstellen(
                    Ablage.json.encodeToString(Bestand.serializer(), snapshot),
                    Ablage.json.encodeToString(Baumzustand.serializer(), store.baum.value), "fixture-restore")
                else store.verarbeiteBaumNachricht("fixture-peer", zaehler = 7) { store.setzeNotiz(snapshot.notizen.single()) }
            }
            assertEquals(StartFehlerArt.RECOVERY, assertThrows(StartFehler::class.java) {
                store.sichereNotiz(Notiz(id = "refused", titel = "Must not acknowledge"))
            }.art)
            assertThrows(StartFehler::class.java) { store.aendereBaum { it.copy(name = "refused") } }
            assertThrows(StartFehler::class.java) { store.portableWiederherstellen("{}", "refused") }
            assertThrows(StartFehler::class.java) {
                store.verarbeiteBaumNachricht("fixture-peer", zaehler = 8) { fail("Mutation must not run") }
            }
            val recovered = Ablage.fuerTest(context) { key }
            val committed = step >= PaarCommitSchritt.ABSICHT_DAUERHAFT
            assertEquals("$restore/$step", committed, recovered.notiz("incoming") != null)
            assertNull(recovered.notiz("refused"))
            if (!restore) assertEquals(if (committed) 7L else 0L, recovered.baum.value.partner.single().zaehlerRein)
            assertFalse(File(context.filesDir, "wiederherstellung.pending").exists())
            recovered.sichereNotiz(Notiz(id = "after-recovery", titel = "Durable local edit"))
            assertNotNull(Ablage.fuerTest(context) { key }.notiz("after-recovery"))
        }
    }
}
