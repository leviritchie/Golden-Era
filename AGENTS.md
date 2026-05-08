# Agent Notes

- Release builds are assembled by GitHub Actions from `release_inputs/stronghold_release_payload.zip`; local Steam installs are maintainer-only inputs and must not be required in CI.
- Before replacing `release_inputs/stronghold_release_payload.zip`, sanitize generated manifests so local paths, user names, and old playtest paths are not present in JSON/config/text files.
- Do not package Python helper scripts or `__pycache__` files from `reference_pack`; they are build-time scratch helpers and can leak local workspace paths.
- If rebuilding `OfflineUnlockMod.dll` for a payload, build with `DebugType=None` and `DebugSymbols=false` or inspect the DLL for embedded PDB paths before publishing.
