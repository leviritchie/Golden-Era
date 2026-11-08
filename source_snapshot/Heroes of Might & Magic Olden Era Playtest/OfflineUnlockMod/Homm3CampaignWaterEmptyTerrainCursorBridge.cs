using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Cursors;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace OfflineUnlockMod;

/// <summary>
/// StoryHub campaign empty-water hover: Prefix erq.bgud (empty-terrain cursor mapper) so OE
/// applies ECursor.ValidPath instead of ValidPathRed. Mountains stay red.
/// Live pin 2026-07-21: bgud is the only private void on erq whose native body emits
/// ECursor immediates 0x17..0x1a. CursorColor/etr.bhij is the interactable branch only.
/// The mapper is now named by GameSymbols (per-build scope) and verified by ValidPath/ValidPathGray/
/// InvalidTarget immediates; 25509697 (Method_Private_Void_0, native bkbj) has no ValidPathRed branch.
/// Proof boundary: source/static + deploy; user-visible ValidPath-on-water pending.
/// </summary>
internal static class Homm3CampaignWaterEmptyTerrainCursorBridge
{
	internal const string ActiveArchitecture = "campaign_water_empty_terrain_bgud_validpath";
	internal const string DiagnosticFlag = "homm3_campaign_water_empty_terrain_cursor_probe.flag";

	private const string LogPrefix = "HOMM3_CAMPAIGN_WATER_EMPTY_TERRAIN_CURSOR";
	private const BindingFlags MemberFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private const BindingFlags StaticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
	private const int MapContextMissBackoffFrames = 300;
	private const int MapContextHitRefreshFrames = 120;
	private const int NativeScanBytes = 0x200;

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedRemap;
	private static readonly Dictionary<string, int> SkipCounts = new(StringComparer.Ordinal);

	private static MethodInfo _bgudMethod;
	private static MethodInfo _cursorStackApply;
	private static MethodInfo _cursorStackSingleton;
	private static FieldInfo _hoverContextField;
	private static MethodInfo _hoverNodeGetter;

