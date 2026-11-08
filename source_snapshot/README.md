# Golden Era source snapshot

This folder is a read-only snapshot of the Golden Era mod's own source code: the BepInEx plugin, the
asset and animation pipelines, the campaign and town converters, the validators, and the design docs.
Day-to-day development happens in a private workspace. This snapshot is exported from it by
`tools/public_source_export/export_public_source.py` (included here).

- Source commit (private workspace): `5ccd7ce95095620e3a2c6cb88c66c7bdd713c787`
- Files: 5103 (about 71 MB of text)

## Releases do not use this folder

Nothing here is read by the installer, the release workflow or the nightly builds. Releases are built
from this repository's top-level `tools/release_installer/`. Their payloads are GitHub Release assets.
Changing or deleting this folder cannot affect an install.

Each export replaces the whole folder, so do not edit it by hand. Issues and pull requests that point
at code here are welcome. Fixes are made in the private workspace and come back with the next export.

## Layout

| Path | What it is |
| --- | --- |
| `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` | The mod itself: the BepInEx 6 IL2CPP plugin (`OfflineUnlockMod.dll`), with Harmony hooks, custom factions, towns, units, laws, the AI driver bridge and bug reporting. `Plugin.cs` is the entry point. `GameSymbols*.cs` is the only place that names obfuscated game symbols. |
| `Heroes of Might & Magic Olden Era Playtest/OfflineLauncher/` | A small WinForms launcher. |
| `Heroes of Might & Magic Olden Era Playtest/DamageHistogramMod/` | The separate damage-histogram plugin. It is not part of Golden Era releases. |
| `custom_factions/` | Faction manifests (`homm3_<faction>.json`), plus hero, law and ability overrides, artifact mechanics, and the predicate contracts that the custom laws are checked against. |
| `scenarios/`, `procedural_scenarios/` | Campaign batch manifests and the seeded scenario generator. The converted maps are not included. |
| `experiments/campaign_port_poc/` | Converts HoMM3 maps and campaigns to Olden Era maps (raw translation, approach cells, Seer's Huts, StoryHub continuity). |
| `experiments/homm3_mocap_v2/`, `experiments/homm3_tower/` | Mocap animation experiments, and Tower faction data generation. |
| `experiments/olden_cs_recovery/`, `experiments/cpp2il_readable_csharp/` | The code-recovery and symbol-mapping pipelines. Only the scripts and schemas are here; all recovered output is excluded. |
| `tools/homm3_import/` | Imports HoMM3 units into Unity bundles (DEF extraction, recolours, alternate upgrades, Unity editor scripts). |
| `tools/homm3_def_retarget*/`, `tools/homm3_glb_patch/`, `tools/homm3_meshy_frame_pose/`, `tools/homm3_unit_look/` | The 3D unit pipeline: retargets animation to HoMM3 DEF reference frames, patches GLBs, binds meshes and sets each unit's look. |
| `tools/homm3_town_scene_meshes/`, `tools/homm3_town_prefabs/` | Builds the 3D town scenes and town prefabs. |
| `tools/homm3_vfx/`, `tools/homm3_metal_shine/` | Spell and ability VFX, and metal materials. |
| `tools/port_current/`, `tools/release_port/` | Ports the mod to new game builds by remapping obfuscated symbols. |
| `tools/olden_ai_sim/`, `tools/olden_ai_mcp/`, `tools/olden_a11y_nvda/` | The adventure-map AI simulator, the MCP bridge to the AI driver, and screen-reader experiments. |
| `tools/nightly/` | The nightly pipeline: bug-report triage, plugin build, payload staging and leak scan. |
| `tools/google_bug_report_relay/` | The receiver for the in-game bug-report button (Google Apps Script). |
| `tools/cross_agent_manager/` | The coordination board for the coding agents that work on the project. |
| `tools/validate_*.py` | The contract validators. The plugin build runs them in its full validation tier (`docs/build_validation_tiers.md`). |
| `docs/` | Design docs, contracts and handoffs. Start with `docs/README.md`; `docs/agent_surface_guide.md` maps the game's engine surfaces. |
| `AGENTS.md`, `CLAUDE.md`, `.agents/` | Instructions for the coding agents that work on this project. They also give the quickest overview of how the project is run. |

## What is missing, and why

The export starts from every file tracked in the private workspace and leaves out these:

| Reason | Files | What it covers |
| --- | ---: | --- |
| `assets` | 3372 | Game and HoMM3 assets, and mod payload data generated from them (sprites, meshes, portraits, generated Core overlays, VCMI/HotA reference configs), plus verbatim game text: HoMM3 campaign prologues, scenario descriptions, objectives and their translations (experiments/campaign_port_poc/*localization*, *_video_prologue_transcripts*). |
| `binary_or_media` | 3031 | Binaries and media: images, GIFs, video, DEF/PCX, GLB/FBX, NumPy arrays, NuGet packages, DLLs. |
| `decompiled` | 1655 | Decompiled, disassembled or recovered game code, plus data derived from it (rename maps, IR, proof ledgers, symbol diffs, xref trees). |
| `generated` | 1197 | Generated artifacts and run output (the artifacts/ tree, build_out, benches, handoffs, logs, dated reports). |
| `oversize` | 35 | Data tables (json/csv/tsv) over 256 KB and docs over 1000 KB. Most are generated (symbol remaps, town-bench edits, name indexes); a few are large hand-kept tables such as tools/homm3_import/owned_unit_presentation.json. |
| `third_party` | 27 | Third-party trees and tool stores (external repos, VCMI, dotnet tool stores, BepInEx docs). |
| `scratch` | 23 | Root-level and tools/ scratch files (tmp*, _*). |
| `superseded` | 20 | The private repo's old tools/release_installer copy; the live installer is this repo's own tools/release_installer. |
| `local_state` | 14 | Maintainer and agent-local state (.codex, .cursor, .claude, checkpoints, the in-game check queue, the private repo's CI, .gitattributes). |

`EXPORT_MANIFEST.json` lists the excluded files by folder and reason.

These scripts contain a decompiler or disassembly marker, so they are left out. Some may only parse
such output rather than quote it; they stay out until each one has been reviewed:

- `experiments/cpp2il_readable_csharp/README.md`
- `experiments/cpp2il_readable_csharp/build_address_map.py`
- `experiments/cpp2il_readable_csharp/build_semantic_index.py`
- `experiments/cpp2il_readable_csharp/test_pipeline.py`
- `experiments/olden_cs_recovery/olden_cs_recovery/lifter/ir_build.py`
- `experiments/olden_cs_recovery/olden_cs_recovery/replay.py`
- `tools/public_source_export/export_public_source.py`

Because of these exclusions:

- **The source does not build or run as it is.** The plugin compiles against BepInEx IL2CPP interop
  assemblies, which are generated from your own copy of Heroes of Might & Magic: Olden Era. Its
  `.csproj` points at the maintainer's local game and tool folders, such as `V:\SteamLibrary\...`.
- **No game content is included.** The asset pipelines need your own copies of HoMM3 (Complete or HD)
  and Olden Era. Many tools also read from local working folders such as `V:/olden_port_work/...` or
  from the excluded `artifacts/` tree, so expect to change those paths.
- **Some pipelines are only partly here.** Folders whose generated output was excluded keep their
  scripts, configs and docs.
- **Docs describe the private workspace.** Paths, proof states and dates in `docs/` and `AGENTS.md`
  refer to that workspace and to the date each doc was written.

## Sanitization

Every file comes from a committed revision, never from uncommitted work. The export fails if any file
contains a secret-shaped token. It replaces the maintainer's user-profile folder with `<user>`, e-mail
addresses with `<email>` or `<maintainer-email>`, and the live bug-report relay deployment id with
`<relay-deployment-id>`.

## License

No license has been chosen for this folder yet. Until one is added, the code is visible but all rights
are reserved.
