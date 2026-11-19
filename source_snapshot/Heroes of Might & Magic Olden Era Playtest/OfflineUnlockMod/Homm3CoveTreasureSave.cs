using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using DataBuff = Hex.Session.Data.Buff;
using DataBuffDuration = Hex.Session.Data.BuffDuration;
using DataRoot = Hex.Session.Data.Data;
using DataSide = Hex.Session.Data.Side;
using Plan = OfflineUnlockMod.Homm3CoveTreasurePlan;

namespace OfflineUnlockMod;

/// <summary>
/// Save persistence for Treasure Hunting. Same carrier pattern as <see cref="Homm3FactoryLogisticsState"/>: one hidden,
/// bonus-less side buff (<see cref="StoreBuffSid"/>, a Core row) whose durations hold the records, so the state rides
/// in the game's own save file. One carrier per map, on whichever side already has it (else the first side).
///
/// What is stored, per planned region: the five piece holders (tile, kind, loose) with who revealed and collected
/// them, the treasure tile and false leads, the value, pieces per side, dug state, Archivist and visited sides; plus
/// every hole. The plan is stored and not re-derived because the holder pool is read from live map objects, which
/// change as the game is played.
///
/// A carrier that fails its checks is never overwritten: the map then plays from a fresh state, unsaved.
/// </summary>
internal static partial class Homm3CoveTreasureRuntime
{
	internal const string StoreBuffSid = "homm3_cove_treasure_store";

	// Version 1 stored treasure values from before they were doubled (2026-11-17); they are doubled on load.
	// Version 2 stored values from before the 8000 base (2026-11-18); it is added on load.
	private const int StoreVersion = 3;
	private const int RecMarker = 0x40000000;
	private const int RecTypeShift = 26;
	private const int RecDataMask = 0x3FFFFFF;
	private const int SideMask = 0xFFF;
	private const int NodeLimit = 1 << 20;

	private const int TVer = 1, TMap = 2, TRegion = 3, TSides = 4, TTrue = 5, TFalse = 6, TCount = 7, THolder = 8, THolderState = 9,
		THole = 10, TValue = 11, TSum = 15;

	private sealed class SavedHolder
	{
		internal int Node;
		internal byte Kind;
		internal bool Guarded, Loose;
		internal uint Revealed, Collected;
	}

	private sealed class SavedRegion
	{
		internal int AreaId;
		internal bool Dug;
		internal int DugSide = -1;
		internal uint Archivist, Visited;
		internal int TrueNode = -1;
		internal int Value = -1;
		internal readonly List<int> FalseNodes = new();
		internal readonly Dictionary<int, int> Pieces = new();
		internal readonly List<SavedHolder> Holders = new();
	}

	private static float _nextSaveFlush;
	private static bool _saveWarned;

	private static int Rec(int type, int data) => RecMarker | (type << RecTypeShift) | (data & RecDataMask);

	private static int StoreChecksum(List<int> records, int count)
	{
		unchecked
		{
			var h = 2166136261u;
			for (var i = 0; i < count; i++)
			{
				var v = (uint)records[i];
				for (var b = 0; b < 4; b++)
				{
					h ^= (v >> (8 * b)) & 0xFF;
					h *= 16777619u;
				}
			}
			return (int)(h & RecDataMask);
		}
	}

	private static int SeedTag(ulong seed) => (int)((seed ^ (seed >> 26) ^ (seed >> 52)) & RecDataMask);

	private static DataBuff FindStore(DataSide side)
	{
		var list = side?.buffs?.list;
		if (list == null)
			return null;
		for (var i = 0; i < list.Count; i++)
		{
			var buff = list[i];
			if (buff != null && string.Equals(Homm3TowerArtificingRuntime.ReadMember(buff, GameSymbols.DungeonCaptives.DataBuffSidMembers) as string, StoreBuffSid, StringComparison.Ordinal))
				return buff;
		}
		return null;
	}

