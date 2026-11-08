using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Text;

namespace OfflineUnlockMod;

// Runtime side of the build-scoped GameSymbols hints (docs/port_to_current_game_version.md,
// "Phase 2/3 current scopes"). GameSymbolsCurrent.g.cs, generated from the P1 remap by
// tools/port_current/generate_current_symbol_scopes.py, gives each GameSymbols class a static
// constructor that calls into this class on the current build only:
//   - scoped declarations get the live literals, position for position, so GameMember and every
//     direct consumer (foreach over a hint array, AccessTools with a hint) sees live names;
//   - refused declarations get the refusal sentinel in every position. The sentinel cannot name a
//     type or member, keeps array lengths, and makes GameMember refuse with a clear log.
// On Golden Era and unknown builds RewriteForCurrentBuild is false and nothing here runs, so Golden
// Era resolution is unchanged. Never throws: a failure refuses the declaration instead (a throwing
// static constructor would take the whole GameSymbols class down).
internal static class GameSymbolScope
{
	internal const string SentinelPrefix = "!unresolved-on-current-build:";

	private sealed class Entry
	{
		internal string Symbol;
		internal string[] Owners;     // runtime full names; null = no owner check
		internal bool Refused;
		internal string Reason;
	}

	private static readonly object Gate = new();
	private static readonly Dictionary<string[], Entry> ByArray = new(ArrayIdentity.Instance);
	private static readonly Dictionary<string, Type> VerifiedTypes = new(StringComparer.Ordinal);
	private static readonly HashSet<string> OwnerRefusalsLogged = new(StringComparer.Ordinal);
	private static int _scoped, _refused, _positionsRefused;

	internal static bool RewriteForCurrentBuild => GameBuild.Kind == GameBuildKind.Current;

	internal static int ScopedCount => _scoped;
	internal static int RefusedCount => _refused;

	internal static bool IsSentinel(string hint) =>
		hint != null && hint.StartsWith(SentinelPrefix, StringComparison.Ordinal);

	/// <summary>True when the array is a generated current-build scope (scoped or refused).</summary>
	internal static bool IsScoped(string[] hints)
	{
		if (hints == null)
			return false;
		lock (Gate)
			return ByArray.ContainsKey(hints);
	}

	/// <summary>Reason a scoped array was refused, or null when it is not a refused scope.</summary>
	internal static string RefusalReason(string[] hints)
	{
		if (hints == null)
			return null;
		lock (Gate)
			return ByArray.TryGetValue(hints, out var e) && e.Refused ? e.Symbol + ": " + e.Reason : null;
	}

	/// <summary>
	/// A type literal of a scoped type array resolved, at scope time, to exactly this live type of the
	/// pinned shape. GameMember's off-Golden build gate accepts obfuscated types reached this way.
	/// </summary>
	internal static bool IsVerifiedType(string hint, Type resolved)
	{
		if (hint == null || resolved == null)
			return false;
		lock (Gate)
			return VerifiedTypes.TryGetValue(hint, out var t) && t == resolved;
	}

	/// <summary>
	/// Owner check for member hint arrays: on the current build a scoped member array was mapped on
	/// specific live owner types; a lookup on a type whose hierarchy contains none of them is refused
	/// (false) and logged once per symbol and type. Arrays without owners always pass.
	/// </summary>
	internal static bool CheckOwner(string id, string[] hints, Type declaringType)
	{
		if (hints == null || declaringType == null || !RewriteForCurrentBuild)
			return true;
		Entry entry;
		lock (Gate)
		{
			if (!ByArray.TryGetValue(hints, out entry) || entry.Owners == null || entry.Owners.Length == 0)
				return true;
		}
		for (var t = declaringType; t != null; t = t.BaseType)
		{
			var name = t.FullName;
			foreach (var owner in entry.Owners)
				if (string.Equals(owner, name, StringComparison.Ordinal))
					return true;
		}
		var key = entry.Symbol + "|" + declaringType.FullName;
		bool first;
		lock (Gate)
			first = OwnerRefusalsLogged.Add(key);
		if (first)
			Plugin.LogSource?.LogError("GameSymbols current scope REFUSED owner: " + id + " (" + entry.Symbol + ") looked up on "
				+ declaringType.FullName + ", but its live names were mapped on " + string.Join(", ", entry.Owners)
				+ "; " + GameBuild.Describe() + ". This surface is unavailable.");
		return false;
	}

