using System.Net;
using System.Text;
using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class GraphDeviceSignInTests
{
    private const string ClientId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    private const string Device = "{\"device_code\":\"owned-private-device\",\"user_code\":\"OWNED-CODE\",\"verification_uri\":\"https://microsoft.com/devicelogin\",\"expires_in\":60,\"interval\":1}";
    private const string Token = "{\"access_token\":\"owned-private-access\",\"refresh_token\":\"owned-private-refresh\",\"expires_in\":3600}";
    private sealed class Protector : ISecretProtector
    {
        internal bool WrongReadback;
        internal int Reads;
        public byte[] Protect(byte[] bytes) => bytes.Reverse().ToArray();
        public byte[] Unprotect(byte[] bytes) { Reads++; return WrongReadback ? Encoding.UTF8.GetBytes("owned-wrong-token") : bytes.Reverse().ToArray(); }
    }
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => send(request, cancellationToken);
    }
    private static HttpResponseMessage Json(string value, HttpStatusCode status = HttpStatusCode.OK) =>
        new(status) { Content = new StringContent(value, Encoding.UTF8, "application/json") };

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-device-signin-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            await TestSuccess(root);
            await TestLateTokenAfterCancellation(root);
            await TestFailureReceipts(root);
        }
        finally { Directory.Delete(root, true); }
    }

    private static async Task TestSuccess(string root)
    {
        var protector = new Protector();
        var store = new GraphTokenStore(Path.Combine(root, "success.dat"), protector);
        var requests = new List<string>();
        using var http = new HttpClient(new Handler(async (request, _) =>
        {
            TestAssert.That(request.Method == HttpMethod.Post && request.RequestUri!.Host == "login.microsoftonline.com", "Device flow used a different provider or method.");
            var body = await request.Content!.ReadAsStringAsync();
            requests.Add(request.RequestUri!.AbsolutePath);
            TestAssert.That(body.Contains(ClientId, StringComparison.Ordinal), "Device flow lost its pinned client ID.");
            if (requests.Count == 1)
            {
                TestAssert.That(body.Contains("Contacts.ReadWrite", StringComparison.Ordinal), "GUI OAuth scopes changed.");
                return Json(Device);
            }
            TestAssert.That(body.Contains("device_code=owned-private-device", StringComparison.Ordinal), "The real OAuth poll omitted its internal provider device code.");
            return Json(Token);
        }));
        var flow = new GraphDeviceSignIn(new(http), ClientId, default, store.SaveVerified);
        var running = flow.RunAsync();
        var pending = await flow.Ready;
        TestAssert.That(pending.State == "pending" && pending.UserCode == "OWNED-CODE" && pending.BrowserAccepted is null && !pending.PersistenceVerified && !store.Exists,
            "Begin claimed completion before the actual token response/readback or opened an unrequested browser.");
        await running;
        var done = flow.Read();
        TestAssert.That(done.State == "succeeded" && done.PersistenceVerified && done.TokenStorageMayHaveChanged && done.UserCode == "" && store.Load() == "owned-private-refresh" && protector.Reads >= 2,
            "Sign-in success did not verify the real protected store transaction.");
        TestAssert.That(!JsonSerializer.Serialize(done).Contains("owned-private", StringComparison.Ordinal) && !JsonSerializer.Serialize(pending).Contains("owned-private", StringComparison.Ordinal),
            "Device/access/refresh tokens leaked through public sign-in snapshots.");
        TestAssert.That(requests.Count == 2, "Device flow did not reuse the actual devicecode/token endpoints.");
    }

    private static async Task TestLateTokenAfterCancellation(string root)
    {
        var pollStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var store = new GraphTokenStore(Path.Combine(root, "cancel.dat"), new Protector());
        using var http = new HttpClient(new Handler((request, _) =>
        {
            if (request.RequestUri!.AbsolutePath.EndsWith("devicecode", StringComparison.Ordinal)) return Task.FromResult(Json(Device));
            pollStarted.TrySetResult(); return release.Task; // Deliberately ignores cancellation like a completed/late HTTP reply.
        }));
        var flow = new GraphDeviceSignIn(new(http), ClientId, cancellation.Token, store.SaveVerified);
        var running = flow.RunAsync();
        await pollStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cancellation.Cancel(); release.SetResult(Json(Token));
        await running.WaitAsync(TimeSpan.FromSeconds(5));
        TestAssert.That(flow.Read().State == "cancelled" && !flow.Read().PersistenceVerified && !store.Exists,
            "A late token response recreated credentials after cancellation.");
    }

    private static async Task TestFailureReceipts(string root)
    {
        foreach (var mode in new[] { "denied", "missing_refresh", "verification", "conflict" })
        {
            var protector = new Protector { WrongReadback = mode == "verification" };
            var store = new GraphTokenStore(Path.Combine(root, mode + ".dat"), protector);
            var browserCalls = 0;
            using var http = new HttpClient(new Handler((request, _) => Task.FromResult(
                request.RequestUri!.AbsolutePath.EndsWith("devicecode", StringComparison.Ordinal)
                    ? mode == "denied" ? Json("owned-private-error", HttpStatusCode.Unauthorized) : Json(Device)
                    : Json(mode == "missing_refresh" ? "{\"access_token\":\"owned-private-access\",\"expires_in\":3600}" : Token))));
            var flow = new GraphDeviceSignIn(new(http), ClientId, default, value =>
            {
                if (mode == "conflict") throw new GraphSignInConflictException();
                store.SaveVerified(value);
            }, _ => { browserCalls++; return false; });
            await flow.RunAsync();
            var result = flow.Read();
            TestAssert.That(result.State == "failed" && !result.PersistenceVerified && result.UserCode == "" && result.VerificationUri == "" &&
                result.ErrorCode == (mode == "denied" ? "network_error" : mode == "conflict" ? "conflict" : "native_operation_failed") &&
                !JsonSerializer.Serialize(result).Contains("owned-private", StringComparison.Ordinal), "Failure receipt leaked native details or claimed verified token persistence.");
            TestAssert.That(browserCalls == (mode == "denied" ? 0 : 1) && (mode != "verification" || result.TokenStorageMayHaveChanged && store.Exists),
                "Optional browser launch or ambiguous post-write verification state was misreported.");
        }
    }
}
