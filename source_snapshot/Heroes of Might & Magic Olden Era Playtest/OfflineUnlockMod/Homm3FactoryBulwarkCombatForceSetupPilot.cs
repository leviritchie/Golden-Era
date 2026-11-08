using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Pilot-only force-setup for Factory Split Assembly C3–C5 and Bulwark Runes Phase A/B
/// fixtures. Off by default. Enable only with the diagnostic flag file plus a local JSON
/// config under the plugin folder. Release-safe profiles must leave this dormant.
/// Additive and removable: delete the flag, config, and this type to unwind.
/// </summary>
internal static class Homm3FactoryBulwarkCombatForceSetupPilot
{
	internal const string PilotFlag = "homm3_factory_bulwark_combat_force_setup_pilot.flag";
	internal const string ConfigFileName = "homm3_factory_bulwark_combat_force_setup.json";

	private const string FactoryFactionSid = "homm3_factory";
	private const string BulwarkFactionSid = "homm3_bulwark";
	private const string FactorySkillSid = "skill_faction_homm3_factory";
	private const string BulwarkSkillSid = "skill_faction_homm3_bulwark";
	private const string NaturalOverclockSubSkillSid = "sub_skill_faction_homm3_factory_gantry_reserve";
	private const string IndustrialOverclockSubSkillSid = "sub_skill_faction_homm3_factory_industrial_tempo";

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PilotConfig _config;
	private static int _loggedApplies;

	private sealed class PilotConfig
	{
		internal string FactionSid;
		internal int SkillRank = 3;
		internal bool AttachOverclockSubskills;
		internal List<ArmySlot> StartArmy = new();
	}

	private sealed class ArmySlot
	{
		internal string UnitSid;
		internal int Count = 10;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		if (!Homm3DiagnosticFlags.IsEnabled(PilotFlag))
		{
			_log?.LogInfo(
				"HoMM3 Factory/Bulwark combat force-setup pilot idle (flag absent). "
				+ "Create "
				+ PilotFlag
				+ " and "
				+ ConfigFileName
				+ " under OfflineUnlockMod for Golden Era combat fixtures only.");
			return;
		}

