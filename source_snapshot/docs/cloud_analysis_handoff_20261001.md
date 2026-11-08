# Cloud analysis input handoff

## Destination and scope

Target chat: `01a0f471-cebf-7037-99ff-3f42675c10fd`, host `durable`, title
`Set up golden_era`. User authorized supplying this existing cloud chat and
explicitly approved private Google Drive transfer on 2026-10-01.

Purpose: static exploration of current Golden Era capabilities, including
abandoned law-tree possibilities, with the user's requested LunaSwarm / GPT-6.1
Sol configuration. This handoff does not authorize mod deployment or claim
runtime behavior. Research swarm launch was deferred during readiness setup.

## Delivered inputs

Local evidence folder: `artifacts/cloud_analysis_handoff_20261001/` (ignored).
`prepare.ps1` captures an explicit input set, checks source stability, records
SHA-256 and provenance, archives inputs, and splits the archive into six parts
below the cloud ingest limit. Do not rerun over existing output files.

- Installed Golden Era native binary and metadata, Unity player/executable,
  Core.zip, global game managers and selected generated interop (including Hex).
- Current dirty-worktree plugin source, custom-law target/profile inputs,
  ability overrides, source pilots, surface navigation skills and relevant docs.
- Historical law/semantic dossiers, interop maps and method-address indexes.
- Actual local LunaSwarm Python client/server, installed skill and contract,
  isolated API tests, packaging metadata and coordination CLI. No old database.

Archive: `olden-era-analysis-inputs.zip`, 184934904 bytes.
SHA-256: `be4542e99fc9fbb508a4906c9bd89b1fd0e8c2f4b7c7cc4853d3787ca9d5be23`.
The archive has 512 payload files plus `input-manifest.json`.
`transfer-manifest.json` lists each ordered part, byte length and hash.

Private Drive folder:
<https://drive.google.com/drive/folders/1Uh5rJ4zK8nnKEKNprPwniNL4pc9TzB9p>.
Folder and all six parts were read back as unshared with owner-only permission.
No public sharing or Git LFS upload was used. Authenticated file references were
sent directly to the cloud chat; transient bearer URLs are not recorded here.

## Verification

- Local: all 512 archive entries matched captured source size and SHA-256.
- Cloud: all six parts, combined archive, and 512 extracted files matched size
  and SHA-256, reported by the destination chat during setup.
- Cloud: LunaSwarm isolated API suite passed all four tests and cleaned its
  temporary database. Existing local swarm state was not transferred.
- Cloud: a real `gpt-6.1-sol` delegation readiness probe completed without
  substitution or simulated worker records. No swarm research was launched.
- Cloud: UnityPy, pefile, Capstone, LIEF and ILSpy were installed and exercised
  on supplied files. Il2CppDumper processed the current binary/metadata pair
  (metadata version 31) and produced fresh dumps and 108 dummy assemblies.
- Destination final setup report: scoped static investigation ready; API tests
  passed 4/4 twice. Full cloud evidence is in its `READINESS.md`. Ghidra remains
  uninstalled. Reusable setup was saved as an environment draft; publication
  and persistence across a new environment are not claimed here.

## Evidence boundaries and omissions

Core.zip is the current **modded installed** payload, not pristine stock OE.
Source reflects this local dirty worktree, not necessarily cloud checkout HEAD
or installed plugin behavior. The source manifest records repository HEAD and
each file's content hash; no unrelated local changes were reverted.

Existing August static dossiers still match the installed native and Hex hashes,
but their exact current metadata provenance is not established. Installed
metadata and Core changed later. The cloud must validate or refresh the old
analysis against the delivered current binary/metadata and reread current Core.
Prior custom-faction law plans are historical context, not proof of abandoned
stock law-tree implementation. Static findings never imply runtime/gameplay proof.

Scene/sharedassets, resources.assets, streamed art, full Unity interop, large
ISIL trees, logs, saves, credentials, installed mod bundles, and existing swarm
chats/database were deliberately excluded. This is sufficient to begin native
code/Core static analysis, not an exhaustive replica or runnable game install.
