package io.gitlab.maik3531.magnolietabletbeta

import kotlin.math.abs

/** Test-only cross-check: actual injection and native receipts, without a WebView RPC. */
internal object NativeGestureBinding {
    data class Receipt(val action:Int, val eventTime:Long, val downTime:Long,
                       val receivedAt:Long, val x:Double, val y:Double, val source:Int, val tool:Int)
    data class Browser(val armedAt:Double, val downStamp:Double, val upStamp:Double)

    fun verify(evaluationStart:Long, armedUptime:Long, previousDownTime:Long,
               issued:List<AsyncTouchPair.Delivery>, receipts:List<Receipt>,
               x:Double, y:Double, browser:Browser, previousOffset:Double?):Double {
        check(evaluationStart >= 0 && armedUptime >= evaluationStart)
        check(issued.size == 2 && issued[0].event.down && !issued[1].event.down)
        val down=issued[0]; val up=issued[1]; val epoch=down.event.downTime
        check(epoch >= armedUptime && epoch > previousDownTime) {"Stale/reused native gesture epoch"}
        check(up.event.downTime == epoch && down.event.eventTime >= epoch && up.event.eventTime >= epoch+40)
        check(up.event.eventTime >= down.event.eventTime)
        for(d in issued) check(d.accepted && d.callAt >= d.event.eventTime && d.returnedAt >= d.callAt)
        check(up.callAt >= down.returnedAt)
        check(receipts.size == 2 && receipts[0].action == 0 && receipts[1].action == 1) {"Missing/cancelled native receipt pair"}
        for((r,d) in receipts.zip(issued)) {
            check(r.downTime == epoch && r.eventTime == d.event.eventTime) {"Native receipt does not match issued event"}
            check(r.receivedAt >= r.eventTime && r.source == 4098 && r.tool == 1)
            check(r.x.isFinite() && r.y.isFinite() && x.isFinite() && y.isFinite())
            check(abs(r.x-x) <= 0.01 && abs(r.y-y) <= 0.01) {"Native screen-coordinate mismatch"}
        }
        check(receipts[1].receivedAt >= receipts[0].receivedAt)
        check(listOf(browser.armedAt,browser.downStamp,browser.upStamp).all {it.isFinite() && it >= 0})
        check(browser.upStamp >= browser.downStamp && browser.downStamp+1 > browser.armedAt)
        check(abs((browser.upStamp-browser.downStamp)-(up.event.eventTime-down.event.eventTime)) < 1)
        val offset=down.event.eventTime-browser.downStamp
        // The JS arm executes between native evaluation entry and result receipt.
        // Native clock readings are millisecond buckets, so the upper bound is open +1 ms.
        val mappedArm=browser.armedAt+offset
        check(mappedArm+1.0 > evaluationStart && mappedArm < armedUptime+1.0) {"Browser/native clock mapping outside preparation interval"}
        if(previousOffset != null) check(previousOffset.isFinite() && abs(offset-previousOffset) < 1) {"Browser native-clock origin changed"}
        return offset
    }
}
