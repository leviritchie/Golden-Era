# Heroes of Might and Magic: Olden Era mechanics reference for law-design agents

Last researched: 2026-06-12

Purpose: give agents a single reference point for designing custom faction laws without confusing three different things:

- `Confirmed game mechanic`: described by public sources or observed in local game data.
- `Law-table primitive`: directly present in current generated faction-law JSON.
- `Mod hook required`: mechanically sensible, but not directly expressible with current law-table primitives.

This document is not a balance guide. It is a sanity checklist for whether a proposed law makes sense in Olden Era before implementation.

## Source status

I attempted to find the community wiki the user mentioned, but current web searches did not surface a usable community-wiki page. Searches included combinations of `Heroes of Might and Magic Olden Era wiki`, `Olden Era Focus wiki`, `Murmuring Focus Olden Era`, and `Faction law points Olden Era`. Search results mostly surfaced press/review articles and Wikipedia pages.

Use these public sources until the community wiki URL is found:

- GamesRadar early-access review: https://www.gamesradar.com/games/strategy/heroes-of-might-and-magic-olden-era-review/
- GamesRadar developer preview: https://www.gamesradar.com/games/strategy/heroes-of-might-and-magic-olden-era-is-a-great-pleasure-and-a-great-responsibility-for-its-superfan-ceo-and-hes-governed-by-one-guiding-principle-heroes-is-for-everyone/
- GamesRadar Grove/Hive preview: https://www.gamesradar.com/games/strategy/im-usually-a-dungeon-disciple-in-heroes-of-might-and-magic-olden-era-but-after-2-hours-with-the-latest-build-im-feeling-oddly-fond-of-insects/
- PC Gamer early-access overview: https://www.pcgamer.com/games/strategy/heroes-of-might-and-magic-olden-era-isnt-a-reimagining-or-a-divisive-reinterpretation-its-just-a-brilliant-strategy-game/
- Wikipedia gameplay overview: https://en.wikipedia.org/wiki/Heroes_of_Might_and_Magic%3A_Olden_Era
- Russian Wikipedia gameplay overview: https://ru.wikipedia.org/wiki/Heroes_of_Might_and_Magic%3A_Olden_Era

Local implementation/data sources used for law primitives:

- `tmp/inferno_gating_rework/Core.zip`
- `DB/fractions_laws/fractions_laws_table_*.json` inside that zip
- `custom_factions/homm3_*.json` for custom-faction identity, not vanilla mechanics

Local law-table provenance for this pass:

- Archive: `tmp/inferno_gating_rework/Core.zip`
- SHA256: `12e183c1c73a4f59b90755a819f758d6f288d56ecbeedf5f92be02e46cbe938f`
- Size: `17487779` bytes
- Tables inspected:
- `DB/fractions_laws/fractions_laws_table_demon.json`
- `DB/fractions_laws/fractions_laws_table_dungeon.json`
- `DB/fractions_laws/fractions_laws_table_human.json`
- `DB/fractions_laws/fractions_laws_table_nature.json`
- `DB/fractions_laws/fractions_laws_table_undead.json`
- `DB/fractions_laws/fractions_laws_table_unfrozen.json`
- `DB/fractions_laws/fractions_laws_table_homm3_castle.json`
- `DB/fractions_laws/fractions_laws_table_homm3_cove.json`
- `DB/fractions_laws/fractions_laws_table_homm3_dungeon.json`
- `DB/fractions_laws/fractions_laws_table_homm3_fortress.json`
- `DB/fractions_laws/fractions_laws_table_homm3_rampart.json`
- `DB/fractions_laws/fractions_laws_table_homm3_tower.json`
- `DB/fractions_laws/fractions_laws_table_homm3_conflux.json`
- `DB/fractions_laws/fractions_laws_table_homm3_inferno.json`
- `DB/fractions_laws/fractions_laws_table_homm3_necropolis.json`
- `DB/fractions_laws/fractions_laws_table_homm3_stronghold.json`

Extraction pattern used for law primitive discovery:

