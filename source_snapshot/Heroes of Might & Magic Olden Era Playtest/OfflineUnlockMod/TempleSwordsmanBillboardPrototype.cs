using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using BepInEx;
using HarmonyLib;
using Newtonsoft.Json.Linq;
using Hex.Configs;
using Hex.Session;
using Hex.Session.Battle;
using UnityEngine;
using UnityEngine.Networking;

namespace OfflineUnlockMod;

internal static class TempleSwordsmanBillboardPrototype
{
	private static readonly Dictionary<int, PrototypeState> ActiveStates = new();
	private static readonly HashSet<string> LoggedClipNames = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, PrototypeAssetBundle> AssetsByExportFolder = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, GameObject> MapPrefabsByUnitSid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, GameObject> BattlePrefabsByPath = new(StringComparer.Ordinal);
	private static Harmony _runtimeHarmony;
	private static bool _battlePatchesInstalled;
	private static bool _battlePatchWarningLogged;
	private static bool _battleDrawerProbeLogged;
	private static bool _battleDrawerRuntimeResolutionDiagLogged;
	private static bool _battleDrawerFodVirtualSlotDiagLogged;
	private static bool _battlePatchHarmonyFailLogged;
	private static bool _runtimePrefabRouteInstalled;
	private static bool _runtimePrefabRouteWarningLogged;
	private static bool _battleContextEntered;
	private static MethodInfo _resManagerGetGameObjectMethod;
	[ThreadStatic] private static bool _resManagerBypass;
	private static PropertyInfo _bhActiveBattleMeProperty;

	internal static void ResetBattleContext()
	{
		_battleContextEntered = false;
	}

	internal static void NotifyBattleUnitInit()
	{
		_battleContextEntered = true;
	}

