# Custom faction law technical implementation proposals

Status: implementation handoff for the definitive custom law list.

This document translates the current desired law designs into technical implementation proposals for future agents that do not have this conversation in context.

## Scope and source material

Primary references: `docs/custom_law_vanilla_effect_match_pass.md` and `docs/olden_era_vanilla_effect_text_reference.md`.

Resource Riches is intentionally excluded. It remains unified across factions for balance.

Castle is intentionally vanilla-adjacent. Castle proposals should prefer native rows and minimal runtime hooks unless the law text explicitly requires faction-specific behavior.

## Non-negotiable implementation constraints

Law levels are not automatically cumulative. Every `parametersPerLevel` row must contain the complete native JSON effect for that rank, and every runtime hook must read the active rank and apply the full intended rank behavior.

Do not invent JSON bonus types unless the editor schema, generator, and runtime parser are intentionally extended. Unknown law bonus types are silent-no-op risks.

Prefer vanilla law/effect data where exact. Use custom runtime hooks for filters, triggers, conditional effects, or mechanics that cannot be represented in native law JSON.

Do not implement gameplay through UI-only changes. Tooltips, disabled buttons, greying, icons, and forecast overlays must reflect real state; they must not be the source of truth.

Centralize all obfuscated type, field, and method names in `GameSymbols`. New hook classes should consume symbol groups, not inline obfuscated names.

If classification fails, skip the custom effect and log behind a diagnostic flag. Do not silently fall back to broader behavior such as all spells, all units, or all buildings.

Runtime probing order should follow project policy: native live bridge read-only features first, volatile probes second, generic bridge enhancement third, manual diagnostic builds last.

## Shared architecture recommendation

Implement one shared law runtime resolver before implementing any custom law family.

Suggested core class: `Homm3CustomFactionLawRuntime`.

| Responsibility | Detail |
|---|---|
| Law resolution | Resolve side, hero, town, faction SID, law SID, active rank, battle, round, and day. |
| ID policy | Resolve law IDs using pattern `fraction_law_homm3_<faction>_<index>`. |
| Gating | Gate every custom effect on active enacted law rank, not faction identity alone. |
| Idempotence | Provide keys for day-start, battle-start, battle-round, spell-cast, construction, capture, reward, damage, and counterattack hooks. |
| Diagnostics | Keep logs behind dedicated flags such as `homm3_custom_law_diag.flag` plus family-specific flags. |

Suggested shared files/classes to inspect or add:

| Area | Files/classes |
|---|---|
| Law generation | `tools/release_port/apply_release_core_overlay.py` |
| Editor/schema | `tools/ability_editor/server.py`, `tools/ability_editor/static/app.js` |
| Law overrides | `custom_factions/law_overrides/*.json` |
| Source mechanics | `custom_factions/source_mechanics/homm3_*.json` |
| Runtime symbols | `artifacts/bridge_current_build/src/OfflineUnlockMod/GameSymbols.cs` |
| Runtime registration | `artifacts/bridge_current_build/src/OfflineUnlockMod/Plugin.cs` |
| Faction registry | `artifacts/bridge_current_build/src/OfflineUnlockMod/Homm3CustomFactionRegistry.cs` |
| Diagnostics | `artifacts/bridge_current_build/src/OfflineUnlockMod/Homm3DiagnosticFlags.cs` |

Suggested runtime hook families:

| Law family | Hook class |
|---|---|
| Hero sight radius | `Homm3AdventureVisionLawHook` |
| Hero primary-stat training | `Homm3HeroTrainingLawHook` |
| Counterattack doctrine | `Homm3CounterattackDoctrineHook` |
| Melee/ranged formations | `Homm3FormationLawRuntime` |
| Gold income percent | `Homm3CustomFactionEconomyLaws` |
| Morale and morale triggers | `Homm3MoraleTriggerLawRuntime` |
| Spell school access | `Homm3SpellSchoolLawHook` |
| Extra construction | `Homm3CustomConstructionLawRuntime` |
| Astrology/calendar income | `Homm3CustomFactionCalendarLawHook` |
| Spell cooldown modifier | `Homm3SpellCooldownLawHook` |

## Vanilla data anchors

| Mechanic | Native/data anchor |
|---|---|
| Plain vision | `heroStat viewRadius`, `sideObjectViewRadius`, Farsight/Groundsight style reveal effects |
| Plain combat stat bonus | `unitStat`, `unitStatBattle`, modifier sets |
| Counterattack damage | Castle-like `outDmgMods counter_attack` row |
| Extra counterattack | `unitStat numCounters` |
| Gold percent income | `sideStat resPercentIncrementSet gold` |
| Morale | native morale rows and additional action chance rows |
| School access | `heroStat magicSchoolSet school 0 1` and `magicSchoolSet school 5 0` |
| Extra construction | `constructionDailyLimit([1])` |
| Construction discount | `constructionDiscount([resource, delta])` |
| Astrology income | `astrologyExp([250/500/750, 0.0])` |
| Friendly spell cooldown | likely `magicCdBonus`, verify from `fraction_law_nature_31` |
| Enemy spell cooldown | likely `magicCdBonus` with enemy/opponent receiver, verify from `fraction_law_unfrozen_36` |

## Law family 1: Hero sight radius

