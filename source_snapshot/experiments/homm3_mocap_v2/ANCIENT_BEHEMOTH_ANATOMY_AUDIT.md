# Ancient Behemoth Anatomy Audit

Status: rebuilt and registered for generated-candidate preparation on 2026-09-06.
The inherited sibling draft was rejected; the current profile was independently
rebuilt from named mesh hierarchy and weighted ownership. CPU consumers and
original-rest preservation pass. This does not establish animation acceptance.

## Verified Identity

- Mesh: `artifacts/meshy_downloads/h3_ancient_behemoth_smartrigged.glb`
- SHA-256: `c05435546d5b0841ef42eb327fc774f1599dd65f1520b0add03f96e6390dba76`
- GLB topology: 59 joints, 12,978 vertices, 9,994 triangles
- Active native source: Golden Era `h3_ancient_behemoth/extracted_battle_source_12fps/CABEHE.dir`
- Idle group: 2, 8 frames

## Measured Hierarchy

The root/pelvis is `Bone_000 -> Bone_001`. The central chain is `Bone_014 -> Bone_013 -> Bone_012 -> Bone_011 -> Bone_010`, with positions `(-.011,.858,-.572)`, `(-.011,1.054,-.410)`, `(-.011,1.181,-.228)`, `(-.011,1.300,-.032)`, and `(.025,1.335,.025)`.

This contradicts the inherited standard-Behemoth profile, which assigned `Bone_014` and `Bone_013` to a leg and used a different spine chain.

Root readback of `load_bind_skeleton` confirms the grounded side chains are
`Bone_005 -> Bone_004 -> Bone_003 -> Bone_002` and
`Bone_009 -> Bone_008 -> Bone_007 -> Bone_006`. Bone_017 and Bone_020 are
children of Bone_002; Bone_023 and Bone_026 are children of Bone_006.
They are distal foot branches, NOT upper-spine branches. The first authoring
audit misread these relationships; independent review and root readback agree.
The head path is Bone_010 -> Bone_028 -> Bone_027, with details through
Bone_038/037 and Bone_040/039. Arms begin at Bone_032 and Bone_036, both
children of Bone_010. Their terminal hand branches are owned by Bone_029
(043/042/041, 046/045/044, 049/048/047) and Bone_033
(052/051/050, 055/054/053, 058/057/056), respectively.

## Rebuilt Preparation

Actual source and prepared bind sheets were inspected. Named weighted-joint
evidence is in skin_mesh_pilot/ancient_behemoth/target_skin_audit_v1.json under
artifacts/homm3_mocap_v2. All 59 source joints have explicit ownership.
Positive-X shoulder/elbow/wrist sites are Bone_036/035/034; negative-X sites
are Bone_032/031/030. Palm and claw descendants follow the corresponding hand,
not the forearm. Upper-chest Bone_010 owns Spine2; neck/head are Bone_028/027.
Both complete foot subtrees are assigned to their actual side.

The real test exercises donor loading, source-weight initialization, bind
fitting, rig validation and CPU WeightField, plus anatomical regressions.
Independent review caught stale headBone/neckBone metadata, corrected before
preparation and pinned by tests. mapped_skin_v1 passed original mesh, topology,
UV, texture and own-bind export preservation. Frozen research-skin SHA:
18b3fd46d119a61d9f724e5d5bbbbd97b99daad4ab9638456463ebc3409d872f.

Current fit outcomes are recorded separately in ANCIENT_RAIDER_EXPANSION.md.
No independent claw or toe motion is asserted by the 25-joint donor.
