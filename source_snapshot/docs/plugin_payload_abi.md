# Plugin payload versions (no DLL-hash pins)

Operational contract, adopted 2026-10-01 at the user's request. Delivery and runtime records pin the **plugin payload version** of the surface they depend on. They never pin the `OfflineUnlockMod.dll` sha256.

## Why

Before this change, every def_retarget unit slice's `runtime_capability_build.json` pinned three things:
- a frozen plugin DLL (`dll` + `dllSha256`, e.g. `combined_installed_5491e6d6/plugin/OfflineUnlockMod.dll`);
- the sha256 of three reader sources (`sources`);
- the import table (`importTableSha256`).

The slice `deploy` stage then **copied that frozen DLL over the installed plugin**. Two problems followed:
- Every plugin deploy staled all 38 records, and agents re-pinned them by hand ("re-pin inferno/conflux to DLL 5491E6D6").
- A record that was not re-pinned would downgrade the installed plugin when its slice shipped. For example, `neutral_nomad_slice_v1` still pointed at `0989db94` while `5491e6d6` was installed.

The mocap candidate lane (`experiments/homm3_mocap_v2/ship_ingame_candidates.py`) worked the same way.

What the hash was meant to prove is "the plugin that reads these bundles supports their format". A version states that directly. The exact binary only matters for runtime observations, and those keep their hash (see Out of scope). So the version replaces the hash. Auto re-pin on deploy was rejected: it would keep rewriting 38 records and keep the downgrade hazard.

## Pieces

| Piece | Where |
|---|---|
| Versions (consts) | `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/PluginPayloadAbi.cs`: `UnitBundleContractVersion`, `TownSceneContractVersion` |
| Surfaces, reader files, acknowledgements | `tools/plugin_payload_abi/surfaces.json` |
| Tool (emit / check-installed / guard / ack) | `tools/plugin_payload_abi/payload_abi.py` |
| Sidecar (generated, deployed next to the DLL) | `<plugin dir>/OfflineUnlockMod.payload_abi.json`: `{schema, dllSha256, dllBytes, surfaces: {UnitBundle: N, TownScene: N}, generatedAt}` |
| Contract validator | `tools/validate_plugin_payload_abi_contract.py [--require-installed] [--strict-readers]` |

Surfaces:
- **UnitBundle**: owned-skinned unit bundles in `homm3_bundles`. This covers `homm3_import.json` bindings, the prefab layout, `__homm3_vfx_*` node names, and the `homm3_mesh_fx` catalog and vanilla-style FX rows. Readers: `Homm3ImportVisuals.cs`, `Homm3UnitLookVfxRuntime.cs`, `Homm3MeshFx.cs`.
- **TownScene**: full-3D town scenes. This covers the `scene3d/<town>/catalog.json` schema and the bundle shaders it names. Readers: `Homm3TownScene3d.cs`, `Homm3FactoryCityWorldVisuals.cs`.

## Records

- **def_retarget and mocap runtime records** (`<out>/runtime_capability_build.json`) carry `"pluginPayloadAbi": {"surface": "UnitBundle", "version": N}`. The keys `dll`, `dllSha256` and `sources` are refused. The 2026-10-01 migration moved them, unchanged, under `retiredDllPin` for provenance.
- **Slice `deploy`** requires two things:
  - the record's version equals the source const;
  - the installed sidecar is current for the installed DLL and carries that version.

  It no longer copies or backs up a plugin DLL. The plugin reaches the game only through the established build.
- **`installed_readback.json`** also records `pluginPayloadAbi` with `installedDllSha256`. This is an observed fact; nothing compares against it.
- **Town installs** (`tools/homm3_town_scene_meshes/install_town_scene3d.py`) never pinned the DLL. They now refuse to install unless the installed sidecar carries the source's `TownScene` version. A catalog validated against the source reader is then read by the same contract in game. Catalogs carry no version of their own: the current source const is the pin.

## Build wiring (docs/build_validation_tiers.md)

| Tier | Target | What |
|---|---|---|
| Quick | `EmitPluginPayloadAbiSidecar` (before `DeployPluginToGame`) | Writes the sidecar for `$(OutDir)OfflineUnlockMod.dll`. `DeployFile` deploys it with the DLL. Then runs `guard`, warn-only |
| Quick | `ValidatePluginPayloadAbiSidecar` (after `DeployPluginToGame`) | `check-installed --require-source`: the installed sidecar exists, matches the installed DLL by sha256, and carries the source versions |
| Full | `ValidatePluginPayloadAbiContract` (before `BeforeBuild`) | The whole contract: every runtime record pins the current version, no retired pins, and the ship lanes and town installer use the check |

The sidecar steps are in the quick tier because they are part of the deploy itself. A deploy that leaves no sidecar, or a stale one, makes every slice and town install fail closed. That is an install-integrity failure, and the quick tier exists to catch those.

## Bumping a version