Likely law index: `2`. Likely law IDs: `fraction_law_homm3_<faction>_2`.

Native reuse: use `heroStat viewRadius` only for simple hero vision. Use `sideObjectViewRadius` or native reveal spells where possible for object-based reveal. Custom runtime hooks are required for object classifications, last-known enemy locations, neutral intention inspection, and structure-based reveals.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3AdventureVisionLawHook`. |
| Symbols | Add `GameSymbols.AdventureVisionLaw` for map hero, side, object config, fog/reveal, law state, and turn/day hooks. |
| Timing | Recompute on side start turn, hero movement, map load, town ownership change, dwelling ownership change, and law enactment. |
| Reveal path | Prefer native reveal APIs or existing spell reveal effects. Avoid direct fog mutation unless native reveal surfaces are insufficient and runtime-probed. |
| Idempotence | Use bounded reveal radii and side/day/object keys. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Road Wardens | Give `viewRadius +4` only when the hero is on road tiles after road terrain has been proven readable. If road classification is unproven, keep this law probe-only or fail closed with diagnostic logging; do not silently replace it with a broad always-on vision bonus. |
| Cove | Sea Charts | Reveal treasure caches, pirate hideouts, creature banks, and high-value neutral camps near owned Cove towns/dwellings. Needs explicit object SID/category allowlists and ownership-driven reveal from structures, not ocean travel assumptions. |
| Dungeon | Deep Scouts | Let heroes inspect neutral intentions or threat disposition. If native Read Minds-style data exists, reuse it. Otherwise provide a custom read-only tooltip/preview hook gated by law rank and hero proximity. |
| Fortress | Marsh Sense | Owned Fortress towns, dwellings, and swamp structures reveal nearby enemy heroes at turn start. Needs structure ownership, enemy hero positions, and native reveal method. |
| Rampart | Avenger's Trail | Reveal last known or nearest Avenger-marked/favored enemy hero/army. Must integrate with the actual Avenger mark owner; do not create a second mark registry. |
| Tower | Observatory Network | Owned Tower towns/observatories reveal artifacts and small regions around each. Use structure-driven object reveal. Artifact classification must be exact SID/category based. |
| Conflux | Planar Attunement | Reveal elemental shrines, elemental dwellings, and magic sites tied to the dominant Conflux army element. Requires explicit elemental-family mapping. |
| Inferno | Hellgate Omens | Reveal Pocket Dimensions, teleporters, Inferno dwellings, and summoning sites. Avoid fabricating teleport/ocean mechanics; use existing map object classes only. |
| Necropolis | Gravesight | Reveal graveyards, recent battle/corpse sites, undead dwellings, and corpse-rich locations near owned Necropolis structures. Needs logical corpse/battle-site data or explicit map-object allowlist. |
| Stronghold | War Scouts | Reveal weaker Easy/Very Easy neutral stacks in the hero's current area. Requires neutral strength classification from native stack threat/intention data, not text. |

Runtime probes: active law/rank on side/hero; native fog/reveal API; map object classification fields; hero tile/road/native terrain reads; neutral stack strength/intention fields.

## Law family 2: Hero primary-stat training

Likely law index: `6` for the divergent primary training row. Leave adjacent vanilla primary-stat rows alone unless the law tree topology requires otherwise.

Native reuse: simple attack/defense/spell power/knowledge data can use native `heroStat`, `unitStat`, or `unitStatBattle`. Most proposed faction effects are conditional and require runtime hooks.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3HeroTrainingLawHook`. |
| Buffs | Add shared buff utilities in `Homm3CustomLawBuffs` if an equivalent does not already exist. |
| Symbols | Add `GameSymbols.HeroTrainingLaws` for damage, spell cast, summon/gate spawn, corpse/casualty, mana, unit status, battle round, and unit stat surfaces. |
| Policy | Prefer native stat rows for static bonuses. Use runtime hooks for conditional damage, stat stacks, temporary mana, speed, and summon entry buffs. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Officer Corps | Units deal +2% damage per positive Morale. Implement as a damage hook keyed to current morale value. Do not change morale itself. |
| Cove | Burning Ash | Gunpowder attacks from Cannons/Pirates reduce enemy Defense by 1/2 stacking. Hook real attack resolution; apply a native-style debuff to target after successful hit. Exact Cannon/Pirate SIDs required. |
| Dungeon | Predator's Instruction | Isolated enemies take +5/10% damage. Needs battle geometry helper and isolated predicate, such as no adjacent allies or boxed/flanked status. |
| Fortress | Hidebound Drill | Enemies with a negative status deal 10% less damage to Fortress units. Use outgoing damage hook on debuffed attacker; classify negative statuses by exact buff IDs. |
| Rampart | Avenger's Tutelage | Increase vulnerability of Avenger-marked units. Runtime must reuse existing Avenger mark state. Do not infer from faction matchup alone. |
| Tower | Arcane Calibration | Each Tower hero spell cast gives friendly units +1 Attack and +1 Defense for 3 rounds, stacking. Hook successful spell cast, apply stackable timed battle buff, clean up by round. |
| Conflux | Elemental Aspect | Fire grants Offense, Earth Defense, Air Speed, Water HP with rank +1/+2. This is mostly data/runtime classification by unit family. Use native `unitStatBattle` if family filters can be generated; otherwise runtime buff by family. |
| Inferno | Infernal Ascension | Gated units enter battle with +15/30% damage. Hook Gating spawn/entry; tag temporary gated stacks; apply entry buff. Must not affect permanent recruited units. |
| Necropolis | Corpse Wisdom | End of combat round grants 2/4/6 temporary mana per corpse. Requires logical corpse count and temporary mana mutation/cleanup. High risk; probe before implementation. |
| Stronghold | Berserker Charge | Wounded units gain +1/+2 Speed. Hook HP/stack-size threshold and turn-order refresh. Speed changes in turn order are high risk; prefer applying at round boundary if native turn order cannot update safely. |

