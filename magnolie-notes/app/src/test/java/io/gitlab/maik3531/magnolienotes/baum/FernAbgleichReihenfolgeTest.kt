package io.gitlab.maik3531.magnolienotes.baum

import org.junit.Assert.*
import org.junit.Test

class FernAbgleichReihenfolgeTest {
    @Test fun reachablePeerAfterTimedOutPeersIsProbedOnTheNextRefresh() {
        val order = FernAbgleichReihenfolge()
        val peers = (1..6).map { "offline-$it" } + "reachable"
        order.naechste(peers).take(6).forEach(order::versucht)
        assertEquals("reachable", order.naechste(peers).first())
    }

    @Test fun moreThanThirtyTwoPeersDoNotPermanentlyHideTheTail() {
        val order = FernAbgleichReihenfolge()
        val peers = (1..70).map { "peer-$it" }
        val seen = mutableSetOf<String>()
        repeat(3) {
            val round = order.naechste(peers)
            assertEquals(32, round.size)
            assertEquals(round.size, round.distinct().size)
            round.forEach { seen += it; order.versucht(it) }
        }
        assertEquals(peers.toSet(), seen)
    }

    @Test fun aPlannedButCancelledRoundDoesNotSkipAnyPeer() {
        val order = FernAbgleichReihenfolge()
        val peers = listOf("a", "b", "c")
        assertEquals(peers, order.naechste(peers))
        assertEquals(peers, order.naechste(peers))
        order.versucht("a")
        assertEquals(listOf("b", "c", "a"), order.naechste(peers))
        assertEquals(listOf("b", "c", "a"), order.naechste(peers))
    }

    @Test fun reorderingPeersKeepsTheCursorBoundToIdentity() {
        val order = FernAbgleichReihenfolge()
        order.versucht("b")
        assertEquals(listOf("a", "d", "c", "b"), order.naechste(listOf("c", "b", "a", "d")))
    }

    @Test fun removedOrUntrustedLastPeerDoesNotHideCurrentCandidates() {
        val order = FernAbgleichReihenfolge()
        order.versucht("removed")
        assertEquals(listOf("allowed-a", "allowed-b"), order.naechste(listOf("allowed-a", "allowed-b")))
    }

    @Test fun noCandidatesProducesNoAttemptAndKeepsTheCursor() {
        val order = FernAbgleichReihenfolge()
        order.versucht("a")
        assertTrue(order.naechste(emptyList()).isEmpty())
        assertEquals(listOf("b", "a"), order.naechste(listOf("a", "b")))
    }

    @Test fun onePeerIsProbedAtMostOnceInARoundAndCanBeRefreshed() {
        val order = FernAbgleichReihenfolge()
        assertEquals(listOf("only"), order.naechste(listOf("only")))
        order.versucht("only")
        assertEquals(listOf("only"), order.naechste(listOf("only")))
    }

    @Test fun aCompleteSmallRoundStartsAgainWithoutDuplicates() {
        val order = FernAbgleichReihenfolge()
        val peers = listOf("a", "b", "c")
        order.naechste(peers).forEach(order::versucht)
        assertEquals(peers, order.naechste(peers))
    }
}
