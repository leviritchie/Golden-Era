# Surface: Live probe / OfficialDeobf build

## Intent

Run live diagnostics or Golden Era compile checks without confusing install selection.

## Ownership preference

- **Play / probe install:** Golden Era path above.
- **Compile profile:** `OfficialDeobfBuild=true` (and related identifiers) for correct interop — not a claim that a separate “Official Deobf Experiment” folder is the active game.

## Touch points

| Kind | Path |
| --- | --- |
| Live probe README | `tools/live_probe_mcp/README.md` |
| Bridge enable | deployed `config.json` `homm3LiveProbeWorkbench` or `homm3_live_probe_workbench.flag` |
| Bridge dir | `…/BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/` |
| Law pilots | `docs/custom_law_runtime_pilot_plan.md`, `tools/release_port/custom_law_diag_flags.py` |
| Documentation contract | forbids “Deobf build only” in live probe README |

## Pitfalls

- Do not enable the live probe bridge during unrelated tests unless the test owner expects it.
- Diagnostic flags are process-cached — relaunch after apply/clear.
- Broad UI bind probes (e.g. Warcry container) belong in separate profiles from sanitized combat law pilots.

## Open unknowns

None for install selection: Golden Era is authoritative. Remaining unknowns are per-packet pilot evidence, not which folder to launch.

## Proof

Bridge up = startup/tooling proof only. Combat claims still need labeled runtime evidence.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
