using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// <b>Deprecated for HoMM3 map units — does not work.</b> Per-frame fog polling for <c>Sprites/Default</c> billboards
/// was never reliable (stutter, wrong ownership, visible-through-fog). Do not attach to HoMM3 shells or
/// <c>homm3_map_visual</c>. Map units must draw on the vanilla shell renderer via
/// <see cref="Homm3NativeShellRendererTransplantSync"/>.
/// </summary>
public sealed class EsquirePikemanMapBillboardFogSync : MonoBehaviour
{
	private const string BhMapSquadTypeName = "Hex.Map.BhMapSquad";
	private const int FogPollFrameInterval = 45;
	private const int FogRetryFrameInterval = 90;

	private const BindingFlags Inst = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
	private const BindingFlags Static = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;

	private static readonly Dictionary<Type, FogMethodCache> FogCaches = new();
	private static readonly object SessionBootstrapLock = new();
	private static readonly string[] SessionHolderTypeNames =
	{
		"Hex.Session.Loader",
		"Hex.Session.BhSession",
		"Hex.Session.Hud.BhHUDSession",
		"Hex.UI.City.BhCityUISession",
		"cta",
		"hl",
		"czr",
		"czk",
	};
	private static readonly string[] SessionHolderStaticNames = { "me", "instance", "current" };

	private static Func<object> _resolveSessionRoot;
	private static object _sessionRootCache;
	private static bool _loggedSessionPath;
	private static bool _loggedSessionFailure;
	private static int _globalDiagLogged;

	private Renderer[] _renderers;
	private bool _lastHide;
	private int _diagLogged;
	private int _nextFogPollFrame;
	private int _cachedNode = -1;
	private int _cachedNodeRefreshFrame;
	private object _cachedFog;
	private bool _cachedFogResolved;
	private Component _cachedBhMapSquad;
	private bool _searchedBhMapSquad;

	private sealed class FogMethodCache
	{
		internal MethodInfo IsNodeHiddenInt;
		internal MethodInfo IsNodeVisibleInt;
		internal bool Scanned;
	}

	private sealed class SearchNode
	{
		internal object Value;
		internal string Path;
		internal int Depth;
	}

	private sealed class ReferenceIdentityComparer : IEqualityComparer<object>
	{
		internal static readonly ReferenceIdentityComparer Instance = new();

		public new bool Equals(object x, object y) => ReferenceEquals(x, y);

		public int GetHashCode(object obj) => obj == null ? 0 : RuntimeHelpers.GetHashCode(obj);
	}

	private void Awake()
	{
		_renderers = GetComponentsInChildren<Renderer>(true);
		_nextFogPollFrame = Time.frameCount + Math.Abs(GetInstanceID() % FogPollFrameInterval);
	}

	private void LateUpdate()
	{
		if (_renderers == null || _renderers.Length == 0)
			_renderers = GetComponentsInChildren<Renderer>(true);

		var frame = Time.frameCount;
		if (frame < _nextFogPollFrame)
			return;
		_nextFogPollFrame = frame + FogPollFrameInterval + Math.Abs(GetInstanceID() % 5);

		// Incomplete fog/node data must not toggle Renderer.enabled — that alternates "visible through fog" vs
		// "invisible" when BhMapSquad vs NodeByPos disagree frame-to-frame.
		if (!TryGetShouldHideForLocalFog(out var hide))
		{
			_nextFogPollFrame = frame + FogRetryFrameInterval + Math.Abs(GetInstanceID() % FogPollFrameInterval);
			return;
		}
		if (hide == _lastHide)
			return;
		_lastHide = hide;
		for (var i = 0; i < _renderers.Length; i++)
		{
			var r = _renderers[i];
			if (r)
				r.forceRenderingOff = hide;
		}
	}

	/// <summary>
	/// Shared adventure-session root with a readable <c>world</c> member (Esquire fog / AI dump FoW).
	/// </summary>
	internal static bool TryGetAdventureSessionRoot(out object session, out string label)
	{
		session = GetSessionRootOrNull();
		label = null;
		if (session == null)
			return false;
		label = session.GetType().FullName ?? session.GetType().Name;
		return true;
	}

