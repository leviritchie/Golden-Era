---
name: decomp-search
description: >-
  Navigate Olden Era / Golden Era IL2CPP decompilation evidence for battle
  mechanics, Direct State, Core donors, and mono→live name pins. Use when
  choosing native vs Direct State ownership, tracing push/teleport/damage/
  occupancy, resolving obfuscated types (egd/ehh/bfdi/eda), reading dump.cs
  or asm, or before inventing combat writes. Prefer this over guessing from
  HotA text or prior failed pilots.
---

# Olden Era Decomp Navigation

Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`.

Build identity is not the folder name. This install now hosts Steam build 25672315 / `GameBuildKind.Current`, selected by the installed `GameAssembly.dll` hash. Legacy `GameBuildKind.Golden` / D477 pins and decomp examples below remain compatibility or historical evidence, not current-name authority. Revalidate native names against this build before use; see [current consolidation](../../../docs/current_version_consolidation.md) for the receipt and proof boundaries.

Obfuscated names live in `GameSymbols.cs` (or established resolvers) — do not scatter new generated names in feature code.

## When to open this skill

Branching technical choice in HoMM Olden Era modding: ability ownership, combat mutation, event hubs, Core mechanic rows, IL2CPP recovery, or “why didn’t this shove/teleport work?”

## Non‑negotiable rules

1. **Evidence labels** — every claim needs one: `source/static`, `xref`, `live-positive`, `live-negative`, `hypothesis`, `contradicted`. A `live-negative` beats static guesses about the same API.
2. **One solution** — no silent fallbacks; fail closed with diagnostics.
3. **Store ≠ product** — CapLog / dual-readback of hex stores is not user-visible combat. Presentation owners (e.g. push `emz`) matter for gameplay proof.
4. **Prefer native verbs** — if Core already has a working mech/spell shape (`teleport`, `push_unit`, buffs, traps), own that envelope before inventing Direct State mid-damage writes.
5. **Dump ≠ live** — June dump / mono demo names drift vs Golden Era DummyDll. Pin live types before coding (e.g. mech factory is live `egd.bdpz`, not dump `egb.bdoh`).
6. **Do not invent** Method_N event publishes, second write paths, or occupancy via `Hex.bcxo`/`cfqf` (`lastCorpse`, not occupants).

## Navigation order (do this)

```
Decomp navigation:
- [ ] 1. State the desired verb in player terms (move enemy 1 hex, damage, buff…)
- [ ] 2. Search Core donors first (unit special / spell), not IL
- [ ] 3. If donor exists: copy/reshape envelope; prove combat
- [ ] 4. If no donor: open battle_state_logic_map + pin table for that family
- [ ] 5. Trace config → factory → apply → presentation → commit
- [ ] 5b. Hook arg type vs map/plan key type: read GameSymbols hints for the
      hook parameter; if they differ from your dictionary key type, bridge
      before lookup (Unit.Init[2]=ObjectPublicPrcgObPrcgInTrPrcgInUnique via
      SideTypeHints → TransferSide via BattleSideTransferSideMembers; eir is
      legacy alias only). Do not key by TransferSide and probe with __args[2]
      unbridged. Native-pointer keys fix managed re-wrap; distinct CapLog
      nativeKeys mean different objects / wrong ownership key.
- [ ] 6. Label gaps (plant-incomplete, ordinal-inferred, hypothesis)
- [ ] 7. Only then consider Direct State owning a traced store transaction
```

### Step 2 — Core before IL

```bash
# Example: find mechanic shapes in installed Core
python -c "import zipfile,json; z=zipfile.ZipFile(r'V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip'); ..."
```

Prefer known live donors:
| Intent | Prefer |
|--------|--------|
| Move enemy to chosen free hex | Schism `arbitrator:abilities:1` (`teleport`, ordered hex) |
| Ally reposition | `arbitrator:abilities:0` (`teleport`) |
| Axial shove / pull | `push_unit` values (`false` away; frog Tongue `["true","false"]` + hex select) |
| Self-destruct AoE | `lava_larva:abilities:0` |
| Corpse harvest | `locust:abilities:0` |

Ability overrides: `custom_factions/ability_overrides/homm3_*.json`. Overlay apply: `tools/release_port/apply_release_core_overlay.py`.

### Step 4–5 — Map + pins

Read in this order:

1. `docs/battle_state_logic_map.md` — claims S*/W*, domains, contradiction log
2. `experiments/direct_state_movement_trace/mono_live_pin_table.md` — mono↔live pins
3. `docs/direct_state_adapter_dossiers.md` — per-family DS recipe (not ship permission)
4. Family handoff if present (e.g. `docs/direct_state_movement_static_trace_handoff.md`)

For deeper recovery tooling: `experiments/olden_cs_recovery/README.md` (IR, proof ledger, plant probes).

### Direct State decision

| Situation | Action |
|-----------|--------|
| Native donor + correct envelope | Keep native; DS off for product |
| Native mech exists, envelope wrong | Fix envelope/reshape; do not mid-damage invent |
| Need store transaction with journal/rollback | DS owns **traced** commit (`bfdi` triad for hex); still need presentation proof for view |
| CapLog agree, screen wrong | Not done — find presentation owner |

**Banned product patterns:** helper+`cfqf` dual-write; `edb` as movement publish; store-only CapLog as combat proof; DamageApplied-time occupancy as design owner.

## Proof promotion bar

Do not claim readiness without the matching label:

- source/static → generated → build → **deployed** → startup smoke → **runtime** → **user-visible gameplay**

Static dossier finished ≠ MovementPush/Teleport product ungated for custom abilities.

`planned:` / plan-dict populated ≠ buff path applied. Plan-build logs prove only that plans were stored under some key; apply proof needs a hit on the same key family the apply hook uses (after any type bridge) plus apply/verify logs.

## Obfuscation hygiene

- Resolve via `GameSymbols` / DirectState law members already exported.
- New live pins: add to pin table + GameSymbols; do not hardcode RVAs in feature hooks.
- Neighbour **fields** (`_cfqh`…`_cfqm`) are readable; invoking Hex neighbour getters can AV.

## Additional resources

- Artifact index: [map.md](map.md)
- Hard-won pitfalls: [pitfalls.md](pitfalls.md)
- Product surfaces (Heroic Strike, unit overrides, laws/damage, specializations, town index): use skill `agent-surface-guide` and `docs/agent_surface_guide.md` — keep this skill focused on battle/decomp ownership; the surface guide owns designer/mod “what can I change?” navigation.
