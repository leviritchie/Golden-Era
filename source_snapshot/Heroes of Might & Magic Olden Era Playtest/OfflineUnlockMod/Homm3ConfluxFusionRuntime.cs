using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.Json;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using DataHero = Hex.Session.Data.Hero;
using DataMapMagic = Hex.Session.Data.MapMagic;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Conflux Elemental Fusion (skill_faction_homm3_conflux; design approved by the user 2026-11-15).
///
/// Spell: a hero with the Conflux faction skill has the world spell homm3_conflux_elemental_fusion (Lane 1 Core row:
/// mechType change_use_necromancy, parameters [homm3_conflux_elemental_fusion], manaCost 0, usageLimit -1 = unlimited). It rides the
/// native Necromancer Will world-magic handler, as Tower Artificing does: <see cref="PrefixFusionSpellCast"/> is a prefix
/// on that handler's Cast. Settings whose parameters[0] is not our mode return true untouched (Castle Elite Strategem,
/// Dungeon Captives, Tower Artificing and Inferno Gating share this target). Ours never reach the native toggle: a local
/// human caster with two eligible stacks gets the fusion panel and Cast reports true; anything else is refused (false).
///
/// Charge: the spell row is free and unlimited (manaCost 0, usageLimit -1), so normally nothing is charged. The native
/// caller still stamps the hero's MapMagic (Data.Hero.mapMagics -> MapMagics lookup by sid: usageCounter / lastUsageDay)
/// when Cast returns true. The prefix snapshots mana and the MapMagic before that; Cancel (button, Esc, or a forced close)
/// puts back any mana that went missing since the snapshot and restores usageCounter / lastUsageDay. The usage guard
/// below only acts when a Core row sets a positive usageLimit again (session day from the side's day-start logic).
///
/// Fusion: drag two different elemental stacks whose lines the hero's Conflux rank unlocks (config tierLines) into the
/// panel; fused = floor(penalty x (nA x vA + nB x vB) / vF), v = UnitLogicConfig.squadValue from the live unit configs;
/// each parent must bring at least minShare of the pooled value. The inputs are always trimmed
/// (<see cref="BuildTrimmedPlan"/>): the most fused creatures the two stacks can make, from the fewest parents, with the
/// surplus left in the army. Confirm re-reads the live army, removes
/// the consumed creatures and adds the fused stack through the shared <see cref="Homm3PartyArmyWriter"/> (a fully consumed
/// parent frees its slot; the fused stack takes parent A's freed slot, else parent B's, else merges into a stack of the
/// fused sid, else the first free slot). Fusion is permanent: there is no unfuse.
/// Second fusions (config "recipes", user 2026-11-15): a fixed list of named pairs of stage-1 fused units, each making one
/// stage-2 unit by the same count rule; only fused units named by a recipe can go into the panel, from recipeMinRank on.
///
/// Balancing lives in custom_factions/conflux_fusion/fusion_config.json, deployed next to the plugin and re-read on every
/// cast (no recompile). The Lava Elemental's Wall of Flame trap is stamped by
/// <see cref="Homm3MarshalSuppressingFireTrapBridge"/> from <see cref="FirewallPlacerSids"/>.
///
/// Proof tier: source + build. Runtime unproven: the intercept on the new spell row, the native mana / MapMagic charge
/// and its refund, the panel, the army write and the Wall of Flame stamp all need the first live test.
/// </summary>
internal static class Homm3ConfluxFusionRuntime
{
	internal const string LogPrefix = "[ConfluxFusion] ";
	internal const string FactionSkillSid = "skill_faction_homm3_conflux";
	/// <summary>parameters[0] of the spell row (also its sid).</summary>
	internal const string FusionMode = "homm3_conflux_elemental_fusion";
	internal const string ConfigSchema = "homm3_conflux_fusion_config.v1";
	/// <summary>The Lava Elemental: places magic_primal_wall_of_flame_summon.</summary>
	internal const string LavaElementalSid = "h3_earth_elemental_upg_alt";

	private static bool _registrationAttempted;
	private static bool _spellRegistered;
	private static ManualLogSource _log;
	private static Type _logicHeroType;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static int _loggedForeignCasts;
	private static int _loggedEvents;

