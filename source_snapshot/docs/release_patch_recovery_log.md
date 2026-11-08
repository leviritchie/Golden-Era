# Release Patch Recovery Log

This document is the first stop after a Steam patch or hotfix breaks the
released Stronghold port. It records what changed, what restored functionality,
and which old experiments must not be revived as shortcuts.

Current pre-runtime mapping rule, May 13, 2026: update and review the semantic registry before broad rename passes. Same-name obfuscated matches and Levenshtein candidates are only proposals; accept them only when the owner type, parameters, return type, field/native field type, invocation kind, and high-risk xref/decompiled-body neighborhood match the hook's source contract. Run `tools/audit_obfuscated_symbols.py --runtime-only` so production hook debt is visible separately from probes, and manually verify dynamic `PatchByName`/`PatchByShape` surfaces that `verify_patch_surfaces.py` cannot infer.

## May 5, 2026 Hotfix Recovery

### Observed break

- Steam updated the released install at
  `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`.
- `GameAssembly.dll`, `global-metadata.dat`, and generated
  `BepInEx\interop\Hex.dll` all had May 5, 2026 timestamps.
- The live `Core.zip` was replaced by the hotfix and had zero
  `homm3_stronghold` registrations.
- The plugin still injected a seventh Custom Game faction list entry:
  `human, undead, nature, demon, unfrozen, dungeon, homm3_stronghold`.
- Selecting the appended entry reached `ScFractionSelect.qvm(...)` and then
  threw a native `NullReferenceException`, because the data/model layer could
  not resolve `homm3_stronghold`.

### Root cause

This regression was not only obfuscated method drift. The hotfix reverted the
release `Core.zip` to vanilla data, removing the Stronghold faction, heroes,
units, city, squads, and map registrations. UI hook changes could still matter
after data recovery, but the first failure was missing data parity.

### Recovery performed

1. Ran `hotfix_triage.ps1` to capture loader, interop, plugin, hook, and log
   state.
2. Verified current interop names from the live Steam interop:
   `SoFractions.pvr(string)`, `ScFractionSelect.qvl()`,
   `BhFraction.qnd(String,Sprite,Boolean,Boolean)`, and
   `BhHero.qoc(String,Boolean,Boolean,Action<T>)`.
3. Ran the Core overlay against the live Steam archive:

   ```powershell
   python "tools/release_port/apply_release_core_overlay.py" --release-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
   ```

4. The overlay prepared 744 archive member updates and created backup
   `Core.zip.backup-20260505-150402`.
5. Confirmed `DB/data.json` now contains
   `homm3_stronghold` in both `fractions` and `availableFractions`.
6. Confirmed critical members exist: `DB/fractions/7_homm3_stronghold.json`,
   Stronghold hero files, unit view files, `homm3_stronghold_city`, and
   `DB/map/objects/4_interactables.json`.
7. Fixed `apply_release_core_overlay.py` idempotence so a post-apply dry run
   does not try to append normalized Stronghold unit-view rows again.
8. Plugin `0.1.246` recovered part of the battle-facing path by tracing current
   shapes instead of adding broad probes. Dynamic billboard flips no longer
   preserve renderer bounds center during movement because that can move the
   quad off the native battle anchor.
9. Plugin `0.1.247` corrects a stale decompile mistake from the first `0.1.246`
   notes. The live Steam preview mesh loader is
   `clu.spo(string, GameObject&, float, Transform, int)`, not `cld.sgk`, so the
   synthetic preview hook now scans relevant Hex assemblies for that loader
   signature. Current `BhTurnView` stores its cached unit in `cgti` and refreshes
   through `UpdateView(Unit,TurnState,bool)`, `befs(Unit,TurnState)`, and narrow
   no-arg/int `Show`/`bef*` refreshes that can overwrite portrait art after the
   initial bind. The same build tries first-pass battle-plane anchoring by
   zeroing authored child billboard `x/z` local offsets before any manual
   screen-space tuning.
