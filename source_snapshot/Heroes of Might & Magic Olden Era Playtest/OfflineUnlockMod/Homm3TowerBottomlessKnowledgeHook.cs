using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Data;
using Il2CppInterop.Runtime.InteropTypes;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Mana Well Aegis subskill under Tower Arcane Battery.
/// Postfixes the native ManaPercentSettingReward apply (GameSymbols.TowerBottomlessKnowledge.ManaPercentSettingRewardApply:
/// the reward logic's Apply(world hero), which sets the hero's Mana to a percent of max - Mana Well, Crystal Trail and
/// the Pandora mana variant all use it). For a hero with the Mana Well Aegis subskill it then removes every hero-map buff
/// whose live config is negative (isPositive=false) and dispellable (isDispellable=true), through the hero's native
/// buff manager Remove(sid) so the buff's bonuses are un-applied, and verifies each removal with Get(sid).
/// The previous binding (TowerBottomlessKnowledge.ManaRewardSetAppliers) is a UI event subscriber that opens the
/// reward-set flow, not the applier, and the previous cleanse edited only the Data buff list.
/// Static evidence (25672315) in tools/port_current/remap/current_scope_overrides_25672315.json; runtime unproven.
/// </summary>
internal static class Homm3TowerBottomlessKnowledgeHook
{
	private static bool _registered;
	private static ManualLogSource _log;
	private static IntPtr _rewardLogicClass;
	private static IntPtr _worldHeroClass;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffRemoveMethod;
	private static MethodInfo _buffGetMethod;
	private static PropertyInfo _logicBuffConfigProperty;
	private static PropertyInfo _configIsPositiveProperty;
	private static PropertyInfo _configIsDispellableProperty;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new ArgumentNullException(nameof(harmony));
		_log = log;

		// Resolve every surface before patching anything, so a miss leaves no partial feature behind.
		var rewardLogicType = GameMember.FindType(
			GameSymbols.TowerBottomlessKnowledge.ManaPercentSettingRewardLogicTypeId,
			GameSymbols.TowerBottomlessKnowledge.ManaPercentSettingRewardLogicTypeHint);
		if (rewardLogicType == null)
			throw new TypeLoadException("Tower Mana Well Aegis: missing ManaPercentSettingReward logic type (TowerBottomlessKnowledge.ManaPercentSettingRewardLogicTypeHint).");

		var methods = GameMember.FindMethodsByNames(
			rewardLogicType,
			1,
			GameSymbols.TowerBottomlessKnowledge.ManaPercentSettingRewardApply.Id,
			GameSymbols.TowerBottomlessKnowledge.ManaPercentSettingRewardApply.NameHints);
		if (methods.Length != 1 || methods[0].ReturnType != typeof(void) || methods[0].IsStatic
		    || !typeof(Il2CppObjectBase).IsAssignableFrom(methods[0].GetParameters()[0].ParameterType))
			throw new MissingMethodException(rewardLogicType.FullName, "ManaPercentSettingReward apply (TowerBottomlessKnowledge.ManaPercentSettingRewardApply): matched " + methods.Length);