	internal static string ConfigPath => Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "custom_factions", "conflux_fusion", "fusion_config.json");

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null)
			return;
		_registrationAttempted = true;
		_log = log;
		var hexAssembly = typeof(TransferBattle).Assembly;
		MethodInfo castMethod = null;
		try
		{
			_logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                 ?? throw new TypeLoadException("Missing " + GameSymbols.CastleEliteStrategem.LogicHeroTypeName);
			_logicHeroDataHeroGetter = Homm3TowerArtificingRuntime.ResolveExactMethod(_logicHeroType, typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
			var handlerType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.conflux.fusion.necromancyHandler");
			castMethod = Homm3TowerArtificingRuntime.ResolveExactMethod(handlerType, typeof(bool), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast);
			var worldHeroType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints, "homm3.conflux.fusion.worldHero");
			_handlerWorldHeroProperty = ResolveTypedProperty(handlerType, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, worldHeroType, "homm3.conflux.fusion.necromancyHandler.worldHero");
			_worldHeroLogicHeroProperty = ResolveTypedProperty(worldHeroType, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, _logicHeroType, "homm3.conflux.fusion.worldHero.logicHero");
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3ConfluxFusionRuntime), castMethod, nameof(PrefixFusionSpellCast), null);
			_spellRegistered = true;
		}
		catch (Exception ex)
		{
			Homm3TowerArtificingRuntime.UnpatchOwned(harmony, typeof(Homm3ConfluxFusionRuntime), castMethod, nameof(PrefixFusionSpellCast));
			_log?.LogError(LogPrefix + "hook NOT registered (the Fusion spell would reach the native Necromancer Will toggle; no fusion panel): " + ex.GetBaseException().Message);
			return;
		}
		// The panel is modal through the Artificing picker's input gates (idempotent registration).
		Homm3TowerArtificingPickerInputBlock.TryRegister(harmony, hexAssembly, _log);
		var writer = Homm3PartyArmyWriter.TryResolve(_logicHeroType, out var writerFail);
		var config = Homm3ConfluxFusionConfig.TryLoad(ConfigPath, out var loaded, out var configFail);
		_log?.LogInfo(LogPrefix + "hook registered: prefix on " + castMethod.DeclaringType?.FullName + "." + castMethod.Name + " for mode " + FusionMode
			+ "; army writer " + (writer ? Homm3PartyArmyWriter.Describe() : "FAILED (" + writerFail + "; Fuse refuses)")
			+ "; config " + (config ? ConfigPath + " (" + loaded.Pairs.Count + " pairs, penalty " + loaded.Penalty.ToString(CultureInfo.InvariantCulture)
			                           + ", minShare " + loaded.MinShare.ToString(CultureInfo.InvariantCulture) + ")" : "NOT LOADED (" + configFail + "; re-read on every cast)")
			+ ". Proof tier: build; runtime unproven.");
	}

	// ---------------------------------------------------------------- cast

	/// <summary>The cast that opened the panel: everything Cancel needs to refund, and what Confirm re-validates against.</summary>
	internal sealed class Session
	{
		internal object LogicHero;
		internal DataHero DataHero;
		internal string HeroSid;
		internal string HeroLabel;
		internal int Rank;
		internal int SideIndex;
		internal Homm3ConfluxFusionConfig Config;
		internal int ManaBefore;
		internal bool HadMapMagic;
		internal int UsageBefore;
		internal int LastUsageDayBefore;
		internal bool ChargeLogged;
	}

	private static bool PrefixFusionSpellCast(object __instance, ref bool __result)
	{
		var recognized = false;
		try
		{
			var setting = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			var parameters = ReadParameters(setting?.parameters);
			if (parameters.Count < 1 || !string.Equals(parameters[0], FusionMode, StringComparison.Ordinal))
				return true;
			recognized = true;
			__result = false;
			var worldHero = _handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(__instance) ? _handlerWorldHeroProperty.GetValue(__instance) : null;
			var logicHero = worldHero == null || !_worldHeroLogicHeroProperty.DeclaringType.IsInstanceOfType(worldHero) ? null : _worldHeroLogicHeroProperty.GetValue(worldHero);
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null)
			{
				_log?.LogError(LogPrefix + "cast refused: casting hero unresolved (worldHero " + (worldHero == null ? "null" : "set") + ", logicHero " + (logicHero == null ? "null" : "set") + ").");
				return false;
			}
			var hero = DescribeHero(dataHero);
			var rank = ResolveRank(dataHero);
			if (rank <= 0)
			{
				_log?.LogWarning(LogPrefix + "cast refused: " + hero + " lacks " + FactionSkillSid + ".");
				return false;
			}
			if (!TryResolveDataSide(logicHero, dataHero, out var side, out var sideFail))
			{
				_log?.LogError(LogPrefix + "cast refused: " + hero + " side unresolved (" + sideFail + ").");
				return false;
			}
			var sideType = side.typeOnCreate.ToString();
			if (!string.Equals(sideType, "Player", StringComparison.Ordinal))
			{
				// AI heroes (and any non-human side) have no panel: refuse before the native charge.
				if (_loggedForeignCasts++ < 8)
					_log?.LogInfo(LogPrefix + "cast refused: " + hero + " on side " + side.index + " is " + sideType + ", not a local human player (no fusion for AI).");
				return false;
			}
			if (!Homm3ConfluxFusionConfig.TryLoad(ConfigPath, out var config, out var configFail))
			{
				_log?.LogError(LogPrefix + "cast refused: config " + ConfigPath + " not loaded (" + configFail + ").");
				Homm3DungeonWarCaptivesWindow.ShowBanner("Elemental Fusion is unavailable: its configuration did not load (see the log).");
				return false;
			}
			var mana = dataHero.mana;
			var mapMagic = LookupMapMagic(dataHero, config.SpellSid, out var magicFail);
			var usageLimit = setting.usageLimit;
			var dayKnown = Homm3SwashbucklerGoldHook.TryReadSessionDay(side.index, out var today);
			var usage = mapMagic == null ? "MapMagic " + config.SpellSid + " unreadable (" + magicFail + ")" : "usageCounter=" + mapMagic.usageCounter + " lastUsageDay=" + mapMagic.lastUsageDay;
			LogEvent("cast intercepted: hero " + hero + " rank " + rank + " side " + side.index + " mana=" + mana + " " + usage + " usageLimit=" + usageLimit
				+ " today=" + (dayKnown ? today.ToString(CultureInfo.InvariantCulture) : "unknown") + ".");
			if (mapMagic != null && dayKnown && usageLimit > 0 && mapMagic.lastUsageDay == today && mapMagic.usageCounter >= usageLimit)
			{
				_log?.LogInfo(LogPrefix + "cast refused: " + hero + " reached the spell row's usageLimit " + usageLimit + " today (plugin usage guard).");
				Homm3DungeonWarCaptivesWindow.ShowBanner("Elemental Fusion cannot be cast again today.");
				return false;
			}
			if (Homm3ConfluxFusionPanel.IsOpen)
			{
				_log?.LogWarning(LogPrefix + "cast refused: the fusion panel is already open.");
				return false;
			}
			var session = new Session
			{
				LogicHero = logicHero,
				DataHero = dataHero,
				HeroSid = dataHero.configSid,
				HeroLabel = hero,
				Rank = rank,
				SideIndex = side.index,
				Config = config,
				ManaBefore = mana,
				HadMapMagic = mapMagic != null,
				UsageBefore = mapMagic?.usageCounter ?? 0,
				LastUsageDayBefore = mapMagic?.lastUsageDay ?? 0,
			};
			if (!Homm3PartyArmyWriter.TryReadArmy(logicHero, dataHero, out var slotSid, out var slotCount, out _, out var armyFail))
			{
				_log?.LogError(LogPrefix + "cast refused: " + hero + " army unreadable (" + armyFail + ").");
				return false;
			}
			var eligible = 0;
			var sids = new HashSet<string>(StringComparer.Ordinal);
			for (var slot = 0; slot < Homm3PartyArmyWriter.MaxArmySlots; slot++)
			{
				if (slotSid[slot] != null && EligibilityBlock(config, rank, slotSid[slot]) == null)
				{
					eligible++;
					sids.Add(slotSid[slot]);
				}
			}
			if (eligible < 2 || sids.Count < 2)
			{
				LogEvent("cast refused before the charge: " + hero + " has " + sids.Count + " eligible elemental type(s) in army " + Homm3PartyArmyWriter.Describe(slotSid, slotCount) + ".");
				Homm3DungeonWarCaptivesWindow.ShowBanner("Elemental Fusion needs two different elementals your " + RankName(rank) + " Conflux mastery allows (" + UnlockedLinesText(config, rank) + ").");
				return false;
			}
			if (!Homm3ConfluxFusionPanel.Open(session, out var openFail))
			{
				_log?.LogError(LogPrefix + "cast refused: fusion panel did not open for " + hero + " (" + openFail + ").");
				return false;
			}
			LogEvent("panel opened for " + hero + "; army " + Homm3PartyArmyWriter.Describe(slotSid, slotCount) + ". Cast returns true: the native charge follows.");
			__result = true;
			return false;
		}
		catch (Exception ex)
		{
			if (recognized)
			{
				__result = false;
				_log?.LogError(LogPrefix + "cast failed closed; native handler suppressed: " + ex.GetBaseException().Message);
				return false;
			}
			if (_loggedForeignCasts++ < 8)
				_log?.LogWarning(LogPrefix + "world-magic inspection failed; native handler remains responsible: " + ex.GetBaseException().Message);
			return true;
		}
	}

	/// <summary>First panel frame after the cast: the native charge has run; log it once.</summary>
	internal static void LogChargeObserved(Session session)
	{
		if (session == null || session.ChargeLogged)
			return;
		session.ChargeLogged = true;
		try
		{
			var magic = LookupMapMagic(session.DataHero, session.Config.SpellSid, out var fail);
			LogEvent("native charge observed for " + session.HeroLabel + ": mana " + session.ManaBefore + "->" + session.DataHero.mana
				+ (magic == null ? ", MapMagic unreadable (" + fail + ")" : ", usageCounter " + session.UsageBefore + "->" + magic.usageCounter + ", lastUsageDay " + session.LastUsageDayBefore + "->" + magic.lastUsageDay) + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "charge readback failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Cancel / Esc / forced close: give back the mana the cast took and roll the MapMagic usage back.</summary>
	internal static void Refund(Session session, string why)
	{
		if (session == null)
			return;
		try
		{
			var manaNow = session.DataHero.mana;
			var charged = session.ManaBefore - manaNow;
			if (charged > 0)
				session.DataHero.mana = manaNow + charged;
			var magic = LookupMapMagic(session.DataHero, session.Config.SpellSid, out var fail);
			string usage;
			if (magic == null)
			{
				usage = "MapMagic unreadable (" + fail + "); usage not rolled back";
			}
			else
			{
				var usageNow = magic.usageCounter;
				var dayNow = magic.lastUsageDay;
				if (session.HadMapMagic)
				{
					magic.usageCounter = session.UsageBefore;
					magic.lastUsageDay = session.LastUsageDayBefore;
				}
				usage = "usageCounter " + session.UsageBefore + "->" + usageNow + "->" + magic.usageCounter + ", lastUsageDay " + session.LastUsageDayBefore + "->" + dayNow + "->" + magic.lastUsageDay
				        + (session.HadMapMagic ? "" : " (no MapMagic at cast; left as is)");
			}
			LogEvent("cancel refund (" + why + ") for " + session.HeroLabel + ": mana before " + session.ManaBefore + ", charged " + Math.Max(0, charged)
				+ ", now " + session.DataHero.mana + "; " + usage + ".");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "cancel refund failed for " + session.HeroLabel + ": " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- fusion

	internal sealed class Plan
	{
		internal int SlotA;
		internal int SlotB;
		internal string SidA;
		internal string SidB;
		internal int CountA;
		internal int CountB;
		internal int InA;
		internal int InB;
		internal int ValueA;
		internal int ValueB;
		internal int ValueF;
		internal Homm3ConfluxFusionConfig.Pair Pair;
		internal int Fused;
		internal long Pooled;
		/// <summary>Fused value lost to rounding down: penalty x pooled - fused x vF.</summary>
		internal decimal RoundingLoss;
		internal int TargetSlot;
		internal bool Merge;
		internal string[] AfterSid;
		internal int[] AfterCount;
		/// <summary>Null when the plan can be confirmed, else the reason for the player.</summary>
		internal string Blocked;
		/// <summary>Blocked only because the army has no slot left for the fused stack.</summary>
		internal bool NoFreeSlot;
		/// <summary>Army slot whose leftover creatures are dropped to make room for the fused stack (-1: none).</summary>
		internal int LostSlot = -1;
		internal string LostSid;
		internal int LostCount;
		/// <summary>Player-facing warning when the plan drops leftovers (Fuse then needs a confirm).</summary>
		internal string LossWarning;
	}

	/// <summary>Null when the unit can go into a fusion at this rank, else the reason.</summary>
	internal static string EligibilityBlock(Homm3ConfluxFusionConfig config, int rank, string sid)
	{
		if (sid != null && config.RecipeUnits.Contains(sid))
			return rank >= config.RecipeMinRank ? null : "Second fusions require " + RankName(config.RecipeMinRank) + " Conflux.";
		if (sid != null && config.FusedUnits.Contains(sid))
			return "This fused elemental has no second fusion.";
		if (sid == null || !config.LineByUnit.TryGetValue(sid, out var line))
			return "Not an elemental.";
		if (!config.UnlockedLines(rank).Contains(line))
			return "Requires " + RankName(config.RankForLine(line)) + " Conflux (" + Cap(line) + " line).";
		return null;
	}

	/// <summary>Builds the fusion of nA from slotA and nB from slotB on the given army; never touches the game.</summary>
	internal static Plan BuildPlan(Homm3ConfluxFusionConfig config, int rank, string[] slotSid, int[] slotCount, int slotA, int slotB, int inA, int inB, int discardSlot = -1)
	{
		var p = new Plan { SlotA = slotA, SlotB = slotB, InA = inA, InB = inB, TargetSlot = -1 };
		if (slotA < 0 || slotB < 0 || slotA >= Homm3PartyArmyWriter.MaxArmySlots || slotB >= Homm3PartyArmyWriter.MaxArmySlots)
		{
			p.Blocked = "Pick two elemental stacks.";
			return p;
		}
		p.SidA = slotSid[slotA];
		p.SidB = slotSid[slotB];
		p.CountA = slotCount[slotA];
		p.CountB = slotCount[slotB];
		if (slotA == slotB || p.SidA == null || p.SidB == null)
		{
			p.Blocked = "Pick two elemental stacks.";
			return p;
		}
		if (string.Equals(p.SidA, p.SidB, StringComparison.Ordinal))
		{
			p.Blocked = "Pick two different elementals.";
			return p;
		}
		p.Blocked = EligibilityBlock(config, rank, p.SidA) ?? EligibilityBlock(config, rank, p.SidB);
		if (p.Blocked != null)
			return p;
		if (!config.TryGetPair(p.SidA, p.SidB, out p.Pair))
		{
			p.Blocked = config.FusedUnits.Contains(p.SidA) || config.FusedUnits.Contains(p.SidB)
				? "These two do not fuse. A fused elemental only fuses with its own second-fusion partner."
				: "These two elementals do not fuse.";
			return p;
		}
		p.ValueA = SquadValue(p.SidA);
		p.ValueB = SquadValue(p.SidB);
		p.ValueF = SquadValue(p.Pair.Fused);
		if (p.ValueF <= 0)
		{
			p.Blocked = FusedName(p.Pair) + " is not installed in this game (" + p.Pair.Fused + ").";
			return p;
		}
		if (p.ValueA <= 0 || p.ValueB <= 0)
		{
			p.Blocked = "Unit value unreadable (" + (p.ValueA <= 0 ? p.SidA : p.SidB) + ").";
			return p;
		}
		if (inA < 1 || inB < 1 || inA > p.CountA || inB > p.CountB)
		{
			p.Blocked = "Put at least one of each in.";
			return p;
		}
		p.Pooled = (long)inA * p.ValueA + (long)inB * p.ValueB;
		p.Fused = Homm3ConfluxFusionMath.FusedCount(inA, p.ValueA, inB, p.ValueB, p.ValueF, config.Penalty);
		p.RoundingLoss = config.Penalty * p.Pooled - (decimal)p.Fused * p.ValueF;
		if (!Homm3ConfluxFusionMath.SharesOk(inA, p.ValueA, inB, p.ValueB, config.MinShare, out var weak))
		{
			p.Blocked = "Each elemental must bring at least " + Percent(config.MinShare) + " of the pooled strength (add more " + Homm3UnitDisplayNames.Resolve(weak == 0 ? p.SidA : p.SidB) + ").";
			return p;
		}
		if (p.Fused < 1)
		{
			p.Blocked = "Too few creatures for one " + FusedName(p.Pair) + ".";
			return p;
		}
		// Army after: consumed parents shrink or free their slot; the fused stack takes A's freed slot, else B's, else
		// merges into a stack of the fused sid, else the first free slot.
		p.AfterSid = (string[])slotSid.Clone();
		p.AfterCount = (int[])slotCount.Clone();
		p.AfterCount[slotA] -= inA;
		p.AfterCount[slotB] -= inB;
		if ((discardSlot == slotA || discardSlot == slotB) && p.AfterCount[discardSlot] > 0)
		{
			// No room otherwise: the leftover of this parent is dropped and its slot takes the fused stack.
			p.LostSlot = discardSlot;
			p.LostSid = slotSid[discardSlot];
			p.LostCount = p.AfterCount[discardSlot];
			p.AfterCount[discardSlot] = 0;
			p.LossWarning = "Your army is full: the " + p.LostCount.ToString("N0", CultureInfo.InvariantCulture) + " leftover "
				+ Homm3UnitDisplayNames.Resolve(p.LostSid) + " will be lost.";
		}
		foreach (var s in new[] { slotA, slotB })
		{
			if (p.AfterCount[s] <= 0)
			{
				p.AfterSid[s] = null;
				p.AfterCount[s] = 0;
			}
		}
		if (p.AfterSid[slotA] == null)
		{
			p.TargetSlot = slotA;
		}
		else if (p.AfterSid[slotB] == null)
		{
			p.TargetSlot = slotB;
		}
		else
		{
			p.TargetSlot = Array.IndexOf(p.AfterSid, p.Pair.Fused);
			p.Merge = p.TargetSlot >= 0;
			if (p.TargetSlot < 0)
				p.TargetSlot = Array.IndexOf(p.AfterSid, null);
		}
		if (p.TargetSlot < 0)
		{
			p.Blocked = "No free army slot for the " + FusedName(p.Pair) + ".";
			p.NoFreeSlot = true;
			return p;
		}
		if (p.Merge)
		{
			p.AfterCount[p.TargetSlot] += p.Fused;
		}
		else
		{
			p.AfterSid[p.TargetSlot] = p.Pair.Fused;
			p.AfterCount[p.TargetSlot] = p.Fused;
		}
		return p;
	}

	/// <summary>
	/// The only fusion the panel offers (trim is always on): both whole stacks are available, and the plan takes the
	/// inputs that make the most fused creatures under the share rule, from the least pooled value (ties keep more of A),
	/// leaving the surplus in the army. When those inputs leave no army slot for the fused stack, the leftover of the weaker
	/// parent (less squad value) is dropped to free its slot; the plan then carries <see cref="Plan.LossWarning"/> and Fuse
	/// needs the player's confirm. Blocked plans carry the reason (from the whole stacks when no input works).
	/// </summary>
	internal static Plan BuildTrimmedPlan(Homm3ConfluxFusionConfig config, int rank, string[] slotSid, int[] slotCount, int slotA, int slotB)
	{
		var inRange = slotA >= 0 && slotB >= 0 && slotA < Homm3PartyArmyWriter.MaxArmySlots && slotB < Homm3PartyArmyWriter.MaxArmySlots;
		var whole = BuildPlan(config, rank, slotSid, slotCount, slotA, slotB, inRange ? slotCount[slotA] : 0, inRange ? slotCount[slotB] : 0);
		if (whole.Pair == null || whole.ValueA <= 0 || whole.ValueB <= 0 || whole.ValueF <= 0 || whole.CountA < 1 || whole.CountB < 1)
			return whole;
		var best = Homm3ConfluxFusionMath.BestInputs(whole.CountA, whole.ValueA, whole.CountB, whole.ValueB, whole.ValueF, config.Penalty, config.MinShare);
		if (best is not { } t)
			return whole;
		var plan = BuildPlan(config, rank, slotSid, slotCount, slotA, slotB, t.A, t.B);
		if (plan.NoFreeSlot)
		{
			// Both parents leave a surplus and the army has no slot for the fused stack: drop the weaker leftover
			// (less squad value; ties drop B's) after the player confirms (user 2026-11-15).
			var lostA = (long)(whole.CountA - t.A) * whole.ValueA;
			var lostB = (long)(whole.CountB - t.B) * whole.ValueB;
			plan = BuildPlan(config, rank, slotSid, slotCount, slotA, slotB, t.A, t.B, lostA < lostB ? slotA : slotB);
		}
		return plan;
	}

	/// <summary>
	/// Confirm: re-reads the live army, rebuilds the trimmed plan from it and writes it. Returns true when the panel should
	/// close (written, or a partial write that cannot be undone); false keeps the panel open with <paramref name="message"/>.
	/// </summary>
	internal static bool TryFuse(Session session, int slotA, int slotB, bool acceptLoss, out string message)
	{
		message = null;
		if (!Homm3PartyArmyWriter.TryReadArmy(session.LogicHero, session.DataHero, out var slotSid, out var slotCount, out var totals, out var readFail))
		{
			message = "Your army could not be read (" + readFail + ").";
			return false;
		}
		var before = Homm3PartyArmyWriter.Describe(slotSid, slotCount);
		var plan = BuildTrimmedPlan(session.Config, session.Rank, slotSid, slotCount, slotA, slotB);
		if (plan.Blocked != null)
		{
			message = plan.Blocked;
			return false;
		}
		if (plan.LostCount > 0 && !acceptLoss)
		{
			message = plan.LossWarning;
			return false;
		}
		var inA = plan.InA;
		var inB = plan.InB;
		var steps = new List<string>();
		var result = Homm3PartyArmyWriter.Write(session.LogicHero, session.DataHero, plan.AfterSid, plan.AfterCount, totals, steps, out var writeFail);
		var inputs = Homm3UnitDisplayNames.Resolve(plan.SidA) + " x" + inA + " (" + plan.SidA + "@" + slotA + ", v" + plan.ValueA + ") + "
		             + Homm3UnitDisplayNames.Resolve(plan.SidB) + " x" + inB + " (" + plan.SidB + "@" + slotB + ", v" + plan.ValueB + ")";
		switch (result)
		{
			case Homm3PartyArmyWriter.WriteResult.Refused:
				_log?.LogWarning(LogPrefix + "confirm refused for " + session.HeroLabel + ": " + writeFail + " (army " + before + ").");
				message = "Fusion refused: " + writeFail + ".";
				return false;
			case Homm3PartyArmyWriter.WriteResult.WriteFailed:
				_log?.LogError(LogPrefix + "confirm: army write failed for " + session.HeroLabel + " after [" + string.Join(", ", steps) + "]: " + writeFail + "; army before " + before + "; no refund.");
				Homm3DungeonWarCaptivesWindow.ShowBanner("Elemental Fusion failed while changing the army (see the log).");
				return true;
			case Homm3PartyArmyWriter.WriteResult.ReadBackMismatch:
				_log?.LogError(LogPrefix + "confirm: army reads back differently for " + session.HeroLabel + " [" + writeFail + "] after [" + string.Join(", ", steps) + "]; army before " + before + "; no refund.");
				Homm3DungeonWarCaptivesWindow.ShowBanner("Elemental Fusion: the army did not update as planned (see the log).");
				return true;
		}
		var magic = LookupMapMagic(session.DataHero, session.Config.SpellSid, out var magicFail);
		LogEvent("confirm: " + session.HeroLabel + " fused " + inputs + " -> " + FusedName(plan.Pair) + " x" + plan.Fused + " (" + plan.Pair.Fused + ", v" + plan.ValueF
			+ ", pooled " + plan.Pooled + " x " + session.Config.Penalty.ToString(CultureInfo.InvariantCulture) + ", rounding loss " + plan.RoundingLoss.ToString("0.##", CultureInfo.InvariantCulture)
			+ (plan.Merge ? ", merged into slot " : ", new stack at slot ") + plan.TargetSlot
			+ (plan.LostCount > 0 ? ", dropped " + plan.LostCount + " leftover " + plan.LostSid + " (army full, confirmed)" : "") + "); army before " + before + " after " + Homm3PartyArmyWriter.Describe(plan.AfterSid, plan.AfterCount)
			+ " steps [" + string.Join(", ", steps) + "]; mana " + session.ManaBefore + "->" + session.DataHero.mana
			+ (magic == null ? ", MapMagic unreadable (" + magicFail + ")" : ", usageCounter " + session.UsageBefore + "->" + magic.usageCounter + ", lastUsageDay " + session.LastUsageDayBefore + "->" + magic.lastUsageDay) + ".");
		Homm3DungeonWarCaptivesWindow.ShowBanner("Fused " + inA.ToString("N0", CultureInfo.InvariantCulture) + " " + Homm3UnitDisplayNames.Resolve(plan.SidA) + " and "
			+ inB.ToString("N0", CultureInfo.InvariantCulture) + " " + Homm3UnitDisplayNames.Resolve(plan.SidB) + " into " + plan.Fused.ToString("N0", CultureInfo.InvariantCulture) + " " + FusedName(plan.Pair) + "."
			+ (plan.LostCount > 0 ? " " + plan.LostCount.ToString("N0", CultureInfo.InvariantCulture) + " leftover " + Homm3UnitDisplayNames.Resolve(plan.LostSid) + " were lost." : ""));
		return true;
	}

	// ---------------------------------------------------------------- Wall of Flame placers

	/// <summary>
	/// Units whose placed magic_primal_wall_of_flame_summon trap deals 10 x creatures: the Lava Elemental and every fused
	/// unit with the Lava Elemental as a parent (the fused unit carries its ability). Read from the deployed config;
	/// the Lava Elemental alone when the config does not load.
	/// </summary>
	internal static HashSet<string> FirewallPlacerSids()
	{
		var now = DateTime.UtcNow;
		if (_firewallPlacers != null && (now - _firewallPlacersReadAt).TotalSeconds < 30)
			return _firewallPlacers;
		var set = new HashSet<string>(StringComparer.Ordinal) { LavaElementalSid };
		if (Homm3ConfluxFusionConfig.TryLoad(ConfigPath, out var config, out _))
		{
			foreach (var pair in config.Pairs)
			{
				if (string.Equals(pair.A, LavaElementalSid, StringComparison.Ordinal) || string.Equals(pair.B, LavaElementalSid, StringComparison.Ordinal))
					set.Add(pair.Fused);
			}
			foreach (var sid in config.FirewallPlacers)
				set.Add(sid);
		}
		_firewallPlacers = set;
		_firewallPlacersReadAt = now;
		return set;
	}

	private static HashSet<string> _firewallPlacers;
	private static DateTime _firewallPlacersReadAt;

	// ---------------------------------------------------------------- helpers

	internal static int SquadValue(string sid)
	{
		var config = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
		return config == null ? 0 : Math.Max(0, config.squadValue);
	}

	internal static string FusedName(Homm3ConfluxFusionConfig.Pair pair)
	{
		var name = Homm3UnitDisplayNames.Resolve(pair.Fused);
		if (!string.Equals(name, pair.Fused, StringComparison.Ordinal) || string.IsNullOrWhiteSpace(pair.Name))
			return name;
		return pair.Name.Trim();
	}

	internal static string RankName(int rank) => rank switch { 1 => "Basic", 2 => "Advanced", 3 => "Expert", _ => "higher" };

	internal static string UnlockedLinesText(Homm3ConfluxFusionConfig config, int rank)
	{
		var names = new List<string>();
		foreach (var line in config.LineOrder)
		{
			if (config.UnlockedLines(rank).Contains(line))
				names.Add(Cap(line));
		}
		return string.Join(", ", names);
	}

	internal static string Cap(string s) => string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);

	internal static string Percent(decimal share) => Math.Round(share * 100m, 0).ToString("0", CultureInfo.InvariantCulture) + "%";

	private static DataMapMagic LookupMapMagic(DataHero dataHero, string sid, out string failReason)
	{
		failReason = null;
		var magics = dataHero?.mapMagics;
		if (magics == null)
		{
			failReason = "hero has no mapMagics";
			return null;
		}
		if (!Homm3AdventureVisionNativeAdapter.TryLookupMapMagic(magics, sid, out var found, out failReason))
			return null;
		if (found is DataMapMagic magic)
			return magic;
		failReason = found == null ? "no MapMagic " + sid : "lookup returned " + found.GetType().FullName;
		return null;
	}

	private static bool TryResolveDataSide(object logicHero, DataHero dataHero, out DataSide side, out string failReason)
	{
		side = null;
		if (Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained(logicHero, out var dataSide, out var pathFail) && dataSide is DataSide resolved)
		{
			side = resolved;
			failReason = null;
			return true;
		}
		// The day-start side cache (the Dungeon Captives path; that hook does not fire on day 1).
		if (dataHero != null && Homm3SwashbucklerGoldHook.TryGetDayStartSide(dataHero.sideId, out var cached))
		{
			side = cached;
			failReason = null;
			return true;
		}
		failReason = (pathFail ?? "shared path returned " + (dataSide?.GetType().FullName ?? "null")) + "; day-start side cache has no side " + (dataHero == null ? "?" : dataHero.sideId.ToString(CultureInfo.InvariantCulture));
		return false;
	}

	internal static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	/// <summary>Rank 1..3 of skill_faction_homm3_conflux, 0 when absent or unreadable.</summary>
	private static int ResolveRank(DataHero dataHero)
	{
		if (dataHero == null)
			return 0;
		var skills = Homm3TowerArtificingRuntime.ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = Homm3TowerArtificingRuntime.ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = (Homm3TowerArtificingRuntime.ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string)?.Trim();
			if (!string.Equals(sid, FactionSkillSid, StringComparison.Ordinal))
				continue;
			return Homm3TowerArtificingRuntime.ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers) is int level ? Math.Max(1, Math.Min(3, level)) : 0;
		}
		return 0;
	}

	internal static string DescribeHero(DataHero dataHero)
	{
		if (dataHero == null)
			return "null";
		var id = Homm3TowerArtificingRuntime.ReadMember(dataHero, GameSymbols.CastleEliteStrategem.DataHeroIdMembers);
		return (dataHero.configSid ?? "?") + "#" + (id?.ToString() ?? "?");
	}

	/// <summary>Count + int indexer first: Il2Cpp lists can yield nothing under managed foreach.</summary>
	private static IEnumerable<object> EnumerateObjects(object list)
	{
		if (list == null)
			yield break;
		var type = list.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		var indexer = type.GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(int) }, null);
		if (countProperty?.GetValue(list) is int count && indexer != null)
		{
			for (var i = 0; i < count; i++)
			{
				var item = indexer.Invoke(list, new object[] { i });
				if (item != null)
					yield return item;
			}
			yield break;
		}
		if (list is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
		}
	}

	private static List<string> ReadParameters(object parameters)
	{
		var result = new List<string>();
		if (parameters is string[] managed)
		{
			result.AddRange(managed);
			return result;
		}
		if (parameters is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				result.Add(item as string ?? item?.ToString());
		}
		return result;
	}

	private static PropertyInfo ResolveTypedProperty(Type type, string name, Type propertyType, string symbolId)
	{
		var property = type?.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		               ?? throw new MissingMemberException(symbolId + " property " + name + " not found on " + (type?.FullName ?? "null"));
		if (property.PropertyType != propertyType || property.GetGetMethod(true) == null)
			throw new MissingMemberException(symbolId + " property " + name + " has type " + property.PropertyType.FullName + ", expected " + propertyType?.FullName);
		return property;
	}

	internal static void LogEvent(string message)
	{
		if (_loggedEvents++ < 120)
			_log?.LogInfo(LogPrefix + message);
	}

	internal static void LogWarning(string message) => _log?.LogWarning(LogPrefix + message);
}