10. Plugin `0.1.248` restores the playtest battle billboard facing model for
    release. The working playtest component derived the billboard normal from
    the current root transform every frame and did not cache a motion-derived
    flip sign. The release root-motion experiment could make backwards actions
    flip, but it also let the last backwards sign persist after movement ended.
    Side mirroring is now applied only as initial local quad scale, without
    preserving renderer bounds center.
11. Plugin `0.1.249` keeps the no-cache rule but adapts it to release, where
    the replacement root does not receive the same action rotation as playtest
    `dzk.bath`. Current-frame root motion is used as a temporary flip signal
    and resets as soon as motion stops. The same build fixes synthetic preview
    wrappers by adding `cls` as `AddComponent<cls>()` so `Rotatable`,
    `Background`, `Model`, and `Sid` fields are writable, adds capped
    turn-order portrait miss logs, and patches current `BhSimulatedBattle`
    methods by shape for the quick battle/result hero portrait.

### Known verification gaps

As of plugin `0.1.239`, the overlay also appends all 21 Stronghold game-unit
SIDs to `DB/ai_pick/arena_pick_content.json` so random map generation can select
Stronghold neutral creature stacks. If Stronghold enemies stop appearing on new
random maps, inspect this file first and confirm it contains `h3_goblin`,
`h3_goblin_upg_alt`, and `h3_behemoth_upg_alt`.

Localization must be checked inside `Core.zip`, not only in loose
`StreamingAssets\Lang`. Plugin `0.1.229` copied loose Lang files, but the
released game still showed raw Stronghold keys because the live archive had no
`Lang/...` Stronghold rows. Plugin `0.1.230` updates
`apply_release_core_overlay.py` to merge Stronghold-only token rows from the
playtest-tweaked loose Lang tree into the release archive. A healthy post-apply
dry run now reports `Prepared 0 Core.zip member update(s)`, and direct archive
inspection should show `Lang/english/texts/heroInfo.json`
`homm3_stronghold_hero_1 = Crag Hack`.

Do not treat the arena pick list gap as the Custom Game selection blocker. The
selection blocker is missing `homm3_stronghold` Core registration or a stale
UI/model resolver.

## Standard Recovery Checklist

Run these steps in order after every Steam patch:

1. From `Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod`, run:

   ```powershell
   .\hotfix_triage.ps1 -Tail 500
   ```

2. Check timestamps for `GameAssembly.dll`, `global-metadata.dat`,
   `BepInEx\interop\Hex.dll`, and the deployed `OfflineUnlockMod.dll`.
3. Verify the current plugin loaded and did not emit stale startup failures.
4. Run a read-only overlay dry run:

   ```powershell
   python "tools/release_port/apply_release_core_overlay.py" --release-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" --dry-run
   ```

5. If the dry run reports Stronghold updates, apply it without `--dry-run`.
6. Verify the overlay dry-run is clean after applying. If it still reports
   `Lang/...` updates, localization was not merged into the archive the game
   loads.

7. Run Core parity:

   ```powershell
   python "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\verify_homm3_stronghold_core_parity.py" --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
   ```

8. Build against the live Steam interop:

   ```powershell
   dotnet build -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" -clp:ErrorsOnly
   ```

9. For missing post-hotfix icon surfaces, prefer the capped diagnostics added in
    plugin `0.1.238` before adding runtime remaps. Building/build-tree logs use
    `Homm3CustomUiIcon: building view` and `Homm3CustomUiIcon probe: building
    icon`; battle-result screen image logs use `Homm3CustomUiIcon probe image:
    source='battle result ...'`.

10. Confirm faction segregation after UI/portrait changes. Dungeon donor SIDs
    and donor sprites must not be reverse-mapped to Stronghold outside a scoped
    custom-SID donor alias prefix/postfix.

