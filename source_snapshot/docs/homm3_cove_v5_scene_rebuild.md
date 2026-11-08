# Cove town scene v5: rebuild from a 3D scene model (2026-10-16)

Status: **baked as candidate `cv5_a` (bundle built, not installed).** kk_v4 rebuild 2 stays installed until the user
approves.

## Build (2026-10-16)

The scripts are in `V:/olden_port_work/kokon/cove_trial/v5/`:

| Script | What it does |
|---|---|
| `scene_v5.py` | Rigid building placement: floor, cliff or object support, and `on:` decks for the castle on the dock and the statue on the nix. |
| `env_v5.py` | Water plane, massif (face, terrace, plateau, caps), object and near cards, and the far band. |
| `review_v5.py` | Paint-order solve, clearance checks and the review cameras. |
| `stage_v5.py` | Bakes the model into a candidate. |
| `render_staged.py` | Relit offline render of the staged bins. |

Steps:
1. `candidate-init --seed-from kk_v4` (`TOWN_FULL3D_CANDIDATE=cv5_a`).
2. `python stage_v5.py`.
3. `stronghold_full3d_scene.py catalog --carry previous`.
4. `town_full3d_ssr_water.py stage`.
5. `bundle`, `render` and `validate`.

What the bake writes:
- **Buildings.** The Meshy layers are baked at their v5 placement through `cove_t2_stage.stage_layer`: painted front
  plus hull, no seed residual, and no paint-order face cut, because paint order is solved by placement.
  - A rock `_skirt` plinth goes under a base that floats on the water: nix2 and the sorceress tiers.
  - Fx bins and particles are scaled about the rest camera with their layer. Whirlpool Fx are re-laid on the water.
- **Cards.** The stilt rows, waterfall, whirlpools and smugglers' rock are rigid sprite cards.
- **Environment.**
  - Mesh_Terrain / Mesh_TerrainNear_0/1 form the level water plane. Its rows are spaced by depth, and it ends inside
    the 415 m Sky_Dome.
  - Mesh_Back_Layer_* holds the massif face (cliff plate), the grazing, top and cap rock tile, the object cards, the
    near band and the far band at 400 m.
  - The old Mesh_Backstop, Mesh_Near_* and kk_v4 layers are dropped.
  - Mesh_Outer* (pan periphery) and Sky_Dome are kept from kk_v4.
- **Lighting.** Env normals are leaned toward up and the viewer, and textures are de-lit through them.

Known open items:
- **Massif terrace wall.** The terrace behind the hall and thgd reads as one flat rock wall from the side poses.
- **Mesh_Outer\* periphery.** These pieces are old ray geometry and show at ±35° and beyond.
- **Near band.** The near-band cards smear at grazing orbits.
- **hal3.** Its base sits about 5 m below the water at its rest-silhouette scale.

## Why the earlier candidates went wrong

The overhead views are top (x, depth) and side (depth, height) splats of every staged piece. They are in
`V:/olden_port_work/kokon/cove_trial/v5/`, made by `topdown.py <candidate>`.

They show that kk_v3 and kk_v4 are not 3D scenes. Each one is a per-pixel depth map seen from one camera:
- **Terrain.** The terrain is a fan of sheets streaked along camera rays.
- **Buildings.** Most buildings are smeared 10–30 m along their rays: say1/say2, nmp1/nmp2, thgd, nix2, the dock and the
  pirate tiers. This came from the footing/contact re-ray edits (kk_v2 onwards, and contact_v1 before them). The Meshy
  meshes themselves are compact.
- **Why my checks missed it.** Every check I ran looked through or near the rest camera: crops at reachable poses,
  rest diffs, streak gates. In that view a ray-stretched object looks correct. It fails exactly where the user looks:
  3D, from far off the rest axis.
- **kk_v4 made it worse.** It moved the env layers forward per pixel and per column, which put the cliff and object
  layers in front of buildings that were behind them in the painting (say1/say2 at 91k/110k px, thgd at all px, pir1 at
  102k px).
  - Each column was solved on its own, which produces the zigzag.

## Rule for v5

