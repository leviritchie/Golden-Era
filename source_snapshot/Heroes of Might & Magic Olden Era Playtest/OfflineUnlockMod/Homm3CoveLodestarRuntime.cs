using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (docs/building_pass_20261122/cove.md, REVIEW §1): Lodestar, the Cove grail
/// (<c>Build_Golden_Calf</c> in <c>homm3_cove_city</c>): "all terrain counts as native" for the owner's battles.
///
/// Primary path (data): the grail row carries the native <c>{"type":"anyLandEqualNativeLandBonus"}</c> in
/// <c>sideBonuses</c>. Static trace on GameAssembly 26615913 (2026-11-22):
/// - Creature-level biome bonuses (<c>Unit$$bjos</c>, 0x1822E1BC0) count the battle as native when the side's
///   <c>TransferSide.sideBonuses</c> holds any parameterless bonus in its 0x108 collection (the any-land handler),
///   otherwise they use the unit's own native flag. The native bonus therefore covers creatures by itself.
/// - Side and hero biome bonuses (<c>euj$$bibm</c> via <c>dvz$$cjs</c>) read only the battle side's native flag
///   (<c>euj</c> +0xE8). The side constructor (<c>euj$$.ctor</c>, 0x18224ACC0) sets that flag from
///   "hero native biome == battlefield biome" and never consults the any-land bonus.
///
/// Fallback (this file, explicit, one switch <see cref="FallbackEnabled"/>): after <c>BattleLogic.Init</c>, for each
/// battle side whose owner has a Cove town with Lodestar, force the side native flag and every own stack's native
/// flag to true when they are false. Each battle logs which path was active per side: "native already" (flag was
/// true: home terrain, or the bonus already applied) or "fallback forced". Fail closed: an unreadable member or
/// owner leaves the battle unchanged.
/// </summary>
internal static class Homm3CoveLodestarRuntime
{
	internal const string BuildingSid = "Build_Golden_Calf";
	internal const string CitySid = "homm3_cove_city";

	/// <summary>The single switch for the plugin fallback. false = data row only (native bonus).</summary>
	internal const bool FallbackEnabled = true;

	private static ManualLogSource _log;
	private static bool _attempted;
	private static int _logged;

	private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
	private static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
	private static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
	private static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		if (!FallbackEnabled)
		{
			_log?.LogInfo("HoMM3 Cove Lodestar: plugin fallback OFF; native anyLandEqualNativeLandBonus row only.");
			return;
		}
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			Type logicType = null;
			foreach (var hint in GameSymbols.InfernoGating.BattleLogicTypeHints ?? Array.Empty<string>())
			{
				if (!string.IsNullOrWhiteSpace(hint) && hexAssembly.GetType(hint) is { } type)
				{
					logicType = type;
					break;
				}
			}
			if (logicType == null)
				throw new TypeLoadException("BattleLogic type not found");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			if (typeof(Unit).GetProperty(At(GameSymbols.CoveLodestar.UnitNativeMembers, 0), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not { CanWrite: true } unitFlag
			    || unitFlag.PropertyType != typeof(bool))
				throw new MissingMemberException("Unit native flag " + At(GameSymbols.CoveLodestar.UnitNativeMembers, 0));
			var postfix = typeof(Homm3CoveLodestarRuntime).GetMethod(nameof(PostfixBattleLogicInit), BindingFlags.Static | BindingFlags.NonPublic)
			              ?? throw new MissingMethodException(nameof(PostfixBattleLogicInit));
			if (!GameMember.IsHarmonyPatchCompatible(init, postfix, out var reason))
				throw new MissingMethodException("postfix incompatible for BattleLogic.Init: " + reason);
			harmony.Patch(init, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			_log?.LogInfo("HoMM3 Cove Lodestar registered: native anyLandEqualNativeLandBonus row + plugin fallback (side and stack native flags at battle init).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Cove Lodestar fallback NOT registered (native bonus row only: creature biome bonuses, not side/hero ones): "
			                 + ex.GetBaseException().Message);
		}
	}

