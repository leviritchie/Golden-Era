# Custom unit battle SFX — build, bundle, and runtime (Esquire learnings)

This document captures what we verified and implemented for **HoMM3-sourced battle sounds** on **custom AssetBundle units** (Esquire as the reference implementation). Use it as a checklist when adding **other units** the same way.

Related docs and code:

- Build order and Unity version: `tools/custom_prefab_pipeline/BUILD.md`
- Battle/map prefab and rendering contract: `tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md`
- Unity bundle batch entry points: `tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs`, `EsquireBattleSoundPrefabsBuild.cs`, `EsquireBillboardAnimatorBuild.cs`
- Mod runtime: `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` (`EsquirePikemanVisuals.cs`, `EsquirePikemanBattlePoolHook.cs`, `EsquireBattleAudioPlayer.cs`, `EsquireBattleClipAudioDriver.cs`, `EsquireBattleAnimatorSetHook.cs`)
- **Lane B (HoMM3 import):** same clip-driven runtime for lab bundles — `tools/homm3_import/stage_homm3_unit_audio.py`, `unity_editor/Homm3BattleSoundPrefabsBuild.cs`, `Homm3LabBattleAudioPlayer.cs`, `Homm3LabClipAudioDriver.cs`, `Homm3ImportVisuals.cs`, `Homm3ImportBattlePoolHook.cs`; stems `HOMM3_<unitSid>_` under `Assets/CustomUnits/homm3_lab/<unitSid>/sounds/`.
- Animator parameter name → `Animator.StringToHash` (Unity 6000): `tools/reference/AnimatorStringToHash_report.tsv`

---

## 1. Goals and constraints

- **Goal:** Play unit-specific battle SFX (attack, hit, walk loop, death variants, victory) for a **custom battle prefab** loaded from a **sidecar AssetBundle**, without routing through shipped `Hex.Sound.*` APIs (avoid brittle game coupling and mixer graph assumptions).
- **Constraint (IL2CPP):** Avoid `Animator.parameters`, `GetParameter`, and similar APIs that can throw under Il2CppInterop; use **integer hashes** from `Animator.StringToHash("literal")` aligned with the stock controller, or drive audio from **animation clip names** (see §6).
- **Constraint (pooling):** Battle instances may be **reused**; hooks must **attach** behaviours on both **first swap** and **reuse** paths.

---

## 2. Asset pipeline — what must be in the bundle

### 2.1 Unity inclusion rule (`BuildCustomUnitBundles`)

For each `unitSid` in `custom_units_manifest.json`, the batch builder:

1. Adds the **battle** and **map** prefab paths from the manifest.
2. Calls `AddSoundsForUnit`, which scans **`Assets/CustomUnits/<unitSid>/sounds/`** and **`Assets/CustomUnits/homm3_lab/<unitSid>/sounds/`** for **prefabs only** (`t:Prefab`), not raw WAVs.

Raw WAVs (or OGG) under `sounds/` are turned into **one small prefab per SFX** by `EsquireBattleSoundPrefabsBuild` (GameObject + `AudioSource` + `clip`); the **bundle must list those `.prefab` paths** or the game mod will never see `AudioClip` sub-assets the way we load them.

### 2.2 Validate the built bundle (do not skip this)

Open **`tools/custom_prefab_pipeline/build_out/<bundleName>.manifest`** (Unity’s YAML manifest). Under **`Assets:`** you must see:

- `Assets/CustomUnits/<unit>/battle.prefab`
- `Assets/CustomUnits/<unit>/map.prefab` (if you ship map in the same bundle)
- **Every** `Assets/CustomUnits/<unit>/sounds/<STEM>.prefab` you expect

If the manifest lists **only** `battle.prefab` / `map.prefab`, the bundle was built **before** sounds existed, from a project **without** `sounds/`, or a **partial** build step was skipped. The mod can index zero clips regardless of runtime code quality.

### 2.3 Full local rebuild (Windows)

- `tools/custom_prefab_pipeline/build_esquire_bundle.cmd` (or `.sh`)
- Copies `build_out/custom_units_esquire` next to the plugin when you build/deploy the mod (`OfflineUnlockMod.csproj` `DeployPluginToGame` target), or copy manually to `BepInEx/plugins/OfflineUnlockMod/`.

---

## 3. Billboard battle motion vs. stock animator triggers

### 3.1 Stock battle controller parameters

Stock `_Battle_Unit_Anim_ctrl_v2` uses **lowercase** triggers/bools such as **`attack`**, **`damage`**, **`die`**, **`victory`**, **`move`** — not legacy PascalCase. Hashes for Unity 6000 are summarized in `tools/reference/AnimatorStringToHash_report.tsv`.

Harmony postfixes on `Animator.SetTrigger` / `SetBool` are **valid** for stock 3D units that actually **set those parameters**.

### 3.2 Esquire billboard path (critical)

