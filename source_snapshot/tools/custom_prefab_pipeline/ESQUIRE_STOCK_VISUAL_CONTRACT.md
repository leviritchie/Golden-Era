# `esquire` stock visual contract (for Pikeman / custom swap)

## Runtime load path (decompiled: `Hex.UI.UiModelsSpawner`, `Hex.Map.MapSquad` / `BattleObjectPool`, etc.)

- **Resource key** is always `ResManager.Get<GameObject>(path)` with  
  `path = "units/" + {mesh or mapMesh from `esquire` view data}`.
- Shipped `esquire` uses:
  - **Battle** (`mesh`): `Humans/1Prefabs/esquire` → `units/Humans/1Prefabs/esquire`
  - **Adventure map** (`mapMesh`): `Humans/1Prefabs/esquire_map` → `units/Humans/1Prefabs/esquire_map`

Battle preloading (pool) builds the same `units/...` string from `UnitViewConfig.mesh` / `meshVariants` (`PrepareForBattle` in decompiled `BattleObjectPool`).

## `UiModelsSpawner` / `BhUnitPreviews` contract (UI previews, hire, etc.)

- `UiModelsSpawner.Spawn(string _path, ...)` does `ResManager.Get<GameObject>($"units/{_path}")`, then `Instantiate` and applies **child** scale: if `scale > 0`, the first child’s `localScale` is set to `sign * scale` (keeps only sign of template axes, multiplies by `UnitViewConfig.scale`).

A replacement **battle** prefab should therefore match the same root/child pattern as stock (at least one child for scale).

**Important:** that spawner logic typically **replaces the first child’s `localScale` magnitude** with `UnitViewConfig.scale` (keeping only the **sign** of the prefab’s axes). Authoring a large `localScale` on the **first child** often has **no effect** on size. Put the mesh on a **nested child** (e.g. `billboard` → `quad`) and set **`localScale` on the inner transform** so the final size is `(game scale) × (inner scale)`.

**OfflineUnlockMod battle swap:** do **not** copy the vanilla instance’s first-child transform onto the bundle prefab — that overwrites the nested `quad` layout above and can make the unit **too thin** or wrong-sized. Correct fix is in **`battle.prefab`** / bundle rebuild (see commit `44051fa` message in history).

## Battle prefab: 3D render pipeline (materials & billboards)

Olden Era’s **battle** view is a **3D forward-style** setup. Stock units (e.g. swordsman / esquire) are drawn with the same pipeline as other **mesh** creatures. Custom bundle art must match that path or it will look invisible, wrong-layer, or broken.

- **Shaders that work in practice**
  - **`Hex/Lit`** — the game’s own lit shader (preferred for consistency with shipped units).
  - **`Sprites/Default`** — Unity’s legacy sprite shader; still runs in **Forward** and is a workable fallback for texture-on-quad billboards.
- **Geometry**
  - Use a **`MeshRenderer`** on a **flat quad mesh** (Unity’s built-in Quad / plane with two triangles), with your creature texture on the material.
  - Do **not** rely on **`SpriteRenderer`** for **`battle.prefab`** in the bundle: it is not the same rendering path as the stock 3D battle units, and often **will not show** (or will behave inconsistently) in combat.
- You can still source art as **sprite textures** (PNG); assign them to a **material** on the **MeshRenderer**, not to a `SpriteRenderer` component.

## Adventure `map.prefab`: same 3D billboard contract as battle

World-map stacks use the same **`ResManager` / `units/.../esquire_map`** pipeline as battle uses for `esquire`, but the **3D forward** pass still applies: **`SpriteRenderer`-only map billboards are fragile** (wrong layer/sorting, import-as-sprite clobber, or pipeline mismatch).

