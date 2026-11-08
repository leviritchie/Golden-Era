using System;
using System.Reflection;
using HarmonyLib;

namespace BepInEx
{
	internal static class Paths
	{
		internal static string BepInExRootPath { get; set; }
		internal static string PluginPath { get; set; }
		internal static string GameRootPath { get; set; }
	}
}

namespace BepInEx.Logging
{
	internal sealed class ManualLogSource
	{
		internal void LogInfo(object message) { }
		internal void LogWarning(object message) { }
		internal void LogError(object message) { }
	}
}

namespace HarmonyLib
{
	internal static class Priority
	{
		internal const int First = 800;
	}

	internal sealed class HarmonyMethod
	{
		internal int priority;

		internal HarmonyMethod(Type declaringType, string methodName) { }
	}

	internal sealed class Harmony
	{
		internal void Patch(MethodBase original, HarmonyMethod prefix = null, HarmonyMethod postfix = null) { }
	}

	internal static class AccessTools
	{
		internal static MethodInfo[] GetDeclaredMethods(Type type)
			=> type.GetMethods(BindingFlags.DeclaredOnly | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance);
	}
}

namespace Il2CppInterop.Runtime.InteropTypes.Arrays
{
	internal sealed class Il2CppStructArray<T>
	{
		private readonly T[] _items;

		internal Il2CppStructArray(T[] items) => _items = items ?? Array.Empty<T>();
		internal int Length => _items.Length;
		internal T[] ToArray() => (T[])_items.Clone();
	}
}

namespace Il2CppSystem.Collections.Generic
{
	internal sealed class Dictionary<TKey, TValue> : System.Collections.Generic.Dictionary<TKey, TValue> { }
}

namespace OfflineUnlockMod
{
	internal sealed class LauncherConfig
	{
		internal bool ModBugReporting = true;
		internal string ModBugReportingEndpoint = "";
		internal bool ModBugReportingIncludeScreenshot = false;
	}

	internal static class Plugin
	{
		internal const string PluginVersion = "fixture-version";
	}

	internal static class GameSymbols
	{
		internal readonly struct MethodSymbol { }

		internal static class ModBugReporting
		{
			internal static readonly string[] SendReportOwnerTypeHints = { "fixture" };
			internal const string SendReportMethodName = "SendReport";
			internal const int SendReportParameterCount = 9;
			internal static readonly string[] ScreenTypeHints = { "fixture" };
			internal const string ScreenShowMethodName = "Show";
			internal const int ScreenShowParameterCount = 1;
			internal static readonly MethodSymbol ScreenStaticAutoSend = new();
		}
	}

	internal static class GameMember
	{
		internal static Type FindTypeFromHints(string owner, string[] hints) => typeof(RedirectPackageTestSymbols.FakeAnalytics);

		internal static MethodInfo[] FindEveryMethodByNames(Type type, GameSymbols.MethodSymbol symbol, Func<MethodInfo, bool> shape, out string error)
		{
			error = "not used by package fixtures";
			return Array.Empty<MethodInfo>();
		}
	}

	internal static class ModBugReportSubmission
	{
		internal static bool TryRegister(Harmony harmony, BepInEx.Logging.ManualLogSource log, LauncherConfig cfg, out string error)
		{
			error = null;
			return true;
		}
	}

	internal static class RedirectPackageTestSymbols
	{
		internal static class FakeAnalytics
		{
			internal static void SendReport(object a, object b, object c, object d, object e, object f, object g, object h, object i) { }
		}
	}
}
