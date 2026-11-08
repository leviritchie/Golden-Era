# Unit preview rendering — traced from Il2Cpp `Hex` interop (Playtest)

This document records how **Olden Era’s unit preview stack** is wired at the type level (Il2CppInterop `Hex.dll`), how it ties to **OfflineUnlockMod** hooks, and what made HoMM3 billboard swaps hard to see.

Sources:

- `tools/homm3_import/DumpHexTypes/` — small `net6.0` tool that reflects `Hex.dll` (run `dotnet build` then `DumpHexTypes.exe`).
- In-repo contract notes: `tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md` (`UiModelsSpawner` / first-child scale).
- Mod code: `Homm3ImportUnitPreviewModelHook.cs`, `Homm3ImportClbPreviewFactoriesHook.cs`, `Homm3PreviewApplyNextFrame.cs`, `EsquireBattleVisualPresentation.cs`.
- Runtime evidence: `BepInEx/LogOutput.log` (wrapper lines show `activeSelf` / layers / bounds).

Shipped game **C# source is not in this repo**; names below are **interop names** (some obfuscated: `bebc`, `cgei`, `hqv`, …).

---

## 1. Core types

### `clb` (`FullName: clb`, extends `MonoBehaviour`)

The preview **rig** is itself a **MonoBehaviour** on a scene object, not a plain DTO.

| Member (interop) | Role |
|-------------------|------|
| `GameObject Rotatable` | Turntable / platform the unit sits on (logged as `platform`). |
| `GameObject Model` | The actual unit instance (vanilla prefab or replacement). |
| `MeshRenderer Background` | Backdrop card behind the unit. |
| `String Sid` | Unit / mesh key string. |

Implication: replacing `Model` is correct, but anything that treats `clb` as “data only” misses **scene hierarchy**, **active state**, and **camera-facing** behaviour that live on the host `GameObject`.

### `Hex.Session.Battle.BhUnitWindowPreview` (unit detail window)

Important members:

| Member | Approximate role |
|--------|------------------|
| `clb cgei` | Current preview rig instance used by this window. |
| `Void Show(UnitViewConfig _viewConfig)` | Opens / refreshes preview for a config. |
| `clb bebc(String a, Transform b)` | Factory: spawn / resolve a `clb` for a string id + parent transform. |
| `Hex.UI.BhUnitPreview cgel` | UI-side preview host (camera + layer). |
| `Hex.Render.UnitPreviewRotation cgep` | Struct: rotation tuning. |
| `Hex.Render.UnitPreviewCameraControl cgeq` | Struct: camera distance / framing tuning (not the `Camera` object itself). |

Mod hooks: Harmony **postfix** on `Show` and `bebc` → `Homm3ImportUnitPreviewModelHook`.

### `Hex.BhUnitPreviews` (shared preview service)

| Member | Approximate role |
|--------|------------------|
| `clb prefab` | Template `clb` used to clone rigs. |
| `List<…> cams` | Preview cameras (type erased as `List\`1` in dump). |
| `Texture bozv` | Likely last / shared output for UI (RT or atlas slot). |
| `clb hqv(UnitViewConfig a)` | **Factory** returning a configured `clb` for a `UnitViewConfig` (recruitment / hire paths). |
| `Boolean hqr(String a, Single b, clb& c)` | Alternate path: string + float + **out** `clb`. |
| `Texture hqw(String a)` | Texture lookup by string (icon / snapshot pipeline). |

Historical non-`OFFICIAL_DEOBF_BUILD` path: `Homm3ImportClbPreviewFactoriesHook` patches `hqv`/`hqr`. It is compiled out of the established Golden Era profile and must not be presented as the active preview route. Current Golden Era preview ownership belongs to the signature-discovered synthetic mesh/window hooks.

### `Hex.UI.BhUnitPreview`

| Member | Role |
|--------|------|
| `beb cam` | Reference to the **preview camera** (type `beb` in interop). |
| `GameObject root` | Root object for the preview scene subtree. |
| `Int32 layer` | **Dedicated Unity layer index** for this preview rig (see logs: often `31` on `platform` / backdrop). |

This is the strongest hint that **layer + camera culling mask** must agree for any replacement mesh; copying only the **vanilla mesh’s layer** can diverge from the **host’s configured preview layer** in some UIs.

---

## 2. End-to-end flow (conceptual)

1. **Config arrives** (`UnitViewConfig` with `mesh` / `mapMesh` paths).
2. A **factory** runs:
   - **Army / detail window:** `BhUnitWindowPreview.bebc(sid, transform)` and/or `Show` → fills `cgei`.
   - **Recruitment / other UI:** often `BhUnitPreviews.hqv(UnitViewConfig)` (and possibly `hqr` with string).
3. The factory instantiates / configures **`clb`**: parents **Rotatable**, spawns **Model** (usually `ResManager` / `units/...` prefab), assigns **Background**.
4. **`BhUnitPreview`** (on the window) owns **`cam`** and **`layer`**: the camera’s **culling mask** and/or target setup are aligned with that layer.
5. **RenderTexture or direct camera render** (implementation inside `beb` / `BhUnitPreviews` IL) samples the rig for UI.

---

## 3. What OfflineUnlockMod does (and ordering)

