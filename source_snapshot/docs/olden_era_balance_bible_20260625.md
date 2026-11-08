# Olden Era Unit Balance Bible

Status: source-validated static read, runtime-unvalidated.

Primary data source: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`

Primary Core SHA-256: `C3D669163FE4BAB1FCC582326EDB6AA45F92CB546998957F27012F61E4C2871F`

Static extraction date: 2026-06-25.

## Scope

This document describes the balance philosophy visible in the current installed Olden Era unit data. It uses unit logic rows from `DB/units/units_logics`, card-facing ability rows from `DB/units/units_views`, English text tokens from `Lang/english/texts/units*.json`, and the growth cross-check in `DB/objects_logic/hires/barracks.json`.

The vanilla scope is every non-`h3_` unit row in the installed Core. HoMM3 imported/custom units are intentionally excluded by both path and SID prefix. The parsed set contains 152 vanilla rows:

- 127 town-faction rows: six native factions with seven regular unit lines, each normally having base, upgraded, and alternate-upgraded rows, plus the Demon `lava_larva` special row.
- 25 neutral or special rows, including the neutral dragon chain and tier-8 avatar-style rows.

Growth values were not present in the unit logic rows themselves. They are stored as `weeklyIncrement` in `DB/objects_logic/hires/barracks.json`, with no growth row found for `avatar`, `avatar_nature`, `avatar_unfrozen`, `dragon`, `dragon_upg`, `dragon_upg_alt`, `gnat`, `lava_larva`, `lich_dragon`, `peasant_normal`, or `undead_peasant`. The philosophy read therefore treats `squadValue`, gold/resource cost, combat stats, attack type, passive count, and card-facing abilities as the primary static budget signals, with growth as a secondary economy input rather than a complete tier-wide column.

Ability data is split across several UI-facing fields: every parsed row has `passives`, while active or conditional power also appears in `abilities`, `alternativeAttacks`, `aura`, `conditionalPassives`, and `globalPassives`. When this document refers to active ability pressure, it means the visible `abilities` list unless otherwise stated; the tier philosophy still considers the broader card rule package.

This is the active deployed Core, not a clean upstream Steam baseline comparison. If an overlay changed non-HoMM3 rows, this document reflects the current installed truth.

## Global Design Rules

1. Tier is a budget band, not a fixed role. Each tier contains melee, ranged, long-reach, flyer, defensive, control, and support units. The tier defines expected impact; faction identity defines how that impact is delivered.
2. Cost mostly follows `squadValue`. Gold cost rises predictably with tier, while tier 7 regular faction capstones start adding rare resources.
3. Base units establish the line's job. The standard upgrade usually makes that same job more reliable. The alternate upgrade usually changes the job by trading defense for damage, speed for durability, or raw stats for a sharper mechanic.
4. Mechanics scale faster than raw stats. The higher the tier, the more of the unit's budget sits in passives, active abilities, targeting patterns, immunity, regeneration, no-counter attacks, or control effects.
5. Ranged units pay for safety. They frequently have lower speed, HP, or melee resilience unless they are explicitly given `Duelist`, `Sharpshooter`, `Nimbleness`, `Blink`, or long-reach behavior as part of their role.
6. Neutral units are not balanced as symmetrical town peers. They often sit at round-number squad values and costs, and many behave like encounter, reward, or scenario pieces.
7. Tier 8 is not a normal recruit tier. It contains special neutral/avatar rows and should not be used as a standard faction balance benchmark.

## Tier 1: Identity Seeds

Static band, regular faction bases: squad value 29-93, median 65; gold 35-115, median 82.5; HP 6-12; attack 2-4; defense 1-4; max damage 3-5.

Tier 1 units are not just weak versions of later units. They are the cheapest way for each faction to state its combat grammar:

- Human `esquire` is a durable defensive baseline with ranged resistance.
- Undead `skeleton` is deliberately cheap and fragile, establishing mass and attrition.
- Nature `elf_tracker` is already a ranged/parry identity piece, so it sits high in the tier budget.
- Demon `trick_demon` uses long reach and anti-strong-target pressure instead of normal frontline value.
- Dungeon `trogl` is a low-stat melee chassis that becomes poisonous or counter-oriented through upgrades.
- Unfrozen `lesser_eldritch` is a flying magical body with active summoning identity even at tier 1.

The tier is balanced by keeping most units to one main combat promise. Upgrades add one extra sentence to that promise: double strike, ranged conversion, poison, anointed defense, or a summon variant. If a tier 1 unit has more tactical reach, it pays through lower HP, lower defense, or lower damage consistency.

Design takeaway: tier 1 should introduce faction identity, not solve whole battles. Its specials should be readable and narrow.

## Tier 2: First Tactical Choices

Static band, regular faction bases: squad value 85-144, median 106.5; gold 100-165, median 122.5; HP 8-18; attack 3-6; defense 0-4; max damage 4-6.

Tier 2 is where basic identity becomes an actual tactical decision. Active ability pressure rises, and upgraded/alternate rows average roughly one active ability per row. Ranged and long-reach pieces are common, but the tier still leans melee overall.

The designers use this tier to introduce battle verbs:

- Demon `locust` is early tempo and double-strike pressure.
- Dungeon `assassin` introduces blink, weak-spot pressure, stealth/control upgrades, and high initiative.
- Human `crossbowman` is the safe ranged teaching unit: double shot, sharpshooter, and piercing tools live here.
- Nature `twinkle` is mobile healing/leeching pressure with flyer movement.
- Undead `flicker` adds flying attrition and morale/fear pressure through Wight/Wraith identity.
- Unfrozen `unfrozen_cultist` is early long-reach control, built around abyssal debuffs.

Tier 2 upgrades do not merely add stats. They specialize the base: standard upgrades generally increase reliability, while alternate upgrades often become more aggressive or more disruptive.

Design takeaway: tier 2 is the first tier where units can ask the player to make a tactical choice beyond target selection.

## Tier 3: The First Real Board Rules

Static band, regular faction bases: squad value 110-233, median 197.5; gold 120-255, median 215; HP 14-45; attack 4-8; defense 6-11; max damage 5-9.

Tier 3 begins the shift from "unit has a trick" to "unit changes how nearby pieces play." Passive counts climb sharply on upgrades, and the tier introduces counter economy, durable bodies, area patterns, flyers, and punish-on-hit effects.

Faction examples:

- Human `griffin` is built around flight and retaliation volume; its standard upgrade pushes this to extreme counter reliability.
- Nature `ent` is a slow, high-HP embodiment that uses area attack, cover, and earth awaken mechanics.
- Demon `wasp` is fast flying pressure, with one upgrade leaning nest-protector and the alternate leaning initiative and piercing damage.
- Dungeon `blade_dancer` is ranged attrition with stacking cuts rather than raw durability.
- Undead `pet` is a lower-budget undead bruiser that adds pack and wound/protection identity through upgrades.
- Unfrozen `frostworm_rider` combines melee, cold, plow-through movement pressure, and breath-style actives.

Design takeaway: tier 3 is the first tier where a unit can reshape local board geometry or retaliation math. This is where a faction's midgame posture starts to become visible.

## Tier 4: The Midgame Pivot

Static band, regular faction bases excluding the special `lava_larva` row: squad value 244-453, median 347; gold 240-450, median 345; HP 30-50; attack 11-12; defense 10-12; max damage 9-14.

Tier 4 is the hinge tier. Regular units move from modest stats to full role definition, and the active ability average jumps above one active per base row. This is where the game starts asking whether a unit is a caster, bruiser, board controller, disposable special, or faction engine.

Important patterns:

- Demon `jaw` is an adaptation unit: the same body can choose attack, defense, or speed pressure.
- Demon `lava_larva` is a special outlier: a cheap tier-4 suicide/fire utility row, not a normal line benchmark.
- Dungeon `minos` is a morale/bravery bruiser whose upgrades split into parry/control or aggression.
- Human `lightweaver` is a ranged support/damage caster line.
- Nature `aqualotl` is a water embodiment with ranged pressure, blink, awaken mechanics, retreat, and control.
- Undead `graverobber` is poison/decay economy and battlefield attrition.
- Unfrozen `eldritch_flyer` keeps the faction's summon/control identity while adding fast flying threat.

Neutral tier-4 rows are premium set pieces around fixed 550 squad value and 600 gold cost. They are not tuned like a town line; they act like compact encounter identities.

Design takeaway: tier 4 is where a faction line can become an engine. New designs should not treat this as "tier 3 with larger numbers"; it is the first heavy specialization tier.

## Tier 5: Specialist Power

Static band, regular faction bases: squad value 339-908, median 623.5; gold 320-850, median 585; HP 45-85; attack 12-18; defense 12-17; max damage 14-40.

Tier 5 is the specialist tier. Its units are expensive enough to carry a plan but still common enough to define mid-to-late battles. The role mix is almost evenly split between melee, ranged, and long-reach/ranged-adjacent models.

Faction examples:

- Demon `godslayer` is a high-variance predator: extreme damage band, anti-tier identity, and aggressive actives.
- Dungeon `medusa` is a premium ranged/control unit, with sculptor/queen variants leaning into petrification, countershot, and ranged quality.
- Human `sunlight_cavalry` is the classic high-speed impact piece: jousting, piercing, morale pressure, and charge.
- Nature `druid` is long-reach spell pressure and utility, built around mushroom/bees/protection effects.
- Undead `lich` is cheaper for the tier but compensates through death manipulation, area strike, and anti-recovery identity.
- Unfrozen `succubus` is ranged denial: abilities, Focus, idle-mind/passivity control, and Nimbleness/Duelist variants.

Upgrades at this tier become meaningfully more expensive and usually add a second active or a major passive. Alternate upgrades often have more passive text than standard upgrades, which indicates a design bias toward alternate rows being sidegrades with more conditional power rather than simple stat upgrades.

Design takeaway: tier 5 should be allowed to be weird, but its weirdness needs a clear combat job. This tier rewards sharp roles more than generic stat inflation.

## Tier 6: Late-Game Anchors

Static band, regular faction bases: squad value 952-1481, median 1407.5; gold 800-1300, median 1200; HP 75-135; attack 19-24; defense 18-24; max damage 14-30.

Tier 6 units are anchors. They are not just large bodies; they are durable pieces that stabilize a faction's late-game board state. Upgrades often jump to about 1.6x base squad value, and both standard and alternate rows add dense passive packages.

Faction examples:

- Demon `olgoi` is a high-HP blink/eater line; its alternate becomes ranged/area while the standard becomes a devouring bruiser.
- Dungeon `hydra` is no-counter sweeping area pressure, later adding regeneration, poison, or more aggressive damage.
- Human `inquisitor` is resistance, armor, and elite melee control.
- Nature `qilin` is an air embodiment built around speed, lightning, defense/attack conversion, and Focus generation in one upgrade.
- Undead `avatar_of_war` is dread/war pressure with double strike or death-stare identity.
- Unfrozen `arbitrator` is a ranged command/control platform with repositioning and fear/switch-place tools.

Neutral tier-6 rows are strong but specialized: `coatl` is fast flying resistance, `dragon_hunter` is anti-dragon melee, and `mech_guard` is a construct ranged defender.

Design takeaway: tier 6 should be a reliable anchor with faction-specific leverage. A tier 6 unit can be slow or specialized, but it must justify its price by changing combat planning around itself.

## Tier 7: Capstones

Static band, regular faction bases: squad value 1875-4620, median 3735; gold 1200-3000, median 2450; HP 150-275; attack 22-30; defense 20-30; max damage 25-75.

Tier 7 units are faction theses. They add rare resources, heavy stat budgets, and mechanics that can define the endgame. Most are flying or otherwise positionally exceptional. Passive packages are dense, and active ability count is high on both standard and alternate upgrades.

Faction examples:

- Demon `hive_queen` is a command/assimilation capstone with contamination, hive identity, and protector/vanguard upgrade split.
- Dungeon `black_dragon` is the classic dragon capstone: high mobility, breath/reach, magic immunity, inner flame, and dominance tools.
- Human `angel` is a ranged flying embodiment with reflection, perfection, and upgrade-side choice between offense and aura/defense.
- Nature `phoenix` is an elemental fire capstone: flying sweep, awakening, resurrection/immortality or explosive fire identity.
- Undead `vampire` is comparatively cheaper but built around sustain, flying, swift/no-counter behavior, and blood utility.
- Unfrozen `unspeakable` is the abyssal control capstone: summons, insanity, area attacks, and mind control.

Neutral tier-7 rows show encounter/capstone tuning rather than town symmetry. The dragon chain is a high-cost neutral benchmark, while `sentinel` is an enormous fixed-stat special with multiple named ways.

Design takeaway: tier 7 should feel unfair in a faction-specific way, because the balancing force is cost, rarity, and opportunity cost rather than simplicity.

## Tier 8: Special Rows, Not a Recruit Standard

Tier 8 contains `avatar`, `avatar_nature`, `avatar_unfrozen`, and `lich_dragon`. These rows do not follow the normal faction ladder. The avatar rows have 1 HP and special movement/resistance packages, while `lich_dragon` is a special dragon/undead-style row.

Design takeaway: do not use tier 8 as a normal power budget reference. Treat it as scenario, summon, or special-system space unless a current runtime surface proves otherwise.

## Complete Tier Inventory

All regular town lines below expand to base, standard upgrade, and alternate upgrade unless called out as special. Neutral rows are single rows unless an upgrade chain is explicitly listed.

| Tier | Regular town lines | Neutral and special rows |
| --- | --- | --- |
| 1 | `trick_demon`, `trogl`, `esquire`, `elf_tracker`, `skeleton`, `lesser_eldritch` | `gnat`, `pixie` |
| 2 | `locust`, `assassin`, `crossbowman`, `twinkle`, `flicker`, `unfrozen_cultist` | `halfling`, `peasant`, `peasant_normal`, `undead_peasant` |
| 3 | `wasp`, `blade_dancer`, `griffin`, `ent`, `pet`, `frostworm_rider` | `animated_armor`, `gorilla` |
| 4 | `jaw`, `minos`, `lightweaver`, `aqualotl`, `graverobber`, `eldritch_flyer`; special `lava_larva` | `kitten_horn`, `primal_remnant`, `star_child`, `unicorn` |
| 5 | `godslayer`, `medusa`, `sunlight_cavalry`, `druid`, `lich`, `succubus` | `fairy_dragon`, `giant_frog` |
| 6 | `olgoi`, `hydra`, `inquisitor`, `qilin`, `avatar_of_war`, `arbitrator` | `coatl`, `dragon_hunter`, `mech_guard` |
| 7 | `hive_queen`, `black_dragon`, `angel`, `phoenix`, `vampire`, `unspeakable` | `dragon` -> `dragon_upg` -> `dragon_upg_alt`, `sentinel` |
| 8 | none | `avatar`, `avatar_nature`, `avatar_unfrozen`, `lich_dragon` |

## Practical Use For Future Balance Work

When adding or changing a unit, choose the tier budget first, then choose exactly one primary job:

- Tier 1: readable identity and one narrow hook.
- Tier 2: first real tactical decision.
- Tier 3: local board rule or retaliation/mobility pressure.
- Tier 4: midgame engine or heavy specialization.
- Tier 5: specialist power piece.
- Tier 6: late-game anchor.
- Tier 7: faction thesis and endgame payoff.
- Tier 8: special-system space, not a normal recruit budget.

The strongest native-friendly balancing pattern is to keep the base row simple, make the standard upgrade a reliable extension, and make the alternate upgrade a role pivot with explicit costs. Avoid adding broad fallback behavior or hidden donor-style identity changes; this roster is balanced through visible card rules and explicit stat/cost tradeoffs.
