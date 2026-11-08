# Stronghold Release Installer Design

Date: May 6, 2026.

Goal: make the current release Stronghold mod installable by a non-technical user without requiring `dotnet`, manual folder copying, Core.zip editing, or knowledge of BepInEx internals.

Important basis: the installer package is based on the **Steam release build**, not the old playtest. Playtest data may remain useful as historical research input for developer tools, but the installable artifact must be generated from a known-good modded Steam release install and applied to another Steam release install.

## Target User Flow

1. User downloads one zip and extracts it anywhere.
2. User runs `StrongholdModInstaller.exe`.
3. Installer auto-detects the Steam release install and a HoMM3 Complete/HD install, or asks for those folders.
4. Installer validates both folders, deploys the plugin payload, patches `Core.zip`, and prints either `Installed successfully` or one plain failure reason.
5. If Steam updates the game, user runs `install.ps1 -Repair`.
6. If needed, user runs `uninstall.ps1` to remove the plugin and restore the latest installer-created Core.zip backup.

## Package Layout

```text
HoMMOE-Stronghold-Mod-vX.Y.Z/
  StrongholdModInstaller.exe
  install.ps1
  uninstall.ps1
  README.txt
  manifest.json
  payload/
    BepInEx/
      plugins/
        OfflineUnlockMod/
          OfflineUnlockMod.dll
          config.json
          homm3_import.json
          homm3_bundles/
          homm3_portraits/
          bundle-backed recruitment idle clips
          homm3_hero_portraits/
          homm3_hero_map_sprites/
          homm3_lab/
          homm3_law_icons/
          histogram_icons/
          homm3_runtime_assets/
          homm3_stronghold_city_music
  core_overlay/
    apply_release_overlay.ps1 or apply_release_overlay.py
    manifest.json
    members/
```

The package must not include logs, diagnostics, scratch dumps, generated interop, the full source `homm3_lab` tree, or a full copied game install. Current Golden Era RCs may ship only runtime `homm3_lab/<sid>/{Generated,extracted_battle,extracted_map}` `.json` sidecars for generated battle/map manifests and RIFE metadata. Source lab files, loose PNG frames, scripts, Unity project files, backups, and diagnostics remain build inputs only. Packaging must verify each `homm3_import.json` row has its declared bundle and either generated battle/map array manifests or explicit bundle-manifest coverage for the legacy prefab/material frame shape. Missing coverage is a content/build failure, not permission to include loose PNG fallbacks.

## Installer Responsibilities

