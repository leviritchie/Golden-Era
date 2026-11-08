# Current Mocap In-Game Test Delivery

## Authority And Scope

The end-to-end stage ownership and forbidden-lane rules are pinned in
[`docs/homm3_mocap_pipeline_contract.md`](homm3_mocap_pipeline_contract.md).
This delivery document records the accepted Stronghold shipment; it does not
promote the newer linked-master or silhouette experiments to animation
authority.

`experiments/homm3_mocap_v2/stronghold_ingame_test.json` selects saved candidates
for the user's in-game evaluation. It is not a production acceptance list.
Game SIDs, lab SIDs, and bundle names are different identities and must match
the current import table and units manifest. Boar Rider is excluded because its
available mesh is a Wolf Raider placeholder. The corrected Ogre Mage source is
retained with its appearance warning.

The animation authority is the saved current mocap fit or explicitly selected
saved skin refit. Old fused-push and continuous-tracker animation files are not
delivery inputs. No retargeting, smoothing, pose optimization, or new cycle keys
are introduced during delivery. The optional approved presentation profile below
is a separately pinned derivative, not a replacement for this raw authority.
Native lifecycle names select the engine-used
DEF groups; the full raw export retains the other groups as source evidence.
The current mocap adapter explicitly classifies groups 6, 7, 8, 9, 10, 11, 13,
14, 16, 17, 18, and 19 as source-only, recording their group IDs, reason, paths,
and hashes in `sourceOnlyGroups`. Unknown groups outside the declared native and
source-only sets fail. The delivery gate checks this partition against the
pinned raw manifest. This classification preserves the prior 186 native clips
for the current selection; it does not discard or repurpose the raw groups.

## Stages

The Python environment is `artifacts/homm3_mocap_v2/venv/Scripts/python.exe`.
The initial test output is `artifacts/homm3_mocap_v2/stronghold_ingame_test_v1`.

1. `export_ingame_candidates.py` copies recorded baseline exports and serializes
   saved refits with calibrated LBS readback. Its raw manifest records provenance.
2. `export_ingame_skin_sidecar.py` writes all eight source influence slots. The
   installed glTFast importer reads only the first four; the Unity lab restores
   the complete weights with `Mesh.SetBoneWeights` after checking vertex, UV,
   triangle, and joint identity, then verifies native weight readback.
   A fresh native mesh preserves the imported non-skin channels while avoiding
   glTFast's incompatible packed skin layout. Readback compares each vertex/joint
   against analytical bounds for quantization plus renormalization, reports
   zero-rounded influences, and rejects meaningful loss. With `q = 1/65535` and
   `delta = slotCount*q + abs(sourceMass-1)`, total per-vertex L1 error across
   corresponding joint weights must stay below `2*delta/(1-delta)`. This bounds
   deformation error without assuming how Unity redistributes rounding among
   individual slots. Maximum individual weight error is also reported.
   Unexpected joint IDs are rejected. Unity documents a minimum storage
   precision of [16-bit normalized weights](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Mesh.SetBoneWeights.html).
3. `prepare_ingame_lighting.py` uses the existing engine-material reduction,
   sprite-matched blackbody light solve, and Blender COMBINED texture bake. An old
   bake is reusable only for an identical engine-material GLB and a matching
   embedded baked texture. Mounted source identity follows the corrected asset
   profiles, not the historical filename meanings. `--reuse-prepared` explicitly
   verifies this rollout's existing textures without another solve.
   For new factions without a solved source, `--solve-only --style-profile baseline`
   with an explicit selection/output writes a pinned raw light solution but no
   texture (`rawSolutionOnly`). Then `--style-profile approved-oe-v1 --solution-root`
   pointing at that output performs the approved matte bake directly, avoiding
   an unused baseline bake. The approved profile applies key strength 0.60 and
   adds 0.25 of the removed key radiance to ambient fill.
4. `assemble_ingame_delivery.py` applies baked albedo and neutral PBR maps to the
   current clips, adds the full-scene orientation wrapper, emits a static master,
   and prepares native lifecycle metadata. Texture transfer requires source
   triangle-corner UV and albedo correspondence, not unchanged fitted positions.
5. `ship_ingame_candidates.py lab` validates delivery and prepares the complete
   selected Unity batch. `bundles` builds only that list, backs up prior source
   bundles, updates their payload contract rows, and runs payload/audio gates.
6. `ship_ingame_candidates.py probe` loads each built bundle in Unity, verifies
   its prefab, controller and high-influence skin, and samples all raw-source key
   times plus their midpoints. Source-varying transforms must produce mesh motion;
   genuinely static clips are classified explicitly. This is a finite-motion
   asset smoke test, not a rendered appearance or exact deformation-parity test.
   Motion expectation comes from raw GLB sampler rows, not editor curve queries
   against built clips, which return empty binding data in this Unity version.
