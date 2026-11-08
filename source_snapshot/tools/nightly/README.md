# Nightly Golden Era release

Unattended pipeline that builds the full Golden Era payload from a private commit, builds both
installers, checks them offline and, with `-Publish`, updates one rolling prerelease:
tag `nightly` on the public repo `leviritchie/Golden-Era`.

- The prerelease is never marked Latest. The stable release (currently v0.1.320) stays Latest, and
  the script checks that Latest is unchanged after it publishes.
- Gates are the nightly tier: compile, live-interop refs, the game-symbols hint gate, the payload
  gates and the sanitizer/leak gate. The full validator suite does not run.
- Nothing is deployed. The game is never started, attached to or stopped.
- The private repo is never pushed. The worktree is only read (`git archive`, `git log`).
- The Golden Era install and the 25672315 mirror are only read.

## Files

| File | Role |
| --- | --- |
| `nightly_release.ps1` | The pipeline. One entry point for the scheduled agent. |
| `build_plugin.ps1` | Clean-export plugin build, quick tier. `-ReleaseCandidate` builds the shipping code set. |
| `stage_release_payload.ps1` | Stages the full payload and runs every payload gate (the v0.1.319 recipe). |
| `payload_leaks.py` | `fix` sanitises local paths in JSON and CSV; `scan` fails on paths, usernames, emails and secrets. |
| `triage_reports.py` | Unpacks in-game bug-report bundles into a ledger and prints a digest. |
| `deploy_local.ps1` | Best effort: builds the maintainer DLL for a commit and swaps it into the local GE copy. Skips with exit 0 if the game is running, `golden-era-deploy` is claimed, the installed DLL is newer or identical, or the DLL is locked. |

## Commands

Run from any directory with `pwsh` 7 on PATH:

```
# dry run: everything except publishing; the assets are kept on N: for inspection
pwsh -NoProfile -ExecutionPolicy Bypass -File "V:\games\olden era playtest tweak\tools\nightly\nightly_release.ps1"

# publish the rolling nightly prerelease
pwsh -NoProfile -ExecutionPolicy Bypass -File "V:\games\olden era playtest tweak\tools\nightly\nightly_release.ps1" -Publish
```

The last line of the output is `NIGHTLY: PASS ...` or `NIGHTLY: FAIL exit=<code> class=<class> ...`.
The run summary is `N:\nightly\logs\<runId>\summary.json`, and a copy goes to
`N:\nightly\logs\latest_summary.json`.

Parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `-Ref` | `HEAD` | Private commit to build. Resolved once at start. |
| `-Publish` | off | Without it, the run stops after the assets are built and verified. |
| `-WorkRoot` | `N:\nightly` | All scratch. Must be on the drive labelled `GENightly`. |
| `-GameRoot` | Golden Era install | Read only: plugin content, BepInEx, Doorstop, modded Core.zip, Unity data. |
| `-CleanMirror` | 25672315 mirror | Read only: clean Core.zip pin and the headless-install source. |
| `-Homm3Root` | none | Enables the full headless install when N: also has room for it. |
| `-UntrackedInputsFrom` | `-Repo` plugin folder, else the main checkout's | Read only: git-ignored compile inputs (`publish_plugin\`, `tools\_dump_types\bin\`) passed to `build_plugin.ps1`. A linked worktree has none, so it falls back to the main checkout that owns its git dir. The stager's git-ignored dialog portrait inventory uses the same fallback. |
| `-KeepAssets` | off | Keep the asset folder after a publish. A dry run always keeps it. |
| `-KeepWork` | off | Debug: keep the build, stage and public clone. |

The version label is `nightly-YYYYMMDD-<shortsha>` (UTC date). It is used in:
- the plugin DLL's AssemblyInformationalVersion. `Plugin.PluginVersion`, the BepInEx version that bug
  reports carry, is a source constant and stays as committed.
- the payload base name, `golden_era_release_payload-<label>.zip` (its `.sha256` and
  `.download-manifest.json` assets). The nightly's parts are named by content instead,
  `golden_era_payload.<first 20 hex of the part's sha256>.part`, and the installer footer lists them,
  so each nightly installer is tied to its own parts while unchanged parts keep their names.
- the release title and notes.

