using System;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact read-only adapter for native battle spell identity.
/// Decomp evidence: eew exposes cnyy/bdma as spell SID and cnyz/bdmb as
/// MagicConfig; MagicConfig carries bxti / backing field / school_ for school.
/// This class does not mutate spellbook, cast-gate, cooldown, or UI state.
/// </summary>
internal static class Homm3SpellIdentityNativeAdapter
{
	internal readonly struct SpellIdentityInfo
	{
		internal readonly string Sid;
		internal readonly object MagicConfig;
		internal readonly string MagicConfigSid;
		internal readonly object School;
		internal readonly string SchoolName;
		internal readonly int Rank;

		internal SpellIdentityInfo(string sid, object magicConfig, string magicConfigSid, object school, string schoolName, int rank)
		{
			Sid = sid;
			MagicConfig = magicConfig;
			MagicConfigSid = magicConfigSid;
			School = school;
			SchoolName = schoolName;
			Rank = rank;
		}

		public override string ToString()
		{
			return "sid=" + (Sid ?? "null")
			       + " magicConfigSid=" + (MagicConfigSid ?? "null")
			       + " school=" + (SchoolName ?? "null")
			       + " rank=" + Rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
			       + " magicConfig=" + DescribeObject(MagicConfig);
		}
	}

	private static Type _battleSpellLogicType;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryRequireSpellSid(
		object battleSpell,
		string requiredSid,
		out SpellIdentityInfo info,
		out string failReason)
	{
		if (!TryReadSpellIdentity(battleSpell, out info, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(requiredSid))
		{
			failReason = "required spell SID is empty";
			return false;
		}
		if (string.Equals(info.Sid, requiredSid, StringComparison.Ordinal)
		    || string.Equals(info.MagicConfigSid, requiredSid, StringComparison.Ordinal))
			return true;
		failReason = "spell SID mismatch: expected " + requiredSid + " actual " + (info.Sid ?? "null");
		return false;
	}

	internal static bool TryRequireAnySpellSid(
		object battleSpell,
		string[] requiredSids,
		out SpellIdentityInfo info,
		out string failReason)
	{
		info = default;
		if (requiredSids == null || requiredSids.Length == 0)
		{
			failReason = "required spell SID list is empty";
			return false;
		}

		string firstFailure = null;
		for (var i = 0; i < requiredSids.Length; i++)
		{
			if (TryRequireSpellSid(battleSpell, requiredSids[i], out info, out failReason))
				return true;
			firstFailure ??= failReason;
		}

		failReason = firstFailure ?? "no required spell SID matched";
		return false;
	}

	internal static bool TryRequireSchool(
		object battleSpell,
		string requiredSchoolName,
		out SpellIdentityInfo info,
		out string failReason)
	{
		if (!TryReadSpellIdentity(battleSpell, out info, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(requiredSchoolName))
		{
			failReason = "required spell school is empty";
			return false;
		}
		if (string.IsNullOrWhiteSpace(info.SchoolName))
		{
			failReason = "spell school is unresolved for spell " + (info.Sid ?? "null");
			return false;
		}
		if (string.Equals(info.SchoolName, requiredSchoolName, StringComparison.OrdinalIgnoreCase))
			return true;
		failReason = "spell school mismatch: expected " + requiredSchoolName + " actual " + info.SchoolName;
		return false;
	}

	internal static bool TryReadSpellIdentity(object battleSpell, out SpellIdentityInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateBattleSpell(battleSpell, out failReason))
			return false;

		var type = battleSpell.GetType();
		var sid = ReadStringMember(battleSpell, type, GameSymbols.SpellCooldownLaws.BattleSpellSidMembers);
		if (string.IsNullOrWhiteSpace(sid))
		{
			failReason = "battle spell SID was not resolved from exact members";
			return false;
		}

		var magicConfig = ReadFirstExactMember(battleSpell, type, GameSymbols.SpellCooldownLaws.BattleSpellMagicConfigMembers);
		if (magicConfig == null)
		{
			failReason = "battle spell MagicConfig was not resolved from exact members";
			return false;
		}

		var magicConfigType = magicConfig.GetType();
		var magicConfigSid = ReadStringMember(magicConfig, magicConfigType, GameSymbols.SpellCooldownLaws.MagicConfigSidMembers);
		var school = ReadFirstExactMember(magicConfig, magicConfigType, GameSymbols.SpellCooldownLaws.MagicConfigSchoolMembers);
		if (school == null)
		{
			failReason = "MagicConfig school was not resolved from exact members";
			return false;
		}
		if (!TryReadIntMember(magicConfig, magicConfigType, GameSymbols.SpellCooldownLaws.MagicConfigRankMembers, out var rank))
		{
			failReason = "MagicConfig rank was not resolved from exact members";
			return false;
		}

		info = new SpellIdentityInfo(sid, magicConfig, magicConfigSid, school, FormatShortValue(school), rank);
		failReason = null;
		return true;
	}

	internal static bool TryDescribeSpellIdentitySurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"battleSpellLogicType=" + DescribeType(_battleSpellLogicType)
			+ " sidMembers=[" + string.Join(",", GameSymbols.SpellCooldownLaws.BattleSpellSidMembers) + "]"
			+ " magicConfigMembers=[" + string.Join(",", GameSymbols.SpellCooldownLaws.BattleSpellMagicConfigMembers) + "]"
			+ " schoolMembers=[" + string.Join(",", GameSymbols.SpellCooldownLaws.MagicConfigSchoolMembers) + "]";
		failReason = null;
		return true;
	}

	private static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		_battleSpellLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellLogic);
		if (_battleSpellLogicType == null)
			return FailResolve("battle spell logic type was not found", out failReason);

		failReason = null;
		return true;
	}

	private static bool ValidateBattleSpell(object battleSpell, out string failReason)
	{
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (_battleSpellLogicType == null)
		{
			failReason = "battle spell logic type is unresolved";
			return false;
		}
		if (!_battleSpellLogicType.IsInstanceOfType(battleSpell))
		{
			failReason = "object is not a resolved battle spell logic instance";
			return false;
		}
		failReason = null;
		return true;
	}

	private static object ReadFirstExactMember(object value, Type type, string[] names)
	{
		if (value == null || type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
						return field.GetValue(value);
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
						return property.GetValue(value, null);
				}
				catch
				{
				}
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
						return method.Invoke(value, null);
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static bool TryReadIntMember(object value, Type type, string[] names, out int intValue)
	{
		intValue = 0;
		var raw = ReadFirstExactMember(value, type, names);
		if (raw == null)
			return false;
		try
		{
			intValue = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}
	private static string ReadStringMember(object value, Type type, string[] names)
	{
		var raw = ReadFirstExactMember(value, type, names);
		return raw as string;
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string FormatShortValue(object value)
	{
		if (value == null)
			return null;
		var text = value.ToString();
		if (string.IsNullOrEmpty(text))
			return null;
		return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
	}
}