	private static void PostfixBattleLogicInit(object __instance)
	{
		try
		{
			// side pointer -> (side, owns Lodestar, stacks)
			var sides = new Dictionary<IntPtr, (Il2CppObjectBase Side, List<Unit> Units)>();
			foreach (var unit in EnumerateUnits(__instance))
			{
				if (Homm3TowerArtificingRuntime.ReadMember(unit, new[] { FieldObjectSide }) is not Il2CppObjectBase side || side.Pointer == IntPtr.Zero)
					continue;
				if (!sides.TryGetValue(side.Pointer, out var entry))
					sides[side.Pointer] = entry = (side, new List<Unit>());
				if (!entry.Units.Exists(u => u.Pointer == unit.Pointer))
					entry.Units.Add(unit);
			}
			foreach (var (side, units) in sides.Values)
			{
				var transferSide = ReadTransferSide(side);
				if (transferSide == null || !Homm3TownBuildingReader.SideHasBuilding(transferSide, BuildingSid, CitySid))
					continue;
				var sideWasNative = ReadBool(side, GameSymbols.CoveLodestar.BattleSideNativeMembers, out var sideReadable);
				if (!sideReadable)
				{
					LogLimited("side " + transferSide.sideIdInWorld + " owns Lodestar but its native flag is unreadable; unchanged.");
					continue;
				}
				var sideForced = !sideWasNative && WriteBool(side, GameSymbols.CoveLodestar.BattleSideNativeMembers);
				var stacksForced = 0;
				foreach (var unit in units)
				{
					if (!ReadBool(unit, GameSymbols.CoveLodestar.UnitNativeMembers, out var unitReadable) && unitReadable
					    && WriteBool(unit, GameSymbols.CoveLodestar.UnitNativeMembers))
						stacksForced++;
				}
				_log?.LogInfo("HoMM3 Cove Lodestar: side " + transferSide.sideIdInWorld + " path="
				              + (sideWasNative ? "native already" : sideForced ? "fallback forced" : "fallback write failed")
				              + ", stacks forced " + stacksForced + "/" + units.Count + ".");
			}
		}
		catch (Exception ex)
		{
			LogLimited("Init postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>The battle side's <see cref="TransferSide"/> (the only member of that type on the side class).</summary>
	private static TransferSide ReadTransferSide(Il2CppObjectBase side)
	{
		foreach (var property in side.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.PropertyType == typeof(TransferSide) && property.GetIndexParameters().Length == 0)
				return property.GetValue(side) as TransferSide;
		}
		return null;
	}

	private static bool ReadBool(object target, string[] names, out bool readable)
	{
		readable = false;
		try
		{
			if (Homm3TowerArtificingRuntime.ReadMember(target, names) is bool value)
			{
				readable = true;
				return value;
			}
		}
		catch
		{
			// unreadable
		}
		return false;
	}

	private static bool WriteBool(object target, string[] names)
	{
		try
		{
			var property = target.GetType().GetProperty(At(names, 0), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (property == null || !property.CanWrite || property.PropertyType != typeof(bool))
				return false;
			property.SetValue(target, true);
			return property.GetValue(target) is true;
		}
		catch (Exception ex)
		{
			LogLimited("native flag write failed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static IEnumerable<Unit> EnumerateUnits(object logic)
	{
		var grid = Homm3TowerArtificingRuntime.ReadMember(logic, new[] { LogicGrid });
		if (Homm3TowerArtificingRuntime.ReadMember(grid, new[] { GridHexes }) is not Il2CppReferenceArray<BattleHex> hexes)
			yield break;
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit != null)
					yield return unit;
			}
		}
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 20)
			_log?.LogWarning("HoMM3 Cove Lodestar: " + message);
	}
}
