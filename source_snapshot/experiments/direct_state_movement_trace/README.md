# Direct-state movement static trace (finished 2026-07-20 / Iteration 11)

Artifacts from GE-pinned Capstone disasm of live `GameAssembly.dll` against `tools/il2cpp_out_20260719_golden_era/` + DummyDll method pointer CSV.

**Status:** static commit-store dossier finished (stores + dest + publish field). Grok Phase 2 accept-with-fixes; **no Phase 3**. MovementPush still gated. Not gameplay proof / not readiness.

Authoritative write-up: `docs/direct_state_adapter_dossiers.md` § movement, `docs/battle_state_logic_map.md` (S31–S45 / W11), `docs/direct_state_movement_static_trace_handoff.md`.

**Mono → live pins:** [`mono_live_pin_table.md`](mono_live_pin_table.md). Includes `ehh_Init.asm.txt`, `ehh_bdpe.asm.txt`, `Hex_bcyf.asm.txt`.

**Remaining (ordered):** `emz` necessity (runtime) → `cfhz` fire? → subscriber types → ordinal drift → optional `set_hex`/`ejr` parity.

Do not re-enable MovementPush from these files alone. Do not reuse dump-era `edb`≈Logic / `cfkg`↔`OnUnitChangedHex` as live GE movement publish truth (`docs/edb_dxy_mono_xref_surface_mapping.md` is bannered superseded for that use).