The custom **flip-book** battle unit built by `EsquireBillboardAnimatorBuild` drives states primarily via **`Animator.Play(stateHash, …)`** on clip names such as:

- `22.Idle`, `01.Walk`, `14.Attack`, `20.Damage`, `21.Death` (see `GeneratedClipNames` in `EsquireBillboardAnimatorBuild.cs`)

In logs, you will see **`Animator.Play`** / **`CrossFade`** telemetry, often **without** corresponding **`SetTrigger("attack")`**-style writes on that hierarchy.

**Lesson:** For billboard-style units, **do not rely solely on Harmony `SetTrigger`/`SetBool` postfixes for SFX**. Either:

- **A (implemented for Esquire):** A small **`MonoBehaviour`** on the **`battle`** root reads `Animator.GetCurrentAnimatorClipInfo(0)` each frame (we used **`LateUpdate`**), picks the **dominant clip by weight**, and on **clip name change** dispatches SFX; or  
- **B:** Harmony-postfix `Animator.Play` / `CrossFade` and map **state hashes** to categories (more work; hashes are not always equal to `Animator.StringToHash(clipName)` for short vs full path).

We chose **A** for clarity and robustness: `EsquireBattleClipAudioDriver` → `EsquireBattleAudioPlayer.OnBillboardDominantClipChanged(string clipName)` with substring rules (`attack`, `damage`, `death`/`die`, `walk`, `idle`, `victory`).

### 3.3 Avoid double playback

If **both** clip-driven code **and** `SetTrigger`/`SetBool` Harmony postfixes call `PlayOneShot` for the same action, you get **stacked** audio.

**Lesson:** Pick **one** dispatch path per unit style. For Esquire we removed audio side-effects from `EsquireBattleAnimatorSetHook` and kept those patches **verbose-logging only**.

Optional safety net: a **short per-category debounce** (we use **100 ms** unscaled time) on `PlayOneShot` to absorb any remaining double edges during transitions.

---

## 4. Runtime mod architecture (Esquire reference)

### 4.1 Clip and stem indexing (`EsquirePikemanVisuals`)

- Load bundle with `AssetBundle.LoadFromFile`.
- Index **`AudioClip`** assets by **stem** (filename without extension), e.g. `ESQUIRE_Attack_1`, for lookup by `EsquireBattleAudioPlayer.BuildCategoryIndex`.
- **`AssetBundle.LoadAllAssets` / name filtering alone** can miss clips that live only as **sub-assets** on sound prefabs; the final indexer also **harvests** from prefabs / known paths as needed (see implementation and comments in `EsquirePikemanVisuals.cs`).

### 4.2 Battle pool swap (`EsquirePikemanBattlePoolHook`)

- Postfix on the narrow **`dzk.bath`** (or equivalent) path used for **`units/.../esquire`** battle prefabs.
- **Instantiate** the bundle `battle` template, reparent to match vanilla, optionally sync presentation, **`Destroy` vanilla**, replace refs.
- **`EsquireBattleAudioPlayer.TryAttach(battleRoot)`** and **`EsquireBattleClipAudioDriver.TryAttach(battleRoot)`** must run on:
  - **New** swapped instance, and  
  - **Reuse** when the pool returns an existing custom instance (`LooksLikeOurBundleBattleInstance`).

### 4.3 Hierarchy and “where is `battle`?”

The animator may live under **`ROOT/Unit/battle/...`**, so **`transform.root`** is **not** the battle prefab root.

**Lesson:** Walk **parents** for a GameObject named **`battle`** (and tolerated clone names like `battle (clone)`). Implemented as `EsquireBattleAudioPlayer.FindBattlePrefabRoot` + `RootNameIsBattle`.

### 4.4 Audio playback (`EsquireBattleAudioPlayer`)

- Two `AudioSource`s: **one-shot** and **loop** (walk).
- **`spatialBlend = 0`** (2D) was chosen so SFX are not lost to **3D distance attenuation** on a billboard that may not match vanilla listener geometry.
- **Volume** is scaled by launcher/mod config **`esquireBattleSfxVolume`** (0–1, default **0.45**), threaded through `LauncherConfig` → `EsquirePikemanVisuals.Configure` → static **`BattleSfxVolume`**, applied when sources are configured and refreshed on play paths.
- **Il2Cpp:** register injected types with **`ClassInjector.RegisterTypeInIl2Cpp<T>`** before `AddComponent` (see `EnsureEsquireBattleAudioPlayerTypeRegistered` / clip driver registration in `EsquirePikemanVisuals.cs`).

### 4.5 Optional animator telemetry

`EsquireBattleAnimatorTelemetry` (verbose-only) helps confirm **which controller** and **which clips** are active; it is **not** required for audio once the clip driver exists.

---

## 5. Configuration (launcher + mod `config.json`)

Keys that matter for this feature (see `LauncherConfig.cs` for the full schema):

