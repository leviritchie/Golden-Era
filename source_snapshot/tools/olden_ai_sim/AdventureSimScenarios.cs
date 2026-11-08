using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>Built-in offline scenarios for GUI and tests (no game required).</summary>
	public static class AdventureSimScenarios
	{
		public static IReadOnlyList<string> Names { get; } = new[]
		{
			"frontier_hold",
			"choke_point",
			"swamp_detour",
			"two_hero_split",
			"rich_pickup_vs_guard",
			"empty_board",
			"portal_hop",
			"mine_income",
		};

		public static AdventureSimState Create(string name)
		{
			switch ((name ?? "").Trim().ToLowerInvariant())
			{
				case "frontier_hold":
					return FrontierHold();
				case "swamp_detour":
					return SwampDetour();
				case "two_hero_split":
					return TwoHeroSplit();
				case "rich_pickup_vs_guard":
					return RichPickupVsGuard();
				case "empty_board":
					return EmptyBoard();
				case "portal_hop":
					return PortalHop();
				case "mine_income":
					return MineIncome();
				case "choke_point":
				default:
					return ChokePoint();
			}
		}

		/// <summary>
		/// Fuller playtest board: owned town with build/hire options, enemy town, mines,
		/// mixed neutrals, roads, and a portal shortcut.
		/// </summary>
		public static AdventureSimState FrontierHold()
		{
			var s = Blank(24, 16, "frontier_hold");
			s.DailyGoldIncome = 500;
			s.Resources.Gold = 4000;
			s.Resources.Wood = 20;
			s.Resources.Ore = 20;

			// Mountain ridge with one road gap and a portal bypass.
			for (var z = 0; z < s.SizeZ; z++)
			{
				var n = AdventurePathfinder.NodeOf(11, z, s.SizeX);
				if (z != 7)
				{
					s.Pathable[n] = false;
					s.Terrain[n] = AdventureSimTerrain.OldenRockBlocked;
				}
			}
			s.Road[AdventurePathfinder.NodeOf(11, 7, s.SizeX)] = 2;
			for (var x = 0; x <= 10; x++)
				s.Road[AdventurePathfinder.NodeOf(x, 7, s.SizeX)] = 1;
			for (var x = 12; x < s.SizeX; x++)
				s.Road[AdventurePathfinder.NodeOf(x, 7, s.SizeX)] = 1;

			var portalA = AdventurePathfinder.NodeOf(10, 2, s.SizeX);
			var portalB = AdventurePathfinder.NodeOf(12, 13, s.SizeX);
			AdventurePathfinder.AddPortal(s, portalA, portalB);

			// Sand band in the south-west (expensive).
			for (var z = 11; z < 15; z++)
			{
				for (var x = 2; x <= 6; x++)
					s.Terrain[AdventurePathfinder.NodeOf(x, z, s.SizeX)] = AdventureSimTerrain.OldenSand;
			}

			AddHero(s, 1, "Catherine", 3, 7, 25, 55);
			AddHero(s, 2, "Scout", 4, 12, 8, 35);

			AddTownOwned(s, 101, 2, 6, "Redoubt", new AdventureSimTown
			{
				EntityId = 101,
				Faction = "castle",
				Buildings =
				{
					AdventureSimTownCatalog.VillageHall,
					AdventureSimTownCatalog.Fort,
					AdventureSimTownCatalog.DwellingT1,
				},
				Garrison =
				{
					new AdventureSimStack { UnitSid = "pikeman", Stacks = 15, UnitValue = 50 },
				},
			});
			AddTown(s, 201, 21, 8, "Black Keep");
			s.Towns.Add(new AdventureSimTown
			{
				EntityId = 201,
				Faction = "castle",
				Buildings = { AdventureSimTownCatalog.VillageHall, AdventureSimTownCatalog.Fort },
			});

			AddMine(s, 301, 6, 4, 300, "Sawmill gold");
			AddMine(s, 302, 18, 4, 400, "Ore pit");
			AddPickup(s, 401, 8, 9, 800, "Chest");
			AddPickup(s, 402, 15, 12, 1200, "Resource cache");

			AddNeutral(s, 501, 7, 7, 350, "Wolves");
			AddNeutral(s, 502, 13, 7, 900, "Orcs");
			AddNeutral(s, 503, 19, 8, 2500, "Keep guard");
			AddNeutral(s, 504, 5, 13, 500, "Swamp pack");
			AddNeutral(s, 505, 16, 3, 700, "Hill tribe");

			s.Marks.MarkedCity = 201;
			s.Marks.MarkedObject = 401;
			s.Marks.MarkedSquads.Add(501);
			s.Marks.MarkedSquads.Add(502);

			OldenTileMp.FillMoveCost(s);
			return s;
		}

		private static void AddTownOwned(AdventureSimState s, int id, int x, int z, string label, AdventureSimTown town)
		{
			s.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = id,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				Kind = AdventureSimTargetKind.Town,
				Label = label,
				OwnerSide = s.SideIndex,
				Alive = true,
			});
			if (town != null)
			{
				town.EntityId = id;
				s.Towns.Add(town);
			}
		}

		public static AdventureSimState ChokePoint()
		{
			var s = Blank(16, 12, "choke_point");
			for (var z = 0; z < s.SizeZ; z++)
			{
				var n = AdventurePathfinder.NodeOf(7, z, s.SizeX);
				if (z != 5)
				{
					s.Pathable[n] = false;
					s.Terrain[n] = AdventureSimTerrain.OldenRockBlocked;
				}
			}
			// Road through the gap.
			s.Road[AdventurePathfinder.NodeOf(7, 5, s.SizeX)] = 2;
			AddHero(s, 1, "Catherine", 2, 5, 20, 60);
			AddNeutral(s, 101, 10, 5, 400, "Wolves");
			AddTown(s, 201, 14, 5, "Enemy Keep");
			AddPickup(s, 301, 4, 2, 500, "Chest");
			s.Marks.MarkedSquads.Add(101);
			s.Marks.MarkedCity = 201;
			s.Resources.Gold = 3000;
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState SwampDetour()
		{
			var s = Blank(14, 10, "swamp_detour");
			// Olden swamp is penalty 0.4 like grass — still paint for visuals; sand band is expensive.
			for (var z = 0; z < s.SizeZ; z++)
			{
				for (var x = 5; x <= 7; x++)
				{
					var n = AdventurePathfinder.NodeOf(x, z, s.SizeX);
					s.Terrain[n] = AdventureSimTerrain.OldenSand;
				}
			}
			AddHero(s, 1, "Solmyr", 1, 4, 15, 80);
			AddNeutral(s, 110, 10, 4, 350, "Elementals");
			AddMine(s, 210, 12, 8, 200, "Gold Mine");
			AddPickup(s, 310, 3, 8, 1000, "Resource pile");
			s.Marks.MarkedObject = 310;
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState TwoHeroSplit()
		{
			var s = Blank(18, 12, "two_hero_split");
			AddHero(s, 1, "Main", 1, 2, 25, 55);
			AddHero(s, 2, "Scout", 1, 10, 5, 30);
			AddNeutral(s, 120, 8, 2, 600, "Strong guard");
			AddPickup(s, 320, 6, 10, 800, "Easy loot");
			AddTown(s, 220, 16, 6, "Prize Town");
			s.Marks.MarkedSquads.Add(120);
			s.Marks.MarkedObject = 320;
			s.Marks.MarkedCity = 220;
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState RichPickupVsGuard()
		{
			var s = Blank(12, 8, "rich_pickup_vs_guard");
			AddHero(s, 1, "Crag Hack", 1, 3, 30, 40);
			AddNeutral(s, 130, 4, 3, 20000, "Dragon (suicide)");
			AddPickup(s, 330, 8, 3, 5000, "Artifact stash");
			AddNeutral(s, 131, 7, 5, 300, "Easy pack");
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState EmptyBoard()
		{
			var s = Blank(10, 10, "empty_board");
			AddHero(s, 1, "Idle", 5, 5, 10, 50);
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState PortalHop()
		{
			var s = Blank(12, 8, "portal_hop");
			// Wall separating left/right except portal.
			for (var z = 0; z < s.SizeZ; z++)
			{
				var n = AdventurePathfinder.NodeOf(5, z, s.SizeX);
				s.Pathable[n] = false;
				s.Terrain[n] = AdventureSimTerrain.OldenRockBlocked;
			}
			var a = AdventurePathfinder.NodeOf(4, 3, s.SizeX);
			var b = AdventurePathfinder.NodeOf(6, 3, s.SizeX);
			s.Pathable[a] = true;
			s.Pathable[b] = true;
			s.Terrain[a] = AdventureSimTerrain.OldenGrass;
			s.Terrain[b] = AdventureSimTerrain.OldenGrass;
			AdventurePathfinder.AddPortal(s, a, b);
			AddHero(s, 1, "PortalWalker", 1, 3, 20, 50);
			AddPickup(s, 401, 10, 3, 2000, "Far chest");
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState MineIncome()
		{
			var s = Blank(10, 8, "mine_income");
			s.DailyGoldIncome = 500;
			AddHero(s, 1, "Miner", 1, 3, 20, 50);
			AddMine(s, 501, 3, 3, 300, "Gold Mine");
			AddPickup(s, 502, 8, 3, 100, "Small chest");
			OldenTileMp.FillMoveCost(s);
			return s;
		}

		public static AdventureSimState Blank(int sizeX, int sizeZ, string name)
		{
			var n = sizeX * sizeZ;
			var pathable = new bool[n];
			var terrain = new byte[n];
			var road = new byte[n];
			for (var i = 0; i < n; i++)
			{
				pathable[i] = true;
				terrain[i] = AdventureSimTerrain.OldenGrass;
				road[i] = 0;
			}
			return new AdventureSimState
			{
				ScenarioName = name,
				SizeX = sizeX,
				SizeZ = sizeZ,
				Pathable = pathable,
				Terrain = terrain,
				Road = road,
				Day = 1,
				SideIndex = 0,
				SideName = "Red",
				DailyGoldIncome = 1000,
				Resources = new AdventureSimResources { Gold = 2000, Wood = 10, Ore = 10 },
				Portals = new Dictionary<int, List<int>>(),
			};
		}

		private static void AddHero(AdventureSimState s, int id, string name, int x, int z, int stacks, int unitValue)
		{
			s.Heroes.Add(new AdventureSimHero
			{
				HeroId = id,
				Name = name,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				MovePoints = 1500,
				MaxMovePoints = 1500,
				Mana = 20,
				Party =
				{
					new AdventureSimStack { UnitSid = "troop", Stacks = stacks, UnitValue = unitValue },
				},
			});
		}

		private static void AddNeutral(AdventureSimState s, int id, int x, int z, int startValue, string label)
		{
			s.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = id,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				Kind = AdventureSimTargetKind.Neutral,
				StartValue = startValue,
				Label = label,
				Alive = true,
			});
		}

		private static void AddTown(AdventureSimState s, int id, int x, int z, string label)
		{
			s.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = id,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				Kind = AdventureSimTargetKind.Town,
				Label = label,
				OwnerSide = 1,
				Alive = true,
			});
		}

		private static void AddPickup(AdventureSimState s, int id, int x, int z, int gold, string label)
		{
			s.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = id,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				Kind = AdventureSimTargetKind.Pickup,
				GoldReward = gold,
				Label = label,
				Alive = true,
			});
		}

		private static void AddMine(AdventureSimState s, int id, int x, int z, int gold, string label)
		{
			s.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = id,
				Node = AdventurePathfinder.NodeOf(x, z, s.SizeX),
				Kind = AdventureSimTargetKind.Mine,
				GoldReward = gold,
				Label = label,
				Alive = true,
				OwnerSide = -1,
			});
		}
	}
}
