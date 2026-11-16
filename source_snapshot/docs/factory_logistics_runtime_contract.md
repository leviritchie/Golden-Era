# Factory Logistics Network: runtime contract (2026-11-16, overnight build)

Design/spec: `docs/factory_logistics_network_design.md` (authoritative for rules and numbers).
Decisions taken without the user: `V:/olden_port_work/factory_logistics/DECISIONS.md`.
Research: `V:/olden_port_work/factory_logistics/{pricing_research,feasibility}.md`.

Two lanes build in parallel against this contract. File ownership is exclusive.

## Lane CORE (gameplay, data, persistence, range engine)

Owns:
- `custom_factions/factory_logistics/logistics_config.json` - single source of truth for
  enhancements (ids, names, per-level effect values, costs, caps), resource cycle, range constants.
- `tools/release_port/homm3_factory_logistics_core_overlay.py` (+ hook-up in
  `apply_release_core_overlay.py`) - replaces Split Assembly content of
  `skill_faction_homm3_factory` (keep the skill SID; keep [0,3,3] subskills, new content), adds world
  spell `homm3_factory_logistics_network` (free, unlimited, clone of the Conflux Fusion spell row) to
  every rank, English texts.
- Plugin C#: `Homm3FactoryLogisticsConfig.cs`, `Homm3FactoryLogisticsState.cs` (model + persistence),
  `Homm3FactoryLogisticsRuntime.cs` (hooks: visit, capture, day/week start, hire cost, spell cast ->
  open viewer), `Homm3FactoryLogisticsRange.cs` (pathfinding + network solve),
  `Homm3FactoryLogisticsEffects.cs`. Retire `Homm3FactorySplitAssembly*` registration (leave files
  unless they break the build; HUD strip must not show).
- Validators: `tools/validate_factory_logistics_contract.py` (full tier).

CORE is split in two agents:
- CORE-A: everything above except `Homm3FactoryLogisticsRange.cs`.
- CORE-B: `Homm3FactoryLogisticsRange.cs` (+ `Homm3FactoryLogisticsMap.cs` map adapter): tile access,
  fog, neutral guard zones, pathfinding, route solve. Pure functions where possible, plus an offline
  test harness under `tools/factory_logistics/range_harness/` if cheap.

Range API (CORE-B implements, CORE-A calls):

```csharp
internal static class Homm3FactoryLogisticsRange {
  internal sealed class Node { public long Key; public string Kind; /* building|town|hero */ public int X, Y, Level;
    public int RangeLevels;        // logistics level (+ own Rail Network bonus) for routes starting here
    public double HubRefresh; }    // 0..1 fraction of spent range refreshed when a route passes through
  internal sealed class Route { public long From, To; public bool Reached; public List<(int x,int y)> Tiles; public int MissingMp; }
  internal sealed class Blocker { public int X, Y; public long GuardKey; public List<(long from,long to)> WouldLink; }
  internal sealed class Result { public List<Route> Routes; public List<Blocker> Blockers; }
  // For every source, best route to every target (best = reaches with fewest MP; if none reaches, the
  // closest cut route). Costs: 10 MP orthogonal, 14 diagonal (x1.41), no terrain penalty, road tiles
  // use the road discount; fog (unexplored for sideId), water/impassable, objects and neutral guard
  // zones block. Hubs refresh range as in the spec (floor of the percentage).
  internal static bool TrySolve(int sideId, IReadOnlyList<Node> sources, IReadOnlyList<Node> targets,
      int mpPerLevel, out Result result, out string fail);
  internal static bool TryGetTile(int x, int y, int level, int sideId, out byte terrain, out bool road,
      out bool water, out bool blocked, out bool fogged);
  internal static int MapWidth { get; } internal static int MapHeight { get; }
}
```

## Lane UI (panels)

Owns: `Homm3FactoryLogisticsUpgradePanel.cs`, `Homm3FactoryLogisticsViewer.cs` (+ any
`Homm3FactoryLogisticsUi*.cs`), mockup scripts under `tools/factory_logistics/`.
Visual target: the approved mockups in `V:/olden_port_work/factory_logistics/mockups/`.

