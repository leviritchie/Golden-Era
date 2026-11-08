# Custom HoMM3 VFX attachment investigation

Status: research record, 2026-10-04. No attachment fix is established or delivered.
The user reports that custom HoMM3 creature effects appear at the mesh/hip rather
than the intended body part, including Gog, Green Dragon breath, and Storm
Elemental lightning. Stock Olden Era creatures are not affected. The user supplied
Graverobber's hand and weapon effects as positive gameplay references.

Proof: source/static and read-only inspection of installed serialized assets.
Installed-asset inspection does not prove evaluated in-game transforms or effect
placement. The user requested continued static inspection with the live bridge
off. Both optional diagnostic enable flags remain disabled; the temporary empty
live-probe enable flag created during this investigation was removed. See the
checked performance entry in `docs/ingame_check_queue.md`.

## Native Graverobber Reference

The installed `Core.zip` view at
`DB/units/units_views/undead/graverobber_v.json` separates these routes:

| Action | View contract |
|---|---|
| Default attack | Animation index 0; `effects/projectiles/Graverobber_projectile` |
| Alternative/counter attack | Animation index 1 |
| Summon ability | Animation index 2 |

In the installed prefab `units/undead/1prefabs/graverobber`, the native unit-view
helper serializes a **direct Transform reference** for `projectileSpawnPoint`.
Its rig-relative path is
`Rig/Root/Torso/spine.001/spine.003/shoulder.L/upper_arm.L/forearm.L/hand.L`.
The end point references `neck`; the shield point references `FX_empty`.
This positively establishes a hand-origin contract, rather than a unit-root or
mesh-center origin.

The projectile prefab contains native projectile-controller/destroyer components
and the particle subtrees. It is not itself the unit's weapon skeleton. The unit
rig has a separate `Rig/shovel.root/DEF.shovel` branch, with no particle subtree
parented under that branch in the inspected prefab.

The visible model Animator uses `graverobber_ctrl`, an override of
`_Battle_Unit_Anim_ctrl_v2`. Its Attack_1 and Attack_2 clip events contain audio
calls, not VFX resource references. A separate
`magic/mesh_vfx/animation/graverobber_anim_vfx` controller and
`Graverobber_weapon_anim_vfx` clip exist, but their activation and binding to the
live shovel have **not been recovered**. Their names alone are not proof of that
connection. The separate `magic/mesh_vfx/skeleton_graverobber_vfx` asset has an
internally animated Head/Jaw mini-rig; it is not evidence of a shovel attachment.
This does not contradict the user's weapon-effect observation; the static
consumer route is still unresolved.

Reproduce the bounded prefab/resource inspection with the existing read-only
probe (do not use its `keys --catalog` mode for this investigation):

```powershell
python tools/homm3_vfx/vanilla_vfx_probe.py tree units/undead/1prefabs/graverobber magic/mesh_vfx/skeleton_graverobber_vfx magic/mesh_vfx/animation/graverobber_anim_vfx effects/projectiles/graverobber_projectile
```

## Custom Delivery Paths

| Example | Installed attachment contract |
|---|---|
| Gog | Cloned native particles on LeftHand/RightHand through `Homm3MeshFx` |
| Storm Elemental | Cloned native particles on hand/head/spine sockets through `Homm3MeshFx` |
| Green Dragon breath | Baked flipbook quad holder under Head; not a `Homm3MeshFx` particle row |

The installed Gog and Storm particle rows checked match their corresponding
source rows. The installed catalog is older overall (361 entries versus 369 in
source), but that difference does not explain those checked sockets. The installed
Green Dragon bundle has the breath quad holder as a zero-offset child of its
actual Head bone, with no ParticleSystem component. Thus a particle-only or
projectile-helper-only explanation cannot be assumed to cover all three examples.

`Homm3UnitViewHelperRuntime` creates native helper point transforms under the
chosen hand/chest bones. That is comparable to Graverobber's direct hand-point
reference, but does not control every custom effect. Its unset meshRenderer and
idleVFX fields are not a demonstrated cause of these placement reports.

## Findings And Limits

- `Homm3MeshFx.TryResolveSocket` finds an exact-name descendant for bone sockets;
  missing bones log and return false. It does not silently attach missing bone
  effects to the hip/root. The installed DLL's inspected attachment methods match
  the current source and existing Release binary.
- The resolver searches all descendants, not specifically the active renderer's
  bone array. Duplicate names remain a code risk, but the inspected installed rigs
  have unique, real hand/head bones with matching inverse-bind origins. That risk
  is not an established cause and does not explain Green's pre-parented quad alone.
- A CUDA skin-weighted region check of the three source GLBs found head/hand
  pivots inside the corresponding regions' bounds at weight >= 0.25. Pivot-to-
  weighted-centroid distances were 0.079-0.155 unit-space units. These named pivots
  are not located at Hips in the rest geometry. Measurements use source glTF
  coordinates, not evaluated Unity runtime transforms.
