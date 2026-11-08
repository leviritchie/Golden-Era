using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Dungeon faction-skill battle slice (Captives era; file name kept for config/plugin
/// compatibility). Draconic Dominion's flee-recruit redirect and Diplomacy pricing were removed
/// 2026-10-12: the escape click is now owned only by <see cref="Homm3DungeonCaptivesRuntime"/>.
/// This hook keeps the Imperial Menagerie / Terror Mandate morale adjustment at BattleLogic.Init
/// (prefix applies, finalizer restores) and the TransferHero -> Data.Hero index it needs, and
/// exposes the faction-skill rank / subskill / unit-config helpers shared with Captives.
/// </summary>
internal static class Homm3DungeonDraconicDominionHook
{
	private const string DungeonFactionSkillSid = "skill_faction_homm3_dungeon";
	private const string ImperialMenagerieSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_3";
	private const string TerrorMandateSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_4";

	private static bool _registered;
	private static ManualLogSource _log;
	private static Type _configRootType;
	private static MemberInfo _battleLogicHeroDataMember;
	private static object _unitLogicConfigTable;
	private static int _loggedMoraleApplications;
	private static int _loggedMoraleDiagnostics;
	private static int _loggedMoraleSideDiagnostics;
	private static int _loggedResolveSkips;
	private static readonly Dictionary<string, Hero> TransferHeroDataHeroesBySid = new(StringComparer.Ordinal);

	private sealed class BattleTransferHeroMoraleState
	{
		internal readonly List<HeroStatMoraleSnapshot> Snapshots = new();
	}

	private sealed class HeroStatMoraleSnapshot
	{
		internal HeroStat Stat;
		internal int OriginalMorale;
	}

	private readonly struct MoraleAdjustment
	{
		internal MoraleAdjustment(int imperialMenagerieBonus, int terrorMandatePenalty)
		{
			ImperialMenagerieBonus = imperialMenagerieBonus;
			TerrorMandatePenalty = terrorMandatePenalty;
		}

		internal int ImperialMenagerieBonus { get; }
		internal int TerrorMandatePenalty { get; }
		internal int Delta => ImperialMenagerieBonus - TerrorMandatePenalty;
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Dungeon Captives morale registration.");

		_log = log;
		var hexAssembly = typeof(Hero).Assembly;
		_battleLogicHeroDataMember = ResolveRequiredExactMember(
			typeof(LogicHero),
			typeof(Hero),
			GameSymbols.DraconicDominion.BattleLogicHeroDataHeroMembers,
			"homm3.dungeon.draconicDominion.battleLogicHero.dataHero");
		var battleLogicType = ResolveRequiredTypeByHint(
			hexAssembly,
			GameSymbols.DraconicDominion.BattleLogicTypeHints,
			GameSymbols.DraconicDominion.BattleLogicTypeId);
		var transferBattleType = ResolveRequiredTypeByName(
			hexAssembly,
			GameSymbols.DraconicDominion.TransferBattleTypeName,
			GameSymbols.DraconicDominion.TransferBattleTypeId);
		var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
			battleLogicType,
			typeof(void),
			new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
			"Init",
			GameSymbols.DraconicDominion.BattleLogicInit.Id,
			m => !m.IsStatic);
		var transferHeroBuilderMethods = ResolveRequiredTransferHeroDataHeroBuilderMethods();

		PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInitMorale));
		PatchFinalizer(harmony, battleLogicInitMethod, nameof(FinalizerBattleLogicInitMorale));
		foreach (var transferHeroBuilderMethod in transferHeroBuilderMethods)
			PatchPostfix(harmony, transferHeroBuilderMethod, nameof(PostfixTransferHeroFromDataHero));

		_registered = true;
		_log?.LogInfo(
			"HoMM3 Dungeon Captives morale: registered Imperial Menagerie / Terror Mandate on "
			+ FormatMethod(battleLogicInitMethod)
			+ ", battle-logic-hero-data="
			+ _battleLogicHeroDataMember.Name
			+ ", transfer-hero-builders="
			+ transferHeroBuilderMethods.Count
			+ ". Draconic Dominion flee recruitment removed; the escape click belongs to Homm3DungeonCaptivesRuntime.");
	}

	private static void PostfixTransferHeroFromDataHero(LogicHero __0, TransferHero __result)
	{
		// Index Configs.Hero from battle LogicHero only. Never patch the StoryHub.Logic.Hero
		// overload (becd): GameMember.TypesEquivalent matches by short name "Hero", and an
		// IL2CPP Harmony postfix on that overload stack-overflows portrait clicks.
		IndexTransferHeroDataHero(ResolveDataHero(__0), __result);
	}
	private static void PrefixBattleLogicInitMorale(object __1, ref BattleTransferHeroMoraleState __state)
	{
		__state = null;
		try
		{
			__state = ApplyBattleLogicInitMorale(__1);
		}
		catch (Exception ex)
		{
			LogResolveSkip("battle logic init morale adjustment failed: " + ex.Message);
		}
	}

	private static Exception FinalizerBattleLogicInitMorale(Exception __exception, BattleTransferHeroMoraleState __state)
	{
		RestoreBattleLogicInitMorale(__state);
		return __exception;
	}

	private static BattleTransferHeroMoraleState ApplyBattleLogicInitMorale(object transferBattle)
	{
		if (transferBattle == null)
			return null;

		var sidesValue = ReadMember(transferBattle, GameSymbols.DraconicDominion.TransferBattleSidesMembers);
		var transferSides = EnumerateObjects(sidesValue).Where(side => side != null).ToList();
		if (transferSides.Count == 0)
			return null;

		var state = new BattleTransferHeroMoraleState();
		foreach (var transferSide in transferSides)
		{
			var adjustment = ResolveTransferBattleMoraleAdjustment(transferSide, transferSides);
			LogMoraleSideDiagnostic(transferSide, transferSides, adjustment);
			if (adjustment.Delta == 0)
			{
				LogMoraleDiagnosticIfRelevant(transferSide, transferSides, adjustment);
				continue;
			}

			var changed = 0;
			foreach (var heroStat in ResolveTransferSideHeroStats(transferSide))
			{
				if (heroStat == null)
					continue;
				RecordHeroStatMoraleSnapshot(state, heroStat);
				heroStat.moral += adjustment.Delta;
				changed++;
			}

			if (changed == 0)
			{
				LogMoraleDiagnosticIfRelevant(transferSide, transferSides, adjustment);
				continue;
			}

			if (_loggedMoraleApplications++ < 12)
			{
				_log?.LogInfo(
					"HoMM3 Dungeon Captives morale: applied "
					+ FormatSigned(adjustment.Delta)
					+ " transfer-battle hero Morale before battle init (Imperial Menagerie +"
					+ adjustment.ImperialMenagerieBonus
					+ ", Terror Mandate -"
					+ adjustment.TerrorMandatePenalty
					+ ", heroStats="
					+ changed
					+ ").");
			}
		}

		return state.Snapshots.Count == 0 ? null : state;
	}

	private static void RestoreBattleLogicInitMorale(BattleTransferHeroMoraleState state)
	{
		if (state == null)
			return;
		foreach (var snapshot in state.Snapshots)
		{
			if (snapshot?.Stat == null)
				continue;
			snapshot.Stat.moral = snapshot.OriginalMorale;
		}
	}

	private static void RecordHeroStatMoraleSnapshot(BattleTransferHeroMoraleState state, HeroStat heroStat)
	{
		if (state == null || heroStat == null)
			return;
		if (state.Snapshots.Any(snapshot => ReferenceEquals(snapshot.Stat, heroStat)))
			return;
		state.Snapshots.Add(new HeroStatMoraleSnapshot
		{
			Stat = heroStat,
			OriginalMorale = heroStat.moral
		});
	}

	private static MoraleAdjustment ResolveTransferBattleMoraleAdjustment(object transferSide, IReadOnlyList<object> allTransferSides)
	{
		var imperialBonus = ResolveTransferSideMixedFactionMoraleMagnitude(transferSide, ImperialMenagerieSubSkillSid);
		var terrorPenalty = ResolveTerrorMandateMoralePenalty(transferSide, allTransferSides);
		return new MoraleAdjustment(imperialBonus, terrorPenalty);
	}

	private static IEnumerable<HeroStat> ResolveTransferSideHeroStats(object transferSide)
	{
		var seen = new HashSet<HeroStat>();
		var transferHero = ResolveTransferHero(transferSide);
		if (transferHero == null)
			yield break;
		if (transferHero.heroStat != null && seen.Add(transferHero.heroStat))
			yield return transferHero.heroStat;
		if (transferHero.heroStatUnclamped != null && seen.Add(transferHero.heroStatUnclamped))
			yield return transferHero.heroStatUnclamped;
	}

	private static int ResolveTransferSideMixedFactionMoraleMagnitude(object transferSide, string subSkillSid)
	{
		var dataHero = ResolveTransferSideDataHero(transferSide);
		if (dataHero == null || !HasHeroSubSkill(dataHero, subSkillSid))
			return 0;

		var distinctFactions = CountDistinctTransferSideFactions(transferSide);
		return distinctFactions > 1 ? distinctFactions - 1 : 0;
	}

	private static int ResolveTerrorMandateMoralePenalty(object ownTransferSide, IReadOnlyList<object> allTransferSides)
	{
		var penalty = 0;
		foreach (var enemyTransferSide in ResolveEnemyTransferSides(ownTransferSide, allTransferSides))
			penalty += ResolveTransferSideMixedFactionMoraleMagnitude(enemyTransferSide, TerrorMandateSubSkillSid);
		return penalty;
	}

	private static IEnumerable<object> ResolveEnemyTransferSides(object ownTransferSide, IReadOnlyList<object> allTransferSides)
	{
		foreach (var candidate in allTransferSides ?? Array.Empty<object>())
		{
			if (candidate == null || ReferenceEquals(candidate, ownTransferSide))
				continue;
			yield return candidate;
		}
	}

	private static int CountDistinctTransferSideFactions(object transferSide)
	{
		var factions = new HashSet<string>(StringComparer.Ordinal);
		foreach (var transferUnit in ResolveTransferSideUnits(transferSide))
		{
			var faction = ResolveTransferUnitFaction(transferUnit);
			if (!string.IsNullOrWhiteSpace(faction))
				factions.Add(faction);
		}
		return factions.Count;
	}

	private static void LogMoraleDiagnosticIfRelevant(object transferSide, IReadOnlyList<object> allTransferSides, MoraleAdjustment adjustment)
	{
		var ownHasImperial = TransferSideHeroHasSubSkill(transferSide, ImperialMenagerieSubSkillSid);
		var enemyHasTerror = ResolveEnemyTransferSides(transferSide, allTransferSides).Any(side => TransferSideHeroHasSubSkill(side, TerrorMandateSubSkillSid));
		if (!ownHasImperial && !enemyHasTerror)
			return;
		if (_loggedMoraleDiagnostics++ >= 8)
			return;

		_log?.LogInfo(
			"HoMM3 Dungeon Captives morale diagnostic: transfer-battle init found relevant subskill but no applied delta; ownFactions="
			+ CountDistinctTransferSideFactions(transferSide)
			+ ", enemyFactions="
			+ string.Join(",", ResolveEnemyTransferSides(transferSide, allTransferSides).Select(side => CountDistinctTransferSideFactions(side).ToString()))
			+ ", imperial=+"
			+ adjustment.ImperialMenagerieBonus
			+ ", terror=-"
			+ adjustment.TerrorMandatePenalty
			+ ".");
	}

	private static void LogMoraleSideDiagnostic(object transferSide, IReadOnlyList<object> allTransferSides, MoraleAdjustment adjustment)
	{
		if (_loggedMoraleSideDiagnostics++ >= 12)
			return;

		var dataHero = ResolveTransferSideDataHero(transferSide);
		var heroStats = ResolveTransferSideHeroStats(transferSide).ToList();
		var ownFactions = DescribeTransferSideFactions(transferSide);
		var enemyFactions = string.Join("/", ResolveEnemyTransferSides(transferSide, allTransferSides).Select(DescribeTransferSideFactions));
		var heroStatMorale = string.Join(",", heroStats.Select(stat => stat?.moral.ToString() ?? "?"));
		var heroSid = NormalizeSid(TryReadString(dataHero, GameSymbols.DraconicDominion.DataHeroSidMembers)) ?? "?";
		var transferHeroSid = NormalizeSid(ResolveTransferHero(transferSide)?.configId) ?? "?";
		var skills = dataHero == null ? "none" : DescribeHeroSkills(dataHero);

		_log?.LogInfo(
			"HoMM3 Dungeon Captives morale side diagnostic: hero="
			+ heroSid
			+ " transferHero="
			+ transferHeroSid
			+ " skills="
			+ skills
			+ " ownFactions="
			+ ownFactions
			+ " enemyFactions="
			+ (string.IsNullOrWhiteSpace(enemyFactions) ? "none" : enemyFactions)
			+ " imperial=+"
			+ adjustment.ImperialMenagerieBonus
			+ " terror=-"
			+ adjustment.TerrorMandatePenalty
			+ " delta="
			+ FormatSigned(adjustment.Delta)
			+ " heroStats="
			+ heroStats.Count
			+ " morale="
			+ (string.IsNullOrWhiteSpace(heroStatMorale) ? "none" : heroStatMorale)
			+ ".");
	}

	private static string DescribeHeroSkills(Hero dataHero)
	{
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		var parts = new List<string>();
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var skillSid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers)) ?? "?";
			var level = ReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers);
			var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
			var subSkillSids = EnumerateObjects(subSkills)
				.Select(subSkill => NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers)) ?? "?")
				.Take(6)
				.ToList();
			parts.Add(skillSid + ":" + level + "[" + (subSkillSids.Count == 0 ? "-" : string.Join("|", subSkillSids)) + "]");
			if (parts.Count >= 10)
				break;
		}
		return parts.Count == 0 ? "none" : string.Join(";", parts);
	}

	private static string DescribeTransferSideFactions(object transferSide)
	{
		var factions = new HashSet<string>(StringComparer.Ordinal);
		foreach (var transferUnit in ResolveTransferSideUnits(transferSide))
		{
			var faction = ResolveTransferUnitFaction(transferUnit);
			if (!string.IsNullOrWhiteSpace(faction))
				factions.Add(faction);
		}
		return factions.Count == 0 ? "none" : string.Join(",", factions.OrderBy(value => value, StringComparer.Ordinal));
	}

	private static bool TransferSideHeroHasSubSkill(object transferSide, string subSkillSid)
	{
		var dataHero = ResolveTransferSideDataHero(transferSide);
		return dataHero != null && HasHeroSubSkill(dataHero, subSkillSid);
	}

	private static TransferSide ResolveTransferSide(object transferSide)
	{
		return transferSide as TransferSide;
	}

	private static TransferHero ResolveTransferHero(object transferSide)
	{
		return ResolveTransferSide(transferSide)?.hero;
	}

	private static Hero ResolveTransferSideDataHero(object transferSide)
	{
		var transferHero = ResolveTransferHero(transferSide);
		if (transferHero == null)
			return null;
		var sid = NormalizeSid(transferHero.configId);
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		lock (TransferHeroDataHeroesBySid)
		{
			return TransferHeroDataHeroesBySid.TryGetValue(sid, out var hero) ? hero : null;
		}
	}

	private static IEnumerable<TransferUnit> ResolveTransferSideUnits(object transferSide)
	{
		var units = ResolveTransferSide(transferSide)?.units;
		if (units == null)
			yield break;
		foreach (var unit in units)
		{
			if (unit != null)
				yield return unit;
		}
	}

	private static string ResolveTransferUnitFaction(TransferUnit transferUnit)
	{
		if (transferUnit == null)
			return null;
		var logicConfig = ResolveUnitLogicConfigBySid(transferUnit.configSid);
		return NormalizeSid(logicConfig?.fraction);
	}

	internal static UnitLogicConfig ResolveUnitLogicConfigBySid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var table = ResolveUnitLogicConfigTable();
		if (table == null)
			return null;
		return TryLookupConfigBySid(table, sid.Trim(), out UnitLogicConfig logicConfig) ? logicConfig : null;
	}

	private static object ResolveUnitLogicConfigTable()
	{
		if (_unitLogicConfigTable != null)
			return _unitLogicConfigTable;

		var rootType = _configRootType ?? ResolveTypeByNames(typeof(TransferSide).Assembly, GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (rootType == null)
			return null;
		_configRootType = rootType;

		var root = ReadStaticMember(rootType, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return null;

		_unitLogicConfigTable = ReadMember(root, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigTables);
		return _unitLogicConfigTable;
	}

	private static bool TryLookupConfigBySid<T>(object table, string sid, out T value) where T : class
	{
		value = null;
		if (table == null || string.IsNullOrWhiteSpace(sid))
			return false;
		try
		{
			var method = FindConfigTableTryGetMethod(table.GetType(), typeof(T));
			if (method == null)
				return false;
			var args = new object[] { sid, null };
			if (!(method.Invoke(table, args) is bool found) || !found)
				return false;
			value = args[1] as T;
			return value != null;
		}
		catch
		{
			return false;
		}
	}

	private static void IndexTransferHeroDataHero(Hero dataHero, TransferHero transferHero)
	{
		if (dataHero == null || transferHero == null)
			return;
		var sid = NormalizeSid(transferHero.configId);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		lock (TransferHeroDataHeroesBySid)
		{
			TransferHeroDataHeroesBySid[sid] = dataHero;
		}
	}

	private static MethodInfo FindConfigTableTryGetMethod(Type tableType, Type valueType)
	{
		if (tableType == null || valueType == null)
			return null;
		foreach (var method in SafeGetMethods(tableType))
		{
			if (method == null || method.ReturnType != typeof(bool) || !MethodMatchesName(method, GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 2 || parameters[0].ParameterType != typeof(string))
				continue;
			if (!parameters[1].ParameterType.IsByRef || parameters[1].ParameterType.GetElementType() != valueType)
				continue;
			return method;
		}
		return null;
	}

	private static string FormatSigned(int value)
	{
		return value > 0 ? "+" + value : value.ToString();
	}

	private static Hero ResolveDataHero(LogicHero logicHero)
	{
		if (logicHero == null)
			return null;
		return ReadResolvedMember(logicHero, _battleLogicHeroDataMember) as Hero;
	}

	/// <summary>Faction-skill rank 1..3 of skill_faction_homm3_dungeon, 0 when absent. Shared with Captives.</summary>
	internal static int ResolveFactionSkillRank(Hero dataHero)
	{
		if (dataHero == null)
			return 0;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, DungeonFactionSkillSid, StringComparison.Ordinal))
				continue;
			var level = ReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers);
			return Math.Max(1, Math.Min(3, level));
		}
		return 0;
	}

	internal static bool HasHeroSubSkill(Hero dataHero, string subSkillSid)
	{
		if (dataHero == null || string.IsNullOrWhiteSpace(subSkillSid))
			return false;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
			foreach (var subSkill in EnumerateObjects(subSkills))
			{
				var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers));
				if (string.Equals(sid, subSkillSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new TypeLoadException("Missing " + symbolId + " type " + fullName + ".");
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			foreach (var type in SafeGetTypes(assembly))
			{
				if (type == null)
					continue;
				if (string.Equals(type.FullName, hint, StringComparison.Ordinal)
				    || string.Equals(type.Name, hint, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(type), hint, StringComparison.Ordinal))
					return type;
			}
		}
		throw new TypeLoadException("Missing " + symbolId + " type with configured hints.");
	}

	private static List<MethodInfo> ResolveRequiredTransferHeroDataHeroBuilderMethods()
	{
		var matches = new List<MethodInfo>();
		foreach (var method in SafeGetMethods(typeof(TransferHero)))
		{
			if (method == null || method.IsSpecialName)
				continue;
			if (!MethodMatchesName(method, GameSymbols.DraconicDominion.TransferHeroFromDataHero.NameHints))
				continue;
			if (!method.IsStatic)
				continue;
			if (!TypesEquivalentByFullName(typeof(TransferHero), method.ReturnType))
				continue;
			// Exact FullName only: Session.Logic.Hero (becc). Name-equivalent matching would
			// also bind StoryHub.Logic.Hero (becd) and crash StoryHub portrait UI.
			if (!ParametersMatchExactFullName(method, new[] { typeof(LogicHero) }))
				continue;
			if (!matches.Contains(method))
				matches.Add(method);
		}
		if (matches.Count == 0)
			throw new MissingMethodException(typeof(TransferHero).FullName, GameSymbols.DraconicDominion.TransferHeroFromDataHero.Id);
		if (matches.Count != 1)
			throw new AmbiguousMatchException(
				GameSymbols.DraconicDominion.TransferHeroFromDataHero.Id
				+ " expected exactly one Session.Logic.Hero TransferHero builder, found "
				+ matches.Count);
		return matches;
	}

	private static bool ParametersMatchExactFullName(MethodInfo method, Type[] parameterTypes)
	{
		var parameters = method.GetParameters();
		if (parameters.Length != parameterTypes.Length)
			return false;
		for (var i = 0; i < parameterTypes.Length; i++)
		{
			var expected = parameterTypes[i];
			if (expected != null && !TypesEquivalentByFullName(expected, parameters[i].ParameterType))
				return false;
		}
		return true;
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(
		Type type,
		Type returnType,
		Type[] parameterTypes,
		string methodName,
		string symbolId,
		Predicate<MethodInfo> extraPredicate)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			throw new MissingMethodException(type?.FullName ?? "?", symbolId);

		var matches = new List<MethodInfo>();
		foreach (var method in SafeGetMethods(type))
		{
			if (method == null || method.IsSpecialName)
				continue;
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (returnType != null && !GameMember.TypesEquivalent(returnType, method.ReturnType))
				continue;
			if (parameterTypes != null && !ParametersMatch(method, parameterTypes))
				continue;
			if (extraPredicate != null && !extraPredicate(method))
				continue;
			matches.Add(method);
		}

		if (matches.Count == 1)
			return matches[0];
		if (matches.Count > 1)
			throw new AmbiguousMatchException(symbolId + " matched " + matches.Count + " exact-named methods on " + type.FullName + ".");
		throw new MissingMethodException(type.FullName, symbolId);
	}

	private static MemberInfo ResolveRequiredExactMember(Type type, Type valueType, string[] names, string symbolId)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			var member = TryResolveExactMemberByName(type, valueType, name);
			if (member != null)
				return member;
		}
		throw new MissingMemberException(type?.FullName ?? "?", symbolId);
	}

	private static MemberInfo TryResolveExactMemberByName(Type type, Type valueType, string name)
	{
		if (type == null || valueType == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

		var field = type.GetField(name, flags);
		if (field != null && GameMember.TypesEquivalent(valueType, field.FieldType))
			return field;

		var property = type.GetProperty(name, flags);
		if (property?.GetMethod != null
		    && property.GetIndexParameters().Length == 0
		    && GameMember.TypesEquivalent(valueType, property.PropertyType))
			return property;

		var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
		if (method != null
		    && !method.IsStatic
		    && GameMember.TypesEquivalent(valueType, method.ReturnType))
			return method;

		return null;
	}

	private static bool TypesEquivalentByFullName(Type expected, Type actual)
	{
		if (expected == null || actual == null)
			return expected == actual;
		if (expected == actual)
			return true;
		try
		{
			if (expected.IsAssignableFrom(actual) || actual.IsAssignableFrom(expected))
				return true;
		}
		catch { }
		return string.Equals(expected.FullName, actual.FullName, StringComparison.Ordinal);
	}

	private static bool ParametersMatch(MethodInfo method, Type[] parameterTypes)
	{
		return ParametersMatch(method.GetParameters(), parameterTypes);
	}

	private static bool ParametersMatch(ParameterInfo[] parameters, Type[] parameterTypes)
	{
		if (parameters.Length != parameterTypes.Length)
			return false;
		for (var i = 0; i < parameterTypes.Length; i++)
		{
			var expected = parameterTypes[i];
			if (expected != null && !GameMember.TypesEquivalent(expected, parameters[i].ParameterType))
				return false;
		}
		return true;
	}

	private static object ReadResolvedMember(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return null;
		if (member is FieldInfo field)
			return field.GetValue(instance);
		if (member is PropertyInfo property)
			return property.GetValue(instance, null);
		if (member is MethodInfo method)
			return method.Invoke(instance, Array.Empty<object>());
		return null;
	}

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible postfix: " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible prefix: " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static void PatchFinalizer(Harmony harmony, MethodInfo target, string finalizerName)
	{
		var finalizer = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), finalizerName);
		if (!GameMember.IsHarmonyPatchCompatible(target, finalizer, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible finalizer: " + reason);
		harmony.Patch(target, finalizer: new HarmonyMethod(finalizer));
	}

	private static bool MethodMatchesName(MethodInfo method, string[] names)
	{
		if (method == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (string.Equals(method.Name, name, StringComparison.Ordinal))
				return true;
			if (string.Equals(GameMember.ReadObfuscatedName(method), name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static Type ResolveTypeByNames(Assembly assembly, string[] names)
	{
		if (assembly == null || names == null)
			return null;
		foreach (var type in SafeGetTypes(assembly))
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				if (string.Equals(type.FullName, name, StringComparison.Ordinal)
				    || string.Equals(type.Name, name, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(type), name, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static object ReadStaticMember(Type type, params string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(null, null);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(null, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static IEnumerable<Type> SafeGetTypes(Assembly assembly)
	{
		if (assembly == null)
			yield break;
		Type[] types;
		try { types = assembly.GetTypes(); }
		catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
		catch { yield break; }
		foreach (var type in types)
			if (type != null)
				yield return type;
	}

	private static IEnumerable<MethodInfo> SafeGetMethods(Type type)
	{
		if (type == null)
			return Array.Empty<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		try { return type.GetMethods(flags); }
		catch { return Array.Empty<MethodInfo>(); }
	}

	private static IEnumerable<FieldInfo> SafeGetFields(Type type)
	{
		if (type == null)
			return Array.Empty<FieldInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		try { return type.GetFields(flags); }
		catch { return Array.Empty<FieldInfo>(); }
	}

	private static IEnumerable<PropertyInfo> SafeGetProperties(Type type)
	{
		if (type == null)
			return Array.Empty<PropertyInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		try { return type.GetProperties(flags); }
		catch { return Array.Empty<PropertyInfo>(); }
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;

		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		var type = value.GetType();
		var count = TryReadCount(value, type);
		var indexer = ResolveIntIndexer(type);
		if (count == null || count.Value <= 0 || indexer == null)
			yield break;

		for (var i = 0; i < count.Value; i++)
		{
			object item = null;
			try { item = indexer.Invoke(value, new object[] { i }); }
			catch { }
			if (item != null)
				yield return item;
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
		catch { }
		try
		{
			var method = type.GetMethod("get_Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method != null && method.GetParameters().Length == 0 && method.Invoke(value, Array.Empty<object>()) is int methodCount)
				return methodCount;
		}
		catch { }
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

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj, null);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static string TryReadString(object obj, params string[] names)
	{
		return ReadMember(obj, names) as string;
	}

	private static int ReadInt(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		if (value is int direct)
			return direct;
		try { return Convert.ToInt32(value); }
		catch { return 0; }
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "null";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static void LogResolveSkip(string message)
	{
		if (_loggedResolveSkips++ < 8)
			_log?.LogWarning("HoMM3 Dungeon Captives morale: " + message);
	}
}
