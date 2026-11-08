# HoMM3 Unit Presentation Stopgap Census

Owner: `tools/validate_homm3_unit_presentation_stopgap_contract.py` (build gate, wired into
`OfflineUnlockMod.csproj` as `ValidateHomm3UnitPresentationStopgapContract`, skip with
`SkipHomm3UnitPresentationStopgapContract=true`) and its ledger
`custom_factions/contracts/homm3_unit_presentation_stopgaps.json`.

Proof tier: **generated artifact** — computed on 2026-09-26 from the installed Golden Era `Core.zip`
unit views and logics, `homm3_import.json`, the installed `homm3_bundles/*.manifest` clip lists, and the
`homm3_ui_portraits` manifest. The mummy's routing is also backed by the installed `LogOutput.log`.
Nothing here proves runtime visuals for any other unit. No mesh was generated, no bundle was rebuilt,
nothing was deployed.

## What the gate does

For every ported unit view (sid `h3_*` / `hota_*` / `toa_*` / `temple_*`, a `homm3_*` view folder, or a
`homm3_import` mesh path), it works out what the runtime shows. This follows the plugin's own keys:

- **Battle** is keyed by **unit sid** (`Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid`).
  - If an import row claims the sid, the unit shows its own model.
  - If no row claims it, the view `mesh` is loaded natively. That is a vanilla donor prefab, or another
    unit's `homm3_import` path.
- **Adventure map** is keyed by **resource path** (`TryResolveHomm3MapEntry(mapMesh)`). Any unit whose
  `mapMesh` names another unit's `mapResPath` gets that unit's model, even when it has its own bundle.

Issue tokens:

| Token | Meaning |
|---|---|
| `battle=donor:<prefab>` / `map=donor:<prefab>` | vanilla Olden Era donor model shown |
| `battle=borrowed:<sid>` / `map=borrowed:<sid>` | another ported unit's model shown |
| `bundle_missing` | an import row names a bundle that is not installed |
| `clips_missing` | owned bundle lacks one of Idle / Move / Hitted / Death / (AttackFront or ShootFront) |
| `portrait_missing` | no `ui_portrait_<sid>` (and no `homm3_portraits/<sid>.png`), so the UI falls back to the native/donor portrait (runtime unproven) |
| `inherited_donor_line` | a cloned neutral kept its donor's `upgradeSid` / `baseSid` |

Every computed stopgap must match a ledger row exactly, and every row needs a fix plan. The gate fails in
three cases:

- a new, unlisted stopgap appears (a silent fallback);
- a row's signature drifts;
- a listed unit stops being a stopgap (ratchet: remove the row).

Mesh-identity faults *inside* an owned bundle cannot be computed from these inputs. They are listed
separately under `declaredMeshIdentity`, where the gate checks only that each row names a real unit and
cites evidence.

## The mummy (user report, 2026-09-26)

`h3_mummy` has no mesh of its own in the game. What you saw is two different stopgaps:

1. `tools/release_port/homm3_neutral_core_overlay.py::_clone_unit_from_donor` builds each neutral's logic
   and view by **cloning the donor unit** named in `tools/homm3_import/faction_concepts/homm3_neutral.json`.
   For the mummy that donor is `homm3_necropolis/h3_walking_dead`. The clone keeps the donor's `mesh`
   and `mapMesh` ("donor mesh/mapMesh retained for runtime visual swap"). No runtime swap exists for
   `h3_mummy`: the unit has no `homm3_import.json` row, no bundle, and no lab `OwnedSkinned` prefab. Its
   lab folder holds only the extracted DEF frames.
2. **Map: Walking Dead (borrowed).** The installed view has
   `mapMesh = homm3_import/necropolis/h3_walking_dead_map`.
   - The map swap is keyed by path, so it resolves to the Walking Dead import row and loads the Walking
     Dead owned mesh.
   - The log records this under the wrong identity:
     `Homm3Import UnitViewHook: swapped unitId='h3_walking_dead' map mesh
     'units/homm3_import/necropolis/h3_walking_dead_map'`. The actual stack was a mummy.
