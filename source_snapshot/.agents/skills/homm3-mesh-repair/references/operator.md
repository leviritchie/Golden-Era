# Internal Batch Operator

This helper executes approved fit/preview steps and checks retained QA provenance.
It does not generate repair decisions, call an LLM, authorize Meshy spending or certify
beauty. The invoking unit worker (GPT-6 Astra by default, or a user-selected model) owns
ALL intervening repair iterations during the same skill run. The parent/orchestrator is not the unit worker and must not run Meshy, image
preparation, Blender MCP, fitting, replay, render or review calls on the worker's behalf.
It must not spawn nested workers or reviewer chains. A user invocation is:
"Repair <units> end-to-end using homm3-mesh-repair and distill reusable learnings."
Do not ask the user to operate the internal phases. If the requested worker cannot be
assigned, the current invocation still completes feasible non-paid stages and retains
the best available artifact and verdict. Defer only actions that require unavailable
authority or capability (for example a cost-confirmed Meshy call or independent review);
record the concrete next action and never label a partial result accepted.

```powershell
py -3 .agents/skills/homm3-mesh-repair/scripts/batch_operator.py context --units h3_grand_elf h3_skeleton
py -3 .agents/skills/homm3-mesh-repair/scripts/batch_operator.py prepare --manifest <batch.json>
py -3 .agents/skills/homm3-mesh-repair/scripts/batch_operator.py finalize --manifest <batch.json>
```

`context` prints only selected source/candidate paths and matching learned rules. It is
read-only and does not reinterpret inventory provenance as semantic approval. `prepare`
runs one heavy subprocess at a time, checks fingerprints, writes logs and returns internal
QA requests. Stage failures are explicit and yield nonzero exit; never call them success.
The default per-attempt `renderMode` is `review`; choose `full` for finalists. Timeouts
bound individual commands (fit 1200s, packet 300s), not the user's overall quality objective.

Use a fresh isolated workspace, outside the production fleet directory. Example structure:

```json
{
  "workspace": "artifacts/repair_batch_example",
  "resourceBudget": {
    "maxUnits": 1,
    "maxRepairAttemptsPerUnit": 2,
    "maxMeshyBodyGenerations": 1,
    "maxMeshyPropGenerations": 1,
    "maxIndependentReviews": 1,
    "maxBlenderSessions": 1,
    "allowNestedDelegation": false
  },
  "units": [{
    "unit": "h3_grand_elf",
    "maxAttempts": 2,
    "attempts": [{
      "fitManifest": "artifacts/repair_batch_example/fit.json",
      "packetDir": "artifacts/repair_batch_example/attempt1-review",
      "review": "artifacts/repair_batch_example/attempt1-review.json",
      "renderMode": "review",
      "hypothesis": "Separate the verified complete bow from hand before rigid ownership"
    }]
  }]
}
```

The fit manifest uses the existing `jobs` schema (`unit`, `bodyPlan`, `mesh`, `runDir`,
`sourceReport`, `out`, plus `propAttachments` and `propOrientation` for any unit whose
source plates show carried equipment). A body-only job is an intermediate diagnostic,
not a complete repair attempt. Candidate/packet output directories
must be disjoint. Append explicit attempts after internal diagnosis; do not silently try
fallbacks. `maxAttempts` is an explicit experiment budget, not a license to hand back after
two tiny edits. Exhausting it while useful routes remain means continued unfinished work.
Fresh candidate directories receive a `batch_attempt.json` ownership stamp. A nonempty
directory without a matching stamp is refused, never silently overwritten. Workspace logs
and result/state files are reserved and cannot overlap candidate or packet outputs.

For retained evidence, `reuseExisting:true` allows a candidate outside the workspace but
NEVER runs the fitter against it. It generates a fresh packet only; stale input fingerprints
or missing full reels refuse final approval. Reuse does not patch provenance or inherit old
visual acceptance. Existing valid packets are reused; stale/incomplete packet directories
are not overwritten. Use a fresh packet version if preparation was interrupted.

## Agent QA

The named reviewer inspects actual native panels and the full moving reel, not a summary
or thumbnails. Write a supplementary review JSON with:

- `candidateFingerprint`: exact fit report fingerprint.
- `artifacts`: SHA-256 map for fitted_bind.glb, retargeted_motion.npz and, when present,
  detail_reel.gif; `inspectedPanels`: actually viewed `{path,sha256}` entries.
- `decision`: `pass` or `reject`; `reviewedFrames`: actually inspected global indices;
  `fullReelReviewed`: actual boolean; `repairWorker` and `reviewer`: actual agent IDs.
- `gates`: identity, alignment, orientation, surface, ownership, prop, contact, continuity;
  each is `{pass:boolean,evidence:...}`. Do not set true for an unperformed audit.
- `nextAction`: concrete internal repair for a rejected result.

Passing requires every gate, all selected individual panels, both hashed `restPanels`
(front and side), full reel inspection and
independent reviewer identity. These are validated attestations, not automated perception.
Hashes prevent a review silently attaching to changed bytes. Regional ownership and
boundaries still need real review, even when whole-body metrics look good.

`finalize` emits only accepted candidates plus genuine exceptions to `batch_result.json`.
Accepted results pin the candidate fingerprint and review/packet hashes as well as mesh,
motion and reel bytes; a mutable review path alone is not approval provenance.
Exception closure requires `sequenceClosure` entries for source, registration, ownership,
props, regeneration, each with `state` (completed/not_indicated/exhausted/blocked), concrete reason
and hashed evidence. At least one relevant route must actually be exhausted or blocked,
plus `exceptionNextAction`. A rejected prop cut with more repair work available is NOT a
terminal exception; leave it internal. Stage execution failures must be resolved/triaged,
not relabeled visual success. Exceptions set `workRemaining:true` and never prove the
user's requested pristine result. This is not a replacement fleet/build acceptance schema.
An unavailable preview needs no fabricated visual review: a matching job/attempt
`stage_exception` in `working_state.json` can support an unfinished exception, with the
same evidence-backed route closure. Exit codes are 0 for a successful phase, 1 for a
stage/validation failure, and 2 for finalized exceptions with work remaining.
The failure identity includes the selected job, render mode, reuse flag and packet path;
changing these requires a new preparation result, not inherited failure evidence.

Keep the final outcome compact. Distill learnings through the one index before closing.
The retained original pilot had two quality rejections, not a successful finished mesh.
