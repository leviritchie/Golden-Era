# Esquire `custom_units_esquire` (headless Unity)

This folder drives **batchmode** rebuild of battle/map **meshes** and **ESQUIRE_** sound prefabs into `build_out/custom_units_esquire`.

## Unity Editor binary

- **Pinned version:** `6000.0.66f2` (matches `oldenera_factions/ProjectSettings/ProjectVersion.txt` and `build_out/*.manifest`).
- **Default path (Windows):**  
  `%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe`  
  e.g. `C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe`
- Override: set **`UNITY`** to the full path of `Unity.exe` before running the script.

## Unity project (`oldenera_factions`)

Resolved **first match wins** (same as `build_esquire_bundle.cmd`):

1. **`OLDENERA_UNITY_PROJECT`** — absolute path to the folder that contains `ProjectSettings/ProjectVersion.txt`
2. **Repo-local:** `<git repo root>/oldenera_factions`  
   For this workspace: `V:\Games\Olden Era Playtest Tweak\oldenera_factions`
3. **Legacy:** `C:\Users\<user>\oldenera_factions` (optional second clone)

`oldenera_factions` is gitignored at the repo root; create it or symlink/junction it beside `tools/`.

## Run the full pipeline

- **cmd:** `tools\custom_prefab_pipeline\build_esquire_bundle.cmd`
- **Git Bash:** `bash tools/custom_prefab_pipeline/build_esquire_bundle.sh`  
  (from repo root; the script resolves paths itself.)

Optional **`HOMM3_SND`** if `Heroes3.snd` is not at `<repo>/HoMM 3 Complete/Data/Heroes3.snd`.

Logs: `unity_esquire_sound_prefabs.log`, `unity_esquire_anim_build.log`, `unity_esquire_bundle_build.log` next to the scripts.

## What runs (order)

0. Stage WAVs into `Assets/CustomUnits/esquire/sounds/` (optional)  
1. Copy `unity_editor/*.cs` → `%PROJECT%/Assets/Editor/`  
2. Unity: **`EsquireBattleSoundPrefabsBuild.RebuildFromBatch`**  
3. Unity: **`EsquireBillboardAnimatorBuild.RebuildFromBatch`**  
4. Unity: **`BuildCustomUnitBundles.BuildFromManifest`**

**See also:** `CUSTOM_UNIT_BATTLE_SFX_RUNTIME.md` — bundle sound prefabs, manifest checks, and mod-side clip-driven SFX (Esquire reference; reuse for other units).
