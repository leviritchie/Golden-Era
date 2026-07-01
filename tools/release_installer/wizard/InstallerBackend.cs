using Microsoft.Win32;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
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
    private const string PayloadFooterMagic = "GERAPKG1";
    private const int PayloadHashLength = 64;
    private const int PayloadFooterLength = PayloadHashLength + sizeof(long) + 8;
    private const string StateRelativePath = @"BepInEx\plugins\OfflineUnlockMod.install-state.json";
    private const string PluginRelativePath = @"BepInEx\plugins\OfflineUnlockMod";
    private const ulong CompatibleSteamAppId = 3105440;
    private const ulong CompatibleSteamDepotId = 3105441;
    private const ulong CompatibleSteamManifestId = 5889655938380499086;
    private const string CompatibleGameAssemblySha256 = "d47706eb0ffedbda0ec07ede47abc778e6022ed820ae1a1fd23522d3acdb8416";
    private const string CompatibleCoreZipSha256 = "b5b1dff2b9cb03447dfc6c31d1070878bcc86f5264497735dc63188c22d9f5ba";

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

    public static void Run(InstallRequest request, Action<string> log)
    {
        switch (request.Operation)
        {
            case InstallerOperation.Install:
            case InstallerOperation.Repair:
                InstallOrRepair(request, log);
                break;
            case InstallerOperation.Update:
                UpdateExistingInstall(request, log);
                break;
            case InstallerOperation.Uninstall:
                Uninstall(request, log);
                break;
            default:
                throw new InvalidOperationException("Unknown installer operation.");
        }
    }

    public static void VerifyEmbeddedPayload(Action<string> log)
    {
        var package = PreparePackageCache(log);
        var manifest = LoadOverlayManifest(package.OverlayManifestPath);
        if (manifest.OperationCount != manifest.Operations.Count)
        {
            throw new InvalidOperationException($"Overlay manifest operation count mismatch: declared {manifest.OperationCount}, found {manifest.Operations.Count}.");
        }

        log("Verified bundled payload: " + package.PayloadZipPath);
        log("Overlay operations: " + manifest.Operations.Count.ToString("N0"));
    }

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
                    return Path.Combine(parent.FullName, "Heroes of Might and Magic Olden Era - Golden Era");
                }
            }
            catch
            {
            }
        }

        return GetLocalAppDataTargetRoot();
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

    private static void InstallOrRepair(InstallRequest request, Action<string> log)
    {
        var sourceRoot = RequireGameRoot(request.SourceGameRoot, "Steam Olden Era source folder");
        var homm3Root = RequireHomm3Root(request.Homm3Root);
        var preferredTarget = GetPreferredTargetRoot(sourceRoot);
        var targetRoot = ResolveTargetRoot(request.TargetGameRoot, preferredTarget, request.TargetIsAutoDefault);

        GuardDistinctRoots(sourceRoot, targetRoot);

        var package = PreparePackageCache(log);
        var overlayManifest = LoadOverlayManifest(package.OverlayManifestPath);

        log("Validating compatible Olden Era source binaries...");
        log(ValidateCompatibleGameRoot(sourceRoot, "Compatible Olden Era source verified"));

        log("Validating clean Steam source Core.zip...");
        ValidateSourceCoreZip(GetCoreZipPath(sourceRoot), overlayManifest);

        log("Copying clean Steam source to modded target...");
        CopyCleanGameRoot(sourceRoot, targetRoot, log);

        log("Installing BepInEx, Doorstop, and Golden Era payload into target copy...");
        InstallPayloadIntoTarget(targetRoot, package.ExtractRoot);

        log("Applying Core.zip overlay to target copy...");
        var cleanCoreBackup = ApplyCoreOverlay(GetCoreZipPath(targetRoot), package.OverlayManifestPath, package.ExtractRoot);
        ValidatePatchedCoreZip(GetCoreZipPath(targetRoot), overlayManifest);

        var launcherPath = WriteLauncher(targetRoot);
        WriteInstallState(
            targetRoot,
            sourceRoot,
            homm3Root,
            package,
            launcherPath,
            cleanCoreBackup,
            existingState: null,
            request.Operation == InstallerOperation.Repair ? "repair" : "install");

        log("Steam source folder was left unchanged: " + sourceRoot);
        log("Golden Era target copy: " + targetRoot);
        log("Launcher: " + launcherPath);
    }

    private static void UpdateExistingInstall(InstallRequest request, Action<string> log)
    {
        var targetRoot = RequireTargetGameRoot(request.TargetGameRoot, "Golden Era target folder");
        var state = ReadInstallState(targetRoot);
        ValidateSideBySideState(targetRoot, state);

        var package = PreparePackageCache(log);
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

            log("Refreshing BepInEx, Doorstop, and Golden Era payload in target copy...");
            ReplaceModFilesInTarget(targetRoot, package.ExtractRoot);

            var launcherPath = WriteLauncher(targetRoot);
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

    private static PackageCache PreparePackageCache(Action<string> log)
    {
        var payloadSource = ResolvePayloadSource();
        var expectedHash = payloadSource.ExpectedSha256;
        var shortHash = expectedHash[..Math.Min(12, expectedHash.Length)];
        var cacheRoot = Path.Combine(
            GetCacheBaseRoot(),
            "PackageCache",
            SanitizePathSegment(PackageVersion),
            shortHash);
        var payloadZipPath = Path.Combine(cacheRoot, "golden_era_release_payload.zip");
        var extractRoot = Path.Combine(cacheRoot, "extracted");
        Directory.CreateDirectory(cacheRoot);

        if (!File.Exists(payloadZipPath) ||
            !string.Equals(ComputeFileSha256(payloadZipPath), expectedHash, StringComparison.OrdinalIgnoreCase))
        {
            log("Extracting bundled release payload to package cache...");
            var tmpZip = payloadZipPath + ".tmp";
            if (File.Exists(tmpZip)) File.Delete(tmpZip);
            using (var resource = payloadSource.OpenRead())
            using (var output = File.Create(tmpZip))
            {
                resource.CopyTo(output);
            }

            var actualHash = ComputeFileSha256(tmpZip);
            if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(tmpZip);
                throw new InvalidOperationException($"Embedded release payload hash mismatch: expected {expectedHash}, actual {actualHash}.");
            }

            if (File.Exists(payloadZipPath)) File.Delete(payloadZipPath);
            File.Move(tmpZip, payloadZipPath);
        }
        else
        {
            log("Using cached release payload: " + payloadZipPath);
        }

        var markerPath = Path.Combine(extractRoot, ".golden-era-cache-hash");
        if (!File.Exists(markerPath) ||
            !string.Equals(File.ReadAllText(markerPath).Trim(), expectedHash, StringComparison.OrdinalIgnoreCase) ||
            !File.Exists(Path.Combine(extractRoot, @"core_overlay\manifest.json")) ||
            !File.Exists(Path.Combine(extractRoot, @"payload\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll")))
        {
            if (Directory.Exists(extractRoot))
            {
                Directory.Delete(extractRoot, recursive: true);
            }
            Directory.CreateDirectory(extractRoot);
            log("Expanding release payload cache...");
            ZipFile.ExtractToDirectory(payloadZipPath, extractRoot, overwriteFiles: true);
            File.WriteAllText(markerPath, expectedHash, Encoding.ASCII);
        }

        var overlayManifestPath = Path.Combine(extractRoot, @"core_overlay\manifest.json");
        RequireFile(Path.Combine(extractRoot, @"payload\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll"), "Release payload is missing OfflineUnlockMod.dll.");
        RequireFile(Path.Combine(extractRoot, @"payload\BepInEx\core\BepInEx.Unity.IL2CPP.dll"), "Release payload is missing BepInEx IL2CPP core.");
        RequireFile(Path.Combine(extractRoot, @"payload\game_root\winhttp.dll"), "Release payload is missing Doorstop winhttp.dll.");
        RequireFile(Path.Combine(extractRoot, @"payload\game_root\dotnet\coreclr.dll"), "Release payload is missing Doorstop CoreCLR runtime.");
        RequireFile(overlayManifestPath, "Release payload is missing Core overlay manifest.");

        return new PackageCache(cacheRoot, extractRoot, payloadZipPath, overlayManifestPath, expectedHash, ComputeFileSha256(overlayManifestPath));
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

    private static void CopyCleanGameRoot(string sourceRoot, string targetRoot, Action<string> log)
    {
        Directory.CreateDirectory(targetRoot);
        CleanTargetModFiles(targetRoot);

        var copiedFiles = 0;
        CopyDirectoryContents(sourceRoot, targetRoot, sourceRoot, ref copiedFiles);
        log($"Copied or refreshed {copiedFiles:N0} file(s) in target copy.");
    }

    private static void CopyDirectoryContents(string sourceDir, string targetDir, string sourceRoot, ref int copiedFiles)
    {
        Directory.CreateDirectory(targetDir);

        foreach (var sourceSubDir in Directory.EnumerateDirectories(sourceDir))
        {
            var relative = Path.GetRelativePath(sourceRoot, sourceSubDir);
            if (ShouldSkipSourceEntry(relative, isDirectory: true))
            {
                continue;
            }
            CopyDirectoryContents(sourceSubDir, Path.Combine(targetDir, Path.GetFileName(sourceSubDir)), sourceRoot, ref copiedFiles);
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
        }
    }

    private static bool ShouldSkipSourceEntry(string relativePath, bool isDirectory)
    {
        var normalized = relativePath.Replace('/', '\\').TrimStart('\\');
        var firstSegment = normalized.Split('\\', 2)[0];
        if (string.Equals(firstSegment, "BepInEx", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(firstSegment, "dotnet", StringComparison.OrdinalIgnoreCase))
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

        CopyFile(Path.Combine(rootPayload, "winhttp.dll"), Path.Combine(targetRoot, "winhttp.dll"));
        CopyDirectory(Path.Combine(rootPayload, "dotnet"), Path.Combine(targetRoot, "dotnet"));
        if (File.Exists(Path.Combine(rootPayload, ".doorstop_version")))
        {
            CopyFile(Path.Combine(rootPayload, ".doorstop_version"), Path.Combine(targetRoot, ".doorstop_version"));
        }
        WriteDoorstopConfig(Path.Combine(targetRoot, "doorstop_config.ini"));

        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx"));
        CopyDirectory(Path.Combine(bepinexPayload, "core"), Path.Combine(targetRoot, "BepInEx", "core"));
        if (Directory.Exists(Path.Combine(bepinexPayload, "patchers")))
        {
            CopyDirectory(Path.Combine(bepinexPayload, "patchers"), Path.Combine(targetRoot, "BepInEx", "patchers"));
        }
        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx", "config"));
        if (File.Exists(Path.Combine(bepinexPayload, "config", "BepInEx.cfg")))
        {
            CopyFile(Path.Combine(bepinexPayload, "config", "BepInEx.cfg"), Path.Combine(targetRoot, "BepInEx", "config", "BepInEx.cfg"));
            DisableUnityLogListening(Path.Combine(targetRoot, "BepInEx", "config", "BepInEx.cfg"));
        }

        Directory.CreateDirectory(Path.Combine(targetRoot, "BepInEx", "plugins"));
        CopyDirectory(pluginPayload, Path.Combine(targetRoot, PluginRelativePath));
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

    private static string WriteLauncher(string targetRoot)
    {
        var launcherPath = Path.Combine(targetRoot, "Launch Golden Era.cmd");
        var text = """
@echo off
pushd "%~dp0"
start "" "%~dp0HeroesOldenEra.exe"
popd
""";
        File.WriteAllText(launcherPath, text.ReplaceLineEndings("\r\n"), Encoding.ASCII);
        return launcherPath;
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

    private static OverlayManifest LoadOverlayManifest(string manifestPath)
    {
        var manifest = JsonSerializer.Deserialize<OverlayManifest>(File.ReadAllText(manifestPath), JsonOptions)
            ?? throw new InvalidOperationException("Core overlay manifest is unreadable.");
        if (manifest.Format != "hommoe-golden-era-release-overlay-v1" &&
            manifest.Format != "hommoe-stronghold-release-overlay-v1")
        {
            throw new InvalidOperationException("Unsupported Core overlay manifest format: " + manifest.Format);
        }
        return manifest;
    }

    private static PayloadSource ResolvePayloadSource()
    {
        var overridePath = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_PACKAGE_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) &&
            File.Exists(overridePath) &&
            TryResolveAppendedPayload(overridePath, out var overrideSource))
        {
            return overrideSource;
        }

        var processPath = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(processPath) &&
            File.Exists(processPath) &&
            TryResolveAppendedPayload(processPath, out var source))
        {
            return source;
        }

        throw new InvalidOperationException("This installer EXE does not contain an appended Golden Era payload. Rebuild it with tools\\release_installer\\package_from_release_inputs.ps1.");
    }

    private static bool TryResolveAppendedPayload(string installerPath, out PayloadSource source)
    {
        source = default!;
        var info = new FileInfo(installerPath);
        if (info.Length < PayloadFooterLength)
        {
            return false;
        }

        using var stream = File.Open(installerPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        stream.Seek(-PayloadFooterLength, SeekOrigin.End);

        Span<byte> hashBytes = stackalloc byte[PayloadHashLength];
        if (stream.Read(hashBytes) != PayloadHashLength)
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

        var magic = Encoding.ASCII.GetString(magicBytes);
        if (!string.Equals(magic, PayloadFooterMagic, StringComparison.Ordinal))
        {
            return false;
        }

        var payloadLength = BitConverter.ToInt64(lengthBytes);
        if (payloadLength <= 0 || payloadLength > info.Length - PayloadFooterLength)
        {
            return false;
        }

        var payloadOffset = info.Length - PayloadFooterLength - payloadLength;
        var expectedHash = Encoding.ASCII.GetString(hashBytes).Trim().ToLowerInvariant();
        if (expectedHash.Length != PayloadHashLength)
        {
            return false;
        }

        source = new PayloadSource(
            installerPath,
            expectedHash,
            payloadLength,
            () =>
            {
                var payloadStream = File.Open(installerPath, FileMode.Open, FileAccess.Read, FileShare.Read);
                payloadStream.Seek(payloadOffset, SeekOrigin.Begin);
                return new BoundedReadStream(payloadStream, payloadLength);
            });
        return true;
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
            throw new InvalidOperationException($"Downloaded depot {label} hash mismatch. Expected {expected}, actual {actual}.");
        }
    }

    private static string GetLocalAppDataTargetRoot()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GoldenEra",
            "OldenEra");
    }

    private static string GetCacheBaseRoot()
    {
        var overrideRoot = Environment.GetEnvironmentVariable("GOLDEN_ERA_INSTALLER_CACHE_ROOT");
        if (!string.IsNullOrWhiteSpace(overrideRoot))
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(overrideRoot));
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GoldenEra");
    }

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

    private sealed record PayloadSource(
        string InstallerPath,
        string ExpectedSha256,
        long Length,
        Func<Stream> OpenRead);

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
            var read = inner.Read(buffer, offset, allowed);
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
