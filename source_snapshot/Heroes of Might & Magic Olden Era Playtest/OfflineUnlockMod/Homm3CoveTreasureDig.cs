using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using DataHero = Hex.Session.Data.Hero;
using DataRoot = Hex.Session.Data.Data;
using LogicHero = Hex.Session.Logic.Hero;
using Plan = OfflineUnlockMod.Homm3CoveTreasurePlan;
using R = OfflineUnlockMod.Homm3CoveTreasureRuntime;
using WorldHero = ObjectPublicHeObInObcqSiObVeBoObUnique;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting, Dig (docs/cove_treasure_hunting_design.md section 6.2 and 6.3).
///
/// Dig is a 0-mana adventure spell: a clone of the native Necromancer Will world magic whose [mode] parameter is
/// <see cref="SpellMode"/>. This prefix recognises the mode, skips the native toggle and digs on the caster's tile.
/// - Needs at least 2/3 of the hero's daily movement (highest movement seen today) and sets movement to 0.
/// - The region's true tile pays the treasure once, to whoever digs first. Any other tile leaves a hole; a hole on a
///   false lead removes that lead for every side. A refused dig (road, water, hole already there, no skill) is free.
/// - Payout: gold and resources to the side, units into the hero's army, artifact to the hero. Anything that cannot
///   be delivered (full army, grant refused) is paid as its gold value instead, so a treasure is never lost.
/// Only local human heroes dig; an AI cast is a no-op success. Proof tier: build only; runtime unproven.
/// </summary>
internal static class Homm3CoveTreasureDig
{
	internal const string SpellMode = "homm3_cove_dig";
	private const int MoveNumerator = 2;
	private const int MoveDenominator = 3;

