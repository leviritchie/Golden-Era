# HoMM3 / HotA Pikeman → Olden Era `esquire` (crewmate-style export)

## Ground truth for “which frames are idle / walk / attack?”

The project’s extractor is **`tools/defextract_py3.py`** (Python 3) or **`tools/defextract.py`** (legacy). It does **not** guess ranges: it parses the binary **`.def`** and writes:

- **`<name>.dir/`** — PNGs named **`GG_FF.png`** (`GG` = DEF block / animation **group**, `FF` = frame within that group).
- **`<name>.json`** — machine-readable list: `sequences[]` with `{ "group", "frames": [...] }`.

**Semantic meaning of each `group` id** (movement vs idle vs hit vs death vs attack facings) is the standard HoMM3 layout documented by **VCMI**:

- [Animation Format — Creature animation groups](https://vcmi.eu/modders/Animation_Format/)

After extraction, print a readable table (frame counts per group + VCMI labels):

```text
python tools/defextract_summarize_groups.py path/to/your_extract/avwpike.json
```

**Unity builder:** `EsquireBillboardAnimatorBuild` (menu **Olden Era → Custom Units → Rebuild Esquire Battle Billboard Animator**) looks for **`<same_base_name>.json`** next to `FramesFolder` (e.g. `…/extracted_avwpike/avwpike.json` beside `…/avwpike.dir/`). If present, clips use **DEF groups** (idle=2, movement=0, hitted=3, death=5, melee attack prefers group 12 then 11/13). If the JSON is missing, it logs a warning and uses the **legacy** “sort all PNGs + heuristic slices” path.

## Approach

- **Fidelity to HoMM3 battle art** is best with the same **DEF → PNG clips → billboard** workflow as [../crewmate/README.md](../crewmate/README.md), but for **`battle.prefab`** in Olden Era you must output a **3D-pipeline** billboard: **`MeshRenderer` + quad mesh** and a material using **`Hex/Lit`** (game shader) or **`Sprites/Default`** — not a **`SpriteRenderer`**. See [../../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md](../../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md) (“Battle prefab: 3D render pipeline”).
- Retarget a humanoid 3D rig only if you are matching the **stock `esquire` animator** in Unity.
- **VCMI (this repo) does not contain** the classic `PIKEMAN.DEF` bytes. Copy battle DEFs from your **local Heroes III / HotA** `Data` / `Maps` / mod `Content` tree the same way the crewmate manifest references `hota/cove/...`.

## Provenance hints (config-only)

- **Adventure (HotA new graphics)**: `vcmi/Mods/hota/mods/newGraphics/.../newCreatureAnimations.json` maps `core:pikeman` map animation to:
  - `hota/castle/adventureMap/creatures/AvWPike.def`
- **Battle**: use the file present in your install (e.g. core `PIKEMAN.DEF` or HotA’s castle creature battle DEF). Point `source.battleAnimation` in `manifest.json` at that path before running your DEF extraction script.

## Pipeline

1. Point `manifest.json` `source` fields at your on-disk DEF files.
2. **Battle art (this repo):** Castle Pikeman is **`cpkman.def`** inside **`H3sprite.lod`** (not a loose `PIKEMAN.DEF`). Bundled installs live next to this project:
   - `Olden Era Playtest Tweak/HoMM 3 Complete/Data/H3sprite.lod`
   - `Olden Era Playtest Tweak/vcmi/Data/H3sprite.lod` (fallback if Complete folder is absent)  
   One-shot: run **`tools/extract_battle_pikeman_for_esquire.cmd`** (extracts `cpkman.def` → PNGs + JSON, copies into `oldenera_factions` as `extracted_avwpike/avwpike.*`). Then rebuild the animator / bundle.  
   Manual: `python tools/lod_extract_entry_py3.py "<path>/H3sprite.lod" cpkman.def ./cpkman.def` then `python tools/defextract_py3.py ./cpkman.def ./out`. Summarize: `python tools/defextract_summarize_groups.py ./out/cpkman.json`.
3. In Unity `oldenera_factions`, wire clips into `Assets/CustomUnits/esquire/battle.prefab` / `map.prefab` and rebuild the bundle with [../../custom_prefab_pipeline/custom_units_manifest.json](../../custom_prefab_pipeline/custom_units_manifest.json).

## Sounds

- Optional: set `source.sound` to `.wav` paths under your H3/VCMI install; wire through the game’s audio data separately if you replace creature SFX (not part of the mesh `ResManager` path).
