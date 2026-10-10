using Microsoft.Win32;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace GoldenEraModInstaller;

internal enum InstallerOperation
{
    Install,
    Update,
    Repair,
    Uninstall
}

internal sealed record InstallRequest(
    InstallerOperation Operation,
    string SourceGameRoot,
    string TargetGameRoot,
    string Homm3Root,
    bool TargetIsAutoDefault);

internal static class InstallerBackend
{
    private const string StateRelativePath = @"BepInEx\plugins\OfflineUnlockMod.install-state.json";
    private const string PluginRelativePath = @"BepInEx\plugins\OfflineUnlockMod";
    private const string StagingFolderName = ".golden-era-package";
    private const long DiskSpaceMarginBytes = 1_000_000_000L;
    private const ulong CompatibleSteamAppId = 3105440;
    private const ulong CompatibleSteamDepotId = 3105441;
    private const ulong CompatibleSteamManifestId = 7750145598966689713;
    private const string CompatibleGameAssemblySha256 = "d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a";
    private const string CompatibleCoreZipSha256 = "f11b90c19aae60908a4d503e639f2abf7a02c5d706cdb072879ef9773812d954";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    public static string PackageVersion { get; } = GetPackageVersion();

    public static string CompatibleSteamConsoleUri => "steam://open/console";

    public static string CompatibleSteamDepotCommand =>
        $"download_depot {CompatibleSteamAppId} {CompatibleSteamDepotId} {CompatibleSteamManifestId}";

    public static string? GetExpectedSteamDepotPath()
    {
        return FindSteamRoots()
            .Select(BuildExpectedSteamDepotPath)
            .FirstOrDefault();
    }

    public static bool TryFindCompatibleSteamDepot(out string depotPath, out string summary)
    {
        string? lastFailure = null;
        foreach (var candidate in FindSteamRoots().Select(BuildExpectedSteamDepotPath))
        {
            if (!Directory.Exists(candidate))
            {
                continue;
            }

            try
            {
                summary = ValidateCompatibleSteamDepot(candidate);
                depotPath = candidate;
                return true;
            }
            catch (Exception ex)
            {
                lastFailure = candidate + ": " + ex.Message;
            }
        }

        depotPath = "";
        summary = lastFailure is null
            ? "Steam depot download was not found yet. In Steam's console, run: " + CompatibleSteamDepotCommand
            : "Steam depot download was found, but it did not validate. " + lastFailure;
        return false;
    }

    public static string ValidateCompatibleSteamDepot(string path)
    {
        var root = RequireGameRoot(path, "Steam depot download folder");
        return ValidateCompatibleGameRoot(root, "Compatible Steam depot verified");
    }

    public static bool IsExpectedSteamDepotContentRoot(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        return FindSteamRoots()
            .Select(BuildExpectedSteamDepotPath)
            .Any(candidate => SamePath(full, candidate));
    }

    public static void DeleteExpectedSteamDepotContentRoot(string path)
    {
        if (!IsExpectedSteamDepotContentRoot(path))
        {
            throw new InvalidOperationException("Refusing to delete a folder that is not the expected Steam depot content cache path.");
        }

        var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        ValidateCompatibleSteamDepot(full);
        if (Directory.Exists(full))
        {
            Directory.Delete(full, recursive: true);
        }
    }

    public static void Run(InstallRequest request, Action<string> log, Action<InstallerProgress>? progress = null)
    {
        log($"Golden Era installer {PackageVersion}: {request.Operation.ToString().ToLowerInvariant()}");
        try
        {
            switch (request.Operation)
            {
                case InstallerOperation.Install:
                case InstallerOperation.Repair:
                    InstallOrRepair(request, log, progress);
                    break;
                case InstallerOperation.Update:
                    UpdateExistingInstall(request, log, progress);
                    break;
                case InstallerOperation.Uninstall:
                    Uninstall(request, log);
                    break;
                default:
                    throw new InvalidOperationException("Unknown installer operation.");
            }
        }
        catch (Exception ex) when (IsDiskFull(ex))
        {
            throw new InvalidOperationException(
                "The drive ran out of free space during the " + request.Operation.ToString().ToLowerInvariant() +
                ". Free up space on the modded copy's drive (or choose a modded copy folder on another drive) and run the installer again. " +
                "Details: " + ex.Message,
                ex);
        }
    }

