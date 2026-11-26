# Building pass: applier hand-back (2026-11-22)

The applier is built and tested on a sample. No override file under `custom_factions/` was written or read: that directory does not exist yet, and the applier treats a missing directory as "no overrides". Nothing was committed and no `dotnet build` was run. The GE install was not written to.

## How to run

- **Fast check (no build, nothing written).** This runs every override file through its town's real normalizer against the GE Core: mechanics, overrides, slot strip, canonical tree and descriptions. It takes about 1 second.

  ```
  python tools/release_port/apply_release_core_overlay.py --check-building-overrides [--building-overrides-dir DIR]
  ```

- **Schema and template check only:**

  ```
  python tools/release_port/homm3_city_building_overrides.py --check [--overrides-dir DIR] [--core Core.zip]
  ```

- **In a build:** the overrides apply automatically. `--building-overrides-dir DIR` points a build or `--dry-run` at another directory. `--help` lists both flags.

## Files changed

### `tools/release_port/homm3_city_building_overrides.py` (new)

- **Loader and fail-closed schema check** (`validate_override_doc`):
  - the section must be an `ObjCityConfig` list;
  - every `fields` key must exist on that section's live config class. `xHomm3*` keys pass. Keys the override sets through its own keys (`sid`, `names`, `icons`, `parametersPerLevel`, `sceneSlot`, `bonuses`, `bonusesPerLevel`) are refused;
  - `template` and `iconFrom` must have the form `<vanilla city>:<sid>` or `self:<sid>`;
  - every level needs a non-empty cost, using `gold`, `wood`, `ore`, `mercury`, `crystals`, `gemstones`, `dust` or `graal`;
  - `bonuses` needs one list per level, with types allowed for the section (`NATIVE_CITY_BUILDING_BONUS_TYPES`, passed in by the overlay). The `mains` and `walls` per-level types are also accepted;
  - `nameText` and `descriptionText` go through the description module's `text_problems` check (forbidden terms, raw keys).
- **Applier** (`apply_overrides_to_city_item`):
  - Runs in this order: snapshot, then `remove`, then replace/add rows, then AI `buildOrders`.
  - Templates are deep-copied. Fields that belong to another section are dropped, and so is the template's `xHomm3*` metadata. Bonuses are inherited only from a same-section template.
  - Costs become `parametersPerLevel[].costs` in the native `{"name","cost"}` shape.
  - Text keys come from `city_building_text_key_for_manifest`, which is `generic_building_text_key`, or the Castle and Fortress equivalents.
  - Icons, `backgroundImages` and `optionalEffectsPerLevel` are resized to the level count.
  - `nameText` and `descriptionText` are stored on the row as `xHomm3NameText`, `xHomm3DescriptionText` and their `...Locales` maps.
  - New levels are appended to every AI build order. The tree module then pulls their prerequisites forward.
- `assert_city_building_overrides_kept`: after the Castle-slot strip, fails if any override row was stripped.
- `override_name_lang_rows` and `override_locale_name_rows`: Lang rows read back from the final city rows.

### `tools/release_port/apply_release_core_overlay.py`

Hunk positions are taken from `git diff` against HEAD.

| Where | Change |
|---|---|
| Imports (~71–74) | Imports the module and `MissingExplicitTranslation`. |
| Fortress normalizer (~3906, ~3909) | `apply_homm3_city_building_overrides(doc, manifest)` after `apply_city_building_mechanics`, before `align_owned_world_city_scene_slots`; `building_overrides.assert_city_building_overrides_kept(...)` right after the strip, before `apply_homm3_city_building_tree`. |
| Castle normalizer (~6602, ~6605) | Same two calls in the same places. |
| Generic normalizer (~9451, ~9454) | Same two calls in the same places. |
| ~8213 | New wrapper `apply_homm3_city_building_overrides`, plus `add_homm3_city_building_override_name_rows` and `add_homm3_city_building_override_locale_name_rows`. |
| `homm3_city_building_locale_rows` (~9279) | A locale that an authored description lacks is skipped, not fatal. |
| `build_overlay` (~21358) | Binds the template reader (pending overlay first, then the Core); unbinds it in `finally`. |
| `build_overlay` (~21418) | English override names are written just before `apply_homm3_city_building_descriptions`, so they win over every per-faction name table. |
| `build_overlay` (~21463) | Authored locale names are written just after `apply_homm3_city_building_description_locales`. |
| ~21529 | New `check_homm3_city_building_overrides`. |
| `parse_args` / `main` (~22044, ~22148) | New flags `--building-overrides-dir` and `--check-building-overrides`. |

