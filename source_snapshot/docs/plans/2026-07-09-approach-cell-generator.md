# Approach-cell alternative generator

Status: parallel pipeline scaffolded; generated-artifact + validator are the ship gate; runtime/playtest user-gated before any default install cutover.

Proof boundary: source/static → generated artifact → approach_cell validator; gameplay unvalidated.

## Decisions

- Parallel SID `h3_roe_castle_homecoming_approach_cell` beside comparison `h3_roe_castle_homecoming_layered_atlas`.
- New spine under `experiments/campaign_port_poc/approach_cell/` — copy leaf helpers; do **not** import/call `functional_points.py`, `footprint_alignment.py`, or layered-atlas/batch orchestrators.
- Domain tags + choke edges only (land / water-boat / layers). Water travel and subterranean gates are chokepoints, not open terrain/connectivity.
- Local single-approach-cell clears (O(K·R)); algorithmic ban on map-wide corridor BFS clears.
- Copies proven land-on GATE overlays. Zone atlas intentionally skipped land-on after failed playtest — do not unify by deleting land-on without a playtest decision.
- Omits HoMM3 signs/signposts (no `fx_quest_mark_*` substitution).
- Default `DeployHomm3ScenarioPayloads` stays on layered atlas until playtest wins.

## Pass order

`emit → omit signs → block_parity → local_1c → accessibility_repair → catalogue diagnostic → assemble`

Must-fight soft-bypass sealing (`seal_soft_corridors_no_pack_relocate` / `seal_soft_bypass`) is retired. Hard-block gaps get visible `mountain_green_small_1` parity pads; accessibility repair then opens min-cost soft paths with packs treated as walkable (clears parity pads/scenery only). The must-fight catalogue remains a diagnostic artifact only.

## Generate / validate / install (opt-in)

```bash
python experiments/campaign_port_poc/approach_cell/build_homecoming_approach_cell_map.py
python tools/validate_homecoming_approach_cell_map_contract.py --repo-root . --skip-generate
python tools/install_homecoming_approach_cell_map.py --repo-root .
```

## Playtest focus

- Load SID `h3_roe_castle_homecoming_approach_cell` (not the layered comparison map)
- Confirm no floating sign quest marks
- Towns/dwellings approachable without mountain skip-holes
- Water remains a boat/shore choke; subterranean only via gates