| JSON key | Role |
|----------|------|
| `esquirePikemanVisuals` | Master enable for Esquire bundle path. |
| `esquirePikemanApplyHarmony` | Enables Harmony patches including pool hook and animator logging. |
| `esquireBattleSfxVolume` | **0–1** linear gain for Esquire battle `AudioSource.volume` (default **0.45**). |
| `esquirePikemanVerbose` | Enables extra logging / telemetry (noisy). |

**Note:** `BepInEx/plugins/OfflineUnlockMod/config.json` is often **gitignored**; ship defaults in `OfflineUnlockMod/publish/config.json.example` and document keys in this file.

---

## 6. Diagnostics you already proved in practice

| Symptom | Likely cause |
|---------|----------------|
| Log: **indexed 0** clips | Bundle manifest has **no** `sounds/*.prefab` entries, or indexer still not seeing clips (prefab sub-assets / path mismatch). |
| Log: **indexed N** clips, `EsquireBattleAudioPlayer: ready`, but **no sound** | Motion driven by **`Animator.Play`** / clip blends, **not** `SetTrigger` — add clip-based driver or postfix `Play`. |
| Sound **twice** | **Two** dispatch paths (e.g. clip driver **+** `SetTrigger` Harmony) or transition edge; use **one** path + optional debounce. |
| Sound **too loud** vs vanilla | Our sources at full digital level; reduce **`esquireBattleSfxVolume`** and/or author quieter source WAVs. |

Log file: `BepInEx/LogOutput.log` (plugin category `HeroesOE Offline Unlock`).

---

## 7. Checklist — porting to another unit

1. **Unity:** `Assets/CustomUnits/<sid>/sounds/` with **prefabs** (or your pipeline’s equivalent), plus `battle.prefab` / `map.prefab` as needed.
2. **Manifest:** `custom_units_manifest.json` (or per-unit manifest) with correct `unitSid`, `bundleName`, prefab asset paths.
3. **Build:** Run full batch pipeline; open **`build_out/<bundle>.manifest`** and confirm **every** sound prefab path is listed under **`Assets:`**.
4. **Deploy:** Place bundle beside `OfflineUnlockMod.dll` (or rely on csproj copy from `tools/custom_prefab_pipeline/build_out/` when present).
5. **Mod:** Duplicate the **narrow** pool hook pattern for the new **`units/...`** path; attach **audio player** + **clip driver** (or equivalent) on the same **`battle`** root you identify.
6. **Clip naming contract:** Document **exact** `AnimationClip.name` strings your Unity builder emits; map them in `OnBillboardDominantClipChanged`-style logic (substring rules or explicit allowlist).
7. **Do not** assume `SetTrigger`/`SetBool` alone — verify with telemetry or Unity logs.
8. **Config:** Add a **per-unit or shared** volume key if multiple bundles differ in loudness.
9. **IL2CPP:** Keep avoiding `Animator.parameters`; prefer **hashes** or **clip names**.

---

## 8. File index (Esquire-specific)

| Area | File |
|------|------|
| Bundle asset list + sounds folder | `tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs` |
| WAV → sound prefab | `tools/custom_prefab_pipeline/unity_editor/EsquireBattleSoundPrefabsBuild.cs` |
| Flip-book clips + override controller | `tools/custom_prefab_pipeline/unity_editor/EsquireBillboardAnimatorBuild.cs` |
| Batch orchestration | `tools/custom_prefab_pipeline/build_esquire_bundle.cmd`, `build_esquire_bundle.sh` |
| Manifest | `tools/custom_prefab_pipeline/custom_units_manifest.json` |
| Bundle output | `tools/custom_prefab_pipeline/build_out/custom_units_esquire` + `.manifest` |
| Mod: bundle + clip index | `OfflineUnlockMod/EsquirePikemanVisuals.cs` |
| Mod: battle pool swap + attach | `OfflineUnlockMod/EsquirePikemanBattlePoolHook.cs` |
| Mod: SFX playback + clip dispatch | `OfflineUnlockMod/EsquireBattleAudioPlayer.cs` |
| Mod: dominant clip watcher | `OfflineUnlockMod/EsquireBattleClipAudioDriver.cs` |
| Mod: animator logging only | `OfflineUnlockMod/EsquireBattleAnimatorSetHook.cs` |
| Config | `OfflineUnlockMod/LauncherConfig.cs`, `OfflineUnlockMod/Plugin.cs` |

---

## 9. Version skew note

Unity **Editor** used for bundles may be **6000.0.66f2** while the **game** exe reports **6000.0.66f1** in BepInEx logs. In practice, **`Animator.StringToHash` for ASCII parameter names** matched; still re-verify hashes if you change Unity minor versions or controller source.

---

*Last updated from the Esquire battle-audio workstream (bundle manifest validation, clip-driven playback, volume + debounce, single dispatch path).*