	private static ManualLogSource _log;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static MethodInfo _setMovePoints;
	private static Type _setMovePointsOwner;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		_log = log;
		MethodInfo castMethod = null;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var handlerType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.cove.treasure.necromancyHandler");
			castMethod = Homm3TowerArtificingRuntime.ResolveExactMethod(handlerType, typeof(bool), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast);
			_handlerWorldHeroProperty = handlerType.GetProperty(GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                            ?? throw new MissingMemberException(handlerType.FullName, "world hero property");
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3CoveTreasureDig), castMethod, nameof(PrefixSpellCast), null);
			log?.LogInfo(R.LogPrefix + "Dig spell prefix registered for mode " + SpellMode + ".");
		}
		catch (Exception ex)
		{
			log?.LogError(R.LogPrefix + "Dig spell hook NOT registered (the Dig spell would reach the native Necromancer Will toggle): " + ex.GetBaseException().Message);
		}
	}

	private static void Info(string message)
	{
		if (_logged++ < 200)
			_log?.LogInfo(R.LogPrefix + "dig: " + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < 200)
			_log?.LogWarning(R.LogPrefix + "dig: " + message);
	}

	private static string N(int value) => value.ToString(CultureInfo.InvariantCulture);

	private static bool PrefixSpellCast(object __instance, ref bool __result)
	{
		try
		{
			var setting = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			string mode = null;
			if (setting?.parameters is IEnumerable en)
			{
				foreach (var p in en)
				{
					mode = p as string ?? p?.ToString();
					break;
				}
			}
			else if (setting?.parameters != null)
			{
				foreach (var p in Homm3FactoryLogisticsEffects.Enumerate(setting.parameters))
				{
					mode = p as string ?? p?.ToString();
					break;
				}
			}
			if (!string.Equals(mode, SpellMode, StringComparison.Ordinal))
				return true;
			// Free spell with no native effect: always the native success shape, so the AI never retries a "failed" cast.
			__result = true;
			var worldHero = _handlerWorldHeroProperty != null && _handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(__instance) ? _handlerWorldHeroProperty.GetValue(__instance) : null;
			if (!Homm3FactoryLogisticsRuntime.TryResolveHeroFromWorldHero(worldHero, out var logicHero, out var dataHero))
			{
				Warn("casting hero unresolved; nothing dug.");
				return false;
			}
			if (!Homm3FactoryLogisticsRuntime.IsLocalHuman(dataHero.sideId))
				return false;
			Dig(worldHero, logicHero, dataHero);
			return false;
		}
		catch (Exception ex)
		{
			Warn("cast threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
			__result = true;
			return false;
		}
	}

	private static void Dig(object worldHero, LogicHero logicHero, DataHero hero)
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out var dataFail) || data == null)
		{
			Banner("Dig is not available right now.");
			Warn("session data unavailable: " + dataFail);
			return;
		}
		if (!R.CheckDig(data, hero, out var refusal))
		{
			Banner(refusal);
			return;
		}
		Homm3CoveTreasureSubskills.Remember(logicHero, hero);
		// Tireless Captain: Dig needs no movement and spends none.
		var tireless = Homm3CoveTreasureSubskills.Has(hero, Homm3CoveTreasureSubskills.TirelessCaptain);
		var now = hero.worldMovePoints;
		var max = R.MaxMoveToday(data, hero);
		// Rounded up: with 2000 a day, 1334 are needed.
		var need = (max * MoveNumerator + MoveDenominator - 1) / MoveDenominator;
		// law pass 2026-11-25: Quick Shovels (#20) is replaced by Treasure Fever, so the dig cost is the skill's again
		// (Tireless Captain is the only way to dig cheaper).
		if (!tireless && (now < need || now <= 0))
		{
			Banner("Digging takes most of a day. This hero needs at least two thirds of its daily movement left.");
			Info("hero " + hero.configSid + " refused: movement " + N(now) + " of " + N(max) + ", needs " + N(need) + ".");
			return;
		}
		string moveFail = null;
		if (!tireless && !TrySpendAllMovement(worldHero, hero, out moveFail))
		{
			Banner("Dig is not available right now.");
			Warn("movement not spent (" + moveFail + "); dig refused so it cannot be free.");
			return;
		}
		var outcome = R.CommitDig(data, hero, out var contents, out var areaId);
		switch (outcome)
		{
			case R.DigOutcome.Treasure:
				var found = Pay(worldHero, logicHero, hero, contents);
				var collector = Homm3CoveTreasureSubskills.OnTreasureDug(logicHero, hero);
				if (collector != null)
					found.Add(collector);
				// law pass 2026-11-25: Treasure Fever (#20)
				var fever = Homm3CoveLawHooks.GrantTreasureFeverXp(logicHero, hero, Warn);
				if (fever != null)
					found.Add(fever);
				Homm3CoveTreasurePopup.ShowTreasure(found, movementSpent: !tireless);
				break;
			case R.DigOutcome.Hole:
				Homm3CoveTreasurePopup.ShowHole(R.IsFalseLead(areaId, hero.node), movementSpent: !tireless);
				break;
			default:
				Warn("commit refused after the movement was spent (area " + N(areaId) + ").");
				break;
		}
	}

	private static void Banner(string text, int lines = 1)
	{
		try { Homm3DungeonWarCaptivesWindow.ShowBanner(text, lines); }
		catch (Exception ex) { Warn("banner failed: " + ex.GetBaseException().Message); }
	}

	// ---------------------------------------------------------------- movement

	/// <summary>Sets the hero's movement to 0 through the native move-point controller (refreshes the HUD and path).</summary>
	private static bool TrySpendAllMovement(object worldHero, DataHero hero, out string fail) => TrySetMovement(worldHero, hero, 0, out fail);

	/// <summary>Sets the hero's movement points through its controller and reads them back (only TrySpendAllMovement calls it since Quick Shovels was replaced, law pass 2026-11-25).</summary>
	private static bool TrySetMovement(object worldHero, DataHero hero, int target, out string fail)
	{
		fail = null;
		if (target < 0)
			target = 0;
		var controller = worldHero == null ? null : Homm3TowerArtificingRuntime.ReadMember(worldHero, GameSymbols.HomecomingBoatTravel.WorldHeroMovePointControllerMembers);
		if (controller == null)
		{
			fail = "move-point controller unreadable (HomecomingBoatTravel.WorldHeroMovePointControllerMembers)";
			return false;
		}
		var type = controller.GetType();
		if (_setMovePointsOwner != type)
		{
			_setMovePointsOwner = type;
			_setMovePoints = GameMember.FindFirstMethodByNames(type, new[] { typeof(int) }, GameSymbols.HomecomingBoatTravel.MovePointControllerSetWorldMovePoints);
			if (_setMovePoints != null && _setMovePoints.ReturnType != typeof(void))
				_setMovePoints = null;
		}
		if (_setMovePoints == null)
		{
			fail = "set-move-points unresolved on " + type.Name + " (HomecomingBoatTravel.MovePointControllerSetWorldMovePoints)";
			return false;
		}
		var before = hero.worldMovePoints;
		_setMovePoints.Invoke(controller, new object[] { target });
		var after = hero.worldMovePoints;
		if (after != target)
		{
			fail = "readback " + N(before) + "->" + N(after) + " is not " + N(target);
			return false;
		}
		return true;
	}

	// ---------------------------------------------------------------- payout

	/// <summary>Delivers the treasure and returns the player-facing list of what was found.</summary>
	private static List<string> Pay(object worldHero, LogicHero logicHero, DataHero hero, Plan.Contents contents)
	{
		var found = new List<string>();
		var side = hero.sideId;
		// law pass 2026-11-21: King's Ransom (#27). Applied at payout (the region value is stored in the save) to the
		// rolled Gold and resources only; units, artifacts and their gold fallbacks are unchanged.
		var ransom = Homm3CoveLawHooks.KingsRansomPercent(side);
		var gold = Homm3CoveLawHooks.ApplyRansom(contents.Gold, ransom);
		if (ransom > 0)
			Info("King's Ransom +" + N(ransom) + "%: gold " + N(contents.Gold) + " -> " + N(gold) + ".");

		if (contents.UnitSid != null && contents.UnitCount > 0)
		{
			if (TryAddUnits(logicHero, hero, contents.UnitSid, contents.UnitCount, out var unitFail))
				found.Add("Joined your army: " + N(contents.UnitCount) + " " + Pretty(contents.UnitSid));
			else
			{
				gold += contents.UnitValue;
				Info("units " + N(contents.UnitCount) + " " + contents.UnitSid + " not added (" + unitFail + "): paid " + N(contents.UnitValue) + " gold instead.");
			}
		}

		if (contents.ArtifactSid != null)
		{
			if (TryGrantArtifact(worldHero, contents.ArtifactSid, out var itemFail))
				found.Add("Artifact: " + Pretty(contents.ArtifactSid));
			else
			{
				gold += contents.ArtifactValue;
				Info("artifact " + contents.ArtifactSid + " not granted (" + itemFail + "): paid " + N(contents.ArtifactValue) + " gold instead.");
			}
		}

		if (gold > 0)
		{
			if (Homm3CovePlunderHook.Grant(side, GameSymbols.EconomyLaws.GoldResourceName, gold, out _, out _, out var goldFail))
				found.Insert(0, N(gold) + " gold");
			else
				Warn("gold " + N(gold) + " not paid to side " + N(side) + ": " + goldFail);
		}
		foreach (var (name, rolled) in contents.Resources)
		{
			var amount = Homm3CoveLawHooks.ApplyRansom(rolled, ransom);
			if (amount <= 0)
				continue;
			if (Homm3CovePlunderHook.Grant(side, name, amount, out _, out _, out var resFail))
				found.Add(N(amount) + " " + Pretty(name));
			else
				Warn(N(amount) + " " + name + " not paid to side " + N(side) + ": " + resFail);
		}
		Info("paid side " + N(side) + " hero " + hero.configSid + ": " + (found.Count == 0 ? "nothing" : string.Join(", ", found)) + ".");
		return found;
	}

	/// <summary>A computer side's treasure (Homm3CoveTreasureAi): paid to the hero when it is still on the map, else as gold.</summary>
	internal static void PayAi(object worldHero, Plan.Contents contents, int side)
	{
		try
		{
			if (Homm3FactoryLogisticsRuntime.TryResolveHeroFromWorldHero(worldHero, out var logicHero, out var hero) && hero != null
				&& hero.status == Hex.Session.Data.EHeroStatus.OnMap && hero.sideId == side)
			{
				Pay(worldHero, logicHero, hero, contents);
				Homm3CoveTreasureSubskills.OnTreasureDug(logicHero, hero);
				// law pass 2026-11-25: Treasure Fever (#20)
				Homm3CoveLawHooks.GrantTreasureFeverXp(logicHero, hero, Warn);
				return;
			}
			var gold = contents.Total();
			if (Homm3CovePlunderHook.Grant(side, GameSymbols.EconomyLaws.GoldResourceName, gold, out _, out _, out var fail))
				Info("computer side " + N(side) + ": digging hero is gone, treasure paid as " + N(gold) + " gold.");
			else
				Warn("gold " + N(gold) + " not paid to computer side " + N(side) + ": " + fail);
		}
		catch (Exception ex)
		{
			Warn("computer payout threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Adds the units to a stack of the same kind, else to the first empty army slot.</summary>
	private static bool TryAddUnits(LogicHero logicHero, DataHero hero, string sid, int count, out string fail)
	{
		if (!Homm3PartyArmyWriter.IsResolved && !Homm3PartyArmyWriter.TryResolve(typeof(LogicHero), out fail))
			return false;
		if (!Homm3PartyArmyWriter.TryReadArmy(logicHero, hero, out var slotSid, out var slotCount, out var totals, out fail))
			return false;
		var slot = Array.IndexOf(slotSid, sid);
		if (slot < 0)
			slot = Array.IndexOf(slotSid, null);
		if (slot < 0)
		{
			fail = "no free army slot";
			return false;
		}
		slotSid[slot] = sid;
		slotCount[slot] += count;
		var steps = new List<string>();
		var result = Homm3PartyArmyWriter.Write(logicHero, hero, slotSid, slotCount, totals, steps, out fail);
		if (result == Homm3PartyArmyWriter.WriteResult.Written)
			return true;
		if (result != Homm3PartyArmyWriter.WriteResult.Refused)
		{
			// The army may already hold the units: do not also pay gold for them.
			Warn("army write " + result + " (" + fail + "); steps: " + string.Join(" | ", steps));
			fail = null;
			return true;
		}
		return false;
	}

	/// <summary>Native "give this hero an item" (world hero, Ghidra 26615913); unverified in game.</summary>
	private static bool TryGrantArtifact(object worldHero, string sid, out string fail)
	{
		fail = null;
		try
		{
			var typed = (worldHero as Il2CppSystem.Object)?.TryCast<WorldHero>();
			if (typed == null)
			{
				fail = "world hero is not the expected type";
				return false;
			}
			if (typed.Method_Public_Boolean_String_Int32_0(sid, 1))
				return true;
			fail = "native grant returned false";
			return false;
		}
		catch (Exception ex)
		{
			fail = ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>The in-game English name from the catalog; an id it does not name reads "Steel Golem Upg".</summary>
	private static string Pretty(string sid)
	{
		var named = R.DisplayName(sid);
		if (named != null)
			return named;
		var words = (sid ?? "").Split(new[] { '_' }, StringSplitOptions.RemoveEmptyEntries);
		var text = new System.Text.StringBuilder();
		foreach (var word in words)
		{
			if (word == "h3")
				continue;
			if (text.Length > 0)
				text.Append(' ');
			text.Append(char.ToUpperInvariant(word[0])).Append(word, 1, word.Length - 1);
		}
		return text.Length == 0 ? sid : text.ToString();
	}
}
