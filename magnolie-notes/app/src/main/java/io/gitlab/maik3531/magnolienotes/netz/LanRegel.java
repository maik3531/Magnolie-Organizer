package io.gitlab.maik3531.magnolienotes.netz;

public final class LanRegel {
    private LanRegel() {}
    public static boolean erforderlich(int api, int target) { return api >= 37 && target >= 37; }

    /** Classify before DNS, including absolute and IDN dot spellings. */
    public static boolean lokalerName(String host) {
        String name = host.trim();
        if (name.indexOf(':') >= 0) return false; // numeric IPv6 is checked after parsing
        try { name = java.net.IDN.toASCII(name).toLowerCase(java.util.Locale.ROOT); }
        catch (IllegalArgumentException invalid) { return true; }
        while (name.endsWith(".")) name = name.substring(0, name.length() - 1);
        return name.endsWith(".local") || name.indexOf('.') < 0;
    }

    @FunctionalInterface public interface Pruefung { void pruefen() throws java.io.IOException; }
    @FunctionalInterface public interface Aufloesung { java.net.InetAddress aufloesen(String host) throws java.io.IOException; }

    /** One resolution and the exact returned address; no second DNS lookup. */
    public static java.net.InetAddress ziel(String host, Pruefung grant, Aufloesung resolver) throws java.io.IOException {
        if (lokalerName(host)) grant.pruefen();
        java.net.InetAddress address = resolver.aufloesen(host);
        if (lokal(address)) grant.pruefen();
        return address;
    }

    public static boolean lokal(java.net.InetAddress address) {
        byte[] bytes = address.getAddress();
        return address.isSiteLocalAddress() || address.isLinkLocalAddress() || address.isLoopbackAddress() ||
            address.isAnyLocalAddress() || address.isMulticastAddress() ||
            (bytes.length == 16 && (bytes[0] & 0xfe) == 0xfc);
    }
}
