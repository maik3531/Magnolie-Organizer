using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record TelefonBluetoothCandidate(string Id, string Address, string Name, bool Paired);
internal sealed class TelefonBluetoothLink(string address, Stream stream, Action? close = null) : IDisposable
{
    internal string Address => address;
    internal Stream Stream => stream;
    private int disposed;
    public void Dispose() { if (Interlocked.Exchange(ref disposed, 1) == 0) { try { stream.Dispose(); } finally { close?.Invoke(); } } }
}
internal interface ITelefonBluetoothClient
{
    Task<IReadOnlyList<TelefonBluetoothCandidate>> DiscoverAsync(CancellationToken cancellation);
    Task PairAsync(TelefonBluetoothCandidate device, CancellationToken cancellation);
    Task<TelefonBluetoothLink> ConnectAsync(string address, CancellationToken cancellation);
}
internal static class TelefonBluetoothClient
{
    internal static bool ValidAddress(string value) => Regex.IsMatch(value, "\\A[0-9A-F]{2}(:[0-9A-F]{2}){5}\\z");
    internal static ITelefonBluetoothClient? Create()
    {
#if WINDOWS
        return new WindowsTelefonBluetoothClient();
#else
        return null;
#endif
    }
    internal static JsonObject Control(string type, string nonce) => new() { ["p"] = TelefonInvitation.Protocol, ["type"] = type, ["nonce"] = nonce };
    internal static async Task<(string Id, string Nonce)> AvailableAsync(TelefonBluetoothLink link, string selected, CancellationToken cancellation)
    {
        if (!ValidAddress(selected) || link.Address != selected) throw new InvalidDataException(NativeLocalization.Gettext("Wrong Bluetooth device."));
        var hello = await TelefonCoordinator.ReadFrameWithinAsync(link.Stream, 2048, TimeSpan.FromSeconds(3), cancellation);
        if (hello.Count != 4 || hello["p"]?.GetValue<string>() != TelefonInvitation.Protocol || hello["type"]?.GetValue<string>() != "bluetooth_available" ||
            hello["device_id"]?.GetValue<string>() is not { } id || !Guid.TryParseExact(id, "D", out var guid) || guid.ToString() != id)
            throw new InvalidDataException();
        var nonce = hello["nonce"]!.GetValue<string>();
        _ = TelefonCrypto.StrictBase64(hello, "nonce", 16);
        return (id, nonce);
    }
    internal static async Task InviteAsync(Stream stream, string target, string nonce, JsonObject identity, CancellationToken cancellation)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(60));
        var offer = identity.DeepClone().AsObject();
        offer["p"] = TelefonInvitation.Protocol; offer["type"] = "bluetooth_offer";
        offer["target"] = target; offer["nonce"] = nonce; offer["ttl"] = 60;
        await TelefonCoordinator.WriteFrameAsync(stream, offer, deadline.Token);
        for (var count = 0; count < 240; count++)
        {
            await TelefonCoordinator.WriteFrameAsync(stream, Control("wait", nonce), deadline.Token);
            var response = await TelefonCoordinator.ReadFrameWithinAsync(stream, 2048, TimeSpan.FromSeconds(2), deadline.Token);
            if (JsonNode.DeepEquals(response, Control("accepted", nonce))) return;
            if (!JsonNode.DeepEquals(response, Control("pending", nonce))) throw new OperationCanceledException();
            await Task.Delay(250, deadline.Token);
        }
        throw new OperationCanceledException();
    }
}
