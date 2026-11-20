package io.gitlab.maik3531.magnolienotes.netz;

import java.io.IOException;
import java.net.InetAddress;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Shared host/JUnit cases. Synthetic addresses and resources; no DNS or sockets. */
public final class LanRoutenCases {
    private int checks;
    private void require(boolean value) {
        checks++;
        if (!value) throw new AssertionError("LAN routing case " + checks);
    }
    private static InetAddress v4(int a, int b, int c, int d) throws Exception {
        return InetAddress.getByAddress(new byte[] {(byte)a, (byte)b, (byte)c, (byte)d});
    }
    private static LanRoutenRegel.Route route(InetAddress prefix, int bits, boolean gateway) {
        return new LanRoutenRegel.Route(prefix, bits, gateway);
    }
    private boolean needs(InetAddress address, LanRoutenRegel.Netz network,
                          boolean internet, LanRoutenRegel.Route... routes) {
        return LanRoutenRegel.brauchtLan(address, network, internet, Arrays.asList(routes));
    }

    public static int run() throws Exception {
        LanRoutenCases cases = new LanRoutenCases();
        cases.routes();
        cases.resolution();
        cases.lifetimes();
        return cases.checks;
    }

    private void routes() throws Exception {
        InetAddress peer = v4(203,0,113,42), remote = v4(198,51,100,7);
        LanRoutenRegel.Route fallback = route(v4(0,0,0,0), 0, true);
        LanRoutenRegel.Route local = route(v4(203,0,113,0), 24, false);
        require(!LanRegel.lokal(peer)); // A public-looking address still can be on-link.
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, fallback, local));
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, local, fallback));
        require(!needs(remote, LanRoutenRegel.Netz.BROADCAST, true, fallback, local));
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, fallback,
            route(v4(203,0,113,0), 24, true))); // public LAN behind a router
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, route(peer, 32, false)));
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, route(v4(0,0,0,0), 0, false)));
        require(needs(remote, LanRoutenRegel.Netz.BROADCAST, true, fallback,
            route(v4(0,0,0,0), 0, false))); // equal-cost ambiguous default routes
        require(needs(remote, LanRoutenRegel.Netz.BROADCAST, false, fallback));
        require(needs(remote, LanRoutenRegel.Netz.BROADCAST, true));
        require(needs(remote, LanRoutenRegel.Netz.BROADCAST, true, local));
        require(needs(remote, LanRoutenRegel.Netz.UNKNOWN, true, fallback));
        require(LanRoutenRegel.brauchtLan(remote, LanRoutenRegel.Netz.BROADCAST, true, null));
        require(LanRoutenRegel.brauchtLan(remote, LanRoutenRegel.Netz.BROADCAST,
            true, Arrays.asList(fallback, null)));
        for (LanRoutenRegel.Netz network : List.of(LanRoutenRegel.Netz.CELLULAR, LanRoutenRegel.Netz.VPN)) {
            require(!needs(peer, network, true, fallback, local));
            require(needs(v4(10,1,2,3), network, true, fallback)); // conservative legacy guard
        }
        // Non-byte-aligned prefixes and both address families must be handled exactly.
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, fallback,
            route(v4(203,0,113,0), 25, false)));
        require(!needs(v4(203,0,113,200), LanRoutenRegel.Netz.BROADCAST, true,
            fallback, route(v4(203,0,113,0), 25, false)));
        byte[] bytes = new byte[16]; bytes[0] = 0x20; bytes[1] = 0x01;
        bytes[2] = 0x0d; bytes[3] = (byte)0xb8; bytes[15] = 42;
        InetAddress peer6 = InetAddress.getByAddress(bytes);
        LanRoutenRegel.Route fallback6 = route(InetAddress.getByAddress(new byte[16]), 0, true);
        require(needs(peer6, LanRoutenRegel.Netz.BROADCAST, true, fallback6, route(peer6, 64, false)));
        require(!needs(peer6, LanRoutenRegel.Netz.BROADCAST, true, fallback6));
        require(needs(peer6, LanRoutenRegel.Netz.BROADCAST, true, fallback));
        require(needs(peer, LanRoutenRegel.Netz.BROADCAST, true, fallback6));
        for (int invalid : new int[] {-1, 33, 128}) {
            try { route(peer, invalid, true); throw new AssertionError("invalid prefix accepted"); }
            catch (IllegalArgumentException expected) { require(true); }
        }
        for (InetAddress special : List.of(v4(0,0,0,0), v4(127,0,0,1), v4(169,254,0,1), v4(239,1,2,3)))
            require(needs(special, LanRoutenRegel.Netz.BROADCAST, true, fallback));
    }

    private void resolution() throws Exception {
        InetAddress peer = v4(203,0,113,42);
        AtomicInteger resolutions = new AtomicInteger(), checks = new AtomicInteger();
        LanRegel.Aufloesung resolver = host -> { resolutions.incrementAndGet(); return peer; };
        LanRegel.Pruefung denied = () -> { checks.incrementAndGet(); throw new IOException("synthetic denial"); };
        try { LanRegel.ziel("sync.example.org", denied, resolver, address -> true); throw new AssertionError(); }
        catch (IOException expected) { require(resolutions.get() == 1 && checks.get() == 1); }
        require(LanRegel.ziel("sync.example.org", denied, resolver, address -> false) == peer);
        require(resolutions.get() == 2 && checks.get() == 1);
        try { LanRegel.ziel("printer.local.", denied, resolver, address -> false); throw new AssertionError(); }
        catch (IOException expected) { require(resolutions.get() == 2); }
    }

    private void lifetimes() throws Exception {
        AtomicBoolean local = new AtomicBoolean(false), grant = new AtomicBoolean(false);
        AtomicInteger closed = new AtomicInteger();
        LanZielWache remote = new LanZielWache(() -> !local.get() || grant.get(), closed::incrementAndGet);
        require(remote.aktuell()); // Public remote traffic survives a missing LAN grant.
        remote.pruefen("waiting");
        local.set(true); // Route became LAN after DNS/initial classification.
        require(!remote.aktuell()); require(closed.get() == 1);
        require(!remote.aktuell()); require(closed.get() == 1);
        grant.set(true);
        require(!remote.aktuell()); // New OS grant cannot revive the old transfer.
        try { remote.pruefen("waiting"); throw new AssertionError("stale transfer revived"); }
        catch (IOException expected) { require(expected.getMessage().equals("waiting")); }
        local.set(false); require(!remote.aktuell()); remote.close();
        LanZielWache resumed = new LanZielWache(() -> !local.get() || grant.get(), closed::incrementAndGet);
        require(resumed.aktuell()); grant.set(false); require(resumed.aktuell());
        local.set(true); require(!resumed.aktuell()); require(closed.get() == 2); resumed.close();
        grant.set(true);
        LanZielWache completed = new LanZielWache(grant::get, closed::incrementAndGet);
        completed.close(); completed.close(); grant.set(false);
        require(!completed.aktuell()); require(closed.get() == 2);
        AtomicInteger reads = new AtomicInteger();
        try {
            new LanZielWache(() -> reads.incrementAndGet() == 1, closed::incrementAndGet);
            throw new AssertionError("registration race accepted");
        } catch (IllegalStateException expected) { require(closed.get() == 3); }
        try { new LanZielWache(() -> false, closed::incrementAndGet); throw new AssertionError(); }
        catch (IllegalStateException expected) { require(closed.get() == 3); } // caller still owns acquisition
    }

    public static void main(String[] args) throws Exception {
        System.out.println("PASS: " + run() + " route/connection assertions (synthetic, not Android acceptance)");
    }
}