- **Authoring:** mirror **`battle.prefab`**: root → **`billboard`** → **`quad`** with **`MeshFilter`** (built-in quad mesh), **`MeshRenderer`**, and a material cloned from **`battle_billboard_mesh.mat`** (or the same template) with **`_MainTex`** set to a **Default** (non-sprite) texture import.
- **Automated:** after copying `EsquireBillboardAnimatorBuild.cs` into the Unity project, menu **Olden Era → Custom Units → Rebuild Esquire Map Mesh Billboard** (or run **`build_esquire_bundle.cmd`**, which runs the map pass at the end of **`RebuildFromBatch`**). That regenerates **`Generated/MapBillboard/Materials`**, **`MapIdle`** clip, **`EsquireMapBillboard.controller`**, and rebuilds **`map.prefab`** with a looping flip-book on **`billboard/quad`** (prefers **defextract JSON**: group **2** idle first so the map does not use battle **walk**; else group **0** movement; otherwise all PNGs in folder order with a warning).
- **Map DEF vs battle DEF:** they are **different assets** in typical HoMM3 / HotA pipelines — adventure-map creatures use a compact **map/world** DEF (often one walk/movement group), while combat uses the full **battle** DEF (idle, attacks, hits, death, directions). Point **`MapFramesFolder`** at the folder produced from the **map** extract (e.g. `extracted_map/.../avwpike.dir` + `avwpike.json`); the build falls back to **`FramesFolder`** only if that folder is missing (wrong art for map, but keeps the batch usable).
- Tune **`MapQuadLocalScale*`** / **`MapQuadLocalPosition*`** in the script for world-map size and foot placement vs battle.

## Timing / six-direction attacks (data)

- `esquire` view JSON: `attackTimeBefore` and `attackTimeAfter` are length **6** (directional attack windows).
- `esquire` logic: melee attacks do **not** key off per-variant `animationIndex` in the decompiled `esquire` logic (standard melee).

A full custom rig should still try to preserve **animator state names and directional attack coverage** from the stock `esquire` prefab; extract the shipped battle prefab in Unity/AssetStudio from `units/Humans/1Prefabs/esquire` and mirror its `Animator` / clip set when building the HoMM3-style or retargeted replacement.

## HoMM3-style animation (billboard / quad + `MeshRenderer`)

HoMM3 creatures are **flip-book**: each animation is a **sequence of full-frame PNGs** (your `extracted_…/00_XX.png` trees). Olden Era still expects a Unity **`Animator`** on the **root** battle object (your `battle.prefab` already has one) and drives it like stock units — so the win is to **keep the stock state machine contract** and only swap **what each clip does**.

### 1) Discover the game’s expectations (once)

- Extract the **shipped** `units/Humans/1Prefabs/esquire` battle prefab (AssetStudio / UABE / etc.) and inspect its **`Animator`**:
  - **Animator Controller** topology (states, transitions, **exact state names**).
  - **Parameters** (bools, triggers, ints) the battle code uses.
- Goal: your replacement controller should use the **same state names and parameters**, so battle logic does not need a mod.

### 2) Turn DEF/PNG sequences into Unity clips

For each stock state you must support (idle, move, hit, death, attacks, …):

1. Import PNGs as **Texture2D** (point filter if you want crisp HoMM3 pixels).
2. Create an **`AnimationClip`** that animates the quad’s material’s **main texture**:
   - In the Animation window, add a curve for **`MeshRenderer.material._MainTex`** (or the renderer on your **`quad`** child) and key **object references** to each frame texture in order, **discrete** keys (HoMM3 is typically ~10 FPS; use `Edit → Snap Settings` / key spacing or set clip frame rate to match).
3. Loop flags: **idle** / **move** loop; **attack** / **hit** / **death** usually clamp.

Alternative: one **sprite atlas** per creature + clip that keys **`_MainTex_ST`** (UV rect) or a small custom shader property; fewer files, more setup.

**`SpriteRenderer` path (e.g. `EsquirePikemanPrefabBuilder`):** `TextureImporter.spritePixelsPerUnit` controls world size as **pixels ÷ PPU** (lower PPU → larger on screen; **25** is a practical starting point for HoMM3-sized frames vs Unity’s default **100**). Use a **bottom** sprite pivot **`(0.5, 0)`** so the transform sits at the feet. **`MeshRenderer` + `Texture2D` import** ignores PPU — size is **quad `localScale`** only. Any remaining vertical offset after rebuild: mod **`esquirePikemanBattleBillboardExtraY`** (and bounds alignment in `OfflineUnlockMod`).

### 3) Wire the Animator on `battle`

- Assign an **`AnimatorController`** to the root **`Animator`** (same GameObject as today).
- States = stock names; each state plays the clip you built (or a blend tree if stock uses direction).
- **Directional melee** (HoMM3 `attack_up` / `attack_front` / `attack_down`): mirror however **stock esquire** selects them (often separate states or a blend tree driven by a **float/int parameter**). Match that, don’t invent new parameter names unless you also patch game code.

