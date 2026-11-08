using System;
using System.Collections.Generic;
using System.Globalization;

namespace OfflineUnlockMod;

/// <summary>
/// Runtime evidence counters for candidate custom-law surfaces.
/// Validation status: source-prepared. This records already-emitted runtime
/// diagnostics in structured form so bridge pilots can prove or falsify
/// surfaces without relying on ambiguous log scraping.
/// </summary>
internal static class Homm3CandidateSurfaceRuntimeCounters
{
	private static readonly object LockObject = new();
	private static readonly Dictionary<string, Counter> Counters = new(StringComparer.Ordinal);

	internal static void Record(string message)
	{
		if (string.IsNullOrWhiteSpace(message))
			return;
		var key = Classify(message);
		var kind = ClassifyKind(message);
		lock (LockObject)
		{
			if (!Counters.TryGetValue(key, out var counter))
				counter = new Counter();
			counter.Observed++;
			if (string.Equals(kind, "applied", StringComparison.Ordinal))
				counter.Applied++;
			else if (string.Equals(kind, "failed", StringComparison.Ordinal))
				counter.Failed++;
			else
				counter.Skipped++;
			counter.LastKind = kind;
			counter.LastMessage = message.Length > 320 ? message.Substring(0, 320) : message;
			Counters[key] = counter;
		}
	}

	internal static string SnapshotJson()
	{
		lock (LockObject)
		{
			var keys = new List<string>(Counters.Keys);
			keys.Sort(StringComparer.Ordinal);
			var items = new List<string>(keys.Count);
			foreach (var key in keys)
			{
				var counter = Counters[key];
				items.Add("\"" + EscapeJson(key) + "\":{"
				          + "\"observed\":" + counter.Observed.ToString(CultureInfo.InvariantCulture)
				          + ",\"applied\":" + counter.Applied.ToString(CultureInfo.InvariantCulture)
				          + ",\"failed\":" + counter.Failed.ToString(CultureInfo.InvariantCulture)
				          + ",\"skipped\":" + counter.Skipped.ToString(CultureInfo.InvariantCulture)
				          + ",\"lastKind\":\"" + EscapeJson(counter.LastKind) + "\""
				          + ",\"lastMessage\":\"" + EscapeJson(counter.LastMessage) + "\""
				          + "}");
			}
			return "{" + string.Join(",", items) + "}";
		}
	}

	private static string ClassifyKind(string message)
	{
		if (Contains(message, "failed closed") || Contains(message, " failed:") || Contains(message, " reason="))
			return "failed";
		if (Contains(message, " applied ") || Contains(message, " armed ") || Contains(message, " consumed ") || Contains(message, " synchronized "))
			return "applied";
		return "skipped";
	}

	private static string Classify(string message)
	{
		if (Contains(message, "counterattack doctrine mutation") || Contains(message, "counterattack correlation diagnostic")) return "counterattack.doctrine";
		if (Contains(message, "battle unit law-owner registry hit")) return "battle.owner-registry";
		if (Contains(message, "battle-event law diagnostic")) return "battle-action.diagnostic";
		if (Contains(message, "training-damage runtime skipped")) return "damage.training";
		if (Contains(message, "training-damage runtime Fortress receiver reduction")) return "damage.fortress-receiver-reduction";
		if (Contains(message, "damage.training=allowed")) return "damage.training";
		if (Contains(message, "battle.melee-formation=allowed")) return "battle-action.melee-formation";
		if (Contains(message, "battle.ranged-formation=allowed")) return "battle-action.ranged-formation";
		if (Contains(message, "morale-trigger law diagnostic")) return "morale.trigger";
		if (Contains(message, "morale.package=denied") || Contains(message, "morale.trigger=denied")) return "morale.owner-resolution";
		if (Contains(message, "Cove Burning Ash")) return "damage.cove-burning-ash";
		if (Contains(message, "Cove Storm Charts") || Contains(message, "Cove Gun Decks") || Contains(message, "cove.focus.on-counterattack")) return "focus.cove";
		if (Contains(message, "Cove morale defense")) return "damage.cove-morale-defense";
		if (Contains(message, "Cove Boarding Parties")) return "damage.cove-boarding-protection";
		if (Contains(message, "Rampart Avenger ranged protection")) return "damage.rampart-avenger-ranged-protection";
		if (Contains(message, "Rampart Avenger's Reprisal") || Contains(message, "rampart.avenger-marked-counterattack-damage")) return "counterattack.rampart-avenger-reprisal";
		if (Contains(message, "Rampart Avenger marker") || Contains(message, "customAvengerMark") || Contains(message, "Avenger marker sync")) return "avenger.marker-sync";
		if (Contains(message, "Dungeon debuffed-target ranged damage")) return "damage.dungeon-debuffed-ranged";
		if (Contains(message, "Dungeon Outnumber") || Contains(message, "dungeon.damage-vs-smaller-stack")) return "counterattack.dungeon-outnumber";
		if (Contains(message, "Stronghold Berserker Charge Haste")) return "buff.stronghold-berserker-haste";
		if (Contains(message, "Stronghold post-attack")) return "damage.stronghold-post-attack";
		if (Contains(message, "Stronghold Blood Feud") || Contains(message, "Blood Feud")) return "counterattack.stronghold-blood-feud";
		if (Contains(message, "Conflux Elemental Backlash") || Contains(message, "conflux.extra-magic-damage-counterattack")) return "counterattack.conflux-backlash";
		if (Contains(message, "Necropolis Death Grip") || Contains(message, "necropolis.counterattack-drain-restore")) return "counterattack.necropolis-death-grip";
		if (Contains(message, "Fortress Thorned Hides") || Contains(message, "fortress.attack-debuff-on-counterattack")) return "counterattack.fortress-thorned-hides";
		if (Contains(message, "battle-action one-shot")) return "battle-action.one-shot-damage";
		if (Contains(message, "morale one-shot") || Contains(message, "morale-trigger law runtime")) return "morale.trigger";
		if (Contains(message, "Tower spellcast battle-local damage")) return "spell.tower-spellcast-damage";
		if (Contains(message, "Tower tier-1 no-cooldown")) return "spell.tower-tier-one-no-cooldown";
		if (Contains(message, "Fortress Bog Hex cooldown")) return "spell.fortress-bog-hex";
		if (Contains(message, "spell-cooldown profile credit")) return "spell.cooldown-credit";
		if (Contains(message, "Prize Shares") || Contains(message, "Subjugated Mines") || Contains(message, "Marsh Rights") || Contains(message, "Preservation Tithe") || Contains(message, "Transmutation Ledger") || Contains(message, "Elemental Market") || Contains(message, "Soul Contract") || Contains(message, "Mortuary Accounting") || Contains(message, "Spoils Ledger")) return "economy.squadvalue-gold";
		if (Contains(message, "Corpse Wisdom")) return "economy.necropolis-corpse-wisdom-mana";
		if (Contains(message, "Corpse Fuel")) return "economy.necropolis-corpse-fuel-mana";
		if (Contains(message, "custom law visual marker")) return "visual-marker";
		return "unknown";
	}

	private static bool Contains(string message, string needle)
	{
		return message?.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static string EscapeJson(string value)
	{
		return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}

	private struct Counter
	{
		internal int Observed;
		internal int Applied;
		internal int Failed;
		internal int Skipped;
		internal string LastKind;
		internal string LastMessage;
	}
}