3. **Battle: vanilla graverobber (donor).** The installed view has `mesh = Undead/1Prefabs/graverobber`,
   which is the Walking Dead row's `battlePresentationResPath` shell. The log reads
   `ecd.Init sid='h3_mummy' ... importEntry=False ... nativeVisual='unit_cutout(Clone)'` and then
   `no homm3_import entry for unitSid='h3_mummy'`, so the native donor model stays.
4. **Portrait: correct.** `homm3_portraits/h3_mummy.png` and `ui_portrait_h3_mummy` both exist.
5. **Data defect on top of the visuals.** The clone also inherited Walking Dead's line data:
   - `upgradeSid = h3_walking_dead_upg`, so a Mummy stack offers an upgrade into a Zombie;
   - the Walking Dead debuff ability;
   - the `xHomm3SourceMechanic = necropolis.walking_dead_line` role text.

What it would take to fix the mummy:

- **Mesh:** zero new Meshy credits. A Meshy mesh already exists at
  `artifacts/meshy_downloads/meshy7_missing/h3_mummy/mesh.glb`, textured but unrigged, and its semantic
  identity has not been reviewed.
- **Pipeline:** identity review → owned rig/bind (mocap lane) → Unity lab import → bundle build → an
  import row for `h3_mummy`.
- **Overlay:** emit the mummy's own `homm3_import/neutral/h3_mummy[_map]` paths, and stop copying the
  donor's `upgradeSid` / `baseSid`, abilities and role text.

## Status after fix step 1 (overlay data fix, 2026-09-26)

`homm3_neutral_core_overlay.py` now does two things for every catalog neutral:

- **Own view paths.** `apply_homm3_neutral_own_view_meshes` runs after every neutral view emitter,
  including the hand-authored Fangarm. When a neutral has an OwnedSkinned `homm3_import.json` row, its
  view `mesh`/`mapMesh` are set to that row's `battleResPath`/`mapResPath`. The row list comes from the
  same `load_homm3_import_skinned_preview_meshes` used for faction units. When the mummy's import row
  lands, it is picked up without further change.
- **No donor line identity.** `_strip_donor_line_identity` removes from every cloned neutral:
  - `upgradeSid` and `baseSid`;
  - active abilities (logic and view `abilities`);
  - the donor's `xHomm3` role/quality keys.

  Donor passives stay: immunities and basic-attack descriptors. One side effect: the vanilla-equivalent
  neutrals also lose their donor actives. Peasant had none. Halfling and Leprechaun lose the Halfling
  teleport, and the Faerie Dragon loses the OE fairy-dragon casts.

Readback from a scratch Core built by `build_overlay()` (`V:/homm3_scratch/neutral_overlay_20260926/Core.zip`,
**generated artifact**):

- satyr, steel golem, leprechaun and fangarm views point at `homm3_import/neutral/<sid>[_map]`;
- no neutral logic row carries `upgradeSid` or `baseSid`;
- the mummy no longer upgrades to `h3_walking_dead_upg`.

The same readback shows that the donor clone reads the donor view from the release Core. That view has
since been normalized to the donor's own `homm3_import` path, so the mummy and the crystal and rust
dragons now **borrow** the donor's model in battle too, instead of a vanilla prefab.

The ledger was regenerated against that scratch Core. The build-time gate reads the *installed* Core, so it
fails until this overlay is applied to the install.

## Status after fix step 2 (own mummy model, 2026-09-26)

