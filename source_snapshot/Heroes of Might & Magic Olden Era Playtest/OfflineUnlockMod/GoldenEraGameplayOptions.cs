using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Player-facing gameplay options (WoG-style toggles) chosen from the main-menu Gameplay Options window
/// (<see cref="GoldenEraGameplayOptionsMenu"/>) and saved in BepInEx/config/GoldenEraGameplayOptions.json.
///
/// Data options edit the loaded native configs in memory, never Core.zip. Each edit is recomputed from the
/// value first seen on that native config object, so applying again (or turning an option off) is exact:
/// - Hero movement: HeroConfig.stats.movementPerBonus += multiplier - 1 (the stat Logistics raises).
///   Read when a hero is created, so it affects heroes in new games.
/// - Experience: every hero ExpConfig level threshold (the table holding exp_standard_campaign) is divided
///   by the multiplier. Read live, so it also affects loaded games.
/// - Neutral strength: DifficultiesLobby squad/guard power multiplied. Read at map generation (new games).
/// Runtime options:
/// - Single-visit sites reset: event banks whose config says visitorsResetType None (campaign rows excluded)
///   are switched to OnStartWeek the first time a hero interacts with one; the native OnStartWeek then
///   clears their visitors. Monthly keeps the native reset on every fourth week turn only.
///   The week-turn count is in memory, so after a reload the first monthly reset can come up to 3 weeks late.
/// - Monster gold: after a won battle against a neutral map stack, the winner gets a share of the defeated
///   stacks' gold recruit cost, granted through the Plunder resource path.
///
/// Applies to every side including AI, like WoG. Not synchronized for multiplayer.
/// </summary>
internal static class GoldenEraGameplayOptions
{
	internal const string FileName = "GoldenEraGameplayOptions.json";
	private const string LogPrefix = "GameplayOptions: ";
	private const string NoResetType = "None";
	private const string WeeklyResetType = "OnStartWeek";
	private const string HeroExpTableMarkerId = "exp_standard_campaign";

	internal static readonly float[] MovementChoices = { 1f, 1.5f, 2f, 3f };
	internal static readonly float[] ExperienceChoices = { 1f, 1.5f, 2f, 3f };
	internal static readonly float[] NeutralStrengthChoices = { 0.5f, 0.75f, 1f, 1.5f, 2f };
	internal static readonly int[] MonsterGoldChoices = { 0, 10, 25 };

	internal enum SiteResetMode
	{
		Off,
		Monthly,
		Weekly,
	}

	internal sealed class Settings
	{
		public float MovementMultiplier = 1f;
		public float ExperienceMultiplier = 1f;
		public float NeutralStrength = 1f;
		public SiteResetMode SiteReset = SiteResetMode.Off;
		public int MonsterGoldPercent;

		internal Settings Clone() => (Settings)MemberwiseClone();

		internal bool IsDefault =>
			MovementMultiplier == 1f && ExperienceMultiplier == 1f && NeutralStrength == 1f
			&& SiteReset == SiteResetMode.Off && MonsterGoldPercent == 0;
	}

	private static Settings _current;
	private static ManualLogSource _log;

	// Original native values, keyed by native object pointer (a config reload makes new objects).
	private static readonly Dictionary<IntPtr, float> _originalMovement = new();
	private static readonly Dictionary<IntPtr, int[]> _originalExp = new();
	private static readonly Dictionary<IntPtr, float> _originalSquadPower = new();
	private static readonly Dictionary<IntPtr, ObjEventBankConfig> _convertedBanks = new();
	private static IntPtr _appliedRoot;
	private static bool _dirty = true;
	private static bool _loggedRootMissing;

	private static bool _hooksRegistered;
	private static IntPtr _eventBankClass;
	private static int _weekTurnFrame = -1;
	private static int _weekTurns;
	private static readonly HashSet<int> _paidBattles = new();
	private const string GoldResourceName = "gold";
	private static Dictionary<string, int> _unitGoldCosts;
	private static IntPtr _unitGoldCostsRoot;

	internal static Settings Current => _current ??= Load();

	internal static string SettingsPath => Path.Combine(Paths.ConfigPath, FileName);

	// ---------------------------------------------------------------- settings file

