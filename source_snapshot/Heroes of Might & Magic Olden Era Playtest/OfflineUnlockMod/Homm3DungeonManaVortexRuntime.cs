using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using DataBuff = Hex.Session.Data.Buff;
using DataBuffDuration = Hex.Session.Data.BuffDuration;
using DataHero = Hex.Session.Data.Hero;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataRoot = Hex.Session.Data.Data;
using DataSide = Hex.Session.Data.Side;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (docs/building_pass_20261122/dungeon.md P5): Dungeon Mana Vortex.
///
/// The building is the native <c>manaFountains</c> row <c>Build_Well_Of_Souls</c> in <c>homm3_dungeon_city</c>, so the
/// native visit already refills mana to maximum on every visit. HoMM3's Vortex also doubles the mana of the first
/// visiting hero each week. The native visit handler (logic BuildingManaFountain) is obfuscated with no proven
/// symbol, so this runtime watches the data instead: a per-frame host reads <c>ObjCity.visitorHeroId</c> of every
/// Dungeon town with the building, and when a new hero arrives and the town's weekly double is unused, it sets
/// that hero's <c>mana</c> to twice its current value once the arrival has settled (the native refill has run, so
/// the result is 2 x maximum) and marks the town for the week.
///
/// Save: the per-town week marks ride in one hidden, bonus-less side buff (<see cref="StoreBuffSid"/>, a Core row
/// requested in docs/building_pass_20261122/build_ind.md), the Factory/Cove carrier pattern. Records:
/// VER, then (CITY id, WEEK id) pairs for the current week only, then SUM (FNV-1a of the rest). A carrier that fails
/// its checks is never overwritten; the session then runs unsaved. Writes happen from the host's Update only, and are
/// read back.
///
/// Limits: an arrival that leaves within the settle window (fast AI passes) is still paid as long as the hero was
/// seen as the visitor; a hero who teleports out in the same frame he arrived is missed. The write is from the UI
/// host, not deterministic side logic (same as War Captives). After loading a save, a hero already standing in a
/// town is not paid (the first observation only seeds).
/// </summary>
internal static class Homm3DungeonManaVortexRuntime
{
	internal const string DungeonCitySid = "homm3_dungeon_city";
	internal const string VortexBuildingSid = "Build_Well_Of_Souls";
	internal const string StoreBuffSid = "homm3_ind_town_building_store";

	private const float SettleSeconds = 0.35f;
	private const float RescanSeconds = 1f;
	private const int StoreVersion = 1;
	private const int RecMarker = 0x40000000;
	private const int RecTypeShift = 26;
	private const int RecDataMask = 0x3FFFFFF;
	private const int TVer = 1, TCity = 2, TWeek = 3, TSum = 15;

	private sealed class Watch
	{
		internal int CityId;
		internal int OwnerSide;
		internal DataObjCity City;
		internal int LastVisitor = -1;
		internal bool Seeded;
		internal int Pending = -1;
		internal float PendingSince;
	}