11. Test one gate at a time:
   Custom Game picker, Stronghold hero list, custom game start, adventure HUD
   and fog, town/map UI, then battle visuals.

## Do Not Repeat

- Do not replace Dungeon in the production picker.
- Do not use Dungeon as a carrier faction except in a clearly labeled,
  temporary diagnostic build.
- Do not hook `Hex.SharedLibrary.Requests.GameSetFractionRequest.set_Fraction`.
  Build `0.1.222` crashed inside the native-to-managed trampoline there.
- Do not resurrect the old launcher, offline unlock, autostart, UI-scale, or
  histogram patches for the release Stronghold port.
- Do not use broad runtime reflection probes over released `Hex.dll`; use
  ILSpy/decompilation and native disassembly first.
- Do not debug town or battle visuals while the Custom Game faction, hero list,
  and adventure HUD/fog gates are broken.

## Current Invariants

- Dungeon must remain selectable as Dungeon.
- Stronghold must be appended as its own Custom Game faction entry.
- The picker list path is `ScFractionSelect.qvl()` plus the shape-based
  `BhFraction(String,Sprite,Boolean,Boolean)` binder.
- The current release `SoFractions` asset lookup is `pvr(string)` by shape;
  `pvs` and `pqu` are only fallback names for older builds.
- Steam patches are expected to reset data and shift obfuscated names. Start
  with data parity and static symbol verification before adding probes.

## Gate 4 Hotfix Notes

- After data recovery, the map and Custom Game gates reached parity again, but
  Stronghold town layers logged `synced empty building state`. Static Steam
  interop decompilation showed `BuildingsData` moved its aggregate constructed
  building list to `cnvj` with backing field `chpr`. Keep older `cnvk/chps` and
  playtest `cgtl/cmzg/bfht` only as fallbacks.
- The selected army-strip hero portrait can register hooks and still miss the
  visible image if the resolver does not walk the current hero wrapper. The
  May 5 hotfix exposes the current hero through `ess.<chys>k__BackingField`
  and `ess.bgum()/bgup()`, while the HUD panel can hold wrapper fields such as
  `casv` and side-hero elements can hold `cayt/cayu/...`.
- For exact obfuscated type inspection, use the local ILSpy helper with
  `--exact`, for example:

  ```powershell
  dotnet run --project "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\tools\ilspy_decompile\Dc.csproj" -- "<Steam>\BepInEx\interop\Hex.dll" "_scratch.cs" --exact ess --exact yf
  ```

  Put scratch decompile outputs outside the mod project or delete them before
  building; otherwise MSBuild will try to compile the generated C#.

## Full Feature Slice Notes

- Plugin `0.1.226` reintroduces the HoMM3 import custom mesh path for release
  with a dedicated `TryRegisterReleaseFullFeatureSlice`. This registers
  ResManager, battle pool, release battle visual/UI, projectile, narrow
  spawner, map-object unit visual, tooltip, and preview hooks.
- Plugin `0.1.227` makes that slice fault-isolated. The first `0.1.226` run
  loaded correctly, but stale surfaces such as playtest `but` inside the
  map-object unit visual path could throw during registration and prevent later
  tooltip/preview hooks from registering. A failed surface must log and allow
  the rest of the slice to continue.
- Plugin `0.1.228` remaps the unit detail preview hook from stale
  `BhUnitWindowPreview.cgei` to the current release preview wrapper shape:
  `BhUnitWindowPreview.char` / `beri(string, Transform)` returning a wrapper
  with `Model`, `Rotatable`, `Background`, and `Sid`.
- Plugin `0.1.229` removes unsafe town diagnostic sampling of
  `List<BhBuildingView>` items. The `releaseTownUiDiagnostics.flag` path
  crashed in `AppendBuildingViewListSnapshot()` while indexing an IL2CPP list
  during `BhUIBuildingSession.Init`; Count-only snapshots are acceptable, but
  do not dereference list items in that native callback.
