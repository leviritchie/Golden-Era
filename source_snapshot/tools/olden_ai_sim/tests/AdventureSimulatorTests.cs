using System;
using System.IO;
using System.Linq;
using OldenAiSim;
using Xunit;

namespace OldenAiSim.Tests
{
	public class AdventureSimulatorTests
	{
		[Fact]
		public void Evaluate_prefers_reachable_weak_neutral_over_unreachable_town()
		{
			var state = BuildGrid(8, 8);
			state.Day = 1;
			state.SideIndex = 0;
			for (var z = 0; z < 8; z++)
				state.Pathable[Node(5, z, 8)] = false;
			state.Heroes.Add(new AdventureSimHero
			{
				HeroId = 1,
				Node = Node(1, 1, 8),
				MovePoints = 400,
				MaxMovePoints = 400,
				Party =
				{
					new AdventureSimStack { UnitSid = "pikeman", Stacks = 20, UnitValue = 50 },
				},
			});
			state.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = 101,
				Node = Node(2, 1, 8),
				Kind = AdventureSimTargetKind.Neutral,
				StartValue = 200,
				Alive = true,
			});
			state.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = 202,
				Node = Node(7, 7, 8),
				Kind = AdventureSimTargetKind.Town,
				StartValue = 0,
				Alive = true,
			});
			OldenTileMp.FillMoveCost(state);

			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs
			{
				BeamDepth = 2,
				BeamWidth = 4,
				TimeBudgetMs = 200,
				WinPowerRatio = 1.0f,
			});

			Assert.True(result.Ok, result.Error);
			Assert.Equal(AdventureSimTargetKind.Neutral, result.PreferredKind);
			Assert.Equal(101, result.PreferredId);
			Assert.NotEmpty(result.Biases);
		}

		[Fact]
		public void Evaluate_skips_unwinnable_neutral()
		{
			var state = BuildGrid(5, 5);
			state.Heroes.Add(new AdventureSimHero
			{
				HeroId = 1,
				Node = 0,
				MovePoints = 500,
				Party = { new AdventureSimStack { UnitSid = "imp", Stacks = 1, UnitValue = 10 } },
			});
			state.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = 9,
				Node = 1,
				Kind = AdventureSimTargetKind.Neutral,
				StartValue = 50000,
				Alive = true,
			});
			state.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = 3,
				Node = 2,
				Kind = AdventureSimTargetKind.Pickup,
				Alive = true,
			});
			OldenTileMp.FillMoveCost(state);

			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs { WinPowerRatio = 1.15f, TimeBudgetMs = 200 });
			Assert.True(result.Ok, result.Error);
			Assert.Equal(AdventureSimTargetKind.Pickup, result.PreferredKind);
			Assert.Equal(3, result.PreferredId);
		}

		[Fact]
		public void Evaluate_empty_occupancy_ok_with_no_biases()
		{
			var state = BuildGrid(3, 3);
			state.Heroes.Add(new AdventureSimHero { HeroId = 1, Node = 0, MovePoints = 100 });
			OldenTileMp.FillMoveCost(state);
			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs());
			Assert.True(result.Ok);
			Assert.Empty(result.Biases);
		}

		[Fact]
		public void Scenario_rich_pickup_vs_guard_avoids_suicide_dragon()
		{
			var state = AdventureSimScenarios.Create("rich_pickup_vs_guard");
			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs
			{
				BeamDepth = 3,
				BeamWidth = 8,
				TimeBudgetMs = 200,
				WinPowerRatio = 1.15f,
			});
			Assert.True(result.Ok, result.Error);
			Assert.NotEqual(130, result.PreferredId);
		}

		[Fact]
		public void MoveCost_authority_road_cheaper_than_dirt()
		{
			var state = AdventureSimScenarios.Blank(4, 4, "road_test");
			var dirt = AdventurePathfinder.NodeOf(1, 1, 4);
			var road = AdventurePathfinder.NodeOf(2, 1, 4);
			state.Terrain[dirt] = AdventureSimTerrain.OldenDirt;
			state.Terrain[road] = AdventureSimTerrain.OldenDirt;
			state.Road[road] = 2;
			OldenTileMp.FillMoveCost(state);
			Assert.True(AdventurePathfinder.MoveCostIsAuthority(state));
			var knobs = new AdventureSimKnobs();
			Assert.True(
				AdventurePathfinder.CellCost(state, knobs, road)
				< AdventurePathfinder.CellCost(state, knobs, dirt));
		}

		[Fact]
		public void Portal_hop_reaches_far_side()
		{
			var state = AdventureSimScenarios.Create("portal_hop");
			var knobs = new AdventureSimKnobs();
			var hero = state.Heroes[0];
			var chest = state.Occupancy.First(o => o.EntityId == 401);
			var costs = AdventurePathfinder.ReachableCosts(state, knobs, hero.Node, 20000, state.Occupancy, 401);
			Assert.True(costs.ContainsKey(chest.Node), "chest must be reachable via portal");
			var path = AdventurePathfinder.ReconstructPath(state, knobs, hero.Node, chest.Node, 20000, state.Occupancy, 401);
			Assert.True(path.Count >= 2);
		}

		[Fact]
		public void Capture_mine_increases_eod_income()
		{
			var state = AdventureSimScenarios.Create("mine_income");
			var mine = state.Occupancy.First(o => o.Kind == AdventureSimTargetKind.Mine);
			var before = AdventureSimEconomy.ComputeEndOfDayGold(state, state.Occupancy);
			Assert.Equal(state.DailyGoldIncome, before);
			mine.OwnerSide = state.SideIndex;
			var after = AdventureSimEconomy.ComputeEndOfDayGold(state, state.Occupancy);
			Assert.Equal(state.DailyGoldIncome + mine.GoldReward, after);
		}

		[Fact]
		public void Stepper_step_back_restores_hero_node()
		{
			var state = AdventureSimScenarios.Create("choke_point");
			var stepper = AdventureSimStepper.Run(state, new AdventureSimKnobs { TimeBudgetMs = 300, BeamDepth = 3, BeamWidth = 8 });
			Assert.True(stepper.Result.Ok, stepper.Result.Error);
			Assert.True(stepper.StepCount >= 1, "expected at least one step");
			string err;
			Assert.True(stepper.TryStepForward(out err), err);
			var after = stepper.CurrentWorld();
			Assert.True(stepper.TryStepBack(out err), err);
			var back = stepper.CurrentWorld();
			Assert.Equal(state.Heroes[0].Node, back.Heroes[0].Node);
			Assert.NotNull(after);
		}

		[Fact]
		public void Stepper_fail_closed_at_end()
		{
			var state = AdventureSimScenarios.Create("empty_board");
			var stepper = AdventureSimStepper.Run(state, new AdventureSimKnobs());
			string err;
			Assert.False(stepper.TryStepForward(out err));
			Assert.Contains("empty", err);
		}

		[Fact]
		public void ScenarioIo_roundtrip_preserves_portal()
		{
			var original = AdventureSimScenarios.Create("portal_hop");
			var text = AdventureSimScenarioIo.ToText(original);
			var loaded = AdventureSimScenarioIo.FromText(text);
			Assert.Equal(original.SizeX, loaded.SizeX);
			Assert.True(loaded.Portals.Count > 0);
			Assert.NotNull(loaded.Road);
		}

		[Fact]
		public void Clipped_fixture_roundtrip()
		{
			var path = Path.Combine(Path.GetTempPath(), "olden_ai_sim_fixture_" + Guid.NewGuid().ToString("N") + ".aisim");
			try
			{
				AdventureSimMapImport.WriteBoundedFixture(path);
				var loaded = AdventureSimScenarioIo.Load(path);
				Assert.Equal("clipped_fixture", loaded.ScenarioName);
				Assert.True(loaded.Heroes.Count >= 1);
				OldenTileMp.FillMoveCost(loaded);
				var result = AdventureSimulator.Evaluate(loaded, new AdventureSimKnobs { TimeBudgetMs = 200 });
				Assert.True(result.Ok, result.Error);
			}
			finally
			{
				if (File.Exists(path))
					File.Delete(path);
			}
		}

		[Fact]
		public void Evaluate_rejects_missing_pathable_grid()
		{
			var state = new AdventureSimState
			{
				SizeX = 2,
				SizeZ = 2,
				Heroes = { new AdventureSimHero { HeroId = 1, Node = 0, MovePoints = 100 } },
				Occupancy = { new AdventureSimOccupant { EntityId = 1, Node = 1, Kind = AdventureSimTargetKind.Pickup } },
			};
			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs());
			Assert.False(result.Ok);
			Assert.Contains("Pathable", result.Error);
		}

		[Fact]
		public void Two_hero_scenario_emits_preferred_with_hero_id()
		{
			var state = AdventureSimScenarios.Create("two_hero_split");
			var result = AdventureSimulator.Evaluate(state, new AdventureSimKnobs
			{
				MultiHero = true,
				BeamDepth = 3,
				BeamWidth = 10,
				TimeBudgetMs = 250,
			});
			Assert.True(result.Ok, result.Error);
			Assert.True(result.PreferredHeroId == 1 || result.PreferredHeroId == 2);
		}

		[Fact]
		public void Frontier_hold_can_build_and_hire()
		{
			var state = AdventureSimScenarios.Create("frontier_hold");
			Assert.Contains(state.Towns, t => t.EntityId == 101 && t.Has(AdventureSimTownCatalog.DwellingT1));
			var beforeGold = state.Resources.Gold;
			var stepper = AdventureSimStepper.Run(state, new AdventureSimKnobs
			{
				BeamDepth = 4,
				BeamWidth = 16,
				TimeBudgetMs = 500,
			});
			Assert.True(stepper.Result.Ok, stepper.Result.Error);
			Assert.True(stepper.StepCount >= 1);
			var kinds = stepper.Records;
			var sawTown = false;
			for (var i = 0; i < kinds.Count; i++)
			{
				var k = kinds[i].ActionKind;
				if (k == AdventureSimActionKind.TownBuild || k == AdventureSimActionKind.TownHire
					|| k == AdventureSimActionKind.TownGarrisonTake || k == AdventureSimActionKind.MoveToOccupy)
					sawTown = true;
			}
			Assert.True(sawTown);
			Assert.True(beforeGold >= 4000);
		}

		[Fact]
		public void Owned_town_adds_daily_income()
		{
			var state = AdventureSimScenarios.Create("frontier_hold");
			var income = AdventureSimEconomy.ComputeEndOfDayGold(state, state.Occupancy, state.Towns);
			Assert.True(income > state.DailyGoldIncome);
		}

		[Fact]
		public void Committed_tile_mp_data_loads()
		{
			OldenTileMp.EnsureLoaded();
			Assert.Equal(100, OldenTileMp.StepMpForTile(1)); // grass 0.4
			Assert.Equal(200, OldenTileMp.StepMpForTile(2)); // sand 0.8
			Assert.Equal(750, OldenTileMp.StepMpForTile(18)); // water 3.0
		}

		private static AdventureSimState BuildGrid(int sizeX, int sizeZ)
		{
			var n = sizeX * sizeZ;
			var pathable = new bool[n];
			var terrain = new byte[n];
			for (var i = 0; i < n; i++)
			{
				pathable[i] = true;
				terrain[i] = AdventureSimTerrain.OldenGrass;
			}
			return new AdventureSimState
			{
				SizeX = sizeX,
				SizeZ = sizeZ,
				Pathable = pathable,
				Terrain = terrain,
				Road = new byte[n],
			};
		}

		private static int Node(int x, int z, int sizeX)
		{
			return z * sizeX + x;
		}
	}
}
