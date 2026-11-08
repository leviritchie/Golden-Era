using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Live world adapter for the adventure AI bridge. This intentionally reads the native
/// MapData/session DTO surfaces already used by the AI screen dump instead of manufacturing
/// a planner grid from marks or managed Unity objects.
/// </summary>
internal static partial class Homm3AiDriverBridge
{
	internal static bool TryCaptureAdventureLiveWorld(
		Homm3AdventureLookaheadState state,
		out string report)
	{
		if (state == null)
		{
			report = "state=null";
			return false;
		}
		try
		{
			return TryCaptureAdventureLiveWorldCore(state, out report);
		}
		catch (Exception ex)
		{
			var message = "adapter exception: " + ex.GetType().Name + ": " + (ex.Message ?? "unknown");
			state.LiveMapCaptured = false;
			state.LiveOccupancyCaptured = false;
			state.MoveCostProvisional = false;
			state.LiveMapCaptureError = message;
			state.LiveOccupancyCaptureError = message;
			report = "FAILED_CLOSED:" + message;
			state.CaptureNotes = string.IsNullOrEmpty(state.CaptureNotes)
				? report
				: state.CaptureNotes + ";" + report;
			return false;
		}
	}

	private static bool TryCaptureAdventureLiveWorldCore(
		Homm3AdventureLookaheadState state,
		out string report)
	{
		report = null;

		var notes = new List<string>();
		object mapData = null;
		if (!TryResolveAdventureMapContext(out _, out mapData, out var mapReason))
		{
			state.LiveMapCaptureError = mapReason ?? "map context unresolved";
			notes.Add("map=FAILED_CLOSED:" + state.LiveMapCaptureError);
		}
		else if (!TryCaptureLiveMap(state, mapData, out var mapError))
		{
			state.LiveMapCaptureError = mapError ?? "map arrays unresolved";
			notes.Add("map=FAILED_CLOSED:" + state.LiveMapCaptureError);
		}
		else
		{
			notes.Add("map=live_full_grid_under_cap");
		}

		if (!TryCaptureLiveHeroes(state, out var heroReport))
			notes.Add("heroes=FAILED_CLOSED:" + (heroReport ?? "pose unresolved"));
		else
			notes.Add("heroes=" + heroReport);

		if (!TryCaptureLiveOccupancy(state, mapData, out var occupancyReport))
		{
			state.SetLiveOccupancyCaptureResult(false, occupancyReport ?? "session occupancy unresolved");
			notes.Add("occupancy=FAILED_CLOSED:" + state.LiveOccupancyCaptureError);
		}
		else
		{
			state.SetLiveOccupancyCaptureResult(true, null);
			notes.Add("occupancy=" + occupancyReport);
		}

		report = string.Join(";", notes.ToArray());
		state.CaptureNotes = string.IsNullOrEmpty(state.CaptureNotes)
			? report
			: state.CaptureNotes + ";" + report;
		return state.LiveMapCaptured && state.LiveOccupancyCaptured && HasCompleteLiveHeroPoses(state);
	}

	private static bool TryCaptureLiveMap(
		Homm3AdventureLookaheadState state,
		object mapData,
		out string error)
	{
		error = null;
		if (mapData == null)
		{
			error = "mapData=null";
			return false;
		}
		if (!TryReadLiveInt(mapData, GameSymbols.AdventureAiDecision.LiveMapSizeXMembers, out var sizeX)
			|| !TryReadLiveInt(mapData, GameSymbols.AdventureAiDecision.LiveMapSizeZMembers, out var sizeZ))
		{
			error = "MapData sizeX/sizeZ unresolved";
			return false;
		}
		if (sizeX <= 0 || sizeZ <= 0
			|| (long)sizeX * sizeZ > GameSymbols.AdventureAiDecision.MaxLiveMapCells)
		{
			error = "MapData dimensions outside live capture cap";
			return false;
		}
		var cells = sizeX * sizeZ;
		if (!TryReadLiveBytes(mapData, GameSymbols.AdventureAiDecision.LiveMapTilesMembers, cells, out var terrain, out error))
			return false;
		if (!TryReadLiveBytes(mapData, GameSymbols.AdventureAiDecision.LiveMapRoadsMembers, cells, out var road, out error))
			return false;
		if (!TryReadLiveBytes(mapData, GameSymbols.AdventureAiDecision.LiveMapWaterMembers, cells, out var water, out error))
			return false;
		return state.SetLiveMap(sizeX, sizeZ, terrain, road, water, out error);
	}