- Plugin `0.1.230` fixes two release-full feature regressions:
  `apply_release_core_overlay.py` now merges Stronghold localization rows into
  `Core.zip` `Lang/...` members, and the release battle visual hook resolves
  `ecd` slots by type after the hotfix moved the live visual to `cexw` and
  made old `cexx` a `Material`. Current `ecd` field meanings from live Steam
  interop: `cexw = GameObject`, `cexx = Material`, `cexs = Animator`,
  `cext = BhEffectHelperComplex`, `ceyb = SpriteRenderer`, `ceyc = Color`.
- Recruitment preview donor aliases were superseded by the June 24 custom-SID recruitment fix.
  `BhHireUnitItemView.UpdateView(string)` must keep the custom SID so native hire ability
  wrappers and hover payloads bind to custom unit data. Donor-compatible visual data belongs
  in explicit view fields; downstream preview hooks should not recover from temporary donor identity.
- Plugin `0.1.231` fixes the next release-full regressions seen after
  localization started working. Current `BhUnitWindowPreview.Show` /
  `BhUnitWindowPreview.beri(string, Transform)` cannot build from
  `homm3_import/stronghold/h3_*` mesh keys directly; prefix-alias those keys to
  the matching Dungeon donor prefab path only while the native preview factory
  runs, then restore the `UnitViewConfig` and replace the preview model with
  the Stronghold sprite prefab. Do not rely on a postfix alone here, because
  the native factory can throw before the replacement code runs.
- The same slice ports the selected-unit HUD guard from retired playtest
  `BhSelectedUnitHud.bdon` to current release `BhSelectedUnitHud.beet`. The
  observed battle softlock signature was repeated
  `KeyNotFoundException: The given key 'h3_orc' was not present in the
  dictionary` from `BhSelectedUnitHud.beet` after an orc attack. The release
  guard temporarily aliases the event unit SID to its Dungeon donor for the
  native HUD lookup, restores it in postfix/finalizer, and suppresses only
  custom-SID `KeyNotFoundException` fallout.
- Current release `dxs` ability wrapper mapping from live Steam interop:
  `cech = AbilityLogicConfig`, `ceci = AbilityViewConfig`, and
  `cecj = bool`. Do not use the stale `ceci`/`cecj` mapping from earlier
  notes; it makes battle ability icons/focus markers inspect the wrong object
  and can leave the action bar looking like blank one-turn cooldown buttons.
- Plugin `0.1.232` corrects the preview alias distinction. The release
  `BhUnitWindowPreview.beri(string, Transform)` factory string is a unit key
  and should be donor-aliased to a vanilla SID such as `assassin`; it should
  not receive `units/Dungeon/1Prefabs/...`. `UnitViewConfig.mesh` and
  `mapMesh` remain prefab-path fields and should use `Dungeon/1Prefabs/...`
  when they need donor paths. The postfix replacement still uses the saved
  original `h3_*` key for the HoMM3 model.
- The same build makes the release selected-unit HUD recovery reflection-based
  so the source can still compile against older interop while runtime binds
  current release members (`unit.cfhm`, `dxr.bama(EAbilityType)`,
  `BhUnitControlsView.begt(dxs[], dxs, bool)`, `cguk/cguj`,
  `BhUnitAbilityView.cntq/cgua`). This is the release equivalent of the old
  playtest `dwq/dwr` action-bar recovery and is specifically aimed at blank
  one-turn cooldown buttons after `BhSelectedUnitHud.beet` custom-SID lookup
  failures.
- `0.1.232` also adds a narrow Stronghold-only finalizer on
  `BhHireUnitItemView.trs/try(IReadOnlyList<string>)`. Suppress only
  `NullReferenceException` while the current city is `homm3_stronghold` or the
  argument list contains `h3_*`; the goal is to let the full recruit panel
  continue using UI portrait fallbacks, not to hide vanilla recruitment errors.
