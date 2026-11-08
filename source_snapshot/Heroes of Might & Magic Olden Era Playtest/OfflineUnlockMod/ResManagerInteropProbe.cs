#nullable disable
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Shared logic for finding <c>Hex.ResManager</c> and its open <c>Get&lt;T&gt;(path)</c> on IL2CPP interop assemblies.
/// Kept in one file and linked from <c>tools/verify_esquire_interop</c> to avoid drift with <see cref="EsquirePikemanVisuals"/>.
/// </summary>
public static class ResManagerInteropProbe
{
	public static Type TryResolveResManagerType(Assembly asm, Action<string> log)
	{
		var direct = asm.GetType("Hex.ResManager", false);
		if (direct != null)
			return direct;

		// ResManager lives in Hex.ResManager.dll (separate assembly from Hex.dll).
		// Scan all loaded assemblies for it before falling back to shape probe.
		var crossAsm = TryFindResManagerAcrossAssemblies(log);
		if (crossAsm != null)
			return crossAsm;

		log?.Invoke("ResManager: scanning assembly types (ReflectionTypeLoadException fallback)…");

		try
		{
			foreach (var t in asm.GetTypes())
			{
				if (t != null && t.Namespace == "Hex" && t.Name == "ResManager")
					return t;
			}
		}
		catch (ReflectionTypeLoadException e)
		{
			if (e.Types == null)
				return null;
			foreach (var t in e.Types)
			{
				if (t != null && t.Namespace == "Hex" && t.Name == "ResManager")
					return t;
			}
		}

		return TryResolveResManagerTypeByShape(asm, log);
	}

	/// <summary>
	/// Scans <see cref="AppDomain.CurrentDomain"/> for the <c>ResManager</c> class, which ships in
	/// <c>Hex.ResManager.dll</c> (a separate assembly from the main <c>Hex.dll</c> that <c>ObjCityConfig</c>
	/// lives in). Falls back to a shape scan of each candidate assembly.
	/// </summary>
	private static Type TryFindResManagerAcrossAssemblies(Action<string> log)
	{
		Assembly[] all;
		try
		{
			all = AppDomain.CurrentDomain.GetAssemblies();
		}
		catch
		{
			return null;
		}

		// Preferred: the known separate assembly name.
		foreach (var a in all)
		{
			if (!string.Equals(a.GetName().Name, "Hex.ResManager", StringComparison.OrdinalIgnoreCase))
				continue;

			// The class is in the global namespace inside Hex.ResManager.dll.
			var t = a.GetType("ResManager", false)
			        ?? a.GetType("Hex.ResManager", false);
			if (t != null)
			{
				log?.Invoke("ResManager: found type '" + t.FullName + "' in assembly '" + a.GetName().Name + "'.");
				return t;
			}

			// Name lookup failed — shape scan this specific assembly.
			var byShape = TryResolveResManagerTypeByShape(a, log);
			if (byShape != null)
			{
				log?.Invoke("ResManager: shape-found type '" + byShape.FullName + "' in assembly '" + a.GetName().Name + "'.");
				return byShape;
			}
		}

		// Fallback: shape scan every loaded assembly (expensive, but only runs once at startup).
		foreach (var a in all)
		{
			var byShape = TryResolveResManagerTypeByShape(a, log);
			if (byShape != null)
			{
				log?.Invoke("ResManager: shape-found type '" + byShape.FullName + "' in assembly '" + a.GetName().Name + "' (broad scan).");
				return byShape;
			}
		}

		return null;
	}

