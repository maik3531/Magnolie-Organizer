using Microsoft.Web.WebView2.Core;

namespace MagnolieOrganizer.Windows;

internal static class WebViewEnvironmentProvider
{
    private static readonly object Sync = new();
    private static readonly Dictionary<string, Task<CoreWebView2Environment>> Environments =
        new(StringComparer.OrdinalIgnoreCase);

    internal static Task<CoreWebView2Environment> GetAsync(WindowsPaths paths)
    {
        paths.EnsureDirectories();
        var userDataFolder = Path.GetFullPath(paths.WebView);
        lock (Sync)
        {
            if (!Environments.TryGetValue(userDataFolder, out var environment))
            {
                environment = CoreWebView2Environment.CreateAsync(null, userDataFolder,
                    new CoreWebView2EnvironmentOptions("--disable-gpu"));
                Environments.Add(userDataFolder, environment);
            }
            return environment;
        }
    }
}
