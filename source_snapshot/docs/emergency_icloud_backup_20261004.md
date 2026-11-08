# Emergency iCloud Project Backup

Copy-only backup requested on 2026-10-04 because V: was behaving unexpectedly.
No project files were moved, removed, offloaded, or reverted. No game payload was
changed. This is a selected project recovery set, not an image of V: or the game
installation.

Destination: `V:\iCloud\iCloudDrive\olden_backups\20261004_project_emergency`.
On another device, use iCloud Drive / `olden_backups` / `20261004_project_emergency`.
The local sync folder is also on V:; local archive creation alone is not off-drive
protection. Cloud proof is recorded separately using the provider's read-only
`CF_PLACEHOLDER_STATE_IN_SYNC` state and an expected filename inventory.

## Contents

| Package | Coverage | Archive Size |
| --- | --- | --- |
| `01_tracked_worktree.7z` | 13,495 existing tracked files, including current uncommitted content | 0.988 GiB |
| `02_untracked_source.7z` | 1,452 additional source, configuration and documentation files | 0.004 GiB |
| `03_selected_artifacts.7z` | 895 selected unit/town assets, saved motion/capture data, provenance and delivery files | 11.189 GiB |
| `04_changed_source.7z` | Recapture of the two sources that changed during the first package | 7,709 bytes |
| `05_local_git_history.bundle` | Self-contained history for the 26 recorded local refs; saved HEAD `2ec88d05f68bf2f50f183b7abddd4f77a3a57706` | 8.486 GiB |
| `06_recovery_metadata.7z` | Selection lists, manifests, verification results, repository state/index and the one-run backup scripts | Small metadata package |

Each package has a SHA-256 sidecar. The four source/asset archives passed `7z t`.
Archive entries were checked against their selection manifests. One volatile
file in package 01 has a different size from its pre-pack metadata; package 04
recaptures both volatile files and its exact names/sizes match. Packages 02 and 03
had no missing or changed selected files while packing.

The Git bundle passed `git bundle verify` and a separate SHA-1 verification of
the complete PACK payload against its trailer. Its complete-history result means
the recorded local refs do not require prerequisite commits from another clone.
It does not preserve unreachable objects, Git LFS's object database, or all local
Git administrative state. The tracked release ZIP itself is included in package 01.

## Boundaries

- The worktree remained live. This is a best-effort capture, not a quiesced,
  transactionally consistent point-in-time snapshot. Files are restored in the
  package order below so the two recaptured files take precedence.
- 740 tracked paths were already absent from V: when selected. They are listed in
  package 01's manifest. The saved Git history preserves historical committed
  versions, but they were not silently restored into the current worktree.
- Artifact selection follows current unit manifests/import tables and town
  catalogs. It includes selected available source/final GLBs, textures, captures,
  records and existing delivery bundles, not the entire artifact history.
- Selection covers 78 current unit IDs / 92 fleet jobs. Thirty selected runs were
  already missing their expected raw capture. Missing registration/fit references
  were not recreated. Details are in `03_selected_artifacts.selection_notes.md`
  inside package 06.
- External Golden Era StreamingAssets map outputs, external Unity projects,
  installed game files, caches, virtual environments, dependencies, old rollback
  duplicates and arbitrary scratch were not backed up by this set. Source and
  configuration for scenario generation are included; this is not a full backup
  of installed campaign map output.
- Credential stores and common private-key filenames were excluded from the
  current-file selection. This is not a secret-content audit of ordinary source
  or Git history. The recovery set stays in the user's private iCloud Drive.
- Backup inclusion does not certify an asset's quality or gameplay behavior.

## Restore On A Healthy Drive

Download the backup folder from iCloud Drive to a healthy drive. Do not extract
back onto the suspect V: drive merely to test it. Preserve the downloaded set.
Check each `.sha256` against `Get-FileHash -Algorithm SHA256`, and run `7z t` on
the `.7z` packages before using them.

For a source recovery without Git, extract packages 01, 02, 03 and finally 04
into one new project folder. Paths inside the archives are project-relative.
Extract package 06 there too to retain recovery evidence.

For history as well, first run:

```powershell
git clone "<downloaded backup>\05_local_git_history.bundle" "<healthy drive>\Recovered Olden Era"
```

Then overlay packages 01, 02, 03 and 04, in that order. The clone can resurrect
the 740 paths that were absent from the original worktree; inspect the missing
list before deciding how to reproduce those deletions. Do not apply a blanket
delete to an existing checkout. The bundle contains multiple refs; use
`git bundle list-heads` and fetch required branches from it explicitly.

`repository_state.json` and `repository_index.bin` in package 06 record the
pre-receipt repository state. Keep the index as evidence; replacing the new
checkout's index is optional and requires understanding its staged/deleted state.
Later changes made by other active writers are outside this capture.

## Performance And Evidence

The source package took 85.35 seconds. Its initial peak-memory measurement was
not captured correctly and must not be interpreted as zero usage. The additional
source package took 3.63 seconds / 13.09 MiB peak working set. The selected-artifact
package took 58.88 seconds / 10.66 MiB peak working set, using stored data rather
than spending CPU recompressing already packed assets. No quality check was
relaxed. File packing, CRC/hash verification and copying are CPU/I/O operations;
no rendering, fitting or GPU job was launched. Git PACK verification took 18.42
seconds; the initial Git creation runtime/child peak RAM were not captured.
An 8 GiB free-space reserve was enforced before each archive.

The existing cold-offload tools were not used: they move files and remove source
directories. The initial Git bundle's atomic rename was blocked by iCloud's
active upload handle. Its complete file was retained, independently verified,
and renamed only after the provider finished; it was not repacked or discarded.

Evidence lane: `artifacts/emergency_icloud_backup_20261004/`. The expected final
filename set is `expected_cloud_files.txt`. Archive inventory results are
`archive_inventory_verification.json`. Cloud proof must be read from the final
`cloud_sync_receipt.json`; archive integrity alone does not prove upload.

Primary provider-state reference:
[Microsoft CF_PLACEHOLDER_STATE](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ne-cfapi-cf_placeholder_state).

Archive and bundle integrity are proven. Cloud completion is established only by
the expected-inventory check in `cloud_sync_receipt.json`, not by this document
or the presence of local sync-folder files.