Runtime probes: final damage mutation point; native buff application/duration fields; battle geometry/adjacency reads; Gating spawn identity; corpse count and mana mutation; turn-order behavior after speed changes.

## Law family 3: Counterattack doctrine

Likely law index: `13`.

Known native data: Castle-style counterattack damage can use `unitStat` modifier set for `outDmgMods counter_attack` at 0.50/1.00 style values. Extra counterattack charge can use `unitStat numCounters 1` where exact.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3CounterattackDoctrineHook` and `Homm3CounterattackDoctrineConfig`. |
| Symbols | Add `GameSymbols.CounterattackDoctrine` for counterattack execution, damage, counter charges, attacker/defender identities, HP restore/revive, Focus mutation, and stat debuff fields. |
| Hook point | Hook actual counterattack execution and damage result. Do not use damage histograms or UI overlay as proof. |
| Idempotence | Track per battle action/counterattack to avoid duplicate effects from animation/update hooks. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Shield Wall | Keep vanilla counterattack damage bonus as data-only if possible. |
| Cove | Boarding Hooks | Counterattacks generate 1 Focus. Hook successful counterattack and add Focus through real Focus mutation surface. Focus is universal, but write path still needs probing. |
| Dungeon | Outnumber | Counterattacks deal +10% damage to stacks with fewer units than the counterattacker. Hook counterattack damage and compare current stack counts. |
| Fortress | Thorned Hides | Counterattacks reduce enemy Attack by -1. Apply native debuff to the original attacker after successful counterattack. |
| Rampart | Avenger's Reprisal | Avenger-marked enemies take +100% counterattack damage. Reuse actual Avenger mark state; damage hook only on marked target. |
| Tower | Reactive Wards | Counterattacks benefit from hero Spell Power as if Attack. Hook damage calculation and add derived attack-equivalent bonus from defending side hero Spell Power. |
| Conflux | Elemental Backlash | Counterattacks deal additional magic damage based on countering stack strength. Add a second damage component only if native supports extra magic damage. Folding it into final physical damage changes resistance, immunity, attribution, and triggers, so treat that only as an explicitly approved design compromise after probing native damage-component support. |
| Inferno | Hellfire Reprisal | All units gain +1 counterattack charge. Use native `unitStat numCounters 1` if it applies cleanly. |
| Necropolis | Death Grip | Counterattacks drain 10/20% dealt damage to restore lost units up to original size. Hook final damage, convert to HP restore, clamp to original stack size. |
| Stronghold | Blood Feud | Successful counterattack applies stacking 2/4% damage bonus. Track per-stack battle buff on counterattack success, cap to avoid runaway until balance pass. |

Runtime probes: counterattack method and final damage mutation point; counter charge storage; Focus mutation; HP restoration/revive stack-size update; whether extra magic damage can be represented separately.

## Law family 4: Melee and ranged formations

Likely law indices: `18` and `19`.

Native reuse: simple melee/ranged unit stat rows may be data-only. The proposed faction variants require battle geometry, first-volley, adjacency, marks, gating, mixed-element composition, and death aura state, so use runtime hooks where needed.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3FormationLawRuntime`. |
| Geometry | Add `Homm3BattleGeometry` helper for adjacency, facing, flank, boxed-in, surrounded, threatened ally, and distance predicates. |
| Symbols | Add `GameSymbols.FormationLaws` for battle units, hex coordinates, ranged/melee attack classification, first attack flag, marks, statuses, and faction/unit SID reads. |
| Slot model | Keep melee and ranged law slots separate in JSON, but let one runtime service resolve both active laws and apply the combined faction formation package. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Line Doctrine | Keep vanilla-style melee/ranged formation bonuses where possible. Use native unit stat rows. |
| Cove | Boarding Parties / Gun Decks | Melee/Pirate adjacency protects shooters; first Cannon/Pirate volley gains bonus; cannon/gunpowder units interact with Focus/reload. Needs first-volley state and exact ranged/gunpowder classification. |
| Dungeon | Kill Corridors | Bonuses when enemies are boxed, disabled, flanked, or unable to retaliate. Needs geometry plus negative-status/unable-retaliate predicate. |
| Fortress | Bog Line | Defensive bonuses when attacked, surrounded, or fighting slowed/poisoned enemies. Hook incoming attacks and status checks. |
| Rampart | Hunter Pairs | Melee protects shooters; shooters exploit Avenger-marked enemies. Needs protect-adjacent-shooter and Avenger mark state. |
| Tower | Battle Automata | Constructs intercept, shooters overcharge, and hero spellcasts reload/prime units. Needs construct classifier and spellcast-to-unit-state hook. |
| Conflux | Elemental Conjunction | Bonuses require mixed elemental composition. Use explicit unit family mapping and battle-start/battle-round refresh. |
| Inferno | Hellpack Assault | Bonuses after gating/teleport adjacency; ranged attacks set fire marks. Needs gated/teleported tag and fire mark buff. |
| Necropolis | Death March | Slow aura pressure, death clouds, and living-enemy penalties. Needs living/undead classifier and aura/status application. |
| Stronghold | Warband Crush | Melee improves after forward movement/kills; ranged softens armor. Needs movement direction/advance predicate, kill hook, armor debuff. |

