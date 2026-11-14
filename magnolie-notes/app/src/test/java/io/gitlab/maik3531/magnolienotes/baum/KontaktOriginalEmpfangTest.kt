package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Partner
import io.gitlab.maik3531.magnolienotes.journal.*
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.lang.reflect.InvocationTargetException
import java.util.UUID
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** Real FS1 -> actual Baumwerk/Ablage receive transaction -> synthetic native
 * provider CAS/readback -> durable verified receipt/result outbox. No sockets,
 * installed documents, physical contacts or actual AndroidKeyStore are used.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktOriginalEmpfangTest {
    private lateinit var parent: File
    private lateinit var context: Context
    private lateinit var provider: KontaktOriginalBindungTest.OriginalProvider
    private lateinit var store: Ablage
    private lateinit var handler: Baumwerk
    private lateinit var server: Server
    private lateinit var sender: EigeneIdentitaet
    private lateinit var receiver: EigeneIdentitaet
    private lateinit var consent: KontaktOriginalDauerfreigaben
    private lateinit var binding: KontaktOriginalBindung
    private lateinit var scope: KontaktOriginalFreigaben
    private var consentKey: SecretKey? = null
    private var rotations = 0
    private val journalKey = SecretKeySpec(ByteArray(32) { 91 }, "AES")
    private val dataKey = SecretKeySpec(ByteArray(32) { 92 }, "AES")
    private var sequence = 0
    private var connection = true
    private var beforeProtection: () -> Unit = {}
    private val id = "11111111-1111-4111-8111-111111111111"
    private val share = "canonical-original-kept"
    private var quote = "b".repeat(64)
    private fun maps() = KontaktOriginalZuordnungen.fuerTest(File(parent, "maps")) { journalKey }
    private fun attempts() = KontaktOriginalVersuche.fuerTest(File(parent, "attempts")) { journalKey }
    private fun sourcePeer() = KontaktOriginalFreigaben.Partner(sender.kennung, sender.oeffentlich)
    private fun newConsent() = KontaktOriginalDauerfreigaben(File(parent, "consent"), KontaktOriginalSchutz.fuerTest(
        { consentKey }, { rotations++; consentKey = SecretKeySpec(ByteArray(32) { 93 }, "AES") }, { consentKey = null }))
    private fun protection(): KontaktOriginalSicherungen {
        val crypto = AesGcmKrypto { journalKey }
        return KontaktOriginalSicherungen(context, DateiSnapshotStore(File(parent, "protection"), Ablage.json),
            crypto, crypto, { store.baum.value.syncEpoch }, "synthetic", { beforeProtection() })
    }
    private fun identity(id: String): EigeneIdentitaet {
        val keys = Krypto.neuesSchluesselpaar()
        return EigeneIdentitaet(id, "Synthetic", Krypto.b64(keys.second), Krypto.b64(keys.first), 0)
    }
    private fun attach(enabled: Boolean = true) {
        handler = if (!enabled) Baumwerk.fuerTest(store, context) else Baumwerk.fuerOriginalRueckwegTest(store, context) { actual ->
            KontaktOriginalEmpfang(context, actual, consent, maps(), attempts(), { protection() }) { connection }
        }
        server = Server(handler, 0)
    }
    @Before fun setup() {
        val app = ApplicationProvider.getApplicationContext<Application>()
        Shadows.shadowOf(app).grantPermissions(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS)
        parent = java.nio.file.Files.createTempDirectory(app.cacheDir.toPath(), "native-original-receive-").toFile()
        val files = File(parent, "data").apply { mkdir() }
        context = object : ContextWrapper(app) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = files
        }
        provider = KontaktOriginalBindungTest.OriginalProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        sender = identity("sender"); receiver = identity("receiver")
        store = Ablage.fuerTest(context) { dataKey }
        store.setzeBaum(Baumzustand(kennung = receiver.kennung, name = receiver.name, geheim = receiver.geheim,
            oeffentlich = receiver.oeffentlich, syncEpoch = "synthetic-epoch", partner = listOf(
                Partner(sender.kennung, oeffentlich = sender.oeffentlich, bestaetigt = true, vertraut = true, kontaktSync = true))))
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        consent = newConsent()
        attach()
    }
    @After fun cleanup() { server.anhalten(); parent.deleteRecursively() }
    private fun configure() {
        scope = KontaktOriginalFreigaben(consent) { sourcePeer() }
        val offered = KontaktOriginalFreigaben.Original(share, binding)
        scope.einrichtenOriginale(listOf(binding), listOf(offered), speichern = { maps().speichern(it) }) { sources, originals ->
            KontaktOriginalFreigaben.Auswahl(sources.toSet(), originals.toSet())
        }
        quote = maps().finden(sourcePeer(), share)!!.basisHash(scope.freigabe(binding))
    }
    private fun request(target: KontaktDaten = binding.aktuell().daten.copy(notiz = "Authenticated native return")): JsonObject = buildJsonObject {
        put("art", KontaktOriginalEmpfang.ANFRAGE); put("fassung", 1); put("request_id", id)
        put("share_id", share); put("before_basis", quote); put("target_sha256", KontaktSync.hash(target))
        put("ziel", JsonObject(KontaktSync.kontaktJson(target, 2).filterKeys {
            it in setOf("vorname", "nachname", "anzeigename", "vcardName", "firma", "notiz", "geburtstag", "jubilaeum", "anschriften")
        }))
    }
    private fun call(name: String, message: JsonObject): JsonObject {
        val method = Server::class.java.getDeclaredMethod(name, EigeneIdentitaet::class.java, JsonObject::class.java, String::class.java)
            .apply { isAccessible = true }
        return try { method.invoke(server, handler.eigen()!!, message, "127.0.0.1") as JsonObject }
        catch (error: InvocationTargetException) { throw requireNotNull(error.cause) }
    }
    private fun send(body: JsonObject) {
        val start = Sitzung.baueStart(sender, receiver.kennung, receiver.oeffentlich)
        val answer = call("sitzungAufbauen", start.nachricht)
        val channel = Sitzung.oeffneAntwort(sender, receiver.kennung, receiver.oeffentlich, start, answer)
        try {
            val marker = ++sequence
            val transport = Krypto.b64(ByteArray(16) { marker.toByte() })
            val envelope = Sitzung.baueUmschlag(channel, sender.kennung, receiver.kennung, body, transport)
            assertTrue(Sitzung.pruefeQuittung(channel, envelope, call("sichereNachricht", envelope)))
        } finally { channel.loeschen(); start.ephemerGeheim.fill(0) }
    }
    private fun queued() = store.baum.value.postfach.filter { it.art == KontaktOriginalEmpfang.ERGEBNIS }
        .map { Json.parseToJsonElement(it.inhalt) as JsonObject }
    private fun assertNoMutation() {
        assertEquals(0, provider.batchCalls); assertEquals(0, provider.writes)
        assertTrue(store.baum.value.partner.single().gesehen.isEmpty()); assertTrue(queued().isEmpty())
        assertFalse(File(parent, "attempts").exists()); assertFalse(File(parent, "protection").exists())
    }

    @Test fun actualCryptoAndReceiveTransactionWriteOnlyTheSelectedOriginalAndQueueTheExactVerifiedResult() {
        configure(); val body = request(); val mapFile = File(parent, "maps").listFiles()!!.single { it.extension == "bin" }
        val before = mapFile.readBytes()
        send(body)
        assertEquals(1, provider.batchCalls); assertEquals(1, queued().size)
        val result = queued().single()
        assertEquals(JsonPrimitive(id), result["request_id"]); assertEquals(JsonPrimitive(quote), result["before_basis"])
        assertEquals(body["target_sha256"], result["target_sha256"]); assertNotNull(result["next_basis"])
        assertTrue(store.baum.value.kontaktEingang.isEmpty()); assertEquals(1, store.baum.value.partner.single().gesehen.size)
        assertArrayEquals(before, mapFile.readBytes())
        val current = maps().beobachten(context, sourcePeer(), share)!!
        assertNotNull(attempts().laden(scope.freigabe(current))!!.bestaetigung()) // Generic ACK did NOT settle it.
    }
    @Test fun aFreshNativeOwnerReemitsTheSameLostResultWithoutAnotherSetupOrProviderBatch() {
        configure(); val body = request(); send(body); val original = queued().single()
        server.anhalten(); store = Ablage.fuerTest(context) { dataKey }; consent = newConsent(); attach()
        send(body)
        assertEquals(original, queued().last()); assertEquals(1, provider.batchCalls); assertEquals(1, rotations)
    }
    @Test fun productionDispatchRemainsOffEvenWithAnAcceptedNativeSourceSetup() {
        configure(); server.anhalten(); attach(enabled = false)
        assertThrows(BaumFehler::class.java) { send(request()) }; assertNoMutation()
    }
    @Test fun missingConsentStopsBeforeProviderObservationOrDefaultStateCreation() {
        val body = request(); val queries = provider.queries
        assertThrows(SecurityException::class.java) { send(body) }
        assertEquals(queries, provider.queries); assertFalse(File(parent, "consent").exists()); assertNoMutation()
    }
    @Test fun aStaleQuotedBasisCannotBeRefilledByTheReceiveController() {
        configure(); val body = JsonObject(request() + ("before_basis" to JsonPrimitive("0".repeat(64))))
        assertThrows(IllegalArgumentException::class.java) { send(body) }; assertNoMutation()
    }
    @Test fun newRequestIdentityCannotBypassTheAlreadyVerifiedPhysicalOriginal() {
        configure(); val body = request(); send(body)
        assertThrows(IllegalArgumentException::class.java) {
            send(JsonObject(body + ("request_id" to JsonPrimitive(UUID.randomUUID().toString()))))
        }
        assertEquals(1, provider.batchCalls); assertEquals(1, queued().size)
    }
    @Test fun phoneFieldsAndUnknownRootFieldsAreNotAFullReturnPermission() {
        configure(); val body = request()
        val badPatch = JsonObject(body.getValue("ziel").jsonObject + ("telefone" to JsonArray(emptyList())))
        assertThrows(IllegalArgumentException::class.java) { send(JsonObject(body + ("ziel" to badPatch))) }
        assertThrows(IllegalArgumentException::class.java) { send(JsonObject(body + ("auto" to JsonPrimitive(true)))) }
        assertNoMutation()
    }
    @Test fun wrongDesiredTargetHashAndNativeConnectionPolicyRejectBeforeProtection() {
        configure(); val body = request()
        assertThrows(IllegalArgumentException::class.java) { send(JsonObject(body + ("target_sha256" to JsonPrimitive("0".repeat(64))))) }
        connection = false
        assertThrows(IllegalArgumentException::class.java) { send(body) }
        assertNoMutation()
    }
    @Test fun nativeCancellationDuringOriginalProtectionCannotReachProviderOrReplayMutation() {
        configure(); beforeProtection = { store.baumTransporteAbbrechen() }
        assertThrows(BaumFehler::class.java) { send(request()) }
        assertEquals(0, provider.batchCalls); assertEquals(0, provider.writes)
        assertTrue(store.baum.value.partner.single().gesehen.isEmpty()); assertTrue(queued().isEmpty())
        assertFalse(File(parent, "attempts").exists())
        assertTrue(File(parent, "protection").listFiles().orEmpty().isEmpty())
    }
    @Test fun aCopiedOriginCannotDriveTheControllerThroughTheActualNativeReceiver() {
        configure(); val body = request(); val queries = provider.queries
        assertThrows(BaumFehler::class.java) { handler.verarbeiteSichereNachricht(Server.FsEmpfang(Any()), body, Krypto.b64(ByteArray(16))) }
        assertEquals(queries, provider.queries); assertNoMutation()
    }

    @Test fun changedTargetUnderTheSameRequestCannotReplaceAnAlreadyVerifiedResult() {
        configure(); val body = request(); send(body); val original = queued().single()
        assertThrows(IllegalArgumentException::class.java) {
            send(request(binding.ruecklesenNachSchreiben().daten.copy(notiz = "Different target under the same request")))
        }
        assertEquals(listOf(original), queued()); assertEquals(1, provider.batchCalls)
    }

    @Test fun oversizedNativePlanAndLegacyUnprovenOriginStopBeforeAnyProtection() {
        configure()
        val text = "x".repeat(1900)
        val target = binding.aktuell().daten.copy(anschriften = List(100) {
            KontaktAnschrift("privat", "$it$text", text, text, text, text)
        })
        val error = assertThrows(IllegalArgumentException::class.java) { send(request(target)) }
        assertEquals("contact_original_binder_budget_required", error.message)
        assertThrows(IllegalArgumentException::class.java) {
            handler.verarbeiteNachricht(sender.kennung, request(), transportId = Krypto.b64(ByteArray(16)))
        }
        assertNoMutation()
    }

    @Test fun acceptedButUnknownPhysicalAttemptCannotBecomeReplayAuthority() {
        configure()
        val body = request()
        val grant = scope.freigabe(binding)
        attempts().vormerken(grant, id, "c".repeat(64), body.getValue("target_sha256").jsonPrimitive.content,
            protection().sichern(grant, id))
        assertThrows(IllegalArgumentException::class.java) { send(body) }
        assertEquals(0, provider.batchCalls); assertTrue(queued().isEmpty())
        assertNull(attempts().laden(grant)!!.bestaetigung())
        assertTrue(store.baum.value.partner.single().gesehen.isEmpty())
    }

    @Test fun failedActualReceiveCommitRecoversTheResultWithoutReplayingTheProvider() {
        configure(); val body = request()
        server.anhalten()
        store = Ablage.fuerTest(context, { dataKey }, { step ->
            if (step == io.gitlab.maik3531.magnolienotes.daten.PaarCommitSchritt.ABSICHT_DAUERHAFT)
                throw java.io.IOException("Controlled actual receive pair-commit interruption")
        })
        attach()
        assertThrows(java.io.IOException::class.java) { send(body) }
        assertEquals(1, provider.batchCalls)
        server.anhalten(); store = Ablage.fuerTest(context) { dataKey }; consent = newConsent(); attach()
        val recovered = queued().single()
        send(body)
        assertEquals(recovered, queued().last()); assertEquals(1, provider.batchCalls); assertEquals(1, rotations)
    }

    @Test fun unsupportedCustomPostalKindStopsBeforeProtectionReservationAndProviderWrite() = unsupportedPostalKind("Native custom label")
    @Test fun emptyPostalKindIsNotSilentlyTurnedIntoAnotherNativeType() = unsupportedPostalKind("")

    private fun unsupportedPostalKind(kind: String) {
        configure()
        val target = binding.aktuell().daten.copy(anschriften = listOf(KontaktAnschrift(kind, "Synthetic street")))
        val error = assertThrows(IllegalArgumentException::class.java) { send(request(target)) }
        assertEquals("Unsupported postal kind reached the actual provider batch", 0, provider.batchCalls)
        assertEquals("contact_original_postal_kind_not_supported", error.message)
        assertNoMutation()
    }

    @Test fun explicitSupportedOtherPostalKindStillReachesVerifiedNativeReadback() {
        configure()
        val target = binding.aktuell().daten.copy(anschriften = listOf(KontaktAnschrift("sonstige", "Synthetic street")))
        send(request(target))
        assertEquals(target, binding.ruecklesenNachSchreiben().daten)
        assertEquals(1, provider.batchCalls); assertEquals(1, queued().size)
    }

    @Test fun unrelatedScalarEditPreservesAnUnchangedCustomPostalLabelAndNativeColumns() {
        val row = provider.postal("Existing synthetic street", ContactsContract.CommonDataKinds.StructuredPostal.TYPE_CUSTOM)
        row[ContactsContract.CommonDataKinds.StructuredPostal.LABEL] = "Existing native label"
        row[ContactsContract.CommonDataKinds.StructuredPostal.POBOX] = "Retained native box"
        row[ContactsContract.Data.DATA11] = "Retained unmodeled native column"
        val nativeId = row.getValue(ContactsContract.Data._ID); val before = row.toMap()
        binding = KontaktOriginalBindung.erfassen(context, "native-lookup")
        configure()
        send(request(binding.aktuell().daten.copy(notiz = "Only the note changes")))
        assertEquals(before, provider.rows.single { it[ContactsContract.Data._ID] == nativeId }.toMap())
        assertEquals(1, provider.batchCalls); assertEquals(1, queued().size)
    }

    @Test fun authenticatedRawFnOnlyChangeUsesExactPlanEvenWhenItsLegacyFingerprintMatchesBefore() {
        configure()
        val before = binding.aktuell().daten
        val fn = listOf(before.vorname, before.nachname).filter { it.isNotEmpty() }.joinToString(" ")
        val target = before.copy(vcardName = listOf("FN:$fn"))
        assertNotEquals(before, target); assertEquals(KontaktSync.hash(before), KontaktSync.hash(target))
        val body = request(target)
        send(body)
        assertEquals(target, binding.ruecklesenNachSchreiben().daten)
        val requestHash = Krypto.sha256(Kanonisch.bytes(body)).joinToString("") { "%02x".format(it.toInt() and 255) }
        assertEquals(JsonPrimitive(requestHash), queued().single()["request_sha256"])
        assertEquals(1, provider.batchCalls)
    }
}
