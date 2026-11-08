# OldenAiSim committed data

These files are the offline source of truth for smoke/tests. **No Core.zip required at runtime.**

| File | Role |
|------|------|
| `olden_tile_mp.v1.json` | Core tile id → provisional `stepMp` |
| `olden_road_mp.v1.json` | Road id → provisional `discountMp` |
| `ai_world_sid_vocab.v1.json` | Core AI SID vocabulary — **reference only, not wired to beam** |
| `clipped_fixture.aisim` | Bounded import/smoke board |

## Provisional MP formula (extract only)

```
stepMp = round(100 * penalty / 0.4)
discountMp = round(100 * road.bonus)
applied cell = max(1, stepMp - discountMp) when a road overlays the cell
```

This is **not** a proven native `worldMovePoints` consumer formula. Correct when Olden path-cost accounting is proven.
