using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;

namespace OldenAiSim
{
	/// <summary>
	/// Committed Core-derived tile/road MP tables. Provisional — see data/README.md.
	/// </summary>
	public static class OldenTileMp
	{
		private static Dictionary<int, int> _tileStepMp;
		private static Dictionary<int, int> _roadDiscountMp;
		private static string _loadError;

		public static string LoadError { get { return _loadError; } }

		public static int StepMpForTile(int tileId)
		{
			EnsureLoaded();
			int mp;
			if (_tileStepMp != null && _tileStepMp.TryGetValue(tileId, out mp))
				return mp;
			return 100;
		}

		public static int RoadDiscount(int roadId)
		{
			EnsureLoaded();
			int d;
			if (_roadDiscountMp != null && _roadDiscountMp.TryGetValue(roadId, out d))
				return d;
			return 0;
		}

		/// <summary>Fill MoveCost from Terrain (+ optional Road ids). MoveCost becomes sole CellCost authority.</summary>
		public static void FillMoveCost(AdventureSimState state)
		{
			if (state == null || state.SizeX <= 0 || state.SizeZ <= 0)
				return;
			var n = state.SizeX * state.SizeZ;
			var costs = new int[n];
			for (var i = 0; i < n; i++)
			{
				byte tile = 0;
				if (state.Terrain != null && i < state.Terrain.Length)
					tile = state.Terrain[i];
				var step = StepMpForTile(tile);
				var roadId = 0;
				if (state.Road != null && i < state.Road.Length)
					roadId = state.Road[i];
				if (roadId > 0)
					step = Math.Max(1, step - RoadDiscount(roadId));
				costs[i] = Math.Max(1, step);
			}
			state.MoveCost = costs;
		}

		public static void EnsureLoaded()
		{
			if (_tileStepMp != null)
				return;
			_tileStepMp = new Dictionary<int, int>();
			_roadDiscountMp = new Dictionary<int, int>();
			try
			{
				var dir = ResolveDataDir();
				LoadTiles(Path.Combine(dir, "olden_tile_mp.v1.json"));
				LoadRoads(Path.Combine(dir, "olden_road_mp.v1.json"));
			}
			catch (Exception ex)
			{
				_loadError = ex.Message;
				// Fail closed to safe defaults already seeded empty → StepMpForTile returns 100.
			}
		}

		private static string ResolveDataDir()
		{
			var asm = Assembly.GetExecutingAssembly().Location;
			var candidates = new[]
			{
				Path.Combine(Path.GetDirectoryName(asm) ?? "", "data"),
				Path.Combine(Path.GetDirectoryName(asm) ?? "", "..", "..", "..", "data"),
				Path.Combine(AppContext.BaseDirectory, "data"),
				Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "data")),
			};
			for (var i = 0; i < candidates.Length; i++)
			{
				var p = Path.GetFullPath(candidates[i]);
				if (File.Exists(Path.Combine(p, "olden_tile_mp.v1.json")))
					return p;
			}
			// Repo-relative from cwd
			var repo = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), "tools", "olden_ai_sim", "data"));
			if (File.Exists(Path.Combine(repo, "olden_tile_mp.v1.json")))
				return repo;
			throw new FileNotFoundException("olden_tile_mp.v1.json not found beside assembly or under tools/olden_ai_sim/data");
		}

		private static void LoadTiles(string path)
		{
			var text = File.ReadAllText(path);
			// Minimal parse without JSON dependency: find "id": N ... "stepMp": N pairs in order.
			var ids = ExtractInts(text, "\"id\"");
			var steps = ExtractInts(text, "\"stepMp\"");
			var count = Math.Min(ids.Count, steps.Count);
			for (var i = 0; i < count; i++)
				_tileStepMp[ids[i]] = steps[i];
			if (_tileStepMp.Count == 0)
				throw new InvalidOperationException("no tile stepMp entries in " + path);
		}

		private static void LoadRoads(string path)
		{
			if (!File.Exists(path))
				return;
			var text = File.ReadAllText(path);
			var ids = ExtractInts(text, "\"id\"");
			var discounts = ExtractInts(text, "\"discountMp\"");
			var count = Math.Min(ids.Count, discounts.Count);
			for (var i = 0; i < count; i++)
				_roadDiscountMp[ids[i]] = discounts[i];
		}

		private static List<int> ExtractInts(string text, string key)
		{
			var list = new List<int>();
			var idx = 0;
			while (idx < text.Length)
			{
				var at = text.IndexOf(key, idx, StringComparison.Ordinal);
				if (at < 0)
					break;
				var colon = text.IndexOf(':', at + key.Length);
				if (colon < 0)
					break;
				var start = colon + 1;
				while (start < text.Length && (text[start] == ' ' || text[start] == '\t'))
					start++;
				var end = start;
				while (end < text.Length && (char.IsDigit(text[end]) || text[end] == '-'))
					end++;
				int v;
				if (int.TryParse(text.Substring(start, end - start), NumberStyles.Integer, CultureInfo.InvariantCulture, out v))
					list.Add(v);
				idx = end;
			}
			return list;
		}
	}
}