	private static Settings Load()
	{
		var settings = new Settings();
		try
		{
			if (!File.Exists(SettingsPath))
				return settings;
			var json = JObject.Parse(File.ReadAllText(SettingsPath));
			settings.MovementMultiplier = Pick(json.Value<float?>("heroMovementMultiplier"), MovementChoices, 1f);
			settings.ExperienceMultiplier = Pick(json.Value<float?>("experienceMultiplier"), ExperienceChoices, 1f);
			settings.NeutralStrength = Pick(json.Value<float?>("neutralStrength"), NeutralStrengthChoices, 1f);
			settings.MonsterGoldPercent = Pick(json.Value<int?>("monsterGoldPercent"), MonsterGoldChoices, 0);
			if (Enum.TryParse(json.Value<string>("siteReset"), true, out SiteResetMode reset))
				settings.SiteReset = reset;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "could not read " + SettingsPath + " (" + ex.Message + "); using defaults.");
		}
		return settings;
	}

	internal static void Save(Settings settings)
	{
		_current = settings.Clone();
		_dirty = true;
		try
		{
			var json = new JObject
			{
				["heroMovementMultiplier"] = settings.MovementMultiplier,
				["experienceMultiplier"] = settings.ExperienceMultiplier,
				["neutralStrength"] = settings.NeutralStrength,
				["siteReset"] = settings.SiteReset.ToString(),
				["monsterGoldPercent"] = settings.MonsterGoldPercent,
			};
			Directory.CreateDirectory(Paths.ConfigPath);
			var temp = SettingsPath + ".tmp";
			File.WriteAllText(temp, json.ToString());
			if (File.Exists(SettingsPath))
				File.Replace(temp, SettingsPath, null);
			else
				File.Move(temp, SettingsPath);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "could not save " + SettingsPath + ": " + ex.Message);
		}
		if (settings.SiteReset == SiteResetMode.Off)
			RestoreConvertedBanks();
	}

	private static float Pick(float? value, float[] choices, float fallback)
	{
		if (value is not float v)
			return fallback;
		foreach (var choice in choices)
			if (Math.Abs(choice - v) < 0.001f)
				return choice;
		return fallback;
	}

	private static int Pick(int? value, int[] choices, int fallback)
	{
		if (value is not int v)
			return fallback;
		return Array.IndexOf(choices, v) >= 0 ? v : fallback;
	}

	// ---------------------------------------------------------------- config edits

	/// <summary>Called every main-menu frame; re-applies only after a settings change or a config reload.</summary>
	internal static void ApplyIfNeeded()
	{
		try
		{
			var root = FindConfigRoot();
			if (root is not Il2CppObjectBase native || native.Pointer == IntPtr.Zero)
			{
				if (!_loggedRootMissing)
				{
					_loggedRootMissing = true;
					Plugin.LogSource?.LogWarning(LogPrefix + "config root not found (UnitPreviewAbilityIcons.ConfigRootTypeNames); data options are inactive.");
				}
				return;
			}
			if (!_dirty && native.Pointer == _appliedRoot)
				return;
			_dirty = false;
			_appliedRoot = native.Pointer;
			var settings = Current;
			var heroes = ApplyMovement(root, settings.MovementMultiplier);
			var levels = ApplyExperience(root, settings.ExperienceMultiplier);
			var squads = ApplyNeutralStrength(root, settings.NeutralStrength);
			Plugin.LogSource?.LogInfo(LogPrefix + "applied movement x" + settings.MovementMultiplier + " to " + heroes
				+ " hero config(s), experience x" + settings.ExperienceMultiplier + " to " + levels
				+ " exp table(s), neutral strength x" + settings.NeutralStrength + " to " + squads
				+ " difficulty row(s); site reset " + settings.SiteReset + ", monster gold " + settings.MonsterGoldPercent + "%.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "apply failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static int ApplyMovement(object root, float multiplier)
	{
		var count = 0;
		foreach (var hero in TableItems<HeroConfig>(root))
		{
			var stats = hero?.stats;
			if (stats == null)
				continue;
			if (!_originalMovement.TryGetValue(stats.Pointer, out var original))
				_originalMovement[stats.Pointer] = original = stats.movementPerBonus;
			stats.movementPerBonus = original + (multiplier - 1f);
			count++;
		}
		return count;
	}

	private static int ApplyExperience(object root, float multiplier)
	{
		var tables = 0;
		foreach (var table in Tables<ExpConfig>(root))
		{
			var rows = TableList<ExpConfig>(table);
			if (!ContainsId(rows, HeroExpTableMarkerId))
				continue;
			tables++;
			foreach (var row in rows)
			{
				var values = row?.values;
				if (values == null)
					continue;
				if (!_originalExp.TryGetValue(row.Pointer, out var original))
				{
					original = new int[values.Length];
					for (var i = 0; i < original.Length; i++)
						original[i] = values[i];
					_originalExp[row.Pointer] = original;
				}
				for (var i = 0; i < original.Length && i < values.Length; i++)
					values[i] = (int)Math.Round(original[i] / multiplier);
			}
		}
		return tables;
	}

	private static int ApplyNeutralStrength(object root, float multiplier)
	{
		var count = 0;
		foreach (var property in root.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.PropertyType != typeof(DifficultiesLobby) || property.GetIndexParameters().Length != 0)
				continue;
			if (property.GetValue(root) is not DifficultiesLobby lobby)
				continue;
			count += ScaleSquads(lobby.squad, multiplier) + ScaleSquads(lobby.guard, multiplier);
		}
		return count;
	}

	private static int ScaleSquads(Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppReferenceArray<DifficultySquad> squads, float multiplier)
	{
		if (squads == null)
			return 0;
		var count = 0;
		for (var i = 0; i < squads.Length; i++)
		{
			var squad = squads[i];
			if (squad == null)
				continue;
			if (!_originalSquadPower.TryGetValue(squad.Pointer, out var original))
				_originalSquadPower[squad.Pointer] = original = squad.power;
			squad.power = original * multiplier;
			count++;
		}
		return count;
	}

	private static object FindConfigRoot()
	{
		var type = GameMember.FindTypeFromHints("goldenEra.gameplayOptions.configRoot", GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (type == null)
			return null;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var member in GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers)
		{
			if (string.IsNullOrEmpty(member))
				continue;
			try
			{
				var value = type.GetProperty(member, flags)?.GetValue(null) ?? type.GetField(member, flags)?.GetValue(null);
				if (value != null)
					return value;
			}
			catch
			{
			}
		}
		return null;
	}

	/// <summary>Config tables on the root whose first generic argument is <typeparamref name="T"/> (cmm&lt;T, string&gt;).</summary>
	private static IEnumerable<object> Tables<T>(object root)
	{
		foreach (var property in root.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			var type = property.PropertyType;
			if (!type.IsGenericType || property.GetIndexParameters().Length != 0)
				continue;
			var args = type.GetGenericArguments();
			if (args.Length != 2 || args[0] != typeof(T) || args[1] != typeof(string))
				continue;
			object table;
			try { table = property.GetValue(root); }
			catch { continue; }
			if (table != null)
				yield return table;
		}
	}

	private static IEnumerable<T> TableItems<T>(object root) where T : Il2CppObjectBase
	{
		foreach (var table in Tables<T>(root))
			foreach (var item in TableList<T>(table))
				yield return item;
	}

	private static List<T> TableList<T>(object table) where T : Il2CppObjectBase
	{
		var result = new List<T>();
		foreach (var property in table.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.PropertyType != typeof(Il2CppSystem.Collections.Generic.List<T>) || property.GetIndexParameters().Length != 0)
				continue;
			if (property.GetValue(table) is not Il2CppSystem.Collections.Generic.List<T> list)
				continue;
			for (var i = 0; i < list.Count; i++)
				if (list[i] != null)
					result.Add(list[i]);
			return result;
		}
		return result;
	}

	private static bool ContainsId<T>(List<T> rows, string id) where T : Il2CppObjectBase
	{
		foreach (var row in rows)
			if (string.Equals(DeobfInteropCompat.GetConfigElementId(row), id, StringComparison.Ordinal))
				return true;
		return false;
	}

	// ---------------------------------------------------------------- runtime hooks

	/// <summary>Event-bank interact/week-turn hooks. Same native surfaces as Hunting Grounds; fails closed.</summary>
	internal static void TryRegisterRuntimeHooks(Harmony harmony, ManualLogSource log)
	{
		if (_hooksRegistered)
			return;
		_hooksRegistered = true;
		_log = log;
		try
		{
			var bankType = GameMember.FindType(GameSymbols.FortressHuntingGrounds.EventBankLogicTypeId, GameSymbols.FortressHuntingGrounds.EventBankLogicTypeHint);
			if (bankType == null)
				throw new TypeLoadException("event-bank logic type " + GameSymbols.FortressHuntingGrounds.EventBankLogicTypeHint);
			var interact = GameMember.FindMethodsByNames(bankType, 1, GameSymbols.FortressHuntingGrounds.EventBankHeroInteract.Id, GameSymbols.FortressHuntingGrounds.EventBankHeroInteract.NameHints);
			var weekly = GameMember.FindMethodsByNames(bankType, 0, GameSymbols.FortressHuntingGrounds.EventBankOnStartWeek.Id, GameSymbols.FortressHuntingGrounds.EventBankOnStartWeek.NameHints);
			if (interact.Length != 1 || weekly.Length != 1)
				throw new MissingMethodException(bankType.FullName, "interact " + interact.Length + "/1, OnStartWeek " + weekly.Length + "/1");
			_eventBankClass = NativeClassOf(bankType);
			harmony.Patch(interact[0], prefix: new HarmonyMethod(typeof(GoldenEraGameplayOptions), nameof(PrefixBankInteract)));
			harmony.Patch(weekly[0],
				prefix: new HarmonyMethod(typeof(GoldenEraGameplayOptions), nameof(PrefixBankOnStartWeek)),
				postfix: new HarmonyMethod(typeof(GoldenEraGameplayOptions), nameof(PostfixBankOnStartWeek)));
			log?.LogInfo(LogPrefix + "site-reset hooks on " + bankType.Name + "." + interact[0].Name + " / " + weekly[0].Name
				+ "; monster gold via the shared battle-result prefix. Proof tier: build; runtime unproven.");
		}
		catch (Exception ex)
		{
			log?.LogWarning(LogPrefix + "site-reset hooks disabled: " + ex.Message);
		}
	}

	private static void PrefixBankInteract(object __instance)
	{
		try
		{
			if (Current.SiteReset == SiteResetMode.Off || !IsNativeInstanceOf(__instance, _eventBankClass))
				return;
			var config = ReadMember(__instance, GameSymbols.FortressHuntingGrounds.EventBankLogicConfigMembers) as ObjEventBankConfig;
			if (config == null || _convertedBanks.ContainsKey(config.Pointer))
				return;
			if (!string.Equals(config.visitorsResetType?.Trim(), NoResetType, StringComparison.Ordinal))
				return;
			var id = DeobfInteropCompat.GetConfigElementId(config) ?? "";
			if (id.StartsWith("campaign", StringComparison.OrdinalIgnoreCase))
				return;
			if (!SetResetType(config, EVisitorsResetType.OnStartWeek))
				return;
			_convertedBanks[config.Pointer] = config;
			_log?.LogInfo(LogPrefix + "site '" + id + "' now resets " + Current.SiteReset.ToString().ToLowerInvariant() + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "bank interact prefix failed: " + ex.Message);
		}
	}

	// The native week turn calls OnStartWeek for every bank in one frame. On non-reset weeks of the monthly
	// mode, converted banks see their original None for the duration of the call.
	private static void PrefixBankOnStartWeek(object __instance, out ObjEventBankConfig __state)
	{
		__state = null;
		try
		{
			if (!IsNativeInstanceOf(__instance, _eventBankClass))
				return;
			var frame = Time.frameCount;
			if (frame != _weekTurnFrame)
			{
				_weekTurnFrame = frame;
				_weekTurns++;
			}
			if (Current.SiteReset != SiteResetMode.Monthly || _weekTurns % 4 == 0)
				return;
			var config = ReadMember(__instance, GameSymbols.FortressHuntingGrounds.EventBankLogicConfigMembers) as ObjEventBankConfig;
			if (config == null || !_convertedBanks.ContainsKey(config.Pointer))
				return;
			if (SetResetType(config, EVisitorsResetType.None))
				__state = config;
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "week-turn prefix failed: " + ex.Message);
		}
	}

	private static void PostfixBankOnStartWeek(ObjEventBankConfig __state)
	{
		if (__state != null)
			SetResetType(__state, EVisitorsResetType.OnStartWeek);
	}

	private static void RestoreConvertedBanks()
	{
		foreach (var config in _convertedBanks.Values)
			SetResetType(config, EVisitorsResetType.None);
		if (_convertedBanks.Count > 0)
			_log?.LogInfo(LogPrefix + "site reset off: restored " + _convertedBanks.Count + " site config(s) to None.");
		_convertedBanks.Clear();
	}

	private static bool SetResetType(ObjEventBankConfig config, EVisitorsResetType type)
	{
		try
		{
			config.visitorsResetType = type.ToString();
			// The parsed enum lives in a compiler backing field; the native visitor reset reads that.
			foreach (var property in typeof(ObjEventBankConfig).GetProperties(BindingFlags.Instance | BindingFlags.Public))
			{
				if (property.PropertyType == typeof(EVisitorsResetType) && property.CanWrite && property.Name.Contains("BackingField"))
				{
					property.SetValue(config, type);
					return true;
				}
			}
			_log?.LogWarning(LogPrefix + "ObjEventBankConfig has no writable EVisitorsResetType backing field.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "could not set site reset type: " + ex.Message);
		}
		return false;
	}

	/// <summary>Called by Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup before the native result applies.</summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		var percent = Current.MonsterGoldPercent;
		if (percent <= 0 || battleLogic == null)
			return;
		try
		{
			var key = battleLogic is Il2CppObjectBase native ? native.Pointer.GetHashCode() : 0;
			lock (_paidBattles)
			{
				if (_paidBattles.Count > 256)
					_paidBattles.Clear();
				if (!_paidBattles.Add(key))
					return;
			}
			var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle
			              ?? ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			var sides = started?.sides;
			if (sides == null || result == null || sides.Length != 2)
				return;
			var winner = result.winnerIndex;
			if (winner < 0 || winner > 1)
				return;
			var loser = sides[1 - winner];
			if (loser == null || loser.typeInWorld != TransferSide.EType.Type_Squad || sides[winner]?.hero == null)
				return;
			var unitCosts = UnitGoldCosts();
			var cost = 0L;
			var units = loser.units;
			for (var i = 0; units != null && i < units.Length; i++)
			{
				var sid = units[i]?.configSid;
				if (sid != null && unitCosts.TryGetValue(sid, out var unitCost))
					cost += (long)Math.Max(0, units[i].stacks) * unitCost;
			}
			var gold = (int)Math.Min(int.MaxValue, cost * percent / 100);
			if (gold <= 0)
				return;
			var sideId = sides[winner].sideIdInWorld;
			if (Homm3CovePlunderHook.Grant(sideId, GoldResourceName, gold, out var before, out var after, out var failReason))
				_log?.LogInfo(LogPrefix + "monster gold: side " + sideId + " +" + gold + " gold (" + percent + "% of " + cost + "), " + before + " -> " + after + ".");
			else
				_log?.LogWarning(LogPrefix + "monster gold grant failed: " + failReason);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "monster gold failed: " + ex.Message);
		}
	}

	private static Dictionary<string, int> UnitGoldCosts()
	{
		var root = FindConfigRoot();
		var rootPointer = root is Il2CppObjectBase native ? native.Pointer : IntPtr.Zero;
		if (_unitGoldCosts != null && rootPointer == _unitGoldCostsRoot)
			return _unitGoldCosts;
		var costs = new Dictionary<string, int>(StringComparer.Ordinal);
		if (root != null)
			foreach (var logic in TableItems<UnitLogicConfig>(root))
			{
				var sid = DeobfInteropCompat.GetConfigElementId(logic);
				if (!string.IsNullOrEmpty(sid))
					costs[sid] = GoldCost(logic);
			}
		_unitGoldCostsRoot = rootPointer;
		return _unitGoldCosts = costs;
	}

	private static int GoldCost(UnitLogicConfig logic)
	{
		var costs = logic?.unitCost?.costResArray;
		for (var i = 0; costs != null && i < costs.Length; i++)
			if (string.Equals(costs[i]?.name, GoldResourceName, StringComparison.Ordinal))
				return ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is int cost ? Math.Max(0, cost) : 0;
		return 0;
	}

	// ---------------------------------------------------------------- helpers

	private static object ReadMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property?.GetMethod != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj);
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch
			{
			}
		}
		return null;
	}

	private static IntPtr NativeClassOf(Type managedType)
	{
		try
		{
			var store = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(store.TypeHandle);
			return store.GetField("NativeClassPtr", BindingFlags.Public | BindingFlags.Static)?.GetValue(null) is IntPtr ptr ? ptr : IntPtr.Zero;
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static bool IsNativeInstanceOf(object value, IntPtr expectedClass)
	{
		if (expectedClass == IntPtr.Zero || value is not Il2CppObjectBase native || native.Pointer == IntPtr.Zero)
			return false;
		var actual = IL2CPP.il2cpp_object_get_class(native.Pointer);
		return actual != IntPtr.Zero && IL2CPP.il2cpp_class_is_assignable_from(expectedClass, actual);
	}
}