	internal static bool IsBattleViewActive()
	{
		try
		{
			var bhActiveBattleType =
				CustomUnitViewRouting.GameAssembly.GetType("Hex.Session.Battle.BhActiveBattle", throwOnError: false);
			if (bhActiveBattleType == null)
			{
				return false;
			}

			_bhActiveBattleMeProperty ??= bhActiveBattleType.GetProperty(
				"me",
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			var me = _bhActiveBattleMeProperty?.GetValue(null, null);
			return me != null;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// Resolves battle <see cref="UnitDrawer"/> CLR type using the same metadata + assembly scan as billboard patches.
	/// Used to fingerprint <c>Unit.Listen(IUnitListenner)</c> when interface / method names are obfuscated.
	/// </summary>
	internal static Type ResolveBattleUnitDrawerClrTypeStatic()
	{
		return CustomUnitViewRouting.GameAssembly.GetType("Hex.Session.Battle.UnitDrawer", throwOnError: false)
			?? FindGameType("Hex.Session.Battle.UnitDrawer")
			?? FindBattleUnitDrawerTypeByInitAndTick();
	}

	internal static void EnsureBattlePatchesInstalled(Unit battleUnit = null, Type battleUnitDrawerClrType = null)
	{
		if (_battlePatchesInstalled)
		{
			return;
		}

		Type unitDrawerType = null;
		if (battleUnitDrawerClrType != null && typeof(Component).IsAssignableFrom(battleUnitDrawerClrType))
		{
			unitDrawerType = battleUnitDrawerClrType;
			Plugin.LogSource?.LogInfo($"Battle billboard: UnitDrawer CLR type from Listen(...): '{unitDrawerType.FullName}'.");
		}
		else if (battleUnit != null && TryResolveUnitDrawerRuntimeType(battleUnit, out var runtimeDrawerType))
		{
			unitDrawerType = runtimeDrawerType;
			Plugin.LogSource?.LogInfo($"Battle billboard: resolved UnitDrawer CLR type from battle scene: '{unitDrawerType.FullName}'.");
		}

		unitDrawerType ??=
			CustomUnitViewRouting.GameAssembly.GetType("Hex.Session.Battle.UnitDrawer", throwOnError: false)
			?? FindGameType("Hex.Session.Battle.UnitDrawer")
			?? FindBattleUnitDrawerTypeByInitAndTick();
		if (unitDrawerType == null)
		{
			if (battleUnit != null)
			{
				LogBattleDrawerRuntimeResolutionDiagnostics(battleUnit);
			}

			if (battleUnit != null && !_battlePatchWarningLogged)
			{
				_battlePatchWarningLogged = true;
				Plugin.LogSource?.LogWarning(
					"Custom billboard runtime could not resolve battle UnitDrawer (listener/unitsDrawers.Get + assembly scan failed).");
			}

			return;
		}

		var initMethod = ResolveBattleDrawerInit(unitDrawerType);
		// Prefer Process(float); fall back to ProcessVisualFrame(float) on obfuscated builds.
		var tickMethod =
			ResolveBattleDrawerProcessFloat(unitDrawerType)
			?? ResolveBattleDrawerProcessVisualFrame(unitDrawerType);
		if (initMethod == null || tickMethod == null)
		{
			LogFieldObjectDrawerVirtualSlotDiagnostics();
			if (!_battlePatchWarningLogged)
			{
				_battlePatchWarningLogged = true;
				LogUnitDrawerMethodDiagnostics(unitDrawerType, initMethod, tickMethod);
				Plugin.LogSource?.LogWarning(
					$"Custom billboard runtime could not resolve battle Init/tick on '{unitDrawerType.FullName}' (Init={(initMethod != null)}, Tick={(tickMethod != null)}).");
			}

			return;
		}

		try
		{
			_runtimeHarmony ??= new Harmony(Plugin.PluginGuid + ".runtime-billboards");
			_runtimeHarmony.Patch(initMethod, postfix: new HarmonyMethod(typeof(TempleSwordsmanBillboardPrototype), nameof(UnitDrawerInitPostfix)));
			_runtimeHarmony.Patch(tickMethod, postfix: new HarmonyMethod(typeof(TempleSwordsmanBillboardPrototype), nameof(UnitDrawerProcessPostfix)));
			_battlePatchesInstalled = true;
			Plugin.LogSource?.LogInfo(
				$"Installed runtime billboard patches: type={unitDrawerType.FullName}, Init → {initMethod.DeclaringType?.FullName}.{initMethod.Name}, Tick → {tickMethod.DeclaringType?.FullName}.{tickMethod.Name}");
		}
		catch (Exception ex)
		{
			if (!_battlePatchHarmonyFailLogged)
			{
				_battlePatchHarmonyFailLogged = true;
				Plugin.LogSource?.LogError($"Custom billboard Harmony patch failed on {unitDrawerType.FullName}: {ex}");
			}
		}
	}

	/// <summary>
	/// One-shot breadcrumb trail when runtime + metadata fail to yield a drawer <see cref="Type"/>.
	/// </summary>
	private static void LogBattleDrawerRuntimeResolutionDiagnostics(Unit unit)
	{
		if (_battleDrawerRuntimeResolutionDiagLogged || unit == null)
		{
			return;
		}

		_battleDrawerRuntimeResolutionDiagLogged = true;

		var parts = new List<string>();
		try
		{
			var ga = CustomUnitViewRouting.GameAssembly;
			parts.Add($"assembly={ga?.GetName()?.Name ?? "null"}");

			var iListener = ga.GetType("Hex.Session.Battle.IUnitListenner", throwOnError: false);
			parts.Add($"hex.IUnitListenner={(iListener != null ? "resolved" : "missing")}");

			const BindingFlags propFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
			var listenerCandidates = 0;
			string listenerDetail = "noProp";
			foreach (var prop in typeof(Unit).GetProperties(propFlags))
			{
				var matchByName = string.Equals(prop.Name, "listener", StringComparison.Ordinal);
				var matchByIface = iListener != null && iListener.IsAssignableFrom(prop.PropertyType);
				if (!matchByName && !matchByIface)
				{
					continue;
				}

				listenerCandidates++;
				string sub;
				try
				{
					var val = prop.GetValue(unit);
					sub = val != null ? $"{prop.Name}=obj:{val.GetType().FullName}" : $"{prop.Name}=null";
				}
				catch (Exception ex)
				{
					sub = $"{prop.Name}=exc:{ex.Message}";
				}

				listenerDetail = sub;
				if (listenerDetail.Contains("obj:", StringComparison.Ordinal))
				{
					break;
				}
			}

			parts.Add($"listenerCandidateCount={listenerCandidates}");
			parts.Add(listenerDetail);

			var heuristicDrawerLikeProps = 0;
			var heuristicDrawerLikeFields = 0;
			foreach (var prop in typeof(Unit).GetProperties(propFlags))
			{
				try
				{
					var val = prop.GetValue(unit);
					if (val != null && MightBeBattleUnitDrawerInstance(val))
					{
						heuristicDrawerLikeProps++;
					}
				}
				catch
				{
					// ignored
				}
			}

			foreach (var field in typeof(Unit).GetFields(propFlags))
			{
				try
				{
					var val = field.GetValue(unit);
					if (val != null && MightBeBattleUnitDrawerInstance(val))
					{
						heuristicDrawerLikeFields++;
					}
				}
				catch
				{
					// ignored
				}
			}

			parts.Add($"heuristicDrawerLikeProps={heuristicDrawerLikeProps}");
			parts.Add($"heuristicDrawerLikeFields={heuristicDrawerLikeFields}");

			var bhType = ResolveBhActiveBattleClrType();
			parts.Add($"BhActiveBattle={(bhType != null ? bhType.FullName : "missing")}");

			object me = null;
			string meExc = null;
			if (bhType != null)
			{
				try
				{
					var meProp = bhType.GetProperty("me", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
					me = meProp?.GetValue(null);
				}
				catch (Exception ex)
				{
					meExc = ex.Message;
				}
			}

			parts.Add(meExc != null ? $"BhActiveBattle.me.exc={meExc}" : $"BhActiveBattle.me={(me != null ? $"ok:{me.GetType().FullName}" : "null")}");

			object drawers = null;
			string drawersExc = null;
			if (me != null)
			{
				try
				{
					var drawersProp = me.GetType().GetProperty(
						"unitsDrawers",
						BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
					drawers = drawersProp?.GetValue(me);
				}
				catch (Exception ex)
				{
					drawersExc = ex.Message;
				}
			}

			parts.Add(drawersExc != null ? $"unitsDrawers.exc={drawersExc}" : $"unitsDrawers={(drawers != null ? drawers.GetType().FullName : "null")}");

			if (drawers != null)
			{
				var matchedGets = 0;
				string getOutcome = "noInvoke";
				foreach (var method in drawers.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
				{
					if (!string.Equals(method.Name, "Get", StringComparison.Ordinal))
					{
						continue;
					}

					var ps = method.GetParameters();
					if (ps.Length != 1 || !typeof(Unit).IsAssignableFrom(ps[0].ParameterType))
					{
						continue;
					}

					matchedGets++;
					try
					{
						var drawerObj = method.Invoke(drawers, new object[] { unit });
						getOutcome = drawerObj != null ? $"returned:{drawerObj.GetType().FullName}" : "returned:null";
						break;
					}
					catch (Exception ex)
					{
						getOutcome = $"exc:{ex.Message}";
					}
				}

				parts.Add($"unitsDrawers.Get(Unit)OverloadMatches={matchedGets}");
				parts.Add($"unitsDrawers.Get(Unit)={getOutcome}");
			}
			else if (me != null)
			{
				var scannedContainers = 0;
				string scanOutcome = "none";
				foreach (var mp in me.GetType().GetProperties(propFlags))
				{
					object container;
					try
					{
						container = mp.GetValue(me);
					}
					catch
					{
						continue;
					}

					if (container == null)
					{
						continue;
					}

					scannedContainers++;
					foreach (var method in container.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
					{
						if (!string.Equals(method.Name, "Get", StringComparison.Ordinal))
						{
							continue;
						}

						var ps = method.GetParameters();
						if (ps.Length != 1 || !typeof(Unit).IsAssignableFrom(ps[0].ParameterType))
						{
							continue;
						}

						try
						{
							var drawerObj = method.Invoke(container, new object[] { unit });
							scanOutcome = drawerObj != null ? $"returned:{drawerObj.GetType().FullName}" : "returned:null";
						}
						catch (Exception ex)
						{
							scanOutcome = $"exc:{ex.Message}";
						}

						break;
					}
				}

				parts.Add($"mePropsScannedForGetUnit={scannedContainers}");
				parts.Add($"mePropScanGet(Unit)={scanOutcome}");
			}
		}
		catch (Exception ex)
		{
			parts.Add($"diagTopLevel.exc={ex.Message}");
		}

		Plugin.LogSource?.LogWarning($"Battle drawer runtime resolution (one-shot diagnostic): {string.Join(" | ", parts)}");
	}

	private static void LogFieldObjectDrawerVirtualSlotDiagnostics()
	{
		if (_battleDrawerFodVirtualSlotDiagLogged)
		{
			return;
		}

		_battleDrawerFodVirtualSlotDiagLogged = true;

		Type fod = null;
		MethodInfo slot = null;
		string fodExc = null;
		string slotNote = null;
		try
		{
			fod = ResolveFieldObjectDrawerType();
			if (fod == null)
			{
				slotNote = "ResolveFieldObjectDrawerType returned null (metadata name stripped?)";
			}
			else
			{
				slot = ResolveFieldObjectDrawerProcessVirtualSlot();
				if (slot == null)
				{
					slotNote = "no DeclaredOnly method Process(float) on FieldObjectDrawer";
				}
			}
		}
		catch (Exception ex)
		{
			fodExc = ex.Message;
		}

		Plugin.LogSource?.LogWarning(
			$"Battle drawer FieldObject.Process slot (one-shot): FieldObjectDrawer={(fod?.FullName ?? "null")}; virtualProcessSlot={(slot != null ? $"{slot.DeclaringType?.FullName}.{slot.Name}" : "null")}; {(fodExc != null ? $"exc={fodExc}" : slotNote ?? string.Empty)}");
	}

	/// <summary>
	/// Playtest builds obfuscate <c>UnitDrawer</c> type names in metadata; the Il2Cpp instance is still reachable:
	/// <c>Unit.listener</c> is set from <see cref="UnitsDrawers.Resp"/> (see game dump), and
	/// <c>BhActiveBattle.me.unitsDrawers.Get(unit)</c> returns the same drawer.
	/// </summary>
	private static Type ResolveBhActiveBattleClrType()
	{
		var ga = CustomUnitViewRouting.GameAssembly;
		return ga.GetType("Hex.Session.Battle.BhActiveBattle", throwOnError: false)
			?? FindGameType("Hex.Session.Battle.BhActiveBattle");
	}

	private static bool MightBeBattleUnitDrawerInstance(object obj)
	{
		if (obj == null)
		{
			return false;
		}

		var t = obj.GetType();
		if (!typeof(Component).IsAssignableFrom(t))
		{
			return false;
		}

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		foreach (var method in t.GetMethods(flags))
		{
			if (!string.Equals(method.Name, "Init", StringComparison.Ordinal))
			{
				continue;
			}

			var ps = method.GetParameters();
			if (ps.Length == 7 && typeof(UnitViewConfig).IsAssignableFrom(ps[0].ParameterType))
			{
				return true;
			}
		}

		return false;
	}

	private static bool TryResolveUnitDrawerRuntimeType(Unit unit, out Type unitDrawerType)
	{
		unitDrawerType = null;
		if (unit == null)
		{
			return false;
		}

		var gameAssembly = CustomUnitViewRouting.GameAssembly;
		var iListener = gameAssembly.GetType("Hex.Session.Battle.IUnitListenner", throwOnError: false);
		const BindingFlags inst = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

		foreach (var prop in typeof(Unit).GetProperties(inst))
		{
			var matchByName = string.Equals(prop.Name, "listener", StringComparison.Ordinal);
			var matchByIface = iListener != null && iListener.IsAssignableFrom(prop.PropertyType);
			if (!matchByName && !matchByIface)
			{
				continue;
			}

			object drawer;
			try
			{
				drawer = prop.GetValue(unit);
			}
			catch
			{
				continue;
			}

			if (drawer != null)
			{
				unitDrawerType = drawer.GetType();
				return true;
			}
		}

		foreach (var prop in typeof(Unit).GetProperties(inst))
		{
			object candidate;
			try
			{
				candidate = prop.GetValue(unit);
			}
			catch
			{
				continue;
			}

			if (candidate != null && MightBeBattleUnitDrawerInstance(candidate))
			{
				unitDrawerType = candidate.GetType();
				return true;
			}
		}

		foreach (var field in typeof(Unit).GetFields(inst))
		{
			object candidate;
			try
			{
				candidate = field.GetValue(unit);
			}
			catch
			{
				continue;
			}

			if (candidate != null && MightBeBattleUnitDrawerInstance(candidate))
			{
				unitDrawerType = candidate.GetType();
				return true;
			}
		}

		try
		{
			var bhType = ResolveBhActiveBattleClrType();
			if (bhType == null)
			{
				return false;
			}

			var meProp = bhType.GetProperty("me", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			var me = meProp?.GetValue(null);
			if (me == null)
			{
				return false;
			}

			object drawers = null;
			var drawersProp = me.GetType().GetProperty("unitsDrawers", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (drawersProp != null)
			{
				try
				{
					drawers = drawersProp.GetValue(me);
				}
				catch
				{
					drawers = null;
				}
			}

			if (drawers == null)
			{
				foreach (var p in me.GetType().GetProperties(inst))
				{
					object container;
					try
					{
						container = p.GetValue(me);
					}
					catch
					{
						continue;
					}

					if (container == null)
					{
						continue;
					}

					foreach (var method in container.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
					{
						if (!string.Equals(method.Name, "Get", StringComparison.Ordinal))
						{
							continue;
						}

						var ps = method.GetParameters();
						if (ps.Length != 1 || !typeof(Unit).IsAssignableFrom(ps[0].ParameterType))
						{
							continue;
						}

						object drawer;
						try
						{
							drawer = method.Invoke(container, new object[] { unit });
						}
						catch
						{
							continue;
						}

						if (drawer != null)
						{
							unitDrawerType = drawer.GetType();
							return true;
						}
					}
				}

				return false;
			}

			foreach (var method in drawers.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				if (!string.Equals(method.Name, "Get", StringComparison.Ordinal))
				{
					continue;
				}

				var ps = method.GetParameters();
				if (ps.Length != 1 || !typeof(Unit).IsAssignableFrom(ps[0].ParameterType))
				{
					continue;
				}

				object drawer;
				try
				{
					drawer = method.Invoke(drawers, new object[] { unit });
				}
				catch
				{
					continue;
				}

				if (drawer != null)
				{
					unitDrawerType = drawer.GetType();
					return true;
				}
			}
		}
		catch
		{
			// ignored
		}

		return false;
	}

	private static MethodInfo ResolveBattleDrawerInit(Type unitDrawerType)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		MethodInfo signatureFallback = null;
		foreach (var method in unitDrawerType.GetMethods(flags))
		{
			if (method.DeclaringType != unitDrawerType)
			{
				continue;
			}

			var p = method.GetParameters();
			if (p.Length != 7 || !typeof(UnitViewConfig).IsAssignableFrom(p[0].ParameterType))
			{
				continue;
			}

			signatureFallback ??= method;

			if (string.Equals(method.Name, "Init", StringComparison.Ordinal))
			{
				return method;
			}
		}

		return signatureFallback;
	}

	private static Type ResolveFieldObjectDrawerType()
	{
		return CustomUnitViewRouting.GameAssembly.GetType("Hex.Session.Battle.FieldObjectDrawer", throwOnError: false)
			?? FindGameType("Hex.Session.Battle.FieldObjectDrawer");
	}

	private static MethodInfo ResolveFieldObjectDrawerProcessVirtualSlot()
	{
		var fod = ResolveFieldObjectDrawerType();
		if (fod == null)
		{
			return null;
		}

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		foreach (var method in fod.GetMethods(flags))
		{
			if (method.Name != "Process")
			{
				continue;
			}

			var p = method.GetParameters();
			if (p.Length != 1 || !IsIl2CppSingleParameter(p[0].ParameterType))
			{
				continue;
			}

			return method;
		}

		return null;
	}

	private static MethodInfo ResolveBattleDrawerProcessFloat(Type unitDrawerType)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;

		for (var t = unitDrawerType; t != null; t = t.BaseType)
		{
			foreach (var method in t.GetMethods(flags))
			{
				if (method.Name != "Process")
				{
					continue;
				}

				var p = method.GetParameters();
				if (p.Length != 1 || !IsIl2CppSingleParameter(p[0].ParameterType))
				{
					continue;
				}

				return method;
			}
		}

		// Playtest IL may rename the override on UnitDrawer; still overrides FieldObjectDrawer.Process(float).
		var virtualSlot = ResolveFieldObjectDrawerProcessVirtualSlot();
		if (virtualSlot == null)
		{
			return null;
		}

		for (var t = unitDrawerType; t != null; t = t.BaseType)
		{
			foreach (var method in t.GetMethods(flags))
			{
				if (method.GetParameters().Length != 1 || !IsIl2CppSingleParameter(method.GetParameters()[0].ParameterType))
				{
					continue;
				}

				MethodInfo baseDef;
				try
				{
					baseDef = method.GetBaseDefinition();
				}
				catch
				{
					continue;
				}

				if (ReferenceEquals(baseDef, virtualSlot) ||
				    (baseDef.MetadataToken == virtualSlot.MetadataToken && baseDef.DeclaringType == virtualSlot.DeclaringType))
				{
					return method;
				}
			}
		}

		return null;
	}

	private static MethodInfo ResolveBattleDrawerProcessVisualFrame(Type unitDrawerType)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var t = unitDrawerType; t != null; t = t.BaseType)
		{
			foreach (var method in t.GetMethods(flags | BindingFlags.DeclaredOnly))
			{
				if (method.Name != "ProcessVisualFrame")
				{
					continue;
				}

				var p = method.GetParameters();
				if (p.Length != 1 || !IsIl2CppSingleParameter(p[0].ParameterType))
				{
					continue;
				}

				return method;
			}
		}

		return null;
	}

	private static bool IsIl2CppSingleParameter(Type parameterType)
	{
		if (parameterType == null)
		{
			return false;
		}

		if (parameterType == typeof(float))
		{
			return true;
		}

		if (string.Equals(parameterType.Name, "Single", StringComparison.Ordinal))
		{
			return true;
		}

		var fn = parameterType.FullName;
		return fn != null
			&& (fn.EndsWith(".Single", StringComparison.Ordinal) || fn.Contains("Il2CppSystem.Single", StringComparison.Ordinal));
	}

	private static void LogUnitDrawerMethodDiagnostics(Type unitDrawerType, MethodInfo initOk, MethodInfo tickOk)
	{
		if (_battleDrawerProbeLogged)
		{
			return;
		}

		_battleDrawerProbeLogged = true;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;

		string Sig(MethodInfo m)
		{
			var ps = m.GetParameters();
			var args = string.Join(", ", ps.Select(p => $"{p.ParameterType.FullName ?? p.ParameterType.Name}"));
			return $"{m.Name}({args})";
		}

		var inits = unitDrawerType.GetMethods(flags).Where(m => m.DeclaringType == unitDrawerType && m.Name == "Init").Select(Sig).ToArray();
		var procs = unitDrawerType.GetMethods(flags).Where(m => m.DeclaringType == unitDrawerType && m.Name == "Process").Select(Sig).ToArray();
		var pvfs = unitDrawerType.GetMethods(flags).Where(m => m.DeclaringType == unitDrawerType && m.Name == "ProcessVisualFrame").Select(Sig).ToArray();
		Plugin.LogSource?.LogWarning(
			$"Battle drawer probe on '{unitDrawerType.FullName}' (Assembly={unitDrawerType.Assembly.GetName().Name}). Init resolved={initOk != null}; Tick resolved={tickOk != null}. Declared Init: [{string.Join(" | ", inits)}]. Declared Process: [{string.Join(" | ", procs)}]. Declared ProcessVisualFrame: [{string.Join(" | ", pvfs)}].");
	}

	internal static void EnsureRuntimePrefabRouteInstalled()
	{
		if (_runtimePrefabRouteInstalled)
		{
			return;
		}

		var resManagerType = FindGameType("Hex.ResManager");
		if (resManagerType == null)
		{
			if (!_runtimePrefabRouteWarningLogged)
			{
				_runtimePrefabRouteWarningLogged = true;
				Plugin.LogSource?.LogWarning("Custom prefab runtime could not find ResManager yet.");
			}

			return;
		}

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var patchedMethods = new List<string>();
		_runtimeHarmony ??= new Harmony(Plugin.PluginGuid + ".runtime-billboards");

		MethodInfo gameObjectLoader = null;
		foreach (var method in resManagerType.GetMethods(flags))
		{
			if (!string.Equals(method.Name, "bmeo", StringComparison.Ordinal) || !method.IsStatic)
			{
				continue;
			}

			if (method.GetParameters().Length != 1 || method.GetParameters()[0].ParameterType != typeof(string))
			{
				continue;
			}

			if (method.IsGenericMethodDefinition && method.GetGenericArguments().Length == 1)
			{
				gameObjectLoader = method.MakeGenericMethod(typeof(GameObject));
				break;
			}

			if (!method.IsGenericMethodDefinition && method.ReturnType == typeof(GameObject))
			{
				gameObjectLoader = method;
				break;
			}
		}

		if (gameObjectLoader != null)
		{
			try
			{
				_runtimeHarmony.Patch(
					gameObjectLoader,
					prefix: new HarmonyMethod(typeof(TempleSwordsmanBillboardPrototype), nameof(ResManagerBmeoGameObjectPrefix)));
				_resManagerGetGameObjectMethod = gameObjectLoader;
				patchedMethods.Add(gameObjectLoader.IsGenericMethod ? "bmeo<GameObject>" : "bmeo");
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"Custom prefab runtime failed to patch ResManager static loader: {ex.Message}");
			}
		}

		if (patchedMethods.Count == 0)
		{
			if (!_runtimePrefabRouteWarningLogged)
			{
				_runtimePrefabRouteWarningLogged = true;
				Plugin.LogSource?.LogWarning(
					"Custom prefab runtime could not find ResManager static GameObject loader (expected obfuscated name 'bmeo').");
			}

			return;
		}

		_runtimePrefabRouteInstalled = true;
		Plugin.LogSource?.LogInfo($"Installed runtime prefab route patch on {resManagerType.FullName}: {string.Join(", ", patchedMethods)}.");
	}

	internal static bool IsRuntimePrefabRouteInstalled()
	{
		return _runtimePrefabRouteInstalled;
	}

	internal static void HandleInit(object drawerInstance, UnitViewConfig viewConfig)
	{
		if (drawerInstance is not Component drawerComponent || viewConfig == null)
		{
			return;
		}

		var key = drawerComponent.GetInstanceID();
		if (!CustomUnitViewRouting.TryResolvePrototypeExportFolder(viewConfig, out var configId, out var exportFolderName))
		{
			if (ActiveStates.TryGetValue(key, out var existing))
			{
				existing.RestoreOriginalVisuals();
				ActiveStates.Remove(key);
			}

			return;
		}

		var assets = GetAssets(exportFolderName);
		if (assets == null)
		{
			Plugin.LogSource?.LogError($"Custom cutout: could not load export folder '{exportFolderName}' for unit '{configId}'. Donor mesh unchanged.");
			return;
		}

		if (!assets.HasRenderableFrames())
		{
			Plugin.LogSource?.LogError(
				$"Custom cutout: export '{exportFolderName}' has no decoded PNG frames for '{configId}'. Fix texture decode or paths; leaving official donor mesh visible.");
			return;
		}

		var meshHolder = TraverseMember<GameObject>(drawerInstance, "meshHolder");
		var animator = TraverseMember<Animator>(drawerInstance, "animator");
		var cutoutObject = TraverseMember<GameObject>(drawerInstance, "cutoutObject");
		var cutoutMaterial = TraverseMember<Material>(drawerInstance, "cutoutMaterial");
		if (meshHolder == null || animator == null || cutoutObject == null || cutoutMaterial == null)
		{
			Plugin.LogSource?.LogWarning("Temple swordsman prototype could not access UnitDrawer visuals.");
			return;
		}

		if (ActiveStates.TryGetValue(key, out var priorState))
		{
			priorState.RestoreOriginalVisuals();
			ActiveStates.Remove(key);
		}

		var state = new PrototypeState(drawerComponent, viewConfig, meshHolder, animator, cutoutObject, cutoutMaterial, assets);
		state.Initialize();
		ActiveStates[key] = state;
		Plugin.LogSource?.LogInfo($"Attached runtime billboard visuals for '{configId}' using export '{exportFolderName}'.");
	}

	internal static void HandleUpdate(object drawerInstance)
	{
		if (drawerInstance is not Component drawerComponent)
		{
			return;
		}

		var key = drawerComponent.GetInstanceID();
		if (!ActiveStates.TryGetValue(key, out var state))
		{
			return;
		}

		if (!state.Sync())
		{
			state.RestoreOriginalVisuals();
			ActiveStates.Remove(key);
		}
	}

	internal static bool TryGetMapPrefab(UnitViewConfig viewConfig, out GameObject prefab)
	{
		prefab = null;
		if (viewConfig == null || !CustomUnitViewRouting.TryResolvePrototypeExportFolder(viewConfig, out var configId, out var exportFolderName))
		{
			return false;
		}

		if (MapPrefabsByUnitSid.TryGetValue(configId, out prefab) && prefab != null)
		{
			return true;
		}

		var assets = GetAssets(exportFolderName);
		if (assets == null)
		{
			return false;
		}

		prefab = BuildMapPrefab(configId, assets, viewConfig.modelHeight);
		if (prefab == null)
		{
			return false;
		}

		MapPrefabsByUnitSid[configId] = prefab;
		Plugin.LogSource?.LogInfo($"Built runtime map prefab for '{configId}' from export '{exportFolderName}'.");
		return true;
	}

	internal static bool TryGetBattlePrefab(string path, out GameObject prefab)
	{
		prefab = null;
		if (!CustomUnitViewRouting.TryGetBattlePrefabRequest(path, out var unitSid, out var exportFolderName, out var donorMesh))
		{
			return false;
		}

		if (BattlePrefabsByPath.TryGetValue(path, out prefab) && prefab != null)
		{
			return true;
		}

		var donorPath = "units/" + donorMesh;
		var donorPrefab = GetOriginalGameObject(donorPath);
		if (donorPrefab == null)
		{
			Plugin.LogSource?.LogError($"Custom battle prefab route failed: donor asset not loaded from '{donorPath}'.");
			return false;
		}

		var assetsProbe = GetAssets(exportFolderName);
		if (assetsProbe == null || !assetsProbe.HasRenderableFrames())
		{
			Plugin.LogSource?.LogWarning(
				$"Custom battle prefab '{path}': donor '{donorPath}' will load with full UnitDrawer behavior, but export '{exportFolderName}' has no decoded PNG frames yet — cutout swap will be skipped until textures load.");
		}

		prefab = donorPrefab;
		BattlePrefabsByPath[path] = prefab;
		Plugin.LogSource?.LogInfo(
			$"Custom battle prefab '{path}' -> official donor prefab asset '{donorPath}' " +
			"(Animator + BhBattleTimelineHelper + mesh layout unchanged per game pipeline). " +
			$"HoMM3-style sprites for '{unitSid}' target export '{exportFolderName}' on engine unit_cutout via UnitDrawer hook.");
		return true;
	}

	private static PrototypeAssetBundle GetAssets(string exportFolderName)
	{
		if (string.IsNullOrWhiteSpace(exportFolderName))
		{
			return null;
		}

		if (AssetsByExportFolder.TryGetValue(exportFolderName, out var cachedOk))
		{
			return cachedOk;
		}

		PrototypeAssetBundle bundle = null;
		try
		{
			if (!TryResolveBillboardExportRoot(exportFolderName, out var root))
			{
				Plugin.LogSource?.LogWarning(
					$"Runtime billboard manifest not found for '{exportFolderName}'. " +
					$"Put manifest.json + clips under OfflineUnlockMod/unity_exports/{exportFolderName}/ next to the DLL, " +
					$"or under ../tools/unity_exports/{exportFolderName}/ relative to the game.");
				return null;
			}

			var manifestPath = Path.Combine(root, "manifest.json");
			if (!File.Exists(manifestPath))
			{
				Plugin.LogSource?.LogWarning($"Runtime billboard manifest not found: {manifestPath}");
				return null;
			}

			var manifest = ParseManifest(File.ReadAllText(manifestPath));
			if (manifest == null)
			{
				Plugin.LogSource?.LogWarning($"Runtime billboard manifest could not be parsed: {manifestPath}");
				return null;
			}

			bundle = PrototypeAssetBundle.Load(root, manifest);
			if (bundle == null || !bundle.HasRenderableFrames())
			{
				Plugin.LogSource?.LogWarning(
					$"Billboard export '{exportFolderName}' loaded from {root} but no PNG frames decoded (check ImageConversion / paths).");
				return null;
			}

			AssetsByExportFolder[exportFolderName] = bundle;
			Plugin.LogSource?.LogInfo($"Loaded runtime billboard assets from {root}.");
			return bundle;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Failed to load runtime billboard assets for '{exportFolderName}': {ex.Message}");
			return null;
		}
	}

	/// <summary>
	/// Prefer <c>BepInEx/plugins/OfflineUnlockMod/unity_exports/&lt;folder&gt;/</c> (shippable with the DLL), then legacy
	/// <c>&lt;game&gt;/../tools/unity_exports/&lt;folder&gt;/</c>.
	/// </summary>
	private static bool TryResolveBillboardExportRoot(string exportFolderName, out string root)
	{
		root = null;
		if (string.IsNullOrWhiteSpace(exportFolderName))
		{
			return false;
		}

		var asmPath = typeof(Plugin).Assembly.Location;
		if (!string.IsNullOrEmpty(asmPath))
		{
			var asmDir = Path.GetDirectoryName(asmPath);
			if (!string.IsNullOrEmpty(asmDir))
			{
				var bundled = Path.GetFullPath(Path.Combine(asmDir, "unity_exports", exportFolderName));
				if (File.Exists(Path.Combine(bundled, "manifest.json")))
				{
					root = bundled;
					return true;
				}
			}
		}

		var legacy = Path.GetFullPath(Path.Combine(Paths.GameRootPath, "..", "tools", "unity_exports", exportFolderName));
		if (File.Exists(Path.Combine(legacy, "manifest.json")))
		{
			root = legacy;
			return true;
		}

		return false;
	}

	private static PrototypeManifest ParseManifest(string json)
	{
		if (string.IsNullOrWhiteSpace(json))
		{
			return null;
		}

		try
		{
			var jo = JObject.Parse(json);
			var canvasToken = jo["canvas"];
			var manifest = new PrototypeManifest
			{
				canvas = new PrototypeCanvas
				{
					width = canvasToken?["width"] != null ? canvasToken["width"].ToObject<int>() : ReadInt(json, "\"width\"\\s*:\\s*(\\d+)", 1),
					height = canvasToken?["height"] != null ? canvasToken["height"].ToObject<int>() : ReadInt(json, "\"height\"\\s*:\\s*(\\d+)", 1)
				},
				clips = ParseManifestClipsFromJArray(jo["clips"] as JArray)
			};

			if (manifest.clips != null && manifest.clips.Length > 0)
			{
				return manifest;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Billboard manifest JSON parse failed ({ex.Message}); trying legacy regex.");
		}

		var fallback = new PrototypeManifest
		{
			canvas = new PrototypeCanvas
			{
				width = ReadInt(json, "\"width\"\\s*:\\s*(\\d+)", 1),
				height = ReadInt(json, "\"height\"\\s*:\\s*(\\d+)", 1)
			}
		};

		var clipMatches = Regex.Matches(
			json,
			"\\{\\s*\"name\"\\s*:\\s*\"([^\"]+)\".*?\"loop\"\\s*:\\s*(true|false).*?\"files\"\\s*:\\s*\\[(.*?)\\]\\s*\\}",
			RegexOptions.Singleline);
		fallback.clips = clipMatches
			.Cast<Match>()
			.Select(match => new PrototypeClip
			{
				name = match.Groups[1].Value,
				loop = bool.TryParse(match.Groups[2].Value, out var loop) && loop,
				files = Regex.Matches(match.Groups[3].Value, "\"([^\"]+)\"")
					.Cast<Match>()
					.Select(fileMatch => fileMatch.Groups[1].Value)
					.ToArray()
			})
			.Where(clip => !string.IsNullOrWhiteSpace(clip.name) && clip.files.Length > 0)
			.ToArray();

		return fallback.clips.Length == 0 ? null : fallback;
	}

	private static PrototypeClip[] ParseManifestClipsFromJArray(JArray clipsArr)
	{
		if (clipsArr == null || clipsArr.Count == 0)
		{
			return Array.Empty<PrototypeClip>();
		}

		var list = new List<PrototypeClip>();
		for (var i = 0; i < clipsArr.Count; i++)
		{
			var token = clipsArr[i];
			var filesToken = token["files"] as JArray;
			string[] files;
			if (filesToken != null && filesToken.Count > 0)
			{
				var fl = new List<string>();
				for (var fi = 0; fi < filesToken.Count; fi++)
				{
					var s = filesToken[fi]?.ToObject<string>();
					if (!string.IsNullOrEmpty(s))
					{
						fl.Add(s);
					}
				}

				files = fl.ToArray();
			}
			else
			{
				files = Array.Empty<string>();
			}

			var clip = new PrototypeClip
			{
				name = token["name"]?.ToObject<string>(),
				loop = token["loop"]?.ToObject<bool>() ?? false,
				files = files
			};
			if (!string.IsNullOrWhiteSpace(clip.name) && clip.files.Length > 0)
			{
				list.Add(clip);
			}
		}

		return list.ToArray();
	}

	private static int ReadInt(string text, string pattern, int fallback)
	{
		var match = Regex.Match(text, pattern, RegexOptions.Singleline);
		return match.Success && int.TryParse(match.Groups[1].Value, out var value) ? value : fallback;
	}

	private static GameObject BuildMapPrefab(string configId, PrototypeAssetBundle assets, float modelHeight)
	{
		var texture = assets.GetRepresentativeFrame();
		if (texture == null)
		{
			return null;
		}

		var root = new GameObject($"{configId}_runtime_map_prefab");
		root.SetActive(false);

		var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
		quad.name = "billboard";
		quad.transform.SetParent(root.transform, worldPositionStays: false);

		// IL2CPP: GameObject.GetComponent(string) throws MissingMethodException (ReadOnlySpan) on Unity 6.
		// Physics types may not be in compile refs — strip any *Collider component by name.
		foreach (var comp in quad.GetComponents<Component>())
		{
			if (comp == null)
			{
				continue;
			}

			var tn = comp.GetType().Name;
			if (tn.EndsWith("Collider", StringComparison.Ordinal))
			{
				UnityEngine.Object.Destroy(comp);
			}
		}

		var material = new Material(FindTransparentShader())
		{
			mainTexture = texture
		};
		var renderer = quad.GetComponent<MeshRenderer>();
		if (renderer != null)
		{
			renderer.sharedMaterial = material;
			renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
			renderer.receiveShadows = false;
		}

		var height = modelHeight > 0f ? Mathf.Max(0.75f, modelHeight * 0.55f) : 1.2f;
		var width = height * assets.AspectRatio;
		quad.transform.localPosition = new Vector3(0f, height * 0.5f, 0f);
		quad.transform.localRotation = Quaternion.identity;
		quad.transform.localScale = new Vector3(width, height, 1f);
		return root;
	}

	private static Shader FindTransparentShader()
	{
		return Shader.Find("Sprites/Default")
			?? Shader.Find("Unlit/Transparent")
			?? Shader.Find("Legacy Shaders/Transparent/Cutout/Diffuse")
			?? Shader.Find("Standard");
	}

	private static GameObject GetOriginalGameObject(string path)
	{
		if (_resManagerGetGameObjectMethod == null || string.IsNullOrWhiteSpace(path))
		{
			return null;
		}

		try
		{
			_resManagerBypass = true;
			return _resManagerGetGameObjectMethod.Invoke(null, new object[] { path }) as GameObject;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Failed to load donor prefab '{path}' through ResManager: {ex.Message}");
			return null;
		}
		finally
		{
			_resManagerBypass = false;
		}
	}

	/// <summary>
	/// HarmonyX matches IL2CPP parameter names; ResManager loaders use <c>string a</c>, not <c>path</c>.
	/// Keep this prefix side-effect free: rewrite only the requested path and let original bmeo() load it.
	/// </summary>
	private static bool ResManagerBmeoGameObjectPrefix(ref string a)
	{
		if (!string.IsNullOrWhiteSpace(a) &&
		    a.IndexOf("units/Custom/", StringComparison.Ordinal) >= 0)
		{
			CustomUnitViewRouting.TryRewriteUnregisteredCustomUnitsPath(ref a);
		}

		if (!_battleContextEntered || !IsBattleViewActive())
		{
			return true;
		}

		if (string.IsNullOrWhiteSpace(a))
		{
			return true;
		}

		if (CustomUnitViewRouting.TryGetBattlePrefabRequest(a, out var unitSid, out var exportFolderName, out var donorMesh))
		{
			var donorPath = "units/" + donorMesh;
			Plugin.LogSource?.LogInfo(
				$"ResManager.bmeo reroute: '{a}' -> '{donorPath}' for unit '{unitSid}'. " +
				$"UnitDrawer cutout will use export '{exportFolderName}'.");
			a = donorPath;
		}

		return true;
	}

	/// <summary>
	/// Obfuscated builds may rename <c>Hex.Session.Battle.UnitDrawer</c>.
	/// Several types share the battle <c>Init(UnitViewConfig, …)</c> signature (e.g. preview drawers); require a per-frame tick too.
	/// </summary>
	private static Type FindBattleUnitDrawerTypeByInitAndTick()
	{
		Type[] types;
		try
		{
			types = CustomUnitViewRouting.GameAssembly.GetTypes();
		}
		catch (ReflectionTypeLoadException ex)
		{
			types = ex.Types;
		}
		catch
		{
			return null;
		}

		if (types == null)
		{
			return null;
		}

		var fodType = ResolveFieldObjectDrawerType();

		const string battleDrawerFullName = "Hex.Session.Battle.UnitDrawer";
		foreach (var type in types)
		{
			if (type == null || type.IsAbstract)
			{
				continue;
			}

			if (!string.Equals(type.FullName, battleDrawerFullName, StringComparison.Ordinal))
			{
				continue;
			}

			if (fodType != null && !type.IsSubclassOf(fodType))
			{
				continue;
			}

			if (!TypeHasBattleDrawerInitSignature(type))
			{
				continue;
			}

			if (ResolveBattleDrawerProcessFloat(type) != null || ResolveBattleDrawerProcessVisualFrame(type) != null)
			{
				return type;
			}
		}

		Type preferred = null;
		Type fallback = null;
		foreach (var type in types)
		{
			if (type == null || type.IsAbstract)
			{
				continue;
			}

			if (fodType != null && !type.IsSubclassOf(fodType))
			{
				continue;
			}

			if (!TypeHasBattleDrawerInitSignature(type))
			{
				continue;
			}

			if (ResolveBattleDrawerProcessFloat(type) == null && ResolveBattleDrawerProcessVisualFrame(type) == null)
			{
				continue;
			}

			var fn = type.FullName ?? string.Empty;
			if (fn.IndexOf("UnitDrawer", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				preferred = type;
				break;
			}

			fallback ??= type;
		}

		return preferred ?? fallback;
	}

	private static bool TypeHasBattleDrawerInitSignature(Type type)
	{
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			var parameters = method.GetParameters();
			if (parameters.Length != 7 ||
			    !typeof(UnitViewConfig).IsAssignableFrom(parameters[0].ParameterType))
			{
				continue;
			}

			return true;
		}

		return false;
	}

	private static T TraverseMember<T>(object instance, string memberName) where T : class
	{
		var t = Traverse.Create(instance);
		try
		{
			var viaProp = t.Property(memberName)?.GetValue<T>();
			if (viaProp != null)
			{
				return viaProp;
			}
		}
		catch
		{
			// ignored
		}

		try
		{
			return t.Field(memberName).GetValue<T>();
		}
		catch
		{
			return null;
		}
	}

	/// <summary>
	/// Resolve a type from <see cref="CustomUnitViewRouting.GameAssembly"/> only (Hex game DLL). Try CLR full name
	/// first; if missing, match by short name within that assembly (never scan Unity/BepInEx assemblies).
	/// </summary>
	private static Type FindGameType(string fullName)
	{
		var asm = CustomUnitViewRouting.GameAssembly;
		var direct = asm.GetType(fullName, throwOnError: false);
		if (direct != null)
		{
			return direct;
		}

		var lastDot = fullName.LastIndexOf('.');
		if (lastDot < 0 || lastDot >= fullName.Length - 1)
		{
			return null;
		}

		var simpleName = fullName.Substring(lastDot + 1);
		Type[] types;
		try
		{
			types = asm.GetTypes();
		}
		catch (ReflectionTypeLoadException ex)
		{
			types = ex.Types;
		}
		catch
		{
			return null;
		}

		if (types == null)
		{
			return null;
		}

		foreach (var type in types)
		{
			if (type != null && string.Equals(type.FullName, fullName, StringComparison.Ordinal))
			{
				return type;
			}
		}

		foreach (var type in types)
		{
			if (type != null && string.Equals(type.Name, simpleName, StringComparison.Ordinal))
			{
				return type;
			}
		}

		return null;
	}

	private static void UnitDrawerInitPostfix(object __instance, UnitViewConfig _viewConfig)
	{
		HandleInit(__instance, _viewConfig);
	}

	private static void UnitDrawerProcessPostfix(object __instance, float dt)
	{
		HandleUpdate(__instance);
	}

	private sealed class PrototypeState
	{
		private readonly Component _drawerComponent;
		private readonly UnitViewConfig _viewConfig;
		private readonly GameObject _meshHolder;
		private readonly Animator _animator;
		private readonly GameObject _cutoutObject;
		private readonly Material _cutoutMaterial;
		private readonly PrototypeAssetBundle _assets;
		private readonly Renderer[] _hiddenRenderers;
		private readonly MeshRenderer _cutoutRenderer;
		private string _lastSequenceName;
		private int _lastFrameIndex = -1;
		private bool _initialized;

		internal PrototypeState(
			Component drawerComponent,
			UnitViewConfig viewConfig,
			GameObject meshHolder,
			Animator animator,
			GameObject cutoutObject,
			Material cutoutMaterial,
			PrototypeAssetBundle assets)
		{
			_drawerComponent = drawerComponent;
			_viewConfig = viewConfig;
			_meshHolder = meshHolder;
			_animator = animator;
			_cutoutObject = cutoutObject;
			_cutoutMaterial = cutoutMaterial;
			_assets = assets;
			_hiddenRenderers = meshHolder.GetComponentsInChildren<Renderer>(includeInactive: true);
			_cutoutRenderer = cutoutObject.GetComponentInChildren<MeshRenderer>(includeInactive: true);
		}

		internal void Initialize()
		{
			if (_initialized)
			{
				return;
			}

			foreach (var renderer in _hiddenRenderers)
			{
				if (renderer != null)
				{
					renderer.enabled = false;
				}
			}

			_animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
			if (_cutoutRenderer != null)
			{
				_cutoutRenderer.enabled = true;
			}

			_cutoutObject.SetActive(true);
			ApplyTransform();
			_initialized = true;
		}

		internal void RestoreOriginalVisuals()
		{
			foreach (var renderer in _hiddenRenderers)
			{
				if (renderer != null)
				{
					renderer.enabled = true;
				}
			}

			if (_cutoutRenderer != null)
			{
				_cutoutRenderer.enabled = false;
			}
		}

		internal bool Sync()
		{
			if (_animator == null || _cutoutObject == null || _cutoutMaterial == null || _drawerComponent == null)
			{
				return false;
			}

			_cutoutObject.SetActive(true);
			if (_cutoutRenderer != null)
			{
				_cutoutRenderer.enabled = true;
			}

			ApplyTransform();

			var clipName = GetCurrentClipName(_animator);
			if (!string.IsNullOrEmpty(clipName) && LoggedClipNames.Add(clipName))
			{
				Plugin.LogSource?.LogInfo($"Temple swordsman prototype observed clip: {clipName}");
			}

			var sequence = _assets.ResolveSequence(clipName);
			if (sequence == null || sequence.Frames.Length == 0)
			{
				return true;
			}

			var stateInfo = _animator.GetCurrentAnimatorStateInfo(0);
			var normalizedTime = sequence.Loop
				? Mathf.Repeat(stateInfo.normalizedTime, 1f)
				: Mathf.Clamp01(stateInfo.normalizedTime);
			var frameIndex = Mathf.Min(sequence.Frames.Length - 1, Mathf.FloorToInt(normalizedTime * sequence.Frames.Length));

			if (!string.Equals(sequence.Name, _lastSequenceName, StringComparison.Ordinal) || frameIndex != _lastFrameIndex)
			{
				_cutoutMaterial.mainTexture = sequence.Frames[frameIndex];
				_lastSequenceName = sequence.Name;
				_lastFrameIndex = frameIndex;
			}

			return true;
		}

		private void ApplyTransform()
		{
			var transform = _cutoutObject.transform;
			var height = _viewConfig.modelHeight > 0f ? _viewConfig.modelHeight : 2f;
			var width = height * _assets.AspectRatio;
			transform.localPosition = new Vector3(0f, height * 0.5f, 0f);
			transform.localScale = new Vector3(width, height, 1f);

			var camera = Camera.main ?? UnityEngine.Object.FindObjectOfType<Camera>();
			if (camera != null)
			{
				transform.rotation = camera.transform.rotation;
			}
		}

		private static string GetCurrentClipName(Animator animator)
		{
			try
			{
				var infos = animator.GetCurrentAnimatorClipInfo(0);
				if (infos != null && infos.Length > 0 && infos[0].clip != null)
				{
					return infos[0].clip.name;
				}
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"Temple swordsman prototype failed to read current clip: {ex.Message}");
			}

			return null;
		}
	}

	private sealed class PrototypeAssetBundle
	{
		private static bool _loggedSoftwareRgbaUpload;

		private readonly Dictionary<string, PrototypeSequence> _byName;

		private PrototypeAssetBundle(Dictionary<string, PrototypeSequence> byName, float aspectRatio)
		{
			_byName = byName;
			AspectRatio = aspectRatio;
		}

		internal float AspectRatio { get; }

		internal bool HasRenderableFrames()
		{
			return _byName.Values.Any(sequence => sequence.Frames != null && sequence.Frames.Length > 0);
		}

		internal static PrototypeAssetBundle Load(string root, PrototypeManifest manifest)
		{
			var byName = new Dictionary<string, PrototypeSequence>(StringComparer.OrdinalIgnoreCase);
			var width = manifest?.canvas?.width ?? 1;
			var height = manifest?.canvas?.height ?? 1;
			var aspectRatio = height == 0 ? 1f : (float)width / height;

			foreach (var clip in manifest?.clips ?? Enumerable.Empty<PrototypeClip>())
			{
				var textures = new List<Texture2D>();
				for (var fi = 0; fi < clip.files.Length; fi++)
				{
					var rel = NormalizeClipRelativePath(clip.files[fi]);
					var combined = Path.Combine(root, rel);
					var tex = LoadTexture(Path.GetFullPath(combined));
					if (tex != null)
					{
						textures.Add(tex);
					}
				}

				if (textures.Count == 0)
				{
					continue;
				}

				byName[clip.name] = new PrototypeSequence
				{
					Name = clip.name,
					Loop = clip.loop,
					Frames = textures.ToArray()
				};
			}

			return new PrototypeAssetBundle(byName, aspectRatio);
		}

		private static string NormalizeClipRelativePath(string file)
		{
			if (string.IsNullOrEmpty(file))
			{
				return file;
			}

			var s = file.Trim().Replace('/', Path.DirectorySeparatorChar);
			while (s.Contains($"{Path.DirectorySeparatorChar}{Path.DirectorySeparatorChar}"))
			{
				s = s.Replace($"{Path.DirectorySeparatorChar}{Path.DirectorySeparatorChar}", $"{Path.DirectorySeparatorChar}");
			}

			return s;
		}

		internal PrototypeSequence ResolveSequence(string clipName)
		{
			if (TryResolve(clipName, out var sequence))
			{
				return sequence;
			}

			return _byName.TryGetValue("idle", out var idle) ? idle : null;
		}

		internal Texture2D GetRepresentativeFrame()
		{
			return ResolveSequence("idle")?.Frames?.FirstOrDefault()
				?? _byName.Values.SelectMany(sequence => sequence.Frames).FirstOrDefault();
		}

		private bool TryResolve(string clipName, out PrototypeSequence sequence)
		{
			sequence = null;
			var normalized = (clipName ?? string.Empty).Trim().ToLowerInvariant();
			var preferred = normalized switch
			{
				"idle" => "idle",
				"rare" => "mouse_over",
				"walk" => "movement",
				"move" => "movement",
				"fly" => "movement",
				"damage" => "hitted",
				"death" => "death",
				"victory" => "mouse_over",
				"rotateleft" => "turn_left",
				"rotateright" => "turn_right",
				"attack" => "attack_front",
				"1" => "attack_front",
				"2" => "attack_front",
				"3" => "attack_front",
				"4" => "attack_front",
				"5" => "attack_front",
				_ when normalized.Contains("attack") => "attack_front",
				_ => "idle"
			};

			if (_byName.TryGetValue(preferred, out sequence))
			{
				return true;
			}

			if (preferred == "mouse_over" && _byName.TryGetValue("idle", out sequence))
			{
				return true;
			}

			return false;
		}

		/// <summary>
		/// Reads width/height from the first IHDR chunk. IL2CPP often rejects <see cref="UnityEngine.ImageConversion.LoadImage"/>
		/// into a tiny placeholder <see cref="Texture2D"/>; allocating native-sized storage first fixes that.
		/// </summary>
		private static bool TryReadPngIhdrDimensions(byte[] bytes, out int width, out int height)
		{
			width = height = 0;
			// Signature + length(4) + 'IHDR'(4) + 13-byte IHDR payload (width,height,bit_depth,color_type,...)
			const int minimum = 8 + 4 + 4 + 13;
			if (bytes == null || bytes.Length < minimum)
			{
				return false;
			}

			if (bytes[0] != 0x89 || bytes[1] != 0x50 || bytes[2] != 0x4e || bytes[3] != 0x47 ||
			    bytes[4] != 0x0d || bytes[5] != 0x0a || bytes[6] != 0x1a || bytes[7] != 0x0a)
			{
				return false;
			}

			var chunkDataLength = (int)ReadUInt32BigEndian(bytes, 8);
			if (chunkDataLength != 13 ||
			    bytes[12] != (byte)'I' || bytes[13] != (byte)'H' ||
			    bytes[14] != (byte)'D' || bytes[15] != (byte)'R')
			{
				return false;
			}

			width = checked((int)ReadUInt32BigEndian(bytes, 16));
			height = checked((int)ReadUInt32BigEndian(bytes, 20));
			if (width <= 0 || height <= 0 || width > 16384 || height > 16384)
			{
				return false;
			}

			var bitDepth = bytes[24];
			var colorType = bytes[25];
			if (bitDepth != 8 && bitDepth != 16)
			{
				return false;
			}

			// RGB, RGBA, palette, grayscale — LoadImage handles expansion; we only need dimensions for allocation.
			return colorType is >= 0 and <= 6;
		}

		private static uint ReadUInt32BigEndian(byte[] bytes, int offset)
		{
			return ((uint)bytes[offset] << 24) | ((uint)bytes[offset + 1] << 16) |
			       ((uint)bytes[offset + 2] << 8) | bytes[offset + 3];
		}

		private static Texture2D LoadTexture(string path)
		{
			path = Path.GetFullPath(path);
			if (!File.Exists(path))
			{
				Plugin.LogSource?.LogWarning($"Temple swordsman prototype frame missing: {path}");
				return null;
			}

			var bytes = File.ReadAllBytes(path);

			if (TryReadPngIhdrDimensions(bytes, out var w, out var h))
			{
				// Prefer managed decode → LoadRawTextureData: Unity PNG APIs often fail on IL2CPP plugins.
				var viaRawPrimary = TryLoadTextureSoftwareRgba(path, bytes);
				if (viaRawPrimary != null)
				{
					if (!_loggedSoftwareRgbaUpload)
					{
						_loggedSoftwareRgbaUpload = true;
						Plugin.LogSource?.LogInfo(
							"Billboard PNGs: ImageSharp decode + Texture2D.LoadRawTextureData (primary path on IL2CPP).");
					}

					return FinalizePrototypeTexture(viaRawPrimary, path);
				}

				var sized = new Texture2D(w, h, TextureFormat.RGBA32, mipChain: false);
				if (TryLoadTextureImage(sized, bytes))
				{
					return FinalizePrototypeTexture(sized, path);
				}

				UnityEngine.Object.Destroy(sized);
			}

			var viaWeb = LoadTextureViaUnityWebRequest(path);
			if (viaWeb != null)
			{
				return FinalizePrototypeTexture(viaWeb, path);
			}

			var viaRawFallback = TryLoadTextureSoftwareRgba(path, bytes);
			if (viaRawFallback != null)
			{
				if (!_loggedSoftwareRgbaUpload)
				{
					_loggedSoftwareRgbaUpload = true;
					Plugin.LogSource?.LogInfo(
						"Billboard PNGs: ImageSharp decode + Texture2D.LoadRawTextureData (fallback after Unity paths).");
				}

				return FinalizePrototypeTexture(viaRawFallback, path);
			}

			Plugin.LogSource?.LogWarning($"Temple swordsman prototype failed to decode frame (all paths): {path}");
			return null;
		}

		/// <summary>
		/// Decode PNG in managed code and upload RGBA32 with <see cref="Texture2D.LoadRawTextureData"/> — bypasses broken
		/// <see cref="UnityEngine.ImageConversion.LoadImage"/> on some IL2CPP targets. Rows are flipped to Unity’s bottom-first convention.
		/// </summary>
		private static Texture2D TryLoadTextureSoftwareRgba(string path, byte[] bytes)
		{
			try
			{
				using var image = Image.Load<Rgba32>(bytes);
				var w = image.Width;
				var h = image.Height;
				if (w <= 0 || h <= 0)
				{
					return null;
				}

				var raw = new byte[w * h * 4];
				image.ProcessPixelRows(accessor =>
				{
					for (var imgY = 0; imgY < accessor.Height; imgY++)
					{
						var row = accessor.GetRowSpan(imgY);
						var destRow = h - 1 - imgY;
						var dest = raw.AsSpan(destRow * w * 4, w * 4);
						MemoryMarshal.AsBytes(row).CopyTo(dest);
					}
				});

				var tex = new Texture2D(w, h, TextureFormat.RGBA32, mipChain: false);
				tex.LoadRawTextureData(raw);
				tex.Apply(false, makeNoLongerReadable: false);
				return tex;
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"Software RGBA PNG load failed for '{path}': {ex.Message}");
				return null;
			}
		}

		private static Texture2D FinalizePrototypeTexture(Texture2D texture, string path)
		{
			texture.name = Path.GetFileName(path);
			texture.filterMode = FilterMode.Point;
			texture.wrapMode = TextureWrapMode.Clamp;
			return texture;
		}

		private static Texture2D LoadTextureViaUnityWebRequest(string absolutePath)
		{
			try
			{
				var url = new Uri(absolutePath).AbsoluteUri;
				var req = UnityWebRequestTexture.GetTexture(url, nonReadable: false);
				var op = req.SendWebRequest();
				while (!op.isDone)
				{
				}

				if (req.result != UnityWebRequest.Result.Success)
				{
					return null;
				}

				return DownloadHandlerTexture.GetContent(req);
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"UnityWebRequestTexture LoadTexture failed for '{absolutePath}': {ex.Message}");
				return null;
			}
		}

		private static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
		{
			if (texture == null || bytes == null || bytes.Length == 0)
			{
				return false;
			}

			try
			{
				return UnityEngine.ImageConversion.LoadImage(texture, bytes, markNonReadable: false);
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"ImageConversion.LoadImage exception: {ex.Message}");
				return TryLoadTextureImageLegacy(texture, bytes);
			}
		}

		private static bool TryLoadTextureImageLegacy(Texture2D texture, byte[] bytes)
		{
			var textureType = texture.GetType();
			foreach (var signature in new[]
				     {
					     new[] { typeof(byte[]) },
					     new[] { typeof(byte[]), typeof(bool) }
				     })
			{
				var loadImage = textureType.GetMethod(
					"LoadImage",
					BindingFlags.Instance | BindingFlags.Public,
					binder: null,
					types: signature,
					modifiers: null);
				if (loadImage == null)
				{
					continue;
				}

				var args = signature.Length == 1 ? new object[] { bytes } : new object[] { bytes, false };
				if (loadImage.Invoke(texture, args) is bool loaded && loaded)
				{
					return true;
				}
			}

			var imageConversionType = typeof(UnityEngine.ImageConversion);
			foreach (var method in imageConversionType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
			{
				if (!string.Equals(method.Name, "LoadImage", StringComparison.Ordinal))
				{
					continue;
				}

				var parameters = method.GetParameters();
				if (parameters.Length < 2 || parameters[0].ParameterType != textureType ||
				    parameters[1].ParameterType != typeof(byte[]))
				{
					continue;
				}

				var args = parameters.Length switch
				{
					2 => new object[] { texture, bytes },
					3 when parameters[2].ParameterType == typeof(bool) => new object[] { texture, bytes, false },
					_ => null
				};
				if (args == null)
				{
					continue;
				}

				var result = method.Invoke(null, args);
				if (result is bool loaded && loaded)
				{
					return true;
				}
			}

			return false;
		}
	}

	private sealed class PrototypeSequence
	{
		internal string Name;
		internal bool Loop;
		internal Texture2D[] Frames;
	}

	private sealed class PrototypeManifest
	{
		public PrototypeCanvas canvas;

		public PrototypeClip[] clips;
	}

	private sealed class PrototypeCanvas
	{
		public int width;

		public int height;
	}

	private sealed class PrototypeClip
	{
		public string name;

		public bool loop;

		public string[] files;
	}
}
