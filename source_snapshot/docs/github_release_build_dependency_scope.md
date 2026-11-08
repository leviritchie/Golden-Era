# GitHub Release Build Dependency Scope

Date: May 7, 2026.

Goal: move the Stronghold installer release build toward GitHub Actions so `StrongholdModInstaller.exe` and the release zip can be built from a public commit with checksums and provenance.

## Current Local Dependencies

`tools/release_installer/package_stronghold_release.ps1` currently requires a live local Steam release install at `GameRoot`.

Required from `GameRoot`:

- `HeroesOldenEra.exe`
- `HeroesOldenEra_Data/StreamingAssets/Core.zip`
- `HeroesOldenEra_Data/StreamingAssets/Core.zip.backup-*` or an explicit `-CleanReleaseCore`
- `BepInEx/plugins/OfflineUnlockMod`
- `BepInEx/core/BepInEx.Unity.IL2CPP.dll` and the rest of `BepInEx/core`
- optional `BepInEx/patchers`
- optional/sanitized `BepInEx/config/BepInEx.cfg`
- `dotnet/coreclr.dll` and the rest of the Doorstop CoreCLR runtime folder
- `winhttp.dll`
- `doorstop_config.ini`
- optional `.doorstop_version`

The package also runs:

- `dotnet publish` for `tools/release_installer/wizard/StrongholdModInstaller.csproj`
- optionally `dotnet build` for `OfflineUnlockMod.csproj`
- `python tools/release_installer/export_release_core_overlay.py`
- `Compress-Archive`

## Current Staged Payload Size

From `dist/HoMMOE-Stronghold-Mod-v0.1.276`:

- Plugin payload: about 126 MB, 4011 files.
- Full staged `payload/BepInEx`: about 132 MB, 4049 files.
- Doorstop game-root payload, mostly `dotnet/`: about 66 MB, 190 files.
- Core overlay: about 14 MB, 879 files.
- Published wizard exe: about 154 MB because it is self-contained WinForms.
- Final zip: about 221 MB.

## Dependency Risks

### Live Steam Install As Source

Risk: highest. CI cannot access a Steam install, and the local install can drift after Steam updates or manual mod testing.

Fix direction: make release packaging consume versioned, repo-local release inputs instead of `GameRoot`.

Risks of fixing:

- Large binary payloads enter Git history unless handled with Git LFS or release artifacts.
- Need a clear update process when Olden Era updates and the `Core.zip` overlay baseline changes.
- Current `manifest.json` records local absolute paths; CI manifests should record source hashes and build commit instead.

### Plugin DLL Build Inputs

Risk: high if we build the DLL in CI. `OfflineUnlockMod.csproj` references BepInEx core assemblies and game-generated interop assemblies from `BepInEx/interop`, including `Hex.dll`, Unity modules, and `Il2Cppmscorlib.dll`.

Fix options:

- Vendor a pinned `ci_deps/release_interop/` reference pack.
- Generate interop in CI from game files, which is not practical without shipping or downloading the game.
- Do not build the plugin in CI; instead package a staged plugin payload.

Risks of fixing:

- Vendored interop DLLs are game-derived/generated artifacts and add binary weight.
- Interop references must match the Steam release build used by the plugin and Core overlay.
- Building from source improves trust, but only if dependencies are reproducible and versioned.

### Plugin Asset Payload

Risk: medium. The staged plugin payload is already self-contained but currently copied from a deployed local install, not from a clean source folder.

Fix direction: introduce a canonical `release_payload/OfflineUnlockMod` source tree or build script that assembles it from repo paths.

Risks of fixing:

- Easy to accidentally include logs, `.flag` files, diagnostics, stale config, or generated interop if the source is copied from a live install.
- GitHub repository size grows substantially if all PNGs/bundles are committed directly.
- Git LFS makes cloning and Actions setup more complex but is probably appropriate for Unity bundles and asset payloads.

### BepInEx/Doorstop Bootstrap

Risk: medium. The installer currently copies a known-good loader/runtime from the local game root.

Fix direction: pin a bootstrap package by version and checksum, either vendored in the repo/LFS or downloaded by CI from an official release.

Risks of fixing:

- Downloading during CI adds supply-chain and availability risk unless checksums are verified.
- Vendoring adds binary size.
- Doorstop config must remain installer-controlled; do not trust a copied local `doorstop_config.ini`.

### Core Overlay Generation

Risk: medium-high. The current overlay exporter compares a clean release `Core.zip` backup to the modded local release `Core.zip`.

Fix direction: commit the already-generated `core_overlay/manifest.json` and `members/*.bin` as the release input, or commit both clean/modded source archives outside Git history and generate in CI.

Risks of fixing:

- Committing generated overlay is easiest and makes CI independent, but reviewing 879 binary payload members is awkward.
- Regenerating overlay in CI requires the same clean and modded Core archives.
- Overlay compatibility must be tied to a specific Olden Era Steam build hash; after a Steam update, old installers should fail cleanly.

### Wizard EXE

Risk: low. The wizard project is already CI-friendly: .NET 8, WinForms, no external packages.

Fix direction: build in GitHub Actions on `windows-latest`.

Risks of fixing:

- Self-contained WinForms creates a large exe.
- Windows SmartScreen will still warn without code signing, even with GitHub provenance and checksums.

## Recommended Migration Plan

1. Add a CI-only package mode that does not require `GameRoot`.
2. Create versioned release inputs:
   - staged plugin payload;
   - BepInEx/Doorstop bootstrap;
   - generated `core_overlay`;
   - installer templates.
3. Keep plugin source builds as a separate verification job until interop dependencies are pinned.
4. Publish the release zip, SHA-256 sums, and GitHub artifact attestation from tags.
5. Add a local `refresh_release_inputs.ps1` used only by maintainers after validating a new Steam release build.

## Practical First Step

The lowest-risk first automation is to make GitHub Actions build the wizard and assemble a zip from already-staged, repo-local release inputs. Do not try to regenerate interop, rebuild Unity bundles, or diff live `Core.zip` in CI in the first pass.
