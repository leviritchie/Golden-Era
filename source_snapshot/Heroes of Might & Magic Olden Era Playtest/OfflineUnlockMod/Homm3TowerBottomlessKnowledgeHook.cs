using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Data;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Mana Well Aegis subskill under Tower Arcane Battery.
/// After ManaPercentSettingReward applies, cleanses explicit negative dispellable
/// hero-map curse buffs for heroes that own the Arcane Battery Mana Well Aegis subskill.
/// </summary>
internal static class Homm3TowerBottomlessKnowledgeHook
{
	private const string ManaPercentSettingRewardType = "ManaPercentSettingReward";

	private static readonly HashSet<string> NegativeDispellableHeroMapBuffSids = new(StringComparer.Ordinal)
	{
		"cm_fun_necromancy_power_disabled",
	};

	private static bool _registered;
	private static ManualLogSource _log;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new ArgumentNullException(nameof(harmony));
		_log = log;

		var rewardApplierType = GameMember.FindType(
			GameSymbols.TowerBottomlessKnowledge.RewardApplierTypeId,
			GameSymbols.TowerBottomlessKnowledge.RewardApplierTypeHint);
		if (rewardApplierType == null)
			throw new TypeLoadException("Missing Tower Arcane Battery Mana Well Aegis reward applier type czy.");

		var methods = GameMember.FindMethodsByNames(
			rewardApplierType,
			new[] { typeof(LogicHero), typeof(DataRewardSet) },
			GameSymbols.TowerBottomlessKnowledge.ManaRewardSetAppliers);
		if (methods.Length == 0)
			throw new MissingMethodException("Missing exact Tower Arcane Battery Mana Well Aegis reward-set apply method on czy.");

		var postfix = new HarmonyMethod(typeof(Homm3TowerBottomlessKnowledgeHook), nameof(PostfixRewardSetApplied));
		foreach (var method in methods)
			harmony.Patch(method, postfix: postfix);

		_registered = true;
		log?.LogInfo("HoMM3 Tower Arcane Battery Mana Well Aegis cleanse slice registered on " + methods.Length + " reward-set method(s).");
	}

	private static void PostfixRewardSetApplied(LogicHero __0, DataRewardSet __1)
	{
		try
		{
			if (!ContainsManaPercentSettingReward(__1))
				return;

			var dataHero = ResolveDataHero(__0);
			if (dataHero == null || !HasManaWellAegis(dataHero))
				return;

			var removed = CleanseNegativeDispellableHeroMapBuffs(dataHero);
			if (removed > 0)
				_log?.LogInfo("HoMM3 Tower Mana Well Aegis cleansed " + removed + " hero-map curse buff(s).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Tower Mana Well Aegis cleanse failed: " + ex);
		}
	}

	private static bool ContainsManaPercentSettingReward(DataRewardSet rewardSet)
	{
		var rewards = rewardSet?.rewards;
		if (rewards == null)
			return false;

		for (var i = 0; i < rewards.Count; i++)
		{
			var reward = rewards[i];
			if (reward == null)
				continue;
			if (string.Equals(reward.stringRewardType, ManaPercentSettingRewardType, StringComparison.Ordinal))
				return true;
			if (string.Equals(reward.rewardType.ToString(), ManaPercentSettingRewardType, StringComparison.Ordinal))
				return true;
		}

		return false;
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

	private static int CleanseNegativeDispellableHeroMapBuffs(Hero dataHero)
	{
		var buffs = dataHero?.buffs;
		var list = buffs?.list;
		if (buffs == null || list == null || list.Count == 0)
			return 0;

		var removed = 0;
		for (var i = list.Count - 1; i >= 0; i--)
		{
			var buff = list[i];
			var sid = NormalizeSid(buff?.sid);
			if (sid == null || !NegativeDispellableHeroMapBuffSids.Contains(sid))
				continue;
			list.RemoveAt(i);
			removed++;
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
