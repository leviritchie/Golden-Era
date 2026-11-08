# HoMM3 AI First-Pass Design Principles

Date: 2026-05-05

## Purpose

This note turns the Stronghold development decisions into reusable guidance for the remaining HoMM3 factions. It is meant for the first automated or AI-assisted content pass before human design review.

The goal is not to make final design calls automatically. The goal is to give the first pass defensible placeholder choices so human review starts from a coherent playable scaffold instead of raw donor clones.

## Stronghold-Derived Philosophy

Stronghold used a practical hierarchy:

1. Keep the game stable and playable.
2. Preserve recognizable HoMM3 faction identity where the Olden Era schema supports it.
3. Use Olden Era-native systems instead of forcing HoMM3 rules through unsafe hooks.
4. Make approximations explicit in data, text, and documentation.
5. Defer native-heavy behavior until it can be statically traced.

This same hierarchy should drive the other factions.

## Principle 1: Use Donors For Engine Compatibility, Not Lore Purity

Stronghold cloned Dungeon for faction/city/unit scaffolding even though Dungeon is not a lore match. That was acceptable because the donor supplied working UI, city, squads, hero tables, battle presentation shells, and map shell behavior.

First-pass rule:

- Choose the donor that best preserves engine behavior for the unit or faction surface.
- Prefer same-tier and same-role donors over visually similar donors.
- Use mixed donors when needed, especially for map shells, projectiles, and previews.
- Keep synthetic HoMM3 import keys under a private namespace so vanilla donor enemies do not accidentally match custom visual swaps.

Stronghold examples:

- `trogl` to `h3_goblin`, `assassin` to `h3_wolf_rider`, and so on gave a complete 7-tier unit shell.
- Wolf Riders used Undead `pet_map` map shells while still living in the Stronghold unit line, because the map shell family fit mounted quadruped placement better.
- HoMM3 unit mesh keys use `homm3_import/stronghold/...` instead of raw donor prefab paths.

First-pass output should record:

- chosen donor SID
- reason for donor choice
- confidence
- surfaces that still use donor behavior intentionally

## Principle 2: Prefer Data-Only Approximations Until Native Behavior Is Traced

Stronghold repeatedly chose safe data equivalents before custom runtime behavior.

First-pass rule:

- If the Core schema has a known field or bonus type, use it.
- If the mechanic needs an unknown native controller path, leave a documented placeholder.
- Do not add runtime hooks just because a HoMM3 rule is iconic.
- Do not write tooltip text that claims behavior the data does not actually implement.

Stronghold examples:

- Hall of Valhalla became an Olden Era hero Attack bonus building.
- Mess Hall uses `cityUnitsIncrement h3_goblin +8`.
- Resource Silo became +1 Crystal and +1 Ore daily through known resource bonus paths.
- Escape Tunnel, Freelancer's Guild, and Ballista Yard were explicitly left outside data-only scope.

First-pass default:

- Implement the closest safe data behavior.
- Put `manualReviewReason` on any iconic behavior that is missing or approximated.
- Use exact visible text for the implemented approximation, not for the unimplemented HoMM3 original.

## Principle 3: Preserve Faction Shape Before Exact Numbers

Stronghold did not flatten every low stat into the Olden Era average. It kept low-tier units fast/glassy and accepted lopsided roles where that matched HoMM3 identity, while flagging tiers 6-7 as under-statted relative to OE.

First-pass rule:

- Preserve the HoMM3 unit's role profile first: glassy, tanky, shooter, flyer, bruiser, caster, fast striker, attrition unit.
- Then scale into the Olden Era tier band.
- Use Horn of the Abyss balance as the source of truth for HoMM3 unit stats, costs, growth, and balance-sensitive mechanics. Fall back to vanilla Complete only when HotA has no entry.
- Do not buff every weak category just because a z-score is low.
- Do not use `squadValue` alone as the balance answer.
- Separate stat review from ability review.

Stronghold examples:

- Goblins stayed fast and fragile.
- Wolf Riders were already high on offence/speed, so extra ability parity would require caution.
- Cyclops and Behemoths were flagged for manual high-tier review because HoMM3 high tiers were structurally under-statted versus Olden Era.

First-pass default:

- Keep at least one visible strength and one visible weakness for most units.
- Use same-tier OE ranges as guardrails, not as mandatory averages.
- If adding a strong signature ability placeholder, reduce or avoid stat buffs in the same pass.
- Record the HotA stat source used for every unit row so later balance passes do not accidentally revert to vanilla values.

