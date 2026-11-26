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
using DataObjCity = Hex.Session.Data.ObjCity;
using DataSide = Hex.Session.Data.Side;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22, factory.bank (HotA Factory Bank; REVIEW 2: "the loan is granted when the Bank is built").
/// Row: <c>Build_Factory_Loan_Bank</c> in <c>homm3_factory_city</c> (plugin-only banks carrier, no native bonus).
///
/// Grant: when a Factory town's Bank goes from not built to built while the same side owns the town, that side gets
/// <see cref="LoanGold"/> gold once and owes <see cref="RepayDays"/> payments of <see cref="RepayGold"/>. Detection is a
/// main-thread poll (host Update, every <see cref="PollSeconds"/> s of real time) against a per-session baseline: the
/// first sighting of a town only records it, so loading a save or capturing a town with a Bank never grants a loan.
/// The construction commit itself is not hooked (Homm3CustomConstructionLawDiagnostics: commit-path patches crashed).
///
/// Repay: the side logic OnStartDay postfix takes min(<see cref="RepayGold"/>, side gold) per outstanding loan and
/// counts one payment down; a payment short of gold is still counted (HotA-style tempo loan, the debt never blocks).
/// The debt belongs to the side, not the town: losing the town does not cancel it.
///
/// Persistence (the Factory logistics pattern, Homm3FactoryLogisticsState): one hidden bonus-less side buff
/// <c>homm3_factory_loan_store</c> (Core row from tools/release_port/homm3_factory_logistics_core_overlay.py) per side
/// with debt. Its durations hold records leftValue = 0x40000000 | type &lt;&lt; 26 | 26 data bits:
///   VER (7) = 1 (first), CITY (1) = town map object id, LEFT (2) = payments left (applies to the CITY before it),
///   PAID (3) = last game day a repayment ran (guards a second day start of the same day), SUM (8) = FNV-1a of the
///   earlier records (last). A carrier that fails the checksum is never trusted or overwritten (logged).
/// Writes happen only from the host tick and the day-start postfix (safe points), never from inside other hooks.
///
/// All sides (human and AI) take the loan the same way. Proof tier: source only (not compiled, not run).
/// </summary>
internal static class Homm3FactoryLoanBankRuntime
{
	internal const string LogPrefix = "[FactoryLoanBank] ";
	internal const string BankSid = "Build_Factory_Loan_Bank";
	internal const string FactoryCitySid = "homm3_factory_city";
	internal const string CarrierSid = "homm3_factory_loan_store";
	internal const int LoanGold = 2500;
	internal const int RepayGold = 500;
	internal const int RepayDays = 5;
	private const float PollSeconds = 1f;

	private const int Marker = 0x40000000;
	private const int TypeShift = 26;
	private const int DataMask = (1 << 26) - 1;
	private const int TVer = 7, TCity = 1, TLeft = 2, TPaid = 3, TSum = 8;
	private const int FormatVersion = 1;

	private sealed class SideLoans
	{
		internal readonly SortedDictionary<int, int> Left = new(); // town object id -> payments left
		internal int LastPaidDay = -1;
		internal string Corrupt;
	}

	private static ManualLogSource _log;
	private static bool _attempted, _hostTypeRegistered;
	private static GameObject _host;
	private static PropertyInfo _sideDataProperty;
	private static float _nextPoll;
	private static IntPtr _sessionData;
	private static readonly Dictionary<int, (int owner, bool built)> _baseline = new();
	private static readonly Dictionary<int, SideLoans> _sides = new();
	private static readonly HashSet<string> _onceLogged = new(StringComparer.Ordinal);

	private static void LogInfo(string m) => (_log ?? Plugin.LogSource)?.LogInfo(LogPrefix + m);
	private static void LogWarning(string m) => (_log ?? Plugin.LogSource)?.LogWarning(LogPrefix + m);
	private static void LogError(string m) => (_log ?? Plugin.LogSource)?.LogError(LogPrefix + m);

