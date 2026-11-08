# Agentic Handoff: Olden Era Playtest Tweak / Golden Era

Last verified: 2026-05-28.

This is a handoff for another agentic coding tool. It is meant to orient the next agent quickly, not replace the detailed reference docs. Use it with `AGENTS.md`, `docs/AGENT_REFERENCE.md`, and `docs/OLDEN_ERA_PLAYTEST_AGENTIC_KNOWLEDGE_BASE.md`.

## Project Shape

This workspace is the private development and integration repo for the Golden Era mod for Heroes of Might and Magic: Olden Era. The public GitHub project is `leviritchie/Golden-Era`.

The core mod is a BepInEx 6 IL2CPP Harmony plugin:

```text
OfflineUnlockMod.dll
```

The normal local build output is:

```text
Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/bin/Release/netstandard2.1/OfflineUnlockMod.dll
```

The plugin is source-built from:

```text
Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/
```

The mod combines:

- managed C# runtime hooks for the current obfuscated IL2CPP game build,
- generator-owned `Core.zip` data overlays,
- HoMM3/VCMI/HotA source assets converted into Unity bundles and plugin payload files,
- a WinForms self-extracting public installer that creates a separate Golden Era game copy.

Do not treat this repo as a clean install root. The old local playtest runtime was intentionally removed. The live Steam/runtime truth is the dedicated Steam release install:

```text
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era
```

Older paths, temporary snapshots, and copied repos under `tmp/` can be useful evidence, but they are not automatically authoritative.

## Source Of Truth Rules

Use these priority rules before changing anything:

1. Runtime bug triage starts from current `Player.log`, `LogOutput.log`, deployed `OfflineUnlockMod.dll`, deployed `config.json`, and the packed live `Core.zip`.
2. Data generation fixes belong in generator scripts, especially `tools/release_port/apply_release_core_overlay.py`, faction-specific deploy/build scripts, and validator scripts.
3. Obfuscated method/member names belong in `GameSymbols.cs` or similarly centralized semantic registries. Do not scatter raw obfuscated names through hook code.
4. Avoid fallbacks that hide contract drift. For runtime patches, fail closed when a required current symbol or asset route is missing.
5. For game behavior, identify the root route first. If the only available solution is a patch around unknown behavior, ask the user explicitly before implementing it.

## Main Local Paths

Private dev source:

```text
V:\Games\Olden Era Playtest Tweak
```

Plugin source:

```text
Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod
```

High-value docs:

```text
AGENTS.md
docs\AGENT_REFERENCE.md
docs\OLDEN_ERA_PLAYTEST_AGENTIC_KNOWLEDGE_BASE.md
docs\rag_chunks\
docs\homm3_faction_plans\
docs\homm3_future_faction_porting_source_of_truth.md
docs\homm3_custom_unit_mechanics_trace.md
docs\steam_hotfix_ui_surface_diff.md
```

Public release repo snapshot sometimes present locally:

```text
tmp\golden-era-release-repo
```

This snapshot may hit Git safe-directory protection. Do not assume its git status is readable until `safe.directory` is configured or you use the GitHub connector/API.

## Build And Local Validation

Build from the plugin project directory or pass the project path explicitly. Repo-root `dotnet build` commonly fails because there is no solution at the root.

Common compile command:

```powershell
dotnet build -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --nologo
```

Use no-deploy/compile-only options when the game is running or when you do not want to mutate the deployed plugin. If a change affects release behavior, verify against the Steam release install and packed artifacts, not only source files.

Useful validation entry points:

```text
tools\validate_custom_faction_manifests.py
tools\release_port\validate_custom_faction_design_contract.py
tools\verify_patch_surfaces.py
```

Read `Player.log` for map-load and battle-init failures. `LogOutput.log` is useful, but it can miss the decisive Unity/IL2CPP exception.

## Release Architecture

There are two related release lanes:

1. Private/dev repo lane: builds plugin source, generates or deploys mod assets and Core overlays, and validates live runtime behavior.
2. Public `leviritchie/Golden-Era` lane: stores the sanitized release input payload and builds the downloadable installer through GitHub Actions.

The public release package is now a single self-extracting installer EXE plus a `.sha256` file. Do not restore the old assumption that the release is a zip containing adjacent install scripts and payload folders.

Current public release input shape in the Golden-Era repo:

```text
release_inputs\golden_era_release_payload.zip
release_inputs\golden_era_release_payload.zip.sha256
```

That payload contains:

- `payload/BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll`
- BepInEx/IL2CPP loader files,
- Doorstop/runtime bootstrap files,
- plugin assets and manifests,
- `core_overlay/manifest.json` plus overlay member payloads.

The local root of this private workspace still has an older `release_inputs/stronghold_release_payload.zip`. Treat that as historical unless the task explicitly concerns the old Stronghold-only lane.

## Public GitHub Release Flow

The public release workflow is tag-driven in `leviritchie/Golden-Era`.

Current workflow file:

```text
.github\workflows\release.yml
```

It runs on `v*` tags and manual dispatch, verifies `release_inputs/golden_era_release_payload.zip.sha256`, publishes the installer with .NET 8 on `windows-latest`, appends the release payload into the installer EXE, uploads artifacts, attests provenance, and publishes a GitHub Release for tags.

Important scripts in the public release repo:

```text
tools\release_installer\refresh_release_inputs.ps1
tools\release_installer\package_from_release_inputs.ps1
tools\release_installer\export_release_core_overlay.py
```

