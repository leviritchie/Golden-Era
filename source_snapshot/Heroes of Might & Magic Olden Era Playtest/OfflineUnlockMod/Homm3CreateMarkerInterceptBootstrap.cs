using System;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod
{
	/// <summary>
	/// Earliest practical CreateMarker hook install for olden_cs_recovery edb::.cctor call-trace.
	/// Invoked as the first action in Plugin.Load so OfflineUnlockMod's own startup cannot race the hook.
	/// Soft-depends on AAA_CreateMarkerInterceptEarly when that plugin is deployed (loads first).
	/// Opt-in only: requires <c>homm3_create_marker_intercept.flag</c>. Without the flag this path is a
	/// no-op so release/perf runs do not sync-append every Unity Profiler CreateMarker to disk.
	/// </summary>
	internal static class Homm3CreateMarkerInterceptBootstrap
	{
		internal const string EarlyPluginGuid = "olden.csrecovery.createmarker.intercept.early";
		internal const string DiagnosticFlag = "homm3_create_marker_intercept.flag";
		private const string HarmonyId = "levir.heroesoe.offlineunlock.createmarker.intercept";
		private static Harmony _harmony;
		private static bool _installed;

		internal static void TryInstallAtPluginLoad(ManualLogSource log)
		{
			if (_installed)
				return;
			if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			{
				log?.LogInfo(
					"CreateMarkerInterceptBootstrap: skipped (opt-in flag "
					+ DiagnosticFlag
					+ " not present).");
				_installed = true;
				return;
			}
			try
			{
				// Prefer already-loaded early plugin probe type (same process, SoftDependency order).
				if (TryInvokeEarlyProbeInstall(log))
				{
					_installed = true;
					return;
				}

				var persist = Path.Combine(
					Paths.PluginPath,
					"OfflineUnlockMod",
					"live_probe_bridge",
					"create_marker_intercept");
				Directory.CreateDirectory(persist);

				var util = FindType("Unity.Profiling.LowLevel.Unsafe.ProfilerUnsafeUtility");
				if (util == null)
				{
					log?.LogWarning("CreateMarkerInterceptBootstrap: ProfilerUnsafeUtility not found");
					return;
				}

				MethodInfo stringOverload = null;
				foreach (var mi in util.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
				{
					if (mi.Name != "CreateMarker")
						continue;
					var ps = mi.GetParameters();
					if (ps.Length == 4 && ps[0].ParameterType == typeof(string))
					{
						stringOverload = mi;
						break;
					}
				}
				if (stringOverload == null)
				{
					log?.LogWarning("CreateMarkerInterceptBootstrap: CreateMarker(string,...) missing");
					return;
				}

				_harmony = new Harmony(HarmonyId);
				var prefix = new HarmonyMethod(typeof(Homm3CreateMarkerInterceptBootstrap).GetMethod(
					nameof(PrefixString), BindingFlags.Static | BindingFlags.NonPublic));
				var postfix = new HarmonyMethod(typeof(Homm3CreateMarkerInterceptBootstrap).GetMethod(
					nameof(PostfixString), BindingFlags.Static | BindingFlags.NonPublic));
				_harmony.Patch(stringOverload, prefix: prefix, postfix: postfix);
				_installed = true;
				File.WriteAllText(
					Path.Combine(persist, "offlineunlock_bootstrap.json"),
					"{\"ok\":true,\"installed\":true,\"source\":\"OfflineUnlockMod.Plugin.Load\",\"target\":\""
					+ stringOverload.DeclaringType.FullName + "::CreateMarker(string,...)\"}\n");
				log?.LogInfo("CreateMarkerInterceptBootstrap: Harmony hook installed at Plugin.Load start");
			}
			catch (Exception ex)
			{
				log?.LogWarning("CreateMarkerInterceptBootstrap failed: " + ex.GetBaseException().Message);
			}
		}

		private static bool TryInvokeEarlyProbeInstall(ManualLogSource log)
		{
			foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
			{
				Type type;
				try
				{
					type = asm.GetType("OldenCsRecovery.Probes.CreateMarkerCallInterceptProbe", false);
				}
				catch
				{
					continue;
				}
				if (type == null)
					continue;
				var method = type.GetMethod("InstallEarly", BindingFlags.Public | BindingFlags.Static);
				if (method == null)
					continue;
				var persist = Path.Combine(
					Paths.PluginPath,
					"OfflineUnlockMod",
					"live_probe_bridge",
					"create_marker_intercept");
				Directory.CreateDirectory(persist);
				var result = method.Invoke(null, new object[] { persist, "offlineunlock_softdependency_already_loaded" });
				log?.LogInfo("CreateMarkerInterceptBootstrap: reused early probe InstallEarly => " + result);
				return true;
			}
			return false;
		}

		private static void PrefixString(string name, ushort categoryId, int metadataCount)
		{
			AppendCall(name, categoryId, metadataCount, IntPtr.Zero);
		}

		private static void PostfixString(string name, ref IntPtr __result)
		{
			AppendCall(name, -1, -1, __result, isReturnUpdate: true);
		}

		private static void AppendCall(string name, int categoryId, int metadataCount, IntPtr handle, bool isReturnUpdate = false)
		{
			try
			{
				var persist = Path.Combine(
					Paths.PluginPath,
					"OfflineUnlockMod",
					"live_probe_bridge",
					"create_marker_intercept");
				Directory.CreateDirectory(persist);
				var path = Path.Combine(persist, "calls.jsonl");
				if (isReturnUpdate)
				{
					// Best-effort: append a return-update line; harvest merges by name order.
					File.AppendAllText(
						path,
						"{\"seq\":-1,\"name\":\"" + Esc(name ?? "") + "\",\"categoryId\":0,\"flags\":0,\"metadataCount\":0,\"returnHandle\":\"0x"
						+ handle.ToString("X") + "\",\"overload\":\"CreateMarker(string)\",\"ticks\":"
						+ DateTime.UtcNow.Ticks + ",\"returnUpdate\":true}\n");
					return;
				}
				File.AppendAllText(
					path,
					"{\"seq\":" + DateTime.UtcNow.Ticks
					+ ",\"name\":\"" + Esc(name ?? "") + "\",\"categoryId\":" + categoryId
					+ ",\"flags\":0,\"metadataCount\":" + metadataCount
					+ ",\"returnHandle\":\"0x0\",\"overload\":\"CreateMarker(string)\",\"ticks\":"
					+ DateTime.UtcNow.Ticks + ",\"source\":\"OfflineUnlockMod.bootstrap\"}\n");
			}
			catch
			{
			}
		}

		private static Type FindType(string fullName)
		{
			foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
			{
				try
				{
					var type = assembly.GetType(fullName, false);
					if (type != null)
						return type;
				}
				catch
				{
				}
			}
			return null;
		}

		private static string Esc(string value)
		{
			if (value == null)
				return "";
			return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
		}
	}
}