```python
import json, zipfile, collections
from pathlib import Path

core = Path("tmp/inferno_gating_rework/Core.zip")
tables = [name for name in zipfile.ZipFile(core).namelist()
          if name.startswith("DB/fractions_laws/fractions_laws_table_")]
signatures = collections.Counter()

with zipfile.ZipFile(core) as zf:
    for table in tables:
        data = json.loads(zf.read(table).decode("utf-8-sig"))
        for row in data.get("array") or []:
            for level in row.get("parametersPerLevel") or []:
                for bonus in level.get("bonuses") or []:
                    params = bonus.get("parameters") or [""]
                    signatures[(bonus.get("type"), str(params[0]))] += 1
```

Do not treat the primitive list below as exhaustive for runtime mechanics. It is only the observed faction-law data surface in this archive.

## Core game structure

Olden Era is a turn-based strategy game split between adventure-map exploration and hex-grid tactical battles. Public sources consistently describe heroes recruiting armies, capturing resources and towns, building towns, leveling heroes, researching/casting spells, and fighting tactical battles.

Early-access vanilla factions named in public sources:

- `Temple`
- `Necropolis`
- `Grove`, previously referred to in previews as `Sylvan`
- `Dungeon`
- `Hive`
- `Schism`

Important design warning: do not assume our HoMM3 custom factions map one-to-one to these vanilla factions. Use vanilla mechanics as a vocabulary and constraint set, not as faction identity.

## Focus

Status: confirmed game mechanic.

Correction to prior mistake: Focus is a real Olden Era combat mechanic. Do not reject a law concept just because `focus` is not visible as a top-level faction-law JSON primitive.

Public evidence:

- GamesRadar early-access review describes hero commander attacks as supplementing army damage while Focus builds during battle and can be spent.
- GamesRadar Grove/Hive preview says Grove/Sylvan’s faction ability `Murmuring` boosts Focus points and frames Focus as one of Olden Era’s complex new systems.
- GamesRadar developer preview also describes Sylvan/Grove armies as focused on boosting Focus points in combat.

Agent rule:

- Treat `Focus` as part of Olden Era’s actual combat vocabulary.
- Separately verify whether a specific law can alter Focus through existing data, or whether it needs a runtime hook.
- A proposal like `Counterattacks generate 1 Focus` is game-mechanically sensible, but probably still needs implementation tracing to find the focus owner/storage and counterattack event surface.

Likely implementation tier:

- `Game mechanic`: yes.
- `Law-table primitive`: not yet proven from generated law tables.
- `Mod hook`: likely required for event-driven Focus gain such as on counterattack, on kill, on spell cast, or on taking damage.

## Faction laws

Status: confirmed game mechanic.

Public evidence:

- Wikipedia describes enacting faction laws as a new series mechanic that grants unique faction bonuses for a special currency.
- GamesRadar developer preview describes faction law points as part of deeper RPG development and says laws help express faction identity.
- PC Gamer says each faction has two law trees split into faction and army buffs. It gives examples: reducing recruitment costs, regular resource shipments, increasing specific units’ strength, and increasing the recruitment pool.

Current local law-table primitives observed in generated faction-law tables from the archive above:

- `sideRes`: daily resource income, including daily gold and rare resources.
- `sideOneTimeAddRes`: one-time resource grants.
- `sideStat resPercentIncrementSet`: resource income percentage.
- `heroStat`: hero stats such as `offence`, `defence`, `spellPower`, `intelligence`, `viewRadius`, `moral`, `magicSchoolSet`, `movementBonus`, `sideExpPerBonus`, and related values.
- `heroStatBattle magicCdBonus`: spell cooldown modifier in battle.
- `unitStat`: unit stat modifiers such as damage, HP, offence, defence, initiative, speed, morale, luck, damage modifiers, hero-stat-derived modifiers, summon bonus, crit, ability cost bonus, and modifier sets.
- `cityUnitsIncrement`: recruitment pool or creature growth.
- `constructionDailyLimit`: extra daily construction.
- `constructionDiscount`: construction cost changes.
- `astrologyExp`: astrology/insight progression.
- `battleSubskillBonus`: limited battle subskill hook observed in vanilla tables.

Agent rule:

- If a proposed law is expressible as one of these primitives, call it `law-native`.
- If it depends on a battle event, map object classification, per-turn trigger, target condition, Focus gain, corpses, gates, or custom faction marks, call it `hook-required`.

