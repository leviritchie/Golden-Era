# Haiku anim bench (side experiment)

A fast loop in which Claude Haiku 5.5 makes one small animation edit per step on a working copy of a unit GLB, looks
at a multi-angle contact sheet rendered by the GPU, and then keeps, reverts or moves on. You can watch it live at
http://127.0.0.1:8771/. Per-step latency is the main metric. This is NOT part of the shipping pipeline:
- export is not install;
- nothing here writes to `artifacts/`, `tools/homm3_glb_patch/key_rotations/`, the authenticity ledger or
  `V:/olden_port_work/authenticity`.

## Run

The bench serves one unit at a time on one GL context. Any def_retarget unit works with no per-unit code: the GLB,
DEF frames, cameras and bone names all come from the unit. The viewer's unit picker, or the driver's `--unit`, switches
the bench in about 3 s (`POST /api/switch`).

```
python tools/haiku_anim_bench/bench_server.py --unit h3_troll --clip Unit_Move     # GL + stack + viewer, :8771
python tools/haiku_anim_bench/haiku_driver.py --unit h3_troll --clip Unit_Move --steps 300 --run free_move
python tools/haiku_anim_bench/export.py --unit h3_troll --name free_move [--draft] # bake (experiment folder only)
python tools/haiku_anim_bench/test_bench.py                                       # skin/gate parity, edit math, rig ops
```

**The prompt is generic (2026-10-07).** It covers the art standard, the sheet layout and the op palette, and nothing
else:
- no unit or clip hints;
- no agenda, no minimum-attempt rule, no idle budget, no mandatory fields;
- no per-op caps worth the name (120 degrees per part, 40 parts per pose, `"hw":"all"` for whole-clip changes,
  translation on any joint that has a position track; stride length and move speed may stay as they are).

Haiku decides what is wrong and what to do; revert and `undo` by id make mistakes cheap. The mesh report is
information only. Edits that pass the glbPatch lane's per-key table limits are exported by a direct bake of the bench's
own channels, and the report records why the lane refused them (`laneRefused`).

**Round 2 aids (2026-10-08): perception and ergonomics, not rules.**
- `try` (same fields as `edit`/`pose`) renders the change both ways in one small sheet, DEF | NOW | A (as written) |
  B (every angle flipped), from the DEF camera, the side and the top, with words for what each does and whether it
  tears. `pick` A, B or none turns the choice into the pending change. The driver counts a try and its pick as one step.
- Net stack: a kept pose change merges into ONE net offset per joint (exact on every key, `anim_core.net_collapse`,
  checked by `test_bench.py`), limited to 120 degrees and 0.6 H per key. Each turn's text lists the net pose per joint
  (`#id`, body-axis degrees per DEF frame, or one value for the whole clip); `undo` takes out a joint's whole net change.
- `OURS NOW`: our own pose at the focus frame in plain words from the geometry (trunk direction, where the head looks,
  legs and arms or wings, and whether they move through the loop). It never names DEF numbers or targets.
- `{"op":"repair","fix":"robust"}`: a mesh pre-pass Haiku may call. It test-bends every joint (35 degrees, whole clip),
  and at each torn spot tries a weight handover (when two non-neighbouring joints share the skin) or a local weight
  blend, keeping a fix only when it tears less and no clip gets worse.
- `look` with `"view"` (sprite, side, top, front, battle, head, film): a zoomed DEF | ours pair, or just the film rows,
  instead of the full sheet.
- `POST /api/reset` (driver `--fresh`) returns the unit to its original animation and mesh.

**Pause, resume or stop the driver.** Either use the viewer's buttons, or write the control file
`V:/olden_port_work/haiku_anim/<unit>/control.json`, for example `{"state":"pause"}` (or `"run"`, or `"stop"`). The
driver reads it once per step.

**Stop the server.** Stop its python process. The edit stack in `stack.json` is rewritten on every change, so a
restart resumes. Delete `stack.json` to start again from the original GLB.

## Pieces