The installers keep stable names (`GoldenEraModInstaller-nightly-upscaled-portraits.exe` and
`-standard-portraits.exe`). The release tag in their footer is `nightly`, so the download URLs are
`https://github.com/leviritchie/Golden-Era/releases/download/nightly/<part>`.

## Versioned release

The same pipeline builds a stable release when given `-ReleaseTag`:

```
pwsh -NoProfile -ExecutionPolicy Bypass -File <clean export>\tools\nightly\nightly_release.ps1 -Repo "V:\games\olden era playtest tweak" `
  -Publish -ReleaseTag v0.1.320 -Latest -NotesFile <public clone>\release_notes\v0.1.320.md `
  -ReleaseTitle "Golden Era v0.1.320 (Preview)" -ExpectPublicSha <public main sha>
```

- Assets: `golden_era_release_payload-v0.1.320.zip.partNN`, its `.sha256` and `.download-manifest.json`,
  and `GoldenEraModInstaller-v0.1.320-{standard,upscaled}-portraits.exe` (+ `.sha256`). The installer
  footers point at `.../releases/download/v0.1.320/`.
- Preflight: `Plugin.PluginVersion` at `-Ref` must equal the tag without the `v`; the tag and any
  release or draft of that name must not exist yet. Existing tags are never moved.
- Public clone: with `-ExpectPublicSha`, public main must be that commit. No workflow file at that
  commit may trigger on `push`, `release`, `create`, `schedule`, `workflow_run` or
  `pull_request_target`: GitHub runs tag and release workflows from the tagged commit, and the
  v0.1.319 assets were overwritten by exactly such a workflow.
- Notes: `-NotesFile` is used as written and goes through the leak scan.
- Publish: public main must still be the commit the installers were built from. The stale-payload
  guard refuses a payload whose sha equals the one in the previous stable release's or the current
  Latest release's `golden_era_release_payload*.zip.sha256` asset. The release is created as a draft
  at that commit, every asset is uploaded and checked (names, sizes, GitHub sha256 digests), and only
  then is it published as a full release (`--latest` with `-Latest`).
- Post-publish verification (`postPublishVerify`): waits `-SettleSeconds` (default 180), re-lists the
  release through the REST API and fails with exit 80 if any asset is missing, extra, resized,
  replaced (new asset id) or has a different digest, if the published `.sha256` or download manifest
  disagrees with the build, if the tag or Latest moved, or if `gh run list` shows any workflow run
  since the publish. The re-listed assets are in `summary.json` under `postPublish`.
- Nightly state (`lastPublishedSha`, the nightly notes base) is not changed by a versioned release.
  The last output line starts with `RELEASE:` instead of `NIGHTLY:`.

## Steps

1. **preflight**
   - Checks: N: is mounted with label `GENightly`; git, gh, dotnet, python, pwsh, powershell and
     Windows tar are present; `gh auth status` passes; the inputs exist.
   - Takes an exclusive lock on `N:\nightly\nightly.lock`. The OS releases it if the process dies.
   - Deletes the previous run's work (everything except `logs`, `reports`, `state.json` and
     `builds.json`).
   - Requires free space of at least the larger of: 2 x the measured staged sources + 2 GB, or
     1.05 x the last run's peak.
2. **build**
   - Runs `build_plugin.ps1 -ReleaseCandidate -InformationalVersion <label>` on a `git archive`
     export under `N:\nightly\work\build`.
   - In the csproj, `ReleaseCandidateBuild=true` forces the full validation tier. The nightly build
     removes that one coupling in the throwaway export only. The patch must match exactly once.
   - The DLL is then checked to contain no `Homm3LiveProbeWorkbench` or `live_probe_bridge` code.
3. **stage**
   - `stage_release_payload.ps1` uses the `tools/release_installer` scripts from the same commit,
     plus the git-ignored dialog portrait inventory copied from the checkout.
   - It applies the v0.1.319 deltas: the 25672315 clean Core pin; preview hooks and map squad
     controller kept; bug reporting kept, with only its shape asserted; OldenAiSim.dll scrubbed; and
     the owned-skinned coverage rule for the 3D-only neutrals.
   - Leftover filters drop `*.pre<digit|_>*`, `*.bak_*`, `*.force_*`, `*.npz` and `.foldercache`.
     They act on copy, and a prune pass catches anything that still reaches the stage.
   - `payload_leaks.py fix` replaces JSON-escaped, whole-value and embedded local paths in JSON and CSV
     files. CSV is included because v0.1.319 shipped
     `custom_factions/custom_law_homm4_icon_assignments.csv` with 93 absolute checkout paths.
   - `payload_leaks.py scan` checks every text file and the two first-party DLLs. The run fails on any
     absolute local path, users-folder path, maintainer folder name, email address, secret-shaped
     token, or the machine's username, computer name or git email. The terms are read at run time and
     never stored.
