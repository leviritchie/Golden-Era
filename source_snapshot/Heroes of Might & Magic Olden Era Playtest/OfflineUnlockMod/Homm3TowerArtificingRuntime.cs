using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Tower Artificing (replaces Arcane Battery once custom_factions/tower_artificing/artificing_policy.json
/// is enabled; design: docs/homm3_tower_artificing.md). Tunables and the schematic catalog are generated into
/// <see cref="Homm3TowerArtificingCatalog"/>; this runtime owns only the mechanics.
///
/// Ledger: hidden hero map buffs saved with the hero (Dungeon Captives pattern), rebuilt from the buffs on
/// every read so nothing leaks across saves:
///   essence bits   homm3_tower_artificing_essence_bit_{0..15}            Arcane Essence (0..65535)
///   schematic book homm3_tower_artificing_schematic_{i}_bit_{0..2}       lowest source tier seen (0 = unknown)
///   graft slots    homm3_tower_artificing_graft_l{line}_s{slot}_bit_{0..8} schematic index + 1 (0 = empty)
///
/// Transcribe: the hero action applies the 1-round marker buff homm3_tower_transcribe_effect to any living
/// stack. A postfix on the native unit buff add (dzv.bbgf) sees the marker and writes that unit's graftable
/// schematics (catalog) into the caster's book. Caster hero route: the caster's TransferSide.logicHero; when
/// that is unreadable, the only Artificing hero in the battle (logged as such; two Artificing heroes = refuse).
///
/// Essence: the shared battle-result prefix (Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup) awards the
/// winning Artificing hero EssencePerCreatureByTier x creatures lost by every other side (started vs after
/// TransferSide stacks, Skeletal Necromancy accounting). Deduped per battle key.
///
/// Grafts: BattleLogic.Init builds a plan per battle-local side index from the hero's graft slots (only the
/// first GraftSlotsByRank[rank] slots per line are active); the shared Unit.Init consumer adds the graft buffs
/// (homm3_tower_graft_{i}: dispellable, infinite, the passive's own data) to every unit of a grafted Tower
/// line. Purge removes them natively. perUnit schematics pick the carrier's variant buff
/// (GraftVariantBuffSid); OncePerBattleSchematics skip units initialized after the first round started.
///
/// Runtime grafts (the passives no buff row can carry; each still needs its graft buff on the carrier, so a
/// purge ends them too):
///   on hit      ObjectTookDamage dispatcher postfix: a carrier's damaging basic attack or counter (dealer tag
///               basic_attack, optional melee/shoot/range filter) on an enemy adds the catalog debuffs; Fangarm
///               then runs native MechBerserk.ApplyBerserk when its berserk debuff stuck (immunity respected).
///   vampirism   same postfix: native UnitHealer.Heal of round(damage x rate) on the carrier or its other allies.
///   first round RoundStarted dispatcher postfix, once per battle: faction-count and flyer synergies.
///
/// Ability grafts (Golem Web, Gremlin Repair): Unit.Init appends fresh copies of the source abilities to the carrier's
/// AbilitiesSet (InjectedAbilitiesBySchematic; JsonUtility configs, at most the 5 HUD skill slots).
///
/// Map grafts (out of battle; the battle graft buff is only a label):
///   hero stats  visible dispellable hero buffs with the native unit-set bonus (sight, experience, terrain, max
///               mana, spell level), held while the army has a carrier stack and no native unit of that set.
///               Reconciled on Logic.Hero.RecalculateStats (native UnitSets calls it on every army change), at day
///               start and after TryGraft. The AI gets them the same way.
///   gold        DailyGoldBySchematic per carrier creature by line, added to the side's day-start grant
///               (Homm3SwashbucklerGoldHook consumer). Not in the native income forecast.
///
/// Spend: <see cref="TryGraft"/> validates and pays; no UI calls it yet (spend UI needs an approved mockup).
///
/// Proof tier: source + build. Runtime unproven: the caster TransferSide read on the hero-ability caster, the
/// native application of statOverrides / sequenceEffect from a mid-battle buff row, essence in simulated
/// (auto-resolve) battles, the dealer tags on basic attacks, the heal/berserk statics and the first
/// RoundStarted timing, JsonUtility ability configs and the injected abilities' cast animation / HUD / charges,
/// and the RecalculateStats symbol all need a Golden Era check before policy.enabled flips.
/// </summary>
internal static class Homm3TowerArtificingRuntime
{
	private const int GraftBuffLevel = 1;
	private const int GraftBuffDuration = 99;
	private const int GraftBuffValue = 1;
	private const int MaxEssence = (1 << Homm3TowerArtificingCatalog.EssenceBits) - 1;
	private const int MaxSchematicTier = (1 << Homm3TowerArtificingCatalog.SchematicTierBits) - 1;
	private const int MaxGraftValue = (1 << Homm3TowerArtificingCatalog.GraftIndexBits) - 1;
	private const string LogPrefix = "HoMM3 Tower Artificing: ";

	private static readonly object Gate = new();
	private static readonly Dictionary<int, BattleSideInfo> SidesByIndex = new();
	/// <summary>Every unit initialized this battle while an Artificing side exists (native-pointer keys).</summary>
	private static readonly Dictionary<long, BattleUnitInfo> UnitsByKey = new();
	/// <summary>Grafted units -> schematic index -> the graft buff sid it carries (base or per-unit variant).</summary>
	private static readonly Dictionary<long, Dictionary<int, string>> CarriersByKey = new();
	private static readonly HashSet<int> AwardedBattles = new();

	private static bool _registrationAttempted;
	private static bool _ledgerRegistered;
	private static bool _battleRegistered;
	private static bool _captureRegistered;
	private static bool _damageRegistered;
	private static bool _roundRegistered;
	private static bool _firstRoundStarted;
	private static bool _observingDamage;
	private static MethodInfo _healMethod;
	private static MethodInfo _berserkMethod;
	private static bool _mapRegistered;
	private static bool _dayStartRegistered;
	[ThreadStatic] private static bool _reconcilingMap;
	/// <summary>Logic hero (native pointer) -> its active grafts, re-read on rank change, at day start and after TryGraft.</summary>
	private static readonly Dictionary<long, MapHeroGrafts> MapGraftsByHero = new();
	private static bool _abilityAccessorsResolved;
	private static string _abilityAccessorFailure;
	private static PropertyInfo _abilityDictProperty;
	private static Type _abilityType;
	private static Type _abilityArrayType;
	private static PropertyInfo _abilityCasterProperty;
	private static MethodInfo _abilityInitMethod;
	private static ManualLogSource _log;
	private static Type _logicHeroType;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _heroBuffManagerProperty;
	private static MethodInfo _heroBuffAddMethod;
	private static MethodInfo _heroBuffRemoveMethod;
	private static MethodInfo _heroBuffGetMethod;
	private static int _loggedEvents;
	private static int _loggedSkips;

	private sealed class BattleSideInfo
	{
		internal int SideIndex;
		internal object LogicHero;
		internal DataHero DataHero;
		internal int Rank;
		/// <summary>Line index -> active graft schematic indices (empty when the side has no grafts).</summary>
		internal Dictionary<int, List<int>> GraftsByLine = new();
	}

	private sealed class MapHeroGrafts
	{
		internal string HeroSid;
		internal int Rank;
		internal Dictionary<int, List<int>> GraftsByLine;
	}

	private sealed class BattleUnitInfo
	{
		internal object Unit;
		internal int SideIndex;
		internal string UnitSid;
	}

	internal readonly struct ArtificingState
	{
		internal ArtificingState(int essence, int[] schematicTiers, int[,] graftSlots)
		{
			Essence = essence;
			SchematicTiers = schematicTiers;
			GraftSlots = graftSlots;
		}

		internal int Essence { get; }
		/// <summary>Schematic index -> lowest source tier transcribed (0 = not in the book).</summary>
		internal int[] SchematicTiers { get; }
		/// <summary>[line, slot] -> schematic index, -1 when empty.</summary>
		internal int[,] GraftSlots { get; }
	}

	internal static bool IsEnabled => Homm3TowerArtificingCatalog.Enabled;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null)
			return;
		_registrationAttempted = true;
		_log = log;
		if (!IsEnabled)
		{
			_log?.LogInfo(LogPrefix + "policy.enabled=false; runtime not registered (Tower keeps Arcane Battery).");
			return;
		}
		var hexAssembly = typeof(TransferBattle).Assembly;

		// Stage 1 (ledger): Logic.Hero -> Data.Hero and the hero map-buff manager (Captives pins).
		try
		{
			var logicHeroType = _logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing " + GameSymbols.CastleEliteStrategem.LogicHeroTypeName);
			_logicHeroDataHeroGetter = ResolveExactMethod(logicHeroType, typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
			_heroBuffManagerProperty = logicHeroType.GetProperty(GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                           ?? throw new MissingMemberException("homm3.tower.artificing.logicHero.buffManager not found on " + logicHeroType.FullName);
			var managerType = _heroBuffManagerProperty.PropertyType;
			_heroBuffAddMethod = ResolveExactMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd);
			_heroBuffRemoveMethod = ResolveExactMethod(managerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove);
			_heroBuffGetMethod = ResolveExactMethod(managerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet);
			if (!string.Equals(_heroBuffGetMethod.ReturnType.FullName, "Hex.Session.Logic.Buff", StringComparison.Ordinal))
				throw new MissingMethodException("homm3.tower.artificing hero buff Get returns " + _heroBuffGetMethod.ReturnType.FullName + ", expected Hex.Session.Logic.Buff");
			_ledgerRegistered = true;
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "[ledger] NOT registered (fail closed: no essence, no book, no grafts): " + ex.GetBaseException().Message);
			return;
		}

		// Stage 2 (battle): BattleLogic.Init side plans + shared Unit.Init graft apply.
		MethodInfo battleInit = null;
		try
		{
			var battleLogicType = ResolveTypeByHints(hexAssembly, GameSymbols.DraconicDominion.BattleLogicTypeHints, "homm3.tower.artificing.battleLogic");
			var transferBattleType = hexAssembly.GetType(GameSymbols.DraconicDominion.TransferBattleTypeName)
			                         ?? throw new TypeLoadException("Missing " + GameSymbols.DraconicDominion.TransferBattleTypeName);
			battleInit = ResolveExactMethod(battleLogicType, typeof(void), new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) }, GameSymbols.DraconicDominion.BattleLogicInit);
			if (!Homm3RuntimeMechanicHooks.TryRegisterSharedUnitInit(harmony, _log))
				throw new InvalidOperationException("shared Unit.Init owner did not register");
			Patch(harmony, battleInit, nameof(PrefixBattleLogicInit), null);
			if (!Homm3BattleUnitLawOwnerRegistry.TryRegisterUnitInitConsumer("homm3.tower.artificing", OnSharedUnitInit, out var consumerFailure))
				throw new InvalidOperationException("shared Unit.Init consumer registration failed: " + consumerFailure);
			_battleRegistered = true;
		}
		catch (Exception ex)
		{
			UnpatchOwned(harmony, battleInit, nameof(PrefixBattleLogicInit));
			_log?.LogError(LogPrefix + "[battle] NOT registered (no grafts applied; essence still needs the battle-result hook): " + ex.GetBaseException().Message);
		}

		// Stage 3 (capture): postfix on the exact unit buff add.
		try
		{
			var unitBuffManagerType = GameMember.FindType(GameSymbols.BuffDebuffLaws.BuffManagerTypeId, GameSymbols.BuffDebuffLaws.BuffManagerTypeHint)
			                          ?? throw new TypeLoadException("unit buff manager type not found");
			var buffAdd = FindBuffAdd(unitBuffManagerType);
			Patch(harmony, buffAdd, null, nameof(PostfixUnitBuffAdd));
			_captureRegistered = true;
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "[capture] NOT registered (Transcribe marks units but records nothing): " + ex.GetBaseException().Message);
		}

		// Stage 4 (combat): battle event dispatcher postfixes for on-hit, vampirism and first-round grafts.
		// Heal / berserk statics are optional: unresolved = that effect off, logged.
		if (_battleRegistered)
		{
			MethodInfo damageDispatcher = null;
			try
			{
				var hubType = ResolveLogicEventHubType() ?? throw new TypeLoadException("battle event hub type not found from BattleLogicEventsTypeHints");
				_healMethod = TryResolveStatic(hexAssembly, GameSymbols.TowerArtificing.UnitHealerTypeHints, GameSymbols.TowerArtificing.UnitHealerHeal, 4, "vampirism");
				_berserkMethod = TryResolveStatic(hexAssembly, GameSymbols.TowerArtificing.MechBerserkTypeHints, GameSymbols.TowerArtificing.MechBerserkApply, 6, "Fangarm berserk");
				damageDispatcher = ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher);
				Patch(harmony, damageDispatcher, null, nameof(PostfixObjectTookDamage), Priority.Last);
				_damageRegistered = true;
				Patch(harmony, ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher), null, nameof(PostfixRoundStarted), Priority.Last);
				_roundRegistered = true;
			}
			catch (Exception ex)
			{
				if (!_roundRegistered)
				{
					UnpatchOwned(harmony, damageDispatcher, nameof(PostfixObjectTookDamage));
					_damageRegistered = false;
				}
				_log?.LogError(LogPrefix + "[combat] NOT registered (no on-hit, vampirism or first-round grafts; once-per-battle grafts apply to every init): " + ex.GetBaseException().Message);
			}
		}

		// Stage 5 (map): hero-stat graft buffs follow the army (Logic.Hero.RecalculateStats, which native UnitSets
		// calls on every army change); daily gold and a slot refresh ride the shared side day-start grant.
		MethodInfo recalculate = null;
		try
		{
			recalculate = ResolveExactMethod(_logicHeroType, typeof(void), Type.EmptyTypes, GameSymbols.TowerArtificing.LogicHeroRecalculateStats);
			Patch(harmony, recalculate, null, nameof(PostfixHeroRecalculateStats));
			_mapRegistered = true;
		}
		catch (Exception ex)
		{
			UnpatchOwned(harmony, recalculate, nameof(PostfixHeroRecalculateStats));
			_log?.LogError(LogPrefix + "[map] hero-stat grafts NOT registered (no map graft buffs): " + ex.GetBaseException().Message);
		}
		if (Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.tower.artificing", OnDayStartHero, out var dayStartFailure))
			_dayStartRegistered = true;
		else
			_log?.LogError(LogPrefix + "[map] day-start consumer NOT registered (no graft gold; map buffs refresh only on army change): " + dayStartFailure);

		var summary = LogPrefix + "registration summary: ledger=" + Stage(_ledgerRegistered) + " battle=" + Stage(_battleRegistered)
			+ " capture=" + Stage(_captureRegistered) + " combat=" + Stage(_damageRegistered && _roundRegistered)
			+ " heal=" + Stage(_healMethod != null) + " berserk=" + Stage(_berserkMethod != null)
			+ " map=" + Stage(_mapRegistered) + " dayStart=" + Stage(_dayStartRegistered)
			+ " graftable=" + Homm3TowerArtificingCatalog.SchematicKeyByIndex.Count + ". Proof tier: build; runtime unproven.";
		if (_battleRegistered && _captureRegistered && _damageRegistered && _roundRegistered && _mapRegistered && _dayStartRegistered)
			_log?.LogInfo(summary);
		else
			_log?.LogError(summary);
	}

	// ---------------------------------------------------------------- battle start: grafts

	private static void PrefixBattleLogicInit(object __1)
	{
		lock (Gate)
		{
			SidesByIndex.Clear();
			UnitsByKey.Clear();
			CarriersByKey.Clear();
			_firstRoundStarted = false;
		}
		try
		{
			var sides = (__1 as TransferBattle)?.sides;
			if (sides == null)
				return;
			for (var sideIndex = 0; sideIndex < sides.Length; sideIndex++)
			{
				var side = sides[sideIndex];
				var dataHero = ResolveDataHero(side?.logicHero);
				var rank = ResolveRank(dataHero);
				if (rank <= 0)
					continue;
				var info = new BattleSideInfo { SideIndex = sideIndex, LogicHero = side.logicHero, DataHero = dataHero, Rank = rank };
				if (TryReadState(side.logicHero, out var state, out var readFail))
					info.GraftsByLine = ActiveGrafts(state, rank);
				else
					LogSkip("side " + sideIndex + " hero " + DescribeHero(dataHero) + " ledger unreadable (" + readFail + "); no grafts this battle.");
				lock (Gate)
					SidesByIndex[sideIndex] = info;
				LogEvent("battle start: side " + sideIndex + " hero " + DescribeHero(dataHero) + " rank=" + rank + " grafts=[" + DescribeGrafts(info.GraftsByLine) + "].");
			}
		}
		catch (Exception ex)
		{
			lock (Gate)
				SidesByIndex.Clear();
			LogSkip("battle-start plan failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Line -> schematic indices in the first SlotsForRank(rank) slots (graftable, deduped).</summary>
	internal static Dictionary<int, List<int>> ActiveGrafts(ArtificingState state, int rank)
	{
		var result = new Dictionary<int, List<int>>();
		var slots = SlotsForRank(rank);
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			for (var slot = 0; slot < slots; slot++)
			{
				var schematic = state.GraftSlots[line, slot];
				if (schematic < 0 || !Homm3TowerArtificingCatalog.SchematicKeyByIndex.ContainsKey(schematic))
					continue;
				if (!result.TryGetValue(line, out var list))
					result[line] = list = new List<int>();
				if (!list.Contains(schematic))
					list.Add(schematic);
			}
		}
		return result;
	}

	/// <summary>The graft buff a unit carries for a schematic: its perUnit variant, else the base row.</summary>
	internal static string GraftBuffSidFor(int schematic, string unitSid)
	{
		return Homm3TowerArtificingCatalog.GraftVariantBuffSid.TryGetValue(schematic + "|" + unitSid, out var variant)
			? variant
			: Homm3TowerArtificingCatalog.GraftBuffPrefix + schematic;
	}

	private static void OnSharedUnitInit(object unit, object[] args)
	{
		try
		{
			if (unit == null || args == null || args.Length < 3 || args[2] == null)
				return;
			BattleSideInfo info;
			bool lateInit;
			lock (Gate)
			{
				if (SidesByIndex.Count == 0)
					return;
				lateInit = _firstRoundStarted;
			}
			if (!(ReadMember(args[2], GameSymbols.BattleEventLaws.BattleSideWrapperLocalSideIndexMembers) is int sideIndex))
				return;
			if (!Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(unit, out var unitSid) || string.IsNullOrWhiteSpace(unitSid))
				return;
			unitSid = unitSid.Trim();
			if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var unitKey, out var keyFail))
			{
				LogSkip("unit " + unitSid + " untracked: unit key unresolved (" + keyFail + ").");
				return;
			}
			lock (Gate)
			{
				// Every unit is tracked: on-hit needs the receiver's side, first-round grafts count allies/enemies.
				UnitsByKey[unitKey] = new BattleUnitInfo { Unit = unit, SideIndex = sideIndex, UnitSid = unitSid };
				if (!SidesByIndex.TryGetValue(sideIndex, out info) || info.GraftsByLine.Count == 0 || CarriersByKey.ContainsKey(unitKey))
					return;
			}
			if (!Homm3TowerArtificingCatalog.TowerLineByUnitSid.TryGetValue(unitSid, out var line)
			    || !info.GraftsByLine.TryGetValue(line, out var schematics))
				return;
			var carried = new Dictionary<int, string>();
			var applied = new List<string>();
			var skipped = new List<string>();
			foreach (var schematic in schematics)
			{
				var buffSid = GraftBuffSidFor(schematic, unitSid);
				if (lateInit && Homm3TowerArtificingCatalog.OncePerBattleSchematics.Contains(schematic))
				{
					skipped.Add(buffSid + ":once-per-battle");
					continue;
				}
				if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, buffSid, unit, GraftBuffLevel, GraftBuffDuration, GraftBuffValue, true, out _, out var addFail))
				{
					applied.Add(buffSid);
					carried[schematic] = buffSid;
					if (Homm3TowerArtificingCatalog.InjectedAbilitiesBySchematic.TryGetValue(schematic, out var abilities))
						InjectAbilities(unit, unitSid, abilities, applied, skipped);
				}
				else
					_log?.LogError(LogPrefix + "graft buff " + buffSid + " on " + unitSid + " failed: " + addFail);
			}
			lock (Gate)
				CarriersByKey[unitKey] = carried;
			LogEvent("grafted " + unitSid + " (line " + line + ", side " + sideIndex + "): [" + string.Join(",", applied) + "]"
				+ (skipped.Count == 0 ? "" : " skipped [" + string.Join(",", skipped) + "]") + " of " + schematics.Count + ".");
		}
		catch (Exception ex)
		{
			LogSkip("unit graft apply failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- battle start: injected abilities

	/// <summary>Max alternative attacks + abilities the battle HUD shows (BhUnitControlsView.SetSkills, 5 fixed slots).</summary>
	private const int HudSkillSlots = 5;

	/// <summary>
	/// Appends fresh copies of the source unit's abilities (catalog JSON through JsonUtility, so every carrier owns
	/// its configs) to the carrier's AbilitiesSet[Ability] array, mirroring AbilitiesSet.InitAbilityArray: new Ability,
	/// caster first (Init reads caster.battleLogic), then Init(logic, view, AbilityID{Ability, index}). Skips the
	/// source unit itself and anything past the HUD slots.
	/// </summary>
	private static void InjectAbilities(object unit, string unitSid, InjectedAbilityGraft[] grafts, List<string> applied, List<string> skipped)
	{
		try
		{
			var manager = ReadMember(unit, GameSymbols.DirectStateLaws.UnitAbilityManagerMembers);
			if (!ResolveAbilityAccessors(manager, unit))
			{
				skipped.Add("abilities:" + _abilityAccessorFailure);
				return;
			}
			var dict = _abilityDictProperty.GetValue(manager);
			var dictType = dict?.GetType() ?? throw new InvalidOperationException("ability dictionary is null");
			var contains = (bool)dictType.GetMethod("ContainsKey").Invoke(dict, new object[] { EAbilityType.Ability });
			var current = contains ? dictType.GetMethod("get_Item").Invoke(dict, new object[] { EAbilityType.Ability }) : null;
			var existing = new List<object>();
			if (current != null)
			{
				var length = Convert.ToInt32(_abilityArrayType.GetProperty("Length").GetValue(current));
				var getItem = _abilityArrayType.GetMethod("get_Item", new[] { typeof(int) });
				for (var i = 0; i < length; i++)
					existing.Add(getItem.Invoke(current, new object[] { i }));
			}
			var hasAlternatives = (bool)dictType.GetMethod("ContainsKey").Invoke(dict, new object[] { EAbilityType.AlternativeAttack });
			var alternativeCount = hasAlternatives
				? Convert.ToInt32(_abilityArrayType.GetProperty("Length").GetValue(dictType.GetMethod("get_Item").Invoke(dict, new object[] { EAbilityType.AlternativeAttack })))
				: 0;
			var added = new List<object>();
			foreach (var graft in grafts)
			{
				var label = graft.SourceUnitSid + "#" + graft.SourceIndex;
				if (string.Equals(unitSid, graft.SourceUnitSid, StringComparison.Ordinal))
				{
					skipped.Add(label + ":native");
					continue;
				}
				if (alternativeCount + existing.Count + added.Count >= HudSkillSlots)
				{
					skipped.Add(label + ":no-hud-slot");
					continue;
				}
				var logic = new AbilityLogicConfig();
				UnityEngine.JsonUtility.FromJsonOverwrite(graft.LogicJson, logic);
				var view = new AbilityViewConfig();
				UnityEngine.JsonUtility.FromJsonOverwrite(graft.ViewJson, view);
				if (logic.damageDealer == null)
				{
					skipped.Add(label + ":config-parse");
					continue;
				}
				var ability = Activator.CreateInstance(_abilityType);
				_abilityCasterProperty.SetValue(ability, ToParameter(unit, _abilityCasterProperty.PropertyType));
				_abilityInitMethod.Invoke(ability, new object[] { logic, view, new AbilityID(EAbilityType.Ability, existing.Count + added.Count) });
				added.Add(ability);
				applied.Add("ability:" + label);
			}
			if (added.Count == 0)
				return;
			var array = Activator.CreateInstance(_abilityArrayType, (long)(existing.Count + added.Count));
			var setItem = _abilityArrayType.GetMethod("set_Item", new[] { typeof(int), _abilityType });
			var index = 0;
			foreach (var item in existing)
				setItem.Invoke(array, new[] { (object)index++, item });
			foreach (var item in added)
				setItem.Invoke(array, new[] { (object)index++, item });
			dictType.GetMethod("set_Item").Invoke(dict, new[] { (object)EAbilityType.Ability, array });
		}
		catch (Exception ex)
		{
			skipped.Add("abilities:threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Shape-resolves the ability dictionary (the manager's unique Dictionary keyed by EAbilityType), the Ability
	/// type, its caster member (the unique writable property the unit fits) and Init. Once; failure disables injection.</summary>
	private static bool ResolveAbilityAccessors(object manager, object unit)
	{
		if (_abilityAccessorsResolved)
			return _abilityDictProperty != null;
		if (manager == null)
		{
			_abilityAccessorFailure = "unit ability manager unreadable";
			return false;
		}
		_abilityAccessorsResolved = true;
		try
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			foreach (var property in manager.GetType().GetProperties(flags))
			{
				var type = property.PropertyType;
				if (!type.IsGenericType || type.GetGenericArguments().Length != 2 || type.GetGenericArguments()[0] != typeof(EAbilityType) || property.GetIndexParameters().Length != 0)
					continue;
				if (_abilityDictProperty != null)
					throw new AmbiguousMatchException("more than one EAbilityType dictionary on " + manager.GetType().FullName);
				_abilityDictProperty = property;
			}
			if (_abilityDictProperty == null)
				throw new MissingMemberException("no EAbilityType dictionary on " + manager.GetType().FullName);
			_abilityArrayType = _abilityDictProperty.PropertyType.GetGenericArguments()[1];
			if (!_abilityArrayType.IsGenericType || _abilityArrayType.GetGenericTypeDefinition() != typeof(Il2CppReferenceArray<>))
				throw new MissingMemberException("ability dictionary value is " + _abilityArrayType.FullName + ", expected Il2CppReferenceArray<Ability>");
			_abilityType = _abilityArrayType.GetGenericArguments()[0];
			foreach (var property in _abilityType.GetProperties(flags))
			{
				if (!property.CanWrite || property.GetIndexParameters().Length != 0 || !typeof(Il2CppObjectBase).IsAssignableFrom(property.PropertyType) || !property.PropertyType.IsInstanceOfType(unit))
					continue;
				if (_abilityCasterProperty != null)
					throw new AmbiguousMatchException("more than one unit-typed member on " + _abilityType.FullName);
				_abilityCasterProperty = property;
			}
			if (_abilityCasterProperty == null)
				throw new MissingMemberException("no caster member on " + _abilityType.FullName);
			_abilityInitMethod = ResolveExactMethod(_abilityType, typeof(void), new[] { typeof(AbilityLogicConfig), typeof(AbilityViewConfig), typeof(AbilityID) }, GameSymbols.TowerArtificing.AbilityInit);
			_log?.LogInfo(LogPrefix + "ability injection resolved: " + _abilityType.FullName + " caster=" + _abilityCasterProperty.Name + ".");
			return true;
		}
		catch (Exception ex)
		{
			_abilityDictProperty = null;
			_abilityAccessorFailure = "accessors unresolved (" + ex.GetBaseException().Message + ")";
			_log?.LogError(LogPrefix + "ability grafts off: " + _abilityAccessorFailure);
			return false;
		}
	}

	// ---------------------------------------------------------------- map: hero-stat buffs, daily gold

	private static void PostfixHeroRecalculateStats(object __instance)
	{
		if (_reconcilingMap || __instance == null || Homm3TowerArtificingCatalog.MapHeroBuffBySchematic.Count == 0)
			return;
		try
		{
			ReconcileMapBuffs(__instance, false, out _);
		}
		catch (Exception ex)
		{
			LogSkip("map graft reconcile failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Daily gold for one hero (shared side day-start grant); refreshes its graft slots and map buffs first.</summary>
	private static int OnDayStartHero(object entry)
	{
		if (entry == null || _logicHeroType == null || !_logicHeroType.IsInstanceOfType(entry))
			return 0;
		var grafts = ReconcileMapBuffs(entry, true, out var army);
		if (grafts == null || army == null || Homm3TowerArtificingCatalog.DailyGoldBySchematic.Count == 0)
			return 0;
		var gold = 0L;
		var parts = new List<string>();
		foreach (var (sid, stacks) in army)
		{
			if (!Homm3TowerArtificingCatalog.TowerLineByUnitSid.TryGetValue(sid, out var line) || !grafts.TryGetValue(line, out var schematics))
				continue;
			foreach (var schematic in schematics)
			{
				if (!Homm3TowerArtificingCatalog.DailyGoldBySchematic.TryGetValue(schematic, out var rates))
					continue;
				gold += (long)stacks * rates[line];
				parts.Add(sid + "x" + stacks + "@" + rates[line]);
			}
		}
		if (gold <= 0)
			return 0;
		var amount = (int)Math.Min(int.MaxValue / 2, gold);
		LogEvent("day-start gold for " + DescribeHero(ResolveDataHero(entry)) + ": +" + amount + " [" + string.Join(",", parts) + "].");
		return amount;
	}

	/// <summary>
	/// Holds each map graft buff exactly while the army has a stack of a line carrying it and no native unit of the
	/// source unit set (native set bonuses never stack). Returns the hero's active grafts (null = not an Artificing hero).
	/// </summary>
	private static Dictionary<int, List<int>> ReconcileMapBuffs(object logicHero, bool refresh, out List<(string Sid, int Stacks)> army)
	{
		army = null;
		var grafts = MapGraftsFor(logicHero, refresh);
		if (grafts == null)
			return null;
		var manager = ResolveHeroBuffManager(logicHero, out _);
		if (manager == null)
			return null;
		army = Homm3SwashbucklerGoldHook.ReadArmy(ResolveDataHero(logicHero));
		var armySids = new HashSet<string>();
		foreach (var (sid, _) in army ?? new List<(string Sid, int Stacks)>())
			armySids.Add(sid);
		var wanted = new HashSet<string>();
		foreach (var sid in armySids)
		{
			if (!Homm3TowerArtificingCatalog.TowerLineByUnitSid.TryGetValue(sid, out var line) || !grafts.TryGetValue(line, out var schematics))
				continue;
			foreach (var schematic in schematics)
			{
				if (!Homm3TowerArtificingCatalog.MapHeroBuffBySchematic.TryGetValue(schematic, out var buff))
					continue;
				var native = false;
				foreach (var nativeSid in buff.NativeUnitSids)
					native |= armySids.Contains(nativeSid);
				if (!native)
					wanted.Add(buff.BuffSid);
			}
		}
		var changes = new List<string>();
		_reconcilingMap = true;
		try
		{
			foreach (var buff in Homm3TowerArtificingCatalog.MapHeroBuffBySchematic.Values)
			{
				var want = wanted.Contains(buff.BuffSid);
				if ((_heroBuffGetMethod.Invoke(manager, new object[] { buff.BuffSid }) != null) == want)
					continue;
				if (want)
				{
					var durations = new Il2CppReferenceArray<BuffDuration>(1);
					durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
					_heroBuffAddMethod.Invoke(manager, new object[] { buff.BuffSid, durations });
				}
				else
					_heroBuffRemoveMethod.Invoke(manager, new object[] { buff.BuffSid });
				changes.Add((want ? "+" : "-") + buff.BuffSid);
			}
		}
		finally
		{
			_reconcilingMap = false;
		}
		if (changes.Count > 0)
			LogEvent("map grafts for " + DescribeHero(ResolveDataHero(logicHero)) + ": [" + string.Join(",", changes) + "]" + (army == null ? " (army unreadable)" : "") + ".");
		return grafts;
	}

	/// <summary>The hero's active grafts by line, cached per hero; only graft slot bits are read (not the book).</summary>
	private static Dictionary<int, List<int>> MapGraftsFor(object logicHero, bool refresh)
	{
		var dataHero = ResolveDataHero(logicHero);
		var rank = ResolveRank(dataHero);
		if (rank <= 0 || !(logicHero is Il2CppObjectBase il2Cpp) || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		var key = il2Cpp.Pointer.ToInt64();
		var heroSid = DescribeHero(dataHero);
		lock (Gate)
		{
			if (!refresh && MapGraftsByHero.TryGetValue(key, out var cached) && cached.Rank == rank && string.Equals(cached.HeroSid, heroSid, StringComparison.Ordinal))
				return cached.GraftsByLine;
		}
		var manager = ResolveHeroBuffManager(logicHero, out _);
		if (manager == null)
			return null;
		var grafts = new Dictionary<int, List<int>>();
		var slots = SlotsForRank(rank);
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			for (var slot = 0; slot < slots; slot++)
			{
				var schematic = ReadBits(manager, GraftBitPrefix(line, slot), Homm3TowerArtificingCatalog.GraftIndexBits) - 1;
				if (schematic < 0 || !Homm3TowerArtificingCatalog.SchematicKeyByIndex.ContainsKey(schematic))
					continue;
				if (!grafts.TryGetValue(line, out var list))
					grafts[line] = list = new List<int>();
				if (!list.Contains(schematic))
					list.Add(schematic);
			}
		}
		lock (Gate)
			MapGraftsByHero[key] = new MapHeroGrafts { HeroSid = heroSid, Rank = rank, GraftsByLine = grafts };
		return grafts;
	}

	// ---------------------------------------------------------------- combat: on hit, vampirism, first round

	private const string BasicAttackTag = "basic_attack";

	private static void PostfixObjectTookDamage(object __instance, object[] __args)
	{
		if (_observingDamage || __args == null || __args.Length < 2)
			return;
		lock (Gate)
		{
			if (CarriersByKey.Count == 0)
				return;
		}
		_observingDamage = true;
		try
		{
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(__args[1], out var hit, out _)
			    || hit.Damage <= 0 || hit.ImmuneToDamage || hit.Caster == null || hit.Receiver == null)
				return;
			if (!Homm3DirectStateIdentity.TryResolveKey(hit.Caster, out var casterKey, out _)
			    || !Homm3DirectStateIdentity.TryResolveKey(hit.Receiver, out var receiverKey, out _))
				return;
			Dictionary<int, string> grafts;
			BattleUnitInfo caster;
			BattleUnitInfo receiver;
			lock (Gate)
			{
				if (!CarriersByKey.TryGetValue(casterKey, out grafts) || grafts.Count == 0
				    || !UnitsByKey.TryGetValue(casterKey, out caster)
				    || !UnitsByKey.TryGetValue(receiverKey, out receiver)
				    || receiver.SideIndex == caster.SideIndex)
					return;
				grafts = new Dictionary<int, string>(grafts);
			}
			var tags = ReadDealerTags(hit.Dealer);
			if (!tags.Contains(BasicAttackTag))
				return;
			foreach (var pair in grafts)
				ApplyOnHit(pair.Key, pair.Value, caster, receiver, hit.Damage, tags);
		}
		catch (Exception ex)
		{
			LogSkip("on-hit graft failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_observingDamage = false;
		}
	}

	private static void ApplyOnHit(int schematic, string graftSid, BattleUnitInfo caster, BattleUnitInfo receiver, int damage, HashSet<string> tags)
	{
		Homm3TowerArtificingCatalog.OnHitBySchematic.TryGetValue(schematic, out var onHit);
		var hasVampirism = Homm3TowerArtificingCatalog.VampirismBySchematic.TryGetValue(schematic, out var vampirism);
		if (onHit == null && !hasVampirism)
			return;
		if (!CarrierStillGrafted(caster.Unit, graftSid))
			return;
		var done = new List<string>();
		foreach (var entry in onHit ?? Array.Empty<OnHitGraft>())
		{
			if (entry.AttackTag != null && !tags.Contains(entry.AttackTag))
				continue;
			if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(receiver.Unit, entry.BuffSid, caster.Unit, GraftBuffLevel, entry.Duration, GraftBuffValue, true, out _, out var addFail))
			{
				LogSkip("on-hit " + entry.BuffSid + " from " + caster.UnitSid + " on " + receiver.UnitSid + " did not stick (immune?): " + addFail);
				continue;
			}
			done.Add(entry.BuffSid);
			if (Homm3TowerArtificingCatalog.BerserkOnHitSchematics.Contains(schematic))
				done.Add(TryBerserk(receiver) ? "berserk" : "berserk:failed");
		}
		if (hasVampirism)
			done.Add(ApplyVampirism(vampirism, caster, damage));
		if (done.Count > 0)
			LogEvent("on-hit " + graftSid + ": " + caster.UnitSid + " -> " + receiver.UnitSid + " dmg=" + damage + " [" + string.Join(",", done) + "].");
	}

	private static string ApplyVampirism(VampirismGraft vampirism, BattleUnitInfo caster, int damage)
	{
		var amount = (int)Math.Round(damage * vampirism.Rate, MidpointRounding.AwayFromZero);
		if (amount <= 0)
			return "heal:0";
		if (_healMethod == null)
			return "heal:unresolved";
		var parameters = _healMethod.GetParameters();
		object healType;
		try
		{
			healType = Enum.Parse(parameters[2].ParameterType, vampirism.HealType);
		}
		catch (ArgumentException)
		{
			return "heal:unknown EHealType " + vampirism.HealType;
		}
		var targets = new List<BattleUnitInfo>();
		if (string.Equals(vampirism.Target, "self", StringComparison.Ordinal))
			targets.Add(caster);
		else
		{
			lock (Gate)
			{
				foreach (var unit in UnitsByKey.Values)
				{
					if (unit.SideIndex == caster.SideIndex && !ReferenceEquals(unit, caster))
						targets.Add(unit);
				}
			}
		}
		var healed = 0;
		foreach (var target in targets)
		{
			// Native Heal skips dead stacks unless revive is set; revive stays false.
			var unit = ToParameter(target.Unit, parameters[0].ParameterType);
			if (unit == null)
				continue;
			_healMethod.Invoke(null, new[] { unit, amount, healType, false });
			healed++;
		}
		return "heal " + amount + " x" + healed + " (" + vampirism.HealType + ")";
	}

	private static bool TryBerserk(BattleUnitInfo receiver)
	{
		if (_berserkMethod == null)
			return false;
		try
		{
			var parameters = _berserkMethod.GetParameters();
			var logic = ToParameter(ReadMember(receiver.Unit, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers), parameters[0].ParameterType);
			var target = ToParameter(receiver.Unit, parameters[3].ParameterType);
			if (logic == null || target == null)
			{
				LogSkip("berserk on " + receiver.UnitSid + " refused: battle logic or target unresolved.");
				return false;
			}
			_berserkMethod.Invoke(null, new[]
			{
				logic,
				Activator.CreateInstance(parameters[1].ParameterType),
				Activator.CreateInstance(parameters[2].ParameterType),
				target,
				1,
				Activator.CreateInstance(parameters[5].ParameterType),
			});
			return true;
		}
		catch (Exception ex)
		{
			LogSkip("berserk on " + receiver.UnitSid + " failed closed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		List<KeyValuePair<long, Dictionary<int, string>>> carriers;
		List<BattleUnitInfo> units;
		Dictionary<long, BattleUnitInfo> unitsByKey;
		lock (Gate)
		{
			if (_firstRoundStarted || SidesByIndex.Count == 0)
				return;
			_firstRoundStarted = true;
			if (CarriersByKey.Count == 0)
				return;
			carriers = new List<KeyValuePair<long, Dictionary<int, string>>>(CarriersByKey);
			unitsByKey = new Dictionary<long, BattleUnitInfo>(UnitsByKey);
			units = new List<BattleUnitInfo>(UnitsByKey.Values);
		}
		try
		{
			var sharedDone = new HashSet<string>();
			foreach (var pair in carriers)
			{
				if (!unitsByKey.TryGetValue(pair.Key, out var carrier))
					continue;
				foreach (var graft in pair.Value)
				{
					if (Homm3TowerArtificingCatalog.BattleStartBySchematic.TryGetValue(graft.Key, out var synergy)
					    && CarrierStillGrafted(carrier.Unit, graft.Value))
						ApplyFirstRound(graft.Key, synergy, carrier, units, sharedDone);
				}
			}
		}
		catch (Exception ex)
		{
			LogSkip("first-round grafts failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void ApplyFirstRound(int schematic, BattleStartGraft synergy, BattleUnitInfo carrier, List<BattleUnitInfo> units, HashSet<string> sharedDone)
	{
		var buffs = new List<KeyValuePair<BattleUnitInfo, string>>();
		string detail;
		switch (synergy.Kind)
		{
			case "enemy_faction_buffs":
			{
				var factions = new HashSet<string>();
				foreach (var unit in units)
				{
					if (unit.SideIndex != carrier.SideIndex && Homm3TowerArtificingCatalog.UnitFactionBySid.TryGetValue(unit.UnitSid, out var faction))
						factions.Add(faction);
				}
				for (var i = 0; i < synergy.Keys.Length && i < synergy.BuffSids.Length; i++)
				{
					if (factions.Contains(synergy.Keys[i]))
						buffs.Add(new KeyValuePair<BattleUnitInfo, string>(carrier, synergy.BuffSids[i]));
				}
				detail = "enemy factions [" + string.Join(",", factions) + "]";
				break;
			}
			case "ally_hive_count":
			{
				var kinds = new HashSet<string>();
				var wanted = new HashSet<string>(synergy.Keys);
				foreach (var unit in units)
				{
					if (unit.SideIndex == carrier.SideIndex && Homm3TowerArtificingCatalog.UnitFactionBySid.TryGetValue(unit.UnitSid, out var faction) && wanted.Contains(faction))
						kinds.Add(unit.UnitSid);
				}
				if (kinds.Count > 0 && synergy.BuffSids.Length > 0)
					buffs.Add(new KeyValuePair<BattleUnitInfo, string>(carrier, synergy.BuffSids[Math.Min(kinds.Count, synergy.BuffSids.Length) - 1]));
				detail = kinds.Count + " allied " + string.Join("/", synergy.Keys) + " kind(s)";
				break;
			}
			case "enemy_flyer_buff":
			{
				// One application per Artificing side, not per carrier stack.
				if (!sharedDone.Add(schematic + "|" + carrier.SideIndex) || synergy.BuffSids.Length == 0)
					return;
				foreach (var unit in units)
				{
					if (unit.SideIndex != carrier.SideIndex && Homm3TowerArtificingCatalog.FlyerUnitSids.Contains(unit.UnitSid))
						buffs.Add(new KeyValuePair<BattleUnitInfo, string>(unit, synergy.BuffSids[0]));
				}
				detail = buffs.Count + " enemy flyer stack(s)";
				break;
			}
			default:
				LogSkip("first-round graft " + schematic + " has unknown kind " + synergy.Kind + "; skipped.");
				return;
		}
		var applied = new List<string>();
		foreach (var pair in buffs)
		{
			if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(pair.Key.Unit, pair.Value, carrier.Unit, GraftBuffLevel, synergy.Duration, GraftBuffValue, true, out _, out var addFail))
				applied.Add(pair.Key.UnitSid + ":" + pair.Value);
			else
				LogSkip("first-round " + pair.Value + " on " + pair.Key.UnitSid + " did not stick: " + addFail);
		}
		LogEvent("first round " + schematic + " (" + synergy.Kind + ") for " + carrier.UnitSid + ": " + detail + " -> [" + string.Join(",", applied) + "].");
	}

	private static bool CarrierStillGrafted(object unit, string graftSid)
	{
		return Homm3BuffDebuffNativeAdapter.TryResolveBuffManagerFromReceiver(unit, out var manager, out _)
		       && Homm3BuffDebuffNativeAdapter.TryQueryBuffSid(manager, graftSid, out var info, out _)
		       && info.HasSid;
	}

	private static HashSet<string> ReadDealerTags(object dealer)
	{
		var tags = new HashSet<string>(StringComparer.Ordinal);
		var config = ReadMember(dealer, GameSymbols.TowerArtificing.CastDealerConfigMembers);
		foreach (var tag in EnumerateObjects(ReadMember(config, GameSymbols.TowerArtificing.CastDealerConfigTagsMembers)))
		{
			if (tag is string text && !string.IsNullOrWhiteSpace(text))
				tags.Add(text.Trim());
		}
		return tags;
	}

	/// <summary>The value as an exact interop parameter type: re-wraps an Il2Cpp proxy of another wrapper type by pointer.</summary>
	private static object ToParameter(object value, Type parameterType)
	{
		if (value == null || parameterType.IsInstanceOfType(value))
			return value;
		if (value is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero && typeof(Il2CppObjectBase).IsAssignableFrom(parameterType))
			return Activator.CreateInstance(parameterType, il2Cpp.Pointer);
		return null;
	}

	private static MethodInfo TryResolveStatic(Assembly assembly, string[] typeHints, GameSymbols.MethodSymbol symbol, int parameterCount, string feature)
	{
		try
		{
			var type = ResolveTypeByHints(assembly, typeHints, symbol.Id);
			MethodInfo selected = null;
			foreach (var name in symbol.NameHints ?? Array.Empty<string>())
			{
				foreach (var method in type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
				{
					if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void) || method.GetParameters().Length != parameterCount)
						continue;
					if (selected != null && !ReferenceEquals(selected, method))
						throw new AmbiguousMatchException(symbol.Id + " matched more than one " + name);
					selected = method;
				}
				if (selected != null)
					return selected;
			}
			throw new MissingMethodException(symbol.Id + " not found on " + type.FullName);
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "[combat] " + feature + " off: " + ex.GetBaseException().Message);
			return null;
		}
	}

	internal static Type ResolveLogicEventHubType()
	{
		foreach (var hint in GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints)
		{
			var type = GameMember.FindType("directState.battleEventHub." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	/// <summary>The hub's exact (object, BattleEventArgs) void dispatcher for the symbol; ambiguity throws.</summary>
	internal static MethodInfo ResolveHubDispatcher(Type hubType, GameSymbols.MethodSymbol symbol)
	{
		MethodInfo selected = null;
		var methods = hubType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 2 || !string.Equals(parameters[1].ParameterType.Name, "BattleEventArgs", StringComparison.Ordinal))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
					throw new AmbiguousMatchException(symbol.Id + " matched more than one dispatcher on " + hubType.FullName);
				selected = method;
			}
		}
		return selected ?? throw new MissingMethodException(symbol.Id + " dispatcher not found on " + hubType.FullName);
	}

	// ---------------------------------------------------------------- Transcribe capture

	private static void PostfixUnitBuffAdd(object __instance, object __result, [HarmonyArgument(0)] string sid, [HarmonyArgument(3)] object caster)
	{
		if (__result == null || !string.Equals(sid, Homm3TowerArtificingCatalog.TranscribeEffectBuffSid, StringComparison.Ordinal))
			return;
		try
		{
			var receiver = ReadMember(__instance, GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers);
			if (receiver == null || !Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(receiver, out var unitSid) || string.IsNullOrWhiteSpace(unitSid))
			{
				_log?.LogError(LogPrefix + "Transcribe refused: marked unit unresolved (receiver " + (receiver?.GetType().FullName ?? "null") + ").");
				return;
			}
			unitSid = unitSid.Trim();
			if (!TryResolveCasterHero(caster, out var logicHero, out var route, out var heroFail))
			{
				_log?.LogError(LogPrefix + "Transcribe of " + unitSid + " refused: caster hero unresolved (" + heroFail + ").");
				return;
			}
			var result = Transcribe(logicHero, unitSid, out var detail);
			LogEvent("Transcribe " + unitSid + " by " + DescribeHero(ResolveDataHero(logicHero)) + " via " + route + ": " + (result ? "recorded " : "nothing recorded: ") + detail + ".");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "Transcribe capture failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool TryResolveCasterHero(object caster, out object logicHero, out string route, out string failReason)
	{
		logicHero = null;
		route = null;
		failReason = null;
		if (ReadMember(caster, GameSymbols.BuffDebuffLaws.BuffReceiverSideMembers) is TransferSide side && side.logicHero != null && ResolveRank(ResolveDataHero(side.logicHero)) > 0)
		{
			logicHero = side.logicHero;
			route = "caster TransferSide";
			return true;
		}
		var candidates = new List<object>();
		lock (Gate)
		{
			foreach (var info in SidesByIndex.Values)
				candidates.Add(info.LogicHero);
		}
		if (candidates.Count == 1)
		{
			logicHero = candidates[0];
			route = "only Artificing hero in battle (caster " + (caster?.GetType().FullName ?? "null") + " exposed no TransferSide)";
			return true;
		}
		failReason = "caster " + (caster?.GetType().FullName ?? "null") + " exposed no TransferSide and the battle has " + candidates.Count + " Artificing heroes";
		return false;
	}

	/// <summary>Writes a unit's graftable schematics into the hero's book, keeping the lowest source tier.</summary>
	internal static bool Transcribe(object logicHero, string unitSid, out string detail)
	{
		if (!Homm3TowerArtificingCatalog.UnitTierBySid.TryGetValue(unitSid, out var tier) || tier < 1 || tier > MaxSchematicTier)
		{
			detail = "unit has no catalog tier";
			return false;
		}
		if (!Homm3TowerArtificingCatalog.GraftableSchematicsByUnitSid.TryGetValue(unitSid, out var schematics) || schematics.Length == 0)
		{
			detail = "unit has no graftable passives (tier " + tier + ")";
			return false;
		}
		var manager = ResolveHeroBuffManager(logicHero, out detail);
		if (manager == null)
			return false;
		var failures = new List<string>();
		var changes = new List<string>();
		foreach (var schematic in schematics)
		{
			var current = ReadBits(manager, SchematicBitPrefix(schematic), Homm3TowerArtificingCatalog.SchematicTierBits);
			if (current != 0 && current <= tier)
				continue;
			WriteBits(manager, SchematicBitPrefix(schematic), Homm3TowerArtificingCatalog.SchematicTierBits, tier, failures);
			changes.Add(Homm3TowerArtificingCatalog.SchematicKeyByIndex[schematic] + " tier " + (current == 0 ? "new" : current + "->") + tier);
		}
		if (failures.Count > 0)
		{
			detail = "ledger write incomplete: " + string.Join("; ", failures);
			return false;
		}
		detail = changes.Count == 0 ? "book already holds these at tier <= " + tier : string.Join(", ", changes);
		return changes.Count > 0;
	}

	// ---------------------------------------------------------------- battle result: essence

	/// <summary>Called by Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup before the native result applies.</summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		if (!_ledgerRegistered || battleLogic == null)
			return;
		try
		{
			var key = BattleKey(battleLogic);
			lock (Gate)
			{
				if (!AwardedBattles.Add(key))
					return;
			}
			var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			if (transfer?.sides == null || started?.sides == null || result == null)
			{
				LogSkip("battle " + key + " result unreadable; no essence.");
				return;
			}
			var winnerIndex = result.winnerIndex;
			if (winnerIndex < 0 || winnerIndex >= started.sides.Length)
				return;
			var logicHero = started.sides[winnerIndex]?.logicHero ?? (winnerIndex < transfer.sides.Length ? transfer.sides[winnerIndex]?.logicHero : null);
			var dataHero = ResolveDataHero(logicHero);
			if (ResolveRank(dataHero) <= 0)
				return;
			var essence = 0L;
			var parts = new List<string>();
			for (var sideIndex = 0; sideIndex < started.sides.Length; sideIndex++)
			{
				if (sideIndex == winnerIndex)
					continue;
				var after = sideIndex < transfer.sides.Length ? transfer.sides[sideIndex] : null;
				essence += SumEssence(started.sides[sideIndex], after, parts);
			}
			if (essence <= 0)
			{
				LogEvent("battle " + key + " won by " + DescribeHero(dataHero) + ": no essence (lost=[" + string.Join(",", parts) + "]).");
				return;
			}
			if (!TryAddEssence(logicHero, (int)Math.Min(MaxEssence, essence), out var before, out var after2, out var fail))
			{
				_log?.LogError(LogPrefix + "essence award for " + DescribeHero(dataHero) + " failed: " + fail);
				return;
			}
			LogEvent("battle " + key + " won by " + DescribeHero(dataHero) + ": essence +" + essence + " (" + before + "->" + after2 + ", lost=[" + string.Join(",", parts) + "]).");
		}
		catch (Exception ex)
		{
			LogSkip("battle-result essence failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static long SumEssence(TransferSide started, TransferSide after, List<string> parts)
	{
		if (started?.units == null)
			return 0;
		var total = 0L;
		foreach (var before in started.units)
		{
			if (before == null || before.stacks <= 0)
				continue;
			var sid = before.configSid?.Trim();
			var remaining = 0;
			if (after?.units != null)
			{
				foreach (var candidate in after.units)
				{
					if (candidate != null && candidate.slotPos == before.slotPos && string.Equals(candidate.configSid?.Trim(), sid, StringComparison.Ordinal))
					{
						remaining = Math.Max(0, candidate.stacks);
						break;
					}
				}
			}
			var lost = Math.Max(0, before.stacks - remaining);
			if (lost == 0)
				continue;
			if (sid == null || !Homm3TowerArtificingCatalog.UnitTierBySid.TryGetValue(sid, out var tier) || tier < 1 || tier > Homm3TowerArtificingCatalog.EssencePerCreatureByTier.Length)
			{
				parts.Add((sid ?? "?") + "x" + lost + ":untiered");
				continue;
			}
			total += (long)lost * Homm3TowerArtificingCatalog.EssencePerCreatureByTier[tier - 1];
			parts.Add(sid + "x" + lost + ":t" + tier);
		}
		return total;
	}

	// ---------------------------------------------------------------- spend

	/// <summary>
	/// Grafts a Schematic Book passive onto a Tower line slot and pays its essence. Replacing a filled slot pays the
	/// full new cost (no refund). Fails closed with the reason; the ledger is untouched unless every check passed.
	/// </summary>
	internal static bool TryGraft(object logicHero, int line, int slot, int schematic, out int cost, out string failReason)
	{
		cost = 0;
		var dataHero = ResolveDataHero(logicHero);
		var rank = ResolveRank(dataHero);
		if (!IsEnabled || !_ledgerRegistered)
		{
			failReason = "Artificing runtime not enabled/registered";
			return false;
		}
		if (rank <= 0)
		{
			failReason = "hero lacks " + Homm3TowerArtificingCatalog.FactionSkillSid;
			return false;
		}
		if (line < 0 || line >= Homm3TowerArtificingCatalog.Lines)
		{
			failReason = "line " + line + " outside 0.." + (Homm3TowerArtificingCatalog.Lines - 1);
			return false;
		}
		if (slot < 0 || slot >= SlotsForRank(rank))
		{
			failReason = "slot " + slot + " not unlocked at rank " + rank + " (" + SlotsForRank(rank) + " slot(s))";
			return false;
		}
		if (!Homm3TowerArtificingCatalog.SchematicKeyByIndex.ContainsKey(schematic) || schematic + 1 > MaxGraftValue)
		{
			failReason = "schematic " + schematic + " is not graftable";
			return false;
		}
		if (!TryReadState(logicHero, out var state, out failReason))
			return false;
		var sourceTier = state.SchematicTiers[schematic];
		if (sourceTier <= 0)
		{
			failReason = "schematic " + Homm3TowerArtificingCatalog.SchematicKeyByIndex[schematic] + " is not in the Schematic Book";
			return false;
		}
		for (var other = 0; other < Homm3TowerArtificingCatalog.MaxSlots; other++)
		{
			if (other != slot && state.GraftSlots[line, other] == schematic)
			{
				failReason = "line " + line + " already carries schematic " + schematic + " in slot " + other;
				return false;
			}
		}
		cost = Homm3TowerArtificingCatalog.GraftCost[sourceTier - 1, line];
		if (state.Essence < cost)
		{
			failReason = "needs " + cost + " Arcane Essence, has " + state.Essence;
			return false;
		}
		var manager = ResolveHeroBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		var failures = new List<string>();
		WriteBits(manager, Homm3TowerArtificingCatalog.EssenceBitPrefix, Homm3TowerArtificingCatalog.EssenceBits, state.Essence - cost, failures);
		WriteBits(manager, GraftBitPrefix(line, slot), Homm3TowerArtificingCatalog.GraftIndexBits, schematic + 1, failures);
		if (failures.Count > 0)
		{
			failReason = "ledger write incomplete (state may be partial): " + string.Join("; ", failures);
			_log?.LogError(LogPrefix + "graft for " + DescribeHero(dataHero) + " " + failReason);
			return false;
		}
		LogEvent("graft bought: " + DescribeHero(dataHero) + " line " + line + " slot " + slot + " <- " + Homm3TowerArtificingCatalog.SchematicKeyByIndex[schematic]
			+ " (source tier " + sourceTier + ") for " + cost + " essence (" + state.Essence + "->" + (state.Essence - cost) + ").");
		try
		{
			ReconcileMapBuffs(logicHero, true, out _);
		}
		catch (Exception ex)
		{
			LogSkip("map graft refresh after graft failed (next army change or day start retries): " + ex.GetBaseException().Message);
		}
		failReason = null;
		return true;
	}

	// ---------------------------------------------------------------- ledger codec

	internal static bool TryReadState(object logicHero, out ArtificingState state, out string failReason)
	{
		state = default;
		var manager = ResolveHeroBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		var essence = ReadBits(manager, Homm3TowerArtificingCatalog.EssenceBitPrefix, Homm3TowerArtificingCatalog.EssenceBits);
		var tiers = new int[Homm3TowerArtificingCatalog.SchematicCount];
		foreach (var schematic in Homm3TowerArtificingCatalog.SchematicKeyByIndex.Keys)
			tiers[schematic] = ReadBits(manager, SchematicBitPrefix(schematic), Homm3TowerArtificingCatalog.SchematicTierBits);
		var slots = new int[Homm3TowerArtificingCatalog.Lines, Homm3TowerArtificingCatalog.MaxSlots];
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			for (var slot = 0; slot < Homm3TowerArtificingCatalog.MaxSlots; slot++)
				slots[line, slot] = ReadBits(manager, GraftBitPrefix(line, slot), Homm3TowerArtificingCatalog.GraftIndexBits) - 1;
		}
		state = new ArtificingState(essence, tiers, slots);
		return true;
	}

	private static bool TryAddEssence(object logicHero, int amount, out int before, out int after, out string failReason)
	{
		before = after = 0;
		var manager = ResolveHeroBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		before = ReadBits(manager, Homm3TowerArtificingCatalog.EssenceBitPrefix, Homm3TowerArtificingCatalog.EssenceBits);
		after = (int)Math.Min(MaxEssence, (long)before + amount);
		var failures = new List<string>();
		WriteBits(manager, Homm3TowerArtificingCatalog.EssenceBitPrefix, Homm3TowerArtificingCatalog.EssenceBits, after, failures);
		failReason = failures.Count == 0 ? null : string.Join("; ", failures);
		return failures.Count == 0;
	}

	private static string SchematicBitPrefix(int schematic)
	{
		return Homm3TowerArtificingCatalog.SchematicBitPrefix + schematic + "_bit_";
	}

	private static string GraftBitPrefix(int line, int slot)
	{
		return Homm3TowerArtificingCatalog.GraftBitPrefix + "l" + line + "_s" + slot + "_bit_";
	}

	private static int ReadBits(object manager, string prefix, int bits)
	{
		var value = 0;
		for (var bit = 0; bit < bits; bit++)
		{
			if (_heroBuffGetMethod.Invoke(manager, new object[] { prefix + bit }) != null)
				value |= 1 << bit;
		}
		return value;
	}

	private static void WriteBits(object manager, string prefix, int bits, int value, List<string> failures)
	{
		for (var bit = 0; bit < bits; bit++)
		{
			var sid = prefix + bit;
			var wanted = (value & (1 << bit)) != 0;
			try
			{
				if ((_heroBuffGetMethod.Invoke(manager, new object[] { sid }) != null) == wanted)
					continue;
				if (wanted)
				{
					var durations = new Il2CppReferenceArray<BuffDuration>(1);
					durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
					_heroBuffAddMethod.Invoke(manager, new object[] { sid, durations });
				}
				else
				{
					// Native Remove only drops dispellable configs: the ledger rows are isDispellable=true.
					_heroBuffRemoveMethod.Invoke(manager, new object[] { sid });
				}
				if ((_heroBuffGetMethod.Invoke(manager, new object[] { sid }) != null) != wanted)
					failures.Add(sid + (wanted ? " add did not stick (row missing from Core?)" : " remove did not stick"));
			}
			catch (Exception ex)
			{
				failures.Add(sid + " threw " + ex.GetBaseException().Message);
			}
		}
	}

	private static object ResolveHeroBuffManager(object logicHero, out string failReason)
	{
		failReason = null;
		if (!_ledgerRegistered)
		{
			failReason = "ledger stage not registered";
			return null;
		}
		if (logicHero == null || !_heroBuffManagerProperty.DeclaringType.IsInstanceOfType(logicHero))
		{
			failReason = "logic hero missing or not Hex.Session.Logic.Hero";
			return null;
		}
		var manager = _heroBuffManagerProperty.GetValue(logicHero);
		if (manager == null)
			failReason = "hero buff manager is null";
		return manager;
	}

	// ---------------------------------------------------------------- helpers

	internal static int SlotsForRank(int rank)
	{
		return rank < 1 ? 0 : Homm3TowerArtificingCatalog.GraftSlotsByRank[Math.Min(rank, Homm3TowerArtificingCatalog.GraftSlotsByRank.Length) - 1];
	}

	/// <summary>Faction-skill rank 1..3 of skill_faction_homm3_tower, 0 when absent or unreadable.</summary>
	private static int ResolveRank(DataHero dataHero)
	{
		if (dataHero == null)
			return 0;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = (ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string)?.Trim();
			if (!string.Equals(sid, Homm3TowerArtificingCatalog.FactionSkillSid, StringComparison.Ordinal))
				continue;
			return ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers) is int level ? Math.Max(1, Math.Min(3, level)) : 0;
		}
		return 0;
	}

	private static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	private static string DescribeHero(DataHero dataHero)
	{
		return dataHero == null ? "null" : dataHero.configSid ?? "?";
	}

	private static string DescribeGrafts(Dictionary<int, List<int>> grafts)
	{
		var parts = new List<string>();
		foreach (var pair in grafts)
			parts.Add("l" + pair.Key + ":" + string.Join("+", pair.Value));
		return string.Join(",", parts);
	}

	private static int BattleKey(object battleLogic)
	{
		if (ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicIdFields) is int id && id != 0)
			return id;
		if (battleLogic is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			var ptr = il2Cpp.Pointer.ToInt64();
			return unchecked((int)(ptr ^ (ptr >> 32)));
		}
		return battleLogic.GetHashCode();
	}

	internal static MethodInfo FindBuffAdd(Type managerType)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var matches = new List<MethodInfo>();
		foreach (var name in GameSymbols.BuffDebuffLaws.BuffAdd.NameHints ?? Array.Empty<string>())
		{
			foreach (var method in managerType.GetMethods(flags))
			{
				var parameters = method.GetParameters();
				if (string.Equals(method.Name, name, StringComparison.Ordinal) && parameters.Length == 6
				    && parameters[0].ParameterType == typeof(string) && method.ReturnType != typeof(void) && !matches.Contains(method))
					matches.Add(method);
			}
			if (matches.Count == 1)
				return matches[0];
			if (matches.Count > 1)
				throw new AmbiguousMatchException(GameSymbols.BuffDebuffLaws.BuffAdd.Id + " matched " + matches.Count + " methods named " + name);
		}
		throw new MissingMethodException(GameSymbols.BuffDebuffLaws.BuffAdd.Id + " (string, int, int, source, int, bool) not found on " + managerType.FullName);
	}

	internal static MethodInfo ResolveExactMethod(Type type, Type returnType, Type[] parameterTypes, GameSymbols.MethodSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || (returnType != null && method.ReturnType != returnType))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length && exact; i++)
					exact = parameters[i].ParameterType == parameterTypes[i];
				if (exact)
					return method;
			}
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + (type?.FullName ?? "null"));
	}

	internal static Type ResolveTypeByHints(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = string.IsNullOrWhiteSpace(hint) ? null : assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new TypeLoadException(symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName, int postfixPriority = -1)
	{
		PatchOwned(harmony, typeof(Homm3TowerArtificingRuntime), target, prefixName, postfixName, postfixPriority);
	}

	/// <summary>Patch target with the owner type's named prefix / postfix after the Harmony compatibility check.</summary>
	internal static void PatchOwned(Harmony harmony, Type owner, MethodInfo target, string prefixName, string postfixName, int postfixPriority = -1)
	{
		var prefix = prefixName == null ? null : GameMember.FindOwnedPatchMethod(owner, prefixName);
		var postfix = postfixName == null ? null : GameMember.FindOwnedPatchMethod(owner, postfixName);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + target.Name + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + target.Name + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : postfixPriority < 0 ? new HarmonyMethod(postfix) : new HarmonyMethod(postfix) { priority = postfixPriority });
	}

	private static void UnpatchOwned(Harmony harmony, MethodInfo target, string patchName)
	{
		UnpatchOwned(harmony, typeof(Homm3TowerArtificingRuntime), target, patchName);
	}

	internal static void UnpatchOwned(Harmony harmony, Type owner, MethodInfo target, string patchName)
	{
		if (harmony == null || target == null)
			return;
		var patch = GameMember.FindOwnedPatchMethod(owner, patchName);
		if (patch == null)
			return;
		try
		{
			harmony.Unpatch(target, patch);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "rollback failed for " + patchName + ": " + ex.Message);
		}
	}

	internal static object ReadMember(object target, IEnumerable<string> names)
	{
		if (target == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0 && property.CanRead)
				return property.GetValue(target);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(target);
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void))
				return method.Invoke(target, null);
		}
		return null;
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

	private static string Stage(bool ok)
	{
		return ok ? "ok" : "FAILED";
	}

	private static void LogEvent(string message)
	{
		if (_loggedEvents++ < 80)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips++ < 40)
			_log?.LogWarning(LogPrefix + message);
	}
}