7. `ship_ingame_candidates.py deploy` requires a successful current bundle probe
   and a verified runtime-capability DLL
   build record, backs up that installed DLL, the selected bundles, and the
   installed `homm3_import.json`, then copies the verified DLL, those bundles,
   and the current source import table (so measured walk-stride fields are
   live). It does not replace campaign content, faction definitions, or
   unrelated bundles. Deployment refuses to run while `HeroesOldenEra.exe`
   is running.

The shipping adapter forwards the exact selection to Unity preparation and uses
the existing `owned_prefab` naming helper for scope, loaded-bundle probing and
installed readback. This includes the established Crusader-specific prefab name;
it does not infer a game SID from a lab SID or silently migrate legacy battle/map
bindings. Those bindings must already match the explicit selected owned prefab.
Selection forwarding and naming/SID mismatch refusal are unit-test proven;
non-Stronghold bundle delivery remains separately unproven.

For a current profile with physical geometry ownership, the skin sidecar now
pins the exact current frozen preparation and source fit report. The shipping
validator reconstructs ownership from the original mesh and current profile,
requires that exact reference in the sidecar, and replays the final styled GLBs
using all serialized skin influences. It measures every source-defined split
pair at animation keys and quaternion-interpolated midpoint samples, refusing
gaps above the profile's explicitly pinned source-unit tolerance. Removing the
metadata cannot bypass this check. Scale, matrix transforms, and non-joint
transforms between joints are refused rather than silently omitted by replay.
Common outer rigid orientation wrappers preserve these distance measurements.
The prepared bind is checked by joint and parent identities, not donor array
order: the exporter canonicalizes joints before writing. Rest offsets retain
JSON double precision; inverse-bind and UV accessors use serialized float32.

This is finite sampled GLB boundary evidence, not continuous-time contact proof
or Unity/runtime appearance proof. Source-detached components have no split
boundary and do not gain a contact claim. Focused replay/ownership/export tests
pass, including second-set influences, animated ancestors, missing references,
and intervening-transform refusal. The existing Stronghold approved delivery
also passes the updated validator unchanged; a new masked-unit shipment remains
unproven until its actual final clips pass this gate and the native bundle probe.

## Physical Surface Authoring

Physical surface authoring must not select hidden body triangles through a
screen-space prop outline. `mesh_preview.raster_mesh(return_face_ids=True)` now
returns triangle IDs from the same opaque-surface z-buffer as its preview;
`visible_faces_in_polygon` selects only witnessed visible pixels. Record the
original source hash, exact camera, polygons and selected IDs with the authored
mask. Never-visible faces still require explicit physical review. Overlapping
front/back tests and matched Crusader source views validate visibility picking;
this utility does not establish semantic ownership or support transparency.
The raster retains backface culling by default. For a source material explicitly
declaring `doubleSided`, authoring may use `cull_backfaces=False`; record that
material authority and setting with the face buffers. This is not a recovery
mode for incomplete masks. Reversed-winding occlusion and ownership regression
tests pass; the option does not change the delivery ownership gate.

## Approved Presentation Profile

`assemble_ingame_delivery.py --style-profile approved-oe-v1` explicitly selects
the approved stronger articulation and matte lighting. `--artifact-root` names
the raw/skin-sidecar preparation root; `--lighting-root` independently names the
lighting preparation root without copying raw exports. Without that option,
lighting uses the artifact root. A selection may instead name exact per-unit
`lightingManifest` values, but combining both lighting selectors is refused.
Baseline remains an explicit separate lane.

`delivery_style.py` owns the complete native clip policy: Move uses the approved
world-space movement gain, AttackFront and ShootFront use the attack envelope,
all at gain 2.20 (+120). Root and leaf-local rotations, endpoint poses, translations,
and non-idle timing are preserved. Idle keeps every pose and stretches key times
by 2.5, giving 40% playback speed (measured against native Olden Era idles in
`homm3_idle_cadence.md`: native beats every 2.67 s median, so 2.5 x a 0.83 s DEF idle is
inside the native range but faster than its median). The same Idle asset serves native Idle and
Idle_Rare; Mouseover is a skill animation and is not retimed. Death, Hitted,
Defence, Mouseover, MoveStart, and MoveEnd otherwise remain byte-identical. Unknown
clip roles fail rather than inheriting attack behavior. No contact repair or
strain-based damping is implied by this profile.