## Combat basics

Status: confirmed game mechanics.

Public evidence:

- Battles occur on hex grids.
- Units act in turn order; PC Gamer names initiative and speed as characteristics affecting turns.
- Heroes can cast spells and can perform attacks from the side of the battlefield.
- Units have basic attacks and spell-like special abilities.
- Public Russian overview says active abilities exist for all creatures and heroes.
- GamesRadar describes weaker neutral groups fleeing, with the player choosing whether to pursue or leave them.

Known useful mechanics for law design:

- `Focus`: hero attack resource that builds during battle and can be spent.
- `Initiative`: turn-order/tempo stat.
- `Speed`: movement/battle movement stat.
- `Morale`: high morale can grant extra action/turn behavior; PC Gamer mentions mixed-faction armies impose morale costs.
- `Luck`: exists in local law tables and traditional Heroes vocabulary, but use current game text before designing luck-specific laws.
- `Counterattacks`: counterattack state is surfaced in combat UI according to public overview, but mutable counterattack behavior such as extra charges, changed formulas, or event payouts must be traced before implementation.
- `Creature specials`: every unit can have active/special abilities; designing laws around ability use is game-sensible but usually hook-required.

## Magic and astrology

Status: confirmed game mechanics.

Public evidence from PC Gamer:

- Cities can build mage guilds.
- Mage guilds unlock random spells by tier.
- Heroes need to visit the city with the guild to receive those spells.
- Lower-tier spells can be learned broadly, but higher-tier spells require proficiency in specific schools.
- The Magic Observatory collects spells unlocked across cities.
- Spells can be upgraded using resources.
- New spells can be unlocked, limited to one per day, when the appropriate guild exists.
- Neutral spells are unlocked manually using `Insight`.
- `Insight` comes from generating enough astrology points.
- Heroes may need appropriate level to learn unlocked neutral spells.

Local law-table support:

- `heroStat magicSchoolSet`
- `heroStatBattle magicCdBonus`
- `astrologyExp`

Agent rule:

- Laws that grant magic-school access, spell cooldown modifiers, or astrology progress are law-native when expressed through the observed primitives above. Use `astrologyExp` specifically for astrology/Insight progression.
- Laws that trigger on a specific spell cast, stack buffs per cast, or modify a named spell’s behavior are hook-required unless a specific data route is found.

## Economy, construction, and recruitment

Status: confirmed game mechanics.

Public evidence:

- Towns and captured structures generate gold/resources daily.
- Buildings, unit recruitment, and unit upgrades require gold and secondary resources.
- Creature dwellings/generators produce units over time.
- PC Gamer says faction laws can reduce recruitment costs, grant regular resources, strengthen specific units, and increase recruitment pool.
- Olden Era has no population management and no broad diplomacy system; diplomacy is described as a secondary skill that allows recruitment of neutral units.
- A GamesRadar preview notes unique city structures. Examples: Hive structure grants visiting heroes +2 Attack; Necropolis structure transmutes other-faction creatures into similar-level Necropolis creatures.

Local law-table support:

- `sideRes`
- `sideOneTimeAddRes`
- `sideStat resPercentIncrementSet`
- `cityUnitsIncrement`
- `constructionDailyLimit`
- `constructionDiscount`

Agent rule:

- Daily resources, one-time resources, percent resource income, growth/recruitment-pool increases, and construction limit/discount effects are law-native.
- Economy triggered by battles, kills, plunder, low losses, defending territory, map-object class, or corpse cleanup is hook-required.

## Faction identity examples from public sources

Use these as mechanical vocabulary anchors, not as direct custom-faction mappings.

### Temple

Public sources identify Temple as the human faction. No detailed unique mechanic was found in this pass.

Design caution:

- Any Temple-like law guidance in this document is speculative/default-theme guidance, not a sourced unique Temple mechanic.
- If using Temple as inspiration, treat it as the safe baseline: morale, order, reliable economy, support magic.

### Grove / formerly Sylvan

Public sources identify Grove/Sylvan as nature/fey/elemental-themed.

Confirmed mechanics/examples:

- Faction ability `Murmuring` boosts Focus points.
- Armies are described as high-mobility and Focus-oriented.
- Example unit: halfling has a ranged slingshot attack and a dash ability across its movement zone.