	/// <summary>
	/// Some builds omit <c>Hex.Session.BhSession</c> from metadata (obfuscation); session is still exposed from short
	/// holder types (e.g. <c>czr</c>/<c>hl</c>) per SessionProbe. Resolve any object whose graph reaches <c>.world</c>.
	/// </summary>
	private static object GetSessionRootOrNull()
	{
		if (_resolveSessionRoot != null)
		{
			var resolved = _resolveSessionRoot();
			if (resolved != null)
				return resolved;
		}

		lock (SessionBootstrapLock)
		{
			if (_resolveSessionRoot == null)
				TryBootstrapSessionResolver();
		}

		if (_resolveSessionRoot != null)
		{
			var resolved = _resolveSessionRoot();
			if (resolved != null)
				return resolved;
		}

		return null;
	}

	private static void TryBootstrapSessionResolver()
	{
		{
			if (_resolveSessionRoot == null)
				_resolveSessionRoot = ResolveCachedSessionRoot;

			var resolved = _resolveSessionRoot();
			if (resolved != null)
				return;

			if (!_loggedSessionFailure)
			{
				_loggedSessionFailure = true;
				Plugin.LogSource?.LogWarning(
					"EsquirePikemanMapBillboardFogSync: could not resolve session with .world - map fog hide inactive.");
			}

			return;
		}
		var asm = typeof(ObjCityConfig).Assembly;
		var holderTypeNames = new[]
		{
			"Hex.Session.BhSession",
			"czr",
			"cta",
			"hl",
			"czk",
		};
		var staticNames = new[] { "me", "instance", "current" };

		foreach (var htn in holderTypeNames)
		{
			var ht = asm.GetType(htn);
			if (ht == null)
				continue;
			foreach (var sn in staticNames)
			{
				var p = ht.GetProperty(sn, Static);
				if (p == null || !p.CanRead)
					continue;
				object sample = null;
				try
				{
					sample = p.GetValue(null);
				}
				catch
				{
					continue;
				}

				if (UnwrapUntilHasWorld(sample, 5) == null)
					continue;

				var capturedProp = p;
				var capturedHolder = htn;
				var capturedSlot = sn;
				_resolveSessionRoot = () =>
				{
					try
					{
						var r = capturedProp.GetValue(null);
						return UnwrapUntilHasWorld(r, 5);
					}
					catch
					{
						return null;
					}
				};

				if (!_loggedSessionPath)
				{
					_loggedSessionPath = true;
					Plugin.LogSource?.LogInfo(
						"EsquirePikemanMapBillboardFogSync: resolved session for fog via "
						+ capturedHolder
						+ "."
						+ capturedSlot
						+ " (BhSession type missing or renamed in this build).");
				}

				return;
			}
		}

		if (!_loggedSessionFailure)
		{
			_loggedSessionFailure = true;
			Plugin.LogSource?.LogWarning(
				"EsquirePikemanMapBillboardFogSync: could not resolve session with .world — map fog hide inactive.");
		}
	}

	private static object UnwrapUntilHasWorld(object root, int maxDepth)
	{
		var cur = root;
		for (var i = 0; i < maxDepth && cur != null; i++)
		{
			if (GetMember(cur, "world") != null)
				return cur;
			var next = GetMember(cur, "me");
			if (ReferenceEquals(next, cur))
				break;
			cur = next;
		}

		return null;
	}

	private static object ResolveCachedSessionRoot()
	{
		var cached = _sessionRootCache;
		if (HasWorldMember(cached))
			return cached;

		lock (SessionBootstrapLock)
		{
			cached = _sessionRootCache;
			if (HasWorldMember(cached))
				return cached;

			if (TryResolveSessionRootNow(out var resolved, out var label))
			{
				_sessionRootCache = resolved;
				if (!_loggedSessionPath)
				{
					_loggedSessionPath = true;
					Plugin.LogSource?.LogInfo(
						"EsquirePikemanMapBillboardFogSync: resolved session for fog via " + label + ".");
				}

				return resolved;
			}
		}

		_sessionRootCache = null;
		return null;
	}