The call sits after the mechanics tables rather than immediately before the tree, for two reasons:
- the override must win over `CITY_BUILDING_MECHANICS_BY_FACTION`;
- the existing slot alignment and Castle-slot strip must still see the final rows.

It is still before `apply_homm3_city_building_tree`, as the brief asks.

### `tools/release_port/homm3_city_building_descriptions.py` (description hook)

- `Sentence` gains an `explicit` field.
- `derive_building_sentences` returns the authored text when the row carries `xHomm3DescriptionText`. It still rejects bonus types the section does not apply.
- English renders the authored text. A locale renders from `xHomm3DescriptionTextLocales`, or raises `MissingExplicitTranslation`.
- The validator reuses these functions unchanged. It accepts authored English, and it reports any locale that lacks a translation.

## How I verified it

Sample overrides live in `V:/olden_port_work/building_pass/applier/sample_overrides/`:

- **Castle:**
  - Bank restored, with `replace` and the `human_city:Build_Bank` template;
  - Stables added in `heroBonusBanks`, as a plugin row with explicit text and a German translation;
  - Brotherhood added in `heroBonusBanks`;
  - Signal Beacon added in `cityBonusBanks`.
- **Dungeon:**
  - Lyceum removed;
  - Portal of Summoning added in `portalSummonings`, from `unfrozen_city`;
  - Mana Vortex added in `manaFountains`, from `undead_city`, with computed text.

Results:

1. `--check-building-overrides` against the GE Core: **OK** for both towns, including the current canonical tree. Castle Training Grounds is wired to the Stables row. Dungeon `Build_Portal_Summoning` sits in the tree in place of the Lyceum.
2. `V:/olden_port_work/building_pass/applier/tests/test_applier.py`: **35/35 checks pass.**
   - Row shapes: section, kept icons and slot, native costs, stripped foreign fields, build orders, removal.
   - Text: explicit text versus computed text ("Produces 1000 Gold daily.", the mana sentence), narrative equal to description, a German translation used, a missing locale raising, name Lang rows.
   - 16 fail-closed error cases. One of them is `usageLimit`, which is not a field on any city building class.
3. A full `--dry-run` with the sample stops at Fortress. The tree agent's table now names `Build_Gymnasium`, which only the Fortress group's override file will add. The same is true for 8 of the 12 towns (see below).
4. An in-process `build_overlay` probe (`tests/pipeline_probe.py`, output in `pipeline_probe.log`) skips only those 8 towns' tree errors. It ran to completion (exit 0) and confirmed:
   - English names, computed descriptions and authored descriptions land in `Lang/english/texts/cities.json`;
   - the German authored description is written, and French falls back to the sync row;
   - the castle rows are in their sections, and the landon castle clone carries the Stables.

   **Finding:** a key that already exists in the installed Core keeps its old locale name after an English rename. For example, the locale rows for Castle `Build_Bank` still read "Ställe"/"Écuries" (Stables), and `Build_Stables` reads "Cavalry Logistics". Neither the sync nor `add_custom_lang_translations` replaces a row the Core already carries. Only `nameTextLocales` fixes this; the applier writes it after the locale pass.

**The full build cannot pass until every faction group's override file and the tree table land together.**

The tree is currently waiting on these override rows:

| Town | SID the tree expects |
|---|---|
| Conflux | `Build_Magic_University` |
| Cove | `Build_Grotto` |
| Factory | `Build_Factory_Loan_Bank` |
| Fortress | `Build_Gymnasium` |
| Inferno | `Build_Mycelium_Roots`, `Build_Mother_Nature` |
| Necropolis | `Build_Mother_Nature`, `Build_Mycelium_Roots` |
| Rampart | `Build_Mystic_Pond`, `Build_Rampart_Treasury` |
| Tower | `Build_Library` |
| Castle | `Build_Stables`, `Build_Mother_Nature`, `Build_Mycelium_Roots` (the real Castle file must add them; only the sample does today) |