## Shared API (CORE implements, UI consumes) - `Homm3FactoryLogistics` facade

```csharp
internal enum LogisticsBuildingKind { Mine, Dwelling }
internal sealed class LogisticsBuildingView {
  public long ObjectKey;            // stable per map object (native-pointer free; e.g. object id)
  public string DisplayName;        // "Crystal Mine", dwelling name
  public LogisticsBuildingKind Kind;
  public string ResourceSid;        // mines: produced resource; dwellings: null
  public string UnitSid; public int UnitTier;        // dwellings
  public int TileX, TileY, Level;   // map position (level = surface/underground)
  public int UpgradeCenterLevel;    // 0 = never visited by a skilled hero
  public bool SwitchUsedThisWeek;
  public string ActiveEnhancementId; public string PendingActiveId;   // pending applies next day
  public IReadOnlyList<LogisticsEnhancementView> Built;               // any number built
  public IReadOnlyList<LogisticsOption> Options;                     // what may be built here
  public int PowerStationBonusLevels;                                // from stations in range
}
internal sealed class LogisticsEnhancementView { public string Id; public int Level; public int PendingLevel; /* remote build in progress, 0 = none */ }
internal sealed class LogisticsOption {
  public string Id, Name; public string[] LevelLines;  // 3 short player texts
  public int BuiltLevel; public int MaxLevelNow;       // cap from hero skill (on site) or UC level (remote)
  public IReadOnlyDictionary<string,int> NextCost;     // resource sid -> amount (after Warehouse discount)
  public bool CanAfford; public string BlockReason;    // null when buildable
}
internal sealed class LogisticsRoute {
  public long FromKey; public string ToKind; public long ToKey; // "building" | "town" | "hero"
  public IReadOnlyList<(int x,int y)> Tiles;   // 8-neighbour tile path, from -> to (or to cut point)
  public bool Cut; public int MissingRangeLevels;   // >0 when cut; also MissingMp
  public int MissingMp;
}
internal sealed class LogisticsBlockingStack { public int TileX, TileY; public string Label; /* "Defeat to link A -> B" */ }
internal sealed class LogisticsNetworkView {
  public int LogisticsLevel; public int RangeMpPerLevel;  // 100
  public IReadOnlyList<LogisticsBuildingView> Buildings;
  public IReadOnlyList<(long key, string name, int x, int y)> Towns, Heroes;
  public IReadOnlyList<LogisticsRoute> Routes;
  public IReadOnlyList<LogisticsBlockingStack> BlockingStacks;
}

internal static class Homm3FactoryLogistics {
  // Visit flow: CORE raises this when a skilled hero of the local player visits an owned eligible building.
  public static event Action<object /*dataHero*/, long /*objectKey*/> VisitRequested;
  public static bool TryGetBuilding(long objectKey, object heroOrNull, out LogisticsBuildingView view, out string fail);
  public static bool TryGetNetwork(out LogisticsNetworkView view, out string fail);   // recomputed on call
  public static bool TryGetTerrainTile(int x, int y, int level, out byte terrain, out bool road, out bool water, out bool fogged);
  public static int MapWidth, MapHeight;
  // Commands. heroOrNull != null => on-site (immediate); null => remote via Upgrade Center (next day).
  public static bool TryBuild(long objectKey, string enhancementId, object heroOrNull, out string fail);  // build L1 or +1 level
  public static bool TrySetActive(long objectKey, string enhancementId, out string fail); // 1/week, next day
  public static bool TryDemolish(long objectKey, string enhancementId, out string fail);  // free, no refund
}
```

Rules CORE enforces (UI only displays): skill-level caps, Upgrade Center caps, weekly switch,
next-day activation, costs/affordability, capture wipe. UI never mutates state directly.
All failures return a reason string and log under `[FactoryLogistics]`.