	private static bool TryResolveSessionRootNow(out object root, out string label)
	{
		root = null;
		label = null;

		foreach (var candidate in EnumerateSessionRoots())
		{
			var candidateRoot = candidate.Value;
			if (!IsAlive(candidateRoot))
				continue;

			if (TryFindDeepMemberContainer(candidateRoot, "world", 6, 384, out var resolved, out var path))
			{
				root = resolved;
				label = string.IsNullOrEmpty(path) ? candidate.Key : candidate.Key + " -> " + path;
				return true;
			}
		}

		return false;
	}

	private static IEnumerable<KeyValuePair<string, object>> EnumerateSessionRoots()
	{
		foreach (var asm in EnumerateCandidateAssemblies())
		{
			foreach (var typeName in SessionHolderTypeNames)
			{
				var type = asm.GetType(typeName);
				if (type == null)
					continue;
				foreach (var staticName in SessionHolderStaticNames)
				{
					if (!TryGetMemberValue(null, type, staticName, out var root) || !IsAlive(root))
						continue;
					yield return new KeyValuePair<string, object>(asm.GetName().Name + ":" + typeName + "." + staticName, root);
				}
			}

			Type[] types = null;
			try
			{
				types = asm.GetTypes();
			}
			catch (ReflectionTypeLoadException ex)
			{
				types = ex.Types;
			}
			catch
			{
				types = null;
			}

			if (types == null)
				continue;

			foreach (var type in types)
			{
				if (type == null || !LooksLikeSessionHolderType(type))
					continue;
				foreach (var staticName in SessionHolderStaticNames)
				{
					if (!TryGetMemberValue(null, type, staticName, out var root) || !IsAlive(root))
						continue;
					yield return new KeyValuePair<string, object>((type.FullName ?? type.Name) + "." + staticName, root);
				}

				foreach (var member in EnumerateStaticReferenceMembers(type))
					yield return member;
			}
		}

	}