	/// <summary>
	/// When <c>Hex.ResManager</c> is renamed in IL2CPP interop, find the type that exposes a real resource
	/// <c>Get&lt;T&gt;(path)=&gt;T</c> (excluding serialization-like generics such as <c>Deserialize&lt;T&gt;</c>).
	/// </summary>
	private static Type TryResolveResManagerTypeByShape(Assembly asm, Action<string> log)
	{
		var allTypes = EnumerateAssemblyTypes(asm);
		if (allTypes == null || allTypes.Count == 0)
		{
			log?.Invoke("ResManager: shape fallback found 0 loadable types.");
			return null;
		}

		const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		var matches = new List<Type>();
		foreach (var t in allTypes)
		{
			if (t == null)
				continue;
			var c = CollectResManagerGetShapeCandidates(t, f);
			if (PickResManagerGetOpenGeneric(c) == null)
				continue;
			matches.Add(t);
		}

		if (matches.Count == 0)
		{
			log?.Invoke("ResManager: shape fallback found 0 candidates.");
			return null;
		}

		if (matches.Count == 1)
		{
			var pick = matches[0];
			log?.Invoke("ResManager: type-name lookup failed; shape fallback selected " + (pick.FullName ?? pick.Name) + ".");
			return pick;
		}

		var hexNs = matches.Where(t => string.Equals(t.Namespace, "Hex", StringComparison.Ordinal)).ToList();
		if (hexNs.Count == 1)
		{
			var pick = hexNs[0];
			log?.Invoke(
				"ResManager: shape fallback selected unique Hex namespace type "
				+ (pick.FullName ?? pick.Name)
				+ " (total shape candidates="
				+ matches.Count
				+ ").");
			return pick;
		}

		var instanceOnly = new List<Type>();
		foreach (var t in matches)
		{
			var c = CollectResManagerGetShapeCandidates(t, f);
			var pickM = PickResManagerGetOpenGeneric(c);
			if (pickM != null && !pickM.IsStatic)
				instanceOnly.Add(t);
		}

		if (instanceOnly.Count == 1)
		{
			var pick = instanceOnly[0];
			log?.Invoke(
				"ResManager: shape fallback selected unique instance-method type "
				+ (pick.FullName ?? pick.Name)
				+ ".");
			return pick;
		}

		var hexInstance = instanceOnly.Where(t => string.Equals(t.Namespace, "Hex", StringComparison.Ordinal)).ToList();
		if (hexInstance.Count == 1)
		{
			var pick = hexInstance[0];
			log?.Invoke(
				"ResManager: shape fallback selected unique Hex + instance-method type "
				+ (pick.FullName ?? pick.Name)
				+ ".");
			return pick;
		}

		var top = matches
			.Take(6)
			.Select(t => t.FullName ?? t.Name)
			.ToArray();
		log?.Invoke(
			"ResManager: shape fallback found "
			+ matches.Count
			+ " ambiguous types (Hex namespace="
			+ hexNs.Count
			+ "); refusing patch. top=["
			+ string.Join(", ", top)
			+ "]");
		return null;
	}

	private static List<Type> EnumerateAssemblyTypes(Assembly asm)
	{
		try
		{
			return asm.GetTypes().Where(t => t != null).ToList();
		}
		catch (ReflectionTypeLoadException e)
		{
			if (e.Types == null)
				return null;
			return e.Types.Where(t => t != null).ToList();
		}
	}

	/// <summary>
	/// Resolves the closed <c>Get&lt;GameObject&gt;(path)</c> loader, or the deobf equivalent
	/// <c>(string)=&gt;UnityEngine.Object</c>, for Harmony postfix registration.
	/// </summary>
	public static MethodInfo FindResManagerGameObjectLoaderMethod(Type t, Action<string> log = null)
	{
		if (t == null)
			return null;

		const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

		// Deobf interop exposes a shared static Get<T>(path) used for TextAsset and GameObject alike.
		// Closing it as GameObject and patching breaks FontsAlias / InputManager bootstrap (BhAppStart NRE/black screen).
		var closedLoader = TryFindClosedUnityObjectLoader(t, f, log);
		if (closedLoader != null)
			return closedLoader;

		var loader = FindResManagerGetOpenGeneric(t, log);
		if (loader != null)
		{
			if (IsUnsafeSharedGenericResourceLoader(loader))
			{
				log?.Invoke(
					"ResManager: refusing unsafe shared generic loader '"
					+ loader.Name
					+ "'; would corrupt non-GameObject resource loads.");
				loader = null;
			}
		}

		if (loader != null)
		{
			if (loader.IsGenericMethodDefinition)
			{
				try
				{
					var closed = loader.MakeGenericMethod(typeof(UnityEngine.GameObject));
					log?.Invoke("ResManager: using open generic loader '" + loader.Name + "' closed as GameObject.");
					return closed;
				}
				catch (Exception ex)
				{
					log?.Invoke("ResManager: MakeGenericMethod(GameObject) on '" + loader.Name + "' failed: " + ex.Message);
				}
			}
			else if (IsUnityObjectReturnType(loader.ReturnType))
			{
				log?.Invoke("ResManager: using closed Unity Object loader '" + loader.Name + "'.");
				return loader;
			}
		}

		var staticGeneric = TryFindDeobfStaticGenericLoader(t, f, log);
		if (staticGeneric != null && !IsUnsafeSharedGenericResourceLoader(staticGeneric))
		{
			try
			{
				var closed = staticGeneric.MakeGenericMethod(typeof(UnityEngine.GameObject));
				log?.Invoke("ResManager: using deobf static generic loader '" + staticGeneric.Name + "' closed as GameObject.");
				return closed;
			}
			catch (Exception ex)
			{
				log?.Invoke("ResManager: MakeGenericMethod(GameObject) on '" + staticGeneric.Name + "' failed: " + ex.Message);
			}
		}

		return null;
	}

