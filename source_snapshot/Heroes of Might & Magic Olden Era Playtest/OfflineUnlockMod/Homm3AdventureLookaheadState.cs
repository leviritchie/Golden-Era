using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;

namespace OfflineUnlockMod;

/// <summary>
/// Planner-owned mark-centric adventure fork (omniscient). Does not wrap live Unity/session objects.
/// Clone for search nodes; capture from live <c>Side</c> is read-only observation.
/// Evidence: docs/ai_lookahead_requirements.md (source/static; runtime capture unvalidated).
/// </summary>
internal sealed class Homm3AdventureLookaheadState
{
	internal const string SchemaVersion = "homm3.adventure.lookahead_state.v1";

	internal string Schema => SchemaVersion;
	internal int Day;
	internal int SideIndex = -1;
	internal string SideName;
	internal Homm3AdventureMarkSnapshot Marks = new Homm3AdventureMarkSnapshot();
	internal Homm3AdventureResourceSnapshot Resources = new Homm3AdventureResourceSnapshot();
	internal List<Homm3AdventureHeroSnapshot> Heroes = new List<Homm3AdventureHeroSnapshot>();
	/// <summary>Live occupancy for relevant session entities; empty until the live adapter completes.</summary>
	internal List<Homm3AdventureOccupancySnapshot> Occupancy = new List<Homm3AdventureOccupancySnapshot>();
	internal string ActiveStrategyHint;
	internal string CaptureNotes;
	internal bool LiveMapCaptured;
	internal bool LiveOccupancyCaptured;
	internal bool MoveCostProvisional;
	internal string LiveMapCaptureError;
	internal string LiveOccupancyCaptureError;

	internal Homm3AdventureLookaheadState Clone()
	{
		var clone = new Homm3AdventureLookaheadState
		{
			Day = Day,
			SideIndex = SideIndex,
			SideName = SideName,
			Marks = Marks.Clone(),
			Resources = Resources.Clone(),
			ActiveStrategyHint = ActiveStrategyHint,
			CaptureNotes = CaptureNotes,
			LiveMapCaptured = LiveMapCaptured,
			LiveOccupancyCaptured = LiveOccupancyCaptured,
			MoveCostProvisional = MoveCostProvisional,
			LiveMapCaptureError = LiveMapCaptureError,
			LiveOccupancyCaptureError = LiveOccupancyCaptureError,
		};
		clone._pathSizeX = _pathSizeX;
		clone._pathSizeZ = _pathSizeZ;
		clone._pathable = _pathable == null ? null : (bool[])_pathable.Clone();
		clone._terrain = _terrain == null ? null : (byte[])_terrain.Clone();
		clone._road = _road == null ? null : (byte[])_road.Clone();
		clone._moveCost = _moveCost == null ? null : (int[])_moveCost.Clone();
		for (var i = 0; i < Heroes.Count; i++)
			clone.Heroes.Add(Heroes[i].Clone());
		for (var i = 0; i < Occupancy.Count; i++)
			clone.Occupancy.Add(Occupancy[i].Clone());
		return clone;
	}

