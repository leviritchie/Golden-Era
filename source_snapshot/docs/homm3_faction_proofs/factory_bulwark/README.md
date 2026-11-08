# Factory + Bulwark Proof Notes

Evidence home for Factory and Bulwark combat / town pilots. These notes are
**not** runtime proof by themselves. Promote a claim only when the matching
`PROOF.json` (combat) or town smoke checklist is filled from a live Golden Era
session.

## Naming

| Kind | Path pattern |
| --- | --- |
| Shared index (this file) | `docs/homm3_faction_proofs/factory_bulwark/README.md` |
| Split Assembly combat proof pack | `artifacts/factory_split_assembly_combat_proof/v1/` |
| Bulwark combat proof pack (Focus / Frostbound / Runes) | `artifacts/bulwark_combat_proof/v1/` (scaffold; no PROOF.json pass yet) |
| Future Runes-only combat proof pack | superseded by `artifacts/bulwark_combat_proof/v1/` unless a narrower pack is needed |
| Town smoke notes | keep under this folder as dated `*_town_smoke.md` files |

Version folders use `v1`, `v2`, … when the fixture contract changes. Do not
overwrite a filled proof pack; add a new version.

## Graduation rules

### Combat (Split Assembly / Runes / unit abilities)

A combat claim may move from **runtime-unvalidated** to **runtime behavior
proven** only when all of the following exist:

1. A versioned artifact folder with a real `PROOF.json` (not a placeholder).
2. Matching BepInEx log excerpts that include the owned grant / apply lines
   (`planned:`, `applied unit buffs: unitSid=… verified=…`, Focus grant, UI
   criteria as required by the case matrix).
3. The case matrix rows for that claim marked pass with date + install identity.
4. Validators that still say "unvalidated" are updated in the same change that
   lands the proof pack — never before.

Fail-closed: missing `verified=true` on required buff SIDs, missing Focus grant
when Natural tier 3 is claimed, or dual-bound Defend handlers is a fail, not a
soft pass.

### Town (owned `cityFactory` world)

Town claims graduate only with cold-start Custom Game smoke notes that record:

- active scene / ownership logs
- hall construction open
- no unbound Castle-slot activation for buildings lacking `nativeLevels`

Factory town presentation already has a prior user-visible proof record in
`docs/custom_town_scene_paradigm.md`. Bulwark town remains **wired, not
Bulwark-specific user-visible proven** until its smoke note lands.

## Marshal Suppressing Fire trap registration (2026-07-25)

Code: `Homm3MarshalSuppressingFireTrapBridge` +
`GameSymbols.MarshalSuppressingFireTrap`.

Architecture remains jaws/VFX placement with Wall-of-Flame CastDealerConfig
damage stamping at trap `Init` (150% placer stack `damageMin`/`damageMax`, flat
base writes, stack damage and `statDmgMult` zeroed). Live type pin is
`FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique`; `ekh` is legacy alias only. Instance
TrapConfig pin leads with `_cgtl_k__BackingField`.

Proof boundary after the registration repair (fresh Golden Era cold start
2026-07-25):

| Claim | Status |
| --- | --- |
| Startup Harmony registration against live Golden Era interop | **startup registration proven** — BepInEx: `HOMM3_MARSHAL_SUPPRESSING_FIRE registered architecture=marshal_suppressing_fire_wall_of_flame_stamp init=FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique.Init` with no `Could not find type named ekh`, `trap_runtime_type_unresolved`, or plugin Load abort |
| Combat stamp execution / observed trigger damage | **unproven** — do not enter combat to claim this |

Resolution notes from the repair: prefer `AccessTools.GetDeclaredMethods` over
`AccessTools.Method("Init")` (base `FieldObject.Init` made the latter
`AmbiguousMatchException`), and patch with `object[] __args` (live first arg is
`param_1`, not `sid`; named-arg postfix caused Harmony IL compile failure).

Static gates: always-on
`tools/validate_homm3_marshal_suppressing_fire_runtime_contract.py`; opt-in
`tools/release_port/validate_gamesymbols_runtime_interop_evidence.py` proves the
generated type exposes six-argument Boolean `Init` and
`get__cgtl_k__BackingField` → `TrapConfig`.

## Shared combat force-setup (pilot only)

Code: `Homm3FactoryBulwarkCombatForceSetupPilot`  
Flag (must exist to arm): `BepInEx/plugins/OfflineUnlockMod/homm3_factory_bulwark_combat_force_setup_pilot.flag`  
Config (required when flag present): `…/homm3_factory_bulwark_combat_force_setup.json`  
Example: `OfflineUnlockMod/homm3_factory_bulwark_combat_force_setup.example.json`

Enable for Golden Era pilots:

1. Copy the example JSON to `homm3_factory_bulwark_combat_force_setup.json` next
   to the plugin DLL.
2. Edit `factionSid` (`homm3_factory` or `homm3_bulwark`), `skillRank` (usually
   `3`), Factory-only `attachOverclockSubskills`, and optional `startArmy`.
3. Create the empty flag file named above.
4. Cold-start Golden Era, fight with that faction, then **delete the flag**
   (and preferably the JSON) before any normal play or release deploy.

Fail-closed behavior: flag without config, invalid faction, missing faction
skill on the matched side, or overclock attach without a clonable subskill
donor throws at battle init. The pilot is idle when the flag is absent.
Release-safe profiles must not ship the flag.

## Split Assembly skill-read fix (2026-07-24)

Live Golden Era log showed `Factory faction skill not present` while
`Player.log` Session::Logic listed `skill_faction_homm3_factory` on the same
hero. Root cause: Split Assembly (and the force-setup pilot) enumerated
`HeroSkills` via managed `IEnumerable` foreach, which yields nothing on the
Il2Cpp list. Fix: Count + int indexer first (same pattern as skeletal/
Dominion hooks). Deployed OfficialDeobf DLL includes the fix; retest Custom
Game Factory combat for `planned:` / `applied unit buffs:` / `verified=`.

## Human live checklist (after Phase 0)

1. Bulwark town smoke (cold start, Custom Game).
2. Split Assembly C0–CNeg–C5 — cold-start after the skill-read fix; arm
   force-setup only for Expert/overclock cases.
3. Ability P0 (Blow Up, Locust, Jotunn Slow).
4. Runes Phase A (live bridge → volatile probe → product hooks).

## Parked (do not execute from this folder)

- Authored `cityFactory.unity`
- Gantry / Mother Nature scene v2 slots
- Campaign Phase B/C
- Sieidi / Altar
- Brand Phase C product pin
- Fair research beyond Trade Carnival
