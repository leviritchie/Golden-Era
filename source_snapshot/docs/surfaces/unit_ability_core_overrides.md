# Surface: Unit ability Core + overrides

## Intent

Change a custom unit’s actives/passives: Focus (`energyLevel`), cooldown, charges, donor special mechanics, display text/icons, branch-role metadata — and keep Steam Core consistent via the overlay generator.

## Ownership preference

1. **Author** in `custom_factions/ability_overrides/<factionSid>.json` (or ability editor that writes those files).
2. **Apply** through `tools/release_port/apply_release_core_overlay.py` → `apply_custom_ability_overrides_to_custom_unit_rows`.
3. **Prefer native donor specials** (`effectKind: unit-special` + `effectKey` like `arbitrator:abilities:1`) over inventing Direct State mid-damage behavior.
4. Catalog is a **readback/browse** surface, not the authoring source.

## Touch points

| Kind | Path |
| --- | --- |
| Overrides | `custom_factions/ability_overrides/homm3_*.json` |
| Manifests | `custom_factions/homm3_*.json` (`unitLines`, `variantSids`) |
| Core logic/view | `DB/units/units_logics/<faction>/<sid>_l.json`, `DB/units/units_views/<faction>/<sid>_v.json` |
| Overlay fn | `apply_custom_ability_overrides_to_custom_unit_rows` |
| Validator | `tools/validate_custom_faction_manifests.py` (+ ability redesign / icon contracts as applicable) |
| Catalog | `docs/homm3_custom_unit_ability_catalog.md`; `python tools/unit_ability_catalog/server.py` |
| Editor notes | `docs/ability_editor_agent_notes.md` |
| Source mechanics (design-only) | `custom_factions/source_mechanics/` — not executable runtime |

## Can change / cannot

**Can:**

- Enable/disable existing slots; replace display text/icon; adjust `energyLevel` / `cooldown` / `rank` / `charges` on preserved mechanics.
- Replace mechanic by copying a live Core donor special (`unit-special`).
- Set `replaceExistingAbilities` / passives only when intentional (clears arrays).

**Cannot:**

- Hand-edit installed Steam `Core.zip` as the source of truth.
- Strip `branchRole` / `sourceMechanicId` / `decisionTest` (schema-preserving validators).
- Use localization keys or atlas labels like `Orientation@4x` as icon keys.
- Claim catalog text as authoring proof without Core readback.

## Requirements

- Manifest validation before Steam apply.
- Overlay dry-run / no-compromise gates when laws+abilities ship together.
- For combat-critical donor reshapes: decomp-search Core-first workflow; gameplay proof after deploy.

## Pitfalls

- Stock game Core has no `homm3_*` unit rows — editor “current data” must read **patched Golden Era** Core.
- `variantSids` must be honored (Rampart named upgrades are not always `*_upg`).
- Empty `effectKey` with `enabled: false` is a deliberate disable; do not “helpfully” invent a mechanic.
- Runtime-mechanics JSON is a separate lane from ability_overrides.

## Proof labels

| Claim | Label |
| --- | --- |
| Override → overlay → units_logics path exists | `source/static` |
| Catalog generated from live Core readback | `generated` / `deployed` depending on last regen |
| Individual ability combat feel | per-ability; often only `deployed` until playtest |

## Open unknowns

- Which donor specials remain live-negative for intended HotA parity (see faction plans / Stronghold notes).
- Multilingual debt strings in non-English `unitsAbility.json` after English cleanup (archived AGENT_REFERENCE warning — revalidate if touching loc).

## Do-not-miss checklist

- [ ] Edit overrides + regenerate overlay; do not only edit an old experiment Core dump.
- [ ] Preserve design-contract metadata fields.
- [ ] Prefer Core donor reshape before Direct State.
- [ ] Refresh catalog after material ability changes if agents will browse it.
