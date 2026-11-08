# Surface: Damage mutation / law runtime

## Intent

Change how much damage is dealt or taken for faction laws, training-style effects, or other combat scalars — and know which path is product-safe today.

## Ownership preference

| Design shape | Prefer |
| --- | --- |
| Passive % melee/ranged/counter damage, in/out modifiers | **Native law** `unitStat` with `modifierSet` / `outDmgMods` / `inDmgMods` (and related) via law overrides + overlay |
| Event-conditioned damage the table cannot express | Packet-gated runtime (`Homm3TrainingDamageLawRuntime` and related law runtimes) **only after** packet proof promotion |
| Journaled multi-step combat write | Direct State adapter with traced store — **not** a second silent damage owner beside training-damage |

One problem → one damage owner. `docs/runtime_mechanics_implementation_handoff.md`: training-damage must not invoke the runtime-mechanics manager alongside competing committed-damage ownership.

## Touch points

| Kind | Path |
| --- | --- |
| Law authoring | `custom_factions/law_overrides/`, overlay `DB/fractions_laws/*` |
| Law status | `docs/custom_law_implementation_status.md`, classification JSON |
| Packet gate | `Homm3CustomLawPacketGate`, `custom_factions/custom_law_packet_proofs.json` |
| Evidence matrix | `docs/gameplay_surface_evidence_matrix.md` (`committed-damage`) |
| Training / hard-law CSV executor | `OfflineUnlockMod/Homm3TrainingDamageLawRuntime.cs` (exact Unit damage prefix; inert while gate closed) |
| Damage method pin | `GameSymbols.BattleEventLaws.BattleUnitApplyDamage` (do not add stale `bbgw` fallback) |
| Profiles / plans | `Homm3CustomLawEffectProfiles.cs`, `Homm3CustomLawEffectPlans.cs` |
| DS damage family | runtime-mechanics adapter manifest `damage` / ingress docs |

## Can change / cannot

**Can:**

- Express many law damage intents as native `unitStat` rows (Officer Corps-style outgoing damage, counterattack doctrine via `outDmgMods.counter_attack`, melee/ranged formation pairs, etc.).
- Prepare source profiles and predicate maps without enabling gameplay.

**Cannot:**

- Set `gameplayAllowed` / mutate combat because static identity is “strong”.
- Register training-damage and Direct State damage adapters as dual product owners.
- Treat CapLog / pilot `+1` fixtures as law balance proof.
- Assume Heroic Strike script math applies to creature attacks.

## Requirements

- Native-data laws: overlay + faction manifest validators + no-compromise static where required.
- Runtime mutation: exact packet proof, exact method bind, caster/law-owner resolve, fail-closed CapLog rejects, typed damage arg dossier.
- DamageApplied-style adapters need prefix/`__state` pairing when applicable.

## Pitfalls

- Damage `__0` is an attacker interface, not a ready `Unit` — unwrap before classify.
- Ability identity may be a lang key, not a pretty English name.
- `Homm3TrainingDamageLawRuntime.TryRegister` remains gated; startup audit may report `NOT_ATTEMPTED` or `BLOCKED_BY_PACKET_GATE` — that is expected, not “secretly on”.
- June-dated law status docs say native-data-implemented for the mass of rows; do not revive speculative Rampart Avenger / similar hooks without revalidation.

## Proof labels

| Claim | Label |
| --- | --- |
| Native outDmgMods / unitStat law shapes in Core tables | `deployed` / `source/static` |
| Committed-damage method identity candidate | `proven-live-metadata` (matrix) — mutation semantics **unproven** |
| Training-damage product gameplay | **not promoted** (packet gate) |
| DS damage fixture `+1` | diagnostic only |

## Open unknowns

- Final damage ordering and safe mutation semantics for committed-damage writes.
- Whether Plugin wiring must explicitly call `Homm3TrainingDamageLawRuntime.TryRegister` from a single registration owner before pilots can ever leave `NOT_ATTEMPTED`.
- Ordinary unit Attack/Defense gap formula location in live IL (separate from hero ability script).

## Do-not-miss checklist

- [ ] Ask: can this be a Core law modifier? If yes, do that.
- [ ] If hook-required: name the packet, proof file, and single owner class.
- [ ] Pin live damage method via GameSymbols; no `bbgw` fallback.
- [ ] Do not share committed-damage ownership with Direct State.
