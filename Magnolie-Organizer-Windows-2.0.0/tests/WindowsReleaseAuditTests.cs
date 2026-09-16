using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsReleaseAuditTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-release-audit-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            const string version = "9.8.7";
            const string installer = "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe";
            const string record = installer + ".build.json";
            const string checksums = "Magnolie-Organizer-Windows-9.8.7-PRUEFSUMMEN.sha256";
            string At(string name) => Path.Combine(root, name);
            void WriteChecksums()
            {
                string Line(string name) => Sha256(At(name)) + "  " + name + "\n";
                File.WriteAllText(At(checksums), Line(installer) + Line(record));
                File.WriteAllText(At("PRUEFSUMMEN.sha256"), Line(installer) + Line(record) + Line(checksums));
            }
            File.WriteAllText(At(installer), "Synthetic installer bytes, never executed.\n");
            var hash = Sha256(At(installer));
            File.WriteAllText(At(record), JsonSerializer.Serialize(new
            {
                schema = "magnolie-installer-build-v1", artifact = installer,
                bytes = new FileInfo(At(installer)).Length, sha256 = hash
            }));
            var url = "https://example.invalid/" + installer;
            File.WriteAllText(At("update.xml"), $"""
                <update><version>{version}</version>
                <windows><version>{version}</version><url>{url}</url><sha256>{hash}</sha256></windows>
                <manual><windows><url>{url}</url><sha256>{hash}</sha256></windows></manual></update>
                """);
            WriteChecksums();
            var pristine = Directory.GetFiles(root).ToDictionary(path => Path.GetFileName(path), File.ReadAllText);
            var rejected = 0;
            void Reset() { foreach (var (name, content) in pristine) File.WriteAllText(At(name), content); }
            void Reject<T>(string name, Action mutate) where T : Exception
            {
                Reset(); mutate();
                TestAssert.Throws<T>(() => Audit(root), "Release audit accepted " + name);
                rejected++;
            }
            Audit(root);
            foreach (var path in new[] { "version", "windows/version", "windows/url", "windows/sha256", "manual/windows/url", "manual/windows/sha256" })
            {
                void Change(Action<XElement> change)
                {
                    var xml = XDocument.Load(At("update.xml"));
                    var element = xml.Root!;
                    foreach (var part in path.Split('/')) element = element.Element(part)!;
                    change(element); xml.Save(At("update.xml"));
                }
                Reject<InvalidOperationException>(path + " missing", () => Change(element => element.Remove()));
                Reject<InvalidOperationException>(path + " duplicate", () => Change(element => element.AddAfterSelf(new XElement(element))));
                if (path != "version")
                    Reject<InvalidOperationException>(path + " mismatch", () => Change(element =>
                        element.Value = path.EndsWith("url", StringComparison.Ordinal) ? "https://example.invalid/wrong.exe" : "wrong"));
            }
            Reject<InvalidDataException>("missing manual", () =>
            {
                var xml = XDocument.Load(At("update.xml")); xml.Root!.Element("manual")!.Remove(); xml.Save(At("update.xml"));
            });
            foreach (var path in new[] { "windows", "manual", "manual/windows" })
                Reject<InvalidOperationException>("duplicate " + path, () =>
                {
                    var xml = XDocument.Load(At("update.xml")); var element = xml.Root!;
                    foreach (var part in path.Split('/')) element = element.Element(part)!;
                    element.AddAfterSelf(new XElement(element)); xml.Save(At("update.xml"));
                });
            Reject<InvalidDataException>("missing manual windows", () =>
            {
                var xml = XDocument.Load(At("update.xml")); xml.Root!.Element("manual")!.Element("windows")!.Remove(); xml.Save(At("update.xml"));
            });
            Reject<InvalidOperationException>("changed installer bytes", () => File.AppendAllText(At(installer), "tampered"));
            foreach (var field in new[] { "schema", "artifact", "bytes", "sha256" })
            {
                Reject<InvalidOperationException>("record " + field, () =>
                {
                    var json = JsonNode.Parse(File.ReadAllText(At(record)))!;
                    json[field] = field == "bytes" ? JsonValue.Create(-1L) : JsonValue.Create("wrong");
                    File.WriteAllText(At(record), json.ToJsonString());
                    // Rebind lists so the record-content invariant, not a stale list hash, must reject this.
                    WriteChecksums();
                });
                Reject<KeyNotFoundException>("record missing " + field, () =>
                {
                    var json = JsonNode.Parse(File.ReadAllText(At(record)))!.AsObject(); json.Remove(field);
                    File.WriteAllText(At(record), json.ToJsonString()); WriteChecksums();
                });
            }
            Reject<JsonException>("malformed record", () => { File.WriteAllText(At(record), "{"); WriteChecksums(); });
            Reject<System.Xml.XmlException>("malformed manifest", () => File.WriteAllText(At("update.xml"), "<update>"));
            foreach (var list in new[] { checksums, "PRUEFSUMMEN.sha256" })
            {
                foreach (var entry in list == checksums ? new[] { installer, record } : new[] { installer, record, checksums })
                {
                    Reject<InvalidOperationException>(list + " missing " + entry, () =>
                        File.WriteAllLines(At(list), File.ReadAllLines(At(list)).Where(line => !line.EndsWith("  " + entry, StringComparison.Ordinal)).ToArray()));
                    Reject<InvalidOperationException>(list + " wrong hash " + entry, () =>
                        File.WriteAllLines(At(list), File.ReadAllLines(At(list)).Select(line =>
                            line.EndsWith("  " + entry, StringComparison.Ordinal) ? new string('0', 64) + "  " + entry : line).ToArray()));
                }
                Reject<InvalidDataException>(list + " duplicate", () => File.AppendAllText(At(list), File.ReadAllLines(At(list))[0] + "\n"));
                Reject<InvalidDataException>(list + " malformed", () => File.AppendAllText(At(list), "not-a-checksum-line\n"));
            }
            foreach (var name in pristine.Keys)
                Reject<FileNotFoundException>("missing " + name, () => File.Delete(At(name)));
            Reset();
            // sha256sum's binary marker and uppercase hashes remain accepted list formats.
            void BinaryList(string name) => File.WriteAllLines(At(name), File.ReadAllLines(At(name)).Select(line =>
                line[..64].ToUpperInvariant() + " *" + line[66..]).ToArray());
            BinaryList(checksums);
            File.WriteAllText(At("PRUEFSUMMEN.sha256"), string.Join('\n', new[] { installer, record, checksums }
                .Select(name => Sha256(At(name)) + "  " + name)) + "\n");
            BinaryList("PRUEFSUMMEN.sha256");
            Audit(root);
            Console.WriteLine($"         RELEASE-AUDIT-FIXTURES: 2 positive, {rejected} negative passed");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    internal static void Audit(string root)
    {
        var document = XDocument.Load(Path.Combine(root, "update.xml"));
        var update = document.Root ?? throw new InvalidDataException("update.xml hat kein Wurzelelement.");
        var version = RequiredValue(update, "version");
        var windows = update.Elements("windows").Single();
        var manualWindows = update.Elements("manual").SingleOrDefault()?.Elements("windows").SingleOrDefault() ??
            throw new InvalidDataException("Der Windows-Handbucheintrag fehlt.");
        var installerName = $"Magnolie-Organizer-Windows-{version}-Setup-x64.exe";
        var installer = Path.Combine(root, installerName);
        var checksumFile = Path.Combine(root, $"Magnolie-Organizer-Windows-{version}-PRUEFSUMMEN.sha256");
        var buildrecord = installer + ".build.json";
        var actualSha = Sha256(installer);
        var actualBytes = new FileInfo(installer).Length;

        TestAssert.That(RequiredValue(windows, "version") == version &&
                        Path.GetFileName(new Uri(RequiredValue(windows, "url")).AbsolutePath) == installerName &&
                        Path.GetFileName(new Uri(RequiredValue(manualWindows, "url")).AbsolutePath) == installerName,
            "Die Windows-Felder in update.xml bezeichnen nicht den Root-Installer der Releasefassung.");
        TestAssert.That(RequiredValue(windows, "sha256") == actualSha &&
                        RequiredValue(manualWindows, "sha256") == actualSha,
            $"Windows-SHA in update.xml passt nicht zum Root-Installer: Manifest {RequiredValue(windows, "sha256")}, Datei {actualSha}.");

        var windowsChecksums = ReadChecksums(checksumFile);
        TestAssert.That(windowsChecksums.TryGetValue(installerName, out var listedInstallerSha) && listedInstallerSha == actualSha,
            "Die Windows-Prüfsummendatei bestätigt den Root-Installer nicht.");
        TestAssert.That(windowsChecksums.TryGetValue(Path.GetFileName(buildrecord), out var listedBuildrecordSha) &&
                        listedBuildrecordSha == Sha256(buildrecord),
            "Die Windows-Prüfsummendatei bestätigt den Buildrecord nicht.");

        using (var json = JsonDocument.Parse(File.ReadAllBytes(buildrecord)))
        {
            var record = json.RootElement;
            TestAssert.That(record.GetProperty("schema").GetString() == "magnolie-installer-build-v1" &&
                            record.GetProperty("artifact").GetString() == installerName &&
                            record.GetProperty("bytes").GetInt64() == actualBytes &&
                            record.GetProperty("sha256").GetString() == actualSha,
                "Der Windows-Buildrecord beschreibt nicht exakt den Root-Installer.");
        }

        var releaseChecksums = ReadChecksums(Path.Combine(root, "PRUEFSUMMEN.sha256"));
        TestAssert.That(releaseChecksums.TryGetValue(installerName, out var releaseInstallerSha) && releaseInstallerSha == actualSha &&
                        releaseChecksums.TryGetValue(Path.GetFileName(buildrecord), out var releaseBuildrecordSha) &&
                        releaseBuildrecordSha == Sha256(buildrecord) &&
                        releaseChecksums.TryGetValue(Path.GetFileName(checksumFile), out var releaseChecksumSha) &&
                        releaseChecksumSha == Sha256(checksumFile),
            "PRUEFSUMMEN.sha256 bestätigt Installer, Buildrecord und Windows-Prüfsummendatei nicht gemeinsam.");
    }

    private static string RequiredValue(XElement parent, XName name) =>
        parent.Elements(name).Single().Value.Trim();

    private static Dictionary<string, string> ReadChecksums(string path)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var line in File.ReadLines(path))
        {
            var parts = line.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 2) throw new InvalidDataException($"Ungültige Prüfsummenzeile in {Path.GetFileName(path)}.");
            if (!result.TryAdd(parts[1].TrimStart('*'), parts[0].ToLowerInvariant()))
                throw new InvalidDataException($"Doppelter Eintrag in {Path.GetFileName(path)}.");
        }
        return result;
    }

    private static string Sha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