		try
		{
			_config = LoadRequiredConfig();
			var hexAssembly = typeof(TransferBattle).Assembly;
			var battleLogicType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.DraconicDominion.BattleLogicTypeHints,
				"homm3.factoryBulwark.forceSetup.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.factoryBulwark.forceSetup.transferBattle");
			var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.factoryBulwark.forceSetup.battleLogic.init",
				method => !method.IsStatic);
			var logicHeroType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.CastleEliteStrategem.LogicHeroTypeName,
				"homm3.factoryBulwark.forceSetup.logicHero");
			_logicHeroDataHeroGetter = ResolveRequiredExactNamedMethod(
				logicHeroType,
				typeof(DataHero),
				Type.EmptyTypes,
				GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints[0],
				"homm3.factoryBulwark.forceSetup.logicHero.dataHeroGetter",
				method => !method.IsStatic);

			var prefix = AccessTools.Method(typeof(Homm3FactoryBulwarkCombatForceSetupPilot), nameof(PrefixBattleLogicInit));
			var patch = new HarmonyMethod(prefix) { priority = Priority.First };
			harmony.Patch(battleLogicInitMethod, prefix: patch);
			_registered = true;
			_log?.LogWarning(
				"HoMM3 Factory/Bulwark combat force-setup PILOT ACTIVE: faction="
				+ _config.FactionSid
				+ " skillRank="
				+ _config.SkillRank
				+ " overclock="
				+ _config.AttachOverclockSubskills
				+ " armySlots="
				+ _config.StartArmy.Count
				+ ". Not for release play. Remove "
				+ PilotFlag
				+ " after the fixture.");
		}
		catch (Exception ex)
		{
			_log?.LogError(
				"HoMM3 Factory/Bulwark combat force-setup pilot failed closed at register: "
				+ ex.Message);
			throw;
		}
	}

	private static void PrefixBattleLogicInit(object __1)
	{
		try
		{
			ApplyForceSetup(__1 as TransferBattle);
		}
		catch (Exception ex)
		{
			// Never abort BattleLogic.Init: this prefix also runs during adventure
			// map / session Loader paths. Soft-skip so a forgotten pilot flag or
			// fixture mismatch cannot brick map load (CapLog: InvalidOperation
			// here cascaded into Hex.Session.Loader.lqo NRE).
			_log?.LogError(
				"HoMM3 Factory/Bulwark combat force-setup pilot soft-skipped during battle init (will not abort Init): "
				+ ex.Message);
		}
	}

	private static void ApplyForceSetup(TransferBattle transferBattle)
	{
		if (transferBattle?.sides == null || _config == null)
			return;

		var matched = 0;
		foreach (var side in transferBattle.sides)
		{
			if (side?.logicHero == null)
				continue;
			if (!TryResolveDataHero(side, out var dataHero, out var heroFail))
			{
				LogLimited("side skipped: " + heroFail);
				continue;
			}

			if (!SideMatchesConfiguredFaction(side, dataHero))
				continue;

			if (!TryForceFactionSkill(dataHero, out var skillFail))
				throw new InvalidOperationException("force skill failed: " + skillFail);

			if (_config.AttachOverclockSubskills
			    && string.Equals(_config.FactionSid, FactoryFactionSid, StringComparison.Ordinal)
			    && !TryAttachFactoryOverclockSubskills(dataHero, out var overclockFail))
			{
				throw new InvalidOperationException("force overclock subskills failed: " + overclockFail);
			}

			if (_config.StartArmy.Count > 0 && !TryForceStartArmy(side, out var armyFail))
				throw new InvalidOperationException("force start army failed: " + armyFail);

			matched++;
			if (_loggedApplies++ < 12)
			{
				_log?.LogWarning(
					"HoMM3 Factory/Bulwark combat force-setup applied: faction="
					+ _config.FactionSid
					+ " skillRank="
					+ _config.SkillRank
					+ " overclock="
					+ _config.AttachOverclockSubskills
					+ " armySlots="
					+ _config.StartArmy.Count
					+ ".");
			}
		}

		if (matched == 0)
		{
			// Soft-skip: a forgotten pilot flag must not brick unrelated map/battle loads.
			_log?.LogWarning(
				"HoMM3 Factory/Bulwark combat force-setup matched no TransferSide for factionSid="
				+ _config.FactionSid
				+ "; skipping apply (start a battle with that faction hero/army, or remove "
				+ PilotFlag
				+ ").");
		}
	}

	private static bool SideMatchesConfiguredFaction(TransferSide side, DataHero dataHero)
	{
		if (SideContainsConfiguredFactionUnit(side))
			return true;

		var skillSid = string.Equals(_config.FactionSid, FactoryFactionSid, StringComparison.Ordinal)
			? FactorySkillSid
			: BulwarkSkillSid;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (string.Equals(sid, skillSid, StringComparison.Ordinal))
				return true;
		}

		var heroSid = NormalizeSid(TryReadString(dataHero, GameSymbols.DraconicDominion.DataHeroSidMembers));
		if (heroSid != null
		    && heroSid.StartsWith(_config.FactionSid + "_hero_", StringComparison.Ordinal))
			return true;

		return false;
	}

	private static bool SideContainsConfiguredFactionUnit(TransferSide side)
	{
		if (side?.units == null)
			return false;
		foreach (var unit in side.units)
		{
			var sid = NormalizeSid(unit?.configSid);
			if (sid != null
			    && Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sid, out var factionSid)
			    && string.Equals(factionSid, _config.FactionSid, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryForceFactionSkill(DataHero dataHero, out string failReason)
	{
		failReason = null;
		var skillSid = string.Equals(_config.FactionSid, FactoryFactionSid, StringComparison.Ordinal)
			? FactorySkillSid
			: BulwarkSkillSid;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (skillList == null)
		{
			failReason = "data-Hero skills list missing";
			return false;
		}

		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, skillSid, StringComparison.Ordinal))
				continue;
			if (!TryWriteInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers, _config.SkillRank))
			{
				failReason = "could not write faction skill level=" + _config.SkillRank;
				return false;
			}
			return true;
		}

		failReason = "faction skill '" + skillSid + "' not present on DataHero";
		return false;
	}

	private static bool TryAttachFactoryOverclockSubskills(DataHero dataHero, out string failReason)
	{
		failReason = null;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		object factorySkill = null;
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, FactorySkillSid, StringComparison.Ordinal))
				continue;
			factorySkill = heroSkill;
			break;
		}
		if (factorySkill == null)
		{
			failReason = "Factory skill row missing for overclock attach";
			return false;
		}

		var required = new[] { NaturalOverclockSubSkillSid, IndustrialOverclockSubSkillSid };
		foreach (var subSkillSid in required)
		{
			if (HasSubSkill(factorySkill, subSkillSid))
				continue;
			if (!TryAppendSubSkill(factorySkill, subSkillSid, out failReason))
				return false;
		}
		return true;
	}

	private static bool HasSubSkill(object heroSkill, string subSkillSid)
	{
		var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
		foreach (var subSkill in EnumerateObjects(subSkills))
		{
			var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers));
			if (string.Equals(sid, subSkillSid, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryAppendSubSkill(object heroSkill, string subSkillSid, out string failReason)
	{
		failReason = null;
		var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
		if (subSkills == null)
		{
			failReason = "Factory skill subSkills collection missing";
			return false;
		}

		object donor = null;
		foreach (var existing in EnumerateObjects(subSkills))
		{
			donor = existing;
			break;
		}
		if (donor == null)
		{
			failReason =
				"Factory skill has empty subSkills; cannot clone a donor row for "
				+ subSkillSid
				+ " (pick Expert subskills in-game once, or start a hero that already owns one)";
			return false;
		}

		object clone;
		try
		{
			clone = Activator.CreateInstance(donor.GetType());
		}
		catch (Exception ex)
		{
			failReason = "Activator.CreateInstance for HeroSubSkill failed: " + ex.Message;
			return false;
		}
		if (clone == null)
		{
			failReason = "Activator.CreateInstance returned null for HeroSubSkill";
			return false;
		}
		if (!TryWriteString(clone, GameSymbols.DraconicDominion.HeroSubSkillSidMembers, subSkillSid))
		{
			failReason = "could not write subskill sid=" + subSkillSid;
			return false;
		}
		if (!TryAddToCollection(subSkills, clone, out failReason))
			return false;
		return true;
	}

	private static bool TryForceStartArmy(TransferSide side, out string failReason)
	{
		failReason = null;
		if (side?.units == null)
		{
			failReason = "TransferSide.units missing";
			return false;
		}
		if (side.units.Length < _config.StartArmy.Count)
		{
			failReason =
				"TransferSide has "
				+ side.units.Length
				+ " unit slots but force-setup startArmy needs "
				+ _config.StartArmy.Count;
			return false;
		}

		for (var i = 0; i < _config.StartArmy.Count; i++)
		{
			var slot = _config.StartArmy[i];
			var unit = side.units[i];
			if (unit == null)
			{
				failReason = "TransferUnit slot " + i + " is null";
				return false;
			}
			if (!Homm3CustomFactionRegistry.IsCustomUnitSid(slot.UnitSid)
			    || !Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(slot.UnitSid, out var factionSid)
			    || !string.Equals(factionSid, _config.FactionSid, StringComparison.Ordinal))
			{
				failReason =
					"startArmy["
					+ i
					+ "] unitSid '"
					+ slot.UnitSid
					+ "' is not an owned "
					+ _config.FactionSid
					+ " unit";
				return false;
			}
			unit.configSid = slot.UnitSid;
			if (!TryWriteUnitCount(unit, slot.Count, out failReason))
				return false;
		}
		return true;
	}

	private static bool TryWriteUnitCount(TransferUnit unit, int count, out string failReason)
	{
		failReason = null;
		foreach (var name in new[] { "count", "stacks", "Amount", "amount" })
		{
			if (TryWriteIntMember(unit, name, count))
				return true;
		}
		// Line-count fixtures only need configSid; count write is best-effort once SID is set.
		_log?.LogWarning(
			"HoMM3 Factory/Bulwark combat force-setup could not write TransferUnit count="
			+ count
			+ "; configSid was set. Combat stack size may remain the map/skirmish default.");
		return true;
	}

	private static PilotConfig LoadRequiredConfig()
	{
		var path = ResolveConfigPath();
		if (!File.Exists(path))
		{
			throw new FileNotFoundException(
				"pilot flag is present but config is missing: "
				+ path
				+ " (see docs/homm3_faction_proofs/factory_bulwark/README.md)");
		}

		var json = File.ReadAllText(path);
		var factionSid = ReadRequiredString(json, "factionSid");
		if (!string.Equals(factionSid, FactoryFactionSid, StringComparison.Ordinal)
		    && !string.Equals(factionSid, BulwarkFactionSid, StringComparison.Ordinal))
		{
			throw new InvalidOperationException(
				"factionSid must be homm3_factory or homm3_bulwark, got '" + factionSid + "'");
		}

		var skillRank = ReadInt(json, "skillRank", 3);
		if (skillRank < 1 || skillRank > 3)
			throw new InvalidOperationException("skillRank must be 1..3, got " + skillRank);

		var attachOverclock = ReadBool(json, "attachOverclockSubskills", false);
		if (attachOverclock && !string.Equals(factionSid, FactoryFactionSid, StringComparison.Ordinal))
		{
			throw new InvalidOperationException(
				"attachOverclockSubskills is Factory-only; unset it for Bulwark Runes fixtures");
		}

		var army = ParseStartArmy(json);
		return new PilotConfig
		{
			FactionSid = factionSid,
			SkillRank = skillRank,
			AttachOverclockSubskills = attachOverclock,
			StartArmy = army,
		};
	}

	private static List<ArmySlot> ParseStartArmy(string json)
	{
		var army = new List<ArmySlot>();
		var match = Regex.Match(
			json,
			"\"startArmy\"\\s*:\\s*\\[(?<body>.*?)\\]",
			RegexOptions.Singleline | RegexOptions.IgnoreCase);
		if (!match.Success)
			return army;

		foreach (Match entry in Regex.Matches(
			         match.Groups["body"].Value,
			         "\\{(?<obj>[^{}]*)\\}",
			         RegexOptions.Singleline))
		{
			var body = entry.Groups["obj"].Value;
			var unitSid = ReadRequiredString("{" + body + "}", "unitSid");
			var count = ReadInt("{" + body + "}", "count", 10);
			if (count < 1)
				throw new InvalidOperationException("startArmy count must be >= 1 for " + unitSid);
			army.Add(new ArmySlot { UnitSid = unitSid, Count = count });
		}
		if (army.Count > 7)
			throw new InvalidOperationException("startArmy may not exceed 7 slots");
		return army;
	}

	private static string ResolveConfigPath()
	{
		var pluginLocal = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", ConfigFileName);
		if (File.Exists(pluginLocal))
			return pluginLocal;
		return Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", ConfigFileName);
	}

	private static bool TryResolveDataHero(TransferSide side, out DataHero dataHero, out string failReason)
	{
		dataHero = null;
		failReason = null;
		if (_logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(side.logicHero))
		{
			failReason = "LogicHero data-Hero getter unavailable";
			return false;
		}
		try
		{
			dataHero = _logicHeroDataHeroGetter.Invoke(side.logicHero, Array.Empty<object>()) as DataHero;
		}
		catch (Exception ex)
		{
			failReason = "LogicHero data-Hero resolution failed: " + ex.GetBaseException().Message;
			return false;
		}
		if (dataHero == null)
		{
			failReason = "LogicHero data-Hero missing";
			return false;
		}
		return true;
	}

	private static bool TryAddToCollection(object collection, object item, out string failReason)
	{
		failReason = null;
		var add = collection.GetType().GetMethod("Add", new[] { item.GetType() })
			?? collection.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
				.FirstOrDefault(method =>
					method.Name == "Add"
					&& method.GetParameters().Length == 1
					&& method.GetParameters()[0].ParameterType.IsInstanceOfType(item));
		if (add == null)
		{
			failReason = "subSkills collection has no Add method for " + item.GetType().FullName;
			return false;
		}
		try
		{
			add.Invoke(collection, new[] { item });
			return true;
		}
		catch (Exception ex)
		{
			failReason = "subSkills.Add failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool TryWriteInt(object target, IEnumerable<string> names, int value)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (TryWriteIntMember(target, name, value))
				return true;
		}
		return false;
	}

	private static bool TryWriteIntMember(object target, string name, int value)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		var field = type.GetField(name, flags);
		if (field != null && field.FieldType == typeof(int) && !field.IsInitOnly)
		{
			field.SetValue(target, value);
			return true;
		}
		var property = type.GetProperty(name, flags);
		if (property != null && property.PropertyType == typeof(int) && property.CanWrite)
		{
			property.SetValue(target, value);
			return true;
		}
		return false;
	}

	private static bool TryWriteString(object target, IEnumerable<string> names, string value)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (TryWriteStringMember(target, name, value))
				return true;
		}
		return false;
	}

	private static bool TryWriteStringMember(object target, string name, string value)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		var field = type.GetField(name, flags);
		if (field != null && field.FieldType == typeof(string) && !field.IsInitOnly)
		{
			field.SetValue(target, value);
			return true;
		}
		var property = type.GetProperty(name, flags);
		if (property != null && property.PropertyType == typeof(string) && property.CanWrite)
		{
			property.SetValue(target, value);
			return true;
		}
		return false;
	}

	private static object ReadMember(object target, IEnumerable<string> names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.CanRead)
				return property.GetValue(target);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(target);
		}
		return null;
	}

	private static string TryReadString(object target, IEnumerable<string> names)
	{
		return ReadMember(target, names) as string;
	}

	/// <summary>
	/// Prefer Count + int indexer for Il2Cpp skill lists; managed foreach on
	/// <see cref="IEnumerable"/> often yields nothing (same root cause as Split Assembly
	/// missing <c>skill_faction_homm3_factory</c> despite Session::Logic listing it).
	/// </summary>
	private static IEnumerable<object> EnumerateObjects(object list)
	{
		if (list == null)
			yield break;

		var type = list.GetType();
		var count = TryReadCount(list, type);
		var indexer = ResolveIntIndexer(type);
		if (count != null && count.Value > 0 && indexer != null)
		{
			for (var i = 0; i < count.Value; i++)
			{
				object item = null;
				try
				{
					item = indexer.Invoke(list, new object[] { i });
				}
				catch
				{
				}

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

	private static int? TryReadCount(object value, Type type)
	{
		if (value == null || type == null)
			return null;
		try
		{
			var property = type.GetProperty("Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (property != null && property.GetIndexParameters().Length == 0 && property.GetValue(value, null) is int propertyCount)
				return propertyCount;
		}
		catch
		{
		}

		try
		{
			var method = type.GetMethod("get_Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method != null && method.GetParameters().Length == 0 && method.Invoke(value, Array.Empty<object>()) is int methodCount)
				return methodCount;
		}
		catch
		{
		}

		return null;
	}

	private static MethodInfo ResolveIntIndexer(Type type)
	{
		if (type == null)
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType == typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length == 1
			    && parameters[0].ParameterType == typeof(int)
			    && (string.Equals(method.Name, "get_Item", StringComparison.Ordinal)
			        || string.Equals(method.Name, "get_ItemOf", StringComparison.Ordinal)))
				return method;
		}

		return null;
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static void LogLimited(string message)
	{
		if (_loggedApplies++ < 24)
			_log?.LogWarning("HoMM3 Factory/Bulwark combat force-setup: " + message);
	}

	private static string ReadRequiredString(string json, string key)
	{
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"",
			RegexOptions.IgnoreCase);
		if (!match.Success)
			throw new InvalidOperationException("config missing string '" + key + "'");
		return Regex.Unescape(match.Groups[1].Value).Trim();
	}

	private static int ReadInt(string json, string key, int fallback)
	{
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?\\d+)",
			RegexOptions.IgnoreCase);
		if (!match.Success || !int.TryParse(match.Groups[1].Value, out var value))
			return fallback;
		return value;
	}

	private static bool ReadBool(string json, string key, bool fallback)
	{
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(true|false)",
			RegexOptions.IgnoreCase);
		if (!match.Success || !bool.TryParse(match.Groups[1].Value, out var value))
			return fallback;
		return value;
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new MissingMemberException(symbolId + " type not found: " + fullName);
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new MissingMemberException(
			symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(
		Type type,
		Type returnType,
		Type[] parameters,
		string name,
		string symbolId,
		Func<MethodInfo, bool> predicate)
	{
		var method = AccessTools.Method(type, name, parameters);
		if (method == null || method.ReturnType != returnType || (predicate != null && !predicate(method)))
		{
			throw new MissingMethodException(symbolId + " method not found: " + type.FullName + "." + name);
		}
		return method;
	}
}
