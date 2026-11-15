package io.gitlab.maik3531.magnolienotes.netz;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.function.BooleanSupplier;

/** Transport lifetime only: no dialogs, pairing, account or persisted consent. */
public final class LanTor {
    private final BooleanSupplier status;
    private final Set<AutoCloseable> resources = new LinkedHashSet<>();
    private long generation;
    private boolean previouslyAllowed = true;

    public LanTor(BooleanSupplier status) { this.status = status; }
    public boolean erlaubt() {
        final boolean allowed;
        final List<AutoCloseable> closing;
        synchronized (this) {
            allowed = status.getAsBoolean();
            if (!allowed && previouslyAllowed) generation++;
            previouslyAllowed = allowed;
            closing = allowed ? new ArrayList<>() : new ArrayList<>(resources);
            if (!allowed) resources.clear();
        }
        for (AutoCloseable resource : closing) {
            try { resource.close(); } catch (Exception ignored) { /* close remaining resources */ }
        }
        return allowed;
    }
    public long marke() {
        final long token;
        synchronized (this) { token = generation; }
        if (!erlaubt()) throw new IllegalStateException("LAN permission missing");
        return token;
    }
    public boolean aktuell(long token) {
        if (!erlaubt()) return false;
        synchronized (this) { return token == generation; }
    }
    public AutoCloseable beobachten(AutoCloseable resource) {
        synchronized (this) { resources.add(resource); }
        if (!erlaubt()) throw new IllegalStateException("LAN permission missing");
        return () -> { synchronized (this) { resources.remove(resource); } };
    }
}
