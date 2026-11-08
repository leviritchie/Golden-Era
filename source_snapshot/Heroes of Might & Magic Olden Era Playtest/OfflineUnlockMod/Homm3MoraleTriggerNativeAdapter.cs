using System;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for morale roll surfaces.
/// Source-prepared from June 18 decomp evidence. This class does not register
/// Harmony patches, does not invoke morale rolls, and does not mutate action
/// scheduling. It only centralizes exact method resolution/classification for
/// future morale packet handlers after runtime ordering proof is promoted.
/// </summary>
internal static class Homm3MoraleTriggerNativeAdapter
{
	internal enum MoraleRollKind
	{
		Unknown = 0,
		Positive = 1,
		Negative = 2,
	}

	internal readonly struct MoraleRollObservation
	{
		internal readonly MoraleRollKind Kind;
		internal readonly bool ReturnedTrue;
		internal readonly string MethodName;

		internal MoraleRollObservation(MoraleRollKind kind, bool returnedTrue, string methodName)
		{
			Kind = kind;
			ReturnedTrue = returnedTrue;
			MethodName = methodName;
		}

		internal bool PositiveCandidateReturnedTrue => Kind == MoraleRollKind.Positive && ReturnedTrue;

		internal bool NegativeCandidateReturnedTrue => Kind == MoraleRollKind.Negative && ReturnedTrue;

		public override string ToString()
		{
			return "kind=" + Kind
			       + " returnedTrue=" + ReturnedTrue
			       + " method=" + (MethodName ?? "?")
			       + " semanticBoundary=roll-result-not-yet-proven-as-trigger";
		}
	}

	private static Type _battleLogicType;
	private static Type _unitType;
	private static MethodInfo _positiveMoraleRoll;
	private static MethodInfo _negativeMoraleRoll;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryClassifyRoll(MethodBase method, out MoraleRollKind kind, out string failReason)
	{
		kind = MoraleRollKind.Unknown;
		if (!TryResolve(out failReason))
			return false;
		if (method == null)
		{
			failReason = "method is null";
			return false;
		}

		if (ReferenceEquals(method, _positiveMoraleRoll)
		    || NameMatches(method.Name, GameSymbols.MoraleTriggerLaws.PositiveMoraleRoll.NameHints))
		{
			kind = MoraleRollKind.Positive;
			failReason = null;
			return true;
		}

		if (ReferenceEquals(method, _negativeMoraleRoll)
		    || NameMatches(method.Name, GameSymbols.MoraleTriggerLaws.NegativeMoraleRoll.NameHints))
		{
			kind = MoraleRollKind.Negative;
			failReason = null;
			return true;
		}

		failReason = "method is not an exact morale roll surface";
		return false;
	}

	internal static bool TryObserveRollResult(MethodBase method, bool rollResult, out MoraleRollObservation observation, out string failReason)
	{
		observation = default;
		if (!TryClassifyRoll(method, out var kind, out failReason))
			return false;
		observation = new MoraleRollObservation(kind, rollResult, method?.Name);
		failReason = null;
		return true;
	}

	internal static bool TryGetRollMethods(out MethodInfo positiveRoll, out MethodInfo negativeRoll, out string failReason)
	{
		positiveRoll = null;
		negativeRoll = null;
		if (!TryResolve(out failReason))
			return false;
		positiveRoll = _positiveMoraleRoll;
		negativeRoll = _negativeMoraleRoll;
		return true;
	}

	internal static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		_battleLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.MoraleTriggerLawsBattleLogic);
		_unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);

		if (_battleLogicType == null)
			return FailResolve("battle logic type was not found", out failReason);
		if (_unitType == null)
			return FailResolve("battle Unit type was not found", out failReason);

		_positiveMoraleRoll = ResolveExactMoraleMethod(
			_battleLogicType,
			_unitType,
			GameSymbols.MoraleTriggerLaws.PositiveMoraleRoll,
			2,
			false);
		_negativeMoraleRoll = ResolveExactMoraleMethod(
			_battleLogicType,
			_unitType,
			GameSymbols.MoraleTriggerLaws.NegativeMoraleRoll,
			3,
			true);

		if (_positiveMoraleRoll == null)
			return FailResolve("positive morale roll method was not found by exact name and signature", out failReason);
		if (_negativeMoraleRoll == null)
			return FailResolve("negative morale roll method was not found by exact name and signature", out failReason);

		failReason = null;
		return true;
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static MethodInfo ResolveExactMoraleMethod(Type type, Type unitType, GameSymbols.MethodSymbol symbol, int parameterCount, bool requiresThirdBool)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!NameMatches(method.Name, symbol.NameHints))
				continue;
			if (method.IsSpecialName || method.ReturnType != typeof(bool))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != parameterCount)
				continue;
			if (!IsExactBattleUnitParameter(parameters[0].ParameterType, unitType))
				continue;
			if (!IsRandomParameter(parameters[1].ParameterType))
				continue;
			if (requiresThirdBool && parameters[2].ParameterType != typeof(bool))
				continue;
			return method;
		}

		return null;
	}

	private static bool NameMatches(string name, string[] hints)
	{
		for (var i = 0; i < hints.Length; i++)
		{
			if (string.Equals(name, hints[i], StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool IsExactBattleUnitParameter(Type parameterType, Type resolvedUnitType)
	{
		if (parameterType == null)
			return false;
		if (resolvedUnitType != null && parameterType == resolvedUnitType)
			return true;
		return string.Equals(parameterType.FullName, "Hex.Session.Battle.Unit", StringComparison.Ordinal)
		       || string.Equals(parameterType.Name, "Unit", StringComparison.Ordinal);
	}

	private static bool IsRandomParameter(Type type)
	{
		return type == typeof(Random)
		       || string.Equals(type?.FullName, "Il2CppSystem.Random", StringComparison.Ordinal)
		       || string.Equals(type?.Name, "Random", StringComparison.Ordinal);
	}
}
