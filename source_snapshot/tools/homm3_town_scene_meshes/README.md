# Interior town-scene Meshy meshes (cityFactory)

## Locked Meshy policy

1. **Building mesh:** `meshy-t2` + `smart-topology`, `should_texture=false` (face cap **100..15000**)
2. **Backdrop mesh (full town plate):** `meshy-6` + `model_type=standard` + `should_remesh=true`,
   `should_texture=false`, generous `target_polycount` (**100..300000**; default **150000**).
   Do **not** use t2 for the backdrop — 15k faces is too low for a whole scene.
3. **Materials (both):** `meshy-6` retexture, `remove_lighting=false`, `enable_pbr=true`, style = same source PNG

```bash
# Backdrop first (needs MESHY_API_KEY)
python tools/homm3_town_scene_meshes/generate_factory_backdrop_pilot.py --polycount 150000

# Building pilot
python tools/homm3_town_scene_meshes/generate_factory_townhall_pilot.py

# Unity AssetBundle + stage into OfflineUnlockMod/homm3_town_scene_meshes/
python tools/homm3_import/build_homm3_town_scene_meshes_bundle.py

# Contract
python tools/validate_town_scene_mesh_contract.py --require-catalog
```

Enable at runtime with `homm3TownSceneMeshes: true` in plugin `config.json`.

Proof: Meshy + bundle = generated artifact validated; in-town look/clicks = runtime until exercised.