		_buffManagerProperty = ResolveRequiredProperty(typeof(LogicHero), GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], "DungeonCaptives.LogicHeroBuffManagerMembers");
		var managerType = _buffManagerProperty.PropertyType;
		_buffRemoveMethod = ResolveRequiredMethod(managerType, typeof(void), GameSymbols.DungeonCaptives.BuffManagerRemove);
		_buffGetMethod = ResolveRequiredMethod(managerType, null, GameSymbols.DungeonCaptives.BuffManagerGet);
		if (!string.Equals(_buffGetMethod.ReturnType.FullName, "Hex.Session.Logic.Buff", StringComparison.Ordinal))
			throw new MissingMethodException("Tower Mana Well Aegis: buff manager Get returns " + _buffGetMethod.ReturnType.FullName + ", expected Hex.Session.Logic.Buff");
		_logicBuffConfigProperty = ResolveRequiredProperty(_buffGetMethod.ReturnType, GameSymbols.TowerBottomlessKnowledge.LogicBuffConfigMembers[0], "TowerBottomlessKnowledge.LogicBuffConfigMembers");
		var configType = _logicBuffConfigProperty.PropertyType;
		_configIsPositiveProperty = ResolveRequiredProperty(configType, GameSymbols.TowerBottomlessKnowledge.BuffConfigIsPositiveMember, "TowerBottomlessKnowledge.BuffConfigIsPositiveMember");
		_configIsDispellableProperty = ResolveRequiredProperty(configType, GameSymbols.TowerBottomlessKnowledge.BuffConfigIsDispellableMember, "TowerBottomlessKnowledge.BuffConfigIsDispellableMember");
		if (_configIsPositiveProperty.PropertyType != typeof(bool) || _configIsDispellableProperty.PropertyType != typeof(bool))
			throw new MissingMemberException(configType.FullName, "isPositive/isDispellable are not bool");

		// Guard the receiver and the world-hero argument by native class, so a folded caller is ignored, not dereferenced.
		_rewardLogicClass = Homm3CovePlunderHook.NativeClassOf(rewardLogicType);
		_worldHeroClass = Homm3CovePlunderHook.NativeClassOf(methods[0].GetParameters()[0].ParameterType);
		if (_rewardLogicClass == IntPtr.Zero || _worldHeroClass == IntPtr.Zero)
			throw new TypeLoadException("Tower Mana Well Aegis: native class pointers for the mana reward logic / world hero unresolved.");

		harmony.Patch(methods[0], postfix: new HarmonyMethod(typeof(Homm3TowerBottomlessKnowledgeHook), nameof(PostfixManaPercentSettingApplied)));

		_registered = true;
		log?.LogInfo("HoMM3 Tower Arcane Battery Mana Well Aegis cleanse slice registered on " + rewardLogicType.Name + "." + methods[0].Name
			+ " (ManaPercentSettingReward apply); removes negative dispellable hero buffs via buff manager "
			+ _buffRemoveMethod.Name + "/" + _buffGetMethod.Name + ". Runtime unproven.");
	}

	private static void PostfixManaPercentSettingApplied(object __instance, object __0)
	{
		try
		{
			if (!Homm3CovePlunderHook.IsNativeInstanceOf(__instance, _rewardLogicClass)
			    || !Homm3CovePlunderHook.IsNativeInstanceOf(__0, _worldHeroClass))
				return;

			var logicHero = ReadMember(__0, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty) as LogicHero;
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null || !HasManaWellAegis(dataHero))
				return;

			var manager = _buffManagerProperty.GetValue(logicHero);
			if (manager == null)
			{
				_log?.LogWarning("HoMM3 Tower Mana Well Aegis: hero " + dataHero.configSid + " has no buff manager; nothing cleansed.");
				return;
			}

			var removed = CleanseNegativeDispellableHeroMapBuffs(dataHero, manager);
			if (removed > 0)
				_log?.LogInfo("HoMM3 Tower Mana Well Aegis cleansed " + removed + " hero-map curse buff(s) from " + dataHero.configSid + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Tower Mana Well Aegis cleanse failed: " + ex);
		}
	}

	private static PropertyInfo ResolveRequiredProperty(Type type, string name, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var property = string.IsNullOrEmpty(name) ? null : type?.GetProperty(name, flags);
		if (property == null || property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
			throw new MissingMemberException("Tower Mana Well Aegis: " + symbolId + " property '" + name + "' not found on " + (type?.FullName ?? "null"));
		return property;
	}

	private static MethodInfo ResolveRequiredMethod(Type type, Type returnType, GameSymbols.MethodSymbol symbol)
	{
		// The name lookup is declared-only; on 26615913 Remove/Get live on the buff manager's abstract base.
		for (var owner = type; owner != null && owner != typeof(Il2CppObjectBase) && owner != typeof(object); owner = owner.BaseType)
		{
			var matches = GameMember.FindMethodsByNames(owner, new[] { typeof(string) }, symbol);
			MethodInfo found = null;
			foreach (var method in matches)
			{
				if (method.IsStatic || (returnType != null && method.ReturnType != returnType))
					continue;
				if (found != null)
					throw new AmbiguousMatchException("Tower Mana Well Aegis: " + symbol.Id + " matched more than one method on " + owner.FullName);
				found = method;
			}
			if (found != null)
				return found;
		}
		throw new MissingMethodException(type.FullName, symbol.Id + " (string)");
	}

	private static Hero ResolveDataHero(LogicHero logicHero)
	{
		if (logicHero == null)
			return null;
		return ReadMember(logicHero, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers) as Hero;
	}

	private static bool HasManaWellAegis(Hero dataHero)
	{
		var skills = ReadMember(dataHero, GameSymbols.TowerBottomlessKnowledge.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.TowerBottomlessKnowledge.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var subSkills = ReadMember(heroSkill, GameSymbols.TowerBottomlessKnowledge.HeroSkillSubSkillsMembers);
			foreach (var subSkill in EnumerateObjects(subSkills))
			{
				var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.TowerBottomlessKnowledge.HeroSubSkillSidMembers));
				if (string.Equals(sid, GameSymbols.TowerArcaneBattery.ManaWellAegisSubSkillSid, StringComparison.Ordinal))
					return true;
			}
		}

		return false;
	}

	/// <summary>
	/// Snapshots the hero's buff sids from the Data list (read only), then for each one asks the native buff manager
	/// for the live buff, keeps it only when its config is negative and dispellable, and removes it through the
	/// manager so the bonuses are un-applied. Each removal is verified with Get(sid) == null; failures are logged.
	/// </summary>
	private static int CleanseNegativeDispellableHeroMapBuffs(Hero dataHero, object manager)
	{
		var list = dataHero?.buffs?.list;
		if (list == null || list.Count == 0)
			return 0;

		var sids = new List<string>();
		for (var i = 0; i < list.Count; i++)
		{
			var buff = list[i];
			var sid = NormalizeSid(DeobfInteropCompat.GetStringMember(buff, GameSymbols.DungeonCaptives.DataBuffSidMembers));
			if (sid != null && !sids.Contains(sid))
				sids.Add(sid);
		}

		var removed = 0;
		foreach (var sid in sids)
		{
			try
			{
				var logicBuff = _buffGetMethod.Invoke(manager, new object[] { sid });
				var config = logicBuff == null ? null : _logicBuffConfigProperty.GetValue(logicBuff);
				if (config == null)
					continue;
				if ((bool)_configIsPositiveProperty.GetValue(config) || !(bool)_configIsDispellableProperty.GetValue(config))
					continue;

				_buffRemoveMethod.Invoke(manager, new object[] { sid });
				if (_buffGetMethod.Invoke(manager, new object[] { sid }) != null)
				{
					_log?.LogWarning("HoMM3 Tower Mana Well Aegis: remove of " + sid + " did not stick.");
					continue;
				}
				removed++;
				_log?.LogInfo("HoMM3 Tower Mana Well Aegis removed negative dispellable buff " + sid + ".");
			}
			catch (Exception ex)
			{
				_log?.LogWarning("HoMM3 Tower Mana Well Aegis: cleansing " + sid + " threw " + ex.GetBaseException().Message);
			}
		}

		return removed;
	}

	/// <summary>
	/// Data.Hero.skills.list (and HeroSkill.subSkills) are Il2CppSystem List&lt;T&gt;, which Il2CppInterop exposes as
	/// Il2CppSystem.Object rather than a managed IEnumerable, so a plain IEnumerable walk saw no skills and Mana Well
	/// Aegis never fired. Managed enumerables are still walked directly; anything else is read by Count + indexer.
	/// </summary>
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

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public;
		var type = value.GetType();
		int count;
		MethodInfo getItem;
		try
		{
			var countProp = type.GetProperty("Count", flags);
			if (countProp?.GetMethod == null || countProp.GetIndexParameters().Length != 0)
				yield break;
			getItem = type.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
			if (getItem == null)
				yield break;
			count = Convert.ToInt32(countProp.GetValue(value));
		}
		catch
		{
			yield break;
		}

		for (var i = 0; i < count; i++)
		{
			object item;
			try
			{
				item = getItem.Invoke(value, new object[] { i });
			}
			catch
			{
				yield break;
			}
			if (item != null)
				yield return item;
		}
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;

		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;

			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop?.GetMethod != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj);
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

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}
}