Runtime probes: battle unit hex/facing/movement fields; ranged vs melee vs long-reach attack classification; first-attack/first-volley state; mark/status storage; unit family classifier from custom registry.

## Law family 5: Gold income percent

Likely law index: `21`.

Known native data: Castle baseline can use `sideStat resPercentIncrementSet gold 0.10/0.20` style rows.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3CustomFactionEconomyLaws`. |
| Resource helper | Add `Homm3SideResourceGrant` that grants resources through real side resource APIs and emits UI/events where needed. |
| Symbols | Add `GameSymbols.EconomyLaws` for side resources, map reward, battle result, object capture, mine/dwelling ownership, day-start, and law state. |
| Hook point | Hook actual reward/capture/commit events, not reward preview text. |
| Idempotence | Every grant needs battle ID, object ID, day, side, and law ID keys. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Prosperous Holdings | Keep native percent gold income. Data-only. |
| Cove | Prize Shares | Grant bonus gold from plunder, treasure, creature banks, and defeated neutrals. Hook real reward resolution; classify treasure/creature banks by object SID/category. |
| Dungeon | Subjugated Mines | Grant income after defeating mine guards or conquering underground sites. Hook ownership transfer/combat completion. Avoid broad all-mine daily bonus unless chosen intentionally. |
| Fortress | Marsh Rights | Grant gold from defensive wins, native terrain control, or swamp structures. Start with defensive win and owned-structure day-start; terrain-control needs probing. |
| Rampart | Preservation Tithe | Grant gold/astrology-style reward for low-loss wins or marked enemy kills. Requires battle result casualty accounting and Avenger mark integration. |
| Tower | Transmutation Ledger | Convert rare resources to gold or construction discounts. Prefer day-start optional conversion only if UI can expose it; otherwise implement passive rare-resource-to-gold trickle with explicit cap. |
| Conflux | Elemental Market | Income depends on elemental family mix in armies/towns. Use explicit family mapping and day-start scan. |
| Inferno | Soul Contract | Sacrifices, summoned losses, or fire kills feed economy. Must distinguish real sacrifice/gated loss from ordinary permanent casualties. |
| Necropolis | Mortuary Accounting | Gold from casualties/corpse sites with reduced civic economy if desired. Use battle casualties/corpse sites, not visual corpses. |
| Stronghold | Spoils Ledger | Gold from aggression, clearing, conquest momentum. Hook neutral clearing, town/mine capture, or consecutive wins with idempotence. |

Runtime probes: safe resource mutation API and UI/event notification; battle reward commit path; object capture/ownership event; casualty/low-loss accounting; sacrifice/summon/gated death identity.

## Law family 6: Morale and morale triggers

Likely law indices: `22` and `25`.

Native reuse: Castle can use morale and additional-action-chance native rows. Necropolis should generally avoid friendly morale bonuses and instead use enemy morale penalties/dread effects.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3MoraleTriggerLawRuntime`. |
| Symbols | Add `GameSymbols.MoraleTriggerLaws` for morale values, morale-trigger events, additional action, kill/death events, Focus, unit buffs, gated units, and warcry/faction abilities. |
| Hook point | Hook actual morale trigger/failure and battle events. Do not infer morale triggers from UI animation alone. |
| Necropolis policy | Keep Necropolis no-friendly-morale identity explicit. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Righteous Zeal | Keep vanilla morale and morale-trigger chance. Data-only where possible. |
| Cove | Crew Nerve | Momentum after kills, plunder, cannon hits, or surviving ranged fire. Hook kill/cannon/survive events and apply temporary morale/Focus/speed buff. |
| Dungeon | Terror Exploitation | Replace friendly morale with bonuses when enemy morale fails or enemy is debuffed. Hook enemy morale failure and negative status. |
| Fortress | Cold-Blooded Endurance | No cheering focus; bonuses after taking hits or slowing enemies. Hook damage taken and slow/poison application. |
| Rampart | Defender's Grace | Morale from protecting allies, favored-enemy kills, preserving units. Needs protect-adjacent ally, low-loss, and Avenger mark hooks. |
| Tower | Synchronization | Constructs calibrate after spells; morale becomes readiness. Use spellcast-to-construct buff, not ordinary morale if constructs are morale-neutral. |
| Conflux | Elemental Harmony | Mixed elemental families produce resonance instead of standard morale. Battle-start/round buffs from family mix. |
| Inferno | Frenzy | Friendly deaths, sacrifices, and gated losses trigger momentum. Must distinguish temporary gated losses from permanent casualties. |
| Necropolis | Dread | No friendly morale; enemy morale penalties, fear aura, and corpse value. Use enemy morale penalty/status aura, not positive undead morale. |
| Stronghold | Rage | Damage taken and kills trigger tempo. Hook damage and kill events; apply Speed/damage buff with cap. |