	private static IEnumerable<Assembly> EnumerateCandidateAssemblies()
	{
		yield return typeof(ObjCityConfig).Assembly;
		Assembly[] assemblies = null;
		try
		{
			assemblies = AppDomain.CurrentDomain.GetAssemblies();
		}
		catch
		{
			assemblies = null;
		}

		if (assemblies == null)
			yield break;
		var seen = new HashSet<Assembly>();
		foreach (var asm in assemblies)
		{
			if (asm == null || !seen.Add(asm))
				continue;
			var n = asm.GetName().Name ?? string.Empty;
			if (n.IndexOf("Hex", StringComparison.OrdinalIgnoreCase) < 0
			    && n.IndexOf("Assembly-CSharp", StringComparison.OrdinalIgnoreCase) < 0
			    && n.IndexOf("OfflineUnlockMod", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			yield return asm;
		}
	}

	private static bool LooksLikeSessionHolderType(Type type)
	{
		var fullName = type.FullName ?? type.Name ?? string.Empty;
		return fullName.IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Hud", StringComparison.OrdinalIgnoreCase) >= 0
		       || string.Equals(fullName, "cta", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(fullName, "hl", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(fullName, "czr", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(fullName, "czk", StringComparison.OrdinalIgnoreCase);
	}

	private static IEnumerable<KeyValuePair<string, object>> EnumerateStaticReferenceMembers(Type type)
	{
		var label = type.FullName ?? type.Name ?? "?";
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			var flags = Static | BindingFlags.DeclaredOnly;
			PropertyInfo[] props = null;
			FieldInfo[] fields = null;
			try { props = cur.GetProperties(flags); } catch { props = null; }
			try { fields = cur.GetFields(flags); } catch { fields = null; }
			if (props != null)
			{
				foreach (var p in props)
				{
					if (p == null || !p.CanRead || p.GetIndexParameters().Length != 0 || IsSimpleValueType(p.PropertyType))
						continue;
					object value = null;
					try { value = p.GetValue(null); } catch { value = null; }
					if (IsAlive(value))
						yield return new KeyValuePair<string, object>(label + "." + p.Name, value);
				}
			}

			if (fields == null)
				continue;
			foreach (var f in fields)
			{
				if (f == null || IsSimpleValueType(f.FieldType))
					continue;
				object value = null;
				try { value = f.GetValue(null); } catch { value = null; }
				if (IsAlive(value))
					yield return new KeyValuePair<string, object>(label + "." + f.Name, value);
			}
		}
	}

	private static bool TryFindDeepMemberContainer(object root, string memberName, int maxDepth, int maxNodes, out object found, out string path)
	{
		found = null;
		path = null;
		if (!IsAlive(root) || string.IsNullOrEmpty(memberName) || maxDepth < 0 || maxNodes <= 0)
			return false;

		var queue = new Queue<SearchNode>();
		var visited = new HashSet<object>(ReferenceIdentityComparer.Instance);
		visited.Add(root);
		queue.Enqueue(new SearchNode { Value = root, Path = root.GetType().Name, Depth = 0 });
		var nodes = 0;

		while (queue.Count > 0 && nodes < maxNodes)
		{
			var cur = queue.Dequeue();
			nodes++;
			var current = cur.Value;
			if (!IsAlive(current))
				continue;

			if (TryGetMemberValue(current, current.GetType(), memberName, out var member) && member != null)
			{
				found = current;
				path = cur.Path;
				return true;
			}

			if (cur.Depth >= maxDepth)
				continue;

			QueueChildren(current, cur.Path, cur.Depth, queue, visited, maxDepth, maxNodes, ref nodes);
		}

		return false;
	}

	private static void QueueChildren(
		object current,
		string currentPath,
		int currentDepth,
		Queue<SearchNode> queue,
		HashSet<object> visited,
		int maxDepth,
		int maxNodes,
		ref int nodes)
	{
		if (!IsAlive(current) || currentDepth >= maxDepth || nodes >= maxNodes)
			return;

		// UnityEngine.Object getters can bridge into native engine state. Reflection-walking them is unsafe in
		// IL2CPP and has crashed in Camera.get_layerCullDistances, so never deep-scan engine objects.
		if (current is UnityEngine.Object)
			return;

		if (current is System.Collections.IEnumerable enumerable && !(current is string))
		{
			var index = 0;
			foreach (var item in enumerable)
			{
				if (nodes >= maxNodes)
					break;
				if (!ShouldTraverse(item))
				{
					index++;
					continue;
				}
				if (visited.Add(item))
				{
					queue.Enqueue(new SearchNode
					{
						Value = item,
						Path = currentPath + "[" + index + "]",
						Depth = currentDepth + 1,
					});
				}
				index++;
			}
		}

		for (var cur = current.GetType(); cur != null && cur != typeof(object) && nodes < maxNodes; cur = cur.BaseType)
		{
			var flags = Inst | BindingFlags.DeclaredOnly;
			try
			{
				foreach (var prop in cur.GetProperties(flags))
				{
					if (nodes >= maxNodes)
						break;
					if (prop == null || prop.GetIndexParameters().Length != 0 || !prop.CanRead)
						continue;
					object value;
					try
					{
						value = prop.GetValue(current);
					}
					catch
					{
						continue;
					}

					if (!ShouldTraverse(value) || !visited.Add(value))
						continue;
					queue.Enqueue(new SearchNode
					{
						Value = value,
						Path = currentPath + "." + prop.Name,
						Depth = currentDepth + 1,
					});
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				foreach (var field in cur.GetFields(flags))
				{
					if (nodes >= maxNodes)
						break;
					if (field == null)
						continue;
					object value;
					try
					{
						value = field.GetValue(current);
					}
					catch
					{
						continue;
					}

					if (!ShouldTraverse(value) || !visited.Add(value))
						continue;
					queue.Enqueue(new SearchNode
					{
						Value = value,
						Path = currentPath + "." + field.Name,
						Depth = currentDepth + 1,
					});
				}
			}
			catch
			{
				// ignore
			}
		}
	}

	private static bool ShouldTraverse(object value)
	{
		return IsAlive(value) && !(value is UnityEngine.Object) && !IsSimpleValueType(value.GetType());
	}

	private static bool IsSimpleValueType(Type t)
	{
		if (t == null)
			return true;
		if (t.IsPrimitive || t.IsEnum)
			return true;
		return t == typeof(string)
		       || t == typeof(decimal)
		       || t == typeof(DateTime)
		       || t == typeof(TimeSpan)
		       || t == typeof(Guid)
		       || t == typeof(IntPtr)
		       || t == typeof(UIntPtr)
		       || t == typeof(Type);
	}

	private static bool IsAlive(object obj)
	{
		if (obj == null)
			return false;
		if (obj is UnityEngine.Object xk)
			return xk;
		return true;
	}

	private static bool HasWorldMember(object root)
	{
		if (!IsAlive(root))
			return false;
		return TryGetMemberValue(root, root.GetType(), "world", out var world) && world != null;
	}

	private bool TryGetShouldHideForLocalFog(out bool hide)
	{
		hide = false;
		try
		{
			var session = GetSessionRootOrNull();
			if (session == null)
				return false;

			if (!TryGetFogNode(out var node) || node < 0)
				return false;

			if (!TryGetCachedFog(session, out var fog))
				return false;

			return TryComputeHideFromFogObject(fog, node, out hide);
		}
		catch (Exception ex)
		{
			MaybeDiag("TryGetShouldHideForLocalFog exception: " + ex.Message);
			return false;
		}
	}

	private static bool TryComputeHideFromFogObject(object fog, int node, out bool hide)
	{
		hide = false;

		var ft = fog.GetType();
		var cache = GetOrBuildFogMethodCache(ft);
		var any = false;

		if (cache.IsNodeHiddenInt != null)
		{
			try
			{
				hide = hide || Convert.ToBoolean(cache.IsNodeHiddenInt.Invoke(fog, new object[] { node }));
				any = true;
			}
			catch
			{
				// ignore
			}
		}

		if (cache.IsNodeVisibleInt != null)
		{
			try
			{
				var vis = Convert.ToBoolean(cache.IsNodeVisibleInt.Invoke(fog, new object[] { node }));
				hide = hide || !vis;
				any = true;
			}
			catch
			{
				// ignore
			}
		}

		if (any)
			return true;

		if (TryReadVisibilityMapNode(fog, node, out var visible))
		{
			hide = !visible;
			return true;
		}

		return false;
	}

	private bool TryGetCachedFog(object session, out object fog)
	{
		fog = null;
		if (_cachedFogResolved && IsAlive(_cachedFog))
		{
			fog = _cachedFog;
			return true;
		}

		var world = GetMember(session, "world");
		if (world == null)
			return false;
		var sides = GetMember(world, "sides");
		if (sides == null)
			return false;
		var lookFor = GetMember(sides, "lookFor");
		if (lookFor == null)
			return false;
		var data = GetMember(lookFor, "data");
		if (data == null)
			return false;
		fog = GetMember(data, "fogData");
		if (fog == null)
			return false;

		_cachedFog = fog;
		_cachedFogResolved = true;
		return true;
	}

	private static bool TryReadVisibilityMapNode(object fog, int node, out bool visible)
	{
		visible = false;
		if (fog == null || node < 0)
			return false;
		var map = GetMember(fog, "visibilityMap");
		if (map == null)
			return false;
		return TryReadIndexedBool(map, node, out visible);
	}

	private static bool TryReadIndexedBool(object indexed, int index, out bool value)
	{
		value = false;
		if (indexed == null || index < 0)
			return false;
		if (indexed is bool[] arr)
		{
			if (index >= arr.Length)
				return false;
			value = arr[index];
			return true;
		}
		if (indexed is System.Collections.IList list)
		{
			if (index >= list.Count)
				return false;
			value = Convert.ToBoolean(list[index]);
			return true;
		}

		try
		{
			var t = indexed.GetType();
			var len = ReadCollectionLength(indexed, t);
			if (len >= 0 && index >= len)
				return false;
			var item = t.GetProperty(
				"Item",
				Inst,
				null,
				null,
				new[] { typeof(int) },
				null);
			if (item != null && item.CanRead)
			{
				value = Convert.ToBoolean(item.GetValue(indexed, new object[] { index }));
				return true;
			}

			var getter = t.GetMethod(
				"get_Item",
				Inst,
				null,
				new[] { typeof(int) },
				null);
			if (getter != null)
			{
				value = Convert.ToBoolean(getter.Invoke(indexed, new object[] { index }));
				return true;
			}
		}
		catch
		{
			return false;
		}

		return false;
	}

	private static int ReadCollectionLength(object indexed, Type t)
	{
		try
		{
			var p = t.GetProperty("Length", Inst);
			if (p != null && p.CanRead)
				return Convert.ToInt32(p.GetValue(indexed));
		}
		catch
		{
		}

		try
		{
			var p = t.GetProperty("Count", Inst);
			if (p != null && p.CanRead)
				return Convert.ToInt32(p.GetValue(indexed));
		}
		catch
		{
		}

		return -1;
	}

	private static FogMethodCache GetOrBuildFogMethodCache(Type ft)
	{
		lock (FogCaches)
		{
			if (FogCaches.TryGetValue(ft, out var existing))
				return existing;

			var c = new FogMethodCache { Scanned = true };
			foreach (var m in ft.GetMethods(Inst))
			{
				if (m.IsStatic)
					continue;
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType != typeof(int))
					continue;
				if (m.ReturnType != typeof(bool))
					continue;
				var n = m.Name;
				if (n == "IsNodeHidden" && c.IsNodeHiddenInt == null)
					c.IsNodeHiddenInt = m;
				else if ((n == "IsNodeVisible" || n == "IsVisibleForNode" || n == "IsNodeVisibleToPlayer")
				         && c.IsNodeVisibleInt == null)
					c.IsNodeVisibleInt = m;
			}

			// Broader names if Il2Cpp strips or renames (still bool(int) only).
			foreach (var m in ft.GetMethods(Inst))
			{
				if (m.IsStatic)
					continue;
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType != typeof(int) || m.ReturnType != typeof(bool))
					continue;
				var n = m.Name;
				if (c.IsNodeHiddenInt == null && n.IndexOf("Hidden", StringComparison.OrdinalIgnoreCase) >= 0)
					c.IsNodeHiddenInt = m;
				else if (c.IsNodeVisibleInt == null
				         && n.IndexOf("Visible", StringComparison.OrdinalIgnoreCase) >= 0
				         && n.IndexOf("Invis", StringComparison.OrdinalIgnoreCase) < 0)
					c.IsNodeVisibleInt = m;
			}

			FogCaches[ft] = c;
			return c;
		}
	}

	private bool TryGetFogNode(out int node)
	{
		node = -1;
		var frame = Time.frameCount;
		if (_cachedNode >= 0 && frame < _cachedNodeRefreshFrame)
		{
			node = _cachedNode;
			return true;
		}

		var squadBh = FindBhMapSquadInParents();
		if (squadBh != null)
		{
			var squad = GetMember(squadBh, "squad");
			if (squad != null && TryReadSquadMapNode(squad, out node) && node >= 0)
			{
				_cachedNode = node;
				_cachedNodeRefreshFrame = frame + 60;
				return true;
			}
			MaybeDiag("BhMapSquad present but squad map node unreadable; using NodeByPos fallback.");
			if (TryNodeFromMapAtPosition(out node))
			{
				_cachedNode = node;
				_cachedNodeRefreshFrame = frame + 60;
				return true;
			}

			_cachedNodeRefreshFrame = frame + FogRetryFrameInterval;
			return false;
		}

		MaybeDiag("BhMapSquad not found in parents; trying NodeByPos fallback.");
		if (TryNodeFromMapAtPosition(out node))
		{
			_cachedNode = node;
			_cachedNodeRefreshFrame = frame + 60;
			return true;
		}

		_cachedNodeRefreshFrame = frame + FogRetryFrameInterval;
		return false;
	}

	private static readonly string[] SquadNodeMemberNames =
	{
		"node",
		"mapNode",
		"hexNode",
		"cellIndex",
		"hex",
		"cell",
		"index",
	};

	private static bool TryReadSquadMapNode(object squad, out int node)
	{
		node = -1;
		if (squad == null)
			return false;
		for (var i = 0; i < SquadNodeMemberNames.Length; i++)
		{
			if (TryReadIntMember(squad, SquadNodeMemberNames[i], out node) && node >= 0)
				return true;
		}

		return false;
	}

	private bool TryNodeFromMapAtPosition(out int node)
	{
		node = -1;
		try
		{
			var session = GetSessionRootOrNull();
			if (session == null)
				return false;
			var world = GetMember(session, "world");
			if (world == null)
				return false;
			var map = GetMember(world, "map");
			if (map == null)
				return false;
			var m = map.GetType().GetMethod(
				"NodeByPos",
				Inst,
				null,
				new[] { typeof(float), typeof(float) },
				null);
			if (m == null)
				return false;
			var pos = transform.position;
			var nodeObj = m.Invoke(map, new object[] { pos.x, pos.z });
			return TryReadInt(nodeObj, out node) && node >= 0;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadIntMember(object target, string name, out int value)
	{
		value = -1;
		var raw = GetMember(target, name);
		return TryReadInt(raw, out value);
	}

	private static bool TryReadInt(object raw, out int value)
	{
		value = -1;
		if (raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private Component FindBhMapSquadInParents()
	{
		if (_cachedBhMapSquad)
			return _cachedBhMapSquad;
		if (_searchedBhMapSquad)
			return null;
		_searchedBhMapSquad = true;

		for (var t = transform; t; t = t.parent)
		{
			foreach (var c in t.GetComponents<Component>())
			{
				if (!c)
					continue;
				var fn = c.GetType().FullName;
				if (fn == BhMapSquadTypeName
				    || (fn != null && fn.EndsWith(".BhMapSquad", StringComparison.Ordinal)))
				{
					_cachedBhMapSquad = c;
					return c;
				}
			}
		}

		return null;
	}

	private static object GetMember(object target, string name)
	{
		if (target == null)
			return null;
		if (target is Type t)
			return TryGetMemberValue(null, t, name, out var staticValue) ? staticValue : null;
		return TryGetMemberValue(target, target.GetType(), name, out var value) ? value : null;
	}

	private static bool TryGetMemberValue(object instance, Type t, string name, out object value)
	{
		value = null;
		if (t == null || string.IsNullOrEmpty(name))
		{
			return false;
		}

		var staticOnly = instance == null;
		var invokeTarget = staticOnly ? null : instance;
		object candidate = null;

		bool TryProperty(PropertyInfo p)
		{
			if (p == null || p.GetIndexParameters().Length != 0)
			{
				return false;
			}

			try
			{
				candidate = p.GetValue(invokeTarget);
				return true;
			}
			catch
			{
				return false;
			}
		}

		bool TryField(FieldInfo f)
		{
			if (f == null)
			{
				return false;
			}

			try
			{
				candidate = f.GetValue(invokeTarget);
				return true;
			}
			catch
			{
				return false;
			}
		}

		for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			var decl = (staticOnly ? BindingFlags.Static : BindingFlags.Instance)
				| BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

			PropertyInfo prop = null;
			try
			{
				prop = cur.GetProperty(name, decl);
			}
			catch
			{
				prop = null;
			}

			if (prop != null && TryProperty(prop))
			{
				value = candidate;
				return true;
			}

			try
			{
				var fExact = cur.GetField(name, decl);
				if (fExact != null && TryField(fExact))
				{
					value = candidate;
					return true;
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				var bf = "<" + name + ">k__BackingField";
				var fBk = cur.GetField(bf, decl);
				if (fBk != null && TryField(fBk))
				{
					value = candidate;
					return true;
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				foreach (var p in cur.GetProperties(decl))
				{
					if (p.GetIndexParameters().Length != 0)
					{
						continue;
					}

					if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase) && TryProperty(p))
					{
						value = candidate;
						return true;
					}
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				foreach (var f in cur.GetFields(decl))
				{
					if (string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase) && TryField(f))
					{
						value = candidate;
						return true;
					}
				}
			}
			catch
			{
				// ignore
			}
		}

		value = null;
		return false;
	}

	private void MaybeDiag(string msg)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || _diagLogged >= 2 || _globalDiagLogged >= 32)
			return;
		_diagLogged++;
		_globalDiagLogged++;
		Plugin.LogSource?.LogInfo("EsquirePikemanMapBillboardFogSync: " + msg);
	}
}