/// <summary>Pure fusion arithmetic (decimal, so 0.9 and 0.3333 are exact).</summary>
internal static class Homm3ConfluxFusionMath
{
	/// <summary>floor(penalty x (nA x vA + nB x vB) / vF).</summary>
	internal static int FusedCount(int nA, int vA, int nB, int vB, int vF, decimal penalty)
	{
		if (vF <= 0)
			return 0;
		var pooled = (decimal)nA * vA + (decimal)nB * vB;
		var fused = decimal.Floor(penalty * pooled / vF);
		return fused <= 0 ? 0 : fused >= int.MaxValue ? int.MaxValue : (int)fused;
	}

	/// <summary>True when each parent brings at least minShare of the pooled value; weak = the parent that does not (0 = A, 1 = B).</summary>
	internal static bool SharesOk(int nA, int vA, int nB, int vB, decimal minShare, out int weak)
	{
		var a = (decimal)nA * vA;
		var b = (decimal)nB * vB;
		var pooled = a + b;
		weak = -1;
		if (pooled <= 0)
		{
			weak = 0;
			return false;
		}
		if (a < minShare * pooled)
			weak = 0;
		else if (b < minShare * pooled)
			weak = 1;
		return weak < 0;
	}

	/// <summary>
	/// Always-on trim: the inputs (1 &lt;= tA &lt;= nA, 1 &lt;= tB &lt;= nB) that pass the share rule and make the most fused
	/// creatures, from the smallest pooled value; ties keep more of parent A in the army. Null when no input passes the
	/// share rule and makes at least one.
	/// </summary>
	internal static (int A, int B)? BestInputs(int nA, int vA, int nB, int vB, int vF, decimal penalty, decimal minShare)
	{
		if (nA < 1 || nB < 1 || vA <= 0 || vB <= 0 || vF <= 0 || penalty <= 0m)
			return null;
		(int A, int B)? best = null;
		var bestCount = 0;
		var bestPooled = decimal.MaxValue;
		for (var tA = 1; tA <= nA; tA++)
		{
			// The share rule bounds B to an interval: B's share needs tB >= lo, A's share needs tB <= hi. The closed forms
			// are nudged with the exact SharesOk check.
			var lo = 1;
			var hi = nB;
			if (minShare > 0m && minShare < 1m)
			{
				var a = (decimal)tA * vA;
				lo = ClampCount(decimal.Ceiling(minShare * a / ((1m - minShare) * vB)), 1, nB + 1);
				hi = ClampCount(decimal.Floor(a * (1m - minShare) / (minShare * vB)), 0, nB);
			}
			while (lo <= hi && !SharesOk(tA, vA, lo, vB, minShare, out _))
				lo++;
			while (hi >= lo && !SharesOk(tA, vA, hi, vB, minShare, out _))
				hi--;
			if (lo > hi)
				continue;
			var count = FusedCount(tA, vA, hi, vB, vF, penalty);
			if (count < 1)
				continue;
			// The fewest B for that count.
			var need = (decimal)count * vF / penalty - (decimal)tA * vA;
			var tB = need <= 0m ? lo : Math.Max(lo, ClampCount(decimal.Ceiling(need / vB), lo, hi));
			while (tB < hi && FusedCount(tA, vA, tB, vB, vF, penalty) < count)
				tB++;
			while (tB > lo && FusedCount(tA, vA, tB - 1, vB, vF, penalty) >= count)
				tB--;
			var pooled = (decimal)tA * vA + (decimal)tB * vB;
			if (count > bestCount || count == bestCount && pooled < bestPooled)
			{
				bestCount = count;
				bestPooled = pooled;
				best = (tA, tB);
			}
		}
		return best;
	}