Runtime probes: exact morale trigger/failure event; additional action behavior; Focus mutation; temporary unit buff application; death/gated/sacrifice classification.

## Law family 7: Spell school access

Likely law indices: `15` and `27`.

Native data shapes: `heroStat magicSchoolSet school 0 1` for +1 spell level, and `heroStat magicSchoolSet school 5 0` for broad/all-tier access. Implement the faction design across both slots unless the law-tree UI is intentionally restructured.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3SpellSchoolLawHook`. |
| Symbols | Add `GameSymbols.SpellSchoolLaws` for spell-cast event, spellbook learn/use checks, MagicConfig SID/school/tier/use fields, law state, hero school modifiers, and battle spell resolution. |
| Data use | Use native `magicSchoolSet` for pure school access. Runtime hooks handle dynamic schools, spellbook reuse, faction ability coupling, and conditional spell boosts. |
| Safety | Do not fabricate spellbook UI entries unless native learn/use route is proven. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Daylight Liturgy | Data-only Daylight access. Slot 15 gives Day spells +1 level; slot 27 unlocks all Day tiers. |
| Cove | Storm Charts | Use Space/Arcane access. Runtime add-on: after Favorable Wind, Doreath's Tide, or similar movement/ranged support spells, Cove gunpowder units gain short ranged/long-reach damage benefit; higher rank also grants Focus on next qualifying attack. |
| Dungeon | Night Dominion | Data-only Night access is acceptable for first pass because Night already contains curses, disables, Vulnerability, Despair, and Silence. |
| Fortress | Bog Witchcraft | Use Primal access. Runtime add-on extends poison/slow/movement-restriction durations and optionally boosts Fortress damage against poisoned/slowed enemies in native-terrain or adjacent conditions. |
| Rampart | Druidic Oath | Use Primal access. Runtime add-on makes cleanse/resistance/regeneration spells grant short Defense and interact with Avenger-marked enemies. |
| Tower | Prepared Artifice | Use Tower's chosen native school from generator profile for base access. Runtime add-on allows limited spellbook reuse and prepared charges. High risk; probe spellbook state. |
| Conflux | Elemental Wheel | Custom dynamic school mapping by dominant elemental family. Avoid static `magicSchoolSet` unless used only as a visible proxy. Runtime must compute family composition and apply effective spell level/access. |
| Inferno | Hellfire Gatecraft | Use Primal if fire/summon/gate spells live there; verify before final data. Runtime charges from gated/summoned loss or sacrifice boost fire/summon/teleport spells. |
| Necropolis | Death Rite | Use Night access. Runtime corpse/casualty value boosts curse, drain, or raise effects. Integrate with existing Skeletal Necromancy bridge. |
| Stronghold | Warcries | No traditional school access. Replace with Warcry law behavior in runtime; reduce Focus/cost, add uses, or empower morale/luck/initiative warcries through real hero ability path. |

Runtime probes: exact spell-cast hook surface; spellbook learn/use and Observatory unlock checks; MagicConfig fields; whether temporary battle-only school boosts affect already-built spellbook UI; Warcry execution/cooldown path.

## Law family 8: Extra construction

Likely law index: `28`.

Known native data: `constructionDailyLimit([1])` and `constructionDiscount([resource, delta])`.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3CustomConstructionLawRuntime`. |
| Symbols | Add `GameSymbols.ConstructionLaws` or extend `GameSymbols.ReleaseTownUi` for build validation, build commit, cost calculation, town/city faction, building SID, building level, constructed state, town garrison, construction cooldown, and side resources. |
| Cost policy | Patch both displayed cost and charged cost through one helper. |
| Build policy | Patch build validation/commit, not only button enabled state. |
| Token policy | If an extra build is allowed, consume the extra token only after successful construction. |
| State policy | Stateful laws need persistence or deterministic recomputation before shipping. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Civic Engineers | Data-only `constructionDailyLimit([1])`. Vanilla baseline. |
| Cove | Harbor Rush | One extra market, tavern, cannon, or pirate infrastructure build per day; eligible buildings cost 20% less gold. Needs targeted eligibility/cost hook. |
| Dungeon | Excavation Crews | Capturing mines, caves, or external dwellings grants a side-scoped token for the next Dungeon dwelling build/upgrade as extra construction. Needs capture hook and dwelling classification. |
| Fortress | Mudworks | One extra fortification/defensive support build per day; fortifications cost 25% less wood/ore. Eligible SIDs include walls and Fortress defensive specials. |
| Rampart | Living Groves | Dwellings mature after construction; a matured dwelling upgrade can be built as extra construction at reduced wood cost. Needs construction-day state/persistence. |
| Tower | Grand Workshop | One extra magical/construct building per day with +50% gold surcharge. Needs normal-slot vs workshop-slot distinction and clear UI cost. |
| Conflux | Planar Alignment | Two elemental alignments allow one extra elemental building; four alignments discount rare resources. Needs explicit town/building elemental mapping. |
| Inferno | Blood Mortar | One extra building per day by sacrificing garrison creatures worth at least 25% of gold cost. Needs safe garrison mutation and visible deterministic sacrifice rule. |
| Necropolis | Reanimated Masonry | Extra dwelling/converter construction by spending deathworks credit from casualties or captured dwellings. Start with credit only; defer actual external dwelling conversion until proven. |
| Stronghold | Warcamp Raising | One extra military building per day; military buildings cost 20% less ore. Professional path is an exact military-building allowlist plus shared displayed/charged cost hook. A broad native ore discount is only an explicitly documented balance/design compromise, not an implementation fallback. |

