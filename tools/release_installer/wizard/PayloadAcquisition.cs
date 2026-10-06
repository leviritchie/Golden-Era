using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GoldenEraModInstaller;

// Finds the Golden Era release payload zip without making extra copies of it.
//
// v0.1.319+ ships the payload as ordinary GitHub Release assets
// (<payloadBaseName>.part01 .. .partNN). The installer EXE carries a small "GERADL01"
// footer naming those parts. Resolution order:
//   1. GOLDEN_ERA_INSTALLER_PACKAGE_PATH (a payload zip or an EXE with an appended payload)
//   2. a payload appended to this EXE ("GERAPKG1" footer, legacy embedded builds)
//   3. the whole payload zip next to this EXE
//   4. the part files next to this EXE (offline install), topped up from the download
//      cache and finally from the matching GitHub Release.
// The parts are never joined on disk: they are read through one seekable stream.
internal static class PayloadAcquisition
{
    internal const string DownloadFooterMagic = "GERADL01";
    private const int DownloadFooterTrailerLength = sizeof(long) + 8;
    private const long DefaultMaxPartBytes = 1_900_000_000L;
    private const long DownloadSpaceMarginBytes = 512L * 1024L * 1024L;
    private const int DownloadAttempts = 3;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    private static readonly Lazy<HttpClient> HttpLazy = new(CreateHttpClient);
    private static HttpClient Http => HttpLazy.Value;

    internal sealed record DownloadManifest(
        string Schema,
        string GithubOwner,
        string GithubRepo,
        string ReleaseTag,
        string PayloadBaseName,
        string ExpectedSha256,
        long ExpectedBytes,
        IReadOnlyList<string> Parts,
        bool? Homm3UseUpscaledHeroPortraits,
        IReadOnlyList<long>? PartBytes = null);

    internal sealed record AcquiredPayload(
        string ExpectedSha256,
        long ExpectedBytes,
        Func<Stream> OpenRead,
        string SourceDescription,
        bool? Homm3UseUpscaledHeroPortraits);

    public static string InstallerDirectory =>
        Path.GetDirectoryName(Path.GetFullPath(Environment.ProcessPath ?? AppContext.BaseDirectory))
        ?? AppContext.BaseDirectory;

    public static AcquiredPayload Resolve(Action<string> log, Action<InstallerProgress>? progress = null)
    {
        var overridePath = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_PACKAGE_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(overridePath));
            if (!File.Exists(full))
            {
                throw new InvalidOperationException("GOLDEN_ERA_INSTALLER_PACKAGE_PATH points to a file that does not exist: " + full);
            }

            if (TryResolveAppendedPackage(full, out var appended))
            {
                log("Using GOLDEN_ERA_INSTALLER_PACKAGE_PATH appended payload: " + full);
                return appended;
            }

