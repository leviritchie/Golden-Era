using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using BepInEx;
using BepInEx.Logging;

namespace OfflineUnlockMod;

/// <summary>
/// Opt-in reflection dump for Il2Cpp types related to localization (LocKit / map loc).
/// Enable by creating an empty file next to <c>OfflineUnlockMod.dll</c> (same folder):
/// <c>BepInEx/plugins/OfflineUnlockMod/loc_kit_debug.flag</c>
/// Then read <c>BepInEx/LogOutput.log</c> for lines starting with <c>[LocKitDebug]</c>.
/// </summary>
internal static class LocKitDebugProbe
{
	private const string FlagFileName = "loc_kit_debug.flag";
	private const int MaxTypesToDump = 48;
	private const int MaxMethodsPerType = 48;

	internal static void TryRun(ManualLogSource log)
	{
		var modDir = Path.GetDirectoryName(typeof(LocKitDebugProbe).Assembly.Location);
		var flag = modDir != null ? Path.Combine(modDir, FlagFileName) : Path.Combine(Paths.PluginPath, "OfflineUnlockMod", FlagFileName);
		if (!File.Exists(flag))
		{
			return;
		}

		try
		{
			RunAllAssemblies(log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("[LocKitDebug] probe failed: " + ex);
		}
	}

	private static Type[] SafeGetTypes(Assembly a)
	{
		try
		{
			return a.GetTypes();
		}
		catch (ReflectionTypeLoadException e)
		{
			return e.Types.Where(t => t != null).Cast<Type>().ToArray();
		}
		catch
		{
			return Type.EmptyTypes;
		}
	}

	private static bool InterestingTypeName(string fullName)
	{
		if (string.IsNullOrEmpty(fullName))
		{
			return false;
		}

		var n = fullName;
		if (n.IndexOf("LocKit", StringComparison.Ordinal) >= 0)
		{
			return true;
		}

		if (n.IndexOf("MapInfoLocalization", StringComparison.Ordinal) >= 0)
		{
			return true;
		}

		if (!n.StartsWith("Hex.", StringComparison.Ordinal))
		{
			return false;
		}

		if (n.IndexOf("LocInfo", StringComparison.Ordinal) >= 0)
		{
			return true;
		}

		if (n.IndexOf("LocString", StringComparison.Ordinal) >= 0)
		{
			return true;
		}

		if (n.IndexOf("Localization", StringComparison.Ordinal) >= 0)
		{
			return true;
		}

		return false;
	}

	private static void RunAllAssemblies(ManualLogSource log)
	{
		var asms = AppDomain.CurrentDomain.GetAssemblies().OrderBy(a => a.FullName, StringComparer.Ordinal).ToArray();
		log?.LogInfo("[LocKitDebug] flag present — scanning " + asms.Length + " loaded assemblies (excluding this mod) for loc-related type names…");

		var hits = new List<(Assembly Asm, Type Type)>();
		var seenAq = new HashSet<string>(StringComparer.Ordinal);

		var selfAsm = typeof(LocKitDebugProbe).Assembly;
		foreach (var asm in asms)
		{
			if (ReferenceEquals(asm, selfAsm))
			{
				continue;
			}

			Type[] types;
			try
			{
				types = SafeGetTypes(asm);
			}
			catch (Exception ex)
			{
				log?.LogInfo("[LocKitDebug] skip assembly (GetTypes): " + asm.GetName().Name + " — " + ex.Message);
				continue;
			}

			foreach (var t in types)
			{
				if (!InterestingTypeName(t.FullName ?? ""))
				{
					continue;
				}

				var aq = t.AssemblyQualifiedName ?? t.FullName ?? "";
				if (!seenAq.Add(aq))
				{
					continue;
				}

				hits.Add((asm, t));
			}
		}

		hits.Sort((a, b) => string.Compare(a.Type.FullName ?? "", b.Type.FullName ?? "", StringComparison.Ordinal));

		var total = hits.Count;
		var dump = hits.Take(MaxTypesToDump).ToList();
		log?.LogInfo("[LocKitDebug] matched " + total + " type(s); dumping " + dump.Count + (total > dump.Count ? " (ccg=" + MaxTypesToDump + ")" : "") + ".");

		foreach (var (asm, t) in dump)
		{
			var sb = new StringBuilder();
			sb.Append("[LocKitDebug] TYPE [").Append(asm.GetName().Name).Append("] ").Append(t.FullName ?? "(null name)");

			try
			{
				var baseT = t.BaseType;
				if (baseT != null)
				{
					sb.Append(" : ").Append(baseT.FullName);
				}
			}
			catch
			{
				// Il2Cpp: BaseType can throw
			}

			log?.LogInfo(sb.ToString());

			MethodInfo[] methods;
			try
			{
				methods = t.GetMethods(BindingFlags.Static | BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
					| BindingFlags.DeclaredOnly);
			}
			catch
			{
				log?.LogInfo("[LocKitDebug]   (could not enumerate methods)");
				continue;
			}

			var count = 0;
			foreach (var m in methods.OrderBy(m => m.Name, StringComparer.Ordinal))
			{
				if (++count > MaxMethodsPerType)
				{
					log?.LogInfo("[LocKitDebug]   … " + (methods.Length - MaxMethodsPerType) + " more method(s) omitted");
					break;
				}

				string sig;
				try
				{
					var ps = m.GetParameters();
					sig = m.Name + "(" + string.Join(", ", ps.Select(p => p.ParameterType.Name)) + ")";
				}
				catch
				{
					sig = m.Name + "(?)";
				}

				log?.LogInfo("[LocKitDebug]   " + sig);
			}
		}

		if (total > dump.Count)
		{
			log?.LogInfo("[LocKitDebug] " + (total - dump.Count) + " more matched type(s) not listed (raise MaxTypesToDump in LocKitDebugProbe.cs if needed).");
		}

		log?.LogInfo("[LocKitDebug] done. If still empty or unhelpful: Il2CppDumper on GameAssembly.dll + global-metadata.dat, search for LocKit / LocInfo / log format strings.");
	}
}
