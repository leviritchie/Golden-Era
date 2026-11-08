using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

// Central resolver for obfuscated game members. Call sites express what they want by
// shape (return type, parameter types) plus optional historical name hints. The resolver
// returns MethodInfo[] cached per declaring type, and emits one log line per resolution
// so post-patch breakage is visible: if zero hints matched, the obfuscated names rolled
// over but the shape still found something — fix the hints. If zero matches at all, the
// shape changed and a maintainer needs to look.
internal static class GameMember
{
	private static readonly Dictionary<(Type type, string id), MethodInfo[]> _methodCache = new();
	private static readonly Dictionary<(Type type, string id), FieldInfo[]> _fieldCache = new();
	private static readonly Dictionary<string, Type> _typeCache = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, ResolutionRecord> _resolutions = new(StringComparer.Ordinal);
	private static bool DiagnosticsEnabled => Homm3DiagnosticFlags.IsEnabled("game_member_diag.flag");

	internal sealed class ResolutionRecord
	{
		internal string Id;
		internal Type DeclaringType;
		internal int Matches;
		internal int HintHits;
		internal string[] PickedNames;
	}

	// Find all parameterless methods on `declaringType` whose return type equals `returnType`.
	// Methods whose names appear in `nameHints` are returned first, in hint order; remaining
	// matches follow alphabetically. Result is cached per (type, id).
	internal static MethodInfo[] FindParameterlessReturning(
		Type declaringType,
		Type returnType,
		string id,
		params string[] nameHints)
	{
		return FindMethods(declaringType, returnType, Type.EmptyTypes, id, nameHints);
	}

	// Find all methods on `declaringType` matching the given return type and parameter shape.
	// `parameterTypes` is the exact ordered list. Pass `null` for any slot to allow any type
	// in that position (rare; mostly use exact types). Hints bias ordering, same as the
	// parameterless variant. Cached per (type, id).
	internal static MethodInfo[] FindMethods(
		Type declaringType,
		Type returnType,
		Type[] parameterTypes,
		string id,
		params string[] nameHints)
	{
		if (declaringType == null || string.IsNullOrEmpty(id))
			return Array.Empty<MethodInfo>();

		var key = (declaringType, id);
		if (_methodCache.TryGetValue(key, out var cached))
			return cached;
		if (!GameSymbolScope.CheckOwner(id, nameHints, declaringType))
			return _methodCache[key] = Array.Empty<MethodInfo>();

		var hadHints = nameHints != null && nameHints.Any(h => !string.IsNullOrEmpty(h));
		nameHints = FilterOffGoldenMemberHints(id, nameHints);
		var paramCount = parameterTypes?.Length ?? 0;
		var matches = new List<MethodInfo>();
		// Declared-only: patching a base-class method via a subclass type causes the patch
		// to fire for ALL subclasses, not just the one we asked about. Restrict to methods
		// declared on this type. If a patch needs the base method, look it up on the base.
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] declaredMethods;
		try { declaredMethods = declaringType.GetMethods(flags); }
		catch { declaredMethods = Array.Empty<MethodInfo>(); }
		foreach (var m in declaredMethods)
		{
			if (!TryGetParameters(m, out var ps))
				continue;
			if (ps.Length != paramCount)
				continue;
			if (returnType != null && !TypesEquivalent(returnType, m.ReturnType))
				continue;
			var ok = true;
			for (var i = 0; i < paramCount; i++)
			{
				var expected = parameterTypes[i];
				if (expected != null && !TypesEquivalent(expected, ps[i].ParameterType))
				{
					ok = false;
					break;
				}
			}
			if (ok)
				matches.Add(m);
		}

		SortByHints(matches, nameHints);

