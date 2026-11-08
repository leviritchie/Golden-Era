using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using BepInEx;

namespace OfflineUnlockMod;

internal enum GameBuildKind
{
	Unknown = 0,
	Golden = 1,
	Current = 2,
}

// Which game build the plugin is running against, chosen by the SHA-256 of GameAssembly.dll
// (GameSymbols.Builds). Obfuscated and Il2CppInterop-generated names are reused for different
// classes between builds (docs/port_to_current_game_version.md section 2), so every hint that
// binds through such a name is only valid for the build it was pinned on:
//   - GameSymbols.TypeGroups carry one hint scope per build; GameMember.ResolveTypeGroup picks the
//     scope for Kind and refuses when that scope is empty.
//   - Flat (unscoped) GameSymbols hints are Golden Era pins. On any other build GameMember refuses
//     the ones that bind through an obfuscated/generated name (see GameMember build gate).
// An unknown hash is never treated as Golden Era. Detection is lazy so resolvers that run before
// Plugin.Load reaches LogIdentity still see the right answer.
internal static class GameBuild
{
	private sealed class Identity
	{
		internal GameBuildKind Kind;
		internal string Sha256;
		internal string Path;
		internal string Error;
		internal long ElapsedMs;
	}

	private static readonly Lazy<Identity> _identity = new(Detect, LazyThreadSafetyMode.ExecutionAndPublication);
	private static int _identityLogged;

	// Retired live builds: Steam no longer serves them, so they are not runtime targets (Kind stays Unknown,
	// fail closed). Their tracked remap/overrides stay under tools/port_current/remap; they are listed only so
	// the log can say why the build is refused.
	internal static readonly (string BuildId, string GameAssemblySha256)[] RetiredBuilds =
	{
		("25061458", "BB4EA1F5B28AF6B3F21031BB53F7FA50021579A8C74ADE2F05904696D6FDB38A"),
		("25509697", "CF5B04145302FEF7A3D355B5457B3CD7AD8409E4AC34062D1C1A85C99AD4C926"),
	};

	internal static GameBuildKind Kind => _identity.Value.Kind;
	internal static bool IsGolden => Kind == GameBuildKind.Golden;
	internal static string Sha256 => _identity.Value.Sha256 ?? "(unavailable)";

	internal static string Describe()
	{
		var id = _identity.Value;
		return "build=" + id.Kind.ToString().ToLowerInvariant() + " GameAssembly.sha256=" + (id.Sha256 ?? "(unavailable)");
	}

	internal static void LogIdentity(BepInEx.Logging.ManualLogSource log)
	{
		if (log == null || Interlocked.Exchange(ref _identityLogged, 1) != 0)
			return;
		var id = _identity.Value;
		if (id.Kind == GameBuildKind.Golden)
		{
			log.LogInfo("GameBuild: Golden Era (GameAssembly.dll sha256 " + id.Sha256 + ", hashed in " + id.ElapsedMs + " ms).");
			return;
		}
		if (id.Kind == GameBuildKind.Current)
		{
			log.LogWarning("GameBuild: current live build " + GameSymbols.CurrentScopes.BuildId + " (GameAssembly.dll sha256 " + id.Sha256
				+ "). Only symbol groups with a populated 'current' scope are enabled; every Golden-Era-only obfuscated/generated hint is refused.");
			return;
		}
		foreach (var retired in RetiredBuilds)
		{
			if (id.Sha256 != null && string.Equals(id.Sha256, retired.GameAssemblySha256, StringComparison.OrdinalIgnoreCase))
			{
				log.LogError("GameBuild: RETIRED game build " + retired.BuildId + " (GameAssembly.dll sha256 " + id.Sha256
					+ "). It is no longer a runtime target, so it is treated as unknown and every feature that binds through obfuscated game symbols is refused. "
					+ "Supported: Golden Era " + GameSymbols.Builds.GoldenGameAssemblySha256 + ", current " + GameSymbols.CurrentScopes.BuildId
					+ " " + GameSymbols.Builds.CurrentGameAssemblySha256 + ".");
				return;
			}
		}
		log.LogError("GameBuild: UNKNOWN game build (GameAssembly.dll "
			+ (id.Sha256 != null ? "sha256 " + id.Sha256 : "unreadable at " + id.Path + ": " + id.Error)
			+ "). Obfuscated game symbols are not pinned for this build, so every feature that binds through them is refused. "
			+ "Known: Golden Era " + GameSymbols.Builds.GoldenGameAssemblySha256 + ", current " + GameSymbols.Builds.CurrentGameAssemblySha256 + ".");
	}

	private static Identity Detect()
	{
		var id = new Identity { Kind = GameBuildKind.Unknown };
		var sw = Stopwatch.StartNew();
		try
		{
			id.Path = System.IO.Path.Combine(Paths.GameRootPath, "GameAssembly.dll");
			using var stream = new FileStream(id.Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 20);
			using var sha = SHA256.Create();
			var digest = sha.ComputeHash(stream);
			var hex = new System.Text.StringBuilder(digest.Length * 2);
			foreach (var b in digest)
				hex.Append(b.ToString("X2", System.Globalization.CultureInfo.InvariantCulture));
			id.Sha256 = hex.ToString();
		}
		catch (Exception ex)
		{
			id.Error = ex.GetType().Name + ": " + ex.Message;
			id.Sha256 = null;
		}
		id.ElapsedMs = sw.ElapsedMilliseconds;
		if (id.Sha256 != null)
		{
			if (string.Equals(id.Sha256, GameSymbols.Builds.GoldenGameAssemblySha256, StringComparison.OrdinalIgnoreCase))
				id.Kind = GameBuildKind.Golden;
			else if (string.Equals(id.Sha256, GameSymbols.Builds.CurrentGameAssemblySha256, StringComparison.OrdinalIgnoreCase))
				id.Kind = GameBuildKind.Current;
		}
		return id;
	}
}
