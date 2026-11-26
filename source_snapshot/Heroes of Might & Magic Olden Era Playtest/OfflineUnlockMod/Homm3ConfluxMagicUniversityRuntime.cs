using System;
using System.Collections.Generic;
using System.Reflection;
using DataHero = Hex.Session.Data.Hero;
using DataHeroSkills = Hex.Session.Data.HeroSkills;
using LogicHero = Hex.Session.Logic.Hero;
using LogicHeroSkill = Hex.Session.Logic.HeroSkill;
using TownHero = OfflineUnlockMod.Homm3TownBuildingWindowKit.TownHero;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22: Conflux Magic University (HoMM3: learn Air/Earth/Fire/Water Magic for 2000 gold). Olden Era
/// has four magic schools, so a hero in town may learn Daylight, Nightshade, Arcane or Primal Magic (skill_magic_day /
/// _night / _space / _primal) for 2500 Gold each, the map University's rewardCost. A hero holds at most 8 skills
/// (Logic.HeroSkills.maxAmount).
/// The skill is added through the logic HeroSkills component (Logic.Hero -> HeroSkills), whose Add(string) creates the
/// data skill, activates its bonuses and fires onHeroLearnedSkill, exactly like a level-up pick. Interop exposes
/// HeroSkills.BySid and HeroSkills.Add as two obfuscated public (string) -> Logic.HeroSkill methods; they are told apart
/// safely by calling both with a skill the hero already has: BySid returns it, Add returns null and changes nothing
/// (it checks skillsDict first). Learning is instant, so there is no daily/weekly state to persist.
/// </summary>
internal static class Homm3ConfluxMagicUniversityRuntime
{
	internal const string FactionSid = "homm3_conflux";
	internal const string BuildingSid = "Build_Magic_University";
	internal const int GoldCost = 2500;
	internal const int MaxSkills = 8;

	internal static readonly (string Sid, string Name)[] Schools =
	{
		("skill_magic_day", "Daylight Magic"),
		("skill_magic_night", "Nightshade Magic"),
		("skill_magic_space", "Arcane Magic"),
		("skill_magic_primal", "Primal Magic"),
	};

	/// <summary>Skill sids the hero holds (data side).</summary>
	internal static HashSet<string> Skills(DataHero hero)
	{
		var set = new HashSet<string>(StringComparer.Ordinal);
		if (hero == null)
			return set;
		var skills = Homm3TowerArtificingRuntime.ReadMember(hero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var list = Homm3TowerArtificingRuntime.ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in Homm3FactoryLogisticsEffects.Enumerate(list))
		{
			var sid = (Homm3TowerArtificingRuntime.ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string)?.Trim();
			if (!string.IsNullOrEmpty(sid))
				set.Add(sid);
		}
		return set;
	}

	/// <summary>Why <paramref name="hero"/> cannot learn <paramref name="sid"/> now, or null when it can.</summary>
	internal static string Blocked(TownHero hero, int side, string sid)
	{
		if (hero == null)
			return "No hero in town";
		var skills = Skills(hero.Data);
		if (skills.Contains(sid))
			return "Already known";
		if (skills.Count >= MaxSkills)
			return "This hero already has " + MaxSkills + " skills";
		if (!Homm3FactoryLogisticsEffects.TryReadResource(side, "gold", out var gold) || gold < GoldCost)
			return "Not enough gold";
		if (hero.Logic == null)
			return "Hero not ready yet (end the turn once or move the hero)";
		return null;
	}

	internal static bool Learn(TownHero hero, int side, string sid, string name, out string result)
	{
		var blocked = Blocked(hero, side, sid);
		if (blocked != null)
		{
			result = name + ": " + blocked + ".";
			return false;
		}
		if (!TryResolveAdd(hero.Logic, hero.Data, out var component, out var add, out var fail))
		{
			result = name + " cannot be taught: " + fail;
			Homm3TownBuildingWindowKit.LogWarning("Magic University: " + fail);
			return false;
		}
		var cost = new Dictionary<string, int>(StringComparer.Ordinal) { ["gold"] = GoldCost };
		if (!Homm3FactoryLogisticsEffects.TryCharge(side, cost, out fail))
		{
			result = name + ": " + fail + ".";
			return false;
		}
		try
		{
			var learned = add.Invoke(component, new object[] { sid });
			if (learned == null || !Skills(hero.Data).Contains(sid))
				throw new InvalidOperationException("the skill was not added");
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsEffects.TryAddResource(side, "gold", GoldCost, out _);
			result = name + " could not be learned (" + ex.GetBaseException().Message + "); gold refunded.";
			Homm3TownBuildingWindowKit.LogWarning("Magic University: " + result);
			return false;
		}
		result = hero.Name + " learned " + name + " for " + GoldCost.ToString("N0", System.Globalization.CultureInfo.InvariantCulture) + " gold.";
		Homm3TownBuildingWindowKit.LogInfo("Magic University: " + result);
		return true;
	}