	/// <summary>
	/// Shared IL2CPP resource loader used for every <c>Get&lt;T&gt;</c> specialization. Patching it as
	/// <c>Get&lt;GameObject&gt;</c> corrupts startup <see cref="UnityEngine.TextAsset"/> loads.
	/// </summary>
	internal static bool IsUnsafeSharedGenericResourceLoader(MethodInfo method)
	{
		if (method == null)
			return false;
		if (string.Equals(method.Name, "Method_Public_Static_a_String_0", StringComparison.Ordinal))
			return true;
		return method.IsStatic
		       && method.IsGenericMethodDefinition
		       && method.Name.StartsWith("Method_Public_Static_", StringComparison.Ordinal)
		       && !LooksLikeUnityObjectOnlyGenericLoader(method);
	}

	private static bool LooksLikeUnityObjectOnlyGenericLoader(MethodInfo method)
	{
		if (method == null || !method.IsGenericMethodDefinition)
			return false;
		Type[] gArgs;
		try { gArgs = method.GetGenericArguments(); }
		catch { return false; }
		if (gArgs == null || gArgs.Length != 1)
			return false;
		if (!ReturnTypeMatchesGenericT(method, gArgs[0]))
			return false;
		try
		{
			foreach (var c in gArgs[0].GetGenericParameterConstraints())
			{
				if (c == typeof(UnityEngine.Object) || c.FullName == "UnityEngine.Object")
					return true;
			}
		}
		catch { }
		return false;
	}

	/// <summary>Finds the open generic <c>Get</c> with one type arg and a single path parameter.</summary>
	/// <param name="t"><c>Hex.ResManager</c> (concrete <see cref="Type"/>) from the interop assembly.</param>
	/// <remarks>
	/// The old fallback <c>FindByShapeOnResManagerOnly</c> did not require
	/// <c>return = T</c> and could select a <em>different</em> 1-arity generic by
	/// <c>MetadataToken</c> alone, so Harmony on <c>Get&lt;GameObject&gt;</c> then patched
	/// the wrong method and broke init. We now only keep methods that pass
	/// <see cref="ReturnTypeMatchesGenericT"/>, then disambiguate: <c>Get</c> first, then
	/// known obfuscated <c>bmeo</c>, else <c>null</c> if still ambiguous.
	/// </remarks>
	public static MethodInfo FindResManagerGetOpenGeneric(Type t, Action<string> log = null)
	{
		if (t == null)
			return null;
		const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic
			| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

		var fromShape = PickResManagerGetOpenGeneric(CollectResManagerGetShapeCandidates(t, f));
		if (fromShape != null)
			return fromShape;

		var knownObjectLoader = TryFindKnownUnityObjectLoaderByName(t, f, log);
		if (knownObjectLoader != null && IsUnsafeSharedGenericResourceLoader(knownObjectLoader))
		{
			log?.Invoke(
				"ResManager: ignoring known-loader candidate '"
				+ knownObjectLoader.Name
				+ "' because it is the shared generic resource loader.");
			knownObjectLoader = null;
		}
		if (knownObjectLoader != null)
			return knownObjectLoader;

		// Shape scan returned nothing. Dump all methods so we can diagnose the failure reason.
		if (log != null)
		{
			try
			{
				var sb = new System.Text.StringBuilder();
				sb.Append("ResManager: shape scan found 0 candidates on '");
				sb.Append(t.FullName ?? t.Name);
				sb.Append("'. All methods: ");
				foreach (var m in t.GetMethods(f))
				{
					sb.Append(m.Name);
					sb.Append('[');
					sb.Append(m.IsGenericMethodDefinition ? "GMD" : m.IsGenericMethod ? "GM" : "");
					sb.Append('|');
					var ps2 = m.GetParameters();
					sb.Append(ps2.Length);
					sb.Append("p");
					if (ps2.Length > 0) { sb.Append(':'); sb.Append(ps2[0].ParameterType.Name); }
					sb.Append('|');
					sb.Append(m.ReturnType.Name);
					sb.Append("] ");
				}
				log(sb.ToString());
			}
			catch (Exception diagEx)
			{
				log("ResManager: method dump failed: " + diagEx.Message);
			}
		}

		// Do not fall back to the obfuscated generic body by name. On this IL2CPP build that body
		// is shared by non-GameObject resource loads too; patching it as Get<GameObject> corrupts
		// startup TextAsset loads and causes a BhAppStart NRE loop.
		log?.Invoke("ResManager: refusing name-only bmeo/Get fallback; no safe GameObject-only method found.");
		return null;
	}