	private static ManualLogSource _log;
	private static bool _registered, _hostTypeRegistered;
	private static GameObject _hostObject;
	private static IntPtr _sessionPtr;
	private static readonly Dictionary<int, Watch> _watches = new();
	private static readonly Dictionary<int, int> _paidWeek = new(); // city id -> week id
	private static float _nextRescan;
	private static int _currentWeek;
	private static bool _loaded;
	private static string _saveBlocked;
	private static bool _dirty;
	private static List<int> _savedRecords;
	private static int _saveSide = -1;
	private static float _nextSave;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		_log = log;
		_registered = true;
		EnsureHost();
	}

	private static void EnsureHost()
	{
		if (_hostObject != null)
			return;
		try
		{
			if (!_hostTypeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3DungeonManaVortexHost>();
				_hostTypeRegistered = true;
			}
			_hostObject = new GameObject("Homm3DungeonManaVortexHost");
			UnityObject.DontDestroyOnLoad(_hostObject);
			_hostObject.AddComponent<Homm3DungeonManaVortexHost>();
			_log?.LogInfo("HoMM3 Dungeon Mana Vortex: host created.");
		}
		catch (Exception ex)
		{
			_hostObject = null;
			_log?.LogWarning("HoMM3 Dungeon Mana Vortex: host failed (" + ex.GetBaseException().Message + "); Mana Vortex only refills mana.");
		}
	}

	internal static void HostDestroyed() => _hostObject = null;

	// ---------------------------------------------------------------- per frame

	internal static void Tick()
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out DataRoot data, out _) || data == null || data.Pointer == IntPtr.Zero)
			return;
		var now = Time.realtimeSinceStartup;
		if (data.Pointer != _sessionPtr)
			ResetSession(data.Pointer);
		if (!_loaded)
			LoadSaved(data);

		var week = ((data.month & 0x7FF) << 3 | (data.week & 7)) + 1;
		if (week != _currentWeek)
		{
			_currentWeek = week;
			var stale = new List<int>();
			foreach (var pair in _paidWeek)
				if (pair.Value != week)
					stale.Add(pair.Key);
			foreach (var id in stale)
				_paidWeek.Remove(id);
			if (stale.Count > 0)
				_dirty = true;
		}

		if (now >= _nextRescan)
		{
			_nextRescan = now + RescanSeconds;
			Rescan(data);
		}

		foreach (var watch in _watches.Values)
			Observe(watch, now);

		if (_dirty && now >= _nextSave)
			FlushSave(data, now);
	}

	private static void ResetSession(IntPtr ptr)
	{
		_sessionPtr = ptr;
		_watches.Clear();
		_paidWeek.Clear();
		_currentWeek = 0;
		_loaded = false;
		_saveBlocked = null;
		_dirty = false;
		_savedRecords = null;
		_saveSide = -1;
		_nextRescan = 0f;
		_nextSave = 0f;
	}

	private static void Rescan(DataRoot data)
	{
		var seen = new HashSet<int>();
		var list = data.objects?.cityObjs;
		for (var i = 0; list != null && i < list.Count; i++)
		{
			var city = list[i];
			if (city == null || city.ownerSide < 0)
				continue;
			if (!Homm3TownBuildingReader.CityHasBuilding(city, VortexBuildingSid) || !Homm3TownBuildingReader.CityMatchesSid(city, DungeonCitySid))
				continue;
			seen.Add(city.idMapObject);
			if (!_watches.TryGetValue(city.idMapObject, out var watch) || watch.OwnerSide != city.ownerSide)
			{
				// New, or captured: the new owner's first observation only seeds (no pay for a hero already inside).
				watch = new Watch { CityId = city.idMapObject, OwnerSide = city.ownerSide };
				_watches[city.idMapObject] = watch;
			}
			watch.City = city;
		}
		var gone = new List<int>();
		foreach (var id in _watches.Keys)
			if (!seen.Contains(id))
				gone.Add(id);
		foreach (var id in gone)
			_watches.Remove(id);
	}

	private static void Observe(Watch watch, float now)
	{
		int visitor;
		try
		{
			visitor = watch.City?.visitorHeroId ?? -1;
		}
		catch
		{
			return;
		}
		if (!watch.Seeded)
		{
			watch.Seeded = true;
			watch.LastVisitor = visitor;
			return;
		}
		if (visitor != watch.LastVisitor)
		{
			watch.LastVisitor = visitor;
			if (visitor >= 0)
			{
				watch.Pending = visitor;
				watch.PendingSince = now;
			}
		}
		if (watch.Pending < 0 || now - watch.PendingSince < SettleSeconds)
			return;
		var heroId = watch.Pending;
		watch.Pending = -1;
		if (!_loaded || _currentWeek <= 0)
			return;
		if (_paidWeek.TryGetValue(watch.CityId, out var paid) && paid == _currentWeek)
			return;
		if (!TryDoubleMana(watch, heroId, out var before, out var after, out var fail))
		{
			if (_logged++ < 12)
				_log?.LogWarning("HoMM3 Dungeon Mana Vortex: city " + watch.CityId + " hero " + heroId + " not doubled (" + fail + ").");
			return;
		}
		_paidWeek[watch.CityId] = _currentWeek;
		_dirty = true;
		if (_logged++ < 24)
			_log?.LogInfo("HoMM3 Dungeon Mana Vortex: city " + watch.CityId + " doubled hero " + heroId + " mana " + before + " -> " + after + " (week " + _currentWeek + ").");
	}

	private static bool TryDoubleMana(Watch watch, int heroId, out int before, out int after, out string fail)
	{
		before = after = 0;
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out fail) || world == null)
			return false;
		foreach (DataHero hero in Homm3FactoryLogisticsEffects.SideHeroes(world, watch.OwnerSide))
		{
			if (hero == null || Homm3FactoryLogisticsEffects.HeroId(hero) != heroId)
				continue;
			before = hero.mana;
			if (before <= 0)
			{
				fail = "hero has no mana to double";
				return false;
			}
			after = before > int.MaxValue / 2 ? int.MaxValue : before * 2;
			hero.mana = after;
			if (hero.mana != after)
			{
				fail = "mana write did not stick";
				return false;
			}
			fail = null;
			return true;
		}
		fail = "visitor hero not found on side " + watch.OwnerSide;
		return false;
	}

	// ---------------------------------------------------------------- save carrier

	private static int Rec(int type, int data) => RecMarker | (type << RecTypeShift) | (data & RecDataMask);

	private static int Checksum(List<int> records, int count)
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

	private static List<int> ReadRaws(DataBuff carrier)
	{
		var durations = carrier?.durations;
		if (durations == null || durations.Length == 0)
			return null;
		var raws = new List<int>(durations.Length);
		for (var i = 0; i < durations.Length; i++)
		{
			var d = durations[i];
			if (d == null)
				return null;
			raws.Add(d.leftValue);
		}
		return raws;
	}

	private static void LoadSaved(DataRoot data)
	{
		var sides = data.sides?.array;
		if (sides == null)
			return; // sides not readable yet; try again next frame
		_loaded = true;
		foreach (var side in sides)
		{
			var carrier = FindStore(side);
			if (carrier == null)
				continue;
			_saveSide = side.index;
			var raws = ReadRaws(carrier);
			if (!TryDecode(raws, out var weeks, out var fail))
			{
				_saveBlocked = fail;
				_log?.LogWarning("HoMM3 Dungeon Mana Vortex: saved carrier on side " + side.index + " rejected (" + fail + "); weekly marks run unsaved this session and the carrier is left untouched.");
				return;
			}
			foreach (var pair in weeks)
				_paidWeek[pair.Key] = pair.Value;
			_savedRecords = raws;
			_log?.LogInfo("HoMM3 Dungeon Mana Vortex: loaded " + weeks.Count + " weekly mark(s) from side " + side.index + ".");
			return;
		}
	}

	private static bool TryDecode(List<int> raws, out Dictionary<int, int> weeks, out string fail)
	{
		weeks = new Dictionary<int, int>();
		fail = null;
		if (raws == null || raws.Count < 2)
		{
			fail = "too few records";
			return false;
		}
		foreach (var raw in raws)
		{
			if ((raw & ~0x7FFFFFFF) != 0 || (raw & RecMarker) == 0)
			{
				fail = "record without marker";
				return false;
			}
		}
		int Type(int r) => (r >> RecTypeShift) & 0xF;
		int Data(int r) => r & RecDataMask;
		if (Type(raws[0]) != TVer || Data(raws[0]) != StoreVersion)
		{
			fail = "version " + Data(raws[0]) + " (type " + Type(raws[0]) + ")";
			return false;
		}
		var last = raws[raws.Count - 1];
		if (Type(last) != TSum || Data(last) != Checksum(raws, raws.Count - 1))
		{
			fail = "checksum mismatch";
			return false;
		}
		for (var i = 1; i < raws.Count - 1; i += 2)
		{
			if (i + 1 >= raws.Count - 1 || Type(raws[i]) != TCity || Type(raws[i + 1]) != TWeek)
			{
				fail = "malformed pair at record " + i;
				return false;
			}
			weeks[Data(raws[i])] = Data(raws[i + 1]);
		}
		return true;
	}

	private static List<int> Encode()
	{
		var records = new List<int> { Rec(TVer, StoreVersion) };
		var ids = new List<int>(_paidWeek.Keys);
		ids.Sort();
		foreach (var id in ids)
		{
			records.Add(Rec(TCity, id));
			records.Add(Rec(TWeek, _paidWeek[id]));
		}
		records.Add(Rec(TSum, Checksum(records, records.Count)));
		return records;
	}

	private static bool SameRecords(List<int> a, List<int> b)
	{
		if (a == null || b == null || a.Count != b.Count)
			return false;
		for (var i = 0; i < a.Count; i++)
			if (a[i] != b[i])
				return false;
		return true;
	}

	private static void FlushSave(DataRoot data, float now)
	{
		_nextSave = now + 1f;
		if (_saveBlocked != null || !_loaded)
		{
			_dirty = false;
			return;
		}
		try
		{
			var records = Encode();
			if (SameRecords(records, _savedRecords))
			{
				_dirty = false;
				return;
			}
			var sides = data.sides?.array;
			if (sides == null)
				return;
			DataSide target = null;
			foreach (var side in sides)
			{
				if (side?.buffs?.list == null)
					continue;
				if (_saveSide < 0 || side.index == _saveSide)
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
			if (!SameRecords(ReadRaws(FindStore(target)), records))
			{
				SaveFailed(now, "read-back mismatch");
				return;
			}
			_saveSide = target.index;
			_savedRecords = records;
			_dirty = false;
		}
		catch (Exception ex)
		{
			SaveFailed(now, "write threw " + ex.GetBaseException().Message);
		}
	}

	private static void SaveFailed(float now, string why)
	{
		_nextSave = now + 30f;
		if (_logged++ < 24)
			_log?.LogWarning("HoMM3 Dungeon Mana Vortex: weekly marks not saved (" + why + "); retrying in 30 s.");
	}
}

public sealed class Homm3DungeonManaVortexHost : MonoBehaviour
{
	public Homm3DungeonManaVortexHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		try
		{
			Homm3DungeonManaVortexRuntime.Tick();
		}
		catch
		{
			// never break the frame
		}
	}

	private void OnDestroy() => Homm3DungeonManaVortexRuntime.HostDestroyed();
}