- A second CUDA check included animated morph targets and skinning at the first,
  middle, and last exact authored input times of each available Attack/Shoot clip.
  Head/hand pivot-to-weighted-surface-centroid distances stayed at 0.078-0.146 for
  Gog, 0.100-0.157 for Green Dragon, and 0.091-0.116 for Storm. The sampled pivots
  stayed distinct from Hips. Storm's left hand approaches Hips in one ShootFront
  sample, but its pivot and weighted surface do not collapse onto Hips. This
  excludes a gross source-pose collapse at those samples, not an error between
  samples or in Unity's imported/compressed playback. A weighted centroid is also
  not an exact surface contact or muzzle location.
- The DefRetarget builder prefixes bone animation bindings with `Orientation/`,
  requires every path to resolve, and copies the original curves unchanged.
  Generated attack clips retain separate hand/head local translations and their
  expected hierarchy; no remapping to Hips was found.
- The battle visual replacement and compatibility paths apply whole-root fit,
  facing, and foot alignment. No shared bone-array/root-bone/avatar/controller
  replacement or per-effect position sweep was found. The runtime billboard
  handler rotates/scales Green's breath holder but does not reposition it.
- The serialized particle field `moveWithTransform` is not a readback of the
  runtime local/world/custom simulation-space enum. The lab recipe's `simSpace`
  name cannot be used to claim that runtime setting has been verified.

The remaining distinction is between an intended socket, the evaluated socket
pose, and the visible effect's own emission/geometry origin. Static parenting,
inverse-bind agreement, and a socket-name log establish only parts of that chain.
The bounded source-pose check included body blendshape deformation; full evaluated
Unity clip playback and the effects' visible emission/geometry origins remain
unverified. There is currently no evidence-backed universal root-centering fix;
changing offsets, forcing particle simulation settings, or adding a root fallback
would be speculative.

## Validation And Cost

`python tools/validate_homm3_mesh_fx_catalog_contract.py` passed for 369 source
entries in approximately 0.27 seconds. It checks catalog configuration, not
in-game attachment tracking. GPU surface-region inspection used torch CUDA on the
RTX 5070 Ti for approximately 7.2k Gog, 14.3k Green Dragon, and 13.9k Storm
vertices; no CPU geometry fallback was used. The rest-region pass took 15.2 seconds
with 9.5 MiB peak CUDA allocation (22 MiB reserved) and approximately 1.06 GiB peak
process working set. The Storm sparse-morph sampling pass took 16.0 seconds with
41 MiB peak CUDA allocation (64 MiB reserved) and approximately 1.32 GiB process
working set. The completed Gog/Green morph sampling pass had no separate resource
footer, so its elapsed/peak measurements are not claimed.

Inputs were the three corresponding
`V:/homm3_unity_work/Assets/CustomUnits/homm3_lab/<unit>/OwnedSkinned/Source/def_retarget_master.glb`
files. These source measurements are not a substitute for installed-clip playback.
No new validator, pipeline stage, Unity job, production source change, bundle
build, or deployment was added. The existing documentation contract validator
passed in approximately 0.54 seconds; its process memory was not measured.

No installed effect change requires a new in-game queue row. No runtime or
user-visible fix is claimed. A future live comparison, only when authorized,
should capture the active clip and simultaneous world positions for the visual
root, target socket, actual particle emitter/quad holder, and native reference
attachment. It must not re-enable the optional diagnostic baseline silently.

## Addendum 2026-10-04 (Claude): lab renders reproduce the symptom

Proof: generated_artifact (existing lab renders) plus source/static. No runtime proof.

- `artifacts/vanilla_vfx_style/lab/<unit>/sheet_Unit_AttackFront.png` ("NEW" row) renders the same
  vanilla-style recipes the game uses. It shows the reported symptom offline: the Gog throw burst
  sits over the torso and hip at t=0.50-0.62 s, and the Storm Elemental bolt sparks bloom around
  the body. So a live session is not needed to reproduce it.
- Every kept emitter in the Gog, Storm and phoenix sources has `simulationSpace=Local`
  (`moveWithTransform=0`), with no mesh-shape references. Emitted particles therefore ride their
  bone. The throw/strike rows clone native *impact* bursts (phoenix hit fire, lightning-strike
  impact), and their windows run to normalized 1.0. The burst blooms at the hand at release, then
  follows the arm through the follow-through down beside the hip.
- Idle hand rows are on the correct bone, but the owned rigs' hands hang at hip height. Gog rest:
  Hips y=0.86, shoulder ~1.39, arm chain 0.785, so the hand sits at ~0.6. A hand flame at the hand
  therefore reads as "at the hip".
- `Homm3MeshFx.IsEffectHelper` uses `component.GetType()` on Il2Cpp proxies, which never matches
  `BhEffectHelper`, so `spawnAsChild`/`Init(socket)` are never applied. This only affects
  non-vanilla rows (one: `crusader_attack_sparks`). It does not explain the reported units.
- Native `BattleEffectSpawner.SpawnAttackEffect` places unit-view attack effects only at
  ProjectileEndPoint, ShieldPoint, Hex or Root (Mono demo decompile). Our helper puts EndPoint and
  Shield on Spine2.

Candidate fix, to prove first in the lab on Gog: set kept burst systems to World simulation space,
so particles stay where they were emitted. Trim throw/strike windows to the release beat. Add
`boneLocalPos` palm offsets for held flames. Not implemented or deployed.
