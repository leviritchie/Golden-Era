# Nexus Release Package

Status: source/static and generated-package validation only. This document does
not prove startup, runtime behavior, or permission to redistribute game-derived
assets.

`tools/release_installer/package_nexus_release.ps1` creates the Nexus-facing
distribution separately from the full local release installer. It combines the release-input plugin subtree, the official pinned BepInEx
Windows x64 IL2CPP runtime, and an explicitly supplied, known-good modded
`Core.zip`, then stages a direct game-root payload:

- `README.md`
- `THIRD_PARTY_NOTICES.txt`
- `manifest.json`
- `SHA256SUMS.txt`
- `winhttp.dll`
- `doorstop_config.ini`
- `dotnet/`
- `BepInEx/core/`
- `BepInEx/plugins/OfflineUnlockMod/`
- `HeroesOldenEra_Data/StreamingAssets/Core.zip`

The package contract is enforced by
`tools/validate_nexus_release_package_contract.py`. The packager validates the
staged directory and the ZIP when `-CreateZip` is supplied. It also validates
the supplied Core against `tools/validate_custom_faction_manifests.py`, checks
the clean pinned depot Core against an explicit SHA-256, requires an overlay
provenance manifest binding the modded Core to that exact vanilla Core, and
fails closed if Git cannot provide a full source commit.

The Core is intentionally a complete game-data replacement. It is not an
overlay, patcher, or installer-generated mutation. This is what makes the
Nexus installation a normal archive extraction into the matching depot root.

## Build

From the repository root, acquire the vanilla Core from the exact pinned depot
and provide both Core paths explicitly. First generate a small provenance
manifest from the two Core files. The exporter will fail if the modded Core
does not preserve a vanilla member unless that deletion is explicitly reviewed.

```powershell
python -m unittest tests.test_nexus_release_package_contract tests.test_nexus_release_package_contract_hardening -v
New-Item -ItemType Directory -Force dist\_nexus_bepinex_source | Out-Null
curl.exe -L --fail --output dist\_nexus_bepinex_source\BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755+3fab71a.zip `
  "https://builds.bepinex.dev/projects/bepinex_be/755/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755%2B3fab71a.zip"
python tools/release_installer/export_official_deobf_release_core_overlay.py `
  --vanilla-core "V:\Games\steamcmd-hommoe-poc\steamapps\content\app_3105440\depot_3105441\HeroesOldenEra_Data\StreamingAssets\Core.zip" `
  --modded-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" `
  --out-dir dist\_nexus_core_provenance `
  --allowed-deleted-member "generator/content_pools/template_maneuvers_pools copy.json" `
  --force
powershell -NoProfile -ExecutionPolicy Bypass -File tools/release_installer/package_nexus_release.ps1 `
  -CoreZipPath "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" `
  -VanillaCoreZipPath "V:\Games\steamcmd-hommoe-poc\steamapps\content\app_3105440\depot_3105441\HeroesOldenEra_Data\StreamingAssets\Core.zip" `
  -BepInExPackagePath dist\_nexus_bepinex_source\BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755+3fab71a.zip `
  -CoreProvenanceManifestPath dist\_nexus_core_provenance\manifest.json `
  -ExpectedVanillaCoreZipSha256 f78797075567b3080806828b5c7f350931fcbc609372855e491fd7457c7ffb6a `
  -PackageVersion golden-era-rc-YYYYMMDD `
  -CreateZip
```

The default outputs are:

- `dist/HoMMOE-Stronghold-Nexus/`
- `dist/HoMMOE-Stronghold-Nexus.zip`
- `dist/HoMMOE-Stronghold-Nexus.zip.sha256`

The current pinned depot Core identity is
`f78797075567b3080806828b5c7f350931fcbc609372855e491fd7457c7ffb6a`.
The input `Core.zip` is not read from the release-input ZIP because that ZIP
contains the installer-oriented `core_overlay/` representation. Supplying the
modded Core, vanilla Core, and generated provenance manifest explicitly binds
the shipped Core to the selected clean depot input instead of silently taking
an unrelated generated Core. The resulting package manifest records both Core
identities and sizes, not any maintainer's local path.

The vanilla hash and provenance checks are build gates, not runtime proof. If
the Steam manifest is retargeted, acquire the new clean depot, regenerate the
provenance manifest, and update the expected hash explicitly rather than
bypassing the checks.

