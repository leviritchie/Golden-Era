# HoMM3 Footprint Compatibility Postpass

This is an isolated candidate-only repair step for the raw translation lane. It
does not change normal object placement rules and it does not run for ordinary
generation unless explicitly enabled.

The insertion point is after raw object, gate, Landon-access, and spawn cleanup
and before `visual_scenery_canon_postpass`. The postpass compares each emitted
building's native `ObjectConfig.nodes == 1` cells with the source HoMM3
non-visitable block-mask cells. HoMM3 land-on (visit-mask) cells are wildcards:
each check may treat them as closed or open, whichever is more permissive
(closed for overhang/dig-in expectations; open for hard-blocker preservation).
Contacts are compared within the same atlas
layer; atlas padding is not a blocker relationship between layers. A building may dig into existing scenery: an overlap is allowed when the scenery already supplies the same permanent blocker cell. Overlaps with another building or a synthetic H3 seal remain unsafe. Native building cells clipped outside the active map are allowed only when the in-envelope native GATE remains available. Source scenery cells projected outside the active map are treated as clipped absent cells; only in-map source cells participate in blocker parity. Other malformed or untrusted HoMM3 footprints are reported as unresolved rather than guessed. Actionable adjacency is limited to the outer face of newly emitted Olden blockers: if a building grows one cell east of the HoMM3 footprint, only a blocker immediately east of that new cell counts (same for west/north/south). Side or inner touches of an overhang are ignored. A neighbor that already touched the building in HoMM3 is not treated as a newly adjacent object when that contact merely shifts. It does not compare roads, a whole-map blocker union, or a route search. Source scenery contacts on that outer face are still reported; only newly emitted scenery is eligible for the first deletion step. An isolated native footprint mismatch with no actionable outer-face contact is diagnostic-only and leaves object placement unchanged.
Resources, artifacts, armies, animals, and other non-permanent interaction rows
are not blockers.

For each mismatched building with an extra Olden cardinal contact, the ordered
policy is:

1. Remove newly generated scenery that causes the contact.
2. If that does not resolve the contact, try a deterministic cardinal reposition of
   up to two tiles. Prefer shorter steps and fewer scenery culls when several
   candidates clear the contact. The building may dig into existing scenery when
   that scenery already blocks the cell; reject unsafe object overlaps and newly
   uncovered Olden-only blocker cells (HoMM3 land-on cells count as expected
   occupancy here). Reject a move that would open an H3 hard-blocked cell formerly
   occupied by the building unless another permanent blocker or the target
   footprint still occupies it; opening a land-on cell is allowed.
3. If a move is blocked only by removable adjacent scenery, remove every scenery
   object required to clear that candidate (any count) and make the reposition.
   Prefer the candidate that needs the fewest culls. Source scenery is removable
   when each H3 blocker cell in its Olden footprint remains covered by another
   permanent blocker; the target building cells count as preserved occupancy.
4. If no safe choice exists, leave that building unresolved (fail-open): commit
   every successful repair and report leftovers without aborting map emit.

All object and property edits happen on a deep candidate copy. By default the
pass is fail-open: successful repairs are committed even when some buildings
remain unresolved, and those leftovers are reported without aborting map emit.
Optional ``raise_on_failure=True`` restores the legacy fail-closed transaction
that refuses to commit when any building is unresolved.

The single-map builder exposes
`--enable-homm3-footprint-compatibility`; the campaign batch builder exposes the
same opt-in. The default remains disabled. The batch input stamp includes both
the module and the enabled/disabled policy, so an opt-in run cannot reuse a
stamp from a different mode.

Validation:

`tools/validate_homm3_footprint_compatibility_contract.py` runs source/static checks and in-memory fixtures for scenery-first deletion, source-scenery contact comparison, protected scenery movement, building overlap with existing scenery, rejection of uncovered Olden-only cells during a move, up-to-two-tile reposition, multi-scenery cleanup supporting a reposition, HoMM3 land-on wildcard permissiveness, fail-open commit with unresolved leftovers, excluded pickup/enemy rows, diagnostic-only isolated mismatches, functional mine clone exclusion, actionable candidate rejection diagnostics, and optional fail-closed transaction behavior.

Proof boundary: the module and fixtures are source/static validated. Default
emit is fail-open (`applied_with_unresolved` when leftovers remain). No runtime
gameplay claim is made by this postpass alone.
