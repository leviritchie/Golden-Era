# Custom unit Focus generation

Owner: `normalize_custom_unit_focus_generation` in [`apply_release_core_overlay.py`](../tools/release_port/apply_release_core_overlay.py).
Gate: [`validate_custom_unit_focus_generation_contract.py`](../tools/validate_custom_unit_focus_generation_contract.py), full build tier (one Core.zip read, about 2 s).

## Vanilla rule

These values come from reading the installed Core on 2026-11-19 (155 vanilla `units_logics` rows):

| Unit | `energyPerCast` (Focus per action) | `energyPerTakeDamage` | `energyPerRound` |
|---|---|---|---|
| Contact melee (`defaultAttacks` has only `melee`) | 2 | 1 | 0 |
| Ranged (`shoot`) or reach (`range`: Trick Demon, Druid, Graverobber, Cultist, Vampire alt) | 1 | 1 | 0 |

Melee earns more because it takes the risk of fighting adjacent. Every vanilla deviation has a card that says so:

- `inquisitor_upg`: 2 Focus when hit.
- `succubus_upg`: 3 Focus per action.
- `qilin_upg_alt`: 2 Focus per round.
- `gnat` is the one uncarded oddity: a melee unit at 1.

## Custom rule

All `h3_*` logic rows follow the vanilla rule. The pass runs after every unit producer, which includes the faction rows, the neutrals and the Conflux fused-row rebuild (`finalize_conflux_fusion_units`). The fusion module no longer inherits any Focus stat from its parents.

A unit may deviate only through `CUSTOM_UNIT_FOCUS_GENERATION_EXCEPTIONS`, and its view must show a card mentioning Focus. The validator checks this. The exceptions list is currently empty.

Before 2026-11-19, rows kept their donor's values. That left 104 rows off the rule, none of them carded:

- 62 melee rows at 1 per action: Angels, Imps, Walking Dead, Wyverns, Rocs, Giants, Genies, Gremlins, Air/Water Elementals, Mechanics, Automatons, Couatls, Mummy, Fangarm, and Water/Air fusions.
- 10 ranged rows at 2: Cyclops ×3, Halfling ×3, Gunslinger ×2, Bounty Hunter, Centaur Ranger alt.
- Genie upgrade at 3 per action.
- Crusader and Bounty Hunter at 2 when hit.
- 25 rows with an uncarded +2 Focus per round: the Mammoth, Basilisk, Earth Elemental and Pristine Unicorn alt upgrades plus 21 Lava fusions.
- 4 rows with no `energyPerRound` key at all.

## Proof

- Generated candidate and installed Core: validator OK on 2026-11-19.
- The installed diff against the previous Core is exactly those 104 stat changes.
- Runtime Focus gain in battle is unproven. See the Units row in [`ingame_check_queue.md`](ingame_check_queue.md).
