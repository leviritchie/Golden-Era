# Custom Law No-Compromise Readiness Matrix

This is the implementation queue for restoring the original faction-law vision without donor/stat compromises.

Machine-readable target mechanics now live in `custom_factions/custom_law_targets.json`. That file records the intended destination for each tracked law row; `temporary-compromise` means the current donor/native row is playable scaffolding only, not accepted final behavior.

Status meanings:

- `native/static-only`: may use exact native law rows or exact static JSON effects when they fully match the intended behavior.
- `diagnostic-only`: current source can observe useful evidence, but gameplay mutation is not allowed yet.
- `blocked`: implementation requires a missing or runtime-unproven surface.

Do not treat this matrix as permission to approximate mechanics. A law is gameplay-ready only when the exact consuming hook context can prove active law rank plus the required native state.

## Cross-cutting blockers

| Surface | Current state | Blocks |
|---|---|---|
| Active law/rank in gameplay context | `diagnostic-only`; resolver exists but runtime correlation is unproven in consuming hooks | Every custom runtime law |
| Unit family classifier | `diagnostic-only`; classifier exists, all family facts are `Unknown` | Cove gunpowder, Tower construct, Conflux elemental, Necropolis undead/living/corpse, Inferno gated/summoned, shooter/melee laws |
| Ranged/melee/action classifier | `diagnostic-only`; raw ability/dealer fields and `formationProbe` exist | Formation laws, first-volley laws, shooter/melee split effects |
| Battle geometry/adjacency/facing/isolation | `diagnostic-only`; hex `x/z` and path evidence exist, no proven native geometry helper | Boarding, protection, boxed/flanked, isolated-target, adjacency laws |
| Committed damage mutation | `diagnostic-only`; `Unit.bbgw(...)` is only a candidate | Training damage, counterstroke damage, lifesteal/reanimate, extra magic damage |
| Buff/debuff ownership/duration/stacking | `diagnostic-only`; exact buff add/query/list surfaces are traced | Fortress status laws, Dungeon disable/debuff laws, Rampart Avenger exploitation, Tower calibration buffs |
| Morale roll/extra-action/failure | `diagnostic-only`; roll candidates exist, action-queue effects unproven | Castle morale scaling, Cove Crew Nerve, Dungeon terror exploitation, construct/undead morale replacement |
| Focus/Energy storage mutation | `diagnostic-only`; event/UI evidence exists, storage mutation unproven | Cove Focus gain/spend laws and any Focus-trigger laws |
| Spell cooldown/cast gate | `diagnostic-only`; storage and gate candidates exist, UI/cast synchronization unproven | Tower overclock, Conflux aspect cooldowns, Inferno sacrificial casting, Necropolis corpse fuel |
| Reward/battle result/corpse economy | `diagnostic-only`; reward/result surfaces traced, corpse state unproven | Necropolis corpse economy, Stronghold spoils, Rampart low-loss rewards, Cove prize shares |
| Construction cost/eligibility/commit | `diagnostic-only`; `Homm3CustomConstructionLawDiagnostics` exists for exact candidate methods, but runtime still must prove display/charge/build agreement | Cove/Tower/Inferno/Fortress construction laws |
| Gating/summon temporary identity | `blocked`; visual spawn work is not law-ready proof | Inferno Gating laws, summon-adjacent laws, sacrifice/gated-loss laws |

## Family readiness

| Law family | Status | Next safe batch |
|---|---|---|
| Castle vanilla baseline | `native/static-only` | Keep exact vanilla/native rows where behavior truly matches. |
| Resource Riches | `native/static-only` | Keep unified across factions; do not customize. |
| Adventure vision | `diagnostic-only` | Prove map object identity, side/law rank, and reveal mutation per object type. |
| Hero primary-stat training | `blocked` | Needs committed damage, family classifier, status ownership, spellcast ordering, Gating identity, corpse/mana, and turn-order speed surfaces. |
| Counterstroke doctrine | `diagnostic-only` | Prove real counterattack dispatch, committed damage ordering, actor identity, active rank, and effect-specific storage. |
| Melee/ranged formations | `blocked` | Needs action classifier, first-volley state, geometry/adjacency/facing, unit family facts, and active rank. |
| Gold/reward/economy laws | `diagnostic-only` | Prove committed reward/capture/battle-result identity and idempotent grant point. |
| Spell school/cast-gate laws | `diagnostic-only` | Prove successful spellcast ordering, native spellbook/gate state, and visible UI synchronization. |
| Construction laws | `diagnostic-only` | Use `homm3_custom_construction_law_diag.flag`; prove native cost display, charged cost, eligibility, and commit all agree. |
| Calendar/daily omen laws | `diagnostic-only` | Prove day-start idempotence, side identity, active rank, and target family/object state. |
| Cooldown laws | `diagnostic-only` | Prove cooldown storage, cast gate, spellbook UI, and law-triggered state edit in the same context. |

## Faction-specific blockers

| Faction | Intended mechanics most blocked | Blocking surfaces |
|---|---|---|
| Cove | Focus gain/spend, gunpowder/Cannon/Pirate laws, first volley, prize shares | Focus storage, unit classifier, action classifier, first-volley, reward commit |
| Dungeon | Isolated-target punishment, disabled/debuffed exploitation, terror/morale effects | Geometry/isolation, buff/debuff ownership, morale/action queue, committed damage |
| Fortress | Poison/slow pressure, Bog Line, defensive reward/status laws | Buff/debuff ownership/duration, living/status classifier, reward/battle result |
| Inferno | Gated-entry buffs, Hellpack adjacency, sacrifice/gated-loss casting | Gating/summon temporary identity, geometry, spell cooldown/cast gate, sacrifice/loss state |
| Necropolis | Corpse economy, living/undead targeting, reanimation/restore, corpse mana/cooldowns | Corpse state, living/undead classifier, battle result, committed damage, mana/cooldown storage |
| Rampart | Avenger-mark exploitation, hunter pairs, low-loss rewards | Avenger buff identity in consuming context, shooter/melee classifier, geometry, reward/battle result |
| Stronghold | Warband melee/ranged split, momentum, spoils, Warcry interactions | Action classifier, movement/kills, reward/battle result, Warcry/Focus separation |
| Tower | Constructs, calibration/overclock, spellbook/cooldown, construct buildings | Construct classifier, spellcast ordering, cooldown/gate/UI sync, construction category proof |
| Conflux | Elemental family composition, elemental aspect/cooldowns, planar calendar | Elemental classifier, spell family mapping, cooldown/gate, calendar side state |

## Activation rule

Before any law moves from `diagnostic-only` or `blocked` to gameplay implementation, the implementation packet must name:

- Active law/rank source in the exact hook context.
- The exact native event or state mutation surface.
- The classifier facts consumed, with `Unknown` fail-closed behavior.
- The diagnostic flag proving the surface.
- The user-driven runtime scenario that will validate it.
- The AGENTS/doc note to update after validation.

If any item is missing, leave the law disabled and document the missing surface. Do not substitute donor effects, generic stat rows, or broad fallback behavior.
