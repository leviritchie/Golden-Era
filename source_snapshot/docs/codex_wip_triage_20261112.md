# Leftover Codex WIP triage (2026-11-12)

Codex was retired on 2026-11-12. The main checkout held about 8,680 dirty paths: 127 modified, 196 deleted and 8,359 untracked. Agents kept skipping them as "Codex's" or saying they were waiting on Codex. This doc records what each group is and what happened to it. The owner's guidance: most of this is probably no longer relevant, so the default is to discard it unless current code still needs it.

**Backup before any change:** `V:/olden_port_work/codex_wip_backup_20261112/` holds:
- `tracked_vs_HEAD.patch`: all tracked diffs against `9eb29e4ddd`, binary-safe.
- `untracked_non_tmp.tar`: the 122 untracked files outside `.tmp/`.
- `status_before.txt`.

`.tmp/` is not in the backup.

## Done

| Group | Size | Decision | Result |
|---|---|---|---|
| Tracked `artifacts/` files already deleted on disk (VFX experiments for storm elemental, titan, oceanid and the roster; behemoth and titan prebake sheets; 2026-09-27 takeover scratch) | 195 | Discard. Only lab tools wrote them, and nothing in the ship pipeline reads them | Deletion committed. `vfx_events/LIVE_CHECK.md` was restored, because vanilla_style unit records cite it |
| Root scratch: `*.exe.stackdump`, `nul.npy`, `shell.npy`, `dump_edges.npy`, `s1.tables/`, `_inspect_rtb.csx`, `.video-rebuild-contract-check4/` | 16 | Discard | Deleted |
| Cross-agent board todos created by Codex: 4c727ac3 (terrain runtime on the old current-version copy), 71af7e2c (move that copy from F: to V:), 02d6e276 (bug-report GitHub routing) | 3 | Obsolete. The 26615913 port and the 2026-11-11/12 bug-report rework (`c6ad8b3a37`) superseded them | Closed on the board, each with a handoff doc |

## Proposed (needs owner OK)

| Group | Size | What it is | Proposal |
|---|---|---|---|
| A. Port work already committed | 124 paths, plus `tools/release_port/apply_release_core_overlay.py` | Each file is byte-identical to branch `port/26615913`, or is exactly HEAD + port merged without conflict. Codex's 26297049 edits (the 10-29 plugin hooks, `hero_overrides`, `law_overrides`) were adopted into those port commits | Restore these paths in main to HEAD and delete the untracked copies. Nothing is lost, because the branch holds them. Main's tree then stops building a mixed Golden Era + port plugin |
| B. Stale untracked tools and docs, 09-08 to 10-21 | 85 | Beholder `sol_v1` repair experiments; town `zs_v1`/`zs_v2` recipes and pose files (superseded by the MoGe/ns2 scenes); fortress env-weld edits (reverted 10-03); scratch glb-patch key rotations; old mocap/rebind docs; per-town `pan_coverage`/`terrain_streak`/`building_depth.npz` debug caches; roc diagnostic GIFs | Delete. The backup tar keeps a copy |
| C. Stale tracked edits, 09-22 to 10-29 | 10 | `docs/homm3_necropolis_t2_town_buildings.md` (Meshy era); `tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py` + test; `tools/meshy_mcp_launcher.mjs` (Meshy lapsed); `town_bench.py`/`bench_edits.py`; `validate_town_scene3d_contract.py`; `tools/homm3_authenticity/ledger.json` (10-14 snapshot, routine disabled); `prefill_homm3_hero_overrides.py`; `game_symbols_hint_allowlist.txt` | Restore to HEAD. The backup patch keeps the diff |
| D. `.tmp/` | 8,237 files, 247 MB | 09-22 to 10-01 scratch: two ChatGPT browser profiles (contain Login Data), npm cache, the Meshy MCP tarball, town bake logs, old town scratch | Delete. It is not backed up, because it is scratch and holds browser login data |

## Left alone

- **Recent Claude edits, not Codex** (modified 2026-11-12, not on the port branch): 7 town `scene3d/*/catalog.json`, `custom_factions/contracts/homm3_bundle_payload_contract.json`, and `tools/homm3_import/faction_concepts/homm3_neutral.json` (a Troll `bandExempt` note citing port decision D3). The session that made them should commit or drop them. None of the working-tree catalogs matches any past commit of that file.
- `.claude/settings.json`: user-owned state.
- `external_repos/homm-olden-era-oldenpedia`: a dirty submodule, unrelated.