## Required Steam Depot Build

The release candidate targets this known-compatible Windows Steam content:

- App ID: `3105440`
- Windows depot ID: `3105441`
- Manifest ID: `3222242645517655127`

For a clean test install, open `steam://open/console` with the Windows Run
dialog, then run:

```text
download_depot 3105440 3105441 3222242645517655127
```

Steam normally places the result under
`steamapps/content/app_3105440/depot_3105441`. That location is a depot cache,
not automatically the playable game root. Copy or mirror the contents of
`depot_3105441` (not its parent folder) into a separate clean directory, such
as `V:/Games/HoMMOE-compatible-3105440-3222242645517655127/`. Before
extracting the package, verify that the final root contains `HeroesOldenEra.exe`
and `HeroesOldenEra_Data/` directly. Do not put the mod in
`steamapps/content/...` unless that directory itself contains those files.
The Steam account must own the game or have access to the required branch and
manifest. The depot is not included in the Nexus ZIP.

The package includes the official BepInEx `6.0.0-be.755+3fab71a` Windows x64
Unity IL2CPP runtime from
[the BepInEx bleeding-edge build page](https://builds.bepinex.dev/projects/bepinex_be).
The exact source archive is pinned by SHA-256 in the build command and package
manifest. Generated interop, logs, caches, backups, and local runtime state are
not bundled.

The repository helper
`tools/release_installer/download_known_compatible_manifest.ps1` uses the same
IDs for maintainer-side acquisition and verification. It is not part of the
Nexus package. An alternative command-line client is the official
[SteamRE DepotDownloader](https://github.com/SteamRE/DepotDownloader).

## Installation

1. Start with a clean copy of the pinned depot game root. Make a backup of
   `HeroesOldenEra_Data/StreamingAssets/Core.zip`.
2. Download the generated Nexus ZIP.
3. Extract the ZIP directly into the main folder of the depot, beside
   `HeroesOldenEra.exe`. In PowerShell, the operation is equivalent to:

   ```powershell
   Expand-Archive -LiteralPath .\HoMMOE-Stronghold-Nexus.zip -DestinationPath . -Force
   ```

4. Launch the game once through Steam so BepInEx initializes and generates any
   game-specific interop files. Close the game after the first successful load.
5. Confirm that these paths now exist relative to the depot root:

   - `winhttp.dll`
   - `doorstop_config.ini`
   - `dotnet/coreclr.dll`
   - `BepInEx/core/BepInEx.Unity.IL2CPP.dll`
   - `BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll`
   - `HeroesOldenEra_Data/StreamingAssets/Core.zip`

Do not extract into a new wrapper directory such as
`HoMMOE-Stronghold-Nexus/`. `Core.zip` is a full replacement, so do not stack
another mod that replaces the same Core. Steam's file validation or a fresh
depot copy restores the original Core when you need to uninstall it.

## Upload Boundary

Upload the plain ZIP, not the full self-extracting installer and not the staged
directory. The package intentionally contains the pinned BepInEx root bootstrap
and runtime files; do not add a second loader, arbitrary executable, downloader,
or diagnostic bundle after validation. The only nested archive is the intentional
game-data file at `HeroesOldenEra_Data/StreamingAssets/Core.zip`; it is not an
installer or an executable payload. Nexus's current guidance recommends
ordinary ZIP/7z uploads and warns that self-extracting or nested archives can
be quarantined; see the [file submission guidelines](https://help.nexusmods.com/article/28-file-submission-guidelines)
and [quarantine guidance](https://help.nexusmods.com/article/117-why-has-my-mod-been-quarantined).

The generated manifest records the release-input digest, source commit, pinned
BepInEx source URL/hash/size/entry count, exact shipped BepInEx runtime files,
Core digest and size, provenance operation/deletion information, pinned vanilla
Core digest and size, copied files, scrubbed plugin DLLs, and excluded input
entries without embedding local machine paths. THIRD_PARTY_NOTICES.txt identifies
the bundled .NET runtime, dependency assemblies, and upstream license/notice
sources. The checksum file covers every shipped file except itself. A successful contract check proves package shape and byte
integrity only; it does not prove that the mod starts, that the payload works
with a particular game build, or that all included assets have redistribution
permission.