	// ---------------------------------------------------------------- logic HeroSkills.Add resolution

	private static PropertyInfo _componentProperty;
	private static MethodInfo _add;
	private static string _resolveFail;

	private static bool TryResolveAdd(LogicHero logicHero, DataHero dataHero, out object component, out MethodInfo add, out string fail)
	{
		component = null;
		add = null;
		fail = null;
		try
		{
			if (_componentProperty == null && !ResolveComponentProperty(out fail))
				return false;
			component = _componentProperty.GetValue(logicHero);
			if (component == null)
			{
				fail = "the hero's skill list is unreadable";
				return false;
			}
			if (_add != null)
			{
				add = _add;
				return true;
			}
			if (_resolveFail != null)
			{
				fail = _resolveFail;
				return false;
			}
			var candidates = new List<MethodInfo>();
			foreach (var m in _componentProperty.PropertyType.GetMethods(BindingFlags.Instance | BindingFlags.Public))
			{
				if (m.ReturnType != typeof(LogicHeroSkill) || m.Name.Contains("_PDM_") || m.IsGenericMethod)
					continue;
				var ps = m.GetParameters();
				if (ps.Length == 1 && ps[0].ParameterType == typeof(string))
					candidates.Add(m);
			}
			if (candidates.Count != 2)
			{
				_resolveFail = fail = "expected 2 skill lookup/add calls on " + _componentProperty.PropertyType.Name + ", found " + candidates.Count;
				return false;
			}
			string owned = null;
			foreach (var s in Skills(dataHero))
			{
				owned = s;
				break;
			}
			if (owned == null)
			{
				// Not cached: another hero with a skill may resolve it later.
				fail = "the hero has no skill to identify the learn call with";
				return false;
			}
			var r0 = candidates[0].Invoke(component, new object[] { owned });
			var r1 = candidates[1].Invoke(component, new object[] { owned });
			if ((r0 == null) == (r1 == null))
			{
				_resolveFail = fail = "skill lookup/add calls are ambiguous (" + candidates[0].Name + ", " + candidates[1].Name + ")";
				return false;
			}
			_add = r0 == null ? candidates[0] : candidates[1];
			Homm3TownBuildingWindowKit.LogInfo("Magic University: learn call " + _componentProperty.PropertyType.Name + "." + _add.Name
				+ " (lookup " + (r0 == null ? candidates[1].Name : candidates[0].Name) + ").");
			add = _add;
			return true;
		}
		catch (Exception ex)
		{
			fail = "learn call failed to resolve: " + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>Logic.Hero's skills component: the property whose type holds a Data.HeroSkills and a Logic.Hero.</summary>
	private static bool ResolveComponentProperty(out string fail)
	{
		const BindingFlags inst = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		PropertyInfo match = null;
		foreach (var p in typeof(LogicHero).GetProperties(inst))
		{
			if (p.GetIndexParameters().Length != 0 || p.PropertyType.IsValueType)
				continue;
			var hasData = false;
			var hasHero = false;
			foreach (var q in p.PropertyType.GetProperties(inst))
			{
				hasData |= q.PropertyType == typeof(DataHeroSkills);
				hasHero |= q.PropertyType == typeof(LogicHero);
			}
			if (!hasData || !hasHero)
				continue;
			// Interop wraps one member twice (backing field and prop_); prefer prop_.
			if (match != null && match.PropertyType != p.PropertyType)
			{
				fail = "two hero skill components: " + match.Name + ", " + p.Name;
				return false;
			}
			if (match == null || !p.Name.EndsWith("k__BackingField", StringComparison.Ordinal))
				match = p;
		}
		if (match == null)
		{
			fail = "the hero skill component was not found on Logic.Hero";
			return false;
		}
		_componentProperty = match;
		fail = null;
		return true;
	}
}
