using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMetadataCommandTests
{
    private sealed class Side
    {
        internal readonly NativeFileControlIdentity Identity;
        internal NativeFileControlPeer Peer;
        internal NativeLocalFileGrant Local;
        internal NativeFileControlSession Session;
        private readonly Func<long> clock;
        internal Side(NativeFileControlIdentity identity, NativeFileControlIdentity other, DeviceFileGrantState grants, Func<long> clock)
        {
            Identity = identity; this.clock = clock;
            Peer = new(other.DeviceId, other.IdentitySha256, new object(), true, true, true, true, true, new string('f', 64));
            Local = new(grants, new object(), true); Session = NewSession();
        }
        internal NativeFileControlSession NewSession() => new(Identity, () => Peer, () => Local, clock);
    }
    private sealed class Pair : IDisposable
    {
        internal long Now = 100;
        internal bool ClockFails;
        internal readonly Side Phone, Desktop;
        internal Pair()
        {
            long Clock() => ClockFails ? throw new InvalidOperationException("fixture native clock failure") : Now;
            var phone = new NativeFileControlIdentity("sender_fixture_01", new string('d', 64));
            var desktop = new NativeFileControlIdentity("receiver_fixture_01", new string('e', 64));
            Phone = new(phone, desktop, new(3, new string('a', 64), false, false), Clock);
            Desktop = new(desktop, phone, new(7, new string('b', 64), false, true), Clock);
        }
        internal static DeviceFileControlPacket Send(Side sender, Side receiver)
        {
            var packet = sender.Session.Packet(); sender.Session.MarkSent(packet);
            receiver.Session.ObserveRemote(DeviceFileControlPacket.Parse(packet.Wire()), receiver.Peer);
            return packet;
        }
        internal void Handshake()
        {
            Send(Phone, Desktop); Send(Desktop, Phone);
            if (Phone.Session.NeedsPacket) Send(Phone, Desktop);
            if (Desktop.Session.NeedsPacket) Send(Desktop, Phone);
        }
        public void Dispose() { Phone.Session.Dispose(); Desktop.Session.Dispose(); }
    }

    internal static Task BootstrapAsync()
    {
        using var pair = new Pair(); var desktop = pair.Desktop.Session;
        TestAssert.That(desktop.RemoteControlWitness() is null, "Absent remote controls produced a witness.");
        TestAssert.Throws<InvalidDataException>(() => desktop.ReceiverCommandTicket(), "Unconfirmed controls authorized source metadata.");
        Pair.Send(pair.Phone, pair.Desktop); Pair.Send(pair.Desktop, pair.Phone);
        TestAssert.Throws<InvalidDataException>(() => desktop.ReceiverCommandTicket(), "Missing final native echo authorized metadata.");
        Pair.Send(pair.Phone, pair.Desktop);
        var before = pair.Desktop.Local.Grants;
        var ticket = desktop.ReceiverCommandTicket(); var captured = desktop.ReceiverCommandWitness(ticket);
        TestAssert.That(desktop.ReceiverCommandCurrent(ticket) && captured == desktop.RemoteControlWitness() &&
            desktop.Binding(new string('c', 64)) is null, "Metadata-only agreement became a data READ grant.");
        TestAssert.Throws<InvalidDataException>(() => desktop.ReceiverCommandTicket(), "A second metadata command overlapped the owner.");
        TestAssert.That(!desktop.ReceiverCommandCurrent(null) && !desktop.ReceiverCommandCurrent(new NativeReceiverCommandTicket()),
            "A foreign/absent native ticket became current.");
        TestAssert.Throws<InvalidDataException>(() => desktop.FinishReceiverCommand(new NativeReceiverCommandTicket()), "Foreign cleanup was accepted.");
        // An exact source configure changes the source's policy while its
        // metadata reply is pending. New data must still wait for a fresh echo.
        pair.Phone.Local = new(new(4, new string('e', 64), true, false), pair.Phone.Local.Owner, true);
        Pair.Send(pair.Phone, pair.Desktop);
        TestAssert.That(desktop.ReceiverCommandCurrent(ticket) && desktop.ReceiverCommandWitness(ticket) == captured &&
            desktop.RemoteControlWitness()!.Value.Sequence > captured.Sequence && desktop.Binding(new string('c', 64)) is null,
            "A native metadata completion required/invented the new data echo or changed its original witness.");
        Pair.Send(pair.Desktop, pair.Phone);
        TestAssert.That(desktop.Binding(new string('c', 64)) is not null && pair.Desktop.Local.Grants.Same(before),
            "Only the actual fresh control echo may establish data scope; metadata must not edit local grants.");
        desktop.FinishReceiverCommand(ticket);
        TestAssert.That(!desktop.ReceiverCommandCurrent(ticket), "Finished command retained metadata authority.");
        TestAssert.Throws<InvalidDataException>(() => desktop.FinishReceiverCommand(ticket), "Duplicate completion silently succeeded.");
        TestAssert.Throws<InvalidDataException>(() => desktop.ReceiverCommandWitness(ticket), "A retired owner exposed a new witness.");
        var next = desktop.ReceiverCommandTicket(); desktop.Dispose();
        TestAssert.That(!desktop.ReceiverCommandCurrent(next) && desktop.RemoteControlWitness() is null &&
            desktop.Binding(new string('c', 64)) is null, "Closed session retained metadata or data authority.");
        desktop.FinishReceiverCommand(next); // Exact finally-cleanup is still legal after revocation.
        return Task.CompletedTask;
    }

    internal static Task WithdrawalAsync()
    {
        foreach (var change in new[] { "ready", "paired", "own", "remoteOwn", "supported", "owner", "key", "pairing",
            "localOwner", "localPermission", "policy", "handlers", "localV1", "remoteV1", "remoteSession", "expired", "rollback", "clock" })
        {
            using var pair = new Pair(); pair.Handshake();
            var side = pair.Desktop; var session = side.Session; var ticket = session.ReceiverCommandTicket();
            var original = side.Peer; var local = side.Local;
            side.Peer = change switch
            {
                "ready" => original with { Ready = false }, "paired" => original with { Paired = false },
                "own" => original with { OwnDevice = false }, "remoteOwn" => original with { RemoteOwnDevice = false },
                "supported" => original with { ControlSupported = false }, "owner" => original with { Owner = new object() },
                "key" => original with { IdentitySha256 = new string('c', 64) },
                "pairing" => original with { PairingEpoch = new string('d', 64) }, _ => original
            };
            if (change == "localOwner") side.Local = new(local.Grants, new object(), true);
            if (change == "localPermission") side.Local = new(new(8, new string('c', 64), false, true), local.Owner, true);
            if (change == "policy") side.Local = new(local.Grants, local.Owner, true, policyReady: false);
            if (change == "handlers") side.Local = new(new(8, new string('c', 64), false, false), local.Owner, false);
            if (change == "localV1") side.Local = new(new(7, new string('b', 64), false, true, [2]), local.Owner, true);
            if (change == "remoteV1")
            {
                pair.Phone.Local = new(new(3, new string('a', 64), false, false, [2]), pair.Phone.Local.Owner, true);
                Pair.Send(pair.Phone, side);
            }
            if (change == "remoteSession")
            {
                pair.Phone.Session.Dispose(); pair.Phone.Session = pair.Phone.NewSession(); Pair.Send(pair.Phone, side);
            }
            if (change == "expired") pair.Now += DeviceFileControl.MaximumTtlMs;
            if (change == "rollback") { pair.Now++; TestAssert.That(session.ReceiverCommandCurrent(ticket), "Valid monotonic advance rejected."); pair.Now--; }
            if (change == "clock") pair.ClockFails = true;
            if (change == "clock") TestAssert.Throws<InvalidOperationException>(() => session.ReceiverCommandCurrent(ticket), "Clock failure was hidden.");
            else TestAssert.That(!session.ReceiverCommandCurrent(ticket), "Withdrawn native metadata scope stayed current: " + change);
            side.Peer = original; side.Local = local; pair.ClockFails = false; pair.Now = 200;
            TestAssert.That(!session.ReceiverCommandCurrent(ticket), "Restoring metadata revived an invalid old ticket: " + change);
            session.FinishReceiverCommand(ticket);
        }
        foreach (var badTime in new[] { -1L, long.MaxValue - 1 })
        {
            using var pair = new Pair(); pair.Handshake(); pair.Now = badTime;
            TestAssert.Throws<InvalidDataException>(() => pair.Desktop.Session.ReceiverCommandTicket(), "Out-of-range TTL/clock was accepted.");
            pair.Now = 100;
            var ticket = pair.Desktop.Session.ReceiverCommandTicket(); pair.Desktop.Session.FinishReceiverCommand(ticket);
        }
        return Task.CompletedTask;
    }

    internal static Task SourceCleanupLeaseAsync()
    {
        using var pair = new Pair(); pair.Handshake(); var session = pair.Desktop.Session;
        var ticket = session.ReceiverCommandTicket(); var id = Guid.NewGuid().ToString("D");
        var lease = session.RetainSourceRun(ticket, id, new string('a', 64), "images");
        TestAssert.Throws<InvalidDataException>(() => session.RetainSourceRun(ticket, id, new string('a', 64), "images"), "Duplicate retained source run admitted.");
        session.FinishReceiverCommand(ticket);
        var forged = new NativeFileControlSession.SourceRunLease(id, lease.Version, "images", lease.RemoteSession);
        TestAssert.Throws<InvalidDataException>(() => session.CleanupCommandTicket(forged), "Unregistered copy of source-run metadata acquired cleanup authority.");
        TestAssert.Throws<InvalidDataException>(() => session.ReleaseSourceRun(forged), "Foreign source lease removed original ownership.");
        pair.Desktop.Local = new(new(8, new string('c', 64), false, false, [2]), pair.Desktop.Local.Owner, false, policyReady: false);
        var cleanup = session.CleanupCommandTicket(lease);
        TestAssert.That(session.ReceiverCommandCurrent(cleanup) && !lease.GrantsReadAuthority && session.Binding(new string('e', 64)) is null,
            "Source cleanup required/restored data/handler/manifest/policy availability.");
        TestAssert.Throws<InvalidDataException>(() => session.RetainSourceRun(cleanup, Guid.NewGuid().ToString("D"), lease.Version, "images"), "Cleanup command created new source READ ownership.");
        TestAssert.Throws<InvalidDataException>(() => session.CleanupCommandTicket(lease), "Two cleanup commands overlapped.");
        pair.Now += DeviceFileControl.MaximumTtlMs;
        TestAssert.That(!session.ReceiverCommandCurrent(cleanup), "Cleanup ticket escaped its bounded deadline.");
        session.FinishReceiverCommand(cleanup);
        pair.Phone.Session.Dispose(); pair.Phone.Session = pair.Phone.NewSession(); Pair.Send(pair.Phone, pair.Desktop);
        TestAssert.Throws<InvalidDataException>(() => session.CleanupCommandTicket(lease), "New source session inherited an old source lease.");
        TestAssert.That(lease.Invalidated, "Session change did not permanently invalidate retained source ownership.");
        session.ReleaseSourceRun(lease);
        TestAssert.Throws<InvalidDataException>(() => session.ReleaseSourceRun(lease), "Released source lease was reusable.");
        return Task.CompletedTask;
    }
}
