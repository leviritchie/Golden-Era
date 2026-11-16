using System;
using System.Collections.Generic;
using System.Reflection;
using DataHero = Hex.Session.Data.Hero;
using DataParty = Hex.Session.Data.DataParty;
using DataUnit = Hex.Session.Data.Unit;
using EListenerCallbackCall = Hex.Session.Logic.EListenerCallbackCall;
using PartyChangedType = Hex.Events.PartyChangedType;

namespace OfflineUnlockMod;

/// <summary>
/// Writes a whole 7-slot army arrangement into a hero's live logic party (shared by the War Captives recruit panel and
/// the Conflux Elemental Fusion panel; the body is the former Homm3DungeonCaptivesRuntime.ApplyRecruitBoard army write).
///
/// The caller builds the arrangement from <see cref="TryReadArmy"/> and passes back the per-sid totals it was built from.
/// <see cref="Write"/> re-reads the live party and refuses (nothing changed) when any of those totals moved; otherwise the
/// existing Data.Units of a sid are reused (slotPos and stacks rewritten, a merged-away or consumed stack is removed from
/// the list), new stacks go through the native AddUnitAtSlot on the logic party, the party listeners run once
/// (NotifyUnits, NotifyChanged), and the army is read back slot by slot.
/// </summary>
internal static class Homm3PartyArmyWriter
{
	internal const int MaxArmySlots = 7;

	internal enum WriteResult
	{
		/// <summary>Nothing was changed (calls unresolved, party unreadable, or the army moved under the caller).</summary>
		Refused,
		/// <summary>A native call threw part-way: the army may be partially written.</summary>
		WriteFailed,
		/// <summary>Every call ran but the army reads back differently from the arrangement.</summary>
		ReadBackMismatch,
		Written,
	}

	private static PropertyInfo _logicHeroPartyProperty;
	private static Type _logicPartyType;
	private static PropertyInfo _partyDataPartyProperty;
	private static MethodInfo _addUnitAtSlotMethod;
	private static MethodInfo _notifyUnitsMethod;
	private static MethodInfo _notifyChangedMethod;
	private static string _resolveFailure;

	internal static bool IsResolved => _addUnitAtSlotMethod != null && _notifyUnitsMethod != null && _notifyChangedMethod != null && _partyDataPartyProperty != null;

	internal static string ResolveFailure => _resolveFailure;

	/// <summary>The logic party type (Hex.Session.Logic.Hero's party property type) once resolved; null before.</summary>
	internal static Type LogicPartyType => IsResolved ? _logicPartyType : null;

	private delegate Il2CppSystem.Collections.Generic.List<DataUnit> UnitSource(out object logicParty, out string failReason);

	/// <summary>"add at slot=..., notify=.../..." for registration logs.</summary>
	internal static string Describe()
	{
		return "add at slot=" + FormatMethod(_addUnitAtSlotMethod) + ", notify=" + FormatMethod(_notifyUnitsMethod) + "/" + FormatMethod(_notifyChangedMethod);
	}