	private static bool TryWriteStoreSid(DataBuff buff)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in GameSymbols.DungeonCaptives.DataBuffSidMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var prop = typeof(DataBuff).GetProperty(name, flags);
			if (prop != null && prop.PropertyType == typeof(string) && prop.CanWrite)
			{
				prop.SetValue(buff, StoreBuffSid);
				if (string.Equals(prop.GetValue(buff) as string, StoreBuffSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	// ---------------------------------------------------------------- load

	/// <summary>Reads the carrier once per map. Leaves <c>SaveLoaded</c> false while the sides cannot be read yet.</summary>
	private static void LoadSaved(DataRoot data, MapState map)
	{
		if (map.SaveLoaded || map.SaveBlocked != null)
			return;
		try
		{
			var sides = data.sides?.array;
			if (sides == null)
				return;
			DataBuff carrier = null;
			var readable = 0;
			foreach (var side in sides)
			{
				if (side?.buffs?.list == null)
					continue;
				readable++;
				var found = FindStore(side);
				if (found == null)
					continue;
				carrier = found;
				map.SaveSide = side.index;
				break;
			}
			if (readable == 0)
				return;
			if (carrier == null)
			{
				map.SaveLoaded = true;
				Info("save: no stored treasure state on this map yet.");
				return;
			}
			var raws = ReadRaws(carrier, out var why);
			if (raws == null || !TryDecode(raws, map, out var regions, out var holes, out why))
			{
				map.SaveBlocked = why ?? "unreadable";
				Warn("save: stored treasure state rejected (" + map.SaveBlocked + "). This map plays from a fresh state and is not saved, so the stored records stay untouched.");
				return;
			}
			map.Saved = regions;
			foreach (var hole in holes)
				map.Holes.Add(hole);
			map.SavedRecords = raws;
			map.SaveLoaded = true;
			Version++;
			Info("save: loaded " + N(regions.Count) + " region(s), " + N(holes.Count) + " hole(s) from side " + N(map.SaveSide) + " (" + N(raws.Count) + " records).");
		}
		catch (Exception ex)
		{
			map.SaveBlocked = "load threw " + ex.GetBaseException().Message;
			Warn("save: " + map.SaveBlocked + ". This map is not saved.");
		}
	}

	/// <summary>Plans every stored region as soon as the map allows it. Saving waits until none is left.</summary>
	private static void MaterializeSaved(MapState map)
	{
		if (map.Saved == null || map.Saved.Count == 0)
			return;
		foreach (var areaId in new List<int>(map.Saved.Keys))
		{
			if (!map.Areas.ContainsKey(areaId))
			{
				map.Saved.Remove(areaId);
				Warn("save: stored region " + N(areaId) + " is not on this map; dropped.");
				continue;
			}
			EnsureRegion(map, areaId);
		}
	}

	private static SavedRegion TakeSaved(MapState map, int areaId)
	{
		if (map.Saved == null || !map.Saved.TryGetValue(areaId, out var saved))
			return null;
		map.Saved.Remove(areaId);
		return saved;
	}

	/// <summary>Replaces the freshly built plan's tiles and holders with the stored ones.</summary>
	private static void ApplySavedPlan(MapState map, Plan.RegionPlan plan, SavedRegion saved, IReadOnlyList<Plan.Holder> candidates)
	{
		plan.TrueNode = saved.TrueNode;
		plan.FalseNodes = saved.FalseNodes.ToArray();
		var pieces = new Plan.Holder[saved.Holders.Count];
		for (var i = 0; i < pieces.Length; i++)
		{
			var s = saved.Holders[i];
			var holder = new Plan.Holder { Node = s.Node, Key = s.Node, Kind = Plan.HolderLoose, Guarded = s.Guarded };
			if (!s.Loose && s.Kind != Plan.HolderLoose && candidates != null)
			{
				foreach (var c in candidates)
				{
					if (c.Node != s.Node || c.Kind != s.Kind)
						continue;
					holder = c;
					break;
				}
			}
			pieces[i] = holder;
		}
		plan.Pieces = pieces;
		if (saved.Value >= 0 && saved.Value != plan.Value)
		{
			plan.Value = saved.Value;
			plan.Contents = Plan.RollContents(Plan.ContentsRng(map.Seed, plan.RegionId), plan.Value, map.Catalog ?? new Plan.Catalog());
		}
	}

	private static void ApplySavedState(RegionState region, SavedRegion saved)
	{
		region.Dug = saved.Dug;
		region.DugSide = saved.Dug ? saved.DugSide : -1;
		region.ArchivistSides = saved.Archivist;
		region.VisitedSides = saved.Visited;
		foreach (var pair in saved.Pieces)
			region.PiecesBySide[pair.Key] = pair.Value;
		for (var i = 0; i < region.Holders.Length && i < saved.Holders.Count; i++)
		{
			var h = region.Holders[i];
			var s = saved.Holders[i];
			h.RevealedSides = s.Revealed;
			h.CollectedSides = s.Collected;
			// A holder that is gone on load already gave up its piece before the save: no new collection.
			h.Loose = s.Loose || h.Holder.Kind == Plan.HolderLoose || IsTaken(h);
		}
	}

	// ---------------------------------------------------------------- encode / decode

	private static bool TryEncode(MapState map, out List<int> records, out string fail)
	{
		fail = null;
		records = new List<int> { Rec(TVer, StoreVersion), Rec(TMap, SeedTag(map.Seed)) };
		var ids = new List<int>(map.Regions.Keys);
		ids.Sort();
		foreach (var id in ids)
		{
			var r = map.Regions[id];
			if (id < 0 || id > 0xFFF || r.DugSide < -1 || r.DugSide > 30)
			{
				fail = "region " + N(id) + " does not fit the save fields";
				return false;
			}
			if (((r.ArchivistSides | r.VisitedSides) & ~(uint)SideMask) != 0)
			{
				fail = "side index above 11 in region " + N(id);
				return false;
			}
			records.Add(Rec(TRegion, id | (r.Dug ? 1 << 12 : 0) | ((r.DugSide + 1) << 13)));
			records.Add(Rec(TSides, (int)r.ArchivistSides | ((int)r.VisitedSides << 12)));
			records.Add(Rec(TValue, Math.Max(0, Math.Min(RecDataMask, r.Plan.Value))));
			records.Add(Rec(TTrue, r.Plan.TrueNode + 1));
			foreach (var node in r.Plan.FalseNodes)
				records.Add(Rec(TFalse, node));
			var sides = new List<int>(r.PiecesBySide.Keys);
			sides.Sort();
			foreach (var side in sides)
			{
				var count = r.PiecesBySide[side];
				if (side < 0 || side > 31 || count < 0 || count > 255)
				{
					fail = "piece count does not fit the save fields in region " + N(id);
					return false;
				}
				if (count > 0)
					records.Add(Rec(TCount, side | (count << 5)));
			}
			foreach (var h in r.Holders)
			{
				var node = h.Holder.Node;
				if (node < 0 || node >= NodeLimit || h.Holder.Kind > 3 || ((h.RevealedSides | h.CollectedSides) & ~(uint)SideMask) != 0)
				{
					fail = "holder at node " + N(node) + " does not fit the save fields";
					return false;
				}
				records.Add(Rec(THolder, node | (h.Holder.Kind << 20) | (h.Holder.Guarded ? 1 << 22 : 0) | (h.Loose ? 1 << 23 : 0)));
				records.Add(Rec(THolderState, (int)h.RevealedSides | ((int)h.CollectedSides << 12)));
			}
		}
		var holes = new List<int>(map.Holes);
		holes.Sort();
		foreach (var hole in holes)
			records.Add(Rec(THole, hole));
		records.Add(Rec(TSum, StoreChecksum(records, records.Count)));
		return true;
	}

	private static List<int> ReadRaws(DataBuff carrier, out string fail)
	{
		fail = null;
		var durations = carrier.durations;
		if (durations == null || durations.Length == 0)
		{
			fail = "carrier has no records";
			return null;
		}
		var raws = new List<int>(durations.Length);
		for (var i = 0; i < durations.Length; i++)
		{
			var d = durations[i];
			if (d == null)
			{
				fail = "record " + N(i) + " is null";
				return null;
			}
			raws.Add(d.leftValue);
		}
		return raws;
	}

	private static bool TryDecode(List<int> raws, MapState map, out Dictionary<int, SavedRegion> regions, out List<int> holes, out string fail)
	{
		regions = new Dictionary<int, SavedRegion>();
		holes = new List<int>();
		fail = null;
		if (raws.Count < 3)
		{
			fail = "too few records";
			return false;
		}
		var last = raws[raws.Count - 1];
		if (last < 0 || (last & RecMarker) == 0 || ((last >> RecTypeShift) & 0xF) != TSum)
		{
			fail = "no checksum record";
			return false;
		}
		if ((last & RecDataMask) != StoreChecksum(raws, raws.Count - 1))
		{
			fail = "checksum mismatch";
			return false;
		}
		SavedRegion region = null;
		SavedHolder holder = null;
		var legacyValues = false;
		var noBase = false;
		for (var i = 0; i < raws.Count - 1; i++)
		{
			var raw = raws[i];
			if (raw < 0 || (raw & RecMarker) == 0)
			{
				fail = "record " + N(i) + " is not a treasure record";
				return false;
			}
			var type = (raw >> RecTypeShift) & 0xF;
			var data = raw & RecDataMask;
			if (i == 0)
			{
				if (type != TVer || data < 1 || data > StoreVersion)
				{
					fail = "unknown version " + N(data);
					return false;
				}
				legacyValues = data == 1;
				noBase = data < 3;
				continue;
			}
			if (i == 1)
			{
				if (type != TMap || data != SeedTag(map.Seed))
				{
					fail = "stored for a different map";
					return false;
				}
				continue;
			}
			if (type == THole)
			{
				holes.Add(data);
				continue;
			}
			if (type == TRegion)
			{
				region = new SavedRegion { AreaId = data & 0xFFF, Dug = (data & (1 << 12)) != 0, DugSide = ((data >> 13) & 0x1F) - 1 };
				if (regions.ContainsKey(region.AreaId))
				{
					fail = "region " + N(region.AreaId) + " stored twice";
					return false;
				}
				regions[region.AreaId] = region;
				holder = null;
				continue;
			}
			if (region == null)
			{
				fail = "record " + N(i) + " has no region";
				return false;
			}
			switch (type)
			{
				case TSides:
					region.Archivist = (uint)(data & SideMask);
					region.Visited = (uint)((data >> 12) & SideMask);
					break;
				case TValue:
					region.Value = legacyValues ? Math.Min(Plan.MaxValue, data * 2) : data;
					if (noBase)
						region.Value += Plan.BaseValue;
					break;
				case TTrue:
					region.TrueNode = data - 1;
					break;
				case TFalse:
					region.FalseNodes.Add(data);
					break;
				case TCount:
					region.Pieces[data & 0x1F] = (data >> 5) & 0xFF;
					break;
				case THolder:
					holder = new SavedHolder
					{
						Node = data & (NodeLimit - 1),
						Kind = (byte)((data >> 20) & 3),
						Guarded = (data & (1 << 22)) != 0,
						Loose = (data & (1 << 23)) != 0,
					};
					region.Holders.Add(holder);
					break;
				case THolderState:
					if (holder == null)
					{
						fail = "record " + N(i) + " has no holder";
						return false;
					}
					holder.Revealed = (uint)(data & SideMask);
					holder.Collected = (uint)((data >> 12) & SideMask);
					break;
				default:
					fail = "record " + N(i) + " has unknown type " + N(type);
					return false;
			}
		}
		return true;
	}

	// ---------------------------------------------------------------- save

	private static bool SameRecords(List<int> a, List<int> b)
	{
		if (a == null || b == null || a.Count != b.Count)
			return false;
		for (var i = 0; i < a.Count; i++)
			if (a[i] != b[i])
				return false;
		return true;
	}

	/// <summary>
	/// Writes the state into the carrier when it changed. Called from the marker host's Update (never from inside a
	/// native hook), about once a second.
	/// </summary>
	internal static void FlushSave(float now)
	{
		if (now < _nextSaveFlush || _inTick)
			return;
		_nextSaveFlush = now + 1f;
		var map = _map;
		if (map == null || map.Failed || !map.SaveLoaded || map.SaveBlocked != null || (map.Saved != null && map.Saved.Count > 0))
			return;
		if (map.SavedRecords == null && map.Regions.Count == 0 && map.Holes.Count == 0)
			return;
		try
		{
			if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) || data == null || data.Pointer != map.DataPointer)
				return;
			if (!TryEncode(map, out var records, out var fail))
			{
				SaveFailed(now, fail);
				return;
			}
			if (SameRecords(records, map.SavedRecords))
				return;
			var sides = data.sides?.array;
			if (sides == null)
				return;
			DataSide target = null;
			foreach (var side in sides)
			{
				if (side?.buffs?.list == null)
					continue;
				if (map.SaveSide < 0 || side.index == map.SaveSide)
				{
					target = side;
					break;
				}
			}
			if (target == null)
			{
				SaveFailed(now, "no side to store on");
				return;
			}
			var durations = new Il2CppReferenceArray<DataBuffDuration>(records.Count);
			for (var i = 0; i < records.Count; i++)
				durations[i] = new DataBuffDuration(EBuffDurationType.Infinite, records[i]);
			var carrier = FindStore(target);
			if (carrier == null)
			{
				carrier = new DataBuff();
				if (!TryWriteStoreSid(carrier))
				{
					SaveFailed(now, "Buff sid member not writable");
					return;
				}
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;
				carrier.wasApplied = false;
				target.buffs.list.Add(carrier);
			}
			else
			{
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;
			}
			var back = ReadRaws(FindStore(target), out var readFail);
			if (!SameRecords(back, records))
			{
				SaveFailed(now, "read-back mismatch (" + (readFail ?? "records differ") + ")");
				return;
			}
			var first = map.SavedRecords == null;
			map.SaveSide = target.index;
			map.SavedRecords = records;
			if (first)
				Info("save: treasure state stored on side " + N(map.SaveSide) + " (" + N(records.Count) + " records); later changes are stored silently.");
		}
		catch (Exception ex)
		{
			SaveFailed(now, "write threw " + ex.GetBaseException().Message);
		}
	}

	private static void SaveFailed(float now, string why)
	{
		_nextSaveFlush = now + 30f;
		if (_saveWarned)
			return;
		_saveWarned = true;
		_log?.LogWarning(LogPrefix + "save: not stored (" + why + "); retrying every 30 s. Treasure progress will be lost on reload until this clears.");
	}
}