1. **Postfix** on factory methods receives a live **`clb`** (never the shared **`BhUnitPreviews.prefab`** template — guarded).
2. `TryApply` enqueues **`ExecuteReplace`** on **`Homm3PreviewApplyNextFrame`**, which drains in **`LateUpdate`** (after most `Update` logic) to reduce races where vanilla resets **`Model`** in the same frame.
3. **`ExecuteReplace`**:
   - Instantiates HoMM3 **`battle`** template and **`MoveGameObjectToScene`** into the preview rig’s scene when needed.
   - Parents under vanilla **Model**’s parent (or `Rotatable` / `clb.transform`).
   - Copies **local pose** from vanilla, syncs presentation from **`EsquireBattleVisualPresentation`**, picks **dominant donor** renderer, copies **renderingLayerMask**, applies **`SyncMeshSortingFromDominantVanillaMesh`**, sets **Unity layer** from **`Rotatable`**, **`clb` root**, reflected **`BhUnitPreview.layer`**, or dominant vanilla mesh, then **`ConfigurePreviewRenderers`**.
   - For **`Sprites/Default`** quad billboards, builds a runtime **`Hex/Lit`** material with the same **`mainTexture`** so the preview camera’s lit pass can show the creature.
   - Aligns feet in Y, scales to donor bounds, **`SetActive(false)`** on vanilla (no **`Destroy`** — pooling / city UI safety).
   - Sets **`preview.Model = instance`**.

---

## 4. Why this was “challenging” (concrete issues)

### A. Multiple factories, one visual contract

Recruitment did not use `BhUnitWindowPreview.bebc` only; **`BhUnitPreviews.hqv`** is a separate entry point. Without patching every factory, some screens stayed vanilla.

**Also:** **`BhUnitPreviews.hqr`** (`bool` + `ref clb`) is patched **only on success** (`__result == true`) so failed lookups are not touched. Combined with **no `Destroy`** on vanilla models, this avoids the earlier city UI regression.

### B. `clb` is a `MonoBehaviour` timing bomb

`Show` / `hqv` can return while **`Model` is still inactive** (`activeSelf=false`) — the UI enables it on the next frame or when the panel opens.

The mod previously did:

```csharp
instance.SetActive(vanilla.activeSelf);
```

If vanilla was **inactive at replace time**, the HoMM3 instance stayed **inactive forever** → **invisible** preview even though logs showed a valid quad and material.

**Fix (applied in mod):** force `instance.SetActive(true)` for these replacements (same idea for `Homm3ImportPreviewWindowHook`).

### C. Layer / sorting / backdrop depth

Logs showed **Background** and **Rotatable** often on **layer 31**, while the **dominant vanilla mesh** could be **layer 0**. The preview **camera** may include multiple masks, but **sorting / Z** of a `Sprites/Default` quad vs a **Hex/Particles** backdrop can still hide the unit **behind** the card in world space even when “correct” in isolation.

**Fix (applied):** prefer **`clb.Rotatable.layer`** for `ApplyLayerRecursive`, and **`SyncMeshSortingFromDominantVanillaMesh`**.

**Pooling:** do **not** `Destroy` the vanilla **`Model`** when swapping — `BhUnitPreviews` / `clb` reuse expects the object graph to stay coherent; **`Destroy`** caused **broken city UI** (missing controls) after leaving the city. The mod only **`SetActive(false)`** on vanilla.

The mod aligns **feet in Y** (`AlignFeetToVanilla`) but does not explicitly resolve **Z fight** with `Background.bounds`.

### D. First-child `UnitViewConfig.scale` (UiModelsSpawner contract)

Documented in `ESQUIRE_STOCK_VISUAL_CONTRACT.md`: spawner logic can **overwrite the first child’s `localScale`** from `UnitViewConfig.scale`. HoMM3 bundles must put authored scale on a **nested** child (`billboard/quad`), not the first child.

### E. No shipped C# decompile in-repo

Understanding required **reflecting `Hex.dll`** under `BepInEx/interop` (net6) — Framework PowerShell could not load those assemblies (`System.Runtime` mismatch).

---

## 5. Suggested follow-ups (if issues remain)

1. **Z vs backdrop:** log **`Background.transform`** vs **`Model` bounds** and add a small **local Z** nudge toward the camera if the quad’s world bounds sit **behind** the backdrop center (logs showed large backdrop Z vs small model Z).
2. **`BhUnitPreview` int `layer` property:** if `Rotatable` is absent but `BhUnitPreview` is an ancestor, consider reading that **int** (not `GameObject.layer`) via reflection — interop may expose a custom preview-layer value separate from Unity’s object layer.
3. **Late `Model` reassignment:** if the game overwrites **`clb.Model`** after our deferred replace, add a narrow postfix on the **`Model` setter** or re-queue replace when **`Show`** completes (heavier).

---

## 6. Tool output snapshot (abbrev.)

`DumpHexTypes.exe` (trimmed):

- `clb` : `Rotatable`, `Model`, `Background`, `Sid`.
- `BhUnitWindowPreview` : `cgei` (`clb`), `Show`, `bebc`, `cgel` (`BhUnitPreview`), `cgep`, `cgeq`.
- `BhUnitPreviews` : `prefab`, `cams`, `bozv` (`Texture`), `hqv(UnitViewConfig)`, `hqr(String, Single, ref clb)`, `hqw(String)`.
- `BhUnitPreview` : `cam` (`beb`), `root`, `layer`.

Regenerate when the game updates: rebuild Il2Cpp interop and re-run **`DumpHexTypes`**.
