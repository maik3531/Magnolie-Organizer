package io.gitlab.maik3531.magnolienotes.netz;

import java.util.function.BooleanSupplier;

/**
 * One Activity's visible LAN setup request. This holds no grant, saved consent,
 * peer, account, service command or continuation. Android owns the permission.
 */
public final class LanAnfrage implements AutoCloseable {
    public enum Art { ERLAUBT, WARTEN, ANFRAGEN }

    public static final class Entscheidung {
        public final Art art;
        public final long ticket;

        private Entscheidung(Art art, long ticket) {
            this.art = art;
            this.ticket = ticket;
        }
    }

    private long generation;
    private long offen;
    private boolean zugeordnet;
    private boolean geschlossen;

    /** Called only by an explicit visible setup action, never by a lifecycle tick. */
    public synchronized Entscheidung einrichten(boolean sichtbar, boolean erforderlich,
                                                BooleanSupplier aktuellerGrant) {
        if (geschlossen || !sichtbar) return new Entscheidung(Art.WARTEN, 0);
        if (aktuellerGrant.getAsBoolean()) return new Entscheidung(Art.ERLAUBT, 0);
        if (!erforderlich || offen != 0) return new Entscheidung(Art.WARTEN, 0);
        offen = ++generation;
        zugeordnet = true;
        return new Entscheidung(Art.ANFRAGEN, offen);
    }

    /** A launch failure releases only the launch that actually failed. */
    public synchronized void startFehlgeschlagen(long ticket) {
        if (ticket != 0 && offen == ticket) {
            offen = 0;
            zugeordnet = false;
        }
    }

    /**
     * The result Boolean is deliberately not an input. Re-read Android's grant.
     * The only result is whether a visible waiting hint may be shown; this can
     * never resume an operation captured before the system dialog.
     */
    public synchronized boolean antwort(boolean sichtbar, BooleanSupplier aktuellerGrant) {
        boolean erlaubt = aktuellerGrant.getAsBoolean();
        boolean hinweis = !geschlossen && offen != 0 && zugeordnet && sichtbar && !erlaubt;
        offen = 0;
        zugeordnet = false;
        return hinweis;
    }

    /**
     * Keep the OS result slot occupied until it returns. Clearing it on stop
     * would allow an old callback to consume a newer request on this Activity.
     */
    public synchronized void unterbrechen() { zugeordnet = false; }

    public synchronized boolean offen() { return offen != 0 && !geschlossen; }

    @Override public synchronized void close() {
        geschlossen = true;
        offen = 0;
        zugeordnet = false;
    }
}
