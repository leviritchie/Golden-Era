using System;
using System.Collections.Generic;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Shared fail-closed classifier boundary for no-compromise faction laws.
/// This helper may expose exact identity evidence that is already available in
/// the current native object graph, but it must not infer unit families from
/// donor identity, display names, visuals, icons, SID substrings, or faction-wide
/// assumptions. Until a native field or custom-owned family table is proven,
/// family facts remain "unknown".
/// </summary>
internal static class Homm3UnitLawClassifier
{
	private const string Unknown = "unknown";

	internal enum Fact
	{
		Unknown,
		Yes,
		No
	}

	internal enum FamilyFact
	{
		Gunpowder,
		Shooter,
		Melee,
		Construct,
		Elemental,
		Undead,
		Living,
		GatedOrSummoned,
		CorpseProducing
	}

	internal readonly struct Classification
	{
		internal readonly string IdentitySource;
		internal readonly string Sid;
		internal readonly string Faction;
		internal readonly string Tier;
		internal readonly Fact Gunpowder;
		internal readonly Fact Shooter;
		internal readonly Fact Melee;
		internal readonly Fact Construct;
		internal readonly Fact Elemental;
		internal readonly Fact Undead;
		internal readonly Fact Living;
		internal readonly Fact GatedOrSummoned;
		internal readonly Fact CorpseProducing;

		internal Classification(
			string identitySource,
			string sid,
			string faction,
			string tier,
			Fact gunpowder,
			Fact shooter,
			Fact melee,
			Fact construct,
			Fact elemental,
			Fact undead,
			Fact living,
			Fact gatedOrSummoned,
			Fact corpseProducing)
		{
			IdentitySource = identitySource;
			Sid = sid;
			Faction = faction;
			Tier = tier;
			Gunpowder = gunpowder;
			Shooter = shooter;
			Melee = melee;
			Construct = construct;
			Elemental = elemental;
			Undead = undead;
			Living = living;
			GatedOrSummoned = gatedOrSummoned;
			CorpseProducing = corpseProducing;
		}
	}

	internal static Classification Classify(object value)
	{
		if (value == null)
			return UnknownClassification("null");

		if (!TryResolveUnitConfig(value, out var config, out var source))
			return UnknownClassification("unresolved");

		var type = config.GetType();
		var sid = ReadUnitConfigSid(config, type);
		var faction = ReadShortMember(config, type, GameSymbols.BattleEventLaws.UnitConfigFactionMembers);
		var tier = ReadShortMember(config, type, GameSymbols.BattleEventLaws.UnitConfigTierMembers);
		if (Homm3UnitLawFamilyRegistry.TryGet(sid, out var registryEntry))
			return new Classification(
				source + "+custom-registry",
				sid,
				faction,
				tier,
				registryEntry.Gunpowder,
				registryEntry.Shooter,
				registryEntry.Melee,
				registryEntry.Construct,
				registryEntry.Elemental,
				registryEntry.Undead,
				registryEntry.Living,
				registryEntry.GatedOrSummoned,
				registryEntry.CorpseProducing);

		return new Classification(
			source,
			sid,
			faction,
			tier,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown);
	}

	internal static bool HasIdentity(Classification classification, out string failReason)
	{
		if (!string.IsNullOrEmpty(classification.Sid))
		{
			failReason = null;
			return true;
		}

		failReason = "unit-identity-unresolved";
		return false;
	}

	internal static bool RequireFact(Fact fact, string factName, out string failReason)
	{
		if (fact == Fact.Yes)
		{
			failReason = null;
			return true;
		}

		failReason = string.IsNullOrEmpty(factName)
			? "classifier-fact-" + FormatFact(fact)
			: factName + "=" + FormatFact(fact);
		return false;
	}

	internal static bool TryRequireFamilyFact(
		object value,
		FamilyFact familyFact,
		out Classification classification,
		out string failReason)
	{
		classification = Classify(value);
		if (!HasIdentity(classification, out failReason))
			return false;
		return RequireFact(GetFact(classification, familyFact), FormatFamilyFactName(familyFact), out failReason);
	}

	internal static string DescribeEvidence(object value)
	{
		var classification = Classify(value);

		var parts = new List<string>(16);
		parts.Add("identitySource=" + classification.IdentitySource);
		AddOptional("sid", classification.Sid, parts);
		AddOptional("faction", classification.Faction, parts);
		AddOptional("tier", classification.Tier, parts);

		AddFamilyBoundary(classification, parts);
		return "{" + string.Join(";", parts) + "}";
	}

	private static Classification UnknownClassification(string source)
	{
		return new Classification(
			source,
			null,
			null,
			null,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown,
			Fact.Unknown);
	}

