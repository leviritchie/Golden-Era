using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>Harness stand-in for the plugin's live map adapter (same member shapes the solver uses).</summary>
internal static class Homm3FactoryLogisticsMap
{
	internal const byte BlockNone = 0;
	internal const byte BlockObject = 1;
	internal const byte BlockWater = 2;

	internal sealed class StaticGrid
	{
		public int W, H;
		public byte[] Terrain, Road, Water, Block;
		public float[] RoadBonus;
		public byte[] CostOrth, CostDiag;
		public byte[] Gate;  // null = no entrance tiles (anchor falls back to the nearest open tile)
	}

	internal struct SquadInfo
	{
		public long Key;
		public int Node;
	}

	internal static StaticGrid Grid;
	internal static bool[] Visible;
	internal static List<SquadInfo> Squads = new();
	internal static readonly List<string> Log = new();

	internal static void Invalidate() { }
	internal static void LogInfo(string m) => Log.Add("I " + m);
	internal static void LogWarning(string m) => Log.Add("W " + m);
	internal static void LogError(string m) => Log.Add("E " + m);

	internal static bool TryGetStaticGrid(out StaticGrid grid, out string fail)
	{
		grid = Grid;
		fail = grid == null ? "no grid" : null;
		return grid != null;
	}

	internal static bool TryGetFogVisible(int sideId, StaticGrid grid, out bool[] visible, out string fail)
	{
		visible = Visible ?? FillTrue(grid.W * grid.H);
		fail = null;
		return true;
	}

	internal static bool TryGetSquads(StaticGrid grid, List<SquadInfo> into, out string fail)
	{
		into.AddRange(Squads);
		fail = null;
		return true;
	}

	private static bool[] FillTrue(int n)
	{
		var a = new bool[n];
		Array.Fill(a, true);
		return a;
	}

	internal static StaticGrid NewGrid(int w, int h)
	{
		var n = w * h;
		return new StaticGrid
		{
			W = w, H = h, Terrain = new byte[n], Road = new byte[n], Water = new byte[n], Block = new byte[n],
			RoadBonus = new float[n],
		};
	}
}
