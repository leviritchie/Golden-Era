using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GoldenEraModInstaller;

internal static class PayloadAcquisition
{
    internal const string DownloadFooterMagic = "GERADL01";
    private const int DownloadFooterTrailerLength = sizeof(long) + 8;
    private const long DefaultMaxPartBytes = 1_900_000_000L;

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
        bool? Homm3UseUpscaledHeroPortraits);

    internal sealed record AcquiredPayload(
        string ExpectedSha256,
        long ExpectedBytes,
        Func<Stream> OpenRead,
        string SourceDescription,
        bool? Homm3UseUpscaledHeroPortraits);

    public static AcquiredPayload Resolve(Action<string> log, Action<InstallerProgress>? progress = null)
    {
        var overridePath = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_PACKAGE_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(overridePath));
            if (File.Exists(full))
            {
                if (TryResolveAppendedPackage(full, out var appended))
                {
                    log("Using GOLDEN_ERA_INSTALLER_PACKAGE_PATH appended payload: " + full);
                    return appended;
                }

                if (string.Equals(Path.GetExtension(full), ".zip", StringComparison.OrdinalIgnoreCase))
                {
                    var hash = ComputeFileSha256(full);
                    log("Using GOLDEN_ERA_INSTALLER_PACKAGE_PATH zip: " + full);
                    return new AcquiredPayload(hash, new FileInfo(full).Length, () => File.OpenRead(full), full, Homm3UseUpscaledHeroPortraits: null);
                }
            }
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

        if (!TryReadDownloadManifest(processPath, out var manifest))
        {
            throw new InvalidOperationException(
                "This installer EXE has neither an embedded payload nor a GitHub download manifest. Rebuild it with tools\\release_installer\\package_from_release_inputs.ps1.");
        }

        ValidateManifest(manifest);
        var exeDir = Path.GetDirectoryName(Path.GetFullPath(processPath))
            ?? throw new InvalidOperationException("Unable to resolve installer directory.");

        var localZip = Path.Combine(exeDir, manifest.PayloadBaseName);
        if (File.Exists(localZip) && new FileInfo(localZip).Length == manifest.ExpectedBytes)
        {
            var localHash = ComputeFileSha256(localZip);
            if (string.Equals(localHash, manifest.ExpectedSha256, StringComparison.OrdinalIgnoreCase))
            {
                log("Using local payload zip beside installer: " + localZip);
                progress?.Invoke(InstallerProgress.OfBytes("Local payload", "Using payload zip beside the installer.", 1, 1));
                return new AcquiredPayload(
                    manifest.ExpectedSha256,
                    manifest.ExpectedBytes,
                    () => File.OpenRead(localZip),
                    localZip,
                    manifest.Homm3UseUpscaledHeroPortraits);
            }

            throw new InvalidOperationException(
                $"Local payload zip hash mismatch for {localZip}: expected {manifest.ExpectedSha256}, actual {localHash}.");
        }

        var localParts = manifest.Parts
            .Select(name => Path.Combine(exeDir, name))
            .ToArray();
        if (localParts.All(File.Exists))
        {
            log("Assembling payload from local part files beside installer...");
            progress?.Invoke(InstallerProgress.Indeterminate("Assembling local parts", "Joining payload parts found beside the installer..."));
            var assembled = AssemblePartsToTemp(localParts, manifest, log, progress);
            return OpenTempPayload(assembled, manifest);
        }

        log("============================================================");
        log("DOWNLOADING Golden Era payload from GitHub Releases");
        log($"Release: {manifest.GithubOwner}/{manifest.GithubRepo} @ {manifest.ReleaseTag}");
        log($"Size: {manifest.ExpectedBytes / (1024d * 1024d * 1024d):0.00} GB across {manifest.Parts.Count} part(s)");
        log("This can take several minutes. Progress updates will appear below.");
        log("============================================================");
        progress?.Invoke(InstallerProgress.OfBytes(
            "Downloading payload",
            $"Starting download of {manifest.Parts.Count} part(s) from GitHub Releases...",
            0,
            manifest.ExpectedBytes));
        var downloaded = DownloadAndAssemble(manifest, log, progress);
        return OpenTempPayload(downloaded, manifest);
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
        if (jsonLength <= 0 || jsonLength > info.Length - DownloadFooterTrailerLength)
        {
            return false;
        }

        stream.Seek(-(DownloadFooterTrailerLength + jsonLength), SeekOrigin.End);
        var jsonBytes = new byte[jsonLength];
        if (stream.Read(jsonBytes) != jsonLength)
        {
            return false;
        }

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

    private static AcquiredPayload OpenTempPayload(string path, DownloadManifest manifest)
    {
        return new AcquiredPayload(
            manifest.ExpectedSha256,
            manifest.ExpectedBytes,
            () => File.OpenRead(path),
            path,
            manifest.Homm3UseUpscaledHeroPortraits);
    }

    private static string DownloadAndAssemble(DownloadManifest manifest, Action<string> log, Action<InstallerProgress>? progress)
    {
        var cacheRoot = Path.Combine(
            InstallerBackend.GetInstallerCacheRoot(),
            "DownloadCache",
            Sanitize(manifest.ReleaseTag),
            manifest.ExpectedSha256[..Math.Min(12, manifest.ExpectedSha256.Length)]);
        Directory.CreateDirectory(cacheRoot);
        log("Download cache: " + cacheRoot);

        var partPaths = new List<string>(manifest.Parts.Count);
        long downloadedTotal = 0;
        for (var i = 0; i < manifest.Parts.Count; i++)
        {
            var partName = manifest.Parts[i];
            var partPath = Path.Combine(cacheRoot, partName);
            partPaths.Add(partPath);
            if (File.Exists(partPath) && new FileInfo(partPath).Length > 0)
            {
                var existing = new FileInfo(partPath).Length;
                downloadedTotal += existing;
                log($"DOWNLOAD: Using cached part {i + 1}/{manifest.Parts.Count}: {partName} ({existing / (1024d * 1024d):0.0} MB)");
                progress?.Invoke(InstallerProgress.OfBytes(
                    "Downloading payload",
                    $"Using cached part {i + 1}/{manifest.Parts.Count}: {partName}",
                    downloadedTotal,
                    manifest.ExpectedBytes));
                continue;
            }

            var url = BuildReleaseAssetUrl(manifest, partName);
            log($"DOWNLOAD: Starting part {i + 1}/{manifest.Parts.Count}: {partName}");
            log($"DOWNLOAD: {url}");
            progress?.Invoke(InstallerProgress.OfBytes(
                "Downloading payload",
                $"Downloading part {i + 1}/{manifest.Parts.Count}: {partName}",
                downloadedTotal,
                manifest.ExpectedBytes));
            var tmp = partPath + ".tmp";
            if (File.Exists(tmp))
            {
                File.Delete(tmp);
            }

            DownloadFile(url, tmp, manifest.ExpectedBytes, ref downloadedTotal, log, progress, i + 1, manifest.Parts.Count, partName);
            if (File.Exists(partPath))
            {
                File.Delete(partPath);
            }

            File.Move(tmp, partPath);
            log($"DOWNLOAD: Finished part {i + 1}/{manifest.Parts.Count}: {partName}");
        }

        log("DOWNLOAD: All parts present. Joining into payload zip...");
        return AssemblePartsToTemp(partPaths.ToArray(), manifest, log, progress);
    }

    private static string AssemblePartsToTemp(
        IReadOnlyList<string> partPaths,
        DownloadManifest manifest,
        Action<string> log,
        Action<InstallerProgress>? progress = null)
    {
        var cacheRoot = Path.Combine(
            InstallerBackend.GetInstallerCacheRoot(),
            "DownloadCache",
            Sanitize(manifest.ReleaseTag),
            manifest.ExpectedSha256[..Math.Min(12, manifest.ExpectedSha256.Length)]);
        Directory.CreateDirectory(cacheRoot);
        var outputPath = Path.Combine(cacheRoot, manifest.PayloadBaseName);
        var tmpPath = outputPath + ".tmp";

        if (File.Exists(outputPath) &&
            new FileInfo(outputPath).Length == manifest.ExpectedBytes &&
            string.Equals(ComputeFileSha256(outputPath), manifest.ExpectedSha256, StringComparison.OrdinalIgnoreCase))
        {
            log("Using previously assembled payload: " + outputPath);
            progress?.Invoke(InstallerProgress.OfBytes("Payload ready", "Using previously assembled payload.", 1, 1));
            return outputPath;
        }

        if (File.Exists(tmpPath))
        {
            File.Delete(tmpPath);
        }

        log("Joining payload parts...");
        progress?.Invoke(InstallerProgress.Indeterminate("Assembling payload", "Joining downloaded payload parts..."));
        long written = 0;
        using (var output = File.Create(tmpPath))
        {
            var buffer = new byte[1024 * 1024];
            foreach (var partPath in partPaths)
            {
                using var input = File.OpenRead(partPath);
                int read;
                while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                {
                    output.Write(buffer, 0, read);
                    written += read;
                    if (manifest.ExpectedBytes > 0 && written % (64L * 1024L * 1024L) < buffer.Length)
                    {
                        progress?.Invoke(InstallerProgress.OfBytes(
                            "Assembling payload",
                            "Joining downloaded payload parts...",
                            written,
                            manifest.ExpectedBytes));
                    }
                }
            }
        }

        var actualBytes = new FileInfo(tmpPath).Length;
        if (actualBytes != manifest.ExpectedBytes)
        {
            File.Delete(tmpPath);
            throw new InvalidOperationException(
                $"Assembled payload size mismatch: expected {manifest.ExpectedBytes:N0} bytes, actual {actualBytes:N0}.");
        }

        progress?.Invoke(InstallerProgress.Indeterminate("Verifying payload", "Checking SHA-256 of assembled payload..."));
        log("Verifying assembled payload SHA-256...");
        var actualHash = ComputeFileSha256(tmpPath);
        if (!string.Equals(actualHash, manifest.ExpectedSha256, StringComparison.OrdinalIgnoreCase))
        {
            File.Delete(tmpPath);
            throw new InvalidOperationException(
                $"Assembled payload hash mismatch: expected {manifest.ExpectedSha256}, actual {actualHash}.");
        }

        if (File.Exists(outputPath))
        {
            File.Delete(outputPath);
        }

        File.Move(tmpPath, outputPath);
        log("DOWNLOAD COMPLETE: Payload ready at " + outputPath);
        progress?.Invoke(InstallerProgress.OfBytes("Download complete", "Payload download and verification finished.", 1, 1));
        return outputPath;
    }

    private static void DownloadFile(
        string url,
        string destinationPath,
        long totalExpected,
        ref long downloadedTotal,
        Action<string> log,
        Action<InstallerProgress>? progress,
        int partNumber,
        int partCount,
        string partName)
    {
        using var response = Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"Failed to download payload asset from GitHub Releases ({(int)response.StatusCode} {response.ReasonPhrase}): {url}");
        }

        var contentLength = response.Content.Headers.ContentLength;
        using var input = response.Content.ReadAsStream();
        using var output = File.Create(destinationPath);
        var buffer = new byte[1024 * 1024];
        long partDownloaded = 0;
        var lastLogged = 0L;
        var lastProgress = DateTime.UtcNow;
        int read;
        while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
        {
            output.Write(buffer, 0, read);
            partDownloaded += read;
            downloadedTotal += read;
            var now = DateTime.UtcNow;
            var shouldLog = partDownloaded - lastLogged >= 16L * 1024L * 1024L || (now - lastProgress) >= TimeSpan.FromSeconds(2);
            if (shouldLog)
            {
                lastLogged = partDownloaded;
                lastProgress = now;
                var overallMb = downloadedTotal / (1024d * 1024d);
                var totalMb = totalExpected / (1024d * 1024d);
                var pct = totalExpected > 0 ? (100d * downloadedTotal / totalExpected) : 0d;
                if (contentLength is > 0)
                {
                    log($"DOWNLOAD: Part {partNumber}/{partCount} {partDownloaded / (1024d * 1024d):0.0}/{contentLength.Value / (1024d * 1024d):0.0} MB | overall {overallMb:0.0}/{totalMb:0.0} MB ({pct:0.0}%)");
                }
                else
                {
                    log($"DOWNLOAD: Part {partNumber}/{partCount} {partDownloaded / (1024d * 1024d):0.0} MB | overall {overallMb:0.0}/{totalMb:0.0} MB ({pct:0.0}%)");
                }

                progress?.Invoke(InstallerProgress.OfBytes(
                    "Downloading payload",
                    $"Downloading part {partNumber}/{partCount}: {partName}",
                    downloadedTotal,
                    totalExpected));
            }
        }

        if (contentLength is > 0 && partDownloaded != contentLength.Value)
        {
            throw new InvalidOperationException(
                $"Incomplete download for {url}: expected {contentLength.Value:N0} bytes, received {partDownloaded:N0}.");
        }

        progress?.Invoke(InstallerProgress.OfBytes(
            "Downloading payload",
            $"Finished part {partNumber}/{partCount}: {partName}",
            downloadedTotal,
            totalExpected));
    }

    private static string BuildReleaseAssetUrl(DownloadManifest manifest, string assetName)
    {
        var overrideBase = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_RELEASE_BASE_URL");
        if (!string.IsNullOrWhiteSpace(overrideBase))
        {
            return overrideBase.TrimEnd('/') + "/" + Uri.EscapeDataString(assetName).Replace("%2F", "/");
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
    }

    private static bool TryResolveAppendedPackage(string installerPath, out AcquiredPayload payload)
    {
        payload = default!;
        // Delegated to InstallerBackend footer reader via shared constants — keep GERAPKG1 parsing here duplicated lightly.
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
            () =>
            {
                var payloadStream = File.Open(installerPath, FileMode.Open, FileAccess.Read, FileShare.Read);
                payloadStream.Seek(payloadOffset, SeekOrigin.Begin);
                return new BoundedReadStream(payloadStream, payloadLength);
            },
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
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("GoldenEraModInstaller", InstallerBackend.PackageVersion));
        client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("*/*"));
        return client;
    }

    private static string ComputeFileSha256(string path)
    {
        using var stream = File.OpenRead(path);
        var hash = SHA256.HashData(stream);
        return Convert.ToHexString(hash).ToLowerInvariant();
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

    private sealed class BoundedReadStream : Stream
    {
        private readonly Stream inner;
        private long remaining;

        public BoundedReadStream(Stream inner, long length)
        {
            this.inner = inner;
            remaining = length;
        }

        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            if (remaining <= 0)
            {
                return 0;
            }

            var allowed = (int)Math.Min(count, remaining);
            var read = inner.Read(buffer, 0, allowed);
            remaining -= read;
            return read;
        }

        public override int Read(Span<byte> buffer)
        {
            if (remaining <= 0)
            {
                return 0;
            }

            var allowed = (int)Math.Min(buffer.Length, remaining);
            var read = inner.Read(buffer[..allowed]);
            remaining -= read;
            return read;
        }

        public override void Flush()
        {
        }

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                inner.Dispose();
            }

            base.Dispose(disposing);
        }
    }
}