    public static void VerifyEmbeddedPayload(Action<string> log, Action<InstallerProgress>? progress = null)
    {
        var payloadSource = PayloadAcquisition.Resolve(log, progress);
        using var stream = payloadSource.OpenRead();
        VerifyPayloadHash(stream, payloadSource, log, progress);
        stream.Position = 0;
        using var zip = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: true);
        // Entry names may use either separator depending on the tool that built the zip.
        var entries = new Dictionary<string, ZipArchiveEntry>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in zip.Entries)
        {
            entries.TryAdd(NormalizeZipPath(entry.FullName), entry);
        }

        foreach (var required in RequiredPayloadEntries)
        {
            if (!entries.ContainsKey(required))
            {
                throw new InvalidOperationException("Release payload is missing " + required + ".");
            }
        }

        var manifestEntry = entries["core_overlay/manifest.json"];
        string manifestText;
        using (var reader = new StreamReader(manifestEntry.Open(), Encoding.UTF8, detectEncodingFromByteOrderMarks: true))
        {
            manifestText = reader.ReadToEnd();
        }

        var manifest = ParseOverlayManifest(manifestText);
        if (manifest.OperationCount != manifest.Operations.Count)
        {
            throw new InvalidOperationException($"Overlay manifest operation count mismatch: declared {manifest.OperationCount}, found {manifest.Operations.Count}.");
        }

        log("Verified release payload: " + payloadSource.SourceDescription);
        log("Zip entries: " + zip.Entries.Count.ToString("N0") + ", uncompressed " + PayloadAcquisition.FormatGb(zip.Entries.Sum(e => e.Length)));
        log("Overlay operations: " + manifest.Operations.Count.ToString("N0"));
    }

    private static readonly string[] RequiredPayloadEntries =
    [
        "payload/BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll",
        "payload/BepInEx/core/BepInEx.Unity.IL2CPP.dll",
        "payload/game_root/winhttp.dll",
        "payload/game_root/dotnet/coreclr.dll",
        "core_overlay/manifest.json"
    ];

    public static string GetPreferredTargetRoot(string sourceRoot)
    {
        if (!string.IsNullOrWhiteSpace(sourceRoot))
        {
            try
            {
                var fullSource = Path.GetFullPath(Environment.ExpandEnvironmentVariables(sourceRoot));
                var parent = Directory.GetParent(fullSource);
                if (parent is not null)
                {
                    return FirstUsableTargetName(Path.Combine(parent.FullName, "Heroes of Might and Magic Olden Era - Golden Era"));
                }
            }
            catch
            {
            }
        }

        return GetLocalAppDataTargetRoot();
    }

    private static string FirstUsableTargetName(string baseTarget)
    {
        // Never suggest a folder that already holds files this installer did not create
        // (for example a hand-made modded copy): Install refuses to touch it anyway.
        for (var i = 1; i < 100; i++)
        {
            var candidate = i == 1 ? baseTarget : $"{baseTarget} {i}";
            if (!Directory.Exists(candidate) ||
                !Directory.EnumerateFileSystemEntries(candidate).Any() ||
                File.Exists(Path.Combine(candidate, StateRelativePath)))
            {
                return candidate;
            }
        }

        return baseTarget;
    }

    public static bool IsValidHomm3Root(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Directory.Exists(path)) return false;

        var hasHeroes3Exe = File.Exists(Path.Combine(path, "Heroes3.exe")) ||
                            File.Exists(Path.Combine(path, "HD_Launcher.exe")) ||
                            File.Exists(Path.Combine(path, "HOMM3 2.0.exe")) ||
                            File.Exists(Path.Combine(path, "HOMM3Launcher.exe")) ||
                            File.Exists(Path.Combine(path, "Might & Magic Heroes III - HD Edition.exe")) ||
                            File.Exists(Path.Combine(path, "Heroes of Might & Magic III - HD Edition.exe"));
        if (!hasHeroes3Exe) return false;

        var data = Path.Combine(path, "Data");
        var hasCompleteLods = File.Exists(Path.Combine(data, "H3bitmap.lod")) &&
                              File.Exists(Path.Combine(data, "H3sprite.lod")) &&
                              File.Exists(Path.Combine(data, "H3ab_bmp.lod")) &&
                              File.Exists(Path.Combine(data, "H3ab_spr.lod"));
        var hasHdMarkers = Directory.Exists(Path.Combine(path, "_HD3_Data")) ||
                           path.Contains("HD Edition", StringComparison.OrdinalIgnoreCase);

        return hasCompleteLods || hasHdMarkers;
    }

    private static string ValidateCompatibleGameRoot(string root, string successPrefix)
    {
        var gameAssembly = Path.Combine(root, "GameAssembly.dll");
        var metadata = Path.Combine(root, @"HeroesOldenEra_Data\il2cpp_data\Metadata\global-metadata.dat");
        var coreZip = GetCoreZipPath(root);

        RequireFile(gameAssembly, "Selected source is missing GameAssembly.dll.");
        RequireFile(metadata, "Selected source is missing global-metadata.dat.");
        RequireFile(coreZip, "Selected source is missing Core.zip.");

        var gameAssemblyHash = ComputeFileSha256(gameAssembly);
        var metadataHash = ComputeFileSha256(metadata);
        var coreZipHash = ComputeFileSha256(coreZip);
        RequireHash(gameAssemblyHash, CompatibleGameAssemblySha256, "GameAssembly.dll");
        RequireHash(coreZipHash, CompatibleCoreZipSha256, "Core.zip");

        return string.Join(Environment.NewLine,
            successPrefix + ": " + root,
            "  manifest: " + CompatibleSteamManifestId,
            "  GameAssembly.dll SHA-256: " + gameAssemblyHash,
            "  global-metadata.dat SHA-256: " + metadataHash,
            "  Core.zip SHA-256: " + coreZipHash);
    }

    private static void InstallOrRepair(InstallRequest request, Action<string> log, Action<InstallerProgress>? progress)
    {
        var sourceRoot = RequireGameRoot(request.SourceGameRoot, "clean Olden Era source folder");
        var homm3Root = RequireHomm3Root(request.Homm3Root);
        var preferredTarget = GetPreferredTargetRoot(sourceRoot);
        var targetRoot = ResolveTargetRoot(request.TargetGameRoot, preferredTarget, request.TargetIsAutoDefault);

        GuardDistinctRoots(sourceRoot, targetRoot);
        GuardTargetIsOursOrEmpty(targetRoot);
        log("Clean source: " + sourceRoot);
        log("Modded copy: " + targetRoot);

        progress?.Invoke(InstallerProgress.Indeterminate("Checking source", "Checking the clean Olden Era folder..."));
        log("Validating compatible Olden Era source binaries...");
        log(ValidateCompatibleGameRoot(sourceRoot, "Compatible Olden Era source verified"));

        Directory.CreateDirectory(targetRoot);
        var stagingRoot = Path.Combine(targetRoot, StagingFolderName);
        try
        {
            var sourceBytes = GetDirectorySize(sourceRoot, relative => !ShouldSkipSourceEntry(relative, isDirectory: false));
            var existingBytes = GetDirectorySize(targetRoot, _ => true);
            var package = PreparePackageCache(log, progress, stagingRoot, Math.Max(0, sourceBytes - existingBytes));
            var overlayManifest = LoadOverlayManifest(package.OverlayManifestPath);

            log("Validating clean source Core.zip...");
            ValidateSourceCoreZip(GetCoreZipPath(sourceRoot), overlayManifest);

            log($"Copying clean Olden Era files to the modded copy ({PayloadAcquisition.FormatGb(sourceBytes)})...");
            progress?.Invoke(InstallerProgress.Indeterminate("Copying game", "Copying the clean Olden Era folder to the modded copy..."));
            CopyCleanGameRoot(sourceRoot, targetRoot, log, progress, sourceBytes);

            log("Installing BepInEx, Doorstop, Golden Era payload, and live-parity binaries into target copy...");
            progress?.Invoke(InstallerProgress.Indeterminate("Installing mod", "Installing BepInEx and the Golden Era payload..."));
            InstallPayloadIntoTarget(targetRoot, package.ExtractRoot);

            log("Applying Core.zip overlay to target copy...");
            progress?.Invoke(InstallerProgress.Indeterminate("Patching Core.zip", "Applying the Golden Era Core.zip overlay..."));
            var cleanCoreBackup = ApplyCoreOverlay(GetCoreZipPath(targetRoot), package.OverlayManifestPath, package.ExtractRoot);
            ValidatePatchedCoreZip(GetCoreZipPath(targetRoot), overlayManifest);

            var launcherPath = WriteLauncher(targetRoot);
            ConfigureWineDllOverride(log);
            WriteInstallState(
                targetRoot,
                sourceRoot,
                homm3Root,
                package,
                launcherPath,
                cleanCoreBackup,
                existingState: null,
                request.Operation == InstallerOperation.Repair ? "repair" : "install");

            log("Clean source folder was left unchanged: " + sourceRoot);
            log("Golden Era target copy: " + targetRoot);
            log("Launcher: " + launcherPath);
        }
        finally
        {
            DeleteStaging(stagingRoot, log);
        }
    }

    private static void GuardTargetIsOursOrEmpty(string targetRoot)
    {
        if (!Directory.Exists(targetRoot) || !Directory.EnumerateFileSystemEntries(targetRoot).Any())
        {
            return;
        }

        if (File.Exists(Path.Combine(targetRoot, StateRelativePath)))
        {
            return;
        }

        var onlyLeftovers = Directory.EnumerateFileSystemEntries(targetRoot)
            .All(entry => string.Equals(Path.GetFileName(entry), StagingFolderName, StringComparison.OrdinalIgnoreCase));
        if (onlyLeftovers)
        {
            return;
        }

        throw new InvalidOperationException(
            "The modded copy folder already contains files that were not installed by this installer: " + targetRoot +
            ". To protect them, the installer will not overwrite it. Choose a new or empty folder for the Golden Era copy" +
            " (or delete that folder yourself first if it is a leftover from a failed install).");
    }

    private static void UpdateExistingInstall(InstallRequest request, Action<string> log, Action<InstallerProgress>? progress)
    {
        var targetRoot = RequireTargetGameRoot(request.TargetGameRoot, "Golden Era target folder");
        var state = ReadInstallState(targetRoot);
        ValidateSideBySideState(targetRoot, state);

        var stagingRoot = Path.Combine(targetRoot, StagingFolderName);
        try
        {
            UpdateFromStaging(request, targetRoot, state, stagingRoot, log, progress);
        }
        finally
        {
            DeleteStaging(stagingRoot, log);
        }
    }

    private static void UpdateFromStaging(
        InstallRequest request,
        string targetRoot,
        InstallState state,
        string stagingRoot,
        Action<string> log,
        Action<InstallerProgress>? progress)
    {
        var package = PreparePackageCache(log, progress, stagingRoot, extraBytesNeeded: 0);
        var overlayManifest = LoadOverlayManifest(package.OverlayManifestPath);
        var targetCoreZip = GetCoreZipPath(targetRoot);
        var cleanCoreBackup = ResolveCleanCoreBackup(targetRoot, state, overlayManifest, log);

        log("Using clean target Core.zip baseline: " + cleanCoreBackup);
        var timestamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var previousPatchedCoreBackup = $"{targetCoreZip}.backup-before-update-{timestamp}";
        File.Copy(targetCoreZip, previousPatchedCoreBackup, overwrite: true);

        string? newCleanCoreBackup = null;
        try
        {
            log("Restoring clean Core.zip baseline into target copy...");
            File.Copy(cleanCoreBackup, targetCoreZip, overwrite: true);

            log("Applying Core.zip overlay to target copy...");
            newCleanCoreBackup = ApplyCoreOverlay(targetCoreZip, package.OverlayManifestPath, package.ExtractRoot);
            ValidatePatchedCoreZip(targetCoreZip, overlayManifest);

            log("Refreshing BepInEx, Doorstop, Golden Era payload, and live-parity binaries in target copy...");
            ReplaceModFilesInTarget(targetRoot, package.ExtractRoot);

            var launcherPath = WriteLauncher(targetRoot);
            ConfigureWineDllOverride(log);
            WriteInstallState(
                targetRoot,
                state.SourceGameRoot ?? request.SourceGameRoot,
                state.Homm3Root ?? request.Homm3Root,
                package,
                launcherPath,
                newCleanCoreBackup,
                state,
                "update");

            log("Updated Golden Era target copy: " + targetRoot);
            log("Previous patched Core.zip backup: " + previousPatchedCoreBackup);
            log("Launcher: " + launcherPath);
        }
        catch
        {
            if (File.Exists(previousPatchedCoreBackup))
            {
                File.Copy(previousPatchedCoreBackup, targetCoreZip, overwrite: true);
            }
            throw;
        }
    }

    private static void Uninstall(InstallRequest request, Action<string> log)
    {
        var targetRootText = string.IsNullOrWhiteSpace(request.TargetGameRoot)
            ? request.SourceGameRoot
            : request.TargetGameRoot;
        if (string.IsNullOrWhiteSpace(targetRootText))
        {
            throw new InvalidOperationException("Choose the modded copy folder to uninstall.");
        }

        var targetRoot = Path.GetFullPath(Environment.ExpandEnvironmentVariables(targetRootText));
        var statePath = Path.Combine(targetRoot, StateRelativePath);
        if (!File.Exists(statePath))
        {
            throw new InvalidOperationException("No Golden Era side-by-side install state was found in the selected target folder.");
        }

        var state = JsonSerializer.Deserialize<InstallState>(File.ReadAllText(statePath), JsonOptions)
            ?? throw new InvalidOperationException("Install state is unreadable.");
        ValidateSideBySideState(targetRoot, state);
        if (!File.Exists(Path.Combine(targetRoot, "HeroesOldenEra.exe")))
        {
            throw new InvalidOperationException("Selected target folder does not contain HeroesOldenEra.exe.");
        }

        log("Removing side-by-side Golden Era target copy: " + targetRoot);
        Directory.Delete(targetRoot, recursive: true);
        log("Steam source folder was left unchanged: " + state.SourceGameRoot);
    }

    private static PackageCache PreparePackageCache(
        Action<string> log,
        Action<InstallerProgress>? progress,
        string stagingRoot,
        long extraBytesNeeded)
    {
        progress?.Invoke(InstallerProgress.Indeterminate("Preparing payload", "Finding the Golden Era release payload..."));
        var payloadSource = PayloadAcquisition.Resolve(log, progress);
        var expectedHash = payloadSource.ExpectedSha256.ToLowerInvariant();

        if (Directory.Exists(stagingRoot))
        {
            Directory.Delete(stagingRoot, recursive: true);
        }

        using (var stream = payloadSource.OpenRead())
        {
            VerifyPayloadHash(stream, payloadSource, log, progress);
            stream.Position = 0;
            using var zip = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: true);
            var uncompressed = zip.Entries.Sum(e => e.Length);
            var needed = uncompressed + extraBytesNeeded + DiskSpaceMarginBytes;
            var parent = Directory.GetParent(stagingRoot)!.FullName;
            var free = GetFreeBytes(parent);
            log($"Disk space on {Path.GetPathRoot(parent)}: {PayloadAcquisition.FormatGb(free)} free, about {PayloadAcquisition.FormatGb(needed)} needed (payload {PayloadAcquisition.FormatGb(uncompressed)} + game files {PayloadAcquisition.FormatGb(extraBytesNeeded)} + margin).");
            if (free < needed)
            {
                throw new InvalidOperationException(
                    $"Not enough free disk space for the Golden Era copy: {PayloadAcquisition.FormatGb(free)} free on {Path.GetPathRoot(parent)}, about {PayloadAcquisition.FormatGb(needed)} needed. " +
                    "Free up space or choose a modded copy folder on a drive with more room.");
            }

            log("Unpacking release payload into the modded copy...");
            ExtractZip(zip, stagingRoot, uncompressed, progress);
        }

        File.WriteAllText(Path.Combine(stagingRoot, ".golden-era-cache-hash"), expectedHash, Encoding.ASCII);
        if (payloadSource.Homm3UseUpscaledHeroPortraits is bool useUpscaled)
        {
            ApplyPortraitConfig(stagingRoot, useUpscaled, log);
        }

        progress?.Invoke(InstallerProgress.OfBytes("Payload ready", "Release payload is ready.", 1, 1));

        var overlayManifestPath = Path.Combine(stagingRoot, @"core_overlay\manifest.json");
        RequireFile(Path.Combine(stagingRoot, @"payload\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll"), "Release payload is missing OfflineUnlockMod.dll.");
        RequireFile(Path.Combine(stagingRoot, @"payload\BepInEx\core\BepInEx.Unity.IL2CPP.dll"), "Release payload is missing BepInEx IL2CPP core.");
        RequireFile(Path.Combine(stagingRoot, @"payload\game_root\winhttp.dll"), "Release payload is missing Doorstop winhttp.dll.");
        RequireFile(Path.Combine(stagingRoot, @"payload\game_root\dotnet\coreclr.dll"), "Release payload is missing Doorstop CoreCLR runtime.");
        RequireFile(overlayManifestPath, "Release payload is missing Core overlay manifest.");

        return new PackageCache(payloadSource.SourceDescription, stagingRoot, payloadSource.SourceDescription, overlayManifestPath, expectedHash, ComputeFileSha256(overlayManifestPath));
    }

    private static void VerifyPayloadHash(Stream stream, PayloadAcquisition.AcquiredPayload payloadSource, Action<string> log, Action<InstallerProgress>? progress)
    {
        log($"Checking SHA-256 of the release payload ({PayloadAcquisition.FormatGb(payloadSource.ExpectedBytes)})...");
        var actual = ComputeStreamSha256WithProgress(stream, payloadSource.ExpectedBytes, "Verifying payload", progress);
        if (!string.Equals(actual, payloadSource.ExpectedSha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"The release payload failed its SHA-256 check (expected {payloadSource.ExpectedSha256}, got {actual}). " +
                "A part file is damaged or from a different release. Delete the payload part files, download them again from the same GitHub Release as this installer, and run it again.");
        }

        log("Payload SHA-256 OK: " + actual);
    }

    private static void ExtractZip(ZipArchive zip, string destinationRoot, long totalBytes, Action<InstallerProgress>? progress)
    {
        var root = EnsureTrailingSeparator(Path.GetFullPath(destinationRoot));
        Directory.CreateDirectory(root);
        long done = 0;
        var lastReport = DateTime.MinValue;
        var buffer = new byte[1 << 20];
        foreach (var entry in zip.Entries)
        {
            var destination = Path.GetFullPath(Path.Combine(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
            if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Release payload contains an unsafe path: " + entry.FullName);
            }

            if (string.IsNullOrEmpty(entry.Name))
            {
                Directory.CreateDirectory(destination);
                continue;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            using (var input = entry.Open())
            using (var output = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 16))
            {
                int read;
                while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                {
                    output.Write(buffer, 0, read);
                    done += read;
                    var now = DateTime.UtcNow;
                    if ((now - lastReport) >= TimeSpan.FromMilliseconds(500))
                    {
                        lastReport = now;
                        progress?.Invoke(InstallerProgress.OfBytes("Unpacking payload", "Unpacking the Golden Era payload...", done, totalBytes));
                    }
                }
            }

            File.SetLastWriteTime(destination, entry.LastWriteTime.DateTime);
        }
    }

    private static void DeleteStaging(string stagingRoot, Action<string> log)
    {
        try
        {
            if (Directory.Exists(stagingRoot))
            {
                Directory.Delete(stagingRoot, recursive: true);
            }
        }
        catch (Exception ex)
        {
            log("Could not remove the temporary payload folder " + stagingRoot + ": " + ex.Message + " (it is safe to delete it by hand).");
        }
    }

    private static void ApplyPortraitConfig(string extractRoot, bool useUpscaledHeroPortraits, Action<string> log)
    {
        var configPath = Path.Combine(extractRoot, @"payload\BepInEx\plugins\OfflineUnlockMod\config.json");
        RequireFile(configPath, "Release payload is missing OfflineUnlockMod config.json.");
        var node = JsonNode.Parse(File.ReadAllText(configPath)) as JsonObject
            ?? throw new InvalidOperationException("OfflineUnlockMod config.json is not a JSON object.");
        node["homm3UseUpscaledHeroPortraits"] = useUpscaledHeroPortraits;
        File.WriteAllText(configPath, node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
        log(useUpscaledHeroPortraits
            ? "Configured installer for upscaled HoMM3 hero portraits."
            : "Configured installer for standard HoMM3 hero portraits.");
    }

    private static void ValidateSourceCoreZip(string coreZipPath, OverlayManifest manifest)
    {
        RequireFile(coreZipPath, "Missing release Core.zip in source game folder.");

        using var zip = ZipFile.OpenRead(coreZipPath);
        var entries = zip.Entries
            .Where(e => !string.IsNullOrEmpty(e.Name))
            .ToDictionary(e => NormalizeZipPath(e.FullName), StringComparer.OrdinalIgnoreCase);

        foreach (var operation in manifest.Operations)
        {
            if (operation.Operation == "add_member")
            {
                if (entries.ContainsKey(operation.Path))
                {
                    throw new InvalidOperationException($"Source Core.zip already contains Golden Era member {operation.Path}. Choose a clean Steam source folder.");
                }
                continue;
            }

            if (!entries.TryGetValue(operation.Path, out var entry))
            {
                throw new InvalidOperationException($"Source Core.zip is missing expected vanilla member {operation.Path}. Steam may have updated the game.");
            }

            var currentHash = ComputeEntrySha256(entry);
            if (string.Equals(currentHash, operation.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException($"Source Core.zip member {operation.Path} is already patched. Choose a clean Steam source folder.");
            }
            if (!string.Equals(currentHash, operation.PreviousSha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException($"Source Core.zip member {operation.Path} does not match the expected vanilla baseline. Steam may have updated the game.");
            }
        }
    }

    private static void ValidatePatchedCoreZip(string coreZipPath, OverlayManifest manifest)
    {
        using var zip = ZipFile.OpenRead(coreZipPath);
        var entries = zip.Entries
            .Where(e => !string.IsNullOrEmpty(e.Name))
            .ToDictionary(e => NormalizeZipPath(e.FullName), StringComparer.OrdinalIgnoreCase);

        foreach (var requiredMember in manifest.RequiredCoreMembers)
        {
            if (!entries.ContainsKey(requiredMember))
            {
                throw new InvalidOperationException($"Patched Core.zip validation failed: missing {requiredMember}.");
            }
        }

        if (manifest.RequiredCoreTokens.Count == 0)
        {
            return;
        }

        if (!entries.TryGetValue("DB/data.json", out var dataEntry))
        {
            throw new InvalidOperationException("Patched Core.zip validation failed: missing DB/data.json.");
        }
        using var stream = dataEntry.Open();
        using var reader = new StreamReader(stream, Encoding.UTF8);
        var dataJson = reader.ReadToEnd();
        foreach (var token in manifest.RequiredCoreTokens)
        {
            if (!dataJson.Contains(token, StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"Patched Core.zip validation failed: DB/data.json does not contain {token}.");
            }
        }
    }

    private static void CopyCleanGameRoot(string sourceRoot, string targetRoot, Action<string> log, Action<InstallerProgress>? progress, long totalBytes)
    {
        Directory.CreateDirectory(targetRoot);
        CleanTargetModFiles(targetRoot);

        var copiedFiles = 0;
        long copiedBytes = 0;
        var lastReport = DateTime.MinValue;
        void Report(long bytes)
        {
            copiedBytes += bytes;
            var now = DateTime.UtcNow;
            if ((now - lastReport) >= TimeSpan.FromMilliseconds(500))
            {
                lastReport = now;
                progress?.Invoke(InstallerProgress.OfBytes("Copying game", "Copying the clean Olden Era folder to the modded copy...", copiedBytes, totalBytes));
            }
        }

        CopyDirectoryContents(sourceRoot, targetRoot, sourceRoot, ref copiedFiles, Report);
        log($"Copied or refreshed {copiedFiles:N0} file(s) in target copy.");
    }

    private static void CopyDirectoryContents(string sourceDir, string targetDir, string sourceRoot, ref int copiedFiles, Action<long> report)
    {
        Directory.CreateDirectory(targetDir);

        foreach (var sourceSubDir in Directory.EnumerateDirectories(sourceDir))
        {
            var relative = Path.GetRelativePath(sourceRoot, sourceSubDir);
            if (ShouldSkipSourceEntry(relative, isDirectory: true))
            {
                continue;
            }
            CopyDirectoryContents(sourceSubDir, Path.Combine(targetDir, Path.GetFileName(sourceSubDir)), sourceRoot, ref copiedFiles, report);
        }

        foreach (var sourceFile in Directory.EnumerateFiles(sourceDir))
        {
            var relative = Path.GetRelativePath(sourceRoot, sourceFile);
            if (ShouldSkipSourceEntry(relative, isDirectory: false))
            {
                continue;
            }

            var targetFile = Path.Combine(targetDir, Path.GetFileName(sourceFile));
            Directory.CreateDirectory(Path.GetDirectoryName(targetFile)!);
            File.Copy(sourceFile, targetFile, overwrite: true);
            copiedFiles++;
            report(new FileInfo(sourceFile).Length);
        }
    }

    private static bool ShouldSkipSourceEntry(string relativePath, bool isDirectory)
    {
        var normalized = relativePath.Replace('/', '\\').TrimStart('\\');
        var firstSegment = normalized.Split('\\', 2)[0];
        if (string.Equals(firstSegment, "BepInEx", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(firstSegment, "dotnet", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(firstSegment, StagingFolderName, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (!isDirectory)
        {
            var fileName = Path.GetFileName(normalized);
            if (string.Equals(fileName, "winhttp.dll", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(fileName, "doorstop_config.ini", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(fileName, ".doorstop_version", StringComparison.OrdinalIgnoreCase) ||
                fileName.Contains(".backup-installer-", StringComparison.OrdinalIgnoreCase) ||
                fileName.Contains(".installer-tmp-", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static void CleanTargetModFiles(string targetRoot)
    {
        foreach (var directory in new[]
        {
            Path.Combine(targetRoot, "BepInEx"),
            Path.Combine(targetRoot, "dotnet")
        })
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }

        foreach (var file in new[]
        {
            Path.Combine(targetRoot, "winhttp.dll"),
            Path.Combine(targetRoot, "doorstop_config.ini"),
            Path.Combine(targetRoot, ".doorstop_version")
        })
        {
            if (File.Exists(file))
            {
                File.Delete(file);
            }
        }
    }

    private static void ReplaceModFilesInTarget(string targetRoot, string packageRoot)
    {
        var backupRoot = Path.Combine(targetRoot, ".golden-era-modfiles-backup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        Directory.CreateDirectory(backupRoot);

        try
        {
            MoveModFilesToBackup(targetRoot, backupRoot);
            InstallPayloadIntoTarget(targetRoot, packageRoot);
            Directory.Delete(backupRoot, recursive: true);
        }
        catch
        {
            if (Directory.Exists(backupRoot) && Directory.EnumerateFileSystemEntries(backupRoot).Any())
            {
                CleanTargetModFiles(targetRoot);
                RestoreModFilesFromBackup(targetRoot, backupRoot);
            }
            else if (Directory.Exists(backupRoot))
            {
                Directory.Delete(backupRoot, recursive: true);
            }
            throw;
        }
    }

    private static void MoveModFilesToBackup(string targetRoot, string backupRoot)
    {
        foreach (var directoryName in new[] { "BepInEx", "dotnet" })
        {
            var source = Path.Combine(targetRoot, directoryName);
            if (!Directory.Exists(source))
            {
                continue;
            }

            Directory.Move(source, Path.Combine(backupRoot, directoryName));
        }

        foreach (var fileName in new[] { "winhttp.dll", "doorstop_config.ini", ".doorstop_version" })
        {
            var source = Path.Combine(targetRoot, fileName);
            if (!File.Exists(source))
            {
                continue;
            }

            File.Move(source, Path.Combine(backupRoot, fileName));
        }
    }

    private static void RestoreModFilesFromBackup(string targetRoot, string backupRoot)
    {
        if (!Directory.Exists(backupRoot))
        {
            return;
        }

        foreach (var source in Directory.EnumerateDirectories(backupRoot))
        {
            Directory.Move(source, Path.Combine(targetRoot, Path.GetFileName(source)));
        }

        foreach (var source in Directory.EnumerateFiles(backupRoot))
        {
            File.Move(source, Path.Combine(targetRoot, Path.GetFileName(source)));
        }

        Directory.Delete(backupRoot, recursive: true);
    }

    private static void InstallPayloadIntoTarget(string targetRoot, string packageRoot)
    {
        var rootPayload = Path.Combine(packageRoot, "payload", "game_root");
        var bepinexPayload = Path.Combine(packageRoot, "payload", "BepInEx");
        var pluginPayload = Path.Combine(packageRoot, "payload", "BepInEx", "plugins", "OfflineUnlockMod");

        // The payload is unpacked into a staging folder inside the target, so moving files into
        // place is instant and needs no extra disk space.
        MoveFile(Path.Combine(rootPayload, "winhttp.dll"), Path.Combine(targetRoot, "winhttp.dll"));
        MoveDirectory(Path.Combine(rootPayload, "dotnet"), Path.Combine(targetRoot, "dotnet"));
        if (File.Exists(Path.Combine(rootPayload, ".doorstop_version")))
        {
            MoveFile(Path.Combine(rootPayload, ".doorstop_version"), Path.Combine(targetRoot, ".doorstop_version"));
        }
        WriteDoorstopConfig(Path.Combine(targetRoot, "doorstop_config.ini"));

        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx"));
        MoveDirectory(Path.Combine(bepinexPayload, "core"), Path.Combine(targetRoot, "BepInEx", "core"));
        if (Directory.Exists(Path.Combine(bepinexPayload, "patchers")))
        {
            MoveDirectory(Path.Combine(bepinexPayload, "patchers"), Path.Combine(targetRoot, "BepInEx", "patchers"));
        }
        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx", "config"));
        if (File.Exists(Path.Combine(bepinexPayload, "config", "BepInEx.cfg")))
        {
            CopyFile(Path.Combine(bepinexPayload, "config", "BepInEx.cfg"), Path.Combine(targetRoot, "BepInEx", "config", "BepInEx.cfg"));
            DisableUnityLogListening(Path.Combine(targetRoot, "BepInEx", "config", "BepInEx.cfg"));
        }

        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx", "plugins"));
        MoveDirectory(pluginPayload, Path.Combine(targetRoot, PluginRelativePath));

        ApplyLiveParityPayloads(targetRoot, packageRoot);
    }

    private static void ApplyLiveParityPayloads(string targetRoot, string packageRoot)
    {
        var unityPayload = Path.Combine(packageRoot, "payload", "unity_data");
        var metadataPayload = Path.Combine(packageRoot, "payload", "il2cpp_metadata", "global-metadata.dat");
        var streamingPayload = Path.Combine(packageRoot, "payload", "streaming_assets");

        RequireDirectory(unityPayload, "Release payload is missing unity_data.");
        RequireFile(Path.Combine(unityPayload, "resources.assets"), "Release payload is missing unity_data/resources.assets.");
        RequireFile(Path.Combine(unityPayload, "globalgamemanagers"), "Release payload is missing unity_data/globalgamemanagers.");
        RequireFile(metadataPayload, "Release payload is missing il2cpp_metadata/global-metadata.dat.");
        RequireDirectory(streamingPayload, "Release payload is missing streaming_assets.");
        RequireDirectory(
            Path.Combine(streamingPayload, "maps", "Story_maps"),
            "Release payload is missing streaming_assets/maps/Story_maps.");
        RequireDirectory(
            Path.Combine(streamingPayload, "video"),
            "Release payload is missing streaming_assets/video.");

        var dataRoot = Path.Combine(targetRoot, "HeroesOldenEra_Data");
        RequireDirectory(dataRoot, "Target is missing HeroesOldenEra_Data.");

        MoveFile(
            Path.Combine(unityPayload, "resources.assets"),
            Path.Combine(dataRoot, "resources.assets"));
        MoveFile(
            Path.Combine(unityPayload, "globalgamemanagers"),
            Path.Combine(dataRoot, "globalgamemanagers"));
        MoveFile(
            metadataPayload,
            Path.Combine(dataRoot, "il2cpp_data", "Metadata", "global-metadata.dat"));

        // Additive/overwrite curated StreamingAssets trees without deleting unrelated vanilla files.
        foreach (var file in Directory.EnumerateFiles(streamingPayload, "*", SearchOption.AllDirectories).ToList())
        {
            var relative = Path.GetRelativePath(streamingPayload, file);
            MoveFile(file, Path.Combine(dataRoot, "StreamingAssets", relative));
        }
    }

    private static void RequireDirectory(string path, string message)
    {
        if (!Directory.Exists(path))
        {
            throw new InvalidOperationException(message);
        }
    }

    private static string ApplyCoreOverlay(string coreZipPath, string manifestPath, string packageRoot)
    {
        var manifest = LoadOverlayManifest(manifestPath);
        var operationsByPath = manifest.Operations.ToDictionary(op => op.Path, StringComparer.OrdinalIgnoreCase);
        var timestamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var backup = $"{coreZipPath}.backup-installer-{timestamp}";
        var tmpZip = $"{coreZipPath}.installer-tmp-{timestamp}";

        File.Copy(coreZipPath, backup, overwrite: true);

        try
        {
            using (var src = ZipFile.OpenRead(coreZipPath))
            using (var dst = ZipFile.Open(tmpZip, ZipArchiveMode.Create))
            {
                var written = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var entry in src.Entries)
                {
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        continue;
                    }

                    var normalizedName = NormalizeZipPath(entry.FullName);
                    if (operationsByPath.TryGetValue(normalizedName, out var operation))
                    {
                        var currentHash = ComputeEntrySha256(entry);
                        if (!string.Equals(currentHash, operation.PreviousSha256, StringComparison.OrdinalIgnoreCase) &&
                            !string.Equals(currentHash, operation.Sha256, StringComparison.OrdinalIgnoreCase))
                        {
                            throw new InvalidOperationException($"Target Core.zip member {normalizedName} does not match the expected vanilla or patched baseline.");
                        }

                        var payloadPath = Path.Combine(packageRoot, "core_overlay", operation.Payload.Replace('/', Path.DirectorySeparatorChar));
                        RequireFile(payloadPath, "Overlay payload is missing: " + payloadPath);
                        if (!string.Equals(ComputeFileSha256(payloadPath), operation.Sha256, StringComparison.OrdinalIgnoreCase))
                        {
                            throw new InvalidOperationException("Overlay payload hash mismatch: " + payloadPath);
                        }

                        AddFileToZip(dst, normalizedName, payloadPath);
                    }
                    else
                    {
                        var copied = dst.CreateEntry(normalizedName, CompressionLevel.Optimal);
                        using var input = entry.Open();
                        using var output = copied.Open();
                        input.CopyTo(output);
                    }

                    written.Add(normalizedName);
                }

                foreach (var operation in manifest.Operations)
                {
                    if (written.Contains(operation.Path))
                    {
                        continue;
                    }
                    if (operation.Operation != "add_member")
                    {
                        throw new InvalidOperationException("Expected existing Core.zip member is missing: " + operation.Path);
                    }

                    var payloadPath = Path.Combine(packageRoot, "core_overlay", operation.Payload.Replace('/', Path.DirectorySeparatorChar));
                    RequireFile(payloadPath, "Overlay payload is missing: " + payloadPath);
                    AddFileToZip(dst, operation.Path, payloadPath);
                }
            }

            File.Move(tmpZip, coreZipPath, overwrite: true);
            return backup;
        }
        catch
        {
            if (File.Exists(tmpZip))
            {
                File.Delete(tmpZip);
            }
            if (File.Exists(backup))
            {
                File.Copy(backup, coreZipPath, overwrite: true);
            }
            throw;
        }
    }

    // Under Wine/Proton the builtin winhttp.dll wins over the game folder's copy, so Doorstop (and with
    // it BepInEx and the plugin) never loads while the patched Core.zip still does. The launcher re-applies
    // the per-exe override on every start because the game may run in a different prefix than the installer.
    private static string WriteLauncher(string targetRoot)
    {
        var launcherPath = Path.Combine(targetRoot, "Launch Golden Era.cmd");
        var text = $"""
@echo off
pushd "%~dp0"
reg query "HKLM\Software\Wine" >nul 2>&1
if not errorlevel 1 (
  reg add "HKCU\{WineDllOverridesKey}" /v winhttp /t REG_SZ /d native,builtin /f >nul 2>&1
  set "WINEDLLOVERRIDES=winhttp=n,b"
)
start "" "%~dp0HeroesOldenEra.exe"
popd
""";
        File.WriteAllText(launcherPath, text.ReplaceLineEndings("\r\n"), Encoding.ASCII);
        return launcherPath;
    }

    private const string WineDllOverridesKey = @"Software\Wine\AppDefaults\HeroesOldenEra.exe\DllOverrides";

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    private static extern IntPtr GetModuleHandleW(string moduleName);

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Ansi)]
    private static extern IntPtr GetProcAddress(IntPtr module, string procName);

    internal static bool IsRunningUnderWine()
    {
        try
        {
            var ntdll = GetModuleHandleW("ntdll.dll");
            return ntdll != IntPtr.Zero && GetProcAddress(ntdll, "wine_get_version") != IntPtr.Zero;
        }
        catch
        {
            return false;
        }
    }

    // Per-exe Wine DLL override in the current prefix (no effect on Windows, no other program affected).
    private static void ConfigureWineDllOverride(Action<string> log)
    {
        if (!IsRunningUnderWine())
        {
            return;
        }

        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(WineDllOverridesKey);
            key.SetValue("winhttp", "native,builtin", RegistryValueKind.String);
            log(@"Wine/Proton detected: set winhttp=native,builtin for HeroesOldenEra.exe in this prefix (HKCU\" + WineDllOverridesKey + ").");
        }
        catch (Exception ex)
        {
            log("Wine/Proton detected, but the winhttp DLL override could not be written (" + ex.Message + "). Launch with Launch Golden Era.cmd, or set the Steam launch option WINEDLLOVERRIDES=\"winhttp=n,b\" %command%.");
        }
    }

    private static void WriteInstallState(
        string targetRoot,
        string? sourceRoot,
        string? homm3Root,
        PackageCache package,
        string launcherPath,
        string cleanCoreBackup,
        InstallState? existingState,
        string operation)
    {
        var now = DateTimeOffset.UtcNow.ToString("o");
        var state = new InstallState
        {
            InstallMode = "side-by-side",
            SourceGameRoot = string.IsNullOrWhiteSpace(sourceRoot) ? existingState?.SourceGameRoot : sourceRoot,
            TargetGameRoot = targetRoot,
            Homm3Root = string.IsNullOrWhiteSpace(homm3Root) ? existingState?.Homm3Root : homm3Root,
            PackageVersion = PackageVersion,
            PreviousPackageVersion = existingState?.PackageVersion,
            PackageCacheRoot = package.CacheRoot,
            ReleaseInputZipSha256 = package.ReleaseInputZipSha256,
            OverlayManifestSha256 = package.OverlayManifestSha256,
            CleanCoreBackup = cleanCoreBackup,
            InstalledAt = existingState?.InstalledAt ?? now,
            UpdatedAt = operation == "install" ? null : now,
            LastOperation = operation,
            Launcher = launcherPath
        };

        var statePath = Path.Combine(targetRoot, StateRelativePath);
        Directory.CreateDirectory(Path.GetDirectoryName(statePath)!);
        File.WriteAllText(statePath, JsonSerializer.Serialize(state, JsonOptions), Encoding.UTF8);
    }

    private static InstallState ReadInstallState(string targetRoot)
    {
        var statePath = Path.Combine(targetRoot, StateRelativePath);
        if (!File.Exists(statePath))
        {
            throw new InvalidOperationException("No Golden Era side-by-side install state was found in the selected target folder. Use Install for a new target or Repair with a clean Steam source.");
        }

        return JsonSerializer.Deserialize<InstallState>(File.ReadAllText(statePath), JsonOptions)
               ?? throw new InvalidOperationException("Install state is unreadable.");
    }

    private static void ValidateSideBySideState(string targetRoot, InstallState state)
    {
        if (!string.Equals(state.InstallMode, "side-by-side", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Install state is not for a side-by-side Golden Era install.");
        }
        if (!SamePath(targetRoot, state.TargetGameRoot))
        {
            throw new InvalidOperationException("Selected target folder does not match the install state target.");
        }
        if (SamePath(targetRoot, state.SourceGameRoot))
        {
            throw new InvalidOperationException("Refusing to modify this install because target and source point to the same folder.");
        }
    }

    private static string ResolveCleanCoreBackup(string targetRoot, InstallState state, OverlayManifest manifest, Action<string> log)
    {
        var candidates = new List<string>();
        AddCandidate(candidates, state.CleanCoreBackup);

        var coreZipPath = GetCoreZipPath(targetRoot);
        var streamingAssets = Path.GetDirectoryName(coreZipPath);
        if (!string.IsNullOrWhiteSpace(streamingAssets) && Directory.Exists(streamingAssets))
        {
            foreach (var file in Directory.EnumerateFiles(streamingAssets, "Core.zip.backup-installer-*")
                         .OrderByDescending(File.GetLastWriteTimeUtc))
            {
                AddCandidate(candidates, file);
            }
        }

        foreach (var candidate in candidates)
        {
            if (!File.Exists(candidate))
            {
                continue;
            }

            try
            {
                ValidateSourceCoreZip(candidate, manifest);
                return candidate;
            }
            catch (Exception ex)
            {
                log("Skipping Core.zip baseline candidate: " + candidate);
                log("  " + ex.Message);
            }
        }

        throw new InvalidOperationException("Could not find a clean target Core.zip backup that matches this package. Use Repair with a clean Steam source folder to rebuild the target copy.");
    }

    private static void AddCandidate(List<string> candidates, string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        if (!candidates.Any(existing => SamePath(existing, full)))
        {
            candidates.Add(full);
        }
    }

    private static string ResolveTargetRoot(string targetRoot, string preferredTarget, bool targetIsAutoDefault)
    {
        var selected = string.IsNullOrWhiteSpace(targetRoot) ? preferredTarget : targetRoot;
        var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(selected));
        if (targetIsAutoDefault && !CanPrepareTarget(full))
        {
            full = GetLocalAppDataTargetRoot();
        }
        return full;
    }

    private static bool CanPrepareTarget(string targetRoot)
    {
        try
        {
            var parent = Directory.GetParent(targetRoot)?.FullName;
            if (string.IsNullOrWhiteSpace(parent))
            {
                return false;
            }
            Directory.CreateDirectory(parent);
            var probe = Path.Combine(parent, ".golden-era-write-test-" + Guid.NewGuid().ToString("N"));
            File.WriteAllText(probe, "ok", Encoding.ASCII);
            File.Delete(probe);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static void GuardDistinctRoots(string sourceRoot, string targetRoot)
    {
        if (SamePath(sourceRoot, targetRoot))
        {
            throw new InvalidOperationException("The modded copy folder must be different from the Steam source folder.");
        }

        var sourceFull = EnsureTrailingSeparator(Path.GetFullPath(sourceRoot));
        var targetFull = EnsureTrailingSeparator(Path.GetFullPath(targetRoot));
        if (targetFull.StartsWith(sourceFull, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The modded copy folder must not be inside the Steam source folder.");
        }
        if (sourceFull.StartsWith(targetFull, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The Steam source folder must not be inside the modded copy folder.");
        }
    }

    private static string RequireGameRoot(string path, string label)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException($"Choose the {label} first.");
        }

        var root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        RequireFile(Path.Combine(root, "HeroesOldenEra.exe"), $"The selected {label} does not contain HeroesOldenEra.exe.");
        if (File.Exists(Path.Combine(root, "winhttp.dll")) ||
            File.Exists(Path.Combine(root, "doorstop_config.ini")) ||
            Directory.Exists(Path.Combine(root, PluginRelativePath)))
        {
            throw new InvalidOperationException("The selected Steam source folder already contains mod loader files. Choose a clean vanilla Steam folder.");
        }
        return root;
    }

    private static string RequireTargetGameRoot(string path, string label)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException($"Choose the {label} first.");
        }

        var root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        RequireFile(Path.Combine(root, "HeroesOldenEra.exe"), $"The selected {label} does not contain HeroesOldenEra.exe.");
        RequireFile(GetCoreZipPath(root), $"The selected {label} does not contain Core.zip.");
        return root;
    }

    private static string RequireHomm3Root(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException("Choose the HoMM3 Complete or HoMM3 HD folder first.");
        }

        var root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path));
        if (!IsValidHomm3Root(root))
        {
            throw new InvalidOperationException("The selected HoMM3 folder does not look like HoMM3 Complete or HoMM3 HD.");
        }

        return root;
    }

    private static OverlayManifest LoadOverlayManifest(string manifestPath) => ParseOverlayManifest(File.ReadAllText(manifestPath));

    private static OverlayManifest ParseOverlayManifest(string json)
    {
        var manifest = JsonSerializer.Deserialize<OverlayManifest>(json, JsonOptions)
            ?? throw new InvalidOperationException("Core overlay manifest is unreadable.");
        if (manifest.Format != "hommoe-golden-era-release-overlay-v1" &&
            manifest.Format != "hommoe-stronghold-release-overlay-v1")
        {
            throw new InvalidOperationException("Unsupported Core overlay manifest format: " + manifest.Format);
        }
        return manifest;
    }

    private static string GetPackageVersion()
    {
        var attribute = Assembly.GetExecutingAssembly()
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>();
        var version = attribute?.InformationalVersion;
        if (string.IsNullOrWhiteSpace(version))
        {
            version = Assembly.GetExecutingAssembly().GetName().Version?.ToString();
        }
        return string.IsNullOrWhiteSpace(version) ? "local" : version;
    }

    private static IEnumerable<string> FindSteamRoots()
    {
        var candidates = new List<string>();
        foreach (var regPath in new[]
        {
            (Registry.CurrentUser, @"Software\Valve\Steam"),
            (Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam"),
            (Registry.LocalMachine, @"SOFTWARE\Valve\Steam")
        })
        {
            try
            {
                using var key = regPath.Item1.OpenSubKey(regPath.Item2);
                AddSteamRootCandidate(candidates, key?.GetValue("SteamPath") as string);
                AddSteamRootCandidate(candidates, key?.GetValue("InstallPath") as string);
            }
            catch
            {
            }
        }

        AddSteamRootCandidate(candidates, @"C:\Program Files (x86)\Steam");
        AddSteamRootCandidate(candidates, @"C:\Program Files\Steam");
        return candidates;
    }

    private static void AddSteamRootCandidate(List<string> candidates, string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path.Replace('/', '\\')));
        if (Directory.Exists(full) &&
            !candidates.Any(existing => SamePath(existing, full)))
        {
            candidates.Add(full);
        }
    }

    private static string BuildExpectedSteamDepotPath(string steamRoot)
    {
        return Path.Combine(steamRoot, "steamapps", "content", "app_" + CompatibleSteamAppId, "depot_" + CompatibleSteamDepotId);
    }

    private static void RequireHash(string actual, string expected, string label)
    {
        if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"The selected folder's {label} is not from Olden Era build 25672315 (expected SHA-256 {expected}, found {actual}). " +
                $"Steam may have updated the game. Download the pinned build with the Steam console command \"{CompatibleSteamDepotCommand}\" and select that depot folder.");
        }
    }

    public static string GetInstallerCacheRoot()
    {
        var overrideRoot = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_CACHE_ROOT");
        if (!string.IsNullOrWhiteSpace(overrideRoot))
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(overrideRoot));
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GoldenEra",
            "InstallerCache");
    }

    public static string GetLogDirectory() => Path.Combine(GetInstallerCacheRoot(), "Logs");

    private static string GetLocalAppDataTargetRoot()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GoldenEra",
            "Heroes of Might and Magic Olden Era - Golden Era");
    }

    public static long GetFreeBytes(string path)
    {
        var root = Path.GetPathRoot(Path.GetFullPath(path));
        if (string.IsNullOrWhiteSpace(root))
        {
            return long.MaxValue;
        }

        try
        {
            return new DriveInfo(root).AvailableFreeSpace;
        }
        catch
        {
            return long.MaxValue;
        }
    }

    public static bool IsDiskFull(Exception? ex)
    {
        for (var current = ex; current is not null; current = current.InnerException)
        {
            if (current is IOException)
            {
                var code = current.HResult & 0xFFFF;
                if (code is 112 or 39)
                {
                    return true;
                }
            }
        }

        return false;
    }

    private static long GetDirectorySize(string root, Func<string, bool> includeRelative)
    {
        if (!Directory.Exists(root))
        {
            return 0;
        }

        long total = 0;
        foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(root, file);
            if (relative.StartsWith(StagingFolderName, StringComparison.OrdinalIgnoreCase) || !includeRelative(relative))
            {
                continue;
            }

            try
            {
                total += new FileInfo(file).Length;
            }
            catch
            {
            }
        }

        return total;
    }

    public static string ComputeStreamSha256WithProgress(Stream stream, long totalBytes, string phase, Action<InstallerProgress>? progress)
    {
        using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[4 << 20];
        long done = 0;
        var lastReport = DateTime.MinValue;
        int read;
        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            sha.AppendData(buffer, 0, read);
            done += read;
            var now = DateTime.UtcNow;
            if ((now - lastReport) >= TimeSpan.FromMilliseconds(500))
            {
                lastReport = now;
                progress?.Invoke(InstallerProgress.OfBytes(phase, "Checking the SHA-256 hash of the payload...", done, totalBytes));
            }
        }

        return Convert.ToHexString(sha.GetHashAndReset()).ToLowerInvariant();
    }

    private static string GetCacheBaseRoot() => GetInstallerCacheRoot();

    private static string GetCoreZipPath(string gameRoot)
    {
        return Path.Combine(gameRoot, @"HeroesOldenEra_Data\StreamingAssets\Core.zip");
    }

    private static void WriteDoorstopConfig(string path)
    {
        var text = """
# General options for Unity Doorstop
[General]
enabled = true
target_assembly = BepInEx\core\BepInEx.Unity.IL2CPP.dll
redirect_output_log = false
boot_config_override =
ignore_disable_switch = false

[UnityMono]
dll_search_path_override =
debug_enabled = false
debug_address = 127.0.0.1:10000
debug_suspend = false

[Il2Cpp]
coreclr_path = dotnet\coreclr.dll
corlib_dir = dotnet
""";
        File.WriteAllText(path, text.ReplaceLineEndings("\r\n"), Encoding.ASCII);
    }

    private static void DisableUnityLogListening(string configPath)
    {
        var text = File.ReadAllText(configPath);
        if (text.Contains("UnityLogListening", StringComparison.OrdinalIgnoreCase))
        {
            text = System.Text.RegularExpressions.Regex.Replace(
                text,
                @"(?m)^UnityLogListening\s*=.*$",
                "UnityLogListening = false");
            File.WriteAllText(configPath, text, Encoding.UTF8);
        }
    }

    private static void CopyDirectory(string source, string destination)
    {
        if (Directory.Exists(destination))
        {
            Directory.Delete(destination, recursive: true);
        }
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, directory)));
        }
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            CopyFile(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
        }
    }

    private static void MoveDirectory(string source, string destination)
    {
        RequireDirectory(source, "Missing payload folder: " + source);
        if (Directory.Exists(destination))
        {
            Directory.Delete(destination, recursive: true);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        if (string.Equals(Path.GetPathRoot(Path.GetFullPath(source)), Path.GetPathRoot(Path.GetFullPath(destination)), StringComparison.OrdinalIgnoreCase))
        {
            Directory.Move(source, destination);
        }
        else
        {
            CopyDirectory(source, destination);
        }
    }

    private static void MoveFile(string source, string destination)
    {
        RequireFile(source, "Missing payload file: " + source);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.Move(source, destination, overwrite: true);
    }

    private static void CopyFile(string source, string destination)
    {
        RequireFile(source, "Missing payload file: " + source);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.Copy(source, destination, overwrite: true);
    }

    private static void AddFileToZip(ZipArchive zip, string entryName, string payloadPath)
    {
        var entry = zip.CreateEntry(entryName, CompressionLevel.Optimal);
        using var input = File.OpenRead(payloadPath);
        using var output = entry.Open();
        input.CopyTo(output);
    }

    private static string ComputeEntrySha256(ZipArchiveEntry entry)
    {
        using var stream = entry.Open();
        return ComputeStreamSha256(stream);
    }

    private static string ComputeFileSha256(string path)
    {
        using var stream = File.OpenRead(path);
        return ComputeStreamSha256(stream);
    }

    private static string ComputeStreamSha256(Stream stream)
    {
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
    }

    private static void RequireFile(string path, string message)
    {
        if (!File.Exists(path))
        {
            throw new InvalidOperationException(message);
        }
    }

    private static string NormalizeZipPath(string path)
    {
        return path.Replace('\\', '/').TrimStart('/');
    }

    private static string SanitizePathSegment(string text)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var builder = new StringBuilder(text.Length);
        foreach (var ch in text)
        {
            builder.Append(invalid.Contains(ch) ? '_' : ch);
        }
        return builder.ToString();
    }

    private static bool SamePath(string left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
        {
            return false;
        }
        return string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
            StringComparison.OrdinalIgnoreCase);
    }

    private static string EnsureTrailingSeparator(string path)
    {
        return Path.TrimEndingDirectorySeparator(path) + Path.DirectorySeparatorChar;
    }

    private sealed record PackageCache(
        string CacheRoot,
        string ExtractRoot,
        string PayloadZipPath,
        string OverlayManifestPath,
        string ReleaseInputZipSha256,
        string OverlayManifestSha256);

    private sealed class InstallState
    {
        public string? InstallMode { get; set; }
        public string? SourceGameRoot { get; set; }
        public string? TargetGameRoot { get; set; }
        public string? Homm3Root { get; set; }
        public string? PackageVersion { get; set; }
        public string? PreviousPackageVersion { get; set; }
        public string? PackageCacheRoot { get; set; }
        public string? ReleaseInputZipSha256 { get; set; }
        public string? OverlayManifestSha256 { get; set; }
        public string? CleanCoreBackup { get; set; }
        public string? InstalledAt { get; set; }
        public string? UpdatedAt { get; set; }
        public string? LastOperation { get; set; }
        public string? Launcher { get; set; }
    }

    private sealed class OverlayManifest
    {
        public string Format { get; set; } = "";
        public int OperationCount { get; set; }
        public List<string> RequiredCoreMembers { get; set; } = [];
        public List<string> RequiredCoreTokens { get; set; } = [];
        public List<OverlayOperation> Operations { get; set; } = [];
    }

    private sealed class OverlayOperation
    {
        public string Path { get; set; } = "";
        public string Operation { get; set; } = "";
        public string Payload { get; set; } = "";
        public string Sha256 { get; set; } = "";
        public string PreviousSha256 { get; set; } = "";
    }
}