	/// <summary>Resolves the logic-party calls from Hex.Session.Logic.Hero (idempotent; throws nothing).</summary>
	internal static bool TryResolve(Type logicHeroType, out string failReason)
	{
		if (IsResolved)
		{
			failReason = null;
			return true;
		}
		try
		{
			if (logicHeroType == null)
				throw new TypeLoadException("logic hero type is null");
			var heroParty = ResolveProperty(logicHeroType, GameSymbols.DungeonCaptives.LogicHeroPartyMembers[0], "homm3.party.writer.logicHero.party");
			var partyType = heroParty.PropertyType;
			var dataParty = ResolveProperty(partyType, GameSymbols.DungeonCaptives.LogicPartyDataPartyMembers[0], "homm3.party.writer.logicParty.dataParty");
			if (dataParty.PropertyType != typeof(DataParty))
				throw new MissingMemberException("homm3.party.writer.logicParty.dataParty property " + dataParty.Name + " has type " + dataParty.PropertyType.FullName + ", expected " + typeof(DataParty).FullName);
			var addAtSlot = ResolveMethod(partyType, new[] { typeof(string), typeof(int), typeof(int), typeof(EListenerCallbackCall), typeof(bool) }, GameSymbols.DungeonCaptives.LogicPartyAddUnitAtSlot);
			var notifyUnits = ResolveMethod(partyType, new[] { typeof(EListenerCallbackCall) }, GameSymbols.DungeonCaptives.LogicPartyNotifyUnits);
			var notifyChanged = ResolveMethod(partyType, new[] { typeof(EListenerCallbackCall), typeof(bool), typeof(PartyChangedType) }, GameSymbols.DungeonCaptives.LogicPartyNotifyChanged);
			_logicHeroPartyProperty = heroParty;
			_logicPartyType = partyType;
			_partyDataPartyProperty = dataParty;
			_addUnitAtSlotMethod = addAtSlot;
			_notifyUnitsMethod = notifyUnits;
			_notifyChangedMethod = notifyChanged;
			_resolveFailure = null;
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			_resolveFailure = failReason = ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>
	/// The logic party's Data.Unit list (the list every native party call edits) and the logic party itself; the data
	/// hero's party list when the logic party is unreadable.
	/// </summary>
	internal static Il2CppSystem.Collections.Generic.List<DataUnit> LiveUnits(object logicHero, DataHero dataHero, out object logicParty, out string failReason)
	{
		failReason = null;
		logicParty = null;
		try
		{
			logicParty = logicHero != null && _logicHeroPartyProperty != null && _logicHeroPartyProperty.DeclaringType.IsInstanceOfType(logicHero)
				? _logicHeroPartyProperty.GetValue(logicHero)
				: null;
			var dataParty = logicParty != null && _partyDataPartyProperty != null ? _partyDataPartyProperty.GetValue(logicParty) as DataParty : null;
			var units = dataParty?.units ?? dataHero?.party?.units;
			if (units == null)
				failReason = "army unreadable";
			return units;
		}
		catch (Exception ex)
		{
			failReason = "army unreadable: " + ex.GetBaseException().Message;
			return null;
		}
	}

	/// <summary>The Data party a logic party edits, or null when <paramref name="logicParty"/> is not a resolved logic party.</summary>
	internal static DataParty DataPartyOf(object logicParty)
	{
		if (logicParty == null || !IsResolved || !_logicPartyType.IsInstanceOfType(logicParty))
			return null;
		return _partyDataPartyProperty.GetValue(logicParty) as DataParty;
	}

	/// <summary>The Data.Unit list of a logic party that is not a hero's (a town garrison); no data-side fallback.</summary>
	private static Il2CppSystem.Collections.Generic.List<DataUnit> LivePartyUnits(object logicParty, out object party, out string failReason)
	{
		party = null;
		failReason = null;
		try
		{
			var dataParty = DataPartyOf(logicParty);
			var units = dataParty?.units;
			if (units == null)
			{
				failReason = IsResolved ? "party army unreadable" : "party writer calls unresolved";
				return null;
			}
			party = logicParty;
			return units;
		}
		catch (Exception ex)
		{
			failReason = "party army unreadable: " + ex.GetBaseException().Message;
			return null;
		}
	}

	/// <summary>
	/// The live army by slot (stacks with no or a duplicate slotPos take the first free slot) and the creature total per
	/// sid. False with the reason when the army is unreadable or holds more than 7 stacks.
	/// </summary>
	internal static bool TryReadArmy(object logicHero, DataHero dataHero, out string[] slotSid, out int[] slotCount, out Dictionary<string, int> totals, out string failReason)
	{
		var units = LiveUnits(logicHero, dataHero, out _, out failReason);
		return ReadSlots(units, out slotSid, out slotCount, out totals, ref failReason);
	}

	/// <summary><see cref="TryReadArmy"/> for a logic party that is not a hero's (a town garrison).</summary>
	internal static bool TryReadPartyArmy(object logicParty, out string[] slotSid, out int[] slotCount, out Dictionary<string, int> totals, out string failReason)
	{
		var units = LivePartyUnits(logicParty, out _, out failReason);
		return ReadSlots(units, out slotSid, out slotCount, out totals, ref failReason);
	}

	private static bool ReadSlots(Il2CppSystem.Collections.Generic.List<DataUnit> units, out string[] slotSid, out int[] slotCount, out Dictionary<string, int> totals, ref string failReason)
	{
		slotSid = new string[MaxArmySlots];
		slotCount = new int[MaxArmySlots];
		totals = new Dictionary<string, int>(StringComparer.Ordinal);
		if (units == null)
			return false;
		var misplaced = new List<(string Sid, int Count)>();
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			var sid = unit == null ? null : UnitSid(unit);
			if (sid == null || unit.stacks <= 0)
				continue;
			totals.TryGetValue(sid, out var own);
			totals[sid] = own + unit.stacks;
			if (unit.slotPos >= 0 && unit.slotPos < MaxArmySlots && slotSid[unit.slotPos] == null)
			{
				slotSid[unit.slotPos] = sid;
				slotCount[unit.slotPos] = unit.stacks;
			}
			else
			{
				misplaced.Add((sid, unit.stacks));
			}
		}
		foreach (var (sid, count) in misplaced)
		{
			var free = Array.IndexOf(slotSid, null);
			if (free < 0)
			{
				failReason = "army has more than " + MaxArmySlots + " stacks";
				return false;
			}
			slotSid[free] = sid;
			slotCount[free] = count;
		}
		return true;
	}

	/// <summary>
	/// Writes <paramref name="targetSid"/>/<paramref name="targetCount"/> (7 slots; null sid = empty) into the live party.
	/// <paramref name="expectedTotals"/> are the per-sid creature totals the arrangement was built from; a sid whose live
	/// total differs refuses the write. <paramref name="steps"/> receives every applied change for the caller's log;
	/// <paramref name="failReason"/> says why for every result but Written.
	/// </summary>
	internal static WriteResult Write(object logicHero, DataHero dataHero, string[] targetSid, int[] targetCount, IReadOnlyDictionary<string, int> expectedTotals,
		List<string> steps, out string failReason)
	{
		return WriteCore((out object party, out string fail) => LiveUnits(logicHero, dataHero, out party, out fail), targetSid, targetCount, expectedTotals, steps, out failReason);
	}

	/// <summary><see cref="Write"/> for a logic party that is not a hero's (a town garrison).</summary>
	internal static WriteResult WritePartyArmy(object logicParty, string[] targetSid, int[] targetCount, IReadOnlyDictionary<string, int> expectedTotals,
		List<string> steps, out string failReason)
	{
		return WriteCore((out object party, out string fail) => LivePartyUnits(logicParty, out party, out fail), targetSid, targetCount, expectedTotals, steps, out failReason);
	}

	private static WriteResult WriteCore(UnitSource source, string[] targetSid, int[] targetCount, IReadOnlyDictionary<string, int> expectedTotals,
		List<string> steps, out string failReason)
	{
		failReason = null;
		if (!IsResolved)
		{
			failReason = "party writer calls unresolved" + (_resolveFailure == null ? "" : " (" + _resolveFailure + ")");
			return WriteResult.Refused;
		}
		if (targetSid == null || targetCount == null || targetSid.Length != MaxArmySlots || targetCount.Length != MaxArmySlots)
		{
			failReason = "arrangement must have " + MaxArmySlots + " slots";
			return WriteResult.Refused;
		}
		var units = source(out var logicParty, out failReason);
		if (units == null || logicParty == null)
		{
			failReason ??= "logic party unreadable";
			return WriteResult.Refused;
		}
		// The army must still be the one the arrangement was built from (own troops per sid).
		var live = new Dictionary<string, List<DataUnit>>(StringComparer.Ordinal);
		var liveTotals = new Dictionary<string, int>(StringComparer.Ordinal);
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			var sid = unit == null ? null : UnitSid(unit);
			if (sid == null)
				continue;
			if (!live.TryGetValue(sid, out var list))
				live[sid] = list = new List<DataUnit>();
			list.Add(unit);
			liveTotals.TryGetValue(sid, out var have);
			liveTotals[sid] = have + Math.Max(0, unit.stacks);
		}
		if (expectedTotals != null)
		{
			foreach (var pair in expectedTotals)
			{
				liveTotals.TryGetValue(pair.Key, out var have);
				if (have != pair.Value)
				{
					failReason = "the army changed while the panel was open (" + pair.Key + " " + pair.Value + " -> " + have + ")";
					return WriteResult.Refused;
				}
			}
		}

		var added = new List<(string Sid, int Count, int Slot)>();
		try
		{
			for (var slot = 0; slot < MaxArmySlots; slot++)
			{
				var sid = targetSid[slot];
				if (sid == null)
					continue;
				DataUnit reuse = null;
				if (live.TryGetValue(sid, out var pool) && pool.Count > 0)
				{
					var at = slot;
					reuse = pool.Find(u => u.slotPos == at) ?? pool[0];
					pool.Remove(reuse);
				}
				if (reuse == null)
				{
					added.Add((sid, targetCount[slot], slot));
					continue;
				}
				if (reuse.slotPos != slot || reuse.stacks != targetCount[slot])
					steps?.Add(sid + "@" + reuse.slotPos + "x" + reuse.stacks + "->@" + slot + "x" + targetCount[slot]);
				reuse.slotPos = slot;
				reuse.stacks = targetCount[slot];
			}
			foreach (var pool in live.Values)
			{
				foreach (var unit in pool)
				{
					steps?.Add("removed " + (UnitSid(unit) ?? "?") + "@" + unit.slotPos + "x" + unit.stacks);
					units.Remove(unit);
				}
			}
			foreach (var (sid, count, slot) in added)
			{
				_addUnitAtSlotMethod.Invoke(logicParty, new object[] { sid, count, slot, EListenerCallbackCall.RealAndPrediction, false });
				steps?.Add("new " + sid + "@" + slot + "x" + count);
			}
			_notifyUnitsMethod.Invoke(logicParty, new object[] { EListenerCallbackCall.RealAndPrediction });
			_notifyChangedMethod.Invoke(logicParty, new object[] { EListenerCallbackCall.RealAndPrediction, false, PartyChangedType.Other });
		}
		catch (Exception ex)
		{
			failReason = ex.GetBaseException().Message;
			return WriteResult.WriteFailed;
		}

		// Read back: every arranged slot must hold its sid and count.
		string backFail = null;
		var readable = ReadSlots(source(out _, out backFail), out var backSid, out var backCount, out _, ref backFail);
		var mismatch = new List<string>();
		for (var slot = 0; slot < MaxArmySlots; slot++)
		{
			if (!readable || !string.Equals(backSid[slot], targetSid[slot], StringComparison.Ordinal) || backCount[slot] != targetCount[slot])
				mismatch.Add(slot + ":" + (readable ? backSid[slot] ?? "-" : "-") + "x" + (readable ? backCount[slot] : 0) + "!=" + (targetSid[slot] ?? "-") + "x" + targetCount[slot]);
		}
		if (mismatch.Count > 0)
		{
			failReason = string.Join(", ", mismatch);
			return WriteResult.ReadBackMismatch;
		}
		return WriteResult.Written;
	}

