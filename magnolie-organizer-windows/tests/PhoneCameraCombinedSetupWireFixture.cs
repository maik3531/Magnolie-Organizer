namespace MagnolieOrganizer.Windows;

// Only compiled into the test host. Production has no caller-supplied hash,
// transaction or alternate resource factory/decoder entry.
internal sealed partial class PhoneCameraCombinedSetupWire
{
    internal static PhoneCameraCombinedSetupWire CombinedWireFixtureCreate(Mode mode, Guid transaction, byte[] source, byte[] helper) =>
        new(Header(mode, transaction, source, helper), parent: true);
    internal static Task<PhoneCameraCombinedSetupWire> CombinedWireFixtureReadAsync(Stream stream, Mode mode,
        byte[] source, byte[] helper, CancellationToken cancellation = default) => ReadExpectedAsync(stream, mode, source, helper, cancellation);
}
