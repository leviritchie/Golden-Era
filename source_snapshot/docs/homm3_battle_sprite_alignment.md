# HoMM3 Battle Sprite Alignment

Lane-B HoMM3 unit bundles render DEF frame PNGs on `battle.prefab -> billboard/quad`. Current extracted battle frames use a 450x400 canvas, so custom-faction battle quads should use:

- `battleQuadLocalScaleX=13.5`
- `battleQuadLocalScaleY=12.0`
- `battleQuadLocalPositionX=0.75`
- `battleQuadLocalPositionY=2.01`
- `battleQuadLocalPositionExtraY=0.0`

This preserves the 450:400 source aspect while keeping the existing vertical size and anchoring the shared HoMM3 foot line near source y=267 at the prefab root. The older square `12x12` quad squeezes sprites horizontally and can make Tower, Stronghold, and later custom-faction units look misaligned even when the DEF frame margins are correct.

Run `python tools/homm3_import/normalize_battle_quad_authoring.py --apply` after adding or regenerating HoMM3 import presets, then rebuild the affected Unity bundles before deployment. Do not compensate for this by changing donor battle-template mappings or runtime fallbacks; the fix belongs in authoring data and the generated bundles.

## Unit Source Accuracy

Visual accuracy also depends on each `unitSid` pointing at the right extracted DEF folder. Use `tools/homm3_import/units_inventory.json` as the source of truth, then run:

```bat
python tools/homm3_import/audit_unit_sprite_sources.py
```

This checks both `tools/homm3_import/presets/<unitSid>/authoring.json` and the Unity lab copy under `oldenera_factions/Assets/CustomUnits/homm3_lab/<unitSid>/authoring.json`.

Known Stronghold trap: `h3_wolf_rider` must use `CBWLFR`, and `h3_wolf_raider` must use `CUWLFR`. `CBWLFR` is the base Wolf Rider even though the shorter-looking naming can make it tempting to assign it to the upgrade. If the audit reports a Unity-lab mismatch, rebuild that unit's extracted frames/prefabs before producing bundles; otherwise the bundle can keep shipping the wrong creature even when the preset lane is correct.

## Animation Frame Accuracy

Run the animation audit on any unit line that looks like it is playing the wrong action:

```bat
python tools/homm3_import/audit_unit_animation_frames.py --unit hota_cove_nymph --unit h3_orc --unit h3_wood_elf
```

The May 17 audit found two source-level traps. First, stock `15.Skill_1` through `19.Skill_5` are attack variants in the reference controller, not death clips; matching death by the raw substring `kill` misreads `Skill_*` and makes melee/attack variants play falling frames. Second, shooter DEF groups are `14/15/16`; if those exist, the generated attack clip and runtime disk remapper should prefer them over melee groups `11/12/13`.

Some HotA/ToA JSON-frame sources, including the Cove nymph/oceanid/nereid line, have no movement group `0`. That is not a reason to drop back to flat-folder slices. The importer should build `01.Walk` from group `1`, then idle if needed, while keeping the real idle/hit/death/attack groups intact.