- Plugin `0.1.233` corrects two stale release assumptions found after the full
  recruit panel was confirmed working. The selected-unit HUD release prefix
  must not call direct old `Unit.cggz/cgha` accessors while extracting the SID;
  after the hotfix those compiled to missing `Unit.bedc()` at runtime and
  prevented the `cfhm -> dxr.bama -> BhUnitControlsView.begt` recovery from
  binding action-bar abilities. Use reflected `chdi/chdj/chdk/chdl` reads and
  only safe fallback extraction in the release path.
- Plugin `0.1.234` corrects the remaining preview/facing assumptions. With the
  Core overlay applied, `h3_*` unit-view rows are real configs and the preview
  path should keep `UnitViewConfig.id` as the custom key while using donor
  `mesh`/`mapMesh` values in Core's `Dungeon/1Prefabs/...` shape. Rewriting the
  id to `blade_dancer` caused current `BhUnitWindowPreview.beri`/`Show` NREs and
  black detail previews. Release battle visuals also read `ecd.Init` argument 5
  (`_leftSide`) and mirror the HoMM3 billboard quad for enemy-side stacks.
- Plugin `0.1.235` removes the last preview donor-SID rewrite from the direct
  `BhUnitWindowPreview.beri(string,Transform)` factory. With current Core data,
  both `Show(UnitViewConfig)` and `beri` must preserve `h3_*` as the custom key;
  donor prefab paths belong in `UnitViewConfig.mesh`/`mapMesh`, not in the unit
  SID argument. It also compensates enemy-side battle mirroring by preserving the
  renderer bounds center after applying negative quad scale, because off-center
  imported billboard pivots shift sideways if mirrored around the raw transform
  origin. The same patch reanchors build-tree row icons to current
  `BhBuildingView.tnv(fbi,dvw,int)` and hover oval art to
  `BhTooltipBuilding.syn(fbi,dvw,int)` / `syo(BhBuildingView,dvw,int,Action)`.
  `BhBuildingView.tnw` is now `tnw(int,int)` and is not a valid building-model
  binder.
- Plugin `0.1.236` fixes the battle-only alternate-upgrade sprite path. The
  import table and `TransferUnit.configSid` can already resolve
  `h3_goblin_upg_alt`, while the battle animator can still display regular
  Hobgoblin art if generated `homm3_frame_NNN` materials point at stale bundle
  textures. `Homm3BattleDiskTextureRemap` treats those materials as frame timing
  only and binds the matching deployed disk PNG for the resolved lab SID. Keep
  full `extracted_battle/**/*.png` deployment in the project file; the earlier
  `00_00`/`00_04`/`02_*` subset was for map/town idle billboards and is
  insufficient for battle.
- Plugin `0.1.237` fixes the remaining cause of the same symptom: the Steam
  plugin folder still had an old `homm3_import.json` where
  `h3_goblin_upg_alt` pointed at the Hobgoblin bundle. The build now deploys
  `homm3_import.json`, and battle-entry resolution checks `gameUnitSids` before
  accepting BattleNorm/MapNorm leaf matches. When the log says an alternate SID
  attached a regular-upgrade `labSid`, inspect deployed data before adding more
  runtime probes.
- If HoMM3 battle sprites appear with Dungeon donor meshes still visible behind
  them, inspect release `ecd` parent renderer siblings. The `0.1.231` battle
  visual hook disables renderer siblings that are part of the native donor
  visual after installing the HoMM3 prefab.
- Do not replace this with a direct call to broad
  `Homm3ImportVisuals.TryRegister()` under `releaseSafeProfile`. The broad
  playtest method registers `Homm3ImportArmyStripPortraitHook.TryRegister()`
  before the release-safe recovered army-strip remap can register, which can
  suppress the working May 5 `BhHeroHUDPanel`/`BhTooltipHeroItemView` portrait
  path.
