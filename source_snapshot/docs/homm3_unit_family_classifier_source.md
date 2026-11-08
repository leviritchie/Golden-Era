# HoMM3 Unit Family Classifier Source

This document defines the hygiene boundary for unit-family facts used by no-compromise custom faction laws.

## Current state

- `custom_factions/unit_family_tags.json` exists as a template only.
- `Homm3UnitLawFamilyRegistry` is intentionally empty.
- `Homm3UnitLawClassifier` reports exact identity evidence when available, but all family facts currently remain `Fact.Unknown`.
- No gameplay law may consume unit-family facts yet.

## Why this exists

Many intended faction laws depend on family facts such as gunpowder, construct, elemental, undead, living, gated/summoned, corpse-producing, shooter, or melee. Those facts are design-critical and cannot be inferred from donor rows or visuals without compromising the law design.

## Accepted source path

The only acceptable custom-owned source path is:

1. Author exact custom unit SID entries in `custom_factions/unit_family_tags.json`.
2. Review each entry against design intent and generated Core output.
3. Prove in runtime diagnostics that the same custom SID reaches the hook context that will consume the fact.
4. Only then mirror the reviewed entries into `Homm3UnitLawFamilyRegistry` or a generated equivalent.

## Explicitly rejected sources

- Donor unit SID or donor faction.
- Custom unit SID substrings.
- Display names or law text.
- Icon keys, portraits, visual prefab paths, animation folders, or projectile tables.
- Law override unit SID arrays.
- Ability tags unless separately proven to be the native action classifier in the consuming hook context.
- Broad assumptions such as all Cove shooters being gunpowder or all Tower units being constructs.

## Required validation before gameplay

- Static validation: every SID in `custom_factions/unit_family_tags.json` must exist in generated custom unit Core rows.
- Static validation: every fact value must be `yes`, `no`, or `unknown`.
- Static validation: `tools/release_port/validate_unit_family_tags.py` must pass before authored entries may be reviewed for runtime use.
- Runtime validation: `classifierEvidence.sid` must match the expected custom SID in the same hook context that will consume the fact.
- Runtime validation: action-dependent facts such as shooter/melee must be proven from the action event, not only from unit identity.
- Runtime validation: summon/corpse facts must be proven from exact summon/lifetime or corpse-state surfaces.

Until those checks exist and pass, `Unknown` is the correct runtime answer.

## Validator behavior

`tools/release_port/validate_unit_family_tags.py` checks the template shape and any authored entries.

It verifies:

- `schemaVersion` is `1`.
- `units` is an object keyed by exact custom unit SID.
- Every authored SID exists in enabled custom faction manifests.
- Every fact key is one of the allowed classifier facts.
- Every fact value is `yes`, `no`, or `unknown`.
- Every authored unit entry states every fact explicitly, using `unknown` when unproven.

The current empty template is valid because it authorizes no runtime facts.

## Registry generation

`tools/release_port/generate_unit_family_registry.py` is the only approved way to update `Homm3UnitLawFamilyRegistry.cs` from authored JSON.

The generator:

- Runs the same static validation as `validate_unit_family_tags.py`.
- Refuses to emit C# if the tag file has validation errors.
- Generates exact SID dictionary entries only from `custom_factions/unit_family_tags.json`.
- Leaves the registry empty when the tag file has no unit entries.

Do not hand-edit `Homm3UnitLawFamilyRegistry.cs` with inferred facts.

## Registry drift check

`tools/release_port/check_unit_family_registry_drift.py` compares the checked-in registry against the generated output from `custom_factions/unit_family_tags.json`.

It verifies:

- The tag file passes static validation.
- The registry file exists.
- The registry file exactly matches generator output.

Use this check before treating registry contents as reviewed implementation input. Passing it still does not prove runtime classifier correctness or law readiness.

## Placeholder synchronization

`tools/release_port/sync_unit_family_tag_placeholders.py` can populate `custom_factions/unit_family_tags.json` with every enabled custom unit SID, setting every fact to `unknown`.

This is an authoring aid only.

- Placeholder entries are not proof of a family fact.
- Placeholder entries do not make gameplay law consumption safe.
- Replacing `unknown` with `yes` or `no` still requires source review and runtime proof.
- Use `--prune-stale` only when intentionally removing SIDs no longer present in enabled manifests.

## Runtime consumption rule

Future gameplay hooks must consume family facts through `Homm3UnitLawClassifier.Classify(...)` and must gate behavior with typed facts rather than diagnostic strings.

Required pattern:

- Call `Homm3UnitLawClassifier.HasIdentity(...)` before using unit-specific facts.
- Call `Homm3UnitLawClassifier.RequireFact(...)` before applying a family-dependent effect.
- Treat `Fact.Unknown` as fail-closed with a diagnostic reason, not as `false`.
- Treat `Fact.No` as fail-closed for that family-dependent effect.

Forbidden pattern:

- Do not parse `classifierEvidence={...}` strings.
- Do not branch on missing fields as if they were `false`.
- Do not replace `Unknown` with donor-derived assumptions or generic stat effects.
