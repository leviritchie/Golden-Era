# Surface: Battle Direct State / native Core donors (index)

## Intent

Choose correctly between **native Core mechanics** and **Direct State** without rewriting the full DS corpus here.

## Ownership preference (resolved conflict)

**Prefer native verbs** when a Core donor exists (`teleport`, `push_unit`, buffs, traps, ability envelopes). Direct State owns **traced** store transactions (e.g. hex `bfdi` triad) when journal/rollback is required — and still needs presentation proof (`emz`, etc.). Static dossiers are not ship permission.

This supersedes older “reach for DS first” habits and any archived note that treated CapLog store agreement as combat done.

## Touch points

See read order below; do not duplicate full DS recipes in this card.

## Read in this order

1. `.cursor/skills/decomp-search/SKILL.md` (+ `pitfalls.md`)
2. `docs/battle_state_logic_map.md`
3. `experiments/direct_state_movement_trace/mono_live_pin_table.md`
4. `docs/direct_state_adapter_dossiers.md`
5. Family handoff if present (`docs/direct_state_movement_static_trace_handoff.md`)
6. `docs/runtime_mechanics_implementation_handoff.md`
7. Recovery tooling: `experiments/olden_cs_recovery/README.md`

## Pitfalls

Banned product patterns (summary):

- Helper + `cfqf` dual-write; `cfqf`/`bcxo` as occupancy
- `edb` as movement publish hub
- Method_N invent; donor restore as product
- Shipping MovementPush/Teleport from static dossier alone
- DamageApplied-time occupancy as design owner

## Proof bar

`source/static` → … → `user-visible gameplay`. MovementPush remains gated.

## Open unknowns

Per-family `plant_incomplete` methods and presentation owners — track in `battle_state_logic_map` / dossiers, not here.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