**Automated flip-book pass (this repo + `oldenera_factions`):** copy `tools/custom_prefab_pipeline/unity_editor/EsquireBillboardAnimatorBuild.cs` into the Unity project’s `Assets/Editor/` (or keep the project copy in sync), then either use menu **Olden Era → Custom Units → Rebuild Esquire Battle Billboard Animator**, or run `tools/custom_prefab_pipeline/build_esquire_bundle.cmd`.

On each rebuild, **`EsquireBillboardAnimatorBuild`** **reimports** every `*.png` under the frames folder as a **Default** texture for **`MeshRenderer` + `_MainTex`**: point filter, no mipmaps, alpha transparency, uncompressed (crisp HoMM3 pixels). It does **not** overwrite **`battle.prefab` → `billboard/quad`** transform anymore — a new DEF often changes canvas size / margins, so you **tune `localScale` / `localPosition` on `quad` in Unity** and rebuild; an earlier version of the script reset the quad to `(4,4,1)` every time and could **erase** the scale that matched stock units. To reset the quad from script constants, use menu **Olden Era → Custom Units → Apply Battle Quad Defaults** (edit `BattleQuadLocalScale*` / `BattleQuadLocalPositionY` in `EsquireBillboardAnimatorBuild.cs` first if needed).

**GUI controller parity (parameters / transitions / blend trees):** the build **does not** author a flat replacement `AnimatorController`. It requires a **one-time AssetStudio export** of the shipped esquire battle controller:

- **Reference path (Unity project):** `Assets/CustomUnits/esquire/Reference/StockEsquireBattle.controller` (plus any dependent `.anim` clips AssetStudio emits — see `Assets/CustomUnits/esquire/Reference/README.txt` and `tools/custom_prefab_pipeline/unity_editor/StockEsquireBattle_IMPORT.txt`).
- **Output:** `Assets/CustomUnits/esquire/Generated/BillboardAnim/EsquireBattleBillboard.overrideController` — an **`AnimatorOverrideController`** over that stock asset. Only motions whose **clip `name`** matches a generated flip-book clip are swapped; the graph stays identical to stock.
- **Prefab:** `battle.prefab` root **`Animator.runtimeAnimatorController`** is set to that override; `applyRootMotion` stays `false`.
- A legacy flat `EsquireBattleBillboard.controller` under `Generated/BillboardAnim/` is **deleted** on rebuild if still present.

Clip **names** used for override matching match shipped inventory (`tools/reference/stock_esquire_animator_inventory.txt`): `Walk_idle`, `esquire_walk`, `esquire_attack`, `esuire_damage`, `esquire_death`. Stock-only names (e.g. campaign map clips) stay unmapped until you add a generated clip with the same name; the builder logs a **warning** per missing name.

**Stock `AnimatorController` (Reference/):** try **`tools/AssetStudioCLI/try_export_stock_esquire_animator_headless.cmd`** first; on the Olden Era demo it usually exports no controller — then run **`tools/AssetRipper/pipeline_esquire_reference_headless.cmd`** (full headless rip + copy into `Reference/`, optional `RUN_UNITY=1` for the bundle build) or **AssetStudio.GUI** (see `StockEsquireBattle_IMPORT.txt`). AssetStudio maps/clips: `bootstrap.cmd`, `build_asset_map.cmd`, `export_esquire_clips.cmd`.

**Optional git:** to avoid committing game-exported binaries, use `Assets/CustomUnits/esquire/Reference/.gitignore` (ignore everything except `README.txt` and the ignore file itself — see that folder in `oldenera_factions` if present).

### 4) Pivot and framing

- Keep **feet / contact** stable: HoMM3 frames often share canvas size; your **`quad`** offset + scale (nested under **`billboard`**) should stay consistent across clips so the creature doesn’t “slide” between idle and attack.

### 5) Content checklist (HoMM3 parity)

