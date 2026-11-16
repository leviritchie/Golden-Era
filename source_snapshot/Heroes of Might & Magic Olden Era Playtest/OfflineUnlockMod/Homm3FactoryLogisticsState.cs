using System;
using System.Collections.Generic;
using System.Globalization;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using DataBuff = Hex.Session.Data.Buff;
using DataBuffDuration = Hex.Session.Data.BuffDuration;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network per-object state and its save carrier.
///
/// Persistence (proposal A of V:/olden_port_work/factory_logistics/feasibility.md): one hidden, bonus-less logic side
/// buff <c>homm3_factory_logistics_store</c> (Core row in DB/logic_side_buffs, a clone of the native hidden
/// heros_crypt_debuff_none) in each owning human side's Data.Side.buffs list. Its durations array holds the records,
/// each an Infinite duration whose leftValue = 0x40000000 | type &lt;&lt; 26 | 26 data bits:
///   VER  (7): format version (1), first record.
///   OBJ  (1): map object id (DataObject.idMapObject); the records below belong to it until the next OBJ.
///   META (2): Upgrade Center level (2 bits) | active code (5) | pending active code (5) | switch week id (14).
///   PDAY (3): day the pending active switch was requested (applies when today &gt; that day).
///   ENH  (4): code (5) | level (3) | pending remote level (3) | request day (15).
///   XCHG (5): the dwelling's original hire extraCharge in thousandths + 2^25 (restored on wipe/deactivate).
///   POOL (6): side record (before any OBJ): resource index (3) | pooled fractional output in thousandths (23).
///   SUM  (8): last record: FNV-1a of every earlier leftValue, low 26 bits. A carrier with a bad or missing
///             checksum (or any unknown record) is treated as NO state: logged once per session, every write for
///             that side is refused, and the save's carrier is never overwritten.
/// A record whose object is now owned by another side is dropped (enemy capture wipes every enhancement).
/// The carrier is never removed once created (an empty state keeps VER + SUM), and it is only written from safe
/// points: the side OnStartDay postfix (<see cref="FlushDirty"/>) and the viewer/panel commands. Native hooks only
/// mark a side dirty. Kill-switch: logistics_config.json "persistenceEnabled": false (state lives in memory only).
/// If the plugin is removed the buff stays an inert hidden side buff (its Core row stays with the Core overlay).
///
/// Proof tier: build target only. Whether the native keeps leftValue of Infinite durations, folds nothing for a
/// bonus-less side buff, and round-trips Data.Side.buffs through save/load is runtime-unproven (playtest first).
/// </summary>
internal static class Homm3FactoryLogisticsState
{
	internal const int Marker = 0x40000000;
	internal const int TypeShift = 26;
	internal const int DataMask = (1 << 26) - 1;
	internal const int TVer = 7, TObj = 1, TMeta = 2, TPday = 3, TEnh = 4, TXchg = 5, TPool = 6, TSum = 8, TUpool = 9;
	/// <summary>Version 1: no upgraded-stock records. Version 2 adds TUpool (Arcane conversion, DECISIONS.md #58). A
	/// state without upgraded stock is still written as version 1, so an older build keeps reading it; an older build
	/// reading a version-2 carrier marks it Corrupt and never writes it.</summary>
	internal const int FormatVersion = 1, FormatVersionUpgradedStock = 2;
	internal const int UpoolCountMask = (1 << 20) - 1;
	internal static readonly string[] PoolResources = { "gold", "wood", GameSymbols.CovePlunder.OreResourceName, "crystals", "mercury", "gemstones", "dust" };

	internal sealed class EnhState
	{
		internal int Level;
		internal int PendingLevel;
		internal int PendingDay;
	}

	internal sealed class ObjectState
	{
		internal int ObjectId;
		internal int UpgradeCenter;
		internal int ActiveCode;
		internal int PendingActiveCode;
		internal int PendingActiveDay;
		internal int SwitchWeek;   // week id the weekly switch was used in; 0 = never
		internal int? OrigExtraChargeMilli;
		internal readonly SortedDictionary<int, EnhState> Built = new();
		/// <summary>Arcane conversion stock: key = setIndex | sidIndex &lt;&lt; 3 (sidIndex &gt;= 1 into the set's sids), value = units.</summary>
		internal readonly SortedDictionary<int, int> UpgradedPool = new();