	private static int _mapContextFrame = -1;
	private static int _mapContextBackoffFrames = MapContextMissBackoffFrames;
	private static object _cachedMapData;
	private static string _cachedFileMapName;
	private static bool _cachedIsCampaignMap;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException(LogPrefix + " Harmony was not initialized.");
		_log = log;
		if (!TryResolveBgud(out var reason))
			throw new InvalidOperationException(LogPrefix + " erq.bgud unresolved: " + reason);
		if (!TryResolveCursorStackApply(out reason))
			throw new InvalidOperationException(LogPrefix + " cir ValidPath apply unresolved: " + reason);
		harmony.Patch(_bgudMethod, prefix: new HarmonyMethod(typeof(Homm3CampaignWaterEmptyTerrainCursorBridge), nameof(PrefixBgud)));
		_registered = true;
		log?.LogInfo(LogPrefix + " registered architecture=" + ActiveArchitecture
			+ " bgud=" + (_bgudMethod.DeclaringType?.FullName ?? "?") + "." + _bgudMethod.Name
			+ " apply=" + (_cursorStackApply?.DeclaringType?.FullName ?? "?") + "." + (_cursorStackApply?.Name ?? "?") + ".");
	}

	private static bool TryResolveBgud(out string reason)
	{
		reason = null;
		Type owner = null;
		foreach (var hint in GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorOwnerTypeHints)
		{
			owner = AccessTools.TypeByName(hint);
			if (owner != null)
				break;
		}
		if (owner == null)
		{
			reason = "owner_type_unresolved";
			return false;
		}

		MethodInfo[] methods;
		try { methods = owner.GetMethods(MemberFlags | BindingFlags.DeclaredOnly); }
		catch (Exception ex)
		{
			reason = "methods_unreadable " + ex.Message;
			return false;
		}

		// Il2CppInterop exposes dump-private methods as public wrappers (bgud / Method_Private_Void_*),
		// so do not filter on MethodInfo.IsPrivate. Prefer name hints, then unique ECursor IL pin.
		var candidates = new List<MethodInfo>();
		foreach (var method in methods)
		{
			if (method == null || method.IsStatic || method.ReturnType != typeof(void))
				continue;
			if (method.Name == ".ctor" || method.Name.StartsWith("set_", StringComparison.Ordinal))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 0)
				continue;
			candidates.Add(method);
		}
		if (candidates.Count == 0)
		{
			reason = "no_void0_candidates owner=" + (owner.FullName ?? owner.Name);
			return false;
		}

		// The mapper is named by GameSymbols (scoped per build) and verified by its own native body:
		// it must emit the ECursor immediates ValidPath, ValidPathGray and InvalidTarget. ValidPathRed is not
		// required: 25509697 dropped that branch (terrain result 1 now maps to ValidPathGray). A fixed scan
		// window from a small neighbour spills into the next function, so an anonymous unique-pin over every
		// void() candidate is not sound on its own; the name decides and the body verifies.
		byte[] image;
		try { image = File.ReadAllBytes(Path.Combine(BepInEx.Paths.GameRootPath, "GameAssembly.dll")); }
		catch (Exception ex)
		{
			reason = "gameassembly_unreadable " + ex.Message;
			return false;
		}

		var pinned = new List<MethodInfo>();
		var hinted = 0;
		var pointerMiss = 0;
		var bodyMiss = 0;
		var bodyReject = 0;
		var seenHints = new HashSet<string>(StringComparer.Ordinal);
		foreach (var hint in GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorMapperMethodHints)
		{
			if (string.IsNullOrWhiteSpace(hint) || !seenHints.Add(hint))
				continue;
			var method = candidates.Find(m => string.Equals(m.Name, hint, StringComparison.Ordinal));
			if (method == null)
				continue;
			hinted++;
			if (!TryGetNativeMethodPointer(owner, method, out var fn) || fn == IntPtr.Zero)
			{
				pointerMiss++;
				continue;
			}
			if (!TryReadNativeBytes(image, fn, NativeScanBytes, out var body))
			{
				bodyMiss++;
				continue;
			}
			if (!NativeBodyHasEmptyTerrainECursorImmediates(body))
			{
				bodyReject++;
				_log?.LogWarning(LogPrefix + " hinted mapper " + method.Name + " rejected: native body lacks ValidPath/ValidPathGray/InvalidTarget immediates");
				continue;
			}
			pinned.Add(method);
			break;
		}

		if (pinned.Count != 1)
		{
			reason = "hinted_pin_count=" + pinned.Count.ToString(CultureInfo.InvariantCulture)
				+ " hinted=" + hinted.ToString(CultureInfo.InvariantCulture)
				+ " candidates=" + candidates.Count.ToString(CultureInfo.InvariantCulture)
				+ " pointer_miss=" + pointerMiss.ToString(CultureInfo.InvariantCulture)
				+ " body_miss=" + bodyMiss.ToString(CultureInfo.InvariantCulture)
				+ " body_reject=" + bodyReject.ToString(CultureInfo.InvariantCulture)
				+ " hints=[" + string.Join(",", GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorMapperMethodHints) + "]"
				+ " owner=" + (owner.FullName ?? owner.Name);
			_log?.LogWarning(LogPrefix + " void0 candidates=["
				+ string.Join(",", candidates.ConvertAll(m => m.Name)) + "]");
			return false;
		}

		_bgudMethod = pinned[0];
		ResolveHoverContextAccess(owner);
		return true;
	}

	private static bool TryGetNativeMethodPointer(Type owner, MethodInfo method, out IntPtr methodPointer)
	{
		methodPointer = IntPtr.Zero;
		if (owner == null || method == null || string.IsNullOrEmpty(method.Name))
			return false;

		FieldInfo field = null;
		// Exact short form, then Il2CppInterop long form NativeMethodInfoPtr_<name>_Private_Void_0.
		foreach (var fieldName in EnumerateNativeMethodInfoPtrFieldNames(method.Name))
		{
			try { field = owner.GetField(fieldName, StaticFlags); }
			catch { field = null; }
			if (field != null)
				break;
		}
		if (field == null)
		{
			FieldInfo[] fields;
			try { fields = owner.GetFields(StaticFlags | BindingFlags.DeclaredOnly); }
			catch { return false; }
			var prefix = "NativeMethodInfoPtr_" + method.Name;
			foreach (var candidate in fields)
			{
				if (candidate == null || candidate.FieldType != typeof(IntPtr))
					continue;
				if (!candidate.Name.StartsWith(prefix, StringComparison.Ordinal))
					continue;
				field = candidate;
				break;
			}
		}
		if (field == null)
			return false;
		object raw;
		try { raw = field.GetValue(null); }
		catch { return false; }
		if (!(raw is IntPtr methodInfo) || methodInfo == IntPtr.Zero)
			return false;
		try
		{
			// Il2CppMethodInfo.methodPointer is the first pointer-sized field.
			methodPointer = Marshal.ReadIntPtr(methodInfo);
			return methodPointer != IntPtr.Zero;
		}
		catch
		{
			return false;
		}
	}

	private static IEnumerable<string> EnumerateNativeMethodInfoPtrFieldNames(string methodName)
	{
		yield return "NativeMethodInfoPtr_" + methodName;
		yield return "NativeMethodInfoPtr_" + methodName + "_Private_Void_0";
		yield return "NativeMethodInfoPtr_" + methodName + "_Public_Void_0";
		yield return "NativeMethodInfoPtr_" + methodName + "_Private_Void_PDM_0";
	}

	private static bool TryReadNativeBytes(byte[] image, IntPtr methodPointer, int size, out byte[] body)
	{
		body = null;
		var modules = ProcessModules();
		foreach (var module in modules)
		{
			if (methodPointer.ToInt64() < module.Base.ToInt64()
			    || methodPointer.ToInt64() >= module.Base.ToInt64() + module.Size)
				continue;
			var rva = unchecked((uint)(methodPointer.ToInt64() - module.Base.ToInt64()));
			if (!TryRvaToFileOffset(image, rva, out var fileOffset))
				return false;
			if (fileOffset < 0 || fileOffset + size > image.Length)
				return false;
			body = new byte[size];
			Buffer.BlockCopy(image, fileOffset, body, 0, size);
			return true;
		}
		return false;
	}

	private static bool TryRvaToFileOffset(byte[] image, uint rva, out int fileOffset)
	{
		fileOffset = 0;
		if (image == null || image.Length < 0x40 || image[0] != (byte)'M' || image[1] != (byte)'Z')
			return false;
		var eLfanew = BitConverter.ToInt32(image, 0x3C);
		if (eLfanew <= 0 || eLfanew + 24 >= image.Length)
			return false;
		if (image[eLfanew] != (byte)'P' || image[eLfanew + 1] != (byte)'E')
			return false;
		var numSections = BitConverter.ToUInt16(image, eLfanew + 6);
		var sizeOpt = BitConverter.ToUInt16(image, eLfanew + 20);
		var secOff = eLfanew + 24 + sizeOpt;
		for (var i = 0; i < numSections; i++)
		{
			var off = secOff + i * 40;
			if (off + 40 > image.Length)
				return false;
			var vsize = BitConverter.ToUInt32(image, off + 8);
			var vaddr = BitConverter.ToUInt32(image, off + 12);
			var rawsize = BitConverter.ToUInt32(image, off + 16);
			var rawptr = BitConverter.ToUInt32(image, off + 20);
			var span = Math.Max(vsize, rawsize);
			if (rva < vaddr || rva >= vaddr + span)
				continue;
			fileOffset = (int)(rawptr + (rva - vaddr));
			return fileOffset >= 0;
		}
		return false;
	}

	private static List<(IntPtr Base, long Size)> ProcessModules()
	{
		var list = new List<(IntPtr, long)>();
		try
		{
			foreach (System.Diagnostics.ProcessModule module in System.Diagnostics.Process.GetCurrentProcess().Modules)
			{
				if (module == null || string.IsNullOrEmpty(module.ModuleName))
					continue;
				if (!string.Equals(module.ModuleName, "GameAssembly.dll", StringComparison.OrdinalIgnoreCase))
					continue;
				list.Add((module.BaseAddress, module.ModuleMemorySize));
			}
		}
		catch { }
		return list;
	}

	private static bool NativeBodyHasEmptyTerrainECursorImmediates(byte[] body)
	{
		if (body == null || body.Length < 8)
			return false;
		var found = new HashSet<byte>();
		for (var i = 0; i + 5 <= body.Length; i++)
		{
			// mov r32, imm32 with ECursor ordinals ValidPath..InvalidTarget
			if ((body[i] == 0xB8 || body[i] == 0xB9 || body[i] == 0xBA || body[i] == 0xBB)
			    && body[i + 1] >= 0x17 && body[i + 1] <= 0x1A
			    && body[i + 2] == 0 && body[i + 3] == 0 && body[i + 4] == 0)
			{
				found.Add(body[i + 1]);
			}
		}
		// ValidPath, ValidPathGray, InvalidTarget. ValidPathRed (0x18) is Golden Era only.
		return found.Contains(0x17) && found.Contains(0x19) && found.Contains(0x1A);
	}

	private static void ResolveHoverContextAccess(Type owner)
	{
		_hoverContextField = null;
		_fapGetter = null;
		foreach (var name in GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorHoverContextMembers)
		{
			FieldInfo field;
			try { field = owner.GetField(name, MemberFlags); }
			catch { field = null; }
			if (field != null)
			{
				_hoverContextField = field;
				return;
			}
			MethodInfo getter;
			try { getter = owner.GetMethod(name, MemberFlags, null, Type.EmptyTypes, null); }
			catch { getter = null; }
			if (getter != null)
			{
				_fapGetter = getter;
				return;
			}
		}
	}

	private static MethodInfo _fapGetter;

	private static bool TryResolveCursorStackApply(out string reason)
	{
		reason = null;
		Type type = null;
		foreach (var hint in GameSymbols.HomecomingWaterPresentation.CursorStackTypeHints)
		{
			type = AccessTools.TypeByName(hint);
			if (type != null)
				break;
		}
		if (type == null)
		{
			reason = "cursor_stack_type_unresolved";
			return false;
		}

		_cursorStackSingleton = GameMember.FindFirstMethodByNames(
			type,
			Type.EmptyTypes,
			GameSymbols.HomecomingWaterPresentation.CursorStackSingleton);
		if (_cursorStackSingleton == null || !_cursorStackSingleton.IsStatic)
		{
			reason = "cursor_stack_singleton_unresolved";
			return false;
		}

		MethodInfo[] methods;
		try { methods = type.GetMethods(MemberFlags | BindingFlags.DeclaredOnly); }
		catch (Exception ex)
		{
			reason = "cursor_stack_methods_unreadable " + ex.Message;
			return false;
		}

		MethodInfo best = null;
		var bestRank = int.MaxValue;
		foreach (var method in methods)
		{
			if (method == null || method.ReturnType != typeof(bool))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length < 1 || ps.Length > 2)
				continue;
			if (ps[0].ParameterType != typeof(ECursor))
				continue;
			if (ps.Length == 2 && ps[1].ParameterType != typeof(int))
				continue;
			var rank = Array.IndexOf(GameSymbols.HomecomingWaterPresentation.CursorStackApplyMethodHints, method.Name);
			if (rank < 0)
				rank = 1000;
			if (rank < bestRank)
			{
				bestRank = rank;
				best = method;
			}
		}
		if (best == null)
		{
			reason = "cursor_stack_apply_unresolved";
			return false;
		}
		_cursorStackApply = best;
		return true;
	}

	private static bool PrefixBgud(object __instance)
	{
		if (__instance == null)
			return true;
		if (!TryReadHoverNode(__instance, out var node))
			return true;
		if (!ShouldForceValidPathForNode(node))
			return true;
		if (!TryApplyValidPath())
		{
			LogSkip("apply_validpath_failed");
			return true;
		}
		LogRemap(node);
		return false;
	}

	private static bool TryReadHoverNode(object erqInstance, out int node)
	{
		node = -1;
		object fap = null;
		if (_hoverContextField != null)
		{
			try { fap = _hoverContextField.GetValue(erqInstance); }
			catch { fap = null; }
		}
		else if (_fapGetter != null)
		{
			try { fap = _fapGetter.Invoke(erqInstance, null); }
			catch { fap = null; }
		}
		if (fap == null)
			return false;

		if (_hoverNodeGetter == null)
		{
			foreach (var name in GameSymbols.HomecomingWaterPresentation.HoverContextNodeMembers)
			{
				MethodInfo method;
				try { method = fap.GetType().GetMethod(name, MemberFlags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method != null && method.ReturnType == typeof(int))
				{
					_hoverNodeGetter = method;
					break;
				}
			}
		}
		if (_hoverNodeGetter != null)
		{
			try
			{
				node = Convert.ToInt32(_hoverNodeGetter.Invoke(fap, null), CultureInfo.InvariantCulture);
				return node >= 0;
			}
			catch { }
		}

		foreach (var name in GameSymbols.HomecomingWaterPresentation.HoverContextNodeMembers)
		{
			var raw = TryReadMember(fap, name);
			if (raw == null)
				continue;
			try
			{
				node = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
				if (node >= 0)
					return true;
			}
			catch { }
		}
		return false;
	}

	private static bool ShouldForceValidPathForNode(int node)
	{
		if (node < 0)
			return false;
		if (!TryGetCachedCampaignMapContext(out var mapData))
			return false;
		return TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers, node, out var tile)
		       && TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataWaterMapMembers, node, out var water)
		       && TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataLevelsMapMembers, node, out var level)
		       && GameSymbols.HomecomingBoatTravel.IsOceanCell(tile, water, level);
	}

	private static bool TryApplyValidPath()
	{
		if (_cursorStackApply == null || _cursorStackSingleton == null)
			return false;
		object stack;
		try { stack = _cursorStackSingleton.Invoke(null, Array.Empty<object>()); }
		catch { return false; }
		if (stack == null)
			return false;
		try
		{
			var ps = _cursorStackApply.GetParameters();
			object result;
			if (ps.Length == 1)
				result = _cursorStackApply.Invoke(stack, new object[] { ECursor.ValidPath });
			else
				result = _cursorStackApply.Invoke(stack, new object[] { ECursor.ValidPath, 0 });
			return result is bool ok ? ok : true;
		}
		catch (Exception ex)
		{
			LogSkip("apply_exception " + ex.GetType().Name);
			return false;
		}
	}

	private static bool TryGetCachedCampaignMapContext(out object mapData)
	{
		mapData = _cachedMapData;
		if (_mapContextFrame >= 0
		    && UnityEngine.Time.frameCount - _mapContextFrame < _mapContextBackoffFrames)
		{
			return _cachedIsCampaignMap;
		}

		_cachedMapData = null;
		_cachedFileMapName = null;
		_cachedIsCampaignMap = false;
		_mapContextFrame = UnityEngine.Time.frameCount;
		if (!Homm3HomecomingWaterPresentationOverlay.TryReadCurrentMapContext(out mapData, out var fileMapName, out var reason))
		{
			_mapContextBackoffFrames = MapContextMissBackoffFrames;
			LogSkip("map_context " + (reason ?? "unresolved"));
			return false;
		}

		_cachedMapData = mapData;
		_cachedFileMapName = fileMapName;
		_cachedIsCampaignMap = RoeCastleCampaignMapRegistry.IsStoryHubPlayableMap(fileMapName);
		_mapContextBackoffFrames = _cachedIsCampaignMap
			? MapContextHitRefreshFrames
			: MapContextMissBackoffFrames;
		if (!_cachedIsCampaignMap)
			LogSkip("sid_not_campaign " + (fileMapName ?? "<null>"));
		return _cachedIsCampaignMap;
	}

	private static bool TryReadMapByte(object mapData, string[] members, int node, out int value)
	{
		value = 0;
		if (node < 0 || mapData == null)
			return false;
		var raw = TryReadFirstMember(mapData, members);
		if (raw == null)
			return false;
		if (raw is byte[] bytes)
			return node < bytes.Length && (value = bytes[node]) >= 0;
		if (raw is Il2CppStructArray<byte> il2CppBytes)
			return node < il2CppBytes.Length && (value = il2CppBytes[node]) >= 0;
		if (raw is sbyte[] signedBytes)
		{
			if (node >= signedBytes.Length)
				return false;
			value = signedBytes[node];
			return true;
		}
		if (raw is Il2CppStructArray<sbyte> il2CppSignedBytes)
		{
			if (node >= il2CppSignedBytes.Length)
				return false;
			value = il2CppSignedBytes[node];
			return true;
		}
		return false;
	}

	private static object TryReadFirstMember(object value, string[] names)
	{
		if (value == null || names == null)
			return null;
		foreach (var name in names)
		{
			var member = TryReadMember(value, name);
			if (member != null)
				return member;
		}
		return null;
	}

	private static object TryReadMember(object value, string name)
	{
		if (value == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = value.GetType();
		PropertyInfo property;
		try { property = type.GetProperty(name, MemberFlags); }
		catch { property = null; }
		if (property != null)
		{
			try { return property.GetValue(value); }
			catch { }
		}
		FieldInfo field;
		try { field = type.GetField(name, MemberFlags); }
		catch { field = null; }
		if (field != null)
		{
			try { return field.GetValue(value); }
			catch { }
		}
		return null;
	}

	private static void LogRemap(int node)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag) && _loggedRemap >= 16)
			return;
		_loggedRemap++;
		_log?.LogInfo(LogPrefix + " remap_validpath node=" + node.ToString(CultureInfo.InvariantCulture)
			+ " sid=" + (_cachedFileMapName ?? "<unknown>") + ".");
	}

	private static void LogSkip(string reason)
	{
		if (string.IsNullOrWhiteSpace(reason))
			reason = "unspecified";
		SkipCounts.TryGetValue(reason, out var count);
		count++;
		SkipCounts[reason] = count;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag) && count > 4)
			return;
		_log?.LogInfo(LogPrefix + " skip " + reason + " count=" + count.ToString(CultureInfo.InvariantCulture));
	}
}
