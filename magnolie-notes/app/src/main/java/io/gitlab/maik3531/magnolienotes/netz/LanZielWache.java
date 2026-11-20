package io.gitlab.maik3531.magnolienotes.netz;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;

/** Per-connection lifetime: changing routes/grants cannot revive a stopped request. */
public final class LanZielWache implements AutoCloseable {
    private final LanTor gate;
    private final long token;
    private final AutoCloseable registration;
    private final AtomicBoolean closed = new AtomicBoolean();

    public LanZielWache(BooleanSupplier permitted, AutoCloseable resource) {
        gate = new LanTor(permitted);
        // The caller owns the socket throughout construction, including failures.
        token = gate.marke();
        registration = gate.beobachten(resource);
    }

    public boolean aktuell() { return !closed.get() && gate.aktuell(token); }

    public void pruefen(String message) throws IOException {
        if (!aktuell()) throw new IOException(message);
    }

    @Override public void close() {
        if (closed.compareAndSet(false, true)) {
            try { registration.close(); }
            catch (Exception impossible) { throw new IllegalStateException(impossible); }
        }
    }
}