- **`anim_core.py`** holds the unit and the edit math.
  - An edit is a raised-cosine rotation bump on one bone, centred on a DEF frame, with a half width in frames
    (cyclic on loop clips).
  - Its axis is given in body terms (pitch+ is nose down, yaw+ turns toward the unit's left, roll+ tilts toward
    the unit's right). The axis is frozen to bone-local when the edit is created.
  - Root (Hips) translation bumps are also supported. Forward root motion on Move clips is zeroed, because stride is
    exempt.
  - Edits are baked as per-key offsets on the clip grid, which is exactly patch_glb `keyRotations` /
    `keyTranslations`, including `regrid` for 2-key STEP holds.
- **`anim_gl.py`** does the moderngl work on one context:
  - compute-shader skinning (morph + LBS);
  - the edge-stretch gate, using patch_glb's `STRETCH_RATIO` 2.0 and `WORST_STRETCH_SLACK` 1.05 on the clip's key
    grid, never relaxed;
  - the 768x672 contact sheet:
    - row 1: DEF, ours from the sprite camera, the battle camera and the preview camera;
    - row 2: front, side, top and rear 3/4;
    - then filmstrips: DEF, sprite and battle;
    - an orange gaze ray (the head joint to the beak-tip direction) in every 3D view.
- **`bench_server.py`** is one persistent process on 127.0.0.1 only.
  - It holds the work copy (`work.glb`, sha-checked), `stack.json`, the GL worker thread and the HTTP API that the
    driver and viewer use.
  - Run1/2 auto-reverted failing edits. From run4 the mesh check only reports (see below).
  - The state line includes our own gaze angle at the focus frame. That is a readout of our pose only, not a DEF
    metric.
- **`haiku_driver.py`** runs the persistent `claude -p --model claude-haiku-5-5 --input-format stream-json
  --output-format stream-json --verbose --tools ""` CLI process. No API key is needed.
  - Each turn sends the sheet as a base64 image block, plus the last op, the gate result and the state line.
  - The reply is one JSON op: `edit` / `keep` / `revert` / `move`, with `why`.
  - Sessions rotate every 12 steps. A spare process is spawned and warmed in the background, so its cold first turn
    is off the clock. The new session gets the kept edits and recent ops.
  - Log: `V:/olden_port_work/haiku_anim/<unit>/runs/<run>/steps.jsonl` (latency split, op, gate, fate, token usage)
    and `system_prompt.txt`.
- **`viewer.html`** is three.js 0.160.0: the core from cdnjs, GLTFLoader and OrbitControls from jsdelivr.
  - It loads `work.glb` and rebuilds the clip with the same edit math in the browser. Parity with the bench was
    checked on world bone rotations to 1e-4.
  - Orbit and zoom, clip pick, play and scrub.
  - "edited" toggles before/after; "follow Haiku" jumps to the clip and frame Haiku is looking at.
  - Panels: the DEF sprite synced to the clip time, the latest sheet, Haiku's op and why, latency, the tally, and
    pause/stop.
- **`export.py`** writes into `V:/olden_port_work/haiku_anim/<unit>/export/`:
  - `<unit>_<name>.glb`, baked by patch_glb's own `op_key_rotations` / `op_key_translations`, with the lane's table
    validation;
  - the tables, under `lane_root/tools/homm3_glb_patch/key_rotations/`;
  - `glbpatch_ops_<name>.json` (`keyRotations` with `regrid: true`, sha-pinned);
  - `export_report_<name>.json`, which records parity of the baked GLB against the bench pose and the gate per clip.

  To adopt the edits later:
  1. Copy the tables into the repo `key_rotations/` directory.
  2. Add the ops to the unit's glbPatch spec.
  3. Run the lane, which does the CS re-bake and the DEF_Master sync that this export skips.

## Mesh report, repair ops and rig ops (run4+)

- **The mesh check reports; it never vetoes.**
  - Every step skins the clip's key grid on the GPU. The rule: an edge is a new defect if its stretch passes
    max(2x, 1.05 x that edge's own original maximum). The thresholds come from the pristine rig, primed for every
    clip at start-up.
  - New defects are tinted red in every 3D view.
  - The battle tile becomes a "worst new stretch" close-up.
  - The state line names the spot in words: extent, torn or stretched, the body parts, the side, the worst frame.
- **The other clips are checked too.** Weight and rig changes touch every clip, so after any repair or rig op (or
  revert), the other clips get the same check. Any that went red are listed by name.
- **Haiku may keep while red.** It is counted (`keptWhileFlagged`) and the defect stays open.
- **The final export must be clean on every clip.** Otherwise only `--draft` writes, and it writes a `*_DRAFT.glb`.
- **`pose`** is a compound op: up to 6 parts, with optional `mirror`, applied as one change.
- **Pose caps.** Parts are scaled to 50% or 25% (or refused) so that the cumulative per-key offsets stay inside the
  lane table limits. The bench caps are 100 degrees and 0.2 H; the lane's are 120 degrees and 0.25 H.
- **`repair`** (`rig.py`, 20–60 ms):
  - `smooth`: local diffusion of the bones' weight shares around the spot;
  - `blend`: move weight from bone A to bone B in a box, which is exactly glbPatch `moveWeights`;
  - `relax`: Taubin relax of the rest shape around the spot, over weld groups keyed by position and weights;
  - `nocs`: drop the corrective-shape morphs on the given bones.
- **`rig`** (80–100 ms):
  - `split`: cut a bone at a fraction. A new joint takes the child, and the weights are re-split smoothly.
  - `add`: a new child joint grown from nearby vertices, toward back/front/up/down/left/right.
  - `pivot`: move a joint and re-bind it consistently.
  - `reparent`: hand a bone to a new parent, with its locals re-baked on the clip grid so the pose is unchanged.
  - New joints get descriptive names. They are keyed through every clip as identity, so the pose is unchanged and
    they are poseable at once.
- **Every kept change is a frozen record.** Repair and rig records go in `stack.json` `mops`; pose edits go in
  `kept`. The rig is a deterministic replay from the pristine copy.
- **The viewer reloads `/work.glb?rig=<key>`** whenever the rig changes. That URL serves the work GLB plus the rig
  state, built by `rig_glb.py` in about 80 ms. The "joints" checkbox shows the skeleton.
- **`export.py`:**
  1. replays the rig;
  2. writes it with `rig_glb.build_rig_glb`: new nodes, joints and IBMs, JOINTS_0/WEIGHTS_0, the rest shape and
     morphs if they changed, and the new joints' channels;
  3. bakes the pose edits with the lane's `op_key_rotations` / `op_key_translations`;
  4. checks parity against the bench and runs the gate on all clips.

  `laneExpressibility` in the report records, for each kept op, what glbPatch can do today:
  - **Expressible now:** `blend` = `moveWeights`; a whole-bone `smooth` = `diffuseWeights`.
  - **Needs a region parameter:** a local `smooth` needs one on `diffuseWeights`.
  - **Needs a new op:** `relax` needs a rest-shape op.
  - **Build-time only:** `nocs` maps to `correctiveSmooth.excludeBones` at build time.
  - **Not expressible:** `split` / `add` / `pivot` / `reparent` need new lane ops (addBones / rebind / reparent), or
    the def_retarget `ext/wing_chain.py` after_skin path in build_unit.
  - **Not done here:** the export does not re-bake the CS morphs for the new weights.

## Measured (h3_roc, RTX 5070 Ti, 2026-10-07)

| Item | Time |
|---|---|
| Server load | ~1.0–1.4 s |
| GL init | ~0.5 s |
| Sheet + gate per edit (pose 3–4 ms, GPU skin + gate, draw 8–9 ms, compose 5–6 ms) | 15–35 ms |
| JPEG | ~125 KB |
| Same work seen by the driver over HTTP | median ~30–40 ms |

**Model turn through the CLI, with one ~850-token image per turn:**
- About 0.6–0.9 s with a short context. It grows roughly linearly with session context, to about 1.9 s at 30k tokens,
  hence the 12-step rotation.
- The first turn of a fresh process is about 2–3 s: boot, cache write and one-off thinking. The warm spare absorbs
  this.
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` removes the CLI's post-turn summary request, which was about 1 s of
  every turn.
- Haiku 5.5 thinks adaptively on harder turns (50–300 tokens), which adds about 1 s. `MAX_THINKING_TOKENS=0` does not
  stop it. A small `--max-out` (160) does suppress it, but a fresh session's first turn can then overflow the cap.

## Rules carried into Haiku's system prompt

- Gaze and motion intent come first, then natural articulation, then mesh integrity (reported, repaired with
  repair/rig ops; the export must be clean).
- No silhouette matching. The motion must read from every angle.
- Stride length and move speed may stay as they are; how the legs swing, bend and land is Haiku's to change (round 2
  wording; the old "never change stride" clause froze the legs).

## Round 3: survey, free camera, mesh tools (2026-10-08)

A run now has two phases (driver `--survey N`):
1. **Survey.** Haiku looks at the mesh in any clip and pose from any angle and writes its own defect checklist. Only
   view, look and note work in this phase. Haiku ends it with `{"op":"phase","to":"fix"}`; if it doesn't, the driver
   ends it when the N steps are used.
2. **Fix.** All ops work on any clip (`"clip"` on edit/pose/try/repair/rig/look). Haiku ticks checklist items as
   fixed or dropped.

Survey steps don't count toward `--steps`.

**Free camera.** `{"op":"view","clip","frame"|"frames":[a,b],"yaw","pitch","dist","at":joint|"body","mode"}`
- Implemented in `AnimGL.view`. It renders one 384 px image, or a strip of up to 8 frames. There is no DEF and no red
  tint, and the pending change and focus are left alone.
- `yaw`: 0 = the unit's front, 90 = its left side. `dist` is the box size in body heights.
- Modes: `shaded`; `wire` (a z-biased wireframe pass over the shaded mesh); `normals` (view-space normals, darkened
  where the dFdx/dFdy face normal leaves the smooth normal, i.e. creases); `heat`; `skeleton`.
- `heat` shows the signed log2 length ratio of each vertex's most deformed edge, against the rest shape. It is
  absolute, so the original mesh's own flaws show too. Red = stretched, blue = squashed, and a words line names the
  joints there.
- Bench time is 8–28 ms per view.
- Images are kept in `<unit>/views/` (the last 24) and served at `/api/view/<k>.jpg`.

**Checklist.** `{"op":"note", ...}` adds items or sets an item's status. The checklist lives in `stack.json`
(`checklist`) and is shown in the state line as `CHECKLIST: ...`.

**Mesh tools** (in `rig.py`, replayed like every other mop):
- **Where they act.** Every region is geodesic: a Dijkstra search over the position-welded surface graph from the seed
  vertex, so a region stays on the part it starts on. The seed is a point given in words: `at` a joint, `toward` a
  direction (that joint's outermost skin that way), `along` toward the child joint, `offset` in body heights.
- `sculpt` changes the rest shape. Modes: move, scale, inflate, deflate, smooth, flatten. It writes POSITION/NORMAL in
  the rig GLB, and the round trip is tested.
- `rebind` binds the core of a region rigidly to one joint: the generic "island" rebind. The troll, wyvern and Roc
  meshes are each one connected piece, so a region stands in for an island.
- `paint` moves skin weight toward or away from one joint.
- `corrective` is a sculpt delta stored as an extra morph target. Its weight is computed in `Unit.pose` from how close
  the joint's local rotation is to the reference pose, relative to the bind rotation (a smoothstep). GPU/CPU parity is
  tested.
  - Correctives exist **in the bench only**. The export and the viewer GLB don't carry them: glTF has no pose drivers,
    so they would have to be baked into per-clip morph weight channels.

**Speed.**
- The driver starts a new CLI session once a turn's context reaches `--rotate-tokens` (24k), with a maximum of
  `--rotate` steps (60).
- NET POSE now shows a range and a peak frame per axis instead of a value per frame. It covers the focus clip only,
  plus the names of other clips that have edits.

**Viewer.**
- A live survey checklist, ticked as items are fixed, and the current phase.
- A gallery of Haiku's camera views; click one to orbit the 3D view there.
- With "follow Haiku" on, the 3D camera jumps to each new view: clip, frame, yaw, pitch and box.

## Round 4: coarse-to-fine funnel (2026-10-08)

Round 3 stalled on small items in loops, so the fix phase is now a funnel, run by `funnel.py` (state in `stack.json` under `funnel`).

**Severity.** Every survey note needs a `"sev"` of BIG, MEDIUM or SMALL, and Haiku rates them itself. A note without one is refused with a one-line reason.
- BIG means wrong at a glance: attitude, gaze or facing, the wrong action, a missing beat, or gross mesh breakage.
- MEDIUM means limb articulation, timing, or a local tear.
- SMALL means polish.

**Tiers.** The tiers run BIG, then MEDIUM, then SMALL, and each gets a budget from `--steps`: 50%, 30% and 20%. Unused steps roll forward, and a tier with no open items is skipped. When a tier's budget is spent, the run advances and parks the tier's open items.

**Tier exit.** When every item in a tier is closed, Haiku checks from 2 or more free-camera yaws taken since the last kept change, then sends `{"op":"tier","to":"next"}`.

**Moving between items.** `{"op":"note","work":id}` picks which item to work on.

**Re-survey.** On entering SMALL, parked items reopen once. Haiku may re-survey at this point. A new or reopened BIG item jumps back to the BIG tier and borrows at least 10 steps from the current tier.

**Loop breaking.** This is tool behaviour and makes no quality judgement. The current item is parked when any of these happen:
- one joint and axis flips sign 3 times;
- 5 reverts happen in a row with no kept net change;
- 12 steps pass on the item with no kept net change.

The net change is tracked as a fingerprint of the rounded net stack plus the mesh/rig op ids. The tool tells Haiku in plain words ("parked #k: you've cycled on X; move on") and names the next item.

**State line.** A new `FUNNEL:` line shows the tier, steps used against budget, the remaining budget of later tiers, the NOW item, the check progress and the parked ids. The CHECKLIST line shows only the current tier's items in full.

**Viewer.** The checklist card shows:
- tier bars with steps used against budget;
- severity badges;
- the NOW item highlighted;
- parked items with their reason;
- a log of funnel events.

**Driver.** It passes `steps` to `/api/reset` and stops when all tiers are DONE.

**Test.** `scratchpad smoke_r4.py` exercises the funnel's code paths without Haiku: refusal of a missing sev, parking on flips, tier skip with rollover, the check, revisits, and the BIG jump-back.

## Round 5 (2026-10-08): intents, candidates, a blind judge, items with tabu

`haiku_driver.py --r5 ...` runs `r5_driver.py`, and the server's `R5Mode` (`r5_bench.py`) takes over `apply` after `/api/reset {"r5": run_dir}`.

- **Intents** (`intent.py`). Goals are `gaze`, `trunk`, `reach`, `spread` and `bend`, stated against a READOUT of our own pose.
  - A weighted DLS solver with an analytic Jacobian spreads the turn along a chain.
  - Each intent produces candidates V1–V4: 50%, 100% and 150% of the goal on the default chain, plus an alternate chain (or 75%).
  - Torn joints are down-weighted and the solve is rerun.
  - One intent turns at most 40° at 100%.
- **Blind judge** (`r5_driver.judge`). It makes two fresh `claude -p` Haiku calls with no history, showing the same before/after pair in both orders.
  - A change is kept only when AFTER wins both orders.
  - An item closes only when the judge also says the problem is fixed.
- **Item list with tabu** (`r5_items.py`). The store is `items.json` in the run folder.
  - Every rejected attempt (item, goal, limb, chain, direction, strength, frames) is tabu for the whole run and is shown every turn.
  - After 4 rejections in a row an item is parked, and gets one second pass.
- **Mesh repair** runs automatically after each accepted change. A repair is kept only if total tears go down and no clip gets worse.
- **Outputs** per run: `steps.jsonl`, `judge.jsonl`, `items.json`, `before_after.jpg` (DEF, then the battle, preview and yawed 3/4 cameras, before and after), `summary.json` and `summary.txt`.
  - `python r5_report.py --table` prints the round 4 vs round 5 comparison.
