# Factory faction ability: Logistics Network (design)

Status: spec from the user (2026-11-15/16), numbers and implementation pending. Replaces
Split Assembly (`skill_faction_homm3_factory`, `Homm3FactorySplitAssemblyRuntime.cs`).

## Core rules

- A hero with the skill must **visit** a flagged, Factory-player-owned building in person and pay
  resources to build an enhancement (skills are hero-bound, not faction-bound).
- A building can hold any number of built enhancements, but only one is active at a time
  (user, 2026-11-16). Each enhancement has 3 levels, one per skill level (Basic / Advanced / Expert).
- Upgrade Center (user, 2026-11-16): a per-building marker that a hero with the skill has
  visited it, at that hero's skill level (a higher-skill visit raises it; lost on capture). It
  lets the player build or upgrade that building's own enhancements remotely from the network
  viewer, up to the marker's level. It affects nothing else on the network. Remote construction
  costs the same, takes a day, and becomes active at the start of the next day; a hero on site
  still builds immediately.
- Without an Upgrade Center, building or upgrading needs the hero on site; switching which built enhancement is active is
  done remotely from the logistics management UI (network viewer), no hero needed. One switch per building per week; it resets at the start of each week (user, 2026-11-16).
  A switch takes effect at the start of the next day; until then the old enhancement stays active
  (stops same-day mass hub swaps for long-range remote hiring).
  Building or upgrading an enhancement on site takes effect immediately (user, 2026-11-16).
- All upgraded buildings the player owns form one **logistics network**, whoever built them.
- Enemy capture destroys all of the building's enhancements permanently (it is not inherited like a town);
  it must be rebuilt after recapture.
- Enhancements can be demolished for free; no refund. (With unlimited built enhancements,
  demolishing is only needed to clear one out.)
- Only buildings with recurring revenue or units count. One-time or weekly-visitable objects
  are not part of the network.

## Costs (rules; table pending research)

- Based on vanilla town buildings with similar effects.
- Level 1: gold, wood and ore only.
- Every enhancement also costs 10 dust at L2 and 20 dust at L3, on top of its normal cost.
- Levels 2-3: add an advanced resource. Dwellings: follow that unit's town-dwelling
  construction cost. Mines: an advanced resource the mine itself does not produce (user, 2026-11-16).
- Food Distribution Center price varies by unit, aligned with the unit's town dwelling cost.

## Resource buildings (mines etc.)

| Enhancement | Effect |
|---|---|
| Byproduct Processing | Small extra gold income. L2 and L3 also raise the mine's own output; L3 = 2x the normal amount. Extra output is pooled per resource across all such buildings and rounded down (two mines each making +0.5 crystal give +1 crystal per day). |
| Export Office | Gold income = 2x the player's current market sell rate for the mine's daily output (stated in the description); the mine stops producing its own resource. Below a gold mine except at L3. |
| Logistics function (per resource) | The resource is no longer granted daily; it feeds the network instead (table below). |
| Logistics Hub | Building works unchanged; refreshes 33/66/100% of the range a route passing through has spent. |