	private static int ClampCount(decimal value, int min, int max) => value <= min ? min : value >= max ? max : (int)value;
}

/// <summary>custom_factions/conflux_fusion/fusion_config.json (schema homm3_conflux_fusion_config.v1), validated on load.</summary>
internal sealed class Homm3ConfluxFusionConfig
{
	internal sealed class Pair
	{
		internal string A;
		internal string B;
		internal string Host;
		internal string Guest;
		internal string Fused;
		internal string Name;
		/// <summary>1 = two elementals; 2 = a second fusion of two fused elementals (config "recipes").</summary>
		internal int Stage = 1;
	}

	internal string SpellSid;
	internal decimal Penalty;
	internal decimal MinShare;
	internal readonly List<string> LineOrder = new();
	internal readonly Dictionary<string, string> LineByUnit = new(StringComparer.Ordinal);
	internal readonly Dictionary<int, HashSet<string>> TierLines = new();
	internal readonly List<Pair> Pairs = new();
	internal readonly HashSet<string> FirewallPlacers = new(StringComparer.Ordinal);
	/// <summary>Every unit a pair or recipe produces.</summary>
	internal readonly HashSet<string> FusedUnits = new(StringComparer.Ordinal);
	/// <summary>Fused units that are an input of at least one second-fusion recipe.</summary>
	internal readonly HashSet<string> RecipeUnits = new(StringComparer.Ordinal);
	internal int RecipeMinRank = 1;
	private readonly Dictionary<string, Pair> _pairByKey = new(StringComparer.Ordinal);

