using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact adapter for native buff/debuff manager query/add surfaces and explicit diagnostic status probes.
/// Source-prepared from the same decomp-backed symbols used by Homm3BuffDebuffLawDiagnostics.
/// After a successful <c>dzv.bbgf</c> add + optional got-buff dispatch, applies
/// <c>BuffConfig.data.stats</c> additively onto <c>Unit.get_stats()</c> via per-field setters.
/// Live-proven (2026-07-26 live probe): manager presence alone does not change
/// <c>get_speed</c>; additive <c>set_speed(current + config.data.stats.speed)</c> does.
/// </summary>
internal static class Homm3BuffDebuffNativeAdapter
{
	internal readonly struct BuffQueryInfo
	{
		internal readonly object Manager;
		internal readonly object Receiver;
		internal readonly string Sid;
		internal readonly bool HasSid;
		internal readonly int MatchCount;

		internal BuffQueryInfo(object manager, object receiver, string sid, bool hasSid, int matchCount)
		{
			Manager = manager;
			Receiver = receiver;
			Sid = sid;
			HasSid = hasSid;
			MatchCount = matchCount;
		}

		public override string ToString()
		{
			return "sid=" + (Sid ?? "null")
			       + " hasSid=" + HasSid
			       + " matchCount=" + MatchCount
			       + " manager=" + DescribeObject(Manager)
			       + " receiver=" + DescribeObject(Receiver);
		}
	}

	private static Type _buffManagerType;
	private static MethodInfo _hasBySidMethod;
	private static MethodInfo _listBySidMethod;
	private static MethodInfo _addMethod;
	private static Type _buffEventArgsType;
	private static ConstructorInfo _buffEventArgsConstructor;
	private static MethodInfo _buffEventDispatchMethod;
	private static bool _resolved;
	private static string _resolveFailure;
	// Native pointer keys of buff instances whose config.data.stats were already
	// folded into Unit.get_stats. Prevents double-apply when bbgf refresh returns
	// the same instance.
	private static readonly HashSet<long> AppliedBuffStatInstanceKeys = new();
	private static readonly object AppliedBuffStatGate = new();

	internal static bool TryRequireAnyBuffSid(
		object buffManager,
		string[] buffSids,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (buffSids == null || buffSids.Length == 0)
		{
			failReason = "buff SID list is empty";
			return false;
		}

		string firstFailure = null;
		for (var i = 0; i < buffSids.Length; i++)
		{
			var sid = buffSids[i];
			if (string.IsNullOrWhiteSpace(sid))
			{
				firstFailure ??= "buff SID list contains an empty SID";
				continue;
			}
			if (TryRequireBuffSid(buffManager, sid, out info, out failReason))
				return true;
			firstFailure ??= failReason;
		}

		failReason = firstFailure ?? "no requested buff SID was present";
		return false;
	}

	internal static bool TryRequireBuffSid(
		object buffManager,
		string buffSid,
		out BuffQueryInfo info,
		out string failReason)
	{
		if (!TryQueryBuffSid(buffManager, buffSid, out info, out failReason))
			return false;
		if (info.HasSid)
			return true;
		failReason = "buff SID is not present: " + buffSid;
		return false;
	}

	internal static bool TryQueryBuffSid(
		object buffManager,
		string buffSid,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (string.IsNullOrWhiteSpace(buffSid))
		{
			failReason = "buff SID is empty";
			return false;
		}
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateManager(buffManager, out failReason))
			return false;

