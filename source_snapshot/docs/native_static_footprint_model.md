# Native Static Footprint Model

Status: the native projection model and the permanent-building semantic split are source/static validated against current ObjectConfig data and the
current `bvf` disassembly. Raw-translation object-cell diagnostics and the native gate-ring anchor branch now use that split. No generated map, installed payload,
or runtime asset was regenerated or changed by this work.

## Model layers

The audit keeps four layers separate:

1. Native `ObjectConfig.nodes`: value `1` is an occupied cell and value `2` is
   a gate cell.
2. The current emitter projection: the legacy anchor-plus-local-cell formula
   used by raw translation today.
3. `generatorConfig` building rectangle: a static candidate for the building
   body, not yet promoted to a runtime path blocker.
4. Presentation and interaction transforms: `offsetX`, `offsetZ`, and
   `pathLineStopRadius`, whose cell-level semantics are not proven.

For an anchor `(anchorX, anchorY)` and a native grid cell `(localX, localZ)`:

```text
unmirrored X = anchorX - pivotX + localX
unmirrored Y = anchorY + pivotZ - localZ
mirrored   X = anchorX + flippedOffset - sizeX + pivotX + localX
mirrored   Y = anchorY + pivotZ - localZ
```

The audit derives the map width and height from each mission's side-by-side
layer atlas. It does not assume every raw-translation mission is 160x80.

## Current evidence

- The native model contract passes for the stables case, an unmirrored pivot
  case, and unknown rotation handling.
- All 87 available raw-translation missions have a recognized atlas envelope.
- The audit modeled 11,912 building placements and 84,258 Environment-tagged
  scenery placements with native node grids. Resources and armies are not in
  this blocker audit.
- Native-versus-current projection differences occur in 9,321 building
  placements and 2,109 scenery placements. These are diagnostic deltas, not a
  claim that every delta is a player-visible failure.
- Native-only road intersections are present in 604 building instances and
  261 scenery instances across the audited missions.
- In Bashing Skulls, stables object `1364` is anchored at node `1965` (`[45,12]`)
  with rotation `10`. The native projection occupies nodes
  `1805,1806,1965,1966`; the current emitter projection records
  `2125,2126,2285,2286`. The source road projects through `1805,1806`, and
  the user-visible runtime result confirms that the building blocks the
  northwest road tile `[45,11]`.

The primary static evidence is in:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/out_isil_current_full/IsilDump/Hex/bvf.txt`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/out_isil_current_full/IsilDump/Hex/bku.txt`

The generated reports are:

- `artifacts/diagnostics/native_footprint_model_audit.json`
- `artifacts/diagnostics/native_static_footprint_audit.json`
- `artifacts/diagnostics/native_footprint_road_intersections.json`

## Production promotion boundary

The semantic split is source/static validated. Permanent `Interact` generator
objects use native pivot-aware node projection in the emitter; `Environment`
scenery remains in the isolated compatibility pass; `Resource`,
`Artifact`, `meta`, and `Army` rows retain the pickup/enemy convention. The
watchtower regression proves the corrected candidate for the 160x80
side-by-side atlas, and stables remains covered by the native projection case.

The emitter now fails closed when native cell geometry would be guessed: missing
or invalid native grids and unknown rotations are reported as errors. Missing
integer `pivotX`, `pivotZ`, or mirrored `flippedOffset` fields are recorded as
native zero defaults, because the native `ObjectConfig` constructor does not
assign those fields. Generator rectangles and presentation offsets stay
audit-only because the current bvf path query reads ObjectConfig nodes. The
opt-in compatibility pass clips cells outside the active H3 layer envelope; a
permanent building must still retain an in-envelope native GATE or the pass
fails closed.

This is a production-path behavior change: raw-translation maps that contain
affected permanent objects must be regenerated and reinstalled before their
payload can be considered current. No map regeneration, installation, startup
smoke, or runtime gameplay proof was performed in this iteration.