Gold mines join the network (they receive other buildings' bonuses) but can only build the Logistics Hub.

### Logistics functions

| Resource | Name | Network effect |
|---|---|---|
| Wood | Warehouse | Other logistics enhancements cost 20/40/60% less to build or upgrade. |
| Ore | Rail Station | Raises the player's global logistics level by +1 per Rail Station level, additive across stations (one full station: level 1 -> 4, range 400 MP); also a full Logistics Hub. |
| Crystal | Power Station | Adds +1 / +2 / +3 effective levels to every enhanced building in its range (user, 2026-11-16). The extra levels continue that enhancement's own per-level step (Export Office 2x/3x/4x -> 7x with a maxed station). Does not affect other Power Stations or unenhanced buildings. Multiple stations add their levels together. A powered Material Synthesizer still multiplies a powered Export Office / Mercenary HQ (maxed: 7x x 3 = 21x market value, ~5000 gold/day with 5 markets; user-approved 2026-11-16). |
| Mercury | Material Synthesizer | Raises the exchange rate of conversion enhancements (resource/units into another resource/gold), including Export Office and Mercenary Headquarters: L3 = 2x, 3x when fully powered by crystal. Also counts as an extra market for each town in range, capped at its level. |
| Gems | Arcane Manufactory | + [level] to all stats of heroes in range; astrology points per town in range, capped at its level; converts a share of dwelling units to a random upgraded variant when produced each week. 100% needs 6 levels' worth (= full Power Station powering a full Manufactory). |

## Creature dwellings

| Enhancement | Effect |
|---|---|
| Food Distribution Center | +33/66/100% weekly units. L1/L2 from next week; L3 immediately (units appear for hire now). |
| Housing Office | Units hired here cost 20/40/60% less. |
| Rail Network | Hire remotely; units are delivered to a town (L1-2) or a town or hero (L3) within logistics range. Routes from this dwelling get +0 / +1 / +2 logistics level (user, 2026-11-16: extra range for this dwelling only). |
| Mercenary Headquarters | No new units each week; instead gold = 1x/2x/3x the purchase price of the units it would have produced. |
| Support Hub | No new units here; every other owned external dwelling in its logistics range produces +15/30/45% weekly units (owner 2026-11-16). Hubs add together; the extra comes from native growth (adds with a Food Distribution Center, does not multiply it) and is converted by an Arcane Manufactory or a Mercenary HQ like other produced units. |
| Logistics Hub | As above. |

## Logistics range

- Measured like hero movement, but terrain penalties don't apply; bonuses such as roads do.
- Tiles controlled by neutral stacks and unexplored tiles are not pathable (killing a neutral can open routes).
- Range of every network building = logistics level x basic range. Basic range = half a typical
  hero's default daily movement (vanilla base 200 MP/day, so 100 MP: ~10 tiles without terrain
  penalty, ~13 on road). Upgrading a building's own enhancement level adds no range.
- Logistics level is player-wide, starts at 2 (one full hero day, owner 2026-11-16), and is raised
  only by Rail Stations, each level adding half a day.
  Connections should take effort.
- Supplies are not used up; the best route is computed when the panel opens and on events that
  need it (turn start, recruiting from a dwelling, ...).
- Hub refresh example: a route reaches a hub after spending 50% of its range; an L1 hub refreshes
  0.33 x 50% = 16.5%, so the route continues with floor(50% + 16.5%) = 66% remaining.

## Hero subskills (owner 2026-11-16)

Advanced rank (pick one):

| Subskill | Effect |
|---|---|
| Mobile Command Center | Owned mines and dwellings within this hero's logistics range can be built/upgraded remotely up to the hero's skill level, as with an Upgrade Center (lands next day). |
| Freight Haulers | Landscape movement penalties removed (-100%, like other such subskills). |
| Survey Office | Factory creatures on native terrain deal 10% more damage and take 10% less. |

Expert rank (pick one):

| Subskill | Effect |
|---|---|
| Night Shift | +20 mana restored per day. |
| Supply Caravan | The hero counts as a level 3 Logistics Hub: routes passing its tile refresh all spent range. |
| Trade Contracts | The hero counts as 2 additional Marketplaces for trading prices (and for Export Office value). |

## Network viewer

- A free spell in every Factory hero's spellbook opens a pan/zoom view of the network.
- Style: Olden Era UI, with neon glow for path elements only.
- Shows the real map tiles (square grid, 8 neighbours); routes step tile to tile.
- Lines are thin and coloured by originating building; routes sharing tiles run as parallel
  offset lines, not merged into one (user, 2026-11-16). Red stays reserved for cut routes and blocking stacks.
- Paths: bright pulsing arrows moving along lines from each building to the other buildings, and
  where relevant to towns and heroes.
- Routes that run out of range: a red X where they end, with red text naming the source
  building's enhancement type and the target, and the extra range needed
  (e.g. "Export Office (Gem Pond) -> Castle Town: +3 range needed"). Multiple cut-short routes from the same source must format and stack cleanly.
- Enemy stacks whose defeat would create new links: glowing red highlight with a note.

## Upgrade panel

- Opens on visit; Olden Era style like the other custom panels (War Captives, Elemental Fusion).
- UI mockups need user approval before install.

## Proposed numbers (draft, not yet approved)

Sources: installed Core.zip and decompiled formulas; research notes in
`V:/olden_port_work/factory_logistics/pricing_research.md`.