		var receiver = ReadFirstExactMember(buffManager, buffManager.GetType(), GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers);
		if (receiver == null)
		{
			failReason = "buff manager receiver was not resolved from exact receiver members";
			return false;
		}
		// Presence authority is list-by-SID Count (dzv.bbfl). Live Golden Era exposes three
		// Boolean_String methods on the buff manager (bbfn / dud / ink); DiffableCs-neighbor
		// guesses for HasBySid have been live-negative while bbgf returned a buff with the
		// correct raw SID. IL2CPP List<T> is not CLR-IEnumerable — read get_Count, do not foreach.
		if (!TryInvokeListCount(buffManager, buffSid, out var matchCount, out failReason))
			return false;
		info = new BuffQueryInfo(buffManager, receiver, buffSid, matchCount > 0, matchCount);
		failReason = null;
		return true;
	}

	internal static bool TryResolveBuffManagerFromReceiver(object receiver, out object buffManager, out string failReason)
	{
		buffManager = null;
		if (!TryResolve(out failReason))
			return false;
		if (receiver == null)
		{
			failReason = "buff receiver is null";
			return false;
		}

		buffManager = ReadFirstExactMember(receiver, receiver.GetType(), GameSymbols.BuffDebuffLaws.BuffReceiverManagerMembers);
		if (buffManager == null)
		{
			failReason = "buff receiver did not expose exact buff manager";
			return false;
		}
		return ValidateManager(buffManager, out failReason);
	}

	internal static bool TryRequireBuffSidFromReceiver(
		object receiver,
		string buffSid,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (!TryResolveBuffManagerFromReceiver(receiver, out var buffManager, out failReason))
			return false;
		return TryRequireBuffSid(buffManager, buffSid, out info, out failReason);
	}

	internal static bool TryRequireAnyBuffSidFromReceiver(
		object receiver,
		string[] buffSids,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (!TryResolveBuffManagerFromReceiver(receiver, out var buffManager, out failReason))
			return false;
		return TryRequireAnyBuffSid(buffManager, buffSids, out info, out failReason);
	}
	internal static bool TryQueryAnyBuffSidFromReceiver(
		object receiver,
		string[] buffSids,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (!TryResolveBuffManagerFromReceiver(receiver, out var buffManager, out failReason))
			return false;
		if (buffSids == null || buffSids.Length == 0)
		{
			failReason = "buff SID list is empty";
			return false;
		}

		string firstFailure = null;
		for (var i = 0; i < buffSids.Length; i++)
		{
			var sid = buffSids[i];
			if (string.IsNullOrWhiteSpace(sid))
				continue;
			if (!TryQueryBuffSid(buffManager, sid, out var current, out var currentFailReason))
			{
				firstFailure ??= currentFailReason;
				continue;
			}
			if (current.HasSid)
			{
				info = current;
				failReason = null;
				return true;
			}
			if (info.Manager == null)
				info = current;
		}

		if (info.Manager != null)
		{
			failReason = "no requested buff SID was present";
			return true;
		}
		failReason = firstFailure ?? "no requested buff SID was queryable";
		return false;
	}
	internal static bool TryDiagnosticAddBuffSidFromReceiver(
		object receiver,
		string buffSid,
		object caster,
		int level,
		int duration,
		int value,
		bool refresh,
		out BuffQueryInfo info,
		out string failReason)
	{
		return TryAddBuffSidFromReceiverCore(receiver, buffSid, caster, level, duration, value, refresh, dispatchEvent: true, out info, out failReason);
	}

	internal static bool TryAddStateOnlyBuffSidFromReceiver(
		object receiver,
		string buffSid,
		object caster,
		int level,
		int duration,
		int value,
		bool refresh,
		out BuffQueryInfo info,
		out string failReason)
	{
		return TryAddBuffSidFromReceiverCore(receiver, buffSid, caster, level, duration, value, refresh, dispatchEvent: false, out info, out failReason);
	}

	internal static bool TryAddBuffSidFromReceiver(
		object receiver,
		string buffSid,
		object caster,
		int level,
		int duration,
		int value,
		bool refresh,
		out BuffQueryInfo info,
		out string failReason)
	{
		return TryAddBuffSidFromReceiverCore(receiver, buffSid, caster, level, duration, value, refresh, dispatchEvent: true, out info, out failReason);
	}

	private static bool TryAddBuffSidFromReceiverCore(
		object receiver,
		string buffSid,
		object caster,
		int level,
		int duration,
		int value,
		bool refresh,
		bool dispatchEvent,
		out BuffQueryInfo info,
		out string failReason)
	{
		info = default;
		if (string.IsNullOrWhiteSpace(buffSid))
		{
			failReason = "buff SID is empty";
			return false;
		}
		if (!TryResolveBuffManagerFromReceiver(receiver, out var buffManager, out failReason))
			return false;
		if (!TryResolveAdd(out failReason))
			return false;
		var parameters = _addMethod.GetParameters();
		if (parameters.Length != 6)
		{
			failReason = "exact buff add method parameter count changed";
			return false;
		}
		var casterType = parameters[3].ParameterType;
		if (!TryNormalizeBuffSource(caster, casterType, out var nativeSourceObject, out var normalizedCaster, out failReason))
			return false;
		try
		{
			var rawBuff = _addMethod.Invoke(buffManager, new object[] { buffSid, level, duration, normalizedCaster, value, refresh });
			if (rawBuff == null)
			{
				failReason = "buff add returned null";
				return false;
			}
			if (dispatchEvent && !TryDispatchBuffEvent(nativeSourceObject, buffManager, rawBuff, out failReason))
				return false;
			if (!TryQueryBuffSid(buffManager, buffSid, out info, out failReason))
				return false;
			if (!info.HasSid)
			{
				var rawSid = TryReadBuffInstanceSid(rawBuff);
				TryInvokeHas(buffManager, buffSid, out var hasBool, out _);
				failReason = "buff add returned but list-by-SID Count did not report SID: "
				             + buffSid
				             + "; rawBuffSid="
				             + (rawSid ?? "null")
				             + "; listMethod="
				             + FormatMethod(_listBySidMethod)
				             + "; matchCount="
				             + info.MatchCount
				             + "; hasMethod="
				             + FormatMethod(_hasBySidMethod)
				             + "; hasBool="
				             + hasBool
				             + "; boolProbe="
				             + ProbeAllBooleanStringMethods(buffManager, buffSid);
				return false;
			}
			// Live-negative: bbgf + bcja presence does not rebuild Unit.get_stats from
			// BuffConfig.data.stats. Fold non-zero config deltas additively (set_speed etc.).
			if (!TryApplyBuffConfigStatsAdditive(receiver, rawBuff, out failReason))
				return false;
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "buff add" + (dispatchEvent ? "/event-dispatch" : "") + " invocation failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	internal static bool TryDescribeBuffDebuffSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"manager=" + DescribeType(_buffManagerType)
			+ " hasBySid=" + FormatMethod(_hasBySidMethod)
			+ " listBySid=" + FormatMethod(_listBySidMethod);
		failReason = null;
		return true;
	}

	private static bool TryNormalizeBuffSource(object caster, Type casterType, out object nativeSourceObject, out object normalizedCaster, out string failReason)
	{
		nativeSourceObject = null;
		normalizedCaster = null;
		if (casterType == null)
		{
			failReason = "buff add caster/source parameter type is unresolved";
			return false;
		}

		var exactAbilityManager = ReadFirstExactMember(caster, caster?.GetType(), GameSymbols.BuffDebuffLaws.BuffSourceAbilityManagerMembers);
		var exactAbilitySource = ReadFirstExactMember(exactAbilityManager, exactAbilityManager?.GetType(), GameSymbols.BuffDebuffLaws.BuffAbilityManagerSourceMembers);
		if (exactAbilitySource != null)
		{
			var exactAbilitySourceSelf = ReadFirstExactMember(exactAbilitySource, exactAbilitySource.GetType(), GameSymbols.BuffDebuffLaws.BuffSourceSelfMembers);
			if (exactAbilitySourceSelf != null && casterType.IsInstanceOfType(exactAbilitySourceSelf))
			{
				nativeSourceObject = exactAbilitySource;
				normalizedCaster = exactAbilitySourceSelf;
				failReason = null;
				return true;
			}
			if (casterType.IsInstanceOfType(exactAbilitySource))
			{
				nativeSourceObject = exactAbilitySource;
				normalizedCaster = exactAbilitySource;
				failReason = null;
				return true;
			}
		}

		if (caster != null && casterType.IsInstanceOfType(caster))
		{
			nativeSourceObject = caster;
			normalizedCaster = caster;
			failReason = null;
			return true;
		}
		var exactSelf = ReadFirstExactMember(caster, caster?.GetType(), GameSymbols.BuffDebuffLaws.BuffSourceSelfMembers);
		if (exactSelf != null && casterType.IsInstanceOfType(exactSelf))
		{
			nativeSourceObject = exactSelf;
			normalizedCaster = exactSelf;
			failReason = null;
			return true;
		}
		var exactReceiverObject = ReadFirstExactMember(caster, caster?.GetType(), GameSymbols.BuffDebuffLaws.BuffReceiverObjectMembers);
		if (exactReceiverObject != null && casterType.IsInstanceOfType(exactReceiverObject))
		{
			nativeSourceObject = exactReceiverObject;
			normalizedCaster = exactReceiverObject;
			failReason = null;
			return true;
		}
		failReason = "buff add caster/source object is not assignable to exact native caster parameter "
		             + DescribeType(casterType)
		             + "; source=" + DescribeObject(caster)
		             + "; exact ability manager=" + DescribeObject(exactAbilityManager)
		             + "; exact ability source=" + DescribeObject(exactAbilitySource)
		             + "; exact bbce source=" + DescribeObject(exactSelf)
		             + "; exact receiver object=" + DescribeObject(exactReceiverObject);
		return false;
	}
	private static bool TryResolveAdd(out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (_addMethod != null)
			return true;
		_addMethod = ResolveExactMethod(_buffManagerType, GameSymbols.BuffDebuffLaws.BuffAdd, 6, null);
		if (_addMethod == null || _addMethod.ReturnType == typeof(void))
		{
			failReason = "exact buff add method was not found";
			return false;
		}
		failReason = null;
		return true;
	}


	/// <summary>
	/// Fold <c>rawBuff.config.data.stats</c> additively into <c>receiver.get_stats()</c>.
	/// Live-proven for speed: <c>set_speed(current + config.speed)</c> moves combat speed;
	/// replacing the whole UnitStat object or calling <c>Method_Public_Void_UnitStat_0</c> clobbers.
	/// </summary>
	private static bool TryApplyBuffConfigStatsAdditive(object receiver, object rawBuff, out string failReason)
	{
		failReason = null;
		if (rawBuff == null)
		{
			failReason = "buff config stats apply: rawBuff is null";
			return false;
		}

		long buffKey = 0;
		if (Homm3DirectStateIdentity.TryResolveKey(rawBuff, out buffKey, out _)
		    && buffKey != 0)
		{
			lock (AppliedBuffStatGate)
			{
				if (!AppliedBuffStatInstanceKeys.Add(buffKey))
					return true;
			}
		}

		object config = null;
		try
		{
			config = ReadFirstExactMember(rawBuff, rawBuff.GetType(), new[] { "config", "dataConfig", "get_config", "get_dataConfig" });
		}
		catch
		{
			// fall through
		}
		if (config == null)
		{
			failReason = "buff config stats apply: BuffConfig was not resolved on rawBuff=" + DescribeObject(rawBuff);
			UndoAppliedBuffKey(buffKey);
			return false;
		}

		object data = null;
		try
		{
			data = ReadFirstExactMember(config, config.GetType(), new[] { "data", "get_data" });
		}
		catch
		{
			// fall through
		}
		if (data == null)
		{
			// Marker / law buffs may lack BuffData — presence-only is OK.
			return true;
		}

		object deltaStats = null;
		try
		{
			deltaStats = ReadFirstExactMember(data, data.GetType(), new[] { "stats", "get_stats" });
		}
		catch
		{
			// fall through
		}
		if (deltaStats == null)
			return true;

		object unitStats = null;
		try
		{
			unitStats = ReadFirstExactMember(receiver, receiver.GetType(), new[] { "get_stats", "stats", "get__stats_k__BackingField" });
		}
		catch
		{
			// fall through
		}
		if (unitStats == null)
		{
			failReason = "buff config stats apply: Unit.get_stats was not resolved on receiver=" + DescribeObject(receiver);
			UndoAppliedBuffKey(buffKey);
			return false;
		}

		// Additive int fields that haste / Split Assembly / initiative buffs use.
		var fields = new[] { "speed", "initiative", "offence", "defence" };
		var appliedAny = false;
		foreach (var field in fields)
		{
			if (!TryReadIntMember(deltaStats, "get_" + field, out var delta) || delta == 0)
				continue;
			if (!TryReadIntMember(unitStats, "get_" + field, out var current))
			{
				failReason = "buff config stats apply: missing get_" + field + " on UnitStat";
				UndoAppliedBuffKey(buffKey);
				return false;
			}
			if (!TryWriteIntMember(unitStats, "set_" + field, current + delta))
			{
				failReason = "buff config stats apply: missing set_" + field + " on UnitStat";
				UndoAppliedBuffKey(buffKey);
				return false;
			}
			appliedAny = true;
		}

		// Percent fields (float) when non-zero on config delta.
		var percFields = new[] { "speedPerc", "initiativePerc", "offencePerc", "defencePerc" };
		foreach (var field in percFields)
		{
			if (!TryReadFloatMember(deltaStats, "get_" + field, out var delta) || Math.Abs(delta) < 0.0001f)
				continue;
			if (!TryReadFloatMember(unitStats, "get_" + field, out var current))
			{
				failReason = "buff config stats apply: missing get_" + field + " on UnitStat";
				UndoAppliedBuffKey(buffKey);
				return false;
			}
			if (!TryWriteFloatMember(unitStats, "set_" + field, current + delta))
			{
				failReason = "buff config stats apply: missing set_" + field + " on UnitStat";
				UndoAppliedBuffKey(buffKey);
				return false;
			}
			appliedAny = true;
		}

		_ = appliedAny;
		failReason = null;
		return true;
	}

	private static void UndoAppliedBuffKey(long buffKey)
	{
		if (buffKey == 0)
			return;
		lock (AppliedBuffStatGate)
			AppliedBuffStatInstanceKeys.Remove(buffKey);
	}

	private static bool TryReadIntMember(object target, string getterName, out int value)
	{
		value = 0;
		if (target == null || string.IsNullOrEmpty(getterName))
			return false;
		var method = AccessTools.Method(target.GetType(), getterName, Type.EmptyTypes);
		if (method == null || method.ReturnType != typeof(int))
			return false;
		try
		{
			value = (int)method.Invoke(target, null);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryWriteIntMember(object target, string setterName, int value)
	{
		if (target == null || string.IsNullOrEmpty(setterName))
			return false;
		var method = AccessTools.Method(target.GetType(), setterName, new[] { typeof(int) });
		if (method == null)
			return false;
		try
		{
			method.Invoke(target, new object[] { value });
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadFloatMember(object target, string getterName, out float value)
	{
		value = 0f;
		if (target == null || string.IsNullOrEmpty(getterName))
			return false;
		var method = AccessTools.Method(target.GetType(), getterName, Type.EmptyTypes);
		if (method == null)
			return false;
		try
		{
			var raw = method.Invoke(target, null);
			if (raw is float f) { value = f; return true; }
			if (raw is double d) { value = (float)d; return true; }
			return false;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryWriteFloatMember(object target, string setterName, float value)
	{
		if (target == null || string.IsNullOrEmpty(setterName))
			return false;
		var method = AccessTools.Method(target.GetType(), setterName, new[] { typeof(float) });
		if (method == null)
			return false;
		try
		{
			method.Invoke(target, new object[] { value });
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryDispatchBuffEvent(object nativeSourceObject, object buffManager, object rawBuff, out string failReason)
	{
		if (nativeSourceObject == null) { failReason = "native buff event source is null"; return false; }
		if (rawBuff == null) { failReason = "raw buff object is null"; return false; }
		var buffReceiver = ReadFirstExactMember(buffManager, buffManager?.GetType(), GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers);
		if (buffReceiver == null) { failReason = "exact buff manager receiver was not resolved for event construction"; return false; }
		// Hub path is Unit/field-object.cfng → dxx.ceih → ecz.cfhc. nativeSourceObject may
		// already be ceig (ability source); that type does not own cfng, so probe the
		// receiver's field-object when the direct read misses.
		var abilityManager = ReadFirstExactMember(nativeSourceObject, nativeSourceObject.GetType(), GameSymbols.BuffDebuffLaws.BuffSourceAbilityManagerMembers);
		if (abilityManager == null)
		{
			var receiverObject = ReadFirstExactMember(buffReceiver, buffReceiver.GetType(), GameSymbols.BuffDebuffLaws.BuffReceiverObjectMembers);
			abilityManager = ReadFirstExactMember(receiverObject, receiverObject?.GetType(), GameSymbols.BuffDebuffLaws.BuffSourceAbilityManagerMembers);
		}
		var eventContext = ReadFirstExactMember(abilityManager, abilityManager?.GetType(), GameSymbols.BuffDebuffLaws.BuffAbilityManagerEventContextMembers);
		var eventSource = ReadFirstExactMember(eventContext, eventContext?.GetType(), GameSymbols.BuffDebuffLaws.BuffEventContextEventHubMembers);
		if (eventSource == null)
		{
			failReason = "exact buff event hub cfng.ceih.cfhc was not resolved from source=" + DescribeObject(nativeSourceObject) + "; abilityManager=" + DescribeObject(abilityManager) + "; eventContext=" + DescribeObject(eventContext);
			return false;
		}
		if (!TryResolveBuffEventDispatch(eventSource, buffReceiver, rawBuff, out failReason))
			return false;
		try
		{
			var parameters = _buffEventArgsConstructor.GetParameters();
			var argsType = Enum.Parse(parameters[3].ParameterType, "Receiving");
			// Live BuffEventArgs ctor is (buffReceiver, buff, bool, EArgsType, castArgs).
			var eventArgs = _buffEventArgsConstructor.Invoke(new[] { buffReceiver, rawBuff, true, argsType, null });
			// ISIL dxx.baqj / eda.bcja: hub.bcja(senderObject, args). The Object sender is the
			// ability/native source (baqj's `a`), NOT the event hub itself. Passing the hub as
			// both `this` and arg0 was live-negative (TargetInvocationException and/or has-by-SID
			// miss after a non-null bbgf return with correct rawBuff.sid).
			_buffEventDispatchMethod.Invoke(eventSource, new[] { nativeSourceObject, eventArgs });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			var root = ex.GetBaseException();
			failReason = "native buff event dispatch failed: "
			             + ex.GetType().Name
			             + ": "
			             + ex.Message
			             + "; root="
			             + root.GetType().Name
			             + ": "
			             + root.Message
			             + "; eventHub="
			             + DescribeObject(eventSource)
			             + "; sender="
			             + DescribeObject(nativeSourceObject)
			             + "; rawBuff="
			             + DescribeObject(rawBuff);
			return false;
		}
	}

	private static bool TryResolveBuffEventDispatch(object eventSource, object buffReceiver, object rawBuff, out string failReason)
	{
		if (!TryResolveAdd(out failReason)) return false;
		_buffEventArgsType ??= GameMember.FindType(GameSymbols.BuffDebuffLaws.BuffEventArgsTypeId, GameSymbols.BuffDebuffLaws.BuffEventArgsTypeHint);
		if (_buffEventArgsType == null)
		{
			failReason = "BuffEventArgs type was not found";
			return false;
		}
		_buffEventArgsConstructor ??= ResolveExactBuffEventArgsConstructor(_buffEventArgsType, buffReceiver.GetType(), rawBuff.GetType());
		if (_buffEventArgsConstructor == null)
		{
			failReason = "exact BuffEventArgs receiving constructor was not found for receiver=" + DescribeObject(buffReceiver) + "; buff=" + DescribeObject(rawBuff);
			return false;
		}
		_buffEventDispatchMethod ??= ResolveExactMethodOnTypeHierarchy(eventSource.GetType(), GameSymbols.BuffDebuffLaws.BuffEventDispatch, 2, typeof(void), _buffEventArgsType);
		if (_buffEventDispatchMethod == null)
		{
			failReason = "exact eda.bcja buff event dispatch method was not found for eventSource=" + DescribeObject(eventSource);
			return false;
		}
		failReason = null;
		return true;
	}

	private static ConstructorInfo ResolveExactBuffEventArgsConstructor(Type eventArgsType, Type eventSourceType, Type rawBuffType)
	{
		if (eventArgsType == null || eventSourceType == null || rawBuffType == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var ctor in eventArgsType.GetConstructors(flags))
		{
			var parameters = ctor.GetParameters();
			if (parameters.Length != 5)
				continue;
			if (!parameters[0].ParameterType.IsAssignableFrom(eventSourceType))
				continue;
			if (!parameters[1].ParameterType.IsAssignableFrom(rawBuffType))
				continue;
			if (parameters[2].ParameterType != typeof(bool))
				continue;
			if (!parameters[3].ParameterType.IsEnum || !string.Equals(parameters[3].ParameterType.Name, "EArgsType", StringComparison.Ordinal))
				continue;
			return ctor;
		}
		return null;
	}
	private static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		_buffManagerType = GameMember.FindType(
			GameSymbols.BuffDebuffLaws.BuffManagerTypeId,
			GameSymbols.BuffDebuffLaws.BuffManagerTypeHint);
		if (_buffManagerType == null)
			return FailResolve("buff manager type was not found", out failReason);

		_hasBySidMethod = ResolveExactMethod(_buffManagerType, GameSymbols.BuffDebuffLaws.BuffHasBySid, 1, typeof(bool));
		if (_hasBySidMethod == null)
			return FailResolve("exact buff has-by-SID method was not found", out failReason);

		_listBySidMethod = ResolveExactMethod(_buffManagerType, GameSymbols.BuffDebuffLaws.BuffListBySid, 1, null);
		if (_listBySidMethod == null)
			return FailResolve("exact buff list-by-SID method was not found", out failReason);

		failReason = null;
		return true;
	}

	private static MethodInfo ResolveExactMethodOnTypeHierarchy(Type type, GameSymbols.MethodSymbol symbol, int parameterCount, Type returnType, Type firstParameterBaseType)
	{
		if (type == null || symbol.NameHints == null)
			return null;
		foreach (var name in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				foreach (var method in current.GetMethods(flags))
				{
					if (!string.Equals(method.Name, name, StringComparison.Ordinal))
						continue;
					if (method.IsSpecialName || method.GetParameters().Length != parameterCount)
						continue;
					if (returnType != null && method.ReturnType != returnType)
						continue;
					var parameters = method.GetParameters();
					if (parameterCount == 1 && firstParameterBaseType != null && !parameters[0].ParameterType.IsAssignableFrom(firstParameterBaseType))
						continue;
					// Interop dispatch senders are Il2CppSystem.Object, not managed System.Object;
					// requiring typeof(object) silently rejected the correct eda.bcja dispatcher.
					if (parameterCount == 2 && (parameters[0].ParameterType != typeof(Il2CppSystem.Object) || (firstParameterBaseType != null && !parameters[1].ParameterType.IsAssignableFrom(firstParameterBaseType))))
						continue;
					return method;
				}
			}
		}
		return null;
	}
	private static MethodInfo ResolveExactMethod(Type type, GameSymbols.MethodSymbol symbol, int parameterCount, Type returnType)
	{
		if (type == null || symbol.NameHints == null)
			return null;
		foreach (var name in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName || method.GetParameters().Length != parameterCount)
					continue;
				if (returnType != null && method.ReturnType != returnType)
					continue;
				return method;
			}
		}
		return null;
	}

	private static bool ValidateManager(object buffManager, out string failReason)
	{
		if (buffManager == null)
		{
			failReason = "buff manager is null";
			return false;
		}
		if (_buffManagerType == null)
		{
			failReason = "buff manager type is unresolved";
			return false;
		}
		if (!_buffManagerType.IsInstanceOfType(buffManager))
		{
			failReason = "object is not a resolved native buff manager";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryInvokeHas(object buffManager, string sid, out bool hasSid, out string failReason)
	{
		hasSid = false;
		try
		{
			var raw = _hasBySidMethod.Invoke(buffManager, new object[] { sid });
			if (raw is bool result)
			{
				hasSid = result;
				failReason = null;
				return true;
			}
			failReason = "buff has-by-SID returned non-boolean result";
			return false;
		}
		catch (Exception ex)
		{
			failReason = "buff has-by-SID invocation failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryInvokeListCount(object buffManager, string sid, out int count, out string failReason)
	{
		count = -1;
		try
		{
			var raw = _listBySidMethod.Invoke(buffManager, new object[] { sid });
			if (raw == null)
			{
				count = 0;
				failReason = null;
				return true;
			}
			if (!TryReadIl2CppCollectionCount(raw, out count, out failReason))
				return false;
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "buff list-by-SID invocation failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryReadIl2CppCollectionCount(object collection, out int count, out string failReason)
	{
		count = -1;
		if (collection == null)
		{
			count = 0;
			failReason = null;
			return true;
		}
		var type = collection.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var getter = type.GetMethod("get_Count", flags, null, Type.EmptyTypes, null);
			if (getter != null && getter.ReturnType == typeof(int))
			{
				count = (int)getter.Invoke(collection, Array.Empty<object>());
				failReason = null;
				return true;
			}
			var prop = type.GetProperty("Count", flags);
			if (prop != null && prop.GetIndexParameters().Length == 0 && prop.PropertyType == typeof(int))
			{
				count = (int)prop.GetValue(collection, null);
				failReason = null;
				return true;
			}
		}
		catch (Exception ex)
		{
			failReason = "buff list Count read failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
		failReason = "buff list-by-SID result has no get_Count/Count: " + DescribeType(type);
		return false;
	}

	private static string ProbeAllBooleanStringMethods(object buffManager, string sid)
	{
		if (buffManager == null || _buffManagerType == null || string.IsNullOrWhiteSpace(sid))
			return "n/a";
		var parts = new List<string>();
		foreach (var method in AccessTools.GetDeclaredMethods(_buffManagerType))
		{
			if (method.ReturnType != typeof(bool) || method.GetParameters().Length != 1)
				continue;
			if (method.GetParameters()[0].ParameterType != typeof(string))
				continue;
			try
			{
				var raw = method.Invoke(buffManager, new object[] { sid });
				parts.Add(method.Name + "=" + (raw is bool b ? b.ToString() : DescribeObject(raw)));
			}
			catch (Exception ex)
			{
				parts.Add(method.Name + "=ERR:" + ex.GetBaseException().GetType().Name);
			}
		}
		return parts.Count == 0 ? "none" : string.Join(",", parts);
	}

	private static object ReadFirstExactMember(object value, Type type, string[] names)
	{
		if (value == null || type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				var fromType = ReadExactMemberOnDeclaredType(value, current, name);
				if (fromType != null)
					return fromType;
			}
			foreach (var iface in type.GetInterfaces())
			{
				var fromInterface = ReadExactMemberOnDeclaredType(value, iface, name);
				if (fromInterface != null)
					return fromInterface;
			}
		}
		return null;
	}

	private static object ReadExactMemberOnDeclaredType(object value, Type declaredType, string name)
	{
		if (value == null || declaredType == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		try
		{
			var field = declaredType.GetField(name, flags);
			if (field != null)
				return field.GetValue(value);
		}
		catch
		{
		}
		try
		{
			var property = declaredType.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
				return property.GetValue(value, null);
		}
		catch
		{
		}
		try
		{
			var method = declaredType.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
				return method.Invoke(value, null);
		}
		catch
		{
		}
		return null;
	}
	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static string TryReadBuffInstanceSid(object rawBuff)
	{
		if (rawBuff == null)
			return null;
		try
		{
			var type = rawBuff.GetType();
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var property = type.GetProperty("sid", flags) ?? type.GetProperty("get_sid", flags);
			if (property != null && property.PropertyType == typeof(string) && property.CanRead)
				return property.GetValue(rawBuff) as string;
			var getter = type.GetMethod("get_sid", flags, null, Type.EmptyTypes, null);
			if (getter != null && getter.ReturnType == typeof(string))
				return getter.Invoke(rawBuff, null) as string;
			var field = type.GetField("sid", flags);
			if (field != null && field.FieldType == typeof(string))
				return field.GetValue(rawBuff) as string;
		}
		catch
		{
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "unresolved";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}
}


