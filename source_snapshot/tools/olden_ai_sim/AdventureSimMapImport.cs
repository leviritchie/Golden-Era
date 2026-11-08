using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace OldenAiSim
{
	/// <summary>
	/// Clipped map import into AdventureSimState / .aisim.
	/// Full 80x80 is opt-in; smoke uses bounded fixtures only.
	/// </summary>
	public static class AdventureSimMapImport
	{
		public static AdventureSimState FromClippedPathability(
			bool[] pathable,
			byte[] terrain,
			int sizeX,
			int sizeZ,
			string name)
		{
			if (sizeX <= 0 || sizeZ <= 0)
				throw new ArgumentException("size must be positive");
			var n = sizeX * sizeZ;
			if (pathable == null || pathable.Length != n)
				throw new ArgumentException("pathable length mismatch");
			if (terrain != null && terrain.Length != n)
				throw new ArgumentException("terrain length mismatch");

			var state = new AdventureSimState
			{
				ScenarioName = name ?? "imported",
				SizeX = sizeX,
				SizeZ = sizeZ,
				Pathable = (bool[])pathable.Clone(),
				Terrain = terrain != null ? (byte[])terrain.Clone() : new byte[n],
				Road = new byte[n],
				Day = 1,
				SideIndex = 0,
				SideName = "Red",
				DailyGoldIncome = 1000,
				Resources = new AdventureSimResources { Gold = 2000 },
				Portals = new Dictionary<int, List<int>>(),
			};
			OldenTileMp.FillMoveCost(state);
			return state;
		}

		/// <summary>Build a small synthetic clipped region and write .aisim (for committed fixture regen).</summary>
		public static AdventureSimState CreateBoundedFixture()
		{
			var s = AdventureSimScenarios.Create("portal_hop");
			s.ScenarioName = "clipped_fixture";
			AddHeroIfMissing(s);
			return s;
		}

		public static void WriteBoundedFixture(string path)
		{
			var s = CreateBoundedFixture();
			AdventureSimScenarioIo.Save(s, path);
		}

		private static void AddHeroIfMissing(AdventureSimState s)
		{
			if (s.Heroes.Count > 0)
				return;
			s.Heroes.Add(new AdventureSimHero
			{
				HeroId = 1,
				Name = "FixtureHero",
				Node = 0,
				MovePoints = 1500,
				MaxMovePoints = 1500,
				Party = { new AdventureSimStack { UnitSid = "troop", Stacks = 10, UnitValue = 40 } },
			});
		}
	}
}