	internal static string Describe(string[] slotSid, int[] slotCount)
	{
		var parts = new List<string>();
		for (var slot = 0; slot < MaxArmySlots && slotSid != null && slotCount != null; slot++)
		{
			if (slotSid[slot] != null)
				parts.Add(slot + ":" + slotSid[slot] + "x" + slotCount[slot]);
		}
		return "[" + string.Join(", ", parts) + "]";
	}

	private static string UnitSid(DataUnit unit)
	{
		var sid = ReadMember(unit, GameSymbols.AdventureAiDecision.DataUnitSidFieldHints) as string;
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static object ReadMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				var property = cur.GetProperty(name, flags | BindingFlags.DeclaredOnly);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj);
				var field = cur.GetField(name, flags | BindingFlags.DeclaredOnly);
				if (field != null)
					return field.GetValue(obj);
				var method = cur.GetMethod(name, flags | BindingFlags.DeclaredOnly, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, null);
			}
		}
		return null;
	}

	private static PropertyInfo ResolveProperty(Type type, string name, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var property = type?.GetProperty(name, flags);
		if (property == null || property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
			throw new MissingMemberException(symbolId + " property " + name + " not found on " + (type?.FullName ?? "null"));
		return property;
	}

	private static MethodInfo ResolveMethod(Type type, Type[] parameterTypes, GameSymbols.MethodSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var matches = new List<MethodInfo>();
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length && exact; i++)
					exact = parameters[i].ParameterType == parameterTypes[i];
				if (exact && !matches.Contains(method))
					matches.Add(method);
			}
			if (matches.Count == 1)
				return matches[0];
			if (matches.Count > 1)
				throw new AmbiguousMatchException(symbol.Id + " matched " + matches.Count + " methods named " + name + " on " + type.FullName);
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + (type?.FullName ?? "null"));
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}
}
