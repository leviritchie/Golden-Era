# Custom law donor-effect application pass

Generated: 2026-06-15

Purpose: apply as many desired custom faction law effects as possible through existing native/donor law rows before designing custom runtime hooks.

## Policy

- Resource Riches remains untouched.
- Native rows are used only when they are exact or a useful same-kind subset of the desired law.
- Broad active supersets are not used as placeholders; if filtering/triggering is the point of the law, that law remains in the rethink queue.
- Partial donor implementations are marked in `notes`; those notes are the rethink queue.
- No custom runtime behavior is claimed here.
- Multi-level rows are copied as complete non-cumulative native rows from Core where available.

## Applied native/donor rows

This pass added or updated 20 override rows across `custom_factions/law_overrides/*.json`. Existing pre-pass overrides for school access, Castle construction, and Astrology income remain active separately.

| Faction | Rows applied in this pass |
|---|---|
| Castle | Sight, counterattack damage, melee/ranged vanilla formations, gold income, morale, morale trigger chance, support-duration rhythm |
| Cove | Sight radius subset |
| Fortress | Owned-object sight radius, extra construction |
| Rampart | Morale trigger chance, extra construction |
| Tower | Sight radius subset, extra construction |
| Conflux | Morale trigger chance, extra construction |
| Inferno | Extra counterattack charge |
| Necropolis | Enemy action/crit suppression as Dread |
| Stronghold | Sight radius subset, extra construction |

## Rethink queue

These desired mechanics still need either custom runtime hooks or a simpler redesign:

| Area | Why donor rows are insufficient |
|---|---|
| Cove Boarding Hooks / Gun Decks / Prize Shares / Storm Omens / Reload Drills | Counterattack-specific Focus, first-volley cannon/ranged logic, plunder rewards, cannon/reload events, and Focus-spent/generated omen or cooldown triggers need event hooks. |
| Dungeon scout/combat laws | Read Minds-style neutral intention reads, isolated-target checks, disabled/debuffed kill cooldown resets, and kill-corridor geometry need runtime state. |
| Fortress poison/slow identity | Status-conditioned damage reduction, counterattack debuffs, swamp/mire cooldown conditions, and poison/slow omen extensions need status and terrain/event hooks. |
| Rampart Avenger laws | Avenger mark state must be reused directly; donor rows can only provide generic morale/cooldown/formation pieces, which are not enough. |
| Tower prepared/overclock laws | Spellbook reuse, overclock credits, construct intercepts, and spell-triggered priming need spellbook/cast-gate and unit-state hooks. |
| Conflux dynamic elemental laws | Dominant-family checks, mixed-element resonance, elemental calendar phases, and matching spell cooldowns need explicit elemental family runtime logic. |
| Inferno sacrifice/gating laws | Gated identity, sacrifice costs, fire marks, and gated-loss/sacrifice cooldown credits need runtime hooks. |
| Necropolis corpse laws | Corpse counts, corpse spend, drain/raise scaling, revive caps, and corpse-fueled cooldowns need corpse-state hooks. |
| Stronghold warcry/rage laws | Real Warcry execution/cooldown, rage tempo, forward-movement/kill momentum, spellbreaker triggers, and weak-neutral scouting need runtime hooks. |
| Non-Castle formation packages | Existing donor formation rows are unconditional attack-type modifiers; they were not kept for divergent factions because positioning/composition/mark triggers are the desired mechanic. |
| Spell cooldown laws | Existing donor cooldown rows are unconditional friendly or enemy cooldown modifiers; they were not kept where spell filtering or event-generated credits are the desired mechanic. |
| Targeted construction discounts | Existing `constructionDiscount` rows are resource-wide; targeted building-category discounts need displayed-cost and charged-cost hooks. |

## Donor rows harvested

Primary donor/native shapes used:

- `heroStat viewRadius`
- `sideObjectViewRadius`
- `unitStat modifierSet outDmgMods counter_attack`
- `unitStat modifierSet outDmgMods/inDmgMods melee_attack`
- `unitStat modifierSet outDmgMods/inDmgMods shoot_attack`
- `sideStat resPercentIncrementSet gold`
- `heroStat moral`
- `unitStat additionalActionChanceModifier`
- `unitStat receiverAllegiance=enemy additionalActionChanceModifier / critChanceModifier`
- `unitStat numCounters`
- `constructionDailyLimit`
