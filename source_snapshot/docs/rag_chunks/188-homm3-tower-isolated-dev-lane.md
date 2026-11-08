# HoMM3 Tower Isolated Dev Lane

Historical status note: this chunk records the old isolated Tower development lane. As of the June 15, 2026 Tower generic-path cleanup, release Tower data is owned by `custom_factions/homm3_tower.json` plus `tools/release_port/apply_release_core_overlay.py`; do not revive dedicated Tower hero/map/skill core passes or `tools/apply_homm3_tower_overlay.py` for Steam release work.

Tower faction work originally lived only in the isolated overlay lane:

- `experiments/homm3_tower/generated_core_overlay/`

As of May 7, 2026, the generated overlay is not a live worktree/build integration:

- `manifest_summary.json` reports `liveCoreZipModified: false`.
- `manifest_summary.json` reports `dataJsonRegistrationGenerated: false`.
- `DB/fractions/10_homm3_tower.json` has `xIsolation: "Generated overlay only; not appended to DB/data.json."`
- The overlay should not patch live `Core.zip`, `DB/data.json`, `homm3_import.json`, plugin hooks, or release overlays until manually reviewed.

Live integration status:

- The overlay city config now points building display fields at `Homm3Tower_Build_*` tokens instead of inherited Human placeholders.
- English overlay localization exists under `experiments/homm3_tower/generated_core_overlay/Lang/english/texts/` for Tower city/building text, external dwelling `barracks_homm3_tower_*` rows, unit names, alternate-upgrade ability names, and HoMM3 Tower hero names.
- Historical local apply script: `tools/apply_homm3_tower_overlay.py` applied the reviewed overlay into local `Core.zip`, registered `homm3_tower` in `DB/data.json`, cloned Human donor squads/heroes, added `barracks_homm3_tower_1..7`, and merged a simple Tower Lang overlay into loose English token files. Do not use this as the current release path; use the shared release overlay generator instead.
- Historical cleanup: that script also removed obsolete donor-named `DB/squads/squads_homm3_tower/**/squad_human*.json` members while rewriting `Core.zip`; current shared generator cleanup should live in `tools/release_port/apply_release_core_overlay.py`.
- `homm3_tower_city.json` carries `xHomm3TowerTownAnimations` metadata copied from `vcmi/Mods/third-upgrades/content/config/town-screen/tower/factions.json`, including `TBTWUP2_*`, `TBTWHRD2U`, and `TBTWEXT5` placements.
- Live town-screen art now has a Tower reference pack at `OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_tower/`. The correct town backdrop is HoMM3 `H3bitmap.lod` member `tbtwback.pcx`, decoded as the custom H3 bitmap payload and exported as `Tower-in-background.png`. Do not use `TpThBkTw` / `TowerHallBg.png` for the town scene; that asset is the town/building UI plate, not the snowy Tower town. Static layers are copied from `vcmi/Mods/third-upgrades/content/sprites/town-screen/tower/frames/` into the same layer IDs used by `xHomm3TowerTownAnimations`.
- The runtime town hooks are still named `Homm3StrongholdTownLayers` / `Homm3StrongholdTownAnimPlayer`, but they are faction-aware. Preserve the `homm3_tower` root selection in those hooks and in `Plugin.GetCityBackdropPath`; a generic `homm3_` fallback would regress Tower to Stronghold town visuals.
- Stronghold release learning applies directly to Tower external dwellings: if live Tower aliases raw donor dwellings, the billboard hook must rewrite reflected `ObjectConfig` SID/id fields to `barracks_homm3_tower_*`, or the visible art can change while native tooltip/localization keeps using the donor faction description.
- Tower rounded hero portraits now exist under `OfflineUnlockMod/homm3_hero_portraits/homm3_tower_hero_*.png`, sourced from HoMM3 `H3bitmap.lod` portraits `HPL032AL..HPL039AL` and `HPL040WZ..HPL047WZ`; slots 17 and 18 currently reuse slot 16 because the overlay clones 18 heroes from a 16-hero HoMM3 Tower roster.

Alternate upgrade skill status:

- The Tower planning names are now implemented in the isolated overlay unit logic rows using existing OE data-backed mechanics and buff SIDs.
- These changes are still not live-game registered because the overlay is not appended to `DB/data.json` and `Core.zip` is not modified.
- Do not describe these as live Tower behavior until the overlay is integrated into the real Core/data path and UI/localization surfaces are reviewed.

Current alt metadata mapping:

| Alt SID | Planned alt name | Skill | Isolated-overlay implementation |
| --- | --- | --- | --- |
| `h3_gremlin_upg_alt` | Gremlin Saboteur | `Jam Mechanism` | Ranged focus debuff using `crossbowman_debuff` for 2 turns with reduced damage. |
| `h3_gargoyle_upg_alt` | Runed Gargoyle | `Spell Carapace` | Deterministic spell protection: existing cast immunity plus direct `magic_damage` immunity. |
| `h3_golem_upg_alt` | Steel Golem | `Anchor` | Self guard/zone-control focus action using `ent_taunt_buff` for 1 turn. |
| `h3_mage_upg_alt` | Battle Mage | `Mana Channel` | Allied focus buff using `lightweaver_buff` for 1 turn. |
| `h3_genie_upg_alt` | Vizier Genie | `Boon Mastery` | Existing `succubus_debuff_3` focus line is lower-cooldown and lasts 3 turns. |
| `h3_naga_upg_alt` | Temple Guard | `Unflinching` | Guard/counter identity through very high counter capacity (`numCounters: 999`). |
| `h3_giant_upg_alt` | Storm Titan | `Storm Conductor` | Enemy-death focus/energy refund using the existing `unit_died` + `add_energy` passive pattern. |

Warning: if asked whether Tower implements the planning-doc alternate upgrade skills, distinguish isolated-overlay implementation from live-game implementation. The overlay rows now contain corresponding non-metadata abilities/passives, but the live Core/data path still does not register Tower.

Steam release promotion note, May 12, 2026:

- The local playtest `HeroesOE_Data/StreamingAssets/Core.zip` may already contain `homm3_tower` registration, city data, barracks, heroes, and cloned squad rows after a prior overlay apply. Do not infer from that state that the Steam release package has Tower.
- The current Steam release overlay/export tooling under `tools/release_port/` and `tools/release_installer/` is still Stronghold-token specific. Before claiming Tower is in the release build, add Tower-aware release overlay logic or generalize those scripts so `homm3_tower`, `h3_gremlin` through `h3_giant`, `hero_homm3_tower`, Tower laws/skills, Tower squads, Tower city rows, and Tower Lang rows are copied/merged into `HeroesOldenEra_Data/StreamingAssets/Core.zip`.
- A historical dry run of `tools/apply_homm3_tower_overlay.py --dry-run` against the local playtest archive prepared 724 member updates and loose English Lang merges, but that script targets the playtest `HeroesOE_Data` path by default. For Steam/current release work, use `tools/release_port/apply_release_core_overlay.py` and preserve the release merge discipline rather than overwriting release archive members wholesale.

Steam release promotion update, May 12, 2026:

- `tools/release_port/apply_release_core_overlay.py` is now Tower-aware. It finds Tower-bearing playtest Core members, appends `homm3_tower` to release `DB/data.json`, adds Tower units to arena pick content, replaces Tower-specific member files, overlays canonical Tower files from `experiments/homm3_tower/generated_core_overlay/`, and merges the simple Tower Lang overlay into archive-local `Lang/english/texts/*.json`.
- Applied to the live Steam archive at `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`; backup was `Core.zip.backup-20260512-052330`. A follow-up dry run reported `Prepared 0 Core.zip member update(s)`.
- Verification found `availableFractions` includes `homm3_tower`, Tower faction/city/hero/specialization files exist, Tower squad JSON count is 656, Tower faction `biome` is `Snow`, Tower unit views use `homm3_import/tower/<sid>` and `homm3_import/tower/<sid>_map`, and archive-local Tower Lang rows exist in `cities`, `units`, `unitsAbility`, `mapObjects`, and `heroInfo`.
- Release GameHub UI integration now appends both `homm3_stronghold` and `homm3_tower` to `ScFractionSelect.qvl()` and aliases `SoFractions` lookup for both custom faction IDs through Dungeon layout assets. Tower currently uses `homm3_runtime_assets/town_scene_refs/homm3_tower/mockups/homm3_tower_background_mock_1920x1080.png` as a temporary faction card/banner. Replace with purpose-built Tower faction art later.
- Tower unit visuals in Steam require all three pieces: `homm3_import.json` entries for 21 Tower SIDs, `custom_units_h3_*` bundles copied to `BepInEx/plugins/OfflineUnlockMod/homm3_bundles/`, and release Core unit views pointing at `homm3_import/tower/*`. Do not re-enable the legacy Tower release normalization that rewrites those views back to Human donor prefab meshes.
- When automating Unity batch builds from PowerShell, quote paths explicitly in a single `Start-Process -ArgumentList` string. Passing an argument array with workspace paths containing spaces can make Unity exit before it creates the requested log, which makes the outer build loop look frozen even though the target unit data is not the problem.

Upgrade selection wiring:

- May 7, 2026 fix: `homm3_tower_city.json` initially kept donor/shifted Human hire rows, so Tower upgrade branches could be absent or point at non-Tower units even though the Tower unit logic rows existed.
- The isolated overlay now maps `Build_Tier_1..7` to `h3_gremlin`, `h3_gargoyle`, `h3_golem`, `h3_mage`, `h3_genie`, `h3_naga`, and `h3_giant`, with each row listing `[base, _upg, _upg_alt]`.
- Unit logic `tier` fields are aligned to the same 1..7 dwelling order and carry `xHomm3TowerDecision.cityDwellingSid` / `cityDwellingTier` metadata for verification.
- If Tower upgrade selection breaks again, first verify the city `unitsHire.units[].sids` rows before changing unit ability logic.