	private static string PairKey(string a, string b) => string.CompareOrdinal(a, b) <= 0 ? a + "|" + b : b + "|" + a;

	internal bool TryGetPair(string a, string b, out Pair pair) => _pairByKey.TryGetValue(PairKey(a, b), out pair);

	/// <summary>Lines unlocked at a rank: the union of tierLines[1..rank].</summary>
	internal HashSet<string> UnlockedLines(int rank)
	{
		var set = new HashSet<string>(StringComparer.Ordinal);
		foreach (var pair in TierLines)
		{
			if (pair.Key <= rank)
				set.UnionWith(pair.Value);
		}
		return set;
	}

	/// <summary>The lowest rank that unlocks a line (4 when none does).</summary>
	internal int RankForLine(string line)
	{
		var best = 4;
		foreach (var pair in TierLines)
		{
			if (pair.Value.Contains(line) && pair.Key < best)
				best = pair.Key;
		}
		return best;
	}

	private static Homm3ConfluxFusionConfig _cached;
	private static DateTime _cachedWrite;
	private static string _cachedPath;

	/// <summary>Reads and validates the config; re-parses only when the file changed. False with the reason (fail closed).</summary>
	internal static bool TryLoad(string path, out Homm3ConfluxFusionConfig config, out string failReason)
	{
		config = null;
		failReason = null;
		try
		{
			if (!File.Exists(path))
			{
				failReason = "file missing";
				return false;
			}
			var write = File.GetLastWriteTimeUtc(path);
			if (_cached != null && write == _cachedWrite && string.Equals(path, _cachedPath, StringComparison.OrdinalIgnoreCase))
			{
				config = _cached;
				return true;
			}
			using var doc = JsonDocument.Parse(File.ReadAllText(path), new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
			var parsed = Parse(doc.RootElement);
			_cached = parsed;
			_cachedWrite = write;
			_cachedPath = path;
			config = parsed;
			return true;
		}
		catch (Exception ex)
		{
			failReason = ex.GetBaseException().Message;
			return false;
		}
	}

	private static Homm3ConfluxFusionConfig Parse(JsonElement root)
	{
		if (root.ValueKind != JsonValueKind.Object)
			throw new FormatException("root is not an object");
		var schema = Str(root, "schema");
		if (!string.Equals(schema, Homm3ConfluxFusionRuntime.ConfigSchema, StringComparison.Ordinal))
			throw new FormatException("schema " + (schema ?? "null") + ", expected " + Homm3ConfluxFusionRuntime.ConfigSchema);
		var c = new Homm3ConfluxFusionConfig
		{
			SpellSid = Str(root, "spellSid") ?? throw new FormatException("spellSid missing"),
			Penalty = Dec(root, "penalty"),
			MinShare = Dec(root, "minShare"),
		};
		if (c.Penalty <= 0m || c.Penalty > 1m)
			throw new FormatException("penalty " + c.Penalty + " outside (0, 1]");
		if (c.MinShare < 0m || c.MinShare > 0.5m)
			throw new FormatException("minShare " + c.MinShare + " outside [0, 0.5]");
		if (!root.TryGetProperty("lines", out var lines) || lines.ValueKind != JsonValueKind.Object)
			throw new FormatException("lines missing");
		foreach (var line in lines.EnumerateObject())
		{
			c.LineOrder.Add(line.Name);
			foreach (var sid in Strings(line.Value, "lines." + line.Name))
			{
				if (c.LineByUnit.TryGetValue(sid, out var other))
					throw new FormatException(sid + " is in lines " + other + " and " + line.Name);
				c.LineByUnit[sid] = line.Name;
			}
		}
		if (!root.TryGetProperty("tierLines", out var tiers) || tiers.ValueKind != JsonValueKind.Object)
			throw new FormatException("tierLines missing");
		foreach (var tier in tiers.EnumerateObject())
		{
			if (!int.TryParse(tier.Name, NumberStyles.Integer, CultureInfo.InvariantCulture, out var rank) || rank < 1 || rank > 3)
				throw new FormatException("tierLines key " + tier.Name + " is not 1..3");
			var set = new HashSet<string>(StringComparer.Ordinal);
			foreach (var line in Strings(tier.Value, "tierLines." + tier.Name))
			{
				if (!lines.TryGetProperty(line, out _))
					throw new FormatException("tierLines." + tier.Name + " names unknown line " + line);
				set.Add(line);
			}
			c.TierLines[rank] = set;
		}
		if (!root.TryGetProperty("pairs", out var pairs) || pairs.ValueKind != JsonValueKind.Array)
			throw new FormatException("pairs missing");
		foreach (var item in pairs.EnumerateArray())
		{
			var pair = new Pair
			{
				A = Str(item, "a"),
				B = Str(item, "b"),
				Host = Str(item, "host"),
				Guest = Str(item, "guest"),
				Fused = Str(item, "fused"),
				Name = Str(item, "name"),
			};
			if (pair.A == null || pair.B == null || pair.Fused == null)
				throw new FormatException("pair needs a, b and fused");
			if (string.Equals(pair.A, pair.B, StringComparison.Ordinal))
				throw new FormatException("pair " + pair.A + " fuses with itself");
			if (!c.LineByUnit.ContainsKey(pair.A) || !c.LineByUnit.ContainsKey(pair.B))
				throw new FormatException("pair " + pair.A + "+" + pair.B + " names a unit outside lines");
			if (!pair.Fused.StartsWith("h3_fusion_", StringComparison.Ordinal))
				throw new FormatException("fused sid " + pair.Fused + " does not start with h3_fusion_");
			var key = PairKey(pair.A, pair.B);
			if (c._pairByKey.ContainsKey(key))
				throw new FormatException("pair " + key + " listed twice");
			c._pairByKey[key] = pair;
			c.Pairs.Add(pair);
			c.FusedUnits.Add(pair.Fused);
		}
		// Optional second fusions: two named stage-1 fused units -> one stage-2 unit.
		if (root.TryGetProperty("recipeMinRank", out var minRank) && minRank.ValueKind == JsonValueKind.Number && minRank.TryGetInt32(out var mr))
		{
			if (mr < 1 || mr > 3)
				throw new FormatException("recipeMinRank " + mr + " is not 1..3");
			c.RecipeMinRank = mr;
		}
		if (root.TryGetProperty("recipes", out var recipes) && recipes.ValueKind == JsonValueKind.Array)
		{
			var stageOne = new HashSet<string>(c.FusedUnits, StringComparer.Ordinal);
			foreach (var item in recipes.EnumerateArray())
			{
				var pair = new Pair
				{
					A = Str(item, "a"),
					B = Str(item, "b"),
					Host = Str(item, "host"),
					Guest = Str(item, "guest"),
					Fused = Str(item, "fused"),
					Name = Str(item, "name"),
					Stage = 2,
				};
				if (pair.A == null || pair.B == null || pair.Fused == null)
					throw new FormatException("recipe needs a, b and fused");
				if (string.Equals(pair.A, pair.B, StringComparison.Ordinal))
					throw new FormatException("recipe " + pair.A + " fuses with itself");
				if (!stageOne.Contains(pair.A) || !stageOne.Contains(pair.B))
					throw new FormatException("recipe " + pair.A + "+" + pair.B + " names a unit that is not a stage-1 fusion");
				if (!pair.Fused.StartsWith("h3_fusion_", StringComparison.Ordinal) || c.FusedUnits.Contains(pair.Fused))
					throw new FormatException("recipe fused sid " + pair.Fused + " is not a new h3_fusion_ unit");
				var key = PairKey(pair.A, pair.B);
				if (c._pairByKey.ContainsKey(key))
					throw new FormatException("recipe " + key + " listed twice");
				c._pairByKey[key] = pair;
				c.Pairs.Add(pair);
				c.FusedUnits.Add(pair.Fused);
				c.RecipeUnits.Add(pair.A);
				c.RecipeUnits.Add(pair.B);
			}
		}
		// Optional: extra units whose Wall of Flame trap scales with their stack (beyond the Lava Elemental's fusions).
		if (root.TryGetProperty("firewallPlacers", out var placers) && placers.ValueKind == JsonValueKind.Array)
		{
			foreach (var sid in Strings(placers, "firewallPlacers"))
				c.FirewallPlacers.Add(sid);
		}
		return c;
	}

	private static string Str(JsonElement obj, string name)
	{
		return obj.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(v.GetString()) ? v.GetString().Trim() : null;
	}

	private static decimal Dec(JsonElement obj, string name)
	{
		if (obj.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetDecimal(out var d))
			return d;
		throw new FormatException(name + " missing or not a number");
	}

	private static List<string> Strings(JsonElement array, string label)
	{
		if (array.ValueKind != JsonValueKind.Array)
			throw new FormatException(label + " is not an array");
		var list = new List<string>();
		foreach (var item in array.EnumerateArray())
		{
			if (item.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(item.GetString()))
				throw new FormatException(label + " holds a non-string");
			list.Add(item.GetString().Trim());
		}
		return list;
	}
}
