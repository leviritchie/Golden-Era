# Surface: Faction laws (native-data vs hard-law runtime)

## Intent

Implement or revise faction law tree effects for HoMM3 custom factions without reviving disabled speculative mutators.

## Ownership preference

1. **Default product:** native Core law bonus primitives (`unitStat`, `heroStat`, `sideRes`, `cityUnitsIncrement`, `battleSubskillBonus`, construction/astrology primitives, …) via `custom_factions/law_overrides/` + overlay.
2. **Hook-required** designs stay behind `Homm3CustomLawPacketGate` / packet proofs until promoted.
3. Castle Elite Strategem is **not** a custom-law row — separate faction-skill / spellbook path.

## Touch points

| Kind | Path |
| --- | --- |
| Overrides | `custom_factions/law_overrides/` |
| Status table | `docs/custom_law_implementation_status.md` |
| Completion classification | `custom_factions/custom_law_runtime_completion_classification.json` |
| Packet proofs | `custom_factions/custom_law_packet_proofs.json` |
| No-compromise / planner validators | `tools/release_port/check_custom_law_no_compromise_static.py`, effect planner coverage |
| Editor | ability editor law sidebar (`docs/ability_editor_agent_notes.md`) |
| Vanilla uniqueness audit | `docs/mechanics_audit/olden_era_vanilla_faction_law_uniqueness.md` |

## Can / cannot

**Can:** ship native-data replacements widely (June 21 classification: mass `native-data-implemented`).

**Cannot:** enable speculative runtime paths “because the CSV mentions them”; cannot treat old mechanics_reference `tmp/inferno_gating_rework/Core.zip` as current install without re-readback.

## Pitfalls

- Faction-locked donor laws (heroStat with faction id, battleSubskill to faction subskills) must be redesigned.
- Law icons may be unit SIDs (`h3_pikeman`) — keep portrait index searchable.

## Open unknowns

Which remaining hook-required laws can be rewritten as native-data without identity loss; packet promotion queue.

## Proof

Native-data rows: `generated`/`deployed` after overlay. Runtime hooks: unpromoted unless packet says otherwise.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