- Detect likely Steam path: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`, then common Steam library registry/install paths later.
- Validate target:
  - `HeroesOldenEra.exe` exists.
  - `HeroesOldenEra_Data/StreamingAssets/Core.zip` exists.
  - Target is not the old playtest `HeroesOE_Data` install unless `-Force` is passed.
- Validate HoMM3 ownership prerequisite:
  - Install and repair must find a local HoMM3 Complete or HoMM3 HD folder before changing the Olden Era install.
  - Complete validation uses `Heroes3.exe` plus the main `Data/*.lod` archives.
  - HD validation is intentionally simple and accepts HD folder/executable markers. This is only an existence/ownership check; it does not extract or rebuild Unity bundles.
- Validate BepInEx:
  - Install bundled Doorstop/BepInEx bootstrap files when missing.
  - `doorstop_config.ini` exists and is enabled.
  - `BepInEx/core/BepInEx.Unity.IL2CPP.dll` exists.
  - `BepInEx/interop/Hex.dll` may be absent on a fresh install; BepInEx should generate it on first game launch.
  - `BepInEx/config/BepInEx.cfg` has `UnityLogListening = false`; installer should set this if the file exists.
- Deploy payload:
  - Copy `payload/BepInEx/plugins/OfflineUnlockMod` to target `BepInEx/plugins/OfflineUnlockMod`.
  - Preserve user `config.json` only if it is already release-safe; otherwise back it up and install the packaged release config.
  - Delete known stale diagnostic files from the target plugin folder.
- Patch release data:
  - Back up `Core.zip` before modification.
  - Apply a release-derived Stronghold overlay generated from the known-good modded Steam release archive.
  - Verify `DB/data.json` contains `homm3_stronghold` in `fractions` and `availableFractions`.
  - Verify Stronghold faction, hero, unit, city, and localization members exist.
  - Restore backup automatically if verification fails.
- Emit simple output:
  - Success path should fit on a few lines.
  - Detailed trace only with `-Verbose`.

## Packaging Responsibilities

The packaging script is the developer-only part. It should:

- Build the plugin against the current release interop.
- Stage the full `OfflineUnlockMod` payload from a known-good deployed plugin folder or from build outputs plus asset source folders.
- Exclude logs, debug probes, old `config.json` variants, `.manifest` files unless explicitly needed, generated interop, and scratch data.
- Generate a release-safe `config.json` with Stronghold enabled and probes disabled.
- Package the Core overlay from release artifacts only. Historical blocker (resolved for the main entrypoint): `tools/release_port/apply_release_core_overlay.py` now defaults to the Golden Era Core. The helper `custom_law_lang_rows` still has a playtest-Core default when called without `release_zip`, so callers must pass the release archive explicitly. Package generation should instead compare:
  - a clean Steam release `Core.zip` for the same game build, preferably the latest pre-overlay backup made immediately after a Steam update, and
  - the known-good modded Steam release `Core.zip` that currently works.
- From that comparison, emit a self-contained release overlay manifest:
  - added members that are Stronghold-specific;
  - changed release JSON/Lang members with only the Stronghold-bearing row/token operations when possible;
  - expected source archive hash/build timestamp so the installer can warn after Steam updates.

The fallback for early local testing is to package the known-good modded Steam release `Core.zip` as an overlay source and call the existing merge logic with that archive explicitly. That is still release-based, but it should not be the final public package because it is less precise and may carry unrelated release data.

## Safety Rules

- Never overwrite `Core.zip` without a timestamped backup.
- Never install into a folder that lacks `HeroesOldenEra.exe`.
- Never silently enable old playtest launcher/offline hooks; release-safe profile remains mandatory.
- Never ship or test a release candidate with `live_probe_bridge`, `.flag` triggers, plugin `.log` files, plugin `.pdb` files, the full source `homm3_lab` tree, or enabled runtime diagnostic config keys. `tools/release_installer/create_official_deobf_release_candidate.ps1` is only a runnable-folder smoke candidate; it mirrors the current Golden Era Steam folder into `dist/HoMMOE-Golden-Era-ReleaseCandidate`, strips those artifacts, forces `UnityLogListening = false`, and writes `release_candidate_manifest.json` with the DLL/Core hashes.
- Installer-style Golden Era RCs must mirror the public Golden-Era release pipeline: generate a sanitized `golden_era_release_payload.zip` plus `.sha256`, then build the self-extracting installer EXEs from that release input. Use `tools/release_installer/refresh_official_deobf_release_inputs.ps1 -CleanReleaseCore <clean Core.zip> -PluginDllOverride <stripped rc dll>` to create `dist/golden_era_release_inputs/golden_era_release_payload.zip`; use `tools/release_installer/build_official_deobf_installer_candidate.ps1 -CleanReleaseCore <clean Core.zip>` to invoke the public staging checkout at `V:\Games\golden_era_release_repo` and produce both upscaled/standard portrait installer EXEs. RC DLLs must be built with `-p:ReleaseCandidateBuild=true`; that compile path excludes `Homm3LiveProbeWorkbench.cs`/live-probe state code instead of merely disabling it, and the refresh script fails closed if the DLL still contains live-bridge command names, PDB/debug provenance, or local source paths. The refresh script may copy only runtime `homm3_lab` `.json` sidecars under `Generated`, `extracted_battle`, and `extracted_map`, and it requires per-import generated battle/map manifests or verified legacy prefab/material frame coverage in the declared Unity bundle manifest before packaging. Live-parity RCs must also stage and install (a) injected `resources.assets` + `globalgamemanagers` dialog portraits, (b) pinned `global-metadata.dat` (`cityFactory`), and (c) curated `StreamingAssets` trees (`maps`/`Story_maps`, `video`, `.procedural_scenarios`) via `tools/release_installer/stage_golden_era_live_parity_payload.py`, while still stripping diagnostics/live bridge. Do not overwrite the public repo's committed `release_inputs` for RC smoke testing; the RC builder stages its temporary input under that repo's `dist`.
- Never require or reference `HeroesOE_Data` / playtest `Core.zip` in an end-user installer.
- Never ask the user to run `dotnet`, edit JSON, or open `Core.zip`.
- Treat Steam updates as expected; `-Repair` must be idempotent.
- Keep the wizard UI on docked/layout-panel sizing instead of fixed pixel coordinates. Windows DPI/font scaling can clip fixed-height labels, text boxes, and buttons badly.
- SteamCMD manifest recovery is only a baseline acquisition path, not proof of compatibility by itself. The current proof-of-concept is `tools/release_installer/download_known_compatible_manifest.ps1`, targeting app `3105440`, depot `3105441`, manifest `3222242645517655127`, and mirroring the downloaded depot into `V:\Games\HoMMOE-compatible-3105440-3222242645517655127`. It can infer the most recent Steam account name from a running/installed Steam client's `config\loginusers.vdf`, but SteamCMD still owns authentication and may prompt for password or Steam Guard. Any installer integration must still verify the downloaded `Core.zip` hash before applying the mod, must keep Steam credentials inside Valve's SteamCMD flow, and must handle SteamCMD failures such as unavailable historical manifests without falling back to patching an unknown build.

## First Implementation Milestones

1. Create `tools/release_installer/package_stronghold_release.ps1` to stage the installer folder and payload.
2. Create installer templates with target detection, BepInEx validation, payload copy, release-overlay application, and rollback.
3. Add release-overlay export support so the installer no longer depends on workspace-local playtest Core paths or the migration tool defaults. First pass: `tools/release_installer/export_release_core_overlay.py` compares a clean Steam release `Core.zip` backup to the known-good modded Steam release `Core.zip` and emits a self-contained manifest plus changed member payloads. `package_stronghold_release.ps1 -CleanReleaseCore <path>` now runs that exporter while staging the package.
4. Add post-install verification against the target `Core.zip`.
5. Test install, repair, and uninstall against a disposable copy of the Steam release folder before using the live install. May 6 first disposable test passed: install applied the overlay, repair was idempotent, uninstall restored the original clean Core.zip hash and removed the install-state file.