	private static bool TryCaptureLiveHeroes(
		Homm3AdventureLookaheadState state,
		out string report)
	{
		report = null;
		if (!TryResolveSessionDataRoot(out var dataRoot, out var dataSource) || dataRoot == null)
		{
			report = "sessionDataRoot unresolved";
			return false;
		}

		var resolved = 0;
		var poseCount = 0;
		for (var i = 0; i < state.Heroes.Count; i++)
		{
			var snapshot = state.Heroes[i];
			if (snapshot == null || snapshot.HeroId < 0)
				continue;
			object dataHero = null;
			try
			{
				if (!TryFindSessionDataHero(dataRoot, snapshot.HeroId, null, out dataHero, out _))
					TryFindDataHeroInRoot(dataRoot, snapshot.HeroId, out dataHero);
			}
			catch
			{
				dataHero = null;
			}
			if (dataHero == null)
				continue;
			try
			{
				if (state.TryApplyDataHero(dataHero))
					resolved++;
			}
			catch
			{
				// Validation below keeps an unresolved pose out of the apply path.
			}
		}

		for (var i = 0; i < state.Heroes.Count; i++)
			if (state.Heroes[i] != null && state.Heroes[i].HasLivePose)
				poseCount++;
		var complete = HasCompleteLiveHeroPoses(state);
		report = resolved.ToString(CultureInfo.InvariantCulture)
			+ "/" + state.Heroes.Count.ToString(CultureInfo.InvariantCulture)
			+ "_resolved "
			+ poseCount.ToString(CultureInfo.InvariantCulture)
			+ "/" + state.Heroes.Count.ToString(CultureInfo.InvariantCulture)
			+ "_pose source=" + dataSource;
		return complete;
	}

	private static bool HasCompleteLiveHeroPoses(Homm3AdventureLookaheadState state)
	{
		if (state == null || state.Heroes == null || state.Heroes.Count == 0)
			return false;
		for (var i = 0; i < state.Heroes.Count; i++)
		{
			var hero = state.Heroes[i];
			if (hero == null || !hero.HasLivePose)
				return false;
		}
		return true;
	}

	private static bool TryFindDataHeroInRoot(object dataRoot, int heroId, out object dataHero)
	{
		dataHero = null;
		if (dataRoot == null || heroId < 0)
			return false;
		var heroesContainer = ReadFirstMemberValue(
			dataRoot,
			GameSymbols.AdventureAiDecision.DataRootHeroesMembers);
		if (heroesContainer == null)
			return false;
		var entries = ReadFirstMemberValue(
			heroesContainer,
			GameSymbols.AdventureAiDecision.DataHeroesAllMembers)
			?? heroesContainer;
		foreach (var entry in EnumerateIl2CppListForDump(entries))
		{
			var candidate = LooksLikeDataHero(entry) ? entry : ResolveDataHeroFromSideEntry(entry);
			if (!TryReadLiveInt(candidate, GameSymbols.AdventureAiDecision.DataHeroIdFieldHints, out var id)
			|| id != heroId)
				continue;
			dataHero = candidate;
			return true;
		}
		return false;
	}

	private sealed class LiveMapObjectPlacement
	{
		internal int Node;
	}

