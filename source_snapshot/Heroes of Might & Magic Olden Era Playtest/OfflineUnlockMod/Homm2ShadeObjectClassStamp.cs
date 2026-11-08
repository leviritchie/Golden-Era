using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime;
using UnityEngine;
using UnityEngine.Rendering;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Writes VCMI RestyleObjectClass values into the backbuffer alpha so ReShade Map-objects
/// ink and visitable solids follow Golden Era identity, not pixel colour.
/// Placed-object visitable class is ObjectConfig.isInteractable, the same bit
/// Settings "always highlight interactibles" uses. Heroes and battle drawers stay visitable.
/// Terrain and UI stay unstamped (alpha 255 → shader class 0).
/// Alpha-only writes come from the precompiled ColorMask A shader bundle, not from
/// runtime ShaderLab compilation and not from GL.ColorMask (missing on this interop).
/// </summary>
internal static class Homm2ShadeObjectClassStamp
{
	internal const string BundleName = "homm2_shade_object_class";
	internal const string ShaderName = "OldenEra/Homm2/ShadeObjectClass";
	private const int RefreshIntervalFrames = 20;
	private const BindingFlags MemberFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private static readonly Color LandscapeColor = new Color(0f, 0f, 0f, GameSymbols.Homm2ShadeObjectClass.LandscapeAlpha / 255f);
	private static readonly Color VisitableColor = new Color(0f, 0f, 0f, GameSymbols.Homm2ShadeObjectClass.VisitableAlpha / 255f);

	private static ManualLogSource _log;
	private static bool _hooked;
	private static bool _typeMissLogged;
	private static bool _bundleMissLogged;
	private static bool _shaderMissLogged;
	private static int _lastRefreshFrame = -999;
	private static int _logFrames;
	private static Type _placedObjectType;
	private static Type _worldCameraType;
	private static Type _heroDrawerType;
	private static readonly List<Type> _battleDrawerTypes = new();
	private static readonly List<Renderer> _landscape = new();
	private static readonly List<Renderer> _visitable = new();
	private static readonly HashSet<int> _seen = new();
	private static readonly Dictionary<int, Material> _cutoutByRenderer = new();
	private static AssetBundle _bundle;
	private static Shader _shader;
	private static Material _opaqueLandscape;
	private static Material _opaqueVisitable;
	private static CommandBuffer _cb;
	private static Harmony _harmony;
	private static bool _objectTypeInvokeLogged;
	private static bool _interactableReadLogged;
	private static int _unresolvedType;
	private static int _blockType;
	private static int _unknownType;
	private static int _resMineType;
	private static int _interactableTrue;
	private static int _interactableFalse;
	private static int _unresolvedInteractable;
	private static string _typeHistogram = "";

