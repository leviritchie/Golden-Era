# Adventure-map artifact Meshy meshes

All `homm3_artifact_*` AVA map frames under `homm3_runtime_assets/artifacts/map/`.
Same Meshy policy as buildings: t2 topology (untextured) + meshy-6 retexture @ 4k
(keep baked lighting). Default `--polycount 500`. AVA frames are ~22–38px; the generator nearest-upscales
uploads to min side 256 so Meshy accepts them (pixel look preserved).

```bash
# Inventory
python tools/homm3_artifact_meshes/inventory_artifact_map_billboards.py

# Meshy
python tools/homm3_artifact_meshes/generate_meshy_t2_artifacts.py \
  --missing-only --parallel 3 --texture-resolution 4k --polycount 500

# Resume
python tools/homm3_artifact_meshes/generate_meshy_t2_artifacts.py \
  --skip-existing --parallel 3 --texture-resolution 4k --polycount 500

# Unity AssetBundle + stage into OfflineUnlockMod/homm3_artifact_meshes/
python tools/homm3_import/build_homm3_artifact_meshes_bundle.py

# Contract
python tools/validate_artifact_mesh_contract.py --require-catalog
```

Enable at runtime with `homm3ArtifactMeshes: true` in plugin `config.json`.
Uncatalogued / incomplete rows keep the PNG billboard until Meshy + bundle catch up.
Catalog hits are fail-closed (no silent PNG fallback).

Proof: Meshy + bundles = generated artifact validated; in-map look = runtime until exercised.
