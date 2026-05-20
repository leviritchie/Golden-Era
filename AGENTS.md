# Agent Notes

- Release builds are assembled by GitHub Actions from `release_inputs/golden_era_release_payload.zip`; local Steam installs are maintainer-only inputs and must not be required in CI.
- Before replacing `release_inputs/golden_era_release_payload.zip`, sanitize generated manifests so local paths, user names, and old playtest paths are not present in JSON/config/text files.
- Do not package Python helper scripts or `__pycache__` files from `reference_pack`; they are build-time scratch helpers and can leak local workspace paths.
- Do not package backup configs, `.disabled` files, `.flag` diagnostics, `.pdb` files, Unity `.meta` files, or stale bundle backup files from a live Steam plugin folder.
- If rebuilding `OfflineUnlockMod.dll` for a payload, build with `DebugType=None` and `DebugSymbols=false` or inspect the DLL for embedded PDB paths before publishing.
- Core overlay manifests use the generic `hommoe-golden-era-release-overlay-v1` format. Do not reintroduce Stronghold-only token filtering when exporting release inputs.