## Principle 4: Represent HoMM3 Identity With A Small Number Of Signature Hooks

Stronghold did not try to recreate every HoMM3 and Horn of the Abyss detail at once. It used a few recognizable unit/building/law/hero ideas and left harder behaviors for later.

First-pass rule:

- Pick one primary identity point per faction.
- Pick one or two signature unit mechanics per tier band, not every possible mechanic.
- Prefer mechanics that can be expressed through existing OE data.
- For alternate upgrades, choose a plausible role variant rather than forcing nonexistent HoMM3 content.
- Any Tears of Ashan alternate upgrade, or AI-invented placeholder alternate, must differ from the original upgraded unit by at least one passive or active ability. A pure stat shuffle is not enough.

Stronghold examples:

- Warcries became the faction hero identity.
- Hall of Valhalla, Mess Hall, and Resource Silo carried city identity.
- Goblin growth, Wolf Rider drills, Orc fletching, Ogre warbands, Roc aeries, Cyclops siegecraft, and Behemoth dominance became law themes.
- Alternate upgrades such as Goblin Trapper, Boar Rider, Orc Berserker, Thunderbird, Blood-Eyed Cyclops, and Ghost Behemoth were treated as plausible role variants rather than strict Restoration of Erathia rows.

First-pass default:

- Add a concise `identityPillars` list to each faction manifest.
- Every placeholder law/building/hero specialty should tie back to one of those pillars.
- If a proposed mechanic does not support a pillar, leave it for manual design.
- Add `upgradeDifferentiator` to every `_upg_alt` manifest row and fail generation if it is empty.

## Principle 4A: Convert Probability Effects Into Focus Abilities

HoMM3 and Tears of Ashan use many probability-based creature effects. Olden Era first-pass design should replace those with focus-point abilities so the player can plan around them and so implementation does not depend on hidden random rolls.

First-pass rule:

- If the source mechanic is chance-based, make it a focus-point active ability or a deterministic focus spender.
- Preserve the source effect's tactical role, target restrictions, and immunities where they are understood.
- Contact-flavored focus actions still need an explicit contact contract. If the ability is a bite, grasp, hook, charge, pounce, talon, slam, or breath-on-attack analogue, emit `attackType_="melee"` even when the payload is a copied buff/debuff spell effect; a plain `cast` row can target at range.
- Tune focus cost, cooldown, and effect magnitude instead of preserving the original percent chance.
- Do not describe a chance in the tooltip unless the implemented OE ability is actually random.
- If the source chance scales with stack size, translate that scaling into focus cost, damage cap, or target threshold.

Examples:

- Thunderbird lightning becomes a focus-cost Lightning Strike, not a chance on attack.
- Basilisk petrify becomes a focus-cost Petrifying Bite, not a random stun.
- Mighty Gorgon death stare becomes a focus-cost Death Stare or high-tier execute effect, not a percent roll.
- Sea Dog Accurate Shot becomes a focus-cost precision shot with a deterministic cap, not a hidden kill chance.
- Sea Serpent poison becomes a focus-cost poison bite with deterministic max-HP pressure, not a 30% roll.

First-pass default:

- Name the focus ability after the HoMM3 mechanic when possible.
- If the exact effect is native-heavy, still reserve the ability slot and mark the implementation `static_trace_required`.
- Keep passive identity separate from the focus spender; for example, a Haspid can have passive Revenge plus focus-cost Venomous Bite.

## Principle 5: Use Olden Era Economy Conventions, Then Layer HoMM3 Flavor

Stronghold used HoMM3 dwelling resource costs where reasonable, but kept Olden Era's alchemical dust ladder for upgrade levels. This made the faction feel HoMM3-inspired without breaking OE economy expectations.

First-pass rule:

- Use HoMM3 costs as flavor and relative ordering.
- Normalize into available OE resource IDs.
- Preserve OE upgrade-resource conventions unless there is a strong reason not to.
- Keep city graph prerequisites conservative and functional before pursuing exact HoMM3 build order.

Stronghold examples:

- Sulfur mapping was folded into an available OE resource path where needed.
- Upgrade dwellings kept the OE dust ladder: tier 1 to 7 uses 10, 20, 30, 40, 50, 75, 100.
- Tier 1 dwelling no longer required a defunct wall gate; tier 2 followed tier 1.
- Mage Guild was capped to level 3 to match Stronghold identity.

