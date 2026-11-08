# Griffin Cliff Event And Victory Contract

Date: 2026-07-14

## Scope

This record covers Long Live the Queen mission 3 (`griffin_cliff`) only:

- three HoMM3 map events;
- the `TAKEDWELLINGS` objective for seven Griffin Towers.

## Root Causes

The translated map treated HoMM3 events as visible, interactable question-mark
objects. Both the custom clone and the stock question-mark object proved inert
in gameplay. Direct inspection of shipped Story maps found the actual native
pattern: invisible entries in the map's `markers` array, with type-1
`propMarkers` and `propActionsBefore` rows. Griffin Cliff now uses that shape
for its unguarded avalanche event. Its two guarded ambushes are physical
`random-squad` objects, because combat—not a separate visit marker—is their
trigger. This is shared semantic generation, not a post-generation Griffin map
edit: unguarded decoded events become invisible zones, guarded decoded events
become squads, and generation may bind an event to an existing real
interactable when that relationship is explicit.

The victory translator previously retained only the objective text. It emitted
no entity bindings or ownership-count triggers for HoMM3 `TAKEDWELLINGS`.

## Implemented Contract

- The unguarded decoded map event must emit as one invisible `Zone 1x1` marker;
  visible question-mark event objects are forbidden.
- Both guarded decoded map events must emit as `random-squad` objects.
- Unguarded event visitation and deletion follow decoded
  `removeAfterVisit`; no cleanup is invented when the source value is false.
- Guarded events bind their translated aggressive squad, show message via
  interrupting `propActionsBefore` Dialog, and grant resources from `SquadKill`.
  QuestScript `SquadInteraction` must not own Dialog (cannot pause combat init).
- Exactly seven decoded creature-generator records identified by the profile
  become deterministic dwelling entities.
- Each dwelling has one repeatable `ObjectCaptureEntity` increment and one
  repeatable `ObjectLose` decrement.
- One non-repeating counter condition at seven executes `GameVictory`.
- `DefeatAllEnemiesEnabled` is false because the source campaign mission does
  not allow normal victory.

## Evidence And Proof Boundary

- Native/static evidence: shipped Story-map type-1 invisible marker event shape
  and existing event-driven `TAKEMINES` ownership vocabulary.
- Source/static validated: all seven profile targets resolve to decoded
  `external_dwelling` / `creature_generator` records.
- Generated artifact validated: event host identities, event actions, seven
  dwelling bindings, fourteen ownership triggers, one count-seven victory
  path, and disabled normal victory.
- Installed payload proven: the installed Story map is byte-identical to the
  generated map and passes Griffin Cliff map-load preflight.
- Campaign-wide installed preflight: all seven Good1/Good2 maps and the merged
  Core payload pass after deterministic regeneration and installation.
- Runtime gameplay: the user confirmed victory fires after all seven towers are
  flagged. The earlier visible question-mark event hosts did not fire; that
  failure led to the native invisible-marker correction documented above.
  Execution of the newly installed invisible avalanche marker and both guarded
  ambushes (propActionsBefore Dialog then combat, SquadKill gold) still requires
  a focused play session. As of 2026-07-23 the map is also installable as a
  lobby custom map via `tools/install_griffin_cliff_custom_map.py`
  (`maps_root_custom_only`; removes any Story_maps duplicate of the same SID).

## Start-hero primary fix (2026-07-24, revised 2026-07-29)

Griffin Cliff (and other campaign-granted / `mainTown.generateHero` starts)
have no map hero. An earlier path synthesized a 3x3 `hero-spawner` and later
pinned it on the town GATE; that put the hero body into the town billboard
(`bodyOverlap`). Emit now binds the grant town as the human City propSpawn
with `spawnHero` and `propHeroes` on that city id (brine_bell / vanilla_stock
shape), and fail-closes if that city primary is missing or not HUMAN / wrong
`heroSid`. Same-side placeholders still must not steal the primary via
`min(hero_ids)`.

The earlier Good2 failures were stale-artifact failures: Steadwick still
contained Meta `random-res` objects and the old payload lacked generated town
construction presets. Full regeneration replaced the random resources with
concrete pickups, generated the presets, and cleared both installed preflight
failures.