	private static void LogOnce(string key, string m)
	{
		if (_onceLogged.Add(key))
			LogWarning(m);
	}

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var sideLogicType = GameMember.FindType(GameSymbols.SwashbucklerGold.SideLogicTypeId, GameSymbols.SwashbucklerGold.SideLogicTypeHint)
			                    ?? throw new TypeLoadException("side logic type (SwashbucklerGold.SideLogicTypeHint)");
			_sideDataProperty = FindPropertyOfType(sideLogicType, typeof(DataSide)) ?? throw new MissingMemberException(sideLogicType.FullName, "Side property");
			var startDay = sideLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(sideLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLoanBankRuntime), startDay, null, nameof(PostfixSideStartDay));
		}
		catch (Exception ex)
		{
			LogError("side day-start hook NOT registered; the Factory Bank grants no loan (a loan without repayment is refused): " + ex.GetBaseException().Message);
			return;
		}
		try
		{
			if (!_hostTypeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FactoryLoanBankRuntimeHost>();
				_hostTypeRegistered = true;
			}
			_host = new GameObject("Homm3FactoryLoanBankRuntimeHost");
			UnityObject.DontDestroyOnLoad(_host);
			_host.AddComponent<Homm3FactoryLoanBankRuntimeHost>();
		}
		catch (Exception ex)
		{
			_host = null;
			LogError("poll host failed; the Factory Bank grants no loan (repayments of saved loans still run): " + ex.GetBaseException().Message);
			return;
		}
		LogInfo("registered: side OnStartDay repayment + construction poll every " + PollSeconds + " s; loan " + LoanGold + " gold, repay " + RepayGold + " x " + RepayDays + " days. Proof tier: source only.");
	}

	private static PropertyInfo FindPropertyOfType(Type type, Type propertyType)
	{
		PropertyInfo found = null;
		foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.PropertyType != propertyType || p.GetIndexParameters().Length != 0 || p.GetGetMethod(true) == null)
				continue;
			if (found == null || p.Name.StartsWith("field_", StringComparison.Ordinal))
				found = p;
		}
		return found;
	}

	internal static void HostDestroyed() => _host = null;

	// ---------------------------------------------------------------- session

	private static bool TryData(out Hex.Session.Data.Data data)
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out data, out _) || data == null)
			return false;
		if (data.Pointer != _sessionData)
		{
			_sessionData = data.Pointer;
			_baseline.Clear();
			_sides.Clear();
			_onceLogged.Clear();
		}
		return true;
	}

	// ---------------------------------------------------------------- grant (host poll)

	internal static void Tick()
	{
		var now = Time.realtimeSinceStartup;
		if (now < _nextPoll)
			return;
		_nextPoll = now + PollSeconds;
		if (!TryData(out var data))
			return;
		var list = data.objects?.cityObjs;
		for (var i = 0; list != null && i < list.Count; i++)
		{
			var city = list[i];
			if (city == null || !Homm3TownBuildingReader.CityMatchesSid(city, FactoryCitySid))
				continue;
			var id = city.idMapObject;
			var owner = city.ownerSide;
			var built = Homm3TownBuildingReader.CityHasBuilding(city, BankSid);
			if (!_baseline.TryGetValue(id, out var seen))
			{
				_baseline[id] = (owner, built);
				continue;
			}
			_baseline[id] = (owner, built);
			if (!built || seen.built || owner < 0 || seen.owner != owner)
				continue;
			GrantLoan(owner, city, data.daysInGameCount);
		}
	}

	private static void GrantLoan(int sideIndex, DataObjCity city, int day)
	{
		var id = city.idMapObject;
		if (!TryLoans(sideIndex, out var loans, out var fail))
		{
			LogError("loan for town " + id + " (side " + sideIndex + ") refused: " + fail);
			return;
		}
		if (loans.Left.TryGetValue(id, out var left) && left > 0)
		{
			LogWarning("town " + id + " (side " + sideIndex + ") already owes " + left + " payment(s); no second loan.");
			return;
		}
		loans.Left[id] = RepayDays;
		if (!TrySave(sideIndex, loans, out fail))
		{
			loans.Left.Remove(id);
			LogError("loan for town " + id + " (side " + sideIndex + ") refused: the debt could not be stored (" + fail + ").");
			return;
		}
		if (!Homm3FactoryLogisticsEffects.TryAddResource(sideIndex, "gold", LoanGold, out fail))
		{
			loans.Left.Remove(id);
			TrySave(sideIndex, loans, out _);
			LogError("loan for town " + id + " (side " + sideIndex + "): +" + LoanGold + " gold FAILED (" + fail + "); debt withdrawn.");
			return;
		}
		LogInfo("day " + day + ": side " + sideIndex + " built the Bank in town " + id + "; +" + LoanGold + " gold, owes " + RepayDays + " x " + RepayGold + ".");
	}

	// ---------------------------------------------------------------- repay (side day start)

	private static void PostfixSideStartDay(object __instance)
	{
		try
		{
			var side = __instance == null || _sideDataProperty == null || !_sideDataProperty.DeclaringType.IsInstanceOfType(__instance)
				? null
				: _sideDataProperty.GetValue(__instance) as DataSide;
			if (side == null || !TryData(out var data))
				return;
			var day = data.daysInGameCount;
			if (!TryLoans(side.index, out var loans, out var fail))
			{
				LogOnce("repay-" + side.index, "repayment skipped for side " + side.index + ": " + fail);
				return;
			}
			if (loans.Left.Count == 0 || loans.LastPaidDay >= day)
				return;
			foreach (var id in new List<int>(loans.Left.Keys))
			{
				Homm3FactoryLogisticsEffects.TryReadResource(side.index, "gold", out var gold);
				var pay = Math.Max(0, Math.Min(RepayGold, gold));
				if (pay > 0 && !Homm3FactoryLogisticsEffects.TryAddResource(side.index, "gold", -pay, out var payFail))
				{
					LogWarning("day " + day + ": side " + side.index + " repayment for town " + id + " failed (" + payFail + "); counted as unpaid.");
					pay = 0;
				}
				var left = loans.Left[id] - 1;
				if (left <= 0)
					loans.Left.Remove(id);
				else
					loans.Left[id] = left;
				LogInfo("day " + day + ": side " + side.index + " repaid " + pay + " gold for the Bank in town " + id + (pay < RepayGold ? " (short of gold)" : "") + "; " + Math.Max(0, left) + " payment(s) left.");
			}
			loans.LastPaidDay = day;
			if (!TrySave(side.index, loans, out fail))
				LogError("day " + day + ": side " + side.index + " loan records not saved (" + fail + "); a reload may repeat today's payment.");
		}
		catch (Exception ex)
		{
			LogOnce("repay-throw", "day-start repayment threw " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- carrier

	private static bool TryLoans(int sideIndex, out SideLoans loans, out string fail)
	{
		fail = null;
		if (_sides.TryGetValue(sideIndex, out loans))
		{
			fail = loans.Corrupt;
			return loans.Corrupt == null;
		}
		if (!Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out fail))
			return false; // not cached: the side may resolve later
		loans = new SideLoans();
		Decode(side, loans);
		_sides[sideIndex] = loans;
		if (loans.Corrupt != null)
		{
			LogError("loan carrier of side " + sideIndex + " is not trusted (" + loans.Corrupt + "); no loan or repayment for this side this session, and it is not overwritten.");
			fail = loans.Corrupt;
			return false;
		}
		return true;
	}

	private static DataBuff FindCarrier(DataSide side)
	{
		var list = side?.buffs?.list;
		for (var i = 0; list != null && i < list.Count; i++)
		{
			var buff = list[i];
			if (buff != null && string.Equals(Homm3TowerArtificingRuntime.ReadMember(buff, GameSymbols.DungeonCaptives.DataBuffSidMembers) as string, CarrierSid, StringComparison.Ordinal))
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

	private static void Decode(DataSide side, SideLoans loans)
	{
		if (side.buffs?.list == null)
		{
			loans.Corrupt = "Data.Side.buffs list is null";
			return;
		}
		var carrier = FindCarrier(side);
		if (carrier == null)
			return;
		var durations = carrier.durations;
		if (durations == null || durations.Length < 2)
		{
			loans.Corrupt = "carrier has too few records";
			return;
		}
		var raws = new List<int>(durations.Length);
		for (var i = 0; i < durations.Length; i++)
		{
			if (durations[i] == null)
			{
				loans.Corrupt = "record " + i + " is null";
				return;
			}
			raws.Add(durations[i].leftValue);
		}
		var last = raws[raws.Count - 1];
		if ((last & Marker) == 0 || last < 0 || ((last >> TypeShift) & 0xF) != TSum || (last & DataMask) != Checksum(raws, raws.Count - 1))
		{
			loans.Corrupt = "checksum missing or wrong";
			return;
		}
		var city = -1;
		for (var i = 0; i < raws.Count - 1; i++)
		{
			var raw = raws[i];
			var type = (raw >> TypeShift) & 0xF;
			var data = raw & DataMask;
			if ((raw & Marker) == 0 || raw < 0 || (i == 0 && (type != TVer || data != FormatVersion)))
			{
				loans.Corrupt = "record " + i + " is not a version-" + FormatVersion + " loan record";
				loans.Left.Clear();
				return;
			}
			switch (type)
			{
				case TVer:
					break;
				case TCity:
					city = data;
					break;
				case TLeft when city >= 0:
					if (data > 0)
						loans.Left[city] = Math.Min(RepayDays, data);
					city = -1;
					break;
				case TPaid:
					loans.LastPaidDay = data;
					break;
				default:
					loans.Corrupt = "unexpected record type " + type + " at " + i;
					loans.Left.Clear();
					return;
			}
		}
	}

	private static int Rec(int type, int data)
	{
		if (data < 0 || data > DataMask)
			throw new ArgumentOutOfRangeException(nameof(data), "record type " + type + " data " + data + " exceeds 26 bits");
		return Marker | (type << TypeShift) | data;
	}

	private static bool TrySave(int sideIndex, SideLoans loans, out string fail)
	{
		fail = null;
		try
		{
			if (loans.Corrupt != null)
			{
				fail = "carrier untrusted (" + loans.Corrupt + ")";
				return false;
			}
			if (!Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out fail))
				return false;
			var list = side.buffs?.list;
			if (list == null)
			{
				fail = "Data.Side.buffs list is null";
				return false;
			}
			var records = new List<int> { Rec(TVer, FormatVersion) };
			foreach (var pair in loans.Left)
			{
				records.Add(Rec(TCity, pair.Key));
				records.Add(Rec(TLeft, pair.Value));
			}
			if (loans.LastPaidDay >= 0)
				records.Add(Rec(TPaid, Math.Min(DataMask, loans.LastPaidDay)));
			records.Add(Rec(TSum, Checksum(records, records.Count)));
			var carrier = FindCarrier(side);
			if (carrier == null && loans.Left.Count == 0)
				return true; // nothing owed and no carrier: do not add one
			var durations = new Il2CppReferenceArray<DataBuffDuration>(records.Count);
			for (var i = 0; i < records.Count; i++)
				durations[i] = new DataBuffDuration(EBuffDurationType.Infinite, records[i]);
			if (carrier == null)
			{
				carrier = new DataBuff();
				if (!TryWriteBuffSid(carrier, out fail))
					return false;
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;
				carrier.wasApplied = false;
				list.Add(carrier);
			}
			else
			{
				carrier.durations = durations;
				carrier.effectsCount = durations.Length;
			}
			var check = new SideLoans();
			Decode(side, check);
			if (check.Corrupt != null || check.Left.Count != loans.Left.Count || check.LastPaidDay != loans.LastPaidDay)
			{
				fail = "carrier read-back mismatch (" + (check.Corrupt ?? check.Left.Count + " vs " + loans.Left.Count + " loans") + ")";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			fail = "carrier write threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool TryWriteBuffSid(DataBuff buff, out string fail)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in GameSymbols.DungeonCaptives.DataBuffSidMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var prop = typeof(DataBuff).GetProperty(name, flags);
			if (prop == null || prop.PropertyType != typeof(string) || !prop.CanWrite)
				continue;
			prop.SetValue(buff, CarrierSid);
			if (string.Equals(prop.GetValue(buff) as string, CarrierSid, StringComparison.Ordinal))
			{
				fail = null;
				return true;
			}
		}
		fail = "Buff sid member not writable (DungeonCaptives.DataBuffSidMembers)";
		return false;
	}
}

public sealed class Homm3FactoryLoanBankRuntimeHost : MonoBehaviour
{
	public Homm3FactoryLoanBankRuntimeHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		try
		{
			Homm3FactoryLoanBankRuntime.Tick();
		}
		catch (Exception ex)
		{
			if (_warned++ < 5)
				Plugin.LogSource?.LogWarning(Homm3FactoryLoanBankRuntime.LogPrefix + "poll threw " + ex.GetBaseException().Message);
		}
	}

	private static int _warned;

	private void OnDestroy() => Homm3FactoryLoanBankRuntime.HostDestroyed();
}