4. **zip**
   - Writes the zip with Fastest compression straight into the public clone's
     `dist\golden_era_release_inputs` (the packaging script requires the zip inside the clone).
   - The zip is deterministic: entries in ordinal path order (files plus empty folders, like
     `ZipFile.CreateFromDirectory`), every entry stamped 2026-01-01 00:00. An unchanged file gives
     the same entry bytes in every nightly. Each entry's local header offset is recorded for the split.
   - Then sha256 and a structure check: required entries and the overlay operation count.
   - The stage is deleted as soon as the zip checks out.
5. **installers**
   - Runs `package_from_release_inputs.ps1` from a fresh shallow clone of public `main`, once with
     upscaled and once with standard portraits.
   - The clone skips Git LFS (`GIT_LFS_SKIP_SMUDGE=1` and the lfs filters disabled). The public repo
     keeps old payload parts in LFS (about 3.7 GB), which N: cannot afford. A clone over 500 MB fails.
   - The packaging script runs under Windows PowerShell 5.1 with `PSModulePath` removed from its
     environment, so it loads its own modules and not pwsh 7's.
   - Settings: `-PackageVersion nightly -PayloadMode Download -PayloadBaseName golden_era_release_payload-<label>.zip`.
6. **split**
   - Splits the zip in place: it copies the last part out, truncates the zip, and repeats. What
     remains is renamed to the first part. Peak disk is the zip plus one part, never two copies.
   - Nightly cuts (incremental upload): a part ends before the first zip entry at or past
     `-ChunkMinBytes` (128 MB) whose path's MD5 first byte is 0 mod `-ChunkModulo` (8), or before the
     first entry at or past `-ChunkSoftMaxBytes` (512 MB). Local entry records hold no offsets, so a
     changed file changes only its own part; the central directory (which holds the offsets) is a
     part of its own. A single entry over `-MaxPartBytes` is sliced. Parts are named
     `golden_era_payload.<sha256 prefix>.part`, and both installer footers (JSON + int64 length +
     `GERADL01` at the end of the EXE) are rewritten to list them with their `partBytes`; the wizard
     accepts any plain file names whose sizes add up to the payload. A code-only nightly therefore
     makes only a few new parts.
   - Versioned releases keep uniform 1.9 GB `<base>.partNN` parts from the packaging script.
   - The packaging script needs the whole zip, so the parts cannot be written while the zip is
     being created.
   - Parts are hashed as they are written.
   - Writes `<base>.sha256` and `<base>.download-manifest.json`.
   - Both installer footers must match the parts exactly: names, sizes, payload sha and byte count.
7. **plan**
   - Runs `--print-plan` on both EXEs. Every URL must be `.../releases/download/nightly/<part>` for a
     part in the asset folder.
8. **verify**
   - A full `--headless` install needs the mirror size (7.2 GB) + 2 x the uncompressed payload + 1 GB
     free (the payload is extracted to a cache, then installed into the copy), plus a `-Homm3Root`.
   - N: (32 GB) cannot hold that next to the 10.5 GB of parts. So the run normally uses the
     installer's own `--verify-payload` from the asset folder: sha256 over the parts read as one
     stream, zip structure and overlay operation count, with no network (the download base URL is
     pointed at an unreachable local address).
   - The choice and the numbers are in `summary.json` under `installCheck`.
9. **notes**
   - Commit subjects since the last published nightly, or the last 3 days, filtered to user-facing
     fixes.
   - Dropped: anything mentioning tools, validators, gates, agents, reports, players or logs,
     anything with paths, URLs, emails or quotes, and any bug-report text.
   - The notes file goes through the leak scan.
