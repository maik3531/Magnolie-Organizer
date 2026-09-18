namespace MagnolieOrganizer.Windows;

// Keep the handle for the complete process lifetime; never unlink a live lock file.
internal sealed class ProfileLease : IDisposable
{
    private readonly FileStream file;
    private ProfileLease(FileStream file) => this.file = file;
    internal static ProfileLease Acquire(string root)
    {
        Directory.CreateDirectory(root);
        var path = Path.Combine(root, ".profile-owner.lock");
        if (File.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException();
        var stream = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            if (!OperatingSystem.IsMacOS()) stream.Lock(0, 1);
            return new ProfileLease(stream);
        }
        catch { stream.Dispose(); throw; }
    }
    public void Dispose() => file.Dispose();
}