	private static bool TryResolveUnitConfig(object value, out object config, out string source)
	{
		config = null;
		source = null;
		if (value == null)
			return false;

		var type = value.GetType();
		if (LooksLikeUnitConfig(value, type))
		{
			config = value;
			source = "direct";
			return true;
		}

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitLogicConfigMembers, out config) && config != null)
		{
			source = "logic";
			return true;
		}

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitViewConfigMembers, out config) && config != null)
		{
			source = "view";
			return true;
		}

		return false;
	}

	private static Fact GetFact(Classification classification, FamilyFact familyFact)
	{
		return familyFact switch
		{
			FamilyFact.Gunpowder => classification.Gunpowder,
			FamilyFact.Shooter => classification.Shooter,
			FamilyFact.Melee => classification.Melee,
			FamilyFact.Construct => classification.Construct,
			FamilyFact.Elemental => classification.Elemental,
			FamilyFact.Undead => classification.Undead,
			FamilyFact.Living => classification.Living,
			FamilyFact.GatedOrSummoned => classification.GatedOrSummoned,
			FamilyFact.CorpseProducing => classification.CorpseProducing,
			_ => Fact.Unknown,
		};
	}

	private static string FormatFamilyFactName(FamilyFact familyFact)
	{
		return familyFact switch
		{
			FamilyFact.Gunpowder => "gunpowder",
			FamilyFact.Shooter => "shooter",
			FamilyFact.Melee => "melee",
			FamilyFact.Construct => "construct",
			FamilyFact.Elemental => "elemental",
			FamilyFact.Undead => "undead",
			FamilyFact.Living => "living",
			FamilyFact.GatedOrSummoned => "gatedOrSummoned",
			FamilyFact.CorpseProducing => "corpseProducing",
			_ => "familyFact",
		};
	}

	private static bool LooksLikeUnitConfig(object value, Type type)
	{
		if (value == null || type == null)
			return false;
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitConfigSidMembers, out var sid) && sid != null)
			return true;
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitConfigFactionMembers, out var faction) && faction != null)
			return true;
		return TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitConfigTierMembers, out var tier) && tier != null;
	}

	private static string ReadUnitConfigSid(object config, Type type)
	{
		if (config == null)
			return null;
		// Field-backed ConfigElement id only. Do not call TryReadNativeStringMember /
		// get_baseSid here — both can fatal-crash via Il2CppStringToManaged on bad pointers.
		var elementId = DeobfInteropCompat.GetConfigElementId(config);
		if (!string.IsNullOrWhiteSpace(elementId))
			return elementId.Trim();
		return ReadShortMember(config, type, GameSymbols.BattleEventLaws.UnitConfigSidMembers);
	}

	private static string ReadShortMember(object value, Type type, string[] names)
	{
		return TryReadExactMember(value, type, names, out var raw) && raw != null ? FormatShortValue(raw) : null;
	}

	private static void AddOptional(string label, string value, List<string> parts)
	{
		if (!string.IsNullOrEmpty(value))
			parts.Add(label + "=" + value);
	}

	private static void AddFamilyBoundary(Classification classification, List<string> parts)
	{
		parts.Add("gunpowder=" + FormatFact(classification.Gunpowder));
		parts.Add("shooter=" + FormatFact(classification.Shooter));
		parts.Add("melee=" + FormatFact(classification.Melee));
		parts.Add("construct=" + FormatFact(classification.Construct));
		parts.Add("elemental=" + FormatFact(classification.Elemental));
		parts.Add("undead=" + FormatFact(classification.Undead));
		parts.Add("living=" + FormatFact(classification.Living));
		parts.Add("gatedOrSummoned=" + FormatFact(classification.GatedOrSummoned));
		parts.Add("corpseProducing=" + FormatFact(classification.CorpseProducing));
		parts.Add("familySource=" + FormatFamilySource(classification));
	}

	private static string FormatFamilySource(Classification classification)
	{
		return !string.IsNullOrEmpty(classification.IdentitySource)
		       && classification.IdentitySource.IndexOf("+custom-registry", StringComparison.Ordinal) >= 0
			? "custom-unit-registry"
			: "no-proven-family-source";
	}

	private static string FormatFact(Fact fact)
	{
		return fact == Fact.Yes ? "yes" : fact == Fact.No ? "no" : Unknown;
	}

	private static bool TryReadExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (value == null || type == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					raw = field.GetValue(value);
					if (raw != null)
						return true;
					continue;
				}
			}
			catch { }
			try
			{
				var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					// Skip managed string getters — Il2CppStringToManaged can AV on bad pointers.
					if (property.PropertyType == typeof(string))
						continue;
					raw = property.GetValue(value, null);
					if (raw != null)
						return true;
					continue;
				}
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
				{
					if (method.ReturnType == typeof(string))
						continue;
					raw = method.Invoke(value, null);
					if (raw != null)
						return true;
				}
			}
			catch { }
		}
		return false;
	}

	private static string FormatShortValue(object raw)
	{
		if (raw == null)
			return "null";
		var text = raw.ToString();
		if (string.IsNullOrEmpty(text))
			text = "(empty)";
		if (text.Length > 80)
			text = text.Substring(0, 80) + "...";
		return text;
	}
}
