package io.gitlab.maik3531.magnolienotes.netz;

import java.net.InetAddress;
import java.util.List;

/** Conservative routing classification, not a substitute for Android's OS grant. */
public final class LanRoutenRegel {
    private LanRoutenRegel() {}

    public enum Netz { BROADCAST, CELLULAR, VPN, UNKNOWN }

    /** Snapshot of a route from LinkProperties; no DNS or network I/O. */
    public static final class Route {
        private final byte[] prefix;
        private final int bits;
        private final boolean gateway;

        public Route(InetAddress prefix, int bits, boolean gateway) {
            this.prefix = prefix.getAddress().clone();
            if (bits < 0 || bits > this.prefix.length * 8)
                throw new IllegalArgumentException("Invalid network prefix");
            this.bits = bits;
            this.gateway = gateway;
        }

        boolean matches(InetAddress address) {
            byte[] value = address.getAddress();
            if (value.length != prefix.length) return false;
            for (int bit = 0; bit < bits; bit++) {
                int mask = 1 << (7 - bit % 8);
                if ((value[bit / 8] & mask) != (prefix[bit / 8] & mask)) return false;
            }
            return true;
        }
    }

    /**
     * Public numbering does not prove a remote destination. On broadcast networks,
     * on-link and specific routes require LAN access, including routed public LANs.
     * Only a known Internet default gateway is classified as a remote path. Missing,
     * unknown or inconsistent information waits for permission instead of guessing.
     * Mobile/VPN routes are exempt, except the conservative special-address guard.
     */
    public static boolean brauchtLan(InetAddress address, Netz network,
                                    boolean internet, List<Route> routes) {
        if (LanRegel.lokal(address)) return true;
        if (network == Netz.CELLULAR || network == Netz.VPN) return false;
        if (network != Netz.BROADCAST || routes == null || routes.isEmpty()) return true;
        int longest = -1;
        boolean direct = false;
        for (Route route : routes) {
            if (route == null) return true;
            if (!route.matches(address)) continue;
            if (route.bits > longest) {
                longest = route.bits;
                direct = !route.gateway;
            } else if (route.bits == longest) {
                direct |= !route.gateway;
            }
        }
        return longest != 0 || direct || !internet;
    }
}