Release input refresh is maintainer/local-machine work. It needs:

- a locally modded Steam release game root,
- a verified clean Steam `Core.zip` supplied as `-CleanReleaseCore`,
- the deployed plugin folder under that game root.

Before replacing `golden_era_release_payload.zip`, the refresh path must sanitize private/local paths, exclude backup files, `.pdb`, `.py`, `.pyc`, `.meta`, `.tmp`, `.log`, `.flag`, `.disabled`, and other maintainer-only artifacts, and verify the payload still contains the plugin DLL, custom faction manifests, `homm3_import.json`, bundles, BepInEx core, Doorstop runtime, and Core overlay manifest.

Before tagging a public release:

1. Refresh or verify `release_inputs/golden_era_release_payload.zip` and `.sha256`.
2. Build a local installer with `package_from_release_inputs.ps1`.
3. Smoke-test the local EXE install path if installer behavior or payload shape changed.
4. Commit payload and release tooling changes.
5. Push `main`.
6. Create and push a `v*` tag.
7. Poll the GitHub Actions workflow until it reaches success or failure.
8. Verify the GitHub Release assets exist and the asset names match the tag.

Do not call a release done after only pushing a tag. The workflow can still fail after the tag exists.

## Current Status On 2026-05-28

Local private workspace:

- Branch: `main`.
- Recent private dev commits include Quick Play faction row spacing, detail unit preview normalization, hero specialization normalization, nested hero profile portraits, Quick Play hero details portraits, enemy stack selector portraits, Quick Play custom hero labels, and hero map sprite reload liveness.
- `Plugin.cs` still declares `PluginVersion = "0.1.295"` in this private checkout.
- The worktree is very dirty at handoff time. It includes many source changes, generated/binary changes, asset sidecars, and untracked scratch/artifact folders. Do not stage broad changes blindly.
- The private root `release_inputs` folder contains the older Stronghold payload, not the current public Golden Era payload.

Public GitHub release:

- Repository: `leviritchie/Golden-Era`.
- Latest verified release from the GitHub API: `v0.1.302`, published `2026-05-28T04:11:23Z`.
- Latest release assets:
  - `GoldenEraModInstaller-v0.1.302.exe`
  - `GoldenEraModInstaller-v0.1.302.exe.sha256`
- The local public repo snapshot's payload manifest, when inspected directly, used format `hommoe-golden-era-release-overlay-v1` with `7428` overlay operations.

Functional status:

- The current public package includes many HoMM3-inspired factions, with Stronghold still the most mature reference implementation.
- Recent development has been focused on UI/visual correctness for Quick Play, unit previews, hero portraits, detail windows, release town UI, custom biome/runtime contracts, and generated no-debt faction data.
- Known public-facing issues still exist. The README-level status includes map enemies sometimes turning sideways, uneven faction tuning, occasional no-HUD map loads requiring reload, town menu back-arrow issues, and other early-access defects.

## High-Risk Areas

Do not make broad fallback fixes in these areas:

- selected-unit HUD and action bar,
- custom biome terrain/material registration,
- town UI visibility and navigation,
- Quick Play pooled UI rows,
- unit detail/recruitment preview donor aliases,
- map-object town and dwelling billboards,
- battle visual replacement and facing,
- custom faction mechanics debt cleanup,
- release payload filtering.

Typical bad fixes:

- changing donor battle-template mappings to fix a UI portrait symptom,
- re-enabling global `Image.sprite` hooks,
- treating missing visual output as an asset-copy problem before checking the manifest/runtime route,
- reverting custom factions to donor biome IDs to get map load,
- clearing mechanics debt by deleting debt metadata or changing text only,
- adding shape-only obfuscated method fallbacks instead of central symbol updates,
- editing `Core.zip` by hand instead of fixing the generator.

## Issue Hygiene

The public repo uses conservative GitHub issue hygiene. Preserve the automated reply prefix exactly when replying:

```text
[beep boop! This is an automated response. The repo owner will read the post when he has time]
```

Suggestions and balance changes should usually be logged locally instead of answered on GitHub. Actionable bugs should be verified with logs/config/payload evidence before claiming a fix.

Relevant local automation notes may live under:

```text
C:\Users\<user>\.codex\automations\github-issue-hygiene\
```

Use `issue_hygiene_notes.md` there before posting duplicate issue comments.

## Safe Next-Agent Checklist

Before modifying code:

- Read `AGENTS.md` and the nearest relevant doc under `docs/`.
- Run `git status --short` and classify unrelated dirty changes.
- Verify whether the task targets private dev source, deployed Steam runtime, or public GitHub release packaging.
- Inspect current live artifacts for runtime questions.
- Trace code/data ownership before patching.

Before testing:

- Send the current diff to a high-reasoning GPT-5.5 review agent before testing, asking it to check for hallucinated requirements, symptomatic patches, mismatch between stated and implemented behavior, and regressions from earlier work. If that exact model is unavailable in the next tool, use the configured highest-reasoning equivalent rather than skipping the review.

Before committing:

- Stage only files you intentionally changed.
- Avoid committing generated/binary payload changes unless they are the point of the task and have been verified.
- Include doc updates for durable findings and warnings.

Before public release:

- Verify payload checksum.
- Build the local installer.
- Smoke-test installer behavior when relevant.
- Push `main`, push the `v*` tag, then poll Actions to terminal state.
- Verify release assets on GitHub.