Use the same logical set as classic creatures: **idle**, **movement** (loop), **attack** variants, **hitted**, **death**, optional **defence**, **movement start/end**. **HoMM3 ground truth** for frame boundaries is the **`defextract_py3.py` output** (`*.json` + `GG_FF.png` group indices), summarized with **`tools/defextract_summarize_groups.py`** and mapped to roles via [VCMI creature animation groups](https://vcmi.eu/modders/Animation_Format/). The Unity menu builder **`EsquireBillboardAnimatorBuild`** reads that **sibling `.json`** when present and builds clips from VCMI group ids; if the JSON is absent, it falls back to sorting all PNGs and legacy heuristic slices.

## Harmony override (this repo)

- `OfflineUnlockMod` loads a local `custom_units_esquire` **AssetBundle** and swaps Esquire visuals via narrow hooks (e.g. **`dzk.bath`** for battle, **`UnitViewConfig.rtd()`** for map when enabled) — see `EsquirePikemanVisuals.cs` / `EsquirePikemanBattlePoolHook.cs`. Patching **`ResManager.Get<GameObject>`** generically is avoided (Il2CPP generic trampoline issues). **Battle HoMM3 SFX** (bundle clips, clip-driven playback, volume, pitfalls) are documented in **`CUSTOM_UNIT_BATTLE_SFX_RUNTIME.md`**.

This avoids editing `Core.zip` while keeping the same `mesh` / `mapMesh` keys.

### `LauncherConfig` (mod `config.json`) for Esquire

- **`esquirePikemanVisuals`** — master switch for the Esquire bundle and registration paths (off by default).
- **`esquirePikemanApplyHarmony`** - when true, immediately registers the narrow battle-pool, shared ResManager GameObject, UnitView, and battle-animator hooks. There is no active delayed registration path.
- **`esquirePikemanDeferPatch`**, **`esquirePikemanDeferBySceneLoad`**, **`esquirePikemanDeferSceneLoadSkips`**, and **`esquirePikemanDeferPatchFrames`** are legacy parsed values in the current source. They are assigned but do not control registration and must not be used as a runtime timing contract.
- **`esquirePikemanDeferResManagerOffsetFrames`** is also a legacy parsed/clamped value. The current registration path never schedules the old frame-delayed generic ResManager prefix.
- **`esquirePikemanSwapAdventureMap`** (default `true`) — set **`false`** to keep stock `esquire_map` on the **adventure map** and only replace the **battle** prefab (if `map.prefab` mismatches the stock hierarchy / child indices).
- **`esquirePikemanUnityErrorCorrelator`** (default `false`) — when `true`, each Unity `Error` / `Exception` / `Assert` also records a one-line **Esquire state** (last `ResManager` get for `esquire` paths, patch flags) in `BepInEx/plugins/OfflineUnlockMod/esquire_unity_correlator.log` next to the Unity message and Unity's stack. Use for **order-of-events**; the **definitive** file + line in game code is still the **full stack** in `Player.log` / the Unity log line (or ILSpy/dnSpy on the named Hex type in the stack).
- **`esquirePikemanPrewarmBundle`** / **`esquirePikemanDiagnostics`** — A/B: load the bundle in `Plugin.Load` and/or append TSV to `BepInEx/plugins/OfflineUnlockMod/esquire_diagnostics.log` (look for `PrewarmEnd` with `battle=true map=true` when the file is on disk and valid).
- **`esquirePikemanSpawnerReflectionProbe`** — log `Hex.UI.UiModelsSpawner` `Spawn` methods to the BepInEx log (obfuscation / signature discovery).
- **`esquirePikemanNarrowUiSpawnerHook`** (experimental) - registers a UI-preview-only `UiModelsSpawner` postfix when enabled. It does not cover map stacks or the battle pool and is independent of the retired ResManager deferral path.

- **`esquireBattleSfxVolume`** (0–1, default **0.45**) — linear gain for Esquire bundle battle `AudioSource` SFX (`LauncherConfig` / mod `config.json`). See **`CUSTOM_UNIT_BATTLE_SFX_RUNTIME.md`**.

Current registration proof is the immediate narrow-hook registration log. The older scene/frame defer markers are retired and must not be expected.

## Manual QA (after deploy)

1. Build `OfflineUnlockMod` (copies `custom_units_esquire` when `build_out/custom_units_esquire` exists).
2. Launch the playtest with BepInEx; confirm log line `EsquirePikeman: loaded bundle from ...`.
3. **Adventure map**: stack with `esquire` as top creature — should use `map.prefab` from the bundle.
4. **Battle**: start a fight with esquires — pool should use `battle.prefab`.
5. **UI**: city hire / unit info preview — should still show the unit (uses the same `units/...` keys).
6. **Edge cases**: upgrade line to `man_at_arms` unchanged; only `esquire` sid uses this mesh override unless you extend the hook.
