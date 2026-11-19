import io.gitlab.maik3531.magnolienotes.netz.LanTor;
import io.gitlab.maik3531.magnolienotes.netz.LanRegel;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Executes the actual production gate, with synthetic platform status; no Android SDK. */
public final class LanGuardProbe {
    private static int checks;
    private static void require(boolean value) {
        checks++;
        if (!value) throw new AssertionError("check " + checks);
    }
    public static void main(String[] args) throws Exception {
        for (int api : new int[] {26,28,35,36,37,38})
            for (int target : new int[] {35,36,37,38})
                for (boolean grant : new boolean[] {false,true}) {
                    LanTor gate = new LanTor(() -> !LanRegel.erforderlich(api,target) || grant);
                    require(gate.erlaubt() == (api < 37 || target < 37 || grant));
                }
        AtomicBoolean grant = new AtomicBoolean(false);
        for (int restart=0; restart<3; restart++) {
            LanTor gate = new LanTor(grant::get);
            for (int tick=0; tick<30; tick++) require(!gate.erlaubt());
            AtomicBoolean closed = new AtomicBoolean();
            try { gate.beobachten(() -> closed.set(true)); throw new AssertionError(); }
            catch (IllegalStateException expected) { require(closed.get()); }
        }
        grant.set(true);
        LanTor gate = new LanTor(grant::get);
        long token = gate.marke();
        require(gate.aktuell(token));
        AtomicInteger closed = new AtomicInteger();
        gate.beobachten(() -> { throw new Exception("synthetic close failure"); });
        gate.beobachten(closed::incrementAndGet);
        grant.set(false);
        require(!gate.erlaubt()); require(!gate.erlaubt()); require(closed.get()==1);
        grant.set(true);
        require(gate.erlaubt()); require(!gate.aktuell(token)); require(gate.aktuell(gate.marke()));
        AutoCloseable completed = gate.beobachten(closed::incrementAndGet);
        completed.close(); grant.set(false); gate.erlaubt(); require(closed.get()==1);
        AtomicInteger reads = new AtomicInteger();
        LanTor racing = new LanTor(() -> reads.incrementAndGet()==1);
        long old = racing.marke();
        try { racing.beobachten(closed::incrementAndGet); throw new AssertionError(); }
        catch (IllegalStateException expected) { require(closed.get()==2); }
        require(!racing.aktuell(old));
        addressRules();
        System.out.println("PASS: " + checks + " production-gate assertions (synthetic, not Android acceptance)");
    }

    private static void addressRules() throws Exception {
        java.net.InetAddress local = java.net.InetAddress.getByAddress(new byte[] {127,0,0,1});
        java.net.InetAddress remote = java.net.InetAddress.getByAddress(new byte[] {(byte)203,0,113,1});
        AtomicInteger resolutions = new AtomicInteger();
        LanRegel.Aufloesung resolver = host -> { resolutions.incrementAndGet(); return local; };
        LanRegel.Pruefung denied = () -> { throw new java.io.IOException("synthetic denial"); };
        for (String host : new String[] {"printer.local", "PRINTER.LOCAL.", "printer.local..", "printer", "printer.", "", "printer.local\u3002"}) {
            require(LanRegel.lokalerName(host));
            try { LanRegel.ziel(host, denied, resolver); throw new AssertionError("Resolved before grant: " + host); }
            catch (java.io.IOException expected) { require(resolutions.get() == 0); }
        }
        require(!LanRegel.lokalerName("sync.example.org."));
        require(!LanRegel.lokalerName("2001:db8::1"));
        try { LanRegel.ziel("sync.example.org", denied, resolver); throw new AssertionError(); }
        catch (java.io.IOException expected) { require(resolutions.get() == 1); }
        AtomicInteger grantReads = new AtomicInteger();
        require(LanRegel.ziel("sync.example.org", () -> grantReads.incrementAndGet(), host -> remote) == remote);
        require(grantReads.get() == 0); // public remote transport does not require LAN
        require(LanRegel.ziel("printer.local.", () -> grantReads.incrementAndGet(), host -> local) == local);
        require(grantReads.get() == 2); // local name before DNS, local address afterwards
        for (byte[] bytes : new byte[][] {{10,0,0,1}, {(byte)169,(byte)254,1,1}, {(byte)224,0,0,1}, new byte[4],
                {(byte)0xfc,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1}})
            require(LanRegel.lokal(java.net.InetAddress.getByAddress(bytes)));
        require(!LanRegel.lokal(remote));
    }
}
