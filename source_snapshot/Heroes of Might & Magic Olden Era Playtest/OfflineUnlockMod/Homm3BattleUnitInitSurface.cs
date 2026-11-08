using System;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Shared Golden Era <c>Hex.Session.Battle.Unit.Init</c> resolver. Live startup
/// already proves this shape via the battle unit law-owner registry; Factory Split
/// Assembly and diagnostics must reuse it instead of maintaining a stricter private
/// finder that can reject the live method (e.g. bool return).
/// Param[2] must match <see cref="GameSymbols.BattleUnitInit.SideTypeHints"/> (live
/// <c>eir</c> wrapper). Callers that key plans by <c>TransferSide</c> must bridge via
/// <c>BattleSideTransferSideMembers</c> before dictionary lookup — do not treat __args[2]
/// as TransferSide.
/// </summary>
internal static class Homm3BattleUnitInitSurface
{
	internal static MethodInfo FindUnitInitMethod(Type unitType)
	{
		if (unitType == null)
			return null;

		MethodInfo best = null;
		var bestScore = -1;
		var tieCount = 0;
		foreach (var method in unitType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (!MatchesUnitInitShape(method, out var score))
				continue;
			if (best == null || score > bestScore)
			{
				best = method;
				bestScore = score;
				tieCount = 1;
				continue;
			}
			if (score == bestScore)
				tieCount++;
		}

		return best != null && tieCount == 1 ? best : null;
	}

	/// <summary>
	/// Fail-closed diagnostic when <see cref="FindUnitInitMethod"/> returns null.
	/// Lists Init-named / near-shape candidates and whether param[2] matched
	/// <see cref="GameSymbols.BattleUnitInit.SideTypeHints"/>.
	/// </summary>
	internal static string DescribeUnitInitMiss(Type unitType)
	{
		if (unitType == null)
			return "unit type null";
		var parts = new System.Collections.Generic.List<string>();
		foreach (var method in unitType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			var ps = method.GetParameters();
			var nameLooksInit = string.Equals(method.Name, "Init", StringComparison.Ordinal)
			                    || method.Name.IndexOf("Init", StringComparison.Ordinal) >= 0;
			var nearShape = ps.Length == 8 || ps.Length == 10;
			if (!nameLooksInit && !nearShape)
				continue;
			var sideType = ps.Length > 2 ? (ps[2].ParameterType.FullName ?? ps[2].ParameterType.Name) : "?";
			var sideOk = ps.Length > 2 && MatchesSideTypeHint(ps[2].ParameterType);
			var shapeOk = MatchesUnitInitShape(method, out var score);
			parts.Add(
				method.Name
				+ "/"
				+ ps.Length
				+ " ret="
				+ (method.ReturnType?.Name ?? "?")
				+ " side="
				+ sideType
				+ " sideHintMatch="
				+ sideOk
				+ " shapeMatch="
				+ shapeOk
				+ (shapeOk ? (" score=" + score) : ""));
		}
		if (parts.Count == 0)
			return "no Init-named or 8/10-arg candidates on " + (unitType.FullName ?? unitType.Name);
		return "candidates=[" + string.Join(" | ", parts) + "] sideHints=["
		       + string.Join(",", GameSymbols.BattleUnitInit.SideTypeHints ?? Array.Empty<string>())
		       + "]";
	}

	internal static bool MatchesUnitInitShape(MethodInfo method, out int score)
	{
		score = 0;
		if (method == null)
			return false;
		var ps = method.GetParameters();
		if (ps.Length != 8 && ps.Length != 10)
			return false;
		if (ps[0].ParameterType != typeof(int))
			return false;
		// Live Init side arg is eir (SideTypeHints), not TransferSide. Refuse shapes that
		// would let callers treat param[2] as the TransferSide plan-key type.
		if (!MatchesSideTypeHint(ps[2].ParameterType))
			return false;
		if (ps[3].ParameterType == typeof(int) || !LooksLikeBattleHexType(ps[3].ParameterType))
			return false;
		if (ps[4].ParameterType != typeof(int) || ps[5].ParameterType != typeof(int) || ps[6].ParameterType != typeof(int))
			return false;
		if (ps[7].ParameterType != typeof(string))
			return false;
		if (ps.Length == 10 && (ps[8].ParameterType != typeof(bool) || ps[9].ParameterType != typeof(bool)))
			return false;

		score = ps.Length == 10 ? 4 : 3;
		if (method.ReturnType == typeof(bool))
			score++;
		foreach (var hint in GameSymbols.BattleUnitInit.Init.NameHints)
		{
			if (string.Equals(method.Name, hint, StringComparison.Ordinal))
			{
				score += 4;
				break;
			}
		}
		return true;
	}

	private static bool LooksLikeBattleHexType(Type type)
	{
		if (type == null)
			return false;
		if (string.Equals(type.FullName, GameSymbols.BattleUnitInit.HexTypeId, StringComparison.Ordinal))
			return true;
		return type.FullName != null
		       && type.FullName.IndexOf("Session.Battle", StringComparison.Ordinal) >= 0
		       && string.Equals(type.Name, "Hex", StringComparison.Ordinal);
	}

	private static bool MatchesSideTypeHint(Type type)
	{
		if (type == null)
			return false;
		// TransferSide is the plan-key / law-owner leaf, never the live Unit.Init side arg.
		if (string.Equals(type.Name, "TransferSide", StringComparison.Ordinal)
		    || (type.FullName != null
		        && type.FullName.IndexOf("TransferSide", StringComparison.Ordinal) >= 0))
			return false;
		foreach (var hint in GameSymbols.BattleUnitInit.SideTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			if (string.Equals(type.Name, hint, StringComparison.Ordinal)
			    || string.Equals(type.FullName, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}