		internal static int PoolKey(int setIndex, int sidIndex) => (setIndex & 7) | (sidIndex & 7) << 3;

		internal bool HasUpgradedStock
		{
			get
			{
				foreach (var v in UpgradedPool.Values)
				{
					if (v > 0)
						return true;
				}
				return false;
			}
		}

		internal bool IsEmpty => Built.Count == 0 && UpgradeCenter == 0 && !HasUpgradedStock;
	}

	internal sealed class SideState
	{
		internal int SideIndex;
		internal readonly SortedDictionary<int, ObjectState> Objects = new();
		internal readonly long[] PoolMilli = new long[PoolResources.Length];
		internal bool Loaded;
		internal string LoadFail;
		/// <summary>The save holds a carrier this build cannot trust: state is empty and nothing may be written.</summary>
		internal string Corrupt;
		internal bool Dirty;
		internal string DirtyWhy;
	}

	private static readonly Dictionary<int, SideState> _sides = new();
	private static bool _loggedPersistenceOff;

	/// <summary>Session check; the runtime owns the token and clears every cache (this one included) on change.</summary>
	internal static void ResetIfSessionChanged() => Homm3FactoryLogisticsRuntime.ResetIfSessionChanged();

	/// <summary>Called by the runtime's session reset only.</summary>
	internal static void ClearCache()
	{
		_sides.Clear();
		_loggedPersistenceOff = false;
	}

