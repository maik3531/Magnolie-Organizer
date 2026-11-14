using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Actual native primary-file observation, deliberately NOT a saved-book witness
// and not constructible/deserializable from caller JSON. Encrypted input must
// authenticate against the already unlocked native session; no password prompt.
internal sealed class ContactSourcePrimaryBook
{
    internal string Binding { get; }
    internal string RawHash { get; }
    internal string PlainHash { get; }
    internal string Content { get; }
    private ContactSourcePrimaryBook(string binding, string rawHash, string plainHash, string content)
    { Binding = binding; RawHash = rawHash; PlainHash = plainHash; Content = content; }

    internal static ContactSourcePrimaryBook Capture(string nativePath, AtomicStore files, EncryptionService encryption, Func<bool> available)
    {
        if (!Path.IsPathFullyQualified(nativePath) || !available())
            throw new InvalidOperationException("contact_source_native_primary_unavailable");
        var path = Path.GetFullPath(nativePath);
        static void RequirePath(string file)
        {
            for (var node = new FileInfo(file) as FileSystemInfo; node is not null;
                 node = node is FileInfo leaf ? leaf.Directory : ((DirectoryInfo)node).Parent)
                if ((File.GetAttributes(node.FullName) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("contact_source_primary_reparse");
        }
        RequirePath(path);
        var session = encryption.Session;
        var raw = files.Read(path) ?? throw new FileNotFoundException("contact_source_primary_missing");
        var encrypted = EncryptionService.IsEncrypted(raw);
        // An active encrypted session must not silently accept substituted clear
        // JSON as the authenticated primary for that same unlocked book.
        if (!encrypted && session is not null) throw new InvalidDataException("contact_source_primary_encryption_changed");
        var plain = encrypted ? encryption.DecryptDataWithSession(raw) : raw;
        var book = JsonNode.Parse(plain) as JsonObject ?? throw new InvalidDataException("contact_source_primary_book_required");
        RequirePath(path);
        if (!available() || !ReferenceEquals(session, encryption.Session) || files.Read(path) != raw)
            throw new InvalidOperationException("contact_source_primary_changed");
        return new(path, BaumSyncSnapshot.Hash(raw), BaumSyncSnapshot.Hash(plain), NativeBookJson.Hash(book));
    }

    internal bool Same(ContactSourcePrimaryBook other) => Binding == other.Binding && RawHash == other.RawHash &&
        PlainHash == other.PlainHash && Content == other.Content;
}