Each clip retains `rawSourceGlb` and separately records `motionStyle` with the
derived GLB, its hash, gain, mode, and duration multiplier. Style timing is owned
only by that derived GLB. Battlefield Walk playback is a separate owner:
`measure_move_stride.py` records bind-space foot travel and cycle seconds on
the delivered Move GLB. (Retired 2026-09-28: ground units no longer write
native `UnitViewConfig.moveSpeed` from it; that lowered Stronghold speeds.
Speed is the normalized Core view row and the stride is matched to it, see
docs/homm3_stride_match.md.) Hex range is unchanged. Do not change Walk clip rate to hide a mismatched travel speed. The existing delivery gate replays the approved raw-to-derived
transform, proves derived-to-delivered animation parity, and remesures Move
stride against the manifest. It also validates the pinned approved lighting
manifest and requires its texture to match the delivery provenance.
The original raw parity gate remains mandatory for the baseline lane.

Motion profile and tamper rejection are unit-test proven; representative actual
raw Move, Idle, and AttackFront exports passed derivation/readback. This is
also installed-payload proven for the 20-unit Stronghold selection as recorded
below; other selections and actual styled runtime appearance remain unproven.

## Engine Compatibility

Current mocap clips preserve imported local translation, rotation, and scale
curves. The old rotation-only copy and tangent adjustment remain confined to the
legacy cascade lane. Every copied mocap curve must resolve to a child transform
in the delivered prefab.

Unity's global skin-weight limit also affects renderers whose mesh data contains
eight influences. The synthetic Unity 6000.0.66f2 probe confirmed that raising
only the renderer's numeric quality does not defeat a global four-weight cap.
The marked mocap prefab therefore declares `__homm3_skin_weights_unlimited__`.
The existing owned-skinned runtime initialization must enable the native global
unlimited cap for this capability and leave explicit fixed-quality renderers
unchanged. Other Auto renderers can observe the higher global limit.

The independent clip validator is
`tools/validate_homm3_mocap_delivery_contract.py`; it must not invent legacy
`physicsSmooth` metadata. Preparation and shipping call this gate before writes.

The existing stock controller maps normal attacks to `AttackFront` when both
`AttackFront` and `ShootFront` exist. The latter clips are addressable test assets,
but Orc/Cyclops ranged dispatch is not covered by the current controller mapping.
This delivery does not change that controller behavior or resolve candidate
appearance warnings recorded in the selection.

### Unit detail preview