## Constraints for faction JSON authors

1. **New rows** (`replace` false) need `template`, `nameText` and one `costs` entry per level. A row with `plugin` must give `descriptionText`.
2. **`fields` keys must be real fields of the section's live config class** (Steam 26615913 interop, `Hex.Configs`):

   | Section | Fields |
   |---|---|
   | `banks`, `heroBonusBanks`, `cityBonusBanks` | `bonuses` (set through the `bonuses` key) |
   | `graals` | `sideBonuses`, `cityBonuses`, `graalType` |
   | `intelligences` | `viewRadius` |
   | `unitsConverters` | `conversionPairs`, `bannedUnits` |
   | `trainingRanges` | `trainingStats` |
   | `rebirthShrines` | `resArr`, `levelStep` |
   | `portalSummonings` | `numberPurchases` |
   | `artifactChangers` | `artifacts` |
   | `artifactMarkets` | `extraChargePurchase`, `extraChargeSell`, `itemsCountPerRarity` |
   | `mains`, `walls` | `bonusesPerLevel` (set through the `bonuses` key) |
   | `myceliumRoots`, `manaFountains`, `taverns`, `markets` | nothing |

   Every section also accepts `isConstructedOnStart`, `levelOnStart`, `backgroundImages` and `optionalEffectsPerLevel`.

   **`usageLimit` does not exist on any city building class:** do not use it. For a per-week limit, put the limit in the plugin and the text.
3. **`bonuses`** follows these rules:
   - `banks` and `cityBonusBanks` accept only `sideRes` and `cityUnitsIncrementPer`;
   - `heroBonusBanks` accepts only `heroStat` and `heroExp`;
   - a flat section carries one list for all levels, so per-level values must be identical;
   - other sections take no `bonuses`;
   - a plugin-only bank uses `"bonuses": [[]]` plus `descriptionText`;
   - when `bonuses` is omitted, a same-section template's bonuses are inherited (for example `human_city:Build_Bank` brings +1000 Gold).
4. **Sources:** `template` and `iconFrom` take only the 6 vanilla city ids, or `self:` for a row the town has before removals. A new row with no `iconFrom` keeps its template's icons.
5. **`sceneSlot`** defaults to the SID without `Build_` for new rows, and must not repeat another building's slot. Shared SIDs (for example `Build_Bank`) are forced to the `cityHuman2` slot by the existing alignment.
6. **Castle-slot SIDs:** an override row whose SID is `Build_Intelligence_Academy` or `Build_Training_Range`, in a town without that native level, must also be listed in the building's `source_mechanics` `currentRows`. If it is not, the strip removes it and the applier fails with that instruction.
7. **Replacing a building that has a `CITY_BUILDING_MECHANICS_BY_FACTION` entry** (for example the Conflux `Build_Bank` "Magic University") requires `nameText`. Otherwise the old table name ships.
8. **`narrativeText` is accepted but not shipped:** the description contract keeps `narrativeDescription` equal to `description`.
9. **Translations:** give `descriptionTextLocales`, and `nameTextLocales` for every renamed or reused SID (otherwise the old locale name stays, see verification item 4), as `{locale: text}` for the 15 OE locales. Missing description locales do not break the build. The locale pass leaves the sync row in place, `--check-building-overrides` warns with a count, and the release validator fails on them.
10. **`remove`** must name rows the town actually has. Prerequisites and `nodePos` stay with the tree table.

## Needed from others (not my files)

- **`validate_homm3_city_building_descriptions_contract.py` `mechanics_errors`:** it still demands the `CITY_BUILDING_MECHANICS_BY_FACTION` section and bonuses for every spec SID. Either delete the stale spec entries the overrides supersede (in `apply_release_core_overlay.py`), or have the validator skip `building_overrides.overridden_sids(faction)`. This one-line edit is for the coordinator.
- **`Plugin.cs` / csproj:** none (Python only).
- **Scene keys:** none (the applier adds no SIDs of its own).
