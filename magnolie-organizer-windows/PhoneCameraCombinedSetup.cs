using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static partial class PhoneCameraAudioSetup
{
    internal const string CombinedElevatedArgument = "--phone-camera-combined-elevated";
    internal const string CombinedElevatedPlanArgument = "--phone-camera-combined-elevated-plan";
    private const string CombinedPipePrefix = "magnolie-phone-combined-";
    private const int CombinedContinue = 0x201, CombinedWillInstall = 0x202, CombinedFinished = 0x203;

    internal static bool ValidCombinedArguments(string[] args)
    {
        if (args.Length != 6 || args[0] is not (CombinedElevatedArgument or CombinedElevatedPlanArgument) ||
            !args[1].StartsWith(CombinedPipePrefix, StringComparison.Ordinal) || !IsHex(args[1][CombinedPipePrefix.Length..], 32)) return false;
        // Reuse the original PID/SID/birth/token grammar, not the old wire.
        var original = args.ToArray(); original[0] = ElevatedArgument; original[1] = PipePrefix + args[1][CombinedPipePrefix.Length..];
        return ValidArguments(original);
    }

    // No UI hook yet: native protected-install/AV acceptance remains pending.
    // The caller must have obtained the explicit combined installation consent.
    internal static Task<PhoneCameraCombinedSetupWire.Result> RunCombinedConfirmedAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation) => RunCombinedAsync(package, originalCurrent, cancellation, install: true);
    internal static Task<PhoneCameraCombinedSetupWire.Result> RunCombinedPreparationAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation) => RunCombinedAsync(package, originalCurrent, cancellation, install: false);

    private static async Task<PhoneCameraCombinedSetupWire.Result> RunCombinedAsync(PhoneCameraAudioPackage package,
        Action originalCurrent, CancellationToken cancellation, bool install)
    {
        ArgumentNullException.ThrowIfNull(package); ArgumentNullException.ThrowIfNull(originalCurrent);
        originalCurrent(); cancellation.ThrowIfCancellationRequested();
        if (RuntimeInformation.ProcessArchitecture != Architecture.X64 || PhoneCameraSourcePayload.LoadEmbedded() is null ||
            PhoneCameraAudioHelperPayload.LoadEmbedded() is null) return new(PhoneCameraCombinedSetupWire.State.Unsupported);
        using var bootstrap = PhoneCameraAudioBootstrapLease.TryAcquire();
        if (bootstrap is null) return new(PhoneCameraCombinedSetupWire.State.Unsupported);
        using var identity = WindowsIdentity.GetCurrent(); var sid = identity.User?.Value; var executable = Environment.ProcessPath;
        if (sid is null || executable is null || !executable.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ||
            Path.GetFileNameWithoutExtension(executable).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
            return new(PhoneCameraCombinedSetupWire.State.Unsupported);
        var header = PhoneCameraCombinedSetupWire.CreateCurrent(install ? PhoneCameraCombinedSetupWire.Mode.Install : PhoneCameraCombinedSetupWire.Mode.Plan);
        var pipeName = CombinedPipePrefix + Guid.NewGuid().ToString("N"); var token = RandomNumberGenerator.GetBytes(32);
        using var pipe = PhoneCameraAudioSetupPipe.CreateServer(pipeName);
        using var current = Process.GetCurrentProcess();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromMinutes(3));
        Process? elevated = null; var mutationApproved = false;
        try
        {
            var start = new ProcessStartInfo(executable) { UseShellExecute = true, Verb = "runas", WorkingDirectory = AppContext.BaseDirectory };
            foreach (var argument in new[] { install ? CombinedElevatedArgument : CombinedElevatedPlanArgument, pipeName,
                Convert.ToHexString(token).ToLowerInvariant(), Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture), sid,
                current.StartTime.ToUniversalTime().Ticks.ToString(System.Globalization.CultureInfo.InvariantCulture) }) start.ArgumentList.Add(argument);
            elevated = await Task.Run(() => Process.Start(start)) ?? throw new IOException("webcam_combined_elevation_not_started");
            var connecting = pipe.WaitForConnectionAsync(deadline.Token);
            if (await Task.WhenAny(connecting, elevated.WaitForExitAsync(deadline.Token)) != connecting)
            { deadline.Token.ThrowIfCancellationRequested(); return new(PhoneCameraCombinedSetupWire.State.Failed); }
            await connecting;
            RequireOriginalPeer(pipe, (uint)elevated.Id, server: true);
            PhoneCameraAudioSetupPipe.RequireOriginalDescriptor(pipe, new SecurityIdentifier(sid));
            var echoedToken = new byte[32]; await pipe.ReadExactlyAsync(echoedToken, deadline.Token);
            if (!CryptographicOperations.FixedTimeEquals(token, echoedToken)) throw new CryptographicException("webcam_combined_original_token_required");
            originalCurrent(); deadline.Token.ThrowIfCancellationRequested();
            // Only after the original child PID/descriptor/token is authenticated.
            await header.WriteHeaderAsync(pipe, deadline.Token); await header.RequireEchoAsync(pipe, deadline.Token);
            using var archive = new MemoryStream(); package.WriteOriginalArchive(archive);
            await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, checked((int)archive.Length), deadline.Token);
            await pipe.WriteAsync(archive.GetBuffer().AsMemory(0, checked((int)archive.Length)), deadline.Token); await pipe.FlushAsync(deadline.Token);
            var preparationApproved = false;
            while (true)
            {
                var phase = await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token);
                if (phase == CombinedFinished)
                {
                    if (!preparationApproved) throw new InvalidDataException("webcam_combined_original_preparation_required");
                    return await header.ReadResultAsync(pipe, mutationApproved, deadline.Token);
                }
                if (phase == CombinedContinue ? preparationApproved : phase != CombinedWillInstall || !install || !preparationApproved || mutationApproved)
                    throw new InvalidDataException("webcam_combined_original_phase_invalid");
                originalCurrent(); deadline.Token.ThrowIfCancellationRequested();
                preparationApproved = true;
                // Ambiguity begins BEFORE sending the one original mutation ACK.
                if (phase == CombinedWillInstall) mutationApproved = true;
                await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, CombinedContinue, deadline.Token);
            }
        }
        catch (Exception error) when (error is IOException or InvalidDataException or Win32Exception or UnauthorizedAccessException or CryptographicException or
            InvalidOperationException or OperationCanceledException or JsonException)
        {
            return new(mutationApproved ? PhoneCameraCombinedSetupWire.State.UnknownPending :
                error is OperationCanceledException or Win32Exception { NativeErrorCode: 1223 } ? PhoneCameraCombinedSetupWire.State.Cancelled :
                PhoneCameraCombinedSetupWire.State.Failed);
        }
        finally
        {
            pipe.Dispose(); CryptographicOperations.ZeroMemory(token);
            // Never detach/kill/retry an original child, even after the IPC deadline.
            if (elevated is not null) { try { await elevated.WaitForExitAsync(); } finally { elevated.Dispose(); } }
        }
    }

    internal static async Task<int> RunCombinedElevatedAsync(string[] args)
    {
        if (!ValidCombinedArguments(args)) return 87;
        using var identity = WindowsIdentity.GetCurrent();
        if (identity.User?.Value != args[4] || !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) return 740;
        var pid = int.Parse(args[3], System.Globalization.CultureInfo.InvariantCulture);
        using var originalProcessHandle = OpenProcess(0x101000, false, pid);
        if (originalProcessHandle.IsInvalid) return 5;
        using var parent = Process.GetProcessById(pid);
        if (parent.StartTime.ToUniversalTime().Ticks != long.Parse(args[5], System.Globalization.CultureInfo.InvariantCulture) || parent.HasExited) return 5;
        var planOnly = args[0] == CombinedElevatedPlanArgument;
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(3));
        using var pipe = new NamedPipeClientStream(".", args[1], PipeDirection.InOut, PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
        await pipe.ConnectAsync(10000, deadline.Token);
        RequireOriginalPeer(pipe, (uint)parent.Id, server: false);
        PhoneCameraAudioSetupPipe.RequireOriginalDescriptor(pipe, new SecurityIdentifier(args[4]));
        if (parent.HasExited) return 5;
        var helper = PhoneCameraAudioHelperPayload.LoadEmbedded(); if (helper is null) return 50;
        await pipe.WriteAsync(Convert.FromHexString(args[2]), deadline.Token); await pipe.FlushAsync(deadline.Token);
        // Expected mode is from the original invocation, NEVER from received bytes.
        var header = await PhoneCameraCombinedSetupWire.ReadCurrentAsync(pipe,
            planOnly ? PhoneCameraCombinedSetupWire.Mode.Plan : PhoneCameraCombinedSetupWire.Mode.Install, deadline.Token);
        await header.WriteHeaderAsync(pipe, deadline.Token);
        var length = await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token);
        if (length is < 1 or > PhoneCameraAudioSetupWire.MaximumArchive) return 87;
        var archive = new byte[length]; PhoneCameraAudioPackage package;
        try { await pipe.ReadExactlyAsync(archive, deadline.Token); package = PhoneCameraAudioPackage.Verify(archive); }
        finally { CryptographicOperations.ZeroMemory(archive); }
        await OriginalPermissionAsync(CombinedContinue);
        using var prepared = PhoneCameraAudioStaging.Prepare(package, helper);
        PhoneCameraSetupJournal? journal = null;
        var mutationApproved = false; var sourceStarted = false; var sourceConfirmed = false; var microphoneStarted = false;
        PhoneCameraCombinedSetupWire.Result result;
        try
        {
            var plan = await CombinedNativeAsync(prepared, "--plan", planOnly);
            if (plan.Exit != 0) result = new(PhoneCameraCombinedSetupWire.State.Failed);
            else if (!PhoneCameraAudioSetupWire.IsOriginalPlan(plan.Json, out var existing))
                result = new(existing ? PhoneCameraCombinedSetupWire.State.ExistingDevice : PhoneCameraCombinedSetupWire.State.Unsupported);
            else if (planOnly) result = new(PhoneCameraCombinedSetupWire.State.PreparedOnly);
            else
            {
                await OriginalPermissionAsync(CombinedWillInstall);
                mutationApproved = true;
                if (parent.HasExited) throw new IOException("webcam_combined_original_parent_exited");
                deadline.Token.ThrowIfCancellationRequested();
                header.RequireCompletedInstallHeader();
                journal = PhoneCameraSetupJournal.CreateCurrent(header);
                sourceStarted = true; // Attempt/uncertainty, not an installation proof.
                PhoneCameraSourceRegistration.InstallCurrent(journal); // Includes protected readback + durable confirmation.
                sourceConfirmed = true;
                if (parent.HasExited) throw new IOException("webcam_combined_original_parent_exited");
                deadline.Token.ThrowIfCancellationRequested();
                journal.BeginMicrophone(); // Durable intent BEFORE original native mutation.
                microphoneStarted = true;
                var installed = await CombinedNativeAsync(prepared, "--install", planOnly);
                var outcome = journal.RecordMicrophoneResult(installed.Exit, installed.Json);
                result = new(outcome == PhoneCameraSetupJournal.Phase.RebootRequired ? PhoneCameraCombinedSetupWire.State.RebootRequired :
                    PhoneCameraCombinedSetupWire.State.UnknownPending, sourceStarted, sourceConfirmed, microphoneStarted);
            }
        }
        catch (Exception error) when (error is IOException or InvalidDataException or Win32Exception or UnauthorizedAccessException or CryptographicException or
            InvalidOperationException or OperationCanceledException or JsonException)
        {
            // Poisoned/terminal journals cannot be revived by a later result.
            if (journal is not null) { try { journal.RecordFailure(unknown: true); } catch (Exception) { } }
            result = new(mutationApproved ? PhoneCameraCombinedSetupWire.State.UnknownPending : PhoneCameraCombinedSetupWire.State.Failed,
                sourceStarted, sourceConfirmed, microphoneStarted);
        }
        finally
        {
            journal?.Dispose();
            if (planOnly) prepared.RemoveKnownUninstalledPreparation();
        }
        await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, CombinedFinished, deadline.Token);
        await header.WriteResultAsync(pipe, result, deadline.Token);
        return 0;

        async Task OriginalPermissionAsync(int phase)
        {
            if (parent.HasExited) throw new IOException("webcam_combined_original_parent_exited");
            await PhoneCameraAudioSetupWire.WriteIntAsync(pipe, phase, deadline.Token);
            if (await PhoneCameraAudioSetupWire.ReadIntAsync(pipe, deadline.Token) != CombinedContinue || parent.HasExited)
                throw new IOException("webcam_combined_original_approval_required");
        }
    }

    private static async Task<(int Exit, string Json)> CombinedNativeAsync(PhoneCameraAudioStaging.Prepared prepared, string mode, bool planOnly)
    {
        if (!PhoneCameraAudioSetupWire.AllowsNativeMode(mode, planOnly)) throw new InvalidOperationException("webcam_combined_plan_cannot_install");
        if (mode == "--install") prepared.MarkInstallationStarted();
        var start = new ProcessStartInfo(prepared.Executable) { UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = prepared.Directory, RedirectStandardOutput = true, RedirectStandardError = true };
        start.ArgumentList.Add(mode); start.ArgumentList.Add(prepared.Directory);
        using var child = Process.Start(start) ?? throw new IOException("webcam_combined_original_helper_not_started");
        var output = DrainBoundedAsync(child.StandardOutput); var errors = DrainBoundedAsync(child.StandardError);
        // Keep original staging/process lifetime even when the parent or deadline is gone.
        try { await child.WaitForExitAsync(); }
        finally { await Task.WhenAll(output, errors); }
        var stdout = await output; var stderr = await errors;
        if (stdout.Overflow || stderr.Overflow || stderr.Text.Length != 0) throw new InvalidDataException("webcam_combined_native_result_invalid");
        return (child.ExitCode, stdout.Text);
    }
    private static async Task<(string Text, bool Overflow)> DrainBoundedAsync(StreamReader reader)
    {
        var text = new StringBuilder(); var buffer = new char[1024]; var overflow = false;
        int count;
        while ((count = await reader.ReadAsync(buffer)) != 0)
        {
            var remaining = PhoneCameraAudioSetupWire.MaximumNativeResult - text.Length;
            text.Append(buffer, 0, Math.Min(count, remaining));
            overflow |= count > remaining;
        }
        return (text.ToString(), overflow);
    }
}