	private static bool TryCaptureLiveOccupancy(
		Homm3AdventureLookaheadState state,
		object mapData,
		out string report)
	{
		report = null;
		if (mapData == null)
		{
			report = "mapData=null";
			return false;
		}
		if (!TryBuildMapObjectPlacements(mapData, out var placements, out var mapObjectError))
		{
			report = mapObjectError ?? "mapData.objects unresolved";
			return false;
		}
		if (!TryResolveSessionDataRoot(out var dataRoot, out var dataSource) || dataRoot == null)
		{
			report = "sessionDataRoot unresolved";
			return false;
		}
		var seen = new HashSet<int>();
		var squadContainer = ReadFirstMemberValue(
			dataRoot,
			GameSymbols.AdventureAiDecision.DataRootSquadsMembers);
		var squadEntries = squadContainer == null
			? null
			: ReadFirstMemberValue(squadContainer, GameSymbols.AdventureAiDecision.DataSquadsAllMembers)
				?? squadContainer;
		if (squadEntries == null)
		{
			report = "Data.squads.list unresolved";
			return false;
		}
		var squads = 0;
		foreach (var row in EnumerateIl2CppListForDump(squadEntries))
		{
			if (!TryReadLiveInt(row, GameSymbols.AdventureAiDecision.DataSquadIdFieldHints, out var id)
				|| !TryReadLiveInt(row, GameSymbols.AdventureAiDecision.DataSquadNodeFieldHints, out var node)
				|| !TryReadLiveInt(row, GameSymbols.AdventureAiDecision.DataSquadStartValueFieldHints, out var startValue)
				|| id <= 0 || node < 0)
				continue;
			var released = TryReadLiveBool(row, GameSymbols.AdventureAiDecision.DataSquadReleasedFieldHints, out var isReleased)
				&& isReleased;
			if (released)
				continue;
			var sid = ReadFirstStringMember(row, GameSymbols.AdventureAiDecision.DataSquadConfigSidMembers);
			var npc = ReadFirstBoolMember(row, GameSymbols.AdventureAiDecision.DataSquadNpcMembers);
			if ((!npc.HasValue || !npc.Value) && !LooksLikeNeutralSid(sid))
				continue;
			if (!seen.Add(id))
				continue;
			state.AddOccupant(id, node, "neutral", startValue, true);
			squads++;
		}

		var objectContainer = ReadFirstMemberValue(
			dataRoot,
			GameSymbols.AdventureAiDecision.DataRootObjectsMembers);
		var objectEntries = objectContainer == null
			? null
			: ReadFirstMemberValue(objectContainer, GameSymbols.AdventureAiDecision.DataObjectsAllMembers)
				?? objectContainer;
		if (objectEntries == null)
		{
			report = "Data.objects.all unresolved";
			return false;
		}
		var objects = 0;
		foreach (var row in EnumerateIl2CppListForDump(objectEntries))
		{
			if (!TryReadLiveInt(row, GameSymbols.AdventureAiDecision.DataObjectMapIdMembers, out var mapId)
				|| !placements.TryGetValue(mapId, out var placement)
				|| mapId <= 0 || placement.Node < 0)
				continue;
			if (TryReadLiveBool(row, GameSymbols.AdventureAiDecision.DataObjectReleasedMembers, out var released)
				&& released)
				continue;
			if (!TryReadLiveInt(row, GameSymbols.AdventureAiDecision.DataObjectAiValueMembers, out var aiValue))
				continue;
			var sid = ReadFirstStringMember(row, GameSymbols.AdventureAiDecision.DataObjectConfigSidMembers);
			var neutral = ReadFirstBoolMember(row, GameSymbols.AdventureAiDecision.DataObjectNeutralMembers) == true;
			var kind = ClassifyLiveObject(sid, neutral);
			if (kind == null || !seen.Add(mapId))
				continue;
			state.AddOccupant(mapId, placement.Node, kind, aiValue, true);
			objects++;
		}

		report = "squads=" + squads.ToString(CultureInfo.InvariantCulture)
			+ ";objects=" + objects.ToString(CultureInfo.InvariantCulture)
			+ ";placements=" + placements.Count.ToString(CultureInfo.InvariantCulture)
			+ ";source=" + dataSource;
		return true;
	}