- Plugin `0.1.240` repairs the next May 5 hotfix asset-routing regressions:
  release `BhTooltipUnit` no longer has `srs/sru`, so tooltip portraits are
  patched by reflected SID-bearing shapes (`Show(string,...)`, `taz(string)`,
  `tbb(string)`) and only apply to literal `h3_*` SIDs. Do not reverse-map
  Dungeon donor SIDs on enemy hover surfaces.
- The same build fixes current build-tree icon resolution. Release `dvw`
  exposes the building key as `cnou` / `zzb()`, level as `cnov` / `zzc()`, and
  underlying `BuildingData` through `cdtb` / `<cdtb>k__BackingField`; `cdtc` is
  the city wrapper, not building data. `BhBuildingView.tnw` is `tnw(int,int)`,
  so read the cached `BhBuildingView.byzb`/`cncz` building when refresh methods
  do not pass a `dvw` argument.
- `0.1.240` also repairs existing `homm3_stronghold` lobby assets instead of
  only appending a clone. Current `ScFractionSelect.qvl()` can return a
  seven-entry list where Stronghold is already present with placeholder art;
  replace `icon`/`bigIcon` and `card`/`slotFon`/`statisticFon`/`versusFon` in
  place. Current lobby hero class art is a separate GameHub surface
  (`BhHeroAdditionalInfo.classIcon`, `BhLobbyPopupHeroElement.classIcon`) from
  the in-game hero profile patch.
- Release-safe warcry native behavior remains quarantined, but `0.1.240` adds
  an icon-only current-release slice for `BhHeroAbilitiyView.siy(bzd,els)` and
  `BhHeroAbilitiesView.shx/shy/sif`. Current hero ability objects are `edg`
  and wrappers are `els`; old `ecf`/`ekn`/`rzt`/`ryt` names are playtest-era.
- If Stronghold adventure-map units show their Dungeon donor models, check
  `UnitViewConfig.id` before changing faction segregation. Current Core can use
  donor `mapMesh` paths while keeping the `h3_*` id; `UnitViewConfig.scd()` must
  resolve the HoMM3 map entry from that id when the synthetic
  `units/homm3_import/..._map` path is not present.
- Plugin `0.1.241` fixes the remaining battle/recruitment portrait surfaces
  from this hotfix pass. Current release `BhSelectedUnitHud.beev(object,
  BattleEventArgs)` does not pass `Unit` directly; read `BattleEventArgs.target`
  or use direct binder `beeu(bool,Unit)`. `BhTurnView.UpdateView(Unit,
  TurnState,bool)` remains the turn-order surface, but SID extraction must be
  shape-based (`Unit.chdj`/`chdk`/`chdl`, `betk`/`betm`/`beto`, or nested
  `sid`/`configSid`/`id`) rather than old `cggz/cgha` accessors.
- The same build maps the recruitment-card popover selector to
  `Hex.UI.City.BhCityUnitSpecialSelection.Show(Vector3,
  BhCityHireIncrementItemView,etc,Action<int>)`. The visible rollup entries are
  `BhCityHireIncrementItemView` instances under `selection.items`; resolve the
  candidate SIDs from `etc.cmea` / `htw()` and then apply the existing
  recruitment item icon path. Do not debug this through `BhHireUnitItemView.trs`;
  that is the large recruit model list and can throw before the small popover
  icons are refreshed.
- Plugin `0.1.242` stabilizes the `0.1.241` battle UI pass after the next test
  reported combat no longer loading. The failure signature was high-volume
  Harmony missing-member spam on Unity `Canvas`, `Camera`, `Rect`, and similar
  types caused by recursive shape scanning from battle UI wrappers. Do not scan
  arbitrary object graphs in battle refreshes; keep recovery on exact/static
  binders until native/decompiled traces identify the next hero portrait path.