Vanilla anchors: mines give 1000 gold / 2 wood or ore / 1 rare per day. Market base value is
250 per basic and 500 per rare, sold at /4 with one town market, improving to /1 at 7 markets.
Bank 2500 g + 5 wood + 5 ore = +1000 gold/day. Wall L2/L3 = +50/+100% town growth. Hero base
movement 200 MP/day; tile 10 native, 14-18 off-native, 7-8 on road.

### Advanced resource for levels 2-3

- Mines (cycle, never the mine's own output): crystal -> mercury, mercury -> gemstones,
  gemstones -> crystal; wood, ore and gold mines -> crystal (Factory's silo rare).
- Dwellings: the largest rare in the unit's level-1 town-dwelling cost, else the rare in its
  upgraded dwelling, else dust at double quantity (Factory tiers 1, 2, 3, 5 have no rare; user-approved).
- Wood discount (Warehouse) applies to these costs.

### Mine enhancement costs (R = advanced resource above)

| Enhancement | L1 | L2 | L3 |
|---|---|---|---|
| Byproduct Processing | 1000 g + 3 wood + 3 ore | 1500 g + 2 R | 2000 g + 4 R |
| Export Office | 1000 g + 5 wood | 1500 g + 2 R | 2500 g + 3 R |
| Warehouse (wood) | 1000 g + 5 wood + 2 ore | 1500 g + 2 crystal | 2000 g + 3 crystal |
| Rail Station (ore) | 2000 g + 5 wood + 10 ore | 3000 g + 3 crystal | 4000 g + 5 crystal |
| Power Station (crystal) | 2500 g + 5 wood + 5 ore | 3500 g + 4 mercury | 5000 g + 6 mercury |
| Material Synthesizer (mercury) | 1500 g + 5 wood + 5 ore | 2500 g + 3 gems | 3500 g + 5 gems |
| Arcane Manufactory (gems) | 3000 g + 5 wood + 5 ore | 4000 g + 4 crystal | 6000 g + 6 crystal |
| Logistics Hub (any, incl. gold) | 1000 g + 3 wood + 3 ore | 1500 g + 2 R | 2500 g + 3 R |

### Dwelling enhancement costs

D = the unit's level-1 town-dwelling gold cost (vanilla tier average for neutral units); t = tier;
b = ceil(t/2)+2 wood and ore at L1; q = ceil(t/2)+1 advanced resource at L2, 2q at L3; gold
rounded to 250.

| Enhancement | L1 | L2 | L3 | Total gold |
|---|---|---|---|---|
| Food Distribution Center | 0.25D + b wood + b ore | 0.30D + q R | 0.45D + 2q R | 1.0D |
| Housing Office | 0.20D + b + b | 0.25D + q R | 0.35D + 2q R | 0.8D |
| Rail Network | 0.20D + b + b | 0.25D + q R | 0.45D + 2q R | 0.9D |
| Mercenary Headquarters | 0.25D + b + b | 0.35D + q R | 0.50D + 2q R | 1.1D |
| Support Hub | 0.25D + b + b | 0.30D + q R | 0.45D + 2q R | 1.0D |
| Logistics Hub | as mine hub | | | |

Example, Factory Food Distribution Center: T1 500 g + 3/3 -> 500 g + 4 dust -> 750 g + 8 dust;
T7 3750 g + 6/6 -> 4500 g + 5 gems -> 6750 g + 10 gems.

### Effect values

| Item | Draft value |
|---|---|
| Byproduct Processing | +100 / +200 / +350 gold per day; own output +0 / +50% / +100% (pooled fractions, floored per resource) |
| Export Office | 2x / 3x / 4x the owner's town sell rate for the mine's daily output (user, 2026-11-16), then the Synthesizer multiplier. Gold per day: 1 market 250 / 375 / 500; 3 markets 333 / 500 / 667; 5 markets 500 / 750 / 1000; 7+ markets 1000 / 1500 / 2000 (wood/ore and rare mines alike). No cap. |
| Warehouse | -20 / -40 / -60% logistics enhancement costs (best one applies, not stacking) |
| Power Station | +1 / +2 / +3 effective levels to enhanced buildings in range, extrapolating each enhancement's per-level step; stations add together; caps below |
| Material Synthesizer | conversion multiplier x1.33 / x1.66 / x2, x3 at L3 when fully powered by crystal; +1 market per town in range, max [level] towns |
| Arcane Manufactory | +[level] all hero stats in range; astrology +250 per day per town in range, max [level] towns; converts 1/6 of produced units per effective level (L3 + maxed Power Station = 6 levels = 100%) |
| Mercenary Headquarters | 1x / 2x / 3x the price of the units it would have produced; weekly value capped at the town-tier weekly value (vanilla neutral dwellings grow up to 100/week) |
| Basic range | 100 MP per logistics level |

### Effective levels with a maxed Power Station (+3), straight-line extrapolation

| Enhancement | L1 / L2 / L3 | L3 + 3 levels (L6) | Proposed cap |
|---|---|---|---|
| Byproduct Processing | +100 / +200 / +350 g, output +0 / +50 / +100% | +~800 g, output +250% | none |
| Export Office | 2x / 3x / 4x | 7x | none |
| Material Synthesizer | x1.33 / x1.66 / x2 | x3 (matches the spec's "3x fully powered") | none |
| Arcane Manufactory | +1 / +2 / +3 stats, 1/6 per level | +6 stats, 100% conversion, 6 towns | conversion 100% |
| Food Distribution Center | +33 / +66 / +100% | +200% | none |
| Housing Office | -20 / -40 / -60% | -120% | proposed -90% |
| Mercenary Headquarters | 1x / 2x / 3x | 6x | none |
| Support Hub | +15 / +30 / +45% to other dwellings in range | +90% | none |
| Warehouse | -20 / -40 / -60% | -120% | proposed -90% |
| Rail Station | +1 / +2 / +3 logistics level | +6 (range 700 MP; user-approved) | none |
| Logistics Hub | 33 / 66 / 100% refresh | 200% | 100% |
| Rail Network | +0 / +1 / +2 own-route logistics level; town / town / town or hero | +5 own-route level | none |

## Implementation notes (feasibility, 2026-11-16)

Full study: `V:/olden_port_work/factory_logistics/feasibility.md`. Static evidence only, nothing
run in game.

- Easy: mine income (prefix/postfix on the mine's OnStartDay), dwelling growth (dwelling
  OnStartWeek), hire discount (per-dwelling extraCharge, below-zero values unchecked),
  visit and capture pins (Plunder already pins the mine ones), remote hire to a hero
  (Homm3PartyArmyWriter), viewer spell (clone the Conflux free spell), minimap render texture.
- Hard: save persistence per map object (proposal: one infinite carrier buff per side packing
  object id / type / level; needs a save-load-capture test before paid enhancements ship);
  neutral guard zones and passability (pin the native planner's grid); market count is computed
  outside the exchange-rate function; astrology is per side, not per town.
- Visiting a dwelling opens the native hire window; ours must open alongside it or after it.
- Build order: persistence + pins -> mine panel and effects -> dwelling effects -> range engine
  -> range consumers (stat buffs, remote hire) -> viewer -> markets, astrology, unit conversion.

## Open questions

- Astrology is player-wide in the engine, so "points per town" becomes player astrology per
  networked town.

## Player-facing UX (owner 2026-11-16, candidate items 1-24)

- One vocabulary: range in days of travel (1 day = 200 MP), "Upgrade Center N" / "Command Center N", "Powered level",
  "Switch", "Remote build", and a "Replaces output" / "Adds to output" tag on every enhancement.
- Viewer: first-open primer, "?" glossary, network totals bar, concrete effect numbers, hover before/after previews,
  range overlay (R), cut-route popup with reasons and fixes, To-do panel with filters, keyboard shortcuts, greyed Hire
  tab with reason, delivery target army/free slots, recommended first build, focus/centre from the build panel.
- Bulk remote recruitment: "Recruit all" (B) lists every hireable dwelling with -/+/Max, Max all, Hire all, total cost
  against resources; it loops the normal remote-hire path and stops at the first refusal.
- Adventure map: Ctrl+L opens the viewer (no text badges over buildings: removed at the owner's request); day-start digest; capture-loss notice;
  build panel after a capture; hint for heroes without the skill.
- Candidate list and remaining items 25-31: `docs/factory_logistics_ux_candidates.md`.