	private static MethodInfo TryFindClosedUnityObjectLoader(Type t, BindingFlags f, Action<string> log)
	{
		MethodInfo best = null;
		var bestHintRank = int.MaxValue;
		var shapeMatches = new List<MethodInfo>();
		foreach (var m in t.GetMethods(f))
		{
			if (m.IsGenericMethodDefinition || m.IsGenericMethod)
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1 || !IsResourcePathParamType(ps[0].ParameterType))
				continue;
			if (m.ReturnType == typeof(void) || typeof(System.Collections.IEnumerator).IsAssignableFrom(m.ReturnType))
				continue;
			if (!IsUnityObjectReturnType(m.ReturnType))
				continue;

			var hintRank = GetResManagerLoaderHintRank(m.Name);
			if (hintRank >= 0)
			{
				if (hintRank < bestHintRank)
				{
					best = m;
					bestHintRank = hintRank;
				}
				continue;
			}

			if (m.Name.StartsWith("Method_Private_Object_String_", StringComparison.Ordinal)
			    || m.Name.StartsWith("Method_Public_Object_String_", StringComparison.Ordinal))
				shapeMatches.Add(m);
		}

		if (best != null)
		{
			log?.Invoke("ResManager: closed Unity Object loader selected by hint '" + best.Name + "'.");
			return best;
		}

		if (shapeMatches.Count == 1)
		{
			log?.Invoke("ResManager: closed Unity Object loader selected by unique shape '" + shapeMatches[0].Name + "'.");
			return shapeMatches[0];
		}