- **Mesh and motion.** The Meshy mesh passed the look check (a bandaged mummy with a crook staff; its
  headdress is a disc rather than the DEF's tall crest). Renders: `artifacts/homm3_def_retarget/h3_mummy/lookcheck/`.
  No mocap capture is possible on this machine (the MocapAnything vendor tree is absent), so the unit is
  hand-keyed: `tools/homm3_def_retarget/handoffs/neutral_tools/mummy_hand_keys.py` writes the `handKeys` of
  `tools/homm3_def_retarget/units/h3_mummy.json`. The lower legs are welded into one surface, so every clip
  keeps the feet together (short shamble steps); the torso, head, free arm and staff carry the motion.
- **Delivery.** `tools/homm3_def_retarget_delivery/mummy_slice_v1.json`: emphasis, unit look and idle
  retime, then lab, bundle `custom_units_neutral_h3_mummy` and the offline bundle probe. The
  `homm3_import.json` row claims `h3_mummy` with battle and map lanes (`battleHeightHexes` 2.512 from the
  Cmummy idle plates, 105.5 px / 42).
- **Proof tier.** Generated artifact + offline bundle probe only. Not installed, and nothing is in game.
  The ledger row is now `bundle_missing` + `map=borrowed:h3_walking_dead`. The battle issue clears when
  the slice is deployed. The map issue clears when the overlay is regenerated, because
  `apply_homm3_neutral_own_view_meshes` picks up the new import row.

## Status after fix step 3 (own neutral models, 2026-09-26)

The neutrals whose Meshy mesh passed the look check are hand-keyed like the mummy (no neutral has a
mocap capture, and no shipped capture has their actions, so a donor capture would ship another unit's
timing). Poses live in `tools/homm3_def_retarget/handoffs/neutral_tools/<name>_hand_keys.py` on the shared
solver `intent_keys.py` (world-space intents, rigid props, two-bone IK for a second grip). Each unit gets
its own slice, import row (`battleHeightHexes` = median idle-plate body height / 42 px) and inventory row.

| Unit | Slice | Hexes | Ledger |
|---|---|---|---|
| h3_peasant | `neutral_peasant_slice_v1.json` | 1.976 | removed after deploy |
| h3_rogue | `neutral_rogue_slice_v1.json` | 1.929 | removed after deploy (no vanilla rogue: donors graverobber / troglodyte_upg_alt_map) |
| h3_troll | `neutral_troll_slice_v1.json` | 2.143 | removed after deploy (graverobber / troglodyte_upg_alt_map donors). Look issue: the Meshy skin is a dark olive against the bright yellow-green CTROLL sprite (silhouette IoU 0.42-0.57; wide grade starts only partly close it) |
| h3_neutral_halfling | `neutral_halfling_slice_v1.json` | 1.548 | removed after deploy (vanilla halfling donors) |
| h3_boar | `neutral_boar_slice_v1.json` | 2.405 | removed after deploy (pet / troglodyte_upg_alt_map donors). Rider hand-keyed on the procedural stronghold_quadruped boar; tier-2 height 2.35 allowlisted (mounted rider, as h3_wolf_rider_upg_alt) |
| h3_nomad | `neutral_nomad_slice_v1.json` | 2.167 | removed after deploy (pet / troglodyte_upg_alt_map donors). Rider hand-keyed on the procedural stronghold_quadruped horse |
| h3_crystal_dragon | `neutral_crystal_dragon_slice_v1.json` | 2.667 | removed after deploy (black_dragon / troglodyte_upg_alt_map donors). Hand-keyed body, fortress tail chain, rubble deferred (death vanishes at the shatter frame) |
| h3_azure_dragon | `neutral_azure_dragon_slice_v1.json` | 2.667 | removed after deploy (black_dragon / troglodyte_upg_alt_map donors). Hand-keyed body, wing_chain finger fans, keyed Move beat (wingSwing 138) |
| h3_rust_dragon | `neutral_rust_dragon_slice_v1.json` | 2.667 | removed after deploy (black_dragon / troglodyte_upg_alt_map donors). Meshy regen from a CRsDgn-drawn concept; hand-keyed body re-based on the upright sit, wing_chain finger fans, keyed Move beat (wingSwing 125) |
| h3_faerie_dragon | `neutral_faerie_dragon_slice_v1.json` | 2.643 | removed after deploy (black_dragon / troglodyte_upg_alt_map donors). Hand-keyed body re-based on the upright sit, wing_chain straight insect-wing panels, keyed Move beat (wingSwing 90) |
| h3_sharpshooter | `neutral_sharpshooter_slice_v1.json` | 1.952 | removed after deploy (elf_tracker_upg / troglodyte_upg_alt_map donors). Hand-keyed longbow archer (no capture for CSHARP), bow rigid on the left hand, cape held on the spine with the arms split free (legSwing 64) |
| h3_enchanter | `neutral_enchanter_slice_v1.json` | 2.31 | removed after deploy (lightweaver / troglodyte_upg_alt_map donors). Hand-keyed caster (no capture for CENCH), crescent collar rigid on Spine2, mantle held off the arms with the arms split free; spell light not delivered (legSwing 44) |

Proof tier: generated artifact + offline bundle probe. Battle clears when the slice is deployed; map
clears when the neutral overlay is regenerated.

## Status after fix step 2 (portraits, 2026-09-26)

`tools/generate_homm3_interface_portraits.py` now writes a static portrait for every `homm3_neutral`
catalog unit, and fails on any unit it cannot map:

- **SoD neutrals:** TwCrPort frames by `displayName`, creature ids 132–144.
- **HotA neutrals** (fangarm, satyr, leprechaun, steel golem): the `graphics.iconLarge` icon from the HotA
  `neutralCreatures` mod.

While mapping the sheet I found the Conflux upgraded-elemental ids were off by two. The sheet has unused
placeholder slots at 122/124/126/128. The corrected mapping changes these existing portraits:

| Unit | Portrait before | Portrait now |
|---|---|---|
| Ice Elemental (`h3_water_elemental_upg`) | Magma | Ice |
| Magma Elemental (`h3_earth_elemental_upg`) | Storm | Magma |
| Storm Elemental (`h3_air_elemental_upg`) | Energy | Storm |
| Energy Elemental (`h3_fire_elemental_upg`) | Phoenix | Energy |
| Firebird | Azure Dragon | Firebird |
| Phoenix | Crystal Dragon | Phoenix |

Those old portraits were wrong, and each was checked visually on a contact sheet.

The regenerated source PNGs (`homm3_portraits/`, gitignored) were fed to
`tools/homm3_import/build_homm3_ui_portrait_bundle.py`, run through `unitylock`/memgate. The staged
`homm3_ui_portraits` manifest now lists 484 sprites (was 470), including all 14 missing neutrals. That is
**build target proven**. It is not installed; the bundle binary is gitignored and deployed separately.

The regenerator also overwrote every painted 512 px source PNG with its 58×64 interface frame. That
downgrade is fixed in step 3 below and must not reach the install.

## Status after fix step 3 (painted portraits, 2026-09-26)

The painted masters (`artifacts/static_asset_painted_upscale/final/`, 1254 px, gitignored) were painted
from the TwCrPort frames *before* the id fix, so six of them show a neighbouring creature. Each master's
source frame was matched pixel-exactly against the sheet, then the masters were relabelled (record:
`artifacts/static_asset_painted_upscale/conflux_relabel_20260926/RELABEL_RECORD.json`, backups beside it):

| Master file before | Shows (frame) | Now the master for |
|---|---|---|
| `h3_water_elemental_upg` | Magma (127) | `h3_earth_elemental_upg` |
| `h3_earth_elemental_upg` | Storm (129) | `h3_air_elemental_upg` |
| `h3_air_elemental_upg` | Energy (131) | `h3_fire_elemental_upg` |
| `h3_fire_elemental_upg` | Phoenix (133) | `h3_firebird_upg` |
| `h3_firebird` | Azure Dragon (134) | `h3_azure_dragon` |
| pilot `h3_firebird_upg` | Crystal Dragon (135) | `h3_crystal_dragon` |

The Storm/Energy identity was also checked against the battle DEFs: CSTORM is the pale yellow figure
(frame 129) and CNRG the blue one (frame 131). Hurricane (`h3_air_elemental_upg_alt`) keeps the Tears of
Ashan `iconsbig/lvl2Alt.png` portrait. Its battle DEF `lvl2Alt.def` is a blue-and-peach recolour of Storm,
and that icon shows the same recolour. The Storm frame is the yellow original and does not match.

The masters were painted with the recipe the existing ones record: `gpt-image` 2.0 (C2PA on every `ai/*.png`),
the refs `gen_refs/<sid>__orig256.png` and `__lanczos.png`, and `CASTLE_SIMPLE_PROMPT.txt` verbatim. The
output went through `_pipeline.postpass_unit` (chroma key, 1254 bust, no circular clip) and the pocket
punch. They were reached through Meshy Image-to-Image `gpt-image-2`, because the direct OpenAI account had
no credits and Gemini was on the free tier. The run used 14 calls at 168 credits, logged in
`artifacts/static_asset_painted_upscale/PAINT_LEDGER_20260926.json` by
`_paint_portrait_masters.py`. It painted these units:
`h3_water_elemental_upg` (Ice), `h3_firebird`, `h3_peasant`, `h3_neutral_halfling`, `h3_boar`,
`h3_rogue`, `h3_nomad`, `h3_enchanter`, `h3_faerie_dragon`, `h3_rust_dragon`, `h3_fangarm`, `h3_satyr`,
`h3_leprechaun` and `h3_steel_golem`. The 24 correct `unit_portrait_touchup_pilot` masters, including
mummy, troll and sharpshooter, were copied into `final/`, so `final/` is the only master directory.

`h3_pixie` is still a raw frame. The provider refused it again, just as it did under GenerateImage.

To stop the downgrade, `generate_homm3_interface_portraits.py` now ends with `apply_painted_masters`. Every
unit with a master ships that master, Lanczos-downsampled to the contract side. The output is
byte-identical to `downsample_homm3_runtime_static_assets.py`, and the manifest records the result as
`paintedPortraitMasters`. `validate_homm3_runtime_static_asset_size_contract.py` (BeforeBuild) fails any
live portrait that has a master but is not that master's size. Result: 273 painted and 1 raw frame (pixie).
The rebuilt `homm3_ui_portraits` has 484 sprites, and the offline UnityPy probe finds 273 unit textures at
512 and pixie at 58×64. Proof tier: generated artifact and build target. The bundle is not installed, and
the in-game view is unproven. Contact sheet:
`artifacts/static_asset_painted_upscale/PORTRAIT_REPAINT_20260926_CONTACT_SHEET.png`.

After both steps the ledger holds **14 rows**, all mesh stopgaps:

| Class | Count | Units |
|---|---|---|
| borrowed mesh | 10 | troll, boar, rogue, nomad, enchanter, sharpshooter, azure / crystal / rust dragon, mummy |
| donor only | 3 | peasant, neutral halfling, faerie dragon |
| owned mesh, stopgap motion | 1 | Boar Rider |

## Census as first found (18 stopgaps, before fix steps 1–2)

Every faction-roster import row (the 261 rows in `homm3_import.json`) resolves to its own model on both
battle and map. One row, the Boar Rider, is idle-only. All stopgaps except the Boar Rider are
**neutrals**.

| Unit | Battle shows | Map shows | Other issues | Class | Fix |
|---|---|---|---|---|---|
| h3_mummy | own model once deployed (was donor graverobber) | Walking Dead until the overlay is regenerated | — | owned mesh pending deploy | deploy `mummy_slice_v1`; regenerate overlay |
| h3_crystal_dragon | donor phoenix_upg | Diamond Dragon alt | portrait; baseSid gold dragon | donor battle / borrowed map | same |
| h3_rust_dragon | donor black_dragon | Red Dragon | portrait; Red Dragon upgrade | donor battle / borrowed map | same |
| h3_peasant | donor peasant | donor peasant | portrait | donor only | same (the donor is the OE peasant) |
| h3_neutral_halfling | donor halfling | donor halfling | portrait | donor only | same (the donor is the OE halfling) |
| h3_faerie_dragon | donor fairy_dragon | donor fairy_dragon | portrait | donor only | same (the donor is the OE fairy dragon) |
| h3_troll | Ogre | Ogre | Ogre upgrade | borrowed mesh | Meshy mesh on disk → full lane |
| h3_boar | Wolf Rider | Wolf Rider | portrait; Wolf Rider upgrade | borrowed mesh | same |
| h3_rogue | Swordsman | Swordsman | portrait; Swordsman upgrade | borrowed mesh | same |
| h3_nomad | Cavalier | Cavalier | portrait; Cavalier upgrade | borrowed mesh | same |
| h3_enchanter | Mage (upg) | Mage (upg) | portrait; Mage line | borrowed mesh | same |
| h3_sharpshooter | Marksman | Marksman | Archer line | borrowed mesh | same |
| h3_azure_dragon | Gold Dragon | Gold Dragon | portrait; green/diamond line | borrowed mesh | same |
| h3_satyr | **own** | Centaur | portrait; Centaur Captain upgrade | owned mesh, map borrowed | data fix in the overlay |
| h3_steel_golem | **own** | Stone Golem | portrait; Golem upgrade | owned mesh, map borrowed | data fix in the overlay |
| h3_leprechaun | **own** | donor halfling | portrait | owned mesh, map donor | data fix in the overlay |
| h3_fangarm | **own** | donor troglodyte shell | portrait | owned mesh, map donor | data fix in the overlay |
| h3_wolf_rider_upg_alt (Boar Rider) | own mesh, **idle only** | own | Wolf Raider placeholder mesh | owned mesh, stopgap motion | new source + Meshy (paid) + motion |

Counts per class:

| Class | Count |
|---|---|
| borrowed mesh | 7 |
| donor only | 3 |
| donor battle / borrowed map | 3 |
| owned mesh, map borrowed | 2 |
| owned mesh, map donor | 2 |
| owned mesh, stopgap motion | 1 |
| broken reference (bundle missing) | 0 |

Every installed bundle named by `homm3_import.json` exists. 259 of 261 rows carry the full clip set.
`h3_cannon` has no melee clip, which is expected for a shooter.

Declared mesh-identity stopgaps are owned bundles that ship the wrong model. None of these is computed by
the gate:

| Unit (lab sid) | Evidence | Fix |
|---|---|---|
| h3_pegasus | mesh correct (check 2026-09-26), delivered by `pegasus_slice_v1`; remaining issue is the rider-and-mount rig | rig work on the existing mesh |
| h3_mechanic_upg_alt | stale mesh renders as a snake statue; the corrected candidate has been reviewed but not bundled | 0 credits: bind, then bundle |

The last three come from `artifacts/homm3_mesh_repair_fleet_v1/identity_reviews.json`. The installed
bundles' embedded GLBs were not hashed, so "still shipping the stale mesh" is inferred: that fleet records
that no bundle was rebuilt. Credit estimates are rough, based on Meshy image-to-3D plus texture at about
30 credits and auto-rig at about 5. Check current pricing before any paid call, which needs user approval.

h3_centaur's row was removed 2026-09-30: `rampart_slice_v1` installed the DEF retarget built on the corrected mesh, and its installed readback (`custom_units_rampart_h3_centaur`, sha 236eb975b9ee...) matches the file in Golden Era. Installed payload proven; the in-game look is not.

The Boar Rider (h3_wolf_rider_upg_alt / toa_boar_rider) left both lists 2026-09-30: `stronghold_boar_rider_slice_v1` installed the h3_boar_rider DEF retarget (full clip set, orc-on-boar mesh) into lab sid toa_boar_rider, and its installed readback (`custom_units_toa_boar_rider`, sha 15e42d978aa3...) matches the Golden Era file. The computed stopgap list is now empty. Installed payload proven; the in-game look is not. The class tables above record the ledger as it stood before.

h3_wyvern_upg_alt's (h3_paokai) row was removed 2026-09-30: `fortress_slice_v1` installed the DEF retarget built on the corrected horned-dragon mesh, and its installed readback (`custom_units_fortress_h3_paokai`, sha e1adbd6fdd89...) matches the file in Golden Era. Installed payload proven; the in-game look is not.

## Silent-fallback findings (AGENTS.md: fail closed, no silent fallbacks)

1. **The neutral overlay emits donor presentation by design and nothing refuses it.**
   - `_clone_unit_from_donor` writes the donor's `mesh`/`mapMesh` with the comment "retained for runtime
     visual swap", but no swap exists for the 13 catalog-only neutrals.
   - `tools/validate_homm3_neutral_catalog_contract.py` checks that each donor exists. It never checks
     that a neutral has an import row or bundle.
   - The new gate now makes each of these explicit.
2. **The battle miss is logged at Info, only with diagnostics on, and capped at 8**
   (`Homm3ImportReleaseBattleVisualHook.TryReplaceBattleVisualForDrawer`), so a donor battle model is
   effectively silent in a normal session.
3. **The map path-swap misattributes identity.** A borrowed map mesh is logged as a successful swap for
   the *owning* unit (`unitId='h3_walking_dead'` for a mummy stack). Nothing in the log says a different
   unit borrowed it.
4. **The clone copies line data.** For 12 neutrals the inherited `upgradeSid`/`baseSid` is a gameplay
   defect, not just a visual one: upgrading a neutral stack turns it into a faction unit. The mummy
   becomes a Zombie.

The fix for 1–3 is to make the release overlay fail closed. A neutral must either have an import row and
emit its own `homm3_import` paths, or be listed as an explicit stopgap, which is what this ledger now
enforces. The runtime miss logs are left as they are, because the gate catches the fault earlier at build
time. Upgrading them to a warning when the view `mesh` is a vanilla prefab for an `h3_` sid is an
optional follow-up. It was not done here.

## Ranked fix plan

1. **Overlay data fix (cheap, no assets). DONE 2026-09-26 (see status above; install pending).** Change `homm3_neutral_core_overlay.py` in two ways:
   - when a neutral has a `homm3_import.json` row, emit that row's `battleResPath`/`mapResPath` as the
     view `mesh`/`mapMesh`;
   - never copy donor `upgradeSid` / `baseSid` / line abilities / role text into a neutral.

   That clears the map stopgap for satyr, steel golem, leprechaun and fangarm, and the upgrade defect for
   all 12 neutrals. It needs a Core rebuild and deploy (not done in this pass), and each fixed row must
   then be removed from the ledger.
2. **Portraits (cheap, no credits). DONE 2026-09-26 (built and staged; install pending).** 14 neutrals have no `ui_portrait_<sid>`. Add their HoMM3 portrait
   frames to the portrait bundle build and to `homm3_portraits`.
3. **Neutral meshes (no new credits).** 13 neutrals have an unrigged Meshy mesh in
   `artifacts/meshy_downloads/meshy7_missing/<sid>/`. For each: identity review → mocap bind → lab →
   bundle → import row → overlay paths.
   - Suggested order by player visibility: mummy, troll, rogue, nomad, boar, sharpshooter, enchanter,
     then the dragons.
   - The dragons (azure, crystal, rust, faerie) need the winged/creature adapter, so they cost more.
   - peasant, halfling and faerie dragon currently show the OE-native equivalent creature. Those three
     could also be accepted as an explicit keep-native decision.
4. **Wrong-model rebinds (no new credits).** Bind and bundle the existing corrected candidates for
   mechanic_upg_alt, then pegasus (mounted adapter) and paokai (geometry). These are still blocked in the
   mesh-repair fleet.
5. **Paid Meshy regenerations (needs user approval).**
   - h3_centaur, from `creature_aaa_3d_upscale/h3_centaur.png`;
   - the Boar Rider (source image first).

   Estimated ~60–70 credits total, plus ~10 if Meshy auto-rig is used.
