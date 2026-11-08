# Unity Billboard Export: Crew Mate

This folder is a Unity-friendly prototype export built from the extracted HoMM3/HotA creature DEF.

## Recommended First Import
- Import every PNG under `clips/` as a sprite.
- Keep the original transparent canvas size so the feet stay anchored consistently.
- Start with a bottom-center pivot.
- Start with `Pixels Per Unit = 100`.
- Start with `Filter Mode = Point` to preserve sprite edges.
- For a first playable prototype, use `idle`, `movement`, `hitted`, `death`, and `attack_front`.

## Prototype Notes
- `attack_up`, `attack_front`, and `attack_down` are directional melee variants from the original HoMM3 animation set.
- For a camera-facing cardboard-cutout prototype, `attack_front` is the simplest default attack clip.
- `movement_start` and `movement_end` are optional polish clips you can add before and after `movement`.

See `manifest.json` for clip metadata and source references.

## Olden Era `custom_units_esquire` / battle bundle

When the same clip workflow is used for **`Assets/CustomUnits/esquire/battle.prefab`**, build the in-combat billboard as **`MeshRenderer` + Quad** with a material using **`Hex/Lit`** or **`Sprites/Default`**. **`SpriteRenderer`** is fine for editor prototypes but often **does not render** in the game’s battle 3D pass; match the path used by stock mesh units. Details: [../../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md](../../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md).