	internal static string Describe() =>
		"GameSymbols current scopes (remap " + GameSymbols.CurrentScopes.BuildId + "): generated " + GameSymbols.CurrentScopes.Scoped
		+ " scoped / " + GameSymbols.CurrentScopes.Refused + " refused; applied so far " + _scoped + " scoped / " + _refused
		+ " refused, " + _positionsRefused + " refused literal position(s).";

	// ------------------------------------------------------------------------------------------
	// Generated-code entry points (GameSymbolsCurrent.g.cs)
	// ------------------------------------------------------------------------------------------

	internal static string[] Types(string symbol, string[] golden, uint hash, string[] live, string[] checks)
	{
		try
		{
			if (!Matches(symbol, golden, hash, live))
				return Refuse(symbol, golden, hash, "golden hints changed since generation");
			var result = new string[live.Length];
			var kept = 0;
			for (var i = 0; i < live.Length; i++)
			{
				var check = checks != null && i < checks.Length ? checks[i] : null;
				if (live[i] == null)
				{
					result[i] = Sentinel(symbol);
					_positionsRefused++;
				}
				else if (check != null && !VerifyType(symbol, live[i], check))
				{
					result[i] = Sentinel(symbol);
					_positionsRefused++;
				}
				else
				{
					result[i] = live[i];
					kept++;
				}
			}
			if (kept == 0)
				return Refuse(symbol, golden, hash, "no live type literal survived verification");
			Register(result, symbol, null, false, null);
			return result;
		}
		catch (Exception ex)
		{
			return Refuse(symbol, golden, hash, "scope failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static string[] Members(string symbol, string[] golden, uint hash, string[] live, string owners)
	{
		try
		{
			if (!Matches(symbol, golden, hash, live))
				return Refuse(symbol, golden, hash, "golden hints changed since generation");
			var result = Substitute(symbol, live);
			Register(result, symbol, SplitOwners(owners), false, null);
			return result;
		}
		catch (Exception ex)
		{
			return Refuse(symbol, golden, hash, "scope failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static string[] Refuse(string symbol, string[] golden, uint hash, string reason)
	{
		var result = Sentinels(symbol, golden?.Length ?? 0);
		Register(result, symbol, null, true, reason);
		LogRefusal(symbol, reason);
		return result;
	}

	// Single-literal declarations (`internal static readonly string X = "..."`; formerly const strings, which a
	// static constructor cannot rewrite). Same rules as the array forms, one position.
	internal static string Type(string symbol, string golden, uint hash, string live, string check) =>
		Types(symbol, new[] { golden }, hash, new[] { live }, new[] { check })[0];

	internal static string Member(string symbol, string golden, uint hash, string live, string owners) =>
		Members(symbol, new[] { golden }, hash, new[] { live }, owners)[0];

	internal static string RefuseOne(string symbol, string golden, uint hash, string reason) =>
		Refuse(symbol, new[] { golden }, hash, reason)[0];

	internal static GameSymbols.MethodSymbol Method(string symbol, GameSymbols.MethodSymbol golden, uint hash, string[] live, string owners)
	{
		var hints = Members(symbol, golden.NameHints, hash, live, owners);
		return new GameSymbols.MethodSymbol(golden.Id, hints);
	}

	/// <summary>
	/// A Golden Era method the live build split into several methods with a changed signature (generator override
	/// with <c>"split": true</c>, backed by recorded native-body evidence). Unlike <see cref="Method"/>, the live
	/// hint count may differ from the golden one, so each hint names one live method, not an alias: a consumer of
	/// such a symbol must bind every hint (GameMember.FindEveryMethodByNames). The golden literals are still hash
	/// pinned, and the live names still carry their owner check.
	/// </summary>
	internal static GameSymbols.MethodSymbol MethodSplit(string symbol, GameSymbols.MethodSymbol golden, uint hash, string[] live, string owners)
	{
		try
		{
			if (golden.NameHints == null || Hash(golden.NameHints) != hash)
				return RefuseMethod(symbol, golden, hash, "golden hints changed since generation");
			if (live == null || live.Length == 0)
				return RefuseMethod(symbol, golden, hash, "split scope lists no live method");
			var result = Substitute(symbol, live);
			Register(result, symbol, SplitOwners(owners), false, null);
			return new GameSymbols.MethodSymbol(golden.Id, result);
		}
		catch (Exception ex)
		{
			return RefuseMethod(symbol, golden, hash, "scope failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static GameSymbols.MethodSymbol RefuseMethod(string symbol, GameSymbols.MethodSymbol golden, uint hash, string reason)
	{
		return new GameSymbols.MethodSymbol(golden.Id, Refuse(symbol, golden.NameHints, hash, reason));
	}

	internal static GameSymbols.FieldSymbol Field(string symbol, GameSymbols.FieldSymbol golden, uint hash, string[] live, string owners)
	{
		var pair = Members(symbol, new[] { golden.NativeFieldInfoName, golden.FieldName }, hash, live, owners);
		return new GameSymbols.FieldSymbol(golden.Id, pair[0], pair[1]);
	}

	internal static GameSymbols.FieldSymbol RefuseField(string symbol, GameSymbols.FieldSymbol golden, uint hash, string reason)
	{
		var pair = Refuse(symbol, new[] { golden.NativeFieldInfoName, golden.FieldName }, hash, reason);
		return new GameSymbols.FieldSymbol(golden.Id, pair[0], pair[1]);
	}

	internal static GameSymbols.MethodSymbol[] Methods(string symbol, GameSymbols.MethodSymbol[] golden, uint hash, string[][] live, string owners)
	{
		try
		{
			var flatGolden = FlattenHints(golden, out var lengths);
			var flatLive = Flatten(live);
			if (!SameShape(lengths, live))
				return RefuseMethods(symbol, golden, hash, "element layout changed since generation");
			var flat = Members(symbol, flatGolden, hash, flatLive, owners);
			var result = new GameSymbols.MethodSymbol[golden.Length];
			var k = 0;
			for (var i = 0; i < golden.Length; i++)
			{
				var hints = new string[lengths[i]];
				Array.Copy(flat, k, hints, 0, hints.Length);
				k += hints.Length;
				result[i] = new GameSymbols.MethodSymbol(golden[i].Id, hints);
				Register(hints, symbol, SplitOwners(owners), AllSentinel(hints), reason: null, count: false);
			}
			return result;
		}
		catch (Exception ex)
		{
			return RefuseMethods(symbol, golden, hash, "scope failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static GameSymbols.MethodSymbol[] RefuseMethods(string symbol, GameSymbols.MethodSymbol[] golden, uint hash, string reason)
	{
		golden ??= Array.Empty<GameSymbols.MethodSymbol>();
		var result = new GameSymbols.MethodSymbol[golden.Length];
		for (var i = 0; i < golden.Length; i++)
		{
			var hints = Sentinels(symbol, golden[i].NameHints.Length);
			Register(hints, symbol, null, true, reason, count: false);
			result[i] = new GameSymbols.MethodSymbol(golden[i].Id, hints);
		}
		_refused++;
		LogRefusal(symbol, reason);
		return result;
	}

	internal static GameSymbols.FieldSymbol[] Fields(string symbol, GameSymbols.FieldSymbol[] golden, uint hash, string[][] live, string owners)
	{
		try
		{
			var flatGolden = new string[golden.Length * 2];
			var lengths = new int[golden.Length];
			for (var i = 0; i < golden.Length; i++)
			{
				flatGolden[2 * i] = golden[i].NativeFieldInfoName;
				flatGolden[2 * i + 1] = golden[i].FieldName;
				lengths[i] = 2;
			}
			if (!SameShape(lengths, live))
				return RefuseFields(symbol, golden, hash, "element layout changed since generation");
			var flat = Members(symbol, flatGolden, hash, Flatten(live), owners);
			var result = new GameSymbols.FieldSymbol[golden.Length];
			for (var i = 0; i < golden.Length; i++)
				result[i] = new GameSymbols.FieldSymbol(golden[i].Id, flat[2 * i], flat[2 * i + 1]);
			return result;
		}
		catch (Exception ex)
		{
			return RefuseFields(symbol, golden, hash, "scope failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static GameSymbols.FieldSymbol[] RefuseFields(string symbol, GameSymbols.FieldSymbol[] golden, uint hash, string reason)
	{
		golden ??= Array.Empty<GameSymbols.FieldSymbol>();
		var result = new GameSymbols.FieldSymbol[golden.Length];
		var s = Sentinel(symbol);
		for (var i = 0; i < golden.Length; i++)
			result[i] = new GameSymbols.FieldSymbol(golden[i].Id, s, s);
		_refused++;
		LogRefusal(symbol, reason);
		return result;
	}

	internal static (string Name, int ParameterCount)[] NamedCounts(string symbol, (string Name, int ParameterCount)[] golden, uint hash, string[] live, string owners)
	{
		golden ??= Array.Empty<(string Name, int ParameterCount)>();
		var names = new string[golden.Length];
		for (var i = 0; i < golden.Length; i++)
			names[i] = golden[i].Name;
		var mapped = Members(symbol, names, hash, live, owners);
		var result = new (string Name, int ParameterCount)[golden.Length];
		for (var i = 0; i < golden.Length; i++)
			result[i] = (mapped[i], golden[i].ParameterCount);
		return result;
	}

	internal static (string Name, int ParameterCount)[] RefuseNamedCounts(string symbol, (string Name, int ParameterCount)[] golden, uint hash, string reason)
	{
		golden ??= Array.Empty<(string Name, int ParameterCount)>();
		var s = Sentinel(symbol);
		var result = new (string Name, int ParameterCount)[golden.Length];
		for (var i = 0; i < golden.Length; i++)
			result[i] = (s, golden[i].ParameterCount);
		_refused++;
		LogRefusal(symbol, reason);
		return result;
	}

	internal static GameSymbols.TypeHintGroup WithCurrent(GameSymbols.TypeHintGroup group, GameSymbols.TypeHintScope current)
	{
		if (group == null)
			return null;
		return new GameSymbols.TypeHintGroup(group.Id, group.Golden, current);
	}

	// ------------------------------------------------------------------------------------------

	/// <summary>FNV-1a 32 over UTF-8 of the values joined by U+001F (tools/port_current/generate_current_symbol_scopes.py fnv1a32).</summary>
	internal static uint Hash(string[] values)
	{
		var h = 0x811C9DC5u;
		if (values == null)
			return h;
		var joined = string.Join("\u001f", values);
		foreach (var b in Encoding.UTF8.GetBytes(joined))
		{
			h ^= b;
			h *= 0x01000193u;
		}
		return h;
	}

	private static bool Matches(string symbol, string[] golden, uint hash, string[] live)
	{
		if (golden == null || live == null || golden.Length != live.Length)
			return false;
		return Hash(golden) == hash;
	}

	private static string[] Substitute(string symbol, string[] live)
	{
		var result = new string[live.Length];
		for (var i = 0; i < live.Length; i++)
		{
			if (live[i] == null)
			{
				result[i] = Sentinel(symbol);
				_positionsRefused++;
			}
			else
			{
				result[i] = live[i];
			}
		}
		return result;
	}

	private static bool VerifyType(string symbol, string literal, string check)
	{
		// check = runtimeFullName|base|fields|methods|obfuscatedName
		var parts = check.Split('|');
		if (parts.Length != 5 || !int.TryParse(parts[2], out var fields) || !int.TryParse(parts[3], out var methods))
		{
			Plugin.LogSource?.LogError("GameSymbols current scope: malformed type check for " + symbol + ": " + check);
			return false;
		}
		Type found = null;
		var hits = 0;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type t = null;
			try { t = asm?.GetType(parts[0], throwOnError: false); } catch { }
			if (t == null)
				continue;
			hits++;
			found ??= t;
		}
		string why = null;
		if (hits != 1)
			why = hits + " loaded type(s) named " + parts[0];
		else
		{
			var observed = GameMember.ObserveTypeShape(found);
			var expected = new GameSymbols.TypeShape(parts[1], fields, methods);
			if (observed.Fields != expected.Fields || observed.Methods != expected.Methods
				|| !string.Equals(observed.BaseType, expected.BaseType, StringComparison.Ordinal))
				why = "shape " + observed + " != pinned " + expected;
			else if (parts[4].Length > 0 && !string.Equals(GameMember.ReadObfuscatedName(found), parts[4], StringComparison.Ordinal))
				why = "ObfuscatedName '" + GameMember.ReadObfuscatedName(found) + "' != pinned '" + parts[4] + "'";
		}
		if (why != null)
		{
			Plugin.LogSource?.LogError("GameSymbols current scope: " + symbol + " type literal '" + literal + "' REFUSED (" + why
				+ "); the live interop differs from the one the remap was generated against.");
			return false;
		}
		lock (Gate)
		{
			VerifiedTypes[literal] = found;
			if (!string.Equals(literal, parts[0], StringComparison.Ordinal))
				VerifiedTypes[parts[0]] = found;
		}
		return true;
	}

	private static void Register(string[] array, string symbol, string[] owners, bool refused, string reason, bool count = true)
	{
		lock (Gate)
			ByArray[array] = new Entry { Symbol = symbol, Owners = owners, Refused = refused, Reason = reason };
		if (!count)
			return;
		if (refused)
			_refused++;
		else
			_scoped++;
	}

	private static void LogRefusal(string symbol, string reason)
	{
		Plugin.LogSource?.LogWarning("GameSymbols current scope REFUSED: " + symbol + " - " + reason
			+ ". Every hint of it is the refusal sentinel on " + GameBuild.Describe() + "; features that need it stay off.");
	}

	private static string Sentinel(string symbol) => SentinelPrefix + symbol;

	private static string[] Sentinels(string symbol, int count)
	{
		var s = Sentinel(symbol);
		var result = new string[count];
		for (var i = 0; i < count; i++)
			result[i] = s;
		return result;
	}

	private static bool AllSentinel(string[] hints)
	{
		foreach (var h in hints)
			if (!IsSentinel(h))
				return false;
		return hints.Length > 0;
	}

	private static string[] SplitOwners(string owners) =>
		string.IsNullOrEmpty(owners) ? null : owners.Split(';', StringSplitOptions.RemoveEmptyEntries);

	private static string[] FlattenHints(GameSymbols.MethodSymbol[] symbols, out int[] lengths)
	{
		symbols ??= Array.Empty<GameSymbols.MethodSymbol>();
		lengths = new int[symbols.Length];
		var flat = new List<string>();
		for (var i = 0; i < symbols.Length; i++)
		{
			lengths[i] = symbols[i].NameHints.Length;
			flat.AddRange(symbols[i].NameHints);
		}
		return flat.ToArray();
	}

	private static string[] Flatten(string[][] parts)
	{
		var flat = new List<string>();
		if (parts != null)
			foreach (var p in parts)
				if (p != null)
					flat.AddRange(p);
		return flat.ToArray();
	}

	// netstandard2.1 has no ReferenceEqualityComparer: key hint arrays by identity, never by contents.
	private sealed class ArrayIdentity : IEqualityComparer<string[]>
	{
		internal static readonly ArrayIdentity Instance = new();
		public bool Equals(string[] x, string[] y) => ReferenceEquals(x, y);
		public int GetHashCode(string[] obj) => RuntimeHelpers.GetHashCode(obj);
	}

	private static bool SameShape(int[] lengths, string[][] live)
	{
		if (live == null || live.Length != lengths.Length)
			return false;
		for (var i = 0; i < lengths.Length; i++)
			if (live[i] == null || live[i].Length != lengths[i])
				return false;
		return true;
	}
}