Every unit detail window (battle, army/hero screen, town garrison, adventure-map
stack, hire-window info) opens `BhUnitWindow` -> `BhUnitWindowPreview.Show(UnitViewConfig)`,
which calls the native factory with `UnitViewConfig.id`. The native factory cannot
build a rig for an `h3_*` id, so `Homm3ImportUnitPreviewModelHook` aliases it to the
registry donor and then swaps the rig's `Model` for the owned skinned bundle prefab
(same prefab and Hex/Lit rebind as battle, native preview model as the Hex/Lit sheet
donor, Idle via the prefab's controller). The swap is keyed on the id the native
factory received, recorded on the Show frame: on live Golden Era the managed
`GetConfigElementId(UnitViewConfig)` read returns null, and keying on it made every
custom unit show its donor (LogOutput 2026-09-25). A refused swap logs
`owned skinned preview refused` as an error. Gate:
`tools/validate_homm3_owned_skinned_preview_contract.py` (build-wired; pins the five
owned skinned neutrals with no registry donor, whose preview has no native rig).
Proof: user-visible for the detail window (user confirmed 2026-09-26).
Preview size (2026-09-29) is the battle fit in every preview lane, not the donor's height or the
donor-copied view scale: `Homm3OwnedSkinnedPreviewFraming` (see `docs/surfaces/custom_unit_skinned_mesh.md`;
gate `tools/validate_homm3_owned_preview_framing_contract.py`). Generated artifact + build target; in-game look unproven.

The town hire screen (the large 3D recruit panel, `BhHireCityView` -> one
`BhHireUnitItemView` per tier) is a separate host: `BhHireUnitItemView.tvn(sids)`
returns its old wrappers to the `BhUnitPreviews` per-sid pool (`htw`) and refills its
own wrapper list (`bzii`) from `BhUnitPreviews.htv(sid)`; the per-item `tvp` is
inlined natively and never runs. For an `h3_*` sid the native view row carries the
donor mesh, so the pooled wrapper shows the donor. A postfix on `tvn` only (never
`htv` or the shared `prefab`) swaps each wrapper whose `Sid` is an owned skinned unit
synchronously, before the native `UpdateView` animates and camera-frames `Model`. The
pool is keyed by our own custom sid, so a swapped wrapper is only re-dequeued for
that sid and is re-layered, not rebuilt. A requested owned sid that no wrapper
carried logs `owned skinned preview refused ... BhHireUnitItemView.modelList` as an
error. Pinned by the same gate. The first build (a8e75f407e) read `BhUnitPreviews.me`
directly; that deobf accessor does not exist live (`field_Public_Static_BhUnitPreviews_0`),
so every swap threw MissingMethodException in game. The singleton is now read by
reflection through `GameSymbols.UnitPreview.SharedPreviewsInstanceMembers`, and the
build-wired `ValidatePluginLiveInteropRefs` gate catches this class of reference.
Proof: build only until the hire screen is checked in game.

## Proof Status

The initial test run generated all 20 selected units and 186 native contract
clips. The synthetic skin-quality diagnostic and full Unity lab import passed;
the latter completed in 133.7 seconds. The scoped bundle build completed in
120.2 seconds, with payload and audio gates passing. The runtime-capability DLL
compiled against Golden Era with 0 errors and 33 warnings. That compile used the
established Factory/Bulwark asset-validation skip for unrelated stale bundle
ownership rows; it is not proof of those factions' payload readiness.

The source-pinned built-bundle smoke test passed all 186 clips over 2,268 samples:
164 moving clips matched their motion expectation, and 22 single-frame movement
transitions remained static. All 20 installed bundles and the runtime DLL passed
hash readback and scoped payload/audio validation in Golden Era. The previous
installed files are retained under `installed_backup_20260907_162939` in the test
output. The focused source/unit-test suite passed 66 tests. This is an installed
test payload, not production quality acceptance; game startup, battle appearance,
and live performance were not established by those automated reports. The user
subsequently reported that the initial Stronghold in-game result was generally
good, while requesting stronger motion and softer lighting. The revised shared
visual profile was approved in offline comparisons. That feedback does not by
itself prove the later styled bundles or every unit's runtime behavior.

Use the rollout's `lab_build.json`, `bundle_build.json`, `bundle_probe.json`,
`runtime_capability_build.json`, and `installed_readback.json` as exact evidence.
The earlier `bundle_probe_report_finite_only_v1.json` is retained diagnostic
history, not the source-pinned motion gate. A sandbox-only Unity licensing failure is not
evidence of an expired license: the successful probe required normal licensing
IPC outside the sandbox and the direct `V:/homm3_unity_work` project path.

### Approved-Style Stronghold Shipment

`artifacts/homm3_mocap_v2/stronghold_oe_approved_v1` contains the subsequently
installed approved-profile shipment: 20 fresh softer matte lighting bakes and
186 native clips, derived from the previous pinned raw captures and fitted skins.
Unity lab import and the scoped bundle build passed. The loaded-bundle probe
passed all 20 units and 186 clips over 2,268 samples. Comparing loaded clip
durations with the initial shipment confirmed all 20 idles are 2.5 times longer
and all 166 other clips retain their duration. Native Idle and Idle_Rare share
the same retimed Idle asset; no second playback-speed adjustment was added.

All 20 bundles were installed into Golden Era and passed hash readback and
scoped payload/audio gates. The prior installed files are retained in
`installed_backup_20260907_234625` under that rollout. The existing pinned
runtime-capability DLL was reused; no new plugin compilation was necessary.
This proves installed payload and offline loaded-bundle behavior, not a new
game startup, live battle appearance, or completion of the full 252-slot faction
rollout. Boar Rider and other missing, placeholder, or unprepared units remain
unfinished scope. Exact source pins and checks are in the rollout stage reports.

### Stronghold +120 stride / preview test

`artifacts/homm3_mocap_v2/stronghold_ingame_test_gain220_v1` is the user-requested
Stronghold in-game test of gain 2.20 (+120), measured Move-clip walk stride,
preview-slot centering, and town recruitment Idle meshes. Raw/skin still come
from `stronghold_ingame_test_v1`; lighting is the existing approved-oe-v1 bakes.
Unity lab import, scoped bundle build, and loaded-bundle probe passed all 20
units and 186 clips over 2,268 samples. The plugin compiled against Golden Era
with 0 errors. Deploy copied those 20 bundles, the compile-pinned DLL, and
the source `homm3_import.json` (stride fields included). Installed hashes match.
The previous Golden Era files are in `installed_backup_20260908_161447`.

The first installed stride pass retimed Walk clip rate to the native hex tween
(`Animator.speed`). That was inverted: ground units now keep authored Walk timing
and write `UnitViewConfig.moveSpeed` (that write is retired, 2026-09-28: see
docs/homm3_stride_match.md); Roc / Thunderbird / Shahrokh are flyers and
are not matched. Hex Speed (range) is unchanged.

This is installed-payload proof. Live battle walk matching, preview centering,
and recruitment mesh appearance remain **runtime / user-visible unproven** until
the player starts the game and looks. Boar Rider stays excluded.