	/// <summary>The cached state of a side, decoded from its carrier the first time it is asked for this session.</summary>
	internal static bool TryGet(int sideIndex, out SideState state, out string fail)
	{
		ResetIfSessionChanged();
		fail = null;
		if (_sides.TryGetValue(sideIndex, out state))
		{
			if (state.Loaded)
				return true;
			// A decode that failed once this session stays failed (logged once, no re-decode per call).
			fail = state.LoadFail;
			return false;
		}
		state = new SideState { SideIndex = sideIndex };
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var configFail))
		{
			fail = "config not loaded (" + configFail + ")";
			return false;   // not cached: the config may load later
		}
		if (!config.PersistenceEnabled)
		{
			if (!_loggedPersistenceOff)
			{
				_loggedPersistenceOff = true;
				Homm3FactoryLogisticsRuntime.LogWarning("persistenceEnabled=false: the save carrier is neither read nor written; logistics state lasts this session only.");
			}
			state.Loaded = true;
			_sides[sideIndex] = state;
			return true;
		}
		if (!TryResolveSide(sideIndex, out var side, out fail))
			return false;   // not cached: the side may resolve later
		if (!TryDecode(side, config, state, out fail))
		{
			Homm3FactoryLogisticsRuntime.LogError("state read for side " + sideIndex + " failed (" + fail + "); this side's logistics stay disabled this session.");
			state.LoadFail = fail;
			_sides[sideIndex] = state;
			return false;
		}
		if (state.Corrupt != null)
		{
			Homm3FactoryLogisticsRuntime.LogError("save carrier for side " + sideIndex + " is not trusted (" + state.Corrupt + "): treated as no state; it will not be overwritten this session.");
			state.Objects.Clear();
			Array.Clear(state.PoolMilli, 0, state.PoolMilli.Length);
		}
		state.Loaded = true;
		_sides[sideIndex] = state;
		return true;
	}

	internal static IEnumerable<SideState> LoadedSides()
	{
		ResetIfSessionChanged();
		return _sides.Values;
	}

	internal static bool TryResolveSide(int sideIndex, out DataSide side, out string fail)
	{
		side = null;
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveGlobalDataSide(sideIndex, out var obj, out fail) && obj is DataSide resolved)
		{
			side = resolved;
			return true;
		}
		if (Homm3SwashbucklerGoldHook.TryGetDayStartSide(sideIndex, out var cached))
		{
			side = cached;
			fail = null;
			return true;
		}
		fail = "data side " + sideIndex + " unresolved (" + (fail ?? "not a Data.Side") + ")";
		return false;
	}

	// ---------------------------------------------------------------- dirty / flush

	/// <summary>Native hooks call this instead of writing side.buffs; the write happens at the next safe point.</summary>
	internal static void MarkDirty(SideState state, string why)
	{
		if (state == null)
			return;
		state.Dirty = true;
		AnyDirty = true;
		state.DirtyWhy = state.DirtyWhy == null ? why : state.DirtyWhy.Length < 120 ? state.DirtyWhy + ", " + why : state.DirtyWhy;
	}

	/// <summary>Set by <see cref="MarkDirty"/>; the host Update tick flushes on the next frame (outside native hooks), so
	/// hook-side changes such as weekly Arcane conversion are saved before any autosave rather than at the next day start.</summary>
	internal static bool AnyDirty;

	/// <summary>Writes every dirty side (or only <paramref name="sideIndex"/>). Safe points only.</summary>
	internal static void FlushDirty(int sideIndex = -1)
	{
		foreach (var state in new List<SideState>(LoadedSides()))
		{
			if (!state.Dirty || (sideIndex >= 0 && state.SideIndex != sideIndex))
				continue;
			if (!TrySave(state, "flush: " + state.DirtyWhy, out var fail))
				Homm3FactoryLogisticsRuntime.LogOncePerDay("flush-" + state.SideIndex, "deferred save failed for side " + state.SideIndex + " (" + state.DirtyWhy + "): " + fail);
		}
	}

	// ---------------------------------------------------------------- carrier

	private static DataBuff FindCarrier(DataSide side, string carrierSid)
	{
		var list = side?.buffs?.list;
		if (list == null)
			return null;
		for (var i = 0; i < list.Count; i++)
		{
			var buff = list[i];
			if (buff != null && string.Equals(Homm3TowerArtificingRuntime.ReadMember(buff, GameSymbols.DungeonCaptives.DataBuffSidMembers) as string, carrierSid, StringComparison.Ordinal))
				return buff;
		}
		return null;
	}

	private static int Checksum(IReadOnlyList<int> records, int count)
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
			return (int)(h & DataMask);
		}
	}

	/// <summary>
	/// Returns false only when the side cannot be read at all. A carrier that is present but untrusted returns true
	/// with <see cref="SideState.Corrupt"/> set (the caller treats it as no state and never writes it).
	/// </summary>
	private static bool TryDecode(DataSide side, Homm3FactoryLogisticsConfig config, SideState state, out string fail)
	{
		fail = null;
		if (side.buffs == null || side.buffs.list == null)
		{
			fail = "Data.Side.buffs list is null";
			return false;
		}
		var carrier = FindCarrier(side, config.CarrierBuffSid);
		if (carrier == null)
			return true;
		var durations = carrier.durations;
		if (durations == null || durations.Length == 0)
		{
			state.Corrupt = "carrier has no records";
			return true;
		}
		var raws = new List<int>(durations.Length);
		for (var i = 0; i < durations.Length; i++)
		{
			var d = durations[i];
			if (d == null)
			{
				state.Corrupt = "record " + i + " is null";
				return true;
			}
			raws.Add(d.leftValue);
		}
		var last = raws[raws.Count - 1];
		if ((last & Marker) == 0 || last < 0 || ((last >> TypeShift) & 0xF) != TSum)
		{
			state.Corrupt = "no checksum record";
			return true;
		}
		if ((last & DataMask) != Checksum(raws, raws.Count - 1))
		{
			state.Corrupt = "checksum mismatch";
			return true;
		}
		ObjectState current = null;
		var sawVersion = false;
		var version = 0;
		for (var i = 0; i < raws.Count - 1; i++)
		{
			var raw = raws[i];
			if ((raw & Marker) == 0 || raw < 0)
			{
				state.Corrupt = "record " + i + " has no marker";
				return true;
			}
			var type = (raw >> TypeShift) & 0xF;
			var data = raw & DataMask;
			if (i == 0 && (type != TVer || (data != FormatVersion && data != FormatVersionUpgradedStock)))
			{
				state.Corrupt = "first record is not version " + FormatVersion + " or " + FormatVersionUpgradedStock;
				return true;
			}
			switch (type)
			{
				case TVer:
					sawVersion = true;
					version = data;
					break;
				case TObj:
					current = new ObjectState { ObjectId = data };
					state.Objects[data] = current;
					break;
				case TPool:
				{
					var res = data & 7;
					if (res < state.PoolMilli.Length)
						state.PoolMilli[res] = data >> 3;
					break;
				}
				default:
					if (current == null)
					{
						state.Corrupt = "record type " + type + " before any object";
						return true;
					}
					switch (type)
					{
						case TMeta:
							current.UpgradeCenter = data & 3;
							current.ActiveCode = (data >> 2) & 31;
							current.PendingActiveCode = (data >> 7) & 31;
							current.SwitchWeek = (data >> 12) & 0x3FFF;
							break;
						case TPday:
							current.PendingActiveDay = data;
							break;
						case TEnh:
						{
							var code = data & 31;
							current.Built[code] = new EnhState { Level = (data >> 5) & 7, PendingLevel = (data >> 8) & 7, PendingDay = (data >> 11) & 0x7FFF };
							break;
						}
						case TXchg:
							current.OrigExtraChargeMilli = data - (1 << 25);
							break;
						case TUpool when version >= FormatVersionUpgradedStock:
						{
							var key = data & 63;
							if ((key >> 3) < 1)
							{
								state.Corrupt = "upgraded-stock record names the base unit";
								return true;
							}
							current.UpgradedPool[key] = (current.UpgradedPool.TryGetValue(key, out var had) ? had : 0) + ((data >> 6) & UpoolCountMask);
							break;
						}
						default:
							state.Corrupt = "unknown record type " + type;
							return true;
					}
					break;
			}
		}
		if (!sawVersion)
			state.Corrupt = "carrier has no version record";
		else if (Homm3FactoryLogisticsRuntime.Verbose)
			Homm3FactoryLogisticsRuntime.LogInfo("state decoded for side " + state.SideIndex + ": " + state.Objects.Count + " object(s), " + raws.Count + " record(s).");
		return true;
	}

	private static int Rec(int type, int data)
	{
		if (data < 0 || data > DataMask)
			throw new ArgumentOutOfRangeException(nameof(data), "record type " + type + " data " + data + " exceeds 26 bits");
		return Marker | (type << TypeShift) | data;
	}

	/// <summary>Every record including the trailing checksum.</summary>
	internal static List<int> Encode(SideState state)
	{
		var anyStock = false;
		foreach (var o in state.Objects.Values)
			anyStock |= o.HasUpgradedStock;
		var records = new List<int> { Rec(TVer, anyStock ? FormatVersionUpgradedStock : FormatVersion) };
		for (var r = 0; r < state.PoolMilli.Length; r++)
		{
			var milli = Math.Max(0, Math.Min((1L << 23) - 1, state.PoolMilli[r]));
			if (milli > 0)
				records.Add(Rec(TPool, r | (int)(milli << 3)));
		}
		foreach (var o in state.Objects.Values)
		{
			if (o.IsEmpty && !o.OrigExtraChargeMilli.HasValue)
				continue;
			records.Add(Rec(TObj, o.ObjectId));
			records.Add(Rec(TMeta, (o.UpgradeCenter & 3) | (o.ActiveCode & 31) << 2 | (o.PendingActiveCode & 31) << 7 | (Math.Min(0x3FFF, Math.Max(0, o.SwitchWeek)) << 12)));
			if (o.PendingActiveCode != 0)
				records.Add(Rec(TPday, Math.Max(0, Math.Min(DataMask, o.PendingActiveDay))));
			foreach (var pair in o.Built)
			{
				var e = pair.Value;
				records.Add(Rec(TEnh, (pair.Key & 31) | (e.Level & 7) << 5 | (e.PendingLevel & 7) << 8 | (Math.Max(0, Math.Min(0x7FFF, e.PendingDay)) << 11)));
			}
			if (o.OrigExtraChargeMilli.HasValue)
				records.Add(Rec(TXchg, Math.Max(0, Math.Min(DataMask, o.OrigExtraChargeMilli.Value + (1 << 25)))));
			foreach (var pair in o.UpgradedPool)
			{
				if (pair.Value > 0)
					records.Add(Rec(TUpool, (pair.Key & 63) | Math.Min(UpoolCountMask, pair.Value) << 6));
			}
		}
		records.Add(Rec(TSum, Checksum(records, records.Count)));
		return records;
	}

	/// <summary>
	/// Rewrites the side's carrier buff from the managed state. Safe points only (side OnStartDay postfix, viewer and
	/// panel commands); native hooks use <see cref="MarkDirty"/>. Never removes the carrier.
	/// </summary>
	internal static bool TrySave(SideState state, string why, out string fail)
	{
		fail = null;
		try
		{
			if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var configFail))
			{
				fail = "config not loaded (" + configFail + ")";
				return false;
			}
			if (state.Corrupt != null)
			{
				fail = "the save's carrier is untrusted (" + state.Corrupt + "); refusing to overwrite it";
				return false;
			}
			if (!config.PersistenceEnabled)
			{
				state.Dirty = false;
				state.DirtyWhy = null;
				return true;
			}
			if (!TryResolveSide(state.SideIndex, out var side, out fail))
				return false;
			var list = side.buffs?.list;
			if (list == null)
			{
				fail = "Data.Side.buffs list is null";
				return false;
			}
			foreach (var o in state.Objects.Values)
			{
				if (o.ObjectId < 0 || o.ObjectId > DataMask)
				{
					fail = "object id " + o.ObjectId + " does not fit the 26-bit save field";
					return false;
				}
			}
			var records = Encode(state);
			var carrier = FindCarrier(side, config.CarrierBuffSid);
			if (carrier == null && records.Count <= 2)
			{
				// Nothing stored and no carrier yet: do not add one.
				state.Dirty = false;
				state.DirtyWhy = null;
				return true;
			}
			var durations = new Il2CppReferenceArray<DataBuffDuration>(records.Count);
			for (var i = 0; i < records.Count; i++)
				durations[i] = new DataBuffDuration(EBuffDurationType.Infinite, records[i]);
			if (carrier == null)
			{
				carrier = new DataBuff();
				if (!TryWriteBuffSid(carrier, config.CarrierBuffSid, out fail))
					return false;
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;   // reviewer: native keeps effectsCount == durations.Length
				carrier.wasApplied = false;
				list.Add(carrier);
			}
			else
			{
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;
			}
			// Read back: the decode of what is now in the save model must reproduce the managed state.
			var check = new SideState { SideIndex = state.SideIndex };
			if (!TryDecode(side, config, check, out var decodeFail) || check.Corrupt != null || check.Objects.Count != CountStored(state))
			{
				fail = "carrier read-back mismatch (" + (decodeFail ?? check.Corrupt ?? check.Objects.Count + " vs " + CountStored(state) + " objects") + ")";
				return false;
			}
			state.Dirty = false;
			state.DirtyWhy = null;
			if (Homm3FactoryLogisticsRuntime.Verbose)
				Homm3FactoryLogisticsRuntime.LogInfo("state saved for side " + state.SideIndex + " (" + why + "): " + records.Count.ToString(CultureInfo.InvariantCulture) + " record(s).");
			return true;
		}
		catch (Exception ex)
		{
			fail = "carrier write threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static int CountStored(SideState state)
	{
		var n = 0;
		foreach (var o in state.Objects.Values)
		{
			if (!o.IsEmpty || o.OrigExtraChargeMilli.HasValue)
				n++;
		}
		return n;
	}

	private static bool TryWriteBuffSid(DataBuff buff, string sid, out string fail)
	{
		fail = null;
		const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
		foreach (var name in GameSymbols.DungeonCaptives.DataBuffSidMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var prop = typeof(DataBuff).GetProperty(name, flags);
			if (prop != null && prop.PropertyType == typeof(string) && prop.CanWrite)
			{
				prop.SetValue(buff, sid);
				if (string.Equals(prop.GetValue(buff) as string, sid, StringComparison.Ordinal))
					return true;
			}
		}
		fail = "Buff sid member not writable (DungeonCaptives.DataBuffSidMembers)";
		return false;
	}
}