	/// <summary>
	/// Read-only capture from a live <c>Hex.Session.Data.Side</c> instance.
	/// Does not mutate <paramref name="liveSide"/>. Map and session-object capture is supplied by the
	/// AI-driver adapter after this side-only pass.
	/// </summary>
	internal static bool TryCaptureFromLiveSide(object liveSide, out Homm3AdventureLookaheadState state, out string error)
	{
		state = null;
		error = null;
		if (liveSide == null)
		{
			error = "liveSide is null";
			return false;
		}

		var sideType = liveSide.GetType();
		if (!TypeMatchesHints(sideType, GameSymbols.AdventureAiDecision.SideTypeHints))
		{
			error = "liveSide type is not Side (" + (sideType.FullName ?? sideType.Name) + ")";
			return false;
		}

		var aiData = ReadMember(liveSide, GameSymbols.AdventureAiDecision.SideAiDataFieldHints);
		if (aiData == null)
		{
			error = "Side.aiData missing";
			return false;
		}

		var captured = new Homm3AdventureLookaheadState();
		captured.SideIndex = ReadInt(liveSide, GameSymbols.AdventureAiDecision.SideIndexFieldHints, -1);
		captured.SideName = ReadString(liveSide, GameSymbols.AdventureAiDecision.SideNameFieldHints);
		if (!Homm3AdventureMarkSnapshot.TryFromLiveAiData(aiData, out var marks, out var marksError))
		{
			error = marksError ?? "SideAiData marks unresolved";
			return false;
		}
		captured.Marks = marks;

		var resHeap = ReadMember(liveSide, GameSymbols.AdventureAiDecision.SideResFieldHints);
		if (resHeap == null)
		{
			error = "Side.res missing";
			return false;
		}
		captured.Resources = Homm3AdventureResourceSnapshot.FromLiveResHeap(resHeap);
		CaptureHeroIds(captured, ReadMember(liveSide, GameSymbols.AdventureAiDecision.SideHeroesFieldHints));
		captured.CaptureNotes = "marks+resources+heroIds; live map/pose/occupancy adapter required; no fog copy";
		state = captured;
		return true;
	}

	/// <summary>Maps capture into OldenAiSim DTO. Missing live arrays produce an invalid DTO rather than a synthetic grid.</summary>
	internal OldenAiSim.AdventureSimState ToSimState()
	{
		var sim = new OldenAiSim.AdventureSimState
		{
			Day = Day,
			SideIndex = SideIndex,
			SideName = SideName,
			Marks = new OldenAiSim.AdventureSimMarks
			{
				MarkedCity = Marks.MarkedCity,
				MarkedHero = Marks.MarkedHero,
				MarkedObject = Marks.MarkedObject,
				MarkedNode = Marks.MarkedNode,
				MarkedEnemyCity = Marks.MarkedEnemyCity,
				HardStrategy = Marks.HardStrategy,
				MarkedSquads = new List<int>(Marks.MarkedSquads),
			},
			Resources = new OldenAiSim.AdventureSimResources
			{
				Gold = Resources.Gold,
				Wood = Resources.Wood,
				Ore = Resources.Ore,
				Gemstones = Resources.Gemstones,
				Crystals = Resources.Crystals,
				Mercury = Resources.Mercury,
			},
		};

		for (var i = 0; i < Heroes.Count; i++)
		{
			var h = Heroes[i];
			var sh = new OldenAiSim.AdventureSimHero
			{
				HeroId = h.HeroId,
				Node = h.Node,
				MovePoints = h.MovePoints,
				Mana = h.Mana,
			};
			for (var p = 0; p < h.Party.Count; p++)
			{
				var s = h.Party[p];
				sh.Party.Add(new OldenAiSim.AdventureSimStack
				{
					UnitSid = s.UnitSid,
					Stacks = s.Stacks,
					UnitValue = 0,
				});
			}
			sim.Heroes.Add(sh);
		}

		for (var i = 0; i < Occupancy.Count; i++)
		{
			var o = Occupancy[i];
			sim.Occupancy.Add(new OldenAiSim.AdventureSimOccupant
			{
				EntityId = o.EntityId,
				Node = o.Node,
				Kind = ParseOccupantKind(o.Kind),
				StartValue = o.StartValue,
				Alive = o.Alive,
			});
		}

		if (_terrain != null)
			sim.Terrain = (byte[])_terrain.Clone();
		if (_road != null)
			sim.Road = (byte[])_road.Clone();
		if (_moveCost != null)
			sim.MoveCost = (int[])_moveCost.Clone();
		EnsurePathability(sim);
		return sim;
	}

	internal void SetPathability(int sizeX, int sizeZ, bool[] pathable)
	{
		_pathSizeX = sizeX;
		_pathSizeZ = sizeZ;
		_pathable = pathable == null ? null : (bool[])pathable.Clone();
	}

