# Campaign placed-hero stub × BeforeIamVsHero mismatch handoff

Date: 2026-08-01  
Workspace: `V:\Games\Olden Era Playtest Tweak`  
Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`

## Status (2026-08-01 follow-through)

**Source/static + generated artifact + installed payload (map readback) fixed.**  
`colocated_hero_dialog_avatar` now uses `resolve_placed_hero_sid` (same owner as propHero emit). Fail-closed gate: `tools/validate_campaign_before_iam_vs_hero_prop_contract.py` (wired into continuity `verify_installed`). Regenerated + installed `bashing_skulls` (crag) and `for_the_throne` (festival).

**Still open:** user-visible gameplay — step onto Gurnisson on `bashing_skulls` and confirm dialog before combat.

## Problem (user-visible)

On Hack and Slash scenario 1 (`bashing_skulls`), the opening Gurnisson / “Gurnis” conversation no longer fires. Combat starts with no dialog.

## Proven root cause (installed + generated artifact)

Colocated H3M EVENT+hero dialogs are delivered as QuestScript `BeforeIamVsHero` interruptions. Native OE matches `interruption.p[0]` against the fought hero’s `propHeroes.heroSid` (not the entity SID, not the portrait icon).

Pre-fix installed `bashing_skulls` map:

| Surface | Value |
|---|---|
| Interruption `bashing_skulls_map_event_1_before_hero`.p | `homm3_stronghold_hero_2` |
| Object 1652 `propHeroes.heroSid` | `h3_campaign_placed_gurnis` |

Those SIDs diverge → interruption never arms → no dialog.

Timeline from Story_maps backups:

- Through `…backup_20260730_221846`: both sides `homm3_stronghold_hero_2` (matched).
- From `…backup_20260731_205156` onward: propHero is the campaign stub; interrupt still targets the catalog SID.

## Why the generator produced the mismatch

1. H3M places hero type **97** with display name **`Gurnis`** (truncated; not `Gurnisson`).
2. `h3_campaign_placed_heroes.resolve_placed_hero_sid` treats any name that fails `h3_hero_name_to_hero_sid` as a **custom stub**:
   - `Gurnis` → `None` in the name table → stub `h3_campaign_placed_gurnis`
   - `Gurnisson` would have resolved to `homm3_stronghold_hero_2`
3. `campaign_runtime_script.colocated_hero_dialog_avatar` built `dialogHeroSid` from **hero type only** via `h3_hero_type_to_hero_sid(97)` → `homm3_stronghold_hero_2`.
4. Port manifests often omit `hasName` while still carrying the custom `name` string; emit recovered the name via campaign-chain `names_by_type`, but interrupt planning did not.
5. `build_colocated_hero_interruptions` copies that `dialogHeroSid` into `BeforeIamVsHero.p`.

So emit and interrupt planning used two different identity policies for the same placed hero.

Same class of bug on `for_the_throne`: interrupt targeted `homm3_rampart_hero_18` while the colocated hero was stubbed as `h3_campaign_placed_duke_boragus`.

Vanilla OE campaign maps (`c_M*`) also show `BeforeIamVsHero` SIDs with no matching `propHeroes` row in some branch maps; those are **native** maps, not our stub pipeline — do not “fix” them as part of this work.

## Fix applied

1. `colocated_hero_dialog_avatar` resolves interrupt SID via `resolve_placed_hero_sid(hero_type, name=…)`; portrait icon stays on catalog/donor type.
2. Name policy: non-empty `name` unless `hasName is False` (covers walk `hasName=true` and port-manifest omitted `hasName`).
3. Validator `tools/validate_campaign_before_iam_vs_hero_prop_contract.py`: every `BeforeIamVsHero.p[0]` ∈ map `propHeroes.heroSid` for HUB_CONFIGS artifacts (+ optional installed Story_maps). Also strengthened colocated checks in `validate_campaign_event_policy_contract.py`.
4. Continuity installer `verify_installed` runs the new validator.

## Validator / contract

```text
python tools/validate_campaign_before_iam_vs_hero_prop_contract.py --repo-root .
python tools/validate_campaign_before_iam_vs_hero_prop_contract.py --repo-root . --installed-story-maps
```

## Inventory

Pre-fix (installed Golden Era `Story_maps`, non-backup): **2** raw_translation mismatches (`bashing_skulls`, `for_the_throne`). Native `c_M*` mismatches excluded.

Post-fix installed readback: both interrupts use stub SIDs present in `propHeroes`. Validator PASS (artifacts + installed).

## Key files

| Role | Path |
|---|---|
| Stub SID policy | `experiments/campaign_port_poc/h3_campaign_placed_heroes.py` |
| propHero bind | `experiments/campaign_port_poc/approach_cell/surface_emit.py` |
| dialogHeroSid + interruptions | `experiments/campaign_port_poc/campaign_runtime_script.py` |
| Gate | `tools/validate_campaign_before_iam_vs_hero_prop_contract.py` |
| Payload grants | `experiments/campaign_port_poc/campaign_placed_hero_payloads.py` |

## Related dirty worktree (do not confuse)

Uncommitted `campaign_placed_hero_payloads.py` Spell Book–only `hasArtifactSet` fix is a **separate** issue. Path-scope commits; do not mix.

## Resume procedure (remaining)

1. Runtime proof: step onto Gurnisson on `bashing_skulls` and confirm dialog before combat.
2. Optionally path-scope commit: runtime script + validator + installer wire + unit tests + this handoff (exclude unrelated dirty files).

## Do not do

- Do not “fix” only Gurnisson with a one-off alias and leave other stubs broken.
- Do not retarget interruptions to entity SIDs — native contract is propHero SID.
- Do not edit vanilla `c_M*` maps as part of this handoff.
- Do not claim runtime dialog fixed until a live play proves it.

## Proof labels

- Root cause: **generated artifact validated** + **installed payload proven** (map readback).
- Fix + validator + regen/install: **installed payload proven** (interrupt `p` ∈ propHeroes).
- Dialog firing again: **user-visible gameplay proven** only after live exercise.
