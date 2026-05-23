# Agent Notes

- Release builds are assembled by GitHub Actions from `release_inputs/golden_era_release_payload.zip`; local Steam installs are maintainer-only inputs and must not be required in CI.
- Public release output is now a single self-extracting `GoldenEraModInstaller-<version>.exe` plus `.sha256`, not a zip of an installer folder. Do not reintroduce adjacent payload/script assumptions into the installer.
- Do not tag, publish, or upload public GitHub release assets for installer changes until a local EXE smoke test has passed and the maintainer explicitly approves the release.
- The installer must keep Steam vanilla: use the selected Steam folder only as a clean source, create a separate Golden Era target copy, and install Doorstop/BepInEx/plugin files plus the Core overlay only into that target.
- Be precise in user docs: the clean Steam `Core.zip` is required for Install/Repair validation and copy staging, but an installed Golden Era target launches from its own patched `Core.zip` and does not read Steam's `Core.zip` at runtime.
- Treat `tools/release_installer/templates/install.ps1` and `uninstall.ps1` as legacy unpacked-package references unless they are intentionally redesigned. The WinForms EXE owns the supported install/uninstall path.
- Before replacing `release_inputs/golden_era_release_payload.zip`, sanitize generated manifests so local paths, user names, and old playtest paths are not present in JSON/config/text files.
- When refreshing release inputs from a locally modded Steam root, pass a verified clean Steam `Core.zip` backup as `-CleanReleaseCore`; check that the chosen baseline has zero `homm3_` entries before exporting the overlay.
- Do not package Python helper scripts or `__pycache__` files from `reference_pack`; they are build-time scratch helpers and can leak local workspace paths.
- Do not package backup configs, `.disabled` files, `.flag` diagnostics, `.pdb` files, Unity `.meta` files, or stale bundle backup files from a live Steam plugin folder.
- If rebuilding `OfflineUnlockMod.dll` for a payload, build with `DebugType=None` and `DebugSymbols=false` or inspect the DLL for embedded PDB paths before publishing.
- Core overlay manifests use the generic `hommoe-golden-era-release-overlay-v1` format. Do not reintroduce Stronghold-only token filtering when exporting release inputs.
- `actions/upload-artifact@v7` with `archive: false` accepts only one file per upload step. Upload the installer EXE and checksum in separate artifact steps; the GitHub Release step may still attach both files together.
- `docs/github_wiki/` is a GitHub-wiki-ready Markdown export for current custom faction attributes. It is generated from the private playtest workspace's live Core data and custom faction manifests; do not hand-edit it as source of truth unless the underlying Core/manifest data is also updated.