            log("Using GOLDEN_ERA_INSTALLER_PACKAGE_PATH zip: " + full);
            return new AcquiredPayload(
                ComputeFileSha256(full, log, progress),
                new FileInfo(full).Length,
                () => File.OpenRead(full),
                full,
                Homm3UseUpscaledHeroPortraits: null);
        }

        var processPath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(processPath) || !File.Exists(processPath))
        {
            throw new InvalidOperationException("Unable to resolve the running installer EXE path.");
        }

        if (TryResolveAppendedPackage(processPath, out var embedded))
        {
            log("Using payload embedded in installer EXE.");
            return embedded;
        }

        var manifest = ReadRequiredManifest(processPath);
        var exeDir = InstallerDirectory;
        log($"Installer payload: {manifest.PayloadBaseName}, {FormatGb(manifest.ExpectedBytes)} in {manifest.Parts.Count} part file(s), release {manifest.ReleaseTag}.");

        var localZip = Path.Combine(exeDir, manifest.PayloadBaseName);
        if (File.Exists(localZip) && new FileInfo(localZip).Length == manifest.ExpectedBytes)
        {
            log("Using payload zip next to the installer: " + localZip);
            return new AcquiredPayload(
                manifest.ExpectedSha256,
                manifest.ExpectedBytes,
                () => File.OpenRead(localZip),
                localZip,
                manifest.Homm3UseUpscaledHeroPortraits);
        }

        var cacheDir = GetDownloadCacheDir(manifest);
        var partPaths = new string[manifest.Parts.Count];
        var missing = new List<int>();
        for (var i = 0; i < manifest.Parts.Count; i++)
        {
            var name = manifest.Parts[i];
            var besideExe = Path.Combine(exeDir, name);
            var cached = Path.Combine(cacheDir, name);
            if (IsUsablePart(besideExe, manifest, i))
            {
                partPaths[i] = besideExe;
                log($"Part {i + 1}/{manifest.Parts.Count}: using {name} next to the installer.");
            }
            else if (IsUsablePart(cached, manifest, i))
            {
                partPaths[i] = cached;
                log($"Part {i + 1}/{manifest.Parts.Count}: using cached {cached}.");
            }
            else
            {
                if (File.Exists(besideExe))
                {
                    log($"Part {i + 1}/{manifest.Parts.Count}: {besideExe} has the wrong size ({new FileInfo(besideExe).Length:N0} bytes); it will be downloaded again.");
                }
                missing.Add(i);
            }
        }

        if (missing.Count > 0)
        {
            DownloadMissingParts(manifest, missing, partPaths, exeDir, cacheDir, log, progress);
        }

        var lengths = partPaths.Select(p => new FileInfo(p).Length).ToArray();
        var total = lengths.Sum();
        if (total != manifest.ExpectedBytes)
        {
            throw new InvalidOperationException(
                $"The payload part files add up to {total:N0} bytes, but this installer expects {manifest.ExpectedBytes:N0}. " +
                "One of the part files is incomplete or from a different release. Delete the part files and download them again from the same GitHub Release as this installer.");
        }

        var description = missing.Count == 0
            ? $"{manifest.Parts.Count} payload part file(s) found locally"
            : $"{manifest.Parts.Count} payload part file(s) ({missing.Count} downloaded)";
        return new AcquiredPayload(
            manifest.ExpectedSha256,
            manifest.ExpectedBytes,
            () => new ConcatenatedReadStream(partPaths, lengths),
            description,
            manifest.Homm3UseUpscaledHeroPortraits);
    }

    /// <summary>One-paragraph, user-facing description of where the payload will come from.</summary>
    public static string DescribePlan()
    {
        try
        {
            var processPath = Environment.ProcessPath;
            if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_PACKAGE_PATH")))
            {
                return "The mod payload comes from GOLDEN_ERA_INSTALLER_PACKAGE_PATH.";
            }
            if (string.IsNullOrWhiteSpace(processPath) || !File.Exists(processPath))
            {
                return "The installer will prepare the mod payload first.";
            }
            if (TryResolveAppendedPackage(processPath, out _))
            {
                return "The mod payload is built into this installer, so nothing needs to be downloaded.";
            }
            if (!TryReadDownloadManifest(processPath, out var manifest))
            {
                return "This installer has no payload information. Download the installer again from the GitHub Release.";
            }

            var exeDir = InstallerDirectory;
            var cacheDir = GetDownloadCacheDir(manifest);
            var size = FormatGb(manifest.ExpectedBytes);
            var firstPart = manifest.Parts[0];
            var lastPart = manifest.Parts[^1];
            var found = 0;
            long missingBytes = 0;
            for (var i = 0; i < manifest.Parts.Count; i++)
            {
                if (IsUsablePart(Path.Combine(exeDir, manifest.Parts[i]), manifest, i) ||
                    IsUsablePart(Path.Combine(cacheDir, manifest.Parts[i]), manifest, i))
                {
                    found++;
                }
                else
                {
                    missingBytes += ExpectedPartBytes(manifest, i) ?? manifest.ExpectedBytes / manifest.Parts.Count;
                }
            }

            if (File.Exists(Path.Combine(exeDir, manifest.PayloadBaseName)) || found == manifest.Parts.Count)
            {
                return $"The mod payload ({size} in {manifest.Parts.Count} part files) was found next to this installer, so nothing needs to be downloaded. Its SHA-256 hash is checked before installing.";
            }

            var partRange = manifest.Parts.Count == 1 ? firstPart : $"{firstPart} through {lastPart}";
            var prefix = found == 0
                ? $"The mod payload is {size} in {manifest.Parts.Count} part files ({partRange})."
                : $"{found} of {manifest.Parts.Count} payload part files were found next to this installer.";
            return prefix +
                   $" The installer will download the missing {FormatGb(missingBytes)} from the {manifest.ReleaseTag} GitHub Release and check the SHA-256 hash before installing." +
                   " To install offline, put all the part files from that Release in the same folder as this installer.";
        }
        catch (Exception ex)
        {
            return "The installer will prepare the mod payload first. (" + ex.Message + ")";
        }
    }

    public static IReadOnlyList<string> DescribeDownloadUrls()
    {
        var processPath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(processPath) || !TryReadDownloadManifest(processPath, out var manifest))
        {
            return [];
        }

        return manifest.Parts.Select(part => BuildReleaseAssetUrl(manifest, part)).ToArray();
    }

    internal static DownloadManifest ReadRequiredManifest(string installerPath)
    {
        if (!TryReadDownloadManifest(installerPath, out var manifest))
        {
            throw new InvalidOperationException(
                "This installer EXE does not contain its payload information (it may be truncated or modified). Download the installer again from the GitHub Release.");
        }

        ValidateManifest(manifest);
        return manifest;
    }

    public static bool TryReadDownloadManifest(string installerPath, out DownloadManifest manifest)
    {
        manifest = default!;
        var info = new FileInfo(installerPath);
        if (info.Length < DownloadFooterTrailerLength)
        {
            return false;
        }

        using var stream = File.Open(installerPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        stream.Seek(-DownloadFooterTrailerLength, SeekOrigin.End);

        Span<byte> lengthBytes = stackalloc byte[sizeof(long)];
        if (stream.Read(lengthBytes) != sizeof(long))
        {
            return false;
        }

        Span<byte> magicBytes = stackalloc byte[8];
        if (stream.Read(magicBytes) != 8)
        {
            return false;
        }

        var magic = Encoding.ASCII.GetString(magicBytes);
        if (!string.Equals(magic, DownloadFooterMagic, StringComparison.Ordinal))
        {
            return false;
        }

        var jsonLength = BitConverter.ToInt64(lengthBytes);
        if (jsonLength <= 0 || jsonLength > 1024 * 1024 || jsonLength > info.Length - DownloadFooterTrailerLength)
        {
            return false;
        }

        stream.Seek(-(DownloadFooterTrailerLength + jsonLength), SeekOrigin.End);
        var jsonBytes = new byte[jsonLength];
        stream.ReadExactly(jsonBytes);

        try
        {
            var parsed = JsonSerializer.Deserialize<DownloadManifest>(jsonBytes, JsonOptions);
            if (parsed is null)
            {
                return false;
            }

            manifest = parsed;
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public static byte[] BuildDownloadManifestFooter(DownloadManifest manifest)
    {
        ValidateManifest(manifest);
        var json = JsonSerializer.SerializeToUtf8Bytes(manifest, JsonOptions);
        var footer = new byte[json.Length + DownloadFooterTrailerLength];
        Buffer.BlockCopy(json, 0, footer, 0, json.Length);
        Buffer.BlockCopy(BitConverter.GetBytes((long)json.Length), 0, footer, json.Length, sizeof(long));
        Buffer.BlockCopy(Encoding.ASCII.GetBytes(DownloadFooterMagic), 0, footer, json.Length + sizeof(long), 8);
        return footer;
    }

    public static IReadOnlyList<string> BuildPartNames(string payloadBaseName, long expectedBytes, long maxPartBytes = DefaultMaxPartBytes)
    {
        if (expectedBytes <= 0)
        {
            throw new InvalidOperationException("expectedBytes must be > 0.");
        }

        if (expectedBytes <= maxPartBytes)
        {
            return [payloadBaseName];
        }

        var partCount = (int)Math.Ceiling(expectedBytes / (double)maxPartBytes);
        var parts = new string[partCount];
        for (var i = 0; i < partCount; i++)
        {
            parts[i] = $"{payloadBaseName}.part{(i + 1):D2}";
        }

        return parts;
    }

    internal static string FormatGb(long bytes) => $"{bytes / 1_000_000_000d:0.0} GB";

    private static string GetDownloadCacheDir(DownloadManifest manifest) => Path.Combine(
        InstallerBackend.GetInstallerCacheRoot(),
        "DownloadCache",
        Sanitize(manifest.ReleaseTag),
        manifest.ExpectedSha256[..Math.Min(12, manifest.ExpectedSha256.Length)]);

    private static long? ExpectedPartBytes(DownloadManifest manifest, int index) =>
        manifest.PartBytes is { } sizes && sizes.Count == manifest.Parts.Count ? sizes[index] : null;

    private static bool IsUsablePart(string path, DownloadManifest manifest, int index)
    {
        if (!File.Exists(path))
        {
            return false;
        }

        var length = new FileInfo(path).Length;
        if (length <= 0)
        {
            return false;
        }

        return ExpectedPartBytes(manifest, index) is not long expected || expected == length;
    }

    private static void DownloadMissingParts(
        DownloadManifest manifest,
        IReadOnlyList<int> missing,
        string[] partPaths,
        string exeDir,
        string cacheDir,
        Action<string> log,
        Action<InstallerProgress>? progress)
    {
        long missingBytes = missing.Sum(i => ExpectedPartBytes(manifest, i) ?? DefaultMaxPartBytes);
        missingBytes = Math.Min(missingBytes, manifest.ExpectedBytes);
        var downloadDir = ChooseDownloadDir(exeDir, cacheDir, missingBytes + DownloadSpaceMarginBytes, log);

        log("============================================================");
        log($"Downloading {missing.Count} of {manifest.Parts.Count} payload part file(s) ({FormatGb(missingBytes)}) from the {manifest.ReleaseTag} GitHub Release.");
        log($"Release: https://github.com/{manifest.GithubOwner}/{manifest.GithubRepo}/releases/tag/{manifest.ReleaseTag}");
        log("Saving parts to: " + downloadDir);
        log("This can take a while. If it is interrupted, run the installer again; finished parts are kept.");
        log("============================================================");

        long done = 0;
        var position = 0;
        foreach (var index in missing)
        {
            position++;
            var name = manifest.Parts[index];
            var destination = Path.Combine(downloadDir, name);
            var url = BuildReleaseAssetUrl(manifest, name);
            log($"DOWNLOAD: part {index + 1}/{manifest.Parts.Count} ({position} of {missing.Count} to fetch): {url}");

            Exception? lastError = null;
            for (var attempt = 1; attempt <= DownloadAttempts; attempt++)
            {
                var tmp = destination + ".tmp";
                var before = done;
                try
                {
                    if (File.Exists(tmp))
                    {
                        File.Delete(tmp);
                    }

                    DownloadFile(url, tmp, manifest, index, missingBytes, ref done, log, progress);
                    File.Move(tmp, destination, overwrite: true);
                    lastError = null;
                    break;
                }
                catch (ReleaseAssetNotFoundException)
                {
                    TryDelete(tmp);
                    throw;
                }
                catch (Exception ex) when (ex is HttpRequestException or IOException or TaskCanceledException && !InstallerBackend.IsDiskFull(ex))
                {
                    TryDelete(tmp);
                    done = before;
                    lastError = ex;
                    log($"DOWNLOAD: attempt {attempt}/{DownloadAttempts} for {name} failed: {ex.Message}");
                }
            }

            if (lastError is not null)
            {
                throw new InvalidOperationException(
                    $"Could not download {name} after {DownloadAttempts} attempts: {lastError.Message}. Check your internet connection and run the installer again, or download the part files from the GitHub Release and put them next to the installer.",
                    lastError);
            }

            partPaths[index] = destination;
            log($"DOWNLOAD: finished {name}.");
        }

        progress?.Invoke(InstallerProgress.OfBytes("Download complete", "All payload parts are present.", 1, 1));
    }

    private static string ChooseDownloadDir(string exeDir, string cacheDir, long bytesNeeded, Action<string> log)
    {
        // Prefer the installer folder: downloaded parts then sit exactly where an offline install
        // expects them, and a later Repair can reuse them without downloading again.
        foreach (var candidate in new[] { exeDir, cacheDir })
        {
            try
            {
                Directory.CreateDirectory(candidate);
                var probe = Path.Combine(candidate, ".golden-era-write-test-" + Guid.NewGuid().ToString("N"));
                File.WriteAllText(probe, "ok");
                File.Delete(probe);
                var free = InstallerBackend.GetFreeBytes(candidate);
                if (free >= bytesNeeded)
                {
                    return candidate;
                }

                log($"Not enough free space for the download in {candidate}: {FormatGb(free)} free, {FormatGb(bytesNeeded)} needed.");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                log($"Cannot save downloads in {candidate}: {ex.Message}");
            }
        }

        throw new InvalidOperationException(
            $"There is not enough free disk space to download the mod payload ({FormatGb(bytesNeeded)} needed). " +
            "Free up space, or put the installer and the downloaded part files on a drive with more room and run it from there.");
    }

    private sealed class ReleaseAssetNotFoundException(string message) : InvalidOperationException(message);

    private static void DownloadFile(
        string url,
        string destinationPath,
        DownloadManifest manifest,
        int partIndex,
        long totalToDownload,
        ref long downloadedTotal,
        Action<string> log,
        Action<InstallerProgress>? progress)
    {
        var partName = manifest.Parts[partIndex];
        var partLabel = $"part {partIndex + 1}/{manifest.Parts.Count}";
        using var response = Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            throw new ReleaseAssetNotFoundException(
                $"GitHub returned 404 Not Found for {url}. The {manifest.ReleaseTag} release may not be published yet, or it does not have this file. " +
                "Download every payload part file from the release page and put them next to this installer, then run it again.");
        }
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException(
                $"GitHub returned {(int)response.StatusCode} {response.ReasonPhrase} for {url}");
        }

        var contentLength = response.Content.Headers.ContentLength;
        if (ExpectedPartBytes(manifest, partIndex) is long expectedPart && contentLength is > 0 && contentLength.Value != expectedPart)
        {
            throw new InvalidOperationException(
                $"The release asset {partName} is {contentLength.Value:N0} bytes, but this installer expects {expectedPart:N0}. The release assets do not match this installer.");
        }

        using var input = response.Content.ReadAsStream();
        long partDownloaded = 0;
        using (var output = new FileStream(destinationPath, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
        {
            var buffer = new byte[1024 * 1024];
            var lastReport = DateTime.MinValue;
            var lastLoggedBytes = 0L;
            int read;
            while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
            {
                output.Write(buffer, 0, read);
                partDownloaded += read;
                downloadedTotal += read;
                var now = DateTime.UtcNow;
                if ((now - lastReport) >= TimeSpan.FromSeconds(1))
                {
                    lastReport = now;
                    progress?.Invoke(InstallerProgress.OfBytes(
                        "Downloading payload",
                        $"Downloading {partLabel}: {partName}",
                        downloadedTotal,
                        totalToDownload));
                }

                if (partDownloaded - lastLoggedBytes >= 256L * 1024L * 1024L)
                {
                    lastLoggedBytes = partDownloaded;
                    var partTotal = contentLength is > 0 ? $"/{contentLength.Value / 1e6:0}" : "";
                    log($"DOWNLOAD: {partLabel} {partDownloaded / 1e6:0}{partTotal} MB | overall {downloadedTotal / 1e6:0}/{totalToDownload / 1e6:0} MB");
                }
            }
        }

        if (contentLength is > 0 && partDownloaded != contentLength.Value)
        {
            throw new IOException(
                $"Incomplete download for {url}: expected {contentLength.Value:N0} bytes, received {partDownloaded:N0}.");
        }
        if (ExpectedPartBytes(manifest, partIndex) is long expected && partDownloaded != expected)
        {
            throw new IOException(
                $"Incomplete download for {url}: expected {expected:N0} bytes, received {partDownloaded:N0}.");
        }
    }

    internal static string BuildReleaseAssetUrl(DownloadManifest manifest, string assetName)
    {
        var overrideBase = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_RELEASE_BASE_URL");
        if (!string.IsNullOrWhiteSpace(overrideBase))
        {
            return overrideBase.TrimEnd('/') + "/" + Uri.EscapeDataString(assetName);
        }

        return string.Concat(
            "https://github.com/",
            Uri.EscapeDataString(manifest.GithubOwner),
            "/",
            Uri.EscapeDataString(manifest.GithubRepo),
            "/releases/download/",
            Uri.EscapeDataString(manifest.ReleaseTag),
            "/",
            Uri.EscapeDataString(assetName));
    }

    private static void ValidateManifest(DownloadManifest manifest)
    {
        if (!string.Equals(manifest.Schema, "golden_era_payload_download/v1", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Unsupported payload download manifest schema: " + manifest.Schema);
        }

        if (string.IsNullOrWhiteSpace(manifest.GithubOwner) ||
            string.IsNullOrWhiteSpace(manifest.GithubRepo) ||
            string.IsNullOrWhiteSpace(manifest.ReleaseTag) ||
            string.IsNullOrWhiteSpace(manifest.PayloadBaseName) ||
            string.IsNullOrWhiteSpace(manifest.ExpectedSha256) ||
            manifest.ExpectedBytes <= 0 ||
            manifest.Parts is null ||
            manifest.Parts.Count == 0)
        {
            throw new InvalidOperationException("Payload download manifest is incomplete.");
        }

        if (manifest.ExpectedSha256.Length != 64 ||
            !manifest.ExpectedSha256.All(static c => Uri.IsHexDigit(c)))
        {
            throw new InvalidOperationException("Payload download manifest expectedSha256 is invalid.");
        }

        foreach (var name in manifest.Parts.Append(manifest.PayloadBaseName))
        {
            if (string.IsNullOrWhiteSpace(name) ||
                name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                name is "." or "..")
            {
                throw new InvalidOperationException("Payload download manifest has an invalid file name: " + name);
            }
        }

        if (manifest.PartBytes is { } sizes &&
            (sizes.Count != manifest.Parts.Count || sizes.Any(s => s <= 0) || sizes.Sum() != manifest.ExpectedBytes))
        {
            throw new InvalidOperationException("Payload download manifest partBytes do not add up to expectedBytes.");
        }
    }

    private static bool TryResolveAppendedPackage(string installerPath, out AcquiredPayload payload)
    {
        payload = default!;
        const string magic = "GERAPKG1";
        const int hashLength = 64;
        const int footerLength = hashLength + sizeof(long) + 8;
        var info = new FileInfo(installerPath);
        if (info.Length < footerLength)
        {
            return false;
        }

        using var stream = File.Open(installerPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        stream.Seek(-footerLength, SeekOrigin.End);

        Span<byte> hashBytes = stackalloc byte[hashLength];
        if (stream.Read(hashBytes) != hashLength)
        {
            return false;
        }

        Span<byte> lengthBytes = stackalloc byte[sizeof(long)];
        if (stream.Read(lengthBytes) != sizeof(long))
        {
            return false;
        }

        Span<byte> magicBytes = stackalloc byte[8];
        if (stream.Read(magicBytes) != 8)
        {
            return false;
        }

        if (!string.Equals(Encoding.ASCII.GetString(magicBytes), magic, StringComparison.Ordinal))
        {
            return false;
        }

        var payloadLength = BitConverter.ToInt64(lengthBytes);
        if (payloadLength <= 0 || payloadLength > info.Length - footerLength)
        {
            return false;
        }

        var expectedHash = Encoding.ASCII.GetString(hashBytes).Trim().ToLowerInvariant();
        if (expectedHash.Length != hashLength)
        {
            return false;
        }

        var payloadOffset = info.Length - footerLength - payloadLength;
        payload = new AcquiredPayload(
            expectedHash,
            payloadLength,
            () => new ConcatenatedReadStream([installerPath], [payloadLength], payloadOffset),
            installerPath + "#embedded",
            Homm3UseUpscaledHeroPortraits: null);
        return true;
    }

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient
        {
            Timeout = TimeSpan.FromHours(6)
        };
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("GoldenEraModInstaller", SanitizeProductVersion(InstallerBackend.PackageVersion)));
        client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("*/*"));
        return client;
    }

    private static string SanitizeProductVersion(string version)
    {
        var builder = new StringBuilder();
        foreach (var ch in version)
        {
            builder.Append(char.IsLetterOrDigit(ch) || ch is '.' or '-' or '_' ? ch : '-');
        }

        return builder.Length == 0 ? "local" : builder.ToString();
    }

    private static string ComputeFileSha256(string path, Action<string> log, Action<InstallerProgress>? progress)
    {
        using var stream = File.OpenRead(path);
        return InstallerBackend.ComputeStreamSha256WithProgress(stream, stream.Length, "Verifying payload", progress);
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
        }
    }

    private static string Sanitize(string text)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var builder = new StringBuilder(text.Length);
        foreach (var ch in text)
        {
            builder.Append(invalid.Contains(ch) ? '_' : ch);
        }

        return builder.ToString();
    }

    /// <summary>
    /// Read-only, seekable view of several files (or a slice of one file) as one stream, so the
    /// split payload can be hashed and unzipped in place without joining the parts on disk.
    /// </summary>
    internal sealed class ConcatenatedReadStream : Stream
    {
        private readonly string[] paths;
        private readonly long[] lengths;
        private readonly long[] starts;
        private readonly long firstOffset;
        private readonly long totalLength;
        private FileStream? current;
        private int currentIndex = -1;
        private long position;

        public ConcatenatedReadStream(IReadOnlyList<string> paths, IReadOnlyList<long> lengths, long firstOffset = 0)
        {
            if (paths.Count == 0 || paths.Count != lengths.Count)
            {
                throw new ArgumentException("paths and lengths must be non-empty and the same size.");
            }

            this.paths = paths.ToArray();
            this.lengths = lengths.ToArray();
            this.firstOffset = firstOffset;
            starts = new long[this.paths.Length];
            long sum = 0;
            for (var i = 0; i < this.paths.Length; i++)
            {
                starts[i] = sum;
                sum += this.lengths[i];
            }

            totalLength = sum;
        }

        public override bool CanRead => true;
        public override bool CanSeek => true;
        public override bool CanWrite => false;
        public override long Length => totalLength;

        public override long Position
        {
            get => position;
            set => Seek(value, SeekOrigin.Begin);
        }

        public override int Read(byte[] buffer, int offset, int count) => Read(buffer.AsSpan(offset, count));

        public override int Read(Span<byte> buffer)
        {
            if (buffer.Length == 0 || position >= totalLength)
            {
                return 0;
            }

            var index = FindIndex(position);
            var stream = OpenPart(index);
            var withinPart = position - starts[index];
            var fileOffset = withinPart + (index == 0 ? firstOffset : 0);
            if (stream.Position != fileOffset)
            {
                stream.Position = fileOffset;
            }

            var allowed = (int)Math.Min(buffer.Length, lengths[index] - withinPart);
            var read = stream.Read(buffer[..allowed]);
            if (read <= 0)
            {
                throw new EndOfStreamException($"Payload part ended early: {paths[index]}");
            }

            position += read;
            return read;
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            var target = origin switch
            {
                SeekOrigin.Begin => offset,
                SeekOrigin.Current => position + offset,
                SeekOrigin.End => totalLength + offset,
                _ => throw new ArgumentOutOfRangeException(nameof(origin))
            };
            if (target < 0)
            {
                throw new IOException("Seek before the start of the payload.");
            }

            position = target;
            return position;
        }

        public override void Flush()
        {
        }

        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        private int FindIndex(long pos)
        {
            var index = Array.BinarySearch(starts, pos);
            if (index < 0)
            {
                index = ~index - 1;
            }

            // Skip zero-length entries.
            while (index < lengths.Length - 1 && pos - starts[index] >= lengths[index])
            {
                index++;
            }

            return index;
        }

        private FileStream OpenPart(int index)
        {
            if (currentIndex == index && current is not null)
            {
                return current;
            }

            current?.Dispose();
            current = new FileStream(paths[index], FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 16, FileOptions.RandomAccess);
            currentIndex = index;
            return current;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                current?.Dispose();
                current = null;
            }

            base.Dispose(disposing);
        }
    }
}
