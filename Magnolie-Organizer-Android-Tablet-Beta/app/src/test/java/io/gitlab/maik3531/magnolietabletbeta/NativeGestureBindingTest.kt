package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class NativeGestureBindingTest {
    private val issued=listOf(
        AsyncTouchPair.Delivery(AsyncTouchPair.Event(true,88453,88453),88453,88455,true),
        AsyncTouchPair.Delivery(AsyncTouchPair.Event(false,88453,88493),88493,88494,true))
    private val receipts=listOf(
        NativeGestureBinding.Receipt(0,88453,88453,88466,1192.0,362.78125,4098,1),
        NativeGestureBinding.Receipt(1,88493,88453,88923,1192.0,362.78125,4098,1))
    private val browser=NativeGestureBinding.Browser(11680.0,11679.8,11719.8)
    private fun verify(start:Long=88452,arm:Long=88453,previous:Long=88000,
                       events:List<AsyncTouchPair.Delivery> = issued,
                       actual:List<NativeGestureBinding.Receipt> = receipts,
                       dom:NativeGestureBinding.Browser=browser,offset:Double?=76773.2) =
        NativeGestureBinding.verify(start,arm,previous,events,actual,1192.0,362.78125,dom,offset)
    private fun rejects(action:()->Unit) {try {action();fail("Invalid native binding accepted")} catch(_:IllegalStateException) {}}

    @Test fun capturedPrecisionBoundaryMatchesNewNativeInjection() {
        assertEquals(76773.2,verify(),0.00001)
    }
    @Test fun oldOrReusedNativeEpochCannotPass() {
        rejects {verify(arm=88454)}
        rejects {verify(previous=88453)}
    }
    @Test fun receiptMustMatchTheIssuedPairAndActualScreenTarget() {
        rejects {verify(actual=receipts.map {it.copy(downTime=88452)})}
        rejects {verify(actual=listOf(receipts[0],receipts[1].copy(eventTime=88494)))}
        rejects {verify(actual=receipts.map {it.copy(x=1200.0)})}
        rejects {verify(actual=receipts.map {it.copy(source=0)})}
        rejects {verify(actual=listOf(receipts[0],receipts[1].copy(action=3)))}
    }
    @Test fun rejectedOrReversedIssuedEventsCannotPass() {
        rejects {verify(events=issued.reversed())}
        rejects {verify(events=listOf(issued[0].copy(accepted=false),issued[1]))}
        rejects {verify(events=listOf(issued[0],issued[1].copy(event=issued[1].event.copy(downTime=0))))}
    }
    @Test fun malformedAndWrongClockMappingAreRejected() {
        rejects {verify(dom=browser.copy(downStamp=Double.NaN))}
        rejects {verify(dom=browser.copy(armedAt=-1.0))}
        rejects {verify(dom=browser.copy(upStamp=11710.0))}
        rejects {verify(offset=76770.0)}
        rejects {verify(start=88454,arm=88455)}
    }
}
