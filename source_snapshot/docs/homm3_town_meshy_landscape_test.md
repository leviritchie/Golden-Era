# Town full-3D: Meshy T2 on the whole landscape backdrop (test, 2026-09-29): negative

**Proof tier:** generated artifact / offline moderngl render. Nothing was staged, bundled or installed.

## Question

Can a Meshy T2 image-to-3D model at a generous triangle budget build the landscape itself, with real hidden volume
behind the ridges, instead of the depth-displaced painting?

## Run

The runner is `artifacts/meshy_town_scene_meshes/homm3_factory/landscape_test/run.py` (artifacts only). Settings:
`meshy-t2`, `smart-topology`, textured, `target_polycount` 15000 (the T2 maximum, since 25000 is refused with HTTP 400
and not billed). The run cost 30 credits, logged to the Factory ledger.

| Input | Faces | Result |
|---|---|---|
| `full`: Factory's building-free backdrop (`Factory-in-background.png`), 1600 wide | 14 074 | a walled village yard |
| `arch`: the right-half crop (arch and mesa), 1024 wide | 14 141 | two blocky mesas on a slab |

Sheet: `artifacts/claude_takeover_20260927/review/factory_landscape_meshy_test.png` (input, front, top, both
obliques and high view per mesh).

## Verdict

Meshy treats any image as **one object on a turntable**. It never reconstructs a vista.

- **`full`.** The canyon is gone. The background houses became the subject: a rectangular walled compound of huts and
  cacti on a flat sand slab, about 16:1 wide to tall. None of the painting's mesas, ledges or distance survive.
- **`arch`.** Closer in spirit, since it has real rock volume with backs and sides, but the arch itself (the
  crop's main feature) is missing. The mesas are generic stepped blocks on a small diorama base with no depth range.
- **Registration.** Neither mesh has the painting's perspective (near ground large, far mesas small), so it cannot be
  registered to the game camera. Projecting the painting onto it would not line up at rest.

The route is closed for vista backdrops. Meshy stays useful for **discrete masses**: a single mesa, spur or arch cut
out of the painting and fitted like a building. That is the form to try if the hidden-volume problem is revisited.
The layered fill plus mirror closure (`docs/homm3_town_mirror_closure.md`) remains the terrain baseline.
