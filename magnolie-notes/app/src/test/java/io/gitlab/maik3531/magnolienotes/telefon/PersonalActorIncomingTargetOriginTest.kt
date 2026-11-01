package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class PersonalActorIncomingTargetOriginTest {
    private val run = "44444444-4444-4444-8444-444444444444"
    private val peer = "22222222-2222-4222-8222-222222222222"
    private val now = 1793505600000L
    private val scope = PhoneContentScope.create(emptyList(), emptyList())
    private val source = "a".repeat(64)
    private fun origin() = PersonalActorIncomingTargetOrigin(run, source, scope, now, 1000)
    private fun wire(sequence: Int = 0, last: Boolean = true, batch: String = run, count: Int = 1): JsonObject =
        PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
            put("format", 1); put("run_id", run); put("proposal_batch_id", batch); put("sequence", sequence); put("last", last)
            put("proposals", JsonArray((0 until count).map { buildJsonObject {
                put("proposal_id", UUID.randomUUID().toString()); put("kind", "note"); put("id", "outside-$sequence-$it"); put("parent_id", "")
                put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", peer); put("counter", 1) })))
                put("prior_hash", source); put("deleted_ms", now); put("label", "Synthetic")
            } }.sortedBy { it.string("proposal_id") }))
        }, 60000, now), run)
    private fun capture(origin: PersonalActorIncomingTargetOrigin, wire: JsonObject, wall: Long = now, mono: Long = 1000) =
        origin.capture(wire, source, scope, wall, mono)
    private fun read(origin: PersonalActorIncomingTargetOrigin, wall: Long = now, mono: Long = 1000) = origin.read(source, scope, wall, mono)

    @Test fun exactOriginalFramesAreReturnedAsCopiesAndRetransmissionDoesNotRenewEitherDeadline() {
        val original = wire(); val origin = origin(); capture(origin, original)
        assertEquals(listOf(original), read(origin))
        capture(origin, original, now + 20000, 21000)
        assertEquals(listOf(original), read(origin, now + 29999, 30999))
        assertTrue(runCatching { read(origin, now + 30000, 31000) }.isFailure)
    }

    @Test fun monotonicExpiryIsIndependentOfWallTimeAndExpiredOriginCannotBeRevived() {
        val original = wire(); val origin = origin(); capture(origin, original)
        assertTrue(runCatching { read(origin, now, 31000) }.isFailure)
        assertTrue(runCatching { capture(origin, original) }.isFailure)
    }

    @Test fun changedSourceAndScopeInvalidateOriginWithoutReturningAFrame() {
        for (changeScope in listOf(false, true)) {
            val origin = origin(); capture(origin, wire())
            assertTrue(runCatching { origin.read(if (changeScope) source else "b".repeat(64),
                if (changeScope) PhoneContentScope.create(listOf("foreign"), emptyList()) else scope, now, 1000) }.isFailure)
            assertTrue(runCatching { read(origin) }.isFailure)
        }
    }

    @Test fun partialOrAmbiguousGroupsCannotBecomeACompleteOrigin() {
        val origin = origin(); val first = wire(0, false); capture(origin, first)
        assertTrue(runCatching { read(origin) }.isFailure)
        val second = wire(1, true); capture(origin, second)
        assertEquals(listOf(first, second), read(origin))
        capture(origin, wire(1, true))
        assertTrue(runCatching { read(origin) }.isFailure)
    }

    @Test fun changedDuplicatePoisonsTheOriginalInsteadOfReplacingIt() {
        val origin = origin(); val original = wire(); capture(origin, original)
        val changed = JsonObject(original + ("expires_ms" to JsonPrimitive(now + 59999)))
        assertTrue(runCatching { capture(origin, changed) }.isFailure)
        assertTrue(runCatching { read(origin) }.isFailure)
    }

    @Test fun targetCapacityIsAtomicAndNeverReturnsAnAllowedPartialGroup() {
        val origin = origin()
        for (sequence in 0..7) capture(origin, wire(sequence, sequence == 7, count = 32))
        assertEquals(8, read(origin).size)
        assertTrue(runCatching { capture(origin, wire(8, true)) }.isFailure)
        assertTrue(runCatching { read(origin) }.isFailure)
    }

    @Test fun originalFrameExpiryAndForeignRunCannotBeExtendedByTheQuarantine() {
        val origin = origin(); val short = wire().let { JsonObject(it + ("expires_ms" to JsonPrimitive(now + 1000))) }
        capture(origin, short)
        assertTrue(runCatching { read(origin, now + 1000, 2000) }.isFailure)
        val foreign = wire().let { JsonObject(it + ("body" to JsonObject(it.getValue("body").jsonObject + ("run_id" to JsonPrimitive(peer))))) }
        assertTrue(runCatching { capture(origin(), foreign) }.isFailure)
    }

    @Test fun retirementWipesThePrivateFrameBuffersAndDisablesFurtherReads() {
        val origin = origin(); capture(origin, wire())
        @Suppress("UNCHECKED_CAST")
        val buffers = (origin.javaClass.getDeclaredField("frames").apply { isAccessible = true }.get(origin) as Map<String, ByteArray>).values.toList()
        assertTrue(buffers.isNotEmpty() && buffers.any { bytes -> bytes.any { it != 0.toByte() } })
        origin.clear()
        assertTrue(buffers.all { bytes -> bytes.all { it == 0.toByte() } })
        assertTrue(runCatching { read(origin) }.isFailure)
    }
}