- Plugin `0.1.243` reverts the `0.1.242` preview alias change after logs proved
  `BhUnitWindowPreview.Show.id` rewriting `h3_wolf_rider` to `assassin`
  immediately NREd in `BhUnitWindowPreview.beri` / `Show` and left the preview
  black. With current Core data, preserve `UnitViewConfig.id` and direct
  `beri(string,Transform)` strings as `h3_*`; only alias donor
  `mesh`/`mapMesh` resource paths, then apply the HoMM3 wrapper replacement.
- The same build resolves release battle unit portraits through
  `Unit.chdi` / `TransferUnit.configSid` plus the existing logic/view/data
  shapes, and resolves battle hero portraits through `BhHeroView.cgsm` ->
  `Hero.cbye` -> `Data.Hero.configSid`. Keep these as exact nested lookups; do
  not restore recursive Unity object graph scans.
- Release battle billboard facing is now dynamic: the helper watches root
  orientation for backwards movement/attack and flips the quad while preserving
  renderer bounds center. Do not hand-tune enemy X offsets until this path has
  been tested, because off-center pivots make raw negative scale look like a
  placement bug.
- Plugin `0.1.244` corrects the preview note above after a failed test of
  `0.1.243`: current Core keeps `UnitViewConfig.id` as `h3_*`, but
  `BhUnitWindowPreview.beri(string,Transform)` can still receive that custom id
  directly and NRE before the postfix sees a wrapper. Keep `Show.id` as `h3_*`,
  but alias the direct factory argument to the donor `Dungeon/1Prefabs/...`
  path, then replace the reflected preview wrapper with the HoMM3 sprite prefab.
- The same build updates battle portrait extraction for generated release
  backing-field spellings such as `_chdi_k__BackingField` on
  `Hex.Session.Battle.Unit` and `_cbye_k__BackingField` on
  `Hex.Session.Logic.Hero`. Generated IL2CPP interop does not always expose the
  CLR-style `<name>k__BackingField` spelling agents expect from decompilation.
- `0.1.244` also samples the billboard transform and hierarchy scale before
  overwriting camera-facing rotation. Root orientation alone did not detect
  backwards movement/attack in the release battle controller.
- Plugin `0.1.245` follows the user-confirmed `0.1.244` no-op. Logs proved
  the Steam DLL was current (`Loading [HeroesOE Offline Unlock 0.1.244]`) and
  that `BhUnitWindowPreview.beri.path` rewrote `h3_goblin` to
  `Dungeon/1Prefabs/troglodyte`, but native `beri` still threw before a wrapper
  existed. The current preview recovery therefore suppresses only Stronghold
  preview constructor failures, creates a minimal reflected `cls`-shaped wrapper
  (`Rotatable`, `Model`, `Background`, `Sid`), and lets the existing HoMM3 model
  replacement populate it.
- The same build extends battle portrait recovery to `BhTurnView.befs(Unit,
  TurnState)` in addition to `UpdateView`, applies the sprite to both `unitPic`
  and images under `tempPic`, and resolves battle hero keys through
  `BhHeroView.cgsm -> eii.cgfa -> TransferSide.hero/configId` or
  `TransferSide.logicHero`. Current battle transfer heroes use `configId`, not
  `configSid`.
- `0.1.245` adds a motion-based battle billboard facing signal. The previous
  transform-orientation sampling produced no visible change; use root movement
  projected onto camera right as the first non-invasive runtime signal before
  tracing native attack-target direction.
- High-frequency release UI helpers must use direct `Type.GetMethods()` lookup
  for known stale names. `AccessTools.Method()` logs every missing obfuscated
  candidate and can flood the log during battle/town refreshes.
- The recruitment-card popover now derives choices from the clicked tier's
  remembered SID (`base`, `_upg`, `_upg_alt`) before consulting `etc.cmea` /
  `htw()`. Treat those fields as fallback evidence, not as a positional source
  for visible popover entries.
