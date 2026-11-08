# iCloud cold-data offload: finding and restoring a set

Operational recipe. The tools live outside the repo, in `V:\olden_port_work\`:

- `icloud_offload.ps1` moves folders into iCloud Drive and waits until every file is online-only.
- `cold_offload_sweep.py` is the repeatable entry point. It discovers cold folders or takes a list you give it, runs
  the dependency trace, archives large sets, and then calls `icloud_offload.ps1`.

Offloaded data lives under `V:\iCloud\iCloudDrive\olden_offload\`.

## 1. Find the set

`olden_offload\INDEX.txt` has one tab-separated line per offloaded source. The columns are: time, original source
path, size/file count, and offload destination.

```powershell
Select-String -Path V:\iCloud\iCloudDrive\olden_offload\INDEX.txt -Pattern 'homm3_owned_bind'
```

There are two kinds of set:

- **Raw.** The source column is the original folder, for example `...\artifacts\town_scene_rollback\tower_x`. The
  destination folder holds the files exactly as they were.
- **Archive (sweep-produced).** The source column is a staging folder,
  `V:\olden_port_work\offload_staging\<label>`. The destination `<...>\<label>\` holds:
  - `<label>.7z.001`, `.002`, ... : 7-Zip volumes, with paths relative to the root.
  - `manifest.tsv` : the first line is `# root<TAB><dir>`, followed by one row per file: relpath, size, mtime, sha256.
  - `sources.txt` : the original folders, with byte and file counts and any warnings the trace raised.

  To find which archive holds a given folder, search the `sources.txt` files:
  `Select-String -Path V:\iCloud\iCloudDrive\olden_offload\*\*\sources.txt -Pattern '<folder>'`.

## 2. Re-hydrate (download)

Do one of the following:

- Open the folder in Explorer and choose "Always keep on this device".
- Run this, then wait until the files are no longer online-only:

  ```powershell
  attrib -U +P /S /D "V:\iCloud\iCloudDrive\olden_offload\<set>\*"
  ```

  Check progress with `attrib` on a big file: `U` means online-only, `P` means pinned local.

Size the download first: hydrating writes the full set to V:. Keep at least 25 GB free.

## 3. Put it back

**Raw set.** Move the folder back to the source path from INDEX.txt. This is a same-volume move, so it is instant:

```powershell
Move-Item "V:\iCloud\iCloudDrive\olden_offload\<set>\<leaf>" "<original parent>\"
```

**Archive set.** Extract into the manifest root (the repo for repo sets), then verify every file against its sha256:

```powershell
& "C:\Program Files\7-Zip\7z.exe" x "V:\iCloud\iCloudDrive\olden_offload\<set>\<label>\<label>.7z.001" -o"<root from manifest.tsv>"
python V:\olden_port_work\cold_offload_sweep.py verify-restore "V:\iCloud\iCloudDrive\olden_offload\<set>\<label>"
```

Use `-o` with a scratch directory, plus `verify-restore --root <scratch>`, to inspect an archive without touching the
repo.

Once the data is back and verified, delete the iCloud copy if you want, and add a note to INDEX.txt
(`restored <date> <path>`).

## 4. Making a new offload

```powershell
python V:\olden_port_work\cold_offload_sweep.py sweep --dry-run                 # discover under artifacts/, print
python V:\olden_port_work\cold_offload_sweep.py sweep --dry-run --paths artifacts/x/y tmp/z   # curated list
python V:\olden_port_work\cold_offload_sweep.py sweep --name <label> [--paths ...]  # really offload
```

The sweep keeps a folder local when any of these holds; the module docstring has the details:

- A scope file names it: tools/, docs/, custom_factions/, scenarios/, the plugin tree, or AGENTS.md. This includes
  unit configs, catalogs, and installed records.
- An artifact record names it: recent records, town candidate stage reports and catalogs, rollback catalogs, or
  delivery selections.
- A scope file uses its leaf name as a path token. This blocks in discovery mode and only warns with `--paths`.
- It was modified or created today.
- Every file in it is git-tracked. Tracked files are never moved.
- It is the newest town rollback.
- It looks like a secret, or contains `.git`.

`--allow-doc-refs` turns a reference that comes only from docs/ into a warning.

Archives are made when a set is 2 GB or larger, has 500 or more files, or contains tracked files. They are written as
3 GB 7-Zip volumes and verified with `7z t` plus a name and size match against the manifest before any source is
deleted. Waves keep V: at 25 GB free or more.

Proof tier: the pack, verify and restore path has been checked on a self-test set only.
