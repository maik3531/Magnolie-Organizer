package io.gitlab.maik3531.magnolienotes.netz;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Shared executable cases for JUnit and the SDK-free host probe. */
public final class LanAnfrageCases {
    private int checks;

    private void require(boolean value, String reason) {
        checks++;
        if (!value) throw new AssertionError(reason);
    }

    public static int pruefen() {
        LanAnfrageCases cases = new LanAnfrageCases();
        cases.visibleUserActionMatrix();
        cases.singleRequestAndDenial();
        cases.stopKeepsOldResultSlot();
        cases.failedLaunchDoesNotPoisonOrFreeAnotherRequest();
        cases.resultDoesNotCreateAuthority();
        cases.recreatedActivityDoesNotInheritAction();
        cases.closeCannotBeResurrected();
        return cases.checks;
    }

    private void visibleUserActionMatrix() {
        for (boolean visible : new boolean[] {false, true}) {
            for (boolean required : new boolean[] {false, true}) {
                for (boolean granted : new boolean[] {false, true}) {
                    LanAnfrage request = new LanAnfrage();
                    AtomicInteger reads = new AtomicInteger();
                    LanAnfrage.Entscheidung decision = request.einrichten(visible, required, () -> {
                        reads.incrementAndGet();
                        return granted;
                    });
                    LanAnfrage.Art expected = !visible ? LanAnfrage.Art.WARTEN :
                        granted ? LanAnfrage.Art.ERLAUBT :
                        required ? LanAnfrage.Art.ANFRAGEN : LanAnfrage.Art.WARTEN;
                    require(decision.art == expected, "visibility/required/grant matrix");
                    require(reads.get() == (visible ? 1 : 0), "only visible setup reads permission here");
                    require((decision.ticket != 0) == (expected == LanAnfrage.Art.ANFRAGEN),
                        "only an actual request owns a ticket");
                    require(request.offen() == (expected == LanAnfrage.Art.ANFRAGEN), "request slot ownership");
                }
            }
        }
    }

    private void singleRequestAndDenial() {
        LanAnfrage request = new LanAnfrage();
        require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.ANFRAGEN, "first explicit setup asks");
        for (int i = 0; i < 20; i++) {
            require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.WARTEN, "no overlapping dialog");
            require(request.einrichten(false, true, () -> false).art == LanAnfrage.Art.WARTEN, "no background dialog");
        }
        require(request.antwort(true, () -> false), "visible denial may show waiting hint");
        require(!request.offen(), "denial drains request");
        require(!request.antwort(true, () -> false), "duplicate/orphan callback has no UI effect");
        require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.ANFRAGEN,
            "a later explicit action may ask again; no automatic retry");
        require(!request.antwort(false, () -> false), "hidden denial must not show UI");
    }

    private void stopKeepsOldResultSlot() {
        LanAnfrage request = new LanAnfrage();
        request.einrichten(true, true, () -> false);
        request.unterbrechen(); // Activity stopped, navigation or peer context changed.
        require(request.offen(), "old system result slot remains occupied");
        require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.WARTEN,
            "resuming cannot assign the pending old callback to a new request");
        require(!request.antwort(true, () -> false), "late callback from stopped context is quiet");
        require(!request.offen(), "late callback drains old slot");
        require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.ANFRAGEN, "fresh action after drainage works");
        request.unterbrechen();
        require(!request.antwort(true, () -> true), "late grant never creates a continuation");
        require(request.einrichten(true, true, () -> true).art == LanAnfrage.Art.ERLAUBT,
            "fresh consciously repeated action uses current actual grant");
    }

    private void failedLaunchDoesNotPoisonOrFreeAnotherRequest() {
        LanAnfrage request = new LanAnfrage();
        long first = request.einrichten(true, true, () -> false).ticket;
        request.startFehlgeschlagen(first);
        require(!request.offen(), "launcher exception releases own slot");
        long second = request.einrichten(true, true, () -> false).ticket;
        require(second > first, "new request has distinct ticket");
        request.startFehlgeschlagen(first);
        request.startFehlgeschlagen(0);
        require(request.offen(), "stale/absent launch failure cannot clear new slot");
        require(request.einrichten(true, true, () -> false).art == LanAnfrage.Art.WARTEN, "no second request after stale failure");
        // Synchronous callback can finish before launch() returns or throws.
        require(!request.antwort(true, () -> true), "successful callback is not an action");
        long third = request.einrichten(true, true, () -> false).ticket;
        request.startFehlgeschlagen(second);
        require(third > second && request.offen(), "late launch error after synchronous result does not affect next request");
        request.startFehlgeschlagen(third);
        require(!request.offen(), "actual current launch failure still releases slot");
    }

    private void resultDoesNotCreateAuthority() {
        LanAnfrage request = new LanAnfrage();
        AtomicBoolean actualGrant = new AtomicBoolean(false);
        AtomicInteger reads = new AtomicInteger();
        java.util.function.BooleanSupplier os = () -> {
            reads.incrementAndGet();
            return actualGrant.get();
        };
        require(request.einrichten(true, true, os).art == LanAnfrage.Art.ANFRAGEN, "first grant read denied");
        actualGrant.set(true); // Android may grant through its permission group.
        require(!request.antwort(true, os), "callback uses actual grant, no callback-Boolean parameter");
        require(reads.get() == 2, "callback reads OS again");
        actualGrant.set(false); // A later revoke must not reuse the callback's grant.
        require(request.einrichten(true, true, os).art == LanAnfrage.Art.ANFRAGEN, "grant is not cached after callback");
        require(request.antwort(true, os), "an OS denial wins even if dialog reported success");
        require(reads.get() == 4, "every visible request/result reads the current authority");
        actualGrant.set(true);
        require(request.einrichten(true, true, os).art == LanAnfrage.Art.ERLAUBT, "already granted permission avoids repeated dialog");
        require(!request.offen(), "pre-granted path does not occupy OS slot");
    }

    private void recreatedActivityDoesNotInheritAction() {
        LanAnfrage oldActivity = new LanAnfrage();
        oldActivity.einrichten(true, true, () -> false);
        oldActivity.close();
        LanAnfrage recreated = new LanAnfrage();
        require(!recreated.antwort(false, () -> true), "restored ActivityResult before RESUMED has no request to resume");
        require(!recreated.offen(), "new Activity restores neither grant nor action");
        require(!oldActivity.antwort(true, () -> true), "destroyed Activity's late callback does nothing");
        require(recreated.einrichten(false, true, () -> true).art == LanAnfrage.Art.WARTEN,
            "even a real grant does not authorize an invisible UI action");
        require(recreated.einrichten(true, true, () -> true).art == LanAnfrage.Art.ERLAUBT,
            "new visible action may use the OS grant independently");
    }

    private void closeCannotBeResurrected() {
        LanAnfrage request = new LanAnfrage();
        long ticket = request.einrichten(true, true, () -> false).ticket;
        request.close();
        request.close();
        request.unterbrechen();
        request.startFehlgeschlagen(ticket);
        require(!request.offen(), "closed request owns no slot");
        for (boolean actualGrant : new boolean[] {false, true}) {
            require(request.einrichten(true, true, () -> actualGrant).art == LanAnfrage.Art.WARTEN, "closed Activity stays closed");
            require(!request.antwort(true, () -> actualGrant), "closed Activity cannot show a callback hint");
        }
    }

    public static void main(String[] args) {
        System.out.println("PASS: " + pruefen() + " LAN request lifecycle assertions (synthetic host, not Android acceptance)");
    }
}
