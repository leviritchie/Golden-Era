using System;
using System.IO;
using System.Reflection;
using System.Threading;
using BepInEx;

namespace OfflineUnlockMod;

/// <summary>
/// Persistent breadcrumbs for crash-prone diagnostic patches.
/// Untested: this is intentionally diagnostic-only and should be promoted to proven
/// only after a runtime crash or pilot confirms the breadcrumb file is written.
/// </summary>
internal static class Homm3DiagnosticBreadcrumbs
{
	private const string FileName = "homm3_last_diagnostic_breadcrumb.txt";
	private static bool _warnedWriteFailure;

	internal static void Enter(string diagnostic, MethodBase method, string stage)
	{
		try
		{
			var directory = Path.Combine(Paths.PluginPath, "OfflineUnlockMod");
			Directory.CreateDirectory(directory);
			File.WriteAllText(Path.Combine(directory, FileName),
				DateTime.UtcNow.ToString("O")
				+ " diagnostic="
				+ (diagnostic ?? "?")
				+ " stage="
				+ (stage ?? "?")
				+ " thread="
				+ Thread.CurrentThread.ManagedThreadId
				+ " method="
				+ FormatMethod(method));
		}
		catch (Exception ex)
		{
			if (_warnedWriteFailure)
				return;
			_warnedWriteFailure = true;
			Plugin.LogSource?.LogWarning("HoMM3 diagnostic breadcrumb write failed closed: " + ex.Message);
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
