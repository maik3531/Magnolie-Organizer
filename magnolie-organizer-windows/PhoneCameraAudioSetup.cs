using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal enum PhoneCameraAudioSetupState { Cancelled, Unsupported, ExistingDevice, Failed, RebootRequired, UnknownPending, PreparedOnly }
internal sealed record PhoneCameraAudioSetupResult(PhoneCameraAudioSetupState State, string? FailureReason = null, int? NativeError = null, int? ElevatedExit = null)
{
    internal string Driver => PhoneCameraAudioPackage.DriverName;
    internal string ManualUrl => PhoneCameraAudioPackage.ManualUrl;
}

// Bounded original local setup IPC, never phone-control or capture authority.
internal static class PhoneCameraAudioSetupWire
{
    internal const int MaximumArchive = 4 * 1024 * 1024;
    internal const int MaximumNativeResult = 16384;
    private static readonly string[] NativeResultFields = ["schema", "driver", "mode", "state", "error", "ownDeviceRegistered",
        "ownDeviceRemoved", "rebootRequired", "defaultsPreserved", "ownInstance"];
    internal static bool AllowsNativeMode(string mode, bool preparationOnly) => mode == "--plan" || !preparationOnly && mode == "--install";
    internal static async Task WriteIntAsync(Stream stream, int value, CancellationToken cancellation)
    {
        var bytes = new byte[4]; System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(bytes, value);
        await stream.WriteAsync(bytes, cancellation); await stream.FlushAsync(cancellation);
    }
    internal static async Task<int> ReadIntAsync(Stream stream, CancellationToken cancellation)
    {
        var bytes = new byte[4]; await stream.ReadExactlyAsync(bytes, cancellation);
        return System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(bytes);
    }
    private static bool Fields(JsonElement root, string[] fields)
    {
        if (root.ValueKind != JsonValueKind.Object) return false;
        var names = root.EnumerateObject().Select(p => p.Name).ToArray();
        return names.Length == fields.Length && names.Order(StringComparer.Ordinal).SequenceEqual(fields.Order(StringComparer.Ordinal));
    }
    internal static bool IsOriginalPlan(string json, out bool existing)
    {
        existing = false;
        using var document = JsonDocument.Parse(json); var root = document.RootElement;
        if (!Fields(root, ["schema", "driver", "mode", "supportedHost", "elevated", "protectedPackage", "existingTransaction",
            "existingDeviceCount", "canInspectAudioDefaults", "endpointPolicy", "installationAttempted"])) return false;
        if (root.GetProperty("schema").GetInt32() != 1 || root.GetProperty("driver").GetString() != "VB-CABLE" || root.GetProperty("mode").GetString() != "plan" ||
            !root.GetProperty("supportedHost").GetBoolean() || !root.GetProperty("elevated").GetBoolean() || !root.GetProperty("protectedPackage").GetBoolean() ||
            root.GetProperty("existingTransaction").GetBoolean() || !root.GetProperty("canInspectAudioDefaults").GetBoolean() ||
            root.GetProperty("endpointPolicy").GetString() != "explicit_app_selection_never_system_default" || root.GetProperty("installationAttempted").GetBoolean()) return false;
        var count = root.GetProperty("existingDeviceCount").GetInt32(); existing = count > 0; return count == 0;
    }
    internal static bool IsRebootResult(string json) => IsRebootResult(json, out _);
    internal static bool IsRebootResult(string json, out string? ownInstance)
    {
        ownInstance = null;
        using var document = JsonDocument.Parse(json); var root = document.RootElement;
        var confirmed = Fields(root, NativeResultFields) &&
            root.GetProperty("schema").GetInt32() == 1 && root.GetProperty("driver").GetString() == "VB-CABLE" && root.GetProperty("mode").GetString() == "install" &&
            root.GetProperty("state").GetString() == "reboot_required" && root.GetProperty("error").GetInt64() == 0 &&
            root.GetProperty("ownDeviceRegistered").GetBoolean() && !root.GetProperty("ownDeviceRemoved").GetBoolean() &&
            root.GetProperty("rebootRequired").GetBoolean() && root.GetProperty("defaultsPreserved").GetBoolean() &&
            root.GetProperty("ownInstance").GetString() is { Length: > 0 and < 200 };
        if (confirmed) ownInstance = root.GetProperty("ownInstance").GetString();
        return confirmed;
    }
    // Preserve a known devnode from the original helper's partial failure, not
    // a success/ownership/retry grant. Exit/state pairs match CableSetupMain.
    internal static string? KnownFailedInstance(int nativeExit, string json)
    {
        if (nativeExit is not (1603 or 1618)) return null;
        using var document = JsonDocument.Parse(json); var root = document.RootElement;
        if (!Fields(root, NativeResultFields) || root.GetProperty("schema").GetInt32() != 1 ||
            root.GetProperty("driver").GetString() != "VB-CABLE" || root.GetProperty("mode").GetString() != "install") return null;
        var state = root.GetProperty("state").GetString();
        if (!(nativeExit == 1603 && state == "failed" || nativeExit == 1618 && state is "unknown_pending" or "cleanup_pending") ||
            root.GetProperty("error").GetInt64() is < 0 or > uint.MaxValue || !root.GetProperty("ownDeviceRegistered").GetBoolean()) return null;
        _ = root.GetProperty("ownDeviceRemoved").GetBoolean();
        _ = root.GetProperty("rebootRequired").GetBoolean();
        _ = root.GetProperty("defaultsPreserved").GetBoolean();
        return root.GetProperty("ownInstance").GetString();
    }
}