Runtime probes: exact construction validation and commit methods; construction cooldown/daily build state; displayed cost and charged cost path; town garrison read/write and unit value; capture/ownership events; durable state strategy.

## Law family 9: Astrology/calendar income

Likely law index: `33`.

Known native data: `astrologyExp([250, 0.0])`, `astrologyExp([500, 0.0])`, `astrologyExp([750, 0.0])`.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3CustomFactionCalendarLawHook`. |
| Symbols | Add `GameSymbols.CalendarLaws` for day start, side start turn, side law state, side astrology fields, astrology exp change events, spell cast, battle start/end, unit statuses, and faction ability events. |
| Data use | Use native `astrologyExp` in JSON for guaranteed income. Custom calendar behavior belongs in C# runtime hooks keyed by law ID and rank. |
| Phase model | Use deterministic phase model by day, for example `day % 3`, rather than mutable counters where practical. |
| Idempotence | Use key `(session, side, day, law)` for day-start behavior. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Chapel Calendar | Native astrology income. Runtime: support/blessing spell casts grant bonus Astrology charges; higher ranks add first-combat blessing/morale support buff. |
| Cove | Storm Omens | Native astrology income. Runtime: Focus generation/spend creates Storm Omens; Pirate/Cannon ranged attacks consume omens for damage/speed/Focus effects by rank. |
| Dungeon | Deep Portents | Native astrology income. Runtime: first Night spells gain spell-level/effect scaling; debuffing spells mark targets for Dungeon damage bonus. |
| Fortress | Witch Signs | Native astrology income. Runtime: first poison/slow applications each battle gain duration; higher ranks add adjacent poisoned/slowed enemy HP restore/regeneration effects. |
| Rampart | Druidic Calendar | Native astrology income. Runtime: cleanse/regeneration/resistance cycle at battle start and unit turn start. Use actual debuff removal. |
| Tower | Celestial Calculus | Native astrology income. Runtime: day-start calculation charges refund cooldown or apply construct/artifice buffs after spellcasts. Cooldown mutation needs probing. |
| Conflux | Planar Calendar | Native astrology income. Runtime: day phase determined by dominant elemental families; apply Fire/Air/Water/Earth round-one or harmony buffs. |
| Inferno | Infernal Signs | Native astrology income. Runtime: first fire damage applies burning/vulnerability marker; gated/summoned units enter buffed; gated-loss/sacrifice fuels spell effect/cooldown. |
| Necropolis | Death Moon | Native astrology income. Runtime: corpse consumption/raise grants Astrology and boosts raise/drain; later ranks add Dread pressure if corpse count threshold met. |
| Stronghold | War Festival | Native astrology income. Runtime: Warcry use grants Astrology; Warcry-followup kills grant speed/damage buffs. Needs real Warcry execution hook. |

Runtime probes: safe Astrology progress grant and notification event; active law/rank read from side law state; spell SID/school classification; Focus spend/generation event; status duration/application/removal; gated/summoned identity; corpse logical state/consumption; actual Warcry gameplay execution.

## Law family 10: Spell cooldown modifier

Confirmed generator law index: `34`. Law IDs: `fraction_law_homm3_<faction>_34`. Earlier proposal drafts used row `31`; do not use row `31` for cooldown implementation unless the generator topology changes and is reverified.

Vanilla anchors: `fraction_law_nature_31` / Natural Serenity for friendly battle spell cooldown reduction; `fraction_law_unfrozen_36` / Absolute Zero for enemy battle spell cooldown increase; `druid_ability_4` for spellbook reuse precedent; `day_10_magic_second_song` for creature ability cooldown reset only, not hero spell cooldown.

Shared implementation:

| Requirement | Proposal |
|---|---|
| Hook | Add `Homm3SpellCooldownLawHook`. |
| Symbols | Add `GameSymbols.SpellCooldownLaw` for battle spell config/runtime, hero spellbook, side law state, battle side/hero, spell SID/school/tier, caster side, remaining cooldown, base cooldown, cast gate, and apply-cooldown method. |
| Data verification | Verify exact native JSON shape for `magicCdBonus` from Core before writing overrides. |
| Hook point | Patch actual cooldown calculation/application and native cast gate. Do not implement by greying or enabling spellbook buttons. |
| Credits | Temporary credits are consumed only after a real successful spell cast. |
| Clamp | Clamp cooldown to the native minimum, likely 0 or whatever the game uses. |

Faction proposals:

| Faction | Law | Implementation proposal |
|---|---|---|
| Castle | Liturgical Rhythm | Support/blessing Daylight spells have cooldown reduced by 1; higher ranks extend to cleanse/heal/morale/defense spells and add one extra once-per-round support cooldown credit. |
| Cove | Reload Drills | Movement-control and storm/sea spells reduced by 1; cannon/reload actions and Focus spend/generation grant once-per-round cooldown credits to qualifying spells. |
| Dungeon | Cruel Momentum | Night/curse spells reduced by 1; killing debuffed or disabled stacks grants cooldown credits or full reset of shortest qualifying cooldown, capped. |
| Fortress | Bog Hex | Enemy spell cooldowns increase while enemy army is slowed/poisoned/mired. Use Absolute Zero native shape only if unconditional enemy penalty is accepted; conditional logic needs runtime. |
| Rampart | Avenger's Patience | Nature/protection/restoration spells reduced by 1; cleanse/resist and Avenger-mark interaction grant cooldown credits. Reuse actual Avenger mark state. |
| Tower | Overclocked Spellworks | Tower spells reduced by 1; spellcasts bank overclock credits; later ranks let a spell with 1 remaining cooldown be treated as ready once per battle through native cast gate. |
| Conflux | Aspect Cooldowns | Spells matching dominant elemental army family get cooldown reduction; mixed-family spell sequencing grants rotating credits. Needs exact unit/spell family mapping. |
| Inferno | Sacrificial Casting | Fire/gating/summon spells reduced by 1; sacrifice or gated/summoned losses grant cooldown credits. Must distinguish temporary summons from permanent casualties. |
| Necropolis | Corpse Fuel | Raise/drain/curse/Night death spells reduced by 1; corpse spending grants cooldown credits. Hook actual corpse consumption, not display count. |
| Stronghold | Spellbreaker Chants | Warcry cooldowns reduced or once-per-round if native path supports; anti-magic/silence/spellbreaker effects increase enemy spell cooldown; maintain sibling Warcry cooldown sharing. |

Runtime probes: exact `magicCdBonus` JSON shape and receiver semantics; stored cooldown vs effective cooldown vs UI cooldown; cast gate before and after cooldown edits; enemy cooldown increase behavior; trigger events for kill, debuff kill, corpse spend, sacrifice/gating, cleanse/resist, cannon reload, and Warcry use.

## Implementation order

| Step | Work |
|---:|---|
| 1 | Add/verify law override data for purely native rows only: Castle baseline construction, gold, school access, astrology, and any plain cooldown rows after Core shape verification. |
| 2 | Add `Homm3CustomFactionLawRuntime` with read-only diagnostics for active side/faction/law/rank. |
| 3 | Add diagnostic-only hooks for day start, battle start, spell cast, construction commit, battle damage, counterattack, morale trigger, reward/capture. |
| 4 | Implement one custom runtime family at a time, starting with lower-risk, self-contained families: construction targeted discounts, gold reward grants, and counterattack stat debuffs. |
| 5 | Implement high-risk dynamic families later: Tower spellbook reuse, Conflux dynamic school/cooldown mapping, Necropolis corpse fuel, Inferno sacrifice/gating economy, Stronghold real Warcry cooldowns. |

Recommended family priority:

| Early | Middle | Late |
|---|---|---|
| Castle native rows | Cove Focus/cannon laws | Tower spellbook/overclock laws |
| Static school access | Fortress poison/slow hooks | Conflux dynamic elemental laws |
| Construction targeted cost | Rampart Avenger interactions | Necropolis corpse economy/cooldowns |
| Gold reward hooks | Dungeon disable/debuff kill triggers | Inferno sacrifice/gating deep hooks |
| Counterattack data/hooks | Morale trigger laws | Stronghold Warcry gameplay cooldowns |

## Required runtime probe checklist

| Surface | Needed for |
|---|---|
| Active law/rank read | Every runtime law |
| Native reveal/fog API | Hero sight radius |
| Battle damage mutation | Training, counterattack, formations, morale, calendar |
| Counterattack execution event | Counterattack doctrine |
| Focus mutation/event | Cove laws, some Tower/Rampart variants |
| Buff/status apply/remove/duration | Training, formations, morale, school, calendar |
| Battle unit hex/geometry | Formations, isolation, adjacency, protection |
| Reward/capture commit | Gold, construction tokens, economy laws |
| Construction validation/cost/commit | Extra construction |
| Astrology progress mutation/event | Calendar laws |
| Spell cast and spellbook gate | School and cooldown laws |
| Spell cooldown storage/application | Cooldown laws |
| Gating/summon temporary unit identity | Inferno laws |
| Corpse logical state/consumption | Necropolis laws |
| Warcry real execution/cooldown | Stronghold laws |
| Avenger mark state | Rampart laws |
| Elemental family mapping | Conflux laws |

## Documentation and code hygiene requirements

Any implementation agent should update `docs/AGENT_REFERENCE.md` or another existing agent reference document with proven runtime findings, especially exact native method names, failed hypotheses, and warnings against unsafe shortcuts.

When adding custom runtime state, document whether it is battle-only, day-only, session-only, or persisted. Do not ship long-lived state without a save/load or deterministic recomputation plan.

Do not add unconditional hot-path logs. Combat, damage, selected-HUD, turn-queue, spellbook, and construction UI logs must be diagnostic-gated.

Do not add special-case fallback behavior to hide missing symbol resolution. If symbols are missing, fail closed and log behind diagnostics.

## Implementation packetization update - June 13, 2026

This section supersedes earlier "likely law index" wording. Implementation agents must treat unconfirmed native surfaces as probe prerequisites, not as implementation facts.

### Confirmed generator and override facts

| Fact | Confirmed implementation detail |
|---|---|
| Override directory | `custom_factions/law_overrides/<factionSid>.json` |
| Override root key | `lawOverrides` |
| Supported override keys | `enabled`, `iconKey`, `nameText`, `descriptionText`, `parametersPerLevel`, `notes` |
| Override lookup keys | full law SID or plain string index |
| Override parameters | must already be native `parametersPerLevel` row shape; there is no override DSL conversion |
| Generated law text target | `Lang/english/texts/factionLaws.json` |
| Stale law text target | `Lang/english/texts/fractionLaws.json` is not the active target |
| Cooldown row correction | generator row `34` is the current spell-cooldown scaffold, not row `31` |

### Source-of-truth law family index table

| Family | Confirmed or packet index policy |
|---|---|
| Hero sight radius | proposed row `2`; verify against generated donor row before gameplay work |
| Hero primary-stat training | proposed row `6`; verify against generated donor row before gameplay work |
| Counterattack doctrine | proposed row `13`; verify against generated donor row before gameplay work |
| Spell school access | confirmed generator rows `15` and `27` |
| Melee and ranged formations | proposed rows `18` and `19`; verify against generated donor row before gameplay work |
| Gold income percent | proposed row `21`; verify against generated donor row before gameplay work |
| Morale and morale triggers | proposed rows `22` and `25`; verify against generated donor row before gameplay work |
| Extra construction | confirmed generator row `28` |
| Astrology/calendar income | confirmed generator row `33` |
| Spell cooldown modifier | confirmed generator row `34` |

Unit/tier law indices vary by donor family and must not be assumed globally: `human` uses `4,10,11,17,23,24,30`; `nature` uses `5,6,10,16,22,23,27`; `dungeon` uses `4,10,11,18,19,25,31`; `undead` uses `4,5,10,11,18,19,23`; unlisted donors currently fall back to `human`.

### Implementation packet template

Every law implementation packet must include:

| Packet field | Required content |
|---|---|
| Goal | Player-visible mechanic and why it belongs to this faction identity. |
| Source law IDs | Exact `fraction_law_homm3_<faction>_<index>` IDs and rank count. |
| Rank behavior | Full non-cumulative rank behavior; rank 2/3 must include any lower-rank effect that should persist. |
| Files to touch | Generator/override/runtime/docs files, limited to the packet scope. |
| Symbols to add | `GameSymbols` groups and exact native fields/methods, or the probe that must discover them. |
| Native probes required | Read-only bridge or volatile probes needed before mutation. |
| Runtime hook points | Exact proven gameplay events/state owners, not UI surfaces. |
| State/idempotence | Battle-only, day-only, session-only, persisted, or deterministic recompute; include duplicate-call keys. |
| Diagnostic flags | Family-specific flag names; no unconditional hot-path logs. |
| Acceptance proof | Concrete proof that real state changed, not only UI. |
| Fail-closed behavior | What happens when classification, symbols, or state reads fail. |
| AGENT_REFERENCE update | Findings, failed probes, and unsafe shortcuts to record after implementation. |

### First packet now implemented

The first safe data packet has been applied through `custom_factions/law_overrides/*.json`:

| Packet | Status |
|---|---|
| Native school access | Implemented for Castle, Cove, Dungeon, Fortress, Rampart, Inferno, and Necropolis where the desired school row is exact. Tower, Conflux, and Stronghold remain packet/probe work because their desired behavior is not exact static school access. |
| Castle construction baseline | Implemented as `Civic Engineers` with native `constructionDailyLimit([1])`. |
| Astrology income | Implemented for all factions with native `astrologyExp([250/500/750, 0.0])`; faction-specific omen/calendar behavior remains runtime packet work. |
| Shared runtime scaffold | Implemented as diagnostic-only `Homm3CustomFactionLawRuntime`; it parses known law IDs, classifies known families, and logs startup readiness only behind `homm3_custom_faction_law_diag.flag`. Active side/faction/law/rank reads remain a prerequisite probe packet, not implemented gameplay. |

### Probe-only prerequisite packets

Before custom gameplay implementation, create proof packets for these surfaces:

| Probe packet | Blocks |
|---|---|
| Active law/rank read | all runtime law families; not implemented by the first diagnostic scaffold |
| Damage mutation | training, counterattack, formations, morale, calendar |
| Construction validation/cost/commit | extra construction |
| Spell cast/cooldown/cast gate | spell school and cooldown laws |
| Resource grant/reward commit | gold/economy laws |
| Morale trigger/failure | morale laws |
| Counterattack execution | counterattack laws |
| Corpse logical state/consumption | Necropolis laws |
| Gating/summon temporary identity | Inferno laws |
| Warcry real execution/cooldown | Stronghold laws |
| Avenger mark state | Rampart laws |
| Elemental family mapping | Conflux laws |
| Focus mutation/event | Cove laws and selected Tower/Rampart variants |

### Explicit not-first packets

Do not implement these before their probes and lower-risk packet predecessors are complete: Tower spellbook reuse, Conflux dynamic school/cooldown mapping, Necropolis corpse fuel, Inferno sacrifice/gating economy, Stronghold Warcry cooldowns, turn-order-changing speed buffs, and any persistent construction-token or mature-dwelling state.
