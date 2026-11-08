# Remediation Sampling-Gap Backlog (2026-09-21)

Phase 6 of the stale-docs/dead-code/code-smell remediation. Each gap below was
re-verified against current worktree/installed state and dispositioned. None is
closed by remediation edits; each names the action that would close it.

## Closed at a higher proof tier by this remediation

| Gap | Evidence | New tier |
| --- | --- | --- |
| Regenerated-mission installed payload | `validate_roe_castle_campaign_continuity_contract.py --require-installed` → contract OK (installStatus=installed); `validate_map_load_preflight_contract.py` → OK (87 map checks, 16 signatures) against the active Golden Era install | Deployed-payload proven (`AGENTS.md` updated). Runtime gameplay tier still open (see below). |

## Open: needs a deploy action (out of remediation scope)

| Gap | Verified state | Closer |
| --- | --- | --- |
| Live DLL `B44EF2FE…` source build unrecorded | On-disk `OfflineUnlockMod.dll` hashes to `B44EF2FE35DC0103311E3107607103C214ABB9920B1E23C7F82CC09FAC2B0CEB`, matching the `offlineunlockmod_dll_provenance.md` coverage note; no provenance row covers it | Rebuild from a recorded source commit and deploy, then append the provenance row |

## Open: needs design content (out of remediation scope)

| Gap | Verified state | Closer |
| --- | --- | --- |
| 26 missing bulwark/factory law targets | `custom_law_targets.json` holds 130 targets across 10 factions × 13; zero bulwark/factory entries. No bulwark/factory laws exist in-repo either (`current_custom_law_readable_descriptions.csv` covers the same 10 factions; faction files point at game-relative `DB/fractions_laws/` tables) | Author the 26 laws (names, mechanics, ranks), then add target entries |

## Open: needs in-game proof (out of remediation scope)

| Gap | Verified state | Closer |
| --- | --- | --- |
| 4K runtime behavior | Static scale-shape gates pass (`validate_homm3_ui_scale_contract.py`); no high-DPI runtime record exists | In-game pass at 4K checking the gated UIs |
| Campaign runtime gameplay | Installed payload proven (above); hero transfer, strongest-N carry, difficulty scaling, video presentation, interaction dispatch, water travel, and underground traversal have no runtime record | Focused runtime record per `AGENTS.md` proof boundaries |

## Residual risk: sampling-based scope research

The remediation's scope research spot-checked marker/validator/doc populations
rather than exhausting them. Mitigations now in place: the audit allowlist in
`tools/audit_obfuscated_symbols.py` pins the triaged surface, `tools/verify_patch_surfaces.py`
scopes generated-code overlap, and the Phase 2 gate-wiring commit keeps
validators runnable. A future pass should re-sample `STALE_`/`FIXME` markers
and the unwired-validator list rather than assuming they stayed clean.