/// <summary>Explicit native user action only. Not invoked by acceptance tests:
/// this path prepares ProgramData and can install a driver after actual UAC.</summary>
[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioSetup
{
    internal const string ElevatedArgument = "--phone-camera-audio-elevated";
    internal const string ElevatedPlanArgument = "--phone-camera-audio-elevated-plan";
    internal const string PreparationProbeArgument = "--phone-camera-audio-preparation-probe";
    private const string PipePrefix = "magnolie-phone-audio-";
    private const int Continue = 1, WillInstall = 2, Finished = 3;
    internal static bool ValidArguments(string[] args)
    {
        try
        {
            return args.Length == 6 && args[0] is ElevatedArgument or ElevatedPlanArgument &&
                args[1].StartsWith(PipePrefix, StringComparison.Ordinal) && IsHex(args[1][PipePrefix.Length..], 32) &&
                IsHex(args[2], 64) && int.TryParse(args[3], out var pid) && pid > 0 &&
                args[4].Length is > 1 and < 185 && new SecurityIdentifier(args[4]).Value == args[4] &&
                long.TryParse(args[5], out var start) && start > 0 && start <= DateTime.MaxValue.Ticks;
        }
        catch (ArgumentException) { return false; }
    }
    private static bool IsHex(string text, int length) => text.Length == length && !text.AsSpan().ContainsAnyExcept("0123456789abcdef");

    // Call ONLY after the explicit native installation question was accepted.
    internal static Task<PhoneCameraAudioSetupResult> RunConfirmedAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation) => RunCoreAsync(package, originalCurrent, cancellation, install: true);

    // Explicit separately approved preparation probe only. Both ends bind the
    // plan-only mode; this path can NEVER publish the install admission token.
    internal static Task<PhoneCameraAudioSetupResult> RunPreparationProbeAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation) => RunCoreAsync(package, originalCurrent, cancellation, install: false);

    private static async Task<PhoneCameraAudioSetupResult> RunCoreAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation, bool install)
    {
        ArgumentNullException.ThrowIfNull(package); ArgumentNullException.ThrowIfNull(originalCurrent);
        originalCurrent(); cancellation.ThrowIfCancellationRequested();
        var helper = PhoneCameraAudioHelperPayload.LoadEmbedded();
        if (helper is null || RuntimeInformation.ProcessArchitecture != Architecture.X64) return new(PhoneCameraAudioSetupState.Unsupported);
        using var bootstrap = PhoneCameraAudioBootstrapLease.TryAcquire();
        if (bootstrap is null) return new(PhoneCameraAudioSetupState.Unsupported);
        using var identity = WindowsIdentity.GetCurrent(); var sid = identity.User?.Value; var executable = Environment.ProcessPath;
        if (sid is null || executable is null || !executable.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ||
            Path.GetFileNameWithoutExtension(executable).Equals("dotnet", StringComparison.OrdinalIgnoreCase)) return new(PhoneCameraAudioSetupState.Unsupported);
        var pipeName = PipePrefix + Guid.NewGuid().ToString("N"); var token = RandomNumberGenerator.GetBytes(32);
        using var pipe = PhoneCameraAudioSetupPipe.CreateServer(pipeName);
        using var currentProcess = Process.GetCurrentProcess();
        var originalStart = currentProcess.StartTime.ToUniversalTime().Ticks.ToString(System.Globalization.CultureInfo.InvariantCulture);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromMinutes(3));
        Process? elevated = null; var mutationPossible = false;
        try
        {
            var start = new ProcessStartInfo(executable) { UseShellExecute = true, Verb = "runas", WorkingDirectory = AppContext.BaseDirectory };
            foreach (var argument in new[] { install ? ElevatedArgument : ElevatedPlanArgument, pipeName, Convert.ToHexString(token).ToLowerInvariant(), Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture), sid, originalStart })
                start.ArgumentList.Add(argument);
            // Await even a cancelled OS prompt; do not detach a later child.
            elevated = await Task.Run(() => Process.Start(start)) ?? throw new IOException("webcam_audio_elevation_not_started");
            var connecting = pipe.WaitForConnectionAsync(deadline.Token);
            if (await Task.WhenAny(connecting, elevated.WaitForExitAsync(deadline.Token)) != connecting)
            {
                deadline.Token.ThrowIfCancellationRequested();
                return new(PhoneCameraAudioSetupState.Failed, "elevated_child_exited_before_pipe", ElevatedExit: elevated.ExitCode);
            }
            await connecting;
            RequireOriginalPeer(pipe, (uint)elevated.Id, server: true);
            PhoneCameraAudioSetupPipe.RequireOriginalDescriptor(pipe, new SecurityIdentifier(sid));
            var echoed = new byte[32]; await pipe.ReadExactlyAsync(echoed, deadline.Token);
            if (!CryptographicOperations.FixedTimeEquals(token, echoed)) throw new CryptographicException("webcam_audio_original_setup_token_required");
            originalCurrent();
            await pipe.WriteAsync(Convert.FromHexString(helper.Sha256), deadline.Token);
            using var archive = new MemoryStream(); package.WriteOriginalArchive(archive);
            await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, checked((int)archive.Length), deadline.Token);
            await pipe.WriteAsync(archive.GetBuffer().AsMemory(0, checked((int)archive.Length)), deadline.Token); await pipe.FlushAsync(deadline.Token);
            var preparationAdmitted = false;
            while (true)
            {
                var phase = await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token);
                if (phase == Finished)
                {
                    var value = await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token);
                    if (!Enum.IsDefined(typeof(PhoneCameraAudioSetupState), value)) throw new InvalidDataException("webcam_audio_setup_result_invalid");
                    if (value == (int)PhoneCameraAudioSetupState.RebootRequired && (!install || !mutationPossible) ||
                        value == (int)PhoneCameraAudioSetupState.PreparedOnly && install)
                        throw new InvalidDataException("webcam_audio_setup_result_wrong_mode");
                    return new((PhoneCameraAudioSetupState)value);
                }
                if (phase is not (Continue or WillInstall)) throw new InvalidDataException("webcam_audio_setup_phase_invalid");
                if (!install && phase == WillInstall) throw new InvalidDataException("webcam_audio_plan_cannot_install");
                if (phase == Continue && preparationAdmitted || phase == WillInstall && (!preparationAdmitted || mutationPossible))
                    throw new InvalidDataException("webcam_audio_setup_phase_replayed");
                originalCurrent(); deadline.Token.ThrowIfCancellationRequested();
                preparationAdmitted = true;
                if (phase == WillInstall) mutationPossible = true;
                await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, Continue, deadline.Token);
            }
        }
        catch (Win32Exception error) when (error.NativeErrorCode == 1223) { return new(PhoneCameraAudioSetupState.Cancelled, "uac_cancelled", error.NativeErrorCode); }
        catch (OperationCanceledException) { return new(mutationPossible ? PhoneCameraAudioSetupState.UnknownPending : PhoneCameraAudioSetupState.Cancelled, "setup_ipc_cancelled"); }
        catch (Exception error) when (error is IOException or InvalidDataException or Win32Exception or UnauthorizedAccessException or CryptographicException or InvalidOperationException)
        {
            var reason = error switch { Win32Exception => "elevation_launch_failed", UnauthorizedAccessException => "original_peer_denied",
                CryptographicException => "original_setup_binding_failed", InvalidDataException => "setup_protocol_invalid", _ => "setup_transport_failed" };
            return new(mutationPossible ? PhoneCameraAudioSetupState.UnknownPending : PhoneCameraAudioSetupState.Failed, reason,
                error is Win32Exception native ? native.NativeErrorCode : null);
        }
        finally
        {
            pipe.Dispose(); CryptographicOperations.ZeroMemory(token);
            // Never kill SetupAPI, retry unknown mutations or abandon a child.
            // UI stays async; completion may outlast the IPC deadline.
            if (elevated is not null) { try { await elevated.WaitForExitAsync(); } finally { elevated.Dispose(); } }
        }
    }

    internal static async Task<int> RunElevatedAsync(string[] args)
    {
        if (!ValidArguments(args)) return 87;
        using var identity = WindowsIdentity.GetCurrent();
        if (identity.User?.Value != args[4] || !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) return 740;
        using var originalProcessHandle = OpenProcess(0x101000, false, int.Parse(args[3], System.Globalization.CultureInfo.InvariantCulture));
        if (originalProcessHandle.IsInvalid) return 5;
        using var parent = Process.GetProcessById(int.Parse(args[3], System.Globalization.CultureInfo.InvariantCulture));
        if (parent.StartTime.ToUniversalTime().Ticks != long.Parse(args[5], System.Globalization.CultureInfo.InvariantCulture) || parent.HasExited) return 5;
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(3));
        // The lower-elevation server may inspect identity, never impersonate
        // the elevated client's privileges. No delegation of an admin token.
        using var pipe = new NamedPipeClientStream(".", args[1], PipeDirection.InOut, PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
        await pipe.ConnectAsync(10000, deadline.Token);
        RequireOriginalPeer(pipe, (uint)parent.Id, server: false);
        PhoneCameraAudioSetupPipe.RequireOriginalDescriptor(pipe, new SecurityIdentifier(args[4]));
        if (parent.HasExited) return 5;
        var helper = PhoneCameraAudioHelperPayload.LoadEmbedded(); if (helper is null) return 50;
        await pipe.WriteAsync(Convert.FromHexString(args[2]), deadline.Token); await pipe.FlushAsync(deadline.Token);
        var hash = new byte[32]; await pipe.ReadExactlyAsync(hash, deadline.Token);
        if (!CryptographicOperations.FixedTimeEquals(hash, Convert.FromHexString(helper.Sha256))) return 5;
        var length = await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token);
        if (length is < 1 or > PhoneCameraAudioSetupWire.MaximumArchive) return 87;
        var archive = new byte[length]; await pipe.ReadExactlyAsync(archive, deadline.Token);
        var package = PhoneCameraAudioPackage.Verify(archive); CryptographicOperations.ZeroMemory(archive);
        await OriginalPermissionAsync(Continue);
        using var prepared = PhoneCameraAudioStaging.Prepare(package, helper);
        var plan = await NativeAsync("--plan");
        PhoneCameraAudioSetupState state;
        if (plan.Exit != 0) state = PhoneCameraAudioSetupState.Failed;
        else if (!PhoneCameraAudioSetupWire.IsOriginalPlan(plan.Json, out var existing))
            state = existing ? PhoneCameraAudioSetupState.ExistingDevice : PhoneCameraAudioSetupState.Unsupported;
        else
        {
            if (args[0] == ElevatedPlanArgument) state = PhoneCameraAudioSetupState.PreparedOnly;
            else
            {
                await OriginalPermissionAsync(WillInstall);
                var installed = await NativeAsync("--install");
                state = installed.Exit == 3010 && PhoneCameraAudioSetupWire.IsRebootResult(installed.Json)
                    ? PhoneCameraAudioSetupState.RebootRequired : PhoneCameraAudioSetupState.UnknownPending;
            }
        }
        if (args[0] == ElevatedPlanArgument) prepared.RemoveKnownUninstalledPreparation();
        await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, Finished, deadline.Token);
        await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, (int)state, deadline.Token);
        return 0;

        async Task OriginalPermissionAsync(int phase)
        {
            if (parent.HasExited) throw new IOException("webcam_audio_original_parent_exited");
            await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, phase, deadline.Token);
            if (await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token) != Continue || parent.HasExited)
                throw new IOException("webcam_audio_original_setup_cancelled");
        }
        async Task<(int Exit, string Json)> NativeAsync(string mode)
        {
            if (!PhoneCameraAudioSetupWire.AllowsNativeMode(mode, args[0] == ElevatedPlanArgument))
                throw new InvalidOperationException("webcam_audio_plan_cannot_install");
            if (mode == "--install") prepared.MarkInstallationStarted();
            var start = new ProcessStartInfo(prepared.Executable) { UseShellExecute = false, CreateNoWindow = true,
                WorkingDirectory = prepared.Directory, RedirectStandardOutput = true, RedirectStandardError = true };
            start.ArgumentList.Add(mode); start.ArgumentList.Add(prepared.Directory);
            using var child = Process.Start(start) ?? throw new IOException("webcam_audio_native_helper_not_started");
            var output = child.StandardOutput.ReadToEndAsync(); var errors = child.StandardError.ReadToEndAsync();
            // After mutation, cancellation does not authorize terminating or
            // restarting PnP. Keep the process and all leases until it exits.
            await child.WaitForExitAsync(); var json = await output; var stderr = await errors;
            if (json.Length > PhoneCameraAudioSetupWire.MaximumNativeResult || stderr.Length != 0) throw new InvalidDataException("webcam_audio_native_result_invalid");
            return (child.ExitCode, json);
        }
    }
    internal static void RequireOriginalPeer(PipeStream pipe, uint expectedProcess, bool server)
    {
        uint actual;
        var found = server ? GetNamedPipeClientProcessId(pipe.SafePipeHandle, out actual) : GetNamedPipeServerProcessId(pipe.SafePipeHandle, out actual);
        if (!found || actual != expectedProcess) throw new UnauthorizedAccessException("webcam_audio_original_local_process_required");
    }
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeClientProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern Microsoft.Win32.SafeHandles.SafeProcessHandle OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, int pid);
}