Every element is a rigid 3D object with one pose in one world. Nothing is placed by a per-pixel depth map, and nothing
is stretched along camera rays.

- **One world.** The world is the rest camera's frame, in metres.
  - The water is a level plane in world space. The painting's sea horizon gives the pitch, and the camera height sets
    the water height. The old fitted plane rose 0.146 per metre of depth, because it was fitted to painted depth.
  - Depth comes from ground contact: where an element's base row meets the water or the terrain, the camera ray hits the
    ground there.
- **Buildings.** The original Meshy GLBs (`artifacts/meshy_town_scene_meshes/homm3_cove/<layer>/model.glb`) are placed
  rigidly: yaw, uniform scale and translation.
  - Depth comes from the base contact. Scale comes from the sprite width at that depth. Yaw is fit to the sprite
    silhouette.
  - Elements with no mesh are rigid cards: the waterfall nmp1/nmp2, the whirlpools whr1/whr2, the grail sky and the
    chests.
- **Terrain and cliff.** One smooth heightfield h(x, z) over the water plane, with no per-pixel depth.
  - It is constrained by:
    - the shoreline contacts, where the cliff or ground meets the water;
    - the feet of the buildings that stand on it (the mage guild, castle and grail sit on the massif, so their
      footprints set the cliff top);
    - "behind every building it is painted behind".
  - The painting's silhouette rows give the cliff profile.
- **Objects.** The wreck, rocks, statue, reeds and near foliage are one rigid card per object (or a props mesh where one
  exists). Each stands on its foot at the contact point, as one plane per object, never per column.
- **Far background.** The far sea, far mountains and sky are far planes plus the existing dome.
- **Textures** (unchanged rule):
  - Each element is textured from the plate in which it is frontmost: terrain from the emptiest plate, objects from the
    painting.
  - The Kokon plates, the layer segmentation (`layers_lab.npy`) and the extension canvas are reused as art.
- **Rest view.** The rest view will not be pixel-identical to the painting. Geometry beats rest dE.

## Review (gates every install)

1. Overhead and side views of the whole scene: nothing streaked along rays, buildings compact, terrain smooth.
2. Built state (all buildings) and empty state, in game framing, from extreme poses: orbit ±35° and high/low, beyond
   the bench's reachable set.
3. Automatic checks:
   - building clearance: no env element in front of a building where the painting shows the building;
   - the depth span of every element relative to its width;
   - every building and object touches the ground.
4. ContourLines emulation in the preview (the pass is now off in game for town pieces) and the SSR water noted as a
   preview gap.

## Reused vs dropped

- **Reused:**
  - the painting, the Kokon extension canvas and peel plates, and the layer labels;
  - the Meshy GLBs and props;
  - the sky dome, SSR water staging, bundle, install and plugin.
- **Dropped:**
  - the kk_v1..v4 env geometry (LDI back layers, Mesh_Outer re-ray, footing/relief/twoside edits, build_v4 depth
    model);
  - the staged building bodies, contact_v1 and the footing re-ray;
  - water plane fitting to painted depth.

## cv5_a review (2026-10-16)

Bundle rebuilt with the vanilla Mesh_Near_* rock dressing restored. Validate passes (streakMax 1.161, panVoid 0,
bldDepth contact_v1:60, ssr 3). Review sheets: `artifacts/homm3_cove_full3d/candidates/v5_review/`.
In the Unity renders, the MassifGraze terrace step shows as a black vertical slab left of the waterfall even at the
rest pose. At the sweeps, the floor reads as a streaky brown plane. Near/boat cards smear, and orbit y+18 shows an
old Mesh_Outer sky panel. Verdict: not install-ready; kk_v4 rebuild 2 stays installed.

Installed 2026-10-16 20:15 UTC at the user's request, for an in-game check, because offline renders have not matched the game: bundle `21f46216`, catalog `8dca8405`, both validators OK, sha256 readback OK.
Rollback `artifacts/town_scene_rollback/cove_20261016T201533Z` restores kk_v4 rebuild 2. The in-game check row is in `docs/ingame_check_queue.md`.