	/// <summary>
	/// Stores the live MapData grid without remapping world node ids. Pathability is a
	/// conservative land projection, not a claim that the engine's hidden pathfinder was read.
	/// MoveCost is the committed provisional Core table and is never treated as native proof.
	/// </summary>
	internal bool SetLiveMap(
		int sizeX,
		int sizeZ,
		byte[] terrain,
		byte[] road,
		byte[] water,
		out string error)
	{
		error = null;
		if (sizeX <= 0 || sizeZ <= 0)
		{
			error = "map dimensions are invalid";
			return false;
		}
		long cellCountLong = (long)sizeX * sizeZ;
		if (cellCountLong > GameSymbols.AdventureAiDecision.MaxLiveMapCells)
		{
			error = "map exceeds live capture cell cap";
			return false;
		}
		var cellCount = (int)cellCountLong;
		if (terrain == null || terrain.Length != cellCount)
		{
			error = "tilesMap missing or wrong length";
			return false;
		}
		if (road == null || road.Length != cellCount)
		{
			error = "roadsMap missing or wrong length";
			return false;
		}
		if (water == null || water.Length != cellCount)
		{
			error = "waterMap missing or wrong length";
			return false;
		}

		_pathSizeX = sizeX;
		_pathSizeZ = sizeZ;
		_terrain = (byte[])terrain.Clone();
		_road = (byte[])road.Clone();
		_pathable = new bool[cellCount];
		for (var i = 0; i < cellCount; i++)
		{
			var tile = terrain[i];
			_pathable[i] = tile > 0
				&& tile != GameSymbols.AdventureAiDecision.LiveMapVoidTerrainTileCode
				&& water[i] == 0;
		}

		var moveCostState = new OldenAiSim.AdventureSimState
		{
			SizeX = sizeX,
			SizeZ = sizeZ,
			Terrain = (byte[])terrain.Clone(),
			Road = (byte[])road.Clone(),
		};
		try
		{
			OldenAiSim.OldenTileMp.FillMoveCost(moveCostState);
		}
		catch (Exception ex)
		{
			error = "provisional move-cost generation failed: " + ex.Message;
			return false;
		}
		if (moveCostState.MoveCost == null || moveCostState.MoveCost.Length != cellCount)
		{
			error = "provisional move-cost grid missing or wrong length";
			return false;
		}
		_moveCost = moveCostState.MoveCost;
		LiveMapCaptured = true;
		MoveCostProvisional = true;
		LiveMapCaptureError = null;
		return true;
	}

	internal void SetLiveOccupancyCaptureResult(bool captured, string error)
	{
		LiveOccupancyCaptured = captured;
		LiveOccupancyCaptureError = error;
	}