1. Bump the const when a change alters what that surface's records depend on. Examples: the catalog or table schema the plugin reads, the bundle or prefab conventions, the shader, node or key names. Do not bump it for fixes inside the same contract.
2. Run `python tools/plugin_payload_abi/payload_abi.py ack <Surface> --note "<why>"`. Commit `PluginPayloadAbi.cs` and `surfaces.json` together.
3. Rebuild the records of that surface against the new version, then set their `pluginPayloadAbi.version`. A record pinning an older version fails `validate_runtime_capability` and the contract validator. This is intended: its payload was made for the old contract.

A reader change that does not break the contract only needs step 2, `ack` with a note. That is one edit per reader change, not one per deploy per record.

## Guard limits (honest)

`guard` compares a hash of each reader file's **code** against its last acknowledgement. Comments and whitespace are stripped; string literals are kept. The guard:
- **warns, it does not fail** (unless `--strict-readers`). It cannot tell a breaking edit from a refactor, so it asks for a decision and does not make one.
- **is file-granular.** A contract change made outside the listed readers goes unseen, for example a `GameSymbols.cs` resolver, a shader inside a bundle, or a helper in another file. Add such a file to `readers` when it starts to matter.
- **is honour-system.** `ack` without thinking defeats it. The note is the audit trail.
- **does not prove runtime compatibility.** v1 is a baseline: the 2026-10-01 migration declared every installed record v1 because the installed plugin already serves all of those bundles. No per-record runtime re-proof was made.

## Import bindings (per-unit, not whole-table)

The same records also pinned `importTableSha256`, the sha256 of the whole `homm3_import.json`. Any unit's binding edit staled every record: 35 of 38 failed it on 2026-10-01. Records now pin only their own units (`tools/homm3_def_retarget_delivery/import_bindings.py`):

    "importBindings": {"schema": "homm3_import_unit_bindings.v1", "units": {"<labSid>": "<sha256>"}}

- **What a unit's digest covers:**
  - the table's global keys (everything but `entries`, e.g. `battleWorldHeightPerHex`);
  - every entry that names the unit: its prefab under `homm3_lab/<labSid>/`, its `bundleName`, or its `gameSid` in `gameUnitSids`.

  Entries are hashed as canonical JSON, sorted.
- **Fail-closed rules:**
  - another unit's binding edit leaves the record valid;
  - an edit to one of its own units, or to a global key, stales it;
  - a pin whose unit set differs from the selection's fails;
  - a record that still carries `importTableSha256` is refused.
- **Checks:**
  - `validate_runtime_capability` checks the pin against the source table;
  - slice `deploy` copies the source table, reads it back, then checks the installed table;
  - `validate_homm3_def_retarget_delivery_contract.py` checks every selection's record against the source table, and against the installed table with `--require-installed`.
- **Migration, 2026-10-01:**
  - The 36 selection records got pins computed from the installed table, which was byte-identical to source.
  - The old hash moved to `retiredImportTablePin`.
  - The two `combined_*` build dirs have no selection and cannot ship: their whole-table pin was retired with no replacement.

- **Refresh, 2026-10-01:** `ship_def_retarget_slice.py repin --selection <slice>` is the one way to refresh a record's
  data pins. It is a dry run by default and prints the pin diff; `--write` applies it, after backing the record up
  beside itself as `runtime_capability_build.prerepin_<ts>.json`.
  - A `meshFx` pin moves only to a file that is byte-identical in the worktree, at HEAD and in the install. Any
    divergence refuses the whole repin, so the deploy that follows ships no plugin-data change.
  - A selection unit with no `importBindings` pin gets `import_bindings.unit_digest` of the source table.
  - A pin outside the selection, or an own unit whose bindings changed, refuses: a real binding change needs a new
    runtime build record.
  - `validate_homm3_def_retarget_delivery_contract.py` requires the subcommand. Tests are in
    `tools/homm3_def_retarget_delivery/test_ship_repin.py`.

## Out of scope (kept as hashes on purpose)

- `tools/validate_offline_unlock_mod_deploy_hash.py`: source build equals deployed DLL (deploy integrity).
- `docs/offlineunlockmod_dll_provenance.md`: a provenance ledger of which source produced which binary.
- Runtime proofs that name the binary they ran under. Examples: the `pluginSha256` of the Bulwark and Factory combat proofs, and `installed.dllSha256` in `tools/homm3_vfx/vanilla_style/displacement_ship_proof.json`. These are observations of one exact binary and must not become a version.
- The `meshFx` pins in runtime records: payload data files, pinned by content on purpose.

## Proof

2026-10-01:
- Plugin `5676de2e` was deployed through the quick tier with its sidecar `{UnitBundle: 1, TownScene: 1}`.
- `validate_plugin_payload_abi_contract.py --require-installed`: OK, 38 records.
- A hand-copied DLL next to the sidecar fails as stale, and a missing sidecar fails.

Proof tier: installed payload proven for the sidecar. The surface checks are source/static.
