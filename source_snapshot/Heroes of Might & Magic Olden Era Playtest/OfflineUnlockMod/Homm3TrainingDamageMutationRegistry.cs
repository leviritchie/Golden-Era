using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Generated source-prepared mutation design registry for TrainingDamage laws.
/// Source: custom_factions/training_damage_mutation_contracts.json.
/// Design classification only; runtime gameplay remains packet-gated.
/// Do not edit by hand; run tools/release_port/generate_training_damage_mutation_registry.py.
/// </summary>
internal static class Homm3TrainingDamageMutationRegistry
{
	private static readonly Dictionary<string, Entry> Entries = new(StringComparer.Ordinal)
	{
		["castle.damage-per-positive-morale"] = new Entry("damage-percent-scalar", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "positive morale value read proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus", "positive morale value" }, "none"),
		["conflux.family-stat-aspect"] = new Entry("damage-percent-scalar", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "exact elemental unit classifier proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus" }, "none"),
		["cove.gunpowder-defense-debuff"] = new Entry("target-vulnerability-mark", "target-custom-battle-state", "after-successful-cove-gunpowder-hit-before-damage-commit", new string[] { "final unit damage ordering proof", "exact Cove gunpowder dealer classification proof", "battle-local ash state idempotence proof", "safe committed-damage mutation point" }, new string[] { "DefenseDebuffPerHit as ash points", "BurningAshPercentPerPoint", "BurningAshMaxPercent" }, "battle-local native-pointer keyed target state cleared at battle cleanup; no native cleanup or status removal required"),
		["dungeon.isolated-target-damage"] = new Entry("damage-percent-scalar", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "isolated target geometry proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus" }, "none"),
		["fortress.debuffed-attacker-damage-reduction"] = new Entry("attacker-damage-reduction", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "dealer negative status query proof", "receiver Fortress law-owner proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus" }, "none"),
		["inferno.gated-entry-damage"] = new Entry("gated-entry-damage-scalar", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "gated unit identity proof", "permanent recruited unit exclusion proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus" }, "none"),
		["necropolis.temp-mana-per-corpse"] = new Entry("temporary-resource-credit", "hero-temporary-resource", "corpse-count-consumption-or-battle-result-phase", new string[] { "corpse count proof", "temporary mana mutation proof", "cleanup proof", "idempotence proof" }, new string[] { "TemporaryManaPerCorpse", "corpse count" }, "temporary mana cleanup required"),
		["rampart.avenger-vulnerability"] = new Entry("damage-percent-scalar", "outgoing-damage", "final-positive-damage-before-commit", new string[] { "final unit damage ordering proof", "custom Avenger marker SID state proof", "safe effect mutation point" }, new string[] { "DamagePercentBonus" }, "custom marker SID gates active duration; battle-local ConditionalWeakTable stores potency count only"),
		["stronghold.wounded-speed"] = new Entry("wounded-speed-buff", "friendly-stack-stat", "safe-round-or-turn-refresh", new string[] { "wounded threshold proof", "native speed stat mutation proof", "turn-order refresh proof", "cleanup proof" }, new string[] { "SpeedDelta" }, "battle cleanup or wounded-state refresh required"),
		["tower.spellcast-stacking-attack-defense"] = new Entry("stacking-temporary-stat-buff", "friendly-stack-stat", "after-successful-hero-spell-cast", new string[] { "spell cast event proof", "target construct/friendly stack identity proof", "native attack/defense stat mutation proof", "battle cleanup proof" }, new string[] { "rank" }, "round-or-battle cleanup required"),
	};

	internal readonly struct Entry
	{
		internal readonly string MutationKind;
		internal readonly string Direction;
		internal readonly string MutationPoint;
		internal readonly string[] RequiredRuntimeProof;
		internal readonly string[] NumericInputs;
		internal readonly string Cleanup;

		internal Entry(string mutationKind, string direction, string mutationPoint, string[] requiredRuntimeProof, string[] numericInputs, string cleanup)
		{
			MutationKind = mutationKind;
			Direction = direction;
			MutationPoint = mutationPoint;
			RequiredRuntimeProof = requiredRuntimeProof ?? Array.Empty<string>();
			NumericInputs = numericInputs ?? Array.Empty<string>();
			Cleanup = cleanup;
		}
	}

	internal static bool TryGet(string effectKey, out Entry entry)
	{
		entry = default;
		return !string.IsNullOrWhiteSpace(effectKey)
		       && Entries.TryGetValue(effectKey, out entry);
	}
}