Law-design implications:

- Focus generation/spending is a valid Grove-like design axis.
- Mobility and repositioning are valid Grove-like mechanics.
- Grove can inspire Rampart laws, but do not assume HoMM3 Rampart already has `Murmuring` unless we implement it.

### Hive

Confirmed mechanics/examples:

- Hive has a unique structure that grants each visiting hero +2 Attack.
- Hive `Swarm` can place insect eggs on the battlefield; eggs hatch into free extra creature stacks.
- Locust `Harvest` eats corpses to gain +2 Attack and Speed until battle end.
- Locust strikes twice in melee and has a ranged projectile affecting clustered targets.

Law-design implications:

- Corpses, free temporary stacks, and battle summons are real Olden Era concepts, not hallucinations.
- However, using them for custom factions requires tracing the specific battle hooks and data types.

### Necropolis

Confirmed mechanics/examples:

- Necropolis has a `graverobber` special action that digs up skeleton stacks.
- Necropolis has a city structure that transmutes creatures from other factions into similar-level Necropolis creatures.
- Necropolis creatures can leech health from enemies.

Law-design implications:

- Corpse/skeleton-generation and life-drain are game-sensible.
- Conversion/transmutation is game-sensible.
- Overhealing beyond original stack size remains unproven and should be treated as hook-required until verified.

### Dungeon

Confirmed mechanics/examples:

- Source conflict: Russian Wikipedia describes Dungeon as dark elves and underground creatures, while a GamesRadar developer preview uses the phrase `Schism's interplanar dark elves`. Treat `dark elf` identity as conflicting public-source terminology until verified from the game/community wiki.
- Red dragons have a special ability that damages melee attackers.

Law-design implications:

- Retaliation punishment, anti-melee auras, and punishing attackers are game-sensible.
- Ambush/isolated-target logic needs a hook unless a native condition exists.

### Schism

Public sources conflict on Schism identity. GamesRadar describes `Schism's interplanar dark elves`; Russian Wikipedia describes Schism as Lovecraft-inspired while assigning dark elves/underground creatures to Dungeon. No detailed Schism mechanics were found in this pass.

Law-design implications:

- Avoid inventing precise Schism mechanics without a better source.
- Do not use `dark elf` as a firm Schism or Dungeon mechanical anchor until a better source resolves the terminology.

## Law proposal triage labels

Use these labels in future matrices or review docs:

- `Native`: can likely be implemented directly with current law-table primitives.
- `Native-ish`: uses a real game mechanic but may need a small condition or lookup hook.
- `Hook`: requires runtime support, event detection, or custom condition evaluation.
- `Subsystem`: requires a broader custom mechanic like a faction mark, aspect cycle, rage meter, or custom conversion economy.
- `Unsupported`: no source found and no local primitive route; rewrite before implementation.

## Current custom-law design checklist

Before accepting a law proposal:

- Does the concept use a confirmed Olden Era mechanic?
- Is the effect expressible with current law-table primitives?
- If not, what event or object must be hooked?
- Does it depend on a custom faction subsystem?
- If it says `areas you control`, can the game identify controlled area in the required context?
- If it says `enemy towns`, `portals`, `water`, `cursed objects`, `dwellings`, or `artifacts`, can those map objects be classified in data?
- If it says `each turn`, `after battle`, `on counterattack`, `on spell cast`, `on kill`, or `per corpse`, assume hook-required until proven otherwise.
- If it modifies morale, remember mixed-faction morale exists and high morale can grant extra turns/actions.
- If it modifies magic, distinguish magic-school access, spell unlock/research, spell upgrade, neutral spell unlock via Insight, and battle cooldowns.
- If it modifies Focus, do not question Focus as a game mechanic. Question only whether the proposed trigger is implemented.

## Corrected note for Focus-related proposals

Bad review wording:

> Focus is not an Olden Era base mechanic.

Correct review wording:

> Focus is a real Olden Era combat mechanic. This law proposal is mechanically meaningful, but the specific trigger or payout still needs implementation tracing. For example, `Counterattacks generate 1 Focus` likely requires a counterattack event hook and a safe write path to the battle Focus resource.
