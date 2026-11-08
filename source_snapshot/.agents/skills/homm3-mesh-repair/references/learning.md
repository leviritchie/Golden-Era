# Learning Contract

The canonical store is `references/learning_index.json` (`repair_learning.v1`). Do not
add a second journal/schema. Detailed experiments remain in artifacts, not skill context.

```powershell
py -3 .agents/skills/homm3-mesh-repair/scripts/repair_knowledge.py validate --verify-evidence
py -3 .agents/skills/homm3-mesh-repair/scripts/repair_knowledge.py query --body-plan biped --signature fused-grip --unit h3_grand_elf
```

`batch_operator.py context` returns relevant rules and verifies selected evidence hashes.
The standalone query also verifies selected evidence by default. Both cap
selection at six. Exact body-plan/signature tags, unit scope, narrower applicability and
deterministic ordering prevent a failed biped experiment from governing unrelated assets.

Each rule requires `id`, `bodyPlans`, `signatures`, `scope`, `kind`, `action`, nonempty
`prerequisites`, `proof`, and `evidence` (`path`, `sha256`). Paths are repo-relative and
must exist; hashes pin evidence, not causality. Unit scope requires `units`. Allowed proof
tiers: `diagnostic`, `source_validated`, `generated_artifact_validated`. This lane never
upgrades a rule to runtime proof. Use `apply_patch` to add/replace a record, then validate.

`negative` records name a failure signature and the decision to avoid. They do not claim
the asset is unrepairable. `recipe` records additionally require `applicability` and
`improvements`: `{unit, metric, before, after, direction, evidencePath}`. Evidence must
show positive improvement, and class recipes need two independent units. These structural
checks do not certify beauty: review all regressions and retain before/after visual proof.
Only publish a final-quality route after complete visual QA, not a lower stretch value.

For a fresh result, keep only: trigger -> preconditions -> proven operation/negative ->
limit. Put seeds, vertex IDs, parameters and resulting candidate hashes in the linked
recipe/report. Update a superseded rule in place, retaining the artifact history. Never
generalize a single hand mask or orientation angle into a fleet default. A changed source
or changed rule evidence must be revalidated rather than silently accepting new bytes.

Import API: `load(path=INDEX, check_evidence=False, verify_evidence=False)` performs
structural validation without opening unrelated artifacts;
`validate(index, check_evidence=True, verify_evidence=False)` checks evidence existence;
`select(index, body_plan=..., signatures=None, unit=..., limit=6, verify_evidence=True)`
verifies selected evidence hashes. Omitted signatures select all applicable signatures,
not all body plans or unit scopes.
The helper is standard-library-only. Tests exercise scope, mutations, ranking and recipe
evidence. No startup/build/deploy contract is introduced by this diagnostic knowledge file.