		// Stale-hint disambiguation: if hints were provided but none matched, only trust
		// the result when the shape filter uniquely identifies a single method. Multiple
		// non-hint matches mean the original named lookup would have been ambiguous —
		// returning the alphabetically-first one would silently re-target patches and
		// invocations to the wrong method. Deobfuscated IL2CPP interop uses Method_* names
		// without ObfuscatedNameAttribute on members; prefer non-PDM lowest ordinal.
		//
		// When any hint hits, return ONLY hint-matching methods. Expanding to every same-shape
		// method (e.g. every parameterless void) caused BhHeroUIElement.OnDisable to be patched
		// as a SideHeroRefresh surface and stack-overflow on combat load.
		var hasHints = nameHints != null && nameHints.Length > 0 && nameHints.Any(h => !string.IsNullOrEmpty(h));
		var hintHits = CountHintHits(matches, nameHints);
		MethodInfo[] result;
		if (hasHints && hintHits > 0)
		{
			var hintIndex = BuildHintIndex(nameHints);
			result = matches.Where(m => MethodMatchesHint(m, hintIndex)).ToArray();
		}
		else if (hadHints && !GameBuild.IsGolden)
		{
			// Off Golden Era a shape-only pick behind stale hints is a guess: refuse.
			result = Array.Empty<MethodInfo>();
		}
		else if (hasHints && hintHits == 0 && matches.Count > 1)
		{
			var deobfMatches = matches.Where(LooksLikeDeobfuscatedInteropMethod).ToList();
			if (deobfMatches.Count > 0)
			{
				deobfMatches.Sort(CompareDeobfuscatedInteropMethods);
				result = new[] { deobfMatches[0] };
			}
			else if (matches.All(LooksLikeDeobfuscatedInteropMethod))
			{
				matches.Sort(CompareDeobfuscatedInteropMethods);
				result = new[] { matches[0] };
			}
			else
			{
				result = Array.Empty<MethodInfo>();
			}
		}
		else
		{
			result = matches.ToArray();
		}
		_methodCache[key] = result;
		RecordResolution(id, declaringType, result.Length, hintHits, matches.Select(m => m.Name).ToArray(), nameHints?.Length ?? 0);
		return result;
	}

	internal static MethodInfo[] FindMethods(
		Type declaringType,
		Type returnType,
		Type[] parameterTypes,
		GameSymbols.MethodSymbol symbol)
	{
		return FindMethods(declaringType, returnType, parameterTypes, symbol.Id, symbol.NameHints);
	}

	internal static MethodInfo FindFirstMethod(
		Type declaringType,
		Type returnType,
		Type[] parameterTypes,
		GameSymbols.MethodSymbol symbol)
	{
		var methods = FindMethods(declaringType, returnType, parameterTypes, symbol);
		return methods.Length == 0 ? null : methods[0];
	}

	internal static Type FindPlacedObjectType(string id, string[] nameHints, Func<string, Type> runtimeLookup)
	{
		if (nameHints == null || nameHints.Length == 0)
			return null;
		for (var i = 0; i < nameHints.Length; i++)
		{
			var name = nameHints[i];
			if (string.IsNullOrEmpty(name))
				continue;
			var type = FindType(id + "." + name, name, () => runtimeLookup?.Invoke(name));
			if (type != null && HasPlacedObjectInitSurface(type))
				return type;
		}
		return null;
	}

	internal static bool HasPlacedObjectInitSurface(Type objectType)
	{
		return FindPlacedObjectInitMethods(objectType, null).Length > 0;
	}

	internal static MethodInfo[] FindPlacedObjectInitMethods(Type objectType, Type metaTypeHint)
	{
		if (objectType == null)
			return Array.Empty<MethodInfo>();

		var shapeMatches = CollectPlacedObjectInitShapeMatches(objectType, metaTypeHint, requireMetaMatch: metaTypeHint != null);
		if (shapeMatches.Count == 0 && metaTypeHint != null)
			shapeMatches = CollectPlacedObjectInitShapeMatches(objectType, metaTypeHint, requireMetaMatch: false);

		var named = shapeMatches.Where(MethodMatchesPlacedObjectInitName).ToArray();
		if (named.Length > 0)
			return named;

		var mapParamType = shapeMatches.Count > 0 ? shapeMatches[0].GetParameters()[0].ParameterType : null;
		var metaParamType = shapeMatches.Count > 0 ? shapeMatches[0].GetParameters()[1].ParameterType : metaTypeHint;
		var resolved = FindMethods(
			objectType,
			typeof(void),
			new[] { mapParamType, metaParamType, typeof(int), typeof(byte), typeof(float) },
			GameSymbols.CustomTownMapBillboard.PlacedObjectInit);
		if (resolved.Length > 0)
			return resolved;

		return Array.Empty<MethodInfo>();
	}

	private static List<MethodInfo> CollectPlacedObjectInitShapeMatches(
		Type objectType,
		Type metaTypeHint,
		bool requireMetaMatch)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var list = new List<MethodInfo>();
		var seen = new HashSet<(Type declaringType, int metadataToken)>();
		for (var current = objectType; current != null; current = current.BaseType)
		{
			MethodInfo[] declaredMethods;
			try { declaredMethods = current.GetMethods(flags); }
			catch { continue; }
			foreach (var m in declaredMethods)
			{
				if (!seen.Add((m.DeclaringType, m.MetadataToken)))
					continue;
				if (m.IsSpecialName || m.ReturnType != typeof(void))
					continue;
				if (!TryGetParameters(m, out var ps))
					continue;
				if (ps.Length != 5)
					continue;
				if (!IsMapLikeType(ps[0].ParameterType))
					continue;
				if (requireMetaMatch && metaTypeHint != null && !TypesEquivalent(metaTypeHint, ps[1].ParameterType))
					continue;
				if (ps[2].ParameterType != typeof(int) || ps[3].ParameterType != typeof(byte) || ps[4].ParameterType != typeof(float))
					continue;
				list.Add(m);
			}
		}
		return list;
	}

	private static bool MethodMatchesPlacedObjectInitName(MethodInfo method)
	{
		if (method == null)
			return false;
		if (string.Equals(method.Name, "Init", StringComparison.Ordinal))
			return true;
		foreach (var hint in GameSymbols.CustomTownMapBillboard.PlacedObjectInit.NameHints)
		{
			if (!string.IsNullOrEmpty(hint) && string.Equals(method.Name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool IsMapLikeType(Type type)
	{
		if (type == null)
			return false;
		if (string.Equals(type.Name, "Map", StringComparison.Ordinal))
			return true;
		return type.FullName != null && type.FullName.EndsWith(".Map", StringComparison.Ordinal);
	}

	// The plugin's own Harmony prefix/postfix by name on its owning plugin type (not a game symbol).
	// Same lookup the runtime files did with a direct AccessTools.Method call; kept here so plugin
	// files carry no raw AccessTools calls (tools/validate_symbol_literal_confinement.py).
	internal static MethodInfo FindOwnedPatchMethod(Type owner, string patchName)
	{
		if (owner == null || string.IsNullOrEmpty(patchName))
			return null;
		return AccessTools.Method(owner, patchName);
	}

	internal static bool IsHarmonyPatchCompatible(MethodInfo target, MethodInfo patch, out string reason)
	{
		reason = null;
		if (target == null || patch == null)
			return true;

		ParameterInfo[] patchParams;
		try { patchParams = patch.GetParameters(); }
		catch (Exception ex)
		{
			reason = "could not inspect patch parameters: " + ex.Message;
			return false;
		}

		foreach (var parameter in patchParams)
		{
			var name = parameter.Name ?? "";
			var type = UnwrapByRef(parameter.ParameterType);
			if (string.Equals(name, "__instance", StringComparison.Ordinal))
			{
				if (target.IsStatic)
				{
					reason = "__instance parameter on static target " + FormatMethod(target);
					return false;
				}
				var declaringType = target.DeclaringType;
				if (type != typeof(object) && declaringType != null && !type.IsAssignableFrom(declaringType))
				{
					reason = "__instance type " + type.FullName + " is not assignable from target owner " + declaringType.FullName;
					return false;
				}
			}
			else if (string.Equals(name, "__result", StringComparison.Ordinal))
			{
				if (target.ReturnType == typeof(void))
				{
					reason = "__result parameter on void target " + FormatMethod(target);
					return false;
				}
				var returnType = UnwrapByRef(target.ReturnType);
				if (type != typeof(object) && returnType != null && !type.IsAssignableFrom(returnType) && !returnType.IsAssignableFrom(type))
				{
					reason = "__result type " + type.FullName + " is incompatible with target return " + returnType.FullName;
					return false;
				}
			}
		}

		return true;
	}

	private static Type UnwrapByRef(Type type)
	{
		if (type == null)
			return null;
		return type.IsByRef ? type.GetElementType() : type;
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "null";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static int CountHintHits(List<MethodInfo> methods, string[] nameHints)
	{
		var hintIndex = BuildHintIndex(nameHints);
		var hits = 0;
		for (var i = 0; i < methods.Count; i++)
			if (MethodMatchesHint(methods[i], hintIndex))
				hits++;
		return hits;
	}

	private static bool MethodMatchesHint(MethodInfo method, Dictionary<string, int> hintIndex)
	{
		if (method == null || hintIndex == null || hintIndex.Count == 0)
			return false;
		if (hintIndex.ContainsKey(method.Name))
			return true;
		var obfuscatedName = TryReadObfuscatedName(method);
		return obfuscatedName != null && hintIndex.ContainsKey(obfuscatedName);
	}

	private static int GetMethodHintRank(MethodInfo method, Dictionary<string, int> hintIndex)
	{
		if (method == null || hintIndex == null || hintIndex.Count == 0)
			return int.MaxValue;
		if (hintIndex.TryGetValue(method.Name, out var rank))
			return rank;
		var obfuscatedName = TryReadObfuscatedName(method);
		if (obfuscatedName != null && hintIndex.TryGetValue(obfuscatedName, out rank))
			return rank;
		return int.MaxValue;
	}

	private static bool LooksLikeDeobfuscatedInteropMethod(MethodInfo method)
	{
		if (method == null)
			return false;
		if (method.Name.StartsWith("Method_", StringComparison.Ordinal))
			return true;
		return method.Name.StartsWith("Method_Public_Virtual_", StringComparison.Ordinal);
	}

	private static bool TryGetParameters(MethodInfo method, out ParameterInfo[] parameters)
	{
		parameters = Array.Empty<ParameterInfo>();
		if (method == null)
			return false;
		try
		{
			parameters = method.GetParameters();
			return true;
		}
		catch (TypeLoadException)
		{
			return false;
		}
		catch
		{
			return false;
		}
	}

	private static int DeobfuscatedInteropMethodRank(MethodInfo method)
	{
		if (method == null)
			return int.MaxValue;
		var rank = 0;
		if (method.Name.Contains("_PDM_", StringComparison.Ordinal))
			rank += 1000;
		if (method.Name.Contains("Virtual", StringComparison.Ordinal))
			rank += 500;
		var match = Regex.Match(method.Name, @"_(\d+)$");
		if (match.Success && int.TryParse(match.Groups[1].Value, out var ordinal))
			rank += ordinal;
		return rank;
	}

	private static int CompareDeobfuscatedInteropMethods(MethodInfo a, MethodInfo b)
	{
		var rankCompare = DeobfuscatedInteropMethodRank(a).CompareTo(DeobfuscatedInteropMethodRank(b));
		if (rankCompare != 0)
			return rankCompare;
		return string.CompareOrdinal(a?.Name, b?.Name);
	}

	// Find all fields on `declaringType` whose declared type equals `fieldType`. Useful for
	// hunting "the Image field on this view" without committing to a specific obfuscated
	// name. Hints bias ordering. Cached per (type, id).
	internal static FieldInfo[] FindFields(
		Type declaringType,
		Type fieldType,
		string id,
		params string[] nameHints)
	{
		if (declaringType == null || fieldType == null || string.IsNullOrEmpty(id))
			return Array.Empty<FieldInfo>();

		var key = (declaringType, id);
		if (_fieldCache.TryGetValue(key, out var cached))
			return cached;
		if (!GameSymbolScope.CheckOwner(id, nameHints, declaringType))
			return _fieldCache[key] = Array.Empty<FieldInfo>();

		var hadHints = nameHints != null && nameHints.Any(h => !string.IsNullOrEmpty(h));
		nameHints = FilterOffGoldenMemberHints(id, nameHints);
		var matches = new List<FieldInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static;
		var seen = new HashSet<(Type, int)>();
		for (var current = declaringType; current != null; current = current.BaseType)
		{
			FieldInfo[] fields;
			try { fields = current.GetFields(flags | BindingFlags.DeclaredOnly); }
			catch { continue; }
			foreach (var f in fields)
			{
				if (!seen.Add((f.DeclaringType, f.MetadataToken)))
					continue;
				if (f.FieldType != fieldType)
					continue;
				matches.Add(f);
			}
		}

		var hintIndex = BuildHintIndex(nameHints);
		matches.Sort((a, b) =>
		{
			var ha = hintIndex.TryGetValue(a.Name, out var ik) ? ik : int.MaxValue;
			var hb = hintIndex.TryGetValue(b.Name, out var il) ? il : int.MaxValue;
			if (ha != hb)
				return ha.CompareTo(hb);
			return string.CompareOrdinal(a.Name, b.Name);
		});

		var hintHits = 0;
		for (var i = 0; i < matches.Count; i++)
			if (hintIndex.ContainsKey(matches[i].Name))
				hintHits++;
		var hasHints = hintIndex.Count > 0;
		FieldInfo[] result;
		if (hadHints && hintHits == 0 && !GameBuild.IsGolden)
		{
			// Off Golden Era a type-only pick behind stale hints is a guess: refuse.
			result = Array.Empty<FieldInfo>();
		}
		else if (hasHints && hintHits == 0 && matches.Count > 1)
		{
			// Same stale-hint disambiguation as FindMethods: refuse to guess when name
			// hints are stale and shape doesn't uniquely identify a single field.
			result = Array.Empty<FieldInfo>();
		}
		else
		{
			result = matches.ToArray();
		}
		_fieldCache[key] = result;
		RecordResolution(id, declaringType, result.Length, hintHits, matches.Select(f => f.Name).ToArray(), hintIndex.Count);
		return result;
	}

	// Resolve a game type by name. If the name doesn't resolve and `shapeFallback` is
	// provided, the fallback runs to discover the type by shape (e.g., scanning for a type
	// with specific method/field signatures). Cached per id.
	// Multi-hint callers should use FindTypeFromHints (or logMiss:false) so dead aliases
	// do not spam type MISS while a later live hint still succeeds.
	internal static Type FindType(string id, string nameHint, Func<Type> shapeFallback = null, bool logMiss = true)
	{
		if (string.IsNullOrEmpty(id))
			return null;
		if (_typeCache.TryGetValue(id, out var cached))
			return cached;

		using var loadTiming = Homm3LoadTiming.Scope("GameMember.FindType id=" + id, minMs: 5);
		if (GameSymbolScope.IsSentinel(nameHint))
		{
			// A GameSymbols hint the current-build scope refused: never run a shape fallback behind it.
			_typeCache[id] = null;
			if (logMiss)
				Plugin.LogSource?.LogWarning("GameMember type REFUSED: " + id + " - hint is unresolved on " + GameBuild.Describe()
					+ " (" + nameHint.Substring(GameSymbolScope.SentinelPrefix.Length) + "); this surface is unavailable.");
			return null;
		}
		var resolved = ResolveTypeByNameHint(nameHint);
		var fromName = resolved != null;
		if (resolved == null)
			resolved = ResolveTypeByObfuscatedNameHint(nameHint);
		if (resolved == null && shapeFallback != null)
		{
			try { resolved = shapeFallback(); } catch { }
		}
		if (RefuseOffGoldenType(id, nameHint, resolved))
		{
			_typeCache[id] = null;
			return null;
		}
		_typeCache[id] = resolved;

		var log = Plugin.LogSource;
		if (log != null)
		{
			if (resolved == null)
			{
				if (logMiss)
					log.LogWarning("GameMember type MISS: " + id + " (hint='" + nameHint + "') — no shape match either; this surface is unavailable.");
			}
			else if (DiagnosticsEnabled && fromName)
				log.LogInfo("GameMember type: " + id + " resolved to " + resolved.FullName + " via name hint '" + nameHint + "'.");
			else if (DiagnosticsEnabled)
				log.LogWarning("GameMember type stale-hint: " + id + " — name '" + nameHint + "' missed, shape fallback resolved " + resolved.FullName + ". Update the hint to lock to the new obfuscated name.");
		}
		return resolved;
	}

	/// <summary>
	/// Try name hints in order under one registry id. Intermediate misses stay quiet;
	/// a single type MISS Warning fires only when every hint fails.
	/// </summary>
	internal static Type FindTypeFromHints(string id, string[] nameHints, Func<string, Type> shapeFallback = null)
	{
		if (string.IsNullOrEmpty(id))
			return null;
		if (_typeCache.TryGetValue(id, out var cached))
			return cached;

		if (nameHints != null)
		{
			for (var i = 0; i < nameHints.Length; i++)
			{
				var hint = nameHints[i];
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				Func<Type> perHintFallback = null;
				if (shapeFallback != null)
				{
					var captured = hint;
					perHintFallback = () => shapeFallback(captured);
				}
				var resolved = FindType(id + "." + hint, hint, perHintFallback, logMiss: false);
				if (resolved != null)
				{
					_typeCache[id] = resolved;
					return resolved;
				}
			}
		}

		_typeCache[id] = null;
		Plugin.LogSource?.LogWarning(
			"GameMember type MISS: " + id + " — no hint in list resolved; this surface is unavailable.");
		return null;
	}

	private static readonly Dictionary<GameSymbols.TypeHintGroup, Type> _typeGroupCache = new();
	private static Dictionary<string, List<Type>> _hexTypesByObfuscatedName;

	/// <summary>
	/// The central type resolver for build-scoped hint groups (GameSymbols.TypeGroups). Picks the
	/// scope for the running build, collects every type any scope hint reaches (by full name in any
	/// loaded assembly, or by ObfuscatedNameAttribute in Hex), keeps those whose shape matches the
	/// scope's pinned TypeShape, and accepts only when exactly one type remains. Otherwise it
	/// returns null and logs why: unknown build, empty scope, no shape match, or ambiguity. It
	/// never throws, so it is safe from BattleLogic.Init / map Loader paths. Cached per group.
	/// </summary>
	internal static Type ResolveTypeGroup(GameSymbols.TypeHintGroup group)
	{
		if (group == null)
			return null;
		if (_typeGroupCache.TryGetValue(group, out var cached))
			return cached;

		Type result = null;
		try
		{
			result = ResolveTypeGroupUncached(group);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("GameMember type-group FAILED: " + group.Id + " — " + ex.GetType().Name + ": " + ex.Message + "; surface unavailable.");
			result = null;
		}
		_typeGroupCache[group] = result;
		return result;
	}

	private static Type ResolveTypeGroupUncached(GameSymbols.TypeHintGroup group)
	{
		var log = Plugin.LogSource;
		var kind = GameBuild.Kind;
		var scope = group.ScopeFor(kind);
		if (scope == null)
		{
			log?.LogError("GameMember type-group REFUSED: " + group.Id + " — unknown game build (" + GameBuild.Describe()
				+ "); obfuscated symbols are not pinned for it. This surface is unavailable.");
			return null;
		}
		if (scope.IsEmpty)
		{
			log?.LogError("GameMember type-group REFUSED: " + group.Id + " — no hints pinned for " + GameBuild.Describe()
				+ (ReferenceEquals(scope, GameSymbols.TypeHintScope.Generated)
					? " (the P1 remap did not resolve this group; see tools/port_current/remap/current_scopes_" + GameSymbols.CurrentScopes.BuildId + ".json)"
					: " (empty '" + kind.ToString().ToLowerInvariant() + "' scope in GameSymbols.TypeGroups)")
				+ ". This surface is unavailable.");
			return null;
		}

		var accepted = new List<(Type type, string hint)>();
		var rejected = new List<string>();
		foreach (var hint in scope.Hints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			foreach (var candidate in EnumerateHintCandidates(hint))
			{
				if (accepted.Exists(a => a.type == candidate) )
					continue;
				var observed = ObserveTypeShape(candidate);
				if (ShapeMatches(scope.Shape, observed))
					accepted.Add((candidate, hint));
				else
					rejected.Add(candidate.FullName + " via '" + hint + "' has " + observed);
			}
		}

		if (accepted.Count == 1)
		{
			if (DiagnosticsEnabled)
				log?.LogInfo("GameMember type-group: " + group.Id + " resolved to " + accepted[0].type.FullName + " via hint '" + accepted[0].hint
					+ "' (" + GameBuild.Describe() + ", shape " + scope.Shape + ")"
					+ (rejected.Count > 0 ? "; shape-rejected: " + string.Join("; ", rejected) : "") + ".");
			return accepted[0].type;
		}

		if (accepted.Count == 0)
		{
			log?.LogWarning("GameMember type-group MISS: " + group.Id + " — no type of expected shape " + scope.Shape + " for " + GameBuild.Describe()
				+ (rejected.Count > 0 ? "; shape-rejected: " + string.Join("; ", rejected) : "; no hint reached any type")
				+ ". This surface is unavailable.");
			return null;
		}

		var names = new List<string>();
		foreach (var a in accepted)
			names.Add(a.type.FullName + " via '" + a.hint + "'");
		log?.LogError("GameMember type-group AMBIGUOUS: " + group.Id + " — " + accepted.Count + " types match shape " + scope.Shape
			+ " (" + string.Join("; ", names) + "). Refusing to guess; this surface is unavailable.");
		return null;
	}

	private static IEnumerable<Type> EnumerateHintCandidates(string hint)
	{
		var seen = new HashSet<Type>();
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null)
				continue;
			Type type = null;
			try { type = asm.GetType(hint, throwOnError: false); }
			catch { }
			if (type != null && seen.Add(type))
				yield return type;
		}
		var byObfuscated = GetHexTypesByObfuscatedName();
		if (byObfuscated.TryGetValue(hint, out var list))
		{
			foreach (var type in list)
				if (seen.Add(type))
					yield return type;
		}
	}

	private static Dictionary<string, List<Type>> GetHexTypesByObfuscatedName()
	{
		if (_hexTypesByObfuscatedName != null)
			return _hexTypesByObfuscatedName;
		var map = new Dictionary<string, List<Type>>(StringComparer.Ordinal);
		foreach (var type in EnumerateHexTypes())
		{
			var obfuscated = TryReadObfuscatedName(type);
			if (string.IsNullOrEmpty(obfuscated))
				continue;
			if (!map.TryGetValue(obfuscated, out var list))
				map[obfuscated] = list = new List<Type>(1);
			list.Add(type);
		}
		_hexTypesByObfuscatedName = map;
		return map;
	}

	/// <summary>Shape as pinned by GameSymbols.TypeShape (see tools/port_current/interop_shape_index).</summary>
	internal static GameSymbols.TypeShape ObserveTypeShape(Type type)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
			| BindingFlags.Static | BindingFlags.DeclaredOnly;
		var baseName = "";
		var bt = type?.BaseType;
		if (bt != null)
		{
			if (bt.IsGenericType && !bt.IsGenericTypeDefinition)
				bt = bt.GetGenericTypeDefinition();
			baseName = bt.FullName ?? bt.Name ?? "";
		}
		int fields = -1, methods = -1;
		try { fields = type.GetFields(flags).Length; } catch { }
		try { methods = type.GetMethods(flags).Length; } catch { }
		return new GameSymbols.TypeShape(baseName, fields, methods);
	}

	private static bool ShapeMatches(GameSymbols.TypeShape expected, GameSymbols.TypeShape observed)
	{
		return expected.Fields == observed.Fields
			&& expected.Methods == observed.Methods
			&& string.Equals(expected.BaseType, observed.BaseType, StringComparison.Ordinal);
	}

	// Build gate for flat (unscoped) GameSymbols hints, which are Golden Era pins. Off Golden Era a
	// type that carries ObfuscatedNameAttribute (renamed obfuscated or Il2CppInterop-generated) is
	// refused: its name was reused for a different class in the next build. Real-name types pass.
	private static bool RefuseOffGoldenType(string id, string nameHint, Type resolved)
	{
		if (resolved == null || GameBuild.IsGolden)
			return false;
		// Reached through a generated current-build scope literal that was verified (exact type, pinned shape).
		if (GameSymbolScope.IsVerifiedType(nameHint, resolved))
			return false;
		var obfuscated = TryReadObfuscatedName(resolved);
		if (string.IsNullOrEmpty(obfuscated))
			return false;
		Plugin.LogSource?.LogError("GameMember build gate REFUSED type: " + id + " (hint='" + nameHint + "') would bind obfuscated type "
			+ resolved.FullName + " [" + obfuscated + "], pinned only for Golden Era; " + GameBuild.Describe()
			+ ". Scope it in GameSymbols.TypeGroups for this build. This surface is unavailable.");
		return true;
	}

	private static readonly Regex GeneratedMemberName = new(
		@"^(Method|field|NativeFieldInfoPtr|NativeMethodInfoPtr)_|^(get|set)_field_|_(Public|Private|Protected|Internal|Assembly)_|Unique",
		RegexOptions.CultureInvariant);

	// Off Golden Era, drop member hints that are Il2CppInterop-generated names (ordinal- and
	// obfuscated-type-derived, not stable across builds). Returns the kept hints; logs what was dropped.
	private static string[] FilterOffGoldenMemberHints(string id, string[] nameHints)
	{
		if (nameHints == null || nameHints.Length == 0 || GameBuild.IsGolden)
			return nameHints;
		// A generated current-build scope already holds live names verified on their live owner (and the
		// refusal sentinel, which matches nothing): nothing to drop.
		if (GameSymbolScope.IsScoped(nameHints))
			return nameHints;
		var kept = new List<string>(nameHints.Length);
		var dropped = 0;
		foreach (var hint in nameHints)
		{
			if (!string.IsNullOrEmpty(hint) && GeneratedMemberName.IsMatch(hint))
				dropped++;
			else
				kept.Add(hint);
		}
		if (dropped > 0)
			Plugin.LogSource?.LogWarning("GameMember build gate: " + id + " dropped " + dropped + " Golden-Era-only generated member hint(s); "
				+ GameBuild.Describe() + ".");
		return kept.ToArray();
	}

	private static Type ResolveTypeByNameHint(string nameHint)
	{
		if (string.IsNullOrEmpty(nameHint))
			return null;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null)
				continue;
			try
			{
				var type = asm.GetType(nameHint, throwOnError: false);
				if (type != null)
					return type;
			}
			catch { }
		}
		return null;
	}

	private static Type ResolveTypeByObfuscatedNameHint(string nameHint)
	{
		if (string.IsNullOrEmpty(nameHint))
			return null;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null || !string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				continue;
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }
			foreach (var type in types)
			{
				if (type == null)
					continue;
				if (string.Equals(TryReadObfuscatedName(type), nameHint, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	internal static string ReadObfuscatedName(MemberInfo member) => TryReadObfuscatedName(member);

	private static string TryReadObfuscatedName(MemberInfo member)
	{
		if (member == null)
			return null;
		try
		{
			foreach (var data in member.GetCustomAttributesData())
			{
				if (data?.AttributeType?.Name != "ObfuscatedNameAttribute")
					continue;
				if (data.ConstructorArguments.Count == 0)
					continue;
				return data.ConstructorArguments[0].Value as string;
			}
		}
		catch { }
		return null;
	}

	internal static bool TypesEquivalent(Type expected, Type actual)
	{
		if (expected == null || actual == null)
			return expected == actual;
		if (expected == actual)
			return true;
		try
		{
			if (expected.IsAssignableFrom(actual) || actual.IsAssignableFrom(expected))
				return true;
		}
		catch { }
		return string.Equals(expected.FullName, actual.FullName, StringComparison.Ordinal)
			|| string.Equals(expected.Name, actual.Name, StringComparison.Ordinal);
	}

	// Convenience overload: filter by parameter count alone (any param types), or any arity
	// when paramCount < 0. Equivalent to passing `new Type[paramCount]` (all nulls) or
	// `null` for any arity.
	internal static MethodInfo[] FindMethodsByNames(
		Type declaringType,
		int paramCount,
		string id,
		params string[] nameList)
	{
		var paramTypes = paramCount < 0 ? null : new Type[paramCount];
		return FindMethodsByNames(declaringType, paramTypes, id, nameList);
	}

	// Find all methods on `declaringType` whose names appear in `nameList` and whose
	// parameter shape matches `parameterTypes` (pass null for `parameterTypes` to skip the
	// shape filter). Useful for patch loops that historically did
	// `foreach (var name in [...]) AccessTools.Method(type, name, ...)`. The resolver
	// returns one MethodInfo per matched name; missing names are silently skipped (same
	// behavior as the original loop). Misses are recorded for visibility.
	internal static MethodInfo[] FindMethodsByNames(
		Type declaringType,
		Type[] parameterTypes,
		string id,
		params string[] nameList)
	{
		if (declaringType == null || string.IsNullOrEmpty(id) || nameList == null || nameList.Length == 0)
			return Array.Empty<MethodInfo>();

		var key = (declaringType, id);
		if (_methodCache.TryGetValue(key, out var cached))
			return cached;
		if (!GameSymbolScope.CheckOwner(id, nameList, declaringType))
			return _methodCache[key] = Array.Empty<MethodInfo>();

		nameList = FilterOffGoldenMemberHints(id, nameList);
		var nameSet = new HashSet<string>(nameList, StringComparer.Ordinal);
		var matches = new List<MethodInfo>();
		// Declared-only: do NOT walk the type hierarchy. If a name resolves to an inherited
		// method, multiple subclasses would patch the same base method, causing prefixes
		// from different subclasses to fire on every call. Match the original GetMethods
		// behavior (declared non-public + inherited public, but for patch targets we only
		// want declared methods).
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] declaredMethods;
		try { declaredMethods = declaringType.GetMethods(flags); }
		catch { declaredMethods = Array.Empty<MethodInfo>(); }
		foreach (var m in declaredMethods)
		{
			if (!nameSet.Contains(m.Name))
			{
				var obfuscatedName = TryReadObfuscatedName(m);
				if (obfuscatedName == null || !nameSet.Contains(obfuscatedName))
					continue;
			}
			if (parameterTypes != null)
			{
				var ps = m.GetParameters();
				if (ps.Length != parameterTypes.Length)
					continue;
				var ok = true;
				for (var i = 0; i < parameterTypes.Length; i++)
				{
					var expected = parameterTypes[i];
					if (expected != null && !TypesEquivalent(expected, ps[i].ParameterType))
					{
						ok = false;
						break;
					}
				}
				if (!ok)
					continue;
			}
			matches.Add(m);
		}

		SortByHints(matches, nameList);
		var result = matches.ToArray();
		_methodCache[key] = result;

		var log = Plugin.LogSource;
		if (log != null)
		{
			if (result.Length == 0)
			{
				log.LogWarning(
					"GameMember name-list MISS: " + id + " on " + declaringType.Name
					+ " — none of " + nameList.Length + " name(s) found ("
					+ string.Join(",", nameList.Take(8))
					+ (nameList.Length > 8 ? ",…" : "")
					+ "). All listed names rolled over.");
			}
			else if (DiagnosticsEnabled && result.Length < nameList.Length)
			{
				log.LogInfo(
					"GameMember name-list: " + id + " on " + declaringType.Name
					+ " matched " + result.Length + "/" + nameList.Length + " — "
					+ string.Join(",", result.Select(m => m.Name).Take(8))
					+ (result.Length > 8 ? ",…" : "")
					+ ". Missing names are likely stale; consider pruning if the gap stays.");
			}
			else if (DiagnosticsEnabled)
			{
				log.LogInfo(
					"GameMember name-list: " + id + " on " + declaringType.Name
					+ " matched all " + result.Length + " names.");
			}
		}
		return result;
	}

	internal static MethodInfo[] FindMethodsByNames(
		Type declaringType,
		Type[] parameterTypes,
		GameSymbols.MethodSymbol symbol)
	{
		return FindMethodsByNames(declaringType, parameterTypes, symbol.Id, symbol.NameHints);
	}

	internal static MethodInfo FindFirstMethodByNames(
		Type declaringType,
		Type[] parameterTypes,
		GameSymbols.MethodSymbol symbol)
	{
		var methods = FindMethodsByNames(declaringType, parameterTypes, symbol);
		return methods.Length == 0 ? null : methods[0];
	}

	/// <summary>
	/// "All of" lookup for a symbol whose hints each name one required method rather than aliases of one (a
	/// Golden Era method the current build split into several, GameSymbolScope.MethodSplit). Every hint must bind
	/// exactly one declared method that satisfies <paramref name="shape"/>; otherwise returns null with the reason
	/// in <paramref name="error"/>, so the caller can fail closed. A refused scope (sentinel hints) is reported as
	/// refused, never as a miss.
	/// </summary>
	internal static MethodInfo[] FindEveryMethodByNames(
		Type declaringType,
		GameSymbols.MethodSymbol symbol,
		Func<MethodInfo, bool> shape,
		out string error)
	{
		error = null;
		var hints = symbol.NameHints;
		if (declaringType == null)
		{
			error = "declaring type not resolved";
			return null;
		}
		if (hints == null || hints.Length == 0)
		{
			error = symbol.Id + ": no hints";
			return null;
		}
		var refusal = GameSymbolScope.RefusalReason(hints);
		if (refusal != null || hints.Any(GameSymbolScope.IsSentinel))
		{
			error = symbol.Id + " refused on this build (" + (refusal ?? "unresolved hint") + ")";
			return null;
		}
		if (!GameSymbolScope.CheckOwner(symbol.Id, hints, declaringType))
		{
			error = symbol.Id + " is not scoped to " + declaringType.FullName;
			return null;
		}
		// Same build gate as FilterOffGoldenMemberHints, but all-or-nothing: dropping one required name would
		// silently leave its method unpatched.
		if (!GameBuild.IsGolden && !GameSymbolScope.IsScoped(hints) && hints.Any(h => GeneratedMemberName.IsMatch(h)))
		{
			error = symbol.Id + " holds Golden-Era-only generated names and has no scope for " + GameBuild.Describe();
			return null;
		}
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] declared;
		try { declared = declaringType.GetMethods(flags); }
		catch (Exception ex)
		{
			error = "methods of " + declaringType.FullName + " unreadable (" + ex.GetType().Name + ")";
			return null;
		}
		var result = new MethodInfo[hints.Length];
		var missing = new List<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			var named = declared.Where(m => string.Equals(m.Name, hint, StringComparison.Ordinal)
				|| string.Equals(TryReadObfuscatedName(m), hint, StringComparison.Ordinal)).ToArray();
			var fitting = named.Where(m => shape == null || shape(m)).ToArray();
			if (fitting.Length == 1 && Array.IndexOf(result, fitting[0]) < 0)
				result[i] = fitting[0];
			else
				missing.Add(hint + " (" + named.Length + " named, " + fitting.Length + " of the expected shape)");
		}
		if (missing.Count > 0)
		{
			error = symbol.Id + ": " + missing.Count + " of " + hints.Length + " expected method(s) not bound on "
				+ declaringType.FullName + ": " + string.Join(", ", missing);
			return null;
		}
		return result;
	}

	private static Dictionary<string, int> BuildHintIndex(string[] nameHints)
	{
		var index = new Dictionary<string, int>(StringComparer.Ordinal);
		var hints = nameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
			if (!string.IsNullOrEmpty(hints[i]))
				index[hints[i]] = i;
		return index;
	}

	private static void SortByHints(List<MethodInfo> methods, string[] nameHints)
	{
		var hintIndex = BuildHintIndex(nameHints);
		methods.Sort((a, b) =>
		{
			var ha = GetMethodHintRank(a, hintIndex);
			var hb = GetMethodHintRank(b, hintIndex);
			if (ha != hb)
				return ha.CompareTo(hb);
			if (LooksLikeDeobfuscatedInteropMethod(a) && LooksLikeDeobfuscatedInteropMethod(b))
				return CompareDeobfuscatedInteropMethods(a, b);
			return string.CompareOrdinal(a.Name, b.Name);
		});
	}

	private static int CountHintHits(MethodInfo[] methods, string[] nameHints)
	{
		var hintIndex = BuildHintIndex(nameHints);
		var hits = 0;
		for (var i = 0; i < methods.Length; i++)
			if (MethodMatchesHint(methods[i], hintIndex))
				hits++;
		return hits;
	}

	private static void RecordResolution(string id, Type declaringType, int matches, int hintHits, string[] pickedNames, int hintCount)
	{
		var record = new ResolutionRecord
		{
			Id = id,
			DeclaringType = declaringType,
			Matches = matches,
			HintHits = hintHits,
			PickedNames = pickedNames,
		};
		_resolutions[id] = record;
		LogResolution(record, hintCount);
	}

	private static IEnumerable<MethodInfo> EnumerateMethods(Type type, BindingFlags flags)
	{
		// Walk type hierarchy so inherited members are visible. Skip duplicates by metadata
		// token + declaring type.
		var seen = new HashSet<(Type, int)>();
		for (var current = type; current != null; current = current.BaseType)
		{
			MethodInfo[] methods;
			try { methods = current.GetMethods(flags | BindingFlags.DeclaredOnly); }
			catch { continue; }
			foreach (var m in methods)
			{
				if (seen.Add((m.DeclaringType, m.MetadataToken)))
					yield return m;
			}
		}
	}

	private static void LogResolution(ResolutionRecord record, int hintCount)
	{
		var log = Plugin.LogSource;
		if (log == null)
			return;

		var picks = record.PickedNames.Length == 0
			? "(none)"
			: string.Join(",", record.PickedNames.Take(6))
			  + (record.PickedNames.Length > 6 ? ",…" : "");

		if (record.Matches == 0)
		{
			log.LogWarning(
				"GameMember MISS: " + record.Id
				+ " on " + (record.DeclaringType?.FullName ?? "?")
				+ " — no shape matches; check whether the game restructured this surface.");
			return;
		}

		if (hintCount > 0 && record.HintHits == 0)
		{
			log.LogWarning(
				"GameMember stale-hints: " + record.Id
				+ " on " + (record.DeclaringType?.Name ?? "?")
				+ " — found " + record.Matches + " by shape but none matched name hints. Picked: "
				+ picks + ". Update the hints to lock to the new obfuscated name.");
			return;
		}

		if (DiagnosticsEnabled)
			log.LogInfo(
				"GameMember: " + record.Id
				+ " on " + (record.DeclaringType?.Name ?? "?")
				+ " resolved " + record.Matches + " (hint hits=" + record.HintHits + "): "
				+ picks + ".");
	}

	internal static IEnumerable<Type> EnumerateHexTypes()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null || !string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				continue;
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }
			foreach (var type in types)
			{
				if (type != null)
					yield return type;
			}
		}
	}

	internal static void EmitSummary()
	{
		var log = Plugin.LogSource;
		if (log == null || _resolutions.Count == 0)
			return;
		var miss = 0;
		var stale = 0;
		foreach (var r in _resolutions.Values)
		{
			if (r.Matches == 0) miss++;
			else if (r.HintHits == 0) stale++;
		}
		log.LogInfo(
			"GameMember summary: " + _resolutions.Count + " resolved, "
			+ miss + " missing, "
			+ stale + " stale-hint.");
	}
}
