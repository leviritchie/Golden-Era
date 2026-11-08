# HoMM3 Underground And Ocean Travel Mechanics Research

Date: 2026-06-17

Scope: Restoration of Erathia, Armageddon's Blade, and Shadow of Death adventure-map travel mechanics relevant to translating campaign maps into Olden Era. This intentionally ignores creature/town combat balance, except where towns and objects create or modify travel state.

This is research and implementation planning, not a validated Olden Era runtime implementation.

## Summary

HoMM3 has two different travel axes that should not be collapsed into one system:

- Underground travel is a physical map-layer problem. A map can have a surface and an underground map, both with their own tiles, objects, fog/reveal state, and visit triggers. Travel between them happens through Subterranean Gates, not by treating one layer as a visual skin over another.
- Ocean travel is a movement-mode and vehicle problem on a physical map layer. Water tiles exist on the same surface/underground coordinate layer as land tiles, but land heroes generally need a persistent boat entity to traverse them. Boarding, disembarking, shipyards, Summon Boat, Scuttle Boat, whirlpools, water objects, and sea movement modifiers all depend on that boat state.

For campaign translation, the importer should preserve both axes explicitly:

```text
physical coordinate = (x, y, z)        // z = surface or underground
travel state        = land | inBoat | waterWalk | later: fly/dimension-door
entity state        = hero, boat, town/object, event, fog, ownership
```

VCMI's architecture is a useful reference here: it stores map layer identity in map headers and `int3` map positions, while its pathfinder has separate movement layers such as `LAND`, `SAIL`, and `WATER`. That distinction maps cleanly onto the Olden problem.

## Source Baseline

Primary/local source:

- `HoMM 3 Complete/Heroes3_Manual.pdf`, New World Computing/3DO player manual. Relevant extracted sections: Adventure Map overview, Movement Allowance, Terrain Movement Costs, Boats, Subterranean Level, movement cursors, Navigation, Ship-to-Ship Combat, Summon Boat, Scuttle Boat, Water Walk, Shipyard, Lighthouse.
- `HoMM 3 Complete/Heroes3_AB_Manual.pdf`, Armageddon's Blade manual. Relevant extracted sections: random map option for one- and two-level maps, map editor/campaign editor notes, revisiting adventure-map objects with Space Bar.
- `HoMM 3 Complete/Heroes3_SoD_Manual.pdf`, Shadow of Death manual. Relevant extracted sections: campaign/map editor notes and Space Bar revisit behavior.

Online mechanics sources reviewed:

- Heroes 3 wiki: [Subterranean Gate](https://heroes.thelazy.net/index.php/Subterranean_Gate), [Boat](https://heroes.thelazy.net/index.php/Boat), [Shipyard](https://heroes.thelazy.net/index.php/Shipyard), [Lighthouse](https://heroes.thelazy.net/index.php/Lighthouse), [Navigation](https://heroes.thelazy.net/index.php/Navigation), [Summon Boat](https://heroes.thelazy.net/index.php/Summon_Boat), [Scuttle Boat](https://heroes.thelazy.net/index.php/Scuttle_Boat), [Water Walk](https://heroes.thelazy.net/index.php/Water_Walk), [Whirlpool](https://heroes.thelazy.net/index.php/Whirlpool), [Sea Captain's Hat](https://heroes.thelazy.net/index.php/Sea_Captain%27s_Hat), [Admiral's Hat](https://heroes.thelazy.net/index.php/Admiral%27s_Hat).
- VCMI source/docs at commit `2689c674e3499c63628f376ef1f828926708cfe3`: [CMapHeader.h](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/mapping/CMapHeader.h), [MapFormatH3M.cpp](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/mapping/MapFormatH3M.cpp), [CMap.h](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/mapping/CMap.h), [TerrainTile.h](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/mapping/TerrainTile.h), [CGPathNode.cpp](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/pathfinder/CGPathNode.cpp), [CPathfinder.cpp](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/pathfinder/CPathfinder.cpp), [PathfindingRules.cpp](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/pathfinder/PathfindingRules.cpp), [SummonBoatEffect.cpp](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/lib/spells/adventure/SummonBoatEffect.cpp), [Map Object Format](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/docs/modders/Map_Object_Format.md), [Boat object docs](https://github.com/vcmi/vcmi/blob/2689c674e3499c63628f376ef1f828926708cfe3/docs/modders/Map_Objects/Boat.md).

## Underground Travel

### Player-Facing Mechanics

Some HoMM3 maps contain a subterranean level. The player manual describes the underground as its own map; the surface and underground are switched with the elevation toggle, and each is revealed as heroes explore it.

Subterranean Gates are the normal transition objects between these two maps. They are adventure-map locations that move a hero between surface and underground. The current Heroes 3 wiki documents an important pairing rule: at map start, each gate is paired with the other layer's nearest gate to the corresponding point; ties choose northmost, then westmost. This means a converter must not assume same `(x, y)` coordinates. If a gate cannot be paired because the other level has no matching gate count, visiting it shows a blocked-tunnel message instead of changing layers.

Subterranean Gates are land objects; the wiki notes they cannot be placed on water. In AB/SoD, if a hero is already standing on the gate trigger, Space Bar can repeat the object action and move between layers without spending movement points. Movement to reach the gate still follows normal land movement/pathfinding rules.

### Data Implications

The map model needs true layer-qualified coordinates:

```text
Surface tile:      (x, y, z=0)
Underground tile:  (x, y, z=1)
```

Every terrain tile, road, river, object, guard, event trigger, owner, and fog/reveal bit must be keyed by this coordinate. Treating underground as a swapped visual overlay would break campaign maps because both layers can contain simultaneous state: towns, heroes, guards, resources, timed events, cleared objects, and fog.

VCMI backs this shape: `CMapHeader` has `mapLayers` and legacy two-level maps become `{SURFACE, UNDERGROUND}`; object and condition positions use `int3`; `CMap` APIs operate on `int3` tiles. This is an implementation reference, not proof of original binary layout, but it matches the HoMM3 manual's player model and supports an importer design.

### Implementation Path

Importer:

- Read or produce an intermediate map model with `LayerId.Surface` and optional `LayerId.Underground`.
- Import all tiles and objects into layer-qualified coordinates.
- Build Subterranean Gate pairing after all gates are loaded, using the HoMM3 nearest-corresponding-point rule. Store unpaired gates as blocked visitable objects with the original blocked-tunnel message.
- Key map events, object visit state, fog, and quest targets by `(x, y, z)`, never just `(x, y)`.

Runtime/simulation:

- Add a layer controller that makes one physical layer visible/interactive at a time while keeping all layer state alive.
- Gate visit action changes the hero coordinate's `z` and active visible layer. It should not destroy or regenerate the hidden layer.
- Elevation toggle is a presentation command; it changes the viewed layer, not the simulation layer contents.

Pathfinding:

- Surface and underground land movement are normal land graphs.
- Subterranean Gates are explicit teleport edges between two gate nodes.
- The pathfinder should not add arbitrary same-`x,y` transitions between layers.

## Ocean Travel

### Player-Facing Mechanics

Heroes need boats to move on water. The manual lists these boat sources:

- built in shoreline towns with shipyards;
- built at adventure-map shipyards;
- created or moved by Summon Boat;
- found already placed on the adventure map.

A boat carries one hero and army at a time. Boarding is done by moving a land hero onto an unoccupied boat. Disembarking requires a valid shore location. The manual states that boarding or disembarking takes the remainder of the hero's movement allowance for the current day; Admiral's Hat removes that penalty and converts movement between land and water pools.

Boat movement uses water movement rules, not normal land terrain rules. The manual says Navigation increases boat movement by 50%, 100%, and 150% at Basic, Advanced, and Expert. The Heroes 3 wiki and VCMI model this as a separate sea movement pool/layer. Lighthouses add water movement and stack cumulatively; Navigation is applied independently before Lighthouse bonuses in the wiki's breakdown.

Heroes in boats can interact with water objects: flotsam, sea chests, shipwreck survivors, shipwreck/derelict-ship banks, mermaids, buoys, sirens, whirlpools, ocean bottles, and water variants of some regular objects in expansions/mods. Ship-to-ship combat is a distinct battle presentation when one boat attacks another.

### Boat Entity Semantics

For translation, a boat is not just a boolean on a hero. It is a persistent map entity with at least:

```text
Boat {
  id
  coord: (x, y, z)
  owner/affiliation or neutral status
  occupantHeroId: optional
  source/type/appearance
  movementLayer = sail
}
```

When a hero boards, the hero becomes associated with the boat and moves in sailing mode. When the hero disembarks, the boat remains on water. If the hero is defeated while in a boat, the wiki documents that the boat disappears.

Shipyards are object/building producers. They spend 1000 gold and 10 wood to create a boat, but only if the relevant water active tile is clear. The wiki documents priority/active-tile behavior, which is important for exact tactics but can be a second-pass fidelity target after basic boat creation works.

### Summon And Scuttle Boat

Summon Boat is a Water Magic adventure spell. The manual and wiki agree on the major behavior:

- Basic: attempts to summon an existing unoccupied boat; 50% success.
- Advanced: can create a new boat if no boat is available; 75% success.
- Expert: same as Advanced, 100% success.
- There is a 64-boat adventure-map limit.

The wiki adds important ownership and placement details: the spell must be cast next to shoreline; it needs an unoccupied summon tile; Basic cannot summon enemy/allied boats; neutral or own free boats are candidates; if multiple summon tiles exist, priority rules choose the placement. VCMI's `SummonBoatEffect` models this as a spell effect that rejects casting while already in a boat, finds the hero's best summon location, optionally moves the nearest unoccupied sailing boat, or creates a new one if allowed.

Scuttle Boat destroys an unoccupied boat with 50%, 75%, or guaranteed success by spell mastery. It cannot destroy occupied boats. AI casting is noted as absent on the wiki; campaign conversion probably only needs player-side semantics at first.

### Whirlpools

Whirlpools are water-only travel objects entered by a hero in a boat. They teleport the hero and boat to another whirlpool. The wiki notes version differences: Shadow of Death behavior is random destination selection, while HotA has fixed ordering. For original campaigns, treat random destination as the safer default unless the source map is known HotA.

Whirlpool entry also causes army loss: 50% rounded up of the weakest stack by total fight value is removed, unless protected by Sea Captain's Hat or Admiral's Hat. This is army mechanics, but the map-porting implementation still needs a trigger hook for it because whirlpools are map transitions with side effects.

VCMI pathfinding treats whirlpools through the teleport machinery and special-cases whirlpool blocked/exit tiles. That reinforces modeling whirlpools as teleport objects, not as special water terrain.

### Adjacent Water Travel Mechanics

Water Walk is not boat travel, but campaigns can rely on it for ocean barriers. The spell lets a hero trace a water path only if the endpoint is an unoccupied land location. Its movement penalty is 40%, 20%, or 0% by mastery. This suggests a separate `WaterWalk` movement mode that can cross water without creating or occupying a boat and cannot normally visit water objects as a boat can.

Fly and Dimension Door are out of this document's scope, but they will eventually need the same graph discipline: they are movement modes/teleport edges, not terrain conversions.

## Implementation Architecture For Olden Era

### Core Model

Use one canonical model for imported HoMM3 map state:

```text
H3Coord              = x, y, z
PhysicalLayer        = surface | underground
TravelMode           = land | sail | waterWalk | future modes
Tile                 = terrain, road, river, static block flags, object ids
MapObject            = object id, type, coord, footprint/mask, visit rules, state
BoatEntity           = map object + occupant/owner/movement layer
TransitionEdge       = source coord/object, destination coord/object, kind, cost/side effects
VisitEvent           = trigger coord/object, allowed travel modes, conditions, effects
FogState             = player, coord, visible/revealed
```

The same object can contribute several graph facts. Example: a Subterranean Gate is a land-visitable object plus a transition edge; a Whirlpool is a sail-visitable object plus a transition edge plus an army-loss side effect.

### Pathfinding Graph

Build pathfinding over nodes like:

```text
(x, y, z, travelMode, optionalBoatId)
```

Edges:

- normal land tile movement;
- normal sailing movement over water;
- `board`: land hero -> boat/sail mode, only onto an unoccupied boat from valid adjacency;
- `disembark`: boat/sail mode -> land mode, only onto valid shore;
- `subterraneanGate`: land mode `(x,y,z)` -> land mode paired gate `(x2,y2,z2)`;
- `whirlpool`: sail mode at whirlpool -> sail mode at selected destination whirlpool, with side effect;
- `waterWalk`: land hero with active effect crosses water to a valid land endpoint;
- object visit edges gated by allowed mode.

Do not use a silent fallback where water becomes land, underground becomes an alternate texture, or missing gates become same-coordinate portals. That would make campaign faults hard to trace.

### Event Triggering

Trigger checks should include both physical layer and travel mode:

```text
TriggerKey = (objectId or coord, z, travelMode, player, heroId)
```

Examples:

- a land event at `(10, 20, surface)` should not fire for a boat passing water at `(10, 20, surface)`;
- a water object should require `sail` mode unless it is explicitly a coast-visitable object;
- a Subterranean Gate should require land mode on the gate's visit tile;
- a Whirlpool should require sail mode and should move both hero and boat.

### Presentation In Olden Era

Given the current finding that Olden Era does not implement true map layering yet, a native-friendly first implementation should still keep both layers alive in our own model:

- Maintain all imported layers and boat entities in mod-owned state.
- Present one active physical layer at a time.
- Hide/cull inactive-layer visuals instead of deleting or swapping state.
- Keep object/event/fog state keyed by layer so toggling or gate travel reveals the existing state.

This is weaker than native engine support but stronger than a swap-based proof because it preserves simultaneous layer state and gives us one path to migrate into future native layer support.

### Minimal Playable Milestones

1. Data-only import:
   - import surface/underground tile/object/event coordinates;
   - import water tiles and boat objects;
   - emit validation errors for unpaired gates, unsupported water objects, or events missing layer keys.

2. Headless graph validation:
   - prove gate pair graph;
   - prove land/water separation;
   - prove board/disembark reachability;
   - prove event trigger mode/layer gating.

3. Runtime underground proof:
   - active layer view toggle;
   - Subterranean Gate visit changes hero layer;
   - both layers keep independent object/fog/event state.

4. Runtime ocean proof:
   - place an empty boat;
   - board, sail, disembark;
   - preserve boat entity after disembark;
   - gate water-object visits by sail mode.

5. Travel-object proof:
   - adventure shipyard creates a boat on a valid water tile;
   - Summon Boat moves or creates a boat under explicit rules;
   - Whirlpool teleports hero and boat with side-effect hook;
   - Scuttle Boat removes only unoccupied boats.

## Risks And Open Questions

- Exact H3M extraction still needs a dedicated importer audit against actual campaign maps. VCMI gives strong shape evidence, but our converter should prove actual source-map layer/object coordinates from the original files.
- Gate travel cost should be runtime-tested in original HoMM3 if exact movement-point parity matters. Current safe model: moving to the gate costs normal movement; AB/SoD Space Bar repeat on the gate trigger costs no additional movement.
- Shipyard active-tile priority and summon-placement priority are second-pass fidelity requirements. Basic campaign playability can start with valid clear adjacent water placement, but exact tactics need priority matching.
- Whirlpool destination behavior must branch by source format/version if HotA maps are ever imported; original SoD behavior should be treated as random destination selection.
- Boat ownership has tactical edge cases: neutral placed boats, own boats, allied boats, enemy boats, defeated-player boats, and shipyard-created boats. Summon Boat depends on these distinctions.
- Water Walk, Fly, Town Portal, Dimension Door, and monoliths are adjacent map-translation systems. Ocean and underground should be implemented as graph primitives that these can reuse.
- Olden Era native AI/pathfinding will not automatically understand our custom graph. Human-playable proof can come first, but campaign parity eventually requires AI route planning across gates and boats.

## Practical Recommendation

Build our own layer-aware and travel-mode-aware campaign map substrate now. The existing Olden layer scaffolding is too weak to carry HoMM3 campaign semantics by itself, but the model should be shaped so it can hand off to native layers later.

The root design should be explicit, fail-closed, and inspectable:

- no same-coordinate gate assumptions;
- no water-as-land fallback;
- no deleting inactive underground state;
- no treating a boat as only a hero flag;
- no unqualified `(x,y)` event keys.

The first complete slice should be a tiny imported test map with surface, underground, one paired gate, a small lake, one boat, one shore disembark point, and one water visit object. That slice exercises the two required axes without pulling in full campaign object coverage.
