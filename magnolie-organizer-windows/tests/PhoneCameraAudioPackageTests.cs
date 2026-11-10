using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioPackageTests
{
    internal static Task ClosedTrustBoundaryAsync()
    {
        TestAssert.That(PhoneCameraAudioPackage.DriverName.Contains("VB-CABLE",StringComparison.Ordinal) &&
            new Uri(PhoneCameraAudioPackage.Url).Scheme=="https" && new Uri(PhoneCameraAudioPackage.Url).Host=="download.vb-audio.com" &&
            Convert.FromHexString(PhoneCameraAudioPackage.Sha256).Length==32 &&
            new Uri(PhoneCameraAudioPackage.ManualUrl).Host=="vb-audio.com" && new Uri(PhoneCameraAudioPackage.LicenseUrl).Host=="vb-audio.com",
            "Named official driver/manual/license policy changed");
        TestAssert.Throws<CryptographicException>(()=>PhoneCameraAudioPackage.Verify(new byte[]{1,2,3}),"Unverified arbitrary archive admitted");
        TestAssert.Throws<InvalidDataException>(()=>PhoneCameraAudioPackage.Verify([]),"Empty archive admitted");
        return Task.CompletedTask;
    }
    private static byte[] Original() => File.ReadAllBytes(Environment.GetEnvironmentVariable("MAGNOLIE_CABLE_PACKAGE_FIXTURE") ??
        throw new InvalidOperationException("Explicit existing official read-only package fixture required"));
    private sealed class Http(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
    {
        internal readonly List<Uri> Requests = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation)
        { cancellation.ThrowIfCancellationRequested(); Requests.Add(request.RequestUri!); return Task.FromResult(response(request)); }
    }
    private static HttpResponseMessage Package(byte[] bytes) => new(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
    private static HttpResponseMessage Redirect(string location)
    { var result = new HttpResponseMessage(HttpStatusCode.Redirect); result.Headers.Location = new Uri(location, UriKind.RelativeOrAbsolute); return result; }

    internal static Task OriginalSnapshotAndExtractionAsync()
    {
        var original = Original(); var package = PhoneCameraAudioPackage.Verify(original); original[0] ^= 1;
        using var saved = new MemoryStream(); package.WriteOriginalArchive(saved);
        TestAssert.That(Convert.ToHexString(SHA256.HashData(saved.ToArray())).ToLowerInvariant() == PhoneCameraAudioPackage.Sha256,
            "Caller mutation changed owned original archive");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-cable-package530-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        IReadOnlyDictionary<string,string>? files = null;
        try
        {
            files = package.ExtractIntoEmptyDirectory(root);
            TestAssert.That(files.Count == package.FileCount && files.Count >= 5, "Original package was reduced/repacked");
            foreach (var (name,hash) in files)
            {
                TestAssert.That(Path.GetFileName(name) == name && Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(root,name)))).ToLowerInvariant() == hash,
                    "As-is package member changed during extraction");
            }
            TestAssert.That(files["vbMmeCable64_win10.inf"] == "cecf9181b6c85842d707330efc594824a749a1d9e01db46eba0e60e72f0a66ee" &&
                files["vbaudio_cable64_win10.cat"] == "5d24c17858b49ad83bb856c66c24c5c2aecdb89cbaae2f8179c15d351124fa9f" &&
                files["vbaudio_cable64_win10.sys"] == "7ebcbbe7004d185f7b29613cd27fdc2dd71c1712224b767a74d2f66bdc33a7ef" &&
                files["vbaudio_cable64arm_win10.sys"] == "85c217af826c2e1d478b52afc7c2248889c8478030d44e8134bd4c23b8915216",
                "Managed extraction differs from actual native kernel-verified package pins");
        }
        finally
        {
            if(files is not null)
            {
                foreach(var (name,hash) in files)
                {
                    var path=Path.Combine(root,name);
                    TestAssert.That((File.GetAttributes(path)&FileAttributes.ReparsePoint)==0 && Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant()==hash,
                        "Unexpected independent own-test file change; preserve");
                    File.Delete(path);
                }
                Directory.Delete(root,false);
            }
        }
        return Task.CompletedTask;
    }
    internal static Task ChangedArchiveRejectedAsync()
    {
        var bytes=Original(); bytes[^1]^=1;
        TestAssert.Throws<CryptographicException>(()=>PhoneCameraAudioPackage.Verify(bytes),"Modified publisher archive admitted");
        TestAssert.Throws<InvalidDataException>(()=>PhoneCameraAudioPackage.Verify([]),"Empty archive admitted");
        TestAssert.Throws<InvalidDataException>(()=>PhoneCameraAudioPackage.Verify(new byte[4*1024*1024+1]),"Unbounded archive admitted");
        return Task.CompletedTask;
    }
    internal static Task ExistingDestinationPreservedAsync()
    {
        var package=PhoneCameraAudioPackage.Verify(Original());
        var root=Path.Combine(Path.GetTempPath(),"magnolie-cable-preserve530-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
        var path=Path.Combine(root,"user-original.txt");File.WriteAllText(path,"original own fixture",Encoding.UTF8);
        try
        {
            TestAssert.Throws<InvalidDataException>(()=>package.ExtractIntoEmptyDirectory(root),"Existing destination overwritten");
            TestAssert.That(File.ReadAllText(path)=="original own fixture" && Directory.EnumerateFiles(root).Count()==1,"Original staging contents changed");
        }
        finally {File.Delete(path);Directory.Delete(root,false);}
        return Task.CompletedTask;
    }
    internal static async Task VerifiedDownloadAsync()
    {
        using var handler=new Http(_=>Package(Original()));using var http=new HttpClient(handler);
        var package=await PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None);
        TestAssert.That(package.FileCount>=5 && handler.Requests.Count==1 && handler.Requests[0].AbsoluteUri==PhoneCameraAudioPackage.Url,
            "Verified download used an unapproved origin or changed package");
    }
    internal static async Task RedirectOriginAndBudgetAsync()
    {
        foreach(var target in new[]{"http://download.vb-audio.com/file.zip","https://foreign.invalid/file.zip","https://download.vb-audio.com:444/file.zip","https://user:password@download.vb-audio.com/file.zip"})
        {
            using var handler=new Http(_=>Redirect(target));using var http=new HttpClient(handler);
            await TestAssert.ThrowsAsync<InvalidDataException>(()=>PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None),"Unapproved redirect followed");
            TestAssert.That(handler.Requests.Count==1,"Request reached rejected redirect origin");
        }
        var count=0;
        using(var handler=new Http(_=>++count==1?Redirect("/Download_CABLE/original.zip"):Package(Original())))
        using(var http=new HttpClient(handler))
        {
            var package=await PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None);
            TestAssert.That(package.FileCount>=5 && handler.Requests.Count==2,"Trusted bounded redirect failed");
        }
        using(var handler=new Http(_=>Redirect("/loop")))
        using(var http=new HttpClient(handler))
        {
            await TestAssert.ThrowsAsync<InvalidDataException>(()=>PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None),"Redirect loop not bounded");
            TestAssert.That(handler.Requests.Count==4,"Redirect budget changed");
        }
    }
    internal static async Task DownloadLimitsAndCancellationAsync()
    {
        using(var handler=new Http(_=>Package([1,2,3])))
        using(var http=new HttpClient(handler))
            await TestAssert.ThrowsAsync<CryptographicException>(()=>PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None),"Unverified downloaded bytes admitted");
        using(var handler=new Http(_=> {var response=Package([1]);response.Content.Headers.ContentLength=4*1024*1024+1;return response;}))
        using(var http=new HttpClient(handler))
            await TestAssert.ThrowsAsync<InvalidDataException>(()=>PhoneCameraAudioPackage.DownloadAsync(http,CancellationToken.None),"Oversized declared download admitted");
        using var canceled=new CancellationTokenSource();canceled.Cancel();
        using var never=new Http(_=>throw new InvalidOperationException("Cancelled request must not start"));using var client=new HttpClient(never);
        await TestAssert.ThrowsAsync<OperationCanceledException>(()=>PhoneCameraAudioPackage.DownloadAsync(client,canceled.Token),"Canceled setup download started");
        TestAssert.That(never.Requests.Count==0,"Cancelled download touched network handler");
    }
    internal static async Task LiveOfficialDownloadAsync()
    {
        // Explicit opt-in read-only network probe. Never install, extract into
        // system locations, execute vendor bytes or request administrator rights.
        var package=await PhoneCameraAudioPackage.DownloadAsync(CancellationToken.None);
        using var original=new MemoryStream();package.WriteOriginalArchive(original);
        TestAssert.That(Convert.ToHexString(SHA256.HashData(original.ToArray())).ToLowerInvariant()==PhoneCameraAudioPackage.Sha256 && package.FileCount>=5,
            "Actual Windows HTTPS download differs from pinned official package");
    }
}