10. **publish** (only with `-Publish`). It changes only the `nightly` release and tag:
    - Creates the prerelease if it is missing (`--prerelease --latest=false --target <public main sha>`).
    - Uploads the parts and payload manifests first, then the installers (`--clobber`, 3 tries each).
      A nightly part already on the release with the same name and size is not uploaded again (the
      name is its content hash). The summary records `reusedParts` and `uploadedBytes`.
    - Deletes assets that are not part of this run.
    - Moves the lightweight `nightly` tag to public `main`.
    - Sets the title and notes.
    - Then checks: exactly the expected assets with the right sizes, still a prerelease, Latest
      unchanged.
    - It refuses to touch a `nightly` release that is not a prerelease.
11. **cleanup**
    - `N:\nightly\work` is removed. A dry run keeps `work\assets`.
    - Kept: `logs\` (the last 10 run folders), `state.json` (last published sha, last run's peak),
      `builds.json` (label to scrubbed DLL sha, for triage) and `reports\`.

## Exit codes

| Code | Class | Typical cause |
| --- | --- | --- |
| 0 | pass | |
| 10 | preflight | N: missing or wrong label, tool missing, gh not logged in, not enough space |
| 11 | locked | another nightly run is active |
| 20 | build | compile error, quick-tier gate failure, RC marker in the DLL |
| 21 | build-timeout | plugin build exceeded `-BuildTimeoutMinutes` |
| 30 | stage | payload staging or a payload gate (pin, coverage, config, live parity) |
| 40 | sanitizer | leak scan hit, JSON sanitise failure, notes failed the scan |
| 50 | zip-split | zip creation, structure check or split |
| 60 | installers | public clone, packaging, footer mismatch, print-plan URL mismatch |
| 70 | install-verify | `--verify-payload` or the headless install failed |
| 80 | publish | gh failure, refused state, verification after publishing |
| 90 | unexpected | script error; see `failures` in the summary |

## Bug-report triage

```
python "V:\games\olden era playtest tweak\tools\nightly\triage_reports.py" <folder with oe-mod-bug-*.zip>
python "V:\games\olden era playtest tweak\tools\nightly\triage_reports.py" --all
python "V:\games\olden era playtest tweak\tools\nightly\triage_reports.py" --set-status <id> triaged
```

- Each new bundle is unpacked into `N:\nightly\reports\<id>\`. Only the known entry names are
  written. Plain relative paths are required, and sizes are capped.
- Every ID is recorded in `N:\nightly\reports\ledger.json` with its status.
- The digest groups reports by exception signature: exception type, first managed frame and
  normalised message. For each report it shows:
  - the truncated title and description
  - the plugin version
  - the build: the nightly label, resolved from the DLL sha256 in `payload_manifest.json` through
    `builds.json`
  - the top exceptions with counts
- A report whose signature matches an earlier one is marked `duplicate`.
- Report contents are untrusted data. They are only read as text or JSON and never run or opened
  with another program. The digest leaves out contact details. Never paste report text into
  release notes or commits.

## Permissions the unattended agent needs

- `pwsh -NoProfile -ExecutionPolicy Bypass -File ...\tools\nightly\nightly_release.ps1` with and
  without `-Publish`. Everything below runs inside that one command.
- `git`, on the private repo: `rev-parse`, `archive`, `log`, `merge-base` and `config` (all reads).
  On N: only: `clone` of the public repo. No `git worktree` and no push of either repo.
- `gh`, all on `leviritchie/Golden-Era`:
  - reads: `auth status`, `release view`, `api repos/.../commits/main` and
    `api repos/.../git/ref/tags/nightly`
  - writes: `release create nightly`, `release upload nightly --clobber`,
    `release delete-asset nightly`, `release edit nightly`, and
    `api -X PATCH repos/.../git/refs/tags/nightly`, which moves the nightly tag to public main and
    replaces a push of the tag.
- `dotnet build` (plugin) and `dotnet publish` (installer wizard, NuGet restore).
- `python` (stager, overlay export, DLL scrub, leak scan, triage).
- `powershell` 5.1 (the public packaging script) and Windows `tar`.
- Running the two built installer EXEs from `N:\nightly\work\assets` with `--print-plan` and
  `--verify-payload`. Add `--headless` only when `-Homm3Root` is given and N: has room.
  The wizard manifest asks for administrator rights. These modes only read the assets and write under
  N:, so the script starts them unelevated with `__COMPAT_LAYER=RunAsInvoker` set on that child only.
  No UAC prompt appears and no system setting changes.
- File writes only under `N:\nightly`. Reads of the private checkout, the Golden Era install and the
  25672315 mirror.
