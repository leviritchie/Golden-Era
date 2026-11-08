# Factory + Bulwark Hard Backlog — Consolidated Execution Order

Conflict-aware order locked from the Phase 0 planning pass. Prefer completing
static/code gates before live play.

## 1. Phase 0 (this execution — static / code)

- 0A Portrait hash refresh for 32 upscaled Factory/Bulwark rows (no full asset rebuild)
- 0B Strip `Build_Intelligence_Academy` / `Build_Training_Range` from constructible
  city rows for owned `cityFactory` peers whose `nativeLevels` lack those SIDs
  (fail-closed; no aliases; no Gantry slots)
- 0C Proof folder scaffolding under `docs/homm3_faction_proofs/factory_bulwark/`
  and `artifacts/factory_split_assembly_combat_proof/v1/`
- 0D Split Assembly log enrichment (`unitSid=`, buff SID list, `verified=`)
- 0E Shared pilot-gated combat force-setup (off by default)
- 0F Bulwark peer-generic deep validator extension (cheap only)
- 0G This consolidated order + faction plan pointers

## 2. Live: Bulwark town smoke

Cold start, Custom Game. Record under the proof README town rules. Do not claim
Bulwark user-visible town proof from Factory's prior hall/world proof alone.

## 3. Live: Split Assembly C0–CNeg–C5

Arm the shared force-setup, capture logs into
`artifacts/factory_split_assembly_combat_proof/v1/`. Keep armies under existing
log caps. Do not promote validators off "unvalidated" without `PROOF.json`.

## 4. Live: ability P0

Blow Up, Locust Harvest, Jotunn Slow combat proof — dealers are already
data-wired (lava_larva / locust / Frostbound Skies runtime). Separate from
Split Assembly graduation. Do not treat these as “missing dealers.”

## 5. Live: Runes combat proof

`Homm3BulwarkRunesRuntime` is registered (Defend/Skip and other gain paths).
Remaining work is installed gameplay / `PROOF.json`, not “bind Defend then
register.” War Mammoth Defend Defense stays a later subscriber scaffold. No
dual-binding.

## 6. PARKED

| Item | Why parked |
| --- | --- |
| Authored `cityFactory.unity` | Accepted synthetic debt; not a near-term gate |
| Gantry / Mother Nature BhBuilding slots | Scene v2 after Castle-parity authored scene |
| Runtime BhBuilding injection | Research-only |
| Campaign Phase B/C | After Split Assembly / Bulwark town / Runes proofs |
| Campaign Phase A | Already done (noop) |
| Sieidi / Altar | Runes + town-slot gated |
| Brand +1 extra (Phase C) | Product pin only after Runes Phase B |
| Fair research (beyond Trade Carnival) | Default skip |
| Creature SFX staging | Out of Phase 0 |
| Dual-binding Defend events | Forbidden; Runes owns the single bind |

## IA / Training constructible policy

Owned-world peers use Castle-parity `nativeLevels`. Constructing Intelligence
Academy or Training Range without a `nativeLevels` entry would activate unbound
Castle donor slots. Overlay generation strips those SIDs from constructible city
rows until scene v2 maps authentic art into `nativeLevels`. Do not alias them
onto Bank/Gantry/other slots.

Tower is the explicit retention exception: `source_mechanics` `tower.library` / `tower.workshop_yard` keep `Build_Intelligence_Academy` / `Build_Training_Range` city rows via `currentRows` even while compositor `nativeLevels` omit those SIDs. Factory/Bulwark/Conflux do not declare those rows and remain stripped.
