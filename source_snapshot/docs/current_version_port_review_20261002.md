# Current-Version Port Independent Review

Status: source/static review and small isolated behavior fixtures, 2026-10-02.
This is a dated review snapshot, not an active port contract or runtime acceptance.
No port implementation was changed, no payload was installed, and no game was launched.

## Review Findings

Reviewed `tools/port_current/carry_scope_overrides.py` while it was untracked.
SHA-256: `225DA0A8AFF7FFBACBCDCADD9E60AA69D7447FC47C9652F3A872A5B037508C47`.
Line references below apply to that snapshot; fixes remain with Claude.

1. **P1: Missing method-body evidence does not prevent automatic carry.**
   Lines 145-162 collect similarity only when both native addresses are available.
   When no score exists, no review problem is added and lines 169-181 accept the entry.
   `symbol_remap/native_body.py:269` permits an absent address. A no-write in-memory
   fixture with a mapped method but no old native address returned success and emitted
   the new method name without `bodySim`, while the evidence said "native body on."
   Require usable body evidence for each carried method, otherwise place the entry in
   `needsReview`. Non-method entries need their own applicable evidence, not a fabricated score.

2. **P2: Positional type-check metadata can silently truncate an override.**
   Lines 113-115 zip the live literals with the checks without validating equal lengths.
   A fixture containing two live positions and one check returned success with two
   `goldenLiterals` but only one `live` and one check. Validate the positional input
   before matching, and retain every live position or refuse the entry. This is a
   malformed-input defect, not a discovered problem in the current 25509697 checks:
   those populated check arrays match their live arrays. The existing explicitly
   split `ModBugReporting.ScreenStaticAutoSend` entry has different golden/live counts
   by design and must not be rejected by a blanket golden/live equality rule.

3. **P2: The generated provenance note claims work the tool does not perform.**
   Line 187 says entries that could not be mapped "were re-derived by hand."
   The tool instead omits review entries and has no input proving their manual review.
   State that omitted entries remain pending manual re-derivation. This is a report
   accuracy issue, not evidence that an incorrect runtime binding has been installed.

No actionable defect was found in the reviewed target/band changes of `37e0486559`.
All three carry-tool findings remain open in this review snapshot. They are not
observed failures of the current game and do not establish that a wrong hook was loaded.

## Claude Progress

- Active target: Steam build `25672315`, depot manifest `7750145598966689713`.
  Independently read the installed Steam appmanifest; the tracked mirror manifest
  records 464 files, 7,203,854,506 bytes, and an identical source comparison.
- Current coordinator: `62e3d473-0df1-4a53-8f68-a115540b553d`.
  Its port subagent is `agent-a75467b1f303b4a88`, "Port to Steam hotfix build."
  Bounded session evidence corroborates the completed mirror and index milestones.
- Index generation completed at 15:46:27 CDT, exit 0, peak private memory 4.14 GB.
  Evidence: `V:/olden_port_work/port_25672315/guard_index.log` and
  `artifacts/port_current/idx2_live_25672315/inputs.json`.
- Commit `37e0486559` records the mirror and `steam_25672315` neutral-band target.
  An independent ZIP comparison found all 304 `DB/units/` members byte-identical
  between `artifacts/port_current/live_25509697/Core.zip` and
  `artifacts/port_current/live_25672315/Core.zip`. Names, content hashes, sizes and
  attributes match; only ZIP timestamps differ. Reusing the earlier bands is supported.
- At 17:28 CDT, live process readback found Claude PID 6276 and the drift wrapper
  PID 29164 with child 41180, still waiting for RAM. The wrapper started at 16:49.
  At approximately 17:30, free physical RAM was 9.58 GiB and free commit 4.28 GiB;
  the gate asks for 6 GiB plus 4 GiB headroom in both. No `guard_drift.log` or
  completed new carry/remap output existed in the inspected locations.
- The generated plugin scopes still name `25509697` in `GameSymbolsCurrent.g.cs:15`.
  `GameBuild.cs` admits only their generated assembly hash, so the new hotfix is
  refused until scopes are regenerated. That is appropriate incomplete-port behavior,
  not a defect in the narrower target/band commit.

The previous build's documented menu/map/town/battle gameplay checks are historical.
They do not prove this hotfix, every required feature, or the later Core/plugin payload.
The current hotfix evidence reaches preparatory/generated artifacts, not plugin build,
installation, startup, runtime, or user-visible gameplay proof.

## Checks And Handoff

- `validate_core_rebuild_layer_order_contract.py`: full gate passed, including its
  fail-closed fixtures and 11-layer contract. Initial sandbox fixture creation failed
  before assertions; the successful rerun used normal filesystem permissions.
- `validate_cross_agent_manager_contract.py`: all 10 isolated tests passed in
  5.422 seconds. The initial sandbox run had the same temporary-directory ACL failure.
- The independent carry review used no-write fixtures; no real remap was run and
  no operational port artifacts were generated by the reviewer.
- Shared-board review project: `d1581356a98742bca66364d6473f5c96`;
  task: `cbefc97628a2401aa30b8b37c545808d`. Only this report and the named review
  resource were reserved. Claude's deployment reservation was not taken over.
- Addressed requests/findings were posted to Claude through the shared mailbox
  (install project messages 7 and 9; setup project message 8). Posting confirms
  persistence, not that Claude has read or accepted them. No reply was observed
  at the final mailbox check for this handoff.

The next useful review boundary is the completed native drift/remap and carry report.
Check omitted entries and hand evidence before regenerated scopes, then run the
scoped-symbol contract, scope-host checks, and the applicable established interop
build gates. Do not promote old-build runtime proof or Golden Era-only reference
checks into current-hotfix runtime proof. Leave heavy job scheduling and implementation
ownership with Claude; do not bypass the memory guard or stop other lanes to accelerate review.