	internal bool TryValidateForSimulation(bool applyFlag, out string error)
	{
		error = null;
		if (!LiveMapCaptured || _pathable == null || _terrain == null || _road == null)
		{
			error = "live map capture incomplete";
			return false;
		}
		long cells = _pathSizeX > 0 && _pathSizeZ > 0 ? (long)_pathSizeX * _pathSizeZ : 0;
		if (cells <= 0 || cells > GameSymbols.AdventureAiDecision.MaxLiveMapCells
			|| _pathable.Length != cells || _terrain.Length != cells || _road.Length != cells)
		{
			error = "live map arrays are inconsistent";
			return false;
		}
		if (_moveCost == null || _moveCost.Length != cells)
		{
			error = "move-cost grid missing";
			return false;
		}
		if (!LiveOccupancyCaptured)
		{
			error = "live occupancy capture incomplete";
			return false;
		}
		if (Heroes == null || Heroes.Count == 0)
		{
			error = "no live heroes";
			return false;
		}
		for (var i = 0; i < Heroes.Count; i++)
		{
			var hero = Heroes[i];
			if (hero == null || !hero.HasLivePose)
			{
				error = "hero pose incomplete at index " + i.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			if (hero.Node < 0 || hero.Node >= cells)
			{
				error = "hero node outside captured map";
				return false;
			}
		}
		if (applyFlag && MoveCostProvisional)
		{
			error = "apply refused while move-cost formula is provisional";
			return false;
		}
		return true;
	}

	private int _pathSizeX;
	private int _pathSizeZ;
	private bool[] _pathable;
	private byte[] _terrain;
	private byte[] _road;
	private int[] _moveCost;

	private void EnsurePathability(OldenAiSim.AdventureSimState sim)
	{
		if (_pathable != null && _pathSizeX > 0 && _pathSizeZ > 0
			&& _pathable.Length == _pathSizeX * _pathSizeZ)
		{
			sim.SizeX = _pathSizeX;
			sim.SizeZ = _pathSizeZ;
			sim.Pathable = (bool[])_pathable.Clone();
			return;
		}

		sim.SizeX = 0;
		sim.SizeZ = 0;
		sim.Pathable = Array.Empty<bool>();
		sim.Terrain = null;
		sim.Road = null;
		sim.MoveCost = null;
	}

	private static OldenAiSim.AdventureSimTargetKind ParseOccupantKind(string kind)
	{
		if (string.IsNullOrEmpty(kind))
			return OldenAiSim.AdventureSimTargetKind.Unknown;
		if (string.Equals(kind, "neutral", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(kind, "squad", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Neutral;
		if (string.Equals(kind, "town", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(kind, "city", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Town;
		if (string.Equals(kind, "hero", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Hero;
		if (string.Equals(kind, "mine", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Mine;
		if (string.Equals(kind, "pickup", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(kind, "object", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Pickup;
		if (string.Equals(kind, "node", StringComparison.OrdinalIgnoreCase))
			return OldenAiSim.AdventureSimTargetKind.Node;
		return OldenAiSim.AdventureSimTargetKind.Unknown;
	}

	internal string FormatSummary()
	{
		var sb = new StringBuilder(192);
		sb.Append("schema=").Append(SchemaVersion)
			.Append(" side=").Append(SideIndex.ToString(CultureInfo.InvariantCulture))
			.Append('/').Append(SideName ?? "?")
			.Append(" day=").Append(Day.ToString(CultureInfo.InvariantCulture))
			.Append(" marks={").Append(Marks.FormatCompact()).Append('}')
			.Append(" gold=").Append(Resources.Gold.ToString(CultureInfo.InvariantCulture))
			.Append(" heroes=").Append(Heroes.Count.ToString(CultureInfo.InvariantCulture))
			.Append(" poses=").Append(CountLiveHeroPoses().ToString(CultureInfo.InvariantCulture))
			.Append(" map=").Append(LiveMapCaptured ? (_pathSizeX + "x" + _pathSizeZ) : "-")
			.Append(" occupancy=").Append(LiveOccupancyCaptured ? "live" : "-");
		if (!string.IsNullOrEmpty(ActiveStrategyHint))
			sb.Append(" strategy=").Append(ActiveStrategyHint);
		return sb.ToString();
	}
	private int CountLiveHeroPoses()
	{
		var count = 0;
		for (var i = 0; i < Heroes.Count; i++)
			if (Heroes[i] != null && Heroes[i].HasLivePose)
				count++;
		return count;
	}

	private static void CaptureHeroIds(Homm3AdventureLookaheadState state, object sideHeroes)
	{
		if (sideHeroes == null)
			return;
		var heroesMember = ReadMember(sideHeroes, GameSymbols.AdventureAiDecision.SideHeroesListMembers);
		if (heroesMember == null)
			heroesMember = sideHeroes;
		if (heroesMember is not IEnumerable enumerable)
			return;
		var seen = new HashSet<int>();
		foreach (var item in enumerable)
		{
			if (item == null)
				continue;
			var id = item is string || item.GetType().IsPrimitive
				? ReadIntValue(item, -1)
				: ReadInt(item, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints, -1);
			if (id < 0 || !seen.Add(id))
				continue;
			state.Heroes.Add(new Homm3AdventureHeroSnapshot { HeroId = id });
		}
	}

	private static int ReadIntValue(object raw, int fallback)
	{
		try { return Convert.ToInt32(raw, CultureInfo.InvariantCulture); }
		catch { return fallback; }
	}

	/// <summary>Merge readable <c>Hex.Session.Data.Hero</c> fields into a matching snapshot by id.</summary>
	internal bool TryApplyDataHero(object dataHero)
	{
		if (dataHero == null)
			return false;
		var id = ReadInt(dataHero, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints, -1);
		if (id < 0)
			return false;
		Homm3AdventureHeroSnapshot hero = null;
		for (var i = 0; i < Heroes.Count; i++)
		{
			if (Heroes[i].HeroId == id)
			{
				hero = Heroes[i];
				break;
			}
		}
		if (hero == null)
		{
			hero = new Homm3AdventureHeroSnapshot { HeroId = id };
			Heroes.Add(hero);
		}

		var node = 0;
		var movePoints = 0;
		var hasNode = TryGetMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroNodeFieldHints, out var nodeRaw)
			&& TryConvertInt(nodeRaw, out node);
		var hasMove = TryGetMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroMovePointsFieldHints, out var moveRaw)
			&& TryConvertInt(moveRaw, out movePoints);
		if (hasNode)
			hero.Node = node;
		if (hasMove)
			hero.MovePoints = movePoints;
		hero.HasLivePose = hasNode && hasMove && hero.Node >= 0 && hero.MovePoints >= 0;
		hero.Mana = ReadInt(dataHero, GameSymbols.AdventureAiDecision.DataHeroManaFieldHints, hero.Mana);
		var party = ReadMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroPartyFieldHints);
		var units = party == null ? null : ReadMember(party, GameSymbols.AdventureAiDecision.DataPartyUnitsFieldHints);
		if (units is IEnumerable unitEnum)
		{
			hero.Party.Clear();
			foreach (var u in unitEnum)
			{
				if (u == null)
					continue;
				var sid = ReadString(u, GameSymbols.AdventureAiDecision.DataUnitSidFieldHints);
				var stacks = ReadInt(u, GameSymbols.AdventureAiDecision.DataUnitStacksFieldHints, 0);
				if (stacks <= 0)
					continue;
				hero.Party.Add(new Homm3AdventureStackSnapshot { UnitSid = sid, Stacks = stacks });
			}
		}
		return true;
	}

	internal void AddOccupant(int entityId, int node, string kind, int startValue, bool alive = true)
	{
		Occupancy.Add(new Homm3AdventureOccupancySnapshot
		{
			EntityId = entityId,
			Node = node,
			Kind = kind,
			StartValue = startValue,
			Alive = alive,
		});
	}

	internal static bool TypeMatchesHints(Type type, string[] hints)
	{
		if (type == null || hints == null)
			return false;
		var full = type.FullName ?? string.Empty;
		var name = type.Name ?? string.Empty;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			if (hint.IndexOf('.') >= 0)
			{
				if (string.Equals(full, hint, StringComparison.Ordinal))
					return true;
				continue;
			}
			if (!string.Equals(name, hint, StringComparison.Ordinal)
				&& !full.EndsWith("." + hint, StringComparison.Ordinal))
				continue;
			// Bare "Side" must live under Session.Data to avoid unrelated short-name collisions.
			if (string.Equals(hint, "Side", StringComparison.Ordinal)
				&& full.IndexOf("Session.Data", StringComparison.Ordinal) < 0)
				continue;
			return true;
		}
		return false;
	}

	internal static bool TryGetMember(object obj, string[] hints, out object value)
	{
		value = null;
		if (obj == null || hints == null)
			return false;
		var type = obj.GetType();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			try
			{
				var prop = type.GetProperty(hint, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					value = prop.GetValue(obj);
					return true;
				}
			}
			catch { }
			try
			{
				var field = type.GetField(hint, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (field != null)
				{
					value = field.GetValue(obj);
					return true;
				}
			}
			catch { }
		}
		return false;
	}

	internal static object ReadMember(object obj, string[] hints)
	{
		TryGetMember(obj, hints, out var value);
		return value;
	}

	internal static int ReadInt(object obj, string[] hints, int fallback)
	{
		var value = ReadMember(obj, hints);
		if (value == null)
			return fallback;
		try { return Convert.ToInt32(value, CultureInfo.InvariantCulture); }
		catch { return fallback; }
	}

	private static bool TryConvertInt(object raw, out int value)
	{
		value = 0;
		if (raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	internal static string ReadString(object obj, string[] hints)
	{
		var value = ReadMember(obj, hints);
		return value as string ?? value?.ToString();
	}
}

internal sealed class Homm3AdventureMarkSnapshot
{
	internal int MarkedCity;
	internal int MarkedHero;
	internal int MarkedObject;
	internal int MarkedNode;
	internal int MarkedEnemyCity;
	internal int MarkedCityToCourier;
	internal int MarkedCityToUnitUpgrade;
	internal string HardStrategy;
	internal int BuildingCooldown;
	internal int HeroesHiredToday;
	internal List<int> MarkedSquads = new List<int>();
	internal int[] AreasReachable = Array.Empty<int>();
	internal int[] AreasLastOpen = Array.Empty<int>();

	internal Homm3AdventureMarkSnapshot Clone()
	{
		return new Homm3AdventureMarkSnapshot
		{
			MarkedCity = MarkedCity,
			MarkedHero = MarkedHero,
			MarkedObject = MarkedObject,
			MarkedNode = MarkedNode,
			MarkedEnemyCity = MarkedEnemyCity,
			MarkedCityToCourier = MarkedCityToCourier,
			MarkedCityToUnitUpgrade = MarkedCityToUnitUpgrade,
			HardStrategy = HardStrategy,
			BuildingCooldown = BuildingCooldown,
			HeroesHiredToday = HeroesHiredToday,
			MarkedSquads = new List<int>(MarkedSquads),
			AreasReachable = (int[])AreasReachable.Clone(),
			AreasLastOpen = (int[])AreasLastOpen.Clone(),
		};
	}

	internal static bool TryFromLiveAiData(object aiData, out Homm3AdventureMarkSnapshot marks, out string error)
	{
		marks = null;
		error = null;
		if (aiData == null)
		{
			error = "aiData is null";
			return false;
		}

		var resolved = 0;
		var snap = new Homm3AdventureMarkSnapshot();
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedCityFieldHints, out snap.MarkedCity))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedHeroFieldHints, out snap.MarkedHero))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedObjectFieldHints, out snap.MarkedObject))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedNodeFieldHints, out snap.MarkedNode))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedEnemyCityFieldHints, out snap.MarkedEnemyCity))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedCityToCourierFieldHints, out snap.MarkedCityToCourier))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.MarkedCityToUnitUpgradeFieldHints, out snap.MarkedCityToUnitUpgrade))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.BuildingCooldownFieldHints, out snap.BuildingCooldown))
			resolved++;
		if (TryReadIntMember(aiData, GameSymbols.AdventureAiDecision.HeroesHiredTodayFieldHints, out snap.HeroesHiredToday))
			resolved++;
		if (Homm3AdventureLookaheadState.TryGetMember(aiData, GameSymbols.AdventureAiDecision.HardStrategyFieldHints, out var hard))
		{
			resolved++;
			snap.HardStrategy = hard as string ?? hard?.ToString();
		}
		if (Homm3AdventureLookaheadState.TryGetMember(aiData, GameSymbols.AdventureAiDecision.MarkedSquadsFieldHints, out var squads))
		{
			resolved++;
			CopyIntCollection(squads, snap.MarkedSquads);
		}
		if (Homm3AdventureLookaheadState.TryGetMember(aiData, GameSymbols.AdventureAiDecision.AreasReachableFieldHints, out var reachable))
		{
			resolved++;
			snap.AreasReachable = CopyIntArray(reachable);
		}
		if (Homm3AdventureLookaheadState.TryGetMember(aiData, GameSymbols.AdventureAiDecision.AreasLastOpenFieldHints, out var lastOpen))
		{
			resolved++;
			snap.AreasLastOpen = CopyIntArray(lastOpen);
		}

		if (resolved == 0)
		{
			error = "no SideAiData mark fields resolved (symbol drift?)";
			return false;
		}

		marks = snap;
		return true;
	}

	private static bool TryReadIntMember(object obj, string[] hints, out int value)
	{
		value = 0;
		if (!Homm3AdventureLookaheadState.TryGetMember(obj, hints, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	internal string FormatCompact()
	{
		return "city=" + MarkedCity.ToString(CultureInfo.InvariantCulture)
			+ " hero=" + MarkedHero.ToString(CultureInfo.InvariantCulture)
			+ " obj=" + MarkedObject.ToString(CultureInfo.InvariantCulture)
			+ " node=" + MarkedNode.ToString(CultureInfo.InvariantCulture)
			+ " enemyCity=" + MarkedEnemyCity.ToString(CultureInfo.InvariantCulture)
			+ " squads=" + MarkedSquads.Count.ToString(CultureInfo.InvariantCulture)
			+ " hard=" + (HardStrategy ?? "-");
	}

	private static void CopyIntCollection(object source, List<int> dest)
	{
		if (source is not IEnumerable enumerable || dest == null)
			return;
		foreach (var item in enumerable)
		{
			if (item == null)
				continue;
			try { dest.Add(Convert.ToInt32(item, CultureInfo.InvariantCulture)); }
			catch { }
		}
	}

	private static int[] CopyIntArray(object source)
	{
		if (source is int[] arr)
			return (int[])arr.Clone();
		if (source is not IEnumerable enumerable)
			return Array.Empty<int>();
		var list = new List<int>();
		CopyIntCollection(enumerable, list);
		return list.ToArray();
	}
}

internal sealed class Homm3AdventureResourceSnapshot
{
	internal int Gold;
	internal int Wood;
	internal int Ore;
	internal int Gemstones;
	internal int Crystals;
	internal int Mercury;

	internal Homm3AdventureResourceSnapshot Clone()
	{
		return new Homm3AdventureResourceSnapshot
		{
			Gold = Gold,
			Wood = Wood,
			Ore = Ore,
			Gemstones = Gemstones,
			Crystals = Crystals,
			Mercury = Mercury,
		};
	}

	internal static Homm3AdventureResourceSnapshot FromLiveResHeap(object resHeap)
	{
		var snap = new Homm3AdventureResourceSnapshot();
		if (resHeap == null)
			return snap;
		snap.Gold = ReadResourceValue(resHeap, "gold");
		snap.Wood = ReadResourceValue(resHeap, "wood");
		snap.Ore = ReadResourceValue(resHeap, "ore");
		snap.Gemstones = ReadResourceValue(resHeap, "gemstones");
		snap.Crystals = ReadResourceValue(resHeap, "crystals");
		snap.Mercury = ReadResourceValue(resHeap, "mercury");
		return snap;
	}

	private static int ReadResourceValue(object resHeap, string fieldName)
	{
		var resource = Homm3AdventureLookaheadState.ReadMember(resHeap, new[] { fieldName });
		if (resource == null)
			return 0;
		return Homm3AdventureLookaheadState.ReadInt(resource, new[] { "value" }, 0);
	}
}

internal sealed class Homm3AdventureHeroSnapshot
{
	internal int HeroId;
	internal int Node;
	internal int MovePoints;
	internal int Mana;
	internal bool HasLivePose;
	internal List<Homm3AdventureStackSnapshot> Party = new List<Homm3AdventureStackSnapshot>();

	internal Homm3AdventureHeroSnapshot Clone()
	{
		var clone = new Homm3AdventureHeroSnapshot
		{
			HeroId = HeroId,
			Node = Node,
			MovePoints = MovePoints,
			Mana = Mana,
			HasLivePose = HasLivePose,
		};
		for (var i = 0; i < Party.Count; i++)
			clone.Party.Add(Party[i].Clone());
		return clone;
	}
}

internal sealed class Homm3AdventureStackSnapshot
{
	internal string UnitSid;
	internal int Stacks;

	internal Homm3AdventureStackSnapshot Clone()
	{
		return new Homm3AdventureStackSnapshot { UnitSid = UnitSid, Stacks = Stacks };
	}
}

internal sealed class Homm3AdventureOccupancySnapshot
{
	internal int EntityId;
	internal int Node;
	internal string Kind;
	internal int StartValue;
	internal bool Alive = true;

	internal Homm3AdventureOccupancySnapshot Clone()
	{
		return new Homm3AdventureOccupancySnapshot
		{
			EntityId = EntityId,
			Node = Node,
			Kind = Kind,
			StartValue = StartValue,
			Alive = Alive,
		};
	}
}
