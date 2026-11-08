using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;

namespace OfflineUnlockMod;

internal static class Homm3DiagnosticFlags
{
	private static readonly Dictionary<string, bool> Cache = new(StringComparer.OrdinalIgnoreCase);

	internal static bool IsEnabled(string flagFileName)
	{
		if (string.IsNullOrWhiteSpace(flagFileName))
			return false;
		if (Cache.TryGetValue(flagFileName, out var enabled))
			return enabled;

		enabled =
			File.Exists(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", flagFileName))
			|| File.Exists(Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", flagFileName));
		Cache[flagFileName] = enabled;
		return enabled;
	}
}