First-pass default:

- Generate costs from HoMM3 source values, then run a normalization pass into OE resources.
- Keep a visible `economyApproximation` note for every resource remap.
- Cap or disable buildings only when the source faction identity is clear.

## Principle 6: Clone Complete Gameplay Surfaces, Not Just Units

Stronghold only became usable after cloning and remapping the full set of dependent surfaces: squads, barracks, heroes, subclasses, map objects, quick-game tables, localization, city audio, M2/M10 presets, and info scripts.

First-pass rule:

- A faction scaffold is incomplete if it only has unit JSON.
- Generate every lookup tree that session startup, Custom Game, RMG, town UI, and battle UI can reach.
- If a row is still donor-backed, make that explicit rather than omitting it.

Stronghold examples:

- `DB/squads/squads_homm3_stronghold/**` was required because session code looks up `squads_{fraction}`.
- `DB/objects_logic/hires/barracks.json` needed faction-tier rows outside the city config.
- Info scripts needed cloned unit functions or the unit info panel could render blank.
- M2/M10 banlists and construction presets needed city-specific rows.

First-pass default:

- Treat missing dependent data as a scaffold failure, not as polish.
- Add a generated checklist covering Custom Game, hero picker, map object, town, recruitment, battle, preview, tooltip, and localization surfaces.

## Principle 7: Make Text Match The Placeholder, Not The Dream

Stronghold repeatedly corrected visible text and Lang args after donor cloning exposed wrong Dungeon descriptions or raw placeholders.

First-pass rule:

- Visible names and descriptions should describe implemented behavior.
- Non-English locales may receive English fallback text until proper localization exists.
- Every token with format placeholders must have matching Lang args rows.
- Do not rely on donor text for faction-specific buildings, laws, abilities, or hero specialties.

Stronghold examples:

- Hall of Valhalla, Mess Hall, and Resource Silo received explicit English overrides because Dungeon text would have described the wrong mechanics.
- Warcries and class labels received explicit Barbarian/Battle Mage text.
- `h3_ogre_moral_selfbuff_description` needed an explicit args override because the donor token had no matching args row.

First-pass default:

- Generate explicit English text for every custom law/building/ability/specialty.
- Generate TODO/fallback locale entries instead of leaving donor flavor visible.
- Run a placeholder/args audit after generation.

## Principle 8: Hero Design Should Translate Function, Not Names Alone

Stronghold cloned Dungeon heroes for stability, but then corrected class labels, portraits, specialties, starting skills/spells, and faction skill identity.

First-pass rule:

- Keep donor hero rows when they provide stable class/UI wiring.
- Replace class names with HoMM3 class names.
- Translate unsupported HoMM3 specialties into closest OE-native equivalents.
- Do not clone faction skills in a way that duplicates global sub-skill IDs.
- Starting armies must use custom unit SIDs unless a diagnostic mode intentionally keeps donor units.

Stronghold examples:

- Might and magic classes became Barbarian and Battle Mage.
- Gurnisson's war-machine identity became an OE Heroic Strike scaling path.
- A broken top-level `skill_faction_homm3_stronghold` clone was removed because duplicated sub-skill keys crashed session load.
- Hero portraits used HoMM3 icon keys while keeping donor mesh/mounts.

First-pass default:

- Generate hero specialty placeholders in three buckets: direct unit specialty, translated OE mechanic, or manual native-trace required.
- Put every unsupported specialty in one of those buckets; do not silently retain donor hero text.

## Principle 9: Town Art Is Visual Evidence, Not Building Behavior

Stronghold town layering proved that visual maps and gameplay building identity are separate systems.

First-pass rule:

- Fix building behavior in city JSON and building categories first.
- Use visual layer mapping only for art presentation.
- Do not swap localization names to hide wrong building SIDs.
- Do not move native building UI transforms just to create town click targets.
- Treat `positions.json` as manual review territory.

Stronghold examples:

- `building_layer_map.json` controls which constructed building shows which Stronghold sprite.
- Runtime visual layers set `raycastTarget=false`; they are not click targets.
- The unsafe root/rect remapping approach for native building views was rejected.
- Upgrade sprite placement needed footprint anchoring, not naive top-left reuse.

First-pass default:

- Generate a rough layer map and positions file.
- Mark every building layer as `placementReview: required`.
- Keep click/hover behavior on native building UI until a safe hit-only path is statically traced.

