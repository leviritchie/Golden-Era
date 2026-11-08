# HoMM3 Scenario Converter Semantic Coverage

Status: source/static + generated-artifact + validator proven for Homecoming layered atlas semantic translators. Runtime gameplay remains unvalidated. No scenario deploy was performed.

## Decision

Scenario emission stays fail-closed. The converter will not write an Olden map when the substitution map contains a placeholder, an approximation, a blocked source object (`replacementSid is None` / `lossiness=blocked`), an unsupported native property family, a deferred non-start hero, or an out-of-envelope object.

`SAFE_LOSSINESS` is only `direct_or_family_substitution` and geometric `footprint_alignment`. `blocked` is not safe.

Homecoming layered atlas passes `require_complete_semantic_coverage` with zero deferred emission counters and zero blocked substitution signatures.

Interactable completeness is measured by the functional-point static accessibility contract (`homm3.olden_functional_points.v1`), not by geometric HoMM3 pathability-mismatch counts. Runtime click dispatch remains unvalidated.

## Implemented Translators

| Family | Contract |
|---|---|
| Non-start / enemy heroes | `placed_hero_to_hero_spawner` + `propHeroes` via `h3m_hero_sid` |
| Concrete / random monsters | `propRandomSquads` with flee/growth flags |
| Map events | marker SID + sides/computer flags + optional rewards (fail-closed without specs) |
| Random artifacts 65–69 | `random-item` + `propRandomItems` rarity |
| Random resources 76 | one-shot `homm3_random_resource_pickup` (not weekly `random-res`) |
| Flotsam 29 | one-shot `homm3_flotsam_pickup` |
| Whirlpools 111 | same-layer pairing + `portal_magic` |
| Two-way monoliths 45 | animation→`portal_1/2/3` + same-layer same-animation pairing |
| Towns | `propCities` owner/name/faction/building masks/garrison |
| Banks / rings / shrines / reveal / morale | `shady_den`, `fairy_ring`, `altar_of_magic_*`, `watchtower`, `fountain`, `quixs_path`, `knowledge_garden` |

## Corrected Contracts

- Surface roads map only code 1→1 and 2→2; other road values fail closed.
- Unmapped river codes fail instead of being erased.
- H3M static objects use an explicit classic-version positive allowlist.
- Good to Go.h3m RoE random-hero / hero-tail walk is complete (413/413).
- Normal plugin builds do not deploy scenario payloads; deploy remains opt-in.

## Proof Boundary

- Layered Homecoming batch generate: pass
- Semantic coverage gate: complete (`blockedSubstitutionCount=0`, deferred*=0)
- Layered atlas + campaign-batch regression + entity substitution + semantic coverage validators: pass
- Runtime pathfinder / water / underground gameplay: unvalidated
