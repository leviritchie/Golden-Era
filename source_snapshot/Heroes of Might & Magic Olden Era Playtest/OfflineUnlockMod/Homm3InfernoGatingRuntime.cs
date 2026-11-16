using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using BattleHex = Hex.Session.Battle.Hex;
using DataHero = Hex.Session.Data.Hero;
using BuffDuration = Hex.Session.Data.BuffDuration;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Inferno Gating: reserved army slots enter the battle late, through a hellgate.
///
/// Design (owner, 2026-11-13):
/// - The hero reserves army slots (1; +1 Wider Gate; +1 Efficient Gate) on the adventure-map army strip
///   (<see cref="Homm3InfernoGatingArmyStripHud"/>). Gating is always open (2026-11-14: the spellbook toggle,
///   mode <see cref="ToggleMode"/>, is no longer granted; its handler stays for saves that learned it).
/// - Reserved stacks skip the opening deployment. They enter in round 2: Basic on a
///   random open hex, Advanced/Expert on a random open hex strictly inside the opponent's half (hexes within
///   half a hex of the board's centre line never count). Expert delays each stack until the moment it would
///   take its own turn in round 2 (its initiative slot), instead of the start of the round.
/// - Losing every deployed stack before the gate opens is a loss (native defeat check: only field units count).
/// - No eligible open hex: that stack never enters (it keeps its full count; it never fought).
/// - Rapid Gate: Haste (level 1) for 1 round on entry. Shielded Arrival: native Carapace barrier (1 charge) on entry.
/// - Open Gate (expert subskill): 2-Focus hero action, available only while stacks are pending, gates all now.
///
/// Mechanics (build 26615913, static disassembly):
/// - BattleLogic.Init clones the TransferBattle (Init +0x50 = TransferBattle.biir) and deploys the clone's
///   sides inside Init (epz.bhns). The prefix trims the reserved TransferUnits from the original sides so the
///   clone never deploys them; the postfix restores the original arrays and appends copies of the reserved
///   TransferUnits to the clone sides, so the battle result keeps them whether or not they enter.
/// - Entry spawns through the native FieldObject factory eop.bgyu(Unit, sid, stacks, sideWrapper, hex,
///   lifetime -1, returnToArmy true, isSummon false, spawnedInBattle true). The factory registers the unit,
///   raises ObjectSpawnedEventArgs (visuals + turn queue insertion by initiative). The spawned unit's
///   TransferUnit link (Unit._cphg) is pointed at the clone-side copy so survivors write back to that slot.
/// - Round/turn timing: RoundStarted (eoi _66) and ActionEnded (eoi PDM_21) postfixes. Turn queue ewd
///   (BattleLogic +0xb8): round counter, current, list0 (still to act this round), list1 (Wait).
///
/// Proof tier: source + static disassembly + build. Runtime unproven until the owner tests in game.
/// </summary>
internal static class Homm3InfernoGatingRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_inferno";
	internal const string ToggleMode = "homm3_inferno_gating_toggle";
	internal const string OpenBuffSid = "homm3_inferno_gating_open";
	internal const string SlotBitPrefix = "homm3_inferno_gating_slot_";
	internal const int ArmySlots = 7;
	internal const string WiderGateSid = "sub_skill_faction_homm3_inferno_gating_more_units";
	internal const string RapidGateSid = "sub_skill_faction_homm3_inferno_gating_fast_gate";
	internal const string EfficientGateSid = "sub_skill_faction_homm3_inferno_gating_focus_efficiency";
	internal const string OpenGateSubSkillSid = "sub_skill_faction_homm3_inferno_gating_any_tile";
	internal const string ShieldedArrivalSid = "sub_skill_faction_homm3_inferno_gating_barrier";
	internal const string OpenGateAbilitySid = "skill_faction_homm3_inferno_ability_open_gate";
	internal const string BarrierBuffSid = "homm3_inferno_gating_barrier_bonus";
	internal const string HasteBuffSid = "magic_haste_effect_1";
	private const string NativeNecromancyMechType = "change_use_necromancy";
	private const int EntryRound = 2;

	// Live interop member names (build 26615913) live in GameSymbols.InfernoGating (scoped by the current-build override).
	private static class Pins
	{
		private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
		internal static string[] BattleLogicTypes => GameSymbols.InfernoGating.BattleLogicTypeHints;
		internal static string LogicFactory => At(GameSymbols.InfernoGating.LogicFactoryMembers, 0);
		internal static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
		internal static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
		internal static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
		internal static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
		internal static string LogicQueue => At(GameSymbols.InfernoGating.LogicQueueMembers, 0);
		internal static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
		internal static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
		internal static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
		internal static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
		internal static string QueueRound => At(GameSymbols.InfernoGating.QueueRoundMembers, 0);
		internal static string QueueToAct => At(GameSymbols.InfernoGating.QueueToActMembers, 0);
		internal static string UnitTransferUnit => At(GameSymbols.InfernoGating.UnitTransferUnitMembers, 0);
		internal static string UnitData => At(GameSymbols.InfernoGating.UnitDataMembers, 0);
		internal static string UnitStat => At(GameSymbols.InfernoGating.UnitStatMembers, 0);
		internal static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
		internal static string UnitDataAlive => At(GameSymbols.InfernoGating.UnitDataAliveMembers, 0);
		internal static string FactorySpawn => At(GameSymbols.InfernoGating.FactorySpawnMembers, 0);
		internal static string[] HeroAbilityTypes => GameSymbols.InfernoGating.HeroAbilityTypeHints;
		internal static string HeroAbilityUsable => At(GameSymbols.InfernoGating.HeroAbilityUsableMembers, 0);
		internal static string HeroAbilityUsableWithFocus => At(GameSymbols.InfernoGating.HeroAbilityUsableMembers, 1);
		internal const string HeroAbilitySid = "sid";
		internal static string HeroAbilitySide => At(GameSymbols.InfernoGating.HeroAbilitySideMembers, 0);
	}

	private sealed class PendingStack
	{
		internal int SideIndex;
		internal int Slot;
		internal string Sid;
		internal int Stacks;
		internal int ModelIndex;
		internal int Initiative;
		internal TransferUnit CloneUnit;
		internal bool Done;
	}

	private sealed class GatingSide
	{
		internal int SideIndex;
		internal int Rank;
		internal bool Rapid;
		internal bool Shielded;
		internal bool OpenGate;
		internal string HeroDescription;
		internal object SideWrapper;
		internal int HomeSign; // -1: home on the low-x half, +1: home on the high-x half, 0 unknown
		internal readonly List<PendingStack> Pending = new();
	}

	private sealed class BattleState
	{
		internal object Logic;
		internal IntPtr HubPointer;
		internal int Serial;
		internal readonly List<GatingSide> Sides = new();
		internal bool HomeResolved;
	}

	private sealed class InitState
	{
		internal readonly List<KeyValuePair<TransferSide, Il2CppReferenceArray<TransferUnit>>> Originals = new();
		internal readonly List<GatingSide> Sides = new();
	}

	private static readonly object Gate = new();
	private static readonly List<BattleState> Battles = new();
	private static readonly System.Random Rng = new();
	private static ManualLogSource _log;
	private static PropertyInfo[] _transferBattleProperties;
	private static bool _loggedSnapshot;
	private static bool _attempted;
	private static bool _stateRegistered;
	private static bool _battleRegistered;
	private static int _serial;
	private static int _logged;

	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAddMethod;
	private static MethodInfo _buffRemoveMethod;
	private static MethodInfo _buffGetMethod;
	private static MethodInfo _spawnMethod;

	internal static bool StateRegistered => _stateRegistered;
	internal static bool BattleRegistered => _battleRegistered;

	// ------------------------------------------------------------------ registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		var hexAssembly = typeof(TransferBattle).Assembly;

		// Stage 1: hero bridge + hero buff manager + spellbook toggle.
		try
		{
			var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			var worldHeroType = ResolveTypeByHints(hexAssembly, GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints, "homm3.inferno.gating.worldHero");
			_worldHeroLogicHeroProperty = RequireProperty(worldHeroType, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, logicHeroType);
			_logicHeroDataHeroGetter = RequireMethod(logicHeroType, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints, typeof(DataHero), Type.EmptyTypes);
			_buffManagerProperty = RequireProperty(logicHeroType, GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], null);
			var managerType = _buffManagerProperty.PropertyType;
			_buffAddMethod = RequireMethod(managerType, GameSymbols.DungeonCaptives.BuffManagerAdd.NameHints, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) });
			_buffRemoveMethod = RequireMethod(managerType, GameSymbols.DungeonCaptives.BuffManagerRemove.NameHints, typeof(void), new[] { typeof(string) });
			_buffGetMethod = RequireMethod(managerType, GameSymbols.DungeonCaptives.BuffManagerGet.NameHints, null, new[] { typeof(string) });

			var handlerType = ResolveTypeByHints(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.inferno.gating.necromancyHandler");
			var castMethod = RequireMethod(handlerType, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast.NameHints, typeof(bool), Type.EmptyTypes);
			_handlerWorldHeroProperty = RequireProperty(handlerType, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, worldHeroType);
			Patch(harmony, castMethod, nameof(PrefixNecromancyWorldMagicCast), null);
			_stateRegistered = true;
			_log?.LogInfo("HoMM3 Inferno Gating [state] registered: toggle prefix on " + FormatMethod(castMethod) + ", hero-buff slot state.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating [state] NOT registered (fail closed: no toggle, no reservations, no gated battles): " + ex.GetBaseException().Message);
			return;
		}

		// Stage 2: battle (deployment trim, round-2 entry, Expert turn timing).
		try
		{
			var logicType = ResolveTypeByHints(hexAssembly, Pins.BattleLogicTypes, "homm3.inferno.gating.battleLogic");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var factoryProperty = RequireProperty(logicType, Pins.LogicFactory, null);
			_spawnMethod = ResolveSpawnMethod(factoryProperty.PropertyType);
			foreach (var name in new[] { Pins.LogicBattleClone, Pins.LogicGrid, Pins.LogicHubs, Pins.LogicState, Pins.LogicQueue })
				RequireProperty(logicType, name, null);

			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs, null).PropertyType, Pins.HubsRoundHub, null).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			var actionEnded = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionEndedDispatcher);

			Patch(harmony, init, nameof(PrefixBattleLogicInit), nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, null, nameof(PostfixRoundStarted));
			Patch(harmony, actionEnded, null, nameof(PostfixActionEnded));
			_battleRegistered = true;
			_log?.LogInfo("HoMM3 Inferno Gating [battle] registered: Init trim/restore, entry via " + _spawnMethod.Name.Substring(0, 40) + "..., RoundStarted/ActionEnded timing.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating [battle] NOT registered (reserved stacks deploy normally): " + ex.GetBaseException().Message);
			return;
		}

		// Stage 3: Open Gate (cast observation + availability). Optional: failure leaves the action inert.
		try
		{
			var patched = 0;
			foreach (var typeHint in GameSymbols.BattleEventLaws.BattleEventDispatcherTypeHints)
			{
				var type = GameMember.FindType(GameSymbols.BattleEventLaws.BattleEventDispatcherTypeId + "." + typeHint, typeHint) ?? hexAssembly.GetType(typeHint);
				if (type == null)
					continue;
				foreach (var methodName in GameSymbols.BattleEventLaws.BattleEventDispatch.NameHints)
				{
					if (string.IsNullOrWhiteSpace(methodName))
						continue;
					foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
					{
						if (method.Name == methodName && method.ReturnType == typeof(void) && method.GetParameters().Length == 2)
						{
							Patch(harmony, method, null, nameof(PostfixBattleEventDispatch));
							patched++;
							break;
						}
					}
				}
			}
			var abilityType = ResolveTypeByHints(hexAssembly, Pins.HeroAbilityTypes, "homm3.inferno.gating.heroAbility");
			foreach (var name in new[] { Pins.HeroAbilityUsable, Pins.HeroAbilityUsableWithFocus })
			{
				foreach (var method in abilityType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
				{
					if (method.Name == name && method.ReturnType == typeof(bool))
					{
						Patch(harmony, method, null, nameof(PostfixHeroAbilityUsable));
						patched++;
						break;
					}
				}
			}
			_log?.LogInfo("HoMM3 Inferno Gating [open gate] registered: " + patched + " patch(es) (cast dispatch + availability).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Inferno Gating [open gate] NOT registered (Open Gate does nothing): " + ex.GetBaseException().Message);
		}
	}

	private static MethodInfo ResolveSpawnMethod(Type factoryType)
	{
		foreach (var method in factoryType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!string.Equals(method.Name, Pins.FactorySpawn, StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 11 && ps[0].ParameterType == typeof(EFieldObjectType) && ps[1].ParameterType == typeof(string)
			    && ps[4].ParameterType == typeof(BattleHex) && ps[6].ParameterType == typeof(bool))
				return method;
		}
		throw new MissingMethodException("eop.bgyu FieldObject factory not found on " + factoryType.FullName);
	}

	// ------------------------------------------------------------------ adventure-map state (hero buffs)

	internal static object ResolveLogicHeroFromWorldHero(object worldHero)
	{
		if (worldHero == null || _worldHeroLogicHeroProperty == null || !_worldHeroLogicHeroProperty.DeclaringType.IsInstanceOfType(worldHero))
			return null;
		return _worldHeroLogicHeroProperty.GetValue(worldHero);
	}

	internal static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	internal static int ResolveRank(DataHero dataHero) => Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, FactionSkillSid);

	internal static int ResolveAllowedSlots(DataHero dataHero)
	{
		if (ResolveRank(dataHero) <= 0)
			return 0;
		var allowed = 1;
		if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, WiderGateSid))
			allowed++;
		if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, EfficientGateSid))
			allowed++;
		return allowed;
	}

	/// <summary>
	/// Reads the persisted Gating state from the hero's data buffs (works on the map and at battle start).
	/// Gating is always open (owner, 2026-11-14: the spellbook toggle was redundant with releasing every slot), so
	/// <paramref name="open"/> is always true; a legacy "open" buff from older saves is ignored.
	/// </summary>
	internal static bool ReadState(DataHero dataHero, out bool open, out int slotMask)
	{
		open = true;
		slotMask = 0;
		var list = dataHero?.buffs?.list;
		if (list == null)
			return dataHero != null;
		for (var i = 0; i < list.Count; i++)
		{
			var sid = DeobfInteropCompat.GetStringMember(list[i], GameSymbols.DungeonCaptives.DataBuffSidMembers)?.Trim();
			if (string.IsNullOrEmpty(sid))
				continue;
			if (sid.StartsWith(SlotBitPrefix, StringComparison.Ordinal)
			         && int.TryParse(sid.Substring(SlotBitPrefix.Length), out var slot) && slot >= 0 && slot < ArmySlots)
				slotMask |= 1 << slot;
		}
		return true;
	}

	/// <summary>Toggles one reserved slot; refuses to exceed the hero's allowed slot count. Returns the new mask.</summary>
	internal static bool TryToggleSlot(object logicHero, int slot, out int newMask, out string failReason)
	{
		newMask = 0;
		var dataHero = ResolveDataHero(logicHero);
		if (dataHero == null || slot < 0 || slot >= ArmySlots)
		{
			failReason = "hero unresolved or slot out of range";
			return false;
		}
		ReadState(dataHero, out _, out var mask);
		var reserved = (mask & (1 << slot)) != 0;
		if (!reserved && CountBits(mask) >= ResolveAllowedSlots(dataHero))
		{
			failReason = "all " + ResolveAllowedSlots(dataHero) + " gating slot(s) already reserved";
			newMask = mask;
			return false;
		}
		if (!TrySetBuff(logicHero, SlotBitPrefix + slot, !reserved, out failReason))
			return false;
		newMask = reserved ? mask & ~(1 << slot) : mask | (1 << slot);
		_log?.LogInfo("HoMM3 Inferno Gating slot " + slot + (reserved ? " released" : " reserved") + " for " + (dataHero.configSid ?? "?") + "; mask=" + newMask + ".");
		return true;
	}

	private static bool TrySetBuff(object logicHero, string sid, bool wanted, out string failReason)
	{
		failReason = null;
		try
		{
			if (logicHero == null || !_buffManagerProperty.DeclaringType.IsInstanceOfType(logicHero))
			{
				failReason = "logic hero missing";
				return false;
			}
			var manager = _buffManagerProperty.GetValue(logicHero);
			if (manager == null)
			{
				failReason = "hero buff manager null";
				return false;
			}
			var present = _buffGetMethod.Invoke(manager, new object[] { sid }) != null;
			if (present == wanted)
				return true;
			if (wanted)
			{
				var durations = new Il2CppReferenceArray<BuffDuration>(1);
				durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
				_buffAddMethod.Invoke(manager, new object[] { sid, durations });
			}
			else
			{
				_buffRemoveMethod.Invoke(manager, new object[] { sid });
			}
			if ((_buffGetMethod.Invoke(manager, new object[] { sid }) != null) != wanted)
			{
				failReason = sid + (wanted ? " add did not stick (Core row missing?)" : " remove did not stick (not dispellable?)");
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			failReason = sid + " threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool PrefixNecromancyWorldMagicCast(object __instance, ref bool __result)
	{
		MagicSetting setting;
		try
		{
			setting = ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
		}
		catch
		{
			return true;
		}
		if (setting == null || !string.Equals(setting.mechType, NativeNecromancyMechType, StringComparison.Ordinal)
		    || setting.parameters == null || setting.parameters.Length < 1
		    || !string.Equals(setting.parameters[0], ToggleMode, StringComparison.Ordinal))
			return true;

		__result = false;
		try
		{
			var worldHero = _handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(__instance) ? _handlerWorldHeroProperty.GetValue(__instance) : null;
			var logicHero = ResolveLogicHeroFromWorldHero(worldHero);
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null)
			{
				_log?.LogError("HoMM3 Inferno Gating toggle refused: casting hero unresolved.");
				return false;
			}
			ReadState(dataHero, out var open, out var mask);
			if (!TrySetBuff(logicHero, OpenBuffSid, !open, out var fail))
			{
				_log?.LogError("HoMM3 Inferno Gating toggle failed: " + fail);
				return false;
			}
			__result = true;
			_log?.LogInfo("HoMM3 Inferno Gating " + (open ? "closed" : "opened") + " for " + (dataHero.configSid ?? "?") + " (reserved mask " + mask
			              + ", allowed " + ResolveAllowedSlots(dataHero) + ").");
			Homm3InfernoGatingArmyStripHud.NotifyStateChanged();
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating toggle failed closed: " + ex.GetBaseException().Message);
		}
		return false;
	}

	// ------------------------------------------------------------------ battle start

	private static void PrefixBattleLogicInit(TransferBattle __1, ref InitState __state)
	{
		__state = null;
		try
		{
			if (__1?.sides == null)
				return;
			for (var sideIndex = 0; sideIndex < __1.sides.Length; sideIndex++)
			{
				var side = __1.sides[sideIndex];
				if (side?.units == null || side.logicHero == null)
					continue;
				var dataHero = ResolveDataHero(side.logicHero);
				var rank = ResolveRank(dataHero);
				if (rank <= 0 || !ReadState(dataHero, out var open, out var mask) || !open || mask == 0)
					continue;
				var allowed = ResolveAllowedSlots(dataHero);
				var kept = new List<TransferUnit>();
				var reserved = new List<TransferUnit>();
				foreach (var unit in side.units)
				{
					if (unit == null)
						continue;
					var isReserved = unit.slotPos >= 0 && unit.slotPos < ArmySlots && (mask & (1 << unit.slotPos)) != 0 && reserved.Count < allowed && unit.stacks > 0;
					(isReserved ? reserved : kept).Add(unit);
				}
				var heroText = (dataHero.configSid ?? "?") + " side " + sideIndex;
				if (reserved.Count == 0)
					continue;
				if (kept.Count == 0)
				{
					_log?.LogInfo("HoMM3 Inferno Gating skipped for " + heroText + ": every stack is reserved, so the whole army deploys normally.");
					continue;
				}
				if (!_loggedSubSkillRows)
				{
					_loggedSubSkillRows = true;
					_log?.LogInfo("HoMM3 Inferno Gating subskill rows for " + heroText + ": "
					              + Homm3DungeonDraconicDominionHook.DescribeSubSkillRows(dataHero, "sub_skill_faction_homm3_inferno_gating_")
					              + " (only non-Inactive rows count).");
				}
				var gating = new GatingSide
				{
					SideIndex = sideIndex,
					Rank = rank,
					Rapid = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, RapidGateSid),
					Shielded = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, ShieldedArrivalSid),
					OpenGate = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, OpenGateSubSkillSid),
					HeroDescription = heroText,
				};
				foreach (var unit in reserved)
				{
					gating.Pending.Add(new PendingStack
					{
						SideIndex = sideIndex,
						Slot = unit.slotPos,
						Sid = unit.configSid,
						Stacks = unit.stacks,
						ModelIndex = unit.modelIndex,
						Initiative = ReadConfigInitiative(unit),
					});
				}
				__state ??= new InitState();
				__state.Originals.Add(new KeyValuePair<TransferSide, Il2CppReferenceArray<TransferUnit>>(side, side.units));
				__state.Sides.Add(gating);
				var trimmed = new Il2CppReferenceArray<TransferUnit>(kept.Count);
				for (var i = 0; i < kept.Count; i++)
					trimmed[i] = kept[i];
				side.units = trimmed;
			}
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating Init prefix failed closed: " + ex.GetBaseException().Message);
			RestoreOriginals(__state);
			__state = null;
		}
	}

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1, ref InitState __state)
	{
		if (__state == null)
			return;
		RestoreOriginals(__state);
		try
		{
			var clone = ReadProperty(__instance, Pins.LogicBattleClone) as TransferBattle;
			var hubs = ReadProperty(__instance, Pins.LogicHubs);
			var hub = ReadProperty(hubs, Pins.HubsRoundHub) as Il2CppObjectBase;
			if (clone?.sides == null || hub == null)
				throw new InvalidOperationException("battle clone or round hub missing after Init");
			var battle = new BattleState { Logic = __instance, HubPointer = hub.Pointer, Serial = ++_serial };
			var wrappers = ReadProperty(ReadProperty(__instance, Pins.LogicState), Pins.StateSideWrappers) as Il2CppArrayBase<Il2CppSystem.Object>;
			foreach (var gating in __state.Sides)
			{
				if (gating.SideIndex >= clone.sides.Length || clone.sides[gating.SideIndex] == null)
					continue;
				var cloneSide = clone.sides[gating.SideIndex];
				gating.SideWrapper = FindSideWrapper(__instance, cloneSide);
				if (gating.SideWrapper == null)
				{
					_log?.LogError("HoMM3 Inferno Gating: side wrapper for " + gating.HeroDescription + " not found; reserved stacks return unfought.");
				}
				// The clone was built from the trimmed side: append copies so the result keeps every reserved stack.
				var units = cloneSide.units;
				var next = new Il2CppReferenceArray<TransferUnit>((units?.Length ?? 0) + gating.Pending.Count);
				var n = 0;
				if (units != null)
				{
					foreach (var unit in units)
						next[n++] = unit;
				}
				foreach (var pending in gating.Pending)
				{
					var copy = new TransferUnit(pending.Sid, pending.Stacks, pending.Slot) { modelIndex = pending.ModelIndex };
					pending.CloneUnit = copy;
					next[n++] = copy;
				}
				cloneSide.units = next;
				if (gating.SideWrapper != null)
					battle.Sides.Add(gating);
				_log?.LogInfo("HoMM3 Inferno Gating armed for " + gating.HeroDescription + " rank " + gating.Rank + ": "
				              + DescribePending(gating) + (gating.Rapid ? " +Rapid" : "") + (gating.Shielded ? " +Shielded" : "") + (gating.OpenGate ? " +OpenGate" : "") + ".");
			}
			SyncStartSnapshot(__instance, __1, clone, __state);
			lock (Gate)
			{
				Battles.RemoveAll(b => ReferenceEquals(b.Logic, __instance));
				if (battle.Sides.Count > 0)
					Battles.Add(battle);
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating Init postfix failed (reserved stacks stay home, unfought): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// The results window diffs the battle's start snapshot against the final army. When Init built that snapshot
	/// from the trimmed sides, reserved stacks read as gained (+N) and their casualties never balance; give the
	/// snapshot the same reserved rows the working clone got.
	/// </summary>
	private static void SyncStartSnapshot(object logic, TransferBattle original, TransferBattle clone, InitState state)
	{
		try
		{
			var started = ReadStartedBattle(logic, clone);
			string kind;
			if (started == null)
				kind = "missing";
			else if (started.Pointer == clone.Pointer)
				kind = "same as the working clone";
			else if (original != null && started.Pointer == original.Pointer)
				kind = "the original (restored)";
			else
			{
				kind = "a separate copy";
				foreach (var gating in state.Sides)
				{
					if (started.sides == null || gating.SideIndex >= started.sides.Length || started.sides[gating.SideIndex] == null)
						continue;
					var side = started.sides[gating.SideIndex];
					var units = side.units;
					var missing = new List<PendingStack>();
					foreach (var pending in gating.Pending)
					{
						var present = false;
						if (units != null)
						{
							foreach (var u in units)
							{
								if (u != null && u.slotPos == pending.Slot && u.configSid == pending.Sid)
								{
									present = true;
									break;
								}
							}
						}
						if (!present)
							missing.Add(pending);
					}
					if (missing.Count == 0)
						continue;
					var next = new Il2CppReferenceArray<TransferUnit>((units?.Length ?? 0) + missing.Count);
					var n = 0;
					if (units != null)
					{
						foreach (var u in units)
							next[n++] = u;
					}
					foreach (var pending in missing)
						next[n++] = new TransferUnit(pending.Sid, pending.Stacks, pending.Slot) { modelIndex = pending.ModelIndex };
					side.units = next;
					kind += "; added " + missing.Count + " reserved row(s) to side " + gating.SideIndex;
				}
			}
			if (!_loggedSnapshot)
			{
				_loggedSnapshot = true;
				_log?.LogInfo("HoMM3 Inferno Gating start snapshot: " + kind + ".");
			}
		}
		catch (Exception ex)
		{
			LogLimited("start snapshot sync failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Battle-result diagnostic: one line per gating side, start snapshot vs final army (sid x stacks @slot).</summary>
	internal static void ObserveBeforeBattleResult(object logic)
	{
		try
		{
			BattleState battle = null;
			lock (Gate)
			{
				foreach (var b in Battles)
				{
					if (b.Logic is Il2CppObjectBase a && logic is Il2CppObjectBase c && a.Pointer == c.Pointer)
						battle = b;
				}
			}
			if (battle == null)
				return;
			var final = ReadProperty(logic, Pins.LogicBattleClone) as TransferBattle;
			var started = ReadStartedBattle(logic, final);
			foreach (var side in battle.Sides)
			{
				_log?.LogInfo("HoMM3 Inferno Gating result " + side.HeroDescription + ": start [" + DescribeUnits(started, side.SideIndex) + "] end ["
				              + DescribeUnits(final, side.SideIndex) + "] gated [" + DescribePending(side) + "].");
			}
		}
		catch (Exception ex)
		{
			LogLimited("result diagnostic failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// BattleLogic's other TransferBattle (beside the working clone): the start-of-battle snapshot. Found by type so no
	/// extra obfuscated member name is needed.
	/// </summary>
	private static TransferBattle ReadStartedBattle(object logic, TransferBattle clone)
	{
		if (logic == null)
			return null;
		_transferBattleProperties ??= Array.FindAll(logic.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic),
			p => p.PropertyType == typeof(TransferBattle) && p.GetIndexParameters().Length == 0 && p.CanRead);
		foreach (var property in _transferBattleProperties)
		{
			if (property.GetValue(logic) is TransferBattle tb && (clone == null || tb.Pointer != clone.Pointer))
				return tb;
		}
		return null;
	}

	private static string DescribeUnits(TransferBattle battle, int sideIndex)
	{
		if (battle?.sides == null || sideIndex >= battle.sides.Length || battle.sides[sideIndex]?.units == null)
			return "?";
		var parts = new List<string>();
		foreach (var u in battle.sides[sideIndex].units)
		{
			if (u != null)
				parts.Add(u.configSid + "x" + u.stacks + "@" + u.slotPos);
		}
		return string.Join(", ", parts);
	}

	private static void RestoreOriginals(InitState state)
	{
		if (state == null)
			return;
		foreach (var pair in state.Originals)
		{
			try
			{
				pair.Key.units = pair.Value;
			}
			catch (Exception ex)
			{
				_log?.LogError("HoMM3 Inferno Gating could not restore an original army array: " + ex.GetBaseException().Message);
			}
		}
	}

	private static object FindSideWrapper(object logic, TransferSide side)
	{
		var wrappers = ReadProperty(ReadProperty(logic, Pins.LogicState), Pins.StateSideWrappers);
		if (wrappers is not System.Collections.IEnumerable enumerable)
			return null;
		foreach (var wrapper in enumerable)
		{
			if (ReadProperty(wrapper, Pins.SideWrapperTransferSide) is TransferSide ts && ts.Pointer == side.Pointer)
				return wrapper;
		}
		return null;
	}

	// ------------------------------------------------------------------ timing

	private static BattleState FindBattleByHub(object hub)
	{
		if (hub is not Il2CppObjectBase obj)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.HubPointer == obj.Pointer)
					return battle;
			}
		}
		return null;
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args)
				return;
			var round = args.roundNumber;
			if (!battle.HomeResolved && round >= 1)
				ResolveHomeHalves(battle);
			if (round < EntryRound)
				return;
			foreach (var side in battle.Sides)
			{
				foreach (var pending in side.Pending)
				{
					if (pending.Done)
						continue;
					// Basic/Advanced: start of round 2. Expert: only stacks faster than the unit that already holds the
					// first turn enter now (they act next); the rest wait for their slot. Past round 2: never later.
					var current = args.target;
					if (side.Rank < 3 || round > EntryRound || current == null || pending.Initiative > ReadUnitInitiative(current))
						Enter(battle, side, pending, side.Rank < 3 || round > EntryRound ? "round " + round + " start" : "round 2, faster than the opening unit");
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixActionEnded(object __instance)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null)
				return;
			var queue = ReadProperty(battle.Logic, Pins.LogicQueue);
			if (queue == null || ReadInt(queue, Pins.QueueRound) != EntryRound)
				return;
			Unit next = null;
			if (ReadProperty(queue, Pins.QueueToAct) is Il2CppSystem.Collections.Generic.List<Unit> toAct)
			{
				for (var i = 0; i < toAct.Count; i++)
				{
					var unit = toAct[i];
					if (unit != null && IsAlive(unit))
					{
						next = unit;
						break;
					}
				}
			}
			var nextInitiative = next == null ? int.MinValue : ReadUnitInitiative(next);
			foreach (var side in battle.Sides)
			{
				if (side.Rank < 3)
					continue;
				foreach (var pending in side.Pending)
				{
					if (!pending.Done && pending.Initiative >= nextInitiative)
						Enter(battle, side, pending, next == null ? "round 2, every remaining unit is waiting" : "round 2, its initiative slot (" + pending.Initiative + " >= next " + nextInitiative + ")");
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("ActionEnded handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ Open Gate

	private static void PostfixBattleEventDispatch(object[] __args)
	{
		try
		{
			if (__args == null)
				return;
			foreach (var arg in __args)
			{
				if (arg == null || !Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(arg, out var info, out _) || !info.HasAbilityName(OpenGateAbilitySid))
					continue;
				var wrapperPtr = (info.Caster as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
				List<(BattleState, GatingSide)> targets = new();
				lock (Gate)
				{
					foreach (var battle in Battles)
					{
						foreach (var side in battle.Sides)
						{
							if (side.OpenGate && HasPending(side) && (wrapperPtr == IntPtr.Zero || (side.SideWrapper as Il2CppObjectBase)?.Pointer == wrapperPtr || CasterBelongsToSide(info.Caster, side)))
								targets.Add((battle, side));
						}
					}
				}
				if (targets.Count == 0)
				{
					LogLimited("Open Gate cast observed but no pending gated stacks matched the caster (" + info + ").");
					continue;
				}
				foreach (var (battle, side) in targets)
				{
					foreach (var pending in side.Pending)
					{
						if (!pending.Done)
							Enter(battle, side, pending, "Open Gate");
					}
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("Open Gate cast handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool CasterBelongsToSide(object caster, GatingSide side)
	{
		if (caster == null || side.SideWrapper is not Il2CppObjectBase wrapper)
			return false;
		var casterSide = ReadProperty(caster, Pins.FieldObjectSide) ?? ReadProperty(caster, Pins.HeroAbilitySide);
		return casterSide is Il2CppObjectBase obj && obj.Pointer == wrapper.Pointer;
	}

	private static void PostfixHeroAbilityUsable(object __instance, ref bool __result)
	{
		if (!__result)
			return;
		try
		{
			if (!string.Equals(ReadProperty(__instance, Pins.HeroAbilitySid) as string, OpenGateAbilitySid, StringComparison.Ordinal))
				return;
			var wrapper = ReadProperty(__instance, Pins.HeroAbilitySide) as Il2CppObjectBase;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					foreach (var side in battle.Sides)
					{
						if (wrapper != null && (side.SideWrapper as Il2CppObjectBase)?.Pointer == wrapper.Pointer && HasPending(side))
							return;
					}
				}
			}
			__result = false;
		}
		catch
		{
			__result = false;
		}
	}

	private static bool HasPending(GatingSide side)
	{
		foreach (var pending in side.Pending)
		{
			if (!pending.Done)
				return true;
		}
		return false;
	}

	// ------------------------------------------------------------------ entry

	private static void Enter(BattleState battle, GatingSide side, PendingStack pending, string reason)
	{
		pending.Done = true;
		try
		{
			var grid = ReadProperty(battle.Logic, Pins.LogicGrid);
			var hexes = ReadProperty(grid, Pins.GridHexes) as Il2CppReferenceArray<BattleHex>;
			var factory = ReadProperty(battle.Logic, Pins.LogicFactory);
			if (hexes == null || factory == null)
			{
				LogLimited("entry of " + pending.Sid + " refused: grid or factory missing.");
				return;
			}
			if (!battle.HomeResolved)
				ResolveHomeHalves(battle);
			var candidates = CollectEntryHexes(hexes, side.Rank >= 2 ? side.HomeSign : 0, side.Rank >= 2);
			if (candidates.Count == 0)
			{
				_log?.LogInfo("HoMM3 Inferno Gating: no eligible open hex for " + pending.Sid + " x" + pending.Stacks + " (" + side.HeroDescription + "); the stack never enters.");
				return;
			}
			Unit spawned = null;
			BattleHex hex = null;
			object portal = null;
			for (var attempt = 0; attempt < 6 && spawned == null && candidates.Count > 0; attempt++)
			{
				var pick = Rng.Next(candidates.Count);
				hex = candidates[pick];
				candidates.RemoveAt(pick);
				portal = Homm3InfernoGatingPortal.Prepare(pending.Sid, hex.position, side.HomeSign);
				var result = _spawnMethod.Invoke(factory, new object[]
				{
					EFieldObjectType.Unit, pending.Sid, pending.Stacks, side.SideWrapper, hex, -1, true, false, true, null, null,
				});
				spawned = (result as Il2CppObjectBase)?.TryCast<Unit>();
				if (spawned == null)
				{
					Homm3InfernoGatingPortal.Cancel(portal);
					portal = null;
				}
			}
			if (spawned == null)
			{
				_log?.LogWarning("HoMM3 Inferno Gating: the native factory refused every hex tried for " + pending.Sid + "; the stack never enters.");
				return;
			}
			try
			{
				WriteProperty(spawned, Pins.UnitTransferUnit, pending.CloneUnit);
			}
			catch (Exception ex)
			{
				_log?.LogError("HoMM3 Inferno Gating: TransferUnit link failed for " + pending.Sid + " (survivors may merge into another slot): " + ex.GetBaseException().Message);
			}
			var applied = new List<string>();
			if (side.Shielded)
				applied.Add(TryBuff(spawned, BarrierBuffSid, 1) ? "barrier" : "barrier FAILED");
			if (side.Rapid)
				applied.Add(TryBuff(spawned, HasteBuffSid, 0) ? "haste" : "haste FAILED");
			Homm3InfernoGatingPortal.Play(portal, hex.position);
			_log?.LogInfo("HoMM3 Inferno Gating entry: " + pending.Sid + " x" + pending.Stacks + " (slot " + pending.Slot + ") for " + side.HeroDescription
			              + " at hex (" + hex.x + "," + hex.z + ") — " + reason + (applied.Count > 0 ? "; " + string.Join(", ", applied) : "") + ".");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Inferno Gating entry of " + pending.Sid + " failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <param name="charges">native buff value; a "bubble" (Carapace) barrier negates one hit per charge.</param>
	private static bool TryBuff(Unit unit, string sid, int charges)
	{
		if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, sid, unit, 1, 1, charges, true, out _, out var fail))
			return true;
		LogLimited("entry buff " + sid + " failed: " + fail);
		return false;
	}

	/// <summary>
	/// Open hexes: on the board, not blocked, no field object at all. With <paramref name="enemyHalfOnly"/>,
	/// only hexes more than half a hex past the board's centre line, on the side away from home.
	/// </summary>
	private static List<BattleHex> CollectEntryHexes(Il2CppReferenceArray<BattleHex> hexes, int homeSign, bool enemyHalfOnly)
	{
		var open = new List<BattleHex>();
		float minX = float.MaxValue, maxX = float.MinValue;
		var rowStep = float.MaxValue;
		foreach (var hex in hexes)
		{
			if (hex == null || hex.blockedByMap || hex.blockedFromAll)
				continue;
			var x = hex.position.x;
			minX = Math.Min(minX, x);
			maxX = Math.Max(maxX, x);
			if (hex.tempBlocked)
				continue;
			var objects = hex.fieldObjects;
			if (objects != null && objects.Count > 0)
				continue;
			open.Add(hex);
		}
		if (!enemyHalfOnly || open.Count == 0)
			return open;
		// hex width: x distance between horizontal neighbours (same row z, x differs by 1)
		var byCell = new Dictionary<(int, int), float>();
		foreach (var hex in hexes)
		{
			if (hex != null)
				byCell[(hex.x, hex.z)] = hex.position.x;
		}
		foreach (var pair in byCell)
		{
			if (byCell.TryGetValue((pair.Key.Item1 + 1, pair.Key.Item2), out var nx))
			{
				var dx = Math.Abs(nx - pair.Value);
				if (dx > 0.01f)
					rowStep = Math.Min(rowStep, dx);
			}
		}
		if (homeSign == 0 || rowStep == float.MaxValue)
		{
			LogLimited("enemy half unresolved (home side " + homeSign + ", hex width " + rowStep + "); entry refused rather than guessing.");
			return new List<BattleHex>();
		}
		var center = (minX + maxX) * 0.5f;
		var margin = rowStep * 0.5f + rowStep * 0.05f;
		var result = new List<BattleHex>();
		foreach (var hex in open)
		{
			var offset = hex.position.x - center;
			if (offset * -homeSign > margin)
				result.Add(hex);
		}
		return result;
	}

	/// <summary>Home half per gating side = the board half holding most of that side's deployed stacks.</summary>
	private static void ResolveHomeHalves(BattleState battle)
	{
		battle.HomeResolved = true;
		try
		{
			var grid = ReadProperty(battle.Logic, Pins.LogicGrid);
			var hexes = ReadProperty(grid, Pins.GridHexes) as Il2CppReferenceArray<BattleHex>;
			if (hexes == null)
				return;
			float minX = float.MaxValue, maxX = float.MinValue;
			foreach (var hex in hexes)
			{
				if (hex == null || hex.blockedByMap || hex.blockedFromAll)
					continue;
				minX = Math.Min(minX, hex.position.x);
				maxX = Math.Max(maxX, hex.position.x);
			}
			var center = (minX + maxX) * 0.5f;
			var sums = new Dictionary<IntPtr, float>();
			var counts = new Dictionary<IntPtr, int>();
			foreach (var hex in hexes)
			{
				if (hex?.fieldObjects == null)
					continue;
				for (var i = 0; i < hex.fieldObjects.Count; i++)
				{
					var unit = hex.fieldObjects[i]?.TryCast<Unit>();
					if (unit == null || ReadProperty(unit, Pins.FieldObjectSide) is not Il2CppObjectBase wrapper)
						continue;
					sums[wrapper.Pointer] = (sums.TryGetValue(wrapper.Pointer, out var s) ? s : 0f) + (hex.position.x - center);
					counts[wrapper.Pointer] = (counts.TryGetValue(wrapper.Pointer, out var c) ? c : 0) + 1;
				}
			}
			foreach (var side in battle.Sides)
			{
				if (side.SideWrapper is Il2CppObjectBase wrapper && sums.TryGetValue(wrapper.Pointer, out var sum) && Math.Abs(sum) > 0.01f)
					side.HomeSign = sum < 0 ? -1 : 1;
				else
					side.HomeSign = side.SideIndex == 0 ? -1 : 1; // native left/attacker deploy zone x 0-1
				_log?.LogInfo("HoMM3 Inferno Gating home half for " + side.HeroDescription + ": " + (side.HomeSign < 0 ? "low-x" : "high-x")
				              + " (" + (counts.TryGetValue((side.SideWrapper as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero, out var n) ? n + " deployed stacks" : "side-index fallback") + ").");
			}
		}
		catch (Exception ex)
		{
			LogLimited("home half resolution failed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ helpers

	private static int ReadConfigInitiative(TransferUnit unit)
	{
		try
		{
			var config = unit.prop_UnitLogicConfig_0 ?? Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unit.configSid);
			return config?.stats?.initiative ?? 0;
		}
		catch
		{
			return 0;
		}
	}

	private static int ReadUnitInitiative(Unit unit)
	{
		try
		{
			return (ReadProperty(unit, Pins.UnitStat) as UnitStat)?.initiative ?? 0;
		}
		catch
		{
			return 0;
		}
	}

	private static bool IsAlive(Unit unit)
	{
		var data = ReadProperty(unit, Pins.UnitData);
		if (data == null)
			return false;
		var method = data.GetType().GetMethod(Pins.UnitDataAlive, BindingFlags.Instance | BindingFlags.Public, null, Type.EmptyTypes, null);
		return method == null || (int)method.Invoke(data, null) > 0;
	}

	private static string DescribePending(GatingSide side)
	{
		var parts = new List<string>();
		foreach (var p in side.Pending)
			parts.Add(p.Sid + "x" + p.Stacks + "@slot" + p.Slot + "(ini " + p.Initiative + ")");
		return string.Join(", ", parts);
	}

	private static int CountBits(int mask)
	{
		var n = 0;
		for (; mask != 0; mask &= mask - 1)
			n++;
		return n;
	}

	private static readonly Dictionary<(Type, string), PropertyInfo> PropertyCache = new();

	private static PropertyInfo FindProperty(Type type, string name)
	{
		lock (PropertyCache)
		{
			if (PropertyCache.TryGetValue((type, name), out var cached))
				return cached;
			PropertyInfo found = null;
			for (var cur = type; cur != null && found == null; cur = cur.BaseType)
				found = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			PropertyCache[(type, name)] = found;
			return found;
		}
	}

	private static object ReadProperty(object obj, string name)
	{
		if (obj == null)
			return null;
		var property = FindProperty(obj.GetType(), name);
		if (property != null)
			return property.GetValue(obj);
		var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return method?.Invoke(obj, null);
	}

	private static void WriteProperty(object obj, string name, object value)
	{
		var property = FindProperty(obj.GetType(), name) ?? throw new MissingMemberException(obj.GetType().FullName + "." + name);
		property.SetValue(obj, value);
	}

	private static int ReadInt(object obj, string name)
	{
		return ReadProperty(obj, name) is int value ? value : -1;
	}

	private static object ReadMember(object obj, string[] names)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var value = ReadProperty(obj, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static Type ResolveTypeByHints(Assembly assembly, string[] hints, string id)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (!string.IsNullOrWhiteSpace(hint) && assembly.GetType(hint) is { } type)
				return type;
		}
		throw new TypeLoadException(id + " type not found from [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static PropertyInfo RequireProperty(Type type, string name, Type expected)
	{
		var property = FindProperty(type, name);
		if (property == null || (expected != null && property.PropertyType != expected))
			throw new MissingMemberException((type?.FullName ?? "null") + "." + name + (expected == null ? "" : " : " + expected.FullName));
		return property;
	}

	private static MethodInfo RequireMethod(Type type, string[] names, Type returnType, Type[] parameterTypes)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, parameterTypes, null);
			if (method != null && (returnType == null || method.ReturnType == returnType))
				return method;
		}
		throw new MissingMethodException((type?.FullName ?? "null") + " [" + string.Join(",", names ?? Array.Empty<string>()) + "]");
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3InfernoGatingRuntime).GetMethod(prefixName, flags);
		var postfix = postfixName == null ? null : typeof(Homm3InfernoGatingRuntime).GetMethod(postfixName, flags);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static string FormatMethod(MethodBase method) => method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;

	private static bool _loggedSubSkillRows;

	private static void LogLimited(string message)
	{
		if (_logged++ < 60)
			_log?.LogWarning("HoMM3 Inferno Gating: " + message);
	}
}