	private static bool TryBuildMapObjectPlacements(
		object mapData,
		out Dictionary<int, LiveMapObjectPlacement> placements,
		out string error)
	{
		placements = new Dictionary<int, LiveMapObjectPlacement>();
		error = null;
		var rows = ReadFirstMemberValue(
			mapData,
			GameSymbols.AdventureAiDecision.LiveMapObjectsMembers)
			?? ReadFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (rows == null)
		{
			error = "MapData.objects missing";
			return false;
		}
		foreach (var row in EnumerateIl2CppListForDump(rows))
		{
			var ids = ReadMapDataObjectIds(row);
			var nodes = ReadMapDataObjectNodes(row);
			var count = Math.Min(ids.Count, nodes.Count);
			for (var i = 0; i < count; i++)
			{
				if (ids[i] <= 0 || nodes[i] < 0)
					continue;
				placements[ids[i]] = new LiveMapObjectPlacement
				{
					Node = nodes[i],
				};
			}
		}
		return true;
	}

	private static string ClassifyLiveObject(string sid, bool neutral)
	{
		if (neutral || LooksLikeNeutralSid(sid))
			return "neutral";
		if (ContainsAny(sid, "town", "city"))
			return "town";
		if (ContainsAny(sid, "mine"))
			return "mine";
		if (ContainsAny(sid, "resource", "pickup", "item", "chest"))
			return "pickup";
		return null;
	}

	private static bool LooksLikeNeutralSid(string sid)
	{
		return ContainsAny(sid, "neutral", "squad", "monster", "guard", "creature");
	}

	private static bool ContainsAny(string value, params string[] needles)
	{
		if (string.IsNullOrEmpty(value) || needles == null)
			return false;
		for (var i = 0; i < needles.Length; i++)
			if (value.IndexOf(needles[i], StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		return false;
	}

	private static bool TryReadLiveInt(object obj, string[] members, out int value)
	{
		value = 0;
		var raw = ReadFirstMemberValue(obj, members);
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

	private static bool TryReadLiveBool(object obj, string[] members, out bool value)
	{
		value = false;
		var raw = ReadFirstMemberValue(obj, members);
		if (raw == null)
			return false;
		try
		{
			value = Convert.ToBoolean(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadLiveBytes(
		object owner,
		string[] members,
		int expected,
		out byte[] values,
		out string error)
	{
		values = null;
		error = null;
		var raw = ReadFirstMemberValue(owner, members);
		if (raw == null)
		{
			error = "map array member missing";
			return false;
		}
		if (raw is byte[] bytes)
		{
			if (bytes.Length != expected)
			{
				error = "map array length=" + bytes.Length.ToString(CultureInfo.InvariantCulture)
					+ " expected=" + expected.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			values = (byte[])bytes.Clone();
			return true;
		}
		var list = new List<byte>(expected);
		if (raw is Array array)
		{
			for (var i = 0; i < array.Length; i++)
			{
				if (!TryConvertByte(array.GetValue(i), out var item))
				{
					error = "map array contains non-byte value";
					return false;
				}
				list.Add(item);
			}
		}
		else if (raw is IEnumerable enumerable)
		{
			try
			{
				foreach (var item in enumerable)
				{
					if (!TryConvertByte(item, out var value))
					{
						error = "map enumerable contains non-byte value";
						return false;
					}
					list.Add(value);
				}
			}
			catch
			{
				list.Clear();
			}
		}
		if (list.Count != expected)
		{
			var length = ReadFirstMemberValue(raw, new[] { "Length", "Count" });
			if (length == null || !TryReadIndexedBytes(raw, expected, list))
			{
				error = "map array length unresolved";
				return false;
			}
		}
		values = list.ToArray();
		return true;
	}

	private static bool TryReadIndexedBytes(object raw, int expected, List<byte> values)
	{
		if (raw == null || values == null)
			return false;
		var getter = raw.GetType().GetMethod(
			"get_Item",
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
			null,
			new[] { typeof(int) },
			null);
		if (getter == null)
			return false;
		values.Clear();
		for (var i = 0; i < expected; i++)
		{
			object item;
			try { item = getter.Invoke(raw, new object[] { i }); }
			catch { return false; }
			if (!TryConvertByte(item, out var value))
				return false;
			values.Add(value);
		}
		return true;
	}

	private static bool TryConvertByte(object raw, out byte value)
	{
		value = 0;
		if (raw == null)
			return false;
		try
		{
			value = Convert.ToByte(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}
}