## Principle 10: Release Safety Beats Clever Generalization

Stronghold release work repeatedly broke when stale playtest hooks were generalized too broadly. The first pass for other factions should reuse statically mapped, narrow release surfaces and avoid broad probing.

First-pass rule:

- Add data-driven registries, not broad runtime reflection.
- Keep release-safe hooks narrow and fault-isolated.
- Do not share postfixes that reference playtest-only obfuscated types with release hooks.
- After Steam hotfixes, verify the static path before changing data.

Stronghold examples:

- The release Custom Game path went through GameHub lobby UI, not the older playtest picker.
- `SoFractions` aliasing was required for custom faction UI assets.
- Map-object release hooks had to avoid playtest-only `but` and generated `buv` accessors.
- Battle visual release fields had to be resolved by type because obfuscated names drifted.

First-pass default:

- Generate registry entries for custom factions, units, heroes, and icons.
- Do not generate new hook code unless a second faction proves a Stronghold assumption is leaking.
- Document any release surface as `staticTraceRequired` if the current hook is Stronghold-specific.

## First-Pass Decision Ladder

For every faction decision, choose the first applicable option:

1. Exact HoMM3 behavior is expressible with known OE data. Use it.
2. A close OE-native behavior exists and visible text can honestly describe it. Use the approximation.
3. A donor behavior is safe and acceptable as a temporary scaffold. Keep it and label it as donor-backed.
4. The behavior appears native-heavy or unknown. Leave it unimplemented, document the desired HoMM3 behavior, and mark static tracing required.
5. The behavior is cosmetic only. Generate a placeholder asset/map and mark visual review required.

Do not skip from option 4 to an untraced runtime hook.

## Manifest Fields For Placeholder Decisions

The first-pass manifest should store design intent alongside data:

```json
{
  "decisionStatus": "placeholder",
  "sourceBehavior": "HoMM3 Hall of Valhalla gives +1 Attack",
  "implementedBehavior": "Olden Era city building gives visiting hero +2 Attack",
  "rationale": "Uses known OE heroStat bonus path and follows Stronghold precedent.",
  "confidence": "medium",
  "manualReviewReason": "Confirm faction economy and bonus magnitude after playtest.",
  "staticTraceRequired": false
}
```

Suggested status values:

- `exact`
- `approximation`
- `donor_backed`
- `visual_placeholder`
- `manual_design_required`
- `static_trace_required`

Recommended ability fields:

- `sourceMechanic`
- `probabilityInSource`
- `focusTranslation`
- `focusCost`
- `cooldown`
- `upgradeDifferentiator`

## First-Pass Review Checklist

Before handing a generated faction to a human, the AI pass should report:

- donor faction, donor city, and per-unit donor SIDs
- unit role profile and intended strength/weakness per tier
- stats compared to same-tier OE bands
- HotA stat source used for each unit, or a reason HotA was unavailable
- signature mechanics implemented, approximated, or deferred
- probability mechanics converted to focus abilities
- `_upg_alt` units with at least one passive or active differentiator
- city buildings with implemented behavior and source inspiration
- laws and hero specialties with text matching actual behavior
- resource remaps and economy approximations
- town layers requiring manual placement
- release UI surfaces that are generic versus still Stronghold-specific
- known risks requiring static decompilation

## Hard Warnings

- Do not claim unsupported HoMM3 mechanics in UI text.
- Do not use runtime probes as a substitute for static tracing when a native path is unknown.
- Do not treat donor clone success as faction design completion.
- Do not solve building identity with localization or town art swaps.
- Do not create duplicate top-level faction skill clones that reuse existing global sub-skill IDs.
- Do not let custom import keys collide with vanilla donor prefab/resource paths.
- Do not commit broad hook generalization just to support one unreviewed placeholder.
- Do not keep probability-based HoMM3/ToA effects as hidden random passives in the first pass; translate them into focus-point abilities.
- Do not create `_upg_alt` units that differ only by stats.
- Do not use vanilla unit stats when HotA has a balance value for the same unit.

## Bottom Line

The first AI pass should make conservative, visible, reversible decisions. It should turn each HoMM3 faction into a playable Olden Era scaffold with clear design intent, honest text, and a list of manual/static-trace debts. Human intervention should then focus on the important 20-30%: mechanics fidelity, faction identity, town presentation, balance, and release validation.