	internal static void Ensure(ManualLogSource log)
	{
		_log = log;
		if (_hooked)
			return;
		try
		{
			var harmony = Plugin.HarmonyInstance;
			if (harmony == null)
			{
				_log?.LogError("Homm2ShadeObjectClassStamp: Harmony instance missing; refusing to write class.");
				return;
			}
			var method = typeof(RenderPipelineManager).GetMethod(
				nameof(RenderPipelineManager.EndCameraRendering),
				BindingFlags.Public | BindingFlags.Static);
			if (method == null)
			{
				_log?.LogError("Homm2ShadeObjectClassStamp: RenderPipelineManager.EndCameraRendering missing; refusing to write class.");
				return;
			}
			harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm2ShadeObjectClassStamp), nameof(EndCameraPostfix)));
			_harmony = harmony;
			_hooked = true;
			_log?.LogInfo("Homm2ShadeObjectClassStamp: host attached. Class comes from ObjectConfig.isInteractable / hero drawers / battle drawers.");
		}
		catch (Exception ex)
		{
			_log?.LogError("Homm2ShadeObjectClassStamp: host attach failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static void Release()
	{
		if (_harmony != null)
		{
			try
			{
				var method = typeof(RenderPipelineManager).GetMethod(
					nameof(RenderPipelineManager.EndCameraRendering),
					BindingFlags.Public | BindingFlags.Static);
				if (method != null)
					_harmony.Unpatch(method, HarmonyPatchType.Postfix, _harmony.Id);
			}
			catch
			{
			}
			_harmony = null;
		}
		_hooked = false;
	}

	private static void EndCameraPostfix(Camera camera)
	{
		OnEndCameraRendering(camera);
	}

	private static void OnEndCameraRendering(Camera camera)
	{
		if (!_hooked)
			return;
		var frame = Time.frameCount;
		if (frame - _lastRefreshFrame >= RefreshIntervalFrames)
		{
			RefreshRegistry();
			_lastRefreshFrame = frame;
		}
		var skip = StampSkipReason(camera);
		_logFrames++;
		if (_logFrames == 1 || _logFrames % 300 == 0)
			LogStampStatus(camera, skip);
		if (skip != null)
			return;
		if (!EnsureMaterials())
			return;
		if (_landscape.Count == 0 && _visitable.Count == 0)
			return;
		if (_cb == null)
		{
			_cb = new CommandBuffer();
			_cb.name = "Homm2ShadeObjectClass";
		}
		_cb.Clear();
		DrawClass(_cb, _landscape, LandscapeColor, _opaqueLandscape);
		DrawClass(_cb, _visitable, VisitableColor, _opaqueVisitable);
		var previous = RenderTexture.active;
		try
		{
			Graphics.SetRenderTarget(camera.targetTexture);
			Graphics.ExecuteCommandBuffer(_cb);
		}
		finally
		{
			RenderTexture.active = previous;
		}
	}

	private static string StampSkipReason(Camera camera)
	{
		if (!camera)
			return "null";
		if (!camera.isActiveAndEnabled)
			return "disabled";
		var name = camera.name ?? "";
		if (name.IndexOf("UI", StringComparison.OrdinalIgnoreCase) >= 0)
			return "ui";
		if (name.IndexOf("Overlay", StringComparison.OrdinalIgnoreCase) >= 0)
			return "overlay";
		if (HasWorldCamera(camera))
			return null;
		if (_visitable.Count > 0 && camera == Camera.main)
			return null;
		return "not-world";
	}

	private static bool HasWorldCamera(Camera camera)
	{
		if (!camera)
			return false;
		var type = ResolveWorldCameraType();
		if (type != null)
		{
			try
			{
				var il2CppType = Il2CppType.From(type);
				for (var transform = camera.transform; transform; transform = transform.parent)
				{
					if (transform.GetComponent(il2CppType) != null)
						return true;
				}
			}
			catch
			{
			}
		}
		var world = ResolveBhWorldCamera();
		return world && world.GetInstanceID() == camera.GetInstanceID();
	}

	private static Camera ResolveBhWorldCamera()
	{
		var type = ResolveWorldCameraType();
		if (type == null)
			return null;
		object singleton = null;
		try
		{
			var getter = GameMember.FindFirstMethod(
				type,
				type,
				Type.EmptyTypes,
				GameSymbols.HomecomingLayerViewToggle.WorldCameraSingleton);
			if (getter != null && getter.IsStatic)
				singleton = getter.Invoke(null, null);
		}
		catch (Exception ex)
		{
			if (!_objectTypeInvokeLogged)
			{
				_objectTypeInvokeLogged = true;
				_log?.LogError("Homm2ShadeObjectClassStamp: BhWorldCamera singleton failed: " + ex.GetType().Name + ": " + ex.Message);
			}
		}
		if (singleton == null)
			return null;
		var camera = InvokeFirstNoArg(singleton, typeof(Camera), GameSymbols.Homm2ShadeObjectClass.WorldCameraCamera) as Camera;
		if (camera)
			return camera;
		if (singleton is Component component)
			return component.GetComponent<Camera>() ?? component.GetComponentInChildren<Camera>();
		return null;
	}

	private static void LogStampStatus(Camera camera, string skip)
	{
		var sb = new StringBuilder();
		sb.Append("Homm2ShadeObjectClassStamp: landscape=").Append(_landscape.Count);
		sb.Append(" visitable=").Append(_visitable.Count);
		sb.Append(" skip=").Append(skip ?? "stamp");
		sb.Append(" shaderSupported=").Append(_shader && _shader.isSupported ? "1" : "0");
		if (camera)
		{
			sb.Append(" cam=").Append(camera.name ?? "");
			sb.Append(" targetTexture=").Append(camera.targetTexture ? camera.targetTexture.name : "swapchain");
			sb.Append(" worldCam=").Append(HasWorldCamera(camera) ? "1" : "0");
		}
		sb.Append(" mines=").Append(_resMineType);
		sb.Append(" block=").Append(_blockType);
		sb.Append(" unknown=").Append(_unknownType);
		sb.Append(" unresolved=").Append(_unresolvedType);
		sb.Append(" interactable=").Append(_interactableTrue);
		sb.Append(" notInteractable=").Append(_interactableFalse);
		sb.Append(" unresolvedInteractable=").Append(_unresolvedInteractable);
		sb.Append(" types=").Append(string.IsNullOrEmpty(_typeHistogram) ? "none" : _typeHistogram);
		_log?.LogInfo(sb.ToString());
	}

	private static bool EnsureMaterials()
	{
		if (_opaqueLandscape && _opaqueVisitable && _shader)
			return _shader.isSupported;
		_shader = ResolveShader();
		if (!_shader)
			return false;
		if (!_shader.isSupported)
		{
			if (!_shaderMissLogged)
			{
				_shaderMissLogged = true;
				_log?.LogError("Homm2ShadeObjectClassStamp: ColorMask A shader is not supported; refusing to write class.");
			}
			return false;
		}
		_opaqueLandscape = CreateClassMaterial(LandscapeColor, useCutoff: false);
		_opaqueVisitable = CreateClassMaterial(VisitableColor, useCutoff: false);
		return _opaqueLandscape && _opaqueVisitable;
	}

	private static Shader ResolveShader()
	{
		if (_shader)
			return _shader;
		var path = ResolveBundlePath();
		if (string.IsNullOrEmpty(path))
		{
			if (!_bundleMissLogged)
			{
				_bundleMissLogged = true;
				_log?.LogError("Homm2ShadeObjectClassStamp: precompiled bundle '" + BundleName + "' missing; refusing to write class.");
			}
			return null;
		}
		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (!_bundle)
			{
				if (!_bundleMissLogged)
				{
					_bundleMissLogged = true;
					_log?.LogError("Homm2ShadeObjectClassStamp: AssetBundle.LoadFromFile returned null for " + path + "; refusing to write class.");
				}
				return null;
			}
			_shader = LoadShaderFromBundle(_bundle);
		}
		catch (Exception ex)
		{
			if (!_bundleMissLogged)
			{
				_bundleMissLogged = true;
				_log?.LogError("Homm2ShadeObjectClassStamp: bundle load failed: " + ex.Message);
			}
			return null;
		}
		if (!_shader && !_shaderMissLogged)
		{
			_shaderMissLogged = true;
			_log?.LogError("Homm2ShadeObjectClassStamp: shader '" + ShaderName + "' missing from " + path + "; refusing to write class.");
		}
		return _shader;
	}

	private static Shader LoadShaderFromBundle(AssetBundle bundle)
	{
		if (!bundle)
			return null;
		try
		{
			var shader = bundle.LoadAsset<Shader>("assets/shaders/homm2shadeobjectclass.shader");
			if (shader && string.Equals(shader.name, ShaderName, StringComparison.Ordinal))
				return shader;
			foreach (var name in bundle.GetAllAssetNames())
			{
				if (string.IsNullOrEmpty(name))
					continue;
				if (!name.EndsWith(".shader", StringComparison.OrdinalIgnoreCase))
					continue;
				shader = bundle.LoadAsset<Shader>(name);
				if (shader && string.Equals(shader.name, ShaderName, StringComparison.Ordinal))
					return shader;
			}
		}
		catch
		{
		}
		return null;
	}

	private static string ResolveBundlePath()
	{
		var candidates = new[]
		{
			Path.Combine(Paths.PluginPath, "OfflineUnlockMod", BundleName),
			Path.Combine(Paths.PluginPath, BundleName),
			Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", BundleName),
		};
		for (var i = 0; i < candidates.Length; i++)
		{
			if (File.Exists(candidates[i]))
				return candidates[i];
		}
		return null;
	}

	private static Material CreateClassMaterial(Color classColor, bool useCutoff)
	{
		var mat = new Material(_shader);
		mat.hideFlags = HideFlags.HideAndDontSave;
		mat.color = classColor;
		mat.SetFloat("_UseCutoff", useCutoff ? 1f : 0f);
		mat.SetFloat("_Cutoff", useCutoff ? 0.5f : 0f);
		return mat;
	}

	private static void DrawClass(CommandBuffer cb, List<Renderer> renderers, Color classColor, Material opaque)
	{
		for (var i = 0; i < renderers.Count; i++)
		{
			var renderer = renderers[i];
			if (!renderer || !renderer.enabled || !renderer.gameObject.activeInHierarchy)
				continue;
			if (renderer.forceRenderingOff)
				continue;
			var source = renderer.sharedMaterial;
			Material mat;
			if (NeedsCutout(source))
			{
				mat = GetCutoutMaterial(renderer, classColor, source);
			}
			else
			{
				mat = opaque;
				mat.color = classColor;
			}
			if (!mat)
				continue;
			try
			{
				cb.DrawRenderer(renderer, mat);
			}
			catch
			{
			}
		}
	}

	private static Material GetCutoutMaterial(Renderer renderer, Color classColor, Material source)
	{
		var id = renderer.GetInstanceID();
		if (!_cutoutByRenderer.TryGetValue(id, out var mat) || !mat)
		{
			mat = CreateClassMaterial(classColor, useCutoff: true);
			_cutoutByRenderer[id] = mat;
		}
		mat.color = classColor;
		if (source && source.HasProperty("_MainTex"))
			mat.mainTexture = source.mainTexture;
		if (source && source.HasProperty("_Cutoff"))
			mat.SetFloat("_Cutoff", source.GetFloat("_Cutoff"));
		else
			mat.SetFloat("_Cutoff", 0.5f);
		mat.SetFloat("_UseCutoff", 1f);
		return mat;
	}

	private static bool NeedsCutout(Material source)
	{
		if (!source || !source.shader)
			return false;
		var shaderName = source.shader.name ?? "";
		if (shaderName.IndexOf("Cutout", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (shaderName.IndexOf("Sprite", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (shaderName.IndexOf("unit_cutout", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		return source.HasProperty("_MainTex") && source.renderQueue >= 2450;
	}

	private static void RefreshRegistry()
	{
		_landscape.Clear();
		_visitable.Clear();
		_seen.Clear();
		CollectPlacedObjects();
		CollectHeroes();
		CollectBattleDrawers();
	}

	private static void CollectPlacedObjects()
	{
		_unresolvedType = 0;
		_blockType = 0;
		_unknownType = 0;
		_resMineType = 0;
		_interactableTrue = 0;
		_interactableFalse = 0;
		_unresolvedInteractable = 0;
		var counts = new Dictionary<string, int>();
		var placedType = ResolvePlacedObjectType();
		if (placedType == null)
		{
			_typeHistogram = "placed-unresolved";
			return;
		}
		ForEachUnityOfType(placedType, obj =>
		{
			var root = GetReleaseMapObjectRoot(obj);
			if (!root)
				return;
			var interactable = ReadIsInteractable(obj);
			CountInteractable(interactable);
			var objectType = ReadPlacedObjectType(obj);
			CountPlacedType(counts, objectType);
			CollectRootRenderers(root, interactable == true ? _visitable : _landscape);
		});
		_typeHistogram = FormatTypeHistogram(counts);
	}

	private static EObjectType? ReadPlacedObjectType(object instance)
	{
		var meta = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.MetaFields);
		var config = GetFirstFieldValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		return ReadObjectType(config);
	}

	private static bool? ReadIsInteractable(object instance)
	{
		var meta = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.MetaFields);
		var config = GetFirstFieldValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		var fromConfig = ReadNamedBool(
			config,
			GameSymbols.Homm2ShadeObjectClass.ObjectConfigIsInteractableId,
			GameSymbols.Homm2ShadeObjectClass.ObjectConfigIsInteractableFields);
		if (fromConfig.HasValue)
			return fromConfig;
		return ReadNamedBool(
			instance,
			GameSymbols.Homm2ShadeObjectClass.ObjectConfigIsInteractableId,
			GameSymbols.Homm2ShadeObjectClass.ObjectConfigIsInteractableFields);
	}

	private static bool? ReadNamedBool(object obj, string id, string[] hints)
	{
		if (obj == null || hints == null || hints.Length == 0)
			return null;
		for (var t = obj.GetType(); t != null && t != typeof(object); t = t.BaseType)
		{
			for (var i = 0; i < hints.Length; i++)
			{
				var name = hints[i];
				try
				{
					var field = t.GetField(name, MemberFlags);
					if (field != null)
					{
						var raw = field.GetValue(obj);
						if (raw != null)
							return Convert.ToBoolean(raw);
					}
				}
				catch (Exception ex)
				{
					LogInteractableReadFailure(ex);
					return null;
				}
				try
				{
					var property = t.GetProperty(name, MemberFlags);
					if (property != null && property.CanRead)
					{
						var raw = property.GetValue(obj, null);
						if (raw != null)
							return Convert.ToBoolean(raw);
					}
				}
				catch (Exception ex)
				{
					LogInteractableReadFailure(ex);
					return null;
				}
			}
		}
		var fields = GameMember.FindFields(obj.GetType(), typeof(bool), id, hints);
		if (fields.Length == 0)
			return null;
		try
		{
			var raw = fields[0].GetValue(obj);
			if (raw == null)
				return null;
			return Convert.ToBoolean(raw);
		}
		catch (Exception ex)
		{
			LogInteractableReadFailure(ex);
			return null;
		}
	}

	private static void LogInteractableReadFailure(Exception ex)
	{
		if (_interactableReadLogged)
			return;
		_interactableReadLogged = true;
		_log?.LogError("Homm2ShadeObjectClassStamp: isInteractable read failed: " + ex.GetType().Name + ": " + ex.Message);
	}

	private static void CountInteractable(bool? interactable)
	{
		if (!interactable.HasValue)
		{
			_unresolvedInteractable++;
			return;
		}
		if (interactable.Value)
			_interactableTrue++;
		else
			_interactableFalse++;
	}

	private static void CountPlacedType(Dictionary<string, int> counts, EObjectType? objectType)
	{
		if (!objectType.HasValue)
		{
			_unresolvedType++;
			AddCount(counts, "unresolved");
			return;
		}
		switch (objectType.Value)
		{
			case EObjectType.Block:
				_blockType++;
				break;
			case EObjectType.Unknown:
				_unknownType++;
				break;
			case EObjectType.ResMine:
				_resMineType++;
				break;
		}
		AddCount(counts, objectType.Value.ToString());
	}

	private static void AddCount(Dictionary<string, int> counts, string key)
	{
		counts.TryGetValue(key, out var n);
		counts[key] = n + 1;
	}

	private static string FormatTypeHistogram(Dictionary<string, int> counts)
	{
		if (counts.Count == 0)
			return "none";
		var keys = new List<string>(counts.Keys);
		keys.Sort(StringComparer.Ordinal);
		var sb = new StringBuilder();
		for (var i = 0; i < keys.Count; i++)
		{
			if (i > 0)
				sb.Append(',');
			sb.Append(keys[i]).Append('=').Append(counts[keys[i]]);
		}
		return sb.ToString();
	}

	private static void CollectHeroes()
	{
		var heroRenderers = new List<Renderer>();
		Homm3HeroMapBillboardAnimatorRegistry.CollectLiveRenderers(heroRenderers);
		for (var i = 0; i < heroRenderers.Count; i++)
			AddRenderer(heroRenderers[i], _visitable);
		var drawerType = ResolveHeroDrawerType();
		if (drawerType == null)
			return;
		ForEachUnityOfType(drawerType, obj =>
		{
			var root = GetHeroDrawerRoot(obj);
			if (root)
				CollectRootRenderers(root, _visitable);
		});
	}

	private static void CollectBattleDrawers()
	{
		ResolveBattleDrawerTypes();
		for (var t = 0; t < _battleDrawerTypes.Count; t++)
		{
			ForEachUnityOfType(_battleDrawerTypes[t], obj =>
			{
				var root = AsGameObject(obj);
				if (root)
					CollectRootRenderers(root, _visitable);
			});
		}
	}

	private static EObjectType? ReadObjectType(object config)
	{
		if (config == null)
			return null;
		for (var t = config.GetType(); t != null && t != typeof(object); t = t.BaseType)
		{
			var method = GameMember.FindFirstMethod(
				t,
				typeof(EObjectType),
				Type.EmptyTypes,
				GameSymbols.Homm2ShadeObjectClass.ObjConfigObjectType);
			if (method == null)
				continue;
			try
			{
				var raw = method.Invoke(config, null);
				if (raw is EObjectType typed)
					return typed;
				if (raw != null && raw.GetType().IsEnum)
					return (EObjectType)Convert.ToInt32(raw);
			}
			catch (Exception ex)
			{
				if (!_objectTypeInvokeLogged)
				{
					_objectTypeInvokeLogged = true;
					_log?.LogError("Homm2ShadeObjectClassStamp: EObjectType invoke failed: " + ex.GetType().Name + ": " + ex.Message);
				}
			}
		}
		return null;
	}

	private static GameObject GetReleaseMapObjectRoot(object instance)
	{
		if (instance == null)
			return null;
		var root = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields) as GameObject;
		if (root)
			return root;
		var transform = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.RootTransformFields) as Transform;
		if (transform && transform.gameObject)
			return transform.gameObject;
		root = InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.CustomTownMapBillboard.RootGameObjectGetter) as GameObject;
		if (root)
			return root;
		transform = InvokeFirstNoArg(instance, typeof(Transform), GameSymbols.CustomTownMapBillboard.RootTransformGetter) as Transform;
		if (transform && transform.gameObject)
			return transform.gameObject;
		return AsGameObject(instance);
	}

	private static GameObject GetHeroDrawerRoot(object instance)
	{
		var root = GetFirstFieldValue(instance, GameSymbols.HeroMap.RootGameObjectProperties) as GameObject;
		if (root)
			return root;
		root = InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.HeroMap.RootGameObjectGetter) as GameObject;
		if (root)
			return root;
		return AsGameObject(instance);
	}

	private static void CollectRootRenderers(GameObject root, List<Renderer> dest)
	{
		if (!root)
			return;
		CollectRenderers(root.transform, dest);
	}

	private static void CollectRenderers(Transform root, List<Renderer> dest)
	{
		if (!root)
			return;
		var renderer = root.GetComponent(Il2CppType.Of<Renderer>())?.TryCast<Renderer>();
		AddRenderer(renderer, dest);
		for (var i = 0; i < root.childCount; i++)
			CollectRenderers(root.GetChild(i), dest);
	}

	private static void AddRenderer(Renderer renderer, List<Renderer> dest)
	{
		if (!renderer || !IsClassRenderer(renderer) || !_seen.Add(renderer.GetInstanceID()))
			return;
		dest.Add(renderer);
	}

	private static bool IsClassRenderer(Renderer renderer)
	{
		if (!renderer)
			return false;
		var typeName = renderer.GetType().Name ?? "";
		if (typeName.IndexOf("Particle", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		if (typeName.IndexOf("Trail", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		if (typeName.IndexOf("Line", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		if (typeName.IndexOf("Halo", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		var shaderName = RendererShaderName(renderer);
		if (string.Equals(shaderName, "Hex/TerrainMap", StringComparison.Ordinal))
			return false;
		if (shaderName.IndexOf("InternalError", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		if (shaderName.IndexOf("FallbackError", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		return true;
	}

	private static string RendererShaderName(Renderer renderer)
	{
		try
		{
			var material = renderer.sharedMaterial;
			if (!material || !material.shader)
				return "";
			return material.shader.name ?? "";
		}
		catch
		{
			return "";
		}
	}

	private static void ForEachUnityOfType(Type type, Action<UnityObject> visit)
	{
		if (type == null || visit == null)
			return;
		object found;
		try
		{
			found = Resources.FindObjectsOfTypeAll(Il2CppType.From(type));
		}
		catch
		{
			return;
		}
		if (found == null)
			return;
		foreach (var obj in (System.Collections.IEnumerable)found)
		{
			var unity = obj as UnityObject;
			if (unity)
				visit(unity);
		}
	}

	private static GameObject AsGameObject(object instance)
	{
		if (instance is GameObject go && go)
			return go;
		if (instance is Component component && component)
			return component.gameObject;
		try
		{
			var unity = instance as UnityObject;
			if (unity)
			{
				var cast = unity.TryCast<Component>();
				if (cast)
					return cast.gameObject;
			}
		}
		catch
		{
		}
		return null;
	}

	private static Type ResolvePlacedObjectType()
	{
		if (_placedObjectType != null)
			return _placedObjectType;
		_placedObjectType = GameMember.FindPlacedObjectType(
			GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
			GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints,
			name => GameMember.FindType(GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId + "." + name, name, logMiss: false));
		if (_placedObjectType == null && !_typeMissLogged)
		{
			_typeMissLogged = true;
			_log?.LogError("Homm2ShadeObjectClassStamp: placed-object type unresolved; map objects will not receive class.");
		}
		return _placedObjectType;
	}

	private static Type ResolveWorldCameraType()
	{
		if (_worldCameraType != null)
			return _worldCameraType;
		foreach (var hint in GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeHints)
		{
			_worldCameraType = GameMember.FindType(
				GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeId + "." + hint,
				hint,
				logMiss: false);
			if (_worldCameraType != null)
				return _worldCameraType;
		}
		return null;
	}

	private static Type ResolveHeroDrawerType()
	{
		if (_heroDrawerType != null)
			return _heroDrawerType;
		foreach (var hint in GameSymbols.HeroMap.DrawerTypeHints)
		{
			_heroDrawerType = GameMember.FindType(GameSymbols.HeroMap.DrawerTypeId + "." + hint, hint, logMiss: false);
			if (_heroDrawerType != null)
				return _heroDrawerType;
		}
		return null;
	}

	private static void ResolveBattleDrawerTypes()
	{
		if (_battleDrawerTypes.Count > 0)
			return;
		foreach (var hint in GameSymbols.BattleVisual.BattleDrawerTypeNames)
		{
			var type = GameMember.FindType("battle.visual.drawer." + hint, hint, logMiss: false);
			if (type != null)
				_battleDrawerTypes.Add(type);
		}
	}

	private static object GetFirstFieldValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetInheritedFieldValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object GetInheritedFieldValue(object obj, string name)
	{
		if (obj == null)
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			try
			{
				var f = t.GetField(name, MemberFlags);
				if (f != null)
					return f.GetValue(obj);
			}
			catch
			{
			}
		}
		return null;
	}

	private static object InvokeFirstNoArg(object obj, Type returnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null)
			return null;
		for (var t = obj.GetType(); t != null && t != typeof(object); t = t.BaseType)
		{
			var methods = GameMember.FindMethods(t, returnType, Type.EmptyTypes, symbol);
			for (var i = 0; i < methods.Length; i++)
			{
				try
				{
					return methods[i].Invoke(obj, null);
				}
				catch
				{
				}
			}
		}
		return null;
	}
}
