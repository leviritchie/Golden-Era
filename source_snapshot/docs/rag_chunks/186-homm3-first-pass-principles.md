# RAG_CHUNK: olden-era-playtest/homm3-first-pass-principles

## HoMM3 AI First-Pass Design Principles

Stable note: full guidance is in `docs/homm3_ai_first_pass_design_principles.md`.

Stronghold-derived first-pass hierarchy:

1. Keep the game stable and playable.
2. Preserve recognizable HoMM3 identity where OE data supports it.
3. Use OE-native data systems before runtime hooks.
4. Make approximations explicit in data, text, and docs.
5. Defer native-heavy behavior until it can be statically traced.

Use donors for engine compatibility, not lore purity. Stronghold cloned Dungeon for faction/city/unit scaffolding and used Undead `pet_map` shells for Wolf Riders where that map shell fit better. Keep HoMM3 visual import keys in private namespaces so vanilla donor enemies do not match custom swaps.

Prefer data-only approximations until native behavior is traced. Stronghold implemented Hall of Valhalla as a hero Attack building, Mess Hall as `cityUnitsIncrement h3_goblin +8`, Resource Silo as known resource income, and left Escape Tunnel/Freelancer's Guild/Ballista Yard outside data-only scope. Visible text must describe implemented behavior, not desired HoMM3 behavior.

Preserve faction/unit shape before exact numbers. Stronghold kept Goblins fast and fragile, treated Wolf Riders as already high offence/speed, and flagged Cyclops/Behemoth for high-tier stat review. Use OE same-tier ranges as guardrails; do not use `squadValue` alone; keep stat and ability review separate.

Use Horn of the Abyss balance as the source of truth for HoMM3 stats/costs/growth when HotA has values. Fall back to vanilla Complete only when HotA has no entry, and record the fallback.

Probability-based HoMM3 or Tears of Ashan unit effects should become focus-point abilities. Examples: Thunderbird lightning, Basilisk petrify, Mighty Gorgon death stare, Sea Dog Accurate Shot, and Sea Serpent poison become deterministic focus spenders instead of hidden chance rolls.

Represent faction identity with a small number of signature choices. Stronghold used Warcries, Hall of Valhalla, Mess Hall, Resource Silo, unit-themed laws, and plausible alternate upgrades. First-pass manifests should define `identityPillars`; every placeholder law/building/hero specialty should tie back to one.

Alternate upgrades from Tears of Ashan, or AI-invented placeholder alternates, must differ from the original upgrade by at least one passive or active ability. A pure stat shuffle is not enough; every `_upg_alt` row needs an `upgradeDifferentiator`.

Use OE economy conventions, then layer HoMM3 flavor. Stronghold used HoMM3-inspired dwelling costs but kept OE upgrade dust ladder T1..T7 = 10,20,30,40,50,75,100 and capped Mage Guild to level 3.

Clone complete gameplay surfaces, not just units: squads, barracks, heroes, subclasses, map object registrations, quick-game tables, M2/M10 presets, info scripts, localization, audio, previews, icons, and release UI aliases.

Hero pass guidance: clone donor rows for stability, rename HoMM3 classes, translate unsupported specialties into OE-native equivalents, keep starting armies on custom unit SIDs, and do not duplicate global sub-skill IDs. Stronghold translated Gurnisson to an OE Heroic Strike path and removed a broken `skill_faction_homm3_stronghold` clone.

Town guidance: city JSON determines building behavior; town layers are only visuals. Do not fix building identity with localization or art swaps. Generate rough layer maps/positions, but mark every town placement as manual review.

Decision ladder: exact OE data behavior, safe OE approximation, donor-backed scaffold, static trace required, or visual placeholder. Do not jump from unknown native behavior to an untraced runtime hook.

First-pass manifest decisions should carry `decisionStatus`, `sourceBehavior`, `implementedBehavior`, `rationale`, `confidence`, `manualReviewReason`, and `staticTraceRequired`.
