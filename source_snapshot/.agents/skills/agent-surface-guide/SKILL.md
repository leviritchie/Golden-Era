---
name: agent-surface-guide
description: >-
  Navigate Olden Era / Golden Era engine and mod product surfaces (Heroic Strike,
  mage hero ability, unit ability overrides, damage/laws, specializations, buffs,
  faction laws, town scene, live probe, GameSymbols, HoMM3 skinned-mesh battle units).
  Use when implementing or changing abilities, specializations, laws, damage hooks,
  buffs, hero battle actions, custom towns, custom unit battle meshes, or before
  inventing a new Harmony/Direct State path. Prefer this over grepping
  AGENT_REFERENCE or guessing from HotA text.
---

# Agent Surface Guide

Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`.

**Canonical hub (read this):** `docs/agent_surface_guide.md`  
**Surface cards:** `docs/surfaces/*.md`  
**Battle/IL2CPP ownership companion:** `.agents/skills/decomp-search/SKILL.md`

This skill does not replace the hub. It forces the navigation ritual so agents do not skip cards, checklists, or proof labels.

## When to use

Any change that answers “what can I change, and where?” for shipped product behavior — especially:

- Heroic Strike / mage hero battle ability / separate hero actions (Warcry, Gating, …)
- Unit actives/passives / ability_overrides / Focus / CD
- Specialization bonus rows / hero_overrides
- Faction laws / damage scalars / hard-law CSV runtime
- Buffs / status DB tables
- Custom town / city world (owned scene paradigm)
- HoMM3 skinned-mesh battle units (not billboard)
- Live probe / OfficialDeobf compile gates
- Keyed Harmony lookups / plan maps / silent miss diagnosis

For push/teleport/occupancy/Direct State **ownership branching**, also open **decomp-search**.

## Non-negotiable rules

1. **Open the hub first** — do not start from `AGENT_REFERENCE.md`, knowledge-base, or `rag_chunks/` as truth.
2. **Match player intent → surface card** via the hub navigation table; read that card’s Intent → Ownership → Can/cannot → Pitfalls before editing.
3. **Run the card’s do-not-miss checklist** (and the hub family checklist for that area).
4. **Prefer native Core envelopes** over new Harmony or Direct State paths when a live donor exists.
5. **One solution, fail closed** — no silent fallbacks that hide misses.
6. **Proof labels** — do not promote `planned`/`registered`/`stored` to user-visible gameplay without evidence.
7. **Obfuscated names** stay in `GameSymbols.cs` (or established resolvers).
8. **Il2Cpp cache keys** — after types match, key by native pointer (`Homm3DirectStateIdentity`), not managed `GetHashCode` on separately marshaled proxies. Matching `nativeKey`s = same native object; distinct `nativeKey`s = different objects / wrong ownership key — pointer keying does not prove store/retrieve are the same instance.

## Required workflow

Copy and track:

```
Surface guide:
- [ ] 1. State the change in player/designer terms
- [ ] 2. Open docs/agent_surface_guide.md
- [ ] 3. Read Silent miss / wrong proof if wiring lookups, collections, or apply timing
- [ ] 4. Pick the navigation-table row → open the linked docs/surfaces/*.md card
- [ ] 5. Read Intent, Ownership preference, Touch points, Pitfalls, Open unknowns
- [ ] 6. Complete that family’s do-not-miss checklist in the hub
- [ ] 7. If native vs plugin vs Direct State still branches → decomp-search skill
- [ ] 8. Label every new claim with a proof tier; do not skip validators for the surface
```

### Quick intent → card map

| Intent | Card under `docs/surfaces/` |
| --- | --- |
| Heroic Strike / warrior commander attack | `heroic_strike_warrior_ability.md` |
| Mage hero battle ability | `mage_hero_battle_ability.md` |
| Extra hero action (Warcry, Gating, …) | `separate_hero_battle_actions.md` |
| Unit active/passive | `unit_ability_core_overrides.md` |
| Law / damage mutation | `damage_mutation_law_runtime.md` |
| Specialization bonuses | `specialization_bonus_row_types.md` |
| Buffs / statuses | `buffs_and_statuses.md` |
| Faction laws | `faction_laws.md` |
| Direct State index | `direct_state_index.md` |
| Custom town | `town_city_scene.md` |
| Live probe / build | `live_probe_and_build.md` |
| HoMM3 skinned-mesh battle unit | `custom_unit_skinned_mesh.md` |
| HoMM2 shade object class on Golden Era | `homm2_shade_object_class.md` |
| Pins / keyed lookups | `gamesymbols_obfuscation.md` |

### Heroic Strike reminder (easy to get wrong)

Stock warrior/mage hero abilities are `absolute_damage` with `ignoreCasterOffence` / `ignoreEnemyDefence`. Script sums offence + defence + SP + INT and applies `heroicStrikeDamagePerLevelBonus`. This is **not** classic creature Attack–Defense gap combat. Details: the heroic-strike surface card + installed `hero_ability.script`.

## Validation

Navigation integrity only (not gameplay proof):

```powershell
$env:PYTHONUTF8 = '1'
python tools/validate_agent_surface_guide_contract.py --repo-root .
```

Also covered by `tools/validate_documentation_contract.py`.

## Anti-patterns

- Grep-only implementation from archived docs without opening the matching surface card
- Changing LocKit / specialty **text** and calling the mechanic done
- Inventing a second damage/hook path when a Core donor or existing bonus row fits
- Treating CapLog / dual-readback / “planned” logs as user-visible proof
- Assuming `OfficialDeobf` is a separate play install
- Treating Route A town posters as the custom-town product path
- Inventing a second HoMM3 battle-visual path instead of the skinned-mesh lane card
- Equating DiffableCs `void(object, BattleEventArgs)` declaration index with live `Method_Public_Void_Object_BattleEventArgs_N` (buff `bcja` index 39 ≠ `Method_39`/`cfir`; correct got-buff raise is `cfin`/`Method_35`)

## Additional resources

- Hub: `docs/agent_surface_guide.md`
- Cards: `docs/surfaces/`
- Docs index: `docs/README.md`
- Decomp / DS ownership: [decomp-search](../decomp-search/SKILL.md)