		if (shapeMatches.Count > 1)
			log?.Invoke("ResManager: closed Unity Object loader shape scan found " + shapeMatches.Count + " ambiguous candidates.");
		return null;
	}

	private static MethodInfo TryFindDeobfStaticGenericLoader(Type t, BindingFlags f, Action<string> log)
	{
		var candidates = CollectResManagerGetShapeCandidates(t, f);
		var pick = PickResManagerGetOpenGeneric(candidates);
		if (pick != null)
			return pick;

		foreach (var m in t.GetMethods(f))
		{
			if (!m.IsGenericMethodDefinition)
				continue;
			var gArgs = m.GetGenericArguments();
			if (gArgs.Length != 1)
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1 || !IsResourcePathParamType(ps[0].ParameterType))
				continue;
			if (!ReturnTypeMatchesGenericT(m, gArgs[0]))
				continue;
			if (GetResManagerLoaderHintRank(m.Name) >= 0 || m.Name.StartsWith("Method_Public_Static_", StringComparison.Ordinal))
			{
				if (IsUnsafeSharedGenericResourceLoader(m))
					continue;
				log?.Invoke("ResManager: deobf static generic loader candidate '" + m.Name + "'.");
				return m;
			}
		}

		return null;
	}

	private static int GetResManagerLoaderHintRank(string name)
	{
		var hints = GameSymbols.ImportVisuals.ResManagerObjectLoader.NameHints;
		for (var i = 0; i < hints.Length; i++)
		{
			if (string.Equals(hints[i], name, StringComparison.Ordinal))
				return i;
		}
		return -1;
	}

	private static bool IsUnityObjectReturnType(Type returnType)
	{
		if (returnType == null)
			return false;
		if (returnType == typeof(UnityEngine.Object) || returnType == typeof(UnityEngine.GameObject))
			return true;
		if (string.Equals(returnType.FullName, "UnityEngine.Object", StringComparison.Ordinal))
			return true;
		try
		{
			return typeof(UnityEngine.Object).IsAssignableFrom(returnType);
		}
		catch
		{
			return returnType.Name == "Object" && string.Equals(returnType.Namespace, "UnityEngine", StringComparison.Ordinal);
		}
	}

	private static MethodInfo TryFindKnownUnityObjectLoaderByName(Type t, BindingFlags f, Action<string> log)
	{
		MethodInfo best = null;
		foreach (var m in t.GetMethods(f))
		{
			if (Array.IndexOf(GameSymbols.ImportVisuals.ResManagerObjectLoader.NameHints, m.Name) < 0)
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1)
				continue;
			if (!IsResourcePathParamType(ps[0].ParameterType))
				continue;
			if (LooksLikeUnityObjectGenericLoader(m))
			{
				if (IsUnsafeSharedGenericResourceLoader(m))
					continue;
				if (best == null
				    || (m.Name == GameSymbols.ImportVisuals.ResManagerObjectLoader.NameHints[0] && best.Name != GameSymbols.ImportVisuals.ResManagerObjectLoader.NameHints[0])
				    || (!best.IsStatic && m.IsStatic))
					best = m;
				continue;
			}
			if (!m.IsGenericMethodDefinition
			    && !m.IsGenericMethod
			    && IsUnityObjectReturnType(m.ReturnType))
			{
				if (best == null || GetResManagerLoaderHintRank(m.Name) < GetResManagerLoaderHintRank(best.Name))
					best = m;
			}
			/*
			// Accept if the method is generic by any means the runtime reports.
			bool hasGenericArgs = false;
			if (!m.IsGenericMethodDefinition && !m.IsGenericMethod && !m.ContainsGenericParameters)
			{
				// Last resort: try GetGenericArguments — Il2CppInterop may still return args.
				try
				{
					var ga = m.GetGenericArguments();
					hasGenericArgs = ga != null && ga.Length == 1;
				}
				catch { }
				if (!hasGenericArgs)
					continue;
			}
			// Prefer static; among equals prefer bmeo over Get (Get may be non-generic overload).
			if (best == null || (!best.IsStatic && m.IsStatic))
				best = m;
			*/
		}
		if (best != null)
			log?.Invoke("ResManager: known-loader fallback selected '" + best.Name + "' IsGMD=" + best.IsGenericMethodDefinition + " IsGM=" + best.IsGenericMethod + ".");
		else
			log?.Invoke("ResManager: known-loader fallback found no UnityEngine.Object-constrained loader with single string param.");
		return best;
	}

	private static bool LooksLikeUnityObjectGenericLoader(MethodInfo m)
	{
		if (m == null)
			return false;
		Type[] gArgs;
		try
		{
			gArgs = m.GetGenericArguments();
		}
		catch
		{
			return false;
		}
		if (gArgs == null || gArgs.Length != 1)
			return false;
		var g = gArgs[0];
		if (!ReturnTypeMatchesGenericT(m, g)
		    && m.ReturnType != typeof(UnityEngine.Object)
		    && m.ReturnType.FullName != "UnityEngine.Object")
			return false;
		try
		{
			foreach (var c in g.GetGenericParameterConstraints())
			{
				if (c == typeof(UnityEngine.Object) || c.FullName == "UnityEngine.Object")
					return true;
			}
		}
		catch
		{
			// Il2CppInterop can be sparse here; fall back to known loader name + generic T return.
		}
		return Array.IndexOf(GameSymbols.ImportVisuals.ResManagerObjectLoader.NameHints, m.Name) >= 0;
	}

	/// <summary>Methods on <c>ResManager</c> that look like <c>Get&lt;T&gt;(path) =&gt; T</c>.</summary>
	internal static IReadOnlyList<MethodInfo> CollectResManagerGetShapeCandidates(Type t, BindingFlags f)
	{
		var list = new List<MethodInfo>();
		if (t == null)
			return list;
		foreach (var m in t.GetMethods(f))
		{
			if (!m.IsGenericMethodDefinition)
				continue;
			if (IsSerializationLikeGenericAccessorName(m.Name))
				continue;
			var gArgs = m.GetGenericArguments();
			if (gArgs.Length != 1)
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1)
				continue;
			if (!IsResourcePathParamType(ps[0].ParameterType))
				continue;
			if (!ReturnTypeMatchesGenericT(m, gArgs[0]))
				continue;
			list.Add(m);
		}
		return list;
	}

	/// <summary>
	/// Choose one open generic for Esquire. Prefer <c>Get</c>, then shipped obfuscated <c>bmeo</c>;
	/// if multiple non-disambiguated methods remain, return <c>null</c> (do not guess).
	/// </summary>
	internal static MethodInfo PickResManagerGetOpenGeneric(IReadOnlyList<MethodInfo> candidates)
	{
		if (candidates == null || candidates.Count == 0)
			return null;
		if (candidates.Count == 1)
			return candidates[0];

		// Prefer instance accessors (resource loader) over static serialization helpers if both shapes exist.
		var instancePref = candidates.Where(m => !m.IsStatic).ToList();
		var pool = instancePref.Count > 0 ? instancePref : candidates;

		var byGet = pool
			.Where(m => m.Name == "Get")
			.OrderBy(m => m.MetadataToken)
			.ToList();
		if (byGet.Count > 0)
			return byGet[0];

		var byBmeo = pool
			.Where(m => m.Name == "bmfq")
			.OrderBy(m => m.MetadataToken)
			.ToList();
		if (byBmeo.Count == 1)
			return byBmeo[0];
		// two+ bmeo or other ambiguous names: unsafe to patch
		return null;
	}

	/// <summary>
	/// True if <paramref name="m"/>'s return is the same type parameter as
	/// <c>GetGenericArguments()[0]</c> for a <c>Get&lt;T&gt;(path) =&gt; T</c> (or obfuscated) accessor.
	/// </summary>
	private static bool ReturnTypeMatchesGenericT(MethodInfo m, Type tArg)
	{
		if (m == null || tArg == null)
			return false;
		var r = m.ReturnType;
		if (ReferenceEquals(r, tArg))
			return true;
		if (r.Equals(tArg))
			return true;
		if (r == tArg)
			return true;
		if (r.IsGenericParameter && tArg.IsGenericParameter
		    && r.GenericParameterPosition == tArg.GenericParameterPosition
		    && ReferenceEquals(r.DeclaringMethod, m) && ReferenceEquals(tArg.DeclaringMethod, m))
			return true;
		// Il2CppInterop: DeclaringMethod may be set on only one side, or reference identity may differ.
		if (r.IsGenericParameter && tArg.IsGenericParameter
		    && r.GenericParameterPosition == tArg.GenericParameterPosition
		    && (ReferenceEquals(r.DeclaringMethod, m) || ReferenceEquals(tArg.DeclaringMethod, m)))
			return true;
		// Same slot (e.g. first type arg) and same parameter name (often "T") on the open method
		if (r.IsGenericParameter && tArg.IsGenericParameter
		    && r.GenericParameterPosition == tArg.GenericParameterPosition
		    && string.Equals(r.Name, tArg.Name, StringComparison.Ordinal))
			return true;
		return false;
	}

	/// <summary>Exclude generic helpers that match <c>T X&lt;T&gt;(string)</c> but are not resource loads (e.g. JSON deserialize).</summary>
	private static bool IsSerializationLikeGenericAccessorName(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		if (string.Equals(name, "Deserialize", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "Serialize", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "TryDeserialize", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "DeserializeFrom", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "FromJson", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "ReadJson", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "Parse", StringComparison.Ordinal))
			return true;
		if (string.Equals(name, "TryParse", StringComparison.Ordinal))
			return true;
		return false;
	}

	public static bool IsResourcePathParamType(Type p)
	{
		if (p == null)
			return false;
		if (p == typeof(string))
			return true;
		if (p.FullName == "System.String")
			return true;
		// Il2Cpp interop: Il2CppSystem.String
		if (p.Name == "String" && p.Namespace != null && p.Namespace.StartsWith("Il2CppSystem", StringComparison.Ordinal))
			return true;
		return false;
	}
}
